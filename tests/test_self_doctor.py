"""Tests for spindoctor.self_doctor — diagnostics of SpinDoctor's own state.

Uses a fresh tmp_path as the synthetic ~/.spindoctor/ for each test so
the developer's real config dir is never touched. Mirrors the existing
test_health.py monkeypatch pattern.
"""
from __future__ import annotations

import json
import os
import time

import pytest

import spindoctor.config as config_mod
import spindoctor.self_doctor as sd
from spindoctor.config import Config


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    """Re-home CONFIG_DIR / CONFIG_FILE into a per-test tmp dir, and
    monkeypatch the self_doctor module's CONFIG_DIR ref too. We have to
    patch BOTH because self_doctor caches the import at module-import
    time — patching only config_mod is not enough."""
    home = tmp_path / ".spindoctor"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(sd, "CONFIG_DIR", home)
    yield home


# ─── config_dir presence ─────────────────────────────────────────────────────


def test_config_dir_missing_is_info(tmp_path, isolated_config_dir):
    """A user who has never run any spindoctor command yet has no
    ~/.spindoctor — that's INFO, not WARN."""
    report = sd.run_self_checks(Config(), fix=False)
    cdir = next(c for c in report.checks if c.name == "config_dir")
    assert cdir.status == sd.Status.INFO


def test_config_dir_present_is_ok(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    report = sd.run_self_checks(Config(), fix=False)
    cdir = next(c for c in report.checks if c.name == "config_dir")
    assert cdir.status == sd.Status.OK


# ─── json corruption ─────────────────────────────────────────────────────────


def test_corrupt_config_json_fails(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text(
        "{not valid", encoding="utf-8",
    )
    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "json_config.json")
    assert chk.status == sd.Status.FAIL
    assert "parse" in chk.detail.lower()


def test_non_object_top_level_fails(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "favorites.json").write_text("[1, 2, 3]", encoding="utf-8")
    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "json_favorites.json")
    assert chk.status == sd.Status.FAIL


def test_clean_json_passes(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text(
        json.dumps({"roms_dir": "/x"}), encoding="utf-8",
    )
    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "json_config.json")
    assert chk.status == sd.Status.OK


# ─── rescue copies ───────────────────────────────────────────────────────────


def _make_old_file(path, days_old: float) -> None:
    """Create *path* and backdate its mtime by *days_old* days."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("rescue copy contents", encoding="utf-8")
    old = time.time() - days_old * 86400.0
    os.utime(path, (old, old))


def test_stale_rescue_copies_are_warn(tmp_path, isolated_config_dir):
    """Rescue copies older than 30 days produce a WARN with a reclaim
    estimate. Fresh ones (< 30 days) produce INFO instead."""
    _make_old_file(
        isolated_config_dir / "config.corrupt-20250101.json",
        days_old=60.0,
    )
    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "rescue_copies")
    assert chk.status == sd.Status.WARN
    assert chk.reclaimable_bytes > 0
    assert chk.fixable is True


def test_fresh_rescue_copies_are_info(tmp_path, isolated_config_dir):
    _make_old_file(
        isolated_config_dir / "config.corrupt-recent.json",
        days_old=1.0,
    )
    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "rescue_copies")
    assert chk.status == sd.Status.INFO
    assert chk.reclaimable_bytes == 0


def test_no_rescue_copies_is_ok(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "rescue_copies")
    assert chk.status == sd.Status.OK


# ─── fix mode ────────────────────────────────────────────────────────────────


def test_fix_deletes_stale_rescue_copies(tmp_path, isolated_config_dir):
    """--fix removes stale rescue copies; fresh ones survive; the
    deletion is recorded in fixes_applied."""
    stale = isolated_config_dir / "config.corrupt-stale.json"
    fresh = isolated_config_dir / "config.corrupt-fresh.json"
    _make_old_file(stale, days_old=60.0)
    _make_old_file(fresh, days_old=1.0)

    report = sd.run_self_checks(Config(), fix=True)

    assert not stale.exists()
    assert fresh.exists()
    assert any("stale" in msg for msg in report.fixes_applied)


def test_fix_no_op_when_nothing_stale(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    report = sd.run_self_checks(Config(), fix=True)
    assert report.fixes_applied == []


# ─── manifest dir sizing ─────────────────────────────────────────────────────


def test_manifest_dir_warning_threshold(tmp_path, isolated_config_dir):
    """Manifest dirs over 50 MB produce a WARN; small ones pass."""
    big_dir = isolated_config_dir / "curation"
    big_dir.mkdir(parents=True)
    # 60 MB of zero bytes is plenty to cross the 50 MB threshold.
    (big_dir / "huge.json").write_bytes(b"\0" * (60 * 1024 * 1024))

    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "manifests_curation")
    assert chk.status == sd.Status.WARN


def test_manifest_dirs_match_writers(tmp_path, isolated_config_dir):
    """Every dir the sizing check scans must be one a command actually
    writes to — a renamed manifest dir (curation, not curate) silently
    exempts that category from the size check."""
    from spindoctor.curate import CURATION_DIR
    from spindoctor.edit import EDIT_DIR, RENAME_DIR
    from spindoctor.media_scan import MANIFEST_DIR as MEDIA_IMPORTS_DIR
    from spindoctor.migrate import MIGRATIONS_DIR
    from spindoctor.themes import THEMES_DIR

    writer_dirs = {
        p.name for p in (
            CURATION_DIR, EDIT_DIR, RENAME_DIR,
            MEDIA_IMPORTS_DIR, MIGRATIONS_DIR, THEMES_DIR,
        )
    }
    for name in writer_dirs:
        d = isolated_config_dir / name
        d.mkdir(parents=True)
        (d / "m.json").write_text("{}", encoding="utf-8")

    report = sd.run_self_checks(Config(), fix=False)
    checked = {
        c.name[len("manifests_"):]
        for c in report.checks if c.name.startswith("manifests_")
    }
    assert checked == writer_dirs


def test_metadata_cache_check_sees_real_cache_dir(tmp_path, isolated_config_dir):
    """The size report must look at metadata_cache/ — the dir the scraper
    actually writes — not some other path, or it always reports empty."""
    from spindoctor.scraper import METADATA_CACHE_DIR

    cache = isolated_config_dir / METADATA_CACHE_DIR.name
    (cache / "screenscraper" / "NES").mkdir(parents=True)
    (cache / "screenscraper" / "NES" / "Mario.json").write_text(
        "{}", encoding="utf-8",
    )

    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "metadata_cache")
    assert "1 cached scraper response" in chk.detail


def test_manifest_dir_small_is_ok(tmp_path, isolated_config_dir):
    small_dir = isolated_config_dir / "edits"
    small_dir.mkdir(parents=True)
    (small_dir / "small.json").write_text("{}", encoding="utf-8")

    report = sd.run_self_checks(Config(), fix=False)
    chk = next(c for c in report.checks if c.name == "manifests_edits")
    assert chk.status == sd.Status.OK


# ─── orphan .part files ──────────────────────────────────────────────────────


def test_stale_part_files_are_warn(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    cfg = Config(hyperspin_dir=str(tmp_path / "hs"))
    media = tmp_path / "hs" / "Media" / "MAME" / "Images" / "Wheel"
    media.mkdir(parents=True)
    _make_old_file(media / "1942.png.part", days_old=14.0)

    report = sd.run_self_checks(cfg, fix=False)
    chk = next(c for c in report.checks if c.name == "part_files")
    assert chk.status == sd.Status.WARN
    assert chk.reclaimable_bytes > 0


def test_fix_deletes_stale_part_files(tmp_path, isolated_config_dir):
    cfg = Config(hyperspin_dir=str(tmp_path / "hs"))
    media = tmp_path / "hs" / "Media" / "MAME" / "Images" / "Wheel"
    media.mkdir(parents=True)
    stale = media / "1942.png.part"
    fresh = media / "1943.png.part"
    _make_old_file(stale, days_old=14.0)
    _make_old_file(fresh, days_old=1.0)

    report = sd.run_self_checks(cfg, fix=True)

    assert not stale.exists()
    assert fresh.exists()
    assert any(".part" in msg for msg in report.fixes_applied)


# ─── overall status aggregation ──────────────────────────────────────────────


def test_overall_picks_worst_status(tmp_path, isolated_config_dir):
    """One FAIL anywhere dominates everything below it."""
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text("{bad", encoding="utf-8")
    report = sd.run_self_checks(Config(), fix=False)
    assert report.overall() == sd.Status.FAIL


def test_overall_ok_when_everything_passes(tmp_path, isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text(
        json.dumps({"roms_dir": "/x"}), encoding="utf-8",
    )
    report = sd.run_self_checks(Config(), fix=False)
    # WARN states drop the overall to WARN, OK / INFO leave it OK.
    assert report.overall() in (sd.Status.OK, sd.Status.INFO)


# ─── CLI smoke ───────────────────────────────────────────────────────────────


def test_cli_self_doctor_exits_zero(tmp_path, isolated_config_dir, monkeypatch):
    """The `spindoctor self-doctor` CLI command runs cleanly on a
    fresh config dir and exits 0."""
    from click.testing import CliRunner
    from spindoctor.cli import cli

    isolated_config_dir.mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["self-doctor"])
    assert result.exit_code == 0, result.output
    assert "config_dir" in result.output
