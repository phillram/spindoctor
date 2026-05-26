"""PCLauncher per-game INI generation + Global Emulators integration."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from spindoctor.config import Config
from spindoctor.rocketlauncher import (
    EMULATOR_EXECUTABLES,
    EMULATOR_EXTENSIONS,
    EMULATOR_WINDOW_TITLES,
    _FADE_TITLE_TIMEOUT,
    _get_fade_title,
    ensure_rl_game_exe,
    generate_global_emulators_ini,
    generate_pclauncher_inis,
    guess_emulator,
    write_pclauncher_system_ini,
    _read_system_default_emulator,
    _read_emulator_exe,
    _read_pclauncher_game_exe,
    _get_app_wait_exe,
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


# ─── write_pclauncher_system_ini with AppWaitExe ─────────────────────────────

def test_write_pclauncher_system_ini_adds_app_wait_exe_for_mame(tmp_path):
    """AppWaitExe=mame.exe must appear when source system resolves to MAME."""
    rl = tmp_path / "rl"
    rl.mkdir()
    # MAME settings file so _read_system_default_emulator finds it
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
    assert "AppWaitExe=mame.exe" in body


def test_write_pclauncher_system_ini_no_app_wait_exe_for_pclauncher_source_without_ini(tmp_path):
    """AppWaitExe omitted when source is PCLauncher-based and no per-game INI exists."""
    rl = tmp_path / "rl"
    rl.mkdir()
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("my_pc_game", "PC Games", "my_pc_game")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "AppWaitExe" not in body


def test_write_pclauncher_system_ini_app_wait_exe_falls_back_to_dict(tmp_path):
    """AppWaitExe falls back to EMULATOR_EXECUTABLES when Global Emulators.ini absent."""
    rl = tmp_path / "rl"
    rl.mkdir()
    # No settings files at all — relies purely on guess_emulator + EMULATOR_EXECUTABLES
    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("tetris_snes", "Super Nintendo", "Tetris")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    # Super Nintendo → RetroArch → retroarch.exe
    assert "AppWaitExe=retroarch.exe" in body


def test_write_pclauncher_system_ini_mixed_sources(tmp_path):
    """MAME entries get AppWaitExe from emulator dict; PCLauncher entry without game INI omits it."""
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

    assert "AppWaitExe=mame.exe" in mame_block
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
    """PC game entries with a direct .exe path receive AppWaitExe= in the system INI."""
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
    assert "AppWaitExe=Hades.exe" in body


def test_write_pclauncher_system_ini_pc_game_with_lnk_omits_app_wait_exe(tmp_path):
    """PC game entries with a .lnk path omit AppWaitExe (shortcuts are not processes)."""
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
    assert "AppWaitExe" not in body


# ─── ensure_rl_game_exe ───────────────────────────────────────────────────────

def test_ensure_rl_game_exe_creates_copy(tmp_path):
    """Creates RocketLauncherGame.exe as a copy of RocketLauncher.exe."""
    rl = tmp_path / "rl"
    rl.mkdir()
    src = rl / "RocketLauncher.exe"
    src.write_bytes(b"\x00" * 2048)  # fake exe content

    dst = ensure_rl_game_exe(rl)

    assert dst == rl / "RocketLauncherGame.exe"
    assert dst.exists()
    assert dst.read_bytes() == src.read_bytes()


def test_ensure_rl_game_exe_updates_stale_copy(tmp_path):
    """Overwrites RocketLauncherGame.exe when its size differs from the source."""
    rl = tmp_path / "rl"
    rl.mkdir()
    src = rl / "RocketLauncher.exe"
    src.write_bytes(b"\x00" * 2048)
    dst_path = rl / "RocketLauncherGame.exe"
    dst_path.write_bytes(b"\xFF" * 512)  # stale/wrong size

    result = ensure_rl_game_exe(rl)

    assert result == dst_path
    assert dst_path.stat().st_size == src.stat().st_size


def test_ensure_rl_game_exe_skips_copy_when_up_to_date(tmp_path):
    """Does not re-copy when RocketLauncherGame.exe already has the correct size."""
    rl = tmp_path / "rl"
    rl.mkdir()
    src = rl / "RocketLauncher.exe"
    src.write_bytes(b"\x00" * 2048)
    dst_path = rl / "RocketLauncherGame.exe"
    dst_path.write_bytes(b"\xFF" * 2048)  # same size, different content
    mtime_before = dst_path.stat().st_mtime

    ensure_rl_game_exe(rl)

    # File should not have been touched (mtime unchanged)
    assert dst_path.stat().st_mtime == mtime_before


def test_ensure_rl_game_exe_falls_back_when_source_missing(tmp_path):
    """Returns RocketLauncher.exe path when source does not exist."""
    rl = tmp_path / "rl"
    rl.mkdir()

    result = ensure_rl_game_exe(rl)

    assert result == rl / "RocketLauncher.exe"
    assert not (rl / "RocketLauncherGame.exe").exists()


# ─── write_pclauncher_system_ini with rl_exe override ────────────────────────

def test_write_pclauncher_system_ini_uses_rl_exe_override(tmp_path):
    """Application= line uses the rl_exe path when provided."""
    rl = tmp_path / "rl"
    rl.mkdir()
    game_exe = rl / "RocketLauncherGame.exe"

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("balloon", "MAME", "balloon")],
        rl,
        rl_exe=game_exe,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "RocketLauncherGame.exe" in body
    assert "RocketLauncher.exe" not in body.replace("RocketLauncherGame.exe", "")


def test_write_pclauncher_system_ini_defaults_to_rl_exe_when_no_override(tmp_path):
    """Application= falls back to RocketLauncher.exe when rl_exe is not given."""
    rl = tmp_path / "rl"
    rl.mkdir()

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("balloon", "MAME", "balloon")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "RocketLauncher.exe" in body


# ─── FadeTitle / EMULATOR_WINDOW_TITLES ──────────────────────────────────────

def _write_emulators_ini(path: Path, emulator_name: str) -> None:
    """Write a folder-layout Emulators.ini for a given emulator name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"[ROMS]\nDefault_Emulator={emulator_name}\nRom_Path=C:\\Games\n",
        encoding="utf-8",
    )


def test_emulator_window_titles_has_known_emulators():
    """Spot-check that key emulators have window titles defined."""
    assert "MAME" in EMULATOR_WINDOW_TITLES
    assert "ZiNc" in EMULATOR_WINDOW_TITLES
    assert "RetroArch" in EMULATOR_WINDOW_TITLES


def test_get_fade_title_returns_title_for_known_emulator(tmp_path):
    """Returns the correct window-title fragment for a known emulator."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Zinc" / "Emulators.ini", "ZiNc")
    title = _get_fade_title("Zinc", rl)
    assert title == EMULATOR_WINDOW_TITLES["ZiNc"]


def test_get_fade_title_returns_empty_for_unknown_emulator(tmp_path):
    """Returns empty string when the emulator is not in EMULATOR_WINDOW_TITLES."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Sega Model 2" / "Emulators.ini", "Model 2")
    title = _get_fade_title("Sega Model 2", rl)
    assert title == ""


def test_get_fade_title_returns_empty_for_pclauncher_system(tmp_path):
    """PCLauncher-based source systems return empty (no emulator window)."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "PC Games" / "Emulators.ini", "PCLauncher")
    title = _get_fade_title("PC Games", rl)
    assert title == ""


def test_get_fade_title_returns_empty_when_no_settings(tmp_path):
    """Returns empty string gracefully when no settings files exist."""
    rl = tmp_path / "rl"
    rl.mkdir()
    title = _get_fade_title("Zinc", rl)
    assert title == ""


def test_write_pclauncher_system_ini_adds_fade_title_for_known_emulator(tmp_path):
    """FadeTitle= and FadeTitleTimeout= are written for emulators in EMULATOR_WINDOW_TITLES."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Zinc" / "Emulators.ini", "ZiNc")
    # Also write global emulators so _read_emulator_exe can find ZiNc.exe
    global_ini = rl / "Settings" / "Global Emulators.ini"
    global_ini.parent.mkdir(parents=True, exist_ok=True)
    global_ini.write_text(
        "[ZiNc]\nEmu_Path=..\\Emulators\\ZiNc\\ZiNc.exe\nModule=ZiNc.ahk\n",
        encoding="utf-8",
    )

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("tondemo", "Zinc", "tondemo")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle=ZiNc" in body
    assert f"FadeTitleTimeout={_FADE_TITLE_TIMEOUT}" in body


def test_write_pclauncher_system_ini_omits_fade_title_for_unknown_emulator(tmp_path):
    """FadeTitle= is omitted when the emulator is not in EMULATOR_WINDOW_TITLES."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Sega Model 2" / "Emulators.ini", "Model 2")

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("vf2", "Sega Model 2", "vf2")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle" not in body
    assert "FadeTitleTimeout" not in body


def test_write_pclauncher_system_ini_fade_title_with_app_wait_exe(tmp_path):
    """Both AppWaitExe= and FadeTitle= appear when emulator is fully resolved."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "MAME" / "Emulators.ini", "MAME")
    global_ini = rl / "Settings" / "Global Emulators.ini"
    global_ini.parent.mkdir(parents=True, exist_ok=True)
    global_ini.write_text(
        "[MAME]\nEmu_Path=..\\Emulators\\MAME\\mame.exe\nModule=MAME.ahk\n",
        encoding="utf-8",
    )

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("1942", "MAME", "1942")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "AppWaitExe=mame.exe" in body
    assert "FadeTitle=MAME" in body
    assert f"FadeTitleTimeout={_FADE_TITLE_TIMEOUT}" in body


def test_get_fade_title_user_config_overrides_builtin(tmp_path):
    """User-supplied extra dict takes precedence over the built-in table."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "MAME" / "Emulators.ini", "MAME")
    # Override built-in "MAME" entry with custom title
    title = _get_fade_title("MAME", rl, extra={"MAME": "MyMAME"})
    assert title == "MyMAME"


def test_get_fade_title_user_config_adds_unknown_emulator(tmp_path):
    """User-supplied extra dict covers emulators not in the built-in table."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Sega Model 2" / "Emulators.ini", "Model 2")
    title = _get_fade_title("Sega Model 2", rl, extra={"Model 2": "Sega Model 2"})
    assert title == "Sega Model 2"


def test_write_pclauncher_system_ini_respects_extra_window_titles(tmp_path):
    """extra_window_titles parameter is used for FadeTitle= resolution."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Sega Model 2" / "Emulators.ini", "Model 2")

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("vf2", "Sega Model 2", "vf2")],
        rl,
        extra_window_titles={"Model 2": "Sega Model 2"},
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle=Sega Model 2" in body
    assert f"FadeTitleTimeout={_FADE_TITLE_TIMEOUT}" in body
