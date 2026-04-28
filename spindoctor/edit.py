"""Batch metadata editing and atomic game rename / clone.

Two related features that share infrastructure:

* **Batch edit** — set / clear / append / prepend metadata fields (genre,
  year, manufacturer, rating, description) across many games in one shot
  with simple filters.  Replaces the most painful HyperHQ workflow.
* **Rename / clone** — change a game's identity in one atomic operation
  that updates the ROM file, the database ``<game>`` entry, every media
  slot (wheel/snap/video/theme/...) and any RocketLauncher per-game files.
  ``clone`` is the same plan but copies instead of renaming, so users can
  stand up a hack/translation alongside the original.

Both produce a JSON manifest under ``~/.spindoctor/`` (``edits/`` or
``renames/``) so the action can be reversed with one command, mirroring
:mod:`spindoctor.misplaced` and :mod:`spindoctor.curate`.
"""
from __future__ import annotations

import fnmatch
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import CONFIG_DIR, Config
from .database import GameEntry, load_database
from .media import MEDIA_DIR_MAP, MEDIA_EXTENSIONS


EDIT_DIR = CONFIG_DIR / "edits"
RENAME_DIR = CONFIG_DIR / "renames"
EDIT_MANIFEST_PREFIX = "edit-"
RENAME_MANIFEST_PREFIX = "rename-"

# Editable metadata fields. ``GameEntry`` does not currently model
# ``players``; we accept it here so the CLI surface matches the spec but
# ignore it during apply if absent. Description doubles as the display
# name field used by HyperSpin wheels.
EDITABLE_FIELDS: tuple[str, ...] = (
    "description",
    "genre",
    "year",
    "manufacturer",
    "rating",
    "players",
)

# Search-by-image, snap, video, theme — same set audit.check_media looks at.
ALL_MEDIA_TYPES: tuple[str, ...] = tuple(MEDIA_DIR_MAP.keys())

# Image / video / sound extension probes used when a slot's stored
# extension differs from the canonical one in MEDIA_EXTENSIONS.
_PROBE_EXTS: dict[str, tuple[str, ...]] = {
    "wheel":      (".png", ".jpg", ".jpeg"),
    "background": (".jpg", ".jpeg", ".png"),
    "artwork":    (".png", ".jpg", ".jpeg"),
    "title":      (".png", ".jpg", ".jpeg"),
    "snap":       (".png", ".jpg", ".jpeg"),
    "fade":       (".png", ".jpg", ".jpeg"),
    "video":      (".mp4", ".avi", ".flv", ".mkv"),
    "trailer":    (".mp4", ".avi", ".flv", ".mkv"),
    "sound":      (".mp3", ".wav", ".ogg"),
    "theme":      (".zip", ".swf"),
}


# ─── batch edit dataclasses ───────────────────────────────────────────────────


@dataclass
class EditFilter:
    """Filter criteria for selecting games out of one system's database."""
    system: str
    name_pattern: Optional[str] = None
    genre: Optional[str] = None
    year_range: Optional[tuple[int, int]] = None
    manufacturer: Optional[str] = None
    missing_field: Optional[str] = None


@dataclass
class EditChange:
    """One mutation applied to a metadata field."""
    field: str
    value: str = ""
    mode: str = "set"  # set | clear | append | prepend

    def __post_init__(self) -> None:
        if self.mode not in ("set", "clear", "append", "prepend"):
            raise ValueError(
                f"EditChange.mode must be set/clear/append/prepend, got {self.mode!r}"
            )
        if self.field not in EDITABLE_FIELDS:
            raise ValueError(
                f"EditChange.field must be one of {EDITABLE_FIELDS}, got {self.field!r}"
            )


@dataclass
class EditResult:
    """Outcome of editing a single game."""
    game_name: str
    field_changes: dict[str, tuple[str, str]] = field(default_factory=dict)
    skipped: bool = False
    reason: str = ""


# ─── filter helpers ───────────────────────────────────────────────────────────


def _year_int(value: str) -> Optional[int]:
    """Pull a 4-digit year out of a string like "1986" or "(c) 1986"."""
    if not value:
        return None
    m = re.search(r"(19|20)\d{2}", value)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def parse_year_range(spec: str) -> tuple[int, int]:
    """Parse "1980-1989", "1986", "1980-" or "-1989" into an inclusive range."""
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("year range is empty")
    if "-" in spec:
        lo_s, _, hi_s = spec.partition("-")
        lo_s, hi_s = lo_s.strip(), hi_s.strip()
        lo = int(lo_s) if lo_s else 0
        hi = int(hi_s) if hi_s else 9999
    else:
        lo = hi = int(spec)
    if lo > hi:
        raise ValueError(f"year range inverted: {spec}")
    return (lo, hi)


def parse_filter_clause(clause: str) -> tuple[str, str]:
    """Split a ``key=value`` filter clause; raises on malformed input."""
    if "=" not in clause:
        raise ValueError(f"filter must be key=value, got {clause!r}")
    key, _, value = clause.partition("=")
    key = key.strip().lower()
    value = value.strip()
    if not key:
        raise ValueError(f"filter has empty key: {clause!r}")
    return key, value


def build_filter(system: str, clauses: Iterable[str]) -> EditFilter:
    """Translate ``--filter k=v`` strings into an :class:`EditFilter`."""
    f = EditFilter(system=system)
    for clause in clauses:
        key, value = parse_filter_clause(clause)
        if key == "name":
            f.name_pattern = value
        elif key == "genre":
            f.genre = value
        elif key == "manufacturer":
            f.manufacturer = value
        elif key == "year":
            f.year_range = parse_year_range(value)
        elif key == "missing":
            field_name = value.lower()
            if field_name not in EDITABLE_FIELDS:
                raise ValueError(
                    f"--filter missing={value!r} not in {EDITABLE_FIELDS}"
                )
            f.missing_field = field_name
        else:
            raise ValueError(
                f"unknown filter key {key!r}; "
                f"expected one of name/genre/manufacturer/year/missing"
            )
    return f


def _matches(filters: EditFilter, game: GameEntry) -> bool:
    if filters.name_pattern:
        pat = filters.name_pattern
        target = (game.description or game.name)
        if not (
            fnmatch.fnmatchcase(game.name, pat)
            or fnmatch.fnmatchcase(target, pat)
            or fnmatch.fnmatchcase(game.name.lower(), pat.lower())
            or fnmatch.fnmatchcase(target.lower(), pat.lower())
        ):
            return False
    if filters.genre and (game.genre or "").strip().lower() != filters.genre.lower():
        return False
    if filters.manufacturer and (
        filters.manufacturer.lower() not in (game.manufacturer or "").lower()
    ):
        return False
    if filters.year_range:
        y = _year_int(game.year)
        lo, hi = filters.year_range
        if y is None or y < lo or y > hi:
            return False
    if filters.missing_field:
        current = getattr(game, filters.missing_field, "") or ""
        if current.strip():
            return False
    return True


def find_matching_games(config: Config, filters: EditFilter) -> list[GameEntry]:
    """Return every game in *filters.system* matching all clauses."""
    db = load_database(filters.system, config.databases_dir)
    return [g for g in db.games().values() if _matches(filters, g)]


# ─── batch edit apply / undo ──────────────────────────────────────────────────


def _current_value(game: GameEntry, field_name: str) -> str:
    return getattr(game, field_name, "") or ""


def _apply_change(current: str, change: EditChange) -> str:
    if change.mode == "set":
        return change.value
    if change.mode == "clear":
        return ""
    if change.mode == "append":
        if not current:
            return change.value
        sep = "" if current.endswith((" ", ",")) else " "
        return f"{current}{sep}{change.value}"
    if change.mode == "prepend":
        if not current:
            return change.value
        return f"{change.value} {current}"
    return current  # unreachable — guarded in __post_init__


def plan_batch_edit(
    games: list[GameEntry],
    changes: list[EditChange],
) -> dict[str, dict[str, tuple[str, str]]]:
    """Compute per-game, per-field ``(before, after)`` for *games*.

    Pure function — does not mutate the games or touch disk.  Skips fields
    not present on :class:`GameEntry` (e.g. ``players``) so an upcoming
    schema extension can use the same plan code.
    """
    plan: dict[str, dict[str, tuple[str, str]]] = {}
    for game in games:
        per_game: dict[str, tuple[str, str]] = {}
        for change in changes:
            if not hasattr(game, change.field):
                continue
            before = _current_value(game, change.field)
            after = _apply_change(before, change)
            if before == after:
                continue
            per_game[change.field] = (before, after)
        if per_game:
            plan[game.name] = per_game
    return plan


def apply_batch_edit(
    config: Config,
    system: str,
    games: list[GameEntry],
    changes: list[EditChange],
    output_dir: Optional[Path] = None,
    manifest_dir: Optional[Path] = None,
) -> tuple[list[EditResult], Optional[Path]]:
    """Apply *changes* to each of *games* and persist the database.

    Writes a single ``.bak`` (the database's own ``save`` mechanism) and a
    JSON manifest under ``~/.spindoctor/edits/`` recording each game's
    before-snapshot so :func:`undo_batch_edit` can restore them.
    """
    if not games or not changes:
        return [], None

    db = load_database(system, config.databases_dir)
    plan = plan_batch_edit(games, changes)

    results: list[EditResult] = []
    manifest_entries: list[dict] = []
    for game in games:
        per_game = plan.get(game.name)
        if not per_game:
            results.append(EditResult(
                game_name=game.name, skipped=True, reason="no field changes",
            ))
            continue
        live = db.get(game.name)
        if live is None:
            results.append(EditResult(
                game_name=game.name, skipped=True, reason="missing in database",
            ))
            continue

        before_snapshot = {
            f: getattr(live, f, "") or ""
            for f in EDITABLE_FIELDS if hasattr(live, f)
        }

        for field_name, (_before, after) in per_game.items():
            setattr(live, field_name, after)
        db.update_game(live)

        results.append(EditResult(
            game_name=game.name,
            field_changes=per_game,
        ))
        manifest_entries.append({
            "game": game.name,
            "before": before_snapshot,
            "changes": {k: list(v) for k, v in per_game.items()},
        })

    if not manifest_entries:
        return results, None

    out_root = config.effective_output_dir(str(output_dir) if output_dir else None)
    if out_root is not None:
        target = out_root / "Databases" / system / f"{system}.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        db.save(output_path=target)
    else:
        db.save()

    out_dir = manifest_dir or EDIT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = out_dir / f"{EDIT_MANIFEST_PREFIX}{stamp}.json"
    manifest_path.write_text(
        json.dumps(
            {
                "timestamp": stamp,
                "system": system,
                "changes": [
                    {"field": c.field, "value": c.value, "mode": c.mode}
                    for c in changes
                ],
                "games": manifest_entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return results, manifest_path


def undo_batch_edit(
    manifest_path: Path,
    config: Config,
) -> list[EditResult]:
    """Restore each game's metadata from the before-snapshot in *manifest*."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    system = data.get("system", "")
    if not system:
        raise ValueError(f"manifest missing 'system': {manifest_path}")

    db = load_database(system, config.databases_dir)
    results: list[EditResult] = []
    for entry in data.get("games", []):
        name = entry.get("game", "")
        before = entry.get("before") or {}
        live = db.get(name)
        if live is None:
            results.append(EditResult(
                game_name=name, skipped=True, reason="missing in database",
            ))
            continue
        reverted: dict[str, tuple[str, str]] = {}
        for field_name, prior in before.items():
            if not hasattr(live, field_name):
                continue
            current = getattr(live, field_name, "") or ""
            if current == prior:
                continue
            reverted[field_name] = (current, prior)
            setattr(live, field_name, prior)
        if reverted:
            db.update_game(live)
            results.append(EditResult(game_name=name, field_changes=reverted))
        else:
            results.append(EditResult(
                game_name=name, skipped=True, reason="no changes to revert",
            ))

    db.save()
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return results


# ─── manifest helpers ─────────────────────────────────────────────────────────


def list_edit_manifests() -> list[Path]:
    if not EDIT_DIR.exists():
        return []
    return sorted(EDIT_DIR.glob(f"{EDIT_MANIFEST_PREFIX}*.json"))


def list_rename_manifests() -> list[Path]:
    if not RENAME_DIR.exists():
        return []
    return sorted(RENAME_DIR.glob(f"{RENAME_MANIFEST_PREFIX}*.json"))


def find_latest_edit_manifest() -> Optional[Path]:
    manifests = list_edit_manifests()
    return manifests[-1] if manifests else None


def find_latest_rename_manifest() -> Optional[Path]:
    manifests = list_rename_manifests()
    return manifests[-1] if manifests else None


def edit_manifest_summary(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"timestamp": "", "system": "", "games": 0, "changes": 0}
    return {
        "timestamp": data.get("timestamp", ""),
        "system": data.get("system", ""),
        "games": len(data.get("games", [])),
        "changes": len(data.get("changes", [])),
    }


def rename_manifest_summary(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"timestamp": "", "system": "", "old": "", "new": "", "moves": 0, "clone": False}
    return {
        "timestamp": data.get("timestamp", ""),
        "system": data.get("system", ""),
        "old": data.get("old_name", ""),
        "new": data.get("new_name", ""),
        "moves": len(data.get("moves", [])),
        "clone": bool(data.get("clone")),
    }


# ─── rename / clone ───────────────────────────────────────────────────────────


@dataclass
class RenameOperation:
    """High-level user intent for a rename or clone."""
    system: str
    old_rom_name: str
    new_rom_name: str
    old_display_name: str = ""
    new_display_name: str = ""
    keep_original: bool = False  # True → clone instead of rename


@dataclass
class FileChange:
    """One concrete file move/copy or DB edit produced by a rename plan."""
    kind: str  # rom | media | db | rl-pclauncher
    src: Optional[Path]
    dest: Optional[Path]
    media_type: str = ""
    note: str = ""


@dataclass
class RenamePlan:
    """The full set of changes a rename or clone would make."""
    op: RenameOperation
    file_changes: list[FileChange] = field(default_factory=list)

    @property
    def is_clone(self) -> bool:
        return self.op.keep_original


def _scan_media_for_game(
    media_base: Path,
    system: str,
    game_name: str,
) -> list[tuple[str, Path]]:
    """Walk every known media slot and return ``(media_type, path)`` for hits."""
    sys_dir = media_base / system
    if not sys_dir.exists():
        return []
    found: list[tuple[str, Path]] = []
    for media_type, segments in MEDIA_DIR_MAP.items():
        slot_dir = sys_dir / Path(*segments)
        if not slot_dir.exists():
            continue
        for ext in _PROBE_EXTS.get(media_type, (MEDIA_EXTENSIONS.get(media_type, ""),)):
            candidate = slot_dir / f"{game_name}{ext}"
            if candidate.exists():
                found.append((media_type, candidate))
        # Themes can be folders too
        if media_type == "theme":
            theme_folder = slot_dir / game_name
            if theme_folder.is_dir():
                found.append(("theme", theme_folder))
    return found


def _pclauncher_ini_for(
    rl_dir: Optional[Path],
    system: str,
    game_name: str,
) -> Optional[Path]:
    if not rl_dir:
        return None
    candidate = rl_dir / "Modules" / "PCLauncher" / system / f"{game_name}.ini"
    return candidate if candidate.exists() else None


def plan_rename(
    config: Config,
    system: str,
    old_name: str,
    new_name: str,
    *,
    clone: bool = False,
    new_display_name: str = "",
) -> RenamePlan:
    """Build a :class:`RenamePlan` enumerating every file move / DB edit.

    Pure read-only — this is what ``--dry-run`` shows the user.  ``apply``
    consumes the plan to actually do the work.
    """
    if not old_name or not new_name:
        raise ValueError("old_name and new_name are both required")
    if old_name == new_name:
        raise ValueError("old_name and new_name are identical")

    db = load_database(system, config.databases_dir)
    existing = db.get(old_name)
    if existing is None:
        raise ValueError(f"{old_name!r} not in {system} database")
    if db.get(new_name) is not None:
        raise ValueError(f"target name already exists in DB: {new_name!r}")

    op = RenameOperation(
        system=system,
        old_rom_name=old_name,
        new_rom_name=new_name,
        old_display_name=existing.description or "",
        new_display_name=new_display_name or "",
        keep_original=clone,
    )
    changes: list[FileChange] = []

    # 1) ROM file (or per-game folder).
    roms_root = Path(config.roms_dir) / system
    rom_candidates = list(roms_root.glob(f"{old_name}.*")) if roms_root.exists() else []
    rom_folder = roms_root / old_name if (roms_root / old_name).is_dir() else None

    for rom_path in rom_candidates:
        if rom_path.is_file():
            target = roms_root / f"{new_name}{rom_path.suffix}"
            changes.append(FileChange(
                kind="rom",
                src=rom_path,
                dest=target,
                note="copy" if clone else "move",
            ))
    if rom_folder is not None:
        target = roms_root / new_name
        changes.append(FileChange(
            kind="rom",
            src=rom_folder,
            dest=target,
            note="copytree" if clone else "move",
        ))

    # 2) DB entry.
    changes.append(FileChange(
        kind="db",
        src=None,
        dest=None,
        note=f"clone {old_name!r} -> {new_name!r}" if clone
             else f"rename {old_name!r} -> {new_name!r}",
    ))

    # 3) Media files.
    if config.hyperspin_dir:
        for media_type, src in _scan_media_for_game(
            config.media_dir, system, old_name
        ):
            dest = src.parent / (new_name + ("" if src.is_dir() else src.suffix))
            changes.append(FileChange(
                kind="media",
                src=src,
                dest=dest,
                media_type=media_type,
                note="copy" if clone else "move",
            ))

    # 4) RocketLauncher PCLauncher INI.
    rl_dir = Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None
    ini = _pclauncher_ini_for(rl_dir, system, old_name)
    if ini is not None and rl_dir is not None:
        target = ini.parent / f"{new_name}.ini"
        changes.append(FileChange(
            kind="rl-pclauncher",
            src=ini,
            dest=target,
            note="copy" if clone else "move",
        ))

    return RenamePlan(op=op, file_changes=changes)


def _move_or_copy(src: Path, dest: Path, *, clone: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if clone:
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
    else:
        shutil.move(str(src), str(dest))


def apply_rename(
    plan: RenamePlan,
    config: Config,
    output_dir: Optional[Path] = None,
    manifest_dir: Optional[Path] = None,
) -> tuple[list[FileChange], Optional[Path]]:
    """Execute *plan*: file moves/copies then DB edit, then write manifest."""
    op = plan.op
    clone = op.keep_original
    applied: list[FileChange] = []
    manifest_moves: list[dict] = []

    # 1) Pre-flight: refuse to overwrite anything.
    for ch in plan.file_changes:
        if ch.dest is not None and ch.dest.exists():
            raise FileExistsError(
                f"refusing to overwrite existing target: {ch.dest}"
            )

    # 2) Files first, DB last — that way the DB edit reflects what's on disk.
    db_change: Optional[FileChange] = None
    for ch in plan.file_changes:
        if ch.kind == "db":
            db_change = ch
            continue
        assert ch.src is not None and ch.dest is not None
        _move_or_copy(ch.src, ch.dest, clone=clone)
        applied.append(ch)
        manifest_moves.append({
            "kind": ch.kind,
            "src": str(ch.src),
            "dest": str(ch.dest),
            "media_type": ch.media_type,
            "clone": clone,
        })

    # 3) DB edit.
    db = load_database(op.system, config.databases_dir)
    existing = db.get(op.old_rom_name)
    if existing is None:
        raise RuntimeError(
            f"database changed under us: {op.old_rom_name!r} no longer present"
        )

    if clone:
        new_entry = GameEntry(
            name=op.new_rom_name,
            description=op.new_display_name or existing.description or op.new_rom_name,
            cloneof=existing.cloneof,
            crc=existing.crc,
            manufacturer=existing.manufacturer,
            year=existing.year,
            genre=existing.genre,
            rating=existing.rating,
            enabled=existing.enabled or "Yes",
        )
        db.add_game(new_entry)
    else:
        # Rebuild the entry under the new key, then drop the old one.
        renamed = GameEntry(
            name=op.new_rom_name,
            description=op.new_display_name or existing.description or op.new_rom_name,
            cloneof=existing.cloneof,
            crc=existing.crc,
            manufacturer=existing.manufacturer,
            year=existing.year,
            genre=existing.genre,
            rating=existing.rating,
            enabled=existing.enabled or "Yes",
        )
        db.remove_game(op.old_rom_name)
        db.add_game(renamed)

    out_root = config.effective_output_dir(str(output_dir) if output_dir else None)
    if out_root is not None:
        target = out_root / "Databases" / op.system / f"{op.system}.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        db.save(output_path=target)
    else:
        db.save()

    if db_change is not None:
        applied.append(db_change)

    # 4) Manifest.
    out_dir = manifest_dir or RENAME_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = out_dir / f"{RENAME_MANIFEST_PREFIX}{stamp}.json"
    manifest_path.write_text(
        json.dumps(
            {
                "timestamp": stamp,
                "system": op.system,
                "old_name": op.old_rom_name,
                "new_name": op.new_rom_name,
                "old_display_name": op.old_display_name,
                "new_display_name": op.new_display_name,
                "clone": clone,
                "moves": manifest_moves,
                "db_before": asdict(existing),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return applied, manifest_path


def undo_rename(
    manifest_path: Path,
    config: Config,
) -> list[FileChange]:
    """Reverse a rename or clone described by *manifest_path*."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    system = data.get("system", "")
    old_name = data.get("old_name", "")
    new_name = data.get("new_name", "")
    is_clone = bool(data.get("clone"))

    reversed_changes: list[FileChange] = []

    # Reverse file moves last-first so we mirror the apply order.
    for entry in reversed(data.get("moves", [])):
        src = Path(entry["src"])
        dest = Path(entry["dest"])
        if not dest.exists():
            reversed_changes.append(FileChange(
                kind=entry.get("kind", ""),
                src=src, dest=dest,
                note="missing during undo",
            ))
            continue
        if is_clone:
            # The clone copied — undo by deleting the copies.
            try:
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
                reversed_changes.append(FileChange(
                    kind=entry.get("kind", ""),
                    src=src, dest=dest,
                    note="deleted clone copy",
                ))
            except OSError as e:
                reversed_changes.append(FileChange(
                    kind=entry.get("kind", ""),
                    src=src, dest=dest,
                    note=f"could not remove clone copy: {e}",
                ))
        else:
            # Rename — move dest back to src.
            src.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(dest), str(src))
                reversed_changes.append(FileChange(
                    kind=entry.get("kind", ""),
                    src=dest, dest=src,
                    note="restored",
                ))
            except OSError as e:
                reversed_changes.append(FileChange(
                    kind=entry.get("kind", ""),
                    src=dest, dest=src,
                    note=f"restore failed: {e}",
                ))

    # DB undo.
    db = load_database(system, config.databases_dir)
    if is_clone:
        db.remove_game(new_name)
    else:
        # Drop the new entry; restore the old one from the snapshot.
        db.remove_game(new_name)
        before = data.get("db_before") or {}
        if before:
            restored = GameEntry(**{
                k: v for k, v in before.items()
                if k in GameEntry.__dataclass_fields__
            })
            db.add_game(restored)
    db.save()

    reversed_changes.append(FileChange(
        kind="db", src=None, dest=None,
        note=f"reverted DB {new_name!r} -> {old_name!r}",
    ))

    try:
        manifest_path.unlink()
    except OSError:
        pass
    return reversed_changes


# ─── CSV report ───────────────────────────────────────────────────────────────


def write_edit_report(
    games: list[GameEntry],
    changes: list[EditChange],
    out_path: Path,
) -> Path:
    """Write a CSV preview: one row per (game, field) that would change."""
    import csv

    plan = plan_batch_edit(games, changes)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["game", "field", "before", "after"])
        for game_name, fields in plan.items():
            for field_name, (before, after) in fields.items():
                writer.writerow([game_name, field_name, before, after])
    return out_path
