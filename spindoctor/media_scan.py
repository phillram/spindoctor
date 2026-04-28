"""Scan a folder of local media and audit it against HyperSpin databases.

The inverse of ``orphan_media`` — given a directory full of art the
user already has on disk (downloaded packs, custom wheels, EmuMovies
dumps) figure out which files correspond to known games and would be
useful to import. Each scanned file is bucketed as:

* ``matched``      — names a known game whose slot is empty (importable)
* ``replacement``  — names a known game whose slot is already filled
* ``unmatched``    — no fuzzy match in the database
* ``unknown_type`` — couldn't determine media type from path/extension

``import_media`` then copies / moves / symlinks the matched files into
the right HyperSpin slots, writing a JSON manifest so the operation
can be undone with ``--undo``.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import CONFIG_DIR, Config, MEDIA_TYPES
from .database import load_database
from .media import MEDIA_DIR_MAP, MEDIA_EXTENSIONS
from .romutils import find_best_match


MANIFEST_DIR = CONFIG_DIR / "media_imports"
MANIFEST_PREFIX = "import-"


# ─── type detection ───────────────────────────────────────────────────────────

# Folder hints (case-insensitive) → canonical media type from MEDIA_TYPES.
_FOLDER_HINTS: dict[str, str] = {
    "wheel": "wheel",
    "wheels": "wheel",
    "logo": "wheel",
    "logos": "wheel",
    "snap": "snap",
    "snaps": "snap",
    "screenshot": "snap",
    "screenshots": "snap",
    "background": "background",
    "backgrounds": "background",
    "artwork": "background",
    "artworks": "background",
    "box": "artwork",
    "boxart": "artwork",
    "boxes": "artwork",
    "cabinet": "artwork",
    "cabinets": "artwork",
    "title": "title",
    "titles": "title",
    "video": "video",
    "videos": "video",
    "trailer": "trailer",
    "trailers": "trailer",
    "theme": "theme",
    "themes": "theme",
    "sound": "sound",
    "sounds": "sound",
}

# Extensions we recognise as media. Anything else is ignored entirely.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
_VIDEO_EXTS = {".mp4", ".avi", ".flv", ".mkv", ".mov", ".webm"}
_SOUND_EXTS = {".mp3", ".wav", ".ogg", ".flac"}
_THEME_EXTS = {".zip", ".swf"}

_ALL_KNOWN_EXTS = _IMAGE_EXTS | _VIDEO_EXTS | _SOUND_EXTS | _THEME_EXTS


def _detect_type_from_path(path: Path) -> Optional[str]:
    """Walk the path components looking for a folder-name hint.

    The deepest (rightmost) hint wins, so ``Wheels/Sub/foo.png`` still
    reads as a wheel and ``Snaps/Wheels/foo.png`` (rare but possible)
    reads as a wheel.
    """
    found: Optional[str] = None
    for part in path.parts:
        hit = _FOLDER_HINTS.get(part.lower())
        if hit is not None:
            found = hit
    return found


def _detect_type_from_extension(path: Path) -> Optional[str]:
    """Fallback when no folder hint is present — infer from extension only.

    Images are ambiguous (wheel/snap/title/etc.), so they return None
    unless we have a folder hint. Videos default to ``video``, audio
    to ``sound``, ``.zip``/``.swf`` to ``theme``.
    """
    ext = path.suffix.lower()
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _SOUND_EXTS:
        return "sound"
    if ext in _THEME_EXTS:
        return "theme"
    return None


def detect_media_type(path: Path) -> Optional[str]:
    """Return one of ``MEDIA_TYPES`` or None if undetectable."""
    if path.suffix.lower() not in _ALL_KNOWN_EXTS:
        return None
    return _detect_type_from_path(path) or _detect_type_from_extension(path)


# ─── scanning ─────────────────────────────────────────────────────────────────

@dataclass
class LocalMediaFile:
    path: Path
    media_type: Optional[str]  # None means unknown_type
    size: int = 0


def scan_local_media(
    source_dir: Path,
    recursive: bool = True,
) -> list[LocalMediaFile]:
    """Walk *source_dir* and return one ``LocalMediaFile`` per media file.

    Files whose extension isn't recognised at all are silently skipped
    (they're not media). Files we recognise but can't classify are
    returned with ``media_type=None`` so the caller can bucket them as
    ``unknown_type``.
    """
    src = Path(source_dir)
    if not src.exists() or not src.is_dir():
        return []
    iterator = src.rglob("*") if recursive else src.iterdir()
    out: list[LocalMediaFile] = []
    for p in iterator:
        if not p.is_file():
            continue
        if p.suffix.lower() not in _ALL_KNOWN_EXTS:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append(LocalMediaFile(
            path=p,
            media_type=detect_media_type(p),
            size=size,
        ))
    out.sort(key=lambda f: str(f.path).lower())
    return out


# ─── matching ─────────────────────────────────────────────────────────────────

@dataclass
class ScanMatch:
    local: LocalMediaFile
    system: str
    game_name: Optional[str] = None
    score: float = 0.0
    target_path: Optional[Path] = None  # destination if imported
    target_exists: bool = False         # slot already filled
    bucket: str = "unmatched"           # matched | replacement | unmatched | unknown_type


@dataclass
class MediaScanReport:
    source_dir: Path
    matched: list[ScanMatch] = field(default_factory=list)
    replacement: list[ScanMatch] = field(default_factory=list)
    unmatched: list[ScanMatch] = field(default_factory=list)
    unknown_type: list[ScanMatch] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.matched) + len(self.replacement)
            + len(self.unmatched) + len(self.unknown_type)
        )

    def all(self) -> list[ScanMatch]:
        return [*self.matched, *self.replacement,
                *self.unmatched, *self.unknown_type]


def _media_target_path(
    config: Config,
    system_name: str,
    game_name: str,
    media_type: str,
    source_ext: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """Compute the HyperSpin slot path for *media_type*.

    Mirrors ``MediaDownloader.media_path`` but we keep the source
    extension when it differs from the canonical extension (e.g. a
    .jpg wheel still drops in as ``Mario.jpg``).
    """
    base = (output_dir / "Media") if output_dir else config.media_dir
    parts = MEDIA_DIR_MAP.get(media_type, (media_type.capitalize(),))
    canonical_ext = MEDIA_EXTENSIONS.get(media_type, "")
    ext = source_ext.lower() or canonical_ext
    return base / system_name / Path(*parts) / f"{game_name}{ext}"


def match_to_database(
    scan_results: Iterable[LocalMediaFile],
    system_name: str,
    config: Config,
    types: Optional[Iterable[str]] = None,
    output_dir: Optional[Path] = None,
) -> MediaScanReport:
    """Match each scanned file against games in *system_name*'s DB.

    *types*, if given, restricts which media types are considered;
    files of any other type are ignored entirely (not bucketed).
    """
    files = list(scan_results)
    src_dir = Path(files[0].path).parent if files else Path(".")
    report = MediaScanReport(source_dir=src_dir)

    db = load_database(system_name, config.databases_dir)
    candidates = list(db.games().keys())

    type_filter = set(types) if types else None
    threshold = config.match_threshold

    for f in files:
        if f.media_type is None:
            report.unknown_type.append(ScanMatch(
                local=f, system=system_name, bucket="unknown_type",
            ))
            continue
        if type_filter and f.media_type not in type_filter:
            continue

        match = find_best_match(f.path.stem, candidates, threshold=threshold)
        if match is None:
            report.unmatched.append(ScanMatch(
                local=f, system=system_name, bucket="unmatched",
            ))
            continue

        game_name, score = match
        target = _media_target_path(
            config, system_name, game_name, f.media_type,
            f.path.suffix, output_dir=output_dir,
        )
        sm = ScanMatch(
            local=f, system=system_name,
            game_name=game_name, score=score,
            target_path=target, target_exists=target.exists(),
        )
        if target.exists():
            sm.bucket = "replacement"
            report.replacement.append(sm)
        else:
            sm.bucket = "matched"
            report.matched.append(sm)

    return report


def merge_reports(reports: Iterable[MediaScanReport]) -> MediaScanReport:
    """Combine per-system reports into one. Source dir from the first."""
    reports = list(reports)
    if not reports:
        return MediaScanReport(source_dir=Path("."))
    out = MediaScanReport(source_dir=reports[0].source_dir)
    for r in reports:
        out.matched.extend(r.matched)
        out.replacement.extend(r.replacement)
        out.unmatched.extend(r.unmatched)
        out.unknown_type.extend(r.unknown_type)
    return out


# ─── import (copy / move / link) + manifest ──────────────────────────────────

@dataclass
class ImportResult:
    imported: list[tuple[Path, Path]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    manifest_path: Optional[Path] = None


def _do_action(src: Path, dest: Path, action: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if action == "copy":
        shutil.copy2(src, dest)
    elif action == "move":
        shutil.move(str(src), str(dest))
    elif action == "link":
        # Symlink — fall back to copy on platforms / FS that reject it.
        try:
            dest.symlink_to(src.resolve())
        except (OSError, NotImplementedError):
            shutil.copy2(src, dest)
    else:
        raise ValueError(f"unknown action: {action}")


def import_media(
    report: MediaScanReport,
    config: Config,
    action: str = "copy",
    overwrite: bool = False,
    include_replacements: bool = False,
    output_dir: Optional[Path] = None,
    manifest_dir: Optional[Path] = None,
) -> ImportResult:
    """Import the ``matched`` (and optionally ``replacement``) entries.

    Writes a JSON manifest under ``~/.spindoctor/media_imports/`` so a
    subsequent ``undo_import`` call can reverse the operation.
    """
    if action not in {"copy", "move", "link"}:
        raise ValueError(f"unknown action: {action!r}")

    result = ImportResult()
    items: list[ScanMatch] = list(report.matched)
    if include_replacements:
        items.extend(report.replacement)

    manifest_entries: list[dict] = []
    for sm in items:
        if sm.target_path is None:
            result.skipped.append((sm.local.path, "no target path"))
            continue
        target = sm.target_path
        if target.exists() and not overwrite:
            result.skipped.append((sm.local.path, f"exists: {target}"))
            continue
        try:
            _do_action(sm.local.path, target, action)
        except (OSError, shutil.Error) as e:
            result.skipped.append((sm.local.path, f"{action} failed: {e}"))
            continue
        result.imported.append((sm.local.path, target))
        manifest_entries.append({
            "src": str(sm.local.path),
            "dest": str(target),
            "system": sm.system,
            "game": sm.game_name or "",
            "media_type": sm.local.media_type or "",
            "action": action,
            "overwrote": bool(overwrite and sm.target_exists),
        })

    if not manifest_entries:
        return result

    out_dir = manifest_dir or MANIFEST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = out_dir / f"{MANIFEST_PREFIX}{stamp}.json"
    manifest_path.write_text(
        json.dumps({
            "timestamp": stamp,
            "source_dir": str(report.source_dir),
            "action": action,
            "output_dir": str(output_dir) if output_dir else "",
            "imports": manifest_entries,
        }, indent=2),
        encoding="utf-8",
    )
    result.manifest_path = manifest_path
    return result


def undo_import(manifest_path: Path) -> dict:
    """Reverse the import described by *manifest_path*.

    For ``copy``/``link`` actions the destination is removed. For
    ``move`` the file is moved back to its original location.
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary: dict = {"reverted": 0, "errors": []}
    for entry in reversed(data.get("imports", [])):
        src = Path(entry["src"])
        dest = Path(entry["dest"])
        action = entry.get("action", "copy")
        try:
            if action == "move":
                if not dest.exists():
                    summary["errors"].append(f"missing during undo: {dest}")
                    continue
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(src))
            else:
                # copy / link: just remove the destination
                if dest.is_symlink() or dest.exists():
                    dest.unlink()
            summary["reverted"] += 1
        except OSError as e:
            summary["errors"].append(f"could not revert {dest}: {e}")
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return summary


def list_manifests(manifest_dir: Optional[Path] = None) -> list[Path]:
    out_dir = manifest_dir or MANIFEST_DIR
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob(f"{MANIFEST_PREFIX}*.json"))


def find_latest_manifest(manifest_dir: Optional[Path] = None) -> Optional[Path]:
    manifests = list_manifests(manifest_dir)
    return manifests[-1] if manifests else None


# ─── CSV reporting ────────────────────────────────────────────────────────────

def report_to_rows(report: MediaScanReport) -> list[dict]:
    """Flatten a report into CSV-ready rows."""
    rows: list[dict] = []
    for sm in report.all():
        rows.append({
            "bucket": sm.bucket,
            "source": str(sm.local.path),
            "media_type": sm.local.media_type or "",
            "system": sm.system,
            "game": sm.game_name or "",
            "score": f"{sm.score:.2f}" if sm.score else "",
            "target": str(sm.target_path) if sm.target_path else "",
        })
    return rows


def write_csv_report(report: MediaScanReport, csv_path: Path) -> None:
    import csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = report_to_rows(report)
    fields = ["bucket", "source", "media_type", "system",
              "game", "score", "target"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ─── public list of valid media types (re-exported for CLI choice) ────────────

VALID_MEDIA_TYPES = list(MEDIA_TYPES)


__all__ = [
    "LocalMediaFile",
    "ScanMatch",
    "MediaScanReport",
    "ImportResult",
    "MANIFEST_DIR",
    "VALID_MEDIA_TYPES",
    "detect_media_type",
    "scan_local_media",
    "match_to_database",
    "merge_reports",
    "import_media",
    "undo_import",
    "list_manifests",
    "find_latest_manifest",
    "report_to_rows",
    "write_csv_report",
]
