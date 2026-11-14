"""ROM headers that are not part of the game data.

Some cartridge dumps start with a header written by a backup copier or an
emulator file format. The game data after it is the same as in a dump without
one, so two copies of one game can differ only by that header:

* SNES (``.smc``, ``.sfc``, ``.swc``, ``.fig``): a 512-byte copier header
  (Super Magicom, Super Wild Card, Pro Fighter). Cartridge data comes in whole
  KiB, so a file 512 bytes over a multiple of 1024 has one.
* NES (``.nes``): the 16-byte iNES / NES 2.0 header, starting ``NES\\x1a``.
* Famicom Disk System (``.fds``): the 16-byte fwNES header, starting
  ``FDS\\x1a``.

Only the extension of a name is looked at, so the same rules apply to raw files
and to the entries inside an archive.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Optional

SNES_EXTENSIONS = frozenset({".smc", ".sfc", ".swc", ".fig"})
_SNES_HEADER = 512
_MAGIC = {".nes": b"NES\x1a", ".fds": b"FDS\x1a"}
_MAGIC_HEADER = 16
HEAD_BYTES = 16  # how much of a file's start header_length() needs


def _extension(name: str) -> str:
    # Archive entries use "/" and Windows paths "\": take the last part either way.
    return PurePosixPath(name.replace("\\", "/")).suffix.lower()


def header_length(name: str, size: int, head: bytes) -> int:
    """Return how many bytes at the start of a ROM are a header (0 for none).

    *name* is the file or archive-entry name (only its extension is used),
    *size* the whole size in bytes and *head* its first :data:`HEAD_BYTES`
    bytes (SNES needs none). A header is never the whole file.
    """
    ext = _extension(name)
    if ext in SNES_EXTENSIONS:
        if size > _SNES_HEADER and size % 1024 == _SNES_HEADER:
            return _SNES_HEADER
        return 0
    magic = _MAGIC.get(ext)
    if magic is not None and size > _MAGIC_HEADER and head[:len(magic)] == magic:
        return _MAGIC_HEADER
    return 0


def file_header_length(path: Path, size: int) -> int:
    """:func:`header_length` for a file on disk of *size* bytes.

    Reads the first bytes only for the extensions whose header has a magic
    number; an unreadable file has no header.
    """
    ext = _extension(path.name)
    if ext in SNES_EXTENSIONS:
        return header_length(path.name, size, b"")
    if ext not in _MAGIC:
        return 0
    try:
        with open(path, "rb") as f:
            head = f.read(HEAD_BYTES)
    except OSError:
        return 0
    return header_length(path.name, size, head)


class HeaderlessSHA1:
    """SHA1 of a ROM's data after its header, fed in chunks of any size.

    A stream's size is known only at its end, and the SNES rule needs it, so
    the bytes after the longest possible header are hashed as they come and
    :meth:`hexdigest` decides. Names that can't carry a header cost nothing.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        ext = _extension(name)
        if ext in SNES_EXTENSIONS:
            self._skip = _SNES_HEADER
        elif ext in _MAGIC:
            self._skip = _MAGIC_HEADER
        else:
            self._skip = 0
        self._sha1 = hashlib.sha1() if self._skip else None
        self._head = b""
        self._size = 0

    def update(self, data: bytes) -> None:
        if self._sha1 is None:
            return
        if len(self._head) < HEAD_BYTES:
            self._head += bytes(data[:HEAD_BYTES - len(self._head)])
        start = self._skip - self._size
        if start < len(data):
            self._sha1.update(memoryview(data)[max(start, 0):])
        self._size += len(data)

    def hexdigest(self) -> Optional[str]:
        """The SHA1 after the header, or None when the data has no header."""
        if self._sha1 is None or not header_length(self._name, self._size, self._head):
            return None
        return self._sha1.hexdigest()
