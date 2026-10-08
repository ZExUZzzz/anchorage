"""Human-readable units for the UI."""

import re

from PySide6.QtCore import QLocale

_OPTIONAL_PLURAL = re.compile(r"\(s\)")

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_decimal(value: float) -> str:
    """One decimal place with the decimal separator of the interface language."""
    return QLocale().toString(value, "f", 1)


def format_bytes(value: int | float) -> str:
    size = float(value)
    for unit in _UNITS:
        if size < 1024 or unit == _UNITS[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{format_decimal(size)} {unit}"
        size /= 1024
    return f"{format_decimal(size)} {_UNITS[-1]}"


def format_rate(bytes_per_second: float) -> str:
    return f"{format_bytes(bytes_per_second)}/s"


def english_plural(text: str, n: int) -> str:
    """Resolve the ``(s)`` of an untranslated ``%n thing(s)`` message.

    Qt only substitutes ``%n``; a catalogue supplies real plural forms, but the English source
    has none, so the optional ending is settled here: ``1 container``, ``2 containers``.
    """
    return _OPTIONAL_PLURAL.sub("" if n == 1 else "s", text)
