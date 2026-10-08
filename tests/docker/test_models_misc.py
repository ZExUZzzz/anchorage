from datetime import datetime, timezone

from anchorage.docker.models import Event, PruneResult, VersionInfo


def test_version_info() -> None:
    v = VersionInfo.from_api(
        {
            "Version": "29.8.2",
            "ApiVersion": "1.56",
            "MinAPIVersion": "1.40",
            "Os": "linux",
            "Arch": "amd64",
            "KernelVersion": "7.2.8",
        }
    )
    assert v.version == "29.8.2"
    assert v.api_version == "1.56"
    assert v.min_api_version == "1.40"
    assert v.os == "linux"
    assert v.arch == "amd64"
    assert v.kernel_version == "7.2.8"


def test_prune_result() -> None:
    r = PruneResult.from_api(
        {
            "ImagesDeleted": [{"Untagged": "old:1"}, {"Deleted": "sha256:abc"}],
            "SpaceReclaimed": 1234,
        }
    )
    assert r.deleted == ("sha256:abc",)
    assert r.untagged == ("old:1",)
    assert r.space_reclaimed == 1234
    assert PruneResult.from_api({"ImagesDeleted": None, "SpaceReclaimed": 0}).deleted == ()


def test_event() -> None:
    e = Event.from_api(
        {
            "Type": "container",
            "Action": "start",
            "Actor": {
                "ID": "3f1c9a7e2b44",
                "Attributes": {"name": "pulse-nginx-1", "image": "nginx"},
            },
            "time": 1759425242,
            "timeNano": 1759425242123456789,
        }
    )
    assert e.type == "container"
    assert e.action == "start"
    assert e.actor_id == "3f1c9a7e2b44"
    assert e.name == "pulse-nginx-1"
    assert e.attributes["image"] == "nginx"
    assert e.time == datetime(2025, 10, 2, 17, 14, 2, 123456, tzinfo=timezone.utc)


def test_event_without_actor() -> None:
    e = Event.from_api({"Type": "daemon", "Action": "reload", "time": 1})
    assert e.actor_id == ""
    assert e.name is None
    assert e.attributes == {}


def test_prune_result_understands_all_deleted_keys() -> None:
    r = PruneResult.from_api({"ContainersDeleted": ["c1"], "VolumesDeleted": ["v1"]})
    assert r.deleted == ("v1", "c1")
    assert r.untagged == ()
