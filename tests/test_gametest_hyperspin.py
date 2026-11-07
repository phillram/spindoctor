"""``spindoctor test --with-hyperspin``: HyperSpin's startup, intro skip and exit.

A fake HyperSpin (:class:`tests.gametest_helpers.HyperSpinBehaviour`) writes
``log.txt`` as the real one does and reacts to the keys SpinDoctor sends, so
each test checks the PowerShell tester's verdict for one startup.
"""
from __future__ import annotations

import json
from pathlib import Path

from spindoctor import _testrun, gametest, gametest_hyperspin

from tests.gametest_helpers import (  # noqa: F401 - home is a fixture
    WORKER_PID, FakeWindows, GameBehaviour, HyperSpinBehaviour, build_cabinet, home,
)


def _start(tmp_path, hs=None, **overrides):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), hyperspin=hs or HyperSpinBehaviour())
    kw = dict(hyperspin_timeout=60)
    kw.update(overrides)
    settings = gametest.RunSettings(**kw)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    journal = gametest.Journal(run_dir / "journal.json", {})
    return cfg, fake, settings, run_dir, journal


def test_the_intro_is_skipped_and_the_main_menu_loads(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path)
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert res["status"] == "PASS"
    assert res["reason"].startswith("HyperSpin opened and loaded the Main Menu in ")
    assert res["reason"].endswith(" seconds (intro video skipped)")
    assert fake.typed == [[0x20]]
    assert (run_dir / res["screenshot"]).is_file()
    assert "wheel loaded successfully" in (run_dir / "HyperSpin log.txt").read_text(encoding="utf-8")
    entry = journal.data["hyperspin"]
    assert entry["started_by_us"] and entry["pid"] == fake.hs["proc"].pid and entry["started"]


def test_play_intro_sends_no_key(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path, HyperSpinBehaviour(intro_seconds=8))
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal, play_intro=True)
    assert res["status"] == "PASS" and "intro" not in res["reason"]
    assert fake.typed == []


def test_hyperspin_ignoring_the_key_is_noted(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(
        tmp_path, HyperSpinBehaviour(intro_seconds=30, reacts_to_keys=False))
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert res["status"] == "PASS"
    assert res["reason"].endswith("(HyperSpin ignored the key press meant to skip its intro video)")
    assert len(fake.typed) == 5


def test_an_error_dialog_fails_and_hyperspin_is_closed(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path, HyperSpinBehaviour(popup=(2, "Error")))
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert (res["status"], res["reason"]) == ("FAIL", "HyperSpin showed a pop-up: 'Error'")
    assert "HyperSpin.exe" in fake.terminated
    assert journal.data["hyperspin"] == {}


def test_not_loading_in_time_fails(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(
        tmp_path, HyperSpinBehaviour(intro_seconds=999, reacts_to_keys=False), hyperspin_timeout=20)
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert res["reason"].startswith("HyperSpin didn't finish loading the Main Menu within 20 seconds")
    assert res["status"] == "FAIL" and "HyperSpin.exe" in fake.terminated


def test_hyperspin_closing_by_itself_fails(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path, HyperSpinBehaviour(quits_after=2))
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert (res["status"], res["reason"]) == ("FAIL", "HyperSpin closed by itself 2 seconds after opening")


def test_log_errors_warn_unless_ignored(tmp_path):
    hs = HyperSpinBehaviour(intro=False, log_lines=("Error intializing joysticks",))
    cfg, fake, settings, run_dir, journal = _start(tmp_path, hs)
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert res["status"] == "WARN" and res["reason"].endswith("but its log has 1 error line(s)")
    assert res["details"] == ["12:00:00 PM |  Error intializing joysticks"]
    cfg, fake, settings, run_dir, journal = _start(tmp_path / "b", hs, ignore_hyperspin_log=("joystick",))
    assert gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)["status"] == "PASS"


def test_an_open_hyperspin_is_left_alone(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path)
    fake.add_proc("HyperSpin.exe", 100)
    res = gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert res == {"status": "PASS", "reason": "HyperSpin was already open, so its startup was not tested",
                   "details": [], "screenshot": "", "seconds": 0}
    assert "hyperspin" not in journal.data and fake.launches == []


def test_closing_goes_through_the_exit_menu(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path)
    gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    assert gametest_hyperspin.close(cfg, fake, journal.data["hyperspin"]) == "exit menu"
    assert fake.typed[-2:] == [[0x1B], [0x0D]]
    assert fake.hs["proc"].returncode is not None
    assert not any("LEDBlinky" in a[0] for a in fake.launches)


def test_a_stuck_exit_menu_closes_the_window_and_tells_ledblinky(tmp_path):
    cfg, fake, settings, run_dir, journal = _start(tmp_path, HyperSpinBehaviour(intro=False))
    hs_dir = Path(cfg.hyperspin_dir)
    (hs_dir / "LEDBlinky").mkdir()
    (hs_dir / "LEDBlinky" / "LEDBlinky.exe").write_text("exe", encoding="utf-8")
    (hs_dir / "Settings" / "Settings.ini").write_text(
        "[LEDBlinky]\nActive=true\nPath=LEDBlinky\n", encoding="utf-8")
    gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    fake.hyperspin.reacts_to_keys = False
    assert gametest_hyperspin.close(cfg, fake, journal.data["hyperspin"]) == "window"
    assert fake.closed_windows == [fake.hs["hwnd"]]
    assert fake.launches[-1] == [str(hs_dir / "LEDBlinky" / "LEDBlinky.exe"), "2"]


def test_closing_hyperspin_that_is_gone(tmp_path):
    cfg, fake, _settings, _run_dir, _journal = _start(tmp_path)
    assert gametest_hyperspin.close(cfg, fake, {"pid": 99999}) == "gone"


# ─── in a whole run ───────────────────────────────────────────────────────────

def test_a_run_with_hyperspin_opens_judges_and_closes_it(tmp_path, home):
    cfg, fake, settings, _run_dir, _journal = _start(tmp_path)
    fake.behaviours = [GameBehaviour()]
    seen = []
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    summary = gametest.run_plan(cfg, plan, settings, fake, with_hyperspin=True, on_hyperspin=seen.append)
    assert seen and seen[0]["status"] == "PASS"
    assert fake.hs["proc"].returncode is not None  # closed at the end
    info = gametest.read_run(summary.run_dir)
    assert info["hyperspin"]["status"] == "PASS"
    assert summary.counts["PASS"] == 1
    assert gametest.Journal.load(summary.run_dir / "journal.json").data["hyperspin"] == {}


def test_leave_hyperspin_open(tmp_path, home):
    cfg, fake, settings, _run_dir, _journal = _start(tmp_path)
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    gametest.run_plan(cfg, plan, settings, fake, with_hyperspin=True, leave_hyperspin_open=True)
    assert fake.hs["proc"].returncode is None


def test_recover_closes_the_hyperspin_a_killed_run_opened(tmp_path, home):
    cfg, fake, settings, run_dir, journal = _start(tmp_path)
    gametest_hyperspin.start_and_check(cfg, settings, fake, run_dir, journal)
    gametest._save_run(run_dir, {"started": "x", "finished": False})
    _testrun.set_active(run_dir, {"pid": WORKER_PID + 1})
    report = gametest.recover(cfg, fake)
    assert report.closed == ["HyperSpin.exe"]
    assert fake.hs["proc"].returncode is not None
    assert json.loads((run_dir / "journal.json").read_text(encoding="utf-8"))["hyperspin"] == {}
