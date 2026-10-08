"""Grouped container list with filter, running-only toggle and context menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QSignalBlocker,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from anchorage.core.containers import ID_ROLE, KIND_ROLE, ContainerStore
from anchorage.ui.containers.delegate import ContainerDelegate
from anchorage.ui.containers.filter import ContainerFilterProxy
from anchorage.ui.theme import icon
from anchorage.ui.widgets.empty_state import EmptyState

ACTIONS: tuple[tuple[str, str], ...] = (
    ("start", str(QT_TRANSLATE_NOOP("ContainersPage", "Start"))),
    ("stop", str(QT_TRANSLATE_NOOP("ContainersPage", "Stop"))),
    ("restart", str(QT_TRANSLATE_NOOP("ContainersPage", "Restart"))),
    ("remove", str(QT_TRANSLATE_NOOP("ContainersPage", "Remove"))),
    ("shell", str(QT_TRANSLATE_NOOP("ContainersPage", "Open shell"))),
)


def enabled_actions(state: str, busy: bool) -> set[str]:
    if busy:
        return set()
    out = {"remove"}
    if state == "running":
        out |= {"stop", "restart", "shell"}
    elif state == "paused":
        out |= {"stop", "restart"}
    else:
        out |= {"start"}
    return out


def _open_in_browser(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class ContainersPage(QWidget):
    container_activated = Signal(str)
    action_requested = Signal(str, str)
    refresh_requested = Signal()

    def __init__(
        self,
        store: ContainerStore,
        parent: QWidget | None = None,
        *,
        open_url: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._open_url = open_url or _open_in_browser
        self._port_click = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel(self.tr("Containers"))
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("filter")
        self.filter_edit.setPlaceholderText(self.tr("Filter by name, image, project…"))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(260)
        header.addWidget(self.filter_edit)
        self.running_only = QPushButton(self.tr("Running only"))
        self.running_only.setCheckable(True)
        header.addWidget(self.running_only)
        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.setIcon(icon("view-refresh", QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.proxy = ContainerFilterProxy(self)
        self.proxy.setSourceModel(store.model)
        self.tree = QTreeView()
        self.tree.setObjectName("containers")
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.delegate = ContainerDelegate(self.tree)
        self.delegate.port_clicked.connect(self._on_port_clicked)
        self.tree.setItemDelegate(self.delegate)
        self.tree.setIndentation(16)
        self.tree.setRootIsDecorated(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setMouseTracking(True)
        self.tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.pressed.connect(self._on_pressed)
        self.tree.clicked.connect(self._on_clicked)
        # ``activated`` is not connected on purpose: single-click desktops emit it together
        # with ``clicked``; Enter is handled in eventFilter instead.
        self.tree.installEventFilter(self)
        self.collapsed: set[str] = set()
        self._syncing = False
        self.tree.collapsed.connect(lambda i: self._track(i, collapsed=True))
        self.tree.expanded.connect(lambda i: self._track(i, collapsed=False))
        self.empty = EmptyState()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)

        self.filter_edit.textChanged.connect(self._on_filter)
        self.running_only.toggled.connect(self._on_running_only)
        store.refreshed.connect(self.expand_groups)
        self.expand_groups()

    def expand_groups(self) -> None:
        """Expand every group except the ones the user collapsed.

        While a filter or project crumb is active every visible group is expanded so no match
        is hidden; the stored collapsed set is left alone and applies again once it is empty.
        """
        searching = bool(self.filter_edit.text().strip()) or self.proxy.project is not None
        self._syncing = True
        try:
            for row in range(self.proxy.rowCount()):
                index = self.proxy.index(row, 0)
                name = str(index.data(Qt.ItemDataRole.DisplayRole))
                self.tree.setExpanded(index, searching or name not in self.collapsed)
        finally:
            self._syncing = False

    def _track(self, index: QModelIndex, *, collapsed: bool) -> None:
        if self._syncing:
            return
        name = str(index.data(Qt.ItemDataRole.DisplayRole))
        if collapsed:
            self.collapsed.add(name)
        else:
            self.collapsed.discard(name)

    def toggle_group(self, index: QModelIndex) -> None:
        self.tree.setExpanded(index, not self.tree.isExpanded(index))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            obj is self.tree
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._activate(self.tree.currentIndex())
            return True
        return super().eventFilter(obj, event)

    def _activate(self, index: QModelIndex) -> None:
        kind = index.data(KIND_ROLE)
        if kind == "container":
            self.container_activated.emit(str(index.data(ID_ROLE)))
        elif kind == "group":
            self.toggle_group(index)

    def set_empty(self, title: str, message: str, action_text: str | None = None) -> None:
        self.empty.set_content(title, message, action_text)
        self.stack.setCurrentWidget(self.empty)

    def clear_empty(self) -> None:
        self.stack.setCurrentWidget(self.tree)

    def set_project_filter(self, project: str) -> None:
        self.running_only.setChecked(False)
        self.proxy.set_project(project)
        blocker = QSignalBlocker(self.filter_edit)
        self.filter_edit.setText(project)
        blocker.unblock()
        self.collapsed.discard(project)
        self.expand_groups()

    def clear_project_filter(self) -> None:
        """Leave project mode (and empty the field it filled); a typed filter stays."""
        if self.proxy.project is not None:
            self.filter_edit.clear()
            self.proxy.set_project(None)
            self.expand_groups()

    def selected_container_id(self) -> str | None:
        index = self.tree.currentIndex()
        if index.isValid() and index.data(KIND_ROLE) == "container":
            return str(index.data(ID_ROLE))
        return None

    def menu_for(self, container_id: str) -> QMenu:
        container = self._store.container(container_id)
        menu = QMenu(self)
        state = container.state if container else ""
        allowed = enabled_actions(state, self._store.is_busy(container_id))
        for key, text in ACTIONS:
            action = QAction(QCoreApplication.translate("ContainersPage", text), menu)
            action.setEnabled(key in allowed)
            action.triggered.connect(
                lambda _=False, k=key, cid=container_id: self.action_requested.emit(k, cid)
            )
            menu.addAction(action)
        return menu

    def _on_filter(self, text: str) -> None:
        self.proxy.set_project(None)
        self.proxy.set_text(text)
        self.expand_groups()

    def _on_running_only(self, checked: bool) -> None:
        self.proxy.set_running_only(checked)
        self.expand_groups()

    def _on_pressed(self, index: QModelIndex) -> None:
        self._port_click = False

    def _on_port_clicked(self, port: int) -> None:
        # The view still emits ``clicked`` for this release; it belongs to the link.
        self._port_click = True
        self._open_url(f"http://localhost:{port}")

    def _on_clicked(self, index: QModelIndex) -> None:
        if self._port_click:
            self._port_click = False
            return
        self._activate(index)

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self.tree.indexAt(pos)
        if index.data(KIND_ROLE) != "container":
            return
        menu = self.menu_for(str(index.data(ID_ROLE)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        menu.deleteLater()
