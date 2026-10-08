"""Interface translations: pick the language and install the Qt translators."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

from anchorage.core.settings import LANGUAGE_CODES, normalize_language

log = logging.getLogger(__name__)

# Code -> the language written in itself, as shown in the settings dialog.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "ru": "Русский",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "zh_CN": "简体中文",
}

CATALOGUE_DIR = Path(__file__).resolve().parents[1] / "i18n"

_installed: list[QTranslator] = []


def catalogue_path(language: str) -> Path:
    return CATALOGUE_DIR / f"anchorage_{language}.qm"


def system_language(ui_languages: list[str] | None = None) -> str:
    """The first supported language among the system's preferred ones, else ``"en"``."""
    tags = QLocale.system().uiLanguages() if ui_languages is None else ui_languages
    for tag in tags:
        parts = tag.replace("_", "-").split("-")
        base = parts[0].lower()
        if base == "zh":
            # Only Simplified Chinese is shipped; Traditional variants fall through.
            rest = {part.lower() for part in parts[1:]}
            if not rest & {"hant", "tw", "hk", "mo"}:
                return "zh_CN"
            continue
        if base in LANGUAGE_CODES:
            return base
    return "en"


def _load(translator: QTranslator, name: str, directory: str) -> bool:
    try:
        return bool(translator.load(name, directory))
    except Exception:  # pragma: no cover - a broken file must not stop the application
        log.warning("cannot read translation %s in %s", name, directory, exc_info=True)
        return False


def install(app: QCoreApplication, language: str = "") -> str:
    """Install the application and Qt translators; return the effective language code.

    ``language`` is a supported code or ``""`` for the system language. A missing catalogue
    or missing Qt translations never raise: the interface then stays English (``"en"``), and
    Qt's own dialogs stay English when ``qtbase_<code>.qm`` is not installed.
    """
    for old in _installed:
        app.removeTranslator(old)
    _installed.clear()

    code = normalize_language(language) or system_language()
    if code != "en":
        own = QTranslator(app)
        if _load(own, f"anchorage_{code}", str(CATALOGUE_DIR)):
            app.installTranslator(own)
            _installed.append(own)
        else:
            log.warning("no translation catalogue for %r; using English", code)
            code = "en"
    if code != "en":
        qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        qt = QTranslator(app)
        if _load(qt, f"qtbase_{code}", qt_path):
            app.installTranslator(qt)
            _installed.append(qt)
        else:
            log.info("Qt translations for %r not found in %s", code, qt_path)
    locale = QLocale(code)
    QLocale.setDefault(locale)
    return code
