"""ROM organization helpers — restructure into per-game folders, write m3u
playlists for multi-disc games, etc.

Most HyperSpin systems work fine with a flat ROM directory (game.zip per ROM).
A small number of systems require per-game folders or multi-disc playlists:

* PS3, Xbox 360, Wii: each game is a folder containing many files.
* PS1/PS2/Saturn/Dreamcast multi-disc games: one folder per game with the
  individual disc images plus a ``Game.m3u`` playlist.

This module provides a *plan*-based workflow: build a plan, show it, optionally
apply it. Every applied plan writes a JSON manifest next to the ROM root so it
can be undone in one command.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# Map a HyperSpin/RocketLauncher system name → required ROM layout.
#   "per-game-folder"  — every ROM becomes its own folder.
#   "multi-disc-m3u"   — only multi-disc games are grouped + given an .m3u.
SYSTEMS_REQUIRING_FOLDERS: dict[str, str] = {
    "Sony Playstation 3": "per-game-folder",
    "Microsoft Xbox 360": "per-game-folder",
    "Nintendo Wii": "per-game-folder",
    "Nintendo Wii U": "per-game-folder",
    "Sony Playstation": "multi-disc-m3u",
    "Sony Playstation 2": "multi-disc-m3u",
    "Sega Saturn": "multi-disc-m3u",
    "Sega Dreamcast": "multi-disc-m3u",
    "Sega CD": "multi-disc-m3u",
    "TurboGrafx-CD": "multi-disc-m3u",
    "PC Engine CD": "multi-disc-m3u",
    "Panasonic 3DO": "multi-disc-m3u",
}

# File extensions that benefit from m3u playlists (disc images).
MULTI_DISC_EXTENSIONS = {".bin", ".cue", ".chd", ".iso", ".img", ".gdi", ".cdi"}

MANIFEST_PREFIX = "_spindoctor-restructure-"

_DISC_RE = re.compile(
    r"^(?P<base>.+?)\s*\(\s*Disc\s*(?P<n>\d+)[^)]*\)\s*$",
    re.IGNORECASE,
)


@dataclass
class FileMove:
    src: str  # absolute path string (JSON-friendly)
    dest: str

    def src_path(self) -> Path:
        return Path(self.src)

    def dest_path(self) -> Path:
        return Path(self.dest)


@dataclass
class FileCreate:
    path: str
    content: str


@dataclass
class RestructurePlan:
    system_name: str
    layout: str
    roms_dir: str
    moves: list[FileMove] = field(default_factory=list)
    creates: list[FileCreate] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.moves and not self.creates


def required_layout(system_name: str) -> Optional[str]:
    """Return the required layout for *system_name* or None if flat is fine."""
    from .config import get_system_overrides
    ovr = get_system_overrides().get(system_name, {})
    layout = ovr.get("layout")
    if isinstance(layout, str) and layout:
        return layout if layout != "flat" else None
    return SYSTEMS_REQUIRING_FOLDERS.get(system_name)


def plan_restructure(system_name: str, roms_dir: Path) -> RestructurePlan:
    """Build a plan to restructure *roms_dir/system_name* into the required layout.

    Returns an empty plan when no restructuring is needed (system is already
    correctly laid out, or it doesn't require nesting).
    """
    layout = required_layout(system_name)
    sys_dir = roms_dir / system_name
    plan = RestructurePlan(
        system_name=system_name,
        layout=layout or "flat",
        roms_dir=str(sys_dir),
    )

    if not layout:
        plan.notes.append(
            f"{system_name} uses a flat layout — no restructuring needed."
        )
        return plan

    if not sys_dir.exists():
        plan.notes.append(f"ROM directory not found: {sys_dir}")
        return plan

    if layout == "per-game-folder":
        _plan_per_game_folder(plan, sys_dir)
    elif layout == "multi-disc-m3u":
        _plan_multi_disc_m3u(plan, sys_dir)

    return plan


def _plan_per_game_folder(plan: RestructurePlan, sys_dir: Path) -> None:
    for entry in sorted(sys_dir.iterdir()):
        if entry.is_dir():
            plan.skipped.append(str(entry))
            continue
        if not entry.is_file():
            continue
        target_dir = sys_dir / entry.stem
        if target_dir.exists():
            plan.skipped.append(str(entry))
            continue
        plan.moves.append(FileMove(
            src=str(entry),
            dest=str(target_dir / entry.name),
        ))


def _plan_multi_disc_m3u(plan: RestructurePlan, sys_dir: Path) -> None:
    # Group files by base name (multi-disc) — only for files whose extension
    # is in MULTI_DISC_EXTENSIONS.  Single-disc games stay where they are.
    groups: dict[str, list[Path]] = {}
    for entry in sorted(sys_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in MULTI_DISC_EXTENSIONS:
            continue
        m = _DISC_RE.match(entry.stem)
        if not m:
            continue
        base = m.group("base").strip()
        groups.setdefault(base, []).append(entry)

    # Only restructure groups that actually have >1 disc.
    for base, files in groups.items():
        if len(files) < 2:
            continue
        target_dir = sys_dir / base
        if target_dir.exists() and any(target_dir.iterdir()):
            plan.skipped.append(base)
            continue

        # Sort by disc number so the m3u order is deterministic.
        files_sorted = sorted(
            files,
            key=lambda p: int(_DISC_RE.match(p.stem).group("n")),
        )

        for f in files_sorted:
            plan.moves.append(FileMove(
                src=str(f),
                dest=str(target_dir / f.name),
            ))

        # Build the m3u that lists discs by relative filename.
        m3u_lines = [f.name for f in files_sorted]
        plan.creates.append(FileCreate(
            path=str(target_dir / f"{base}.m3u"),
            content="\n".join(m3u_lines) + "\n",
        ))


# ─── apply / undo ─────────────────────────────────────────────────────────────

def apply_restructure(plan: RestructurePlan) -> Path:
    """Execute *plan* and write a manifest. Returns the manifest path.

    Raises if a destination collides with an existing file (caller should have
    seen this in the dry-run output).
    """
    if plan.empty:
        return _write_manifest(plan, applied_moves=[], applied_creates=[])

    applied_moves: list[FileMove] = []
    applied_creates: list[FileCreate] = []

    for move in plan.moves:
        src = Path(move.src)
        dest = Path(move.dest)
        if dest.exists():
            raise FileExistsError(f"Destination already exists: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        applied_moves.append(move)

    for create in plan.creates:
        path = Path(create.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(create.content, encoding="utf-8")
        applied_creates.append(create)

    return _write_manifest(plan, applied_moves, applied_creates)


def undo_restructure(manifest_path: Path) -> dict:
    """Reverse the restructure described by *manifest_path*. Returns a summary dict."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    moves = [FileMove(**m) for m in data.get("moves", [])]
    creates = [FileCreate(**c) for c in data.get("creates", [])]

    summary = {"moves_reverted": 0, "creates_removed": 0, "errors": []}

    # Remove generated files first so empty group folders can be cleaned up.
    for create in creates:
        p = Path(create.path)
        try:
            if p.exists():
                p.unlink()
                summary["creates_removed"] += 1
        except OSError as e:
            summary["errors"].append(f"Could not remove {p}: {e}")

    # Reverse moves in reverse order so directories that are about to be empty
    # don't get rmdir'd before their contents move out.
    for move in reversed(moves):
        src = Path(move.src)
        dest = Path(move.dest)
        try:
            if dest.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(src))
                summary["moves_reverted"] += 1
            else:
                summary["errors"].append(f"Missing during undo: {dest}")
        except OSError as e:
            summary["errors"].append(f"Could not undo move {dest} → {src}: {e}")

    # Best-effort cleanup of now-empty group directories.
    for move in moves:
        parent = Path(move.dest).parent
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    try:
        manifest_path.unlink()
    except OSError:
        pass

    return summary


def find_latest_manifest(system_name: str, roms_dir: Path) -> Optional[Path]:
    sys_dir = roms_dir / system_name
    if not sys_dir.exists():
        return None
    manifests = sorted(sys_dir.glob(f"{MANIFEST_PREFIX}*.json"))
    return manifests[-1] if manifests else None


def _write_manifest(
    plan: RestructurePlan,
    applied_moves: list[FileMove],
    applied_creates: list[FileCreate],
) -> Path:
    sys_dir = Path(plan.roms_dir)
    sys_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = sys_dir / f"{MANIFEST_PREFIX}{stamp}.json"
    payload = {
        "system": plan.system_name,
        "layout": plan.layout,
        "timestamp": stamp,
        "roms_dir": plan.roms_dir,
        "moves": [asdict(m) for m in applied_moves],
        "creates": [asdict(c) for c in applied_creates],
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path
