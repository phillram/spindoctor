"""Main Menu editor: load, edit, save round-trip and discovery."""
from __future__ import annotations

import textwrap
import xml.etree.ElementTree as ET

import pytest

from spindoctor.config import Config
from spindoctor.mainmenu import (
    add_system,
    discover_systems,
    hide,
    load_main_menu,
    move_down,
    move_up,
    remove_system,
    reorder,
    save_main_menu,
    show,
    sort_alphabetical,
    sort_by_field,
)


SAMPLE_MENU_XML = textwrap.dedent("""\
    <?xml version="1.0"?>
    <menu>
      <header>
        <listname>Main Menu</listname>
        <listversion>2.0</listversion>
      </header>
      <!-- HyperHQ added: keep this comment -->
      <game name="MAME">
        <description>MAME</description>
        <manufacturer>Various</manufacturer>
        <year>1975</year>
        <enabled>Yes</enabled>
      </game>
      <game name="Sony Playstation">
        <description>Sony Playstation</description>
        <manufacturer>Sony</manufacturer>
        <year>1994</year>
        <enabled>Yes</enabled>
      </game>
      <game name="Nintendo 64">
        <description>Nintendo 64</description>
        <manufacturer>Nintendo</manufacturer>
        <year>1996</year>
        <enabled>Yes</enabled>
      </game>
    </menu>
    """)


def _config(tmp_path) -> Config:
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    cfg.backup_before_modify = False
    return cfg


def _seed_menu(tmp_path, content: str = SAMPLE_MENU_XML):
    db_dir = tmp_path / "Databases" / "Main Menu"
    db_dir.mkdir(parents=True, exist_ok=True)
    p = db_dir / "Main Menu.xml"
    p.write_text(content, encoding="utf-8")
    return p


def _names_in(path):
    return [g.get("name") for g in ET.parse(path).getroot().findall("game")]


def test_load_returns_ordered_entries(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    assert menu.systems() == ["MAME", "Sony Playstation", "Nintendo 64"]
    assert menu.get("MAME").enabled == "Yes"


def test_reorder_then_save_roundtrip(tmp_path):
    path = _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    reorder(menu, "Nintendo 64", 1)
    assert menu.systems() == ["Nintendo 64", "MAME", "Sony Playstation"]
    save_main_menu(menu, cfg)

    re_menu = load_main_menu(cfg)
    assert re_menu.systems() == ["Nintendo 64", "MAME", "Sony Playstation"]
    # Saved file actually reflects the order on disk.
    assert _names_in(path) == ["Nintendo 64", "MAME", "Sony Playstation"]


def test_move_up_and_down(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    move_up(menu, "Nintendo 64")
    assert menu.systems() == ["MAME", "Nintendo 64", "Sony Playstation"]
    move_down(menu, "MAME")
    assert menu.systems() == ["Nintendo 64", "MAME", "Sony Playstation"]


def test_hide_and_show_toggle_enabled(tmp_path):
    path = _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    hide(menu, "Sony Playstation")
    save_main_menu(menu, cfg)

    re_menu = load_main_menu(cfg)
    assert re_menu.get("Sony Playstation").enabled == "No"
    assert not re_menu.get("Sony Playstation").visible

    show(re_menu, "Sony Playstation")
    save_main_menu(re_menu, cfg)
    third = load_main_menu(cfg)
    assert third.get("Sony Playstation").enabled == "Yes"


def test_add_and_remove_system(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)

    assert add_system(menu, "Atari Jaguar") is True
    assert add_system(menu, "Atari Jaguar") is False  # idempotent
    save_main_menu(menu, cfg)

    re_menu = load_main_menu(cfg)
    assert "Atari Jaguar" in re_menu.systems()

    assert remove_system(re_menu, "MAME") is True
    save_main_menu(re_menu, cfg)
    third = load_main_menu(cfg)
    assert "MAME" not in third.systems()
    assert "Atari Jaguar" in third.systems()


def test_reorder_invalid_position_raises(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    with pytest.raises(ValueError):
        reorder(menu, "MAME", 0)
    with pytest.raises(KeyError):
        reorder(menu, "Bogus", 1)


def test_sort_alphabetical(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    sort_alphabetical(menu)
    assert menu.systems() == ["MAME", "Nintendo 64", "Sony Playstation"]


def test_sort_by_year(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    sort_by_field(menu, "year")
    assert menu.systems() == ["MAME", "Sony Playstation", "Nintendo 64"]


def test_discover_systems_finds_unlisted_db_folders(tmp_path):
    _seed_menu(tmp_path)
    # Add a system folder under Databases/ that's NOT in Main Menu.
    extra = tmp_path / "Databases" / "Atari Jaguar"
    extra.mkdir(parents=True)
    (extra / "Atari Jaguar.xml").write_text(
        '<?xml version="1.0"?><menu><header/></menu>', encoding="utf-8"
    )
    # And a system that IS listed should not appear.
    listed = tmp_path / "Databases" / "MAME"
    listed.mkdir(parents=True)
    (listed / "MAME.xml").write_text(
        '<?xml version="1.0"?><menu><header/></menu>', encoding="utf-8"
    )

    cfg = _config(tmp_path)
    extras = discover_systems(cfg)
    assert "Atari Jaguar" in extras
    assert "MAME" not in extras


def test_save_creates_backup_when_configured(tmp_path):
    path = _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    cfg.backup_before_modify = True
    menu = load_main_menu(cfg)
    move_up(menu, "Nintendo 64")
    save_main_menu(menu, cfg)
    backups = list(path.parent.glob("Main Menu.*.bak"))
    assert backups, "expected a .bak file alongside Main Menu.xml"


def test_save_to_output_dir_routes_elsewhere(tmp_path):
    _seed_menu(tmp_path)
    cfg = _config(tmp_path)
    menu = load_main_menu(cfg)
    reorder(menu, "Nintendo 64", 1)
    out_dir = tmp_path / "out"
    out_path = save_main_menu(menu, cfg, output_dir=out_dir)
    assert out_path == out_dir / "Databases" / "Main Menu" / "Main Menu.xml"
    assert out_path.exists()
    assert _names_in(out_path)[0] == "Nintendo 64"
    # Original file is untouched.
    original = tmp_path / "Databases" / "Main Menu" / "Main Menu.xml"
    assert _names_in(original)[0] == "MAME"
