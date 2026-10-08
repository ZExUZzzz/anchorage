"""Small filled line chart drawn with QPainter."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Sparkline(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.series: list[float] = []
        self.ceiling: float | None = None
        self.floor = 0.0
        self.headroom = 1.0
        self.setMinimumHeight(110)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("section")
        head.addWidget(self.title_label)
        head.addStretch()
        self.value_label = QLabel("")
        self.value_label.setStyleSheet("font-weight: 600;")
        head.addWidget(self.value_label)
        layout.addLayout(head)
        layout.addStretch()

    def set_series(
        self,
        values: list[float],
        value_text: str,
        ceiling: float | None = None,
        *,
        floor: float = 0.0,
        headroom: float = 1.0,
    ) -> None:
        """Plot ``values``.

        A ``ceiling`` fixes the top of the scale. Otherwise the top is the peak times
        ``headroom``, but never below ``floor``, so idle noise does not fill the chart.
        """
        self.series = list(values)
        self.ceiling = ceiling if ceiling and ceiling > 0 else None
        self.floor = max(floor, 0.0)
        self.headroom = max(headroom, 1.0)
        self.value_label.setText(value_text)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        pal = self.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(pal.color(QPalette.ColorRole.Mid)))
        painter.setBrush(pal.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(rect, 6, 6)
        if len(self.series) < 2:
            painter.end()
            return
        area = QRectF(rect).adjusted(10, 30, -10, -8)
        peak = self.ceiling or max(max(self.series) * self.headroom, self.floor) or 1.0
        count = len(self.series)
        points = [
            QPointF(
                area.left() + area.width() * i / (count - 1),
                area.bottom() - area.height() * (v / peak),
            )
            for i, v in enumerate(self.series)
        ]
        fill_path = QPainterPath(QPointF(area.left(), area.bottom()))
        for pt in points:
            fill_path.lineTo(pt)
        fill_path.lineTo(area.right(), area.bottom())
        fill_path.closeSubpath()
        highlight = pal.color(QPalette.ColorRole.Highlight)
        fill = QColor(highlight)
        fill.setAlpha(60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(fill_path)
        line = QPainterPath(points[0])
        for pt in points[1:]:
            line.lineTo(pt)
        painter.setPen(QPen(highlight, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line)
        painter.end()
