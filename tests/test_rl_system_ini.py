"""Tests for generate_rl_system_ini + detect_rl_layout.

Three layout scenarios:
  folder — Settings/<system>/Emulators.ini already exists (HyperHQ layout).
  flat   — Settings/<system>.ini already exists (older RL layout).
  new    — neither file exists (first-time generate-config run).
"""
from __future__ import annotations

from pathlib import Path

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.rocketlauncher import detect_rl_layout, generate_rl_system_ini


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _make_config(tmp_path: Path) -> tuple[Config, Path]:
    """Return a minimal Config and the RL base directory."""
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    (roms / "MAME").mkdir(parents=True)
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    save_config(cfg)
    return cfg, rl


# ─── detect_rl_layout ────────────────────────────────────────────────────────


def test_detect_folder_layout(tmp_path):
    settings = tmp_path / "Settings"
    (settings / "MAME").mkdir(parents=True)
    (settings / "MAME" / "Emulators.ini").write_text("[ROMS]\n", encoding="utf-8")
    assert detect_rl_layout(settings, "MAME") == "folder"


def test_detect_flat_layout(tmp_path):
    settings = tmp_path / "Settings"
    settings.mkdir()
    (settings / "MAME.ini").write_text("[Settings]\n", encoding="utf-8")
    assert detect_rl_layout(settings, "MAME") == "flat"


def test_detect_new_when_neither_exists(tmp_path):
    settings = tmp_path / "Settings"
    settings.mkdir()
    assert detect_rl_layout(settings, "MAME") == "new"


def test_detect_folder_wins_when_both_exist(tmp_path):
    """If both files exist, folder layout is reported (checked first)."""
    settings = tmp_path / "Settings"
    (settings / "MAME").mkdir(parents=True)
    (settings / "MAME" / "Emulators.ini").write_text("[ROMS]\n", encoding="utf-8")
    (settings / "MAME.ini").write_text("[Settings]\n", encoding="utf-8")
    assert detect_rl_layout(settings, "MAME") == "folder"


# ─── generate_rl_system_ini — folder layout ──────────────────────────────────


def test_folder_layout_updates_emulators_ini(tmp_path):
    """When Settings/MAME/Emulators.ini already exists, it is updated in-place
    and the flat Settings/MAME.ini is NOT created."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text("[ROMS]\nDefault_Emulator=MAME\nRom_Path=D:\\old\n",
                       encoding="utf-8")

    written = generate_rl_system_ini("MAME", cfg)

    assert len(written) == 1
    assert written[0] == emu_ini
    body = emu_ini.read_text(encoding="utf-8")
    assert "[ROMS]" in body
    assert "Default_Emulator=MAME" in body
    # Rom_Path updated to the new roms_dir value.
    new_rom_path = str(Path(cfg.roms_dir) / "MAME")
    assert f"Rom_Path={new_rom_path}" in body
    # Flat file must NOT be created.
    assert not (rl / "Settings" / "MAME.ini").exists()


def test_folder_layout_uses_roms_section_not_settings(tmp_path):
    """Folder-layout Emulators.ini must use [ROMS], not [Settings]."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text("", encoding="utf-8")

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert "[ROMS]" in body
    assert "[Settings]" not in body


# ─── generate_rl_system_ini — flat layout ────────────────────────────────────


def test_flat_layout_updates_flat_ini(tmp_path):
    """When Settings/MAME.ini already exists, it is updated and the folder-
    layout file is NOT created."""
    cfg, rl = _make_config(tmp_path)
    flat_ini = rl / "Settings" / "MAME.ini"
    flat_ini.write_text("[Settings]\nDefault_Emulator=MAME\nRom_Path=D:\\old\n",
                        encoding="utf-8")

    written = generate_rl_system_ini("MAME", cfg)

    assert len(written) == 1
    assert written[0] == flat_ini
    body = flat_ini.read_text(encoding="utf-8")
    assert "[Settings]" in body
    new_rom_path = str(Path(cfg.roms_dir) / "MAME")
    assert f"Rom_Path={new_rom_path}" in body
    # Folder-layout file must NOT be created.
    assert not (rl / "Settings" / "MAME" / "Emulators.ini").exists()


# ─── generate_rl_system_ini — new system ─────────────────────────────────────


def test_new_system_writes_both_files(tmp_path):
    """When neither file exists, both are written so the cabinet works
    regardless of which layout RocketLauncher prefers."""
    cfg, rl = _make_config(tmp_path)

    written = generate_rl_system_ini("MAME", cfg)

    assert len(written) == 2
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    flat_ini = rl / "Settings" / "MAME.ini"
    assert emu_ini in written
    assert flat_ini in written

    # Folder file uses [ROMS]; flat file uses [Settings].
    assert "[ROMS]" in emu_ini.read_text(encoding="utf-8")
    assert "[Settings]" in flat_ini.read_text(encoding="utf-8")


def test_new_system_both_files_have_correct_rom_path(tmp_path):
    cfg, rl = _make_config(tmp_path)
    generate_rl_system_ini("MAME", cfg)

    expected = str(Path(cfg.roms_dir) / "MAME")
    for p in [
        rl / "Settings" / "MAME" / "Emulators.ini",
        rl / "Settings" / "MAME.ini",
    ]:
        assert f"Rom_Path={expected}" in p.read_text(encoding="utf-8")


# ─── Emu_Path preservation ────────────────────────────────────────────────────


def test_folder_layout_preserves_emu_path(tmp_path):
    """generate_rl_system_ini must keep an existing Emu_Path in the
    [Emulator] section of the folder-layout Emulators.ini.

    Root cause of the post-migration launch failure: the original file (written
    by HyperHQ / RLUI) contained Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame.exe.
    Before this fix, generate_rl_system_ini wiped the entire file, dropping
    Emu_Path, and RL then emitted 'Could not find an Emu_path for MAME'."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\n"
        "Default_Emulator=MAME\n"
        "Rom_Path=D:\\old\\MAME\n"
        "\n"
        "[MAME]\n"
        "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame.exe\n"
        "Rom_Path=D:\\old\\MAME\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    # Rom_Path updated to the new value.
    new_rom_path = str(Path(cfg.roms_dir) / "MAME")
    assert f"Rom_Path={new_rom_path}" in body
    # Emu_Path must be preserved verbatim.
    assert "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame.exe" in body


def test_flat_layout_preserves_emu_path(tmp_path):
    """Same preservation requirement for the flat-layout Settings/<system>.ini."""
    cfg, rl = _make_config(tmp_path)
    flat_ini = rl / "Settings" / "MAME.ini"
    flat_ini.write_text(
        "[Settings]\n"
        "Default_Emulator=MAME\n"
        "Rom_Path=D:\\old\\MAME\n"
        "\n"
        "[MAME]\n"
        "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame.exe\n"
        "Rom_Path=D:\\old\\MAME\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = flat_ini.read_text(encoding="utf-8")
    new_rom_path = str(Path(cfg.roms_dir) / "MAME")
    assert f"Rom_Path={new_rom_path}" in body
    assert "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame.exe" in body


def test_no_emu_path_entry_when_none_existed(tmp_path):
    """When the existing file has no Emu_Path, the rewritten file must also
    omit it — no empty or placeholder Emu_Path= line is inserted."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\nDefault_Emulator=MAME\nRom_Path=D:\\old\\MAME\n"
        "\n[MAME]\nRom_Path=D:\\old\\MAME\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert "Emu_Path=" not in body
