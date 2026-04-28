"""Audit and scan logic for SpinDoctor."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config, MEDIA_TYPES, get_rom_extensions, get_system_overrides
from .database import GameEntry, load_database
from .romutils import clean_display_name, derive_pc_title, find_best_match


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
    title: bool = False
    snap: bool = False
    video: bool = False
    trailer: bool = False
    sound: bool = False
    theme: bool = False

    def missing(self) -> list[str]:
        return [t for t in MEDIA_TYPES if not getattr(self, t, False)]

    def has_all(self) -> bool:
        return all(getattr(self, t, False) for t in MEDIA_TYPES)

    def present(self) -> list[str]:
        return [t for t in MEDIA_TYPES if getattr(self, t, False)]


@dataclass
class FuzzyMatchEntry:
    """A ROM that has no exact DB entry but closely resembles one."""
    rom_name: str
    db_name: str
    score: float
    db_entry: Optional[GameEntry]


@dataclass
class GameAuditEntry:
    rom_name: str
    in_database: bool
    rom_exists: bool
    db_entry: Optional[GameEntry]
    media: MediaStatus = field(default_factory=MediaStatus)
    missing_metadata: list[str] = field(default_factory=list)
    ignored: bool = False
    # Optional MAME -listxml enrichment.  None means "not checked"; True/False
    # are populated only when config.mame_executable is set and the system
    # routes through MAME.
    has_mame_input: Optional[bool] = None

    @property
    def needs_attention(self) -> bool:
        return (
            not self.ignored
            and (
                not self.in_database
                or not self.rom_exists
                or bool(self.missing_metadata)
                or not self.media.has_all()
            )
        )


@dataclass
class SystemAuditResult:
    system_name: str
    total_roms: int = 0
    total_db_entries: int = 0
    roms_in_db: int = 0
    roms_not_in_db: int = 0
    db_entries_no_rom: int = 0
    ignored_count: int = 0
    entries: list[GameAuditEntry] = field(default_factory=list)
    fuzzy_matches: list[FuzzyMatchEntry] = field(default_factory=list)

    @property
    def roms_only(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.rom_exists and not e.in_database and not e.ignored]

    @property
    def db_only(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.in_database and not e.rom_exists and not e.ignored]

    @property
    def missing_metadata_entries(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.missing_metadata and not e.ignored]

    @property
    def missing_media_entries(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.in_database and e.media.missing() and not e.ignored]

    @property
    def matched(self) -> list[GameAuditEntry]:
        return [e for e in self.entries if e.rom_exists and e.in_database]


def scan_roms(system_name: str, roms_dir: Path) -> dict[str, RomFileInfo]:
    system_rom_dir = roms_dir / system_name
    if not system_rom_dir.exists():
        return {}
    extensions = get_rom_extensions(system_name)
    ovr = get_system_overrides().get(system_name, {})
    if ovr.get("recursive_scan"):
        return _scan_recursive(
            system_rom_dir,
            extensions,
            ovr.get("title_strategy", "smart"),
        )
    roms: dict[str, RomFileInfo] = {}
    for rom_path in system_rom_dir.iterdir():
        if rom_path.is_file() and rom_path.suffix.lower() in extensions:
            roms[rom_path.stem] = RomFileInfo(
                name=rom_path.stem,
                path=rom_path,
                extension=rom_path.suffix.lower(),
            )
    return roms


def _scan_recursive(
    system_rom_dir: Path,
    extensions: list[str],
    title_strategy: str,
) -> dict[str, RomFileInfo]:
    """Walk *system_rom_dir* recursively, deriving a title for each match.

    When two files in different sub-folders derive to the same title (e.g.
    a game with both an .exe and a .lnk), the first one wins; subsequent
    duplicates are dropped so the database key stays unique.
    """
    roms: dict[str, RomFileInfo] = {}
    ext_set = {e.lower() for e in extensions}
    for rom_path in system_rom_dir.rglob("*"):
        if not rom_path.is_file() or rom_path.suffix.lower() not in ext_set:
            continue
        title = derive_pc_title(rom_path, system_rom_dir, title_strategy)
        if title in roms:
            continue
        roms[title] = RomFileInfo(
            name=title,
            path=rom_path,
            extension=rom_path.suffix.lower(),
        )
    return roms


def check_media(game_name: str, system_name: str, media_base: Path) -> MediaStatus:
    sys_dir = media_base / system_name
    status = MediaStatus()

    img_exts = {".png", ".jpg", ".jpeg"}
    video_exts = {".mp4", ".avi", ".flv", ".mkv"}
    sound_exts = {".mp3", ".wav", ".ogg"}

    status.wheel = _exists(sys_dir / "Images" / "Wheel", game_name, img_exts)
    status.background = _exists(sys_dir / "Images" / "Backgrounds", game_name, img_exts)
    status.artwork = _exists(sys_dir / "Images" / "Artwork1", game_name, img_exts)
    status.title = _exists(sys_dir / "Images" / "Artwork2", game_name, img_exts)
    status.snap = _exists(sys_dir / "Images" / "Artwork3", game_name, img_exts)
    status.video = _exists(sys_dir / "Video", game_name, video_exts)
    status.trailer = _exists(sys_dir / "Video" / "Trailers", game_name, video_exts)
    status.sound = _exists(sys_dir / "Sound", game_name, sound_exts)
    status.theme = (sys_dir / "Themes" / game_name).exists() or _exists(
        sys_dir / "Themes", game_name, {".zip", ".swf"}
    )
    return status


def _exists(directory: Path, stem: str, extensions: set[str]) -> bool:
    if not directory.exists():
        return False
    return any((directory / f"{stem}{ext}").exists() for ext in extensions)


def audit_system(
    system_name: str,
    config: Config,
    check_media_flag: bool = True,
    fuzzy: bool = True,
    check_mame_controls: bool = True,
) -> SystemAuditResult:
    """Full audit of one system: ROMs vs database vs media, with fuzzy matching."""
    result = SystemAuditResult(system_name=system_name)

    roms = scan_roms(system_name, Path(config.roms_dir))
    db = load_database(system_name, config.databases_dir)
    db_games = db.games()

    # Optional: load MAME -listxml input data when configured + system is arcade-ish.
    listxml_lookup: dict[str, bool] = {}
    if check_mame_controls and config.mame_executable and _is_mame_system(system_name):
        try:
            from .ledblinky import load_listxml_for_system
            info_map = load_listxml_for_system(config, system_name)
            listxml_lookup = {
                name: info.has_input for name, info in info_map.items()
            }
        except Exception:
            listxml_lookup = {}

    result.total_roms = len(roms)
    result.total_db_entries = len(db_games)

    # Build exact-match union
    all_names = set(roms.keys()) | set(db_games.keys())
    db_name_list = list(db_games.keys())

    # Track which DB entries have been claimed by a ROM (exact or fuzzy)
    claimed_db_names: set[str] = set()

    for name in all_names:
        rom_exists = name in roms
        in_database = name in db_games
        db_entry = db_games.get(name)
        is_ignored = config.is_ignored(name, system_name)

        if in_database:
            claimed_db_names.add(name)

        media = (
            check_media(name, system_name, config.media_dir)
            if check_media_flag and config.hyperspin_dir
            else MediaStatus()
        )
        missing_meta = db_entry.missing_fields() if db_entry else []

        controls_state: Optional[bool] = None
        if listxml_lookup:
            controls_state = listxml_lookup.get(name)

        entry = GameAuditEntry(
            rom_name=name,
            in_database=in_database,
            rom_exists=rom_exists,
            db_entry=db_entry,
            media=media,
            missing_metadata=missing_meta,
            ignored=is_ignored,
            has_mame_input=controls_state,
        )
        result.entries.append(entry)

        if is_ignored:
            result.ignored_count += 1

    # Fuzzy pass: for ROMs with no exact DB match, find near-matches
    if fuzzy and db_name_list:
        for entry in result.entries:
            if entry.rom_exists and not entry.in_database and not entry.ignored:
                match = find_best_match(
                    entry.rom_name,
                    [n for n in db_name_list if n not in claimed_db_names],
                    threshold=config.match_threshold,
                )
                if match:
                    db_name, score = match
                    result.fuzzy_matches.append(
                        FuzzyMatchEntry(
                            rom_name=entry.rom_name,
                            db_name=db_name,
                            score=score,
                            db_entry=db_games.get(db_name),
                        )
                    )
                    claimed_db_names.add(db_name)

    result.roms_in_db = sum(1 for e in result.entries if e.rom_exists and e.in_database)
    result.roms_not_in_db = sum(
        1 for e in result.entries if e.rom_exists and not e.in_database and not e.ignored
    )
    result.db_entries_no_rom = sum(
        1 for e in result.entries if e.in_database and not e.rom_exists and not e.ignored
    )
    result.entries.sort(key=lambda e: e.rom_name.lower())
    result.fuzzy_matches.sort(key=lambda f: f.score, reverse=True)
    return result


def build_stub_entry(rom_name: str, strip_variants: bool = False) -> GameEntry:
    """Create a minimal stub GameEntry from a ROM filename stem."""
    description = clean_display_name(rom_name, strip_variants=strip_variants)
    return GameEntry(name=rom_name, description=description)


_MAME_SYSTEM_HINTS = ("mame", "arcade", "neogeo", "neo geo", "cps1", "cps2", "cps3")


def _is_mame_system(system_name: str) -> bool:
    s = system_name.lower()
    return any(h in s for h in _MAME_SYSTEM_HINTS)
