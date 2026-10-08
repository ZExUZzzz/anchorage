#!/usr/bin/env bash
# Build distribution packages in Docker containers and verify each one in a fresh
# container of its distribution. Usage: packaging/build.sh <arch|deb|rpm|universal|all>
# Builds the committed tree (git archive HEAD). Output: dist/packages/.
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
    echo "usage: $0 <arch|deb|rpm|universal|all>" >&2
    exit 2
}

image_for() {
    case "$1" in
        arch) echo archlinux:latest ;;
        deb) echo debian:trixie ;;
        rpm) echo fedora:latest ;;
        universal) echo debian:11 ;;
        *) echo "unknown target: $1" >&2; usage ;;
    esac
}

# Remove the target's previous outputs so a stale package cannot satisfy the check.
clean_outputs() {
    case "$1" in
        arch) rm -f "$OUT"/anchorage-*.pkg.tar.zst ;;
        deb) rm -f "$OUT"/anchorage_*_all.deb ;;
        rpm) rm -f "$OUT"/anchorage-*.noarch.rpm ;;
        universal) rm -f "$OUT"/anchorage_*~universal_amd64.deb "$OUT"/anchorage-*~universal.x86_64.rpm "$OUT"/Anchorage-*.AppImage ;;
    esac
}

# One check in a fresh container; the whole output goes to its log. Runs as a background job.
check_job() {  # script image logfile
    local start=$SECONDS rc=0
    timeout 20m docker run --rm -v "$PWD:/src:ro" -v "$OUT:/pkg:ro" "$2" bash "/src/packaging/$1" >"$3" 2>&1 || rc=$?
    echo "$rc" >"$3.rc"
    if [ "$rc" -eq 0 ]; then echo "ok $2 [$(basename "$1" .sh)] ($((SECONDS - start))s)"; fi
}

# Run the checks given as "script image" arguments, at most $JOBS at a time. Prints a line per
# check, the full log of every failed one and a summary; returns non-zero if any check failed.
run_checks() {  # target script image [script image ...]
    local target=$1 script image kind log n=0 failed=0 ok=0 i
    shift
    local -a logs=() images=()
    mkdir -p "$LOGS"
    while [ $# -ge 2 ]; do
        script=$1 image=$2
        shift 2
        kind=$(basename "$script" .sh | sed 's/^check-\?//')
        log="$LOGS/$target${kind:+-$kind}-$(echo "$image" | tr '/:' '__').log"
        rm -f "$log" "$log.rc"
        logs+=("$log")
        images+=("$image")
        while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n || true; done
        echo "==> check $script in a fresh $image"
        check_job "$script" "$image" "$log" &
    done
    wait || true
    for i in "${!logs[@]}"; do
        n=$((n + 1))
        if [ "$(cat "${logs[$i]}.rc" 2>/dev/null || echo 1)" -eq 0 ]; then
            ok=$((ok + 1))
        else
            failed=$((failed + 1))
            echo "FAIL ${images[$i]} (${logs[$i]})"
            cat "${logs[$i]}" 2>/dev/null || true
        fi
    done
    echo "checks: $ok ok, $failed failed"
    [ "$failed" -eq 0 ]
}

run_target() {
    local target=$1 image
    image=$(image_for "$target")
    clean_outputs "$target"
    echo "==> $target: build in $image"
    docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
        -v "$PWD:/src:ro" -v "$OUT:/out" -v "$CACHE:/cache" "$image" bash "/src/packaging/$target/build.sh"
    if [ "$target" = universal ]; then
        run_checks "$target" \
            universal/check-deb.sh debian:11 universal/check-deb.sh debian:12 \
            universal/check-deb.sh ubuntu:22.04 universal/check-deb.sh ubuntu:24.04 \
            universal/check-rpm.sh rockylinux:8 universal/check-rpm.sh rockylinux:9 \
            universal/check-rpm.sh opensuse/leap:15.6 universal/check-rpm.sh fedora:41 \
            universal/check-appimage.sh debian:11
        return
    fi
    run_checks "$target" "$target/check.sh" "$image"
}

[ $# -eq 1 ] || usage
case "$1" in arch|deb|rpm|universal|all) ;; *) usage ;; esac
if ! docker info >/dev/null 2>&1; then
    echo "docker is not available: start the Docker daemon or set DOCKER_HOST" >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "warning: uncommitted changes are not part of the build (git archive HEAD)" >&2
fi

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
OUT="$PWD/dist/packages"
LOGS="$OUT/logs"
CACHE="$PWD/dist/cache"
JOBS=${ANCHORAGE_PACKAGING_JOBS:-3}
if ! [[ $JOBS =~ ^[1-9][0-9]*$ ]]; then
    echo "ANCHORAGE_PACKAGING_JOBS must be a positive integer, got: $JOBS" >&2
    exit 2
fi
mkdir -p "$OUT" "$CACHE"
git archive --format=tar.gz --prefix="anchorage-$VERSION/" -o "$OUT/anchorage-$VERSION.tar.gz" HEAD
echo "source tarball: $OUT/anchorage-$VERSION.tar.gz"

if [ "$1" = all ]; then
    for target in arch deb rpm universal; do run_target "$target"; done
else
    run_target "$1"
fi
echo "==> done"
ls -l "$OUT"
