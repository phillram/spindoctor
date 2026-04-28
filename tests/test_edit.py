"""Batch metadata editor + atomic game rename / clone."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import spindoctor.config as config_mod
import spindoctor.edit as edit_mod
from spindoctor.config import Config, save_config
from spindoctor.database import GameEntry, HyperspinDatabase
from spindoctor.edit import (
    EditChange, apply_batch_edit, apply_rename, build_filter,
    find_latest_edit_manifest, find_latest_rename_manifest,
    find_matching_games, list_edit_manifests, list_rename_manifests,
    parse_filter_clause, parse_year_range, plan_batch_edit, plan_rename,
    undo_batch_edit, undo_rename,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(edit_mod, "EDIT_DIR", home / "edits")
    monkeypatch.setattr(edit_mod, "RENAME_DIR", home / "renames")
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _build_cfg(tmp_path: Path) -> Config:
    """Create a synthetic NES system with 3 games + ROMs + a wheel/snap each."""
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    db_dir = hs_dir / "Databases" / "nes"
    media_dir = hs_dir / "Media" / "nes"
    db_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    (media_dir / "Images" / "Wheel").mkdir(parents=True)
    (media_dir / "Images" / "Artwork3").mkdir(parents=True)

    games = [
        GameEntry(name="mario", description="Super Mario", manufacturer="Nintendo",
                  year="1985", genre="Platformer", rating=""),
        GameEntry(name="zelda", description="Zelda", manufacturer="Nintendo",
                  year="1986", genre="Action", rating="5"),
        GameEntry(name="contra", description="Contra", manufacturer="Konami",
                  year="1988", genre="Action", rating=""),
    ]
    for g in games:
        (roms_dir / "nes" / f"{g.name}.nes").write_text("rom", encoding="utf-8")
        (media_dir / "Images" / "Wheel" / f"{g.name}.png").write_bytes(b"wheel")
        (media_dir / "Images" / "Artwork3" / f"{g.name}.png").write_bytes(b"snap")

    db = HyperspinDatabase("nes", db_dir / "nes.xml")
    for g in games:
        db.add_game(g)
    db.save()

    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)
    return cfg


# ─── filter parsing ───────────────────────────────────────────────────────────


def test_parse_filter_clause_basic():
    assert parse_filter_clause("genre=Action") == ("genre", "Action")
    assert parse_filter_clause(" name = *Mario* ") == ("name", "*Mario*")


def test_parse_filter_clause_rejects_no_equals():
    with pytest.raises(ValueError):
        parse_filter_clause("garbage")


def test_parse_year_range_variants():
    assert parse_year_range("1980-1989") == (1980, 1989)
    assert parse_year_range("1986") == (1986, 1986)
    assert parse_year_range("1980-") == (1980, 9999)
    assert parse_year_range("-1989") == (0, 1989)
    with pytest.raises(ValueError):
        parse_year_range("1990-1980")


def test_build_filter_unknown_key_raises():
    with pytest.raises(ValueError):
        build_filter("nes", ["bogus=value"])


def test_build_filter_unknown_missing_field_raises():
    with pytest.raises(ValueError):
        build_filter("nes", ["missing=cloneof"])


# ─── filtered selection ───────────────────────────────────────────────────────


def test_find_matching_games_filter_by_genre(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    f = build_filter("nes", ["genre=Action"])
    matches = sorted(g.name for g in find_matching_games(cfg, f))
    assert matches == ["contra", "zelda"]


def test_find_matching_games_filter_by_missing_field(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    f = build_filter("nes", ["missing=rating"])
    matches = sorted(g.name for g in find_matching_games(cfg, f))
    assert matches == ["contra", "mario"]


def test_find_matching_games_filter_by_year_range(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    f = build_filter("nes", ["year=1985-1986"])
    matches = sorted(g.name for g in find_matching_games(cfg, f))
    assert matches == ["mario", "zelda"]


def test_find_matching_games_filter_by_name_glob(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    f = build_filter("nes", ["name=mar*"])
    matches = sorted(g.name for g in find_matching_games(cfg, f))
    assert matches == ["mario"]


def test_find_matching_games_filter_combined(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    f = build_filter("nes", ["genre=Action", "manufacturer=Nintendo"])
    matches = sorted(g.name for g in find_matching_games(cfg, f))
    assert matches == ["zelda"]


# ─── batch edit apply / undo ──────────────────────────────────────────────────


def test_plan_batch_edit_set_and_clear():
    games = [GameEntry(name="a", rating="3", genre="Old")]
    plan = plan_batch_edit(
        games,
        [EditChange("rating", "5", "set"),
         EditChange("genre", "", "clear")],
    )
    assert plan["a"]["rating"] == ("3", "5")
    assert plan["a"]["genre"] == ("Old", "")


def test_plan_batch_edit_append_prepend():
    games = [GameEntry(name="a", description="Game")]
    plan = plan_batch_edit(
        games,
        [EditChange("description", " (USA)", "append")],
    )
    assert plan["a"]["description"][1].endswith("(USA)")

    plan2 = plan_batch_edit(
        games,
        [EditChange("description", "Old", "prepend")],
    )
    assert plan2["a"]["description"][1].startswith("Old ")


def test_plan_batch_edit_no_op_skipped():
    games = [GameEntry(name="a", rating="5")]
    plan = plan_batch_edit(games, [EditChange("rating", "5", "set")])
    assert plan == {}


def test_apply_batch_edit_round_trip(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    f = build_filter("nes", ["genre=Action"])
    games = find_matching_games(cfg, f)
    assert {g.name for g in games} == {"zelda", "contra"}

    results, manifest = apply_batch_edit(
        cfg, "nes", games, [EditChange("rating", "5", "set")],
    )
    assert manifest is not None and manifest.exists()
    edited = {r.game_name for r in results if not r.skipped}
    # Zelda was already 5 → no-op; contra moves from "" to "5"
    assert "contra" in edited

    # Verify on disk
    games_after = {g.name: g for g in find_matching_games(cfg, build_filter("nes", []))}
    assert games_after["contra"].rating == "5"
    assert games_after["zelda"].rating == "5"

    # Backup file landed alongside the DB
    backups = list((Path(cfg.hyperspin_dir) / "Databases" / "nes").glob("*.bak"))
    assert backups, "expected save() to write a .bak"

    # Undo restores the previous state
    undo_results = undo_batch_edit(manifest, cfg)
    assert any(r.game_name == "contra" and not r.skipped for r in undo_results)
    games_post_undo = {g.name: g for g in find_matching_games(cfg, build_filter("nes", []))}
    assert games_post_undo["contra"].rating == ""
    assert not manifest.exists()


def test_list_edit_manifests_after_apply(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    games = find_matching_games(cfg, build_filter("nes", ["name=mario"]))
    apply_batch_edit(cfg, "nes", games, [EditChange("rating", "4", "set")])
    manifests = list_edit_manifests()
    assert len(manifests) == 1
    assert find_latest_edit_manifest() == manifests[-1]


# ─── rename ───────────────────────────────────────────────────────────────────


def test_plan_rename_lists_rom_db_and_media(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    plan = plan_rename(cfg, "nes", "mario", "mario_v2")
    kinds = {ch.kind for ch in plan.file_changes}
    assert {"rom", "db", "media"}.issubset(kinds)
    media_types = {ch.media_type for ch in plan.file_changes if ch.kind == "media"}
    assert "wheel" in media_types
    assert "snap" in media_types


def test_plan_rename_rejects_existing_target(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    with pytest.raises(ValueError):
        plan_rename(cfg, "nes", "mario", "zelda")


def test_apply_rename_moves_rom_db_and_media(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    plan = plan_rename(cfg, "nes", "mario", "super_mario_bros")
    applied, manifest = apply_rename(plan, cfg)
    assert manifest is not None and manifest.exists()

    # ROM moved
    assert not (Path(cfg.roms_dir) / "nes" / "mario.nes").exists()
    assert (Path(cfg.roms_dir) / "nes" / "super_mario_bros.nes").exists()

    # Media moved
    media_root = Path(cfg.hyperspin_dir) / "Media" / "nes" / "Images"
    assert not (media_root / "Wheel" / "mario.png").exists()
    assert (media_root / "Wheel" / "super_mario_bros.png").exists()
    assert (media_root / "Artwork3" / "super_mario_bros.png").exists()

    # DB updated
    games = {g.name: g for g in find_matching_games(cfg, build_filter("nes", []))}
    assert "mario" not in games
    assert "super_mario_bros" in games


def test_apply_rename_undo_round_trip(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    plan = plan_rename(cfg, "nes", "mario", "super_mario_bros")
    _, manifest = apply_rename(plan, cfg)

    undo_rename(manifest, cfg)

    assert (Path(cfg.roms_dir) / "nes" / "mario.nes").exists()
    media_root = Path(cfg.hyperspin_dir) / "Media" / "nes" / "Images"
    assert (media_root / "Wheel" / "mario.png").exists()

    games = {g.name: g for g in find_matching_games(cfg, build_filter("nes", []))}
    assert "mario" in games
    assert "super_mario_bros" not in games
    assert not manifest.exists()


# ─── clone ────────────────────────────────────────────────────────────────────


def test_apply_clone_preserves_original(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    plan = plan_rename(cfg, "nes", "mario", "mario (Hack)", clone=True)
    applied, manifest = apply_rename(plan, cfg)
    assert manifest is not None and manifest.exists()

    # Original ROM stayed put
    assert (Path(cfg.roms_dir) / "nes" / "mario.nes").exists()
    assert (Path(cfg.roms_dir) / "nes" / "mario (Hack).nes").exists()

    # Media files duplicated
    wheel_dir = Path(cfg.hyperspin_dir) / "Media" / "nes" / "Images" / "Wheel"
    assert (wheel_dir / "mario.png").exists()
    assert (wheel_dir / "mario (Hack).png").exists()

    # DB has both entries
    games = {g.name: g for g in find_matching_games(cfg, build_filter("nes", []))}
    assert "mario" in games
    assert "mario (Hack)" in games

    # Manifest records clone=True
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["clone"] is True


def test_apply_clone_undo_removes_only_copies(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    plan = plan_rename(cfg, "nes", "mario", "mario (Hack)", clone=True)
    _, manifest = apply_rename(plan, cfg)

    undo_rename(manifest, cfg)

    # Original survived
    assert (Path(cfg.roms_dir) / "nes" / "mario.nes").exists()
    # Copy is gone
    assert not (Path(cfg.roms_dir) / "nes" / "mario (Hack).nes").exists()
    wheel_dir = Path(cfg.hyperspin_dir) / "Media" / "nes" / "Images" / "Wheel"
    assert not (wheel_dir / "mario (Hack).png").exists()

    # DB only has the original
    games = {g.name: g for g in find_matching_games(cfg, build_filter("nes", []))}
    assert "mario" in games
    assert "mario (Hack)" not in games


def test_list_rename_manifests_after_apply(isolated_config, tmp_path):
    cfg = _build_cfg(tmp_path)
    plan = plan_rename(cfg, "nes", "mario", "renamed")
    apply_rename(plan, cfg)
    manifests = list_rename_manifests()
    assert len(manifests) == 1
    assert find_latest_rename_manifest() == manifests[-1]
