"""Plan / apply / restore round-trips for the backup command."""
from __future__ import annotations

from pathlib import Path

import pytest

import spindoctor.backup as backup_mod
import spindoctor.config as config_mod
from spindoctor.backup import (
    apply_backup, apply_restore, find_latest_backup, list_backups,
    normalize_components, plan_backup, plan_restore, read_manifest,
)
from spindoctor.config import Config, save_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", home)
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _touch(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _seed_library(tmp_path: Path) -> Config:
    roms = tmp_path / "live" / "ROMs"
    hyperspin = tmp_path / "live" / "HyperSpin"
    emulators = tmp_path / "live" / "Emulators"
    _touch(roms / "MAME" / "pacman.zip", "rom-bytes")
    _touch(roms / "SNES" / "Chrono Trigger.sfc", "rom-bytes-2")
    _touch(hyperspin / "Databases" / "MAME" / "MAME.xml", "<menu/>")
    _touch(hyperspin / "Media" / "MAME" / "Images" / "Wheel" / "pacman.png", "png")
    _touch(emulators / "MAME" / "mame.exe", "exe")
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hyperspin)
    cfg.emulators_dir = str(emulators)
    save_config(cfg)
    return cfg


# ─── normalize_components ─────────────────────────────────────────────────────


def test_normalize_simple_aliases():
    assert normalize_components(["games"]) == ["roms"]
    assert normalize_components(["config"]) == ["settings"]


def test_normalize_composite_aliases():
    # `hyperspin` expands to its two components, in order
    assert normalize_components(["hyperspin"]) == ["databases", "media"]


def test_normalize_all():
    result = normalize_components(["all"])
    assert "roms" in result
    assert "databases" in result
    assert "media" in result
    assert "settings" in result
    assert len(result) == len(set(result))  # no dupes


def test_normalize_dedupes_overlap():
    # `media` and `hyperspin` both reference media — the canonical name
    # should appear exactly once.
    result = normalize_components(["media", "hyperspin"])
    assert result.count("media") == 1
    assert result.count("databases") == 1


def test_normalize_unknown():
    with pytest.raises(ValueError):
        normalize_components(["bogus"])


# ─── plan_backup ──────────────────────────────────────────────────────────────


def test_plan_skips_unconfigured(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "backups"
    plan = plan_backup(cfg, target, ["roms", "ledblinky", "rocketlauncher"])
    chosen = {i.component for i in plan.items}
    assert chosen == {"roms"}
    # Two skipped: ledblinky + rocketlauncher (both unset)
    assert len(plan.skipped) == 2
    assert all("not configured" in s for s in plan.skipped)


def test_plan_includes_settings(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    plan = plan_backup(cfg, tmp_path / "backups", ["settings"])
    assert len(plan.items) == 1
    assert plan.items[0].component == "settings"
    # Source is the isolated config dir, which exists
    assert Path(plan.items[0].src).exists()


def test_plan_total_bytes(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    plan = plan_backup(cfg, tmp_path / "backups", ["roms"])
    assert plan.total_bytes > 0


def test_plan_databases_and_media_split(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    plan = plan_backup(cfg, tmp_path / "backups", ["databases", "media"])
    by_name = {i.component: i for i in plan.items}
    assert "databases" in by_name and "media" in by_name
    # destinations live under HyperSpin/{Databases,Media}
    assert Path(by_name["databases"].dest).name == "Databases"
    assert Path(by_name["media"].dest).name == "Media"


# ─── apply_backup ─────────────────────────────────────────────────────────────


def test_apply_writes_files_and_manifest(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "backups"
    plan = plan_backup(cfg, target, ["roms", "databases", "settings"])
    backup_root = apply_backup(plan, cfg)

    assert backup_root.exists()
    assert (backup_root / "manifest.json").exists()
    assert (backup_root / "Games" / "MAME" / "pacman.zip").read_text() == "rom-bytes"
    assert (backup_root / "HyperSpin" / "Databases" / "MAME" / "MAME.xml").exists()
    assert (backup_root / "Settings" / "config.json").exists()

    manifest = read_manifest(backup_root)
    assert manifest["version"] >= 1
    assert {i["component"] for i in manifest["items"]} == {
        "roms", "databases", "settings",
    }
    # config snapshot is recorded
    assert manifest["config_snapshot"]["roms_dir"] == cfg.roms_dir


def test_apply_refuses_existing_destination(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "backups"
    plan = plan_backup(cfg, target, ["roms"])
    # Pre-create the destination subfolder
    Path(plan.items[0].dest).mkdir(parents=True)
    with pytest.raises(FileExistsError):
        apply_backup(plan, cfg)


# ─── list_backups / find_latest_backup ────────────────────────────────────────


def test_list_backups_returns_only_manifest_dirs(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "backups"

    # Two real backups, with deterministic names so we can assert order.
    p1 = target / "spindoctor-backup-20260101_000000"
    p2 = target / "spindoctor-backup-20260202_000000"
    plan1 = plan_backup(cfg, target, ["roms"], backup_root=p1)
    apply_backup(plan1, cfg)
    plan2 = plan_backup(cfg, target, ["roms"], backup_root=p2)
    # plan2 will fail because the source ROM dir hasn't changed and the
    # subfolder name is "Games" — both backups want to write Games/.
    # That's fine: each backup gets its own root, so destinations don't clash.
    apply_backup(plan2, cfg)

    # And one decoy — a non-backup directory and a malformed backup.
    (target / "random-folder").mkdir()
    bad = target / "spindoctor-backup-99999999_999999"
    bad.mkdir()  # no manifest.json

    found = list_backups(target)
    assert [b.name for b in found] == [p1.name, p2.name]
    assert find_latest_backup(target).name == p2.name


def test_list_backups_empty_target(tmp_path):
    assert list_backups(tmp_path / "does_not_exist") == []


# ─── plan_restore / apply_restore ─────────────────────────────────────────────


def test_restore_round_trip(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    target = tmp_path / "backups"
    plan = plan_backup(cfg, target, ["roms", "databases"])
    backup_root = apply_backup(plan, cfg)

    # Wipe the live library
    import shutil
    shutil.rmtree(cfg.roms_dir)
    shutil.rmtree(Path(cfg.hyperspin_dir) / "Databases")

    rplan = plan_restore(backup_root)
    assert {i.component for i in rplan.items} == {"roms", "databases"}
    apply_restore(rplan)

    assert (Path(cfg.roms_dir) / "MAME" / "pacman.zip").read_text() == "rom-bytes"
    assert (Path(cfg.hyperspin_dir) / "Databases" / "MAME" / "MAME.xml").exists()


def test_restore_filtered_to_settings_only(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    backup_root = apply_backup(
        plan_backup(cfg, tmp_path / "backups", ["roms", "settings"]), cfg,
    )
    rplan = plan_restore(backup_root, components=["settings"])
    assert {i.component for i in rplan.items} == {"settings"}


def test_restore_refuses_unknown_filter(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    backup_root = apply_backup(
        plan_backup(cfg, tmp_path / "backups", ["roms"]), cfg,
    )
    plan = plan_restore(backup_root, components=["bogus"])
    assert plan.empty
    assert any("Unknown component" in s for s in plan.skipped)


def test_restore_refuses_missing_filter(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    backup_root = apply_backup(
        plan_backup(cfg, tmp_path / "backups", ["roms"]), cfg,
    )
    plan = plan_restore(backup_root, components=["emulators"])
    assert plan.empty
    assert any("not present" in s for s in plan.skipped)


def test_restore_refuses_clobber_unless_overwrite(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    backup_root = apply_backup(
        plan_backup(cfg, tmp_path / "backups", ["roms"]), cfg,
    )
    # Live ROMs still exist — restore should refuse.
    rplan = plan_restore(backup_root)
    with pytest.raises(FileExistsError):
        apply_restore(rplan)

    # With overwrite, it succeeds and the file is restored.
    apply_restore(rplan, overwrite=True)
    assert (Path(cfg.roms_dir) / "MAME" / "pacman.zip").exists()


def test_restore_use_current_paths(isolated_config, tmp_path):
    cfg = _seed_library(tmp_path)
    backup_root = apply_backup(
        plan_backup(cfg, tmp_path / "backups", ["roms"]), cfg,
    )

    # Pretend the user re-pointed roms_dir at a new location
    new_roms = tmp_path / "relocated" / "Games"
    cfg.roms_dir = str(new_roms)
    save_config(cfg)

    plan = plan_restore(backup_root, use_current_config=cfg)
    assert plan.items[0].dest == str(new_roms)
    apply_restore(plan)
    assert (new_roms / "MAME" / "pacman.zip").exists()


def test_read_manifest_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_manifest(tmp_path)


def test_read_manifest_malformed(tmp_path):
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        read_manifest(tmp_path)
