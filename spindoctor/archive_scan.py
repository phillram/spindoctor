"""Scan ROM archives for inner-extension mismatches against RocketLauncher config."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set

_ARCHIVE_SUFFIXES = frozenset({".zip", ".7z", ".rar"})


@dataclass
class ArchiveExtMismatch:
    archive_name: str
    inner_extensions: list[str]
    unknown_extensions: list[str]


@dataclass
class SystemExtScanResult:
    system_name: str
    rom_dir: Path
    configured_extensions: Optional[Set[str]]
    archives_scanned: int = 0
    mismatches: list[ArchiveExtMismatch] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def has_mismatches(self) -> bool:
        return bool(self.mismatches)


def _inner_extensions_zip(path: Path) -> list[str]:
    with zipfile.ZipFile(path, "r") as z:
        return sorted({
            Path(n).suffix.lower().lstrip(".")
            for n in z.namelist()
            if not n.endswith("/") and Path(n).suffix
        })


def _inner_extensions_7z(path: Path) -> list[str]:
    import py7zr  # optional dep: spindoctor[archives]
    with py7zr.SevenZipFile(path, mode="r") as z:
        return sorted({
            Path(n).suffix.lower().lstrip(".")
            for n in z.getnames()
            if Path(n).suffix
        })


def _inner_extensions_rar(path: Path) -> list[str]:
    import rarfile  # optional dep: spindoctor[archives]
    with rarfile.RarFile(path) as z:
        return sorted({
            Path(n).suffix.lower().lstrip(".")
            for n in z.namelist()
            if not n.endswith("/") and Path(n).suffix
        })


def _peek_archive(path: Path) -> Optional[list[str]]:
    """Return extensions of files inside *path*. Returns None on error or unsupported format."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            return _inner_extensions_zip(path)
        if suffix == ".7z":
            return _inner_extensions_7z(path)
        if suffix == ".rar":
            return _inner_extensions_rar(path)
    except Exception:
        return None
    return None


def scan_system_archive_extensions(
    system_name: str,
    rom_dir: Path,
    configured_extensions: Optional[Set[str]],
) -> SystemExtScanResult:
    """Scan *rom_dir* for archives whose inner files have extensions not in *configured_extensions*.

    When *configured_extensions* is None (RocketLauncher config unavailable), the scan still
    runs and reports every extension found — the caller should note no comparison was possible.
    """
    result = SystemExtScanResult(
        system_name=system_name,
        rom_dir=rom_dir,
        configured_extensions=configured_extensions,
    )

    if not rom_dir.exists():
        return result

    for f in sorted(rom_dir.iterdir()):
        if f.suffix.lower() not in _ARCHIVE_SUFFIXES:
            continue
        result.archives_scanned += 1
        inner = _peek_archive(f)
        if inner is None:
            result.scan_errors.append(f.name)
            continue
        if not inner:
            continue

        if configured_extensions is not None:
            unknown = [e for e in inner if e and e not in configured_extensions]
        else:
            unknown = inner

        if unknown:
            result.mismatches.append(ArchiveExtMismatch(
                archive_name=f.name,
                inner_extensions=inner,
                unknown_extensions=unknown,
            ))

    return result
