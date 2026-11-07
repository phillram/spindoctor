"""``spindoctor test``: whole runs, play statistics, the journal and recovery.

The GUI's Stop ends the worker with TerminateProcess, so a run must survive
being killed between any two lines.  The kill test below takes the journal,
the run pointer and the process table at a moment mid-launch, lets the run
die, puts that moment back, and checks that :func:`gametest.recover` finishes
the job: it closes what was left running and puts the statistics back.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import _testrun, gametest
from spindoctor.cli import cli
from spindoctor.config import save_config

from tests.gametest_helpers import (
    WORKER_PID, FakeWindows, GameBehaviour, Recorder, build_cabinet,
)

FAST = dict(game_seconds=5, launch_timeout=20, close_timeout=5, cooldown=1)


def _stats(cfg) -> dict:
    folder = Path(cfg.rocketlauncher_dir) / "Data" / "Statistics"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.ini"))}


def _setup(tmp_path, *behaviours):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), list(behaviours))
    return cfg, fake, gametest.RunSettings(**FAST)


def test_a_run_writes_its_results_and_skipped_games(tmp_path, home):
    cfg, fake, settings = _setup(
        tmp_path, GameBehaviour(), GameBehaviour(black=True),
        GameBehaviour(popup=(4, "Error", "#32770", 300, 200)))
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    rec = Recorder()
    summary = gametest.run_plan(cfg, plan, settings, fake, selection={"all": True}, on_result=rec)
    assert summary.finished and summary.launched == 3
    assert summary.counts == {"PASS": 1, "WARN": 1, "FAIL": 1, "SKIPPED": 1}
    assert [c[:4] for c in rec.calls] == [(1, 3, "Alpha", "PASS"), (2, 3, "Bravo", "WARN"),
                                           (3, 3, "Charlie", "FAIL")]
    run_dir = summary.run_dir
    assert run_dir.parent == Path(cfg.test_results_dir)
    rows = gametest.read_csv(run_dir / "results.csv")
    assert [(r["Game"], r["Status"]) for r in rows] == [
        ("Missing", "SKIPPED"), ("Alpha", "PASS"), ("Bravo", "WARN"), ("Charlie", "FAIL")]
    assert "game file not found" in rows[0]["Reason"]
    assert (run_dir / rows[1]["Screenshot"]).is_file()
    info = gametest.read_run(run_dir)
    assert info["finished"] is True and info["selection"] == {"all": True} and info["seconds"] == 5
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert len(data["results"]) == 4 and data["run"]["finished"] is True
    assert [r["Game"] for r in gametest.read_csv(run_dir / "plan.csv")] == [
        "Alpha", "Bravo", "Charlie", "Missing"]
    assert _testrun.active_run() is None
    assert gametest.list_runs(Path(cfg.test_results_dir))[0][0] == run_dir


def test_play_statistics_are_put_back_after_every_game(tmp_path, home):
    cfg, fake, settings = _setup(tmp_path, GameBehaviour(), GameBehaviour(emulator="mame.exe"))
    before = _stats(cfg)
    seen = []

    def watch(f):
        # While the second game runs, the first one's launch must be gone already.
        if f.current and f.current["game"] == "galaga":
            seen.append(_stats(cfg))

    fake.on_sleep = watch
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha"), gametest.PlannedGame("MAME", "galaga")])
    summary = gametest.run_plan(cfg, plan, settings, fake)
    assert summary.stats_restored
    assert seen and seen[0] == before
    # RocketLauncher wrote NES.ini, MAME.ini (new) and Global Statistics.ini; all undone.
    assert _stats(cfg) == before
    manifest = json.loads((summary.run_dir / "stats-backup" / "manifest.json").read_text(encoding="utf-8"))
    assert {Path(e["original"]).name for e in manifest["files"]} == {"NES.ini", "Global Statistics.ini"}
    assert all(e["backup"].startswith("stats") for e in manifest["files"]) and manifest["created"]


def test_restore_stats_only_rewrites_what_changed(tmp_path):
    cfg = build_cabinet(tmp_path)
    rl = Path(cfg.rocketlauncher_dir)
    manifest = gametest.backup_stats(rl, tmp_path / "bk")
    assert gametest.restore_stats(rl, manifest) == (0, 0)
    (rl / "Data" / "Statistics" / "NES.ini").write_text("changed", encoding="utf-8")
    (rl / "Settings" / "Global Statistics").mkdir(parents=True)
    (rl / "Settings" / "Global Statistics" / "NES.ini").write_text("new", encoding="utf-8")
    assert gametest.restore_stats(rl, manifest) == (1, 1)
    assert not (rl / "Settings" / "Global Statistics" / "NES.ini").exists()


class _Killed(BaseException):
    """Stands in for TerminateProcess: nothing may catch it."""


def test_a_run_killed_mid_launch_is_recovered_and_resumed(tmp_path, home):
    cfg, fake, settings = _setup(tmp_path, GameBehaviour(), GameBehaviour(), GameBehaviour())
    before = _stats(cfg)
    moment = {}

    def kill(f):
        cur = f.current
        if cur and cur["game"] == "Bravo" and f.t - cur["t0"] > 5 and not moment:
            run_dir = Path(_testrun.active_run()["run_dir"])
            moment.update(
                journal=(run_dir / "journal.json").read_bytes(),
                active=_testrun.active_file().read_bytes(),
                procs=dict(f.procs), times=dict(f.start_times), windows=list(f.windows),
                run_dir=run_dir)
            raise _Killed()

    fake.on_sleep = kill
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    with pytest.raises(_Killed):
        gametest.run_plan(cfg, plan, settings, fake)

    # Put back the moment of the kill: no finally ran, the game is still open.
    run_dir = moment["run_dir"]
    (run_dir / "journal.json").write_bytes(moment["journal"])
    _testrun.active_file().write_bytes(moment["active"])
    fake.procs, fake.start_times, fake.windows = moment["procs"], moment["times"], moment["windows"]
    fake.current["rl"].returncode = None
    fake.on_sleep = None
    del fake.procs[WORKER_PID]  # the killed worker
    journal = json.loads(moment["journal"])
    assert journal["stats"]["restored"] is False
    assert journal["current"]["game"] == "Bravo"
    assert [p["name"] for p in journal["current"]["processes"]] == ["RocketLauncher.exe", "nestopia.exe"]

    report = gametest.recover(cfg, fake)
    assert report.run_dir == run_dir
    assert report.closed == ["nestopia.exe"]  # RocketLauncher quit with its emulator
    assert _stats(cfg) == before  # including the stats RocketLauncher wrote as it closed
    assert _testrun.active_run() is None
    assert gametest.read_run(run_dir)["interrupted"] is True
    assert gametest.recover(cfg, fake) is None  # nothing left to do

    # --resume: Alpha is done, Bravo (cut off) and Charlie run now.
    plan = gametest.plan_from_rows(gametest.read_csv(run_dir / "plan.csv"))
    rec = Recorder()
    summary = gametest.run_plan(cfg, plan, settings, fake, run_dir=run_dir, on_result=rec)
    assert summary.finished
    assert [c[:3] for c in rec.calls] == [(2, 3, "Bravo"), (3, 3, "Charlie")]
    games = [r["Game"] for r in gametest.read_csv(run_dir / "results.csv")]
    assert sorted(games) == ["Alpha", "Bravo", "Charlie", "Missing"]
    assert _stats(cfg) == before


def _journal_run(tmp_path, cfg, current, worker=None, restored=True):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    gametest._save_run(run_dir, {"started": "x", "finished": False})
    manifest = gametest.backup_stats(Path(cfg.rocketlauncher_dir), run_dir / "stats-backup")
    gametest.Journal(run_dir / "journal.json", {
        "current": current, "stats": {"manifest": str(manifest), "restored": restored}}).save()
    _testrun.set_active(run_dir, worker or {"pid": 1, "started": 1.0})
    return run_dir


def test_recover_refuses_while_the_run_is_still_going(tmp_path, home):
    cfg, fake, _ = _setup(tmp_path)
    _journal_run(tmp_path, cfg, {}, worker={"pid": WORKER_PID, "started": 1000.0 + WORKER_PID})
    with pytest.raises(_testrun.ActiveRunError, match="already running"):
        gametest.recover(cfg, fake)
    assert _testrun.active_run() is not None


def test_recover_leaves_a_reused_pid_alone(tmp_path, home):
    cfg, fake, _ = _setup(tmp_path)
    other = fake.add_proc("RocketLauncher.exe", 100, started=5000.0)
    _journal_run(tmp_path, cfg, {"launch_at": 9000.0, "processes": [
        {"pid": other, "name": "RocketLauncher.exe", "started": 4000.0}]})
    report = gametest.recover(cfg, fake)
    assert report.closed == [] and other in fake.procs


def test_recover_finds_a_rocketlauncher_started_before_its_pid_was_written(tmp_path, home):
    cfg, fake, _ = _setup(tmp_path)
    old = fake.add_proc("RocketLauncher.exe", 100, started=10.0)
    rl = fake.add_proc("RocketLauncher.exe", WORKER_PID, started=2000.0)
    emu = fake.add_proc("nestopia.exe", rl, started=2003.0)
    _journal_run(tmp_path, cfg, {"launch_at": 2000.0, "processes": []}, restored=False)
    (Path(cfg.rocketlauncher_dir) / "Data" / "Statistics" / "NES.ini").write_text("dirty", encoding="utf-8")
    report = gametest.recover(cfg, fake)
    assert report.closed == ["nestopia.exe", "RocketLauncher.exe"]
    assert old in fake.procs and emu not in fake.procs
    assert report.stats_restored == (1, 0)
    assert "Number_of_Times_Played=1" in _stats(cfg)["NES.ini"]


def test_recover_with_nothing_to_do(home, tmp_path):
    cfg, fake, _ = _setup(tmp_path)
    assert gametest.recover(cfg, fake) is None


def test_ctrl_c_closes_the_game_and_puts_the_stats_back(tmp_path, home):
    cfg, fake, settings = _setup(tmp_path, GameBehaviour())
    before = _stats(cfg)

    def interrupt(f):
        if f.current and f.t - f.current["t0"] > 4:
            f.on_sleep = None
            raise KeyboardInterrupt

    fake.on_sleep = interrupt
    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")])
    with pytest.raises(KeyboardInterrupt):
        gametest.run_plan(cfg, plan, settings, fake)
    assert "nestopia.exe" in fake.terminated
    assert _stats(cfg) == before
    assert _testrun.active_run() is None
    run_dir = gametest.list_runs(Path(cfg.test_results_dir))[0][0]
    assert gametest.read_run(run_dir)["finished"] is False


def test_a_stop_request_ends_the_run_after_the_current_game(tmp_path, home):
    cfg, fake, settings = _setup(tmp_path, GameBehaviour(), GameBehaviour())

    def stop_after_first(number, total, item, result, left):
        (Path(_testrun.active_run()["run_dir"]) / "stop-request").write_text("", encoding="utf-8")

    plan = gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha"), gametest.PlannedGame("NES", "Bravo")])
    summary = gametest.run_plan(cfg, plan, settings, fake, on_result=stop_after_first)
    assert summary.launched == 1 and not summary.finished
    assert len(fake.launches) == 1


# ─── the Custom Wheels guard ──────────────────────────────────────────────────

def test_custom_wheels_are_not_rebuilt_during_a_test_run(tmp_path, home):
    from spindoctor import playtime, recent

    cfg = build_cabinet(tmp_path)
    recent.rebuild(cfg, dry_run=True)  # fine without a run
    _testrun.set_active(tmp_path / "runs" / "x", {"pid": 1})
    with pytest.raises(_testrun.ActiveRunError, match="spindoctor test --recover"):
        recent.rebuild(cfg, dry_run=False)
    with pytest.raises(_testrun.ActiveRunError):
        playtime.build_most_played_wheel(cfg)
    recent.rebuild(cfg, dry_run=True)  # a dry run writes nothing, so it may run


def test_recent_rebuild_command_explains_the_refusal(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    save_config(cfg)
    _testrun.set_active(tmp_path / "runs" / "x", {"pid": 1})
    result = CliRunner().invoke(cli, ["recent", "rebuild", "--apply"])
    assert result.exit_code == 1
    assert "test --recover" in result.output


def test_stat_files_moved_but_scrub_still_finds_them(tmp_path):
    from spindoctor.cli import _collect_stat_files
    from spindoctor.playtime import stat_files

    rl = Path(build_cabinet(tmp_path).rocketlauncher_dir)
    assert sorted(_collect_stat_files(rl)) == sorted(stat_files(rl))
    assert len(stat_files(rl)) == 2


# ─── the command ──────────────────────────────────────────────────────────────

def test_without_apply_the_command_only_lists_the_games(tmp_path, home):
    save_config(build_cabinet(tmp_path))
    result = CliRunner().invoke(cli, ["test", "--system", "NES", "--all"])
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output and "3 of 4 picked games are ready" in result.output
    assert "Missing" in result.output and "game file not found" in result.output
    assert not (tmp_path / "runs").exists()


def test_json_plan(tmp_path, home):
    save_config(build_cabinet(tmp_path))
    result = CliRunner().invoke(cli, ["test", "--genre", "Shooter", "--all", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [(g["System"], g["Game"]) for g in data["games"]] == [
        ("NES", "Alpha"), ("NES", "Missing"), ("MAME", "galaga")]
    assert {s["system"] for s in data["skipped_systems"]} == {"PC Games", "Direct", "Favorites", "Orphan"}


def test_launching_needs_windows(tmp_path, home, monkeypatch):
    save_config(build_cabinet(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    result = CliRunner().invoke(cli, ["test", "--system", "NES", "--apply"])
    assert result.exit_code == 1
    assert "need Windows" in result.output


def test_unknown_wheel_and_missing_setup(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    save_config(cfg)
    result = CliRunner().invoke(cli, ["test", "--system", "Nope"])
    assert result.exit_code == 1 and "No wheel named" in result.output
    cfg.rocketlauncher_dir = ""
    save_config(cfg)
    result = CliRunner().invoke(cli, ["test", "--system", "NES"])
    assert result.exit_code == 1 and "rocketlauncher_dir" in result.output


def test_recover_option_puts_the_stats_back(tmp_path, home, monkeypatch):
    cfg = build_cabinet(tmp_path)
    save_config(cfg)
    monkeypatch.setattr(sys, "platform", "linux")  # no process steps, stats only
    result = CliRunner().invoke(cli, ["test", "--recover"])
    assert result.exit_code == 0 and "No interrupted test run" in result.output
    _journal_run(tmp_path, cfg, {}, restored=False)
    (Path(cfg.rocketlauncher_dir) / "Data" / "Statistics" / "NES.ini").write_text("dirty", encoding="utf-8")
    result = CliRunner().invoke(cli, ["test", "--recover"])
    assert result.exit_code == 0, result.output
    assert "Finished an interrupted test run" in result.output
    assert "Number_of_Times_Played=1" in _stats(cfg)["NES.ini"]
    assert _testrun.active_run() is None


def test_list_runs(tmp_path, home):
    cfg, fake, settings = _setup(tmp_path, GameBehaviour())
    save_config(cfg)
    gametest.run_plan(cfg, gametest.Plan(games=[gametest.PlannedGame("NES", "Alpha")]), settings, fake)
    result = CliRunner().invoke(cli, ["test", "--list-runs"])
    assert result.exit_code == 0, result.output
    assert "finished" in result.output and "1 pass" in result.output


def test_config_set_bounds_and_lists(tmp_path, home):
    save_config(build_cabinet(tmp_path))
    result = CliRunner().invoke(cli, ["config", "set", "test_game_seconds", "0"])
    assert result.exit_code == 1 and "Out of range" in result.output
    result = CliRunner().invoke(cli, ["config", "set", "test_skip_systems", "Toolkit, KODI"])
    assert result.exit_code == 0, result.output
    assert config_mod.load_config().test_skip_systems == ["Toolkit", "KODI"]
