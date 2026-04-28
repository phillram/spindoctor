"""HyperSpin sort-database generation."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from spindoctor.database import (
    GameEntry,
    _bucket_value,
    _letter_bucket,
    _safe_bucket_filename,
    write_sort_databases,
)


def test_letter_bucket_alpha_digit_other():
    assert _letter_bucket("Pac-Man") == "P"
    assert _letter_bucket("1942") == "0-9"
    assert _letter_bucket("[Bios]") == "B"   # leading bracket stripped
    assert _letter_bucket("@") == "#"
    assert _letter_bucket("") == "#"


def test_bucket_value_matches_axis():
    g = GameEntry(name="x", description="X-Men", year="1992",
                  manufacturer="Capcom", genre="Beat 'em up")
    assert _bucket_value(g, "year") == "1992"
    assert _bucket_value(g, "letter") == "X"
    assert _bucket_value(g, "manufacturer") == "Capcom"


def test_safe_bucket_filename_removes_path_separators():
    assert _safe_bucket_filename("Action / Adventure") == "Action _ Adventure"
    assert _safe_bucket_filename("???") == "___"
    assert _safe_bucket_filename("Beat 'em up") == "Beat 'em up"


def test_write_sort_databases_creates_buckets(tmp_path):
    games = [
        GameEntry(name="1942", description="1942", year="1984",
                  manufacturer="Capcom", genre="Shooter"),
        GameEntry(name="pacman", description="Pac-Man", year="1980",
                  manufacturer="Namco", genre="Maze"),
        GameEntry(name="galaga", description="Galaga", year="1981",
                  manufacturer="Namco", genre="Shooter"),
    ]
    written = write_sort_databases("MAME", games, tmp_path)

    # Genre wheel: Shooter has two entries, Maze one
    shooter = tmp_path / "MAME" / "Genre" / "Shooter.xml"
    assert shooter.exists()
    names = {g.get("name") for g in ET.parse(shooter).getroot().findall("game")}
    assert names == {"1942", "galaga"}

    # Letter wheel: P bucket holds pacman
    p_letter = tmp_path / "MAME" / "Letter" / "P.xml"
    assert p_letter.exists()

    # Year wheel
    year_1984 = tmp_path / "MAME" / "Year" / "1984.xml"
    assert year_1984.exists()

    assert "genre" in written and len(written["genre"]) >= 1


def test_write_sort_databases_skips_existing_unless_overwrite(tmp_path):
    games = [GameEntry(name="x", description="X", genre="Misc")]
    written = write_sort_databases("MAME", games, tmp_path)
    assert written["genre"], "first write should create files"

    # Second write must NOT touch the existing file by default
    f = tmp_path / "MAME" / "Genre" / "Misc.xml"
    f.write_text("custom user data", encoding="utf-8")
    write_sort_databases("MAME", games, tmp_path, overwrite=False)
    assert f.read_text(encoding="utf-8") == "custom user data"

    # With overwrite=True it gets replaced
    write_sort_databases("MAME", games, tmp_path, overwrite=True)
    assert "<menu>" in f.read_text(encoding="utf-8")
