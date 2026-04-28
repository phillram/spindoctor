"""Duplicate detection — within-system + cross-system."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.dupes import (
    find_cross_system_duplicates,
    find_duplicates_in_system,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _make_config(roms_dir):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    save_config(cfg)
    return cfg


def test_no_duplicates_returns_empty(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Mario.nes").touch()
    (sys_dir / "Zelda.nes").touch()
    cfg = _make_config(tmp_path / "roms")

    assert find_duplicates_in_system("nes", cfg) == []


def test_title_collisions_grouped(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    # Region variants normalize to the same title
    (sys_dir / "Zelda (USA).nes").touch()
    (sys_dir / "Zelda (Japan).nes").touch()
    (sys_dir / "Mario.nes").touch()
    cfg = _make_config(tmp_path / "roms")

    groups = find_duplicates_in_system("nes", cfg)
    assert len(groups) == 1
    assert groups[0].count == 2
    assert groups[0].reason == "title"
    names = sorted(p.name for p in groups[0].files)
    assert names == ["Zelda (Japan).nes", "Zelda (USA).nes"]


def test_by_content_finds_renamed_copies(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"identical bytes" * 1024
    (sys_dir / "mario.nes").write_bytes(payload)
    (sys_dir / "Super Mario.nes").write_bytes(payload)
    # A different file should NOT be grouped
    (sys_dir / "Zelda.nes").write_bytes(b"different content" * 1024)
    cfg = _make_config(tmp_path / "roms")

    groups = find_duplicates_in_system("nes", cfg, by_content=True)
    content_groups = [g for g in groups if g.reason == "content"]
    assert len(content_groups) == 1
    assert content_groups[0].count == 2


def test_cross_system_detects_overlap(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    (roms / "nes").mkdir(parents=True)
    (roms / "snes").mkdir(parents=True)
    (roms / "nes" / "Tetris.nes").touch()
    (roms / "snes" / "Tetris.sfc").touch()
    (roms / "nes" / "Mario.nes").touch()
    cfg = _make_config(roms)

    matches = find_cross_system_duplicates(["nes", "snes"], cfg)
    assert len(matches) == 1
    assert matches[0].systems == ["nes", "snes"]


def test_cross_system_ignores_single_system_dupes(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    (roms / "nes").mkdir(parents=True)
    (roms / "nes" / "Zelda (USA).nes").touch()
    (roms / "nes" / "Zelda (Japan).nes").touch()
    (roms / "snes").mkdir(parents=True)
    cfg = _make_config(roms)

    # Two Zelda variants in the SAME system aren't a cross-system dupe.
    assert find_cross_system_duplicates(["nes", "snes"], cfg) == []
