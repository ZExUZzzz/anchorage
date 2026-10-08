"""Left navigation column."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QStyle, QVBoxLayout, QWidget

from anchorage.ui.theme import icon

SECTIONS: tuple[tuple[str, str, str, QStyle.StandardPixmap, bool], ...] = (
    ("containers", "Containers", "package-x-generic", QStyle.StandardPixmap.SP_DirIcon, True),
    ("images", "Images", "media-optical", QStyle.StandardPixmap.SP_DriveCDIcon, True),
    ("volumes", "Volumes", "drive-harddisk", QStyle.StandardPixmap.SP_DriveHDIcon, True),
    ("networks", "Networks", "network-wired", QStyle.StandardPixmap.SP_DriveNetIcon, True),
)

ROW_HEIGHT = 32


class _Nav(QListWidget):
    """Remembers whether a press landed on the row that was already current.

    ``currentRowChanged`` stays silent then, so the click is the only signal.
    """

    def __init__(self) -> None:
        super().__init__()
        self.pressed_on_current = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        self.pressed_on_current = item is not None and self.row(item) == self.currentRow()
        super().mousePressEvent(event)


class Sidebar(QWidget):
    section_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        brand = QLabel("Anchorage")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        self.nav = _Nav()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setUniformItemSizes(True)
        self._keys: list[str] = []
        for key, text, icon_name, fallback, enabled in SECTIONS:
            item = QListWidgetItem(icon(icon_name, fallback), text)
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            if not enabled:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.nav.addItem(item)
            self._keys.append(key)
        self.nav.currentRowChanged.connect(self._on_row)
        self.nav.itemClicked.connect(self._on_clicked)
        layout.addWidget(self.nav)
        layout.addStretch()
        self.engine_label = QLabel("Engine: not connected")
        layout.addWidget(self.engine_label)
        self.socket_label = QLabel("")
        self.socket_label.setObjectName("muted")
        self.socket_label.setWordWrap(True)
        layout.addWidget(self.socket_label)
        self.nav.setCurrentRow(0)

    def select(self, key: str) -> None:
        """Show a section and announce it, even when it is already the current one."""
        if key not in self._keys:
            return
        row = self._keys.index(key)
        item = self.nav.item(row)
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        if self.nav.currentRow() == row:
            self.section_changed.emit(key)
        else:
            self.nav.setCurrentRow(row)

    def current_key(self) -> str:
        row = self.nav.currentRow()
        return self._keys[row] if 0 <= row < len(self._keys) else ""

    def set_engine(self, text: str, color: QColor | None = None) -> None:
        self.engine_label.setText(text)
        self.engine_label.setStyleSheet(f"color: {color.name()};" if color is not None else "")

    def set_socket(self, path: str) -> None:
        self.socket_label.setText(path)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        row = self.nav.row(item)
        if self.nav.pressed_on_current and 0 <= row < len(self._keys):
            self.section_changed.emit(self._keys[row])

    def _on_row(self, row: int) -> None:
        if 0 <= row < len(self._keys):
            self.section_changed.emit(self._keys[row])
