"""Tests for bundled synthetic-wheel asset installers.

Covers install_system_wheel_art, install_system_background, install_system_music,
install_system_video, install_system_theme, and install_bundled_system_assets.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from spindoctor.rocketlauncher import (
    install_bundled_system_assets,
    install_system_background,
    install_system_music,
    install_system_theme,
    install_system_video,
    install_system_wheel_art,
)

SYNTHETIC = ("Favorites", "Most Played", "Recently Played")
NON_SYNTHETIC = "MAME"


# ── helpers ────────────────────────────────────────────────────────────────────

def _hs_dir(tmp_path: Path) -> Path:
    """Return a minimal HyperSpin root under tmp_path."""
    d = tmp_path / "HyperSpin"
    d.mkdir()
    return d


# ── install_system_theme ───────────────────────────────────────────────────────

class TestInstallSystemTheme:

    def test_installs_zip_to_correct_path(self, tmp_path):
        hs = _hs_dir(tmp_path)
        for system_name in SYNTHETIC:
            path, status = install_system_theme(hs, system_name, dry_run=False)
            dest = hs / "Media" / "Main Menu" / "Themes" / f"{system_name}.zip"
            assert status == "installed", f"{system_name}: expected 'installed', got {status!r}"
            assert dest.exists(), f"Theme zip not found at {dest}"
            assert path == dest

    def test_zip_contains_required_files(self, tmp_path):
        hs = _hs_dir(tmp_path)
        for system_name in SYNTHETIC:
            install_system_theme(hs, system_name, dry_run=False)
            dest = hs / "Media" / "Main Menu" / "Themes" / f"{system_name}.zip"
            with zipfile.ZipFile(dest) as zf:
                names = set(zf.namelist())
            assert "Theme.xml" in names, f"{system_name}: missing Theme.xml"
            assert "Info.txt"  in names, f"{system_name}: missing Info.txt"
            # No SWF files — following the MAME "Cinematic" minimal-theme pattern
            assert not any(n.endswith(".swf") for n in names), \
                f"{system_name}: unexpected SWF file(s) in theme zip: {names}"

    def test_theme_xml_has_video_element(self, tmp_path):
        hs = _hs_dir(tmp_path)
        for system_name in SYNTHETIC:
            install_system_theme(hs, system_name, dry_run=False)
            dest = hs / "Media" / "Main Menu" / "Themes" / f"{system_name}.zip"
            with zipfile.ZipFile(dest) as zf:
                xml = zf.read("Theme.xml").decode("utf-8")
            assert "<video" in xml.lower(), f"{system_name}: Theme.xml missing <video> element"

    def test_theme_xml_video_is_invisible(self, tmp_path):
        """Video element must be 1×1 px — audio plays, image hidden by background PNG."""
        hs = _hs_dir(tmp_path)
        install_system_theme(hs, "Favorites", dry_run=False)
        dest = hs / "Media" / "Main Menu" / "Themes" / "Favorites.zip"
        with zipfile.ZipFile(dest) as zf:
            xml = zf.read("Theme.xml").decode("utf-8")
        assert 'w="1"' in xml, "Video element width must be 1 (invisible)"
        assert 'h="1"' in xml, "Video element height must be 1 (invisible)"

    def test_skips_when_exists_and_overwrite_false(self, tmp_path):
        hs = _hs_dir(tmp_path)
        dest = hs / "Media" / "Main Menu" / "Themes" / "Favorites.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"user-placed-theme")

        _, status = install_system_theme(hs, "Favorites", dry_run=False, overwrite=False)
        assert status == "skipped"
        assert dest.read_bytes() == b"user-placed-theme", "Existing file was overwritten unexpectedly"

    def test_overwrites_when_overwrite_true(self, tmp_path):
        hs = _hs_dir(tmp_path)
        dest = hs / "Media" / "Main Menu" / "Themes" / "Favorites.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"user-placed-theme")

        _, status = install_system_theme(hs, "Favorites", dry_run=False, overwrite=True)
        assert status == "overwritten"
        # Should now be a real zip, not the placeholder bytes
        with zipfile.ZipFile(dest) as zf:
            assert "Theme.xml" in zf.namelist()

    def test_dry_run_does_not_write(self, tmp_path):
        hs = _hs_dir(tmp_path)
        path, status = install_system_theme(hs, "Favorites", dry_run=True)
        assert status == "dry_run"
        dest = hs / "Media" / "Main Menu" / "Themes" / "Favorites.zip"
        assert not dest.exists(), "dry_run must not write the file"

    def test_no_asset_for_non_synthetic_system(self, tmp_path):
        hs = _hs_dir(tmp_path)
        path, status = install_system_theme(hs, NON_SYNTHETIC)
        assert status == "no_asset"
        assert path is None


# ── install_bundled_system_assets ──────────────────────────────────────────────

class TestInstallBundledSystemAssets:

    def test_returns_all_five_keys(self, tmp_path):
        hs = _hs_dir(tmp_path)
        result = install_bundled_system_assets(hs, "Favorites", dry_run=True)
        assert set(result) == {"wheel_art", "background", "music", "video", "theme"}

    def test_all_assets_installed_for_synthetic(self, tmp_path):
        hs = _hs_dir(tmp_path)
        result = install_bundled_system_assets(hs, "Favorites", dry_run=False)
        # "music" is intentionally no_asset — attract-mode audio is in the MP4.
        expected = {
            "wheel_art": "installed",
            "background": "installed",
            "music": "no_asset",
            "video": "installed",
            "theme": "installed",
        }
        for key, expected_status in expected.items():
            _, status = result[key]
            assert status == expected_status, f"Key {key!r}: expected {expected_status!r}, got {status!r}"

    def test_theme_overwritten_when_overwrite_true(self, tmp_path):
        hs = _hs_dir(tmp_path)
        # First install
        install_bundled_system_assets(hs, "Favorites")
        # Second install with overwrite
        result = install_bundled_system_assets(hs, "Favorites", overwrite=True)
        assert result["theme"][1] == "overwritten"

    def test_theme_skipped_when_overwrite_false(self, tmp_path):
        hs = _hs_dir(tmp_path)
        install_bundled_system_assets(hs, "Favorites")
        result = install_bundled_system_assets(hs, "Favorites", overwrite=False)
        assert result["theme"][1] == "skipped"

    def test_non_synthetic_returns_no_asset_for_theme(self, tmp_path):
        hs = _hs_dir(tmp_path)
        result = install_bundled_system_assets(hs, NON_SYNTHETIC)
        assert result["theme"][1] == "no_asset"


# ── other individual installers smoke-test ─────────────────────────────────────

@pytest.mark.parametrize("system_name", SYNTHETIC)
def test_wheel_art_installs(tmp_path, system_name):
    hs = _hs_dir(tmp_path)
    _, status = install_system_wheel_art(hs, system_name)
    assert status == "installed"
    dest = hs / "Media" / "Main Menu" / "Images" / "Wheel" / f"{system_name}.png"
    assert dest.exists()


@pytest.mark.parametrize("system_name", SYNTHETIC)
def test_background_installs(tmp_path, system_name):
    hs = _hs_dir(tmp_path)
    _, status = install_system_background(hs, system_name)
    assert status == "installed"


@pytest.mark.parametrize("system_name", SYNTHETIC)
def test_music_returns_no_asset(tmp_path, system_name):
    # _MUSIC_ASSETS is intentionally empty — attract-mode audio is in the MP4.
    # Active-browsing (main-menu scrolling) plays silence.
    hs = _hs_dir(tmp_path)
    _, status = install_system_music(hs, system_name)
    assert status == "no_asset"


@pytest.mark.parametrize("system_name", SYNTHETIC)
def test_video_installs(tmp_path, system_name):
    hs = _hs_dir(tmp_path)
    _, status = install_system_video(hs, system_name)
    assert status == "installed"
