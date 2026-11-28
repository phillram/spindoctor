"""LEDBlinky profiles from EKA2L1, Cxbx-R, WinUAE and BigPEmu keys.

Each keeps its keyboard binds in its own files beside the exe, which
``ledblinky profiles`` couldn't read: N-Gage, Xbox, Amiga CD32 and Jaguar
wheels kept old profiles or lit only the admin buttons.
"""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import ledblinky_library as ll, ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

#: EKA2L1: Qt key codes (65 = A, 16777220 = Return) -> Symbian keys (53 = 5, 167 = OK).
EKA2L1_BINDINGS = "".join(f"""- source:
    type: key
    data:
      keycode: {code}
  target: {target}
""" for code, target in ((16777235, 16), (65, 53), (66, 55), (82, 164), (83, 165), (16777220, 167))) + """- source:
    type: controller
    data:
      controller_id: 0
      button_id: 0
  target: 167
"""

CXBXR_SETTINGS = """[input-port-0]
Type = 1
DeviceName = SDL/0/PS4 Controller
ProfileName = "PS4 Pad"

[input-port-1]
Type = 1
DeviceName = DInput/0/KeyboardMouse
ProfileName = "Panel P2"

[input-profile-0]
Type = 1
ProfileName = "PS4 Pad"
DeviceName = SDL/0/PS4 Controller
A = Button 0
Start = Button 6

[input-profile-1]
Type = 1
ProfileName = "Panel P1"
DeviceName = DInput/0/KeyboardMouse
Start = R
Back = S
A = D
B = E
X = A
Y = B
Black = C
White = F
L Trigger = V
R Trigger = W
Left Axis X+ = RIGHT

[input-profile-2]
Type = 1
ProfileName = "Panel P2"
DeviceName = DInput/0/KeyboardMouse
Start = T
A = J
X = G
"""

#: WinUAE: set 4 holds the custom game-port binds; JOY2 is player 1.
UAE_HOST = """input.config=0
joyport0=custom
joyport1=custom
input.4.keyboard.0.custom=true
input.4.keyboard.0.button.30.A=JOY2_CD32_GREEN.4.1
input.4.keyboard.0.button.48.B=JOY2_CD32_YELLOW.4.1
input.4.keyboard.0.button.32.D=JOY2_CD32_RED.4.1
input.4.keyboard.0.button.18.E=JOY2_CD32_BLUE.4.1
input.4.keyboard.0.button.19.R=JOY2_CD32_PLAY.4.1
input.4.keyboard.0.button.200.UP=JOY2_UP.4.1
input.4.keyboard.0.button.34.G=JOY1_CD32_GREEN.4.0
input.4.keyboard.0.button.36.J=JOY1_CD32_RED.4.0
input.1.keyboard.0.button.31.S=JOY2_CD32_RED.4.1
"""


def _jaguar_device(keys: dict[int, int], modifier: frozenset = frozenset()) -> dict:
    """A BigPEmu device: 51 inputs; *keys* maps an input's place to its keyboard scan code."""
    def triggers(i):
        if i not in keys:
            return []
        t = {"B_KB": True, "B_ID": keys[i], "B_AH": 0.0}
        if i in modifier:
            t.update({"M_KB": True, "M_ID": 42, "M_AH": 0.0})
        return [t, {"B_KB": False, "B_ID": i, "B_AH": 0.0, "B_DevID": "00"}]
    return {"DeviceType": 0, "Bindings": [{"Triggers": triggers(i)} for i in range(51)]}


#: Player 1: C B A on A B C, Pause R, Option S, keypad 1 on D, * on V; keypad 2 only with Shift.
BIGPEMU_CONFIG = {"BigPEmuConfig": {"Input": {
    "Device0": _jaguar_device({0: 30, 1: 48, 2: 46, 3: 19, 4: 31, 5: 200, 10: 32, 11: 18, 19: 47},
                              modifier=frozenset({11})),
    "Device1": _jaguar_device({0: 34, 3: 20}),
    "Device2": {"DeviceType": 1, "Bindings": []}}}}

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

WHEELS = {
    "Nokia N-Gage": ("EKA2L1", "EKA2L1\\eka2l1_qt.exe"),
    "Microsoft Xbox": ("CxbxR", "CxbxR\\cxbx.exe"),
    "Commodore Amiga CD32": ("WinUAE", "WinUAE\\winuae64.exe"),
    "Atari Jaguar": ("BigPEmu", "BigPEmu\\BigPEmu.exe"),
}


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _db(root: Path, system: str, games: list[str]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{n}</description>\n'
                   f"    <cloneof></cloneof>\n  </game>\n" for n in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "LIBRARY_DIR", tmp_path / "ledblinky_library")
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini", "")
    _write(led / "Colors.ini", "")
    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "Global Emulators.ini", "")
    emus = root / "Emulators"
    for wheel, (emu, exe) in WHEELS.items():
        _write(settings / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator={emu}\n[{emu}]\nEmu_Path=..\\Emulators\\{exe}\n")
        _write(emus / exe.replace("\\", "/"), "")
    _write(emus / "EKA2L1" / "config.yml", "current-keybind-profile: default\n")
    _write(emus / "EKA2L1" / "bindings" / "default.yml", EKA2L1_BINDINGS)
    _write(emus / "CxbxR" / "settings.ini", CXBXR_SETTINGS)
    _write(emus / "WinUAE" / "Configurations" / "Host" / "cd32host.uae", UAE_HOST)
    # One game has a config of its own, with Red on F.
    _write(emus / "WinUAE" / "Configurations" / "Diggers.uae",
           UAE_HOST.replace("button.32.D=JOY2_CD32_RED", "button.33.F=JOY2_CD32_RED"))
    _write(emus / "BigPEmu" / "UserData" / "BigPEmuConfig.bigpcfg", json.dumps(BIGPEMU_CONFIG, indent=4))
    _db(root, "Nokia N-Gage", ["Rayman 3"])
    _db(root, "Microsoft Xbox", ["Jet Set Radio Future"])
    _db(root, "Commodore Amiga CD32", ["Diggers", "Zool"])
    _db(root, "Atari Jaguar", ["Tempest 2000"])
    _db(root, "Main Menu", list(WHEELS))
    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def _group(builder, system, name="DEFAULT"):
    emu = builder.doc.emulators()[lp.system_key(system)]
    return ET.fromstring(lp.ControlsXmlDoc.groups(emu)[lp.emu_key(name)][0].strip())


def _voices(group):
    return {(c.get("voice"), c.get("inputCodes")) for p in group.iter("player")
            if p.get("number") != "0" for c in p.iter("control")}


# ── EKA2L1 ────────────────────────────────────────────────────────────────────

def test_eka2l1_reads_key_binds_of_the_current_profile(tmp_path):
    _write(tmp_path / "config.yml", "current-keybind-profile: panel\n")
    _write(tmp_path / "bindings" / "panel.yml", EKA2L1_BINDINGS)
    km = lp.eka2l1_keymap(tmp_path)
    assert km.source == "EKA2L1 bindings\\panel.yml"
    assert km.keys == {(1, "16"): ["KEYCODE_UP"], (1, "53"): ["KEYCODE_A"], (1, "55"): ["KEYCODE_B"],
                       (1, "164"): ["KEYCODE_R"], (1, "165"): ["KEYCODE_S"],
                       (1, "167"): ["KEYCODE_ENTER"]}   # the pad's bind to OK isn't a key
    assert km.labels["53"] == "Key 5" and km.labels["167"] == "OK" and "164" in km.system_actions


def test_eka2l1_without_its_profile_file_is_none(tmp_path):
    _write(tmp_path / "config.yml", "current-keybind-profile: gone\n")
    _write(tmp_path / "bindings" / "default.yml", EKA2L1_BINDINGS)
    assert lp.eka2l1_keymap(tmp_path) is None


# ── Cxbx-R ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("A", "KEYCODE_A"), ("7", "KEYCODE_7"), ("F2", "KEYCODE_F2"), ("RETURN", "KEYCODE_ENTER"),
    ("NUMPAD3", "KEYCODE_3_PAD"), ("Button 0", None), ("", None)])
def test_key_from_dinput_name(name, expected):
    assert lp.key_from_dinput_name(name) == expected


def test_cxbxr_uses_keyboard_profiles_where_a_port_has_a_pad(tmp_path):
    km = lp.cxbxr_keymap(_write(tmp_path / "settings.ini", CXBXR_SETTINGS).parent)
    # Port 0 is on a pad, so player 1 takes the first keyboard profile not used by port 1.
    assert km.source == "Cxbx-R settings.ini (Panel P1, Panel P2)"
    assert km.get(1, "X") == ["KEYCODE_A"] and km.get(1, "Black") == ["KEYCODE_C"]
    assert km.get(1, "Back") == ["KEYCODE_S"] and "Back" in km.system_actions
    assert km.get(2, "A") == ["KEYCODE_J"] and km.get(2, "Start") == ["KEYCODE_T"]
    assert km.labels["L Trigger"] == "Left Trigger"


def test_cxbxr_with_no_keyboard_profile_is_none(tmp_path):
    text = CXBXR_SETTINGS.replace("DInput/0/KeyboardMouse", "XInput/0/Gamepad")
    assert lp.cxbxr_keymap(_write(tmp_path / "settings.ini", text).parent) is None


# ── WinUAE ────────────────────────────────────────────────────────────────────

def test_winuae_reads_the_game_port_set(tmp_path):
    km = lp.winuae_keymap(_write(tmp_path / "cd32host.uae", UAE_HOST))
    assert km.keys == {(1, "CD32_GREEN"): ["KEYCODE_A"], (1, "CD32_YELLOW"): ["KEYCODE_B"],
                       (1, "CD32_RED"): ["KEYCODE_D"], (1, "CD32_BLUE"): ["KEYCODE_E"],
                       (1, "CD32_PLAY"): ["KEYCODE_R"], (2, "CD32_GREEN"): ["KEYCODE_G"],
                       (2, "CD32_RED"): ["KEYCODE_J"]}   # set 1 and the arrow aren't read
    assert km.labels["CD32_RWD"] == "Reverse" and "CD32_PLAY" in km.system_actions


def test_winuae_reads_the_set_input_config_names(tmp_path):
    km = lp.winuae_keymap(_write(tmp_path / "a.uae", UAE_HOST.replace("input.config=0", "input.config=1")))
    assert km.keys == {(1, "CD32_RED"): ["KEYCODE_S"]}


@pytest.mark.parametrize("wheel,host", [
    ("Commodore Amiga CD32", "cd32host.uae"), ("Commodore CDTV", "cdtvhost.uae"),
    ("Commodore Amiga CD", "amigacdhost.uae"), ("Commodore Amiga", "amigahost.uae")])
def test_winuae_host_config_follows_the_module(tmp_path, wheel, host):
    _write(tmp_path / "Configurations" / "host" / host, "")
    assert lp.winuae_host_config(tmp_path, wheel).name == host


# ── BigPEmu ───────────────────────────────────────────────────────────────────

def test_bigpemu_reads_keyboard_triggers_in_input_order(tmp_path):
    _write(tmp_path / "UserData" / "BigPEmuConfig.bigpcfg", json.dumps(BIGPEMU_CONFIG))
    km = lp.bigpemu_keymap(tmp_path)
    assert km.keys == {(1, "C"): ["KEYCODE_A"], (1, "B"): ["KEYCODE_B"], (1, "A"): ["KEYCODE_C"],
                       (1, "Pause"): ["KEYCODE_R"], (1, "Option"): ["KEYCODE_S"],
                       (1, "Keypad 1"): ["KEYCODE_D"], (1, "Keypad *"): ["KEYCODE_V"],
                       (2, "C"): ["KEYCODE_G"], (2, "Pause"): ["KEYCODE_T"]}   # no arrow LED; Shift+E is a chord
    assert km.labels["A"] == "Button A" and "Pause" in km.system_actions


@pytest.mark.parametrize("text", ["", "{not json", '{"BigPEmuConfig": {}}'])
def test_bigpemu_unreadable_config_is_none(tmp_path, text):
    _write(tmp_path / "UserData" / "BigPEmuConfig.bigpcfg", text)
    assert lp.bigpemu_keymap(tmp_path) is None


# ── ledblinky profiles ────────────────────────────────────────────────────────

def test_profiles_lights_each_wheel_from_its_emulator(cabinet):
    b = lp.plan_profiles(cabinet)
    assert {("Key 5", "KEYCODE_A"), ("OK", "KEYCODE_ENTER"), ("Left soft key", "KEYCODE_R")} <= \
        _voices(_group(b, "Nokia N-Gage"))
    assert {("X", "KEYCODE_A"), ("Black", "KEYCODE_C"), ("A", "KEYCODE_J")} <= _voices(_group(b, "Microsoft Xbox"))
    assert {("Red", "KEYCODE_D"), ("Play", "KEYCODE_R"), ("Green", "KEYCODE_G")} <= \
        _voices(_group(b, "Commodore Amiga CD32"))
    assert {("Button C", "KEYCODE_A"), ("Keypad 1", "KEYCODE_D"), ("Pause", "KEYCODE_R")} <= \
        _voices(_group(b, "Atari Jaguar"))


def test_profiles_gives_a_winuae_game_with_its_own_config_a_group(cabinet):
    b = lp.plan_profiles(cabinet)
    assert ("Red", "KEYCODE_F") in _voices(_group(b, "Commodore Amiga CD32", "Diggers"))
    groups = lp.ControlsXmlDoc.groups(b.doc.emulators()[lp.system_key("Commodore Amiga CD32")])
    assert "ZOOL" not in groups          # same keys as the wheel's host config


def test_profiles_rerun_changes_nothing(cabinet):
    lp.plan_profiles(cabinet).write(dry_run=False, backup=False)
    again = lp.plan_profiles(cabinet)
    assert again.doc.text == again._xml_original
