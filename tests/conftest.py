import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The suite asserts English text: pin Qt's system locale before any Qt object exists, whatever
# the developer's machine is set to.
os.environ["LC_ALL"] = "C"
os.environ["LANG"] = "C"
os.environ["LANGUAGE"] = "en"
os.environ.pop("ANCHORAGE_LANGUAGE", None)


@pytest.fixture(autouse=True)
def english_locale():
    """Every test starts and ends with the English default locale and no translators."""
    from PySide6.QtCore import QLocale

    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    yield
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
