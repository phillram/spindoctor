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

``shuffle_videos`` reorders both lists to a fresh random order (membership
untouched) — useful because the third-party randomizer script may not
itself randomize on every boot, so a pre-shuffled list is the only way to
vary playback order across sessions.
"""
from __future__ import annotations

import random
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


@dataclass
class ShuffleResult:
    old_order: list[str]
    new_order: list[str]
    changed: bool
    backup_path: Optional[Path] = None


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
    """Timestamped backup of *path*, mirroring ledblinky._backup's shape.

    Raises RandomizerIniError — instead of letting a raw OSError escape —
    if backup_dir was explicitly configured but writing to it fails (an
    unmounted drive, a permission problem). A misconfigured/unavailable
    backup destination should be a clear, actionable error, not a bare
    traceback the user has to scroll past to understand what happened.
    """
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if backup_dir:
        dest_dir = backup_dir / "IntroVideoRandomizer"
        dest = dest_dir / f"{path.name}.{stamp}.bak"
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        except OSError as exc:
            raise RandomizerIniError(
                f"backup_before_modify is on, but writing the Random.ini "
                f"backup to the configured backup_dir failed: {dest_dir} "
                f"({exc}). Nothing was changed — fix backup_dir (Setup tab, "
                f"or `spindoctor config set backup_dir <path>`), or turn off "
                f"backup_before_modify, then try again."
            ) from exc
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


def add_videos(
    config: Config, sources: list[Path], *, apply: bool = False,
) -> list[AddResult]:
    """Copy each of *sources* into the randomizer's Folder and register it
    in FileList/RandomList. Non-destructive: an existing file at a
    destination is never overwritten.

    Disk copies happen per-file (so a later duplicate name in the same
    batch correctly sees the earlier copy as already-on-disk), but
    Random.ini gets a single backup and a single surgical rewrite for the
    whole batch rather than one per file. Every source — and, if a backup
    will actually be needed, the configured backup destination — is
    validated up front, before any copy happens, so a missing source file
    or an unwritable backup_dir (unmounted drive, permission problem)
    aborts cleanly with nothing copied and Random.ini untouched, instead
    of leaving earlier files copied-but-unregistered. A copy failure
    partway through for a reason that can't be pre-validated (disk full,
    a locked file) can still leave earlier files in that call copied but
    unregistered; that risk predates batching (a single `add_video` copy
    could always raise) and isn't new here, just still present.
    """
    ini_path = get_ini_path(config)
    state = load_randomizer(ini_path)

    # Validate every source before touching disk or Random.ini — see the
    # docstring above for why this ordering matters for a multi-file batch.
    for source in sources:
        if not source.exists() or not source.is_file():
            raise RandomizerIniError(f"Source video not found: {source}")

    # Same reasoning for the backup destination: if this call will actually
    # try to back Random.ini up, make sure that destination is writable
    # *before* copying any source — otherwise a bad backup_dir would be
    # discovered only after files were already copied, orphaning them the
    # same way a missing source used to.
    if apply and config.backup_before_modify:
        backup_dir = _config_backup_dir(config)
        if backup_dir:
            try:
                (backup_dir / "IntroVideoRandomizer").mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RandomizerIniError(
                    f"backup_before_modify is on, but the configured "
                    f"backup_dir isn't writable: {backup_dir} ({exc}). Fix "
                    f"backup_dir (Setup tab, or `spindoctor config set "
                    f"backup_dir <path>`), or turn off backup_before_modify, "
                    f"then try again."
                ) from exc

    new_file_list = list(state.file_list)
    new_random_list = list(state.random_list)
    results: list[AddResult] = []
    any_list_change = False

    for source in sources:
        # Case-insensitive on-disk lookup — Path.exists() case-folds on
        # Windows/NTFS and macOS/APFS (the common dev/prod targets) but not
        # on a case-sensitive filesystem (e.g. Linux/ext4, where part of CI
        # runs), which would otherwise let a re-add under different casing
        # slip past the "already there" check and copy a duplicate file.
        # Scanning ourselves keeps this decision independent of the host
        # filesystem.
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
        # Case-insensitive membership check (Windows/NTFS filesystems are)
        # so an existing "capcom intro.mp4" entry isn't treated as distinct
        # from a newly-added "Capcom Intro.mp4", and against the
        # accumulated batch lists so two same-named files in one batch
        # don't both register.
        source_key = source.name.lower()
        file_list_changed = source_key not in {n.lower() for n in new_file_list}
        random_list_changed = source_key not in {n.lower() for n in new_random_list}
        already_registered = not file_list_changed and not random_list_changed

        copied = False
        if apply:
            if not already_on_disk:
                state.folder.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                copied = True
        else:
            copied = not already_on_disk

        if file_list_changed:
            new_file_list.append(source.name)
        if random_list_changed:
            new_random_list.append(source.name)
        any_list_change = any_list_change or file_list_changed or random_list_changed

        results.append(AddResult(
            dest=dest,
            copied=copied,
            already_registered=already_registered,
            file_list_changed=file_list_changed,
            random_list_changed=random_list_changed,
        ))

    if apply and any_list_change:
        backup_path = None
        if config.backup_before_modify:
            backup_path = _backup(ini_path, _config_backup_dir(config))
        _rewrite_lists(ini_path, new_file_list, new_random_list)
        for result in results:
            if result.file_list_changed or result.random_list_changed:
                result.backup_path = backup_path

    return results


def add_video(config: Config, source: Path, *, apply: bool = False) -> AddResult:
    """Copy *source* into the randomizer's Folder and register it in
    FileList/RandomList. Non-destructive: an existing file at the
    destination is never overwritten.
    """
    return add_videos(config, [source], apply=apply)[0]


def remove_videos(
    config: Config, filenames: list[str], *, apply: bool = False,
) -> list[RemoveResult]:
    """Drop each of *filenames* from FileList/RandomList. The video files
    on disk are never deleted — this only stops the randomizer from
    picking them. A single Random.ini backup and rewrite covers the whole
    batch rather than one per file.
    """
    ini_path = get_ini_path(config)
    state = load_randomizer(ini_path)

    new_file_list = list(state.file_list)
    new_random_list = list(state.random_list)
    results: list[RemoveResult] = []
    any_change = False

    for filename in filenames:
        target = filename.lower()
        file_list_changed = any(f.lower() == target for f in new_file_list)
        random_list_changed = any(f.lower() == target for f in new_random_list)
        if file_list_changed:
            new_file_list = [f for f in new_file_list if f.lower() != target]
        if random_list_changed:
            new_random_list = [f for f in new_random_list if f.lower() != target]
        any_change = any_change or file_list_changed or random_list_changed
        results.append(RemoveResult(
            filename=filename,
            file_list_changed=file_list_changed,
            random_list_changed=random_list_changed,
        ))

    if apply and any_change:
        backup_path = None
        if config.backup_before_modify:
            backup_path = _backup(ini_path, _config_backup_dir(config))
        _rewrite_lists(ini_path, new_file_list, new_random_list)
        for result in results:
            if result.changed:
                result.backup_path = backup_path

    return results


def remove_video(config: Config, filename: str, *, apply: bool = False) -> RemoveResult:
    """Drop *filename* from FileList/RandomList. The video file on disk is
    never deleted — this only stops the randomizer from picking it.
    """
    return remove_videos(config, [filename], apply=apply)[0]


def shuffle_videos(
    config: Config, *, seed: Optional[int] = None, apply: bool = False,
) -> ShuffleResult:
    """Randomize the playback order of the registered videos in Random.ini.

    FileList and RandomList are shuffled to the same new order; a filename
    present in only one of the two lists (dangling INI entries can happen —
    see :func:`list_videos`) is shuffled separately within that list so
    membership in each list is preserved exactly, just reordered. No video
    file, and no FileList/RandomList *membership*, is added, removed, or
    otherwise touched — this only changes the order names are listed in.

    ``seed`` makes the shuffle reproducible (mainly for tests); omit it for a
    fresh random order every call.
    """
    ini_path = get_ini_path(config)
    state = load_randomizer(ini_path)
    rng = random.Random(seed)

    new_file_list = list(state.file_list)
    rng.shuffle(new_file_list)

    file_set = set(state.file_list)
    random_set = set(state.random_list)
    new_random_list = [name for name in new_file_list if name in random_set]
    random_only = [name for name in state.random_list if name not in file_set]
    rng.shuffle(random_only)
    new_random_list += random_only

    changed = new_file_list != state.file_list or new_random_list != state.random_list

    result = ShuffleResult(
        old_order=state.file_list,
        new_order=new_file_list,
        changed=changed,
    )

    if apply and changed:
        if config.backup_before_modify:
            result.backup_path = _backup(ini_path, _config_backup_dir(config))
        _rewrite_lists(ini_path, new_file_list, new_random_list)

    return result
