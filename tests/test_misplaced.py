"""Misplaced-ROM detection: ROM extension does not match folder system."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.misplaced import find_misplaced_in_system


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _cfg(roms_dir):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    save_config(cfg)
    return cfg


def test_clean_folder_reports_nothing(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Mario.nes").touch()
    (sys_dir / "Zelda.zip").touch()  # generic container — allowed
    cfg = _cfg(tmp_path / "roms")

    assert find_misplaced_in_system("nes", cfg) == []


def test_wrong_extension_flagged_with_suggestions(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "snes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Mario.sfc").touch()      # legit
    (sys_dir / "Metroid.nes").touch()    # belongs to nes
    cfg = _cfg(tmp_path / "roms")

    found = find_misplaced_in_system("snes", cfg)
    assert len(found) == 1
    m = found[0]
    assert m.path.name == "Metroid.nes"
    assert m.extension == ".nes"
    assert "nes" in m.suggested_systems


def test_unknown_extensions_silently_skipped(isolated_config, tmp_path):
    """Random non-ROM files (.txt, .nfo) shouldn't be flagged — no system
    claims them, so flagging would be noise."""
    sys_dir = tmp_path / "roms" / "snes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Mario.sfc").touch()
    (sys_dir / "readme.txt").touch()
    (sys_dir / "info.nfo").touch()
    cfg = _cfg(tmp_path / "roms")

    assert find_misplaced_in_system("snes", cfg) == []


def test_missing_folder_returns_empty(isolated_config, tmp_path):
    cfg = _cfg(tmp_path / "roms")
    assert find_misplaced_in_system("nope", cfg) == []
