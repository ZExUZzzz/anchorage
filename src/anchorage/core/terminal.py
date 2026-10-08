"""Open an interactive shell in a container using the user's terminal emulator."""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QProcess

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


def detected_terminal(environ: Mapping[str, str] | None = None, which: Which = shutil.which) -> str:
    """The automatically chosen terminal command line, or an empty string when none is found."""
    found = find_terminal(environ, which)
    return shlex.join(found) if found else ""


def open_shell(
    container_id: str,
    *,
    command: str = "",
    environ: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    launcher: Callable[[list[str]], bool] | None = None,
) -> Launch:
    """Open a shell; a non-blank ``command`` replaces the automatic terminal detection."""
    docker = which("docker")
    if not docker:
        return Launch(
            exec_command(container_id),
            None,
            QCoreApplication.translate("Terminal", "docker CLI not found in PATH"),
        )
    exec_argv = exec_command(container_id, docker)
    terminal: tuple[str, ...] | None
    if command.strip():
        try:
            terminal = tuple(shlex.split(command))
        except ValueError as exc:
            return Launch(
                exec_argv,
                None,
                QCoreApplication.translate("Terminal", "invalid terminal command ({error})").format(
                    error=exc
                ),
            )
        if not terminal or not terminal[0]:
            return Launch(
                exec_argv, None, QCoreApplication.translate("Terminal", "empty terminal command")
            )
        terminal = (os.path.expanduser(terminal[0]), *terminal[1:])
        if not which(terminal[0]):
            return Launch(
                exec_argv,
                None,
                QCoreApplication.translate(
                    "Terminal", "terminal command {command} not found"
                ).format(command=repr(terminal[0])),
            )
    else:
        terminal = find_terminal(environ, which)
        if terminal is None:
            return Launch(
                exec_argv,
                None,
                QCoreApplication.translate("Terminal", "no terminal emulator found"),
            )
    argv = [*terminal, *exec_argv]
    started = (launcher or _start_detached)(argv)
    return Launch(
        exec_argv,
        terminal,
        None if started else QCoreApplication.translate("Terminal", "failed to start the terminal"),
    )
