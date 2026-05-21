"""Backup and restore a SpinDoctor library.

Copy any combination of the library's top-level directories — ROMs, HyperSpin
Databases, HyperSpin Media, Emulators, RocketLauncher, LEDBlinky — and the
SpinDoctor settings folder (``~/.spindoctor/``) into a dated backup directory
on a different drive. Each backup is self-describing via a ``manifest.json``
that ``restore`` can replay.

Component map:

    roms           → roms_dir                       (subfolder: Games)
    databases      → <hyperspin_dir>/Databases/     (subfolder: HyperSpin/Databases)
    media          → <hyperspin_dir>/Media/         (subfolder: HyperSpin/Media)
    emulators      → emulators_dir                  (subfolder: Emulators)
    rocketlauncher → rocketlauncher_dir             (subfolder: RocketLauncher)
    ledblinky      → ledblinky_dir                  (subfolder: LEDBlinky)
    settings       → ~/.spindoctor/                 (subfolder: Settings)

User-friendly aliases (``games``, ``hyperspin``, ``hs``, ``rl``, ``led``,
``config`` …) are accepted on the command line and resolved to canonical
component names.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .fileinfo import _dir_size

# Byte-formatting and free-space helpers live in `_utils` so they can
# be shared across backup / migrate / cleanup without three copies of
# the same 6-line loop. Re-exported here so callers like
# `from .backup import format_bytes` keep working unchanged.
from ._utils import format_bytes, free_bytes  # noqa: F401 — re-export
from .config import CONFIG_DIR, Config


BACKUP_DIR_PREFIX = "spindoctor-backup-"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1


# ─── component definitions ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ComponentSpec:
    """Describes one logical thing that can be backed up/restored.

    ``source_resolver`` returns the on-disk path the component lives at given a
    :class:`Config`. ``subfolder`` is the relative path used inside the backup
    directory (forward-slash separated; converted to a Path on use).
    """
    name: str
    subfolder: str
    description: str
    source_resolver: callable  # type: ignore[assignment]


def _resolve_databases(cfg: Config) -> str:
    return str(cfg.databases_dir) if cfg.hyperspin_dir else ""


def _resolve_media(cfg: Config) -> str:
    return str(cfg.media_dir) if cfg.hyperspin_dir else ""


def _resolve_settings(_cfg: Config) -> str:
    # Always use the canonical SpinDoctor config dir.
    return str(CONFIG_DIR)


COMPONENTS: dict[str, ComponentSpec] = {
    "roms": ComponentSpec(
        name="roms",
        subfolder="Games",
        description="ROM / game files",
        source_resolver=lambda c: c.roms_dir,
    ),
    "databases": ComponentSpec(
        name="databases",
        subfolder="HyperSpin/Databases",
        description="HyperSpin database XMLs",
        source_resolver=_resolve_databases,
    ),
    "media": ComponentSpec(
        name="media",
        subfolder="HyperSpin/Media",
        description="HyperSpin media (wheels, snaps, video, themes)",
        source_resolver=_resolve_media,
    ),
    "emulators": ComponentSpec(
        name="emulators",
        subfolder="Emulators",
        description="Emulator binaries",
        source_resolver=lambda c: c.emulators_dir,
    ),
    "rocketlauncher": ComponentSpec(
        name="rocketlauncher",
        subfolder="RocketLauncher",
        description="RocketLauncher install (settings, modules)",
        source_resolver=lambda c: c.rocketlauncher_dir,
    ),
    "ledblinky": ComponentSpec(
        name="ledblinky",
        subfolder="LEDBlinky",
        description="LEDBlinky install (controls.ini, colors.ini)",
        source_resolver=lambda c: c.ledblinky_dir,
    ),
    "settings": ComponentSpec(
        name="settings",
        subfolder="Settings",
        description="SpinDoctor config & state (~/.spindoctor/)",
        source_resolver=_resolve_settings,
    ),
}

ALL_COMPONENTS = tuple(COMPONENTS.keys())

COMPONENT_ALIASES: dict[str, list[str]] = {
    # single-target aliases
    "games": ["roms"],
    "rom": ["roms"],
    "data": ["databases"],
    "db": ["databases"],
    "databases": ["databases"],
    "emu": ["emulators"],
    "emulator": ["emulators"],
    "rl": ["rocketlauncher"],
    "led": ["ledblinky"],
    "config": ["settings"],
    # composite aliases — expand to multiple canonical components
    "hyperspin": ["databases", "media"],
    "hs": ["databases", "media"],
}


# ─── data classes ─────────────────────────────────────────────────────────────


@dataclass
class BackupItem:
    component: str
    src: str
    dest: str
    size_bytes: int = 0


@dataclass
class BackupPlan:
    backup_root: str
    items: list[BackupItem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.items

    @property
    def total_bytes(self) -> int:
        return sum(i.size_bytes for i in self.items)


@dataclass
class RestoreItem:
    component: str
    src: str          # path inside the backup
    dest: str         # path on disk to restore to
    size_bytes: int = 0


@dataclass
class RestorePlan:
    backup_root: str
    items: list[RestoreItem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.items

    @property
    def total_bytes(self) -> int:
        return sum(i.size_bytes for i in self.items)


# ─── component resolution ─────────────────────────────────────────────────────


def normalize_components(values: Iterable[str]) -> list[str]:
    """Resolve user-supplied component names (with aliases) to canonical names.

    Accepts ``"all"`` to expand to every component. Raises ``ValueError`` on
    unknown names. Order is preserved; duplicates collapsed.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(canonical: str) -> None:
        if canonical not in seen:
            out.append(canonical)
            seen.add(canonical)

    for raw in values:
        token = (raw or "").strip().lower()
        if not token:
            continue
        if token == "all":
            for c in ALL_COMPONENTS:
                _add(c)
            continue
        if token in COMPONENTS:
            _add(token)
            continue
        expanded = COMPONENT_ALIASES.get(token)
        if expanded is None:
            raise ValueError(
                f"Unknown component '{raw}'. Valid: "
                f"{', '.join(ALL_COMPONENTS)}, all, "
                f"{', '.join(sorted(COMPONENT_ALIASES))}"
            )
        for c in expanded:
            _add(c)
    return out


# `free_bytes` and `format_bytes` live in `spindoctor._utils` — see the
# import at the top of this module. They used to be defined here as
# part of three copy-paste pairs (backup / migrate / cleanup); the
# shared helper deduplicates them without churning call sites.


# ─── planning ─────────────────────────────────────────────────────────────────


def _new_backup_root(target: Path, label: Optional[str] = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"-{label}" if label else ""
    return target / f"{BACKUP_DIR_PREFIX}{stamp}{suffix}"


def plan_backup(
    config: Config,
    target: Path,
    components: list[str],
    *,
    label: Optional[str] = None,
    backup_root: Optional[Path] = None,
) -> BackupPlan:
    """Plan a backup of *components* from *config* paths into *target*.

    Returns a :class:`BackupPlan`. ``label`` (optional) is appended to the
    auto-generated backup folder name. Pass ``backup_root`` to override the
    auto-generated dated folder name entirely (used in tests).
    """
    if backup_root is None:
        backup_root = _new_backup_root(target, label)
    plan = BackupPlan(backup_root=str(backup_root))

    if not components:
        plan.notes.append("No components selected.")
        return plan

    for comp in components:
        spec = COMPONENTS.get(comp)
        if spec is None:
            plan.skipped.append(f"{comp}: unknown component")
            continue
        src_str = spec.source_resolver(config) or ""
        if not src_str:
            plan.skipped.append(
                f"{comp}: not configured ({spec.description})"
            )
            continue
        src = Path(src_str)
        if not src.exists():
            plan.skipped.append(f"{comp}: source does not exist ({src})")
            continue

        dest = backup_root / spec.subfolder
        plan.items.append(
            BackupItem(
                component=comp,
                src=str(src),
                dest=str(dest),
                size_bytes=_dir_size(src),
            )
        )

    return plan


# ─── apply backup ─────────────────────────────────────────────────────────────


def apply_backup(
    plan: BackupPlan,
    config: Config,
    *,
    progress_cb=None,
) -> Path:
    """Execute *plan*, writing manifest. Returns the backup root path."""
    backup_root = Path(plan.backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)

    completed: list[BackupItem] = []
    current_dest: Optional[Path] = None
    try:
        for item in plan.items:
            if progress_cb:
                progress_cb(item, "start")

            src = Path(item.src)
            dest = Path(item.dest)
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                # Refuse to overwrite an existing component subfolder — manifests
                # become ambiguous. Caller should choose a different target.
                raise FileExistsError(
                    f"Backup destination already exists: {dest}"
                )

            current_dest = dest
            if src.is_dir():
                shutil.copytree(str(src), str(dest))
            else:
                shutil.copy2(str(src), str(dest))
            current_dest = None

            completed.append(item)
            if progress_cb:
                progress_cb(item, "done")
    except KeyboardInterrupt:
        # Ctrl+C mid-copy leaves the in-flight component half-written.
        # Sweep it so the backup root only contains whole components.
        if current_dest is not None:
            try:
                if current_dest.is_dir():
                    shutil.rmtree(str(current_dest), ignore_errors=True)
                elif current_dest.exists():
                    current_dest.unlink()
            except OSError:
                pass
        # Persist a manifest for whatever DID complete so `list_backups`
        # can see it and `restore` can replay it. Without this the
        # finished components are invisible (list_backups filters on
        # manifest.json existing) and effectively orphaned.
        if completed:
            try:
                _write_manifest(backup_root, plan, completed, config)
            except OSError as exc:
                import sys
                print(
                    f"WARNING: backup interrupted and manifest could not be written "
                    f"({exc}). The {len(completed)} completed component(s) are in "
                    f"{backup_root} but `spindoctor backup list` will not show them "
                    "and `backup restore` cannot replay them without a manifest.",
                    file=sys.stderr,
                )
        raise

    _write_manifest(backup_root, plan, completed, config)
    return backup_root


# ─── manifest ─────────────────────────────────────────────────────────────────


def _write_manifest(
    backup_root: Path,
    plan: BackupPlan,
    completed: list[BackupItem],
    config: Config,
) -> Path:
    manifest_path = backup_root / MANIFEST_FILENAME
    payload = {
        "version": MANIFEST_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "backup_root": str(backup_root),
        "items": [asdict(i) for i in completed],
        "config_snapshot": config.to_dict(),
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return manifest_path


def read_manifest(backup_root: Path) -> dict:
    """Read the manifest from *backup_root*. Raises ``FileNotFoundError`` /
    ``ValueError`` on missing or malformed manifests."""
    manifest_path = backup_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest at {manifest_path} — not a SpinDoctor backup?"
        )
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed manifest at {manifest_path}: {e}") from e


def list_backups(target: Path) -> list[Path]:
    """List backup directories under *target*, sorted oldest→newest."""
    if not target.exists() or not target.is_dir():
        return []
    out: list[Path] = []
    for child in target.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith(BACKUP_DIR_PREFIX):
            continue
        if (child / MANIFEST_FILENAME).exists():
            out.append(child)
    return sorted(out, key=lambda p: p.name)


def find_latest_backup(target: Path) -> Optional[Path]:
    backups = list_backups(target)
    return backups[-1] if backups else None


# ─── restore ──────────────────────────────────────────────────────────────────


def plan_restore(
    backup_root: Path,
    components: Optional[list[str]] = None,
    *,
    use_current_config: Optional[Config] = None,
) -> RestorePlan:
    """Plan a restore from *backup_root*.

    ``components`` filters which items to restore (None = all items in the
    manifest). ``use_current_config`` reroutes destinations to the current
    config's paths — useful when the original drive letters have changed since
    the backup was taken. When None, items are restored to the exact paths
    recorded in the manifest.
    """
    manifest = read_manifest(backup_root)
    plan = RestorePlan(backup_root=str(backup_root))

    if components:
        try:
            wanted = set(normalize_components(components))
        except ValueError as e:
            plan.skipped.append(str(e))
            return plan
    else:
        wanted = None

    for raw in manifest.get("items", []):
        item = BackupItem(**raw)
        if wanted is not None and item.component not in wanted:
            continue
        spec = COMPONENTS.get(item.component)
        backup_path = Path(item.dest)
        if not backup_path.exists():
            plan.skipped.append(
                f"{item.component}: missing in backup ({backup_path})"
            )
            continue

        if use_current_config is not None and spec is not None:
            current = spec.source_resolver(use_current_config) or ""
            target_path = current or item.src
        else:
            target_path = item.src

        plan.items.append(
            RestoreItem(
                component=item.component,
                src=str(backup_path),
                dest=str(target_path),
                size_bytes=_dir_size(backup_path),
            )
        )

    if wanted is not None:
        recorded = {raw["component"] for raw in manifest.get("items", [])}
        for missing in sorted(wanted - recorded):
            plan.skipped.append(
                f"{missing}: not present in this backup"
            )

    return plan


def apply_restore(
    plan: RestorePlan,
    *,
    overwrite: bool = False,
    progress_cb=None,
) -> int:
    """Execute *plan*. Returns the number of components restored.

    By default refuses to clobber an existing destination that is non-empty;
    pass ``overwrite=True`` to remove and replace it.
    """
    restored = 0
    for item in plan.items:
        if progress_cb:
            progress_cb(item, "start")

        src = Path(item.src)
        dest = Path(item.dest)

        if dest.exists():
            is_empty_dir = dest.is_dir() and not any(dest.iterdir())
            if not is_empty_dir:
                if not overwrite:
                    raise FileExistsError(
                        f"Destination already exists (pass --overwrite to "
                        f"replace it): {dest}"
                    )
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            else:
                # Empty directory — copytree refuses to write into an existing
                # directory, so remove it and let copytree recreate it.
                dest.rmdir()

        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dest))
        else:
            shutil.copy2(str(src), str(dest))

        restored += 1
        if progress_cb:
            progress_cb(item, "done")

    return restored
