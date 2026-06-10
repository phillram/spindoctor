"""HyperSpin Main Menu editor.

The Main Menu lives at ``<hyperspin_dir>/Databases/Main Menu/Main Menu.xml``
and lists the systems shown at the top level of the cabinet UI as
``<game name="..."/>`` entries.  This module loads it, lets callers
re-order / hide / add / remove systems, and writes it back via the same
lossless lxml round-trip used by :mod:`spindoctor.database`.

A ``MainMenu`` is structurally a HyperSpin database — it has a ``<menu>``
root with a ``<header>`` and a list of ``<game>`` children.  We keep the
order explicit (HyperSpin honours XML order for the menu wheel) and
piggy-back on :class:`spindoctor.database.HyperspinDatabase` for backup,
output-dir handling, and comment-preserving I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config
from .database import HyperspinDatabase, GameEntry


MAIN_MENU_FOLDER = "Main Menu"
MAIN_MENU_FILENAME = "Main Menu.xml"


@dataclass
class MainMenuEntry:
    """One system entry in the Main Menu wheel."""
    system: str
    enabled: str = "Yes"
    description: str = ""
    manufacturer: str = ""
    year: str = ""
    genre: str = ""
    # Carries unknown <game> attributes from the source XML so things like
    # HyperSpin's ``exe="true"`` on the Search entry survive load → save.
    extra_attrs: dict = field(default_factory=dict)

    @property
    def visible(self) -> bool:
        return (self.enabled or "Yes").strip().lower() != "no"


@dataclass
class MainMenu:
    """Ordered list of system entries plus the underlying database tree."""
    xml_path: Path
    entries: list[MainMenuEntry] = field(default_factory=list)
    # Keep the loaded HyperspinDatabase so save() can reuse the lxml tree
    # (which preserves comments and unknown attributes).
    _db: Optional[HyperspinDatabase] = None

    def index_of(self, system: str) -> int:
        """Return the 0-based index of *system*; raise KeyError otherwise."""
        key = system.strip().lower()
        for i, entry in enumerate(self.entries):
            if entry.system.strip().lower() == key:
                return i
        raise KeyError(system.strip())

    def get(self, system: str) -> MainMenuEntry:
        return self.entries[self.index_of(system)]

    def has(self, system: str) -> bool:
        try:
            self.index_of(system)
        except KeyError:
            return False
        return True

    def systems(self) -> list[str]:
        return [e.system for e in self.entries]


# ─── load / save ──────────────────────────────────────────────────────────────

def _main_menu_path(config: Config, output_dir: Optional[Path] = None) -> Path:
    db_base = (output_dir / "Databases") if output_dir else config.databases_dir
    return db_base / MAIN_MENU_FOLDER / MAIN_MENU_FILENAME


def load_main_menu(config: Config) -> MainMenu:
    """Read the current Main Menu.xml and return an ordered :class:`MainMenu`."""
    path = _main_menu_path(config)
    db = HyperspinDatabase(MAIN_MENU_FOLDER, path, enabled_as_attribute=True)
    db.load()

    entries: list[MainMenuEntry] = []
    for game in db.iter_xml_order():
        entries.append(_entry_from_game(game))

    return MainMenu(xml_path=path, entries=entries, _db=db)


def _entry_from_game(game: GameEntry) -> MainMenuEntry:
    return MainMenuEntry(
        system=game.name,
        enabled=(game.enabled or "Yes"),
        description=game.description or "",
        manufacturer=game.manufacturer or "",
        year=game.year or "",
        genre=game.genre or "",
        extra_attrs=dict(game.extra_attrs or {}),
    )


def _entry_to_game(entry: MainMenuEntry) -> GameEntry:
    return GameEntry(
        name=entry.system,
        description=entry.description or entry.system,
        manufacturer=entry.manufacturer,
        year=entry.year,
        genre=entry.genre,
        enabled=entry.enabled or "Yes",
        extra_attrs=dict(entry.extra_attrs or {}),
    )


def save_main_menu(
    menu: MainMenu,
    config: Config,
    output_dir: Optional[Path] = None,
) -> Path:
    """Write *menu* back to disk in its current order.

    Saves a ``.YYYYMMDD_HHMMSS.bak`` first when ``config.backup_before_modify``
    is true and we're writing to the live file (i.e. no ``output_dir``).
    """
    target = _main_menu_path(config, output_dir)
    db = menu._db

    # If we have a tree (file existed), rewrite its <game> children in the
    # exact order requested.  This preserves comments, the <header>, and any
    # unknown attributes/elements lxml saw during load.
    if db is not None and db._tree is not None and db._root is not None:
        # Sync the in-memory game map to match the menu order.
        db._games.clear()
        db._game_elements.clear()
        # Drop existing <game> children from the tree; re-append in order.
        for child in list(db._root.findall("game")):
            db._root.remove(child)
        for entry in menu.entries:
            game = _entry_to_game(entry)
            db._games[game.name] = game
        # save() will rebuild <game> elements in dict-iteration order.
    else:
        # Fresh file path: build from scratch.
        db = HyperspinDatabase(MAIN_MENU_FOLDER, target, enabled_as_attribute=True)
        db.load()  # noop, file likely missing
        for entry in menu.entries:
            game = _entry_to_game(entry)
            db._games[game.name] = game
        menu._db = db

    use_backup = config.backup_before_modify and output_dir is None
    bak_dir = Path(config.backup_dir) if getattr(config, "backup_dir", "") else None
    if output_dir is None:
        # Writing in-place — let HyperspinDatabase.save() backup the live file.
        return db.save(backup=use_backup, backup_dir=bak_dir)
    # Routed elsewhere — write to the explicit target (no backup).
    return db.save(output_path=target, backup=False)


# ─── operations ───────────────────────────────────────────────────────────────

def reorder(menu: MainMenu, system: str, position: int) -> None:
    """Move *system* to *position* (1-indexed)."""
    if position < 1:
        raise ValueError(f"position must be >= 1 (got {position})")
    src = menu.index_of(system)
    entry = menu.entries.pop(src)
    target = max(0, min(position - 1, len(menu.entries)))
    menu.entries.insert(target, entry)


def move_up(menu: MainMenu, system: str) -> None:
    idx = menu.index_of(system)
    if idx == 0:
        return
    menu.entries[idx - 1], menu.entries[idx] = menu.entries[idx], menu.entries[idx - 1]


def move_down(menu: MainMenu, system: str) -> None:
    idx = menu.index_of(system)
    if idx >= len(menu.entries) - 1:
        return
    menu.entries[idx + 1], menu.entries[idx] = menu.entries[idx], menu.entries[idx + 1]


def hide(menu: MainMenu, system: str) -> None:
    """Set ``enabled="No"`` so HyperSpin skips the system on the wheel."""
    menu.get(system).enabled = "No"


def show(menu: MainMenu, system: str) -> None:
    menu.get(system).enabled = "Yes"


def add_system(menu: MainMenu, system: str) -> bool:
    """Append *system* to the menu (idempotent).  Returns True if added."""
    system = system.strip()
    if not system:
        raise ValueError("system name is empty")
    if menu.has(system):
        return False
    menu.entries.append(MainMenuEntry(
        system=system,
        enabled="Yes",
        description=system,
    ))
    return True


def remove_system(menu: MainMenu, system: str) -> bool:
    """Delete *system* from the menu.  Returns True if removed."""
    try:
        idx = menu.index_of(system)
    except KeyError:
        return False
    menu.entries.pop(idx)
    return True


def sort_alphabetical(menu: MainMenu) -> None:
    """Sort systems alphabetically by display name (case-insensitive)."""
    menu.entries.sort(key=lambda e: (e.description or e.system).lower())


def sort_by_field(menu: MainMenu, field_name: str) -> None:
    """Sort by ``manufacturer`` or ``year``; ties broken by system name."""
    if field_name not in {"manufacturer", "year", "genre"}:
        raise ValueError(
            f"sort_by_field only supports manufacturer/year/genre (got {field_name!r})"
        )
    menu.entries.sort(
        key=lambda e: (
            (getattr(e, field_name) or "").lower(),
            (e.description or e.system).lower(),
        )
    )


# ─── discovery ────────────────────────────────────────────────────────────────

def discover_systems(config: Config) -> list[str]:
    """Return systems present in ``<hyperspin_dir>/Databases/`` but absent
    from the Main Menu.

    A "system" is any sub-folder of ``Databases/`` other than ``Main Menu``
    itself that holds a ``<Folder>.xml`` database file.
    """
    db_dir = config.databases_dir
    if not db_dir.exists():
        return []

    menu = load_main_menu(config)
    listed = {s.strip().lower() for s in menu.systems()}

    found: list[str] = []
    for child in sorted(db_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name == MAIN_MENU_FOLDER:
            continue
        # Only count it as a system if it actually has an XML database.
        if not any(child.glob("*.xml")):
            continue
        if child.name.strip().lower() in listed:
            continue
        found.append(child.name)
    return found


def system_exists_in_databases(config: Config, system: str) -> bool:
    """Return True if ``Databases/<system>/`` exists with at least one XML."""
    sys_dir = config.databases_dir / system
    if not sys_dir.is_dir():
        return False
    return any(sys_dir.glob("*.xml"))
