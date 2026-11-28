"""LEDBlinky profiles from PPSSPP, DuckStation, PCSX2 2.x and Vita3K keys.

These emulators keep their keyboard binds in their own files beside the exe
(portable installs), which ``ledblinky profiles`` couldn't read, so PSP,
PlayStation, PlayStation 2 and Vita wheels kept old profiles or lit only the
admin buttons.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import ledblinky_library as ll, ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

#: PPSSPP: device 1 is the keyboard (Android codes, 29 = A), 10 and 20 are pads.
PPSSPP_CONTROLS = """[ControlMapping]
Up = 1-19,20-19,10-19
Circle = 1-33,20-97,10-188
Cross = 1-32,20-96,10-189
Square = 1-29,20-99,10-191
Triangle = 1-30,20-100,10-190
Start = 1-46,20-108,10-197
Select = 1-47,20-109,10-196
L = 1-31,20-102,10-194
R = 1-34:1-35,20-103,10-195
SpeedToggle = 1-54
"""

#: DuckStation / PCSX2 2.x: one line per device; a chord is "a & b".
PAD_INI = """[Main]
SettingsVersion = 3

[Pad1]
Type = AnalogController
Up = Keyboard/Up
Square = Keyboard/A
Square = SDL-0/X
Triangle = Keyboard/B
L1 = Keyboard/C
L2 = Keyboard/V
Cross = Keyboard/D
Circle = Keyboard/E
R1 = Keyboard/F
R2 = Keyboard/W
Start = Keyboard/R
Select = Keyboard/S
L3 = SDL-0/LeftStick

[Pad2]
Type = AnalogController
Square = Keyboard/G
Cross = Keyboard/J
Start = Keyboard/T
Select = Keyboard/Shift & Keyboard/U

[Hotkeys]
SwitchToNextDisc = Keyboard/P
"""

VITA3K_CONFIG = """---
keyboard-button-select: KeyS
keyboard-button-start: KeyR
keyboard-button-up: KeyH
keyboard-button-down: KeyK
keyboard-button-l1: KeyC
keyboard-button-r1: KeyF
keyboard-button-l2: Unbound
keyboard-button-triangle: KeyB
keyboard-button-circle: KeyE
keyboard-button-cross: KeyD
keyboard-button-square: KeyA
keyboard-leftstick-left: ArrowLeft
keyboard-gui-fullscreen: F11
keyboard-button-square-alt: KeyV
...
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

WHEELS = {
    "Sony PSP": ("PPSSPP", "PPSSPP\\PPSSPPWindows64.exe"),
    "Sony Playstation": ("DuckStation", "DuckStation\\duckstation-qt-x64-ReleaseLTCG.exe"),
    "Sony Playstation 2": ("PCSX2", "PCSX2\\pcsx2-qt.exe"),
    "Sony PlayStation Vita": ("Vita3K", "Vita3K\\Vita3K.exe"),
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
        _db(root, wheel, ["Game One"])
    _write(emus / "PPSSPP" / "memstick" / "PSP" / "SYSTEM" / "controls.ini", PPSSPP_CONTROLS)
    _write(emus / "DuckStation" / "settings.ini", PAD_INI)
    _write(emus / "PCSX2" / "inis" / "PCSX2.ini", PAD_INI.replace("AnalogController", "DualShock2"))
    _write(emus / "Vita3K" / "portable" / "config.yml", VITA3K_CONFIG)
    _db(root, "Main Menu", list(WHEELS))
    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def _default(builder, system):
    emu = builder.doc.emulators()[lp.system_key(system)]
    return ET.fromstring(lp.ControlsXmlDoc.groups(emu)["DEFAULT"][0].strip())


def _voices(group):
    return {(c.get("voice"), c.get("inputCodes")) for p in group.iter("player")
            if p.get("number") != "0" for c in p.iter("control")}


# ── key codes ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected", [
    (29, "KEYCODE_A"), (54, "KEYCODE_Z"), (7, "KEYCODE_0"), (16, "KEYCODE_9"), (66, "KEYCODE_ENTER"),
    (62, "KEYCODE_SPACE"), (131, "KEYCODE_F1"), (144, "KEYCODE_0_PAD"), (19, "KEYCODE_UP"), (4000, None)])
def test_key_from_android(code, expected):
    assert lp.key_from_android(code) == expected


@pytest.mark.parametrize("name,expected", [
    ("A", "KEYCODE_A"), ("z", "KEYCODE_Z"), ("1", "KEYCODE_1"), ("F2", "KEYCODE_F2"),
    ("Return", "KEYCODE_ENTER"), ("Enter", "KEYCODE_ENTER"), ("Space", "KEYCODE_SPACE"),
    ("Numpad4", "KEYCODE_4_PAD"), ("Backtab", None)])
def test_key_from_keyboard_name(name, expected):
    assert lp.key_from_keyboard_name(name) == expected


@pytest.mark.parametrize("value,expected", [
    ("KeyS", "KEYCODE_S"), ("Digit3", "KEYCODE_3"), ("Numpad1", "KEYCODE_1_PAD"), ("F11", "KEYCODE_F11"),
    ("Enter", "KEYCODE_ENTER"), ("ArrowUp", "KEYCODE_UP"), ("Unbound", None), ("4", "KEYCODE_A")])
def test_key_from_vita3k(value, expected):
    assert lp.key_from_vita3k(value) == expected


# ── reading the files ─────────────────────────────────────────────────────────

def test_ppsspp_reads_keyboard_binds_only(tmp_path):
    _write(tmp_path / "memstick" / "PSP" / "SYSTEM" / "controls.ini", PPSSPP_CONTROLS)
    km = lp.ppsspp_keymap(tmp_path)
    assert km.keys == {(1, "Circle"): ["KEYCODE_E"], (1, "Cross"): ["KEYCODE_D"],
                       (1, "Square"): ["KEYCODE_A"], (1, "Triangle"): ["KEYCODE_B"],
                       (1, "Start"): ["KEYCODE_R"], (1, "Select"): ["KEYCODE_S"],
                       (1, "L"): ["KEYCODE_C"]}   # R is only a key combination; hotkeys are skipped
    assert km.labels["L"] == "L Button" and km.source == "PPSSPP controls.ini"
    assert lp.ppsspp_keymap(tmp_path / "elsewhere") is None


def test_pad_ini_reads_both_pads_and_skips_chords(tmp_path):
    km = lp.pad_ini_keymap(_write(tmp_path / "settings.ini", PAD_INI), "DuckStation settings.ini")
    assert km.get(1, "Square") == ["KEYCODE_A"] and km.get(1, "R2") == ["KEYCODE_W"]
    assert km.get(1, "Select") == ["KEYCODE_S"] and km.get(1, "L3") == []
    assert km.get(2, "Cross") == ["KEYCODE_J"] and km.get(2, "Select") == []
    assert (1, "SwitchToNextDisc") not in km.keys     # hotkeys aren't pad buttons


def test_pad_ini_drops_an_unplugged_pad(tmp_path):
    text = PAD_INI.replace("[Pad2]\nType = AnalogController", "[Pad2]\nType = None")
    km = lp.pad_ini_keymap(_write(tmp_path / "PCSX2.ini", text), "PCSX2")
    assert not any(p == 2 for p, _ in km.keys)


def test_pad_ini_without_pad_sections_is_none(tmp_path):
    assert lp.pad_ini_keymap(_write(tmp_path / "PCSX2.ini", "[UI]\nTheme = x\n"), "PCSX2") is None
    assert lp.pcsx2_keymap(tmp_path) is None          # PCSX2 1.x: no inis\PCSX2.ini


def test_vita3k_reads_main_and_alt_keys(tmp_path):
    _write(tmp_path / "portable" / "config.yml", VITA3K_CONFIG)
    km = lp.vita3k_keymap(tmp_path)
    assert km.source == "Vita3K portable\\config.yml"
    assert km.get(1, "square") == ["KEYCODE_A", "KEYCODE_V"]
    assert km.get(1, "up") == ["KEYCODE_H"] and km.get(1, "l2") == []
    assert km.labels["up"] == "D-pad Up"


def test_vita3k_config_beside_the_exe(tmp_path):
    _write(tmp_path / "config.yml", "keyboard-button-cross: 7\n")    # an older build's scancode
    assert lp.vita3k_keymap(tmp_path).get(1, "cross") == ["KEYCODE_D"]


# ── ledblinky profiles ────────────────────────────────────────────────────────

def test_profiles_lights_each_sony_wheel_from_its_emulator(cabinet):
    b = lp.plan_profiles(cabinet)
    psp = _voices(_default(b, "Sony PSP"))
    assert ("Cross", "KEYCODE_D") in psp and ("L Button", "KEYCODE_C") in psp
    assert not any(v == "R Button" for v, _ in psp)
    ps1 = _voices(_default(b, "Sony Playstation"))
    assert {("Square", "KEYCODE_A"), ("R2", "KEYCODE_W"), ("Square", "KEYCODE_G"),
            ("Start", "KEYCODE_T")} <= ps1
    ps2 = _voices(_default(b, "Sony Playstation 2"))
    assert ps2 == ps1
    vita = _voices(_default(b, "Sony PlayStation Vita"))
    assert {("Square", "KEYCODE_A|KEYCODE_V"), ("D-pad Up", "KEYCODE_H"), ("Select", "KEYCODE_S")} <= vita
    sources = {a.system: a.source for a in b.result.actions if a.action == "DEFAULT from keymap"}
    assert sources == {"Sony PSP": "PPSSPP controls.ini", "Sony Playstation": "DuckStation settings.ini",
                       "Sony Playstation 2": "PCSX2 inis\\PCSX2.ini",
                       "Sony PlayStation Vita": "Vita3K portable\\config.yml"}


def test_console_group_keeps_each_players_colours_on_a_rerun(tmp_path):
    # Player 2 binds fewer buttons, so the palette gives its Cross another colour than player 1's.
    panel = lp.load_panel(INPUT_MAP.parent)
    km = lp.pad_ini_keymap(_write(tmp_path / "settings.ini", PAD_INI), "DuckStation settings.ini")
    first = lp.build_console_group("DEFAULT", km, panel, None, "")
    again = lp.build_console_group("DEFAULT", km, panel, ET.fromstring(first.render()), "")
    assert again.render() == first.render()


def test_profiles_rerun_changes_nothing(cabinet):
    lp.plan_profiles(cabinet).write(dry_run=False, backup=False)
    again = lp.plan_profiles(cabinet)
    assert again.doc.text == again._xml_original
