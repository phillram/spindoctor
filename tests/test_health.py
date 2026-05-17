"""Tests for spindoctor.health — the `doctor` command's check pipeline.

Each ``check_*`` is exercised in isolation, with disk fixtures that
mirror what a real cabinet would look like in OK / WARN / FAIL states.
Critically, the ``--fix`` path on ``check_match_cache`` is covered: it
mutates files on disk and the previous baseline had no test for it.
"""
from __future__ import annotations

import json

import pytest

from spindoctor import health
from spindoctor.config import Config


def _mk_cabinet(tmp_path):
    roms = tmp_path / "roms"
    hs = tmp_path / "hs"
    (roms / "NES").mkdir(parents=True)
    (hs / "Databases" / "NES").mkdir(parents=True)
    (hs / "Media" / "NES").mkdir(parents=True)
    return Config(roms_dir=str(roms), hyperspin_dir=str(hs))


# ─── check_paths ─────────────────────────────────────────────────────────────


def test_check_paths_fails_when_required_missing(tmp_path):
    cfg = Config()
    result = health.check_paths(cfg)
    assert result.status == health.Status.FAIL
    statuses = {c.name: c.status for c in result.children}
    assert statuses["roms_dir"] == health.Status.FAIL
    assert statuses["hyperspin_dir"] == health.Status.FAIL


def test_check_paths_warns_when_optional_missing(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    result = health.check_paths(cfg)
    # Required paths exist; optional ones (rocketlauncher_dir,
    # emulators_dir, ledblinky_dir) are blank → WARN, not FAIL.
    assert result.status == health.Status.WARN


def test_check_paths_ok_when_everything_configured(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    for opt in ("rocketlauncher_dir", "emulators_dir", "ledblinky_dir"):
        d = tmp_path / opt
        d.mkdir()
        setattr(cfg, opt, str(d))
    assert health.check_paths(cfg).status == health.Status.OK


def test_check_paths_flags_file_at_directory_slot(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    bogus = tmp_path / "rocketlauncher.exe"
    bogus.write_bytes(b"x")
    cfg.rocketlauncher_dir = str(bogus)
    result = health.check_paths(cfg)
    detail = {c.name: c for c in result.children}["rocketlauncher_dir"]
    assert detail.status == health.Status.WARN
    assert "not a directory" in detail.detail


# ─── check_binaries ──────────────────────────────────────────────────────────


def test_check_binaries_fails_when_mame_path_invalid(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    cfg.mame_executable = str(tmp_path / "missing-mame")
    result = health.check_binaries(cfg)
    by_name = {c.name: c for c in result.children}
    assert by_name["mame_executable"].status == health.Status.FAIL


def test_check_binaries_warns_when_mame_unconfigured(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    by_name = {c.name: c for c in health.check_binaries(cfg).children}
    assert by_name["mame_executable"].status == health.Status.WARN


# ─── check_lxml & soft deps ──────────────────────────────────────────────────


def test_check_lxml_returns_either_ok_or_warn():
    """Status depends on whether lxml is installed in the test env;
    the function itself shouldn't raise either way."""
    result = health.check_lxml()
    assert result.status in (health.Status.OK, health.Status.WARN)


def test_check_archive_support_runs_without_crashing():
    parent = health.check_archive_support()
    assert parent.name == "Archive support"
    assert {c.name for c in parent.children} == {".zip", ".7z", ".rar", ".gz", ".chd"}


def test_check_preview_support_runs_without_crashing():
    result = health.check_preview_support()
    assert result.name == "Preview support"
    assert result.status in (health.Status.OK, health.Status.WARN)


# ─── check_databases ─────────────────────────────────────────────────────────


def test_check_databases_skips_when_hyperspin_missing(tmp_path):
    cfg = Config()
    result = health.check_databases(cfg)
    assert result.status == health.Status.INFO


def test_check_databases_ok_with_valid_xml(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    xml = cfg.databases_dir / "NES" / "NES.xml"
    xml.write_text(
        '<?xml version="1.0"?><menu><game name="Mario"/></menu>',
        encoding="utf-8",
    )
    result = health.check_databases(cfg)
    assert result.status == health.Status.OK
    statuses = {c.name: c.status for c in result.children}
    assert statuses["NES"] == health.Status.OK


def test_check_databases_fails_with_broken_xml(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    xml = cfg.databases_dir / "NES" / "NES.xml"
    xml.write_text("<menu><game", encoding="utf-8")  # truncated
    result = health.check_databases(cfg)
    assert result.status == health.Status.FAIL


# ─── check_match_cache (read + --fix paths) ──────────────────────────────────


@pytest.fixture
def isolated_match_cache(tmp_path, monkeypatch):
    """Point the matcher cache at a tmp dir so writes don't touch ~/."""
    cache = tmp_path / "matcher-cache"
    cache.mkdir()
    from spindoctor import matcher
    monkeypatch.setattr(matcher, "CACHE_DIR", cache)
    return cache


def test_check_match_cache_ok_when_no_cache_dir(tmp_path, monkeypatch):
    from spindoctor import matcher
    monkeypatch.setattr(matcher, "CACHE_DIR", tmp_path / "no-such")
    cfg = _mk_cabinet(tmp_path)
    fixes: list[str] = []
    result = health.check_match_cache(cfg, fix=False, fixes_applied=fixes)
    assert result.status == health.Status.OK
    assert "no cache" in result.detail
    assert fixes == []


def test_check_match_cache_warns_about_stale_entries(tmp_path, isolated_match_cache):
    cfg = _mk_cabinet(tmp_path)
    # Match cache claims three ROMs; only one actually exists on disk.
    (cfg.roms_dir + "/NES" + "/Mario.zip")  # purely to document intent
    rom_dir = tmp_path / "roms" / "NES"
    (rom_dir / "Mario.zip").write_bytes(b"x")
    cache_file = isolated_match_cache / "NES.json"
    cache_file.write_text(json.dumps({
        "Mario": {"matched": True},
        "DeletedGame1": {"matched": True},
        "DeletedGame2": {"matched": True},
    }), encoding="utf-8")
    fixes: list[str] = []
    result = health.check_match_cache(cfg, fix=False, fixes_applied=fixes)
    assert result.status == health.Status.WARN
    assert "2 stale entries" in result.detail
    # Without --fix, the cache file must remain untouched.
    assert set(json.loads(cache_file.read_text())) == {"Mario", "DeletedGame1", "DeletedGame2"}
    assert fixes == []


def test_check_match_cache_fix_prunes_stale_entries(tmp_path, isolated_match_cache):
    cfg = _mk_cabinet(tmp_path)
    rom_dir = tmp_path / "roms" / "NES"
    (rom_dir / "Mario.zip").write_bytes(b"x")
    cache_file = isolated_match_cache / "NES.json"
    cache_file.write_text(json.dumps({
        "Mario": {"m": True},
        "Gone": {"m": True},
    }), encoding="utf-8")
    fixes: list[str] = []
    result = health.check_match_cache(cfg, fix=True, fixes_applied=fixes)
    assert result.status == health.Status.OK
    assert set(json.loads(cache_file.read_text())) == {"Mario"}
    assert any("pruned 1" in m for m in fixes)


def test_check_match_cache_skips_unparseable_files(tmp_path, isolated_match_cache):
    cfg = _mk_cabinet(tmp_path)
    bad = isolated_match_cache / "Broken.json"
    bad.write_text("{not json", encoding="utf-8")
    fixes: list[str] = []
    # Must not raise — corrupt cache files are just skipped.
    result = health.check_match_cache(cfg, fix=True, fixes_applied=fixes)
    assert result.status == health.Status.OK


# ─── check_global_emulators ──────────────────────────────────────────────────


def test_check_global_emulators_skips_without_rocketlauncher(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    result = health.check_global_emulators(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.INFO


def test_check_global_emulators_ok_when_file_present(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    (rl / "Settings" / "Global Emulators.ini").write_text("[ZSNES]\n", encoding="utf-8")
    cfg.rocketlauncher_dir = str(rl)
    result = health.check_global_emulators(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.OK


def test_check_global_emulators_warns_when_missing(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    cfg.rocketlauncher_dir = str(rl)
    result = health.check_global_emulators(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.WARN


# ─── check_ledblinky ─────────────────────────────────────────────────────────


def test_check_ledblinky_info_when_unconfigured(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    assert health.check_ledblinky(cfg).status == health.Status.INFO


def test_check_ledblinky_warns_on_missing_files(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    led = tmp_path / "led"
    led.mkdir()
    cfg.ledblinky_dir = str(led)
    result = health.check_ledblinky(cfg)
    assert result.status == health.Status.WARN
    assert all(c.status == health.Status.WARN for c in result.children)


# ─── check_api_creds ─────────────────────────────────────────────────────────


def test_check_api_creds_info_when_blank(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    parent = health.check_api_creds(cfg)
    statuses = {c.name: c.status for c in parent.children}
    assert statuses["ScreenScraper"] == health.Status.INFO
    assert statuses["TheGamesDB"] == health.Status.INFO


def test_check_api_creds_reports_configured_credentials(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    cfg.screenscraper_user = "u"
    cfg.screenscraper_pass = "p"
    cfg.thegamesdb_key = "abc"
    parent = health.check_api_creds(cfg)
    statuses = {c.name: c.status for c in parent.children}
    assert statuses["ScreenScraper"] == health.Status.OK
    assert statuses["TheGamesDB"] == health.Status.OK


# ─── check_media_skeletons (read + --fix) ────────────────────────────────────


def test_check_media_skeletons_info_when_missing_subfolders(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    fixes: list[str] = []
    result = health.check_media_skeletons(cfg, fix=False, fixes_applied=fixes)
    assert result.status == health.Status.INFO
    assert "subfolders not created" in result.detail
    assert fixes == []


def test_check_media_skeletons_fix_creates_folders(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    fixes: list[str] = []
    result = health.check_media_skeletons(cfg, fix=True, fixes_applied=fixes)
    assert result.status == health.Status.OK
    # Every expected leaf must now exist.
    for parts in (("Images", "Wheel"), ("Images", "Backgrounds"),
                  ("Video",), ("Sound",), ("Themes",)):
        assert (cfg.media_dir / "NES" / "/".join(parts)).exists()
    assert any("media subfolder" in m for m in fixes)


# ─── run_health_checks orchestration ─────────────────────────────────────────


def test_run_health_checks_emits_all_sections(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    report = health.run_health_checks(cfg, fix=False)
    names = [c.name for c in report.checks]
    assert "Paths" in names
    assert "External binaries" in names
    assert "lxml" in names
    assert "Archive support" in names
    assert "Preview support" in names
    assert "HyperSpin databases" in names
    assert "Match cache" in names
    assert "Global Emulators.ini" in names
    assert "LEDBlinky" in names
    assert "Metadata APIs" in names
    assert "Media folders" in names


def test_health_report_overall_picks_worst_status():
    rep = health.HealthReport()
    rep.add(health.Check("a", health.Status.OK))
    rep.add(health.Check("b", health.Status.WARN))
    assert rep.overall() == health.Status.WARN
    # FAIL trumps WARN.
    rep.add(health.Check("c", health.Status.FAIL))
    assert rep.overall() == health.Status.FAIL


def test_health_report_overall_visits_nested_children():
    """Worst status can live arbitrarily deep in the children tree."""
    rep = health.HealthReport()
    parent = health.Check("p", health.Status.OK)
    parent.children.append(health.Check("c1", health.Status.OK))
    parent.children.append(health.Check("c2", health.Status.FAIL))
    rep.add(parent)
    assert rep.overall() == health.Status.FAIL
