"""Configuration management for SpinDoctor."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".spindoctor"
CONFIG_FILE = CONFIG_DIR / "config.json"

ROM_EXTENSIONS: dict[str, list[str]] = {
    "default": [".zip", ".7z", ".rar"],
    "mame": [".zip", ".7z"],
    "nes": [".nes", ".zip", ".7z"],
    "snes": [".sfc", ".smc", ".zip", ".7z"],
    "genesis": [".md", ".bin", ".smd", ".zip", ".7z"],
    "n64": [".z64", ".n64", ".v64", ".zip", ".7z"],
    "gba": [".gba", ".zip", ".7z"],
    "psx": [".bin", ".cue", ".iso", ".img", ".zip", ".7z"],
    "ps2": [".iso", ".bin", ".img"],
    "arcade": [".zip", ".7z"],
}

# Ordered list — used for display, CSV columns, and download loops.
# theme is last because it's rarely downloadable via APIs.
MEDIA_TYPES = [
    "wheel",
    "background",
    "artwork",
    "title",
    "snap",
    "video",
    "trailer",
    "sound",
    "theme",
]

SCREENSCRAPER_API = "https://www.screenscraper.fr/api2"
THEGAMESDB_API = "https://api.thegamesdb.net/v1"


@dataclass
class Config:
    # Directories
    roms_dir: str = ""
    hyperspin_dir: str = ""
    emulators_dir: str = ""
    rocketlauncher_dir: str = ""
    output_dir: str = ""
    auto_audit_export_dir: str = ""

    # Metadata API credentials
    screenscraper_user: str = ""
    screenscraper_pass: str = ""
    thegamesdb_key: str = ""
    default_metadata_source: str = "screenscraper"

    # Behaviour
    backup_before_modify: bool = True
    max_concurrent_downloads: int = 3
    match_threshold: float = 0.80
    interactive_matching: bool = True
    strip_variant_tags_in_display_name: bool = False

    # Per-system ignore lists  {system_name: [rom_name, ...], "_global": [...]}
    ignore_lists: dict[str, list[str]] = field(default_factory=dict)

    # ── derived paths ──────────────────────────────────────────────────────────

    @property
    def databases_dir(self) -> Path:
        return Path(self.hyperspin_dir) / "Databases"

    @property
    def media_dir(self) -> Path:
        return Path(self.hyperspin_dir) / "Media"

    def effective_output_dir(self, override: Optional[str] = None) -> Optional[Path]:
        d = override or self.output_dir
        return Path(d) if d else None

    # ── validation ─────────────────────────────────────────────────────────────

    def is_valid(self) -> tuple[bool, list[str]]:
        errors = []
        if not self.roms_dir:
            errors.append("roms_dir is not set")
        elif not Path(self.roms_dir).exists():
            errors.append(f"roms_dir does not exist: {self.roms_dir}")
        if not self.hyperspin_dir:
            errors.append("hyperspin_dir is not set")
        elif not Path(self.hyperspin_dir).exists():
            errors.append(f"hyperspin_dir does not exist: {self.hyperspin_dir}")
        return len(errors) == 0, errors

    # ── ignore list helpers ────────────────────────────────────────────────────

    def is_ignored(self, rom_name: str, system_name: str) -> bool:
        global_list = self.ignore_lists.get("_global", [])
        system_list = self.ignore_lists.get(system_name, [])
        return rom_name in global_list or rom_name in system_list

    def add_ignore(self, rom_name: str, system_name: str) -> None:
        if system_name not in self.ignore_lists:
            self.ignore_lists[system_name] = []
        if rom_name not in self.ignore_lists[system_name]:
            self.ignore_lists[system_name].append(rom_name)

    def remove_ignore(self, rom_name: str, system_name: str) -> bool:
        lst = self.ignore_lists.get(system_name, [])
        if rom_name in lst:
            lst.remove(rom_name)
            return True
        return False

    def get_ignore_list(self, system_name: Optional[str] = None) -> list[str]:
        if system_name:
            return list(self.ignore_lists.get(system_name, []))
        all_names: list[str] = []
        for lst in self.ignore_lists.values():
            all_names.extend(lst)
        return all_names

    # ── serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def load_config() -> Config:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return Config.from_dict(json.load(f))
        except (json.JSONDecodeError, TypeError):
            pass
    return Config()


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)


def get_rom_extensions(system_name: str) -> list[str]:
    key = system_name.lower().replace(" ", "")
    # Exact match first
    if key in ROM_EXTENSIONS:
        return ROM_EXTENSIONS[key]
    # Longest-key-first partial match to avoid "nes" matching "genesis"
    for k in sorted(ROM_EXTENSIONS, key=len, reverse=True):
        if k != "default" and (k in key or key in k):
            return ROM_EXTENSIONS[k]
    return ROM_EXTENSIONS["default"]


def get_systems(config: Config) -> list[str]:
    systems: set[str] = set()
    roms_path = Path(config.roms_dir)
    db_path = config.databases_dir
    if roms_path.exists():
        systems.update(p.name for p in roms_path.iterdir() if p.is_dir())
    if db_path.exists():
        systems.update(p.name for p in db_path.iterdir() if p.is_dir())
    return sorted(systems)
