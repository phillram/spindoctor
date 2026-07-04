"""Regression tests for build/build_windows.py asset bundling.

build/ has no __init__.py (it's a standalone build script, not part of the
installed package), so the module is loaded directly from its file path.

Covers the bug fixed in this PR: the modern (--onedir / Windows 10) spec
generator dropped the `.is_file()` guard that the Win7 (--onefile) path
kept, so the ~129 MB `spindoctor/assets/archive/` directory (deprecated
originals, deliberately excluded from every build) got recursively bundled
into the Win10 EXE only. `iter_bundle_assets()` is now the single filter
both build paths share, so this can't drift apart again.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "build" / "build_windows.py"


def _load_build_windows() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_windows", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def bw(tmp_path, monkeypatch):
    """A build_windows module instance pointed at a small fixture assets dir."""
    mod = _load_build_windows()

    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "icon.ico").write_bytes(b"icon")
    (assets / "bg_Favorites.png").write_bytes(b"bg")
    (assets / "bg_Recently_Played.png").write_bytes(b"bg")
    (assets / "music_Favorites.mp3").write_bytes(b"music")
    (assets / "navigate_sound.mp3").write_bytes(b"shared")
    (assets / "theme_blank.zip").write_bytes(b"shared")

    # The deprecated-originals folder that must never be bundled by any EXE,
    # on either build path. A directory whose name matches no media pattern
    # falls through _bundle_asset()'s "not media -> always include" branch,
    # which is exactly what let it leak into the Win10 build.
    archive = assets / "archive"
    archive.mkdir()
    (archive / "bg_Favorites.png").write_bytes(b"big original" * 1000)

    monkeypatch.setattr(mod, "ASSETS_DIR", assets)
    monkeypatch.setattr(mod, "ICON", tmp_path / "no-such-icon.ico")
    monkeypatch.setattr(mod, "BUILD", tmp_path / "build")
    return mod


class TestIterBundleAssets:

    @pytest.mark.parametrize(
        "name", ["spindoctor", "spindoctor-gui", "spindoctor-fav",
                 "spindoctor-recent", "spindoctor-stats"]
    )
    def test_never_bundles_the_archive_directory(self, bw, name):
        bundled = bw.iter_bundle_assets(name)
        assert all(p.is_file() for p in bundled), \
            f"{name}: iter_bundle_assets returned a non-file entry"
        assert not any(p.name == "archive" for p in bundled), \
            f"{name}: archive/ directory must never be bundled"

    def test_full_cli_gets_all_media(self, bw):
        names = {p.name for p in bw.iter_bundle_assets("spindoctor")}
        assert names == {
            "icon.ico", "bg_Favorites.png", "bg_Recently_Played.png",
            "music_Favorites.mp3", "navigate_sound.mp3", "theme_blank.zip",
        }

    def test_fav_gets_only_favorites_and_shared_media(self, bw):
        names = {p.name for p in bw.iter_bundle_assets("spindoctor-fav")}
        assert names == {
            "icon.ico", "bg_Favorites.png", "music_Favorites.mp3",
            "navigate_sound.mp3", "theme_blank.zip",
        }

    def test_recent_gets_only_recently_played_and_shared_media(self, bw):
        names = {p.name for p in bw.iter_bundle_assets("spindoctor-recent")}
        assert names == {
            "icon.ico", "bg_Recently_Played.png",
            "navigate_sound.mp3", "theme_blank.zip",
        }

    def test_gui_and_stats_get_no_deployment_media(self, bw):
        for name in ("spindoctor-gui", "spindoctor-stats"):
            names = {p.name for p in bw.iter_bundle_assets(name)}
            assert names == {"icon.ico"}, f"{name}: expected only icon.ico, got {names}"


class TestGenerateOnedirSpecExcludesArchive:
    """Exercise the actual --onedir spec-writing path, not just the helper."""

    def test_spec_text_never_references_the_archive_directory(self, bw, tmp_path):
        shims = {name: tmp_path / f"shim_{name}.py" for _, name, _ in bw.TARGETS}
        spec_path = bw.generate_onedir_spec(shims)
        text = spec_path.read_text()
        archive_path = (bw.ASSETS_DIR / "archive").as_posix()
        assert archive_path not in text, \
            "generate_onedir_spec() bundled the archive/ directory into a Win10 EXE"
