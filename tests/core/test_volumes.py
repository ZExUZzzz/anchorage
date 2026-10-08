from PySide6.QtCore import QObject, Qt

from anchorage.core.volumes import COLUMNS, ROW_ROLE, VolumeStore, uses_by_volume
from anchorage.core.workers import TaskRunner
from anchorage.docker.errors import Conflict
from tests.core.fakes import FakeEngine, make_container, make_event, make_volume


class Watcher(QObject):
    def __init__(self, store: VolumeStore) -> None:
        super().__init__()
        self.failed: list[tuple[str, str]] = []
        self.pruned: list[int] = []
        self.refreshes = 0
        store.action_failed.connect(self.on_failed)
        store.pruned.connect(self.on_pruned)
        store.refreshed.connect(self.on_refreshed)

    def on_failed(self, target: str, error) -> None:  # type: ignore[no-untyped-def]
        self.failed.append((target, error.message))

    def on_pruned(self, result) -> None:  # type: ignore[no-untyped-def]
        self.pruned.append(result.space_reclaimed)

    def on_refreshed(self) -> None:
        self.refreshes += 1


def seeded(engine: FakeEngine) -> None:
    engine.volumes = [
        make_volume("pulse_dbdata", project="pulse"),
        make_volume("orphan"),
        make_volume("old_cache"),
    ]
    engine.add(
        make_container("pulse-db-1", project="pulse", volumes={"pulse_dbdata": "/var/lib/mysql"}),
        make_container("stopped", state="exited", volumes={"old_cache": "/cache"}),
    )


def cells(store: VolumeStore) -> list[list[str]]:
    m = store.model
    return [[m.item(r, c).text() for c in range(m.columnCount())] for r in range(m.rowCount())]


def test_uses_by_volume_counts_stopped_containers() -> None:
    engine = FakeEngine()
    seeded(engine)
    uses = uses_by_volume(engine.list_containers())
    assert [u.container_name for u in uses["pulse_dbdata"]] == ["pulse-db-1"]
    assert uses["old_cache"][0].state == "exited"
    assert "orphan" not in uses


def test_store_joins_volumes_with_container_usage(qtbot) -> None:
    engine = FakeEngine()
    seeded(engine)
    from anchorage.core.containers import ContainerStore

    runner = TaskRunner(inline=True)
    containers = ContainerStore(engine, runner)
    store = VolumeStore(engine, runner, containers=containers)
    containers.refresh()
    store.refresh()
    assert COLUMNS == ("Name", "Driver", "Compose project", "Used by", "Created")
    assert cells(store) == [
        [
            "old_cache",
            "local",
            "",
            "1 container",
            store.rows()[0].volume.created.astimezone().strftime("%Y-%m-%d %H:%M"),
        ],
        [
            "orphan",
            "local",
            "",
            "unused",
            store.rows()[1].volume.created.astimezone().strftime("%Y-%m-%d %H:%M"),
        ],
        [
            "pulse_dbdata",
            "local",
            "pulse",
            "1 container",
            store.rows()[2].volume.created.astimezone().strftime("%Y-%m-%d %H:%M"),
        ],
    ]
    row = store.row("pulse_dbdata")
    assert row is not None and row.users[0].destination == "/var/lib/mysql" and not row.unused
    assert store.row("orphan").unused is True
    assert store.model.item(2, 0).data(ROW_ROLE) is row
    assert store.model.item(2, 3).data(Qt.ItemDataRole.UserRole + 3) == 1


def test_container_refresh_rebuilds_usage_without_listing_volumes(qtbot) -> None:
    engine = FakeEngine()
    seeded(engine)
    from anchorage.core.containers import ContainerStore

    runner = TaskRunner(inline=True)
    containers = ContainerStore(engine, runner)
    store = VolumeStore(engine, runner, containers=containers)
    watcher = Watcher(store)
    containers.refresh()
    store.refresh()
    before = len(engine.calls_to("list_volumes"))
    del engine.containers[next(c.id for c in engine.containers.values() if c.name == "pulse-db-1")]
    containers.refresh()
    assert store.row("pulse_dbdata").unused is True
    assert len(engine.calls_to("list_volumes")) == before
    assert watcher.refreshes >= 2


def test_events_coalesce_and_actions(qtbot) -> None:
    engine = FakeEngine()
    seeded(engine)
    store = VolumeStore(engine, TaskRunner(inline=True), coalesce_ms=30)
    watcher = Watcher(store)
    store.refresh()
    before = len(engine.calls_to("list_volumes"))
    store.handle_event(make_event("create", "v1", kind="volume"))
    store.handle_event(make_event("destroy", "v2", kind="volume"))
    store.handle_event(make_event("start", "abc"))
    qtbot.waitUntil(lambda: len(engine.calls_to("list_volumes")) == before + 1, timeout=2000)
    store.remove("orphan")
    assert engine.calls_to("remove_volume")[0][1:] == (("orphan",), {"force": False})
    engine.errors["remove_volume"] = Conflict("volume is in use", 409)
    store.remove("pulse_dbdata", force=True)
    assert watcher.failed == [("pulse_dbdata", "volume is in use")]
    store.prune()
    assert engine.calls_to("prune_volumes")
    assert watcher.pruned == [2048]


def test_used_by_counts_distinct_containers(qtbot) -> None:
    from dataclasses import replace

    from anchorage.core.containers import ContainerStore
    from anchorage.core.volumes import SORT_ROLE

    engine = FakeEngine()
    engine.volumes = [make_volume("shared")]
    app = make_container("app", volumes={"shared": "/a"})
    engine.add(replace(app, mounts=(*app.mounts, replace(app.mounts[0], destination="/b"))))
    runner = TaskRunner(inline=True)
    containers = ContainerStore(engine, runner)
    store = VolumeStore(engine, runner, containers=containers)
    containers.refresh()
    store.refresh()
    assert len(store.rows()[0].users) == 2
    assert store.model.item(0, 3).text() == "1 container"
    assert store.model.item(0, 3).data(SORT_ROLE) == 1
