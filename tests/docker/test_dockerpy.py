"""docker-py backend specifics: error mapping and unreachable daemons."""

import gc
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from anchorage.docker.errors import (
    Conflict,
    DockerError,
    EngineUnavailable,
    NotFound,
    PermissionDenied,
    ProtocolError,
    ServerError,
    Timeout,
)

docker = pytest.importorskip("docker")

from anchorage.docker.dockerpy import DockerPyClient, map_error  # noqa: E402


@pytest.fixture
def new_client() -> Iterator[Callable[[str], DockerPyClient]]:
    created: list[DockerPyClient] = []

    def make(socket_path: str) -> DockerPyClient:
        created.append(DockerPyClient(socket_path))
        return created[-1]

    yield make
    for client in created:
        client.close()


def test_client_satisfies_engine_api(daemon, new_client) -> None:  # type: ignore[no-untyped-def]
    from anchorage.docker.client import EngineAPI

    api: EngineAPI = new_client(daemon.socket_path)
    assert api.socket_path == daemon.socket_path


def test_dockerpy_maps_api_errors(daemon, new_client) -> None:  # type: ignore[no-untyped-def]
    daemon.add_json("GET", "/containers/missing/json", {"message": "No such container"}, 404)
    daemon.add_json("POST", "/containers/abc/start", {"message": "already started"}, 409)
    daemon.add_json("GET", "/version", {"message": "boom"}, 500)
    client = new_client(daemon.socket_path)
    with pytest.raises(NotFound) as exc:
        client.inspect_container("missing")
    assert exc.value.message == "No such container"
    with pytest.raises(Conflict):
        client.start_container("abc")
    with pytest.raises(ServerError):
        client.version()


# docker-py's UnixHTTPConnection leaks its socket when connect() fails; collect it here so the
# warning cannot surface in an unrelated test.
@pytest.mark.filterwarnings("ignore::ResourceWarning")
def test_dockerpy_unreachable_socket(tmp_path, new_client) -> None:  # type: ignore[no-untyped-def]
    client = new_client(str(tmp_path / "nope.sock"))
    with pytest.raises(EngineUnavailable):
        client.ping()
    gc.collect()


def test_map_error_passes_docker_errors_through() -> None:
    err = NotFound("x", 404)
    assert map_error(err, "/tmp/x.sock") is err


def test_dockerpy_stream_close_is_safe_from_another_thread(daemon, new_client) -> None:  # type: ignore[no-untyped-def]
    # docker-py's events() sends the request eagerly, so the headers are not held back here: the
    # reader gets the first item and then blocks in the socket read until ``hold`` is released.
    hold = threading.Event()
    daemon.add_stream(
        "GET", "/events", [b'{"Type": "container", "Action": "start", "time": 1}\n'], hold=hold
    )
    stream = new_client(daemon.socket_path).events()
    items: list[object] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            items.extend(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(0.2)  # let the reader consume the first item and block in the socket read
    stream.close()
    assert stream.closed is True
    thread.join(timeout=5)
    assert not thread.is_alive()  # close() alone ends the read; the hold is still in place
    hold.set()
    assert errors == []
    assert len(items) <= 1


def test_dockerpy_truncated_log_stream_is_a_protocol_error(daemon, new_client) -> None:  # type: ignore[no-untyped-def]
    daemon.add_stream("GET", "/containers/abc/logs", [b"partial\n"], abort=True)
    stream = new_client(daemon.socket_path).logs("abc", tty=True)
    with pytest.raises(ProtocolError):
        list(stream)
    assert stream.closed is True


def test_dockerpy_followed_streams_outlive_the_request_timeout(daemon) -> None:  # type: ignore[no-untyped-def]
    logs_hold, stats_hold = threading.Event(), threading.Event()
    daemon.add_stream(
        "GET", "/containers/abc/logs", [b"line one\n"], hold=logs_hold, content_type="text/plain"
    )
    daemon.add_stream(
        "GET", "/containers/abc/stats", [b'{"read": "2026-01-01T00:00:00Z"}\n'], hold=stats_hold
    )
    client = DockerPyClient(daemon.socket_path, timeout=0.5)
    try:
        for stream, hold in (
            (client.logs("abc", tty=True), logs_hold),
            (client.stats("abc"), stats_hold),
        ):
            errors: list[BaseException] = []
            items: list[object] = []

            def reader(stream=stream, errors=errors, items=items) -> None:  # type: ignore[no-untyped-def]
                try:
                    items.extend(stream)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            thread.join(timeout=1.5)
            assert thread.is_alive(), f"stream ended early: {errors}"
            assert errors == []
            hold.set()
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert errors == []
            assert len(items) == 1
    finally:
        logs_hold.set()
        stats_hold.set()
        client.close()


def _api_error(status: int | None) -> Exception:
    import requests

    response = None
    if status is not None:
        response = requests.Response()
        response.status_code = status
    return docker.errors.APIError("boom", response=response, explanation="gone")


def _map_error_cases() -> list[tuple[str, Exception, type[DockerError]]]:
    import requests
    import urllib3.exceptions as u3

    read_timeout = u3.ReadTimeoutError(None, "/x", "Read timed out")  # type: ignore[arg-type]
    return [
        ("ReadTimeout", requests.exceptions.ReadTimeout("t"), Timeout),
        ("ConnectTimeout", requests.exceptions.ConnectTimeout("t"), Timeout),
        ("urllib3 ReadTimeoutError", read_timeout, Timeout),
        ("wrapped ReadTimeoutError", requests.exceptions.ConnectionError(read_timeout), Timeout),
        (
            "EACCES",
            requests.exceptions.ConnectionError("[Errno 13] Permission denied"),
            PermissionDenied,
        ),
        (
            "EACCES token",
            requests.exceptions.ConnectionError("PermissionError EACCES"),
            PermissionDenied,
        ),
        (
            "no such file",
            requests.exceptions.ConnectionError("[Errno 2] No such file or directory"),
            EngineUnavailable,
        ),
        ("chunked", requests.exceptions.ChunkedEncodingError("cut"), ProtocolError),
        ("api 404", _api_error(404), NotFound),
        ("api no response", _api_error(None), DockerError),
        ("invalid version", docker.errors.InvalidVersion("old"), DockerError),
    ]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [pytest.param(e, t, id=name) for name, e, t in _map_error_cases()],
)
def test_map_error_table(exc: Exception, expected: type[DockerError]) -> None:
    mapped = map_error(exc, "/tmp/x.sock")
    if expected is DockerError:
        assert type(mapped) is DockerError
    else:
        assert isinstance(mapped, expected)


@pytest.mark.parametrize("kind", ["logs", "stats"])
def test_dockerpy_close_ends_a_followed_read_blocked_in_the_body(daemon, new_client, kind) -> None:  # type: ignore[no-untyped-def]
    hold = threading.Event()
    if kind == "logs":
        daemon.add_stream(
            "GET", "/containers/abc/logs", [b"one\n"], hold=hold, content_type="text/plain"
        )
    else:
        daemon.add_stream(
            "GET", "/containers/abc/stats", [b'{"read": "2026-01-01T00:00:00Z"}\n'], hold=hold
        )
    client = new_client(daemon.socket_path)
    stream = client.logs("abc", tty=True) if kind == "logs" else client.stats("abc")
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(0.3)  # the reader has the first item and blocks in the body read
    closer = threading.Thread(target=stream.close, daemon=True)
    closer.start()
    closer.join(timeout=5)
    assert not closer.is_alive(), "close() hung on the blocked read"
    thread.join(timeout=5)
    assert not thread.is_alive()  # the hold is still in place
    hold.set()
    assert errors == []
