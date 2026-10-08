"""In-memory EngineAPI for core tests."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from anchorage.core.workers import TaskRunner, wrap_error
from anchorage.docker.client import Stream
from anchorage.docker.errors import DockerError, NotFound
from anchorage.docker.models import (
    COMPOSE_PROJECT_LABEL,
    COMPOSE_SERVICE_LABEL,
    Container,
    ContainerDetails,
    ContainerState,
    ContainerStats,
    Event,
    Image,
    ImageDetails,
    ImageLayer,
    LogLine,
    Mount,
    Network,
    PortBinding,
    PruneResult,
    PullProgress,
    Subnet,
    VersionInfo,
    Volume,
)

T = TypeVar("T")
_END = object()


class Feed(Generic[T]):
    """Thread-safe item source. Tests ``put`` items; a ``Stream`` consumes them."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(_END)

    def put(self, item: T) -> None:
        self._queue.put(item)

    def end(self) -> None:
        self._queue.put(_END)

    def fail(self, error: BaseException) -> None:
        self._queue.put(error)

    def __iter__(self) -> Iterator[T]:
        while True:
            item = self._queue.get()
            if item is _END:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def stream(self) -> Stream[T]:
        return Stream(self, iter(self))


def make_container(
    name: str,
    *,
    state: str = "running",
    status: str | None = None,
    project: str | None = None,
    service: str | None = None,
    image: str = "busybox:latest",
    container_id: str | None = None,
    ports: tuple[PortBinding, ...] = (),
    volumes: dict[str, str] | None = None,
    networks: dict[str, str] | None = None,
) -> Container:
    labels: dict[str, str] = {}
    if project:
        labels[COMPOSE_PROJECT_LABEL] = project
    if service:
        labels[COMPOSE_SERVICE_LABEL] = service
    return Container(
        id=container_id or (name * 8)[:64].ljust(64, "0"),
        name=name,
        image=image,
        image_id="sha256:" + "0" * 64,
        command="sh",
        state=state,
        status=status or ("Up 3 hours" if state == "running" else "Exited (0) 5 minutes ago"),
        created=datetime(2026, 10, 2, 17, 14, 2, tzinfo=UTC),
        ports=ports,
        labels=labels,
        mounts=tuple(
            Mount("volume", f"/var/lib/docker/volumes/{n}/_data", dest, "z", True, n)
            for n, dest in (volumes or {}).items()
        ),
        networks=dict(networks or {}),
    )


def make_volume(name: str, *, project: str | None = None, driver: str = "local") -> Volume:
    labels = {COMPOSE_PROJECT_LABEL: project} if project else {}
    created = datetime(2026, 10, 2, 7, 56, tzinfo=UTC)
    mountpoint = f"/var/lib/docker/volumes/{name}/_data"
    return Volume(name, driver, mountpoint, created, "local", labels, {})


def make_network(
    name: str,
    *,
    subnet: str | None = "172.18.0.0/16",
    gateway: str = "172.18.0.1",
    driver: str = "bridge",
    project: str | None = None,
) -> Network:
    labels = {COMPOSE_PROJECT_LABEL: project} if project else {}
    subnets = (Subnet(subnet, gateway),) if subnet else ()
    created = datetime(2026, 10, 2, 15, 40, tzinfo=UTC)
    return Network(
        (name * 8)[:64].ljust(64, "f"),
        name,
        driver,
        "local",
        created,
        False,
        False,
        False,
        False,
        subnets,
        labels,
        {},
    )


def make_image(
    repo_tags: tuple[str, ...], *, size: int = 1000, image_id: str | None = None
) -> Image:
    digest = image_id or (
        "sha256:" + (repo_tags[0] if repo_tags else "none").encode().hex().ljust(64, "a")[:64]
    )
    return Image(
        id=digest,
        repo_tags=repo_tags,
        repo_digests=(),
        created=datetime(2026, 9, 18, 10, 0, tzinfo=UTC),
        size=size,
        labels={},
    )


def make_event(action: str, actor_id: str, *, kind: str = "container", name: str = "") -> Event:
    return Event(
        type=kind,
        action=action,
        actor_id=actor_id,
        attributes={"name": name} if name else {},
        time=datetime(2026, 10, 3, 0, 0, tzinfo=UTC),
    )


class FakeEngine:
    """EngineAPI with in-memory state and controllable streams."""

    socket_path = "/tmp/fake-docker.sock"

    def __init__(self) -> None:
        self.containers: dict[str, Container] = {}
        self.images: list[Image] = []
        self.volumes: list[Volume] = []
        self.networks: list[Network] = []
        self.version_info = VersionInfo("29.8.2", "1.56", "1.40", "linux", "amd64", "7.2.8")
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.errors: dict[str, DockerError] = {}
        self.event_feeds: list[Feed[Event]] = []
        self.log_feeds: list[Feed[LogLine]] = []
        self.stats_feeds: list[Feed[ContainerStats]] = []
        self.pull_feeds: list[Feed[PullProgress]] = []

    def add(self, *containers: Container) -> None:
        for container in containers:
            self.containers[container.id] = container

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        error = self.errors.get(name)
        if error is not None:
            raise error

    def calls_to(self, name: str) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
        return [call for call in self.calls if call[0] == name]

    def ping(self) -> None:
        self._call("ping")

    def version(self) -> VersionInfo:
        self._call("version")
        return self.version_info

    def list_containers(self, *, all: bool = True) -> list[Container]:
        self._call("list_containers", all=all)
        return list(self.containers.values())

    def inspect_container(self, container_id: str) -> ContainerDetails:
        self._call("inspect_container", container_id)
        container = self.containers.get(container_id)
        if container is None:
            raise NotFound(f"No such container: {container_id}", 404)
        return ContainerDetails(
            id=container.id,
            name=container.name,
            image=container.image,
            image_id=container.image_id,
            created=container.created,
            command=("sh",),
            state=ContainerState(
                container.state, container.state == "running", False, False, 0, None, None, None
            ),
            restart_policy="no",
            tty=False,
            env=(),
            labels=dict(container.labels),
            mounts=(),
            networks=(),
            ports=(),
        )

    def start_container(self, container_id: str) -> None:
        self._call("start_container", container_id)

    def stop_container(self, container_id: str, *, timeout: int = 10) -> None:
        self._call("stop_container", container_id, timeout=timeout)

    def restart_container(self, container_id: str, *, timeout: int = 10) -> None:
        self._call("restart_container", container_id, timeout=timeout)

    def remove_container(
        self, container_id: str, *, force: bool = False, volumes: bool = False
    ) -> None:
        self._call("remove_container", container_id, force=force, volumes=volumes)

    def list_images(self) -> list[Image]:
        self._call("list_images")
        return list(self.images)

    def inspect_image(self, reference: str) -> ImageDetails:
        self._call("inspect_image", reference)
        raise NotFound(f"No such image: {reference}", 404)

    def image_history(self, reference: str) -> list[ImageLayer]:
        self._call("image_history", reference)
        return []

    def remove_image(self, reference: str, *, force: bool = False) -> None:
        self._call("remove_image", reference, force=force)

    def prune_images(self, *, dangling_only: bool = True) -> PruneResult:
        self._call("prune_images", dangling_only=dangling_only)
        return PruneResult(deleted=("sha256:gone",), untagged=(), space_reclaimed=4096)

    def list_volumes(self) -> list[Volume]:
        self._call("list_volumes")
        return list(self.volumes)

    def remove_volume(self, name: str, *, force: bool = False) -> None:
        self._call("remove_volume", name, force=force)

    def prune_volumes(self) -> PruneResult:
        self._call("prune_volumes")
        return PruneResult(deleted=("gone",), untagged=(), space_reclaimed=2048)

    def list_networks(self) -> list[Network]:
        self._call("list_networks")
        return list(self.networks)

    def remove_network(self, network_id: str) -> None:
        self._call("remove_network", network_id)

    def prune_networks(self) -> PruneResult:
        self._call("prune_networks")
        return PruneResult(deleted=("gone_net",), untagged=(), space_reclaimed=0)

    def events(self) -> Stream[Event]:
        self._call("events")
        feed: Feed[Event] = Feed()
        self.event_feeds.append(feed)
        return feed.stream()

    def logs(
        self, container_id: str, *, tty: bool, tail: int | None = 1000, timestamps: bool = True
    ) -> Stream[LogLine]:
        self._call("logs", container_id, tty=tty, tail=tail, timestamps=timestamps)
        feed: Feed[LogLine] = Feed()
        self.log_feeds.append(feed)
        return feed.stream()

    def stats(self, container_id: str) -> Stream[ContainerStats]:
        self._call("stats", container_id)
        feed: Feed[ContainerStats] = Feed()
        self.stats_feeds.append(feed)
        return feed.stream()

    def pull_image(self, repository: str, tag: str = "latest") -> Stream[PullProgress]:
        self._call("pull_image", repository, tag)
        feed: Feed[PullProgress] = Feed()
        self.pull_feeds.append(feed)
        return feed.stream()


Pending = tuple[Callable[[], Any], Callable[[Any], None], Callable[[DockerError], None]]


class DeferredRunner(TaskRunner):
    def __init__(self) -> None:
        super().__init__()
        self.pending: list[Pending] = []

    def submit(self, fn, on_result, on_error) -> None:  # type: ignore[no-untyped-def, override]
        self.pending.append((fn, on_result, on_error))

    def run_pending(self, *, reverse: bool = False) -> None:
        pending, self.pending = self.pending, []
        for fn, on_result, on_error in reversed(pending) if reverse else pending:
            try:
                value = fn()
            except DockerError as exc:
                on_error(wrap_error(exc))
            else:
                on_result(value)
