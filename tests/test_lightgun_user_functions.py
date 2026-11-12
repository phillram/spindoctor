"""Light-gun wiring started from RocketLauncher User Functions.

Many cabinets start the Sinden software (``Lightgun.exe``) and DemulShooter
from the AHK files RocketLauncher runs per system, game and emulator
(``Lib\\User Functions``), not from a ``Pre_Launch_App`` hook.  ``detect``,
``audit`` and ``doctor`` must count that as wired, and ``configure`` warns
that a hook on top of it would start the gun software twice.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

from spindoctor import health, lightgun
from spindoctor.cli import cli
from spindoctor.config import Config, save_config
from spindoctor.lightgun import (
    LightgunInstall,
    audit_system_wiring,
    detect_lightgun_systems,
    plan_wire_system,
)

SINDEN_RUN = "run, Lightgun.exe, D:\\Arcade\\Utilities\\Sinden\\Sinden P1\\SindenLightgun"
DEMUL_RUN = "Run, D:\\Arcade\\Utilities\\DemulShooter\\DemulShooter.exe -target=model2 -rom=vcop"
UF = "Lib\\User Functions"


@pytest.fixture(autouse=True)
def _no_system_scan_roots(monkeypatch):
    """configure also scans Program Files, LocalAppData and the Start Menu;
    keep a lightgun install on the test machine out of these tests."""
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA",
                "APPDATA", "PROGRAMDATA"):
        monkeypatch.delenv(var, raising=False)


def _write(p: Path, body: str = "", encoding: str = "utf-8") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding=encoding)
    return p


def _ahk(*lines: str) -> str:
    """A User Functions file whose InitUserFeatures() holds *lines*."""
    body = "".join(f"\t\t{line}\n" for line in lines)
    return (
        "; Code in this file will only be run for the system whose name matches\n"
        "class SystemUserFunction extends UserFunction {\n"
        "\tInitUserFeatures() {\n"
        f"{body}"
        "\t}\n"
        "}\n"
    )


def _cabinet(tmp_path, system="Gun Games", emulator="MAME (Gun Games)", games_ini=""):
    """A folder-layout system; returns its config and the User Functions folder."""
    rl = tmp_path / "RocketLauncher"
    _write(rl / "Settings" / system / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator={emulator}\nRom_Path=D:\\Games\\{system}\n")
    if games_ini:
        _write(rl / "Settings" / system / "Games.ini", games_ini)
    cfg = Config(roms_dir=str(tmp_path / "roms"), hyperspin_dir=str(tmp_path / "hs"),
                 rocketlauncher_dir=str(rl))
    return cfg, rl / "Lib" / "User Functions"


def _node(check, name):
    return next(c for c in check.children if c.name == name)


# ─── which lines count ───────────────────────────────────────────────────────

def test_system_file_that_runs_lightgun_counts_as_wired(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(SINDEN_RUN))
    status = audit_system_wiring("Gun Games", cfg)
    assert status.wired_via_user_functions
    assert not status.is_wired  # no Pre_Launch_App hook
    assert status.user_functions == [f"{UF}\\Gun Games.ahk"]
    assert status.user_functions_programs == {"lightgun"}


@pytest.mark.parametrize("line", [
    "Run, D:\\Arcade\\Utilities\\DemulShooter\\DemulShooter.exe -target=model2",
    'RunWait "D:\\Arcade\\Tools\\DemulShooterX64.exe" -target=lindbergh',
    'Run("D:\\Arcade\\Utilities\\Sinden\\Lightgun.exe")',
    "run,Lightgun.exe, D:\\Arcade\\Utilities\\Sinden",
    "Run, %comspec% /c start Lightgun.exe",
])
def test_run_lines_in_any_form_count(tmp_path, line):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(line))
    assert audit_system_wiring("Gun Games", cfg).wired_via_user_functions


@pytest.mark.parametrize("lines", [
    ("; " + SINDEN_RUN,),
    (";" + SINDEN_RUN,),
    ("; [Sinden v1 off] " + SINDEN_RUN,),
    ("/*", SINDEN_RUN, DEMUL_RUN, "*/"),
    ("/* " + SINDEN_RUN + " */",),
    ("RunWait, notepad.exe ; Lightgun.exe is started elsewhere",),
    ("process=Lightgun.exe", "Process, Exist, %process%"),
    ("Process, Close, DemulShooter.exe",),
    ("Run, D:\\Arcade\\Utilities\\JoyToKey\\JoyToKey.exe",),
])
def test_comments_and_other_lines_do_not_count(tmp_path, lines):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(*lines))
    status = audit_system_wiring("Gun Games", cfg)
    assert not status.wired_via_user_functions
    assert status.user_functions == [] and status.user_functions_games == []


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1252", "utf-16"])
def test_files_are_read_whatever_their_encoding(tmp_path, encoding):
    """A BOM must not hide a Run on the first line; ANSI accents and UTF-16
    (Notepad's "Unicode") must not make the file unreadable."""
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", SINDEN_RUN + "\n; Sinden réglé\n", encoding=encoding)
    assert audit_system_wiring("Gun Games", cfg).user_functions_programs == {"lightgun"}


# ─── which files count ───────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", [
    "Emulators/MAME (Gun Games).ahk",
    "Gun Games/Emulators/MAME (Gun Games).ahk",
])
def test_the_systems_emulator_files_count(tmp_path, rel):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / rel, _ahk(SINDEN_RUN))
    status = audit_system_wiring("Gun Games", cfg)
    assert status.user_functions == [UF + "\\" + rel.replace("/", "\\")]


def test_other_emulators_and_systems_files_do_not_count(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Emulators" / "Demul.ahk", _ahk(DEMUL_RUN))
    _write(uf / "Gun Games" / "Emulators" / "Demul.ahk", _ahk(DEMUL_RUN))
    _write(uf / "Other Guns.ahk", _ahk(SINDEN_RUN))
    _write(uf / "Global.ahk", _ahk(SINDEN_RUN))
    _write(uf / "Gun Games.old.ahk", _ahk(SINDEN_RUN))
    assert not audit_system_wiring("Gun Games", cfg).wired_via_user_functions


def test_games_ini_emulator_overrides_count(tmp_path):
    cfg, uf = _cabinet(tmp_path, games_ini=(
        "[Time Crisis II (USA)]\nEmulator=PCSX2 (Gun Games)\n"))
    _write(uf / "Emulators" / "PCSX2 (Gun Games).ahk", _ahk(DEMUL_RUN))
    status = audit_system_wiring("Gun Games", cfg)
    assert status.user_functions == [f"{UF}\\Emulators\\PCSX2 (Gun Games).ahk"]
    assert status.user_functions_programs == {"demulshooter"}


def test_game_files_are_counted_per_game(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games" / "vcop.ahk", _ahk(DEMUL_RUN))
    _write(uf / "Gun Games" / "hotd.ahk", _ahk(DEMUL_RUN))
    _write(uf / "Gun Games" / "lethalen.ahk", _ahk("; " + DEMUL_RUN))
    status = audit_system_wiring("Gun Games", cfg)
    assert status.user_functions == []
    assert status.user_functions_games == [f"{UF}\\Gun Games\\hotd.ahk",
                                           f"{UF}\\Gun Games\\vcop.ahk"]
    assert status.user_functions_where() == f"2 game files in {UF}\\Gun Games"


def test_names_match_case_insensitively(tmp_path):
    """RocketLauncher finds User Functions files whatever their case; the
    report keeps the spelling on disk."""
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "gun games.AHK", _ahk(SINDEN_RUN))
    _write(uf / "EMULATORS" / "mame (gun games).ahk", _ahk(SINDEN_RUN))
    status = audit_system_wiring("Gun Games", cfg)
    assert status.user_functions == [f"{UF}\\gun games.AHK",
                                     f"{UF}\\EMULATORS\\mame (gun games).ahk"]


def test_files_are_indexed_once_and_never_statted_per_game(tmp_path, monkeypatch):
    rl = tmp_path / "RocketLauncher"
    for system in ("Gun Games", "Gun Games 2"):
        _write(rl / "Settings" / system / "Emulators.ini", "[ROMS]\nDefault_Emulator=MAME\n")
    uf = rl / "Lib" / "User Functions"
    _write(uf / "Emulators" / "MAME.ahk", _ahk(SINDEN_RUN))
    for game in range(20):
        _write(uf / "Gun Games" / f"game{game}.ahk", _ahk("; nothing"))
    cfg = Config(roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
                 rocketlauncher_dir=str(rl))

    reads, statted = [], []
    real_read, real_path_stat, real_os_stat = lightgun._read_ahk, Path.stat, os.stat

    def counting_read(path):
        reads.append(path.name)
        return real_read(path)

    def recording_path_stat(self, *args, **kwargs):
        statted.append(str(self))
        return real_path_stat(self, *args, **kwargs)

    def recording_os_stat(path, *args, **kwargs):
        statted.append(str(path))
        return real_os_stat(path, *args, **kwargs)

    monkeypatch.setattr(lightgun, "_read_ahk", counting_read)
    monkeypatch.setattr(Path, "stat", recording_path_stat)
    monkeypatch.setattr(os, "stat", recording_os_stat)
    wiring = lightgun.detect_lightgun_wiring(cfg)

    assert list(wiring) == ["Gun Games", "Gun Games 2"]
    assert reads.count("MAME.ahk") == 1  # shared by both systems, read once
    assert not [p for p in statted if p.startswith(str(uf))]


# ─── detect ──────────────────────────────────────────────────────────────────

def test_detect_lists_systems_wired_via_user_functions(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    rl = Path(cfg.rocketlauncher_dir)
    _write(rl / "Settings" / "MAME.ini",
           "[Settings]\nPre_Launch_App=C:\\T\\DemulShooter.exe -target=mame\n")
    _write(rl / "Settings" / "Driving Games.ini", "[Settings]\nDefault_Emulator=MAME\n")
    _write(rl / "Settings" / "American Laser Games.ini", "[Settings]\n")
    _write(uf / "Emulators" / "MAME (Gun Games).ahk", _ahk(SINDEN_RUN))
    _write(uf / "Driving Games.ahk", _ahk("Run, JoyToKey.exe", "; " + SINDEN_RUN))
    _write(uf / "American Laser Games.ahk", _ahk(SINDEN_RUN))

    assert detect_lightgun_systems(cfg) == ["American Laser Games", "Gun Games", "MAME"]
    wiring = lightgun.detect_lightgun_wiring(cfg)
    assert wiring["MAME"] == "Pre_Launch_App"
    assert wiring["Gun Games"] == f"User Functions: {UF}\\Emulators\\MAME (Gun Games).ahk"
    assert wiring["American Laser Games"] == f"User Functions: {UF}\\American Laser Games.ahk"


def test_detect_cli_names_the_user_functions_file(tmp_path, config_home):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(SINDEN_RUN))
    save_config(cfg)
    result = CliRunner().invoke(cli, ["lightgun", "detect"])
    assert result.exit_code == 0, result.output
    out = " ".join(unstyle(result.output).split())
    assert f"Gun Games (User Functions: {UF}\\Gun Games.ahk)" in out


def test_audit_cli_reports_user_functions_wiring(tmp_path, config_home):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Emulators" / "MAME (Gun Games).ahk", _ahk(SINDEN_RUN))
    cfg.set_lightgun("Gun Games", True)
    save_config(cfg)
    result = CliRunner().invoke(cli, ["lightgun", "audit"])
    assert result.exit_code == 0, result.output
    # No hook is wired, so "wired" can only be the User Functions column.
    assert "wired" in result.output


# ─── doctor ──────────────────────────────────────────────────────────────────

def test_doctor_passes_a_system_wired_via_user_functions(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Emulators" / "MAME (Gun Games).ahk", _ahk(SINDEN_RUN))
    _write(uf / "Gun Games" / "vcop.ahk", _ahk(DEMUL_RUN))
    cfg.set_lightgun("Gun Games", True)
    result = health.check_lightguns(cfg)
    assert result.status == health.Status.OK
    node = _node(result, "Gun Games")
    assert node.status == health.Status.OK
    assert node.detail == (f"wired via User Functions ({UF}\\Emulators\\MAME (Gun Games).ahk, "
                           f"{UF}\\Gun Games\\vcop.ahk)")


def test_doctor_is_info_when_only_some_games_are_wired(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games" / "vcop.ahk", _ahk(DEMUL_RUN))
    _write(uf / "Gun Games" / "hotd.ahk", _ahk(DEMUL_RUN))
    cfg.set_lightgun("Gun Games", True)
    result = health.check_lightguns(cfg)
    node = _node(result, "Gun Games")
    assert node.status == health.Status.INFO
    assert "2 games only" in node.detail
    assert result.status != health.Status.FAIL


def test_doctor_still_fails_when_the_run_lines_are_commented_out(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk("; " + SINDEN_RUN))
    cfg.set_lightgun("Gun Games", True)
    node = _node(health.check_lightguns(cfg), "Gun Games")
    assert node.status == health.Status.FAIL
    assert "no gun" in node.detail


def test_doctor_lists_user_functions_once_for_every_system(tmp_path, monkeypatch):
    cfg, uf = _cabinet(tmp_path)
    for system in ("Gun Games 2", "Gun Games 3"):
        _write(Path(cfg.rocketlauncher_dir) / "Settings" / system / "Emulators.ini",
               "[ROMS]\nDefault_Emulator=MAME (Gun Games)\n")
    _write(uf / "Emulators" / "MAME (Gun Games).ahk", _ahk(SINDEN_RUN))
    for system in ("Gun Games", "Gun Games 2", "Gun Games 3"):
        cfg.set_lightgun(system, True)
    calls = []
    real_index = lightgun.index_user_functions

    def counting_index(rl_dir):
        calls.append(rl_dir)
        return real_index(rl_dir)

    monkeypatch.setattr(lightgun, "index_user_functions", counting_index)
    assert health.check_lightguns(cfg).status == health.Status.OK
    assert len(calls) == 1


def test_doctor_notes_demulshooter_started_by_both(tmp_path):
    rl = tmp_path / "RocketLauncher"
    _write(rl / "Settings" / "Sega Model 2.ini",
           "[Settings]\nDefault_Emulator=Model 2\n"
           "Pre_Launch_App=C:\\T\\DemulShooter.exe -target=model2\n"
           'Post_Launch_App=taskkill /IM "DemulShooter.exe" /F\n')
    _write(rl / "Lib" / "User Functions" / "Sega Model 2" / "vcop.ahk", _ahk(DEMUL_RUN))
    cfg = Config(roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
                 rocketlauncher_dir=str(rl))
    cfg.set_lightgun("Sega Model 2", True)
    result = health.check_lightguns(cfg)
    node = _node(result, "Sega Model 2")
    assert _node(node, "user functions").status == health.Status.INFO
    assert "run twice" in _node(node, "user functions").detail
    assert result.status in (health.Status.OK, health.Status.INFO)


# ─── Pre_Launch_App / Post_Launch_App ────────────────────────────────────────

@pytest.mark.parametrize("hooks, expected", [
    ("Pre_Launch_App=\nPost_Launch_App=taskkill /IM DemulShooter.exe /F\n", None),
    ("Pre_Launch_App=\n; Pre_Launch_App=C:\\T\\DemulShooter.exe -target=mame\n", None),
    ("Pre_Launch_App = C:\\T\\DemulShooter.exe -target=mame  \nPost_Launch_App=\n",
     "C:\\T\\DemulShooter.exe -target=mame"),
])
def test_an_empty_pre_launch_app_does_not_take_the_next_line(tmp_path, hooks, expected):
    """The value is read from the key's own line: an empty Pre_Launch_App
    followed by a line naming DemulShooter isn't wired."""
    rl = tmp_path / "RocketLauncher"
    _write(rl / "Settings" / "MAME.ini", "[Settings]\n" + hooks)
    cfg = Config(roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
                 rocketlauncher_dir=str(rl))
    status = audit_system_wiring("MAME", cfg)
    assert status.pre_launch == expected
    assert status.is_wired == (expected is not None)
    assert detect_lightgun_systems(cfg) == ([] if expected is None else ["MAME"])
    if expected is not None:
        assert status.target == "mame"


@pytest.mark.parametrize("post, expected", [
    ("Post_Launch_App=C:\\Tools\\restore-resolution.exe", None),
    ("Post_Launch_App=\n; was: taskkill /IM DemulShooter.exe /F", None),
    ('Post_Launch_App=taskkill /IM "DemulShooter.exe" /F', 'taskkill /IM "DemulShooter.exe" /F'),
])
def test_only_a_demulshooter_post_launch_app_is_its_teardown(tmp_path, post, expected):
    rl = tmp_path / "RocketLauncher"
    _write(rl / "Settings" / "MAME.ini",
           f"[Settings]\nPre_Launch_App=C:\\T\\DemulShooter.exe -target=mame\n{post}\n")
    cfg = Config(roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
                 rocketlauncher_dir=str(rl))
    assert audit_system_wiring("MAME", cfg).post_launch == expected
    cfg.set_lightgun("MAME", True)
    teardown = [c for c in _node(health.check_lightguns(cfg), "MAME").children
                if c.name == "teardown"]
    assert bool(teardown) == (expected is None)


# ─── configure ───────────────────────────────────────────────────────────────

def _install(tmp_path):
    install = LightgunInstall(demulshooter_exe=tmp_path / "tools" / "DemulShooter.exe")
    _write(install.demulshooter_exe)
    return install


def test_configure_warns_when_user_functions_already_start_demulshooter(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games" / "vcop.ahk", _ahk(DEMUL_RUN))
    plan = plan_wire_system("Gun Games", cfg, _install(tmp_path), target_override="model2")
    assert len(plan.warnings) == 1
    assert "already starts DemulShooter" in plan.warnings[0]
    assert f"{UF}\\Gun Games\\vcop.ahk" in plan.warnings[0]
    assert "second time" in plan.warnings[0]
    assert plan.pre_launch_command  # configure itself is unchanged


def test_configure_warns_when_user_functions_start_the_sinden_software(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(SINDEN_RUN))
    plan = plan_wire_system("Gun Games", cfg, _install(tmp_path), target_override="mame")
    assert len(plan.warnings) == 1
    assert "already starts the gun software" in plan.warnings[0]


def test_configure_has_no_warning_without_user_functions(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk("; " + SINDEN_RUN))
    plan = plan_wire_system("Gun Games", cfg, _install(tmp_path), target_override="mame")
    assert plan.warnings == []


def test_configure_cli_prints_the_warning_and_stays_a_dry_run(tmp_path, config_home):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(SINDEN_RUN))
    _write(Path(cfg.rocketlauncher_dir) / "Modules" / "DemulShooter" / "DemulShooter.exe")
    save_config(cfg)
    ini = Path(cfg.rocketlauncher_dir) / "Settings" / "Gun Games" / "Emulators.ini"
    before = ini.read_text(encoding="utf-8")
    result = CliRunner().invoke(cli, ["lightgun", "configure", "--system", "Gun Games",
                                      "--target", "mame"])
    assert result.exit_code == 0, result.output
    out = " ".join(unstyle(result.output).split())
    assert "Warning:" in out
    assert f"User Functions ({UF}\\Gun Games.ahk)" in out
    assert ini.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("line", [
    'Run, taskkill /IM "DemulShooter.exe" /F',
    'RunWait, %comspec% /c taskkill /IM "DemulShooterX64.exe" /F,, Hide',
    'Run, notepad.exe D:\\Tools\\Lightgun.exe',
    'Run, helper.bat, D:\\Tools\\Lightgun.exe',
    'Run, D:\\Tools\\Lightgun.exe.config',
    'Run, D:\\Tools\\not-Lightgun.exe',
    'Run, C:\\Windows\\System32\\taskkill.exe /IM D:\\Tools\\DemulShooter.exe /F',
    'Run, C:\\Windows\\notepad.exe D:\\Tools\\Lightgun.exe',
    'Run, D:\\Tools\\helper.bat D:\\Tools\\Lightgun.exe',
])
def test_run_must_launch_the_gun_not_merely_name_it(tmp_path, line):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(line))
    assert not audit_system_wiring("Gun Games", cfg).wired_via_user_functions
    assert detect_lightgun_systems(cfg) == []
    cfg.set_lightgun("Gun Games", True)
    assert _node(health.check_lightguns(cfg), "Gun Games").status == health.Status.FAIL
    plan = plan_wire_system("Gun Games", cfg, _install(tmp_path), target_override="mame")
    assert plan.warnings == []


@pytest.mark.parametrize("wired_emulators, expected", [
    (("PCSX2 (Gun Games)",), health.Status.INFO),
    (("MAME (Gun Games)",), health.Status.INFO),
    (("MAME (Gun Games)", "PCSX2 (Gun Games)"), health.Status.OK),
])
def test_emulator_wiring_must_cover_default_and_game_overrides(
        tmp_path, wired_emulators, expected):
    cfg, uf = _cabinet(tmp_path, games_ini="[Time Crisis]\nEmulator=PCSX2 (Gun Games)\n")
    for emu in wired_emulators:
        _write(uf / "Emulators" / f"{emu}.ahk", _ahk(SINDEN_RUN))
    cfg.set_lightgun("Gun Games", True)
    node = _node(health.check_lightguns(cfg), "Gun Games")
    assert node.status == expected
    if expected == health.Status.INFO:
        assert "other games may run with no gun" in node.detail
    assert detect_lightgun_systems(cfg) == ["Gun Games"]


def test_empty_post_launch_does_not_warn_about_replacing_the_next_key(tmp_path):
    cfg, _uf = _cabinet(tmp_path)
    ini = Path(cfg.rocketlauncher_dir) / "Settings" / "Gun Games" / "Emulators.ini"
    _write(ini, "[ROMS]\nPost_Launch_App=\nRom_Path=D:\\Games\n")
    plan = plan_wire_system("Gun Games", cfg, _install(tmp_path), target_override="mame")
    assert not plan.replace_post
    assert plan.notes == []


@pytest.mark.parametrize("line", [
    'Run, "C:\\Program Files\\Sinden\\Lightgun.exe", C:\\Program Files\\Sinden',
    'Run, C:\\Program Files\\DemulShooter\\DemulShooterX64.exe -target=model2',
    'Run, *RunAs "D:\\Tools\\DemulShooter.exe" -target=model2',
    'Run, % "D:\\Tools\\Lightgun.exe"',
    'Run, %comspec% /c start "" "D:\\Tools\\Lightgun.exe"',
])
def test_launch_target_matching_preserves_common_ahk_forms(tmp_path, line):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(line))
    assert audit_system_wiring("Gun Games", cfg).wired_via_user_functions


def test_system_file_covers_unwired_emulator_overrides(tmp_path):
    cfg, uf = _cabinet(tmp_path, games_ini="[Time Crisis]\nEmulator=PCSX2\n")
    _write(uf / "Gun Games.ahk", _ahk(SINDEN_RUN))
    cfg.set_lightgun("Gun Games", True)
    assert _node(health.check_lightguns(cfg), "Gun Games").status == health.Status.OK


def test_audit_cli_labels_emulator_only_coverage_partial(tmp_path, config_home):
    cfg, uf = _cabinet(tmp_path, games_ini="[Time Crisis]\nEmulator=PCSX2\n")
    _write(uf / "Emulators" / "PCSX2.ahk", _ahk(SINDEN_RUN))
    cfg.set_lightgun("Gun Games", True)
    save_config(cfg)
    result = CliRunner().invoke(cli, ["lightgun", "audit"])
    assert result.exit_code == 0, result.output
    assert "partial" in result.output


def test_empty_game_emulator_inherits_wired_default(tmp_path):
    cfg, uf = _cabinet(tmp_path, games_ini="[vcop]\nEmulator=\n")
    _write(uf / "Emulators" / "MAME (Gun Games).ahk", _ahk(SINDEN_RUN))
    cfg.set_lightgun("Gun Games", True)
    assert _node(health.check_lightguns(cfg), "Gun Games").status == health.Status.OK
