"""Write-ahead recovery survives failure inside the filesystem operation."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from spindoctor import _undo, config, curate, database, edit, media_scan, migrate, misplaced, organize
from spindoctor import favorites, recent, medialink


def write(path, content=b"original"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(config, "CONFIG_DIR", home)
    monkeypatch.setattr(config, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path / "manifests")
    cfg = config.Config(roms_dir=str(tmp_path / "roms"), hyperspin_dir=str(tmp_path / "hs"))
    config.save_config(cfg)
    write(Path(cfg.roms_dir) / "NES" / "old.nes")
    write(cfg.databases_dir / "NES" / "NES.xml",
          b'<menu><game name="old"><description>Old</description><custom key="v"/></game></menu>')
    return cfg


@pytest.mark.parametrize("operation", ["rename", "curate", "misplaced", "restructure", "migration"])
@pytest.mark.parametrize("after_move", [False, True])
def test_move_intent_survives_interruption_inside_move(cabinet, tmp_path, monkeypatch, operation, after_move):
    cfg = cabinet
    src = Path(cfg.roms_dir) / "NES" / "old.nes"
    manifests = tmp_path / "manifests"
    real_move = shutil.move

    def interrupted(source, dest, *args, **kwargs):
        records = list(tmp_path.rglob("*.json"))
        records = [p for p in records if p.name != "config.json"]
        assert len(records) == 1
        record = json.loads(records[0].read_text(encoding="utf-8"))
        assert str(dest) in record["pending"]
        if after_move:
            real_move(source, dest, *args, **kwargs)
        raise SystemExit("simulated interruption")

    if operation == "rename":
        plan = edit.plan_rename(cfg, "NES", "old", "new")
        apply = lambda: edit.apply_rename(plan, cfg, manifest_dir=manifests)
        undo = lambda p: edit.undo_rename(p, cfg)
    elif operation == "curate":
        groups = [curate.CurationGroup("Game", src.with_name("keep.nes"), [src])]
        apply = lambda: curate.apply_curation(groups, cfg, "NES", manifest_dir=manifests)
        undo = curate.undo_curation
    elif operation == "misplaced":
        items = [misplaced.MisplacedRom(src, "NES", ".nes", ["Other"])]
        apply = lambda: misplaced.apply_moves(items, cfg, manifest_dir=manifests)
        undo = misplaced.undo_moves
    elif operation == "restructure":
        plan = organize.RestructurePlan("NES", "per-game-folder", str(src.parent),
                                       [organize.FileMove(str(src), str(src.parent / "old" / src.name))])
        apply = lambda: organize.apply_restructure(plan)
        undo = organize.undo_restructure
    else:
        plan = migrate.MigrationPlan(str(tmp_path / "new"), [
            migrate.MigrateMove("roms", str(src), str(tmp_path / "new" / src.name)),
        ])
        apply = lambda: migrate.apply_migration(plan, update_config=False)
        undo = migrate.undo_migration

    monkeypatch.setattr(shutil, "move", interrupted)
    with pytest.raises(SystemExit, match="simulated interruption"):
        apply()
    monkeypatch.setattr(shutil, "move", real_move)
    records = [p for p in tmp_path.rglob("*.json") if p.name != "config.json"]
    assert len(records) == 1
    result = undo(records[0])
    if operation == "rename":
        assert not any("failed" in change.note for change in result)
    else:
        assert result["errors"] == []
    assert src.read_bytes() == b"original"
    assert not records[0].exists()


def test_partial_cross_drive_move_is_recorded_but_not_guessed(tmp_path):
    src = write(tmp_path / "source")
    dest = write(tmp_path / "dest", b"partial")
    path = tmp_path / "manifest.json"
    data = {"moves": []}
    _undo.begin_step(path, data, "moves", {"src": str(src), "dest": str(dest)})
    result = misplaced.undo_moves(path)
    assert "investigation" in result["errors"][0]
    assert path.exists()
    assert src.read_bytes() == b"original"
    assert dest.read_bytes() == b"partial"


@pytest.mark.parametrize("checkpoint_number", [1, 2])
def test_failed_checkpoint_prevents_next_rename_mutation(cabinet, tmp_path, monkeypatch, checkpoint_number):
    cfg = cabinet
    plan = edit.plan_rename(cfg, "NES", "old", "new")
    real_write = _undo.atomic_write_bytes
    calls = 0

    def fail(path, data):
        nonlocal calls
        calls += 1
        if calls == checkpoint_number:
            raise OSError("journal disk full")
        real_write(path, data)

    monkeypatch.setattr(_undo, "atomic_write_bytes", fail)
    with pytest.raises(OSError, match="journal disk full"):
        edit.apply_rename(plan, cfg, manifest_dir=tmp_path / "manifests")
    assert (Path(cfg.roms_dir) / "NES" / "old.nes").read_bytes() == b"original"
    assert not (Path(cfg.roms_dir) / "NES" / "new.nes").exists()


def test_rename_database_failure_undo_restores_files(cabinet, tmp_path, monkeypatch):
    cfg = cabinet
    plan = edit.plan_rename(cfg, "NES", "old", "new")
    real_save = database.HyperspinDatabase.save

    def fail(*args, **kwargs):
        raise OSError("database locked")

    monkeypatch.setattr(database.HyperspinDatabase, "save", fail)
    manifests = tmp_path / "manifests"
    with pytest.raises(OSError, match="database locked"):
        edit.apply_rename(plan, cfg, manifest_dir=manifests)
    monkeypatch.setattr(database.HyperspinDatabase, "save", real_save)
    path, = manifests.glob("*.json")
    assert not any("failed" in change.note for change in edit.undo_rename(path, cfg))
    assert (Path(cfg.roms_dir) / "NES" / "old.nes").exists()
    assert database.load_database("NES", cfg.databases_dir).get("old") is not None


def test_failed_completion_checkpoint_leaves_recoverable_intent(cabinet, tmp_path, monkeypatch):
    cfg = cabinet
    plan = edit.plan_rename(cfg, "NES", "old", "new")
    real_write = _undo.atomic_write_bytes
    calls = 0

    def fail(path, data):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("checkpoint failed after move")
        real_write(path, data)

    manifests = tmp_path / "manifests"
    monkeypatch.setattr(_undo, "atomic_write_bytes", fail)
    with pytest.raises(OSError, match="checkpoint failed after move"):
        edit.apply_rename(plan, cfg, manifest_dir=manifests)
    monkeypatch.setattr(_undo, "atomic_write_bytes", real_write)
    path, = manifests.glob("*.json")
    assert json.loads(path.read_text())["pending"]
    assert not any("failed" in change.note for change in edit.undo_rename(path, cfg))
    assert (Path(cfg.roms_dir) / "NES" / "old.nes").read_bytes() == b"original"


@pytest.mark.parametrize("clone", [False, True])
def test_rename_clone_and_undo_preserve_custom_xml_children(cabinet, tmp_path, clone):
    cfg = cabinet
    plan = edit.plan_rename(cfg, "NES", "old", "new", clone=clone)
    _, path = edit.apply_rename(plan, cfg, manifest_dir=tmp_path / "manifests")
    db = database.load_database("NES", cfg.databases_dir)
    assert '<custom key="v"' in db.get("new").xml_template
    assert not any("failed" in change.note for change in edit.undo_rename(path, cfg))
    db = database.load_database("NES", cfg.databases_dir)
    assert db.get("new") is None
    assert '<custom key="v"' in db.get("old").xml_template


def test_process_exit_during_import_has_usable_recovery(tmp_path):
    src = write(tmp_path / "source.png")
    dest = tmp_path / "media" / "game.png"
    manifests = tmp_path / "manifests"
    program = """
import os
from pathlib import Path
from spindoctor import config, media_scan
src, dest, manifests = map(Path, __import__('sys').argv[1:])
original = media_scan._do_action
def crash(*args):
    original(*args)
    os._exit(23)
media_scan._do_action = crash
report = media_scan.MediaScanReport(src.parent, matched=[
    media_scan.ScanMatch(media_scan.LocalMediaFile(src, 'wheel'), 'NES', 'game', target_path=dest)
])
media_scan.import_media(report, config.Config(), action='move', manifest_dir=manifests)
"""
    result = subprocess.run([sys.executable, "-c", program, str(src), str(dest), str(manifests)],
                            cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, timeout=30)
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    path, = manifests.glob("*.json")
    assert media_scan.undo_import(path)["errors"] == []
    assert src.read_bytes() == b"original"
    assert not dest.exists()


@pytest.mark.parametrize("action", ["copy", "move"])
def test_import_overwrite_undo_preserves_previous_target(tmp_path, action):
    src = write(tmp_path / "source.png", b"new media")
    dest = write(tmp_path / "game.png", b"previous media")
    report = media_scan.MediaScanReport(src.parent, matched=[
        media_scan.ScanMatch(media_scan.LocalMediaFile(src, "wheel"), "NES", "game", target_path=dest)
    ])
    result = media_scan.import_media(report, config.Config(), action=action, overwrite=True,
                                     manifest_dir=tmp_path / "manifests")
    assert dest.read_bytes() == b"new media"
    assert media_scan.undo_import(result.manifest_path)["errors"] == []
    assert dest.read_bytes() == b"previous media"
    assert src.read_bytes() == b"new media"


@pytest.mark.parametrize("overwrite", [False, True])
def test_failed_import_copy_retains_recovery_for_partial_destination(tmp_path, monkeypatch, overwrite):
    src = write(tmp_path / "source.png", b"new media")
    dest = tmp_path / "media" / "game.png"
    if overwrite:
        write(dest, b"previous media")
    report = media_scan.MediaScanReport(src.parent, matched=[
        media_scan.ScanMatch(media_scan.LocalMediaFile(src, "wheel"), "NES", "game", target_path=dest)
    ])

    def partial(source, target, action):
        write(target, b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(media_scan, "_do_action", partial)
    result = media_scan.import_media(report, config.Config(), overwrite=overwrite,
                                     manifest_dir=tmp_path / "manifests")
    assert result.skipped
    assert result.manifest_path.exists()
    assert media_scan.undo_import(result.manifest_path)["errors"] == []
    assert src.read_bytes() == b"new media"
    if overwrite:
        assert dest.read_bytes() == b"previous media"
    else:
        assert not dest.exists()


def test_import_undo_missing_backup_does_not_remove_imported_file(tmp_path):
    src = write(tmp_path / "source.png", b"new media")
    dest = write(tmp_path / "game.png", b"previous media")
    report = media_scan.MediaScanReport(src.parent, matched=[
        media_scan.ScanMatch(media_scan.LocalMediaFile(src, "wheel"), "NES", "game", target_path=dest)
    ])
    result = media_scan.import_media(report, config.Config(), overwrite=True,
                                     manifest_dir=tmp_path / "manifests")
    record = json.loads(result.manifest_path.read_text())
    Path(record["imports"][0]["backup"]).unlink()
    assert media_scan.undo_import(result.manifest_path)["errors"]
    assert dest.read_bytes() == b"new media"
    assert result.manifest_path.exists()


def test_import_move_undo_retries_only_failed_backup_restore(tmp_path, monkeypatch):
    src = write(tmp_path / "source.png", b"new media")
    dest = write(tmp_path / "game.png", b"previous media")
    report = media_scan.MediaScanReport(src.parent, matched=[
        media_scan.ScanMatch(media_scan.LocalMediaFile(src, "wheel"), "NES", "game", target_path=dest)
    ])
    result = media_scan.import_media(report, config.Config(), action="move", overwrite=True,
                                     manifest_dir=tmp_path / "manifests")
    real_copy = shutil.copy2

    def failed_restore(*args, **kwargs):
        raise OSError("backup restore blocked")

    monkeypatch.setattr(shutil, "copy2", failed_restore)
    assert media_scan.undo_import(result.manifest_path)["errors"]
    assert src.read_bytes() == b"new media"
    assert json.loads(result.manifest_path.read_text())["imports"][0]["action"] == "restore-backup"
    monkeypatch.setattr(shutil, "copy2", real_copy)
    assert media_scan.undo_import(result.manifest_path)["errors"] == []
    assert src.read_bytes() == b"new media"
    assert dest.read_bytes() == b"previous media"


def test_batch_edit_records_snapshot_before_database_save(cabinet, tmp_path, monkeypatch):
    cfg = cabinet
    games = list(database.load_database("NES", cfg.databases_dir).games().values())
    manifests = tmp_path / "manifests"

    def fail(*args, **kwargs):
        path, = manifests.glob("*.json")
        assert json.loads(path.read_text())["games"][0]["before"]["description"] == "Old"
        raise OSError("database locked")

    monkeypatch.setattr(database.HyperspinDatabase, "save", fail)
    with pytest.raises(OSError, match="database locked"):
        edit.apply_batch_edit(cfg, "NES", games, [edit.EditChange("description", "New")],
                              manifest_dir=manifests)


@pytest.mark.parametrize("builder", ["favorites", "recent"])
def test_custom_wheel_rebuild_refreshes_source_media_and_preserves_xml(cabinet, tmp_path, builder):
    cfg = cabinet
    src = write(cfg.media_dir / "NES" / "Images" / "Wheel" / "old.png", b"first art")
    entry = favorites.FavoriteEntry("NES", "old", "Old", "")
    if builder == "favorites":
        store = favorites.FavoriteStore([entry], target_system="Custom Wheel")
        rebuild = lambda: favorites.rebuild(store, cfg, media_mode=medialink.LinkMode.COPY,
                                             skip_launchers=True)
    else:
        rebuild = lambda: recent._build_synthetic_wheel(cfg, "Custom Wheel", [entry],
                                                        media_mode=medialink.LinkMode.COPY,
                                                        skip_launchers=True)
    assert not rebuild().media_errors
    replacement = src.with_suffix(".new")
    replacement.write_bytes(b"updated art")
    replacement.replace(src)
    assert not rebuild().media_errors
    dest = cfg.media_dir / "Custom Wheel" / "Images" / "Wheel" / "old.png"
    assert dest.read_bytes() == b"updated art"
    game = database.load_database("Custom Wheel", cfg.databases_dir).get("old")
    assert '<custom key="v"' in game.xml_template
