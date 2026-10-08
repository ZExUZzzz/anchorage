"""Smoke tests against the local daemon. Run with ``pytest -m integration``."""

import os
import threading
from collections.abc import Iterator

import pytest

from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.transport import discover_socket_path
from tests.docker.conftest import BACKENDS, build_client

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=BACKENDS)
def client(request: pytest.FixtureRequest) -> Iterator[EngineAPI]:
    if request.param == "dockerpy":
        pytest.importorskip("docker")
    path = discover_socket_path()
    if not os.path.exists(path):
        pytest.skip(f"no Docker socket at {path}")
    client = build_client(request.param, path)
    try:
        client.ping()
    except DockerError as exc:
        pytest.skip(f"daemon not reachable: {exc}")
    yield client
    close = getattr(client, "close", None)
    if close is not None:
        close()


def test_version(client: EngineAPI) -> None:
    version = client.version()
    assert version.api_version
    assert version.version


def test_list_containers_and_inspect(client: EngineAPI) -> None:
    containers = client.list_containers()
    for container in containers[:3]:
        details = client.inspect_container(container.id)
        assert details.id == container.id
        assert details.name == container.name


def test_list_images_and_history(client: EngineAPI) -> None:
    images = client.list_images()
    for image in images[:3]:
        assert client.image_history(image.id)


def test_events_stream_opens_and_closes(client: EngineAPI) -> None:
    stream = client.events()
    done = threading.Event()

    def reader() -> None:
        for _ in stream:
            pass
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    threading.Event().wait(0.2)
    stream.close()
    assert done.wait(timeout=2)


def test_logs_and_stats_for_a_running_container(client: EngineAPI) -> None:
    running = [c for c in client.list_containers() if c.state == "running"]
    if not running:
        pytest.skip("no running container")
    details = client.inspect_container(running[0].id)
    logs = client.logs(details.id, tty=details.tty, tail=5)
    collected: list[object] = []
    enough = threading.Event()
    finished = threading.Event()

    def reader() -> None:
        for line in logs:
            collected.append(line)
            if len(collected) >= 5:
                enough.set()
                break
        finished.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    enough.wait(timeout=3)
    logs.close()
    assert finished.wait(timeout=2), "log reader did not stop after close()"
    thread.join(timeout=2)
    with client.stats(details.id) as stats:
        sample = next(stats)
    assert sample.memory_limit >= 0


def test_list_volumes(client: EngineAPI) -> None:
    for volume in client.list_volumes():
        assert volume.name


def test_list_networks(client: EngineAPI) -> None:
    networks = client.list_networks()
    assert networks
    assert all(n.name and n.id for n in networks)
