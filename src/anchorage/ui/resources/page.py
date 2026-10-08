"""Table + details card page shared by volumes and networks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QSettings, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anchorage.ui.theme import icon, state_color
from anchorage.ui.widgets.empty_state import EmptyState
from anchorage.ui.widgets.row_delegate import RowDelegate

MEMBERS_FILTER_THRESHOLD = 5


@dataclass(frozen=True, slots=True)
class Member:
    container_id: str
    name: str
    extra: str
    state: str


@dataclass(frozen=True, slots=True)
class DetailsContent:
    title: str
    fields: list[tuple[str, str]]
    members_title: str
    members: list[Member]


class MembersTable(QTableWidget):
    """Row-selecting table that reports Enter/Return on the current row."""

    row_entered = Signal(int)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentRow() >= 0:
            self.row_entered.emit(self.currentRow())
            return
        super().keyPressEvent(event)


class DetailsCard(QFrame):
    container_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._members: list[Member] = []
        self._content: DetailsContent | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        layout.addWidget(self.title_label)
        self._fields = QGridLayout()
        self._fields.setHorizontalSpacing(18)
        self._fields.setVerticalSpacing(4)
        self._fields.setColumnStretch(1, 1)
        layout.addLayout(self._fields)
        head = QHBoxLayout()
        self.members_label = QLabel()
        self.members_label.setObjectName("section")
        head.addWidget(self.members_label)
        head.addStretch()
        self.members_filter = QLineEdit()
        self.members_filter.setObjectName("logsearch")
        self.members_filter.setPlaceholderText("Filter containers…")
        self.members_filter.setClearButtonEnabled(True)
        self.members_filter.setFixedWidth(220)
        self.members_filter.textChanged.connect(self._filter_members)
        head.addWidget(self.members_filter)
        layout.addLayout(head)
        self.members_empty = QLabel("Not used by any container")
        self.members_empty.setObjectName("muted")
        layout.addWidget(self.members_empty)
        self.members_table = MembersTable(0, 3)
        self.members_table.setObjectName("members")
        self.members_table.setHorizontalHeaderLabels(["Container", "", "State"])
        self.members_table.horizontalHeader().setVisible(False)
        self.members_table.verticalHeader().setVisible(False)
        self.members_table.setShowGrid(False)
        self.members_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.members_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.members_table.setItemDelegate(RowDelegate(self.members_table))
        self.members_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.members_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.members_table.verticalHeader().setDefaultSectionSize(26)
        hdr = self.members_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.members_table.cellClicked.connect(self._on_member_clicked)
        self.members_table.row_entered.connect(self._on_member_row)
        layout.addWidget(self.members_table, 1)
        self.hide()

    def field_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in range(self._fields.rowCount()):
            key = self._fields.itemAtPosition(row, 0)
            value = self._fields.itemAtPosition(row, 1)
            key_widget = key.widget() if key is not None else None
            value_widget = value.widget() if value is not None else None
            if isinstance(key_widget, QLabel) and isinstance(value_widget, QLabel):
                values[key_widget.text()] = value_widget.text()
        return values

    def show_content(self, content: DetailsContent) -> None:
        if content == self._content:
            self.show()
            return
        previous = self._content
        keep_filter = (
            self.members_filter.text() if previous and previous.title == content.title else ""
        )
        self._content = content
        self.title_label.setText(content.title)
        while self._fields.count():
            item = self._fields.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for row, (key, value) in enumerate(content.fields):
            key_label = QLabel(key)
            key_label.setObjectName("muted")
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            self._fields.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignTop)
            self._fields.addWidget(value_label, row, 1)
        self._members = list(content.members)
        self.members_label.setText(f"{content.members_title} ({len(self._members)})")
        self.members_filter.setText(keep_filter)
        self.members_filter.setVisible(len(self._members) > MEMBERS_FILTER_THRESHOLD)
        self.members_empty.setVisible(not self._members)
        self.members_table.setVisible(bool(self._members))
        self.members_table.setUpdatesEnabled(False)
        self.members_table.setRowCount(len(self._members))
        palette = self.palette()
        for row, member in enumerate(self._members):
            name = QTableWidgetItem(member.name)
            name.setForeground(palette.color(palette.ColorRole.Link))
            name.setToolTip("Open container")
            extra = QTableWidgetItem(member.extra)
            extra.setForeground(palette.color(palette.ColorRole.PlaceholderText))
            state = QTableWidgetItem(member.state)
            state.setForeground(QColor(state_color(member.state, palette)))
            for col, cell in enumerate((name, extra, state)):
                self.members_table.setItem(row, col, cell)
        self._filter_members(self.members_filter.text())
        self.members_table.setUpdatesEnabled(True)
        self.show()

    def clear(self) -> None:
        self._members = []
        self._content = None
        self.hide()

    def _filter_members(self, text: str) -> None:
        needle = text.strip().lower()
        for row, member in enumerate(self._members):
            self.members_table.setRowHidden(row, bool(needle) and needle not in member.name.lower())

    def _on_member_clicked(self, row: int, _column: int) -> None:
        self._on_member_row(row)

    def _on_member_row(self, row: int) -> None:
        if 0 <= row < len(self._members):
            self.container_activated.emit(self._members[row].container_id)


class ResourcePage(QWidget):
    remove_requested = Signal(str)
    prune_requested = Signal()
    refresh_requested = Signal()
    container_activated = Signal(str)

    def __init__(
        self,
        title: str,
        model: QStandardItemModel,
        widths: list[int],
        row_role: int,
        sort_role: int,
        *,
        prune_text: str = "Prune unused",
        settings: QSettings | None = None,
        settings_key: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row_role = row_role
        self._selected: str | None = None
        self._quiet = False
        self._settings = settings
        self._settings_key = settings_key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        label = QLabel(title)
        label.setObjectName("pageTitle")
        header.addWidget(label)
        header.addStretch()
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("filter")
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(240)
        header.addWidget(self.filter_edit)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setIcon(icon("edit-delete", QStyle.StandardPixmap.SP_TrashIcon))
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._emit_remove)
        header.addWidget(self.remove_button)
        self.prune_button = QPushButton(prune_text)
        self.prune_button.clicked.connect(self.prune_requested.emit)
        header.addWidget(self.prune_button)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(icon("view-refresh", QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # Connected before the proxy attaches so it runs before the selection model reacts.
        model.rowsAboutToBeRemoved.connect(self._begin_quiet)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(model)
        self.proxy.setSortRole(sort_role)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(RowDelegate(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setStretchLastSection(True)
        for col, width in enumerate(widths):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.empty = EmptyState()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)

        self.card = DetailsCard()
        self.card.container_activated.connect(self.container_activated.emit)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.card)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.splitterMoved.connect(self._save_splitter)
        layout.addWidget(self.splitter, 1)
        self._restore_splitter()

        self.filter_edit.textChanged.connect(self._set_filter)

    def details_for(self, row: Any) -> DetailsContent:
        raise NotImplementedError

    def can_remove(self, row: Any) -> tuple[bool, str]:
        """Whether Remove applies to this row; the text explains a refusal."""
        return True, ""

    def _update_remove(self, row: Any | None) -> None:
        allowed, reason = self.can_remove(row) if row is not None else (False, "")
        self.remove_button.setEnabled(allowed)
        self.remove_button.setToolTip("" if allowed else reason)

    def bind_refreshed(self, signal: Any) -> None:
        signal.connect(self._on_refreshed)

    def selected_key(self) -> str | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].data(self._row_role)
        return str(row.name) if row is not None else None

    def set_empty(self, title: str, message: str, action_text: str | None = None) -> None:
        self.empty.set_content(title, message, action_text)
        self.stack.setCurrentWidget(self.empty)
        self.card.clear()

    def clear_empty(self) -> None:
        self.stack.setCurrentWidget(self.table)

    def _emit_remove(self) -> None:
        key = self.selected_key()
        if key:
            self.remove_requested.emit(key)

    def _begin_quiet(self) -> None:
        self._quiet = True

    def _set_filter(self, text: str) -> None:
        self._quiet = True
        try:
            self.proxy.setFilterFixedString(text)
        finally:
            self._quiet = False
        if self._selected is not None:
            self._restore_selection()

    def _on_selection(self) -> None:
        if self._quiet:
            return
        indexes = self.table.selectionModel().selectedRows()
        row = indexes[0].data(self._row_role) if indexes else None
        self._selected = str(row.name) if row is not None else None
        self._update_remove(row)
        if row is None:
            self.card.clear()
        else:
            self.card.show_content(self.details_for(row))

    def _on_refreshed(self) -> None:
        self._quiet = False
        if self._selected is None:
            self.card.clear()
            return
        self._restore_selection()

    def _restore_selection(self) -> None:
        """Re-select the remembered key; hide the card while a filter hides it; drop it if gone."""
        wanted = self._selected
        for proxy_row in range(self.proxy.rowCount()):
            data = self.proxy.index(proxy_row, 0).data(self._row_role)
            if data is not None and data.name == wanted:
                self._quiet = True
                try:
                    self.table.selectRow(proxy_row)
                finally:
                    self._quiet = False
                self._update_remove(data)
                self.card.show_content(self.details_for(data))
                return
        self.table.clearSelection()
        self._update_remove(None)
        self.card.clear()
        if not self._in_source(wanted):
            self._selected = None

    def _in_source(self, key: str | None) -> bool:
        source = self.proxy.sourceModel()
        for row in range(source.rowCount()):
            data = source.index(row, 0).data(self._row_role)
            if data is not None and data.name == key:
                return True
        return False

    def _save_splitter(self) -> None:
        if self._settings is not None and self._settings_key:
            self._settings.setValue(f"{self._settings_key}/splitter", self.splitter.saveState())

    def _restore_splitter(self) -> None:
        if self._settings is None or not self._settings_key:
            return
        state = self._settings.value(f"{self._settings_key}/splitter")
        if state is not None:
            self.splitter.restoreState(state)
