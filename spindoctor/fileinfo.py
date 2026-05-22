"""Detailed file metadata: sizes, image dimensions, video duration.

All reads are done with stdlib only — no Pillow, no moviepy.
ffprobe is used for video duration when available; falls back to
reading the MP4/AVI header directly.
"""
from __future__ import annotations

import json
import logging
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

from .config import MEDIA_TYPES
from .database import GameEntry

# Hide the console window when ``ffprobe`` is invoked from the GUI on
# Windows. Without ``CREATE_NO_WINDOW`` the user sees a black ``cmd``
# window flash on every video duration probe — and ``audit`` /
# ``preview`` can call this hundreds of times in a row. 0 elsewhere
# so the flag is a no-op on macOS / Linux.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
from .media import MEDIA_DIR_MAP


def human_size(n: int) -> str:
    """Convert a byte count to a human-readable string."""
    nb = float(n)
    if nb == 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if nb < 1024.0:
            return f"{nb:.1f} {unit}"
        nb /= 1024.0
    return f"{nb:.1f} TB"


# Extensions to try per media type when scanning for existing files
_MEDIA_SEARCH_EXTS: dict[str, list[str]] = {
    "wheel":      [".png", ".jpg", ".jpeg", ".gif"],
    "background": [".jpg", ".jpeg", ".png"],
    "artwork":    [".png", ".jpg", ".jpeg"],
    "title":      [".png", ".jpg", ".jpeg"],
    "snap":       [".png", ".jpg", ".jpeg"],
    "video":      [".mp4", ".avi", ".flv", ".mkv", ".mov"],
    "trailer":    [".mp4", ".avi", ".flv", ".mkv", ".mov"],
    "sound":      [".mp3", ".wav", ".ogg"],
    "theme":      [".zip", ".swf"],
}

_ROM_SEARCH_EXTS = [
    ".zip", ".7z", ".rar",
    ".nes", ".sfc", ".smc", ".md", ".bin", ".smd",
    ".z64", ".n64", ".v64",
    ".gba",
    ".iso", ".cue", ".img",
]


# ─── FileDetail ───────────────────────────────────────────────────────────────

@dataclass
class FileDetail:
    """All known metadata about one file on disk."""
    path: Path
    media_type: str = ""        # 'rom', 'wheel', 'video', etc.
    exists: bool = False
    size_bytes: int = 0
    extension: str = ""
    modified: Optional[datetime] = None

    # Images
    width: Optional[int] = None
    height: Optional[int] = None

    # Video / audio
    duration_seconds: Optional[float] = None

    error: str = ""

    # ── display helpers ───────────────────────────────────────────────────────

    @property
    def size_human(self) -> str:
        return human_size(self.size_bytes)

    @property
    def duration_human(self) -> str:
        if self.duration_seconds is None:
            return "—"
        total = int(self.duration_seconds)
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @property
    def dimensions(self) -> str:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return "—"

    @property
    def modified_str(self) -> str:
        return self.modified.strftime("%Y-%m-%d %H:%M") if self.modified else "—"

    @property
    def detail_str(self) -> str:
        """One combined string for dim / duration column in tables."""
        parts = []
        if self.width and self.height:
            parts.append(f"{self.width}×{self.height}")
        if self.duration_seconds is not None:
            parts.append(self.duration_human)
        return "  ·  ".join(parts) if parts else "—"


# ─── GameFileReport ───────────────────────────────────────────────────────────

@dataclass
class GameFileReport:
    """All scanned file details for one game in one system."""
    game_name: str
    system_name: str
    db_name: str = ""
    db_description: str = ""
    db_year: str = ""
    db_manufacturer: str = ""
    db_genre: str = ""
    db_rating: str = ""
    rom: Optional[FileDetail] = None
    media: dict[str, FileDetail] = field(default_factory=dict)

    @property
    def total_size_bytes(self) -> int:
        total = self.rom.size_bytes if self.rom and self.rom.exists else 0
        for d in self.media.values():
            total += d.size_bytes
        return total

    @property
    def total_size_human(self) -> str:
        return human_size(self.total_size_bytes)

    def missing_media(self) -> list[str]:
        return [t for t in MEDIA_TYPES if not self.media.get(t, FileDetail(path=Path())).exists]

    def present_media(self) -> list[str]:
        return [t for t in MEDIA_TYPES if self.media.get(t, FileDetail(path=Path())).exists]


# ─── scanning ─────────────────────────────────────────────────────────────────

def scan_file(path: Path, media_type: str = "") -> FileDetail:
    """Return a FileDetail populated from the filesystem."""
    detail = FileDetail(path=path, media_type=media_type, extension=path.suffix.lower())

    if not path.exists():
        return detail

    detail.exists = True
    try:
        stat = path.stat()
        detail.size_bytes = stat.st_size
        detail.modified = datetime.fromtimestamp(stat.st_mtime)
    except OSError as e:
        detail.error = str(e)
        return detail

    ext = path.suffix.lower()

    if ext in (".png", ".jpg", ".jpeg"):
        try:
            detail.width, detail.height = (
                _png_dimensions(path) if ext == ".png" else _jpeg_dimensions(path)
            )
        except Exception as exc:
            _log.debug("Couldn't read image dimensions for %s: %s: %s",
                       path.name, type(exc).__name__, exc)

    if ext in (".mp4", ".avi", ".flv", ".mkv", ".mov", ".wmv", ".m4v"):
        try:
            detail.duration_seconds = _video_duration(path)
        except Exception as exc:
            _log.debug("Couldn't read video duration for %s: %s: %s",
                       path.name, type(exc).__name__, exc)

    return detail


def find_media_file(
    game_name: str,
    system_name: str,
    media_type: str,
    media_base: Path,
) -> FileDetail:
    """Locate the actual media file on disk and return its FileDetail.

    Tries each supported extension for the media type.  Returns a
    FileDetail with exists=False pointing to the canonical expected path
    if nothing is found.
    """
    dir_parts = MEDIA_DIR_MAP.get(media_type, (media_type.capitalize(),))
    directory = media_base / system_name / Path(*dir_parts)

    # Special case: theme may be a directory
    if media_type == "theme":
        theme_dir = directory / game_name
        if theme_dir.is_dir():
            d = FileDetail(path=theme_dir, media_type=media_type,
                           extension="<dir>", exists=True)
            try:
                d.size_bytes = _dir_size(theme_dir)
                d.modified = datetime.fromtimestamp(theme_dir.stat().st_mtime)
            except OSError:
                pass
            return d

    exts = _MEDIA_SEARCH_EXTS.get(media_type, [".bin"])
    for ext in exts:
        candidate = directory / f"{game_name}{ext}"
        if candidate.exists():
            return scan_file(candidate, media_type)

    # Not found — return pointer to canonical path
    from .media import MEDIA_EXTENSIONS
    default_ext = MEDIA_EXTENSIONS.get(media_type, exts[0] if exts else "")
    return FileDetail(
        path=directory / f"{game_name}{default_ext}",
        media_type=media_type,
        extension=default_ext,
        exists=False,
    )


def find_rom_file(
    rom_name: str,
    system_name: str,
    roms_base: Path,
) -> FileDetail:
    """Locate a ROM file in the system's ROM directory."""
    system_dir = roms_base / system_name
    if not system_dir.exists():
        return FileDetail(
            path=system_dir / rom_name,
            media_type="rom",
            exists=False,
        )

    for ext in _ROM_SEARCH_EXTS:
        candidate = system_dir / f"{rom_name}{ext}"
        if candidate.exists():
            return scan_file(candidate, "rom")

    # Also try exact name (might already have an extension embedded)
    direct = system_dir / rom_name
    if direct.exists():
        return scan_file(direct, "rom")

    return FileDetail(path=system_dir / rom_name, media_type="rom", exists=False)


def scan_game(
    game_name: str,
    system_name: str,
    roms_base: Path,
    media_base: Path,
    db_entry: Optional["GameEntry"] = None,
    media_types: Optional[list[str]] = None,
) -> GameFileReport:
    """Build a full GameFileReport for one game."""
    report = GameFileReport(game_name=game_name, system_name=system_name)

    if db_entry is not None:
        report.db_name = db_entry.name
        report.db_description = db_entry.description
        report.db_year = db_entry.year
        report.db_manufacturer = db_entry.manufacturer
        report.db_genre = db_entry.genre
        report.db_rating = db_entry.rating

    report.rom = find_rom_file(game_name, system_name, roms_base)

    types = media_types or MEDIA_TYPES
    for mt in types:
        report.media[mt] = find_media_file(game_name, system_name, mt, media_base)

    return report


def scan_system(
    system_name: str,
    roms_base: Path,
    media_base: Path,
    db_games: "dict[str, GameEntry]",
    game_names: Optional[list[str]] = None,
    media_types: Optional[list[str]] = None,
) -> list[GameFileReport]:
    """Scan all (or a subset of) games in a system."""
    names = game_names or sorted(db_games.keys())
    return [
        scan_game(
            name, system_name, roms_base, media_base,
            db_entry=db_games.get(name),
            media_types=media_types,
        )
        for name in names
    ]


# ─── image helpers ────────────────────────────────────────────────────────────

def _png_dimensions(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG")
    width = struct.unpack(">I", header[16:20])[0]
    height = struct.unpack(">I", header[20:24])[0]
    return width, height


def _jpeg_dimensions(path: Path) -> tuple[int, int]:
    """Read width/height from a JPEG by walking the segment markers.

    The SOF marker can sit far past the file header in progressive or
    high-resolution JPEGs with large comment/EXIF segments. We walk
    the segment chain via seek() so we don't have to slurp the whole
    file into memory or guess a buffer size.
    """
    _SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                    0xC9, 0xCA, 0xCB}
    with open(path, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError("Not a JPEG")
        while True:
            byte = f.read(1)
            if not byte:
                break
            if byte != b"\xff":
                # Marker bytes must start with 0xFF; misaligned data
                # means the file is corrupt or not actually a JPEG.
                raise ValueError("Malformed JPEG (missing marker)")
            # Skip any padding 0xFF bytes between segments.
            marker_byte = f.read(1)
            while marker_byte == b"\xff":
                marker_byte = f.read(1)
            if not marker_byte:
                break
            marker = marker_byte[0]
            if marker in _SOF_MARKERS:
                # SOF: 2-byte length, 1-byte precision, 2-byte height,
                # 2-byte width.
                payload = f.read(7)
                if len(payload) < 7:
                    break
                height = struct.unpack(">H", payload[3:5])[0]
                width = struct.unpack(">H", payload[5:7])[0]
                return width, height
            if marker in (0xD8, 0xD9):
                # SOI/EOI carry no payload.
                continue
            seg_len_bytes = f.read(2)
            if len(seg_len_bytes) < 2:
                break
            seg_len = struct.unpack(">H", seg_len_bytes)[0]
            if seg_len < 2:
                break
            f.seek(seg_len - 2, 1)
    raise ValueError("No SOF marker found")


# ─── video helpers ────────────────────────────────────────────────────────────

_ffprobe_ok: Optional[bool] = None


def _has_ffprobe() -> bool:
    global _ffprobe_ok
    if _ffprobe_ok is None:
        try:
            subprocess.run(
                ["ffprobe", "-version"],
                capture_output=True,
                timeout=5,
                creationflags=_CREATE_NO_WINDOW,
            )
            _ffprobe_ok = True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            _ffprobe_ok = False
    return _ffprobe_ok


def reset_ffprobe_cache() -> None:
    """Drop the cached ffprobe-availability flag.

    The flag is set once per process. Tests that patch ``subprocess.run``
    to simulate a missing/present ffprobe must call this before and
    after, otherwise the first test's verdict sticks for the rest of
    the suite.
    """
    global _ffprobe_ok
    _ffprobe_ok = None


def _duration_ffprobe(path: Path) -> Optional[float]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
        data = json.loads(result.stdout)
        raw = data.get("format", {}).get("duration")
        return float(raw) if raw else None
    except Exception:
        return None


def _duration_mp4_native(path: Path) -> Optional[float]:
    """Parse MP4 mvhd atom for duration — no external tools required."""
    try:
        with open(path, "rb") as f:
            data = f.read(1024 * 1024)  # First 1 MB covers most moov boxes
    except OSError:
        return None
    return _walk_boxes(data)


def _walk_boxes(data: bytes) -> Optional[float]:
    i = 0
    while i + 8 <= len(data):
        try:
            size = struct.unpack(">I", data[i:i + 4])[0]
        except struct.error:
            break
        name = data[i + 4:i + 8]

        # An atom's body begins after the header. The header is 8 bytes
        # for the common case (size+type) and 16 bytes when size==1
        # (the 64-bit "extended-size" variant carries an extra
        # 8-byte length immediately after the type).
        header_len = 8
        if size == 0:
            break
        if size == 1:
            if i + 16 <= len(data):
                size = struct.unpack(">Q", data[i + 8:i + 16])[0]
                header_len = 16
            else:
                break

        if name == b"moov":
            return _walk_boxes(data[i + header_len: i + size])

        if name == b"mvhd":
            # mvhd in the wild is never 64-bit (it's <100 bytes), but
            # slicing from the body start keeps both shapes consistent.
            return _parse_mvhd(data[i: i + size])

        if size < header_len:
            break
        i += size
    return None


def _parse_mvhd(box: bytes) -> Optional[float]:
    if len(box) < 28:
        return None
    version = box[8]
    if version == 0:
        timescale = struct.unpack(">I", box[20:24])[0]
        duration = struct.unpack(">I", box[24:28])[0]
    else:
        # version 1: 8-byte ctime, mtime, 4-byte timescale, 8-byte duration
        if len(box) < 40:
            return None
        timescale = struct.unpack(">I", box[28:32])[0]
        duration = struct.unpack(">Q", box[32:40])[0]
    return (duration / timescale) if timescale else None


def _video_duration(path: Path) -> Optional[float]:
    if _has_ffprobe():
        result = _duration_ffprobe(path)
        if result is not None:
            return result
    if path.suffix.lower() in (".mp4", ".m4v", ".mov"):
        return _duration_mp4_native(path)
    return None


# ─── utility ──────────────────────────────────────────────────────────────────

def _dir_size(path: Path) -> int:
    # Single source of truth — backup.py and migrate.py import this rather
    # than carrying their own copies. Tolerates a missing path and skips
    # files the OS refuses to stat (permission errors on Windows cabinets
    # with leftover read-only attributes are common enough to be worth
    # swallowing rather than aborting a 50 GB backup pre-flight).
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total
