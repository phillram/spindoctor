"""Find media assets whose game no longer exists.

The audit command checks the *forward* direction: every game in the
database / ROM directory should have its media files present. This
module checks the *reverse* direction: every file under
``Media/<system>/...`` should correspond to a game that's still in the
database or ROM directory. Anything else is an orphan — a leftover
wheel, snap, video, or theme from a game that's been removed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .audit import scan_roms
from .config import Config
from .database import load_database


# Media-directory layout under Media/<system>/. Mirrors check_media in audit.py
# and excludes "Themes" because those live as folders, not flat files.
_MEDIA_SUBDIRS = (
    ("Images/Wheel",       {".png", ".jpg", ".jpeg"}),
    ("Images/Backgrounds", {".png", ".jpg", ".jpeg"}),
    ("Images/Artwork1",    {".png", ".jpg", ".jpeg"}),
    ("Images/Artwork2",    {".png", ".jpg", ".jpeg"}),
    ("Images/Artwork3",    {".png", ".jpg", ".jpeg"}),
    ("Video",              {".mp4", ".avi", ".flv", ".mkv"}),
    ("Video/Trailers",     {".mp4", ".avi", ".flv", ".mkv"}),
    ("Sound",              {".mp3", ".wav", ".ogg"}),
)


@dataclass
class OrphanMedia:
    path: Path
    system: str
    media_type: str  # "Wheel" | "Backgrounds" | "Video" | ...

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass
class OrphanReport:
    system: str
    orphans: list[OrphanMedia] = field(default_factory=list)
    by_type: dict[str, int] = field(default_factory=dict)


def find_orphan_media(system_name: str, config: Config) -> OrphanReport:
    """Walk media folders and flag any file whose stem isn't a known game.

    Known games = (DB entries) ∪ (ROM stems). A file is an orphan when
    its stem matches neither set.
    """
    report = OrphanReport(system=system_name)
    media_root = config.media_dir / system_name
    if not media_root.exists():
        return report

    db = load_database(system_name, config.databases_dir)
    known: set[str] = set(db.games().keys())
    known.update(scan_roms(system_name, Path(config.roms_dir)).keys())

    for subdir, exts in _MEDIA_SUBDIRS:
        d = media_root / subdir
        if not d.exists() or not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or f.suffix.lower() not in exts:
                continue
            if f.stem in known:
                continue
            media_type = subdir.split("/")[-1]
            report.orphans.append(OrphanMedia(
                path=f, system=system_name, media_type=media_type,
            ))
            report.by_type[media_type] = report.by_type.get(media_type, 0) + 1

    # Theme folders: each game gets its own subfolder under Themes/<game>/
    theme_root = media_root / "Themes"
    if theme_root.exists():
        for entry in theme_root.iterdir():
            if entry.is_dir() and entry.name not in known:
                report.orphans.append(OrphanMedia(
                    path=entry, system=system_name, media_type="Themes",
                ))
                report.by_type["Themes"] = report.by_type.get("Themes", 0) + 1

    report.orphans.sort(key=lambda o: (o.media_type, o.path.name.lower()))
    return report


def delete_orphans(orphans: Iterable[OrphanMedia]) -> tuple[int, list[str]]:
    """Delete each orphan path. Returns (count_deleted, errors)."""
    import shutil
    deleted = 0
    errors: list[str] = []
    for o in orphans:
        try:
            if o.path.is_dir():
                shutil.rmtree(o.path)
            else:
                o.path.unlink()
            deleted += 1
        except OSError as e:
            errors.append(f"{o.path}: {e}")
    return deleted, errors
