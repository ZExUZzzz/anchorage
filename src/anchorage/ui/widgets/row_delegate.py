"""Item delegate for row-selecting tables: no per-cell focus frame."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem


class RowDelegate(QStyledItemDelegate):
    """Drops ``State_HasFocus`` so styles like Breeze do not outline the current cell."""

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        option.state &= ~QStyle.StateFlag.State_HasFocus
