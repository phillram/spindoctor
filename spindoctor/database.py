"""Hyperspin XML database read/write."""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


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

    def load(self) -> None:
        if not self.xml_path.exists():
            self._loaded = True
            return
        try:
            tree = ET.parse(self.xml_path)
            root = tree.getroot()
            for game_el in root.findall("game"):
                name = game_el.get("name", "").strip()
                if not name:
                    continue
                entry = GameEntry(
                    name=name,
                    description=_text(game_el, "description"),
                    cloneof=_text(game_el, "cloneof"),
                    crc=_text(game_el, "crc"),
                    manufacturer=_text(game_el, "manufacturer"),
                    year=_text(game_el, "year"),
                    genre=_text(game_el, "genre"),
                    rating=_text(game_el, "rating"),
                    enabled=_text(game_el, "enabled") or "Yes",
                )
                self._games[name] = entry
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse {self.xml_path}: {e}") from e
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

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

    def iter_incomplete(self) -> Iterator[GameEntry]:
        self._ensure_loaded()
        return (g for g in self._games.values() if not g.is_metadata_complete())

    def save(self, output_path: Optional[Path] = None, backup: bool = True) -> Path:
        self._ensure_loaded()
        target = output_path or self.xml_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if backup and target.exists() and output_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(target, target.with_suffix(f".{stamp}.bak"))

        root = ET.Element("menu")
        header = ET.SubElement(root, "header")
        _set_text(header, "listname", self.system_name)
        _set_text(header, "lastlistupdate", datetime.now().strftime("%Y-%m-%d"))
        _set_text(header, "listversion", "2.0")
        _set_text(header, "exporterversion", "SpinDoctor")

        for game in sorted(self._games.values(), key=lambda g: g.name.lower()):
            el = ET.SubElement(root, "game", name=game.name)
            _set_text(el, "description", game.description or game.name)
            _set_text(el, "cloneof", game.cloneof)
            _set_text(el, "crc", game.crc)
            _set_text(el, "manufacturer", game.manufacturer)
            _set_text(el, "year", game.year)
            _set_text(el, "genre", game.genre)
            _set_text(el, "rating", game.rating)
            _set_text(el, "enabled", game.enabled or "Yes")

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        with open(target, "wb") as f:
            f.write(b'<?xml version="1.0"?>\n')
            tree.write(f, encoding="utf-8", xml_declaration=False)

        return target


def find_database(system_name: str, databases_dir: Path) -> Optional[Path]:
    """Locate the XML database file for a system."""
    system_db_dir = databases_dir / system_name
    if not system_db_dir.exists():
        return None
    candidates = list(system_db_dir.glob("*.xml"))
    if not candidates:
        return None
    # Prefer exact match on system name
    for c in candidates:
        if c.stem.lower() == system_name.lower():
            return c
    return candidates[0]


def load_database(system_name: str, databases_dir: Path) -> HyperspinDatabase:
    xml_path = find_database(system_name, databases_dir)
    if xml_path is None:
        # Return an empty database pointing to where it would be created
        xml_path = databases_dir / system_name / f"{system_name}.xml"
    db = HyperspinDatabase(system_name, xml_path)
    db.load()
    return db


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _set_text(parent: ET.Element, tag: str, text: str) -> None:
    el = ET.SubElement(parent, tag)
    el.text = text or ""
