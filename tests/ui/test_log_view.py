from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from anchorage.docker.errors import NotFound
from anchorage.docker.models import LogLine
from anchorage.ui.widgets.log_view import LogView


def line(text: str, stream: str = "stdout") -> LogLine:
    return LogLine(stream, text, datetime(2026, 10, 2, 20, 14, 3, 118000, tzinfo=UTC))


def test_append_strips_ansi_and_prefixes_timestamps(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line("\x1b[31merror\x1b[0m happened"), line("plain")])
    text = view.edit.toPlainText()
    assert "error happened" in text
    assert "\x1b" not in text
    assert text.startswith("20:14:03.118")
    view.timestamps.setChecked(False)
    assert view.edit.toPlainText().startswith("error happened")


def test_follow_scrolls_to_bottom_and_pauses_when_user_scrolls(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.resize(400, 120)
    view.show()
    view.append_lines([line(f"line {i}") for i in range(200)])
    bar = view.edit.verticalScrollBar()
    assert bar.value() == bar.maximum()
    bar.setValue(0)
    assert view.follow.isChecked() is False
    view.append_lines([line("tail")])
    assert bar.value() == 0
    view.follow.setChecked(True)
    assert bar.value() == bar.maximum()


def test_search_finds_next(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line("alpha"), line("beta"), line("alpha again")])
    view.search.setText("alpha")
    view.find_next()
    assert view.edit.textCursor().selectedText() == "alpha"
    view.find_next()
    assert view.edit.textCursor().blockNumber() == 2
    view.find_next()
    assert view.edit.textCursor().blockNumber() == 0


def test_search_finds_previous_and_wraps(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line("alpha"), line("beta"), line("alpha again")])
    view.search.setText("alpha")
    cursor = view.edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    view.edit.setTextCursor(cursor)
    view.find_previous()
    assert view.edit.textCursor().selectedText() == "alpha"
    assert view.edit.textCursor().blockNumber() == 2
    view.find_previous()
    assert view.edit.textCursor().blockNumber() == 0
    view.find_previous()
    assert view.edit.textCursor().blockNumber() == 2


def test_shift_enter_and_buttons_search_backwards(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line("alpha"), line("beta"), line("alpha again")])
    view.search.setText("alpha")
    view.find_next()
    assert view.edit.textCursor().blockNumber() == 0
    qtbot.keyClick(view.search, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert view.edit.textCursor().blockNumber() == 2
    qtbot.keyClick(view.search, Qt.Key.Key_Return)
    assert view.edit.textCursor().blockNumber() == 0
    view.prev_button.click()
    assert view.edit.textCursor().blockNumber() == 2
    view.next_button.click()
    assert view.edit.textCursor().blockNumber() == 0


def test_clear_and_mark_ended(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line("x")])
    view.clear()
    assert view.edit.toPlainText() == ""
    view.mark_ended(None)
    assert "stream ended" in view.edit.toPlainText()
    view.mark_ended(NotFound("gone", 404))
    assert "gone" in view.edit.toPlainText()


def test_buffer_is_bounded(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line(str(i)) for i in range(LogView.MAX_LINES + 50)])
    assert view.edit.blockCount() <= LogView.MAX_LINES + 1
    view.timestamps.setChecked(False)
    assert view.edit.toPlainText().splitlines()[0] == "50"


def test_ended_marker_survives_timestamp_toggle(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.append_lines([line("x")])
    view.mark_ended(None)
    view.timestamps.setChecked(False)
    assert "stream ended" in view.edit.toPlainText()
    view.clear()
    view.timestamps.setChecked(True)
    assert "stream ended" not in view.edit.toPlainText()


def test_timestamp_toggle_keeps_scroll_position_when_not_following(qtbot) -> None:
    view = LogView()
    qtbot.addWidget(view)
    view.resize(400, 120)
    view.show()
    view.append_lines([line(f"line {i}") for i in range(300)])
    bar = view.edit.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    assert view.follow.isChecked() is False
    mid = bar.value()
    assert mid > 0
    view.timestamps.setChecked(False)
    assert bar.value() == min(mid, bar.maximum())


def test_level_mode_colours_by_detected_level_not_stream(qtbot) -> None:
    from anchorage.ui.theme import level_color
    from anchorage.ui.widgets.log_view import ansi_color

    view = LogView()
    qtbot.addWidget(view)
    view.timestamps.setChecked(False)
    view.set_color_mode("level")
    view.append_lines(
        [
            LogLine("stderr", "2026-10-03 4:39:19 0 [Note] InnoDB: Starting shutdown"),
            LogLine("stdout", "2026-10-03 4:54:53 0 [Warn] [Entrypoint]: not writable"),
            LogLine("stderr", "[ERROR] InnoDB: cannot open tablespace"),
        ]
    )
    palette = view.palette()
    colours = []
    block = view.edit.document().firstBlock()
    while block.isValid():
        fmt = block.begin().fragment().charFormat()
        colours.append(
            fmt.foreground().color() if fmt.hasProperty(fmt.Property.ForegroundBrush) else None
        )
        block = block.next()
    assert colours[0] is None
    assert colours[1] == level_color("warn", palette)
    assert colours[2] == level_color("error", palette)
    assert colours[2] != ansi_color(1, palette) or level_color("error", palette) == ansi_color(
        1, palette
    )
    view.set_color_mode("stream")
    block = view.edit.document().firstBlock()
    fmt = block.begin().fragment().charFormat()
    assert fmt.foreground().color() == ansi_color(1, palette)
