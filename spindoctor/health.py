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
from .rl_rom_paths import _RomLookup, _RomPick, _RomSource, _raw_game_names, _resolve_rom_path, _wheel_games
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

    # Search/Genre/Favorites hook scan — a LedBlinky process hook in a menu's
    # Settings.ini starts or stops LEDBlinky.exe as that menu opens or closes.
    # LEDBlinkyControls.xml isn't consulted: LedBlinky never looks these menus
    # up there, so a missing entry for them is no risk.
    try:
        scan_res = scan(config, menus=SEARCH_MENU_NAMES)
    except Exception:  # noqa: BLE001 — a scan failure must not sink doctor
        scan_res = None
    if scan_res is not None:
        hooked = [mi["menu"] for mi in scan_res["menu_inis"] if mi["has_hooks"]]
        if hooked:
            parent.children.append(Check(
                name="Search/Genre/Favorites", status=Status.WARN,
                detail=f"LedBlinky process hook in the {', '.join(hooked)} menu Settings.ini",
                fix=f"spindoctor ledblinky fix --apply --menus {','.join(hooked)}",
            ))
        else:
            parent.children.append(Check(
                name="Search/Genre/Favorites", status=Status.OK,
                detail="no LedBlinky hooks in the menus' Settings.ini",
            ))

    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_api_creds(config: Config) -> Check:
    from .scraper import _SCREENSCRAPER_PLACEHOLDER_DEVIDS, SCREENSCRAPER_DEVELOPER_REQUEST_URL

    parent = Check(name="Metadata APIs", status=Status.OK)
    placeholder_devid = (config.screenscraper_devid or "") in _SCREENSCRAPER_PLACEHOLDER_DEVIDS
    if config.screenscraper_user and config.screenscraper_pass and placeholder_devid:
        # ScreenScraper refuses the bundled developer ID on every request,
        # whatever the user login, so a set login alone isn't "OK".
        parent.children.append(Check(
            name="ScreenScraper", status=Status.WARN,
            detail=(f"user: {config.screenscraper_user}; developer ID is the bundled "
                    "placeholder, which ScreenScraper refuses (HTTP 403)"),
            fix=(f"ask ScreenScraper for a developer ID on its forum ({SCREENSCRAPER_DEVELOPER_REQUEST_URL}), "
                 "then: spindoctor config set screenscraper_devid <id> "
                 "and screenscraper_devpassword <password>"),
        ))
    elif config.screenscraper_user and config.screenscraper_pass:
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


# ─── PCLauncher INI text ─────────────────────────────────────────────────────
#
# PCLauncher waits for a game's window by ``FadeTitle`` (a title, often with
# ``ahk_class``).  RocketLauncher's AutoHotkey is an ANSI build: it compares
# the INI's raw bytes with the window title in the PC's code page, so a
# Japanese title is kept as its Shift-JIS bytes (on a Western PC they show as
# ``‚a‚`‚s‚s‚k‚d``).  An editor that re-saves the INI as UTF-8 swaps every
# byte it can't read for U+FFFD (``EF BF BD``): the bytes are gone, the window
# is never found, and RocketLauncher gives up with "There was an error waiting
# for the window" while the game runs behind the fade screen.

_UTF8_REPLACEMENT = b"\xef\xbf\xbd"


def _ini_lost_characters(path: Path) -> list[tuple[str, str]]:
    """``(section, key)`` of every line in *path* holding U+FFFD.

    Works on the raw bytes: decoding with ``errors="replace"`` would turn every
    intact Shift-JIS or cp1252 title into U+FFFD as well.  A UTF-16 INI (BOM)
    is decoded first.  Comment lines don't count; a damaged section name is
    reported with an empty key.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError:
            return []
        rows = [(line, "�" in line) for line in text.splitlines()]
    else:
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        rows = [(raw.decode("utf-8", errors="replace"), _UTF8_REPLACEMENT in raw) for raw in data.splitlines()]
    hits: list[tuple[str, str]] = []
    section = ""
    for line, lost in rows:
        s = line.strip().lstrip("﻿")
        if s.startswith("[") and "]" in s:
            section = s[1:s.index("]")].strip()
            if lost:
                hits.append((section, ""))
            continue
        if not lost or s.startswith((";", "#")):
            continue
        hits.append((section, s.split("=", 1)[0].strip()))
    return hits


def check_pclauncher_ini_text(config: Config) -> Check:
    """WARN for PCLauncher module INI values that lost bytes in a UTF-8 re-save.

    Looks at the INIs RocketLauncher reads for the wheels on the Main Menu:
    ``Modules\\PCLauncher\\PCLauncher.ini``, ``<System>.ini`` (the per-system
    module INI with a ``[<game>]`` section per game) and ``<System>\\*.ini``
    (per-game INIs), one ``os.scandir`` per folder.  Other INIs there (old
    ``... BACKUP.ini`` copies, removed wheels) are left alone, and so are the
    sections and per-game INIs of games the wheel's database doesn't list
    (when it lists any).  With no Main Menu it looks at every INI in the folder.

    Diagnosis only: the lost bytes can't be worked out from what is left, so
    the fix names the values to put back.
    """
    name = "PCLauncher INI text"
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO, detail="rocketlauncher_dir not configured; skipping")
    pcl = Path(config.rocketlauncher_dir) / "Modules" / "PCLauncher"
    try:
        entries = {e.name.lower(): e for e in os.scandir(pcl)}
    except OSError:
        return Check(name=name, status=Status.INFO, detail="no PCLauncher module folder")

    from .rocketlauncher import _win_safe_stem

    wheels: list[str] = []
    if config.hyperspin_dir:
        wheels = _main_menu_wheels(Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml")
    if wheels:
        groups = [("PCLauncher.ini", None, ["pclauncher.ini"], [])] + [
            (w, w, [f"{w}.ini".lower()], [w.lower()]) for w in wheels
        ]
    else:
        groups = [(e.name, None, [k], []) for k, e in sorted(entries.items()) if e.is_file() and k.endswith(".ini")]
        groups += [(e.name, None, [], [k]) for k, e in sorted(entries.items()) if e.is_dir()]

    parent = Check(name=name, status=Status.OK)
    checked = 0
    for label, wheel, files, folders in groups:
        games: set[str] = set()
        if wheel and any(k in entries for k in files + folders):
            try:
                games = {g.lower() for g in load_database(wheel, config.databases_dir).games().keys()}
            except Exception:  # noqa: BLE001 — DB integrity is check_databases' job
                games = set()
        stems = {_win_safe_stem(g).lower() for g in games}
        found: list[str] = []
        paths: list[tuple[Path, str, bool]] = []  # (path, shown name, per-system module INI)
        for key in files:
            e = entries.get(key)
            if e is not None and e.is_file():
                paths.append((Path(e.path), e.name, True))
        for key in folders:
            e = entries.get(key)
            if e is None or not e.is_dir():
                continue
            try:
                inis = sorted((f for f in os.scandir(e.path) if f.is_file() and f.name.lower().endswith(".ini")),
                              key=lambda f: f.name.lower())
            except OSError:
                continue
            paths += [(Path(f.path), f"{e.name}\\{f.name}", False) for f in inis
                      if not stems or f.name[:-4].lower() in stems]
        for path, shown, module_ini in paths:
            checked += 1
            for section, key in _ini_lost_characters(path):
                # A [<game>] section RocketLauncher never reads can't break a launch
                # (a section name that lost characters itself is always shown).
                if (module_ini and games and section and "�" not in section
                        and section.lower() not in games | {"settings"}):
                    continue
                where = f"[{section}] {key}".rstrip() if section else key
                found.append(f"{shown} {where}")
        if found:
            more = f" (+{len(found) - 3} more)" if len(found) > 3 else ""
            parent.children.append(Check(
                name=label, status=Status.WARN,
                detail=(f"{len(found)} value(s) lost characters (U+FFFD), so RocketLauncher can't match them: "
                        + "; ".join(found[:3]) + more),
                fix=("put back each listed value's original bytes: copy the line from a backup of the INI, or "
                     "retype the window title in an editor that saves in the PC's ANSI code page (not UTF-8)"),
            ))

    if not parent.children:
        parent.detail = f"{checked} INI(s) OK" if checked else "no PCLauncher INIs for the Main Menu's wheels"
        if not checked:
            parent.status = Status.INFO
    else:
        parent.status = _worst(c.status for c in parent.children)
    return parent


# ─── PC game programs ────────────────────────────────────────────────────────
#
# A program that needs a DLL which isn't there never starts: Windows' loader
# ends it at once with STATUS_DLL_NOT_FOUND (0xC0000135) and shows a "System
# Error ... was not found" box naming the DLL (logged as System event 26,
# "Application Popup").  That happens when RocketLauncher starts the program
# too, and on a cabinet the box can open behind the frontend, so the screen
# looks frozen.  Every other check passes such a game: its INI and its
# program are there.  Antivirus quarantine is a common cause (replaced or
# emulated Steam DLLs, steam_api.dll above all), and so is a runtime the game
# expects Windows to have (OpenAL, Games for Windows Live's xlive.dll).  A
# WorkingFolder that doesn't hold the program stops the launch earlier, with
# AutoHotkey's "Failed attempt to launch program or document".

_PCLAUNCHER_MODULE = "pclauncher.ahk"

# The module INI keys PCLauncher starts a program from (Application last
# reads as the game's own; the others run around it).
_PCLAUNCHER_PROGRAM_KEYS = ("Application", "PreLaunch", "PostLaunch", "PostExit")

# Microsoft's C/C++ runtimes that come from side-by-side assemblies
# (``%windir%\\WinSxS`` or a ``Microsoft.VC90.CRT`` folder beside the program)
# rather than the system folder.
_SXS_RUNTIME_PREFIXES = ("msvcr", "msvcp", "msvcm", "mfc", "atl", "vcomp")


@dataclass
class _PeImage:
    """What the loader needs from one Windows program or DLL."""
    bits: int                 # 32 or 64
    imports: list[str]        # statically imported DLLs, as the import table spells them


def _pe_image(path: Path) -> Optional[_PeImage]:
    """The bitness and import table of the PE file at *path*; None when it
    isn't one (a ``.bat``, an ``.ahk``, a damaged file).

    Reads only the headers, the section table and the import directory, so a
    200 MB game program costs a few small reads.  Delay-loaded DLLs aren't in
    the import table: the program loads those when it first uses them."""

    def u16(b: bytes, at: int) -> int:
        return int.from_bytes(b[at:at + 2], "little")

    def u32(b: bytes, at: int) -> int:
        return int.from_bytes(b[at:at + 4], "little")

    try:
        with open(path, "rb") as fh:
            def read(offset: int, size: int) -> bytes:
                fh.seek(offset)
                return fh.read(size)

            dos = read(0, 64)
            if len(dos) < 64 or dos[:2] != b"MZ":
                return None
            pe = u32(dos, 60)
            head = read(pe, 24)
            if len(head) < 24 or head[:4] != b"PE\0\0":
                return None
            sections, opt_size = u16(head, 6), u16(head, 20)
            opt = read(pe + 24, opt_size)
            magic = u16(opt, 0)
            if magic == 0x10B:
                bits, dirs = 32, 96
            elif magic == 0x20B:
                bits, dirs = 64, 112
            else:
                return None
            # NumberOfRvaAndSizes sits just before the data directories; the
            # import table is directory 1.
            if len(opt) < dirs + 16 or u32(opt, dirs - 4) < 2:
                return _PeImage(bits, [])
            table_rva = u32(opt, dirs + 8)
            raw = read(pe + 24 + opt_size, 40 * sections)
            spans = []
            for i in range(len(raw) // 40):
                s = raw[40 * i:40 * i + 40]
                spans.append((u32(s, 12), max(u32(s, 8), u32(s, 16)), u32(s, 20)))

            def offset(rva: int) -> Optional[int]:
                for va, size, start in spans:
                    if va <= rva < va + size:
                        return rva - va + start
                return None

            names: list[str] = []
            seen: set[str] = set()
            at = offset(table_rva) if table_rva else None
            while at is not None and len(seen) < 4096:
                entry = read(at, 20)
                if len(entry) < 20 or u32(entry, 12) == 0:
                    break  # the all-zero entry that ends the table
                where = offset(u32(entry, 12))
                if where is not None:
                    name = read(where, 256).split(b"\0", 1)[0].decode("ascii", errors="replace").strip()
                    if name and name.lower() not in seen:
                        seen.add(name.lower())
                        names.append(name)
                at += 20
            return _PeImage(bits, names)
    except OSError:
        return None


def _windows_dir() -> Optional[Path]:
    """``%SystemRoot%`` (``%windir%``) when it is a folder, else None."""
    for var in ("SystemRoot", "windir"):
        value = os.environ.get(var, "")
        if value and Path(value).is_dir():
            return Path(value)
    return None


@dataclass
class _PcProgram:
    """One program PCLauncher starts for a game, and what it lacks."""
    game: str
    key: str                  # Application / PreLaunch / PostLaunch / PostExit
    path: Path
    ini: Optional[Path]       # the module INI the key came from
    bits: int = 0
    missing: list[str] = field(default_factory=list)        # "steam_api.dll" or "binkw32.dll (for x.dll)"
    wrong_bits: list[str] = field(default_factory=list)     # "x.dll is 64-bit"
    plugins: list[str] = field(default_factory=list)        # Unity plugin DLLs' missing DLLs
    loaded: set[str] = field(default_factory=set)            # own DLLs the loader loads up front (normcase)


class _DllSearch:
    """Where Windows' loader finds a program's DLLs, in its order (safe DLL
    search mode): the program's folder, the system folder for the program's
    bitness (``SysWOW64`` for a 32-bit program on 64-bit Windows, else
    ``System32``), the Windows folder, the folder the program starts in, then
    ``PATH``.  PCLauncher starts every program by its file name inside its
    start folder, so that is always the program's own folder here.
    ``api-ms-*`` / ``ext-ms-*`` names are API sets Windows maps itself, and
    Microsoft's C runtimes may come from side-by-side assemblies.  Every
    folder is listed once per run (:meth:`_RomLookup.listing`) and every file
    parsed once."""

    def __init__(self, look: _RomLookup, windows: Path):
        self.look = look
        self.windows = windows
        # A 32-bit Python on 64-bit Windows sees SysWOW64 under System32's name;
        # Sysnative is the real System32 then.
        native = windows / "Sysnative"
        self.system = {
            64: native if look.listing(native) is not None else windows / "System32",
            32: windows / "SysWOW64" if look.listing(windows / "SysWOW64") is not None else windows / "System32",
        }
        self.path = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
        self._images: dict[str, Optional[_PeImage]] = {}
        self._sxs: Optional[list[str]] = None

    def image(self, path: Path) -> Optional[_PeImage]:
        key = os.path.normcase(str(path))
        if key not in self._images:
            self._images[key] = _pe_image(path)
        return self._images[key]

    def _in(self, folder: Path, name: str) -> Optional[Path]:
        lst = self.look.listing(folder)
        real = lst[0].get(name.lower()) if lst is not None else None
        return folder / real if real is not None else None

    def _side_by_side(self, name: str, bits: int, home: Path) -> bool:
        """Whether *name* is a C runtime found as a side-by-side assembly: a
        ``Microsoft.*`` folder beside the program, or ``WinSxS``."""
        if not name.lower().startswith(_SXS_RUNTIME_PREFIXES):
            return False
        lst = self.look.listing(home)
        if lst is not None and any(self._in(home / sub, name) for low, sub in lst[1].items()
                                   if low.startswith("microsoft.")):
            return True
        if self._sxs is None:
            sxs = self.look.listing(self.windows / "WinSxS")
            self._sxs = [real for low, real in (sxs[1].items() if sxs else [])
                         if low.startswith(("x86_microsoft.vc", "amd64_microsoft.vc"))]
        arch = "x86_" if bits == 32 else "amd64_"
        return any(self._in(self.windows / "WinSxS" / sub, name)
                   for sub in self._sxs if sub.lower().startswith(arch))

    def find(self, name: str, bits: int, home: Path, first: Optional[Path] = None,
             ) -> tuple[Optional[Path], bool]:
        """``(file, own)``: where the loader finds DLL *name* for a *bits*-bit
        program in *home* (*first*: a folder searched before the rest, a
        Unity plugin's own), and whether that is one of the game's own
        folders.  ``(None, False)`` when it is nowhere."""
        low = name.lower()
        if low.startswith(("api-ms-", "ext-ms-")):
            return self.system[bits] / name, False
        for folder, own in ([(first, True)] if first else []) + [
            (home, True), (self.system[bits], False), (self.windows, False),
        ] + [(p, False) for p in self.path]:
            hit = self._in(folder, name)
            if hit is not None:
                return hit, own
        if self._side_by_side(name, bits, home):
            return self.windows / "WinSxS" / name, False
        return None, False

    def on_search_path(self, name: str) -> bool:
        """Whether Windows finds the program *name* by its bare name outside
        the start folder: in the system folders, the Windows folder or
        ``PATH`` (``notepad.exe``)."""
        return any(self._in(folder, name) is not None
                   for folder in [self.system[64], self.system[32], self.windows] + self.path)

    def check(self, program: _PcProgram, image: _PeImage) -> None:
        """Fill *program*'s ``missing`` / ``wrong_bits``: every DLL the program
        imports, and every DLL those of its own folders import in turn (the
        loader loads them all before the program runs)."""
        home = program.path.parent
        queue = [(program.path, image)]
        done = program.loaded
        done.add(os.path.normcase(str(program.path)))
        while queue:
            path, img = queue.pop(0)
            needer = "" if path == program.path else f" (for {path.name})"
            for name in img.imports:
                hit, own = self.find(name, image.bits, home)
                if hit is None:
                    program.missing.append(name + needer)
                    continue
                if not own or os.path.normcase(str(hit)) in done:
                    continue
                done.add(os.path.normcase(str(hit)))
                dll = self.image(hit)
                if dll is None:
                    continue
                if dll.bits != image.bits:
                    program.wrong_bits.append(f"{hit.name} is {dll.bits}-bit")
                    continue
                queue.append((hit, dll))

    def unity_plugins(self, program: _PcProgram, image: _PeImage) -> bool:
        """Whether *program* is a Unity game (a ``<program>_Data`` folder
        beside it), filling ``plugins`` for one.

        Unity games load their native plugins while running: the DLLs in
        ``<program>_Data\\Plugins`` (or its ``x86`` / ``x86_64`` folder), and
        DLLs beside the program that it doesn't import, so the import table
        doesn't name them.  ``plugins`` gets the DLLs those import that are
        nowhere (looked for beside the plugin first, as Unity's Mono loads
        them, and among the game's other plugins).  Call after :meth:`check`."""
        home = program.path.parent
        data = home / f"{program.path.stem}_Data"
        if self.look.listing(data) is None:
            return False
        plugins = data / "Plugins"
        lst = self.look.listing(plugins)
        groups = []
        if lst is not None:
            arch = "x86" if image.bits == 32 else "x86_64"
            groups = [(f, self._dlls(f)) for f in [plugins] + ([plugins / lst[1][arch]] if arch in lst[1] else [])]
        groups.append((home, [p for p in self._dlls(home) if os.path.normcase(str(p)) not in program.loaded]))
        own = {p.name.lower() for _f, dlls in groups for p in dlls}
        for folder, dlls in groups:
            for plugin in dlls:
                img = self.image(plugin)
                if img is None or img.bits != image.bits:
                    continue  # the other bitness's copy, or not a DLL
                for name in img.imports:
                    if name.lower() in own:
                        continue
                    hit, _own = self.find(name, image.bits, home, first=None if folder == home else folder)
                    entry = f"{name} (for {plugin.name})"
                    if hit is None and entry not in program.plugins:
                        program.plugins.append(entry)
        return True

    def _dlls(self, folder: Path) -> list[Path]:
        lst = self.look.listing(folder)
        return [folder / real for low, real in sorted((lst[0] if lst else {}).items()) if low.endswith(".dll")]


def _is_uninstaller(path: Path) -> bool:
    """``unins000.exe`` (Inno Setup), ``uninstall.exe``, ``uninst.exe``…"""
    low = path.name.lower()
    return low.startswith("unins") and low.endswith(".exe")


def _pc_program_target(value: str) -> Optional[str]:
    """*value* (a PCLauncher program key) as a path to check, or None for a
    URL or Steam browser link (the module runs those as they are: it tests
    ``"http"`` / ``"ste"`` at the start, ignoring case)."""
    value = value.strip().strip('"').strip()
    if not value or value[:4].lower() == "http" or value[:3].lower() == "ste":
        return None
    return value


def _bare_file_name(value: str) -> bool:
    """Whether a program key names just a file (``setup.exe``), no folder."""
    from pathlib import PureWindowsPath

    pw = PureWindowsPath(value)
    return not pw.drive and not pw.root and len(pw.parts) == 1


def _on_unmounted_drive(value: str, look: _RomLookup) -> bool:
    """Whether *value* is on a drive that can't be listed now: one with no
    disc in it, or a virtual drive letter that exists only while mounted."""
    from pathlib import PureWindowsPath

    drive = PureWindowsPath(value).drive
    return bool(drive) and look.listing(Path(drive + "\\")) is None


def _wheel_pc_programs(
    system: str, look: _RomLookup, databases_dir: Path, search: Optional[_DllSearch],
) -> Optional[Check]:
    """One wheel's node for :func:`check_pc_game_programs`; None when none of
    its games starts through PCLauncher."""

    def pclauncher(src: Optional[_RomSource]) -> bool:
        module = look.module_file(src) if src is not None and not src.stops else None
        return module is not None and module.name.lower() == _PCLAUNCHER_MODULE

    overrides = look.game_overrides(system)
    own = look.source(system)
    if not pclauncher(own) and not any(
        pclauncher(look.source(other, emu) if other and other.lower() != system.lower()
                   else look.source(system, emu) or own)
        for emu, other in overrides.values()
    ):
        return None

    games, _raw = _wheel_games(system, databases_dir)
    node = Check(name=system, status=Status.OK)
    checked: set[str] = set()
    programs: list[_PcProgram] = []
    uninstallers: list[_PcProgram] = []
    absent: list[_PcProgram] = []
    misplaced: list[tuple[_PcProgram, str, Path, Optional[Path]]] = []  # (program, WorkingFolder, folder, its INI)
    other = 0           # Steam / URL / script (.ahk, .bat): no import table to read
    on_disc = 0         # on a DiscImage that is only there once PCLauncher mounts it
    unity = 0
    uncheckable = False
    for name in games:
        src, _other = look.game_source(system, name, overrides)
        if src is None or src.stops:
            continue  # RL stops before any module runs (the ROM paths check)
        module = look.module_file(src, name)
        if module is None or module.name.lower() != _PCLAUNCHER_MODULE or not look.exists(module):
            continue
        # PCLauncher reads each key with moduleIni.Read(dbName, key): the game's
        # own <System>\<game>.ini, then <System>.ini, then PCLauncher.ini.
        setting = {key: look.module_setting(module, src.system, name, [name], key)
                   for key in _PCLAUNCHER_PROGRAM_KEYS + ("SteamID", "WorkingFolder", "OriginGame", "DiscImage")}
        steam = bool(setting["SteamID"][0])
        if steam:
            other += 1  # Steam starts the game; the other keys still run
        folder = setting["WorkingFolder"][0].strip('"').strip()
        work = _resolve_rom_path(folder, look.rl_dir) if folder else None
        # Origin starts the game itself, and a DiscImage game's program may be
        # on the mounted disc: neither goes through the plain start below.
        disc = bool(setting["DiscImage"][0])
        plain = not setting["OriginGame"][0] and not disc
        read_any = False
        for key in _PCLAUNCHER_PROGRAM_KEYS:
            value, ini = setting[key]
            if key == "Application" and steam:
                continue
            target = _pc_program_target(value)
            if target is None:
                if value and key == "Application":
                    other += 1
                continue
            if disc and key == "Application" and _bare_file_name(target):
                # PCLauncher takes a bare Application name as the root of the
                # mounted image, not the RocketLauncher folder.
                on_disc += 1
                continue
            full = _resolve_rom_path(target, look.rl_dir)
            if full is None:
                uncheckable = True
                continue
            program = _PcProgram(name, key, full, ini)
            if key == "Application" and _is_uninstaller(full):
                uninstallers.append(program)
            if not look.exists(full):
                if disc and _on_unmounted_drive(target, look):
                    # PCLauncher mounts DiscImage before it looks for its
                    # programs, so one on the virtual drive is there by then.
                    on_disc += 1
                else:
                    absent.append(program)
                continue
            if key == "Application" and plain and work is not None:
                # RocketLauncher's Process.Run() starts it as
                #   Run, "<file name>", <WorkingFolder or the program's folder>
                # with no UseErrorLevel (PreLaunch/PostLaunch/PostExit always
                # start in their own folder), so the copy that runs is the one
                # in WorkingFolder, and with none there AutoHotkey stops the
                # module: "Failed attempt to launch program or document".
                lst = look.listing(work)
                there = lst[0].get(full.name.lower()) if lst is not None else None
                if there is not None:
                    program.path = full = work / there
                elif not look.exists(look.rl_dir / full.name) and not (
                        search is not None and search.on_search_path(full.name)):
                    misplaced.append((program, folder, work, setting["WorkingFolder"][1]))
            if search is None:
                continue
            image = search.image(full)
            if image is None:
                if key == "Application":
                    other += 1  # .ahk / .bat / .lnk: no import table
                continue
            program.bits = image.bits
            search.check(program, image)
            if key == "Application" and search.unity_plugins(program, image):
                unity += 1
            read_any = True
            if program.missing or program.wrong_bits or program.plugins:
                programs.append(program)
        if read_any:
            checked.add(name)

    def where(p: _PcProgram) -> str:
        return f"{p.game}: {p.path.name}" + ("" if p.key == "Application" else f" ({p.key})")

    total = len(checked)
    if misplaced:
        p, value, work, ini = misplaced[0]
        node.children.append(Check(
            name="Start folder", status=Status.FAIL,
            detail=(f"{len(misplaced)} game(s) won't start: PCLauncher starts the program by its file name "
                    "inside WorkingFolder, which doesn't hold it, so AutoHotkey stops the module with "
                    "\"Failed attempt to launch program or document\" and RocketLauncher waits for it "
                    "forever (the error box can sit behind the frontend): "
                    + _some([f"{g.game}: {g.path.name} isn't in {w}" for g, _v, w, _i in misplaced], 5)),
            fix=(f"Set WorkingFolder={p.path.parent} under [{p.game}] in {ini}, or remove the line (the "
                 "program then starts in its own folder). A game that must start somewhere else needs a "
                 "launcher (.bat) in that folder"),
        ))
    missing = [p for p in programs if p.missing]
    if missing:
        rows = [f"{where(p)} needs {', '.join(p.missing)}" for p in missing]
        games_hit = len({p.game for p in missing})
        node.children.append(Check(
            name="Missing DLLs", status=Status.FAIL,
            detail=(f"{games_hit}/{total} games have a program that can't start: it needs a DLL that isn't "
                    "there, so Windows ends it at once (0xC0000135) with a \"System Error ... was not "
                    "found\" box, also when RocketLauncher starts it. The program waits on that box, which "
                    f"on a cabinet can open behind the frontend, so the screen looks frozen. {_some(rows, 5)}"),
            fix=(f"Put each DLL back beside the program ({missing[0].path.parent}), from the game's own "
                 "install, or install the runtime it comes with (OpenAL, Games for Windows Live). "
                 "Antivirus quarantine is a common cause, especially of steam_api.dll: check its history "
                 "(and decide whether you trust the file) before restoring it. Windows logs each box as "
                 "System event 26 (\"Application Popup\")"),
        ))
    wrong = [p for p in programs if p.wrong_bits]
    if wrong:
        rows = [f"{where(p)} is {p.bits}-bit, {', '.join(p.wrong_bits)}" for p in wrong]
        node.children.append(Check(
            name="DLL bitness", status=Status.FAIL,
            detail=(f"{len({p.game for p in wrong})}/{total} games have a program that can't start: a DLL "
                    f"beside it is built for the other bitness (0xC000007B): {_some(rows, 5)}"),
            fix=f"Replace each DLL in {wrong[0].path.parent} with the game's own copy (same bitness as the program)",
        ))
    plugins = [p for p in programs if p.plugins]
    if plugins:
        rows = [f"{where(p)}: {', '.join(p.plugins)}" for p in plugins]
        node.children.append(Check(
            name="Unity plugins", status=Status.WARN,
            detail=(f"{len(plugins)}/{unity} Unity games have a plugin (in <program>_Data\\Plugins or beside "
                    "the program) that needs a DLL that isn't there. Unity loads plugins while the game runs, "
                    f"so it may stop or carry on without it: {_some(rows, 5)}"),
            fix=(f"Put each DLL back beside its plugin (e.g. in {plugins[0].path.parent}), from the game's own "
                 "install; antivirus quarantine is a common cause, especially of steam_api.dll"),
        ))
    if uninstallers:
        first = uninstallers[0]
        node.children.append(Check(
            name="Uninstaller", status=Status.WARN,
            detail=(f"{len(uninstallers)} game(s) start an uninstaller as their Application: "
                    + _some([f"{p.game} ({p.path.name})" for p in uninstallers], 5)),
            fix=f"Point Application under [{first.game}] in {first.ini} at the game's own program",
        ))
    if absent:
        node.children.append(Check(
            name="Programs not found", status=Status.INFO,
            detail=(f"{len(absent)} program(s) aren't there, so PCLauncher stops with \"Cannot find this "
                    f"...\" before they start: {_some([f'{where(p)} ({p.path})' for p in absent], 3)}"),
            fix=f"Fix the path in each game's module INI (e.g. {absent[0].key} under [{absent[0].game}] in {absent[0].ini})",
        ))

    notes = []
    if total and not any(c.status in (Status.FAIL, Status.WARN) for c in node.children):
        notes.append(f"{total} game(s) OK")
    elif total:
        notes.append(f"{total} game(s) read")
    if other:
        notes.append(f"{other} start through Steam, a URL or a script (no import table to read)")
    if on_disc:
        notes.append(f"{on_disc} program(s) are on a disc image PCLauncher mounts first (not read)")
    if search is None:
        notes.append("no Windows folder (SystemRoot), so DLLs weren't looked for")
    if uncheckable:
        notes.append("some paths use Windows drive letters; can't check them on this OS")
    if not total and not node.children and not other and not on_disc:
        node.status = Status.INFO
        notes.append("no programs to read")
    node.detail = "; ".join(notes)
    if node.children:
        node.status = _worst(c.status for c in node.children)
    return node


def check_pc_game_programs(config: Config) -> Check:
    """Will each PCLauncher game's program start?  FAIL when it needs a DLL
    that isn't there.

    For every game on a Main Menu wheel that launches with PCLauncher, the
    programs the module starts (``Application``, ``PreLaunch``, ``PostLaunch``,
    ``PostExit``) are read the way the module reads them, key by key
    (:meth:`_RomLookup.module_setting`: ``<System>\\<game>.ini``, then
    ``<System>.ini``, then ``PCLauncher.ini``; a relative path starts from the
    RocketLauncher folder).  Each program's import table is read, and each DLL
    it names is looked for where Windows' loader looks (:class:`_DllSearch`),
    following the DLLs of the game's own folders to theirs:

    * an ``Application`` its ``WorkingFolder`` doesn't hold is a FAIL:
      RocketLauncher starts it by its file name inside that folder, and
      AutoHotkey stops the module with "Failed attempt to launch program or
      document" (a copy found by its bare name in the RocketLauncher folder,
      Windows' folders or ``PATH`` would start instead, so that isn't flagged);
    * a DLL that is nowhere is a FAIL: Windows ends the program at once
      (0xC0000135) with a "System Error" box, which can open behind the
      frontend;
    * a DLL beside the program built for the other bitness is a FAIL (0xC000007B);
    * a Unity game's plugin (``<program>_Data\\Plugins``) that needs a missing
      DLL is a WARN: the game loads plugins while running, so the import
      table can't tell whether it stops;
    * an ``Application`` that is an uninstaller (``unins*.exe``) is a WARN.

    URLs, Steam (``SteamID``, ``steam://``) and scripts (``.ahk``, ``.bat``,
    which have no import table) are skipped, and so is a program on a
    ``DiscImage`` that isn't there until PCLauncher mounts it (a bare file
    name, or a drive that can't be listed now).  DLLs a program loads only while
    running (delay-loaded, or with ``LoadLibrary``) can't be seen.  Wheels
    switched off on the Main Menu are capped at INFO.  Diagnosis only.
    """
    name = "PC game programs"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO, detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO, detail="rocketlauncher_dir not configured; skipping")

    from .rocketlauncher import SKIP_GENERATE_CONFIG

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    look = _RomLookup(Path(config.rocketlauncher_dir))
    windows = _windows_dir()
    search = _DllSearch(look, windows) if windows is not None else None
    hidden = _hidden_main_menu_wheels(mm_path)
    parent = Check(name=name, status=Status.OK)
    for system in _main_menu_wheels(mm_path):
        if system in SKIP_GENERATE_CONFIG:
            continue
        node = _wheel_pc_programs(system, look, config.databases_dir, search)
        if node is None:
            continue
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)
    if not parent.children:
        return Check(name=name, status=Status.INFO, detail="no PCLauncher systems")
    parent.status = _worst(c.status for c in parent.children)
    return parent


# ─── Casual Games (PopCap / Big Fish Games) ──────────────────────────────────
#
# RocketLauncher's Casual Games module starts each game's own .exe: gamePath
# under [<romName>] in its module INIs, else <romPath>\<romName>.exe, else
# <romPath>\<romName>\<romName>.exe, with romPath and romName as RocketLauncher's
# ROM search left them.

_CASUAL_GAMES_MODULE = "casual games.ahk"

# Extensions the module refuses before it looks for the program
# (StringUtils.Contains(romExtension, "\.zip|\.7z|\.rar"), ignoring case).
_CASUAL_ARCHIVES = ("zip", "7z", "rar")


@dataclass
class _CasualGame:
    """One game's outcome in :func:`_casual_program`, kept for the report."""
    name: str
    outcome: str        # "ok", "fallback", "lost" or "unknown"
    game_path: str      # gamePath as written ("" = not set)
    ini: Optional[Path]  # the module INI it came from
    full: Optional[Path]  # gamePath as a full path
    module: Path


def _casual_program(
    look: _RomLookup, module: Path, system: str, game: str, rom_name: str, rom_dir: Optional[Path],
) -> _CasualGame:
    """What the Casual Games module (v2.0.x) does with one game.

    It reads gamePath under ``[<romName>]`` (:meth:`_RomLookup.module_setting`;
    a relative path starts from the RocketLauncher folder, as ``GetFullName``
    resolves it).  When that file is missing it tries
    ``<romPath>\\<romName>.exe`` and ``<romPath>\\<romName>\\<romName>.exe`` (its
    middle try, ``<romPath>\\`` + the first one's full path, can't name a real
    file).  The outcome is ``"ok"`` (gamePath is there), ``"fallback"`` (a
    fallback is), ``"lost"`` (nothing is: "Could not locate …") or
    ``"unknown"`` (gamePath can't be checked on this OS)."""
    value, ini = look.module_setting(module, system, game, [rom_name], "gamePath")
    full = _resolve_rom_path(value, look.rl_dir) if value else None
    if value and full is None:
        outcome = "unknown"
    elif full is not None and look.exists(full):
        outcome = "ok"
    elif rom_dir is not None and any(
        look.exists(p) for p in (rom_dir / f"{rom_name}.exe", rom_dir / rom_name / f"{rom_name}.exe")
    ):
        outcome = "fallback"
    else:
        outcome = "lost"
    return _CasualGame(game, outcome, value, ini, full, module)


def _is_casual_module(path: Optional[Path]) -> bool:
    return path is not None and path.name.lower() == _CASUAL_GAMES_MODULE


def _wheel_casual_games(system: str, look: _RomLookup, databases_dir: Path) -> Optional[Check]:
    """One wheel's node for :func:`check_casual_games`; None when none of its
    games starts through the Casual Games module."""

    def casual(src: Optional[_RomSource]) -> bool:
        return src is not None and not src.stops and _is_casual_module(look.module_file(src))

    overrides = look.game_overrides(system)
    own = look.source(system)
    if not casual(own) and not any(
        casual(look.source(other, emu) if other and other.lower() != system.lower()
               else look.source(system, emu) or own)
        for emu, other in overrides.values()
    ):
        return None

    games, raw = _wheel_games(system, databases_dir)
    node = Check(name=system, status=Status.OK)
    checked = unfound = 0
    uncheckable = False
    trapped: list[tuple[str, _RomPick, list[str]]] = []  # (game, RL's pick, extensions)
    archives: list[tuple[str, _RomPick]] = []
    lost: list[_CasualGame] = []
    stale: list[_CasualGame] = []
    for name in games:
        src, _other = look.game_source(system, name, overrides)
        if src is None or src.stops:
            continue  # RL stops before any module runs (the ROM paths check)
        rl_name = raw.get(name, name)  # RL gets the XML name exactly as written
        module = look.module_file(src, rl_name)
        if not _is_casual_module(module):
            continue
        if not src.checkable():
            uncheckable = True
            continue
        picked = look.pick(src, rl_name)
        if picked is None:
            if not look.skips_rom_check(src.system):
                unfound += 1  # "Cannot find Rom": the ROM paths check reports it
                continue
            # Under Skipchecks RL carries on with romPath set to the whole
            # Rom_Path, which names a folder only when it holds one.
            only = [f for _el, f in src.folders]
            result = _casual_program(look, module, src.system, rl_name, rl_name,
                                     only[0] if len(only) == 1 else None)
        else:
            # The module refuses an archive before it looks for the program.
            refused = picked.ext.lower().startswith(_CASUAL_ARCHIVES)
            if refused and not picked.by_ext:
                checked += 1
                archives.append((name, picked))
                continue
            result = None if refused else _casual_program(
                look, module, src.system, rl_name, picked.rom_name, picked.rom_dir)
            if result is None or (picked.by_ext and result.outcome == "lost"):
                # RL took another file in the game's folder as the game.  Found
                # by its own name (a <game>.txt placeholder), would it start?
                trapped.append((name, picked, src.exts))
                result = _casual_program(look, module, src.system, rl_name, rl_name, picked.folder)
        checked += 1
        if result.outcome == "unknown":
            uncheckable = True
        elif result.outcome == "lost":
            lost.append(result)
        elif result.outcome == "fallback" and result.game_path:
            stale.append(result)

    rom_path = own.folders[0][1] if own is not None and len(own.folders) == 1 else None
    each_game = (rom_path or Path("<Rom_Path>")) / "<game>"
    if trapped:
        first, pick, _exts = trapped[0]
        took = ", ".join(f"{g}: {p.rom_name}.{p.ext}" for g, p, _e in trapped[:3])
        more = f" and {len(trapped) - 3} more" if len(trapped) > 3 else ""
        # A placeholder only helps if RL reaches it before the stray file:
        # an extension no later in Rom_Extension than any game's stray one.
        last = min(e.index(p.ext) for _g, p, e in trapped)
        usable = [x for x in trapped[0][2][:last + 1] if not x.lower().startswith(_CASUAL_ARCHIVES)]
        ext = "txt" if "txt" in usable else (usable[0] if usable else "")
        steps = []
        if ext:
            steps.append(f"add an empty {pick.folder / f'<game>.{ext}'} for each (e.g. {first}.{ext}), "
                         "so RocketLauncher finds the game by its own name")
        if look.skips_rom_check(system):
            steps.append("set Rom_Match_Extension=false under [Settings] in "
                         f"{look.settings_dir / system / 'RocketLauncher.ini'}")
        if not steps:
            steps.append(f"move {pick.rom_name}.{pick.ext} out of {pick.rom_dir}")
        node.children.append(Check(
            name="ROM search", status=Status.WARN,
            detail=(f"{len(trapped)}/{checked} games won't start: RocketLauncher takes another file in "
                    f"the game's folder as the game (Rom_Match_Extension), and the module can't start "
                    f"that ({took}{more})"),
            fix=steps[0][0].upper() + steps[0][1:] + "".join(f"; or {s}" for s in steps[1:]),
        ))
    if archives:
        names = [f"{g}.{p.ext}" for g, p in archives]
        node.children.append(Check(
            name="Archives", status=Status.WARN,
            detail=(f"{len(archives)}/{checked} games are found as archives, which the module refuses "
                    f"(\"Compressed games are not supported\"): {_some(names, 5)}"),
            fix=(f"Extract each game into its own folder ({each_game}) and move its archive out of "
                 "Rom_Path (RocketLauncher tries 7z_Extensions before Rom_Extension)"),
        ))
    if lost:
        with_path = [g for g in lost if g.game_path]
        if with_path:
            g = with_path[0]
            step = (f"Fix gamePath under each game's section in {g.ini} (a relative path starts from "
                    f"the RocketLauncher folder: [{g.name}] gamePath={g.game_path} is {g.full}, "
                    "which doesn't exist)")
        else:
            step = (f"Set gamePath=<the game's .exe> under [<game>] in "
                    f"{lost[0].module.parent / (system + '.ini')}")
        node.children.append(Check(
            name="Programs", status=Status.WARN,
            detail=(f"{len(lost)}/{checked} games won't start: no program at their gamePath or in "
                    f"Rom_Path (\"Could not locate …\"): {_some([g.name for g in lost], 5)}"),
            fix=f"{step}; or name each program {each_game / '<game>.exe'}",
        ))
    if stale:
        g = stale[0]
        node.children.append(Check(
            name="gamePath", status=Status.INFO,
            detail=(f"{len(stale)}/{checked} games' gamePath points at a missing file, so the module "
                    f"starts the copy it finds in Rom_Path: {_some([s.name for s in stale], 5)}"),
            fix=(f"Correct or remove gamePath under those games' sections in {g.ini} "
                 f"(e.g. [{g.name}] gamePath={g.game_path} is {g.full})"),
        ))

    notes = []
    if not any(c.status == Status.WARN for c in node.children) and checked:
        notes.append(f"{checked} games OK")
    if unfound:
        notes.append(f"{unfound} not found by RocketLauncher (see ROM paths)")
    if uncheckable:
        notes.append("some paths use Windows drive letters; can't check them on this OS")
    node.detail = "; ".join(notes)
    node.status = _worst([c.status for c in node.children])
    return node


def check_casual_games(config: Config) -> Check:
    """Will RocketLauncher's Casual Games module find each game's program?

    The module (``Modules\\Casual Games\\Casual Games.ahk``, for PopCap and Big
    Fish Games wheels) starts each game's own ``.exe``, found through its
    ``gamePath`` setting or the game's ``Rom_Path`` folder, and stops with
    "Could not locate "<name>" in your Rom Path or in the GamePath" when
    neither holds it.  Every check before this one passes such a game: its
    ROM (an empty ``<game>.txt`` or the ``.exe``) is found.  For every game on a
    Main Menu wheel that launches with that module this follows RocketLauncher
    the way the PC games check follows PCLauncher:

    * the ROM search, in RocketLauncher's own order
      (:meth:`_RomLookup.pick`), since the module looks the program up under
      the ``romName`` it leaves.  With ``Rom_Match_Extension`` on, a game with
      no file named after it gets any file of a listed extension from its
      folder (a ``license.txt``), and the module then looks for
      ``license.exe``: a WARN, fixed by an empty ``<game>.txt`` placeholder.
      An archive is refused outright ("Compressed games are not supported");
    * ``gamePath`` (:meth:`_RomLookup.module_setting`: the game's own
      ``<System>\\<game>.ini``, then ``<System>.ini``, then ``Casual Games.ini``),
      relative to the RocketLauncher folder, then the two ``Rom_Path``
      fallbacks.  No program anywhere is a WARN listing the games; a
      ``gamePath`` that is missing while a fallback copy starts is INFO.

    Wheels switched off on the Main Menu are capped at INFO.  Diagnosis only:
    each fix line names the INI section and key, or the placeholder to add.
    """
    name = "Casual Games"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO, detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO, detail="rocketlauncher_dir not configured; skipping")

    from .rocketlauncher import SKIP_GENERATE_CONFIG

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    look = _RomLookup(Path(config.rocketlauncher_dir))
    hidden = _hidden_main_menu_wheels(mm_path)
    parent = Check(name=name, status=Status.OK)
    for system in _main_menu_wheels(mm_path):
        if system in SKIP_GENERATE_CONFIG:
            continue
        node = _wheel_casual_games(system, look, config.databases_dir)
        if node is None:
            continue
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)
    if not parent.children:
        return Check(name=name, status=Status.INFO, detail="no Casual Games (PopCap / Big Fish Games) systems")
    parent.status = _worst(c.status for c in parent.children)
    return parent


# ─── ScummVM ──────────────────────────────────────────────────────────────────
#
# RocketLauncher's ScummVM module (v2.x) starts ``scummvm.exe [-c<list>] <target>``
# and ScummVM looks the game's folder up under ``[<target>] path=`` in its game
# list, scummvm.ini.  Every RocketLauncher check passes while that list is
# missing or still points at an old drive.

_SCUMMVM_MODULE = "scummvm.ahk"


@dataclass
class _ScummGame:
    """One wheel game as the ScummVM module starts it."""
    name: str                 # database name
    target: str               # the [section] looked up in the game list
    fallback: Optional[Path]  # LaunchMode=ParseIni's <romPath>\<romName>, when that exists


def _scummvm_game_list(
    look: _RomLookup, module: Path, system: str, game: str,
) -> tuple[Optional[Path], str, Optional[Path]]:
    """``(file, where, ini)``: the scummvm.ini the ScummVM module reads for
    *game*, where that comes from (for display), and the module INI that sets
    ``CustomConfig`` (None when none does).

    ``CustomConfig`` under ``[Settings]`` (:meth:`_RomLookup.module_setting`),
    relative to the RocketLauncher folder as ``GetFullName`` resolves it; when
    it is blank, ScummVM's own ``%APPDATA%\\ScummVM\\scummvm.ini``.  *file* is
    None when that can't be told on this OS (a drive path off Windows, no
    ``APPDATA``)."""
    value, ini = look.module_setting(module, system, game, ["Settings"], "CustomConfig")
    value = value.strip('"').strip()
    if value:
        return _resolve_rom_path(value, look.rl_dir), f"CustomConfig={value} in {ini}", ini
    appdata = os.environ.get("APPDATA", "")
    where = "no CustomConfig, so the module reads ScummVM's own list in %APPDATA%"
    return (Path(appdata) / "ScummVM" / "scummvm.ini" if appdata else None), where, None


def _wheel_scummvm(system: str, look: _RomLookup, databases_dir: Path, roms_dir: str) -> Optional[Check]:
    """One wheel's node for :func:`check_scummvm_game_list`; None when none of
    its games starts through the ScummVM module."""
    import re

    def scummvm(src: Optional[_RomSource]) -> bool:
        module = look.module_file(src) if src is not None and not src.stops else None
        return module is not None and module.name.lower() == _SCUMMVM_MODULE

    overrides = look.game_overrides(system)
    own = look.source(system)
    if not scummvm(own) and not any(
        scummvm(look.source(other, emu) if other and other.lower() != system.lower()
                else look.source(system, emu) or own)
        for emu, other in overrides.values()
    ):
        return None

    games, raw = _wheel_games(system, databases_dir)
    # game list -> (file, where, CustomConfig INI, module, emulator folder, games)
    lists: dict[str, tuple[Optional[Path], str, Optional[Path], Path, Optional[Path], list[_ScummGame]]] = {}
    unfound = 0
    for name in games:
        src, _other = look.game_source(system, name, overrides)
        if src is None or src.stops:
            continue  # RL stops before any module runs (the ROM paths check)
        rl_name = raw.get(name, name)  # RL gets the XML name exactly as written
        module = look.module_file(src, rl_name)
        if module is None or module.name.lower() != _SCUMMVM_MODULE or not look.exists(module):
            continue
        picked = look.pick(src, rl_name) if src.checkable() else None
        if picked is not None:
            rom_dir, rom_name = picked.rom_dir, picked.rom_name
        elif not src.checkable() or look.skips_rom_check(src.system):
            # Under Skipchecks RL carries on with romPath set to the whole
            # Rom_Path, which names a folder only when it holds one.
            only = [f for _el, f in src.folders]
            rom_dir, rom_name = (only[0] if len(only) == 1 else None), rl_name
        else:
            unfound += 1  # "Cannot find Rom": the ROM paths check reports it
            continue
        mode, _ini = look.module_setting(module, src.system, rl_name, [rom_name, "Settings"], "LaunchMode")
        target, _ini = look.module_setting(module, src.system, rl_name, [rom_name], "TargetName")
        target = target or rom_name
        fallback = None
        if mode.lower() == "parseini":  # the module reads path= itself
            # ScummVM section names have no spaces or parentheses, so the
            # module looks up "Some_Game__CD_" for "Some Game (CD)".
            target = re.sub(r"[ ()]", "_", target)
            if rom_dir is not None and look.exists(rom_dir / rom_name):
                fallback = rom_dir / rom_name
        file, where, ini = _scummvm_game_list(look, module, src.system, rl_name)
        program = _resolve_rom_path(src.emu_path, look.rl_dir) if src.emu_path else None
        key = os.path.normcase(str(file)) if file is not None else where
        lists.setdefault(key, (file, where, ini, module, program.parent if program else None, []))[5].append(
            _ScummGame(name, target, fallback))

    node = Check(name=system, status=Status.OK)
    total = sum(len(entry[5]) for entry in lists.values())
    checked = 0
    uncheckable = False
    listed: list[Path] = []  # game lists that are there
    for file, where, ini, module, emu_dir, items in lists.values():
        module_ini = ini or module.parent / f"{module.stem}.ini"
        if file is None:
            uncheckable = True
            continue
        if not look.exists(file):
            beside = emu_dir / "scummvm.ini" if emu_dir is not None else None
            if beside is not None and look.exists(beside):
                try:
                    rel = os.path.relpath(beside, look.rl_dir)
                except ValueError:  # another drive
                    rel = str(beside)
                step = f"Set CustomConfig={rel} under [Settings] in {module_ini} (the game list beside the emulator)"
            elif ini is None:
                step = (f"Set CustomConfig=<your scummvm.ini, relative to the RocketLauncher folder> under "
                        f"[Settings] in {module_ini}, or start ScummVM once so it writes {file}")
            else:
                step = f"Point CustomConfig in {module_ini} at your scummvm.ini (relative to the RocketLauncher folder)"
            node.children.append(Check(
                name="Game list", status=Status.WARN,
                detail=f"{len(items)}/{total} games won't start (\"Cannot find {file}\"): {where}",
                fix=step,
            ))
            continue
        listed.append(file)
        try:
            _read_windows_text(file)
        except OSError as e:
            node.children.append(Check(name="Game list", status=Status.INFO, detail=f"{file} unreadable: {e}"))
            continue
        data = _read_rl_ini(file)
        no_section: list[_ScummGame] = []
        no_folder: list[tuple[_ScummGame, str, Optional[Path]]] = []  # (game, path=, folder)
        fell_back: list[_ScummGame] = []
        for g in items:
            section = data.get(g.target.lower())
            value = (section or {}).get("path", "")  # ScummVM reads it as written, quotes and all
            # A relative path= starts from the emulator's folder, where RL runs ScummVM.
            folder = _setting_folder(value, emu_dir, False) if value else None
            if value and folder is None:
                uncheckable = True
                continue
            checked += 1
            if folder is not None and look.exists(folder):
                continue
            if g.fallback is not None:
                fell_back.append(g)
            elif section is None:
                no_section.append(g)
            else:
                no_folder.append((g, value, folder))
        if no_section:
            names = [g.name if g.target == g.name else f"{g.name} [{g.target}]" for g in no_section]
            node.children.append(Check(
                name="Targets", status=Status.WARN,
                detail=(f"{len(no_section)}/{len(items)} games have no section in {file}, so ScummVM "
                        f"doesn't know where their files are: {_some(names, 5)}"),
                fix=(f"Add the games in ScummVM (Add Game, with this game list), then name each one's target: "
                     f"TargetName=<ScummVM target> under [<game>] in {module_ini}"),
            ))
        if no_folder:
            rows = [f"{g.name}: {value or 'no path='}" for g, value, _f in no_folder]
            example = next((
                f" (e.g. [{g.target}] path={new})" for g, value, f in no_folder if value and f is not None
                for new in [_rebased_setting(value, f, roms_dir, False)] if new
            ), "")
            node.children.append(Check(
                name="Game folders", status=Status.WARN,
                detail=(f"{len(no_folder)}/{len(items)} games won't start: their path= in {file} is "
                        f"missing or names a folder that doesn't exist: {_some(rows, 3)}"),
                fix=(f"With ScummVM closed (it rewrites {file.name} when it exits), point path= under each "
                     f"game's section at its folder{example}"),
            ))
        if fell_back:
            node.children.append(Check(
                name="ParseIni", status=Status.INFO,
                detail=(f"{len(fell_back)}/{len(items)} games have no folder at their path= in {file}, so the "
                        f"module sends their Rom_Path folder instead: {_some([g.name for g in fell_back], 5)}"),
            ))

    notes = []
    if checked and not any(c.status == Status.WARN for c in node.children):
        notes.append(f"{checked} games OK")
    if len(listed) == 1:
        notes.append(f"game list: {listed[0]}")
    if unfound:
        notes.append(f"{unfound} not found by RocketLauncher (see ROM paths)")
    if uncheckable:
        notes.append("some paths use Windows drive letters or %APPDATA%; can't check them on this OS")
    node.detail = "; ".join(notes)
    node.status = _worst([c.status for c in node.children])
    return node


def check_scummvm_game_list(config: Config) -> Check:
    """Will ScummVM find each ScummVM wheel game that RocketLauncher starts?

    RocketLauncher's ScummVM module (``Modules\\ScummVM\\ScummVM.ahk``) reads
    ScummVM's game list from the module INI's ``[Settings] CustomConfig``
    (relative to the RocketLauncher folder), or from ScummVM's own
    ``%APPDATA%\\ScummVM\\scummvm.ini`` when that is blank, and stops every
    launch with "Cannot find …scummvm.ini" when the file isn't there.  It then
    starts ScummVM with the game's target: its ``TargetName`` in the module
    INIs, else its name, which needs a ``[<target>]`` section in that list
    whose ``path=`` is the game's folder.  After a drive change those paths
    still name the old drive, and every RocketLauncher check passes.

    For every game on a Main Menu wheel that starts with that module (module
    INIs read as :meth:`_RomLookup.module_setting` does, ``Games.ini``
    overrides followed):

    * a missing game list is a WARN naming the file and where its path came
      from;
    * a game with no section, or whose ``path=`` is missing or names no
      folder, is a WARN listing the games.  With ``LaunchMode=ParseIni`` the
      module reads ``path=`` itself (section name with spaces and parentheses
      made ``_``) and falls back to ``<Rom_Path>\\<game>``: INFO when that
      fallback is there.

    Wheels switched off on the Main Menu are capped at INFO.  Diagnosis only:
    the fix line names the INI and key.
    """
    name = "ScummVM game list"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO, detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO, detail="rocketlauncher_dir not configured; skipping")

    from .rocketlauncher import SKIP_GENERATE_CONFIG

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    look = _RomLookup(Path(config.rocketlauncher_dir))
    hidden = _hidden_main_menu_wheels(mm_path)
    parent = Check(name=name, status=Status.OK)
    for system in _main_menu_wheels(mm_path):
        if system in SKIP_GENERATE_CONFIG:
            continue
        node = _wheel_scummvm(system, look, config.databases_dir, config.roms_dir)
        if node is None:
            continue
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)
    if not parent.children:
        return Check(name=name, status=Status.INFO, detail="no wheels start games with the ScummVM module")
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


# Files HyperSpin plays as a game's video (a .png in the video folder is a still).
_HS_VIDEO_EXTS = (".mp4", ".flv")


def _hs_video_path(hs_dir: Path, system: str) -> str:
    """``[video defaults] path=`` in HyperSpin's ``Settings\\<system>.ini``,
    unquoted; "" when blank or unset (HyperSpin then reads
    ``Media\\<system>\\Video``)."""
    return _read_rl_ini(hs_dir / "Settings" / f"{system}.ini").get(
        "video defaults", {}).get("path", "").strip().strip('"').strip()


def _hs_video_names(folder: Path) -> Optional[set[str]]:
    """Lower-cased names of the video files directly in *folder* (HyperSpin
    doesn't look in subfolders); None when it doesn't exist or can't be listed."""
    try:
        with os.scandir(folder) as it:
            return {e.name.lower() for e in it
                    if e.name.lower().endswith(_HS_VIDEO_EXTS) and e.is_file()}
    except OSError:
        return None


def _wheel_video_redirect(
    system: str,
    value: str,
    hs_dir: Path,
    games: list[str],
    index,
) -> Check:
    """One wheel's node for :func:`check_video_redirects`: *value* is its
    ``path=``, *games* the names HyperSpin looks videos up under (as written
    in the database), *index* :func:`_hs_video_names`, cached."""
    from pathlib import PureWindowsPath

    ini = hs_dir / "Settings" / f"{system}.ini"
    own = hs_dir / "Media" / system / "Video"
    n = len(games)
    item = "wheel" if system == "Main Menu" else "game"  # the Main Menu's videos are its wheels'
    node = Check(name=system, status=Status.OK)

    def key(p: Path) -> str:
        return os.path.normcase(os.path.normpath(str(p)))

    def count(num: int, word: str) -> str:
        return f"{num} {word}{'s' if num != 1 else ''}"

    def with_video(folder: Optional[Path]) -> list[str]:
        """The games with a video directly in *folder*."""
        names = index(folder) if folder is not None else None
        if not names:
            return []
        return [g for g in games if any(f"{g.lower()}{ext}" in names for ext in _HS_VIDEO_EXTS)]

    def blank_fix(source: Optional[Path], copies: int) -> str:
        if source is not None and copies:
            return (f"Copy the {count(copies, 'video')} of this wheel's {item}s in {source} into {own} "
                    f"(keep the ones already there), then leave path= blank under "
                    f"[video defaults] in {ini}")
        return f"In {ini}, leave path= blank under [video defaults], so HyperSpin reads {own}"

    own_videos = with_video(own)
    k = len(own_videos)
    own_held = f"; its own {own} holds videos for {k} of its {count(n, item)}" if k else ""

    if not PureWindowsPath(value).drive and not Path(value).is_absolute():
        # .\Video\ on one cabinet's Main Menu meant Media\Main Menu\Video, and
        # .\Atari 5200\Video\ on its Atari 5200 wheel Media\Atari 5200\Video.
        node.status = Status.INFO
        node.detail = (f"path={value} is relative, and which folder HyperSpin reads it from "
                       f"isn't clear (its own folder, Media or Media\\{system}){own_held}")
        rel = PureWindowsPath(value).parts
        best: tuple[int, Optional[Path]] = (0, None)
        for base in (hs_dir / "Media", hs_dir, own.parent):
            folder = Path(os.path.normpath(base.joinpath(*rel)))
            if key(folder) != key(own):
                found = len(with_video(folder))
                if found > best[0]:
                    best = (found, folder)
        node.fix = blank_fix(best[1], best[0])
        return node

    folder = _setting_folder(value, hs_dir, False)
    if folder is None:
        node.status = Status.INFO
        node.detail = f"path={value} can't be checked on this OS"
        return node
    if key(folder) == key(own):
        node.detail = "path= names the wheel's own video folder, as a blank path= would"
        return node

    if not _dir_exists(folder):
        node.status = Status.WARN
        node.detail = (f"path={value} doesn't exist, so HyperSpin plays no video on this "
                       f"wheel, and shows no error{own_held}")
        node.fix = blank_fix(None, 0)
        # The same folder under the HyperSpin folder (R:\Arcade\Media\MAME\Video
        # after a drive move): its videos can be copied in, or path= repointed.
        moved = _rebased_setting(value, folder, str(hs_dir), False)
        if moved and key(Path(moved)) != key(own):
            found = len(with_video(Path(moved)))
            if found:
                node.fix = blank_fix(Path(moved), found) + f"; or set path={moved} there"
        return node

    there = with_video(folder)
    if not k:
        node.detail = f"videos from {value}"
        if n:
            node.detail += (f": {len(there)} of its {count(n, item)} "
                            f"{'has' if len(there) == 1 else 'have'} one there")
        return node
    node.detail = (f"path={value} sends HyperSpin elsewhere, so {count(k, 'video')} in {own} "
                   f"named after its {item}s never play{'s' if k == 1 else ''} "
                   "(HyperSpin has no per-game fallback)")
    lost = k - len(set(own_videos) & set(there))
    if lost:
        node.status = Status.WARN
        node.detail += (f"; {lost} of those {item}s {'has' if lost == 1 else 'have'} no video in "
                        f"{value}, so {'it plays' if lost == 1 else 'they play'} none")
    else:
        # Each still plays a video, just not the wheel's own copy.
        node.status = Status.INFO
        who = f"that {item} plays its" if k == 1 else f"those {item}s play their"
        node.detail += f"; {who} video from {value} instead"
    node.fix = blank_fix(folder, len(there))
    return node


def check_video_redirects(config: Config) -> Check:
    """Wheels whose ``[video defaults] path=`` hides or loses their videos.

    ``path=`` under ``[video defaults]`` in ``<hyperspin_dir>\\Settings\\<System>.ini``
    sends HyperSpin to another folder for a wheel's videos (``<name>.mp4`` /
    ``.flv``), classically the MAME wheel's ``Media\\MAME\\Video`` for MAME
    sub-wheels.  HyperSpin then reads that folder only, with no per-game
    fallback: videos in the wheel's own ``Media\\<System>\\Video`` never play,
    and a folder that doesn't exist (an old drive letter) plays none at all,
    without an error, while ``audit`` counts the videos as present.

    Per Main Menu wheel with ``path=`` set (and the Main Menu's own
    ``Settings\\Main Menu.ini``): a WARN when the folder doesn't exist, or when
    it's another folder while the wheel's own ``Video`` holds videos named
    after its games (counted) and some of those games have none in the other
    folder, so they play none (INFO when each has one there); an INFO for a
    relative ``path=``, whose base folder isn't clear.  The fix is to copy
    the videos in and leave ``path=`` blank.  A redirect with nothing in the
    wheel's own folder is OK.  Wheels switched off on the Main Menu are only
    INFO; wheels with a blank ``path=`` aren't listed.  Diagnosis only.
    """
    name = "Video redirects"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO,
                     detail="hyperspin_dir not configured; skipping")
    hs_dir = Path(config.hyperspin_dir)
    mm_path = hs_dir / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = _main_menu_wheels(mm_path)
    if not wheels:
        return Check(name=name, status=Status.INFO, detail="no wheels on the Main Menu")
    hidden = _hidden_main_menu_wheels(mm_path)
    listings: dict[str, Optional[set[str]]] = {}

    def index(folder: Path) -> Optional[set[str]]:
        """:func:`_hs_video_names`, once per folder per run (wheels share folders)."""
        k = os.path.normcase(os.path.normpath(str(folder)))
        if k not in listings:
            listings[k] = _hs_video_names(folder)
        return listings[k]

    parent = Check(name=name, status=Status.OK)
    for system in ["Main Menu"] + wheels:
        value = _hs_video_path(hs_dir, system)
        if not value:
            continue
        if system == "Main Menu":
            games = [w for w in wheels if w not in hidden]
        else:
            stripped, raw = _wheel_games(system, config.databases_dir)
            games = list(dict.fromkeys(raw.get(g, g) for g in stripped))
        node = _wheel_video_redirect(system, value, hs_dir, games, index)
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)

    n = len(parent.children)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    with_path = f"wheel{'s' if n != 1 else ''} with [video defaults] path="
    if not n:
        parent.detail = ("no Main Menu wheel sets [video defaults] path=: each plays "
                         "its videos from Media\\<wheel>\\Video")
    elif warned:
        parent.detail = f"{warned} of {n} {with_path} lose{'s' if warned == 1 else ''} videos in HyperSpin"
    else:
        parent.detail = f"{n} {with_path}; see each for where HyperSpin reads videos"
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
    redirect = _hs_video_path(hs_dir, system)
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


# Wheel art HyperSpin accepts, looked up under the database name as written.
_HS_WHEEL_ART_EXTS = (".png", ".swf")
# Characters Windows refuses in a file name: no art can be named after them.
_NOT_IN_FILE_NAMES = frozenset('\\/:*?"<>|')
# SpinDoctor's ranked wheels (the recent.py / playtime.py defaults) list games
# by date or by plays, not A-Z, so jumping a letter means nothing there.
_RANKED_WHEELS = frozenset({"recently played", "most played"})
# Game names, and first characters, listed per wheel before "and N more".
_ART_NAMES_SHOWN = 5
_LETTERS_SHOWN = 12


def _file_stems(folder: Path, exts: tuple[str, ...]) -> Optional[set[str]]:
    """Lower-cased stems of the files in *folder* ending in one of *exts*
    (lower case, dot included; ``..png`` is the stem ``.``); None when the
    folder is missing or can't be listed."""
    stems: set[str] = set()
    try:
        with os.scandir(folder) as it:
            for entry in it:
                low = entry.name.lower()
                ext = next((e for e in exts if low.endswith(e)), None)
                if ext and len(low) > len(ext) and entry.is_file():
                    stems.add(low[:-len(ext)])
    except OSError:
        return None
    return stems


@dataclass
class _HsWheelView:
    """What one visible wheel lists, for :func:`check_wheel_art` and
    :func:`check_letter_art`."""
    system: str
    ini: Path
    wheels_only: bool
    parents_only: bool
    # (name as written, description) of each game HyperSpin can list before
    # the wheels_only filter: enabled, and parents only with parents_only=true.
    listed: list[tuple[str, str]]
    no_art: set[str]  # names as written, from *listed*, with no wheel art

    def shown(self) -> list[tuple[str, str]]:
        """The games HyperSpin puts on the wheel."""
        if not self.wheels_only:
            return self.listed
        return [g for g in self.listed if g[0] not in self.no_art]


def _hs_listed_games(system: str, databases_dir: Path, parents_only: bool) -> list[tuple[str, str]]:
    """``(name as written, description)`` per database game HyperSpin lists
    before its art filters: not ``<enabled>No</enabled>``, and with
    *parents_only* not a clone (a ``<cloneof>`` naming another game)."""
    try:
        games = load_database(system, databases_dir).games()
    except Exception:  # noqa: BLE001 — DB integrity is check_databases' job
        return []
    raw = _raw_game_names(system, databases_dir) if games else {}
    listed: list[tuple[str, str]] = []
    for name, game in games.items():
        if game.enabled == "No":
            continue
        clone = (game.cloneof or "").strip()
        if parents_only and clone and clone.lower() != name.lower():
            continue
        listed.append((raw.get(name, name), (game.description or "").strip() or name))
    return listed


def _hs_wheel_views(config: Config) -> Optional[list[_HsWheelView]]:
    """One view per Main Menu wheel switched on, the Main Menu itself first;
    None when there's no HyperSpin folder or Main Menu."""
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return None
    hs_dir = Path(config.hyperspin_dir)
    mm_path = hs_dir / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = _main_menu_wheels(mm_path)
    if not wheels:
        return None
    hidden = _hidden_main_menu_wheels(mm_path)
    on = [w for w in wheels if w not in hidden]
    views: list[_HsWheelView] = []
    for system in ["Main Menu"] + on:
        ini = hs_dir / "Settings" / f"{system}.ini"
        filters = _read_rl_ini(ini).get("filters", {})
        wheels_only = filters.get("wheels_only", "").strip().lower() == "true"
        parents_only = filters.get("parents_only", "").strip().lower() == "true"
        if system == "Main Menu":
            listed = [(w, w) for w in on]
        else:
            listed = _hs_listed_games(system, config.databases_dir, parents_only)
        art = _file_stems(config.media_dir / system / "Images" / "Wheel", _HS_WHEEL_ART_EXTS) or set()
        no_art = {name for name, _d in listed
                  if name.lower() not in art or not _NOT_IN_FILE_NAMES.isdisjoint(name)}
        views.append(_HsWheelView(system, ini, wheels_only, parents_only, listed, no_art))
    return views


def _wheel_art_node(view: _HsWheelView, config: Config) -> Check:
    """One wheel's node for :func:`check_wheel_art`."""
    missing = [name for name, _d in view.listed if name in view.no_art]
    k, n = len(missing), len(view.listed)
    of = f"{n:,} {'parent ' if view.parents_only else ''}game{'s' if n != 1 else ''}"
    names = _some([f'"{m}"' for m in missing], _ART_NAMES_SHOWN)
    folder = config.media_dir / view.system / "Images" / "Wheel"
    add = f"Add wheel art to {folder} as <name>.png"
    if view.system != "Main Menu":
        add += f' (spindoctor fetch-media --system "{view.system}" --types wheel --apply)'
    node = Check(name=view.system, status=Status.INFO)
    if not view.wheels_only:
        node.detail = (f"{k:,} of {of} {'has' if k == 1 else 'have'} no wheel art, "
                       f"so HyperSpin shows {'its' if k == 1 else 'their'} name as plain text: {names}")
        node.fix = add
        return node
    if k == n:
        node.status = Status.WARN
        node.detail = (f"wheels_only=true, but none of its {of} has wheel art, "
                       "so HyperSpin lists no games")
    else:
        node.detail = (f"wheels_only=true hides {k:,} of {of} from the wheel, "
                       f"as {'it has' if k == 1 else 'they have'} no wheel art: {names}")
    node.fix = f"{add}, or set wheels_only=false under [filters] in {view.ini} to list them as text"
    return node


def check_wheel_art(config: Config) -> Check:
    """Games with no wheel art: shown as plain text, or hidden by wheels_only.

    HyperSpin shows each game by its wheel art,
    ``Media\\<System>\\Images\\Wheel\\<name>.png`` (or ``.swf``) under the
    database name as written.  A game without it shows its name as plain
    text, unless the wheel's ``Settings\\<System>.ini`` has ``[filters]
    wheels_only=true``: then HyperSpin leaves the game off the wheel, so a game
    added to the database can't be seen or picked until it gets art, while
    every ROM check passes.  Games ``parents_only=true`` hides anyway (clones)
    aren't counted, nor are ``<enabled>No</enabled>`` games.  The Main Menu is
    checked too: its games are the systems, with art under
    ``Media\\Main Menu\\Images\\Wheel``.

    One INFO row per wheel with games lacking art, saying how they show and
    naming the first five; a WARN when wheels_only=true hides every game, as
    the wheel then opens empty.  Wheels switched off on the Main Menu are
    skipped.  Diagnosis only.
    """
    name = "Wheel art"
    views = _hs_wheel_views(config)
    if views is None:
        return Check(name=name, status=Status.INFO,
                     detail="hyperspin_dir or its Main Menu not found; skipping")
    parent = Check(name=name, status=Status.OK)
    hidden = [0, 0]  # games, wheels
    text = [0, 0]
    for view in views:
        if not view.no_art:
            continue
        parent.children.append(_wheel_art_node(view, config))
        tally = hidden if view.wheels_only else text
        tally[0] += len(view.no_art)
        tally[1] += 1

    def count(games: int, wheels: int) -> str:
        return f"{games:,} game{'s' if games != 1 else ''} on {wheels} wheel{'s' if wheels != 1 else ''}"

    parts = []
    if hidden[1]:
        parts.append(f"wheels_only=true hides {count(*hidden)} (no wheel art)")
    if text[1]:
        parts.append(f"{count(*text)} show as plain text (no wheel art)")
    wheels = len(views) - 1
    parent.detail = "; ".join(parts) or (
        f"every game on the Main Menu and its {wheels} wheel{'s' if wheels != 1 else ''} has wheel art")
    parent.status = _worst(c.status for c in parent.children)
    return parent


def check_letter_art(config: Config) -> Check:
    """First characters with no letter art for HyperSpin's letter jump.

    Jumping to the next letter (HyperSpin's skip keys) shows
    ``Media\\<System>\\Images\\Letters\\<char>.png`` for the first character
    of the game's description.  A wheel with no ``Letters`` folder, or one
    with no ``.png`` in it, has no letter to show for any game; a missing
    picture for one character (``$``, ``.``, a digit) shows nothing for those
    games only.  Only games on the wheel count: clones are left out with
    ``parents_only=true``, and games without wheel art with
    ``wheels_only=true``.  Characters no file can be named after (``"``,
    ``?``, ...) are skipped.

    Per visible Main Menu wheel: a WARN when the folder is missing or empty,
    an INFO listing the characters with no picture otherwise.  The Main Menu
    (systems in your own order) and SpinDoctor's ranked Recently Played and
    Most Played wheels (by date and by plays, not A-Z) are skipped, as are
    wheels switched off on the Main Menu.  Diagnosis only.
    """
    name = "Letter art"
    views = _hs_wheel_views(config)
    if views is None:
        return Check(name=name, status=Status.INFO,
                     detail="hyperspin_dir or its Main Menu not found; skipping")
    parent = Check(name=name, status=Status.OK)
    checked = 0
    for view in views:
        if view.system == "Main Menu" or view.system.lower() in _RANKED_WHEELS:
            continue
        initials = sorted({d[:1].lower() for _n, d in view.shown()
                           if d and d[:1].isprintable() and not d[:1].isspace()
                           and d[:1] not in _NOT_IN_FILE_NAMES})
        if not initials:
            continue
        checked += 1
        folder = config.media_dir / view.system / "Images" / "Letters"
        letters = _file_stems(folder, (".png",))
        n = len(initials)
        chars = f"{n} first character{'s' if n != 1 else ''}"
        if not letters:
            why = "no Letters folder" if letters is None else "no .png letters in its Letters folder"
            listed = _some(['"' + c + '"' for c in initials], _LETTERS_SHOWN)
            parent.children.append(Check(
                name=view.system, status=Status.WARN,
                detail=(f"{why}, so HyperSpin has no letter to show when you jump to the "
                        f"next letter ({chars}: {listed})"),
                fix=(f"Copy a letter set (a.png to z.png, 0.png to 9.png) into {folder}; "
                     "another wheel's Images\\Letters set works"),
            ))
            continue
        missing = [c for c in initials if c not in letters]
        if missing:
            listed = _some(['"' + c + '"' for c in missing], _LETTERS_SHOWN)
            files = _some(['"' + c + '.png"' for c in missing], _LETTERS_SHOWN)
            parent.children.append(Check(
                name=view.system, status=Status.INFO,
                detail=f"no letter art for {len(missing)} of {chars}: {listed}",
                fix=f"Add {files} to {folder}",
            ))

    empty = sum(1 for c in parent.children if c.status == Status.WARN)
    some = len(parent.children) - empty
    parts = []
    if empty:
        parts.append(f"{empty} wheel{'s have' if empty != 1 else ' has'} no letter art at all")
    if some:
        parts.append(f"{some} wheel{'s miss' if some != 1 else ' misses'} letters for some first characters")
    parent.detail = "; ".join(parts) or (
        f"every first character on {checked} wheel{'s' if checked != 1 else ''} has letter art")
    parent.status = _worst(c.status for c in parent.children)
    return parent


# HyperSpin 1.5 lays a theme out on this canvas and stretches it to the screen.
_THEME_CANVAS = (1024, 768)
# Videos played this much too wide or too tall look plainly stretched.
# 4:3 videos in a full-screen box on a 16:9 screen are 1.33x too wide.
_THEME_STRETCH_LIMIT = 1.3
# Videos read per wheel, spread through the folder, to learn their usual shape.
_THEME_VIDEO_SAMPLE = 25
# Games named per wheel whose own theme stretches their video.
_THEME_GAMES_SHOWN = 5
_NAMED_SHAPES = ((16 / 9, "16:9"), (4 / 3, "4:3"), (3 / 2, "3:2"), (5 / 4, "5:4"), (10 / 9, "10:9"),
                 (1.0, "1:1"), (5 / 6, "5:6"), (3 / 4, "3:4"), (2 / 3, "2:3"), (9 / 16, "9:16"))


def _shape_text(ratio: float) -> str:
    """*ratio* (width / height) as ``4:3`` when within 1% of a common shape,
    else as ``1.85:1``."""
    for value, text in _NAMED_SHAPES:
        if abs(ratio / value - 1) <= 0.01:
            return text
    return f"{ratio:.2f}:1"


def _theme_zips(folder: Path) -> "dict[str, Path]":
    """The zips in a wheel's ``Themes`` folder as ``{name.lower(): path}``:
    ``default`` is the wheel's main theme, the others games' own
    (``<game>.zip``); {} when there are none."""
    zips: "dict[str, Path]" = {}
    try:
        with os.scandir(folder) as it:
            for entry in it:
                stem, ext = os.path.splitext(entry.name)
                if ext.lower() == ".zip" and entry.is_file():
                    zips[stem.lower()] = folder / entry.name
    except OSError:
        pass
    return zips


def _default_theme_zip(folder: Path) -> Optional[Path]:
    """``Default.zip`` in a wheel's ``Themes`` folder, any case; None if absent."""
    return _theme_zips(folder).get("default")


def _theme_video_box(zip_path: Path) -> Optional[dict]:
    """The ``<video>`` element's attributes (names lower-cased) in a theme
    zip's ``Theme.xml``; None when there's no readable one.  Read with a
    pattern, not an XML parser: hand-made themes aren't always valid XML."""
    import re
    import zipfile

    try:
        with zipfile.ZipFile(zip_path) as zf:
            entry = next((n for n in zf.namelist()
                          if n.replace("\\", "/").rsplit("/", 1)[-1].lower() == "theme.xml"), None)
            if entry is None:
                return None
            text = zf.read(entry).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, ValueError):
        return None
    m = re.search(r"<video\b([^>]*)>", text, re.IGNORECASE)
    if not m:
        return None
    return {k.lower(): v for k, v in re.findall(r'([\w-]+)\s*=\s*"([^"]*)"', m.group(1))}


def _hs_video_folder(config: Config, system: str) -> Path:
    """The folder HyperSpin plays *system*'s game videos from: its
    ``[video defaults] path=`` when that's a folder (absolute, or under
    ``Media`` or the HyperSpin folder), else ``Media\\<system>\\Video``."""
    from pathlib import PureWindowsPath

    hs_dir = Path(config.hyperspin_dir)
    raw = _hs_video_path(hs_dir, system)
    if raw:
        win = PureWindowsPath(raw)
        # A cabinet writes Windows paths; Path(raw) also covers a native
        # absolute path, which PureWindowsPath doesn't count as absolute off Windows.
        if win.drive or win.is_absolute() or Path(raw).is_absolute():
            candidates = [Path(raw)]
        else:
            rel = Path(*[p for p in win.parts if p != "."]) if win.parts else Path()
            candidates = [config.media_dir / rel, hs_dir / rel]
        for folder in candidates:
            if folder.is_dir():
                return folder
    return config.media_dir / system / "Video"


def _hs_game_videos(folder: Path) -> "dict[str, str]":
    """``{game name.lower(): file name}`` of the videos directly in *folder*,
    one per game (an ``.mp4`` before an ``.flv``); {} if it can't be listed."""
    found: "dict[str, str]" = {}
    try:
        with os.scandir(folder) as it:
            for entry in it:
                stem, ext = os.path.splitext(entry.name)
                ext = ext.lower()
                if ext in _HS_VIDEO_EXTS and entry.is_file() and (stem.lower() not in found or ext == ".mp4"):
                    found[stem.lower()] = entry.name
    except OSError:
        pass
    return found


def _video_shapes(folder: Path, files: "list[str]") -> "list[tuple[float, str]]":
    """``(width / height, game name)`` of up to :data:`_THEME_VIDEO_SAMPLE`
    of the video *files* in *folder*, spread through them A-Z, sorted by
    shape; [] if none can be read."""
    from .introvideo import video_frame_size

    names = sorted(files, key=str.lower)
    step = max(1, len(names) // _THEME_VIDEO_SAMPLE)
    shapes = []
    for file_name in names[::step][:_THEME_VIDEO_SAMPLE]:
        size = video_frame_size(folder / file_name)
        if size:
            shapes.append((size[0] / size[1], os.path.splitext(file_name)[0]))
    return sorted(shapes)


def _theme_box_size(box: Optional[dict]) -> "Optional[tuple[float, float]]":
    """A ``<video>`` box's ``w``, ``h`` when it has ``forceaspect="both"`` and
    a usable size; None otherwise (nothing to judge)."""
    if not box or box.get("forceaspect", "").strip().lower() != "both":
        return None
    try:
        w, h = float(box.get("w", "")), float(box.get("h", ""))
    except ValueError:
        return None
    return (w, h) if w > 0 and h > 0 else None


def _theme_fits(stretch: float) -> bool:
    """True when a video shown *stretch* times too wide (below 1: too tall)
    still looks its own shape."""
    return 1 / _THEME_STRETCH_LIMIT < stretch < _THEME_STRETCH_LIMIT


def _theme_stretch_text(stretch: float) -> str:
    """*stretch* as ``1.3x too wide`` or ``1.8x too tall``."""
    return f"{stretch:.1f}x too wide" if stretch > 1 else f"{1 / stretch:.1f}x too tall"


def _theme_shape_node(config: Config, system: str, screen: "tuple[int, int]",
                      files: "Optional[list[str]]" = None) -> Optional[Check]:
    """A wheel's main theme for :func:`check_theme_video_shape` on a *screen*
    (width, height): OK; INFO when it fits the usual shape but some videos
    are another; WARN when it stretches the videos.  None when there's
    nothing to compare (no ``Default.zip``, a ``forceaspect`` other than
    ``both``, no usable box, or no readable video).

    *files* are the videos of the games that use the main theme (file names
    in the wheel's video folder); without, all the wheel's videos."""
    themes = config.media_dir / system / "Themes"
    theme = _default_theme_zip(themes)
    box = _theme_video_box(theme) if theme else None
    size = _theme_box_size(box)
    if size is None:
        return None
    folder = _hs_video_folder(config, system)
    if files is None:
        files = list(_hs_game_videos(folder).values())
    shapes = _video_shapes(folder, files)
    if not shapes:
        return None
    clip, read = shapes[len(shapes) // 2][0], len(shapes)
    sx, sy = screen[0] / _THEME_CANVAS[0], screen[1] / _THEME_CANVAS[1]
    shown = (size[0] * sx) / (size[1] * sy)
    stretch = shown / clip
    said = (f"the theme's video box is {_shape_text(shown)} on the {screen[0]}x{screen[1]} screen, "
            f"its videos are {_shape_text(clip)} (the usual shape of {read} read)")
    box_shape = f"w x {sx:.4g} : h x {sy:.4g} = video width : height"
    own_copy = (f"give those games their own copy of the theme, {themes}\\<game>.zip, "
                f"with a box of their shape ({box_shape})")

    def odd_ones(odd: "list[tuple[float, str]]") -> str:
        return (f"{len(odd)} of the {read} read {'is' if len(odd) == 1 else 'are'} "
                f"{_shape_text(odd[len(odd) // 2][0])}: "
                + _some(sorted((f'"{g}"' for _s, g in odd), key=str.lower), _THEME_GAMES_SHOWN))

    if _theme_fits(stretch):
        # One box can't fit clips of two shapes: the odd ones need their own.
        odd = [s for s in shapes if not _theme_fits(shown / s[0])]
        if not odd:
            return Check(name=system, status=Status.OK, detail=said)
        return Check(
            name=system, status=Status.INFO,
            detail=f"some videos are another shape and play stretched ({odd_ones(odd)}); {said}",
            fix=f"One box can't fit videos of two shapes: {own_copy}",
        )
    fix = (f"In Theme.xml in {theme}, give <video> the videos' shape on screen, {box_shape} "
           f'(now w="{box.get("w")}" h="{box.get("h")}"), or use a theme made for this system')
    odd = [s for s in shapes if not _theme_fits(clip / s[0])]
    if odd:
        fix += (f". Not all its videos are that shape ({odd_ones(odd)}), "
                f"and one box can't fit them all: {own_copy}")
    return Check(
        name=system, status=Status.WARN,
        detail=f"its videos play {_theme_stretch_text(stretch)}: {said}",
        fix=fix,
    )


def _game_themes_node(system: str, screen: "tuple[int, int]", themes: Path, folder: Path,
                      own: "list[tuple[str, Path, str]]") -> "tuple[Optional[Check], int, int]":
    """Games' own themes on one wheel for :func:`check_theme_video_shape`:
    *own* lists each game's name, the theme zip it uses and its video's file
    name in *folder*.  The WARN naming the games whose theme stretches their
    video (None when none does), how many were checked, and how many stretch."""
    from .introvideo import video_frame_size

    sx, sy = screen[0] / _THEME_CANVAS[0], screen[1] / _THEME_CANVAS[1]
    sizes: "dict[Path, Optional[tuple[float, float]]]" = {}
    checked, bad = 0, []
    for name, theme, video in own:
        if theme not in sizes:
            sizes[theme] = _theme_box_size(_theme_video_box(theme))
        size = sizes[theme]
        frame = video_frame_size(folder / video) if size else None
        if not frame:
            continue
        checked += 1
        stretch = (size[0] * sx) / (size[1] * sy) / (frame[0] / frame[1])
        if not _theme_fits(stretch):
            bad.append(f'"{name}" ({_theme_stretch_text(stretch)})')
    if not bad:
        return None, checked, 0
    n = len(bad)
    whose = "game's own theme" if checked == 1 else "games' own themes"
    return Check(
        name=f"{system} (games' own themes)", status=Status.WARN,
        detail=(f"{n} of {checked} {whose} "
                f"stretch{'es' if n == 1 else ''} {'its' if n == 1 else 'their'} video: "
                f"{_some(bad, _THEME_GAMES_SHOWN)}"),
        fix=(f"In Theme.xml in each one's {themes}\\<game>.zip, give <video> its video's shape on screen, "
             f"w x {sx:.4g} : h x {sy:.4g} = video width : height"),
    ), checked, n


def _hs_clone_parents(system: str, databases_dir: Path) -> "dict[str, str]":
    """``{clone name.lower(): parent name.lower()}`` from a wheel's database;
    {} when it can't be read."""
    try:
        games = load_database(system, databases_dir).games()
    except Exception:  # noqa: BLE001 — DB integrity is check_databases' job
        return {}
    parents = {}
    for name, game in games.items():
        parent = (game.cloneof or "").strip().lower()
        if parent and parent != name.lower():
            parents[name.lower()] = parent
    return parents


def _wheel_theme_nodes(config: Config, view: "_HsWheelView", screen: "tuple[int, int]") -> dict:
    """One wheel for :func:`check_theme_video_shape`: ``main`` (the main
    theme's node, or None), ``games`` (the games' own themes' WARN, or None),
    ``games_checked``, ``games_bad``, and ``unused`` (True when no game on
    the wheel uses its main theme, so it isn't judged)."""
    system = view.system
    themes = config.media_dir / system / "Themes"
    out = {"main": None, "games": None, "games_checked": 0, "games_bad": 0, "unused": False}
    if not view.listed:
        # No readable database: judge the main theme by all the wheel's videos.
        out["main"] = _theme_shape_node(config, system, screen)
        return out
    zips = _theme_zips(themes)
    folder = _hs_video_folder(config, system)
    videos = _hs_game_videos(folder)
    opts = _read_rl_ini(view.ini).get("themes", {})
    parent_themes = opts.get("use_parent_themes", "").strip().lower() == "true"
    parent_vids = opts.get("use_parent_vids", "").strip().lower() == "true"
    parents = _hs_clone_parents(system, config.databases_dir) if parent_themes or parent_vids else {}
    on_main, main_files, own = 0, set(), []
    for name, _desc in view.shown():
        key = name.lower()
        parent = parents.get(key.strip(), "")
        # A game's own Themes\<game>.zip, else (use_parent_themes) its parent's,
        # else the main theme; its own video, else (use_parent_vids) its parent's.
        theme = zips.get(key) if key != "default" else None
        if theme is None and parent_themes and parent and parent != "default":
            theme = zips.get(parent)
        video = videos.get(key) or (videos.get(parent) if parent_vids and parent else None)
        if theme is None:
            on_main += 1
            if video:
                main_files.add(video)
        elif video:
            own.append((name, theme, video))
    if on_main:
        out["main"] = _theme_shape_node(config, system, screen, sorted(main_files))
    elif "default" in zips and _theme_box_size(_theme_video_box(zips["default"])):
        out["unused"] = True
    if own:
        out["games"], out["games_checked"], out["games_bad"] = _game_themes_node(
            system, screen, themes, folder, own)
    return out


def check_theme_video_shape(config: Config) -> Check:
    """Game themes, a wheel's or a game's own, that stretch videos out of shape.

    A HyperSpin 1.5 theme is laid out on a 1024x768 canvas that is stretched
    to the screen (``[Resolution]`` in ``Settings\\Settings.ini``): on a
    1920x1080 screen one unit is 1.875 pixels across and 1.406 down.  With
    ``forceaspect="both"`` the video fills its ``<video>`` box, ``w`` by
    ``h``, whatever the clip's own shape.  So a box that isn't the videos'
    shape *on screen* pulls every clip wider or taller: a basic full-screen
    theme turns 4:3 videos into 16:9 ones, and tall two-screen handheld clips
    (DS, 3DS) into wide smears.

    Per visible Main Menu wheel, for the games HyperSpin puts on it (from its
    database), the theme each one plays its video in: its own
    ``Media\\<System>\\Themes\\<game>.zip``, else its parent's with
    ``use_parent_themes=true``, else the wheel's main theme ``Default.zip``.
    Only boxes with ``forceaspect="both"`` are judged, against the videos
    (MP4 / M4V / MOV track headers, FLV ``onMetaData``; no ffprobe):

    * the main theme against the median shape of up to 25 videos of the
      games that use it; not at all when every game has its own theme, as
      nobody sees it then.  INFO when the usual shape fits but some of the
      videos read are another shape: one box can't fit both, so those games
      need their own copy of the theme with a box of their shape;
    * each game's own theme against that game's video, with the games
      whose theme stretches theirs named per wheel.

    A WARN when videos play 1.3x or more too wide or too tall.  Games with
    no readable video and other ``forceaspect`` values are skipped; with no
    readable database the main theme is judged by all the wheel's videos.
    Diagnosis only.
    """
    name = "Theme video shape"
    views = _hs_wheel_views(config)
    if views is None:
        return Check(name=name, status=Status.INFO,
                     detail="hyperspin_dir or its Main Menu not found; skipping")
    from .display_mode import hyperspin_resolution

    screen = hyperspin_resolution(config)
    if screen is None:
        return Check(name=name, status=Status.INFO,
                     detail=("no [Resolution] Width / Height in HyperSpin's Settings\\Settings.ini, "
                             "so how far themes are stretched isn't known; skipping"))
    parent = Check(name=name, status=Status.OK)
    wheels = wheels_bad = mixed = games = games_bad = unused = 0
    for view in views:
        if view.system == "Main Menu":
            continue
        found = _wheel_theme_nodes(config, view, screen)
        main = found["main"]
        if main is not None:
            wheels += 1
            wheels_bad += main.status == Status.WARN
            mixed += main.status == Status.INFO
            if main.status != Status.OK:
                parent.children.append(main)
        if found["games"] is not None:
            parent.children.append(found["games"])
        games += found["games_checked"]
        games_bad += found["games_bad"]
        unused += found["unused"]
    counts = [(n, bad, what) for n, bad, what in ((wheels, wheels_bad, "wheel theme"), (games, games_bad, "game theme"))
              if n]
    if wheels_bad or games_bad:
        one = len(counts) == 1 and wheels_bad + games_bad == 1
        parent.detail = (" and ".join(f"{bad:,} of {n:,} {what}{'s' if n != 1 else ''}" for n, bad, what in counts)
                         + f" checked stretch{'es' if one else ''} the videos out of shape")
    elif counts:
        one = len(counts) == 1 and wheels + games == 1
        parent.detail = ("the video box of "
                         + " and ".join(f"{n:,} {what}{'s' if n != 1 else ''}" for n, _bad, what in counts)
                         + f" {'matches' if one else 'match'} the videos' shape")
    else:
        parent.detail = 'no wheel or game theme with forceaspect="both" and readable videos to check'
    if mixed:
        parent.detail += (f"; {mixed} wheel theme{'s' if mixed != 1 else ''} also stretch{'es' if mixed == 1 else ''} "
                          "the videos of another shape than most")
    if unused:
        parent.detail += (f"; {unused} wheel theme{'s' if unused != 1 else ''} that no game uses "
                          f"(each has its own) {'was' if unused == 1 else 'were'} skipped")
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
    from .lightgun import emulator_systems as map_emulator_systems, index_user_functions
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
    emulator_systems = map_emulator_systems(rl, wheels.values())

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


def check_keymapper_hotkeys(config: Config) -> Check:
    """Hotkeys in AHK keymapper profiles that RocketLauncher's menus switch off.

    RocketLauncher assigns its navigation keys with AutoHotkey's ``Hotkey``
    command, in the script an Internal keymapper profile is appended to.  That
    replaces a plain ``w::`` or ``~w::`` in the profile, so it never fires,
    while ``*w::`` and remaps (``w::c``) still do.  Each such hotkey on a
    navigation key is a WARN, with the line and the setting it clashes with
    (see :mod:`spindoctor.keymapper_hotkeys`).  Wheels that are hidden or not
    on the Main Menu are INFO.  Diagnosis only.
    """
    from .keymapper_hotkeys import scan_profiles

    name = "Keymapper hotkeys"
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")
    found, checked = scan_profiles(config)
    if not checked:
        return Check(name=name, status=Status.INFO,
                     detail="no AHK keymapper profiles that RocketLauncher's Internal method would load")
    if not found:
        return Check(name=name, status=Status.OK,
                     detail="no plain hotkeys on RocketLauncher's navigation keys")

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    wheels = {w.lower() for w in _main_menu_wheels(mm_path)}
    hidden = {w.lower() for w in _hidden_main_menu_wheels(mm_path)}
    by_system: dict[str, list] = {}
    for system, path, hits in found:
        by_system.setdefault(system, []).append((path, hits))
    parent = Check(name=name, status=Status.OK)
    for system, profiles in by_system.items():
        listed = [f"{path.name} line {h.hotkey.line} {h.hotkey.text.split('::')[0]}:: is {h.setting} = {h.value}"
                  for path, hits in profiles for h in hits]
        key = profiles[0][1][0].hotkey.key
        node = Check(name=system, status=Status.WARN,
                     detail=f"{len(profiles)} profile{'s' if len(profiles) != 1 else ''}: {_some(listed)}",
                     fix=(f"In {profiles[0][0].parent}, start each of these with * "
                          f"({key}:: becomes *{key}::), or make it a remap"))
        if wheels and system.lower() != "_default" and (system.lower() not in wheels or system.lower() in hidden):
            node.name += " (wheel hidden or not on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    parent.detail = (f"{warned} wheel{'s' if warned != 1 else ''} with hotkeys RocketLauncher switches off"
                     if warned else "only hidden wheels have hotkeys RocketLauncher switches off")
    parent.status = _worst(c.status for c in parent.children)
    return parent


# Future Pinball's own type library ("Future Pinball 1.0 Type Library").
# Table scripts can't start unless it's registered with Windows.
FUTURE_PINBALL_TYPELIB = "{FB22A459-4AD0-4CB3-B959-15158F7139F5}"
_FUTURE_PINBALL_EXES = ("future pinball.exe", "fploader.exe")


def _future_pinball_typelib_path() -> Optional[str]:
    """The program the type library is registered for, ``""`` if its path is blank, None if it isn't registered.

    HKEY_CLASSES_ROOT is the current user's classes merged over the machine's,
    so one look finds an all-users and a per-user registration.
    """
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            rf"TypeLib\{FUTURE_PINBALL_TYPELIB}\1.0\0\win32") as key:
            return str(winreg.QueryValueEx(key, None)[0] or "")
    except OSError:
        return None


def check_future_pinball_typelib(config: Config) -> Check:
    """Future Pinball's scripting library, missing from a copied install.

    Future Pinball needs its own type library registered with Windows for
    table scripts to run.  A folder copied from another PC or an older drive
    has no registration, and running the program as a normal user doesn't add
    one.  The table then loads, draws and changes camera, but its script never
    starts, so coin, start, flippers and the score displays do nothing.  A
    missing registration is a WARN when RocketLauncher has Future Pinball; one
    naming a program that's gone is a WARN too.  Windows only; diagnosis only.
    """
    import sys

    name = "Future Pinball scripting"
    exes: list[Path] = []
    for _section, exe, candidates in _rl_emulator_entries(config):
        if exe in _FUTURE_PINBALL_EXES:
            for candidate in candidates:
                # BAM's FPLoader.exe sits one folder below Future Pinball.exe.
                here = candidate if exe == _FUTURE_PINBALL_EXES[0] else candidate.parent.parent / "Future Pinball.exe"
                if here.is_file() and here not in exes:
                    exes.append(here)
    if not exes:
        return Check(name=name, status=Status.INFO, detail="Future Pinball isn't set up in RocketLauncher")
    if sys.platform != "win32":
        return Check(name=name, status=Status.INFO, detail="can only be checked on Windows")

    registered = _future_pinball_typelib_path()
    if registered is None:
        return Check(
            name=name, status=Status.WARN,
            detail=("its type library isn't registered, so table scripts never start: "
                    "coin, start, flippers and displays do nothing"),
            fix=("Register it for your Windows user (no administrator needed): see "
                 "\"Register Future Pinball's type library\" in docs/troubleshooting.md"))
    if registered and not Path(registered).is_file():
        return Check(
            name=name, status=Status.WARN,
            detail=f"its type library is registered for {registered}, which isn't there",
            fix="Register it again from where Future Pinball is now (docs/troubleshooting.md)")
    return Check(name=name, status=Status.OK,
                 detail="type library registered" + (f" for {registered}" if registered else ""))


# ─── DOSBox game configs ──────────────────────────────────────────────────────
#
# RocketLauncher's DOSBox module (2.0.x, made for eXoDOS sets) gives each game a
# short folder name from ``ZipMapping\<System>.ini`` and starts DOSBox with that
# game's own ``<Config_Folder>\<short>\dosbox.conf``.  A missing one stops the
# game with a CheckFile error before DOSBox starts, while every RocketLauncher
# check passes.

# Text only the eXoDOS-style DOSBox module has (it may be renamed, e.g.
# "DOSBox (Alt+Enter).ahk"); other DOSBox modules start games differently.
_DOSBOX_MODULE_MARKS = ("zipmapping", "config_folder")


class _DosboxModules:
    """The eXoDOS-style DOSBox modules and their INIs, each read once per run."""

    def __init__(self, look: _RomLookup):
        self.look = look
        self._texts: dict[str, str] = {}
        self._inis: dict[str, dict[str, dict[str, str]]] = {}

    def text(self, module: Path) -> str:
        """The module's source, lower-cased ("" when it can't be read)."""
        key = os.path.normcase(str(module))
        if key not in self._texts:
            try:
                self._texts[key] = _read_windows_text(module).lower()
            except OSError:
                self._texts[key] = ""
        return self._texts[key]

    def ini(self, path: Path) -> dict[str, dict[str, str]]:
        key = os.path.normcase(str(path))
        if key not in self._inis:
            self._inis[key] = _read_rl_ini(path)
        return self._inis[key]

    def matches(self, module: Optional[Path]) -> bool:
        """Whether *module* is the eXoDOS-style DOSBox module."""
        if module is None or not module.name.lower().startswith("dosbox") or not self.look.exists(module):
            return False
        text = self.text(module)
        return all(mark in text for mark in _DOSBOX_MODULE_MARKS)

    def setting(self, module: Path, sections: list[str], key: str) -> str:
        """A setting as the module's ``IniReadCheck(settingsFile, "Settings|<game>", …)``
        reads it from ``<module folder>\\<module name>.ini``: the last of
        *sections* with a value wins ("" when none has one)."""
        data = self.ini(module.parent / f"{module.stem}.ini")
        value = ""
        for section in sections:
            value = data.get(section.lower(), {}).get(key.lower(), "").strip() or value
        return value


def _dosbox_saves(system: str, look: _RomLookup, mods: _DosboxModules, module: Path) -> Optional[Check]:
    """INFO when RocketLauncher deletes the wheel's unpacked games, and with them
    the saves DOS games keep in their own folders; None when it keeps them.

    RL's ``7zCleanUp`` deletes the game it unpacked when ``7z_Delete_Temp`` is
    true and ``7z_Games_to_Keep`` (``Settings\\RocketLauncher.ini`` only, for
    every system) is blank; when that is a number, it keeps only that many of
    the newest folders in the unpack folder, whatever ``7z_Delete_Temp`` says.
    A module that sets ``sevenZGamesToKeep`` itself decides on its own."""
    import re

    if look.rl_setting(system, "7z", "7z_enabled", "false").lower() != "true":
        return None
    if re.search(r"(?m)^\s*sevenzgamestokeep\s*:?=", mods.text(module)):
        return None
    general = look.settings_dir / "RocketLauncher.ini"
    keep = mods.ini(general).get("7z", {}).get("7z_games_to_keep", "").strip()
    delete = look.rl_setting(system, "7z", "7z_delete_temp", "true").lower() == "true"
    own = look.settings_dir / system / "RocketLauncher.ini"
    if keep.isdigit():
        kept = int(keep)
        if kept == 0:
            what = "every unpacked game's folder is deleted"
        elif kept == 1:
            what = "only the newest unpacked game keeps its folder"
        else:
            what = f"only the {kept} newest unpacked games keep their folders"
        detail = (f"DOS games save inside their own folder, but {what}: 7z_Games_to_Keep={keep} "
                  f"under [7z] in {general} (for every system; it overrides 7z_Delete_Temp)")
        fix = (f"Set 7z_Delete_Temp=false under [7z] in {own}, and (since 7z_Games_to_Keep is for every "
               f"system) set sevenZGamesToKeep := \"\" in {module.name} before it calls 7zCleanUp")
    elif delete:
        detail = ("DOS games save inside their own folder, but RocketLauncher deletes each game's "
                  "unpacked folder when it closes (7z_Delete_Temp=true)")
        fix = f"Set 7z_Delete_Temp=false under [7z] in {own}"
    else:
        return None
    return Check(name="Saves", status=Status.INFO, detail=detail, fix=fix)


def _wheel_dosbox(system: str, look: _RomLookup, mods: _DosboxModules, databases_dir: Path) -> Optional[Check]:
    """One wheel's node for :func:`check_dosbox_game_configs`; None when none of
    its games starts through the eXoDOS-style DOSBox module."""

    def dosbox(src: Optional[_RomSource]) -> bool:
        return src is not None and not src.stops and mods.matches(look.module_file(src))

    overrides = look.game_overrides(system)
    own = look.source(system)
    if not dosbox(own) and not any(
        dosbox(look.source(other, emu) if other and other.lower() != system.lower()
               else look.source(system, emu) or own)
        for emu, other in overrides.values()
    ):
        return None

    games, raw = _wheel_games(system, databases_dir)
    missing: list[tuple[str, Path, Path]] = []  # (game, expected config, ZipMapping INI)
    no_folder: list[tuple[str, str]] = []       # (game, short name): extracted sets only
    saves: dict[str, Check] = {}
    checked = unfound = unknown = 0
    for name in games:
        src, _other = look.game_source(system, name, overrides)
        if src is None or src.stops:
            continue  # RL stops before any module runs (the ROM paths check)
        rl_name = raw.get(name, name)  # RL gets the XML name exactly as written
        module = look.module_file(src, rl_name)
        if not mods.matches(module):
            continue
        picked = look.pick(src, rl_name) if src.checkable() else None
        rom_name = picked.rom_name if picked is not None else rl_name
        mapping_ini = module.parent / "ZipMapping" / f"{src.system}.ini"
        short = mods.ini(mapping_ini).get("mapping", {}).get(rom_name.lower(), "").strip() or rom_name
        folder_setting = mods.setting(module, ["Settings"], "Config_Folder").strip('"').strip()
        if look.rl_setting(src.system, "7z", "7z_enabled", "false").lower() != "true":
            # Unpacked sets: the module looks for a <short> folder in each Rom_Path
            # folder, the last one found wins, and stops when there is none.
            found = [f for _el, f in src.folders if f is not None and look.exists(f / short)]
            if not found:
                if src.checkable():
                    no_folder.append((name, short))
                else:
                    unknown += 1
                continue
            rom_dir: Optional[Path] = found[-1]
        elif picked is not None:
            rom_dir = picked.rom_dir
        elif src.checkable():
            # "Cannot find Rom"; under Skipchecks RL carries on and the module
            # stops instead ("Couldn't find <game>").  The ROM paths check's job.
            unfound += 1
            continue
        else:
            rom_dir = None  # a drive path off Windows
        if folder_setting:
            config_dir = _resolve_rom_path(folder_setting, look.rl_dir)
        elif rom_dir is not None:
            config_dir = rom_dir / ("!win3x" if "windows" in src.system.lower() else "!dos")
        else:
            config_dir = None
        if config_dir is None:
            unknown += 1
            continue
        conf_name = mods.setting(module, ["Settings", rom_name], "Conf_File") or "dosbox.conf"
        checked += 1
        # The config folder is listed once; the game's own folder only when it's there.
        configs = look.listing(config_dir)
        sub = configs[1].get(short.lower()) if configs is not None else None
        if sub is None or not look.exists(config_dir / sub / conf_name):
            missing.append((name, config_dir / short / conf_name, mapping_ini))
        if src.system.lower() not in saves:
            note = _dosbox_saves(src.system, look, mods, module)
            if note is not None:
                saves[src.system.lower()] = note

    node = Check(name=system, status=Status.OK)
    if missing:
        rows = [f"{g}: {conf}" for g, conf, _m in missing]
        node.children.append(Check(
            name="Configs", status=Status.WARN,
            detail=(f"{len(missing)}/{checked} games won't start: the DOSBox module stops with a CheckFile "
                    f"error when the game's config isn't there: {_some(rows, 3)}"),
            fix=(f"Give each game its config at that path, or map the game to the config folder it has: "
                 f"<game>=<folder> under [mapping] in {missing[0][2]}"),
        ))
    if no_folder:
        rows = [g if s == g else f"{g} [{s}]" for g, s in no_folder]
        node.children.append(Check(
            name="Game folders", status=Status.WARN,
            detail=(f"{len(no_folder)} games won't start: no Rom_Path folder holds their folder, so the "
                    f"module stops (\"Couldn't find a folder …\"): {_some(rows, 5)}"),
            fix="Unpack each game into a folder named after it (or its ZipMapping name) in Rom_Path",
        ))
    node.children.extend(saves.values())

    notes = []
    if checked and not missing:
        notes.append(f"{checked} games OK")
    if unfound:
        notes.append(f"{unfound} not found by RocketLauncher (see ROM paths)")
    if unknown:
        notes.append(f"{unknown} with paths that can't be checked on this OS")
    node.detail = "; ".join(notes)
    node.status = _worst([c.status for c in node.children])
    return node


def check_dosbox_game_configs(config: Config) -> Check:
    """Does each game RocketLauncher starts with the eXoDOS-style DOSBox module
    have its own DOSBox config?

    That module (``Modules\\DOSBox\\DOSBox.ahk`` 2.0.x and renamed copies such
    as ``DOSBox (Alt+Enter).ahk``) maps the game to a short folder name under
    ``[mapping]`` in ``ZipMapping\\<System>.ini`` beside it (else the game's
    name) and starts DOSBox with ``<Config_Folder>\\<short>\\<Conf_File>``:
    ``Config_Folder`` under ``[Settings]`` in the module's INI (relative to the
    RocketLauncher folder), else ``!dos`` (``!win3x`` for a Windows system) in
    the folder RocketLauncher found the game in; ``Conf_File`` under the
    game's own section or ``[Settings]``, else ``dosbox.conf``.  A missing
    config stops the game before DOSBox starts: WARN, listing the games.  For
    unpacked sets (7z off) a game whose folder isn't in Rom_Path is a WARN too.

    DOS games keep their saves in their own folder, which RocketLauncher may
    delete after each game (``7z_Delete_Temp``, and ``7z_Games_to_Keep`` in
    ``Settings\\RocketLauncher.ini``, which applies to every system): INFO,
    unless the module sets ``sevenZGamesToKeep`` itself.  Wheels switched off
    on the Main Menu are capped at INFO.  Diagnosis only.
    """
    name = "DOSBox game configs"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO, detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO, detail="rocketlauncher_dir not configured; skipping")

    from .rocketlauncher import SKIP_GENERATE_CONFIG

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    look = _RomLookup(Path(config.rocketlauncher_dir))
    mods = _DosboxModules(look)
    hidden = _hidden_main_menu_wheels(mm_path)
    parent = Check(name=name, status=Status.OK)
    for system in _main_menu_wheels(mm_path):
        if system in SKIP_GENERATE_CONFIG:
            continue
        node = _wheel_dosbox(system, look, mods, config.databases_dir)
        if node is None:
            continue
        if system in hidden:
            node.name = f"{system} (hidden on the Main Menu)"
            _cap_at_info(node)
        parent.children.append(node)
    if not parent.children:
        return Check(name=name, status=Status.INFO, detail="no wheels start games with the eXoDOS DOSBox module")
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


def _mame_wheel_games(config: Config) -> dict[tuple[Path, str], dict]:
    """``(folder, exe)`` -> the games the Main Menu's visible wheels launch with that MAME build.

    Follows each wheel's ``Default_Emulator`` and its ``Games.ini`` overrides,
    as the Coin/Start check does, for ``mame*`` / ``hbmame*`` programs; MESS
    console wheels are skipped.  Each value has ``exe`` (as RocketLauncher
    names it), ``emulators`` (in order) and ``games`` (``{lower-case name:
    (name, [wheels])}``).
    """
    from .ledblinky_profiles import MESS_DRIVERS, MESS_PER_GAME_DRIVER

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    hidden = {w.lower() for w in _hidden_main_menu_wheels(mm_path)}
    wheels = [w for w in _main_menu_wheels(mm_path) if w.lower() not in hidden]
    rl = _RomLookup(Path(config.rocketlauncher_dir))
    mess_systems = {s.lower() for s in (*MESS_DRIVERS, *MESS_PER_GAME_DRIVER)}
    defaults: dict[str, str] = {}
    programs: dict[tuple[str, str], Optional[Path]] = {}

    def default_emulator(system: str) -> str:
        if system not in defaults:
            found = rl.system(system)
            defaults[system] = found[2][found[1]].get("default_emulator", "") if found else ""
        return defaults[system]

    def mame_program(emulator: str, system: str) -> Optional[Path]:
        key = (emulator.lower(), system.lower())
        if key not in programs:
            path = None
            if emulator and system.lower() not in mess_systems:
                found = rl.system(system)
                data = found[2] if found else {}
                # Like RL, use the local emulator section when present, even if empty.
                section = data.get(emulator.lower(), rl.global_emus.get(emulator.lower(), {}))
                raw = next((section[k] for k in _EMU_PATH_KEYS if section.get(k)), "")
                path = _resolve_rom_path(raw, rl.rl_dir) if raw else None
                if path is not None and not (path.name.lower().startswith(("mame", "hbmame"))
                                             and path.parent.is_dir()):
                    path = None
            programs[key] = path
        return programs[key]

    out: dict[tuple[Path, str], dict] = {}
    for wheel in wheels:
        overrides = rl.game_overrides(wheel)
        if mame_program(default_emulator(wheel), wheel) is None and not any(
                mame_program(emu or default_emulator(other or wheel), other or wheel) is not None
                for emu, other in overrides.values()):
            continue  # no game on this wheel launches with MAME
        games, _ = _wheel_games(wheel, config.databases_dir)
        for game in games:
            emu, other = overrides.get(game.lower(), ("", ""))
            system = other or wheel
            emulator = emu or default_emulator(system)
            path = mame_program(emulator, system)
            if path is None:
                continue
            g = out.setdefault((path.parent, path.name.lower()),
                               {"exe": path.name, "emulators": [], "games": {}})
            if emulator not in g["emulators"]:
                g["emulators"].append(emulator)
            on = g["games"].setdefault(game.lower(), (game, []))[1]
            if wheel not in on:
                on.append(wheel)
    return out


def check_mame_driving_keys(config: Config) -> Check:
    """MAME driving games whose pedals no key presses, or that give one key two jobs.

    A game set up for a steering wheel can keep only the wheel's axis for a
    pedal in its own cfg, so on a keyboard panel it steers and accelerates
    but never brakes; the same cfgs can put two inputs on one key.  For the
    games the Main Menu's visible wheels launch with MAME, whose cfg names a
    pedal (see :mod:`spindoctor.mame_pedals`):

    * A pedal whose own key is gone while the folder-wide one has a key, or
      that names only a device MAME no longer finds: WARN.
    * One key alone on two inputs of different types, among what the game's
      cfg sets: WARN.
    * A folder-wide pedal with no key: INFO (real pedals work that way), or
      a WARN when it names only a lost device.

    Keys a driver gives its own inputs never appear in a cfg, so they aren't
    covered.  Diagnosis only.
    """
    from .mame_pedals import MamePedalKeys, _pedal_order, input_name

    name = "MAME driving keys"
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO,
                     detail="rocketlauncher_dir not configured; skipping")
    groups = _mame_wheel_games(config)
    if not groups:
        return Check(name=name, status=Status.INFO,
                     detail="no MAME games on the Main Menu's wheels")

    parent = Check(name=name, status=Status.OK)
    checked, with_pedals, bad = 0, 0, 0
    for (folder, _exe), g in groups.items():
        reader = MamePedalKeys(folder, g["exe"])
        checked += len(g["games"])
        games = [r for r in (reader.game(game) for game, _ in g["games"].values()) if r is not None]
        if not games:
            continue
        wheels: list[str] = []
        for r in games:
            wheels.extend(w for w in g["games"][r.game.lower()][1] if w not in wheels)
        with_pedals += len(games)
        node = Check(name=" / ".join(g["emulators"]), status=Status.OK)
        n_games = f"{len(games)} game{'s' if len(games) != 1 else ''}"

        no_key = sorted((r for r in games if r.no_key),
                        key=lambda r: (not any(b.lost for _, b in r.no_key), r.game.lower()))
        doubled = sorted((r for r in games if r.two_jobs), key=lambda r: r.game.lower())
        bad += len({r.game.lower() for r in no_key + doubled})
        if no_key:
            listed = ", ".join(r.no_key_text() for r in no_key[:5])
            more = f", and {len(no_key) - 5} more" if len(no_key) > 5 else ""
            node.children.append(Check(
                name="pedals", status=Status.WARN,
                detail=(f"{len(no_key)} of {n_games} with pedals have a pedal that no key presses "
                        f"(Pedal 1 is usually the gas, Pedal 2 the brake): {listed}{more}"),
                fix=reader.pedal_fix(),
            ))
        if doubled:
            listed = ", ".join(r.two_jobs_text() for r in doubled[:5])
            more = f", and {len(doubled) - 5} more" if len(doubled) > 5 else ""
            node.children.append(Check(
                name="keys", status=Status.WARN,
                detail=(f"{len(doubled)} of {n_games} with pedals give one key two jobs, so one "
                        f"press does both: {listed}{more}"),
                fix=reader.two_jobs_fix(),
            ))
        for kind in sorted({k for r in games for k in r.as_folder}, key=_pedal_order):
            wide = reader.folder_binding(kind)
            if wide.has_key:
                continue
            affected = sum(1 for r in games if kind in r.as_folder)
            n_affected = f"{affected} game{'s' if affected != 1 else ''}"
            where = wide.source or "MAME's own keys"
            if wide.lost:
                node.children.append(Check(
                    name=where, status=Status.WARN,
                    detail=(f"{input_name(kind)} is bound to a device MAME no longer finds "
                            f"({wide.seq}), so {n_affected} with that pedal can't press it"),
                    fix=f"with MAME closed, bind {input_name(kind)} Inc again in {where}, or in "
                        "MAME's menu (Tab > Input (general))",
                ))
            else:
                how = wide.seq if wide.why() == "nothing" else f"{wide.why()}: {wide.seq}"
                node.children.append(Check(
                    name=where, status=Status.INFO,
                    detail=(f"{input_name(kind)} has no key ({how}): "
                            "fine for real pedals, but a keyboard panel can't press it in "
                            f"{n_affected}, unless a game's driver gives it a key of its own"),
                ))
        if node.children:
            node.detail = f"{n_games} with pedals on {', '.join(wheels)}"
            node.status = _worst(c.status for c in node.children)
            parent.children.append(node)

    games_text = f"MAME game{'s' if with_pedals != 1 else ''} with pedals"
    if not with_pedals:
        parent.detail = f"{checked} MAME game{'s' if checked != 1 else ''}: none whose cfg sets a pedal"
    elif bad:
        parent.detail = (f"{bad} of {with_pedals} MAME games with pedals have a pedal no key "
                         "presses, or a key with two jobs")
    elif any(c.status == Status.WARN for c in parent.children):
        parent.detail = (f"{with_pedals} {games_text}; a folder-wide pedal is bound to a device "
                         "MAME no longer finds")
    elif parent.children:
        parent.detail = (f"{with_pedals} {games_text}; some folder-wide pedals have no key "
                         "(fine for real pedals)")
    else:
        parent.detail = (f"{with_pedals} {games_text}: every pedal has a key and no key does "
                         "two jobs, as far as their cfgs show")
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


# Layout items that draw an element's artwork (MAME layout version 2).
_LAYOUT_ART_ITEMS = ("backdrop", "overlay", "bezel", "cpanel", "marquee")


def _layout_views(lay: Path) -> "tuple[list[tuple[str, Optional[list[str]]]], str]":
    """The views of a MAME layout (``.lay``) file in file order, as ``(name,
    image files its artwork items draw)``, the files None when an item names
    an element the file doesn't define; and why MAME can't use the file
    ("" when it can)."""
    try:
        root = ET.fromstring(lay.read_bytes())
    except OSError as e:
        return [], f"can't be read ({e.strerror or e})"
    except ET.ParseError as e:
        return [], f"isn't valid XML ({e})"
    if root.tag != "mamelayout" or (root.get("version") or "").strip() != "2":
        return [], 'isn\'t a <mamelayout version="2"> layout'
    images = {
        (el.get("name") or ""): [img.get("file") or "" for img in el.iter("image") if img.get("file")]
        for el in root.findall("element")
    }
    views: list[tuple[str, Optional[list[str]]]] = []
    for view in root.findall("view"):
        files: Optional[list[str]] = []
        for item in view:
            if item.tag not in _LAYOUT_ART_ITEMS:
                continue
            ref = item.get("element") or ""
            if ref not in images:
                files = None
                break
            files += images[ref]
        views.append((view.get("name") or "", files))
    return views, ""


def _layout_view_shown(name: str, views: "list[tuple[str, Optional[list[str]]]]") -> str:
    """The view MAME shows for ``-view "<name>"``: the first whose name starts
    with *name*, ignoring case, else the first one ("" when there is none)."""
    low = name.lower()
    return next((v for v, _f in views if v.lower().startswith(low)), views[0][0] if views else "")


def _vectrex_artwork(look: _RomLookup, emu_dir: Path) -> "tuple[list[Check], str, bool]":
    """The findings on one MESS folder's Vectrex artwork for
    :func:`check_vectrex_overlays`: the rows, a detail for the wheel when no
    row warns, and False when there's no overlay of any kind."""
    import re
    from pathlib import PureWindowsPath

    def listing(folder: Optional[Path]) -> "tuple[dict[str, str], dict[str, str]]":
        found = look.listing(folder) if folder is not None else None
        return found if found is not None else ({}, {})

    # Each folder listed once, names looked up ignoring case, as Windows does.
    emu_dirs = listing(emu_dir)[1]
    art_dir = emu_dir / emu_dirs["artwork"] if "artwork" in emu_dirs else None
    art_files, art_dirs = listing(art_dir)
    vec_dir = art_dir / art_dirs["vectrex"] if art_dir is not None and "vectrex" in art_dirs else None
    vec_files = listing(vec_dir)[0]
    where = vec_dir or (art_dir or emu_dir / "artwork") / "Vectrex"  # as the module spells it
    lay = where / vec_files.get("vectrex.lay", "vectrex.lay")
    has_lay = "vectrex.lay" in vec_files

    def stems(files: "dict[str, str]", ext: str) -> "dict[str, str]":
        return {low[:-len(ext)]: real[:-len(ext)] for low, real in files.items()
                if low.endswith(ext) and len(low) > len(ext)}

    arts = sorted({**stems(art_files, ".art"), **stems(vec_files, ".art")}.values(), key=str.lower)
    pngs = stems(vec_files, ".png")
    if not arts and not pngs and not has_lay:
        return [], f"no overlays in {where}: every game shows plain white vectors", False

    views, error = _layout_views(lay) if has_lay else ([], "")
    if error:
        return [Check(
            name="vectrex.lay", status=Status.WARN,
            detail=f"{lay} {error}, so MESS ignores it and no game shows its overlay",
            fix=(f'Correct {lay}: valid XML in a <mamelayout version="2"> element (an & in a game\'s '
                 "name is written &amp;)"),
        )], "", True

    names = {v.lower() for v, _f in views}
    rows: list[Check] = []
    # Overlays still in the pre-0.107 .art format.  "Game (USA) (A00ED3D6)"
    # is one of two dumps' copies of the overlay of the game "Game (USA)".
    crc = re.compile(r"\s\([0-9a-f]{8}\)$", re.IGNORECASE)
    old = [a for a in arts if a.lower() not in names and crc.sub("", a).lower() not in names]
    if old:
        n = len(old)
        rows.append(Check(
            name="Old .art overlays", status=Status.WARN,
            detail=(f"{n} .art overlay{'s' if n != 1 else ''} with no view in "
                    f"{'vectrex.lay' if has_lay else 'a vectrex.lay (there is none)'} ({_some(old)}): "
                    "MAME and MESS stopped reading .art files in 0.107, so "
                    f"{'these games run' if n != 1 else 'this game runs'} without an overlay"),
            fix=(f"Give each game a view in {lay}, named exactly as its ROM, that draws the .art file's "
                 f"PNG saved as {where / '<game>.png'}"),
        ))

    # PNGs the module asks MESS for a view of, with no view of that name.
    lost = [real for low, real in sorted(pngs.items()) if low not in names]
    if lost and not has_lay:
        rows.append(Check(
            name="vectrex.lay", status=Status.WARN,
            detail=(f"not in {where}: the module asks MESS for the view of each of the {len(lost)} "
                    "games with an overlay PNG there, but MESS has only its own plain views"),
            fix=f"Add {lay} with one view per PNG, named exactly as the PNG, drawing it as an overlay",
        ))
    elif lost:
        n = len(lost)
        if views:
            got = [f"{p} gets {_layout_view_shown(p, views)}'s" for p in lost]
            why = f"the module asks MESS for that view, and MESS shows another one ({_some(got)})"
        else:
            why = f"vectrex.lay has no views, so they show plain white vectors ({_some(lost)})"
        rows.append(Check(
            name="Overlay PNGs", status=Status.WARN,
            detail=f"{n} overlay PNG{'s' if n != 1 else ''} with no view of the same name in vectrex.lay: {why}",
            fix=f'Add a <view name="<game>"> drawing <game>.png to {lay} for each, named exactly as the PNG',
        ))

    # Views the module asks for that MESS doesn't reach, or that draw nothing.
    late: list[str] = []
    broken: list[str] = []
    for i, (view, files) in enumerate(views):
        low = view.lower()
        if low not in pngs:
            continue
        first = next((v for v, _f in views[:i] if v.lower().startswith(low)), None)
        if first is not None:
            late.append(f"{view} gets {first}'s" if first.lower() != low else f"{view} (twice)")
        elif files is None or not all(look.exists(where.joinpath(*PureWindowsPath(f).parts)) for f in files):
            broken.append(view)
    if late:
        n = len(late)
        rows.append(Check(
            name="View order", status=Status.WARN,
            detail=(f"{n} game{'s get' if n != 1 else ' gets'} an earlier view whose name starts with "
                    f"{'theirs' if n != 1 else 'its own'} ({_some(late)}): MESS takes the first view whose "
                    "name starts with the one asked for"),
            fix=(f"In {lay}, put each game's view above every longer name it starts with (views sorted "
                 "by name are in that order), and keep one view per name"),
        ))
    if broken:
        n = len(broken)
        rows.append(Check(
            name="Overlay images", status=Status.WARN,
            detail=(f"{n} game{'s' if n != 1 else ''}' view draws an image that isn't in {where}, or an "
                    f"element vectrex.lay doesn't define ({_some(broken)}), so "
                    f"{'they show' if n != 1 else 'it shows'} no overlay"),
            fix=f"In {lay}, give each view's overlay an <element> whose <image file=\"...\"> is in {where}",
        ))

    # Views no game reaches: the module asks for -view standard without the PNG.
    unasked = [v for v, _f in views if v.lower() not in pngs]
    if unasked:
        n = len(unasked)
        rows.append(Check(
            name="Views without a PNG", status=Status.INFO,
            detail=(f"{n} view{'s' if n != 1 else ''} in vectrex.lay with no PNG of the same name "
                    f"({_some(unasked)}): the module starts a game with -view standard (plain white "
                    f"vectors) unless {where / '<game>.png'} is there"),
            fix=f"For each such game on the wheel, save its overlay as {where / '<view name>.png'}",
        ))

    good = sum(1 for low in pngs if low in names)
    detail = (f"{good} overlay{'s' if good != 1 else ''} in {where}, each with its own view in vectrex.lay"
              if good else f"no overlay PNG in {where}")
    if arts and not old:
        detail += (f"; {len(arts)} old .art file{'s are' if len(arts) != 1 else ' is'} unused "
                   "(MESS reads only vectrex.lay)")
    return rows, detail, True


def check_vectrex_overlays(config: Config) -> Check:
    """Vectrex games that start without their colour overlay, or with another game's.

    A Vectrex draws white vectors; each game came with a coloured plastic
    overlay.  RocketLauncher's MESS module starts a Vectrex game with
    ``-view "<romName>"`` when ``<emulator folder>\\artwork\\Vectrex\\<romName>.png``
    exists, else ``-view standard`` (plain white).  MESS reads the views from
    ``artwork\\vectrex\\vectrex.lay`` (a MAME layout file; MAME and MESS
    stopped reading ``.art`` files in 0.107) and takes the first view whose
    name starts with the name asked for, ignoring case; with none, the file's
    first view: another game's overlay.

    Per visible Main Menu wheel with "vectrex" in its name whose default
    emulator uses the MESS module, in the ``artwork`` folder beside its
    ``Emu_Path``:

    * ``.art`` overlays (in ``artwork`` or ``artwork\\Vectrex``) whose game has
      no view in ``vectrex.lay``: WARN, the game runs without its overlay.
    * PNGs with no view of the same name (or no ``vectrex.lay`` at all): WARN,
      MESS shows another view.
    * A game whose view comes after a view whose name starts with the game's
      ("Polar Rescue (USA) (Beta)" before "Polar Rescue (USA)"): WARN.
    * A game's view drawing an image that isn't there, or an element the
      file doesn't define: WARN.  A ``vectrex.lay`` MESS can't read: WARN.
    * Views with no PNG of their name (the module never asks for them), and
      ``Use_Overlays=false`` for the system in the module's INI: INFO.

    Diagnosis only.
    """
    name = "Vectrex overlays"
    if not config.hyperspin_dir or not Path(config.hyperspin_dir).is_dir():
        return Check(name=name, status=Status.INFO, detail="hyperspin_dir not configured; skipping")
    if not config.rocketlauncher_dir:
        return Check(name=name, status=Status.INFO, detail="rocketlauncher_dir not configured; skipping")

    mm_path = Path(config.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    hidden = _hidden_main_menu_wheels(mm_path)
    look = _RomLookup(Path(config.rocketlauncher_dir))
    folders: dict[str, tuple[list[Check], str, bool]] = {}  # one reading per MESS folder
    parent = Check(name=name, status=Status.OK)
    for system in _main_menu_wheels(mm_path):
        if "vectrex" not in system.lower() or system in hidden:
            continue
        src = look.source(system)
        module = look.module_file(src) if src is not None and src.emu_where else None
        if module is None or module.name.lower() != "mess.ahk":
            continue
        node = Check(name=system, status=Status.OK)
        parent.children.append(node)
        program = _resolve_rom_path(src.emu_path, look.rl_dir) if src.emu_path else None
        if program is None:
            node.status = Status.INFO
            node.detail = (f"no Emu_Path in {src.emu_where}" if not src.emu_path
                           else "Emu_Path uses a Windows drive letter; can't check it on this OS")
            continue
        emu_dir = _windows_case(program.parent)
        if not emu_dir.is_dir():
            node.status = Status.INFO
            node.detail = f"emulator folder not found: {emu_dir} (see ROM paths)"
            continue
        key = os.path.normcase(str(emu_dir))
        if key not in folders:
            folders[key] = _vectrex_artwork(look, emu_dir)
        rows, detail, found = folders[key]
        node.children = list(rows)
        # The module's own INI can switch overlays off for the whole system.
        ini = module.parent / f"{module.stem}.ini"
        if _read_rl_ini(ini).get(system.lower(), {}).get("use_overlays", "").strip().lower() == "false":
            node.children.append(Check(
                name="Use_Overlays", status=Status.INFO,
                detail=(f"Use_Overlays=false under [{system}] in {ini}: the module starts MESS with "
                        "-nouse_overlays, so no game shows its overlay"),
                fix=f"Set Use_Overlays=true under [{system}] in {ini}",
            ))
        node.status = _worst(c.status for c in node.children) if found else Status.INFO
        node.detail = detail if node.status != Status.WARN else f"MESS folder {emu_dir}"

    if not parent.children:
        return Check(name=name, status=Status.INFO,
                     detail="no visible Vectrex wheel starts with RocketLauncher's MESS module")
    total = len(parent.children)
    warned = sum(1 for c in parent.children if c.status == Status.WARN)
    plural = "s" if total != 1 else ""
    if warned:
        parent.detail = (f"{warned} of {total} Vectrex wheel{plural} on MESS start{'s' if warned == 1 else ''} "
                         "some games without their overlay, or with another game's")
    else:
        parent.detail = f"{total} Vectrex wheel{plural} on MESS: no overlay problem found"
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
        load_live_inis,
        unused_entries,
        wheel_scope,
    )

    listxml = listxml_if_cached(config)
    library = Library()
    scope = wheel_scope(config, listxml=listxml)

    children: list[Check] = []
    live = load_live_inis(config)
    unused = unused_entries(config, scope, live=live)
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

    rows = audit_coverage(config, roms, library=library, listxml=listxml, scope=scope, live=live)
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
    _safe("Casual Games", lambda: check_casual_games(config))
    _safe("PCLauncher INI text", lambda: check_pclauncher_ini_text(config))
    _safe("PC game programs", lambda: check_pc_game_programs(config))
    _safe("ROM paths", lambda: check_rom_paths(config))
    _safe("HyperSpin ROMs only", lambda: check_hyperspin_roms_only(config))
    _safe("Video redirects", lambda: check_video_redirects(config))
    _safe("Spaces in game names", lambda: check_game_name_spaces(config))
    _safe("Wheel art", lambda: check_wheel_art(config))
    _safe("Letter art", lambda: check_letter_art(config))
    _safe("Theme video shape", lambda: check_theme_video_shape(config))
    _safe("Match cache", lambda: check_match_cache(config, fix, report.fixes_applied))
    _safe("Global Emulators.ini", lambda: check_global_emulators(config, fix, report.fixes_applied))
    _safe("RocketLauncher settings", lambda: check_rocketlauncher_settings(config))
    _safe("ScummVM game list", lambda: check_scummvm_game_list(config))
    _safe("Lightguns", lambda: check_lightguns(config))
    _safe("Emulator ROM folders", lambda: check_emulator_rom_paths(config))
    _safe("Daphne keys", lambda: check_daphne_keys(config))
    _safe("Vectrex overlays", lambda: check_vectrex_overlays(config))
    _safe("User Functions", lambda: check_user_functions(config))
    _safe("Coin/Start", lambda: check_coin_start(config))
    _safe("MAME key maps", lambda: check_mame_key_maps(config))
    _safe("MAME driving keys", lambda: check_mame_driving_keys(config))
    _safe("Keymapper hotkeys", lambda: check_keymapper_hotkeys(config))
    _safe("Future Pinball scripting", lambda: check_future_pinball_typelib(config))
    _safe("DOSBox game configs", lambda: check_dosbox_game_configs(config))
    _safe("LEDBlinky", lambda: check_ledblinky(config))
    _safe("LED coverage", lambda: check_led_coverage(config))
    _safe("Intro video", lambda: check_intro_video(config))
    _safe("SpinDoctor helpers", lambda: check_refresh_helpers(config))
    _safe("Idle tour", lambda: check_idle_tour(config))
    _safe("Orphan media", lambda: check_orphan_media(config))
    _safe("Metadata APIs", lambda: check_api_creds(config))
    _safe("Media folders", lambda: check_media_skeletons(config, fix, report.fixes_applied))
    return report
