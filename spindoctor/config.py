"""Configuration management for SpinDoctor."""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
    "ps3": [".iso", ".pkg"],
    "playstation3": [".iso", ".pkg"],
    "saturn": [".chd", ".cue", ".bin", ".iso"],
    "dreamcast": [".chd", ".cdi", ".gdi", ".cue"],
    "segacd": [".chd", ".cue", ".bin", ".iso"],
    "wii": [".iso", ".wbfs", ".rvz"],
    "xbox360": [".iso"],
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
    "fade",
    "video",
    "trailer",
    "sound",
    "theme",
]

SCREENSCRAPER_API = "https://www.screenscraper.fr/api2"
THEGAMESDB_API = "https://api.thegamesdb.net/v1"


DEFAULT_LEDBLINKY_COLORS: dict[str, str] = {
    # Standard 6-button arcade panel palette (hex RGB)
    "button1": "FF0000",  # red
    "button2": "FFFF00",  # yellow
    "button3": "00FF00",  # green
    "button4": "0000FF",  # blue
    "button5": "FF00FF",  # magenta
    "button6": "00FFFF",  # cyan
    "joystick": "FFFFFF",  # white
    "start": "FFFFFF",
    "coin": "FF8000",  # orange
}


@dataclass
class Config:
    # Directories
    roms_dir: str = ""
    hyperspin_dir: str = ""
    emulators_dir: str = ""
    rocketlauncher_dir: str = ""
    ledblinky_dir: str = ""
    output_dir: str = ""
    auto_audit_export_dir: str = ""

    # External binaries
    mame_executable: str = ""
    demulshooter_path: str = ""           # Override DemulShooter.exe location
    demulshooter_extra_args: str = ""     # Extra CLI args appended to -target

    # Metadata API credentials
    screenscraper_user: str = ""
    screenscraper_pass: str = ""
    thegamesdb_key: str = ""
    default_metadata_source: str = "screenscraper"

    # Behaviour
    backup_before_modify: bool = True
    max_concurrent_downloads: int = 4
    match_threshold: float = 0.80
    interactive_matching: bool = True
    strip_variant_tags_in_display_name: bool = False

    # Caching
    metadata_cache_ttl_days: int = 30
    metadata_cache_enabled: bool = True

    # GUI preferences
    # ui_scale multiplies the named-font sizes (TkDefaultFont, etc.) and
    # the initial window geometry, so cabinet owners on 1280x720 (or
    # ultra-HD) can fit the whole tab on screen. Clamped to [0.6, 2.0].
    ui_scale: float = 1.0
    # Hides the bottom Output panel when False. Persisted so the
    # preference survives restarts.
    output_visible: bool = True
    # Set the first time the GUI's first-run wizard finishes (or is
    # skipped). Stops the wizard from re-opening on every launch.
    # Older configs (pre-wizard) auto-promote to True the first time
    # they validate cleanly, so existing installs never see it.
    first_run_complete: bool = False
    # Persisted Tk geometry string (e.g. "1280x800+120+60") and last
    # active notebook tab index. Restored on the next launch so a
    # cabinet owner who lives in the Curate or Wheels tab doesn't have
    # to re-navigate every time. Empty string = "use the calculated
    # default geometry"; a negative tab index disables restore.
    gui_window_geometry: str = ""
    gui_last_active_tab: int = -1
    # Last SpinDoctor version that this user saw the "What's new" dialog
    # for. Compared to __version__ at GUI launch — when they differ, a
    # one-shot dialog appears with the recent CHANGELOG highlights. Set
    # to "" for fresh installs, which suppresses the dialog (first-run
    # wizard covers them instead).
    last_seen_version: str = ""

    # LEDBlinky default per-button color palette (hex RGB strings)
    ledblinky_default_colors: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_LEDBLINKY_COLORS)
    )

    # Region/version preference order used by `spindoctor curate` to choose
    # the canonical ROM per game. First match wins. Override per-run with
    # `--regions USA,Japan` on the CLI.
    region_preferences: list[str] = field(
        default_factory=lambda: ["USA", "World", "Europe", "Japan"]
    )

    # Per-system ignore lists  {system_name: [rom_name, ...], "_global": [...]}
    ignore_lists: dict[str, list[str]] = field(default_factory=dict)

    # User-supplied overrides for hardcoded system lookups.  Lets users add
    # support for new consoles (e.g. a future PS7) or PC/Windows/Steam game
    # libraries without editing source.
    # Schema:
    #   {
    #     "Sony Playstation 7": {
    #         "screenscraper_id": 999,        # int
    #         "thegamesdb_id": 99,             # int
    #         "rom_extensions": [".ps7"],      # list[str]
    #         "layout": "per-game-folder",     # "per-game-folder" | "multi-disc-m3u" | "flat"
    #         "emulator": "RPCS7",             # free-form
    #         "recursive_scan": True,          # walk subdirectories under <roms_dir>/<system>/
    #         "title_strategy": "smart",       # "smart" | "stem" | "parent_folder"
    #         "lightgun": True,                # System uses Sinden / DemulShooter
    #     }
    #   }
    system_overrides: dict[str, dict] = field(default_factory=dict)

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

    # ── lightgun helpers ───────────────────────────────────────────────────────

    def lightgun_systems(self) -> list[str]:
        """System names with ``lightgun: true`` in their override map."""
        return sorted(
            name for name, ovr in (self.system_overrides or {}).items()
            if isinstance(ovr, dict) and ovr.get("lightgun")
        )

    def set_lightgun(self, system_name: str, enabled: bool) -> None:
        ovr = self.system_overrides.setdefault(system_name, {})
        if enabled:
            ovr["lightgun"] = True
        else:
            ovr.pop("lightgun", None)
            if not ovr:
                self.system_overrides.pop(system_name, None)

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


_OVERRIDE_CACHE: Optional[dict[str, dict]] = None


def get_system_overrides() -> dict[str, dict]:
    """Return the user-supplied system overrides map (cached)."""
    global _OVERRIDE_CACHE
    if _OVERRIDE_CACHE is None:
        _OVERRIDE_CACHE = load_config().system_overrides or {}
    return _OVERRIDE_CACHE


def reset_override_cache() -> None:
    """Drop the in-memory override cache so the next lookup re-reads disk."""
    global _OVERRIDE_CACHE
    _OVERRIDE_CACHE = None


def load_config() -> Config:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return Config.from_dict(json.load(f))
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            # Preserve the corrupt file so the user can recover hand-edited
            # values; falling through to Config() would overwrite it on the
            # next save with no trace of what was there.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = CONFIG_FILE.with_suffix(f".corrupt-{stamp}.json")
            try:
                shutil.copy2(CONFIG_FILE, backup)
                backup_note = f" Backed up to {backup}."
            except OSError:
                backup_note = ""
            print(
                f"spindoctor: warning — {CONFIG_FILE} is unreadable ({exc}); "
                f"using defaults.{backup_note}",
                file=sys.stderr,
            )
    return Config()


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)
    reset_override_cache()


def get_rom_extensions(system_name: str) -> list[str]:
    # User override wins
    ovr = get_system_overrides().get(system_name, {})
    if isinstance(ovr.get("rom_extensions"), list) and ovr["rom_extensions"]:
        return [str(e) if str(e).startswith(".") else f".{e}"
                for e in ovr["rom_extensions"]]

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
