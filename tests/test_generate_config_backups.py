"""generate-config backups: one per file, never overwritten.

Every folder-layout system keeps its RocketLauncher settings in a file named
``Emulators.ini``.  With ``backup_dir`` set, generate-config used to back
them all up into one flat ``backup_dir/RocketLauncher/`` folder as
``Emulators.ini.<YYYYMMDD_HHMMSS>.bak``, so every system written in the same
second got the same backup name and only the last one survived.  On a run
over ~120 systems, 3 backups were left.
"""
from __future__ import annotations

from datetime import datetime

import spindoctor.cli as cli_mod
from spindoctor.config import Config

SYSTEMS = ("Sega Dreamcast", "Sony Playstation", "Nintendo 64")


class _FrozenDateTime:
    """Every backup in these tests is stamped in the same second."""

    @classmethod
    def now(cls):
        return datetime(2026, 6, 14, 17, 46, 35)


def _rl_tree(tmp_path):
    rl = tmp_path / "RocketLauncher"
    for system in SYSTEMS:
        ini = rl / "Settings" / system / "Emulators.ini"
        ini.parent.mkdir(parents=True)
        ini.write_text(
            f"[ROMS]\nDefault_Emulator=RetroArch\nRom_Path=J:\\Games\\{system}\n",
            encoding="utf-8",
        )
    return rl


def test_same_named_inis_get_one_backup_each(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "datetime", _FrozenDateTime)
    rl = _rl_tree(tmp_path)
    cfg = Config(rocketlauncher_dir=str(rl), backup_dir=str(tmp_path / "backups"))

    baks = [
        cli_mod._generate_config_backup(rl / "Settings" / s / "Emulators.ini", cfg)
        for s in SYSTEMS
    ]

    assert len(set(baks)) == len(SYSTEMS)
    # The backup mirrors the file's place under rocketlauncher_dir.
    root = tmp_path / "backups" / "RocketLauncher" / "Settings"
    for system, bak in zip(SYSTEMS, baks):
        assert bak == root / system / "Emulators.ini.20260614_174635.bak"
        assert f"Rom_Path=J:\\Games\\{system}" in bak.read_text(encoding="utf-8")


def test_flat_layout_ini_backup_lands_in_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "datetime", _FrozenDateTime)
    rl = tmp_path / "RocketLauncher"
    flat = rl / "Settings" / "Sega Saturn.ini"
    flat.parent.mkdir(parents=True)
    flat.write_text("[Settings]\nRom_Path=J:\\Games\\Sega Saturn\n", encoding="utf-8")
    cfg = Config(rocketlauncher_dir=str(rl), backup_dir=str(tmp_path / "backups"))

    bak = cli_mod._generate_config_backup(flat, cfg)

    assert bak == (tmp_path / "backups" / "RocketLauncher" / "Settings"
                   / "Sega Saturn.ini.20260614_174635.bak")


def test_file_outside_rocketlauncher_dir_keeps_its_folder_name(tmp_path, monkeypatch):
    """Main Menu.xml lives under the HyperSpin databases, not under RL."""
    monkeypatch.setattr(cli_mod, "datetime", _FrozenDateTime)
    rl = _rl_tree(tmp_path)
    menu = tmp_path / "HyperSpin" / "Databases" / "Main Menu" / "Main Menu.xml"
    menu.parent.mkdir(parents=True)
    menu.write_text("<menu/>\n", encoding="utf-8")
    cfg = Config(rocketlauncher_dir=str(rl), backup_dir=str(tmp_path / "backups"))

    bak = cli_mod._generate_config_backup(menu, cfg)

    assert bak == (tmp_path / "backups" / "RocketLauncher" / "Main Menu"
                   / "Main Menu.xml.20260614_174635.bak")


def test_second_backup_of_same_file_in_same_second_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "datetime", _FrozenDateTime)
    rl = _rl_tree(tmp_path)
    cfg = Config(rocketlauncher_dir=str(rl), backup_dir=str(tmp_path / "backups"))
    ini = rl / "Settings" / "Sega Dreamcast" / "Emulators.ini"

    first = cli_mod._generate_config_backup(ini, cfg)
    ini.write_text("[ROMS]\nRom_Path=E:\\Games\\Sega Dreamcast\n", encoding="utf-8")
    second = cli_mod._generate_config_backup(ini, cfg)

    assert second != first
    assert second.name == "Emulators.ini.20260614_174635_2.bak"
    assert "J:\\Games" in first.read_text(encoding="utf-8")
    assert "E:\\Games" in second.read_text(encoding="utf-8")


def test_sidecar_backups_without_backup_dir_are_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "datetime", _FrozenDateTime)
    rl = _rl_tree(tmp_path)
    cfg = Config(rocketlauncher_dir=str(rl))
    ini = rl / "Settings" / "Sega Dreamcast" / "Emulators.ini"

    first = cli_mod._generate_config_backup(ini, cfg)
    second = cli_mod._generate_config_backup(ini, cfg)

    assert first == ini.parent / "Emulators.20260614_174635.bak"
    assert second == ini.parent / "Emulators.20260614_174635_2.bak"
    # Both stay visible to `backup sidecar list`.
    assert cli_mod._find_sidecars(ini) == [second, first]
