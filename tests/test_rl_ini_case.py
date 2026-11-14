"""RocketLauncher INI lookups are case-insensitive and tolerate duplicates.

RocketLauncher reads its INIs through the Windows profile API, so ``[Roms]``
is ``[ROMS]``, ``[mame]`` is ``[MAME]``, and a repeated key or section isn't an
error (the first one wins).  configparser is case-sensitive about sections
and raises on duplicates, so wheels that launch fine were reported as having
no ``Default_Emulator``, and a single duplicate anywhere in
``Global Emulators.ini`` hid every emulator's ``Emu_Path``.

These lookups, the ``doctor`` ROM paths check and ``audit`` share one reader
(``rocketlauncher._read_rl_ini``), so they also agree on encodings and on
where a section name ends.
"""
from __future__ import annotations
from tests.helpers import write_bytes as _write_bytes

from spindoctor import rocketlauncher

import pytest

from spindoctor import health
from spindoctor.config import Config
from spindoctor.rl_rom_paths import _RomLookup
from spindoctor.rocketlauncher import (
    _read_emulator_emu_path,
    _read_emulator_exe,
    _read_rl_ini,
    _read_system_default_emulator,
    _read_windows_text_with_encoding,
    read_rl_rom_extensions,
)


@pytest.mark.parametrize("encoding,bom", [
    ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"),
])
@pytest.mark.parametrize("damage", ["truncated", "surrogate"])
def test_corrupt_utf16_is_tolerated_for_diagnostics_only(tmp_path, encoding, bom, damage):
    ini = tmp_path / "Emulators.ini"
    content = bom + "[ROMS]\nDefault_Emulator=Mesen\nBroken=".encode(encoding)
    content += b"\x00" if damage == "truncated" else "\ud800".encode(encoding, errors="surrogatepass")
    ini.write_bytes(content)
    assert _read_rl_ini(ini)["roms"]["default_emulator"] == "Mesen"
    with pytest.raises(UnicodeDecodeError):
        _read_windows_text_with_encoding(ini)
    assert ini.read_bytes() == content


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("section", ["ROMS", "Roms", "roms"])
def test_default_emulator_any_section_case(tmp_path, section):
    _write(tmp_path / "Settings" / "Sega Model 3" / "Emulators.ini",
           f"[{section}]\nDefault_Emulator=Supermodel\nRom_Path=D:\\Games\\Model 3\n")
    assert _read_system_default_emulator("Sega Model 3", tmp_path) == "Supermodel"


def test_default_emulator_flat_layout_lowercase_section(tmp_path):
    _write(tmp_path / "Settings" / "Famicom.ini", "[settings]\ndefault_emulator=Mesen\n")
    assert _read_system_default_emulator("Famicom", tmp_path) == "Mesen"


def test_default_emulator_survives_duplicate_keys(tmp_path):
    _write(tmp_path / "Settings" / "ScummVM" / "Emulators.ini",
           "[ROMS]\nDefault_Emulator=ScummVM\nRom_Path=A\nRom_Path=B\n")
    assert _read_system_default_emulator("ScummVM", tmp_path) == "ScummVM"


def test_global_emulators_section_case_and_duplicates(tmp_path):
    _write(tmp_path / "Settings" / "Global Emulators.ini",
           "[MAME]\nEmu_Path=..\\Emulators\\MAME\\mame.exe\nRom_Extension=zip|7z\n"
           "Rom_Extension=chd\n"
           "[Dolphin]\nEmu_Path=D:\\Emulators\\Dolphin\\Dolphin.exe\n"
           "[Dolphin]\nEmu_Path=D:\\Old\\Dolphin.exe\n")
    assert _read_emulator_emu_path("mame", tmp_path) == "..\\Emulators\\MAME\\mame.exe"
    assert _read_emulator_exe("mame", tmp_path) == "mame.exe"
    assert _read_emulator_emu_path("Dolphin", tmp_path) == "D:\\Emulators\\Dolphin\\Dolphin.exe"


def test_rom_extensions_from_case_mismatched_section(tmp_path):
    # A name SpinDoctor can't guess an emulator from, so only the INI counts.
    _write(tmp_path / "Settings" / "Cave Shooters" / "Emulators.ini",
           "[Roms]\nDefault_Emulator=mame\n")
    _write(tmp_path / "Settings" / "Global Emulators.ini",
           "[MAME]\nEmu_Path=mame.exe\nRom_Extension=zip|7z\n")
    assert read_rl_rom_extensions("Cave Shooters", tmp_path) == {"zip", "7z"}


def test_doctor_wheel_wiring_reads_roms_section_in_any_case(tmp_path):
    hs = tmp_path / "HyperSpin"
    rl = tmp_path / "RocketLauncher"
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml",
           '<menu><game name="Sega Model 3"/></menu>')
    _write(rl / "Settings" / "Sega Model 3" / "Emulators.ini",
           "[Roms]\nDefault_Emulator=Supermodel\n")
    _write(rl / "Settings" / "Global Emulators.ini",
           "[Supermodel]\nEmu_Path=D:\\Emulators\\Supermodel\\Supermodel.exe\n")
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))

    result = health.check_wheel_wiring(cfg, fix=False, fixes_applied=[])
    wheel = next(c for c in result.children if c.name == "Sega Model 3")
    emulator = next(c for c in wheel.children if c.name == "Emulator")
    assert "no Default_Emulator" not in (emulator.detail or "")


def test_utf16_and_ansi_inis(tmp_path):
    # The Windows profile API reads UTF-16 (with a BOM) and ANSI files too.
    utf16 = tmp_path / "Settings" / "Famicom" / "Emulators.ini"
    utf16.parent.mkdir(parents=True)
    utf16.write_bytes("[ROMS]\r\nDefault_Emulator=Mesen\r\n".encode("utf-16"))
    ansi = tmp_path / "Settings" / "Global Emulators.ini"
    ansi.write_bytes("[Mesen]\r\nEmu_Path=D:\\Émulateurs\\Mesen\\Mesen.exe\r\n"
                     "Rom_Extension=nes|fds\r\n".encode("cp1252"))
    assert _read_system_default_emulator("Famicom", tmp_path) == "Mesen"
    assert _read_emulator_emu_path("Mesen", tmp_path) == "D:\\Émulateurs\\Mesen\\Mesen.exe"
    assert read_rl_rom_extensions("Famicom", tmp_path) == {"nes", "fds"}


def test_section_name_runs_to_the_last_bracket(tmp_path):
    # A comment after [ROMS] doesn't hide the section, and a Games.ini
    # section for a game named "Name [!]" keeps its brackets.
    _write(tmp_path / "Settings" / "NES" / "Emulators.ini",
           "[ROMS] ; edited by hand\nDefault_Emulator=Nestopia\nRom_Path=..\\Games\\NES\n"
           "[Nestopia]\nRom_Extension=nes|zip\n")
    games = _write(tmp_path / "Settings" / "NES" / "Games.ini",
                   "[Super Game [!]]\nEmulator=Mesen\n")
    assert _read_rl_ini(games) == {"super game [!]": {"emulator": "Mesen"}}
    assert _read_system_default_emulator("NES", tmp_path) == "Nestopia"
    look = _RomLookup(tmp_path)
    src = look.source("NES")
    assert (src.emulator, src.exts) == ("Nestopia", ["nes", "zip"])
    assert look.game_overrides("NES") == {"super game [!]": ("Mesen", "")}


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16", "utf-8-sig"])
def test_ini_rom_path_update_preserves_encoding(config_home, tmp_path, encoding):
    path = _write_bytes(tmp_path / "Emulators.ini",
                 "[ROMS]\r\nRom_Path=old\r\n; Émulateurs\r\n".encode(encoding))
    assert rocketlauncher._update_rom_path_in_ini(path, "new")
    assert path.read_bytes().decode(encoding) == "[ROMS]\r\nRom_Path=new\r\n; Émulateurs\r\n"


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_damaged_utf16_is_readable_but_not_losslessly_editable(tmp_path, encoding):
    path = tmp_path / "Emulators.ini"
    content = ("\ufeff[ROMS]\r\nDefault_Emulator=MAME\r\n").encode(encoding) + b"x"
    path.write_bytes(content)
    assert rocketlauncher._read_rl_ini(path)["roms"]["default_emulator"] == "MAME"
    with pytest.raises(UnicodeDecodeError):
        rocketlauncher._read_windows_text_with_encoding(path)
    assert path.read_bytes() == content
