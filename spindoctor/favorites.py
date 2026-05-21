"""Cross-system favorites — manage and generate the synthetic system.

A "favorite" is a (source_system, rom_name) pair stored in
``~/.spindoctor/favorites.json``. ``rebuild`` regenerates a synthetic
HyperSpin system (default name: ``Favorites``) from that store, mirroring
each game's media via :mod:`spindoctor.medialink` and writing per-game
PCLauncher INIs that delegate launching back to the original system via
RocketLauncher's ``RLaunch.exe`` helper.

The ``add``/``remove``/``list``/``sync``/``rebuild`` operations are also
exposed as a standalone CLI so ``python -m spindoctor.favorites rebuild``
or the installed ``spindoctor-fav`` console script can run on system
startup or be wired into HyperSpin's Tools menu without depending on the
full SpinDoctor command surface.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import CONFIG_DIR, Config, load_config
from .database import GameEntry, HyperspinDatabase, load_database
from .medialink import LinkMode, apply_plan, plan_mirror, remove_target
from .rocketlauncher import generate_synthetic_system_ini


FAVORITES_FILE = CONFIG_DIR / "favorites.json"
DEFAULT_FAV_SYSTEM = "Favorites"


@dataclass
class FavoriteEntry:
    system: str        # source system (e.g. "Super Nintendo")
    rom_name: str      # source DB key / file stem
    display_name: str  # what HyperSpin shows on the wheel
    added: str         # ISO 8601 timestamp


@dataclass
class FavoriteStore:
    entries: list[FavoriteEntry] = field(default_factory=list)
    target_system: str = DEFAULT_FAV_SYSTEM

    def find(self, system: str, rom_name: str) -> Optional[FavoriteEntry]:
        for e in self.entries:
            if e.system == system and e.rom_name == rom_name:
                return e
        return None


# ─── persistence ──────────────────────────────────────────────────────────────

def load_store(path: Path = FAVORITES_FILE) -> FavoriteStore:
    if not path.exists():
        return FavoriteStore()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return FavoriteStore()
    entries = [FavoriteEntry(**e) for e in data.get("entries", [])]
    return FavoriteStore(
        entries=entries,
        target_system=data.get("target_system", DEFAULT_FAV_SYSTEM),
    )


def save_store(store: FavoriteStore, path: Path = FAVORITES_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_system": store.target_system,
        "entries": [asdict(e) for e in store.entries],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ─── CRUD ────────────────────────────────────────────────────────────────────

def add(store: FavoriteStore, system: str, rom_name: str,
        display_name: Optional[str] = None) -> bool:
    if store.find(system, rom_name):
        return False
    store.entries.append(FavoriteEntry(
        system=system,
        rom_name=rom_name,
        display_name=display_name or rom_name,
        added=datetime.now().isoformat(timespec="seconds"),
    ))
    return True


def remove(store: FavoriteStore, system: str, rom_name: str) -> bool:
    existing = store.find(system, rom_name)
    if not existing:
        return False
    store.entries.remove(existing)
    return True


def sync_native(store: FavoriteStore, config: Config) -> int:
    """Merge HyperSpin's per-system Favorites lists into the cross-system store.

    HyperSpin writes ``<game name="X" favorite="1"/>`` flags into each
    system's database when the user toggles the F-key inside a wheel.
    This helper picks those up and adds them to our store so the
    cross-system Favorites wheel reflects them on next rebuild.
    """
    added = 0
    db_root = config.databases_dir
    if not db_root.exists():
        return 0

    from .config import get_systems
    for sys_name in get_systems(config):
        if sys_name == store.target_system:
            continue
        try:
            db = load_database(sys_name, db_root)
        except (ValueError, OSError):
            continue
        for game in db.games().values():
            # Built-in HyperSpin sets favorite="1" in the <favorite> tag or
            # via a sibling .ini list. We probe the GameEntry first; users
            # without lxml may have lost the attribute, so the .ini fallback
            # below picks up the rest.
            if getattr(game, "favorite", "") == "1":
                if add(store, sys_name, game.name, game.description):
                    added += 1

        ini = db_root / sys_name / f"{sys_name}_Favorites.ini"
        if ini.exists():
            for line in ini.read_text(encoding="utf-8").splitlines():
                rom = line.strip()
                if not rom or rom.startswith(";") or rom.startswith("["):
                    continue
                source = db.get(rom)
                display = source.description if source else rom
                if add(store, sys_name, rom, display):
                    added += 1
    return added


# ─── synthetic system rebuild ────────────────────────────────────────────────

def _sorted_entries(entries: Iterable[FavoriteEntry]) -> list[FavoriteEntry]:
    """Order favorites alphabetically by display title (case-insensitive).

    Falls back to ``rom_name`` so legacy stores written before
    ``display_name`` was always populated still order sensibly.
    """
    return sorted(
        entries,
        key=lambda e: (e.display_name or e.rom_name).casefold(),
    )


def _resolve_target_names(entries: Iterable[FavoriteEntry]) -> dict[str, str]:
    """Compute a unique HyperSpin entry name for each favorite.

    Same rom_name across two systems collides on disk (Media uses the
    name as the filename stem) so the loser gets ``" ({system})"``
    appended to disambiguate.
    """
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        counts[e.rom_name] += 1
    used: set[str] = set()
    out: dict[str, str] = {}
    for e in entries:
        candidate = e.rom_name if counts[e.rom_name] == 1 else f"{e.rom_name} ({e.system})"
        # Guard against pathological collisions (same display in same system twice)
        n = 2
        base = candidate
        while candidate in used:
            candidate = f"{base} #{n}"
            n += 1
        used.add(candidate)
        out[f"{e.system}::{e.rom_name}"] = candidate
    return out


def _generate_pclauncher_ini(
    rocketlauncher_dir: Path,
    target_system: str,
    target_name: str,
    source_system: str,
    source_rom: str,
) -> Path:
    """Write a PCLauncher INI that defers launch back to the source system.

    Uses ``RLaunch.exe`` so the original emulator config (keymaps,
    overlays, save paths) is reused — we don't have to know which
    emulator the source system uses.
    """
    from .rocketlauncher import pclauncher_exe_info_text

    module_dir = rocketlauncher_dir / "Modules" / "PCLauncher" / target_system
    module_dir.mkdir(parents=True, exist_ok=True)
    ini = module_dir / f"{target_name}.ini"
    rl_exe = rocketlauncher_dir / "RocketLauncher.exe"
    contents = pclauncher_exe_info_text(
        rl_exe,
        parameters=f'-s "{source_system}" -r "{source_rom}" -p HyperSpin',
    )
    ini.write_text(contents, encoding="utf-8")
    return ini


@dataclass
class RebuildSummary:
    target_system: str
    db_path: Optional[Path] = None
    entries: int = 0
    media_linked: int = 0
    media_copied: int = 0
    media_skipped: int = 0
    media_errors: list[str] = field(default_factory=list)
    inis_written: int = 0
    pruned: int = 0


def rebuild(
    store: FavoriteStore,
    config: Config,
    *,
    media_mode: LinkMode = LinkMode.AUTO,
    skip_media: bool = False,
    skip_launchers: bool = False,
    dry_run: bool = False,
) -> RebuildSummary:
    """Regenerate the synthetic system's database, media mirrors, and launchers.

    When ``dry_run`` is true, returns a populated summary describing what
    would be written without touching disk.
    """
    summary = RebuildSummary(target_system=store.target_system)

    if not config.hyperspin_dir:
        return summary

    sorted_entries = _sorted_entries(store.entries)
    target_names = _resolve_target_names(sorted_entries)
    summary.entries = len(target_names)

    if dry_run:
        # Preview-only: report counts without touching disk.
        summary.inis_written = 0 if skip_launchers else len(target_names)
        if not skip_media:
            summary.media_linked = len(target_names)
        return summary

    # ── 1. Database XML ──────────────────────────────────────────────────────
    db_path = config.databases_dir / store.target_system / f"{store.target_system}.xml"
    db = HyperspinDatabase(store.target_system, db_path)
    db.load()
    existing_targets = set(target_names.values())
    summary.pruned = sum(
        1 for name in db.games() if name not in existing_targets
    )
    # Drop every existing entry so the upserts below dictate XML order —
    # otherwise `_merge_into_tree` would keep surviving games at their
    # prior positions, defeating the alphabetical sort.
    db.reset_games()

    for entry in sorted_entries:
        target_name = target_names[f"{entry.system}::{entry.rom_name}"]
        source_db = _safe_load(entry.system, config)
        source_game = source_db.get(entry.rom_name) if source_db else None
        merged = GameEntry(
            name=target_name,
            description=entry.display_name or (source_game.description if source_game else entry.rom_name),
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

    # ── 2. Media mirror ──────────────────────────────────────────────────────
    if not skip_media:
        # Drop any orphan media for entries that were pruned or renamed
        seen_targets = set(target_names.values())
        for media_path in (config.media_dir / store.target_system).rglob("*"):
            if media_path.is_file() and media_path.stem not in seen_targets:
                try:
                    media_path.unlink()
                except OSError:
                    pass

        for entry in sorted_entries:
            target_name = target_names[f"{entry.system}::{entry.rom_name}"]
            plan = plan_mirror(
                config.media_dir, entry.system, store.target_system,
                entry.rom_name, target_name,
            )
            result = apply_plan(plan, mode=media_mode)
            summary.media_linked += result["linked"]
            summary.media_copied += result["copied"]
            summary.media_skipped += result["skipped"]
            summary.media_errors.extend(result["errors"])

    # ── 3. Per-game PCLauncher INIs ──────────────────────────────────────────
    if not skip_launchers and config.rocketlauncher_dir:
        rl_dir = Path(config.rocketlauncher_dir)
        # Wipe stale INIs (renamed/removed favorites)
        existing_ini_dir = rl_dir / "Modules" / "PCLauncher" / store.target_system
        if existing_ini_dir.exists():
            keep = set(target_names.values())
            for ini in existing_ini_dir.iterdir():
                if ini.is_file() and ini.suffix == ".ini" and ini.stem not in keep:
                    try:
                        ini.unlink()
                    except OSError:
                        pass
        for entry in sorted_entries:
            target_name = target_names[f"{entry.system}::{entry.rom_name}"]
            _generate_pclauncher_ini(
                rl_dir, store.target_system, target_name,
                entry.system, entry.rom_name,
            )
            summary.inis_written += 1
        generate_synthetic_system_ini(store.target_system, rl_dir)

    return summary


def _safe_load(system_name: str, config: Config) -> Optional[HyperspinDatabase]:
    try:
        return load_database(system_name, config.databases_dir)
    except (ValueError, OSError):
        return None


# ─── standalone CLI (python -m spindoctor.favorites …) ───────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spindoctor-fav",
        description="Manage cross-system HyperSpin favorites.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add a favorite")
    p_add.add_argument("system")
    p_add.add_argument("rom_name")
    p_add.add_argument("--display-name", default=None)

    p_rem = sub.add_parser("remove", help="Remove a favorite")
    p_rem.add_argument("system")
    p_rem.add_argument("rom_name")

    sub.add_parser("list", help="List current favorites")
    sub.add_parser("sync", help="Merge per-system HyperSpin favorites into the store")

    p_reb = sub.add_parser("rebuild",
                           help="Regenerate the Favorites system + media + launchers")
    p_reb.add_argument("--media-mode",
                       choices=["link", "symlink", "copy", "auto", "none"],
                       default="auto")
    p_reb.add_argument("--apply", action="store_true",
                       help="Commit the rebuild (default: dry-run preview).")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    config = load_config()
    store = load_store()

    if args.cmd == "add":
        if add(store, args.system, args.rom_name, args.display_name):
            save_store(store)
            print(f"Added: {args.system} :: {args.rom_name}")
        else:
            print(f"Already a favorite: {args.system} :: {args.rom_name}")
        return 0

    if args.cmd == "remove":
        if remove(store, args.system, args.rom_name):
            save_store(store)
            # Drop mirrored media on removal so we don't leave orphans
            if config.hyperspin_dir:
                target_names = _resolve_target_names(store.entries + [
                    FavoriteEntry(args.system, args.rom_name, args.rom_name, "")
                ])
                stale = target_names.get(f"{args.system}::{args.rom_name}")
                if stale:
                    remove_target(config.media_dir, store.target_system, stale)
            print(f"Removed: {args.system} :: {args.rom_name}")
        else:
            print(f"Not a favorite: {args.system} :: {args.rom_name}")
        return 0

    if args.cmd == "list":
        if not store.entries:
            print("(no favorites)")
            return 0
        for e in _sorted_entries(store.entries):
            print(f"  · {e.system} :: {e.rom_name}  [{e.display_name}]")
        return 0

    if args.cmd == "sync":
        n = sync_native(store, config)
        save_store(store)
        print(f"Synced {n} favorite(s) from per-system HyperSpin lists.")
        return 0

    if args.cmd == "rebuild":
        if not config.hyperspin_dir:
            print("ERROR: hyperspin_dir is not configured.", file=sys.stderr)
            return 1
        skip_media = args.media_mode == "none"
        mode = LinkMode.AUTO if skip_media else LinkMode(args.media_mode)
        if not args.apply:
            print("[DRY RUN] No files will be written. Re-run with --apply to commit.")
        summary = rebuild(store, config, media_mode=mode, skip_media=skip_media,
                          dry_run=not args.apply)
        print(f"Favorites system: {summary.target_system}")
        print(f"  entries:    {summary.entries}")
        print(f"  pruned:     {summary.pruned}")
        print(f"  db:         {summary.db_path}")
        print(f"  media:      linked={summary.media_linked} "
              f"copied={summary.media_copied} skipped={summary.media_skipped}")
        if summary.media_errors:
            print(f"  errors:     {len(summary.media_errors)}")
            for e in summary.media_errors[:5]:
                print(f"    - {e}")
        print(f"  launchers:  {summary.inis_written}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
