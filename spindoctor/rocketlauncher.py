"""RocketLauncher system INI and HyperSpin Main Menu XML generation."""
from __future__ import annotations

import configparser
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from ._compat import et_indent
from .config import Config, get_rom_extensions, get_system_overrides
from .mainmenu import _main_menu_path


# System names that generate-config must never overwrite.
# These are either SpinDoctor-managed synthetic PCLauncher wheels whose
# settings are written by fav/recent/stats rebuild, or HyperSpin's own
# internal pseudo-system that is not a real emulated platform.
# Allowing generate-config to process them writes incorrect RetroArch
# settings (guess_emulator falls back to RetroArch for unknown names)
# which breaks the wheels on the next RL launch.
SKIP_GENERATE_CONFIG: frozenset[str] = frozenset({
    "Favorites",
    "Recently Played",
    "Most Played",
    "Recompiled",
    "Main Menu",
})


EMULATOR_MAP: dict[str, str] = {
    # ── Arcade / MAME ──────────────────────────────────────────────────────────
    "mame": "MAME",
    "arcade": "MAME",
    "cps1": "MAME",
    "cps2": "MAME",
    "cps3": "MAME",
    "neogeo": "MAME",
    "neo geo": "MAME",
    "naomi": "MAME",
    "atomiswave": "MAME",
    "triforce": "MAME",
    "zinc": "ZiNc",
    # ── Nintendo ───────────────────────────────────────────────────────────────
    "nes": "RetroArch",
    "nintendo entertainment system": "RetroArch",
    "famicom": "RetroArch",
    "snes": "RetroArch",
    "super nintendo": "RetroArch",
    "super famicom": "RetroArch",
    "n64": "Project64",
    "nintendo 64": "Project64",
    "gba": "RetroArch",
    "game boy advance": "RetroArch",
    "gameboy": "RetroArch",
    "game boy": "RetroArch",
    "game boy color": "RetroArch",
    "gbc": "RetroArch",
    "gamecube": "Dolphin",
    "nintendo gamecube": "Dolphin",
    "wii": "Dolphin",
    "nintendo wii": "Dolphin",
    "wiiware": "Dolphin",
    "nintendo wiiware": "Dolphin",
    "nintendo ds": "RetroArch",
    "nds": "RetroArch",
    "nintendo 3ds": "RetroArch",
    "3ds": "RetroArch",
    # ── Sega ───────────────────────────────────────────────────────────────────
    "genesis": "RetroArch",
    "mega drive": "RetroArch",
    "sega genesis": "RetroArch",
    "master system": "RetroArch",
    "sega master system": "RetroArch",
    "game gear": "RetroArch",
    "sega game gear": "RetroArch",
    "sega cd": "RetroArch",
    "32x": "RetroArch",
    "sega 32x": "RetroArch",
    "dreamcast": "Demul",
    "sega dreamcast": "Demul",
    "saturn": "SSF",
    "sega saturn": "SSF",
    # ── Sony ───────────────────────────────────────────────────────────────────
    "psx": "RetroArch",
    "playstation": "RetroArch",
    "ps2": "PCSX2",
    "playstation 2": "PCSX2",
    "psp": "RetroArch",
    "playstation portable": "RetroArch",
    # ── Atari ──────────────────────────────────────────────────────────────────
    "atari 2600": "RetroArch",
    "atari 7800": "RetroArch",
    "atari lynx": "RetroArch",
    "atari jaguar": "RetroArch",
    "atari st": "RetroArch",
    # ── NEC ────────────────────────────────────────────────────────────────────
    "turbografx": "RetroArch",
    "turbografx-16": "RetroArch",
    "pc engine": "RetroArch",
    "turbografx cd": "RetroArch",
    "pc engine cd": "RetroArch",
    # ── 3DO ────────────────────────────────────────────────────────────────────
    "3do": "RetroArch",
    "panasonic 3do": "RetroArch",
    "3do interactive multiplayer": "RetroArch",
    # ── LaserDisc / Daphne-based ───────────────────────────────────────────────
    # These systems use a Daphne-family emulator.  The emulator name must match
    # the section header in Global Emulators.ini exactly — some cabinets use
    # "Daphne Singe" or "Daphne Singe (WoW Action Max)" for ALG / WoW Action
    # Max.  Use `config system set --emulator` to override when that is the
    # case.  All Daphne-family emulators share the same ROM folder; see
    # EMULATOR_FAMILY_FOLDERS below for the shared-path fallback logic.
    "daphne": "Daphne",
    "action max": "Daphne",
    "american laser games": "Daphne",
    "wow action max": "Daphne",
    # ── Other older/misc consoles ──────────────────────────────────────────────
    "neo geo cd": "RetroArch",
    "neogeo cd": "RetroArch",
    "wonderswan": "RetroArch",
    "wonderswan color": "RetroArch",
    "colecovision": "RetroArch",
    "intellivision": "RetroArch",
    "entex adventure vision": "RetroArch",
    "adventure vision": "RetroArch",
    "vectrex": "RetroArch",
    "commodore 64": "RetroArch",
    "c64": "RetroArch",
    "amiga": "RetroArch",
    "amiga cd32": "RetroArch",
    "fairchild channel f": "RetroArch",
    "channel f": "RetroArch",
    # ── PC / Windows / Steam / Arcade-PC ──────────────────────────────────────
    # PCLauncher reads a per-game INI to find the actual executable.
    "pc": "PCLauncher",
    "pc games": "PCLauncher",
    "windows": "PCLauncher",
    "windows games": "PCLauncher",
    "steam": "PCLauncher",
    "steam games": "PCLauncher",
    "doujin": "PCLauncher",
    "doujin games": "PCLauncher",
    "taito type x": "PCLauncher",
    "taito type x2": "PCLauncher",
    "taito type x3": "PCLauncher",
    "nesica": "PCLauncher",
}


# Emulator family → canonical ROM folder name under roms_dir.
#
# When a system's own ROM folder (roms_dir/<system_name>) doesn't exist,
# generate-config falls back to roms_dir/<canonical_folder> when the
# system's guessed (or existing) emulator name starts with a key in this
# table.  This is the generic equivalent of the MAME-variant keyword logic:
# instead of matching "MAME" in the system name we match the emulator name.
#
# Use case: "Daphne", "American Laser Games" (Daphne Singe), and
# "WoW Action Max" (Daphne Singe (WoW Action Max)) all share game content
# from one directory.  When generate-config runs for "American Laser Games"
# and J:\Games\American Laser Games doesn't exist, it falls back to
# J:\Games\Daphne rather than writing a phantom path.
#
# Key:   emulator name prefix, lower-case
# Value: subfolder name under roms_dir to use as the shared ROM location
EMULATOR_FAMILY_FOLDERS: dict[str, str] = {
    "daphne": "Daphne",
}


def _get_emulator_family_folder(emulator_name: str) -> Optional[str]:
    """Return the canonical shared ROM folder for *emulator_name*, or ``None``.

    Checks :data:`EMULATOR_FAMILY_FOLDERS` by lower-case prefix match so that
    variant names like ``"Daphne Singe"`` and ``"Daphne Singe (WoW Action Max)"``
    both match the ``"daphne"`` key and return ``"Daphne"``.
    MAME variants are handled by a separate keyword check in
    :func:`generate_rl_system_ini` and intentionally have no entry here.
    """
    emu_lower = emulator_name.lower()
    for prefix, canonical in EMULATOR_FAMILY_FOLDERS.items():
        if emu_lower.startswith(prefix):
            return canonical
    return None


def guess_emulator(system_name: str) -> str:
    ovr = get_system_overrides().get(system_name, {})
    if isinstance(ovr.get("emulator"), str) and ovr["emulator"]:
        return ovr["emulator"]
    mapped = EMULATOR_MAP.get(system_name.lower())
    if mapped:
        return mapped
    # System names that contain "MAME" (e.g. "MAME (Vector)", "MAME Atari
    # Classics") are sub-catalogues of the main MAME library and always use
    # the MAME emulator.
    if re.search(r"\bmame\b", system_name, re.IGNORECASE):
        return "MAME"
    return "RetroArch"


# Default executable names per emulator — used when generating
# Global Emulators.ini.  Users can edit the file afterwards; spindoctor
# refuses to overwrite an existing file unless --overwrite-global is set.
EMULATOR_EXECUTABLES: dict[str, str] = {
    "MAME": "mame.exe",
    "RetroArch": "retroarch.exe",
    "Project64": "Project64.exe",
    "PCSX2": "pcsx2.exe",
    "Dolphin": "Dolphin.exe",
    "Demul": "demul.exe",
    "PCLauncher": "PCLauncher.exe",
}

EMULATOR_EXTENSIONS: dict[str, str] = {
    "MAME": "zip|7z",
    "RetroArch": "zip|7z|nes|sfc|smc|md|bin|gba|gb|gbc|n64|z64",
    "Project64": "z64|n64|v64|zip",
    "PCSX2": "iso|bin|img",
    "Dolphin": "iso|gcm|gcz|wbfs|ciso|rvz",
    "Demul": "chd|cdi|gdi|cue",
    # PCLauncher "ROMs" are always per-game INI files stored under
    # Modules/PCLauncher/<system>/<game>.ini — true for both synthetic
    # wheels (Favorites, Recently Played, Most Played) and real
    # PC/Windows/Steam systems.  The actual application (.exe/.lnk/etc.)
    # is referenced inside the INI, not used directly as the ROM file.
    "PCLauncher": "ini",
}

# Correction table for emulator window titles used as PCLauncher's ``FadeTitle=`` key.
#
# **Why FadeTitle is needed alongside AppWaitExe:**
# PCLauncher.ahk v2.2.7 source (lines 214-224) shows that when ``AppWaitExe``
# is set *without* ``FadeTitle``, PCLauncher waits for the AppWaitExe process
# to start (correct) but then tries to find that process's window by PID
# (``WinWait ahk_pid <PID>``). DirectX emulators running in exclusive
# fullscreen — or those that create their game window in a child process —
# don't produce a Win32 window detectable by PID. The wait times out after
# ~30 s: "There was an error waiting for the window ahk_pid XXXX".
#
# Setting ``FadeTitle`` causes PCLauncher to skip the PID-based window search
# entirely (the ``If !FadeTitle`` block at line 215 is bypassed). It instead
# waits for a window whose title *contains* the FadeTitle value — which works
# even when the window is owned by a child process. ``AppWaitExe.WaitClose()``
# then handles exit detection cleanly (the process disappearing when the user
# quits the game).
#
# **Default behaviour (no entry needed for most emulators):**
# ``_get_fade_title`` falls back to the emulator's registered name when it is
# not found in this table.  AHK ``WinWait`` uses case-insensitive partial
# matching, so "Supermodel" matches "Supermodel 3.1 UI", "Model 2" matches
# "Sega Model 2 Emulator", and so on.  This means FadeTitle works
# automatically for any emulator whose window title contains its registered
# name — which is the overwhelming majority.
#
# **Add an entry here only when the emulator name does NOT appear in the
# window title at all** — e.g. if an emulator registered as "Zinc" actually
# shows "Drunken Muppets Arcade" as its window title.  The ``emulator_window_titles``
# field in :class:`~spindoctor.config.Config` provides user-level overrides
# with the same semantics (user entries take precedence over this table).
EMULATOR_WINDOW_TITLES: dict[str, str] = {
    "ZiNc": "ZiNc",   # window title: "ZiNc 1.1 (C)1997-2005 Drunken Muppets ..."
                       # name and title match so this is a no-op, but kept as a
                       # documented example of the correction format.
}

# Safety timeout (seconds) for FadeTitle window detection.
# If the emulator's window hasn't appeared within this many seconds of
# PCLauncher launching the Application, PCLauncher errors out.  This prevents
# an infinite hang if the emulator crashes before showing a window.
_FADE_TITLE_TIMEOUT = 30


# ─── Global Emulators.ini ─────────────────────────────────────────────────────

def generate_global_emulators_ini(
    config: Config,
    output_base: Optional[Path] = None,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Generate ``RocketLauncher/Settings/Global Emulators.ini``.

    Returns ``(path, status)`` where status is one of
    ``"created"``, ``"skipped-exists"``, ``"overwritten"``.

    By default does not overwrite an existing file (RL UI / users may have
    customised it).  Pass ``overwrite=True`` to replace it.
    """
    rl_base = output_base or (
        Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None
    )
    if not rl_base:
        raise ValueError(
            "rocketlauncher_dir not configured. "
            "Run: spindoctor config set rocketlauncher_dir <path>  "
            "or pass --output-dir."
        )

    settings_dir = rl_base / "Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    ini_path = settings_dir / "Global Emulators.ini"

    if ini_path.exists() and not overwrite:
        return ini_path, "skipped-exists"

    # Distinct emulators referenced by EMULATOR_MAP
    emulators = sorted(set(EMULATOR_MAP.values()))
    emulators_root = (
        Path(config.emulators_dir) if config.emulators_dir else Path("Emulators")
    )

    lines: list[str] = [
        "; Generated by SpinDoctor.",
        "; Edit paths here once; per-system Settings/<System>.ini will reference",
        "; these emulators by name (RocketLauncher hierarchy).",
        "",
    ]
    for emu in emulators:
        exe = EMULATOR_EXECUTABLES.get(emu, f"{emu}.exe")
        ext = EMULATOR_EXTENSIONS.get(emu, "zip|7z")
        emu_dir = emulators_root / emu
        lines.extend([
            f"[{emu}]",
            f"Emu_Path={emu_dir / exe}",
            f"Rom_Extension={ext}",
            "",
        ])

    status = "overwritten" if ini_path.exists() else "created"
    ini_path.write_text("\n".join(lines), encoding="utf-8")
    return ini_path, status


# ─── RocketLauncher INI ───────────────────────────────────────────────────────

def detect_rl_layout(settings_dir: Path, system_name: str) -> str:
    """Return which RocketLauncher settings layout a system currently uses.

    RocketLauncher supports two layouts for per-system emulator routing:

    - ``"folder"`` — ``Settings/<system>/Emulators.ini`` exists.  RL reads
      ``Default_Emulator`` from the ``[ROMS]`` section.  This is the layout
      produced by HyperHQ and used by cabinets that have per-game override
      folders alongside the system-level ``Emulators.ini``.

    - ``"flat"``   — ``Settings/<system>.ini`` exists (no sub-folder).  RL
      reads ``Default_Emulator`` from the ``[Settings]`` section.

    - ``"new"``    — neither file exists yet (first run for this system).
      ``generate_rl_system_ini`` will write both so the cabinet works
      regardless of which layout RL happens to prefer.

    The check is done in folder-first order because a cabinet that has both
    files almost certainly grew from HyperHQ (folder layout), and the
    folder-layout ``Emulators.ini`` is what RL actually reads in that case.
    """
    if (settings_dir / system_name / "Emulators.ini").exists():
        return "folder"
    if (settings_dir / f"{system_name}.ini").exists():
        return "flat"
    return "new"


def _is_absolute_path(p: str) -> bool:
    """True for POSIX absolute (/foo) and Windows absolute (C:\\foo) paths.

    ``pathlib.Path.is_absolute()`` returns ``False`` for Windows drive-letter
    paths when running on macOS/Linux, so we check both forms.
    """
    return Path(p).is_absolute() or bool(re.match(r"^[A-Za-z]:[/\\]", p))


def _read_rom_path_from_ini(ini_path: Path) -> Optional[str]:
    """Return the first ``Rom_Path=`` value found in *ini_path*, or ``None``.

    Used by :func:`generate_rl_system_ini` to check whether the existing
    file already points at a valid directory before deciding to overwrite.
    """
    try:
        for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("rom_path="):
                return stripped.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def _read_default_emulator_from_ini(ini_path: Path) -> Optional[str]:
    """Return the Default_Emulator value from *ini_path*, or ``None``."""
    try:
        for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("default_emulator="):
                return stripped.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def _update_rom_path_in_ini(ini_path: Path, new_rom_path: str) -> bool:
    """Replace every ``Rom_Path=`` line in *ini_path* with *new_rom_path*.

    The key match is case-insensitive (``rom_path=``, ``ROM_PATH=``, etc. all
    match) and the replacement is written with canonical capitalisation
    ``Rom_Path=``.  All other lines — ``Default_Emulator``, ``Emu_Path``,
    ``Module``, ``Pause_Save_State_Keys``, etc. — are preserved exactly.

    Returns ``True`` if at least one replacement was made, ``False`` if no
    ``Rom_Path=`` line was found.  The caller should fall back to writing a
    fresh template when ``False`` is returned.
    """
    content = ini_path.read_text(encoding="utf-8", errors="replace")
    # Use a callable replacement to avoid re.subn interpreting backslashes in
    # Windows paths (e.g. C:\Users\...) as regex backreferences (\U, \N, etc.).
    replacement = f"Rom_Path={new_rom_path}"
    new_content, count = re.subn(
        r"(?im)^rom_path=.*$",
        lambda m: replacement,
        content,
    )
    if count:
        ini_path.write_text(new_content, encoding="utf-8")
    return count > 0


def generate_rl_system_ini(
    system_name: str,
    config: Config,
    output_base: Optional[Path] = None,
) -> list[Path]:
    """Write RocketLauncher per-system settings INI file(s).

    **For existing files** only ``Rom_Path=`` is updated in-place.  Every other
    key — ``Default_Emulator``, ``Emu_Path``, ``Module``,
    ``Pause_Save_State_Keys``, ``Rom_Extension``, and any other emulator section
    — is preserved exactly as written by HyperHQ / RLUI.

    This is intentional: ``generate-config`` is a *ROM-path updater*, not a
    full emulator reconfiguration tool.  Overwriting ``Default_Emulator`` with
    SpinDoctor's best-guess emulator name breaks systems that use emulators not
    in SpinDoctor's built-in map (e.g. SSF for Sega Saturn, Mednafen for
    TurboGrafx-16).  Adding a bare ``[<Emulator>]`` section without ``Emu_Path``
    causes RocketLauncher to stop its emulator-path lookup at the per-system
    file and report "Could not find an Emu_path" instead of falling back to
    ``Global Emulators.ini`` where the path is defined.

    **For new systems** (neither file exists) both folder-layout and flat-layout
    files are written from the template so the cabinet works regardless of which
    layout RocketLauncher prefers.

    Returns the list of paths written (one or two items).
    """
    rl_base = output_base or (Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None)
    if not rl_base:
        raise ValueError(
            "rocketlauncher_dir not configured. "
            "Run: spindoctor config set rocketlauncher_dir <path>  "
            "or pass --output-dir."
        )

    settings_dir = rl_base / "Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)

    # Per-system rom_path override wins over the default roms_dir/system_name
    # derivation.  This is how MAME-variant systems (MAME (Vector), MAME
    # (Vertical), …) that all share a single ROM folder are configured:
    #   spindoctor config system-override "MAME (Vector)" rom_path J:\Games\MAME
    ovr = get_system_overrides().get(system_name, {})
    if isinstance(ovr.get("rom_path"), str) and ovr["rom_path"]:
        rom_path = ovr["rom_path"]
        _natural_rom_path = rom_path
    else:
        rom_path = str(Path(config.roms_dir) / system_name)
        # Track the system-derived path before any fallback so that existing-INI
        # guards can test whether the system has its own folder, independently of
        # whatever family fallback we may apply below.
        _natural_rom_path = rom_path
        # MAME-variant system names (e.g. "MAME (Vector)", "MAME Atari
        # Classics") never have their own ROM folder — all ROMs live in the
        # main MAME folder.  Fall back to roms_dir/MAME when the
        # system-named folder doesn't exist and a "MAME" folder does.
        if (
            re.search(r"\bmame\b", system_name, re.IGNORECASE)
            and not Path(rom_path).exists()
        ):
            mame_path = str(Path(config.roms_dir) / "MAME")
            if Path(mame_path).exists():
                rom_path = mame_path
        # Generic emulator-family fallback: when the system's emulator maps to
        # a shared canonical folder (e.g. "American Laser Games" → emulator
        # "Daphne Singe" → canonical "Daphne"), use that folder when the
        # system-named folder doesn't exist but the canonical one does.
        if not Path(rom_path).exists():
            _new_family = _get_emulator_family_folder(guess_emulator(system_name))
            if _new_family:
                _new_family_path = str(Path(config.roms_dir) / _new_family)
                if Path(_new_family_path).exists():
                    rom_path = _new_family_path
    emulator = guess_emulator(system_name)

    # PCLauncher systems need Rom_Path pointing to the per-game INI directory
    # (Modules/PCLauncher/<system>/) and Rom_Extension=ini so RL discovers
    # games via their placeholder INIs regardless of how game files are laid
    # out on disk.  generate_synthetic_system_ini already generates exactly
    # this layout (and always rewrites so stale paths are corrected).
    if emulator == "PCLauncher":
        generate_synthetic_system_ini(system_name, rl_base)
        return [
            rl_base / "Settings" / system_name / "Emulators.ini",
            rl_base / "Settings" / f"{system_name}.ini",
        ]

    extensions = "|".join(ext.lstrip(".") for ext in get_rom_extensions(system_name))
    layout = detect_rl_layout(settings_dir, system_name)
    written: list[Path] = []

    if layout in ("folder", "new"):
        folder_dir = settings_dir / system_name
        folder_dir.mkdir(parents=True, exist_ok=True)
        emu_ini = folder_dir / "Emulators.ini"
        # Guard: when the existing file already points at a valid directory but
        # the computed path does not exist, the system has a custom ROM location
        # (e.g. a MAME variant that shares J:\Games\MAME instead of having its
        # own J:\Games\MAME (Vector) folder).  Overwriting would break launches.
        # We only apply this guard when no explicit system_override is set — if
        # the user configured a rom_path override we always honour it.
        _skip_update = False
        if not ovr.get("rom_path") and emu_ini.exists() and not output_base:
            _current = _read_rom_path_from_ini(emu_ini)
            if _current and Path(_current).is_dir() and not Path(_natural_rom_path).exists():
                _skip_update = True
            if not _skip_update:
                _existing_emu = _read_default_emulator_from_ini(emu_ini)
                if _existing_emu and re.search(r"\bmame\b", _existing_emu, re.IGNORECASE):
                    if _current and not _is_absolute_path(_current):
                        # Relative path: resolve from RL root (how RocketLauncher
                        # resolves it on Windows).  Only preserve if it still points
                        # at a real directory — a stale relative path (e.g. ROMs
                        # moved from D: to J:) must be updated, not preserved.
                        try:
                            if (rl_base / _current).resolve().is_dir():
                                _skip_update = True
                        except (OSError, ValueError):
                            pass
                    if not _skip_update and not Path(rom_path).exists():
                        # Computed path doesn't exist (MAME variant, or non-MAME-
                        # named system like "4-Player Games").  Fall back to
                        # roms_dir/MAME rather than writing a phantom path.
                        _mame_fallback = str(Path(config.roms_dir) / "MAME")
                        if Path(_mame_fallback).exists():
                            rom_path = _mame_fallback
                # Generic emulator-family fallback (e.g. existing ini has
                # Default_Emulator=Daphne Singe → fall back to roms_dir/Daphne).
                if not _skip_update and not Path(rom_path).exists() and _existing_emu:
                    _folder_family = _get_emulator_family_folder(_existing_emu)
                    if _folder_family:
                        _folder_family_path = str(Path(config.roms_dir) / _folder_family)
                        if Path(_folder_family_path).exists():
                            rom_path = _folder_family_path
        if not _skip_update:
            if not (emu_ini.exists() and _update_rom_path_in_ini(emu_ini, rom_path)):
                emu_ini.write_text("\n".join([
                    "[ROMS]",
                    f"Default_Emulator={emulator}",
                    f"Rom_Path={rom_path}",
                    f"Rom_Extension={extensions}",
                    "",
                    f"[{emulator}]",
                    f"Rom_Path={rom_path}",
                    "",
                ]), encoding="utf-8")
        written.append(emu_ini)

    if layout in ("flat", "new"):
        flat_ini = settings_dir / f"{system_name}.ini"
        _skip_update_flat = False
        if not ovr.get("rom_path") and flat_ini.exists() and not output_base:
            _current_flat = _read_rom_path_from_ini(flat_ini)
            if _current_flat and Path(_current_flat).is_dir() and not Path(_natural_rom_path).exists():
                _skip_update_flat = True
            if not _skip_update_flat:
                _existing_emu_flat = _read_default_emulator_from_ini(flat_ini)
                if _existing_emu_flat and re.search(r"\bmame\b", _existing_emu_flat, re.IGNORECASE):
                    if _current_flat and not _is_absolute_path(_current_flat):
                        try:
                            if (rl_base / _current_flat).resolve().is_dir():
                                _skip_update_flat = True
                        except (OSError, ValueError):
                            pass
                    if not _skip_update_flat and not Path(rom_path).exists():
                        _mame_fallback_flat = str(Path(config.roms_dir) / "MAME")
                        if Path(_mame_fallback_flat).exists():
                            rom_path = _mame_fallback_flat
                # Generic emulator-family fallback for flat-layout INIs.
                if not _skip_update_flat and not Path(rom_path).exists() and _existing_emu_flat:
                    _flat_family = _get_emulator_family_folder(_existing_emu_flat)
                    if _flat_family:
                        _flat_family_path = str(Path(config.roms_dir) / _flat_family)
                        if Path(_flat_family_path).exists():
                            rom_path = _flat_family_path
        if not _skip_update_flat:
            if not (flat_ini.exists() and _update_rom_path_in_ini(flat_ini, rom_path)):
                flat_ini.write_text("\n".join([
                    "[Settings]",
                    f"Default_Emulator={emulator}",
                    f"Rom_Path={rom_path}",
                    f"Rom_Extension={extensions}",
                    "",
                    f"[{emulator}]",
                    f"Rom_Path={rom_path}",
                    "",
                ]), encoding="utf-8")
        written.append(flat_ini)

    return written


def generate_synthetic_system_ini(system_name: str, rocketlauncher_dir: Path) -> Path:
    """Write RocketLauncher system settings for a synthetic PCLauncher wheel.

    Synthetic systems (Favorites, Recently Played, Most Played) store per-game
    INIs under Modules/PCLauncher/<system>/ — so that directory is the
    Rom_Path, and the extension is "ini".

    Two files are written to cover both layout variants found in the wild:

    1. ``Settings/<system>.ini`` (flat layout) — RL reads ``Default_Emulator``
       from the ``[Settings]`` section here.
    2. ``Settings/<system>/Emulators.ini`` (folder layout) — RL reads
       ``Default_Emulator`` from the ``[ROMS]`` section and ``Rom_Extension``
       from the ``[PCLauncher]`` emulator section.

    **Rom_Extension must appear in every section RL may consult:**

    RL v1.2 reads ``Rom_Extension`` from the emulator section (``[PCLauncher]``)
    first.  When no ``[PCLauncher]`` section exists in the system file, RL falls
    back to the ``[PCLauncher]`` section in ``Global Emulators.ini``.  If that
    global section also lacks ``Rom_Extension=ini``, RL uses its built-in default
    extension list (``zip|rar|7z|lha|…``) and cannot find the placeholder INIs::

        Cannot find Rom 1942 in any Rom_Paths provided:
            "…\\Modules\\PCLauncher\\Favorites"
        with any provided Rom_Extension: "zip|rar|7z|lha|lzh|gzip|tar|"

    Therefore both files explicitly carry ``[PCLauncher]`` with
    ``Rom_Extension=ini`` so RL reads the correct value from the system file
    regardless of what the cabinet's ``Global Emulators.ini`` contains.
    """
    settings_dir = rocketlauncher_dir / "Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    pclauncher_dir = rocketlauncher_dir / "Modules" / "PCLauncher" / system_name

    # ── 1. Flat layout: Settings/<system>.ini ────────────────────────────────
    ini_path = settings_dir / f"{system_name}.ini"
    flat_lines = [
        "[Settings]",
        "Default_Emulator=PCLauncher",
        f"Rom_Path={pclauncher_dir}",
        "Rom_Extension=ini",
        "",
        "[PCLauncher]",
        f"Rom_Path={pclauncher_dir}",
        "Rom_Extension=ini",
        "",
    ]
    ini_path.write_text("\n".join(flat_lines), encoding="utf-8")

    # ── 2. Folder layout: Settings/<system>/Emulators.ini ────────────────────
    # [ROMS] carries Default_Emulator and Rom_Path.
    # [PCLauncher] carries Rom_Extension=ini explicitly so RL reads it from
    # the system file rather than falling back to Global Emulators.ini whose
    # [PCLauncher] section may omit Rom_Extension or set it to a non-ini value.
    system_folder = settings_dir / system_name
    system_folder.mkdir(parents=True, exist_ok=True)
    emulators_ini = system_folder / "Emulators.ini"
    emulator_lines = [
        "[ROMS]",
        "Default_Emulator=PCLauncher",
        f"Rom_Path={pclauncher_dir}",
        "Rom_Extension=ini",
        "",
        "[PCLauncher]",
        f"Rom_Path={pclauncher_dir}",
        "Rom_Extension=ini",
        "",
    ]
    emulators_ini.write_text("\n".join(emulator_lines), encoding="utf-8")

    return ini_path


# ─── HyperSpin system settings INI ───────────────────────────────────────────

# Minimal HyperSpin system settings template.  ``hyperlaunch=true`` in
# ``[exe info]`` is the critical key: without it HyperSpin shows
# "Cannot find <system>.ini" when the user tries to open the sub-wheel
# because it cannot find the correct launch configuration.
#
# ``parents_only=false`` prevents the wheel from hiding games that are
# not flagged as "parent" ROMs in the database (most synthetic-wheel
# entries are not tagged that way).
_HYPERSPIN_SYSTEM_INI_TEMPLATE = (
    "[exe info]\n"
    "hyperlaunch=true\n"
    "\n"
    "[filters]\n"
    "parents_only=false\n"
)


def write_hyperspin_system_ini(
    system_name: str,
    hyperspin_dir: Path,
) -> Optional[Path]:
    """Write a minimal HyperSpin system settings INI if one does not exist.

    HyperSpin requires ``<hyperspin_dir>/Settings/<system>.ini`` to be
    present when a wheel is opened as a sub-menu.  If the file is absent,
    HyperSpin reports "Cannot find <system>.ini" and the wheel never loads.

    The function only writes the file if it is **missing** — existing files
    (user-customised or created by HyperHQ) are left untouched.

    Returns the path that was written, or ``None`` if the file already existed.
    """
    settings_dir = hyperspin_dir / "Settings"
    ini_path = settings_dir / f"{system_name}.ini"
    if ini_path.exists():
        return None
    settings_dir.mkdir(parents=True, exist_ok=True)
    ini_path.write_text(_HYPERSPIN_SYSTEM_INI_TEMPLATE, encoding="utf-8")
    return ini_path


# ─── Bundled synthetic-wheel media assets ────────────────────────────────────
#
# Each dict maps an exact HyperSpin system name to the bundled asset filename
# under ``spindoctor/assets/``.  Filenames use underscores (no spaces) so they
# survive any filesystem that rejects spaces in filenames.
#
# All three install functions share the same contract:
#   • Only write when the destination is **absent** — user files are never clobbered.
#   • Return (dest_path, status) where status ∈ {installed, skipped, no_asset, dry_run}.

_WHEEL_ART_ASSETS: dict[str, str] = {
    "Favorites":       "wheel_art_Favorites.png",
    "Most Played":     "wheel_art_Most_Played.png",
    "Recently Played": "wheel_art_Recently_Played.png",
    "Recompiled":      "wheel_art_Recompiled.png",
}

# System background image — displayed behind the game list while browsing.
# HyperSpin path: Media\<SystemName>\Images\Backgrounds\<SystemName>.png
#
# Background files have been removed: the attract-mode MP4 visually fills the
# screen for all synthetic wheels, so separate per-system background PNGs are
# redundant.  Add entries here and place PNG files in assets/ to restore.
_BACKGROUND_ASSETS: dict[str, str] = {}

# Background music — plays while the user browses the wheel (active browsing,
# not attract-mode idle).  HyperSpin path: Media\Main Menu\Sound\<SystemName>.*
# (extension preserved from the source file — HyperSpin accepts .mp3 and .wav)
_MUSIC_ASSETS: dict[str, str] = {
    "Favorites":       "music_Favorites.wav",
    "Most Played":     "music_Most_Played.wav",
    "Recently Played": "music_Recently_Played.mp3",
    "Recompiled":      "music_Recompiled.wav",
}

# Attract-mode video — static-frame MP4 containing the background image and
# looped music at exactly 2× the music duration.  HyperSpin plays this video
# for the system's slot during attract-mode rotation on the Main Menu, then
# advances to the next system when playback ends.
# HyperSpin path: Media\Main Menu\Video\<SystemName>.mp4
# Durations: Favorites ≈57.7 s, Most Played ≈57.9 s, Recently Played ≈61.5 s
_VIDEO_ASSETS: dict[str, str] = {
    "Favorites":       "video_Favorites.mp4",
    "Most Played":     "video_Most_Played.mp4",
    "Recently Played": "video_Recently_Played.mp4",
    "Recompiled":      "video_Recompiled.mp4",
}

# HyperSpin theme zip — controls where HyperSpin renders the video slot when
# the system is selected on the Main Menu.
# Without a theme zip HyperSpin may not show the attract-mode video at all.
#
# Design: zip contains only Theme.xml (no Info.txt, no SWF files) — exact
# structure of the reference Favorites.zip provided by the cabinet owner.
# The <video> element is full-screen: w="1024" h="768" x="512" y="384"
# with forceaspect="both".
#
# HyperSpin path: Media\Main Menu\Themes\<SystemName>.zip
_THEME_ASSETS: dict[str, str] = {
    "Favorites":       "theme_Favorites.zip",
    "Most Played":     "theme_Most_Played.zip",
    "Recently Played": "theme_Recently_Played.zip",
    "Recompiled":      "theme_Recompiled.zip",
}

# Navigate sound — plays on every left/right cursor move while browsing the
# game list inside a synthetic wheel.
# HyperSpin path: Media\<SystemName>\Sound\Wheel Click.mp3
# (per-system Sound folder, not Media\Main Menu\Sound which is for the top-level
# wheel browsing music — a separate HyperSpin concept).
_NAVIGATE_SOUND_ASSETS: dict[str, str] = {
    "Favorites":       "navigate_sound.mp3",
    "Most Played":     "navigate_sound.mp3",
    "Recently Played": "navigate_sound.mp3",
    "Recompiled":      "navigate_sound.mp3",
}


def _install_asset(
    src: Path,
    dest: Path,
    dry_run: bool,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy *src* to *dest*.  Shared by all bundled-asset installers.

    *overwrite* controls what happens when *dest* already exists:

    * ``False`` (default) — skip if present; returns ``"skipped"``.  Used by
      ``rebuild --apply`` so user-placed files are never clobbered.
    * ``True`` — always copy; returns ``"overwritten"`` when a file was
      replaced, ``"installed"`` when the destination was absent.  Used by
      ``mainmenu add`` where the user is explicitly requesting the full
      bundled media set.

    Dry-run behaviour: never writes; returns ``"dry_run"`` when the file
    would be installed/overwritten, ``"skipped"`` when overwrite is off
    and the file already exists.
    """
    already_exists = dest.exists()
    if already_exists and not overwrite:
        return dest, "skipped"
    if dry_run:
        return dest, "dry_run"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest, "overwritten" if already_exists else "installed"


def _resolve_asset(
    registry: dict[str, str],
    system_name: str,
) -> Optional[Path]:
    """Return the absolute path to the bundled asset, or None if not registered."""
    filename = registry.get(system_name)
    if not filename:
        return None
    src = Path(__file__).parent / "assets" / filename
    return src if src.exists() else None


def install_system_wheel_art(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy the bundled Main Menu wheel art for *system_name* to HyperSpin.

    Destination::

        <hyperspin_dir>/Media/Main Menu/Images/Wheel/<system_name>.png

    When *overwrite* is ``False`` (default, used by ``rebuild --apply``) the
    file is only written if absent — user-placed images are never clobbered.
    When *overwrite* is ``True`` (used by ``mainmenu add --apply``) the bundled
    asset is always written so the wheel gets a fresh copy of every media file.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_WHEEL_ART_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = hyperspin_dir / "Media" / "Main Menu" / "Images" / "Wheel" / f"{system_name}.png"
    return _install_asset(src, dest, dry_run, overwrite=overwrite)


def install_system_background(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy the bundled background image for *system_name* to HyperSpin.

    Destination::

        <hyperspin_dir>/Media/Main Menu/Images/Backgrounds/<system_name>.png

    HyperSpin reads system-level attract-mode media from ``Media/Main Menu/``
    regardless of which system is being displayed.  This is the same directory
    as the wheel art (``Images/Wheel/``) — all system-tile assets live here.

    When *overwrite* is ``False`` (default) the file is skipped if present.
    When *overwrite* is ``True`` (``mainmenu add``) it is always written.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_BACKGROUND_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = (
        hyperspin_dir / "Media" / "Main Menu"
        / "Images" / "Backgrounds" / f"{system_name}.png"
    )
    return _install_asset(src, dest, dry_run, overwrite=overwrite)


def install_system_music(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy the bundled background music for *system_name* to HyperSpin.

    Destination::

        <hyperspin_dir>/Media/Main Menu/Sound/<system_name><ext>

    where *ext* is the source file's extension (.mp3 or .wav).  HyperSpin reads
    active-browsing audio from ``Media/Main Menu/Sound/`` — this plays while the
    user is scrolling through systems on the main menu, distinct from the
    attract-mode audio carried by the MP4 video.

    When *overwrite* is ``False`` (default) the file is skipped if present.
    When *overwrite* is ``True`` (``mainmenu add``) it is always written.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_MUSIC_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = hyperspin_dir / "Media" / "Main Menu" / "Sound" / f"{system_name}{src.suffix}"
    return _install_asset(src, dest, dry_run, overwrite=overwrite)


def install_system_video(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy the bundled attract-mode video for *system_name* to HyperSpin.

    Destination::

        <hyperspin_dir>/Media/Main Menu/Video/<system_name>.mp4

    The video is a static-frame MP4 (background image + looped music) whose
    duration is exactly 2× the bundled music track.  HyperSpin plays it during
    attract-mode rotation and advances to the next system when it ends — no
    global timer configuration required.

    When *overwrite* is ``False`` (default) the file is skipped if present.
    When *overwrite* is ``True`` (``mainmenu add``) it is always written.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_VIDEO_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = hyperspin_dir / "Media" / "Main Menu" / "Video" / f"{system_name}.mp4"
    return _install_asset(src, dest, dry_run, overwrite=overwrite)


def install_system_theme(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy the bundled HyperSpin theme zip for *system_name* to HyperSpin.

    Destination::

        <hyperspin_dir>/Media/Main Menu/Themes/<system_name>.zip

    The theme zip contains only ``Theme.xml`` (no ``Info.txt``, no SWF files),
    matching the reference layout provided by the cabinet owner.  The
    ``<video>`` element uses ``w="1024" h="768" x="512" y="384"``
    (full-screen, centred on HyperSpin's 1024×768 canvas) with
    ``forceaspect="both"``.  Without a theme zip HyperSpin may not play the
    attract-mode audio/video for the system at all.

    When *overwrite* is ``False`` (default) the file is skipped if present.
    When *overwrite* is ``True`` (``mainmenu add``) it is always written.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_THEME_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = hyperspin_dir / "Media" / "Main Menu" / "Themes" / f"{system_name}.zip"
    return _install_asset(src, dest, dry_run, overwrite=overwrite)


def install_system_navigate_sound(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[Optional[Path], str]:
    """Copy the bundled navigate sound for *system_name* to HyperSpin.

    Destination::

        <hyperspin_dir>/Media/<system_name>/Sound/Wheel Click.mp3

    HyperSpin plays this file on every left/right cursor move while the user
    browses the game list inside the wheel.  Unlike ``install_system_music``
    (which targets ``Media\\Main Menu\\Sound\\`` for top-level wheel browsing),
    this file lives inside the per-system ``Sound/`` folder.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_NAVIGATE_SOUND_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = hyperspin_dir / "Media" / system_name / "Sound" / "Wheel Click.mp3"
    return _install_asset(src, dest, dry_run, overwrite=overwrite)


def install_bundled_system_assets(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, tuple[Optional[Path], str]]:
    """Install all bundled media assets for *system_name* in one call.

    Runs :func:`install_system_wheel_art`, :func:`install_system_background`,
    :func:`install_system_music`, :func:`install_system_video`, and
    :func:`install_system_theme` and returns their results keyed by asset type
    so callers can report each outcome individually.

    *overwrite* is forwarded to each individual installer:

    * ``False`` (default) — skip files that already exist.  Used by
      ``rebuild --apply`` so user-placed media is preserved.
    * ``True`` — always write the bundled asset.  Used by
      ``mainmenu add --apply`` where the user explicitly requests a fresh
      install of every media file for the wheel.

    Return value::

        {
            "wheel_art":      (Path | None, status),
            "background":     (Path | None, status),
            "music":          (Path | None, status),
            "video":          (Path | None, status),
            "theme":          (Path | None, status),
            "navigate_sound": (Path | None, status),
        }

    Each *status* ∈ ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    return {
        "wheel_art":      install_system_wheel_art(     hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "background":     install_system_background(    hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "music":          install_system_music(         hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "video":          install_system_video(         hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "theme":          install_system_theme(         hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "navigate_sound": install_system_navigate_sound(hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
    }


# ─── HyperSpin Main Menu XML ──────────────────────────────────────────────────

def _read_main_menu_systems(path: Path) -> list[str]:
    """Return current <game name="..."/> entries from Main Menu.xml (or [])."""
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        import sys
        print(
            f"WARNING: Main Menu.xml at {path} could not be parsed ({exc}) — "
            "existing system entries will not be preserved. "
            "Run: spindoctor doctor  to check your HyperSpin files.",
            file=sys.stderr,
        )
        return []
    return [
        (g.get("name") or "").strip()
        for g in tree.getroot().findall("game")
        if (g.get("name") or "").strip()
    ]


def _write_main_menu(systems: list[str], out_path: Path) -> Path:
    """Write Main Menu.xml in HyperSpin's native minimal format.

    Native shape: a bare ``<menu>`` containing ``<game name="..."/>`` entries,
    no XML declaration, no ``<header>``, no child elements. This is what
    HyperSpin ships and what its parser expects; bloated formats (with empty
    ``<description>``/``<enabled>`` children) cause "Error creating main menu"
    on some HyperSpin builds.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("menu")
    for sys_name in systems:
        ET.SubElement(root, "game", name=sys_name)

    tree = ET.ElementTree(root)
    et_indent(tree)
    with open(out_path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=False)
    return out_path


def generate_hs_main_menu(
    systems: list[str],
    config: Config,
    output_base: Optional[Path] = None,
) -> Path:
    """Sync Databases/Main Menu/Main Menu.xml to match *systems*.

    Preserves the existing wheel order when the file already exists:
    - entries still present in *systems* keep their current positions
    - newly-discovered systems are appended at the end (in the order
      they appear in *systems*, which is typically alphabetical)
    - entries no longer in *systems* are dropped

    Synthetic wheels (Favorites, Recently Played, Most Played) that are
    already in the XML are always preserved, even though they are not
    included in the *systems* list passed by generate-config (those
    systems are managed by fav/recent/stats rebuild, not by generate-config).
    Without this, generate-config would silently remove them on every run.

    When the file doesn't exist yet the order of *systems* is used as-is.
    """
    target = _main_menu_path(config, output_base)
    systems_set = set(systems)

    # Synthetic wheels are excluded from generate-config's systems list
    # (SKIP_GENERATE_CONFIG) but must not be dropped from Main Menu.xml.
    # "Main Menu" is in SKIP_GENERATE_CONFIG but is never an entry in its
    # own XML, so we exclude it from the preserve set.
    _preserve = SKIP_GENERATE_CONFIG - {"Main Menu"}

    existing = _read_main_menu_systems(target)
    ordered: list[str] = [s for s in existing if s in systems_set or s in _preserve]
    already_listed = set(ordered)
    for s in systems:
        if s not in already_listed:
            ordered.append(s)

    return _write_main_menu(ordered, target)


def upsert_main_menu_system(
    system_name: str,
    config: Config,
    output_base: Optional[Path] = None,
) -> tuple[Path, bool]:
    """Add *system_name* to Main Menu.xml without disturbing other entries.

    Returns ``(path, added)`` where ``added`` is False if the system was
    already listed.
    """
    out_path = _main_menu_path(config, output_base)
    existing = _read_main_menu_systems(out_path)
    if system_name in existing:
        return out_path, False
    existing.append(system_name)
    _write_main_menu(existing, out_path)
    return out_path, True


# ─── System database stubs ────────────────────────────────────────────────────

def generate_system_db_stubs(
    systems: list[str],
    config: Config,
    output_base: Optional[Path] = None,
) -> list[Path]:
    """Create empty database XMLs for systems that don't have one yet."""
    from .database import HyperspinDatabase

    created = []
    db_base = output_base / "Databases" if output_base else config.databases_dir

    for sys_name in systems:
        xml_path = db_base / sys_name / f"{sys_name}.xml"
        if xml_path.exists():
            continue
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        db = HyperspinDatabase(sys_name, xml_path)
        db.load()
        db.save(backup=False)
        created.append(xml_path)

    return created


# ─── PCLauncher per-game INIs ─────────────────────────────────────────────────

# Characters Windows forbids in filenames.
_WIN_FILENAME_FORBIDDEN = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")

# Windows device names that cannot be used as filenames regardless of extension.
# "NUL.png" writes to the null device; "CON.mp4" maps to the console, etc.
_WIN_RESERVED_NAMES: frozenset = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM0", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT0", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

# Lowercase stem-prefixes that identify non-game executables (uninstallers,
# setup helpers, redistributables, etc.).  Used by list_exe_candidates and
# _pick_best_exe to separate "recommended" launches from noise.
_EXE_EXCLUSION_PREFIXES: tuple[str, ...] = (
    "unins", "uninst", "setup", "install",
    "vc_redist", "vcredist", "dxsetup", "directx",
    "crashpad", "dotnet", "helper", "updater",
    "unitycrashhandler", "cef",
    # NW.js / Electron runtimes bundle chromedriver alongside the real launcher
    "chromedriver", "nwjc", "nacl_irt",
)


def _win_safe_stem(title: str) -> str:
    """Strip Windows-invalid characters from *title* to produce a safe INI stem.

    The result is used as the INI **filename** only.  The INI **section
    header** (``[<name>]``) must still use the original HyperSpin dbName
    (which may contain colons) so PCLauncher.ahk can find it.
    """
    out = title
    for ch in _WIN_FILENAME_FORBIDDEN:
        out = out.replace(ch, "")
    out = out.strip().rstrip(".")
    # Guard against Windows reserved device names — these map to system devices
    # rather than files (e.g. "NUL.png" writes to the null device, not a file).
    if out.upper() in _WIN_RESERVED_NAMES:
        out = out + "_"
    return out


def _pclauncher_ini_text(game_name: str, executable) -> str:
    """Render the PCLauncher per-game INI body for *game_name* pointing at *executable*.

    PCLauncher.ahk looks up ``[<game_name>]`` sections and reads ``Application=``.
    *executable* may be any path-like (str, Path, PureWindowsPath).  We
    leave the path string verbatim so Windows-style paths produced from a
    macOS/Linux dev box (or vice-versa) round-trip without mangling.
    """
    return (
        f"[{game_name}]\n"
        f"Application={executable}\n"
        f"WorkingFolder={executable.parent}\n"
    )


def list_exe_candidates(game_dir: Path, title_hint: str = "") -> list:
    """Return .exe/.ahk/.bat files in *game_dir* and every subdirectory, recommended first.

    Sort priority (ascending = better):
    1. File type: non-excluded .exe → .ahk → .bat → excluded .exe.
    2. Depth relative to *game_dir* — shallower files first (0 = top-level).
    3. Stem similarity to *title_hint* — exact match, partial match, no match.
    4. File name alphabetically.
    """
    if not game_dir.is_dir():
        return []
    hint_norm = re.sub(r"[^a-z0-9]", "", title_hint.lower())

    def _sort_key(p: Path) -> tuple:
        ext = p.suffix.lower()
        is_excluded_exe = ext == ".exe" and any(
            p.stem.lower().startswith(pf) for pf in _EXE_EXCLUSION_PREFIXES
        )
        if ext == ".exe" and not is_excluded_exe:
            type_rank = 0
        elif ext == ".ahk":
            type_rank = 1
        elif ext == ".bat":
            type_rank = 2
        else:
            type_rank = 3  # excluded .exe
        depth = len(p.relative_to(game_dir).parts) - 1  # 0 = directly in game_dir
        stem_norm = re.sub(r"[^a-z0-9]", "", p.stem.lower())
        if stem_norm == hint_norm:
            similarity = 0
        elif hint_norm and (stem_norm in hint_norm or hint_norm in stem_norm):
            similarity = 1
        else:
            similarity = 2
        return (type_rank, depth, similarity, p.name.lower())

    candidates: list = []
    for glob in ("*.exe", "*.ahk", "*.bat"):
        candidates.extend(p for p in game_dir.rglob(glob) if p.is_file())
    return sorted(candidates, key=_sort_key)


def _pick_best_exe(game_dir: Path, title_hint: str = "") -> Optional[Path]:
    """Return the most-likely launcher in *game_dir*, or None.

    Delegates to :func:`list_exe_candidates` and returns the first entry
    that is *not* in the excluded-prefix set.  For PCLauncher systems that
    use .ahk or .bat launchers the caller should verify the auto-detected
    path makes sense; use --exe / Browse to override when needed.
    """
    for p in list_exe_candidates(game_dir, title_hint):
        if not any(p.stem.lower().startswith(pf) for pf in _EXE_EXCLUSION_PREFIXES):
            return p
    return None


def _resolve_pclauncher_exe(rom_path, title: str):
    """Return the best Application= path for a PC game.

    When *rom_path* is already a ``.exe`` it is returned as-is (preserving
    whatever path type was passed — ``PureWindowsPath``, ``Path``, or ``str``).

    For non-exe ROMs (.lnk, .zip, webcache, …) the function first checks
    whether a game-named subdirectory exists alongside the ROM file (e.g.
    ``PC Games/Hades/`` next to ``PC Games/Hades.lnk``); if so it uses
    :func:`_pick_best_exe` to scan that subdirectory recursively.

    If no game-named subdirectory is found, the parent directory is searched
    *non-recursively* — it is typically a system-level folder (e.g.
    ``PC Games/``) and a recursive scan would cross into sibling game folders.

    Falls back to *rom_path* when no ``.exe`` is found.

    Avoids converting *rom_path* through ``Path()`` when the suffix already
    matches ``.exe`` — that conversion would mangle Windows-style backslash
    paths on macOS/Linux.
    """
    try:
        suffix = rom_path.suffix.lower()      # PurePath / Path
    except AttributeError:
        import os as _os
        suffix = _os.path.splitext(str(rom_path))[1].lower()
    if suffix == ".exe":
        return rom_path

    parent = Path(rom_path).parent
    stem = Path(str(rom_path)).stem

    # Look for a game-named subdirectory first (e.g. "Hades/" next to "Hades.lnk").
    # Scan it recursively — depth-sorted so the main exe rises to the top.
    game_subdir = parent / stem
    if game_subdir.is_dir():
        best = _pick_best_exe(game_subdir, title)
        if best is not None:
            return best

    # Fall back: scan the parent directory non-recursively only.  The parent is
    # usually a system folder; rglob would reach into sibling game directories.
    for p in sorted(parent.glob("*.exe")):
        if p.is_file() and not any(
            p.stem.lower().startswith(pf) for pf in _EXE_EXCLUSION_PREFIXES
        ):
            return p

    return rom_path


def rewrite_pclauncher_application(ini_path: Path, section: str, new_exe: Path) -> bool:
    """Update ``Application=`` and ``WorkingFolder=`` in *section* of *ini_path*.

    Only those two keys are modified; all other keys (``FadeTitle=``, etc.)
    survive verbatim.  Line endings are preserved.  If *section* is not found
    in the file, the block is appended.  Returns ``True`` when the file was
    actually changed, ``False`` when it was unchanged or missing.
    """
    if not ini_path.exists():
        return False
    lines = ini_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    in_section = False
    section_found = False
    new_lines: list = []
    changed = False
    for line in lines:
        stripped = line.rstrip("\r\n")
        eol = line[len(stripped):]
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].lower() == section.lower()
            if in_section:
                section_found = True
        if in_section and re.match(r"(?i)^Application\s*=", stripped):
            want = f"Application={new_exe}"
            if stripped != want:
                new_lines.append(want + eol)
                changed = True
                continue
        if in_section and re.match(r"(?i)^WorkingFolder\s*=", stripped):
            want = f"WorkingFolder={new_exe.parent}"
            if stripped != want:
                new_lines.append(want + eol)
                changed = True
                continue
        new_lines.append(line)
    if not section_found:
        # Section is absent — append it after a blank separator line.
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append("\n" + _pclauncher_ini_text(section, new_exe))
        changed = True
    if changed:
        ini_path.write_text("".join(new_lines), encoding="utf-8")
    return changed


def repath_pclauncher_system_ini(
    system_ini: Path,
    system_name: str,
    new_rom_path: str,
    apply: bool = False,
) -> tuple:
    """Re-prefix all ``Application=`` paths in a PCLauncher system-level INI.

    When a system's game folder moves to a new drive (e.g. from
    ``D:\\Arcade\\Games\\Taito Type X`` to ``J:\\Games\\Taito Type X``),
    this rewrites every ``[GameName]`` section's ``Application=`` entry so the
    path is rooted under *new_rom_path*.

    The game-relative suffix (e.g. ``Arcana Heart 3\\CleanLaunch.ahk``) is
    extracted by locating ``<system_name>\\`` in the current path and taking
    everything after it.

    Returns a 2-tuple ``(changes, skipped)`` where:
      - *changes*: list of ``(game_name, old_path, new_path)`` for every entry
        that would change (or changed when *apply* is ``True``).
      - *skipped*: list of ``(game_name, old_path)`` for entries whose
        ``Application=`` path did not contain the system name as a directory
        component and therefore could not be re-prefixed automatically.

    Caller is responsible for making a backup of *system_ini* before calling
    with ``apply=True``.
    """
    if not system_ini.exists():
        return [], []

    lines = system_ini.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    delimiter = system_name.replace("/", "\\") + "\\"

    # First pass — collect which Application= values need changing and which
    # can't be resolved because the system name isn't in the path.
    section_changes: dict = {}
    section_skipped: dict = {}
    current_section = ""
    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
            continue
        if current_section and re.match(r"(?i)^Application\s*=", stripped):
            old_path = stripped.split("=", 1)[1]
            normalised = old_path.replace("/", "\\")
            idx = normalised.lower().find(delimiter.lower())
            if idx == -1:
                section_skipped[current_section] = old_path
                continue
            suffix = normalised[idx + len(delimiter):]
            new_path = new_rom_path.rstrip("\\") + "\\" + suffix
            if normalised != new_path:
                section_changes[current_section] = (old_path, new_path)

    changes = [
        (game, old, new_p)
        for game, (old, new_p) in sorted(section_changes.items())
    ]
    skipped = [
        (game, path)
        for game, path in sorted(section_skipped.items())
    ]

    if not apply or not changes:
        return changes, skipped

    # Second pass — rewrite in place.
    current_section = ""
    new_lines: list = []
    for line in lines:
        stripped = line.rstrip("\r\n")
        eol = line[len(stripped):]
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
        if current_section in section_changes and re.match(
            r"(?i)^Application\s*=", stripped
        ):
            _, new_path = section_changes[current_section]
            new_lines.append(f"Application={new_path}" + eol)
            continue
        new_lines.append(line)

    system_ini.write_text("".join(new_lines), encoding="utf-8")
    return changes, skipped


def read_pclauncher_ini_application_path(
    ini_path: Path,
    section_name: Optional[str] = None,
) -> str:
    """Return the Application= value from the ``[<game_name>]`` section of a per-game
    PCLauncher INI, or '' if not found.

    *section_name* overrides the section to search for.  When omitted the
    function falls back to ``ini_path.stem`` — which is correct only when
    the HyperSpin dbName and the INI filename stem are identical.  Pass the
    actual dbName (which may contain colons) so stale-detection works even
    when the filename had those characters stripped.

    INIs written in the old ``[Settings] / ApplicationPath=`` format return
    '' so they are treated as stale and regenerated on the next
    ``--overwrite-pclauncher`` run.
    """
    try:
        game_name = (section_name if section_name else ini_path.stem).lower()
        in_game_section = False
        for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and "]" in stripped:
                section = stripped[1:stripped.index("]")].lower()
                in_game_section = (section == game_name)
            elif in_game_section and stripped.lower().startswith("application="):
                return stripped.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def pclauncher_settings_text(executable, parameters: str = "") -> str:
    """Render a ``[Settings]``-format PCLauncher INI that launches *executable*.

    Unlike ``[exe info]``, this format does not require ``fadetitle`` or a
    monitored process — PCLauncher launches the exe and returns immediately.

    Used for synthetic-wheel per-game INIs that invoke ``RocketLauncher.exe
    -p HyperSpin``: RL handles the HyperSpin fade/unfade itself via the
    ``-p HyperSpin`` flag, so PCLauncher does not need to monitor any window.
    """
    exe = Path(executable)
    return (
        "[Settings]\n"
        f"ApplicationPath={exe}\n"
        f"ApplicationParameters={parameters}\n"
        f"StartIn={exe.parent}\n"
    )


def _read_system_default_emulator(source_system: str, rocketlauncher_dir: Path) -> str:
    """Return the Default_Emulator name configured for *source_system* in RL's settings.

    Checks folder layout (``Settings/<system>/Emulators.ini`` → ``[ROMS]``) first,
    then flat layout (``Settings/<system>.ini`` → ``[Settings]``).
    Returns an empty string if neither file exists or the key is not set.
    """

    settings_dir = rocketlauncher_dir / "Settings"

    # Folder layout: Settings/<system>/Emulators.ini → [ROMS] Default_Emulator
    folder_ini = settings_dir / source_system / "Emulators.ini"
    if folder_ini.exists():
        try:
            cp = configparser.RawConfigParser()
            cp.read_string(folder_ini.read_text(encoding="utf-8", errors="replace"))
            val = cp.get("ROMS", "Default_Emulator", fallback="").strip()
            if val:
                return val
        except Exception:
            pass

    # Flat layout: Settings/<system>.ini → [Settings] Default_Emulator
    flat_ini = settings_dir / f"{source_system}.ini"
    if flat_ini.exists():
        try:
            cp = configparser.RawConfigParser()
            cp.read_string(flat_ini.read_text(encoding="utf-8", errors="replace"))
            val = cp.get("Settings", "Default_Emulator", fallback="").strip()
            if val:
                return val
        except Exception:
            pass

    return ""


def _read_emulator_exe(emulator_name: str, rocketlauncher_dir: Path) -> str:
    """Return the bare exe filename for *emulator_name* from ``Global Emulators.ini``.

    Tries ``Emu_Path`` and ``Emulator_Application_Path`` keys (cabinet installations
    vary).  Falls back to the ``EMULATOR_EXECUTABLES`` dict when the global INI
    is absent or the emulator has no entry.

    Returns an empty string if the emulator is completely unknown.
    """

    global_ini = rocketlauncher_dir / "Settings" / "Global Emulators.ini"
    if global_ini.exists():
        try:
            from pathlib import PureWindowsPath
            cp = configparser.RawConfigParser()
            cp.read_string(global_ini.read_text(encoding="utf-8", errors="replace"))
            if cp.has_section(emulator_name):
                for key in ("Emu_Path", "Emulator_Application_Path", "emulator_path", "emu_path"):
                    if cp.has_option(emulator_name, key):
                        path_str = cp.get(emulator_name, key).strip()
                        if path_str:
                            return PureWindowsPath(path_str).name
        except Exception:
            pass

    return EMULATOR_EXECUTABLES.get(emulator_name, "")


def _read_pclauncher_game_exe(
    source_system: str, source_rom: str, rocketlauncher_dir: Path
) -> str:
    """Return the bare exe name from a per-game PCLauncher INI.

    For source systems that are themselves PCLauncher-based (e.g. "PC Games"),
    the game's actual executable is recorded in
    ``Modules/PCLauncher/<source_system>/<source_rom>.ini`` under
    ``ApplicationPath=``.

    Only returns a value when ``ApplicationPath`` ends in ``.exe`` — shortcuts
    (``.lnk``), batch files (``.bat``), and URL launchers (``.url``) are not
    process names and cannot be used as ``AppWaitExe``.

    Returns an empty string if the INI is absent, unreadable, or the path is
    not a plain executable.
    """
    from pathlib import PureWindowsPath

    game_ini = (
        rocketlauncher_dir / "Modules" / "PCLauncher" / source_system / f"{source_rom}.ini"
    )
    if not game_ini.exists():
        return ""
    try:
        cp = configparser.RawConfigParser()
        cp.read_string(game_ini.read_text(encoding="utf-8", errors="replace"))
        for section in cp.sections():
            for key in ("ApplicationPath", "applicationpath", "Application", "application"):
                if cp.has_option(section, key):
                    path_str = cp.get(section, key).strip()
                    if path_str:
                        name = PureWindowsPath(path_str).name
                        if name.lower().endswith(".exe"):
                            return name
    except Exception:
        pass
    return ""


def _get_app_wait_exe(
    source_system: str, rocketlauncher_dir: Path, source_rom: str = ""
) -> str:
    """Return the ``AppWaitExe=`` value for a PCLauncher entry targeting *source_system*.

    PCLauncher.ahk monitors the launched process via one of two mechanisms:

    1. **Window wait** (default): waits for a window owned by the Application's PID.
       RL#2 in standalone mode (no ``-p HyperSpin``) never creates a visible window,
       so this times out after ~30 s with "error waiting for window ahk_pid XXXX".

    2. **AppWaitExe** (explicit): tells PCLauncher to monitor a named exe instead of
       waiting for a window.  When set, PCLauncher polls for that process to exit,
       which works regardless of whether a window is present.

    For non-PCLauncher source systems (e.g. MAME, RetroArch) the emulator exe
    is resolved via RL's settings files and the ``EMULATOR_EXECUTABLES`` table.

    For PCLauncher-based source systems (e.g. "PC Games"), the actual game exe
    is read from ``Modules/PCLauncher/<source_system>/<source_rom>.ini``.  Only
    ``.exe`` paths are usable — shortcuts (``.lnk``), batch files (``.bat``),
    and URL launchers (``.url``) are not process names, so those entries omit
    ``AppWaitExe`` and fall back to PCLauncher's standard process-exit detection.

    *source_rom* is only needed (and used) when *source_system* resolves to
    PCLauncher; pass it whenever the ROM name is known.
    """
    emulator = _read_system_default_emulator(source_system, rocketlauncher_dir)
    if not emulator:
        emulator = guess_emulator(source_system)

    if emulator == "PCLauncher":
        return _read_pclauncher_game_exe(source_system, source_rom, rocketlauncher_dir)

    return _read_emulator_exe(emulator, rocketlauncher_dir)


def _get_fade_title(
    source_system: str,
    rocketlauncher_dir: Path,
    extra: "dict[str, str] | None" = None,
) -> str:
    """Return the ``FadeTitle=`` window-title fragment for *source_system*'s emulator.

    Looks up the system's configured emulator name (from RL settings) first in
    *extra* (user-supplied overrides from :attr:`~spindoctor.config.Config.emulator_window_titles`),
    then falls back to the built-in :data:`EMULATOR_WINDOW_TITLES` table.
    Returns an empty string when the emulator is unknown or PCLauncher-based.

    *extra* values take precedence so users can override a built-in entry or
    add support for any emulator not yet in the built-in table — without
    editing source code.

    See the :data:`EMULATOR_WINDOW_TITLES` docstring for why ``FadeTitle``
    is necessary alongside ``AppWaitExe`` to avoid the 30-second
    "waiting for window ahk_pid" error from PCLauncher.ahk.
    """
    emulator = _read_system_default_emulator(source_system, rocketlauncher_dir)
    if not emulator or emulator == "PCLauncher":
        return ""
    merged: dict[str, str] = {**EMULATOR_WINDOW_TITLES, **(extra or {})}
    # Fall back to the emulator name itself: AHK WinWait uses case-insensitive
    # partial matching, so "Supermodel" matches "Supermodel 3.1 UI", etc.
    # This makes FadeTitle work for any emulator automatically — EMULATOR_WINDOW_TITLES
    # only needs entries where the name genuinely doesn't appear in the window title.
    return merged.get(emulator, emulator)


def ensure_rl_game_exe(rocketlauncher_dir: Path) -> Path:
    """Ensure ``RocketLauncherGame.exe`` exists as a copy of ``RocketLauncher.exe``.

    **Why a renamed copy?**  ``RocketLauncher.exe`` is a compiled AutoHotkey
    script that uses ``#SingleInstance`` to prevent two instances of the *same*
    executable from running simultaneously.  AHK's single-instance mutex is
    keyed to the executable's full path, so a copy under a different filename
    has a unique identity and is not affected by the restriction.

    When a game is launched from a synthetic wheel (Favorites, Recently Played,
    Most Played), the launch chain is:

        HyperSpin → RL#1 (``RocketLauncher.exe``, loads PCLauncher module)
                  → ``PCLauncher.exe``
                  → RL#2 (``RocketLauncher.exe``, should launch the emulator)

    RL#2 detects RL#1 already running under the same executable path and
    exits immediately due to ``#SingleInstance`` — before opening the log
    file, before loading the emulator module, before launching anything.
    PCLauncher's ``AppWaitExe`` timer runs out waiting for an emulator process
    that will never appear.

    Using ``RocketLauncherGame.exe`` as RL#2 bypasses the conflict entirely:
    both instances run freely, RL#2 loads the emulator module normally, and
    the emulator appears within seconds.

    Returns the path to ``RocketLauncherGame.exe``.  If ``RocketLauncher.exe``
    is missing or the copy cannot be written (permissions, network share issue),
    falls back to returning ``RocketLauncher.exe`` so callers are not broken.
    """
    import shutil

    src = rocketlauncher_dir / "RocketLauncher.exe"
    dst = rocketlauncher_dir / "RocketLauncherGame.exe"
    if not src.exists():
        return src  # nothing to copy; caller falls back gracefully
    try:
        src_stat = src.stat()
        # Recreate the copy if it is absent or has a different size (which
        # indicates a RL update replaced the original since the last refresh).
        if not dst.exists() or dst.stat().st_size != src_stat.st_size:
            shutil.copy2(src, dst)
    except OSError:
        return src  # copy failed; fall back to the original
    return dst


def write_pclauncher_system_ini(
    system_name: str,
    entries: list,
    rocketlauncher_dir: Path,
    rl_exe: Optional[Path] = None,
    extra_window_titles: "dict[str, str] | None" = None,
) -> Path:
    """Write the system-level PCLauncher INI that PCLauncher.ahk reads.

    PCLauncher.ahk locates game configuration by reading
    ``Modules/PCLauncher/<SystemName>.ini`` and looking up ``[<game_name>]``
    sections within it.  Per-game placeholder files in the same-named
    subdirectory are used only by RocketLauncher for ROM discovery and are
    not read by PCLauncher.ahk.

    *entries* is a list of ``(target_name, source_system, source_rom)`` tuples.
    Each entry produces::

        [<target_name>]
        Application=<RocketLauncherGame.exe>
        Parameters=-s "<source_system>" -r "<source_rom>"
        WorkingFolder=<rocketlauncher_dir>
        AppWaitExe=<emulator.exe>   ← present when source emulator can be resolved

    *rl_exe* — path to the RocketLauncher executable to use as ``Application=``.
    Callers should pass the result of :func:`ensure_rl_game_exe` so that RL#2
    runs under a different filename and bypasses AHK's ``#SingleInstance``
    mutex.  Defaults to ``rocketlauncher_dir/RocketLauncher.exe`` when omitted.

    **Why no ``-p HyperSpin``:** RL#1 (launched by HyperSpin for the
    Favorites/Recently Played/Most Played wheel) already owns the HyperSpin IPC
    pipe.  Without ``-p HyperSpin``, RL#2 runs in standalone mode: it launches
    the emulator, waits for it to exit, then returns.  PCLauncher (inside RL#1)
    detects RL#2's exit and returns control to RL#1, which handles the
    fade-back to HyperSpin normally.

    **Why ``AppWaitExe`` + ``FadeTitle``:**
    RL#2 in standalone mode never creates a visible window under its own PID.
    Without ``FadeTitle``, PCLauncher.ahk (source lines 214-224) waits for a
    window owned by the AppWaitExe PID — but many DirectX emulators run in
    exclusive fullscreen or create their game window in a child process, so the
    PID-based wait always fails after ~30 s ("error waiting for window
    ahk_pid XXXX") even though the game is running.

    Setting ``FadeTitle`` bypasses that PID-based search: PCLauncher finds the
    window by *title* instead (which works regardless of child-process
    hierarchy).  ``AppWaitExe.WaitClose()`` then handles exit detection cleanly.
    ``FadeTitleTimeout`` caps the start-up wait so PCLauncher doesn't hang
    forever if the emulator crashes before showing a window.

    Returns the path of the written file.
    """
    rl_exe = rl_exe or (rocketlauncher_dir / "RocketLauncher.exe")
    system_ini = rocketlauncher_dir / "Modules" / "PCLauncher" / f"{system_name}.ini"
    lines: list[str] = []
    for target_name, source_system, source_rom in entries:
        app_wait_exe = _get_app_wait_exe(source_system, rocketlauncher_dir, source_rom)
        fade_title = _get_fade_title(source_system, rocketlauncher_dir, extra_window_titles)
        lines.append(f"[{target_name}]")
        lines.append(f"Application={rl_exe}")
        lines.append(f'Parameters=-s "{source_system}" -r "{source_rom}"')
        lines.append(f"WorkingFolder={rocketlauncher_dir}")
        if app_wait_exe:
            lines.append(f"AppWaitExe={app_wait_exe}")
        if fade_title:
            lines.append(f"FadeTitle={fade_title}")
            lines.append(f"FadeTitleTimeout={_FADE_TITLE_TIMEOUT}")
        lines.append("")
    system_ini.parent.mkdir(parents=True, exist_ok=True)
    system_ini.write_text("\n".join(lines), encoding="utf-8")
    return system_ini


def generate_pclauncher_inis(
    system_name: str,
    title_to_path: dict,
    config: Config,
    output_base: Optional[Path] = None,
    overwrite: bool = False,
    title_to_section: Optional[dict] = None,
) -> tuple[Path, list[Path], list[Path]]:
    """Write per-game PCLauncher INIs for *system_name*.

    Each INI lives at
    ``<RL>/Modules/PCLauncher/<system>/<stem>.ini`` and tells the
    PCLauncher AHK module which executable to actually launch when
    HyperSpin asks RocketLauncher to run the game.

    *title_to_section* maps a folder-derived title (which may have had
    Windows-invalid characters stripped) to the exact HyperSpin dbName that
    PCLauncher.ahk uses when looking up the ``[<section>]`` header.  When a
    mapping is provided the INI **filename** uses the Windows-safe stem while
    the **section header** uses the original dbName (e.g. filename
    ``Submachine Legacy.ini`` but section ``[Submachine: Legacy]``).  This
    ensures PCLauncher finds the correct section when the game name contains
    colons or other characters that are invalid in Windows filenames.

    Returns ``(module_dir, written_paths, skipped_paths)``.  Existing INIs
    are left alone unless *overwrite* is set so user edits survive a
    re-run of ``add-pc-system``.
    """
    rl_base = output_base or (
        Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None
    )
    if not rl_base:
        raise ValueError(
            "rocketlauncher_dir not configured. "
            "Run: spindoctor config set rocketlauncher_dir <path>  "
            "or pass --output-dir."
        )

    module_dir = rl_base / "Modules" / "PCLauncher" / system_name
    module_dir.mkdir(parents=True, exist_ok=True)

    _sec = title_to_section or {}
    written: list[Path] = []
    skipped: list[Path] = []
    for title, exe_path in sorted(title_to_path.items()):
        stem = _win_safe_stem(title)
        ini_path = module_dir / f"{stem}.ini"
        section = _sec.get(title, title)
        if ini_path.exists() and not overwrite:
            skipped.append(ini_path)
            continue
        # If the "rom" RL found is not an exe (e.g. webcache.zip from a GOG
        # install), resolve the real game executable from the same folder.
        resolved = _resolve_pclauncher_exe(exe_path, title)
        ini_path.write_text(_pclauncher_ini_text(section, resolved), encoding="utf-8")
        written.append(ini_path)
    return module_dir, written, skipped


# ─── Toolkit module-INI helper ────────────────────────────────────────────────

#: Stems of every tool entry that install-tools can write.  Kept here so
#: write_toolkit_module_ini can strip stale SpinDoctor sections without
#: importing from cli.py (which would create a circular dependency).
_TOOLKIT_TOOL_NAMES: frozenset = frozenset({
    "Refresh Favorites",
    "Refresh Recently Played",
    "Refresh Most Played",
    "Refresh Both",
    "Refresh All",
})


def write_toolkit_module_ini(
    system_name: str,
    tool_entries: "list[tuple[str, Path]]",
    rocketlauncher_dir: Path,
) -> Path:
    """Write or update the PCLauncher module INI for a Toolkit-style wheel.

    PCLauncher.ahk reads ``Modules/PCLauncher/<system>.ini`` and looks up
    ``[<game_name>]`` sections to find ``Application=``, ``FadeTitle=``, etc.
    Without an entry here PCLauncher errors: "You have not set up <game> in
    RocketLauncherUI yet, so PCLauncher does not know what exe, FadeTitle,
    and/or SteamID to watch for."

    *tool_entries* is a list of ``(tool_name, bat_path)`` pairs.  Each bat
    is launched directly — no recursive RocketLauncher call — so no
    ``FadeTitle`` or ``AppWaitExe`` is needed; PCLauncher will track the
    ``cmd.exe`` PID of the running batch.

    When the file already exists, existing non-SpinDoctor sections are
    preserved.  SpinDoctor-managed sections (from :data:`_TOOLKIT_TOOL_NAMES`)
    are replaced with the freshly generated ones.
    """
    module_ini = rocketlauncher_dir / "Modules" / "PCLauncher" / f"{system_name}.ini"

    # Build the replacement section text for each SpinDoctor tool.
    new_section_lines: list[str] = []
    for tool_name, bat_path in tool_entries:
        new_section_lines.append(f"[{tool_name}]")
        new_section_lines.append(f"Application={bat_path}")
        new_section_lines.append(f"WorkingFolder={bat_path.parent}")
        new_section_lines.append("")
    new_sections = "\n".join(new_section_lines)

    if module_ini.exists():
        # Preserve non-SpinDoctor sections; replace SpinDoctor ones.
        existing = module_ini.read_text(encoding="utf-8", errors="replace")
        preserved_lines: list[str] = []
        in_sd_section = False
        for line in existing.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section_name = stripped[1:-1]
                in_sd_section = section_name in _TOOLKIT_TOOL_NAMES
            if not in_sd_section:
                preserved_lines.append(line)
        base = "".join(preserved_lines)
        if base and not base.endswith("\n"):
            base += "\n"
        content = base + new_sections
    else:
        module_ini.parent.mkdir(parents=True, exist_ok=True)
        content = new_sections

    module_ini.write_text(content, encoding="utf-8")
    return module_ini


# ─── ROM extension helpers ────────────────────────────────────────────────────

def read_rl_rom_extensions(
    system_name: str,
    rocketlauncher_dir: Optional[Path],
) -> Optional[set[str]]:
    """Return the configured ``Rom_Extension`` set for *system_name* from RL settings.

    Resolution order:
    1. Read the default emulator for the system from ``Settings/<system>/Emulators.ini``
       (folder layout) or ``Settings/<system>.ini`` (flat layout).
    2. Look up that emulator's ``Rom_Extension`` value in ``Global Emulators.ini``.
    3. Fall back to :data:`EMULATOR_EXTENSIONS` keyed by the guessed emulator name.

    Returns ``None`` when *rocketlauncher_dir* is not provided, the files cannot be
    read, or no extension list can be resolved.
    """
    if not rocketlauncher_dir:
        return None


    emulator = _read_system_default_emulator(system_name, rocketlauncher_dir)
    if not emulator:
        emulator = guess_emulator(system_name)

    global_ini = rocketlauncher_dir / "Settings" / "Global Emulators.ini"
    if global_ini.exists() and emulator:
        try:
            cp = configparser.RawConfigParser()
            cp.read_string(global_ini.read_text(encoding="utf-8", errors="replace"))
            if cp.has_section(emulator):
                ext_str = cp.get(emulator, "Rom_Extension", fallback="").strip()
                if ext_str:
                    return {e.lower() for e in ext_str.split("|") if e.strip()}
        except Exception:
            pass

    if emulator and emulator in EMULATOR_EXTENSIONS:
        return {e.lower() for e in EMULATOR_EXTENSIONS[emulator].split("|") if e.strip()}

    return None


