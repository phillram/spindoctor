"""Detect ROMs that are likely in the wrong system folder.

A ROM is *misplaced* when its file extension does not match any extension
the containing system claims. e.g. a ``.nes`` file inside the ``snes``
folder, or an ``.iso`` inside ``GameBoy``. The scanner suggests one or
more candidate systems whose extension list does include the file's
extension so the user can decide where to move it.

When the user passes ``--apply`` to the CLI, ``apply_moves`` relocates
each misplaced ROM to its suggested system folder and writes a JSON
manifest so the change can be undone with ``--undo``.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import Config, ROM_EXTENSIONS, get_rom_extensions, get_system_overrides


MANIFEST_PREFIX = "_spindoctor-misplaced-"


# Generic container extensions that match many systems and don't tell us
# anything about the actual platform — exclude from "misplaced" reasoning
# because their presence is never wrong on its own.
_GENERIC_EXTS = {".zip", ".7z", ".rar", ".bin", ".cue", ".iso", ".img", ".chd"}


@dataclass
class MisplacedRom:
    path: Path
    current_system: str
    extension: str
    suggested_systems: list[str] = field(default_factory=list)
    reason: str = "extension"


def _all_known_systems_with_ext(ext: str, known_systems: Iterable[str]) -> list[str]:
    """Return every known system whose extension list contains ``ext``.

    Looks at both the hardcoded ``ROM_EXTENSIONS`` table and any user
    ``system_overrides`` so a custom system contributes to suggestions.
    """
    ext = ext.lower()
    matches: set[str] = set()

    for key, exts in ROM_EXTENSIONS.items():
        if key == "default":
            continue
        if ext in (e.lower() for e in exts):
            matches.add(key)

    overrides = get_system_overrides()
    for sys_name, ovr in overrides.items():
        ovr_exts = ovr.get("rom_extensions") or []
        norm = {(e if e.startswith(".") else f".{e}").lower() for e in ovr_exts}
        if ext in norm:
            matches.add(sys_name)

    # Prefer real configured systems where they exist
    known = {s for s in known_systems}
    ranked = sorted(matches, key=lambda s: (s not in known, s.lower()))
    return ranked


def find_misplaced_in_system(
    system_name: str,
    config: Config,
    known_systems: Iterable[str] = (),
) -> list[MisplacedRom]:
    """Walk a system's ROM folder and flag every file whose extension is
    not declared by that system.

    Generic container extensions (``.zip``, ``.bin``, ``.iso``, …) that
    could legitimately belong to almost any platform are skipped — those
    are ambiguous on inspection alone and would only create false noise.
    """
    roms_dir = Path(config.roms_dir) / system_name
    if not roms_dir.exists():
        return []

    expected = {e.lower() for e in get_rom_extensions(system_name)}
    overrides = get_system_overrides().get(system_name, {})
    recursive = bool(overrides.get("recursive_scan"))
    iterator = roms_dir.rglob("*") if recursive else roms_dir.iterdir()

    misplaced: list[MisplacedRom] = []
    for path in iterator:
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if not ext or ext in expected:
            continue
        if ext in _GENERIC_EXTS:
            continue
        suggested = _all_known_systems_with_ext(ext, known_systems)
        # If no other system owns this extension, it's probably noise
        # (a .txt, .nfo, screenshot...) and shouldn't be reported.
        if not suggested:
            continue
        misplaced.append(
            MisplacedRom(
                path=path,
                current_system=system_name,
                extension=ext,
                suggested_systems=suggested,
                reason="extension",
            )
        )
    misplaced.sort(key=lambda m: (m.extension, m.path.name.lower()))
    return misplaced


# ─── apply / undo ─────────────────────────────────────────────────────────────

@dataclass
class MoveResult:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def apply_moves(
    items: Iterable[MisplacedRom],
    config: Config,
    manifest_dir: Optional[Path] = None,
) -> tuple[MoveResult, Optional[Path]]:
    """Move each *items* entry into its first suggested system folder.

    Items with no suggestion or whose target already exists are skipped
    (with a reason). Returns a ``MoveResult`` and the manifest path so a
    subsequent ``--undo`` can reverse the change.
    """
    result = MoveResult()
    manifest_entries: list[dict] = []
    roms_root = Path(config.roms_dir)

    for item in items:
        if not item.suggested_systems:
            result.skipped.append((item.path, "no suggested system"))
            continue
        target_system = item.suggested_systems[0]
        target_dir = roms_root / target_system
        target_path = target_dir / item.path.name
        if target_path.exists():
            result.skipped.append((item.path, f"target exists: {target_path}"))
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.path), str(target_path))
        except OSError as e:
            result.skipped.append((item.path, f"move failed: {e}"))
            continue
        result.moved.append((item.path, target_path))
        manifest_entries.append({
            "src": str(item.path),
            "dest": str(target_path),
            "from_system": item.current_system,
            "to_system": target_system,
        })

    if not manifest_entries:
        return result, None

    out_dir = manifest_dir or roms_root
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = out_dir / f"{MANIFEST_PREFIX}{stamp}.json"
    manifest_path.write_text(
        json.dumps(
            {"timestamp": stamp, "moves": manifest_entries},
            indent=2,
        ),
        encoding="utf-8",
    )
    return result, manifest_path


def undo_moves(manifest_path: Path) -> dict:
    """Reverse the moves described by *manifest_path*. Returns a summary."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = {"reverted": 0, "errors": []}
    for entry in reversed(data.get("moves", [])):
        src = Path(entry["src"])
        dest = Path(entry["dest"])
        try:
            if not dest.exists():
                summary["errors"].append(f"missing during undo: {dest}")
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(src))
            summary["reverted"] += 1
        except OSError as e:
            summary["errors"].append(f"could not revert {dest} → {src}: {e}")
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return summary


def find_latest_misplaced_manifest(roms_dir: Path) -> Optional[Path]:
    if not roms_dir.exists():
        return None
    manifests = sorted(roms_dir.glob(f"{MANIFEST_PREFIX}*.json"))
    return manifests[-1] if manifests else None
