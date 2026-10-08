#!/usr/bin/env bash
# Build the Arch package with makepkg from the git archive tarball.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)

useradd -m builder
WORK=/home/builder/pkg
mkdir -p "$WORK"
cp /src/packaging/aur/PKGBUILD "$WORK/"
cp "/out/anchorage-$VERSION.tar.gz" "$WORK/"
# The AUR PKGBUILD fetches the release tarball; this build uses the local git archive.
sed -i "s|^source=.*|source=(\"anchorage-$VERSION.tar.gz\")|" "$WORK/PKGBUILD"
# Install the PKGBUILD's own dependency lists so they cannot drift from this script.
deps=$(bash -c 'source '"$WORK"'/PKGBUILD; echo "${depends[@]} ${makedepends[@]} ${checkdepends[@]}"')
pacman -Syu --noconfirm --needed base-devel $deps >/dev/null
chown -R builder:builder "$WORK"
su builder -c "cd $WORK && makepkg --noconfirm"
publish "$WORK"/anchorage-"$VERSION"-*.pkg.tar.zst
