"""Tests for the `doctor` **Daphne keys** check (``health.check_daphne_keys``)
and the ``dapinput.ini`` reader behind it (``spindoctor.daphne_keys``).

Daphne 1.0.x and its Singe builds (SDL 1.2) read ``KEY_QUIT = 27 0 0`` as two
keyboard keys and a joystick button.  SDL 1.2 reports keys it has no name
for, such as volume keys, as 0, so a 0 key slot matches them: one Volume Up
press can quit the game.  The fixtures copy the real files' layout (CRLF,
no BOM, the order DaphneLoader writes).
"""
from __future__ import annotations

import pytest

from spindoctor import daphne_keys, health
from spindoctor.config import Config
from spindoctor.daphne_keys import read_key_file

# A stock DaphneLoader key file: R/1 start, A/B/C buttons, Esc quit, P pause,
# and a 0 second slot on everything that has only one key.
STOCK = (
    "[KEYBOARD]\r\n"
    "KEY_UP = 273 264 0\r\n"
    "KEY_LEFT = 276 260 0\r\n"
    "KEY_DOWN = 274 258 0\r\n"
    "KEY_RIGHT = 275 262 0\r\n"
    "KEY_START1 = 114 49 0\r\n"
    "KEY_START2 = 116 50 0\r\n"
    "KEY_BUTTON1 = 97 0 0\r\n"
    "KEY_BUTTON2 = 98 0 0\r\n"
    "KEY_BUTTON3 = 99 0 0\r\n"
    "KEY_COIN1 = 115 53 0\r\n"
    "KEY_COIN2 = 117 54 0\r\n"
    "KEY_SKILL1 = 103 0 0\r\n"
    "KEY_SKILL2 = 104 0 0\r\n"
    "KEY_SKILL3 = 105 0 0\r\n"
    "KEY_SERVICE = 57 0 0\r\n"
    "KEY_TEST = 283 0 0\r\n"
    "KEY_RESET = 284 0 0\r\n"
    "KEY_SCREENSHOT = 293 0 0\r\n"
    "KEY_QUIT = 27 0 0\r\n"
    "KEY_PAUSE = 112 0 0\r\n"
    "KEY_TILT = 0 0 0\r\n"
    "END\r\n"
)
FILLED = STOCK.replace(" 0 0\r\n", " 296 0\r\n").replace("KEY_TILT = 0 296 0", "KEY_TILT = 296 296 0")

# A Singe build's short file: only the keys its games use.  Everything it
# leaves out keeps Daphne's built-in keys.
SHORT = (
    "[KEYBOARD]\r\n"
    "KEY_UP = 273 296 0\r\n"
    "KEY_DOWN = 274 296 0\r\n"
    "KEY_RIGHT = 275 296 0\r\n"
    "KEY_LEFT = 276 296 0\r\n"
    "KEY_BUTTON1 = 122 296 0\r\n"
    "KEY_BUTTON2 = 120 296 0\r\n"
    "KEY_COIN1 = 53 296 0\r\n"
    "KEY_START1 = 49 296 0\r\n"
    "KEY_PAUSE = 112 296 0\r\n"
    "KEY_SERVICE = 283 296 0\r\n"
    "KEY_SCREENSHOT = 293 296 0\r\n"
    "KEY_QUIT = 293 296 0\r\n"
    "END\r\n"
)


def _write(path, text, raw=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw + text.encode("latin-1"))
    return path


def _zero(path):
    return [s.action for s in read_key_file(path).zero_slots()]


def _cabinet(tmp_path):
    """RocketLauncher and Emulators folders with no emulator installed."""
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    emus = tmp_path / "Emulators"
    emus.mkdir()
    cfg = Config(rocketlauncher_dir=str(rl), emulators_dir=str(emus))
    return cfg, rl, emus


def _register(rl, section, emu_path, ini=None):
    """Add an emulator entry to Global Emulators.ini (or another settings file)."""
    ini = ini or rl / "Settings" / "Global Emulators.ini"
    text = ini.read_text(encoding="utf-8") if ini.exists() else "\n"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(text + f"[{section}]\nEmu_Path={emu_path}\nRom_Extension=txt\n", encoding="utf-8")


def _exe(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "daphne.exe").write_bytes(b"MZ")
    return folder


def _node(result, path):
    return next(c for c in result.children if c.name.endswith(str(path)))


# ── the reader ────────────────────────────────────────────────────────────────

def test_stock_file_leaves_quit_pause_service_and_test_on_key_0_first(tmp_path):
    zero = _zero(_write(tmp_path / "dapinput.ini", STOCK))
    assert zero[:6] == ["KEY_QUIT", "KEY_PAUSE", "KEY_SERVICE", "KEY_TEST", "KEY_RESET", "KEY_TILT"]
    assert set(zero) == {"KEY_QUIT", "KEY_PAUSE", "KEY_SERVICE", "KEY_TEST", "KEY_RESET", "KEY_TILT",
                         "KEY_SCREENSHOT", "KEY_BUTTON1", "KEY_BUTTON2", "KEY_BUTTON3",
                         "KEY_SKILL1", "KEY_SKILL2", "KEY_SKILL3"}


def test_filled_file_leaves_nothing_on_key_0(tmp_path):
    # KEY_CONSOLE isn't in the file: its built-in 0 slot is harmless (it does nothing).
    assert _zero(_write(tmp_path / "dapinput.ini", FILLED)) == []


def test_fixed_line_fills_each_0_key_slot_and_keeps_the_button(tmp_path):
    report = read_key_file(_write(tmp_path / "dapinput.ini", STOCK.replace(
        "KEY_QUIT = 27 0 0", "KEY_QUIT = 27 0 3")))
    assert report.slots["KEY_QUIT"].fixed() == "KEY_QUIT = 27 296 3"
    assert report.slots["KEY_TILT"].fixed() == "KEY_TILT = 296 296 0"
    assert report.slots["KEY_QUIT"].line == 20


def test_a_0_joystick_button_is_fine(tmp_path):
    text = FILLED.replace("KEY_QUIT = 27 296 0", "KEY_QUIT = 27 113 0").replace("\r\n", "\n")
    assert _zero(_write(tmp_path / "dapinput.ini", text)) == []


def test_actions_left_out_keep_daphnes_built_in_keys(tmp_path):
    report = read_key_file(_write(tmp_path / "dapinput.ini", SHORT))
    zero = [s.action for s in report.zero_slots()]
    assert zero == ["KEY_TEST", "KEY_RESET", "KEY_TILT", "KEY_COIN2", "KEY_START2",
                    "KEY_BUTTON3", "KEY_SKILL1", "KEY_SKILL2", "KEY_SKILL3"]
    assert report.slots["KEY_TEST"].line == 0
    assert report.slots["KEY_TEST"].fixed() == "KEY_TEST = 283 296 0"
    assert "KEY_CONSOLE" not in zero


def test_a_word_in_a_key_slot_counts_as_0_like_atoi(tmp_path):
    path = _write(tmp_path / "dapinput.ini", FILLED.replace("KEY_PAUSE = 112 296 0",
                                                            "KEY_PAUSE = 112 none 0"))
    assert _zero(path) == ["KEY_PAUSE"]


def test_lines_before_the_header_and_after_end_are_not_read(tmp_path):
    text = "KEY_PAUSE = 112 0 0\r\n" + FILLED + "KEY_QUIT = 27 0 0\r\n"
    assert _zero(_write(tmp_path / "dapinput.ini", text)) == []


def test_names_and_header_match_in_any_case(tmp_path):
    text = FILLED.replace("[KEYBOARD]", "[Keyboard]").replace("KEY_QUIT = 27 296 0",
                                                              "key_quit = 27 0 0")
    assert _zero(_write(tmp_path / "dapinput.ini", text)) == ["KEY_QUIT"]


def test_no_header_means_the_built_in_keys(tmp_path):
    report = read_key_file(_write(tmp_path / "dapinput.ini", FILLED.replace("[KEYBOARD]\r\n", "")))
    assert not report.header
    zero = [s.action for s in report.zero_slots()]
    assert "KEY_PAUSE" in zero and "KEY_START1" in zero
    assert "KEY_QUIT" not in zero  # built in: Esc and Q


def test_a_byte_order_mark_hides_the_header_from_daphne(tmp_path):
    report = read_key_file(_write(tmp_path / "dapinput.ini", FILLED, raw=b"\xef\xbb\xbf"))
    assert report.bom and not report.header
    assert "KEY_PAUSE" in [s.action for s in report.zero_slots()]


@pytest.mark.parametrize("bad", ["KEY_QUIT=27 296 0", "KEY_QUIT = 27 296", "KEY_JUMP = 1 2 0",
                                 "; comment"])
def test_daphne_stops_reading_at_a_line_it_cannot_parse(tmp_path, bad):
    text = FILLED.replace("KEY_QUIT = 27 296 0\r\n", bad + "\r\n")
    report = read_key_file(_write(tmp_path / "dapinput.ini", text))
    assert report.stopped_line == 20 and report.stopped
    # KEY_PAUSE comes after the bad line, so it keeps its built-in P and 0.
    assert [s.action for s in report.zero_slots()] == ["KEY_PAUSE", "KEY_TILT"]


def test_missing_file_means_the_built_in_keys(tmp_path):
    report = read_key_file(tmp_path / "dapinput.ini")
    assert not report.exists
    assert report.slots["KEY_PAUSE"].keys == (112, 0)


def test_the_filler_is_sdl_1_2_f15():
    assert daphne_keys.FILLER == 296
    assert daphne_keys.label("KEY_SERVICE") == "service"


# ── the doctor check ──────────────────────────────────────────────────────────

def test_daphne_and_its_controls_files_warn_with_the_lines_to_write(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    daphne = _exe(emus / "Daphne")
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    live = _write(daphne / "dapinput.ini", STOCK)
    default = _write(daphne / "controls" / "dapinput.ini", STOCK)
    game = _write(daphne / "controls" / "gpworld.ini", FILLED)
    _write(daphne / "controls" / "readme.txt", "not a key file")

    result = health.check_daphne_keys(cfg)
    assert result.status == health.Status.WARN
    assert [c.name for c in result.children] == [f"Daphne: {p}" for p in (live, default, game)]
    node = _node(result, live)
    assert node.status == health.Status.WARN
    assert node.detail.startswith("quit, pause, service, test, reset and 8 more left on key 0")
    assert "volume" in node.detail and "controls\\<game>.ini" in node.detail
    assert "296 (F15, a key nothing sends)" in node.fix
    assert "set KEY_QUIT = 27 296 0, KEY_PAUSE = 112 296 0, KEY_SERVICE = 57 296 0 and 10 more" in node.fix
    assert "controls" not in _node(result, default).detail
    assert _node(result, game).status == health.Status.OK
    assert result.detail.startswith("2 of 3 key files leave actions on key 0")


def test_filled_files_pass(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _write(_exe(emus / "Daphne") / "dapinput.ini", FILLED)
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    result = health.check_daphne_keys(cfg)
    assert result.status == health.Status.OK
    assert result.detail == "1 key file: no action left on key 0"
    assert result.children[0].detail == "no action left on key 0"


def test_singe_builds_in_their_own_folders_are_found(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    alg = _exe(emus / "American Laser Games" / "data")
    wow = _exe(emus / "WoW Action Max" / "data")
    _register(rl, "Daphne Singe", "..\\Emulators\\American Laser Games\\data\\daphne.exe")
    _register(rl, "Daphne Singe (WoW Action Max)", "..\\Emulators\\WoW Action Max\\data\\daphne.exe")
    _write(alg / "dapinput.ini", FILLED)
    short = _write(wow / "dapinput.ini", SHORT)

    result = health.check_daphne_keys(cfg)
    assert {c.name.split(":")[0] for c in result.children} == {"Daphne Singe",
                                                               "Daphne Singe (WoW Action Max)"}
    node = _node(result, short)
    assert node.status == health.Status.WARN
    assert node.detail.startswith("test, reset, tilt, coin2, start2 and 4 more left on key 0")
    assert "9 of them aren't in the file, so Daphne's built-in keys apply" in node.detail
    assert "add KEY_TEST = 283 296 0, KEY_RESET = 284 296 0, KEY_TILT = 116 296 0 and 6 more " \
           "before END" in node.fix
    assert "set " not in node.fix


def test_emulators_sharing_a_folder_share_its_rows(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _write(_exe(emus / "Daphne") / "dapinput.ini", FILLED)
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    _register(rl, "Daphne (Overlay)", "..\\Emulators\\daphne\\DAPHNE.EXE")
    result = health.check_daphne_keys(cfg)
    # One folder on every OS: RocketLauncher's paths ignore case, as Windows does.
    assert [c.name.split(": ")[0] for c in result.children] == ["Daphne, Daphne (Overlay)"]
    assert result.children[0].name.endswith(str(emus / "Daphne" / "dapinput.ini"))


def test_a_renamed_build_is_found_by_its_key_file(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    folder = emus / "Laserdisc"
    _write(folder / "dapinput.ini", STOCK)
    (folder / "ld.exe").write_bytes(b"MZ")
    _register(rl, "Laserdisc", "..\\Emulators\\Laserdisc\\ld.exe")
    result = health.check_daphne_keys(cfg)
    assert [c.name.split(":")[0] for c in result.children] == ["Laserdisc"]
    assert result.status == health.Status.WARN


def test_a_system_s_own_emulator_entry_is_found(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _write(_exe(emus / "Daphne") / "dapinput.ini", STOCK)
    local = rl / "Settings" / "LaserDisc" / "Emulators.ini"
    _write(local, "[ROMS]\r\nDefault_Emulator=Daphne Local\r\nRom_Path=..\\Games\\Daphne\r\n")
    _register(rl, "Daphne Local", "..\\Emulators\\Daphne\\daphne.exe", ini=local)
    result = health.check_daphne_keys(cfg)
    assert [c.name.split(":")[0] for c in result.children] == ["Daphne Local"]


def test_other_emulators_are_ignored(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    (emus / "MAME").mkdir()
    (emus / "MAME" / "mame.exe").write_bytes(b"MZ")
    _register(rl, "MAME", "..\\Emulators\\MAME\\mame.exe")
    result = health.check_daphne_keys(cfg)
    assert result.status == health.Status.INFO
    assert result.detail == "no Daphne or Singe emulator found"


def test_registered_exe_that_is_missing_is_skipped(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    assert health.check_daphne_keys(cfg).status == health.Status.INFO


def test_falls_back_to_emulators_dir_when_rocketlauncher_lists_none(tmp_path):
    cfg, _rl, emus = _cabinet(tmp_path)
    path = _write(emus / "Daphne" / "dapinput.ini", STOCK)
    result = health.check_daphne_keys(cfg)
    assert [c.name for c in result.children] == [f"Daphne: {path}"]
    assert result.status == health.Status.WARN


def test_missing_live_file_is_info_when_controls_will_supply_it(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    daphne = _exe(emus / "Daphne")
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    _write(daphne / "controls" / "dapinput.ini", FILLED)
    result = health.check_daphne_keys(cfg)
    live = _node(result, daphne / "dapinput.ini")
    assert live.status == health.Status.INFO and "copies one from controls" in live.detail
    assert result.status in (health.Status.OK, health.Status.INFO)


def test_missing_key_file_warns_about_the_built_in_keys(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _exe(emus / "Daphne")
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    node = health.check_daphne_keys(cfg).children[0]
    assert node.status == health.Status.WARN
    assert node.detail.startswith("no dapinput.ini, so Daphne uses its built-in keys; pause, ")
    assert "create it with [KEYBOARD], KEY_PAUSE = 112 296 0" in node.fix


def test_byte_order_mark_fix_says_to_save_without_it(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _write(_exe(emus / "Daphne") / "dapinput.ini", FILLED, raw=b"\xef\xbb\xbf")
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    node = health.check_daphne_keys(cfg).children[0]
    assert node.status == health.Status.WARN
    assert node.detail.startswith("the file starts with a byte-order mark")
    assert "without a byte-order mark" in node.fix


def test_a_line_daphne_cannot_parse_is_named_in_the_fix(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    text = STOCK.replace("KEY_QUIT = 27 0 0", "KEY_QUIT=27 0 0")
    _write(_exe(emus / "Daphne") / "dapinput.ini", text)
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    node = health.check_daphne_keys(cfg).children[0]
    assert node.detail.startswith("Daphne stops reading at line 20 (not '<name> = <key> <key> <button>'")
    assert "fix or remove line 20, then run doctor again" in node.fix
    assert "before END" not in node.fix


def test_a_file_that_stops_early_with_nothing_on_0_is_info(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    text = FILLED.replace("END\r\n", "KEY_BUTTON4 = 1 2 0\r\nEND\r\n")
    _write(_exe(emus / "Daphne") / "dapinput.ini", text)
    _register(rl, "Daphne", "..\\Emulators\\Daphne\\daphne.exe")
    node = health.check_daphne_keys(cfg).children[0]
    assert node.status == health.Status.INFO
    assert "an action Daphne doesn't know: KEY_BUTTON4" in node.detail


def test_doctor_runs_the_check_after_emulator_rom_folders(tmp_path):
    cfg, _rl, _emus = _cabinet(tmp_path)
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert names.index("Daphne keys") == names.index("Emulator ROM folders") + 1
