#!/usr/bin/env bash
# Build the self-contained /opt/anchorage tree on the oldest supported userland and pack it
# as a universal deb, a universal rpm and an AppImage. Runs in debian:11.
source /src/packaging/common.sh
source /src/packaging/universal/pins.sh
VERSION=$(version_from_pyproject)
export DEBIAN_FRONTEND=noninteractive

source /src/packaging/universal/apt-archive.sh
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates curl xz-utils binutils rpm file \
    desktop-file-utils >/dev/null
# The runtime libraries of the target desktop, so the finished tree can be started here.
RUNTIME_PKGS=$(grep -v '^\s*$' /src/packaging/universal/debian-depends.txt | grep -v '^libc6' \
    | sed 's/.*| *//; s/ *(.*//')
# shellcheck disable=SC2086
apt-get install -y -qq --no-install-recommends $RUNTIME_PKGS >/dev/null
WORK=/build
mkdir -p "$WORK/dl"
cd "$WORK"
tar xzf "/out/anchorage-$VERSION.tar.gz"

# /cache (the host's dist/cache) keeps verified downloads between runs; it may be absent or read-only.
# Tries the primary URL, then the fallback (if any); the sha256 must match either way.
fetch() {  # url fallback-url sha256 dest
    local cached tmp url name
    name=$(basename "$4")
    cached="/cache/$name"
    if [ -f "$cached" ] && echo "$3  $cached" | sha256sum -c - >/dev/null 2>&1; then
        chmod 644 "$cached" 2>/dev/null && chown "${HOST_UID:-0}:${HOST_GID:-0}" "$cached" 2>/dev/null || true
        cp "$cached" "$4"
        echo "cached $name"
        return
    fi
    tmp=$(mktemp)
    for url in "$1" $2; do
        if curl -fsSL "$url" -o "$tmp" && echo "$3  $tmp" | sha256sum -c - >/dev/null 2>&1; then
            if cp "$tmp" "$cached" 2>/dev/null; then
                chmod 644 "$cached"
                chown "${HOST_UID:-0}:${HOST_GID:-0}" "$cached"
            fi
            mv "$tmp" "$4"
            echo "downloaded $name from $url"
            return
        fi
        echo "could not fetch $name from $url (or its sha256 differs)" >&2
    done
    echo "no source served $name" >&2
    return 1
}
fetch "$PBS_URL" "" "$PBS_SHA256" "dl/$PBS_FILE"
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_FALLBACK_URL" "$APPIMAGETOOL_SHA256" dl/appimagetool
fetch "$RUNTIME_URL" "$RUNTIME_FALLBACK_URL" "$RUNTIME_SHA256" dl/runtime-x86_64
chmod +x dl/appimagetool

# --- the tree ---------------------------------------------------------------------------
TREE="$WORK/tree/opt/anchorage"
mkdir -p "$WORK/tree/opt"
tar xzf "dl/$PBS_FILE" -C "$WORK/tree/opt"      # extracts ./python
mv "$WORK/tree/opt/python" "$TREE"
PY="$TREE/bin/python3"
"$PY" -m pip install --no-cache-dir -q --require-hashes --only-binary :all: -r /src/packaging/universal/requirements.txt
"$PY" -m pip install --no-cache-dir -q --no-deps "./anchorage-$VERSION"
SITE=$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
echo "tree before trim: $(du -sh "$TREE" | cut -f1)"
du -h --max-depth=5 "$TREE" | sort -h | tail -10
# Qt and PySide parts the application never loads (same list as the former Ubuntu bundle).
rm -rf "$TREE"/bin/pip* "$TREE"/bin/pyside6-* "$SITE"/pip "$SITE"/pip-*.dist-info
for name in assistant designer linguist lupdate lrelease qml qmlls qmllint qmlformat \
        qmlimportscanner qsb svgtoqml balsam balsamui qtdiag qtpaths; do
    rm -f "$SITE/PySide6/$name"
done
rm -rf "$SITE"/PySide6/Qt/qml "$SITE"/PySide6/Qt/libexec \
    "$SITE"/PySide6/Qt/plugins/sqldrivers "$SITE"/PySide6/Qt/plugins/tls \
    "$SITE"/PySide6/Qt/plugins/qmltooling "$SITE"/PySide6/Qt/plugins/designer \
    "$SITE"/PySide6/Qt/plugins/printsupport "$SITE"/PySide6/Qt/plugins/networkinformation \
    "$SITE"/PySide6/Qt/plugins/egldeviceintegrations \
    "$SITE"/PySide6/Qt/plugins/vectorimageformats "$SITE"/PySide6/Qt/plugins/wayland-graphics-integration-server
rm -rf "$SITE"/PySide6/Qt/plugins/qmllint
# Keep the compose and ibus input-method plugins; the on-screen keyboard needs QtQuick.
rm -f "$SITE"/PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so
rm -f "$SITE"/PySide6/Qt/plugins/platforms/libqvnc.so "$SITE"/PySide6/Qt/plugins/platforms/libqlinuxfb.so \
    "$SITE"/PySide6/Qt/plugins/platforms/libqeglfs.so "$SITE"/PySide6/Qt/plugins/generic/libqtuiotouchplugin.so \
    "$SITE"/PySide6/Qt/plugins/imageformats/libqpdf.so "$SITE"/PySide6/libpyside6qml*
rm -f "$SITE"/PySide6/Qt/lib/libQt6Qml* "$SITE"/PySide6/Qt/lib/libQt6Quick* \
    "$SITE"/PySide6/Qt/lib/libQt6Designer* "$SITE"/PySide6/Qt/lib/libQt6Sql* \
    "$SITE"/PySide6/Qt/lib/libQt6Test* "$SITE"/PySide6/Qt/lib/libQt6Network* \
    "$SITE"/PySide6/Qt/lib/libQt6Labs* "$SITE"/PySide6/Qt/lib/libQt6Help* \
    "$SITE"/PySide6/Qt/lib/libQt6UiTools* "$SITE"/PySide6/Qt/lib/libQt6OpenGLWidgets* \
    "$SITE"/PySide6/Qt/lib/libQt6PrintSupport* "$SITE"/PySide6/Qt/lib/libQt6Concurrent* \
    "$SITE"/PySide6/Qt/lib/libQt6Xml* "$SITE"/PySide6/Qt/lib/libQt6Pdf* \
    "$SITE"/PySide6/Qt/lib/libQt6WaylandCompositor* "$SITE"/PySide6/Qt/lib/libQt6WaylandEglCompositorHwIntegration* \
    "$SITE"/PySide6/Qt/lib/libQt6VirtualKeyboard* "$SITE"/PySide6/Qt/lib/libQt6Lottie* \
    "$SITE"/PySide6/Qt/lib/libQt6EglFS* "$SITE"/PySide6/Qt/lib/libQt6EglFs*
rm -f "$SITE"/PySide6/QtQml* "$SITE"/PySide6/QtQuick* "$SITE"/PySide6/QtDesigner* \
    "$SITE"/PySide6/QtSql* "$SITE"/PySide6/QtTest* "$SITE"/PySide6/QtNetwork* \
    "$SITE"/PySide6/QtHelp* "$SITE"/PySide6/QtUiTools* "$SITE"/PySide6/QtOpenGLWidgets* \
    "$SITE"/PySide6/QtPrintSupport* "$SITE"/PySide6/QtConcurrent* "$SITE"/PySide6/QtXml* \
    "$SITE"/PySide6/QtPdf*
rm -f "$SITE"/anchorage*.dist-info/direct_url.json
# CPython parts a GUI application never needs.
LIB="$TREE/lib/python3.12"
rm -f "$LIB"/lib-dynload/_tkinter*
rm -rf "$LIB"/test "$LIB"/idlelib "$LIB"/tkinter "$LIB"/turtledemo "$LIB"/ensurepip "$LIB"/lib2to3 \
    "$TREE"/lib/tcl* "$TREE"/lib/tk* "$TREE"/lib/libtcl* "$TREE"/lib/libtk* "$TREE"/lib/itcl* \
    "$TREE"/lib/tdbc* "$TREE"/lib/thread* "$TREE"/share "$TREE"/include "$TREE"/bin/anchorage
# Entry points whose targets the trim removed.
rm -f "$TREE"/bin/idle3* "$TREE"/bin/2to3* "$TREE"/bin/python3*-config
# libxcb-cursor is needed by Qt's xcb platform plugin but RHEL 8 does not ship it (EPEL only), so
# the tree carries its one small library (MIT) from Debian 11; its own dependencies are ordinary.
(cd "$WORK/dl" && apt-get download libxcb-cursor0 >/dev/null && dpkg-deb -x libxcb-cursor0_*.deb cursor)
cp -L "$WORK/dl/cursor/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0" "$SITE/PySide6/Qt/lib/libxcb-cursor.so.0"
install -Dm644 "$WORK/dl/cursor/usr/share/doc/libxcb-cursor0/copyright" "$TREE/licenses/libxcb-cursor.copyright"
# Licenses of the bundled components. Debian's base-files carries the GNU texts.
LIC="$TREE/licenses"
mkdir -p "$LIC"
install -m644 /usr/share/common-licenses/LGPL-3 "$LIC/LGPL-3.0.txt"
install -m644 /usr/share/common-licenses/GPL-3 "$LIC/GPL-3.0.txt"
mv "$LIB/LICENSE.txt" "$LIC/CPython-LICENSE.txt"
QT_VERSION=$("$PY" -c 'from PySide6.QtCore import qVersion; print(qVersion())')
XCB_VERSION=$(dpkg-deb -f "$WORK"/dl/libxcb-cursor0_*.deb Version)
cat > "$LIC/THIRD-PARTY.md" <<EOF
# Third-party components bundled in this package

| Component | Version | License | Source |
| --- | --- | --- | --- |
| CPython (python-build-standalone) | $PBS_VERSION, release $PBS_RELEASE | PSF-2.0 (CPython-LICENSE.txt) | https://github.com/astral-sh/python-build-standalone/releases/tag/$PBS_RELEASE , https://www.python.org/ftp/python/$PBS_VERSION/ |
| Qt | $QT_VERSION | LGPL-3.0-only (LGPL-3.0.txt, GPL-3.0.txt) | https://download.qt.io/official_releases/qt/ , https://code.qt.io/cgit/qt/ |
| PySide6 (Essentials) | $PYSIDE_VERSION | LGPL-3.0-only (LGPL-3.0.txt, GPL-3.0.txt) | https://download.qt.io/official_releases/QtForPython/ , https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| shiboken6 | $PYSIDE_VERSION | LGPL-3.0-only (LGPL-3.0.txt, GPL-3.0.txt) | https://download.qt.io/official_releases/QtForPython/ , https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| libxcb-cursor | $XCB_VERSION (Debian 11 package libxcb-cursor0) | MIT (libxcb-cursor.copyright) | https://sources.debian.org/src/xcb-util-cursor/ , https://xcb.freedesktop.org/ |

The Qt and PySide6 libraries are shared libraries under site-packages/PySide6 and can be
replaced by another build of the same version. The source of each component is available
from the upstream locations above.
EOF
# Static libraries, build-time data, stubs, most Qt translations and test suites.
find "$TREE" -name '*.a' -delete
rm -rf "$LIB"/config-3.12-* "$SITE"/PySide6/include \
    "$SITE"/PySide6/typesystems "$SITE"/PySide6/glue "$SITE"/PySide6/scripts
find "$SITE"/PySide6 "$SITE"/shiboken6 -name '*.pyi' -delete
# Keep only the Qt dialog translations for the shipped interface languages.
find "$SITE"/PySide6/Qt/translations -type f \
    ! \( -name 'qtbase_ru.qm' -o -name 'qtbase_de.qm' -o -name 'qtbase_es.qm' \
    -o -name 'qtbase_fr.qm' -o -name 'qtbase_zh_CN.qm' \) -delete
find "$SITE" -type d \( -name test -o -name tests \) -prune -exec rm -rf {} +
find "$TREE" -name __pycache__ -type d -prune -exec rm -rf {} +
# Compile everything once, now that the tree is final: unchecked hash-based pycs are never
# rewritten at run time, and -s/-p record the install path instead of the build path. The
# interpreter must not write its own pycs while compiling (they would keep the build path).
PYTHONDONTWRITEBYTECODE=1 "$PY" -m compileall -q -j0 --invalidation-mode unchecked-hash -s "$WORK/tree" -p / "$TREE"
echo "tree after trim: $(du -sh "$TREE" | cut -f1)"
du -h --max-depth=5 "$TREE" | sort -h | tail -10
PYTHONDONTWRITEBYTECODE=1 "$PY" -I -m anchorage --version

# The tree must be relocatable: nothing may refer to where it was built or will be installed.
# (CPython's own sysconfig data names its upstream build directory /build/Python-*; that is
# inert data and not matched here; dist-info holds the README text, which mentions the install path.)
if grep -rIl --exclude-dir="*.dist-info" "$WORK/tree\|$WORK/dl\|/opt/anchorage" "$TREE" ; then
    echo "tree references the build or install path" >&2; exit 1
fi

# (Only our own build directories are matched: CPython's _sysconfigdata pyc keeps the inert
# upstream /build/Python-* string, like the sysconfig text data above.)
if grep -rl --include='*.pyc' "$WORK/tree\|$WORK/dl" "$TREE"; then
    echo "bytecode references the build path" >&2; exit 1
fi

# No absolute RUNPATH/RPATH either (only $ORIGIN-relative ones).
if find "$TREE" -type f \( -name '*.so*' -o -name python3 \) -print0 | xargs -0 readelf -d 2>/dev/null \
        | grep -E 'RUNPATH|RPATH' | grep '/build\|/opt/anchorage'; then
    echo "tree has an absolute RUNPATH/RPATH" >&2; exit 1
fi

# External sonames the tree needs (for rpm Requires and the ldd checks).
find "$TREE" -name '*.so*' -type f -print0 | xargs -0 objdump -p 2>/dev/null \
    | sed -n 's/^ *NEEDED *//p' | sort -u > "$WORK/needed.txt"
find "$TREE" -name '*.so*' -type f -printf '%f\n' | sort -u > "$WORK/bundled.txt"
grep -vxF -f "$WORK/bundled.txt" "$WORK/needed.txt" | grep -v '^ld-linux\|/' > "$WORK/external.txt" || true
echo "external sonames: $(tr '\n' ' ' < "$WORK/external.txt")"

echo "libxcb-cursor newest glibc symbol: $(objdump -T "$SITE/PySide6/Qt/lib/libxcb-cursor.so.0" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"

# Shared desktop files.
DATA="$WORK/tree/usr/share"
install -Dm644 "anchorage-$VERSION/data/$APP_ID.desktop" "$DATA/applications/$APP_ID.desktop"
install -Dm644 "anchorage-$VERSION/data/$APP_ID.metainfo.xml" "$DATA/metainfo/$APP_ID.metainfo.xml"
install -Dm644 "anchorage-$VERSION/src/anchorage/data/icon.svg" "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"
install -Dm644 "anchorage-$VERSION/LICENSE" "$DATA/doc/anchorage/copyright"
cat >> "$DATA/doc/anchorage/copyright" <<'EOF'

This package bundles CPython, Qt, PySide6, shiboken6 and libxcb-cursor under /opt/anchorage.
Their licenses, versions and upstream sources are in /opt/anchorage/licenses/ (see
THIRD-PARTY.md there).
EOF
mkdir -p "$WORK/tree/usr/bin"
cat > "$WORK/tree/usr/bin/anchorage" <<'EOF'
#!/bin/sh
unset LD_LIBRARY_PATH QT_PLUGIN_PATH
# The bundled Qt has only the gtk3 and xdgdesktopportal platform themes. Without one of them
# (Plasma's "kde" theme cannot load here) Qt ignores the desktop's dark preference.
case "${QT_QPA_PLATFORMTHEME:-}" in
    gtk3|xdgdesktopportal) ;;
    *)
        case "${XDG_CURRENT_DESKTOP:-}" in
            *GNOME*|*Unity*|*Cinnamon*|*MATE*|*XFCE*|*Pantheon*|*Budgie*) QT_QPA_PLATFORMTHEME=gtk3 ;;
            *) QT_QPA_PLATFORMTHEME=xdgdesktopportal ;;
        esac
        export QT_QPA_PLATFORMTHEME
        ;;
esac
exec /opt/anchorage/bin/python3 -I -B -m anchorage "$@"
EOF
chmod 755 "$WORK/tree/usr/bin/anchorage"

# --- deb --------------------------------------------------------------------------------
DEB="$WORK/deb"
cp -a "$WORK/tree" "$DEB"
mkdir -p "$DEB/DEBIAN"
DEPENDS=$(grep -v '^\s*$' /src/packaging/universal/debian-depends.txt | paste -sd, - | sed 's/,/, /g')
cat > "$DEB/DEBIAN/control" <<EOF
Package: anchorage
Version: $VERSION-1~universal
Section: utils
Priority: optional
Architecture: amd64
Maintainer: Pavel Makhnychev <pmakhnychev@gmail.com>
Installed-Size: $(du -sk "$DEB" | cut -f1)
Depends: $DEPENDS
Recommends: docker.io | docker-ce
Homepage: https://github.com/zexuzzzz/anchorage
Description: Native desktop client for Docker Engine (self-contained build)
 Anchorage talks to a local Docker Engine over its UNIX socket. It shows
 containers grouped by Compose project with live state, logs, resource
 charts and inspect details, manages images, volumes and networks, and
 opens a shell in a container in your terminal emulator.
 .
 This build carries its own Python and Qt under /opt/anchorage and runs on
 any x86_64 distribution with glibc 2.28 or newer.
EOF
dpkg-deb --root-owner-group --build "$DEB" "$WORK/anchorage_${VERSION}-1~universal_amd64.deb"

# --- rpm --------------------------------------------------------------------------------
RPMTOP="$WORK/rpmbuild"
mkdir -p "$RPMTOP"/{SPECS,BUILD,RPMS,SOURCES,BUILDROOT}
REQUIRES=$(sed 's/.*/Requires: &()(64bit)/' "$WORK/external.txt")
sed -e "s/@VERSION@/$VERSION/" -e "/@REQUIRES@/{r /dev/stdin
d}" /src/packaging/universal/anchorage-universal.spec <<< "$REQUIRES" > "$RPMTOP/SPECS/anchorage.spec"
rpmbuild --define "_topdir $RPMTOP" --define "_tree $WORK/tree" --target x86_64 -bb "$RPMTOP/SPECS/anchorage.spec"
RPM=$(ls "$RPMTOP"/RPMS/x86_64/anchorage-"$VERSION"-1~universal.x86_64.rpm)
rpm -qp --requires "$RPM" | head -40
rpm -qp --provides "$RPM"

# --- AppImage ---------------------------------------------------------------------------
APPDIR="$WORK/AppDir"
cp -a "$WORK/tree" "$APPDIR"
rm -rf "$APPDIR/usr/bin"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
unset LD_LIBRARY_PATH QT_PLUGIN_PATH
# The bundled Qt has only the gtk3 and xdgdesktopportal platform themes. Without one of them
# (Plasma's "kde" theme cannot load here) Qt ignores the desktop's dark preference.
case "${QT_QPA_PLATFORMTHEME:-}" in
    gtk3|xdgdesktopportal) ;;
    *)
        case "${XDG_CURRENT_DESKTOP:-}" in
            *GNOME*|*Unity*|*Cinnamon*|*MATE*|*XFCE*|*Pantheon*|*Budgie*) QT_QPA_PLATFORMTHEME=gtk3 ;;
            *) QT_QPA_PLATFORMTHEME=xdgdesktopportal ;;
        esac
        export QT_QPA_PLATFORMTHEME
        ;;
esac
exec "$HERE/opt/anchorage/bin/python3" -I -B -m anchorage "$@"
EOF
chmod 755 "$APPDIR/AppRun"
cp "$DATA/applications/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
cp "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
ln -sf "$APP_ID.svg" "$APPDIR/.DirIcon"
sed -i "s/^Exec=.*/Exec=anchorage/" "$APPDIR/$APP_ID.desktop"
echo "X-AppImage-Version=$VERSION" >> "$APPDIR/$APP_ID.desktop"
desktop-file-validate "$APPDIR/$APP_ID.desktop"
ARCH=x86_64 "$WORK/dl/appimagetool" --appimage-extract-and-run --comp zstd --runtime-file "$WORK/dl/runtime-x86_64" \
    "$APPDIR" "$WORK/Anchorage-$VERSION-x86_64.AppImage"

ls -l "$WORK"/*.deb "$RPM" "$WORK"/*.AppImage
publish "$WORK"/anchorage_"$VERSION"-1~universal_amd64.deb "$RPM" "$WORK"/Anchorage-"$VERSION"-x86_64.AppImage
