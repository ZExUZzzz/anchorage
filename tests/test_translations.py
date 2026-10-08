"""The shipped catalogues are complete, keep their placeholders and load into the app."""

import re

import pytest
from PySide6.QtCore import QCoreApplication

from anchorage.ui import i18n
from anchorage.ui.containers.details_tree import health_text
from anchorage.ui.theme import state_text
from tests.i18n_catalogue import LANGUAGE_CODES, Message, load_catalogue

PLURAL_FORMS = {"ru": 3, "de": 2, "es": 2, "fr": 2, "zh_CN": 1}
# Index of the plural form Qt picks for a count (Qt's rules for these languages).
PLURAL_INDEX = {
    "ru": lambda n: (
        0
        if n % 10 == 1 and n % 100 != 11
        else 1
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
        else 2
    ),
    "de": lambda n: 0 if n == 1 else 1,
    "es": lambda n: 0 if n == 1 else 1,
    "fr": lambda n: 0 if n < 2 else 1,
    "zh_CN": lambda n: 0,
}
PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}|%n|%\d+")


def placeholders(text: str) -> list[str]:
    return sorted(PLACEHOLDER.findall(text))


@pytest.fixture
def app() -> QCoreApplication:
    instance = QCoreApplication.instance()
    assert instance is not None
    return instance  # conftest removes the translators after each test


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_every_message_is_translated(code: str) -> None:
    missing = [m.key for m in load_catalogue(code).messages if not m.translated]
    assert missing == [], code


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_plural_messages_have_the_forms_of_their_language(code: str) -> None:
    for message in load_catalogue(code).messages:
        expected = PLURAL_FORMS[code] if message.numerus else 1
        assert len(message.translations) == expected, (code, message.key)


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_translations_keep_every_placeholder(code: str) -> None:
    for message in load_catalogue(code).messages:
        wanted = placeholders(message.source)
        for form in message.translations:
            assert placeholders(form) == wanted, (code, message.source, form)


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_translations_drop_the_english_plural_marker(code: str) -> None:
    for message in load_catalogue(code).messages:
        if message.numerus:
            assert all("(s)" not in form for form in message.translations), (code, message)


def single(message: Message) -> str:
    (text,) = message.translations
    return text


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_installed_language_translates_like_its_catalogue(qtbot, app, code: str) -> None:  # type: ignore[no-untyped-def]
    catalogue = load_catalogue(code)
    sidebar = next(m for m in catalogue.messages if m.key == ("Sidebar", "Containers", ""))
    assert i18n.install(app, code) == code
    assert QCoreApplication.translate("Sidebar", "Containers") == single(sidebar)
    assert single(sidebar) != "Containers"
    # The compiled .qm matches the catalogue: it was rebuilt after the last edit.
    counts = (1, 2, 5) if code == "ru" else (1, 2)
    for message in catalogue.messages:
        comment = message.comment or None
        if not message.numerus:
            shown = QCoreApplication.translate(message.context, message.source, comment)
            assert shown == single(message), (code, message.key)
            continue
        for n in counts:
            shown = QCoreApplication.translate(message.context, message.source, comment, n)
            form = message.translations[PLURAL_INDEX[code](n)]
            assert shown == form.replace("%n", str(n)), (code, message.key, n)


def test_russian_plural_forms_follow_the_count(qtbot, app) -> None:  # type: ignore[no-untyped-def]
    i18n.install(app, "ru")
    texts = [QCoreApplication.translate("MainWindow", "%n image(s)", "", n) for n in (1, 3, 5, 21)]
    assert texts == ["1 образ", "3 образа", "5 образов", "21 образ"]


def test_chinese_has_a_single_plural_form(qtbot, app) -> None:  # type: ignore[no-untyped-def]
    i18n.install(app, "zh_CN")
    texts = {QCoreApplication.translate("MainWindow", "%n image(s)", "", n) for n in (1, 2)}
    assert texts == {"1 个镜像", "2 个镜像"}


def test_container_states_are_shown_translated_and_unknown_ones_raw(qtbot, app) -> None:  # type: ignore[no-untyped-def]
    assert state_text("running") == "running"
    assert state_text("weird") == "weird"
    i18n.install(app, "ru")
    assert state_text("running") == "работает"
    assert state_text("exited") == "завершён"
    assert state_text("weird") == "weird"
    assert state_text("") == ""


def test_health_states_are_shown_translated_and_unknown_ones_raw(qtbot, app) -> None:  # type: ignore[no-untyped-def]
    assert health_text("healthy") == "healthy"
    i18n.install(app, "de")
    assert health_text("unhealthy") == "ungesund"
    assert health_text("weird") == "weird"
