"""add-system and generate-config keep Main Menu entries' attributes.

``upsert_main_menu_system`` (add-system) and ``generate_hs_main_menu``
(generate-config) rewrite Main Menu.xml.  They used to write ``name`` only,
so every wheel hidden with ``enabled="False"`` came back on the menu, and
``exe="true"`` on a Search entry was lost.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from spindoctor.config import Config
from spindoctor.rocketlauncher import (
    _read_main_menu_entries,
    _read_main_menu_systems,
    generate_hs_main_menu,
    upsert_main_menu_system,
)


# HyperSpin's own format, as HyperSpin ships it and `mainmenu` saves it.
NATIVE_MENU = (
    "<menu>\n"
    '  <game name="MAME"/>\n'
    '  <game name="Nintendo Game &amp; Watch"/>\n'
    '  <game name="Search" exe="true"/>\n'
    '  <game name="Nintendo 3DS" enabled="False"/>\n'
    '  <game name="Sega Genesis"/>\n'
    '  <game name="KODI" enabled="False"/>\n'
    "</menu>\n"
)


@pytest.fixture
def cfg(tmp_path):
    config = Config()
    config.hyperspin_dir = str(tmp_path)
    return config


def _seed(tmp_path, text=NATIVE_MENU):
    path = tmp_path / "Databases" / "Main Menu" / "Main Menu.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _entries(path):
    return [(g.get("name"), dict(g.attrib)) for g in ET.parse(path).getroot().findall("game")]


def test_upsert_keeps_hidden_wheels_hidden(tmp_path, cfg):
    _seed(tmp_path)
    path, added = upsert_main_menu_system("Sony Playstation 3", cfg)
    assert added is True
    entries = dict(_entries(path))
    assert entries["Nintendo 3DS"].get("enabled") == "False"
    assert entries["KODI"].get("enabled") == "False"
    assert "enabled" not in entries["Sony Playstation 3"]
    assert "enabled" not in entries["MAME"]


def test_upsert_keeps_other_attributes_and_order(tmp_path, cfg):
    _seed(tmp_path)
    path, _ = upsert_main_menu_system("Sony Playstation 3", cfg)
    assert [name for name, _ in _entries(path)] == [
        "MAME", "Nintendo Game & Watch", "Search", "Nintendo 3DS",
        "Sega Genesis", "KODI", "Sony Playstation 3",
    ]
    assert dict(_entries(path))["Search"].get("exe") == "true"


def test_upsert_changes_nothing_but_the_new_line(tmp_path, cfg):
    pytest.importorskip("lxml")
    _seed(tmp_path)
    path, _ = upsert_main_menu_system("Sony Playstation 3", cfg)
    expected = NATIVE_MENU.replace(
        "</menu>\n", '  <game name="Sony Playstation 3"/>\n</menu>\n'
    )
    assert path.read_bytes() == expected.encode("utf-8")


def test_upsert_of_a_listed_system_leaves_the_file_alone(tmp_path, cfg):
    path = _seed(tmp_path)
    before = path.read_bytes()
    _, added = upsert_main_menu_system("Nintendo 3DS", cfg)
    assert added is False
    assert path.read_bytes() == before


def test_generate_keeps_hidden_flags_of_kept_systems(tmp_path, cfg):
    _seed(tmp_path)
    path = generate_hs_main_menu(
        ["MAME", "Nintendo Game & Watch", "Nintendo 3DS", "Sega Genesis", "Atari 2600"],
        cfg,
    )
    entries = _entries(path)
    # Order kept, dropped systems gone, new ones last (unchanged behaviour).
    assert [name for name, _ in entries] == [
        "MAME", "Nintendo Game & Watch", "Nintendo 3DS", "Sega Genesis", "Atari 2600",
    ]
    attrs = dict(entries)
    assert attrs["Nintendo 3DS"].get("enabled") == "False"
    assert "enabled" not in attrs["Atari 2600"]


def test_generate_keeps_hidden_synthetic_wheel_hidden(tmp_path, cfg):
    _seed(
        tmp_path,
        "<menu>\n"
        '  <game name="MAME"/>\n'
        '  <game name="Most Played" enabled="False"/>\n'
        "</menu>\n",
    )
    path = generate_hs_main_menu(["MAME"], cfg)
    assert dict(_entries(path))["Most Played"].get("enabled") == "False"


def test_legacy_enabled_child_becomes_the_attribute(tmp_path, cfg):
    _seed(
        tmp_path,
        "<menu>\n"
        '  <game name="MAME"><enabled>Yes</enabled></game>\n'
        '  <game name="KODI"><enabled>No</enabled></game>\n'
        "</menu>\n",
    )
    path, _ = upsert_main_menu_system("Sega Genesis", cfg)
    root = ET.parse(path).getroot()
    games = {g.get("name"): g for g in root.findall("game")}
    assert games["KODI"].get("enabled") == "False"
    assert games["MAME"].get("enabled") is None
    assert all(list(g) == [] for g in games.values()), "native format has no children"


def test_read_entries_and_systems(tmp_path):
    path = _seed(tmp_path)
    entries = _read_main_menu_entries(path)
    assert entries[3] == ("Nintendo 3DS", {"enabled": "False"})
    assert _read_main_menu_systems(path) == [name for name, _ in entries]


def test_read_entries_of_a_missing_file(tmp_path):
    assert _read_main_menu_entries(tmp_path / "nope.xml") == []
