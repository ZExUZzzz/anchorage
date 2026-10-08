import pytest

from anchorage.core.containers import ContainerStore
from anchorage.core.images import ImageStore
from anchorage.core.networks import NetworkStore
from anchorage.core.volumes import VolumeStore
from anchorage.docker.errors import DockerError
from tests.core.fakes import DeferredRunner, FakeEngine


@pytest.mark.parametrize("store_class", [ContainerStore, ImageStore, VolumeStore, NetworkStore])
def test_failure_of_superseded_refresh_is_ignored(store_class) -> None:
    engine = FakeEngine()
    runner = DeferredRunner()
    store = store_class(engine, runner)
    failures: list[object] = []
    store.refresh_failed.connect(failures.append)
    store.refresh()
    store.refresh()
    (_, _, fail_old), (fn_new, ok_new, _) = runner.pending
    runner.pending.clear()
    ok_new(fn_new())
    fail_old(DockerError("boom"))
    assert failures == []


@pytest.mark.parametrize("store_class", [ContainerStore, ImageStore, VolumeStore, NetworkStore])
def test_failure_of_current_refresh_is_reported(store_class) -> None:
    runner = DeferredRunner()
    store = store_class(FakeEngine(), runner)
    failures: list[object] = []
    store.refresh_failed.connect(failures.append)
    store.refresh()
    ((_, _, fail),) = runner.pending
    error = DockerError("boom")
    fail(error)
    assert failures == [error]
