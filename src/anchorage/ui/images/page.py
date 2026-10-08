"""Image table with pull, prune and remove."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from anchorage.core.images import ROW_ROLE, SORT_ROLE, ImageStore, PullJob
from anchorage.ui.images.pull_dialog import PullDialog
from anchorage.ui.images.pull_panel import PullPanel
from anchorage.ui.theme import icon
from anchorage.ui.widgets.empty_state import EmptyState
from anchorage.ui.widgets.row_delegate import RowDelegate


class ImagesPage(QWidget):
    pull_requested = Signal(str, str)
    remove_requested = Signal(str)
    prune_requested = Signal()
    refresh_requested = Signal()
    copied = Signal(str)

    def __init__(self, store: ImageStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._selected: str | None = None
        self._quiet = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel(self.tr("Images"))
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("filter")
        self.filter_edit.setPlaceholderText(self.tr("Filter…"))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(240)
        header.addWidget(self.filter_edit)
        self.pull_button = QPushButton(self.tr("Pull…"))
        self.pull_button.setObjectName("primary")
        self.pull_button.setIcon(icon("download", QStyle.StandardPixmap.SP_ArrowDown))
        self.pull_button.clicked.connect(self.open_pull_dialog)
        header.addWidget(self.pull_button)
        self.remove_button = QPushButton(self.tr("Remove"))
        self.remove_button.setIcon(icon("edit-delete", QStyle.StandardPixmap.SP_TrashIcon))
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._emit_remove)
        header.addWidget(self.remove_button)
        self.prune_button = QPushButton(self.tr("Prune unused"))
        self.prune_button.clicked.connect(self.prune_requested.emit)
        header.addWidget(self.prune_button)
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.setIcon(icon("view-refresh", QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(store.model)
        self.proxy.setSortRole(SORT_ROLE)
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
        for col, width in ((0, 360), (1, 140), (2, 160), (3, 100), (4, 150)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.table.clicked.connect(self._on_cell_clicked)
        id_header = store.model.horizontalHeaderItem(2)
        if id_header is not None:
            id_header.setToolTip(self.tr("Click a cell to copy the full ID"))
        self.empty = EmptyState()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)

        self.panel = PullPanel()
        self.panel.job_finished.connect(self._on_pull_finished)
        layout.addWidget(self.panel)

        self.filter_edit.textChanged.connect(self._set_filter)
        store.model.rowsAboutToBeRemoved.connect(self._begin_quiet)
        store.refreshed.connect(self._restore_selection)

    def selected_reference(self) -> str | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].data(ROW_ROLE)
        return str(row.reference) if row else None

    def show_pull(self, job: PullJob, reference: str) -> None:
        self.pull_button.setEnabled(job.done)
        self.panel.bind(job, reference)

    def open_pull_dialog(self) -> None:
        dialog = PullDialog(self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        reference = dialog.reference() if accepted else None
        dialog.deleteLater()
        if reference is not None:
            self.pull_requested.emit(*reference)

    def _on_pull_finished(self) -> None:
        self.pull_button.setEnabled(True)

    def set_empty(self, title: str, message: str, action_text: str | None = None) -> None:
        self.empty.set_content(title, message, action_text)
        self.stack.setCurrentWidget(self.empty)

    def clear_empty(self) -> None:
        self.stack.setCurrentWidget(self.table)

    def _on_cell_clicked(self, index: QModelIndex) -> None:
        if index.column() != 2:
            return
        row = index.siblingAtColumn(0).data(ROW_ROLE)
        if row is None:
            return
        QApplication.clipboard().setText(row.image.id)
        self.copied.emit(self.tr("Image ID copied"))

    def _emit_remove(self) -> None:
        reference = self.selected_reference()
        if reference:
            self.remove_requested.emit(reference)

    def _begin_quiet(self) -> None:
        self._quiet = True

    def _set_filter(self, text: str) -> None:
        self._quiet = True
        try:
            self.proxy.setFilterFixedString(text)
        finally:
            self._quiet = False

    def _on_selection(self) -> None:
        reference = self.selected_reference()
        if reference is not None and not self._quiet:
            self._selected = reference
        self.remove_button.setEnabled(reference is not None)

    def _restore_selection(self) -> None:
        self._quiet = False
        wanted = self._selected
        if wanted is None:
            return
        if self._store.row(wanted) is None:
            self._selected = None
            self.remove_button.setEnabled(False)
            return
        for row in range(self.proxy.rowCount()):
            data = self.proxy.index(row, 0).data(ROW_ROLE)
            if data is not None and data.reference == wanted:
                self.table.selectRow(row)
                return
