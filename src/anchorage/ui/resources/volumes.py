"""Volumes page."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from anchorage.core.volumes import ROW_ROLE, SORT_ROLE, VolumeRow, VolumeStore, VolumeUse
from anchorage.ui.resources.page import DetailsContent, Member, ResourcePage


class VolumesPage(ResourcePage):
    def __init__(
        self,
        store: VolumeStore,
        *,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Volumes",
            store.model,
            [360, 90, 160, 120, 150],
            ROW_ROLE,
            SORT_ROLE,
            settings=settings,
            settings_key="volumes",
            parent=parent,
        )
        self.bind_refreshed(store.refreshed)

    def details_for(self, row: VolumeRow) -> DetailsContent:
        volume = row.volume
        created = volume.created.astimezone().strftime("%Y-%m-%d %H:%M") if volume.created else ""
        labels = "  ·  ".join(f"{k}={v}" for k, v in sorted(volume.labels.items())) or "none"
        options = "  ·  ".join(f"{k}={v}" for k, v in sorted(volume.options.items())) or "none"
        fields = [
            ("Mountpoint", volume.mountpoint),
            ("Driver", f"{volume.driver} · scope {volume.scope}"),
            ("Created", created),
            ("Labels", labels),
            ("Options", options),
        ]
        by_container: dict[str, list[VolumeUse]] = {}
        for use in row.users:
            by_container.setdefault(use.container_id, []).append(use)
        members = [
            Member(
                uses[0].container_id,
                uses[0].container_name,
                "mounted at " + ", ".join(u.destination for u in uses),
                uses[0].state,
            )
            for uses in by_container.values()
        ]
        return DetailsContent(volume.name, fields, "USED BY", members)
