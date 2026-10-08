"""EngineAPI on top of docker-py (the ``docker`` package), for comparison with the native client.

Optional: install with ``pip install 'anchorage-docker[dockerpy]'``.

Private docker-py members in use, and why: ``APIClient._get``, ``_url`` and ``_raise_for_status``
(logs: the public ``logs(stream=True)`` drops the stdout/stderr frame type, so the raw response is
read and fed to ``iter_log_lines``) and ``_delete`` (``remove_volume`` loses ``force``).

``Stream.close()`` marks the stream closed at once and closes the response and generator on a best
effort basis. A read blocked in the response body ends on ``close()``: the backend shuts the
socket down before closing the response. A request still waiting for the response headers cannot be
interrupted; it returns when the daemon answers or the request fails.

``decode=True`` streams (events, pull) end silently on a truncated chunked body, whereas logs and
stats, which read the raw response, raise ``ProtocolError``. Followed requests (logs, stats) pass
``timeout=None``: docker-py's request timeout would otherwise end a quiet stream.

Thread safety: one ``requests.Session`` is shared by the worker threads. urllib3 pools are locked
and docker-py does not mutate per-request state, so concurrent calls are safe; the pool is sized
by ``max_pool_size``.
"""

from __future__ import annotations

import contextlib
import http.client
import re
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

try:
    import docker.errors
    import docker.types
    import requests
    import urllib3.exceptions

    import docker
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "the docker-py backend needs the 'docker' package: pip install 'anchorage-docker[dockerpy]'"
    ) from exc

from anchorage.docker.client import Stream
from anchorage.docker.errors import (
    DockerError,
    EngineUnavailable,
    PermissionDenied,
    ProtocolError,
    Timeout,
    error_for_status,
)
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
from anchorage.docker.transport import discover_socket_path

T = TypeVar("T")
API_VERSION = "1.41"


_CONNECTION_HINTS = re.compile(
    r"connect|Connection|No such file|refused|EACCES|Permission denied", re.IGNORECASE
)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (requests.exceptions.Timeout, urllib3.exceptions.TimeoutError)):
        return True
    # requests wraps a urllib3 ReadTimeoutError in a plain ConnectionError
    return isinstance(exc, requests.exceptions.ConnectionError) and any(
        isinstance(arg, urllib3.exceptions.TimeoutError) for arg in exc.args
    )


def map_error(exc: BaseException, socket_path: str) -> DockerError:
    """Translate docker-py and requests exceptions into anchorage's error hierarchy."""
    if isinstance(exc, DockerError):
        return exc
    if isinstance(exc, docker.errors.APIError):
        status = exc.response.status_code if exc.response is not None else None
        message = exc.explanation or str(exc)
        if isinstance(message, bytes):
            message = message.decode("utf-8", "replace")
        if status is None:
            return DockerError(message)
        return error_for_status(status, message)
    if isinstance(
        exc,
        (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
            urllib3.exceptions.ProtocolError,
            http.client.IncompleteRead,
        ),
    ):
        return ProtocolError(f"stream read failed: {exc}")
    if _is_timeout(exc):
        return Timeout(f"Timed out talking to {socket_path}")
    text = str(exc)
    if isinstance(exc, requests.exceptions.ConnectionError) or (
        isinstance(exc, docker.errors.DockerException) and _CONNECTION_HINTS.search(text)
    ):
        if "Permission denied" in text or "EACCES" in text:
            return PermissionDenied(f"Permission denied for {socket_path}")
        return EngineUnavailable(f"Cannot connect to Docker at {socket_path}: {text}")
    return DockerError(text)


class _GeneratorSource:
    """Closable over a docker-py generator; a read blocked in the socket cannot be interrupted."""

    def __init__(self, generator: Any, response: Any = None) -> None:
        self._generator = generator
        self._response = response
        self._closed = False

    @property
    def generator(self) -> Any:
        return self._generator

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._response is not None:
            # Closing a response from another thread blocks on the reader's buffered-read lock, so
            # shut the socket down first (what docker-py's own CancellableStream.close does): the
            # blocked read then returns and the lock is released.
            with contextlib.suppress(Exception):
                docker.types.CancellableStream(iter(()), self._response).close()
        for target in (self._response, self._generator):
            closer = getattr(target, "close", None)
            if closer is not None:
                with contextlib.suppress(Exception):  # best effort, the reader may be mid-read
                    closer()


class DockerPyClient:
    def __init__(self, socket_path: str, *, timeout: float = 30.0) -> None:
        self._socket_path = socket_path
        self._api = docker.APIClient(
            base_url=f"http+unix://{socket_path}",
            version=API_VERSION,
            timeout=timeout,
            max_pool_size=32,
        )

    @classmethod
    def from_env(cls) -> DockerPyClient:
        return cls(discover_socket_path())

    @property
    def socket_path(self) -> str:
        return self._socket_path

    def close(self) -> None:
        self._api.close()

    def _call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise map_error(exc, self._socket_path) from None

    def ping(self) -> None:
        self._call(self._api.ping)

    def version(self) -> VersionInfo:
        return VersionInfo.from_api(self._call(self._api.version))

    def list_containers(self, *, all: bool = True) -> list[Container]:
        return [Container.from_api(item) for item in self._call(self._api.containers, all=all)]

    def inspect_container(self, container_id: str) -> ContainerDetails:
        return ContainerDetails.from_api(self._call(self._api.inspect_container, container_id))

    def start_container(self, container_id: str) -> None:
        self._call(self._api.start, container_id)

    def stop_container(self, container_id: str, *, timeout: int = 10) -> None:
        self._call(self._api.stop, container_id, timeout=timeout)

    def restart_container(self, container_id: str, *, timeout: int = 10) -> None:
        self._call(self._api.restart, container_id, timeout=timeout)

    def remove_container(
        self, container_id: str, *, force: bool = False, volumes: bool = False
    ) -> None:
        self._call(self._api.remove_container, container_id, v=volumes, force=force)

    def list_images(self) -> list[Image]:
        return [Image.from_api(item) for item in self._call(self._api.images)]

    def inspect_image(self, reference: str) -> ImageDetails:
        return ImageDetails.from_api(self._call(self._api.inspect_image, reference))

    def image_history(self, reference: str) -> list[ImageLayer]:
        return [ImageLayer.from_api(item) for item in self._call(self._api.history, reference)]

    def remove_image(self, reference: str, *, force: bool = False) -> None:
        self._call(self._api.remove_image, reference, force=force)

    def prune_images(self, *, dangling_only: bool = True) -> PruneResult:
        result = self._call(self._api.prune_images, filters={"dangling": dangling_only})
        return PruneResult.from_api(result or {})

    def list_volumes(self) -> list[Volume]:
        payload = self._call(self._api.volumes) or {}
        return [Volume.from_api(item) for item in payload.get("Volumes") or []]

    def remove_volume(self, name: str, *, force: bool = False) -> None:
        # APIClient.remove_volume builds the query into a URL helper that drops it, so ``force``
        # never reaches the daemon; send the request directly.
        self._call(self._remove_volume, name, force)

    def _remove_volume(self, name: str, force: bool) -> None:
        response = self._api._delete(
            self._api._url("/volumes/{0}", name), params={"force": force} if force else {}
        )
        self._api._raise_for_status(response)

    def prune_volumes(self) -> PruneResult:
        return PruneResult.from_api(self._call(self._api.prune_volumes) or {})

    def list_networks(self) -> list[Network]:
        return [Network.from_api(item) for item in self._call(self._api.networks) or []]

    def remove_network(self, network_id: str) -> None:
        self._call(self._api.remove_network, network_id)

    def prune_networks(self) -> PruneResult:
        return PruneResult.from_api(self._call(self._api.prune_networks) or {})

    def _guarded(self, generator: Iterator[Any], source: _GeneratorSource) -> Iterator[Any]:
        try:
            yield from generator
        except Exception as exc:
            if source.closed:
                return  # close() cut the read short; end quietly
            raise map_error(exc, self._socket_path) from None

    def _stream(
        self, generator: Any, parse: Callable[[dict[str, Any]], T], response: Any = None
    ) -> Stream[T]:
        source = _GeneratorSource(generator, response)
        return Stream(source, (parse(d) for d in self._guarded(generator, source)))

    def events(self) -> Stream[Event]:
        gen = self._call(
            self._api.events,
            filters={"type": ["container", "image", "volume", "network"]},
            decode=True,
        )
        return self._stream(gen, Event.from_api)

    def _follow(self, path: str, container_id: str, params: dict[str, Any]) -> tuple[Any, Any]:
        """Open a followed response without a read timeout: a quiet container is not an error."""
        response = self._call(
            self._api._get,
            self._api._url(path, container_id),
            params=params,
            stream=True,
            timeout=None,
        )
        try:
            self._api._raise_for_status(response)
        except Exception as exc:
            response.close()
            raise map_error(exc, self._socket_path) from None
        return response, response.iter_content(chunk_size=None)

    def logs(
        self,
        container_id: str,
        *,
        tty: bool,
        tail: int | None = 1000,
        timestamps: bool = True,
    ) -> Stream[LogLine]:
        params = {
            "follow": 1,
            "stdout": 1,
            "stderr": 1,
            "timestamps": int(timestamps),
            "tail": "all" if tail is None else tail,
        }
        response, chunks = self._follow("/containers/{0}/logs", container_id, params)
        source = _GeneratorSource(chunks, response)
        guarded = self._guarded(source.generator, source)
        return Stream(source, iter_log_lines(guarded, tty=tty, timestamps=timestamps))

    def stats(self, container_id: str) -> Stream[ContainerStats]:
        response, chunks = self._follow("/containers/{0}/stats", container_id, {"stream": True})
        source = _GeneratorSource(chunks, response)
        guarded = iter_json_lines(self._guarded(source.generator, source))
        return Stream(source, (ContainerStats.from_api(d) for d in guarded))

    def pull_image(self, repository: str, tag: str = "latest") -> Stream[PullProgress]:
        gen = self._call(self._api.pull, repository, tag=tag, stream=True, decode=True)
        return self._stream(gen, PullProgress.from_api)
