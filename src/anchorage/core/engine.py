"""Connection state and the daemon event stream."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

from anchorage.core.workers import StreamWorker, TaskRunner
from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.models import Event, VersionInfo


class EngineState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class EngineService(QObject):
    """Owns the daemon connection: probes it, streams events, reconnects with backoff."""

    state_changed = Signal(object)
    version_changed = Signal(object)
    event_received = Signal(object)

    def __init__(
        self,
        api: EngineAPI,
        runner: TaskRunner,
        *,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._runner = runner
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._state = EngineState.DISCONNECTED
        self._error: DockerError | None = None
        self._version: VersionInfo | None = None
        self._attempts = 0
        self._generation = 0
        self._events: StreamWorker | None = None
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._connect)

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def error(self) -> DockerError | None:
        return self._error

    @property
    def version(self) -> VersionInfo | None:
        return self._version

    @property
    def socket_path(self) -> str:
        return self._api.socket_path

    def retry_delay(self, attempt: int) -> float:
        return float(min(self._base_delay * (2 ** min(attempt, 16)), self._max_delay))

    def start(self) -> None:
        self._retry.stop()
        self._connect()

    def stop(self) -> bool:
        self._generation += 1
        self._retry.stop()
        stopped = self._stop_events(wait=True)
        self._set_state(EngineState.DISCONNECTED)
        return stopped

    def reconnect_now(self) -> None:
        self._retry.stop()
        self._attempts = 0
        self._connect()

    def _connect(self) -> None:
        if self._state is EngineState.CONNECTING:
            return
        self._stop_events(wait=False)
        self._set_state(EngineState.CONNECTING)
        self._generation += 1
        generation = self._generation
        api = self._api

        def probe() -> VersionInfo:
            api.ping()
            return api.version()

        self._runner.submit(
            probe,
            lambda version: self._on_probed(generation, version),
            lambda error: self._on_probe_failed(generation, error),
        )

    def _on_probed(self, generation: int, version: VersionInfo) -> None:
        if generation != self._generation:
            return
        self._stop_events(wait=False)
        self._version = version
        self.version_changed.emit(version)
        self._attempts = 0
        worker = StreamWorker(self._api.events, parent=self)
        worker.items.connect(self._on_events)
        worker.ended.connect(self._on_events_ended)
        worker.finished.connect(worker.deleteLater)
        self._events = worker
        worker.start()
        self._set_state(EngineState.CONNECTED)

    def _on_probe_failed(self, generation: int, error: DockerError) -> None:
        if generation != self._generation:
            return
        self._set_state(EngineState.ERROR, error)
        self._schedule_retry()

    def _on_events(self, items: list[Event]) -> None:
        if self.sender() is not self._events:
            return
        for item in items:
            self.event_received.emit(item)

    def _on_events_ended(self, error: object) -> None:
        worker = self.sender()
        if worker is not self._events:
            return
        self._events = None
        self._set_state(EngineState.DISCONNECTED, error if isinstance(error, DockerError) else None)
        self._schedule_retry()

    def _schedule_retry(self) -> None:
        delay = self.retry_delay(self._attempts)
        self._attempts += 1
        self._retry.start(int(delay * 1000))

    def _stop_events(self, *, wait: bool) -> bool:
        worker = self._events
        if worker is None:
            return True
        self._events = None
        if wait:
            return worker.dispose()
        worker.close()
        return True

    def _set_state(self, state: EngineState, error: DockerError | None = None) -> None:
        if state is self._state and error is self._error:
            return
        self._state = state
        self._error = error
        self.state_changed.emit(state)
