import argparse
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from anchorage.core.settings import AppSettings, InvalidEnvironment, resolve


@pytest.fixture
def store(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def settings(store: QSettings) -> AppSettings:
    return AppSettings(store)


def args(**given: str | None) -> argparse.Namespace:
    values: dict[str, str | None] = {"socket": None, "backend": None, "log_colors": None}
    values.update(given)
    return argparse.Namespace(**values)


def test_defaults(settings: AppSettings) -> None:
    assert settings.log_colors == "stream"
    assert settings.backend == "native"
    assert settings.socket == ""
    assert settings.terminal == ""


def test_setters_write_under_settings_group(store: QSettings, settings: AppSettings) -> None:
    settings.log_colors = "level"
    settings.backend = "dockerpy"
    settings.socket = "/run/x.sock"
    settings.terminal = "kitty --single-instance"
    assert store.value("settings/log_colors") == "level"
    assert store.value("settings/backend") == "dockerpy"
    assert store.value("settings/socket") == "/run/x.sock"
    assert store.value("settings/terminal") == "kitty --single-instance"
    assert AppSettings(store).backend == "dockerpy"


def test_invalid_saved_values_fall_back_to_defaults(
    store: QSettings, settings: AppSettings
) -> None:
    store.setValue("settings/log_colors", "rainbow")
    store.setValue("settings/backend", "bogus")
    store.setValue("settings/socket", ["a", "b"])
    store.setValue("settings/terminal", 42)
    assert settings.log_colors == "stream"
    assert settings.backend == "native"
    assert settings.terminal == ""
    assert settings.socket == "a,b"  # INI turns a comma into a list; the path is rejoined


def test_setters_reject_invalid_modes(settings: AppSettings) -> None:
    with pytest.raises(ValueError):
        settings.backend = "bogus"
    with pytest.raises(ValueError):
        settings.log_colors = "rainbow"


@pytest.mark.parametrize(
    ("key", "flag", "env_name", "env_value", "saved", "values"),
    [
        (
            "log_colors",
            "log_colors",
            "ANCHORAGE_LOG_COLORS",
            "level",
            "stream",
            ("stream", "level"),
        ),
        ("backend", "backend", "ANCHORAGE_BACKEND", "dockerpy", "native", ("native", "dockerpy")),
    ],
)
def test_precedence_for_enumerated_values(
    settings: AppSettings,
    key: str,
    flag: str,
    env_name: str,
    env_value: str,
    saved: str,
    values: tuple[str, str],
) -> None:
    default, other = values
    # default
    resolved = resolve(args(), {}, settings)
    assert getattr(resolved, key) == default
    assert key not in resolved.locked
    # saved
    setattr(settings, key, other)
    resolved = resolve(args(), {}, settings)
    assert getattr(resolved, key) == other
    assert key not in resolved.locked
    # env beats saved
    setattr(settings, key, default)
    resolved = resolve(args(), {env_name: env_value}, settings)
    assert getattr(resolved, key) == env_value
    assert resolved.locked[key] == env_name
    # flag beats env and saved
    resolved = resolve(args(**{flag: default}), {env_name: env_value}, settings)
    assert getattr(resolved, key) == default
    assert resolved.locked[key] == "--" + key.replace("_", "-")


def test_precedence_for_socket(settings: AppSettings) -> None:
    resolved = resolve(args(), {}, settings)
    assert resolved.socket == ""
    assert "socket" not in resolved.locked
    settings.socket = "/saved.sock"
    assert resolve(args(), {}, settings).socket == "/saved.sock"
    env = {"DOCKER_HOST": "unix:///env.sock"}
    resolved = resolve(args(), env, settings)
    assert resolved.socket == ""  # left to the engine client, which reads DOCKER_HOST itself
    assert resolved.locked["socket"] == "DOCKER_HOST"
    resolved = resolve(args(socket="/flag.sock"), env, settings)
    assert resolved.socket == "/flag.sock"
    assert resolved.locked["socket"] == "--socket"


def test_empty_environment_values_are_ignored(settings: AppSettings) -> None:
    env = {"DOCKER_HOST": "", "ANCHORAGE_BACKEND": "", "ANCHORAGE_LOG_COLORS": ""}
    assert resolve(args(), env, settings).locked == {}


def test_terminal_is_never_locked(settings: AppSettings) -> None:
    settings.terminal = "foot"
    resolved = resolve(args(), {"TERMINAL": "kitty"}, settings)
    assert resolved.terminal == "foot"
    assert "terminal" not in resolved.locked


def test_invalid_environment_values_are_errors(settings: AppSettings) -> None:
    with pytest.raises(InvalidEnvironment, match="ANCHORAGE_BACKEND"):
        resolve(args(), {"ANCHORAGE_BACKEND": "bogus"}, settings)
    with pytest.raises(InvalidEnvironment, match="ANCHORAGE_LOG_COLORS"):
        resolve(args(), {"ANCHORAGE_LOG_COLORS": "rainbow"}, settings)


def test_flag_overrides_an_invalid_environment_value(settings: AppSettings) -> None:
    resolved = resolve(args(backend="native"), {"ANCHORAGE_BACKEND": "bogus"}, settings)
    assert resolved.backend == "native"
