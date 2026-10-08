"""Parsers for the daemon's streaming body formats.

All functions take an iterable of byte chunks as read from the socket and know nothing
about HTTP. Chunk boundaries carry no meaning: frames and lines may span several chunks.
"""

import json
from collections.abc import Iterable, Iterator
from typing import Any

from anchorage.docker._time import parse_rfc3339
from anchorage.docker.errors import ProtocolError
from anchorage.docker.models import LogLine

STDOUT = 1
STDERR = 2
_HEADER_LEN = 8
_STREAM_NAMES = {0: "stdin", STDOUT: "stdout", STDERR: "stderr"}


def iter_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Split on ``\\n``; strip trailing ``\\r``; flush the last partial line."""
    buffer = bytearray()
    for chunk in chunks:
        buffer += chunk
        while (index := buffer.find(b"\n")) != -1:
            line = bytes(buffer[:index])
            del buffer[: index + 1]
            yield line.rstrip(b"\r")
    if buffer:
        yield bytes(buffer).rstrip(b"\r")


def iter_json_lines(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    for line in iter_lines(chunks):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError as exc:
            raise ProtocolError(f"malformed JSON line: {line[:80]!r}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError(f"unexpected JSON value: {line[:80]!r}")
        yield payload


def iter_frames(chunks: Iterable[bytes]) -> Iterator[tuple[int, bytes]]:
    """Decode the multiplexed stream of ``/containers/{id}/logs`` and ``attach``.

    Each frame is an 8-byte header (stream type, three zero bytes, big-endian payload
    length) followed by the payload.
    """
    buffer = bytearray()
    for chunk in chunks:
        buffer += chunk
        while len(buffer) >= _HEADER_LEN:
            if buffer[0] not in _STREAM_NAMES or any(buffer[1:4]):
                raise ProtocolError("not a multiplexed stream")
            length = int.from_bytes(buffer[4:_HEADER_LEN], "big")
            end = _HEADER_LEN + length
            if len(buffer) < end:
                break
            stream_type = buffer[0]
            payload = bytes(buffer[_HEADER_LEN:end])
            del buffer[:end]
            yield stream_type, payload
    if buffer:
        raise ProtocolError("truncated log frame")


def _make_line(stream: str, raw: bytes, timestamps: bool) -> LogLine:
    text = raw.rstrip(b"\r").decode("utf-8", errors="replace")
    if not timestamps:
        return LogLine(stream=stream, text=text)
    head, sep, rest = text.partition(" ")
    stamp = parse_rfc3339(head) if sep else None
    if stamp is None:
        return LogLine(stream=stream, text=text)
    return LogLine(stream=stream, text=rest, timestamp=stamp)


def iter_log_lines(chunks: Iterable[bytes], *, tty: bool, timestamps: bool) -> Iterator[LogLine]:
    """Yield log lines from either the raw TTY stream or the multiplexed stream."""
    if tty:
        for raw in iter_lines(chunks):
            yield _make_line("stdout", raw, timestamps)
        return

    pending: dict[int, bytes] = {}
    for stream_type, payload in iter_frames(chunks):
        data = pending.pop(stream_type, b"") + payload
        parts = data.split(b"\n")
        tail = parts.pop()
        if tail:
            pending[stream_type] = tail
        name = _STREAM_NAMES.get(stream_type, "stdout")
        for raw in parts:
            yield _make_line(name, raw, timestamps)
    for stream_type, tail in pending.items():
        yield _make_line(_STREAM_NAMES.get(stream_type, "stdout"), tail, timestamps)
