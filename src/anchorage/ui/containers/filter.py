"""Text and running-only filtering over the grouped container model."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel

from anchorage.core.containers import CONTAINER_ROLE, KIND_ROLE

# Resolved once; tests patch it to exercise the pre-6.10 path.
HAS_FILTER_CHANGE = hasattr(QSortFilterProxyModel, "endFilterChange")


class ContainerFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._running_only = False
        self._project: str | None = None
        self.setRecursiveFilteringEnabled(True)

    @property
    def project(self) -> str | None:
        return self._project

    def _change_filter(self, apply: Callable[[], None]) -> None:
        # Qt 6.10 introduced begin/endFilterChange; older Qt re-filters with invalidateFilter.
        if HAS_FILTER_CHANGE:
            self.beginFilterChange()
            apply()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            apply()
            self.invalidateFilter()

    def set_text(self, text: str) -> None:
        value = text.strip().lower()

        def apply() -> None:
            self._text = value

        self._change_filter(apply)

    def set_project(self, project: str | None) -> None:
        def apply() -> None:
            self._project = project

        self._change_filter(apply)

    def set_running_only(self, flag: bool) -> None:
        def apply() -> None:
            self._running_only = flag

        self._change_filter(apply)

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        if index.data(KIND_ROLE) != "container":
            return False
        container = index.data(CONTAINER_ROLE)
        if container is None:
            return False
        if self._running_only and container.state != "running":
            return False
        if self._project is not None:
            return bool(container.compose_project == self._project)
        if not self._text:
            return True
        haystack = " ".join(
            filter(
                None,
                (
                    container.name,
                    container.image,
                    container.compose_project,
                    container.compose_service,
                ),
            )
        ).lower()
        return self._text in haystack
