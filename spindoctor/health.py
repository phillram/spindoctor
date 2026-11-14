"""Health-check / `spindoctor doctor` logic.

A self-contained module that inspects the local install — paths, configured
binaries, API credentials, XML DBs, match cache, RocketLauncher INIs,
LEDBlinky files — and reports each check as ✓ / ⚠ / ✗.

The companion ``--fix`` flag performs only safe, idempotent repairs:
prunes stale match-cache entries, creates missing media folder skeletons,
and regenerates a missing ``Global Emulators.ini``.
"""
from __future__ import annotations

import json
import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import Config, get_systems
from .database import find_database, load_database
# The RocketLauncher Rom_Path lookup behind check_rom_paths, shared with `audit`.
from .rl_rom_paths import _RomLookup, _RomSource, _raw_game_names, _wheel_games
from .rocketlauncher import _read_rl_ini, _read_windows_text


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"


# Severity ordering: OK and INFO are both "fine"; WARN then FAIL escalate.
_STATUS_ORDER = {Status.OK: 0, Status.INFO: 0, Status.WARN: 1, Status.FAIL: 2}


def _worst(statuses) -> Status:
    """Return the most severe status in *statuses* (OK/INFO < WARN < FAIL)."""
    return max(statuses, key=lambda s: _STATUS_ORDER[s], default=Status.OK)


def _resolve_emu_path(emu_path: str, rl_dir: Path) -> list[Path]:
    """Resolve a Global Emulators.ini ``Emu_Path`` to local candidate paths for
    an existence check.

    Returns an **empty list** when the path can't be meaningfully checked on this
    OS (an absolute Windows drive path while running on POSIX, e.g. from a dev
    machine) — callers treat "no candidates" as "don't warn". A relative path
    (``..\\Emulators\\X``) is resolved against both the RocketLauncher ``Settings``
    dir (RL's own base for relative paths) and the RL root, and the caller warns
    only if *none* of the candidates exist — keeping false positives off cabinets
    whose emulators live on another drive.
    """
    from pathlib import PureWindowsPath

    pw = PureWindowsPath(emu_path)
    if pw.drive or pw.is_absolute():
        return [Path(emu_path)] if os.name == "nt" else []
    rel = Path(*pw.parts) if pw.parts else None
    if rel is None:
        return []
    return [
        _windows_case(Path(os.path.normpath(rl_dir / "Settings" / rel))),
        _windows_case(Path(os.path.normpath(rl_dir / rel))),
    ]


def _windows_case(path: Path) -> Path:
    """*path* as Windows would find it, ignoring case.

    RocketLauncher's paths are Windows paths, where ``Emulators\\daphne\\DAPHNE.EXE``
    is the same file as ``Emulators\\Daphne\\daphne.exe``.  On a case-sensitive
    file system each part that doesn't exist as spelled is swapped for the
    entry in its folder whose name matches ignoring case.  Unchanged on
    Windows, when the path exists as spelled, or when a part has no match.
    """
    if os.name == "nt" or path.exists():
        return path
    found = Path(path.parts[0])
    for part in path.parts[1:]:
        if not (found / part).exists():
            try:
                with os.scandir(found) as it:
                    matches = sorted(e.name for e in it if e.name.lower() == part.lower())
            except OSError:
                return path
            if not matches:
                return path
            part = matches[0]
        found = found / part
    return found


def _pc_app_exists(app_path: str) -> Optional[bool]:
    """Whether a PCLauncher ``Application=`` path exists on disk.

    Returns None when it can't be checked on this OS (an absolute Windows drive
    path while running on POSIX) so callers don't false-flag; True/False when the
    path is checkable (POSIX-style path, or any path on Windows).
    """
    if not app_path:
        return None
    from pathlib import PureWindowsPath

    if PureWindowsPath(app_path).drive:  # absolute Windows path (D:\...)
        return Path(app_path).exists() if os.name == "nt" else None
    return Path(app_path).exists()


@dataclass
class Check:
    name: str
    status: Status
    detail: str = ""
    fix: Optional[str] = None
    children: list["Check"] = field(default_factory=list)


@dataclass
class HealthReport:
    checks: list[Check] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    def overall(self) -> Status:
        worst = Status.OK
        order = {Status.OK: 0, Status.INFO: 0, Status.WARN: 1, Status.FAIL: 2}

        def visit(c: Check):
            nonlocal worst
            if order[c.status] > order[worst]:
                worst = c.status
            for ch in c.children:
                visit(ch)

        for c in self.checks:
            visit(c)
        return worst


# ─── individual checks ────────────────────────────────────────────────────────


def _check_path(name: str, path_str: str, *, optional: bool = False) -> Check:
    if not path_str:
        return Check(
            name=name,
            status=Status.WARN if optional else Status.FAIL,
            detail="not set" if optional else "not set (required)",
            fix=f"spindoctor config set {name} <path>",
        )
    p = Path(path_str)
    if not p.exists():
        return Check(
            name=name, status=Status.FAIL,
            detail=f"does not exist: {p}",
        )
    if not p.is_dir():
        return Check(
            name=name, status=Status.WARN,
            detail=f"not a directory: {p}",
        )
    return Check(name=name, status=Status.OK, detail=str(p))


def check_paths(config: Config) -> Check:
    parent = Check(name="Paths", status=Status.OK)
    parent.children.append(_check_path("roms_dir", config.roms_dir))
    parent.children.append(_check_path("hyperspin_dir", config.hyperspin_dir))
    parent.children.append(
        _check_path("rocketlauncher_dir", config.rocketlauncher_dir, optional=True)
    )
    parent.children.append(
        _check_path("emulators_dir", config.emulators_dir, optional=True)
    )
    parent.children.append(
        _check_path("ledblinky_dir", config.ledblinky_dir, optional=True)
    )
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_binaries(config: Config) -> Check:
    parent = Check(name="External binaries", status=Status.OK)

    if config.mame_executable:
        p = Path(config.mame_executable)
        if not p.exists():
            parent.children.append(Check(
                name="mame_executable", status=Status.FAIL,
                detail=f"does not exist: {p}",
            ))
        else:
            parent.children.append(Check(
                name="mame_executable", status=Status.OK, detail=str(p),
            ))
    else:
        parent.children.append(Check(
            name="mame_executable", status=Status.WARN, detail="not configured",
            fix="spindoctor config set mame_executable /path/to/mame",
        ))

    if shutil.which("ffprobe"):
        parent.children.append(Check(
            name="ffprobe", status=Status.OK,
            detail="available (used for video duration)",
        ))
    else:
        parent.children.append(Check(
            name="ffprobe", status=Status.INFO,
            detail="not installed (native fallback used; install ffmpeg for accuracy)",
        ))

    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_lxml() -> Check:
    try:
        import lxml  # noqa: F401
        return Check(
            name="lxml", status=Status.OK,
            detail="installed (XML round-trip preserves comments)",
        )
    except ImportError:
        return Check(
            name="lxml", status=Status.WARN,
            detail="not installed; XML comments will be lost on save",
            fix="pip install spindoctor[xml]",
        )


def check_archive_support() -> Check:
    """Surface which archive formats `verify` / `find-dupes` can read.

    .zip, .gz, and .chd are always available (stdlib + native parser).
    .7z and .rar are soft deps — install via ``pip install -e .[archives]``.
    """
    from . import archives

    status = archives.support_status()
    children: list[Check] = []
    missing: list[str] = []
    for kind in ("zip", "7z", "rar", "gz", "chd"):
        available, hint = status[kind]
        if available:
            detail = (
                "built-in" if kind in ("zip", "gz", "chd")
                else "installed"
            )
            children.append(Check(
                name=f".{kind}", status=Status.OK, detail=detail,
            ))
        else:
            missing.append(f".{kind}")
            children.append(Check(
                name=f".{kind}", status=Status.WARN,
                detail="not installed",
                fix=hint,
            ))
    parent = Check(name="Archive support", status=Status.OK, children=children)
    if missing:
        parent.status = Status.WARN
        parent.detail = (
            f"{', '.join(missing)} unavailable — "
            "install with `pip install -e .[archives]`"
        )
        parent.fix = "pip install -e .[archives]"
    else:
        parent.detail = "zip, 7z, rar, gz, chd"
    return parent


def check_preview_support() -> Check:
    """Surface whether Pillow is available for `spindoctor preview --format png`.

    Pillow is a soft dep — without it the HTML preview modes still work,
    but the PNG contact sheet falls back to HTML with a warning.
    """
    from . import preview as _preview

    if _preview.pillow_available():
        return Check(
            name="Preview support", status=Status.OK,
            detail="PIL installed (PNG contact sheets enabled)",
        )
    return Check(
        name="Preview support", status=Status.WARN,
        detail="PIL not installed; only HTML preview available",
        fix="pip install -e .[preview]",
    )


def check_databases(config: Config) -> Check:
    parent = Check(name="HyperSpin databases", status=Status.OK)
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        parent.status = Status.INFO
        parent.detail = "hyperspin_dir not configured; skipping"
        return parent

    systems = get_systems(config)
    if not systems:
        parent.status = Status.WARN
        parent.detail = "no systems detected"
        return parent

    bad = 0
    for sys_name in systems:
        xml_path = find_database(sys_name, config.databases_dir)
        if xml_path is None:
            parent.children.append(Check(
                name=sys_name, status=Status.WARN,
                detail="no DB XML found",
            ))
            continue
        try:
            db = load_database(sys_name, config.databases_dir)
            n = len(db.games())
        except Exception as e:  # noqa: BLE001
            # doctor must never crash on one bad/locked/mis-encoded file —
            # load_database only wraps parse errors as ValueError, but a live
            # cabinet can hand us PermissionError / UnicodeDecodeError too.
            bad += 1
            parent.children.append(Check(
                name=sys_name, status=Status.FAIL,
                detail=f"unreadable: {type(e).__name__}: {e}",
            ))
            continue
        if n == 0:
            parent.children.append(Check(
                name=sys_name, status=Status.WARN,
                detail=f"0 entries (empty database) · {xml_path.name}",
            ))
        else:
            parent.children.append(Check(
                name=sys_name, status=Status.OK,
                detail=f"{n} entries · {xml_path.name}",
            ))

    parent.status = Status.FAIL if bad else (
        Status.WARN if any(c.status == Status.WARN for c in parent.children) else Status.OK
    )
    return parent


def check_match_cache(config: Config, fix: bool, fixes_applied: list[str]) -> Check:
    """Find match-cache entries pointing to ROMs that no longer exist."""
    from .matcher import CACHE_DIR as MATCH_CACHE_DIR
    cache_dir = MATCH_CACHE_DIR
    if not cache_dir.exists():
        return Check(name="Match cache", status=Status.OK, detail="no cache yet")
    if not config.roms_dir:
        # Without roms_dir every entry would look "stale" (rom_dir can't exist),
        # so an unguarded --fix would wipe the whole cache. Skip instead.
        return Check(
            name="Match cache", status=Status.INFO,
            detail="roms_dir not configured; skipping",
        )

    stale_total = 0
    files_touched = 0
    corrupt: list[str] = []
    for cache_file in cache_dir.glob("*.json"):
        system = cache_file.stem
        rom_dir = Path(config.roms_dir) / system
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            corrupt.append(f"{cache_file.name}: {exc}")
            continue
        if not isinstance(data, dict):
            continue
        # Case-insensitive: the cabinet's filesystem (NTFS) is case-insensitive,
        # so a ROM re-cased by a tagger must not read as a deleted (stale) entry.
        existing_roms = {p.stem.lower() for p in rom_dir.rglob("*") if p.is_file()} if rom_dir.exists() else set()
        stale = [name for name in data if name.lower() not in existing_roms]
        if stale:
            stale_total += len(stale)
            files_touched += 1
            if fix:
                for name in stale:
                    data.pop(name, None)
                cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                fixes_applied.append(
                    f"pruned {len(stale)} stale entries from match_cache/{system}.json"
                )

    if corrupt:
        detail = f"{len(corrupt)} corrupt cache file(s): " + "; ".join(corrupt[:3])
        if len(corrupt) > 3:
            detail += f" (and {len(corrupt) - 3} more)"
        return Check(
            name="Match cache", status=Status.WARN,
            detail=detail,
            fix="Delete the corrupt files from ~/.spindoctor/match_cache/ and re-run.",
        )
    if stale_total == 0:
        return Check(name="Match cache", status=Status.OK, detail="no stale entries")
    if fix:
        return Check(
            name="Match cache", status=Status.OK,
            detail=f"pruned {stale_total} stale entries across {files_touched} files",
        )
    return Check(
        name="Match cache", status=Status.WARN,
        detail=f"{stale_total} stale entries across {files_touched} system(s)",
        fix="spindoctor doctor --fix",
    )


def check_global_emulators(
    config: Config, fix: bool, fixes_applied: list[str],
) -> Check:
    if not config.rocketlauncher_dir:
        return Check(
            name="Global Emulators.ini", status=Status.INFO,
            detail="rocketlauncher_dir not configured; skipping",
        )
    target = Path(config.rocketlauncher_dir) / "Settings" / "Global Emulators.ini"
    if target.exists():
        return Check(
            name="Global Emulators.ini", status=Status.OK, detail=str(target),
        )
    if fix:
        from .rocketlauncher import generate_global_emulators_ini
        try:
            p, _ = generate_global_emulators_ini(config, overwrite=False)
            fixes_applied.append(f"created {p}")
            return Check(
                name="Global Emulators.ini", status=Status.OK,
                detail=f"created: {p}",
            )
        except ValueError as e:
            return Check(
                name="Global Emulators.ini", status=Status.WARN, detail=str(e),
                fix="Configure at least one system's emulator/rom paths, then "
                    "re-run: spindoctor generate-config --global-emulators --apply",
            )
    return Check(
        name="Global Emulators.ini", status=Status.WARN,
        detail=f"missing: {target}",
        fix="spindoctor generate-config --global-emulators  (or doctor --fix)",
    )


def check_rocketlauncher_settings(config: Config) -> Check:
    """RocketLauncher's own settings that stop launches or slow every one down.

    Reads ``Settings/RocketLauncher.ini`` the way RocketLauncher does
    (case-insensitive sections and keys, relative paths resolved against the
    RocketLauncher folder):

    * **Virtual drive** — ``Virtual_Drive_Path`` must exist when any system
      mounts disc images through it.  ``Virtual_Drive_Enabled`` comes from
      ``Global RocketLauncher.ini``, overridden per system by
      ``Settings/<System>/RocketLauncher.ini`` (``use_global`` defers).  The
      usual break is DAEMON Tools Lite reinstalled into the *other* Program
      Files folder, so the fix names that path when the program is there.
    * **7-Zip** — RocketLauncher checks ``7z_Path`` at the start of every
      launch, whether or not 7z is enabled, so a stale path stops them all.
    * **Logging** — ``Logging_Level`` 4 (debug) and up slows every launch.

    Diagnosis only: these are the user's RocketLauncher settings, so each
    finding names the file and key to edit.
    """
    name = "RocketLauncher settings"
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")
    rl_dir = Path(config.rocketlauncher_dir)
    settings_dir = rl_dir / "Settings"

    # One listing of Settings/: top-level INIs by lower-cased name, plus the
    # per-system folders (each may hold its own RocketLauncher.ini).
    inis: dict[str, Path] = {}
    system_dirs: list[Path] = []
    try:
        with os.scandir(settings_dir) as it:
            for entry in it:
                if entry.is_dir():
                    system_dirs.append(Path(entry.path))
                elif entry.is_file():
                    inis[entry.name.lower()] = Path(entry.path)
    except OSError:
        pass
    rl_ini = inis.get("rocketlauncher.ini")
    if rl_ini is None:
        return Check(name=name, status=Status.INFO,
                     detail=f"no RocketLauncher.ini in {settings_dir}; skipping")

    # Main Menu wheels with no Settings/<System>/ folder have no per-system
    # value, so they follow the global Virtual_Drive_Enabled.
    folderless: list[str] = []
    if config.hyperspin_dir:
        from .rocketlauncher import SKIP_GENERATE_CONFIG

        have = {d.name.lower() for d in system_dirs}
        mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
        folderless = [
            w for w in _main_menu_wheels(mm_path)
            if w not in SKIP_GENERATE_CONFIG and w.lower() not in have
        ]

    settings = _read_rl_settings_ini(rl_ini)
    parent = Check(name=name, status=Status.OK, detail=str(rl_ini))
    parent.children.append(_check_rl_virtual_drive(
        settings, _read_rl_settings_ini(inis.get("global rocketlauncher.ini")),
        system_dirs, folderless, rl_ini, rl_dir,
    ))
    parent.children.append(_check_rl_7z_path(settings, rl_ini, rl_dir))
    parent.children.append(_check_rl_logging(settings, rl_ini))
    parent.status = _worst(c.status for c in parent.children)
    return parent


def _check_rl_virtual_drive(
    settings: dict[str, dict[str, str]],
    global_settings: dict[str, dict[str, str]],
    system_dirs: list[Path],
    folderless: list[str],
    rl_ini: Path,
    rl_dir: Path,
) -> Check:
    name = "Virtual drive"
    raw = settings.get("virtual drive", {}).get("virtual_drive_path", "")
    exists = _rl_path_exists(raw, rl_dir) if raw else None
    if exists:
        return Check(name=name, status=Status.OK, detail=raw)
    if raw and exists is None:
        return Check(name=name, status=Status.INFO,
                     detail=f"can't check a Windows path from this OS: {raw}")

    # Empty or missing: that only matters if some system mounts through it.
    # RocketLauncher's default for a missing global switch is "false".  A
    # system's own value wins unless it is "use_global" (or absent); any other
    # value, blank included, means off for that system.
    global_on = global_settings.get("virtual drive", {}).get(
        "virtual_drive_enabled", "").lower() == "true"
    switched_on: list[str] = []
    inheriting: list[str] = []
    for d in system_dirs:
        value = _read_rl_settings_ini(d / "RocketLauncher.ini").get("virtual drive", {}).get(
            "virtual_drive_enabled", "use_global").lower()
        if value == "true":
            switched_on.append(d.name)
        elif value == "use_global" and global_on:
            inheriting.append(d.name)
    if global_on:
        inheriting.extend(folderless)
    # Systems switched on explicitly come first: they're usually the disc systems.
    users = sorted(switched_on, key=str.lower) + sorted(inheriting, key=str.lower)
    in_use = bool(users) or (global_on and not system_dirs)

    if not in_use:
        if exists is False:
            # Nothing mounts through it, so a stale path breaks nothing.
            return Check(
                name=name, status=Status.INFO,
                detail=f"Virtual_Drive_Path not found: {raw} (no system uses the virtual drive)",
                fix=_rl_twin_path_fix(raw, rl_dir, "Virtual_Drive_Path", "Virtual Drive", rl_ini),
            )
        return Check(name=name, status=Status.OK, detail="not used by any system")

    shown = ", ".join(users[:5]) + (f" and {len(users) - 5} more" if len(users) > 5 else "")
    if global_on:
        who = f"enabled globally ({len(users)} system(s): {shown})" if users else "enabled globally"
    else:
        who = f"enabled for {shown}"
    if not raw:
        return Check(
            name=name, status=Status.WARN,
            detail=f"Virtual_Drive_Path is empty but the virtual drive is {who}",
            fix=(f"Set Virtual_Drive_Path under [Virtual Drive] in {rl_ini}, "
                 "or turn Virtual_Drive_Enabled off"),
        )
    return Check(
        name=name, status=Status.WARN,
        detail=f"Virtual_Drive_Path not found: {raw} — {who}",
        fix=_rl_twin_path_fix(raw, rl_dir, "Virtual_Drive_Path", "Virtual Drive", rl_ini)
        or (f"Point Virtual_Drive_Path under [Virtual Drive] in {rl_ini} at your virtual-drive "
            "program (e.g. DTLite.exe), or turn Virtual_Drive_Enabled off for those systems"),
    )


def _check_rl_7z_path(
    settings: dict[str, dict[str, str]], rl_ini: Path, rl_dir: Path,
) -> Check:
    name = "7-Zip"
    # A blank or missing key falls back to RocketLauncher's bundled copy.
    raw = settings.get("7z", {}).get("7z_path", "") or r".\Module Extensions\7z.exe"
    exists = _rl_path_exists(raw, rl_dir)
    if exists is None:
        return Check(name=name, status=Status.INFO,
                     detail=f"can't check a Windows path from this OS: {raw}")
    if exists:
        return Check(name=name, status=Status.OK, detail=raw)
    return Check(
        name=name, status=Status.WARN,
        detail=f"7z_Path not found: {raw} — RocketLauncher stops every launch at this check",
        fix=_rl_twin_path_fix(raw, rl_dir, "7z_Path", "7z", rl_ini)
        or (f"Point 7z_Path under [7z] in {rl_ini} at 7z.exe "
            "(RocketLauncher ships one in its Module Extensions folder)"),
    )


def _check_rl_logging(settings: dict[str, dict[str, str]], rl_ini: Path) -> Check:
    name = "Logging"
    raw = settings.get("logging", {}).get("logging_level", "")
    if not raw:
        return Check(name=name, status=Status.OK,
                     detail="Logging_Level not set (RocketLauncher uses 3)")
    try:
        level = int(raw)
    except ValueError:
        return Check(name=name, status=Status.INFO,
                     detail=f"Logging_Level is not a number: {raw}")
    if level >= 4:
        return Check(
            name=name, status=Status.INFO,
            detail=(f"Logging_Level={level} (debug or higher) slows every launch; "
                    "2-3 still logs warnings and errors"),
            fix=f"Set Logging_Level=3 under [Logging] in {rl_ini} once you're done troubleshooting",
        )
    return Check(name=name, status=Status.OK, detail=f"Logging_Level={level}")


def _read_rl_settings_ini(path: Optional[Path]) -> dict[str, dict[str, str]]:
    """``{section: {key: value}}`` from a RocketLauncher INI, names lower-cased.

    Same parsing as :func:`_read_rl_ini`; *path* may be None (no such file).
    """
    return _read_rl_ini(path) if path is not None else {}


def _rl_path_exists(value: str, rl_dir: Path) -> Optional[bool]:
    """Whether a path from a RocketLauncher INI exists on disk.

    Relative paths (``.\\Module Extensions\\7z.exe``) resolve against the
    RocketLauncher folder, as RocketLauncher resolves them.  Returns None when
    the path can't be checked here: an absolute Windows path on POSIX.
    """
    from pathlib import PureWindowsPath

    pw = PureWindowsPath(value)
    if pw.drive:
        return Path(value).exists() if os.name == "nt" else None
    if os.path.isabs(value):
        return Path(value).exists()
    return Path(os.path.normpath(os.path.join(str(rl_dir), *pw.parts))).exists()


def _rl_twin_path_fix(
    raw: str, rl_dir: Path, key: str, section: str, rl_ini: Path,
) -> Optional[str]:
    """Fix hint when a missing program is in the other Program Files folder.

    A program reinstalled as 64-bit (or as 32-bit) lands in ``Program Files``
    instead of ``Program Files (x86)`` (or the reverse), while RocketLauncher
    still points at the old one.  Returns the exact edit when the file exists
    there, else None.
    """
    import re

    x86 = re.compile(r"(^|[\\/])Program Files \(x86\)(?=[\\/]|$)", re.IGNORECASE)
    native = re.compile(r"(^|[\\/])Program Files(?=[\\/]|$)", re.IGNORECASE)
    if x86.search(raw):
        twin = x86.sub(lambda m: m.group(1) + "Program Files", raw, count=1)
    elif native.search(raw):
        twin = native.sub(lambda m: m.group(1) + "Program Files (x86)", raw, count=1)
    else:
        return None
    if not _rl_path_exists(twin, rl_dir):
        return None
    return f"Set {key}={twin} under [{section}] in {rl_ini} (found in the other Program Files folder)"


def check_ledblinky(config: Config) -> Check:
    if not config.ledblinky_dir:
        return Check(
            name="LEDBlinky", status=Status.INFO,
            detail="ledblinky_dir not configured",
        )
    base = Path(config.ledblinky_dir)
    parent = Check(name="LEDBlinky", status=Status.OK)
    from .ledblinky import (
        COLOR_RGB_NAME,
        COLORS_INI_NAME,
        CONTROLS_INI_NAME,
        SEARCH_MENU_NAMES,
        parse_ini_sections,
        scan,
    )
    for fname in (CONTROLS_INI_NAME, COLORS_INI_NAME):
        p = base / fname
        if not p.exists():
            parent.children.append(Check(
                name=fname, status=Status.WARN,
                detail=f"missing: {p}",
            ))
        else:
            try:
                n = len(parse_ini_sections(p))
                parent.children.append(Check(
                    name=fname, status=Status.OK,
                    detail=f"{n} sections",
                ))
            except Exception as e:  # noqa: BLE001
                parent.children.append(Check(
                    name=fname, status=Status.WARN,
                    detail=f"{type(e).__name__}: {e}",
                ))

    # Color-RGB.ini — without it `ledblinky generate` silently degrades to the
    # legacy hex color format, which real LedBlinky can't read.
    rgb = base / COLOR_RGB_NAME
    if rgb.exists():
        parent.children.append(Check(
            name=COLOR_RGB_NAME, status=Status.OK, detail=str(rgb),
        ))
    else:
        parent.children.append(Check(
            name=COLOR_RGB_NAME, status=Status.WARN,
            detail="missing — `ledblinky generate` falls back to legacy hex colors LedBlinky can't read",
            fix="Add a named palette with: spindoctor ledblinky colors add ...",
        ))

    # Search/Genre/Favorites crash scan — a LedBlinky process hook in a menu's
    # Settings.ini (or a missing LEDBlinkyControls.xml entry) is the documented
    # cause of HyperSpin crashing when you open those menus.
    try:
        scan_res = scan(config, menus=SEARCH_MENU_NAMES)
    except Exception:  # noqa: BLE001 — a scan failure must not sink doctor
        scan_res = None
    if scan_res is not None:
        risky = [
            mi["menu"] for mi in scan_res["menu_inis"]
            if mi["has_hooks"]
            or (scan_res["controls_xml_exists"] and not mi["has_controls_entry"])
        ]
        if risky:
            parent.children.append(Check(
                name="Search/Genre/Favorites", status=Status.WARN,
                detail=f"crash risk on: {', '.join(risky)} (LedBlinky hook or missing controls entry)",
                fix="spindoctor ledblinky fix --apply",
            ))
        else:
            parent.children.append(Check(
                name="Search/Genre/Favorites", status=Status.OK,
                detail="no LedBlinky menu-crash conflicts",
            ))

    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_api_creds(config: Config) -> Check:
    parent = Check(name="Metadata APIs", status=Status.OK)
    if config.screenscraper_user and config.screenscraper_pass:
        parent.children.append(Check(
            name="ScreenScraper", status=Status.OK,
            detail=f"user: {config.screenscraper_user}",
        ))
    else:
        parent.children.append(Check(
            name="ScreenScraper", status=Status.INFO,
            detail="credentials not set",
        ))
    if config.thegamesdb_key:
        parent.children.append(Check(
            name="TheGamesDB", status=Status.OK,
            detail="API key configured",
        ))
    else:
        parent.children.append(Check(
            name="TheGamesDB", status=Status.INFO,
            detail="API key not set",
        ))
    return parent


def check_media_skeletons(
    config: Config, fix: bool, fixes_applied: list[str],
) -> Check:
    """For each known system, ensure Media/<System>/Images/ subdirs exist.

    Missing subdirs are not an error per se — but creating them lets RocketUI
    or external taggers drop files in without 'directory not found' errors.
    """
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(
            name="Media folders", status=Status.INFO,
            detail="hyperspin_dir missing; skipping",
        )
    needed = (
        ("Images", "Wheel"), ("Images", "Backgrounds"),
        ("Images", "Artwork1"), ("Images", "Artwork2"),
        ("Images", "Artwork3"), ("Video",), ("Video", "Trailers"),
        ("Sound",), ("Themes",),
    )
    systems = get_systems(config)
    missing = 0
    for sys_name in systems:
        for parts in needed:
            d = config.media_dir / sys_name / Path(*parts)
            if not d.exists():
                missing += 1
                if fix:
                    d.mkdir(parents=True, exist_ok=True)
    if missing == 0:
        return Check(
            name="Media folders", status=Status.OK,
            detail="skeleton complete",
        )
    if fix:
        fixes_applied.append(f"created {missing} media subfolder(s)")
        return Check(
            name="Media folders", status=Status.OK,
            detail=f"created {missing} skeleton folders",
        )
    return Check(
        name="Media folders", status=Status.INFO,
        detail=f"{missing} subfolders not created (cosmetic)",
        fix="spindoctor doctor --fix",
    )


def _main_menu_wheels(mm_path: Path) -> list[str]:
    """Real wheel names from Main Menu.xml.

    Excludes HyperSpin built-in entries carrying ``exe="true"`` (e.g. the
    ``Search`` entry), which are not selectable console/system wheels and have
    no Settings INI / database of their own.
    """
    if not mm_path.exists():
        return []
    try:
        tree = ET.parse(mm_path)
    except ET.ParseError:
        return []
    wheels: list[str] = []
    for g in tree.getroot().findall("game"):
        name = (g.get("name") or "").strip()
        if not name:
            continue
        if (g.get("exe") or "").strip().lower() == "true":
            continue  # built-in (Search) — not a wheel
        wheels.append(name)
    return wheels


def check_wheel_wiring(
    config: Config, fix: bool, fixes_applied: list[str],
) -> Check:
    """Per-wheel launch/open wiring for every system on the Main Menu.

    The install-wide checks (databases, Global Emulators.ini, media skeleton)
    can all pass while an individual wheel is still broken.  This walks
    ``Main Menu.xml`` and, for each wheel, verifies the pieces HyperSpin and
    RocketLauncher actually need at selection/launch time:

    * **HyperSpin ``Settings/<System>.ini``** — required to *open* the wheel;
      without it HyperSpin reports "Cannot find <System>.ini".  ``--fix`` writes
      the minimal INI (idempotent).
    * **``Media/<System>/Themes/default.zip``** — HyperSpin's per-console
      fallback theme; without it games with no theme of their own render blank.
      ``--fix`` installs the bundled blank theme.
    * **RocketLauncher emulator mapping** — a wheel with no ``Default_Emulator``
      (or one that resolves to no known executable) can't launch its games.
      Diagnosis only — SpinDoctor can't guess an uninstalled emulator.
    * **Database presence** — a Main-Menu wheel with no DB XML is an empty
      orphan.
    """
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(
            name="Wheel wiring", status=Status.INFO,
            detail="hyperspin_dir not configured; skipping",
        )

    from .rocketlauncher import (
        SKIP_GENERATE_CONFIG,
        _read_emulator_emu_path,
        _read_emulator_exe,
        _read_system_default_emulator,
        fill_default_theme,
        write_hyperspin_system_ini,
    )

    hs_dir = Path(config.hyperspin_dir)
    rl_dir = Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None
    mm_path = hs_dir / "Databases" / "Main Menu" / "Main Menu.xml"

    parent = Check(name="Wheel wiring", status=Status.OK)
    if not mm_path.exists():
        parent.status = Status.INFO
        parent.detail = f"no Main Menu.xml at {mm_path}; skipping"
        return parent
    wheels = _main_menu_wheels(mm_path)
    if not wheels:
        parent.status = Status.INFO
        parent.detail = "Main Menu.xml has no wheels"
        return parent

    for system in wheels:
        node = Check(name=system, status=Status.OK)

        # 1. HyperSpin Settings/<System>.ini — required to OPEN the wheel.
        ini_path = hs_dir / "Settings" / f"{system}.ini"
        if ini_path.exists():
            node.children.append(Check(
                name="HyperSpin settings INI", status=Status.OK, detail=str(ini_path),
            ))
        elif fix and write_hyperspin_system_ini(system, hs_dir) is not None:
            fixes_applied.append(f"wrote HyperSpin Settings/{system}.ini")
            node.children.append(Check(
                name="HyperSpin settings INI", status=Status.OK,
                detail=f"created: {ini_path}",
            ))
        else:
            node.children.append(Check(
                name="HyperSpin settings INI", status=Status.WARN,
                detail=f'missing — HyperSpin will report "Cannot find {system}.ini" on select',
                fix=f'spindoctor mainmenu add "{system}" --apply  (or doctor --fix)',
            ))

        # 2. Default console theme (Media/<System>/Themes/default.zip).
        theme_path = hs_dir / "Media" / system / "Themes" / "default.zip"
        if theme_path.exists():
            node.children.append(Check(
                name="Default theme", status=Status.OK, detail=str(theme_path),
            ))
        elif fix:
            status = fill_default_theme(hs_dir, system)
            if status == "installed":
                fixes_applied.append(f"installed default theme for {system}")
                node.children.append(Check(
                    name="Default theme", status=Status.OK, detail=f"created: {theme_path}",
                ))
            else:  # "no_asset" — bundled zip missing (should never happen in a real install)
                node.children.append(Check(
                    name="Default theme", status=Status.INFO,
                    detail="bundled theme_blank.zip missing from package",
                ))
        else:
            node.children.append(Check(
                name="Default theme", status=Status.INFO,
                detail="no default.zip (untheme'd games show a blank screen)",
                fix=f'spindoctor theme-fill --system "{system}" --default --apply  (or doctor --fix)',
            ))

        # 3. RocketLauncher emulator mapping — skip synthetic/PCLauncher wheels.
        if system in SKIP_GENERATE_CONFIG:
            node.children.append(Check(
                name="Emulator", status=Status.OK, detail="synthetic/PCLauncher wheel",
            ))
        elif rl_dir is None:
            node.children.append(Check(
                name="Emulator", status=Status.INFO,
                detail="rocketlauncher_dir not configured; skipping",
            ))
        else:
            emu = _read_system_default_emulator(system, rl_dir)
            if not emu:
                node.children.append(Check(
                    name="Emulator", status=Status.WARN,
                    detail="no Default_Emulator configured — games won't launch",
                    fix=(f'spindoctor config system set "{system}" --emulator <NAME> '
                         f'--rom-path <PATH>  then  spindoctor generate-config --apply'),
                ))
            elif emu == "PCLauncher":
                node.children.append(Check(
                    name="Emulator", status=Status.OK, detail="PCLauncher",
                ))
            elif not _read_emulator_exe(emu, rl_dir):
                node.children.append(Check(
                    name="Emulator", status=Status.WARN,
                    detail=f'"{emu}" not found in Global Emulators.ini — games may not launch',
                    fix="Add the emulator to Settings/Global Emulators.ini with an Emu_Path=",
                ))
            else:
                # Emulator is registered — now confirm its binary exists on disk,
                # otherwise the wheel opens but nothing launches (stale Emu_Path
                # after an uninstall / drive-letter change).
                exe_name = _read_emulator_exe(emu, rl_dir)
                emu_path = _read_emulator_emu_path(emu, rl_dir)
                candidates = _resolve_emu_path(emu_path, rl_dir) if emu_path else []
                if candidates and not any(c.exists() for c in candidates):
                    node.children.append(Check(
                        name="Emulator", status=Status.WARN,
                        detail=f"{emu} exe not found on disk: {emu_path}",
                        fix="Fix Emu_Path in Settings/Global Emulators.ini, or reinstall the emulator",
                    ))
                else:
                    node.children.append(Check(
                        name="Emulator", status=Status.OK, detail=f"{emu} → {exe_name}",
                    ))

        # 4. Database presence — an orphan Main-Menu wheel with no DB is empty.
        if find_database(system, config.databases_dir) is None:
            node.children.append(Check(
                name="Database", status=Status.WARN,
                detail="no DB XML — wheel will be empty",
                fix=f'spindoctor add-system "{system}" --apply',
            ))

        node.status = _worst([c.status for c in node.children])
        parent.children.append(node)

    # Reverse orphans: systems fully set up under Databases/ but missing from the
    # Main Menu — invisible in HyperSpin even though all the work was done.
    from .mainmenu import discover_systems
    try:
        orphans = discover_systems(config)
    except Exception:  # noqa: BLE001
        orphans = []
    for system in orphans:
        parent.children.append(Check(
            name=system, status=Status.WARN,
            detail="set up in Databases/ but not on the Main Menu — invisible in HyperSpin",
            fix=f'spindoctor mainmenu add "{system}" --apply',
        ))

    parent.status = _worst([c.status for c in parent.children])
    return parent


def check_pc_launchability(config: Config) -> Check:
    """Verify per-game launch wiring for every PCLauncher system.

    ``check_wheel_wiring`` treats ``Default_Emulator=PCLauncher`` as automatically
    OK and never looks deeper.  This walks the per-game PCLauncher INIs — the
    layer that actually produces "Cannot find this Application" — and, per PC
    system, checks that every game in the database has an INI whose
    ``Application=`` path still exists on disk (the stale-drive-letter bug).

    Diagnosis only: the fixes (`add-pc-system` / `pc-rename`) rewrite RL config
    and per-game INIs, which is too broad to fold into a blanket ``doctor --fix``
    — each finding names the exact command instead.
    """
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name="PC games", status=Status.INFO,
                     detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name="PC games", status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")

    from .rocketlauncher import (
        SKIP_GENERATE_CONFIG,
        _read_system_default_emulator,
        _win_safe_stem,
        read_pclauncher_ini_application_path,
    )

    rl_dir = Path(config.rocketlauncher_dir)
    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    pc_systems = [
        w for w in _main_menu_wheels(mm_path)
        if w not in SKIP_GENERATE_CONFIG
        and _read_system_default_emulator(w, rl_dir) == "PCLauncher"
    ]
    if not pc_systems:
        return Check(name="PC games", status=Status.INFO, detail="no PCLauncher systems")

    parent = Check(name="PC games", status=Status.OK)
    for system in pc_systems:
        node = Check(name=system, status=Status.OK)
        try:
            games = list(load_database(system, config.databases_dir).games().keys())
        except Exception:  # noqa: BLE001 — DB integrity is check_databases' job
            games = []
        if not games:
            node.status = Status.INFO
            node.detail = "no games in database"
            parent.children.append(node)
            continue

        ini_dir = rl_dir / "Modules" / "PCLauncher" / system
        missing_ini: list[str] = []
        stale_app: list[str] = []
        for name in games:
            ini = ini_dir / f"{_win_safe_stem(name)}.ini"
            if not ini.exists():
                missing_ini.append(name)
                continue
            app = read_pclauncher_ini_application_path(ini, section_name=name)
            if _pc_app_exists(app) is False:
                stale_app.append(name)

        total = len(games)
        if missing_ini:
            node.children.append(Check(
                name="per-game INIs", status=Status.FAIL,
                detail=f"{len(missing_ini)}/{total} games have no PCLauncher INI (e.g. {missing_ini[0]})",
                fix=f'spindoctor add-pc-system "{system}" --apply',
            ))
        if stale_app:
            node.children.append(Check(
                name="Application paths", status=Status.FAIL,
                detail=f"{len(stale_app)}/{total} games' Application path is missing on disk (e.g. {stale_app[0]})",
                # Plain --apply only writes missing INIs; the stale ones are
                # rewritten only with --overwrite-pclauncher.
                fix=(f'spindoctor pc-rename "{system}" --overwrite-pclauncher --apply   '
                     "(rewrites every per-game INI, replacing hand edits)"),
            ))
        if not node.children:
            node.detail = f"{total} game(s) OK"
        node.status = _worst([c.status for c in node.children])
        parent.children.append(node)

    parent.status = _worst(c.status for c in parent.children)
    return parent


# The "games are in a subfolder" hint only looks at Rom_Path folders with at
# most this many subfolders (roms\, MultiDisc\, _Gun Games\ and the like).
_SUBFOLDER_HINT_MAX = 50


def _wheel_rom_paths(system: str, look: _RomLookup, databases_dir: Path) -> Check:
    """One wheel's node for :func:`check_rom_paths`."""
    node = Check(name=system, status=Status.OK)
    own = look.source(system)
    if own is None:
        node.status = Status.INFO
        node.detail = "no RocketLauncher settings for this system; skipping"
        return node
    games, raw = _wheel_games(system, databases_dir)
    if not games:
        node.status = Status.INFO
        node.detail = "no games in database"
        return node

    # Group the games by where RL looks for them.  Games.ini can send a game
    # to another emulator (its Rom_Extension) or, with System=, to another
    # system's settings: RL then reads that system's Emulators.ini and
    # RocketLauncher.ini instead (Rom_Path, Skipchecks, Rom_Match_Extension),
    # so those games are reported per borrowed system.
    overrides = look.game_overrides(system)
    own_games: list[tuple[_RomSource, str]] = []
    borrowed: dict[str, list[tuple[_RomSource, str]]] = {}
    for name in games:
        src, other = look.game_source(system, name, overrides)
        if other:
            if src is not None:  # else System= names a system with no settings
                borrowed.setdefault(other.lower(), []).append((src, name))
        else:
            own_games.append((src or own, name))
    considered = len(own_games) + sum(len(v) for v in borrowed.values())

    def found(src: _RomSource, name: str) -> bool:
        return look.found(src, [name, raw[name]] if name in raw else [name])

    checked = 0
    unlooked = 0  # PCLauncher games with no extension: RL doesn't look for a file
    game_rows: list[tuple[Check, int]] = []  # rows listing games RL can't find
    uncheckable = not own.checkable()

    # 1. The wheel's own Rom_Path.  Under Skipchecks=Rom Only / Rom and Emu RL
    #    neither looks for ROMs nor stops on a missing folder, so only warn.
    skip = look.launch_settings(system)[0]
    skipping = look.skips_rom_check(system)
    rom_path_rows: list[Check] = []  # severity decided once the games are checked
    own_looked = 0  # own games RL actually looks for a file for
    if own_games:
        if not own.folders and not skipping:
            rom_path_rows.append(Check(
                name="Rom_Path", status=Status.WARN,
                detail=f"not set in {own.ini}",
                fix=f"Set Rom_Path in {own.ini} to the folder holding this wheel's games",
            ))
        for shown in own.missing_folders():
            rom_path_rows.append(Check(
                name="Rom_Path", status=Status.WARN,
                detail=f"folder not found: {shown}",
                fix=f"Fix Rom_Path in {own.ini} (old drive letter or moved folder?)",
            ))
        node.children.extend(rom_path_rows)
        if not skipping and not uncheckable:
            missing: list[tuple[str, _RomSource]] = []
            stopped: dict[tuple[str, str, str], list[str]] = {}
            for src, name in own_games:
                if src.stops:
                    stopped.setdefault((src.emulator, src.stops, src.stop_fix), []).append(name)
                elif not src.exts:
                    unlooked += 1
                    continue
                elif not found(src, name):
                    missing.append((name, src))
                checked += 1
            own_looked = checked - sum(len(v) for v in stopped.values())
            # RL only fails a launch when no Rom_Path folder holds the ROM, so
            # a Rom_Path row is a FAIL only when RL looks for games and there
            # is no folder left to look in.  A missing second folder (an
            # unplugged drive) or a wheel RL never looks up stays a WARN.
            if own_looked and not any(
                f is not None and f.is_dir() for _el, f in own.folders
            ):
                for row in rom_path_rows:
                    row.status = Status.FAIL
            if missing:
                row = _missing_games_check(missing, checked, own, games, look)
                node.children.append(row)
                game_rows.append((row, len(missing)))
            # RL gives up on these before looking for any file.
            for (emu, why, fix), names in stopped.items():
                who = f"games use {emu}" if emu else "games"
                row = Check(
                    name="Emulator settings", status=Status.WARN,
                    detail=(f"{len(names)}/{checked} {who}: RocketLauncher stops before "
                            f"looking for them, because {why} (e.g. {names[0]})"),
                    fix=fix,
                )
                node.children.append(row)
                game_rows.append((row, len(names)))

    # 2. Games that use another system's settings (Games.ini System=).
    games_ini = look.settings_dir / system / "Games.ini"
    for entries in borrowed.values():
        src = entries[0][0]
        if not src.checkable():
            uncheckable = True
            continue
        n = len(entries)
        uses = f"{n} game{' uses' if n == 1 else 's use'} {src.system}'s settings (Games.ini System=)"
        gone = ", ".join(src.missing_folders())
        lost: list[str] = []
        stop = None  # the first of these games' sources on which RL stops early
        if not look.skips_rom_check(src.system):
            looked = 0
            for s, name in entries:
                if s.stops:
                    stop = stop or s
                    lost.append(name)
                elif not s.exts:
                    unlooked += 1
                    continue
                elif not found(s, name):
                    lost.append(name)
                looked += 1
            checked += looked
            n = looked
        if lost:
            detail = (f"{len(lost)}/{n} games that use {src.system}'s settings "
                      f"(Games.ini System=) not found (e.g. {', '.join(lost[:2])})")
            if stop is not None:
                detail += f"; RocketLauncher stops before looking, because {stop.stops}"
            elif gone:
                detail += f"; its Rom_Path folder doesn't exist: {gone}"
            elif not src.folders:
                detail += f"; Rom_Path is not set in {src.ini}"
        elif gone:
            detail = f"{uses}, whose Rom_Path folder doesn't exist: {gone}"
        else:
            continue
        fix = f"Fix Rom_Path in {src.ini}, or these games' System= in {games_ini}"
        if stop is not None:
            fix = f"{stop.stop_fix}, or change these games' System= in {games_ini}"
        row = Check(
            name=f"Games via {src.system}", status=Status.WARN, detail=detail, fix=fix,
        )
        node.children.append(row)
        if lost:
            game_rows.append((row, len(lost)))

    # Only a wheel where RL can find none of the games is a FAIL.
    if game_rows and sum(k for _row, k in game_rows) == considered:
        for row, _k in game_rows:
            row.status = Status.FAIL

    if uncheckable:
        node.detail = "Rom_Path uses Windows drive paths; can't check games on this OS"
    elif skipping:
        node.detail = f"Skipchecks={skip}: RocketLauncher doesn't look for ROM files"
    elif not game_rows and checked:
        node.detail = f"{checked} games OK"
    if unlooked and not uncheckable:
        note = (f"{unlooked} PCLauncher game{'s' if unlooked != 1 else ''} not checked: "
                "with no Rom_Extension, RocketLauncher doesn't look for a file")
        node.detail = f"{node.detail}; {note}" if node.detail else note
    node.status = _worst([c.status for c in node.children])
    return node


def _missing_games_check(
    missing: list[tuple[str, _RomSource]],
    checked: int,
    own: _RomSource,
    games: list[str],
    look: _RomLookup,
) -> Check:
    """The "Games" row (WARN; the caller makes it FAIL when every game of the
    wheel is missing): how many games RL can't find, plus the likely fix."""
    names = [n for n, _src in missing]
    examples = ", ".join(names[:2])
    hints: list[str] = []

    # Subfolder hint: most missing games sit in ONE subfolder of a Rom_Path
    # element (e.g. Sega Dreamcast\roms, Sony Playstation\MultiDisc).
    game_dirs = {g.lower() for g in games}
    wanted = [
        (n.lower(), [f"{n.lower()}.{ext}" if ext else n.lower() for ext in src.exts])
        for n, src in missing
    ]
    best: Optional[tuple[Path, Path]] = None  # (Rom_Path folder, its subfolder)
    for _el, folder in own.folders:
        lst = look.listing(folder) if folder is not None else None
        if lst is None or best is not None:
            continue
        # Skip <name>\<name>.ext game folders.  A folder with many other
        # subfolders is a per-game layout, not one ROM folder holding most
        # of the games, and scanning them all is slow on a cabinet's HDD.
        candidates = [real for low, real in lst[1].items() if low not in game_dirs]
        if len(candidates) > _SUBFOLDER_HINT_MAX:
            continue
        for real in candidates:
            sub = folder / real
            hits = sum(1 for n, w in wanted if look.found_in(sub, n, w))
            if hits * 2 > len(missing):
                best = (folder, sub)  # only one subfolder can hold most of them
                break
    if best is not None:
        hints.append(
            f"Move the files up into {best[0]}, or add {best[1]} to Rom_Path "
            f"in {own.ini} (separate several folders with |)"
        )

    # Placeholder hint: MAME alternate names (MameRomName in the MAME module
    # INI) need an empty <name>.txt in the ROM folder for RL to find them.
    mame = look.mame_rom_names()
    alt = [(n, src) for n, src in missing if n.lower() in mame]
    if alt:
        n, src = alt[0]
        folder = next(
            (f for _el, f in src.folders if f is not None and f.is_dir()),
            src.folders[0][1] if src.folders else None,
        )
        where = f" in {folder}" if folder is not None else ""
        mapping = f"MameRomName = {mame[n.lower()]} in Modules\\MAME\\MAME.ini"
        if len(alt) == 1:
            hint = (f"{n} is a MAME alternate name ({mapping}): "
                    f"it needs an empty {n}.txt placeholder{where}")
        else:
            hint = (f"{len(alt)} games are MAME alternate names (e.g. {n}: {mapping}): "
                    f"each needs an empty <name>.txt placeholder{where}, e.g. {n}.txt")
        if "txt" not in src.exts:
            hint += " (and add txt to Rom_Extension)"
        hints.append(hint)

    if not hints:
        src = missing[0][1]
        hints.append(
            f"Check Rom_Path in {own.ini}, and Rom_Extension in {src.ext_where} "
            f"(extensions tried: {'|'.join(src.exts)})"
        )
    return Check(
        name="Games",
        status=Status.WARN,
        detail=f"{len(missing)}/{checked} games not found in Rom_Path (e.g. {examples})",
        fix="; ".join(hints),
    )


def check_rom_paths(config: Config) -> Check:
    """Verify RocketLauncher can find every wheel's games in its ``Rom_Path``.

    ``check_wheel_wiring`` confirms a wheel has an emulator, but not that RL
    can find the ROM files — the layer that fails with RL's
    "Cannot find Rom … in any Rom_Paths provided".  For every Main Menu wheel
    this reads the system's ``Rom_Path`` (``|``-separated) from
    ``Settings/<System>/Emulators.ini`` ``[ROMS]`` (or flat
    ``Settings/<System>.ini`` ``[Settings]``) and the extensions RL tries the
    way RL 1.x does — ``Rom_Extension`` from the emulator's section in the
    first of the system file and ``Global Emulators.ini`` that has one (never
    from ``[ROMS]``), plus ``7z_Extensions`` when ``7z_Enabled`` — with
    ``Games.ini`` per-game overrides, and reports:

    * each ``Rom_Path`` folder that doesn't exist (moved folder, old drive
      letter);
    * games RL can't find as ``<path>\\<name>.<ext>`` or
      ``<path>\\<name>\\<name>.<ext>`` (or any matching file under
      ``<path>\\<name>\\`` with RL's ``Rom_Match_Extension=true``), with a hint
      when most of them sit in one subfolder of a ``Rom_Path`` folder, or are
      MAME alternate names (``MameRomName``) missing their empty
      ``<name>.txt`` placeholder.

    Games for which RL stops before looking (an emulator with no
    ``Rom_Extension`` or no section at all) get their own row.  PCLauncher
    wheels are included: their ``Rom_Path`` is the per-game INI folder.  A
    PCLauncher game with no extension to try isn't looked for by RL, so it
    isn't checked either.  Wheels with ``Skipchecks=Rom Only`` / ``Rom and Emu`` only get a
    folder warning, since RL doesn't look for their ROM files.  Games that a
    ``Games.ini`` ``System=`` sends to another system's settings are reported
    on their own row, judged by that system's ``Rom_Path`` and ``Skipchecks``
    as RL does.  Wheels switched off on the Main Menu are still checked, but
    capped at INFO so they can't fail ``doctor``.  Diagnosis only: the fix is
    an edit to the wheel's RL settings or ROM folder, named per row.
    """
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name="ROM paths", status=Status.INFO,
                     detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name="ROM paths", status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")

    from .rocketlauncher import SKIP_GENERATE_CONFIG

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = [w for w in _main_menu_wheels(mm_path) if w not in SKIP_GENERATE_CONFIG]
    if not wheels:
        return Check(name="ROM paths", status=Status.INFO, detail="no wheels on the Main Menu")

    look = _RomLookup(Path(config.rocketlauncher_dir))
    hidden = _hidden_main_menu_wheels(mm_path)
    parent = Check(name="ROM paths", status=Status.OK)
    for system in wheels:
        node = _wheel_rom_paths(system, look, config.databases_dir)
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)
    parent.status = _worst(c.status for c in parent.children)
    return parent


def _hidden_main_menu_wheels(mm_path: Path) -> set[str]:
    """Main Menu entries switched off (``enabled="False"`` / ``<enabled>No</enabled>``)."""
    from .database import _read_enabled

    try:
        with open(mm_path, "rb") as fh:
            root = ET.parse(fh).getroot()
    except (OSError, ET.ParseError):
        return set()
    return {
        (g.get("name") or "").strip() for g in root.findall("game")
        if _read_enabled(g, enabled_as_attribute=True) == "No"
    }


def _cap_at_info(check: Check) -> None:
    """Turn WARN/FAIL into INFO throughout *check*: findings on a hidden wheel
    are worth seeing, but can't break anything a player can reach."""
    if check.status in (Status.WARN, Status.FAIL):
        check.status = Status.INFO
    for child in check.children:
        _cap_at_info(child)


# ─── what HyperSpin itself shows ─────────────────────────────────────────────
#
# HyperSpin reads <hyperspin_dir>\Settings\<System>.ini and looks up media on
# its own; RocketLauncher reads neither, so every RocketLauncher check can pass
# while a wheel shows no games, or a game shows its name as text.

# Media HyperSpin looks up under a game's database name exactly as written:
# (what, folder under Media\<System>, extensions).  The video folder can be
# redirected by [video defaults] path= in the wheel's Settings INI.
_HS_GAME_MEDIA = (
    ("wheel art", ("Images", "Wheel"), (".png",)),
    ("video", ("Video",), (".mp4", ".flv", ".png")),
    ("theme", ("Themes",), (".zip",)),
)

# Names listed per wheel before "and N more".
_SPACED_NAMES_SHOWN = 5


def _hs_rom_index(folder: Path, recursive: bool) -> Optional[tuple[set[str], dict[str, set[str]]]]:
    """``(lower-cased names, {lower-cased stem: extensions})`` of the files and
    folders in *folder*, and in its subfolders when *recursive*; None when it
    can't be listed."""
    names: set[str] = set()
    try:
        if recursive:
            for _root, dirs, files in os.walk(folder):
                names.update(n.lower() for n in dirs)
                names.update(n.lower() for n in files)
        else:
            with os.scandir(folder) as it:
                names.update(entry.name.lower() for entry in it)
    except OSError:
        return None
    stems: dict[str, set[str]] = {}
    for n in names:
        stem, ext = os.path.splitext(n)
        stems.setdefault(stem, set()).add(ext[1:])
    return names, stems


def _hs_found(index: tuple[set[str], dict[str, set[str]]], names: list[str], exts: list[str]) -> bool:
    """Whether HyperSpin's ROMs-only filter finds a game under any of *names*:
    ``<name>.<ext>`` for an extension in *exts*, or any extension when it's empty."""
    listed, stems = index
    for name in names:
        low = name.lower()
        if exts:
            if any(f"{low}.{ext}" in listed for ext in exts):
                return True
        elif low in stems:
            return True
    return False


def _wheel_roms_only(
    system: str,
    ini: Path,
    exe: dict[str, str],
    config: Config,
    look: Optional[_RomLookup],
    index,
) -> Check:
    """One roms_only=true wheel's node for :func:`check_hyperspin_roms_only`."""
    node = Check(name=system, status=Status.OK)
    games, raw = _wheel_games(system, config.databases_dir)
    if not games:
        node.status = Status.INFO
        node.detail = "roms_only=true; no games in database"
        return node
    n = len(games)
    value = exe.get("rompath", "").strip().strip('"').strip()
    exts = [e.strip().lstrip(".").lower() for e in exe.get("romextension", "").split(",") if e.strip()]
    recursive = exe.get("searchsubfolders", "").strip().lower() == "true"

    def found(folder: Path) -> int:
        idx = index(folder, recursive)
        return 0 if idx is None else sum(
            1 for g in games if _hs_found(idx, [raw.get(g, g), g], exts))

    folder = _setting_folder(value, ini.parent.parent, False) if value else None
    if value and folder is None:
        node.status = Status.INFO
        node.detail = f"roms_only=true; rompath={value} can't be checked on this OS"
        return node
    steps: list[str] = []
    if folder is not None and _dir_exists(folder):
        idx = index(folder, recursive)
        if idx is None:
            node.status = Status.INFO
            node.detail = f"roms_only=true; can't list the rompath folder {value}"
            return node
        k = found(folder)
        if k:
            node.detail = f"roms_only=true: {k} of {n} games found in {value}"
            if k < n:
                node.detail += f" (HyperSpin hides the other {n - k})"
            return node
        with_ext = f"romextension={','.join(exts)}" if exts else "any extension"
        problem = f"rompath={value} holds none of its {n} games with {with_ext}"
        # The right folder with the wrong extensions?
        other: dict[str, int] = {}
        for g in games:
            for ext in set().union(*(idx[1].get(nm.lower(), set()) for nm in (raw.get(g, g), g))):
                if ext:
                    other[ext] = other.get(ext, 0) + 1
        if other:
            top = sorted(other, key=lambda e: (-other[e], e))[:3]
            steps.append(f"add {','.join(top)} to romextension= under [exe info] "
                         f"(the games there are .{', .'.join(top)} files)")
    elif value:
        problem = f"rompath={value} doesn't exist"
    else:
        problem = "rompath is empty"

    # A folder that does hold the games: RocketLauncher's Rom_Path for the
    # wheel, the same folder under roms_dir, or <roms_dir>\<System>.
    candidates: list[Path] = []
    if look is not None:
        src = look.source(system)
        if src is not None:
            candidates += [f for _el, f in src.folders if f is not None]
    if folder is not None:
        rebased = _rebased_setting(value, folder, config.roms_dir, False)
        if rebased:
            candidates.append(Path(rebased))
    if config.roms_dir:
        candidates.append(Path(config.roms_dir) / system)
    seen = {os.path.normcase(os.path.normpath(str(folder)))} if folder is not None else set()
    sep = os.sep if value.endswith(("\\", "/")) else ""
    for cand in candidates:
        key = os.path.normcase(os.path.normpath(str(cand)))
        if key in seen or not _dir_exists(cand):
            continue
        seen.add(key)
        k = found(cand)
        if k:
            new = str(cand).rstrip("\\/") + sep
            steps.insert(0, f"set rompath={new} under [exe info] (it holds {k} of the {n} games)")
            break
    if not steps:
        steps.append("point rompath under [exe info] at the folder holding this wheel's games")
    node.status = Status.WARN
    node.detail = f"roms_only=true, but {problem}, so HyperSpin lists no games"
    node.fix = (f"In {ini}, " + "; or ".join(steps)
                + "; or set roms_only=false under [filters] to list every game")
    return node


def check_hyperspin_roms_only(config: Config) -> Check:
    """Wheels whose HyperSpin "ROMs only" filter hides every game.

    With ``[filters] roms_only=true`` in ``<hyperspin_dir>\\Settings\\<System>.ini``,
    HyperSpin lists only the database games it finds as
    ``<[exe info] rompath>\\<name>.<ext>``, for an extension in the
    comma-separated ``romextension`` (counted anywhere below ``rompath`` with
    ``searchsubfolders=true``).  RocketLauncher never reads that file, so its
    ``Rom_Path`` (what ``generate-config`` writes and the ROM paths check reads)
    can be right while ``rompath`` still names an old drive after a ROM-drive
    move, and the wheel opens empty.  A relative ``rompath`` resolves from the
    HyperSpin folder, HyperSpin's working folder (``..\\Arcade\\<System>\\``).

    Per Main Menu wheel with roms_only=true: a WARN when ``rompath`` is empty,
    doesn't exist or holds none of the wheel's games, with a fix naming the
    file and key (a folder that holds the games, when one is found: the
    wheel's RocketLauncher ``Rom_Path``, the same folder under ``roms_dir`` or
    ``<roms_dir>\\<System>``).  Wheels switched off on the Main Menu are only
    INFO; wheels without roms_only=true aren't listed.  Diagnosis only.
    """
    name = "HyperSpin ROMs only"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO,
                     detail="hyperspin_dir not configured; skipping")
    hs_dir = Path(config.hyperspin_dir)
    mm_path = hs_dir / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = _main_menu_wheels(mm_path)
    if not wheels:
        return Check(name=name, status=Status.INFO, detail="no wheels on the Main Menu")
    hidden = _hidden_main_menu_wheels(mm_path)
    look = _RomLookup(Path(config.rocketlauncher_dir)) if config.rocketlauncher_dir else None
    indexes: dict[tuple[str, bool], Optional[tuple[set[str], dict[str, set[str]]]]] = {}

    def index(folder: Path, recursive: bool):
        """:func:`_hs_rom_index`, once per folder per run (wheels share folders)."""
        key = (os.path.normcase(os.path.normpath(str(folder))), recursive)
        if key not in indexes:
            indexes[key] = _hs_rom_index(folder, recursive)
        return indexes[key]

    parent = Check(name=name, status=Status.OK)
    for system in wheels:
        ini = hs_dir / "Settings" / f"{system}.ini"
        data = _read_rl_ini(ini)  # the one INI reader: any case, BOM, ANSI / UTF-16
        if data.get("filters", {}).get("roms_only", "").strip().lower() != "true":
            continue
        node = _wheel_roms_only(system, ini, data.get("exe info", {}), config, look, index)
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)

    n = len(parent.children)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    with_filter = f"wheel{'s' if n != 1 else ''} with roms_only=true"
    if not n:
        parent.detail = "no Main Menu wheel uses roms_only=true: HyperSpin lists every database game"
    elif warned:
        parent.detail = f"{warned} of {n} {with_filter} show{'s' if warned == 1 else ''} no games in HyperSpin"
    else:
        parent.detail = f"{n} {with_filter}; see each for what it shows"
    parent.status = _worst(c.status for c in parent.children)
    return parent


def _wheel_name_spaces(
    system: str,
    raw: dict[str, str],
    config: Config,
    look: Optional[_RomLookup],
) -> Check:
    """One wheel's node for :func:`check_game_name_spaces`."""
    from ._utils import win_safe_stem

    hs_dir = Path(config.hyperspin_dir)
    xml = find_database(system, config.databases_dir)
    spaced = sorted(raw.items(), key=lambda kv: kv[0].lower())  # (trimmed, as written)
    media = config.media_dir / system
    redirect = _read_rl_ini(hs_dir / "Settings" / f"{system}.ini").get(
        "video defaults", {}).get("path", "").strip().strip('"')
    redirected = _setting_folder(redirect, hs_dir, False) if redirect else None

    def has(dirs: list[Path], stem: str, exts) -> bool:
        for d in dirs:
            for ext in exts:
                try:
                    if (d / f"{stem}{ext}").is_file():
                        return True
                except (OSError, ValueError):
                    continue
        return False

    trimmed_only: dict[str, int] = {}  # media kind -> games with it under the trimmed name only
    lost_games = 0
    as_written_media = 0
    for trimmed, as_written in spaced:
        lost = False
        for what, sub, exts in _HS_GAME_MEDIA:
            dirs = [media.joinpath(*sub)]
            if what == "video" and redirected is not None:
                dirs.append(redirected)
            if has(dirs, as_written, exts):
                as_written_media += 1
            elif has(dirs, win_safe_stem(trimmed), exts):
                trimmed_only[what] = trimmed_only.get(what, 0) + 1
                lost = True
        if lost:
            lost_games += 1

    count = len(spaced)
    shown = ", ".join(f'"{r}"' for _t, r in spaced[:_SPACED_NAMES_SHOWN])
    more = f", and {count - _SPACED_NAMES_SHOWN} more" if count > _SPACED_NAMES_SHOWN else ""
    names = "game name starts or ends" if count == 1 else "game names start or end"
    detail = (f"{count} {names} with a space: {shown}{more}; "
              "HyperSpin looks up wheel art, video and theme under the name as written")
    if lost_games:
        kinds = ", ".join(w for w, _s, _e in _HS_GAME_MEDIA if w in trimmed_only)
        detail += (f", but {lost_games} of them {'has' if lost_games == 1 else 'have'} "
                   f"{kinds} only under the trimmed name")

    example = ""
    if look is not None:
        src = look.source(system)
        for trimmed, as_written in spaced:
            rom = look.find(src, [as_written]) if src is not None else None
            if rom is not None:
                example = f' (e.g. "{rom.name}" to "{trimmed}{rom.suffix}")'
                break
    if xml is None:
        xml = config.databases_dir / system / f"{system}.xml"
    fix = (f'In {xml}, remove the spaces around each name="..." and its <description>, '
           f"then rename the ROM file to match{example}")
    if as_written_media:
        # find-orphan-media matches media to trimmed names, so it lists these.
        fix += ", and any media saved under the name as written (find-orphan-media lists it as orphaned)"
    return Check(name=system, status=Status.WARN, detail=detail, fix=fix)


def check_game_name_spaces(config: Config) -> Check:
    """Database game names with leading or trailing spaces.

    ``load_database`` strips names, but RocketLauncher and HyperSpin both get a
    ``<game name="...">`` attribute exactly as written: RocketLauncher launches
    ``Some Hack V2 .nes`` for ``name="Some Hack V2 "`` (which the ROM paths
    check finds), and HyperSpin looks for
    ``Media\\<System>\\Images\\Wheel\\Some Hack V2 .png``, its video and its
    theme.  Media is usually saved under the trimmed name, by scrapers and by
    SpinDoctor's own downloads (Windows-safe names are trimmed), and
    ``audit`` looks the trimmed name up, so everything looks present while
    HyperSpin shows the game's name as text and plays no video.

    One WARN row per visible Main Menu wheel listing the names (the first
    five, then "and N more"), noting games whose media exists only under the
    trimmed name.  Wheels switched off on the Main Menu are only INFO.
    Diagnosis only: the fix is an edit to the database XML and a ROM rename.
    """
    name = "Spaces in game names"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO,
                     detail="hyperspin_dir not configured; skipping")
    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = _main_menu_wheels(mm_path)
    if not wheels:
        return Check(name=name, status=Status.INFO, detail="no wheels on the Main Menu")
    hidden = _hidden_main_menu_wheels(mm_path)
    look = _RomLookup(Path(config.rocketlauncher_dir)) if config.rocketlauncher_dir else None

    parent = Check(name=name, status=Status.OK)
    total = 0
    for system in wheels:
        raw = _raw_game_names(system, config.databases_dir)
        if not raw:
            continue
        total += len(raw)
        node = _wheel_name_spaces(system, raw, config, look)
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)

    if not parent.children:
        parent.detail = (f"no game name starts or ends with a space on the Main Menu's "
                         f"{len(wheels)} wheel{'s' if len(wheels) != 1 else ''}")
    else:
        n = len(parent.children)
        parent.detail = (f"{total} game name{'s' if total != 1 else ''} on {n} wheel"
                         f"{'s' if n != 1 else ''} start or end with a space")
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_lightguns(config: Config) -> Check:
    """Verify DemulShooter wiring for every system marked ``lightgun: true``.

    A system flagged for lightgun support runs a light-gun game — but if the
    RocketLauncher `Pre_Launch_App` DemulShooter wiring is missing, the game
    launches with no aiming device attached, and a missing `Post_Launch_App`
    teardown leaves DemulShooter running and can break the next launch.  These
    are silent failures the user only notices mid-game, so they belong in doctor.

    A system whose RocketLauncher User Functions start the gun software
    (``Lightgun.exe`` or DemulShooter) for the system or its emulators is
    wired too, and passes; one where only some games' files do is INFO.

    Diagnosis only — wiring a system needs a DemulShooter path and a `-target`
    choice, so there is no safe blanket auto-fix; each finding names the exact
    ``lightgun configure`` command instead.
    """
    from .lightgun import audit_system_wiring, index_user_functions

    systems = config.lightgun_systems()
    if not systems:
        return Check(
            name="Lightguns", status=Status.INFO,
            detail="no systems marked lightgun",
        )

    parent = Check(name="Lightguns", status=Status.OK)

    # demulshooter_path override, if set, must point at a real file.
    if config.demulshooter_path:
        p = Path(config.demulshooter_path)
        if not p.exists():
            parent.children.append(Check(
                name="demulshooter_path", status=Status.WARN,
                detail=f"configured but missing: {p}",
                fix="spindoctor config set demulshooter_path <path-to-DemulShooter.exe>",
            ))

    if not config.rocketlauncher_dir:
        parent.children.append(Check(
            name="wiring", status=Status.INFO,
            detail="rocketlauncher_dir not configured; can't check wiring",
        ))
        parent.status = _worst(c.status for c in parent.children)
        return parent

    # List the User Functions folder once, not once per system.
    user_functions = index_user_functions(Path(config.rocketlauncher_dir))
    for system in systems:
        node = Check(name=system, status=Status.OK)
        status = audit_system_wiring(system, config, user_functions=user_functions)
        if status is not None and not status.is_wired and status.wired_via_user_functions:
            where = status.user_functions_where()
            if status.user_functions_system_wide:
                node.detail = f"wired via User Functions ({where})"
            elif status.user_functions:
                node.status = Status.INFO
                node.detail = (f"wired via User Functions for some emulators only ({where}); "
                               "its other games may run with no gun")
            else:
                n = len(status.user_functions_games)
                node.status = Status.INFO
                node.detail = (f"wired via User Functions for {n} game{'s' if n != 1 else ''} "
                               f"only ({where}); its other games may run with no gun")
        elif status is None or not status.is_wired:
            node.status = Status.FAIL
            node.detail = ("marked lightgun but no DemulShooter Pre_Launch_App or User "
                           "Functions gun wiring — game runs with no gun")
            node.fix = f'spindoctor lightgun configure --system "{system}" --apply'
        else:
            if status.post_launch is None:
                node.children.append(Check(
                    name="teardown", status=Status.WARN,
                    detail="no DemulShooter Post_Launch_App — DemulShooter may keep running after exit",
                    fix=f'spindoctor lightgun configure --system "{system}" --apply',
                ))
            if status.target is None:
                node.children.append(Check(
                    name="target", status=Status.INFO,
                    detail="wired, but -target could not be parsed",
                ))
            else:
                node.children.append(Check(
                    name="target", status=Status.OK, detail=f"-target {status.target}",
                ))
            if "demulshooter" in status.user_functions_programs:
                node.children.append(Check(
                    name="user functions", status=Status.INFO,
                    detail=(f"User Functions also start DemulShooter "
                            f"({status.user_functions_where()}) — it may run twice"),
                ))
            node.status = _worst(c.status for c in node.children)
        parent.children.append(node)

    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_user_functions(config: Config) -> Check:
    """Programs started from RocketLauncher User Functions.

    Two mistakes in the AHK files RocketLauncher runs around a launch only
    show when someone plays: a ``Run`` line naming a program that isn't there
    (AutoHotkey stops with "Failed attempt to launch program or document"),
    and a key mapper (JoyToKey, Xpadder, antimicro) left running in HyperSpin
    after the game, where it doubles every pad press that DS4Windows Auto
    Profiles or another mapper also turn into keys.  Both are a WARN naming
    the file and line (see :mod:`spindoctor.rl_user_functions`).

    A file nothing a player can reach would run is listed as INFO: a wheel
    that's hidden or not on the Main Menu, a game that isn't on its wheel, or
    an emulator no visible wheel launches with.  Diagnosis only.
    """
    from .lightgun import _system_emulators, index_user_functions, system_settings_ini
    from .rl_user_functions import scan_user_functions

    if not config.rocketlauncher_dir:
        return Check(name="User Functions", status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")
    rl = Path(config.rocketlauncher_dir)
    index = index_user_functions(rl)
    if not index.files:
        return Check(name="User Functions", status=Status.OK,
                     detail="no User Functions files")

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = {w.lower(): w for w in _main_menu_wheels(mm_path)}
    hidden = {w.lower() for w in _hidden_main_menu_wheels(mm_path)}
    emulator_systems: dict[str, set[str]] = {}
    for low, wheel in wheels.items():
        found = system_settings_ini(rl, wheel)
        if found is None:
            continue
        try:
            body = found[0].read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for emu in _system_emulators(rl, wheel, body):
            if emu:
                emulator_systems.setdefault(emu, set()).add(low)

    wheel_games: dict[str, set[str]] = {}

    def unreachable(key: str) -> str:
        """Why nothing a player can reach runs the file at *key*, or ``""``."""
        if not wheels:
            return ""  # no Main Menu to tell by
        parts = key.split("/")
        if parts == ["global.ahk"]:
            return ""
        if parts[0] == "emulators":
            users = emulator_systems.get(parts[1][:-4], set())
            if not users:
                return "no wheel on the Main Menu uses this emulator"
            return "" if users - hidden else "only hidden wheels use this emulator"
        system = parts[0][:-4] if len(parts) == 1 else parts[0]
        if system not in wheels:
            return "not on the Main Menu"
        if system in hidden:
            return "hidden on the Main Menu"
        if len(parts) == 2:
            if system not in wheel_games:
                games, _ = _wheel_games(wheels[system], config.databases_dir)
                wheel_games[system] = {g.lower() for g in games}
            if wheel_games[system] and parts[1][:-4] not in wheel_games[system]:
                return f"not on the {wheels[system]} wheel"
        return ""

    findings = scan_user_functions(index, emulator_systems)
    parent = Check(name="User Functions", status=Status.OK)
    for key, items in findings.items():
        node = Check(name=index.label(key), status=Status.WARN,
                     detail="; ".join(f.text for f in items),
                     fix=" / ".join(dict.fromkeys(f.fix for f in items)))
        why = unreachable(key)
        if why:
            node.name += f" ({why})"
            _cap_at_info(node)
        parent.children.append(node)

    n = len(index.files)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    if not parent.children:
        parent.detail = (f"{n} file{'s' if n != 1 else ''}: no missing programs, "
                         "no key mapper left running")
    elif warned:
        parent.detail = f"{warned} of {n} files need a look"
    else:
        parent.detail = (f"{len(parent.children)} of {n} files have findings, all on "
                         "wheels, games or emulators players can't reach")
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_coin_start(config: Config) -> Check:
    """Games on the Main Menu's wheels that can't take a coin or start from a key.

    MAME and Supermodel keep one binding per input, and a game's own settings
    replace the folder-wide ones.  A game set up for a wheel, pad or gun can
    bind Coin 1 or 1 Player Start to that device's buttons only, so on a
    keyboard-encoder panel it boots but nothing inserts a coin or starts it.
    MAME also saves a game's cfg as it exits and writes
    ``JOYCODE_n_UNKNOWN_*`` for a device that's gone, losing the binding.

    A game is a WARN when its own binding has no key while the folder-wide one
    has, or names only a device that's gone (see :mod:`spindoctor.coin_start`).
    A folder-wide binding with no key is INFO (a joystick-encoder panel works
    that way), or a WARN when it names a lost device.  Hidden wheels and MESS
    console wheels are skipped.  Diagnosis only.
    """
    from .coin_start import LABELS, PORTS, check_game, inputs_for
    from .ledblinky_profiles import MESS_DRIVERS, MESS_PER_GAME_DRIVER
    from .rl_rom_paths import _resolve_rom_path

    name = "Coin/Start"
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")
    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    hidden = {w.lower() for w in _hidden_main_menu_wheels(mm_path)}
    wheels = [w for w in _main_menu_wheels(mm_path) if w.lower() not in hidden]
    rl = _RomLookup(Path(config.rocketlauncher_dir))
    mess_systems = {s.lower() for s in (*MESS_DRIVERS, *MESS_PER_GAME_DRIVER)}

    defaults: dict[str, str] = {}
    readers: dict[tuple[Path, str], object] = {}

    def default_emulator(system: str) -> str:
        if system not in defaults:
            found = rl.system(system)
            defaults[system] = found[2][found[1]].get("default_emulator", "") if found else ""
        return defaults[system]

    def reader_for(emulator: str, system: str):
        """``(reader, emulator name)`` for games *system* launches with *emulator*."""
        if not emulator or system.lower() in mess_systems:
            return None, ""
        found = rl.system(system)
        data = found[2] if found else {}
        # Like RL, use the local emulator section when present, even if empty.
        section = data.get(emulator.lower(), rl.global_emus.get(emulator.lower(), {}))
        raw = next((section[k] for k in _EMU_PATH_KEYS if section.get(k)), "")
        path = _resolve_rom_path(raw, rl.rl_dir) if raw else None
        if path is None:
            return None, ""
        identity = (path.parent, path.name.lower())
        if identity not in readers:
            readers[identity] = (inputs_for(path.parent, path.name)
                                 if path.parent.is_dir() else None)
        return readers[identity], emulator

    # Reader identity includes the executable: MAME and HBMAME may share a folder.
    groups: dict[object, dict] = {}
    for wheel in wheels:
        overrides = rl.game_overrides(wheel)
        if reader_for(default_emulator(wheel), wheel)[0] is None and not any(
                reader_for(emu or default_emulator(other or wheel), other or wheel)[0] is not None
                for emu, other in overrides.values()):
            continue  # no game on this wheel launches with MAME or Supermodel
        games, _ = _wheel_games(wheel, config.databases_dir)
        for game in games:
            emu, other = overrides.get(game.lower(), ("", ""))
            system = other or wheel
            reader, emulator = reader_for(emu or default_emulator(system), system)
            if reader is None:
                continue
            g = groups.setdefault(reader, {"emulators": [], "wheels": [], "games": {},
                                          "reader": reader})
            for key, value in (("emulators", emulator), ("wheels", wheel)):
                if value not in g[key]:
                    g[key].append(value)
            if game.lower() not in g["games"]:
                g["games"][game.lower()] = (game, check_game(reader, game))

    parent = Check(name=name, status=Status.OK)
    checked, bad = 0, set()
    for identity, g in groups.items():
        reader, games = g["reader"], list(g["games"].values())
        checked += len(games)
        node = Check(name=" / ".join(g["emulators"]), status=Status.OK)
        wheels_text = ", ".join(g["wheels"])
        findings = [f for _, f in games if f is not None]
        if findings:
            bad.update((identity, f.game.lower()) for f in findings)
            findings.sort(key=lambda f: (not any(b.lost for b in f.bindings.values()),
                                         f.game.lower()))
            listed = ", ".join(f.text() for f in findings[:5])
            more = f", and {len(findings) - 5} more" if len(findings) > 5 else ""
            node.children.append(Check(
                name="games", status=Status.WARN,
                detail=(f"{len(findings)} of {len(games)} games have a Coin or Start binding "
                        f"of their own that no key can press: {listed}{more}"),
                fix=reader.fix(),
            ))
        for port in PORTS:
            wide = reader.folder_binding(port)
            if wide.has_key:
                continue
            without = [game for game, _ in games if reader.game_binding(game, port) is None]
            affected = len(without)
            if not affected:
                continue
            label = LABELS[port]
            n_games = f"{affected} game{'s' if affected != 1 else ''}"
            if wide.lost:
                bad.update((identity, game.lower()) for game in without)
                verb = "take a coin" if port == "COIN1" else "start"
                node.children.append(Check(
                    name=wide.source, status=Status.WARN,
                    detail=(f"{label} is bound to a device MAME no longer finds ({wide.seq}), "
                            f"so {n_games} without a binding of their own can't {verb} "
                            "from any button"),
                    fix=f"with MAME closed, bind {label} again in {wide.source}, or in "
                        "MAME's menu (Tab > Input (general))",
                ))
            else:
                node.children.append(Check(
                    name=wide.source, status=Status.INFO,
                    detail=(f"{label} has no key ({wide.why()}: {wide.seq}): fine for a "
                            f"joystick-encoder panel, but a keyboard panel can't use {label} "
                            f"in {n_games}"),
                ))
        if reader.limits:
            node.children.append(Check(name="coverage", status=Status.INFO,
                                       detail="; ".join(reader.limits)))
        if node.children:
            node.detail = f"{len(games)} game{'s' if len(games) != 1 else ''} on {wheels_text}"
            node.status = _worst(c.status for c in node.children)
            parent.children.append(node)

    if not groups:
        parent.detail = "no MAME or Supermodel games on the Main Menu's wheels"
    elif not parent.children:
        parent.detail = (f"{checked} MAME / Supermodel games: each can take a coin "
                         "and start from a key")
    elif bad:
        parent.detail = (f"{len(bad)} of {checked} MAME / Supermodel games can't take a coin "
                         "or start from a key")
    elif any(g["reader"].limits for g in groups.values()):
        parent.detail = f"{checked} MAME / Supermodel games; see per-emulator coverage limits"
    else:
        parent.detail = (f"{checked} MAME / Supermodel games; some folder-wide bindings "
                         "have no key (fine for a joystick-encoder panel)")
    parent.status = _worst(c.status for c in parent.children)
    return parent


def _mame_emulator_folders(config: Config) -> dict[tuple[Path, str], list[str]]:
    """``(folder, exe)`` -> RocketLauncher emulator names, for each MAME-family build.

    An emulator counts when its ``Emu_Path`` names an existing ``mame*`` or
    ``hbmame*`` program (MAME, HBMAME and builds named after them, as the
    Coin/Start check reads them), from ``Global Emulators.ini`` and each
    system's own ``Emulators.ini``; when neither has one, the folders one
    level under ``emulators_dir`` holding such a program (no names).
    """
    def mame(name: str) -> bool:
        return name.lower().startswith(("mame", "hbmame"))

    found: dict[tuple[Path, str], list[str]] = {}
    for section, exe, candidates in _rl_emulator_entries(config):
        if not mame(exe):
            continue
        candidate = next((c for c in candidates if c.is_file()), None)
        if candidate is not None:
            names = found.setdefault((candidate.parent, candidate.name), [])
            if section not in names:
                names.append(section)
    if not found and config.emulators_dir:
        for folder in _subfolders(Path(config.emulators_dir)):
            try:
                with os.scandir(folder) as it:
                    exes = sorted(e.name for e in it if e.is_file() and mame(e.name)
                                  and e.name.lower().endswith(".exe"))
            except OSError:
                continue
            if exes:
                found[(folder, exes[0])] = []
    return found


def check_mame_key_maps(config: Config) -> Check:
    """MAME key maps that a crash while saving has emptied, or will.

    MAME saves ``cfg\\default.cfg`` as every game exits, and a crash while it
    does leaves the file at 0 bytes.  The next run ignores it and starts from
    MAME's own keys (5, 1, Ctrl / Alt / Space), then saves an empty map, so
    the panel's map is gone while every launch still works (see
    :mod:`spindoctor.mame_keymaps`).  Per MAME folder RocketLauncher lists:

    * ``default.cfg`` of 0 bytes, or one MAME can't read: WARN.
    * No key map in ``default.cfg`` (or none there) while ``ctrlr\\default.cfg``
      or ``cfg\\default.BAK.cfg`` holds one MAME never reads (``mame.ini``'s
      ``ctrlr`` doesn't name it): WARN, the map was probably lost.  With no
      such copy, an empty map is fine: MAME's own keys or each game's cfg.
    * MAME 0.145-0.179 with pad codes in ``default.cfg`` that it can place
      only while that pad is connected: WARN, it crashes saving them.
    * Game cfgs of 0 bytes (the same crash while saving a game's own
      settings): INFO.

    Diagnosis only.
    """
    from .mame_keymaps import exe_product_version, read_key_maps

    name = "MAME key maps"
    folders = _mame_emulator_folders(config)
    if not folders:
        return Check(name=name, status=Status.INFO, detail="no MAME or HBMAME emulator found")

    parent = Check(name=name, status=Status.OK)
    for (folder, exe), emulators in folders.items():
        maps = read_key_maps(folder, exe)
        default = maps.default
        node = Check(name=f"{', '.join(emulators) or folder.name}: {folder}", status=Status.OK)
        restore = ""
        if maps.spares:
            spare = maps.spares[0]
            restore = (f"With MAME closed, copy {spare.label} over {default.label} ({spare.ports} "
                       "bindings), start and quit one game, and check that the file still holds them")
            if spare.unplaceable and maps.crashes_saving:
                restore += (f"; first take {_some(spare.unplaceable)} out of the copy (each with the "
                            f"OR before it): MAME {maps.version} crashes saving them when the pad "
                            "isn't connected")
        else:
            restore = (f"With MAME closed, put the panel's key map back in {default.label} from a "
                       "backup, or set the keys again in MAME's menu (Tab > Input (general))")
        controller = maps.controller if maps.controller is not None and maps.controller.has_map else None
        if controller is not None:
            keys = f"only the map in {controller.label} ({maps.ini_name}'s ctrlr)"
        else:
            keys = "MAME's own keys (5 coin, 1 start, Ctrl / Alt / Space)"
        lost = f"the next run ignores it, starts from {keys} and saves an empty map at exit"

        if default.path is not None and default.size == 0:
            node.children.append(Check(
                name=default.label, status=Status.WARN,
                detail=f"0 bytes: MAME crashed while saving it, so {lost}",
                fix=restore))
        elif default.path is not None and not default.loads:
            node.children.append(Check(
                name=default.label, status=Status.WARN,
                detail=("MAME can't read it (no <mameconfig> with a \"default\" system), so MAME "
                        f"ignores it, starts from {keys} and saves an empty map over it at exit"),
                fix=restore))
        elif not default.has_map and maps.spares and controller is None:
            spare = maps.spares[0]
            where = "isn't there" if default.path is None else "holds no key map"
            ctrlr = (f"{maps.ini_name}'s ctrlr is blank" if not maps.controller_option
                     else f"{maps.ini_name}'s ctrlr names {maps.controller_option}")
            node.children.append(Check(
                name=default.label, status=Status.WARN,
                detail=(f"{where}, while {spare.label} holds {spare.ports} bindings MAME never "
                        f"reads ({ctrlr}): the panel's map was probably lost, and MAME uses its "
                        "own keys"),
                fix=restore))

        if default.has_map and default.unplaceable and maps.crashes_saving:
            node.children.append(Check(
                name=f"{default.label} pad codes", status=Status.WARN,
                detail=(f"MAME {maps.version} can place {_some(default.unplaceable)} only while "
                        "their pad is connected; without it, MAME crashes saving this file as "
                        f"the game exits, leaving it 0 bytes, and {lost}"),
                fix=(f"With MAME closed, take those codes out of {default.label} (each with the OR "
                     "before it), keeping the keys, or connect the pad before MAME starts")))

        if maps.empty_games:
            n = len(maps.empty_games)
            node.children.append(Check(
                name="game cfgs", status=Status.INFO,
                detail=(f"{n} game cfg file{'s are' if n != 1 else ' is'} 0 bytes "
                        f"({_some(maps.empty_games, 5)}): MAME crashed while saving "
                        f"{'them' if n != 1 else 'it'}, so those games start from "
                        f"{default.label} and their own settings are gone")))

        if node.children:
            version = maps.version or exe_product_version(folder / exe)
            node.detail = f"{exe}, MAME {version}" if version else exe
            node.status = _worst(c.status for c in node.children)
            parent.children.append(node)

    total = len(folders)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    plural = "s" if total != 1 else ""
    if warned:
        parent.detail = f"{warned} of {total} MAME folder{plural} lost or can lose the panel's key map"
    elif parent.children:
        parent.detail = f"{total} MAME folder{plural}: key maps fine; some game cfgs are empty"
    else:
        parent.detail = f"{total} MAME folder{plural}: no key map lost or at risk"
    parent.status = _worst(c.status for c in parent.children)
    return parent


@dataclass(frozen=True)
class _EmuFolderSetting:
    """One emulator config value that names a ROM or save folder.

    ``key`` is a regex matched against the whole lower-cased key name;
    ``section``, ``count_key`` and ``module_writes`` are lower-case too.
    """
    emulator: str                 # display name
    exes: tuple[str, ...]         # Emu_Path exe names that identify the emulator
    filename: str                 # config file in the emulator's folder
    key: str
    section: str = ""             # only this [section]; "" = any
    count_key: str = ""           # numbered keys at or above this key's value are unused
    file_value: bool = False      # the value names a file; check its folder
    rl_module: str = ""           # file lives in RocketLauncher\Modules\<rl_module>\ instead
    module_writes: str = ""       # a module that writes this key sets the folder at launch
    off_when: tuple[str, str] = ("", "")  # (key, value) under which the setting is unused


# Emulators that keep their own ROM / save folder, which neither
# generate-config nor migrate rewrites.  Add a row to cover another one.
# MAME's mame.ini ``rompath`` is left out on purpose: RocketLauncher passes
# -rompath on the command line, so a stale value there is cosmetic.
# ``module_writes`` spots the same case in a module that writes the setting
# before each launch: the stock AAE module (mame_rom_path) and the Demul
# v0.5.8 / v0.7 modules (they append the ROM folder and bump romsPathsCount).
# The Demul v0.5.6 / v0.5.7 modules only pass -rom=, so Demul searches roms0..N.
_EMU_FOLDER_SETTINGS = (
    _EmuFolderSetting("AAE", ("aae.exe",), "aae.ini", r"mame_rom_path",
                      module_writes="mame_rom_path"),
    _EmuFolderSetting("Demul", ("demul.exe",), "Demul.ini", r"roms\d+",
                      section="files", count_key="romspathscount",
                      module_writes="romspathscount"),
    # eepromfile is the one shared save file only while eepromshare is on (the
    # default).  With it off PokeMini saves next to each ROM and just writes the
    # last game's .eep back here, so a stale value breaks nothing.
    _EmuFolderSetting("PokeMini", ("pokemini.exe",), "pokemini.cfg", r"eepromfile",
                      file_value=True, off_when=("eepromshare", "no")),
    _EmuFolderSetting("Daphne", (), "Daphne.ini", r"homedir", rl_module="Daphne"),
)

# Global Emulators.ini keys that hold the emulator exe (as _read_emulator_exe).
_EMU_PATH_KEYS = ("emu_path", "emulator_application_path", "emulator_path")


def _read_ini_entries(path: Path) -> list[tuple[str, str, str]]:
    """``(section, key, value)`` for every ``key=value`` line of *path*.

    Loose on purpose: emulator configs repeat a section (Demul writes a second
    ``[main]``) or have no section at all (pokemini.cfg), which configparser
    rejects.  Names keep their case; callers compare them lower-cased.
    """
    import re

    text = _read_windows_text(path)
    entries: list[tuple[str, str, str]] = []
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s[0] == "[" and s[-1] == "]":
            section = s[1:-1].strip()
        elif "=" in s:
            key, value = s.split("=", 1)
            # aae.ini puts comments after values: "doublebuffer = 1 ;Enable ..."
            value = re.sub(r"\s+;.*$", "", value)
            entries.append((section, key.strip(), value.strip()))
    return entries


def _dir_exists(p: Path) -> bool:
    try:
        return p.is_dir()
    except (OSError, ValueError):
        return False


def _subfolders(folder: Path) -> list[Path]:
    try:
        with os.scandir(folder) as it:
            return sorted((Path(e.path) for e in it if e.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return []


def _setting_folder(value: str, base: Optional[Path], file_value: bool) -> Optional[Path]:
    """The folder a config value points at, or None when it can't be checked.

    A relative value resolves from *base* (the emulator's folder, where
    RocketLauncher starts it); with no base it is skipped.  An absolute Windows
    drive path can only be checked on Windows (as ``_resolve_emu_path``).
    """
    from pathlib import PureWindowsPath

    pw = PureWindowsPath(value)
    if pw.drive:
        if os.name != "nt":
            return None
        p = Path(value)
    elif Path(value).is_absolute():
        p = Path(value)
    elif base is not None:
        p = Path(os.path.normpath(base.joinpath(*pw.parts)))
    else:
        return None
    return p.parent if file_value else p


def _rebased_setting(value: str, folder: Path, roms_dir: str, file_value: bool) -> Optional[str]:
    """*value* moved under *roms_dir* when the same trailing folders exist there
    (``J:\\Games\\Sega Naomi`` → ``<roms_dir>\\Sega Naomi``), longest tail first."""
    if not roms_dir:
        return None
    from pathlib import PureWindowsPath

    parts = folder.parts[1:] if folder.anchor else folder.parts
    for i in range(len(parts)):
        candidate = Path(roms_dir).joinpath(*parts[i:])
        if _dir_exists(candidate):
            if file_value:
                return str(candidate / PureWindowsPath(value).name)
            return str(candidate) + (os.sep if value.endswith(("\\", "/")) else "")
    return None


def _module_writes(module: Path, key: str, cache: dict) -> bool:
    """Whether RocketLauncher *module* writes *key* (lower-case) into the
    emulator's config before launch: a ``Write`` line naming it, outside a
    ``;`` comment."""
    if (module, key) not in cache:
        try:
            text = module.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            text = ""
        cache[(module, key)] = any(
            "write" in code and key in code
            for code in (line.split(";", 1)[0] for line in text.splitlines())
        )
    return cache[(module, key)]


def _emulator_config_files(
    config: Config,
) -> list[tuple[_EmuFolderSetting, Path, Optional[Path], Optional[Path]]]:
    """``(setting, config file, emulator folder, managing module)`` for each
    installed emulator in ``_EMU_FOLDER_SETTINGS``.

    Emulator folders come from the ``Emu_Path`` entries of Global Emulators.ini.
    An emulator with no usable entry there is looked for one level under
    ``emulators_dir`` instead.  A RocketLauncher module INI has no emulator
    folder (None).  The managing module is set only when every entry that
    launches the folder uses a module that writes the setting itself.
    """
    from pathlib import PureWindowsPath

    rl_dir = Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None
    known_exes = {exe for s in _EMU_FOLDER_SETTINGS for exe in s.exes}

    # (exe, candidate folders, module file) per known emulator in Global Emulators.ini.
    emus: list[tuple[str, list[Path], Path]] = []
    global_ini = rl_dir / "Settings" / "Global Emulators.ini" if rl_dir else None
    if global_ini is not None and global_ini.is_file():
        try:
            entries = _read_ini_entries(global_ini)
        except OSError:  # locked / unreadable: fall back to emulators_dir
            entries = []
        sections: dict[str, tuple[str, dict[str, str]]] = {}
        for section, key, value in entries:
            sections.setdefault(section.lower(), (section, {}))[1].setdefault(key.lower(), value)
        for section, keys in sections.values():
            emu_path = next((keys[k] for k in _EMU_PATH_KEYS if keys.get(k)), "")
            exe = PureWindowsPath(emu_path).name.lower()
            if exe not in known_exes:
                continue
            # RocketLauncher resolves Module= from Modules\<emulator>\ (default <emulator>.ahk).
            module = PureWindowsPath(keys.get("module") or f"{section}.ahk")
            emus.append((
                exe,
                [c.parent for c in _resolve_emu_path(emu_path, rl_dir)],
                Path(os.path.normpath(rl_dir.joinpath("Modules", section, *module.parts))),
            ))

    subdirs: Optional[list[Path]] = None
    writes_cache: dict = {}
    found: list[tuple[_EmuFolderSetting, Path, Optional[Path], Optional[Path]]] = []
    for setting in _EMU_FOLDER_SETTINGS:
        if setting.rl_module:
            module_ini = rl_dir / "Modules" / setting.rl_module / setting.filename if rl_dir else None
            if module_ini is not None and module_ini.is_file():
                found.append((setting, module_ini, None, None))
            continue
        # folder -> modules of the entries that launch it (several can share one)
        folders: dict[Path, list[Path]] = {}
        for exe, dirs, module in emus:
            if exe in setting.exes:
                hit = next((d for d in dirs if (d / setting.filename).is_file()), None)
                if hit is not None:
                    folders.setdefault(hit, []).append(module)
        if not folders and config.emulators_dir:
            if subdirs is None:
                subdirs = _subfolders(Path(config.emulators_dir))
            folders = {d: [] for d in subdirs if (d / setting.filename).is_file()}
        for folder, modules in folders.items():
            managed = None
            if setting.module_writes and modules and all(
                    _module_writes(m, setting.module_writes, writes_cache) for m in modules):
                managed = modules[0]
            found.append((setting, folder / setting.filename, folder, managed))
    return found


def check_emulator_rom_paths(config: Config) -> Check:
    """Flag ROM / save folders that emulators keep in their *own* config files.

    After a ROM-drive move, ``generate-config`` rewrites RocketLauncher's
    ``Rom_Path`` values, but some emulators read ROMs or saves from a folder in
    their own config: AAE's ``mame_rom_path``, Demul's ``roms0..N`` (the v0.5.7
    module only passes ``-rom=``), PokeMini's ``eepromfile`` and the Daphne
    module's per-game ``homedir``.  Neither ``generate-config`` nor ``migrate``
    rewrites those, so the games can't find their ROMs while every
    RocketLauncher check passes.

    Diagnosis only: each missing folder is a WARN naming the file, key and
    current value, plus the exact replacement when the same folder exists under
    ``roms_dir``.  It is only INFO when the emulator's RocketLauncher module
    writes that setting itself before every launch.
    """
    import re

    name = "Emulator ROM folders"
    configs = _emulator_config_files(config)
    if not configs:
        labels = [s.emulator for s in _EMU_FOLDER_SETTINGS]
        return Check(
            name=name, status=Status.INFO,
            detail=f"no {', '.join(labels[:-1])} or {labels[-1]} config found",
        )

    parent = Check(name=name, status=Status.OK)
    for setting, path, base, managed in configs:
        node = Check(name=f"{setting.emulator}: {path}", status=Status.OK)
        try:
            entries = [(k, v) for sec, k, v in _read_ini_entries(path)
                       if not setting.section or sec.lower() == setting.section]
        except OSError as e:
            node.status = Status.INFO
            node.detail = f"unreadable: {e}"
            parent.children.append(node)
            continue

        off_key, off_value = setting.off_when
        if off_key and any(
            k.lower() == off_key and v.strip('"').strip().lower() in (off_value, "false", "0")
            for k, v in entries
        ):
            node.detail = f"{off_key}={off_value}, so {setting.key} isn't used"
            parent.children.append(node)
            continue

        limit = None
        if setting.count_key:
            counts = [v for k, v in entries if k.lower() == setting.count_key]
            if counts and counts[-1].isdigit():
                limit = int(counts[-1])

        # (key, value) -> number of entries, so 17 Daphne games sharing one
        # stale homedir make one row.
        missing: dict[tuple[str, str], int] = {}
        checked = 0
        for key, value in entries:
            value = value.strip('"').strip()
            if not value or not re.fullmatch(setting.key, key.lower()):
                continue
            number = re.search(r"\d+$", key)
            if limit is not None and number and int(number.group()) >= limit:
                continue
            folder = _setting_folder(value, base, setting.file_value)
            if folder is None:
                continue
            checked += 1
            if not _dir_exists(folder):
                missing[(key, value)] = missing.get((key, value), 0) + 1

        if missing and managed is not None:
            # The module sets the folder before every launch: harmless leftovers.
            keys = ", ".join(dict.fromkeys(k for k, _ in missing))
            node.status = Status.INFO
            node.detail = f"{keys} not found; harmless, {managed.name} sets the folder at launch"
            parent.children.append(node)
            continue
        for (key, value), count in missing.items():
            folder = _setting_folder(value, base, setting.file_value)
            new = _rebased_setting(value, folder, config.roms_dir, setting.file_value)
            node.children.append(Check(
                name=key, status=Status.WARN,
                detail=f"folder not found: {value}" + (f" ({count} entries)" if count > 1 else ""),
                fix=(f"In {path}, set {key}={new}" if new
                     else f"In {path}, point {key} at the folder's new location"),
            ))
        if node.children:
            node.status = Status.WARN
            node.detail = f"{sum(missing.values())} of {checked} folder path(s) not found"
        elif checked:
            node.detail = f"{checked} folder path(s) OK"
        else:
            node.detail = "no checkable folder paths (unset or relative)"
        parent.children.append(node)

    parent.status = _worst(c.status for c in parent.children)
    return parent


def _rl_emulator_entries(config: Config) -> list[tuple[str, str, list[Path]]]:
    """``(emulator name, exe name lower-cased, candidate exe paths)`` per emulator.

    From ``Global Emulators.ini`` and each system's own
    ``Settings\\<System>\\Emulators.ini`` (their ``[ROMS]`` sections aside),
    with ``Emu_Path`` resolved as :func:`_resolve_emu_path` does.
    """
    from pathlib import PureWindowsPath

    if not config.rocketlauncher_dir:
        return []
    rl_dir = Path(config.rocketlauncher_dir)
    settings = rl_dir / "Settings"
    inis = [settings / "Global Emulators.ini"]
    inis += [d / "Emulators.ini" for d in _subfolders(settings)]
    out = []
    for ini in inis:
        try:
            entries = _read_ini_entries(ini) if ini.is_file() else []
        except OSError:
            continue
        sections: dict[str, tuple[str, dict[str, str]]] = {}
        for section, key, value in entries:
            if section.lower() != "roms":
                sections.setdefault(section.lower(), (section, {}))[1].setdefault(
                    key.lower(), value)
        for section, keys in sections.values():
            emu_path = next((keys[k] for k in _EMU_PATH_KEYS if keys.get(k)), "").strip('"')
            if emu_path:
                out.append((section, PureWindowsPath(emu_path).name.lower(),
                            _resolve_emu_path(emu_path, rl_dir)))
    return out


def _daphne_emulator_folders(config: Config) -> dict[Path, list[str]]:
    """Folder -> RocketLauncher emulator names, for each Daphne or Singe build.

    An emulator counts when its ``Emu_Path`` names ``daphne.exe`` or a
    ``dapinput.ini`` sits beside the exe (a renamed build).  Emulators come
    from ``Global Emulators.ini`` and from each system's own
    ``Settings\\<System>\\Emulators.ini``; when neither has one, from the
    folders one level under ``emulators_dir`` holding either file (no names).
    """
    from .daphne_keys import KEY_FILE

    found: dict[Path, list[str]] = {}
    for section, exe, candidates in _rl_emulator_entries(config):
        for candidate in candidates:
            folder = candidate.parent
            if ((exe == "daphne.exe" and candidate.is_file())
                    or (folder / KEY_FILE).is_file()):
                names = found.setdefault(folder, [])
                if section not in names:
                    names.append(section)
                break
    if not found and config.emulators_dir:
        for folder in _subfolders(Path(config.emulators_dir)):
            if (folder / KEY_FILE).is_file() or (folder / "daphne.exe").is_file():
                found[folder] = []
    return found


def _some(items: list[str], shown: int = 3) -> str:
    """The first *shown* items, then how many more."""
    more = f" and {len(items) - shown} more" if len(items) > shown else ""
    return ", ".join(items[:shown]) + more


def check_daphne_keys(config: Config) -> Check:
    """Daphne / Singe key files that leave an action on key 0.

    Daphne 1.0.x and its Singe builds (SDL 1.2) read a ``dapinput.ini`` line
    such as ``KEY_QUIT = 27 0 0`` as two keyboard keys and a joystick button.
    SDL 1.2 reports keys it has no name for (volume and media keys) as 0, and
    Daphne checks every action's two key slots, so a 0 slot isn't "no key":
    one Volume Up press can quit, pause or tilt the game.  Actions the file
    leaves out keep Daphne's built-in keys, most of which have a 0 slot too
    (see :mod:`spindoctor.daphne_keys`).

    Each emulator folder's ``dapinput.ini`` is read, plus the
    ``controls\\*.ini`` files RocketLauncher's Daphne module copies over it
    before every launch.  A file that leaves actions on key 0 is a WARN
    naming them (quit, pause, service and test first), with the lines to
    write: 296 (F15, a key nothing sends) in each 0 slot.  Diagnosis only.
    """
    from .daphne_keys import FILLER, KEY_FILE, label, read_key_file

    name = "Daphne keys"
    folders = _daphne_emulator_folders(config)
    if not folders:
        return Check(name=name, status=Status.INFO, detail="no Daphne or Singe emulator found")

    parent = Check(name=name, status=Status.OK)
    for folder, emulators in folders.items():
        try:
            with os.scandir(folder / "controls") as it:
                controls = [Path(e.path) for e in it
                            if e.is_file() and e.name.lower().endswith(".ini")]
        except OSError:
            controls = []
        controls.sort(key=lambda p: (p.name.lower() != KEY_FILE, p.name.lower()))
        title = ", ".join(emulators) or folder.name
        for path in [folder / KEY_FILE] + controls:
            report = read_key_file(path)
            node = Check(name=f"{title}: {path}", status=Status.OK)
            parent.children.append(node)
            if not report.exists and controls:
                node.status = Status.INFO
                node.detail = ("not there yet; RocketLauncher's Daphne module copies one "
                               "from controls\\ before each launch")
                continue

            why = ""
            if not report.exists:
                why = f"no {KEY_FILE}, so Daphne uses its built-in keys"
            elif not report.header and report.bom:
                why = ("the file starts with a byte-order mark, so Daphne never finds "
                       "its [KEYBOARD] line and uses its built-in keys")
            elif not report.header:
                why = "no [KEYBOARD] line, so Daphne uses its built-in keys"
            elif report.stopped:
                why = (f"Daphne stops reading at line {report.stopped_line} ({report.stopped}), "
                       "so the actions after it keep its built-in keys")

            zero = report.zero_slots()
            if not zero:
                node.status = Status.INFO if why else Status.OK
                node.detail = why or "no action left on key 0"
                continue
            names = [label(s.action) for s in zero]
            node.status = Status.WARN
            node.detail = (f"{_some(names, 5)} left on key 0: any key SDL 1.2 doesn't know, "
                           f"such as a volume or media key, presses {'it' if len(zero) == 1 else 'them'}")
            built_in = [s.fixed() for s in zero if not s.line]
            if why:
                node.detail = f"{why}; {node.detail}"
            elif built_in:
                node.detail += (f" ({len(built_in)} of them aren't in the file, so Daphne's "
                                "built-in keys apply)")
            if path == folder / KEY_FILE and controls:
                node.detail += ("; RocketLauncher's Daphne module copies controls\\<game>.ini "
                                "or controls\\dapinput.ini over this file before each launch, "
                                "so fix those too")
            if report.exists and not report.header and report.bom:
                node.fix = (f"With Daphne closed, save {path} as ANSI or UTF-8 without a "
                            "byte-order mark, then run doctor again")
                continue
            in_file = [s.fixed() for s in zero if s.line]
            fixes = []
            if in_file:
                fixes.append(f"set {_some(in_file)}")
            if report.stopped:
                # The lines after it may set the rest; doctor can tell once Daphne reads them.
                fixes.append(f"fix or remove line {report.stopped_line}, then run doctor again")
            elif built_in:
                fixes.append(f"add {_some(built_in)} before END" if report.exists
                             else f"create it with [KEYBOARD], {_some(built_in)}, then END")
            node.fix = (f"With Daphne closed, put {FILLER} (F15, a key nothing sends) in every "
                        f"0 key slot of {path}: " + "; ".join(fixes))

    total = len(parent.children)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    if warned:
        parent.detail = (f"{warned} of {total} key file{'s' if total != 1 else ''} "
                         f"{'leaves' if warned == 1 else 'leave'} actions on key 0, which a "
                         "volume or media key presses")
    else:
        parent.detail = f"{total} key file{'s' if total != 1 else ''}: no action left on key 0"
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_led_coverage(config: Config) -> Check:
    """Report how many wheel games have LEDBlinky control/color entries.

    Purely informational, and deliberately **cache-only**: it never triggers a
    fresh ``mame -listxml`` (which can take minutes). Games are those in every
    wheel that uses MAME ROM names, plus their parents, the set ``ledblinky
    generate`` works on. Without a fresh cached listxml it still counts what
    SpinDoctor's LEDBlinky library can restore; with neither it points the
    user at ``ledblinky audit``.

    "Could be generated" games are the actionable bucket: no LEDBlinky entry
    yet, but the library or MAME's input data has one, so ``ledblinky
    generate`` can light them up. A child WARN flags live files holding
    thousands of entries for games in no wheel: LEDBlinky loads them all at
    startup before it answers the front end (``ledblinky prune`` fixes it).
    """
    if not config.ledblinky_dir:
        return Check(name="LED coverage", status=Status.INFO,
                     detail="ledblinky_dir not configured; skipping")

    from .ledblinky import audit_coverage
    from .ledblinky_library import (
        PRUNE_WARN_ENTRIES,
        Library,
        listxml_if_cached,
        unused_entries,
        wheel_scope,
    )

    listxml = listxml_if_cached(config)
    library = Library()
    scope = wheel_scope(config, listxml=listxml)

    children: list[Check] = []
    unused = unused_entries(config, scope)
    if unused.controls >= PRUNE_WARN_ENTRIES:
        children.append(Check(
            name="Entries for games in no wheel", status=Status.WARN,
            detail=(f"{unused.controls} of {unused.controls_total} controls.ini entries "
                    f"({unused.colors} of {unused.colors_total} in Colors.ini); LEDBlinky loads "
                    "them all at startup, delaying its lights"),
            fix="spindoctor ledblinky prune --apply",
        ))

    def done(status: Status, detail: str, fix: Optional[str] = None) -> Check:
        return Check(name="LED coverage", status=_worst([status] + [c.status for c in children]),
                     detail=detail, fix=fix, children=children)

    if not listxml and not library:
        if not config.mame_executable:
            return done(Status.INFO, "mame_executable not configured; skipping")
        return done(Status.INFO, "MAME control data not cached (won't run -listxml from doctor)",
                    "spindoctor ledblinky audit")

    roms = scope.names()
    if not roms:
        return done(Status.INFO, "no wheel uses MAME ROM names; skipping")

    rows = audit_coverage(config, roms, library=library, listxml=listxml, scope=scope)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    covered = counts.get("covered", 0)
    from_library = counts.get("from-library", 0)
    would = counts.get("would-synth", 0) + from_library
    detail = (f"{covered}/{len(roms)} covered (wheel games and their parents) · {would} could be generated"
              + (f" ({from_library} from SpinDoctor's library)" if from_library else "")
              + f" · {counts.get('no-input', 0)} no-input · "
              f"{counts.get('missing', 0)} no data"
              + ("" if listxml else " (MAME data not cached: library only)"))
    if would:
        return done(Status.WARN, detail, "spindoctor ledblinky generate --apply")
    return done(Status.OK, detail)


def _mmss(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def _intro_clip_length_checks(config: Config) -> "list[Check]":
    """Can the logon swap wait out every clip in the pool?

    HyperSpin holds ``intro_video_target`` open while the clip plays, and the
    swap retries for that clip's length plus a margin, up to
    ``SWAP_RETRY_MAX_SECONDS``. A longer clip makes the swap fail at every
    boot it's the one playing; a clip whose length can't be read gets the
    old fixed 3 minutes. Reads only each file's header.
    """
    from .introvideo import (
        SWAP_RETRY_ATTEMPTS,
        SWAP_RETRY_DELAY_SECONDS,
        SWAP_RETRY_MARGIN_SECONDS,
        SWAP_RETRY_MAX_SECONDS,
        pool_clip_lengths,
    )

    lengths = pool_clip_lengths(config)
    out: list[Check] = []
    if lengths.too_long:
        shown = ", ".join(f"{name} ({_mmss(s)})" for name, s in lengths.too_long[:3])
        more = f" and {len(lengths.too_long) - 3} more" if len(lengths.too_long) > 3 else ""
        out.append(Check(
            name="clip length", status=Status.WARN,
            detail=(f"{len(lengths.too_long)} clip(s) too long for the logon swap to wait out "
                    f"(it waits at most {_mmss(SWAP_RETRY_MAX_SECONDS)}): {shown}{more}"),
            fix=f'spindoctor introvideo remove "{lengths.too_long[0][0]}" --apply',
        ))
    elif lengths.longest:
        wait = min(lengths.longest_seconds + SWAP_RETRY_MARGIN_SECONDS, SWAP_RETRY_MAX_SECONDS)
        wait = max(wait, SWAP_RETRY_ATTEMPTS * SWAP_RETRY_DELAY_SECONDS)
        out.append(Check(
            name="clip length", status=Status.OK,
            detail=(f"longest clip {_mmss(lengths.longest_seconds)} ({lengths.longest}); "
                    f"the logon swap waits up to {_mmss(wait)} for it"),
        ))
    if lengths.unreadable:
        shown = ", ".join(lengths.unreadable[:3])
        more = f" and {len(lengths.unreadable) - 3} more" if len(lengths.unreadable) > 3 else ""
        out.append(Check(
            name="clip length (unread)", status=Status.INFO,
            detail=(f"{len(lengths.unreadable)} video(s) whose length can't be read (only MP4 / M4V / "
                    f"MOV are): {shown}{more}. While one of them plays, the swap waits as long as for "
                    f"the longest clip it can read, and at least "
                    f"{_mmss(SWAP_RETRY_ATTEMPTS * SWAP_RETRY_DELAY_SECONDS)}"),
            fix=("convert them to MP4, or give the logon task a head start: "
                 "spindoctor introvideo install-autorun --delay-minutes <N> --apply"),
        ))
    return out


def check_intro_video(config: Config) -> Check:
    """Health of the intro-video randomizer (opt-in feature).

    Catches failures that otherwise have *no* symptom until someone notices the
    boot video stopped changing: an empty pool (``introvideo swap`` is a silent
    no-op by design), a target whose folder no longer exists, and a logon
    auto-run task that's registered but stale (points at an old install after a
    portable upgrade — re-running ``install-autorun`` fixes it in place).
    """
    if not config.intro_randomizer_dir and not config.intro_video_target:
        return Check(name="Intro video", status=Status.INFO,
                     detail="not configured (optional feature)")

    parent = Check(name="Intro video", status=Status.OK)

    if config.intro_randomizer_dir:
        pool_dir = Path(config.intro_randomizer_dir)
        if not pool_dir.exists():
            parent.children.append(Check(
                name="pool", status=Status.WARN,
                detail=f"intro_randomizer_dir missing: {pool_dir}",
                fix="spindoctor config set intro_randomizer_dir <path>",
            ))
        else:
            from .introvideo import list_videos
            enabled = [v for v in list_videos(config) if v.enabled]
            if not enabled:
                parent.children.append(Check(
                    name="pool", status=Status.WARN,
                    detail="pool is empty — introvideo swap is a silent no-op",
                    fix="spindoctor introvideo add <video-file>",
                ))
            else:
                parent.children.append(Check(
                    name="pool", status=Status.OK,
                    detail=f"{len(enabled)} video(s) in rotation",
                ))
                parent.children.extend(_intro_clip_length_checks(config))

    if config.intro_video_target:
        target_parent = Path(config.intro_video_target).parent
        if not target_parent.exists():
            parent.children.append(Check(
                name="target", status=Status.WARN,
                detail=f"target folder does not exist: {target_parent}",
                fix="spindoctor config set intro_video_target <path>",
            ))

    # Logon auto-run task staleness (Windows-only; skip elsewhere silently).
    try:
        from .introvideo import autorun_status
        st = autorun_status()
        if st.registered and st.stale:
            parent.children.append(Check(
                name="auto-run", status=Status.WARN,
                detail="logon task is stale (points at an old install)",
                fix="spindoctor introvideo install-autorun --apply",
            ))
    except Exception:  # noqa: BLE001 — NotSupportedError off-Windows, etc.
        pass

    parent.status = _worst(c.status for c in parent.children)
    return parent


@dataclass
class _HelperFolder:
    """A folder `install-tools` may have written its .bat helpers to."""

    folder: Path
    system: Optional[str] = None   # the --add-to-system wheel, None for the Tools menu
    wired: bool = False            # a PCLauncher module INI section runs a .bat here
    system_default: bool = False   # where --add-to-system writes without --output-dir


def _rl_local_path(value: str, rl_dir: Path) -> Optional[Path]:
    """A path from a RocketLauncher INI as a local path (a relative one from the
    RocketLauncher folder); None for an absolute Windows path checked off Windows."""
    from pathlib import PureWindowsPath

    pw = PureWindowsPath(value)
    if pw.drive:
        return Path(os.path.normpath(value)) if os.name == "nt" else None
    if os.path.isabs(value):
        return Path(os.path.normpath(value))
    return Path(os.path.normpath(os.path.join(str(rl_dir), *pw.parts)))


def _install_tools_folders(rl_dir: Path) -> list[_HelperFolder]:
    """Every folder `install-tools` writes its helpers to that can be found.

    The Tools-menu default first, then for each PCLauncher system (a
    ``Modules\\PCLauncher\\<System>.ini`` module INI or ``<System>\\`` folder)
    the folders ``--add-to-system`` uses: those of the ``.bat`` files its
    module INI's helper sections run, the first ``Rom_Path`` entry of
    ``Settings\\<System>\\Emulators.ini`` (where a run without ``--apply``
    leaves the ``.bat`` files too) and ``Modules\\PCLauncher\\<System>\\``.
    """
    from .toolkit_helpers import ALL_NAMES

    tool_sections = {n.lower() for n in ALL_NAMES}
    out = [_HelperFolder(rl_dir / "Modules" / "HyperLaunch" / "Tools" / "spindoctor")]
    pcl = rl_dir / "Modules" / "PCLauncher"
    try:
        with os.scandir(pcl) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        entries = []
    systems: dict[str, str] = {}
    for entry in entries:
        if entry.is_dir():
            systems.setdefault(entry.name.lower(), entry.name)
        elif entry.name.lower().endswith(".ini"):
            systems.setdefault(entry.name[:-4].lower(), entry.name[:-4])
    for system in systems.values():
        for name, values in _read_rl_ini(pcl / f"{system}.ini").items():
            app = values.get("application", "")
            if name in tool_sections and app.lower().endswith(".bat"):
                bat = _rl_local_path(app, rl_dir)
                if bat is not None:
                    out.append(_HelperFolder(bat.parent, system, wired=True))
        rom_path = next((v["rom_path"] for v in _read_rl_ini(
            rl_dir / "Settings" / system / "Emulators.ini").values() if v.get("rom_path")), "")
        first = rom_path.split("|")[0].strip()
        default = _rl_local_path(first, rl_dir) if first else pcl / system
        if default is not None:
            out.append(_HelperFolder(default, system, system_default=True))
        if first:
            out.append(_HelperFolder(pcl / system, system))
    return out


def _bat_programs(bat: Path) -> list[str]:
    """The quoted ``.exe`` paths a ``.bat`` file runs, in order, comments skipped.

    Matches every format `install-tools` has written: v3's ``start "" /B /WAIT
    "<exe>" --run-tool spindoctor-fav …``, the per-tool ``"<install
    folder>\\spindoctor-fav.exe"`` of v2, with or without ``start``.  A source
    install's helpers call bare names from PATH and have none.
    """
    import re

    try:
        text = _read_windows_text(bat)
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip().lstrip("@").strip()
        low = s.lower()
        if low.startswith("::") or low == "rem" or low.startswith(("rem ", "rem\t")):
            continue
        for exe in re.findall(r'"([^"]+?\.exe)"', s, flags=re.IGNORECASE):
            if exe not in out:
                out.append(exe)
    return out


def check_refresh_helpers(config: Config) -> Check:
    """Do the .bat helpers `install-tools` wrote still find SpinDoctor?

    They run SpinDoctor by full path: v3 ``"<the EXE that ran install-tools>"
    --run-tool spindoctor-fav …``, v2 ``"<install folder>\\spindoctor-fav.exe"``.
    Portable installs unzip each release into a new folder, so once the old
    one is gone every helper fails, from the Tools menu, a Toolkit wheel or a
    scheduled task, and the wheels stop refreshing while nothing else looks
    wrong.  Re-running `install-tools` the same way, with the same helpers,
    rewrites them.  Reads only the ``.bat`` files and RocketLauncher INIs;
    diagnosis only.
    """
    if not config.rocketlauncher_dir:
        return Check(name="SpinDoctor helpers", status=Status.INFO,
                     detail="rocketlauncher_dir not set; skipping")
    from pathlib import PureWindowsPath

    from . import toolkit_helpers as th

    # One row per folder; what two finds of the same wheel's folder say is merged.
    merged: dict[str, _HelperFolder] = {}
    for hf in _install_tools_folders(Path(config.rocketlauncher_dir)):
        key = os.path.normcase(os.path.normpath(str(hf.folder)))
        first = merged.setdefault(key, hf)
        if first is not hf and first.system is not None and first.system.lower() == (hf.system or "").lower():
            first.wired |= hf.wired
            first.system_default |= hf.system_default
    parent = Check(name="SpinDoctor helpers", status=Status.OK)
    for hf in merged.values():
        bats = [hf.folder / f"{stem}.bat" for stem in sorted(th.ALL_NAMES)
                if (hf.folder / f"{stem}.bat").is_file()]
        if not bats:
            continue
        missing: list[str] = []
        present: list[str] = []
        broken = 0
        for bat in bats:
            bad = False
            for exe in _bat_programs(bat):
                if "%" in exe:
                    continue  # an environment variable: can't be checked here
                if not PureWindowsPath(exe).drive and not os.path.isabs(exe):
                    exe = os.path.normpath(os.path.join(str(bat.parent), exe))
                exists = _pc_app_exists(exe)
                if exists is False:
                    bad = True
                    if exe not in missing:
                        missing.append(exe)
                elif exists and exe not in present:
                    present.append(exe)
            broken += bad
        name = hf.system or "Tools menu"
        where = f"{len(bats)} helper(s) in {hf.folder}"
        if missing:
            # Re-run install-tools the way it was run: same helpers (a renamed
            # one as its new name), same folder, same wheel.
            names = {th.RENAMED.get(b.stem, b.stem) for b in bats}
            fix = "spindoctor install-tools " + th.tool_option(
                [h for h in th.HELPERS if h.name in names])
            if hf.system is not None:
                if not hf.system_default:
                    fix += f' --output-dir "{hf.folder}"'
                fix += f' --add-to-system "{hf.system}"' + (" --apply" if hf.wired else "")
            if len(missing) == 1:
                detail = f"{broken} of {where} run {missing[0]}, which no longer exists"
            else:
                detail = (f"{broken} of {where} run programs that no longer exist "
                          f"({missing[0]} and {len(missing) - 1} more)")
            parent.children.append(Check(name=name, status=Status.WARN, detail=detail, fix=fix))
        elif present:
            more = f" and {len(present) - 1} more" if len(present) > 1 else ""
            parent.children.append(Check(
                name=name, status=Status.OK, detail=f"{where} run {present[0]}{more}",
            ))
        else:
            parent.children.append(Check(
                name=name, status=Status.INFO,
                detail=f"{where} run no program that can be checked here (commands from PATH)",
            ))
    if not parent.children:
        return Check(name="SpinDoctor helpers", status=Status.INFO,
                     detail="no install-tools helpers found (optional)")
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_idle_tour(config: Config) -> Check:
    """Will the idle tour start with HyperSpin, and see what it needs?

    `install-tools --tool idle-tour --apply` adds ``Idle Tour.bat`` to the
    ``[Startup]`` list of HyperSpin's Startup Script, which stops at the first
    missing number.  The tour changes wheels only while HyperSpin's own idle
    mode runs (``Settings\\Settings.ini`` ``[AttractMode] Active=true``) and
    reads where HyperSpin is from its LEDBlinky calls in ``log.txt``
    (``[LEDBlinky] Active=true``).  Diagnosis only.
    """
    from . import startup_script as ss
    from . import toolkit_helpers as th
    from ._text import read_editable_text
    from .idle_tour import SETTINGS_FILE, hyperspin_setting, other_tours, read_settings, single_mode

    name = "Idle tour"
    bat_name = f"{th.find('idle-tour').name}.bat"
    install = "spindoctor install-tools --tool idle-tour --apply"
    script = ss.find(config.hyperspin_dir)
    items = ss.entries(read_editable_text(script.path)) if script.path else []
    entry = next((e for e in items if e.target.strip().strip('"').lower() == bat_name.lower()), None)
    menu_bat = (Path(config.rocketlauncher_dir) / "Modules" / "HyperLaunch" / "Tools" / "spindoctor"
                / bat_name) if config.rocketlauncher_dir else None
    if entry is None and not (menu_bat is not None and menu_bat.is_file()):
        return Check(name=name, status=Status.INFO, detail="not installed (optional)")

    parent = Check(name=name, status=Status.OK)
    row = "Startup Script"
    if entry is None:
        if script.path is None:
            parent.children.append(Check(
                name=row, status=Status.WARN,
                detail=f"{menu_bat} is there, but nothing starts it: {script.problem}",
                fix=f"have HyperSpin's startup program run {bat_name} (hidden) each time HyperSpin starts"))
        else:
            parent.children.append(Check(
                name=row, status=Status.WARN,
                detail=f"{script.path.name} doesn't start {bat_name}", fix=install))
    else:
        last = ss.runs_to(items)
        # The Startup Script runs each entry from its folder, its own when relative.
        folder = Path(entry.working_dir.strip().strip('"') or ".")
        if not folder.is_absolute():
            folder = script.path.parent / folder
        target = Path(entry.target.strip().strip('"'))
        bat = target if target.is_absolute() else folder / target
        gone = [exe for exe in (_bat_programs(bat) if bat.is_file() else [])
                if "%" not in exe and _pc_app_exists(exe) is False]
        if entry.number > last:
            parent.children.append(Check(
                name=row, status=Status.WARN,
                detail=(f"[Startup] entry {entry.number} comes after a gap at {last + 1}: the Startup "
                        "Script stops at the first missing number, so the tour never starts"),
                fix=f"number the [Startup] entries in {script.path} 1, 2, 3 … without gaps"))
        elif _pc_app_exists(str(bat)) is False:
            parent.children.append(Check(
                name=row, status=Status.WARN,
                detail=f"[Startup] entry {entry.number} runs {bat}, which doesn't exist", fix=install))
        elif gone:
            # SpinDoctor moved or upgraded into a new folder: rewrite the .bat where it is.
            fix = "spindoctor install-tools --tool idle-tour"
            if menu_bat is None or (os.path.normcase(str(bat.resolve()))
                                    != os.path.normcase(str(menu_bat.resolve()))):
                fix += f' --output-dir "{bat.parent}"'
            parent.children.append(Check(
                name=row, status=Status.WARN,
                detail=f"{bat.name} runs {gone[0]}, which no longer exists", fix=fix))
        else:
            parent.children.append(Check(
                name=row, status=Status.OK,
                detail=f"starts it with HyperSpin ([Startup] entry {entry.number} in {script.path.name})"))
            settings_file = bat.parent / SETTINGS_FILE
            if not read_settings(settings_file).enabled:
                parent.children.append(Check(
                    name="Settings", status=Status.INFO,
                    detail=f"switched off (Enabled=0 in {settings_file})"))
    attract = hyperspin_setting(config.hyperspin_dir, "AttractMode", "Active")
    if attract.strip().lower() != "true":
        parent.children.append(Check(
            name="HyperSpin idle mode", status=Status.WARN,
            detail=(f"off ([AttractMode] Active={attract or '(not set)'}): the tour only changes "
                    "wheels while it runs"),
            fix="Settings\\Settings.ini [AttractMode] Active=true (edit it with HyperSpin closed)"))
    else:
        wait = hyperspin_setting(config.hyperspin_dir, "AttractMode", "Time")
        parent.children.append(Check(
            name="HyperSpin idle mode", status=Status.OK,
            detail=f"on, after {wait} s with no input" if wait else "on"))
    led = hyperspin_setting(config.hyperspin_dir, "LEDBlinky", "Active")
    if led.strip().lower() != "true":
        parent.children.append(Check(
            name="LEDBlinky calls", status=Status.WARN,
            detail=(f"off ([LEDBlinky] Active={led or '(not set)'}): HyperSpin's log.txt then shows "
                    "no selections or idle spins, so the tour does nothing"),
            fix="Settings\\Settings.ini [LEDBlinky] Active=true (edit it with HyperSpin closed)"))
    single = single_mode(config.hyperspin_dir)
    if single:
        parent.children.append(Check(
            name="HyperSpin menu mode", status=Status.WARN,
            detail=f"{single}, so the tour presses nothing",
            fix="Settings\\Settings.ini [Main] Menu_Mode=multi, or uninstall-tools --tool idle-tour --apply"))
    others = other_tours(items, bat_name)
    if others:
        parent.children.append(Check(
            name="Another idle tour", status=Status.WARN,
            detail=(f"{script.path.name} also starts {others[0]}: two tours press keys over "
                    "each other"),
            fix=f"take one of them out of [Startup] in {script.path}"))
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_orphan_media(config: Config) -> Check:
    """Report leftover media files with no matching game (disk bloat).

    Diagnosis only, and INFO severity — orphan media doesn't break anything, it
    just wastes space.  Deleting is destructive, so this never touches files
    (doctor's contract is "never deletes ROMs/DBs/media"); it points at
    ``find-orphan-media``, which has its own preview and ``--apply`` gate.
    """
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name="Orphan media", status=Status.INFO,
                     detail="hyperspin_dir not configured; skipping")

    from .orphan_media import find_orphan_media

    total = 0
    systems_hit = 0
    for system in get_systems(config):
        try:
            n = len(find_orphan_media(system, config).orphans)
        except Exception:  # noqa: BLE001 — a bad DB is check_databases' problem
            continue
        if n:
            total += n
            systems_hit += 1

    if total == 0:
        return Check(name="Orphan media", status=Status.OK, detail="none")
    return Check(
        name="Orphan media", status=Status.INFO,
        detail=f"{total} orphan media file(s) across {systems_hit} system(s) — disk bloat",
        fix="spindoctor find-orphan-media --all   (preview; add --apply to remove)",
    )


# ─── orchestration ────────────────────────────────────────────────────────────


def run_health_checks(config: Config, fix: bool = False) -> HealthReport:
    report = HealthReport()

    def _safe(name: str, fn) -> None:
        """Run one check; a crash becomes a FAIL row, never a doctor crash.

        `doctor` is the tool you reach for *because* something is wrong, so a
        single check hitting an unexpected condition (a locked file, a
        permission error, a malformed INI it didn't anticipate) must not take
        down the whole report.
        """
        try:
            report.add(fn())
        except Exception as e:  # noqa: BLE001
            report.add(Check(
                name=name, status=Status.FAIL,
                detail=f"check crashed: {type(e).__name__}: {e}",
            ))

    _safe("Paths", lambda: check_paths(config))
    _safe("External binaries", lambda: check_binaries(config))
    _safe("lxml", check_lxml)
    _safe("Archive support", check_archive_support)
    _safe("Preview support", check_preview_support)
    _safe("HyperSpin databases", lambda: check_databases(config))
    _safe("Wheel wiring", lambda: check_wheel_wiring(config, fix, report.fixes_applied))
    _safe("PC games", lambda: check_pc_launchability(config))
    _safe("ROM paths", lambda: check_rom_paths(config))
    _safe("HyperSpin ROMs only", lambda: check_hyperspin_roms_only(config))
    _safe("Spaces in game names", lambda: check_game_name_spaces(config))
    _safe("Match cache", lambda: check_match_cache(config, fix, report.fixes_applied))
    _safe("Global Emulators.ini", lambda: check_global_emulators(config, fix, report.fixes_applied))
    _safe("RocketLauncher settings", lambda: check_rocketlauncher_settings(config))
    _safe("Lightguns", lambda: check_lightguns(config))
    _safe("Emulator ROM folders", lambda: check_emulator_rom_paths(config))
    _safe("Daphne keys", lambda: check_daphne_keys(config))
    _safe("User Functions", lambda: check_user_functions(config))
    _safe("Coin/Start", lambda: check_coin_start(config))
    _safe("MAME key maps", lambda: check_mame_key_maps(config))
    _safe("LEDBlinky", lambda: check_ledblinky(config))
    _safe("LED coverage", lambda: check_led_coverage(config))
    _safe("Intro video", lambda: check_intro_video(config))
    _safe("SpinDoctor helpers", lambda: check_refresh_helpers(config))
    _safe("Idle tour", lambda: check_idle_tour(config))
    _safe("Orphan media", lambda: check_orphan_media(config))
    _safe("Metadata APIs", lambda: check_api_creds(config))
    _safe("Media folders", lambda: check_media_skeletons(config, fix, report.fixes_applied))
    return report
