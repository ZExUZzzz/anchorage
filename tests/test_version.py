import sys
import tomllib
from pathlib import Path

import pytest

import anchorage
from anchorage.core.settings import AppSettings


def tmp_settings(tmp_path: Path) -> AppSettings:
    from PySide6.QtCore import QSettings

    return AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert anchorage.__version__ == data["project"]["version"]


def test_parse_args() -> None:
    from anchorage.app import parse_args

    args = parse_args(["anchorage", "--socket", "/tmp/x.sock", "--verbose"])
    assert args.socket == "/tmp/x.sock"
    assert args.verbose is True


def test_create_api_reports_unusable_docker_host(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from anchorage.app import create_api
    from anchorage.docker.transport import DEFAULT_SOCKET_PATH

    monkeypatch.setenv("DOCKER_HOST", "tcp://x")
    api, warning = create_api(None)
    assert warning
    assert api.socket_path == DEFAULT_SOCKET_PATH  # type: ignore[attr-defined]


def test_create_api_explicit_socket_has_no_warning() -> None:
    from anchorage.app import create_api

    api, warning = create_api("/tmp/x.sock")
    assert warning is None
    assert api.socket_path == "/tmp/x.sock"  # type: ignore[attr-defined]


def test_app_id_is_shared() -> None:
    from anchorage import APP_ID
    from anchorage.app import APP_ID as APP_ID_FROM_APP

    assert APP_ID == APP_ID_FROM_APP == "io.github.zexuzzzz.Anchorage"


def test_parse_args_leaves_unset_options_as_none() -> None:
    from anchorage.app import parse_args

    args = parse_args(["anchorage"])
    assert (args.socket, args.backend, args.log_colors) == (None, None, None)
    args = parse_args(["anchorage", "--backend", "native", "--log-colors", "level"])
    assert (args.backend, args.log_colors) == ("native", "level")


def test_invalid_backend_env_is_rejected(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from anchorage.app import resolve_or_exit

    monkeypatch.setenv("ANCHORAGE_BACKEND", "bogus")
    with pytest.raises(SystemExit):
        resolve_or_exit(["anchorage"], tmp_settings(tmp_path))


def test_create_api_dockerpy_backend() -> None:
    pytest.importorskip("docker")
    from anchorage.app import create_api
    from anchorage.docker.dockerpy import DockerPyClient

    api, warning = create_api("/tmp/x.sock", "dockerpy")
    assert isinstance(api, DockerPyClient)
    assert warning is None


def test_create_api_dockerpy_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import builtins

    from anchorage.app import BackendUnavailable, create_api

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "docker" or name.startswith("docker."):
            raise ImportError("no docker")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "anchorage.docker.dockerpy", raising=False)
    with pytest.raises(BackendUnavailable):
        create_api("/tmp/x.sock", "dockerpy")


def test_invalid_log_colors_env_is_rejected(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from anchorage.app import resolve_or_exit

    monkeypatch.setenv("ANCHORAGE_LOG_COLORS", "rainbow")
    with pytest.raises(SystemExit):
        resolve_or_exit(["anchorage"], tmp_settings(tmp_path))


def test_resolve_or_exit_applies_flag_env_saved_precedence(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from anchorage.app import resolve_or_exit

    for name in ("ANCHORAGE_BACKEND", "ANCHORAGE_LOG_COLORS", "DOCKER_HOST"):
        monkeypatch.delenv(name, raising=False)
    settings = tmp_settings(tmp_path)
    settings.log_colors = "level"
    _, resolved = resolve_or_exit(["anchorage"], settings)
    assert resolved.log_colors == "level"
    monkeypatch.setenv("ANCHORAGE_LOG_COLORS", "stream")
    _, resolved = resolve_or_exit(["anchorage"], settings)
    assert resolved.log_colors == "stream"
    _, resolved = resolve_or_exit(["anchorage", "--log-colors", "level"], settings)
    assert resolved.log_colors == "level"


def _hide_docker_py(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "docker" or name.startswith("docker."):
            raise ImportError("no docker")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "anchorage.docker.dockerpy", raising=False)


def test_saved_dockerpy_without_the_package_falls_back_to_native(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from anchorage.app import create_api_or_fall_back
    from anchorage.core.settings import Resolved
    from anchorage.docker.client import DockerClient

    _hide_docker_py(monkeypatch)
    settings = tmp_settings(tmp_path)
    settings.backend = "dockerpy"
    resolved = Resolved("stream", "dockerpy", "/x.sock", "")
    api, new, warning = create_api_or_fall_back(resolved, settings)
    assert isinstance(api, DockerClient)
    assert new.backend == "native"
    assert settings.backend == "native"
    assert warning == "docker-py is not installed; using the native backend"


def test_flag_chosen_dockerpy_without_the_package_names_the_flag(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from anchorage.app import BackendUnavailable, create_api_or_fall_back
    from anchorage.core.settings import Resolved

    _hide_docker_py(monkeypatch)
    settings = tmp_settings(tmp_path)
    for reason in ("--backend", "ANCHORAGE_BACKEND"):
        resolved = Resolved("stream", "dockerpy", "", "", {"backend": reason})
        with pytest.raises(BackendUnavailable) as info:
            create_api_or_fall_back(resolved, settings)
        assert f"{reason} dockerpy" in str(info.value) or f"{reason}=dockerpy" in str(info.value)
    assert settings.backend == "native"


def test_language_flag_accepts_codes_and_auto_only() -> None:
    from anchorage.app import parse_args

    assert parse_args(["anchorage", "--language", "zh_CN"]).language == "zh_CN"
    assert parse_args(["anchorage", "--language", "auto"]).language == "auto"
    assert parse_args(["anchorage"]).language is None
    with pytest.raises(SystemExit):
        parse_args(["anchorage", "--language", "klingon"])
