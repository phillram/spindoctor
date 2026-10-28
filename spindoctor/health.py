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
        Path(os.path.normpath(rl_dir / "Settings" / rel)),
        Path(os.path.normpath(rl_dir / rel)),
    ]


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
                fix=f'spindoctor pc-rename "{system}" --apply   (fixes stale drive letters)',
            ))
        if not node.children:
            node.detail = f"{total} game(s) OK"
        node.status = _worst([c.status for c in node.children])
        parent.children.append(node)

    parent.status = _worst(c.status for c in parent.children)
    return parent


# RocketLauncher's default 7z_Extensions (RocketLauncher.ini [7z]).  With
# 7z_Enabled=true RL puts these in front of every emulator's Rom_Extension,
# PCLauncher's too -- which is why its "Cannot find Rom" error can quote
# "zip|rar|7z|lha|lzh|gzip|tar|" for an emulator that sets no extension.
_RL_7Z_DEFAULT_EXTENSIONS = "zip|rar|7z|lha|lzh|gzip|tar"

# Skipchecks values (Settings/<System>/RocketLauncher.ini) under which
# RocketLauncher never looks for the ROM file, so a missing one isn't an error.
_RL_SKIP_ROM_CHECKS = ("rom only", "rom and emu")

# The "games are in a subfolder" hint only looks at Rom_Path folders with at
# most this many subfolders (roms\, MultiDisc\, _Gun Games\ and the like).
_SUBFOLDER_HINT_MAX = 50


def _read_windows_text(path: Path) -> str:
    """Read a Windows config file the way the Windows profile API does.

    A ``FF FE`` / ``FE FF`` BOM means UTF-16; otherwise the file is ANSI
    (cp1252) unless it decodes as UTF-8, which is what most tools write
    today.  Without this a cp1252 ``Jeux Rétro`` path would come back as
    ``Jeux R\\ufffdtro`` and be reported as a missing folder.  Raises
    ``OSError`` when the file can't be read.
    """
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _read_rl_ini(path: Path) -> dict[str, dict[str, str]]:
    """Parse a RocketLauncher INI the way RocketLauncher reads it.

    Returns ``{section: {key: value}}`` with section and key names lower-cased:
    RL goes through the Windows profile API, so ``[ROMS]`` == ``[Roms]`` and
    ``Rom_Path`` == ``rom_path``; the first occurrence of a key wins.  Unlike
    ``configparser`` this tolerates a BOM, UTF-16 and ANSI files (see
    :func:`_read_windows_text`), duplicate keys and the
    ``<!--Paste ... Output Below Here-->`` lines RL tools leave in ``Games.ini``
    and module INIs.  A missing or unreadable file reads as ``{}``.
    """
    out: dict[str, dict[str, str]] = {}
    try:
        text = _read_windows_text(path)
    except OSError:
        return out
    cur: Optional[dict[str, str]] = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = out.setdefault(s[1:-1].strip().lower(), {})
        elif cur is not None and "=" in s and not s.startswith((";", "#", "<")):
            key, value = s.split("=", 1)
            cur.setdefault(key.strip().lower(), value.strip())
    return out


def _split_rom_extensions(value: str) -> list[str]:
    """``"zip|7z | .chd"`` → ``["zip", "7z", "chd"]`` (lower-cased, de-duplicated)."""
    exts: list[str] = []
    for part in value.split("|"):
        ext = part.strip().lstrip(".").lower()
        if ext and ext not in exts:
            exts.append(ext)
    return exts


def _resolve_rom_path(element: str, rl_dir: Path) -> Optional[Path]:
    """Resolve one ``Rom_Path`` element to a local folder.

    Relative elements are resolved against the RocketLauncher root, as RL does.
    Returns None when the element can't be checked on this OS (an absolute
    Windows drive path while running on POSIX), mirroring ``_resolve_emu_path``.
    """
    from pathlib import PureWindowsPath

    if Path(element).is_absolute():
        return Path(element)
    pw = PureWindowsPath(element)
    if pw.drive:
        return Path(element) if os.name == "nt" else None
    if not pw.parts:
        return None
    return Path(os.path.normpath(rl_dir / Path(*pw.parts)))


@dataclass
class _RomSource:
    """Where RocketLauncher looks for one group of games: the Rom_Path folders
    from one system's settings, and the extensions RL tries with one emulator.

    An empty *exts* means RL doesn't look for these games' files: *stops* then
    says why RL gives up before looking (no ``Rom_Extension``, no emulator
    section), or is blank for PCLauncher, which needs no extension."""
    system: str
    ini: Path
    folders: list[tuple[str, Optional[Path]]]  # (Rom_Path element, resolved folder)
    exts: list[str]
    emulator: str = ""
    ext_where: str = ""  # where the extensions come from, e.g. "[MAME] in <file>"
    stops: str = ""
    stop_fix: str = ""

    def missing_folders(self) -> list[str]:
        """Rom_Path elements whose folder doesn't exist, for display."""
        out = []
        for element, folder in self.folders:
            if folder is not None and not folder.is_dir():
                out.append(element if element == str(folder) else f"{element} ({folder})")
        return out

    def checkable(self) -> bool:
        """False when a Rom_Path element can't be checked on this OS."""
        return all(folder is not None for _el, folder in self.folders)


class _RomLookup:
    """Settings and folder listings shared by every wheel in one doctor run.

    Wheels share settings (``Games.ini`` ``System=`` overrides) and ROM folders
    (several MAME wheels point at one 36,000-file folder), so each settings
    file is parsed once and each folder is listed once with ``os.scandir``;
    games are then looked up case-insensitively in memory.
    """

    def __init__(self, rl_dir: Path):
        self.rl_dir = rl_dir
        self.settings_dir = rl_dir / "Settings"
        self.global_emus_ini = self.settings_dir / "Global Emulators.ini"
        self.global_emus = _read_rl_ini(self.global_emus_ini)
        self._systems: dict[str, Optional[tuple[Path, str, dict[str, dict[str, str]]]]] = {}
        self._sources: dict[tuple[str, str], Optional[_RomSource]] = {}
        self._listings: dict[str, Optional[tuple[set[str], dict[str, str]]]] = {}
        self._launch: dict[str, tuple[str, bool]] = {}
        self._rl_inis: dict[str, dict[str, dict[str, str]]] = {}
        self._mame_names: Optional[dict[str, str]] = None

    def system(self, system: str) -> Optional[tuple[Path, str, dict[str, dict[str, str]]]]:
        """``(settings file, Rom_Path section, parsed file)`` for *system*: folder
        layout ``Settings/<System>/Emulators.ini`` ``[ROMS]`` first, then flat
        ``Settings/<System>.ini`` ``[Settings]``; None when neither exists."""
        key = system.lower()
        if key not in self._systems:
            found = None
            for ini, section in (
                (self.settings_dir / system / "Emulators.ini", "roms"),
                (self.settings_dir / f"{system}.ini", "settings"),
            ):
                data = _read_rl_ini(ini)
                if section in data:
                    found = (ini, section, data)
                    break
            self._systems[key] = found
        return self._systems[key]

    def source(self, system: str, emulator: str = "") -> Optional[_RomSource]:
        """Rom_Path folders and the extensions RL tries for *system*'s games
        launched with *emulator* (blank → the system's Default_Emulator)."""
        key = (system.lower(), emulator.lower())
        if key in self._sources:
            return self._sources[key]
        found = self.system(system)
        src = None
        if found is not None:
            ini, section, data = found
            sec = data[section]
            emu = (emulator or sec.get("default_emulator", "")).strip()
            low = emu.lower()
            folders = [
                (el.strip(), _resolve_rom_path(el.strip(), self.rl_dir))
                for el in sec.get("rom_path", "").split("|") if el.strip()
            ]
            # RocketLauncher 1.x reads every emulator key from the first file
            # with an [<emulator>] section -- this system's Emulators.ini, else
            # Global Emulators.ini -- and never Rom_Extension from [ROMS].  The
            # flat (HyperLaunch-era) layout keeps it in [Settings] instead.
            emu_sec: Optional[dict[str, str]] = None
            where = ""
            if low and low in data:
                emu_sec, where = data[low], f"[{emu}] in {ini}"
            elif low and low in self.global_emus:
                emu_sec, where = self.global_emus[low], f"[{emu}] in {self.global_emus_ini}"
            raw = emu_sec.get("rom_extension", "") if emu_sec is not None else ""
            if section == "settings" and sec.get("rom_extension"):
                raw, where = sec["rom_extension"], f"[Settings] in {ini}"
            exts = _split_rom_extensions(raw)
            src = _RomSource(system, ini, folders, exts, emu, where)
            if not sec.get("default_emulator", "").strip():
                # RL demands a Default_Emulator before it reads a game's
                # Games.ini Emulator=, so a blank one stops every game.
                src.stops = "no Default_Emulator is set"
                src.stop_fix = f"Set Default_Emulator in {ini}"
            elif emu_sec is None and not raw:
                src.stops = (f"there is no [{emu}] section in {ini} or {self.global_emus_ini} "
                             f'("Could not locate a section called [{emu}]")')
                src.stop_fix = (f"Add an [{emu}] section, with Emu_Path and Rom_Extension, "
                                f"to {self.global_emus_ini}")
            elif not exts and low != "pclauncher":
                # PCLauncher needs no extension: with none, RL just doesn't look.
                src.stops = f'{where} has no Rom_Extension ("Could not find a Rom_Extension for {emu}")'
                src.stop_fix = f"Add Rom_Extension=<extensions> to {where}"
                if section == "roms" and sec.get("rom_extension"):
                    src.stop_fix += f" (RocketLauncher doesn't read the Rom_Extension under [ROMS] in {ini})"
            if not src.stops and self.rl_setting(system, "7z", "7z_enabled", "false").lower() == "true":
                # RL adds each 7z_Extensions entry its list doesn't already
                # contain (a substring test on the "|"-joined list), in front.
                joined = "|".join(exts)
                seven = _split_rom_extensions(
                    self.rl_setting(system, "7z", "7z_extensions", _RL_7Z_DEFAULT_EXTENSIONS))
                added = [e for e in seven if e not in joined]
                # RL adds them as "<ext>|", so a list that was empty ends in an
                # empty entry: RL then also tries "<name>.", and Windows drops
                # the dot, matching a file or folder named exactly like the game.
                src.exts = added + (exts if exts or not added else [""])
        self._sources[key] = src
        return src

    def rl_setting(self, system: str, section: str, key: str, default: str) -> str:
        """A RocketLauncher.ini setting as RL's ``RIniLoadVar`` reads it: the
        system's own ``Settings/<System>/RocketLauncher.ini`` value unless it is
        missing or ``use_global``, then ``Global RocketLauncher.ini``, then
        *default*.  *section* and *key* are lower-case."""
        value = self._rl_ini(self.settings_dir / system / "RocketLauncher.ini").get(section, {}).get(key)
        if value is None or value.lower() == "use_global":
            value = self._rl_ini(self.settings_dir / "Global RocketLauncher.ini").get(section, {}).get(key)
        return default if value is None else value

    def _rl_ini(self, path: Path) -> dict[str, dict[str, str]]:
        """``_read_rl_ini``, parsed once per run."""
        key = os.path.normcase(str(path))
        if key not in self._rl_inis:
            self._rl_inis[key] = _read_rl_ini(path)
        return self._rl_inis[key]

    def listing(self, folder: Path) -> Optional[tuple[set[str], dict[str, str]]]:
        """``(lower-cased file names, {lower-cased subfolder: real name})`` of
        *folder*, listed once per run; None when it can't be listed."""
        key = os.path.normcase(str(folder))
        if key not in self._listings:
            files: set[str] = set()
            subdirs: dict[str, str] = {}
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        try:
                            if entry.is_dir():
                                subdirs[entry.name.lower()] = entry.name
                            else:
                                files.add(entry.name.lower())
                        except OSError:
                            continue
                self._listings[key] = (files, subdirs)
            except OSError:
                self._listings[key] = None
        return self._listings[key]

    def found_in(
        self, folder: Path, name: str, wanted: list[str], match_exts: Optional[list[str]] = None,
    ) -> bool:
        """RL's own lookup in one folder: ``<folder>\\<name>.<ext>`` or
        ``<folder>\\<name>\\<name>.<ext>``.  *name* is lower-cased and *wanted*
        holds the lower-cased ``<name>.<ext>`` file names (just ``<name>`` for
        the empty extension, which a ``<name>`` folder also satisfies).  With
        *match_exts* (RL's ``Rom_Match_Extension=true``) any file with one of
        those extensions anywhere under ``<folder>\\<name>\\`` also counts."""
        lst = self.listing(folder)
        if lst is None:
            return False
        if any(w in lst[0] for w in wanted):
            return True
        sub = lst[1].get(name)
        if sub is None:
            return False
        if name in wanted:
            return True
        inner = self.listing(folder / sub)
        if inner is not None and any(w in inner[0] for w in wanted):
            return True
        if match_exts:
            suffixes = tuple(f".{ext}" for ext in match_exts)
            for _root, _dirs, files in os.walk(folder / sub):
                if any(f.lower().endswith(suffixes) for f in files):
                    return True
        return False

    def found(self, src: _RomSource, names: list[str]) -> bool:
        """Whether RL finds a game under any of *names* through *src*, honoring
        the ``Rom_Match_Extension`` of the system the settings belong to."""
        folders = [f for _el, f in src.folders if f is not None]
        match_exts = src.exts if self.launch_settings(src.system)[1] else None
        for name in names:
            low = name.lower()
            wanted = [f"{low}.{ext}" if ext else low for ext in src.exts]
            if any(self.found_in(f, low, wanted, match_exts) for f in folders):
                return True
        return False

    def launch_settings(self, system: str) -> tuple[str, bool]:
        """``(Skipchecks, Rom_Match_Extension)`` from ``Settings/<System>/RocketLauncher.ini``
        ``[Settings]``.  RL reads Skipchecks from the system file only;
        Rom_Match_Extension falls back to ``Global RocketLauncher.ini``."""
        key = system.lower()
        if key not in self._launch:
            sec = self._rl_ini(self.settings_dir / system / "RocketLauncher.ini").get("settings", {})
            match = self.rl_setting(system, "settings", "rom_match_extension", "false")
            self._launch[key] = (sec.get("skipchecks", ""), match.lower() == "true")
        return self._launch[key]

    def skips_rom_check(self, system: str) -> bool:
        """``Skipchecks=Rom Only`` / ``Rom and Emu``: RL never looks for the ROM."""
        return self.launch_settings(system)[0].lower() in _RL_SKIP_ROM_CHECKS

    def game_overrides(self, system: str) -> dict[str, tuple[str, str]]:
        """``Games.ini``: lower-cased game → (Emulator=, System=) overrides."""
        ini = _read_rl_ini(self.settings_dir / system / "Games.ini")
        return {
            game: (keys.get("emulator", ""), keys.get("system", ""))
            for game, keys in ini.items()
        }

    def mame_rom_names(self) -> dict[str, str]:
        """Lower-cased alternate name → ``MameRomName`` from the RL MAME module INI."""
        if self._mame_names is None:
            ini = _read_rl_ini(self.rl_dir / "Modules" / "MAME" / "MAME.ini")
            self._mame_names = {
                sec: keys["mameromname"] for sec, keys in ini.items()
                if keys.get("mameromname")
            }
        return self._mame_names


def _wheel_games(system: str, databases_dir: Path) -> tuple[list[str], dict[str, str]]:
    """The wheel's database names, plus ``{name: raw name}`` for names whose XML
    ``name`` attribute has leading or trailing spaces.  ``load_database`` strips
    names, but RL gets the attribute exactly as written, so a game named
    ``"Some Hack V2 "`` launches ``Some Hack V2 .nes``."""
    try:
        games = list(load_database(system, databases_dir).games().keys())
    except Exception:  # noqa: BLE001 — DB integrity is check_databases' job
        return [], {}
    raw: dict[str, str] = {}
    xml_path = find_database(system, databases_dir)
    if games and xml_path is not None:
        try:
            with open(xml_path, "rb") as fh:
                root = ET.parse(fh).getroot()
        except Exception:  # noqa: BLE001 — names stay stripped, as loaded
            root = None
        for g in root.findall("game") if root is not None else ():
            name = g.get("name") or ""
            if name.strip() and name != name.strip():
                raw[name.strip()] = name
    return games, raw


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
        emu, other = overrides.get(name.lower(), ("", ""))
        if other and other.lower() != system.lower():
            src = look.source(other, emu)
            if src is not None:  # else System= names a system with no settings
                borrowed.setdefault(other.lower(), []).append((src, name))
        else:
            own_games.append((look.source(system, emu) or own, name))
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


def check_lightguns(config: Config) -> Check:
    """Verify DemulShooter wiring for every system marked ``lightgun: true``.

    A system flagged for lightgun support runs a light-gun game — but if the
    RocketLauncher `Pre_Launch_App` DemulShooter wiring is missing, the game
    launches with no aiming device attached, and a missing `Post_Launch_App`
    teardown leaves DemulShooter running and can break the next launch.  These
    are silent failures the user only notices mid-game, so they belong in doctor.

    Diagnosis only — wiring a system needs a DemulShooter path and a `-target`
    choice, so there is no safe blanket auto-fix; each finding names the exact
    ``lightgun configure`` command instead.
    """
    from .lightgun import audit_system_wiring

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

    for system in systems:
        node = Check(name=system, status=Status.OK)
        status = audit_system_wiring(system, config)
        if status is None or not status.is_wired:
            node.status = Status.FAIL
            node.detail = "marked lightgun but no DemulShooter Pre_Launch_App — game runs with no gun"
            node.fix = f'spindoctor lightgun configure --system "{system}" --apply'
        else:
            if status.post_launch is None:
                node.children.append(Check(
                    name="teardown", status=Status.WARN,
                    detail="no Post_Launch_App — DemulShooter may keep running after exit",
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
            node.status = _worst(c.status for c in node.children)
        parent.children.append(node)

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


def check_led_coverage(config: Config) -> Check:
    """Report how much of the MAME set has LEDBlinky control/color coverage.

    Purely informational, and deliberately **cache-only**: it never triggers a
    fresh ``mame -listxml`` (which can take minutes), so it only runs when a
    fresh cached listxml already exists from a prior ``ledblinky audit`` /
    ``generate``.  Otherwise it points the user at that command instead.

    "would-synth" games are the actionable bucket — they have MAME input data
    but no LEDBlinky entry yet, so ``ledblinky generate`` can light them up.
    """
    if not config.ledblinky_dir:
        return Check(name="LED coverage", status=Status.INFO,
                     detail="ledblinky_dir not configured; skipping")
    if not config.mame_executable:
        return Check(name="LED coverage", status=Status.INFO,
                     detail="mame_executable not configured; skipping")

    from .ledblinky import LISTXML_CACHE_DIR, audit_coverage

    cache = LISTXML_CACHE_DIR / "MAME.xml"
    mame = Path(config.mame_executable)
    fresh = (
        cache.exists()
        and (not mame.exists() or cache.stat().st_mtime >= mame.stat().st_mtime)
    )
    if not fresh:
        return Check(
            name="LED coverage", status=Status.INFO,
            detail="MAME control data not cached (won't run -listxml from doctor)",
            fix="spindoctor ledblinky audit --system MAME",
        )

    try:
        roms = list(load_database("MAME", config.databases_dir).games().keys())
    except Exception:  # noqa: BLE001
        roms = []
    if not roms:
        return Check(name="LED coverage", status=Status.INFO,
                     detail="no MAME database; skipping")

    rows = audit_coverage(config, roms)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    covered = counts.get("covered", 0)
    would = counts.get("would-synth", 0)
    detail = (f"{covered}/{len(roms)} covered · {would} could be generated · "
              f"{counts.get('no-input', 0)} no-input · "
              f"{counts.get('missing', 0)} not in listxml")
    if would:
        return Check(
            name="LED coverage", status=Status.WARN, detail=detail,
            fix="spindoctor ledblinky generate --apply",
        )
    return Check(name="LED coverage", status=Status.OK, detail=detail)


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
    _safe("Match cache", lambda: check_match_cache(config, fix, report.fixes_applied))
    _safe("Global Emulators.ini", lambda: check_global_emulators(config, fix, report.fixes_applied))
    _safe("RocketLauncher settings", lambda: check_rocketlauncher_settings(config))
    _safe("Lightguns", lambda: check_lightguns(config))
    _safe("Emulator ROM folders", lambda: check_emulator_rom_paths(config))
    _safe("LEDBlinky", lambda: check_ledblinky(config))
    _safe("LED coverage", lambda: check_led_coverage(config))
    _safe("Intro video", lambda: check_intro_video(config))
    _safe("Orphan media", lambda: check_orphan_media(config))
    _safe("Metadata APIs", lambda: check_api_creds(config))
    _safe("Media folders", lambda: check_media_skeletons(config, fix, report.fixes_applied))
    return report
