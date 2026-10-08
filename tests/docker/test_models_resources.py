from datetime import UTC, datetime

from anchorage.docker.models import Network, PruneResult, Volume

VOLUME = {
    "CreatedAt": "2026-10-02T12:56:26+05:00",
    "Driver": "local",
    "Labels": {"com.docker.compose.project": "pulse", "com.docker.compose.volume": "dbdata"},
    "Mountpoint": "/var/lib/docker/volumes/pulse_dbdata/_data",
    "Name": "pulse_dbdata",
    "Options": None,
    "Scope": "local",
}

NETWORK = {
    "Name": "pulse_default",
    "Id": "fb86d9d98f76bc677b90dd218ca7e1fbcaf5a52703cb194c29f2258415fdadc4",
    "Created": "2026-10-02T20:40:57.986891268+05:00",
    "Scope": "local",
    "Driver": "bridge",
    "EnableIPv6": False,
    "IPAM": {
        "Driver": "default",
        "Options": None,
        "Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}],
    },
    "Internal": False,
    "Attachable": False,
    "Ingress": False,
    "Containers": {},
    "Options": {},
    "Labels": {"com.docker.compose.network": "default", "com.docker.compose.project": "pulse"},
}


def test_volume_from_api() -> None:
    v = Volume.from_api(VOLUME)
    assert v.name == "pulse_dbdata"
    assert v.driver == "local"
    assert v.mountpoint.endswith("pulse_dbdata/_data")
    expected = datetime(2026, 10, 2, 7, 56, 26, tzinfo=UTC)
    assert v.created is not None and v.created.astimezone(UTC) == expected
    assert v.scope == "local"
    assert v.compose_project == "pulse"
    assert v.options == {}


def test_volume_tolerates_missing_fields() -> None:
    v = Volume.from_api({"Name": "x", "Driver": "local", "Mountpoint": "/m"})
    assert v.created is None and v.labels == {} and v.compose_project is None


def test_network_from_api() -> None:
    n = Network.from_api(NETWORK)
    assert n.short_id == "fb86d9d98f76"
    assert (n.name, n.driver, n.scope) == ("pulse_default", "bridge", "local")
    assert n.created is not None
    assert [(s.subnet, s.gateway) for s in n.subnets] == [("172.18.0.0/16", "172.18.0.1")]
    assert (n.internal, n.attachable, n.ingress, n.ipv6) == (False, False, False, False)
    assert n.compose_project == "pulse"


def test_network_without_ipam() -> None:
    data = {
        "Name": "host",
        "Id": "abc",
        "Driver": "host",
        "Scope": "local",
        "IPAM": {"Config": None},
    }
    n = Network.from_api(data)
    assert n.subnets == ()
    assert n.labels == {} and n.options == {}


def test_prune_result_for_volumes_and_networks() -> None:
    volumes = PruneResult.from_api({"VolumesDeleted": ["a", "b"], "SpaceReclaimed": 10})
    assert volumes.deleted == ("a", "b")
    assert PruneResult.from_api({"NetworksDeleted": ["n1"]}).deleted == ("n1",)
    assert PruneResult.from_api({"VolumesDeleted": None, "SpaceReclaimed": 0}).deleted == ()
