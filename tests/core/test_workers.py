import threading

from PySide6.QtCore import QCoreApplication, QObject, QThread

from anchorage.core.workers import StreamWorker, TaskRunner, wrap_error
from anchorage.docker.errors import DockerError, NotFound
from tests.core.fakes import Feed


class Recorder(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[object]] = []
        self.ended: list[object] = []
        self.threads: list[QThread] = []

    def on_items(self, items: list[object]) -> None:
        self.batches.append(items)
        self.threads.append(QThread.currentThread())

    def on_ended(self, error: object) -> None:
        self.ended.append(error)
        self.threads.append(QThread.currentThread())

    @property
    def items(self) -> list[object]:
        return [item for batch in self.batches for item in batch]


def main_thread() -> QThread:
    app = QCoreApplication.instance()
    assert app is not None
    return app.thread()


def test_submit_delivers_result(qtbot) -> None:
    runner = TaskRunner()
    results: list[int] = []
    runner.submit(lambda: 41 + 1, results.append, lambda e: results.append(-1))
    qtbot.waitUntil(lambda: results == [42], timeout=2000)


def test_callbacks_run_in_runner_thread(qtbot) -> None:
    runner = TaskRunner()
    seen: list[tuple[QThread, QThread]] = []

    def work() -> QThread:
        return QThread.currentThread()

    runner.submit(
        work, lambda worker: seen.append((worker, QThread.currentThread())), lambda e: None
    )
    qtbot.waitUntil(lambda: len(seen) == 1, timeout=2000)
    worker_thread, callback_thread = seen[0]
    assert worker_thread is not main_thread()
    assert callback_thread is main_thread()


def test_docker_error_goes_to_on_error(qtbot) -> None:
    runner = TaskRunner()
    errors: list[DockerError] = []

    def boom() -> None:
        raise NotFound("nope", 404)

    runner.submit(boom, lambda _: errors.append(DockerError("wrong")), errors.append)
    qtbot.waitUntil(lambda: len(errors) == 1, timeout=2000)
    assert isinstance(errors[0], NotFound)


def test_unexpected_exception_is_wrapped(qtbot) -> None:
    runner = TaskRunner()
    errors: list[DockerError] = []

    def boom() -> None:
        raise ValueError("bad json")

    runner.submit(boom, lambda _: None, errors.append)
    qtbot.waitUntil(lambda: len(errors) == 1, timeout=2000)
    assert type(errors[0]) is DockerError
    assert "ValueError: bad json" in errors[0].message


def test_inline_runner_is_synchronous() -> None:
    runner = TaskRunner(inline=True)
    results: list[int] = []
    errors: list[DockerError] = []
    runner.submit(lambda: 1, results.append, errors.append)
    assert results == [1]

    def boom() -> int:
        raise NotFound("x", 404)

    runner.submit(boom, results.append, errors.append)
    assert isinstance(errors[0], NotFound)


def test_closed_runner_drops_callbacks(qtbot) -> None:
    runner = TaskRunner()
    gate = threading.Event()
    results: list[int] = []

    def work() -> int:
        gate.wait(2)
        return 1

    runner.submit(work, results.append, lambda e: results.append(-1))
    runner.close()
    gate.set()
    qtbot.wait(200)
    assert results == []


def test_wrap_error_passes_docker_errors_through() -> None:
    err = NotFound("x", 404)
    assert wrap_error(err) is err
    wrapped = wrap_error(KeyError("Id"))
    assert isinstance(wrapped, DockerError)
    assert "KeyError" in wrapped.message


def test_stream_worker_emits_items_and_ends(qtbot) -> None:
    feed: Feed[str] = Feed()
    recorder = Recorder()
    worker = StreamWorker(feed.stream)
    worker.items.connect(recorder.on_items)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    feed.put("a")
    feed.put("b")
    qtbot.waitUntil(lambda: recorder.items == ["a", "b"], timeout=2000)
    feed.end()
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
    assert worker.wait(2000)
    assert all(thread is main_thread() for thread in recorder.threads)


def test_stream_worker_close_ends_blocked_stream(qtbot) -> None:
    feed: Feed[str] = Feed()
    recorder = Recorder()
    worker = StreamWorker(feed.stream)
    worker.items.connect(recorder.on_items)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    feed.put("a")
    qtbot.waitUntil(lambda: recorder.items == ["a"], timeout=2000)
    assert worker.stop(2000)
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
    assert feed.closed


def test_stream_worker_close_before_open(qtbot) -> None:
    opened = threading.Event()
    release = threading.Event()
    feed: Feed[str] = Feed()

    def slow_open():  # type: ignore[no-untyped-def]
        opened.set()
        release.wait(2)
        return feed.stream()

    recorder = Recorder()
    worker = StreamWorker(slow_open)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    assert opened.wait(2)
    worker.close()
    release.set()
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
    assert worker.wait(2000)
    assert feed.closed


def test_stream_worker_reports_open_failure(qtbot) -> None:
    def failing_open():  # type: ignore[no-untyped-def]
        raise NotFound("no such container", 404)

    recorder = Recorder()
    worker = StreamWorker(failing_open)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    qtbot.waitUntil(lambda: len(recorder.ended) == 1, timeout=2000)
    assert isinstance(recorder.ended[0], NotFound)
    assert worker.wait(2000)


def test_stream_worker_reports_mid_stream_error(qtbot) -> None:
    feed: Feed[str] = Feed()
    recorder = Recorder()
    worker = StreamWorker(feed.stream)
    worker.items.connect(recorder.on_items)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    feed.put("a")
    feed.fail(ValueError("corrupt"))
    qtbot.waitUntil(lambda: len(recorder.ended) == 1, timeout=2000)
    assert isinstance(recorder.ended[0], DockerError)
    assert recorder.items == ["a"]
    assert worker.wait(2000)


def test_stream_worker_batches_items(qtbot) -> None:
    feed: Feed[int] = Feed()
    recorder = Recorder()
    worker = StreamWorker(feed.stream, batch_interval=0.2)
    worker.items.connect(recorder.on_items)
    worker.ended.connect(recorder.on_ended)
    for i in range(5):
        feed.put(i)
    feed.end()
    worker.start()
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
    assert recorder.items == [0, 1, 2, 3, 4]
    assert len(recorder.batches) <= 2
    assert worker.wait(2000)


def test_stream_worker_flushes_batch_on_timer(qtbot) -> None:
    feed: Feed[int] = Feed()
    recorder = Recorder()
    worker = StreamWorker(feed.stream, batch_interval=0.2)
    worker.items.connect(recorder.on_items)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    feed.put(1)
    qtbot.waitUntil(lambda: recorder.items == [1], timeout=1000)
    feed.end()
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
    assert worker.wait(2000)


def test_stream_worker_emits_nothing_after_close(qtbot) -> None:
    feed: Feed[int] = Feed()
    recorder = Recorder()
    worker = StreamWorker(feed.stream)
    worker.items.connect(recorder.on_items)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    feed.put(1)
    feed.put(2)
    qtbot.waitUntil(lambda: recorder.items == [1, 2], timeout=2000)
    worker.close()
    feed.put(3)
    feed.put(4)
    feed.end()
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
    assert recorder.items == [1, 2]
    assert worker.wait(2000)


def test_stream_worker_close_wins_over_open_failure(qtbot) -> None:
    opened = threading.Event()
    release = threading.Event()

    def slow_failing_open():  # type: ignore[no-untyped-def]
        opened.set()
        release.wait(2)
        raise NotFound("gone", 404)

    recorder = Recorder()
    worker = StreamWorker(slow_failing_open)
    worker.ended.connect(recorder.on_ended)
    worker.start()
    assert opened.wait(2)
    worker.close()
    release.set()
    qtbot.waitUntil(lambda: len(recorder.ended) == 1, timeout=2000)
    assert recorder.ended == [None]
    assert worker.wait(2000)


class FinishCounter(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def on_finished(self) -> None:
        self.count += 1


def test_dispose_of_stuck_worker_survives_owner_deletion(qtbot) -> None:
    release = threading.Event()
    feed: Feed[int] = Feed()

    def open_stream():  # type: ignore[no-untyped-def]
        release.wait()
        return feed.stream()

    parent = QObject()
    worker = StreamWorker(open_stream, parent=parent)
    counter = FinishCounter()
    worker.finished.connect(counter.on_finished)
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=2000)
    assert worker.dispose(50) is False
    assert worker.parent() is QCoreApplication.instance()
    parent.deleteLater()
    qtbot.wait(50)
    release.set()
    qtbot.waitUntil(lambda: counter.count == 1, timeout=2000)
    qtbot.wait(50)


def test_dispose_returns_true_for_stopped_worker(qtbot) -> None:
    feed: Feed[int] = Feed()
    worker = StreamWorker(feed.stream)
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=2000)
    assert worker.dispose() is True
    assert feed.closed


def test_dispose_returns_true_when_close_unblocks_pending_first_item(qtbot) -> None:
    # Models a stream whose response headers have not arrived: open returns at once and
    # the first __next__ blocks until close() shuts the connection down.
    feed: Feed[int] = Feed()
    worker = StreamWorker(feed.stream)
    recorder = Recorder()
    worker.ended.connect(recorder.on_ended)
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=2000)
    qtbot.wait(100)
    assert worker.dispose(200) is True
    assert feed.closed
    qtbot.waitUntil(lambda: recorder.ended == [None], timeout=2000)
