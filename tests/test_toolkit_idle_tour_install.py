"""Installing the idle tour: HyperSpin's Startup Script, install-tools and doctor.

`install-tools --tool idle-tour --apply` writes ``Idle Tour.bat`` and its
settings file and adds the ``.bat`` to the ``[Startup]`` list of HyperSpin's
Startup Script, found from HyperSpin's own ``[Startup Program]`` setting;
`uninstall-tools` takes it out again, numbering the later entries down; the
``doctor`` "Idle tour" check reads it all.  Every cabinet is built under
tmp_path.
"""
from __future__ import annotations

import re

import pytest
from click import unstyle
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import health
from spindoctor import idle_tour as it
from spindoctor import startup_script as ss
from spindoctor import toolkit_helpers as th
from spindoctor.cli import cli
from spindoctor.config import Config
from spindoctor.health import Status
from spindoctor.idle_tour import DEFAULT_SETTINGS_TEXT, SETTINGS_FILE


def _script_text(hs):
    return (
        "[Required]\r\n"
        f"HyperSpin_Folder_Path={hs}\r\n"
        "[General]\r\n"
        "Primary_Color_RRGGBB=363636\r\n"
        "[Startup]\r\n"
        "Minimize_Background_Windows_Enabled=false\r\n"
        "Program_To_Run_Target_1=HyperSearch.exe\r\n"
        f"Program_To_Run_Working_Dir_1={hs}\\Utilities\\HyperSearch\r\n"
        "Program_To_Run_MaxMinHide_1=Hide\r\n"
        "Program_To_Run_Target_2=Wake ROM Drives.ahk\r\n"
        f"Program_To_Run_Working_Dir_2={hs}\\Utilities\r\n"
        "Program_To_Run_MaxMinHide_2=Hide\r\n"
        "Process_Name_To_Close_1=\r\n"
        "[Exit]\r\n"
        "Restore_Windows_On_Exit=False\r\n"
        "Process_Name_To_Close_1=HyperSearch.exe\r\n"
        "Program_To_Run_Target_1=ExitScript.bat\r\n"
        f"Program_To_Run_Working_Dir_1={hs}\r\n"
        "Program_To_Run_MaxMinHide_1=Hide\r\n"
        "[Roulette]\r\n"
        "Roulette_Key=\r\n"
    )


TOUR_LINES = (
    "Program_To_Run_Target_3=Idle Tour.bat\r\n"
    "Program_To_Run_Working_Dir_3={out}\r\n"
    "Program_To_Run_MaxMinHide_3=Hide\r\n"
)


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    hs = tmp_path / "hyperspin"
    rl = tmp_path / "rocketlauncher"
    script_dir = hs / "Utilities" / "Startup and Exit"
    for d in (tmp_path / "roms", hs / "Settings", hs / "Databases", script_dir, rl / "Settings"):
        d.mkdir(parents=True)
    (hs / "Settings" / "Settings.ini").write_bytes(
        b"[Main]\r\nExit_Default=yes\r\n[AttractMode]\r\nActive=true\r\nTime=300\r\n"
        b"[Startup Program]\r\nExecutable=HyperSpin Startup Script.exe\r\nParamaters=\r\n"
        + f"Working_Directory={script_dir}\\\r\n".encode("utf-8")
        + b"WinState=NORMAL\r\n[LEDBlinky]\r\nActive=true\r\n")
    (script_dir / "HyperSpin Startup Script.exe").write_bytes(b"MZ")
    ini = script_dir / "HyperSpin Startup Script.ini"
    ini.write_bytes(_script_text(hs).encode("utf-8"))
    config_mod.save_config(Config(
        roms_dir=str(tmp_path / "roms"), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl),
        emulators_dir=str(tmp_path / "emulators"),
    ))
    yield {"hs": hs, "rl": rl, "ini": ini, "script_dir": script_dir,
           "settings": hs / "Settings" / "Settings.ini",
           "menu": rl / "Modules" / "HyperLaunch" / "Tools" / "spindoctor"}
    config_mod.reset_override_cache()


def _run(*args):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


def _check():
    return health.check_idle_tour(config_mod.load_config())


def _rows(check):
    return {c.name: c for c in check.children}


# ── the helper ───────────────────────────────────────────────────────────────

def test_idle_tour_is_a_helper_that_starts_with_hyperspin():
    helper = th.find("idle-tour")
    assert helper.name == "Idle Tour" and helper.startup
    assert helper in th.STARTUP_HELPERS and helper not in th.WHEEL_HELPERS
    assert set(th.WHEEL_HELPERS) | set(th.STARTUP_HELPERS) == set(th.HELPERS)
    body = helper.body()
    assert 'toolkit idle-tour --settings "%~dp0Idle Tour settings.ini"\r\n' in body
    assert "start " not in body          # shares the hidden console it was started in
    assert body.count("\n") == body.count("\r\n")


# ── finding the Startup Script ───────────────────────────────────────────────

def test_finds_the_script_hyperspin_starts(cabinet):
    found = ss.find(cabinet["hs"])
    assert found.path == cabinet["ini"] and found.program == "HyperSpin Startup Script.exe"
    assert found.problem == ""


def test_a_relative_working_directory_is_hyperspins_folder(cabinet):
    cabinet["settings"].write_text(
        "[Startup Program]\nExecutable=HyperSpin Startup Script.exe\n"
        "Working_Directory=Utilities\\Startup and Exit\n".replace("\\", "/"), encoding="utf-8")
    assert ss.find(cabinet["hs"]).path == cabinet["ini"]


@pytest.mark.parametrize("settings, problem", [
    ("[Startup Program]\nExecutable=\n", "has no Startup Program"),
    ("[Startup Program]\nExecutable=Other.exe\nWorking_Directory={dir}\n", "doesn't exist"),
])
def test_says_why_no_script_was_found(cabinet, settings, problem):
    cabinet["settings"].write_text(settings.format(dir=cabinet["script_dir"]), encoding="utf-8")
    found = ss.find(cabinet["hs"])
    assert found.path is None and problem in found.problem
    assert "not set" in ss.find("").problem


def test_a_startup_program_that_isnt_the_script_is_left_alone(cabinet):
    cabinet["ini"].write_text("[Settings]\nFoo=1\n", encoding="utf-8")
    found = ss.find(cabinet["hs"])
    assert found.path is None and "isn't the HyperSpin Startup Script" in found.problem


# ── reading and editing [Startup] ────────────────────────────────────────────

def test_entries_stop_at_the_first_missing_or_blank_number(cabinet):
    text = _script_text(cabinet["hs"])
    items = ss.entries(text)
    assert [(e.number, e.target) for e in items] == [(1, "HyperSearch.exe"), (2, "Wake ROM Drives.ahk")]
    assert ss.runs_to(items) == 2
    gap = text.replace("_2=", "_4=")
    assert ss.runs_to(ss.entries(gap)) == 1
    blank = text.replace("Target_2=Wake ROM Drives.ahk", "Target_2=")
    assert ss.runs_to(ss.entries(blank)) == 1


def test_add_puts_the_entry_after_the_last_one_and_keeps_every_other_byte(cabinet):
    text = _script_text(cabinet["hs"])
    new, number, action = ss.add(text, "Idle Tour.bat", r"D:\Tools")
    assert (number, action) == (3, "added")
    marker = "Program_To_Run_MaxMinHide_2=Hide\r\n"
    assert new == text.replace(marker, marker + TOUR_LINES.format(out=r"D:\Tools"))
    # [Exit]'s own Program_To_Run_*_1 keys are another list: untouched.
    assert new.split("[Exit]")[1] == text.split("[Exit]")[1]
    assert ss.add(new, "idle tour.BAT", r"D:\Tools") == (new, 3, "unchanged")


def test_add_again_with_another_folder_updates_the_entry_in_place(cabinet):
    first, _, _ = ss.add(_script_text(cabinet["hs"]), "Idle Tour.bat", r"D:\Old")
    new, number, action = ss.add(first, "Idle Tour.bat", r"D:\New")
    assert (number, action) == (3, "updated")
    assert new == first.replace(r"Working_Dir_3=D:\Old", r"Working_Dir_3=D:\New")


def test_add_fills_a_blank_entry_in_place(cabinet):
    text = _script_text(cabinet["hs"]).replace(
        "Process_Name_To_Close_1=\r\n", "Program_To_Run_Target_3=\r\nProcess_Name_To_Close_1=\r\n")
    new, number, _ = ss.add(text, "Idle Tour.bat", r"D:\Tools")
    assert number == 3 and "Program_To_Run_Target_3=Idle Tour.bat\r\nProgram_To_Run_Working_Dir_3" in new
    assert new.count("Program_To_Run_Target_3=") == 1


def test_add_refuses_when_entries_sit_after_a_gap(cabinet):
    text = _script_text(cabinet["hs"]).replace("_2=", "_4=")
    with pytest.raises(ss.StartupScriptError, match="after a gap at 2"):
        ss.add(text, "Idle Tour.bat", r"D:\Tools")
    mine_after_gap = _script_text(cabinet["hs"]).replace("Wake ROM Drives.ahk", "Idle Tour.bat") \
        .replace("_2=", "_5=")
    with pytest.raises(ss.StartupScriptError, match="never starts"):
        ss.add(mine_after_gap, "Idle Tour.bat", r"D:\Tools")


def test_add_to_an_empty_startup_section(cabinet):
    text = "[Required]\nHyperSpin_Folder_Path=X\n[Startup]\nMinimize_Background_Windows_Enabled=false\n\n[Exit]\n"
    new, number, _ = ss.add(text, "Idle Tour.bat", "D:/Tools")
    assert number == 1
    assert new == text.replace("=false\n", "=false\nProgram_To_Run_Target_1=Idle Tour.bat\n"
                                           "Program_To_Run_Working_Dir_1=D:/Tools\n"
                                           "Program_To_Run_MaxMinHide_1=Hide\n")
    with pytest.raises(ss.StartupScriptError):
        ss.add("[Exit]\n", "Idle Tour.bat", "D:/Tools")


def test_remove_numbers_the_later_entries_down(cabinet):
    text, _, _ = ss.add(_script_text(cabinet["hs"]), "Idle Tour.bat", r"D:\Tools")
    text, _, _ = ss.add(text, "CabVol.exe", r"D:\Vol")
    new, removed = ss.remove(text, "Idle Tour.bat")
    assert removed == [3]
    assert [(e.number, e.target) for e in ss.entries(new)] == [
        (1, "HyperSearch.exe"), (2, "Wake ROM Drives.ahk"), (3, "CabVol.exe")]
    assert "Program_To_Run_Working_Dir_3=D:\\Vol\r\n" in new
    assert new.split("[Exit]")[1] == text.split("[Exit]")[1]
    assert ss.remove(new, "Idle Tour.bat") == (new, [])


def test_written_file_keeps_its_bom_and_line_ends(cabinet, tmp_path):
    path = tmp_path / "s.ini"
    path.write_bytes(b"\xef\xbb\xbf" + _script_text(cabinet["hs"]).encode("utf-8"))
    from spindoctor._text import read_editable_text

    new, _, _ = ss.add(read_editable_text(path), "Idle Tour.bat", r"D:\Tools")
    ss.write(path, new)
    data = path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf[Required]") and b"\r\r" not in data
    assert data.count(b"\n") == data.count(b"\r\n")


def test_backup_is_a_sidecar_beside_the_file_or_in_backup_dir(cabinet, tmp_path):
    ini = cabinet["ini"]
    beside = ss.backup(ini, Config())
    assert beside.parent == ini.parent and beside.name.startswith("HyperSpin Startup Script.")
    assert beside.suffix == ".bak" and beside.read_bytes() == ini.read_bytes()
    elsewhere = ss.backup(ini, Config(backup_dir=str(tmp_path / "bk")))
    assert elsewhere.parent == tmp_path / "bk" / "HyperSpin"
    assert ss.backup(ini, Config(backup_before_modify=False)) is None


# ── install-tools / uninstall-tools ──────────────────────────────────────────

def test_install_without_apply_writes_the_helper_and_previews_the_entry(cabinet):
    before = cabinet["ini"].read_bytes()
    result = _run("install-tools", "--tool", "idle-tour")
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in cabinet["menu"].iterdir()) == ["Idle Tour settings.ini", "Idle Tour.bat"]
    assert (cabinet["menu"] / SETTINGS_FILE).read_bytes() == DEFAULT_SETTINGS_TEXT.encode("utf-8")
    assert cabinet["ini"].read_bytes() == before
    assert "[DRY RUN]" in result.output and "Would add [Startup] entry 3" in result.output
    assert "HyperHQ" not in result.output       # not a Tools-menu helper


def test_install_with_apply_adds_the_entry_after_a_backup(cabinet):
    before = cabinet["ini"].read_bytes()
    result = _run("install-tools", "--tool", "idle-tour", "--apply")
    assert result.exit_code == 0, result.output
    assert cabinet["ini"].read_bytes() == before.replace(
        b"Program_To_Run_MaxMinHide_2=Hide\r\n",
        b"Program_To_Run_MaxMinHide_2=Hide\r\n"
        + TOUR_LINES.format(out=cabinet["menu"].resolve()).encode("utf-8"))
    backups = list(cabinet["script_dir"].glob("HyperSpin Startup Script.*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    output = unstyle(result.output)
    assert "added [Startup] entry 3" in output and "no [Exit]" in output
    again = _run("install-tools", "--tool", "idle-tour", "--apply")
    assert again.exit_code == 0 and "already starts Idle Tour.bat ([Startup] entry 3)" in again.output
    assert len(list(cabinet["script_dir"].glob("*.bak"))) == 1


def test_install_keeps_settings_edited_since(cabinet):
    assert _run("install-tools", "--tool", "idle-tour").exit_code == 0
    settings = cabinet["menu"] / SETTINGS_FILE
    settings.write_text("[IdleTour]\nGamesPerConsole=9\n", encoding="utf-8")
    result = _run("install-tools", "--tool", "idle-tour")
    assert "kept the settings already there" in result.output
    assert settings.read_text(encoding="utf-8") == "[IdleTour]\nGamesPerConsole=9\n"


def test_idle_tour_is_never_a_wheel_entry(cabinet):
    (cabinet["hs"] / "Databases" / "Toolkit").mkdir()
    (cabinet["hs"] / "Databases" / "Toolkit" / "Toolkit.xml").write_text("<menu></menu>", encoding="utf-8")
    result = _run("install-tools", "--tool", "refresh-all,idle-tour", "--add-to-system", "Toolkit", "--apply")
    assert result.exit_code == 2 and "can't be a wheel entry" in result.output
    assert not (cabinet["rl"] / "Modules").exists()
    assert (cabinet["hs"] / "Databases" / "Toolkit" / "Toolkit.xml").read_text(encoding="utf-8") == "<menu></menu>"


def test_install_warns_when_hyperspins_idle_mode_or_ledblinky_calls_are_off(cabinet):
    cabinet["settings"].write_bytes(cabinet["settings"].read_bytes()
                                    .replace(b"[AttractMode]\r\nActive=true", b"[AttractMode]\r\nActive=false")
                                    .replace(b"[LEDBlinky]\r\nActive=true", b"[LEDBlinky]\r\nActive=false"))
    result = _run("install-tools", "--tool", "idle-tour")
    assert result.exit_code == 0
    assert "[AttractMode] Active=false" in result.output and "[LEDBlinky] Active=false" in result.output


def test_install_without_a_startup_script_says_what_to_do(cabinet):
    cabinet["settings"].write_text("[Startup Program]\nExecutable=\n", encoding="utf-8")
    preview = _run("install-tools", "--tool", "idle-tour")
    assert preview.exit_code == 0 and "isn't started with HyperSpin yet" in preview.output
    result = _run("install-tools", "--tool", "idle-tour", "--apply")
    assert result.exit_code == 1      # asked to start it with HyperSpin, and couldn't
    assert "isn't started with HyperSpin yet" in result.output and "Idle Tour.bat" in result.output
    assert (cabinet["menu"] / "Idle Tour.bat").is_file()


def test_install_writes_an_absolute_folder_for_a_relative_output_dir(cabinet, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _run("install-tools", "--tool", "idle-tour", "--output-dir", "tools", "--apply").exit_code == 0
    entry = [e for e in ss.entries(cabinet["ini"].read_text(encoding="utf-8")) if e.number == 3][0]
    assert entry.working_dir == str((tmp_path / "tools").resolve())


def test_install_refuses_a_folder_the_startup_script_would_misread(cabinet, tmp_path):
    before = cabinet["ini"].read_bytes()
    result = _run("install-tools", "--tool", "idle-tour", "--output-dir", str(tmp_path / "Jeux Rétro"), "--apply")
    assert result.exit_code == 1 and "plain ASCII" in result.output
    assert cabinet["ini"].read_bytes() == before


def test_install_warns_about_another_idle_tour_and_single_mode(cabinet):
    cabinet["ini"].write_bytes(cabinet["ini"].read_bytes().replace(b"Wake ROM Drives.ahk", b"IdleTour.exe"))
    cabinet["settings"].write_bytes(cabinet["settings"].read_bytes().replace(
        b"[Main]\r\n", b"[Main]\r\nMenu_Mode=single\r\n"))
    result = _run("install-tools", "--tool", "idle-tour")
    assert result.exit_code == 0
    assert "also starts IdleTour.exe, another idle tour" in result.output
    assert "single mode" in result.output


def test_install_stops_at_a_gap_without_writing_the_script(cabinet):
    cabinet["ini"].write_bytes(cabinet["ini"].read_bytes().replace(b"_2=", b"_4="))
    before = cabinet["ini"].read_bytes()
    result = _run("install-tools", "--tool", "idle-tour", "--apply")
    assert result.exit_code == 1 and "after a gap" in result.output
    assert cabinet["ini"].read_bytes() == before


def test_uninstall_removes_the_helper_its_settings_and_its_entry(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    text = cabinet["ini"].read_bytes().replace(
        b"Process_Name_To_Close_1=\r\n[Exit]",
        b"Program_To_Run_Target_4=CabVol.exe\r\nProgram_To_Run_Working_Dir_4=X\r\n"
        b"Process_Name_To_Close_1=\r\n[Exit]")
    cabinet["ini"].write_bytes(text)
    preview = _run("uninstall-tools", "--tool", "idle-tour")
    assert preview.exit_code == 0 and "would remove [Startup] entry 3" in preview.output
    assert cabinet["ini"].read_bytes() == text and (cabinet["menu"] / "Idle Tour.bat").is_file()
    result = _run("uninstall-tools", "--tool", "idle-tour", "--apply")
    assert result.exit_code == 0, result.output
    assert list(cabinet["menu"].iterdir()) == []
    after = cabinet["ini"].read_bytes().decode("utf-8")
    assert [(e.number, e.target) for e in ss.entries(after)] == [
        (1, "HyperSearch.exe"), (2, "Wake ROM Drives.ahk"), (3, "CabVol.exe")]


def test_uninstall_of_every_helper_includes_the_idle_tour(cabinet):
    assert _run("install-tools", "--tool", "idle-tour,refresh-all", "--apply").exit_code == 0
    assert _run("uninstall-tools", "--apply").exit_code == 0
    assert list(cabinet["menu"].iterdir()) == []
    assert "Idle Tour" not in cabinet["ini"].read_text(encoding="utf-8")


# ── doctor ───────────────────────────────────────────────────────────────────

def test_doctor_not_installed_is_info(cabinet):
    chk = _check()
    assert chk.status == Status.INFO and chk.detail == "not installed (optional)"


def test_doctor_installed_is_ok(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    chk = _check()
    rows = _rows(chk)
    assert chk.status == Status.OK, [(c.name, c.status, c.detail) for c in chk.children]
    assert rows["Startup Script"].detail == \
        "starts it with HyperSpin ([Startup] entry 3 in HyperSpin Startup Script.ini)"
    assert rows["HyperSpin idle mode"].detail == "on, after 300 s with no input"
    assert "LEDBlinky calls" not in rows


def test_doctor_warns_when_idle_mode_or_ledblinky_calls_are_off(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    cabinet["settings"].write_bytes(cabinet["settings"].read_bytes()
                                    .replace(b"[AttractMode]\r\nActive=true", b"[AttractMode]\r\nActive=false")
                                    .replace(b"[LEDBlinky]\r\nActive=true", b""))
    chk = _check()
    rows = _rows(chk)
    assert chk.status == Status.WARN
    assert rows["HyperSpin idle mode"].status == Status.WARN and "Active=false" in rows["HyperSpin idle mode"].detail
    assert rows["LEDBlinky calls"].status == Status.WARN and "(not set)" in rows["LEDBlinky calls"].detail
    assert "[LEDBlinky] Active=true" in rows["LEDBlinky calls"].fix


def test_doctor_warns_when_the_helper_isnt_in_the_startup_script(cabinet):
    assert _run("install-tools", "--tool", "idle-tour").exit_code == 0     # no --apply
    row = _rows(_check())["Startup Script"]
    assert row.status == Status.WARN and "doesn't start Idle Tour.bat" in row.detail
    assert row.fix == "spindoctor install-tools --tool idle-tour --apply"


def test_doctor_warns_about_an_entry_after_a_gap(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    cabinet["ini"].write_bytes(cabinet["ini"].read_bytes().replace(b"_2=", b"_7="))
    row = _rows(_check())["Startup Script"]
    assert row.status == Status.WARN and "after a gap at 2" in row.detail and "never starts" in row.detail


def test_doctor_warns_when_the_entrys_bat_is_gone(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    (cabinet["menu"] / "Idle Tour.bat").unlink()
    row = _rows(_check())["Startup Script"]
    assert row.status == Status.WARN and "which doesn't exist" in row.detail
    assert row.fix == "spindoctor install-tools --tool idle-tour --apply"


def test_doctor_warns_when_the_bat_runs_a_spindoctor_thats_gone(cabinet, tmp_path):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    gone = tmp_path / "old" / "spindoctor.exe"
    (cabinet["menu"] / "Idle Tour.bat").write_text(
        f'"{gone}" --run-tool spindoctor toolkit idle-tour\r\n', encoding="utf-8")
    row = _rows(_check())["Startup Script"]
    assert row.status == Status.WARN and f"runs {gone}, which no longer exists" in row.detail
    assert row.fix == "spindoctor install-tools --tool idle-tour"


def test_doctor_reads_a_relative_working_dir_from_the_scripts_folder(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    tools = cabinet["script_dir"] / "tools"
    tools.mkdir()
    (cabinet["menu"] / "Idle Tour.bat").replace(tools / "Idle Tour.bat")
    text = cabinet["ini"].read_bytes()
    cabinet["ini"].write_bytes(re.sub(rb"Working_Dir_3=[^\r\n]*", b"Working_Dir_3=tools", text))
    assert _rows(_check())["Startup Script"].status == Status.OK


def test_doctor_warns_about_single_mode_and_another_tour(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    cabinet["ini"].write_bytes(cabinet["ini"].read_bytes().replace(b"Wake ROM Drives.ahk", b"IdleTour.exe"))
    cabinet["settings"].write_bytes(cabinet["settings"].read_bytes().replace(
        b"[Main]\r\n", b"[Main]\r\nMenu_Mode=single\r\n"))
    rows = _rows(_check())
    assert rows["HyperSpin menu mode"].status == Status.WARN
    assert rows["Another idle tour"].status == Status.WARN and "IdleTour.exe" in rows["Another idle tour"].detail


def test_doctor_notes_a_tour_switched_off(cabinet):
    assert _run("install-tools", "--tool", "idle-tour", "--apply").exit_code == 0
    (cabinet["menu"] / SETTINGS_FILE).write_text("[IdleTour]\nEnabled=0\n", encoding="utf-8")
    chk = _check()
    assert chk.status == Status.OK and _rows(chk)["Settings"].status == Status.INFO


def test_doctor_warns_when_nothing_starts_the_helper(cabinet):
    assert _run("install-tools", "--tool", "idle-tour").exit_code == 0
    cabinet["settings"].write_text("[AttractMode]\nActive=true\n[LEDBlinky]\nActive=true\n", encoding="utf-8")
    row = _rows(_check())["Startup Script"]
    assert row.status == Status.WARN and "nothing starts it" in row.detail


def test_doctor_runs_the_idle_tour_check(cabinet):
    names = [c.name for c in health.run_health_checks(config_mod.load_config()).checks]
    assert "Idle tour" in names and names.index("Idle tour") == names.index("SpinDoctor helpers") + 1


# ── the settings: toolkit idle-tour-settings ─────────────────────────────────

def test_settings_are_found_beside_the_bat_the_startup_script_starts(cabinet, tmp_path):
    cfg = config_mod.load_config()
    assert it.settings_location(cfg) == cabinet["menu"] / SETTINGS_FILE     # install-tools' folder
    other = tmp_path / "elsewhere"
    assert _run("install-tools", "--tool", "idle-tour", "--output-dir", str(other), "--apply").exit_code == 0
    assert it.settings_location(cfg).resolve() == (other / SETTINGS_FILE).resolve()
    assert it.settings_location(Config()) is None
    # An entry edited by hand to run the .bat by its full path from another
    # folder: the .bat reads the settings beside itself.
    bat = (other / "Idle Tour.bat").resolve()
    text = cabinet["ini"].read_text(encoding="utf-8")
    text = text.replace("Program_To_Run_Target_3=Idle Tour.bat", f"Program_To_Run_Target_3={bat}")
    text = text.replace(f"Program_To_Run_Working_Dir_3={other.resolve()}",
                        f"Program_To_Run_Working_Dir_3={cabinet['hs']}")
    cabinet["ini"].write_text(text, encoding="utf-8")
    assert f"Program_To_Run_Target_3={bat}" in text and f"Working_Dir_3={cabinet['hs']}" in text
    assert it.settings_location(cfg) == bat.parent / SETTINGS_FILE


def test_settings_command_shows_the_installed_settings(cabinet):
    missing = _run("toolkit", "idle-tour-settings")
    assert missing.exit_code == 1 and "Install the tour first" in missing.output
    assert _run("install-tools", "--tool", "idle-tour").exit_code == 0
    result = _run("toolkit", "idle-tour-settings")
    assert result.exit_code == 0, result.output
    assert re.search(r"GamesPerConsole\s+5\b", result.output)
    assert re.search(r"NoVideoSeconds\s+8\b", result.output)
    assert re.search(r"Skip\s+Toolkit\|Favorites\|Most Played\|Recently Played", result.output)


def test_settings_command_changes_only_the_keys_given(cabinet):
    assert _run("install-tools", "--tool", "idle-tour").exit_code == 0
    path = cabinet["menu"] / SETTINGS_FILE
    before = path.read_bytes()
    args = ("toolkit", "idle-tour-settings", "--consoles-on-main-menu", "1", "--games-per-console", "10",
            "--console-minutes", "0", "--main-menu-minutes", "0", "--tour-max-minutes", "60",
            "--no-video-seconds", "12", "--skip", "Toolkit|Apple II", "--enabled")
    result = _run(*args)
    assert result.exit_code == 0, result.output
    assert "GamesPerConsole: 5 → 10" in result.output and "ConsolesOnMainMenu: 5 → 1" in result.output
    assert "NoVideoSeconds: 8 → 12" in result.output
    assert "TourMaxMinutes: 0 → 60" in result.output     # a tour limit (none by default)
    assert "Enabled" not in result.output   # already so
    expected = before
    for old, new in ((b"GamesPerConsole=5\r", b"GamesPerConsole=10\r"),
                     (b"ConsoleMinutes=5\r", b"ConsoleMinutes=0\r"),
                     (b"ConsolesOnMainMenu=5\r", b"ConsolesOnMainMenu=1\r"),
                     (b"MainMenuMinutes=5\r", b"MainMenuMinutes=0\r"),
                     (b"TourMaxMinutes=0\r", b"TourMaxMinutes=60\r"),
                     (b"NoVideoSeconds=8\r", b"NoVideoSeconds=12\r"),
                     (b"Skip=Toolkit|Favorites|Most Played|Recently Played\r", b"Skip=Toolkit|Apple II\r")):
        assert expected.count(old) == 1, old
        expected = expected.replace(old, new)
    assert path.read_bytes() == expected
    again = _run(*args)
    assert "Nothing to change" in again.output and path.read_bytes() == expected
    assert _run("toolkit", "idle-tour-settings", "--disabled", "--skip", "").exit_code == 0
    s = it.read_settings(path)
    assert not s.enabled and s.skip == ()
    assert _run("toolkit", "idle-tour-settings", "--games-per-console", "-1").exit_code == 2
    assert _run("toolkit", "idle-tour-settings", "--console-minutes", "2000").exit_code == 2
    assert _run("toolkit", "idle-tour-settings", "--no-video-seconds", "4000").exit_code == 2
    before = path.read_bytes()
    nan = _run("toolkit", "idle-tour-settings", "--console-minutes", "nan")   # click's range may let it by
    assert nan.exit_code in (1, 2) and path.read_bytes() == before


def test_settings_command_reports_a_file_it_cant_change(cabinet, tmp_path):
    path = tmp_path / "ansi.ini"
    path.write_bytes(b"[IdleTour]\r\nSkip=Pok\xe9mon Mini\r\n")
    result = _run("toolkit", "idle-tour-settings", "--settings", str(path), "--skip", "漢字")
    assert result.exit_code == 1 and "Not changed" in result.output
    assert path.read_bytes() == b"[IdleTour]\r\nSkip=Pok\xe9mon Mini\r\n"


# ── GUI ──────────────────────────────────────────────────────────────────────

def test_gui_passes_apply_for_the_idle_tour_when_apply_is_ticked(monkeypatch):
    from tests.test_gui import _build_gui_for_test

    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        ran = []
        monkeypatch.setattr(app, "_run_cli", lambda _bin, args: ran.append(list(args)))
        app._tools_pick_vars["idle-tour"].set(True)
        app._run_install_tools()
        app._global_apply_var.set(True)
        app._run_install_tools()
        app._tools_pick_vars["idle-tour"].set(False)
        app._tools_pick_vars["refresh-all"].set(True)
        app._run_install_tools()
        assert ran == [
            ["install-tools", "--tool", "idle-tour"],
            ["install-tools", "--tool", "idle-tour", "--apply"],
            ["install-tools", "--tool", "refresh-all"],
        ]
        # "Install into wheel" leaves the Idle Tour out instead of failing.
        prompts = []
        monkeypatch.setattr(app, "_flash_validation", prompts.append)
        app._tools_wheel_var.set("Toolkit")
        app._tools_pick_vars["idle-tour"].set(True)
        app._run_install_tools_into_wheel()
        assert ran[-1] == ["install-tools", "--tool", "refresh-all", "--add-to-system", "Toolkit"]
        app._tools_pick_vars["refresh-all"].set(False)
        app._run_install_tools_into_wheel()
        assert len(ran) == 4 and "starts with HyperSpin" in prompts[-1]
    finally:
        app.root.destroy()


def test_gui_settings_form_loads_and_saves_the_idle_tour_settings(cabinet, monkeypatch):
    from tests.test_gui import _build_gui_for_test

    assert _run("install-tools", "--tool", "idle-tour").exit_code == 0
    path = cabinet["menu"] / SETTINGS_FILE
    it.change_settings(path, games_per_console=10, skip=("Toolkit", "Favorites"))
    menu = cabinet["hs"] / "Databases" / "Main Menu"
    menu.mkdir(parents=True)
    (menu / "Main Menu.xml").write_text(
        '<menu>\n<game name="MAME"/>\n<game name="Toolkit"/>\n<game name="Atari 2600"/>\n'
        '<game name="toolkit"/>\n</menu>\n',                  # listed twice: shown once
        encoding="utf-8")
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        # Loaded at start: the file's values, the main menu as the skip list
        # (skipped names that aren't on it at the end), the file's place.
        assert app._idle_tour_vars["games_per_console"].get() == "10"
        assert app._idle_tour_vars["tour_max_minutes"].get() == "0"      # no tour limit by default
        assert app._idle_tour_vars["no_video_seconds"].get() == "8"
        lb = app._idle_tour_skip_lb
        assert list(lb.get(0, "end")) == ["MAME", "Toolkit", "Atari 2600", "Favorites"]
        assert [lb.get(i) for i in lb.curselection()] == ["Toolkit", "Favorites"]
        assert str(path) in app._idle_tour_file_label.cget("text")

        ran = []
        monkeypatch.setattr(app, "_run_cli",
                            lambda _bin, args, on_complete=None: ran.append(list(args)))
        app._idle_tour_enabled_var.set(False)
        app._idle_tour_vars["consoles_on_main_menu"].set("1")
        app._idle_tour_vars["main_menu_minutes"].set("2.5")
        app._idle_tour_vars["tour_max_minutes"].set("45")
        app._idle_tour_vars["no_video_seconds"].set("0")
        lb.selection_clear(0, "end")
        lb.selection_set(2)
        app._save_idle_tour_settings()
        assert ran == [["toolkit", "idle-tour-settings", "--settings", str(path), "--disabled",
                        "--games-per-console", "10", "--console-minutes", "5",
                        "--consoles-on-main-menu", "1", "--main-menu-minutes", "2.5",
                        "--tour-max-minutes", "45", "--no-video-seconds", "0", "--skip", "Atari 2600"]]
        # What it runs writes what the form shows; Load reads it back.
        assert _run(*ran[0]).exit_code == 0
        app._load_idle_tour_settings()
        assert not app._idle_tour_enabled_var.get()
        assert app._idle_tour_vars["main_menu_minutes"].get() == "2.5"
        assert app._idle_tour_vars["no_video_seconds"].get() == "0"
        assert it.read_settings(path).no_video_seconds == 0
        assert app._idle_tour_vars["tour_max_minutes"].get() == "45"
        assert it.read_settings(path).tour_max_minutes == 45
        assert [lb.get(i) for i in lb.curselection()] == ["Atari 2600"]
        assert list(lb.get(0, "end")) == ["MAME", "Toolkit", "Atari 2600"]

        # Numbers the CLI would refuse are caught before anything runs.
        prompts = []
        monkeypatch.setattr(app, "_flash_validation", prompts.append)
        for field, raw, label in (("console_minutes", "-2", "Minutes in a console"),
                                  ("games_per_console", "2.5", "Games in a console"),
                                  ("tour_max_minutes", "nan", "Tour limit"),
                                  ("main_menu_minutes", "5000", "Minutes on the main menu"),
                                  ("no_video_seconds", "-1", "Seconds on an item with no video"),
                                  ("no_video_seconds", "4000", "Seconds on an item with no video")):
            app._load_idle_tour_settings()
            app._idle_tour_vars[field].set(raw)
            app._save_idle_tour_settings()
            assert len(ran) == 1 and label in prompts[-1], (field, prompts)
        # Not installed: the form says so and Save runs nothing.
        path.unlink()
        app._load_idle_tour_settings()
        assert "Not installed yet" in app._idle_tour_file_label.cget("text")
        assert app._idle_tour_vars["games_per_console"].get() == "5"      # the defaults
        app._save_idle_tour_settings()
        assert len(ran) == 1 and "Install Idle Tour first" in prompts[-1]
    finally:
        app.root.destroy()
