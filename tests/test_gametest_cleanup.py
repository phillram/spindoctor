"""``spindoctor test``: files the games create (``test_cleanup`` / ``--cleanup``).

The rule that matters most: nothing that existed when the run started is
ever touched.  The fake games write save files and configs when they close,
the fake watcher reports them, and each test checks what the cleanup did.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from spindoctor import _testrun, gametest, gametest_cleanup
from spindoctor.cli import cli
from spindoctor.config import save_config

from tests.gametest_helpers import FakeWindows, GameBehaviour, build_cabinet, home  # noqa: F401

SAVE = "emu/saves/Alpha.srm"
BEZEL = "rl/Settings/NES/Alpha/Bezel.ini"
FAST = dict(game_seconds=5, launch_timeout=20, close_timeout=5, cooldown=0)


def _run(tmp_path, *behaviours, mode=None, games=("Alpha",), **cfg_changes):
    cfg = build_cabinet(tmp_path)
    for k, v in cfg_changes.items():
        setattr(cfg, k, v)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), list(behaviours))
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", g) for g in games])
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(**FAST), fake, cleanup=mode)
    return cfg, fake, summary


def _rows(summary):
    return gametest.read_csv(summary.run_dir / "cleanup.csv")


def test_report_mode_lists_new_files_and_leaves_them(tmp_path, home):
    cfg, fake, summary = _run(tmp_path, GameBehaviour(creates=(SAVE, BEZEL)))
    rows = _rows(summary)
    assert sorted((r["Action"], Path(r["Path"]).name) for r in rows) == [
        ("found", "Alpha.srm"), ("found", "Bezel.ini"), ("found folder", "Alpha")]
    assert all(r["After"] == "NES > Alpha" for r in rows)
    assert (tmp_path / SAVE).exists() and (tmp_path / BEZEL).exists()
    assert gametest.read_csv(summary.run_dir / "results.csv")[0]["Cleaned"] == "3"
    clean = gametest.read_run(summary.run_dir)["cleanup"]
    assert (clean["mode"], clean["found"], clean["removed"], clean["left"]) == ("report", 3, 0, 0)
    assert clean["baseline"] > 0 and (summary.run_dir / "baseline.bin").is_file()
    assert all(w.closed for w in fake.watchers) and len(fake.watchers) == 3  # hs, rl, emu
    assert (tmp_path / "emu" / "saves" / "Old Game.srm").read_text(encoding="utf-8") == "an old save"


def test_remove_mode_backs_up_then_deletes(tmp_path, home):
    backups = tmp_path / "backups"
    cfg, fake, summary = _run(tmp_path, GameBehaviour(creates=(SAVE, BEZEL)), mode="remove",
                              backup_dir=str(backups))
    assert not (tmp_path / SAVE).exists() and not (tmp_path / BEZEL).parent.exists()
    base = backups / "test-cleanup" / summary.run_dir.name
    assert (base / "emu" / "saves" / "Alpha.srm").read_text(encoding="utf-8") == "data"
    assert (base / "rl" / "Settings" / "NES" / "Alpha" / "Bezel.ini").is_file()
    actions = sorted(r["Action"] for r in _rows(summary))
    assert actions == ["removed", "removed", "removed empty new folder"]
    clean = gametest.read_run(summary.run_dir)["cleanup"]
    assert (clean["removed"], clean["backup_dir"]) == (3, str(base))
    # The old save and the rest of the cabinet are untouched.
    assert (tmp_path / "emu" / "saves" / "Old Game.srm").exists()
    assert (tmp_path / "rl" / "Settings" / "NES" / "Emulators.ini").exists()


def test_without_backup_dir_the_backup_goes_to_the_run_folder(tmp_path, home):
    _cfg, _fake, summary = _run(tmp_path, GameBehaviour(creates=(SAVE,)), mode="remove")
    assert (summary.run_dir / "cleanup-backup" / "emu" / "saves" / "Alpha.srm").is_file()


def test_a_file_that_existed_is_never_touched(tmp_path, home):
    old = "emu/saves/Old Game.srm"
    _cfg, fake, summary = _run(tmp_path, GameBehaviour(creates=(old,)), mode="remove")
    assert (tmp_path / old).read_text(encoding="utf-8") == "data"  # the game's own change stays
    assert _rows(summary) == []


def test_a_file_made_again_after_removal_is_removed_again(tmp_path, home):
    _cfg, _fake, summary = _run(tmp_path, GameBehaviour(creates=(SAVE,)), GameBehaviour(creates=(SAVE,)),
                                mode="remove", games=("Alpha", "Bravo"))
    rows = _rows(summary)
    assert [(r["After"], r["Action"]) for r in rows] == [("NES > Alpha", "removed"), ("NES > Bravo", "removed")]


def test_skip_folders_and_running_programs_are_left_alone(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    cfg.test_cleanup_skip = [str(tmp_path / "emu" / "saves")]
    fake = FakeWindows(Path(cfg.rocketlauncher_dir),
                       [GameBehaviour(creates=(SAVE, "emu/tools/ds4/profile.xml", BEZEL))])
    tool = fake.add_proc("DS4Windows.exe", 100)
    fake.image_paths[tool] = str(tmp_path / "emu" / "tools" / "ds4" / "DS4Windows.exe")
    (tmp_path / "emu" / "tools" / "ds4").mkdir(parents=True)
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(**FAST), fake)
    names = sorted(Path(r["Path"]).name for r in _rows(summary))
    assert names == ["Alpha", "Bezel.ini"]
    skipped = gametest.read_run(summary.run_dir)["cleanup"]["skipped"]
    assert str(tmp_path / "emu" / "tools" / "ds4") in skipped
    assert str(tmp_path / "rl" / "Data" / "Statistics") in skipped


def test_the_7z_extract_folder_is_skipped(tmp_path):
    cfg = build_cabinet(tmp_path)
    ini = Path(cfg.rocketlauncher_dir) / "Settings" / "Global RocketLauncher.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + "[7z]\n7z_Extract_Path=..\\hs\\cache\n", encoding="utf-8")
    roots = gametest_cleanup.watched_roots(cfg)
    assert os.path.normpath(str(tmp_path / "hs" / "cache")) in gametest_cleanup.skip_folders(cfg, roots, [])


def test_an_overflow_makes_the_next_cleanup_list_everything(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), [GameBehaviour()])

    def unseen_write(f):
        if f.current and f.t - f.current["t0"] > 4 and not (tmp_path / SAVE).exists():
            (tmp_path / SAVE).write_text("quiet", encoding="utf-8")  # no watcher event
            for w in f.watchers:
                w.overflowed = True

    fake.on_sleep = unseen_write
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(**FAST), fake)
    assert [r["After"] for r in _rows(summary)] == ["NES > Alpha"]
    assert gametest.read_run(summary.run_dir)["cleanup"]["overflows"] >= 1


def test_a_missed_file_is_caught_at_the_end(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), [GameBehaviour()])
    fake.on_sleep = lambda f: (tmp_path / SAVE).write_text("quiet", encoding="utf-8") if f.current else None
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(**FAST), fake)
    assert [r["After"] for r in _rows(summary)] == ["end of run"]


def test_without_a_watcher_every_cleanup_lists_the_folders(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), [GameBehaviour(creates=(SAVE,))])

    def no_watcher(root):
        raise OSError("no ReadDirectoryChangesW here")

    fake.watch_folder = no_watcher
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(**FAST), fake)
    assert [r["After"] for r in _rows(summary)] == ["NES > Alpha"]


def test_off_mode_does_nothing(tmp_path, home):
    _cfg, fake, summary = _run(tmp_path, GameBehaviour(creates=(SAVE,)), mode="off")
    assert not (summary.run_dir / "baseline.bin").exists() and not (summary.run_dir / "cleanup.csv").exists()
    assert "cleanup" not in gametest.read_run(summary.run_dir) and fake.watchers == []


def test_recovery_sweeps_with_the_saved_baseline(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    gametest._save_run(run_dir, {"started": "x", "finished": False})
    roots = gametest_cleanup.watched_roots(cfg)
    since = time.time()
    gametest_cleanup.Cleanup(cfg, run_dir, "remove", roots, [], since).start()
    gametest.Journal(run_dir / "journal.json", {"current": {}, "cleanup": {
        "mode": "remove", "roots": roots, "skip": [], "since": since}}).save()
    _testrun.set_active(run_dir, {"pid": 1})
    (tmp_path / "emu" / "saves" / "Alpha.srm").write_text("made before the kill", encoding="utf-8")
    report = gametest.recover(cfg, None)
    assert "Checked for files the games created: 1 removed." in report.messages
    assert not (tmp_path / SAVE).exists()
    assert gametest.read_run(run_dir)["cleanup"]["removed"] == 1
    assert json.loads((run_dir / "journal.json").read_text(encoding="utf-8"))["cleanup"] == {}


def test_baseline_round_trip_and_unreadable_folders(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.txt").write_text("x", encoding="utf-8")
    base = gametest_cleanup.Baseline.take([str(tmp_path / "a")], [])
    assert base.count == 2 and base.existed(str(tmp_path / "a" / "b" / "c.txt"))
    base.unreadable.append(str(tmp_path / "a" / "locked"))
    base.save(tmp_path)
    again = gametest_cleanup.Baseline.load(tmp_path)
    assert again.hashes == base.hashes
    assert again.existed(str(tmp_path / "a" / "locked" / "anything.sav"))
    assert not again.existed(str(tmp_path / "a" / "new.sav"))


def test_watched_roots_leave_out_folders_inside_another(tmp_path):
    cfg = build_cabinet(tmp_path)
    assert len(gametest_cleanup.watched_roots(cfg)) == 3
    cfg.rocketlauncher_dir = str(tmp_path / "hs" / "RocketLauncher")
    Path(cfg.rocketlauncher_dir).mkdir()
    assert [Path(r).name for r in gametest_cleanup.watched_roots(cfg)] == ["hs", "emu"]


def test_path_hash_is_stable():
    assert gametest_cleanup.path_hash("D:/Arcade/x") == gametest_cleanup.path_hash("D:/Arcade/x")
    assert gametest_cleanup.path_hash("D:/Arcade/x") != gametest_cleanup.path_hash("D:/Arcade/y")


def test_config_and_option_values(tmp_path, home):
    save_config(build_cabinet(tmp_path))
    result = CliRunner().invoke(cli, ["config", "set", "test_cleanup", "delete"])
    assert result.exit_code == 1 and "expected one of: report, remove, off" in result.output
    assert CliRunner().invoke(cli, ["config", "set", "test_cleanup", "Remove"]).exit_code == 0
    result = CliRunner().invoke(cli, ["test", "--system", "NES", "--cleanup", "bogus"])
    assert result.exit_code == 2


@pytest.mark.skipif(sys.platform != "win32", reason="ReadDirectoryChangesW")
def test_the_real_watcher_sees_new_files(tmp_path):
    from spindoctor import _win32

    w = _win32.DirectoryWatcher(str(tmp_path))
    try:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "new.sav").write_text("x", encoding="utf-8")
        found = set()
        for _ in range(40):
            added, _over = w.drain()
            found |= added
            if str(tmp_path / "sub" / "new.sav") in found:
                break
            time.sleep(0.05)
        assert {str(tmp_path / "sub"), str(tmp_path / "sub" / "new.sav")} <= found
    finally:
        t = time.time()
        w.close()
        assert time.time() - t < 6
