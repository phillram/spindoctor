"""Orphan-media detection: media files whose game is gone."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.orphan_media import find_orphan_media


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _layout(tmp_path, db_text=None, roms=()):
    """Build a minimal HyperSpin tree with one system."""
    hs = tmp_path / "hs"
    roms_dir = tmp_path / "roms"
    sys_dir = roms_dir / "nes"
    sys_dir.mkdir(parents=True)
    for r in roms:
        (sys_dir / r).touch()

    db_dir = hs / "Databases" / "nes"
    db_dir.mkdir(parents=True)
    (db_dir / "nes.xml").write_text(
        db_text or "<menu></menu>", encoding="utf-8"
    )

    media = hs / "Media" / "nes"
    (media / "Images" / "Wheel").mkdir(parents=True)
    (media / "Video").mkdir(parents=True)
    (media / "Themes").mkdir(parents=True)
    return roms_dir, hs


def _cfg(roms_dir, hs_dir):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)
    return cfg


def test_no_orphans_when_assets_match_games(isolated_config, tmp_path):
    db = "<menu><game name=\"Mario\"><description>Mario</description></game></menu>"
    roms_dir, hs = _layout(tmp_path, db_text=db, roms=["Mario.nes"])
    (hs / "Media" / "nes" / "Images" / "Wheel" / "Mario.png").touch()
    cfg = _cfg(roms_dir, hs)

    report = find_orphan_media("nes", cfg)
    assert report.orphans == []


def test_orphan_wheel_flagged(isolated_config, tmp_path):
    db = "<menu><game name=\"Mario\"><description>Mario</description></game></menu>"
    roms_dir, hs = _layout(tmp_path, db_text=db, roms=["Mario.nes"])
    (hs / "Media" / "nes" / "Images" / "Wheel" / "Zelda.png").touch()
    cfg = _cfg(roms_dir, hs)

    report = find_orphan_media("nes", cfg)
    assert len(report.orphans) == 1
    assert report.orphans[0].stem == "Zelda"
    assert report.orphans[0].media_type == "Wheel"


def test_theme_folder_orphan_flagged(isolated_config, tmp_path):
    db = "<menu><game name=\"Mario\"><description>Mario</description></game></menu>"
    roms_dir, hs = _layout(tmp_path, db_text=db, roms=["Mario.nes"])
    (hs / "Media" / "nes" / "Themes" / "OldGame").mkdir()
    cfg = _cfg(roms_dir, hs)

    report = find_orphan_media("nes", cfg)
    assert any(o.media_type == "Themes" and o.stem == "OldGame"
               for o in report.orphans)


def test_rom_only_game_is_not_orphan(isolated_config, tmp_path):
    """A wheel for a ROM that exists but isn't in the DB still counts."""
    roms_dir, hs = _layout(tmp_path, roms=["Tetris.nes"])
    (hs / "Media" / "nes" / "Images" / "Wheel" / "Tetris.png").touch()
    cfg = _cfg(roms_dir, hs)

    assert find_orphan_media("nes", cfg).orphans == []
