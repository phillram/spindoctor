"""Tests for scrub --backup-dir, scrub-restore, and --hs-favorites CLI commands."""
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


def test_collect_stat_files_includes_global_aggregate(tmp_path):
    from spindoctor.cli import _collect_stat_files
    rl = tmp_path / "rl"
    # Global Statistics.ini must be included so scrub clears it — otherwise
    # the refresh fallback reads stale data from it after per-system files
    # are deleted, repopulating Most Played / Recently Played with old games.
    agg = rl / "Data" / "Statistics" / "Global Statistics.ini"
    agg.parent.mkdir(parents=True, exist_ok=True)
    agg.write_text("[Global]\nTotal=99\n", encoding="utf-8")
    result = _collect_stat_files(rl)
    assert agg in result


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

def test_scrub_backup_dir_works_in_dry_run(tmp_path, monkeypatch):
    """--backup-dir creates a snapshot even without --apply (dry-run mode).

    The backup is created so users can capture state before deciding to apply.
    No data is deleted in dry-run mode.
    """
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
    # A snapshot folder should now be created even in dry-run
    subdirs = list(backup_dir.iterdir())
    assert len(subdirs) == 1, f"Expected snapshot folder, got: {subdirs}"
    assert subdirs[0].name.startswith("scrub-")
    # Output should mention snapshot / dry-run
    assert "snapshot" in result.output.lower() or "dry-run" in result.output.lower()


# ─── CLI: scrub --stats with actual files (regression: is_relative_to Python 3.8) ──

def test_scrub_stats_dry_run_lists_files(tmp_path, monkeypatch):
    """Dry-run scrub --stats must list found files without crashing.

    Regression test for Python 3.8 incompatibility: Path.is_relative_to() was
    added in 3.9.  The file-listing loop in scrub_cmd previously called
    f.is_relative_to(rl) and crashed with AttributeError on the cabinet's
    Python 3.8 build.  This test exercises that exact code path by ensuring at
    least one Statistics.ini exists, so the loop is entered.  It must pass on
    Python 3.8 (ubuntu-latest × 3.8 in CI).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "spindoctor.config.CONFIG_FILE", tmp_path / ".spindoctor" / "config.json"
    )
    rl = tmp_path / "rl"
    stat_file = _make_stat_file(rl, "classic", "MAME")
    _write_cfg(tmp_path, str(rl), str(tmp_path / "hs"))

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub", "--stats"])
    assert result.exit_code == 0, result.output
    # The filename must appear somewhere in the output (Rich may wrap it)
    flat = result.output.replace("\n", "")
    assert stat_file.name in flat
    # File was NOT deleted (dry-run)
    assert stat_file.exists()


def test_scrub_stats_apply_deletes_files(tmp_path, monkeypatch):
    """scrub --stats --apply deletes Statistics.ini files and reports them.

    Also a regression guard for the is_relative_to Python 3.8 crash: apply
    mode goes through the same listing loop before unlinking, so this ensures
    both the display path and the delete path work under Python 3.8.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "spindoctor.config.CONFIG_FILE", tmp_path / ".spindoctor" / "config.json"
    )
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE", tmp_path / "nope.json")
    rl = tmp_path / "rl"
    stat_file = _make_stat_file(rl, "classic", "MAME")
    _write_cfg(tmp_path, str(rl), str(tmp_path / "hs"))

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub", "--stats", "--apply"])
    assert result.exit_code == 0, result.output
    flat = result.output.replace("\n", "")
    assert stat_file.name in flat
    # File must be gone after --apply
    assert not stat_file.exists()


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


# ─── collect_native_fav_files ─────────────────────────────────────────────────

def _build_hs_layout(tmp_path: Path):
    """Create a minimal HyperSpin + RocketLauncher layout with per-system fav files."""
    hs = tmp_path / "hs"
    rl = tmp_path / "rl"
    roms = tmp_path / "roms"
    for d in (hs, rl, roms):
        d.mkdir()
    # Config
    cfg_file = tmp_path / ".spindoctor" / "config.json"
    cfg_file.parent.mkdir()
    cfg_file.write_text(
        json.dumps({
            "hyperspin_dir": str(hs),
            "rocketlauncher_dir": str(rl),
            "roms_dir": str(roms),
        }),
        encoding="utf-8",
    )
    # Main Menu.xml so get_systems can enumerate systems
    mm = hs / "Databases" / "Main Menu"
    mm.mkdir(parents=True)
    (mm / "Main Menu.xml").write_text(
        '<menu><game name="Super Nintendo"/><game name="MAME"/></menu>',
        encoding="utf-8",
    )
    return hs, rl, cfg_file


def _write_fav_files(hs: Path, sys_name: str, ini=False, txt=False, xml_fav=False):
    sys_dir = hs / "Databases" / sys_name
    sys_dir.mkdir(parents=True, exist_ok=True)
    # Base XML is always needed
    fav_attr = ' favorite="1"' if xml_fav else ''
    (sys_dir / f"{sys_name}.xml").write_text(
        f'<menu><game name="Kirby"{fav_attr}><description>Kirby</description></game></menu>',
        encoding="utf-8",
    )
    if ini:
        (sys_dir / f"{sys_name}_Favorites.ini").write_text("Kirby\n", encoding="utf-8")
    if txt:
        (sys_dir / "favorites.txt").write_text("Kirby\n", encoding="utf-8")


def test_collect_native_fav_files_finds_ini(tmp_path, monkeypatch):
    from spindoctor.favorites import collect_native_fav_files
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", ini=True)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    ini_files, txt_files, xml_files = collect_native_fav_files(cfg)
    assert any("Super Nintendo_Favorites.ini" in str(f) for f in ini_files)
    assert txt_files == []
    assert xml_files == []


def test_collect_native_fav_files_finds_txt(tmp_path, monkeypatch):
    from spindoctor.favorites import collect_native_fav_files
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", txt=True)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    ini_files, txt_files, xml_files = collect_native_fav_files(cfg)
    assert ini_files == []
    assert any("favorites.txt" in str(f) for f in txt_files)
    assert xml_files == []


def test_collect_native_fav_files_finds_xml_with_favorite_attr(tmp_path, monkeypatch):
    from spindoctor.favorites import collect_native_fav_files
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", xml_fav=True)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    ini_files, txt_files, xml_files = collect_native_fav_files(cfg)
    assert ini_files == []
    assert txt_files == []
    assert any("Super Nintendo.xml" in str(f) for f in xml_files)


def test_collect_native_fav_files_skips_xml_without_favorite(tmp_path, monkeypatch):
    from spindoctor.favorites import collect_native_fav_files
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", xml_fav=False)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    ini_files, txt_files, xml_files = collect_native_fav_files(cfg)
    assert xml_files == []


# ─── clear_native_favorites ───────────────────────────────────────────────────

def test_clear_native_favorites_dry_run_does_not_delete(tmp_path, monkeypatch):
    from spindoctor.favorites import clear_native_favorites
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", ini=True, txt=True, xml_fav=True)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    summary = clear_native_favorites(cfg, dry_run=True)
    # Counts what would be removed
    assert summary.ini_cleared == 1
    assert summary.txt_cleared == 1
    assert summary.xml_cleared == 1
    assert summary.xml_games_cleared == 1
    # Files untouched
    assert (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").exists()
    assert (hs / "Databases" / "Super Nintendo" / "favorites.txt").exists()
    xml_content = (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").read_text()
    assert 'favorite="1"' in xml_content


def test_clear_native_favorites_apply_deletes_flat_files(tmp_path, monkeypatch):
    from spindoctor.favorites import clear_native_favorites
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", ini=True, txt=True)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    summary = clear_native_favorites(cfg, dry_run=False)
    assert summary.ini_cleared == 1
    assert summary.txt_cleared == 1
    assert not (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").exists()
    assert not (hs / "Databases" / "Super Nintendo" / "favorites.txt").exists()


def test_clear_native_favorites_apply_strips_xml_attribute(tmp_path, monkeypatch):
    from spindoctor.favorites import clear_native_favorites
    from spindoctor.config import Config
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", xml_fav=True)
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    summary = clear_native_favorites(cfg, dry_run=False)
    assert summary.xml_cleared == 1
    assert summary.xml_games_cleared == 1
    xml_content = (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").read_text()
    assert 'favorite="1"' not in xml_content
    # Other content preserved
    assert "Kirby" in xml_content


# ─── CLI: scrub --hs-favorites ────────────────────────────────────────────────

def test_scrub_hs_favorites_dry_run(tmp_path, monkeypatch):
    """--hs-favorites dry-run prints files without touching them."""
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", ini=True, xml_fav=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub", "--hs-favorites"])
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    # Files not deleted
    assert (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").exists()
    xml_content = (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").read_text()
    assert 'favorite="1"' in xml_content


def test_scrub_hs_favorites_apply(tmp_path, monkeypatch):
    """--hs-favorites --apply removes ini and strips XML."""
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", ini=True, xml_fav=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE", tmp_path / "fav.json")

    runner = CliRunner()
    result = runner.invoke(cli, ["scrub", "--hs-favorites", "--apply"])
    assert result.exit_code == 0, result.output
    assert not (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").exists()
    xml_content = (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").read_text()
    assert 'favorite="1"' not in xml_content


def test_scrub_hs_favorites_backup_includes_files(tmp_path, monkeypatch):
    """--hs-favorites --backup-dir copies ini + XML before deleting."""
    hs, rl, cfg_file = _build_hs_layout(tmp_path)
    _write_fav_files(hs, "Super Nintendo", ini=True, xml_fav=True)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE", tmp_path / "fav.json")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["scrub", "--hs-favorites", "--backup-dir", str(backup_dir), "--apply"]
    )
    assert result.exit_code == 0, result.output
    # A scrub-<timestamp> folder was created
    scrub_dirs = list(backup_dir.iterdir())
    assert len(scrub_dirs) == 1
    scrub_folder = scrub_dirs[0]
    manifest = json.loads((scrub_folder / "manifest.json").read_text())
    backed_names = [Path(e["backup"]).name for e in manifest["files"]]
    assert "Super Nintendo_Favorites.ini" in backed_names
    assert "Super Nintendo.xml" in backed_names
