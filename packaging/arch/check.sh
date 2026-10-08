#!/usr/bin/env bash
# Install the Arch package in a fresh container and smoke-test it.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)

pacman -Syu --noconfirm >/dev/null
pacman -U --noconfirm /pkg/anchorage-"$VERSION"-*.pkg.tar.zst >/dev/null
pacman -S --noconfirm --needed desktop-file-utils >/dev/null
icon_check python
smoke_test "$VERSION"
