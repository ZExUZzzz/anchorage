from PySide6.QtCore import QObject

from anchorage.core.engine import EngineService, EngineState
from anchorage.core.workers import TaskRunner
from anchorage.docker.errors import EngineUnavailable
from tests.core.fakes import DeferredRunner, FakeEngine, make_event


class StateLog(QObject):
    def __init__(self, service: EngineService) -> None:
        super().__init__()
        self.states: list[EngineState] = []
        self.events: list[str] = []
        self.versions: list[str] = []
        service.state_changed.connect(self.on_state)
        service.event_received.connect(self.on_event)
        service.version_changed.connect(self.on_version)

    def on_state(self, state: EngineState) -> None:
        self.states.append(state)

    def on_event(self, event) -> None:  # type: ignore[no-untyped-def]
        self.events.append(event.action)

    def on_version(self, version) -> None:  # type: ignore[no-untyped-def]
        self.versions.append(version.version)


def make_service(engine: FakeEngine) -> tuple[EngineService, StateLog]:
    service = EngineService(engine, TaskRunner(inline=True), base_delay=0.02, max_delay=0.05)
    return service, StateLog(service)


def test_start_connects_and_streams_events(qtbot) -> None:
    engine = FakeEngine()
    service, log = make_service(engine)
    service.start()
    assert service.state is EngineState.CONNECTED
    assert log.states == [EngineState.CONNECTING, EngineState.CONNECTED]
    assert log.versions == ["29.8.2"]
    assert service.version is not None
    assert service.socket_path == engine.socket_path
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 1, timeout=2000)
    engine.event_feeds[0].put(make_event("start", "abc"))
    qtbot.waitUntil(lambda: log.events == ["start"], timeout=2000)
    assert service.stop() is True
    assert service.state is EngineState.DISCONNECTED


def test_connect_failure_sets_error_and_retries(qtbot) -> None:
    engine = FakeEngine()
    engine.errors["ping"] = EngineUnavailable("socket missing")
    service, _log = make_service(engine)
    service.start()
    assert service.state is EngineState.ERROR
    assert service.error is not None
    assert "socket missing" in service.error.message
    del engine.errors["ping"]
    qtbot.waitUntil(lambda: service.state is EngineState.CONNECTED, timeout=2000)
    assert service.error is None
    service.stop()


def test_backoff_grows_and_is_capped() -> None:
    engine = FakeEngine()
    service = EngineService(engine, TaskRunner(inline=True), base_delay=2.0, max_delay=30.0)
    assert [service.retry_delay(n) for n in range(6)] == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_events_stream_end_reconnects(qtbot) -> None:
    engine = FakeEngine()
    service, log = make_service(engine)
    service.start()
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 1, timeout=2000)
    engine.event_feeds[0].end()
    qtbot.waitUntil(lambda: EngineState.DISCONNECTED in log.states, timeout=2000)
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 2, timeout=2000)
    assert service.state is EngineState.CONNECTED
    engine.event_feeds[1].put(make_event("die", "abc"))
    qtbot.waitUntil(lambda: log.events == ["die"], timeout=2000)
    service.stop()


def test_stop_does_not_reconnect(qtbot) -> None:
    engine = FakeEngine()
    service, _log = make_service(engine)
    service.start()
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 1, timeout=2000)
    service.stop()
    assert engine.event_feeds[0].closed
    qtbot.wait(150)
    assert len(engine.event_feeds) == 1
    assert service.state is EngineState.DISCONNECTED


def test_stale_worker_end_is_ignored_after_reconnect(qtbot) -> None:
    engine = FakeEngine()
    service, log = make_service(engine)
    service.start()
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 1, timeout=2000)
    service.reconnect_now()
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 2, timeout=2000)
    assert engine.event_feeds[0].closed
    qtbot.wait(150)
    assert service.state is EngineState.CONNECTED
    assert log.states.count(EngineState.DISCONNECTED) == 0
    service.stop()


def test_probe_finishing_after_stop_is_ignored(qtbot) -> None:
    engine = FakeEngine()
    runner = DeferredRunner()
    service = EngineService(engine, runner, base_delay=0.02, max_delay=0.05)
    service.start()
    service.stop()
    runner.run_pending()
    qtbot.wait(100)
    assert service.state is EngineState.DISCONNECTED
    assert len(engine.event_feeds) == 0


def test_failed_probe_after_stop_does_not_retry(qtbot) -> None:
    engine = FakeEngine()
    engine.errors["ping"] = EngineUnavailable("socket missing")
    runner = DeferredRunner()
    service = EngineService(engine, runner, base_delay=0.02, max_delay=0.05)
    service.start()
    service.stop()
    runner.run_pending()
    qtbot.wait(100)
    assert service.state is EngineState.DISCONNECTED
    assert runner.pending == []


def test_reconnect_after_stop_leaves_one_live_feed(qtbot) -> None:
    engine = FakeEngine()
    runner = DeferredRunner()
    service = EngineService(engine, runner, base_delay=0.02, max_delay=0.05)
    service.start()
    service.stop()
    service.reconnect_now()
    runner.run_pending()
    runner.run_pending()
    qtbot.waitUntil(lambda: len(engine.event_feeds) == 1, timeout=2000)
    qtbot.wait(100)
    assert len(engine.event_feeds) == 1
    assert not engine.event_feeds[0].closed
    assert service.state is EngineState.CONNECTED
    service.stop()


def test_retry_delay_does_not_overflow() -> None:
    service = EngineService(FakeEngine(), TaskRunner(inline=True), base_delay=2.0, max_delay=30.0)
    assert service.retry_delay(5000) == 30.0
