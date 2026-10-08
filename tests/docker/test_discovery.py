import pytest

from anchorage.docker.errors import EngineUnavailable
from anchorage.docker.transport import DEFAULT_SOCKET_PATH, discover_socket_path


def test_docker_host_unix_wins() -> None:
    env = {"DOCKER_HOST": "unix:///tmp/custom.sock", "XDG_RUNTIME_DIR": "/run/user/1000"}
    assert discover_socket_path(env, exists=lambda _: True) == "/tmp/custom.sock"


def test_rootless_socket_when_present() -> None:
    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert discover_socket_path(env, exists=lambda p: p == "/run/user/1000/docker.sock") == (
        "/run/user/1000/docker.sock"
    )


def test_default_when_rootless_missing() -> None:
    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert discover_socket_path(env, exists=lambda _: False) == DEFAULT_SOCKET_PATH


def test_default_without_environment() -> None:
    assert discover_socket_path({}, exists=lambda _: False) == DEFAULT_SOCKET_PATH


def test_tcp_docker_host_is_rejected() -> None:
    with pytest.raises(EngineUnavailable, match="unix"):
        discover_socket_path({"DOCKER_HOST": "tcp://10.0.0.1:2375"}, exists=lambda _: False)
