"""Human-readable units for the UI."""

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_bytes(value: int | float) -> str:
    size = float(value)
    for unit in _UNITS:
        if size < 1024 or unit == _UNITS[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {_UNITS[-1]}"


def format_rate(bytes_per_second: float) -> str:
    return f"{format_bytes(bytes_per_second)}/s"
