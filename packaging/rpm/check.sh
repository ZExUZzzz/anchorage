#!/usr/bin/env bash
# Install the Fedora package in a fresh container, hard dependencies only, and smoke-test it.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)

# su comes from util-linux, which the minimal Fedora image lacks.
dnf install -y -q --setopt=install_weak_deps=False /pkg/anchorage-"$VERSION"-*.noarch.rpm desktop-file-utils util-linux >/dev/null
icon_check python3
smoke_test "$VERSION"
