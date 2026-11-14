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

import configparser
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from ._utils import win_safe_stem


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
    # "fade" media (media.py MEDIA_DIR_MAP → Images/Artwork4).  Was omitted, so
    # fade images were never mirrored into synthetic wheels.
    "Images/Artwork4",
    # Title-screen captures used by many HyperSpin themes for side-panel
    # artwork.  Absent from the original list — games in synthetic wheels
    # showed a blank title-image slot even though source systems had them.
    "Images/Titles",
    "Images/Letters",
    "Video",
    "Video/Trailers",
    "Sound",
    # Themes are usually distributed as per-game .zip files
    # (e.g. Media/MAME/Themes/1942.zip).  Include the Themes subfolder here
    # so those zip files are picked up by the file-based mirror path.
    # The MEDIA_DIR_SUBDIRS entry below handles the less-common case where
    # themes have been extracted into per-game subdirectories.
    "Themes",
)
MEDIA_DIR_SUBDIRS = ("Themes",)
_FILE_EXTS = {
    # Uncompressed media formats
    ".png", ".jpg", ".jpeg",
    ".mp4", ".avi", ".flv", ".mkv",
    # .wmv is the native Windows Media Video format and very common in
    # older HyperSpin video packs, especially on Windows 7 cabinets.
    # .mpeg / .mpg are the older MPEG-1/2 container also found in legacy packs.
    ".wmv", ".mpeg", ".mpg",
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
    replace_existing: bool = False


@dataclass
class LinkPlan:
    actions: list[LinkAction] = field(default_factory=list)

    @property
    def to_apply(self) -> list[LinkAction]:
        return [a for a in self.actions if not a.skip_reason]

    @property
    def skipped(self) -> list[LinkAction]:
        return [a for a in self.actions if a.skip_reason]


def _read_hs_video_dir(settings_dir: Path, system: str) -> Optional[Path]:
    """Return the ``[video defaults]`` path override from a HyperSpin system INI.

    Some setups point HyperSpin MAME subsystems ("4-Player Games", "Driving
    Games", "Gun Games", etc.) at the MAME wheel's videos in
    ``Media/MAME/Video/`` through the system's Settings INI::

        [video defaults]
        path=D:\\Arcade\\Media\\MAME\\Video\\

    With ``path=`` set, HyperSpin reads that wheel's videos *only* from that
    folder, with no per-game fallback: videos saved in the wheel's own
    ``Media/<system>/Video/`` (by a scraper, or added by hand for games that
    aren't MAME's) never play, and a path that's gone (an old drive letter)
    plays none at all, without an error.  Copying the videos the wheel uses
    into its own ``Video/`` folder and leaving ``path=`` blank is the safer
    setup; ``doctor``'s Video redirects check reports both problems.

    When the INI exists and the path points at an existing directory, this
    function returns that directory so :func:`plan_mirror` can look there when
    the system's own ``Media/<system>/Video/`` folder is absent.

    The settings dir is normally ``<hyperspin_dir>/Settings/``.
    """
    ini_path = settings_dir / f"{system}.ini"
    if not ini_path.is_file():
        return None
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        # utf-8-sig handles the BOM that HyperSpin sometimes writes
        parser.read(ini_path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            parser.read(ini_path, encoding="cp1252")
        except (OSError, configparser.Error, UnicodeDecodeError):
            return None
    except (OSError, configparser.Error):
        return None
    raw = parser.get("video defaults", "path", fallback="").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def plan_mirror(
    media_root: Path,
    source_system: str,
    target_system: str,
    source_stem: str,
    target_stem: Optional[str] = None,
    *,
    video_dir_override: Optional[Path] = None,
    refresh: bool = False,
) -> LinkPlan:
    """Build the action list to mirror one game's media from src→target.

    *source_stem* is the basename used by the originating system; if the
    target should use a different name (collision suffixing) pass
    *target_stem*.

    *video_dir_override* — when set and the source system's own ``Video/``
    subdirectory does not exist, this path is scanned for video files instead.
    Use :func:`_read_hs_video_dir` to derive the value from the HyperSpin
    system settings INI (``[video defaults]`` → ``path=``).  This handles
    MAME subsystems ("4-Player Games", "Driving Games", etc.) that store all
    their videos under ``Media/MAME/Video/`` rather than a per-system folder.

    ``refresh`` permits replacing stale targets. Only wheel builders that have
    validated ownership should enable it; ordinary mirrors preserve conflicts.
    """
    # Media files on disk are always written with a Windows-safe stem
    # (media.py sanitizes game names before writing, and HyperSpin resolves
    # media the same way), so match source files and name target files by the
    # sanitized stem — not the raw game name, which may contain ':' etc.  Using
    # the raw name meant zero media was mirrored for any game with a forbidden
    # character in its title (e.g. "Metal Gear Solid: VR Missions").
    target_stem = target_stem or source_stem
    source_stem = win_safe_stem(source_stem)
    target_stem = win_safe_stem(target_stem)
    plan = LinkPlan()
    if not source_stem or not target_stem:
        return plan

    src_root = media_root / source_system
    dst_root = media_root / target_system
    if not src_root.exists():
        return plan

    for sub in MEDIA_FILE_SUBDIRS:
        src_dir = src_root / sub
        # For the Video subdir, fall back to the HyperSpin redirect path when
        # the source system's Video folder is absent OR exists but contains no
        # file with the right stem.  HyperSpin (and previous SpinDoctor runs)
        # often create the directory skeleton without populating it, so checking
        # is_dir() alone is not sufficient — an empty directory must also
        # trigger the fallback.
        if sub == "Video" and video_dir_override:
            has_own_video = src_dir.is_dir() and any(
                e.is_file() and e.stem == source_stem
                and e.suffix.lower() in _FILE_EXTS
                for e in src_dir.iterdir()
            )
            if not has_own_video:
                src_dir = video_dir_override
        if not src_dir.is_dir():
            continue
        theme_found = False
        for entry in src_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.stem != source_stem or entry.suffix.lower() not in _FILE_EXTS:
                continue
            if sub == "Themes":
                theme_found = True
            dest = dst_root / sub / f"{target_stem}{entry.suffix}"
            plan.actions.append(_classify(entry, dest, is_dir=False, refresh=refresh))

        # When the source system has no per-game theme, fall back to
        # Default.zip (the console-level fallback HyperSpin uses in the
        # source wheel). Copy it as <target_stem>.zip so the same themed
        # background and video layout appear in the synthetic wheel.
        if sub == "Themes" and not theme_found:
            # Accept either casing: SpinDoctor's own fill_default_theme (and the
            # HyperSpin/RocketLauncher convention) writes lowercase default.zip,
            # while some packs ship Default.zip.
            default_theme = src_dir / "default.zip"
            if not default_theme.is_file():
                default_theme = src_dir / "Default.zip"
            if default_theme.is_file():
                dest = dst_root / sub / f"{target_stem}.zip"
                plan.actions.append(_classify(default_theme, dest, is_dir=False, refresh=refresh))

    for sub in MEDIA_DIR_SUBDIRS:
        src_dir = src_root / sub / source_stem
        if src_dir.is_dir():
            dest = dst_root / sub / target_stem
            plan.actions.append(_classify(src_dir, dest, is_dir=True, refresh=refresh))

    return plan


def _classify(src: Path, dest: Path, is_dir: bool, refresh: bool = False) -> LinkAction:
    if dest.exists() or dest.is_symlink():
        if _same_target(src, dest):
            return LinkAction(src=src, dest=dest, is_dir=is_dir,
                              skip_reason="already linked")
        if refresh:
            return LinkAction(src=src, dest=dest, is_dir=is_dir, replace_existing=True)
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
        if src.is_dir() and dest.is_dir():
            src_names = {p.name for p in src.iterdir()}
            return src_names == {p.name for p in dest.iterdir()} and all(
                _same_target(src / name, dest / name) for name in src_names
            )
        # filecmp's global stat cache can be stale after same-size/mtime edits.
        # Compare bytes directly rather than treating timestamps as identity.
        if not src.is_file() or not dest.is_file() or s_stat.st_size != d_stat.st_size:
            return False
        with src.open("rb") as left, dest.open("rb") as right:
            while True:
                chunk = left.read(1024 * 1024)
                if chunk != right.read(1024 * 1024):
                    return False
                if not chunk:
                    return True
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
            if action.replace_existing:
                outcome = _refresh_one(action, mode)
            else:
                outcome = _apply_one(action.src, action.dest, action.is_dir, mode)
            summary[outcome] += 1
            if log_fn is not None:
                verb = "copy " if outcome == "copied" else "link "
                log_fn(f"  {verb} {action.src}\n     ->  {action.dest}")
        except OSError as e:
            summary["errors"].append(f"{action.src} -> {action.dest}: {e}")
            if log_fn is not None:
                log_fn(f"  ERROR {action.src} → {action.dest}: {e}")
    return summary


def _refresh_one(action: LinkAction, mode: LinkMode) -> str:
    """Stage replacements so a failed copy leaves the previous mirror intact."""
    with tempfile.TemporaryDirectory(prefix=".spindoctor-mirror-", dir=action.dest.parent) as tmp:
        staged = Path(tmp) / "new"
        outcome = _apply_one(action.src, staged, action.is_dir, mode)
        # os.replace cannot put a directory over a symlink or a file, and on
        # Windows cannot replace a directory or directory symlink at all.
        if action.dest.is_symlink() or action.dest.is_dir() or staged.is_dir():
            previous = Path(tmp) / "previous"
            os.replace(action.dest, previous)
            try:
                os.replace(staged, action.dest)
            except BaseException:
                os.replace(previous, action.dest)
                raise
        else:
            os.replace(staged, action.dest)
        return outcome


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
    target_stem = win_safe_stem(target_stem)
    removed = 0
    sys_root = media_root / target_system
    # Names such as ".." normalize to "", which would select the whole
    # media subfolder for deletion.
    if not target_stem or not sys_root.exists():
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


def prune_mirrored_media(target_root: Path, keep: set[str]) -> list[str]:
    """Remove stale game media, without entering themes or deleting system art."""
    errors = []
    keep = {win_safe_stem(stem).casefold() for stem in keep}
    for sub in MEDIA_FILE_SUBDIRS:
        # Letters and wheel sounds belong to the system, not individual games.
        if sub == "Images/Letters":
            continue
        directory = target_root / sub
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in _FILE_EXTS:
                continue
            if (path.stem.casefold() in keep
                    or (sub == "Themes" and path.stem.casefold() == "default")
                    or (sub == "Sound" and path.stem.casefold() == "wheel click")):
                continue
            try:
                path.unlink()
            except OSError as exc:
                errors.append(f"cleanup {path.name}: {exc}")
    for sub in MEDIA_DIR_SUBDIRS:
        directory = target_root / sub
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_dir() or path.name.casefold() in keep or path.name.casefold() == "default":
                continue
            try:
                if path.is_symlink():
                    path.unlink()
                else:
                    shutil.rmtree(path)
            except OSError as exc:
                errors.append(f"cleanup {path.name}: {exc}")
    return errors
