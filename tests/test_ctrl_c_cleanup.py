"""Ctrl+C mid-operation must not leave half-written state behind.

Each test simulates a KeyboardInterrupt at the worst-possible moment
(during the copy/move of one component) and asserts the cleanup hooks
remove the partial output before re-raising.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import spindoctor.backup as backup_mod
import spindoctor.config as config_mod
import spindoctor.migrate as migrate_mod
from spindoctor.backup import apply_backup, plan_backup
from spindoctor.config import Config, save_config
from spindoctor.curate import CurationGroup, apply_curation
from spindoctor.migrate import (
    MigrateMove,
    MigrationPlan,
    apply_migration,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(migrate_mod, "CONFIG_DIR", home)
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _touch(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ─── backup ──────────────────────────────────────────────────────────────────


def test_backup_keyboard_interrupt_removes_partial_dest(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roms = tmp_path / "live" / "ROMs"
    _touch(roms / "MAME" / "pacman.zip", "rom-bytes")
    cfg = Config()
    cfg.roms_dir = str(roms)
    save_config(cfg)

    backup_target = tmp_path / "backups"
    backup_target.mkdir(parents=True, exist_ok=True)
    plan = plan_backup(cfg, backup_target, ["roms"])

    real_copytree = shutil.copytree

    def boom(src, dest, *a, **kw):
        # Mimic shutil.copytree's mid-flight failure: create the dest
        # then raise KeyboardInterrupt. Without the cleanup hook in
        # backup.apply_backup, this dest would be left dangling.
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "partial.zip").write_bytes(b"half")
        raise KeyboardInterrupt()

    monkeypatch.setattr(shutil, "copytree", boom)
    try:
        with pytest.raises(KeyboardInterrupt):
            apply_backup(plan, cfg)
    finally:
        monkeypatch.setattr(shutil, "copytree", real_copytree)

    # The half-written component dest must be gone.
    leftover = list(Path(plan.backup_root).rglob("partial.zip"))
    assert leftover == [], f"partial backup not cleaned up: {leftover}"


# ─── migrate ─────────────────────────────────────────────────────────────────


def test_migrate_keyboard_interrupt_keep_source_removes_partial_dest(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_root = tmp_path / "old" / "ROMs"
    _touch(src_root / "MAME" / "pacman.zip", "rom-bytes")
    dest_root = tmp_path / "new" / "ROMs"
    cfg = Config()
    cfg.roms_dir = str(src_root)
    save_config(cfg)

    plan = MigrationPlan(
        target_root=str(tmp_path / "new"),
        moves=[
            MigrateMove(
                component="roms",
                src=str(src_root),
                dest=str(dest_root),
                size_bytes=10,
            ),
        ],
    )

    real_copytree = shutil.copytree

    def boom(src, dest, *a, **kw):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "partial.zip").write_bytes(b"half")
        raise KeyboardInterrupt()

    monkeypatch.setattr(shutil, "copytree", boom)
    try:
        with pytest.raises(KeyboardInterrupt):
            apply_migration(plan, keep_source=True, update_config=False)
    finally:
        monkeypatch.setattr(shutil, "copytree", real_copytree)

    assert not dest_root.exists() or not any(dest_root.iterdir()), (
        f"partial migration dest not cleaned up: {list(dest_root.rglob('*'))}"
    )


# ─── curate ──────────────────────────────────────────────────────────────────


def test_curate_keyboard_interrupt_persists_partial_manifest(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already-archived files must end up in a manifest so `curate --undo`
    can roll them back even if the user Ctrl+C'd mid-system."""
    roms = tmp_path / "live" / "ROMs"
    system = "MAME"
    rom_dir = roms / system
    rom_a = rom_dir / "ToRetire-A.zip"
    rom_b = rom_dir / "ToRetire-B.zip"
    rom_keep = rom_dir / "Keep.zip"
    _touch(rom_a, "a")
    _touch(rom_b, "b")
    _touch(rom_keep, "k")

    cfg = Config()
    cfg.roms_dir = str(roms)
    save_config(cfg)

    groups = [
        CurationGroup(
            title="Test",
            keep=rom_keep,
            retire=[rom_a, rom_b],
        ),
    ]

    real_move = shutil.move
    moved: list[str] = []

    def flaky_move(src, dst, *a, **kw):
        # First move succeeds (so the manifest must record it); the
        # second raises KeyboardInterrupt mid-loop.
        if not moved:
            moved.append(str(src))
            return real_move(src, dst, *a, **kw)
        raise KeyboardInterrupt()

    manifest_dir = tmp_path / "manifests"

    monkeypatch.setattr(shutil, "move", flaky_move)
    try:
        with pytest.raises(KeyboardInterrupt):
            apply_curation(
                groups, cfg, system, action="archive",
                manifest_dir=manifest_dir,
            )
    finally:
        monkeypatch.setattr(shutil, "move", real_move)

    # A manifest exists, and it records the one file that DID get archived.
    manifests = list(manifest_dir.glob("*.json"))
    assert len(manifests) == 1, f"expected one partial manifest, got: {manifests}"
    text = manifests[0].read_text(encoding="utf-8")
    assert "ToRetire-A.zip" in text
    assert "ToRetire-B.zip" not in text  # never reached


# ─── partial-manifest persistence (PR follow-up) ─────────────────────────────


def test_backup_keyboard_interrupt_writes_partial_manifest(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completed components must be recorded in a manifest before re-raise,
    otherwise `list_backups` can't see them and `restore` can't replay
    them — the work is invisible and effectively orphaned.
    """
    roms = tmp_path / "live" / "ROMs"
    _touch(roms / "MAME" / "pacman.zip", "a")
    settings_dir = isolated_config  # CONFIG_DIR fixture
    _touch(settings_dir / "config.json", '{"roms_dir": "x"}')

    cfg = Config()
    cfg.roms_dir = str(roms)
    save_config(cfg)

    backup_target = tmp_path / "backups"
    backup_target.mkdir(parents=True, exist_ok=True)
    plan = plan_backup(cfg, backup_target, ["settings", "roms"])

    real_copytree = shutil.copytree
    call_count = {"n": 0}

    def flaky(src, dest, *a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First component succeeds
            return real_copytree(src, dest, *a, **kw)
        # Second triggers the Ctrl+C
        Path(dest).mkdir(parents=True, exist_ok=True)
        raise KeyboardInterrupt()

    monkeypatch.setattr(shutil, "copytree", flaky)
    try:
        with pytest.raises(KeyboardInterrupt):
            apply_backup(plan, cfg)
    finally:
        monkeypatch.setattr(shutil, "copytree", real_copytree)

    manifests = list(Path(plan.backup_root).rglob("manifest.json"))
    assert len(manifests) == 1, f"expected partial manifest, got {manifests}"
    # And list_backups() must surface this folder.
    from spindoctor.backup import list_backups

    assert Path(plan.backup_root) in list_backups(backup_target)


def test_migrate_keyboard_interrupt_writes_partial_manifest(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In move-mode the source is destroyed during the move. Without a
    manifest, the completed moves cannot be undone — `migrate --undo`
    relies on the manifest to know where to put things back.
    """
    # MIGRATIONS_DIR is computed at import time from CONFIG_DIR, so the
    # isolated_config fixture's CONFIG_DIR patch doesn't reach it.
    # Patch the module-level constant directly so the partial manifest
    # lands in tmp_path rather than ~/.spindoctor/migrations/.
    manifests_dir = isolated_config / "migrations"
    monkeypatch.setattr(migrate_mod, "MIGRATIONS_DIR", manifests_dir)
    sysA = tmp_path / "old" / "ROMs" / "MAME"
    sysB = tmp_path / "old" / "ROMs" / "SNES"
    destA = tmp_path / "new" / "ROMs" / "MAME"
    destB = tmp_path / "new" / "ROMs" / "SNES"
    _touch(sysA / "pacman.zip", "a")
    _touch(sysB / "chrono.sfc", "b")

    cfg = Config()
    cfg.roms_dir = str(tmp_path / "old" / "ROMs")
    save_config(cfg)

    plan = MigrationPlan(
        target_root=str(tmp_path / "new"),
        moves=[
            MigrateMove(
                component="MAME", src=str(sysA), dest=str(destA),
                size_bytes=10,
            ),
            MigrateMove(
                component="SNES", src=str(sysB), dest=str(destB),
                size_bytes=10,
            ),
        ],
    )

    real_move = shutil.move
    moved = {"n": 0}

    def flaky(src, dst, *a, **kw):
        moved["n"] += 1
        if moved["n"] == 1:
            return real_move(src, dst, *a, **kw)
        raise KeyboardInterrupt()

    monkeypatch.setattr(shutil, "move", flaky)
    try:
        with pytest.raises(KeyboardInterrupt):
            apply_migration(plan, keep_source=False, update_config=False)
    finally:
        monkeypatch.setattr(shutil, "move", real_move)

    # Manifest must record the one move that DID complete so undo works.
    manifests = list(manifests_dir.glob("*.json"))
    assert manifests, "expected a partial manifest after KeyboardInterrupt"
    text = manifests[0].read_text(encoding="utf-8")
    assert "MAME" in text  # the move that completed
