from PySide6.QtCore import Qt

from anchorage.core.engine import EngineState
from anchorage.docker.errors import EngineUnavailable, PermissionDenied
from anchorage.ui.context import AppContext
from anchorage.ui.main_window import MainWindow
from anchorage.ui.theme import level_color
from anchorage.ui.widgets.empty_state import EmptyState
from anchorage.ui.widgets.sidebar import Sidebar
from anchorage.ui.widgets.toast import Toast
from tests.core.fakes import FakeEngine


def test_window_builds_with_sidebar_and_pages(qtbot, context: AppContext) -> None:
    window = MainWindow(context)
    qtbot.addWidget(window)
    assert window.windowTitle() == "Anchorage"
    assert window.pages.count() == 5
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    window.sidebar.select("images")
    assert window.pages.currentIndex() == MainWindow.PAGE_IMAGES
    window.sidebar.select("volumes")
    assert window.pages.currentIndex() == MainWindow.PAGE_VOLUMES
    window.sidebar.select("networks")
    assert window.pages.currentIndex() == MainWindow.PAGE_NETWORKS
    window.sidebar.select("containers")
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS


def test_engine_state_drives_status_bar(qtbot, context: AppContext, engine: FakeEngine) -> None:
    window = MainWindow(context)
    qtbot.addWidget(window)
    context.engine.start()
    assert context.engine.state is EngineState.CONNECTED
    assert "Connected" in window.status_connection.text()
    assert "1.56" in window.status_version.text()
    assert "29.8.2" in window.sidebar.engine_label.text()
    assert engine.socket_path in window.sidebar.socket_label.text()


def test_engine_error_shows_message(qtbot, context: AppContext, engine: FakeEngine) -> None:
    engine.errors["ping"] = EngineUnavailable("connection refused")
    window = MainWindow(context)
    qtbot.addWidget(window)
    context.engine.start()
    assert context.engine.state is EngineState.ERROR
    assert "not running" in window.status_connection.text().lower()
    error_name = level_color("error", window.palette()).name()
    assert error_name in window.status_connection.styleSheet()
    engine.errors["ping"] = PermissionDenied("permission denied")
    context.engine.reconnect_now()
    assert "permission" in window.status_connection.text().lower()
    assert error_name in window.status_connection.styleSheet()


def test_fresh_window_reads_not_connected(qtbot, context: AppContext, engine: FakeEngine) -> None:
    window = MainWindow(context)
    qtbot.addWidget(window)
    assert "Not connected" in window.status_connection.text()
    assert window.status_version.text() == ""
    engine.errors["ping"] = EngineUnavailable("connection refused")
    context.engine.start()
    assert "not running" in window.status_connection.text().lower()
    assert window.status_version.text() == ""


def test_shutdown_is_idempotent(qtbot, engine: FakeEngine) -> None:
    ctx = AppContext.build(engine, inline=True)
    ctx.engine.start()
    stops: list[bool] = []
    original = ctx.engine.stop

    def counting_stop() -> bool:
        result = original()
        stops.append(result)
        return result

    ctx.engine.stop = counting_stop  # type: ignore[method-assign]
    assert ctx.shutdown(timeout_ms=500) is True
    assert ctx.shutdown(timeout_ms=500) is True
    assert stops == [True]


def test_second_shutdown_returns_first_result_without_waiting(engine: FakeEngine) -> None:
    class StuckJob:
        stops = 0

        def stop(self, timeout_ms: int = 2000) -> bool:
            StuckJob.stops += 1
            return False

    ctx = AppContext.build(engine, inline=True)
    ctx.images._jobs.append(StuckJob())  # type: ignore[arg-type]
    assert ctx.shutdown(timeout_ms=100) is False
    assert ctx.shutdown(timeout_ms=100) is False
    assert StuckJob.stops == 1
    ctx.images._jobs.clear()


def test_shutdown_reports_a_worker_that_missed_its_deadline(qtbot, engine: FakeEngine) -> None:
    class StuckJob:
        def stop(self, timeout_ms: int = 2000) -> bool:
            return False

    ctx = AppContext.build(engine, inline=True)
    ctx.images._jobs.append(StuckJob())  # type: ignore[arg-type]
    assert ctx.shutdown(timeout_ms=100) is False
    ctx.images._jobs.clear()


def test_shutdown_returns_true_when_everything_stopped(qtbot, engine: FakeEngine) -> None:
    ctx = AppContext.build(engine, inline=True)
    ctx.engine.start()
    assert ctx.shutdown(timeout_ms=500) is True


def test_toast_zero_timeout_stays(qtbot) -> None:
    toast = Toast()
    qtbot.addWidget(toast)
    toast.show_message("x", timeout_ms=0)
    qtbot.wait(100)
    assert not toast.isHidden()


def test_toast_shows_and_dismisses(qtbot) -> None:
    toast = Toast()
    qtbot.addWidget(toast)
    assert toast.isHidden()
    toast.show_message("boom", timeout_ms=50)
    assert not toast.isHidden()
    assert toast.label.text() == "boom"
    qtbot.waitUntil(lambda: toast.isHidden(), timeout=2000)
    toast.show_message("again")
    toast.dismiss()
    assert toast.isHidden()


def test_empty_state_action(qtbot) -> None:
    widget = EmptyState()
    qtbot.addWidget(widget)
    clicked: list[bool] = []
    widget.action_clicked.connect(lambda: clicked.append(True))
    widget.set_content("Title", "Message")
    assert widget.button.isHidden()
    widget.set_content("Title", "Message", action_text="Retry")
    assert not widget.button.isHidden()
    qtbot.mouseClick(widget.button, Qt.MouseButton.LeftButton)
    assert clicked == [True]


def test_close_event_runs_shutdown(qtbot, context: AppContext, engine: FakeEngine) -> None:
    window = MainWindow(context)
    qtbot.addWidget(window)
    context.engine.start()
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 1, timeout=2000)
    window.close()
    assert engine.event_feeds[0].closed
    assert context.engine.state is EngineState.DISCONNECTED


def click_row(qtbot, sidebar: Sidebar, row: int) -> None:
    rect = sidebar.nav.visualItemRect(sidebar.nav.item(row))
    qtbot.mouseClick(sidebar.nav.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())


def test_select_current_section_emits_again(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    emitted: list[str] = []
    sidebar.section_changed.connect(emitted.append)
    sidebar.select("containers")
    sidebar.select("containers")
    assert emitted == ["containers", "containers"]
    sidebar.select("images")
    assert emitted[-1] == "images"
    assert len(emitted) == 3


def test_select_ignores_unknown_sections(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    emitted: list[str] = []
    sidebar.section_changed.connect(emitted.append)
    sidebar.select("nope")
    assert emitted == []
    assert sidebar.nav.currentRow() == 0


def test_clicking_current_section_emits_once_and_other_rows_once(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    sidebar.show()
    emitted: list[str] = []
    sidebar.section_changed.connect(emitted.append)
    click_row(qtbot, sidebar, 0)
    assert emitted == ["containers"]
    click_row(qtbot, sidebar, 1)
    assert emitted == ["containers", "images"]
    click_row(qtbot, sidebar, 1)
    assert emitted == ["containers", "images", "images"]
    click_row(qtbot, sidebar, 2)
    assert emitted == ["containers", "images", "images", "volumes"]


def test_nav_rows_have_a_fixed_height(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    assert sidebar.nav.uniformItemSizes()
    heights = [sidebar.nav.item(row).sizeHint().height() for row in range(sidebar.nav.count())]
    assert heights == [32] * sidebar.nav.count()


def test_shell_uses_the_saved_terminal_override(
    qtbot, context: AppContext, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from anchorage.core import terminal
    from anchorage.core.settings import AppSettings, Resolved

    calls: list[tuple[str, str]] = []

    def fake_open_shell(container_id: str, *, command: str = "") -> terminal.Launch:
        calls.append((container_id, command))
        return terminal.Launch(("docker",), ("x",), None)

    monkeypatch.setattr(terminal, "open_shell", fake_open_shell)
    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings = AppSettings(store)
    window = MainWindow(context, app_settings=settings, resolved=Resolved.defaults())
    qtbot.addWidget(window)
    settings.terminal = "kitty -e"
    window._launch_shell("abc")
    settings.terminal = ""
    window._launch_shell("def")
    assert calls == [("abc", "kitty -e"), ("def", "")]
