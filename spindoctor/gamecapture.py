"""Record games for ``generate-media record``: a clip, its sound and a still.

Each game is launched by the launch tester (:mod:`spindoctor.gametest`), so
everything that makes a test run safe holds here too: RocketLauncher's play
statistics are put back after every game, only programs the run started are
closed, the run can be stopped, resumed, and recovered after a crash.

Once a game has run its wait without trouble, the recorder waits until the
picture moves (a loading screen usually doesn't), records the screen with
ffmpeg and the sound with :mod:`spindoctor._loopback`, and lets the tester
close the game.  It presses nothing: most games show their own demo.  Keys can
be given for a single game, whose timing the caller knows.

A take is only used when it is a moving picture of the game: a black or frozen
one, or one with another window in front, never becomes its video.  A frozen
but not black one still makes a still.

The run ends between games when its time is up, and at once when someone uses
the keyboard, a control panel or a mouse button.
"""
from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import _testrun, clips, gametest
from .config import Config
from .genmedia import GameState, Stage, WheelState, matching
from .rl_rom_paths import _raw_game_names, _RomLookup

KIND = "capture"                # gametest run kind, in run.json
OVERHEAD_SECONDS = 20           # per game, on top of the wait and the recording
IDLE_SECONDS = 15               # nobody may have touched the PC for this long
IDLE_LIMIT = 300
STILL_SECONDS = 4               # how much is recorded when only a still is wanted

SAVED, STILL_ONLY, NOTHING = "Recorded", "Still only", "Nothing saved"


class CaptureError(RuntimeError):
    """Recording can't start."""


@dataclass
class CaptureSettings:
    wait: int = 20              # seconds a game runs before recording may start
    settle: int = 40            # how much longer to wait for a moving picture
    seconds: int = 35
    minutes: int = 30           # the run starts no new game after this; 0 = no limit
    video: bool = True          # False: a still only
    sound: bool = True
    crop: str = "auto"
    presses: list = field(default_factory=list)     # (seconds after the window opened, key text)

    def per_game(self) -> int:
        return self.wait + (self.seconds if self.video else STILL_SECONDS) + OVERHEAD_SECONDS

    def estimate(self, games: int) -> int:
        """About how long *games* take, in seconds, time limit included."""
        total = games * self.per_game()
        return min(total, self.minutes * 60 + self.per_game()) if self.minutes else total


def parse_presses(texts) -> list[tuple[float, str]]:
    """``12:Enter`` -> ``(12.0, "Enter")``; :class:`CaptureError` for anything else."""
    out = []
    for text in texts:
        at, _colon, key = text.partition(":")
        try:
            seconds = float(at)
        except ValueError:
            seconds = -1.0
        if seconds < 0 or gametest.virtual_key(key) < 0:
            raise CaptureError(f"{text!r} is not a key press: use SECONDS:KEY, like 12:Enter or 15:F1.")
        out.append((seconds, key.strip()))
    return sorted(out)


# ─── picking games ────────────────────────────────────────────────────────────

@dataclass
class CapturePlan:
    plan: gametest.Plan
    states: dict[tuple[str, str], GameState]    # (system, game) -> what it has
    left_hidden: int = 0
    problems: list[tuple[str, str]] = field(default_factory=list)   # (wheel, why nothing is recorded)

    @property
    def games(self) -> int:
        return len(self.plan.to_launch)


def wants(game: GameState, video: bool) -> bool:
    """Whether recording would fill a gap of *game*."""
    if video:
        return game.video in ("no", "placeholder", "still")
    return game.video in ("no", "placeholder")


def plan_capture(config: Config, states: list[WheelState], *, patterns=(), count: Optional[int] = None,
                 video: bool = True, show_hidden: bool = False) -> CapturePlan:
    """The games to record: those with no video (a still doesn't count as
    one), or with neither when only stills are wanted, games with nothing
    first.  *patterns* names games, which may then also be clones that play
    their parent's video; *count* takes the first that can be launched."""
    look = _RomLookup(Path(config.rocketlauncher_dir))
    out = CapturePlan(gametest.Plan(), {})
    ready = 0
    named = any(p.strip() for p in patterns)
    for state in states:
        why = state.problem or state.video_problem
        if not why and gametest._hyperspin_launches_itself(config, state.system):
            why = "HyperSpin starts these games itself, not through RocketLauncher"
        if not why and look.source(state.system) is None:
            why = "RocketLauncher has no settings for this wheel"
        if why:
            out.problems.append((state.system, why))
            continue
        picked = []
        for game in matching(state.games, patterns):
            if not (wants(game, video) or (named and game.video == "parent")):
                continue
            if game.hidden and not show_hidden:
                out.left_hidden += 1
                continue
            picked.append(game)
        picked.sort(key=lambda g: g.video == "still")  # nothing at all first
        raw = _raw_game_names(state.system, config.databases_dir)
        overrides = look.game_overrides(state.system)
        for game in picked:
            if count is not None and ready >= count:
                break
            emu, problem, fix = gametest.check_game(look, state.system, game.name.strip(), raw, overrides)
            ready += not problem
            out.plan.games.append(gametest.PlannedGame(state.system, game.name, game.title, "", emu,
                                                       problem, fix))
            out.states[(state.system, game.name)] = game
    return out


# ─── one game ─────────────────────────────────────────────────────────────────

@dataclass
class _Take:
    video: Path
    sound: Optional[clips.SoundFile] = None
    sound_skip: float = 0.0
    sound_note: str = ""
    method: str = ""
    front: str = ""         # a window that got in front of the game
    error: str = ""         # what ffmpeg said when it recorded nothing


def picture_changed(before: bytes, after: bytes, share: float = 0.01) -> bool:
    """Whether enough of two thumbnails differs to call it movement."""
    if len(before) != len(after):
        return True
    step = max(4, len(after) // 4 // 4000 * 4)
    looked = changed = 0
    for i in range(0, len(after) - 2, step):
        looked += 1
        if (abs(before[i] - after[i]) + abs(before[i + 1] - after[i + 1])
                + abs(before[i + 2] - after[i + 2])) > 36:
            changed += 1
    return looked > 0 and changed >= max(1, looked * share)


class CaptureRunner(gametest.Runner):
    """Launches a game like the tester, records it, and stages what it got."""

    def __init__(self, config: Config, settings: gametest.RunSettings, platform, run_dir: Path, journal,
                 stop_requested: Callable[[], bool] = lambda: False, *, capture: CaptureSettings,
                 stage: Stage, states: dict, tools, sound_factory=None, inputs=None):
        super().__init__(config, settings, platform, run_dir, journal, stop_requested=self._stop_now)
        self.capture = capture
        self.stage = stage
        self.states = states
        self.tools = tools
        self.inputs = inputs
        self.halted = ""            # why the run was stopped early
        self._asked = stop_requested
        self._sound_factory = sound_factory
        self._began = platform.now()
        self._take: Optional[_Take] = None
        self._pending: list = []

    # -- stopping

    def _stop_now(self) -> bool:
        if self._asked():
            self.halted = self.halted or "a stop was asked for"
        elif self.inputs is not None and self.inputs.used:
            self._halt(f"someone used the {self.inputs.used}")
        return bool(self.halted)

    def _halt(self, why: str) -> None:
        """Stop the run after the game it is at, the way a stop request does."""
        if not self.halted:
            self.halted = why
            try:
                (self.run_dir / "stop-request").write_text(why, encoding="utf-8")
            except OSError:
                pass

    # -- the launch

    def launch(self, item: gametest.PlannedGame) -> Optional[gametest.LaunchResult]:
        limit = self.capture.minutes * 60
        if limit and self.platform.now() - self._began >= limit:
            self._halt(f"the {self.capture.minutes} minutes are up")
        if self._stop_now():
            return None
        self._take = None
        self._pending = list(self.capture.presses)
        try:
            result = super().launch(item)
            return None if result is None else self._finish(item, result)
        finally:
            shutil.rmtree(self.run_dir / "takes", ignore_errors=True)

    def on_poll(self, proc, state, opened_at) -> None:
        """Press the keys that are due, only while the game is in front."""
        if opened_at is None:
            return
        while self._pending and self.platform.now() - opened_at >= self._pending[0][0]:
            _at, key = self._pending.pop(0)
            if self._game_in_front(proc, state):
                self.platform.press_keys([gametest.virtual_key(key)], 80)

    def _game_in_front(self, proc, state) -> bool:
        fg = self.platform.foreground_pid()
        return fg == proc.pid or fg in state.alive_game

    def _poll(self, proc, watch, state, fails, opened_at) -> tuple:
        """Wait a second and look again: ``(state, "", "ended" or "stopped")``."""
        p = self.platform
        p.sleep(1)
        if proc.poll() is not None:
            return state, "ended"
        if self.stop_requested():
            return state, "stopped"
        state = watch.update(p.list_processes(), p.list_windows())
        if state.error_windows:
            fails.append(f"Pop-up window appeared: '{state.error_windows[0].title}'")
            return state, "ended"
        if state.crash:
            fails.append("The emulator crashed (Windows crash report appeared)")
            return state, "ended"
        self.on_poll(proc, state, opened_at)
        return state, ""

    def while_running(self, item, proc, watch, state, fails, warns):
        p, c = self.platform, self.capture
        opened_at = p.now() - self.settings.game_seconds
        if not self._game_in_front(proc, state):
            p.bring_to_front(state.game_windows[0].hwnd)
            p.sleep(0.7)
            if not self._game_in_front(proc, state):
                warns.append("Another window stayed in front of the game, so it wasn't recorded")
                return state, False
        # A loading screen: wait for a picture that isn't black and moves.
        deadline = p.now() + c.settle
        before = None
        while c.video:
            shot = p.capture(160)
            black = shot is None or gametest.looks_black(shot.pixels, shot.width, shot.height)
            if not black and before is not None and picture_changed(before, shot.thumb):
                break
            before = None if black else shot.thumb
            if p.now() >= deadline:
                break
            state, end = self._poll(proc, watch, state, fails, opened_at)
            if end:
                return self._ended(state, end, fails)
        region = self._region(state)
        method = self._method(region)
        folder = self.run_dir / "takes"
        seconds = c.seconds if c.video else STILL_SECONDS
        take = _Take(folder / "take.mkv", method=method)
        sound = self._start_sound(take, folder / "sound.raw")
        try:
            recording = self.tools.start_take(method, take.video, seconds, region)
        except clips.ClipError as exc:
            if sound is not None:
                sound.stop()
            fails.append(str(exc))
            return state, False
        end, behind = "", 0
        deadline = p.now() + seconds + 30
        try:
            while recording.running() and not end:
                state, end = self._poll(proc, watch, state, fails, opened_at)
                behind = 0 if self._game_in_front(proc, state) or p.foreground_pid() == 0 else behind + 1
                if behind >= 2 and not end:
                    take.front = "another window came in front of the game"
                if p.now() >= deadline:
                    break
        finally:
            if end or recording.running():
                recording.kill()
            recording.finish()
            if sound is not None:
                sound.stop()
        if end:
            return self._ended(state, end, fails)
        if not take.video.is_file() or not take.video.stat().st_size:
            take.error = f"ffmpeg ({method}): {recording.error}" if recording.error else "nothing was recorded"
        if sound is not None and not sound.error and sound.started_at and take.video.is_file():
            take.sound = clips.SoundFile(sound.path, sound.format, sound.rate, sound.channels)
            first = recording.first_frame or recording.started
            take.sound_skip = max(0.0, first - sound.started_at)
        elif sound is not None and sound.error:
            take.sound_note = f"no sound: {sound.error}"
        self._take = take
        return state, False

    def _ended(self, state, end, fails):
        if end == "stopped":
            return state, True
        if not fails:
            fails.append("Game closed by itself while it was being recorded")
        return state, False

    def _region(self, state) -> Optional[tuple[int, int, int, int]]:
        """The part of the screen the game's window covers; None for all of it."""
        if not state.game_windows:
            return None
        sw, sh = self.platform.screen_size()
        w = max(state.game_windows, key=lambda win: win.width * win.height)
        left, top = max(0, w.left), max(0, w.top)
        width, height = min(w.left + w.width, sw) - left, min(w.top + w.height, sh) - top
        if width < 160 or height < 120 or (width >= sw * 0.95 and height >= sh * 0.95):
            return None
        return left, top, width, height

    def _method(self, region) -> str:
        """The way of recording that sees this game.  Desktop Duplication sees
        full-screen games a GDI copy shows frozen; it records one monitor."""
        methods = self.tools.methods()
        if self.platform.monitor_count() != 1 and len(methods) > 1:
            methods = [m for m in methods if m != "ddagrab"]
        usable = ""
        for method in methods:
            a = self.tools.probe(method, region)
            if a.problem or a.is_black:
                continue
            if not a.is_frozen:
                return method
            usable = usable or method
        return usable or methods[-1]

    def _start_sound(self, take: _Take, path: Path):
        if not (self.capture.video and self.capture.sound and self._sound_factory):
            return None
        sound = self._sound_factory(path)
        if not sound.start():
            take.sound_note = f"no sound: {sound.error}"
            return None
        return sound

    # -- what came of it

    def _finish(self, item: gametest.PlannedGame, result: gametest.LaunchResult) -> gametest.LaunchResult:
        take, why = self._take, ""
        if result.status == gametest.FAIL:
            why = result.reason
        elif take is None:
            why = result.reason if result.status == gametest.WARN else "nothing was recorded"
        elif take.error or take.front:
            why = take.error or take.front
        if why:
            return self._judged(result, gametest.FAIL, f"{NOTHING}: {why}")
        a = self.tools.analyse(take.video)
        if a.problem or a.seconds < 1 or a.is_black:
            return self._judged(result, gametest.FAIL, f"{NOTHING}: {a.verdict}")
        game = self.states.get((item.system, item.game))
        title = game.title if game else item.description or item.game
        stem = game.stem if game else item.game
        crop = clips.choose_crop(self.capture.crop, a)
        size = clips.fit_size(*(crop[:2] if crop else (a.width, a.height)))
        try:
            if self.capture.video and not a.is_frozen:
                return self._judged(result, gametest.PASS, self._save_clip(item, title, stem, take, a, crop, size))
            why = a.verdict if self.capture.video else ""
            entry = self.stage.new_item(item.system, item.game, title, "still", "recorded", stem, ".png", why)
            self.tools.make_still(take.video, self.stage.target(entry), crop=crop, size=size)
            self.stage.add(entry)
            self.stage.save()
        except (clips.ClipError, OSError) as exc:
            return self._judged(result, gametest.FAIL, f"{NOTHING}: {exc}")
        if not why:
            return self._judged(result, gametest.PASS, "Screenshot taken")
        if game is not None and game.video == "still":
            return self._judged(result, gametest.WARN, f"{STILL_ONLY} (it has one already): {why}")
        return self._judged(result, gametest.WARN, f"{STILL_ONLY}: {why}")

    def _save_clip(self, item, title, stem, take: _Take, a, crop, size) -> str:
        mean = peak = None
        if take.sound is not None:
            mean, peak = self.tools.volume(take.sound, take.sound_skip, a.seconds)
        heard = mean is not None and mean > clips.SILENT_DB
        note = "with sound" if heard else (take.sound_note or ("no sound was heard" if take.sound else "no sound"))
        entry = self.stage.new_item(item.system, item.game, title, "video", "recorded", stem, ".mp4", note)
        self.tools.make_clip(take.video, self.stage.target(entry), crop=crop, size=size,
                             sound=take.sound if heard else None, sound_skip=take.sound_skip,
                             gain=clips.gain_db(mean, peak) if heard else 0.0, seconds=self.capture.seconds)
        self.stage.add(entry)
        self.stage.save()
        return f"{SAVED} {int(round(a.seconds))} s, {note}"

    @staticmethod
    def _judged(result, status, reason):
        result.details = [reason] + [d for d in result.details if d != reason]
        result.status, result.reason = status, reason
        return result


# ─── a whole run ──────────────────────────────────────────────────────────────

def check_ready(config: Config, platform) -> None:
    """:class:`CaptureError` when something is open that a run would disturb."""
    names = {p.name.lower() for p in platform.list_processes()}
    if "hyperspin.exe" in names:
        raise CaptureError("HyperSpin is open. Exit HyperSpin first: recording takes over the screen.")
    if gametest.rocketlauncher_running(platform):
        raise CaptureError("RocketLauncher is already running (a game is open). Close it first.")
    exe = Path(config.rocketlauncher_dir) / "RocketLauncher.exe"
    if not exe.is_file():
        raise CaptureError(f"RocketLauncher.exe not found: {exe}")


def wait_until_idle(platform, say: Callable[[str], None] = lambda _text: None,
                    seconds: int = IDLE_SECONDS, limit: int = IDLE_LIMIT) -> None:
    """Return once nobody has used the keyboard or mouse for *seconds*;
    :class:`CaptureError` when that doesn't happen within *limit*."""
    end = platform.now() + limit
    said = False
    while platform.idle_seconds() < seconds:
        if platform.now() >= end:
            raise CaptureError(f"Someone is using the PC (no {seconds} quiet seconds in "
                               f"{limit // 60} minutes). Nothing was started.")
        if not said:
            said = True
            say(f"Starting once nobody has touched the keyboard or mouse for {seconds} seconds.")
        platform.sleep(1)


@dataclass
class CaptureSummary:
    run: gametest.RunSummary
    halted: str = ""


def record(
    config: Config,
    plan: CapturePlan,
    capture: CaptureSettings,
    stage: Stage,
    platform,
    tools,
    *,
    run_dir: Optional[Path] = None,
    sound_factory=None,
    on_result=None,
    cleanup: Optional[str] = None,
) -> CaptureSummary:
    """Record every game of *plan* into *stage*.  The caller has run
    :func:`gametest.recover`, :func:`check_ready` and :func:`wait_until_idle`."""
    settings = gametest.settings_from_config(config, capture.wait)
    inputs = platform.watch_inputs()
    runners: list[CaptureRunner] = []

    def make(*args, **kwargs):
        runner = CaptureRunner(*args, capture=capture, stage=stage, states=plan.states, tools=tools,
                               sound_factory=sound_factory, inputs=inputs, **kwargs)
        runners.append(runner)
        return runner

    platform.keep_display_on(True)
    try:
        summary = gametest.run_plan(
            config, plan.plan, settings, platform, run_dir=run_dir, on_result=on_result, cleanup=cleanup,
            runner_class=make, kind=KIND,
            run_info={"stage": str(stage.folder), "capture": asdict(capture)})
    finally:
        platform.keep_display_on(False)
        inputs.close()
        stage.finish()
    return CaptureSummary(summary, runners[0].halted if runners else "")


def unfinished_run(config: Config) -> Optional[tuple[Path, dict]]:
    """The newest recording run that didn't finish and still has its stage."""
    for folder, info in gametest.list_runs(_testrun.tests_dir(config), kind=KIND):
        if not info.get("finished") and info.get("stage") and Path(info["stage"]).is_dir():
            return folder, info
    return None


def resumed_settings(info: dict) -> CaptureSettings:
    """The settings a run was started with (``run.json``)."""
    saved = info.get("capture") if isinstance(info.get("capture"), dict) else {}
    known = {k: v for k, v in saved.items() if k in CaptureSettings.__dataclass_fields__}
    known["presses"] = [tuple(p) for p in known.get("presses") or []]
    return CaptureSettings(**known)


def resumed_plan(config: Config, run_dir: Path, states: list[WheelState]) -> CapturePlan:
    """The games of a run that didn't finish; ``run_plan`` skips the done ones."""
    plan = gametest.plan_from_rows(gametest.read_csv(run_dir / "plan.csv"))
    games = {(s.system, g.name): g for s in states for g in s.games}
    return CapturePlan(plan, {(g.system, g.game): games[(g.system, g.game)] for g in plan.games
                              if (g.system, g.game) in games})
