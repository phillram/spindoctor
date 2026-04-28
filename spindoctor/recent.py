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
from .medialink import LinkMode, apply_plan, plan_mirror


DEFAULT_RECENT_SYSTEM = "Recently Played"
DEFAULT_LIMIT = 20
_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
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


def _read_stats_file(path: Path, system_name: str) -> list[PlayRecord]:
    """Parse one RocketLauncher Statistics.ini file into PlayRecords.

    The format used by RocketLauncher::

        [GameName]
        Last_Played=2026-04-27 18:33:12
        Number_of_Times_Played=12
        Total_Time_Played=...

    System-level keys (no specific game) are ignored.
    """
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return []

    records: list[PlayRecord] = []
    for section in parser.sections():
        if section.lower() in ("settings", "global"):
            continue
        last_raw = (
            parser.get(section, "Last_Played", fallback="")
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


def collect_play_records(config: Config) -> list[PlayRecord]:
    """Walk RocketLauncher's Statistics tree and return every game launch.

    Looks in two locations:
      * ``<RocketLauncher>/Settings/Global Statistics/<system>.ini``
      * ``<RocketLauncher>/Settings/<system>/Statistics.ini`` (older layout)
    """
    if not config.rocketlauncher_dir:
        return []
    rl = Path(config.rocketlauncher_dir)
    records: list[PlayRecord] = []

    global_dir = rl / "Settings" / "Global Statistics"
    if global_dir.is_dir():
        for ini in global_dir.glob("*.ini"):
            records.extend(_read_stats_file(ini, ini.stem))

    settings_dir = rl / "Settings"
    if settings_dir.is_dir():
        for sys_dir in settings_dir.iterdir():
            stats = sys_dir / "Statistics.ini"
            if stats.is_file():
                records.extend(_read_stats_file(stats, sys_dir.name))

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


def rebuild(
    config: Config,
    *,
    target_system: str = DEFAULT_RECENT_SYSTEM,
    limit: int = DEFAULT_LIMIT,
    media_mode: LinkMode = LinkMode.AUTO,
    skip_media: bool = False,
    skip_launchers: bool = False,
) -> RecentSummary:
    """Regenerate the Recently Played system from RocketLauncher stats.

    Re-uses the same launcher and media-mirror plumbing as
    :func:`spindoctor.favorites.rebuild` so the two synthetic systems
    behave identically inside HyperSpin.
    """
    summary = RecentSummary(target_system=target_system)
    if not config.hyperspin_dir:
        return summary

    # Restrict to systems we actually know about so a stray INI doesn't
    # break the rebuild with an unknown source DB.
    known = set(get_systems(config))
    raw = collect_play_records(config)
    raw = [r for r in raw if r.system in known]
    top = top_recent(raw, limit=limit)

    # Sort newest-first so HyperSpin renders them in play order.
    pseudo_entries = [
        FavoriteEntry(
            system=r.system, rom_name=r.rom_name,
            display_name=r.rom_name, added=r.isoformat(),
        )
        for r in top
    ]
    target_names = _resolve_target_names(pseudo_entries)
    summary.entries = len(target_names)

    db_path = config.databases_dir / target_system / f"{target_system}.xml"
    db = HyperspinDatabase(target_system, db_path)
    db.load()
    keep = set(target_names.values())
    for name in list(db.games().keys()):
        if name not in keep:
            db.remove_game(name)
            summary.pruned += 1

    for r, fe in zip(top, pseudo_entries):
        target_name = target_names[f"{fe.system}::{fe.rom_name}"]
        source_db = _safe_load(r.system, config)
        source_game = source_db.get(r.rom_name) if source_db else None
        merged = GameEntry(
            name=target_name,
            description=(source_game.description if source_game else r.rom_name),
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

    if not skip_media:
        seen = set(target_names.values())
        for media_path in (config.media_dir / target_system).rglob("*"):
            if media_path.is_file() and media_path.stem not in seen:
                try:
                    media_path.unlink()
                except OSError:
                    pass
        for r, fe in zip(top, pseudo_entries):
            target_name = target_names[f"{fe.system}::{fe.rom_name}"]
            plan = plan_mirror(
                config.media_dir, r.system, target_system,
                r.rom_name, target_name,
            )
            result = apply_plan(plan, mode=media_mode)
            summary.media_linked += result["linked"]
            summary.media_copied += result["copied"]
            summary.media_skipped += result["skipped"]
            summary.media_errors.extend(result["errors"])

    if not skip_launchers and config.rocketlauncher_dir:
        rl_dir = Path(config.rocketlauncher_dir)
        ini_dir = rl_dir / "Modules" / "PCLauncher" / target_system
        if ini_dir.exists():
            for ini in ini_dir.iterdir():
                if ini.is_file() and ini.suffix == ".ini" and ini.stem not in keep:
                    try:
                        ini.unlink()
                    except OSError:
                        pass
        for r, fe in zip(top, pseudo_entries):
            target_name = target_names[f"{fe.system}::{fe.rom_name}"]
            _generate_pclauncher_ini(
                rl_dir, target_system, target_name, r.system, r.rom_name,
            )
            summary.inis_written += 1

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

    sub.add_parser("list", help="Print the current top-N play records")
    return p


def main(argv: Optional[list[str]] = None) -> int:
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
        skip_media = args.media_mode == "none"
        mode = LinkMode.AUTO if skip_media else LinkMode(args.media_mode)
        summary = rebuild(
            config,
            target_system=args.target_system,
            limit=args.limit,
            media_mode=mode,
            skip_media=skip_media,
        )
        print(f"Recently Played system: {summary.target_system}")
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
