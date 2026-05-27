"""Tests for scrub --backup-dir and scrub-restore CLI commands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from spindoctor.cli import cli


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_stat_file(rl: Path, layout: str, system: str = "MAME") -> Path:
    """Write a fake Statistics.ini in the requested layout."""
    if layout == "classic":
        p = rl / "Settings" / "Global Statistics" / f"{system}.ini"
    elif layout == "legacy":
        p = rl / "Settings" / system / "Statistics.ini"
    else:  # newer
        p = rl / "Data" / "Statistics" / f"{system}.ini"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"[{system}]\nTimesPlayed=7\n", encoding="utf-8")
    return p


def _cfg_path(tmp_path: Path) -> Path:
    return tmp_path / ".spindoctor" / "config.json"


def _write_cfg(tmp_path: Path, rl_dir: str, hs_dir: str) -> None:
    p = _cfg_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"rocketlauncher_dir": rl_dir, "hyperspin_dir": hs_dir}),
        encoding="utf-8",
    )


# ─── _collect_stat_files ─────────────────────────────────────────────────────

def test_collect_stat_files_classic(tmp_path):
    from spindoctor.cli import _collect_stat_files
    rl = tmp_path / "rl"
    f = _make_stat_file(rl, "classic", "MAME")
    result = _collect_stat_files(rl)
    assert f in result


def test_collect_stat_files_legacy(tmp_path):
    from spindoctor.cli import _collect_stat_files
    rl = tmp_path / "rl"
    f = _make_stat_file(rl, "legacy", "Zinc")
    result = _collect_stat_files(rl)
    assert f in result


def test_collect_stat_files_newer(tmp_path):
    from spindoctor.cli import _collect_stat_files
    rl = tmp_path / "rl"
    f = _make_stat_file(rl, "newer", "Dreamcast")
    result = _collect_stat_files(rl)
    assert f in result


def test_collect_stat_files_excludes_global_aggregate(tmp_path):
    from spindoctor.cli import _collect_stat_files
    rl = tmp_path / "rl"
    # Create the aggregate file that must be excluded
    agg = rl / "Data" / "Statistics" / "Global Statistics.ini"
    agg.parent.mkdir(parents=True, exist_ok=True)
    agg.write_text("[Global]\nTotal=99\n", encoding="utf-8")
    result = _collect_stat_files(rl)
    assert agg not in result


def test_collect_stat_files_all_three_layouts(tmp_path):
    from spindoctor.cli import _collect_stat_files
    rl = tmp_path / "rl"
    f1 = _make_stat_file(rl, "classic", "MAME")
    f2 = _make_stat_file(rl, "legacy", "Zinc")
    f3 = _make_stat_file(rl, "newer", "Dreamcast")
    result = _collect_stat_files(rl)
    assert f1 in result
    assert f2 in result
    assert f3 in result


# ─── _scrub_backup ────────────────────────────────────────────────────────────

def test_scrub_backup_stats_copies_files(tmp_path, monkeypatch):
    from spindoctor.cli import _scrub_backup
    from spindoctor.config import Config

    rl = tmp_path / "rl"
    stat_file = _make_stat_file(rl, "classic", "MAME")

    config = Config(rocketlauncher_dir=str(rl), hyperspin_dir=str(tmp_path / "hs"))
    # Patch FAVORITES_FILE to a non-existent path so only stats are backed up
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE", tmp_path / "nonexistent.json")

    backup_dir = tmp_path / "backups"
    folder, manifest = _scrub_backup(backup_dir, do_favorites=False, do_stats=True, config=config)

    assert folder.exists()
    assert (folder / "manifest.json").exists()
    assert len(manifest) == 1
    assert manifest[0]["original"] == str(stat_file)
    backed_up = folder / manifest[0]["backup"]
    assert backed_up.exists()
    assert backed_up.read_text() == stat_file.read_text()


def test_scrub_backup_favorites_copies_file(tmp_path, monkeypatch):
    from spindoctor.cli import _scrub_backup
    from spindoctor.config import Config

    fav_file = tmp_path / "favorites.json"
    fav_file.write_text('{"entries": [], "target_system": "Favorites"}', encoding="utf-8")
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE", fav_file)
    monkeypatch.setattr("spindoctor.cli.FAVORITES_FILE", fav_file, raising=False)

    config = Config(rocketlauncher_dir="", hyperspin_dir="")
    backup_dir = tmp_path / "backups"
    folder, manifest = _scrub_backup(backup_dir, do_favorites=True, do_stats=False, config=config)

    assert len(manifest) == 1
    assert (folder / "favorites.json").exists()


def test_scrub_backup_creates_manifest_json(tmp_path, monkeypatch):
    from spindoctor.cli import _scrub_backup
    from spindoctor.config import Config

    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE", tmp_path / "nope.json")
    config = Config(rocketlauncher_dir="", hyperspin_dir="")
    folder, _ = _scrub_backup(tmp_path / "bk", False, False, config)

    manifest_path = folder / "manifest.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert "created" in data
    assert "files" in data


# ─── CLI: scrub --backup-dir (dry-run) ───────────────────────────────────────

def test_scrub_backup_dir_skipped_in_dry_run(tmp_path, monkeypatch):
    """--backup-dir is mentioned as skipped when not combined with --apply."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "spindoctor.config.CONFIG_FILE", tmp_path / ".spindoctor" / "config.json"
    )
    rl = tmp_path / "rl"
    rl.mkdir()
    _write_cfg(tmp_path, str(rl), str(tmp_path / "hs"))
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub", "--stats", "--backup-dir", str(backup_dir)])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "skipped" in result.output.lower() or "dry-run" in result.output.lower()
    # No actual backup folder should be created inside backup_dir
    subdirs = list(backup_dir.iterdir())
    assert subdirs == []


# ─── CLI: scrub-restore ───────────────────────────────────────────────────────

def test_scrub_restore_dry_run_lists_files(tmp_path):
    """Dry-run restore prints files without touching them."""
    # Create a minimal backup folder
    backup = tmp_path / "scrub-20260101-120000"
    backup.mkdir()
    target = tmp_path / "restored_favorites.json"
    (backup / "favorites.json").write_text('{"entries": []}', encoding="utf-8")
    manifest = {
        "created": "20260101-120000",
        "files": [{"original": str(target), "backup": "favorites.json"}],
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub-restore", str(backup)])
    assert result.exit_code == 0
    # Rich may hard-wrap long paths at character boundaries (not word boundaries),
    # e.g. "restored_favorites.json" → "restore\nd_favorites.json".
    # Strip newlines (not join-with-space) so the filename reassembles correctly.
    flat = result.output.replace("\n", "")
    assert "DRY RUN" in flat
    assert target.name in flat          # at minimum the filename appears
    # File was NOT written (dry-run)
    assert not target.exists()


def test_scrub_restore_apply_writes_files(tmp_path):
    """--apply copies files back to original locations."""
    backup = tmp_path / "scrub-20260101-120000"
    backup.mkdir()
    target = tmp_path / "favorites.json"
    (backup / "favorites.json").write_text('{"entries": []}', encoding="utf-8")
    manifest = {
        "created": "20260101-120000",
        "files": [{"original": str(target), "backup": "favorites.json"}],
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub-restore", str(backup), "--apply"])
    assert result.exit_code == 0
    assert target.exists()
    assert target.read_text() == '{"entries": []}'


def test_scrub_restore_missing_manifest_exits(tmp_path):
    """scrub-restore fails clearly when manifest.json is missing."""
    backup = tmp_path / "not-a-backup"
    backup.mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub-restore", str(backup)])
    assert result.exit_code != 0
    assert "manifest.json" in result.output.lower() or "manifest" in result.output


def test_scrub_restore_empty_manifest(tmp_path):
    """scrub-restore handles an empty files list gracefully."""
    backup = tmp_path / "scrub-empty"
    backup.mkdir()
    (backup / "manifest.json").write_text(
        json.dumps({"created": "20260101-000000", "files": []}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub-restore", str(backup), "--apply"])
    assert result.exit_code == 0
    assert "nothing" in result.output.lower() or "0" in result.output
