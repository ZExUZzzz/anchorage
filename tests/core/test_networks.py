from anchorage.core.containers import ContainerStore
from anchorage.core.networks import COLUMNS, ROW_ROLE, NetworkStore, members_by_network
from anchorage.core.workers import TaskRunner
from tests.core.fakes import FakeEngine, make_container, make_event, make_network


def seeded(engine: FakeEngine) -> None:
    engine.networks = [
        make_network("pulse_default", project="pulse"),
        make_network("bridge", subnet="172.17.0.0/16", gateway="172.17.0.1"),
        make_network("host", subnet=None, driver="host"),
    ]
    engine.add(
        make_container("pulse-nginx-1", project="pulse", networks={"pulse_default": "172.18.0.5"}),
        make_container(
            "pulse-db-1", project="pulse", state="exited", networks={"pulse_default": ""}
        ),
    )


def cells(store: NetworkStore) -> list[list[str]]:
    m = store.model
    return [[m.item(r, c).text() for c in range(m.columnCount())] for r in range(m.rowCount())]


def test_members_by_network() -> None:
    engine = FakeEngine()
    seeded(engine)
    members = members_by_network(engine.list_containers())
    assert [(m.container_name, m.ip, m.state) for m in members["pulse_default"]] == [
        ("pulse-nginx-1", "172.18.0.5", "running"),
        ("pulse-db-1", "", "exited"),
    ]


def test_store_rows_and_cells(qtbot) -> None:
    engine = FakeEngine()
    seeded(engine)
    runner = TaskRunner(inline=True)
    containers = ContainerStore(engine, runner)
    store = NetworkStore(engine, runner, containers=containers)
    containers.refresh()
    store.refresh()
    assert COLUMNS == ("Name", "Driver", "Scope", "Subnet", "Containers", "Internal")
    assert cells(store) == [
        ["bridge", "bridge", "local", "172.17.0.0/16", "0", "no"],
        ["host", "host", "local", "—", "0", "no"],
        ["pulse_default", "bridge", "local", "172.18.0.0/16", "2", "no"],
    ]
    row = store.row("pulse_default")
    assert row is not None and len(row.members) == 2
    assert store.model.item(2, 0).data(ROW_ROLE) is row


def test_network_events_and_actions(qtbot) -> None:
    engine = FakeEngine()
    seeded(engine)
    store = NetworkStore(engine, TaskRunner(inline=True), coalesce_ms=30)
    store.refresh()
    before = len(engine.calls_to("list_networks"))
    store.handle_event(make_event("create", "n1", kind="network"))
    qtbot.waitUntil(lambda: len(engine.calls_to("list_networks")) == before + 1, timeout=2000)
    store.remove(store.row("bridge").network.id)
    assert engine.calls_to("remove_network")[0][1] == (store.row("bridge").network.id,)
    store.prune()
    assert engine.calls_to("prune_networks")
