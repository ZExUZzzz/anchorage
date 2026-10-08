from PySide6.QtCore import Qt

from anchorage.docker.errors import Conflict
from anchorage.docker.models import PullProgress
from anchorage.ui.context import AppContext
from anchorage.ui.images.page import ImagesPage
from anchorage.ui.images.pull_dialog import PullDialog
from tests.core.fakes import FakeEngine, make_image


def seeded(engine: FakeEngine) -> None:
    engine.images = [
        make_image(("nginx:alpine", "nginx:1.27-alpine"), size=48_300_000),
        make_image(("redis:7-alpine",), size=41_500_000),
        make_image((), size=801_000_000),
    ]


def column(page: ImagesPage, col: int) -> list[str]:
    return [
        page.proxy.index(r, col).data(Qt.ItemDataRole.DisplayRole)
        for r in range(page.proxy.rowCount())
    ]


def test_table_lists_rows_sorted_and_filtered(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    context.images.refresh()
    assert column(page, 0) == ["<none>", "nginx", "nginx", "redis"]
    page.table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
    assert column(page, 0)[0] == "<none>"
    page.filter_edit.setText("redis")
    assert column(page, 0) == ["redis"]
    page.filter_edit.setText("")
    page.resize(900, 600)
    page.show()
    page.table.grab()


def test_selection_enables_remove_and_survives_refresh(
    qtbot, context: AppContext, engine: FakeEngine
) -> None:
    seeded(engine)
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    context.images.refresh()
    assert page.remove_button.isEnabled() is False
    assert page.selected_reference() is None
    row = column(page, 0).index("redis")
    page.table.selectRow(row)
    assert page.selected_reference() == "redis:7-alpine"
    assert page.remove_button.isEnabled() is True
    removed: list[str] = []
    page.remove_requested.connect(removed.append)
    page.remove_button.click()
    assert removed == ["redis:7-alpine"]
    context.images.refresh()
    assert page.selected_reference() == "redis:7-alpine"


def test_pull_dialog_parses_reference(qtbot) -> None:
    dialog = PullDialog()
    qtbot.addWidget(dialog)
    dialog.edit.setText("ghcr.io/acme/api:1.4.2")
    assert dialog.reference() == ("ghcr.io/acme/api", "1.4.2")
    dialog.edit.setText("  nginx  ")
    assert dialog.reference() == ("nginx", "latest")
    dialog.edit.setText("")
    assert dialog.reference() is None


def test_pull_panel_tracks_job(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    job = context.images.pull("nginx", "alpine")
    page.show_pull(job, "nginx:alpine")
    assert not page.panel.isHidden()
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    feed = engine.pull_feeds[0]
    feed.put(PullProgress(status="Pulling from library/nginx"))
    feed.put(PullProgress(status="Downloading", layer_id="aa", current=10, total=40))
    feed.put(PullProgress(status="Pull complete", layer_id="aa"))
    feed.put(PullProgress(status="Extracting", layer_id="bb", current=5, total=10))
    qtbot.waitUntil(lambda: "bb" in page.panel.rows, timeout=2000)
    _, bar_aa, status_aa = page.panel.rows["aa"]
    assert bar_aa.value() == 100
    assert status_aa.text() == "Pull complete"
    _, bar_bb, _ = page.panel.rows["bb"]
    assert bar_bb.value() == 50
    assert "nginx:alpine" in page.panel.title.text()
    feed.end()
    qtbot.waitUntil(lambda: job.done, timeout=2000)
    assert "complete" in page.panel.title.text().lower()
    qtbot.waitUntil(lambda: page.panel.isHidden(), timeout=5000)


def test_pull_panel_cancel_and_error(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    job = context.images.pull("nginx")
    page.show_pull(job, "nginx:latest")
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    page.panel.cancel_button.click()
    qtbot.waitUntil(lambda: job.done, timeout=2000)
    assert job.cancelled
    assert "cancel" in page.panel.title.text().lower()


def test_prune_and_refresh_buttons(qtbot, context: AppContext) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    fired: list[str] = []
    page.prune_requested.connect(lambda: fired.append("prune"))
    page.refresh_requested.connect(lambda: fired.append("refresh"))
    page.prune_button.click()
    page.refresh_button.click()
    assert fired == ["prune", "refresh"]


def test_pull_button_disabled_while_running(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    job = context.images.pull("nginx")
    page.show_pull(job, "nginx:latest")
    assert page.pull_button.isEnabled() is False
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    engine.pull_feeds[0].end()
    qtbot.waitUntil(lambda: page.pull_button.isEnabled(), timeout=2000)


def test_second_pull_cancels_first(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    first = context.images.pull("nginx")
    page.show_pull(first, "nginx:latest")
    first.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    second = context.images.pull("redis")
    page.show_pull(second, "redis:latest")
    qtbot.waitUntil(lambda: engine.pull_feeds[0].closed, timeout=2000)
    assert first.cancelled
    assert "redis" in page.panel.title.text()
    assert page.pull_button.isEnabled() is False


def test_pull_failure_shown(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    job = context.images.pull("nope")
    page.show_pull(job, "nope:latest")
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    engine.pull_feeds[0].fail(Conflict("manifest unknown", 409))
    qtbot.waitUntil(lambda: job.done, timeout=2000)
    assert "FAILED" in page.panel.title.text()
    assert "manifest unknown" in page.panel.title.text()


def test_bind_done_job_finishes_immediately(qtbot, context: AppContext, engine: FakeEngine) -> None:
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    job = context.images.pull("nginx")
    job.start()
    qtbot.waitUntil(lambda: len(engine.pull_feeds) == 1, timeout=2000)
    engine.pull_feeds[0].end()
    qtbot.waitUntil(lambda: job.done, timeout=2000)
    page.show_pull(job, "nginx:latest")
    assert "complete" in page.panel.title.text().lower()
    assert page.pull_button.isEnabled() is True


def test_filtered_out_selection_is_kept(qtbot, context: AppContext, engine: FakeEngine) -> None:
    seeded(engine)
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    context.images.refresh()
    page.table.selectRow(column(page, 0).index("redis"))
    page.filter_edit.setText("nginx")
    context.images.refresh()
    page.filter_edit.setText("")
    context.images.refresh()
    assert page.selected_reference() == "redis:7-alpine"


def test_clicking_id_cell_copies_image_id(qtbot, context: AppContext, engine: FakeEngine) -> None:
    from PySide6.QtWidgets import QApplication

    seeded(engine)
    page = ImagesPage(context.images)
    qtbot.addWidget(page)
    context.images.refresh()
    copied: list[str] = []
    page.copied.connect(copied.append)
    row = column(page, 0).index("redis")
    page.table.clicked.emit(page.proxy.index(row, 2))
    assert QApplication.clipboard().text() == context.images.row("redis:7-alpine").image.id
    assert copied == ["Image ID copied"]
    page.table.clicked.emit(page.proxy.index(row, 0))
    assert len(copied) == 1
