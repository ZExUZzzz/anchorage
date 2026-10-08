from datetime import datetime, timezone

import pytest

from anchorage.docker.errors import ProtocolError
from anchorage.docker.streams import iter_frames, iter_json_lines, iter_lines, iter_log_lines


def frame(stream: int, payload: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def test_json_lines_across_chunk_boundaries() -> None:
    chunks = [b'{"a": 1}\n{"b"', b': 2}\n\n{"c": 3}']
    assert list(iter_json_lines(chunks)) == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_json_lines_rejects_garbage() -> None:
    with pytest.raises(ProtocolError):
        list(iter_json_lines([b"not json\n"]))


def test_iter_lines_strips_cr_and_flushes_tail() -> None:
    assert list(iter_lines([b"one\r\ntw", b"o\nthree"])) == [b"one", b"two", b"three"]


def test_frames_reassembled_from_split_chunks() -> None:
    data = frame(1, b"hello\n") + frame(2, b"oops\n")
    chunks = [data[:3], data[3:11], data[11:]]
    assert list(iter_frames(chunks)) == [(1, b"hello\n"), (2, b"oops\n")]


def test_truncated_frame_is_protocol_error() -> None:
    with pytest.raises(ProtocolError):
        list(iter_frames([frame(1, b"hello")[:-2]]))


def test_log_lines_multiplexed_with_timestamps() -> None:
    chunks = [
        frame(1, b"2026-10-02T20:14:03.118000000Z first\n2026-10-02T20:14:03.200000000Z sec"),
        frame(2, b"2026-10-02T20:14:03.150000000Z err\n"),
        frame(1, b"ond\n"),
    ]
    lines = list(iter_log_lines(chunks, tty=False, timestamps=True))
    assert [(line.stream, line.text) for line in lines] == [
        ("stdout", "first"),
        ("stderr", "err"),
        ("stdout", "second"),
    ]
    assert lines[0].timestamp == datetime(2026, 10, 2, 20, 14, 3, 118000, tzinfo=timezone.utc)


def test_log_lines_flush_partial_line_at_end() -> None:
    lines = list(iter_log_lines([frame(1, b"no newline")], tty=False, timestamps=False))
    assert [line.text for line in lines] == ["no newline"]


def test_log_lines_tty_raw() -> None:
    lines = list(iter_log_lines([b"a\r\nb\n"], tty=True, timestamps=False))
    assert [(line.stream, line.text, line.timestamp) for line in lines] == [
        ("stdout", "a", None),
        ("stdout", "b", None),
    ]


def test_log_lines_keep_text_when_timestamp_unparsable() -> None:
    lines = list(iter_log_lines([b"garbage line\n"], tty=True, timestamps=True))
    assert lines[0].text == "garbage line"
    assert lines[0].timestamp is None


def test_log_lines_decode_invalid_utf8() -> None:
    lines = list(iter_log_lines([b"caf\xe9\n"], tty=True, timestamps=False))
    assert lines[0].text == "caf�"


def test_frames_reject_plain_text() -> None:
    with pytest.raises(ProtocolError, match="not a multiplexed stream"):
        list(iter_frames([b"2026-10-03T10:00:00Z hello from a tty\n"]))


def test_frames_reject_unknown_stream_type() -> None:
    with pytest.raises(ProtocolError, match="not a multiplexed stream"):
        list(iter_frames([bytes([3, 0, 0, 0, 0, 0, 0, 1, 0x41])]))


def test_frames_truncated_header_at_end_of_stream() -> None:
    with pytest.raises(ProtocolError, match="truncated"):
        list(iter_frames([bytes([1, 0, 0, 0, 0])]))
