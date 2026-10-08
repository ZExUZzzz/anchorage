from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from anchorage.ui.context import AppContext
from anchorage.ui.resources.networks import NetworksPage
from anchorage.ui.resources.page import (
    MEMBERS_FILTER_THRESHOLD,
    DetailsCard,
    DetailsContent,
    Member,
)
from anchorage.ui.resources.volumes import VolumesPage
from tests.core.fakes import FakeEngine, make_container, make_network, make_volume


def seeded(engine: FakeEngine) -> None:
    engine.volumes = [make_volume("pulse_dbdata", project="pulse"), make_volume("orphan")]
    engine.networks = [
        make_network("pulse_default", project="pulse"),
        make_network("bridge", subnet="172.17.0.0/16"),
    ]
    engine.add(
        make_container(
            "pulse-db-1",
            project="pulse",
            volumes={"pulse_dbdata": "/var/lib/mysql"},
            networks={"pulse_default": "172.18.0.2"},
        ),
        *[
            make_container(f"web-{i}", networks={"pulse_default": f"172.18.0.{10 + i}"})
            for i in range(8)
        ],
    )


def ready(context: AppContext) -> None:
    context.containers.refresh()
    context.volumes.refresh()
    context.networks.refresh()


def column(page, col: int) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        page.proxy.index(r, col).data(Qt.ItemDataRole.DisplayRole)
        for r in range(page.proxy.rowCount())
    ]


def test_volumes_page_lists_and_shows_details(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    assert column(page, 0) == ["orphan", "pulse_dbdata"]
    assert page.remove_button.isEnabled() is False
    assert page.card.isHidden()
    page.table.selectRow(1)
    assert page.selected_key() == "pulse_dbdata"
    assert page.remove_button.isEnabled()
    assert not page.card.isHidden()
    assert page.card.title_label.text() == "pulse_dbdata"
    fields = page.card.field_values()
    assert fields["Mountpoint"].endswith("pulse_dbdata/_data")
    assert "pulse" in fields["Labels"]
    assert page.card.members_label.text() == "USED BY (1)"
    assert page.card.members_table.rowCount() == 1
    assert page.card.members_table.item(0, 0).text() == "pulse-db-1"
    assert page.card.members_table.item(0, 1).text() == "mounted at /var/lib/mysql"
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    page.card.members_table.cellClicked.emit(0, 0)
    db = next(c for c in context.containers.containers() if c.name == "pulse-db-1")
    assert activated == [db.id]
    page.resize(900, 700)
    page.show()
    page.grab()


def test_unused_volume_shows_no_members(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(0)
    assert page.card.members_label.text() == "USED BY (0)"
    assert page.card.members_table.rowCount() == 0
    assert not page.card.members_empty.isHidden()


def test_networks_page_members_filter_and_scroll(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = NetworksPage(context.networks)
    qtbot.addWidget(page)
    ready(context)
    assert column(page, 0) == ["bridge", "pulse_default"]
    assert column(page, 4) == ["0", "9"]
    page.table.selectRow(1)
    assert page.card.members_label.text() == "CONNECTED CONTAINERS (9)"
    assert page.card.members_table.rowCount() == 9
    assert not page.card.members_filter.isHidden()
    page.card.members_filter.setText("web-3")
    visible = [
        r
        for r in range(page.card.members_table.rowCount())
        if not page.card.members_table.isRowHidden(r)
    ]
    assert len(visible) == 1
    fields = page.card.field_values()
    assert fields["Subnet"].startswith("172.18.0.0/16")
    page.table.selectRow(0)
    assert page.card.members_filter.isHidden()
    assert page.card.members_table.rowCount() == 0
    assert MEMBERS_FILTER_THRESHOLD < 9


def test_selection_survives_refresh_and_removed_row_clears_card(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(1)
    context.volumes.refresh()
    assert page.selected_key() == "pulse_dbdata"
    engine.volumes = [v for v in engine.volumes if v.name != "pulse_dbdata"]
    context.volumes.refresh()
    assert page.selected_key() is None
    assert page.card.isHidden()
    assert page.remove_button.isEnabled() is False


def test_buttons_emit_intents(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    fired: list[str] = []
    page.remove_requested.connect(lambda name: fired.append(f"remove:{name}"))
    page.prune_requested.connect(lambda: fired.append("prune"))
    page.refresh_requested.connect(lambda: fired.append("refresh"))
    page.table.selectRow(0)
    page.remove_button.click()
    page.prune_button.click()
    page.refresh_button.click()
    assert fired == ["remove:orphan", "prune", "refresh"]
    page.filter_edit.setText("pulse")
    assert column(page, 0) == ["pulse_dbdata"]


def test_details_card_standalone(qtbot) -> None:
    card = DetailsCard()
    qtbot.addWidget(card)
    card.show_content(
        DetailsContent("t", [("K", "V")], "MEMBERS", [Member("id1", "a", "x", "running")])
    )
    assert card.field_values() == {"K": "V"}
    assert card.members_table.item(0, 2).text() == "running"
    card.clear()
    assert card.isHidden()


def test_large_network_card_stays_bounded(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    engine.add(
        *[
            make_container(f"many-{i}", networks={"pulse_default": f"172.18.1.{i}"})
            for i in range(60)
        ]
    )
    page = NetworksPage(context.networks)
    qtbot.addWidget(page)
    ready(context)
    page.resize(900, 700)
    page.show()
    page.table.selectRow(1)
    assert page.card.members_table.rowCount() == 69
    assert page.card.height() <= page.splitter.height() * 0.6 + 1
    assert page.table.height() > 100
    bar = page.card.members_table.verticalScrollBar()
    assert bar.maximum() > 0


def test_identical_refresh_keeps_card_and_members_filter(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = NetworksPage(context.networks)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(1)
    page.card.members_filter.setText("web-3")
    table = page.card.members_table
    hidden = [table.isRowHidden(r) for r in range(table.rowCount())]
    first = table.item(0, 0)
    context.containers.refresh()
    assert page.selected_key() == "pulse_default"
    assert page.card.members_filter.text() == "web-3"
    assert [table.isRowHidden(r) for r in range(table.rowCount())] == hidden
    assert table.item(0, 0) is first


def test_changed_content_keeps_filter_for_same_key(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = NetworksPage(context.networks)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(1)
    page.card.members_filter.setText("web-3")
    engine.add(make_container("web-new", networks={"pulse_default": "172.18.0.99"}))
    context.containers.refresh()
    assert page.card.members_label.text() == "CONNECTED CONTAINERS (10)"
    assert page.card.members_filter.text() == "web-3"
    table = page.card.members_table
    assert sum(not table.isRowHidden(r) for r in range(table.rowCount())) == 1


def test_deselected_row_stays_deselected_after_refresh(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(1)
    page.table.clearSelection()
    context.volumes.refresh()
    assert page.selected_key() is None
    assert page.card.isHidden()
    assert page.remove_button.isEnabled() is False


def test_volume_with_two_mounts_is_one_member(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    from dataclasses import replace

    engine.volumes = [make_volume("shared")]
    app = make_container("app", volumes={"shared": "/a"})
    engine.add(replace(app, mounts=(*app.mounts, replace(app.mounts[0], destination="/b"))))
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(0)
    assert page.card.members_label.text() == "USED BY (1)"
    extra = page.card.members_table.item(0, 1).text()
    assert "/a" in extra
    assert "/b" in extra


def test_filter_hiding_the_selection_keeps_it_for_later(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = VolumesPage(context.volumes)
    qtbot.addWidget(page)
    ready(context)
    page.table.selectRow(1)
    assert page.selected_key() == "pulse_dbdata"
    page.filter_edit.setText("zzz")
    assert page.card.isHidden()
    assert page.remove_button.isEnabled() is False
    context.volumes.refresh()
    assert page._selected == "pulse_dbdata"
    assert page.card.isHidden()
    page.filter_edit.setText("")
    assert page.selected_key() == "pulse_dbdata"
    assert not page.card.isHidden()
    assert page.card.title_label.text() == "pulse_dbdata"
    assert page.remove_button.isEnabled()


def test_networks_remove_disabled_for_builtin_and_connected(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    engine.networks.append(make_network("lonely"))
    page = NetworksPage(context.networks)
    qtbot.addWidget(page)
    ready(context)
    assert column(page, 0) == ["bridge", "lonely", "pulse_default"]
    page.table.selectRow(0)
    assert page.remove_button.isEnabled() is False
    assert page.remove_button.toolTip() == "Built-in network"
    page.table.selectRow(2)
    assert page.remove_button.isEnabled() is False
    assert page.remove_button.toolTip() == "Network has connected containers"
    page.table.selectRow(1)
    assert page.remove_button.isEnabled()
    assert page.remove_button.toolTip() == ""
    context.networks.refresh()
    assert page.remove_button.isEnabled()


def test_splitter_state_is_restored_from_settings(
    qtbot, context: AppContext, engine: FakeEngine, tmp_path
) -> None:
    from PySide6.QtCore import QSettings

    seeded(engine)
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    first = VolumesPage(context.volumes, settings=settings)
    qtbot.addWidget(first)
    first.resize(900, 700)
    first.show()
    first.splitter.setSizes([420, 180])
    first._save_splitter()
    settings.sync()
    expected = first.splitter.sizes()
    second = VolumesPage(context.volumes, settings=settings)
    qtbot.addWidget(second)
    second.resize(900, 700)
    second.show()
    assert second.splitter.sizes() == expected
    assert expected[0] > expected[1]


def test_row_delegate_drops_the_cell_focus_frame(qtbot) -> None:
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QTableView

    from anchorage.ui.widgets.row_delegate import RowDelegate

    model = QStandardItemModel()
    model.appendRow([QStandardItem("a")])
    table = QTableView()
    qtbot.addWidget(table)
    table.setModel(model)
    delegate = RowDelegate(table)
    option = QStyleOptionViewItem()
    option.state |= QStyle.StateFlag.State_HasFocus
    delegate.initStyleOption(option, model.index(0, 0))
    assert not option.state & QStyle.StateFlag.State_HasFocus


def members_card(qtbot, count: int = 3) -> DetailsCard:
    card = DetailsCard()
    qtbot.addWidget(card)
    members = [Member(f"id{i}", f"c{i}", "x", "running") for i in range(count)]
    card.show_content(DetailsContent("t", [("K", "V")], "MEMBERS", members))
    card.show()
    qtbot.waitExposed(card)
    return card


def test_members_table_enter_activates_current_row(qtbot) -> None:
    card = members_card(qtbot)
    table = card.members_table
    assert table.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    activated: list[str] = []
    card.container_activated.connect(activated.append)
    table.setFocus()
    table.selectRow(1)
    qtbot.keyClick(table, Qt.Key.Key_Return)
    qtbot.keyClick(table, Qt.Key.Key_Enter)
    assert activated == ["id1", "id1"]
    table.cellClicked.emit(2, 0)
    assert activated[-1] == "id2"


def test_members_table_enter_ignores_a_row_hidden_by_the_filter(qtbot) -> None:
    card = members_card(qtbot)
    table = card.members_table
    activated: list[str] = []
    card.container_activated.connect(activated.append)
    table.setFocus()
    table.selectRow(1)
    table.setRowHidden(1, True)
    qtbot.keyClick(table, Qt.Key.Key_Return)
    assert activated == []


def test_members_table_is_reached_by_tab(qtbot) -> None:
    card = members_card(qtbot, MEMBERS_FILTER_THRESHOLD + 1)
    chain = []
    widget = card.members_filter.nextInFocusChain()
    while widget is not card.members_filter:
        if widget.isVisibleTo(card) and widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
            chain.append(widget)
        widget = widget.nextInFocusChain()
    assert chain[:1] == [card.members_table]
