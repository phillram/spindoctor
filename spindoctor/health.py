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
    from .ledblinky import CONTROLS_INI_NAME, COLORS_INI_NAME
    for fname in (CONTROLS_INI_NAME, COLORS_INI_NAME):
        p = base / fname
        if not p.exists():
            parent.children.append(Check(
                name=fname, status=Status.WARN,
                detail=f"missing: {p}",
            ))
        else:
            try:
                from .ledblinky import parse_ini_sections
                n = len(parse_ini_sections(p))
                parent.children.append(Check(
                    name=fname, status=Status.OK,
                    detail=f"{n} sections",
                ))
            except Exception as e:
                parent.children.append(Check(
                    name=fname, status=Status.WARN,
                    detail=f"{type(e).__name__}: {e}",
                ))
    parent.status = (
        Status.OK if all(c.status == Status.OK for c in parent.children)
        else Status.WARN
    )
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

    parent.status = _worst([c.status for c in parent.children])
    return parent


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
    report.add(check_match_cache(config, fix, report.fixes_applied))
    report.add(check_global_emulators(config, fix, report.fixes_applied))
    report.add(check_ledblinky(config))
    report.add(check_api_creds(config))
    report.add(check_media_skeletons(config, fix, report.fixes_applied))
    return report
