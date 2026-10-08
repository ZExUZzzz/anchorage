"""The desktop entry and the AppStream metainfo stay in step with the package."""

import configparser
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import anchorage
from anchorage import APP_ID

ROOT = Path(__file__).parents[1]
DESKTOP = ROOT / "data" / f"{APP_ID}.desktop"
METAINFO = ROOT / "data" / f"{APP_ID}.metainfo.xml"


def test_desktop_entry_fields() -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(DESKTOP)
    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Name"] == "Anchorage"
    assert entry["Exec"] == "anchorage"
    assert entry["Icon"] == APP_ID
    assert entry["Terminal"] == "false"
    assert "Development;" in entry["Categories"]


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="tool not installed")
def test_desktop_entry_validates() -> None:
    subprocess.run(["desktop-file-validate", str(DESKTOP)], check=True)


def test_metainfo_matches_package() -> None:
    root = ET.parse(METAINFO).getroot()
    assert root.get("type") == "desktop-application"
    assert root.findtext("id") == APP_ID
    assert root.findtext("project_license") == "MIT"
    assert root.findtext("launchable") == f"{APP_ID}.desktop"
    assert root.findtext("provides/binary") == "anchorage"
    release = root.find("releases/release")
    assert release is not None
    assert release.get("version") == anchorage.__version__


@pytest.mark.skipif(shutil.which("appstreamcli") is None, reason="tool not installed")
def test_metainfo_validates() -> None:
    subprocess.run(["appstreamcli", "validate", "--no-net", str(METAINFO)], check=True)


def test_license_is_mit() -> None:
    text = (ROOT / "LICENSE").read_text()
    assert text.startswith("MIT License")
    assert "Copyright (c) 2026" in text
