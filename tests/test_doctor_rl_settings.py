"""Tests for the `doctor` RocketLauncher settings check
(``health.check_rocketlauncher_settings``).

Each test builds a throwaway RocketLauncher tree: ``Settings/RocketLauncher.ini``
(program paths, logging), ``Settings/Global RocketLauncher.ini`` (the global
virtual-drive switch) and optional ``Settings/<System>/RocketLauncher.ini``
overrides.  Program paths are absolute temp paths, so the existence checks
run the same on Windows and POSIX.
"""
from __future__ import annotations

import pytest

from spindoctor import health
from spindoctor.config import Config


def _cabinet(tmp_path, *, vd_path="", logging_level="3", global_vd="false", systems=None):
    """RocketLauncher dir with its settings INIs; returns (config, rl_dir).

    *systems* maps a system name to its own ``Virtual_Drive_Enabled`` value.
    """
    rl = tmp_path / "RocketLauncher"
    settings = rl / "Settings"
    settings.mkdir(parents=True)
    # RocketLauncher won't launch anything without 7z.exe; ship one so only the
    # setting under test decides the parent's status.
    (rl / "Module Extensions").mkdir()
    (rl / "Module Extensions" / "7z.exe").write_bytes(b"MZ")
    (settings / "RocketLauncher.ini").write_text(
        "[Settings]\nModules_Path=.\\Modules\n\n"
        f"[Logging]\nLogging_Level={logging_level}\n\n"
        "[7z]\n7z_Path=.\\Module Extensions\\7z.exe\n\n"
        f"[Virtual Drive]\nVirtual_Drive_Path={vd_path}\nVirtual_Drive_Add_Drive=true\n",
        encoding="utf-8")
    (settings / "Global RocketLauncher.ini").write_text(
        f"[Virtual Drive]\nVirtual_Drive_Enabled={global_vd}\nVirtual_Drive_Use_SCSI=true\n",
        encoding="utf-8")
    for system, value in (systems or {}).items():
        (settings / system).mkdir()
        (settings / system / "RocketLauncher.ini").write_text(
            f"[Virtual Drive]\nVirtual_Drive_Enabled={value}\nVirtual_Drive_Use_SCSI=true\n",
            encoding="utf-8")
    return Config(rocketlauncher_dir=str(rl)), rl


def _dtlite(tmp_path, program_files, create=False):
    """DTLite.exe under a fake ``<drive>/<program_files>/DAEMON Tools Lite``."""
    exe = tmp_path / "C" / program_files / "DAEMON Tools Lite" / "DTLite.exe"
    if create:
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
    return exe


def _sub(node, name):
    return next((c for c in node.children if c.name == name), None)


# ─── virtual drive ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("configured, installed", [
    ("Program Files (x86)", "Program Files"),   # reinstalled as 64-bit
    ("Program Files", "Program Files (x86)"),   # reinstalled as 32-bit
])
def test_missing_vd_path_warns_and_names_the_other_program_files_path(tmp_path, configured, installed):
    stale = _dtlite(tmp_path, configured)
    real = _dtlite(tmp_path, installed, create=True)
    cfg, rl = _cabinet(tmp_path, vd_path=str(stale), global_vd="true",
                       systems={"Sega Saturn": "true", "NES": "use_global"})
    result = health.check_rocketlauncher_settings(cfg)
    assert result.status == health.Status.WARN
    vd = _sub(result, "Virtual drive")
    assert vd.status == health.Status.WARN
    assert str(stale) in vd.detail
    assert "Sega Saturn" in vd.detail
    # The fix is the exact edit: key, section, file and the path that exists.
    assert f"Virtual_Drive_Path={real}" in vd.fix
    assert "[Virtual Drive]" in vd.fix
    assert str(rl / "Settings" / "RocketLauncher.ini") in vd.fix


def test_missing_vd_path_without_alternate_names_file_and_key(tmp_path):
    stale = _dtlite(tmp_path, "Program Files (x86)")  # and no 64-bit install either
    cfg, rl = _cabinet(tmp_path, vd_path=str(stale), systems={"Sega Saturn": "true"})
    vd = _sub(health.check_rocketlauncher_settings(cfg), "Virtual drive")
    assert vd.status == health.Status.WARN
    assert "Virtual_Drive_Path" in vd.fix
    assert "[Virtual Drive]" in vd.fix
    assert "other Program Files" not in vd.fix


@pytest.mark.parametrize("global_vd, systems", [
    ("false", {"NES": "use_global", "Sony Playstation": "false"}),
    ("false", {}),
    # On globally, but every system turns it off for itself.
    ("true", {"NES": "false", "Sony Playstation": "false"}),
])
def test_missing_vd_path_is_info_when_no_system_uses_it(tmp_path, global_vd, systems):
    stale = _dtlite(tmp_path, "Program Files (x86)")
    real = _dtlite(tmp_path, "Program Files", create=True)
    cfg, _ = _cabinet(tmp_path, vd_path=str(stale), global_vd=global_vd, systems=systems)
    result = health.check_rocketlauncher_settings(cfg)
    vd = _sub(result, "Virtual drive")
    assert vd.status == health.Status.INFO
    assert "no system uses" in vd.detail
    assert str(real) in vd.fix  # still worth pointing at, but nothing is broken
    assert result.status != health.Status.WARN


def test_empty_vd_path_is_ok_when_unused(tmp_path):
    cfg, _ = _cabinet(tmp_path, vd_path="", systems={"NES": "use_global"})
    vd = _sub(health.check_rocketlauncher_settings(cfg), "Virtual drive")
    assert vd.status == health.Status.OK


def test_per_system_enable_with_global_disabled(tmp_path):
    stale = _dtlite(tmp_path, "Program Files (x86)")
    cfg, _ = _cabinet(tmp_path, vd_path=str(stale), global_vd="false",
                      systems={"Sega Saturn": "true", "SNK Neo Geo CD": "TRUE",
                               "NES": "use_global", "SNES": "false"})
    vd = _sub(health.check_rocketlauncher_settings(cfg), "Virtual drive")
    assert vd.status == health.Status.WARN
    assert "enabled for Sega Saturn, SNK Neo Geo CD" in vd.detail
    # use_global follows the (off) global switch; false is off.
    assert "NES" not in vd.detail
    assert "globally" not in vd.detail


def test_global_enable_lists_switched_on_systems_first_and_skips_opt_outs(tmp_path):
    stale = _dtlite(tmp_path, "Program Files (x86)")
    systems = {"Sega Saturn": "true", "Sony Playstation": "false", "NES": "use_global"}
    for i in range(1, 6):
        systems[f"Arcade {i}"] = "use_global"
    cfg, rl = _cabinet(tmp_path, vd_path=str(stale), global_vd="true", systems=systems)
    # A system folder with no RocketLauncher.ini of its own inherits too.
    (rl / "Settings" / "MAME").mkdir()
    vd = _sub(health.check_rocketlauncher_settings(cfg), "Virtual drive")
    assert vd.status == health.Status.WARN
    # 8 users: Sega Saturn (switched on) first, then the inheritors A-Z.
    assert "enabled globally (8 system(s): Sega Saturn, Arcade 1, Arcade 2, Arcade 3, Arcade 4 and 3 more)" \
        in vd.detail
    assert "Sony Playstation" not in vd.detail


def test_empty_vd_path_warns_when_enabled(tmp_path):
    cfg, _ = _cabinet(tmp_path, vd_path="", systems={"Sega Saturn": "true"})
    vd = _sub(health.check_rocketlauncher_settings(cfg), "Virtual drive")
    assert vd.status == health.Status.WARN
    assert "empty" in vd.detail
    assert "Sega Saturn" in vd.detail


def test_vd_ok_when_path_exists(tmp_path):
    real = _dtlite(tmp_path, "Program Files", create=True)
    cfg, _ = _cabinet(tmp_path, vd_path=str(real), global_vd="true")
    result = health.check_rocketlauncher_settings(cfg)
    assert _sub(result, "Virtual drive").status == health.Status.OK
    assert result.status == health.Status.OK


def test_relative_vd_path_resolves_against_rocketlauncher_dir(tmp_path):
    # ..\Tools\DTLite.exe from the RocketLauncher folder, as RocketLauncher reads it.
    exe = tmp_path / "Tools" / "DTLite.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    cfg, _ = _cabinet(tmp_path, vd_path="..\\Tools\\DTLite.exe", global_vd="true")
    assert _sub(health.check_rocketlauncher_settings(cfg), "Virtual drive").status == health.Status.OK


# ─── 7-Zip ───────────────────────────────────────────────────────────────────


def test_missing_7z_path_warns(tmp_path):
    cfg, rl = _cabinet(tmp_path)
    (rl / "Module Extensions" / "7z.exe").unlink()
    result = health.check_rocketlauncher_settings(cfg)
    seven = _sub(result, "7-Zip")
    assert seven.status == health.Status.WARN
    assert "every launch" in seven.detail
    assert "7z_Path" in seven.fix
    assert result.status == health.Status.WARN


# ─── logging ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("level, expected", [
    ("4", health.Status.INFO),
    ("5", health.Status.INFO),
    ("10", health.Status.INFO),
    ("3", health.Status.OK),
    ("2", health.Status.OK),
])
def test_logging_level(tmp_path, level, expected):
    cfg, _ = _cabinet(tmp_path, logging_level=level)
    result = health.check_rocketlauncher_settings(cfg)
    log = _sub(result, "Logging")
    assert log.status == expected
    if expected == health.Status.INFO:
        assert "slows every launch" in log.detail
        assert "Logging_Level=3" in log.fix
    # INFO never raises the overall verdict.
    assert result.status == health.Status.OK


# ─── robustness ──────────────────────────────────────────────────────────────


def test_no_settings_file_is_info(tmp_path):
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    result = health.check_rocketlauncher_settings(Config(rocketlauncher_dir=str(rl)))
    assert result.status == health.Status.INFO
    assert "no RocketLauncher.ini" in result.detail


def test_skips_without_rocketlauncher_dir():
    result = health.check_rocketlauncher_settings(Config())
    assert result.status == health.Status.INFO


def test_missing_keys_fall_back_to_rocketlauncher_defaults(tmp_path):
    cfg, rl = _cabinet(tmp_path)
    settings = rl / "Settings"
    # No [Logging], [7z] or [Virtual Drive] at all, and no global INI.
    (settings / "RocketLauncher.ini").write_text("[Settings]\nModules_Path=.\\Modules\n", encoding="utf-8")
    (settings / "Global RocketLauncher.ini").unlink()
    result = health.check_rocketlauncher_settings(cfg)
    assert result.status == health.Status.OK
    assert "uses 3" in _sub(result, "Logging").detail
    # 7z_Path defaults to RocketLauncher's own Module Extensions\7z.exe.
    assert _sub(result, "7-Zip").status == health.Status.OK
    assert _sub(result, "Virtual drive").status == health.Status.OK


def test_lowercase_sections_keys_and_utf8_bom(tmp_path):
    stale = _dtlite(tmp_path, "Program Files (x86)")
    real = _dtlite(tmp_path, "Program Files", create=True)
    cfg, rl = _cabinet(tmp_path)
    settings = rl / "Settings"
    # utf-8-sig writes the BOM some editors leave in front of the first section.
    (settings / "RocketLauncher.ini").write_text(
        f"[logging]\nlogging_level=4\n\n[virtual drive]\nvirtual_drive_path={stale}\n",
        encoding="utf-8-sig")
    (settings / "Global RocketLauncher.ini").write_text(
        "[VIRTUAL DRIVE]\nVIRTUAL_DRIVE_ENABLED=True\n", encoding="utf-8-sig")
    result = health.check_rocketlauncher_settings(cfg)
    assert _sub(result, "Logging").status == health.Status.INFO
    vd = _sub(result, "Virtual drive")
    assert vd.status == health.Status.WARN
    assert str(real) in vd.fix


# ─── orchestration ───────────────────────────────────────────────────────────


def test_doctor_runs_it_right_after_global_emulators(tmp_path):
    roms = tmp_path / "roms"
    hs = tmp_path / "hs"
    (roms / "NES").mkdir(parents=True)
    (hs / "Databases" / "NES").mkdir(parents=True)
    cfg, _ = _cabinet(tmp_path, logging_level="4")
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hs)
    names = [c.name for c in health.run_health_checks(cfg, fix=False).checks]
    assert names.index("RocketLauncher settings") == names.index("Global Emulators.ini") + 1
