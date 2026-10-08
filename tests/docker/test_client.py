from collections.abc import Callable
from typing import Any

from anchorage.docker.client import DockerClient, EngineAPI
from anchorage.docker.transport import Response, Transport
from tests.docker.conftest import assert_query
from tests.docker.fake_daemon import FakeDaemon
from tests.docker.test_models_containers import INSPECT, LIST_ITEM
from tests.docker.test_models_images import LIST_ITEM as IMAGE_ITEM

ClientFactory = Callable[[FakeDaemon], EngineAPI]


def test_ping_and_version(daemon: FakeDaemon, client_factory: ClientFactory) -> None:
    daemon.add_raw("GET", "/_ping", b"OK")
    daemon.add_json("GET", "/version", {"Version": "29.8.2", "ApiVersion": "1.56"})
    client = client_factory(daemon)
    client.ping()
    assert client.version().version == "29.8.2"
    assert client.socket_path == daemon.socket_path


def test_list_and_inspect_containers(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_json("GET", "/containers/json", [LIST_ITEM])
    daemon.add_json("GET", f"/containers/{LIST_ITEM['Id']}/json", INSPECT)
    client = client_factory(daemon)
    containers = client.list_containers()
    assert [c.name for c in containers] == ["pulse-nginx-1"]
    assert_query(daemon, backend, {"all": "true"})
    details = client.inspect_container(str(LIST_ITEM["Id"]))
    assert details.tty is False


def test_container_lifecycle_calls(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_raw("POST", "/containers/abc/start", b"", 204)
    daemon.add_raw("POST", "/containers/abc/stop", b"", 204)
    daemon.add_raw("POST", "/containers/abc/restart", b"", 204)
    daemon.add_raw("DELETE", "/containers/abc", b"", 204)
    client = client_factory(daemon)
    client.start_container("abc")
    client.stop_container("abc", timeout=5)
    assert_query(daemon, backend, {"t": "5"})
    client.restart_container("abc")
    assert_query(daemon, backend, {"t": "10"})
    client.remove_container("abc", force=True, volumes=True)
    assert_query(daemon, backend, {"force": "true", "v": "true"})


def test_start_already_running_is_not_an_error(
    daemon: FakeDaemon, client_factory: ClientFactory
) -> None:
    daemon.add_raw("POST", "/containers/abc/start", b"", 304)
    client_factory(daemon).start_container("abc")


def test_images(daemon: FakeDaemon, client_factory: ClientFactory, backend: str) -> None:
    daemon.add_json("GET", "/images/json", [IMAGE_ITEM])
    daemon.add_json("GET", "/images/nginx:alpine/json", {"Id": "sha256:1", "Config": {}})
    daemon.add_json("GET", "/images/nginx:alpine/history", [{"Id": "<missing>", "Size": 1}])
    daemon.add_json("DELETE", "/images/nginx:alpine", [{"Untagged": "nginx:alpine"}])
    daemon.add_json(
        "POST", "/images/prune", {"ImagesDeleted": [{"Deleted": "sha256:x"}], "SpaceReclaimed": 9}
    )
    client = client_factory(daemon)
    assert client.list_images()[0].repo_tags == ("nginx:alpine", "nginx:1.27-alpine")
    assert client.inspect_image("nginx:alpine").id == "sha256:1"
    assert client.image_history("nginx:alpine")[0].size == 1
    client.remove_image("nginx:alpine", force=True)
    assert_query(daemon, backend, {"force": "true"})
    result = client.prune_images()
    assert result.space_reclaimed == 9
    assert_query(daemon, backend, {"filters": '{"dangling": ["true"]}'})
    client.prune_images(dangling_only=False)
    assert_query(daemon, backend, {"filters": '{"dangling": ["false"]}'})


class RecordingTransport(Transport):
    def __init__(self) -> None:
        super().__init__("/nonexistent")
        self.timeouts: list[float | None] = []

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        self.timeouts.append(kwargs.get("timeout"))
        return Response(status=200, body=b"{}")


def test_long_operations_extend_the_read_timeout() -> None:
    transport = RecordingTransport()
    client = DockerClient(transport)
    client.stop_container("abc", timeout=20)
    client.restart_container("abc", timeout=30)
    client.prune_images()
    assert transport.timeouts == [35, 45, 300.0]
