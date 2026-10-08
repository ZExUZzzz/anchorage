"""Build the app the way ``run()`` does and close it against the real daemon, read-only."""

import os

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from anchorage.docker.client import DockerClient
from anchorage.docker.errors import DockerError
from anchorage.docker.transport import discover_socket_path
from anchorage.ui.context import AppContext
from anchorage.ui.main_window import MainWindow

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> DockerClient:
    path = discover_socket_path()
    if not os.path.exists(path):
        pytest.skip(f"no Docker socket at {path}")
    client = DockerClient.from_env()
    try:
        client.ping()
    except DockerError as exc:
        pytest.skip(f"daemon not reachable: {exc}")
    return client


def test_window_close_and_quit_shut_down_cleanly(qtbot, client: DockerClient) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    context = AppContext.build(client)
    window = MainWindow(context)
    window.show()
    context.engine.start()
    QTimer.singleShot(1500, window.close)
    QTimer.singleShot(1600, app.quit)
    assert app.exec() == 0
    assert context.shutdown() is True
