#!/usr/bin/env bash
# Install the universal deb in a fresh Debian/Ubuntu image, hard dependencies only, and verify.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)
export DEBIAN_FRONTEND=noninteractive
source /src/packaging/universal/apt-archive.sh
apt-get update -qq
apt-get install -y -qq --no-install-recommends "/pkg/anchorage_${VERSION}-1~universal_amd64.deb" desktop-file-utils >/dev/null
source /src/packaging/universal/verify-tree.sh /opt/anchorage
icon_check /opt/anchorage/bin/python3
smoke_test "$VERSION"
