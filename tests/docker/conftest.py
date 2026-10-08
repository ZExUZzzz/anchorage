from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from anchorage.docker.client import DockerClient, EngineAPI
from anchorage.docker.transport import Transport
from tests.docker.fake_daemon import FakeDaemon, wait_for_socket

BACKENDS = ("native", "dockerpy")


@pytest.fixture
def daemon(tmp_path: Path) -> Iterator[FakeDaemon]:
    fake = FakeDaemon(str(tmp_path / "docker.sock"))
    fake.start()
    wait_for_socket(fake.socket_path)
    yield fake
    fake.stop()


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    name = str(request.param)
    if name == "dockerpy":
        pytest.importorskip("docker")
    return name


def build_client(backend: str, socket_path: str) -> EngineAPI:
    if backend == "dockerpy":
        from anchorage.docker.dockerpy import DockerPyClient

        return DockerPyClient(socket_path)
    return DockerClient(Transport(socket_path))


@pytest.fixture
def client_factory(backend: str) -> Iterator[Callable[[FakeDaemon], EngineAPI]]:
    created: list[EngineAPI] = []

    def make(daemon: FakeDaemon) -> EngineAPI:
        client = build_client(backend, daemon.socket_path)
        created.append(client)
        return client

    yield make
    for client in created:
        close = getattr(client, "close", None)
        if close is not None:
            close()


_BOOLEANS = {"1": "true", "0": "false", "true": "true", "false": "false"}


def assert_query(daemon: FakeDaemon, backend: str, expected: dict[str, str]) -> None:
    """Assert on the last request's query string.

    The native client sends exactly ``expected``. docker-py encodes booleans as ``1``/``True`` and
    adds its own defaults (``size``, ``limit``, ``noprune``...), so there every expected key must be
    present with the same value once booleans are normalized.
    """
    actual = daemon.last().query
    if backend == "native":
        assert actual == expected
        return

    def norm(value: str) -> str:
        return _BOOLEANS.get(value.lower(), value)

    assert {k: norm(actual.get(k, "<missing>")) for k in expected} == {
        k: norm(v) for k, v in expected.items()
    }
