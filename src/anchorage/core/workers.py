"""Thread helpers: one-shot tasks on a pool and long-lived stream readers."""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

from PySide6.QtCore import (
    QCoreApplication,
    QDeadlineTimer,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    Signal,
)

from anchorage.docker.client import Stream
from anchorage.docker.errors import DockerError

T = TypeVar("T")
log = logging.getLogger(__name__)


def wrap_error(exc: BaseException) -> DockerError:
    """Return DockerErrors unchanged; wrap anything else so callers see one error type.

    The traceback is cut loose: its frames hold the callbacks and workers, so an error
    kept anywhere they can reach would put QObjects in a reference cycle. Only the
    cyclic GC frees those, on whichever Python thread triggers it, and destroying a
    QObject off its own thread races the main thread's event loop.
    """
    if isinstance(exc, DockerError):
        error = exc
    else:
        log.error("unexpected error in worker", exc_info=exc)
        error = DockerError(f"{type(exc).__name__}: {exc}")
    traceback.clear_frames(exc.__traceback__)
    return error.with_traceback(None)


class _Task(QRunnable):
    def __init__(
        self,
        runner: TaskRunner,
        fn: Callable[[], Any],
        on_result: Callable[[Any], None],
        on_error: Callable[[DockerError], None],
    ) -> None:
        super().__init__()
        self._runner = runner
        self._fn = fn
        self._on_result = on_result
        self._on_error = on_error

    def run(self) -> None:
        try:
            value = self._fn()
        except Exception as exc:
            self._runner.deliver(self._on_error, wrap_error(exc))
            return
        self._runner.deliver(self._on_result, value)


class TaskRunner(QObject):
    """Runs callables on a thread pool and invokes callbacks in this object's thread.

    Delivery goes through a queued signal on the runner, so any callable works as a
    callback, including lambdas. ``inline=True`` runs everything synchronously for tests.
    """

    _delivered = Signal(object, object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        pool: QThreadPool | None = None,
        inline: bool = False,
    ) -> None:
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        self._inline = inline
        self._closed = False
        self._delivered.connect(self._invoke)

    def submit(
        self,
        fn: Callable[[], T],
        on_result: Callable[[T], None],
        on_error: Callable[[DockerError], None],
    ) -> None:
        if self._inline:
            try:
                value = fn()
            except Exception as exc:
                on_error(wrap_error(exc))
                return
            on_result(value)
            return
        self._pool.start(_Task(self, fn, on_result, on_error))

    def close(self) -> None:
        """Drop callbacks of tasks that finish after this call."""
        self._closed = True

    def deliver(self, callback: Callable[[Any], None], value: Any) -> None:
        if not self._closed:
            self._delivered.emit(callback, value)

    def _invoke(self, callback: Callable[[Any], None], value: Any) -> None:
        if not self._closed:
            callback(value)


class StreamWorker(QThread):
    """Reads one ``Stream`` on its own thread.

    ``items`` carries a list of items (one, or a batch when ``batch_interval`` is set).
    ``ended`` fires exactly once with ``None`` or the ``DockerError`` that stopped the read.
    ``close()`` may be called from any thread at any time, before or after the stream opens.
    """

    items = Signal(list)
    ended = Signal(object)

    def __init__(
        self,
        open_stream: Callable[[], Stream[Any]],
        *,
        batch_interval: float = 0.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._open = open_stream
        self._interval = batch_interval
        self._lock = threading.Lock()
        self._stream: Stream[Any] | None = None
        self._closed = False
        self._batch: list[Any] = []
        self._flush_timer: threading.Timer | None = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            stream = self._stream
        if stream is not None:
            stream.close()

    def stop(self, timeout_ms: int = 2000) -> bool:
        self.close()
        return self.wait(QDeadlineTimer(timeout_ms))

    def dispose(self, timeout_ms: int = 2000) -> bool:
        """Close and join; a worker that misses the deadline outlives its owner.

        It is reparented to the application and deleted once its thread returns, so
        destroying the former owner cannot destroy a running QThread.
        """
        if self.stop(timeout_ms):
            return True
        self.setParent(QCoreApplication.instance())
        self.finished.connect(self.deleteLater)
        return False

    def run(self) -> None:
        try:
            stream = self._open()
        except Exception as exc:
            self.ended.emit(None if self._closed else wrap_error(exc))
            return
        with self._lock:
            self._stream = stream
            closed = self._closed
        if closed:
            stream.close()
            self.ended.emit(None)
            return

        error: DockerError | None = None
        try:
            for item in stream:
                self._push(item)
        except Exception as exc:
            if not self._closed:
                error = wrap_error(exc)
        finally:
            stream.close()
        self._finish_batching()
        self.ended.emit(error)

    def _push(self, item: Any) -> None:
        with self._lock:
            self._batch.append(item)
            if self._interval > 0:
                if self._flush_timer is None:
                    self._flush_timer = threading.Timer(self._interval, self._flush)
                    self._flush_timer.daemon = True
                    self._flush_timer.start()
                return
        self._flush()

    def _flush(self) -> None:
        with self._lock:
            batch, self._batch = self._batch, []
            self._flush_timer = None
            closed = self._closed
        if batch and not closed:
            self.items.emit(batch)

    def _finish_batching(self) -> None:
        with self._lock:
            timer = self._flush_timer
        if timer is not None:
            timer.cancel()
            timer.join()
        self._flush()
