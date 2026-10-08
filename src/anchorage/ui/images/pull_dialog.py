"""Ask for an image reference to pull."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from anchorage.docker.models import split_reference


class PullDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Pull image"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Image reference (repository[:tag]):")))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("nginx:alpine")
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(False)
        self.edit.textChanged.connect(lambda text: ok.setEnabled(bool(text.strip())))

    def reference(self) -> tuple[str, str] | None:
        text = self.edit.text().strip()
        if not text:
            return None
        return split_reference(text)
