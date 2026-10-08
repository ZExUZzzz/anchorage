import pytest

from anchorage.core.loglevel import detect_level


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("2026-10-03  4:54:53 0 [Warn] [Entrypoint]: /sys/fs/cgroup not writable", "warn"),
        ("2026-10-03  4:54:54 0 [Warning] mariadbd: io_uring_queue_init() failed", "warn"),
        ("2026-10-03  4:39:19 0 [Note] InnoDB: Starting shutdown...", None),
        ("2026-10-03  4:39:19 0 [ERROR] InnoDB: cannot open tablespace", "error"),
        ('time="2026/10/03 15:40:58" level=warning msg="listening without auth"', "warn"),
        ('time="2026/10/03 15:40:58" level=error msg="bind failed"', "error"),
        ('time="2026/10/03 15:40:58" level=info msg="starting"', None),
        ('{"level":"error","msg":"boom"}', "error"),
        ('{"level":"warn","ts":1}', "warn"),
        ("WARN[0000] no config file", "warn"),
        ("ERRO[0001] bad thing", "error"),
        ("ERROR:root:unhandled", "error"),
        ("WARNING:urllib3:retrying", "warn"),
        ("2026/10/03 12:00:00 [error] 7#7: *1 connect() failed", "error"),
        ("2026/10/03 12:00:00 [warn] 7#7: low on workers", "warn"),
        ("2026/10/03 12:00:00 [notice] 7#7: start worker", None),
        ("FATAL: database files are incompatible with server", "error"),
        ("PANIC: could not write to file", "error"),
        ("CRITICAL - disk full", "error"),
        ("Starting server, 0 errors found", None),
        ("GET /health 200 OK", None),
        ("", None),
        ("x" * 100 + " ERROR far away", None),
    ],
)
def test_detect_level(text: str, level: str | None) -> None:
    assert detect_level(text) == level
