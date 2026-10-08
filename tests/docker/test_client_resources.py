from collections.abc import Callable

from anchorage.docker.client import EngineAPI
from tests.docker.conftest import assert_query
from tests.docker.fake_daemon import FakeDaemon
from tests.docker.test_models_resources import NETWORK, VOLUME

ClientFactory = Callable[[FakeDaemon], EngineAPI]


def test_volumes(daemon: FakeDaemon, client_factory: ClientFactory, backend: str) -> None:
    daemon.add_json("GET", "/volumes", {"Volumes": [VOLUME], "Warnings": None})
    daemon.add_raw("DELETE", "/volumes/pulse_dbdata", b"", 204)
    daemon.add_json("POST", "/volumes/prune", {"VolumesDeleted": ["old"], "SpaceReclaimed": 7})
    client = client_factory(daemon)
    assert [v.name for v in client.list_volumes()] == ["pulse_dbdata"]
    client.remove_volume("pulse_dbdata", force=True)
    assert_query(daemon, backend, {"force": "true"})
    assert client.prune_volumes().space_reclaimed == 7


def test_volumes_null_list(daemon: FakeDaemon, client_factory: ClientFactory) -> None:
    daemon.add_json("GET", "/volumes", {"Volumes": None, "Warnings": None})
    assert client_factory(daemon).list_volumes() == []


def test_networks(daemon: FakeDaemon, client_factory: ClientFactory) -> None:
    daemon.add_json("GET", "/networks", [NETWORK])
    daemon.add_raw("DELETE", "/networks/fb86d9d98f76", b"", 204)
    daemon.add_json("POST", "/networks/prune", {"NetworksDeleted": ["pulse_default"]})
    client = client_factory(daemon)
    assert [n.name for n in client.list_networks()] == ["pulse_default"]
    client.remove_network("fb86d9d98f76")
    assert daemon.last().path == "/networks/fb86d9d98f76"
    assert client.prune_networks().deleted == ("pulse_default",)


def test_events_filter_includes_volumes_and_networks(
    daemon: FakeDaemon, client_factory: ClientFactory, backend: str
) -> None:
    daemon.add_stream("GET", "/events", [])
    with client_factory(daemon).events() as stream:
        list(stream)
    expected = '{"type": ["container", "image", "volume", "network"]}'
    assert_query(daemon, backend, {"filters": expected})
