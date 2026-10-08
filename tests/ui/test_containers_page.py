from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPalette
from PySide6.QtWidgets import QStyleOptionViewItem

from anchorage.core.containers import ID_ROLE, KIND_ROLE
from anchorage.docker.models import PortBinding
from anchorage.ui.containers.delegate import port_spans
from anchorage.ui.containers.list_page import ContainersPage, enabled_actions
from anchorage.ui.context import AppContext
from tests.core.fakes import FakeEngine, make_container


def visible(page: ContainersPage) -> list[tuple[str, list[str]]]:
    proxy = page.proxy
    out = []
    for row in range(proxy.rowCount()):
        group = proxy.index(row, 0)
        children = [
            proxy.index(c, 0, group).data(Qt.ItemDataRole.DisplayRole)
            for c in range(proxy.rowCount(group))
        ]
        out.append((group.data(Qt.ItemDataRole.DisplayRole), children))
    return out


def seeded(engine: FakeEngine) -> None:
    engine.add(
        make_container("pulse-nginx-1", project="pulse", service="nginx", image="nginx:alpine"),
        make_container("pulse-db-1", project="pulse", service="db", state="exited"),
        make_container("api", project="acme", state="exited"),
        make_container("solo"),
    )


def test_page_lists_groups_and_expands(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    assert visible(page) == [
        ("acme", ["api"]),
        ("pulse", ["pulse-db-1", "pulse-nginx-1"]),
        ("Standalone", ["solo"]),
    ]
    assert page.tree.isExpanded(page.proxy.index(1, 0))
    page.resize(900, 600)
    page.show()
    page.tree.grab()


def test_filter_matches_name_image_project_and_service(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.filter_edit.setText("nginx")
    assert visible(page) == [("pulse", ["pulse-nginx-1"])]
    page.filter_edit.setText("PULSE")
    assert visible(page) == [("pulse", ["pulse-db-1", "pulse-nginx-1"])]
    page.filter_edit.setText("db")
    assert visible(page) == [("pulse", ["pulse-db-1"])]
    page.filter_edit.setText("")
    assert len(visible(page)) == 3


def test_running_only_hides_stopped_groups(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.running_only.setChecked(True)
    assert visible(page) == [("pulse", ["pulse-nginx-1"]), ("Standalone", ["solo"])]


def test_click_on_container_emits_activated(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    group = page.proxy.index(1, 0)
    child = page.proxy.index(1, 0, group)
    assert child.data(KIND_ROLE) == "container"
    page.tree.clicked.emit(child)
    assert activated == [child.data(ID_ROLE)]
    page.tree.clicked.emit(group)
    assert len(activated) == 1
    page.tree.setCurrentIndex(child)
    assert page.selected_container_id() == child.data(ID_ROLE)


def test_context_menu_actions_follow_state(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    requested: list[tuple[str, str]] = []
    page.action_requested.connect(lambda action, cid: requested.append((action, cid)))
    running = next(c for c in context.containers.containers() if c.name == "solo")
    stopped = next(c for c in context.containers.containers() if c.name == "api")
    menu = page.menu_for(running.id)
    actions = {a.text(): a for a in menu.actions()}
    assert actions["Start"].isEnabled() is False
    assert actions["Stop"].isEnabled() is True
    assert actions["Open shell"].isEnabled() is True
    actions["Stop"].trigger()
    assert requested == [("stop", running.id)]
    menu = page.menu_for(stopped.id)
    actions = {a.text(): a for a in menu.actions()}
    assert actions["Start"].isEnabled() is True
    assert actions["Open shell"].isEnabled() is False
    assert enabled_actions("running", True) == set()


def test_empty_state_replaces_tree(qtbot, context: AppContext) -> None:
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    page.set_empty("Docker Engine is not running", "Start the docker service")
    assert page.stack.currentWidget() is page.empty
    assert page.empty.title.text() == "Docker Engine is not running"
    page.clear_empty()
    assert page.stack.currentWidget() is page.tree


def test_refresh_button_emits(qtbot, context: AppContext) -> None:
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    fired: list[bool] = []
    page.refresh_requested.connect(lambda: fired.append(True))
    page.refresh_button.click()
    assert fired == [True]


def test_sort_and_proxy_do_not_lose_roles(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    index: QModelIndex = page.proxy.index(0, 0)
    assert index.data(KIND_ROLE) == "group"


def release(point) -> QMouseEvent:  # type: ignore[no-untyped-def]
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(point),
        QPointF(point),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def ports_page(qtbot, context: AppContext, engine: FakeEngine):  # type: ignore[no-untyped-def]
    c = make_container(
        "web",
        ports=(PortBinding(80, "tcp", 8080, "0.0.0.0"), PortBinding(443, "tcp", 8443, "0.0.0.0")),
    )
    engine.add(c)
    opened: list[str] = []
    page = ContainersPage(context.containers, open_url=opened.append)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.resize(900, 600)
    page.show()
    qtbot.waitExposed(page)
    index = page.proxy.index(0, 0, page.proxy.index(0, 0))
    return page, c, index, opened


def option_for(page: ContainersPage, index) -> QStyleOptionViewItem:  # type: ignore[no-untyped-def]
    option = QStyleOptionViewItem()
    option.rect = page.tree.visualRect(index)
    option.font = page.tree.font()
    return option


def test_clicking_a_published_port_opens_it(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page, c, index, opened = ports_page(qtbot, context, engine)
    option = option_for(page, index)
    spans = port_spans(c.ports, option.rect, page.tree.fontMetrics())
    assert len(spans) == 2
    handled = page.delegate.editorEvent(release(spans[1][0].center()), page.proxy, option, index)
    assert handled is True
    assert opened == ["http://localhost:8443"]
    page.delegate.editorEvent(release(spans[0][0].center()), page.proxy, option, index)
    assert opened[-1] == "http://localhost:8080"


def test_click_elsewhere_on_row_opens_nothing_and_activates(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    page, c, index, opened = ports_page(qtbot, context, engine)
    option = option_for(page, index)
    name_point = option.rect.topLeft() + QPoint(60, 12)
    assert page.delegate.editorEvent(release(name_point), page.proxy, option, index) is False
    assert opened == []
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    qtbot.mouseClick(
        page.tree.viewport(), Qt.MouseButton.LeftButton, pos=page.tree.visualRect(index).center()
    )
    assert activated == [c.id]
    assert opened == []


def test_real_click_on_port_opens_url(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page, c, index, opened = ports_page(qtbot, context, engine)
    rect = page.tree.visualRect(index)
    spans = port_spans(c.ports, rect, page.tree.fontMetrics())
    qtbot.mouseClick(page.tree.viewport(), Qt.MouseButton.LeftButton, pos=spans[0][0].center())
    assert opened == ["http://localhost:8080"]


def test_port_click_does_not_also_open_the_detail_page(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    page, c, index, opened = ports_page(qtbot, context, engine)
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    spans = port_spans(c.ports, page.tree.visualRect(index), page.tree.fontMetrics())
    qtbot.mouseClick(page.tree.viewport(), Qt.MouseButton.LeftButton, pos=spans[0][0].center())
    assert opened == ["http://localhost:8080"]
    assert activated == []
    qtbot.mouseClick(
        page.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=page.tree.visualRect(index).topLeft() + QPoint(60, 12),
    )
    assert activated == [c.id]


def test_enter_opens_the_container(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page, c, index, _ = ports_page(qtbot, context, engine)
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    page.tree.setCurrentIndex(index)
    qtbot.keyClick(page.tree, Qt.Key.Key_Return)
    assert activated == [c.id]
    page.tree.setCurrentIndex(page.proxy.index(0, 0))
    qtbot.keyClick(page.tree, Qt.Key.Key_Return)
    assert activated == [c.id]


def test_paused_container_cannot_open_a_shell() -> None:
    assert "shell" not in enabled_actions("paused", False)
    assert {"stop", "restart", "remove"} <= enabled_actions("paused", False)
    assert "shell" in enabled_actions("running", False)


def test_context_menu_is_deleted_after_use(qtbot, context: AppContext, engine: FakeEngine) -> None:
    import shiboken6
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    page, _c, index, _ = ports_page(qtbot, context, engine)
    seen: list[QMenu] = []

    def close_popup() -> None:
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu):
            seen.append(popup)
            popup.close()

    QTimer.singleShot(200, close_popup)
    page._on_context_menu(page.tree.visualRect(index).center())
    assert len(seen) == 1
    qtbot.waitUntil(lambda: not shiboken6.isValid(seen[0]), timeout=2000)


def test_set_project_filter_shows_only_that_project(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.set_project_filter("pulse")
    assert page.filter_edit.text() == "pulse"
    assert [name for name, _ in visible(page)] == ["pulse"]


def test_project_filter_is_exact_until_the_user_types(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    engine.add(make_container("pulse-impostor"))
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.set_project_filter("pulse")
    assert [name for name, _ in visible(page)] == ["pulse"]
    page.filter_edit.setText("pul")
    assert len(visible(page)) == 2
    names = [c for _, children in visible(page) for c in children]
    assert "pulse-impostor" in names
    assert "pulse-nginx-1" in names
    page.filter_edit.clear()
    assert page.proxy.rowCount() == 3


def test_set_project_filter_unchecks_running_only(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.running_only.setChecked(True)
    page.set_project_filter("pulse")
    assert not page.running_only.isChecked()
    children = [c for _, kids in visible(page) for c in kids]
    assert "pulse-db-1" in children


def test_group_row_spans_full_width_and_branch_strip_is_plain(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.resize(900, 600)
    page.show()
    group = page.proxy.index(1, 0)
    child = page.proxy.index(0, 0, group)
    assert not page.tree.rootIsDecorated()
    assert page.tree.visualRect(group).left() == 0
    image = page.tree.viewport().grab().toImage()
    rect = page.tree.visualRect(child)
    base = page.tree.palette().color(QPalette.ColorRole.Base).rgb()
    y = rect.center().y()
    strip = [image.pixel(x, y) for x in range(1, rect.left() - 1)]
    assert strip and all(pixel == base for pixel in strip)


def test_click_on_group_toggles_it(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    group = page.proxy.index(1, 0)
    assert page.tree.isExpanded(group)
    page.tree.clicked.emit(group)
    assert not page.tree.isExpanded(group)
    assert page.collapsed == {"pulse"}
    page.tree.clicked.emit(group)
    assert page.tree.isExpanded(group)
    assert page.collapsed == set()
    assert activated == []


def test_collapsed_group_survives_refresh_and_filter(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    group = page.proxy.index(1, 0)
    page.tree.clicked.emit(group)
    context.containers.refresh()
    assert not page.tree.isExpanded(page.proxy.index(1, 0))
    assert page.tree.isExpanded(page.proxy.index(0, 0))
    page.filter_edit.setText("pulse")
    assert page.tree.isExpanded(page.proxy.index(0, 0))
    assert page.collapsed == {"pulse"}
    page.filter_edit.setText("")
    assert not page.tree.isExpanded(page.proxy.index(1, 0))
    assert page.tree.isExpanded(page.proxy.index(0, 0))
    assert page.tree.isExpanded(page.proxy.index(2, 0))


def test_project_crumb_opens_a_collapsed_group(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.tree.clicked.emit(page.proxy.index(1, 0))
    assert page.collapsed == {"pulse"}
    page.set_project_filter("pulse")
    assert page.proxy.rowCount() == 1
    assert page.tree.isExpanded(page.proxy.index(0, 0))
    assert page.collapsed == set()


def test_enter_opens_container_and_enter_on_group_toggles_it(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.show()
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    group = page.proxy.index(1, 0)
    child = page.proxy.index(1, 0, group)
    page.tree.setCurrentIndex(child)
    qtbot.keyClick(page.tree, Qt.Key.Key_Return)
    assert activated == [child.data(ID_ROLE)]
    page.tree.setCurrentIndex(group)
    qtbot.keyClick(page.tree, Qt.Key.Key_Enter)
    assert activated == [child.data(ID_ROLE)]
    assert not page.tree.isExpanded(group)


def test_activated_signal_is_ignored(qtbot, context: AppContext, engine: FakeEngine) -> None:
    """Single-click desktops emit clicked and activated for one click; only clicked counts."""
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    activated: list[str] = []
    page.container_activated.connect(activated.append)
    group = page.proxy.index(1, 0)
    child = page.proxy.index(1, 0, group)
    page.tree.activated.emit(child)
    assert activated == []
    page.tree.clicked.emit(child)
    page.tree.activated.emit(child)
    assert activated == [child.data(ID_ROLE)]


def test_keyboard_collapse_survives_refresh(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.show()
    group = page.proxy.index(1, 0)
    page.tree.setCurrentIndex(group)
    qtbot.keyClick(page.tree, Qt.Key.Key_Left)
    assert not page.tree.isExpanded(group)
    assert page.collapsed == {"pulse"}
    context.containers.refresh()
    assert not page.tree.isExpanded(page.proxy.index(1, 0))
    page.tree.setCurrentIndex(page.proxy.index(1, 0))
    qtbot.keyClick(page.tree, Qt.Key.Key_Right)
    assert page.tree.isExpanded(page.proxy.index(1, 0))
    assert page.collapsed == set()
