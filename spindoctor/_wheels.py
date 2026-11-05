"""Safety checks shared by synthetic-wheel builders and clear commands."""
from pathlib import Path

from ._utils import win_safe_stem


DEFAULT_SYNTHETIC_NAMES = frozenset({"Favorites", "Recently Played", "Most Played"})


def validate_target(config, name, sources=()):
    """Never interpret a wheel name as a path or overwrite a source system."""
    if not name or name != name.strip() or win_safe_stem(name) != name or name in (".", ".."):
        raise ValueError("Target system must be a non-empty, Windows-safe folder name.")
    if name.casefold() in {s.casefold() for s in sources}:
        raise ValueError(f"Target system is also a source system: {name}")
    if name.casefold() in {"main menu", "frontend"}:
        raise ValueError(f"Cannot replace HyperSpin's {name} system.")
    if config.roms_dir and (Path(config.roms_dir) / name).exists():
        raise ValueError(f"Target system has a source ROM folder: {name}")
    if config.hyperspin_dir and name not in DEFAULT_SYNTHETIC_NAMES:
        folder = config.databases_dir / name
        if (folder / f"{name}.xml").exists() and not (folder / ".spindoctor-synthetic").exists():
            # Older custom synthetic wheels have generated launcher placeholders.
            launchers = Path(config.rocketlauncher_dir) / "Modules" / "PCLauncher" / name
            if not config.rocketlauncher_dir or not launchers.is_dir():
                raise ValueError(f"Refusing to replace an existing non-synthetic database: {name}")


def mark_synthetic(config, name):
    (config.databases_dir / name / ".spindoctor-synthetic").touch()


def synthetic_names(config):
    names = set(DEFAULT_SYNTHETIC_NAMES)
    if config.hyperspin_dir:
        names.update(p.parent.name for p in config.databases_dir.glob("*/.spindoctor-synthetic"))
    return names
