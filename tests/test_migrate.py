"""Plan / apply / undo round-trips for the drive migration command."""
from __future__ import annotations

from pathlib import Path

import pytest

import spindoctor.config as config_mod
import spindoctor.migrate as migrate_mod
from spindoctor.config import Config, load_config, save_config
from spindoctor.migrate import (
    apply_migration, find_latest_manifest, list_manifests, normalize_components,
    plan_migration, undo_migration,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(migrate_mod, "MIGRATIONS_DIR", home / "migrations")
    monkeypatch.setattr(migrate_mod, "CONFIG_DIR", home)
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _touch(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _seed_library(tmp_path: Path) -> Config:
    roms = tmp_path / "old" / "ROMs"
    hyperspin = tmp_path / "old" / "HyperSpin"
    emulators = tmp_path / "old" / "Emulators"
    _touch(roms / "MAME" / "pacman.zip")
    _touch(roms / "SNES" / "Chrono Trigger.sfc")
    _touch(hyperspin / "Databases" / "MAME" / "MAME.xml", "<menu/>")
    _touch(hyperspin / "Media" / "MAME" / "Images" / "Wheel" / "pacman.png")
    _touch(emulators / "MAME" / "mame.exe")
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hyperspin)
    cfg.emulators_dir = str(emulators)
    save_config(cfg)
    return cfg


# ─── normalize_components ─────────────────────────────────────────────────────


def test_normalize_aliases():
    assert normalize_components(["games", "media"]) == ["roms", "hyperspin"]
    assert normalize_components(["all"]) == [
        "roms", "hyperspin", "emulators", "rocketlauncher", "ledblinky",
    ]
    assert normalize_components(["roms", "ROMS", "games"]) == ["roms"]


def test_normalize_unknown():
    with pytest.raises(ValueError):
        normalize_components(["nonsense"])


# ─── plan_migration ───────────────────────────────────────────────────────────


def test_plan_skips_unconfigured_components(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms", "hyperspin", "ledblinky"])
    components = {m.component for m in plan.moves}
    assert components == {"roms", "hyperspin"}
    assert any("ledblinky" in s for s in plan.skipped)


def test_plan_full_components_marks_config_updates(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms", "hyperspin"])
    assert plan.config_updates["roms_dir"] == str(target / "Games")
    assert plan.config_updates["hyperspin_dir"] == str(target / "HyperSpin")


def test_plan_per_system_filter_does_not_update_config(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms"], systems_filter=["MAME"])
    # Single move for the MAME system only.
    assert len(plan.moves) == 1
    assert plan.moves[0].src.endswith("MAME")
    # roms_dir is left alone — user is splitting their library.
    assert "roms_dir" not in plan.config_updates


def test_plan_skips_when_target_exists_and_nonempty(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    # Pre-populate target Games/ with a stray file.
    _touch(target / "Games" / "stray.txt")
    plan = plan_migration(cfg, target, ["roms"])
    assert plan.empty
    assert any("already exists" in s for s in plan.skipped)


def test_preserve_names_uses_original_basename(isolated_config, tmp_path):
    # Seed a library with non-standard folder names.
    roms = tmp_path / "old" / "MyGames"
    hs = tmp_path / "old" / "HS"
    _touch(roms / "MAME" / "pacman.zip")
    _touch(hs / "Databases" / "MAME" / "MAME.xml", "<menu/>")
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hs)
    save_config(cfg)

    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms", "hyperspin"], preserve_names=True)
    dests = {m.component: m.dest for m in plan.moves}
    assert dests["roms"] == str(target / "MyGames")
    assert dests["hyperspin"] == str(target / "HS")
    # Config update map reflects the preserved names.
    assert plan.config_updates["roms_dir"] == str(target / "MyGames")
    assert plan.config_updates["hyperspin_dir"] == str(target / "HS")


def test_preserve_names_collision_is_skipped(isolated_config, tmp_path):
    # Two components pointing at folders with the same basename.
    roms = tmp_path / "drive_a" / "Cab"
    emu = tmp_path / "drive_b" / "Cab"
    _touch(roms / "MAME" / "pacman.zip")
    _touch(emu / "MAME" / "mame.exe")
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.emulators_dir = str(emu)
    save_config(cfg)

    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms", "emulators"], preserve_names=True)
    # First wins; second is skipped with a clear message.
    components_moved = [m.component for m in plan.moves]
    assert components_moved == ["roms"]
    assert any("collide" in s for s in plan.skipped)


# ─── apply / undo round trips ─────────────────────────────────────────────────


def test_apply_moves_and_updates_config(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms", "hyperspin"])
    manifest = apply_migration(plan)

    # Files are at the new location.
    assert (target / "Games" / "MAME" / "pacman.zip").exists()
    assert (target / "HyperSpin" / "Databases" / "MAME" / "MAME.xml").exists()
    # Originals are gone.
    assert not (tmp_path / "old" / "ROMs").exists()
    assert not (tmp_path / "old" / "HyperSpin").exists()
    # Config now points at the target.
    refreshed = load_config()
    assert refreshed.roms_dir == str(target / "Games")
    assert refreshed.hyperspin_dir == str(target / "HyperSpin")
    # Manifest exists under the migrations dir.
    assert manifest.exists()
    assert manifest in list_manifests()


def test_apply_then_undo_round_trip(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    original_roms = cfg.roms_dir
    target = tmp_path / "new"

    plan = plan_migration(cfg, target, ["roms", "hyperspin"])
    manifest = apply_migration(plan)
    assert (target / "Games" / "MAME" / "pacman.zip").exists()

    summary = undo_migration(manifest)
    assert summary["moves_reverted"] == 2
    assert summary["config_restored"] is True
    assert not manifest.exists()

    # Files are back where they came from.
    assert (Path(original_roms) / "MAME" / "pacman.zip").exists()
    # Config restored to the pre-migration snapshot.
    after = load_config()
    assert after.roms_dir == original_roms


def test_keep_source_copies_without_deleting(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms"])
    manifest = apply_migration(plan, keep_source=True, verify=True)

    # Both source and destination exist.
    assert (Path(cfg.roms_dir) / "MAME" / "pacman.zip").exists()
    assert (target / "Games" / "MAME" / "pacman.zip").exists()
    # Config is NOT updated in keep-source mode.
    refreshed = load_config()
    assert refreshed.roms_dir == cfg.roms_dir

    # Undo removes the copy and leaves the source alone.
    summary = undo_migration(manifest)
    assert summary["destinations_removed"] >= 1
    assert (Path(cfg.roms_dir) / "MAME" / "pacman.zip").exists()
    assert not (target / "Games").exists()


def test_per_system_filter_apply(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["roms"], systems_filter=["MAME"])
    apply_migration(plan)

    # MAME moved, SNES untouched.
    assert (target / "Games" / "MAME" / "pacman.zip").exists()
    assert (Path(cfg.roms_dir) / "SNES" / "Chrono Trigger.sfc").exists()
    assert not (Path(cfg.roms_dir) / "MAME").exists()
    # roms_dir config unchanged (split-library mode).
    refreshed = load_config()
    assert refreshed.roms_dir == cfg.roms_dir


def test_find_latest_manifest_returns_newest(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "new"
    plan = plan_migration(cfg, target, ["emulators"])
    manifest = apply_migration(plan)
    latest = find_latest_manifest()
    assert latest == manifest
