"""Tests for generate_rl_system_ini + detect_rl_layout.

Three layout scenarios:
  folder — Settings/<system>/Emulators.ini already exists (HyperHQ layout).
  flat   — Settings/<system>.ini already exists (older RL layout).
  new    — neither file exists (first-time generate-config run).

In-place update contract (existing files):
  Only Rom_Path= is changed.  Default_Emulator, Emu_Path, Module, and every
  other key are preserved exactly as set by HyperHQ / RLUI.  This was the
  root cause of the post-migration "Could not find an Emu_path" breakage:
  the old code replaced the file wholesale, overwriting Default_Emulator with
  SpinDoctor's guessed value (RetroArch for any system not in EMULATOR_MAP)
  and adding a bare [<Emulator>] section without Emu_Path, which blocked
  RocketLauncher's fallback lookup to Global Emulators.ini.
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


# ─── generate_rl_system_ini — folder layout, existing file ───────────────────


def test_folder_layout_updates_emulators_ini(tmp_path):
    """When Settings/MAME/Emulators.ini already exists, only Rom_Path is
    updated and the flat Settings/MAME.ini is NOT created."""
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
    """Folder-layout Emulators.ini must use [ROMS], not [Settings].
    (Tested via the fresh-template path when the file is empty/has no Rom_Path.)"""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text("", encoding="utf-8")  # no Rom_Path= → fresh template

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert "[ROMS]" in body
    assert "[Settings]" not in body


def test_folder_layout_preserves_default_emulator(tmp_path):
    """generate_rl_system_ini must NOT overwrite Default_Emulator in an
    existing Emulators.ini.

    This is the primary root cause of the post-migration breakage: systems
    whose emulator SpinDoctor doesn't recognise (e.g. SSF for Sega Saturn,
    Mednafen for TurboGrafx-16, NullDC for Dreamcast) had Default_Emulator
    overwritten with the fallback 'RetroArch'.  RocketLauncher then searched
    for RetroArch's Emu_Path, found a bare [RetroArch] section added by
    SpinDoctor (no Emu_Path), stopped its lookup chain, and reported:
    'Could not find an Emu_path for RetroArch'."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "Sega Saturn" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\nDefault_Emulator=SSF\nRom_Path=D:\\old\\Sega Saturn\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("Sega Saturn", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    # SSF must be preserved — NOT replaced with RetroArch (the fallback guess).
    assert "Default_Emulator=SSF" in body
    assert "Default_Emulator=RetroArch" not in body
    # No [RetroArch] section should be injected.
    assert "[RetroArch]" not in body
    # Rom_Path must be updated.
    new_rom_path = str(Path(cfg.roms_dir) / "Sega Saturn")
    assert f"Rom_Path={new_rom_path}" in body


def test_folder_layout_preserves_emu_path(tmp_path):
    """Emu_Path in an existing [Emulator] section is preserved by the in-place
    update (the line is not touched because only Rom_Path= lines change)."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\n"
        "Default_Emulator=MAME\n"
        "Rom_Path=D:\\old\\MAME\n"
        "\n"
        "[MAME]\n"
        "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame64.exe\n"
        "Rom_Path=D:\\old\\MAME\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame64.exe" in body
    assert "Default_Emulator=MAME" in body
    new_rom_path = str(Path(cfg.roms_dir) / "MAME")
    assert f"Rom_Path={new_rom_path}" in body


def test_folder_layout_preserves_module_and_pause_keys(tmp_path):
    """Module= and Pause_*_Keys= from the original file are untouched."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\n"
        "Default_Emulator=MAME\n"
        "Rom_Path=D:\\old\\MAME\n"
        "\n"
        "[MAME]\n"
        "Emu_Path=..\\.\\Emulators\\MAME\\mame64.exe\n"
        "Rom_Extension=zip|7z|txt\n"
        "Module=MAME.ahk\n"
        "Pause_Save_State_Keys={Shift down}{F7 down}{Shift up}{F7 up}\n"
        "Pause_Load_State_Keys={F7 down}{F7 up}\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert "Module=MAME.ahk" in body
    assert "Pause_Save_State_Keys=" in body
    assert "Pause_Load_State_Keys=" in body
    assert "Rom_Extension=zip|7z|txt" in body


def test_no_extra_emulator_section_added_to_minimal_existing_file(tmp_path):
    """When an existing file has no [MAME] section (the normal cabinet format),
    generate_rl_system_ini must not inject one.

    The real cabinet per-system Emulators.ini files contain ONLY:
      [ROMS]
      Default_Emulator=<emulator>
      Rom_Path=<path>
    Adding a bare [<Emulator>] section without Emu_Path causes RocketLauncher
    to stop its lookup chain at the per-system file and fail with
    'Could not find an Emu_path' instead of falling back to Global Emulators.ini."""
    cfg, rl = _make_config(tmp_path)
    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\nDefault_Emulator=MAME\nRom_Path=D:\\old\\MAME\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    # Only [ROMS] section — no [MAME] section should be added.
    assert "[MAME]" not in body
    assert "Emu_Path=" not in body


# ─── generate_rl_system_ini — flat layout, existing file ─────────────────────


def test_flat_layout_updates_flat_ini(tmp_path):
    """When Settings/MAME.ini already exists, only Rom_Path is updated and the
    folder-layout file is NOT created."""
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


def test_flat_layout_preserves_default_emulator(tmp_path):
    """Default_Emulator is preserved for flat-layout files too."""
    cfg, rl = _make_config(tmp_path)
    flat_ini = rl / "Settings" / "Sega Saturn.ini"
    flat_ini.write_text(
        "[Settings]\nDefault_Emulator=SSF\nRom_Path=D:\\old\\Sega Saturn\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("Sega Saturn", cfg)

    body = flat_ini.read_text(encoding="utf-8")
    assert "Default_Emulator=SSF" in body
    assert "Default_Emulator=RetroArch" not in body


def test_flat_layout_preserves_emu_path(tmp_path):
    """Emu_Path is preserved in flat-layout files by the in-place update."""
    cfg, rl = _make_config(tmp_path)
    flat_ini = rl / "Settings" / "MAME.ini"
    flat_ini.write_text(
        "[Settings]\n"
        "Default_Emulator=MAME\n"
        "Rom_Path=D:\\old\\MAME\n"
        "\n"
        "[MAME]\n"
        "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame64.exe\n"
        "Rom_Path=D:\\old\\MAME\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = flat_ini.read_text(encoding="utf-8")
    assert "Emu_Path=D:\\Arcade\\Emulators\\MAME\\mame64.exe" in body
    new_rom_path = str(Path(cfg.roms_dir) / "MAME")
    assert f"Rom_Path={new_rom_path}" in body


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


# ─── generate_rl_system_ini — custom rom_path preservation ───────────────────


def test_preserves_valid_custom_rom_path_when_computed_path_absent(tmp_path):
    """When the existing Emulators.ini points at a directory that exists, but
    the computed path (roms_dir/system_name) does not exist, the current value
    is preserved.

    This is the MAME-variant case: 'MAME (Vector)' shares a single ROM
    folder (e.g. J:\\Games\\MAME) rather than having its own sibling folder
    (J:\\Games\\MAME (Vector)), which does not exist.  Prior to this fix,
    generate-config --apply would replace the working path with the
    non-existent variant folder, breaking every MAME (Vector) launch.
    """
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    # Only the shared MAME folder exists — MAME (Vector) folder does NOT.
    (roms / "MAME").mkdir(parents=True)
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    save_config(cfg)

    shared_path = str(roms / "MAME")
    emu_ini = rl / "Settings" / "MAME (Vector)" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        f"[ROMS]\nDefault_Emulator=MAME (Vector)\nRom_Path={shared_path}\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME (Vector)", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    # The shared MAME path must be preserved untouched.
    assert f"Rom_Path={shared_path}" in body
    # The non-existent per-variant path must NOT appear.
    bad_path = str(roms / "MAME (Vector)")
    assert bad_path not in body


def test_system_override_rom_path_wins_over_derived_path(tmp_path):
    """A rom_path value in system_overrides takes precedence over the default
    roms_dir/system_name derivation, allowing MAME variants to be configured
    with the shared ROM folder once instead of relying on the auto-preserve
    heuristic."""
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    override_dir = tmp_path / "shared" / "MAME"
    override_dir.mkdir(parents=True)
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    cfg.system_overrides = {"MAME (Vector)": {"rom_path": str(override_dir)}}
    save_config(cfg)

    generate_rl_system_ini("MAME (Vector)", cfg)

    emu_ini = rl / "Settings" / "MAME (Vector)" / "Emulators.ini"
    body = emu_ini.read_text(encoding="utf-8")
    assert f"Rom_Path={override_dir}" in body
    assert str(roms / "MAME (Vector)") not in body


def test_custom_path_guard_skipped_when_computed_path_exists(tmp_path):
    """When the computed path exists (a real migration — ROMs moved to a new
    drive), the preserve guard does not fire: the path is updated normally."""
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    # Both the old and new ROM directories exist.
    old_path = tmp_path / "old_roms" / "MAME"
    old_path.mkdir(parents=True)
    (roms / "MAME").mkdir(parents=True)
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    save_config(cfg)

    emu_ini = rl / "Settings" / "MAME" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        f"[ROMS]\nDefault_Emulator=MAME\nRom_Path={old_path}\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    new_path = str(roms / "MAME")
    # New path exists → guard does not fire → path is updated.
    assert f"Rom_Path={new_path}" in body
    assert str(old_path) not in body


# ─── MAME-variant auto-detection ─────────────────────────────────────────────


def test_mame_variant_name_falls_back_to_mame_rom_path(tmp_path):
    """New Emulators.ini for 'MAME (Vector)' uses roms_dir/MAME when the
    per-variant folder doesn't exist but roms_dir/MAME does."""
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    (roms / "MAME").mkdir(parents=True)   # only the shared folder exists
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    save_config(cfg)

    generate_rl_system_ini("MAME (Vector)", cfg)

    emu_ini = rl / "Settings" / "MAME (Vector)" / "Emulators.ini"
    body = emu_ini.read_text(encoding="utf-8")
    assert f"Rom_Path={roms / 'MAME'}" in body
    assert str(roms / "MAME (Vector)") not in body


def test_mame_emulator_guard_preserves_relative_rom_path(tmp_path):
    """When an existing Emulators.ini declares a MAME-family emulator and a
    relative Rom_Path (e.g. ..\\Games\\Mame\\roms written by RLUI), the path
    is left untouched — relative paths are resolved by RocketLauncher, not us."""
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    (roms / "MAME").mkdir(parents=True)
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    save_config(cfg)

    emu_ini = rl / "Settings" / "MAME Atari Classics" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    relative_path = r"..\Games\Mame\roms"
    emu_ini.write_text(
        f"[ROMS]\nDefault_Emulator=MAME\nRom_Path={relative_path}\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("MAME Atari Classics", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert f"Rom_Path={relative_path}" in body


def test_non_mame_named_system_with_mame_emulator_uses_mame_fallback(tmp_path):
    """Systems like '4-Player Games' that use a MAME-family emulator but have
    no 'MAME' in their name fall back to roms_dir/MAME when neither their own
    folder nor the computed path exists."""
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    (roms / "MAME").mkdir(parents=True)   # J:\Games\MAME exists
    (rl / "Settings").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), rocketlauncher_dir=str(rl))
    save_config(cfg)

    emu_ini = rl / "Settings" / "4-Player Games" / "Emulators.ini"
    emu_ini.parent.mkdir(parents=True)
    emu_ini.write_text(
        "[ROMS]\nDefault_Emulator=MAME (XBOX 4P DSW)\nRom_Path=J:\\Games\\4-Player Games\n",
        encoding="utf-8",
    )

    generate_rl_system_ini("4-Player Games", cfg)

    body = emu_ini.read_text(encoding="utf-8")
    assert f"Rom_Path={roms / 'MAME'}" in body
    assert "J:\\Games\\4-Player Games" not in body


def test_guess_emulator_returns_mame_for_mame_variant_names(tmp_path):
    """guess_emulator() returns 'MAME' for system names containing the word
    'MAME', without requiring an exact match in EMULATOR_MAP."""
    from spindoctor.rocketlauncher import guess_emulator
    assert guess_emulator("MAME (Vector)") == "MAME"
    assert guess_emulator("MAME Atari Classics") == "MAME"
    assert guess_emulator("MAME") == "MAME"
    assert guess_emulator("4-Player Games") == "RetroArch"  # unchanged
