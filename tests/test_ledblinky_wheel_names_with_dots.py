"""LEDBlinky cuts a wheel's name at its last dot before it matches a section.

LEDBlinky looks a launched game up as ``<wheel>|<game>``, and it treats the
wheel name like a file name: everything from the last dot is dropped, so
``Nokia N-Gage 2.0`` is asked for as ``NOKIA_N-GAGE_2`` and ``Tiger Game.com``
as ``TIGER_GAME`` (``UnknownGames.dat`` lists them that way).  Game names keep
their dots.  ``ledblinky profiles`` wrote and looked for ``Tiger_Game.com``, so
those wheels lit nothing of their own.
"""
from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

from spindoctor import health, ledblinky, ledblinky_library as ll, ledblinky_profiles as lp
from spindoctor.cli import cli
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

OLD_SECTION = """  <emulator emuname="Tiger_Game.com" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="1" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON1" voice="Button A" alwaysActive="0" color="Red" inputCodes="KEYCODE_Z" />
      </player>
    </controlGroup>
    <controlGroup groupName="Mr._Driller" voice="Mr. Driller" numPlayers="1" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON1" voice="Drill" alwaysActive="0" color="Lime" inputCodes="KEYCODE_A" />
      </player>
    </controlGroup>
  </emulator>
"""

CONTROLS_XML = """<?xml version="1.0"?>
<dat>
  <emulator emuname="MAME" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0">
    </controlGroup>
  </emulator>
{extra}  <emulator emuname="OTHER" emuDesc="">
    <controlGroup groupName="DEFAULT" numPlayers="2" />
  </emulator>
</dat>
"""

#: The Game.com's four buttons on A B D E (MESS driver gamecom).
GAMECOM_CFG = """<?xml version="1.0"?>
<mameconfig version="10">
    <system name="gamecom">
        <input>
""" + "".join(f"""            <port tag=":IN0" type="P1_BUTTON{i}" mask="{1 << i}" defvalue="{1 << i}">
                <newseq type="standard">
                    KEYCODE_{k}
                </newseq>
            </port>
""" for i, k in enumerate("ABDE", 1)) + """        </input>
    </system>
</mameconfig>
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _db(root: Path, system: str, games: list[tuple[str, str]]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{d}</description>\n'
                   f"    <cloneof></cloneof>\n  </game>\n" for n, d in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


def _cabinet(tmp_path: Path, monkeypatch, extra: str = OLD_SECTION,
             wheels: tuple[str, ...] = ("Tiger Game.com", "Nokia N-Gage 2.0")) -> Config:
    monkeypatch.setattr(ll, "LIBRARY_DIR", tmp_path / "ledblinky_library")
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML.format(extra=extra))
    _write(led / "Controls.ini", "")
    _write(led / "Colors.ini", "")
    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "Global Emulators.ini", "")
    _write(settings / "Tiger Game.com" / "Emulators.ini",
           "[ROMS]\nDefault_Emulator=MESS\n[MESS]\nEmu_Path=..\\Emulators\\MESS\\mess.exe\n")
    _write(settings / "Nokia N-Gage 2.0" / "Emulators.ini",
           "[ROMS]\nDefault_Emulator=EKA2L1\n[EKA2L1]\nEmu_Path=..\\Emulators\\EKA2L1\\eka2l1_qt.exe\n")
    _write(root / "Emulators" / "MESS" / "mess.exe", "")
    _write(root / "Emulators" / "MESS" / "cfg" / "gamecom.cfg", GAMECOM_CFG)
    _write(root / "Emulators" / "EKA2L1" / "eka2l1_qt.exe", "")
    _db(root, "Main Menu", [(w, "") for w in wheels])
    _db(root, "Tiger Game.com", [("Mr. Driller", "Mr. Driller"), ("Resident Evil 2", "Resident Evil 2")])
    _db(root, "Nokia N-Gage 2.0", [("Boom Blox", "Boom Blox")])
    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(root / "Emulators"), ledblinky_dir=str(led))


def _emunames(text: str) -> list[str]:
    return re.findall(r'<emulator emuname="([^"]*)"', text)


# ── the name LEDBlinky asks for ───────────────────────────────────────────────

@pytest.mark.parametrize("wheel,section", [
    ("Nokia N-Gage 2.0", "Nokia_N-Gage_2"),
    ("Tiger Game.com", "Tiger_Game"),
    ("Sega Genesis", "Sega_Genesis"),
    ("A.B.C", "A.B"),
    (" Atari 2600 ", "Atari_2600"),
])
def test_wheel_section_name_cuts_at_the_last_dot(wheel, section):
    assert ledblinky.wheel_section_name(wheel) == section


def test_game_names_keep_their_dots():
    assert lp.system_key("Tiger Game.com") == "TIGER_GAME"
    assert lp.emu_key("Mr. Driller") == "MR._DRILLER"
    assert lp.group_name("Mr. Driller") == "Mr._Driller"


# ── ledblinky profiles ────────────────────────────────────────────────────────

def test_profiles_renames_a_full_name_section_and_keeps_its_groups(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch)
    b = lp.plan_profiles(cfg)
    emus = b.doc.emulators()
    assert "TIGER_GAME" in emus and "TIGER_GAME.COM" not in emus
    assert 'emuname="Tiger_Game"' in emus["TIGER_GAME"]
    groups = lp.ControlsXmlDoc.groups(emus["TIGER_GAME"])
    # The hand-made game group survives, dots and all.
    assert "Lime" in groups["MR._DRILLER"][0]
    # DEFAULT now lights the four keys gamecom.cfg binds.
    default = ET.fromstring(groups["DEFAULT"][0].strip())
    assert sorted(c.get("inputCodes") for c in default.iter("control")
                  if c.get("name", "").startswith("P1_")) == ["KEYCODE_A", "KEYCODE_B", "KEYCODE_D", "KEYCODE_E"]
    assert any(a.action == "section Tiger_Game.com renamed Tiger_Game" for a in b.result.actions)


def test_profiles_creates_a_new_section_under_the_cut_name(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch)
    b = lp.plan_profiles(cfg)
    names = _emunames(b.doc.text)
    assert "Nokia_N-Gage_2" in names
    assert not any(n.startswith("Nokia_N-Gage_2.") for n in names)


def test_profiles_written_file_has_no_unreachable_section(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch)
    assert [s["emuname"] for s in ledblinky.unreachable_sections(cfg)] == ["Tiger_Game.com"]
    lp.plan_profiles(cfg).write(dry_run=False, backup=False)
    assert ledblinky.unreachable_sections(cfg) == []
    # A second run finds the section by its cut name and changes nothing more.
    again = lp.plan_profiles(cfg)
    assert not any("renamed" in a.action for a in again.result.actions)


def test_profiles_leaves_both_sections_alone_when_the_cut_one_exists(tmp_path, monkeypatch):
    cut = OLD_SECTION.replace('emuname="Tiger_Game.com"', 'emuname="Tiger_Game"').replace("Mr._Driller", "Other")
    cfg = _cabinet(tmp_path, monkeypatch, extra=OLD_SECTION + cut)
    b = lp.plan_profiles(cfg)
    names = _emunames(b.doc.text)
    assert names.count("Tiger_Game.com") == 1 and names.count("Tiger_Game") == 1
    assert any("Tiger_Game.com' is never used" in w for w in b.result.warnings)
    # The cut section is the one that got the keys.
    groups = lp.ControlsXmlDoc.groups(b.doc.emulators()["TIGER_GAME"])
    assert "KEYCODE_E" in groups["DEFAULT"][0] and "OTHER" in groups


# ── ledblinky check / doctor ──────────────────────────────────────────────────

def test_unreachable_sections_names_the_wheel_and_the_name_to_use(tmp_path, monkeypatch):
    stray = OLD_SECTION.replace("Tiger_Game.com", "Foo.Bar")
    deep = OLD_SECTION.replace("Tiger_Game.com", "A.B")
    cfg = _cabinet(tmp_path, monkeypatch, extra=OLD_SECTION + stray + deep,
                   wheels=("Tiger Game.com", "A.B.C"))
    assert ledblinky.unreachable_sections(cfg) == [
        {"emuname": "Tiger_Game.com", "wheel": "Tiger Game.com", "use": "Tiger_Game"},
        {"emuname": "Foo.Bar", "wheel": "", "use": ""},
    ]   # A.B is what the A.B.C wheel asks for


def test_scan_reports_the_unused_section(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch)
    res = ledblinky.scan(cfg)
    assert not res["ok"]
    assert any("'Tiger_Game.com' is never used" in i and "'Tiger_Game'" in i for i in res["issues"])


def test_scan_is_quiet_without_dotted_sections(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch, extra="")
    res = ledblinky.scan(cfg)
    assert res["unreachable_sections"] == []
    assert not any("never used" in i for i in res["issues"])


def test_doctor_warns_about_the_unused_section(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch)
    child = next(c for c in health.check_ledblinky(cfg).children if c.name == "Wheel sections")
    assert child.status == health.Status.WARN
    assert "Tiger_Game.com" in child.detail and "Tiger_Game.com -> Tiger_Game" in child.fix


def test_doctor_adds_nothing_when_every_section_is_reachable(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch, extra="")
    assert all(c.name != "Wheel sections" for c in health.check_ledblinky(cfg).children)


def test_cli_check_lists_the_unused_section(tmp_path, monkeypatch):
    cfg = _cabinet(tmp_path, monkeypatch)
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: cfg)
    out = unstyle(CliRunner().invoke(cli, ["ledblinky", "check"]).output)
    assert "1 never used" in out and "Tiger_Game.com" in out
