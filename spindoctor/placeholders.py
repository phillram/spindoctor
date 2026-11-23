"""Which media files only stand in for missing ones.

``spindoctor generate-media`` can put a drawn title on a wheel, or a "No video
found" clip where a game has no video.  HyperSpin shows those like any other
file, but they are not the game's media: audits still count the game as
missing it, and a download or import replaces the stand-in without
``--overwrite``.

Each media folder that holds stand-ins has one or more small list files
(``spindoctor-placeholders*.json``) naming them with their size and SHA1.  A
file is a stand-in only while its name *and size* match its entry, so a file
someone put there by hand is never mistaken for one, and a list that outlived
its files does no harm.  The lists sit beside the files, so they move with the
media folder.  Every staged batch brings a list of its own name, so copying a
batch in by hand keeps the marks of earlier ones.

Standard library only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ._utils import atomic_write_bytes, hash_stream

LIST_PREFIX = "spindoctor-placeholders"
LIST_NAME = LIST_PREFIX + ".json"


@dataclass(frozen=True)
class Placeholder:
    name: str       # file name, as written
    size: int
    sha1: str
    kind: str       # "drawn" (a title on a wheel), "clip" or "picture"
    game: str = ""


def is_list_name(name: str) -> bool:
    low = name.lower()
    return low.startswith(LIST_PREFIX) and low.endswith(".json")


def describe(path: Path, kind: str, game: str = "") -> Placeholder:
    """The entry for *path* as it is now."""
    with open(path, "rb") as fh:
        sha1, _crc, size = hash_stream(fh)
    return Placeholder(path.name, size, sha1 or "", kind, game)


def list_files(folder: Path) -> list[Path]:
    """The stand-in lists in *folder* (usually none)."""
    try:
        with os.scandir(folder) as entries:
            return sorted(Path(e.path) for e in entries if is_list_name(e.name))
    except OSError:
        return []


def read_list(path: Path) -> dict[str, Placeholder]:
    """One list, by lower-case file name.  An unreadable list is an empty one:
    its files then count as real media, which is the safe way round."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("files", []) if isinstance(data, dict) else []
        out = {}
        for row in rows:
            entry = Placeholder(str(row["name"]), int(row["size"]), str(row.get("sha1", "")),
                                str(row.get("kind", "")), str(row.get("game", "")))
            out[entry.name.casefold()] = entry
        return out
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def read(folder: Path) -> dict[str, Placeholder]:
    """Every list in *folder*, merged; by lower-case file name."""
    out: dict[str, Placeholder] = {}
    for path in list_files(folder):
        out.update(read_list(path))
    return out


class PlaceholderIndex:
    """Reads each folder's lists once.  For one operation only: never kept
    across writes."""

    def __init__(self) -> None:
        self._folders: dict[Path, dict[str, Placeholder]] = {}

    def entry(self, path: Path) -> Optional[Placeholder]:
        """The list entry *path* still matches (name and size), or None."""
        path = Path(path)
        listed = self._folders.get(path.parent)
        if listed is None:
            listed = self._folders[path.parent] = read(path.parent)
        entry = listed.get(path.name.casefold())
        if entry is None:
            return None
        try:
            return entry if path.stat().st_size == entry.size else None
        except OSError:
            return None

    def is_placeholder(self, path: Path) -> bool:
        return self.entry(path) is not None


def is_placeholder(path: Path) -> bool:
    """Whether *path* is a stand-in (see :class:`PlaceholderIndex` for many files)."""
    return PlaceholderIndex().is_placeholder(path)


def taken(path: Path) -> bool:
    """Whether real media is at *path*: it exists and isn't a stand-in."""
    return Path(path).exists() and not is_placeholder(path)


def _write(path: Path, entries: Iterable[Placeholder]) -> None:
    rows = [{"name": e.name, "size": e.size, "sha1": e.sha1, "kind": e.kind, "game": e.game}
            for e in sorted(entries, key=lambda e: e.name.casefold())]
    data = {
        "about": "Files SpinDoctor made to stand in for missing media. Missing-media reports "
                 "still count these games. `spindoctor generate-media remove --apply` "
                 "deletes them.",
        "files": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, json.dumps(data, indent=1, ensure_ascii=False).encode("utf-8"))


def record(folder: Path, entries: Iterable[Placeholder], list_name: str = LIST_NAME) -> None:
    """Add *entries* to one of *folder*'s lists.  Entries that match no file any
    more stay: an undo can bring their file back."""
    path = folder / list_name
    listed = read_list(path)
    listed.update({e.name.casefold(): e for e in entries})
    if listed:
        _write(path, listed.values())


def _matches(folder: Path, entry: Placeholder) -> bool:
    try:
        return (folder / entry.name).stat().st_size == entry.size
    except OSError:
        return False


def forget(path: Path) -> None:
    """Take *path* out of its folder's lists: real media is there now."""
    key = path.name.casefold()
    for list_path in list_files(path.parent):
        listed = read_list(list_path)
        if key not in listed:
            continue
        del listed[key]
        if listed:
            _write(list_path, listed.values())
        else:
            try:
                list_path.unlink()
            except OSError:
                _write(list_path, [])


@dataclass
class Removal:
    removed: list[Path]
    changed: list[Path]     # listed, same size, but not the bytes SpinDoctor wrote: left alone
    errors: list[str]


def find(folder: Path, kinds: Optional[Iterable[str]] = None) -> list[tuple[Path, Placeholder]]:
    """The stand-ins in *folder* that are still there, by name."""
    wanted = set(kinds) if kinds is not None else None
    return [(folder / e.name, e) for _key, e in sorted(read(folder).items())
            if (wanted is None or e.kind in wanted) and _matches(folder, e)]


def remove(folder: Path, kinds: Optional[Iterable[str]] = None,
           names: Optional[Iterable[str]] = None, keep: Iterable[Path] = ()) -> Removal:
    """Delete *folder*'s stand-ins of *kinds* (all kinds when None) and, with
    *names*, only those games', but none of *keep*.  The bytes are checked
    first: a file whose SHA1 isn't the listed one is left alone."""
    result = Removal([], [], [])
    wanted = {n.casefold() for n in names} if names is not None else None
    kept = {p.name.casefold() for p in keep}
    for path, entry in find(folder, kinds):
        if wanted is not None and entry.game.casefold() not in wanted:
            continue
        if path.name.casefold() in kept:
            continue
        try:
            if describe(path, entry.kind).sha1 != entry.sha1:
                result.changed.append(path)
                continue
            path.unlink()
        except OSError as exc:
            result.errors.append(f"{path}: {exc}")
            continue
        result.removed.append(path)
        forget(path)
    return result
