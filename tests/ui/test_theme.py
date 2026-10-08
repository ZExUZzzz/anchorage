from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QStyle

from anchorage.ui import theme


def dark_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#202326"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7f8c8d"))
    return pal


def light_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#efefef"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#808080"))
    return pal


def test_stylesheet_has_no_literal_colours() -> None:
    import re

    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", theme.STYLESHEET)
    assert "palette(window)" in theme.STYLESHEET


def test_disabled_primary_button_is_restyled() -> None:
    assert "QPushButton#primary:disabled" in theme.STYLESHEET


def test_is_dark() -> None:
    assert theme.is_dark(dark_palette()) is True
    assert theme.is_dark(light_palette()) is False


def test_state_colours_adapt_to_palette() -> None:
    dark_green = theme.state_color("running", dark_palette())
    light_green = theme.state_color("running", light_palette())
    assert dark_green.lightness() > light_green.lightness()
    assert theme.state_color("exited", dark_palette()) == QColor("#7f8c8d")
    assert (
        theme.state_color("paused", dark_palette()).hue()
        == theme.state_color("restarting", dark_palette()).hue()
    )
    assert theme.level_color("error", dark_palette()).hue() in (0, 359, 360)


def test_icon_falls_back_to_standard_pixmap(qtbot) -> None:
    icon = theme.icon("definitely-not-an-icon-name", QStyle.StandardPixmap.SP_BrowserReload)
    assert not icon.isNull()


def test_app_icon_renders(qtbot) -> None:
    from anchorage.ui.theme import ICON_PATH, app_icon

    assert ICON_PATH.is_file()
    assert not app_icon().pixmap(32).isNull()


def test_app_icon_missing_file_returns_null_icon(qtbot, monkeypatch, tmp_path) -> None:
    from anchorage.ui import theme

    monkeypatch.setattr(theme, "ICON_PATH", tmp_path / "missing.svg")
    # The offscreen platform has no icon theme, so fromTheme(APP_ID) is null here.
    assert theme.app_icon().isNull()
