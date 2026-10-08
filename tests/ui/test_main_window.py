from PySide6.QtCore import QSettings, QSize

from anchorage.core.engine import EngineState
from anchorage.core.settings import Resolved
from anchorage.core.terminal import Launch
from anchorage.docker.errors import Conflict, EngineUnavailable, PermissionDenied
from anchorage.docker.models import LogLine
from anchorage.ui.context import AppContext
from anchorage.ui.main_window import MainWindow
from tests.core.fakes import FakeEngine, make_container, make_image, make_network, make_volume


class Confirmer:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, list[str]]] = []

    def __call__(self, title: str, text: str, buttons: list[str]) -> str:
        self.calls.append((title, text, buttons))
        return self.answer


def build(
    qtbot, context: AppContext, answer: str = "Cancel", launch=None
) -> tuple[MainWindow, Confirmer]:
    confirmer = Confirmer(answer)
    window = MainWindow(context, confirm=confirmer, launch_shell=launch)
    qtbot.addWidget(window)
    return window, confirmer


def test_connected_engine_populates_pages_and_counts(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    engine.add(make_container("a", project="p"), make_container("b", state="exited"))
    engine.images = [make_image(("nginx:alpine",))]
    window, _ = build(qtbot, context)
    context.engine.start()
    assert window.containers_page.proxy.rowCount() == 2
    assert window.images_page.proxy.rowCount() == 1
    assert "2 containers" in window.status_counts.text()
    assert "1 running" in window.status_counts.text()
    assert "1 image" in window.status_counts.text()
    assert window.containers_page.stack.currentWidget() is window.containers_page.tree


def test_engine_error_shows_empty_states(qtbot, context: AppContext, engine: FakeEngine) -> None:
    engine.errors["ping"] = EngineUnavailable("refused")
    window, _ = build(qtbot, context)
    context.engine.start()
    assert window.containers_page.stack.currentWidget() is window.containers_page.empty
    assert "not running" in window.containers_page.empty.title.text()
    assert window.images_page.stack.currentWidget() is window.images_page.empty
    del engine.errors["ping"]
    window.containers_page.empty.button.click()
    assert context.engine.state is EngineState.CONNECTED
    assert window.containers_page.stack.currentWidget() is window.containers_page.tree


def test_unreachable_saved_socket_is_named_in_the_empty_state(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    engine.errors["ping"] = EngineUnavailable("refused")
    resolved = Resolved("stream", "native", "/saved/docker.sock", "")
    window = MainWindow(context, resolved=resolved)
    qtbot.addWidget(window)
    context.engine.start()
    title = window.containers_page.empty.title.text()
    message = window.containers_page.empty.message.text()
    assert "not running" not in title
    assert "The socket set in Settings (/saved/docker.sock) is not available." in message
    assert "clear it to find the daemon automatically" in message


def test_socket_from_a_flag_keeps_the_daemon_empty_state(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    engine.errors["ping"] = EngineUnavailable("refused")
    resolved = Resolved("stream", "native", "/x.sock", "", {"socket": "--socket"})
    window = MainWindow(context, resolved=resolved)
    qtbot.addWidget(window)
    context.engine.start()
    assert "not running" in window.containers_page.empty.title.text()


def test_open_container_and_back(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    window, _ = build(qtbot, context)
    context.engine.start()
    window.containers_page.container_activated.emit(c.id)
    assert window.pages.currentIndex() == MainWindow.PAGE_DETAIL
    assert window.detail_page.container_id == c.id
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    window.detail_page.back_requested.emit()
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert engine.log_feeds[0].closed
    window.sidebar.select("images")
    assert window.pages.currentIndex() == MainWindow.PAGE_IMAGES


def test_actions_route_to_store_with_confirmation(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("solo")
    engine.add(c)
    window, confirmer = build(qtbot, context, answer="Cancel")
    context.engine.start()
    window.perform("stop", c.id)
    assert engine.calls_to("stop_container")[0][1] == (c.id,)
    window.perform("remove", c.id)
    assert confirmer.calls and "solo" in confirmer.calls[0][1]
    assert confirmer.calls[0][2] == ["Force remove", "Cancel"]
    assert engine.calls_to("remove_container") == []
    confirmer.answer = "Force remove"
    window.perform("remove", c.id)
    assert engine.calls_to("remove_container")[-1][2]["force"] is True
    confirmer.answer = "Remove"
    engine.containers[c.id] = make_container("solo", state="exited", container_id=c.id)
    context.containers.refresh()
    window.perform("remove", c.id)
    assert engine.calls_to("remove_container")[-1][2]["force"] is False
    assert confirmer.calls[-1][2] == ["Remove", "Cancel"]


def test_action_failure_shows_toast(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    engine.errors["restart_container"] = Conflict("cannot restart", 409)
    window, _ = build(qtbot, context)
    context.engine.start()
    window.perform("restart", c.id)
    assert not window.toast.isHidden()
    assert "cannot restart" in window.toast.label.text()


def test_open_shell_success_and_failure(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    launches: list[str] = []

    def ok(container_id: str) -> Launch:
        launches.append(container_id)
        return Launch(("docker", "exec"), ("konsole", "-e"), None)

    window, confirmer = build(qtbot, context, launch=ok)
    context.engine.start()
    window.perform("shell", c.id)
    assert launches == [c.id]
    assert confirmer.calls == []

    def fail(container_id: str) -> Launch:
        return Launch(
            ("docker", "exec", "-it", container_id, "sh"), None, "no terminal emulator found"
        )

    window2, confirmer2 = build(qtbot, context, launch=fail)
    window2.perform("shell", c.id)
    assert confirmer2.calls and "docker exec -it" in confirmer2.calls[0][1]


def test_images_actions(qtbot, context: AppContext, engine: FakeEngine) -> None:
    engine.images = [make_image(("nginx:alpine",))]
    window, confirmer = build(qtbot, context, answer="Remove")
    context.engine.start()
    window.images_page.remove_requested.emit("nginx:alpine")
    assert engine.calls_to("remove_image")[0][1] == ("nginx:alpine",)
    confirmer.answer = "Prune"
    window.images_page.prune_requested.emit()
    assert engine.calls_to("prune_images")
    assert "reclaimed" in window.toast.label.text().lower()
    window.images_page.pull_requested.emit("redis", "7")
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    assert not window.images_page.panel.isHidden()
    assert "redis:7" in window.images_page.panel.title.text()


def test_close_with_live_sessions_and_pull(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    window, _ = build(qtbot, context)
    context.engine.start()
    window.open_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    engine.log_feeds[0].put(LogLine("stdout", "x"))
    window.images_page.pull_requested.emit("redis", "7")
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    window.close()
    assert engine.log_feeds[0].closed
    assert engine.stats_feeds[0].closed
    assert engine.pull_feeds[0].closed
    assert engine.event_feeds[0].closed
    assert context.engine.state is EngineState.DISCONNECTED


def test_sidebar_leaves_detail_and_disconnect_closes_sessions(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("solo")
    engine.add(c)
    window, _ = build(qtbot, context)
    context.engine.start()
    window.open_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    window.sidebar.select("images")
    assert engine.log_feeds[0].closed
    assert window.detail_page.container_id is None

    window.sidebar.select("containers")
    window.open_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 2, timeout=2000)
    assert window.pages.currentIndex() == MainWindow.PAGE_DETAIL
    engine.errors["ping"] = EngineUnavailable("gone")
    context.engine.reconnect_now()
    assert context.engine.state is not EngineState.CONNECTED
    assert window.detail_page.container_id is None
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert all(feed.closed for feed in engine.log_feeds)
    assert all(feed.closed for feed in engine.stats_feeds)
    assert window.status_counts.text() == ""


def test_selecting_current_section_leaves_detail_page(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("solo")
    engine.add(c)
    window, _ = build(qtbot, context)
    context.engine.start()
    window.open_container(c.id)
    assert window.pages.currentIndex() == MainWindow.PAGE_DETAIL
    window.sidebar.select("containers")
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert window.detail_page.container_id is None


def test_permission_denied_shows_group_hint(qtbot, context: AppContext, engine: FakeEngine) -> None:
    engine.errors["ping"] = PermissionDenied("denied")
    window, _ = build(qtbot, context)
    context.engine.start()
    empty = window.containers_page.empty
    assert window.containers_page.stack.currentWidget() is empty
    assert "docker group" in empty.message.text()


def test_confirmation_text_is_selectable(qtbot, context: AppContext, monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    flags: list[Qt.TextInteractionFlag] = []

    def fake_exec(self: QMessageBox) -> int:
        flags.append(self.textInteractionFlags())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    window = MainWindow(context)
    qtbot.addWidget(window)
    window._ask("Shell", "docker exec -it abc sh", ["Cancel"])
    assert flags and flags[0] & Qt.TextInteractionFlag.TextSelectableByMouse


def test_volumes_and_networks_pages_wired(qtbot, context: AppContext, engine: FakeEngine) -> None:
    engine.volumes = [make_volume("orphan"), make_volume("pulse_dbdata", project="pulse")]
    engine.networks = [make_network("pulse_default", project="pulse")]
    engine.add(
        make_container(
            "pulse-db-1",
            project="pulse",
            volumes={"pulse_dbdata": "/var/lib/mysql"},
            networks={"pulse_default": "172.18.0.2"},
        )
    )
    window, confirmer = build(qtbot, context, answer="Cancel")
    context.engine.start()
    window.sidebar.select("volumes")
    assert window.pages.currentIndex() == MainWindow.PAGE_VOLUMES
    assert window.volumes_page.proxy.rowCount() == 2
    window.sidebar.select("networks")
    assert window.pages.currentIndex() == MainWindow.PAGE_NETWORKS
    assert window.networks_page.proxy.rowCount() == 1
    counts = window.status_counts.text()
    assert "2 volumes" in counts and "1 network" in counts
    window.volumes_page.remove_requested.emit("orphan")
    assert confirmer.calls[-1][2] == ["Remove", "Cancel"]
    assert engine.calls_to("remove_volume") == []
    confirmer.answer = "Remove"
    window.volumes_page.remove_requested.emit("orphan")
    assert engine.calls_to("remove_volume")[0][1] == ("orphan",)
    assert engine.calls_to("remove_volume")[0][2]["force"] is False
    confirmer.answer = "Prune"
    window.volumes_page.prune_requested.emit()
    assert "not used by any container" in confirmer.calls[-1][1]
    assert "Named volumes are included" in confirmer.calls[-1][1]
    assert engine.calls_to("prune_volumes")
    assert "reclaimed" in window.toast.label.text().lower()
    confirmer.answer = "Remove"
    window.networks_page.remove_requested.emit("pulse_default")
    network_id = context.networks.row("pulse_default").network.id
    assert engine.calls_to("remove_network")[0][1] == (network_id,)
    confirmer.answer = "Prune"
    window.networks_page.prune_requested.emit()
    assert engine.calls_to("prune_networks")


def test_member_click_opens_container_and_crumbs_navigate(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    engine.networks = [make_network("pulse_default", project="pulse")]
    c = make_container("pulse-db-1", project="pulse", networks={"pulse_default": "172.18.0.2"})
    engine.add(c, make_container("solo"))
    window, _ = build(qtbot, context)
    context.engine.start()
    window.sidebar.select("networks")
    window.networks_page.container_activated.emit(c.id)
    assert window.pages.currentIndex() == MainWindow.PAGE_DETAIL
    assert window.detail_page.container_id == c.id
    window.detail_page.project_requested.emit("pulse")
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert window.containers_page.filter_edit.text() == "pulse"
    assert window.containers_page.proxy.rowCount() == 1
    assert window.detail_page.container_id is None
    window.open_container(c.id)
    window.detail_page.list_requested.emit()
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert window.containers_page.filter_edit.text() == ""
    window.open_container(c.id)
    window.detail_page.copied.emit("Container ID copied")
    assert window.toast.label.text() == "Container ID copied"
    window.show_list()  # stop the log stream before the fixture shuts down


def test_engine_error_sets_empty_state_on_all_pages(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    engine.errors["ping"] = EngineUnavailable("refused")
    window, _ = build(qtbot, context)
    context.engine.start()
    for page in (window.volumes_page, window.networks_page):
        assert page.stack.currentWidget() is page.empty


def test_back_keeps_typed_filter_but_crumb_clears_project_filter(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("maria-1", project="pulse")
    engine.add(c, make_container("solo"))
    window, _ = build(qtbot, context)
    context.engine.start()
    window.containers_page.filter_edit.setText("maria")
    window.open_container(c.id)
    window.show_list()
    assert window.containers_page.filter_edit.text() == "maria"
    window.show_project("pulse")
    assert window.containers_page.proxy.project == "pulse"
    window.show_list()
    assert window.containers_page.filter_edit.text() == ""
    assert window.containers_page.proxy.project is None


def test_back_returns_to_origin_page_and_crumb_to_containers(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    engine.networks = [make_network("pulse_default", project="pulse")]
    c = make_container("pulse-db-1", project="pulse", networks={"pulse_default": "172.18.0.2"})
    engine.add(c)
    window, _ = build(qtbot, context)
    context.engine.start()
    window.sidebar.select("networks")
    window.networks_page.container_activated.emit(c.id)
    assert window.pages.currentIndex() == MainWindow.PAGE_DETAIL
    window.detail_page.back_requested.emit()
    assert window.pages.currentIndex() == MainWindow.PAGE_NETWORKS
    assert window.sidebar.current_key() == "networks"
    assert window.detail_page.container_id is None
    window.networks_page.container_activated.emit(c.id)
    window.detail_page.list_requested.emit()
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert window.sidebar.current_key() == "containers"
    window.sidebar.select("volumes")
    window.volumes_page.container_activated.emit(c.id)
    window.detail_page.project_requested.emit("pulse")
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS
    assert window.sidebar.current_key() == "containers"
    window.open_container(c.id)
    window.detail_page.back_requested.emit()
    assert window.pages.currentIndex() == MainWindow.PAGE_CONTAINERS


def ini(tmp_path) -> QSettings:  # type: ignore[no-untyped-def]
    return QSettings(str(tmp_path / "anchorage.ini"), QSettings.Format.IniFormat)


def test_window_geometry_persists(qtbot, context: AppContext, tmp_path) -> None:
    window = MainWindow(context, settings=ini(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    # The offscreen screen is 800 wide and the window's minimum width is close to that.
    window.resize(798, 650)
    window.close()
    again = MainWindow(context, settings=ini(tmp_path))
    qtbot.addWidget(again)
    assert again.size() == QSize(798, 650)


def test_corrupt_geometry_setting_is_ignored(qtbot, context: AppContext, tmp_path) -> None:
    settings = ini(tmp_path)
    settings.setValue("window/geometry", "not a byte array")
    settings.sync()
    window = MainWindow(context, settings=ini(tmp_path))
    qtbot.addWidget(window)
    assert window.size() == QSize(1180, 720)
