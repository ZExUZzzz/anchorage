"""Typed Docker Engine client and the EngineAPI protocol it implements."""

from __future__ import annotations

from collections.abc import Iterator
from types import TracebackType
from typing import Any, Generic, Protocol, TypeVar
from urllib.parse import quote

from anchorage.docker.models import (
    Container,
    ContainerDetails,
    ContainerStats,
    Event,
    Image,
    ImageDetails,
    ImageLayer,
    LogLine,
    Network,
    PruneResult,
    PullProgress,
    VersionInfo,
    Volume,
)
from anchorage.docker.streams import iter_json_lines, iter_log_lines
from anchorage.docker.transport import Transport, discover_socket_path

T = TypeVar("T")

_SLACK = 15
_PRUNE_TIMEOUT = 300.0


class Closable(Protocol):
    """What a ``Stream`` needs from its source; any backend can provide it."""

    @property
    def closed(self) -> bool: ...

    def close(self) -> None: ...


class Stream(Generic[T]):
    """Iterator over a streaming endpoint. ``close()`` is safe from any thread."""

    def __init__(self, response: Closable, items: Iterator[T]) -> None:
        self._response = response
        self._items = items

    def __iter__(self) -> Stream[T]:
        return self

    def __next__(self) -> T:
        if self.closed:
            raise StopIteration
        try:
            item = next(self._items)
        except BaseException:
            self.close()
            raise
        if self.closed:
            raise StopIteration
        return item

    @property
    def closed(self) -> bool:
        return self._response.closed

    def close(self) -> None:
        self._response.close()

    def __enter__(self) -> Stream[T]:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class EngineAPI(Protocol):
    """Everything the application needs from a Docker Engine."""

    @property
    def socket_path(self) -> str: ...

    def ping(self) -> None: ...
    def version(self) -> VersionInfo: ...

    def list_containers(self, *, all: bool = True) -> list[Container]: ...
    def inspect_container(self, container_id: str) -> ContainerDetails: ...
    def start_container(self, container_id: str) -> None: ...
    def stop_container(self, container_id: str, *, timeout: int = 10) -> None: ...
    def restart_container(self, container_id: str, *, timeout: int = 10) -> None: ...
    def remove_container(
        self, container_id: str, *, force: bool = False, volumes: bool = False
    ) -> None: ...

    def list_images(self) -> list[Image]: ...
    def inspect_image(self, reference: str) -> ImageDetails: ...
    def image_history(self, reference: str) -> list[ImageLayer]: ...
    def remove_image(self, reference: str, *, force: bool = False) -> None: ...
    def prune_images(self, *, dangling_only: bool = True) -> PruneResult: ...

    def list_volumes(self) -> list[Volume]: ...
    def remove_volume(self, name: str, *, force: bool = False) -> None: ...
    def prune_volumes(self) -> PruneResult: ...

    def list_networks(self) -> list[Network]: ...
    def remove_network(self, network_id: str) -> None: ...
    def prune_networks(self) -> PruneResult: ...

    def events(self) -> Stream[Event]: ...
    def logs(
        self,
        container_id: str,
        *,
        tty: bool,
        tail: int | None = 1000,
        timestamps: bool = True,
    ) -> Stream[LogLine]: ...
    def stats(self, container_id: str) -> Stream[ContainerStats]: ...
    def pull_image(self, repository: str, tag: str = "latest") -> Stream[PullProgress]: ...


def _ref(value: str) -> str:
    return quote(value, safe="")


class DockerClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    @classmethod
    def from_env(cls) -> DockerClient:
        return cls(Transport(discover_socket_path()))

    @property
    def socket_path(self) -> str:
        return self._transport.socket_path

    def _get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self._transport.request("GET", path, query=query).json()

    def ping(self) -> None:
        self._transport.request("GET", "/_ping")

    def version(self) -> VersionInfo:
        return VersionInfo.from_api(self._get("/version"))

    def list_containers(self, *, all: bool = True) -> list[Container]:
        return [Container.from_api(item) for item in self._get("/containers/json", {"all": all})]

    def inspect_container(self, container_id: str) -> ContainerDetails:
        return ContainerDetails.from_api(self._get(f"/containers/{_ref(container_id)}/json"))

    def start_container(self, container_id: str) -> None:
        self._transport.request("POST", f"/containers/{_ref(container_id)}/start")

    def stop_container(self, container_id: str, *, timeout: int = 10) -> None:
        self._transport.request(
            "POST",
            f"/containers/{_ref(container_id)}/stop",
            query={"t": timeout},
            timeout=timeout + _SLACK,
        )

    def restart_container(self, container_id: str, *, timeout: int = 10) -> None:
        self._transport.request(
            "POST",
            f"/containers/{_ref(container_id)}/restart",
            query={"t": timeout},
            timeout=timeout + _SLACK,
        )

    def remove_container(
        self, container_id: str, *, force: bool = False, volumes: bool = False
    ) -> None:
        self._transport.request(
            "DELETE", f"/containers/{_ref(container_id)}", query={"force": force, "v": volumes}
        )

    def list_images(self) -> list[Image]:
        return [Image.from_api(item) for item in self._get("/images/json")]

    def inspect_image(self, reference: str) -> ImageDetails:
        return ImageDetails.from_api(self._get(f"/images/{_ref(reference)}/json"))

    def image_history(self, reference: str) -> list[ImageLayer]:
        return [
            ImageLayer.from_api(item) for item in self._get(f"/images/{_ref(reference)}/history")
        ]

    def remove_image(self, reference: str, *, force: bool = False) -> None:
        self._transport.request("DELETE", f"/images/{_ref(reference)}", query={"force": force})

    def prune_images(self, *, dangling_only: bool = True) -> PruneResult:
        filters = {"dangling": ["true" if dangling_only else "false"]}
        response = self._transport.request(
            "POST", "/images/prune", query={"filters": filters}, timeout=_PRUNE_TIMEOUT
        )
        return PruneResult.from_api(response.json() or {})

    def list_volumes(self) -> list[Volume]:
        payload = self._get("/volumes") or {}
        return [Volume.from_api(item) for item in payload.get("Volumes") or []]

    def remove_volume(self, name: str, *, force: bool = False) -> None:
        self._transport.request("DELETE", f"/volumes/{_ref(name)}", query={"force": force})

    def prune_volumes(self) -> PruneResult:
        response = self._transport.request("POST", "/volumes/prune", timeout=_PRUNE_TIMEOUT)
        return PruneResult.from_api(response.json() or {})

    def list_networks(self) -> list[Network]:
        return [Network.from_api(item) for item in self._get("/networks") or []]

    def remove_network(self, network_id: str) -> None:
        self._transport.request("DELETE", f"/networks/{_ref(network_id)}")

    def prune_networks(self) -> PruneResult:
        response = self._transport.request("POST", "/networks/prune", timeout=_PRUNE_TIMEOUT)
        return PruneResult.from_api(response.json() or {})

    def events(self) -> Stream[Event]:
        response = self._transport.stream(
            "GET",
            "/events",
            query={"filters": {"type": ["container", "image", "volume", "network"]}},
        )
        return Stream(response, (Event.from_api(d) for d in iter_json_lines(response.chunks())))

    def logs(
        self,
        container_id: str,
        *,
        tty: bool,
        tail: int | None = 1000,
        timestamps: bool = True,
    ) -> Stream[LogLine]:
        response = self._transport.stream(
            "GET",
            f"/containers/{_ref(container_id)}/logs",
            query={
                "follow": True,
                "stdout": True,
                "stderr": True,
                "timestamps": timestamps,
                "tail": "all" if tail is None else tail,
            },
        )
        lines = iter_log_lines(response.chunks(), tty=tty, timestamps=timestamps)
        return Stream(response, lines)

    def stats(self, container_id: str) -> Stream[ContainerStats]:
        response = self._transport.stream(
            "GET", f"/containers/{_ref(container_id)}/stats", query={"stream": True}
        )
        samples = (ContainerStats.from_api(d) for d in iter_json_lines(response.chunks()))
        return Stream(response, samples)

    def pull_image(self, repository: str, tag: str = "latest") -> Stream[PullProgress]:
        response = self._transport.stream(
            "POST", "/images/create", query={"fromImage": repository, "tag": tag}
        )
        progress = (PullProgress.from_api(d) for d in iter_json_lines(response.chunks()))
        return Stream(response, progress)
