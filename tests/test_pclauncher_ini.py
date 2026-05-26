"""PCLauncher per-game INI generation + Global Emulators integration."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from spindoctor.config import Config
from spindoctor.rocketlauncher import (
    EMULATOR_EXECUTABLES,
    EMULATOR_EXTENSIONS,
    EMULATOR_WINDOW_TITLES,
    generate_global_emulators_ini,
    generate_pclauncher_inis,
    guess_emulator,
    write_pclauncher_system_ini,
    _read_system_default_emulator,
    _read_emulator_exe,
    _read_pclauncher_game_exe,
    _get_app_wait_exe,
    _get_fade_title,
)


def test_pclauncher_in_emulator_dicts():
    assert EMULATOR_EXECUTABLES["PCLauncher"] == "PCLauncher.exe"
    assert "exe" in EMULATOR_EXTENSIONS["PCLauncher"]
    assert "lnk" in EMULATOR_EXTENSIONS["PCLauncher"]
    assert "url" in EMULATOR_EXTENSIONS["PCLauncher"]


@pytest.mark.parametrize("name", [
    "PC", "PC Games", "Windows", "Windows Games", "Steam", "Steam Games",
])
def test_guess_emulator_routes_pc_aliases_to_pclauncher(name):
    assert guess_emulator(name) == "PCLauncher"


def test_global_emulators_ini_includes_pclauncher_block(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    p, status = generate_global_emulators_ini(cfg)
    assert status == "created"
    text = p.read_text(encoding="utf-8")
    assert "[PCLauncher]" in text
    assert "PCLauncher.exe" in text
    assert "exe|lnk|url|bat" in text


def test_generate_pclauncher_inis_writes_per_game_files(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    # PureWindowsPath so .parent works on macOS / Linux test runners.
    titles = {
        "Cyberpunk 2077": PureWindowsPath(r"C:\Games\Cyberpunk 2077\bin\launcher.exe"),
        "Hades": PureWindowsPath(r"C:\Games\Hades.lnk"),
    }
    module_dir, written, skipped = generate_pclauncher_inis(
        "PC Games", titles, cfg,
    )
    assert module_dir.name == "PC Games"
    assert module_dir.parent.name == "PCLauncher"
    assert len(written) == 2
    assert skipped == []

    cyber = (module_dir / "Cyberpunk 2077.ini").read_text(encoding="utf-8")
    assert r"ApplicationPath=C:\Games\Cyberpunk 2077\bin\launcher.exe" in cyber
    assert r"StartIn=C:\Games\Cyberpunk 2077\bin" in cyber
    assert "ApplicationParameters=" in cyber

    hades = (module_dir / "Hades.ini").read_text(encoding="utf-8")
    assert r"ApplicationPath=C:\Games\Hades.lnk" in hades


def test_generate_pclauncher_inis_skips_existing_unless_overwrite(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    titles = {"Hades": Path(r"C:\Games\Hades.lnk")}
    module_dir, written, _ = generate_pclauncher_inis(
        "PC Games", titles, cfg,
    )
    # Mutate the file the user might have customised.
    (module_dir / "Hades.ini").write_text("custom\n", encoding="utf-8")

    _, written2, skipped2 = generate_pclauncher_inis(
        "PC Games", titles, cfg,
    )
    assert written2 == []
    assert len(skipped2) == 1
    assert (module_dir / "Hades.ini").read_text(encoding="utf-8") == "custom\n"

    _, written3, _ = generate_pclauncher_inis(
        "PC Games", titles, cfg, overwrite=True,
    )
    assert len(written3) == 1
    assert "ApplicationPath" in (module_dir / "Hades.ini").read_text(encoding="utf-8")


def test_generate_pclauncher_inis_requires_rocketlauncher_dir(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
    )
    with pytest.raises(ValueError, match="rocketlauncher_dir"):
        generate_pclauncher_inis(
            "PC Games", {"Hades": Path(r"C:\Games\Hades.lnk")}, cfg,
        )


# ─── _read_system_default_emulator ────────────────────────────────────────────

def test_read_system_default_emulator_folder_layout(tmp_path):
    """Reads Default_Emulator from Settings/<system>/Emulators.ini [ROMS]."""
    rl = tmp_path / "rl"
    folder = rl / "Settings" / "MAME"
    folder.mkdir(parents=True)
    (folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=MAME\nRom_Path=D:\\roms\\MAME\n",
        encoding="utf-8",
    )
    assert _read_system_default_emulator("MAME", rl) == "MAME"


def test_read_system_default_emulator_flat_layout(tmp_path):
    """Falls through to flat Settings/<system>.ini [Settings] when folder INI absent."""
    rl = tmp_path / "rl"
    settings = rl / "Settings"
    settings.mkdir(parents=True)
    (settings / "Super Nintendo.ini").write_text(
        "[Settings]\nDefault_Emulator=RetroArch\n",
        encoding="utf-8",
    )
    assert _read_system_default_emulator("Super Nintendo", rl) == "RetroArch"


def test_read_system_default_emulator_prefers_folder_over_flat(tmp_path):
    """Folder layout takes precedence when both files exist."""
    rl = tmp_path / "rl"
    folder = rl / "Settings" / "MAME"
    folder.mkdir(parents=True)
    (folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=MAME\n", encoding="utf-8",
    )
    (rl / "Settings" / "MAME.ini").write_text(
        "[Settings]\nDefault_Emulator=RetroArch\n", encoding="utf-8",
    )
    assert _read_system_default_emulator("MAME", rl) == "MAME"


def test_read_system_default_emulator_missing_returns_empty(tmp_path):
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _read_system_default_emulator("DoesNotExist", rl) == ""


# ─── _read_emulator_exe ───────────────────────────────────────────────────────

def test_read_emulator_exe_from_emu_path(tmp_path):
    """Reads exe name from Emu_Path key (cabinet variant)."""
    rl = tmp_path / "rl"
    settings = rl / "Settings"
    settings.mkdir(parents=True)
    (settings / "Global Emulators.ini").write_text(
        "[MAME]\nEmu_Path=D:\\Arcade\\Emulators\\MAME\\mame.exe\n",
        encoding="utf-8",
    )
    assert _read_emulator_exe("MAME", rl) == "mame.exe"


def test_read_emulator_exe_from_emulator_application_path(tmp_path):
    """Reads exe name from Emulator_Application_Path key (standard variant)."""
    rl = tmp_path / "rl"
    settings = rl / "Settings"
    settings.mkdir(parents=True)
    (settings / "Global Emulators.ini").write_text(
        "[RetroArch]\nEmulator_Application_Path=C:\\RetroArch\\retroarch.exe\n",
        encoding="utf-8",
    )
    assert _read_emulator_exe("RetroArch", rl) == "retroarch.exe"


def test_read_emulator_exe_falls_back_to_dict_when_global_ini_absent(tmp_path):
    """Falls back to EMULATOR_EXECUTABLES when Global Emulators.ini doesn't exist."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _read_emulator_exe("MAME", rl) == "mame.exe"
    assert _read_emulator_exe("RetroArch", rl) == "retroarch.exe"


def test_read_emulator_exe_unknown_emulator_returns_empty(tmp_path):
    """Returns empty string for a completely unknown emulator."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _read_emulator_exe("SomeUnknownEmu", rl) == ""


# ─── _get_app_wait_exe ────────────────────────────────────────────────────────

def test_get_app_wait_exe_resolves_via_guess_emulator(tmp_path):
    """For a MAME system with no settings files, guesses MAME → mame.exe."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _get_app_wait_exe("MAME", rl) == "mame.exe"


def test_get_app_wait_exe_uses_rl_settings_over_guess(tmp_path):
    """When RL settings file names a specific emulator, that takes precedence."""
    rl = tmp_path / "rl"
    folder = rl / "Settings" / "Arcade"
    folder.mkdir(parents=True)
    (folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=MAME\n", encoding="utf-8",
    )
    assert _get_app_wait_exe("Arcade", rl) == "mame.exe"


def test_get_app_wait_exe_returns_empty_for_pclauncher_source(tmp_path):
    """PCLauncher-based source systems return empty — can't determine game exe."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _get_app_wait_exe("PC Games", rl) == ""
    assert _get_app_wait_exe("Windows", rl) == ""


# ─── EMULATOR_WINDOW_TITLES sanity checks ────────────────────────────────────

def test_emulator_window_titles_covers_core_emulators():
    """Core emulators used in test fixtures must have FadeTitle entries."""
    for emu in ("MAME", "RetroArch", "ZiNc", "Dolphin", "PCSX2"):
        assert emu in EMULATOR_WINDOW_TITLES, f"{emu} missing from EMULATOR_WINDOW_TITLES"


# ─── _get_fade_title ─────────────────────────────────────────────────────────

def test_get_fade_title_resolves_zinc_via_rl_settings(tmp_path):
    """ZiNc system with RL settings resolves to FadeTitle 'ZiNc'."""
    rl = tmp_path / "rl"
    folder = rl / "Settings" / "Zinc"
    folder.mkdir(parents=True)
    (folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=ZiNc\n", encoding="utf-8",
    )
    assert _get_fade_title("Zinc", rl) == "ZiNc"


def test_get_fade_title_resolves_retroarch_via_guess(tmp_path):
    """Super Nintendo → RetroArch → 'RetroArch' when no RL settings exist."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _get_fade_title("Super Nintendo", rl) == "RetroArch"


def test_get_fade_title_resolves_mame_via_guess(tmp_path):
    """MAME system → 'MAME' when no RL settings exist."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _get_fade_title("MAME", rl) == "MAME"


def test_get_fade_title_returns_empty_for_pclauncher_source(tmp_path):
    """PCLauncher-based source systems return empty — per-game window title unknown."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _get_fade_title("PC Games", rl) == ""
    assert _get_fade_title("Windows", rl) == ""


def test_get_fade_title_returns_empty_for_unknown_emulator(tmp_path):
    """Emulators absent from EMULATOR_WINDOW_TITLES return empty string."""
    rl = tmp_path / "rl"
    folder = rl / "Settings" / "SomeSystem"
    folder.mkdir(parents=True)
    (folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=ObscureEmu2000\n", encoding="utf-8",
    )
    assert _get_fade_title("SomeSystem", rl) == ""


# ─── write_pclauncher_system_ini with FadeTitle / AppWaitExe ─────────────────

def test_write_pclauncher_system_ini_uses_fade_title_for_mame(tmp_path):
    """FadeTitle=MAME must appear (not AppWaitExe) when source system resolves to MAME."""
    rl = tmp_path / "rl"
    mame_folder = rl / "Settings" / "MAME"
    mame_folder.mkdir(parents=True)
    (mame_folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=MAME\n", encoding="utf-8",
    )

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("balloon", "MAME", "balloon")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle=MAME" in body
    assert "AppWaitExe" not in body


def test_write_pclauncher_system_ini_uses_fade_title_for_zinc(tmp_path):
    """FadeTitle=ZiNc must appear when source system resolves to ZiNc emulator."""
    rl = tmp_path / "rl"
    zinc_folder = rl / "Settings" / "Zinc"
    zinc_folder.mkdir(parents=True)
    (zinc_folder / "Emulators.ini").write_text(
        "[ROMS]\nDefault_Emulator=ZiNc\n", encoding="utf-8",
    )

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("tondemo", "Zinc", "tondemo")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle=ZiNc" in body
    assert "AppWaitExe" not in body


def test_write_pclauncher_system_ini_fade_title_for_retroarch_via_guess(tmp_path):
    """FadeTitle=RetroArch appears when guess_emulator resolves the system."""
    rl = tmp_path / "rl"
    rl.mkdir()
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("tetris_snes", "Super Nintendo", "Tetris")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle=RetroArch" in body
    assert "AppWaitExe" not in body


def test_write_pclauncher_system_ini_no_fade_title_for_pclauncher_source_without_ini(tmp_path):
    """Neither FadeTitle nor AppWaitExe when source is PCLauncher-based and no per-game INI."""
    rl = tmp_path / "rl"
    rl.mkdir()
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("my_pc_game", "PC Games", "my_pc_game")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle" not in body
    assert "AppWaitExe" not in body


def test_write_pclauncher_system_ini_mixed_sources(tmp_path):
    """MAME entries get FadeTitle; PCLauncher source without game INI gets neither."""
    rl = tmp_path / "rl"
    rl.mkdir()
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [
            ("mame_game", "MAME", "strider"),
            ("pc_game", "PC Games", "mygame"),
        ],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")

    mame_block = body.split("[mame_game]")[1].split("[")[0]
    pc_block = body.split("[pc_game]")[1]

    assert "FadeTitle=MAME" in mame_block
    assert "AppWaitExe" not in mame_block
    assert "FadeTitle" not in pc_block
    assert "AppWaitExe" not in pc_block


# ─── _read_pclauncher_game_exe ────────────────────────────────────────────────

def test_read_pclauncher_game_exe_finds_exe_path(tmp_path):
    """Reads ApplicationPath from Settings-format per-game PCLauncher INI."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Games\\Hades\\Hades.exe\n",
        encoding="utf-8",
    )
    assert _read_pclauncher_game_exe("PC Games", "Hades", rl) == "Hades.exe"


def test_read_pclauncher_game_exe_ignores_lnk(tmp_path):
    """Returns empty string when ApplicationPath is a .lnk shortcut (not a process name)."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Users\\Public\\Desktop\\Hades.lnk\n",
        encoding="utf-8",
    )
    assert _read_pclauncher_game_exe("PC Games", "Hades", rl) == ""


def test_read_pclauncher_game_exe_ignores_bat(tmp_path):
    """Returns empty string when ApplicationPath is a .bat file."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Games\\launch.bat\n",
        encoding="utf-8",
    )
    assert _read_pclauncher_game_exe("PC Games", "Hades", rl) == ""


def test_read_pclauncher_game_exe_missing_ini(tmp_path):
    """Returns empty string when the per-game INI doesn't exist."""
    rl = tmp_path / "rl"
    rl.mkdir()
    assert _read_pclauncher_game_exe("PC Games", "Hades", rl) == ""


def test_get_app_wait_exe_pclauncher_source_with_exe_game_ini(tmp_path):
    """For PCLauncher source, reads AppWaitExe from per-game INI when path is .exe."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Games\\Hades\\Hades.exe\n",
        encoding="utf-8",
    )
    assert _get_app_wait_exe("PC Games", rl, "Hades") == "Hades.exe"


def test_get_app_wait_exe_pclauncher_source_with_lnk_returns_empty(tmp_path):
    """For PCLauncher source with .lnk path, returns empty (lnk is not a process)."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Users\\Public\\Desktop\\Hades.lnk\n",
        encoding="utf-8",
    )
    assert _get_app_wait_exe("PC Games", rl, "Hades") == ""


def test_write_pclauncher_system_ini_pc_game_with_exe_gets_app_wait_exe(tmp_path):
    """PC game entries with a direct .exe path fall back to AppWaitExe (FadeTitle unknown)."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Games\\Hades\\Hades.exe\n",
        encoding="utf-8",
    )
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("Hades", "PC Games", "Hades")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle" not in body
    assert "AppWaitExe=Hades.exe" in body


def test_write_pclauncher_system_ini_pc_game_with_lnk_omits_both(tmp_path):
    """PC game entries with a .lnk path omit FadeTitle and AppWaitExe."""
    rl = tmp_path / "rl"
    game_dir = rl / "Modules" / "PCLauncher" / "PC Games"
    game_dir.mkdir(parents=True)
    (game_dir / "Hades.ini").write_text(
        "[Settings]\nApplicationPath=C:\\Users\\Public\\Desktop\\Hades.lnk\n",
        encoding="utf-8",
    )
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("Hades", "PC Games", "Hades")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle" not in body
    assert "AppWaitExe" not in body
