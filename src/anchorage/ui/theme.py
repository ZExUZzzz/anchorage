"""Palette-based stylesheet, state colours and icon lookup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyle

from anchorage import APP_ID

ICON_PATH = Path(__file__).resolve().parents[1] / "data" / "icon.svg"


def app_icon() -> QIcon:
    """The desktop theme's icon for our application ID, else the bundled SVG."""
    themed = QIcon.fromTheme(APP_ID)
    if not themed.isNull():
        return themed
    return QIcon(str(ICON_PATH)) if ICON_PATH.is_file() else QIcon()


STYLESHEET = """
QWidget#sidebar { background: palette(window); border-right: 1px solid palette(mid); }
QLabel#brand { font-size: 15px; font-weight: 700; padding: 6px 4px; }
QListWidget#nav { background: transparent; border: none; outline: none; }
QListWidget#nav::item { padding: 7px 10px; border-radius: 6px; margin: 1px 0; }
QListWidget#nav::item:hover { background: palette(button); }
QListWidget#nav::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QListWidget#nav::item:disabled { color: palette(placeholder-text); }

QWidget#content { background: palette(window); }
QLabel#pageTitle { font-size: 18px; font-weight: 700; }
QLabel#crumb { color: palette(placeholder-text); }
QLabel#muted { color: palette(placeholder-text); }
QLabel#title { font-size: 15px; font-weight: 600; }
QLabel#section { font-weight: 700; font-size: 11px; color: palette(placeholder-text); }
QToolButton#back { border: 1px solid palette(mid); border-radius: 6px; padding: 3px 8px; background: palette(button); }
QToolButton#back:hover { background: palette(midlight); }

QLineEdit#filter, QLineEdit#logsearch {
    background: palette(base); border: 1px solid palette(mid); border-radius: 7px; padding: 4px 10px;
}
QLineEdit#filter:focus, QLineEdit#logsearch:focus { border-color: palette(highlight); }

QPushButton { padding: 5px 12px; border-radius: 6px; border: 1px solid palette(mid); background: palette(button); }
QPushButton:hover { background: palette(midlight); }
QPushButton:pressed { background: palette(dark); }
QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); border-color: palette(highlight); }
QPushButton#settingsButton { text-align: left; }
QPushButton#primary { background: palette(highlight); color: palette(highlighted-text); border-color: palette(highlight); }
QPushButton:disabled { color: palette(placeholder-text); }
QPushButton#primary:disabled { background: palette(button); color: palette(placeholder-text); border-color: palette(mid); }

QTreeView#containers, QTableView, QTreeWidget {
    border: 1px solid palette(mid); border-radius: 8px; background: palette(base);
    alternate-background-color: palette(alternate-base);
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text); outline: none;
}
QTreeView#containers { show-decoration-selected: 1; }
QTreeView#containers::item { border-bottom: 1px solid palette(alternate-base); }
QTreeView#containers::branch { background: transparent; border: none; image: none; }
QTableView::item { padding: 2px 8px; }
QHeaderView::section {
    background: palette(window); border: none; border-bottom: 1px solid palette(mid);
    border-right: 1px solid palette(mid); padding: 4px 8px; font-weight: 600;
}

QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }
QToolButton#linkButton { border: none; background: transparent; color: palette(link); padding: 0 2px; }
QToolButton#linkButton:hover { text-decoration: underline; }
QTableWidget#members { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); }
QFrame#toast { background: palette(base); border: 1px solid palette(highlight); border-radius: 8px; }
QTabWidget::pane { border: 1px solid palette(mid); border-radius: 6px; top: -1px; background: palette(base); }
QTabBar::tab { padding: 5px 14px; border: 1px solid transparent; border-bottom: none; margin-right: 2px; }
QTabBar::tab:selected { border-color: palette(mid); border-top-left-radius: 6px; border-top-right-radius: 6px; background: palette(base); }
QStatusBar { border-top: 1px solid palette(mid); }
QStatusBar QLabel { padding: 0 6px; }
QPlainTextEdit#logs { background: palette(base); border: none; }
QProgressBar { border: 1px solid palette(mid); border-radius: 4px; background: palette(base); text-align: center; }
QProgressBar::chunk { background: palette(highlight); border-radius: 3px; }
"""

_STATE_HUES = {"running": 130, "paused": 45, "restarting": 45, "removing": 45}
_LEVEL_HUES = {"error": 0, "warn": 45, "info": 130}


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def _hue_color(hue: int, palette: QPalette) -> QColor:
    color = QColor()
    color.setHslF(hue / 360, 0.6, 0.55 if is_dark(palette) else 0.38)
    return color


def state_color(state: str, palette: QPalette) -> QColor:
    hue = _STATE_HUES.get(state)
    if hue is None:
        return palette.color(QPalette.ColorRole.PlaceholderText)
    return _hue_color(hue, palette)


def level_color(level: str, palette: QPalette) -> QColor:
    return _hue_color(_LEVEL_HUES.get(level, 0), palette)


def icon(name: str, fallback: QStyle.StandardPixmap | None = None) -> QIcon:
    result = QIcon.fromTheme(name)
    if result.isNull() and fallback is not None:
        style = QApplication.style()
        if style is not None:
            return style.standardIcon(fallback)
    return result
