import pytest

from anchorage.ui.containers import filter as filter_module
from anchorage.ui.containers.list_page import ContainersPage
from anchorage.ui.context import AppContext
from tests.core.fakes import FakeEngine
from tests.ui.test_containers_page import seeded, visible


# invalidateFilter is deprecated on Qt 6.10+, where the legacy path only runs in this test.
@pytest.mark.filterwarnings("ignore:.*invalidateFilter.*:DeprecationWarning")
@pytest.mark.parametrize("has_filter_change", [True, False])
def test_text_filter_on_both_qt_paths(
    qtbot,
    context: AppContext,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
    has_filter_change: bool,
) -> None:
    if has_filter_change and not filter_module.HAS_FILTER_CHANGE:
        pytest.skip("Qt older than 6.10 has no endFilterChange")
    # False exercises the invalidateFilter path used on Qt older than 6.10.
    monkeypatch.setattr(filter_module, "HAS_FILTER_CHANGE", has_filter_change)
    seeded(engine)
    page = ContainersPage(context.containers)
    qtbot.addWidget(page)
    context.containers.refresh()
    page.proxy.set_text("nginx")
    assert visible(page) == [("pulse", ["pulse-nginx-1"])]
    page.proxy.set_text("")
    assert len(visible(page)) == 3
    page.proxy.set_running_only(True)
    assert visible(page) == [("pulse", ["pulse-nginx-1"]), ("Standalone", ["solo"])]
    page.proxy.set_running_only(False)
    page.proxy.set_project("acme")
    assert visible(page) == [("acme", ["api"])]
