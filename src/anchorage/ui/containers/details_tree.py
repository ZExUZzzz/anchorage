"""Inspect output as a two-column tree."""

from __future__ import annotations

import shlex

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from anchorage.docker.models import ContainerDetails

# Section keys stay English; the visible titles are translated in ``show_details``.
_EXPANDED = {"General", "Ports", "Mounts", "Networks"}


class DetailsTree(QTreeWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels([self.tr("Key"), self.tr("Value")])
        self.setColumnWidth(0, 260)
        self.setAlternatingRowColors(True)

    def show_details(self, details: ContainerDetails) -> None:
        self.clear()
        state = details.state
        created = (
            details.created.astimezone().strftime("%Y-%m-%d %H:%M:%S") if details.created else ""
        )
        general = [
            (self.tr("ID"), details.short_id),
            (self.tr("Image"), details.image),
            (self.tr("Created"), created),
            (self.tr("Command"), shlex.join(details.command)),
            (self.tr("State"), state.status),
            (self.tr("Exit code"), str(state.exit_code)),
            (self.tr("Restart policy"), details.restart_policy),
            (self.tr("TTY"), self.tr("yes") if details.tty else self.tr("no")),
        ]
        if state.health:
            general.insert(5, (self.tr("Health"), state.health))
        ports = [
            (
                f"{p.private_port}/{p.protocol}",
                f"{p.host_ip or '0.0.0.0'}:{p.public_port} → {p.private_port}/{p.protocol}",
            )
            for p in details.ports
            if p.public_port
        ] or [(self.tr("(none published)"), "")]
        env = [(k, v) for k, _, v in (item.partition("=") for item in details.env)]
        mounts = [
            (
                f"{m.type}  {m.name or m.source}",
                f"{m.destination}  ({'rw' if m.read_write else 'ro'})",
            )
            for m in details.mounts
        ]
        networks = [
            (
                n.name,
                self.tr("{address}/{prefix}   gw {gateway}").format(
                    address=n.ip_address, prefix=n.prefix_len, gateway=n.gateway
                ),
            )
            for n in details.networks
        ]
        labels = sorted(details.labels.items())
        sections: list[tuple[str, str, list[tuple[str, str]]]] = [
            ("General", self.tr("General"), general),
            ("Ports", self.tr("Ports"), ports),
            ("Environment", self.tr("Environment"), env),
            ("Mounts", self.tr("Mounts"), mounts),
            ("Networks", self.tr("Networks"), networks),
            ("Labels", self.tr("Labels"), labels),
        ]
        for name, title, rows in sections:
            top = QTreeWidgetItem([title, ""])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for key, value in rows:
                top.addChild(QTreeWidgetItem([key, value]))
            self.addTopLevelItem(top)
            top.setExpanded(name in _EXPANDED)
