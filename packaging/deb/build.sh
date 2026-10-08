#!/usr/bin/env bash
# Build the Debian package with dpkg-buildpackage from the git archive tarball.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential devscripts equivs lintian >/dev/null
WORK=/build
mkdir -p "$WORK"
cd "$WORK"
cp "/out/anchorage-$VERSION.tar.gz" "anchorage_$VERSION.orig.tar.gz"
tar xzf "anchorage_$VERSION.orig.tar.gz"
cd "anchorage-$VERSION"
cp -r /src/packaging/debian debian
mk-build-deps -i -r -t 'apt-get -y -qq --no-install-recommends' debian/control >/dev/null
dpkg-buildpackage -us -uc -b
lintian --fail-on error "../anchorage_${VERSION}-1_all.deb"
publish "../anchorage_${VERSION}-1_all.deb"
