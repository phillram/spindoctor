"""Migrate a SpinDoctor library to a new drive.

Move (or copy) any combination of the library's top-level directories — ROMs,
HyperSpin (databases + media), Emulators, RocketLauncher, LEDBlinky — to a new
location, optionally filtered to specific systems.

Workflow mirrors :mod:`spindoctor.organize`: build a plan, show it, optionally
apply it. Every applied migration writes a JSON manifest under
``~/.spindoctor/migrations/`` that ``--undo`` can reverse.

Components map to config-field paths:

    roms           → roms_dir
    hyperspin      → hyperspin_dir          (Databases + Media live inside)
    emulators      → emulators_dir
    rocketlauncher → rocketlauncher_dir
    ledblinky      → ledblinky_dir

Aliases (``games`` → roms, ``media``/``data``/``databases`` → hyperspin) are
accepted on the command line for convenience.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from ._utils import format_bytes, free_bytes  # noqa: F401 — re-export
from .config import CONFIG_DIR, Config, load_config, save_config
from .fileinfo import _dir_size


COMPONENT_TO_CONFIG_KEY: dict[str, str] = {
    "roms": "roms_dir",
    "hyperspin": "hyperspin_dir",
    "emulators": "emulators_dir",
    "rocketlauncher": "rocketlauncher_dir",
    "ledblinky": "ledblinky_dir",
}

# User-facing aliases. Map straight to a canonical component name.
COMPONENT_ALIASES: dict[str, str] = {
    "games": "roms",
    "rom": "roms",
    "media": "hyperspin",
    "data": "hyperspin",
    "databases": "hyperspin",
    "hs": "hyperspin",
    "rl": "rocketlauncher",
    "led": "ledblinky",
    "emulator": "emulators",
    "emu": "emulators",
}

# Default subfolder name to create under the target root for each component.
# "Games" rather than "ROMs" because the same folder also holds non-ROM
# titles (PC games, Steam shortcuts, multi-disc folders, etc.).
COMPONENT_SUBFOLDER: dict[str, str] = {
    "roms": "Games",
    "hyperspin": "HyperSpin",
    "emulators": "Emulators",
    "rocketlauncher": "RocketLauncher",
    "ledblinky": "LEDBlinky",
}

ALL_COMPONENTS = tuple(COMPONENT_TO_CONFIG_KEY.keys())

MIGRATIONS_DIR = CONFIG_DIR / "migrations"
MANIFEST_PREFIX = "migrate-"


# ─── data classes ─────────────────────────────────────────────────────────────


@dataclass
class MigrateMove:
    component: str
    src: str
    dest: str
    config_key: str = ""  # set when this move triggers a config field update
    size_bytes: int = 0


@dataclass
class MigrationPlan:
    target_root: str
    moves: list[MigrateMove] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    config_updates: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.moves

    @property
    def total_bytes(self) -> int:
        return sum(m.size_bytes for m in self.moves)


# ─── component / system resolution ────────────────────────────────────────────


def normalize_components(values: Iterable[str]) -> list[str]:
    """Resolve user-supplied component names (with aliases) to canonical names.

    Accepts ``"all"`` to expand to every component. Raises ``ValueError`` on
    unknown names.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        token = (raw or "").strip().lower()
        if not token:
            continue
        if token == "all":
            for c in ALL_COMPONENTS:
                if c not in seen:
                    out.append(c)
                    seen.add(c)
            continue
        canonical = COMPONENT_ALIASES.get(token, token)
        if canonical not in COMPONENT_TO_CONFIG_KEY:
            raise ValueError(
                f"Unknown component '{raw}'. Valid: "
                f"{', '.join(ALL_COMPONENTS)}, all"
            )
        if canonical not in seen:
            out.append(canonical)
            seen.add(canonical)
    return out


def _resolve_subfolder(component: str, src: Path, preserve_names: bool) -> str:
    """Return the subfolder name to use under the target root for *component*."""
    if preserve_names:
        # Use the original top-level folder name. Fall back to the standardized
        # name when the source path is the filesystem root or otherwise has no
        # usable basename.
        name = src.name
        if name:
            return name
    return COMPONENT_SUBFOLDER[component]




# ─── planning ─────────────────────────────────────────────────────────────────


def plan_migration(
    config: Config,
    target_root: Path,
    components: list[str],
    systems_filter: Optional[list[str]] = None,
    preserve_names: bool = False,
) -> MigrationPlan:
    """Build a plan to move *components* from *config* paths to *target_root*.

    ``systems_filter`` only applies to the ``roms`` component: when set, only
    those system subdirectories are moved (the ``roms_dir`` config is left
    pointing at the original location since the library is being split).

    ``preserve_names`` keeps each component's original top-level folder name
    (e.g. ``D:\\MyArcade\\HS`` lands at ``<target>/HS``). Default behaviour
    standardizes the subfolder names (``Games``, ``HyperSpin``, ``Emulators``,
    ``RocketLauncher``, ``LEDBlinky``).
    """
    plan = MigrationPlan(target_root=str(target_root))

    if not components:
        plan.notes.append("No components selected.")
        return plan

    target_root.mkdir(parents=True, exist_ok=True)

    chosen_subfolders: dict[str, str] = {}  # tracks collisions in preserve mode

    for component in components:
        config_key = COMPONENT_TO_CONFIG_KEY[component]
        src_str = getattr(config, config_key, "") or ""
        if not src_str:
            plan.skipped.append(f"{component}: not configured ({config_key} is empty)")
            continue

        src = Path(src_str)
        if not src.exists():
            plan.skipped.append(f"{component}: source does not exist ({src})")
            continue

        sub = _resolve_subfolder(component, src, preserve_names)
        # Two components landing at the same target subfolder is a hard error
        # (only really possible in --preserve-names mode with weird configs).
        clash = next((c for c, s in chosen_subfolders.items() if s == sub), None)
        if clash:
            plan.skipped.append(
                f"{component}: target subfolder '{sub}' would collide with "
                f"'{clash}' — rename one of the source folders or drop "
                f"--preserve-names"
            )
            continue
        chosen_subfolders[component] = sub

        component_target = target_root / sub

        if component == "roms" and systems_filter:
            _plan_roms_per_system(plan, src, component_target, systems_filter)
            continue

        if component_target.exists() and any(component_target.iterdir()):
            plan.skipped.append(
                f"{component}: target {component_target} already exists and is "
                f"non-empty"
            )
            continue

        if src.resolve() == component_target.resolve():
            plan.skipped.append(f"{component}: already at {component_target}")
            continue

        plan.moves.append(
            MigrateMove(
                component=component,
                src=str(src),
                dest=str(component_target),
                config_key=config_key,
                size_bytes=_dir_size(src),
            )
        )
        plan.config_updates[config_key] = str(component_target)

    return plan


def _plan_roms_per_system(
    plan: MigrationPlan,
    roms_dir: Path,
    component_target: Path,
    systems_filter: list[str],
) -> None:
    requested = {s.strip() for s in systems_filter if s.strip()}
    for system in sorted(requested):
        sys_src = roms_dir / system
        if not sys_src.exists() or not sys_src.is_dir():
            plan.skipped.append(f"roms: system '{system}' not found under {roms_dir}")
            continue
        sys_dest = component_target / system
        if sys_dest.exists() and any(sys_dest.iterdir()):
            plan.skipped.append(
                f"roms: target {sys_dest} already exists and is non-empty"
            )
            continue
        plan.moves.append(
            MigrateMove(
                component="roms",
                src=str(sys_src),
                dest=str(sys_dest),
                config_key="",  # split mode — don't touch roms_dir
                size_bytes=_dir_size(sys_src),
            )
        )
    plan.notes.append(
        "ROMs: moving individual systems — roms_dir config is unchanged. "
        "Symlink the moved folders back under the original roms_dir if you "
        "want SpinDoctor to keep finding them in one place."
    )


# ─── apply ────────────────────────────────────────────────────────────────────


def _sha1(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _verify_tree(src: Path, dest: Path) -> list[str]:
    """SHA1-compare every file under *dest* against the matching file under
    *src*. Returns a list of mismatches (empty == all good).

    Note: only invoked in ``--keep-source`` flows where *src* still exists.
    """
    errors: list[str] = []
    if dest.is_file():
        try:
            if _sha1(src) != _sha1(dest):
                errors.append(f"hash mismatch: {dest}")
        except OSError as e:
            errors.append(f"could not hash {dest}: {e}")
        return errors
    for d_file in dest.rglob("*"):
        if not d_file.is_file():
            continue
        rel = d_file.relative_to(dest)
        s_file = src / rel
        if not s_file.exists():
            errors.append(f"missing in source: {rel}")
            continue
        try:
            if _sha1(s_file) != _sha1(d_file):
                errors.append(f"hash mismatch: {rel}")
        except OSError as e:
            errors.append(f"could not hash {rel}: {e}")
    return errors


def apply_migration(
    plan: MigrationPlan,
    *,
    keep_source: bool = False,
    verify: bool = False,
    update_config: bool = True,
    progress_cb=None,
) -> Path:
    """Execute *plan* and write a manifest. Returns the manifest path.

    ``keep_source`` performs a copy (rather than move) and leaves the original
    in place. ``verify`` SHA1-checks every file post-copy (only meaningful with
    ``keep_source=True``; a regular move deletes the source as it goes).

    ``progress_cb`` is invoked as ``progress_cb(move, status)`` with ``status``
    in ``{"start", "done"}``. May be ``None``.
    """
    if plan.empty:
        return _write_manifest(plan, applied=[], config_before={},
                               keep_source=keep_source)

    # Snapshot config so undo can restore exact prior values.
    cfg_before = load_config().to_dict()

    applied: list[MigrateMove] = []
    for move in plan.moves:
        if progress_cb:
            progress_cb(move, "start")

        src = Path(move.src)
        dest = Path(move.dest)
        if dest.exists():
            if dest.is_dir() and not any(dest.iterdir()):
                dest.rmdir()
            else:
                raise FileExistsError(f"Destination already exists: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)

        if keep_source:
            if src.is_dir():
                shutil.copytree(str(src), str(dest))
            else:
                shutil.copy2(str(src), str(dest))
            if verify:
                errors = _verify_tree(src, dest)
                if errors:
                    raise RuntimeError(
                        f"Verification failed for {move.component}: "
                        f"{len(errors)} file(s) differ. First: {errors[0]}"
                    )
        else:
            shutil.move(str(src), str(dest))

        applied.append(move)
        if progress_cb:
            progress_cb(move, "done")

    if update_config and not keep_source and plan.config_updates:
        cfg = load_config()
        for key, new_path in plan.config_updates.items():
            setattr(cfg, key, new_path)
        save_config(cfg)

    return _write_manifest(plan, applied, cfg_before, keep_source)


# ─── undo ─────────────────────────────────────────────────────────────────────


def undo_migration(manifest_path: Path) -> dict:
    """Reverse the migration described by *manifest_path*.

    For move-mode migrations: moves each dest back to src and restores the
    pre-migration config snapshot. For keep-source migrations: deletes each
    destination tree (the source was never touched).
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    moves = [MigrateMove(**m) for m in data.get("moves", [])]
    keep_source = bool(data.get("keep_source", False))
    cfg_before = data.get("config_before") or {}

    summary = {
        "moves_reverted": 0,
        "destinations_removed": 0,
        "errors": [],
        "config_restored": False,
    }

    if keep_source:
        # Just remove the copied destinations.
        for move in reversed(moves):
            dest = Path(move.dest)
            try:
                if dest.is_dir():
                    shutil.rmtree(dest)
                    summary["destinations_removed"] += 1
                elif dest.exists():
                    dest.unlink()
                    summary["destinations_removed"] += 1
            except OSError as e:
                summary["errors"].append(f"Could not remove {dest}: {e}")
    else:
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

        # Restore config snapshot if we have one.
        if cfg_before:
            try:
                save_config(Config.from_dict(cfg_before))
                summary["config_restored"] = True
            except (TypeError, ValueError) as e:
                summary["errors"].append(f"Could not restore config: {e}")

    try:
        manifest_path.unlink()
    except OSError:
        pass

    return summary


# ─── manifest helpers ─────────────────────────────────────────────────────────


def _write_manifest(
    plan: MigrationPlan,
    applied: list[MigrateMove],
    config_before: dict,
    keep_source: bool,
) -> Path:
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = MIGRATIONS_DIR / f"{MANIFEST_PREFIX}{stamp}.json"
    payload = {
        "timestamp": stamp,
        "target_root": plan.target_root,
        "keep_source": keep_source,
        "moves": [asdict(m) for m in applied],
        "config_before": config_before,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def list_manifests() -> list[Path]:
    """Return migration manifests sorted oldest→newest."""
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob(f"{MANIFEST_PREFIX}*.json"))


def find_latest_manifest() -> Optional[Path]:
    manifests = list_manifests()
    return manifests[-1] if manifests else None


# `format_bytes` is re-exported from `spindoctor._utils` via the import
# at the top of this module — see the matching note in `backup.py`.
