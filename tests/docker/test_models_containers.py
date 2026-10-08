from datetime import datetime, timezone

from anchorage.docker.models import Container, ContainerDetails, PortBinding

LIST_ITEM = {
    "Id": "3f1c9a7e2b44aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22aa33",
    "Names": ["/pulse-nginx-1"],
    "Image": "nginx:alpine",
    "ImageID": "sha256:7a2c1f000000",
    "Command": "/docker-entrypoint.sh nginx -g 'daemon off;'",
    "Created": 1759425242,
    "State": "running",
    "Status": "Up 3 hours (healthy)",
    "Ports": [
        {"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
        {"IP": "::", "PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
        {"PrivatePort": 443, "Type": "tcp"},
    ],
    "Labels": {
        "com.docker.compose.project": "pulse",
        "com.docker.compose.service": "nginx",
    },
}

INSPECT = {
    "Id": "3f1c9a7e2b44aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22aa33",
    "Name": "/pulse-nginx-1",
    "Created": "2026-10-02T17:14:02.123456789Z",
    "Path": "/docker-entrypoint.sh",
    "Args": ["nginx", "-g", "daemon off;"],
    "Image": "sha256:7a2c1f000000",
    "State": {
        "Status": "running",
        "Running": True,
        "Paused": False,
        "Restarting": False,
        "ExitCode": 0,
        "StartedAt": "2026-10-02T17:14:03.000000001Z",
        "FinishedAt": "0001-01-01T00:00:00Z",
        "Health": {"Status": "healthy"},
    },
    "Config": {
        "Image": "nginx:alpine",
        "Env": ["NGINX_VERSION=1.27.2", "PATH=/usr/bin"],
        "Tty": False,
        "Labels": {"com.docker.compose.project": "pulse"},
    },
    "HostConfig": {"RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0}},
    "Mounts": [
        {
            "Type": "bind",
            "Source": "/home/me/pulse/nginx",
            "Destination": "/etc/nginx/conf.d",
            "Mode": "ro",
            "RW": False,
        },
        {
            "Type": "volume",
            "Name": "pulse_logs",
            "Source": "/var/lib/docker/volumes/pulse_logs/_data",
            "Destination": "/var/log/nginx",
            "Mode": "z",
            "RW": True,
        },
    ],
    "NetworkSettings": {
        "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}], "443/tcp": None},
        "Networks": {
            "pulse_default": {
                "IPAddress": "172.18.0.5",
                "Gateway": "172.18.0.1",
                "IPPrefixLen": 16,
                "MacAddress": "02:42:ac:12:00:05",
            }
        },
    },
}


def test_container_from_list_item() -> None:
    c = Container.from_api(LIST_ITEM)
    assert c.name == "pulse-nginx-1"
    assert c.short_id == "3f1c9a7e2b44"
    assert c.image == "nginx:alpine"
    assert c.state == "running"
    assert c.status == "Up 3 hours (healthy)"
    assert c.created == datetime(2025, 10, 2, 17, 14, 2, tzinfo=timezone.utc)
    assert c.compose_project == "pulse"
    assert c.compose_service == "nginx"


def test_container_ports_are_deduplicated_and_sorted() -> None:
    c = Container.from_api(LIST_ITEM)
    assert c.ports == (
        PortBinding(private_port=80, protocol="tcp", public_port=8080, host_ip="0.0.0.0"),
        PortBinding(private_port=443, protocol="tcp", public_port=None, host_ip=None),
    )


def test_container_without_names_uses_short_id() -> None:
    data = dict(LIST_ITEM, Names=[])
    assert Container.from_api(data).name == "3f1c9a7e2b44"
    data.pop("Names")
    assert Container.from_api(data).name == "3f1c9a7e2b44"


def test_container_null_labels_and_ports() -> None:
    c = Container.from_api(dict(LIST_ITEM, Labels=None, Ports=None))
    assert c.labels == {}
    assert c.ports == ()
    assert c.compose_project is None


def test_container_details_from_inspect() -> None:
    d = ContainerDetails.from_api(INSPECT)
    assert d.name == "pulse-nginx-1"
    assert d.image == "nginx:alpine"
    assert d.image_id == "sha256:7a2c1f000000"
    assert d.command == ("/docker-entrypoint.sh", "nginx", "-g", "daemon off;")
    assert d.created == datetime(2026, 10, 2, 17, 14, 2, 123456, tzinfo=timezone.utc)
    assert d.state.status == "running"
    assert d.state.running is True
    assert d.state.health == "healthy"
    assert d.state.started_at is not None
    assert d.state.finished_at is None
    assert d.restart_policy == "unless-stopped"
    assert d.tty is False
    assert d.env == ("NGINX_VERSION=1.27.2", "PATH=/usr/bin")
    assert d.labels == {"com.docker.compose.project": "pulse"}
    assert [m.destination for m in d.mounts] == ["/etc/nginx/conf.d", "/var/log/nginx"]
    assert d.mounts[1].name == "pulse_logs"
    assert d.mounts[0].read_write is False
    assert d.networks[0].name == "pulse_default"
    assert d.networks[0].ip_address == "172.18.0.5"
    assert d.networks[0].prefix_len == 16
    assert d.ports == (
        PortBinding(private_port=80, protocol="tcp", public_port=8080, host_ip="0.0.0.0"),
        PortBinding(private_port=443, protocol="tcp", public_port=None, host_ip=None),
    )


def test_container_details_tolerates_missing_sections() -> None:
    data = {
        "Id": "abc123def456aaaa",
        "Name": "/bare",
        "State": {"Status": "exited", "ExitCode": 1},
        "Config": {"Image": "busybox"},
    }
    d = ContainerDetails.from_api(data)
    assert d.state.exit_code == 1
    assert d.state.health is None
    assert d.command == ()
    assert d.env == ()
    assert d.mounts == ()
    assert d.networks == ()
    assert d.ports == ()
    assert d.restart_policy == "no"


def test_container_mounts_and_networks_from_list_item() -> None:
    data = dict(
        LIST_ITEM,
        Mounts=[
            {
                "Type": "volume",
                "Name": "pulse_dbdata",
                "Source": "/var/lib/docker/volumes/pulse_dbdata/_data",
                "Destination": "/var/lib/mysql",
                "Mode": "z",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/home/me/conf",
                "Destination": "/etc/nginx/conf.d",
                "Mode": "ro",
                "RW": False,
            },
        ],
        NetworkSettings={
            "Networks": {
                "pulse_default": {"IPAddress": "172.18.0.5", "Gateway": "172.18.0.1"},
                "other": None,
            }
        },
    )
    c = Container.from_api(data)
    assert [(m.type, m.name, m.destination) for m in c.mounts] == [
        ("volume", "pulse_dbdata", "/var/lib/mysql"),
        ("bind", None, "/etc/nginx/conf.d"),
    ]
    assert c.networks == {"pulse_default": "172.18.0.5", "other": ""}
    assert Container.from_api(LIST_ITEM).mounts == ()
    assert Container.from_api(LIST_ITEM).networks == {}
