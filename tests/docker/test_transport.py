import os
import threading
from pathlib import Path

import pytest

from anchorage.docker.errors import (
    Conflict,
    EngineUnavailable,
    NotFound,
    PermissionDenied,
    ProtocolError,
    ServerError,
    Timeout,
)
from anchorage.docker.transport import Transport
from tests.docker.fake_daemon import FakeDaemon


def test_request_returns_json_and_prefixes_version(daemon: FakeDaemon) -> None:
    daemon.add_json("GET", "/version", {"Version": "29.8.2"})
    response = Transport(daemon.socket_path).request("GET", "/version")
    assert response.status == 200
    assert response.json() == {"Version": "29.8.2"}
    assert daemon.last().path == "/version"


def test_query_encoding(daemon: FakeDaemon) -> None:
    daemon.add_json("GET", "/containers/json", [])
    Transport(daemon.socket_path).request(
        "GET",
        "/containers/json",
        query={"all": True, "limit": 5, "skip": None, "filters": {"type": ["container"]}},
    )
    assert daemon.last().query == {
        "all": "true",
        "limit": "5",
        "filters": '{"type": ["container"]}',
    }


def test_json_body_is_sent(daemon: FakeDaemon) -> None:
    daemon.add_json("POST", "/containers/create", {"Id": "x"}, status=201)
    response = Transport(daemon.socket_path).request(
        "POST", "/containers/create", body={"Image": "busybox"}
    )
    assert response.status == 201
    assert daemon.last().body == b'{"Image": "busybox"}'


def test_empty_204_response(daemon: FakeDaemon) -> None:
    daemon.add_raw("POST", "/containers/x/start", b"", status=204)
    response = Transport(daemon.socket_path).request("POST", "/containers/x/start")
    assert response.status == 204
    assert response.body == b""


def test_error_status_maps_to_typed_error(daemon: FakeDaemon) -> None:
    daemon.add_json("GET", "/containers/nope/json", {"message": "No such container: nope"}, 404)
    daemon.add_json("DELETE", "/containers/busy", {"message": "running"}, 409)
    daemon.add_raw("GET", "/boom", b"<html>bad gateway</html>", 502, "text/html")
    daemon.add_raw("GET", "/empty", b"", 500)
    transport = Transport(daemon.socket_path)
    with pytest.raises(NotFound, match="No such container"):
        transport.request("GET", "/containers/nope/json")
    with pytest.raises(Conflict, match="running"):
        transport.request("DELETE", "/containers/busy")
    with pytest.raises(ServerError, match="bad gateway"):
        transport.request("GET", "/boom")
    with pytest.raises(ServerError, match="HTTP 500"):
        transport.request("GET", "/empty")


def test_missing_socket_is_engine_unavailable(tmp_path: Path) -> None:
    with pytest.raises(EngineUnavailable):
        Transport(str(tmp_path / "missing.sock")).request("GET", "/_ping")


def test_unreadable_socket_is_permission_denied(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    path = tmp_path / "locked.sock"
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(1)
        path.chmod(0)
        with pytest.raises(PermissionDenied):
            Transport(str(path)).request("GET", "/_ping")


def test_stream_yields_chunks_until_end(daemon: FakeDaemon) -> None:
    daemon.add_stream("GET", "/events", [b'{"a":1}\n', b'{"b":2}\n'])
    stream = Transport(daemon.socket_path).stream("GET", "/events")
    assert b"".join(stream.chunks()) == b'{"a":1}\n{"b":2}\n'
    assert stream.closed is False
    stream.close()
    assert stream.closed is True


def test_stream_error_status_raises_on_first_chunk(daemon: FakeDaemon) -> None:
    daemon.add_json("GET", "/containers/nope/logs", {"message": "No such container"}, 404)
    stream = Transport(daemon.socket_path).stream("GET", "/containers/nope/logs")
    with pytest.raises(NotFound, match="No such container"):
        next(stream.chunks())


def test_close_while_headers_pending_unblocks_reader(daemon: FakeDaemon) -> None:
    hold_headers = threading.Event()
    daemon.add_stream("GET", "/events", [b'{"a":1}\n'], hold_headers=hold_headers)
    stream = Transport(daemon.socket_path).stream("GET", "/events")
    received: list[bytes] = []
    errors: list[BaseException] = []
    finished = threading.Event()

    def reader() -> None:
        try:
            received.extend(stream.chunks())
        except BaseException as exc:
            errors.append(exc)
        finished.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    assert not finished.wait(timeout=0.3), "reader should be blocked waiting for headers"
    stream.close()
    assert finished.wait(timeout=2), "reader did not stop after close()"
    hold_headers.set()
    thread.join(timeout=2)
    assert received == []
    assert errors == []


@pytest.mark.parametrize("connection_close", [False, True], ids=["chunked", "connection-close"])
def test_close_unblocks_reader_in_other_thread(daemon: FakeDaemon, connection_close: bool) -> None:
    hold = threading.Event()
    daemon.add_stream(
        "GET", "/events", [b'{"a":1}\n'], hold=hold, connection_close=connection_close
    )
    stream = Transport(daemon.socket_path).stream("GET", "/events")
    received: list[bytes] = []
    finished = threading.Event()

    def reader() -> None:
        for chunk in stream.chunks():
            received.append(chunk)
        finished.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = threading.Event()
    for _ in range(100):
        if received:
            break
        deadline.wait(0.02)
    assert received == [b'{"a":1}\n']
    stream.close()
    assert finished.wait(timeout=2), "reader did not stop after close()"
    hold.set()


def test_unexpected_disconnect_is_protocol_error(daemon: FakeDaemon) -> None:
    daemon.add_stream("GET", "/events", [b'{"a":1}\n'], abort=True)
    stream = Transport(daemon.socket_path).stream("GET", "/events")
    chunks = stream.chunks()
    assert next(chunks) == b'{"a":1}\n'
    with pytest.raises(ProtocolError):
        next(chunks)


def test_slow_response_is_timeout_not_engine_unavailable(daemon: FakeDaemon) -> None:
    daemon.add_raw("GET", "/slow", b"ok", delay=0.5)
    with pytest.raises(Timeout):
        Transport(daemon.socket_path, timeout=0.1).request("GET", "/slow")


def test_per_request_timeout_overrides_default(daemon: FakeDaemon) -> None:
    daemon.add_raw("GET", "/slow", b"ok", delay=0.3)
    transport = Transport(daemon.socket_path, timeout=0.05)
    assert transport.request("GET", "/slow", timeout=5).body == b"ok"


def test_stream_headers_are_not_bound_by_connect_timeout(daemon: FakeDaemon) -> None:
    daemon.add_stream("POST", "/images/create", [b'{"a":1}\n'], delay=0.4)
    transport = Transport(daemon.socket_path, connect_timeout=0.1)
    stream = transport.stream("POST", "/images/create")
    assert b"".join(stream.chunks()) == b'{"a":1}\n'
    stream.close()
