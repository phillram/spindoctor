"""Tests for the `doctor` ScummVM game list check (``health.check_scummvm_game_list``).

RocketLauncher's ScummVM module starts ``scummvm.exe [-c<list>] <target>``.  It
reads ScummVM's game list from ``[Settings] CustomConfig`` in its module INIs
(relative to the RocketLauncher folder), else from ScummVM's own
``%APPDATA%\\ScummVM\\scummvm.ini``, and stops with "Cannot find …" when that
file isn't there.  The target is the game's ``TargetName``, else its name, and
ScummVM finds the game's files under ``[<target>] path=`` in that list.  Each
test builds a small HyperSpin + RocketLauncher cabinet in a temp dir, laid out
like a real one: ``Settings\\ScummVM\\Emulators.ini`` with ``[Roms]``,
``Skipchecks=Rom Only``, the emulator in ``<tmp>\\Arcade\\Emulators\\ScummVM``
and the games in ``<tmp>\\Games\\ScummVM\\<target>\\``.  ``APPDATA`` points at
an empty ``<tmp>\\AppData`` unless a test fills it.
"""
from __future__ import annotations

import os

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    # RocketLauncher's INIs are CRLF files.
    path.write_bytes(text.replace("\n", "\r\n").encode("cp1252"))
    return path


def _cabinet(tmp_path, monkeypatch, games, system="ScummVM", module_ini="", default_emulator="ScummVM",
             other_wheels=None, hidden=(), games_ini=""):
    """A cabinet whose *system* wheel lists *games*, started with the ScummVM
    module unless *default_emulator* says otherwise.  *module_ini* is the body
    of ``Modules\\ScummVM\\ScummVM.ini`` after its ``[Settings]`` line."""
    hs = tmp_path / "Arcade"
    rl = hs / "RocketLauncher"
    folder = tmp_path / "Games" / system
    folder.mkdir(parents=True, exist_ok=True)
    (tmp_path / "AppData").mkdir(exist_ok=True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    wheels = {system: games, **(other_wheels or {})}
    menu = "".join(
        f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>' for w in wheels
    )
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, names in wheels.items():
        xml = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in names)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    _write(rl / "Settings" / "Global Emulators.ini",
           "[ScummVM]\nEmu_Path=..\\Emulators\\ScummVM\\scummvm.exe\nRom_Extension=7z|zip|txt\n"
           "Module=ScummVM.ahk\n\n"
           "[DOSBox]\nEmu_Path=..\\Emulators\\DOSBox\\dosbox.exe\nRom_Extension=exe|bat\n")
    _write(rl / "Settings" / system / "Emulators.ini",
           f"[Roms]\nRom_Path={folder}\nDefault_Emulator={default_emulator}\n")
    _write(rl / "Settings" / system / "RocketLauncher.ini", "[Settings]\nSkipchecks=Rom Only\n")
    if games_ini:
        _write(rl / "Settings" / system / "Games.ini", games_ini)
    _write(rl / "Modules" / "ScummVM" / "ScummVM.ahk", 'MEmu := "ScummVM"\n')
    _write(rl / "Modules" / "ScummVM" / "ScummVM.ini", "[Settings]\nFullscreen=true\n" + module_ini)
    _write(hs / "Emulators" / "ScummVM" / "scummvm.exe", "MZ")
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl), roms_dir=str(tmp_path / "Games"))
    return cfg, rl, folder


def _game_list(path, targets):
    """A scummvm.ini at *path* with ``{target: path= value}`` (None = no path= line)."""
    text = "[scummvm]\nversioninfo=1.7.0\nfullscreen=true\n\n"
    for target, value in targets.items():
        text += f"[{target}]\ndescription={target}\n" + (f"path={value}\n" if value is not None else "")
        text += "gameid=scumm\n\n"
    return _write(path, text)


def _games(folder, *names):
    """A folder per game in Rom_Path, as ScummVM games are kept."""
    for name in names:
        _write(folder / name / "data.000", "x")
    return {name: f"{folder / name}{os.sep}" for name in names}


def _appdata_list(tmp_path):
    return tmp_path / "AppData" / "ScummVM" / "scummvm.ini"


def _beside_emulator(rl):
    return rl.parent / "Emulators" / "ScummVM" / "scummvm.ini"


def _wheel(cfg, name="ScummVM"):
    result = health.check_scummvm_game_list(cfg)
    return next(c for c in result.children if c.name == name)


def _row(node, name):
    rows = [c for c in node.children if c.name == name]
    return rows[0] if rows else None


# ─── basics ──────────────────────────────────────────────────────────────────


def test_info_without_rocketlauncher_or_hyperspin_dir(tmp_path, monkeypatch):
    cfg, _rl, _f = _cabinet(tmp_path, monkeypatch, ["sword1"])
    cfg.rocketlauncher_dir = ""
    assert health.check_scummvm_game_list(cfg).status == INFO
    cfg, _rl, _f = _cabinet(tmp_path / "b", monkeypatch, ["sword1"])
    cfg.hyperspin_dir = str(tmp_path / "missing")
    assert health.check_scummvm_game_list(cfg).status == INFO


def test_info_when_no_wheel_uses_the_module(tmp_path, monkeypatch):
    cfg, _rl, _f = _cabinet(tmp_path, monkeypatch, ["Commander Keen"], system="DOS", default_emulator="DOSBox")
    result = health.check_scummvm_game_list(cfg)
    assert result.status == INFO
    assert "no wheels start games with the ScummVM module" in result.detail
    assert result.children == []


def test_registered_in_doctor(tmp_path, monkeypatch):
    cfg, _rl, _f = _cabinet(tmp_path, monkeypatch, [])
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert names.index("ScummVM game list") == names.index("RocketLauncher settings") + 1


# ─── the game list ───────────────────────────────────────────────────────────


def test_appdata_game_list_with_every_game_is_ok(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1", "monkey2"])
    _game_list(_appdata_list(tmp_path), _games(folder, "sword1", "monkey2"))
    result = health.check_scummvm_game_list(cfg)
    assert result.status == OK
    [node] = result.children
    assert node.status == OK
    assert node.children == []
    assert "2 games OK" in node.detail
    assert f"game list: {_appdata_list(tmp_path)}" in node.detail


def test_missing_appdata_game_list_warns_and_names_the_list_beside_the_emulator(tmp_path, monkeypatch):
    # No CustomConfig and nothing in AppData: the module stops every game, though
    # the emulator folder holds the list (a portable copy moved from another PC).
    cfg, rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1", "comi"])
    _game_list(_beside_emulator(rl), _games(folder, "sword1", "comi"))
    node = _wheel(cfg)
    assert node.status == WARN
    row = _row(node, "Game list")
    assert row.status == WARN
    assert "2/2 games won't start" in row.detail
    assert str(_appdata_list(tmp_path)) in row.detail
    assert "no CustomConfig" in row.detail
    assert f'"Cannot find {_appdata_list(tmp_path)}"' in row.detail
    rel = os.path.join("..", "Emulators", "ScummVM", "scummvm.ini")
    assert row.fix.startswith(f"Set CustomConfig={rel} under [Settings] in ")
    assert row.fix.endswith("(the game list beside the emulator)")
    assert str(rl / "Modules" / "ScummVM" / "ScummVM.ini") in row.fix
    # The games themselves aren't judged against a list the module can't read.
    assert _row(node, "Targets") is None and _row(node, "Game folders") is None


def test_missing_appdata_game_list_with_none_beside_the_emulator(tmp_path, monkeypatch):
    cfg, rl, _folder = _cabinet(tmp_path, monkeypatch, ["sword1"])
    row = _row(_wheel(cfg), "Game list")
    assert row.status == WARN
    assert "Set CustomConfig=<your scummvm.ini" in row.fix
    assert f"start ScummVM once so it writes {_appdata_list(tmp_path)}" in row.fix


def test_custom_config_is_relative_to_the_rocketlauncher_folder(tmp_path, monkeypatch):
    cfg, rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1"],
                               module_ini="CustomConfig=..\\Emulators\\ScummVM\\scummvm.ini\n")
    _game_list(_beside_emulator(rl), _games(folder, "sword1"))
    node = _wheel(cfg)
    assert node.status == OK
    assert f"game list: {_beside_emulator(rl)}" in node.detail


def test_custom_config_that_is_missing_warns(tmp_path, monkeypatch):
    cfg, rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1"],
                               module_ini="CustomConfig=..\\Emulators\\ScummVM\\gone.ini\n")
    _game_list(_appdata_list(tmp_path), _games(folder, "sword1"))  # not read with CustomConfig set
    row = _row(_wheel(cfg), "Game list")
    assert row.status == WARN
    gone = rl.parent / "Emulators" / "ScummVM" / "gone.ini"
    assert f'("Cannot find {gone}"): CustomConfig=..\\Emulators\\ScummVM\\gone.ini in ' in row.detail
    assert row.fix.startswith(f"Point CustomConfig in {rl / 'Modules' / 'ScummVM' / 'ScummVM.ini'}")


def test_per_game_and_system_module_inis_come_first(tmp_path, monkeypatch):
    # RL reads <System>\<game>.ini, then <System>.ini, then ScummVM.ini.
    cfg, rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1", "comi"], system="LucasArts",
                               module_ini="CustomConfig=..\\Emulators\\ScummVM\\gone.ini\n")
    _game_list(_beside_emulator(rl), _games(folder, "sword1", "comi"))
    modules = rl / "Modules" / "ScummVM"
    _write(modules / "LucasArts" / "sword1.ini", "[Settings]\nCustomConfig=..\\Emulators\\ScummVM\\scummvm.ini\n")
    node = _wheel(cfg, "LucasArts")
    assert "1/2 games won't start" in _row(node, "Game list").detail  # comi still reads gone.ini
    assert "1 games OK" not in node.detail
    _write(modules / "LucasArts.ini", "[Settings]\nCustomConfig=..\\Emulators\\ScummVM\\scummvm.ini\n")
    node = _wheel(cfg, "LucasArts")
    assert node.status == OK
    assert "2 games OK" in node.detail


def test_unreadable_drive_path_or_no_appdata_is_not_judged(tmp_path, monkeypatch):
    cfg, _rl, _folder = _cabinet(tmp_path, monkeypatch, ["sword1"])
    monkeypatch.delenv("APPDATA")
    node = _wheel(cfg)
    assert node.status == OK
    assert node.children == []
    assert "can't check them on this OS" in node.detail


# ─── targets and their folders ───────────────────────────────────────────────


def test_paths_on_an_old_drive_warn_with_the_folder_under_roms_dir(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1", "comi", "dig"])
    here = _games(folder, "sword1", "comi", "dig")
    old = tmp_path / "OldDrive" / "Games" / "ScummVM"
    _game_list(_appdata_list(tmp_path), {
        "sword1": f"{old / 'sword1'}{os.sep}",
        "comi": f"{old / 'comi'}{os.sep}",
        "dig": here["dig"],
    })
    node = _wheel(cfg)
    assert node.status == WARN
    row = _row(node, "Game folders")
    assert row.status == WARN
    assert "2/3 games won't start" in row.detail
    assert f"sword1: {old / 'sword1'}{os.sep}" in row.detail
    assert "dig" not in row.detail
    assert f"[sword1] path={folder / 'sword1'}{os.sep}" in row.fix
    assert "With ScummVM closed (it rewrites scummvm.ini when it exits)" in row.fix
    assert "games OK" not in node.detail


def test_a_game_with_no_section_warns(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1", "Day of the Tentacle (CD DOS)"])
    _game_list(_appdata_list(tmp_path), _games(folder, "sword1", "tentacle"))
    node = _wheel(cfg)
    row = _row(node, "Targets")
    assert row.status == WARN
    assert "1/2 games have no section in" in row.detail
    assert "Day of the Tentacle (CD DOS)" in row.detail
    assert "sword1" not in row.detail
    assert "TargetName=<ScummVM target> under [<game>]" in row.fix


def test_target_name_from_the_module_ini(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["Day of the Tentacle (CD DOS)"],
                                module_ini="\n[Day of the Tentacle (CD DOS)]\nTargetName=tentacle\n")
    _game_list(_appdata_list(tmp_path), _games(folder, "tentacle"))
    assert _wheel(cfg).status == OK


def test_target_name_from_a_per_game_module_ini(tmp_path, monkeypatch):
    cfg, rl, folder = _cabinet(tmp_path, monkeypatch, ["Day of the Tentacle (CD DOS)"])
    _write(rl / "Modules" / "ScummVM" / "ScummVM" / "Day of the Tentacle (CD DOS).ini",
           "[Day of the Tentacle (CD DOS)]\nTargetName=tentacle\n")
    _game_list(_appdata_list(tmp_path), _games(folder, "tentacle"))
    assert _wheel(cfg).status == OK


def test_old_scummvmname_key_is_not_a_target_name(tmp_path, monkeypatch):
    # Module 2.x reads TargetName only; ScummVMName= (old example INIs) is ignored.
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["Day of the Tentacle (CD DOS)"],
                                module_ini="\n[Day of the Tentacle (CD DOS)]\nScummVMName=tentacle\n")
    _game_list(_appdata_list(tmp_path), _games(folder, "tentacle"))
    assert _row(_wheel(cfg), "Targets").status == WARN


def test_section_names_ignore_case(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1"])
    _game_list(_appdata_list(tmp_path), {"SWORD1": _games(folder, "sword1")["sword1"]})
    assert _wheel(cfg).status == OK


def test_a_section_without_path_warns(tmp_path, monkeypatch):
    cfg, _rl, _folder = _cabinet(tmp_path, monkeypatch, ["sword1"])
    _game_list(_appdata_list(tmp_path), {"sword1": None})
    row = _row(_wheel(cfg), "Game folders")
    assert row.status == WARN
    assert "sword1: no path=" in row.detail


def test_a_relative_path_starts_from_the_emulator_folder(tmp_path, monkeypatch):
    cfg, rl, _folder = _cabinet(tmp_path, monkeypatch, ["sword1"])
    _write(rl.parent / "Emulators" / "ScummVM" / "games" / "sword1" / "data.000", "x")
    _game_list(_appdata_list(tmp_path), {"sword1": "games\\sword1\\"})
    assert _wheel(cfg).status == OK


def test_a_quoted_custom_config_is_read(tmp_path, monkeypatch):
    cfg, rl, folder = _cabinet(tmp_path, monkeypatch, ["sword1"],
                               module_ini='CustomConfig="..\\Emulators\\ScummVM\\scummvm.ini"\n')
    _game_list(_beside_emulator(rl), _games(folder, "sword1"))
    assert _wheel(cfg).status == OK


# ─── LaunchMode=ParseIni ─────────────────────────────────────────────────────


def test_parseini_looks_up_the_name_with_underscores(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["Sam and Max (CD DOS)"],
                                module_ini="LaunchMode=ParseIni\n")
    elsewhere = tmp_path / "Elsewhere"
    _game_list(_appdata_list(tmp_path), {"Sam_and_Max__CD_DOS_": _games(elsewhere, "samnmax")["samnmax"]})
    assert _wheel(cfg).status == OK


def test_parseini_falls_back_to_the_rom_path_folder(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["Sam and Max (CD DOS)", "Lost Game"],
                                module_ini="LaunchMode=ParseIni\n")
    _games(folder, "Sam and Max (CD DOS)")
    _game_list(_appdata_list(tmp_path), {})
    node = _wheel(cfg)
    assert node.status == WARN
    fallback = _row(node, "ParseIni")
    assert fallback.status == INFO
    assert "Sam and Max (CD DOS)" in fallback.detail
    targets = _row(node, "Targets")
    assert "Lost Game [Lost_Game]" in targets.detail
    assert "Sam and Max" not in targets.detail


def test_launch_mode_per_game(tmp_path, monkeypatch):
    # [<game>] LaunchMode= beats [Settings]; only ParseIni games fall back.
    cfg, _rl, folder = _cabinet(tmp_path, monkeypatch, ["Sam and Max (CD DOS)", "Loom (CD DOS)"],
                                module_ini="\n[Sam and Max (CD DOS)]\nLaunchMode=ParseIni\n")
    _games(folder, "Sam and Max (CD DOS)", "Loom (CD DOS)")
    _game_list(_appdata_list(tmp_path), {})
    node = _wheel(cfg)
    assert "Sam and Max (CD DOS)" in _row(node, "ParseIni").detail
    assert "Loom (CD DOS)" in _row(node, "Targets").detail


# ─── which games ─────────────────────────────────────────────────────────────


def test_only_games_ini_overrides_to_scummvm_are_checked(tmp_path, monkeypatch):
    cfg, _rl, folder = _cabinet(
        tmp_path, monkeypatch, ["Commander Keen", "Loom (CD DOS)"], system="DOS", default_emulator="DOSBox",
        games_ini="[Loom (CD DOS)]\nEmulator=ScummVM\n",
    )
    _game_list(_appdata_list(tmp_path), {})
    node = _wheel(cfg, "DOS")
    row = _row(node, "Targets")
    assert "1/1 games" in row.detail
    assert "Loom (CD DOS)" in row.detail
    assert "Commander Keen" not in row.detail


def test_a_game_module_is_not_the_scummvm_module(tmp_path, monkeypatch):
    cfg, rl, _folder = _cabinet(tmp_path, monkeypatch, ["sword1", "Special"])
    _write(rl / "Modules" / "Game Modules" / "Special" / "Special.ahk", 'MEmu := "Special"\n')
    _game_list(_appdata_list(tmp_path), {})
    row = _row(_wheel(cfg), "Targets")
    assert "1/1 games" in row.detail
    assert "Special" not in row.detail


def test_hidden_wheel_is_capped_at_info(tmp_path, monkeypatch):
    cfg, _rl, _folder = _cabinet(tmp_path, monkeypatch, ["sword1"], hidden=("ScummVM",))
    result = health.check_scummvm_game_list(cfg)
    [node] = result.children
    assert node.name == "ScummVM (hidden on the Main Menu)"
    assert node.status == INFO
    assert _row(node, "Game list").status == INFO
    assert result.status == INFO
