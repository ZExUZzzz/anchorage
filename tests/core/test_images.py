from PySide6.QtCore import QObject

from anchorage.core.images import COLUMNS, IMAGE_ROLE, ROW_ROLE, SORT_ROLE, ImageStore, PullJob
from anchorage.core.workers import TaskRunner
from anchorage.docker.errors import Conflict
from anchorage.docker.models import PullProgress
from tests.core.fakes import DeferredRunner, FakeEngine, make_event, make_image


class Watcher(QObject):
    def __init__(self, store: ImageStore) -> None:
        super().__init__()
        self.failed: list[tuple[str, str]] = []
        self.pruned: list[int] = []
        store.action_failed.connect(self.on_failed)
        store.pruned.connect(self.on_pruned)

    def on_failed(self, reference: str, error) -> None:  # type: ignore[no-untyped-def]
        self.failed.append((reference, error.message))

    def on_pruned(self, result) -> None:  # type: ignore[no-untyped-def]
        self.pruned.append(result.space_reclaimed)


class JobWatcher(QObject):
    def __init__(self, job: PullJob) -> None:
        super().__init__()
        self.progress: list[str] = []
        self.finished: list[object] = []
        job.progress.connect(self.on_progress)
        job.finished.connect(self.on_finished)

    def on_progress(self, item) -> None:  # type: ignore[no-untyped-def]
        self.progress.append(item.status)

    def on_finished(self, error: object) -> None:
        self.finished.append(error)


def make_store(engine: FakeEngine, coalesce_ms: int = 10) -> ImageStore:
    return ImageStore(engine, TaskRunner(inline=True), coalesce_ms=coalesce_ms)


def cells(store: ImageStore) -> list[list[str]]:
    model = store.model
    return [
        [model.item(r, c).text() for c in range(model.columnCount())]
        for r in range(model.rowCount())
    ]


def test_refresh_builds_one_row_per_tag() -> None:
    engine = FakeEngine()
    engine.images = [
        make_image(
            ("nginx:alpine", "nginx:1.27-alpine"),
            size=48_300_000,
            image_id="sha256:" + "7a2c1f" + "0" * 58,
        ),
        make_image((), size=801_000_000, image_id="sha256:" + "5e7d02" + "0" * 58),
        make_image(("ghcr.io/acme/api:1.4.2",), size=10),
    ]
    store = make_store(engine)
    store.refresh()
    assert COLUMNS == ("Repository", "Tag", "ID", "Size", "Created")
    stamp = engine.images[0].created.astimezone().strftime("%Y-%m-%d %H:%M")
    assert cells(store) == [
        ["<none>", "<none>", "5e7d02000000", "763.9 MB", stamp],
        ["ghcr.io/acme/api", "1.4.2", engine.images[2].short_id, "10 B", stamp],
        ["nginx", "1.27-alpine", "7a2c1f000000", "46.1 MB", stamp],
        ["nginx", "alpine", "7a2c1f000000", "46.1 MB", stamp],
    ]
    rows = store.rows()
    assert [r.reference for r in rows][2:] == ["nginx:1.27-alpine", "nginx:alpine"]
    assert rows[0].reference.startswith("sha256:")
    assert store.model.item(2, 0).data(IMAGE_ROLE).size == 48_300_000
    assert store.model.item(2, 0).data(ROW_ROLE).tag == "1.27-alpine"
    assert store.model.item(2, 3).data(SORT_ROLE) == 48_300_000
    assert store.row("nginx:alpine") is not None
    assert store.row("missing:tag") is None


def test_image_events_coalesce_into_refresh(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine, coalesce_ms=30)
    store.refresh()
    before = len(engine.calls_to("list_images"))
    store.handle_event(make_event("pull", "nginx:alpine", kind="image"))
    store.handle_event(make_event("delete", "sha256:x", kind="image"))
    store.handle_event(make_event("start", "abc"))
    assert len(engine.calls_to("list_images")) == before
    qtbot.waitUntil(lambda: len(engine.calls_to("list_images")) == before + 1, timeout=2000)
    qtbot.wait(60)
    assert len(engine.calls_to("list_images")) == before + 1


def test_remove_and_prune() -> None:
    engine = FakeEngine()
    engine.images = [make_image(("nginx:alpine",))]
    store = make_store(engine)
    watcher = Watcher(store)
    store.refresh()
    store.remove("nginx:alpine")
    assert engine.calls_to("remove_image")[0][1:] == (("nginx:alpine",), {"force": False})
    assert len(engine.calls_to("list_images")) == 2
    engine.errors["remove_image"] = Conflict("image is in use", 409)
    store.remove("nginx:alpine", force=True)
    assert watcher.failed == [("nginx:alpine", "image is in use")]
    store.prune()
    assert engine.calls_to("prune_images")[0][2] == {"dangling_only": True}
    assert watcher.pruned == [4096]
    assert len(engine.calls_to("list_images")) == 3


def test_pull_job_tracks_layers_and_refreshes(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine)
    store.refresh()
    job = store.pull("nginx", "alpine")
    watcher = JobWatcher(job)
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    feed = engine.pull_feeds[0]
    feed.put(PullProgress(status="Pulling from library/nginx"))
    feed.put(PullProgress(status="Downloading", layer_id="aa", current=10, total=40))
    feed.put(PullProgress(status="Downloading", layer_id="bb", current=0, total=10))
    feed.put(PullProgress(status="Pull complete", layer_id="aa"))
    qtbot.waitUntil(lambda: len(watcher.progress) == 4, timeout=2000)
    assert job.status == "Pulling from library/nginx"
    assert list(job.layers) == ["aa", "bb"]
    assert job.layers["aa"].status == "Pull complete"
    assert job.layers["aa"].fraction == 1.0
    assert job.layers["bb"].fraction == 0.0
    before = len(engine.calls_to("list_images"))
    feed.end()
    qtbot.waitUntil(lambda: watcher.finished == [None], timeout=2000)
    assert job.done is True
    assert job.error is None
    qtbot.waitUntil(lambda: len(engine.calls_to("list_images")) == before + 1, timeout=2000)
    assert engine.calls_to("pull_image")[0][1] == ("nginx", "alpine")


def test_pull_job_reports_error_and_cancel(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine)
    job = store.pull("nginx")
    watcher = JobWatcher(job)
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    engine.pull_feeds[0].fail(Conflict("manifest unknown", 409))
    qtbot.waitUntil(lambda: len(watcher.finished) == 1, timeout=2000)
    assert job.error is not None
    assert job.error.message == "manifest unknown"

    job2 = store.pull("redis")
    watcher2 = JobWatcher(job2)
    job2.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 2, timeout=2000)
    job2.cancel()
    qtbot.waitUntil(lambda: watcher2.finished == [None], timeout=2000)
    assert engine.pull_feeds[1].closed


def test_pull_job_stop_cancels_and_is_single_use(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine)
    job = store.pull("nginx")
    assert job.cancelled is False
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    assert job.stop() is True
    assert job.cancelled is True
    assert engine.pull_feeds[0].closed
    job.start()
    assert len(engine.calls_to("pull_image")) == 1


def test_pull_stop_while_pending(qtbot) -> None:
    # The daemon has not answered yet: the stream is open but yields nothing.
    engine = FakeEngine()
    store = make_store(engine)
    job = store.pull("nginx")
    watcher = JobWatcher(job)
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    qtbot.wait(100)
    assert watcher.progress == []
    assert job.stop(200) is True
    assert engine.pull_feeds[0].closed
    qtbot.waitUntil(lambda: watcher.finished == [None], timeout=2000)


def test_cancelled_job_does_not_start() -> None:
    engine = FakeEngine()
    job = make_store(engine).pull("nginx")
    job.cancel()
    job.start()
    assert engine.calls_to("pull_image") == []


def test_store_shutdown_stops_live_jobs(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine)
    first, second = store.pull("nginx"), store.pull("redis")
    watchers = [JobWatcher(first), JobWatcher(second)]
    first.start()
    second.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 2, timeout=2000)
    assert store.shutdown() is True
    assert all(feed.closed for feed in engine.pull_feeds)
    qtbot.waitUntil(lambda: all(w.finished == [None] for w in watchers), timeout=2000)
    assert store._jobs == []


def test_steady_event_stream_does_not_postpone_refresh(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine, coalesce_ms=30)
    for _ in range(20):
        store.handle_event(make_event("tag", "nginx", kind="image"))
        qtbot.wait(5)
    assert len(engine.calls_to("list_images")) >= 2
    qtbot.wait(60)


def test_stale_refresh_result_is_dropped() -> None:
    engine = FakeEngine()
    engine.images = [make_image(("old:1",))]
    runner = DeferredRunner()
    store = ImageStore(engine, runner)
    store.refresh()
    engine.images = [make_image(("new:1",))]
    store.refresh()
    runner.run_pending(reverse=True)
    assert [r.reference for r in store.rows()] == ["new:1"]


def test_every_cell_has_sort_role() -> None:
    engine = FakeEngine()
    engine.images = [make_image(("Nginx/App:V1",), size=500, image_id="sha256:AB" + "0" * 62)]
    store = make_store(engine)
    store.refresh()
    image = engine.images[0]
    assert [store.model.item(0, c).data(SORT_ROLE) for c in range(5)] == [
        "nginx/app",
        "v1",
        image.short_id.lower(),
        500,
        image.created.timestamp(),
    ]
