"""Package metadata under packaging/ carries the version from pyproject."""

import re
from pathlib import Path

import anchorage

PACKAGING = Path(__file__).parents[1] / "packaging"


def _match(pattern: str, text: str) -> str:
    found = re.search(pattern, text, re.MULTILINE)
    assert found is not None, pattern
    return found.group(1)


def test_pkgbuild_version() -> None:
    text = (PACKAGING / "aur" / "PKGBUILD").read_text()
    assert _match(r"^pkgver=(.+)$", text) == anchorage.__version__


def test_srcinfo_version() -> None:
    text = (PACKAGING / "aur" / ".SRCINFO").read_text()
    assert _match(r"^\tpkgver = (.+)$", text) == anchorage.__version__


def test_debian_changelog_version() -> None:
    first = (PACKAGING / "debian" / "changelog").read_text().splitlines()[0]
    assert _match(r"^anchorage \((.+)-\d+\) ", first) == anchorage.__version__


def test_rpm_spec_version() -> None:
    text = (PACKAGING / "rpm" / "anchorage.spec").read_text()
    assert _match(r"^Version:\s+(.+)$", text) == anchorage.__version__
