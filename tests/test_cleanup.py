"""Cache + manifest inventory and removal."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import spindoctor.cleanup as cleanup_mod
import spindoctor.config as config_mod
from spindoctor.cleanup import (
    filter_files, format_size, FileEntry, prune_empty_dirs, remove, scan,
)
from spindoctor.config import Config


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(cleanup_mod, "CONFIG_DIR", home)
    yield home


def _touch(path: Path, content: str = "x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


def test_scan_empty_layout_returns_zero_counts(isolated_home, tmp_path):
    cfg = Config()
    reports = scan(cfg)
    assert all(r.count == 0 for r in reports.values())
    assert "match-cache" in reports
    assert "metadata-cache" in reports
    assert "db-backups" in reports


def test_scan_finds_match_and_metadata_caches(isolated_home, tmp_path):
    _touch(isolated_home / "match_cache" / "MAME.json", json.dumps({"a": "1"}))
    _touch(isolated_home / "metadata_cache" / "ss" / "MAME" / "pacman.json", "{}")

    cfg = Config()
    reports = scan(cfg)
    assert reports["match-cache"].count == 1
    assert reports["metadata-cache"].count == 1
    assert reports["match-cache"].total_bytes > 0


def test_scan_finds_db_backups_and_restructure_manifests(isolated_home, tmp_path):
    roms = tmp_path / "ROMs"
    hyperspin = tmp_path / "HyperSpin"
    _touch(roms / "MAME" / "_spindoctor-restructure-20260101_010101.json", "{}")
    _touch(roms / "MAME" / "_spindoctor-misplaced-20260101_010101.json", "{}")
    _touch(hyperspin / "Databases" / "MAME" / "MAME.xml.20260101_010101.bak", "<x/>")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hyperspin))
    reports = scan(cfg)
    assert reports["restructure-manifests"].count == 1
    assert reports["misplaced-manifests"].count == 1
    assert reports["db-backups"].count == 1


def test_scan_includes_audit_export_dir(isolated_home, tmp_path):
    exports = tmp_path / "audits"
    _touch(exports / "audit_20260101_010101.csv", "system,games\n")
    cfg = Config(auto_audit_export_dir=str(exports))
    reports = scan(cfg)
    assert reports["audit-exports"].count == 1


def test_safe_flag_categories(isolated_home):
    cfg = Config()
    reports = scan(cfg)
    safe = {k: r.safe for k, r in reports.items()}
    # caches and audit exports rebuild themselves; backups/manifests do not.
    assert safe["match-cache"] is True
    assert safe["metadata-cache"] is True
    assert safe["audit-exports"] is True
    assert safe["partial-downloads"] is True
    assert safe["db-backups"] is False
    assert safe["migration-manifests"] is False
    assert safe["restructure-manifests"] is False


def test_scan_finds_partial_download_sidecars(isolated_home, tmp_path):
    hyperspin = tmp_path / "HyperSpin"
    media = hyperspin / "Media"
    _touch(media / "MAME" / "Images" / "Wheel" / "1942.png.part", "abc")
    _touch(media / "SNES" / "Video" / "Super Mario World.mp4.part", "xy")
    _touch(media / "MAME" / "Images" / "Wheel" / "complete.png", "real")

    cfg = Config(hyperspin_dir=str(hyperspin))
    reports = scan(cfg)
    partials = reports["partial-downloads"]
    assert partials.count == 2
    assert partials.total_bytes == 5
    names = {f.path.name for f in partials.files}
    assert names == {"1942.png.part", "Super Mario World.mp4.part"}


def test_partial_downloads_returns_zero_when_hyperspin_unset(isolated_home):
    cfg = Config()
    reports = scan(cfg)
    assert "partial-downloads" in reports
    assert reports["partial-downloads"].count == 0


def test_filter_files_older_than(isolated_home, tmp_path):
    now = 1_700_000_000.0
    old = FileEntry(tmp_path / "old.json", 100, now - 40 * 86400)
    fresh = FileEntry(tmp_path / "fresh.json", 100, now - 1 * 86400)
    selected = filter_files([old, fresh], older_than_days=30, now=now)
    assert selected == [old]


def test_filter_files_keep_recent(isolated_home, tmp_path):
    files = [
        FileEntry(tmp_path / f"f{i}.json", 10, 1_000_000 + i)
        for i in range(5)
    ]
    # Keep 2 newest (f4, f3) → delete the other 3 (f2, f1, f0)
    selected = filter_files(files, keep_recent=2)
    deleted_names = {f.path.name for f in selected}
    assert deleted_names == {"f2.json", "f1.json", "f0.json"}


def test_remove_dry_run_does_not_delete(isolated_home, tmp_path):
    p = _touch(tmp_path / "x.json", "data")
    entry = FileEntry(p, p.stat().st_size, p.stat().st_mtime)
    result = remove([entry], dry_run=True)
    assert result.count_removed == 1
    assert result.bytes_freed == 4
    assert p.exists()


def test_remove_actually_deletes(isolated_home, tmp_path):
    p = _touch(tmp_path / "x.json", "data")
    entry = FileEntry(p, p.stat().st_size, p.stat().st_mtime)
    result = remove([entry], dry_run=False)
    assert result.count_removed == 1
    assert result.bytes_freed == 4
    assert not p.exists()
    assert result.failed == []


def test_remove_handles_missing_file(isolated_home, tmp_path):
    p = tmp_path / "ghost.json"
    entry = FileEntry(p, 100, time.time())
    result = remove([entry], dry_run=False)
    assert result.count_removed == 0
    assert result.failed == []


def test_prune_empty_dirs_collapses_now_empty_tree(isolated_home, tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    n = prune_empty_dirs([tmp_path / "a"])
    assert n >= 3
    assert not (tmp_path / "a").exists()


def test_prune_empty_dirs_leaves_non_empty(isolated_home, tmp_path):
    keep = tmp_path / "a" / "b" / "file.txt"
    _touch(keep, "x")
    prune_empty_dirs([tmp_path / "a"])
    assert keep.exists()


def test_format_size_units():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(2048).startswith("2.0 KB")
    assert format_size(5 * 1024 * 1024).endswith(" MB")


def test_scan_filters_by_keys(isolated_home):
    _touch(isolated_home / "match_cache" / "MAME.json", "{}")
    _touch(isolated_home / "metadata_cache" / "x.json", "{}")
    cfg = Config()
    reports = scan(cfg, keys=["match-cache"])
    assert list(reports.keys()) == ["match-cache"]
