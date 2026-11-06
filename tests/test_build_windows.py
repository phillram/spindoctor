"""Regression tests for build/build_windows.py asset bundling.

build/ has no __init__.py (it's a standalone build script, not part of the
installed package), so the module is loaded directly from its file path.

The ~129 MB `spindoctor/assets/archive/` directory (deprecated originals)
must never be bundled. Both default targets are independent one-file EXEs.
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
        "name", ["spindoctor-cli", "spindoctor", "spindoctor-fav",
                 "spindoctor-recent", "spindoctor-stats"]
    )
    def test_never_bundles_the_archive_directory(self, bw, name):
        bundled = bw.iter_bundle_assets(name)
        assert all(p.is_file() for p in bundled), \
            f"{name}: iter_bundle_assets returned a non-file entry"
        assert not any(p.name == "archive" for p in bundled), \
            f"{name}: archive/ directory must never be bundled"

    def test_full_cli_gets_all_media(self, bw):
        names = {p.name for p in bw.iter_bundle_assets("spindoctor-cli")}
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

    def test_stats_gets_only_most_played_and_shared_media(self, bw):
        names = {p.name for p in bw.iter_bundle_assets("spindoctor-stats")}
        assert names == {"icon.ico", "navigate_sound.mp3", "theme_blank.zip"}

    def test_standalone_gui_embeds_all_media(self, bw):
        assert bw.iter_bundle_assets("spindoctor") == bw.iter_bundle_assets("spindoctor-cli")


class TestRunPyinstaller:
    """Every target is one independent file with no external runtime folder."""

    def _command(self, bw, monkeypatch, tmp_path, name, windowed):
        captured = []
        monkeypatch.setattr(bw.subprocess, "check_call", captured.append)
        bw.run_pyinstaller(tmp_path / "shim.py", name, windowed, out_dir=tmp_path / "dist")
        return captured[0]

    @pytest.mark.parametrize("_entry,name,windowed", [
        ("spindoctor._runtime:cli_main", "spindoctor-cli", False),
        ("spindoctor.gui:main", "spindoctor", True),
    ])
    def test_targets_are_independent_onefile_builds(
        self, bw, monkeypatch, tmp_path, _entry, name, windowed,
    ):
        cmd = self._command(bw, monkeypatch, tmp_path, name, windowed)
        text = " ".join(cmd)
        assert "--onefile" in cmd and "--onedir" not in cmd
        assert ("--windowed" if windowed else "--console") in cmd
        assert (bw.ASSETS_DIR / "archive").as_posix() not in text.replace("\\", "/")
        added = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--add-data"]
        assert len(added) == len(bw.iter_bundle_assets(name))

    def test_gui_bundles_embedded_workers(self, bw, monkeypatch, tmp_path):
        cmd = self._command(bw, monkeypatch, tmp_path, "spindoctor", True)
        hidden = {cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--hidden-import"}
        assert {
            "spindoctor._runtime", "spindoctor.cli", "spindoctor.favorites",
            "spindoctor.recent", "spindoctor.playtime", "spindoctor.gui",
        } <= hidden

    def test_default_targets_are_only_gui_and_cli(self, bw):
        assert [name for _, name, _ in bw.TARGETS] == ["spindoctor-cli", "spindoctor"]


@pytest.mark.parametrize("platform", ["win7", "win10"])
def test_release_archives_contain_only_the_selected_executable(tmp_path, platform):
    from zipfile import ZipFile

    spec = importlib.util.spec_from_file_location(
        "package_windows", _MODULE_PATH.with_name("package_windows.py"),
    )
    packaging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaging)
    dist = tmp_path / "dist"
    dist.mkdir()
    for name in ("spindoctor.exe", "spindoctor-cli.exe", "spindoctor-gui.exe", "stale-helper.exe"):
        (dist / name).write_bytes(name.encode())
    (dist / "_internal").mkdir()
    archives = packaging.package_windows(dist, tmp_path / "artifacts", platform, "v3.0.1")
    assert [p.name for p in archives] == [
        f"spindoctor-gui-{platform}-v3.0.1.zip",
        f"spindoctor-cli-{platform}-v3.0.1.zip",
    ]
    for archive, executable in zip(archives, ("spindoctor.exe", "spindoctor-cli.exe")):
        with ZipFile(archive) as bundle:
            assert bundle.namelist() == [executable]
            assert bundle.read(executable) == executable.encode()


def test_release_packaging_requires_both_executables_before_writing(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "package_windows", _MODULE_PATH.with_name("package_windows.py"),
    )
    packaging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaging)
    (tmp_path / "spindoctor.exe").write_bytes(b"gui")
    output = tmp_path / "artifacts"
    with pytest.raises(FileNotFoundError):
        packaging.package_windows(tmp_path, output, "win7", "v3.0.1")
    assert not output.exists()
    with pytest.raises(ValueError):
        packaging.package_windows(tmp_path, output, "win7", "../bad")
    with pytest.raises(ValueError):
        packaging.package_windows(tmp_path, output, "other", "v3.0.1")
