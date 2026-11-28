"""Tests for the `doctor` PC game programs check (``health.check_pc_game_programs``).

A PCLauncher game whose program needs a DLL that isn't there never starts:
Windows ends it at once (0xC0000135) with a "System Error" box, which on a
cabinet can open behind the frontend.
The check reads each program PCLauncher starts (``Application``, ``PreLaunch``,
``PostLaunch``, ``PostExit``; per key from ``<System>\\<game>.ini``, then
``<System>.ini``, then ``PCLauncher.ini``), reads its PE import table and
looks for each DLL where Windows' loader does.  Each test builds a small
HyperSpin + RocketLauncher cabinet in a temp dir, a stand-in Windows folder
(``SystemRoot``, with ``System32`` and ``SysWOW64``) and an empty ``PATH``; the
programs are tiny synthetic PE files built by :func:`_pe`.
"""
from __future__ import annotations

import os
import struct

import pytest

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
FAIL = health.Status.FAIL
INFO = health.Status.INFO

SYSTEM = "PC Games"


def _pe(imports=(), bits=32, dll=False):
    """A minimal PE file (``bits`` 32 or 64) whose import table names *imports*."""
    rva = 0x1000
    table = 20 * (len(imports) + 1)
    names, entries = b"", b""
    for name in imports:
        entries += struct.pack("<5I", 0, 0, 0, rva + table + len(names), 0)
        names += name.encode("ascii") + b"\0"
    data = entries + b"\0" * 20 + names
    opt_size = 224 if bits == 32 else 240
    coff = struct.pack("<HHIIIHH", 0x14C if bits == 32 else 0x8664, 1, 0, 0, 0, opt_size,
                       0x2102 if dll else 0x0102)
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x10B if bits == 32 else 0x20B)
    dirs = 96 if bits == 32 else 112
    struct.pack_into("<I", opt, dirs - 4, 16)  # NumberOfRvaAndSizes
    if imports:
        struct.pack_into("<II", opt, dirs + 8, rva, len(data))  # the import directory
    section = struct.pack("<8sIIIIIIHHI", b".idata", len(data), rva, len(data), 0x200, 0, 0, 0, 0, 0xC0000040)
    head = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40) + b"PE\0\0" + coff + bytes(opt) + section
    return head.ljust(0x200, b"\0") + data


def _write(path, data=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        # RocketLauncher's INIs are CRLF files.
        data = data.replace("\n", "\r\n").encode("cp1252")
    path.write_bytes(data)
    return path


@pytest.fixture
def windows(tmp_path, monkeypatch):
    """A stand-in Windows folder with the usual DLLs, for both bitnesses."""
    win = tmp_path / "Windows"
    for folder, bits in (("System32", 64), ("SysWOW64", 32)):
        for name in ("KERNEL32.dll", "USER32.dll", "d3d9.dll"):
            _write(win / folder / name, _pe(bits=bits, dll=True))
    monkeypatch.setenv("SystemRoot", str(win))
    monkeypatch.setenv("windir", str(win))
    monkeypatch.setenv("PATH", "")
    return win


def _cabinet(tmp_path, games, system=SYSTEM, hidden=(), other_wheels=None):
    """A cabinet whose *system* wheel lists *games* and launches them with PCLauncher.
    Returns ``(config, rl_dir, games folder)``; the games are in ``<tmp>\\Games\\<system>``."""
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
        _write(rl / "Settings" / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator=PCLauncher\nRom_Path={rl / 'Modules' / 'PCLauncher' / wheel}\n"
               "Rom_Extension=ini\n")
    _write(rl / "Settings" / "Global Emulators.ini",
           "[PCLauncher]\nModule=PCLauncher.ahk\nEmu_Path=..\\Emulators\\PCLauncher\\PCLauncher.exe\n\n"
           "[Nestopia]\nEmu_Path=..\\Emulators\\Nestopia\\nestopia.exe\nRom_Extension=nes|zip\n")
    _write(rl / "Modules" / "PCLauncher" / "PCLauncher.ahk", 'MEmu := "PCLauncher"\n')
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    return cfg, rl, folder


def _game_ini(rl, game, system=SYSTEM, **keys):
    """``Modules\\PCLauncher\\<system>\\<game>.ini`` with ``[<game>]`` and *keys*."""
    body = "".join(f"{k}={v}\n" for k, v in keys.items())
    return _write(rl / "Modules" / "PCLauncher" / system / f"{game}.ini", f"[{game}]\n{body}")


def _wheel(cfg, name=SYSTEM):
    result = health.check_pc_game_programs(cfg)
    return next(c for c in result.children if c.name.startswith(name))


def _row(node, name):
    rows = [c for c in node.children if c.name == name]
    return rows[0] if rows else None


# ─── the PE reader ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("bits", [32, 64])
def test_pe_image_reads_bitness_and_imports(tmp_path, bits):
    exe = _write(tmp_path / "game.exe", _pe(["steam_api.dll", "KERNEL32.dll", "kernel32.dll"], bits=bits))
    image = health._pe_image(exe)
    assert image.bits == bits
    assert image.imports == ["steam_api.dll", "KERNEL32.dll"]  # one entry per DLL, as spelled first


def test_pe_image_of_a_program_with_no_imports(tmp_path):
    image = health._pe_image(_write(tmp_path / "x.exe", _pe()))
    assert image.bits == 32 and image.imports == []


@pytest.mark.parametrize("data", [b"@echo off\r\nstart game.exe\r\n", b"MZ", b"", b"MZ" + b"\0" * 62])
def test_pe_image_of_other_files_is_none(tmp_path, data):
    assert health._pe_image(_write(tmp_path / "launch.bat", data)) is None
    assert health._pe_image(tmp_path / "missing.exe") is None


# ─── missing DLLs ───────────────────────────────────────────────────────────


def test_missing_dll_fails(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Sky Raider", "Run Gun"])
    exe = _write(folder / "Sky Raider" / "exe" / "raider.exe", _pe(["steam_api.dll", "KERNEL32.dll"]))
    _game_ini(rl, "Sky Raider", Application=exe, WorkingFolder=exe.parent)
    ok = _write(folder / "Run Gun" / "Run Gun.exe", _pe(["steam_api.dll", "USER32.dll"]))
    _write(folder / "Run Gun" / "steam_api.dll", _pe(["KERNEL32.dll"], dll=True))
    _game_ini(rl, "Run Gun", Application=ok)

    result = health.check_pc_game_programs(cfg)
    assert result.status == FAIL
    node = _wheel(cfg)
    row = _row(node, "Missing DLLs")
    assert row.status == FAIL
    assert row.detail.startswith("1/2 games have a program that can't start")
    assert "Sky Raider: raider.exe needs steam_api.dll" in row.detail
    assert "0xC0000135" in row.detail and "System Error" in row.detail and "behind the frontend" in row.detail
    assert "waits on that box" in row.detail
    assert "Run Gun" not in row.detail
    assert str(exe.parent) in row.fix
    assert "quarantine" in row.fix and "steam_api.dll" in row.fix and "event 26" in row.fix
    assert node.detail == "2 game(s) read"


def test_all_dlls_found_is_ok(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Brawl Night"])
    exe = _write(folder / "Brawl Night" / "BrawlNight.exe",
                 _pe(["steam_api.dll", "kernel32.DLL", "api-ms-win-crt-runtime-l1-1-0.dll",
                      "ext-ms-win-ntuser-window-l1-1-0.dll"]))
    _write(folder / "Brawl Night" / "STEAM_API.DLL", _pe(dll=True))  # names match ignoring case
    _game_ini(rl, "Brawl Night", Application=exe)
    result = health.check_pc_game_programs(cfg)
    assert result.status == OK
    node = _wheel(cfg)
    assert node.children == []
    assert node.detail == "1 game(s) OK"


def test_dll_is_looked_for_in_the_system_folder_of_the_programs_bitness(tmp_path, windows):
    _write(windows / "System32" / "xinput9_1_0.dll", _pe(bits=64, dll=True))
    _write(windows / "SysWOW64" / "openal32.dll", _pe(bits=32, dll=True))
    cfg, rl, folder = _cabinet(tmp_path, ["Sixty Four", "Thirty Two", "Wrong Folder"])
    _game_ini(rl, "Sixty Four", Application=_write(folder / "a" / "a.exe", _pe(["xinput9_1_0.dll"], bits=64)))
    _game_ini(rl, "Thirty Two", Application=_write(folder / "b" / "b.exe", _pe(["OpenAL32.dll"], bits=32)))
    # A 32-bit program never gets System32's (64-bit) DLLs on 64-bit Windows.
    _game_ini(rl, "Wrong Folder", Application=_write(folder / "c" / "c.exe", _pe(["xinput9_1_0.dll"], bits=32)))
    row = _row(_wheel(cfg), "Missing DLLs")
    assert row.detail.startswith("1/3 games")
    assert "Wrong Folder: c.exe needs xinput9_1_0.dll" in row.detail
    assert "Sixty Four" not in row.detail and "Thirty Two" not in row.detail


def test_32_bit_windows_has_no_syswow64(tmp_path, windows):
    import shutil

    shutil.rmtree(windows / "SysWOW64")
    _write(windows / "System32" / "openal32.dll", _pe(bits=32, dll=True))
    cfg, rl, folder = _cabinet(tmp_path, ["Rally"])
    _game_ini(rl, "Rally", Application=_write(folder / "Rally" / "Rally.exe", _pe(["OpenAL32.dll"], bits=32)))
    assert _wheel(cfg).status == OK


def test_windows_folder_and_path_are_searched(tmp_path, windows, monkeypatch):
    _write(windows / "d3dx9_43.dll", _pe(dll=True))
    extra = tmp_path / "Runtime"
    _write(extra / "xlive.dll", _pe(dll=True))
    monkeypatch.setenv("PATH", str(extra))
    cfg, rl, folder = _cabinet(tmp_path, ["Fight Night"])
    exe = _write(folder / "Fight Night" / "fight.exe", _pe(["d3dx9_43.dll", "xlive.dll", "GDFFIGHT.dll"]))
    _write(folder / "Fight Night" / "GDFFIGHT.dll", _pe(dll=True))
    _game_ini(rl, "Fight Night", Application=exe, WorkingFolder=exe.parent)
    assert _wheel(cfg).status == OK
    monkeypatch.setenv("PATH", "")
    assert "Fight Night: fight.exe needs xlive.dll" in _row(_wheel(cfg), "Missing DLLs").detail


# ─── the start folder ───────────────────────────────────────────────────────


def test_working_folder_that_doesnt_hold_the_program_fails(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Sky Raider", "Run Gun", "Gone Folder"])
    exe = _write(folder / "Sky Raider" / "exe" / "raider.exe", _pe(["KERNEL32.dll"]))
    ini = _game_ini(rl, "Sky Raider", Application=exe, WorkingFolder=folder / "Sky Raider")
    ok = _write(folder / "Run Gun" / "Run Gun.exe", _pe(["KERNEL32.dll"]))
    _game_ini(rl, "Run Gun", Application=ok, WorkingFolder=f"{ok.parent}{os.sep}")  # a trailing separator is fine
    gone = _write(folder / "g" / "g.exe", _pe())
    _game_ini(rl, "Gone Folder", Application=gone, WorkingFolder=folder / "no such folder")
    node = _wheel(cfg)
    row = _row(node, "Start folder")
    assert row.status == FAIL and node.status == FAIL
    assert row.detail.startswith("2 game(s) won't start")
    assert "Failed attempt to launch program or document" in row.detail and "waits for it forever" in row.detail
    assert f"Sky Raider: raider.exe isn't in {folder / 'Sky Raider'}" in row.detail
    assert "Gone Folder: g.exe isn't in" in row.detail
    assert "Run Gun" not in row.detail
    assert f"WorkingFolder={exe.parent} under [Sky Raider] in {ini}" in row.fix


def test_only_the_application_starts_in_working_folder(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Brawl Night"])
    exe = _write(folder / "Brawl Night" / "BrawlNight.exe", _pe())
    tool = _write(folder / "Tools" / "trainer.exe", _pe())
    _game_ini(rl, "Brawl Night", Application=exe, WorkingFolder=exe.parent, PreLaunch=tool, PostExit=tool)
    assert _wheel(cfg).status == OK


def test_the_copy_in_working_folder_is_the_one_that_runs(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Street Duo"])
    exe = _write(folder / "Street Duo" / "StreetDuo.exe", _pe(["KERNEL32.dll"]))
    # A same-named copy in the start folder is what Run() finds and starts.
    _write(folder / "Street Duo" / "bin" / "streetduo.exe", _pe(["steam_api.dll"]))
    _game_ini(rl, "Street Duo", Application=exe, WorkingFolder=folder / "Street Duo" / "bin")
    node = _wheel(cfg)
    assert _row(node, "Start folder") is None
    assert "Street Duo: streetduo.exe needs steam_api.dll" in _row(node, "Missing DLLs").detail


def test_program_found_by_its_bare_name_elsewhere_is_not_flagged(tmp_path, windows):
    notepad = _write(windows / "System32" / "notepad.exe", _pe(bits=64))
    cfg, rl, folder = _cabinet(tmp_path, ["Notes", "Steam", "Origin", "Disc"])
    other = folder / "Elsewhere"
    other.mkdir()
    _game_ini(rl, "Notes", Application=notepad, WorkingFolder=other)
    _game_ini(rl, "Steam", SteamID="207140", Application="", WorkingFolder=other)
    _game_ini(rl, "Origin", Application=_write(folder / "o" / "o.exe", _pe()), OriginGame="true", WorkingFolder=other)
    _game_ini(rl, "Disc", Application=_write(folder / "d" / "setup.exe", _pe()), DiscImage="disc.iso",
              WorkingFolder=other)
    assert _row(_wheel(cfg), "Start folder") is None


def test_dlls_of_the_games_own_dlls_are_followed(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Last Outpost"])
    exe = _write(folder / "Last Outpost" / "outpost.exe", _pe(["SDL2.dll", "sw_cbif.dll", "KERNEL32.dll"]))
    _write(folder / "Last Outpost" / "SDL2.dll", _pe(["KERNEL32.dll"], dll=True))
    _write(folder / "Last Outpost" / "sw_cbif.dll", _pe(["steam_api.dll", "SDL2.dll"], dll=True))
    _game_ini(rl, "Last Outpost", Application=exe)
    row = _row(_wheel(cfg), "Missing DLLs")
    assert "Last Outpost: outpost.exe needs steam_api.dll (for sw_cbif.dll)" in row.detail


def test_dll_of_the_other_bitness_fails(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Maze Collection"])
    exe = _write(folder / "Maze Collection" / "MazeCollection.exe", _pe(["steam_api.dll"], bits=32))
    _write(folder / "Maze Collection" / "steam_api.dll", _pe(bits=64, dll=True))
    _game_ini(rl, "Maze Collection", Application=exe)
    node = _wheel(cfg)
    assert _row(node, "Missing DLLs") is None
    row = _row(node, "DLL bitness")
    assert row.status == FAIL
    assert "Maze Collection: MazeCollection.exe is 32-bit, steam_api.dll is 64-bit" in row.detail
    assert "0xC000007B" in row.detail


def test_c_runtimes_from_side_by_side_assemblies(tmp_path, windows):
    _write(windows / "WinSxS" / "x86_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.30729.9625_none_508ef7e4bcbbe589"
           / "msvcr90.dll", _pe(dll=True))
    cfg, rl, folder = _cabinet(tmp_path, ["Private", "Shared", "Sixty Four"])
    _game_ini(rl, "Private", Application=_write(folder / "p" / "p.exe", _pe(["MSVCP90.dll"])))
    _write(folder / "p" / "Microsoft.VC90.CRT" / "msvcp90.dll", _pe(dll=True))
    _game_ini(rl, "Shared", Application=_write(folder / "s" / "s.exe", _pe(["MSVCR90.dll"])))
    # WinSxS holds only the 32-bit copy.
    _game_ini(rl, "Sixty Four", Application=_write(folder / "x" / "x.exe", _pe(["MSVCR90.dll"], bits=64)))
    row = _row(_wheel(cfg), "Missing DLLs")
    assert row.detail.startswith("1/3 games")
    assert "Sixty Four: x.exe needs MSVCR90.dll" in row.detail


# ─── which programs, read the way PCLauncher reads them ─────────────────────


def test_keys_are_read_per_key_game_ini_then_system_ini_then_module_ini(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Broken Pre", "Broken Post"])
    pcl = rl / "Modules" / "PCLauncher"
    good = _write(folder / "good.exe", _pe(["KERNEL32.dll"]))
    bad = _write(folder / "tool" / "bad.exe", _pe(["binkw32.dll"]))
    # Application from the per-game INI, PreLaunch from <System>.ini, PostExit from PCLauncher.ini.
    _game_ini(rl, "Broken Pre", Application=good)
    _write(pcl / f"{SYSTEM}.ini", f"[Broken Pre]\nApplication={bad}\nPreLaunch={bad}\n")
    _write(pcl / "PCLauncher.ini", f"[Broken Post]\nApplication={good}\nPostExit={bad}\n")
    row = _row(_wheel(cfg), "Missing DLLs")
    assert "Broken Pre: bad.exe (PreLaunch) needs binkw32.dll" in row.detail
    assert "Broken Post: bad.exe (PostExit) needs binkw32.dll" in row.detail
    assert "Broken Pre: bad.exe needs" not in row.detail  # the per-game Application wins
    assert row.detail.startswith("2/2 games")


def test_relative_paths_start_from_the_rocketlauncher_folder(tmp_path, windows):
    cfg, rl, _folder = _cabinet(tmp_path, ["Relative"])
    _write(rl.parent / "PC" / "Relative" / "game.exe", _pe(["steam_api.dll"]))
    _game_ini(rl, "Relative", Application='"..\\PC\\Relative\\game.exe"')
    assert "Relative: game.exe needs steam_api.dll" in _row(_wheel(cfg), "Missing DLLs").detail


def test_urls_steam_and_scripts_are_skipped(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Web", "Steam Link", "Steam ID", "Script", "Batch"])
    pcl = rl / "Modules" / "PCLauncher"
    bad = _write(folder / "bad.exe", _pe(["steam_api.dll"]))
    _game_ini(rl, "Web", Application="https://example.com/play", AppWaitExe="browser.exe")
    _game_ini(rl, "Steam Link", Application="steam://rungameid/207140")
    _write(pcl / f"{SYSTEM}.ini", f"[Steam ID]\nSteamID=207140\nApplication={bad}\n")  # Steam starts it
    _game_ini(rl, "Script", Application=_write(folder / "launch.ahk", "Run, game.exe\n"))
    _game_ini(rl, "Batch", Application=_write(folder / "launch.bat", "@start game.exe\n"))
    node = _wheel(cfg)
    assert node.status == OK
    assert node.children == []
    assert "5 start through Steam, a URL or a script" in node.detail


def test_steam_games_still_have_their_other_programs_checked(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Steam ID"])
    _game_ini(rl, "Steam ID", SteamID="207140",
              PreLaunch=_write(folder / "trainer.exe", _pe(["steam_api.dll"])))
    assert "Steam ID: trainer.exe (PreLaunch) needs steam_api.dll" in _row(_wheel(cfg), "Missing DLLs").detail


def test_missing_program_is_info(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Gone"])
    _game_ini(rl, "Gone", Application=folder / "Gone" / "game.exe")
    node = _wheel(cfg)
    row = _row(node, "Programs not found")
    assert row.status == INFO
    assert "Gone: game.exe" in row.detail and "Cannot find this" in row.detail
    assert str(rl / "Modules" / "PCLauncher" / SYSTEM / "Gone.ini") in row.fix
    assert node.status == INFO


def test_disc_image_program_on_the_disc_root_is_not_reported_missing(tmp_path, windows):
    # PCLauncher mounts DiscImage before it checks the programs, and takes a bare
    # Application file name as the root of the mounted image.
    cfg, rl, folder = _cabinet(tmp_path, ["Disc Root", "Local Gone", "No Disc"])
    iso = _write(folder / "isos" / "game.iso", b"")
    _game_ini(rl, "Disc Root", Application="setup.exe", DiscImage=iso)
    _write(rl / "setup.exe", _pe(["steam_api.dll"]))  # not the program that runs
    _game_ini(rl, "Local Gone", Application=folder / "Local" / "game.exe", DiscImage=iso)
    _game_ini(rl, "No Disc", Application="nodisc.exe")
    node = _wheel(cfg)
    row = _row(node, "Programs not found")
    assert "Disc Root" not in row.detail
    assert "Local Gone: game.exe" in row.detail  # a local path is still checked
    assert "No Disc: nodisc.exe" in row.detail
    assert row.detail.startswith("2 program(s)")
    assert _row(node, "Missing DLLs") is None
    assert "1 program(s) are on a disc image" in node.detail


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows paths")
def test_disc_image_program_on_a_drive_that_isnt_there_is_not_reported_missing(tmp_path, windows):
    free = next(c for c in "QRSTUVWXYZ" if not os.path.exists(f"{c}:\\"))
    cfg, rl, folder = _cabinet(tmp_path, ["Disc Drive", "No Disc Drive"])
    iso = _write(folder / "isos" / "game.iso", b"")
    _game_ini(rl, "Disc Drive", Application=f"{free}:\\GAME\\game.exe", DiscImage=iso,
              PreLaunch=f"{free}:\\patch.exe")
    _game_ini(rl, "No Disc Drive", Application=f"{free}:\\GAME\\game.exe")
    row = _row(_wheel(cfg), "Programs not found")
    assert "Disc Drive:" not in row.detail.replace("No Disc Drive:", "")
    assert "No Disc Drive: game.exe" in row.detail
    assert row.detail.startswith("1 program(s)")


def test_uninstaller_as_application_warns(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Robot Rumble", "Run Gun"])
    ini = _game_ini(rl, "Robot Rumble",
                    Application=_write(folder / "Robot Rumble" / "unins000.exe", _pe(["KERNEL32.dll"])))
    # Only the Application counts (a PostExit helper may be named anything).
    _game_ini(rl, "Run Gun", Application=_write(folder / "g" / "Run Gun.exe", _pe()),
              PostExit=_write(folder / "g" / "uninstall.exe", _pe()))
    node = _wheel(cfg)
    row = _row(node, "Uninstaller")
    assert row.status == WARN
    assert row.detail == "1 game(s) start an uninstaller as their Application: Robot Rumble (unins000.exe)"
    assert str(ini) in row.fix and "[Robot Rumble]" in row.fix
    assert node.status == WARN


# ─── Unity games ────────────────────────────────────────────────────────────


def test_unity_plugin_needing_a_missing_dll_warns(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Pixel Squad", "Maze 256"])
    exe = _write(folder / "Pixel Squad" / "Pixel Squad.exe", _pe(["KERNEL32.dll"]))
    _write(folder / "Pixel Squad" / "Pixel Squad_Data" / "Plugins" / "CSteamworks.dll", _pe(["steam_api.dll"], dll=True))
    _write(folder / "Pixel Squad" / "Pixel Squad_Data" / "Plugins" / "steam_api64.dll", _pe(bits=64, dll=True))
    _game_ini(rl, "Pixel Squad", Application=exe)
    # The plugin's DLL beside it in Plugins counts (Unity loads plugins from there).
    pac = _write(folder / "Maze 256" / "Maze-256.exe", _pe(["KERNEL32.dll"]))
    _write(folder / "Maze 256" / "Maze-256_Data" / "Plugins" / "CSteamworks.dll", _pe(["steam_api.dll"], dll=True))
    _write(folder / "Maze 256" / "Maze-256_Data" / "Plugins" / "steam_api.dll", _pe(dll=True))
    _game_ini(rl, "Maze 256", Application=pac)
    node = _wheel(cfg)
    assert _row(node, "Missing DLLs") is None
    row = _row(node, "Unity plugins")
    assert row.status == WARN
    assert row.detail.startswith("1/2 Unity games have a plugin")
    assert "Pixel Squad: Pixel Squad.exe: steam_api.dll (for CSteamworks.dll)" in row.detail
    assert "Maze 256" not in row.detail
    assert node.status == WARN


def test_unity_dll_beside_the_program_that_it_doesnt_import_warns(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Squad Missions"])
    game = folder / "Squad Missions"
    exe = _write(game / "Squad Missions.exe", _pe(["UnityPlayer.dll"], bits=64))
    _write(game / "UnityPlayer.dll", _pe(["KERNEL32.dll"], bits=64, dll=True))
    _write(game / "SteamworksNative.dll", _pe(["steam_api64.dll"], bits=64, dll=True))
    _write(game / "Old32.dll", _pe(["gone.dll"], bits=32, dll=True))  # the other bitness: never loaded
    (game / "Squad Missions_Data" / "Managed").mkdir(parents=True)
    _game_ini(rl, "Squad Missions", Application=exe)
    row = _row(_wheel(cfg), "Unity plugins")
    assert row.detail.endswith("Squad Missions: Squad Missions.exe: steam_api64.dll (for SteamworksNative.dll)")


def test_unity_arch_plugin_folder_is_read(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Ink Run"])
    game = folder / "Ink Run"
    exe = _write(game / "Ink Run.exe", _pe(["KERNEL32.dll"], bits=64))
    plugins = game / "Ink Run_Data" / "Plugins"
    _write(plugins / "x86_64" / "Galaxy64.dll", _pe(["MSVCR120.dll"], bits=64, dll=True))
    _write(plugins / "x86" / "Galaxy.dll", _pe(["MSVCR120.dll"], bits=32, dll=True))  # not this game's
    _game_ini(rl, "Ink Run", Application=exe)
    row = _row(_wheel(cfg), "Unity plugins")
    assert row.detail.endswith("Ink Run: Ink Run.exe: MSVCR120.dll (for Galaxy64.dll)")


# ─── wheels and setup ───────────────────────────────────────────────────────


def test_hidden_wheel_is_capped_at_info(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Prop Aces"], hidden=(SYSTEM,))
    _game_ini(rl, "Prop Aces", Application=_write(folder / "d" / "PropAces.exe", _pe(["steam_api.dll"])))
    result = health.check_pc_game_programs(cfg)
    [node] = result.children
    assert node.name == f"{SYSTEM} (hidden on the Main Menu)"
    assert node.status == INFO and _row(node, "Missing DLLs").status == INFO
    assert result.status == INFO


def test_wheels_not_on_pclauncher_are_left_out(tmp_path, windows):
    cfg, rl, folder = _cabinet(tmp_path, ["Brawl Night"], other_wheels={"Nintendo Entertainment System": ["Contra"]})
    _write(rl / "Settings" / "Nintendo Entertainment System" / "Emulators.ini",
           "[ROMS]\nDefault_Emulator=Nestopia\nRom_Path=x\n")
    _game_ini(rl, "Brawl Night", Application=_write(folder / "s.exe", _pe(["KERNEL32.dll"])))
    result = health.check_pc_game_programs(cfg)
    assert [c.name for c in result.children] == [SYSTEM]


def test_info_when_not_configured_or_no_pclauncher_wheel(tmp_path, windows):
    assert health.check_pc_game_programs(Config()).status == INFO
    cfg, rl, _folder = _cabinet(tmp_path, ["Contra"], system="Nintendo Entertainment System")
    _write(rl / "Settings" / "Nintendo Entertainment System" / "Emulators.ini",
           "[ROMS]\nDefault_Emulator=Nestopia\nRom_Path=x\n")
    result = health.check_pc_game_programs(cfg)
    assert result.status == INFO
    assert result.detail == "no PCLauncher systems"


def test_without_a_windows_folder_dlls_are_not_looked_for(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemRoot", str(tmp_path / "nowhere"))
    monkeypatch.setenv("windir", str(tmp_path / "nowhere"))
    cfg, rl, folder = _cabinet(tmp_path, ["Robot Rumble"])
    _game_ini(rl, "Robot Rumble", Application=_write(folder / "unins000.exe", _pe(["steam_api.dll"])))
    node = _wheel(cfg)
    assert _row(node, "Missing DLLs") is None
    assert _row(node, "Uninstaller").status == WARN  # still told
    assert "no Windows folder (SystemRoot)" in node.detail


def test_registered_in_doctor(tmp_path, windows):
    cfg, _rl, _folder = _cabinet(tmp_path, [])
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert names.index("PC game programs") == names.index("PCLauncher INI text") + 1
