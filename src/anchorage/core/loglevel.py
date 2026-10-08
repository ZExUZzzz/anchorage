"""Guess a log line's severity from the level marker most log formats put near its start."""

from __future__ import annotations

import re

# Level markers appear right after the application's own timestamp, so only the head of a
# line is inspected; a word such as "error" deep inside a message is not a level.
_WINDOW = 64

# A marker is a known level word delimited by brackets, quotes, '=' or ':' (``[ERROR]``,
# ``level=warning``, ``"level":"warn"``, ``WARN[0000]``, ``ERROR:root:``, ``FATAL:``) or
# standing alone as a word.
_ERROR = re.compile(
    r"(?i)(?:^|[\s\[(<\"'=:])"
    r"(?:error|err|erro|fatal|panic|crit|critical|emerg|emergency|alert|severe)"
    r"(?:[\])>\"':\s\[-]|$)"
)
_WARN = re.compile(r"(?i)(?:^|[\s\[(<\"'=:])(?:warn|warning)(?:[\])>\"':\s\[-]|$)")


def detect_level(text: str) -> str | None:
    """Return ``"error"``, ``"warn"`` or ``None`` for a log line."""
    head = text[:_WINDOW]
    if _ERROR.search(head):
        return "error"
    if _WARN.search(head):
        return "warn"
    return None
