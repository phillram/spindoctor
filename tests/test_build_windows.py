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


def test_gui_keeps_xml_and_drag_drop_without_forcing_cli(bw):
    imports = set(bw.HIDDEN_IMPORTS["spindoctor-gui"])
    assert imports == {
        "spindoctor", "spindoctor.update_check", "spindoctor.gui",
        "lxml._elementpath", "lxml.etree", "tkinterdnd2",
    }
    assert "spindoctor.cli" in bw.HIDDEN_IMPORTS["spindoctor"]


def test_onefile_gui_does_not_force_cli_imports(bw, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bw.subprocess, "check_call", calls.append)
    bw.run_pyinstaller(tmp_path / "gui_entry.py", "spindoctor-gui", True)
    cmd, = calls
    imports = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--hidden-import"]
    assert imports == bw.HIDDEN_IMPORTS["spindoctor-gui"]
    assert "spindoctor.cli" not in imports
    assert "--windowed" in cmd


def test_onedir_gui_uses_the_same_lean_imports(bw, tmp_path):
    analyses = []

    def analysis(*args, **kwargs):
        from types import SimpleNamespace

        analyses.append(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    shims = {name: tmp_path / f"shim_{name}.py" for _, name, _ in bw.TARGETS}
    spec = bw.generate_onedir_spec(shims)
    namespace = dict(Analysis=analysis, PYZ=lambda *a: None,
                     EXE=lambda *a, **kw: None, COLLECT=lambda *a, **kw: None)
    exec(compile(spec.read_text(), str(spec), "exec"), namespace)
    gui_index = next(i for i, (_, name, _) in enumerate(bw.TARGETS) if name == "spindoctor-gui")
    gui_analysis = analyses[gui_index]
    assert gui_analysis["hiddenimports"] == bw.HIDDEN_IMPORTS["spindoctor-gui"]
    assert "spindoctor.cli" not in gui_analysis["hiddenimports"]
    assert gui_analysis["excludes"] == []


@pytest.mark.parametrize("name", [
    "spindoctor", "spindoctor-gui", "spindoctor-fav", "spindoctor-recent", "spindoctor-stats",
])
def test_shared_media_leaves_only_app_assets_embedded(bw, name):
    assert {p.name for p in bw.iter_bundle_assets(name, shared_media=True)} == {"icon.ico"}


def test_shared_media_copy_contains_one_complete_media_set(bw, tmp_path):
    dest = bw.copy_shared_media(tmp_path / "dist")
    expected = {p for p in bw.iter_bundle_assets("spindoctor") if bw._is_deployment_media(p)}
    assert {p.name for p in dest.iterdir()} == {p.name for p in expected}
    for source in expected:
        assert (dest / source.name).read_bytes() == source.read_bytes()
    assert not (dest / "archive").exists()
    assert not (dest / "icon.ico").exists()


def test_onefile_shared_media_omits_deployment_data(bw, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bw.subprocess, "check_call", calls.append)
    bw.run_pyinstaller(tmp_path / "cli_entry.py", "spindoctor", False, shared_media=True)
    cmd, = calls
    datas = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--add-data"]
    assert len(datas) == 1
    assert "icon.ico" in datas[0]


def test_onedir_shared_media_omits_deployment_data(bw, tmp_path):
    shims = {name: tmp_path / f"shim_{name}.py" for _, name, _ in bw.TARGETS}
    spec = bw.generate_onedir_spec(shims, shared_media=True).read_text()
    assert "icon.ico" in spec
    assert "bg_Favorites.png" not in spec
    assert "theme_blank.zip" not in spec


@pytest.mark.parametrize("modern", [False, True])
def test_main_routes_shared_media_and_copies_pack(bw, monkeypatch, tmp_path, modern):
    from unittest.mock import Mock

    monkeypatch.setattr(bw, "DIST", tmp_path / "dist")
    onefile, onedir = Mock(), Mock(return_value=tmp_path / "build.spec")
    monkeypatch.setattr(bw, "run_pyinstaller", onefile)
    monkeypatch.setattr(bw, "generate_onedir_spec", onedir)
    monkeypatch.setattr(bw.subprocess, "check_call", Mock())
    monkeypatch.setattr(bw.sys, "argv", ["build_windows.py", "--shared-media"] + (["--modern"] if modern else []))
    assert bw.main() == 0
    out_dir = bw.DIST / "spindoctor-win10" if modern else bw.DIST
    assert (out_dir / "spindoctor-media" / "bg_Favorites.png").read_bytes() == b"bg"
    if modern:
        assert onedir.call_args.kwargs["shared_media"] is True
        onefile.assert_not_called()
    else:
        assert onefile.call_count == len(bw.TARGETS)
        assert all(call.kwargs["shared_media"] is True for call in onefile.call_args_list)
        onedir.assert_not_called()
