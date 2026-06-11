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


def test_generate_preserves_synthetic_wheels(config):
    """generate-config must never remove synthetic wheel entries.

    Favorites, Recently Played, and Most Played are excluded from the
    systems list passed to generate_hs_main_menu (they are in
    SKIP_GENERATE_CONFIG).  Without explicit preservation they would be
    silently dropped from Main Menu.xml on every generate-config run.
    """
    # Simulate a working setup: all three synthetic wheels on the menu.
    generate_hs_main_menu(["MAME", "SNES"], config)
    from spindoctor.mainmenu import add_system, load_main_menu, save_main_menu
    menu = load_main_menu(config)
    add_system(menu, "Favorites")
    add_system(menu, "Recently Played")
    add_system(menu, "Most Played")
    save_main_menu(menu, config)

    # Simulate generate-config being run: systems list does NOT include
    # the synthetic wheels (they are in SKIP_GENERATE_CONFIG).
    path = generate_hs_main_menu(["MAME", "SNES"], config)
    systems = _systems_in(path)
    assert "Favorites" in systems, "generate-config must not drop Favorites"
    assert "Recently Played" in systems, "generate-config must not drop Recently Played"
    assert "Most Played" in systems, "generate-config must not drop Most Played"
    # Real arcade systems are still present.
    assert "MAME" in systems
    assert "SNES" in systems


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
