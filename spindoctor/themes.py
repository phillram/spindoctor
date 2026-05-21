"""HyperSpin frontend theme inventory + replacement.

Two halves:

1. **Scan** (read-only) — :func:`scan_frontend_art` walks the HyperSpin
   install and returns one :class:`ThemeAsset` per overlay file found
   under ``Media/Frontend/Images/`` and per-system
   ``Media/<system>/Images/{Special A,Special B}``. These are the
   folders HyperHQ → Special A/B writes into and the most common
   place "controller hint glyph" art lives.

2. **Apply** (read-write) — :func:`plan_apply` takes a source folder
   of replacement images (e.g. a community "PS Buttons" pack), walks
   it, and matches each source file to every existing target by
   filename. :func:`apply_plan` performs the swaps with a manifest
   under ``~/.spindoctor/themes/`` so the Undo Center / CLI ``--undo``
   can reverse the whole run later.

Out of scope: editing embedded glyphs inside ``.swf`` Flash theme
zips. Those need a SWF authoring tool — :func:`has_swf_themes` flags
the case so callers can warn instead of silently doing nothing.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import CONFIG_DIR, Config


# Where every applied swap drops its manifest + originals. Mirrors the
# layout of `migrations/`, `curation/`, etc. — one folder per run, each
# folder self-contained so a corrupted entry can't poison the others.
THEMES_DIR = CONFIG_DIR / "themes"
_MANIFEST_FILENAME = "manifest.json"


# Canonical extensions HyperSpin uses for overlay art. Other formats
# (.bmp, .gif) work but aren't community standard — we surface them
# anyway when found, just labeled "image".
_OVERLAY_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}

# Filename keywords commonly found in controller-glyph art. Used by
# the optional --keyword filter (and the GUI's filter box) to narrow
# a multi-thousand-file scan down to "things that probably look like
# controller buttons". Lowercased; substring match.
KNOWN_GLYPH_KEYWORDS: tuple[str, ...] = (
    "xbox", "x360", "xbone", "xbox360",
    "playstation", "ps3", "ps4", "ps5", "ps2", "psx", "dualshock",
    "switch", "joycon", "joy-con",
    "arcade", "button", "stick", "joystick",
    "nintendo", "nes", "snes", "n64",
    "controller", "gamepad", "pad",
    "specialA", "special_a", "specialB", "special_b",
    "hint", "overlay",
)


@dataclass(frozen=True)
class ThemeAsset:
    """One overlay file with everything the scanner / GUI needs to render it.

    ``scope`` distinguishes universal frontend art ("Frontend") from
    per-system Special A/B overlays so the GUI can group by it. ``kind``
    is the lowercased file extension without the dot — used by the
    image-viewer fallback to decide whether to even try opening.
    """
    path: Path
    scope: str          # "Frontend" or system name
    bucket: str         # "Frontend / Images" or "Special A" / "Special B"
    kind: str           # extension sans dot ("png", "swf", …)
    size_bytes: int
    modified: datetime


def _safe_iterdir(d: Path) -> Iterable[Path]:
    """Yield direct children of *d* without raising on missing dirs.

    The scanner walks several optional locations — most cabinets won't
    have every one populated. Bubbling FileNotFoundError up to the
    caller would force them to wrap each call in a try/except, which
    is just noise.
    """
    try:
        yield from d.iterdir()
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return


def _collect_files(directory: Path, scope: str, bucket: str) -> list[ThemeAsset]:
    """Return one :class:`ThemeAsset` per overlay-extension file in *directory*.

    Recursive — many cabinets organise Special A art into per-game
    sub-folders, and we want those too. Skips dotfiles and anything
    without an :data:`_OVERLAY_EXTS` extension.
    """
    out: list[ThemeAsset] = []
    if not directory.exists():
        return out
    for path in directory.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        if ext not in _OVERLAY_EXTS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append(ThemeAsset(
            path=path,
            scope=scope,
            bucket=bucket,
            kind=ext.lstrip("."),
            size_bytes=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime),
        ))
    return out


def scan_frontend_art(config: Config) -> list[ThemeAsset]:
    """Collect every Frontend / Special A / Special B overlay file.

    Order: Frontend universal art first, then per-system buckets
    sorted by system name. Within a bucket, files come out in
    ``rglob`` order (the OS's directory traversal). Callers that need
    a specific sort apply it themselves — sorting is a display
    concern, not a scanner concern.
    """
    if not config.hyperspin_dir:
        return []
    media = Path(config.hyperspin_dir) / "Media"
    out: list[ThemeAsset] = []

    # Universal frontend art — covers the bottom-of-screen hint
    # graphics on the Main Menu and falls back to per-system overrides
    # when those aren't set.
    out.extend(_collect_files(
        media / "Frontend" / "Images",
        scope="Frontend", bucket="Frontend / Images",
    ))

    # Per-system Special A/B buckets. We list every system folder we
    # see under Media/, not just ones in the Main Menu — extra noise
    # is cheaper than missing a folder the user actually cares about.
    for system_dir in sorted(_safe_iterdir(media)):
        if not system_dir.is_dir() or system_dir.name == "Frontend":
            continue
        for bucket_label in ("Special A", "Special B"):
            out.extend(_collect_files(
                system_dir / "Images" / bucket_label,
                scope=system_dir.name, bucket=bucket_label,
            ))
    return out


def filter_assets(
    assets: Iterable[ThemeAsset],
    *,
    system: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[ThemeAsset]:
    """Return *assets* narrowed by an optional system + filename keyword.

    *system* matches ``ThemeAsset.scope`` exactly (case-sensitive — the
    on-disk folder names are the source of truth). *keyword* is a
    case-insensitive substring match against the filename, useful for
    "show me everything that might be Xbox glyphs" via ``"xbox"``.
    """
    out = list(assets)
    if system:
        out = [a for a in out if a.scope == system]
    if keyword:
        kw = keyword.lower()
        out = [a for a in out if kw in a.path.name.lower()]
    return out


def has_swf_themes(config: Config) -> bool:
    """Quick heuristic: are any frontend overlays embedded inside SWFs?

    Used by the CLI / GUI to surface a "your glyphs may live inside
    `default.zip` (Flash) — SpinDoctor can't edit those" warning when
    a scan returns no PNG hits. Looks at the Main Menu themes folder
    only; per-system theme zips are a different concern (per-game
    art, not frontend overlays).
    """
    if not config.hyperspin_dir:
        return False
    main_themes = (Path(config.hyperspin_dir) / "Media" / "Main Menu"
                   / "Themes")
    if not main_themes.exists():
        return False
    return any(p.suffix.lower() in {".swf", ".zip"}
               for p in _safe_iterdir(main_themes))


# ─── Apply / undo ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SwapPlan:
    """One source→target swap. Filename-based matching, so a single
    source file can produce multiple :class:`SwapPlan` entries (e.g.
    ``select.png`` exists under several systems' Special A folders)."""
    source: Path
    target: Path
    target_scope: str
    target_bucket: str


@dataclass
class ApplyResult:
    """Outcome of :func:`apply_plan`. Counts plus a manifest pointer
    so the caller can surface "view manifest" / "undo" links."""
    swapped: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    manifest_path: Optional[Path] = None


@dataclass
class PackCreateResult:
    """Outcome of :func:`create_pack`."""
    files_copied: int = 0
    bytes_copied: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    output_dir: Optional[Path] = None


def _enumerate_source_pack(source_dir: Path) -> dict[str, Path]:
    """Map lowercase filename → source Path for every overlay-extension
    file in *source_dir* (recursively).

    Filename collisions across sub-folders pick the first one found
    by ``rglob`` — community packs almost never have collisions, and
    the alternative (refusing to apply on collision) is more annoying
    than helpful in practice.
    """
    out: dict[str, Path] = {}
    for path in source_dir.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        if ext not in _OVERLAY_EXTS:
            continue
        out.setdefault(path.name.lower(), path)
    return out


def plan_apply(
    config: Config,
    source_dir: Path,
    *,
    target: Optional[str] = None,
    systems: Optional[list[str]] = None,
) -> list[SwapPlan]:
    """Build the list of swaps for replacing frontend art with *source_dir*.

    *target* narrows the candidate pool (single scope):

    * ``None`` or ``"all"`` — every Frontend / Special A / Special B file.
    * ``"frontend"`` — only the universal ``Media/Frontend/Images``
      bucket. Useful when a pack is generic (no per-system art).
    * any other string — treated as a system name; only that system's
      Special A/B folders are considered.

    *systems* accepts a list of system names (e.g. ``["MAME", "Sega
    Naomi"]``). When provided it overrides *target* for the system-name
    filtering step: only those systems' Special A/B folders are
    considered. Useful for applying a pack to several wheels at once
    without touching the universal Frontend bucket.

    Each match is one :class:`SwapPlan`. A source file with no matching
    target name is dropped silently (the source pack just has spare
    files that don't apply to this cabinet).
    """
    sources = _enumerate_source_pack(source_dir)
    if not sources:
        return []

    all_targets = scan_frontend_art(config)

    if systems:
        # Multi-system filter: include Frontend + every named system.
        systems_set = set(systems)
        targets = [t for t in all_targets if t.scope in systems_set]
    elif target and target.lower() != "all":
        if target.lower() == "frontend":
            targets = [t for t in all_targets if t.scope == "Frontend"]
        else:
            # Exact match against the on-disk system folder name.
            targets = [t for t in all_targets if t.scope == target]
    else:
        targets = all_targets

    plans: list[SwapPlan] = []
    for t in targets:
        src = sources.get(t.path.name.lower())
        if src is None:
            continue
        plans.append(SwapPlan(
            source=src,
            target=t.path,
            target_scope=t.scope,
            target_bucket=t.bucket,
        ))
    return plans


def apply_plan(
    plans: Iterable[SwapPlan],
    *,
    manifest_dir: Optional[Path] = None,
) -> ApplyResult:
    """Execute *plans*, backing up every overwritten file under a
    timestamped manifest folder.

    For each plan: copy ``target`` to ``<manifest_dir>/<run>/backup/...``
    preserving the original's relative path under ``Media/``, then
    copy ``source`` over ``target``. The whole list is written to a
    JSON manifest at the run's root so :func:`undo_plan` can reverse
    the run later (or :func:`spindoctor.cli.undo` via the Undo
    Center).

    On any I/O error, the in-progress run is recorded as far as it
    got — the manifest only contains successfully-swapped entries,
    never the failed ones. Callers see a non-zero ``skipped`` count
    and can re-run with the failures fixed.
    """
    base = manifest_dir or THEMES_DIR
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = base / f"theme-apply-{stamp}"
    run_dir.mkdir()
    backup_root = run_dir / "backup"

    result = ApplyResult()
    swap_records: list[dict] = []

    plans_list = list(plans)
    for p in plans_list:
        try:
            # Mirror the on-disk relative path under backup/ so we can
            # walk it back the same way during undo. Using the bytes
            # under "Media/" as the key keeps the path portable
            # between Windows and POSIX.
            try:
                rel = p.target.relative_to(p.target.anchor)
            except ValueError:
                rel = Path(p.target.name)
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p.target, backup)
            shutil.copy2(p.source, p.target)
        except OSError as exc:
            result.skipped.append((p.target, str(exc)))
            continue
        swap_records.append({
            "source": str(p.source),
            "target": str(p.target),
            "backup": str(backup),
            "target_scope": p.target_scope,
            "target_bucket": p.target_bucket,
        })
        result.swapped += 1

    if swap_records:
        manifest_path = run_dir / _MANIFEST_FILENAME
        manifest_path.write_text(json.dumps({
            "timestamp": stamp,
            "swaps": swap_records,
        }, indent=2), encoding="utf-8")
        result.manifest_path = manifest_path
    else:
        # No swaps applied — clean up the empty run folder so we
        # don't litter ~/.spindoctor with empty manifests.
        try:
            shutil.rmtree(run_dir)
        except OSError:
            pass
    return result


def undo_plan(manifest_path: Path) -> dict:
    """Restore every backup recorded in *manifest_path*.

    Returns ``{"restored": int, "errors": list[str]}``.
    Missing backups and files that cannot be restored are reported in ``errors``.
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    result: dict = {"restored": 0, "errors": []}
    for entry in data.get("swaps", []):
        backup = Path(entry["backup"])
        target = Path(entry["target"])
        if not backup.exists():
            result["errors"].append(f"backup file missing, cannot restore: {target}")
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            result["restored"] += 1
        except OSError as exc:
            result["errors"].append(f"could not restore {target}: {exc}")
    return result


def list_manifests(manifest_dir: Optional[Path] = None) -> list[Path]:
    """Return every existing theme-apply manifest, newest first.

    Used by the CLI's ``--list-manifests`` flag and the GUI's "List
    manifests" button — the same shape every other reversible
    SpinDoctor command exposes.
    """
    base = manifest_dir or THEMES_DIR
    if not base.exists():
        return []
    out: list[Path] = []
    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        manifest = run_dir / _MANIFEST_FILENAME
        if manifest.exists():
            out.append(manifest)
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def find_latest_manifest(manifest_dir: Optional[Path] = None) -> Optional[Path]:
    """First entry from :func:`list_manifests`, or ``None`` if there
    are no theme-apply manifests on disk yet."""
    manifests = list_manifests(manifest_dir)
    return manifests[0] if manifests else None


def undo_plan_system(manifest_path: Path, system: str) -> dict:
    """Restore only the files belonging to *system* from *manifest_path*.

    Like :func:`undo_plan` but scoped to a single ``target_scope`` so
    a multi-system swap can be partially reversed — e.g. roll back
    "Sega Naomi" without touching every other wheel the pack touched.

    Returns ``{"restored": int, "errors": list[str]}``.
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    result: dict = {"restored": 0, "errors": []}
    for entry in data.get("swaps", []):
        if entry.get("target_scope") != system:
            continue
        backup = Path(entry["backup"])
        target = Path(entry["target"])
        if not backup.exists():
            result["errors"].append(f"backup file missing, cannot restore: {target}")
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            result["restored"] += 1
        except OSError as exc:
            result["errors"].append(f"could not restore {target}: {exc}")
    return result


def list_systems_in_manifest(manifest_path: Path) -> list[str]:
    """Return the unique system names (``target_scope`` values) recorded
    in *manifest_path*, sorted alphabetically.

    Used by the GUI's per-system revert picker to populate a dropdown
    without parsing the JSON twice.
    """
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    scopes: set[str] = set()
    for entry in data.get("swaps", []):
        scope = entry.get("target_scope", "")
        if scope:
            scopes.add(scope)
    return sorted(scopes)


def create_pack(
    config: Config,
    output_dir: Path,
    *,
    target: Optional[str] = None,
) -> PackCreateResult:
    """Snapshot the cabinet's current Frontend / Special A / Special B art
    into a directory tree shaped like a community pack.

    Walks the same folders :func:`scan_frontend_art` covers and copies
    each overlay file to::

        <output_dir>/<scope>/<bucket>/<filename>

    where ``scope`` is ``"Frontend"`` or the system name, and ``bucket``
    is ``"Frontend/Images"``, ``"Special A"``, or ``"Special B"``. The
    resulting tree is accepted by :func:`plan_apply` (and its CLI
    counterpart ``theme-apply``) so users can back up, share, or
    migrate their art alongside a library migration.

    *target* narrows which art is snapshotted:

    * ``None`` / ``"all"`` — everything (default).
    * ``"frontend"`` — only ``Media/Frontend/Images``.
    * any other string — only that system's Special A/B buckets.
    """
    assets = scan_frontend_art(config)
    if target and target.lower() not in ("", "all"):
        if target.lower() == "frontend":
            assets = [a for a in assets if a.scope == "Frontend"]
        else:
            assets = [a for a in assets if a.scope == target]

    output_dir.mkdir(parents=True, exist_ok=True)
    result = PackCreateResult(output_dir=output_dir)

    for asset in assets:
        # "Frontend / Images" → "Frontend/Images"; "Special A" stays as-is.
        bucket_path = asset.bucket.replace(" / ", "/")
        dest_dir = output_dir / asset.scope / bucket_path
        dest = dest_dir / asset.path.name
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset.path, dest)
            result.files_copied += 1
            result.bytes_copied += asset.size_bytes
        except OSError as exc:
            result.skipped.append((asset.path, str(exc)))

    return result
