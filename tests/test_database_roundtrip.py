"""XML round-trip tests for HyperspinDatabase.

When ``lxml`` is installed, comments and unknown attributes/elements added by
HyperHQ or other tools must survive a save() round-trip.
"""
from __future__ import annotations

import textwrap

import pytest

from spindoctor.database import GameEntry, HyperspinDatabase

try:
    import lxml  # noqa: F401
    HAS_LXML = True
except ImportError:
    HAS_LXML = False


SAMPLE_XML = textwrap.dedent("""\
    <?xml version="1.0"?>
    <menu>
      <header>
        <listname>MAME</listname>
        <listversion>2.0</listversion>
      </header>
      <!-- HyperHQ added: leave this comment alone -->
      <game name="1942" custom_attr="hq-edited">
        <description>1942</description>
        <manufacturer>Capcom</manufacturer>
        <year>1984</year>
        <genre>Shooter</genre>
        <enabled>Yes</enabled>
      </game>
      <game name="pacman">
        <description>Pac-Man</description>
        <manufacturer>Namco</manufacturer>
        <year>1980</year>
        <genre>Maze</genre>
        <enabled>Yes</enabled>
      </game>
    </menu>
    """)


def _write(tmp_path, content):
    p = tmp_path / "MAME.xml"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_parses_known_games(tmp_path):
    p = _write(tmp_path, SAMPLE_XML)
    db = HyperspinDatabase("MAME", p)
    db.load()
    assert set(db.games().keys()) == {"1942", "pacman"}
    assert db.get("1942").year == "1984"
    assert db.get("pacman").manufacturer == "Namco"


def test_roundtrip_updates_existing_game_in_place(tmp_path):
    p = _write(tmp_path, SAMPLE_XML)
    db = HyperspinDatabase("MAME", p)
    db.load()
    g = db.get("1942")
    g.genre = "Vertical Shooter"
    db.update_game(g)
    db.save(backup=False)

    re_db = HyperspinDatabase("MAME", p)
    re_db.load()
    assert re_db.get("1942").genre == "Vertical Shooter"
    # Other fields must survive.
    assert re_db.get("1942").year == "1984"
    assert re_db.get("pacman").description == "Pac-Man"


@pytest.mark.skipif(not HAS_LXML, reason="lxml needed for comment preservation")
def test_roundtrip_preserves_xml_comments(tmp_path):
    p = _write(tmp_path, SAMPLE_XML)
    db = HyperspinDatabase("MAME", p)
    db.load()
    db.save(backup=False)
    saved = p.read_text(encoding="utf-8")
    assert "HyperHQ added: leave this comment alone" in saved


@pytest.mark.skipif(not HAS_LXML, reason="lxml needed for unknown-attr preservation")
def test_roundtrip_preserves_custom_attribute(tmp_path):
    p = _write(tmp_path, SAMPLE_XML)
    db = HyperspinDatabase("MAME", p)
    db.load()
    db.save(backup=False)
    saved = p.read_text(encoding="utf-8")
    assert 'custom_attr="hq-edited"' in saved


def test_add_new_game(tmp_path):
    p = _write(tmp_path, SAMPLE_XML)
    db = HyperspinDatabase("MAME", p)
    db.load()
    db.add_game(GameEntry(name="galaga", description="Galaga", year="1981"))
    db.save(backup=False)

    re_db = HyperspinDatabase("MAME", p)
    re_db.load()
    assert re_db.get("galaga") is not None
    assert re_db.get("galaga").year == "1981"


def test_remove_game(tmp_path):
    p = _write(tmp_path, SAMPLE_XML)
    db = HyperspinDatabase("MAME", p)
    db.load()
    db.remove_game("pacman")
    db.save(backup=False)

    re_db = HyperspinDatabase("MAME", p)
    re_db.load()
    assert "pacman" not in re_db.games()
    assert "1942" in re_db.games()


def test_save_creates_fresh_file_when_no_existing(tmp_path):
    p = tmp_path / "NEW.xml"
    db = HyperspinDatabase("NEW", p)
    db.load()  # file does not exist
    db.add_game(GameEntry(name="x", description="X", year="2000"))
    db.save(backup=False)
    assert p.exists()
    re_db = HyperspinDatabase("NEW", p)
    re_db.load()
    assert "x" in re_db.games()
