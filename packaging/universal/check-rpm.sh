#!/usr/bin/env bash
# Install the universal rpm in a fresh RHEL-family, openSUSE or Fedora image, hard dependencies
# only, and verify.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)
RPM="/pkg/anchorage-${VERSION}-1~universal.x86_64.rpm"
if command -v dnf >/dev/null; then
    dnf install -y -q --setopt=install_weak_deps=False "$RPM" desktop-file-utils util-linux
elif command -v yum >/dev/null; then
    yum install -y -q "$RPM" desktop-file-utils util-linux
elif command -v zypper >/dev/null; then
    zypper --non-interactive install --no-recommends --allow-unsigned-rpm "$RPM" desktop-file-utils util-linux
else
    echo "no supported package manager" >&2; exit 1
fi
source /src/packaging/universal/verify-tree.sh /opt/anchorage
icon_check /opt/anchorage/bin/python3
smoke_test "$VERSION"
