"""Tests for the `doctor` **SpinDoctor helpers** check.

`install-tools` writes ``Refresh Favorites.bat`` and friends with the full path
of the SpinDoctor EXE that ran it: v3 ``"<exe>" --run-tool spindoctor-fav …``,
v2 ``"<install folder>\\spindoctor-fav.exe" …``.  Portable installs unzip each
release into a new folder, so once the old one is gone every helper fails while
nothing else looks wrong.  The check finds the helpers where `install-tools`
writes them (the Tools-menu folder, and the folders ``--add-to-system`` uses)
and WARNs when a program they run is missing.

Each test builds a small RocketLauncher tree in a temp dir.
"""
from __future__ import annotations

import os
import sys

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO

STEMS = ("Refresh Favorites", "Refresh Recently Played", "Refresh Most Played", "Refresh All")
TOOLS = {"Refresh Favorites": "spindoctor-fav", "Refresh Recently Played": "spindoctor-recent",
         "Refresh Most Played": "spindoctor-stats"}
# The fix re-runs install-tools with the helpers found in that folder.
PICK = "--tool refresh-favorites,refresh-recently-played,refresh-most-played,refresh-all"


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _exe(path):
    """A stand-in SpinDoctor EXE."""
    return _write(path, "MZ")


def _v3_bat(exe, tool):
    """A helper as v3's install-tools writes it (one EXE, --run-tool)."""
    return (f'@echo off\r\nREM Regenerates a wheel.\r\nstart "" /B /WAIT "{exe}" '
            f"--run-tool {tool} rebuild --apply\r\nif errorlevel 1 pause\r\nexit\r\n")


def _v2_bat(folder, tool):
    """A helper as v2 wrote it (a sibling EXE per tool, inside the install folder)."""
    return (f'@echo off\r\nstart "" /B /WAIT "{folder}\\{tool}.exe" rebuild --apply\r\n'
            "if errorlevel 1 pause\r\nexit\r\n")


def _helpers(folder, body):
    """The four helpers in *folder*; *body(tool)* gives each one's text."""
    for stem in STEMS:
        tools = list(TOOLS.values()) if stem == "Refresh All" else [TOOLS[stem]]
        _write(folder / f"{stem}.bat", "".join(body(t) for t in tools))
    return folder


def _cfg(rl):
    return Config(rocketlauncher_dir=str(rl))


def _tools_menu(rl):
    return rl / "Modules" / "HyperLaunch" / "Tools" / "spindoctor"


def _row(chk, name):
    return next(c for c in chk.children if c.name == name)


# ── Tools-menu helpers (plain `install-tools`) ──────────────────────────────

def test_v3_helpers_whose_exe_is_gone_warn_with_install_tools_as_the_fix(tmp_path):
    rl = tmp_path / "RocketLauncher"
    old = tmp_path / "spindoctor-win10-v3.0.0" / "spindoctor-gui.exe"
    _helpers(_tools_menu(rl), lambda t: _v3_bat(old, t))
    chk = health.check_refresh_helpers(_cfg(rl))
    assert chk.status == WARN
    row = _row(chk, "Tools menu")
    assert row.status == WARN
    assert "4 of 4 helper(s)" in row.detail
    assert str(old) in row.detail and "no longer exists" in row.detail
    assert row.fix == f"spindoctor install-tools {PICK}"


def test_v3_helpers_whose_exe_exists_are_ok(tmp_path):
    rl = tmp_path / "RocketLauncher"
    exe = _exe(tmp_path / "spindoctor" / "spindoctor-gui.exe")
    _helpers(_tools_menu(rl), lambda t: _v3_bat(exe, t))
    chk = health.check_refresh_helpers(_cfg(rl))
    assert chk.status == OK
    row = _row(chk, "Tools menu")
    assert row.status == OK and str(exe) in row.detail and row.fix is None


def test_v2_sibling_exe_helpers_from_a_removed_install_folder_warn(tmp_path):
    rl = tmp_path / "RocketLauncher"
    old = tmp_path / "spindoctor-win7-v2.10.1"  # never created: the folder is gone
    _helpers(_tools_menu(rl), lambda t: _v2_bat(old, t))
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu")
    assert row.status == WARN
    assert "4 of 4 helper(s)" in row.detail
    # Three different missing programs: the first is named, the rest counted.
    assert f"{old}\\spindoctor-" in row.detail and "and 2 more" in row.detail


def test_oldest_format_without_start_is_read_too(tmp_path):
    rl = tmp_path / "RocketLauncher"
    old = tmp_path / "gone" / "spindoctor-fav.exe"
    _write(_tools_menu(rl) / "Refresh Favorites.bat",
           f'@echo off\r\n"{old}" rebuild --apply\r\nif errorlevel 1 pause\r\nexit\r\n')
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu")
    assert row.status == WARN and "1 of 1 helper(s)" in row.detail and str(old) in row.detail


def test_only_helpers_with_a_missing_program_are_counted(tmp_path):
    rl = tmp_path / "RocketLauncher"
    exe = _exe(tmp_path / "spindoctor" / "spindoctor-gui.exe")
    folder = _helpers(_tools_menu(rl), lambda t: _v3_bat(exe, t))
    _write(folder / "Refresh Favorites.bat", _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", "spindoctor-fav"))
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu")
    assert row.status == WARN and "1 of 4 helper(s)" in row.detail


def test_doubled_carriage_returns_still_parse(tmp_path):
    # Text-mode write_text of "\r\n" on Windows leaves "\r\r\n" line ends.
    rl = tmp_path / "RocketLauncher"
    old = tmp_path / "old" / "spindoctor-gui.exe"
    bat = _tools_menu(rl) / "Refresh All.bat"
    bat.parent.mkdir(parents=True)
    bat.write_bytes(_v3_bat(old, "spindoctor-fav").replace("\r\n", "\r\r\n").encode("utf-8"))
    assert _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu").status == WARN


def test_comment_lines_are_ignored(tmp_path):
    rl = tmp_path / "RocketLauncher"
    exe = _exe(tmp_path / "spindoctor" / "spindoctor-gui.exe")
    gone = tmp_path / "old" / "spindoctor-gui.exe"
    _write(_tools_menu(rl) / "Refresh All.bat",
           f'@echo off\r\nREM was "{gone}"\r\n:: also "{gone}"\r\n@rem "{gone}"\r\n' + _v3_bat(exe, "spindoctor-fav"))
    assert _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu").status == OK


def test_source_install_helpers_with_bare_names_are_info(tmp_path):
    rl = tmp_path / "RocketLauncher"
    _helpers(_tools_menu(rl), lambda t: f'@echo off\r\nstart "" /B /WAIT {t} rebuild --apply\r\nexit\r\n')
    chk = health.check_refresh_helpers(_cfg(rl))
    assert chk.status == INFO
    assert _row(chk, "Tools menu").status == INFO


def test_a_program_named_through_an_environment_variable_is_not_checked(tmp_path):
    rl = tmp_path / "RocketLauncher"
    _write(_tools_menu(rl) / "Refresh All.bat",
           '@echo off\r\nstart "" /B /WAIT "%LOCALAPPDATA%\\SpinDoctor\\spindoctor.exe" --run-tool spindoctor-fav\r\n')
    assert _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu").status == INFO


def test_a_relative_program_path_resolves_from_the_bat_folder(tmp_path):
    rl = tmp_path / "RocketLauncher"
    folder = _tools_menu(rl)
    _exe(folder / "bin" / "spindoctor.exe")
    _write(folder / "Refresh All.bat", f'start "" /B /WAIT "bin{os.sep}spindoctor.exe" --run-tool spindoctor-fav\r\n')
    assert _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu").status == OK


def test_other_bat_files_in_the_folder_are_not_read(tmp_path):
    rl = tmp_path / "RocketLauncher"
    _write(_tools_menu(rl) / "My Script.bat", f'"{tmp_path / "gone.exe"}"\r\n')
    chk = health.check_refresh_helpers(_cfg(rl))
    assert chk.status == INFO and not chk.children


def test_legacy_refresh_both_is_checked(tmp_path):
    rl = tmp_path / "RocketLauncher"
    _write(_tools_menu(rl) / "Refresh Both.bat", _v2_bat(tmp_path / "spindoctor-v2.4.0", "spindoctor-fav"))
    assert _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu").status == WARN


# ── --add-to-system helpers (a Toolkit wheel) ───────────────────────────────

def _toolkit(tmp_path, rom_path=None, wired=True, folder=None):
    """RocketLauncher with a PCLauncher 'Toolkit' wheel.  The helpers go to
    *folder* (default: an absolute *rom_path*, else Modules\\PCLauncher\\Toolkit)
    and, when *wired*, the module INI has a section for each one."""
    rl = tmp_path / "RocketLauncher"
    pcl = rl / "Modules" / "PCLauncher"
    if rom_path is not None:
        _write(rl / "Settings" / "Toolkit" / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator=PCLauncher\nRom_Path={rom_path}\n")
    if folder is None:
        folder = pcl / "Toolkit" if rom_path is None else rom_path
    folder.mkdir(parents=True, exist_ok=True)
    module = "[Gun Control Start]\nApplication=D:\\Tools\\gun.exe\n\n"
    if wired:
        module += "".join(f"[{s}]\nApplication={folder / (s + '.bat')}\nWorkingFolder={folder}\n\n" for s in STEMS)
    _write(pcl / "Toolkit.ini", module)
    return rl, folder


def test_wired_toolkit_helpers_with_a_missing_exe_warn_with_the_add_to_system_fix(tmp_path):
    rl, folder = _toolkit(tmp_path, rom_path=tmp_path / "Utilities" / "Toolkit")
    old = tmp_path / "spindoctor-win7-v2.10.1"
    _helpers(folder, lambda t: _v2_bat(old, t))
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Toolkit")
    assert row.status == WARN
    assert str(folder) in row.detail
    assert row.fix == f'spindoctor install-tools {PICK} --add-to-system "Toolkit" --apply'


def test_helpers_left_by_a_run_without_apply_are_found_through_rom_path(tmp_path):
    # --add-to-system without --apply writes the .bat files to the wheel's
    # Rom_Path but no INIs; a relative Rom_Path resolves from RocketLauncher.
    rl, folder = _toolkit(tmp_path, rom_path="..\\Utilities\\Toolkit", wired=False,
                          folder=tmp_path / "Utilities" / "Toolkit")
    _helpers(folder, lambda t: _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", t))
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Toolkit")
    assert row.status == WARN
    # Re-run it the same way: no --apply, so the wheel isn't changed.
    assert row.fix == f'spindoctor install-tools {PICK} --add-to-system "Toolkit"'


def test_helpers_written_with_output_dir_get_it_in_the_fix(tmp_path):
    elsewhere = tmp_path / "Tools" / "Refresh"
    rl, folder = _toolkit(tmp_path, rom_path=tmp_path / "Utilities" / "Toolkit", folder=elsewhere)
    _helpers(folder, lambda t: _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", t))
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Toolkit")
    assert row.status == WARN
    assert row.fix == f'spindoctor install-tools {PICK} --output-dir "{elsewhere}" --add-to-system "Toolkit" --apply'


def test_helpers_in_the_pclauncher_folder_of_a_new_wheel(tmp_path):
    # No Settings\Toolkit\Emulators.ini: install-tools writes to Modules\PCLauncher\Toolkit.
    rl, folder = _toolkit(tmp_path)
    exe = _exe(tmp_path / "spindoctor" / "spindoctor-gui.exe")
    _helpers(folder, lambda t: _v3_bat(exe, t))
    chk = health.check_refresh_helpers(_cfg(rl))
    assert _row(chk, "Toolkit").status == OK and chk.status == OK


def test_section_and_key_names_are_case_insensitive(tmp_path):
    rl, folder = _toolkit(tmp_path, rom_path=tmp_path / "Utilities" / "Toolkit", wired=False)
    _write(rl / "Modules" / "PCLauncher" / "Toolkit.ini",
           f"[refresh all]\napplication={folder / 'Refresh All.bat'}\n")
    _write(folder / "Refresh All.bat", _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", "spindoctor-fav"))
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Toolkit")
    assert row.status == WARN and row.fix.endswith("--apply")


def test_a_folder_reached_twice_is_one_row(tmp_path):
    # --add-to-system with --output-dir pointing at the Tools-menu folder.
    menu = _tools_menu(tmp_path / "RocketLauncher")
    rl, folder = _toolkit(tmp_path, rom_path=tmp_path / "Utilities" / "Toolkit", folder=menu)
    _helpers(folder, lambda t: _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", t))
    chk = health.check_refresh_helpers(_cfg(rl))
    assert [c.name for c in chk.children] == ["Tools menu"]


def test_both_places_are_reported(tmp_path):
    rl, folder = _toolkit(tmp_path, rom_path=tmp_path / "Utilities" / "Toolkit")
    exe = _exe(tmp_path / "spindoctor" / "spindoctor-gui.exe")
    _helpers(folder, lambda t: _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", t))
    _helpers(_tools_menu(rl), lambda t: _v3_bat(exe, t))
    chk = health.check_refresh_helpers(_cfg(rl))
    assert {c.name: c.status for c in chk.children} == {"Tools menu": OK, "Toolkit": WARN}
    assert chk.status == WARN


# ── nothing to check ────────────────────────────────────────────────────────

def test_no_helpers_anywhere_is_info(tmp_path):
    rl, _folder = _toolkit(tmp_path, rom_path=tmp_path / "Utilities" / "Toolkit")
    chk = health.check_refresh_helpers(_cfg(rl))
    assert chk.status == INFO and not chk.children and "no install-tools helpers" in chk.detail


def test_rocketlauncher_dir_unset_is_info():
    chk = health.check_refresh_helpers(Config())
    assert chk.status == INFO and "rocketlauncher_dir" in chk.detail


# ── the real generator and the doctor run ───────────────────────────────────

def test_parses_what_install_tools_writes_on_a_frozen_build(tmp_path, monkeypatch):
    from spindoctor import cli

    exe = _exe(tmp_path / "spindoctor-win10-v3.0.0" / "spindoctor-gui.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    rl = tmp_path / "RocketLauncher"
    folder = _tools_menu(rl)
    folder.mkdir(parents=True)
    bats = cli._make_install_tools_bats()  # every helper install-tools can write
    for name, body in bats.items():
        (folder / name).write_text(body, encoding="utf-8")
    monkeypatch.undo()
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu")
    assert row.status == OK and str(exe) in row.detail
    exe.unlink()  # the release folder is removed after an upgrade
    row = _row(health.check_refresh_helpers(_cfg(rl)), "Tools menu")
    assert row.status == WARN and f"{len(bats)} of {len(bats)} helper(s)" in row.detail


def test_doctor_runs_the_check(tmp_path):
    rl = tmp_path / "RocketLauncher"
    _helpers(_tools_menu(rl), lambda t: _v3_bat(tmp_path / "old" / "spindoctor-gui.exe", t))
    cfg = Config(roms_dir=str(tmp_path / "Games"), hyperspin_dir=str(tmp_path / "HyperSpin"),
                 rocketlauncher_dir=str(rl))
    report = health.run_health_checks(cfg)
    chk = next(c for c in report.checks if c.name == "SpinDoctor helpers")
    assert chk.status == WARN and "check crashed" not in chk.detail
