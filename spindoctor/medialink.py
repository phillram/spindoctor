"""Mirror media files from one system folder to another.

HyperSpin only looks under ``Media/<system>/...``, so the synthetic
"Favorites" and "Recently Played" wheels need their own copies of each
game's media. To avoid doubling disk usage, this module prefers
hardlinks (NTFS) or junctions (directory-level) and falls back to
copies when the filesystem (FAT32, exFAT) doesn't support either.

A *plan* is built first so callers can preview moves; ``apply_plan``
executes it. Re-runs are idempotent: existing targets that already
point at the right source are left alone.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class LinkMode(str, Enum):
    HARDLINK = "link"   # os.link — same inode, zero extra disk
    SYMLINK = "symlink" # os.symlink — small pointer, traversable
    COPY = "copy"       # shutil.copy2 — duplicated bytes
    AUTO = "auto"       # try hardlink, fall back to copy on OSError


# Mirror layout under Media/<system>/. Themes live as folders so they get
# special handling (link the directory, not its contents).
MEDIA_FILE_SUBDIRS = (
    "Images/Wheel",
    "Images/Backgrounds",
    "Images/Artwork1",
    "Images/Artwork2",
    "Images/Artwork3",
    "Video",
    "Video/Trailers",
    "Sound",
)
MEDIA_DIR_SUBDIRS = ("Themes",)
_FILE_EXTS = {
    # Uncompressed media formats
    ".png", ".jpg", ".jpeg",
    ".mp4", ".avi", ".flv", ".mkv",
    ".mp3", ".wav", ".ogg",
    # Archive-packed media.
    # HyperSpin reads .zip natively (video, wheel art, themes, etc.).
    # The other formats (.rar, .7z, .lha, .lzh, .gz, .tar) are not read
    # natively by HyperSpin but may appear in media directories from
    # downloaded media packs — include them so they are not silently skipped
    # during the Favorites / Recently Played / Most Played mirror.
    ".zip",
    ".rar", ".7z",
    ".lha", ".lzh",
    ".gz", ".tar",
}


@dataclass
class LinkAction:
    src: Path
    dest: Path
    is_dir: bool = False
    skip_reason: str = ""  # set when nothing needs doing


@dataclass
class LinkPlan:
    actions: list[LinkAction] = field(default_factory=list)

    @property
    def to_apply(self) -> list[LinkAction]:
        return [a for a in self.actions if not a.skip_reason]

    @property
    def skipped(self) -> list[LinkAction]:
        return [a for a in self.actions if a.skip_reason]


def plan_mirror(
    media_root: Path,
    source_system: str,
    target_system: str,
    source_stem: str,
    target_stem: Optional[str] = None,
) -> LinkPlan:
    """Build the action list to mirror one game's media from src→target.

    *source_stem* is the basename used by the originating system; if the
    target should use a different name (collision suffixing) pass
    *target_stem*.
    """
    target_stem = target_stem or source_stem
    plan = LinkPlan()

    src_root = media_root / source_system
    dst_root = media_root / target_system
    if not src_root.exists():
        return plan

    for sub in MEDIA_FILE_SUBDIRS:
        src_dir = src_root / sub
        if not src_dir.is_dir():
            continue
        for entry in src_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.stem != source_stem or entry.suffix.lower() not in _FILE_EXTS:
                continue
            dest = dst_root / sub / f"{target_stem}{entry.suffix}"
            plan.actions.append(_classify(entry, dest, is_dir=False))

    for sub in MEDIA_DIR_SUBDIRS:
        src_dir = src_root / sub / source_stem
        if src_dir.is_dir():
            dest = dst_root / sub / target_stem
            plan.actions.append(_classify(src_dir, dest, is_dir=True))

    return plan


def _classify(src: Path, dest: Path, is_dir: bool) -> LinkAction:
    if dest.exists() or dest.is_symlink():
        if _same_target(src, dest):
            return LinkAction(src=src, dest=dest, is_dir=is_dir,
                              skip_reason="already linked")
        return LinkAction(src=src, dest=dest, is_dir=is_dir,
                          skip_reason="target exists, different content")
    return LinkAction(src=src, dest=dest, is_dir=is_dir)


def _same_target(src: Path, dest: Path) -> bool:
    """True when *dest* already points at *src* (hardlink, symlink, or identical copy)."""
    try:
        if dest.is_symlink():
            return dest.resolve() == src.resolve()
        s_stat = src.stat()
        d_stat = dest.stat()
        # Same inode → hardlink / junction
        if (s_stat.st_dev, s_stat.st_ino) == (d_stat.st_dev, d_stat.st_ino):
            return True
        # Same size + mtime is a cheap "probably already copied" hint
        return s_stat.st_size == d_stat.st_size and abs(
            s_stat.st_mtime - d_stat.st_mtime) < 1.0
    except OSError:
        return False


def apply_plan(plan: LinkPlan, mode: LinkMode = LinkMode.AUTO,
               log_fn=None) -> dict:
    """Execute the plan with the given link mode. Returns a summary dict.

    *log_fn* is an optional callable that receives one string per file
    action — useful for verbose CLI output or GUI progress.  Each line
    is of the form::

        copy  D:\\Media\\MAME\\Images\\Wheel\\pacman.png
           →  D:\\Media\\Favorites\\Images\\Wheel\\pacman.png

    Pass ``print`` (or a GUI append function) to enable per-file logging.
    """
    summary = {"linked": 0, "copied": 0, "skipped": 0, "errors": []}

    for action in plan.actions:
        if action.skip_reason:
            summary["skipped"] += 1
            continue
        action.dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            outcome = _apply_one(action.src, action.dest, action.is_dir, mode)
            summary[outcome] += 1
            if log_fn is not None:
                verb = "copy " if outcome == "copied" else "link "
                log_fn(f"  {verb} {action.src}\n     →  {action.dest}")
        except OSError as e:
            summary["errors"].append(f"{action.src} → {action.dest}: {e}")
            if log_fn is not None:
                log_fn(f"  ERROR {action.src} → {action.dest}: {e}")
    return summary


def _apply_one(src: Path, dest: Path, is_dir: bool, mode: LinkMode) -> str:
    """Apply one link/copy operation. Returns 'linked' or 'copied'."""
    if is_dir:
        # Directories: try symlink (cross-platform), fall back to copytree
        if mode in (LinkMode.SYMLINK, LinkMode.AUTO, LinkMode.HARDLINK):
            try:
                os.symlink(src, dest, target_is_directory=True)
                return "linked"
            except (OSError, NotImplementedError):
                if mode == LinkMode.SYMLINK:
                    raise
        shutil.copytree(src, dest)
        return "copied"

    if mode == LinkMode.HARDLINK:
        os.link(src, dest)
        return "linked"
    if mode == LinkMode.SYMLINK:
        os.symlink(src, dest)
        return "linked"
    if mode == LinkMode.COPY:
        shutil.copy2(src, dest)
        return "copied"
    # AUTO — hardlink first, fallback to copy
    try:
        os.link(src, dest)
        return "linked"
    except OSError:
        shutil.copy2(src, dest)
        return "copied"


def remove_target(media_root: Path, target_system: str, target_stem: str) -> int:
    """Delete every mirrored file/folder for *target_stem* in *target_system*.

    Returns count removed. Used when un-favoriting a game so we don't
    leave orphan media behind.
    """
    removed = 0
    sys_root = media_root / target_system
    if not sys_root.exists():
        return 0

    for sub in MEDIA_FILE_SUBDIRS:
        d = sys_root / sub
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and f.stem == target_stem:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass

    for sub in MEDIA_DIR_SUBDIRS:
        d = sys_root / sub / target_stem
        if d.exists():
            try:
                if d.is_symlink() or d.is_file():
                    d.unlink()
                else:
                    shutil.rmtree(d)
                removed += 1
            except OSError:
                pass
    return removed
