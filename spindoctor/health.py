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


# ─── orchestration ────────────────────────────────────────────────────────────


def run_health_checks(config: Config, fix: bool = False) -> HealthReport:
    report = HealthReport()
    report.add(check_paths(config))
    report.add(check_binaries(config))
    report.add(check_lxml())
    report.add(check_archive_support())
    report.add(check_preview_support())
    report.add(check_databases(config))
    report.add(check_wheel_wiring(config, fix, report.fixes_applied))
    report.add(check_pc_launchability(config))
    report.add(check_match_cache(config, fix, report.fixes_applied))
    report.add(check_global_emulators(config, fix, report.fixes_applied))
    report.add(check_lightguns(config))
    report.add(check_ledblinky(config))
    report.add(check_led_coverage(config))
    report.add(check_api_creds(config))
    report.add(check_media_skeletons(config, fix, report.fixes_applied))
    return report
