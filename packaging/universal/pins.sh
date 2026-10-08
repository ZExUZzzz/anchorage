# Pinned downloads for the universal build. Update the version, URL and sha256 together.
PBS_RELEASE=20261003
PBS_VERSION=3.12.15
PBS_FILE="cpython-${PBS_VERSION}+${PBS_RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_FILE}"
PBS_SHA256=731af898886c5f821890dc901eca3c651cca8e51fa7308c159d12a1194aeac91
PYSIDE_VERSION=6.9.3   # last line with manylinux_2_28 wheels (glibc >= 2.28)
# The AppImage tools live on the project's own release first (the "continuous" upstream builds
# are replaced in place, so their content drifts); upstream is the fallback. The sha256 is checked either way.
TOOLS_URL=https://github.com/zexuzzzz/anchorage/releases/download/build-tools
APPIMAGETOOL_URL=$TOOLS_URL/appimagetool-x86_64.AppImage
APPIMAGETOOL_FALLBACK_URL=https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256=95cbe7cce9717fce90c484e34052ee7c7f1d7635b33c12525b4776826a7d29b6
RUNTIME_URL=$TOOLS_URL/runtime-x86_64
RUNTIME_FALLBACK_URL=https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64
RUNTIME_SHA256=156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074
