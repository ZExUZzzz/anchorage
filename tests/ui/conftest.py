from collections.abc import Iterator

import pytest

from anchorage.ui.context import AppContext
from tests.core.fakes import FakeEngine


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def context(qtbot, engine: FakeEngine) -> Iterator[AppContext]:
    ctx = AppContext.build(engine, inline=True)
    yield ctx
    ctx.shutdown(timeout_ms=500)
