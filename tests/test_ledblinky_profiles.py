"""Tests for per-game LEDBlinky profiles built from the cabinet's real keymaps."""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import ledblinky_profiles as lp
from spindoctor.config import Config

INPUT_MAP = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"

ADMIN_P0 = """      <player number="0">
        <control name="CONTROL_JOY8WAY" voice="8-Way Joystick" primaryControl="1" alwaysActive="0" color="" inputCodes="" />
        <control name="UI_CANCEL" voice="" alwaysActive="1" color="Plum" inputCodes="KEYCODE_ESC" />
        <control name="UI_PAUSE" voice="" alwaysActive="1" color="Amber" inputCodes="KEYCODE_P|KEY_MAMEPAUSE" />
      </player>"""

CONTROLS_XML = f"""<?xml version="1.0"?>
<dat>
  <emulator emuname="MAME" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0">
      <player number="0">
        <control name="UI_CANCEL" voice="" alwaysActive="1" color="Plum" />
      </player>
    </controlGroup>
    <controlGroup groupName="asteroid" voice="" numPlayers="2" alternating="1">
      <player number="1">
        <control name="P1_BUTTON3" voice="Fire" color="White" />
        <control name="P1_BUTTON4" voice="Thrust" color="White" />
      </player>
    </controlGroup>
  </emulator>
  <emulator emuname="Nintendo_Entertainment_System" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0" defaultActive="48,48,48,48" defaultInactive="0,0,0,0" jukebox="0">
{ADMIN_P0}
      <player number="1">
        <control name="P1_BUTTON1" voice="Button B" alwaysActive="0" color="Red" inputCodes="KEYCODE_A" />
        <control name="P1_JOYSTICK_UP" voice="Up" alwaysActive="0" color="Black" inputCodes="JOYCODE_1_UP" />
      </player>
    </controlGroup>
  </emulator>
  <emulator emuname="Sega_Naomi" emuDesc="">
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0" jukebox="0">
{ADMIN_P0}
    </controlGroup>
    <controlGroup groupName="DEFAULT" voice="" numPlayers="2" alternating="0" jukebox="0">
    </controlGroup>
    <controlGroup groupName="doa2" voice="Dead or Alive 2" numPlayers="2" alternating="0" jukebox="0">
      <player number="1">
        <control name="P1_BUTTON4" voice="Hold" color="White" inputCodes="KEYCODE_A" />
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


def _db(root: Path, system: str, games: list[tuple[str, str, str]]) -> None:
    body = "".join(f'  <game name="{n}">\n    <description>{d}</description>\n'
                   f"    <cloneof>{c}</cloneof>\n  </game>\n" for n, d, c in games)
    _write(root / "Databases" / system / f"{system}.xml", f"<menu>\n{body}</menu>\n")


def _mame_cfg(ports: dict[str, str], tag: bool = False) -> str:
    t = ' tag=":IN0" mask="1" defvalue="0"' if tag else ""
    body = "".join(f'<port type="{p}"{t}><newseq type="standard">{s}</newseq></port>' for p, s in ports.items())
    name = "game" if tag else "default"
    return f'<?xml version="1.0"?><mameconfig version="10"><system name="{name}"><input>{body}</input></system></mameconfig>'


@pytest.fixture
def cabinet(tmp_path):
    """A miniature cabinet: RocketLauncher settings, emulators, databases, LEDBlinky."""
    root = tmp_path / "Arcade"
    led = root / "LEDBlinky"
    led.mkdir(parents=True)
    shutil.copy(INPUT_MAP, led / lp.INPUT_MAP_NAME)
    _write(led / "LEDBlinkyControls.xml", CONTROLS_XML)
    _write(led / "Controls.ini",
           "[sf2]\nnumPlayers=2\nalternating=0\n" + "".join(f"P1_BUTTON{i}=1\n" for i in range(1, 7))
           + "P1_START=1\nP1_COIN=1\n" + "".join(f"P2_BUTTON{i}=1\n" for i in range(1, 7))
           + "P2_START=1\nP2_COIN=1\n\n"
           "[mrdrillr]\nnumPlayers=1\n" + "".join(f"P1_BUTTON{i}=1\n" for i in range(1, 7)) + "P1_START=1\n\n"
           "[doa2]\nnumPlayers=2\nP1_BUTTON1=1\nP1_BUTTON2=1\nP1_BUTTON3=1\nP1_BUTTON4=1\n\n")
    _write(led / "Colors.ini", "[sf2]\nP1_BUTTON1=Red\nP1_START=Black\n\n[mrdrillr]\nP1_BUTTON1=Blue\n")
    _write(led / "controls.ini.20260527_211753.bak",
           "[mrdrillr]\nP1NumButtons=1\nP1_BUTTON1=Drill\n\n[sf2]\nP1NumButtons=6\nP1_BUTTON1=Jab\n")

    settings = root / "RocketLauncher" / "Settings"
    _write(settings / "Global Emulators.ini",
           "[RetroArch]\nEmu_Path=..\\Emulators\\RetroArch\\retroarch.exe\n"
           "[MAME]\nEmu_Path=..\\Emulators\\MAME\\mame64.exe\n"
           "[RetroArch (MultiPlayer)]\nEmu_Path=..\\Emulators\\RetroArch (MultiPlayer)\\retroarch.exe\n"
           "[Demul57]\nEmu_Path=..\\Emulators\\Demul\\demul.exe\n")
    for system, emu in [("Nintendo Entertainment System", "RetroArch"), ("Capcom Play System II", "MAME"),
                        ("MAME", "MAME"), ("Sega Naomi", "Demul57")]:
        _write(settings / system / "Emulators.ini", f"[ROMS]\nDefault_Emulator={emu}\n")
    _write(settings / "Nintendo Entertainment System" / "Games.ini",
           "<!--comment-->\n[Contra (USA) (MultiPlayer)]\nEmulator=RetroArch (MultiPlayer)\nSystem=\n")

    emus = root / "Emulators"
    _write(emus / "RetroArch" / "retroarch.cfg", 'input_player1_b = "z"\n')
    _write(emus / "RetroArch" / "config" / "Nintendo Entertainment System.cfg",
           'input_player1_b = "a"\ninput_player1_a = "b"\ninput_player1_start = "r"\n'
           'input_player1_select = "s"\ninput_player2_b = "g"\ninput_player1_x = "z"\n')
    _write(emus / "RetroArch (MultiPlayer)" / "retroarch.cfg", 'input_player1_b = "num4"\n')
    _write(emus / "RetroArch (MultiPlayer)" / "config" / "Nintendo Entertainment System.cfg",
           'input_player1_b = "num1"\ninput_player1_a = "num2"\n')
    _write(emus / "MAME" / "mame.ini", "ctrlr                     \n")
    _write(emus / "MAME" / "cfg" / "default.cfg", _mame_cfg({
        **{f"P1_BUTTON{i}": f"KEYCODE_{k} OR JOYCODE_1_BUTTON{i}" for i, k in enumerate("ABCDEF", 1)},
        **{f"P2_BUTTON{i}": f"KEYCODE_{k}" for i, k in enumerate("GHIJKL", 1)},
        "START1": "KEYCODE_R", "START2": "KEYCODE_T", "COIN1": "KEYCODE_S", "COIN2": "KEYCODE_U"}))
    _write(emus / "Demul" / "padDemul.ini",
           "[JAMMA0_0]\nPUSH1 = 30\nPUSH2 = 48\nPUSH3 = 46\nPUSH4 = 32\nSTART = 19\nCOIN = 31\n"
           "[JAMMA0_1]\nPUSH1 = 34\nSTART = 20\n")

    _db(root, "Main Menu", [(s, "", "") for s in
                            ("MAME", "Capcom Play System II", "Nintendo Entertainment System",
                             "Sega Naomi", "PC Games", "Favorites")])
    _db(root, "MAME", [("sf2", "Street Fighter II", ""), ("mrdrillr", "Mr. Driller", ""),
                       ("sf2ce", "Street Fighter II CE", "sf2")])
    _db(root, "Capcom Play System II", [("sf2", "Street Fighter II", ""), ("sf2xbox", "SF2 4P", "")])
    _db(root, "Nintendo Entertainment System", [("Contra (USA)", "Contra", ""),
                                                ("Contra (USA) (MultiPlayer)", "Contra MP", "")])
    _db(root, "Sega Naomi", [("doa2", "Dead or Alive 2", ""), ("mvsc2", "MvC2", "")])
    _db(root, "PC Games", [("Cuphead", "Cuphead", "")])
    _db(root, "Favorites", [("sf2", "Street Fighter II (MAME)", ""),
                            ("Contra (USA)", "Contra (Nintendo Entertainment System)", "")])

    return Config(hyperspin_dir=str(root), rocketlauncher_dir=str(root / "RocketLauncher"),
                  emulators_dir=str(emus), ledblinky_dir=str(led))


def _groups(builder, system):
    emu = builder.doc.emulators()[lp.emu_key(system)]
    return {k: ET.fromstring(v[0].strip()) for k, v in lp.ControlsXmlDoc.groups(emu).items()}


def _lit(group, panel):
    return sorted({panel[k] for c in group.iter("control")
                   for k in (c.get("inputCodes") or "").split("|") if k in panel})


# ── key normalisation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("a", "KEYCODE_A"), ("num1", "KEYCODE_1"), ("keypad4", "KEYCODE_4PAD"),
    ("enter", "KEYCODE_ENTER"), ("rshift", "KEYCODE_RSHIFT"), ("nul", None), ("", None)])
def test_key_from_retroarch(name, expected):
    assert lp.key_from_retroarch(name) == expected


def test_key_from_dik_and_ascii():
    assert lp.key_from_dik(0x1E) == "KEYCODE_A"
    assert lp.key_from_dik(19) == "KEYCODE_R"
    assert lp.key_from_ascii(69) == "KEYCODE_E"     # Windows VK
    assert lp.key_from_ascii(114) == "KEYCODE_R"    # SDL lower-case
    assert lp.key_from_ascii(300) is None


def test_keys_from_mame_seq_keeps_single_keycodes_only():
    assert lp.keys_from_mame_seq("KEYCODE_A OR JOYCODE_1_BUTTON3") == ["KEYCODE_A"]
    assert lp.keys_from_mame_seq("NONE") == []
    assert lp.keys_from_mame_seq("KEYCODE_LSHIFT KEYCODE_A") == []  # a combo isn't one key


# ── keymap readers ────────────────────────────────────────────────────────────

def test_panel_routes_by_input_codes():
    panel = lp.load_panel(INPUT_MAP.parent)
    assert panel["KEYCODE_A"] == "P1B1"
    assert panel["KEYCODE_D"] == "P1B5"   # bottom-row first button
    # Buttons 4 and 8 sit at the end of each row and send V/W (P1) and Y/X (P2).
    assert [panel[f"KEYCODE_{k}"] for k in "VWYX"] == ["P1B4", "P1B8", "P2B4", "P2B8"]


def test_retroarch_system_cfg_overrides_base(cabinet):
    ra = lp.RetroArchIndex(Path(cabinet.emulators_dir) / "RetroArch")
    km = ra.keymap("nintendo entertainment system")   # case-insensitive file match
    assert km.get(1, "b") == ["KEYCODE_A"]
    assert km.get(1, "a") == ["KEYCODE_B"]
    assert ra.keymap("Missing System") is None


def test_mame_index_default_and_game_cfg(cabinet):
    folder = Path(cabinet.emulators_dir) / "MAME"
    _write(folder / "cfg" / "sf2.cfg", _mame_cfg({"P1_BUTTON1": "KEYCODE_F"}, tag=True))
    idx = lp.MameIndex(folder, "mame64.exe")
    assert idx.keymap().get(1, "BUTTON4") == ["KEYCODE_D"]
    assert idx.keymap("sf2").get(1, "BUTTON1") == ["KEYCODE_F"]
    assert idx.keymap().get(1, "START") == ["KEYCODE_R"]


def test_mame_index_skips_ports_no_cfg_remaps(tmp_path):
    # A wheel/gun MAME setup that never maps P2 Button 4 or P1 Button 6: MAME
    # would fall back to W and X, which are P1 Button 8 and P2 Button 8 here.
    folder = tmp_path / "MAME (Driving Games)"
    _write(folder / "mame.ini", "ctrlr                     \n")
    _write(folder / "cfg" / "default.cfg", _mame_cfg({"P1_BUTTON1": "KEYCODE_A"}))
    km = lp.MameIndex(folder, "mame64.exe").keymap("coolridr")
    assert km.keys == {(1, "BUTTON1"): ["KEYCODE_A"]}


def test_mame_index_blank_ctrlr_does_not_read_next_line(tmp_path):
    folder = tmp_path / "MAME"
    _write(folder / "mame.ini", "ctrlr                     \nmouse 1\n")
    _write(folder / "ctrlr" / "mouse 1.cfg", _mame_cfg({"P1_BUTTON1": "KEYCODE_Z"}))
    _write(folder / "cfg" / "default.cfg", _mame_cfg({}))
    assert lp.MameIndex(folder, "mame64.exe").keymap().get(1, "BUTTON1") == []


def test_mame_index_reads_named_ctrlr(tmp_path):
    folder = tmp_path / "MAME (Gun Games)(Other)"
    _write(folder / "mame.ini", "ctrlr                     gunconfig\n")
    _write(folder / "ctrlr" / "gunconfig.cfg", _mame_cfg({"COIN1": "KEYCODE_S"}))
    assert lp.MameIndex(folder, "mame64.exe").keymap().get(1, "COIN") == ["KEYCODE_S"]


def test_mame_driver_keymap_ignores_builtins(cabinet):
    folder = Path(cabinet.emulators_dir) / "MAME"
    _write(folder / "cfg" / "coleco.cfg", _mame_cfg({"P1_BUTTON1": "KEYCODE_A"}, tag=True))
    km = lp.MameIndex(folder, "mame64.exe").driver_keymap("coleco")
    assert km.keys == {(1, "BUTTON1"): ["KEYCODE_A"]}   # no P2 builtin A/S leaking in
    assert lp.MameIndex(folder, "mame64.exe").driver_keymap("nothere") is None


def test_demul_zinc_ssf_desmume_readers(tmp_path):
    _write(tmp_path / "demul" / "padDemul.ini", "[JAMMA0_0]\nPUSH1 = 30\nPUSH4 = 32\nCOIN = 31\n[JAMMA0_1]\nPUSH1 = 34\n")
    km = lp.demul_keymap(tmp_path / "demul")
    assert km.get(1, "BUTTON4") == ["KEYCODE_D"] and km.get(2, "BUTTON1") == ["KEYCODE_G"]

    _write(tmp_path / "zinc" / "controller.cfg", "[player1]\nbtn1=k1E\nstart=k13\n[player2]\nbtn1=k22\n")
    km = lp.zinc_keymap(tmp_path / "zinc")
    assert km.get(1, "BUTTON1") == ["KEYCODE_A"] and km.get(1, "START") == ["KEYCODE_R"]
    assert km.get(2, "BUTTON1") == ["KEYCODE_G"]

    _write(tmp_path / "ssf" / "SSF.ini",
           'Pad0_0_0="2/200/2/208/2/203/2/205/2/32/2/18/2/33/2/30/2/48/2/46/2/44/2/45/2/19"\n')
    km = lp.ssf_keymap(tmp_path / "ssf")
    assert km.get(1, "A") == ["KEYCODE_D"] and km.get(1, "X") == ["KEYCODE_A"]
    assert km.get(1, "Start") == ["KEYCODE_R"]

    _write(tmp_path / "ds" / "desmume.ini", "[Controls]\nA=69\nB=68\nY=65\nStart=82\n")
    km = lp.desmume_keymap(tmp_path / "ds")
    assert km.get(1, "A") == ["KEYCODE_E"] and km.get(1, "Y") == ["KEYCODE_A"]


def test_games_ini_tolerates_html_comments(cabinet):
    rl = lp.RocketLauncherIndex(cabinet)
    assert rl.game_overrides("Nintendo Entertainment System") == {
        "Contra (USA) (MultiPlayer)": ("RetroArch (MultiPlayer)", "")}
    lau = rl.launcher("RetroArch", "Nintendo Entertainment System")
    assert lau.folder == Path(cabinet.emulators_dir) / "RetroArch"


# ── group building ────────────────────────────────────────────────────────────

def test_console_group_lights_only_routed_keys():
    panel = lp.load_panel(INPUT_MAP.parent)
    km = lp.Keymap(source="t", labels=dict(lp.CONSOLE_LABELS["Nintendo Entertainment System"]),
                   keys={(1, "b"): ["KEYCODE_A"], (1, "a"): ["KEYCODE_B"], (1, "start"): ["KEYCODE_R"],
                         (1, "x"): ["KEYCODE_Z"]})   # Z has no LED -> dropped
    g = lp.build_console_group("DEFAULT", km, panel, None, ADMIN_P0)
    names = {c.name: (c.voice, c.color) for c in g.controls}
    assert names["P1_BUTTON1"] == ("Button B", "Red")
    assert names["P1_BUTTON9"][0] == "Start" and names["P1_BUTTON9"][1] == "Black"
    assert all("KEYCODE_Z" not in c.input_codes for c in g.controls)


def test_console_group_never_leaves_a_used_face_button_dim():
    panel = lp.load_panel(INPUT_MAP.parent)
    old = ET.fromstring('<controlGroup groupName="DEFAULT"><player number="1">'
                        '<control name="P1_BUTTON1" voice="Button A" color="Black" inputCodes="KEYCODE_A"/>'
                        '</player></controlGroup>')
    km = lp.Keymap(source="t", labels={"a": "Button A"}, keys={(1, "a"): ["KEYCODE_A"]})
    g = lp.build_console_group("DEFAULT", km, panel, old, "")
    assert g.controls[0].color != "Black"


def test_arcade_group_uses_controls_and_colors():
    panel = lp.load_panel(INPUT_MAP.parent)
    ctl = {"numPlayers": "2", "P1_BUTTON1": "1", "P1_BUTTON4": "1", "P1_START": "1", "P3_BUTTON1": "1"}
    g = lp.build_arcade_group("sf2", ctl, {"P1_BUTTON1": "Red"}, lp.arcade_layout_keymap(), panel,
                              ADMIN_P0, {1: "Jab"})
    by = {c.name: c for c in g.controls}
    assert by["P1_BUTTON1"].color == "Red" and by["P1_BUTTON1"].voice == "Jab"
    assert by["P1_BUTTON4"].input_codes == ["KEYCODE_D"]      # bottom row, not a duplicate of A
    assert by["START1"].input_codes == ["KEYCODE_R"]
    assert not any(c.player == 3 for c in g.controls)           # the panel has two players
    assert "UI_CANCEL" in g.render()


def test_rekey_fixes_button4_duplicate():
    panel = lp.load_panel(INPUT_MAP.parent)
    block = '<controlGroup groupName="x"><player number="1"><control name="P1_BUTTON4" inputCodes="KEYCODE_A" /></player></controlGroup>'
    out = lp.rekey_arcade_group(block, lp.arcade_layout_keymap(), panel)
    assert 'inputCodes="KEYCODE_D"' in out
    assert lp.rekey_arcade_group(out, lp.arcade_layout_keymap(), panel) is None   # idempotent


def test_upsert_groups_replaces_dedupes_and_adds_emulators():
    doc = lp.ControlsXmlDoc(CONTROLS_XML)
    doc.upsert_groups("Sega Naomi", [lp.GroupXml(name="DEFAULT")])
    assert len(lp.ControlsXmlDoc.groups(doc.emulators()["SEGA_NAOMI"])["DEFAULT"]) == 1
    doc.upsert_groups("Capcom Play System II", [lp.GroupXml(name="sf2")])
    text = doc.text
    assert text.index('emuname="Capcom_Play_System_II"') < text.index('emuname="OTHER"')
    ET.fromstring(text)   # still well-formed


# ── end to end ────────────────────────────────────────────────────────────────

def test_plan_profiles_end_to_end(cabinet):
    b = lp.plan_profiles(cabinet)
    panel = b.panel

    nes = _groups(b, "Nintendo Entertainment System")
    assert _lit(nes["DEFAULT"], panel) == ["EXIT", "P1B1", "P1B2", "P1COIN", "P1START", "P2B1", "PAUSE"]
    # The MultiPlayer variant launches on numpad keys: nothing on the panel but admin.
    assert _lit(nes[lp.emu_key("Contra (USA) (MultiPlayer)")], panel) == ["EXIT", "PAUSE"]

    cps2 = _groups(b, "Capcom Play System II")
    assert _lit(cps2["SF2"], panel) == ["EXIT", "P1B1", "P1B2", "P1B3", "P1B5", "P1B6", "P1B7",
                                        "P1COIN", "P1START", "P2B1", "P2B2", "P2B3", "P2B5",
                                        "P2B6", "P2B7", "P2COIN", "P2START", "PAUSE"]
    assert "SF2XBOX" in cps2    # base ROM sf2 found by stripping the xbox suffix

    naomi = _groups(b, "Sega Naomi")
    doa2 = naomi["DOA2"]
    assert [c.get("inputCodes") for c in doa2.iter("control") if c.get("name") == "P1_BUTTON4"] == ["KEYCODE_D"]
    assert "EXIT" in _lit(doa2, panel)   # admin added to a group that had none

    assert _lit(_groups(b, "PC Games")["DEFAULT"], panel) == ["EXIT", "PAUSE"]

    fav = _groups(b, "Favorites")
    assert "P1B7" in _lit(fav["SF2"], panel)
    assert _lit(fav[lp.emu_key("Contra (USA)")], panel) == _lit(nes["DEFAULT"], panel)

    # MAME: sf2ce borrows its parent's Controls.ini entry; mrdrillr takes the
    # community's 1-button count (no XML group, no per-game remap).
    assert b.controls_for("sf2ce") == b.controls_for("sf2")
    assert [k for k in b.controls_for("mrdrillr") if k.startswith("P1_BUTTON")] == ["P1_BUTTON1"]
    assert "asteroid" not in b.result.controls_ini_community


def test_dry_run_writes_nothing_and_apply_backs_up(cabinet, tmp_path):
    led = Path(cabinet.ledblinky_dir)
    before = {p.name: p.read_bytes() for p in led.iterdir()}
    res = lp.plan_profiles(cabinet).write(dry_run=True)
    assert res.written and {p.name: p.read_bytes() for p in led.iterdir()} == before

    res = lp.plan_profiles(cabinet).write(dry_run=False)
    assert len(res.backups) == 3
    ET.parse(led / "LEDBlinkyControls.xml")
    assert "[sf2ce]" in (led / "Controls.ini").read_text(encoding="utf-8")
    # A second run finds nothing left to change.
    assert lp.plan_profiles(cabinet).write(dry_run=True).written == []


def test_collection_members_from_description(cabinet):
    members = lp.collection_members(cabinet, "Favorites")
    assert ("sf2", "MAME", "sf2") in members
    assert ("Contra (USA)", "Nintendo Entertainment System", "Contra (USA)") in members


def test_collection_members_prefers_pclauncher_ini(cabinet):
    _write(Path(cabinet.rocketlauncher_dir) / "Modules" / "PCLauncher" / "Favorites.ini",
           '[Street Fighter II]\nParameters=-s "MAME" -r "sf2"\n')
    assert lp.collection_members(cabinet, "Favorites") == [("Street Fighter II", "MAME", "sf2")]


def test_community_joystick_sets_servostik_mode():
    assert lp.community_joystick({"P1Controls": "4-way Joystick+joy4way"}) == "CONTROL_JOY4WAY"
    assert lp.community_joystick({"P1Controls": "Just Buttons+button"}) is None
    p0 = lp.set_primary_joystick(ADMIN_P0, "CONTROL_JOY4WAY")
    assert 'name="CONTROL_JOY4WAY"' in p0 and "CONTROL_JOY8WAY" not in p0
    assert lp.set_primary_joystick(ADMIN_P0, None) == ADMIN_P0


def test_chained_parents_resolve_in_one_run(cabinet):
    # A hack whose parent is another hack listed after it in the database.
    _db(Path(cabinet.hyperspin_dir), "HBMAME", [("sf2hack2", "SF2 hack of hack", "sf2hack"),
                                                ("sf2hack", "SF2 hack", "sf2")])
    mm = Path(cabinet.hyperspin_dir) / "Databases" / "Main Menu" / "Main Menu.xml"
    mm.write_text(mm.read_text(encoding="utf-8").replace("</menu>", '  <game name="HBMAME">\n'
                  "    <description></description>\n    <cloneof></cloneof>\n  </game>\n</menu>"),
                  encoding="utf-8")
    b = lp.plan_profiles(cabinet)
    assert b.controls_for("sf2hack2") == b.controls_for("sf2")
    b.write(dry_run=False)
    assert lp.plan_profiles(cabinet).write(dry_run=True).written == []


def test_console_fallback_colors_avoid_colors_already_used():
    panel = lp.load_panel(INPUT_MAP.parent)
    old = ET.fromstring('<controlGroup groupName="DEFAULT"><player number="1">'
                        '<control name="P1_BUTTON1" voice="Button B" color="Red" inputCodes="KEYCODE_D"/>'
                        '<control name="P1_BUTTON2" voice="L Button" color="Black" inputCodes="KEYCODE_C"/>'
                        '</player></controlGroup>')
    km = lp.Keymap(source="t", labels={"l": "L Button", "b": "Button B"},
                   keys={(1, "l"): ["KEYCODE_C"], (1, "b"): ["KEYCODE_D"]})
    colors = {c.voice: c.color for c in lp.build_console_group("DEFAULT", km, panel, old, "").controls}
    assert colors["Button B"] == "Red"
    assert colors["L Button"] not in ("Red", "Black")
