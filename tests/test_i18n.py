import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QLocale

from anchorage.core.settings import LANGUAGE_CODES as SETTING_CODES
from anchorage.ui import i18n
from tests.i18n_catalogue import (
    CATALOGUE_DIR,
    LANGUAGE_CODES,
    Catalogue,
    load_catalogue,
    parse_ts,
)

SAMPLE_TS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="ru" sourcelanguage="en">
<context>
    <name>Sidebar</name>
    <message>
        <source>Containers</source>
        <translation>Контейнеры</translation>
    </message>
</context>
</TS>
"""


def tool(name: str) -> str | None:
    beside = Path(sys.executable).parent / name
    return str(beside) if beside.exists() else shutil.which(name)


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    instance = QCoreApplication.instance()
    assert instance is not None
    yield instance
    i18n.install(instance, "en")


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    lrelease = tool("pyside6-lrelease")
    if lrelease is None:
        pytest.skip("pyside6-lrelease is not available")
    ts = tmp_path / "anchorage_ru.ts"
    ts.write_text(SAMPLE_TS, encoding="utf-8")
    subprocess.run([lrelease, str(ts), "-qm", str(tmp_path / "anchorage_ru.qm")], check=True)
    return tmp_path


def test_languages_match_the_supported_codes() -> None:
    assert tuple(i18n.LANGUAGES) == SETTING_CODES
    assert i18n.LANGUAGES["ru"] == "Русский"
    assert i18n.LANGUAGES["zh_CN"] == "简体中文"


def test_english_installs_no_translator(qtbot, app) -> None:  # type: ignore[no-untyped-def]
    assert i18n.install(app, "en") == "en"
    assert QCoreApplication.translate("Sidebar", "Containers") == "Containers"
    assert QLocale().language() == QLocale.Language.English


def test_installed_catalogue_translates_and_sets_the_locale(
    qtbot, app, sample_dir: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(i18n, "CATALOGUE_DIR", sample_dir)
    assert i18n.install(app, "ru") == "ru"
    assert QCoreApplication.translate("Sidebar", "Containers") == "Контейнеры"
    assert QLocale().language() == QLocale.Language.Russian
    assert i18n.install(app, "en") == "en"
    assert QCoreApplication.translate("Sidebar", "Containers") == "Containers"


def test_installing_twice_does_not_stack_translators(
    qtbot, app, sample_dir: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(i18n, "CATALOGUE_DIR", sample_dir)
    i18n.install(app, "ru")
    i18n.install(app, "ru")
    assert len(i18n._installed) <= 2
    i18n.install(app, "en")
    assert i18n._installed == []


def test_missing_catalogue_falls_back_to_english(qtbot, app, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(i18n, "CATALOGUE_DIR", tmp_path)
    assert i18n.install(app, "de") == "en"
    assert QCoreApplication.translate("Sidebar", "Containers") == "Containers"


def test_missing_qt_translations_are_not_an_error(
    qtbot, app, sample_dir: Path, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    class NoQt:
        class LibraryPath:
            TranslationsPath = object()

        @staticmethod
        def path(_which: object) -> str:
            return str(tmp_path / "nowhere")

    monkeypatch.setattr(i18n, "CATALOGUE_DIR", sample_dir)
    monkeypatch.setattr(i18n, "QLibraryInfo", NoQt)
    assert i18n.install(app, "ru") == "ru"
    assert QCoreApplication.translate("Sidebar", "Containers") == "Контейнеры"


@pytest.mark.parametrize("value", ["klingon", "xx_YY", "zh_TW", None])
def test_unknown_language_follows_the_system(qtbot, app, value: str | None, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(i18n, "system_language", lambda ui_languages=None: "en")
    assert i18n.install(app, value or "") == "en"


@pytest.mark.parametrize(
    ("tags", "code"),
    [
        (["ru-RU", "en-US"], "ru"),
        (["pt-BR", "de-DE"], "de"),
        (["en-US", "ru"], "en"),
        (["zh-Hans-CN"], "zh_CN"),
        (["zh-CN"], "zh_CN"),
        (["zh-Hant-TW", "fr-FR"], "fr"),
        (["zh-TW"], "en"),
        (["xx"], "en"),
        ([], "en"),
    ],
)
def test_system_language_picks_the_first_supported(tags: list[str], code: str) -> None:
    assert i18n.system_language(tags) == code


def test_shipped_catalogues_load_for_every_language(qtbot, app) -> None:  # type: ignore[no-untyped-def]
    for code in LANGUAGE_CODES:
        assert (CATALOGUE_DIR / f"anchorage_{code}.qm").is_file()
        assert i18n.install(app, code) == code


def test_catalogue_files_exist_and_name_their_language() -> None:
    for code in LANGUAGE_CODES:
        catalogue = load_catalogue(code)
        assert catalogue.language == code
        assert catalogue.messages


def test_catalogues_hold_the_same_sources() -> None:
    reference = load_catalogue("ru").keys()
    for code in LANGUAGE_CODES:
        assert load_catalogue(code).keys() == reference, code


def test_catalogues_carry_the_plural_forms_of_their_language() -> None:
    forms = {"ru": 3, "de": 2, "es": 2, "fr": 2, "zh_CN": 1}
    for code, count in forms.items():
        plural = [m for m in load_catalogue(code).messages if m.numerus]
        assert plural, code
        assert {len(m.translations) for m in plural} == {count}, code
    sources = {m.source for m in load_catalogue("ru").messages if m.numerus}
    assert "%n container(s)" in sources


def test_parse_ts_reads_translations_and_state(tmp_path: Path) -> None:
    ts = tmp_path / "x.ts"
    ts.write_text(
        SAMPLE_TS.replace(
            "</context>",
            """    <message numerus="yes">
        <source>%n image(s)</source>
        <translation type="unfinished">
            <numerusform></numerusform><numerusform></numerusform>
        </translation>
    </message>
</context>""",
        ),
        encoding="utf-8",
    )
    catalogue: Catalogue = parse_ts(ts)
    done, pending = catalogue.messages
    assert done.translated and done.translations == ("Контейнеры",)
    assert pending.numerus and pending.unfinished and not pending.translated
    assert len(pending.translations) == 2


def test_catalogues_are_current_with_the_sources(tmp_path: Path) -> None:
    """A string wrapped (or unwrapped) without running tools/update_translations.sh fails."""
    lupdate = tool("pyside6-lupdate")
    if lupdate is None:
        pytest.skip("pyside6-lupdate is not available")
    fresh = tmp_path / "fresh.ts"
    source = Path(i18n.__file__).resolve().parents[1]
    subprocess.run(
        [
            lupdate,
            "-extensions",
            "py",
            "-no-obsolete",
            "-locations",
            "none",
            str(source),
            "-ts",
            str(fresh),
        ],
        check=True,
        capture_output=True,
    )
    assert parse_ts(fresh).keys() == load_catalogue("ru").keys()
