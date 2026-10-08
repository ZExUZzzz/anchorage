#!/usr/bin/env bash
# Install the Debian package in a fresh container, Depends only, and smoke-test it.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq --no-install-recommends "/pkg/anchorage_${VERSION}-1_all.deb" desktop-file-utils >/dev/null
icon_check python3
smoke_test "$VERSION"
