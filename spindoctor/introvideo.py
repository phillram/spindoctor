"""Intro Video Randomizer — manage the pool of startup videos HyperSpin's
Random.ini-driven randomizer picks from.

The randomizer (a third-party AutoHotkey/launcher script, not part of
SpinDoctor) reads a single INI file on every boot::

    [Randomize1]
    Option=1
    Folder=D:\\Arcade\\Media\\Frontend\\Video\\Intro Video Randomizer\\Intro Videos
    FileToRandomize=D:\\Arcade\\Media\\Frontend\\Video\\Intro.mp4
    FileList=a.mp4|b.mp4|c.mp4
    RandomList=a.mp4|c.mp4

``Folder`` is where the candidate video files live; ``FileToRandomize`` is
the file HyperSpin actually plays on boot (the randomizer copies a chosen
video over it). ``FileList`` and ``RandomList`` are pipe-delimited filename
lists — this module keeps them identical, since "remove" means "the
randomizer should stop using this file" rather than a distinction SpinDoctor
needs to expose.

Writes are surgical: only the ``FileList=``/``RandomList=`` lines are
replaced in place (same approach as ``rocketlauncher.rewrite_pclauncher_application``)
so every other line, comment, and the file's key casing survive untouched.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config

INI_FILENAME = "Random.ini"
SECTION = "Randomize1"
BACKUP_SUBFOLDER = "Backup"
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".avi", ".wmv", ".mkv", ".mov", ".m4v", ".flv",
})


class RandomizerIniError(Exception):
    """Random.ini is unset, missing, or missing a required key."""


@dataclass
class RandomizerState:
    ini_path: Path
    option: str
    folder: Path
    file_to_randomize: Path
    file_list: list[str] = field(default_factory=list)
    random_list: list[str] = field(default_factory=list)


@dataclass
class VideoStatus:
    filename: str
    in_file_list: bool
    in_random_list: bool
    on_disk: bool
    size_bytes: Optional[int] = None

    @property
    def registered(self) -> bool:
        return self.in_file_list and self.in_random_list


@dataclass
class AddResult:
    dest: Path
    copied: bool
    already_registered: bool
    file_list_changed: bool
    random_list_changed: bool
    backup_path: Optional[Path] = None


@dataclass
class RemoveResult:
    filename: str
    file_list_changed: bool
    random_list_changed: bool
    backup_path: Optional[Path] = None

    @property
    def changed(self) -> bool:
        return self.file_list_changed or self.random_list_changed


def get_ini_path(config: Config) -> Path:
    if not config.intro_randomizer_dir:
        raise RandomizerIniError(
            "intro_randomizer_dir is not set — configure the Intro Video "
            "Randomizer directory (the folder containing Random.ini) via "
            "the Setup tab or `spindoctor config set intro_randomizer_dir <path>`."
        )
    return Path(config.intro_randomizer_dir) / INI_FILENAME


def _split_list(value: str) -> list[str]:
    return [v for v in value.split("|") if v]


def _join_list(items: list[str]) -> str:
    return "|".join(items)


def load_randomizer(ini_path: Path) -> RandomizerState:
    if not ini_path.exists():
        raise RandomizerIniError(f"Random.ini not found: {ini_path}")
    text = ini_path.read_text(encoding="utf-8", errors="replace")
    in_section = False
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].strip().lower() == SECTION.lower()
            continue
        if not in_section or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        values[key.strip().lower()] = val

    missing = [k for k in ("folder", "filetorandomize") if k not in values]
    if missing:
        raise RandomizerIniError(
            f"[{SECTION}] in {ini_path} is missing key(s): {', '.join(missing)}"
        )
    return RandomizerState(
        ini_path=ini_path,
        option=values.get("option", "1"),
        folder=Path(values["folder"]),
        file_to_randomize=Path(values["filetorandomize"]),
        file_list=_split_list(values.get("filelist", "")),
        random_list=_split_list(values.get("randomlist", "")),
    )


def _config_backup_dir(config: Config) -> Optional[Path]:
    return Path(config.backup_dir) if getattr(config, "backup_dir", None) else None


def _backup(path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """Timestamped backup of *path*, mirroring ledblinky._backup's shape."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if backup_dir:
        dest_dir = backup_dir / "IntroVideoRandomizer"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{path.name}.{stamp}.bak"
    else:
        dest = path.with_suffix(path.suffix + f".{stamp}.bak")
    shutil.copy2(path, dest)
    return dest


def _rewrite_lists(
    ini_path: Path, file_list: list[str], random_list: list[str],
) -> bool:
    """Replace only the FileList=/RandomList= lines of [Randomize1], verbatim otherwise."""
    lines = ini_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    in_section = False
    saw_file_list = False
    saw_random_list = False
    new_lines: list[str] = []
    changed = False
    for line in lines:
        stripped = line.rstrip("\r\n")
        eol = line[len(stripped):]
        head = stripped.strip()
        if head.startswith("[") and head.endswith("]"):
            in_section = head[1:-1].strip().lower() == SECTION.lower()
        if in_section and re.match(r"(?i)^FileList\s*=", stripped):
            saw_file_list = True
            want = f"FileList={_join_list(file_list)}"
            if stripped != want:
                new_lines.append(want + eol)
                changed = True
                continue
        if in_section and re.match(r"(?i)^RandomList\s*=", stripped):
            saw_random_list = True
            want = f"RandomList={_join_list(random_list)}"
            if stripped != want:
                new_lines.append(want + eol)
                changed = True
                continue
        new_lines.append(line)

    if not (saw_file_list and saw_random_list):
        raise RandomizerIniError(
            f"[{SECTION}] in {ini_path} is missing FileList=/RandomList= — "
            "cannot update the randomizer pool."
        )
    if changed:
        ini_path.write_text("".join(new_lines), encoding="utf-8")
    return changed


def list_videos(state: RandomizerState) -> list[VideoStatus]:
    """Every video on disk (excluding the Backup\\ subfolder) union every
    filename registered in FileList/RandomList — surfaces orphaned disk
    files and dangling INI references alike.

    Matching is case-insensitive (Windows/NTFS filesystems are), so a
    ``Random.ini`` entry that differs only in case from the on-disk
    filename is treated as the same video, not a second missing one.
    """
    on_disk: dict[str, int] = {}      # lower(name) -> size
    on_disk_names: dict[str, str] = {}  # lower(name) -> actual on-disk casing
    if state.folder.exists():
        for p in state.folder.iterdir():
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            key = p.name.lower()
            on_disk[key] = p.stat().st_size
            on_disk_names[key] = p.name

    file_list_lower = {n.lower() for n in state.file_list}
    random_list_lower = {n.lower() for n in state.random_list}

    # Prefer the on-disk casing for display; fall back to whatever casing
    # the INI used for entries that don't exist on disk.
    canonical: dict[str, str] = {}
    for name in state.file_list + state.random_list:
        canonical.setdefault(name.lower(), name)
    canonical.update(on_disk_names)

    keys = set(on_disk) | file_list_lower | random_list_lower
    out = [
        VideoStatus(
            filename=canonical[key],
            in_file_list=key in file_list_lower,
            in_random_list=key in random_list_lower,
            on_disk=key in on_disk,
            size_bytes=on_disk.get(key),
        )
        for key in keys
    ]
    out.sort(key=lambda v: v.filename.lower())
    return out


def add_video(config: Config, source: Path, *, apply: bool = False) -> AddResult:
    """Copy *source* into the randomizer's Folder and register it in
    FileList/RandomList. Non-destructive: an existing file at the
    destination is never overwritten.
    """
    ini_path = get_ini_path(config)
    state = load_randomizer(ini_path)
    if not source.exists() or not source.is_file():
        raise RandomizerIniError(f"Source video not found: {source}")

    # Case-insensitive on-disk lookup — Path.exists() case-folds on
    # Windows/NTFS and macOS/APFS (the common dev/prod targets) but not on
    # a case-sensitive filesystem (e.g. Linux/ext4, where part of CI runs),
    # which would otherwise let a re-add under different casing slip past
    # the "already there" check and copy a duplicate file. Scanning
    # ourselves keeps this decision independent of the host filesystem.
    dest = state.folder / source.name
    existing_match = None
    if state.folder.exists():
        for p in state.folder.iterdir():
            if p.is_file() and p.name.lower() == source.name.lower():
                existing_match = p
                break
    if existing_match is not None:
        dest = existing_match
    already_on_disk = existing_match is not None
    # Case-insensitive membership check (Windows/NTFS filesystems are) so an
    # existing "capcom intro.mp4" entry isn't treated as distinct from a
    # newly-added "Capcom Intro.mp4".
    source_key = source.name.lower()
    file_list_changed = source_key not in {n.lower() for n in state.file_list}
    random_list_changed = source_key not in {n.lower() for n in state.random_list}
    already_registered = not file_list_changed and not random_list_changed

    if not apply:
        return AddResult(
            dest=dest,
            copied=not already_on_disk,
            already_registered=already_registered,
            file_list_changed=file_list_changed,
            random_list_changed=random_list_changed,
        )

    state.folder.mkdir(parents=True, exist_ok=True)
    copied = False
    if not already_on_disk:
        shutil.copy2(source, dest)
        copied = True

    backup_path = None
    if file_list_changed or random_list_changed:
        if config.backup_before_modify:
            backup_path = _backup(ini_path, _config_backup_dir(config))
        new_file_list = list(state.file_list)
        if file_list_changed:
            new_file_list.append(source.name)
        new_random_list = list(state.random_list)
        if random_list_changed:
            new_random_list.append(source.name)
        _rewrite_lists(ini_path, new_file_list, new_random_list)

    return AddResult(
        dest=dest,
        copied=copied,
        already_registered=already_registered,
        file_list_changed=file_list_changed,
        random_list_changed=random_list_changed,
        backup_path=backup_path,
    )


def remove_video(config: Config, filename: str, *, apply: bool = False) -> RemoveResult:
    """Drop *filename* from FileList/RandomList. The video file on disk is
    never deleted — this only stops the randomizer from picking it.
    """
    ini_path = get_ini_path(config)
    state = load_randomizer(ini_path)
    target = filename.lower()
    file_list_changed = any(f.lower() == target for f in state.file_list)
    random_list_changed = any(f.lower() == target for f in state.random_list)

    if not apply or not (file_list_changed or random_list_changed):
        return RemoveResult(
            filename=filename,
            file_list_changed=file_list_changed,
            random_list_changed=random_list_changed,
        )

    backup_path = None
    if config.backup_before_modify:
        backup_path = _backup(ini_path, _config_backup_dir(config))
    new_file_list = [f for f in state.file_list if f.lower() != target]
    new_random_list = [f for f in state.random_list if f.lower() != target]
    _rewrite_lists(ini_path, new_file_list, new_random_list)

    return RemoveResult(
        filename=filename,
        file_list_changed=file_list_changed,
        random_list_changed=random_list_changed,
        backup_path=backup_path,
    )
