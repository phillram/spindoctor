"""Tests for the `doctor` Casual Games check (``health.check_casual_games``).

RocketLauncher's Casual Games module (PopCap and Big Fish Games wheels) starts
each game's own ``.exe``: ``gamePath`` under ``[<romName>]`` in its module
INIs, else ``<romPath>\\<romName>.exe``, else
``<romPath>\\<romName>\\<romName>.exe``, with ``romPath`` / ``romName`` as
RocketLauncher's ROM search left them.  Each test builds a small HyperSpin +
RocketLauncher cabinet in a temp dir, laid out like a real one: the module
INIs beside ``Casual Games.ahk``, ``Rom_Extension=txt|exe`` with 7-Zip's
extensions in front, ``Skipchecks=Rom and Emu`` and ``Rom_Match_Extension``
on, and each game in ``<Rom_Path>\\<game>\\`` with an empty ``<game>.txt``
placeholder beside it.
"""
from __future__ import annotations

from spindoctor import health
from spindoctor.config import Config
from spindoctor.rl_rom_paths import _RomLookup

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO

SEVEN_Z = "zip|rar|7z|lha|lzh|gzip|tar"


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    # RocketLauncher's INIs are CRLF files.
    path.write_bytes(text.replace("\n", "\r\n").encode("cp1252"))
    return path


def _cabinet(tmp_path, games, system="PopCap", rom_path=None, match_ext="true", skipchecks="Rom and Emu",
             other_wheels=None, hidden=()):
    """A cabinet whose *system* wheel lists *games* and launches them with the
    Casual Games module.  The RocketLauncher folder is ``<tmp>\\Arcade\\RocketLauncher``,
    so a relative ``..\\Games\\…`` gamePath means ``<tmp>\\Arcade\\Games\\…``; the
    games themselves are in ``<tmp>\\Games\\<system>``."""
    hs = tmp_path / "Arcade"
    rl = hs / "RocketLauncher"
    folder = tmp_path / "Games" / system
    folder.mkdir(parents=True, exist_ok=True)
    wheels = {system: games, **(other_wheels or {})}
    menu = "".join(
        f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>' for w in wheels
    )
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, names in wheels.items():
        xml = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in names)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    _write(rl / "Settings" / "Global Emulators.ini",
           "[Casual Games]\nEmu_Path=..\\Emulators\\PCLauncher\\PCLauncher.exe\n"
           "Rom_Extension=txt|exe\nModule=Casual Games.ahk\n\n"
           "[Nestopia]\nEmu_Path=..\\Emulators\\Nestopia\\nestopia.exe\nRom_Extension=nes|zip\n")
    _write(rl / "Settings" / system / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator=Casual Games\nRom_Path={rom_path or folder}\n")
    _write(rl / "Settings" / system / "RocketLauncher.ini",
           f"[Settings]\nSkipchecks={skipchecks}\nRom_Match_Extension=use_global\n")
    _write(rl / "Settings" / "Global RocketLauncher.ini",
           f"[Settings]\nRom_Match_Extension={match_ext}\n\n[7z]\n7z_Enabled=true\n7z_Extensions={SEVEN_Z}\n")
    _write(rl / "Modules" / "Casual Games" / "Casual Games.ahk", 'MEmu := "Casual Games"\n')
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    return cfg, rl, folder


def _game(folder, name, exe=None, placeholder=True, extra=()):
    """``<folder>\\<name>\\<exe>`` (default ``<name>.exe``), any *extra* files
    (paths inside the game's folder), and the empty ``<name>.txt``."""
    _write(folder / name / (exe or f"{name}.exe"), "MZ")
    for rel in extra:
        _write(folder / name / rel, "x")
    if placeholder:
        _write(folder / f"{name}.txt")


def _module_ini(rl, name, sections):
    """``Modules\\Casual Games\\<name>.ini`` with ``{section: gamePath}``."""
    text = "".join(f"[{s}]\ngamePath={p}\n\n" for s, p in sections.items())
    return _write(rl / "Modules" / "Casual Games" / f"{name}.ini", "[Settings]\nremapWinKeys=true\n\n" + text)


def _wheel(cfg, name="PopCap"):
    result = health.check_casual_games(cfg)
    return next(c for c in result.children if c.name == name)


def _row(node, name):
    rows = [c for c in node.children if c.name == name]
    return rows[0] if rows else None


# ─── basics ──────────────────────────────────────────────────────────────────


def test_info_without_rocketlauncher_or_hyperspin_dir(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, ["Alchemy Deluxe"])
    cfg.rocketlauncher_dir = ""
    assert health.check_casual_games(cfg).status == INFO
    cfg, _rl, _f = _cabinet(tmp_path / "b", ["Alchemy Deluxe"])
    cfg.hyperspin_dir = str(tmp_path / "missing")
    assert health.check_casual_games(cfg).status == INFO


def test_info_when_no_wheel_uses_the_module(tmp_path):
    cfg, rl, _f = _cabinet(tmp_path, ["Alchemy Deluxe"])
    _write(rl / "Settings" / "PopCap" / "Emulators.ini", "[ROMS]\nDefault_Emulator=Nestopia\nRom_Path=x\n")
    result = health.check_casual_games(cfg)
    assert result.status == INFO
    assert "no Casual Games" in result.detail
    assert result.children == []


def test_registered_in_doctor(tmp_path):
    cfg, _rl, _f = _cabinet(tmp_path, [])
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert "Casual Games" in names
    assert names.index("Casual Games") == names.index("PC games") + 1


def test_games_found_by_gamepath_or_by_name_are_ok(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Alchemy Deluxe", "Cosmic Bugs", "Water Bugs"])
    _game(folder, "Alchemy Deluxe")                       # <Rom_Path>\<game>\<game>.exe
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")    # needs gamePath
    _game(folder, "Water Bugs", exe="WaterBugs.exe")
    _module_ini(rl, "PopCap", {
        "Cosmic Bugs": folder / "Cosmic Bugs" / "CosmicBugs.exe",
        "Water Bugs": folder / "Water Bugs" / "WaterBugs.exe",
    })
    result = health.check_casual_games(cfg)
    node = _wheel(cfg)
    assert result.status == OK
    assert node.status == OK
    assert node.detail == "3 games OK"
    assert node.children == []


def test_relative_gamepath_starts_from_the_rocketlauncher_folder(tmp_path):
    cfg, rl, _folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    # ..\Games\PopCap\... is <tmp>\Arcade\Games\PopCap\..., beside RocketLauncher.
    _write(tmp_path / "Arcade" / "Games" / "PopCap" / "Cosmic Bugs" / "CosmicBugs.exe", "MZ")
    _module_ini(rl, "PopCap", {"Cosmic Bugs": "..\\Games\\PopCap\\Cosmic Bugs\\CosmicBugs.exe"})
    assert _wheel(cfg).status == OK


# ─── the program paths ───────────────────────────────────────────────────────


def test_gamepath_into_a_gone_folder_is_a_warn_listing_the_games(tmp_path):
    """The real failure: every gamePath said ..\\Games\\PopCap\\…, a folder that had
    moved to another drive.  Games whose program is named after the game still
    start through the module's fallback; the others can't."""
    names = ["Alchemy Deluxe", "Cosmic Bugs", "Mummy Maze Deluxe", "Water Bugs"]
    cfg, rl, folder = _cabinet(tmp_path, names)
    _game(folder, "Alchemy Deluxe")
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    _game(folder, "Mummy Maze Deluxe", exe="WinMM.exe")
    _game(folder, "Water Bugs", exe="WaterBugs.exe")
    ini = _module_ini(rl, "PopCap", {
        "Alchemy Deluxe": "..\\Games\\PopCap\\Alchemy Deluxe\\Alchemy Deluxe.exe",
        "Cosmic Bugs": "..\\Games\\PopCap\\Cosmic Bugs\\CosmicBugs.exe",
        "Mummy Maze Deluxe": "..\\Games\\PopCap\\Mummy Maze Deluxe\\WinMM.exe",
        "Water Bugs": "..\\Games\\PopCap\\Water Bugs\\WaterBugs.exe",
    })
    node = _wheel(cfg)
    programs = _row(node, "Programs")
    assert node.status == WARN
    assert programs.status == WARN
    assert programs.detail.startswith("3/4 games won't start")
    assert "Cosmic Bugs, Mummy Maze Deluxe, Water Bugs" in programs.detail
    assert "Alchemy Deluxe" not in programs.detail
    assert str(ini) in programs.fix
    gone = tmp_path / "Arcade" / "Games" / "PopCap" / "Cosmic Bugs" / "CosmicBugs.exe"
    assert str(gone) in programs.fix
    assert "relative path starts from the RocketLauncher folder" in programs.fix
    # The one that starts from Rom_Path anyway is INFO.
    stale = _row(node, "gamePath")
    assert stale.status == INFO
    assert "Alchemy Deluxe" in stale.detail
    assert stale.detail.startswith("1/4 games' gamePath points at a missing file")


def test_no_gamepath_anywhere_names_the_system_module_ini(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    programs = _row(_wheel(cfg), "Programs")
    assert programs.status == WARN
    assert "Set gamePath=<the game's .exe> under [<game>]" in programs.fix
    assert str(rl / "Modules" / "Casual Games" / "PopCap.ini") in programs.fix
    assert str(folder / "<game>" / "<game>.exe") in programs.fix


def test_exe_beside_the_placeholder_is_found(tmp_path):
    """<romPath>\\<romName>.exe: the module's first fallback."""
    cfg, _rl, folder = _cabinet(tmp_path, ["Pixelus Deluxe"])
    _write(folder / "Pixelus Deluxe.exe", "MZ")
    _write(folder / "Pixelus Deluxe.txt")
    assert _wheel(cfg).status == OK


def test_names_and_sections_match_ignoring_case(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    _write(rl / "Modules" / "Casual Games" / "PopCap.ini",
           f"[COSMIC BUGS]\nGAMEPATH={folder / 'Cosmic Bugs' / 'COSMICBUGS.EXE'}\n")
    assert _wheel(cfg).status == OK


def test_more_than_five_games_are_counted(tmp_path):
    names = [f"Game {i}" for i in range(7)]
    cfg, _rl, folder = _cabinet(tmp_path, names)
    for n in names:
        _game(folder, n, exe="prog.exe")
    programs = _row(_wheel(cfg), "Programs")
    assert programs.detail.endswith("Game 0, Game 1, Game 2, Game 3, Game 4 and 2 more")


# ─── which module INI wins ───────────────────────────────────────────────────


def _three_inis(rl, folder, rom=None, system=None, glob=None):
    if rom is not None:
        _write(rl / "Modules" / "Casual Games" / "PopCap" / "Cosmic Bugs.ini",
               f"[Cosmic Bugs]\ngamePath={rom}\n")
    if system is not None:
        _write(rl / "Modules" / "Casual Games" / "PopCap.ini", f"[Cosmic Bugs]\ngamePath={system}\n")
    if glob is not None:
        _write(rl / "Modules" / "Casual Games" / "Casual Games.ini", f"[Cosmic Bugs]\ngamePath={glob}\n")


def _status(cfg):
    return _wheel(cfg).status


def test_the_games_own_ini_comes_first(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    good, bad = folder / "Cosmic Bugs" / "CosmicBugs.exe", folder / "nope.exe"
    _three_inis(rl, folder, rom=good, system=bad, glob=bad)
    assert _status(cfg) == OK
    _three_inis(rl, folder, rom=bad, system=good, glob=good)
    assert _status(cfg) == WARN


def test_the_system_ini_comes_before_the_global_one(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    good, bad = folder / "Cosmic Bugs" / "CosmicBugs.exe", folder / "nope.exe"
    _three_inis(rl, folder, system=good, glob=bad)
    assert _status(cfg) == OK
    _three_inis(rl, folder, system=bad, glob=good)
    programs = _row(_wheel(cfg), "Programs")
    assert str(rl / "Modules" / "Casual Games" / "PopCap.ini") in programs.fix


def test_a_blank_gamepath_falls_through_to_the_next_ini(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    _three_inis(rl, folder, system="", glob=folder / "Cosmic Bugs" / "CosmicBugs.exe")
    assert _status(cfg) == OK


def test_module_setting_reports_the_file_it_read(tmp_path):
    _cfg, rl, _folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    module = rl / "Modules" / "Casual Games" / "Casual Games.ahk"
    _three_inis(rl, None, system="  ", glob="C.exe")
    look = _RomLookup(rl)
    assert look.module_setting(module, "PopCap", "Cosmic Bugs", ["Cosmic Bugs"], "gamePath") == (
        "C.exe", rl / "Modules" / "Casual Games" / "Casual Games.ini")
    assert look.module_setting(module, "PopCap", "Other", ["Other"], "gamePath") == ("", None)


def test_module_setting_reads_each_file_through_before_the_next(tmp_path):
    """moduleIni.Read(romName . "|Settings", ...): [Settings] of the system INI
    comes before [<game>] of the global one."""
    _cfg, rl, _folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    module = rl / "Modules" / "Casual Games" / "Casual Games.ahk"
    _three_inis(rl, None, glob="C.exe")
    _write(rl / "Modules" / "Casual Games" / "PopCap.ini", "[Settings]\ngamePath=S.exe\n")
    look = _RomLookup(rl)
    assert look.module_setting(module, "PopCap", "Cosmic Bugs", ["Cosmic Bugs", "Settings"], "gamePath") == (
        "S.exe", rl / "Modules" / "Casual Games" / "PopCap.ini")


# ─── the .txt placeholder trap ───────────────────────────────────────────────


def test_missing_placeholder_lets_rocketlauncher_take_another_txt(tmp_path):
    """The real failure: with no empty <game>.txt, RocketLauncher took the
    game folder's license.txt as the game (romName "license"), and the module
    stopped with 'Could not locate "license"'."""
    cfg, rl, folder = _cabinet(tmp_path, ["Alchemy Deluxe", "NingPo MahJong Deluxe"])
    _game(folder, "Alchemy Deluxe")
    _game(folder, "NingPo MahJong Deluxe", placeholder=False, extra=["license.txt", "readme.TXT"])
    node = _wheel(cfg)
    search = _row(node, "ROM search")
    assert node.status == WARN
    assert search.status == WARN
    assert search.detail.startswith("1/2 games won't start: RocketLauncher takes another file")
    assert "NingPo MahJong Deluxe: license.txt" in search.detail  # NTFS order: license before readme
    assert search.fix.startswith(f"Add an empty {folder / '<game>.txt'} for each")
    assert "NingPo MahJong Deluxe.txt" in search.fix
    assert "Rom_Match_Extension=false" in search.fix
    assert str(rl / "Settings" / "PopCap" / "RocketLauncher.ini") in search.fix
    # Found by its own name, its NingPo MahJong Deluxe.exe would start.
    assert _row(node, "Programs") is None


def test_the_placeholder_fixes_it(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["NingPo MahJong Deluxe"])
    _game(folder, "NingPo MahJong Deluxe", extra=["license.txt"])
    assert _wheel(cfg).status == OK


def test_a_stray_txt_deeper_in_the_folder_is_taken_too(tmp_path):
    """RocketLauncher's extension search (Loop, …\\*.txt,,1) goes into subfolders."""
    cfg, _rl, folder = _cabinet(tmp_path, ["Zuma Deluxe"])
    _game(folder, "Zuma Deluxe", placeholder=False, extra=["docs/manual.txt"])
    search = _row(_wheel(cfg), "ROM search")
    assert "Zuma Deluxe: manual.txt" in search.detail


def test_trapped_game_that_also_lacks_a_program_is_in_both_rows(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Typer Shark Deluxe"])
    _game(folder, "Typer Shark Deluxe", exe="TyperShark.exe", placeholder=False, extra=["license.txt"])
    node = _wheel(cfg)
    assert "Typer Shark Deluxe" in _row(node, "ROM search").detail
    assert "Typer Shark Deluxe" in _row(node, "Programs").detail


def test_no_trap_with_rom_match_extension_off(tmp_path):
    """Without Rom_Match_Extension RocketLauncher only looks for files named
    after the game, and finds <game>\\<game>.exe."""
    cfg, _rl, folder = _cabinet(tmp_path, ["NingPo MahJong Deluxe"], match_ext="false")
    _game(folder, "NingPo MahJong Deluxe", placeholder=False, extra=["license.txt"])
    assert _wheel(cfg).status == OK


def test_an_archive_in_the_game_folder_is_taken_before_any_txt(tmp_path):
    """7-Zip's extensions come first, and the module refuses archives.  A .txt
    placeholder comes too late to help, so the fix is Rom_Match_Extension."""
    cfg, _rl, folder = _cabinet(tmp_path, ["Big Money Deluxe"])
    _game(folder, "Big Money Deluxe", extra=["music.zip"])
    search = _row(_wheel(cfg), "ROM search")
    assert "Big Money Deluxe: music.zip" in search.detail
    assert search.fix.startswith("Set Rom_Match_Extension=false")
    assert ".txt" not in search.fix


def test_a_game_found_as_an_archive_is_refused(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Chuzzle Deluxe"])
    _game(folder, "Chuzzle Deluxe")
    _write(folder / "Chuzzle Deluxe.zip", "PK")
    archives = _row(_wheel(cfg), "Archives")
    assert archives.status == WARN
    assert "Chuzzle Deluxe.zip" in archives.detail
    assert "Compressed games are not supported" in archives.detail


# ─── what RocketLauncher picks ───────────────────────────────────────────────


def test_pick_follows_rocketlauncher_order(tmp_path):
    _cfg, rl, folder = _cabinet(tmp_path, ["A"])
    look = _RomLookup(rl)
    src = look.source("PopCap")
    assert src.exts == SEVEN_Z.split("|") + ["txt", "exe"]
    _write(folder / "A" / "A.exe", "MZ")
    _write(folder / "A" / "B" / "z.txt")
    _write(folder / "A" / "y.TXT")
    pick = _RomLookup(rl).pick(src, "A")
    # txt comes before exe; the folder's own files before its subfolders'.
    assert (pick.rom_dir, pick.rom_name, pick.ext, pick.by_ext) == (folder / "A", "y", "txt", True)
    _write(folder / "A" / "A.txt")
    pick = _RomLookup(rl).pick(src, "A")
    assert (pick.rom_dir, pick.rom_name, pick.by_ext) == (folder / "A", "A", False)
    _write(folder / "a.TXT")
    pick = _RomLookup(rl).pick(src, "A")
    assert (pick.folder, pick.rom_dir, pick.rom_name) == (folder, folder, "A")
    assert _RomLookup(rl).pick(src, "Missing") is None


def test_pick_tries_each_rom_path_folder_in_turn(tmp_path):
    second = tmp_path / "More"
    _cfg, rl, folder = _cabinet(tmp_path, ["A"])
    _write(rl / "Settings" / "PopCap" / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator=Casual Games\nRom_Path={folder}|{second}\n")
    _write(second / "A.zip", "PK")
    _write(folder / "A" / "A.exe", "MZ")
    look = _RomLookup(rl)
    # Every extension in the first folder before the second folder.
    assert look.pick(look.source("PopCap"), "A").ext == "exe"


# ─── which games are checked ─────────────────────────────────────────────────


def test_games_ini_emulator_override_is_followed(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Bejeweled Deluxe", "Mario"])
    _write(rl / "Settings" / "PopCap" / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator=Nestopia\nRom_Path={folder}\n")
    _write(rl / "Settings" / "PopCap" / "Games.ini", "[Bejeweled Deluxe]\nEmulator=Casual Games\n")
    _game(folder, "Bejeweled Deluxe", exe="Bejeweled.exe")
    _write(folder / "Mario.nes")
    programs = _row(_wheel(cfg), "Programs")
    assert programs.detail.startswith("1/1 games won't start")
    assert "Mario" not in programs.detail


def test_a_game_module_replaces_the_casual_games_module(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs", "Water Bugs"])
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    _game(folder, "Water Bugs", exe="WaterBugs.exe")
    _write(rl / "Modules" / "Game Modules" / "Cosmic Bugs" / "Cosmic Bugs.ahk", "; own module")
    programs = _row(_wheel(cfg), "Programs")
    assert programs.detail.startswith("1/1 games won't start")
    assert "Cosmic Bugs" not in programs.detail


def test_another_module_is_not_checked(tmp_path):
    cfg, rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"])
    _write(rl / "Settings" / "PopCap" / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator=Casual Games\nRom_Path={folder}\n\n"
           "[Casual Games]\nRom_Extension=txt|exe\nModule=My Casual Games.ahk\n")
    assert health.check_casual_games(cfg).status == INFO


def test_hidden_wheel_is_capped_at_info(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Cosmic Bugs"], hidden=("PopCap",))
    _game(folder, "Cosmic Bugs", exe="CosmicBugs.exe")
    node = _wheel(cfg, "PopCap (hidden on the Main Menu)")
    assert node.status == INFO
    assert _row(node, "Programs").status == INFO


# ─── games RocketLauncher doesn't find ───────────────────────────────────────


def test_unfound_game_without_skipchecks_is_left_to_rom_paths(tmp_path):
    cfg, _rl, folder = _cabinet(tmp_path, ["Alchemy Deluxe", "Gone"], skipchecks="false")
    _game(folder, "Alchemy Deluxe")
    node = _wheel(cfg)
    assert node.status == OK
    assert node.detail == "1 games OK; 1 not found by RocketLauncher (see ROM paths)"


def test_unfound_game_under_rom_and_emu_needs_its_gamepath(tmp_path):
    """Found nowhere, RocketLauncher carries on with romPath set to Rom_Path, so
    only gamePath can start the game."""
    cfg, rl, folder = _cabinet(tmp_path, ["Elsewhere", "Nowhere"])
    _write(tmp_path / "Other" / "Elsewhere" / "run.exe", "MZ")
    _module_ini(rl, "PopCap", {"Elsewhere": tmp_path / "Other" / "Elsewhere" / "run.exe"})
    programs = _row(_wheel(cfg), "Programs")
    assert programs.detail.startswith("1/2 games won't start")
    assert programs.detail.endswith(": Nowhere")
