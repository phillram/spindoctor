"""SpinDoctor self-diagnostics — inspect SpinDoctor's own state, not the cabinet.

The main ``doctor`` command checks the *library* — paths, configured
binaries, scraper credentials, HyperSpin databases. Over time, the cabinet
also accumulates state inside SpinDoctor's own config directory
(``~/.spindoctor/``): orphan backup folders, corrupt-config rescue copies
from a botched edit, manifest dirs that never got pruned, expired metadata
cache, leftover ``.part`` files from interrupted downloads. None of this
breaks the cab, but it adds up and confuses users when they try to
inventory what's on disk.

``spindoctor self-doctor`` produces a one-line-per-issue report so the user
can decide what to clean up. The companion ``--fix`` flag performs only
safe, idempotent deletions (rescue copies older than 30 days, ``.part``
files older than 7 days, manifest dirs over a configurable size). Live
config, current backups, and the current metadata cache are never touched.

Kept as a separate module from ``health`` because the audience and
output shape differ — ``health`` answers "is my library OK?", this
answers "is my SpinDoctor install OK?".
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR
from ._utils import format_bytes


class Status(str, Enum):
    OK = "ok"
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class SelfCheck:
    name: str
    status: Status
    detail: str = ""
    # Bytes that would be reclaimed by --fix for this check, if any.
    reclaimable_bytes: int = 0
    # When --fix is supported by this check.
    fixable: bool = False


@dataclass
class SelfDoctorReport:
    checks: list[SelfCheck] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)

    def add(self, check: SelfCheck) -> None:
        self.checks.append(check)

    def overall(self) -> Status:
        order = {Status.OK: 0, Status.INFO: 0, Status.WARN: 1, Status.FAIL: 2}
        worst = Status.OK
        for c in self.checks:
            if order[c.status] > order[worst]:
                worst = c.status
        return worst

    def total_reclaimable_bytes(self) -> int:
        return sum(c.reclaimable_bytes for c in self.checks)


# Age thresholds in days. Conservative defaults — anything younger gets
# a WARN with a recommendation, not a FAIL, and is never auto-deleted.
_RESCUE_COPY_STALE_DAYS = 30
_PART_FILE_STALE_DAYS = 7
# A manifest dir over this size is unusual — recent runs accumulate fast
# but most manifests are < 1 MB. 50 MB is the "you've never cleaned up"
# threshold; below that, no warning.
_MANIFEST_DIR_WARN_BYTES = 50 * 1024 * 1024


def _walk_size(path: Path) -> int:
    """Total bytes under *path*. Tolerates missing files / permission errors."""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total



def _days_since(path: Path) -> Optional[float]:
    """Days between *path*'s mtime and now. None if path missing."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return (time.time() - mtime) / 86400.0


def check_config_dir_exists(report: SelfDoctorReport) -> None:
    if CONFIG_DIR.exists():
        report.add(SelfCheck(
            name="config_dir",
            status=Status.OK,
            detail=f"~/.spindoctor/ exists at {CONFIG_DIR}",
        ))
    else:
        report.add(SelfCheck(
            name="config_dir",
            status=Status.INFO,
            detail=(
                f"~/.spindoctor/ does not exist yet. SpinDoctor will "
                f"create it the first time you save a config. Path: "
                f"{CONFIG_DIR}"
            ),
        ))


def check_config_corruption(report: SelfDoctorReport) -> None:
    """The two JSON files SpinDoctor writes at runtime — config.json and
    favorites.json — must parse as objects. If either is broken on disk,
    the next save will lose data even though config.py has a rescue-copy
    safety net."""
    for name in ("config.json", "favorites.json"):
        p = CONFIG_DIR / name
        if not p.exists():
            continue  # Optional file; not having it is fine.
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            report.add(SelfCheck(
                name=f"json_{name}",
                status=Status.FAIL,
                detail=(
                    f"{name} failed to parse: {e}. SpinDoctor will rescue "
                    f"it on next read, but unsaved hand edits will be lost. "
                    f"Restore from a backup or fix the file by hand."
                ),
            ))
            continue
        if not isinstance(data, dict):
            report.add(SelfCheck(
                name=f"json_{name}",
                status=Status.FAIL,
                detail=(
                    f"{name} parsed but is not a JSON object (got "
                    f"{type(data).__name__}). SpinDoctor expects a dict."
                ),
            ))
            continue
        report.add(SelfCheck(
            name=f"json_{name}",
            status=Status.OK,
            detail=f"{name} parses cleanly.",
        ))


def check_rescue_copies(report: SelfDoctorReport) -> SelfCheck:
    """``config.corrupt-<stamp>.json`` rescue copies accumulate when the
    config goes corrupt and gets auto-rescued. After 30 days they're
    very unlikely to be referenced — recommend cleanup."""
    if not CONFIG_DIR.exists():
        check = SelfCheck(name="rescue_copies", status=Status.OK,
                          detail="No config dir; nothing to inspect.")
        report.add(check)
        return check
    stale: list[Path] = []
    stale_bytes = 0
    fresh = 0
    for p in CONFIG_DIR.glob("config.corrupt-*.json"):
        days = _days_since(p)
        if days is None:
            continue
        if days > _RESCUE_COPY_STALE_DAYS:
            stale.append(p)
            stale_bytes += _walk_size(p)
        else:
            fresh += 1
    if not stale and not fresh:
        check = SelfCheck(name="rescue_copies", status=Status.OK,
                          detail="No corrupt-config rescue copies on disk.")
    elif not stale:
        check = SelfCheck(
            name="rescue_copies", status=Status.INFO,
            detail=(
                f"{fresh} rescue copy/copies present, all under "
                f"{_RESCUE_COPY_STALE_DAYS} days old — keeping for now."
            ),
        )
    else:
        check = SelfCheck(
            name="rescue_copies", status=Status.WARN,
            detail=(
                f"{len(stale)} rescue copy/copies older than "
                f"{_RESCUE_COPY_STALE_DAYS} days, totalling "
                f"{format_bytes(stale_bytes)}. Safe to delete — "
                f"--fix will remove them."
            ),
            reclaimable_bytes=stale_bytes,
            fixable=True,
        )
    report.add(check)
    return check


def check_manifest_dir_sizes(report: SelfDoctorReport) -> None:
    """Manifest dirs (curate / migrate / edits / renames / themes /
    media_imports / restructures) accumulate one JSON per --apply run.
    Most are < 1 MB total; over time, dirs over 50 MB indicate the user
    has never cleaned them up — worth surfacing but never auto-deleted
    (manifests are the undo path)."""
    manifest_dirs = [
        "curate", "migrations", "edits", "renames", "themes",
        "media_imports", "restructures",
    ]
    for name in manifest_dirs:
        d = CONFIG_DIR / name
        if not d.exists():
            continue
        size = _walk_size(d)
        n_files = sum(1 for _ in d.rglob("*") if _.is_file())
        if size < _MANIFEST_DIR_WARN_BYTES:
            report.add(SelfCheck(
                name=f"manifests_{name}",
                status=Status.OK,
                detail=f"{name}/: {n_files} manifest(s), {format_bytes(size)}",
            ))
            continue
        report.add(SelfCheck(
            name=f"manifests_{name}",
            status=Status.WARN,
            detail=(
                f"{name}/: {n_files} manifest(s), {format_bytes(size)}. "
                f"Manifests are the --undo path, so they're not "
                f"auto-deleted; archive or prune by hand if you're "
                f"confident you no longer need undo history."
            ),
        ))


def check_orphan_part_files(report: SelfDoctorReport, config) -> SelfCheck:
    """``.part`` sidecars are left behind when a media download is
    interrupted. The next download attempt resumes from them via HTTP
    Range, so we keep them for a week. After that, they're more likely
    to be stale than useful — recommend cleanup."""
    media_dir = getattr(config, "media_dir", None)
    if media_dir is None or not Path(media_dir).exists():
        check = SelfCheck(
            name="part_files", status=Status.INFO,
            detail="hyperspin_dir not configured; can't inspect for "
                   "orphan .part files.",
        )
        report.add(check)
        return check
    stale: list[Path] = []
    stale_bytes = 0
    fresh = 0
    for p in Path(media_dir).rglob("*.part"):
        days = _days_since(p)
        if days is None:
            continue
        if days > _PART_FILE_STALE_DAYS:
            stale.append(p)
            try:
                stale_bytes += p.stat().st_size
            except OSError:
                pass
        else:
            fresh += 1
    if not stale and not fresh:
        check = SelfCheck(
            name="part_files", status=Status.OK,
            detail="No orphan .part files under HyperSpin/Media/.",
        )
    elif not stale:
        check = SelfCheck(
            name="part_files", status=Status.INFO,
            detail=(
                f"{fresh} .part file(s) present, all under "
                f"{_PART_FILE_STALE_DAYS} days old — keeping in case "
                f"the user resumes those downloads."
            ),
        )
    else:
        check = SelfCheck(
            name="part_files", status=Status.WARN,
            detail=(
                f"{len(stale)} orphan .part file(s) older than "
                f"{_PART_FILE_STALE_DAYS} days, totalling "
                f"{format_bytes(stale_bytes)}. Safe to delete — "
                f"--fix will remove them."
            ),
            reclaimable_bytes=stale_bytes,
            fixable=True,
        )
    report.add(check)
    return check


def check_metadata_cache(report: SelfDoctorReport, config) -> SelfCheck:
    """The metadata cache (one JSON per scraped game) can grow into
    the hundreds of MB on a big library. INFO-level reporting — never
    a WARN, since the user explicitly configured the TTL."""
    cache_dir = CONFIG_DIR / "cache" / "metadata"
    if not cache_dir.exists():
        check = SelfCheck(
            name="metadata_cache", status=Status.OK,
            detail="Metadata cache not yet populated.",
        )
        report.add(check)
        return check
    size = _walk_size(cache_dir)
    n_files = sum(1 for _ in cache_dir.rglob("*.json") if _.is_file())
    check = SelfCheck(
        name="metadata_cache", status=Status.INFO,
        detail=(
            f"{n_files} cached scraper response(s), {format_bytes(size)}. "
            f"TTL = {getattr(config, 'metadata_cache_ttl_days', '?')} days; "
            f"old entries auto-expire on the next fetch-meta run."
        ),
    )
    report.add(check)
    return check


def run_self_checks(config, fix: bool = False) -> SelfDoctorReport:
    """Run every check; return a populated report. When ``fix=True``,
    safe deletions (stale rescue copies, stale .part files) are
    performed in-place and recorded in ``report.fixes_applied``.
    """
    report = SelfDoctorReport()
    check_config_dir_exists(report)
    check_config_corruption(report)
    rescue_check = check_rescue_copies(report)
    check_manifest_dir_sizes(report)
    part_check = check_orphan_part_files(report, config)
    check_metadata_cache(report, config)

    if fix:
        _apply_safe_fixes(report, rescue_check, part_check, config)
    return report


def _apply_safe_fixes(
    report: SelfDoctorReport,
    rescue_check: SelfCheck,
    part_check: SelfCheck,
    config,
) -> None:
    """Delete stale rescue copies + .part files. Never touches manifests,
    config, current backups, or the metadata cache.

    Both stale-set computations re-walk disk (rather than caching the
    list inside the SelfCheck) because the check ran moments ago — fast
    enough — and a fresh walk avoids deleting a file the user just
    explicitly created between check and fix.
    """
    if rescue_check.fixable and rescue_check.reclaimable_bytes > 0:
        for p in CONFIG_DIR.glob("config.corrupt-*.json"):
            days = _days_since(p)
            if days is not None and days > _RESCUE_COPY_STALE_DAYS:
                try:
                    p.unlink()
                    report.fixes_applied.append(
                        f"Deleted stale rescue copy: {p.name}"
                    )
                except OSError as e:
                    report.fixes_applied.append(
                        f"Could not delete {p.name}: {e}"
                    )

    if part_check.fixable and part_check.reclaimable_bytes > 0:
        media_dir = getattr(config, "media_dir", None)
        if media_dir is not None and Path(media_dir).exists():
            for p in Path(media_dir).rglob("*.part"):
                days = _days_since(p)
                if days is not None and days > _PART_FILE_STALE_DAYS:
                    try:
                        p.unlink()
                        report.fixes_applied.append(
                            f"Deleted stale .part file: {p.name}"
                        )
                    except OSError as e:
                        report.fixes_applied.append(
                            f"Could not delete {p.name}: {e}"
                        )


# ─── CLI rendering ───────────────────────────────────────────────────────────

_BADGE = {
    Status.OK:   "[green]✓[/green]",
    Status.INFO: "[blue]ℹ[/blue]",
    Status.WARN: "[yellow]⚠[/yellow]",
    Status.FAIL: "[red]✗[/red]",
}


def render_report(report: SelfDoctorReport, console) -> None:
    """Pretty-print a SelfDoctorReport to a Rich console."""
    from rich import box
    from rich.table import Table

    table = Table(box=box.SIMPLE)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail")
    for c in report.checks:
        table.add_row(c.name, _BADGE[c.status], c.detail)
    console.print(table)

    reclaim = report.total_reclaimable_bytes()
    if reclaim > 0:
        console.print(
            f"\n[bold]Reclaimable with --fix:[/bold] "
            f"{format_bytes(reclaim)}"
        )

    if report.fixes_applied:
        console.print("\n[bold]Fixes applied:[/bold]")
        for f in report.fixes_applied:
            console.print(f"  • {f}")

    overall = report.overall()
    console.print(f"\nOverall: {_BADGE[overall]} ({overall.value})")
