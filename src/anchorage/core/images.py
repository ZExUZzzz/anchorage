"""Image table model and pull jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from anchorage.core.engine import EngineService, EngineState
from anchorage.core.units import format_bytes
from anchorage.core.workers import StreamWorker, TaskRunner
from anchorage.docker.client import EngineAPI, Stream
from anchorage.docker.errors import DockerError
from anchorage.docker.models import Event, Image, PruneResult, PullProgress, split_reference

IMAGE_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_ROLE = Qt.ItemDataRole.UserRole + 2
SORT_ROLE = Qt.ItemDataRole.UserRole + 3

COLUMNS = ("Repository", "Tag", "ID", "Size", "Created")
_NONE = "<none>"


@dataclass(frozen=True, slots=True)
class ImageRow:
    image: Image
    repository: str
    tag: str
    reference: str


@dataclass(frozen=True, slots=True)
class LayerProgress:
    id: str
    status: str
    current: int | None
    total: int | None

    @property
    def fraction(self) -> float | None:
        if self.status in ("Pull complete", "Already exists"):
            return 1.0
        if self.current is None or not self.total:
            return None
        return min(self.current / self.total, 1.0)


class PullJob(QObject):
    """One image pull: per-layer progress plus completion. Single-use."""

    progress = Signal(object)
    finished = Signal(object)

    def __init__(
        self, open_stream: Callable[[], Stream[PullProgress]], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.layers: dict[str, LayerProgress] = {}
        self.status = ""
        self.error: DockerError | None = None
        self.done = False
        self.cancelled = False
        self._started = False
        self._worker = StreamWorker(open_stream, parent=self)
        self._worker.items.connect(self._on_items)
        self._worker.ended.connect(self._on_ended)

    def start(self) -> None:
        if self._started or self.cancelled:
            return
        self._started = True
        self._worker.start()

    def cancel(self) -> None:
        self.cancelled = True
        self._worker.close()

    def stop(self, timeout_ms: int = 2000) -> bool:
        self.cancelled = True
        return self._worker.dispose(timeout_ms)

    def _on_items(self, items: list[PullProgress]) -> None:
        for item in items:
            if item.layer_id:
                self.layers[item.layer_id] = LayerProgress(
                    item.layer_id, item.status, item.current, item.total
                )
            else:
                self.status = item.status
            self.progress.emit(item)

    def _on_ended(self, error: object) -> None:
        self.done = True
        self.error = error if isinstance(error, DockerError) else None
        self.finished.emit(self.error)


def _rows(images: list[Image]) -> list[ImageRow]:
    rows: list[ImageRow] = []
    for image in images:
        if image.dangling:
            rows.append(ImageRow(image, _NONE, _NONE, image.id))
            continue
        for ref in image.repo_tags:
            repository, tag = split_reference(ref)
            rows.append(ImageRow(image, repository, tag, ref))
    return sorted(rows, key=lambda r: (r.repository.lower(), r.tag.lower()))


class ImageStore(QObject):
    """Flat table model with one row per image tag."""

    refreshed = Signal()
    refresh_failed = Signal(object)
    action_failed = Signal(str, object)
    pruned = Signal(object)

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
        self._rows: list[ImageRow] = []
        self._jobs: list[PullJob] = []
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

    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        self._runner.submit(
            self._api.list_images,
            lambda images: self._apply_if_current(generation, images),
            lambda error: self._fail_if_current(generation, error),
        )

    def _fail_if_current(self, generation: int, error: DockerError) -> None:
        if generation == self._generation:
            self.refresh_failed.emit(error)

    def _apply_if_current(self, generation: int, images: list[Image]) -> None:
        if generation == self._generation:
            self._apply(images)

    def rows(self) -> list[ImageRow]:
        return list(self._rows)

    def row(self, reference: str) -> ImageRow | None:
        return next((r for r in self._rows if r.reference == reference), None)

    def remove(self, reference: str, *, force: bool = False) -> None:
        self._runner.submit(
            lambda: self._api.remove_image(reference, force=force),
            lambda _: self.refresh(),
            lambda error: self.action_failed.emit(reference, error),
        )

    def prune(self, *, dangling_only: bool = True) -> None:
        def done(result: PruneResult) -> None:
            self.pruned.emit(result)
            self.refresh()

        self._runner.submit(
            lambda: self._api.prune_images(dangling_only=dangling_only),
            done,
            lambda error: self.action_failed.emit("prune", error),
        )

    def pull(self, repository: str, tag: str = "latest") -> PullJob:
        api = self._api
        job = PullJob(lambda: api.pull_image(repository, tag), parent=self)
        job.finished.connect(self._on_pull_finished)
        self._jobs.append(job)
        return job

    def shutdown(self, timeout_ms: int = 2000) -> bool:
        """Stop every live pull; True when all workers finished within the timeout."""
        stopped = True
        for job in list(self._jobs):
            stopped = job.stop(timeout_ms) and stopped
        return stopped

    def handle_event(self, event: Event) -> None:
        if event.type == "image" and not self._timer.isActive():
            self._timer.start()

    def _on_engine_state(self, state: EngineState) -> None:
        if state is EngineState.CONNECTED:
            self.refresh()

    def _on_pull_finished(self, error: object) -> None:
        job = self.sender()
        if job in self._jobs:
            self._jobs.remove(job)
        if error is None:
            self.refresh()

    def _apply(self, images: list[Image]) -> None:
        self._rows = _rows(images)
        self.model.removeRows(0, self.model.rowCount())
        for row in self._rows:
            created = row.image.created.astimezone().strftime("%Y-%m-%d %H:%M")
            cells = [
                QStandardItem(row.repository),
                QStandardItem(row.tag),
                QStandardItem(row.image.short_id),
                QStandardItem(format_bytes(row.image.size)),
                QStandardItem(created),
            ]
            for cell in cells:
                cell.setEditable(False)
            cells[0].setData(row.image, IMAGE_ROLE)
            cells[0].setData(row, ROW_ROLE)
            cells[0].setData(row.repository.lower(), SORT_ROLE)
            cells[1].setData(row.tag.lower(), SORT_ROLE)
            cells[2].setData(row.image.short_id.lower(), SORT_ROLE)
            cells[3].setData(row.image.size, SORT_ROLE)
            cells[4].setData(row.image.created.timestamp(), SORT_ROLE)
            self.model.appendRow(cells)
        self.refreshed.emit()
