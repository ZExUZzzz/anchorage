#!/usr/bin/env bash
# Run the AppImage from a random directory in a fresh Debian 11 image with the runtime libraries
# a desktop has (the packages of debian-depends.txt). smoke_test expects /usr/bin/anchorage and
# installed desktop files, which an AppImage does not have, so the two run checks are
# reimplemented here (no FUSE in a container).
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)
export DEBIAN_FRONTEND=noninteractive
PKGS=$(grep -v '^\s*$' /src/packaging/universal/debian-depends.txt | grep -v '^libc6' \
    | sed 's/.*| *//; s/ *(.*//')
source /src/packaging/universal/apt-archive.sh
apt-get update -qq
# shellcheck disable=SC2086
apt-get install -y -qq --no-install-recommends desktop-file-utils util-linux $PKGS >/dev/null
ensure_tester
DIR=$(mktemp -d /tmp/appimage-XXXXXX)
cp /pkg/Anchorage-"$VERSION"-x86_64.AppImage "$DIR/"
chmod 755 "$DIR"/Anchorage-*.AppImage
chown tester "$DIR"
AI="./Anchorage-$VERSION-x86_64.AppImage"
# The path without FUSE must work.
out=$(su tester -c "cd '$DIR' && $AI --appimage-extract-and-run --version")
[ "$out" = "anchorage $VERSION" ] || { echo "unexpected --version output: $out" >&2; exit 1; }
# Extract once, so the timed run below measures the application and not the extraction.
su tester -c "cd '$DIR' && $AI --appimage-extract >/dev/null"
out=$(su tester -c "cd '$DIR' && squashfs-root/AppRun --version")
[ "$out" = "anchorage $VERSION" ] || { echo "unexpected AppRun --version output: $out" >&2; exit 1; }
err=$(mktemp); chmod 644 "$err"; rc=0
su tester -c "cd '$DIR' && QT_QPA_PLATFORM=offscreen timeout 3 squashfs-root/AppRun" 2>"$err" || rc=$?
if [ "$rc" -ne 124 ]; then
    echo "offscreen run exited $rc" >&2; cat "$err" >&2; exit 1
fi
if grep -q Traceback "$err"; then cat "$err" >&2; exit 1; fi
echo "appimage checks passed for anchorage $VERSION"
