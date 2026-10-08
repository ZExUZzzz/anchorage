"""Inspect output as a two-column tree."""

from __future__ import annotations

import shlex

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from anchorage.docker.models import ContainerDetails

_EXPANDED = {"General", "Ports", "Mounts", "Networks"}


class DetailsTree(QTreeWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Key", "Value"])
        self.setColumnWidth(0, 260)
        self.setAlternatingRowColors(True)

    def show_details(self, details: ContainerDetails) -> None:
        self.clear()
        state = details.state
        created = (
            details.created.astimezone().strftime("%Y-%m-%d %H:%M:%S") if details.created else ""
        )
        general = [
            ("ID", details.short_id),
            ("Image", details.image),
            ("Created", created),
            ("Command", shlex.join(details.command)),
            ("State", state.status),
            ("Exit code", str(state.exit_code)),
            ("Restart policy", details.restart_policy),
            ("TTY", "yes" if details.tty else "no"),
        ]
        if state.health:
            general.insert(5, ("Health", state.health))
        ports = [
            (
                f"{p.private_port}/{p.protocol}",
                f"{p.host_ip or '0.0.0.0'}:{p.public_port} → {p.private_port}/{p.protocol}",
            )
            for p in details.ports
            if p.public_port
        ] or [("(none published)", "")]
        env = [(k, v) for k, _, v in (item.partition("=") for item in details.env)]
        mounts = [
            (
                f"{m.type}  {m.name or m.source}",
                f"{m.destination}  ({'rw' if m.read_write else 'ro'})",
            )
            for m in details.mounts
        ]
        networks = [
            (n.name, f"{n.ip_address}/{n.prefix_len}   gw {n.gateway}") for n in details.networks
        ]
        labels = sorted(details.labels.items())
        sections: list[tuple[str, list[tuple[str, str]]]] = [
            ("General", general),
            ("Ports", ports),
            ("Environment", env),
            ("Mounts", mounts),
            ("Networks", networks),
            ("Labels", labels),
        ]
        for name, rows in sections:
            top = QTreeWidgetItem([name, ""])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for key, value in rows:
                top.addChild(QTreeWidgetItem([key, value]))
            self.addTopLevelItem(top)
            top.setExpanded(name in _EXPANDED)
