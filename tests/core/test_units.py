from anchorage.core.units import format_bytes, format_rate


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(999) == "999 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(48_300_000) == "46.1 MB"
    assert format_bytes(16 * 1024**3) == "16.0 GB"
    assert format_bytes(3 * 1024**4) == "3.0 TB"


def test_format_rate() -> None:
    assert format_rate(0) == "0 B/s"
    assert format_rate(1536) == "1.5 KB/s"
