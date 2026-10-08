"""Top-level window: sidebar, page stack, status bar, toasts, confirmations, shutdown."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from anchorage.core import terminal
from anchorage.core.engine import EngineState
from anchorage.core.settings import AppSettings, Resolved
from anchorage.core.terminal import Launch
from anchorage.core.units import english_plural, format_bytes
from anchorage.docker.errors import DockerError, EngineUnavailable, PermissionDenied
from anchorage.docker.models import PruneResult, VersionInfo
from anchorage.ui.containers.detail_page import ContainerDetailPage
from anchorage.ui.containers.list_page import ContainersPage
from anchorage.ui.context import AppContext
from anchorage.ui.images.page import ImagesPage
from anchorage.ui.resources.networks import NetworksPage
from anchorage.ui.resources.volumes import VolumesPage
from anchorage.ui.settings_dialog import SettingsDialog
from anchorage.ui.theme import level_color, state_color
from anchorage.ui.widgets.sidebar import Sidebar
from anchorage.ui.widgets.toast import Toast

Confirm = Callable[[str, str, list[str]], str]
LaunchShell = Callable[[str], Launch]


class MainWindow(QMainWindow):
    PAGE_CONTAINERS = 0
    PAGE_DETAIL = 1
    PAGE_IMAGES = 2
    PAGE_VOLUMES = 3
    PAGE_NETWORKS = 4
    _SECTION_PAGES: ClassVar[dict[str, int]] = {
        "containers": PAGE_CONTAINERS,
        "images": PAGE_IMAGES,
        "volumes": PAGE_VOLUMES,
        "networks": PAGE_NETWORKS,
    }

    def __init__(
        self,
        context: AppContext,
        *,
        confirm: Confirm | None = None,
        launch_shell: LaunchShell | None = None,
        settings: QSettings | None = None,
        app_settings: AppSettings | None = None,
        resolved: Resolved | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self._origin = self.PAGE_CONTAINERS
        self.confirm: Confirm = confirm or self._ask
        self.app_settings = app_settings
        self.resolved = resolved or Resolved.defaults()
        self._launch_shell: LaunchShell = launch_shell or self._open_shell
        self.setWindowTitle("Anchorage")
        self.resize(1180, 720)
        self._settings = settings
        if settings is not None:
            geometry = settings.value("window/geometry")
            if isinstance(geometry, QByteArray) and not self.restoreGeometry(geometry):
                self.resize(1180, 720)

        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.section_changed.connect(self._on_section)
        self.sidebar.settings_requested.connect(self.open_settings)
        self.settings_dialog: SettingsDialog | None = None
        row.addWidget(self.sidebar)

        content = QWidget()
        content.setObjectName("content")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.toast = Toast()
        column.addWidget(self.toast)
        self.pages = QStackedWidget()
        column.addWidget(self.pages, 1)
        row.addWidget(content, 1)

        self.containers_page = ContainersPage(context.containers)
        self.detail_page = ContainerDetailPage(context.api, context.containers, context.engine)
        self.images_page = ImagesPage(context.images)
        self.volumes_page = VolumesPage(context.volumes, settings=settings)
        self.networks_page = NetworksPage(context.networks, settings=settings)
        self.pages.addWidget(self.containers_page)
        self.pages.addWidget(self.detail_page)
        self.pages.addWidget(self.images_page)
        self.pages.addWidget(self.volumes_page)
        self.pages.addWidget(self.networks_page)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_connection = QLabel()
        status.addWidget(self.status_connection)
        self.status_counts = QLabel()
        self.status_counts.setObjectName("muted")
        status.addWidget(self.status_counts)
        self.status_version = QLabel()
        self.status_version.setObjectName("muted")
        status.addPermanentWidget(self.status_version)

        self.containers_page.container_activated.connect(self.open_container)
        self.containers_page.action_requested.connect(self.perform)
        self.containers_page.refresh_requested.connect(context.containers.refresh)
        self.containers_page.empty.action_clicked.connect(context.engine.reconnect_now)
        self.detail_page.back_requested.connect(self.show_origin)
        self.detail_page.list_requested.connect(self.show_list)
        self.detail_page.project_requested.connect(self.show_project)
        self.detail_page.copied.connect(self._on_copied)
        self.images_page.copied.connect(self._on_copied)
        self.detail_page.action_requested.connect(self.perform)
        self.detail_page.notice.connect(self.toast.show_message)
        self.images_page.pull_requested.connect(self._pull)
        self.images_page.remove_requested.connect(self._remove_image)
        self.images_page.prune_requested.connect(self._prune)
        self.images_page.refresh_requested.connect(context.images.refresh)
        self.images_page.empty.action_clicked.connect(context.engine.reconnect_now)
        self.volumes_page.remove_requested.connect(self._remove_volume)
        self.volumes_page.prune_requested.connect(self._prune_volumes)
        self.volumes_page.refresh_requested.connect(context.volumes.refresh)
        self.volumes_page.container_activated.connect(self.open_container)
        self.volumes_page.empty.action_clicked.connect(context.engine.reconnect_now)
        self.networks_page.remove_requested.connect(self._remove_network)
        self.networks_page.prune_requested.connect(self._prune_networks)
        self.networks_page.refresh_requested.connect(context.networks.refresh)
        self.networks_page.container_activated.connect(self.open_container)
        self.networks_page.empty.action_clicked.connect(context.engine.reconnect_now)

        context.containers.refreshed.connect(self._update_counts)
        context.images.refreshed.connect(self._update_counts)
        context.containers.action_failed.connect(self._on_action_failed)
        context.containers.refresh_failed.connect(self._on_refresh_failed)
        context.images.action_failed.connect(self._on_action_failed)
        context.images.refresh_failed.connect(self._on_refresh_failed)
        context.images.pruned.connect(self._on_pruned)
        for store in (context.volumes, context.networks):
            store.refreshed.connect(self._update_counts)
            store.action_failed.connect(self._on_action_failed)
            store.refresh_failed.connect(self._on_refresh_failed)
        context.volumes.pruned.connect(self._on_volumes_pruned)
        context.networks.pruned.connect(self._on_networks_pruned)

        self.sidebar.set_socket(context.engine.socket_path)
        context.engine.state_changed.connect(self._on_engine_state)
        context.engine.version_changed.connect(self._on_version)
        self._on_engine_state(context.engine.state)

    def open_container(self, container_id: str) -> None:
        if self.pages.currentIndex() != self.PAGE_DETAIL:
            self._origin = self.pages.currentIndex()
        self.detail_page.show_container(container_id)
        self.pages.setCurrentIndex(self.PAGE_DETAIL)

    def show_list(self) -> None:
        self._leave_detail()
        self.containers_page.clear_project_filter()
        self.pages.setCurrentIndex(self.PAGE_CONTAINERS)
        self.sidebar.select("containers")

    def show_origin(self) -> None:
        self._leave_detail()
        index = self._origin
        self.pages.setCurrentIndex(index)
        key = {v: k for k, v in self._SECTION_PAGES.items()}.get(index, "containers")
        self.sidebar.select(key)

    def show_project(self, project: str) -> None:
        self._leave_detail()
        self.containers_page.set_project_filter(project)
        self.pages.setCurrentIndex(self.PAGE_CONTAINERS)
        self.sidebar.select("containers")

    def _on_copied(self, text: str) -> None:
        self.toast.show_message(text, 2000)

    def perform(self, action: str, container_id: str) -> None:
        store = self.context.containers
        container = store.container(container_id)
        name = container.name if container else container_id[:12]
        if action == "start":
            store.start(container_id)
        elif action == "stop":
            store.stop(container_id)
        elif action == "restart":
            store.restart(container_id)
        elif action == "remove":
            running = bool(container and container.state in ("running", "paused", "restarting"))
            buttons = ["Force remove", "Cancel"] if running else ["Remove", "Cancel"]
            if running:
                text = self.tr("Remove container {name}? It is running and will be killed.")
            else:
                text = self.tr("Remove container {name}?")
            choice = self.confirm(self.tr("Remove container"), text.format(name=name), buttons)
            if choice == "Force remove":
                store.remove(container_id, force=True)
            elif choice == "Remove":
                store.remove(container_id)
        elif action == "shell":
            launch = self._launch_shell(container_id)
            if not launch.ok:
                command = " ".join(launch.command)
                self.confirm(
                    self.tr("Cannot open a terminal"),
                    self.tr("{reason}. Run this command in a terminal:\n\n{command}").format(
                        reason=launch.reason, command=command
                    ),
                    ["OK"],
                )

    def open_settings(self) -> None:
        if self.app_settings is None:
            return
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            return
        dialog = SettingsDialog(
            self.app_settings,
            self.resolved,
            discovered_socket=self.context.engine.socket_path,
            parent=self,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.settings_dialog = dialog
        dialog.accepted.connect(lambda: self._on_settings_accepted(dialog))
        dialog.finished.connect(self._on_settings_closed)
        dialog.open()

    def _on_settings_closed(self) -> None:
        self.settings_dialog = None

    def _on_settings_accepted(self, dialog: SettingsDialog) -> None:
        changed = dialog.save()
        store = self.app_settings
        if store is None or not changed:
            return
        values = {key: getattr(store, key) for key in changed}
        self.resolved = dataclasses.replace(self.resolved, **values)
        if "log_colors" in changed:
            self.detail_page.log_view.set_color_mode(self.resolved.log_colors)
        if changed & {"socket", "backend", "language"}:
            self.toast.show_message(
                self.tr("Socket, backend and language changes apply after a restart")
            )

    def _open_shell(self, container_id: str) -> Launch:
        command = self.app_settings.terminal if self.app_settings is not None else ""
        return terminal.open_shell(container_id, command=command)

    def _pull(self, repository: str, tag: str) -> None:
        job = self.context.images.pull(repository, tag)
        self.images_page.show_pull(job, f"{repository}:{tag}")
        job.start()

    def _remove_image(self, reference: str) -> None:
        choice = self.confirm(
            self.tr("Remove image"),
            self.tr("Remove image {reference}?").format(reference=reference),
            ["Remove", "Force remove", "Cancel"],
        )
        if choice == "Remove":
            self.context.images.remove(reference)
        elif choice == "Force remove":
            self.context.images.remove(reference, force=True)

    def _prune(self) -> None:
        choice = self.confirm(
            self.tr("Prune images"), self.tr("Remove all dangling images?"), ["Prune", "Cancel"]
        )
        if choice == "Prune":
            self.context.images.prune()

    def _on_pruned(self, result: PruneResult) -> None:
        count = len(result.deleted)
        message = self.tr("Pruned %n image(s), reclaimed {size}", "", count)
        self.toast.show_message(
            english_plural(message, count).format(size=format_bytes(result.space_reclaimed))
        )

    def _remove_volume(self, name: str) -> None:
        choice = self.confirm(
            self.tr("Remove volume"),
            self.tr("Remove volume {name}?").format(name=name),
            ["Remove", "Cancel"],
        )
        if choice == "Remove":
            self.context.volumes.remove(name)

    def _prune_volumes(self) -> None:
        choice = self.confirm(
            self.tr("Prune volumes"),
            self.tr(
                "Remove all volumes not used by any container? Named volumes are included "
                "and data in them is lost. This cannot be undone."
            ),
            ["Prune", "Cancel"],
        )
        if choice == "Prune":
            self.context.volumes.prune()

    def _on_volumes_pruned(self, result: PruneResult) -> None:
        count = len(result.deleted)
        message = self.tr("Pruned %n volume(s), reclaimed {size}", "", count)
        self.toast.show_message(
            english_plural(message, count).format(size=format_bytes(result.space_reclaimed))
        )

    def _remove_network(self, name: str) -> None:
        row = self.context.networks.row(name)
        if row is None:
            return
        choice = self.confirm(
            self.tr("Remove network"),
            self.tr("Remove network {name}?").format(name=name),
            ["Remove", "Cancel"],
        )
        if choice == "Remove":
            self.context.networks.remove(row.network.id)

    def _prune_networks(self) -> None:
        choice = self.confirm(
            self.tr("Prune networks"),
            self.tr("Remove all networks not used by any container?"),
            ["Prune", "Cancel"],
        )
        if choice == "Prune":
            self.context.networks.prune()

    def _on_networks_pruned(self, result: PruneResult) -> None:
        count = len(result.deleted)
        self.toast.show_message(english_plural(self.tr("Pruned %n network(s)", "", count), count))

    def _on_action_failed(self, target: str, error: DockerError) -> None:
        self.toast.show_message(error.message)

    def _on_refresh_failed(self, error: DockerError) -> None:
        self.toast.show_message(self.tr("Refresh failed: {message}").format(message=error.message))

    def _update_counts(self) -> None:
        containers = self.context.containers.containers()
        running = sum(1 for c in containers if c.state == "running")
        images = len({r.image.id for r in self.context.images.rows()})
        projects = len({c.compose_project for c in containers if c.compose_project})
        volumes = len(self.context.volumes.rows())
        networks = len(self.context.networks.rows())
        parts = [
            self.tr("{containers}, {running}").format(
                containers=english_plural(
                    self.tr("%n container(s)", "", len(containers)), len(containers)
                ),
                running=self.tr("%n running", "", running),
            ),
            english_plural(self.tr("%n image(s)", "", images), images),
            english_plural(self.tr("%n volume(s)", "", volumes), volumes),
            english_plural(self.tr("%n network(s)", "", networks), networks),
        ]
        if projects:
            parts.append(english_plural(self.tr("%n compose project(s)", "", projects), projects))
        self.status_counts.setText("  ·  ".join(parts))

    def _on_section(self, key: str) -> None:
        index = self._SECTION_PAGES.get(key)
        if index is None:
            return
        self._leave_detail()
        self.pages.setCurrentIndex(index)

    def _leave_detail(self) -> None:
        if self.detail_page.container_id is not None:
            self.detail_page.leave()

    def _on_engine_state(self, state: EngineState) -> None:
        palette = self.palette()
        engine = self.context.engine
        error = engine.error
        if state is EngineState.CONNECTED:
            text, color = self.tr("Connected"), state_color("running", palette)
            self.containers_page.clear_empty()
            self.images_page.clear_empty()
            self.volumes_page.clear_empty()
            self.networks_page.clear_empty()
        else:
            if state is EngineState.CONNECTING:
                text, color = self.tr("Connecting…"), state_color("paused", palette)
                title, message = self.tr("Connecting to Docker Engine…"), engine.socket_path
            elif isinstance(error, PermissionDenied):
                text, color = (
                    self.tr("Permission denied on the Docker socket"),
                    level_color("error", palette),
                )
                title = self.tr("Permission denied")
                message = self.tr(
                    "Add your user to the docker group to use {path}, then log in again."
                ).format(path=engine.socket_path)
            elif error is not None and not isinstance(error, EngineUnavailable):
                text, color = error.message, level_color("error", palette)
                title, message = self.tr("Cannot reach Docker Engine"), error.message
            else:
                if isinstance(error, EngineUnavailable):
                    text = self.tr("Docker Engine is not running")
                    color = level_color("error", palette)
                else:
                    text, color = self.tr("Not connected"), state_color("dead", palette)
                detail = error.message if error else ""
                saved_socket = self.resolved.socket
                if saved_socket and "socket" not in self.resolved.locked:
                    title = self.tr("Docker socket not available")
                    message = (
                        self.tr(
                            "The socket set in Settings ({socket}) is not available. "
                            "Start the docker service, or change the socket in Settings or clear "
                            "it to find the daemon automatically.\n{detail}"
                        )
                        .format(socket=saved_socket, detail=detail)
                        .strip()
                    )
                else:
                    title = self.tr("Docker Engine is not running")
                    message = (
                        self.tr("Start the docker service and retry.\n{detail}")
                        .format(detail=detail)
                        .strip()
                    )
            action = None if state is EngineState.CONNECTING else self.tr("Retry")
            for page in (
                self.containers_page,
                self.images_page,
                self.volumes_page,
                self.networks_page,
            ):
                page.set_empty(title, message, action)
            was_detail = self.pages.currentIndex() == self.PAGE_DETAIL
            self._leave_detail()
            if was_detail:
                self.pages.setCurrentIndex(self.PAGE_CONTAINERS)
                self.sidebar.select("containers")
            self.status_counts.setText("")
        self.status_connection.setText(f"●  {text}")
        self.status_connection.setStyleSheet(f"color: {color.name()};")
        version = engine.version
        engine_text = (
            self.tr("Engine {version}").format(version=version.version)
            if version and state is EngineState.CONNECTED
            else self.tr("Engine: not connected")
        )
        self.sidebar.set_engine(f"●  {engine_text}", color)
        if state is not EngineState.CONNECTED:
            self.status_version.setText("")
        elif version is not None:
            self._on_version(version)

    def _on_version(self, version: VersionInfo) -> None:
        api = version.api_version
        self.status_version.setText(self.tr("API {version}").format(version=api) if api else "")

    def _ask(self, title: str, text: str, buttons: list[str]) -> str:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        added: dict[str, QPushButton] = {}
        for key in buttons:
            role = (
                QMessageBox.ButtonRole.RejectRole
                if key == "Cancel"
                else QMessageBox.ButtonRole.AcceptRole
            )
            if key.startswith("Force") or key in ("Remove", "Prune"):
                role = QMessageBox.ButtonRole.DestructiveRole
            added[key] = box.addButton(self._button_text(key), role)
        if "Cancel" in added:
            box.setDefaultButton(added["Cancel"])
        box.exec()
        clicked = box.clickedButton()
        for key, button in added.items():
            if button is clicked:
                return key
        return "Cancel"

    def _button_text(self, key: str) -> str:
        """The visible label of a confirmation button; ``key`` is what ``confirm`` returns."""
        if key == "Remove":
            return self.tr("Remove")
        if key == "Force remove":
            return self.tr("Force remove")
        if key == "Prune":
            return self.tr("Prune")
        if key == "Cancel":
            return self.tr("Cancel")
        if key == "OK":
            return self.tr("OK")
        return key

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._settings is not None:
            self._settings.setValue("window/geometry", self.saveGeometry())
        self.detail_page.leave()
        self.context.shutdown()
        event.accept()
