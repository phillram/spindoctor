"""Tests for the `doctor` ROM paths check (``health.check_rom_paths``).

Each test builds a small HyperSpin + RocketLauncher cabinet in a temp dir and
checks what RocketLauncher would find for each wheel: the ``Rom_Path``
folders, the ``Rom_Extension`` lookup chain, ``Games.ini`` overrides, and the
hints for the usual breakages (games in a ``roms\\`` subfolder, a multi-disc
folder left out of ``Rom_Path``, deleted MAME ``.txt`` placeholders, an old
drive letter).
"""
from __future__ import annotations

import os

import pytest

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
FAIL = health.Status.FAIL
INFO = health.Status.INFO


def _write(path, text="", encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def _touch(folder, *names):
    for name in names:
        _write(folder / name)


def _cabinet(tmp_path, wheels, hidden=()):
    """HyperSpin + RocketLauncher dirs; *wheels* maps wheel name -> DB game names,
    and the wheels in *hidden* are switched off on the Main Menu."""
    hs = tmp_path / "HyperSpin"
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    menu = "".join(
        f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
        for w in wheels
    )
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, games in wheels.items():
        xml = "".join(f'<game name="{g}"/>' for g in games)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    cfg = Config(
        roms_dir=str(tmp_path / "Games"),
        hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
    )
    return cfg, rl


def _emulators_ini(rl, system, rom_path, emulator="Emu", extra="", section="ROMS", rom_ext=None):
    """Folder-layout ``Settings/<System>/Emulators.ini``; *rom_ext* goes in an
    ``[<emulator>]`` section, where RocketLauncher reads it."""
    if rom_ext is not None:
        extra += f"\n[{emulator}]\nRom_Extension={rom_ext}\n"
    return _write(
        rl / "Settings" / system / "Emulators.ini",
        f"[{section}]\nDefault_Emulator={emulator}\nRom_Path={rom_path}\n{extra}",
    )


def _global_emulators(rl, text):
    _write(rl / "Settings" / "Global Emulators.ini", text)


def _wheel(cfg, name):
    result = health.check_rom_paths(cfg)
    return next(c for c in result.children if c.name == name)


def _rows(node, name):
    return [c for c in node.children if c.name == name]


# ─── basics ──────────────────────────────────────────────────────────────────


def test_info_without_rocketlauncher_dir(tmp_path):
    cfg, _rl = _cabinet(tmp_path, {"NES": ["Mario"]})
    cfg.rocketlauncher_dir = ""
    assert health.check_rom_paths(cfg).status == INFO


def test_all_ok_wheel(tmp_path):
    games = ["Mario Kart 64 (USA)", "Star Fox 64 (USA)"]
    cfg, rl = _cabinet(tmp_path, {"Nintendo 64": games})
    n64 = tmp_path / "Games" / "Nintendo 64"
    # RL's lookup is case-insensitive (NTFS), so a re-cased file still counts.
    _touch(n64, "Mario Kart 64 (USA).z64", "STAR FOX 64 (USA).Z64")
    _emulators_ini(rl, "Nintendo 64", n64, rom_ext="7z|z64")

    result = health.check_rom_paths(cfg)
    node = next(c for c in result.children if c.name == "Nintendo 64")
    assert result.status == OK
    assert node.status == OK
    assert node.detail == "2 games OK"
    assert node.children == []


def test_synthetic_wheels_are_skipped(tmp_path):
    cfg, _rl = _cabinet(tmp_path, {"Favorites": ["Hades"], "Most Played": ["Hades"]})
    result = health.check_rom_paths(cfg)
    assert result.status == INFO
    assert result.children == []


def test_wheel_without_rocketlauncher_settings_is_info(tmp_path):
    cfg, _rl = _cabinet(tmp_path, {"GCE Vectrex": ["Mine Storm"]})
    node = _wheel(cfg, "GCE Vectrex")
    assert node.status == INFO
    assert "no RocketLauncher settings" in node.detail


def test_doctor_registers_rom_paths_check(tmp_path):
    cfg, _rl = _cabinet(tmp_path, {"NES": ["Mario"]})
    names = [c.name for c in health.run_health_checks(cfg, fix=False).checks]
    assert "ROM paths" in names


def test_read_rl_ini_is_lenient_and_case_insensitive(tmp_path):
    ini = _write(
        tmp_path / "x.ini",
        "[ROMS]\nRom_Path = A\nROM_PATH=B\n<!--Paste Output Below Here-->\n"
        "; comment\n[Game (USA) [b]]\nEmulator=X\n",
        encoding="utf-8-sig",
    )
    data = health._read_rl_ini(ini)
    assert data["roms"]["rom_path"] == "A"  # first occurrence wins, like RL
    assert data["game (usa) [b]"]["emulator"] == "X"
    assert health._read_rl_ini(tmp_path / "missing.ini") == {}


# ─── Rom_Path folders ────────────────────────────────────────────────────────


def test_games_in_roms_subfolder_names_it_in_the_fix(tmp_path):
    """Rom_Path points at the parent of the roms\\ folder holding every game."""
    games = ["Crazy Taxi (USA)", "Jet Grind Radio (USA)", "Shenmue (USA) (Disc 1)"]
    cfg, rl = _cabinet(tmp_path, {"Sega Dreamcast": games})
    dc = tmp_path / "Games" / "Sega Dreamcast"
    _touch(dc / "roms", *(g + ".cdi" for g in games))
    _touch(dc / "BIOS", "dc_boot.bin")
    _emulators_ini(rl, "Sega Dreamcast", dc, emulator="NullDC")
    _global_emulators(rl, "[NullDC]\nRom_Extension=gdi|cdi|chd\n")

    node = _wheel(cfg, "Sega Dreamcast")
    row = _rows(node, "Games")[0]
    assert node.status == FAIL
    assert row.status == FAIL  # every game is missing
    assert row.detail.startswith("3/3 games not found in Rom_Path")
    assert "Crazy Taxi (USA)" in row.detail
    # Flat game folders first: move the files up, or list the subfolder.
    assert f"Move the files up into {dc}, or add {dc / 'roms'} to Rom_Path" in row.fix
    assert "separate several folders with |" in row.fix


def test_multi_path_rom_path_searches_every_folder(tmp_path):
    games = ["Ape Escape (USA)", "Final Fantasy VII (USA) (Disc 1)"]
    cfg, rl = _cabinet(tmp_path, {"Sony Playstation": games})
    psx = tmp_path / "Games" / "Sony Playstation"
    _touch(psx, "Ape Escape (USA).chd")
    _touch(psx / "MultiDisc", "Final Fantasy VII (USA) (Disc 1).chd")
    _emulators_ini(
        rl, "Sony Playstation", f"{psx}|{psx / 'MultiDisc'}", rom_ext="chd",
    )

    node = _wheel(cfg, "Sony Playstation")
    assert node.status == OK
    assert node.detail == "2 games OK"


def test_multi_disc_folder_left_out_of_rom_path_is_hinted(tmp_path):
    games = [
        "Ape Escape (USA)",
        "Final Fantasy VII (USA) (Disc 1)",
        "Final Fantasy VII (USA) (Disc 2)",
    ]
    cfg, rl = _cabinet(tmp_path, {"Sony Playstation": games})
    psx = tmp_path / "Games" / "Sony Playstation"
    _touch(psx, "Ape Escape (USA).chd")
    _touch(psx / "MultiDisc", *(g + ".chd" for g in games[1:]))
    _emulators_ini(rl, "Sony Playstation", psx, rom_ext="chd")

    row = _rows(_wheel(cfg, "Sony Playstation"), "Games")[0]
    assert row.status == WARN  # some games missing, not all
    assert row.detail.startswith("2/3 games not found")
    assert "Final Fantasy VII (USA) (Disc 1)" in row.detail
    assert f"Move the files up into {psx}, or add {psx / 'MultiDisc'} to Rom_Path" in row.fix


def test_relative_rom_path_resolves_from_rocketlauncher_dir(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Nintendo Entertainment System": ["Contra (USA)"]})
    _touch(tmp_path / "Games" / "NES", "Contra (USA).nes")
    # RocketLauncher resolves ..\ from its own folder: <tmp>\Games\NES.
    _emulators_ini(
        rl, "Nintendo Entertainment System", "..\\Games\\NES", rom_ext="nes|zip",
    )

    node = _wheel(cfg, "Nintendo Entertainment System")
    assert node.status == OK
    assert node.detail == "1 games OK"


def test_missing_rom_path_folder_fails(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Sega Saturn": ["Nights into Dreams (USA)"]})
    gone = tmp_path / "OldDrive" / "Sega Saturn"
    ini = _emulators_ini(rl, "Sega Saturn", gone, rom_ext="cue")

    node = _wheel(cfg, "Sega Saturn")
    folder_rows = _rows(node, "Rom_Path")
    assert len(folder_rows) == 1
    assert folder_rows[0].status == FAIL
    assert str(gone) in folder_rows[0].detail
    assert str(ini) in folder_rows[0].fix
    assert _rows(node, "Games")[0].status == FAIL


def test_missing_relative_rom_path_shows_the_resolved_folder(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Sega Saturn": ["Nights into Dreams (USA)"]})
    _emulators_ini(rl, "Sega Saturn", "..\\Games\\Sega Saturn", rom_ext="cue")

    row = _rows(_wheel(cfg, "Sega Saturn"), "Rom_Path")[0]
    assert row.status == FAIL
    assert "..\\Games\\Sega Saturn" in row.detail
    assert str(tmp_path / "Games" / "Sega Saturn") in row.detail


def test_rom_path_on_a_drive_that_no_longer_exists(tmp_path):
    if os.name == "nt":
        letter = next((d for d in "ZYXWVUTSRQPONMLK" if not os.path.exists(d + ":\\")), None)
        if letter is None:
            pytest.skip("every candidate drive letter is in use")
    else:
        letter = "Q"
    stale = letter + ":\\Games\\PC Games"
    cfg, rl = _cabinet(tmp_path, {"PC Games": ["Hades"]})
    _emulators_ini(rl, "PC Games", stale, emulator="PCLauncher", rom_ext="ini")

    node = _wheel(cfg, "PC Games")
    if os.name == "nt":
        assert node.status == FAIL
        assert stale in _rows(node, "Rom_Path")[0].detail
    else:
        # A Windows drive path can't be checked from Linux/macOS: no false alarm.
        assert node.status == OK
        assert "can't check" in node.detail


def test_pclauncher_wheel_placeholder_folder(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"PC Games": ["Hades", "Celeste"]})
    pcl = rl / "Modules" / "PCLauncher" / "PC Games"
    _emulators_ini(
        rl, "PC Games", pcl, emulator="PCLauncher",
        extra=f"Rom_Extension=ini\n\n[PCLauncher]\nRom_Path={pcl}\nRom_Extension=ini\n",
    )

    node = _wheel(cfg, "PC Games")
    assert _rows(node, "Rom_Path")[0].status == FAIL
    assert str(pcl) in _rows(node, "Rom_Path")[0].detail

    _touch(pcl, "Hades.ini", "Celeste.ini")
    node = _wheel(cfg, "PC Games")
    assert node.status == OK
    assert node.detail == "2 games OK"


# ─── settings formats and the Rom_Extension chain ────────────────────────────


def test_lowercase_roms_section_and_bom(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Sony Playstation 2": ["Okami (USA)"]})
    ps2 = tmp_path / "Games" / "Sony Playstation 2"
    _touch(ps2, "Okami (USA).iso")
    _write(
        rl / "Settings" / "Sony Playstation 2" / "Emulators.ini",
        f"[Roms]\nrom_path={ps2}\nDefault_Emulator=PCSX2\n",
        encoding="utf-8-sig",
    )
    _global_emulators(rl, "[PCSX2]\nRom_Extension=7z|iso\n")

    node = _wheel(cfg, "Sony Playstation 2")
    assert node.status == OK
    assert node.detail == "1 games OK"


def test_flat_layout(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Atari 2600": ["Pitfall! (USA)", "Combat (USA)"]})
    a26 = tmp_path / "Games" / "Atari 2600"
    _touch(a26, "Pitfall! (USA).a26")
    _write(
        rl / "Settings" / "Atari 2600.ini",
        f"[Settings]\nDefault_Emulator=Stella\nRom_Path={a26}\nRom_Extension=a26|zip\n",
    )

    row = _rows(_wheel(cfg, "Atari 2600"), "Games")[0]
    assert row.status == WARN
    assert row.detail == "1/2 games not found in Rom_Path (e.g. Combat (USA))"
    assert "Atari 2600.ini" in row.fix


@pytest.mark.parametrize("roms_ext, system_emu_ext, global_ext, rom_ext, found", [
    ("", None, "chd", "chd", True),      # Global Emulators.ini [<emu>]
    ("", "cue", "chd", "cue", True),     # the system file's [<emu>] wins...
    ("", "cue", "chd", "chd", False),    # ...and the global list isn't merged in
    ("", "", "chd", "chd", False),       # even a bare [<emu>] with no Rom_Extension wins
    ("iso", None, "chd", "iso", False),  # RL never reads Rom_Extension under [ROMS]
    ("iso", None, "chd", "chd", True),
])
def test_rom_extension_lookup_chain(tmp_path, roms_ext, system_emu_ext, global_ext, rom_ext, found):
    """RocketLauncher 1.x reads every emulator key from the first file with an
    [<emulator>] section: the system's Emulators.ini, else Global Emulators.ini."""
    cfg, rl = _cabinet(tmp_path, {"Sega CD": ["Sonic CD (USA)"]})
    scd = tmp_path / "Games" / "Sega CD"
    _touch(scd, f"Sonic CD (USA).{rom_ext}")
    extra = f"Rom_Extension={roms_ext}\n" if roms_ext else ""
    if system_emu_ext is not None:
        extra += f"\n[Genesis Plus]\nRom_Extension={system_emu_ext}\n"
    _emulators_ini(rl, "Sega CD", scd, emulator="Genesis Plus", extra=extra)
    _global_emulators(rl, f"[Genesis Plus]\nRom_Extension={global_ext}\n")

    node = _wheel(cfg, "Sega CD")
    assert (node.status == OK) is found


def test_emulator_without_rom_extension_stops_rocketlauncher(tmp_path):
    """RL stops with "Could not find a Rom_Extension" before it looks for any
    file; a Rom_Extension under [ROMS] doesn't help."""
    cfg, rl = _cabinet(tmp_path, {"Sega CD": ["Sonic CD (USA)", "Snatcher (USA)"]})
    scd = tmp_path / "Games" / "Sega CD"
    _touch(scd, "Sonic CD (USA).iso", "Snatcher (USA).iso")
    ini = _emulators_ini(rl, "Sega CD", scd, emulator="Genesis Plus", extra="Rom_Extension=iso\n")
    _global_emulators(rl, "[Genesis Plus]\nEmu_Path=..\\Emulators\\gpgx.exe\n")

    node = _wheel(cfg, "Sega CD")
    row = _rows(node, "Emulator settings")[0]
    assert row.status == FAIL  # no game on the wheel can launch
    assert row.detail.startswith("2/2 games use Genesis Plus: RocketLauncher stops before looking")
    assert "has no Rom_Extension" in row.detail
    assert "Add Rom_Extension=<extensions> to [Genesis Plus] in" in row.fix
    assert f"doesn't read the Rom_Extension under [ROMS] in {ini}" in row.fix
    assert _rows(node, "Games") == []


def test_emulator_with_no_section_anywhere(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Sega CD": ["Sonic CD (USA)"]})
    _emulators_ini(rl, "Sega CD", tmp_path / "Games" / "Sega CD", emulator="Kega Fusion")
    _global_emulators(rl, "[Genesis Plus]\nRom_Extension=iso\n")

    row = _rows(_wheel(cfg, "Sega CD"), "Emulator settings")[0]
    assert "there is no [Kega Fusion] section" in row.detail
    assert "Could not locate a section called [Kega Fusion]" in row.detail


def _gun_cabinet(tmp_path, global_7z=None, system_7z=None):
    """A gun wheel with one SNES game launched through PCLauncher (Games.ini
    Emulator=), whose Global Emulators.ini [PCLauncher] has no Rom_Extension."""
    cfg, rl = _cabinet(tmp_path, {"Gun Games": ["alien3", "Battle Clash (USA)"]})
    mame = tmp_path / "Games" / "MAME"
    _touch(mame, "alien3.zip")
    _emulators_ini(rl, "Gun Games", mame, emulator="MAME")
    _global_emulators(rl, "[MAME]\nRom_Extension=zip|7z\n"
                          "[PCLauncher]\nModule=PCLauncher.ahk\nRom_Extension=\n")
    _write(rl / "Settings" / "Gun Games" / "Games.ini",
           "[Battle Clash (USA)]\nEmulator=PCLauncher\n")
    if global_7z is not None:
        _write(rl / "Settings" / "Global RocketLauncher.ini", f"[7z]\n7z_Enabled={global_7z}\n")
    if system_7z is not None:
        _write(rl / "Settings" / "Gun Games" / "RocketLauncher.ini",
               f"[7z]\n7z_Enabled={system_7z}\n")
    return cfg


def test_pclauncher_game_without_extension_is_not_looked_for(tmp_path):
    node = _wheel(_gun_cabinet(tmp_path), "Gun Games")
    assert node.status == OK
    assert node.detail == ("1 games OK; 1 PCLauncher game not checked: with no "
                           "Rom_Extension, RocketLauncher doesn't look for a file")


@pytest.mark.parametrize("global_7z, system_7z, launches", [
    ("false", None, True),
    ("true", None, False),  # 7-Zip on: RL looks for Battle Clash (USA).zip, .rar, ...
    ("true", "use_global", False),
    ("true", "false", True),  # the wheel turns 7-Zip off again
])
def test_7z_extensions_make_rl_look_for_pclauncher_games(tmp_path, global_7z, system_7z, launches):
    node = _wheel(_gun_cabinet(tmp_path, global_7z, system_7z), "Gun Games")
    assert (node.status == OK) is launches
    if not launches:
        row = _rows(node, "Games")[0]
        assert row.detail.startswith("1/2 games not found")
        # RL's own list, as its "Cannot find Rom" error quotes it (trailing | included)
        assert "extensions tried: zip|rar|7z|lha|lzh|gzip|tar|)" in row.fix


@pytest.mark.parametrize("what", ["folder", "file"])
def test_7z_on_and_no_extension_also_accepts_the_bare_game_name(tmp_path, what):
    """RL adds 7z_Extensions as "<ext>|", so an empty list ends in an empty
    entry: "<name>." then matches a folder or an extension-less file named
    exactly like the game (Windows drops the trailing dot)."""
    cfg = _gun_cabinet(tmp_path, "true")
    mame = tmp_path / "Games" / "MAME"
    if what == "folder":
        (mame / "Battle Clash (USA)").mkdir(parents=True)
    else:
        _touch(mame, "Battle Clash (USA)")
    assert _wheel(cfg, "Gun Games").status == OK


def test_blank_default_emulator_stops_games_with_their_own_emulator(tmp_path):
    """RL reads Default_Emulator before a game's Games.ini Emulator=, so a
    blank one stops every game on the wheel."""
    cfg, rl = _cabinet(tmp_path, {"Driving Games": ["outrun"]})
    mame = tmp_path / "Games" / "MAME"
    _touch(mame, "outrun.zip")
    _emulators_ini(rl, "Driving Games", mame, emulator="")
    _global_emulators(rl, "[MAME]\nRom_Extension=zip\n")
    _write(rl / "Settings" / "Driving Games" / "Games.ini", "[outrun]\nEmulator=MAME\n")

    row = _rows(_wheel(cfg, "Driving Games"), "Emulator settings")[0]
    assert row.status == FAIL
    assert "games use MAME" in row.detail
    assert "no Default_Emulator is set" in row.detail


@pytest.mark.parametrize("rom_extension, seven_zip, found", [
    ("z64", "true", True),    # RL adds 7z_Extensions in front, so a .zip is found
    ("z64", "false", False),
    ("gzip", "true", False),  # only those its list doesn't already contain as text
])
def test_7z_extensions_are_added_to_the_emulators_list(tmp_path, rom_extension, seven_zip, found):
    cfg, rl = _cabinet(tmp_path, {"Nintendo 64": ["Star Fox 64 (USA)"]})
    n64 = tmp_path / "Games" / "Nintendo 64"
    _touch(n64, "Star Fox 64 (USA).zip")
    _emulators_ini(rl, "Nintendo 64", n64, rom_ext=rom_extension)
    _write(rl / "Settings" / "Global RocketLauncher.ini", f"[7z]\n7z_Enabled={seven_zip}\n")
    assert (_wheel(cfg, "Nintendo 64").status == OK) is found


def test_games_ini_overrides(tmp_path):
    """Games.ini sends a game to another emulator (its Rom_Extension) or to
    another system's settings (its Rom_Path); RL tool marker lines and a
    System= with no settings must not crash the check."""
    games = ["outrun", "daytona", "initd", "ghost"]
    cfg, rl = _cabinet(tmp_path, {"Driving Games": games})
    mame = tmp_path / "Games" / "MAME"
    model2 = tmp_path / "Games" / "Sega Model 2"
    _touch(mame, "outrun.zip", "initd.dat")
    _touch(model2, "daytona.zip")
    _emulators_ini(rl, "Driving Games", mame, emulator="MAME")
    _emulators_ini(rl, "Sega Model 2", model2, emulator="Model 2")
    _global_emulators(
        rl,
        "[MAME]\nRom_Extension=zip|7z\n[Model 2]\nRom_Extension=zip\n"
        "[Demul]\nRom_Extension=dat|zip\n",
    )
    _write(
        rl / "Settings" / "Driving Games" / "Games.ini",
        "# remap games\n<!--Paste alternateemulator Output Below Here-->\n"
        "[daytona]\nEmulator=Model 2\nSystem=Sega Model 2\n"
        "[initd]\nEmulator=Demul\nSystem=\n"
        "[ghost]\nSystem=Nowhere\n",
    )

    node = _wheel(cfg, "Driving Games")
    assert node.status == OK
    assert node.detail == "3 games OK"  # ghost's System= has no settings to check


def _borrowing_cabinet(tmp_path, own_games, other_skipchecks="", own_skipchecks=""):
    """A CAVE wheel whose last two games use Taito Type X's settings (System=);
    Taito Type X's Rom_Path folder doesn't exist."""
    cfg, rl = _cabinet(tmp_path, {"CAVE": own_games + ["ddpsdoj", "Deathsmiles II"]})
    mame = tmp_path / "Games" / "MAME"
    _touch(mame, *(g + ".zip" for g in own_games))
    _emulators_ini(rl, "CAVE", mame, emulator="MAME", rom_ext="zip")
    taito = rl / "Modules" / "PCLauncher" / "Taito Type X"
    taito_ini = _emulators_ini(rl, "Taito Type X", taito, emulator="PCLauncher",
                               rom_ext="ini")
    _write(rl / "Settings" / "CAVE" / "Games.ini",
           "[ddpsdoj]\nEmulator=PCLauncher\nSystem=Taito Type X\n"
           "[Deathsmiles II]\nEmulator=PCLauncher\nSystem=Taito Type X\n")
    for system, skip in (("Taito Type X", other_skipchecks), ("CAVE", own_skipchecks)):
        if skip:
            _write(rl / "Settings" / system / "RocketLauncher.ini",
                   f"[Settings]\nSkipchecks={skip}\n")
    return cfg, taito, taito_ini


def test_system_override_folder_is_reported_as_the_games_problem(tmp_path):
    """RL takes Skipchecks from the System= system too: with Rom Only there it
    won't stop on these games, so the borrowed folder is a warning on their
    row, not a Rom_Path failure of the wheel itself."""
    cfg, taito, taito_ini = _borrowing_cabinet(
        tmp_path, ["dodonpachi", "espgal"], other_skipchecks="Rom Only")

    node = _wheel(cfg, "CAVE")
    assert _rows(node, "Rom_Path") == []
    assert _rows(node, "Games") == []
    row = _rows(node, "Games via Taito Type X")[0]
    assert row.status == WARN
    assert row.detail.startswith("2 games use Taito Type X's settings (Games.ini System=)")
    assert str(taito) in row.detail
    assert str(taito_ini) in row.fix
    assert node.status == WARN


def test_system_override_games_are_checked_with_that_systems_settings(tmp_path):
    # No Skipchecks on Taito Type X: RL looks for the games and can't find them.
    cfg, taito, _ini = _borrowing_cabinet(tmp_path, ["dodonpachi"])
    row = _rows(_wheel(cfg, "CAVE"), "Games via Taito Type X")[0]
    assert row.status == WARN  # dodonpachi still launches
    assert row.detail.startswith("2/2 games that use Taito Type X's settings")
    assert "its Rom_Path folder doesn't exist" in row.detail

    # The wheel's own Skipchecks doesn't cover games sent elsewhere by System=.
    cfg, taito, _ini = _borrowing_cabinet(tmp_path / "b", [], own_skipchecks="Rom Only")
    row = _rows(_wheel(cfg, "CAVE"), "Games via Taito Type X")[0]
    assert row.status == FAIL  # every game on the wheel is affected

    # Once the placeholder folder exists, they're found there.
    _touch(taito, "ddpsdoj.ini", "Deathsmiles II.ini")
    assert _wheel(cfg, "CAVE").status == OK


def test_name_with_trailing_space_is_looked_up_as_written(tmp_path):
    """load_database strips names, but RL gets the XML name exactly as written."""
    cfg, rl = _cabinet(tmp_path, {"NES Hacks": ["Super Hack - Type V2 ", "Plain Hack"]})
    nes = tmp_path / "Games" / "NES Hacks"
    _touch(nes, "Super Hack - Type V2 .nes", "Plain Hack.nes")
    _emulators_ini(rl, "NES Hacks", nes, rom_ext="nes")

    node = _wheel(cfg, "NES Hacks")
    assert node.status == OK
    assert node.detail == "2 games OK"


def test_hidden_wheel_is_checked_but_capped_at_info(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"KODI": ["kodi"], "NES": ["Contra (USA)"]}, hidden=("KODI",))
    _emulators_ini(rl, "KODI", tmp_path / "Games" / "KODI", rom_ext="exe")
    nes = tmp_path / "Games" / "NES"
    _touch(nes, "Contra (USA).nes")
    _emulators_ini(rl, "NES", nes, rom_ext="nes")

    result = health.check_rom_paths(cfg)
    node = next(c for c in result.children if c.name == "KODI (hidden on the Main Menu)")
    assert node.status == INFO
    assert {c.name for c in node.children} == {"Rom_Path", "Games"}  # still reported
    assert all(c.status == INFO for c in node.children)
    report = health.HealthReport()
    report.add(result)
    assert report.overall() == OK  # a hidden wheel can't fail doctor


# ─── RocketLauncher launch settings ──────────────────────────────────────────


def test_skipchecks_rom_and_emu_does_not_flag_games(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Pinball FX3": ["Medieval Madness"]})
    gone = tmp_path / "Games" / "Pinball FX3"
    _emulators_ini(rl, "Pinball FX3", gone, emulator="Pinball FX3")
    _write(rl / "Settings" / "Pinball FX3" / "RocketLauncher.ini",
           "[Settings]\nSkipchecks=Rom and Emu\n")

    node = _wheel(cfg, "Pinball FX3")
    assert _rows(node, "Games") == []
    assert "Skipchecks=Rom and Emu" in node.detail
    # RL won't stop on the missing folder, so it's a warning, not a failure.
    assert _rows(node, "Rom_Path")[0].status == WARN


@pytest.mark.parametrize("match_ext", ["true", "false"])
def test_rom_match_extension_accepts_any_file_in_the_game_folder(tmp_path, match_ext):
    cfg, rl = _cabinet(tmp_path, {"SNES CD": ["Secret of Mana (Proto)"]})
    snes_cd = tmp_path / "Games" / "SNES CD"
    _touch(snes_cd / "Secret of Mana (Proto)" / "tracks", "disc.cue")
    _emulators_ini(rl, "SNES CD", snes_cd, rom_ext="cue|chd")
    _write(rl / "Settings" / "SNES CD" / "RocketLauncher.ini",
           "[Settings]\nRom_Match_Extension=use_global\n")
    _write(rl / "Settings" / "Global RocketLauncher.ini",
           f"[Settings]\nRom_Match_Extension={match_ext}\n")

    node = _wheel(cfg, "SNES CD")
    assert (node.status == OK) is (match_ext == "true")


def test_game_in_its_own_named_folder(tmp_path):
    cfg, rl = _cabinet(tmp_path, {"Apple II": ["Oregon Trail"]})
    a2 = tmp_path / "Games" / "Apple II"
    _touch(a2 / "Oregon Trail", "Oregon Trail.dsk")
    _emulators_ini(rl, "Apple II", a2, rom_ext="dsk|zip")
    assert _wheel(cfg, "Apple II").status == OK


# ─── MAME alternate-name placeholders ────────────────────────────────────────


def _four_player_cabinet(tmp_path, extensions="zip|7z|txt"):
    cfg, rl = _cabinet(tmp_path, {"4-Player Games": ["xmen", "xmenxbox", "wofxbox"]})
    mame = tmp_path / "Games" / "MAME"
    _touch(mame, "xmen.zip", "wof.zip")
    _emulators_ini(rl, "4-Player Games", mame, emulator="MAME")
    _global_emulators(rl, f"[MAME]\nRom_Extension={extensions}\n")
    _write(
        rl / "Modules" / "MAME" / "MAME.ini",
        "[Settings]\nVideomode=d3d\n<!--Paste mameromname Output Below Here-->\n"
        "[xmenxbox]\nMameRomName = xmen\n[wofxbox]\nMameRomName = wof\n",
    )
    return cfg, mame


def test_mame_alternate_names_need_txt_placeholders(tmp_path):
    cfg, mame = _four_player_cabinet(tmp_path)

    row = _rows(_wheel(cfg, "4-Player Games"), "Games")[0]
    assert row.status == WARN
    assert row.detail.startswith("2/3 games not found")
    assert "MameRomName = xmen" in row.fix
    assert "xmenxbox.txt" in row.fix
    assert str(mame) in row.fix

    # Restoring the empty placeholders fixes the wheel.
    _touch(mame, "xmenxbox.txt", "wofxbox.txt")
    node = _wheel(cfg, "4-Player Games")
    assert node.status == OK
    assert node.detail == "3 games OK"


def test_placeholder_hint_asks_for_txt_extension_when_missing(tmp_path):
    cfg, _mame = _four_player_cabinet(tmp_path, extensions="zip|7z")
    row = _rows(_wheel(cfg, "4-Player Games"), "Games")[0]
    assert "add txt to Rom_Extension" in row.fix
