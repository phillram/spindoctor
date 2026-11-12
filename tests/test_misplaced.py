"""Misplaced-ROM detection, auto-move, and undo.

Detection: a ROM's extension does not match its folder's system.
Apply: relocate flagged ROMs with a manifest, and undo the moves later.
"""
from __future__ import annotations
import json
from tests.helpers import write_bytes as _write_bytes

from spindoctor import misplaced


from spindoctor.config import Config, save_config
from spindoctor.misplaced import (
    apply_moves, find_latest_misplaced_manifest,
    find_misplaced_in_system, undo_moves,
)


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


# ─── apply_moves / undo_moves ─────────────────────────────────────────────────

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


def test_undo_retry_does_not_replay_already_completed_moves(isolated_config, tmp_path):
    first_src, first_dest = tmp_path / "one.zip", _write_bytes(tmp_path / "moved-one.zip")
    second_src = _write_bytes(tmp_path / "two.zip", b"conflicting")
    second_dest = _write_bytes(tmp_path / "moved-two.zip")
    manifest = _write_bytes(tmp_path / "undo.json", json.dumps({"moves": [
        {"src": str(first_src), "dest": str(first_dest)},
        {"src": str(second_src), "dest": str(second_dest)},
    ]}).encode())
    summary = misplaced.undo_moves(manifest)
    assert summary["reverted"] == 1 and summary["errors"]
    assert len(json.loads(manifest.read_text())["moves"]) == 1
    second_src.unlink()
    assert misplaced.undo_moves(manifest) == {"reverted": 1, "errors": []}
    assert first_src.exists() and second_src.exists() and not manifest.exists()
