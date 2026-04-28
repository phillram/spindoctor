"""Cache and ephemeral-file inventory + cleanup.

SpinDoctor scatters caches, undo manifests, database backups, and a few
temp directories across ``~/.spindoctor/``, the ROMs tree, the HyperSpin
tree, and ``/tmp``. This module catalogues those locations as named
*categories*, scans them on demand, and removes selected entries.

Each category declares whether it is *safe* to delete by default. Caches
(API responses, match decisions) are safe — re-running the relevant
command rebuilds them. Undo manifests and DB backups are flagged unsafe
because deleting them removes a recovery option.

The module is pure: it does not print, prompt, or touch the network. The
CLI in :mod:`spindoctor.cli` formats reports and confirms before calling
:func:`remove`.
"""
from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from .config import CONFIG_DIR, Config


# ─── data model ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FileEntry:
    path: Path
    size: int
    mtime: float


@dataclass
class CategoryReport:
    key: str
    label: str
    description: str
    location: str
    safe: bool
    files: list[FileEntry] = field(default_factory=list)
    note: str = ""

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def oldest_mtime(self) -> Optional[float]:
        return min((f.mtime for f in self.files), default=None)

    @property
    def newest_mtime(self) -> Optional[float]:
        return max((f.mtime for f in self.files), default=None)


# ─── category definitions ─────────────────────────────────────────────────────

# Each spec is a callable that returns (label, description, location_str,
# safe, files, note) given the current config. We keep the discovery
# logic here rather than scattering it through the CLI so that audit and
# run see the exact same view of disk.

_CategoryFn = Callable[[Config], CategoryReport]


def _scan_glob(directory: Path, pattern: str, recursive: bool = False) -> list[FileEntry]:
    if not directory.exists():
        return []
    iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
    out: list[FileEntry] = []
    for p in iterator:
        if not p.is_file():
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(FileEntry(p, stat.st_size, stat.st_mtime))
    return out


def _match_cache(config: Config) -> CategoryReport:
    d = CONFIG_DIR / "match_cache"
    return CategoryReport(
        key="match-cache",
        label="Metadata match decisions",
        description="Cached game-to-metadata picks per system. Rebuilt by `fetch-meta`.",
        location=str(d),
        safe=True,
        files=_scan_glob(d, "*.json"),
    )


def _media_pick_cache(config: Config) -> CategoryReport:
    d = CONFIG_DIR / "media_pick_cache"
    return CategoryReport(
        key="media-pick-cache",
        label="Media picker decisions",
        description="Cached media-asset selections per system. Rebuilt by `fetch-media`.",
        location=str(d),
        safe=True,
        files=_scan_glob(d, "*.json"),
    )


def _pc_titles_cache(config: Config) -> CategoryReport:
    d = CONFIG_DIR / "pc_titles_cache"
    return CategoryReport(
        key="pc-titles-cache",
        label="PC/Steam title confirmations",
        description="Cached title confirmations for PC/Windows/Steam scans. Rebuilt by `sync-db`.",
        location=str(d),
        safe=True,
        files=_scan_glob(d, "*.json"),
    )


def _metadata_cache(config: Config) -> CategoryReport:
    d = CONFIG_DIR / "metadata_cache"
    return CategoryReport(
        key="metadata-cache",
        label="Scraper API responses",
        description="ScreenScraper / TheGamesDB JSON responses. TTL governed by `metadata_cache_ttl_days`.",
        location=str(d),
        safe=True,
        files=_scan_glob(d, "*.json", recursive=True),
    )


def _listxml_cache(config: Config) -> CategoryReport:
    d = CONFIG_DIR / "mame_listxml_cache"
    return CategoryReport(
        key="listxml-cache",
        label="MAME -listxml cache",
        description="Parsed MAME listxml output. Re-generated on next LEDBlinky/MAME run.",
        location=str(d),
        safe=True,
        files=_scan_glob(d, "*", recursive=True),
    )


def _preview_temp(config: Config) -> CategoryReport:
    d = Path(tempfile.gettempdir()) / "spindoctor_preview"
    return CategoryReport(
        key="preview-temp",
        label="Media preview thumbnails",
        description="Temporary preview images written during interactive media picking.",
        location=str(d),
        safe=True,
        files=_scan_glob(d, "*", recursive=True),
    )


def _migration_manifests(config: Config) -> CategoryReport:
    d = CONFIG_DIR / "migrations"
    return CategoryReport(
        key="migration-manifests",
        label="Migration undo manifests",
        description="Manifests for `migrate --apply`. Required to run `migrate --undo`.",
        location=str(d),
        safe=False,
        files=_scan_glob(d, "migrate-*.json"),
        note="Removing these makes past migrations un-undoable.",
    )


def _restructure_manifests(config: Config) -> CategoryReport:
    base = Path(config.roms_dir) if config.roms_dir else None
    files: list[FileEntry] = []
    if base and base.exists():
        files = _scan_glob(base, "_spindoctor-restructure-*.json", recursive=True)
    return CategoryReport(
        key="restructure-manifests",
        label="Restructure undo manifests",
        description="Manifests for `organize --apply`. Required to run `organize --undo`.",
        location=str(base) if base else "<roms_dir not set>",
        safe=False,
        files=files,
        note="Removing these makes past restructures un-undoable.",
    )


def _misplaced_manifests(config: Config) -> CategoryReport:
    base = Path(config.roms_dir) if config.roms_dir else None
    files: list[FileEntry] = []
    if base and base.exists():
        files = _scan_glob(base, "_spindoctor-misplaced-*.json", recursive=True)
    return CategoryReport(
        key="misplaced-manifests",
        label="Misplaced-ROM reports",
        description="Reports written by `misplaced --report`. Informational only.",
        location=str(base) if base else "<roms_dir not set>",
        safe=True,
        files=files,
    )


def _db_backups(config: Config) -> CategoryReport:
    base = config.databases_dir if config.hyperspin_dir else None
    files: list[FileEntry] = []
    if base and base.exists():
        files = _scan_glob(base, "*.bak", recursive=True)
    return CategoryReport(
        key="db-backups",
        label="HyperSpin XML database backups",
        description="Timestamped `.bak` snapshots written before XML edits.",
        location=str(base) if base else "<hyperspin_dir not set>",
        safe=False,
        files=files,
        note="Each backup is a recovery point for one edit. Use --keep-recent to thin.",
    )


def _ledblinky_backups(config: Config) -> CategoryReport:
    base = Path(config.ledblinky_dir) if config.ledblinky_dir else None
    files: list[FileEntry] = []
    if base and base.exists():
        files = _scan_glob(base, "*.bak", recursive=True)
    return CategoryReport(
        key="ledblinky-backups",
        label="LEDBlinky file backups",
        description="Timestamped `.bak` snapshots beside LEDBlinky XML/INI files.",
        location=str(base) if base else "<ledblinky_dir not set>",
        safe=False,
        files=files,
        note="Each backup is a recovery point. Use --keep-recent to thin.",
    )


def _audit_exports(config: Config) -> CategoryReport:
    base = Path(config.auto_audit_export_dir) if config.auto_audit_export_dir else None
    files: list[FileEntry] = []
    if base and base.exists():
        files = _scan_glob(base, "audit_*.csv")
    return CategoryReport(
        key="audit-exports",
        label="Auto-audit CSV exports",
        description="CSV reports auto-written after write operations when configured.",
        location=str(base) if base else "<auto_audit_export_dir not set>",
        safe=True,
        files=files,
    )


_CATEGORY_FNS: tuple[_CategoryFn, ...] = (
    _match_cache,
    _media_pick_cache,
    _pc_titles_cache,
    _metadata_cache,
    _listxml_cache,
    _preview_temp,
    _audit_exports,
    _misplaced_manifests,
    _migration_manifests,
    _restructure_manifests,
    _db_backups,
    _ledblinky_backups,
)


CATEGORY_KEYS: tuple[str, ...] = tuple(fn(Config()).key for fn in _CATEGORY_FNS)


# ─── public API ───────────────────────────────────────────────────────────────


def scan(config: Config, keys: Optional[Iterable[str]] = None) -> dict[str, CategoryReport]:
    """Discover files for *keys* (default: all categories) under *config*."""
    wanted = set(keys) if keys is not None else None
    out: dict[str, CategoryReport] = {}
    for fn in _CATEGORY_FNS:
        report = fn(config)
        if wanted is None or report.key in wanted:
            out[report.key] = report
    return out


def filter_files(
    files: list[FileEntry],
    *,
    older_than_days: Optional[float] = None,
    keep_recent: Optional[int] = None,
    now: Optional[float] = None,
) -> list[FileEntry]:
    """Apply --older-than and --keep-recent to a category's file list.

    ``older_than_days`` keeps only entries with mtime older than the cutoff.
    ``keep_recent`` keeps the N newest by mtime *after* the older-than filter,
    excluding them from deletion (i.e. the return value is what to delete).
    """
    out = list(files)
    if older_than_days is not None:
        cutoff = (now if now is not None else time.time()) - older_than_days * 86400
        out = [f for f in out if f.mtime <= cutoff]
    if keep_recent is not None and keep_recent > 0:
        out.sort(key=lambda f: f.mtime, reverse=True)
        out = out[keep_recent:]
    return out


@dataclass
class RemovalResult:
    removed: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    bytes_freed: int = 0

    @property
    def count_removed(self) -> int:
        return len(self.removed)


def remove(entries: Iterable[FileEntry], *, dry_run: bool = True) -> RemovalResult:
    """Delete *entries* unless *dry_run* is true.

    Returns a :class:`RemovalResult` describing the action that was (or
    would have been) performed. In dry-run mode, ``removed`` lists every
    path that would have been deleted but no filesystem change occurs.
    """
    result = RemovalResult()
    for entry in entries:
        if dry_run:
            result.removed.append(entry.path)
            result.bytes_freed += entry.size
            continue
        try:
            entry.path.unlink()
        except FileNotFoundError:
            continue
        except OSError as e:
            result.failed.append((entry.path, str(e)))
            continue
        result.removed.append(entry.path)
        result.bytes_freed += entry.size
    return result


def prune_empty_dirs(roots: Iterable[Path]) -> int:
    """Remove now-empty directories under each root. Returns count removed."""
    pruned = 0
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        # Walk bottom-up so child dirs are removed before parents.
        for sub in sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            try:
                sub.rmdir()
                pruned += 1
            except OSError:
                pass
        try:
            root.rmdir()
            pruned += 1
        except OSError:
            pass
    return pruned


def format_size(num_bytes: int) -> str:
    """Render bytes as a short human string ('1.4 MB')."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"
