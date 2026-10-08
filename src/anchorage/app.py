"""Application entry point: CLI flags, logging, services and the main window."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import signal
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from anchorage import APP_ID, __version__
from anchorage.core.settings import (
    BACKENDS,
    LOG_COLOR_MODES,
    AppSettings,
    InvalidEnvironment,
    Resolved,
    resolve,
)
from anchorage.docker.client import DockerClient, EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.transport import DEFAULT_SOCKET_PATH, Transport
from anchorage.ui.context import AppContext
from anchorage.ui.main_window import MainWindow
from anchorage.ui.theme import STYLESHEET, app_icon

log = logging.getLogger(__name__)


class BackendUnavailable(Exception):
    """The selected backend cannot be used (for example its optional package is missing)."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anchorage", description="Native Docker Engine client")
    parser.add_argument("--socket", help="path to the Docker UNIX socket")
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        help="Docker API client implementation (default: native)",
    )
    parser.add_argument(
        "--log-colors",
        choices=LOG_COLOR_MODES,
        help="colour container logs by output stream (stderr red) or by detected level",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging to stderr")
    parser.add_argument("--version", action="version", version=f"anchorage {__version__}")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse flags; options that were not given stay ``None`` so ``resolve`` can tell."""
    return build_parser().parse_args(argv[1:])


def resolve_or_exit(argv: list[str], settings: AppSettings) -> tuple[argparse.Namespace, Resolved]:
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    try:
        return args, resolve(args, os.environ, settings)
    except InvalidEnvironment as exc:
        parser.error(str(exc))


def create_api(socket_path: str | None, backend: str = "native") -> tuple[EngineAPI, str | None]:
    """Return the client and, when the environment was unusable, a warning for the user."""
    if backend == "dockerpy":
        try:
            from anchorage.docker.dockerpy import DockerPyClient
        except ImportError:
            raise BackendUnavailable(
                "the docker-py backend is not installed (pip install 'anchorage-docker[dockerpy]')"
            ) from None

        def make(path: str) -> EngineAPI:
            return DockerPyClient(path)

        def from_env() -> EngineAPI:
            return DockerPyClient.from_env()
    else:

        def make(path: str) -> EngineAPI:
            return DockerClient(Transport(path))

        def from_env() -> EngineAPI:
            return DockerClient.from_env()

    if socket_path:
        return make(socket_path), None
    try:
        return from_env(), None
    except DockerError as exc:
        log.warning("%s; falling back to %s", exc.message, DEFAULT_SOCKET_PATH)
        warning = f"{exc.message}; using {DEFAULT_SOCKET_PATH}"
        return make(DEFAULT_SOCKET_PATH), warning


def create_api_or_fall_back(
    resolved: Resolved, settings: AppSettings
) -> tuple[EngineAPI, Resolved, str | None]:
    """Create the client; a saved but unusable docker-py backend falls back to native.

    A backend fixed by a flag or variable is never replaced: the error names its source.
    """
    try:
        api, warning = create_api(resolved.socket or None, resolved.backend)
    except BackendUnavailable as exc:
        source = resolved.locked.get("backend")
        if source is not None:
            usage = f"{source} dockerpy" if source.startswith("--") else f"{source}=dockerpy"
            raise BackendUnavailable(f"{exc} (requested by {usage})") from None
        resolved = dataclasses.replace(resolved, backend="native")
        settings.backend = "native"
        api, _ = create_api(resolved.socket or None, "native")
        return api, resolved, "docker-py is not installed; using the native backend"
    return api, resolved, warning


def create_application(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setApplicationName("Anchorage")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLESHEET)
    return app


def run(argv: list[str]) -> int:
    store = QSettings("Anchorage", "Anchorage")
    settings = AppSettings(store)
    args, resolved = resolve_or_exit(argv, settings)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    app = create_application(argv[:1])
    # Qt's event loop never returns to Python, so the default Python handler cannot run;
    # restore the OS default so Ctrl+C in the launching terminal ends the process.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        api, resolved, warning = create_api_or_fall_back(resolved, settings)
    except BackendUnavailable as exc:
        print(f"anchorage: {exc}", file=sys.stderr)
        return 2
    context = AppContext.build(api, parent=app)
    window = MainWindow(
        context,
        settings=store,
        app_settings=settings,
        resolved=resolved,
    )
    window.detail_page.log_view.set_color_mode(resolved.log_colors)
    if resolved.backend == "dockerpy":
        window.sidebar.set_socket(f"{context.engine.socket_path} \u00b7 docker-py")
    # Connection order is call order: dispose the detail sessions before the stores shut down.
    app.aboutToQuit.connect(window.detail_page.leave)
    app.aboutToQuit.connect(context.shutdown)
    window.show()
    if warning:
        window.toast.show_message(warning, timeout_ms=0)
    context.engine.start()
    rc = app.exec()
    if not context.shutdown():
        # A worker is still blocked in the daemon; Qt must not destroy its running thread.
        log.warning("a worker missed its shutdown deadline; exiting without cleanup")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(rc)
    return rc
