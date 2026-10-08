"""Minimal Docker-like HTTP server on a UNIX socket for transport and client tests."""

from __future__ import annotations

import json
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

API_PREFIX = "/v1.41"


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: dict[str, str]
    body: bytes


@dataclass
class Route:
    status: int
    content_type: str
    body: bytes = b""
    chunks: list[bytes] = field(default_factory=list)
    hold: threading.Event | None = None
    hold_headers: threading.Event | None = None
    streaming: bool = False
    delay: float = 0.0
    connection_close: bool = False
    abort: bool = False


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, path: str, handler: type[BaseHTTPRequestHandler], daemon: FakeDaemon
    ) -> None:
        self.daemon_ref = daemon
        super().__init__(path, handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        if not isinstance(sys.exc_info()[1], OSError):
            super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def address_string(self) -> str:
        return "unix"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _dispatch(self) -> None:
        server: _Server = self.server  # type: ignore[assignment]
        daemon = server.daemon_ref
        parts = urlsplit(self.path)
        path = unquote(parts.path).removeprefix(API_PREFIX)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        daemon.requests.append(
            RecordedRequest(self.command, path, dict(parse_qsl(parts.query)), body)
        )
        route = daemon.routes.get((self.command, path))
        if route is None:
            payload = json.dumps({"message": f"page not found: {path}"}).encode()
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if route.delay:
            time.sleep(route.delay)
        if route.streaming:
            self._stream(route)
            return
        self.send_response(route.status)
        self.send_header("Content-Type", route.content_type)
        self.send_header("Content-Length", str(len(route.body)))
        self.end_headers()
        self.wfile.write(route.body)

    def _stream(self, route: Route) -> None:
        if route.hold_headers is not None:
            route.hold_headers.wait(timeout=10)
        self.send_response(route.status)
        self.send_header("Content-Type", route.content_type)
        if route.connection_close:
            self.send_header("Connection", "close")
            self.close_connection = True
        else:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for chunk in route.chunks:
                if route.connection_close:
                    self.wfile.write(chunk)
                else:
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
            if route.hold is not None:
                route.hold.wait(timeout=10)
            if route.abort:
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if not route.connection_close:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        except OSError:
            return

    do_GET = _dispatch  # noqa: N815
    do_POST = _dispatch  # noqa: N815
    do_DELETE = _dispatch  # noqa: N815
    do_HEAD = _dispatch  # noqa: N815


class FakeDaemon:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self.routes: dict[tuple[str, str], Route] = {}
        self.requests: list[RecordedRequest] = []
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def add_json(self, method: str, path: str, payload: Any, status: int = 200) -> None:
        self.routes[(method, path)] = Route(
            status=status, content_type="application/json", body=json.dumps(payload).encode()
        )

    def add_raw(
        self,
        method: str,
        path: str,
        body: bytes,
        status: int = 200,
        content_type: str = "text/plain",
        delay: float = 0.0,
    ) -> None:
        self.routes[(method, path)] = Route(
            status=status, content_type=content_type, body=body, delay=delay
        )

    def add_stream(
        self,
        method: str,
        path: str,
        chunks: list[bytes],
        *,
        hold: threading.Event | None = None,
        hold_headers: threading.Event | None = None,
        content_type: str = "application/json",
        status: int = 200,
        delay: float = 0.0,
        connection_close: bool = False,
        abort: bool = False,
    ) -> None:
        self.routes[(method, path)] = Route(
            status=status,
            content_type=content_type,
            chunks=chunks,
            hold=hold,
            hold_headers=hold_headers,
            streaming=True,
            delay=delay,
            connection_close=connection_close,
            abort=abort,
        )

    def start(self) -> None:
        self._server = _Server(self.socket_path, _Handler, self)
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def last(self) -> RecordedRequest:
        return self.requests[-1]


def wait_for_socket(path: str, attempts: int = 50) -> None:
    for _ in range(attempts):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            try:
                sock.connect(path)
                return
            except OSError:
                threading.Event().wait(0.02)
    raise RuntimeError(f"fake daemon did not come up at {path}")
