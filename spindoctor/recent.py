"""Recently-played wheel — derive from RocketLauncher Statistics.

RocketLauncher writes ``Statistics.ini`` files under
``<RocketLauncher>/Settings/Global Statistics`` (and a per-system file
under each system's settings folder) with the timestamp and play count
for every launch. We parse those, combine them across systems, take the
most recent N (default 20), and regenerate a synthetic "Recently Played"
HyperSpin system the same way :mod:`spindoctor.favorites` does.

Designed to be safe to run repeatedly on every system boot or via a
HyperSpin Tools menu entry — fast (only reads INI files), idempotent
(prunes stale entries), and silent when nothing has changed.
"""
from __future__ import annotations

import argparse
import configparser
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import Config, get_systems, load_config
from .database import GameEntry, HyperspinDatabase
from .favorites import (
    FavoriteEntry, _generate_pclauncher_ini,
    _resolve_target_names, _safe_load,
)
from .medialink import LinkMode, apply_plan, plan_mirror, _read_hs_video_dir
from .rocketlauncher import (
    ensure_rl_game_exe,
    generate_synthetic_system_ini,
    install_bundled_system_assets,
    write_hyperspin_system_ini,
    write_pclauncher_system_ini,
)


DEFAULT_RECENT_SYSTEM = "Recently Played"
DEFAULT_LIMIT = 20

# System names SpinDoctor generates as synthetic wheels.  These are excluded by
# default when reading play statistics so that sessions launched *from* a
# synthetic wheel (Favorites → RL#1 records the play under "Favorites") do not
# pollute the Recently Played / Most Played lists.
SYNTHETIC_SYSTEM_NAMES: frozenset[str] = frozenset({
    "Favorites",
    "Recently Played",
    "Most Played",
})

# Extended exclusion set for collecting play statistics.
# Adds the Toolkit launcher to SYNTHETIC_SYSTEM_NAMES so that tool runs
# (Refresh Favorites, Refresh Most Played, etc.) recorded by RocketLauncher
# when the user launches them from the Toolkit wheel are never treated as
# real game plays and never appear in Recently Played or Most Played.
_STATS_EXCLUDE: frozenset[str] = SYNTHETIC_SYSTEM_NAMES | frozenset({"Toolkit"})
_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    # RocketLauncher's Global Statistics.ini format: "Friday May 22, 2026 07:19:22 AM"
    "%A %B %d, %Y %I:%M:%S %p",
)


@dataclass
class PlayRecord:
    system: str
    rom_name: str
    last_played: datetime
    play_count: int = 0

    def isoformat(self) -> str:
        return self.last_played.isoformat(timespec="seconds")


def _parse_time(value: str) -> Optional[datetime]:
    value = value.strip()
    if not value:
        return None
    # Try common RL formats, then ISO-with-microseconds, then bare epoch
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(int(value))
    except (ValueError, OSError, OverflowError):
        return None


def _read_stats_file(
    path: Path,
    system_name: str,
    *,
    warnings: "list[str] | None" = None,
) -> list[PlayRecord]:
    """Parse one RocketLauncher Statistics.ini file into PlayRecords.

    The format used by RocketLauncher::

        [GameName]
        Last_Time_Played=Friday June 12, 2026 08:18:02 PM
        Number_of_Times_Played=12
        Total_Time_Played=...

    Older RL versions write ``Last_Played`` instead of ``Last_Time_Played``.
    System-level keys (no specific game) are ignored.
    """
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        # utf-8-sig strips the BOM RocketLauncher sometimes writes; plain
        # utf-8 leaves it on the first section header and configparser then
        # raises MissingSectionHeaderError, silently dropping the whole
        # file (playtime._read_playstats_file already uses utf-8-sig).
        parser.read(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        # RL on Windows may write game names in the system codepage
        # (e.g. accented letters like ü → 0xfc in cp1252). Retry once.
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            parser.read(path, encoding="cp1252")
        except (OSError, configparser.Error, UnicodeDecodeError) as exc:
            if warnings is not None:
                warnings.append(
                    f"Could not read stats file {path}: {type(exc).__name__}: {exc}"
                )
            return []
    except (OSError, configparser.Error) as exc:
        if warnings is not None:
            warnings.append(
                f"Could not read stats file {path}: {type(exc).__name__}: {exc}"
            )
        return []

    records: list[PlayRecord] = []
    for section in parser.sections():
        if section.lower() in ("settings", "global"):
            continue
        last_raw = (
            parser.get(section, "Last_Time_Played", fallback="")
            or parser.get(section, "Last_Played", fallback="")
            or parser.get(section, "LastPlayed", fallback="")
        )
        ts = _parse_time(last_raw)
        if not ts:
            continue
        try:
            count = int(parser.get(section, "Number_of_Times_Played", fallback="0") or 0)
        except ValueError:
            count = 0
        records.append(PlayRecord(
            system=system_name, rom_name=section,
            last_played=ts, play_count=count,
        ))
    return records


_GLOBAL_STATS_SKIP_SYSTEMS = frozenset({"toolkit"})


def _read_global_statistics_ini(
    path: Path,
    *,
    exclude_systems: "frozenset[str] | None" = None,
    warnings: "list[str] | None" = None,
) -> list[PlayRecord]:
    """Parse the ``[Last_Played_Games]`` section of RocketLauncher's aggregate
    ``Global Statistics.ini`` file (found at ``Data/Statistics/``).

    This file contains only top-10/top-20 summaries, not full history.  It is
    used as a **fallback** when no per-system ``<system>.ini`` files are found.
    Entries from the ``Toolkit`` pseudo-system (SpinDoctor/RocketLauncherUI
    meta-launches) are skipped automatically.  *exclude_systems* is applied on
    top so that synthetic wheel names (Favorites, Recently Played, Most Played)
    are also dropped when this function is called from :func:`collect_play_records`.
    """
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        # utf-8-sig handles the BOM that RocketLauncher sometimes writes
        parser.read(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            parser.read(path, encoding="cp1252")
        except (OSError, configparser.Error, UnicodeDecodeError) as exc:
            if warnings is not None:
                warnings.append(
                    f"Could not read Global Statistics file {path}: "
                    f"{type(exc).__name__}: {exc}"
                )
            return []
    except (OSError, configparser.Error) as exc:
        if warnings is not None:
            warnings.append(
                f"Could not read Global Statistics file {path}: "
                f"{type(exc).__name__}: {exc}"
            )
        return []

    section = "Last_Played_Games"
    if not parser.has_section(section):
        return []

    records: list[PlayRecord] = []
    i = 1
    while True:
        sys_key = f"{i}_System"
        if not parser.has_option(section, sys_key):
            break
        system = parser.get(section, sys_key, fallback="").strip()
        name = parser.get(section, f"{i}_Name", fallback="").strip()
        date_str = parser.get(section, f"{i}_Date", fallback="").strip()
        i += 1
        if not system or not name:
            continue
        if system.lower() in _GLOBAL_STATS_SKIP_SYSTEMS:
            continue
        if exclude_systems and system in exclude_systems:
            continue
        ts = _parse_time(date_str)
        if ts:
            records.append(PlayRecord(
                system=system, rom_name=name, last_played=ts, play_count=1,
            ))
    return records


def collect_play_records(
    config: Config,
    *,
    exclude_systems: "frozenset[str] | set[str] | None" = _STATS_EXCLUDE,
    warnings: "list[str] | None" = None,
    notes: "list[str] | None" = None,
) -> list[PlayRecord]:
    """Walk RocketLauncher's Statistics tree and return every game launch.

    Checks three locations in priority order:
      * ``<RocketLauncher>/Settings/Global Statistics/<system>.ini`` (classic layout)
      * ``<RocketLauncher>/Settings/<system>/Statistics.ini`` (oldest layout)
      * ``<RocketLauncher>/Data/Statistics/<system>.ini`` (newer RL layout)

    If none of those per-system files yield records, falls back to reading
    the aggregate ``Data/Statistics/Global Statistics.ini`` summary (which
    contains only the top-10 lists, but is better than nothing).

    *exclude_systems* — system names to skip entirely when reading stats.
    Defaults to :data:`_STATS_EXCLUDE` (= :data:`SYNTHETIC_SYSTEM_NAMES` plus
    ``"Toolkit"``) so that sessions launched *from* a synthetic wheel or the
    Toolkit launcher (Refresh Favorites, etc.) do not pollute the Recently
    Played / Most Played lists.  Pass ``None`` or an empty set to read all
    systems.

    Pass a list to *notes* to receive informational messages describing which
    paths were found and used (useful for CLI / GUI diagnostics).
    """
    if not config.rocketlauncher_dir:
        return []
    rl = Path(config.rocketlauncher_dir)
    records: list[PlayRecord] = []
    _excluded: frozenset[str] = frozenset(exclude_systems) if exclude_systems else frozenset()

    def _note(msg: str) -> None:
        if notes is not None:
            notes.append(msg)

    def _is_excluded(name: str) -> bool:
        return name in _excluded

    # Classic layout: Settings/Global Statistics/<system>.ini
    global_dir = rl / "Settings" / "Global Statistics"
    if global_dir.is_dir():
        before = len(records)
        for ini in global_dir.glob("*.ini"):
            if _is_excluded(ini.stem):
                continue
            records.extend(_read_stats_file(ini, ini.stem, warnings=warnings))
        added = len(records) - before
        if added:
            _note(f"Settings/Global Statistics/: {added} record(s) from "
                  f"{len(list(global_dir.glob('*.ini')))} file(s)")

    # Oldest layout: Settings/<system>/Statistics.ini
    settings_dir = rl / "Settings"
    if settings_dir.is_dir():
        before = len(records)
        sys_dirs_with_stats = []
        for sys_dir in settings_dir.iterdir():
            if not sys_dir.is_dir():
                continue
            if _is_excluded(sys_dir.name):
                continue
            stats = sys_dir / "Statistics.ini"
            if stats.is_file():
                records.extend(_read_stats_file(stats, sys_dir.name, warnings=warnings))
                sys_dirs_with_stats.append(sys_dir.name)
        added = len(records) - before
        if added:
            _note(f"Settings/<system>/Statistics.ini: {added} record(s) from "
                  f"{len(sys_dirs_with_stats)} system(s)")

    # Newer layout: Data/Statistics/<system>.ini
    # The aggregate "Global Statistics.ini" lives in the same folder — skip it
    # here; it's handled as a fallback below.
    data_stats_dir = rl / "Data" / "Statistics"
    if data_stats_dir.is_dir():
        before = len(records)
        data_files = [
            ini for ini in data_stats_dir.glob("*.ini")
            if ini.stem.lower() != "global statistics"
            and not _is_excluded(ini.stem)
        ]
        for ini in data_files:
            records.extend(_read_stats_file(ini, ini.stem, warnings=warnings))
        added = len(records) - before
        if added:
            _note(f"Data/Statistics/: {added} record(s) from "
                  f"{len(data_files)} system file(s)")
        elif data_files:
            _note(f"Data/Statistics/: found {len(data_files)} system file(s) "
                  f"but 0 parseable records (files may be empty or unrecognised format)")

    # Fallback: parse the aggregate Global Statistics.ini if no per-game data
    # was found anywhere.  This gives us at most 10 recently-played entries
    # but is still far better than showing an empty wheel.
    if not records:
        global_stats_path = rl / "Data" / "Statistics" / "Global Statistics.ini"
        if global_stats_path.is_file():
            fallback = _read_global_statistics_ini(
                global_stats_path,
                exclude_systems=_excluded if _excluded else None,
                warnings=warnings,
            )
            records.extend(fallback)
            if fallback:
                _note(
                    f"Data/Statistics/Global Statistics.ini (fallback): "
                    f"{len(fallback)} recent game(s) — this file contains only "
                    f"top-10 summaries, not full history.  Per-system stats files "
                    f"were not found."
                )
            else:
                _note(
                    "Data/Statistics/Global Statistics.ini exists but contains "
                    "no [Last_Played_Games] entries."
                )
        else:
            _note(
                "No stats files found in any of the searched locations.  "
                "Check that rocketlauncher_dir is set correctly and that "
                "RocketLauncher has recorded at least one game launch."
            )

    return records


def top_recent(
    records: Iterable[PlayRecord],
    limit: int = DEFAULT_LIMIT,
) -> list[PlayRecord]:
    """Return the most-recent *limit* records, deduplicated by (system, rom)."""
    by_key: dict[tuple[str, str], PlayRecord] = {}
    for r in records:
        key = (r.system, r.rom_name)
        if key not in by_key or r.last_played > by_key[key].last_played:
            by_key[key] = r
    sorted_records = sorted(by_key.values(), key=lambda r: r.last_played, reverse=True)
    return sorted_records[:limit]


# ─── synthetic system rebuild ────────────────────────────────────────────────

@dataclass
class RecentSummary:
    target_system: str
    db_path: Optional[Path] = None
    entries: int = 0
    pruned: int = 0
    media_linked: int = 0
    media_copied: int = 0
    media_skipped: int = 0
    inis_written: int = 0
    media_errors: list[str] = field(default_factory=list)
    system_ini_path: Optional[Path] = None
    read_warnings: list[str] = field(default_factory=list)
    # Informational messages about where stats data was found/sourced from.
    read_notes: list[str] = field(default_factory=list)
    # Results from install_bundled_system_assets().
    # Keys: "wheel_art", "background", "music"
    # Values: (Optional[Path], status_str) where status ∈
    #   "installed" | "skipped" | "no_asset" | "dry_run"
    bundled_assets: dict = field(default_factory=dict)


@dataclass
class ClearWheelSummary:
    """Result of :func:`clear_wheel_artifacts`."""
    target_system: str
    db_removed: bool = False
    media_files_removed: int = 0
    ini_files_removed: int = 0
    errors: list[str] = field(default_factory=list)


def clear_wheel_artifacts(
    config: Config,
    target_system: str,
    *,
    dry_run: bool = True,
) -> ClearWheelSummary:
    """Remove all on-disk artifacts for a synthetic wheel.

    Deletes:
      * ``Databases/<target_system>/<target_system>.xml``
      * All files under ``Media/<target_system>/``
      * All ``*.ini`` files under
        ``<RocketLauncher>/Modules/PCLauncher/<target_system>/``

    RocketLauncher's own ``Statistics.ini`` files are *never* touched —
    the synthetic wheels are derived from those; clearing the wheel just
    removes what SpinDoctor wrote.  HyperSpin's ``Settings/<system>.ini``
    is likewise left intact as it may contain user customisations.

    When *dry_run* is ``True`` (the default) no files are changed; the
    returned summary describes what *would* be removed.
    """
    summary = ClearWheelSummary(target_system=target_system)

    if config.hyperspin_dir:
        db_path = config.databases_dir / target_system / f"{target_system}.xml"
        media_dir = config.media_dir / target_system

        if dry_run:
            if db_path.exists():
                summary.db_removed = True
            if media_dir.exists():
                summary.media_files_removed = sum(
                    1 for p in media_dir.rglob("*") if p.is_file()
                )
        else:
            # ── database XML ────────────────────────────────────────────
            if db_path.exists():
                try:
                    db_path.unlink()
                    summary.db_removed = True
                    # Drop the parent dir if it is now empty.
                    try:
                        db_path.parent.rmdir()
                    except OSError:
                        pass
                except OSError as exc:
                    summary.errors.append(f"remove {db_path}: {exc}")

            # ── media files ─────────────────────────────────────────────
            if media_dir.exists():
                for media_file in list(media_dir.rglob("*")):
                    if media_file.is_file():
                        try:
                            media_file.unlink()
                            summary.media_files_removed += 1
                        except OSError as exc:
                            summary.errors.append(f"remove {media_file.name}: {exc}")
                # Attempt to prune empty subdirs (best-effort).
                try:
                    shutil.rmtree(media_dir)
                except OSError:
                    pass

    if config.rocketlauncher_dir:
        rl = Path(config.rocketlauncher_dir)
        ini_dir = rl / "Modules" / "PCLauncher" / target_system
        if ini_dir.exists():
            if dry_run:
                summary.ini_files_removed = sum(
                    1 for f in ini_dir.glob("*.ini") if f.is_file()
                )
            else:
                for ini_file in list(ini_dir.glob("*.ini")):
                    try:
                        ini_file.unlink()
                        summary.ini_files_removed += 1
                    except OSError as exc:
                        summary.errors.append(f"remove {ini_file.name}: {exc}")
                try:
                    ini_dir.rmdir()
                except OSError:
                    pass

    return summary


def _build_synthetic_wheel(
    config: Config,
    target_system: str,
    pseudo_entries: list[FavoriteEntry],
    *,
    media_mode: LinkMode = LinkMode.COPY,
    skip_media: bool = False,
    skip_launchers: bool = False,
    verbose: bool = False,
) -> RecentSummary:
    """Shared synthetic-wheel builder used by ``recent`` and ``playtime``.

    Given a list of :class:`FavoriteEntry` records (each pointing at a
    source ``(system, rom_name)``), this:

      1. Writes ``Databases/<target_system>/<target_system>.xml``,
         pulling metadata from the source system's database when
         available and pruning entries that are no longer in the list.
      2. Mirrors media via :func:`spindoctor.medialink.plan_mirror` /
         :func:`apply_plan` (drops orphans first).
      3. Writes per-game PCLauncher INIs that defer launching back to
         the source system via RocketLauncher.

    The recent + playtime callers translate their domain records into
    :class:`FavoriteEntry` shells before delegating here so all three
    synthetic wheels (Favorites, Recently Played, Most Played) behave
    identically inside HyperSpin.
    """
    summary = RecentSummary(target_system=target_system)
    if not config.hyperspin_dir:
        return summary

    # Pre-validate entries against their source HyperSpin databases.
    # RL#2 writes playtime stats on every exit — including failed launches
    # from synthetic wheels — recording whatever name PCLauncher passed as
    # -r back to the *source* system's stats file.  If that name differs
    # from the canonical database name (e.g. "Kirby's Adventure" in stats
    # while the DB has "Kirby's Adventure (USA)"), the resulting PCLauncher
    # INI routes to the wrong ROM and the launch fails perpetually.
    # Filtering here breaks the cycle; entries with no DB match are logged
    # and skipped.  If the source DB can't be loaded we keep the entry so
    # a missing or unreadable database file doesn't silently empty the wheel.
    src_cache: dict = {}
    valid_entries: list[FavoriteEntry] = []
    for fe in pseudo_entries:
        src_db = _safe_load(fe.system, config, src_cache)
        if src_db is not None and src_db.get(fe.rom_name) is None:
            print(
                f"[{target_system}] WARN: skipping '{fe.rom_name}' ({fe.system})"
                f" — not found in source HyperSpin database."
                f" This is a stale stats entry from a failed synthetic-wheel launch.",
                flush=True,
            )
            continue
        valid_entries.append(fe)
    pseudo_entries = valid_entries

    n = len(pseudo_entries)
    print(f"[{target_system}] building wheel — {n} entr{'y' if n == 1 else 'ies'}…",
          flush=True)

    target_names = _resolve_target_names(pseudo_entries)
    summary.entries = len(target_names)

    # ── Phase 1: write / prune the HyperSpin database XML ────────────────────
    print(f"[{target_system}] writing database…", flush=True)
    db_path = config.databases_dir / target_system / f"{target_system}.xml"
    db = HyperspinDatabase(target_system, db_path, preserve_order=True)
    db.load()
    keep = set(target_names.values())
    # Drop every existing entry so the ranked upserts below dictate XML order —
    # otherwise `_merge_into_tree` would keep surviving games at their prior
    # (alphabetical) positions, defeating the recency / most-played ranking.
    summary.pruned = sum(1 for name in db.games() if name not in keep)
    db.reset_games()

    # src_cache is pre-populated above; continue reusing it so each source
    # system DB is parsed only once across the full build.
    for fe in pseudo_entries:
        target_name = target_names[f"{fe.system}::{fe.rom_name}"]
        source_db = _safe_load(fe.system, config, src_cache)
        source_game = source_db.get(fe.rom_name) if source_db else None
        base_desc = fe.display_name or (source_game.description if source_game else fe.rom_name)
        merged = GameEntry(
            name=target_name,
            description=f"{base_desc} ({fe.system})",
            cloneof=source_game.cloneof if source_game else "",
            crc=source_game.crc if source_game else "",
            manufacturer=source_game.manufacturer if source_game else "",
            year=source_game.year if source_game else "",
            genre=source_game.genre if source_game else "",
            rating=source_game.rating if source_game else "",
            enabled="Yes",
        )
        db.upsert_game(merged)
    summary.db_path = db.save(backup=False)
    print(f"[{target_system}] database done — {len(keep)} games "
          f"({summary.pruned} pruned).", flush=True)

    # ── Phase 2: mirror media ─────────────────────────────────────────────────
    if not skip_media:
        print(f"[{target_system}] mirroring media for {n} game(s)…", flush=True)
        seen = set(target_names.values())
        _target_media = config.media_dir / target_system
        # Per-system video directory overrides: HyperSpin subsystems that use MAME
        # (e.g. "4-Player Games", "Driving Games") redirect their video lookup to
        # Media/MAME/Video/ via [video defaults] → path= in the system Settings INI.
        # Cache one lookup per source system to avoid re-reading the same INI.
        _hs_settings = Path(config.hyperspin_dir) / "Settings" if config.hyperspin_dir else None
        _video_cache: dict[str, Optional[Path]] = {}

        # Write new media FIRST so a mid-run failure never leaves entries
        # without media that was deleted before the replacement was written.
        for idx, fe in enumerate(pseudo_entries, 1):
            if _hs_settings and fe.system not in _video_cache:
                _video_cache[fe.system] = _read_hs_video_dir(_hs_settings, fe.system)
            video_override = _video_cache.get(fe.system) if _hs_settings else None
            target_name = target_names[f"{fe.system}::{fe.rom_name}"]
            plan = plan_mirror(
                config.media_dir, fe.system, target_system,
                fe.rom_name, target_name,
                video_dir_override=video_override,
            )
            result = apply_plan(plan, mode=media_mode,
                               log_fn=print if verbose else None)
            summary.media_linked += result["linked"]
            summary.media_copied += result["copied"]
            summary.media_skipped += result["skipped"]
            summary.media_errors.extend(result["errors"])
            # Emit progress every 10 games (or on the last one) so the
            # GUI output panel shows activity during long media copies.
            if idx % 10 == 0 or idx == n:
                print(
                    f"[{target_system}] media {idx}/{n} — "
                    f"linked {summary.media_linked} "
                    f"copied {summary.media_copied} "
                    f"skipped {summary.media_skipped}",
                    flush=True,
                )

        # Remove orphan media AFTER writing new files.
        if _target_media.is_dir():
            for media_path in _target_media.rglob("*"):
                if media_path.is_file() and media_path.stem not in seen:
                    try:
                        media_path.unlink()
                    except OSError as e:
                        summary.media_errors.append(f"cleanup {media_path.name}: {e}")
        print(f"[{target_system}] media done.", flush=True)

    # ── Phase 3: write PCLauncher INIs ────────────────────────────────────────
    if not skip_launchers and config.rocketlauncher_dir:
        print(f"[{target_system}] writing {n} PCLauncher INI(s)…", flush=True)
        rl_dir = Path(config.rocketlauncher_dir)
        ini_dir = rl_dir / "Modules" / "PCLauncher" / target_system
        # Write new INIs FIRST, then remove stale ones.
        for fe in pseudo_entries:
            target_name = target_names[f"{fe.system}::{fe.rom_name}"]
            _generate_pclauncher_ini(
                rl_dir, target_system, target_name, fe.system, fe.rom_name,
            )
            summary.inis_written += 1
        # Write the system-level PCLauncher INI that PCLauncher.ahk reads.
        # PCLauncher.ahk reads Modules/PCLauncher/<SystemName>.ini and looks up
        # [<game_name>] sections — it does NOT read the per-game placeholder
        # files in the subdirectory (those are only for RL game discovery).
        pclauncher_entries = [
            (target_names[f"{fe.system}::{fe.rom_name}"], fe.system, fe.rom_name)
            for fe in pseudo_entries
        ]
        game_exe = ensure_rl_game_exe(rl_dir)
        write_pclauncher_system_ini(
            target_system, pclauncher_entries, rl_dir,
            rl_exe=game_exe,
            extra_window_titles=config.emulator_window_titles or None,
        )
        summary.system_ini_path = generate_synthetic_system_ini(target_system, rl_dir)
        # Remove stale per-game INIs AFTER writing new ones.
        if ini_dir.exists():
            for ini in ini_dir.iterdir():
                if ini.is_file() and ini.suffix == ".ini" and ini.stem not in keep:
                    try:
                        ini.unlink()
                    except OSError as e:
                        summary.media_errors.append(f"cleanup {ini.name}: {e}")
        print(f"[{target_system}] PCLauncher INIs done.", flush=True)

    # ── Phase 4: HyperSpin system settings INI ────────────────────────────────
    # HyperSpin requires Settings/<system>.ini to open a sub-wheel.  Without
    # it the wheel reports "Cannot find <system>.ini" on selection.  We only
    # write when the file is absent so user customisations are never clobbered.
    hs_dir = Path(config.hyperspin_dir)
    write_hyperspin_system_ini(target_system, hs_dir)

    # ── Phase 5: Bundled system media (wheel art, background, music) ──────────
    # Install all package-bundled assets for this synthetic system.
    # Each asset is only written when absent — user files are never clobbered.
    summary.bundled_assets = install_bundled_system_assets(hs_dir, target_system)

    print(f"[{target_system}] wheel build complete.", flush=True)
    return summary


def rebuild(
    config: Config,
    *,
    target_system: str = DEFAULT_RECENT_SYSTEM,
    limit: int = DEFAULT_LIMIT,
    media_mode: LinkMode = LinkMode.COPY,
    skip_media: bool = False,
    skip_launchers: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> RecentSummary:
    """Regenerate the Recently Played system from RocketLauncher stats.

    Re-uses the same launcher and media-mirror plumbing as
    :func:`spindoctor.favorites.rebuild` so the two synthetic systems
    behave identically inside HyperSpin.

    When ``dry_run`` is true, returns a populated summary describing
    what would be written without touching disk.
    """
    if not config.hyperspin_dir:
        return RecentSummary(target_system=target_system)

    # Restrict to real source systems only — exclude synthetic wheel directories
    # (Databases/Favorites/ etc. exist on disk and would otherwise pass the
    # known-system filter, letting stray stats entries leak into this wheel).
    known = set(get_systems(config)) - _STATS_EXCLUDE - {target_system}
    read_warnings: list[str] = []
    read_notes: list[str] = []
    raw = collect_play_records(
        config,
        exclude_systems=_STATS_EXCLUDE | {target_system},
        warnings=read_warnings,
        notes=read_notes,
    )
    raw = [r for r in raw if r.system in known]
    top = top_recent(raw, limit=limit)

    # Sort newest-first so HyperSpin renders them in play order.
    pseudo_entries = [
        FavoriteEntry(
            system=r.system, rom_name=r.rom_name,
            display_name="", added=r.isoformat(),
        )
        for r in top
    ]
    if dry_run:
        summary = RecentSummary(target_system=target_system)
        summary.entries = len(pseudo_entries)
        if not skip_launchers:
            summary.inis_written = len(pseudo_entries)
        if not skip_media:
            summary.media_linked = len(pseudo_entries)
        summary.read_warnings = read_warnings
        summary.read_notes = read_notes
        if config.hyperspin_dir:
            summary.bundled_assets = install_bundled_system_assets(
                Path(config.hyperspin_dir), target_system, dry_run=True
            )
        return summary
    summary = _build_synthetic_wheel(
        config, target_system, pseudo_entries,
        media_mode=media_mode, skip_media=skip_media,
        skip_launchers=skip_launchers, verbose=verbose,
    )
    summary.read_warnings = read_warnings
    summary.read_notes = read_notes
    return summary


# ─── standalone CLI (python -m spindoctor.recent …) ──────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spindoctor-recent",
        description="Regenerate the Recently Played HyperSpin wheel from "
                    "RocketLauncher launch statistics.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_reb = sub.add_parser("rebuild", help="Rebuild the Recently Played system")
    p_reb.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                       help=f"How many recent games to keep (default {DEFAULT_LIMIT}).")
    p_reb.add_argument("--target-system", default=DEFAULT_RECENT_SYSTEM,
                       help=f"Synthetic system name (default '{DEFAULT_RECENT_SYSTEM}').")
    p_reb.add_argument("--media-mode",
                       choices=["link", "symlink", "copy", "auto", "none"],
                       default="auto")
    p_reb.add_argument("--apply", action="store_true",
                       help="Commit the rebuild (default: dry-run preview).")
    p_reb.add_argument("--verbose", action="store_true",
                       help="Print each media file copied/linked (src → dest).")

    sub.add_parser("list", help="Print the current top-N play records")

    p_clr = sub.add_parser(
        "clear",
        help="Remove the synthetic Recently Played wheel from disk",
    )
    p_clr.add_argument(
        "--target-system", default=DEFAULT_RECENT_SYSTEM,
        help=f"Synthetic system name to clear (default '{DEFAULT_RECENT_SYSTEM}').",
    )
    p_clr.add_argument(
        "--apply", action="store_true",
        help="Actually delete files (default: dry-run preview).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    from ._compat import enable_windows_utf8_console
    enable_windows_utf8_console()
    args = _build_parser().parse_args(argv)
    config = load_config()

    if args.cmd == "list":
        records = collect_play_records(config)
        for r in top_recent(records):
            print(f"  · {r.last_played:%Y-%m-%d %H:%M}  "
                  f"[{r.system}] {r.rom_name}  ({r.play_count}×)")
        if not records:
            print("(no statistics found)")
        return 0

    if args.cmd == "rebuild":
        if not config.hyperspin_dir:
            print("ERROR: hyperspin_dir is not configured.", file=sys.stderr)
            return 1
        if not config.rocketlauncher_dir:
            print(
                "WARNING: rocketlauncher_dir is not configured — no system INI or "
                "PCLauncher INIs will be written.",
                file=sys.stderr,
            )
        elif not Path(config.rocketlauncher_dir).exists():
            print(
                f"WARNING: rocketlauncher_dir '{config.rocketlauncher_dir}' is "
                "configured but does not exist on disk — no system INI or "
                "PCLauncher INIs will be written.",
                file=sys.stderr,
            )
        skip_media = args.media_mode == "none"
        mode = LinkMode.AUTO if skip_media else LinkMode(args.media_mode)
        if not args.apply:
            print("[DRY RUN] No files will be written. Re-run with --apply to commit.")
        summary = rebuild(
            config,
            target_system=args.target_system,
            limit=args.limit,
            media_mode=mode,
            skip_media=skip_media,
            dry_run=not args.apply,
            verbose=getattr(args, "verbose", False),
        )
        print(f"Recently Played system: {summary.target_system}")
        for note in summary.read_notes:
            print(f"  source:     {note}")
        print(f"  entries:    {summary.entries}")
        print(f"  pruned:     {summary.pruned}")
        print(f"  db:         {summary.db_path}")
        print(f"  media:      linked={summary.media_linked} "
              f"copied={summary.media_copied} skipped={summary.media_skipped}")
        if summary.media_errors:
            print(f"  errors:     {len(summary.media_errors)}")
            for e in summary.media_errors[:5]:
                print(f"    - {e}", file=sys.stderr)
        print(f"  launchers:  {summary.inis_written}")
        if summary.system_ini_path:
            print(f"  system INI: {summary.system_ini_path}")
        else:
            print("  system INI: skipped (rocketlauncher_dir not set)")
        for w in summary.read_warnings:
            print(f"  WARNING:    {w}", file=sys.stderr)
        return 0

    if args.cmd == "clear":
        if not config.hyperspin_dir and not config.rocketlauncher_dir:
            print("ERROR: neither hyperspin_dir nor rocketlauncher_dir is configured.",
                  file=sys.stderr)
            return 1
        target_system = args.target_system
        if not args.apply:
            print("[DRY RUN] No files will be deleted. "
                  "Re-run with --apply to commit.")
        summary = clear_wheel_artifacts(
            config, target_system, dry_run=not args.apply,
        )
        verb = "Would remove" if not args.apply else "Removed"
        print(f"Clear wheel: {target_system}")
        if summary.db_removed:
            print(f"  {verb}: Databases/{target_system}/{target_system}.xml")
        else:
            print("  database: not found (nothing to remove)")
        print(f"  {verb}: {summary.media_files_removed} media file(s) "
              f"under Media/{target_system}/")
        print(f"  {verb}: {summary.ini_files_removed} PCLauncher INI(s)")
        print("  Note: RocketLauncher Statistics.ini files are not modified.")
        if summary.errors:
            print(f"  {len(summary.errors)} error(s):", file=sys.stderr)
            for e in summary.errors[:5]:
                print(f"    - {e}", file=sys.stderr)
        return 0 if not summary.errors else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
