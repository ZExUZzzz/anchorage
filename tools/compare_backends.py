"""Compare the native and docker-py Docker backends and write a Markdown report.

Usage: uv run python tools/compare_backends.py [--out docs/backend-comparison.md] [--iterations 200]
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.metadata
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from anchorage.docker.transport import discover_socket_path  # noqa: E402

BACKENDS = ("native", "dockerpy")
LABELS = {"native": "native", "dockerpy": "docker-py"}
DOCKER_SOCKET = discover_socket_path()
CAP = 10.0
UNREACHABLE = "n/a (daemon unreachable)"
DEP_PACKAGES = ("docker", "requests", "urllib3", "charset_normalizer", "idna", "certifi")


FINDINGS = [
    "- docker-py's default request timeout also applies to streamed reads unless disabled; the "
    "backend passes `timeout=None` for logs and stats.",
    "- docker-py drops `force` in `APIClient.remove_volume`; the backend calls the private "
    "`_delete` instead.",
    "- docker-py leaks a socket when a connect fails.",
    "- docker-py's public `logs(stream=True)` loses the stdout/stderr frame type; the backend "
    "uses the private `_get` and demultiplexes itself.",
    "- `events()` sends its request in the caller's thread, so it can block there.",
    "- A read blocked before the response headers arrive (the `events()` request itself) cannot be "
    "interrupted; body reads return because the backend shuts the socket down before closing "
    "the response.",
    "- `decode=True` streams (events, pull) end silently on a truncated chunked body; logs and "
    "stats, which read the raw response, raise `ProtocolError` (see the fake-daemon row above).",
    "- The daemon answers the first stats sample in about 1 ms from a warm collector and in "
    "about 1 s from a cold one (manual probe, both backends alike); the table measures the "
    "warm case.",
]


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build(backend: str, socket_path: str) -> Any:
    from tests.docker.conftest import build_client

    return build_client(backend, socket_path)


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def ms(value_ns: float) -> str:
    return f"{value_ns / 1e6:.2f}"


def percentile95(samples: list[int]) -> int:
    ordered = sorted(samples)
    return ordered[max(int(0.95 * len(ordered)) - 1, 0)]


# --- code, dependencies, import time ---------------------------------------------------------


def count_lines(*names: str) -> int:
    total = 0
    for name in names:
        with (ROOT / "src/anchorage/docker" / name).open(encoding="utf-8") as handle:
            total += len([line for line in handle if line.strip()])
    return total


def dependency_mib() -> float:
    total = 0
    for name in DEP_PACKAGES:
        dist = importlib.metadata.distribution(name)
        for file in dist.files or []:
            path = Path(str(dist.locate_file(file)))
            if path.is_file():
                total += path.stat().st_size
    return total / (1024 * 1024)


def import_time_ms(module: str) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    samples = []
    for _ in range(5):
        result = subprocess.run(
            [sys.executable, "-X", "importtime", "-c", f"import {module}"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        cumulative = [int(m.group(1)) for m in re.finditer(r"\|\s*(\d+) \|", result.stderr)]
        if cumulative:
            samples.append(cumulative[-1])
    return f"{statistics.median(samples) / 1000:.0f}" if samples else "n/a (parse failed)"


def code_section() -> str:
    native = count_lines("transport.py")
    dockerpy = count_lines("dockerpy.py")
    shared = count_lines("client.py", "models.py", "streams.py", "errors.py", "_time.py")
    log("measuring dependency size and import time")
    mib = f"{dependency_mib():.1f}"
    rows = [
        [
            "native",
            f"{native} (transport.py)",
            "0",
            import_time_ms("anchorage.docker.client"),
        ],
        [
            "docker-py",
            f"{dockerpy} (dockerpy.py)",
            mib,
            import_time_ms("anchorage.docker.dockerpy"),
        ],
        ["shared", f"{shared} (client.py, models.py, streams.py, errors.py, _time.py)", "-", "-"],
    ]
    note = (
        "Import time is the median of 5 runs of `-X importtime` (cumulative, last line). "
        "`client.py` holds the shared `Stream` and `EngineAPI` plus the native `DockerClient`, so "
        "it is counted in the shared row; dependency size is the sum of installed files of "
        f"{', '.join(DEP_PACKAGES)}."
    )
    return table(["Backend", "Lines (non-blank)", "Dependencies, MiB", "Import time, ms"], rows) + (
        "\n\n" + note
    )


# --- live daemon ---------------------------------------------------------------------------


def daemon_alive() -> bool:
    try:
        client = build("native", DOCKER_SOCKET)
        client.ping()
    except Exception:
        return False
    return True


def timed(func: Callable[[], Any], count: int) -> tuple[str, str]:
    for _ in range(5):
        func()
    samples = []
    for _ in range(count):
        start = time.perf_counter_ns()
        func()
        samples.append(time.perf_counter_ns() - start)
    return ms(statistics.median(samples)), ms(percentile95(samples))


def latency_section(iterations: int) -> str:
    if not daemon_alive():
        return UNREACHABLE
    clients = {b: build(b, DOCKER_SOCKET) for b in BACKENDS}
    containers = clients["native"].list_containers(all=True)
    first = containers[0].id if containers else None
    half = max(iterations // 2, 1)
    operations: list[tuple[str, Callable[[Any], Any] | None, int]] = [
        (f"list_containers x{iterations}", lambda c: c.list_containers(all=True), iterations),
        (
            f"inspect_container x{iterations}",
            (lambda c: c.inspect_container(first)) if first else None,
            iterations,
        ),
        (f"list_images x{half}", lambda c: c.list_images(), half),
        (f"version x{half}", lambda c: c.version(), half),
    ]
    rows = []
    for name, op, count in operations:
        log(f"latency: {name}")
        row = [name]
        for backend in BACKENDS:
            if op is None:
                row += ["n/a (no containers)"] * 2
                continue
            client = clients[backend]
            median, p95 = timed(lambda op=op, client=client: op(client), count)
            row += [median, p95]
        rows.append(row)
    for client in clients.values():
        close = getattr(client, "close", None)
        if close:
            close()
    return table(
        [
            "Operation",
            "native median, ms",
            "native p95, ms",
            "docker-py median, ms",
            "docker-py p95, ms",
        ],
        rows,
    )


def drain(stream: Any, state: dict[str, Any], accept: Callable[[Any], bool] | None = None) -> None:
    try:
        for item in stream:
            state["count"] += 1
            state["last"] = time.perf_counter()
            if "first" not in state and (accept is None or accept(item)):
                state["first"] = state["last"]
    except Exception as exc:
        state["error"] = type(exc).__name__
    finally:
        state["done"] = True


def first_item_ms(
    open_stream: Callable[[], Any],
    trigger: Callable[[], None] | None = None,
    accept: Callable[[Any], bool] | None = None,
) -> str:
    """Time from the start of the call (or from the trigger) to the first accepted item."""
    state: dict[str, Any] = {"count": 0, "done": False}
    start = time.perf_counter()
    result: dict[str, Any] = {}

    def run() -> None:
        # the request is sent here: docker-py's events() blocks in the caller's thread
        try:
            result["stream"] = open_stream()
        except Exception as exc:
            state["error"] = type(exc).__name__
            state["done"] = True
            return
        drain(result["stream"], state, accept)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if trigger:
        time.sleep(1.0)
        start = time.perf_counter()
        trigger()
    deadline = start + CAP
    while "first" not in state and not state["done"] and time.perf_counter() < deadline:
        time.sleep(0.001)
    if "stream" in result:
        result["stream"].close()
    thread.join(timeout=CAP)
    if "first" not in state:
        return "n/a (no item)"
    return f"{(state['first'] - start) * 1000:.1f}"


def stats_first_ms(client: Any, container_id: str) -> str:
    """Median of 5 runs: the daemon sometimes answers the very first request from a cache."""
    values = []
    for _ in range(5):
        value = first_item_ms(lambda: client.stats(container_id))
        if not value.startswith("n/a"):
            values.append(float(value))
        time.sleep(1.5)
    return f"{statistics.median(values):.1f}" if values else "n/a (no item)"


def tail_ms(client: Any, container_id: str, tty: bool) -> str:
    state: dict[str, Any] = {"count": 0, "done": False}
    start = time.perf_counter()
    stream = client.logs(container_id, tty=tty, tail=1000, timestamps=True)
    thread = threading.Thread(target=drain, args=(stream, state), daemon=True)
    thread.start()
    while time.perf_counter() < start + CAP and not state["done"]:
        if state["count"] >= 1000 or (
            state.get("last") and time.perf_counter() - state["last"] > 1.0
        ):
            break
        time.sleep(0.002)
    stream.close()
    thread.join(timeout=CAP)
    if not state["count"]:
        return "n/a (no lines)"
    return f"{(state['last'] - start) * 1000:.1f} ({state['count']} lines)"


def throwaway_container() -> str | None:
    """Create ``busybox sleep 300``; return its id or None (pull failure) with the reason logged."""
    have = subprocess.run(
        ["docker", "image", "inspect", "busybox"], capture_output=True, check=False
    )
    if have.returncode != 0:
        try:
            pulled = subprocess.run(
                ["docker", "pull", "busybox"], capture_output=True, timeout=60, check=False
            )
        except subprocess.TimeoutExpired:
            return None
        if pulled.returncode != 0:
            return None
    run = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            f"anchorage-compare-{os.getpid()}",
            "busybox",
            "sleep",
            "300",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return run.stdout.strip() if run.returncode == 0 else None


def streaming_section() -> str:
    if not daemon_alive():
        return UNREACHABLE
    clients = {b: build(b, DOCKER_SOCKET) for b in BACKENDS}
    native = clients["native"]
    running = [c for c in native.list_containers(all=False) if c.state == "running"]
    rows: list[list[str]] = []

    log("streaming: first stats sample")
    if running:
        cid = running[0].id
        rows.append(
            [
                "first stats sample, warm collector, median of 5, ms",
                *(stats_first_ms(clients[b], cid) for b in BACKENDS),
            ]
        )
    else:
        rows.append(["first stats sample, ms"] + ["n/a (no running container)"] * 2)

    log("streaming: tail logs")
    if running:
        best, best_lines = running[0], -1
        for container in running:
            state: dict[str, Any] = {"count": 0, "done": False}
            tty = native.inspect_container(container.id).tty
            stream = native.logs(container.id, tty=tty, tail=1000)
            thread = threading.Thread(target=drain, args=(stream, state), daemon=True)
            thread.start()
            time.sleep(1.0)
            stream.close()
            thread.join(timeout=CAP)
            if state["count"] > best_lines:
                best, best_lines = container, state["count"]
        tty = native.inspect_container(best.id).tty
        label = "tail=1000 logs of the busiest running container, ms"
        log(f"busiest container: {best.name}")
        rows.append([label] + [tail_ms(clients[b], best.id, tty) for b in BACKENDS])
    else:
        rows.append(["tail=1000 logs, ms"] + ["n/a (no running container)"] * 2)

    log("streaming: first event after pause/unpause")
    cid = None
    try:
        cid = throwaway_container()
        if cid is None:
            rows.append(
                ["first event after docker pause (includes CLI spawn), ms"]
                + ["n/a (busybox absent and pull failed)"] * 2
            )
        else:
            cells = []
            for backend in BACKENDS:
                client = clients[backend]
                cells.append(
                    first_item_ms(
                        client.events,
                        lambda: subprocess.run(
                            ["docker", "pause", cid], capture_output=True, check=False
                        ),
                        lambda event: event.action == "pause" and event.actor_id == cid,
                    )
                )
                subprocess.run(["docker", "unpause", cid], capture_output=True, check=False)
                time.sleep(1.0)
            rows.append(["first event after docker pause (includes CLI spawn), ms", *cells])
    finally:
        if cid:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)
        for client in clients.values():
            close = getattr(client, "close", None)
            if close:
                close()
    return table(["Measurement", "native", "docker-py"], rows)


def join_time(thread: threading.Thread, start: float) -> str:
    thread.join(timeout=CAP)
    if thread.is_alive():
        return f">{CAP:.0f} s"
    return f"{(time.perf_counter() - start) * 1000:.0f} ms"


def cancellation_section() -> str:
    from tests.docker.fake_daemon import FakeDaemon, wait_for_socket

    rows: list[list[str]] = []

    log("cancel: close() while blocked in a body read")
    label = "live: reader return after close() while blocked in a body read"
    if daemon_alive():
        cells = []
        for backend in BACKENDS:
            client = build(backend, DOCKER_SOCKET)
            state: dict[str, Any] = {"count": 0}
            stream = client.events()
            thread = threading.Thread(target=drain, args=(stream, state), daemon=True)
            thread.start()
            time.sleep(1.0)
            if not thread.is_alive():
                cells.append(f"n/a (reader ended early: {state.get('error', 'no exception')})")
            else:
                start = time.perf_counter()
                stream.close()
                cell = join_time(thread, start)
                if "error" in state:
                    cell += f" ({state['error']})"
                cells.append(cell)
            close = getattr(client, "close", None)
            if close:
                close()
        rows.append([label, *cells])
    else:
        rows.append([label, *[UNREACHABLE] * 2])

    log("cancel: daemon loss on the fake daemon")
    event = b'{"Type":"container","Action":"start","Actor":{"ID":"abc","Attributes":{}},"time":1}\n'
    cells = []
    for backend in BACKENDS:
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeDaemon(str(Path(tmp) / "docker.sock"))
            hold = threading.Event()
            fake.add_stream("GET", "/events", [event], hold=hold, abort=True)
            fake.start()
            wait_for_socket(fake.socket_path)
            client = build(backend, fake.socket_path)
            state: dict[str, Any] = {"count": 0}
            try:
                stream = client.events()
                thread = threading.Thread(target=drain, args=(stream, state), daemon=True)
                thread.start()
                time.sleep(1.0)
                start = time.perf_counter()
                fake.stop()
                hold.set()
                result = join_time(thread, start)
                outcome = state.get("error", "ended quietly" if state.get("done") else "blocked")
                cells.append(f"{result} ({outcome})")
                with contextlib.suppress(Exception):
                    stream.close()
            finally:
                hold.set()
                close = getattr(client, "close", None)
                if close:
                    close()
    rows.append(["fake daemon aborts the connection mid-stream: reader return", *cells])
    notes = (
        "`FakeDaemon.stop()` does not drop open connections, so the daemon loss is simulated: "
        "the route aborts the socket once `stop()` has returned.\n\n"
        "A read blocked before the response headers arrive (the `events()` request itself) "
        "cannot be interrupted by `close()`; a read blocked in the response body returns because "
        "the backend shuts the socket down before closing the response."
    )
    return table(["Measurement", "native", "docker-py"], rows) + "\n\n" + notes


# --- application footprint -----------------------------------------------------------------


def proc_stats(pid: int) -> tuple[float, float]:
    rss = 0.0
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            rss = int(line.split()[1]) / 1024
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rindex(")") + 2 :].split()
    ticks = os.sysconf("SC_CLK_TCK")
    return rss, (int(fields[11]) + int(fields[12])) / ticks


def footprint_section() -> str:
    if not daemon_alive():
        return UNREACHABLE
    rows = []
    for backend in BACKENDS:
        log(f"footprint: anchorage --backend {backend} for 20 s")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "src"))
        proc = subprocess.Popen(
            [sys.executable, "-m", "anchorage", "--backend", backend],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(20)
            if proc.poll() is not None:
                rows.append([LABELS[backend], f"n/a (exited with {proc.returncode})", "n/a"])
                continue
            rss, cpu = proc_stats(proc.pid)
            rows.append([LABELS[backend], f"{rss:.1f}", f"{cpu:.2f}"])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    return table(["Backend", "RSS after 20 s, MiB", "CPU time, s"], rows)


# --- report --------------------------------------------------------------------------------


def environment() -> str:
    cpu = platform.processor()
    with contextlib.suppress(OSError):
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    import PySide6

    return (
        f"CPU: {cpu}; kernel: {platform.release()}; Python: {platform.python_version()}; "
        f"PySide6: {PySide6.__version__}; docker-py: {importlib.metadata.version('docker')}"
    )


def method_section(iterations: int) -> str:
    half = max(iterations // 2, 1)
    daemon = "daemon unreachable"
    if daemon_alive():
        client = build("native", DOCKER_SOCKET)
        version = client.version()
        daemon = (
            f"Docker Engine {version.version}, API {version.api_version}; "
            f"{len(client.list_containers(all=True))} containers and {len(client.list_images())} "
            "images on the daemon"
        )
    return "\n".join(
        [
            f"- Run date (UTC): {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M}",
            f"- {daemon}",
            "- Single run, backends measured sequentially (native first).",
            f"- Samples per row: {iterations}/{iterations}/{half}/{half} for the latency rows, 5 "
            "for the stats and import rows, 1 for the pause event and the live cancellation rows.",
            "- The native client opens a UNIX connection per request while docker-py reuses pooled "
            "keep-alive connections, which explains most of the latency difference.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "docs/backend-comparison.md"))
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()

    sections = [
        ("Code and dependencies", code_section),
        ("Call latency", lambda: latency_section(args.iterations)),
        ("Streaming", streaming_section),
        ("Cancellation and daemon loss", cancellation_section),
        ("Application footprint", footprint_section),
    ]
    parts = ["# Backend comparison", "", environment(), ""]
    parts += ["## Method", "", method_section(args.iterations), ""]
    for title, build_section in sections:
        try:
            body = build_section()
        except Exception as exc:
            body = f"n/a ({type(exc).__name__}: {exc})"
        parts += [f"## {title}", "", body, ""]
    parts += [
        "## Findings from implementation (static notes, not measured by this script)",
        "",
        *FINDINGS,
        "",
    ]
    parts += ["## Conclusions", "", "_To be written by the lead._", ""]
    Path(args.out).write_text("\n".join(parts), encoding="utf-8")
    log(f"wrote {args.out}")


if __name__ == "__main__":
    main()
