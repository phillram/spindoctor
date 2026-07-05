"""Tests for bundled synthetic-wheel asset installers.

Covers install_system_wheel_art, install_system_background, install_system_music,
install_system_video, install_system_theme, and install_bundled_system_assets.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from spindoctor.rocketlauncher import (
    fill_default_theme,
    fill_missing_themes,
    install_bundled_system_assets,
    install_system_background,
    install_system_music,
    install_system_navigate_sound,
    install_system_theme,
    install_system_video,
    install_system_wheel_art,
)

SYNTHETIC = ("Favorites", "Most Played", "Recently Played", "Recompiled")
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

    def test_zip_contains_only_theme_xml(self, tmp_path):
        """Zip must contain exactly Theme.xml and nothing else (matches reference)."""
        hs = _hs_dir(tmp_path)
        for system_name in SYNTHETIC:
            install_system_theme(hs, system_name, dry_run=False)
            dest = hs / "Media" / "Main Menu" / "Themes" / f"{system_name}.zip"
            with zipfile.ZipFile(dest) as zf:
                names = zf.namelist()
            assert names == ["Theme.xml"], \
                f"{system_name}: expected ['Theme.xml'], got {names}"

    def test_theme_xml_has_video_element(self, tmp_path):
        hs = _hs_dir(tmp_path)
        for system_name in SYNTHETIC:
            install_system_theme(hs, system_name, dry_run=False)
            dest = hs / "Media" / "Main Menu" / "Themes" / f"{system_name}.zip"
            with zipfile.ZipFile(dest) as zf:
                xml = zf.read("Theme.xml").decode("utf-8")
            assert "<video" in xml.lower(), f"{system_name}: Theme.xml missing <video> element"

    def test_theme_xml_video_is_fullscreen(self, tmp_path):
        """Video element must be full-screen (1024×768) centred at (512, 384)."""
        hs = _hs_dir(tmp_path)
        install_system_theme(hs, "Favorites", dry_run=False)
        dest = hs / "Media" / "Main Menu" / "Themes" / "Favorites.zip"
        with zipfile.ZipFile(dest) as zf:
            xml = zf.read("Theme.xml").decode("utf-8")
        assert 'w="1024"' in xml, "Video element width must be 1024 (full screen)"
        assert 'h="768"'  in xml, "Video element height must be 768 (full screen)"
        assert 'x="512"'  in xml, "Video element x must be 512 (centred)"
        assert 'y="384"'  in xml, "Video element y must be 384 (centred)"
        assert 'forceaspect="both"' in xml, "forceaspect must be 'both'"

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

    def test_returns_all_keys(self, tmp_path):
        hs = _hs_dir(tmp_path)
        result = install_bundled_system_assets(hs, "Favorites", dry_run=True)
        assert set(result) == {"wheel_art", "background", "music", "video", "theme", "navigate_sound"}

    def test_all_assets_installed_for_synthetic(self, tmp_path):
        hs = _hs_dir(tmp_path)
        result = install_bundled_system_assets(hs, "Favorites", dry_run=False)
        expected = {
            "wheel_art":      "installed",
            "background":     "installed",
            "music":          "installed",
            "video":          "installed",
            "theme":          "installed",
            "navigate_sound": "installed",
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
def test_music_installs(tmp_path, system_name):
    hs = _hs_dir(tmp_path)
    _, status = install_system_music(hs, system_name)
    assert status == "installed"


@pytest.mark.parametrize("system_name", SYNTHETIC)
def test_video_installs(tmp_path, system_name):
    hs = _hs_dir(tmp_path)
    _, status = install_system_video(hs, system_name)
    assert status == "installed"


@pytest.mark.parametrize("system_name", SYNTHETIC)
def test_navigate_sound_installs_as_wheel_click(tmp_path, system_name):
    hs = _hs_dir(tmp_path)
    dest, status = install_system_navigate_sound(hs, system_name)
    assert status == "installed"
    assert dest == hs / "Media" / system_name / "Sound" / "Wheel Click.mp3"
    assert dest.exists()


# ── fill_missing_themes ────────────────────────────────────────────────────────

class TestFillMissingThemes:

    def _make_video(self, hs: Path, system: str, name: str) -> None:
        video_dir = hs / "Media" / system / "Video"
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / f"{name}.mp4").write_bytes(b"fake")

    def _make_theme(self, hs: Path, system: str, name: str) -> None:
        themes_dir = hs / "Media" / system / "Themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        (themes_dir / f"{name}.zip").write_bytes(b"fake")

    def test_installs_blank_theme_for_video_without_theme(self, tmp_path):
        hs = _hs_dir(tmp_path)
        self._make_video(hs, "MAME", "Galaga")
        results = fill_missing_themes(hs, "MAME", dry_run=False)
        assert results["Galaga"] == "installed"
        assert (hs / "Media" / "MAME" / "Themes" / "Galaga.zip").exists()

    def test_skips_game_with_existing_theme(self, tmp_path):
        hs = _hs_dir(tmp_path)
        self._make_video(hs, "MAME", "Galaga")
        self._make_theme(hs, "MAME", "Galaga")
        results = fill_missing_themes(hs, "MAME", dry_run=False)
        assert results["Galaga"] == "skipped"

    def test_dry_run_does_not_write(self, tmp_path):
        hs = _hs_dir(tmp_path)
        self._make_video(hs, "MAME", "Galaga")
        results = fill_missing_themes(hs, "MAME", dry_run=True)
        assert results["Galaga"] == "dry_run"
        assert not (hs / "Media" / "MAME" / "Themes" / "Galaga.zip").exists()

    def test_empty_when_no_video_dir(self, tmp_path):
        hs = _hs_dir(tmp_path)
        results = fill_missing_themes(hs, "MAME", dry_run=False)
        assert results == {}

    def test_mixed_existing_and_missing(self, tmp_path):
        hs = _hs_dir(tmp_path)
        self._make_video(hs, "SNES", "Donkey Kong Country")
        self._make_video(hs, "SNES", "Super Mario World")
        self._make_theme(hs, "SNES", "Super Mario World")
        results = fill_missing_themes(hs, "SNES", dry_run=False)
        assert results["Donkey Kong Country"] == "installed"
        assert results["Super Mario World"] == "skipped"


# ── fill_default_theme ─────────────────────────────────────────────────────────

class TestFillDefaultTheme:

    def _default_path(self, hs: Path, system: str) -> Path:
        return hs / "Media" / system / "Themes" / "default.zip"

    def test_installs_default_when_absent(self, tmp_path):
        hs = _hs_dir(tmp_path)
        status = fill_default_theme(hs, "MAME", dry_run=False)
        assert status == "installed"
        assert self._default_path(hs, "MAME").exists()

    def test_creates_themes_dir_when_missing(self, tmp_path):
        hs = _hs_dir(tmp_path)
        # No Media/MAME/Themes/ directory exists yet.
        assert not (hs / "Media" / "MAME" / "Themes").exists()
        status = fill_default_theme(hs, "MAME", dry_run=False)
        assert status == "installed"
        assert self._default_path(hs, "MAME").exists()

    def test_skips_when_default_present(self, tmp_path):
        hs = _hs_dir(tmp_path)
        dest = self._default_path(hs, "MAME")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"user-placed-default")
        status = fill_default_theme(hs, "MAME", dry_run=False)
        assert status == "skipped"
        assert dest.read_bytes() == b"user-placed-default", "Existing default.zip was overwritten"

    def test_dry_run_does_not_write(self, tmp_path):
        hs = _hs_dir(tmp_path)
        status = fill_default_theme(hs, "MAME", dry_run=True)
        assert status == "dry_run"
        assert not self._default_path(hs, "MAME").exists()
