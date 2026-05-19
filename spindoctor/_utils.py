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

import shutil
from pathlib import Path


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
