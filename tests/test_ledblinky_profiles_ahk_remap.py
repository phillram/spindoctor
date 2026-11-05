"""LEDBlinky profiles through RocketLauncher's AHK keymapper (``Profiles\\AHK``).

RocketLauncher can load an AHK profile that swaps keys while a game runs
(``r::1``): the panel's Start sends R, the emulator gets 1.  A profile must
then light the panel key that sends 1, not look for a "1" button.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

CONTROLS_XML = """<?xml version="1.0"?>
<dat>
  <emulator emuname="MAME" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0">
    </controlGroup>
  </emulator>
  <emulator emuname="Sega_Naomi" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0" jukebox="0">
    </controlGroup>
    <controlGroup groupName="doa2" voice="Dead or Alive 2" numPlayers="2" alternating="0" jukebox="0">
      <player number="1">
        <control name="START1" voice="Start Game" color="White" inputCodes="KEYCODE_R" />
      </player>
    </controlGroup>
  </emulator>
  <emulator emuname="OTHER" emuDesc="">
    <controlGroup groupName="DEFAULT" numPlayers="2" />
  </emulator>
</dat>
"""

#: The remap a light-gun wheel uses: panel Start / Coin onto MAME's 1 / 5 / 2 / 6.
GUN_REMAP = "#MaxHotkeysPerInterval 200000000\n\nr::1\ns::5\n\nt::2\nu::6\n"

START_COIN = "".join(f"P{p}_{a}=1\n" for p in (1, 2) for a in ("START", "COIN"))


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _db(root: Path, system: str, games: list[tuple[str, str]]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{d}</description>\n'
                   f"    <cloneof></cloneof>\n  </game>\n" for n, d in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


def _mame_cfg(ports: dict[str, str]) -> str:
    body = "".join(f'<port type="{p}"><newseq type="standard">{s}</newseq></port>' for p, s in ports.items())
    return ('<?xml version="1.0"?><mameconfig version="10"><system name="default">'
            f"<input>{body}</input></system></mameconfig>")


def _ahk(config: Config, rel: str, text: str) -> Path:
    return _write(Path(config.rocketlauncher_dir) / "Profiles" / "AHK" / rel, text)


@pytest.fixture
def cabinet(tmp_path):
    """A miniature cabinet with the AHK keymapper on (Internal) and no AHK profiles yet."""
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini", "".join(f"[{rom}]\nnumPlayers=2\nP1_BUTTON1=1\n{START_COIN}\n"
                                         for rom in ("alien3", "quiet", "sf2")))
    _write(led / "Colors.ini", "")

    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "Global RocketLauncher.ini",
           "[Keymapper]\nKeymapper_Enabled=false\nKeymapper=xpadder\nKeymapper_AHK_Method=Internal\n")
    _write(settings / "Global Emulators.ini",
           "[MAME (Gun Games)]\nEmu_Path=..\\Emulators\\MAME (Gun Games)\\mame64.exe\n"
           "[Model 2]\nEmu_Path=..\\Emulators\\Model 2\\emulator_multicpu.exe\n"
           "[MAME]\nEmu_Path=..\\Emulators\\MAME\\mame64.exe\n"
           "[RetroArch]\nEmu_Path=..\\Emulators\\RetroArch\\retroarch.exe\n"
           "[Demul]\nEmu_Path=..\\Emulators\\Demul\\demul.exe\n")
    for system, emu in [("Gun Games", "MAME (Gun Games)"), ("MAME", "MAME"),
                        ("Nintendo Entertainment System", "RetroArch"), ("Sega Naomi", "Demul")]:
        _write(settings / system / "Emulators.ini", f"[ROMS]\nDefault_Emulator={emu}\n")
        _write(settings / system / "RocketLauncher.ini", "[Keymapper]\nKeymapper_AHK_Method=use_global\n")
    _write(settings / "Gun Games" / "Games.ini", "[hotd]\nEmulator=Model 2\n")

    emus = root / "Emulators"
    # Both MAME folders listen for MAME's own Start / Coin keys, not the panel's.
    for folder in ("MAME (Gun Games)", "MAME"):
        _write(emus / folder / "mame.ini", "ctrlr                     \n")
        _write(emus / folder / "cfg" / "default.cfg", _mame_cfg({
            "P1_BUTTON1": "KEYCODE_A", "START1": "KEYCODE_1", "COIN1": "KEYCODE_5",
            "START2": "KEYCODE_2", "COIN2": "KEYCODE_6"}))
    _write(emus / "Model 2" / "EMULATOR.INI", "")   # a keymap SpinDoctor can't read
    _write(emus / "RetroArch" / "config" / "Nintendo Entertainment System.cfg",
           'input_player1_b = "a"\ninput_player1_a = "b"\n'
           'input_player1_start = "num1"\ninput_player1_select = "num5"\n')
    _write(emus / "Demul" / "padDemul.ini", "[JAMMA0_0]\nPUSH1 = 30\nSTART = 2\nCOIN = 6\n")

    _db(root, "Main Menu", [(s, "") for s in ("Gun Games", "MAME", "Nintendo Entertainment System",
                                              "Sega Naomi", "Favorites")])
    _db(root, "Gun Games", [("alien3", "Alien3: The Gun"), ("quiet", "Quiet Gun"), ("hotd", "House of the Dead")])
    _db(root, "MAME", [("sf2", "Street Fighter II")])
    _db(root, "Nintendo Entertainment System", [("Contra (USA)", "Contra"), ("Duck Hunt (World)", "Duck Hunt")])
    _db(root, "Sega Naomi", [("doa2", "Dead or Alive 2")])
    _db(root, "Favorites", [("sf2", "Street Fighter II (MAME)")])

    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def _groups(builder, system):
    emu = builder.doc.emulators()[lp.emu_key(system)]
    return {k: ET.fromstring(v[0].strip()) for k, v in lp.ControlsXmlDoc.groups(emu).items()}


def _lit(group, panel):
    return sorted({panel[k] for c in group.iter("control")
                   for k in (c.get("inputCodes") or "").split("|") if k in panel})


# ── reading AHK profiles ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("r", "KEYCODE_R"), ("R", "KEYCODE_R"), ("1", "KEYCODE_1"), ("Enter", "KEYCODE_ENTER"),
    ("space", "KEYCODE_SPACE"), ("LCtrl", "KEYCODE_LCONTROL"), ("LAlt", "KEYCODE_LALT"),
    ("down", "KEYCODE_DOWN"), ("F2", "KEYCODE_F2"), ("Numpad0", "KEYCODE_0_PAD"), ("/", "KEYCODE_SLASH"),
    ("RButton", None), ("^c", None), ("", None)])
def test_key_from_ahk(name, expected):
    assert lp.key_from_ahk(name) == expected


def test_read_ahk_remap_takes_plain_one_key_remaps_only(tmp_path):
    path = _write(tmp_path / "Wheel.ahk", "\n".join([
        "#MaxHotkeysPerInterval 200000000",
        "; r::9 is a comment",
        "r::1",
        "$s::5",
        "~t::2",
        "u::6 ; coin 2",
        "c::Send {LControl down}{6 down}{LControl up}{6 up}",
        "ESCAPE::",
        "send !{F4}",
        "rbutton::5",
        "^d::e",
        "a::LButton",
        "r::7",
    ]) + "\n")
    remap = lp.read_ahk_remap(path)
    assert remap.source == "Wheel.ahk"
    assert remap.sends == {"KEYCODE_R": "KEYCODE_1", "KEYCODE_S": "KEYCODE_5", "KEYCODE_T": "KEYCODE_2",
                           "KEYCODE_U": "KEYCODE_6", "KEYCODE_A": ""}   # A sends a mouse button
    assert remap.passthrough == {"KEYCODE_T"}


def test_panel_keys_map_each_emulator_key_back():
    remap = lp.KeyRemap(source="t", sends={"KEYCODE_R": "KEYCODE_1", "KEYCODE_A": "KEYCODE_1",
                                           "KEYCODE_T": "KEYCODE_2", "KEYCODE_D": "KEYCODE_R"},
                        passthrough={"KEYCODE_T"})
    # Every panel key remapped to 1 reaches it, and 1 itself isn't remapped away.
    assert remap.panel_keys("KEYCODE_1") == ["KEYCODE_1", "KEYCODE_R", "KEYCODE_A"]
    # R is remapped away; only D now sends R.
    assert remap.panel_keys("KEYCODE_R") == ["KEYCODE_D"]
    # ``~t::2`` sends 2 and lets T through as well.
    assert remap.panel_keys("KEYCODE_T") == ["KEYCODE_T"]
    assert remap.panel_keys("KEYCODE_2") == ["KEYCODE_2", "KEYCODE_T"]
    assert remap.panel_keys("KEYCODE_B") == ["KEYCODE_B"]


def test_daphne_keeps_both_keyboard_keys_so_a_remap_onto_the_second_one_lights(tmp_path):
    # Daphne listens for R or 1; the wheel's profile turns the panel's R into 1.
    _write(tmp_path / "daphne" / "dapinput.ini",
           "[KEYBOARD]\nKEY_START1 = 114 49 0\nKEY_COIN1 = 115 53 0\nKEY_BUTTON1 = 97 32 0\n")
    km = lp.daphne_keymap(tmp_path / "daphne")
    assert km.get(1, "START") == ["KEYCODE_R", "KEYCODE_1"]
    assert km.get(1, "BUTTON1") == ["KEYCODE_A"]          # 32 (space) has no code here
    remap = lp.KeyRemap(source="t", sends={"KEYCODE_R": "KEYCODE_1", "KEYCODE_S": "KEYCODE_5"})
    assert km.remapped(remap).get(1, "START") == ["KEYCODE_1", "KEYCODE_R"]


def test_keymap_remapped_returns_a_new_keymap():
    km = lp.Keymap(source="MAME\\cfg", keys={(1, "START"): ["KEYCODE_1", "KEYCODE_R"],
                                            (1, "BUTTON1"): ["KEYCODE_A"]})
    out = km.remapped(lp.KeyRemap(source="Gun Games.ahk", sends={"KEYCODE_R": "KEYCODE_1"}))
    assert out.get(1, "START") == ["KEYCODE_1", "KEYCODE_R"]   # R itself no longer reaches START
    assert out.get(1, "BUTTON1") == ["KEYCODE_A"]
    assert out.source == "MAME\\cfg + AHK Gun Games.ahk"
    assert km.get(1, "START") == ["KEYCODE_1", "KEYCODE_R"]    # cached keymaps stay untouched


# ── which profile RocketLauncher loads ────────────────────────────────────────

def test_ahk_profile_first_that_exists(cabinet):
    for rel in ("_Default.ahk", "Gun Games.ahk", "Gun Games\\MAME (Gun Games).ahk", "Gun Games\\alien3.ahk"):
        _ahk(cabinet, rel.replace("\\", "/"), "r::1\n")
    rl = lp.RocketLauncherIndex(cabinet)
    ahk = Path(cabinet.rocketlauncher_dir) / "Profiles" / "AHK"
    emu = "MAME (Gun Games)"
    assert rl.ahk_profile("Gun Games", "alien3", emu) == ahk / "Gun Games" / "alien3.ahk"
    assert rl.ahk_profile("Gun Games", "ALIEN3", emu) == ahk / "Gun Games" / "alien3.ahk"   # any case
    assert rl.ahk_profile("Gun Games", "alien3j", emu) == ahk / "Gun Games" / "MAME (Gun Games).ahk"
    assert rl.ahk_profile("Gun Games", "alien3j", "Model 2") == ahk / "Gun Games.ahk"
    assert rl.ahk_profile("Gun Games", None, "Model 2") == ahk / "Gun Games.ahk"
    assert rl.ahk_profile("Sega Naomi", "doa2", "Demul") == ahk / "_Default.ahk"
    assert rl.ahk_remap("Gun Games", "alien3", emu).source == "Gun Games\\alien3.ahk"


@pytest.mark.parametrize("wheel,glob,on", [
    ("use_global", "Internal", True),
    (None, "External", True),
    ("Internal", "false", True),
    ("false", "Internal", False),
    ("use_global", None, False),     # no key anywhere: RocketLauncher's default is false
    (None, None, False),
])
def test_ahk_keymapper_method_setting(tmp_path, wheel, glob, on):
    settings = tmp_path / "RocketLauncher" / "Settings"
    if glob is not None:
        _write(settings / "Global RocketLauncher.ini",
               f"[Keymapper]\nKeymapper_Enabled=false\nKeymapper_AHK_Method={glob}\n")
    if wheel is not None:
        _write(settings / "Gun Games" / "RocketLauncher.ini", f"[keymapper]\nkeymapper_ahk_method={wheel}\n")
    cfg = Config(rocketlauncher_dir=str(tmp_path / "RocketLauncher"))
    _ahk(cfg, "Gun Games.ahk", GUN_REMAP)
    rl = lp.RocketLauncherIndex(cfg)
    assert rl.ahk_keymapper_on("Gun Games") is on
    assert (rl.ahk_remap("Gun Games", "alien3", "MAME") is not None) is on


def test_profiles_path_setting_moves_the_ahk_folder(tmp_path):
    rl_dir = tmp_path / "RocketLauncher"
    _write(rl_dir / "Settings" / "RocketLauncher.ini", "[Settings]\nProfiles_Path=..\\Keymaps\n")
    _write(rl_dir / "Settings" / "Global RocketLauncher.ini", "[Keymapper]\nKeymapper_AHK_Method=Internal\n")
    _write(tmp_path / "Keymaps" / "AHK" / "Gun Games.ahk", GUN_REMAP)
    rl = lp.RocketLauncherIndex(Config(rocketlauncher_dir=str(rl_dir)))
    assert rl.ahk_remap("Gun Games", "alien3", "MAME").sends["KEYCODE_R"] == "KEYCODE_1"


def test_assumed_keymaps_are_left_alone(cabinet):
    _ahk(cabinet, "Gun Games.ahk", GUN_REMAP)
    resolver = lp.KeymapResolver(cabinet)
    km = lp.arcade_layout_keymap()
    assert resolver.through_remap(km, "Gun Games", "alien3", None) is km
    assert resolver.through_remap(None, "Gun Games", "alien3", None) is None


# ── profiles ──────────────────────────────────────────────────────────────────

def test_gun_wheel_start_and_coin_light_through_the_wheel_remap(cabinet):
    _ahk(cabinet, "Gun Games.ahk", GUN_REMAP)
    # A game's own profile replaces the wheel's, even with no remaps in it.
    _ahk(cabinet, "Gun Games/quiet.ahk", "#MaxHotkeysPerInterval 200000000\n")
    b = lp.plan_profiles(cabinet)
    gun = _groups(b, "Gun Games")

    alien3 = gun["ALIEN3"]
    assert _lit(alien3, b.panel) == ["EXIT", "P1B1", "P1COIN", "P1START", "P2COIN", "P2START", "PAUSE"]
    codes = {c.get("name"): c.get("inputCodes") for c in alien3.iter("control")}
    assert codes["START1"] == "KEYCODE_1|KEYCODE_R" and codes["COIN2"] == "KEYCODE_6|KEYCODE_U"
    assert _lit(gun["QUIET"], b.panel) == ["EXIT", "P1B1", "PAUSE"]
    # hotd runs on an emulator whose keys can't be read: the assumed panel
    # Start / Coin keys aren't run through the remap.
    assert _lit(gun["HOTD"], b.panel) == ["EXIT", "P1COIN", "P1START", "P2COIN", "P2START", "PAUSE"]
    action = next(a for a in b.result.actions if a.system == "Gun Games")
    assert "1 through AHK keymapper profiles" in action.note   # quiet's profile remaps nothing

    b.write(dry_run=False)
    assert lp.plan_profiles(cabinet).write(dry_run=True).written == []


def test_keymapper_off_writes_what_no_profile_writes(cabinet):
    plain = lp.plan_profiles(cabinet).doc.text
    _ahk(cabinet, "Gun Games.ahk", GUN_REMAP)
    _ahk(cabinet, "Nintendo Entertainment System/Duck Hunt (World).ahk", "r::1\n")
    _write(Path(cabinet.rocketlauncher_dir) / "Settings" / "Gun Games" / "RocketLauncher.ini",
           "[Keymapper]\nKeymapper_AHK_Method=false\n")
    _write(Path(cabinet.rocketlauncher_dir) / "Settings" / "Nintendo Entertainment System" / "RocketLauncher.ini",
           "[Keymapper]\nKeymapper_AHK_Method=false\n")
    b = lp.plan_profiles(cabinet)
    assert b.doc.text == plain
    assert _lit(_groups(b, "Gun Games")["ALIEN3"], b.panel) == ["EXIT", "P1B1", "PAUSE"]


def test_console_game_with_its_own_profile_gets_its_own_group(cabinet):
    _ahk(cabinet, "Nintendo Entertainment System/Duck Hunt (World).ahk", "r::1\ns::5\n")
    b = lp.plan_profiles(cabinet)
    nes = _groups(b, "Nintendo Entertainment System")
    assert _lit(nes["DEFAULT"], b.panel) == ["EXIT", "P1B1", "P1B2", "PAUSE"]
    assert _lit(nes[lp.emu_key("Duck Hunt (World)")], b.panel) == ["EXIT", "P1B1", "P1B2", "P1COIN",
                                                                   "P1START", "PAUSE"]
    assert lp.emu_key("Contra (USA)") not in nes   # no profile of its own: DEFAULT is right


def test_console_default_uses_the_wheel_profile(cabinet):
    _ahk(cabinet, "Nintendo Entertainment System.ahk", "r::1\ns::5\n")
    b = lp.plan_profiles(cabinet)
    nes = _groups(b, "Nintendo Entertainment System")
    assert _lit(nes["DEFAULT"], b.panel) == ["EXIT", "P1B1", "P1B2", "P1COIN", "P1START", "PAUSE"]
    assert set(nes) == {"DEFAULT"}
    action = next(a for a in b.result.actions if a.system == "Nintendo Entertainment System")
    assert action.source.endswith("+ AHK Nintendo Entertainment System.ahk")


def test_rekeyed_arcade_group_uses_its_games_profile(cabinet):
    _ahk(cabinet, "Sega Naomi/doa2.ahk", "r::1\n")
    b = lp.plan_profiles(cabinet)
    doa2 = _groups(b, "Sega Naomi")["DOA2"]
    assert [c.get("inputCodes") for c in doa2.iter("control") if c.get("name") == "START1"] == ["KEYCODE_R"]


def test_collection_copy_of_a_mame_rom_uses_the_mame_wheel_profile(cabinet):
    _ahk(cabinet, "MAME.ahk", "r::1\ns::5\n")
    b = lp.plan_profiles(cabinet)
    # The profile remaps only P1's Start / Coin.
    assert _lit(_groups(b, "Favorites")["SF2"], b.panel) == ["EXIT", "P1B1", "P1COIN", "P1START", "PAUSE"]
