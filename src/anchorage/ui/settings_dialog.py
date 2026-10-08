"""The settings dialog: edits the saved values that flags and environment variables do not fix."""

from __future__ import annotations

import importlib.util
import os

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication
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
from anchorage.ui.i18n import LANGUAGES

LOG_COLOR_LABELS = (
    ("stream", str(QT_TRANSLATE_NOOP("SettingsDialog", "Output stream"))),
    ("level", str(QT_TRANSLATE_NOOP("SettingsDialog", "Detected level"))),
)
BACKEND_LABELS = (
    ("native", str(QT_TRANSLATE_NOOP("SettingsDialog", "Native"))),
    ("dockerpy", "docker-py"),
)


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
        self.setWindowTitle(self.tr("Settings"))
        self.setModal(True)
        self._settings = settings
        self._locked = dict(resolved.locked)

        self.log_colors = QComboBox()
        for value, label in LOG_COLOR_LABELS:
            self.log_colors.addItem(QCoreApplication.translate("SettingsDialog", label), value)
        self.backend = QComboBox()
        for value, label in BACKEND_LABELS:
            self.backend.addItem(QCoreApplication.translate("SettingsDialog", label), value)
        if importlib.util.find_spec("docker") is None:
            index = self.backend.findData("dockerpy")
            item = self.backend.model().item(index)  # type: ignore[attr-defined]
            item.setEnabled(False)
            item.setToolTip(self.tr("Needs the docker-py package"))
        self.socket = QLineEdit()
        self.socket.setPlaceholderText(discovered_socket or self.tr("Automatic"))
        self.browse = QPushButton(self.tr("Browse…"))
        self.browse.clicked.connect(self._browse)
        self.terminal = QLineEdit()
        self.terminal.setPlaceholderText(detected_terminal() or self.tr("no terminal found"))
        self.terminal.setToolTip(
            self.tr(
                "Anchorage appends `docker exec -it <container> sh`, so include the option your "
                "terminal needs to run a command (konsole -e, gnome-terminal --, xterm -e)."
            )
        )
        self.language = QComboBox()
        self.language.addItem(self.tr("System default"), "")
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)

        # A locked key shows what this run uses; an unlocked one shows what is saved.
        self._set_combo(self.log_colors, resolved.log_colors)
        self._set_combo(self.backend, resolved.backend)
        self.socket.setText(resolved.socket)
        self.terminal.setText(resolved.terminal)
        self._set_combo(self.language, resolved.language)

        form = QFormLayout()
        form.addRow(self.tr("Log colours"), self._row(self.log_colors, key="log_colors"))
        form.addRow(self.tr("Backend"), self._row(self.backend, key="backend", restart=True))
        form.addRow(
            self.tr("Socket"), self._row(self.socket, self.browse, key="socket", restart=True)
        )
        form.addRow(self.tr("Terminal"), self._row(self.terminal, key="terminal"))
        form.addRow(self.tr("Language"), self._row(self.language, key="language", restart=True))

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
            if reason == "DOCKER_HOST":
                reason = f"DOCKER_HOST={os.environ.get('DOCKER_HOST', '')}"
            notes.append(self.tr("Set by {reason} for this run").format(reason=reason))
            for field in fields:
                field.setEnabled(False)
                field.setToolTip(
                    self.tr("Fixed by {reason}; the saved value is not changed").format(
                        reason=reason
                    )
                )
        if restart:
            notes.append(self.tr("Applies after a restart"))
        for text in notes:
            note = QLabel(text)
            note.setObjectName("muted")
            note.setWordWrap(True)
            column.addWidget(note)
        return holder

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Docker socket"), self.socket.text())
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
        update("language", str(self.language.currentData()))
        return changed
