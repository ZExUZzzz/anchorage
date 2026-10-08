from PySide6.QtCore import QObject

from anchorage.core.containers import (
    BUSY_ROLE,
    CONTAINER_ROLE,
    GROUP_ROLE,
    ID_ROLE,
    KIND_ROLE,
    STANDALONE_GROUP,
    ContainerStore,
)
from anchorage.core.workers import TaskRunner
from anchorage.docker.errors import Conflict, NotFound
from tests.core.fakes import DeferredRunner, FakeEngine, make_container, make_event


class Failures(QObject):
    def __init__(self, store: ContainerStore) -> None:
        super().__init__()
        self.failed: list[tuple[str, str]] = []
        store.action_failed.connect(self.on_failed)

    def on_failed(self, container_id: str, error) -> None:  # type: ignore[no-untyped-def]
        self.failed.append((container_id, error.message))


def make_store(engine: FakeEngine, coalesce_ms: int = 10) -> ContainerStore:
    return ContainerStore(engine, TaskRunner(inline=True), coalesce_ms=coalesce_ms)


def tree(store: ContainerStore) -> list[tuple[str, list[str]]]:
    model = store.model
    out = []
    for row in range(model.rowCount()):
        group = model.item(row)
        out.append((group.text(), [group.child(i).text() for i in range(group.rowCount())]))
    return out


def test_refresh_groups_by_compose_project() -> None:
    engine = FakeEngine()
    engine.add(
        make_container("pulse-nginx-1", project="pulse", service="nginx"),
        make_container("pulse-db-1", project="pulse", service="db", state="exited"),
        make_container("zed", project="acme"),
        make_container("solo"),
        make_container("alpha"),
    )
    store = make_store(engine)
    store.refresh()
    assert tree(store) == [
        ("acme", ["zed"]),
        ("pulse", ["pulse-db-1", "pulse-nginx-1"]),
        (STANDALONE_GROUP, ["alpha", "solo"]),
    ]
    group = store.model.item(1)
    assert group.data(KIND_ROLE) == "group"
    summary = group.data(GROUP_ROLE)
    assert (summary.name, summary.total, summary.running, summary.standalone) == (
        "pulse",
        2,
        1,
        False,
    )
    assert store.model.item(2).data(GROUP_ROLE).standalone is True
    child = group.child(1)
    assert child.data(KIND_ROLE) == "container"
    assert child.data(CONTAINER_ROLE).name == "pulse-nginx-1"
    assert child.data(ID_ROLE) == child.data(CONTAINER_ROLE).id
    assert child.data(BUSY_ROLE) is False
    assert [c.name for c in store.containers()] == [
        "zed",
        "pulse-db-1",
        "pulse-nginx-1",
        "alpha",
        "solo",
    ]


def test_refresh_updates_rows_in_place() -> None:
    engine = FakeEngine()
    nginx = make_container("pulse-nginx-1", project="pulse")
    engine.add(nginx, make_container("solo"))
    store = make_store(engine)
    store.refresh()
    item = store.model.item(0).child(0)
    engine.containers[nginx.id] = make_container(
        "pulse-nginx-1", project="pulse", state="exited", container_id=nginx.id
    )
    store.refresh()
    assert store.model.item(0).child(0) is item
    assert item.data(CONTAINER_ROLE).state == "exited"
    assert store.model.item(0).data(GROUP_ROLE).running == 0


def test_removed_container_and_empty_group_disappear() -> None:
    engine = FakeEngine()
    only = make_container("only", project="acme")
    engine.add(only, make_container("solo"))
    store = make_store(engine)
    store.refresh()
    del engine.containers[only.id]
    store.refresh()
    assert tree(store) == [(STANDALONE_GROUP, ["solo"])]
    assert store.container(only.id) is None


def test_container_moves_between_groups_and_renames() -> None:
    engine = FakeEngine()
    c = make_container("mover", project="acme")
    engine.add(c, make_container("anchor", project="acme"), make_container("beta", project="pulse"))
    store = make_store(engine)
    store.refresh()
    engine.containers[c.id] = make_container("aaa-mover", project="pulse", container_id=c.id)
    store.refresh()
    assert tree(store) == [("acme", ["anchor"]), ("pulse", ["aaa-mover", "beta"])]
    assert len(store.containers()) == 3


def test_new_group_inserted_in_sorted_position() -> None:
    engine = FakeEngine()
    engine.add(
        make_container("a", project="alpha"),
        make_container("z", project="zulu"),
        make_container("s"),
    )
    store = make_store(engine)
    store.refresh()
    engine.add(make_container("m", project="mike"))
    store.refresh()
    assert [name for name, _ in tree(store)] == ["alpha", "mike", "zulu", STANDALONE_GROUP]


def test_events_coalesce_into_one_refresh(qtbot) -> None:
    engine = FakeEngine()
    engine.add(make_container("solo"))
    store = make_store(engine, coalesce_ms=30)
    store.refresh()
    calls_before = len(engine.calls_to("list_containers"))
    for action in ("create", "start", "die", "health_status: healthy"):
        store.handle_event(make_event(action, "abc"))
    store.handle_event(make_event("exec_create: sh", "abc"))
    assert len(engine.calls_to("list_containers")) == calls_before
    qtbot.waitUntil(
        lambda: len(engine.calls_to("list_containers")) == calls_before + 1, timeout=2000
    )
    qtbot.wait(60)
    assert len(engine.calls_to("list_containers")) == calls_before + 1


def test_image_events_are_ignored(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine, coalesce_ms=10)
    store.refresh()
    before = len(engine.calls_to("list_containers"))
    store.handle_event(make_event("pull", "nginx", kind="image"))
    qtbot.wait(50)
    assert len(engine.calls_to("list_containers")) == before


def test_actions_mark_busy_until_call_returns() -> None:
    engine = FakeEngine()
    c = make_container("solo")
    engine.add(c)
    runner = DeferredRunner()
    store = ContainerStore(engine, runner)
    store.refresh()
    runner.run_pending()
    store.stop(c.id)
    assert store.is_busy(c.id) is True
    assert store.model.item(0).child(0).data(BUSY_ROLE) is True
    store.stop(c.id)
    assert len(runner.pending) == 1
    store.handle_event(make_event("kill", c.id))
    runner.run_pending()
    assert engine.calls_to("stop_container")[0][1] == (c.id,)
    assert len(engine.calls_to("stop_container")) == 1
    assert store.is_busy(c.id) is False
    assert store.model.item(0).child(0).data(BUSY_ROLE) is False
    before = len(engine.calls_to("list_containers"))
    runner.run_pending()
    assert len(engine.calls_to("list_containers")) == before + 1


def test_action_error_clears_busy_and_reports() -> None:
    engine = FakeEngine()
    c = make_container("solo")
    engine.add(c)
    engine.errors["remove_container"] = Conflict("container is running", 409)
    store = make_store(engine)
    failures = Failures(store)
    store.refresh()
    store.remove(c.id)
    assert store.is_busy(c.id) is False
    assert failures.failed == [(c.id, "container is running")]
    store.remove(c.id, force=True)
    assert engine.calls_to("remove_container")[-1][2] == {"force": True, "volumes": False}


def test_start_restart_call_api() -> None:
    engine = FakeEngine()
    c = make_container("solo", state="exited")
    engine.add(c)
    store = make_store(engine)
    store.refresh()
    store.start(c.id)
    assert store.is_busy(c.id) is False
    store.restart(c.id)
    assert [call[0] for call in engine.calls if call[0].endswith("_container")] == [
        "start_container",
        "restart_container",
    ]


def move_both_ways(from_project: str | None, to_project: str | None) -> None:
    engine = FakeEngine()
    mover = make_container("mover", project=from_project)
    engine.add(
        mover,
        make_container("a-stay", project=from_project),
        make_container("b-stay", project=to_project),
    )
    store = make_store(engine)
    store.refresh()
    item = store._items[mover.id]
    store._set_busy(mover.id, True)
    engine.containers[mover.id] = make_container("mover", project=to_project, container_id=mover.id)
    store.refresh()
    assert store._items[mover.id] is item
    assert item.parent().data(GROUP_ROLE).standalone is (to_project is None)
    assert item.data(BUSY_ROLE) is True
    assert store.is_busy(mover.id) is True


def test_move_to_later_group_keeps_item_and_busy() -> None:
    move_both_ways("acme", "pulse")


def test_move_to_earlier_group_keeps_item_and_busy() -> None:
    move_both_ways("pulse", "acme")


def test_move_out_of_vanishing_group_keeps_item_and_busy() -> None:
    engine = FakeEngine()
    mover = make_container("mover", project="acme")
    engine.add(mover, make_container("other", project="pulse"))
    store = make_store(engine)
    store.refresh()
    item = store._items[mover.id]
    store._set_busy(mover.id, True)
    engine.containers[mover.id] = make_container("mover", project="pulse", container_id=mover.id)
    store.refresh()
    assert tree(store) == [("pulse", ["mover", "other"])]
    assert store._items[mover.id] is item
    assert item.data(BUSY_ROLE) is True


def test_rename_reorders_same_item() -> None:
    engine = FakeEngine()
    c = make_container("alpha", project="acme")
    engine.add(c, make_container("beta", project="acme"))
    store = make_store(engine)
    store.refresh()
    item = store.model.item(0).child(0)
    engine.containers[c.id] = make_container("zeta", project="acme", container_id=c.id)
    store.refresh()
    assert tree(store) == [("acme", ["beta", "zeta"])]
    assert store.model.item(0).child(1) is item
    assert item.row() == 1


def test_stale_refresh_result_is_dropped() -> None:
    engine = FakeEngine()
    engine.add(make_container("old"))
    runner = DeferredRunner()
    store = ContainerStore(engine, runner)
    store.refresh()
    engine.containers.clear()
    engine.add(make_container("new"))
    store.refresh()
    runner.run_pending(reverse=True)
    assert tree(store) == [(STANDALONE_GROUP, ["new"])]


def test_steady_event_stream_does_not_postpone_refresh(qtbot) -> None:
    engine = FakeEngine()
    store = make_store(engine, coalesce_ms=30)
    for _ in range(20):
        store.handle_event(make_event("health_status: healthy", "abc"))
        qtbot.wait(5)
    assert len(engine.calls_to("list_containers")) >= 2
    qtbot.wait(60)


class DetailsWatcher(QObject):
    def __init__(self, store: ContainerStore) -> None:
        super().__init__()
        self.ready: list[tuple[str, object]] = []
        self.failed: list[tuple[str, object]] = []
        store.details_ready.connect(self.on_ready)
        store.details_failed.connect(self.on_failed)

    def on_ready(self, container_id: str, details: object) -> None:
        self.ready.append((container_id, details))

    def on_failed(self, container_id: str, error: object) -> None:
        self.failed.append((container_id, error))


def test_inspect_emits_details() -> None:
    engine = FakeEngine()
    c = make_container("solo")
    engine.add(c)
    store = make_store(engine)
    watcher = DetailsWatcher(store)
    store.inspect(c.id)
    assert [(cid, d.name) for cid, d in watcher.ready] == [(c.id, "solo")]  # type: ignore[attr-defined]
    assert watcher.failed == []


def test_inspect_reports_not_found() -> None:
    store = make_store(FakeEngine())
    watcher = DetailsWatcher(store)
    store.inspect("missing")
    assert watcher.ready == []
    assert len(watcher.failed) == 1
    container_id, error = watcher.failed[0]
    assert container_id == "missing"
    assert isinstance(error, NotFound)


def test_stale_inspect_result_is_dropped() -> None:
    engine = FakeEngine()
    c = make_container("solo")
    engine.add(c)
    runner = DeferredRunner()
    store = ContainerStore(engine, runner)
    watcher = DetailsWatcher(store)
    store.inspect(c.id)
    engine.containers[c.id] = make_container("renamed", container_id=c.id)
    store.inspect(c.id)
    runner.run_pending(reverse=True)
    assert [d.name for _, d in watcher.ready] == ["renamed"]  # type: ignore[attr-defined]


def test_inspect_generations_are_per_container() -> None:
    engine = FakeEngine()
    a, b = make_container("a"), make_container("b")
    engine.add(a, b)
    runner = DeferredRunner()
    store = ContainerStore(engine, runner)
    watcher = DetailsWatcher(store)
    store.inspect(a.id)
    store.inspect(b.id)
    runner.run_pending()
    assert sorted(cid for cid, _ in watcher.ready) == sorted([a.id, b.id])


class ChangeCounter(QObject):
    def __init__(self, store: ContainerStore) -> None:
        super().__init__()
        self.count = 0
        store.model.dataChanged.connect(self.on_changed)

    def on_changed(self) -> None:
        self.count += 1


def test_identical_refresh_emits_no_data_changed() -> None:
    engine = FakeEngine()
    engine.add(
        make_container("a", project="acme"),
        make_container("b", project="acme", state="exited"),
        make_container("solo"),
    )
    store = make_store(engine)
    store.refresh()
    counter = ChangeCounter(store)
    store.refresh()
    assert counter.count == 0
    engine.add(make_container("solo", state="exited"))
    store.refresh()
    assert counter.count > 0
