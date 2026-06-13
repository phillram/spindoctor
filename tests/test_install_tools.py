"""End-to-end tests for `spindoctor install-tools`.

Uses Click's CliRunner with a tmp HOME / cabinet layout so all writes
land under tmp_path. Two main scenarios:

1. The default mode — bats only, written under
   `<rl>/Modules/HyperLaunch/Tools/spindoctor/`.
2. The `--add-to-system` mode — bats + per-game PCLauncher INIs +
   `<game>` entries in the target system's database XML.
"""
from __future__ import annotations

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
        "Refresh All.bat",
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
        "Refresh All.bat",
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
        "Refresh All",
    ):
        assert expected_name in games, f"missing <game name=\"{expected_name}\"/>"
        assert games[expected_name].genre == "Tools"
        assert games[expected_name].manufacturer == "SpinDoctor"

    # The RocketLauncher system INI must be written so RL knows to use
    # PCLauncher for this system.  Without it, RL has no emulator mapping
    # and PCLauncher throws "does not know what exe / FadeTitle to watch
    # for" even when every per-game INI is in place.
    sys_ini = cabinet["rl"] / "Settings" / "Toolkit.ini"
    assert sys_ini.exists(), "Settings/Toolkit.ini was not written"
    body = sys_ini.read_text(encoding="utf-8")
    assert "Default_Emulator=PCLauncher" in body
    assert "Rom_Extension=ini" in body
    assert str(pcl_dir) in body

    # The folder-based Emulators.ini must also be written for RL
    # installations that use Settings/<system>/Emulators.ini instead of
    # the flat Settings/<system>.ini file for emulator routing.
    emulators_ini = cabinet["rl"] / "Settings" / "Toolkit" / "Emulators.ini"
    assert emulators_ini.exists(), "Settings/Toolkit/Emulators.ini was not written"
    emu_body = emulators_ini.read_text(encoding="utf-8")
    assert "[ROMS]" in emu_body, "section must be [ROMS] for folder-layout Emulators.ini (not [Settings])"
    assert "Default_Emulator=PCLauncher" in emu_body
    assert "Rom_Extension=ini" in emu_body


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


def test_install_tools_add_to_system_respects_existing_emulators_ini_rom_path(cabinet):
    """When Settings/<system>/Emulators.ini already exists with a custom
    Rom_Path, install-tools writes bat + ini files to that path — not to
    the default Modules/PCLauncher/<system> — so PCLauncher can find them
    and the "not set up in RocketLauncherUI" error does not occur."""
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )

    # Simulate the real cabinet: Toolkit's Emulators.ini points to a
    # Utilities directory outside the PCLauncher modules folder.
    rl = cabinet["rl"]
    utilities_dir = rl.parent / "Utilities" / "Toolkit"
    utilities_dir.mkdir(parents=True)
    emulators_ini_dir = rl / "Settings" / "Toolkit"
    emulators_ini_dir.mkdir(parents=True)
    # Use a relative path (as the real cabinet does): "../Utilities/Toolkit"
    # resolves to utilities_dir when joined to the RL dir.
    rel_path = "../Utilities/Toolkit"
    (emulators_ini_dir / "Emulators.ini").write_text(
        f"[ROMS]\r\nDefault_Emulator=PCLauncher\r\nRom_Path={rel_path}\r\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["install-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # Bat + ini files must land in utilities_dir, NOT in Modules/PCLauncher/Toolkit.
    pcl_dir = rl / "Modules" / "PCLauncher" / "Toolkit"
    for stem in ("Refresh Favorites", "Refresh Recently Played", "Refresh Most Played"):
        assert (utilities_dir / f"{stem}.bat").exists(), (
            f"{stem}.bat missing from utilities_dir"
        )
        assert (utilities_dir / f"{stem}.ini").exists(), (
            f"{stem}.ini missing from utilities_dir"
        )
        assert not (pcl_dir / f"{stem}.bat").exists(), (
            f"{stem}.bat should NOT be in pcl_dir"
        )

    # The INI's ApplicationPath must point at the bat in utilities_dir.
    ini_body = (utilities_dir / "Refresh Favorites.ini").read_text(encoding="utf-8")
    assert str(utilities_dir / "Refresh Favorites.bat") in ini_body


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
        "Refresh Most Played", "Refresh All",
    }
    assert set(db.games().keys()) == expected

    # System INI must exist after both runs.
    sys_ini = cabinet["rl"] / "Settings" / "Toolkit.ini"
    assert sys_ini.exists(), "Settings/Toolkit.ini missing after idempotent re-run"
    assert "Default_Emulator=PCLauncher" in sys_ini.read_text(encoding="utf-8")


# ─── stale-file cleanup tests ────────────────────────────────────────────────


def test_install_tools_removes_stale_refresh_both_bat(cabinet):
    """install-tools removes 'Refresh Both.bat' left by an older version."""
    out_dir = (cabinet["rl"] / "Modules" / "HyperLaunch" / "Tools" / "spindoctor")
    out_dir.mkdir(parents=True)
    (out_dir / "Refresh Both.bat").write_text("@echo off\r\n", encoding="utf-8")
    (out_dir / "Refresh Both.ini").write_text("[Settings]\r\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["install-tools"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    assert not (out_dir / "Refresh Both.bat").exists(), (
        "Refresh Both.bat must be removed by install-tools migration"
    )
    assert not (out_dir / "Refresh Both.ini").exists()
    assert (out_dir / "Refresh All.bat").exists(), "Refresh All.bat must still be written"


def test_install_tools_add_to_system_removes_stale_refresh_both_db_entry(cabinet):
    """install-tools --add-to-system removes the stale 'Refresh Both' DB entry."""
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"

    from spindoctor.database import GameEntry
    db_init = HyperspinDatabase("Toolkit", db_path)
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )
    db_init.load()
    db_init.upsert_game(GameEntry(
        name="Refresh Both", description="Refresh Both",
        manufacturer="SpinDoctor", year="", genre="Tools",
        players="1", enabled="Yes",
    ))
    db_init.save(backup=False)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["install-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    db = HyperspinDatabase("Toolkit", db_path)
    db.load()
    assert "Refresh Both" not in db.games(), (
        "'Refresh Both' DB entry must be removed by install-tools migration"
    )
    assert "Refresh All" in db.games(), "current 'Refresh All' entry must be present"


# ─── uninstall-tools tests ────────────────────────────────────────────────────


def test_uninstall_tools_default_removes_bats_from_hyperlaunch_tools(cabinet):
    """Default mode (no --add-to-system) removes bats from HyperLaunch/Tools."""
    runner = CliRunner()

    # Install first so there are files to remove.
    result = runner.invoke(cli, ["install-tools"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    out_dir = (cabinet["rl"] / "Modules" / "HyperLaunch" / "Tools"
               / "spindoctor")
    # Confirm the bats exist before uninstalling.
    assert (out_dir / "Refresh Favorites.bat").exists()

    result = runner.invoke(cli, ["uninstall-tools", "--apply"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    for stem in ("Refresh Favorites", "Refresh Recently Played",
                 "Refresh Most Played", "Refresh Both"):
        assert not (out_dir / f"{stem}.bat").exists(), (
            f"{stem}.bat should have been removed"
        )


def test_uninstall_tools_default_is_idempotent_when_nothing_installed(cabinet):
    """Running uninstall-tools when no bats exist should succeed (exit 0)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["uninstall-tools", "--apply"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "nothing to delete" in result.output.lower()


def test_uninstall_tools_add_to_system_removes_bats_inis_and_db_entries(cabinet):
    """--add-to-system removes bats, INIs, and database XML entries."""
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )

    runner = CliRunner()

    # Install first.
    result = runner.invoke(
        cli, ["install-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    pcl_dir = cabinet["rl"] / "Modules" / "PCLauncher" / "Toolkit"

    # Confirm install wrote files.
    assert (pcl_dir / "Refresh Favorites.bat").exists()
    db = HyperspinDatabase("Toolkit", db_path)
    db.load()
    assert "Refresh Favorites" in db.games()

    # Now uninstall.
    result = runner.invoke(
        cli, ["uninstall-tools", "--add-to-system", "Toolkit", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # All SpinDoctor-written bats and INIs must be gone.
    for stem in ("Refresh Favorites", "Refresh Recently Played",
                 "Refresh Most Played", "Refresh Both"):
        assert not (pcl_dir / f"{stem}.bat").exists(), (
            f"{stem}.bat should have been removed"
        )
        assert not (pcl_dir / f"{stem}.ini").exists(), (
            f"{stem}.ini should have been removed"
        )

    # Database entries must be gone.
    db2 = HyperspinDatabase("Toolkit", db_path)
    db2.load()
    for name in ("Refresh Favorites", "Refresh Recently Played",
                 "Refresh Most Played", "Refresh Both", "Refresh All"):
        assert name not in db2.games(), (
            f"<game name=\"{name}\"/> should have been removed from the DB"
        )


def test_uninstall_tools_add_to_system_handles_legacy_refresh_both_files(cabinet):
    """uninstall-tools removes 'Refresh Both' files even when 'Refresh All' was
    also installed (or vice-versa). Verifies both current and renamed stems."""
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"

    # Seed the database with both the current name ("Refresh Both") and the
    # renamed variant ("Refresh All") to simulate a cabinet that was partially
    # migrated.
    db_init = HyperspinDatabase("Toolkit", db_path)
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )
    db_init.load()
    from spindoctor.database import GameEntry
    for name in ("Refresh Both", "Refresh All"):
        db_init.upsert_game(GameEntry(
            name=name, description=name,
            manufacturer="SpinDoctor", year="", genre="Tools",
            players="1", enabled="Yes",
        ))
    db_init.save(backup=False)

    pcl_dir = cabinet["rl"] / "Modules" / "PCLauncher" / "Toolkit"
    pcl_dir.mkdir(parents=True)
    # Write both bat + ini on disk to simulate a mixed install.
    for stem in ("Refresh Both", "Refresh All"):
        (pcl_dir / f"{stem}.bat").write_text("@echo off\r\n", encoding="utf-8")
        (pcl_dir / f"{stem}.ini").write_text("[Settings]\r\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["uninstall-tools", "--add-to-system", "Toolkit", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # Both files must have been removed.
    for stem in ("Refresh Both", "Refresh All"):
        assert not (pcl_dir / f"{stem}.bat").exists()
        assert not (pcl_dir / f"{stem}.ini").exists()

    # Both DB entries must be gone.
    db2 = HyperspinDatabase("Toolkit", db_path)
    db2.load()
    assert "Refresh Both" not in db2.games()
    assert "Refresh All" not in db2.games()


def test_uninstall_tools_removes_files_from_existing_rom_path(cabinet):
    """When Settings/<system>/Emulators.ini has a custom Rom_Path,
    uninstall-tools removes files from that detected directory."""
    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )

    rl = cabinet["rl"]
    utilities_dir = rl.parent / "Utilities" / "Toolkit"
    utilities_dir.mkdir(parents=True)
    emulators_ini_dir = rl / "Settings" / "Toolkit"
    emulators_ini_dir.mkdir(parents=True)
    (emulators_ini_dir / "Emulators.ini").write_text(
        "[ROMS]\r\nDefault_Emulator=PCLauncher\r\nRom_Path=../Utilities/Toolkit\r\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    # Install — files land in utilities_dir.
    result = runner.invoke(
        cli, ["install-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert (utilities_dir / "Refresh Favorites.bat").exists()

    # Uninstall — files must be removed from utilities_dir.
    result = runner.invoke(
        cli, ["uninstall-tools", "--add-to-system", "Toolkit", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    for stem in ("Refresh Favorites", "Refresh Recently Played", "Refresh Most Played"):
        assert not (utilities_dir / f"{stem}.bat").exists(), (
            f"{stem}.bat should have been removed from utilities_dir"
        )
        assert not (utilities_dir / f"{stem}.ini").exists(), (
            f"{stem}.ini should have been removed from utilities_dir"
        )


def test_uninstall_tools_add_to_system_also_removes_legacy_pcl_files(cabinet):
    """uninstall-tools removes files from Modules/PCLauncher/<system> even
    when the detected Rom_Path is different — for cabinets that had files
    written there by an older version of install-tools."""
    rl = cabinet["rl"]
    utilities_dir = rl.parent / "Utilities" / "Toolkit"
    utilities_dir.mkdir(parents=True)
    emulators_ini_dir = rl / "Settings" / "Toolkit"
    emulators_ini_dir.mkdir(parents=True)
    (emulators_ini_dir / "Emulators.ini").write_text(
        "[ROMS]\r\nDefault_Emulator=PCLauncher\r\nRom_Path=../Utilities/Toolkit\r\n",
        encoding="utf-8",
    )

    # Manually place legacy files in the old default location (as a previous
    # version of install-tools would have done before this fix).
    pcl_dir = rl / "Modules" / "PCLauncher" / "Toolkit"
    pcl_dir.mkdir(parents=True)
    (pcl_dir / "Refresh Favorites.bat").write_text("@echo off\r\n", encoding="utf-8")
    (pcl_dir / "Refresh Favorites.ini").write_text("[Settings]\r\n", encoding="utf-8")

    toolkit_dir = cabinet["hs"] / "Databases" / "Toolkit"
    toolkit_dir.mkdir(parents=True)
    db_path = toolkit_dir / "Toolkit.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["uninstall-tools", "--add-to-system", "Toolkit", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # Legacy files in the old default location must be gone.
    assert not (pcl_dir / "Refresh Favorites.bat").exists()
    assert not (pcl_dir / "Refresh Favorites.ini").exists()


def test_uninstall_tools_add_to_system_skips_missing_db(cabinet):
    """uninstall-tools with --add-to-system succeeds even when the database
    XML doesn't exist (prints a warning but exits 0)."""
    # Create the PCLauncher directory with one bat so there's something to
    # delete — only the DB step is skipped.
    pcl_dir = cabinet["rl"] / "Modules" / "PCLauncher" / "Toolkit"
    pcl_dir.mkdir(parents=True)
    (pcl_dir / "Refresh Favorites.bat").write_text("@echo off\r\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["uninstall-tools", "--add-to-system", "Toolkit", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert not (pcl_dir / "Refresh Favorites.bat").exists()


def test_uninstall_tools_add_to_system_is_idempotent(cabinet):
    """Running uninstall-tools twice in a row should succeed both times."""
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

    for _ in range(2):
        result = runner.invoke(
            cli, ["uninstall-tools", "--add-to-system", "Toolkit", "--apply"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output


# ─── uninstall-tools dry-run tests ───────────────────────────────────────────


def test_uninstall_tools_dry_run_does_not_delete_files(cabinet):
    """Without --apply, uninstall-tools must not delete any files.

    This is the bug that was reported: the GUI showed "DRY RUN" but the
    command deleted files anyway because there was no --apply gate.
    """
    runner = CliRunner()

    # Install first.
    result = runner.invoke(cli, ["install-tools"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    out_dir = (cabinet["rl"] / "Modules" / "HyperLaunch" / "Tools"
               / "spindoctor")
    assert (out_dir / "Refresh Favorites.bat").exists(), (
        "pre-condition: install-tools must have written the bat"
    )

    # Dry-run — no --apply.
    result = runner.invoke(cli, ["uninstall-tools"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    # Files must still be there.
    assert (out_dir / "Refresh Favorites.bat").exists(), (
        "Refresh Favorites.bat must NOT be deleted by a dry-run"
    )
    # Output must mention dry-run.
    assert "dry-run" in result.output.lower() or "would remove" in result.output.lower()


def test_uninstall_tools_add_to_system_dry_run_does_not_delete(cabinet):
    """Without --apply, --add-to-system mode must not delete files or DB entries."""
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

    pcl_dir = cabinet["rl"] / "Modules" / "PCLauncher" / "Toolkit"
    assert (pcl_dir / "Refresh Favorites.bat").exists()

    # Dry-run — no --apply.
    result = runner.invoke(
        cli, ["uninstall-tools", "--add-to-system", "Toolkit"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # Files must still be there.
    assert (pcl_dir / "Refresh Favorites.bat").exists(), (
        "bat must NOT be deleted by a dry-run"
    )
    assert (pcl_dir / "Refresh Favorites.ini").exists(), (
        "ini must NOT be deleted by a dry-run"
    )

    # Database entries must still be there.
    db = HyperspinDatabase("Toolkit", db_path)
    db.load()
    assert "Refresh Favorites" in db.games(), (
        "DB entry must NOT be removed by a dry-run"
    )

    # Output must describe what would happen.
    assert "dry-run" in result.output.lower() or "would remove" in result.output.lower()
