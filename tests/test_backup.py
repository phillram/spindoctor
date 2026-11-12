"""Plan / apply / restore round-trips for the backup command."""
from __future__ import annotations
from tests.helpers import write_bytes as _write_bytes

from click.testing import CliRunner
from spindoctor import backup
from spindoctor.cli import cli
from spindoctor import config
import json
import shutil

from pathlib import Path

import pytest

import spindoctor.backup as backup_mod
from spindoctor.backup import (
    apply_backup, apply_restore, find_latest_backup, list_backups,
    normalize_components, plan_backup, plan_restore, read_manifest,
)
from spindoctor.config import Config, save_config


@pytest.fixture
def isolated_config(config_home, monkeypatch):
    config_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", config_home)
    return config_home


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


def test_backups_started_in_the_same_second_get_separate_roots(
    isolated_config, tmp_path, monkeypatch,
):
    """The folder name only has one-second resolution. A second backup in
    the same second used to reuse the first one's folder and overwrite its
    manifest.json, which hid the first backup's components from restore."""
    from datetime import datetime

    class _FrozenDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 6, 14, 17, 46, 35)

    monkeypatch.setattr(backup_mod, "datetime", _FrozenDateTime)
    cfg = _seed_library(tmp_path)
    target = tmp_path / "backups"

    first = apply_backup(plan_backup(cfg, target, ["roms"]), cfg)
    second = apply_backup(plan_backup(cfg, target, ["databases"]), cfg)

    assert first.name == "spindoctor-backup-20260614_174635"
    assert second.name == "spindoctor-backup-20260614_174635_2"
    assert {i["component"] for i in read_manifest(first)["items"]} == {"roms"}
    assert {i["component"] for i in read_manifest(second)["items"]} == {"databases"}
    assert [b.name for b in list_backups(target)] == [first.name, second.name]


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


def test_restore_uses_selected_backup_not_original_location(isolated_config, tmp_path):
    src = tmp_path / "live"
    _write_bytes(src / "game.zip")
    cfg = config.Config(roms_dir=str(src))
    original = backup.apply_backup(backup.plan_backup(cfg, tmp_path / "backups", ["roms"]), cfg)
    relocated = tmp_path / "relocated"
    shutil.copytree(original, relocated)
    _write_bytes(original / "Games" / "game.zip", b"stale")
    plan = backup.plan_restore(relocated)
    assert Path(plan.items[0].src) == relocated / "Games"
    shutil.rmtree(src)
    backup.apply_restore(plan)
    assert (src / "game.zip").read_bytes() == b"original"


def test_settings_backup_excludes_runtime_lock(isolated_config, tmp_path):
    _write_bytes(backup.CONFIG_DIR / "gui.lock", b"locked")
    _write_bytes(backup.CONFIG_DIR / "config.json", b"{}")
    cfg = config.Config()
    root = backup.apply_backup(backup.plan_backup(cfg, tmp_path / "backups", ["settings"]), cfg)
    assert not (root / "Settings" / "gui.lock").exists()
    assert (root / "Settings" / "config.json").exists()


def test_settings_restore_does_not_delete_live_lock(isolated_config, tmp_path, monkeypatch):
    source = tmp_path / "saved"
    _write_bytes(source / "config.json", b'{"new":true}')
    _write_bytes(source / "gui.lock", b"obsolete lock")
    live_lock = _write_bytes(backup.CONFIG_DIR / "gui.lock", b"active lock")
    _write_bytes(backup.CONFIG_DIR / "config.json", b"{}")
    real_rmtree = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        assert Path(path) != backup.CONFIG_DIR
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", guarded_rmtree)
    plan = backup.RestorePlan(str(tmp_path), [
        backup.RestoreItem("settings", str(source), str(backup.CONFIG_DIR)),
    ])
    assert backup.apply_restore(plan, overwrite=True) == 1
    assert live_lock.read_bytes() == b"active lock"
    assert json.loads((backup.CONFIG_DIR / "config.json").read_text()) == {"new": True}


def test_backup_apply_rejects_hand_built_nested_plan(isolated_config, tmp_path):
    src = tmp_path / "live"
    _write_bytes(src / "game.zip")
    root = src / "backup"
    plan = backup.BackupPlan(str(root), [
        backup.BackupItem("roms", str(src), str(root / "Games")),
    ])
    with pytest.raises(ValueError, match="inside its source"):
        backup.apply_backup(plan, config.Config())
    assert not root.exists()


def test_restore_rechecks_sources_before_removing_destination(isolated_config, tmp_path):
    live = _write_bytes(tmp_path / "live" / "valuable", b"keep")
    plan = backup.RestorePlan(str(tmp_path / "backup"), [
        backup.RestoreItem("roms", str(tmp_path / "missing"), str(live.parent)),
    ])
    with pytest.raises(FileNotFoundError):
        backup.apply_restore(plan, overwrite=True)
    assert live.read_bytes() == b"keep"


def test_old_backup_settings_locks_are_never_restored(isolated_config, tmp_path):
    saved = tmp_path / "backup"
    _write_bytes(saved / "config.json", b"{}")
    _write_bytes(saved / "gui.lock")
    live = tmp_path / "live"
    plan = backup.RestorePlan(str(saved), [
        backup.RestoreItem("settings", str(saved), str(live)),
    ])
    assert backup.apply_restore(plan) == 1
    assert (live / "config.json").exists()
    assert not (live / "gui.lock").exists()


def test_latest_backup_uses_numeric_collision_counter(tmp_path):
    names = ["spindoctor-backup-20261104_120000" + suffix for suffix in ("", "_2", "_9", "_10")]
    for name in names:
        root = tmp_path / name
        root.mkdir()
        (root / "manifest.json").write_text("{}")
    assert [p.name for p in backup.list_backups(tmp_path)] == names
    assert backup.find_latest_backup(tmp_path).name == names[-1]


def test_restore_overlap_reports_a_cli_error(tmp_path, monkeypatch):
    source = tmp_path / "saved"
    source.mkdir()
    plan = backup.RestorePlan(str(source), [
        backup.RestoreItem("roms", str(source), str(source / "nested")),
    ])
    monkeypatch.setattr(backup, "plan_restore", lambda *args, **kwargs: plan)
    monkeypatch.setattr(config, "load_config", lambda: config.Config())
    result = CliRunner().invoke(cli, ["backup", "restore", "--backup", str(source), "--apply"])
    assert result.exit_code == 1
    assert "overlap" in result.output
    assert "Aborted" in result.output
