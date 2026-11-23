"""``generate-media record``: launching, recording, judging, stopping, resuming.

Driven by the launch tester's fake Windows and a fake ffmpeg, so no program
is started and no screen is recorded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import _testrun, clips, gamecapture, gametest, genmedia, media_scan
from spindoctor.cli import cli
from spindoctor.config import save_config

from tests.gametest_helpers import FakeWindows, GameBehaviour, build_cabinet

MOVING = dict(seconds=35.0, width=1280, height=720, crop=(960, 720, 160, 0))


class Desktop(FakeWindows):
    """The tester's fake Windows, with a picture that moves and an input watcher."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.used = ""
        self.closed = False
        self.idle = 60.0
        self.monitors = 1
        self.display: list[bool] = []
        self.shots = 0
        self.still_until = 0.0      # seconds after a launch before the picture moves

    def capture(self, thumb_width):
        shot = super().capture(thumb_width)
        self.shots += 1
        if self.current and self.t - self.current["t0"] >= self.still_until:
            shot.thumb = bytes([self.shots * 40 % 256]) * len(shot.thumb)
        return shot

    def idle_seconds(self):
        return self.idle

    def monitor_count(self):
        return self.monitors

    def keep_display_on(self, on):
        self.display.append(on)

    def watch_inputs(self):
        return self

    def close(self):
        self.closed = True


class FakeTake:
    error = ""

    def __init__(self, fake, out: Path, seconds: float):
        self.fake, self.out, self.ends = fake, out, fake.t + seconds
        self.started = fake.t
        self.first_frame = fake.t + 0.4
        self.killed = False
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"take")

    def running(self):
        return not self.killed and self.fake.t < self.ends

    def kill(self):
        self.killed = True

    def finish(self, timeout=20):
        return True


class FakeTools:
    """clips.Tools without ffmpeg.  *analyses*: one per take, in order."""

    def __init__(self, fake, *analyses, methods=("ddagrab", "gdigrab"), probes=None):
        self.fake = fake
        self.analyses = list(analyses)
        self._methods = list(methods)
        self.probes = probes or {}
        self.takes: list = []
        self.clips: list = []
        self.sound = (-30.0, -8.0)

    def methods(self):
        return list(self._methods)

    def probe(self, method, region=None):
        return self.probes.get(method, clips.Analysis(seconds=1.5))

    def start_take(self, method, out, seconds, region=None):
        self.takes.append((method, seconds, region))
        self.take = FakeTake(self.fake, out, seconds)
        return self.take

    def analyse(self, take):
        assert take.read_bytes() == b"take"
        return self.analyses.pop(0) if self.analyses else clips.Analysis(**MOVING)

    def volume(self, sound, skip, seconds):
        return self.sound

    def make_clip(self, take, out, **kwargs):
        self.clips.append(kwargs)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"video")
        return out

    def make_still(self, take, out, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"still")
        return out


class FakeSound:
    made: list = []

    def __init__(self, path: Path):
        self.path, self.error, self.started_at = path, "", None
        self.format, self.rate, self.channels = "f32le", 48000, 2
        self.stopped = False
        FakeSound.made.append(self)

    def start(self):
        self.started_at = FakeSound.clock.t
        return True

    def stop(self):
        self.stopped = True


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", folder)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", folder / "config.json")
    monkeypatch.setattr(genmedia, "CONFIG_DIR", folder)
    monkeypatch.setattr(media_scan, "MANIFEST_DIR", folder / "media_imports")
    monkeypatch.setattr(FakeSound, "made", [])
    return folder


def _setup(tmp_path, *behaviours, analyses=(), **tool_args):
    cfg = build_cabinet(tmp_path)
    cfg.output_dir = str(tmp_path / "out")
    fake = Desktop(Path(cfg.rocketlauncher_dir), list(behaviours))
    FakeSound.clock = fake
    return cfg, fake, FakeTools(fake, *analyses, **tool_args)


def _plan(cfg, system="NES", **kwargs):
    return gamecapture.plan_capture(cfg, [genmedia.wheel_state(cfg, system)], **kwargs)


def _record(cfg, fake, tools, plan=None, stage=None, run_dir=None, sound=FakeSound, **capture):
    plan = plan or _plan(cfg)
    stage = stage or genmedia.Stage.create(genmedia.stage_root(cfg), "recordings")
    settings = gamecapture.CaptureSettings(**{"wait": 5, "settle": 10, "seconds": 20, **capture})
    results: list = []
    done = gamecapture.record(
        cfg, plan, settings, stage, fake, tools, run_dir=run_dir, sound_factory=sound, cleanup="off",
        on_result=lambda n, total, item, result, left: results.append((item.game, result.status, result.reason)))
    return done, stage, results


# ─── picking ─────────────────────────────────────────────────────────────────

def test_only_games_missing_a_video_are_planned(tmp_path, home):
    cfg, _fake, _tools = _setup(tmp_path)
    video = cfg.media_dir / "NES" / "Video"
    video.mkdir(parents=True)
    (video / "Alpha.mp4").write_bytes(b"real")
    (video / "Bravo.png").write_bytes(b"still")
    plan = _plan(cfg)
    assert [(g.game, bool(g.reason)) for g in plan.plan.games] == [
        ("Charlie", False), ("Missing", True), ("Bravo", False)]   # a still only: last
    assert plan.games == 2
    assert [g.game for g in _plan(cfg, video=False).plan.games] == ["Charlie", "Missing"]
    assert [g.game for g in _plan(cfg, count=1).plan.games] == ["Charlie"]
    assert [g.game for g in _plan(cfg, patterns=["b*"]).plan.games] == ["Bravo"]


def test_wheels_rocketlauncher_cant_launch_are_named(tmp_path, home):
    cfg, _fake, _tools = _setup(tmp_path)
    for wheel, why in (("Direct", "itself"), ("Orphan", "no settings")):
        plan = _plan(cfg, wheel)
        assert plan.games == 0 and why in plan.problems[0][1]


def test_hidden_games_are_left_out_unless_asked(tmp_path, home):
    cfg, _fake, _tools = _setup(tmp_path)
    ini = Path(cfg.hyperspin_dir) / "Settings" / "NES.ini"
    ini.write_text("[filters]\nwheels_only=true\n", encoding="utf-8")
    plan = _plan(cfg)
    assert plan.games == 0 and plan.left_hidden == 4
    assert _plan(cfg, show_hidden=True).games == 3


def test_a_clone_that_plays_its_parents_video_is_recorded_only_by_name(tmp_path, home):
    cfg, _fake, _tools = _setup(tmp_path)
    state = genmedia.wheel_state(cfg, "NES")
    for g in state.games:
        g.video = "parent"
    assert gamecapture.plan_capture(cfg, [state]).games == 0
    assert gamecapture.plan_capture(cfg, [state], patterns=["alpha"]).games == 1


def test_estimates_know_the_time_limit():
    # 20 s wait + half the 40 s settle + 35 s recording + 18 s launch, close and the pause after; 90 s for the run
    c = gamecapture.CaptureSettings(wait=20, seconds=35, minutes=30)
    assert c.per_game() == 93 and c.estimate(10) == 930 + 90
    assert c.estimate(1000) == 30 * 60 + 93 + 90
    assert gamecapture.CaptureSettings(minutes=0).estimate(1000) == 93000 + 90
    assert gamecapture.CaptureSettings(video=False, wait=5).per_game() == 5 + 4 + 18
    # As measured on a cabinet's 84 handhelds: 57 s each
    assert gamecapture.CaptureSettings(wait=3, settle=3).per_game() == 57
    assert c.estimate(0) == 0


def test_play_keys_are_parsed():
    assert gamecapture.parse_play(["Up Down,Left", "Right A", "A"]) == ["Up", "Down", "Left", "Right", "A"]
    assert gamecapture.parse_play([]) == []
    with pytest.raises(gamecapture.CaptureError):
        gamecapture.parse_play(["Up NoSuchKey"])


def test_key_presses_are_parsed():
    assert gamecapture.parse_presses(["15:F1", "2.5:Enter"]) == [(2.5, "Enter"), (15.0, "F1")]
    for bad in ("Enter", "5:", "x:Enter", "-1:Enter", "5:NoSuchKey"):
        with pytest.raises(gamecapture.CaptureError):
            gamecapture.parse_presses([bad])


def test_movement():
    grey = bytes([100] * 4000)
    assert not gamecapture.picture_changed(grey, grey)
    assert not gamecapture.picture_changed(grey, bytes([104] * 4000))      # noise
    assert gamecapture.picture_changed(grey, bytes([100] * 3600 + [200] * 400))


# ─── recording ───────────────────────────────────────────────────────────────

def test_a_run_records_clips_with_sound_and_puts_the_statistics_back(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    stats = Path(cfg.rocketlauncher_dir) / "Data" / "Statistics"
    before = {p.name: p.read_text(encoding="utf-8") for p in stats.iterdir()}
    done, stage, results = _record(cfg, fake, tools)
    assert [(g, s) for g, s, _r in results] == [("Alpha", "PASS"), ("Bravo", "PASS"), ("Charlie", "PASS")]
    assert results[0][2] == "Recorded 35 s, with sound"
    assert [i.file for i in stage.items] == [f"Media/NES/Video/{n}.mp4" for n in ("Alpha", "Bravo", "Charlie")]
    assert all(i.kind == "recorded" for i in stage.items)
    assert done.run.finished and not done.halted
    assert {p.name: p.read_text(encoding="utf-8") for p in stats.iterdir()} == before
    assert _testrun.active_run() is None and not (done.run.run_dir / "takes").exists()
    # Black bars cropped, sound brought to the usual loudness and lined up.
    clip = tools.clips[0]
    assert clip["crop"] == (960, 720, 160, 0) and clip["size"] == (640, 480) and clip["gain"] == 7.0
    assert clip["sound"].sample_format == "f32le" and clip["sound_skip"] == pytest.approx(0.4)
    assert all(s.stopped for s in FakeSound.made) and len(FakeSound.made) == 3
    assert fake.display == [True, False] and fake.closed
    # Nothing is in HyperSpin yet, and what is put in is real media.
    assert not cfg.media_dir.exists()
    genmedia.put_in(cfg, stage, genmedia.plan_put_in(cfg, stage))
    assert genmedia.wheel_state(cfg, "NES").count(video="yes") == 3


def test_recording_runs_dont_mix_with_test_runs(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    done, _stage, _results = _record(cfg, fake, tools, _plan(cfg, count=1))
    root = _testrun.tests_dir(cfg)
    assert gametest.list_runs(root) == []
    assert [d for d, _i in gametest.list_runs(root, kind=gamecapture.KIND)] == [done.run.run_dir]


@pytest.mark.parametrize("analysis, status, reason, files", [
    (dict(MOVING, black=34.0), "FAIL", "Nothing saved: the picture was black", []),
    (dict(MOVING, frozen=34.0), "WARN", "Still only: the picture didn't move", ["Media/NES/Video/Alpha.png"]),
    (dict(MOVING, seconds=0.0), "FAIL", "Nothing saved: nothing was recorded", []),
    (dict(problem="ffmpeg fell over"), "FAIL", "Nothing saved: ffmpeg fell over", []),
])
def test_bad_takes_never_become_the_video(tmp_path, home, analysis, status, reason, files):
    cfg, fake, tools = _setup(tmp_path, analyses=[clips.Analysis(**analysis)])
    _done, stage, results = _record(cfg, fake, tools, _plan(cfg, count=1))
    assert results == [("Alpha", status, reason)] and [i.file for i in stage.items] == files
    assert tools.clips == []


def test_what_ffmpeg_said_is_passed_on(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    real = tools.start_take

    def fails_at_once(method, out, seconds, region=None):
        take = real(method, out, 0, region)
        out.unlink()
        take.error = "Failed to capture image (error 5)"
        return take

    tools.start_take = fails_at_once
    _done, stage, results = _record(cfg, fake, tools, _plan(cfg, count=1))
    assert results[0][1:] == ("FAIL", "Nothing saved: ffmpeg (ddagrab): Failed to capture image (error 5)")
    assert stage.items == []


def test_another_window_in_front_spoils_the_take(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)

    def popup(f):
        if tools.takes and f.current and f.current["emu"] in f.procs:
            f.fg = 100  # the desktop is in front

    fake.on_sleep = popup
    _done, stage, results = _record(cfg, fake, tools, _plan(cfg, count=1))
    assert results[0][1:] == ("FAIL", "Nothing saved: another window came in front of the game")
    assert stage.items == []


def test_a_game_that_stays_behind_another_window_isnt_recorded(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    fake.bring_to_front = lambda hwnd: None

    def behind(f):
        f.fg = 100

    fake.on_sleep = behind
    _done, _stage, results = _record(cfg, fake, tools, _plan(cfg, count=1))
    assert results[0][1] == "FAIL" and "Another window stayed in front" in results[0][2]
    assert tools.takes == []


def test_a_game_that_quits_or_crashes_saves_nothing(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path, GameBehaviour(quits_after=15), GameBehaviour(crash_after=15),
                              GameBehaviour(popup=(15, "Error", "#32770", 300, 200)))
    _done, stage, results = _record(cfg, fake, tools)
    assert [s for _g, s, _r in results] == ["FAIL", "FAIL", "FAIL"] and stage.items == []
    assert "closed by itself while it was being recorded" in results[0][2]
    assert "crashed" in results[1][2] and "Pop-up" in results[2][2]
    assert fake.current["rl"].returncode == 0 and "nestopia.exe" not in {p.name for p in fake.list_processes()}


def test_a_loading_screen_is_waited_out(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    fake.still_until = 14.0     # opens after 3 s, runs its 5 s wait, then stands still
    started = []
    real = tools.start_take
    tools.start_take = lambda *a, **k: (started.append(fake.t - fake.current["t0"]), real(*a, **k))[1]
    _record(cfg, fake, tools, _plan(cfg, count=1))
    assert 14 <= started[0] <= 17
    # But not for ever.
    cfg, fake, tools = _setup(tmp_path / "two")
    fake.still_until = 10_000.0
    real2 = tools.start_take
    tools.start_take = lambda *a, **k: (started.append(fake.t - fake.current["t0"]), real2(*a, **k))[1]
    _record(cfg, fake, tools, _plan(cfg, count=1))
    assert started[1] <= 3 + 5 + 10 + 3


def test_the_way_of_recording_that_sees_the_game_is_used(tmp_path, home):
    frozen, black = clips.Analysis(seconds=1.5, frozen=1.5), clips.Analysis(seconds=1.5, black=1.5)
    for probes, monitors, want in (
            ({}, 1, "ddagrab"),
            ({"ddagrab": frozen}, 1, "gdigrab"),
            ({"ddagrab": black, "gdigrab": frozen}, 1, "gdigrab"),
            ({"ddagrab": frozen, "gdigrab": frozen}, 1, "ddagrab"),    # a title screen that stands still
            ({"ddagrab": clips.Analysis(problem="x"), "gdigrab": black}, 1, "gdigrab"),
            ({}, 2, "gdigrab")):                                       # it would record the wrong monitor
        cfg, fake, tools = _setup(tmp_path / f"{want}{monitors}{len(probes)}{id(probes)}", probes=probes)
        fake.monitors = monitors
        _record(cfg, fake, tools, _plan(cfg, count=1))
        assert tools.takes[0][0] == want, probes


def test_a_window_is_recorded_without_the_rest_of_the_screen(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path, GameBehaviour(window=(100, 50, 800, 600)),
                              GameBehaviour(window=(-8, -8, 1936, 1096)))
    _record(cfg, fake, tools, _plan(cfg, count=2))
    assert tools.takes[0][2] == (100, 50, 800, 600) and tools.takes[1][2] is None


def test_screenshots_only(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path, analyses=[clips.Analysis(**dict(MOVING, seconds=4.0, frozen=4.0))])
    _done, stage, results = _record(cfg, fake, tools, _plan(cfg, count=1, video=False), video=False)
    assert results == [("Alpha", "PASS", "Screenshot taken")]
    assert [(i.media, i.file) for i in stage.items] == [("still", "Media/NES/Video/Alpha.png")]
    assert FakeSound.made == [] and tools.takes[0][1] == gamecapture.STILL_SECONDS


class NoSound(FakeSound):
    def start(self):
        self.error = "no sound device"
        return False


def test_without_sound_the_clip_is_silent(tmp_path, home):
    for factory, sound, note in ((NoSound, (-30.0, -8.0), "no sound: no sound device"),
                                 (FakeSound, (-120.0, -120.0), "no sound was heard"),
                                 (None, (-30.0, -8.0), "no sound")):
        cfg, fake, tools = _setup(tmp_path / note.replace(":", ""))
        tools.sound = sound
        _done, _stage, results = _record(cfg, fake, tools, _plan(cfg, count=1), sound=factory)
        assert results == [("Alpha", "PASS", f"Recorded 35 s, {note}")]
        assert tools.clips[0]["sound"] is None


def test_keys_are_pressed_for_the_game_and_only_while_it_is_in_front(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path, GameBehaviour(exit_key_works=False))
    presses = gamecapture.parse_presses(["1:5", "20:1"])
    _record(cfg, fake, tools, _plan(cfg, count=1), presses=presses)
    assert fake.pressed[:2] == [[ord("5")], [ord("1")]]


def test_keys_are_pressed_for_every_game_of_a_run(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path, GameBehaviour(exit_key_works=False))
    presses = gamecapture.parse_presses(["1:5"])
    _record(cfg, fake, tools, _plan(cfg), presses=presses)
    assert len(fake.launches) >= 2
    assert sum(1 for p in fake.pressed if p == [ord("5")]) == len(fake.launches)


def test_play_keys_are_pressed_at_random_after_the_set_ones(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path, GameBehaviour(exit_key_works=False))
    play = gamecapture.parse_play(["Up Down A"])
    _record(cfg, fake, tools, _plan(cfg, count=1), presses=gamecapture.parse_presses(["1:Enter"]), play=play)
    keys = [p[0] for p in fake.pressed if len(p) == 1]
    first = keys.index(0x0D)
    played = [k for k in keys[first + 1:] if k in (0x26, 0x28, ord("A"))]
    assert first == 0 and len(played) >= 5 and len(set(played)) >= 2


# ─── stopping and resuming ───────────────────────────────────────────────────

def test_someone_at_the_keyboard_stops_the_run_and_the_game(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)

    def touch(f):
        if len(f.launches) == 2 and tools.takes[1:]:
            f.used = "keyboard"

    fake.on_sleep = touch
    done, stage, results = _record(cfg, fake, tools)
    assert [g for g, _s, _r in results] == ["Alpha"] and len(fake.launches) == 2
    assert done.halted == "someone used the keyboard" and not done.run.finished
    assert tools.take.killed and "nestopia.exe" not in {p.name for p in fake.list_processes()}
    assert len(stage.items) == 1 and (stage.folder / "review.html").exists()
    assert done.run.stats_restored and _testrun.active_run() is None


def test_the_time_limit_ends_a_run_between_games(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    done, _stage, results = _record(cfg, fake, tools, minutes=1)
    assert len(results) == 2 and done.halted == "the 1 minutes are up"
    assert not done.run.finished and len(fake.launches) == 2


def test_a_stopped_run_is_carried_on_where_it_was(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)
    done, stage, _results = _record(cfg, fake, tools, minutes=1)
    run_dir, info = gamecapture.unfinished_run(cfg)
    assert run_dir == done.run.run_dir and Path(info["stage"]) == stage.folder
    settings = gamecapture.resumed_settings(info)
    assert (settings.seconds, settings.minutes) == (20, 1)
    plan = gamecapture.resumed_plan(cfg, run_dir, [genmedia.wheel_state(cfg, "NES")])
    again = genmedia.Stage.load(Path(info["stage"]))
    done, _s, results = _record(cfg, fake, tools, plan, again, run_dir)
    assert [g for g, _st, _r in results] == ["Charlie"] and done.run.finished
    assert len(genmedia.Stage.load(stage.folder).items) == 3
    assert gamecapture.unfinished_run(cfg) is None


def test_the_stop_button_stops_it(tmp_path, home):
    cfg, fake, tools = _setup(tmp_path)

    def stop(f):
        run = _testrun.active_run()
        if run and tools.takes:
            (Path(run["run_dir"]) / "stop-request").write_text("", encoding="utf-8")

    fake.on_sleep = stop
    done, _stage, results = _record(cfg, fake, tools)
    assert results == [] and done.halted == "a stop was asked for" and tools.take.killed


def test_it_wont_start_while_something_is_open(tmp_path, home):
    cfg, fake, _tools = _setup(tmp_path)
    gamecapture.check_ready(cfg, fake)
    pid = fake.add_proc("HyperSpin.exe", 100)
    with pytest.raises(gamecapture.CaptureError, match="HyperSpin is open"):
        gamecapture.check_ready(cfg, fake)
    fake.remove(pid)
    fake.add_proc("RocketLauncher.exe", 100)
    with pytest.raises(gamecapture.CaptureError, match="already running"):
        gamecapture.check_ready(cfg, fake)


def test_it_waits_for_a_quiet_pc(tmp_path, home):
    _cfg, fake, _tools = _setup(tmp_path)
    said = []
    gamecapture.wait_until_idle(fake, said.append)
    assert said == []
    fake.idle = 0.0
    quiet_at = fake.t + 30

    def settle(f):
        f.idle = max(0.0, f.t - quiet_at)

    fake.on_sleep = settle
    gamecapture.wait_until_idle(fake, said.append)
    assert len(said) == 1 and fake.t >= quiet_at + gamecapture.IDLE_SECONDS
    fake.on_sleep = None
    fake.idle = 1.0
    with pytest.raises(gamecapture.CaptureError, match="Someone is using the PC"):
        gamecapture.wait_until_idle(fake)


# ─── the command ─────────────────────────────────────────────────────────────

def _cli(*args, input=None):
    return CliRunner().invoke(cli, ["generate-media", "record", *args], input=input)


def test_the_dry_run_lists_and_launches_nothing(tmp_path, home):
    cfg, _fake, _tools = _setup(tmp_path)
    save_config(cfg)
    out = _cli("-s", "NES", "--minutes", "1").output
    assert "3 game(s) to record, 1 can't be launched" in out and "takes over the screen" in out
    assert "It stops after 1 minutes" in out and "DRY RUN" in out
    assert not genmedia.stage_root(cfg).exists()
    for args, why in ((("--resume",), "no unfinished recording"),
                      ((), "Name the wheel"),
                      (("-s", "NES", "--play", "Up NoSuchKey"), "is not a key"),
                      (("-s", "NES", "--press", "Enter"), "not a key press"),
                      (("-s", "Nowhere"), "No wheel named")):
        assert why in _cli(*args).output, args


@pytest.mark.skipif(sys.platform == "win32", reason="what happens off Windows")
def test_recording_needs_windows(tmp_path, home):
    cfg, _fake, _tools = _setup(tmp_path)
    save_config(cfg)
    result = _cli("-s", "NES", "--apply", "--yes")
    assert result.exit_code == 1 and "needs Windows" in result.output


@pytest.fixture
def desktop(tmp_path, home, monkeypatch):
    """The whole command on the fake Windows."""
    from spindoctor import _loopback

    cfg, fake, tools = _setup(tmp_path)
    save_config(cfg)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(gametest, "WindowsPlatform", lambda: fake)
    monkeypatch.setattr(clips, "find_tools", lambda config: tools)
    monkeypatch.setattr(_loopback, "LoopbackRecorder", FakeSound)
    return cfg, fake


def test_the_whole_command(desktop):
    cfg, fake = desktop
    assert "Nothing was started" in _cli("-s", "NES", "--count", "2", "--apply", input="n\n").output
    assert fake.launches == []
    result = _cli("-s", "NES", "--count", "2", "--wait", "5", "--seconds", "20", "--apply", "--yes")
    assert result.exit_code == 0, result.output
    assert "2 recorded, 0 still only, 0 with nothing saved." in result.output
    assert "2 file(s) made" in result.output and len(fake.launches) == 2


def test_the_command_can_put_the_batch_in_when_done(desktop):
    cfg, _fake = desktop
    result = _cli("-s", "NES", "--count", "2", "--wait", "5", "--seconds", "20", "--put-in", "--apply", "--yes")
    assert result.exit_code == 0, result.output
    assert "2 file(s) made" in result.output and "2 file(s) put in" in result.output
    assert len([p for p in (cfg.media_dir / "NES" / "Video").iterdir() if p.suffix == ".mp4"]) == 2
    assert genmedia.find_stage(genmedia.stage_root(cfg), genmedia.list_stages(genmedia.stage_root(cfg))[0].name).put_in_at
    assert "2 file(s) undone" in CliRunner().invoke(cli, ["generate-media", "undo", "--apply"]).output


def test_the_command_refuses_when_hyperspin_is_open_or_ffmpeg_missing(desktop, monkeypatch):
    _cfg, fake = desktop
    fake.add_proc("HyperSpin.exe", 100)
    result = _cli("-s", "NES", "--apply", "--yes")
    assert result.exit_code == 1 and "HyperSpin is open" in result.output and fake.launches == []

    def missing(config):
        raise clips.ClipError("ffmpeg not found.")

    monkeypatch.setattr(clips, "find_tools", missing)
    result = _cli("-s", "NES", "--apply", "--yes")
    assert result.exit_code == 1 and "ffmpeg not found" in result.output


def test_resume_from_the_command_line(desktop):
    _cfg, fake = desktop
    out = _cli("-s", "NES", "--wait", "5", "--seconds", "20", "--minutes", "1", "--apply", "--yes").output
    assert "Stopped early: the 1 minutes are up" in out
    out = _cli("--resume", "--apply", "--yes").output
    assert "1 game(s) left" in out and "file(s) made" in out and len(fake.launches) == 3
    assert "no unfinished recording" in _cli("--resume").output


def test_resuming_presses_nothing_it_wasnt_told_to():
    settings = gamecapture.resumed_settings({"capture": {"presses": [[12.0, "Enter"]], "unknown": 1,
                                                         "play": ["Up", "A"], "settle": 3}})
    assert settings.presses == [(12.0, "Enter")] and settings.seconds == 35 and settings.play == ["Up", "A"]
    assert settings.settle == 3
    assert gamecapture.resumed_settings({"capture": "broken"}) == gamecapture.CaptureSettings()
