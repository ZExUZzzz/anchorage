# Shared helpers for the in-container packaging scripts. Sourced, not executed.
# Contract: /src is the repository (read-only), /out receives build artifacts,
# /pkg holds them for the check stage. HOST_UID/HOST_GID own published files.
set -euo pipefail

APP_ID=io.github.zexuzzzz.Anchorage

version_from_pyproject() {
    sed -n 's/^version = "\(.*\)"/\1/p' /src/pyproject.toml | head -1
}

publish() {
    cp -f "$@" /out/
    if [ -n "${HOST_UID:-}" ]; then
        for f in "$@"; do
            chown "$HOST_UID:${HOST_GID:-$HOST_UID}" "/out/$(basename "$f")"
        done
    fi
    ls -l /out
}

ensure_tester() {
    id tester >/dev/null 2>&1 || useradd -m tester
}

# Run the installed application as an unprivileged user and check the desktop files.
smoke_test() {
    local version=$1 out rc=0 err
    ensure_tester
    out=$(su tester -c "anchorage --version")
    if [ "$out" != "anchorage $version" ]; then
        echo "unexpected --version output: $out" >&2
        return 1
    fi
    err=$(mktemp)
    chmod 644 "$err"
    su tester -c "QT_QPA_PLATFORM=offscreen timeout 3 anchorage" 2>"$err" || rc=$?
    if [ "$rc" -ne 124 ]; then
        echo "offscreen run exited $rc" >&2
        cat "$err" >&2
        return 1
    fi
    if grep -q Traceback "$err"; then
        cat "$err" >&2
        return 1
    fi
    desktop-file-validate "/usr/share/applications/$APP_ID.desktop"
    test -s "/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
    test -s "/usr/share/metainfo/$APP_ID.metainfo.xml"
    echo "smoke test passed for anchorage $version"
}

# The window icon must render from the SVG with only the declared dependencies installed.
icon_check() {
    local python=$1
    ensure_tester
    su tester -c "QT_QPA_PLATFORM=offscreen $python -c '
import sys
from PySide6.QtWidgets import QApplication
from anchorage.ui.theme import app_icon
app = QApplication(sys.argv)
sys.exit(0 if not app_icon().pixmap(32).isNull() else 1)
'" || { echo "the application icon does not render" >&2; return 1; }
    echo "icon renders"
}
