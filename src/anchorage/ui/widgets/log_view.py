"""Read-only log pane with ANSI colours, follow mode, timestamps and search."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from anchorage.core.loglevel import detect_level
from anchorage.docker.errors import DockerError
from anchorage.docker.models import LogLine
from anchorage.ui.theme import is_dark, level_color
from anchorage.ui.widgets.ansi import parse_ansi

_HUES = (None, 0, 120, 50, 215, 300, 185, None)


def ansi_color(index: int, palette: QPalette) -> QColor:
    base = index % 8
    hue = _HUES[base]
    if hue is None:
        role = QPalette.ColorRole.PlaceholderText if base == 0 else QPalette.ColorRole.Text
        return palette.color(role)
    color = QColor()
    light = 0.65 if is_dark(palette) else 0.35
    if index >= 8:
        light += 0.1 if is_dark(palette) else -0.05
    color.setHslF(hue / 360, 0.6, light)
    return color


class _SearchEdit(QLineEdit):
    """Search field where Shift+Enter asks for the previous match."""

    previous_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.previous_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class LogView(QWidget):
    MAX_LINES = 10_000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lines: deque[LogLine] = deque(maxlen=self.MAX_LINES)
        self._ended: tuple[DockerError | None] | None = None
        self._color_mode = "stream"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        bar = QHBoxLayout()
        self.search = _SearchEdit()
        self.search.setObjectName("logsearch")
        self.search.setPlaceholderText(self.tr("Search logs… (Enter next, Shift+Enter previous)"))
        self.search.setToolTip(self.search.placeholderText())
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.find_next)
        self.search.previous_requested.connect(self.find_previous)
        bar.addWidget(self.search, 1)
        self.prev_button = QPushButton(self.tr("Prev"))
        self.prev_button.clicked.connect(self.find_previous)
        bar.addWidget(self.prev_button)
        self.next_button = QPushButton(self.tr("Next"))
        self.next_button.clicked.connect(self.find_next)
        bar.addWidget(self.next_button)
        self.follow = QPushButton(self.tr("Follow"))
        self.follow.setCheckable(True)
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._on_follow_toggled)
        bar.addWidget(self.follow)
        self.timestamps = QPushButton(self.tr("Timestamps"))
        self.timestamps.setCheckable(True)
        self.timestamps.setChecked(True)
        self.timestamps.toggled.connect(self._render_all)
        bar.addWidget(self.timestamps)
        self.clear_button = QPushButton(self.tr("Clear"))
        self.clear_button.clicked.connect(self.clear)
        bar.addWidget(self.clear_button)
        layout.addLayout(bar)

        self.edit = QPlainTextEdit()
        self.edit.setObjectName("logs")
        self.edit.setReadOnly(True)
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.edit.setMaximumBlockCount(self.MAX_LINES + 1)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(max(font.pointSize() - 1, 8))
        self.edit.setFont(font)
        self.edit.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        layout.addWidget(self.edit, 1)
        self._suspend_scroll_watch = False

    def append_lines(self, lines: list[LogLine]) -> None:
        self._lines.extend(lines)
        self._insert(lines)

    def set_lines(self, lines: list[LogLine]) -> None:
        self._lines.clear()
        self._lines.extend(lines)
        self._render_all()

    def clear(self) -> None:
        self._lines.clear()
        self._ended = None
        self.edit.clear()

    def mark_ended(self, error: DockerError | None) -> None:
        self._ended = (error,)
        self._append_ended(error)

    def _append_ended(self, error: DockerError | None) -> None:
        text = (
            self.tr("— stream ended: {message} —").format(message=error.message)
            if error
            else self.tr("— stream ended —")
        )
        fmt = QTextCharFormat()
        fmt.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
        fmt.setFontItalic(True)
        cursor = self._end_cursor()
        if not self.edit.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(text, fmt)
        self._scroll_if_following()

    def find_next(self) -> None:
        needle = self.search.text()
        if not needle:
            return
        if not self.edit.find(needle):
            cursor = self.edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.edit.setTextCursor(cursor)
            self.edit.find(needle)

    def find_previous(self) -> None:
        needle = self.search.text()
        if not needle:
            return
        backward = QTextDocument.FindFlag.FindBackward
        if not self.edit.find(needle, backward):
            cursor = self.edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.edit.setTextCursor(cursor)
            self.edit.find(needle, backward)

    def set_color_mode(self, mode: str) -> None:
        """``"stream"`` colours stderr lines; ``"level"`` colours by the detected severity."""
        if mode not in ("stream", "level"):
            raise ValueError(f"unknown log colour mode: {mode!r}")
        if mode != self._color_mode:
            self._color_mode = mode
            self._render_all()

    def _end_cursor(self) -> QTextCursor:
        cursor = self.edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor

    def _render_all(self) -> None:
        bar = self.edit.verticalScrollBar()
        keep = bar.value()
        self.edit.clear()
        self._insert(list(self._lines))
        if self._ended is not None:
            self._append_ended(self._ended[0])
        if self.follow.isChecked():
            self._scroll_if_following()
        else:
            self._suspend_scroll_watch = True
            bar.setValue(min(keep, bar.maximum()))
            self._suspend_scroll_watch = False

    def _insert(self, lines: list[LogLine]) -> None:
        if not lines:
            return
        palette = self.palette()
        muted = QTextCharFormat()
        muted.setForeground(palette.color(QPalette.ColorRole.PlaceholderText))
        stderr = QTextCharFormat()
        stderr.setForeground(ansi_color(1, palette))
        by_level = {name: QTextCharFormat() for name in ("error", "warn")}
        for name, fmt in by_level.items():
            fmt.setForeground(level_color(name, palette))
        by_stream = self._color_mode == "stream"
        show_stamp = self.timestamps.isChecked()
        cursor = self._end_cursor()
        cursor.beginEditBlock()
        first = self.edit.document().isEmpty()
        for line in lines:
            if not first:
                cursor.insertBlock()
            first = False
            if show_stamp and line.timestamp is not None:
                ts = line.timestamp
                stamp = ts.strftime("%H:%M:%S.") + f"{ts.microsecond // 1000:03d}  "
                cursor.insertText(stamp, muted)
            level: str | None = None if by_stream else detect_level(line.text)
            for span in parse_ansi(line.text):
                if span.fg is not None:
                    fmt = QTextCharFormat()
                elif by_stream and line.stream == "stderr":
                    fmt = QTextCharFormat(stderr)
                elif level is not None:
                    fmt = QTextCharFormat(by_level[level])
                else:
                    fmt = QTextCharFormat()
                if span.fg is not None:
                    fmt.setForeground(ansi_color(span.fg, palette))
                if span.bold:
                    fmt.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(span.text, fmt)
        cursor.endEditBlock()
        self._scroll_if_following()

    def _scroll_if_following(self) -> None:
        if self.follow.isChecked():
            bar = self.edit.verticalScrollBar()
            self._suspend_scroll_watch = True
            bar.setValue(bar.maximum())
            self._suspend_scroll_watch = False

    def _on_scrolled(self, value: int) -> None:
        if self._suspend_scroll_watch:
            return
        bar = self.edit.verticalScrollBar()
        if value < bar.maximum() and self.follow.isChecked():
            self.follow.setChecked(False)

    def _on_follow_toggled(self, checked: bool) -> None:
        if checked:
            self._scroll_if_following()
