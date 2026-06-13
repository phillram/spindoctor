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
import os
import sys
import tempfile
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .config import CONFIG_DIR, Config, load_config
from .database import GameEntry, HyperspinDatabase, load_database, resolve_atomic_tmp_dir
from .medialink import LinkMode, apply_plan, plan_mirror, remove_target, _read_hs_video_dir
from .rocketlauncher import (
    ensure_rl_game_exe,
    generate_synthetic_system_ini,
    install_bundled_system_assets,
    write_hyperspin_system_ini,
    write_pclauncher_system_ini,
)


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
    except (json.JSONDecodeError, OSError) as exc:
        warnings.warn(
            f"favorites.json is unreadable or corrupt ({exc}); returning empty store. "
            "Your existing favorites have NOT been modified — fix or delete the file "
            f"at {path} before running any write operation.",
            RuntimeWarning,
            stacklevel=2,
        )
        return FavoriteStore()
    entries = [FavoriteEntry(**e) for e in data.get("entries", [])]
    return FavoriteStore(
        entries=entries,
        target_system=data.get("target_system", DEFAULT_FAV_SYSTEM),
    )


def save_store(store: FavoriteStore, path: Path = FAVORITES_FILE,
               tmp_dir: Optional[Path] = None) -> None:
    """Persist *store* to *path* using an atomic temp-file + rename.

    *tmp_dir* is the scratch directory for the temp file
    (``config.effective_atomic_tmp_dir``).  Pass ``None`` to use
    ``path.parent`` (the original default).
    :func:`~spindoctor.database.resolve_atomic_tmp_dir` handles the
    same-filesystem check so a cross-drive directory is silently ignored.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_system": store.target_system,
        "entries": [asdict(e) for e in store.entries],
    }
    data = json.dumps(payload, indent=2).encode("utf-8")
    write_dir = resolve_atomic_tmp_dir(path, tmp_dir)
    fd, tmp = tempfile.mkstemp(dir=write_dir, suffix=".tmp")
    try:
        os.write(fd, data)
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


@dataclass
class ClearFavoritesSummary:
    """Result of :func:`clear_favorites`."""
    entries_cleared: int = 0
    store_path: Optional[Path] = None
    wheel: "Optional[Any]" = None   # ClearWheelSummary, imported lazily


def clear_favorites(
    store: "FavoriteStore",
    config: Config,
    *,
    path: "Optional[Path]" = None,
    dry_run: bool = True,
) -> ClearFavoritesSummary:
    """Empty the favorites store and tear down the synthetic Favorites wheel.

    When *dry_run* is ``True`` (the default) nothing is changed; the
    returned summary shows what *would* be removed.

    When *dry_run* is ``False``:
      1. The favorites store is saved empty to *path* (defaults to
         :data:`FAVORITES_FILE` resolved at call time).
      2. All on-disk wheel artifacts (database XML, media files, PCLauncher
         INIs) are deleted via :func:`spindoctor.recent.clear_wheel_artifacts`.
    """
    from .recent import clear_wheel_artifacts

    # Resolve default at call time so monkeypatching FAVORITES_FILE in tests works.
    resolved_path = path if path is not None else FAVORITES_FILE

    n = len(store.entries)
    target_system = store.target_system

    wheel_summary = clear_wheel_artifacts(
        config, target_system, dry_run=dry_run,
    )

    if not dry_run:
        # Overwrite store with an empty one (preserve target_system name).
        empty = FavoriteStore(entries=[], target_system=target_system)
        save_store(empty, resolved_path, tmp_dir=config.effective_atomic_tmp_dir)

    summary = ClearFavoritesSummary(
        entries_cleared=n,
        store_path=resolved_path,
        wheel=wheel_summary,
    )
    return summary


def sync_native(
    store: FavoriteStore,
    config: Config,
    *,
    progress_cb: "Optional[Any]" = None,
    log_cb: "Optional[Any]" = None,
    verbose: bool = False,
) -> tuple[int, list[str], list[str]]:
    """Merge HyperSpin's per-system Favorites lists into the cross-system store.

    Checks three sources per system, in order:

    1. ``<game favorite="1"/>`` attributes in the system's database XML.
    2. ``<databases_dir>/<System>/<System>_Favorites.ini`` — the INI format
       written by some HyperSpin / RocketLauncher builds (one ROM per line,
       optional ``[section]`` header).
    3. ``<databases_dir>/<System>/favorites.txt`` — the plain-text format
       written by other RocketLauncher builds (one ROM per line, no headers).
       The search is case-insensitive so ``Favorites.txt`` also matches.

    *progress_cb*, when supplied, is called as ``progress_cb(index, total,
    system_name)`` before each system is scanned (1-based *index*) so a
    caller can render a live counter.  *log_cb*, when supplied, receives a
    string for each per-system detail line; detail lines are only produced
    when *verbose* is true.

    The XML database is **not** parsed unless a fast text scan first finds a
    ``favorite="1"`` marker, and the database is loaded at all only when a
    favorites file (XML / ini / txt) is actually present for the system — so
    consoles with no favorites cost a few ``stat`` calls instead of a full
    XML parse.

    Returns ``(added_count, warnings, notes)`` where *warnings* lists any
    systems whose databases could not be loaded, and *notes* provides
    diagnostic info about where files were found (or not).
    """
    import re as _re

    added = 0
    warnings: list[str] = []
    notes: list[str] = []
    db_root = config.databases_dir
    if not db_root.exists():
        notes.append(
            f"databases_dir does not exist: {db_root} — "
            "check that hyperspin_dir is configured correctly."
        )
        return 0, warnings, notes

    from .config import get_systems
    systems = [s for s in get_systems(config) if s != store.target_system]
    total = len(systems)
    ini_found: list[str] = []       # systems with <System>_Favorites.ini
    txt_found: list[str] = []       # systems with favorites.txt
    xml_favorites_found = 0
    _FAV_RE = _re.compile(r'favorite\s*=\s*["\']1["\']')

    def _emit(msg: str) -> None:
        if verbose and log_cb is not None:
            log_cb(msg)

    for index, sys_name in enumerate(systems, 1):
        if progress_cb is not None:
            progress_cb(index, total, sys_name)

        sys_dir = db_root / sys_name
        ini = sys_dir / f"{sys_name}_Favorites.ini"
        has_ini = ini.exists()
        txt_path = _find_favorites_txt(sys_dir)
        has_txt = txt_path is not None

        # Fast text pre-scan: skip the (expensive) XML parse unless the raw
        # file actually contains a favorite="1" marker.
        xml = sys_dir / f"{sys_name}.xml"
        xml_has_fav = False
        if xml.is_file():
            try:
                raw = xml.read_text(encoding="utf-8", errors="replace")
                xml_has_fav = bool(_FAV_RE.search(raw))
            except OSError as exc:
                warnings.append(
                    f"sync: could not read {xml.name}: {type(exc).__name__}: {exc}"
                )

        if not (xml_has_fav or has_ini or has_txt):
            _emit(f"  {sys_name}: no favorites")
            continue

        # A favorites source exists — now (and only now) parse the database,
        # which is needed both for XML favorite flags and for display-name
        # lookups when expanding ini/txt ROM lists.
        try:
            db = _safe_load(sys_name, config)
        except (ValueError, OSError) as exc:
            warnings.append(f"sync: skipped {sys_name} — {type(exc).__name__}: {exc}")
            continue
        if db is None:
            warnings.append(f"sync: skipped {sys_name} — database could not be loaded")
            continue

        sys_added = 0

        # ── 1. XML database favorite="1" attributes ───────────────────────────
        if xml_has_fav:
            for game in db.games().values():
                # HyperSpin stores the flag as a ``favorite="1"`` attribute,
                # which the loader keeps in ``extra_attrs`` (not a modelled
                # field), so read it from there.
                if game.extra_attrs.get("favorite", "") == "1":
                    if add(store, sys_name, game.name, game.description):
                        added += 1
                        sys_added += 1
                        xml_favorites_found += 1

        # ── 2. <System>_Favorites.ini ─────────────────────────────────────────
        if has_ini:
            ini_found.append(sys_name)
            try:
                text = _read_text_robust(ini)
            except OSError as exc:
                warnings.append(
                    f"sync: could not read {ini.name}: {type(exc).__name__}: {exc}"
                )
                text = ""
            ini_roms: list[str] = []
            for line in text.splitlines():
                rom = line.strip()
                if not rom or rom.startswith(";") or rom.startswith("["):
                    continue
                source = db.get(rom)
                display = source.description if source else rom
                if add(store, sys_name, rom, display):
                    added += 1
                    sys_added += 1
                ini_roms.append(rom)
            if not ini_roms:
                warnings.append(
                    f"sync: {sys_name}_Favorites.ini exists but contained "
                    f"0 parseable ROM names — file may be empty or use an "
                    f"unexpected format."
                )

        # ── 3. favorites.txt (case-insensitive) ───────────────────────────────
        if has_txt:
            txt_found.append(sys_name)
            try:
                text = _read_text_robust(txt_path)
            except OSError as exc:
                warnings.append(
                    f"sync: could not read {txt_path.name} for {sys_name}: "
                    f"{type(exc).__name__}: {exc}"
                )
                text = ""
            txt_roms = _parse_favorites_txt(text)
            if txt_roms:
                for rom in txt_roms:
                    source = db.get(rom)
                    display = source.description if source else rom
                    if add(store, sys_name, rom, display):
                        added += 1
                        sys_added += 1
            else:
                warnings.append(
                    f"sync: {sys_name}/{txt_path.name} exists but contained "
                    f"0 parseable ROM names — file may be empty."
                )

        _emit(f"  {sys_name}: +{sys_added} new favorite(s)")

    # ── Diagnostic notes ──────────────────────────────────────────────────────
    if xml_favorites_found:
        notes.append(
            f"Found {xml_favorites_found} favorite flag(s) set in XML databases."
        )
    if ini_found:
        notes.append(
            f"Found <System>_Favorites.ini for {len(ini_found)} system(s): "
            f"{', '.join(ini_found)}"
        )
    if txt_found:
        notes.append(
            f"Found favorites.txt for {len(txt_found)} system(s): "
            f"{', '.join(txt_found)}"
        )

    nothing_found = not ini_found and not txt_found and not xml_favorites_found
    if nothing_found:
        notes.append(
            f"No favorites found after checking {len(systems)} system(s) "
            f"in {db_root}.\n"
            f"SpinDoctor searches each system folder for:\n"
            f"  • <game favorite=\"1\"/> in the database XML\n"
            f"  • <System>_Favorites.ini  (HyperSpin F-key format)\n"
            f"  • favorites.txt  (RocketLauncher plain-text format)\n"
            f"If favorites appear in HyperSpin but not here, those files may\n"
            f"live in a different directory.  Your configured databases_dir is:\n"
            f"  {db_root}"
        )

    return added, warnings, notes


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

    Invokes ``RocketLauncher.exe -p HyperSpin`` with the source system and
    ROM so the original emulator config (keymaps, overlays, save paths) is
    reused — SpinDoctor doesn't need to know which emulator any system uses.

    Uses ``[Settings]`` format (not ``[exe info]``) so PCLauncher does not
    require a ``fadetitle`` or monitored process.  RocketLauncher handles the
    HyperSpin fade/unfade itself when launched with ``-p HyperSpin``, making
    PCLauncher's window-monitoring unnecessary and avoiding the "PCLauncher
    does not know what exe / FadeTitle to watch for" error that ``[exe info]``
    produces when those fields are left blank.
    """
    from .rocketlauncher import pclauncher_settings_text

    module_dir = rocketlauncher_dir / "Modules" / "PCLauncher" / target_system
    module_dir.mkdir(parents=True, exist_ok=True)
    ini = module_dir / f"{target_name}.ini"
    rl_exe = rocketlauncher_dir / "RocketLauncher.exe"
    contents = pclauncher_settings_text(
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
    system_ini_path: Optional[Path] = None
    # Results from install_bundled_system_assets().
    # Keys: "wheel_art", "background", "music"
    # Values: (Optional[Path], status_str) where status ∈
    #   "installed" | "skipped" | "no_asset" | "dry_run"
    bundled_assets: dict = field(default_factory=dict)


def rebuild(
    store: FavoriteStore,
    config: Config,
    *,
    media_mode: LinkMode = LinkMode.COPY,
    skip_media: bool = False,
    skip_launchers: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
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
        if not skip_launchers and config.rocketlauncher_dir:
            # Show the path that *would* be written so the user can see
            # it's not being skipped because rocketlauncher_dir is unset.
            rl_dir = Path(config.rocketlauncher_dir)
            summary.system_ini_path = rl_dir / "Settings" / f"{store.target_system}.ini"
        hs_dir = Path(config.hyperspin_dir)
        summary.bundled_assets = install_bundled_system_assets(
            hs_dir, store.target_system, dry_run=True
        )
        return summary

    n = len(target_names)
    print(
        f"[{store.target_system}] building wheel — "
        f"{n} entr{'y' if n == 1 else 'ies'}…",
        flush=True,
    )

    # ── 1. Database XML ──────────────────────────────────────────────────────
    print(f"[{store.target_system}] writing database…", flush=True)
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

    # Memoise source DBs so each source system is parsed once, not once
    # per favorite drawn from it.
    src_cache: dict[str, Optional[HyperspinDatabase]] = {}
    for entry in sorted_entries:
        target_name = target_names[f"{entry.system}::{entry.rom_name}"]
        source_db = _safe_load(entry.system, config, src_cache)
        source_game = source_db.get(entry.rom_name) if source_db else None
        base_desc = entry.display_name or (source_game.description if source_game else entry.rom_name)
        merged = GameEntry(
            name=target_name,
            description=f"{base_desc} ({entry.system})",
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
    print(
        f"[{store.target_system}] database done — {n} game(s), "
        f"{summary.pruned} pruned.",
        flush=True,
    )

    # ── 2. Media mirror ──────────────────────────────────────────────────────
    if not skip_media:
        print(f"[{store.target_system}] mirroring media for {n} game(s)…", flush=True)
        # Drop any orphan media for entries that were pruned or renamed
        seen_targets = set(target_names.values())
        _target_media = config.media_dir / store.target_system
        if _target_media.is_dir():
            for media_path in _target_media.rglob("*"):
                if media_path.is_file() and media_path.stem not in seen_targets:
                    try:
                        media_path.unlink()
                    except OSError as e:
                        summary.media_errors.append(f"cleanup {media_path.name}: {e}")

        # Per-system video directory overrides (HyperSpin [video defaults] redirect).
        _hs_settings = Path(config.hyperspin_dir) / "Settings" if config.hyperspin_dir else None
        _video_cache: dict[str, Optional[Path]] = {}

        for entry in sorted_entries:
            if _hs_settings and entry.system not in _video_cache:
                _video_cache[entry.system] = _read_hs_video_dir(_hs_settings, entry.system)
            video_override = _video_cache.get(entry.system) if _hs_settings else None
            target_name = target_names[f"{entry.system}::{entry.rom_name}"]
            plan = plan_mirror(
                config.media_dir, entry.system, store.target_system,
                entry.rom_name, target_name,
                video_dir_override=video_override,
            )
            result = apply_plan(plan, mode=media_mode,
                               log_fn=print if verbose else None)
            summary.media_linked += result["linked"]
            summary.media_copied += result["copied"]
            summary.media_skipped += result["skipped"]
            summary.media_errors.extend(result["errors"])
        print(f"[{store.target_system}] media done.", flush=True)

    # ── 3. Per-game PCLauncher INIs ──────────────────────────────────────────
    if not skip_launchers and config.rocketlauncher_dir:
        rl_dir = Path(config.rocketlauncher_dir)
        print(f"[{store.target_system}] writing {n} PCLauncher INI(s)…", flush=True)
        # Wipe stale INIs (renamed/removed favorites)
        existing_ini_dir = rl_dir / "Modules" / "PCLauncher" / store.target_system
        if existing_ini_dir.exists():
            keep = set(target_names.values())
            for ini in existing_ini_dir.iterdir():
                if ini.is_file() and ini.suffix == ".ini" and ini.stem not in keep:
                    try:
                        ini.unlink()
                    except OSError as e:
                        summary.media_errors.append(f"cleanup {ini.name}: {e}")
        for entry in sorted_entries:
            target_name = target_names[f"{entry.system}::{entry.rom_name}"]
            _generate_pclauncher_ini(
                rl_dir, store.target_system, target_name,
                entry.system, entry.rom_name,
            )
            summary.inis_written += 1
        # Write the system-level PCLauncher INI that PCLauncher.ahk reads.
        # PCLauncher.ahk reads Modules/PCLauncher/<SystemName>.ini and looks up
        # [<game_name>] sections — it does NOT read the per-game placeholder
        # files in the subdirectory (those are only for RL game discovery).
        pclauncher_entries = [
            (target_names[f"{e.system}::{e.rom_name}"], e.system, e.rom_name)
            for e in sorted_entries
        ]
        game_exe = ensure_rl_game_exe(rl_dir)
        write_pclauncher_system_ini(
            store.target_system, pclauncher_entries, rl_dir,
            rl_exe=game_exe,
            extra_window_titles=config.emulator_window_titles or None,
        )
        summary.system_ini_path = generate_synthetic_system_ini(store.target_system, rl_dir)
        print(f"[{store.target_system}] PCLauncher INIs done.", flush=True)

    # ── 4. HyperSpin system settings INI ────────────────────────────────────
    # HyperSpin requires Settings/<system>.ini to open a sub-wheel.  Without
    # it the wheel reports "Cannot find <system>.ini" on selection.  We only
    # write when the file is absent so user customisations are never clobbered.
    hs_dir = Path(config.hyperspin_dir)
    write_hyperspin_system_ini(store.target_system, hs_dir)

    # ── 5. Bundled system media (wheel art, background, music) ──────────────
    # Install all package-bundled assets for this synthetic system.
    # Each asset is only written when absent — user files are never clobbered.
    summary.bundled_assets = install_bundled_system_assets(hs_dir, store.target_system)
    print(f"[{store.target_system}] wheel build complete.", flush=True)

    return summary


# ─── native HyperSpin favorites — collect + clear ────────────────────────────

def collect_native_fav_files(
    config: Config,
) -> tuple[list[Path], list[Path], list[Path]]:
    """Scan every non-synthetic system for per-system HyperSpin favorite files.

    Returns ``(ini_files, txt_files, xml_files)`` where:

    * *ini_files* — ``<System>_Favorites.ini`` files found under
      ``<databases_dir>/<System>/``.
    * *txt_files* — ``favorites.txt`` files (case-insensitive).
    * *xml_files* — system XML database files that contain at least one
      ``<game favorite="1"/>`` element.

    Synthetic wheel names (Favorites / Recently Played / Most Played) are
    excluded from the scan.
    """
    import re as _re
    from .config import get_systems
    from .recent import SYNTHETIC_SYSTEM_NAMES

    ini_files: list[Path] = []
    txt_files: list[Path] = []
    xml_files: list[Path] = []

    db_root = config.databases_dir
    if not db_root.is_dir():
        return ini_files, txt_files, xml_files

    for sys_name in get_systems(config):
        if sys_name in SYNTHETIC_SYSTEM_NAMES:
            continue
        sys_dir = db_root / sys_name
        if not sys_dir.is_dir():
            continue

        # 1. <System>_Favorites.ini
        ini = sys_dir / f"{sys_name}_Favorites.ini"
        if ini.is_file():
            ini_files.append(ini)

        # 2. favorites.txt (case-insensitive)
        found_txt = _find_favorites_txt(sys_dir)
        if found_txt is not None:
            txt_files.append(found_txt)

        # 3. XML with favorite="1" attribute — scan raw text (fast, no full parse)
        xml = sys_dir / f"{sys_name}.xml"
        if xml.is_file():
            try:
                raw = xml.read_text(encoding="utf-8", errors="replace")
                if _re.search(r'favorite\s*=\s*["\']1["\']', raw):
                    xml_files.append(xml)
            except OSError:
                pass

    return ini_files, txt_files, xml_files


@dataclass
class ClearNativeFavoritesSummary:
    """Result of :func:`clear_native_favorites`."""
    ini_cleared: int = 0        # _Favorites.ini files deleted
    txt_cleared: int = 0        # favorites.txt files deleted
    xml_cleared: int = 0        # XML files with favorite flags stripped
    xml_games_cleared: int = 0  # total game entries stripped across all XMLs
    errors: list[str] = field(default_factory=list)


def clear_native_favorites(
    config: Config,
    *,
    dry_run: bool = True,
) -> ClearNativeFavoritesSummary:
    """Remove per-system HyperSpin favorite markers from disk.

    Three sources are cleared:

    1. ``<System>_Favorites.ini`` files — deleted.
    2. ``favorites.txt`` files — deleted.
    3. ``favorite="1"`` attributes in system XML database files — the
       attribute is stripped from every matching ``<game>`` element using
       a targeted regex substitution that preserves the rest of the file's
       formatting.

    When *dry_run* is ``True`` (the default) nothing is modified; the
    returned summary reports what *would* be removed.
    """
    import re as _re

    summary = ClearNativeFavoritesSummary()
    ini_files, txt_files, xml_files = collect_native_fav_files(config)

    if not dry_run:
        # 1 + 2. Delete flat files
        for f in ini_files:
            try:
                f.unlink()
                summary.ini_cleared += 1
            except OSError as exc:
                summary.errors.append(f"Could not delete {f.name}: {exc}")

        for f in txt_files:
            try:
                f.unlink()
                summary.txt_cleared += 1
            except OSError as exc:
                summary.errors.append(f"Could not delete {f.name}: {exc}")

        # 3. Strip favorite="..." from XML files in place
        _FAV_ATTR_RE = _re.compile(r'\s*favorite\s*=\s*"[^"]*"|\s*favorite\s*=\s*\'[^\']*\'')
        for xml_path in xml_files:
            try:
                content = xml_path.read_text(encoding="utf-8", errors="replace")
                matches = len(_re.findall(r'favorite\s*=\s*["\']1["\']', content))
                new_content = _FAV_ATTR_RE.sub("", content)
                if new_content != content:
                    data = new_content.encode("utf-8")
                    _atmp = resolve_atomic_tmp_dir(xml_path, config.effective_atomic_tmp_dir)
                    fd, tmp = tempfile.mkstemp(dir=_atmp, suffix=".tmp")
                    try:
                        os.write(fd, data)
                        os.close(fd)
                        os.replace(tmp, xml_path)
                    except Exception:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        raise
                    summary.xml_cleared += 1
                    summary.xml_games_cleared += matches
            except OSError as exc:
                summary.errors.append(f"Could not update {xml_path.name}: {exc}")
    else:
        summary.ini_cleared = len(ini_files)
        summary.txt_cleared = len(txt_files)
        summary.xml_cleared = len(xml_files)
        # Count total games marked in XML files (for the dry-run preview)
        _FAV_ATTR_RE = _re.compile(r'favorite\s*=\s*["\']1["\']')
        for xml_path in xml_files:
            try:
                content = xml_path.read_text(encoding="utf-8", errors="replace")
                summary.xml_games_cleared += len(_FAV_ATTR_RE.findall(content))
            except OSError:
                pass

    return summary


def _find_favorites_txt(sys_dir: Path) -> "Optional[Path]":
    """Return the ``favorites.txt`` file in *sys_dir* if one exists.

    The search is **case-insensitive** so both ``favorites.txt`` and
    ``Favorites.txt`` (or any other capitalisation) are found correctly
    regardless of the host filesystem's case rules.
    """
    try:
        for p in sys_dir.iterdir():
            if p.is_file() and p.name.lower() == "favorites.txt":
                return p
    except OSError:
        pass
    return None


def _parse_favorites_txt(text: str) -> list[str]:
    """Return ROM names from a plain-text ``favorites.txt`` file.

    The format is one ROM name per line.  Empty lines and lines starting
    with ``#`` or ``;`` are treated as comments and ignored.  Unlike
    ``_Favorites.ini`` there are no section headers.
    """
    roms: list[str] = []
    for line in text.splitlines():
        rom = line.strip()
        if not rom or rom.startswith(";") or rom.startswith("#"):
            continue
        roms.append(rom)
    return roms


def _read_text_robust(path: Path) -> str:
    """Read *path* trying common Windows encodings in order.

    HyperSpin is a Windows application and ``_Favorites.ini`` files are
    sometimes written as UTF-8-with-BOM, UTF-16-LE, or the system ANSI
    code page (Windows-1252 / Latin-1).  Using plain ``utf-8`` silently
    produces the wrong output (or raises) for these files.
    """
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort: raw bytes with replacement — data may be mangled
    warnings.warn(
        f"Could not decode {path} with any known encoding; "
        "falling back to UTF-8 with replacement characters. "
        "The file may have been saved in an unsupported code page.",
        RuntimeWarning,
        stacklevel=2,
    )
    return path.read_bytes().decode("utf-8", errors="replace")


def _safe_load(
    system_name: str,
    config: Config,
    cache: "Optional[dict[str, Optional[HyperspinDatabase]]]" = None,
) -> Optional[HyperspinDatabase]:
    """Load a source system's database, optionally memoising the result.

    When *cache* is supplied, each system's parsed database (or the
    ``None`` sentinel recorded for an unreadable one) is reused on
    subsequent calls.  Synthetic-wheel rebuilds pull many favorites from
    the same source system, so without the cache the source XML would be
    re-parsed once per entry — the dominant cost for a large wheel.
    """
    if cache is not None and system_name in cache:
        return cache[system_name]
    try:
        db = load_database(system_name, config.databases_dir)
    except (ValueError, OSError) as exc:
        warnings.warn(
            f"Couldn't load database for '{system_name}': {exc}. "
            "Rebuilt favorite entries for this system will have empty metadata fields.",
            RuntimeWarning,
            stacklevel=2,
        )
        db = None
    if cache is not None:
        cache[system_name] = db
    return db


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
    p_sync = sub.add_parser("sync", help="Merge per-system HyperSpin favorites into the store")
    p_sync.add_argument("--verbose", action="store_true",
                        help="Print per-console scan detail.")

    p_reb = sub.add_parser("rebuild",
                           help="Regenerate the Favorites system + media + launchers")
    p_reb.add_argument("--media-mode",
                       choices=["link", "symlink", "copy", "auto", "none"],
                       default="copy")
    p_reb.add_argument("--apply", action="store_true",
                       help="Commit the rebuild (default: dry-run preview).")
    p_reb.add_argument("--verbose", action="store_true",
                       help="Print each media file copied/linked (src → dest).")

    p_clr = sub.add_parser(
        "clear",
        help="Empty the favorites store and remove the synthetic wheel from disk",
    )
    p_clr.add_argument(
        "--apply", action="store_true",
        help="Actually clear (default: dry-run preview).",
    )

    return p


def _stdout_sync_progress() -> tuple[Any, Any]:
    """Build ``(progress_cb, log_cb)`` that render the sync crawl on stdout.

    The progress callback overwrites a single counter line in place when
    stdout is a TTY (so the crawl doesn't flood the scrollback); when piped
    it stays silent and leaves the per-console detail (``log_cb``, verbose
    only) to carry the output.
    """
    is_tty = sys.stdout.isatty()
    state = {"width": 0}

    def progress_cb(index: int, total: int, system: str) -> None:
        if not is_tty:
            return
        msg = f"  scanning {system} ({index}/{total})…"
        pad = max(0, state["width"] - len(msg))
        state["width"] = len(msg)
        sys.stdout.write("\r" + msg + " " * pad)
        sys.stdout.flush()
        if index == total:
            sys.stdout.write("\r" + " " * (len(msg) + pad) + "\r")
            sys.stdout.flush()

    def log_cb(msg: str) -> None:
        if is_tty and state["width"]:
            sys.stdout.write("\r" + " " * state["width"] + "\r")
            state["width"] = 0
        print(msg)

    return progress_cb, log_cb


def main(argv: Optional[list[str]] = None) -> int:
    from ._compat import enable_windows_utf8_console
    enable_windows_utf8_console()
    args = _build_parser().parse_args(argv)
    config = load_config()
    store = load_store()

    _tmp_dir = config.effective_atomic_tmp_dir

    if args.cmd == "add":
        if add(store, args.system, args.rom_name, args.display_name):
            save_store(store, tmp_dir=_tmp_dir)
            print(f"Added: {args.system} :: {args.rom_name}")
        else:
            print(f"Already a favorite: {args.system} :: {args.rom_name}")
        return 0

    if args.cmd == "remove":
        if remove(store, args.system, args.rom_name):
            save_store(store, tmp_dir=_tmp_dir)
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
        _prog, _log = _stdout_sync_progress()
        n, sync_warns, sync_notes = sync_native(
            store, config, progress_cb=_prog, log_cb=_log,
            verbose=getattr(args, "verbose", False),
        )
        save_store(store, tmp_dir=_tmp_dir)
        for w in sync_warns:
            print(f"WARNING: {w}", file=sys.stderr)
        for note in sync_notes:
            print(f"  note: {note}")
        print(f"Synced {n} favorite(s) from per-system HyperSpin lists.")
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
        _prog, _log = _stdout_sync_progress()
        synced, sync_warns, sync_notes = sync_native(
            store, config, progress_cb=_prog, log_cb=_log,
            verbose=getattr(args, "verbose", False),
        )
        for w in sync_warns:
            print(f"WARNING: {w}", file=sys.stderr)
        if synced > 0:
            save_store(store, tmp_dir=_tmp_dir)
            print(f"  synced {synced} favorite(s) from HyperSpin per-system lists.")
        else:
            print(
                "  sync: 0 found in HyperSpin per-system lists — add favorites "
                "with the F key in HyperSpin or use 'fav add'"
            )
        for note in sync_notes:
            print(f"  note: {note}")
        skip_media = args.media_mode == "none"
        mode = LinkMode.AUTO if skip_media else LinkMode(args.media_mode)
        if not args.apply:
            print("[DRY RUN] No files will be written. Re-run with --apply to commit.")
        summary = rebuild(store, config, media_mode=mode, skip_media=skip_media,
                          dry_run=not args.apply,
                          verbose=getattr(args, "verbose", False))
        print(f"Favorites system: {summary.target_system}")
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
        return 0

    if args.cmd == "clear":
        if not args.apply:
            print("[DRY RUN] No changes will be made. "
                  "Re-run with --apply to commit.")
        result = clear_favorites(store, config, dry_run=not args.apply)
        verb = "Would remove" if not args.apply else "Removed"
        target_system = store.target_system
        n = result.entries_cleared
        print(f"Clear favorites: {target_system}")
        if not args.apply:
            print(f"  {verb}: {n} entr{'y' if n == 1 else 'ies'} "
                  f"from {result.store_path}")
        else:
            print(f"  {verb}: {n} entr{'y' if n == 1 else 'ies'} from store "
                  f"({result.store_path})")
        w = result.wheel
        if w is not None:
            if w.db_removed:
                print(f"  {verb}: Databases/{target_system}/{target_system}.xml")
            else:
                print("  database: not found (nothing to remove)")
            print(f"  {verb}: {w.media_files_removed} media file(s) "
                  f"under Media/{target_system}/")
            print(f"  {verb}: {w.ini_files_removed} PCLauncher INI(s)")
            if w.errors:
                print(f"  {len(w.errors)} error(s):", file=sys.stderr)
                for e in w.errors[:5]:
                    print(f"    - {e}", file=sys.stderr)
        return 0 if not (result.wheel and result.wheel.errors) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
