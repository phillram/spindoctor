"""Configuration management for SpinDoctor."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".spindoctor"
CONFIG_FILE = CONFIG_DIR / "config.json"

ROM_EXTENSIONS = {
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

MEDIA_TYPES = ["wheel", "background", "artwork", "video", "sound", "theme"]

SCREENSCRAPER_API = "https://www.screenscraper.fr/api2"
THEGAMESDB_API = "https://api.thegamesdb.net/v1"


@dataclass
class Config:
    roms_dir: str = ""
    hyperspin_dir: str = ""
    emulators_dir: str = ""
    output_dir: str = ""
    screenscraper_user: str = ""
    screenscraper_pass: str = ""
    thegamesdb_key: str = ""
    default_metadata_source: str = "screenscraper"
    backup_before_modify: bool = True
    max_concurrent_downloads: int = 3
    ignore_lists: dict[str, list[str]] = field(default_factory=dict)

    # Derived paths (not stored, computed from hyperspin_dir)
    @property
    def databases_dir(self) -> Path:
        return Path(self.hyperspin_dir) / "Databases"

    @property
    def media_dir(self) -> Path:
        return Path(self.hyperspin_dir) / "Media"

    def effective_output_dir(self, override: Optional[str] = None) -> Optional[Path]:
        """Return the output directory override, if any."""
        d = override or self.output_dir
        return Path(d) if d else None

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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = {f for f in cls.__dataclass_fields__}
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
    for k, exts in ROM_EXTENSIONS.items():
        if k in key or key in k:
            return exts
    return ROM_EXTENSIONS["default"]


def get_systems(config: Config) -> list[str]:
    """Return list of system names found in both ROMs and Databases directories."""
    systems = set()
    roms_path = Path(config.roms_dir)
    db_path = config.databases_dir

    if roms_path.exists():
        systems.update(p.name for p in roms_path.iterdir() if p.is_dir())
    if db_path.exists():
        systems.update(p.name for p in db_path.iterdir() if p.is_dir())

    return sorted(systems)
