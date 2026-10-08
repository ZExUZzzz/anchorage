"""Open an interactive shell in a container using the user's terminal emulator."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import QProcess

SHELL_COMMAND = "command -v bash >/dev/null 2>&1 && exec bash || exec sh"

KNOWN_TERMINALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("konsole", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("kitty", ()),
    ("alacritty", ("-e",)),
    ("foot", ()),
    ("xfce4-terminal", ("-x",)),
    ("xterm", ("-e",)),
)
_FLAGS = dict(KNOWN_TERMINALS)

Which = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class Launch:
    command: tuple[str, ...]
    terminal: tuple[str, ...] | None
    reason: str | None

    @property
    def ok(self) -> bool:
        return self.reason is None


def exec_command(container_id: str, docker: str = "docker") -> tuple[str, ...]:
    return (docker, "exec", "-it", container_id, "sh", "-c", SHELL_COMMAND)


def find_terminal(
    environ: Mapping[str, str] | None = None, which: Which = shutil.which
) -> tuple[str, ...] | None:
    env = os.environ if environ is None else environ
    if which("xdg-terminal-exec"):
        return ("xdg-terminal-exec",)
    preferred = env.get("TERMINAL")
    if preferred and which(preferred):
        flags = _FLAGS.get(os.path.basename(preferred), ("-e",))
        return (preferred, *flags)
    for name, flags in KNOWN_TERMINALS:
        if which(name):
            return (name, *flags)
    return None


def _start_detached(argv: list[str]) -> bool:
    started, _pid = QProcess.startDetached(argv[0], argv[1:])
    return bool(started)


def open_shell(
    container_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    launcher: Callable[[list[str]], bool] | None = None,
) -> Launch:
    docker = which("docker")
    if not docker:
        return Launch(exec_command(container_id), None, "docker CLI not found in PATH")
    command = exec_command(container_id, docker)
    terminal = find_terminal(environ, which)
    if terminal is None:
        return Launch(command, None, "no terminal emulator found")
    argv = [*terminal, *command]
    started = (launcher or _start_detached)(argv)
    return Launch(command, terminal, None if started else "failed to start the terminal")
