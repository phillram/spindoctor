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
    # Sorted output, but all three should be there
    assert set(_systems_in(path)) == {"MAME", "SNES", "PS3"}


def test_upsert_idempotent(config):
    upsert_main_menu_system("PS3", config)
    path, added = upsert_main_menu_system("PS3", config)
    assert added is False
    assert _systems_in(path).count("PS3") == 1
