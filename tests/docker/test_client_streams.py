import json
import threading
from collections.abc import Callable

import pytest

from anchorage.docker.client import EngineAPI, Stream
from anchorage.docker.errors import ServerError
from tests.docker.conftest import assert_query
from tests.docker.fake_daemon import FakeDaemon
from tests.docker.test_models_stats import SAMPLE

ClientFactory = Callable[[FakeDaemon], EngineAPI]


def frame(stream: int, payload: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def test_client_satisfies_engine_api(daemon: FakeDaemon, client_factory: ClientFactory) -> None:
    api: EngineAPI = client_factory(daemon)
    assert api.socket_path == daemon.socket_path


def test_events_stream(daemon: FakeDaemon, client_factory: ClientFactory, backend: str) -> None:
    payload = {"Type": "container", "Action": "start", "Actor": {"ID": "abc"}, "time": 1}
    daemon.add_stream("GET", "/events", [json.dumps(payload).encode() + b"\n"])
    with client_factory(daemon).events() as stream:
        events = list(stream)
    assert [(e.type, e.action, e.actor_id) for e in events] == [("container", "start", "abc")]
    assert_query(
        daemon, backend, {"filters": '{"type": ["container", "image", "volume", "network"]}'}
    )


def test_stream_closed_after_natural_end(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_stream("GET", "/events", [b'{"Type": "container", "Action": "start", "time": 1}\n'])
    stream = client_factory(daemon).events()
    assert len(list(stream)) == 1
    assert stream.closed is True


def test_logs_multiplexed(daemon: FakeDaemon, client_factory: ClientFactory, backend: str) -> None:
    daemon.add_stream(
        "GET",
        "/containers/abc/logs",
        [
            frame(1, b"2026-10-02T20:14:03.118000000Z hello\n"),
            frame(2, b"2026-10-02T20:14:04.000000000Z bad\n"),
        ],
        content_type="application/vnd.docker.multiplexed-stream",
    )
    with client_factory(daemon).logs("abc", tty=False, tail=50) as stream:
        lines = list(stream)
    assert [(line.stream, line.text) for line in lines] == [("stdout", "hello"), ("stderr", "bad")]
    assert lines[0].timestamp is not None
    # docker-py sends booleans as 1/0 and tail as a string; assert_query normalizes both
    assert_query(
        daemon,
        backend,
        {"follow": "true", "stdout": "true", "stderr": "true", "timestamps": "true", "tail": "50"},
    )


def test_logs_tty_and_tail_all(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_stream("GET", "/containers/abc/logs", [b"raw line\n"], content_type="text/plain")
    with client_factory(daemon).logs("abc", tty=True, tail=None, timestamps=False) as stream:
        assert [line.text for line in stream] == ["raw line"]
    assert_query(
        daemon,
        backend,
        {
            "follow": "true",
            "stdout": "true",
            "stderr": "true",
            "timestamps": "false",
            "tail": "all",
        },
    )


def test_stats_stream(daemon: FakeDaemon, client_factory: ClientFactory, backend: str) -> None:
    daemon.add_stream("GET", "/containers/abc/stats", [json.dumps(SAMPLE).encode() + b"\n"])
    with client_factory(daemon).stats("abc") as stream:
        samples = list(stream)
    assert samples[0].pids == 7
    assert_query(daemon, backend, {"stream": "true"})


def test_pull_progress_and_error(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    lines = [
        b'{"status": "Pulling from library/nginx", "id": "alpine"}\n',
        b'{"status": "Downloading", "id": "aa", "progressDetail": {"current": 1, "total": 2}}\n',
        b'{"error": "manifest unknown", "errorDetail": {"message": "manifest unknown"}}\n',
    ]
    daemon.add_stream("POST", "/images/create", lines)
    stream = client_factory(daemon).pull_image("nginx", "alpine")
    first = next(stream)
    assert first.status == "Pulling from library/nginx"
    second = next(stream)
    assert (second.layer_id, second.current, second.total) == ("aa", 1, 2)
    with pytest.raises(ServerError, match="manifest unknown"):
        next(stream)
    assert stream.closed is True
    stream.close()
    assert_query(daemon, backend, {"fromImage": "nginx", "tag": "alpine"})


def test_close_from_other_thread_ends_iteration(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    hold = threading.Event()
    daemon.add_stream(
        "GET", "/events", [b'{"Type": "container", "Action": "start", "time": 1}\n'], hold=hold
    )
    stream = client_factory(daemon).events()
    seen: list[str] = []
    done = threading.Event()

    def reader() -> None:
        for event in stream:
            seen.append(event.action)
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    for _ in range(100):
        if seen:
            break
        threading.Event().wait(0.02)
    stream.close()
    assert done.wait(timeout=2)
    assert seen == ["start"]
    assert stream.closed is True
    hold.set()


EVENT_LINE = b'{"Type": "container", "Action": "start", "time": 1}\n'


def test_close_after_first_item_discards_rest_of_chunk(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_stream("GET", "/events", [EVENT_LINE * 5])
    stream = client_factory(daemon).events()
    assert next(stream).action == "start"
    stream.close()
    assert list(stream) == []


def test_close_before_first_next_ends_iteration(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_stream("GET", "/events", [EVENT_LINE * 3])
    stream = client_factory(daemon).events()
    stream.close()
    assert list(stream) == []


def test_double_close_is_harmless(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_stream("GET", "/events", [EVENT_LINE])
    stream = client_factory(daemon).events()
    stream.close()
    stream.close()
    assert stream.closed is True


class MemoryResource:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


def test_stream_over_in_memory_closable() -> None:
    resource = MemoryResource()
    stream = Stream(resource, iter([1, 2, 3]))
    assert list(stream) == [1, 2, 3]
    assert resource.closed is True


def test_stream_close_delegates_to_closable() -> None:
    resource = MemoryResource()
    with Stream(resource, iter([1, 2, 3])) as stream:
        assert next(stream) == 1
    assert stream.closed is True
    assert list(stream) == []
