"""Timestamp helpers for daemon payloads."""

import re
from datetime import datetime, timezone

_UNSET_PREFIX = "0001-01-01"
_SPLIT = re.compile(r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?(?P<zone>.*)$")


def parse_rfc3339(value: str | None) -> datetime | None:
    """Parse an RFC 3339 timestamp with up to nine fractional digits.

    Returns None for empty values, the daemon's zero time and unparsable input.
    """
    if not value or value.startswith(_UNSET_PREFIX):
        return None
    match = _SPLIT.match(value)
    if match is None:
        return None
    frac = (match.group("frac") or "")[:7]
    zone = match.group("zone")
    if zone == "Z":
        zone = "+00:00"
    try:
        return datetime.fromisoformat(f"{match.group('base')}{frac}{zone}")
    except ValueError:
        return None


def from_unix(seconds: int | float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)
