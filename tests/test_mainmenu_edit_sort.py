"""`mainmenu edit` with piped commands, and `mainmenu sort` by an empty field.

- Windows PowerShell 5.1 pipes a UTF-8 byte-order mark in front of the
  first line when ``$OutputEncoding`` is UTF-8.  ``edit`` called that line
  an unrecognised command, ran every later index move one step off, and
  still saved with exit code 0.
- HyperSpin's own Main Menu.xml lists names only, so ``sort manufacturer``
  and ``sort year`` sorted A-Z while saying they sorted by maker or year.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli


NATIVE_MENU = (
    "<menu>\n"
    '  <game name="Sega Genesis"/>\n'
    '  <game name="MAME"/>\n'
    '  <game name="Nintendo 3DS" enabled="False"/>\n'
    '  <game name="Atari 2600"/>\n'
    "</menu>\n"
)

MENU_WITH_YEARS = (
    "<menu>\n"
    '  <game name="Sega Genesis"><year>1988</year></game>\n'
    '  <game name="MAME"/>\n'
    '  <game name="Atari 2600"><year>1977</year></game>\n'
    "</menu>\n"
)


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    roms = tmp_path / "roms"
    roms.mkdir()
    hs = tmp_path / "hyperspin"
    menu = hs / "Databases" / "Main Menu" / "Main Menu.xml"
    menu.parent.mkdir(parents=True)
    menu.write_bytes(NATIVE_MENU.encode("utf-8"))
    cfg = config_mod.Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    cfg.backup_before_modify = False
    config_mod.save_config(cfg)
    yield menu
    config_mod.reset_override_cache()


def _names(menu_path):
    import xml.etree.ElementTree as ET
    return [g.get("name") for g in ET.parse(menu_path).getroot().findall("game")]


def _edit(commands):
    return CliRunner().invoke(cli, ["mainmenu", "edit"], input=commands, catch_exceptions=False)


# ─── edit: byte-order mark ───────────────────────────────────────────────────

@pytest.mark.parametrize("bom", ["\ufeff", "\u00ef\u00bb\u00bf"], ids=["utf8", "read-as-cp1252"])
def test_edit_ignores_a_bom_before_the_first_command(cabinet, bom):
    result = _edit(bom + "move 2 to 1\nmove 4 to 2\nq\ny\n")
    assert result.exit_code == 0, result.output
    assert "unrecognised" not in result.output
    assert _names(cabinet) == ["MAME", "Atari 2600", "Sega Genesis", "Nintendo 3DS"]


# ─── edit: a failed piped command saves nothing ──────────────────────────────

def test_edit_saves_nothing_when_a_piped_command_fails(cabinet):
    before = cabinet.read_bytes()
    result = _edit("move 2 to 1\nmove 9 to 1\nq\ny\n")
    assert result.exit_code == 1
    assert "nothing was saved" in result.output
    assert "move 9 to 1" in result.output
    assert cabinet.read_bytes() == before


def test_edit_saves_nothing_after_an_unrecognised_command(cabinet):
    before = cabinet.read_bytes()
    result = _edit("mvoe 2 to 1\nmove 3 to 1\nq\ny\n")
    assert result.exit_code == 1
    assert cabinet.read_bytes() == before


def test_edit_piped_commands_that_all_work_still_save(cabinet):
    result = _edit("move 4 to 1\nq\ny\n")
    assert result.exit_code == 0, result.output
    assert _names(cabinet)[0] == "Atari 2600"
    assert 'enabled="False"' in cabinet.read_text(encoding="utf-8")


# ─── sort by a field no entry has ────────────────────────────────────────────

@pytest.mark.parametrize("field", ["manufacturer", "year"])
def test_sort_by_a_field_no_entry_has_stops(cabinet, field):
    before = cabinet.read_bytes()
    result = CliRunner().invoke(
        cli, ["mainmenu", "sort", field, "--apply"], catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert f"No Main Menu entry has a {field}" in result.output
    assert cabinet.read_bytes() == before


def test_sort_year_still_sorts_when_entries_have_years(cabinet):
    cabinet.write_bytes(MENU_WITH_YEARS.encode("utf-8"))
    result = CliRunner().invoke(
        cli, ["mainmenu", "sort", "year", "--apply"], catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "1 system(s) have no year and sort first" in result.output
    assert _names(cabinet) == ["MAME", "Atari 2600", "Sega Genesis"]


def test_edit_sort_by_a_field_no_entry_has_is_a_failed_command(cabinet):
    before = cabinet.read_bytes()
    result = _edit("sort year\nq\n")
    assert result.exit_code == 1
    assert "No Main Menu entry has a year" in result.output
    assert cabinet.read_bytes() == before


def test_sort_alpha_is_unchanged(cabinet):
    result = CliRunner().invoke(
        cli, ["mainmenu", "sort", "alpha", "--apply"], catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert _names(cabinet) == ["Atari 2600", "MAME", "Nintendo 3DS", "Sega Genesis"]


# ─── edit: UTF-8 misread as cp1252, and input that ends early ────────────────

def test_edit_reads_names_after_a_misread_bom_as_utf8(cabinet):
    misread = "\ufeffadd Pokémon\nq\ny\n".encode("utf-8").decode("cp1252")
    result = _edit(misread)
    assert result.exit_code == 0, result.output
    assert "Pokémon" in _names(cabinet) and "PokÃ©mon" not in _names(cabinet)


def test_edit_refuses_input_that_cant_be_the_utf8_its_bom_says(cabinet):
    before = cabinet.read_bytes()
    result = _edit("\u00ef\u00bb\u00bfadd Pok\u00e9mon\nq\ny\n")    # é alone isn't UTF-8 read as cp1252
    assert result.exit_code == 1
    assert "not UTF-8" in result.output and "nothing was saved" in result.output
    assert cabinet.read_bytes() == before


def test_edit_fails_when_piped_input_ends_after_a_failed_command(cabinet):
    before = cabinet.read_bytes()
    result = _edit("move 2 to 1\nbogus\n")
    assert result.exit_code == 1
    assert "bogus" in result.output and "nothing was saved" in result.output
    assert cabinet.read_bytes() == before


def test_edit_fails_when_piped_changes_end_without_q(cabinet):
    before = cabinet.read_bytes()
    result = _edit("move 2 to 1\n")
    assert result.exit_code == 1
    assert "ended without q" in result.output
    assert cabinet.read_bytes() == before


def test_edit_piped_input_with_no_changes_can_just_end(cabinet):
    assert _edit("list\n").exit_code == 0
