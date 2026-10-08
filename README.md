# Anchorage

**English** | [Русский](README.ru.md)

Native Linux desktop client for Docker Engine. It talks to the daemon over the UNIX socket and
is a plain Qt application that follows your desktop theme. There is no virtual machine and no
web view.

![Container list grouped by Compose project](docs/screenshots/containers.png)

| | |
|---|---|
| ![Container logs](docs/screenshots/container-logs.png) | ![Container resource charts](docs/screenshots/container-stats.png) |
| ![Network with its containers](docs/screenshots/networks.png) | ![Volumes](docs/screenshots/volumes.png) |

## Features

- Containers grouped by Compose project with live state; start, stop, restart, remove.
- Per-container logs with search and follow, CPU / memory / network / block I/O charts,
  and the full inspect tree.
- "Open shell" runs `docker exec -it` in your terminal emulator.
- Images with pull progress, remove and prune.
- Volumes and networks with the containers that use them.
- Reconnects on its own when the daemon restarts.
- A Settings button in the sidebar sets the log colours, the Docker client backend, the socket
  path and the terminal command; socket and backend apply after a restart.

## Requirements

- Linux with a desktop session (X11 or Wayland).
- Docker Engine 20.10 or newer (API 1.41) reachable over a UNIX socket, and permission to use it
  (usually membership in the `docker` group).
- Python 3.11 or newer and PySide6 6.6 or newer (installed by the package).
- For "Open shell": the `docker` CLI and a terminal emulator (`xdg-terminal-exec`, or one of
  the common ones such as konsole, gnome-terminal, kitty, alacritty, foot, xfce4-terminal).

## Install

Packages for every release are attached to the
[GitHub releases](https://github.com/zexuzzzz/anchorage/releases).

| Distribution | Package |
|---|---|
| Any x86_64 Linux with glibc 2.28 or newer (Debian 11+, Ubuntu 20.04+, RHEL/Rocky/Alma 8+, openSUSE Leap, any Fedora) | `anchorage_<version>-1~universal_amd64.deb` (`sudo apt install ./anchorage_*universal_amd64.deb`), `anchorage-<version>-1~universal.x86_64.rpm` (`sudo dnf install ./anchorage-*universal.x86_64.rpm`, or `zypper in`), or `Anchorage-<version>-x86_64.AppImage` (`chmod +x`, then run; without FUSE add `--appimage-extract-and-run`). Self-contained: own Python and Qt under `/opt/anchorage`, about 46 MB (deb), 41 MB (rpm) or 61 MB (AppImage) to download and about 180 MB installed. Systems with glibc older than 2.28 (for example CentOS 7) fail with a loader error |
| Arch Linux | `anchorage-<version>-1-any.pkg.tar.zst` (`sudo pacman -U`). The file is built against the current Arch Python; after a Python major upgrade rebuild it with `packaging/build.sh arch` or use the self-contained package |
| Debian 13, Ubuntu 25.04 and newer | `anchorage_<version>-1_all.deb` (`sudo apt install ./anchorage_*_all.deb`), uses the distribution's PySide6 |
| Fedora (current release at build time, `fcNN` in the file name) | `anchorage-<version>-1.fcNN.noarch.rpm` (`sudo dnf install ./anchorage-*.noarch.rpm`) |
| Anything else | `pipx install anchorage-docker` (the command and the application are still `anchorage`) |

GitHub shows `~universal` as `.universal` in download names. The native packages use the desktop's own Qt and pick up the Plasma style on KDE; the self-contained build uses Fusion with the desktop's dark or light preference on KDE and the GTK theme on GNOME.

For a `pipx` install, take the two files from the source repository
(they are not in the wheel) and install them into your local share directory:

    install -Dm644 data/io.github.zexuzzzz.Anchorage.desktop ~/.local/share/applications/io.github.zexuzzzz.Anchorage.desktop
    install -Dm644 src/anchorage/data/icon.svg ~/.local/share/icons/hicolor/scalable/apps/io.github.zexuzzzz.Anchorage.svg

## Command line

    anchorage [--socket PATH] [--backend {native,dockerpy}] [--log-colors {stream,level}] [--verbose] [--version]

`DOCKER_HOST` is honoured when it is a `unix://` URL. Any other value is ignored with a warning
and the default `/var/run/docker.sock` is used. When `DOCKER_HOST` is unset (and without
`--socket`), the client uses a rootless daemon's `$XDG_RUNTIME_DIR/docker.sock` if that file
exists, and `/var/run/docker.sock` otherwise.

`--backend` (or `ANCHORAGE_BACKEND`) selects the Docker API client. `native` is the default.
`dockerpy` is experimental and exists for the comparison in `docs/backend-comparison.md`; it
needs the docker-py package: `pip install 'anchorage-docker[dockerpy]'` or
`pipx inject anchorage-docker docker`, and with distribution packages the system package
(`python-docker` on Arch, `python3-docker` on Debian/Ubuntu/Fedora). The self-contained packages
do not include it.

`--log-colors` (or `ANCHORAGE_LOG_COLORS`) chooses how container logs are coloured. `stream`, the
default, paints lines written to stderr red, which mirrors `docker logs`; `level` ignores the
stream and colours lines by the severity marker found near their start (`[ERROR]`,
`level=warning`, `WARN[0000]`, `FATAL:` and similar): errors red, warnings yellow.

Flags and environment variables override the values saved in Settings for that run, and the
dialog shows such a setting as fixed and leaves its saved value unchanged.

## Building packages

`packaging/build.sh <arch|deb|rpm|universal|all>` builds the committed tree in a Docker
container of the target distribution and then installs and smoke-tests the result in a fresh
container. Packages land in `dist/packages/`. The same script runs in the Packages workflow
on GitHub Actions. Downloads for the universal build are kept in `dist/cache/` and reused after a
checksum match; the checks of a target run in parallel, `ANCHORAGE_PACKAGING_JOBS` at a time
(default 3), with their logs in `dist/packages/logs/`.

## Development

    uv sync
    uv run anchorage
    uv run pytest
    uv run ruff check . && uv run ruff format --check .
    uv run mypy

Integration tests against a real daemon: `uv run pytest -m integration`.

The repository layout: `anchorage.docker` is a pure-Python Docker Engine API client over
`AF_UNIX`, `anchorage.core` holds the Qt models, workers and stores, `anchorage.ui` the
widgets and `anchorage.app` the entry point. `data/` holds the desktop entry and AppStream
metainfo, `packaging/aur/` the PKGBUILD.

## License

MIT, see `LICENSE`.
