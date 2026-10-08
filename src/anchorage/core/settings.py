"""Persistent user settings and their precedence against flags and the environment."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

LOG_COLOR_MODES = ("stream", "level")
BACKENDS = ("native", "dockerpy")

DEFAULT_LOG_COLORS = "stream"
DEFAULT_BACKEND = "native"

ENV_LOG_COLORS = "ANCHORAGE_LOG_COLORS"
ENV_BACKEND = "ANCHORAGE_BACKEND"
ENV_SOCKET = "DOCKER_HOST"

GROUP = "settings"


class InvalidEnvironment(ValueError):
    """An environment variable that selects a setting holds an unusable value."""


class AppSettings:
    """Typed view of the ``settings/`` group; unreadable saved values read as the default."""

    def __init__(self, store: QSettings) -> None:
        self._store = store

    def _text(self, key: str) -> str | None:
        value = self._store.value(f"{GROUP}/{key}")
        if isinstance(value, str):
            return value
        if isinstance(value, list) and all(isinstance(part, str) for part in value):
            return ",".join(value)  # INI storage splits a value containing commas
        return None

    def _choice(self, key: str, choices: tuple[str, ...], default: str) -> str:
        value = self._text(key)
        return value if value in choices else default

    def _write(self, key: str, value: str) -> None:
        self._store.setValue(f"{GROUP}/{key}", value)

    @property
    def log_colors(self) -> str:
        return self._choice("log_colors", LOG_COLOR_MODES, DEFAULT_LOG_COLORS)

    @log_colors.setter
    def log_colors(self, value: str) -> None:
        if value not in LOG_COLOR_MODES:
            raise ValueError(f"unknown log colour mode {value!r}")
        self._write("log_colors", value)

    @property
    def backend(self) -> str:
        return self._choice("backend", BACKENDS, DEFAULT_BACKEND)

    @backend.setter
    def backend(self, value: str) -> None:
        if value not in BACKENDS:
            raise ValueError(f"unknown backend {value!r}")
        self._write("backend", value)

    @property
    def socket(self) -> str:
        return self._text("socket") or ""

    @socket.setter
    def socket(self, value: str) -> None:
        self._write("socket", value.strip())

    @property
    def terminal(self) -> str:
        return (self._text("terminal") or "").strip()

    @terminal.setter
    def terminal(self, value: str) -> None:
        self._write("terminal", value.strip())


@dataclass(frozen=True, slots=True)
class Resolved:
    """Effective values after flag > environment > saved > default.

    ``socket`` is the path to hand to the client; empty means automatic discovery, which
    also covers ``DOCKER_HOST`` (the client reads it itself). ``locked`` maps a key fixed by
    a flag or variable to the reason, for example ``"--socket"``; the dialog must not save it.
    """

    log_colors: str = DEFAULT_LOG_COLORS
    backend: str = DEFAULT_BACKEND
    socket: str = ""
    terminal: str = ""
    locked: dict[str, str] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> Resolved:
        return cls()


def _from_env(environ: Mapping[str, str], name: str, choices: tuple[str, ...]) -> str | None:
    value = environ.get(name)
    if not value:
        return None
    if value not in choices:
        raise InvalidEnvironment(
            f"invalid {name} value {value!r} (choose from {', '.join(choices)})"
        )
    return value


def resolve(
    args: argparse.Namespace, environ: Mapping[str, str], settings: AppSettings
) -> Resolved:
    locked: dict[str, str] = {}

    def pick(
        key: str, flag: str | None, env_name: str, choices: tuple[str, ...], saved: str
    ) -> str:
        if flag is not None:
            locked[key] = "--" + key.replace("_", "-")
            return flag
        from_env = _from_env(environ, env_name, choices)
        if from_env is not None:
            locked[key] = env_name
            return from_env
        return saved

    log_colors = pick(
        "log_colors", args.log_colors, ENV_LOG_COLORS, LOG_COLOR_MODES, settings.log_colors
    )
    backend = pick("backend", args.backend, ENV_BACKEND, BACKENDS, settings.backend)

    socket = settings.socket
    if args.socket is not None:
        socket = args.socket
        locked["socket"] = "--socket"
    elif environ.get(ENV_SOCKET):
        socket = ""
        locked["socket"] = ENV_SOCKET
    return Resolved(log_colors, backend, socket, settings.terminal, locked)
