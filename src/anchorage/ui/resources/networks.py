"""Networks page."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QWidget

from anchorage.core.networks import ROW_ROLE, SORT_ROLE, NetworkRow, NetworkStore
from anchorage.ui.resources.page import DetailsContent, Member, ResourcePage

BUILTIN_NETWORKS = frozenset({"bridge", "host", "none"})


class NetworksPage(ResourcePage):
    def __init__(
        self,
        store: NetworkStore,
        *,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            QCoreApplication.translate("NetworksPage", "Networks"),
            store.model,
            [360, 90, 70, 180, 100, 80],
            ROW_ROLE,
            SORT_ROLE,
            settings=settings,
            settings_key="networks",
            parent=parent,
        )
        self.bind_refreshed(store.refreshed)

    def can_remove(self, row: NetworkRow) -> tuple[bool, str]:
        if row.network.name in BUILTIN_NETWORKS:
            return False, self.tr("Built-in network")
        if row.members:
            return False, self.tr("Network has connected containers")
        return True, ""

    def details_for(self, row: NetworkRow) -> DetailsContent:
        network = row.network
        created = network.created.astimezone().strftime("%Y-%m-%d %H:%M") if network.created else ""
        subnets = (
            "  ·  ".join(
                self.tr("{subnet}  gw {gateway}").format(subnet=s.subnet, gateway=s.gateway)
                for s in network.subnets
            )
            or "—"
        )
        flags = ", ".join(
            name
            for name, on in (
                (self.tr("internal"), network.internal),
                (self.tr("attachable"), network.attachable),
                (self.tr("ingress"), network.ingress),
                (self.tr("ipv6"), network.ipv6),
            )
            if on
        ) or self.tr("none")
        labels = "  ·  ".join(
            f"{k}={v}" for k, v in sorted(network.labels.items()) if "config-hash" not in k
        ) or self.tr("none")
        fields = [
            (self.tr("ID"), network.short_id),
            (
                self.tr("Driver"),
                self.tr("{driver} · scope {scope}").format(
                    driver=network.driver, scope=network.scope
                ),
            ),
            (self.tr("Subnet"), subnets),
            (self.tr("Flags"), flags),
            (self.tr("Created"), created),
            (self.tr("Labels"), labels),
        ]
        members = [Member(m.container_id, m.container_name, m.ip, m.state) for m in row.members]
        return DetailsContent(network.name, fields, self.tr("CONNECTED CONTAINERS"), members)
