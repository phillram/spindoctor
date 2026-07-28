"""`mainmenu add` / `add-system` write HyperSpin's per-system Settings INI.

Regression for "Cannot find <System>.ini" when *selecting* a newly added wheel:
HyperSpin needs ``<hyperspin_dir>/Settings/<System>.ini`` to open a wheel as a
sub-menu.  The synthetic-wheel rebuilds already wrote it; the ``mainmenu add``
path (the only way the Recompiled wheel is set up) did not.
"""
from __future__ import annotations

import textwrap

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli


SAMPLE_MENU_XML = textwrap.dedent("""\
    <menu>
      <game name="MAME" />
      <game name="Sony Playstation" />
    </menu>
    """)


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
    menu_dir = hs / "Databases" / "Main Menu"
    for d in (roms, menu_dir, hs / "Settings", rl / "Settings"):
        d.mkdir(parents=True)
    (menu_dir / "Main Menu.xml").write_text(SAMPLE_MENU_XML, encoding="utf-8")

    cfg = config_mod.Config(
        roms_dir=str(roms),
        hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
    )
    cfg.backup_before_modify = False
    config_mod.save_config(cfg)
    yield {"hs": hs, "rl": rl}
    config_mod.reset_override_cache()


def _settings_ini(cabinet, system: str):
    return cabinet["hs"] / "Settings" / f"{system}.ini"


def test_mainmenu_add_writes_hyperspin_settings_ini(cabinet):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["mainmenu", "add", "Dreamcast", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    ini = _settings_ini(cabinet, "Dreamcast")
    assert ini.exists(), "HyperSpin Settings/<System>.ini was not created"
    assert "hyperlaunch=true" in ini.read_text(encoding="utf-8")


def test_mainmenu_add_recompiled_writes_hyperspin_settings_ini(cabinet):
    """The exact reported case: the Recompiled wheel."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["mainmenu", "add", "Recompiled", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert _settings_ini(cabinet, "Recompiled").exists()


def test_mainmenu_add_installs_default_console_theme(cabinet):
    """A newly added wheel gets Media/<System>/Themes/default.zip so its games
    render a fallback theme instead of a blank screen."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["mainmenu", "add", "Dreamcast", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    default_zip = cabinet["hs"] / "Media" / "Dreamcast" / "Themes" / "default.zip"
    assert default_zip.exists(), "console-level default.zip theme was not installed"


def test_mainmenu_add_does_not_clobber_existing_default_theme(cabinet):
    default_zip = cabinet["hs"] / "Media" / "Dreamcast" / "Themes" / "default.zip"
    default_zip.parent.mkdir(parents=True)
    default_zip.write_bytes(b"CUSTOM-THEME")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["mainmenu", "add", "Dreamcast", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert default_zip.read_bytes() == b"CUSTOM-THEME"


def test_mainmenu_add_does_not_clobber_existing_ini(cabinet):
    """A user/HyperHQ-authored theme INI must survive re-adding the wheel."""
    ini = _settings_ini(cabinet, "Dreamcast")
    ini.write_text("[wheel]\ntext_color1=0xCUSTOM\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["mainmenu", "add", "Dreamcast", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # Untouched: still the user's content, not the minimal template.
    assert ini.read_text(encoding="utf-8") == "[wheel]\ntext_color1=0xCUSTOM\n"


def test_mainmenu_add_dry_run_writes_nothing(cabinet):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["mainmenu", "add", "Dreamcast"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert not _settings_ini(cabinet, "Dreamcast").exists()
