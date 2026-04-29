"""End-to-end smoke test for `spindoctor add-pc-system`.

Uses Click's CliRunner with a temp HOME so all writes (config.json,
HyperSpin XMLs, RocketLauncher INIs, PCLauncher INIs) land under
tmp_path.  Network calls (system-media fetch) are disabled with --no-system-media.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
import spindoctor.matcher as matcher_mod
import spindoctor.pc_titles as pc_titles_mod
from spindoctor.cli import cli


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    """Set up a fake HyperSpin/RocketLauncher cabinet under tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json",
    )
    monkeypatch.setattr(
        pc_titles_mod, "CACHE_DIR", home / ".spindoctor" / "pc_titles_cache",
    )
    monkeypatch.setattr(
        matcher_mod, "CACHE_DIR", home / ".spindoctor" / "match_cache",
    )
    monkeypatch.setattr(
        matcher_mod, "MEDIA_CACHE_DIR", home / ".spindoctor" / "media_pick_cache",
    )
    config_mod.reset_override_cache()

    roms = tmp_path / "roms"
    hs = tmp_path / "hyperspin"
    rl = tmp_path / "rocketlauncher"
    for d in (roms, hs / "Databases", hs / "Media", rl / "Settings"):
        d.mkdir(parents=True)

    # Drop a few PC games into roms/PC Games/.
    pc_dir = roms / "PC Games"
    pc_dir.mkdir()
    (pc_dir / "Cyberpunk 2077").mkdir()
    (pc_dir / "Cyberpunk 2077" / "bin").mkdir()
    (pc_dir / "Cyberpunk 2077" / "bin" / "launcher.exe").touch()
    (pc_dir / "Hades.lnk").touch()

    cfg = config_mod.Config(
        roms_dir=str(roms),
        hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
        emulators_dir=str(tmp_path / "emulators"),
    )
    config_mod.save_config(cfg)
    yield {"roms": roms, "hs": hs, "rl": rl, "home": home}
    config_mod.reset_override_cache()


def test_add_pc_system_writes_overrides_db_and_pclauncher_inis(
    cabinet, monkeypatch,
):
    # Accept all proposed titles (empty input).
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "add-pc-system", "PC Games",
            "--no-system-media",
            "--no-game-media",
            "--apply",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # 1. Config gained the override entry with PC defaults.
    cfg = config_mod.load_config()
    entry = cfg.system_overrides["PC Games"]
    assert entry["recursive_scan"] is True
    assert entry["title_strategy"] == "smart"
    assert entry["emulator"] == "PCLauncher"
    assert ".exe" in entry["rom_extensions"]

    # 2. Main Menu got the system tile.
    main_menu = cabinet["hs"] / "Databases" / "Main Menu" / "Main Menu.xml"
    assert main_menu.exists()
    assert "PC Games" in main_menu.read_text(encoding="utf-8")

    # 3. Per-system DB written with the *derived* titles, not filenames.
    sys_db = cabinet["hs"] / "Databases" / "PC Games" / "PC Games.xml"
    assert sys_db.exists()
    body = sys_db.read_text(encoding="utf-8")
    assert 'name="Cyberpunk 2077"' in body
    assert 'name="Hades"' in body
    assert 'name="launcher"' not in body  # bare exe filename must NOT leak

    # 4. PCLauncher INIs written under Modules/PCLauncher/PC Games/.
    pcl_dir = cabinet["rl"] / "Modules" / "PCLauncher" / "PC Games"
    cyber_ini = pcl_dir / "Cyberpunk 2077.ini"
    hades_ini = pcl_dir / "Hades.ini"
    assert cyber_ini.exists()
    assert hades_ini.exists()
    assert "launcher.exe" in cyber_ini.read_text(encoding="utf-8")
    assert "Hades.lnk" in hades_ini.read_text(encoding="utf-8")


def test_add_pc_system_dry_run_writes_nothing(cabinet):
    """Default invocation (no --apply) is a dry-run preview."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "add-pc-system", "PC Games",
            "--no-system-media",
            "--no-game-media",
            "--no-rename",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # No override persisted, no DB, no INIs.
    cfg = config_mod.load_config()
    assert "PC Games" not in cfg.system_overrides
    assert not (cabinet["hs"] / "Databases" / "PC Games" / "PC Games.xml").exists()
    assert not (cabinet["rl"] / "Modules" / "PCLauncher" / "PC Games").exists()


def test_add_pc_system_no_rename_accepts_proposals(cabinet):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "add-pc-system", "PC Games",
            "--no-system-media",
            "--no-game-media",
            "--no-rename",
            "--apply",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    sys_db = cabinet["hs"] / "Databases" / "PC Games" / "PC Games.xml"
    assert sys_db.exists()
    body = sys_db.read_text(encoding="utf-8")
    assert 'name="Cyberpunk 2077"' in body
    assert 'name="Hades"' in body
