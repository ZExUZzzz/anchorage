"""Per-container log and stats streams with bounded history."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QDeadlineTimer, QObject, Signal

from anchorage.core.workers import StreamWorker
from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.models import ContainerStats, LogLine

LOG_BATCH_INTERVAL = 0.05


class LogSession(QObject):
    """Follows one container's logs and keeps the last ``max_lines`` lines.

    One session per page visit; create a new one to restart. Callers must call
    ``dispose()`` before dropping the session, or keep it alive until ``ended`` fires.
    """

    lines_added = Signal(list)
    ended = Signal(object)

    def __init__(
        self,
        api: EngineAPI,
        container_id: str,
        *,
        tty: bool,
        tail: int | None = 1000,
        max_lines: int = 10_000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.container_id = container_id
        self._buffer: deque[LogLine] = deque(maxlen=max_lines)
        self._active = False
        self._stopped = False
        self._started = False
        self._worker = StreamWorker(
            lambda: api.logs(container_id, tty=tty, tail=tail, timestamps=True),
            batch_interval=LOG_BATCH_INTERVAL,
            parent=self,
        )
        self._worker.items.connect(self._on_items)
        self._worker.ended.connect(self._on_ended)

    @property
    def lines(self) -> list[LogLine]:
        return list(self._buffer)

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._started or self._stopped:
            return
        self._started = True
        self._active = True
        self._worker.start()

    def stop(self) -> None:
        self._stopped = True
        self._worker.close()

    def wait(self, timeout_ms: int = 2000) -> bool:
        return self._worker.wait(QDeadlineTimer(timeout_ms))

    def dispose(self, timeout_ms: int = 2000) -> bool:
        self._stopped = True
        return self._worker.dispose(timeout_ms)

    def _on_items(self, lines: list[LogLine]) -> None:
        if self._stopped:
            return
        self._buffer.extend(lines)
        self.lines_added.emit(lines)

    def _on_ended(self, error: object) -> None:
        self._active = False
        self.ended.emit(error if isinstance(error, DockerError) else None)


@dataclass(frozen=True, slots=True)
class StatsPoint:
    at: datetime
    cpu_percent: float
    memory_usage: int
    memory_limit: int
    net_rx_rate: float
    net_tx_rate: float
    block_read_rate: float
    block_write_rate: float
    pids: int


def _rate(current: int, previous: int, seconds: float) -> float:
    delta = current - previous
    if delta <= 0 or seconds <= 0:
        return 0.0
    return delta / seconds


class StatsSession(QObject):
    """Streams one container's stats and converts cumulative counters to rates.

    One session per page visit; create a new one to restart. Callers must call
    ``dispose()`` before dropping the session, or keep it alive until ``ended`` fires.
    """

    sample_added = Signal(object)
    ended = Signal(object)

    def __init__(
        self,
        api: EngineAPI,
        container_id: str,
        *,
        max_points: int = 120,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.container_id = container_id
        self._points: deque[StatsPoint] = deque(maxlen=max_points)
        self._previous: tuple[datetime, bool, ContainerStats] | None = None
        self._active = False
        self._stopped = False
        self._started = False
        self._worker = StreamWorker(lambda: api.stats(container_id), parent=self)
        self._worker.items.connect(self._on_items)
        self._worker.ended.connect(self._on_ended)

    @property
    def points(self) -> list[StatsPoint]:
        return list(self._points)

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._started or self._stopped:
            return
        self._started = True
        self._active = True
        self._worker.start()

    def stop(self) -> None:
        self._stopped = True
        self._worker.close()

    def wait(self, timeout_ms: int = 2000) -> bool:
        return self._worker.wait(QDeadlineTimer(timeout_ms))

    def dispose(self, timeout_ms: int = 2000) -> bool:
        self._stopped = True
        return self._worker.dispose(timeout_ms)

    def _on_items(self, samples: list[ContainerStats]) -> None:
        if self._stopped:
            return
        for sample in samples:
            point = self._to_point(sample)
            self._points.append(point)
            self.sample_added.emit(point)

    def _to_point(self, sample: ContainerStats) -> StatsPoint:
        synthesized = sample.read_at is None
        at = sample.read_at or datetime.now(UTC)
        if self._previous is None:
            rates = (0.0, 0.0, 0.0, 0.0)
        else:
            prev_at, prev_synthesized, prev = self._previous
            seconds = (at - prev_at).total_seconds()
            if synthesized or prev_synthesized or seconds <= 0:
                seconds = 1.0
            rates = (
                _rate(sample.network_rx, prev.network_rx, seconds),
                _rate(sample.network_tx, prev.network_tx, seconds),
                _rate(sample.block_read, prev.block_read, seconds),
                _rate(sample.block_write, prev.block_write, seconds),
            )
        self._previous = (at, synthesized, sample)
        return StatsPoint(
            at=at,
            cpu_percent=sample.cpu_percent,
            memory_usage=sample.memory_usage,
            memory_limit=sample.memory_limit,
            net_rx_rate=rates[0],
            net_tx_rate=rates[1],
            block_read_rate=rates[2],
            block_write_rate=rates[3],
            pids=sample.pids,
        )

    def _on_ended(self, error: object) -> None:
        self._active = False
        self.ended.emit(error if isinstance(error, DockerError) else None)
