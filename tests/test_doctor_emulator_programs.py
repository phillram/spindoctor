"""Tests for the `doctor` Emulator programs check (``health.check_emulator_programs``).

An emulator whose program needs a DLL that isn't there (often an older Visual
C++ runtime) never starts, so none of its wheel's games do.  The check
follows each Main Menu wheel's emulators (``Default_Emulator`` and the
``Games.ini`` overrides) to their ``Emu_Path`` and reads each program's PE
import table with the PC game programs check's reader.  Each test builds a
small HyperSpin + RocketLauncher cabinet in a temp dir, a stand-in Windows
folder (``SystemRoot``) and an empty ``PATH``; programs are tiny synthetic PE
files.
"""
from __future__ import annotations

import struct

import pytest

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
FAIL = health.Status.FAIL
INFO = health.Status.INFO


def _pe(imports=(), bits=32, dll=False):
    """A minimal PE file whose import table names *imports* (as in
    ``test_doctor_pc_game_programs.py``)."""
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
    struct.pack_into("<I", opt, dirs - 4, 16)
    if imports:
        struct.pack_into("<II", opt, dirs + 8, rva, len(data))
    section = struct.pack("<8sIIIIIIHHI", b".idata", len(data), rva, len(data), 0x200, 0, 0, 0, 0, 0xC0000040)
    head = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40) + b"PE\0\0" + coff + bytes(opt) + section
    return head.ljust(0x200, b"\0") + data


def _write(path, data=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.replace("\n", "\r\n").encode("cp1252")
    path.write_bytes(data)
    return path


@pytest.fixture
def windows(tmp_path, monkeypatch):
    win = tmp_path / "Windows"
    for folder, bits in (("System32", 64), ("SysWOW64", 32)):
        for name in ("KERNEL32.dll", "USER32.dll", "OPENGL32.dll"):
            _write(win / folder / name, _pe(bits=bits, dll=True))
    monkeypatch.setenv("SystemRoot", str(win))
    monkeypatch.setenv("windir", str(win))
    monkeypatch.setenv("PATH", "")
    return win


def _cabinet(tmp_path, wheels, emulators, hidden=()):
    """*wheels* maps a wheel to its Default_Emulator; *emulators* maps an
    emulator section to its ``Emu_Path`` (``Module=`` too when given as a
    tuple).  Returns ``(config, rl_dir)``."""
    hs = tmp_path / "Arcade"
    rl = hs / "RocketLauncher"
    menu = "".join(f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>' for w in wheels)
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, emu in wheels.items():
        _write(hs / "Databases" / wheel / f"{wheel}.xml", '<menu><game name="A Game"/></menu>')
        _write(rl / "Settings" / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator={emu}\nRom_Path={tmp_path / 'Games' / wheel}\n")
    text = ""
    for section, value in emulators.items():
        path, module = value if isinstance(value, tuple) else (value, "")
        text += f"[{section}]\nEmu_Path={path}\nRom_Extension=zip\n" + (f"Module={module}\n" if module else "") + "\n"
    _write(rl / "Settings" / "Global Emulators.ini", text)
    return Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl)), rl


def _node(result, name):
    found = [c for c in result.children if c.name.startswith(name)]
    return found[0] if found else None


def test_emulator_missing_a_runtime_fails(tmp_path, windows):
    emus = tmp_path / "Emulators"
    poke = _write(emus / "PokeMini" / "PokeMini.exe", _pe(["MSVCR100.dll", "KERNEL32.dll", "SDL.dll"]))
    _write(emus / "PokeMini" / "SDL.dll", _pe(["USER32.dll"], dll=True))
    mame = _write(emus / "MAME" / "mame64.exe", _pe(["KERNEL32.dll", "OPENGL32.dll"], bits=64))
    cfg, _rl = _cabinet(tmp_path, {"Nintendo Pokemon Mini": "PokeMini", "MAME": "MAME"},
                        {"PokeMini": poke, "MAME": mame})
    result = health.check_emulator_programs(cfg)
    assert result.status == FAIL
    assert result.detail == "1 of 2 emulator program(s) can't start"
    node = _node(result, "PokeMini")
    assert node.status == FAIL
    assert node.detail.startswith("PokeMini.exe needs MSVCR100.dll, which isn't there (0xC0000135)")
    assert "Used by Nintendo Pokemon Mini ([PokeMini] in" in node.detail
    assert node.fix.startswith("Install Microsoft Visual C++ 2010 Redistributable (x86).")
    assert "docs/windows-10-migration.md" in node.fix
    assert _node(result, "MAME") is None


def test_everything_present_is_ok(tmp_path, windows):
    emu = _write(tmp_path / "Emulators" / "Nestopia" / "nestopia.exe", _pe(["KERNEL32.dll", "msvcr90.dll"]))
    _write(tmp_path / "Emulators" / "Nestopia" / "Microsoft.VC90.CRT" / "msvcr90.dll", _pe(dll=True))
    cfg, _rl = _cabinet(tmp_path, {"Nintendo Entertainment System": "Nestopia"}, {"Nestopia": emu})
    result = health.check_emulator_programs(cfg)
    assert result.status == OK
    assert result.detail == "1 emulator program(s) OK"
    assert result.children == []


def test_one_program_used_by_several_wheels_is_one_row(tmp_path, windows):
    emu = _write(tmp_path / "Emulators" / "Demul" / "demul.exe", _pe(["d3dx9_43.dll"]))
    wheels = {"Sega Naomi": "Demul", "Sammy Atomiswave": "Demul", "Sega Dreamcast": "Demul Dreamcast"}
    cfg, _rl = _cabinet(tmp_path, wheels, {"Demul": emu, "Demul Dreamcast": emu})
    result = health.check_emulator_programs(cfg)
    [node] = result.children
    assert node.name == "Demul"
    assert "Used by Sega Naomi, Sammy Atomiswave, Sega Dreamcast (" in node.detail
    assert "DirectX End-User Runtime (June 2010)" in node.fix


def test_games_ini_emulator_override_is_followed(tmp_path, windows):
    ok = _write(tmp_path / "Emulators" / "MAME" / "mame64.exe", _pe(["KERNEL32.dll"], bits=64))
    old = _write(tmp_path / "Emulators" / "MAME 0.139" / "mame.exe", _pe(["MSVCR120.dll"], bits=64))
    cfg, rl = _cabinet(tmp_path, {"MAME": "MAME"}, {"MAME": ok, "MAME 0.139": old})
    _write(rl / "Settings" / "MAME" / "Games.ini", "[A Game]\nEmulator=MAME 0.139\n")
    node = _node(health.check_emulator_programs(cfg), "MAME 0.139")
    assert node.status == FAIL
    assert "Microsoft Visual C++ 2013 Redistributable (x64)" in node.fix


def test_relative_emu_path_starts_from_the_rocketlauncher_folder(tmp_path, windows):
    cfg, rl = _cabinet(tmp_path, {"Atari Lynx": "Handy"}, {"Handy": "..\\Emulators\\Handy\\handy.exe"})
    _write(rl.parent / "Emulators" / "Handy" / "handy.exe", _pe(["OpenAL32.dll"]))
    node = _node(health.check_emulator_programs(cfg), "Handy")
    assert node.detail.startswith("handy.exe needs OpenAL32.dll")
    assert node.fix.startswith("Install OpenAL.")


def test_dll_of_the_other_bitness_and_unknown_dll(tmp_path, windows):
    folder = tmp_path / "Emulators" / "Supermodel"
    emu = _write(folder / "Supermodel.exe", _pe(["SDL2.dll", "zlibwapi.dll"], bits=64))
    _write(folder / "SDL2.dll", _pe(bits=32, dll=True))
    cfg, _rl = _cabinet(tmp_path, {"Sega Model 3": "Supermodel"}, {"Supermodel": emu})
    node = _node(health.check_emulator_programs(cfg), "Supermodel")
    assert "needs zlibwapi.dll, which isn't there" in node.detail
    assert "is 64-bit, but SDL2.dll is 32-bit (0xC000007B)" in node.detail
    assert node.fix.startswith(f"Put the missing DLL in {folder}, from the emulator's own download.")


def test_placeholder_emu_paths_and_missing_programs_are_skipped(tmp_path, windows):
    bad = _write(tmp_path / "Emulators" / "PCLauncher" / "PCLauncher.exe", _pe(["gone.dll"]))
    cfg, _rl = _cabinet(
        tmp_path,
        {"PC Games": "PCLauncher", "PopCap": "Casual Games", "Gone Wheel": "Gone"},
        {"PCLauncher": (bad, "PCLauncher.ahk"), "Casual Games": (bad, "Casual Games.ahk"),
         "Gone": tmp_path / "Emulators" / "Gone" / "gone.exe"},
    )
    result = health.check_emulator_programs(cfg)
    assert result.status == INFO
    assert result.detail == "no emulator programs to read"


def test_emulator_used_only_by_hidden_wheels_is_info(tmp_path, windows):
    emu = _write(tmp_path / "Emulators" / "nullDC" / "nullDC.exe", _pe(["MSVCP100.dll"]))
    cfg, _rl = _cabinet(tmp_path, {"Sega Dreamcast": "nullDC"}, {"nullDC": emu}, hidden=("Sega Dreamcast",))
    result = health.check_emulator_programs(cfg)
    [node] = result.children
    assert node.name == "nullDC (only wheels hidden on the Main Menu)"
    assert node.status == INFO and result.status == INFO


@pytest.mark.parametrize("dll, bits, runtime", [
    ("MSVCR100.dll", 32, "Microsoft Visual C++ 2010 Redistributable (x86)"),
    ("msvcp120.dll", 64, "Microsoft Visual C++ 2013 Redistributable (x64)"),
    ("VCRUNTIME140_1.dll", 64, "Microsoft Visual C++ 2015-2022 Redistributable (x64)"),
    ("mfc140u.dll", 32, "Microsoft Visual C++ 2015-2022 Redistributable (x86)"),
    ("MSVCR80.dll", 32, "Microsoft Visual C++ 2005 Redistributable (x86)"),
    ("d3dx9_43.dll", 32, "the DirectX End-User Runtime (June 2010)"),
    ("XINPUT1_3.dll", 32, "the DirectX End-User Runtime (June 2010)"),
    ("xaudio2_7.dll", 32, "the DirectX End-User Runtime (June 2010)"),
    ("D3DCompiler_43.dll", 64, "the DirectX End-User Runtime (June 2010)"),
    ("xinput1_4.dll", 32, ""),  # part of Windows
    ("xaudio2_9.dll", 64, ""),
    ("d3dcompiler_47.dll", 64, ""),
    ("OpenAL32.dll", 32, "OpenAL"),
    ("xlive.dll", 32, "Games for Windows Live"),
    ("steam_api.dll", 32, ""),
])
def test_runtime_names(dll, bits, runtime):
    assert health._runtime_of(dll, bits) == runtime


def test_info_when_not_configured_or_no_windows_folder(tmp_path, monkeypatch):
    assert health.check_emulator_programs(Config()).status == INFO
    monkeypatch.setenv("SystemRoot", str(tmp_path / "nowhere"))
    monkeypatch.setenv("windir", str(tmp_path / "nowhere"))
    cfg, _rl = _cabinet(tmp_path, {"MAME": "MAME"}, {"MAME": _write(tmp_path / "mame.exe", _pe(["gone.dll"]))})
    result = health.check_emulator_programs(cfg)
    assert result.status == INFO
    assert "no Windows folder" in result.detail


def test_registered_in_doctor(tmp_path, windows):
    cfg, _rl = _cabinet(tmp_path, {}, {})
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert names.index("Emulator programs") == names.index("PC game programs") + 1
