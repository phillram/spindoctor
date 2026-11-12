"""``spindoctor test``: judging one launch, with a fake Windows.

Each test scripts what RocketLauncher and the emulator do over time
(:class:`tests.gametest_helpers.GameBehaviour`) and checks the verdict the
PowerShell tester would give, word for word.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from spindoctor import gametest
from spindoctor._win32 import ProcInfo, WinInfo
from spindoctor.rl_rom_paths import _RomLookup

from tests.gametest_helpers import FakeWindows, GameBehaviour, build_cabinet

ALPHA = gametest.PlannedGame("NES", "Alpha", "Alpha (USA)", emulator="Nestopia")
LOG_ERROR = "13:05:01:123 | RL |    ERROR   | +0     | Cannot find Rom\n"


def _runner(tmp_path, *behaviours, stop=None, **overrides):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), list(behaviours))
    kw = dict(game_seconds=5, launch_timeout=20, close_timeout=5)
    kw.update(overrides)
    settings = gametest.RunSettings(**kw)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    journal = gametest.Journal(run_dir / "journal.json", {"current": {}})
    runner = gametest.Runner(cfg, settings, fake, run_dir, journal,
                             stop_requested=stop or (lambda: False))
    return runner, fake, run_dir


def test_a_game_that_runs_passes_and_is_closed_with_the_exit_key(tmp_path):
    runner, fake, run_dir = _runner(tmp_path, GameBehaviour(log="12:00:00:000 | RL | INFO | +0 | ok\n"))
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == ("PASS", "Opened and ran normally")
    assert fake.launches == [[str(runner.rl_exe), "NES", "Alpha"]]
    assert fake.pressed == [[0x1B]]
    assert result.capture == "fake"
    assert (run_dir / result.screenshot).is_file()
    assert result.screenshot.startswith("screenshots/NES/Alpha.")
    assert (run_dir / result.log).read_text(encoding="utf-8").startswith("12:00:00:000")
    assert 5 <= result.seconds <= 12
    # The journal named RocketLauncher and the emulator while they ran.
    names = [p["name"] for p in runner.journal.data["current"]["processes"]]
    assert names == ["RocketLauncher.exe", "nestopia.exe"]


def test_nothing_opening_is_a_did_not_start_failure(tmp_path):
    runner, fake, _ = _runner(tmp_path, GameBehaviour(window_after=None, emulator=""))
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == (
        "FAIL", "Game didn't start: nothing opened within 20 seconds")


def test_an_emulator_without_a_window_is_a_warning(tmp_path):
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(window_after=None))
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == (
        "WARN", "The emulator is running but no game window was seen")


def test_rocketlauncher_quitting_early_quotes_its_log(tmp_path):
    runner, _fake, _ = _runner(
        tmp_path, GameBehaviour(window_after=None, emulator="", quits_after=2, log=LOG_ERROR))
    result = runner.launch(ALPHA)
    assert result.status == "FAIL"
    assert result.reason.startswith("Game didn't start: RocketLauncher closed after ")
    assert result.reason.endswith(" seconds. RocketLauncher said: Cannot find Rom")
    assert "Log: Cannot find Rom" in result.details


def test_a_game_that_closes_by_itself_fails(tmp_path):
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(window_after=2, quits_after=6))
    result = runner.launch(ALPHA)
    assert result.status == "FAIL"
    assert result.reason == "Game closed by itself 4 seconds after it opened"


def test_an_error_dialog_fails_the_game(tmp_path):
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(popup=(4, "Error", "#32770", 400, 200)))
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == ("FAIL", "Pop-up window appeared: 'Error'")


def test_an_error_word_in_a_small_window_title_fails_the_game(tmp_path):
    runner, _fake, _ = _runner(
        tmp_path, GameBehaviour(popup=(4, "BIOS not found", "Emu", 500, 300)))
    assert runner.launch(ALPHA).reason == "Pop-up window appeared: 'BIOS not found'"


def test_the_games_own_name_is_not_an_error_word(tmp_path):
    item = gametest.PlannedGame("NES", "Crash Bandicoot (USA)", "Crash Bandicoot (USA)")
    runner, _fake, _ = _runner(
        tmp_path, GameBehaviour(popup=(4, "Crash Bandicoot", "Emu", 800, 600)))
    assert runner.launch(item).status == "PASS"


def test_a_windows_crash_report_for_the_emulator_fails_and_is_closed(tmp_path):
    runner, fake, _ = _runner(tmp_path, GameBehaviour(crash_after=4))
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == (
        "FAIL", "The emulator crashed (Windows crash report appeared)")
    assert "WerFault.exe" in fake.terminated


def test_a_hung_window_fails(tmp_path):
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(hung=True))
    assert runner.launch(ALPHA).reason == "nestopia stopped responding"


def test_a_black_screen_is_a_warning(tmp_path):
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(black=True))
    result = runner.launch(ALPHA)
    assert result.status == "WARN"
    assert result.reason.startswith("Screen looked black")


def test_log_errors_warn_unless_ignored(tmp_path):
    line = "13:05:01:123 | MD |    ERROR   | +0     | Module has no CRC defined\n"
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(log=line), ignore_log_errors=())
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == (
        "WARN", "RocketLauncher logged an error: Module has no CRC defined")
    # The default ignore list ("No CRC defined") matches without regard to case.
    runner, _fake, _ = _runner(tmp_path / "b", GameBehaviour(log=line))
    assert runner.launch(ALPHA).status == "PASS"


def test_a_game_that_ignores_the_exit_key_is_forced_closed(tmp_path):
    runner, fake, _ = _runner(tmp_path, GameBehaviour(exit_key_works=False))
    result = runner.launch(ALPHA)
    assert (result.status, result.reason) == (
        "WARN", "The exit key didn't close it; SpinDoctor had to force-close the emulator")
    assert fake.terminated == ["nestopia.exe"]


def test_unpacking_with_7z_extends_the_launch_timeout(tmp_path):
    runner, _fake, _ = _runner(tmp_path, GameBehaviour(unzip_for=25))
    assert runner.launch(ALPHA).status == "PASS"


def test_helper_windows_are_not_the_game(tmp_path):
    runner, _fake, _ = _runner(
        tmp_path, GameBehaviour(window_after=None, emulator="", helper_window=True))
    assert runner.launch(ALPHA).reason.startswith("Game didn't start")


def test_a_game_another_launcher_started_counts_and_is_closed(tmp_path):
    runner, fake, _ = _runner(
        tmp_path, GameBehaviour(window_after=None, emulator="steam.exe", other_program_after=4))
    result = runner.launch(ALPHA)
    assert result.status == "PASS"
    assert "game.exe" in fake.terminated


def test_the_exit_key_is_never_sent_to_hyperspin(tmp_path):
    runner, fake, _ = _runner(tmp_path, GameBehaviour(exit_key_works=False))
    hs = fake.add_proc("HyperSpin.exe", 100)

    def hyperspin_in_front(f):
        f.fg = hs

    fake.on_sleep = hyperspin_in_front
    fake.bring_to_front = lambda hwnd: None
    result = runner.launch(ALPHA)
    assert fake.pressed == []
    assert result.reason == "The game window was not in front"
    assert any("force-close" in d for d in result.details)


def test_a_stop_request_closes_the_game_and_gives_no_result(tmp_path):
    holder = {}
    runner, fake, _ = _runner(tmp_path, GameBehaviour(),
                              stop=lambda: holder["f"].t - holder["t0"] > 4)
    holder["f"], holder["t0"] = fake, fake.t
    assert runner.launch(ALPHA) is None
    assert fake.current["rl"].returncode is not None
    assert fake.pressed == [[0x1B]]


# ─── LaunchWatch on its own ───────────────────────────────────────────────────

def test_processes_named_in_the_log_are_owned(tmp_path):
    settings = gametest.RunSettings()
    watch = gametest.LaunchWatch(10, {1: "explorer.exe"}, settings, (1920, 1080), [], lambda pid: None)
    procs = [ProcInfo(1, 0, "explorer.exe"), ProcInfo(10, 1, "RocketLauncher.exe"),
             ProcInfo(20, 999, "teknoparrot.exe"), ProcInfo(21, 10, "AutoHotkey.exe")]
    obs = watch.update(procs, [WinInfo(5, 20, "Game", "X", 0, 0, 1920, 1080)], [20])
    assert watch.owned == {20: "teknoparrot.exe"}
    assert [w.pid for w in obs.game_windows] == [20]
    assert obs.alive_game == {20: "teknoparrot.exe"}


# ─── exit keys, logs, screenshots ─────────────────────────────────────────────

@pytest.mark.parametrize("name, vk", [
    ("Esc", 0x1B), ("~Esc", 0x1B), ("F12", 0x7B), ("Numpad5", 0x65), ("q", 0x51),
    ("1", 0x31), ("LAlt", 0xA4), ("Joy1", -1), ("", -1),
])
def test_virtual_key(name, vk):
    assert gametest.virtual_key(name) == vk


@pytest.mark.parametrize("raw, wait, vks, hold", [
    ("Esc", "0", [0x1B], 150),
    ("H500:Esc", "0", [0x1B], 650),
    ("~1 & ~2", "100", [0x31, 0x32], 250),
    ("2Joy7|F4", "0", [0x73], 150),
    ("Joy1", "0", [0x1B], 150),
])
def test_exit_key_from_rocketlauncher_settings(tmp_path, raw, wait, vks, hold):
    cfg = build_cabinet(tmp_path)
    rl = Path(cfg.rocketlauncher_dir)
    (rl / "Settings" / "Global RocketLauncher.ini").write_text(
        f"[Exit]\nExit_Emulator_Key={raw}\nExit_Emulator_Key_Wait={wait}\n", encoding="utf-8")
    key = gametest.exit_key(_RomLookup(rl), "NES")
    assert (key.vks, key.hold_ms) == (vks, hold)


def test_a_systems_own_exit_key_wins_unless_use_global(tmp_path):
    cfg = build_cabinet(tmp_path)
    rl = Path(cfg.rocketlauncher_dir)
    ini = rl / "Settings" / "NES" / "RocketLauncher.ini"
    ini.write_text("[Exit]\nExit_Emulator_Key=F10\n", encoding="utf-8")
    assert gametest.exit_key(_RomLookup(rl), "NES").vks == [0x79]
    ini.write_text("[Exit]\nExit_Emulator_Key=use_global\n", encoding="utf-8")
    assert gametest.exit_key(_RomLookup(rl), "NES").vks == [0x1B]


def test_log_errors_and_pids():
    text = ("12:00:00:000 | RL |    INFO    | +0     | Process ID: 4321\n"
            "12:00:01:000 | RL |    ERROR   | +0     | No CRC defined for this module\n"
            "12:00:02:000 | MD |    ERROR   | +5     | Could not find the window\n"
            "12:00:02:500 | MD |    ERROR   | +5     | Could not find the window\n")
    assert gametest.log_pids(text) == [4321]
    assert gametest.log_errors(text) == ["No CRC defined for this module", "Could not find the window"]
    assert gametest.log_errors(text, ("no crc",)) == ["Could not find the window"]


def test_read_log_ignores_an_old_log(tmp_path):
    log = tmp_path / "RocketLauncher.log"
    log.write_text("old", encoding="utf-8")
    mtime = log.stat().st_mtime
    assert gametest.read_log(log, since=mtime + 60) == ""
    assert gametest.read_log(log, since=mtime) == "old"
    assert gametest.read_log(tmp_path / "none.log") == ""


def _frame(width, height, pixel=b"\x00\x00\x00\x00"):
    return bytearray(pixel * (width * height))


def test_looks_black_checks_the_middle_of_the_game_window():
    w, h = 200, 100
    px = _frame(w, h)
    assert gametest.looks_black(bytes(px), w, h)
    # A bright bezel round a black game is still black.
    for y in range(h):
        for x in list(range(0, 20)) + list(range(180, 200)):
            px[(y * w + x) * 4:(y * w + x) * 4 + 4] = b"\xff\xff\xff\x00"
    assert gametest.looks_black(bytes(px), w, h)
    i = (50 * w + 99) * 4  # a sampled pixel: x = 60 + 3k, y = 20 + 3k
    px[i:i + 4] = b"\x40\x40\x40\x00"
    assert not gametest.looks_black(bytes(px), w, h)
    # Only the game window's middle counts.
    assert gametest.looks_black(bytes(px), w, h, region=(0, 0, 100, 50))


def test_encode_png_is_a_valid_png():
    w, h = 3, 2
    bgra = bytes([10, 20, 30, 0] * (w * h))
    data = gametest.encode_png(w, h, bgra)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (w, h)
    idat = data.index(b"IDAT")
    length = struct.unpack(">I", data[idat - 4:idat])[0]
    raw = zlib.decompress(data[idat + 4:idat + 4 + length])
    assert raw == (b"\x00" + bytes([30, 20, 10]) * w) * h


def test_encode_image_falls_back_to_png_without_pillow(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    data, ext = gametest.encode_image(2, 2, bytes(16))
    assert ext == "png" and data.startswith(b"\x89PNG")


def test_safe_names_are_short_and_windows_safe():
    assert gametest._safe_name('Who: "Me"?') == "Who Me"
    long = gametest._safe_name("A" * 200)
    assert len(long) == 89 and "~" in long


def test_helper_list_from_config(tmp_path):
    cfg = build_cabinet(tmp_path)
    cfg.test_helper_processes = ["MyTool.exe", "!steam.exe"]
    s = gametest.settings_from_config(cfg, seconds=45)
    assert "mytool.exe" in s.helpers and "steam.exe" not in s.helpers
    assert s.game_seconds == 45
    assert gametest.settings_from_config(cfg).game_seconds == 20
