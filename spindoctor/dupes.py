"""Duplicate ROM detection — within a system and across systems.

Finds ROM files that look like duplicates by:
  * normalized title (region/version/disc tags stripped) — e.g.
    ``Zelda (USA).nes`` and ``Zelda (Japan).nes`` collapse to the same key
  * file content (size + SHA1) when ``by_content=True`` — slow but exact;
    a ROM header (SNES copier, iNES, fwNES) is left out, so a headered and
    an unheadered copy of one game match
  * cross-system: the same normalized title appearing under two systems
    (e.g. ``Tetris`` filed under both ``GameBoy`` and ``NES``).
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import archives
from .audit import scan_roms
from .config import Config
from .romheaders import file_header_length
from .romutils import normalize


@dataclass
class DuplicateGroup:
    """A set of ROM files considered duplicates of each other."""
    key: str
    system: str
    files: list[Path] = field(default_factory=list)
    reason: str = "title"  # "title" | "content"
    # Content groups whose copies differ by a ROM header: the files whose
    # header was left out of the match. Empty when all are byte-for-byte equal.
    headers_ignored: list[Path] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.files)


@dataclass
class CrossSystemMatch:
    """Same normalized title found under more than one system."""
    key: str
    occurrences: list[tuple[str, Path]] = field(default_factory=list)

    @property
    def systems(self) -> list[str]:
        return sorted({s for s, _ in self.occurrences})


def _hash_file(path: Path, chunk: int = 1 << 20, start: int = 0) -> Optional[str]:
    """SHA1 the bytes of *path* from offset *start* (no archive unwrapping)."""
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            f.seek(start)
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()
    except OSError:
        return None


def _joined_sha1(digests: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(digests)).encode("ascii")).hexdigest()


def _content_hash(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Return ``(sha1, exact)`` for the *logical* content of a ROM file.

    For raw files ``sha1`` is the file SHA1, taken after the ROM header when
    the file has one (see :mod:`spindoctor.romheaders`), so a headered
    ``.smc`` and an unheadered ``.sfc`` of one game collapse to the same key.
    For archive containers (zip/7z/rar/gz/chd) it is a SHA1 of the sorted
    concatenation of inner-entry SHA1s, each after its ROM header likewise,
    so ``mario.zip`` and ``mario.7z`` containing the same payload collapse to
    the same key. Falls back to the wrapper SHA1 when the optional dep
    needed to peek inside is missing.

    ``exact`` stands for the bytes with their headers: it equals ``sha1``
    when no header was left out, and two files with the same ``sha1`` are
    byte-for-byte copies only when their ``exact`` match too.
    """
    if archives.archive_kind(path) is None:
        try:
            skip = file_header_length(path, path.stat().st_size)
            header = b""
            if skip:
                with open(path, "rb") as f:
                    header = f.read(skip)
        except OSError:
            return None, None
        digest = _hash_file(path, start=skip)
        if digest is None or not skip:
            return digest, digest
        return digest, digest + ":" + hashlib.sha1(header).hexdigest()
    info = archives.extract_inner_hash(path, headerless=True)
    if not info or not info["entries"]:
        # py7zr/rarfile not installed, or unsupported CHD version — fall back
        # to the raw wrapper SHA1 so the user still gets *some* duplicate
        # detection signal.
        wrapper = _hash_file(path)
        return wrapper, wrapper
    inner = [e.get("sha1_headerless") or e["sha1"] for e in info["entries"] if e.get("sha1")]
    if not inner:
        wrapper = _hash_file(path)
        return wrapper, wrapper
    exact = [e["sha1"] for e in info["entries"] if e.get("sha1")]
    return _joined_sha1(inner), _joined_sha1(exact)


def find_duplicates_in_system(
    system_name: str,
    config: Config,
    by_content: bool = False,
) -> list[DuplicateGroup]:
    """Return duplicate groups within one system.

    By default, two files are duplicates when their stems collapse to the
    same normalized title. Pass ``by_content=True`` to additionally pair
    files that share the same SHA1 — useful for catching pure copies that
    were renamed (``mario.zip`` and ``Super Mario.zip`` of identical bytes).
    The SHA1 leaves out a ROM header, so copies that differ only by one
    pair up too; the headered files are then listed in ``headers_ignored``.
    """
    roms = scan_roms(system_name, Path(config.roms_dir))
    groups: list[DuplicateGroup] = []

    by_title: dict[str, list[Path]] = defaultdict(list)
    for info in roms.values():
        by_title[normalize(info.name)].append(info.path)
    for key, paths in by_title.items():
        if len(paths) > 1:
            groups.append(
                DuplicateGroup(
                    key=key, system=system_name,
                    files=sorted(paths), reason="title",
                )
            )

    if by_content:
        # Walk all files (recursive) — some duplicates may live in nested
        # folders that scan_roms() skips when recursive_scan isn't set.
        roms_dir = Path(config.roms_dir) / system_name
        if roms_dir.exists():
            by_size: dict[int, list[Path]] = defaultdict(list)
            for p in roms_dir.rglob("*"):
                if p.is_file():
                    try:
                        by_size[p.stat().st_size].append(p)
                    except OSError:
                        continue
            seen_pairs: set[tuple[Path, ...]] = set()
            # When archives are involved, two files with different *wrapper*
            # sizes can still share the same inner content (e.g. mario.zip and
            # mario.7z compressing the same payload). Bucket archives together
            # and let the content-aware hash do the matching.
            archive_paths: list[Path] = []
            raw_by_size: dict[int, list[Path]] = defaultdict(list)
            for size, paths in by_size.items():
                for p in paths:
                    if archives.archive_kind(p) is not None:
                        archive_paths.append(p)
                    else:
                        # A ROM header makes a copy bigger by its length, so
                        # bucket raw files by their size after the header.
                        raw_by_size[size - file_header_length(p, size)].append(p)
            grouped: list[list[Path]] = list(raw_by_size.values())
            if archive_paths:
                grouped.append(archive_paths)
            for paths in grouped:
                if len(paths) < 2:
                    continue
                by_hash: dict[str, list[Path]] = defaultdict(list)
                exact: dict[Path, Optional[str]] = {}
                for p in paths:
                    digest, exact[p] = _content_hash(p)
                    if digest:
                        by_hash[digest].append(p)
                for digest, hpaths in by_hash.items():
                    if len(hpaths) > 1:
                        sig = tuple(sorted(hpaths))
                        if sig in seen_pairs:
                            continue
                        seen_pairs.add(sig)
                        # Name the files whose header was left out, unless
                        # the copies are byte-for-byte the same anyway.
                        ignored: list[Path] = []
                        if len({exact[p] for p in sig}) > 1:
                            ignored = [p for p in sig if exact[p] != digest]
                        groups.append(
                            DuplicateGroup(
                                key=digest[:12], system=system_name,
                                files=list(sig), reason="content",
                                headers_ignored=ignored,
                            )
                        )

    groups.sort(key=lambda g: (g.reason, g.key))
    return groups


def find_cross_system_duplicates(
    systems: Iterable[str],
    config: Config,
) -> list[CrossSystemMatch]:
    """Return normalized titles that appear under more than one system."""
    by_title: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for sys_name in systems:
        roms = scan_roms(sys_name, Path(config.roms_dir))
        for info in roms.values():
            by_title[normalize(info.name)].append((sys_name, info.path))

    matches: list[CrossSystemMatch] = []
    for key, occ in by_title.items():
        distinct_systems = {s for s, _ in occ}
        if len(distinct_systems) > 1:
            matches.append(CrossSystemMatch(key=key, occurrences=sorted(occ)))
    matches.sort(key=lambda m: m.key)
    return matches
