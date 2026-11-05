"""Lossless Windows text reads and atomic edits shared by cabinet writers."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ._utils import atomic_write_bytes


def read_windows_text_with_encoding(path: Path) -> tuple[str, str]:
    """Keep byte order, BOM and newlines; refuse damaged UTF-16."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16-le" if data.startswith(b"\xff\xfe") else "utf-16-be"
        return data.decode(encoding), encoding
    try:
        encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
        return data.decode(encoding), encoding
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="surrogateescape"), "cp1252"


def read_editable_text(path: Path) -> str:
    """Lossless text without a BOM character interfering with first-line keys."""
    return read_windows_text_with_encoding(path)[0].lstrip("\ufeff")


def read_windows_text(path: Path) -> str:
    """Printable read-only diagnostics, including damaged legacy text."""
    try:
        text, encoding = read_windows_text_with_encoding(path)
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-16", errors="replace").lstrip("\ufeff")
    if encoding == "cp1252":
        text = text.encode(encoding, errors="surrogateescape").decode(encoding, errors="replace")
    return text.lstrip("\ufeff")


def write_windows_text(path: Path, text: str, source: Optional[Path] = None) -> None:
    """Write exact text atomically, retaining an existing source's encoding/BOM."""
    original = source or path
    encoding = "utf-8"
    bom = ""
    if original.exists():
        old, encoding = read_windows_text_with_encoding(original)
        if old.startswith("\ufeff"):
            bom = "\ufeff"
    # utf-8-sig supplies its own BOM. UTF-16 endian codecs need it explicitly.
    if encoding == "utf-8-sig":
        bom = ""
    payload = (bom + text.lstrip("\ufeff")).encode(encoding, errors="surrogateescape")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, payload)
