"""Playtime / stats reporting — aggregate RocketLauncher launch statistics.

RocketLauncher persists per-game launch counts and durations in
``<rocketlauncher_dir>/Settings/Global Statistics/<System>.ini`` (and a
fallback ``<rocketlauncher_dir>/Settings/<System>/Statistics.ini`` for
older layouts).  This module reads those files, exposes the data as
:class:`PlayStat` records, computes summaries (total time, top-N,
per-system breakdown), and can regenerate a synthetic "Most Played"
HyperSpin wheel of the user's most-played games.

Parsing is delegated to :mod:`spindoctor.recent` so the two modules
agree on key names, timestamp formats, and which sections to skip.
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
from .recent import _build_synthetic_wheel, _parse_time


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


def _read_playstats_file(path: Path, system_name: str) -> list[PlayStat]:
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
    except (OSError, configparser.Error):
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


def load_all_playtime(config: Config) -> list[PlayStat]:
    """Read every Statistics.ini under the RocketLauncher tree.

    Looks in:
      * ``<RocketLauncher>/Settings/Global Statistics/<system>.ini``
      * ``<RocketLauncher>/Settings/<system>/Statistics.ini`` (older layout)

    Records keyed on the same ``(system, game)`` pair are merged
    (newest ``last_played`` wins; counts are summed).
    """
    if not config.rocketlauncher_dir:
        return []
    rl = Path(config.rocketlauncher_dir)
    by_key: dict[tuple[str, str], PlayStat] = {}

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

    global_dir = rl / "Settings" / "Global Statistics"
    if global_dir.is_dir():
        for ini in global_dir.glob("*.ini"):
            _merge(_read_playstats_file(ini, ini.stem))

    settings_dir = rl / "Settings"
    if settings_dir.is_dir():
        for sys_dir in settings_dir.iterdir():
            if not sys_dir.is_dir():
                continue
            stats = sys_dir / "Statistics.ini"
            if stats.is_file():
                _merge(_read_playstats_file(stats, sys_dir.name))

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
    if not parts:
        # Edge case: e.g. exactly 1 day.
        if days:
            parts.append(f"{days}d")
        elif hours:
            parts.append(f"{hours}h")
        elif minutes:
            parts.append(f"{minutes}m")
        else:
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
    media_mode: LinkMode = LinkMode.AUTO,
    skip_media: bool = False,
    skip_launchers: bool = False,
    register_in_main_menu: bool = True,
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

    known = set(get_systems(config))
    stats = [s for s in load_all_playtime(config) if s.system in known]
    top = top_games(stats, n=limit, scope="all")

    pseudo_entries = [
        FavoriteEntry(
            system=s.system, rom_name=s.game,
            display_name=s.display_name or s.game,
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
        skip_launchers=skip_launchers,
    )

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

    p_sys = sub.add_parser("system", help="Per-system breakdown")

    p_bw = sub.add_parser("build-wheel",
                          help="Generate the Most Played HyperSpin wheel")
    p_bw.add_argument("--limit", type=int, default=DEFAULT_TOP_N)
    p_bw.add_argument("--target-system", default=DEFAULT_PLAYED_SYSTEM)
    p_bw.add_argument("--media-mode",
                      choices=["link", "symlink", "copy", "auto", "none"],
                      default="auto")
    p_bw.add_argument("--apply", action="store_true",
                      help="Actually write files (default is dry-run).")
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
        )
        print(f"Most Played system: {summary.target_system}")
        print(f"  entries:    {summary.entries}")
        print(f"  pruned:     {summary.pruned}")
        print(f"  db:         {summary.db_path}")
        print(f"  media:      linked={summary.media_linked} "
              f"copied={summary.media_copied} skipped={summary.media_skipped}")
        if summary.media_errors:
            print(f"  errors:     {len(summary.media_errors)}")
        print(f"  launchers:  {summary.inis_written}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
