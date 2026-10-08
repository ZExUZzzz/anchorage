# Sourced before apt-get on Debian images. Debian 11 is end of life: its repositories live on
# archive.debian.org. A no-op on every other release.
if grep -q '^VERSION_ID="11"' /etc/os-release 2>/dev/null; then
    cat > /etc/apt/sources.list <<'LIST'
deb http://archive.debian.org/debian bullseye main
deb http://archive.debian.org/debian-security bullseye-security main
LIST
    rm -f /etc/apt/sources.list.d/*.list
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99archive
fi
