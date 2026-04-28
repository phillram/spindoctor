"""Auto-move + undo for misplaced ROMs."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.misplaced import (
    apply_moves, find_latest_misplaced_manifest,
    find_misplaced_in_system, undo_moves,
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


def _cfg(roms_dir):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    save_config(cfg)
    return cfg


def test_apply_moves_relocates_file_and_writes_manifest(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    (roms / "snes").mkdir(parents=True)
    (roms / "nes").mkdir()
    (roms / "snes" / "Metroid.nes").write_text("data", encoding="utf-8")
    cfg = _cfg(roms)

    items = find_misplaced_in_system("snes", cfg, known_systems=["nes", "snes"])
    assert len(items) == 1

    result, manifest = apply_moves(items, cfg)
    assert len(result.moved) == 1
    assert manifest is not None
    assert manifest.exists()
    assert (roms / "nes" / "Metroid.nes").exists()
    assert not (roms / "snes" / "Metroid.nes").exists()


def test_undo_reverses_the_move(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    (roms / "snes").mkdir(parents=True)
    (roms / "nes").mkdir()
    (roms / "snes" / "Metroid.nes").write_text("data", encoding="utf-8")
    cfg = _cfg(roms)

    items = find_misplaced_in_system("snes", cfg, known_systems=["nes", "snes"])
    _, manifest = apply_moves(items, cfg)

    summary = undo_moves(manifest)
    assert summary["reverted"] == 1
    assert (roms / "snes" / "Metroid.nes").exists()
    assert not (roms / "nes" / "Metroid.nes").exists()
    assert not manifest.exists()  # manifest cleaned up after undo


def test_skip_when_target_already_exists(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    (roms / "snes").mkdir(parents=True)
    (roms / "nes").mkdir()
    (roms / "snes" / "Metroid.nes").write_text("a", encoding="utf-8")
    (roms / "nes" / "Metroid.nes").write_text("b", encoding="utf-8")  # collision
    cfg = _cfg(roms)

    items = find_misplaced_in_system("snes", cfg, known_systems=["nes", "snes"])
    result, manifest = apply_moves(items, cfg)
    assert result.moved == []
    assert len(result.skipped) == 1
    assert manifest is None  # nothing applied → no manifest


def test_find_latest_manifest_picks_newest(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "_spindoctor-misplaced-20240101_000000.json").write_text("{}", encoding="utf-8")
    (roms / "_spindoctor-misplaced-20990101_000000.json").write_text("{}", encoding="utf-8")
    latest = find_latest_misplaced_manifest(roms)
    assert latest is not None
    assert latest.name.endswith("20990101_000000.json")
