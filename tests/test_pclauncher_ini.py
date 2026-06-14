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
    _resolve_pclauncher_exe,
    _win_safe_stem,
    ensure_rl_game_exe,
    generate_global_emulators_ini,
    generate_pclauncher_inis,
    guess_emulator,
    list_exe_candidates,
    _pick_best_exe,
    read_pclauncher_ini_application_path,
    rewrite_pclauncher_application,
    write_pclauncher_system_ini,
    write_toolkit_module_ini,
    _read_system_default_emulator,
    _read_emulator_exe,
    _read_pclauncher_game_exe,
    _get_app_wait_exe,
)


def test_pclauncher_in_emulator_dicts():
    assert EMULATOR_EXECUTABLES["PCLauncher"] == "PCLauncher.exe"
    # PCLauncher "ROMs" are always per-game INI files — the application
    # executable lives inside the INI, not used directly as a ROM file.
    assert EMULATOR_EXTENSIONS["PCLauncher"] == "ini"


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
    # PCLauncher ROMs are per-game INI files; Rom_Extension must be "ini"
    # so RL finds the placeholder .ini files for all PCLauncher systems
    # (synthetic wheels and PC Games alike).
    assert "Rom_Extension=ini" in text


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
    assert "[Cyberpunk 2077]" in cyber
    assert r"Application=C:\Games\Cyberpunk 2077\bin\launcher.exe" in cyber
    assert r"WorkingFolder=C:\Games\Cyberpunk 2077\bin" in cyber

    hades = (module_dir / "Hades.ini").read_text(encoding="utf-8")
    assert "[Hades]" in hades
    assert r"Application=C:\Games\Hades.lnk" in hades


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
    assert "Application=" in (module_dir / "Hades.ini").read_text(encoding="utf-8")


def test_generate_pclauncher_inis_requires_rocketlauncher_dir(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
    )
    with pytest.raises(ValueError, match="rocketlauncher_dir"):
        generate_pclauncher_inis(
            "PC Games", {"Hades": Path(r"C:\Games\Hades.lnk")}, cfg,
        )


# ─── _win_safe_stem ───────────────────────────────────────────────────────────

def test_win_safe_stem_strips_colon():
    assert _win_safe_stem("Submachine: Legacy") == "Submachine Legacy"


def test_win_safe_stem_strips_all_forbidden_chars():
    assert _win_safe_stem('A\\B/C:D*E?F"G<H>I|J') == "ABCDEFGHIJ"


def test_win_safe_stem_passthrough_for_safe_title():
    assert _win_safe_stem("Hades") == "Hades"
    assert _win_safe_stem("Mega Man X") == "Mega Man X"


# ─── generate_pclauncher_inis with title_to_section ──────────────────────────

def test_generate_pclauncher_inis_title_to_section_uses_dbname_in_header(tmp_path):
    """When title_to_section is provided, section header uses the dbName (colon intact)
    while the filename uses the Windows-safe stem."""
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    exe = PureWindowsPath(r"J:\Games\PC GAMES\Submachine Legacy\webcache.zip")
    titles = {"Submachine Legacy": exe}
    section_map = {"Submachine Legacy": "Submachine: Legacy"}

    module_dir, written, _ = generate_pclauncher_inis(
        "PC Games", titles, cfg, title_to_section=section_map,
    )

    ini = module_dir / "Submachine Legacy.ini"
    assert ini in written
    content = ini.read_text(encoding="utf-8")
    assert "[Submachine: Legacy]" in content
    assert "[Submachine Legacy]" not in content
    assert r"Application=J:\Games\PC GAMES\Submachine Legacy\webcache.zip" in content


def test_generate_pclauncher_inis_no_section_map_uses_title_as_section(tmp_path):
    """Without title_to_section the section header equals the title (existing behaviour)."""
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    titles = {"Hades": PureWindowsPath(r"C:\Games\Hades\Hades.exe")}
    module_dir, written, _ = generate_pclauncher_inis("PC Games", titles, cfg)

    content = (module_dir / "Hades.ini").read_text(encoding="utf-8")
    assert "[Hades]" in content


# ─── read_pclauncher_ini_application_path ────────────────────────────────────

def test_read_pclauncher_ini_application_path_new_format(tmp_path):
    """Reads Application= from [game_name] section (new PCLauncher.ahk format)."""
    ini = tmp_path / "Master Key.ini"
    ini.write_text(
        "[Master Key]\nApplication=J:\\Games\\PC Games\\Master Key\\MasterKey.exe\nWorkingFolder=J:\\Games\\PC Games\\Master Key\n",
        encoding="utf-8",
    )
    assert read_pclauncher_ini_application_path(ini) == r"J:\Games\PC Games\Master Key\MasterKey.exe"


def test_read_pclauncher_ini_application_path_old_format_returns_empty(tmp_path):
    """Old [Settings]/ApplicationPath= format returns '' — treated as stale."""
    ini = tmp_path / "Hades.ini"
    ini.write_text(
        "[Settings]\nApplicationPath=C:\\Games\\Hades\\Hades.exe\nStartIn=C:\\Games\\Hades\n",
        encoding="utf-8",
    )
    assert read_pclauncher_ini_application_path(ini) == ""


def test_read_pclauncher_ini_application_path_missing_file(tmp_path):
    """Returns '' when the INI file does not exist."""
    assert read_pclauncher_ini_application_path(tmp_path / "NoGame.ini") == ""


def test_read_pclauncher_ini_application_path_wrong_section_returns_empty(tmp_path):
    """Returns '' when Application= is in a different section than the filename stem."""
    ini = tmp_path / "Hades.ini"
    ini.write_text(
        "[SomeOtherGame]\nApplication=C:\\Games\\Hades\\Hades.exe\n",
        encoding="utf-8",
    )
    assert read_pclauncher_ini_application_path(ini) == ""


def test_read_pclauncher_ini_application_path_case_insensitive_section(tmp_path):
    """Section name match is case-insensitive."""
    ini = tmp_path / "Hades.ini"
    ini.write_text(
        "[HADES]\nApplication=C:\\Games\\Hades\\Hades.exe\n",
        encoding="utf-8",
    )
    assert read_pclauncher_ini_application_path(ini) == r"C:\Games\Hades\Hades.exe"


def test_read_pclauncher_ini_application_path_section_name_override_colon(tmp_path):
    """section_name override finds a section whose header has a colon not in the filename."""
    ini = tmp_path / "Submachine Legacy.ini"
    ini.write_text(
        "[Submachine: Legacy]\nApplication=J:\\Games\\sub.exe\n",
        encoding="utf-8",
    )
    # Without override: stem is "Submachine Legacy" → no match for "[Submachine: Legacy]"
    assert read_pclauncher_ini_application_path(ini) == ""
    # With override using the dbName: finds the section
    assert read_pclauncher_ini_application_path(
        ini, section_name="Submachine: Legacy"
    ) == r"J:\Games\sub.exe"


def test_read_pclauncher_ini_application_path_section_name_detects_old_stripped_header(tmp_path):
    """section_name override returns '' when INI still has the colon-stripped header.

    This is the core stale-detection fix: an INI written by an older SpinDoctor version
    with [Submachine Legacy] (no colon) looks 'current' without the override but is
    correctly flagged as missing (stale) when the dbName 'Submachine: Legacy' is used.
    """
    ini = tmp_path / "Submachine Legacy.ini"
    ini.write_text(
        "[Submachine Legacy]\nApplication=J:\\Games\\sub.exe\n",
        encoding="utf-8",
    )
    # Without override: stem matches → returns the path (false "current")
    assert read_pclauncher_ini_application_path(ini) == r"J:\Games\sub.exe"
    # With override (dbName with colon): no match → stale detected
    assert read_pclauncher_ini_application_path(
        ini, section_name="Submachine: Legacy"
    ) == ""


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


def test_emulator_window_titles_correction_table_has_zinc():
    """ZiNc entry is kept as a documented correction-table example."""
    assert "ZiNc" in EMULATOR_WINDOW_TITLES


def test_get_fade_title_returns_title_for_correction_table_emulator(tmp_path):
    """Returns the correction-table value when the emulator has an explicit entry."""
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Zinc" / "Emulators.ini", "ZiNc")
    title = _get_fade_title("Zinc", rl)
    assert title == EMULATOR_WINDOW_TITLES["ZiNc"]


def test_get_fade_title_returns_emulator_name_for_unknown_emulator(tmp_path):
    """Falls back to the emulator name itself when not in EMULATOR_WINDOW_TITLES.

    AHK WinWait uses case-insensitive partial matching, so the emulator name
    (e.g. 'Model 2') will match any window title that contains it.
    """
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Sega Model 2" / "Emulators.ini", "Model 2")
    title = _get_fade_title("Sega Model 2", rl)
    assert title == "Model 2"


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


def test_write_pclauncher_system_ini_uses_emulator_name_as_fade_title_for_unknown(tmp_path):
    """FadeTitle= uses the emulator name when not in EMULATOR_WINDOW_TITLES.

    AHK partial matching means 'Model 2' in FadeTitle= will match any window
    whose title contains 'Model 2', so no explicit entry is needed for most emulators.
    """
    rl = tmp_path / "rl"
    _write_emulators_ini(rl / "Settings" / "Sega Model 2" / "Emulators.ini", "Model 2")

    ini_path = write_pclauncher_system_ini(
        "Favorites",
        [("vf2", "Sega Model 2", "vf2")],
        rl,
    )
    body = ini_path.read_text(encoding="utf-8")
    assert "FadeTitle=Model 2" in body
    assert f"FadeTitleTimeout={_FADE_TITLE_TIMEOUT}" in body


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


# ─── write_toolkit_module_ini ─────────────────────────────────────────────────

def test_write_toolkit_module_ini_creates_fresh(tmp_path):
    """Creates Modules/PCLauncher/<system>.ini with Application= for each tool."""
    rl = tmp_path / "rl"
    bat_dir = tmp_path / "Toolkit"
    bat_dir.mkdir()
    entries = [
        ("Refresh Recently Played", bat_dir / "Refresh Recently Played.bat"),
        ("Refresh Favorites", bat_dir / "Refresh Favorites.bat"),
    ]
    module_ini = write_toolkit_module_ini("Toolkit", entries, rl)

    assert module_ini == rl / "Modules" / "PCLauncher" / "Toolkit.ini"
    body = module_ini.read_text(encoding="utf-8")
    assert "[Refresh Recently Played]" in body
    assert str(bat_dir / "Refresh Recently Played.bat") in body
    assert "[Refresh Favorites]" in body
    assert "WorkingFolder=" in body


def test_write_toolkit_module_ini_preserves_non_sd_sections(tmp_path):
    """Existing non-SpinDoctor sections are kept when the file is updated."""
    rl = tmp_path / "rl"
    module_dir = rl / "Modules" / "PCLauncher"
    module_dir.mkdir(parents=True)
    existing = module_dir / "Toolkit.ini"
    existing.write_text(
        "[TeamViewer]\nApplication=C:\\TeamViewer\\TeamViewer.exe\n\n",
        encoding="utf-8",
    )
    bat_dir = tmp_path / "Toolkit"
    bat_dir.mkdir()
    entries = [("Refresh Recently Played", bat_dir / "Refresh Recently Played.bat")]
    write_toolkit_module_ini("Toolkit", entries, rl)

    body = existing.read_text(encoding="utf-8")
    assert "[TeamViewer]" in body
    assert "TeamViewer.exe" in body
    assert "[Refresh Recently Played]" in body


def test_write_toolkit_module_ini_replaces_stale_sd_sections(tmp_path):
    """SpinDoctor sections are replaced, not duplicated, on re-run."""
    rl = tmp_path / "rl"
    module_dir = rl / "Modules" / "PCLauncher"
    module_dir.mkdir(parents=True)
    existing = module_dir / "Toolkit.ini"
    existing.write_text(
        "[Refresh Recently Played]\nApplication=C:\\old\\Refresh Recently Played.bat\n\n",
        encoding="utf-8",
    )
    bat_dir = tmp_path / "new_path"
    bat_dir.mkdir()
    entries = [("Refresh Recently Played", bat_dir / "Refresh Recently Played.bat")]
    write_toolkit_module_ini("Toolkit", entries, rl)

    body = existing.read_text(encoding="utf-8")
    # New path present, old literal path gone, only one section
    assert str(bat_dir) in body
    assert "C:\\old\\" not in body
    assert body.count("[Refresh Recently Played]") == 1


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


# ─── list_exe_candidates / _pick_best_exe ────────────────────────────────────


def test_list_exe_candidates_prefers_name_match(tmp_path):
    game_dir = tmp_path / "ElecHead"
    game_dir.mkdir()
    (game_dir / "ElecHead.exe").write_bytes(b"\x00" * 5_000_000)
    (game_dir / "unins000.exe").write_bytes(b"\x00" * 1_000_000)
    result = list_exe_candidates(game_dir, "ElecHead")
    assert result[0].name == "ElecHead.exe"
    assert result[-1].name == "unins000.exe"


def test_list_exe_candidates_excludes_come_after_recommended(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "game.exe").write_bytes(b"\x00" * 4_000_000)
    (game_dir / "setup.exe").write_bytes(b"\x00" * 500_000)
    (game_dir / "vcredist_x64.exe").write_bytes(b"\x00" * 100_000)
    result = list_exe_candidates(game_dir, "game")
    names = [p.name for p in result]
    assert names[0] == "game.exe"
    assert "setup.exe" in names
    assert "vcredist_x64.exe" in names


def test_list_exe_candidates_empty_dir(tmp_path):
    game_dir = tmp_path / "Empty"
    game_dir.mkdir()
    assert list_exe_candidates(game_dir, "Empty") == []


def test_list_exe_candidates_missing_dir(tmp_path):
    assert list_exe_candidates(tmp_path / "NoSuchDir", "game") == []


def test_pick_best_exe_returns_name_match(tmp_path):
    game_dir = tmp_path / "ElecHead"
    game_dir.mkdir()
    (game_dir / "ElecHead.exe").write_bytes(b"\x00" * 5_000_000)
    (game_dir / "unins000.exe").write_bytes(b"\x00" * 1_000_000)
    assert _pick_best_exe(game_dir, "ElecHead").name == "ElecHead.exe"


def test_pick_best_exe_skips_uninstaller_when_only_candidate(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "unins000.exe").write_bytes(b"\x00" * 1_000_000)
    # Only an uninstaller present → no recommended candidate
    assert _pick_best_exe(game_dir, "Game") is None


def test_pick_best_exe_tiebreaker_largest(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "launcher.exe").write_bytes(b"\x00" * 200_000)
    (game_dir / "game_main.exe").write_bytes(b"\x00" * 8_000_000)
    result = _pick_best_exe(game_dir, "Something Else")
    assert result.name == "game_main.exe"


# ─── rewrite_pclauncher_application ──────────────────────────────────────────


def test_rewrite_pclauncher_application_updates_paths(tmp_path):
    ini = tmp_path / "ElecHead.ini"
    ini.write_text(
        "[ElecHead]\nApplication=J:\\Games\\ElecHead\\webcache.zip\n"
        "WorkingFolder=J:\\Games\\ElecHead\n",
        encoding="utf-8",
    )
    new_exe = PureWindowsPath(r"J:\Games\ElecHead\ElecHead.exe")
    changed = rewrite_pclauncher_application(ini, "ElecHead", new_exe)
    assert changed
    body = ini.read_text(encoding="utf-8")
    assert "Application=J:\\Games\\ElecHead\\ElecHead.exe" in body
    assert "WorkingFolder=J:\\Games\\ElecHead" in body
    assert "webcache.zip" not in body


def test_rewrite_pclauncher_application_preserves_other_keys(tmp_path):
    ini = tmp_path / "Game.ini"
    ini.write_text(
        "[Game]\nApplication=D:\\old.exe\nFadeTitle=Game Window\nWorkingFolder=D:\\\n",
        encoding="utf-8",
    )
    changed = rewrite_pclauncher_application(
        ini, "Game", PureWindowsPath(r"J:\Games\Game\game.exe")
    )
    assert changed
    body = ini.read_text(encoding="utf-8")
    assert "FadeTitle=Game Window" in body
    assert r"Application=J:\Games\Game\game.exe" in body


def test_rewrite_pclauncher_application_noop_when_already_correct(tmp_path):
    exe = PureWindowsPath(r"J:\Games\ElecHead\ElecHead.exe")
    ini = tmp_path / "ElecHead.ini"
    ini.write_text(
        f"[ElecHead]\nApplication={exe}\nWorkingFolder={exe.parent}\n",
        encoding="utf-8",
    )
    changed = rewrite_pclauncher_application(ini, "ElecHead", exe)
    assert not changed


def test_rewrite_pclauncher_application_noop_on_missing_file(tmp_path):
    changed = rewrite_pclauncher_application(
        tmp_path / "missing.ini", "Game", PureWindowsPath(r"J:\game.exe")
    )
    assert not changed


def test_rewrite_pclauncher_application_section_not_found(tmp_path):
    ini = tmp_path / "Game.ini"
    ini.write_text("[OtherGame]\nApplication=D:\\old.exe\n", encoding="utf-8")
    changed = rewrite_pclauncher_application(
        ini, "Game", PureWindowsPath(r"J:\Games\Game\game.exe")
    )
    # Section not present → no modification
    assert not changed
    assert "D:\\old.exe" in ini.read_text(encoding="utf-8")


# ── _resolve_pclauncher_exe ───────────────────────────────────────────────────

def test_resolve_pclauncher_exe_already_exe(tmp_path):
    exe = tmp_path / "ElecHead.exe"
    exe.write_bytes(b"\x00" * 100)
    result = _resolve_pclauncher_exe(exe, "ElecHead")
    assert result == exe


def test_resolve_pclauncher_exe_zip_resolves_to_best_exe(tmp_path):
    game_dir = tmp_path / "ElecHead"
    game_dir.mkdir()
    (game_dir / "ElecHead.exe").write_bytes(b"\x00" * 5000)
    (game_dir / "unins000.exe").write_bytes(b"\x00" * 100)
    (game_dir / "webcache.zip").write_bytes(b"\x00" * 50)
    zip_path = game_dir / "webcache.zip"
    result = _resolve_pclauncher_exe(zip_path, "ElecHead")
    assert result.name == "ElecHead.exe"


def test_resolve_pclauncher_exe_zip_fallback_when_no_exe(tmp_path):
    game_dir = tmp_path / "MyGame"
    game_dir.mkdir()
    (game_dir / "webcache.zip").write_bytes(b"\x00" * 50)
    zip_path = game_dir / "webcache.zip"
    result = _resolve_pclauncher_exe(zip_path, "MyGame")
    assert result == zip_path


def test_resolve_pclauncher_exe_zip_only_excluded_falls_back(tmp_path):
    game_dir = tmp_path / "MyGame"
    game_dir.mkdir()
    (game_dir / "unins000.exe").write_bytes(b"\x00" * 100)
    (game_dir / "webcache.zip").write_bytes(b"\x00" * 50)
    zip_path = game_dir / "webcache.zip"
    result = _resolve_pclauncher_exe(zip_path, "MyGame")
    # Only excluded exe found → fall back to the original rom path
    assert result == zip_path


# ── generate_pclauncher_inis exe-resolution ───────────────────────────────────

def test_generate_pclauncher_inis_resolves_zip_to_exe(tmp_path):
    """generate_pclauncher_inis writes the real .exe even when the rom is a zip."""
    game_dir = tmp_path / "roms" / "PC GAMES" / "ElecHead"
    game_dir.mkdir(parents=True)
    (game_dir / "ElecHead.exe").write_bytes(b"\x00" * 5000)
    (game_dir / "unins000.exe").write_bytes(b"\x00" * 100)
    (game_dir / "webcache.zip").write_bytes(b"\x00" * 50)

    config = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    zip_path = game_dir / "webcache.zip"
    module_dir, written, skipped = generate_pclauncher_inis(
        "PC GAMES", {"ElecHead": zip_path}, config
    )
    assert len(written) == 1
    ini_text = (module_dir / "ElecHead.ini").read_text(encoding="utf-8")
    assert "ElecHead.exe" in ini_text
    assert "webcache.zip" not in ini_text


def test_generate_pclauncher_inis_exe_path_unchanged(tmp_path):
    """When the rom is already an .exe, generate_pclauncher_inis uses it directly."""
    game_dir = tmp_path / "roms" / "PC GAMES" / "MyGame"
    game_dir.mkdir(parents=True)
    exe = game_dir / "MyGame.exe"
    exe.write_bytes(b"\x00" * 100)

    config = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    module_dir, written, skipped = generate_pclauncher_inis(
        "PC GAMES", {"MyGame": exe}, config
    )
    assert len(written) == 1
    ini_text = (module_dir / "MyGame.ini").read_text(encoding="utf-8")
    assert "MyGame.exe" in ini_text


# ── _EXE_EXCLUSION_PREFIXES — chromedriver / NW.js ──────────────────────────

def test_pick_best_exe_prefers_game_exe_over_chromedriver(tmp_path):
    """chromedriver.exe (NW.js runtime) must lose to the real game launcher."""
    game_dir = tmp_path / "Look Outside"
    game_dir.mkdir()
    (game_dir / "chromedriver.exe").write_bytes(b"\x00" * 5000)
    (game_dir / "Game.exe").write_bytes(b"\x00" * 100)
    result = _pick_best_exe(game_dir, "Look Outside")
    assert result is not None
    assert result.name == "Game.exe"


def test_list_exe_candidates_chromedriver_sorted_last(tmp_path):
    """list_exe_candidates puts chromedriver in the excluded (lower-priority) tier."""
    game_dir = tmp_path / "Look Outside"
    game_dir.mkdir()
    (game_dir / "chromedriver.exe").write_bytes(b"\x00" * 100)
    (game_dir / "Game.exe").write_bytes(b"\x00" * 100)
    candidates = list_exe_candidates(game_dir, "Look Outside")
    names = [p.name for p in candidates]
    assert names.index("Game.exe") < names.index("chromedriver.exe")
