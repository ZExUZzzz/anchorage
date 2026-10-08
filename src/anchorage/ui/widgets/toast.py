"""In-window notification bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class Toast(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        layout.addWidget(copy)
        close = QPushButton("Dismiss")
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.hide()

    def show_message(self, text: str, timeout_ms: int = 8000) -> None:
        self.label.setText(text)
        self.show()
        if timeout_ms > 0:
            self._timer.start(timeout_ms)
        else:
            self._timer.stop()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.label.text())
