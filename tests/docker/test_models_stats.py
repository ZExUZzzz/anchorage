import pytest

from anchorage.docker.errors import ServerError
from anchorage.docker.models import ContainerStats, LogLine, PullProgress

SAMPLE = {
    "read": "2026-10-02T20:00:01.000000000Z",
    "cpu_stats": {
        "cpu_usage": {"total_usage": 2_000_000_000},
        "system_cpu_usage": 100_000_000_000,
        "online_cpus": 4,
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 1_000_000_000},
        "system_cpu_usage": 60_000_000_000,
        "online_cpus": 4,
    },
    "memory_stats": {
        "usage": 60_000_000,
        "limit": 16_000_000_000,
        "stats": {"inactive_file": 10_000_000},
    },
    "networks": {
        "eth0": {"rx_bytes": 1000, "tx_bytes": 200},
        "eth1": {"rx_bytes": 1, "tx_bytes": 2},
    },
    "blkio_stats": {
        "io_service_bytes_recursive": [
            {"major": 8, "minor": 0, "op": "read", "value": 4096},
            {"major": 8, "minor": 0, "op": "write", "value": 8192},
            {"major": 8, "minor": 0, "op": "Read", "value": 1},
        ]
    },
    "pids_stats": {"current": 7},
}


def test_stats_sample() -> None:
    s = ContainerStats.from_api(SAMPLE)
    assert s.read_at is not None
    assert s.cpu_percent == pytest.approx(10.0)
    assert s.memory_usage == 50_000_000
    assert s.memory_limit == 16_000_000_000
    assert s.network_rx == 1001
    assert s.network_tx == 202
    assert s.block_read == 4097
    assert s.block_write == 8192
    assert s.pids == 7


def test_stats_cgroup_v1_cache_and_missing_precpu() -> None:
    data = dict(SAMPLE)
    data["precpu_stats"] = {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0}
    data["memory_stats"] = {"usage": 60_000_000, "limit": 1, "stats": {"cache": 5_000_000}}
    data["networks"] = None
    data["blkio_stats"] = {"io_service_bytes_recursive": None}
    data["pids_stats"] = {}
    s = ContainerStats.from_api(data)
    assert s.cpu_percent == 0.0
    assert s.memory_usage == 55_000_000
    assert s.network_rx == 0
    assert s.block_write == 0
    assert s.pids == 0


def test_stats_cpu_without_online_cpus_uses_percpu_length() -> None:
    data = dict(SAMPLE)
    data["cpu_stats"] = {
        "cpu_usage": {"total_usage": 2_000_000_000, "percpu_usage": [1, 1]},
        "system_cpu_usage": 100_000_000_000,
    }
    assert ContainerStats.from_api(data).cpu_percent == pytest.approx(5.0)


def test_log_line_defaults() -> None:
    line = LogLine(stream="stdout", text="hello")
    assert line.timestamp is None


def test_pull_progress() -> None:
    p = PullProgress.from_api(
        {
            "status": "Downloading",
            "id": "77aa88bb99cc",
            "progressDetail": {"current": 10, "total": 31},
        }
    )
    assert p == PullProgress(status="Downloading", layer_id="77aa88bb99cc", current=10, total=31)
    assert PullProgress.from_api({"status": "Pulling from library/nginx"}).layer_id is None


def test_pull_progress_error_raises() -> None:
    with pytest.raises(ServerError, match="manifest unknown"):
        PullProgress.from_api(
            {
                "error": "manifest unknown",
                "errorDetail": {"message": "manifest unknown"},
            }
        )
