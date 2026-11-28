"""LEDBlinky profiles for a Nintendo DS wheel that runs melonDS.

melonDS 1.x keeps its binds in ``melonDS.toml`` beside the exe, table
``[Instance0.Keyboard]``, as Qt key codes: a letter is its capital's code,
the arrows are 16777234-16777237, and -1 is unbound.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import ledblinky_library as ll, ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

#: Shaped like the file melonDS 1.1 writes: a multi-line list before the
#: tables, keys in melonDS's own order, a joystick table after the keyboard one.
MELONDS_TOML = """\
RecentROM = [
    "D:\\\\Games\\\\Nintendo DS\\\\A = B (USA).nds",
]
LimitFPS = true

[Instance0]
JoystickID = 0

[Instance0.Keyboard]
HK_GuitarGripGreen = -1
HK_Lid = 87
B = 68
Down = 16777237
A = 69
Y = 65
HK_Pause = 80
X = 66
L = 67
R = 70
Start = 82
Select = 83
HK_Mic = 86
HK_FastForward = 16777217
Left = 16777234

[Instance0.Joystick]
A = 1
B = 0
Start = 6
"""

#: The panel keys above: Y X L on the top row, B A R on the bottom row.
PANEL_KEYS = {(1, "Y"): ["KEYCODE_A"], (1, "X"): ["KEYCODE_B"], (1, "L"): ["KEYCODE_C"],
              (1, "B"): ["KEYCODE_D"], (1, "A"): ["KEYCODE_E"], (1, "R"): ["KEYCODE_F"],
              (1, "Start"): ["KEYCODE_R"], (1, "Select"): ["KEYCODE_S"],
              (1, "HK_Mic"): ["KEYCODE_V"], (1, "HK_Lid"): ["KEYCODE_W"]}

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


def _write(path: Path, text: str, newline: str = "\n", bom: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", newline).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


def _keyboard(text: str) -> str:
    return "[Instance0.Keyboard]\n" + text


# ── Qt key codes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected", [
    (65, "KEYCODE_A"), (90, "KEYCODE_Z"), (0x35, "KEYCODE_5"),
    (16777234, "KEYCODE_LEFT"), (16777235, "KEYCODE_UP"),
    (16777236, "KEYCODE_RIGHT"), (16777237, "KEYCODE_DOWN"),
    (16777220, "KEYCODE_ENTER"), (16777219, "KEYCODE_BACKSPACE"),   # melonDS's own Start / Select
    (16777216, "KEYCODE_ESC"), (16777217, "KEYCODE_TAB"), (32, "KEYCODE_SPACE"),
    (0x2F, "KEYCODE_SLASH"), (16777264, "KEYCODE_F1"), (16777275, "KEYCODE_F12"),
    (16777248, "KEYCODE_LSHIFT"), (16777249, "KEYCODE_LCONTROL"),
    (-2130706400, "KEYCODE_RSHIFT"),                     # bit 31: the right-hand Shift
    (0x20000031, "KEYCODE_1PAD"), (0x21000005, "KEYCODE_ENTERPAD"),   # keypad flag
    (0x2000002B, "KEYCODE_PLUSPAD"),
    (-1, None), (0, None), (0x5B, None), (0x61, None),
    (0x02000041, None), (0x04000053, None),              # Shift+A, Ctrl+S: chords
    (0x20000041, None),                                  # keypad flag on a letter
])
def test_key_from_qt(code, expected):
    assert lp.key_from_qt(code) == expected


# ── melonDS.toml ──────────────────────────────────────────────────────────────

def test_reads_instance0_keyboard(tmp_path):
    _write(tmp_path / "melonDS.toml", MELONDS_TOML, newline="\r\n", bom=True)
    km = lp.melonds_keymap(tmp_path)
    assert km.source == "melonDS melonDS.toml"
    assert km.keys == PANEL_KEYS          # not the joystick table's A = 1, nor HK_Pause
    assert km.labels["HK_Mic"] == "Microphone" and km.labels["HK_Lid"] == "Lid"
    assert list(km.labels)[:8] == ["Y", "X", "L", "B", "A", "R", "Start", "Select"]   # DeSmuME's


def test_unbound_and_chorded_keys_light_nothing(tmp_path):
    _write(tmp_path / "melonDS.toml", _keyboard(
        "A = -1\nB = 33554497\nStart = 16777220\nSelect = 16777219\nHK_Mic = -1\nX = 66.0\nY = \"65\"\n"))
    km = lp.melonds_keymap(tmp_path)
    assert km.keys == {(1, "Start"): ["KEYCODE_ENTER"], (1, "Select"): ["KEYCODE_BACKSPACE"]}


def test_other_toml_spellings(tmp_path):
    _write(tmp_path / "melonDS.toml",
           "Instance0.Keyboard.L = 67\n"
           "[ Instance0 . Keyboard ]   # spaced header\n"
           "A=69  # no spaces, a comment\n"
           "[Instance0]\n"
           "Keyboard.Y = 65\n"
           "[instance0.keyboard]\n"     # melonDS reads names exactly: not its table
           "X = 66\n"
           "[[Instance0.Keyboard]]\n"   # an array of tables ends the table
           "R = 70\n")
    km = lp.melonds_keymap(tmp_path)
    assert km.keys == {(1, "L"): ["KEYCODE_C"], (1, "A"): ["KEYCODE_E"], (1, "Y"): ["KEYCODE_A"]}


def test_file_name_in_any_case(tmp_path):
    _write(tmp_path / "MELONDS.TOML", _keyboard("A = 69\n"))
    assert lp.melonds_keymap(tmp_path).keys == {(1, "A"): ["KEYCODE_E"]}


def test_no_keymap_without_the_keyboard_table(tmp_path):
    assert lp.melonds_keymap(tmp_path) is None                     # no file
    _write(tmp_path / "melonDS.ini", "Key_A=69\n")                  # melonDS 0.9's INI
    assert lp.melonds_keymap(tmp_path) is None
    _write(tmp_path / "melonDS.toml", "[Instance0.Joystick]\nA = 1\n")
    assert lp.melonds_keymap(tmp_path) is None


# ── through RocketLauncher ────────────────────────────────────────────────────

@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    """A Nintendo DS wheel whose RocketLauncher emulator is melonDS."""
    monkeypatch.setattr(ll, "LIBRARY_DIR", tmp_path / "ledblinky_library")
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini", "")
    _write(led / "Colors.ini", "")

    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "Global Emulators.ini", "[melonDS]\nEmu_Path=..\\Emulators\\melonDS\\melonDS.exe\n")
    _write(settings / "Nintendo DS" / "Emulators.ini", "[ROMS]\nDefault_Emulator=melonDS\n")

    emus = root / "Emulators"
    _write(emus / "melonDS" / "melonDS.toml", MELONDS_TOML)

    for system, games in (("Main Menu", ["Nintendo DS"]),
                          ("Nintendo DS", ["Mario Kart DS (USA, Australia) (En,Fr,De,Es,It)"])):
        body = "".join(f'  <game name="{g}">\n    <description>{g}</description>\n  </game>\n' for g in games)
        _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")

    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def test_resolver_reads_melonds_for_the_wheel(cabinet):
    resolver = lp.KeymapResolver(cabinet)
    launcher = resolver.system_launcher("Nintendo DS")
    assert launcher.exe == "melonDS.exe"
    km = resolver.for_launcher(launcher, "Nintendo DS")
    assert km.source == "melonDS melonDS.toml" and km.keys == PANEL_KEYS
    # One melonDS.toml for the whole wheel: no per-game keymap.
    assert resolver.for_launcher(launcher, "Nintendo DS", "Mario Kart DS (USA, Australia) (En,Fr,De,Es,It)") is None
    assert resolver.for_game("Nintendo DS", "Mario Kart DS (USA, Australia) (En,Fr,De,Es,It)").keys == PANEL_KEYS


def test_profiles_light_the_ds_buttons(cabinet):
    b = lp.plan_profiles(cabinet)
    emu = b.doc.emulators()[lp.emu_key("Nintendo DS")]
    default = ET.fromstring(lp.ControlsXmlDoc.groups(emu)["DEFAULT"][0].strip())
    lit = sorted({b.panel[k] for c in default.iter("control")
                  for k in (c.get("inputCodes") or "").split("|") if k in b.panel})
    assert {"P1B1", "P1B2", "P1B3", "P1B4", "P1B5", "P1B6", "P1B7", "P1B8",
            "P1START", "P1COIN"} <= set(lit)
    voices = {c.get("voice") for c in default.iter("control")}
    assert {"Button A", "Button Y", "Microphone", "Lid", "Start", "Select"} <= voices
    action = next(a for a in b.result.actions if a.system == "Nintendo DS")
    assert action.source == "melonDS melonDS.toml"
