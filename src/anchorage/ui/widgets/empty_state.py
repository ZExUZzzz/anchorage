"""Placeholder shown instead of a list when there is nothing to show."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch()
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.message = QLabel()
        self.message.setObjectName("muted")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.button = QPushButton()
        self.button.clicked.connect(self.action_clicked.emit)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.button.hide()

    def set_content(self, title: str, message: str, action_text: str | None = None) -> None:
        self.title.setText(title)
        self.message.setText(message)
        if action_text:
            self.button.setText(action_text)
            self.button.show()
        else:
            self.button.hide()
