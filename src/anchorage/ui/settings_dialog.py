"""The settings dialog: edits the saved values that flags and environment variables do not fix."""

from __future__ import annotations

import importlib.util

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from anchorage.core.settings import AppSettings, Resolved
from anchorage.core.terminal import detected_terminal

LOG_COLOR_LABELS = (("stream", "Output stream"), ("level", "Detected level"))
BACKEND_LABELS = (("native", "Native"), ("dockerpy", "docker-py"))
RESTART_NOTE = "Applies after a restart"


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        resolved: Resolved,
        *,
        discovered_socket: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self._settings = settings
        self._locked = dict(resolved.locked)

        self.log_colors = QComboBox()
        for value, label in LOG_COLOR_LABELS:
            self.log_colors.addItem(label, value)
        self.backend = QComboBox()
        for value, label in BACKEND_LABELS:
            self.backend.addItem(label, value)
        if importlib.util.find_spec("docker") is None:
            index = self.backend.findData("dockerpy")
            item = self.backend.model().item(index)  # type: ignore[attr-defined]
            item.setEnabled(False)
            item.setToolTip("Needs the docker-py package")
        self.socket = QLineEdit()
        self.socket.setPlaceholderText(discovered_socket or "Automatic")
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        self.terminal = QLineEdit()
        self.terminal.setPlaceholderText(detected_terminal() or "no terminal found")

        # A locked key shows what this run uses; an unlocked one shows what is saved.
        self._set_combo(self.log_colors, resolved.log_colors)
        self._set_combo(self.backend, resolved.backend)
        self.socket.setText(resolved.socket)
        self.terminal.setText(resolved.terminal)

        form = QFormLayout()
        form.addRow("Log colours", self._row(self.log_colors, key="log_colors"))
        form.addRow("Backend", self._row(self.backend, key="backend", restart=True))
        form.addRow("Socket", self._row(self.socket, self.browse, key="socket", restart=True))
        form.addRow("Terminal", self._row(self.terminal, key="terminal"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setMinimumWidth(460)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _row(self, *fields: QWidget, key: str, restart: bool = False) -> QWidget:
        """The fields with notes below; a locked key is disabled, the reason as tooltip."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        line = QHBoxLayout()
        for index, field in enumerate(fields):
            line.addWidget(field, 1 if index == 0 else 0)
        column.addLayout(line)
        notes: list[str] = []
        reason = self._locked.get(key)
        if reason:
            notes.append(f"Set by {reason} for this run")
            for field in fields:
                field.setEnabled(False)
                field.setToolTip(f"Fixed by {reason}; the saved value is not changed")
        if restart:
            notes.append(RESTART_NOTE)
        if notes:
            note = QLabel(". ".join(notes))
            note.setObjectName("muted")
            note.setWordWrap(True)
            column.addWidget(note)
        return holder

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Docker socket", self.socket.text())
        if path:
            self.socket.setText(path)

    def save(self) -> set[str]:
        """Write the changed values that no flag or variable fixes; return their keys."""
        store = self._settings
        changed: set[str] = set()

        def update(key: str, value: str) -> None:
            if key not in self._locked and value != getattr(store, key):
                setattr(store, key, value)
                changed.add(key)

        update("log_colors", str(self.log_colors.currentData()))
        update("backend", str(self.backend.currentData()))
        update("socket", self.socket.text().strip())
        update("terminal", self.terminal.text().strip())
        return changed
