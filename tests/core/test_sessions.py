from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QObject

from anchorage.core.sessions import LogSession, StatsSession
from anchorage.docker.errors import NotFound
from anchorage.docker.models import ContainerStats, LogLine
from tests.core.fakes import FakeEngine


class LogWatcher(QObject):
    def __init__(self, session: LogSession) -> None:
        super().__init__()
        self.batches: list[list[LogLine]] = []
        self.ended: list[object] = []
        session.lines_added.connect(self.on_lines)
        session.ended.connect(self.on_ended)

    def on_lines(self, lines: list[LogLine]) -> None:
        self.batches.append(lines)

    def on_ended(self, error: object) -> None:
        self.ended.append(error)


class StatsWatcher(QObject):
    def __init__(self, session: StatsSession) -> None:
        super().__init__()
        self.points: list[object] = []
        self.ended: list[object] = []
        session.sample_added.connect(self.on_point)
        session.ended.connect(self.on_ended)

    def on_point(self, point: object) -> None:
        self.points.append(point)

    def on_ended(self, error: object) -> None:
        self.ended.append(error)


def sample(seconds: int | None, rx: int, tx: int, read: int = 0, write: int = 0) -> ContainerStats:
    if seconds is not None:
        at = datetime(2026, 10, 3, 0, 0, tzinfo=UTC) + timedelta(seconds=seconds)
    else:
        at = None
    return ContainerStats(
        read_at=at,
        cpu_percent=5.0,
        memory_usage=100,
        memory_limit=1000,
        network_rx=rx,
        network_tx=tx,
        block_read=read,
        block_write=write,
        pids=3,
    )


def test_log_session_buffers_and_emits(qtbot) -> None:
    engine = FakeEngine()
    session = LogSession(engine, "abc", tty=False, tail=50, max_lines=3)
    watcher = LogWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    assert engine.calls_to("logs")[0][2] == {"tty": False, "tail": 50, "timestamps": True}
    feed = engine.log_feeds[0]
    for i in range(5):
        feed.put(LogLine("stdout", f"line {i}"))
    qtbot.waitUntil(lambda: sum(len(b) for b in watcher.batches) == 5, timeout=2000)
    assert [line.text for line in session.lines] == ["line 2", "line 3", "line 4"]
    assert session.active is True
    session.stop()
    qtbot.waitUntil(lambda: watcher.ended == [None], timeout=2000)
    assert session.active is False
    assert feed.closed
    assert session.wait()


def test_log_session_reports_open_error(qtbot) -> None:
    engine = FakeEngine()
    engine.errors["logs"] = NotFound("no such container", 404)
    session = LogSession(engine, "abc", tty=True)
    watcher = LogWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(watcher.ended) == 1, timeout=2000)
    assert isinstance(watcher.ended[0], NotFound)
    assert session.active is False
    assert session.wait()


def test_log_session_ignores_late_items(qtbot) -> None:
    engine = FakeEngine()
    session = LogSession(engine, "abc", tty=False, max_lines=10)
    watcher = LogWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    feed = engine.log_feeds[0]
    feed.put(LogLine("stdout", "line 1"))
    qtbot.waitUntil(lambda: sum(len(b) for b in watcher.batches) == 1, timeout=2000)
    assert len(session.lines) == 1
    session.stop()
    qtbot.waitUntil(lambda: watcher.ended == [None], timeout=2000)
    initial_batches = len(watcher.batches)
    initial_lines = len(session.lines)
    session._on_items([LogLine("stdout", "late")])
    assert len(watcher.batches) == initial_batches
    assert len(session.lines) == initial_lines
    feed.end()
    assert session.wait()


def test_stats_session_computes_rates(qtbot) -> None:
    engine = FakeEngine()
    session = StatsSession(engine, "abc", max_points=2)
    watcher = StatsWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(engine.stats_feeds) == 1, timeout=2000)
    feed = engine.stats_feeds[0]
    feed.put(sample(0, rx=1000, tx=100))
    feed.put(sample(2, rx=3000, tx=100, write=4096))
    feed.put(sample(4, rx=3000, tx=400))
    qtbot.waitUntil(lambda: len(watcher.points) == 3, timeout=2000)
    first, second, third = watcher.points
    assert (first.net_rx_rate, first.net_tx_rate) == (0.0, 0.0)
    assert (second.net_rx_rate, second.block_write_rate) == (1000.0, 2048.0)
    assert (third.net_rx_rate, third.net_tx_rate) == (0.0, 150.0)
    assert third.cpu_percent == 5.0
    assert third.memory_limit == 1000
    assert len(session.points) == 2
    session.stop()
    qtbot.waitUntil(lambda: watcher.ended == [None], timeout=2000)
    assert session.wait()


def test_stats_session_tolerates_bad_timestamps(qtbot) -> None:
    engine = FakeEngine()
    session = StatsSession(engine, "abc")
    watcher = StatsWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(engine.stats_feeds) == 1, timeout=2000)
    feed = engine.stats_feeds[0]
    feed.put(sample(None, rx=1000, tx=0))
    feed.put(sample(None, rx=2000, tx=0))
    feed.put(sample(10, rx=5000, tx=0))
    feed.put(sample(5, rx=1000, tx=0))
    qtbot.waitUntil(lambda: len(watcher.points) == 4, timeout=2000)
    for point in watcher.points:
        assert point.net_rx_rate >= 0.0
        assert point.at is not None
    assert watcher.points[1].net_rx_rate == 1000.0
    session.stop()
    qtbot.waitUntil(lambda: watcher.ended == [None], timeout=2000)
    assert session.wait()


def test_stats_session_ignores_late_items(qtbot) -> None:
    engine = FakeEngine()
    session = StatsSession(engine, "abc", max_points=10)
    watcher = StatsWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(engine.stats_feeds) == 1, timeout=2000)
    feed = engine.stats_feeds[0]
    feed.put(sample(0, rx=1000, tx=100))
    qtbot.waitUntil(lambda: len(watcher.points) == 1, timeout=2000)
    assert len(session.points) == 1
    session.stop()
    qtbot.waitUntil(lambda: watcher.ended == [None], timeout=2000)
    initial_points = len(watcher.points)
    initial_session_points = len(session.points)
    initial_previous = session._previous
    session._on_items([sample(1, rx=2000, tx=200)])
    assert len(watcher.points) == initial_points
    assert len(session.points) == initial_session_points
    assert session._previous is initial_previous
    feed.end()
    assert session.wait()


def test_log_session_is_single_use(qtbot) -> None:
    engine = FakeEngine()
    session = LogSession(engine, "abc", tty=False)
    session.start()
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    feed = engine.log_feeds[0]
    feed.put(LogLine("stdout", "line 1"))
    session.stop()
    qtbot.waitUntil(lambda: feed.closed, timeout=2000)
    session.start()
    assert len(engine.log_feeds) == 1
    assert session.wait()


def test_stats_session_is_single_use(qtbot) -> None:
    engine = FakeEngine()
    session = StatsSession(engine, "abc")
    session.start()
    qtbot.waitUntil(lambda: len(engine.stats_feeds) == 1, timeout=2000)
    feed = engine.stats_feeds[0]
    feed.put(sample(0, rx=1000, tx=100))
    session.stop()
    qtbot.waitUntil(lambda: feed.closed, timeout=2000)
    session.start()
    assert len(engine.stats_feeds) == 1
    assert session.wait()


def test_session_dispose_allows_owner_deletion(qtbot) -> None:
    engine = FakeEngine()
    owner = QObject()
    session = LogSession(engine, "abc", tty=False, parent=owner)
    watcher = LogWatcher(session)
    session.start()
    qtbot.waitUntil(lambda: len(engine.log_feeds) == 1, timeout=2000)
    assert session.dispose() is True
    assert engine.log_feeds[0].closed
    owner.deleteLater()
    qtbot.wait(50)
    qtbot.waitUntil(lambda: watcher.ended == [None], timeout=2000)


def test_stats_session_dispose_closes_stream(qtbot) -> None:
    engine = FakeEngine()
    session = StatsSession(engine, "abc")
    session.start()
    qtbot.waitUntil(lambda: len(engine.stats_feeds) == 1, timeout=2000)
    assert session.dispose() is True
    assert engine.stats_feeds[0].closed
