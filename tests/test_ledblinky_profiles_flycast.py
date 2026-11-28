"""LEDBlinky profiles from Flycast's keyboard maps (Dreamcast, Naomi, Atomiswave).

Flycast keeps its keys in ``mappings\\SDL_Keyboard*.cfg`` beside the exe, as
``bindN = <SDL scancode>:<action>`` lines.  ``ledblinky profiles`` couldn't read
them, so Flycast wheels kept their old profiles or lit only Exit / Pause.
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

#: Flycast's Dreamcast map on a panel: X Y L on the top row, A B R below, Start on R (21); P2 likewise.
DC_MAP = """[digital]
bind0 = 4:btn_x
bind1 = 5:btn_y
bind2 = 6:btn_trigger_left
bind3 = 7:btn_a
bind4 = 8:btn_b
bind5 = 9:btn_trigger_right
bind6 = 21:btn_start
bind7 = 82:btn_analog_up
bind8 = 10:btn_x1
bind9 = 11:btn_y1
bind10 = 12:btn_trigger_left1
bind11 = 13:btn_a1
bind12 = 14:btn_b1
bind13 = 15:btn_trigger_right1
bind14 = 23:btn_start1
bind15 = 58:btn_menu
bind16 = 16:btn_x2

[emulator]
mapping_name = Keyboard
version = 3
"""

#: The arcade map: buttons 1-3 on A B C, 4-6 on D E F, 7-8 on V W, Start R, Coin S; P2 G H I / J K L.
ARCADE_MAP = "[digital]\n" + "".join(
    f"bind{i} = {code}:{act}\n" for i, (code, act) in enumerate([
        (4, "btn_a"), (5, "btn_b"), (6, "btn_c"), (7, "btn_x"), (8, "btn_y"), (9, "btn_z"),
        (25, "btn_dpad2_left"), (26, "btn_dpad2_right"), (21, "btn_start"), (22, "btn_d"),
        (82, "btn_dpad1_up"), (59, "btn_dpad2_up"), (61, "btn_dpad2_down"),
        (10, "btn_a1"), (11, "btn_b1"), (12, "btn_c1"), (13, "btn_x1"), (14, "btn_y1"), (15, "btn_z1"),
        (23, "btn_start1"), (24, "btn_d1")])) + "\n[emulator]\nversion = 3\n"

CONTROLS_XML = """<?xml version="1.0"?>
<dat>
  <emulator emuname="MAME" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0">
    </controlGroup>
  </emulator>
  <emulator emuname="Sega_Naomi" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON1" voice="" color="Red" inputCodes="KEYCODE_A" />
        <control name="P1_BUTTON5" voice="" color="Red" inputCodes="KEYCODE_E" />
        <control name="START1" voice="Start" color="White" inputCodes="KEYCODE_1" />
      </player>
    </controlGroup>
    <controlGroup groupName="ggx" voice="Guilty Gear X" numPlayers="2" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON5" voice="Slash" color="Red" inputCodes="KEYCODE_E" />
        <control name="P1_BUTTON6" voice="Heavy Slash" color="Blue" inputCodes="KEYCODE_F" />
      </player>
    </controlGroup>
    <controlGroup groupName="vs2_2k" voice="Virtua Striker 2" numPlayers="2" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON1" voice="Shoot" color="Red" inputCodes="KEYCODE_A" />
      </player>
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


def _db(root: Path, system: str, games: list[tuple[str, str]]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{d}</description>\n'
                   f"    <cloneof></cloneof>\n  </game>\n" for n, d in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


def _cart(path: Path, title: bytes, magic: bytes = b"NAOMI", member: str = "epr-21929c.ic22") -> Path:
    """A ROM zip whose cartridge header holds *title*, with another ROM in front of it."""
    header = magic.ljust(16) + b"SEGA ENTERPRISES".ljust(32) + title.ljust(32) + b"\0" * 0x30
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mpr-21914.ic1", b"\x12" * 0x100)
        z.writestr(member, header)
    return path


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    """Dreamcast, Naomi and Atomiswave wheels, all on one portable Flycast."""
    monkeypatch.setattr(ll, "LIBRARY_DIR", tmp_path / "ledblinky_library")
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini", "".join(
        f"[{rom}]\nnumPlayers=2\n" + "".join(f"P1_BUTTON{i}=1\n" for i in range(1, n + 1))
        + "P1_START=1\nP1_COIN=1\n\n" for rom, n in (("ggx", 6), ("vs2_2k", 3), ("ftspeed", 2))))
    _write(led / "Colors.ini", "")

    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "Global Emulators.ini", "")
    games = tmp_path / "Games"
    for system, ext in (("Sega Dreamcast", "gdi|chd"), ("Sega Naomi", "zip"), ("Sammy Atomiswave", "zip")):
        _write(settings / system / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator=Flycast\nRom_Path={games / system}\n"
               f"[Flycast]\nEmu_Path=..\\Emulators\\Flycast\\flycast.exe\nRom_Extension={ext}\n")

    flycast = root / "Emulators" / "Flycast"
    _write(flycast / "flycast.exe", "")
    _write(flycast / "mappings" / "SDL_Keyboard.cfg", DC_MAP)
    _write(flycast / "mappings" / "SDL_Keyboard_arcade.cfg", ARCADE_MAP)
    # Guilty Gear X: buttons 5 and 6 swapped.
    _write(flycast / "mappings" / "SDL_Keyboard_GUILTY GEAR X V1.00_arcade.cfg",
           ARCADE_MAP.replace("8:btn_y\n", "9:btn_y\n").replace("9:btn_z\n", "8:btn_z\n"))
    # A Dreamcast game's own map is named after the product number inside its disc.
    _write(flycast / "mappings" / "SDL_Keyboard_MK-51035.cfg", DC_MAP.replace("4:btn_x", "29:btn_x"))
    _cart(games / "Sega Naomi" / "ggx.zip", b"GUILTY GEAR X V1.00", member="epr-23356.ic22")
    _cart(games / "Sega Naomi" / "vs2_2k.zip", b"VIRTUA STRIKER 2 VER.2000")
    _write(games / "Sammy Atomiswave" / "ftspeed.zip", "")
    _write(games / "Sega Dreamcast" / "Crazy Taxi" / "Crazy Taxi.gdi", "")

    _db(root, "Main Menu", [(s, "") for s in ("Sega Dreamcast", "Sega Naomi", "Sammy Atomiswave")])
    _db(root, "Sega Dreamcast", [("Crazy Taxi", "Crazy Taxi")])
    _db(root, "Sega Naomi", [("ggx", "Guilty Gear X"), ("vs2_2k", "Virtua Striker 2 Ver. 2000")])
    _db(root, "Sammy Atomiswave", [("ftspeed", "Faster Than Speed")])
    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(root / "Emulators"), ledblinky_dir=str(led))


def _groups(builder, system):
    emu = builder.doc.emulators()[lp.emu_key(system)]
    return {k: ET.fromstring(v[0].strip()) for k, v in lp.ControlsXmlDoc.groups(emu).items()}


def _codes(group):
    return {c.get("name"): c.get("inputCodes") for c in group.iter("control")}


def _lit(group, panel):
    return sorted({panel[k] for c in group.iter("control")
                   for k in (c.get("inputCodes") or "").split("|") if k in panel})


# ── reading Flycast's files ───────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected", [
    (4, "KEYCODE_A"), (29, "KEYCODE_Z"), (30, "KEYCODE_1"), (39, "KEYCODE_0"), (40, "KEYCODE_ENTER"),
    (44, "KEYCODE_SPACE"), (58, "KEYCODE_F1"), (69, "KEYCODE_F12"), (82, "KEYCODE_UP"),
    (89, "KEYCODE_1_PAD"), (98, "KEYCODE_0_PAD"), (224, "KEYCODE_LCONTROL"), (3, None), (300, None)])
def test_key_from_sdl_scancode(code, expected):
    assert lp.key_from_sdl_scancode(code) == expected


def test_dreamcast_map_reads_both_ports(tmp_path):
    km = lp.flycast_keymap(_write(tmp_path / "SDL_Keyboard.cfg", DC_MAP), arcade=False)
    assert km.source == "Flycast mappings\\SDL_Keyboard.cfg"
    assert km.keys == {(1, "X"): ["KEYCODE_A"], (1, "Y"): ["KEYCODE_B"], (1, "L"): ["KEYCODE_C"],
                       (1, "A"): ["KEYCODE_D"], (1, "B"): ["KEYCODE_E"], (1, "R"): ["KEYCODE_F"],
                       (1, "Start"): ["KEYCODE_R"], (2, "X"): ["KEYCODE_G"], (2, "Y"): ["KEYCODE_H"],
                       (2, "L"): ["KEYCODE_I"], (2, "A"): ["KEYCODE_J"], (2, "B"): ["KEYCODE_K"],
                       (2, "R"): ["KEYCODE_L"], (2, "Start"): ["KEYCODE_T"]}
    # The stick, the menu and port C (btn_x2) have no light.
    assert km.labels["L"] == "L Trigger" and km.labels["Start"] == "Start"


def test_arcade_map_reads_buttons_start_and_coin(tmp_path):
    km = lp.flycast_keymap(_write(tmp_path / "SDL_Keyboard_arcade.cfg", ARCADE_MAP), arcade=True)
    assert [km.get(1, f"BUTTON{i}") for i in range(1, 9)] == [
        ["KEYCODE_A"], ["KEYCODE_B"], ["KEYCODE_C"], ["KEYCODE_D"], ["KEYCODE_E"], ["KEYCODE_F"],
        ["KEYCODE_V"], ["KEYCODE_W"]]
    assert km.get(1, "START") == ["KEYCODE_R"] and km.get(1, "COIN") == ["KEYCODE_S"]
    assert km.get(2, "BUTTON4") == ["KEYCODE_J"] and km.get(2, "COIN") == ["KEYCODE_U"]
    assert not km.labels                          # arcade groups keep their own voices


def test_key_file_follows_flycasts_order(tmp_path):
    names = ("SDL_Keyboard.cfg", "sdl_keyboard_arcade.cfg", "SDL_Keyboard_MK-51035.cfg",
             "SDL_Keyboard_INITIAL D Ver.2_arcade.cfg", "SDL_Keyboard_ JAMBO SAFARI_arcade.cfg",
             "SDL_Keyboard_A-B_arcade.cfg", "SDL_Keyboard_ONLY DC NAME.cfg")
    files = {n.lower(): tmp_path / n for n in names}
    pick = lp.flycast_key_file
    assert pick(files, False).name == "SDL_Keyboard.cfg"
    assert pick(files, False, "MK-51035").name == "SDL_Keyboard_MK-51035.cfg"
    assert pick(files, True).name == "sdl_keyboard_arcade.cfg"
    assert pick(files, True, "INITIAL D Ver.2").name == "SDL_Keyboard_INITIAL D Ver.2_arcade.cfg"
    assert pick(files, True, " JAMBO SAFARI").name == "SDL_Keyboard_ JAMBO SAFARI_arcade.cfg"   # leading space kept
    assert pick(files, True, "A:B").name == "SDL_Keyboard_A-B_arcade.cfg"                       # ":" is "-"
    # An arcade game's Dreamcast-named file counts only when there's no general arcade file.
    assert pick(files, True, "ONLY DC NAME").name == "sdl_keyboard_arcade.cfg"
    del files["sdl_keyboard_arcade.cfg"]
    assert pick(files, True, "ONLY DC NAME").name == "SDL_Keyboard_ONLY DC NAME.cfg"
    assert pick({}, True) is None


def test_naomi_boot_title_from_the_cartridge_header(tmp_path):
    assert lp.naomi_boot_title(_cart(tmp_path / "a.zip", b" JAMBO SAFARI ------------")) == \
        " JAMBO SAFARI ------------"
    assert lp.naomi_boot_title(_cart(tmp_path / "b.zip", b"WILD RIDERS IN JAPAN", magic=b"Naomi2",
                                     member="epr-23622.ic11")) == "WILD RIDERS IN JAPAN"
    assert lp.naomi_boot_title(_cart(tmp_path / "c.zip", b"\xff" * 32)) is None     # title further on
    assert lp.naomi_boot_title(_cart(tmp_path / "d.zip", b"X", magic=b"SEGA SEGAKATANA")) is None
    assert lp.naomi_boot_title(_write(tmp_path / "e.zip", "not a zip")) is None
    assert lp.naomi_boot_title(tmp_path / "missing.zip") is None


# ── profiles ──────────────────────────────────────────────────────────────────

def test_dreamcast_default_from_flycasts_map(cabinet):
    b = lp.plan_profiles(cabinet)
    dc = _groups(b, "Sega Dreamcast")
    assert _lit(dc["DEFAULT"], b.panel) == ["EXIT", "P1B1", "P1B2", "P1B3", "P1B5", "P1B6", "P1B7", "P1START",
                                            "P2B1", "P2B2", "P2B3", "P2B5", "P2B6", "P2B7", "P2START", "PAUSE"]
    assert {c.get("voice") for c in dc["DEFAULT"].iter("control") if c.get("inputCodes") == "KEYCODE_C"} == \
        {"L Trigger"}
    # Its own map is named after the disc's product number, which isn't read: no group of its own.
    assert list(dc) == ["DEFAULT"]
    action = next(a for a in b.result.actions if a.system == "Sega Dreamcast")
    assert action.action == "DEFAULT from keymap" and action.source == "Flycast mappings\\SDL_Keyboard.cfg"


def test_naomi_groups_are_rekeyed_to_flycasts_keys(cabinet):
    b = lp.plan_profiles(cabinet)
    naomi = _groups(b, "Sega Naomi")
    assert _codes(naomi["DEFAULT"])["START1"] == "KEYCODE_R"            # was MAME-style 1
    # Guilty Gear X's own map, found through the title in its cartridge header.
    assert _codes(naomi["GGX"])["P1_BUTTON5"] == "KEYCODE_F" and _codes(naomi["GGX"])["P1_BUTTON6"] == "KEYCODE_E"
    # Virtua Striker 2 has a header but no map of its own: the general arcade map.
    assert _codes(naomi["VS2_2K"])["P1_BUTTON1"] == "KEYCODE_A"
    action = next(a for a in b.result.actions if a.system == "Sega Naomi")
    assert action.action == "re-keyed existing arcade groups" and action.source.endswith("SDL_Keyboard_arcade.cfg")

    b.write(dry_run=False)
    assert lp.plan_profiles(cabinet).write(dry_run=True).written == []


def test_atomiswave_without_a_section_gets_per_game_groups(cabinet):
    b = lp.plan_profiles(cabinet)
    aw = _groups(b, "Sammy Atomiswave")
    assert _lit(aw["FTSPEED"], b.panel) == ["EXIT", "P1B1", "P1B2", "P1COIN", "P1START", "PAUSE"]


def test_per_game_maps_are_not_looked_for_without_any(cabinet, monkeypatch):
    flycast = Path(cabinet.emulators_dir) / "Flycast" / "mappings"
    (flycast / "SDL_Keyboard_GUILTY GEAR X V1.00_arcade.cfg").unlink()
    (flycast / "SDL_Keyboard_MK-51035.cfg").unlink()
    r = lp.KeymapResolver(cabinet)
    lau = r.system_launcher("Sega Naomi")
    calls = []
    monkeypatch.setattr(lp, "naomi_boot_title", lambda rom: calls.append(rom))
    assert r.for_launcher(lau, "Sega Naomi", "ggx") is None
    assert calls == []                                                 # no zip opened
    assert r.for_launcher(lau, "Sega Naomi").source == "Flycast mappings\\SDL_Keyboard_arcade.cfg"
