"""Tests for the `doctor` DOSBox game configs check (``health.check_dosbox_game_configs``).

RocketLauncher's eXoDOS-style DOSBox module gives each game a short folder name
from ``[mapping]`` in ``ZipMapping\\<System>.ini`` beside it (else the game's
name) and starts DOSBox with ``<Config_Folder>\\<short>\\<Conf_File>``, by
default ``<the game's Rom_Path folder>\\!dos\\<short>\\dosbox.conf``; a missing
one stops the game before DOSBox starts.  DOS games also keep their saves in
their own (unpacked) folder, which RocketLauncher may delete after each game.
Each test builds a small HyperSpin + RocketLauncher cabinet in a temp dir, laid
out like a real one: ``Settings\\<System>\\Emulators.ini`` with ``[Roms]``,
``Skipchecks=Rom Only``, 7z on, and the games as ``<tmp>\\Games\\<System>\\<game>.zip``.
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO

MSDOS = "Microsoft MS-DOS"

# The lines of RocketLauncher's DOSBox module (2.0.x) that the check relies on.
EXODOS_MODULE = r"""MEmu = DOSBox
MVersion = 2.0.7
settingsFile := modulePath . "\" . moduleName . ".ini"
confFile := IniReadCheck(settingsFile, "Settings|" . romName, "Conf_File", "dosbox.conf",,1)
shortName := IniReadCheck(modulePath . "\ZipMapping\" . systemName . ".ini", "mapping", romName, romName,,1)
configFolder := IniReadCheck(settingsFile, "Settings", "Config_Folder", romPath . "\" . defaultConfigFolderName,,1)
originalConfFile := CheckFile(configFolder . "\" . shortName . "\" . confFile)
7zCleanUp()
"""

# Some other DOSBox module that starts games its own way.
PLAIN_MODULE = 'MEmu := "DOSBox"\nRun(executable . " """ . romPath . "\\" . romName . romExtension . """")\n'


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    # RocketLauncher's INIs are CRLF files.
    path.write_bytes(text.replace("\n", "\r\n").encode("cp1252"))
    return path


def _cabinet(tmp_path, games, system=MSDOS, *, emulator="DOSBox", module="DOSBox.ahk", module_text=EXODOS_MODULE,
             module_ini="", mapping="", default_emulator=None, seven="true", delete_temp="false", keep="",
             games_ini="", hidden=(), other_wheels=None, zips=True):
    """A cabinet whose *system* wheel lists *games*, started with the DOSBox
    module unless *default_emulator* says otherwise.  *module* is the
    ``Module=`` value (relative to ``Modules\\<emulator>``) and *module_ini* the
    body of the module's INI after its ``[Settings]`` line; *mapping* goes under
    ``[mapping]`` in ``ZipMapping\\<System>.ini``.  *keep* is
    ``7z_Games_to_Keep`` in ``Settings\\RocketLauncher.ini`` (None: no line)."""
    hs = tmp_path / "Arcade"
    rl = hs / "RocketLauncher"
    wheels = {system: games, **(other_wheels or {})}
    menu = "".join(
        f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>' for w in wheels
    )
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, names in wheels.items():
        xml = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in names)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
        folder = tmp_path / "Games" / wheel
        folder.mkdir(parents=True, exist_ok=True)
        if zips:
            for g in names:
                _write(folder / f"{g}.zip", "PK")
        _write(rl / "Settings" / wheel / "Emulators.ini",
               f"[Roms]\nRom_Path={folder}\nDefault_Emulator={default_emulator or emulator}\n")
        _write(rl / "Settings" / wheel / "RocketLauncher.ini",
               f"[Settings]\nSkipchecks=Rom Only\n\n[7z]\n7z_Enabled={seven}\n7z_Delete_Temp={delete_temp}\n")
    if games_ini:
        _write(rl / "Settings" / system / "Games.ini", games_ini)
    _write(rl / "Settings" / "Global Emulators.ini",
           f"[{emulator}]\nEmu_Path=..\\Emulators\\DOSBox\\dosbox.exe\nRom_Extension=zip|conf\nModule={module}\n\n"
           "[ScummVM]\nEmu_Path=..\\Emulators\\ScummVM\\scummvm.exe\nRom_Extension=zip\n")
    _write(rl / "Settings" / "Global RocketLauncher.ini", "[7z]\n7z_Enabled=false\n7z_Delete_Temp=true\n")
    _write(rl / "Settings" / "RocketLauncher.ini",
           "[Settings]\nModules_Path=\n\n[7z]\n" + (f"7z_Games_to_Keep={keep}\n" if keep is not None else ""))
    # Module= is a Windows path relative to Modules\<emulator>, as RocketLauncher resolves it.
    module_path = Path(os.path.normpath(rl / "Modules" / emulator / Path(*PureWindowsPath(module).parts)))
    _write(module_path, module_text)
    _write(module_path.parent / f"{module_path.stem}.ini", "[Settings]\nFullscreen=true\n" + module_ini)
    _write(module_path.parent / "ZipMapping" / f"{system}.ini", "[mapping]\n" + mapping)
    _write(rl / "Modules" / "ScummVM" / "ScummVM.ahk", 'MEmu := "ScummVM"\n')
    _write(hs / "Emulators" / "DOSBox" / "dosbox.exe", "MZ")
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl), roms_dir=str(tmp_path / "Games"))
    return cfg, rl, tmp_path / "Games" / system


def _conf(folder, short, name="dosbox.conf", config_dir="!dos"):
    return _write(folder / config_dir / short / name, "[autoexec]\nmount c .\\games\\" + short + "\n")


def _wheel(cfg, name=MSDOS):
    result = health.check_dosbox_game_configs(cfg)
    return next(c for c in result.children if c.name == name)


def _row(node, name):
    rows = [c for c in node.children if c.name == name]
    return rows[0] if rows else None


# ─── basics ──────────────────────────────────────────────────────────────────


def test_info_without_rocketlauncher_or_hyperspin_dir(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, ["Abuse (1995)"])
    cfg.rocketlauncher_dir = ""
    assert health.check_dosbox_game_configs(cfg).status == INFO
    cfg, _rl, _f = _cabinet(tmp_path / "b", ["Abuse (1995)"])
    cfg.hyperspin_dir = str(tmp_path / "missing")
    assert health.check_dosbox_game_configs(cfg).status == INFO


def test_info_when_no_wheel_uses_the_module(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, ["Sam and Max"], system="ScummVM", default_emulator="ScummVM")
    result = health.check_dosbox_game_configs(cfg)
    assert result.status == INFO
    assert "no wheels start games with the eXoDOS DOSBox module" in result.detail
    assert result.children == []


def test_other_dosbox_modules_are_not_checked(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, ["Abuse (1995)"], module_text=PLAIN_MODULE)
    result = health.check_dosbox_game_configs(cfg)
    assert result.status == INFO
    assert result.children == []


def test_registered_in_doctor(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, [])
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert names.index("DOSBox game configs") == names.index("Future Pinball scripting") + 1


# ─── configs ─────────────────────────────────────────────────────────────────


def test_ok_when_every_game_has_its_config(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Abuse (1995)", "DOOM (1993)"])
    _conf(folder, "Abuse (1995)")
    _conf(folder, "DOOM (1993)")
    node = _wheel(cfg)
    assert node.status == OK
    assert node.children == []
    assert "2 games OK" in node.detail
    assert health.check_dosbox_game_configs(cfg).status == OK


def test_warn_names_games_without_a_config(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Abuse (1995)", "DOOM (1993)"])
    _conf(folder, "Abuse (1995)")
    node = _wheel(cfg)
    row = _row(node, "Configs")
    assert node.status == WARN and row.status == WARN
    assert "1/2 games won't start" in row.detail
    assert "DOOM (1993)" in row.detail and "Abuse" not in row.detail
    assert str(folder / "!dos" / "DOOM (1993)" / "dosbox.conf") in row.detail
    assert str(rl / "Modules" / "DOSBox" / "ZipMapping" / f"{MSDOS}.ini") in row.fix
    assert health.check_dosbox_game_configs(cfg).status == WARN


def test_zipmapping_short_name_is_used(tmp_path):
    game = "Indiana Jones and the Fate of Atlantis (1992)"
    # Keys match case-insensitively, as Windows' IniRead does.
    cfg, _rl, folder = _cabinet(tmp_path, [game], mapping=f"{game.lower()}=indy4\n")
    _conf(folder, "IndiJFoA")  # a config filed under another name
    row = _row(_wheel(cfg), "Configs")
    assert row is not None and str(folder / "!dos" / "indy4" / "dosbox.conf") in row.detail
    _conf(folder, "INDY4")  # folder names match case-insensitively too
    node = _wheel(cfg)
    assert node.status == OK and "1 games OK" in node.detail


def test_config_folder_and_conf_file_settings(tmp_path):
    module_ini = "Config_Folder=..\\Configs\\DOS\nConf_File=game.conf\n\n[DOOM (1993)]\nConf_File=doom.conf\n"
    cfg, rl, _folder = _cabinet(tmp_path, ["Abuse (1995)", "DOOM (1993)"], module_ini=module_ini)
    configs = rl.parent / "Configs" / "DOS"  # relative to the RocketLauncher folder
    _write(configs / "Abuse (1995)" / "game.conf")
    _write(configs / "DOOM (1993)" / "game.conf")  # the game's own section wins
    row = _row(_wheel(cfg), "Configs")
    assert row is not None and "1/2" in row.detail
    assert str(configs / "DOOM (1993)" / "doom.conf") in row.detail
    _write(configs / "DOOM (1993)" / "doom.conf")
    assert _wheel(cfg).status == OK


def test_windows_system_uses_win3x(tmp_path):
    system = "Microsoft Windows 3.x"
    cfg, _rl, folder = _cabinet(tmp_path, ["SkiFree (1991)"], system=system)
    _conf(folder, "SkiFree (1991)")  # in !dos, where a Windows system doesn't look
    assert _wheel(cfg, system).status == WARN
    _conf(folder, "SkiFree (1991)", config_dir="!win3x")
    assert _wheel(cfg, system).status == OK


def test_renamed_module_through_module_path(tmp_path):
    cfg, rl, folder = _cabinet(
        tmp_path, ["Abuse (1995)"], emulator="DOSBox SVN", module="..\\DOSBox\\DOSBox (Alt+Enter).ahk",
        module_ini="Conf_File=alt.conf\n")
    assert (rl / "Modules" / "DOSBox" / "DOSBox (Alt+Enter).ini").is_file()
    _conf(folder, "Abuse (1995)")
    row = _row(_wheel(cfg), "Configs")
    assert row is not None and "alt.conf" in row.detail  # read from the renamed module's own INI
    _conf(folder, "Abuse (1995)", name="alt.conf")
    assert _wheel(cfg).status == OK


def test_games_ini_overrides(tmp_path):
    games_ini = "[DOOM (1993)]\nEmulator=ScummVM\n"
    cfg, _rl, folder = _cabinet(tmp_path, ["Abuse (1995)", "DOOM (1993)"], games_ini=games_ini)
    _conf(folder, "Abuse (1995)")
    node = _wheel(cfg)  # DOOM starts on ScummVM here, so its missing config doesn't matter
    assert node.status == OK and "1 games OK" in node.detail

    cfg, rl, _f = _cabinet(tmp_path / "b", ["Sam and Max"], system="ScummVM", default_emulator="ScummVM",
                           games_ini="[Sam and Max]\nEmulator=DOSBox\n")
    row = _row(_wheel(cfg, "ScummVM"), "Configs")
    assert row is not None and "Sam and Max" in row.detail


def test_unfound_game_is_counted_not_warned(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Abuse (1995)", "DOOM (1993)"])
    _conf(folder, "Abuse (1995)")
    (folder / "DOOM (1993).zip").unlink()
    node = _wheel(cfg)
    assert node.status == OK and _row(node, "Configs") is None
    assert "1 not found by RocketLauncher" in node.detail


def test_unpacked_sets(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Abuse (1995)", "DOOM (1993)"], seven="false", zips=False,
                                mapping="DOOM (1993)=doom\n")
    (folder / "Abuse (1995)").mkdir()
    _conf(folder, "Abuse (1995)")
    node = _wheel(cfg)
    row = _row(node, "Game folders")
    assert row is not None and row.status == WARN
    assert "DOOM (1993) [doom]" in row.detail and "Abuse" not in row.detail
    (folder / "doom").mkdir()
    row = _row(_wheel(cfg), "Configs")
    assert row is not None and str(folder / "!dos" / "doom" / "dosbox.conf") in row.detail


def test_hidden_wheel_capped_at_info(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, ["Abuse (1995)"], hidden=(MSDOS,))
    result = health.check_dosbox_game_configs(cfg)
    node = result.children[0]
    assert node.name == f"{MSDOS} (hidden on the Main Menu)"
    assert node.status == INFO and _row(node, "Configs").status == INFO
    assert result.status == INFO


# ─── saves ───────────────────────────────────────────────────────────────────


def test_saves_info_when_each_game_is_deleted(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Abuse (1995)"], delete_temp="true")
    _conf(folder, "Abuse (1995)")
    node = _wheel(cfg)
    row = _row(node, "Saves")
    assert row is not None and row.status == INFO and node.status == INFO
    assert "7z_Delete_Temp=true" in row.detail
    assert str(rl / "Settings" / MSDOS / "RocketLauncher.ini") in row.fix


def test_saves_info_names_games_to_keep(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Abuse (1995)"], keep="1")
    _conf(folder, "Abuse (1995)")
    row = _row(_wheel(cfg), "Saves")
    assert row is not None and row.status == INFO
    assert "only the newest unpacked game keeps its folder" in row.detail
    assert "7z_Games_to_Keep=1" in row.detail and str(rl / "Settings" / "RocketLauncher.ini") in row.detail
    assert "sevenZGamesToKeep" in row.fix and "DOSBox.ahk" in row.fix
    cfg, _rl, folder = _cabinet(tmp_path / "b", ["Abuse (1995)"], keep="3")
    _conf(folder, "Abuse (1995)")
    assert "only the 3 newest unpacked games keep their folders" in _row(_wheel(cfg), "Saves").detail


def test_no_saves_note_when_games_are_kept(tmp_path):
    # 7z_Delete_Temp=false and no 7z_Games_to_Keep: nothing is deleted.
    cfg, _rl, folder = _cabinet(tmp_path, ["Abuse (1995)"])
    _conf(folder, "Abuse (1995)")
    assert _row(_wheel(cfg), "Saves") is None
    # The module decides itself.
    cfg, _rl, folder = _cabinet(tmp_path / "b", ["Abuse (1995)"], keep="1",
                                module_text=EXODOS_MODULE + 'sevenZGamesToKeep := ""\n')
    _conf(folder, "Abuse (1995)")
    assert _row(_wheel(cfg), "Saves") is None
    # 7z off: nothing is unpacked.
    cfg, _rl, folder = _cabinet(tmp_path / "c", ["Abuse (1995)"], seven="false", zips=False, keep="1")
    (folder / "Abuse (1995)").mkdir()
    _conf(folder, "Abuse (1995)")
    assert _row(_wheel(cfg), "Saves") is None
