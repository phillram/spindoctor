"""Multi-disc validation for PS1/PS2/Saturn/Dreamcast layouts.

Two distinct checks:

1. **Disc completeness** — when a folder contains ``Game (Disc 2).cue``,
   we expect ``Disc 1`` (and any higher numbered discs that exist between)
   to be present. A missing intermediate disc is reported.

2. **m3u integrity** — when an ``.m3u`` playlist is present, every line
   inside must resolve to a file relative to the playlist. Stale lines or
   missing referenced files are reported.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .config import Config


_DISC_RE = re.compile(
    r"^(?P<base>.+?)\s*\(\s*Disc\s*(?P<n>\d+)[^)]*\)\s*$",
    re.IGNORECASE,
)
_DISC_EXTS = {".bin", ".cue", ".chd", ".iso", ".img", ".gdi", ".cdi"}


@dataclass
class DiscIssue:
    kind: str        # "missing-disc" | "missing-m3u-target" | "playlist-references-missing"
    location: Path   # folder or file the issue lives in
    detail: str


@dataclass
class DiscReport:
    system: str
    issues: list[DiscIssue] = field(default_factory=list)
    games_checked: int = 0
    playlists_checked: int = 0


def _iter_disc_folders(roms_dir: Path) -> Iterable[Path]:
    """Yield every directory we'll inspect.

    For multi-disc systems users typically restructure into per-game folders
    (see ``organize.py``). We also walk top-level files in case the layout
    is still flat.
    """
    yield roms_dir
    for entry in roms_dir.iterdir():
        if entry.is_dir():
            yield entry


def _check_disc_completeness(folder: Path, report: DiscReport) -> None:
    by_base: dict[str, list[int]] = defaultdict(list)
    for entry in folder.iterdir():
        if not entry.is_file() or entry.suffix.lower() not in _DISC_EXTS:
            continue
        m = _DISC_RE.match(entry.stem)
        if not m:
            continue
        base = m.group("base").strip()
        by_base[base].append(int(m.group("n")))

    for base, discs in by_base.items():
        report.games_checked += 1
        if not discs:
            continue
        unique = sorted(set(discs))
        expected = list(range(1, max(unique) + 1))
        missing = [n for n in expected if n not in unique]
        if missing:
            report.issues.append(DiscIssue(
                kind="missing-disc",
                location=folder,
                detail=(
                    f"{base}: have discs {unique}, missing "
                    f"{missing}"
                ),
            ))


def _check_m3u(playlist: Path, report: DiscReport) -> None:
    report.playlists_checked += 1
    try:
        lines = [
            ln.strip() for ln in playlist.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    except OSError as e:
        report.issues.append(DiscIssue(
            kind="missing-m3u-target",
            location=playlist,
            detail=f"could not read playlist: {e}",
        ))
        return

    missing: list[str] = []
    for line in lines:
        target = (playlist.parent / line).resolve()
        if not target.exists():
            missing.append(line)
    if missing:
        report.issues.append(DiscIssue(
            kind="playlist-references-missing",
            location=playlist,
            detail=f"missing {len(missing)} referenced file(s): "
                   + ", ".join(missing[:5])
                   + ("…" if len(missing) > 5 else ""),
        ))


def check_discs(system_name: str, config: Config) -> DiscReport:
    """Validate multi-disc layout for *system_name*."""
    report = DiscReport(system=system_name)
    roms_dir = Path(config.roms_dir) / system_name
    if not roms_dir.exists():
        return report

    for folder in _iter_disc_folders(roms_dir):
        if folder.exists() and folder.is_dir():
            _check_disc_completeness(folder, report)

    for playlist in roms_dir.rglob("*.m3u"):
        _check_m3u(playlist, report)

    return report
