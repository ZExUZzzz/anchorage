"""HTTP/1.1 over a UNIX socket for the Docker Engine API."""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import socket
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from anchorage.docker.errors import (
    DockerError,
    EngineUnavailable,
    PermissionDenied,
    ProtocolError,
    Timeout,
    error_for_status,
)

DEFAULT_SOCKET_PATH = "/var/run/docker.sock"
API_VERSION = "1.41"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self, socket_path: str, *, connect_timeout: float, read_timeout: float | None
    ) -> None:
        super().__init__("localhost", timeout=read_timeout)
        self._socket_path = socket_path
        self._connect_timeout = connect_timeout
        self.raw_sock: socket.socket | None = None

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self._connect_timeout)
            sock.connect(self._socket_path)
            sock.settimeout(self.timeout)
        except TimeoutError as exc:
            sock.close()
            raise EngineUnavailable(f"Timed out connecting to {self._socket_path}") from exc
        except BaseException:
            sock.close()
            raise
        self.sock = sock
        self.raw_sock = sock


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except ValueError as exc:
            raise ProtocolError(f"malformed JSON response: {self.body[:80]!r}") from exc


class StreamResponse:
    """An open streaming response.

    The request has been sent but the response headers may not have arrived yet; they are
    read lazily by the first ``chunks()`` step. ``chunks()`` blocks on the socket.
    ``close()`` may be called from another thread, whether or not the headers have arrived;
    it shuts the socket down, which ends the iteration in the reading thread.
    """

    def __init__(self, connection: UnixHTTPConnection, method: str, path: str) -> None:
        self._connection = connection
        self._method = method
        self._path = path
        self._response: http.client.HTTPResponse | None = None
        self._lock = threading.Lock()
        self._reading = False
        self.closed = False

    def chunks(self, size: int = 65536) -> Iterator[bytes]:
        while True:
            with self._lock:
                if self.closed:
                    return
                self._reading = True
            try:
                response = self._response
                if response is None:
                    response = self._response = self._read_headers()
                data = response.read1(size)
            except (OSError, http.client.HTTPException) as exc:
                self._release()
                if self.closed:
                    return
                raise ProtocolError(f"stream read failed: {exc}") from exc
            except BaseException:
                self._release()
                raise
            finally:
                with self._lock:
                    self._reading = False
                    if self.closed:
                        self._release()
            if not data:
                self._release()
                return
            yield data

    def _read_headers(self) -> http.client.HTTPResponse:
        try:
            response = self._connection.getresponse()
        except TimeoutError as exc:
            raise Timeout(f"Timed out waiting for {self._method} {self._path}") from exc
        except (OSError, http.client.HTTPException) as exc:
            if self.closed:
                raise
            raise ProtocolError(f"{self._method} {self._path} failed: {exc}") from exc
        if response.status >= 400:
            try:
                data = response.read()
            except (OSError, http.client.HTTPException):
                data = b""
            raise error_for_status(response.status, _error_message(response.status, data))
        return response

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            sock = self._connection.raw_sock
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)
            if not self._reading:
                self._release()

    def _release(self) -> None:
        if self._response is not None:
            with contextlib.suppress(OSError):
                self._response.close()
        self._connection.close()


def _encode_query(query: Mapping[str, Any] | None) -> str:
    if not query:
        return ""
    items: list[tuple[str, str]] = []
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, bool):
            items.append((key, "true" if value else "false"))
        elif isinstance(value, Mapping | list):
            items.append((key, json.dumps(value)))
        else:
            items.append((key, str(value)))
    return "?" + urlencode(items) if items else ""


def _error_message(status: int, body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    if text:
        try:
            payload = json.loads(text)
        except ValueError:
            return text
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])
        return text
    return f"HTTP {status}"


class Transport:
    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        *,
        api_version: str = API_VERSION,
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.socket_path = socket_path
        self.api_version = api_version
        self.timeout = timeout
        self.connect_timeout = connect_timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        timeout: float | None = None,
    ) -> Response:
        read_timeout = self.timeout if timeout is None else timeout
        connection, response = self._open(method, path, query, body, read_timeout)
        try:
            data = response.read()
        except TimeoutError as exc:
            raise Timeout(f"Timed out waiting for {method} {path}") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise ProtocolError(f"response read failed: {exc}") from exc
        finally:
            connection.close()
        return Response(status=response.status, body=data)

    def stream(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> StreamResponse:
        """Connect and send the request; the response headers are read by ``chunks()``."""
        connection = self._send(method, path, query, body, None)
        return StreamResponse(connection, method, path)

    def _send(
        self,
        method: str,
        path: str,
        query: Mapping[str, Any] | None,
        body: Any,
        read_timeout: float | None,
    ) -> UnixHTTPConnection:
        url = f"/v{self.api_version}{path}{_encode_query(query)}"
        headers = {"Host": "localhost", "Accept": "application/json"}
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        connection = UnixHTTPConnection(
            self.socket_path, connect_timeout=self.connect_timeout, read_timeout=read_timeout
        )
        try:
            connection.request(method, url, body=payload, headers=headers)
        except BaseException as exc:
            connection.close()
            raise self._map_error(exc, method, path) from exc
        return connection

    def _map_error(self, exc: BaseException, method: str, path: str) -> BaseException:
        if isinstance(exc, DockerError):
            return exc
        if isinstance(exc, FileNotFoundError):
            return EngineUnavailable(f"Docker socket not found: {self.socket_path}")
        if isinstance(exc, PermissionError):
            return PermissionDenied(f"Permission denied: {self.socket_path}")
        if isinstance(exc, ConnectionRefusedError):
            return EngineUnavailable(f"Connection refused: {self.socket_path}")
        if isinstance(exc, TimeoutError):
            return Timeout(f"Timed out waiting for {method} {path}")
        if isinstance(exc, OSError | http.client.HTTPException):
            return ProtocolError(f"{method} {path} failed: {exc}")
        return exc

    def _open(
        self,
        method: str,
        path: str,
        query: Mapping[str, Any] | None,
        body: Any,
        read_timeout: float | None,
    ) -> tuple[UnixHTTPConnection, http.client.HTTPResponse]:
        connection = self._send(method, path, query, body, read_timeout)
        try:
            response = connection.getresponse()
        except BaseException as exc:
            connection.close()
            raise self._map_error(exc, method, path) from exc
        if response.status >= 400:
            try:
                data = response.read()
            except (OSError, http.client.HTTPException):
                data = b""
            finally:
                connection.close()
            raise error_for_status(response.status, _error_message(response.status, data))
        return connection, response


def discover_socket_path(
    environ: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> str:
    """Pick the daemon socket: DOCKER_HOST, then the rootless socket, then the system default."""
    env = os.environ if environ is None else environ
    host = env.get("DOCKER_HOST", "")
    if host:
        if not host.startswith("unix://"):
            msg = f"DOCKER_HOST={host!r} is not supported; only unix:// sockets are"
            raise EngineUnavailable(msg)
        return host.removeprefix("unix://") or DEFAULT_SOCKET_PATH
    runtime_dir = env.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        candidate = os.path.join(runtime_dir, "docker.sock")
        if exists(candidate):
            return candidate
    return DEFAULT_SOCKET_PATH
