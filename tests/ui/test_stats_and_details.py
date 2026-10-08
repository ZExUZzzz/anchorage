from datetime import UTC, datetime

from anchorage.core.sessions import StatsPoint
from anchorage.core.units import format_bytes
from anchorage.docker.models import (
    ContainerDetails,
    ContainerState,
    Mount,
    NetworkAttachment,
    PortBinding,
)
from anchorage.ui.containers.details_tree import DetailsTree
from anchorage.ui.containers.stats_panel import StatsPanel
from anchorage.ui.widgets.sparkline import Sparkline


def point(cpu: float, mem: int, rx: float, write: float) -> StatsPoint:
    return StatsPoint(
        at=datetime(2026, 10, 3, tzinfo=UTC),
        cpu_percent=cpu,
        memory_usage=mem,
        memory_limit=16 * 1024**3,
        net_rx_rate=rx,
        net_tx_rate=0.0,
        block_read_rate=0.0,
        block_write_rate=write,
        pids=3,
    )


def test_sparkline_paints_series(qtbot) -> None:
    spark = Sparkline("CPU")
    qtbot.addWidget(spark)
    spark.resize(240, 100)
    spark.set_series([1.0, 5.0, 2.0], "5.0 %")
    assert spark.value_label.text() == "5.0 %"
    spark.grab()
    spark.set_series([], "")
    spark.grab()


def test_stats_panel_formats_values_and_bounds_history(qtbot) -> None:
    panel = StatsPanel()
    qtbot.addWidget(panel)
    for _ in range(StatsPanel.MAX_POINTS + 5):
        panel.add_point(point(7.1, 50 * 1024 * 1024, 1536.0, 0.0))
    assert panel.cpu.value_label.text() == "7.1 %"
    assert panel.memory.value_label.text() == "50.0 MB / 16.0 GB"
    assert panel.network.value_label.text() == "1.5 KB/s / 0 B/s"
    assert panel.block.value_label.text() == "0 B/s / 0 B/s"
    assert len(panel.cpu.series) == StatsPanel.MAX_POINTS
    panel.reset()
    assert panel.cpu.series == []
    assert panel.cpu.value_label.text() == ""


def test_only_the_first_sample_is_skipped(qtbot) -> None:
    panel = StatsPanel()
    qtbot.addWidget(panel)
    panel.add_point(point(0.0, 10 * 1024**2, 0.0, 0.0))
    assert panel.cpu.series == []
    assert panel.memory.series == []
    panel.add_point(point(0.0, 20 * 1024**2, 0.0, 0.0))
    panel.add_point(point(3.0, 20 * 1024**2, 0.0, 0.0))
    assert panel.cpu.series == [0.0, 3.0]
    panel.reset()
    panel.add_point(point(5.0, 20 * 1024**2, 0.0, 0.0))
    assert panel.cpu.series == []


def test_charts_scale_to_usage_with_floors(qtbot) -> None:
    panel = StatsPanel()
    qtbot.addWidget(panel)
    panel.add_point(point(1.0, 50 * 1024**2, 0.0, 0.0))
    panel.add_point(point(1.0, 50 * 1024**2, 0.0, 0.0))
    # Memory follows the container's usage, not the (host-wide) limit; the limit is in the label.
    assert panel.memory.ceiling is None
    assert panel.memory.headroom == 1.5
    assert panel.memory.value_label.text().endswith(format_bytes(16 * 1024**3))
    # Tiny CPU and network values must not fill the chart.
    assert panel.cpu.floor == 5.0
    assert panel.network.floor == panel.block.floor == 64 * 1024.0
    panel.memory.resize(240, 100)
    panel.memory.grab()
    spark = Sparkline("X")
    qtbot.addWidget(spark)
    spark.set_series([1.0, 2.0], "", ceiling=0.0)
    assert spark.ceiling is None


def test_details_tree_sections(qtbot) -> None:
    tree = DetailsTree()
    qtbot.addWidget(tree)
    details = ContainerDetails(
        id="3f1c9a7e2b44" + "0" * 52,
        name="pulse-nginx-1",
        image="nginx:alpine",
        image_id="sha256:7a2c1f",
        created=datetime(2026, 10, 2, 17, 14, 2, tzinfo=UTC),
        command=("/docker-entrypoint.sh", "nginx", "-g", "daemon off;"),
        state=ContainerState("running", True, False, False, 0, None, None, "healthy"),
        restart_policy="unless-stopped",
        tty=False,
        env=("NGINX_VERSION=1.27.2",),
        labels={"com.docker.compose.project": "pulse"},
        mounts=(Mount("bind", "/home/me/conf", "/etc/nginx/conf.d", "ro", False, None),),
        networks=(NetworkAttachment("pulse_default", "172.18.0.5", "172.18.0.1", 16, "02:42:ac"),),
        ports=(PortBinding(80, "tcp", 8080, "0.0.0.0"),),
    )
    tree.show_details(details)
    sections = {
        tree.topLevelItem(i).text(0): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
    }
    assert list(sections) == ["General", "Ports", "Environment", "Mounts", "Networks", "Labels"]
    gen = sections["General"]
    general = {gen.child(i).text(0): gen.child(i).text(1) for i in range(gen.childCount())}
    assert general["ID"] == "3f1c9a7e2b44"
    assert general["Command"] == "/docker-entrypoint.sh nginx -g 'daemon off;'"
    assert general["Health"] == "healthy"
    assert general["Restart policy"] == "unless-stopped"
    assert sections["Ports"].child(0).text(1) == "0.0.0.0:8080 → 80/tcp"
    assert sections["Mounts"].child(0).text(0) == "bind  /home/me/conf"
    assert sections["Mounts"].child(0).text(1) == "/etc/nginx/conf.d  (ro)"
    assert sections["Networks"].child(0).text(1).startswith("172.18.0.5/16")
    assert sections["Labels"].child(0).text(0) == "com.docker.compose.project"
    assert sections["Environment"].isExpanded() is False
    assert sections["General"].isExpanded() is True
    tree.clear()
    assert tree.topLevelItemCount() == 0
