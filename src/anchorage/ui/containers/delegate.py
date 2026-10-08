"""Two-line container rows and group summary rows."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPointF,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from anchorage.core.containers import BUSY_ROLE, CONTAINER_ROLE, GROUP_ROLE, KIND_ROLE, GroupSummary
from anchorage.core.units import english_plural
from anchorage.docker.models import Container, PortBinding
from anchorage.ui.theme import state_color

GROUP_HEIGHT = 34
ROW_HEIGHT = 46
PORTS_WIDTH = 230
CHEVRON_X = 16  # centre of the expander glyph, from the row's left edge
TEXT_X = 30  # where the group name starts


_PORT_SEPARATOR = ", "


def _paint_chevron(painter: QPainter, rect: QRect, color: QColor, expanded: bool) -> None:
    cx = rect.left() + CHEVRON_X
    cy = rect.center().y()
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if expanded:
        points = [QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)]
    else:
        points = [QPointF(cx - 2, cy - 4), QPointF(cx + 2, cy), QPointF(cx - 2, cy + 4)]
    painter.drawPolyline(QPolygonF(points))


def ports_text(ports: tuple[PortBinding, ...]) -> str:
    published = [f"{p.public_port}:{p.private_port}" for p in ports if p.public_port]
    return ", ".join(published)


def ports_rect(row: QRect) -> QRect:
    return QRect(row.right() - PORTS_WIDTH, row.top(), PORTS_WIDTH - 10, row.height())


def port_spans(
    ports: tuple[PortBinding, ...], row: QRect, metrics: QFontMetrics
) -> list[tuple[QRect, int]]:
    """Where each published port is drawn: one (rect, public port) per port, right-aligned.

    Painting and hit-testing both use this, so the link a user sees is the link they click.
    """
    area = ports_rect(row)
    labels = [(f"{p.public_port}:{p.private_port}", p.public_port) for p in ports if p.public_port]
    separator = metrics.horizontalAdvance(_PORT_SEPARATOR)
    widths = [metrics.horizontalAdvance(label) for label, _ in labels]
    total = sum(widths) + separator * max(len(labels) - 1, 0)
    x = max(area.left(), area.left() + area.width() - total)
    height = metrics.height()
    top = area.top() + (area.height() - height) // 2
    spans: list[tuple[QRect, int]] = []
    for (_, public), width in zip(labels, widths, strict=True):
        spans.append((QRect(x, top, width, height), public))
        x += width + separator
    return spans


class ContainerDelegate(QStyledItemDelegate):
    port_clicked = Signal(int)

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and index.data(KIND_ROLE) == "container"
        ):
            container: Container | None = index.data(CONTAINER_ROLE)
            if container is not None:
                point = event.position().toPoint()
                metrics = QFontMetrics(self._fonts(option)[0])
                for rect, public in port_spans(container.ports, option.rect, metrics):
                    if rect.contains(point):
                        self.port_clicked.emit(public)
                        return True
        return super().editorEvent(event, model, option, index)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        height = GROUP_HEIGHT if index.data(KIND_ROLE) == "group" else ROW_HEIGHT
        return QSize(0, height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        kind = index.data(KIND_ROLE)
        if kind == "group":
            self._paint_group(painter, option, index.data(GROUP_ROLE))
        elif kind == "container":
            self._paint_container(
                painter, option, index.data(CONTAINER_ROLE), bool(index.data(BUSY_ROLE))
            )
        else:
            super().paint(painter, option, index)

    def _fonts(self, option: QStyleOptionViewItem) -> tuple[QFont, QFont, QFont]:
        base = QFont(option.font)
        bold = QFont(base)
        bold.setWeight(QFont.Weight.DemiBold)
        small = QFont(base)
        small.setPointSize(max(base.pointSize() - 1, 8))
        return base, bold, small

    def _paint_group(
        self, painter: QPainter, option: QStyleOptionViewItem, summary: GroupSummary | None
    ) -> None:
        if summary is None:
            return
        pal = option.palette
        r = option.rect
        painter.save()
        painter.fillRect(r, pal.color(QPalette.ColorRole.AlternateBase))
        expanded = bool(option.state & QStyle.StateFlag.State_Open)
        _paint_chevron(painter, r, pal.color(QPalette.ColorRole.PlaceholderText), expanded)
        _, bold, small = self._fonts(option)
        x = r.left() + TEXT_X
        painter.setFont(bold)
        painter.setPen(pal.color(QPalette.ColorRole.Text))
        painter.drawText(
            QRect(x, r.top(), 400, r.height()), Qt.AlignmentFlag.AlignVCenter, summary.name
        )
        width = painter.fontMetrics().horizontalAdvance(summary.name)
        painter.setFont(small)
        painter.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
        count = english_plural(self.tr("%n container(s)", "", summary.total), summary.total)
        text = (
            count
            if summary.standalone
            else self.tr("{count} · {running}").format(
                count=count, running=self.tr("%n running", "", summary.running)
            )
        )
        painter.drawText(
            QRect(x + width + 12, r.top(), 400, r.height()), Qt.AlignmentFlag.AlignVCenter, text
        )
        painter.restore()

    def _paint_container(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        container: Container | None,
        busy: bool,
    ) -> None:
        if container is None:
            return
        pal = option.palette
        r = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if selected:
            painter.fillRect(r, pal.color(QPalette.ColorRole.Highlight))
        elif hovered:
            painter.fillRect(r, pal.color(QPalette.ColorRole.Button))
        fg = pal.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        if selected:
            muted = QColor(fg)
            muted.setAlpha(170)
        else:
            muted = pal.color(QPalette.ColorRole.PlaceholderText)
        if busy:
            fg = muted
        base, bold, small = self._fonts(option)

        x = r.left() + 10
        dot = fg if selected else state_color(container.state, pal)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(dot))
        painter.drawEllipse(QPointF(x + 5, r.top() + 15), 4, 4)

        tx = x + 18
        text_width = r.width() - tx - PORTS_WIDTH
        painter.setFont(bold)
        painter.setPen(fg)
        name = container.name + ("  …" if busy else "")
        painter.drawText(
            QRect(tx, r.top() + 5, text_width, 20), Qt.AlignmentFlag.AlignVCenter, name
        )
        painter.setFont(small)
        painter.setPen(muted)
        parts = [container.image, container.status]
        if container.compose_service:
            parts.append(self.tr("service: {name}").format(name=container.compose_service))
        line2 = painter.fontMetrics().elidedText(
            "  ·  ".join(parts), Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(
            QRect(tx, r.top() + 24, text_width, 18), Qt.AlignmentFlag.AlignVCenter, line2
        )

        painter.setFont(base)
        painter.setPen(fg if selected else pal.color(QPalette.ColorRole.Link))
        painter.setClipRect(ports_rect(r))
        spans = port_spans(container.ports, r, painter.fontMetrics())
        published = [p for p in container.ports if p.public_port]
        for position, ((rect, _), port) in enumerate(zip(spans, published, strict=True)):
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignVCenter, f"{port.public_port}:{port.private_port}"
            )
            if position < len(spans) - 1:
                painter.drawText(
                    QRect(rect.right() + 1, rect.top(), 40, rect.height()),
                    Qt.AlignmentFlag.AlignVCenter,
                    _PORT_SEPARATOR,
                )
        painter.setClipping(False)
        painter.restore()
