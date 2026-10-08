# Changelog

## Unreleased

- The interface is translated into Russian, German, Spanish, French and Simplified Chinese;
  choose the language in Settings, with `--language` or `ANCHORAGE_LANGUAGE`.
- The self-contained packages follow the desktop's dark or light preference on KDE.
- Stats charts scale to the container's own usage, so idle noise no longer fills them.
- A Settings dialog for log colours, backend, socket and terminal; flags and environment
  variables still override saved values.
- Member lists in volume and network details can be used from the keyboard: Tab to reach them,
  Enter opens the selected container.
- A saved docker-py backend without the docker-py package falls back to the native backend and
  says so, instead of refusing to start; a backend set by a flag or variable still exits with
  an error that names it.
- When the socket saved in Settings is not available, the empty state says so and points to
  Settings.
- A refresh that was superseded by a newer one no longer reports its failure.
- Screenshots in the README and the AppStream metadata.

## 0.1.0 - 2026-10-08

First release.

- Containers grouped by Compose project with live state from the event stream; start, stop,
  restart, remove; logs with search and follow, stats charts, inspect details; open a shell in
  an external terminal.
- Images: list, pull with progress, remove, prune.
- Volumes and networks with the containers that use them; remove, prune.
- Engine connection with automatic reconnect, `DOCKER_HOST` (`unix://`) and `--socket` support.
- `--log-colors level` colours container logs by the severity marker in each line.
- Experimental docker-py backend (`--backend dockerpy`) and a measured comparison with the
  native client in `docs/backend-comparison.md`.
- Follows the system Qt palette; window geometry, splitter positions and column widths are kept.
- Packages: self-contained deb, rpm and AppImage for any x86_64 Linux with glibc 2.28 or newer;
  native packages for Arch Linux, Debian 13 / Ubuntu 25.04+ and current Fedora; wheel and sdist
  on PyPI as `anchorage-docker`.
