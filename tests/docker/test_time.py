from datetime import datetime, timezone

from anchorage.docker._time import from_unix, parse_rfc3339


def test_parse_nanosecond_timestamp() -> None:
    value = parse_rfc3339("2026-10-02T17:14:02.123456789Z")
    assert value == datetime(
        2026,
        10,
        2,
        17,
        14,
        2,
        123456,
        tzinfo=timezone.utc,
    )


def test_parse_timestamp_without_fraction() -> None:
    assert parse_rfc3339("2026-10-02T17:14:02Z") == datetime(
        2026,
        10,
        2,
        17,
        14,
        2,
        tzinfo=timezone.utc,
    )


def test_parse_timestamp_with_offset() -> None:
    value = parse_rfc3339("2026-10-02T20:14:02.5+03:00")
    assert value is not None
    assert value.astimezone(timezone.utc) == datetime(
        2026,
        10,
        2,
        17,
        14,
        2,
        500000,
        tzinfo=timezone.utc,
    )


def test_unset_timestamp_is_none() -> None:
    assert parse_rfc3339("0001-01-01T00:00:00Z") is None
    assert parse_rfc3339("") is None
    assert parse_rfc3339(None) is None


def test_garbage_timestamp_is_none() -> None:
    assert parse_rfc3339("yesterday") is None


def test_from_unix() -> None:
    assert from_unix(1_700_000_000) == datetime(
        2023,
        11,
        14,
        22,
        13,
        20,
        tzinfo=timezone.utc,
    )
