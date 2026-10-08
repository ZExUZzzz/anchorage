"""Application-wide services the window binds to."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QThreadPool

from anchorage.core.containers import ContainerStore
from anchorage.core.engine import EngineService
from anchorage.core.images import ImageStore
from anchorage.core.networks import NetworkStore
from anchorage.core.volumes import VolumeStore
from anchorage.core.workers import TaskRunner
from anchorage.docker.client import EngineAPI


@dataclass
class AppContext:
    api: EngineAPI
    runner: TaskRunner
    engine: EngineService
    containers: ContainerStore
    images: ImageStore
    volumes: VolumeStore
    networks: NetworkStore
    _shut_down: bool | None = field(default=None, init=False, repr=False)

    @classmethod
    def build(
        cls, api: EngineAPI, *, inline: bool = False, parent: QObject | None = None
    ) -> AppContext:
        runner = TaskRunner(parent, inline=inline)
        engine = EngineService(api, runner, parent=parent)
        containers = ContainerStore(api, runner, engine, parent=parent)
        images = ImageStore(api, runner, engine, parent=parent)
        volumes = VolumeStore(api, runner, engine, containers, parent=parent)
        networks = NetworkStore(api, runner, engine, containers, parent=parent)
        return cls(api, runner, engine, containers, images, volumes, networks)

    def shutdown(self, timeout_ms: int = 2000) -> bool:
        """Stop every worker; False when one missed its deadline and is still running.

        Idempotent: the window's close and the application's ``aboutToQuit`` both call it,
        and later calls return the first result without waiting again.
        """
        if self._shut_down is not None:
            return self._shut_down
        pulls_stopped = self.images.shutdown(timeout_ms)
        engine_stopped = self.engine.stop()
        self.runner.close()
        pool_idle = QThreadPool.globalInstance().waitForDone(timeout_ms)
        self._shut_down = pulls_stopped and engine_stopped and pool_idle
        return self._shut_down
