import pytest

from anchorage.docker.errors import (
    BadRequest,
    Conflict,
    DockerError,
    NotFound,
    ServerError,
    error_for_status,
)


@pytest.mark.parametrize(
    ("status", "cls"),
    [(400, BadRequest), (404, NotFound), (409, Conflict), (500, ServerError), (503, ServerError)],
)
def test_error_for_status_maps_known_codes(status: int, cls: type[DockerError]) -> None:
    err = error_for_status(status, "boom")
    assert isinstance(err, cls)
    assert err.message == "boom"
    assert err.status == status
    assert str(err) == "boom"


def test_error_for_status_falls_back_to_base_class() -> None:
    err = error_for_status(418, "teapot")
    assert type(err) is DockerError
