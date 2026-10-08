"""Persistent user settings and their precedence against flags and the environment."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

LOG_COLOR_MODES = ("stream", "level")
BACKENDS = ("native", "dockerpy")
# Interface languages; the empty string stands for "follow the system locale".
LANGUAGE_CODES = ("en", "ru", "de", "es", "fr", "zh_CN")

DEFAULT_LOG_COLORS = "stream"
DEFAULT_BACKEND = "native"
DEFAULT_LANGUAGE = ""

ENV_LOG_COLORS = "ANCHORAGE_LOG_COLORS"
ENV_BACKEND = "ANCHORAGE_BACKEND"
ENV_LANGUAGE = "ANCHORAGE_LANGUAGE"
ENV_SOCKET = "DOCKER_HOST"

GROUP = "settings"

log = logging.getLogger(__name__)


class InvalidEnvironment(ValueError):
    """An environment variable that selects a setting holds an unusable value."""


def chinese_variant(subtags: list[str]) -> str:
    """``zh_CN`` for Simplified Chinese subtags (after ``zh``), else ``""``.

    Only Simplified Chinese is shipped. The script subtag decides first (``Hans`` or
    ``Hant``); without one, the Traditional regions (TW, HK, MO) mean Traditional.
    """
    lowered = {tag.lower() for tag in subtags}
    if "hans" in lowered:
        return "zh_CN"
    if "hant" in lowered or lowered & {"tw", "hk", "mo"}:
        return DEFAULT_LANGUAGE
    return "zh_CN"


def normalize_language(value: str | None) -> str:
    """The supported code for ``value`` (``ru``, ``ru_RU``, ``zh-cn``, ``zh``, ...), else ``""``.

    ``""`` means automatic, so an unknown or unsupported value never fails.
    """
    if not value:
        return DEFAULT_LANGUAGE
    text = value.strip().replace("-", "_").split(".")[0].split("@")[0]
    for code in LANGUAGE_CODES:
        if text.lower() == code.lower():
            return code
    base, *rest = text.lower().split("_")
    if base == "zh":
        # Bare ``zh`` and ``zh_Hans`` mean Simplified; Traditional variants stay automatic.
        return chinese_variant(rest)
    return base if base in LANGUAGE_CODES else DEFAULT_LANGUAGE


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
    def language(self) -> str:
        return normalize_language(self._text("language"))

    @language.setter
    def language(self, value: str) -> None:
        if value and value not in LANGUAGE_CODES:
            raise ValueError(f"unknown language {value!r}")
        self._write("language", value)

    @property
    def socket(self) -> str:
        return (self._text("socket") or "").strip()

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
    An empty ``socket`` is ambiguous, so the dialog reads ``locked["socket"]`` to tell
    ``DOCKER_HOST`` from automatic discovery.
    """

    log_colors: str = DEFAULT_LOG_COLORS
    backend: str = DEFAULT_BACKEND
    socket: str = ""
    terminal: str = ""
    locked: dict[str, str] = field(default_factory=dict)
    language: str = DEFAULT_LANGUAGE

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

    language = settings.language
    if args.language is not None:
        language = "" if args.language == "auto" else normalize_language(args.language)
        locked["language"] = "--language"
    elif environ.get(ENV_LANGUAGE):
        value = environ[ENV_LANGUAGE]
        language = "" if value == "auto" else normalize_language(value)
        if value != "auto" and not language:
            log.warning(
                "%s=%r is not a supported language; following the system", ENV_LANGUAGE, value
            )
        locked["language"] = ENV_LANGUAGE
    return Resolved(log_colors, backend, socket, settings.terminal, locked, language)
