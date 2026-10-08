"""Typed errors raised by the Docker layer."""


class DockerError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class EngineUnavailable(DockerError):
    """Socket missing, connection refused or connect timed out."""


class Timeout(DockerError):
    """The daemon accepted the connection but did not answer in time."""


class PermissionDenied(DockerError):
    """The socket exists but the current user may not open it."""


class BadRequest(DockerError):
    """HTTP 400."""


class NotFound(DockerError):
    """HTTP 404."""


class Conflict(DockerError):
    """HTTP 409, for example removing a running container without force."""


class ServerError(DockerError):
    """HTTP 5xx or an error object inside a stream."""


class ProtocolError(DockerError):
    """Malformed response or an unexpected end of stream."""


def error_for_status(status: int, message: str) -> DockerError:
    if status == 400:
        return BadRequest(message, status)
    if status == 404:
        return NotFound(message, status)
    if status == 409:
        return Conflict(message, status)
    if status >= 500:
        return ServerError(message, status)
    return DockerError(message, status)
