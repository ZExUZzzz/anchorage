Name:           anchorage
Version:        @VERSION@
Release:        1~universal
Summary:        Native desktop client for Docker Engine (self-contained build)
License:        MIT AND LGPL-3.0-only AND PSF-2.0
URL:            https://github.com/zexuzzzz/anchorage
AutoReqProv:    no
Requires:       glibc >= 2.28
Requires:       hicolor-icon-theme
@REQUIRES@
Recommends:     docker-cli

%global appid io.github.zexuzzzz.Anchorage
%global _build_id_links none
%global __brp_mangle_shebangs %{nil}
%global __brp_python_bytecompile %{nil}
%global __brp_strip %{nil}
%global __brp_strip_static_archive %{nil}
%global __brp_ldconfig %{nil}
%global debug_package %{nil}
%global _binary_payload w9.xzdio

%description
Anchorage talks to a local Docker Engine over its UNIX socket. It shows
containers grouped by Compose project with live state, logs, resource charts
and inspect details, manages images, volumes and networks, and opens a shell
in a container in your terminal emulator.

This build carries its own Python and Qt under /opt/anchorage and runs on any
x86_64 distribution with glibc 2.28 or newer.

%install
mkdir -p %{buildroot}
cp -a %{_tree}/. %{buildroot}/

%files
/opt/anchorage
%dir %{_datadir}/doc/anchorage
%{_bindir}/anchorage
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/metainfo/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%license %{_datadir}/doc/anchorage/copyright
