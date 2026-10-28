"""`audit` finds ROM files where RocketLauncher looks for them.

``audit_system`` used to look only in ``<roms_dir>/<System>`` with SpinDoctor's
own per-system extension guess, while RocketLauncher launches each game from
the wheel's ``Rom_Path`` (``|``-separated, relative entries resolved from the
RocketLauncher folder) with its ``Rom_Extension`` list.  Each test builds a
small HyperSpin + RocketLauncher tree in a temp dir.
"""
from __future__ import annotations

import csv
import os

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import audit
from spindoctor.audit import audit_system, scan_roms
from spindoctor.cli import cli
from spindoctor.config import Config, save_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep the real ~/.spindoctor (and its system overrides) out of the tests."""
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json")
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _touch(folder, *names):
    for name in names:
        _write(folder / name, "rom")


def _cabinet(tmp_path, wheels):
    """HyperSpin + RocketLauncher dirs; *wheels* maps wheel name -> DB game names.
    ROMs go under ``<tmp>/Games``, which is also ``roms_dir``."""
    hs = tmp_path / "HyperSpin"
    rl = tmp_path / "RocketLauncher"
    roms = tmp_path / "Games"
    (rl / "Settings").mkdir(parents=True)
    roms.mkdir()
    for wheel, games in wheels.items():
        xml = "".join(f'<game name="{g}"/>' for g in games)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    return cfg, rl, roms


def _emulators_ini(rl, system, rom_path, emulator="Emu", extra="", rom_ext=None):
    """Folder-layout ``Settings/<System>/Emulators.ini``; *rom_ext* goes in an
    ``[<emulator>]`` section, where RocketLauncher reads it."""
    if rom_ext is not None:
        extra += f"\n[{emulator}]\nRom_Extension={rom_ext}\n"
    return _write(
        rl / "Settings" / system / "Emulators.ini",
        f"[ROMS]\nDefault_Emulator={emulator}\nRom_Path={rom_path}\n{extra}",
    )


def _audit(cfg, system, **kwargs):
    return audit_system(system, cfg, check_media_flag=False, check_mame_controls=False, **kwargs)


def _names(entries):
    return sorted(e.rom_name for e in entries)


# ─── where the ROMs are ──────────────────────────────────────────────────────


def test_rom_path_pointing_at_a_roms_subfolder(tmp_path):
    """Dreamcast keeps every game in <System>\\roms; the old scan listed only
    <roms_dir>\\Sega Dreamcast and reported 0 ROMs."""
    games = ["Crazy Taxi (USA)", "Jet Grind Radio (USA)", "Shenmue (USA) (Disc 1)"]
    cfg, rl, roms = _cabinet(tmp_path, {"Sega Dreamcast": games})
    dc = roms / "Sega Dreamcast"
    _touch(dc / "roms", *(g + ".cdi" for g in games), "Homebrew Demo.cdi", "readme.txt")
    _touch(dc / "BIOS", "dc_boot.bin")
    _emulators_ini(rl, "Sega Dreamcast", dc / "roms", emulator="NullDC")
    _write(rl / "Settings" / "Global Emulators.ini", "[NullDC]\nRom_Extension=gdi|cdi|chd\n")

    result = _audit(cfg, "Sega Dreamcast")
    assert result.total_roms == 4
    assert result.roms_in_db == 3
    assert result.db_entries_no_rom == 0
    assert _names(result.roms_only) == ["Homebrew Demo"]
    taxi = next(e for e in result.entries if e.rom_name == "Crazy Taxi (USA)")
    assert taxi.rom_path == dc / "roms" / "Crazy Taxi (USA).cdi"
    # scan_roms() itself still means <roms_dir>/<System>, for its other callers.
    assert scan_roms("Sega Dreamcast", roms) == {}


def test_multi_path_rom_path_searches_every_folder(tmp_path):
    games = ["Ape Escape (USA)", "Final Fantasy VII (USA) (Disc 1)", "Point Blank (USA)"]
    cfg, rl, roms = _cabinet(tmp_path, {"Sony Playstation": games})
    psx = roms / "Sony Playstation"
    _touch(psx, "Ape Escape (USA).chd")
    _touch(psx / "MultiDisc", "Final Fantasy VII (USA) (Disc 1).chd")
    _touch(psx / "_Gun Games", "Point Blank (USA).chd")
    _emulators_ini(
        rl, "Sony Playstation", f"{psx}|{psx / 'MultiDisc'}|{psx / '_Gun Games'}",
        rom_ext="chd|cue",
    )

    result = _audit(cfg, "Sony Playstation")
    assert result.roms_in_db == 3
    assert result.db_entries_no_rom == 0
    assert result.roms_not_in_db == 0


def test_relative_rom_path_resolves_from_rocketlauncher_dir(tmp_path):
    """``..\\Games\\NES`` resolves from the RocketLauncher folder, and the folder
    isn't named after the wheel, so <roms_dir>\\<System> doesn't even exist."""
    games = ["Contra (USA)", "Metroid (USA)"]
    cfg, rl, roms = _cabinet(tmp_path, {"Nintendo Entertainment System": games})
    _touch(roms / "NES", "Contra (USA).nes", "Metroid (USA).zip")
    _emulators_ini(
        rl, "Nintendo Entertainment System", "..\\Games\\NES", rom_ext="nes|zip",
    )

    result = _audit(cfg, "Nintendo Entertainment System")
    assert result.roms_in_db == 2
    assert result.db_entries_no_rom == 0


def test_game_in_its_own_named_folder(tmp_path):
    """RocketLauncher also launches <path>\\<name>\\<name>.<ext>."""
    cfg, rl, roms = _cabinet(tmp_path, {"Apple II": ["Oregon Trail", "Karateka"]})
    a2 = roms / "Apple II"
    _touch(a2, "Karateka.dsk")
    _touch(a2 / "Oregon Trail", "Oregon Trail.dsk", "Oregon Trail (Side B).dsk")
    _touch(a2 / "Lode Runner", "LODE RUNNER.DSK")  # a game folder the DB doesn't list
    _touch(a2 / "Utilities", "copy2plus.dsk")      # no Utilities.dsk inside: not a game
    _emulators_ini(rl, "Apple II", a2, rom_ext="dsk|zip")

    result = _audit(cfg, "Apple II")
    assert result.roms_in_db == 2
    assert result.db_entries_no_rom == 0
    assert _names(result.roms_only) == ["Lode Runner"]
    trail = next(e for e in result.entries if e.rom_name == "Oregon Trail")
    assert trail.rom_path == a2 / "Oregon Trail" / "Oregon Trail.dsk"


def test_rom_extension_comes_from_rocketlauncher(tmp_path):
    """RocketLauncher's Rom_Extension decides what's a ROM, not SpinDoctor's
    per-system guess: a .pbp it launches counts, a stray .bin it won't doesn't."""
    games = ["Ape Escape (USA)", "Crash Bandicoot (USA)"]
    cfg, rl, roms = _cabinet(tmp_path, {"Sony Playstation": games})
    psx = roms / "Sony Playstation"
    _touch(psx, "Ape Escape (USA).pbp", "Crash Bandicoot (USA).cue",
           "Crash Bandicoot (USA).bin", "Stray Track (USA).bin")
    _emulators_ini(rl, "Sony Playstation", psx, emulator="ePSXe")
    _write(rl / "Settings" / "Global Emulators.ini", "[ePSXe]\nRom_Extension=pbp|cue\n")

    result = _audit(cfg, "Sony Playstation")
    assert result.roms_in_db == 2
    assert result.roms_only == []


def test_rom_match_extension_finds_any_file_in_the_game_folder(tmp_path):
    cfg, rl, roms = _cabinet(tmp_path, {"SNES CD": ["Secret of Mana (Proto)"]})
    snes_cd = roms / "SNES CD"
    _touch(snes_cd / "Secret of Mana (Proto)" / "tracks", "disc.cue")
    _emulators_ini(rl, "SNES CD", snes_cd, rom_ext="cue|chd")
    _write(rl / "Settings" / "SNES CD" / "RocketLauncher.ini",
           "[Settings]\nRom_Match_Extension=true\n")

    result = _audit(cfg, "SNES CD")
    assert result.roms_in_db == 1
    [entry] = result.matched
    assert entry.rom_path == snes_cd / "Secret of Mana (Proto)" / "tracks" / "disc.cue"


def test_games_ini_system_override(tmp_path):
    """A mixed wheel sends games elsewhere with Games.ini: System= uses that
    system's Rom_Path, Emulator= that emulator's Rom_Extension."""
    cfg, rl, roms = _cabinet(tmp_path, {
        "Driving Games": ["outrun", "daytona", "initd"],
        "Sega Model 2": ["daytona", "srallyc"],
    })
    mame = roms / "MAME"
    model2 = roms / "Sega Model 2"
    _touch(mame, "outrun.zip", "initd.dat")
    _touch(model2, "daytona.zip", "srallyc.zip")
    _emulators_ini(rl, "Driving Games", mame, emulator="MAME")
    _emulators_ini(rl, "Sega Model 2", model2, emulator="Model 2")
    _write(
        rl / "Settings" / "Global Emulators.ini",
        "[MAME]\nRom_Extension=zip|7z\n[Model 2]\nRom_Extension=zip\n"
        "[Demul]\nRom_Extension=dat|zip\n",
    )
    _write(
        rl / "Settings" / "Driving Games" / "Games.ini",
        "<!--Paste alternateemulator Output Below Here-->\n"
        "[daytona]\nEmulator=Model 2\nSystem=Sega Model 2\n"
        "[initd]\nEmulator=Demul\n",
    )

    result = _audit(cfg, "Driving Games")
    assert result.roms_in_db == 3
    assert result.db_entries_no_rom == 0
    # Sega Model 2's other games are that wheel's business, not this one's.
    assert _names(result.entries) == ["daytona", "initd", "outrun"]


def test_system_override_uses_that_systems_rom_match_extension(tmp_path):
    """With System=, RL reads the other system's RocketLauncher.ini too, so its
    Rom_Match_Extension decides, not the wheel's."""
    cfg, rl, roms = _cabinet(tmp_path, {"Driving Games": ["srally2"]})
    mame = roms / "MAME"
    model2 = roms / "Sega Model 2"
    _touch(model2 / "srally2" / "disk", "track1.zip")
    _emulators_ini(rl, "Driving Games", mame, emulator="MAME", rom_ext="zip")
    _emulators_ini(rl, "Sega Model 2", model2, emulator="Model 2", rom_ext="zip")
    _write(rl / "Settings" / "Driving Games" / "Games.ini", "[srally2]\nSystem=Sega Model 2\n")
    _write(rl / "Settings" / "Sega Model 2" / "RocketLauncher.ini",
           "[Settings]\nRom_Match_Extension=true\n")

    result = _audit(cfg, "Driving Games")
    assert result.roms_in_db == 1
    [entry] = result.matched
    assert entry.rom_path == model2 / "srally2" / "disk" / "track1.zip"


def test_name_with_trailing_space_is_looked_up_as_written(tmp_path):
    """load_database strips names, but RL launches the XML name as written:
    "Super Hack - Type V2 " is Super Hack - Type V2 .nes, not a ROM missing
    from the database plus a database game with no ROM."""
    cfg, rl, roms = _cabinet(tmp_path, {"NES Hacks": ["Super Hack - Type V2 ", "Plain Hack"]})
    hacks = roms / "Hacks"
    _touch(hacks, "Super Hack - Type V2 .nes", "Plain Hack.nes")
    _emulators_ini(rl, "NES Hacks", hacks, rom_ext="nes")

    result = _audit(cfg, "NES Hacks")
    assert result.roms_in_db == 2
    assert result.roms_only == []
    assert result.db_only == []
    hack = next(e for e in result.entries if e.rom_name == "Super Hack - Type V2")
    assert hack.rom_path == hacks / "Super Hack - Type V2 .nes"


# ─── a folder several wheels share ───────────────────────────────────────────


def _shared_mame_cabinet(tmp_path):
    """Three wheels with Rom_Path pointing at one MAME folder."""
    cfg, rl, roms = _cabinet(tmp_path, {
        "MAME": ["1942", "sf2", "xmen"],
        "Fighting Games": ["sf2", "mk2"],
        "4-Player Games": ["xmen", "xmenxbox"],
    })
    mame = roms / "MAME"
    _touch(mame, "1942.zip", "sf2.zip", "xmen.zip", "pacman.zip", "galaga.zip", "xmenxbox.txt")
    for wheel in ("MAME", "Fighting Games", "4-Player Games"):
        _emulators_ini(rl, wheel, mame, emulator="MAME")
    _write(rl / "Settings" / "Global Emulators.ini", "[MAME]\nRom_Extension=zip|7z|txt\n")
    return cfg, mame


def test_shared_folder_only_supplies_the_wheels_own_games(tmp_path):
    cfg, mame = _shared_mame_cabinet(tmp_path)
    index = audit.RomPathIndex(cfg)

    fighting = _audit(cfg, "Fighting Games", rom_index=index)
    assert fighting.total_roms == 1
    assert fighting.roms_in_db == 1
    assert _names(fighting.db_only) == ["mk2"]
    # Not "ROMs not in DB: 5" for every other game in the MAME folder.
    assert fighting.roms_only == []
    assert fighting.fuzzy_matches == []
    assert list(fighting.shared_rom_folders) == [str(mame)]
    assert sorted(fighting.shared_rom_folders[str(mame)]) == ["4-Player Games", "MAME"]

    # An alternate name's empty .txt placeholder is its ROM (txt is in Rom_Extension).
    four = _audit(cfg, "4-Player Games", rom_index=index)
    assert four.roms_in_db == 2
    assert four.roms_only == []

    # The wheel the folder is named after still gets the full listing.
    full = _audit(cfg, "MAME", rom_index=index)
    assert full.shared_rom_folders == {}
    assert _names(full.roms_only) == ["galaga", "pacman", "xmenxbox"]


def test_one_index_lists_a_shared_folder_once(tmp_path, monkeypatch):
    cfg, mame = _shared_mame_cabinet(tmp_path)
    listed = []
    real_scandir = os.scandir

    def counting_scandir(path="."):
        listed.append(os.path.normcase(str(path)))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", counting_scandir)
    index = audit.RomPathIndex(cfg)
    for wheel in ("MAME", "Fighting Games", "4-Player Games"):
        _audit(cfg, wheel, rom_index=index)
    assert listed.count(os.path.normcase(str(mame))) == 1


def test_audit_command_reports_the_shared_folder(tmp_path):
    """Console row and CSV: the shared folder's other ROMs aren't rows."""
    cfg, _mame = _shared_mame_cabinet(tmp_path)
    save_config(cfg)
    report = tmp_path / "audit.csv"

    result = CliRunner().invoke(
        cli, ["audit", "--system", "Fighting Games", "--no-media", "--report", str(report)],
    )
    assert result.exit_code == 0, result.output
    assert "Shared ROM folder" in result.output
    with open(report, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["rom_name"]: r["rom_exists"] for r in rows} == {"mk2": "False", "sf2": "True"}


# ─── unchanged without RocketLauncher settings ───────────────────────────────


def _dreamcast_split(tmp_path):
    """One game in <roms_dir>\\Sega Dreamcast, the other in its roms\\ folder."""
    games = ["Crazy Taxi (USA)", "Jet Grind Radio (USA)"]
    cfg, rl, roms = _cabinet(tmp_path, {"Sega Dreamcast": games})
    dc = roms / "Sega Dreamcast"
    _touch(dc, "Crazy Taxi (USA).cdi")
    _touch(dc / "roms", "Jet Grind Radio (USA).cdi")
    return cfg, rl, dc


def test_without_rocketlauncher_audit_scans_roms_dir(tmp_path):
    cfg, rl, dc = _dreamcast_split(tmp_path)
    _emulators_ini(rl, "Sega Dreamcast", dc / "roms")
    cfg.rocketlauncher_dir = ""

    result = _audit(cfg, "Sega Dreamcast")
    assert _names(result.matched) == ["Crazy Taxi (USA)"]
    assert _names(result.db_only) == ["Jet Grind Radio (USA)"]


@pytest.mark.parametrize("settings", ["no settings file", "blank Rom_Path"])
def test_system_without_a_rom_path_scans_roms_dir(tmp_path, settings):
    cfg, rl, dc = _dreamcast_split(tmp_path)
    if settings == "blank Rom_Path":
        _emulators_ini(rl, "Sega Dreamcast", "")

    result = _audit(cfg, "Sega Dreamcast")
    assert _names(result.matched) == ["Crazy Taxi (USA)"]
    assert _names(result.db_only) == ["Jet Grind Radio (USA)"]


def test_recursive_scan_pc_library_keeps_spindoctor_scan(tmp_path):
    """A PC library set up with recursive_scan is audited by its install
    folders, not by its PCLauncher placeholder-INI Rom_Path."""
    cfg, rl, roms = _cabinet(tmp_path, {"PC Games": ["Hades", "Celeste"]})
    _touch(roms / "PC Games" / "Hades", "Hades.exe")
    _touch(roms / "PC Games" / "Celeste", "Celeste.exe")
    pcl = rl / "Modules" / "PCLauncher" / "PC Games"
    _touch(pcl, "Hades.ini")
    _emulators_ini(rl, "PC Games", pcl, emulator="PCLauncher", rom_ext="ini")
    cfg.system_overrides = {"PC Games": {"rom_extensions": [".exe"], "recursive_scan": True}}
    save_config(cfg)

    result = _audit(cfg, "PC Games")
    assert result.roms_in_db == 2
    assert result.db_entries_no_rom == 0


def test_no_extension_to_try_keeps_spindoctor_scan(tmp_path):
    """When RocketLauncher has no extension to try (here the emulator sets no
    Rom_Extension, so RL stops before looking), the audit keeps scanning
    <roms_dir>\\<System> rather than reporting every game missing."""
    cfg, rl, roms = _cabinet(tmp_path, {"Nintendo Entertainment System": ["Contra (USA)"]})
    _touch(roms / "Nintendo Entertainment System", "Contra (USA).nes")
    _emulators_ini(rl, "Nintendo Entertainment System", roms / "NES (unused)", emulator="Nestopia")
    _write(rl / "Settings" / "Global Emulators.ini", "[Nestopia]\nEmu_Path=..\\Emulators\\nestopia.exe\n")

    result = _audit(cfg, "Nintendo Entertainment System")
    assert _names(result.matched) == ["Contra (USA)"]
