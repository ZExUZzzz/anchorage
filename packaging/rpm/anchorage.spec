Name:           anchorage
Version:        0.1.0
Release:        1%{?dist}
Summary:        Native desktop client for Docker Engine
License:        MIT
URL:            https://github.com/zexuzzzz/anchorage
Source0:        %{url}/archive/v%{version}/anchorage-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-hatchling
BuildRequires:  python3-pytest
BuildRequires:  python3-pytest-qt
BuildRequires:  python3-pyside6
BuildRequires:  qt6-qtsvg
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
Requires:       python3-pyside6
Requires:       qt6-qtsvg
Requires:       hicolor-icon-theme
Recommends:     qt6-qtwayland
Recommends:     docker-cli

%global appid io.github.zexuzzzz.Anchorage

%description
Anchorage talks to a local Docker Engine over its UNIX socket. It shows
containers grouped by Compose project with live state, logs, resource charts
and inspect details, manages images, volumes and networks, and opens a shell
in a container in your terminal emulator. It is a plain Qt application that
follows the desktop theme: no virtual machine, no web view.

%prep
%autosetup -n anchorage-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l anchorage
install -Dm644 data/%{appid}.desktop %{buildroot}%{_datadir}/applications/%{appid}.desktop
install -Dm644 data/%{appid}.metainfo.xml %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
install -Dm644 src/anchorage/data/icon.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
QT_QPA_PLATFORM=offscreen HOME=%{_builddir} %pytest -W error

%files -f %{pyproject_files}
%doc README.md CHANGELOG.md
%{_bindir}/anchorage
%{_datadir}/applications/%{appid}.desktop
%{_metainfodir}/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg

%changelog
* Thu Oct 08 2026 Pavel Makhnychev <pmakhnychev@gmail.com> - 0.1.0-1
- Initial package
