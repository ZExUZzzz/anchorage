import dataclasses

from anchorage.core.containers import ContainerStore
from anchorage.docker.errors import NotFound
from anchorage.docker.models import LogLine
from anchorage.ui.containers.detail_page import ContainerDetailPage
from anchorage.ui.context import AppContext
from tests.core.fakes import DeferredRunner, FakeEngine, make_container, make_event


def make_page(qtbot, context: AppContext) -> ContainerDetailPage:
    page = ContainerDetailPage(context.api, context.containers, context.engine)
    qtbot.addWidget(page)
    return page


def test_show_container_fills_header_and_starts_sessions(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("pulse-nginx-1", project="pulse", image="nginx:alpine")
    engine.add(c)
    context.containers.refresh()
    page = make_page(qtbot, context)
    page.show_container(c.id)
    assert page.title.text() == "pulse-nginx-1"
    assert "running" in page.state_label.text()
    assert "nginx:alpine" in page.meta_prefix.text()
    assert page.buttons["stop"].isEnabled() and not page.buttons["start"].isEnabled()
    assert page.details_tree.topLevelItemCount() > 0
    qtbot.waitUntil(
        lambda: len(engine.log_feeds) == 1 and len(engine.stats_feeds) == 1, timeout=2000
    )
    assert engine.calls_to("logs")[0][2]["tty"] is False
    engine.log_feeds[0].put(LogLine("stdout", "hello from nginx"))
    qtbot.waitUntil(lambda: "hello from nginx" in page.log_view.edit.toPlainText(), timeout=2000)
    page.leave()
    assert engine.log_feeds[0].closed and engine.stats_feeds[0].closed
    assert page.container_id is None


def test_inspect_failure_emits_notice(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    engine.errors["inspect_container"] = NotFound("gone", 404)
    page = make_page(qtbot, context)
    notices: list[str] = []
    page.notice.connect(notices.append)
    page.show_container(c.id)
    assert notices and "gone" in notices[0]
    assert len(engine.log_feeds) == 0


def test_start_event_for_this_container_restarts_sessions(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("solo")
    other = make_container("other")
    engine.add(c, other)
    context.containers.refresh()
    page = make_page(qtbot, context)
    page.show_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    context.engine.event_received.emit(make_event("start", other.id))
    context.engine.event_received.emit(make_event("die", c.id))
    qtbot.wait(50)
    assert len(engine.log_feeds) == 1
    engine.log_feeds[0].put(LogLine("stdout", "old line"))
    context.engine.event_received.emit(make_event("start", c.id))
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 2, timeout=2000)
    qtbot.wait(100)
    assert len(engine.log_feeds) == 2
    assert engine.log_feeds[0].closed
    engine.log_feeds[0].put(LogLine("stdout", "stale"))
    engine.log_feeds[1].put(LogLine("stdout", "fresh line"))
    qtbot.waitUntil(lambda: "fresh line" in page.log_view.edit.toPlainText(), timeout=2000)
    assert "stale" not in page.log_view.edit.toPlainText()
    assert "old line" not in page.log_view.edit.toPlainText()
    context.engine.event_received.emit(make_event("start", c.id))
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 3, timeout=2000)
    qtbot.wait(100)
    assert len(engine.log_feeds) == 3
    page.leave()


def test_start_event_before_details_is_ignored(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    engine.errors["inspect_container"] = NotFound("gone", 404)
    page = make_page(qtbot, context)
    page.show_container(c.id)
    context.engine.event_received.emit(make_event("start", c.id))
    qtbot.wait(100)
    assert len(engine.log_feeds) == 0
    assert len(engine.stats_feeds) == 0
    page.leave()


def test_second_details_does_not_restart_sessions(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    page = make_page(qtbot, context)
    page.show_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    context.containers.inspect(c.id)
    qtbot.waitUntil(lambda: len(engine.calls_to("inspect_container")) == 2, timeout=2000)
    qtbot.wait(100)
    assert len(engine.log_feeds) == 1
    assert not engine.log_feeds[0].closed
    page.leave()


def test_tty_container_opens_log_with_tty(
    qtbot, context: AppContext, engine: FakeEngine, monkeypatch
) -> None:
    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    original = engine.inspect_container
    monkeypatch.setattr(
        engine,
        "inspect_container",
        lambda cid: dataclasses.replace(original(cid), tty=True),
    )
    page = make_page(qtbot, context)
    page.show_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    assert engine.calls_to("logs")[0][2]["tty"] is True
    page.leave()


def test_removed_container_returns_to_list(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    page = make_page(qtbot, context)
    back: list[bool] = []
    page.back_requested.connect(lambda: back.append(True))
    page.show_container(c.id)
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    del engine.containers[c.id]
    context.containers.refresh()
    assert back == [True]
    assert page.container_id is None
    assert engine.log_feeds[0].closed


def test_refresh_updates_buttons_and_busy(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    page = make_page(qtbot, context)
    page.show_container(c.id)
    requested: list[tuple[str, str]] = []
    page.action_requested.connect(lambda a, cid: requested.append((a, cid)))
    page.buttons["stop"].click()
    assert requested == [("stop", c.id)]
    engine.containers[c.id] = make_container("solo", state="exited", container_id=c.id)
    context.containers.refresh()
    assert page.buttons["start"].isEnabled() and not page.buttons["stop"].isEnabled()
    assert "exited" in page.state_label.text()
    page.leave()


def test_action_buttons_follow_busy_state(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("solo")
    engine.add(c)
    runner = DeferredRunner()
    store = ContainerStore(engine, runner)
    store.refresh()
    runner.run_pending()
    page = ContainerDetailPage(engine, store, context.engine)
    qtbot.addWidget(page)
    page.show_container(c.id)
    assert page.buttons["stop"].isEnabled()
    store.stop(c.id)
    assert not any(button.isEnabled() for button in page.buttons.values())
    runner.run_pending()
    assert page.buttons["stop"].isEnabled()
    page.leave()


def test_breadcrumb_buttons_emit_navigation(qtbot, context: AppContext, engine: FakeEngine) -> None:
    c = make_container("pulse-nginx-1", project="pulse")
    solo = make_container("solo")
    engine.add(c, solo)
    context.containers.refresh()
    page = make_page(qtbot, context)
    fired: list[str] = []
    page.list_requested.connect(lambda: fired.append("list"))
    page.project_requested.connect(lambda p: fired.append(f"project:{p}"))
    page.show_container(c.id)
    assert page.crumb_root.text() == "Containers"
    assert page.crumb_project.text() == "pulse" and not page.crumb_project.isHidden()
    page.crumb_project.click()
    page.crumb_root.click()
    assert fired == ["project:pulse", "list"]
    page.show_container(solo.id)
    assert page.crumb_project.isHidden()
    page.leave()


def test_id_button_copies_full_id(qtbot, context: AppContext, engine: FakeEngine) -> None:
    from PySide6.QtWidgets import QApplication

    c = make_container("solo")
    engine.add(c)
    context.containers.refresh()
    page = make_page(qtbot, context)
    copied: list[str] = []
    page.copied.connect(copied.append)
    page.show_container(c.id)
    assert page.id_button.text() == c.short_id
    assert page.id_button.accessibleName() == "Copy container ID"
    page.id_button.click()
    assert QApplication.clipboard().text() == c.id
    assert copied == ["Container ID copied"]
    assert c.short_id not in page.meta_label.text()
    page.leave()
