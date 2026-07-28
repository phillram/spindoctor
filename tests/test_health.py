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


def test_check_databases_does_not_crash_on_non_valueerror(tmp_path, monkeypatch):
    """doctor must never crash: a PermissionError/OSError from a locked file
    becomes one FAIL row, not an exception out of the whole command."""
    cfg = _mk_cabinet(tmp_path)
    (cfg.databases_dir / "NES" / "NES.xml").write_text(
        '<menu><game name="Mario"/></menu>', encoding="utf-8")

    def _boom(*a, **k):
        raise PermissionError("file is locked by HyperSpin")

    monkeypatch.setattr(health, "load_database", _boom)
    result = health.check_databases(cfg)  # must not raise
    assert result.status == health.Status.FAIL
    assert "PermissionError" in result.children[0].detail


def test_check_databases_warns_on_empty_db(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    (cfg.databases_dir / "NES" / "NES.xml").write_text(
        "<menu></menu>", encoding="utf-8")  # parses, but zero games
    result = health.check_databases(cfg)
    assert result.status == health.Status.WARN
    assert "empty" in {c.name: c for c in result.children}["NES"].detail


def test_check_match_cache_skips_when_roms_dir_unset(tmp_path, isolated_match_cache):
    cfg = _mk_cabinet(tmp_path)
    cfg.roms_dir = ""
    (isolated_match_cache / "NES.json").write_text('{"Mario": {}}', encoding="utf-8")
    result = health.check_match_cache(cfg, fix=True, fixes_applied=[])
    assert result.status == health.Status.INFO
    # Cache must be untouched (not wiped as "all stale").
    assert (isolated_match_cache / "NES.json").exists()


def test_check_match_cache_case_insensitive_rom_match(tmp_path, isolated_match_cache):
    """A re-cased ROM (mario.zip vs cached 'Mario') is not stale on NTFS."""
    cfg = _mk_cabinet(tmp_path)
    (tmp_path / "roms" / "NES" / "mario.zip").write_bytes(b"x")
    (isolated_match_cache / "NES.json").write_text('{"Mario": {}}', encoding="utf-8")
    result = health.check_match_cache(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.OK


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


def test_check_match_cache_reports_unparseable_files(tmp_path, isolated_match_cache):
    cfg = _mk_cabinet(tmp_path)
    bad = isolated_match_cache / "Broken.json"
    bad.write_text("{not json", encoding="utf-8")
    fixes: list[str] = []
    # Corrupt cache files must now surface as WARN so the user knows about them.
    result = health.check_match_cache(cfg, fix=True, fixes_applied=fixes)
    assert result.status == health.Status.WARN
    assert "Broken.json" in result.detail


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


# ─── check_wheel_wiring (read + --fix) ───────────────────────────────────────


def _seed_main_menu(cfg, *names, extra_xml=""):
    """Write Main Menu.xml under the cabinet's hyperspin_dir."""
    mm = cfg.databases_dir / "Main Menu" / "Main Menu.xml"
    mm.parent.mkdir(parents=True, exist_ok=True)
    games = "".join(f'<game name="{n}"/>' for n in names)
    mm.write_text(f"<menu>{games}{extra_xml}</menu>", encoding="utf-8")
    return mm


def _wheel_node(parent, name):
    return next((c for c in parent.children if c.name == name), None)


def _sub(node, name):
    return next((c for c in node.children if c.name == name), None)


def test_wheel_wiring_skips_without_hyperspin(tmp_path):
    cfg = Config()
    result = health.check_wheel_wiring(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.INFO


def test_wheel_wiring_info_when_no_main_menu(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    result = health.check_wheel_wiring(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.INFO


def test_wheel_wiring_warns_on_missing_settings_ini(tmp_path):
    """The exact bug: a wheel on the Main Menu with no HyperSpin Settings INI."""
    cfg = _mk_cabinet(tmp_path)
    _seed_main_menu(cfg, "Recompiled")
    result = health.check_wheel_wiring(cfg, fix=False, fixes_applied=[])
    assert result.status == health.Status.WARN
    node = _wheel_node(result, "Recompiled")
    ini_check = _sub(node, "HyperSpin settings INI")
    assert ini_check.status == health.Status.WARN
    assert "Cannot find Recompiled.ini" in ini_check.detail
    assert "mainmenu add" in ini_check.fix


def test_wheel_wiring_excludes_search_entry(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    _seed_main_menu(cfg, "Recompiled", extra_xml='<game name="Search" exe="true"/>')
    result = health.check_wheel_wiring(cfg, fix=False, fixes_applied=[])
    assert _wheel_node(result, "Search") is None
    assert _wheel_node(result, "Recompiled") is not None


def test_wheel_wiring_fix_writes_settings_ini_and_theme(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    _seed_main_menu(cfg, "Recompiled")
    fixes: list[str] = []
    result = health.check_wheel_wiring(cfg, fix=True, fixes_applied=fixes)

    ini = cfg.hyperspin_dir + "/Settings/Recompiled.ini"
    from pathlib import Path
    assert Path(ini).exists()
    assert "hyperlaunch=true" in Path(ini).read_text(encoding="utf-8")
    default_zip = Path(cfg.media_dir) / "Recompiled" / "Themes" / "default.zip"
    assert default_zip.exists()
    assert any("Settings/Recompiled.ini" in m for m in fixes)
    # Recompiled is synthetic → emulator sub-check is OK, so the node clears.
    node = _wheel_node(result, "Recompiled")
    assert _sub(node, "HyperSpin settings INI").status == health.Status.OK


def test_wheel_wiring_warns_on_missing_emulator_for_console(tmp_path):
    """A non-synthetic wheel with a Settings INI + theme but no emulator mapping
    still warns, because its games can't launch."""
    cfg = _mk_cabinet(tmp_path)
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    cfg.rocketlauncher_dir = str(rl)
    _seed_main_menu(cfg, "Dreamcast")
    # Give Dreamcast its Settings INI + theme so only the emulator is missing.
    (cfg.hyperspin_dir + "/Settings")  # noqa
    from pathlib import Path
    ini = Path(cfg.hyperspin_dir) / "Settings" / "Dreamcast.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text("[exe info]\nhyperlaunch=true\n", encoding="utf-8")
    theme = Path(cfg.media_dir) / "Dreamcast" / "Themes" / "default.zip"
    theme.parent.mkdir(parents=True, exist_ok=True)
    theme.write_bytes(b"x")
    (cfg.databases_dir / "Dreamcast").mkdir(parents=True, exist_ok=True)
    (cfg.databases_dir / "Dreamcast" / "Dreamcast.xml").write_text(
        "<menu><game name='x'/></menu>", encoding="utf-8")

    node = _wheel_node(
        health.check_wheel_wiring(cfg, fix=False, fixes_applied=[]), "Dreamcast")
    emu = _sub(node, "Emulator")
    assert emu.status == health.Status.WARN
    assert "won't launch" in emu.detail


def test_wheel_wiring_ok_when_emulator_resolves(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings" / "Dreamcast").mkdir(parents=True)
    (rl / "Settings" / "Dreamcast" / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=Demul\n", encoding="utf-8")
    (rl / "Settings" / "Global Emulators.ini").write_text(
        "[Demul]\nEmu_Path=..\\Emulators\\Demul\\demul.exe\n", encoding="utf-8")
    # Emu_Path is relative to RL's Settings/ dir → rl/Emulators/Demul/demul.exe.
    (rl / "Emulators" / "Demul").mkdir(parents=True)
    (rl / "Emulators" / "Demul" / "demul.exe").write_bytes(b"MZ")
    cfg.rocketlauncher_dir = str(rl)
    _seed_main_menu(cfg, "Dreamcast")
    from pathlib import Path
    ini = Path(cfg.hyperspin_dir) / "Settings" / "Dreamcast.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text("[exe info]\nhyperlaunch=true\n", encoding="utf-8")
    theme = Path(cfg.media_dir) / "Dreamcast" / "Themes" / "default.zip"
    theme.parent.mkdir(parents=True, exist_ok=True)
    theme.write_bytes(b"x")
    (cfg.databases_dir / "Dreamcast").mkdir(parents=True, exist_ok=True)
    (cfg.databases_dir / "Dreamcast" / "Dreamcast.xml").write_text(
        "<menu><game name='x'/></menu>", encoding="utf-8")

    node = _wheel_node(
        health.check_wheel_wiring(cfg, fix=False, fixes_applied=[]), "Dreamcast")
    emu = _sub(node, "Emulator")
    assert emu.status == health.Status.OK
    assert "demul.exe" in emu.detail


def test_wheel_wiring_warns_when_emulator_exe_missing_on_disk(tmp_path):
    """Emulator is registered in Global Emulators.ini, but its Emu_Path binary
    doesn't exist (stale after uninstall/drive change) → WARN, not a false OK."""
    cfg = _mk_cabinet(tmp_path)
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings" / "Dreamcast").mkdir(parents=True)
    (rl / "Settings" / "Dreamcast" / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=Demul\n", encoding="utf-8")
    (rl / "Settings" / "Global Emulators.ini").write_text(
        "[Demul]\nEmu_Path=..\\Emulators\\Demul\\demul.exe\n", encoding="utf-8")
    # Note: the demul.exe binary is deliberately NOT created.
    cfg.rocketlauncher_dir = str(rl)
    _seed_main_menu(cfg, "Dreamcast")
    from pathlib import Path
    ini = Path(cfg.hyperspin_dir) / "Settings" / "Dreamcast.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text("[exe info]\nhyperlaunch=true\n", encoding="utf-8")
    theme = Path(cfg.media_dir) / "Dreamcast" / "Themes" / "default.zip"
    theme.parent.mkdir(parents=True, exist_ok=True)
    theme.write_bytes(b"x")
    (cfg.databases_dir / "Dreamcast").mkdir(parents=True, exist_ok=True)
    (cfg.databases_dir / "Dreamcast" / "Dreamcast.xml").write_text(
        "<menu><game name='x'/></menu>", encoding="utf-8")

    node = _wheel_node(
        health.check_wheel_wiring(cfg, fix=False, fixes_applied=[]), "Dreamcast")
    emu = _sub(node, "Emulator")
    assert emu.status == health.Status.WARN
    assert "not found on disk" in emu.detail


# ─── check_lightguns ─────────────────────────────────────────────────────────


def _lightgun_cabinet(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    cfg.rocketlauncher_dir = str(rl)
    return cfg, rl


def _write_rl_ini(rl, system, body):
    (rl / "Settings" / f"{system}.ini").write_text(body, encoding="utf-8")


def test_lightguns_info_when_none_marked(tmp_path):
    cfg = _mk_cabinet(tmp_path)
    assert health.check_lightguns(cfg).status == health.Status.INFO


def test_lightguns_fail_when_marked_but_not_wired(tmp_path):
    cfg, rl = _lightgun_cabinet(tmp_path)
    cfg.set_lightgun("Point Blank", True)
    # No RL INI at all for the system → not wired.
    result = health.check_lightguns(cfg)
    assert result.status == health.Status.FAIL
    node = _wheel_node(result, "Point Blank")
    assert node.status == health.Status.FAIL
    assert "no gun" in node.detail
    assert "lightgun configure" in node.fix


def test_lightguns_ok_when_fully_wired(tmp_path):
    cfg, rl = _lightgun_cabinet(tmp_path)
    cfg.set_lightgun("Point Blank", True)
    _write_rl_ini(rl, "Point Blank",
                  "[Point Blank]\n"
                  "Pre_Launch_App=C:\\Tools\\DemulShooter.exe -target demul\n"
                  "Post_Launch_App=taskkill /IM DemulShooter.exe\n")
    result = health.check_lightguns(cfg)
    assert result.status == health.Status.OK
    node = _wheel_node(result, "Point Blank")
    assert _sub(node, "target").detail.endswith("demul")


def test_lightguns_warn_when_teardown_missing(tmp_path):
    cfg, rl = _lightgun_cabinet(tmp_path)
    cfg.set_lightgun("Point Blank", True)
    _write_rl_ini(rl, "Point Blank",
                  "[Point Blank]\n"
                  "Pre_Launch_App=C:\\Tools\\DemulShooter.exe -target demul\n")
    result = health.check_lightguns(cfg)
    assert result.status == health.Status.WARN
    node = _wheel_node(result, "Point Blank")
    assert _sub(node, "teardown").status == health.Status.WARN


def test_lightguns_warn_on_bad_demulshooter_path(tmp_path):
    cfg, rl = _lightgun_cabinet(tmp_path)
    cfg.set_lightgun("Point Blank", True)
    _write_rl_ini(rl, "Point Blank",
                  "[Point Blank]\n"
                  "Pre_Launch_App=C:\\Tools\\DemulShooter.exe -target demul\n"
                  "Post_Launch_App=taskkill /IM DemulShooter.exe\n")
    cfg.demulshooter_path = str(tmp_path / "nope" / "DemulShooter.exe")
    result = health.check_lightguns(cfg)
    assert _sub(result, "demulshooter_path").status == health.Status.WARN


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
    assert "Wheel wiring" in names
    assert "Match cache" in names
    assert "Global Emulators.ini" in names
    assert "Lightguns" in names
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
