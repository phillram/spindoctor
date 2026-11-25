"""``ledblinky check`` / ``fix`` and ``doctor``: LEDBlinky hooks in HyperSpin's menus.

LEDBlinky reads ``LEDBlinkyControls.xml``'s ``<emulator emuname>`` sections
(games are their ``<controlGroup groupName>``) and its ``<frontEnd>``
sections, never a ``<game>`` element, and HyperSpin doesn't call LEDBlinky
when its Search, Genre or Favorites menu opens. So a controls file with no
entry for those menus is no crash risk, and the fix must not add ``<game>``
stubs to it. What is still checked and fixed: ``Start_Hyperspin_Process`` /
``Exit_Hyperspin_Process`` lines that start LEDBlinky from a menu's own
``Settings.ini``.
"""
from __future__ import annotations

import re
from pathlib import Path

from click import unstyle
from click.testing import CliRunner

from spindoctor import health, ledblinky
from spindoctor.cli import cli
from spindoctor.config import Config

MENUS = ledblinky.SEARCH_MENU_NAMES   # Search, Genre, Favorites

# LEDBlinky's own layout: emulators with their control groups, front ends.
CONTROLS_XML = (
    '<?xml version="1.0"?>\r\n'
    "<dat>\r\n"
    "  <meta>\r\n"
    '    <generatedBy name="LEDBlinky" />\r\n'
    "  </meta>\r\n"
    '  <emulator emuname="MAME" emuDesc="">\r\n'
    '    <controlGroup groupName="DEFAULT" voice="" numPlayers="1">\r\n'
    '      <player number="0">\r\n'
    '        <control name="P1_BUTTON1" voice="" color="Red" inputCodes="KEYCODE_LCONTROL" />\r\n'
    "      </player>\r\n"
    "    </controlGroup>\r\n"
    '    <controlGroup groupName="pacman" voice="" numPlayers="2">\r\n'
    '      <player number="0">\r\n'
    '        <control name="CONTROL_JOY4WAY" voice="" color="Red" inputCodes="" />\r\n'
    "      </player>\r\n"
    "    </controlGroup>\r\n"
    "  </emulator>\r\n"
    '  <frontEnd fename="HyperSpin">\r\n'
    '    <controlGroup groupName="DEFAULT">\r\n'
    '      <player number="0">\r\n'
    '        <control name="P1_GENRE" voice="Player 1: Genre" />\r\n'
    '        <control name="P1_FAVORITES" voice="Player 1: Favorites" />\r\n'
    "      </player>\r\n"
    "    </controlGroup>\r\n"
    "  </frontEnd>\r\n"
    "</dat>\r\n"
)

# What an older ``ledblinky fix --apply`` left behind: harmless, LEDBlinky ignores it.
OLD_STUB = '  <game name="Search" controlGroup="default" spindoctor="compat-stub" />\r\n'

HOOK_INI = "[Main]\r\nStart_Hyperspin_Process=LEDBlinky\\LEDBlinky.exe 5\r\nkeep=1\r\n"


def _cabinet(tmp_path, xml=CONTROLS_XML):
    roms = tmp_path / "roms"
    (roms / "MAME").mkdir(parents=True)
    hs = tmp_path / "HyperSpin"
    (hs / "Databases" / "MAME").mkdir(parents=True)
    (hs / "Settings").mkdir()
    (hs / "Settings" / "Settings.ini").write_bytes(b"[LEDBlinky]\r\nActive=true\r\n")
    led = tmp_path / "LEDBlinky"
    led.mkdir()
    (led / ledblinky.CONTROLS_INI_NAME).write_text("[pacman]\nP1_BUTTON1=Red\n", encoding="utf-8")
    (led / ledblinky.COLORS_INI_NAME).write_text("[pacman]\nP1_BUTTON1=Red\n", encoding="utf-8")
    (led / ledblinky.COLOR_RGB_NAME).write_text("[Colors]\nRed=48,0,0\n", encoding="utf-8")
    (led / ledblinky.CONTROLS_XML_NAME).write_bytes(xml.encode("utf-8"))
    return Config(roms_dir=str(roms), hyperspin_dir=str(hs), ledblinky_dir=str(led),
                  backup_dir=str(tmp_path / "backups"))


def _controls_xml(cfg):
    return Path(cfg.ledblinky_dir) / ledblinky.CONTROLS_XML_NAME


def _menu_ini(cfg, menu, text=HOOK_INI):
    path = Path(cfg.hyperspin_dir) / "Menu" / menu / "Settings.ini"
    path.parent.mkdir(parents=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _row(cfg):
    result = health.check_ledblinky(cfg)
    return result, next(c for c in result.children if c.name == "Search/Genre/Favorites")


def _run(monkeypatch, cfg, *args):
    """``spindoctor ledblinky <args>``; output without styles, borders or wrapping."""
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: cfg)
    result = CliRunner().invoke(cli, ["ledblinky", *args])
    assert result.exit_code == 0, result.output
    return " ".join(re.sub(r"[│┃|]", " ", unstyle(result.output)).split())


# ─── scan ─────────────────────────────────────────────────────────────────────


def test_scan_finds_no_issue_when_the_controls_file_has_no_menu_entries(tmp_path):
    cfg = _cabinet(tmp_path)
    res = ledblinky.scan(cfg, menus=MENUS)
    assert res["controls_xml_exists"]
    assert res["issues"] == []
    assert res["ok"]
    assert [mi["menu"] for mi in res["menu_inis"]] == MENUS


def test_scan_still_finds_a_hook_in_a_menus_settings_ini(tmp_path):
    cfg = _cabinet(tmp_path)
    path = _menu_ini(cfg, "Genre")
    res = ledblinky.scan(cfg, menus=MENUS)
    assert {mi["menu"]: mi["has_hooks"] for mi in res["menu_inis"]} == {
        "Search": False, "Genre": True, "Favorites": False}
    assert len(res["issues"]) == 1
    assert "Genre" in res["issues"][0] and str(path) in res["issues"][0]


# ─── doctor ───────────────────────────────────────────────────────────────────


def test_doctor_is_ok_with_a_real_controls_file_and_no_hooks(tmp_path):
    cfg = _cabinet(tmp_path)
    result, row = _row(cfg)
    assert row.status == health.Status.OK
    assert result.status == health.Status.OK
    assert "crash" not in row.detail


def test_doctor_ignores_stub_entries_an_older_fix_added(tmp_path):
    cfg = _cabinet(tmp_path, CONTROLS_XML.replace("</dat>", OLD_STUB + "</dat>"))
    _result, row = _row(cfg)
    assert row.status == health.Status.OK


def test_doctor_warns_only_for_the_hooked_menu_and_its_fix_names_it(tmp_path):
    cfg = _cabinet(tmp_path)
    _menu_ini(cfg, "Favorites")
    result, row = _row(cfg)
    assert result.status == health.Status.WARN
    assert row.status == health.Status.WARN
    assert "Favorites" in row.detail
    assert "Search" not in row.detail and "Genre" not in row.detail
    # Without --menus, `ledblinky fix` patches only Search.
    assert row.fix == "spindoctor ledblinky fix --apply --menus Favorites"


# ─── apply_fix ────────────────────────────────────────────────────────────────


def test_fix_leaves_the_controls_file_byte_for_byte(tmp_path):
    cfg = _cabinet(tmp_path)
    xml = _controls_xml(cfg)
    before = xml.read_bytes()
    res = ledblinky.apply_fix(cfg, dry_run=False, menus=MENUS)
    assert xml.read_bytes() == before
    assert "controls_xml" not in res
    assert res["errors"] == []
    assert not (tmp_path / "backups").exists()   # nothing changed, nothing backed up


def test_fix_still_comments_out_a_menu_hook(tmp_path):
    cfg = _cabinet(tmp_path)
    path = _menu_ini(cfg, "Genre")
    xml_before = _controls_xml(cfg).read_bytes()
    res = ledblinky.apply_fix(cfg, dry_run=False, menus=["Genre"])
    (info,) = res["menu_inis"]
    assert (info["menu"], info["lines_changed"], info["wrote"]) == ("Genre", 1, True)
    assert path.read_bytes() == HOOK_INI.replace(
        "Start_Hyperspin_Process=LEDBlinky\\LEDBlinky.exe 5",
        ";Start_Hyperspin_Process=LEDBlinky\\LEDBlinky.exe 5  " + ledblinky.LEDBLINKY_DISABLE_TAG,
    ).encode("utf-8")
    assert _controls_xml(cfg).read_bytes() == xml_before


def test_fix_needs_no_ledblinky_dir(tmp_path):
    cfg = _cabinet(tmp_path)
    cfg.ledblinky_dir = ""
    path = _menu_ini(cfg, "Search")
    res = ledblinky.apply_fix(cfg, dry_run=False, backup=False)
    assert res["errors"] == []
    assert res["menu_inis"][0]["wrote"]
    assert b";Start_Hyperspin_Process" in path.read_bytes()


def test_fix_to_an_output_dir_writes_no_controls_file(tmp_path):
    cfg = _cabinet(tmp_path)
    _menu_ini(cfg, "Search")
    out = tmp_path / "out"
    ledblinky.apply_fix(cfg, output_base=out, menus=MENUS)
    assert not (out / "LEDBlinky").exists()
    assert (out / "Menu" / "Search" / "Settings.ini").exists()


# ─── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_check_finds_no_issue_in_a_real_controls_file(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path)
    out = _run(monkeypatch, cfg, "check", "--menus", "Search,Genre,Favorites")
    assert "No issues detected" in out
    assert "controls.xml=" not in out
    assert "no entry" not in out


def test_cli_check_points_the_fix_at_the_hooked_menu(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path)
    _menu_ini(cfg, "Genre")
    out = _run(monkeypatch, cfg, "check", "--menus", "Search,Genre,Favorites")
    assert "Genre menu Settings.ini contains a LedBlinky process hook" in out
    assert "spindoctor ledblinky fix --menus Genre" in out


def test_cli_fix_apply_leaves_the_controls_file_alone(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, CONTROLS_XML.replace("</dat>", OLD_STUB + "</dat>"))
    xml = _controls_xml(cfg)
    before = xml.read_bytes()
    out = _run(monkeypatch, cfg, "fix", "--apply", "--menus", "Search,Genre,Favorites")
    assert xml.read_bytes() == before
    assert "Would add" not in out and "Added" not in out
    assert "no Settings.ini" in out
