"""find-global cross-system search command."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli


SAMPLE_DB = """<?xml version="1.0"?>
<menu>
  <header>
    <listname>{system}</listname>
    <listversion>2.0</listversion>
  </header>
{games}
</menu>
"""


def _game(name: str, description: str = "") -> str:
    desc = description or name
    return (
        f'  <game name="{name}">\n'
        f'    <description>{desc}</description>\n'
        f'    <enabled>Yes</enabled>\n'
        f'  </game>'
    )


def _write_db(databases_dir: Path, system: str, entries: list[str]) -> None:
    sys_dir = databases_dir / system
    sys_dir.mkdir(parents=True, exist_ok=True)
    body = SAMPLE_DB.format(
        system=system,
        games="\n".join(_game(*e if isinstance(e, tuple) else (e,))
                        for e in entries),
    )
    (sys_dir / f"{system}.xml").write_text(body, encoding="utf-8")


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json",
    )
    config_mod.reset_override_cache()

    roms = tmp_path / "roms"
    hs = tmp_path / "hyperspin"
    (hs / "Databases").mkdir(parents=True)
    (hs / "Media").mkdir(parents=True)

    for sys_name in ("MAME", "Sega Naomi", "Sega Dreamcast"):
        (roms / sys_name).mkdir(parents=True)
        (hs / "Databases" / sys_name).mkdir()

    _write_db(hs / "Databases", "MAME", [
        ("hotd", "House of the Dead"),
        ("pacman", "Pac-Man"),
    ])
    _write_db(hs / "Databases", "Sega Naomi", [
        ("hotd2", "House of the Dead 2"),
        ("crazytaxi", "Crazy Taxi"),
    ])
    _write_db(hs / "Databases", "Sega Dreamcast", [
        ("hotd2dc", "House of the Dead 2 (Dreamcast)"),
    ])

    cfg = config_mod.Config(
        roms_dir=str(roms),
        hyperspin_dir=str(hs),
    )
    config_mod.save_config(cfg)
    return tmp_path


def test_find_global_returns_matches_across_systems(cabinet):
    runner = CliRunner()
    res = runner.invoke(cli, ["find-global", "house of the dead"])
    assert res.exit_code == 0, res.output
    # All three systems carry a House of the Dead title.
    assert "MAME" in res.output
    assert "Sega Naomi" in res.output
    assert "Sega Dreamcast" in res.output
    assert "3 match" in res.output


def test_find_global_substring_match(cabinet):
    runner = CliRunner()
    res = runner.invoke(cli, ["find-global", "pac"])
    assert res.exit_code == 0
    assert "Pac-Man" in res.output


def test_find_global_no_matches(cabinet):
    runner = CliRunner()
    res = runner.invoke(cli, ["find-global", "metal slug"])
    assert res.exit_code == 0
    assert "No matches" in res.output


def test_find_global_exact_flag(cabinet):
    runner = CliRunner()
    # Substring would match many; --exact narrows to one.
    res = runner.invoke(cli, ["find-global", "Pac-Man", "--exact"])
    assert res.exit_code == 0
    assert "1 match" in res.output
