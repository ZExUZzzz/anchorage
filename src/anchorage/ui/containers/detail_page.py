"""One container: header with actions, Logs / Stats / Details tabs, live sessions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from anchorage.core.containers import ContainerStore
from anchorage.core.engine import EngineService
from anchorage.core.sessions import LogSession, StatsSession
from anchorage.docker.client import EngineAPI
from anchorage.docker.errors import DockerError
from anchorage.docker.models import Container, ContainerDetails, Event
from anchorage.ui.containers.details_tree import DetailsTree
from anchorage.ui.containers.list_page import enabled_actions
from anchorage.ui.containers.stats_panel import StatsPanel
from anchorage.ui.theme import icon, state_color
from anchorage.ui.widgets.log_view import LogView

BUTTONS: tuple[tuple[str, str, str, QStyle.StandardPixmap], ...] = (
    ("start", "Start", "media-playback-start", QStyle.StandardPixmap.SP_MediaPlay),
    ("stop", "Stop", "media-playback-stop", QStyle.StandardPixmap.SP_MediaStop),
    ("restart", "Restart", "view-refresh", QStyle.StandardPixmap.SP_BrowserReload),
    ("remove", "Remove", "edit-delete", QStyle.StandardPixmap.SP_TrashIcon),
)


def link_button(text: str = "") -> QToolButton:
    button = QToolButton()
    button.setObjectName("linkButton")
    button.setAutoRaise(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setText(text)
    return button


class ContainerDetailPage(QWidget):
    back_requested = Signal()
    list_requested = Signal()
    project_requested = Signal(str)
    copied = Signal(str)
    action_requested = Signal(str, str)
    notice = Signal(str)

    def __init__(
        self,
        api: EngineAPI,
        store: ContainerStore,
        engine: EngineService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._store = store
        self.container_id: str | None = None
        self._tty = False
        self._details_loaded = False
        self._project = ""
        self._full_id = ""
        self.log_session: LogSession | None = None
        self.stats_session: StatsSession | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        back = QToolButton()
        back.setObjectName("back")
        back.setIcon(icon("go-previous", QStyle.StandardPixmap.SP_ArrowBack))
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        self.crumb_root = link_button("Containers")
        self.crumb_root.clicked.connect(self.list_requested.emit)
        header.addWidget(self.crumb_root)
        sep1 = QLabel("/")
        sep1.setObjectName("crumb")
        header.addWidget(sep1)
        self.crumb_project = link_button()
        self.crumb_project.clicked.connect(self._emit_project)
        header.addWidget(self.crumb_project)
        self.crumb_sep2 = QLabel("/")
        self.crumb_sep2.setObjectName("crumb")
        header.addWidget(self.crumb_sep2)
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        header.addWidget(self.title)
        header.addStretch()
        layout.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)
        status_row = QHBoxLayout()
        self.state_label = QLabel()
        status_row.addWidget(self.state_label)
        self.meta_prefix = QLabel()
        self.meta_prefix.setObjectName("muted")
        status_row.addWidget(self.meta_prefix)
        self.id_button = link_button()
        self.id_button.setToolTip("Copy full ID")
        self.id_button.setAccessibleName("Copy container ID")
        self.id_button.clicked.connect(self._copy_id)
        status_row.addWidget(self.id_button)
        self.meta_label = QLabel()
        self.meta_label.setObjectName("muted")
        status_row.addWidget(self.meta_label)
        status_row.addStretch()
        card_layout.addLayout(status_row)
        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.buttons: dict[str, QPushButton] = {}
        for key, text, icon_name, fallback in BUTTONS:
            button = QPushButton(text)
            button.setIcon(icon(icon_name, fallback))
            button.clicked.connect(lambda _=False, k=key: self._emit_action(k))
            self.buttons[key] = button
            button_row.addWidget(button)
        button_row.addStretch()
        shell = QPushButton("Open shell")
        shell.setObjectName("primary")
        shell.setIcon(icon("utilities-terminal", QStyle.StandardPixmap.SP_ComputerIcon))
        shell.clicked.connect(lambda _=False: self._emit_action("shell"))
        self.buttons["shell"] = shell
        button_row.addWidget(shell)
        card_layout.addLayout(button_row)
        layout.addWidget(card)

        self.tabs = QTabWidget()
        self.log_view = LogView()
        self.stats_panel = StatsPanel()
        self.details_tree = DetailsTree()
        self.tabs.addTab(self.log_view, "Logs")
        self.tabs.addTab(self.stats_panel, "Stats")
        self.tabs.addTab(self.details_tree, "Details")
        layout.addWidget(self.tabs, 1)

        store.refreshed.connect(self.refresh_header)
        store.busy_changed.connect(self._on_busy_changed)
        store.details_ready.connect(self._on_details)
        store.details_failed.connect(self._on_details_failed)
        engine.event_received.connect(self._on_event)

    def show_container(self, container_id: str) -> None:
        self.leave()
        self.container_id = container_id
        self.log_view.clear()
        self.stats_panel.reset()
        self.details_tree.clear()
        self.refresh_header()
        self._store.inspect(container_id)

    def leave(self) -> None:
        self._stop_sessions()
        self.container_id = None
        self._tty = False
        self._details_loaded = False

    def refresh_header(self) -> None:
        if self.container_id is None:
            return
        container = self._store.container(self.container_id)
        if container is None:
            self.leave()
            self.back_requested.emit()
            return
        self._render(container)

    def _render(self, container: Container) -> None:
        palette = self.palette()
        self.title.setText(container.name)
        project = container.compose_project or ""
        self._project = project
        self.crumb_project.setText(project)
        self.crumb_project.setVisible(bool(project))
        self.crumb_sep2.setVisible(bool(project))
        color = state_color(container.state, palette)
        self.state_label.setText(f"●  {container.state}")
        self.state_label.setStyleSheet(f"color: {color.name()}; font-weight: 600;")
        ports = ", ".join(
            f"{p.host_ip or '0.0.0.0'}:{p.public_port}→{p.private_port}/{p.protocol}"
            for p in container.ports
            if p.public_port
        )
        self.meta_prefix.setText(f"{container.image}  ·")
        self.id_button.setText(container.short_id)
        self._full_id = container.id
        meta = [container.status] + ([ports] if ports else [])
        self.meta_label.setText("·  " + "  ·  ".join(meta))
        allowed = enabled_actions(container.state, self._store.is_busy(container.id))
        for key, button in self.buttons.items():
            button.setEnabled(key in allowed)

    def _emit_project(self) -> None:
        if self._project:
            self.project_requested.emit(self._project)

    def _copy_id(self) -> None:
        QApplication.clipboard().setText(self._full_id)
        self.copied.emit("Container ID copied")

    def _on_busy_changed(self, container_id: str, busy: bool) -> None:
        if container_id == self.container_id:
            self.refresh_header()

    def _emit_action(self, key: str) -> None:
        if self.container_id is not None:
            self.action_requested.emit(key, self.container_id)

    def _on_details(self, container_id: str, details: ContainerDetails) -> None:
        if container_id != self.container_id:
            return
        self.details_tree.show_details(details)
        self._tty = details.tty
        if not self._details_loaded:
            self._details_loaded = True
            self._start_sessions()

    def _on_details_failed(self, container_id: str, error: DockerError) -> None:
        if container_id == self.container_id:
            self.notice.emit(f"Cannot inspect container: {error.message}")

    def _on_event(self, event: Event) -> None:
        if event.type != "container" or event.actor_id != self.container_id:
            return
        if event.action == "start" and self._details_loaded:
            self.log_view.clear()
            self.stats_panel.reset()
            self._start_sessions()

    def _start_sessions(self) -> None:
        self._stop_sessions()
        if self.container_id is None:
            return
        self.log_session = LogSession(self._api, self.container_id, tty=self._tty, parent=self)
        self.log_session.lines_added.connect(self.log_view.append_lines)
        self.log_session.ended.connect(self._on_log_ended)
        self.log_session.start()
        self.stats_session = StatsSession(self._api, self.container_id, parent=self)
        self.stats_session.sample_added.connect(self.stats_panel.add_point)
        self.stats_session.start()

    def _stop_sessions(self) -> None:
        for session in (self.log_session, self.stats_session):
            if session is not None:
                session.dispose()
                session.deleteLater()
        self.log_session = None
        self.stats_session = None

    def _on_log_ended(self, error: object) -> None:
        if self.sender() is self.log_session:
            self.log_view.mark_ended(error if isinstance(error, DockerError) else None)
