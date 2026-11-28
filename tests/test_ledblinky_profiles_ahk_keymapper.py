"""LEDBlinky profiles from AHK keymapper profiles, for emulators whose keys can't be read.

A PC game launcher or a Flash player has no key config SpinDoctor reads, so
such wheels lit only Exit / Pause.  RocketLauncher's AHK keymapper profile
(``Profiles\\AHK``) is what turns the panel's keys into the game's there:
``ledblinky profiles`` now lights the keys it remaps or binds.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import keymapper_hotkeys as kh, ledblinky_library as ll, ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

CONTROLS_XML = """<?xml version="1.0"?>
<dat>
  <emulator emuname="MAME" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0">
    </controlGroup>
  </emulator>
  <emulator emuname="Run_N_Gun" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON1" voice="Jump" alwaysActive="0" color="Red" inputCodes="KEYCODE_A" />
      </player>
    </controlGroup>
  </emulator>
  <emulator emuname="OTHER" emuDesc="">
    <controlGroup groupName="DEFAULT" numPlayers="2" />
  </emulator>
</dat>
"""

#: The cabinet's menu keys: the panel's stick and the first P2 button move RocketLauncher's menus.
NAVIGATION = ("[Navigation]\nNavigation_Up_Key=Up|W\nNavigation_Down_Key=Down|S\n"
              "Navigation_Left_Key=Left|A\nNavigation_Right_Key=Right|D\nNavigation_Select_Key=Enter|G\n"
              "Navigation_P2_Up_Key=N\nNavigation_P2_Down_Key=Q\nNavigation_P2_Left_Key=M\n"
              "Navigation_P2_Right_Key=O\nNavigation_P2_Select_Key=Enter|G\n")
NAV = {"w", "s", "a", "d", "enter", "g", "up", "down", "left", "right"}


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _db(root: Path, system: str, games: list[tuple[str, str]]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{d}</description>\n'
                   f"    <cloneof></cloneof>\n  </game>\n" for n, d in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


def _ahk(config: Config, rel: str, text: str) -> Path:
    return _write(Path(config.rocketlauncher_dir) / "Profiles" / "AHK" / rel, text)


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    """PC Games and Run N Gun on PCLauncher, Flash Games on a Flash player, NES on RetroArch."""
    monkeypatch.setattr(ll, "LIBRARY_DIR", tmp_path / "ledblinky_library")
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini", "")
    _write(led / "Colors.ini", "")

    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "RocketLauncher.ini", NAVIGATION)
    _write(settings / "Global RocketLauncher.ini", "[Keymapper]\nKeymapper_AHK_Method=Internal\n")
    _write(settings / "Global Emulators.ini",
           "[PCLauncher]\nEmu_Path=..\\Emulators\\PCLauncher\\PCLauncher.exe\n"
           "[EZ Flasher]\nEmu_Path=..\\Emulators\\EZ Flasher\\flasher.exe\n"
           "[RetroArch]\nEmu_Path=..\\Emulators\\RetroArch\\retroarch.exe\n")
    for system, emu in [("PC Games", "PCLauncher"), ("Run N Gun", "PCLauncher"),
                        ("Flash Games", "EZ Flasher"), ("Nintendo Entertainment System", "RetroArch")]:
        _write(settings / system / "Emulators.ini", f"[ROMS]\nDefault_Emulator={emu}\n")
        _write(settings / system / "RocketLauncher.ini", "[Keymapper]\nKeymapper_AHK_Method=use_global\n")

    emus = root / "Emulators"
    _write(emus / "PCLauncher" / "PCLauncher.exe", "")
    _write(emus / "EZ Flasher" / "flasher.exe", "")
    _write(emus / "RetroArch" / "config" / "Nintendo Entertainment System.cfg",
           'input_player1_b = "a"\ninput_player1_a = "b"\n'
           'input_player1_start = "r"\ninput_player1_select = "s"\n')

    _db(root, "Main Menu", [(s, "") for s in ("PC Games", "Run N Gun", "Flash Games",
                                              "Nintendo Entertainment System", "Favorites")])
    _db(root, "PC Games", [("Pac-Man 256", "Pac-Man 256"), ("Race Driver Grid", "Race Driver: GRID"),
                           ("Solitaire", "Solitaire")])
    _db(root, "Run N Gun", [("Broforce", "Broforce"), ("Cuphead", "Cuphead")])
    _db(root, "Flash Games", [("Moon Waltz", "Moon Waltz"), ("Super Mario Crossover", "Super Mario Crossover"),
                              ("Same As Wheel", "Same As Wheel"), ("Other Voice", "Other Voice"),
                              ("Bloons", "Bloons")])
    _db(root, "Nintendo Entertainment System", [("Contra (USA)", "Contra")])
    _db(root, "Favorites", [("Moon Waltz", "Moon Waltz (Flash Games)")])

    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def _groups(builder, system):
    emu = builder.doc.emulators()[lp.emu_key(system)]
    return {k: ET.fromstring(v[0].strip()) for k, v in lp.ControlsXmlDoc.groups(emu).items()}


def _lit(group, panel):
    return sorted({panel[k] for c in group.iter("control")
                   for k in (c.get("inputCodes") or "").split("|") if k in panel})


def _voices(group, panel):
    return {panel[k]: c.get("voice") for c in group.iter("control")
            for k in (c.get("inputCodes") or "").split("|")
            if k in panel and c.get("name", "").startswith(("P1_", "P2_"))}


# ── reading a profile's keys ──────────────────────────────────────────────────

def _keys(text: str, navigation=NAV):
    return [(k.key, k.does) for k in kh.profile_keys(text, {n: ("", "") for n in navigation})]


def test_remaps_light_their_left_hand_key_even_on_a_navigation_key():
    text = "#MaxHotkeysPerInterval 200000000\n\na::Space\n~e::Enter\nr::1 ; Start\n$f::LButton\n"
    assert _keys(text) == [("a", "Space"), ("e", "Enter"), ("r", "1"), ("f", "LButton")]


def test_plain_hotkeys_on_navigation_keys_never_fire_but_wildcards_do():
    text = "w::Send {Up}\n*a::Send {Enter}{Space}\nr::Send {1}{Enter}\n~s::Send x\n$d::Send y\n"
    # Internal: RocketLauncher's Hotkey commands take over w, s and d.
    assert _keys(text) == [("a", "Enter+Space"), ("r", "1+Enter")]
    # External: the profile is a script of its own, so every hotkey fires.
    assert _keys(text, navigation=()) == [("w", "Up"), ("a", "Enter+Space"), ("r", "1+Enter"),
                                          ("s", "x"), ("d", "y")]


def test_hotkey_bodies_below_the_line_and_stacked_hotkeys():
    text = "\n".join([
        "b::",
        "  Send, {LCtrl down}{Space}{LCtrl up}",
        "Return",
        "c::",
        "{",
        "  Run, notepad.exe",
        "}",
        "v::",
        "x::Send {Tab}",          # v falls through into x's line
        "e::",
        "Return",                 # e does nothing
    ])
    assert _keys(text) == [("b", "LCtrl+Space"), ("c", "Run"), ("v", "Tab"), ("x", "Tab")]


def test_keys_left_out():
    text = "\n".join([
        "/* block comment",
        "b::Space",
        "*/",
        "; c::Space",
        "^d::e",                  # needs Ctrl held
        "a & e::Space",
        "e up::Space",
        "x::Return",              # switched off
        "#IfWinActive ahk_exe game.exe",
        "f::Space",
        "#IfWinActive",
        "v::1",
        "v::2",                   # AutoHotkey refuses a second v
    ])
    assert _keys(text) == [("v", "1")]


def test_profile_keymap_takes_players_and_start_coin_from_the_input_map():
    panel = lp.load_panel(INPUT_MAP.parent)
    keys = kh.profile_keys("a::Space\nr::Enter\nu::5\ng::Space\nUp::w\nLButton::a\n~Enter::Space\n", {})
    km = lp.ahk_profile_keymap(keys, "PC Games\\x.ahk", panel)
    assert km.source == "AHK PC Games\\x.ahk"
    assert km.keys == {(1, "KEYCODE_A"): ["KEYCODE_A"], (1, "KEYCODE_R"): ["KEYCODE_R"],
                       (2, "KEYCODE_U"): ["KEYCODE_U"], (2, "KEYCODE_G"): ["KEYCODE_G"],
                       (1, "KEYCODE_ENTER"): ["KEYCODE_ENTER"]}      # the stick and the mouse have no LED
    assert km.labels["KEYCODE_A"] == "Space" and km.labels["KEYCODE_U"] == "5"
    assert km.system_actions == {"KEYCODE_R", "KEYCODE_U", "KEYCODE_ENTER"}


def test_profile_lookup_follows_rocketlaunchers_order(cabinet):
    _ahk(cabinet, "_Default.ahk", "c::Space\n")
    _ahk(cabinet, "Flash Games.ahk", "r::Space\n")
    _ahk(cabinet, "Flash Games/EZ Flasher.ahk", "b::Space\n")
    _ahk(cabinet, "Flash Games/Moon Waltz.ahk", "~a::Space\n")
    r = lp.KeymapResolver(cabinet)
    panel = lp.load_panel(Path(cabinet.ledblinky_dir))
    assert r.profile_keymap("Flash Games", "moon waltz", panel).source == "AHK Flash Games\\Moon Waltz.ahk"
    assert r.profile_keymap("Flash Games", "Bloons", panel).source == "AHK Flash Games\\EZ Flasher.ahk"
    assert r.profile_keymap("Flash Games", None, panel).source == "AHK Flash Games\\EZ Flasher.ahk"
    assert r.profile_keymap("PC Games", "Solitaire", panel).source == "AHK _Default.ahk"


# ── profiles ──────────────────────────────────────────────────────────────────

def test_flash_wheel_lights_its_profile_and_each_games_own(cabinet):
    _ahk(cabinet, "Flash Games.ahk", "#MaxHotkeysPerInterval 200000000\n\nr::Space\n")
    _ahk(cabinet, "Flash Games/Moon Waltz.ahk", "~a::Space\n")
    _ahk(cabinet, "Flash Games/Super Mario Crossover.ahk", "r::Send {1}{Enter}\n")
    _ahk(cabinet, "Flash Games/Same As Wheel.ahk", "r::Space\n")
    _ahk(cabinet, "Flash Games/Other Voice.ahk", "r::Enter\n")
    b = lp.plan_profiles(cabinet)
    flash = _groups(b, "Flash Games")
    assert _lit(flash["DEFAULT"], b.panel) == ["EXIT", "P1START", "PAUSE"]
    start = next(c for c in flash["DEFAULT"].iter("control") if c.get("inputCodes") == "KEYCODE_R")
    assert start.get("voice") == "Space" and start.get("name") == "P1_BUTTON9"   # lit as a Start button
    # Only the game's own file loads, so Moon Waltz lights A and not the wheel's R.
    assert _lit(flash["MOON_WALTZ"], b.panel) == ["EXIT", "P1B1", "PAUSE"]
    assert _voices(flash["SUPER_MARIO_CROSSOVER"], b.panel) == {"P1START": "1+Enter"}
    assert _voices(flash["OTHER_VOICE"], b.panel) == {"P1START": "Enter"}
    assert "SAME_AS_WHEEL" not in flash and "BLOONS" not in flash       # the DEFAULT serves them
    action = next(a for a in b.result.actions if a.system == "Flash Games")
    assert action.action == "DEFAULT from keymap" and action.source == "AHK Flash Games.ahk"
    # Favorites copies the game's own group.
    assert _lit(_groups(b, "Favorites")["MOON_WALTZ"], b.panel) == ["EXIT", "P1B1", "PAUSE"]

    b.write(dry_run=False)
    assert lp.plan_profiles(cabinet).write(dry_run=True).written == []


def test_wheel_without_a_profile_of_its_own_still_lights_its_games(cabinet):
    _ahk(cabinet, "PC Games/Pac-Man 256.ahk", "*a::Send {Enter}{Space}\nw::Send {Up}\n~Enter::Space\n")
    _ahk(cabinet, "PC Games/Race Driver Grid.ahk", "~up::a\n~down::z\n")
    b = lp.plan_profiles(cabinet)
    pc = _groups(b, "PC Games")
    assert _lit(pc["DEFAULT"], b.panel) == ["EXIT", "PAUSE"]
    assert _lit(pc["PAC-MAN_256"], b.panel) == ["EXIT", "P1B1", "PAUSE", "SELECT"]    # W never fires
    assert "RACE_DRIVER_GRID" not in pc        # its remaps are on the stick: nothing more to light
    assert "SOLITAIRE" not in pc
    assert [(a.action.split(" (")[0], a.groups) for a in b.result.actions if a.system == "PC Games"] == \
        [("admin-only DEFAULT", 1), ("per-game groups", 1)]


def test_hand_made_default_is_kept_and_games_get_their_own(cabinet):
    _ahk(cabinet, "Run N Gun/Broforce.ahk", "a::Space\nb::x\np::Esc\n")
    _ahk(cabinet, "Run N Gun/Cuphead.ahk", "p::Esc\n")     # Pause is lit by the admin block anyway
    b = lp.plan_profiles(cabinet)
    rng = _groups(b, "Run N Gun")
    assert _voices(rng["DEFAULT"], b.panel) == {"P1B1": "Jump"}
    broforce = rng["BROFORCE"]
    assert _voices(broforce, b.panel) == {"P1B1": "Space", "P1B2": "x"}
    assert next(c for c in broforce.iter("control") if c.get("voice") == "Space").get("color") == "Red"
    assert "CUPHEAD" not in rng
    assert any(a.system == "Run N Gun" and a.action == "kept existing DEFAULT" for a in b.result.actions)


def test_no_profiles_when_the_keymapper_is_off(cabinet):
    _write(Path(cabinet.rocketlauncher_dir) / "Settings" / "Flash Games" / "RocketLauncher.ini",
           "[Keymapper]\nKeymapper_AHK_Method=false\n")
    _ahk(cabinet, "Flash Games.ahk", "r::Space\n")
    _ahk(cabinet, "Flash Games/Moon Waltz.ahk", "~a::Space\n")
    b = lp.plan_profiles(cabinet)
    assert list(_groups(b, "Flash Games")) == ["DEFAULT"]
    assert _lit(_groups(b, "Flash Games")["DEFAULT"], b.panel) == ["EXIT", "PAUSE"]


def test_readable_emulators_still_go_through_the_remap(cabinet):
    # A RetroArch wheel's profile maps emulator keys back; it isn't a keymap of its own.
    _ahk(cabinet, "Nintendo Entertainment System.ahk", "x::r\n")
    b = lp.plan_profiles(cabinet)
    action = next(a for a in b.result.actions if a.system == "Nintendo Entertainment System")
    assert action.source.startswith("RetroArch") and action.source.endswith("+ AHK Nintendo Entertainment System.ahk")
    # X now sends RetroArch's Start key too; the profile's own keys aren't a keymap here.
    assert _lit(_groups(b, "Nintendo Entertainment System")["DEFAULT"], b.panel) == \
        ["EXIT", "P1B1", "P1B2", "P1COIN", "P1START", "P2B8", "PAUSE"]


@pytest.mark.parametrize("hand_authored", [False, True])
def test_removed_ahk_profile_only_removes_generated_group(cabinet, hand_authored):
    profile = _ahk(cabinet, "PC Games/Pac-Man 256.ahk", "a::Space\n")
    before = lp.plan_profiles(cabinet)
    if hand_authored:
        before.doc.text = before.doc.text.replace(lp._GENERATED_OVERRIDE, "")
    before.write(dry_run=False)
    old_group = lp.ControlsXmlDoc.groups(
        before.doc.emulators()[lp.emu_key("PC Games")])["PAC-MAN_256"]

    profile.unlink()
    after = lp.plan_profiles(cabinet)
    groups = _groups(after, "PC Games")
    if hand_authored:
        assert lp.ControlsXmlDoc.groups(
            after.doc.emulators()[lp.emu_key("PC Games")])["PAC-MAN_256"] == old_group
    else:
        assert "PAC-MAN_256" not in groups
        assert _lit(groups["DEFAULT"], after.panel) == ["EXIT", "PAUSE"]
    after.write(dry_run=False)
    assert lp.plan_profiles(cabinet).write(dry_run=True).written == []


def test_unreadable_emulator_override_keeps_generated_group(cabinet):
    system = "Nintendo Entertainment System"
    settings = Path(cabinet.rocketlauncher_dir) / "Settings"
    _write(settings / system / "Games.ini", "[Contra (USA)]\nEmulator=Other RetroArch\n")
    with (settings / "Global Emulators.ini").open("a", encoding="utf-8") as f:
        f.write("[Other RetroArch]\nEmu_Path=..\\Emulators\\Other RetroArch\\retroarch.exe\n")
    cfg = _write(Path(cabinet.emulators_dir) / "Other RetroArch" / "config" / f"{system}.cfg",
                 'input_player1_a = "c"\n')
    before = lp.plan_profiles(cabinet)
    before.write(dry_run=False)
    old_group = lp.ControlsXmlDoc.groups(before.doc.emulators()[lp.emu_key(system)])["CONTRA_(USA)"]
    assert lp._GENERATED_OVERRIDE in old_group[0]

    cfg.unlink()
    after = lp.plan_profiles(cabinet)
    assert lp.ControlsXmlDoc.groups(after.doc.emulators()[lp.emu_key(system)])["CONTRA_(USA)"] == old_group
