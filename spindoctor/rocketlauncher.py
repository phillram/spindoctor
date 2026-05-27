"""RocketLauncher system INI and HyperSpin Main Menu XML generation."""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

from ._compat import et_indent
from .config import Config, get_rom_extensions, get_system_overrides
from .database import _set_text as _set
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
    "Main Menu",
})


EMULATOR_MAP: dict[str, str] = {
    "mame": "MAME",
    "arcade": "MAME",
    "cps1": "MAME",
    "cps2": "MAME",
    "cps3": "MAME",
    "neogeo": "MAME",
    "neo geo": "MAME",
    "nes": "RetroArch",
    "nintendo entertainment system": "RetroArch",
    "famicom": "RetroArch",
    "snes": "RetroArch",
    "super nintendo": "RetroArch",
    "super famicom": "RetroArch",
    "genesis": "RetroArch",
    "mega drive": "RetroArch",
    "sega genesis": "RetroArch",
    "n64": "Project64",
    "nintendo 64": "Project64",
    "gba": "RetroArch",
    "game boy advance": "RetroArch",
    "gameboy": "RetroArch",
    "game boy": "RetroArch",
    "game boy color": "RetroArch",
    "gbc": "RetroArch",
    "psx": "RetroArch",
    "playstation": "RetroArch",
    "ps2": "PCSX2",
    "playstation 2": "PCSX2",
    "dreamcast": "Demul",
    "gamecube": "Dolphin",
    "wii": "Dolphin",
    "atari 2600": "RetroArch",
    "atari 7800": "RetroArch",
    "atari lynx": "RetroArch",
    "master system": "RetroArch",
    "sega master system": "RetroArch",
    "game gear": "RetroArch",
    "turbografx": "RetroArch",
    "turbografx-16": "RetroArch",
    "pc engine": "RetroArch",
    # PC / Windows / Steam — RocketLauncher PCLauncher module reads a
    # per-game INI to find the actual executable.
    "pc": "PCLauncher",
    "pc games": "PCLauncher",
    "windows": "PCLauncher",
    "windows games": "PCLauncher",
    "steam": "PCLauncher",
    "steam games": "PCLauncher",
}


def guess_emulator(system_name: str) -> str:
    ovr = get_system_overrides().get(system_name, {})
    if isinstance(ovr.get("emulator"), str) and ovr["emulator"]:
        return ovr["emulator"]
    return EMULATOR_MAP.get(system_name.lower(), "RetroArch")


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
    "Dolphin": "iso|gcm|wbfs|rvz",
    "Demul": "chd|cdi|gdi|cue",
    "PCLauncher": "exe|lnk|url|bat",
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
            f"Emulator_Path={emu_dir}",
            f"Emulator_Application_Path={emu_dir / exe}",
            f"Emulator_Extension={ext}",
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


def generate_rl_system_ini(
    system_name: str,
    config: Config,
    output_base: Optional[Path] = None,
) -> list[Path]:
    """Write RocketLauncher per-system settings INI file(s).

    Detects which layout the system already uses and writes accordingly:

    - **folder layout** (``Settings/<system>/Emulators.ini`` exists) →
      updates that file using the ``[ROMS]`` section convention.
    - **flat layout** (``Settings/<system>.ini`` exists) →
      updates that file using the ``[Settings]`` section convention.
    - **new system** (neither file exists) → writes *both* files so the
      cabinet works regardless of which layout RocketLauncher uses.

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

    rom_path = str(Path(config.roms_dir) / system_name)
    emulator = guess_emulator(system_name)
    extensions = "|".join(ext.lstrip(".") for ext in get_rom_extensions(system_name))
    layout = detect_rl_layout(settings_dir, system_name)
    written: list[Path] = []

    if layout in ("folder", "new"):
        # Folder layout: Settings/<system>/Emulators.ini  [ROMS] section
        folder_dir = settings_dir / system_name
        folder_dir.mkdir(parents=True, exist_ok=True)
        emu_ini = folder_dir / "Emulators.ini"
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
        # Flat layout: Settings/<system>.ini  [Settings] section
        flat_ini = settings_dir / f"{system_name}.ini"
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
       ``Default_Emulator`` and ``Rom_Extension`` from the ``[ROMS]`` section.

    **Rom_Extension must appear in every section RL may consult:**

    When RL finds a ``[PCLauncher]`` section (in either file layout) it reads
    ``Rom_Extension`` from *that* section first.  If the key is absent RL falls
    back to the global extension list (``zip|rar|7z|lha|…``) and ignores the
    value set in ``[Settings]`` or ``[ROMS]``, producing::

        Cannot find Rom 1942 in any Rom_Paths provided:
            "…\\Modules\\PCLauncher\\Favorites"
        with any provided Rom_Extension: "zip|rar|7z|lha|lzh|gzip|tar|"

    Therefore:

    * The **flat-layout** ``Settings/<system>.ini`` carries ``Rom_Extension=ini``
      in *both* ``[Settings]`` and ``[PCLauncher]``.
    * The **folder-layout** ``Settings/<system>/Emulators.ini`` has **no**
      ``[PCLauncher]`` section at all.  Without that section RL reads
      ``Rom_Extension`` from ``[ROMS]`` and correctly finds ``ini``.  A
      ``[PCLauncher]`` block in the folder-layout file would be filled in
      by RL's own ``IniWrite`` on first launch, adding blank ``Rom_Extension=``
      which then overrides the ``[ROMS]`` value.
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
        # [PCLauncher] must also carry Rom_Extension=ini.  When RL finds a
        # [PCLauncher] section it reads Rom_Extension from there first; if
        # the key is absent RL falls back to the global extensions list
        # (zip|rar|7z|...) and ignores the [Settings] value — producing
        # "Cannot find Rom X with any provided Rom_Extension: zip|rar|7z|..."
        "[PCLauncher]",
        f"Rom_Path={pclauncher_dir}",
        "Rom_Extension=ini",
        "",
    ]
    ini_path.write_text("\n".join(flat_lines), encoding="utf-8")

    # ── 2. Folder layout: Settings/<system>/Emulators.ini ────────────────────
    # [ROMS] section ONLY — no [PCLauncher] block.  See docstring for why.
    system_folder = settings_dir / system_name
    system_folder.mkdir(parents=True, exist_ok=True)
    emulators_ini = system_folder / "Emulators.ini"
    emulator_lines = [
        "[ROMS]",
        "Default_Emulator=PCLauncher",
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
}

# System background image — displayed behind the game list while browsing.
# HyperSpin path: Media\<SystemName>\Images\Backgrounds\<SystemName>.png
_BACKGROUND_ASSETS: dict[str, str] = {
    "Favorites":       "bg_Favorites.png",
    "Most Played":     "bg_Most_Played.png",
    "Recently Played": "bg_Recently_Played.png",
}

# Background music — plays while the user browses the wheel.
# HyperSpin path: Media\Main Menu\Sound\<SystemName>.mp3
_MUSIC_ASSETS: dict[str, str] = {
    "Favorites":       "music_Favorites.mp3",
    "Most Played":     "music_Most_Played.mp3",
    "Recently Played": "music_Recently_Played.mp3",
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

        <hyperspin_dir>/Media/Main Menu/Sound/<system_name>.mp3

    HyperSpin reads system-level attract-mode audio from ``Media/Main Menu/Sound/``.
    This plays on the main menu while the wheel is highlighting this system,
    not inside the system's game list.

    When *overwrite* is ``False`` (default) the file is skipped if present.
    When *overwrite* is ``True`` (``mainmenu add``) it is always written.

    Returns ``(dest_path, status)`` where *status* ∈
    ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    src = _resolve_asset(_MUSIC_ASSETS, system_name)
    if src is None:
        return None, "no_asset"
    dest = hyperspin_dir / "Media" / "Main Menu" / "Sound" / f"{system_name}.mp3"
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


def install_bundled_system_assets(
    hyperspin_dir: Path,
    system_name: str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, tuple[Optional[Path], str]]:
    """Install all bundled media assets for *system_name* in one call.

    Runs :func:`install_system_wheel_art`, :func:`install_system_background`,
    :func:`install_system_music`, and :func:`install_system_video` and returns
    their results keyed by asset type so callers can report each outcome
    individually.

    *overwrite* is forwarded to each individual installer:

    * ``False`` (default) — skip files that already exist.  Used by
      ``rebuild --apply`` so user-placed media is preserved.
    * ``True`` — always write the bundled asset.  Used by
      ``mainmenu add --apply`` where the user explicitly requests a fresh
      install of every media file for the wheel.

    Return value::

        {
            "wheel_art":  (Path | None, status),
            "background": (Path | None, status),
            "music":      (Path | None, status),
            "video":      (Path | None, status),
        }

    Each *status* ∈ ``{"installed", "overwritten", "skipped", "no_asset", "dry_run"}``.
    """
    return {
        "wheel_art":  install_system_wheel_art( hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "background": install_system_background(hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "music":      install_system_music(     hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
        "video":      install_system_video(     hyperspin_dir, system_name, dry_run=dry_run, overwrite=overwrite),
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

    When the file doesn't exist yet the order of *systems* is used as-is.
    """
    target = _main_menu_path(config, output_base)
    systems_set = set(systems)

    existing = _read_main_menu_systems(target)
    ordered: list[str] = [s for s in existing if s in systems_set]
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

def _pclauncher_ini_text(executable) -> str:
    """Render the PCLauncher INI body that points at *executable*.

    *executable* may be any path-like (str, Path, PureWindowsPath).  We
    leave the path string verbatim so Windows-style paths produced from a
    macOS/Linux dev box (or vice-versa) round-trip without mangling.
    """
    return (
        "[Settings]\n"
        f"ApplicationPath={executable}\n"
        "ApplicationParameters=\n"
        f"StartIn={executable.parent}\n"
    )


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


def pclauncher_exe_info_text(
    applicationpath, parameters: str = "", rompath: str = "",
) -> str:
    """Render an ``[exe info]``-style PCLauncher INI body.

    PCLauncher accepts two INI dialects: the standard ``[Settings]`` form
    (see ``pclauncher_settings_text``) and ``[exe info]``, which requires
    ``fadetitle`` or a monitored exe. Kept for callers that explicitly
    need ``[exe info]`` semantics (e.g. direct emulator launch without
    RocketLauncher in the chain).
    """
    return (
        "[exe info]\n"
        f"applicationpath={applicationpath}\n"
        f"rompath={rompath}\n"
        f"parameters={parameters}\n"
    )


def _read_system_default_emulator(source_system: str, rocketlauncher_dir: Path) -> str:
    """Return the Default_Emulator name configured for *source_system* in RL's settings.

    Checks folder layout (``Settings/<system>/Emulators.ini`` → ``[ROMS]``) first,
    then flat layout (``Settings/<system>.ini`` → ``[Settings]``).
    Returns an empty string if neither file exists or the key is not set.
    """
    import configparser

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
    import configparser

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
    import configparser
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
) -> tuple[Path, list[Path], list[Path]]:
    """Write per-game PCLauncher INIs for *system_name*.

    Each INI lives at
    ``<RL>/Modules/PCLauncher/<system>/<title>.ini`` and tells the
    PCLauncher AHK module which executable to actually launch when
    HyperSpin asks RocketLauncher to run *<title>*.

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

    written: list[Path] = []
    skipped: list[Path] = []
    for title, exe_path in sorted(title_to_path.items()):
        ini_path = module_dir / f"{title}.ini"
        if ini_path.exists() and not overwrite:
            skipped.append(ini_path)
            continue
        ini_path.write_text(_pclauncher_ini_text(exe_path), encoding="utf-8")
        written.append(ini_path)
    return module_dir, written, skipped


