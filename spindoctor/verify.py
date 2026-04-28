"""ROM integrity verification against No-Intro / Redump DAT files.

A *DAT* file is the standard XML manifest format published by No-Intro,
Redump, and TOSEC that lists known-good ROMs along with their CRC32,
MD5, and SHA1 hashes. This module reads a DAT and verifies that every
ROM file in a system folder either:

* matches a known entry exactly (good)
* has a hash collision with a different name (renamed copy)
* is unknown to the DAT (homebrew, hack, bad dump)

DAT format (simplified)::

    <datafile>
      <header><name>...</name></header>
      <game name="Title">
        <rom name="Title.nes" size="262144" crc="abcd1234"
             md5="..." sha1="..."/>
      </game>
    </datafile>

The verifier reads the DAT's ``rom`` entries and matches by SHA1 first,
then CRC32, then size+name as a fallback. Hashing is done lazily — no
per-file SHA1 unless the size already matched something in the DAT.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import archives


@dataclass(frozen=True)
class DatEntry:
    game_name: str
    rom_name: str
    size: int
    crc: Optional[str]
    sha1: Optional[str]


@dataclass
class VerifyEntry:
    path: Path
    status: str          # "good" | "renamed" | "bad" | "unknown"
    expected_name: Optional[str] = None
    detail: str = ""


@dataclass
class VerifyReport:
    system: str
    dat_path: Path
    entries: list[VerifyEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def parse_dat(dat_path: Path) -> list[DatEntry]:
    """Parse a No-Intro / Redump DAT file into a list of ``DatEntry``.

    Tolerant of missing hashes — a real-world DAT may carry only CRC for
    older systems or only SHA1 for Redump CD images.
    """
    tree = ET.parse(dat_path)
    root = tree.getroot()
    entries: list[DatEntry] = []
    for game in root.iter("game"):
        game_name = game.get("name", "")
        for rom in game.iter("rom"):
            try:
                size = int(rom.get("size", "0") or "0")
            except ValueError:
                size = 0
            entries.append(DatEntry(
                game_name=game_name,
                rom_name=rom.get("name", ""),
                size=size,
                crc=(rom.get("crc") or "").lower() or None,
                sha1=(rom.get("sha1") or "").lower() or None,
            ))
    return entries


def _index(entries: Iterable[DatEntry]) -> dict[str, dict]:
    """Group entries by lookup key for fast hash matching."""
    by_sha1: dict[str, DatEntry] = {}
    by_crc: dict[str, DatEntry] = {}
    by_size: dict[int, list[DatEntry]] = {}
    by_name: dict[str, DatEntry] = {}
    for e in entries:
        if e.sha1:
            by_sha1[e.sha1] = e
        if e.crc:
            by_crc[e.crc] = e
        if e.size:
            by_size.setdefault(e.size, []).append(e)
        if e.rom_name:
            by_name[e.rom_name.lower()] = e
    return {"sha1": by_sha1, "crc": by_crc, "size": by_size, "name": by_name}


def _hash_file(path: Path, want_sha1: bool, want_crc: bool) -> tuple[Optional[str], Optional[str]]:
    sha1 = hashlib.sha1() if want_sha1 else None
    crc = 0
    try:
        with open(path, "rb") as f:
            while True:
                buf = f.read(1 << 20)
                if not buf:
                    break
                if sha1:
                    sha1.update(buf)
                if want_crc:
                    crc = zlib.crc32(buf, crc)
    except OSError:
        return None, None
    sha1_hex = sha1.hexdigest() if sha1 else None
    crc_hex = f"{crc & 0xFFFFFFFF:08x}" if want_crc else None
    return sha1_hex, crc_hex


def _classify_archive(path: Path, index: dict[str, dict]) -> VerifyEntry:
    """Verify an archive by hashing its inner contents instead of the wrapper.

    For multi-entry archives (zip/7z/rar) any inner SHA1 hit promotes the file
    to ``good`` (or ``renamed`` if the inner filename differs from the DAT
    entry). CHDs carry a single ``rawsha1`` in their header that DATs match
    against directly. Missing optional dependencies degrade to ``unknown``
    with a one-line install hint.
    """
    info = archives.extract_inner_hash(path)
    if info is None:
        # Defensive — caller already gated on archive_kind, so this only fires
        # if the extension table and the dispatcher disagree.
        return VerifyEntry(path=path, status="unknown", detail="not an archive")

    if info["error"] and not info["entries"]:
        return VerifyEntry(path=path, status="unknown", detail=info["error"])

    matches: list[tuple[dict, "DatEntry"]] = []
    for entry in info["entries"]:
        sha1_hex = (entry.get("sha1") or "").lower() or None
        crc_hex = (entry.get("crc32") or "").lower() or None
        match = None
        if sha1_hex and sha1_hex in index["sha1"]:
            match = index["sha1"][sha1_hex]
        elif crc_hex and crc_hex in index["crc"]:
            match = index["crc"][crc_hex]
        if match is not None:
            matches.append((entry, match))

    if not matches:
        names = ", ".join(e.get("name", "?") for e in info["entries"]) or "(empty)"
        return VerifyEntry(
            path=path, status="unknown",
            detail=f"{info['kind']}: no inner entry matches DAT ({names})",
        )

    # Promote to "good" if either the wrapper filename or any inner entry name
    # matches the DAT entry name; otherwise "renamed".
    inner_entry, dat_match = matches[0]
    inner_name = (inner_entry.get("name") or "").lower()
    dat_name = dat_match.rom_name.lower()
    wrapper_stem = path.stem.lower()
    dat_stem = Path(dat_match.rom_name).stem.lower()

    if info["kind"] == "chd":
        # CHD DAT entries reference the .chd filename directly.
        if path.name.lower() == dat_name:
            return VerifyEntry(
                path=path, status="good", expected_name=dat_match.rom_name,
                detail="chd rawsha1 match",
            )
        return VerifyEntry(
            path=path, status="renamed", expected_name=dat_match.rom_name,
            detail=f"chd rawsha1 match — DAT calls it '{dat_match.rom_name}'",
        )

    if inner_name == dat_name or wrapper_stem == dat_stem:
        return VerifyEntry(
            path=path, status="good", expected_name=dat_match.rom_name,
            detail=f"{info['kind']}: inner sha1 match",
        )
    return VerifyEntry(
        path=path, status="renamed", expected_name=dat_match.rom_name,
        detail=(
            f"{info['kind']}: inner sha1 match — DAT calls it "
            f"'{dat_match.rom_name}'"
        ),
    )


def _classify(
    path: Path,
    index: dict[str, dict],
) -> VerifyEntry:
    if archives.archive_kind(path) is not None:
        return _classify_archive(path, index)

    try:
        size = path.stat().st_size
    except OSError as e:
        return VerifyEntry(path=path, status="unknown", detail=f"stat failed: {e}")

    candidates = index["size"].get(size, [])
    if not candidates:
        # Size doesn't match anything in the DAT → either a bad dump or
        # something the DAT doesn't know about. Don't bother hashing.
        named = index["name"].get(path.name.lower())
        if named:
            return VerifyEntry(
                path=path, status="bad",
                expected_name=named.rom_name,
                detail=f"name match but size {size} ≠ {named.size}",
            )
        return VerifyEntry(path=path, status="unknown", detail=f"size {size} not in DAT")

    want_sha1 = any(c.sha1 for c in candidates)
    want_crc = any(c.crc for c in candidates)
    sha1_hex, crc_hex = _hash_file(path, want_sha1, want_crc)

    if sha1_hex and sha1_hex in index["sha1"]:
        match = index["sha1"][sha1_hex]
        if path.name.lower() == match.rom_name.lower():
            return VerifyEntry(path=path, status="good", expected_name=match.rom_name)
        return VerifyEntry(
            path=path, status="renamed", expected_name=match.rom_name,
            detail=f"sha1 match — DAT calls it '{match.rom_name}'",
        )

    if crc_hex and crc_hex in index["crc"]:
        match = index["crc"][crc_hex]
        if path.name.lower() == match.rom_name.lower():
            return VerifyEntry(path=path, status="good", expected_name=match.rom_name)
        return VerifyEntry(
            path=path, status="renamed", expected_name=match.rom_name,
            detail=f"crc match — DAT calls it '{match.rom_name}'",
        )

    # Size matched but hashes didn't — likely a bad dump.
    expected = candidates[0]
    return VerifyEntry(
        path=path, status="bad",
        expected_name=expected.rom_name,
        detail=f"size matches '{expected.rom_name}' but hash differs",
    )


def verify_system(system_name: str, dat_path: Path, roms_dir: Path) -> VerifyReport:
    """Verify every ROM under ``roms_dir/system_name`` against ``dat_path``."""
    report = VerifyReport(system=system_name, dat_path=dat_path)
    sys_dir = roms_dir / system_name
    if not sys_dir.exists():
        return report

    index = _index(parse_dat(dat_path))

    for path in sorted(sys_dir.rglob("*")):
        if not path.is_file():
            continue
        # Skip our own manifests
        if path.name.startswith(("_spindoctor-", ".")):
            continue
        report.entries.append(_classify(path, index))

    for e in report.entries:
        report.summary[e.status] = report.summary.get(e.status, 0) + 1
    return report
