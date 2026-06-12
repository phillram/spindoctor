"""Playtime / stats reporting — aggregate RocketLauncher launch statistics.

RocketLauncher persists per-game launch counts and durations in one of
several locations depending on version and configuration:

  * ``<rocketlauncher_dir>/Settings/Global Statistics/<System>.ini``  (classic)
  * ``<rocketlauncher_dir>/Settings/<System>/Statistics.ini``  (oldest)
  * ``<rocketlauncher_dir>/Data/Statistics/<System>.ini``  (newer RL)

An aggregate summary (top-10 lists only) is also written to
``<rocketlauncher_dir>/Data/Statistics/Global Statistics.ini`` and is
used as a fallback when no per-game files are found.

This module reads those files, exposes the data as :class:`PlayStat`
records, computes summaries (total time, top-N, per-system breakdown),
and can regenerate a synthetic "Most Played" HyperSpin wheel.
"""
from __future__ import annotations

import argparse
import configparser
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import Config, get_systems, load_config
from .favorites import FavoriteEntry
from .medialink import LinkMode
from .recent import SYNTHETIC_SYSTEM_NAMES, _build_synthetic_wheel, _parse_time


DEFAULT_PLAYED_SYSTEM = "Most Played"
DEFAULT_TOP_N = 20


@dataclass
class PlayStat:
    """Aggregated playtime info for one (system, game)."""
    system: str
    game: str
    display_name: str
    times_played: int = 0
    total_seconds: int = 0
    last_played: Optional[datetime] = None
    average_seconds: int = 0


@dataclass
class SystemSummary:
    """Per-system roll-up of playtime."""
    system: str
    total_seconds: int = 0
    unique_games_played: int = 0
    times_played: int = 0


# ─── parsing ──────────────────────────────────────────────────────────────────

def _coerce_int(raw: str) -> int:
    raw = (raw or "").strip()
    if not raw:
        return 0
    try:
        # RocketLauncher sometimes writes floating-point seconds.
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _read_playstats_file(
    path: Path,
    system_name: str,
    *,
    warnings: "list[str] | None" = None,
) -> list[PlayStat]:
    """Parse one Statistics.ini file into PlayStat records.

    The format used by RocketLauncher::

        [GameName]
        Number_of_Times_Played=12
        Total_Time_Played=3601
        Last_Played=2026-04-27 18:33:12
        Average_Time_Played=300
    """
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        if warnings is not None:
            warnings.append(
                f"Could not read stats file {path}: {type(exc).__name__}: {exc}"
            )
        return []

    out: list[PlayStat] = []
    for section in parser.sections():
        if section.lower() in ("settings", "global"):
            continue
        times = _coerce_int(parser.get(section, "Number_of_Times_Played", fallback="0"))
        total = _coerce_int(parser.get(section, "Total_Time_Played", fallback="0"))
        avg = _coerce_int(parser.get(section, "Average_Time_Played", fallback="0"))
        last_raw = (
            parser.get(section, "Last_Played", fallback="")
            or parser.get(section, "LastPlayed", fallback="")
        )
        last = _parse_time(last_raw) if last_raw else None

        # Skip records that have no signal at all.
        if times == 0 and total == 0 and last is None:
            continue
        out.append(PlayStat(
            system=system_name,
            game=section,
            display_name=section,
            times_played=times,
            total_seconds=total,
            last_played=last,
            average_seconds=avg,
        ))
    return out


_GLOBAL_STATS_SKIP_SYSTEMS = frozenset({"toolkit"})


def _read_global_statistics_ini(
    path: Path,
    *,
    exclude_systems: "frozenset[str] | None" = None,
    warnings: "list[str] | None" = None,
) -> list[PlayStat]:
    """Parse RocketLauncher's aggregate ``Global Statistics.ini`` for playtime data.

    This file (``Data/Statistics/Global Statistics.ini``) contains top-10
    summaries rather than full per-game history.  It is used as a fallback
    when no per-system ``<system>.ini`` files are found.  Entries from the
    ``Toolkit`` pseudo-system are skipped.  *exclude_systems* is applied on
    top so that synthetic wheel names (Favorites, Recently Played, Most Played)
    are also dropped when this function is called from :func:`load_all_playtime`.

    Reads two sections:
      * ``[TopTen_Time_Played]`` — total seconds per game
      * ``[TopTen_Times_Played]`` — number of sessions per game
    """
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(path, encoding="utf-8-sig")
    except (OSError, configparser.Error) as exc:
        if warnings is not None:
            warnings.append(
                f"Could not read Global Statistics file {path}: "
                f"{type(exc).__name__}: {exc}"
            )
        return []

    by_key: dict[tuple[str, str], PlayStat] = {}

    # --- [TopTen_Time_Played] ---
    section = "TopTen_Time_Played"
    if parser.has_section(section):
        i = 1
        while True:
            sys_key = f"{i}_System"
            if not parser.has_option(section, sys_key):
                break
            system = parser.get(section, sys_key, fallback="").strip()
            name = parser.get(section, f"{i}_Name", fallback="").strip()
            total = _coerce_int(
                parser.get(section, f"{i}_Time_Played", fallback="0")
            )
            i += 1
            if not system or not name:
                continue
            if system.lower() in _GLOBAL_STATS_SKIP_SYSTEMS:
                continue
            if exclude_systems and system in exclude_systems:
                continue
            key = (system, name)
            by_key[key] = PlayStat(
                system=system, game=name, display_name=name,
                total_seconds=total,
            )

    # --- [TopTen_Times_Played] ---
    section2 = "TopTen_Times_Played"
    if parser.has_section(section2):
        i = 1
        while True:
            sys_key = f"{i}_System"
            if not parser.has_option(section2, sys_key):
                break
            system = parser.get(section2, sys_key, fallback="").strip()
            name = parser.get(section2, f"{i}_Name", fallback="").strip()
            count = _coerce_int(
                parser.get(section2, f"{i}_Times_Played", fallback="0")
            )
            i += 1
            if not system or not name:
                continue
            if system.lower() in _GLOBAL_STATS_SKIP_SYSTEMS:
                continue
            if exclude_systems and system in exclude_systems:
                continue
            key = (system, name)
            if key in by_key:
                by_key[key].times_played = count
            else:
                by_key[key] = PlayStat(
                    system=system, game=name, display_name=name,
                    times_played=count,
                )

    return list(by_key.values())


def load_all_playtime(
    config: Config,
    *,
    exclude_systems: "frozenset[str] | set[str] | None" = SYNTHETIC_SYSTEM_NAMES,
    warnings: "list[str] | None" = None,
    notes: "list[str] | None" = None,
) -> list[PlayStat]:
    """Read every Statistics.ini under the RocketLauncher tree.

    Checks three locations:
      * ``<RocketLauncher>/Settings/Global Statistics/<system>.ini`` (classic layout)
      * ``<RocketLauncher>/Settings/<system>/Statistics.ini`` (oldest layout)
      * ``<RocketLauncher>/Data/Statistics/<system>.ini`` (newer RL layout)

    If none of those per-system files yield records, falls back to reading
    the aggregate ``Data/Statistics/Global Statistics.ini`` summary (top-10
    lists only, but better than an empty wheel).

    Records keyed on the same ``(system, game)`` pair are merged
    (newest ``last_played`` wins; counts are summed).

    *exclude_systems* — system names to skip entirely when reading stats.
    Defaults to :data:`~spindoctor.recent.SYNTHETIC_SYSTEM_NAMES` so that
    sessions launched *from* a synthetic wheel (where RL#1 records the play
    under the synthetic system name) do not pollute the Most Played list.
    Pass ``None`` or an empty set to read all systems.

    Pass a list to *notes* to receive informational messages describing which
    paths were found and used (useful for CLI / GUI diagnostics).
    """
    if not config.rocketlauncher_dir:
        return []
    rl = Path(config.rocketlauncher_dir)
    by_key: dict[tuple[str, str], PlayStat] = {}
    _excluded: frozenset[str] = frozenset(exclude_systems) if exclude_systems else frozenset()

    def _note(msg: str) -> None:
        if notes is not None:
            notes.append(msg)

    def _is_excluded(name: str) -> bool:
        return name in _excluded

    def _merge(stats: Iterable[PlayStat]) -> None:
        for s in stats:
            key = (s.system, s.game)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = s
                continue
            existing.times_played += s.times_played
            existing.total_seconds += s.total_seconds
            if s.last_played and (
                existing.last_played is None or s.last_played > existing.last_played
            ):
                existing.last_played = s.last_played
            # Recompute average from totals when both sides agree.
            if existing.times_played > 0 and existing.total_seconds > 0:
                existing.average_seconds = existing.total_seconds // existing.times_played
            elif s.average_seconds:
                existing.average_seconds = s.average_seconds

    # Classic layout: Settings/Global Statistics/<system>.ini
    global_dir = rl / "Settings" / "Global Statistics"
    if global_dir.is_dir():
        before = len(by_key)
        for ini in global_dir.glob("*.ini"):
            if _is_excluded(ini.stem):
                continue
            _merge(_read_playstats_file(ini, ini.stem, warnings=warnings))
        added = len(by_key) - before
        if added:
            _note(f"Settings/Global Statistics/: {added} game(s) from "
                  f"{len(list(global_dir.glob('*.ini')))} system file(s)")

    # Oldest layout: Settings/<system>/Statistics.ini
    settings_dir = rl / "Settings"
    if settings_dir.is_dir():
        before = len(by_key)
        sys_dirs_with_stats: list[str] = []
        for sys_dir in settings_dir.iterdir():
            if not sys_dir.is_dir():
                continue
            if _is_excluded(sys_dir.name):
                continue
            stats = sys_dir / "Statistics.ini"
            if stats.is_file():
                _merge(_read_playstats_file(stats, sys_dir.name, warnings=warnings))
                sys_dirs_with_stats.append(sys_dir.name)
        added = len(by_key) - before
        if added:
            _note(f"Settings/<system>/Statistics.ini: {added} game(s) from "
                  f"{len(sys_dirs_with_stats)} system(s)")

    # Newer layout: Data/Statistics/<system>.ini
    # Skip the aggregate "Global Statistics.ini" here — it's handled below.
    data_stats_dir = rl / "Data" / "Statistics"
    if data_stats_dir.is_dir():
        before = len(by_key)
        data_files = [
            ini for ini in data_stats_dir.glob("*.ini")
            if ini.stem.lower() != "global statistics"
            and not _is_excluded(ini.stem)
        ]
        for ini in data_files:
            _merge(_read_playstats_file(ini, ini.stem, warnings=warnings))
        added = len(by_key) - before
        if added:
            _note(f"Data/Statistics/: {added} game(s) from "
                  f"{len(data_files)} system file(s)")
        elif data_files:
            _note(f"Data/Statistics/: found {len(data_files)} system file(s) "
                  f"but 0 parseable records (files may be empty or unrecognised format)")

    # Fallback: use the aggregate Global Statistics.ini when no per-game data
    # was found anywhere (top-10 summaries are better than a blank wheel).
    if not by_key:
        global_stats_path = rl / "Data" / "Statistics" / "Global Statistics.ini"
        if global_stats_path.is_file():
            before = len(by_key)
            _merge(_read_global_statistics_ini(
                global_stats_path,
                exclude_systems=_excluded if _excluded else None,
                warnings=warnings,
            ))
            added = len(by_key) - before
            if added:
                _note(
                    f"Data/Statistics/Global Statistics.ini (fallback): "
                    f"{added} game(s) — this file contains only top-10 summaries, "
                    f"not full history.  Per-system stats files were not found."
                )
            else:
                _note(
                    "Data/Statistics/Global Statistics.ini exists but contains "
                    "no recognisable playtime data."
                )
        else:
            _note(
                "No stats files found in any of the searched locations.  "
                "Check that rocketlauncher_dir is set correctly and that "
                "RocketLauncher has recorded at least one game launch."
            )

    return list(by_key.values())


# ─── aggregation ──────────────────────────────────────────────────────────────

def aggregate_by_system(stats: Iterable[PlayStat]) -> list[SystemSummary]:
    """Roll PlayStats up by source system, sorted by total_seconds desc."""
    by_sys: dict[str, SystemSummary] = {}
    for s in stats:
        summary = by_sys.setdefault(s.system, SystemSummary(system=s.system))
        summary.total_seconds += s.total_seconds
        summary.times_played += s.times_played
        if s.times_played > 0 or s.total_seconds > 0:
            summary.unique_games_played += 1
    return sorted(by_sys.values(), key=lambda s: s.total_seconds, reverse=True)


def top_games(
    stats: Iterable[PlayStat],
    n: int = DEFAULT_TOP_N,
    scope: str = "all",
) -> list[PlayStat]:
    """Return the *n* games with the highest total_seconds.

    If *scope* is anything other than ``"all"`` it's interpreted as a
    system-name filter (case-insensitive).
    """
    if scope and scope != "all":
        scope_l = scope.strip().lower()
        filtered = [s for s in stats if s.system.strip().lower() == scope_l]
    else:
        filtered = list(stats)
    filtered.sort(key=lambda s: (s.total_seconds, s.times_played), reverse=True)
    return filtered[: max(0, n)]


def most_recent(
    stats: Iterable[PlayStat],
    n: int = DEFAULT_TOP_N,
) -> list[PlayStat]:
    """Return the *n* games sorted newest-first by ``last_played``.

    Records with no timestamp are excluded.
    """
    timed = [s for s in stats if s.last_played is not None]
    timed.sort(key=lambda s: s.last_played, reverse=True)  # type: ignore[arg-type,return-value]
    return timed[: max(0, n)]


def total_seconds(stats: Iterable[PlayStat]) -> int:
    return sum(s.total_seconds for s in stats)


def total_sessions(stats: Iterable[PlayStat]) -> int:
    return sum(s.times_played for s in stats)


# ─── formatting / export ──────────────────────────────────────────────────────

def format_duration(seconds: int) -> str:
    """Render *seconds* as ``1d 2h 3m`` / ``45m 12s`` / ``5s``.

    Negative or non-numeric inputs collapse to ``0s``.
    """
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return "0s"

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:  # drop minutes once we're talking days+
        parts.append(f"{minutes}m")
    if secs and not (days or hours):
        parts.append(f"{secs}s")
    return " ".join(parts)


def export_csv(stats: Iterable[PlayStat], path: Path) -> Path:
    """Write all stats to *path* as CSV.  Returns the written path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        stats,
        key=lambda s: (s.system.lower(), -s.total_seconds, s.game.lower()),
    )
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "system", "game", "display_name", "times_played",
            "total_seconds", "total_played", "last_played", "average_seconds",
        ])
        for s in rows:
            writer.writerow([
                s.system, s.game, s.display_name,
                s.times_played, s.total_seconds, format_duration(s.total_seconds),
                s.last_played.isoformat(timespec="seconds") if s.last_played else "",
                s.average_seconds,
            ])
    return path


def export_json(stats: Iterable[PlayStat], path: Path) -> Path:
    """Dump all stats + per-system roll-up to *path* as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    materialised = list(stats)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "total_seconds": total_seconds(materialised),
            "total_sessions": total_sessions(materialised),
            "unique_games": sum(
                1 for s in materialised
                if s.times_played > 0 or s.total_seconds > 0
            ),
        },
        "per_system": [asdict(s) for s in aggregate_by_system(materialised)],
        "stats": [
            {
                **asdict(s),
                "last_played": (
                    s.last_played.isoformat(timespec="seconds")
                    if s.last_played else None
                ),
            }
            for s in materialised
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ─── synthetic "Most Played" wheel ────────────────────────────────────────────

def build_most_played_wheel(
    config: Config,
    *,
    target_system: str = DEFAULT_PLAYED_SYSTEM,
    limit: int = DEFAULT_TOP_N,
    media_mode: LinkMode = LinkMode.COPY,
    skip_media: bool = False,
    skip_launchers: bool = False,
    register_in_main_menu: bool = True,
    verbose: bool = False,
):
    """Regenerate a synthetic "Most Played" HyperSpin system.

    Mirrors :func:`spindoctor.recent.rebuild` — top-N by total playtime
    across every known source system, written as a synthetic wheel with
    media hardlinks and PCLauncher INIs that route launches back to the
    original system.

    When *register_in_main_menu* is true, the synthetic system is added
    to the HyperSpin Main Menu (idempotent — no-op if already present).
    """
    if not config.hyperspin_dir:
        from .recent import RecentSummary
        return RecentSummary(target_system=target_system)

    # Restrict to real source systems only — exclude synthetic wheel directories
    # (Databases/Favorites/ etc. exist on disk and would otherwise pass the
    # known-system filter, letting stray stats entries leak into this wheel).
    known = set(get_systems(config)) - SYNTHETIC_SYSTEM_NAMES - {target_system}
    read_warnings: list[str] = []
    read_notes: list[str] = []
    stats = [
        s for s in load_all_playtime(
            config,
            exclude_systems=SYNTHETIC_SYSTEM_NAMES | {target_system},
            warnings=read_warnings,
            notes=read_notes,
        )
        if s.system in known
    ]
    top = top_games(stats, n=limit, scope="all")

    pseudo_entries = [
        FavoriteEntry(
            system=s.system, rom_name=s.game,
            display_name="",
            added=(
                s.last_played.isoformat(timespec="seconds")
                if s.last_played else ""
            ),
        )
        for s in top
    ]
    summary = _build_synthetic_wheel(
        config, target_system, pseudo_entries,
        media_mode=media_mode, skip_media=skip_media,
        skip_launchers=skip_launchers, verbose=verbose,
    )
    summary.read_warnings = read_warnings
    summary.read_notes = read_notes

    if register_in_main_menu and summary.entries > 0:
        try:
            from . import mainmenu as mm
            menu = mm.load_main_menu(config)
            if mm.add_system(menu, target_system):
                mm.save_main_menu(menu, config)
        except (OSError, ValueError):
            # Main Menu update is best-effort — a missing/corrupt menu
            # shouldn't fail an otherwise-successful wheel rebuild.
            pass

    return summary


# ─── standalone CLI (python -m spindoctor.playtime …) ────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spindoctor-stats",
        description="RocketLauncher playtime reporting + Most Played wheel.",
    )
    sub = p.add_subparsers(dest="cmd")

    p_sum = sub.add_parser("summary", help="Overall summary (default)")
    p_sum.add_argument("--top", type=int, default=10)

    p_top = sub.add_parser("top", help="Top-N games by total playtime")
    p_top.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    p_top.add_argument("--system", default=None,
                       help="Restrict to one system.")

    p_rec = sub.add_parser("recent", help="Most recently played")
    p_rec.add_argument("--top", type=int, default=DEFAULT_TOP_N)

    sub.add_parser("system", help="Per-system breakdown")

    p_bw = sub.add_parser("build-wheel",
                          help="Generate the Most Played HyperSpin wheel")
    p_bw.add_argument("--limit", type=int, default=DEFAULT_TOP_N)
    p_bw.add_argument("--target-system", default=DEFAULT_PLAYED_SYSTEM)
    p_bw.add_argument("--media-mode",
                      choices=["link", "symlink", "copy", "auto", "none"],
                      default="copy")
    p_bw.add_argument("--apply", action="store_true",
                      help="Actually write files (default is dry-run).")
    p_bw.add_argument("--verbose", action="store_true",
                      help="Print each media file copied/linked (src → dest).")

    p_cw = sub.add_parser(
        "clear-wheel",
        help="Remove the synthetic Most Played wheel from disk",
    )
    p_cw.add_argument(
        "--target-system", default=DEFAULT_PLAYED_SYSTEM,
        help=f"Synthetic system name to clear (default '{DEFAULT_PLAYED_SYSTEM}').",
    )
    p_cw.add_argument(
        "--apply", action="store_true",
        help="Actually delete files (default: dry-run preview).",
    )
    return p


def _print_summary(stats: list[PlayStat], top_n: int = 10) -> None:
    if not stats:
        print("(no statistics found)")
        return
    print(f"Total playtime:  {format_duration(total_seconds(stats))}")
    print(f"Sessions:        {total_sessions(stats)}")
    played = [s for s in stats if s.times_played > 0 or s.total_seconds > 0]
    print(f"Unique games:    {len(played)}")
    by_sys = aggregate_by_system(stats)
    if by_sys:
        print(f"Most-played sys: {by_sys[0].system}  "
              f"({format_duration(by_sys[0].total_seconds)})")

    print(f"\nTop {top_n} most played:")
    for s in top_games(stats, n=top_n):
        print(f"  · {format_duration(s.total_seconds):>12}  "
              f"[{s.system}] {s.game}  ({s.times_played}x)")

    print(f"\nTop {top_n} most recent:")
    for s in most_recent(stats, n=top_n):
        when = s.last_played.strftime("%Y-%m-%d %H:%M") if s.last_played else "?"
        print(f"  · {when}  [{s.system}] {s.game}")


def main(argv: Optional[list[str]] = None) -> int:
    from ._compat import enable_windows_utf8_console
    enable_windows_utf8_console()
    args = _build_parser().parse_args(argv)
    config = load_config()

    cmd = args.cmd or "summary"

    if cmd == "summary":
        _print_summary(load_all_playtime(config), top_n=args.top)
        return 0

    if cmd == "top":
        stats = load_all_playtime(config)
        scope = args.system or "all"
        rows = top_games(stats, n=args.top, scope=scope)
        if not rows:
            print("(no statistics found)")
            return 0
        for s in rows:
            print(f"  · {format_duration(s.total_seconds):>12}  "
                  f"[{s.system}] {s.game}  ({s.times_played}x)")
        return 0

    if cmd == "recent":
        rows = most_recent(load_all_playtime(config), n=args.top)
        if not rows:
            print("(no statistics found)")
            return 0
        for s in rows:
            when = s.last_played.strftime("%Y-%m-%d %H:%M") if s.last_played else "?"
            print(f"  · {when}  [{s.system}] {s.game}")
        return 0

    if cmd == "system":
        rows = aggregate_by_system(load_all_playtime(config))
        if not rows:
            print("(no statistics found)")
            return 0
        for s in rows:
            print(f"  · {format_duration(s.total_seconds):>12}  "
                  f"{s.system}  "
                  f"({s.unique_games_played} games, {s.times_played}x)")
        return 0

    if cmd == "build-wheel":
        if not config.hyperspin_dir:
            print("ERROR: hyperspin_dir is not configured.", file=sys.stderr)
            return 1
        if not args.apply:
            stats = load_all_playtime(config)
            top = top_games(stats, n=args.limit)
            print(f"DRY RUN — would build '{args.target_system}' "
                  f"with {len(top)} entries:")
            for s in top:
                print(f"  · {format_duration(s.total_seconds):>12}  "
                      f"[{s.system}] {s.game}")
            print("(re-run with --apply to write)")
            return 0
        skip_media = args.media_mode == "none"
        mode = LinkMode.AUTO if skip_media else LinkMode(args.media_mode)
        summary = build_most_played_wheel(
            config,
            target_system=args.target_system,
            limit=args.limit,
            media_mode=mode,
            skip_media=skip_media,
            verbose=getattr(args, "verbose", False),
        )
        print(f"Most Played system: {summary.target_system}")
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
        for w in summary.read_warnings:
            print(f"  WARNING:    {w}", file=sys.stderr)
        return 0

    if cmd == "clear-wheel":
        from .recent import clear_wheel_artifacts
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
