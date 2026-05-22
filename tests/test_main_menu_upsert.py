"""Main Menu upsert preserves existing entries."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from spindoctor.config import Config
from spindoctor.rocketlauncher import (
    generate_hs_main_menu,
    upsert_main_menu_system,
)


def _systems_in(path):
    return [
        g.get("name") for g in ET.parse(path).getroot().findall("game")
    ]


@pytest.fixture
def config(tmp_path):
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    return cfg


def test_upsert_creates_file_when_missing(config):
    path, added = upsert_main_menu_system("PS3", config)
    assert added is True
    assert _systems_in(path) == ["PS3"]


def test_upsert_preserves_existing_entries(config):
    generate_hs_main_menu(["MAME", "SNES"], config)
    path, added = upsert_main_menu_system("PS3", config)
    assert added is True
    assert set(_systems_in(path)) == {"MAME", "SNES", "PS3"}


def test_upsert_idempotent(config):
    upsert_main_menu_system("PS3", config)
    path, added = upsert_main_menu_system("PS3", config)
    assert added is False
    assert _systems_in(path).count("PS3") == 1


def test_generate_preserves_existing_order(config):
    """A second generate-config call must not reorder already-present systems."""
    generate_hs_main_menu(["SNES", "MAME"], config)
    # Second call passes systems in a different order (as sorted() would);
    # PS3 is new. SNES and MAME must stay in their original positions.
    path = generate_hs_main_menu(["MAME", "PS3", "SNES"], config)
    assert _systems_in(path) == ["SNES", "MAME", "PS3"]


def test_generate_drops_removed_systems(config):
    """Systems no longer detected on disk must be removed from the menu."""
    generate_hs_main_menu(["MAME", "SNES", "N64"], config)
    path = generate_hs_main_menu(["MAME", "SNES"], config)
    assert _systems_in(path) == ["MAME", "SNES"]


def test_generated_main_menu_uses_native_minimal_format(config):
    """``generate_hs_main_menu`` must emit HyperSpin's native minimal format:
    bare ``<game name="..."/>`` entries, no XML declaration, no <header>,
    no empty child elements. The previous verbose output broke HyperSpin
    with "Error creating main menu"."""
    path = generate_hs_main_menu(["MAME", "SNES"], config)
    text = path.read_text(encoding="utf-8")

    assert "<?xml" not in text, "Main Menu must not have an XML declaration"
    assert "<header" not in text, "Main Menu must not have a <header> block"
    assert "<description>" not in text
    assert "<enabled>" not in text
    root = ET.fromstring(text)
    for game in root.findall("game"):
        assert list(game) == [], f"{game.get('name')} has unexpected children"
        assert game.get("enabled") is None, "visible entries must not carry enabled attr"
