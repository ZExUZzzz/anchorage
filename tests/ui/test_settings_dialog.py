from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel

from anchorage.core.settings import AppSettings, Resolved
from anchorage.ui import settings_dialog
from anchorage.ui.context import AppContext
from anchorage.ui.main_window import MainWindow
from anchorage.ui.settings_dialog import SettingsDialog


@pytest.fixture
def store(tmp_path: Path) -> AppSettings:
    return AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def make(qtbot, store: AppSettings, **locked: str) -> SettingsDialog:
    resolved = Resolved(
        log_colors="level" if "log_colors" in locked else store.log_colors,
        backend=store.backend,
        socket=store.socket,
        terminal=store.terminal,
        language=store.language,
        locked=dict(locked),
    )
    dialog = SettingsDialog(store, resolved, discovered_socket="/run/docker.sock")
    qtbot.addWidget(dialog)
    return dialog


def test_fields_start_from_saved_values(qtbot, store: AppSettings) -> None:
    store.log_colors = "level"
    store.terminal = "kitty"
    dialog = make(qtbot, store)
    assert dialog.log_colors.currentData() == "level"
    assert dialog.terminal.text() == "kitty"
    assert dialog.socket.placeholderText() == "/run/docker.sock"


def test_ok_saves_changed_values(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store)
    dialog.log_colors.setCurrentIndex(dialog.log_colors.findData("level"))
    dialog.socket.setText("  /tmp/d.sock ")
    dialog.terminal.setText("foot")
    assert dialog.save() == {"log_colors", "socket", "terminal"}
    assert (store.log_colors, store.socket, store.terminal) == ("level", "/tmp/d.sock", "foot")
    assert store.backend == "native"


def test_cancel_saves_nothing(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store)
    dialog.log_colors.setCurrentIndex(dialog.log_colors.findData("level"))
    dialog.terminal.setText("foot")
    dialog.reject()
    assert (store.log_colors, store.terminal) == ("stream", "")


def test_locked_fields_are_disabled_and_not_saved(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store, log_colors="--log-colors", socket="DOCKER_HOST")
    assert not dialog.log_colors.isEnabled()
    assert not dialog.socket.isEnabled()
    assert not dialog.browse.isEnabled()
    assert "--log-colors" in dialog.log_colors.toolTip()
    assert "DOCKER_HOST" in dialog.socket.toolTip()
    assert dialog.backend.isEnabled()
    dialog.log_colors.setCurrentIndex(dialog.log_colors.findData("stream"))
    dialog.socket.setText("/x")
    assert dialog.save() == set()
    assert store.socket == ""
    assert store.log_colors == "stream"


def test_dockerpy_disabled_without_docker(qtbot, store: AppSettings, monkeypatch) -> None:
    monkeypatch.setattr(settings_dialog.importlib.util, "find_spec", lambda name: None)
    dialog = make(qtbot, store)
    item = dialog.backend.model().item(dialog.backend.findData("dockerpy"))
    assert not item.isEnabled()
    assert item.toolTip()
    assert dialog.backend.model().item(dialog.backend.findData("native")).isEnabled()


def test_window_applies_log_colors_at_once(qtbot, context: AppContext, store: AppSettings) -> None:
    window = MainWindow(context, app_settings=store)
    qtbot.addWidget(window)
    window.sidebar.settings_button.click()
    dialog = window.settings_dialog
    assert dialog is not None
    dialog.log_colors.setCurrentIndex(dialog.log_colors.findData("level"))
    dialog.accept()
    assert window.detail_page.log_view._color_mode == "level"
    assert store.log_colors == "level"
    assert window.resolved.log_colors == "level"
    assert window.settings_dialog is None
    assert not window.toast.isVisible()


def test_window_warns_when_socket_or_backend_changes(
    qtbot, context: AppContext, store: AppSettings
) -> None:
    window = MainWindow(context, app_settings=store)
    qtbot.addWidget(window)
    window.open_settings()
    assert window.settings_dialog is not None
    window.settings_dialog.socket.setText("/tmp/other.sock")
    window.settings_dialog.accept()
    assert "after a restart" in window.toast.label.text()
    assert store.socket == "/tmp/other.sock"


def test_escape_closes_without_saving(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store)
    dialog.show()
    dialog.terminal.setText("foot")
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert dialog.result() == dialog.DialogCode.Rejected
    assert store.terminal == ""


def test_enter_accepts(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store)
    dialog.show()
    qtbot.keyClick(dialog.terminal, Qt.Key.Key_Return)
    assert dialog.result() == dialog.DialogCode.Accepted


def test_terminal_only_change_saves_without_restart_toast(
    qtbot, context: AppContext, store: AppSettings
) -> None:
    window = MainWindow(context, app_settings=store)
    qtbot.addWidget(window)
    window.open_settings()
    assert window.settings_dialog is not None
    window.settings_dialog.terminal.setText("foot")
    window.settings_dialog.accept()
    assert store.terminal == "foot"
    assert window.resolved.terminal == "foot"
    assert not window.toast.isVisible()


def test_docker_host_value_is_shown_in_note(qtbot, store: AppSettings, monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "unix:///x/d.sock")
    dialog = make(qtbot, store, socket="DOCKER_HOST")
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("DOCKER_HOST=unix:///x/d.sock" in text for text in texts)


def test_terminal_tooltip_explains_the_run_option(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store)
    tip = dialog.terminal.toolTip()
    assert "docker exec -it <container> sh" in tip
    assert "konsole -e" in tip


def test_language_combo_lists_system_default_and_native_names(qtbot, store: AppSettings) -> None:
    dialog = make(qtbot, store)
    items = [(dialog.language.itemData(i), dialog.language.itemText(i)) for i in range(7)]
    assert items == [
        ("", "System default"),
        ("en", "English"),
        ("ru", "Русский"),
        ("de", "Deutsch"),
        ("es", "Español"),
        ("fr", "Français"),
        ("zh_CN", "简体中文"),
    ]
    assert dialog.language.currentData() == ""


def test_language_is_saved_and_noted_as_needing_a_restart(qtbot, store: AppSettings) -> None:
    store.language = "de"
    dialog = make(qtbot, store)
    assert dialog.language.currentData() == "de"
    dialog.language.setCurrentIndex(dialog.language.findData("ru"))
    assert dialog.save() == {"language"}
    assert store.language == "ru"
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert texts.count("Applies after a restart") == 3  # backend, socket, language


def test_locked_language_is_not_saved(qtbot, store: AppSettings) -> None:
    store.language = "fr"
    dialog = make(qtbot, store, language="--language")
    assert not dialog.language.isEnabled()
    assert "--language" in dialog.language.toolTip()
    dialog.language.setCurrentIndex(dialog.language.findData("ru"))
    assert dialog.save() == set()
    assert store.language == "fr"


def test_window_announces_a_restart_after_a_language_change(
    qtbot, context: AppContext, store: AppSettings
) -> None:
    window = MainWindow(context, app_settings=store)
    qtbot.addWidget(window)
    window.open_settings()
    assert window.settings_dialog is not None
    window.settings_dialog.language.setCurrentIndex(window.settings_dialog.language.findData("es"))
    window.settings_dialog.accept()
    assert store.language == "es"
    assert "after a restart" in window.toast.label.text()
