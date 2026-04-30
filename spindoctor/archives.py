"""Archive-aware hashing for ROM verification and duplicate detection.

ROM sets in the wild are distributed inside a variety of archive containers:

* ``.zip`` — universal default, supported by Python's stdlib.
* ``.7z``  — common for MAME, full-set redistributions.
* ``.rar`` — legacy scene releases.
* ``.gz``  — single-file gzip wrappers (some scene releases of small ROMs).
* ``.chd`` — MAME / Redump compressed disc image (Saturn, Dreamcast, Sega CD,
  optionally PSX). CHDs carry a ``rawsha1`` of the uncompressed disc data in
  their header — that is what DAT files compare against, so we read the SHA1
  directly out of the header rather than decompressing.

The 7z and RAR readers are *soft* dependencies: ``py7zr`` and ``rarfile`` are
imported lazily and missing imports degrade to a structured ``error`` field on
the returned dict so callers can hint the user toward
``pip install -e .[archives]``. This mirrors the ``lxml`` pattern in
``spindoctor.database``.

Public surface
--------------
* :func:`is_archive` — extension check (cheap).
* :func:`archive_kind` — extension-based normalisation to ``"zip" | "7z" |
  "rar" | "gz" | "chd"`` or ``None``.
* :func:`extract_inner_hash` — open the archive and return SHA1/CRC32/size for
  each inner entry (or a single CHD logical entry).
* :func:`support_status` — table of ``{kind: (available, hint)}`` used by the
  ``doctor`` command to render archive support.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any, Optional

# Extensions we know about. Matched case-insensitively.
_KIND_BY_EXT = {
    ".zip": "zip",
    ".7z": "7z",
    ".rar": "rar",
    ".gz": "gz",
    ".chd": "chd",
}


def is_archive(path: Path) -> bool:
    """Return True if *path* has an archive extension we know about."""
    return archive_kind(path) is not None


def archive_kind(path: Path) -> Optional[str]:
    """Map a path's extension to one of our supported archive kinds, or None."""
    return _KIND_BY_EXT.get(path.suffix.lower())


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def support_status() -> dict[str, tuple[bool, Optional[str]]]:
    """Return ``{kind: (available, hint)}`` for every supported archive kind.

    ``hint`` is a short installation suggestion when ``available`` is False.
    Used by :func:`spindoctor.health.check_archive_support` so ``spindoctor
    doctor`` can render a one-line summary.
    """
    py7zr = _try_import("py7zr")
    rarfile = _try_import("rarfile")
    return {
        "zip": (True, None),                                      # stdlib
        "gz": (True, None),                                       # stdlib
        "chd": (True, None),                                      # native parser
        "7z": (py7zr is not None, "pip install py7zr"),
        "rar": (rarfile is not None, "pip install rarfile"),
    }


# ─── inner-hash extraction ────────────────────────────────────────────────────


_CHUNK = 1 << 20  # 1 MiB streaming chunk


def _hash_stream(stream) -> tuple[str, str, int]:
    """Stream a binary file-like into ``(sha1_hex, crc32_hex, size)``."""
    sha1 = hashlib.sha1()
    crc = 0
    size = 0
    while True:
        buf = stream.read(_CHUNK)
        if not buf:
            break
        sha1.update(buf)
        crc = zlib.crc32(buf, crc)
        size += len(buf)
    return sha1.hexdigest(), f"{crc & 0xFFFFFFFF:08x}", size


def _zip_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info) as f:
                sha1_hex, crc_hex, size = _hash_stream(f)
            # zipfile already exposes a CRC32 field; trust ours since we just
            # streamed the bytes.
            entries.append({
                "name": info.filename,
                "size": size,
                "sha1": sha1_hex,
                "crc32": crc_hex,
            })
    return entries


def _gz_entries(path: Path) -> list[dict[str, Any]]:
    # gzip wraps a single file; the original name lives in the header but is
    # optional. Fall back to stripping the ``.gz`` suffix when missing.
    inner_name = path.stem
    with gzip.open(path, "rb") as f:
        sha1_hex, crc_hex, size = _hash_stream(f)
    return [{
        "name": inner_name,
        "size": size,
        "sha1": sha1_hex,
        "crc32": crc_hex,
    }]


def _sevenz_entries(path: Path) -> list[dict[str, Any]]:
    py7zr = _try_import("py7zr")
    if py7zr is None:
        raise ModuleNotFoundError("py7zr")

    # py7zr's preferred reading API is ``extract(factory=WriterFactory)`` which
    # streams each inner file through our hasher without materialising it.
    # That keyword arg only exists in py7zr >= 1.0, which dropped Python 3.8;
    # the latest 3.8-compatible release (0.22.x — needed for the Win 7 build)
    # still ships ``readall()`` returning name -> BytesIO. We try the modern
    # path first and fall back when the kwarg is rejected.
    class _Hasher:
        def __init__(self) -> None:
            self.sha1 = hashlib.sha1()
            self.crc = 0
            self.length = 0

        def write(self, s: bytes) -> int:  # noqa: D401 - Py7zIO contract
            self.sha1.update(s)
            self.crc = zlib.crc32(s, self.crc)
            self.length += len(s)
            return len(s)

        def read(self, size: Optional[int] = None) -> bytes:
            return b""

        def seek(self, offset: int, whence: int = 0) -> int:
            return self.length

        def flush(self) -> None:
            pass

        def size(self) -> int:
            return self.length

    class _Factory:
        def __init__(self) -> None:
            self.hashers: dict[str, _Hasher] = {}

        def create(self, filename: str):
            h = _Hasher()
            self.hashers[filename] = h
            return h

    factory = _Factory()
    hashers: dict[str, _Hasher] = factory.hashers
    with py7zr.SevenZipFile(path, mode="r") as zf:  # type: ignore[union-attr]
        try:
            zf.extract(factory=factory)
        except TypeError:
            # Old py7zr (<= 0.22): no factory kwarg. Use readall() — loads each
            # entry into a BytesIO, but it's the only inner-content API there.
            zf.reset()
            data = zf.readall() or {}
            for name, buf in data.items():
                h = _Hasher()
                for chunk in iter(lambda: buf.read(1 << 20), b""):
                    h.write(chunk)
                hashers[name] = h

    entries: list[dict[str, Any]] = []
    for name, h in hashers.items():
        entries.append({
            "name": name,
            "size": h.length,
            "sha1": h.sha1.hexdigest(),
            "crc32": f"{h.crc & 0xFFFFFFFF:08x}",
        })
    return entries


def _rar_entries(path: Path) -> list[dict[str, Any]]:
    rarfile = _try_import("rarfile")
    if rarfile is None:
        raise ModuleNotFoundError("rarfile")
    entries: list[dict[str, Any]] = []
    with rarfile.RarFile(path) as rf:  # type: ignore[union-attr]
        for info in rf.infolist():
            if info.isdir():
                continue
            with rf.open(info) as f:
                sha1_hex, crc_hex, size = _hash_stream(f)
            entries.append({
                "name": info.filename,
                "size": size,
                "sha1": sha1_hex,
                "crc32": crc_hex,
            })
    return entries


# ─── CHD header parsing ──────────────────────────────────────────────────────
#
# CHD header layout, from MAME's ``src/lib/util/chd.cpp``::
#
#   Bytes  0..7    tag:    b"MComprHD"
#   Bytes  8..11   length  (uint32 BE) — header length in bytes
#   Bytes 12..15   version (uint32 BE) — supported: 3, 4, 5
#
# Per-version offsets to the *raw* SHA1 (uncompressed disc/HD data):
#   v3 → 60   (20 bytes, big-endian binary SHA1)
#   v4 → 48   (called "raw sha1" in v4)
#   v5 → 84   ("rawsha1")
#
# The "rawsha1" is what MAME / Redump store in their DAT files for CHD games.

_CHD_TAG = b"MComprHD"
_CHD_RAW_SHA1_OFFSET = {
    3: 60,
    4: 48,
    5: 84,
}


def _chd_entries(path: Path) -> list[dict[str, Any]]:
    """Parse a CHD header and return a single logical entry with ``rawsha1``.

    Raises ``ValueError`` for unsupported / malformed CHDs. Caller maps that
    to ``error`` in the result dict.
    """
    with open(path, "rb") as f:
        head = f.read(16)
    if len(head) < 16 or head[:8] != _CHD_TAG:
        raise ValueError("not a CHD file (missing MComprHD tag)")
    length = struct.unpack(">I", head[8:12])[0]
    version = struct.unpack(">I", head[12:16])[0]
    if version not in _CHD_RAW_SHA1_OFFSET:
        raise ValueError(f"unsupported CHD version {version} (need v3/v4/v5)")
    sha1_offset = _CHD_RAW_SHA1_OFFSET[version]
    if length < sha1_offset + 20:
        raise ValueError(f"CHD v{version} header too short ({length} bytes)")
    with open(path, "rb") as f:
        f.seek(sha1_offset)
        raw = f.read(20)
    if len(raw) < 20:
        raise ValueError("CHD header truncated before rawsha1")
    sha1_hex = raw.hex()
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return [{
        "name": path.name,
        "size": size,
        "sha1": sha1_hex,
        "crc32": None,
        "chd_version": version,
    }]


# ─── public dispatch ──────────────────────────────────────────────────────────


def extract_inner_hash(path: Path) -> Optional[dict[str, Any]]:
    """Read *path* and return ``{kind, entries, error}`` (or None for non-archives).

    ``entries`` is a list of ``{name, size, sha1, crc32}`` dicts:

    * for ``zip``/``7z``/``rar`` it lists every inner file
    * for ``gz``  it has exactly one entry (the wrapped file)
    * for ``chd`` it has exactly one entry whose ``sha1`` is the CHD's
      ``rawsha1`` (uncompressed disc data) read from the header

    On a soft-dependency miss (``py7zr``/``rarfile``) ``entries`` is empty and
    ``error`` is populated. On a hard parse failure ``entries`` is empty and
    ``error`` carries the exception message.
    """
    kind = archive_kind(path)
    if kind is None:
        return None

    result: dict[str, Any] = {"kind": kind, "entries": [], "error": None}

    try:
        if kind == "zip":
            result["entries"] = _zip_entries(path)
        elif kind == "gz":
            result["entries"] = _gz_entries(path)
        elif kind == "7z":
            try:
                result["entries"] = _sevenz_entries(path)
            except ModuleNotFoundError:
                result["error"] = (
                    "py7zr not installed — install with "
                    "`pip install -e .[archives]` to verify .7z files"
                )
        elif kind == "rar":
            try:
                result["entries"] = _rar_entries(path)
            except ModuleNotFoundError:
                result["error"] = (
                    "rarfile not installed — install with "
                    "`pip install -e .[archives]` to verify .rar files"
                )
        elif kind == "chd":
            result["entries"] = _chd_entries(path)
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error) as e:
        result["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # pragma: no cover — last-resort guard
        # py7zr / rarfile raise their own exception types; we don't import
        # them eagerly so we can't catch them by name. Stringify and move on.
        result["error"] = f"{type(e).__name__}: {e}"

    return result
