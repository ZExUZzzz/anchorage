"""Per-layer progress for one pull job."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from anchorage.core.images import PullJob
from anchorage.docker.errors import DockerError
from anchorage.docker.models import PullProgress

HIDE_DELAY_MS = 3000


class PullPanel(QFrame):
    job_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._job: PullJob | None = None
        self._reference = ""
        self.rows: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("section")
        head.addWidget(self.title)
        head.addStretch()
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self._cancel)
        head.addWidget(self.cancel_button)
        layout.addLayout(head)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(10)
        layout.addLayout(self._grid)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.hide()

    def bind(self, job: PullJob, reference: str) -> None:
        if self._job is not None and not self._job.done:
            self._job.cancel()
        self._detach()
        self._reference = reference
        self.rows.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.title.setText(self.tr("PULLING  {reference}").format(reference=reference))
        self.cancel_button.setEnabled(True)
        self._hide_timer.stop()
        self.show()
        if job.done:
            self._finish(job.cancelled, job.error)
            return
        self._job = job
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_finished)

    def _detach(self) -> None:
        if self._job is not None:
            self._job.progress.disconnect(self._on_progress)
            self._job.finished.disconnect(self._on_finished)
        self._job = None

    def _cancel(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self.cancel_button.setEnabled(False)

    def _on_progress(self, item: PullProgress) -> None:
        if item.layer_id is None:
            return
        row = self.rows.get(item.layer_id)
        if row is None:
            digest = QLabel(item.layer_id)
            digest.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            status = QLabel()
            status.setObjectName("muted")
            index = len(self.rows)
            self._grid.addWidget(digest, index, 0)
            self._grid.addWidget(bar, index, 1)
            self._grid.addWidget(status, index, 2)
            self._grid.setColumnStretch(1, 1)
            row = (digest, bar, status)
            self.rows[item.layer_id] = row
        _, bar, status = row
        job = self._job
        layer = job.layers.get(item.layer_id) if job else None
        fraction = layer.fraction if layer else None
        if fraction is not None:
            bar.setValue(int(fraction * 100))
        status.setText(item.status)

    def _on_finished(self, error: object) -> None:
        job = self._job
        self._detach()
        self._finish(job is not None and job.cancelled, error)

    def _finish(self, cancelled: bool, error: object) -> None:
        if cancelled:
            self.title.setText(self.tr("CANCELLED  {reference}").format(reference=self._reference))
        elif error is not None:
            detail = error.message if isinstance(error, DockerError) else str(error)
            self.title.setText(
                self.tr("FAILED  {reference}: {detail}").format(
                    reference=self._reference, detail=detail
                )
            )
        else:
            self.title.setText(self.tr("COMPLETE  {reference}").format(reference=self._reference))
        self.cancel_button.setEnabled(False)
        self._hide_timer.start(HIDE_DELAY_MS)
        self.job_finished.emit()
