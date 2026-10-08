"""Container list as a grouped item model, kept current from daemon events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from anchorage.core.engine import EngineService, EngineState
from anchorage.core.workers import TaskRunner
from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.models import Container, ContainerDetails, Event

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
CONTAINER_ROLE = Qt.ItemDataRole.UserRole + 2
GROUP_ROLE = Qt.ItemDataRole.UserRole + 3
BUSY_ROLE = Qt.ItemDataRole.UserRole + 4
ID_ROLE = Qt.ItemDataRole.UserRole + 5

STANDALONE_GROUP = "Standalone"


@dataclass(frozen=True, slots=True)
class GroupSummary:
    name: str
    total: int
    running: int
    standalone: bool


def _group_key(container: Container) -> str:
    return container.compose_project or ""


def _sorted_keys(keys: set[str]) -> list[str]:
    return sorted(keys, key=lambda k: (k == "", k.lower()))


class ContainerStore(QObject):
    """Tree model: one top-level row per Compose project, containers as children.

    Rows are updated in place and keyed by container ID so view state survives refreshes.
    Actions mark a row busy until the API call returns; then the row refreshes.
    """

    refreshed = Signal()
    refresh_failed = Signal(object)
    action_failed = Signal(str, object)
    details_ready = Signal(str, object)
    details_failed = Signal(str, object)
    busy_changed = Signal(str, bool)

    def __init__(
        self,
        api: EngineAPI,
        runner: TaskRunner,
        engine: EngineService | None = None,
        *,
        coalesce_ms: int = 150,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._runner = runner
        self._generation = 0
        self._inspect_generations: dict[str, int] = {}
        self.model = QStandardItemModel(self)
        self._groups: dict[str, QStandardItem] = {}
        self._items: dict[str, QStandardItem] = {}
        self._busy: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(coalesce_ms)
        self._timer.timeout.connect(self.refresh)
        if engine is not None:
            engine.state_changed.connect(self._on_engine_state)
            engine.event_received.connect(self.handle_event)

    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        self._runner.submit(
            self._api.list_containers,
            lambda containers: self._apply_if_current(generation, containers),
            self.refresh_failed.emit,
        )

    def inspect(self, container_id: str) -> None:
        generation = self._inspect_generations.get(container_id, 0) + 1
        self._inspect_generations[container_id] = generation
        self._runner.submit(
            lambda: self._api.inspect_container(container_id),
            lambda details: self._details_if_current(container_id, generation, details),
            lambda error: self._details_failed_if_current(container_id, generation, error),
        )

    def _details_if_current(
        self, container_id: str, generation: int, details: ContainerDetails
    ) -> None:
        if self._inspect_generations.get(container_id) == generation:
            self.details_ready.emit(container_id, details)

    def _details_failed_if_current(
        self, container_id: str, generation: int, error: DockerError
    ) -> None:
        if self._inspect_generations.get(container_id) == generation:
            self.details_failed.emit(container_id, error)

    def _apply_if_current(self, generation: int, containers: list[Container]) -> None:
        if generation == self._generation:
            self._apply(containers)

    def container(self, container_id: str) -> Container | None:
        item = self._items.get(container_id)
        if item is None:
            return None
        container: Container = item.data(CONTAINER_ROLE)
        return container

    def containers(self) -> list[Container]:
        out: list[Container] = []
        for row in range(self.model.rowCount()):
            group = self.model.item(row)
            for child in range(group.rowCount()):
                out.append(group.child(child).data(CONTAINER_ROLE))
        return out

    def is_busy(self, container_id: str) -> bool:
        return container_id in self._busy

    def start(self, container_id: str) -> None:
        self._action(container_id, lambda: self._api.start_container(container_id))

    def stop(self, container_id: str) -> None:
        self._action(container_id, lambda: self._api.stop_container(container_id))

    def restart(self, container_id: str) -> None:
        self._action(container_id, lambda: self._api.restart_container(container_id))

    def remove(self, container_id: str, *, force: bool = False) -> None:
        self._action(container_id, lambda: self._api.remove_container(container_id, force=force))

    def handle_event(self, event: Event) -> None:
        if event.type != "container" or event.action.startswith("exec_"):
            return
        if not self._timer.isActive():
            self._timer.start()

    def _on_engine_state(self, state: EngineState) -> None:
        if state is EngineState.CONNECTED:
            self.refresh()

    def _action(self, container_id: str, fn: Callable[[], None]) -> None:
        if container_id in self._busy:
            return
        self._set_busy(container_id, True)

        def failed(error: DockerError) -> None:
            self._set_busy(container_id, False)
            self.action_failed.emit(container_id, error)

        def succeeded(_: object) -> None:
            self._set_busy(container_id, False)
            self.refresh()

        self._runner.submit(fn, succeeded, failed)

    def _set_busy(self, container_id: str, busy: bool) -> None:
        if busy:
            self._busy.add(container_id)
        else:
            self._busy.discard(container_id)
        item = self._items.get(container_id)
        if item is not None:
            item.setData(busy, BUSY_ROLE)
        self.busy_changed.emit(container_id, busy)

    def _apply(self, containers: list[Container]) -> None:
        grouped: dict[str, list[Container]] = {}
        for container in containers:
            grouped.setdefault(_group_key(container), []).append(container)

        wanted = {c.id for c in containers}
        for key in list(self._groups):
            if key not in grouped:
                gone = self._groups.pop(key)
                for row in reversed(range(gone.rowCount())):
                    container_id = gone.child(row).data(ID_ROLE)
                    if container_id in wanted:
                        gone.takeRow(row)
                    else:
                        self._items.pop(container_id, None)
                        self._busy.discard(container_id)
                self.model.removeRow(gone.row())

        for index, key in enumerate(_sorted_keys(set(grouped))):
            existing = self._groups.get(key)
            if existing is None:
                group = QStandardItem()
                group.setEditable(False)
                group.setData("group", KIND_ROLE)
                self._groups[key] = group
                self.model.insertRow(index, group)
            else:
                group = existing
                if group.row() != index:
                    self.model.insertRow(index, self.model.takeRow(group.row()))
            self._sync_group(group, key, sorted(grouped[key], key=lambda c: c.name.lower()), wanted)
        self.refreshed.emit()

    def _sync_group(
        self,
        group: QStandardItem,
        key: str,
        containers: list[Container],
        wanted: set[str],
    ) -> None:
        for row in reversed(range(group.rowCount())):
            container_id = group.child(row).data(ID_ROLE)
            if container_id not in wanted:
                group.removeRow(row)
                self._items.pop(container_id, None)
                self._busy.discard(container_id)

        for index, container in enumerate(containers):
            item = self._items.get(container.id)
            if item is None:
                item = QStandardItem()
                item.setEditable(False)
                item.setData("container", KIND_ROLE)
                item.setData(container.id, ID_ROLE)
                self._items[container.id] = item
                group.insertRow(index, item)
            else:
                owner = item.parent()
                if owner is None:
                    group.insertRow(index, item)
                elif owner is not group:
                    group.insertRow(index, owner.takeRow(item.row()))
                elif item.row() != index:
                    group.insertRow(index, group.takeRow(item.row()))
            if item.text() != container.name:
                item.setText(container.name)
            if item.data(CONTAINER_ROLE) != container:
                item.setData(container, CONTAINER_ROLE)
            busy = container.id in self._busy
            if item.data(BUSY_ROLE) != busy:
                item.setData(busy, BUSY_ROLE)

        name = key or STANDALONE_GROUP
        running = sum(1 for c in containers if c.state == "running")
        summary = GroupSummary(name, len(containers), running, key == "")
        if group.text() != name:
            group.setText(name)
        if group.data(GROUP_ROLE) != summary:
            group.setData(summary, GROUP_ROLE)
