"""Wheel art for the helpers `install-tools --add-to-system` adds.

Every helper has a bundled logo, ``spindoctor/assets/toolkit_<key>.png``
(drawn by build/make_toolkit_art.py).  install-tools copies it to the wheel
when the wheel has none; uninstall-tools removes it only while it's still
SpinDoctor's own.  Cabinets are built under tmp_path.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import toolkit_helpers as th
from spindoctor.cli import cli
from spindoctor.config import Config

ASSETS = Path(__file__).resolve().parent.parent / "spindoctor" / "assets"


def _png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    width, height = struct.unpack(">II", data[16:24])
    color_type = data[25]
    return width, height, color_type


@pytest.mark.parametrize("helper", th.HELPERS, ids=lambda h: h.key)
def test_every_helper_has_a_400x156_transparent_logo(helper):
    path = ASSETS / f"toolkit_{helper.key}.png"
    assert path.is_file(), f"no wheel art for {helper.name}: run build/make_toolkit_art.py"
    assert _png_size(path) == (400, 156, 6)  # colour type 6: RGBA


def test_no_logo_without_a_helper():
    keys = {h.key for h in th.HELPERS}
    strays = [p.name for p in ASSETS.glob("toolkit_*.png") if p.stem[len("toolkit_"):] not in keys]
    assert strays == []


def test_builds_bundle_the_logos_with_the_gui_and_cli_only():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bw", Path(__file__).resolve().parent.parent / "build" / "build_windows.py")
    bw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bw)
    logo = ASSETS / "toolkit_refresh-favorites.png"
    assert bw._bundle_asset(logo, "spindoctor") and bw._bundle_asset(logo, "spindoctor-cli")
    assert not bw._bundle_asset(logo, "spindoctor-fav")  # the standalone wheel builders
    assert not bw._bundle_asset(logo, "spindoctor-stats")


# ── install-tools / uninstall-tools ──────────────────────────────────────────

@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    hs, rl = tmp_path / "hyperspin", tmp_path / "rocketlauncher"
    (hs / "Databases" / "Toolkit").mkdir(parents=True)
    (rl / "Settings").mkdir(parents=True)
    (hs / "Databases" / "Toolkit" / "Toolkit.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n', encoding="utf-8")
    config_mod.save_config(Config(roms_dir=str(tmp_path), hyperspin_dir=str(hs),
                                  rocketlauncher_dir=str(rl), emulators_dir=str(tmp_path)))
    yield hs / "Media" / "Toolkit" / "Images" / "Wheel"
    config_mod.reset_override_cache()


def _run(*args):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


def test_install_adds_the_logo_for_each_picked_entry(cabinet):
    result = _run("install-tools", "--tool", "shut-down-cabinet,refresh-all",
                  "--add-to-system", "Toolkit", "--apply")
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in cabinet.iterdir()) == ["Refresh All.png", "Shut Down Cabinet.png"]
    assert (cabinet / "Shut Down Cabinet.png").read_bytes() == \
        (ASSETS / "toolkit_shut-down-cabinet.png").read_bytes()
    assert "added wheel art for 2 entry(ies)" in result.output


def test_install_keeps_the_wheels_own_art(cabinet):
    cabinet.mkdir(parents=True)
    (cabinet / "Restart Cabinet.png").write_bytes(b"the cabinet's own logo")
    result = _run("install-tools", "--tool", "restart-cabinet", "--add-to-system", "Toolkit", "--apply")
    assert result.exit_code == 0, result.output
    assert (cabinet / "Restart Cabinet.png").read_bytes() == b"the cabinet's own logo"
    assert "kept the wheel art already there" in result.output


def test_dry_run_writes_no_art(cabinet):
    result = _run("install-tools", "--tool", "restart-cabinet", "--add-to-system", "Toolkit")
    assert result.exit_code == 0 and "wheel art" in result.output
    assert not cabinet.exists()


def test_uninstall_removes_only_spindoctors_own_logo(cabinet):
    assert _run("install-tools", "--tool", "restart-cabinet,exit-to-windows",
                "--add-to-system", "Toolkit", "--apply").exit_code == 0
    (cabinet / "Exit To Windows.png").write_bytes(b"replaced by hand")
    preview = _run("uninstall-tools", "--add-to-system", "Toolkit")
    assert "wheel art for 1 entry(ies)" in preview.output
    assert (cabinet / "Restart Cabinet.png").exists()  # a dry run removes nothing
    result = _run("uninstall-tools", "--add-to-system", "Toolkit", "--apply")
    assert result.exit_code == 0, result.output
    assert [p.name for p in cabinet.iterdir()] == ["Exit To Windows.png"]
