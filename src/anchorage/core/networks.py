"""Network table model joined with container membership."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from anchorage.core.containers import ContainerStore
from anchorage.core.engine import EngineService, EngineState
from anchorage.core.workers import TaskRunner
from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.models import Container, Event, Network, PruneResult

ROW_ROLE = Qt.ItemDataRole.UserRole + 2
SORT_ROLE = Qt.ItemDataRole.UserRole + 3
COLUMNS = ("Name", "Driver", "Scope", "Subnet", "Containers", "Internal")


@dataclass(frozen=True, slots=True)
class NetworkMember:
    container_id: str
    container_name: str
    ip: str
    state: str


@dataclass(frozen=True, slots=True)
class NetworkRow:
    network: Network
    members: tuple[NetworkMember, ...]

    @property
    def name(self) -> str:
        return self.network.name


def members_by_network(containers: list[Container]) -> dict[str, list[NetworkMember]]:
    members: dict[str, list[NetworkMember]] = {}
    for container in containers:
        for name, ip in container.networks.items():
            members.setdefault(name, []).append(
                NetworkMember(container.id, container.name, ip, container.state)
            )
    return members


class NetworkStore(QObject):
    refreshed = Signal()
    refresh_failed = Signal(object)
    action_failed = Signal(str, object)
    pruned = Signal(object)

    def __init__(
        self,
        api: EngineAPI,
        runner: TaskRunner,
        engine: EngineService | None = None,
        containers: ContainerStore | None = None,
        *,
        coalesce_ms: int = 150,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._runner = runner
        self._containers = containers
        self._networks: list[Network] = []
        self._rows: list[NetworkRow] = []
        self._generation = 0
        self.model = QStandardItemModel(0, len(COLUMNS), self)
        self.model.setHorizontalHeaderLabels(list(COLUMNS))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(coalesce_ms)
        self._timer.timeout.connect(self.refresh)
        if engine is not None:
            engine.state_changed.connect(self._on_engine_state)
            engine.event_received.connect(self.handle_event)
        if containers is not None:
            containers.refreshed.connect(self._rebuild)

    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        self._runner.submit(
            self._api.list_networks,
            lambda networks: self._apply_if_current(generation, networks),
            lambda error: self._fail_if_current(generation, error),
        )

    def rows(self) -> list[NetworkRow]:
        return list(self._rows)

    def row(self, name: str) -> NetworkRow | None:
        return next((r for r in self._rows if r.name == name), None)

    def remove(self, network_id: str) -> None:
        self._runner.submit(
            lambda: self._api.remove_network(network_id),
            lambda _: self.refresh(),
            lambda error: self.action_failed.emit(network_id, error),
        )

    def prune(self) -> None:
        def done(result: PruneResult) -> None:
            self.pruned.emit(result)
            self.refresh()

        self._runner.submit(
            self._api.prune_networks, done, lambda e: self.action_failed.emit("prune", e)
        )

    def handle_event(self, event: Event) -> None:
        if event.type == "network" and not self._timer.isActive():
            self._timer.start()

    def _on_engine_state(self, state: EngineState) -> None:
        if state is EngineState.CONNECTED:
            self.refresh()

    def _fail_if_current(self, generation: int, error: DockerError) -> None:
        if generation == self._generation:
            self.refresh_failed.emit(error)

    def _apply_if_current(self, generation: int, networks: list[Network]) -> None:
        if generation == self._generation:
            self._networks = networks
            self._rebuild()

    def _rebuild(self) -> None:
        containers = self._containers.containers() if self._containers is not None else []
        members = members_by_network(containers)
        self._rows = [
            NetworkRow(network, tuple(members.get(network.name, [])))
            for network in sorted(self._networks, key=lambda n: n.name.lower())
        ]
        self.model.removeRows(0, self.model.rowCount())
        for row in self._rows:
            net = row.network
            subnet = ", ".join(s.subnet for s in net.subnets) or "—"
            cells = [
                QStandardItem(row.name),
                QStandardItem(net.driver),
                QStandardItem(net.scope),
                QStandardItem(subnet),
                QStandardItem(str(len(row.members))),
                QStandardItem("yes" if net.internal else "no"),
            ]
            for cell in cells:
                cell.setEditable(False)
            cells[0].setData(row, ROW_ROLE)
            cells[0].setData(row.name.lower(), SORT_ROLE)
            cells[1].setData(net.driver.lower(), SORT_ROLE)
            cells[2].setData(net.scope.lower(), SORT_ROLE)
            cells[3].setData(subnet.lower(), SORT_ROLE)
            cells[4].setData(len(row.members), SORT_ROLE)
            cells[5].setData(int(net.internal), SORT_ROLE)
            self.model.appendRow(cells)
        self.refreshed.emit()
