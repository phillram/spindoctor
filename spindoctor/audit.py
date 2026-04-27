"""Audit and scan logic for SpinDoctor."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config, MEDIA_TYPES, get_rom_extensions
from .database import GameEntry, HyperspinDatabase, load_database


@dataclass
class RomFileInfo:
    name: str
    path: Path
    extension: str


@dataclass
class MediaStatus:
    wheel: bool = False
    background: bool = False
    artwork: bool = False
    video: bool = False
    sound: bool = False
    theme: bool = False

    def missing(self) -> list[str]:
        return [t for t in MEDIA_TYPES if not getattr(self, t, False)]

    def has_all(self) -> bool:
        return all(getattr(self, t, False) for t in MEDIA_TYPES)


@dataclass
class GameAuditEntry:
    rom_name: str
    in_database: bool
    rom_exists: bool
    db_entry: Optional[GameEntry]
    media: MediaStatus = field(default_factory=MediaStatus)
    missing_metadata: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return (
            not self.in_database
            or not self.rom_exists
            or bool(self.missing_metadata)
            or not self.media.has_all()
        )


@dataclass
class SystemAuditResult:
    system_name: str
    total_roms: int = 0
    total_db_entries: int = 0
    roms_in_db: int = 0
    roms_not_in_db: int = 0
    db_entries_no_rom: int = 0
    entries: list[GameAuditEntry] = field(default_factory=list)

    @property
    def roms_only(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.rom_exists and not e.in_database]

    @property
    def db_only(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.in_database and not e.rom_exists]

    @property
    def missing_metadata_entries(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.missing_metadata]

    @property
    def missing_media_entries(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.in_database and e.media.missing()]

    @property
    def matched(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.rom_exists and e.in_database]


def scan_roms(system_name: str, roms_dir: Path) -> dict[str, RomFileInfo]:
    """Scan the ROM directory for a system and return a dict keyed by stem name."""
    system_rom_dir = roms_dir / system_name
    if not system_rom_dir.exists():
        return {}

    extensions = get_rom_extensions(system_name)
    roms: dict[str, RomFileInfo] = {}

    for rom_path in system_rom_dir.iterdir():
        if rom_path.is_file() and rom_path.suffix.lower() in extensions:
            roms[rom_path.stem] = RomFileInfo(
                name=rom_path.stem,
                path=rom_path,
                extension=rom_path.suffix.lower(),
            )
    return roms


def check_media(
    game_name: str,
    system_name: str,
    media_base: Path,
) -> MediaStatus:
    """Check which media assets exist for a game."""
    media_system_dir = media_base / system_name
    status = MediaStatus()

    wheel_dir = media_system_dir / "Images" / "Wheel"
    bg_dir = media_system_dir / "Images" / "Backgrounds"
    artwork_dir = media_system_dir / "Images" / "Artwork1"
    video_dir = media_system_dir / "Video"
    sound_dir = media_system_dir / "Sound"
    theme_dir = media_system_dir / "Themes"

    img_exts = {".png", ".jpg", ".jpeg"}
    video_exts = {".mp4", ".avi", ".flv"}
    sound_exts = {".mp3", ".wav", ".ogg"}

    status.wheel = _file_exists(wheel_dir, game_name, img_exts)
    status.background = _file_exists(bg_dir, game_name, img_exts)
    status.artwork = _file_exists(artwork_dir, game_name, img_exts)
    status.video = _file_exists(video_dir, game_name, video_exts)
    status.sound = _file_exists(sound_dir, game_name, sound_exts)
    status.theme = (theme_dir / game_name).exists() or _file_exists(
        theme_dir, game_name, {".zip", ".swf"}
    )

    return status


def _file_exists(directory: Path, stem: str, extensions: set[str]) -> bool:
    if not directory.exists():
        return False
    for ext in extensions:
        if (directory / f"{stem}{ext}").exists():
            return True
    return False


def audit_system(
    system_name: str,
    config: Config,
    check_media_flag: bool = True,
) -> SystemAuditResult:
    """Full audit of a system: ROMs vs database vs media."""
    result = SystemAuditResult(system_name=system_name)

    roms = scan_roms(system_name, Path(config.roms_dir))
    db = load_database(system_name, config.databases_dir)
    db_games = db.games()

    result.total_roms = len(roms)
    result.total_db_entries = len(db_games)

    all_names = set(roms.keys()) | set(db_games.keys())

    for name in all_names:
        rom_exists = name in roms
        in_database = name in db_games
        db_entry = db_games.get(name)

        if check_media_flag and config.hyperspin_dir:
            media = check_media(name, system_name, config.media_dir)
        else:
            media = MediaStatus()

        missing_meta = db_entry.missing_fields() if db_entry else []

        entry = GameAuditEntry(
            rom_name=name,
            in_database=in_database,
            rom_exists=rom_exists,
            db_entry=db_entry,
            media=media,
            missing_metadata=missing_meta,
        )
        result.entries.append(entry)

    result.roms_in_db = sum(1 for e in result.entries if e.rom_exists and e.in_database)
    result.roms_not_in_db = sum(1 for e in result.entries if e.rom_exists and not e.in_database)
    result.db_entries_no_rom = sum(1 for e in result.entries if e.in_database and not e.rom_exists)

    result.entries.sort(key=lambda e: e.rom_name.lower())
    return result


def build_stub_entry(rom_name: str) -> GameEntry:
    """Create a minimal stub GameEntry from a ROM filename."""
    description = rom_name.replace("_", " ").replace("-", " ")
    parts = description.split("(")
    clean_name = parts[0].strip()
    return GameEntry(name=rom_name, description=clean_name)
