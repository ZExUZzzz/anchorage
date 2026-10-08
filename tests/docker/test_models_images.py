from datetime import datetime, timezone

from anchorage.docker.models import Image, ImageDetails, ImageLayer, split_reference

LIST_ITEM = {
    "Id": "sha256:7a2c1f1111111111111111111111111111111111111111111111111111111111",
    "RepoTags": ["nginx:alpine", "nginx:1.27-alpine"],
    "RepoDigests": ["nginx@sha256:abc"],
    "Created": 1759425242,
    "Size": 48300000,
    "Labels": None,
    "Containers": -1,
}


def test_image_from_list_item() -> None:
    img = Image.from_api(LIST_ITEM)
    assert img.short_id == "7a2c1f111111"
    assert img.repo_tags == ("nginx:alpine", "nginx:1.27-alpine")
    assert img.repo_digests == ("nginx@sha256:abc",)
    assert img.created == datetime(2025, 10, 2, 17, 14, 2, tzinfo=timezone.utc)
    assert img.size == 48300000
    assert img.labels == {}


def test_image_without_tags_is_dangling() -> None:
    img = Image.from_api(dict(LIST_ITEM, RepoTags=None, RepoDigests=None))
    assert img.repo_tags == ()
    assert img.dangling is True
    assert Image.from_api(dict(LIST_ITEM, RepoTags=["<none>:<none>"])).dangling is True
    assert Image.from_api(LIST_ITEM).dangling is False


def test_split_reference() -> None:
    assert split_reference("nginx:alpine") == ("nginx", "alpine")
    assert split_reference("nginx") == ("nginx", "latest")
    assert split_reference("ghcr.io/acme/api:1.4.2") == ("ghcr.io/acme/api", "1.4.2")
    assert split_reference("localhost:5000/app") == ("localhost:5000/app", "latest")
    assert split_reference("localhost:5000/app:dev") == ("localhost:5000/app", "dev")
    assert split_reference("<none>:<none>") == ("<none>", "<none>")


def test_image_details() -> None:
    data = {
        "Id": "sha256:7a2c1f1111111111111111111111111111111111111111111111111111111111",
        "RepoTags": ["nginx:alpine"],
        "Created": "2026-09-18T10:00:00.5Z",
        "Size": 48300000,
        "Architecture": "amd64",
        "Os": "linux",
        "Author": "",
        "Config": {
            "Env": ["PATH=/usr/bin"],
            "Cmd": ["nginx", "-g", "daemon off;"],
            "Entrypoint": ["/docker-entrypoint.sh"],
            "ExposedPorts": {"80/tcp": {}},
            "WorkingDir": "",
            "Labels": {"maintainer": "x"},
        },
    }
    d = ImageDetails.from_api(data)
    assert d.repo_tags == ("nginx:alpine",)
    assert d.created == datetime(2026, 9, 18, 10, 0, 0, 500000, tzinfo=timezone.utc)
    assert d.architecture == "amd64"
    assert d.os == "linux"
    assert d.env == ("PATH=/usr/bin",)
    assert d.cmd == ("nginx", "-g", "daemon off;")
    assert d.entrypoint == ("/docker-entrypoint.sh",)
    assert d.exposed_ports == ("80/tcp",)
    assert d.labels == {"maintainer": "x"}


def test_image_layer_from_history() -> None:
    layer = ImageLayer.from_api(
        {
            "Id": "<missing>",
            "Created": 1759425242,
            "CreatedBy": "/bin/sh -c #(nop) EXPOSE 80",
            "Size": 0,
            "Comment": "",
            "Tags": None,
        }
    )
    assert layer.id == "<missing>"
    assert layer.created_by == "/bin/sh -c #(nop) EXPOSE 80"
    assert layer.size == 0
    assert layer.tags == ()
