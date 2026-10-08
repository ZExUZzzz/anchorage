"""Four live charts for one container."""

from __future__ import annotations

from collections import deque

from PySide6.QtWidgets import QGridLayout, QWidget

from anchorage.core.sessions import StatsPoint
from anchorage.core.units import format_bytes, format_rate
from anchorage.ui.widgets.sparkline import Sparkline


class StatsPanel(QWidget):
    MAX_POINTS = 120

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: deque[StatsPoint] = deque(maxlen=self.MAX_POINTS)
        self._seen_first = False
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(10)
        self.cpu = Sparkline("CPU")
        self.memory = Sparkline("MEMORY")
        self.network = Sparkline("NETWORK  rx / tx")
        self.block = Sparkline("BLOCK I/O  read / write")
        grid.addWidget(self.cpu, 0, 0)
        grid.addWidget(self.memory, 0, 1)
        grid.addWidget(self.network, 1, 0)
        grid.addWidget(self.block, 1, 1)

    def add_point(self, point: StatsPoint) -> None:
        if not self._seen_first:
            # The daemon's first sample has no previous reading, so its rates are not real.
            self._seen_first = True
            return
        self._points.append(point)
        points = list(self._points)
        self.cpu.set_series([p.cpu_percent for p in points], f"{point.cpu_percent:.1f} %")
        self.memory.set_series(
            [float(p.memory_usage) for p in points],
            f"{format_bytes(point.memory_usage)} / {format_bytes(point.memory_limit)}",
            ceiling=float(point.memory_limit) if point.memory_limit > 0 else None,
        )
        self.network.set_series(
            [p.net_rx_rate + p.net_tx_rate for p in points],
            f"{format_rate(point.net_rx_rate)} / {format_rate(point.net_tx_rate)}",
        )
        self.block.set_series(
            [p.block_read_rate + p.block_write_rate for p in points],
            f"{format_rate(point.block_read_rate)} / {format_rate(point.block_write_rate)}",
        )

    def reset(self) -> None:
        self._points.clear()
        self._seen_first = False
        for chart in (self.cpu, self.memory, self.network, self.block):
            chart.set_series([], "")
