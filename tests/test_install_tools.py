"""End-to-end tests for `spindoctor install-tools`.

Uses Click's CliRunner with a tmp HOME / cabinet layout so all writes
land under tmp_path. Two main scenarios:

1. The default mode — bats only, written under
   `<rl>/Modules/HyperLaunch/Tools/spindoctor/`.
2. The `--add-to-system` mode — bats + per-game PCLauncher INIs +
   `<game>` entries in the target system's database XML.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli
from spindoctor.database import HyperspinDatabase


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
    rl = tmp_path / "rocketlauncher"
    for d in (roms, hs / "Databases", hs / "Media", rl / "Settings"):
        d.mkdir(parents=True)

    cfg = config_mod.Config(
        roms_dir=str(roms),
        hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
        emulators_dir=str(tmp_path / "emulators"),
    )
    config_mod.save_config(cfg)
    yield {"roms": roms, "hs": hs, "rl": rl, "home": home}
    config_mod.reset_override_cache()


def test_install_tools_default_writes_bats_under_hyperlaunch_tools(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["install-tools"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    out_dir = (cabinet["rl"] / "Modules" / "HyperLaunch" / "Tools"
               / "spindoctor")
    for expected in (
        "Refresh Favorites.bat",
        "Refresh Recently Played.bat",
        "Refresh Most Played.bat",
        "Refresh Both.bat",
    ):
        assert (out_dir / expected).exists(), f"missing {expected}"


def test_install_tools_add_to_system_creates_db_entries_and_inis(cabinet):
    # Pre-create an empty Toolkit database so the command has somewhere
    # to upsert into. The CLI errors if the DB doesn't exist (matches
    # the "system must already exist" UX in the docs).
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["install-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # Bats + INIs land under PCLauncher/<system>/, not under
    # HyperLaunch/Tools, so the per-game INIs sit next to the bats they
    # launch.
    pcl_dir = (cabinet["rl"] / "Modules" / "PCLauncher" / "Toolkit")
    for expected_bat in (
        "Refresh Favorites.bat",
        "Refresh Recently Played.bat",
        "Refresh Most Played.bat",
        "Refresh Both.bat",
    ):
        assert (pcl_dir / expected_bat).exists(), f"missing {expected_bat}"
        ini = pcl_dir / expected_bat.replace(".bat", ".ini")
        assert ini.exists(), f"missing INI for {expected_bat}"
        body = ini.read_text(encoding="utf-8")
        # The INI's applicationpath must point at the bat that lives
        # alongside it — without this, PCLauncher launches the wrong
        # thing.
        assert str(pcl_dir / expected_bat) in body

    # Database now has entries with HyperSpin-friendly metadata.
    db = HyperspinDatabase("Toolkit", db_path)
    db.load()
    games = db.games()
    for expected_name in (
        "Refresh Favorites",
        "Refresh Recently Played",
        "Refresh Most Played",
        "Refresh Both",
    ):
        assert expected_name in games, f"missing <game name=\"{expected_name}\"/>"
        assert games[expected_name].genre == "Tools"
        assert games[expected_name].manufacturer == "SpinDoctor"


def test_install_tools_add_to_system_errors_when_db_missing(cabinet):
    # No Toolkit.xml on disk → command should error rather than silently
    # creating one (matches the "system must already exist" guarantee
    # in the help text and avoids creating phantom systems on typos).
    runner = CliRunner()
    result = runner.invoke(
        cli, ["install-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "Database" in result.output


def test_install_tools_add_to_system_overwrites_existing_entries(cabinet):
    # Re-running --add-to-system should be idempotent: the second run
    # overwrites the entries from the first without raising.
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    for _ in range(2):
        result = runner.invoke(
            cli, ["install-tools", "--add-to-system", "Toolkit"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    db = HyperspinDatabase("Toolkit", db_path)
    db.load()
    # Still exactly the four expected entries — no duplicates from the
    # second invocation.
    expected = {
        "Refresh Favorites", "Refresh Recently Played",
        "Refresh Most Played", "Refresh Both",
    }
    assert set(db.games().keys()) == expected
