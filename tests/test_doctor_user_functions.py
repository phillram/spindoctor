"""Tests for the `doctor` User Functions check.

RocketLauncher runs AHK "User Functions" files around every launch.  Two
mistakes there only show when someone plays: a ``Run`` line naming a program
that isn't there (AutoHotkey stops the launch with an error), and a key
mapper (JoyToKey, Xpadder, antimicro) left running in HyperSpin after the
game, where it doubles pad presses that DS4Windows Auto Profiles also map.
Each test builds a small cabinet in a temp dir.
"""
from __future__ import annotations

import os

import pytest

from spindoctor import health
from spindoctor.config import Config
from spindoctor.lightgun import index_user_functions
from spindoctor.rl_user_functions import (
    MAPPER_AT_EXIT,
    MAPPER_LEFT_RUNNING,
    MISSING,
    code_lines,
    parse_run,
    program_exists,
    scan_user_functions,
)

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO
UF = "Lib\\User Functions"


def _write(path, text="", encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def _ahk(init=(), exit_=(), stop=()):
    """A User Functions file: *init* lines in InitUserFeatures(), *stop* in
    StopUserFeatures() and *exit_* in PostExit(), as RocketLauncher's template."""
    def body(lines):
        return "".join(f"\t\t{line}\n" for line in lines)
    return (
        "; Code in this file will only be run for the system whose name matches\n"
        "class SystemUserFunction extends UserFunction {\n"
        "\tInitUserFeatures() {\n"
        '\t\tRLLog.Info(A_ThisFunc . " - Starting")\n'
        f"{body(init)}"
        "\t}\n"
        "\tStopUserFeatures() {\n"
        f"{body(stop)}"
        "\t}\n"
        "\tPostExit() {\n"
        f"{body(exit_)}"
        "\t}\n"
        "}\n"
    )


def _cabinet(tmp_path, wheels=None, hidden=(), emulators=None):
    """HyperSpin + RocketLauncher dirs.  *wheels* maps wheel name -> DB game
    names; *emulators* maps wheel name -> its Default_Emulator."""
    wheels = {"Driving Games": ["outrun", "daytona"]} if wheels is None else wheels
    emulators = emulators or {}
    hs = tmp_path / "HyperSpin"
    rl = tmp_path / "RocketLauncher"
    (rl / "Lib" / "User Functions").mkdir(parents=True)
    menu = "".join(
        f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
        for w in wheels
    )
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, games in wheels.items():
        xml = "".join(f'<game name="{g}"/>' for g in games)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
        _write(rl / "Settings" / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator={emulators.get(wheel, 'MAME')}\nRom_Path=E:\\Games\n")
    cfg = Config(roms_dir=str(tmp_path / "Games"), hyperspin_dir=str(hs),
                 rocketlauncher_dir=str(rl))
    return cfg, rl / "Lib" / "User Functions"


def _tool(tmp_path, name="JoyToKey.exe"):
    """A real program file; returns its full path."""
    return str(_write(tmp_path / "Tools" / name.replace(".exe", "") / name))


def _scan(uf, emulator_systems=None):
    return scan_user_functions(index_user_functions(uf.parent.parent), emulator_systems)


def _kinds(findings, key):
    return [f.kind for f in findings.get(key, [])]


# --- reading Run lines --------------------------------------------------------

@pytest.mark.parametrize("code, expected", [
    ("Run, D:\\Arcade\\Utilities\\JoyToKey (Driving MAME)\\JoyToKey.exe Hyperspin",
     ("D:\\Arcade\\Utilities\\JoyToKey (Driving MAME)\\JoyToKey.exe", "Hyperspin", "")),
    ('Run, D:\\Tools\\JoyToKey.exe "Wacky Races"',
     ("D:\\Tools\\JoyToKey.exe", '"Wacky Races"', "")),
    ("run, JoyToKey.exe, D:\\Arcade\\Utilities\\JoyToKey",
     ("JoyToKey.exe", "", "D:\\Arcade\\Utilities\\JoyToKey")),
    ('Run, "C:\\Program Files\\Logitech\\LCore.exe" /minimized',
     ("C:\\Program Files\\Logitech\\LCore.exe", "/minimized", "")),
    ('Run("D:\\Tools\\Xpadder.exe /m", "D:\\Tools")',
     ("D:\\Tools\\Xpadder.exe", "/m", "D:\\Tools")),
    ("RunWait, D:\\Tools\\fix.bat,, Hide", ("D:\\Tools\\fix.bat", "", "")),
])
def test_parse_run_reads_program_arguments_and_working_dir(code, expected):
    assert parse_run(code) == expected


@pytest.mark.parametrize("code", [
    "Run, % emuPath . \"\\JoyToKey.exe\"",
    "Run(joyToKeyPath)",
    "Run, https://example.com",
])
def test_parse_run_gives_no_program_for_expressions_and_urls(code):
    assert parse_run(code) == ("", "", "")


@pytest.mark.parametrize("code", [
    "Process, Close, JoyToKey.exe",
    "RunAsUser := true",
    "WinClose, JoyToKey ahk_class TMainForm",
])
def test_parse_run_ignores_lines_that_arent_run(code):
    assert parse_run(code) is None


def test_code_lines_track_methods_and_drop_comments():
    text = (
        "class GameUserFunction extends GameFunction {\n"
        "\tInitUserFeatures() {\n"
        "\t\tRun, D:\\A.exe ; starts A\n"
        "\t\t; Run, D:\\Commented.exe\n"
        "\t}\n"
        "\tPostExit()\n"
        "\t{\n"
        "\t\t/*\n"
        "\t\tRun, D:\\InBlock.exe\n"
        "\t\t*/\n"
        "\t\tif (x) {\n"
        "\t\t\tRun, D:\\B.exe\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )
    runs = [(n, m, c.strip()) for n, m, c in code_lines(text) if c.strip().lower().startswith("run")]
    assert runs == [(3, "inituserfeatures", "Run, D:\\A.exe"), (12, "postexit", "Run, D:\\B.exe")]


# --- does the program exist ----------------------------------------------------

def test_program_exists_for_full_paths(tmp_path):
    tool = _tool(tmp_path)
    assert program_exists(tool) is True
    assert program_exists(str(tmp_path / "Gone" / "JoyToKey.exe")) is False


def test_program_exists_resolves_a_name_against_the_working_dir(tmp_path):
    tool = _tool(tmp_path)
    folder = os.path.dirname(tool)
    assert program_exists("JoyToKey.exe", folder) is True
    assert program_exists("Xpadder.exe", folder) is False


@pytest.mark.parametrize("program, working_dir", [
    ("JoyToKey.exe", ""),                       # may be on PATH
    ("%A_ScriptDir%\\JoyToKey.exe", ""),        # only known at launch
    ("JoyToKey.exe", "%ToolsDir%"),
    ("", ""),
])
def test_program_exists_cant_tell(program, working_dir):
    assert program_exists(program, working_dir) is None


def test_windows_paths_are_only_checked_on_windows():
    expected = False if os.name == "nt" else None
    assert program_exists("Z:\\Nowhere\\SpinDoctorTest\\JoyToKey.exe") is expected


# --- scanning the files --------------------------------------------------------

def test_a_missing_program_is_found_with_its_line(tmp_path):
    _, uf = _cabinet(tmp_path)
    gone = str(tmp_path / "Gone" / "LCore.exe")
    _write(uf / "Driving Games.ahk", _ahk(init=[f"Run, {gone}"]))
    findings = _scan(uf)
    (f,) = findings["driving games.ahk"]
    assert f.kind == MISSING
    assert f.line == 5
    assert f.program == gone
    assert "isn't there" in f.text and "AutoHotkey" in f.text


def test_a_missing_program_next_to_its_working_dir_is_found(tmp_path):
    _, uf = _cabinet(tmp_path)
    gone_dir = str(tmp_path / "Utilities" / "JoyToKey")
    _write(uf / "Gun Games.ahk", _ahk(init=[f"run, JoyToKey.exe, {gone_dir}"]))
    (f,) = _scan(uf)["gun games.ahk"]
    assert f.kind == MISSING
    assert f.program == os.path.join(gone_dir, "JoyToKey.exe")


def test_commented_out_and_present_programs_are_fine(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path, "Lightgun.exe")
    gone = str(tmp_path / "Gone" / "JoyToKey.exe")
    _write(uf / "Gun Games.ahk", _ahk(init=[f"Run, {tool}", f"; Run, {gone}"]))
    assert _scan(uf) == {}


def test_a_mapper_started_as_the_game_ends_is_flagged(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Emulators" / "MAME.ahk",
           _ahk(init=["Process, Close, Xpadder.exe", f"Run, {tool} MAME"],
                exit_=["Process, Close, Xpadder.exe", f"Run, {tool} Hyperspin"]))
    findings = _scan(uf)
    (f,) = findings["emulators/mame.ahk"]  # one row: the start line isn't repeated
    assert f.kind == MAPPER_AT_EXIT
    assert 'starts JoyToKey as the game ends (profile "Hyperspin")' in f.text
    assert "keeps running in HyperSpin" in f.text
    assert "PostExit()" in f.fix and "DS4Windows" in f.fix


def test_stopuserfeatures_counts_as_the_game_ending(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path, "Xpadder.exe")
    _write(uf / "Driving Games.ahk", _ahk(stop=[f"Run, {tool}"]))
    assert _kinds(_scan(uf), "driving games.ahk") == [MAPPER_AT_EXIT]


def test_a_mapper_started_and_never_closed_is_flagged(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Gun Games.ahk",
           _ahk(init=[f"run, JoyToKey.exe, {os.path.dirname(tool)}"],
                stop=["Process, Close, Xpadder.exe"]))
    (f,) = _scan(uf)["gun games.ahk"]
    assert f.kind == MAPPER_LEFT_RUNNING
    assert "nothing closes it when the game ends" in f.text


@pytest.mark.parametrize("close", [
    "Process, Close, JoyToKey.exe",
    "WinClose, JoyToKey ahk_class TMainForm",
    "Run, taskkill /f /im JoyToKey.exe,, Hide",  # runs taskkill, not JoyToKey
    "Run, %comspec% /c taskkill /f /im JoyToKey.exe,, Hide",
    "for proc in ComObjGet(\"winmgmts:\").ExecQuery(\"Select * from Win32_Process where Name = 'JoyToKey.exe'\")",
])
def test_a_mapper_closed_in_postexit_is_fine(tmp_path, close):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(init=[f"Run, {tool}"], exit_=[close]))
    assert _scan(uf) == {}


def test_taskkill_naming_a_mapper_isnt_a_start():
    assert parse_run("Run, taskkill /f /im JoyToKey.exe,, Hide") == (
        "taskkill", "/f /im JoyToKey.exe", "")


def test_a_close_outside_an_exit_method_doesnt_count(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Gun Games.ahk", _ahk(init=["Process, Close, JoyToKey.exe", f"Run, {tool}"]))
    assert _kinds(_scan(uf), "gun games.ahk") == [MAPPER_LEFT_RUNNING]


def test_a_game_file_closed_by_its_system_file_or_global_is_fine(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Driving Games" / "outrun.ahk", _ahk(init=[f"Run, {tool} OutRun"]))
    _write(uf / "Driving Games.ahk", _ahk(exit_=["Process, Close, JoyToKey.exe"]))
    _write(uf / "Gun Games" / "hotd.ahk", _ahk(init=[f"Run, {tool} Guns"]))
    _write(uf / "Global.ahk", _ahk(exit_=["Process, Close, JoyToKey.exe"]))
    assert _scan(uf) == {}


def test_a_shared_emulator_file_needs_every_system_to_close_it(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Emulators" / "MAME.ahk", _ahk(init=[f"Run, {tool} MAME"]))
    _write(uf / "Driving Games.ahk", _ahk(exit_=["Process, Close, JoyToKey.exe"]))
    _write(uf / "Racing.ahk", _ahk())
    assert _kinds(_scan(uf, {"mame": {"driving games"}}), "emulators/mame.ahk") == []
    assert _kinds(_scan(uf, {"mame": {"driving games", "racing"}}),
                  "emulators/mame.ahk") == [MAPPER_LEFT_RUNNING]
    assert _kinds(_scan(uf), "emulators/mame.ahk") == [MAPPER_LEFT_RUNNING]


@pytest.mark.parametrize("exe, shown", [
    ("JoyToKey.exe", "JoyToKey"),
    ("Joy2Key.exe", "JoyToKey"),
    ("xpadder.exe", "Xpadder"),
    ("antimicro.exe", "antimicro"),
    ("antimicrox.exe", "antimicroX"),
])
def test_each_key_mapper_is_recognized(tmp_path, exe, shown):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path, exe)
    _write(uf / "Driving Games.ahk", _ahk(exit_=[f"Run, {tool} Hyperspin"]))
    (f,) = _scan(uf)["driving games.ahk"]
    assert f"starts {shown} as the game ends" in f.text


def test_other_programs_left_running_arent_flagged(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path, "Lightgun.exe")
    _write(uf / "Gun Games.ahk", _ahk(init=[f"Run, {tool}"]))
    assert _scan(uf) == {}


def test_a_missing_mapper_is_reported_as_missing_not_as_left_running(tmp_path):
    _, uf = _cabinet(tmp_path)
    gone = str(tmp_path / "Gone" / "JoyToKey.exe")
    _write(uf / "Driving Games.ahk", _ahk(init=[f"Run, {gone} MAME"], exit_=[f"Run, {gone} Hyperspin"]))
    assert _kinds(_scan(uf), "driving games.ahk") == [MISSING, MISSING]


def test_files_are_read_with_a_bom_or_as_utf16(tmp_path):
    _, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    _write(uf / "Driving Games.ahk", _ahk(exit_=[f"Run, {tool} Hyperspin"]), encoding="utf-8-sig")
    _write(uf / "Gun Games.ahk", _ahk(exit_=[f"Run, {tool} Hyperspin"]), encoding="utf-16")
    findings = _scan(uf)
    assert _kinds(findings, "driving games.ahk") == [MAPPER_AT_EXIT]
    assert _kinds(findings, "gun games.ahk") == [MAPPER_AT_EXIT]


# --- doctor --------------------------------------------------------------------

def _node(result, name):
    return next(c for c in result.children if c.name == name)


def test_doctor_is_ok_when_nothing_is_wrong(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    _write(uf / "Driving Games.ahk", _ahk(init=[f"Run, {_tool(tmp_path, 'Lightgun.exe')}"]))
    result = health.check_user_functions(cfg)
    assert result.status == OK
    assert result.children == []
    assert result.detail == "1 file: no missing programs, no key mapper left running"


def test_doctor_warns_for_a_visible_wheel(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    tool = _tool(tmp_path)
    gone = str(tmp_path / "Gone" / "LCore.exe")
    _write(uf / "Driving Games.ahk", _ahk(init=[f"Run, {gone}"], exit_=[f"Run, {tool} Hyperspin"]))
    result = health.check_user_functions(cfg)
    assert result.status == WARN
    assert result.detail == "1 of 1 files need a look"
    node = _node(result, f"{UF}\\Driving Games.ahk")
    assert node.status == WARN
    assert node.detail.startswith("line 5 runs ")
    assert "; line 10 starts JoyToKey as the game ends" in node.detail
    assert "correct the path on line 5" in node.fix and "PostExit()" in node.fix


def test_doctor_warns_for_global_and_for_an_emulator_a_visible_wheel_uses(tmp_path):
    cfg, uf = _cabinet(tmp_path, emulators={"Driving Games": "MAME (Driving Games)"})
    tool = _tool(tmp_path)
    _write(uf / "Global.ahk", _ahk(exit_=[f"Run, {tool} Hyperspin"]))
    _write(uf / "Emulators" / "MAME (Driving Games).ahk", _ahk(exit_=[f"Run, {tool} Hyperspin"]))
    result = health.check_user_functions(cfg)
    assert _node(result, f"{UF}\\Global.ahk").status == WARN
    assert _node(result, f"{UF}\\Emulators\\MAME (Driving Games).ahk").status == WARN


@pytest.mark.parametrize("path, suffix", [
    (("Gun Games.ahk",), "hidden on the Main Menu"),
    (("Gun Games.old.ahk",), "not on the Main Menu"),
    (("Driving Games", "OutRun 2 SP SDX.ahk"), "not on the Driving Games wheel"),
    (("Emulators", "Dolphin Triforce.ahk"), "no wheel on the Main Menu uses this emulator"),
    (("Emulators", "MAME (Gun Games).ahk"), "only hidden wheels use this emulator"),
])
def test_doctor_lists_files_no_player_can_reach_as_info(tmp_path, path, suffix):
    cfg, uf = _cabinet(tmp_path, wheels={"Driving Games": ["outrun"], "Gun Games": ["area51"]},
                       hidden=("Gun Games",), emulators={"Gun Games": "MAME (Gun Games)"})
    gone = str(tmp_path / "Gone" / "JoyToKey.exe")
    _write(uf.joinpath(*path), _ahk(init=[f"Run, {gone}"]))
    result = health.check_user_functions(cfg)
    label = "\\".join((UF,) + path)
    node = _node(result, f"{label} ({suffix})")
    assert node.status == INFO
    assert result.status == INFO  # can't fail or warn doctor
    assert result.detail.endswith("all on wheels, games or emulators players can't reach")


def test_doctor_game_file_on_its_wheel_warns(tmp_path):
    cfg, uf = _cabinet(tmp_path)
    gone = str(tmp_path / "Gone" / "JoyToKey.exe")
    _write(uf / "Driving Games" / "OutRun.ahk", _ahk(init=[f"Run, {gone}"]))
    node = _node(health.check_user_functions(cfg), f"{UF}\\Driving Games\\OutRun.ahk")
    assert node.status == WARN


def test_doctor_without_rocketlauncher_or_files(tmp_path):
    cfg = Config(roms_dir=str(tmp_path / "Games"), hyperspin_dir=str(tmp_path / "hs"))
    assert health.check_user_functions(cfg).status == INFO
    cfg, _ = _cabinet(tmp_path)
    result = health.check_user_functions(cfg)
    assert (result.status, result.detail) == (OK, "no User Functions files")
