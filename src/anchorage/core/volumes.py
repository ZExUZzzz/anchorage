"""Volume table model joined with container usage."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from anchorage.core.containers import ContainerStore
from anchorage.core.engine import EngineService, EngineState
from anchorage.core.units import english_plural
from anchorage.core.workers import TaskRunner
from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.models import Container, Event, PruneResult, Volume

ROW_ROLE = Qt.ItemDataRole.UserRole + 2
SORT_ROLE = Qt.ItemDataRole.UserRole + 3
COLUMNS = (
    str(QT_TRANSLATE_NOOP("VolumeStore", "Name")),
    str(QT_TRANSLATE_NOOP("VolumeStore", "Driver")),
    str(QT_TRANSLATE_NOOP("VolumeStore", "Compose project")),
    str(QT_TRANSLATE_NOOP("VolumeStore", "Used by")),
    str(QT_TRANSLATE_NOOP("VolumeStore", "Created")),
)


@dataclass(frozen=True, slots=True)
class VolumeUse:
    container_id: str
    container_name: str
    destination: str
    state: str


@dataclass(frozen=True, slots=True)
class VolumeRow:
    volume: Volume
    users: tuple[VolumeUse, ...]

    @property
    def name(self) -> str:
        return self.volume.name

    @property
    def unused(self) -> bool:
        return not self.users


def uses_by_volume(containers: list[Container]) -> dict[str, list[VolumeUse]]:
    uses: dict[str, list[VolumeUse]] = {}
    for container in containers:
        for mount in container.mounts:
            if mount.type == "volume" and mount.name:
                uses.setdefault(mount.name, []).append(
                    VolumeUse(container.id, container.name, mount.destination, container.state)
                )
    return uses


class VolumeStore(QObject):
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
        self._volumes: list[Volume] = []
        self._rows: list[VolumeRow] = []
        self._generation = 0
        self.model = QStandardItemModel(0, len(COLUMNS), self)
        self.model.setHorizontalHeaderLabels(
            [QCoreApplication.translate("VolumeStore", name) for name in COLUMNS]
        )
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(coalesce_ms)
        self._timer.timeout.connect(self.refresh)
        if engine is not None:
            engine.state_changed.connect(self._on_engine_state)
            engine.event_received.connect(self.handle_event)
        if containers is not None:
            containers.refreshed.connect(self._rebuild)

    def _used_by(self, count: int) -> str:
        if count == 0:
            return self.tr("unused")
        return english_plural(self.tr("%n container(s)", "", count), count)

    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        self._runner.submit(
            self._api.list_volumes,
            lambda volumes: self._apply_if_current(generation, volumes),
            lambda error: self._fail_if_current(generation, error),
        )

    def rows(self) -> list[VolumeRow]:
        return list(self._rows)

    def row(self, name: str) -> VolumeRow | None:
        return next((r for r in self._rows if r.name == name), None)

    def remove(self, name: str, *, force: bool = False) -> None:
        self._runner.submit(
            lambda: self._api.remove_volume(name, force=force),
            lambda _: self.refresh(),
            lambda error: self.action_failed.emit(name, error),
        )

    def prune(self) -> None:
        def done(result: PruneResult) -> None:
            self.pruned.emit(result)
            self.refresh()

        self._runner.submit(
            self._api.prune_volumes, done, lambda e: self.action_failed.emit("prune", e)
        )

    def handle_event(self, event: Event) -> None:
        if event.type == "volume" and not self._timer.isActive():
            self._timer.start()

    def _on_engine_state(self, state: EngineState) -> None:
        if state is EngineState.CONNECTED:
            self.refresh()

    def _fail_if_current(self, generation: int, error: DockerError) -> None:
        if generation == self._generation:
            self.refresh_failed.emit(error)

    def _apply_if_current(self, generation: int, volumes: list[Volume]) -> None:
        if generation == self._generation:
            self._volumes = volumes
            self._rebuild()

    def _rebuild(self) -> None:
        containers = self._containers.containers() if self._containers is not None else []
        uses = uses_by_volume(containers)
        self._rows = [
            VolumeRow(volume, tuple(uses.get(volume.name, [])))
            for volume in sorted(self._volumes, key=lambda v: v.name.lower())
        ]
        self.model.removeRows(0, self.model.rowCount())
        for row in self._rows:
            created = (
                row.volume.created.astimezone().strftime("%Y-%m-%d %H:%M")
                if row.volume.created
                else ""
            )
            project = row.volume.compose_project or ""
            cells = [
                QStandardItem(row.name),
                QStandardItem(row.volume.driver),
                QStandardItem(project),
                QStandardItem(self._used_by(len({u.container_id for u in row.users}))),
                QStandardItem(created),
            ]
            for cell in cells:
                cell.setEditable(False)
            cells[0].setData(row, ROW_ROLE)
            cells[0].setData(row.name.lower(), SORT_ROLE)
            cells[1].setData(row.volume.driver.lower(), SORT_ROLE)
            cells[2].setData(project.lower(), SORT_ROLE)
            cells[3].setData(len({u.container_id for u in row.users}), SORT_ROLE)
            cells[4].setData(
                row.volume.created.timestamp() if row.volume.created else 0.0, SORT_ROLE
            )
            self.model.appendRow(cells)
        self.refreshed.emit()
