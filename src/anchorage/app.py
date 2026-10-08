"""Application entry point: CLI flags, logging, services and the main window."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from anchorage import APP_ID, __version__
from anchorage.docker.client import DockerClient, EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.transport import DEFAULT_SOCKET_PATH, Transport
from anchorage.ui.context import AppContext
from anchorage.ui.main_window import MainWindow
from anchorage.ui.theme import STYLESHEET, app_icon

log = logging.getLogger(__name__)


class BackendUnavailable(Exception):
    """The selected backend cannot be used (for example its optional package is missing)."""


LOG_COLOR_MODES = ("stream", "level")
BACKENDS = ("native", "dockerpy")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="anchorage", description="Native Docker Engine client")
    parser.add_argument("--socket", help="path to the Docker UNIX socket")
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=os.environ.get("ANCHORAGE_BACKEND", "native"),
        help="Docker API client implementation (default: native)",
    )
    parser.add_argument(
        "--log-colors",
        choices=LOG_COLOR_MODES,
        default=os.environ.get("ANCHORAGE_LOG_COLORS", "stream"),
        help="colour container logs by output stream (stderr red) or by detected level",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging to stderr")
    parser.add_argument("--version", action="version", version=f"anchorage {__version__}")
    args = parser.parse_args(argv[1:])
    if args.log_colors not in LOG_COLOR_MODES:
        parser.error(
            f"invalid ANCHORAGE_LOG_COLORS value {args.log_colors!r} "
            f"(choose from {', '.join(LOG_COLOR_MODES)})"
        )
    if args.backend not in BACKENDS:  # argparse does not check a default against ``choices``
        parser.error(
            f"invalid ANCHORAGE_BACKEND value {args.backend!r} (choose from {', '.join(BACKENDS)})"
        )
    return args


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


def create_application(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setApplicationName("Anchorage")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLESHEET)
    return app


def run(argv: list[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    app = create_application(argv[:1])
    # Qt's event loop never returns to Python, so the default Python handler cannot run;
    # restore the OS default so Ctrl+C in the launching terminal ends the process.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        api, warning = create_api(args.socket, args.backend)
    except BackendUnavailable as exc:
        print(f"anchorage: {exc}", file=sys.stderr)
        return 2
    context = AppContext.build(api, parent=app)
    window = MainWindow(context, settings=QSettings("Anchorage", "Anchorage"))
    window.detail_page.log_view.set_color_mode(args.log_colors)
    if args.backend == "dockerpy":
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
