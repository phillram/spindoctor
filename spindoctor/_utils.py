"""Small shared helpers used across multiple SpinDoctor modules.

Historically `format_bytes` and `free_bytes` lived in three places —
`backup.py`, `migrate.py`, and `cleanup.py` (as `format_size`) — with
copy-paste implementations. They've now landed here, and the original
modules re-export them so existing callers (`from .backup import
format_bytes`, `from .cleanup import format_size`) keep working
without churning every call site.

Resist the urge to grow this file into a junk drawer. New helpers
belong here only when they're (a) shared by two or more modules and
(b) genuinely generic — disk-usage primitives, byte formatting, etc.
Domain-specific helpers (manifest path resolution, component
normalisation) should stay in their owning module even when the
shape looks similar across modules; their semantics diverge.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional


def resolve_atomic_tmp_dir(target: Path, configured: Optional[Path]) -> Path:
    """Use a configured scratch folder only on the target's filesystem."""
    if configured is not None:
        try:
            configured.mkdir(parents=True, exist_ok=True)
            if configured.stat().st_dev == target.parent.stat().st_dev:
                return configured
        except OSError:
            pass
    return target.parent


def atomic_write_bytes(target: Path, data: bytes, tmp_dir: Optional[Path] = None) -> None:
    """Write complete bytes through a unique temp file, then replace the target."""
    fd, tmp = tempfile.mkstemp(dir=resolve_atomic_tmp_dir(target, tmp_dir), suffix=".tmp")
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("Could not complete atomic write")
            remaining = remaining[written:]
        os.close(fd)
        fd = -1
        os.replace(tmp, target)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            # Best-effort cleanup must not mask a failed write or replacement.
            pass


def is_within(path: Path, parent: Path) -> bool:
    """Whether a resolved path is the parent itself or one of its descendants."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def move_no_replace(src: Path, dest: Path) -> None:
    """Move to an exact path, refusing occupied files, folders and broken links."""
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"Destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


_WIN_FILENAME_FORBIDDEN = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")
_WIN_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(10)}
)


def win_safe_stem(name: str) -> str:
    """Match HyperSpin's Windows-safe media and PCLauncher filename convention."""
    for ch in _WIN_FILENAME_FORBIDDEN:
        name = name.replace(ch, "")
    name = name.strip().rstrip(".")
    return name + "_" if name.upper() in _WIN_RESERVED_NAMES else name


def format_bytes(n: int) -> str:
    """Render a non-negative byte count as a short human string.

    Examples:
        format_bytes(0)              → "0 B"
        format_bytes(512)            → "512 B"
        format_bytes(2048)           → "2.0 KB"
        format_bytes(5 * 1024**2)    → "5.0 MB"
        format_bytes(3 * 1024**4)    → "3.0 TB"

    `B` is rendered without a decimal point; every higher unit gets
    one decimal place. The loop stops at TB so anything above that
    keeps rendering in TB rather than overflowing into PB — fine for
    the cabinet-library scale this project targets.
    """
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(n)} B"


def free_bytes(path: Path) -> int:
    """Return free space in bytes at *path* (or its nearest existing parent).

    Walks up the parent chain until an existing directory is found —
    so a destination path like ``E:\\Backups\\new-folder`` that doesn't
    exist yet still reports the free space of its parent volume.
    Returns 0 on any OS error rather than raising; callers use this
    for "are we likely to fit?" hints, not for blocking writes.
    """
    p = path
    while not p.exists():
        if p.parent == p:
            break
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return 0


def unique_path(path: Path) -> Path:
    """Return *path*, or the first free ``<stem>_2<suffix>``, ``<stem>_3<suffix>``, … sibling.

    Backup names carry a ``YYYYMMDD_HHMMSS`` stamp, which only has
    one-second resolution, so two backups written in the same second
    would otherwise overwrite each other. ``Emulators.20260614_174635.bak``
    becomes ``Emulators.20260614_174635_2.bak``; a folder such as
    ``scrub-20260614_174635`` becomes ``scrub-20260614_174635_2``.
    """
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def numbered_path_key(path: Path) -> tuple:
    """Sort timestamped names and unique_path counters numerically."""
    return tuple((1, int(part)) if part.isdecimal() else (0, part)
                 for part in re.split(r"(\d+)", path.name))
