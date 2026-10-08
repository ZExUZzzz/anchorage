#!/usr/bin/env bash
# Build the Fedora package with rpmbuild from the git archive tarball.
source /src/packaging/common.sh
VERSION=$(version_from_pyproject)

dnf install -y -q rpm-build rpmdevtools dnf-plugins-core rpmlint >/dev/null
rpmdev-setuptree
cp /src/packaging/rpm/anchorage.spec ~/rpmbuild/SPECS/
cp "/out/anchorage-$VERSION.tar.gz" ~/rpmbuild/SOURCES/
dnf builddep -y -q ~/rpmbuild/SPECS/anchorage.spec >/dev/null
# Dynamic build requirements: a first pass writes them, the second pass builds.
# Exit 0: nothing missing. Exit 11: the buildreqs file was written. Anything else is a failure.
rc=0
rpmbuild -br ~/rpmbuild/SPECS/anchorage.spec || rc=$?
[ "$rc" -eq 0 ] || [ "$rc" -eq 11 ] || exit "$rc"
echo "rpmbuild -br exit code: $rc"
# The pass writes the file only when generated requirements are still missing.
if compgen -G ~/rpmbuild/SRPMS/anchorage-*.buildreqs.nosrc.rpm >/dev/null; then
    dnf builddep -y -q ~/rpmbuild/SRPMS/anchorage-*.buildreqs.nosrc.rpm >/dev/null
fi
rpmbuild -bb ~/rpmbuild/SPECS/anchorage.spec
rpmlint ~/rpmbuild/RPMS/noarch/anchorage-*.rpm || true
publish ~/rpmbuild/RPMS/noarch/anchorage-"$VERSION"-*.noarch.rpm
