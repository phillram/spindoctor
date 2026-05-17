"""Hyperspin XML database read/write.

Uses ``lxml`` when available so that comments, attribute order, and any custom
elements added by HyperHQ / Don's tools survive a save round-trip.  Falls back
to ``xml.etree.ElementTree`` (which loses comments) with a one-time warning.
"""
from __future__ import annotations

import shutil
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from ._compat import et_indent

try:
    from lxml import etree as LET  # type: ignore
    _HAS_LXML = True
except ImportError:  # pragma: no cover - fallback path
    LET = None  # type: ignore
    _HAS_LXML = False

# Order in which fields are emitted for new <game> elements (HyperSpin convention).
# ``players`` sits next to ``rating`` — both are short, optional descriptors and
# HyperHQ-exported XMLs typically place them adjacent.
_FIELD_ORDER = (
    "description", "cloneof", "crc", "manufacturer",
    "year", "genre", "rating", "players", "enabled",
)

_LXML_WARNED = False


def _warn_no_lxml_once() -> None:
    global _LXML_WARNED
    if not _LXML_WARNED:
        _LXML_WARNED = True
        warnings.warn(
            "lxml not installed; XML comments and attribute order will not be "
            "preserved on round-trip. Install with: pip install spindoctor[xml]",
            RuntimeWarning,
            stacklevel=2,
        )


@dataclass
class GameEntry:
    name: str
    description: str = ""
    cloneof: str = ""
    crc: str = ""
    manufacturer: str = ""
    year: str = ""
    genre: str = ""
    rating: str = ""
    players: str = ""
    enabled: str = "Yes"

    def is_metadata_complete(self) -> bool:
        return all([self.description, self.manufacturer, self.year, self.genre])

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.description:
            missing.append("description")
        if not self.manufacturer:
            missing.append("manufacturer")
        if not self.year:
            missing.append("year")
        if not self.genre:
            missing.append("genre")
        return missing


class HyperspinDatabase:
    def __init__(self, system_name: str, xml_path: Path):
        self.system_name = system_name
        self.xml_path = xml_path
        self._games: dict[str, GameEntry] = {}
        self._loaded = False
        # Tracks the parsed tree and per-game element refs for in-place updates
        # so comments / custom attributes survive round-trip.
        self._tree: Any = None
        self._root: Any = None
        self._game_elements: dict[str, Any] = {}

    # ── load ───────────────────────────────────────────────────────────────────

    def load(self) -> None:
        if not self.xml_path.exists():
            self._loaded = True
            return
        try:
            # Open the file ourselves and pass the handle into the
            # parser so the OS lock is released as soon as parsing
            # finishes. Passing a *path* to lxml/ET keeps the file
            # open on Windows until the tree is GC'd — which then
            # blocks any concurrent rename / save / migrate touching
            # the same XML.
            if _HAS_LXML:
                parser = LET.XMLParser(remove_comments=False, remove_blank_text=False)
                with open(self.xml_path, "rb") as fh:
                    self._tree = LET.parse(fh, parser)
            else:
                _warn_no_lxml_once()
                with open(self.xml_path, "rb") as fh:
                    self._tree = ET.parse(fh)

            self._root = self._tree.getroot()
            for game_el in self._root.findall("game"):
                name = (game_el.get("name") or "").strip()
                if not name:
                    continue
                self._games[name] = GameEntry(
                    name=name,
                    description=_text(game_el, "description"),
                    cloneof=_text(game_el, "cloneof"),
                    crc=_text(game_el, "crc"),
                    manufacturer=_text(game_el, "manufacturer"),
                    year=_text(game_el, "year"),
                    genre=_text(game_el, "genre"),
                    rating=_text(game_el, "rating"),
                    players=_text(game_el, "players"),
                    enabled=_text(game_el, "enabled") or "Yes",
                )
                self._game_elements[name] = game_el
        except (ET.ParseError, Exception) as e:
            if _HAS_LXML and isinstance(e, LET.XMLSyntaxError):
                raise ValueError(f"Failed to parse {self.xml_path}: {e}") from e
            if isinstance(e, ET.ParseError):
                raise ValueError(f"Failed to parse {self.xml_path}: {e}") from e
            raise
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ── accessors ──────────────────────────────────────────────────────────────

    def games(self) -> dict[str, GameEntry]:
        self._ensure_loaded()
        return self._games

    def get(self, name: str) -> Optional[GameEntry]:
        self._ensure_loaded()
        return self._games.get(name)

    def contains(self, name: str) -> bool:
        self._ensure_loaded()
        return name in self._games

    def add_game(self, game: GameEntry) -> None:
        self._ensure_loaded()
        self._games[game.name] = game

    def update_game(self, game: GameEntry) -> None:
        self._ensure_loaded()
        if game.name in self._games:
            self._games[game.name] = game

    def upsert_game(self, game: GameEntry) -> None:
        self._ensure_loaded()
        self._games[game.name] = game

    def remove_game(self, name: str) -> bool:
        self._ensure_loaded()
        if name in self._games:
            del self._games[name]
            return True
        return False

    def reset_games(self) -> None:
        """Drop every game from both the dict and the parsed XML tree.

        Synthetic systems (Favorites, Recently Played, Most Played) own
        their XML end-to-end and want full control over entry order on
        each rebuild. Without this, ``_merge_into_tree`` would leave
        surviving ``<game>`` elements in their original positions.
        """
        self._ensure_loaded()
        self._games.clear()
        if self._root is not None:
            for el in list(self._game_elements.values()):
                self._root.remove(el)
        self._game_elements.clear()

    def iter_incomplete(self) -> Iterator[GameEntry]:
        self._ensure_loaded()
        return (g for g in self._games.values() if not g.is_metadata_complete())

    # ── save ───────────────────────────────────────────────────────────────────

    def save(self, output_path: Optional[Path] = None, backup: bool = True) -> Path:
        self._ensure_loaded()
        target = output_path or self.xml_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if backup and target.exists() and output_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(target, target.with_suffix(f".{stamp}.bak"))

        # In-place merge path: an original tree exists, so update it so that
        # comments / unknown elements are preserved.
        if self._tree is not None and self._root is not None:
            self._merge_into_tree()
            self._write_tree(target)
        else:
            self._write_fresh(target)

        return target

    # Update the existing tree in place to match self._games.
    def _merge_into_tree(self) -> None:
        # 1) Update / remove existing <game> elements.
        for name, el in list(self._game_elements.items()):
            if name in self._games:
                _update_game_element(el, self._games[name])
            else:
                self._root.remove(el)
                del self._game_elements[name]

        # 2) Append new <game> elements for games not already present.
        for name, game in self._games.items():
            if name not in self._game_elements:
                el = _new_game_element(game)
                self._root.append(el)
                self._game_elements[name] = el

        # Refresh header timestamp if present.
        hdr = self._root.find("header")
        if hdr is not None:
            last = hdr.find("lastlistupdate")
            if last is not None:
                last.text = datetime.now().strftime("%Y-%m-%d")

    def _write_tree(self, target: Path) -> None:
        if _HAS_LXML and isinstance(self._tree, LET._ElementTree):
            xml_bytes = LET.tostring(
                self._tree,
                pretty_print=True,
                xml_declaration=True,
                encoding="UTF-8",
            )
            target.write_bytes(xml_bytes)
        else:
            et_indent(self._tree)
            with open(target, "wb") as f:
                f.write(b'<?xml version="1.0"?>\n')
                self._tree.write(f, encoding="utf-8", xml_declaration=False)

    # Build a brand-new tree from scratch.  Used the first time a DB is created.
    def _write_fresh(self, target: Path) -> None:
        if _HAS_LXML:
            root = LET.Element("menu")
            hdr = LET.SubElement(root, "header")
        else:
            _warn_no_lxml_once()
            root = ET.Element("menu")
            hdr = ET.SubElement(root, "header")

        _set_text(hdr, "listname", self.system_name)
        _set_text(hdr, "lastlistupdate", datetime.now().strftime("%Y-%m-%d"))
        _set_text(hdr, "listversion", "2.0")
        _set_text(hdr, "exporterversion", "SpinDoctor")

        for game in sorted(self._games.values(), key=lambda g: g.name.lower()):
            el = _new_game_element(game, root=root)

        if _HAS_LXML:
            tree = LET.ElementTree(root)
            xml_bytes = LET.tostring(
                tree,
                pretty_print=True,
                xml_declaration=True,
                encoding="UTF-8",
            )
            target.write_bytes(xml_bytes)
        else:
            tree = ET.ElementTree(root)
            et_indent(tree)
            with open(target, "wb") as f:
                f.write(b'<?xml version="1.0"?>\n')
                tree.write(f, encoding="utf-8", xml_declaration=False)


# ─── helpers ───────────────────────────────────────────────────────────────────

def find_database(system_name: str, databases_dir: Path) -> Optional[Path]:
    """Locate the XML database file for a system."""
    system_db_dir = databases_dir / system_name
    if not system_db_dir.exists():
        return None
    candidates = list(system_db_dir.glob("*.xml"))
    if not candidates:
        return None
    for c in candidates:
        if c.stem.lower() == system_name.lower():
            return c
    return candidates[0]


def load_database(system_name: str, databases_dir: Path) -> HyperspinDatabase:
    xml_path = find_database(system_name, databases_dir)
    if xml_path is None:
        xml_path = databases_dir / system_name / f"{system_name}.xml"
    db = HyperspinDatabase(system_name, xml_path)
    db.load()
    return db


def _text(el, tag: str) -> str:
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _set_text(parent, tag: str, text: str):
    """Append a child <tag>text</tag> to ``parent`` and return it."""
    if _HAS_LXML and hasattr(parent, "nsmap"):
        el = LET.SubElement(parent, tag)
    else:
        el = ET.SubElement(parent, tag)
    el.text = text or ""
    return el


def _update_game_element(el, game: "GameEntry") -> None:
    """Update text on existing field children; add any missing fields."""
    el.set("name", game.name)
    for field_name in _FIELD_ORDER:
        value = getattr(game, field_name, "") or ""
        # Preserve description fallback to game name (HyperSpin requires a value).
        if field_name == "description" and not value:
            value = game.name
        if field_name == "enabled" and not value:
            value = "Yes"
        child = el.find(field_name)
        if child is None:
            # Skip optional fields that have no value rather than emitting
            # empty placeholder elements.  ``players`` is an opt-in tag and
            # adding ``<players></players>`` would be misleading.
            if field_name == "players" and not value:
                continue
            _set_text(el, field_name, value)
        else:
            child.text = value


# ─── secondary sort databases ─────────────────────────────────────────────────

# HyperSpin reads these per-system sub-folders to build "Sort by …" wheels.
SORT_AXES: tuple[str, ...] = ("genre", "manufacturer", "year", "letter")


def _letter_bucket(name: str) -> str:
    """Return the alphabetical bucket for *name* — A–Z, "0–9" for digits, "#" else."""
    if not name:
        return "#"
    first = name.lstrip().lstrip("[(").lstrip()[:1].upper()
    if first.isalpha():
        return first
    if first.isdigit():
        return "0-9"
    return "#"


def _bucket_value(game: "GameEntry", axis: str) -> str:
    if axis == "genre":
        return (game.genre or "").strip()
    if axis == "manufacturer":
        return (game.manufacturer or "").strip()
    if axis == "year":
        return (game.year or "").strip()
    if axis == "letter":
        return _letter_bucket(game.description or game.name)
    return ""


def write_sort_databases(
    system_name: str,
    games: list["GameEntry"],
    databases_dir: Path,
    *,
    axes: tuple[str, ...] = SORT_AXES,
    overwrite: bool = False,
) -> dict[str, list[Path]]:
    """Write per-axis HyperSpin sort databases for *system_name*.

    Files go to ``<databases_dir>/<system_name>/<Axis>/<Bucket>.xml`` where
    *Axis* is one of "Genre", "Manufacturer", "Year", "Letter".  Each XML
    lists the games belonging to that bucket.

    By default existing files are skipped (so user-curated lists survive).
    Pass ``overwrite=True`` to replace them.

    Returns a dict {axis: [written_paths]}.
    """
    written: dict[str, list[Path]] = {a: [] for a in axes}
    sys_dir = databases_dir / system_name

    for axis in axes:
        if axis not in SORT_AXES:
            continue
        buckets: dict[str, list["GameEntry"]] = {}
        for g in games:
            value = _bucket_value(g, axis)
            if not value:
                continue
            buckets.setdefault(value, []).append(g)

        if not buckets:
            continue

        axis_dir = sys_dir / axis.capitalize()
        axis_dir.mkdir(parents=True, exist_ok=True)

        for bucket_name, bucket_games in buckets.items():
            safe = _safe_bucket_filename(bucket_name)
            out_path = axis_dir / f"{safe}.xml"
            if out_path.exists() and not overwrite:
                continue

            root = ET.Element("menu")
            hdr = ET.SubElement(root, "header")
            _set_text(hdr, "listname", f"{system_name} — {axis}: {bucket_name}")
            _set_text(hdr, "lastlistupdate", datetime.now().strftime("%Y-%m-%d"))
            _set_text(hdr, "listversion", "2.0")
            _set_text(hdr, "exporterversion", "SpinDoctor")

            for g in sorted(bucket_games, key=lambda x: (x.description or x.name).lower()):
                _new_game_element(g, root=root)

            tree = ET.ElementTree(root)
            et_indent(tree)
            with open(out_path, "wb") as f:
                f.write(b'<?xml version="1.0"?>\n')
                tree.write(f, encoding="utf-8", xml_declaration=False)
            written[axis].append(out_path)

    return written


_BUCKET_FILE_SAFE = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")


def _safe_bucket_filename(name: str) -> str:
    """Sanitize a bucket value so it's a legal Windows/macOS/Linux filename."""
    for ch in _BUCKET_FILE_SAFE:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".") or "_"


def _new_game_element(game: "GameEntry", root=None):
    """Build a fresh <game> element with all canonical fields."""
    if _HAS_LXML and (root is None or hasattr(root, "nsmap")):
        if root is not None:
            el = LET.SubElement(root, "game")
        else:
            el = LET.Element("game")
    else:
        if root is not None:
            el = ET.SubElement(root, "game")
        else:
            el = ET.Element("game")

    el.set("name", game.name)
    _set_text(el, "description", game.description or game.name)
    _set_text(el, "cloneof", game.cloneof)
    _set_text(el, "crc", game.crc)
    _set_text(el, "manufacturer", game.manufacturer)
    _set_text(el, "year", game.year)
    _set_text(el, "genre", game.genre)
    _set_text(el, "rating", game.rating)
    # Only emit <players> when populated — HyperSpin treats an empty
    # element as "1 player" in some skins, which is misleading.
    if game.players:
        _set_text(el, "players", game.players)
    _set_text(el, "enabled", game.enabled or "Yes")
    return el
