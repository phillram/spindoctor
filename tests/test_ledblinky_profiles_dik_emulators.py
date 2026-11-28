"""LEDBlinky profiles from SNESGT, Project64's N-Rage and Mugen keys, and MESS consoles' keypads.

SNESGT, N-Rage and WinMugen keep DirectInput scan codes in their own files,
Mugen 1.x SDL key symbols, and every Mugen game is its own build with its own
``data\\mugen.cfg``; none of them could be read.  MESS console profiles lit
only the buttons, not Start / Select or the keypads that games start with.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from spindoctor import ledblinky_library as ll, ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

SNESGT_INI = """[key_config]
1P_UP=200
1P_START=19
1P_SELECT=31
1P_Y=30
1P_B=18
1P_R=33
1P_L=46
1P_X=48
1P_A=32
2P_Y=34
2P_A=36
3P_A=0
[other]
1P_B=45
"""

NRAGE_INI = """[Controller 1]
Plugged=1
[Controls]
Button=0 0 4D 0 5
Button=0 4 13 0 5
Button=0 5 11 0 5
Button=0 6 1E 0 5
Button=0 7 20 0 5
Button=0 12 2F 0 5
Button=0 9 03 0 1
Button=1 7 24 0 5
Button=2 7 25 0 5
[Shortcuts]
Button=0 1 4E 0 5
"""

#: WinMugen: DirectInput codes (Jump 200 = up); top row X Y Z on A B C, bottom A B C on D E F.
MUGEN_DIK = """[Config]
GameSpeed = 0
[P1 Keys]
Jump   = 200
Crouch = 208
A      = 32 ; light punch
B      = 18
C      = 33
X      = 30
Y      = 48
Z      = 46
Start  = 19
[P2 Keys]
Jump   = 49
A      = 36
Start  = 20
[Joystick]
A = 1
"""
#: Mugen 1.x: SDL 1.2 key symbols (Jump 273 = up), A B C on the top row.
MUGEN_SDL = MUGEN_DIK.replace("200", "273").replace("= 32", "= 97").replace("= 18", "= 98") \
    .replace("= 33", "= 99").replace("= 30", "= 100").replace("= 48", "= 101").replace("= 46", "= 102") \
    .replace("= 19", "= 114").replace("= 49", "= 110").replace("= 36", "= 103").replace("= 20", "= 116")

PV1000_CFG = """<?xml version="1.0"?>
<mameconfig version="10">
    <system name="pv1000">
        <input>
            <port tag=":IN0" type="P1_SELECT" mask="1" defvalue="0"><newseq type="standard">KEYCODE_S</newseq></port>
            <port tag=":IN0" type="P1_START" mask="2" defvalue="0"><newseq type="standard">KEYCODE_R</newseq></port>
            <port tag=":IN0" type="P2_START" mask="4" defvalue="0"><newseq type="standard">KEYCODE_T</newseq></port>
            <port tag=":IN3" type="P1_BUTTON1" mask="1" defvalue="0"><newseq type="standard">KEYCODE_A</newseq></port>
            <port tag=":IN1" type="P1_JOYSTICK_UP" mask="1" defvalue="0"><newseq type="standard">KEYCODE_UP</newseq></port>
            <port tag=":KEYPAD1" type="KEYPAD" mask="8" defvalue="0"><newseq type="standard">KEYCODE_9PAD OR KEYCODE_F</newseq></port>
            <port tag=":KEYPAD2" type="KEYPAD" mask="8" defvalue="0"><newseq type="standard">KEYCODE_ASTERISK OR KEYCODE_L</newseq></port>
            <port tag=":KEY.0" type="KEYBOARD" mask="2" defvalue="0"><newseq type="standard">KEYCODE_1PAD OR KEYCODE_R OR KEYCODE_LSHIFT KEYCODE_X</newseq></port>
            <port tag=":KEY.0" type="KEYBOARD" mask="4" defvalue="0"><newseq type="standard">KEYCODE_HOME</newseq></port>
            <port tag=":panel" type="OTHER" mask="1" defvalue="0"><newseq type="standard">KEYCODE_U</newseq></port>
            <port tag=":PC0" type="OTHER" mask="1" defvalue="0"><newseq type="standard">KEYCODE_P</newseq></port>
        </input>
    </system>
</mameconfig>
"""

CONTROLS_XML = """<?xml version="1.0"?>
<dat>
  <emulator emuname="MAME" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0">
    </controlGroup>
  </emulator>
  <emulator emuname="OTHER" emuDesc="">
    <controlGroup groupName="DEFAULT" numPlayers="2" />
  </emulator>
</dat>
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _zip(path: Path, files: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return path


def _db(root: Path, system: str, games: list[str]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{n}</description>\n'
                   f"    <cloneof></cloneof>\n  </game>\n" for n in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "LIBRARY_DIR", tmp_path / "ledblinky_library")
    monkeypatch.setattr(lp, "MUGEN_CFG_CACHE", tmp_path / "mugen_cache.json")
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini", "")
    _write(led / "Colors.ini", "")
    rl = root / "RocketLauncher"
    settings = rl / "Settings"
    games = tmp_path / "Games"
    _write(settings / "Global Emulators.ini",
           f"[MUGEN]\nEmu_Path={games / 'Mugen' / 'PCLauncher.exe'}\nRom_Extension=7z|zip\nModule=MUGEN.ahk\n")
    emus = root / "Emulators"
    for wheel, emu, exe in (("Nintendo Satellaview", "SNESGT", "SNESGT\\snesgt.exe"),
                            ("Nintendo 64DD", "Project 64DD", "Project 64DD\\Project64.exe"),
                            ("Casio PV-1000", "MESS", "MESS\\mess.exe")):
        _write(settings / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator={emu}\n[{emu}]\nEmu_Path=..\\Emulators\\{exe}\n")
        _write(emus / exe.replace("\\", "/"), "")
        _db(root, wheel, ["Game One"])
    _write(emus / "SNESGT" / "SNESGT.ini", SNESGT_INI)
    _write(emus / "Project 64DD" / "Config" / "NRage.ini", NRAGE_INI)
    _write(emus / "MESS" / "cfg" / "pv1000.cfg", PV1000_CFG)
    # Mugen: two builds share WinMugen's layout, one is Mugen 1.x with its exe elsewhere.
    _write(settings / "Mugen" / "Emulators.ini", f"[ROMS]\nDefault_Emulator=MUGEN\nRom_Path={games / 'Mugen'}\n")
    _write(games / "Mugen" / "PCLauncher.exe", "")
    _write(rl / "Modules" / "MUGEN" / "MUGEN.ini", "[Fighters Two]\ngamePath = Fighters Two\\bin\\Fight.exe\n")
    _zip(games / "Mugen" / "Fighters One.zip", {"Fighters One/data/mugen.cfg": MUGEN_DIK,
                                                "Fighters One/font/data/mugen.cfg": MUGEN_SDL})
    _zip(games / "Mugen" / "Fighters Two.zip", {"Fighters Two/bin/data/mugen.cfg": MUGEN_SDL,
                                                "Fighters Two/data/mugen.cfg": MUGEN_DIK})
    _write(games / "Mugen" / "Fighters Three" / "data" / "mugen.cfg", MUGEN_DIK)
    _db(root, "Mugen", ["Fighters One", "Fighters Two", "Fighters Three"])
    _db(root, "Main Menu", ["Nintendo Satellaview", "Nintendo 64DD", "Casio PV-1000", "Mugen"])
    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(rl),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def _group(builder, system, name="DEFAULT"):
    emu = builder.doc.emulators()[lp.system_key(system)]
    return ET.fromstring(lp.ControlsXmlDoc.groups(emu)[lp.emu_key(name)][0].strip())


def _voices(group):
    return {(c.get("voice"), c.get("inputCodes")) for p in group.iter("player")
            if p.get("number") != "0" for c in p.iter("control")}


# ── readers ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected", [
    (97, "KEYCODE_A"), (122, "KEYCODE_Z"), (48, "KEYCODE_0"), (13, "KEYCODE_ENTER"), (32, "KEYCODE_SPACE"),
    (273, "KEYCODE_UP"), (256, "KEYCODE_0_PAD"), (282, "KEYCODE_F1"), (65, None)])
def test_key_from_sdl1(code, expected):
    assert lp.key_from_sdl1(code) == expected


def test_snesgt_reads_key_config(tmp_path):
    km = lp.snesgt_keymap(_write(tmp_path / "SNESGT.ini", SNESGT_INI).parent)
    assert km.get(1, "Y") == ["KEYCODE_A"] and km.get(1, "B") == ["KEYCODE_E"]
    assert km.get(1, "START") == ["KEYCODE_R"] and km.get(1, "SELECT") == ["KEYCODE_S"]
    assert km.get(2, "A") == ["KEYCODE_J"] and (3, "A") not in km.keys
    assert km.labels["L"] == "L Button"


def test_nrage_reads_keyboard_controls_only(tmp_path):
    km = lp.nrage_keymap(_write(tmp_path / "Config" / "NRage.ini", NRAGE_INI).parent.parent)
    # The D-pad's numpad 6 has no panel name; a pad button (type 1), controller 3
    # and the [Shortcuts] keys aren't read.
    assert km.keys == {(1, "4"): ["KEYCODE_R"], (1, "5"): ["KEYCODE_W"], (1, "6"): ["KEYCODE_A"],
                       (1, "7"): ["KEYCODE_D"], (1, "12"): ["KEYCODE_V"], (2, "7"): ["KEYCODE_J"]}
    assert (1, "9") not in km.keys and (1, "1") not in km.keys
    assert km.labels["5"] == "Z Trigger" and km.labels["12"] == "R Button"


def test_mugen_dik_and_sdl_layouts_read_the_same(tmp_path):
    dik = lp.mugen_keymap_text(MUGEN_DIK, "x")
    sdl = lp.mugen_keymap_text(MUGEN_SDL, "x")
    assert dik.get(1, "X") == ["KEYCODE_A"] and dik.get(1, "A") == ["KEYCODE_D"]
    assert dik.get(1, "Start") == ["KEYCODE_R"] and dik.get(2, "A") == ["KEYCODE_J"]
    assert sdl.get(1, "A") == ["KEYCODE_A"] and sdl.get(1, "X") == ["KEYCODE_D"]
    assert sdl.get(2, "Start") == ["KEYCODE_T"]
    assert lp.mugen_keymap_text(MUGEN_DIK.replace("Jump   = 200", "Jump   = 72"), "x") is None


def test_mugen_game_cfg_from_a_folder_and_a_zip(tmp_path):
    _write(tmp_path / "Folder Game" / "data" / "mugen.cfg", "[P1 Keys]\nJump = 200\n")
    assert "Jump" in lp.mugen_game_cfg(tmp_path / "Folder Game", "Folder Game/data/mugen.cfg")
    z = _zip(tmp_path / "Zip Game.zip", {"Zip Game/DATA/Mugen.cfg": "[P1 Keys]\n"})
    assert lp.mugen_game_cfg(z, "Zip Game/data/mugen.cfg") == "[P1 Keys]\n"
    assert lp.mugen_game_cfg(z, "Zip Game/bin/data/mugen.cfg") is None


def test_mugen_7z_is_read_once_until_it_changes(tmp_path, monkeypatch):
    py7zr = pytest.importorskip("py7zr")
    monkeypatch.setattr(lp, "MUGEN_CFG_CACHE", tmp_path / "cache.json")
    arc = tmp_path / "Seven.7z"
    with py7zr.SevenZipFile(arc, "w") as z:
        z.writestr("[P1 Keys]\nJump = 200\n", "Seven/data/mugen.cfg")
    assert lp.mugen_game_cfg(arc, "Seven/data/mugen.cfg") == "[P1 Keys]\nJump = 200\n"
    monkeypatch.setattr(lp, "_read_7z_member", lambda *a: pytest.fail("read again"))
    assert lp.mugen_game_cfg(arc, "Seven/data/mugen.cfg") == "[P1 Keys]\nJump = 200\n"
    with py7zr.SevenZipFile(arc, "w") as z:
        z.writestr("[P1 Keys]\nJump = 273\n", "Seven/data/mugen.cfg")
    monkeypatch.setattr(lp, "_read_7z_member", lambda *a: b"changed")
    assert lp.mugen_game_cfg(arc, "Seven/data/mugen.cfg") == "changed"


def test_mess_driver_lights_start_select_and_keypad_keys(tmp_path):
    _write(tmp_path / "cfg" / "pv1000.cfg", PV1000_CFG)
    panel = lp.load_panel(INPUT_MAP.parent)
    km = lp.MameIndex(tmp_path, "mess.exe").driver_keymap("pv1000", panel)
    assert km.get(1, "START") == ["KEYCODE_R"] and km.get(1, "SELECT") == ["KEYCODE_S"]
    assert km.get(2, "START") == ["KEYCODE_T"] and km.get(1, "BUTTON1") == ["KEYCODE_A"]
    keypad = {(p, km.labels[a], tuple(k)) for (p, a), k in km.keys.items() if ":" in a}
    # Named by the port's other key; the L and U of the P2 side go to player 2; a chord isn't a key.
    assert keypad == {(1, "Keypad 9", ("KEYCODE_F",)), (2, "Keypad *", ("KEYCODE_L",)),
                      (1, "Key 1", ("KEYCODE_R",)), (2, "Other", ("KEYCODE_U",))}


# ── ledblinky profiles ────────────────────────────────────────────────────────

def test_profiles_lights_satellaview_64dd_and_mess(cabinet):
    b = lp.plan_profiles(cabinet)
    assert {("Button Y", "KEYCODE_A"), ("Select", "KEYCODE_S"), ("Button A", "KEYCODE_J")} <= \
        _voices(_group(b, "Nintendo Satellaview"))
    assert {("Start", "KEYCODE_R"), ("Z Trigger", "KEYCODE_W"), ("Button A", "KEYCODE_J")} <= \
        _voices(_group(b, "Nintendo 64DD"))
    assert {("Start", "KEYCODE_R"), ("Select", "KEYCODE_S"), ("Keypad 9", "KEYCODE_F"),
            ("Keypad *", "KEYCODE_L")} <= _voices(_group(b, "Casio PV-1000"))


def test_profiles_mugen_default_is_the_common_layout(cabinet):
    b = lp.plan_profiles(cabinet)
    default = _voices(_group(b, "Mugen"))
    assert ("Button X", "KEYCODE_A") in default and ("Button A", "KEYCODE_D") in default
    # Fighters Two starts bin\Fight.exe (MUGEN.ini), so its keys are bin\data\mugen.cfg's.
    two = _voices(_group(b, "Mugen", "Fighters Two"))
    assert ("Button A", "KEYCODE_A") in two and ("Button X", "KEYCODE_D") in two
    groups = lp.ControlsXmlDoc.groups(b.doc.emulators()["MUGEN"])
    assert "FIGHTERS_ONE" not in groups and "FIGHTERS_THREE" not in groups
    assert any(a.source.startswith("Mugen data\\mugen.cfg (2 of 3") for a in b.result.actions)


def test_profiles_rerun_changes_nothing(cabinet):
    lp.plan_profiles(cabinet).write(dry_run=False, backup=False)
    again = lp.plan_profiles(cabinet)
    assert again.doc.text == again._xml_original
