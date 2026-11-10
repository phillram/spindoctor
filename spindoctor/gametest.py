"""Launch-test games through RocketLauncher, the way HyperSpin starts them.

``spindoctor test`` picks games from the HyperSpin wheels, checks each one's
files with the RocketLauncher rules ``doctor`` uses (:mod:`spindoctor.rl_rom_paths`),
then runs ``RocketLauncher.exe "<system>" "<game>"``, watches what opens and
judges it: didn't start, closed by itself, an error pop-up, a Windows crash
report, not responding, errors in RocketLauncher's log, a black screen.  It
takes a screenshot, closes the game with the system's exit key and moves on.

RocketLauncher records every launch in its play statistics, which the
Recently Played and Most Played wheels are built from.  A run backs those
files up first and puts them back after every game.

A run can be killed at any moment: the GUI's Stop ends the worker with
``TerminateProcess``, so no ``finally`` runs.  Anything that changes
something outside the run folder is written to the run's journal first, and
:func:`recover` finishes a run that didn't end: it closes what the run left
open and puts the statistics back.

The Windows calls live in :mod:`spindoctor._win32`.  This module only sees
them through a *platform* object (:class:`WindowsPlatform`), so tests drive it
with fakes.
"""
from __future__ import annotations

import csv
import fnmatch
import hashlib
import io
import json
import os
import random
import re
import struct
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import _testrun
from ._undo import checkpoint
from ._utils import atomic_write_bytes, unique_path, win_safe_stem
from ._win32 import ProcInfo, Shot, WinInfo
from .config import Config
from .rl_rom_paths import _RomLookup, _raw_game_names
from .rocketlauncher import _read_rl_ini


# ─── settings ─────────────────────────────────────────────────────────────────

# Programs RocketLauncher starts that are not the game: AutoHotkey modules,
# archive and disc-image tools, keymappers, lightgun helpers, launchers.
BUILTIN_HELPERS = frozenset({
    "autohotkey.exe", "autohotkeya32.exe", "autohotkeyu32.exe", "autohotkeyu64.exe",
    "7z.exe", "7za.exe", "conhost.exe", "cmd.exe", "wscript.exe", "cscript.exe",
    "dtlite.exe", "dtagent.exe", "dthelper.exe",
    "xpadder.exe", "joytokey.exe", "antimicro.exe",
    "dxwnd.exe", "demulshooter.exe", "demulshooterx64.exe", "blockinput.exe",
    "ledblinky.exe", "werfault.exe", "cabvol.exe",
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "galaxyclient.exe",
})

# Windows programs that are never the game.
SYSTEM_PROCESSES = frozenset({
    "explorer.exe", "applicationframehost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "searchui.exe", "searchapp.exe", "textinputhost.exe",
    "lockapp.exe", "systemsettings.exe", "powershell.exe", "pwsh.exe",
    "windowsterminal.exe", "openconsole.exe", "hyperspin.exe", "rocketlauncher.exe",
    "taskmgr.exe", "dwm.exe", "ctfmon.exe", "smartscreen.exe",
})

# Words in a pop-up's title that mean something went wrong.
DEFAULT_ERROR_WORDS = (r"error|fail|missing|not found|exception|crash|cannot|can't|unable|"
                       r"bios|stopped working|corrupt|invalid|not responding")

PASS, WARN, FAIL, SKIPPED = "PASS", "WARN", "FAIL", "SKIPPED"

_LOG_ERROR_RE = re.compile(r"^\d\d:\d\d:\d\d:\d{3} \| (?:RL|MD) \|\s+ERROR\s+\|[^|]*\|\s*(.+?)\s*$", re.M)
_LOG_PID_RE = re.compile(r"Process ID: (\d+)")
_WER_TARGET_RE = re.compile(r"-p\s+(\d+)")


@dataclass
class RunSettings:
    game_seconds: int = 20
    launch_timeout: int = 90
    close_timeout: int = 25
    cooldown: int = 3
    per_system: int = 3
    screenshot_width: int = 480
    helpers: frozenset = BUILTIN_HELPERS
    ignore_log_errors: tuple = ("No CRC defined",)
    error_words: str = DEFAULT_ERROR_WORDS
    hyperspin_timeout: int = 180
    ignore_hyperspin_log: tuple = ()
    skip_intro: bool = True


def settings_from_config(config: Config, seconds: Optional[int] = None) -> RunSettings:
    """The ``test_*`` config keys as :class:`RunSettings`.

    ``test_helper_processes`` entries are added to the built-in helper list;
    an entry starting with ``!`` takes a built-in one out."""
    helpers = set(BUILTIN_HELPERS)
    for name in config.test_helper_processes:
        name = name.strip().lower()
        if name.startswith("!"):
            helpers.discard(name[1:].strip())
        elif name:
            helpers.add(name)
    return RunSettings(
        game_seconds=seconds if seconds else config.test_game_seconds,
        launch_timeout=config.test_launch_timeout,
        close_timeout=config.test_close_timeout,
        cooldown=config.test_cooldown,
        per_system=config.test_per_system,
        screenshot_width=config.test_screenshot_width,
        helpers=frozenset(helpers),
        ignore_log_errors=tuple(s for s in config.test_ignore_log_errors if s.strip()),
        error_words=config.test_error_window_words or DEFAULT_ERROR_WORDS,
        hyperspin_timeout=config.test_hyperspin_timeout,
        ignore_hyperspin_log=tuple(s for s in config.test_ignore_hyperspin_log if s.strip()),
        skip_intro=config.test_skip_intro_video,
    )


# ─── picking games ────────────────────────────────────────────────────────────

@dataclass
class PlannedGame:
    system: str
    game: str
    description: str = ""
    genre: str = ""
    emulator: str = ""
    reason: str = ""  # why it is not launched ("" = launch it)
    fix: str = ""
    doctor: str = ""  # `doctor` findings for this game, "; "-separated (gametest_notes)

    @property
    def launch(self) -> bool:
        return not self.reason


@dataclass
class Plan:
    games: list[PlannedGame] = field(default_factory=list)
    skipped_systems: list[tuple[str, str]] = field(default_factory=list)  # (system, why)

    @property
    def to_launch(self) -> list[PlannedGame]:
        return [g for g in self.games if g.launch]


class PlanError(ValueError):
    """The selection can't be turned into a plan (unknown wheel, nothing set up)."""


def main_menu_wheels(config: Config) -> list[str]:
    """The wheels on HyperSpin's Main Menu, in menu order."""
    from .health import _main_menu_wheels

    return _main_menu_wheels(config.databases_dir / "Main Menu" / "Main Menu.xml")


def _hyperspin_launches_itself(config: Config, system: str) -> bool:
    """``[exe info] hyperlaunch=false`` in HyperSpin's ``Settings\\<System>.ini``:
    HyperSpin starts these games itself, not through RocketLauncher."""
    ini = _read_rl_ini(Path(config.hyperspin_dir) / "Settings" / f"{system}.ini")
    return ini.get("exe info", {}).get("hyperlaunch", "").strip().lower() == "false"


def _wheel_entries(config: Config, system: str):
    from .database import load_database

    try:
        return list(load_database(system, config.databases_dir).iter_xml_order())
    except Exception:  # noqa: BLE001 - a broken database is check_databases' job
        return []


def check_game(
    look: _RomLookup, system: str, name: str, raw: Optional[dict] = None,
    overrides: Optional[dict] = None,
) -> tuple[str, str, str]:
    """``(emulator, problem, fix)`` for one game, by RocketLauncher's own rules.

    *problem* is "" when RocketLauncher has what it needs: settings for the
    system, an emulator with an ``Emu_Path`` that exists and a module, and,
    unless ``Skipchecks`` says not to look, the game's file in ``Rom_Path``.
    *raw* is :func:`_raw_game_names` for the wheel, *overrides* its ``Games.ini``."""
    src, other = look.game_source(system, name, overrides)
    games_ini = look.settings_dir / system / "Games.ini"
    if src is None:
        if other:
            return "", (f"Games.ini sends it to system {other}, which has no RocketLauncher "
                        f"settings"), f"Fix System= for [{name}] in {games_ini}"
        return "", f"RocketLauncher has no settings for {system}", (
            f"Set up {system} in RocketLauncherUI (Settings\\{system}\\Emulators.ini)")
    if src.stops:
        return src.emulator, f"RocketLauncher stops before looking for it: {src.stops}", src.stop_fix
    problems = look.emulator_problems(src, name)
    settings_system = other or system
    if (not look.skips_rom_check(settings_system) and src.exts and src.checkable()
            and not look.found(src, [name, raw[name]] if raw and name in raw else [name])):
        tried = ", ".join(f".{e}" if e else "(no extension)" for e in src.exts)
        problems.append((f"game file not found in Rom_Path ({tried})",
                         f"Check Rom_Path in {src.ini} and Rom_Extension in {src.ext_where}"))
    if not problems:
        return src.emulator, "", ""
    return (src.emulator, "; ".join(p for p, _f in problems),
            "; ".join(f for _p, f in problems))


def _resolve_wheels(config: Config, systems: list[str], all_systems: bool) -> list[str]:
    menu = main_menu_wheels(config)
    if all_systems:
        if not menu:
            raise PlanError("No wheels found in HyperSpin's Main Menu.xml. Check hyperspin_dir.")
        return menu
    by_low = {w.lower(): w for w in menu}
    out: list[str] = []
    for name in systems:
        hit = by_low.get(name.strip().lower())
        if hit is None:
            if (config.databases_dir / name / f"{name}.xml").is_file():
                hit = name  # not on the Main Menu, but it has a wheel database
            else:
                raise PlanError(f"No wheel named {name!r} on the Main Menu.")
        if hit not in out:
            out.append(hit)
    return out


def pick_games(
    config: Config,
    *,
    systems: Optional[list[str]] = None,
    all_systems: bool = False,
    genres: Optional[list[str]] = None,
    games: Optional[list[str]] = None,
    all_games: bool = False,
    count: Optional[int] = None,
    per_system: Optional[int] = None,
    seed: Optional[int] = None,
    include_skipped: bool = False,
) -> Plan:
    """Turn a selection into a :class:`Plan`, each game checked by :func:`check_game`.

    With ``--game`` patterns or ``--all`` every matching game is listed, and
    the ones that can't launch say why.  Random picks (``count`` in total,
    ``per_system`` per wheel) only draw from games that can launch, as the
    PowerShell tester's Quick mode did.  Without ``--system`` a genre or game
    pattern searches every wheel."""
    from ._wheels import synthetic_names
    from .edit import genre_matches

    systems = list(systems or [])
    genres = [g for g in (genres or []) if g.strip()]
    patterns = [p.strip().lower() for p in (games or []) if p.strip()]
    if not systems and not all_systems:
        if not (genres or patterns):
            raise PlanError("Name the wheels to test with --system, or use --all-systems.")
        all_systems = True
    wheels = _resolve_wheels(config, systems, all_systems)
    named = {s.lower() for s in systems}
    if not all_games and count is None and per_system is None and not patterns:
        per_system = config.test_per_system
    rng = random.Random(seed)
    look = _RomLookup(Path(config.rocketlauncher_dir))
    synthetic = {s.lower() for s in synthetic_names(config)} if config.test_skip_custom_wheels else set()
    skip_list = {s.strip().lower() for s in config.test_skip_systems}

    plan = Plan()
    pools: list[list[PlannedGame]] = []
    for system in wheels:
        low = system.lower()
        chosen = include_skipped or low in named
        own = look.source(system)
        why = ""
        if _hyperspin_launches_itself(config, system):
            why = "HyperSpin starts these games itself, not through RocketLauncher"
        elif own is None:
            why = "RocketLauncher has no settings for this wheel"
        elif low in synthetic and not chosen:
            why = "SpinDoctor's own Custom Wheel; its games come from other wheels"
        elif low in skip_list and not chosen:
            why = "on the test_skip_systems list"
        elif (config.test_skip_pclauncher and own.emulator.lower() == "pclauncher"
              and not chosen):
            why = "its games use PCLauncher (test_skip_pclauncher)"
        if why:
            plan.skipped_systems.append((system, why))
            continue
        entries = [e for e in _wheel_entries(config, system) if e.enabled != "No"]
        if genres:
            entries = [e for e in entries if any(genre_matches(e.genre, g) for g in genres)]
        if patterns:
            entries = [e for e in entries
                       if any(fnmatch.fnmatchcase(e.name.lower(), p) for p in patterns)]
        if not entries:
            continue
        raw = _raw_game_names(system, config.databases_dir)
        overrides = look.game_overrides(system)
        checked: list[PlannedGame] = []
        for e in entries:
            emu, problem, fix = check_game(look, system, e.name, raw, overrides)
            item = PlannedGame(system, e.name, e.description or "", e.genre or "", emu, problem, fix)
            if (not problem and config.test_skip_pclauncher and not chosen
                    and emu.lower() == "pclauncher"):
                item.reason = "uses PCLauncher (test_skip_pclauncher)"
            checked.append(item)
        if all_games or (patterns and count is None and per_system is None):
            plan.games.extend(checked)
            continue
        ok = [g for g in checked if g.launch]
        if per_system is not None:
            picked = rng.sample(ok, min(per_system, len(ok)))
            order = {id(g): i for i, g in enumerate(checked)}
            plan.games.extend(sorted(picked, key=lambda g: order[id(g)]))
        else:
            pools.append(ok)
    if count is not None and pools:
        everything = [g for pool in pools for g in pool]
        picked = rng.sample(everything, min(count, len(everything)))
        order = {id(g): i for i, g in enumerate(everything)}
        plan.games.extend(sorted(picked, key=lambda g: order[id(g)]))
    from .gametest_notes import add_notes

    add_notes(config, plan.games, look)
    return plan


# ─── exit keys and the RocketLauncher log ─────────────────────────────────────

_VK_NAMES = {
    "esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "bs": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22, "pause": 0x13,
    "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1, "ctrl": 0x11, "control": 0x11,
    "lctrl": 0xA2, "rctrl": 0xA3, "lcontrol": 0xA2, "rcontrol": 0xA3,
    "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5,
}


def virtual_key(name: str) -> int:
    """An AutoHotkey key name (``Esc``, ``F12``, ``~1``, ``Numpad5``) as a
    virtual-key code, or -1 for one that isn't a keyboard key."""
    key = name.strip().lstrip("~$*!^+#").strip().lower()
    if not key:
        return -1
    if key in _VK_NAMES:
        return _VK_NAMES[key]
    m = re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key)
    if m:
        return 0x6F + int(m.group(1))
    m = re.fullmatch(r"numpad([0-9])", key)
    if m:
        return 0x60 + int(m.group(1))
    if re.fullmatch(r"[a-z0-9]", key):
        return ord(key.upper())
    return -1


@dataclass
class ExitKey:
    vks: list[int]
    hold_ms: int
    text: str


def exit_key(look: _RomLookup, system: str) -> ExitKey:
    """The key RocketLauncher closes *system*'s games with: ``[Exit]
    Exit_Emulator_Key`` (``Esc``, ``H500:Esc`` to hold it 500 ms, ``~1 & ~2``
    for a combination, ``|`` between alternatives).  Joystick alternatives
    are passed over; with nothing usable, Esc."""
    raw = look.rl_setting(system, "exit", "exit_emulator_key", "").strip() or "Esc"
    wait = look.rl_setting(system, "exit", "exit_emulator_key_wait", "0").strip()
    hold = int(wait) if wait.isdigit() else 0
    for alt in raw.split("|"):
        alt = alt.strip()
        m = re.match(r"^H(\d+):(.*)$", alt, re.I)
        h = 0
        if m:
            h, alt = int(m.group(1)), m.group(2)
        if "joy" in alt.lower():
            continue
        vks = [virtual_key(part) for part in alt.split("&")]
        if vks and all(v >= 0 for v in vks):
            return ExitKey(vks, max(hold, h) + 150, raw)
    return ExitKey([0x1B], hold + 150, raw)


def read_log(path: Path, since: Optional[float] = None) -> str:
    """RocketLauncher's log, or "" when it is missing or older than *since*
    (RocketLauncher starts a new log for every launch)."""
    from ._text import read_windows_text

    try:
        if since is not None and path.stat().st_mtime < since - 2:
            return ""
        return read_windows_text(path)
    except OSError:
        return ""


def log_errors(text: str, ignore: tuple = ()) -> list[str]:
    """The ``ERROR`` lines of a RocketLauncher log, minus *ignore* substrings."""
    out: list[str] = []
    for m in _LOG_ERROR_RE.finditer(text or ""):
        msg = m.group(1)
        if any(i.lower() in msg.lower() for i in ignore):
            continue
        if msg not in out:
            out.append(msg)
    return out


def log_pids(text: str) -> list[int]:
    """The ``Process ID: N`` lines: programs RocketLauncher says it started."""
    return [int(m.group(1)) for m in _LOG_PID_RE.finditer(text or "")]


# ─── screenshots ──────────────────────────────────────────────────────────────

def looks_black(pixels: bytes, width: int, height: int,
                region: Optional[tuple[int, int, int, int]] = None) -> bool:
    """Whether the middle of *region* (``left, top, width, height``; the
    whole screen when None or tiny) is black: no sampled pixel brighter than
    24 of 255.  The middle only, because bezels around a game are often bright."""
    rx, ry, rw, rh = 0, 0, width, height
    if region:
        rx, ry = max(0, region[0]), max(0, region[1])
        rw, rh = min(region[2], width - rx), min(region[3], height - ry)
        if rw < 40 or rh < 40:
            rx, ry, rw, rh = 0, 0, width, height
    x0, x1 = rx + int(rw * 0.3), rx + int(rw * 0.7)
    y0, y1 = ry + int(rh * 0.2), ry + int(rh * 0.8)
    step_x, step_y = max(1, (x1 - x0) // 24), max(1, (y1 - y0) // 16)
    brightest = 0.0
    for y in range(y0, y1, step_y):
        row = y * width * 4
        for x in range(x0, x1, step_x):
            i = row + x * 4
            lum = 0.114 * pixels[i] + 0.587 * pixels[i + 1] + 0.299 * pixels[i + 2]  # B, G, R
            if lum > brightest:
                brightest = lum
    return brightest < 24


def encode_png(width: int, height: int, bgra: bytes) -> bytes:
    """32-bit BGRA rows as an RGB PNG, with nothing but the standard library."""
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    stride = width * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def encode_image(width: int, height: int, bgra: bytes) -> tuple[bytes, str]:
    """``(file bytes, extension)``: JPEG through Pillow when it is installed, else PNG."""
    try:
        from PIL import Image
    except ImportError:
        return encode_png(width, height, bgra), "png"
    img = Image.frombuffer("RGB", (width, height), bgra, "raw", "BGRX", 0, 1)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    return buf.getvalue(), "jpg"


# ─── the platform ─────────────────────────────────────────────────────────────

class WindowsPlatform:
    """The real thing: :mod:`spindoctor._win32`, ``subprocess`` and the clock."""

    def __init__(self) -> None:
        from . import _win32

        self._w = _win32
        _win32.make_dpi_aware()

    def list_processes(self) -> list[ProcInfo]:
        return self._w.list_processes()

    def list_windows(self) -> list[WinInfo]:
        return self._w.list_windows()

    def foreground_pid(self) -> int:
        return self._w.foreground_pid()

    def bring_to_front(self, hwnd: int) -> None:
        self._w.bring_to_front(hwnd)

    def is_hung(self, hwnd: int) -> bool:
        return self._w.is_hung(hwnd)

    def press_keys(self, vks: list[int], hold_ms: int) -> None:
        self._w.press_keys(vks, hold_ms)

    def type_keys(self, vks: list[int]) -> None:
        self._w.type_keys(vks)

    def close_window(self, hwnd: int) -> None:
        self._w.close_window(hwnd)

    def terminate(self, pid: int) -> bool:
        return self._w.terminate(pid)

    def start_time(self, pid: int) -> Optional[float]:
        return self._w.process_start_time(pid)

    def image_path(self, pid: int) -> str:
        return self._w.process_image_path(pid)

    def watch_folder(self, root: str):
        return self._w.DirectoryWatcher(root)

    def command_line(self, pid: int) -> str:
        return self._w.command_line(pid)

    def screen_size(self) -> tuple[int, int]:
        _l, _t, w, h = self._w.screen_rect()
        return w, h

    def capture(self, thumb_width: int) -> Optional[Shot]:
        return self._w.capture_screen(thumb_width)

    def start(self, args: list[str], cwd: str):
        return self._w.start_process(args, cwd)

    def worker_pid(self) -> int:
        return os.getpid()

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _wait_exit(platform, proc, timeout: float) -> bool:
    """Wait up to *timeout* seconds for *proc* to end."""
    end = platform.now() + timeout
    while proc.poll() is None:
        if platform.now() >= end:
            return False
        platform.sleep(0.5)
    return True


# ─── judging one launch ───────────────────────────────────────────────────────

@dataclass
class Observation:
    game_windows: list[WinInfo]
    error_windows: list[WinInfo]
    alive_game: dict[int, str]
    crash: bool
    busy: bool
    alive: dict[int, str]


class LaunchWatch:
    """What RocketLauncher has started, poll by poll.

    *owned* collects the processes RocketLauncher started (its new
    descendants, plus the PIDs its log names), minus helpers; *seen* collects
    other new programs with a big window (a game Steam started).  Pop-ups
    are small windows of a dialog class (``#32770``) or with an error word in
    the title, from those programs, RocketLauncher or WerFault."""

    def __init__(self, rl_pid: int, before: dict[int, str], settings: RunSettings,
                 screen: tuple[int, int], game_names: list[str],
                 wer_target: Callable[[int], Optional[int]]):
        self.rl_pid = rl_pid
        self.before = before
        self.helpers = settings.helpers
        self.screen = screen
        self.game_names = [n for n in game_names if len(n) >= 3]
        self.error_re = re.compile(settings.error_words, re.I)
        self.wer_target = wer_target
        self.owned: dict[int, str] = {}
        self.seen: dict[int, str] = {}
        self.wer_hits: dict[int, bool] = {}

    def update(self, procs: list[ProcInfo], windows: list[WinInfo],
               logged_pids: Optional[list[int]] = None) -> Observation:
        alive = {p.pid: p.name for p in procs}
        children: dict[int, list[int]] = {}
        for p in procs:
            if p.pid != p.parent:
                children.setdefault(p.parent, []).append(p.pid)
        busy = False
        queue, visited = [self.rl_pid], set()
        while queue:
            pid = queue.pop()
            if pid in visited:
                continue
            visited.add(pid)
            for kid in children.get(pid, ()):
                if kid in self.before:
                    continue
                queue.append(kid)
                name = alive.get(kid, "")
                if name.lower().startswith("7z"):
                    busy = True  # still unpacking the game
                if name.lower() not in self.helpers:
                    self.owned[kid] = name
        for pid in logged_pids or ():
            name = alive.get(pid)
            if name and pid not in self.before and name.lower() not in self.helpers:
                self.owned[pid] = name

        sw, sh = self.screen
        game_windows: list[WinInfo] = []
        error_windows: list[WinInfo] = []
        for w in windows:
            if w.pid in self.before:
                continue
            name = alive.get(w.pid)
            if name is None:
                continue
            low = name.lower()
            is_rl = w.pid == self.rl_pid
            is_wer = low == "werfault.exe"
            big = w.width >= 160 and w.height >= 120
            if (not is_rl and not is_wer and w.pid not in self.owned and big
                    and low not in self.helpers and low not in SYSTEM_PROCESSES):
                self.seen[w.pid] = name
            is_game = w.pid in self.owned or w.pid in self.seen
            if not (is_game or is_rl or is_wer):
                continue
            # The game's own name comes out first, so "Crash Bandicoot" isn't a crash.
            title = w.title
            for gn in self.game_names:
                title = re.sub(re.escape(gn), lambda _m: "", title, flags=re.I)
            small = w.width < 0.7 * sw or w.height < 0.7 * sh
            if (is_wer and w.width > 0) or (
                    small and w.width > 0 and (w.cls == "#32770" or self.error_re.search(title))):
                error_windows.append(w)
            elif is_game and big:
                game_windows.append(w)

        alive_game = {pid: n for pid, n in list(self.owned.items()) + list(self.seen.items())
                      if alive.get(pid) == n}
        watched = set(alive_game) | set(self.owned) | {self.rl_pid}
        crash = False
        for pid, name in alive.items():
            if name.lower() == "werfault.exe" and pid not in self.before:
                if pid not in self.wer_hits:
                    self.wer_hits[pid] = self.wer_target(pid) in watched
                crash = crash or self.wer_hits[pid]
        return Observation(game_windows, error_windows, alive_game, crash, busy, alive)


def _game_names(item: PlannedGame) -> list[str]:
    """The game's name and description without "(USA)"-style tags, for
    taking them out of window titles."""
    names = []
    for text in (item.game, item.description):
        base = re.sub(r"\s*[\(\[].*$", "", text or "").strip()
        if len(base) >= 3 and base not in names:
            names.append(base)
    return names


def _safe_name(name: str) -> str:
    """A file name for *name*: Windows-safe, at most about 90 characters."""
    safe = win_safe_stem(name) or "_"
    if len(safe) > 90:
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]  # noqa: S324 - a file name, not security
        safe = safe[:80].strip() + "~" + digest
    return safe


@dataclass
class LaunchResult:
    status: str
    reason: str
    details: list[str] = field(default_factory=list)
    seconds: int = 0
    screenshot: str = ""  # relative to the run folder, with / separators
    log: str = ""
    capture: str = ""  # how the screenshot was taken


class Runner:
    """Launches one game at a time and judges it (the tester's ``Test-GameLaunch``)."""

    def __init__(self, config: Config, settings: RunSettings, platform, run_dir: Path,
                 journal: "Journal", stop_requested: Callable[[], bool] = lambda: False):
        self.settings = settings
        self.platform = platform
        self.run_dir = run_dir
        self.journal = journal
        self.stop_requested = stop_requested
        self.rl_dir = Path(config.rocketlauncher_dir)
        self.rl_exe = self.rl_dir / "RocketLauncher.exe"
        self.rl_log = self.rl_dir / "RocketLauncher.log"
        self.look = _RomLookup(self.rl_dir)
        self.screen = platform.screen_size()

    def _wer_target(self, pid: int) -> Optional[int]:
        try:
            m = _WER_TARGET_RE.search(self.platform.command_line(pid) or "")
        except OSError:
            return None
        return int(m.group(1)) if m else None

    def _record(self, rl_pid: int, rl_started: Optional[float], watch: Optional[LaunchWatch]) -> None:
        procs = [{"pid": rl_pid, "name": "RocketLauncher.exe", "started": rl_started}]
        for pid, name in (watch.owned.items() if watch else ()):
            procs.append({"pid": pid, "name": name, "started": self.platform.start_time(pid)})
        self.journal.data["current"]["processes"] = procs
        self.journal.save()

    def launch(self, item: PlannedGame) -> Optional[LaunchResult]:
        """Launch, judge and close *item*.  None when a stop was requested
        mid-launch: the game was closed and gets no result, so ``--resume``
        tests it again."""
        p, s = self.platform, self.settings
        fails: list[str] = []
        warns: list[str] = []
        before = {pr.pid: pr.name for pr in p.list_processes()}
        t0 = p.now()
        self.journal.data["current"] = {
            "system": item.system, "game": item.game, "launch_at": t0, "processes": []}
        self.journal.save()
        try:
            proc = p.start([str(self.rl_exe), item.system, item.game], str(self.rl_dir))
        except OSError as exc:
            return LaunchResult(FAIL, f"Couldn't start RocketLauncher: {exc}")
        rl_started = p.start_time(proc.pid)
        self._record(proc.pid, rl_started, None)
        watch = LaunchWatch(proc.pid, before, s, self.screen, _game_names(item), self._wer_target)
        known = 0
        started = ended_early = stopped = False
        opened_at = judge_at = 0.0
        deadline = t0 + s.launch_timeout
        state: Optional[Observation] = None
        while True:
            p.sleep(1)
            if proc.poll() is not None:
                ended_early = True
                break
            if self.stop_requested():
                stopped = True
                break
            text = read_log(self.rl_log, since=t0)
            state = watch.update(p.list_processes(), p.list_windows(), log_pids(text))
            if len(watch.owned) != known:
                known = len(watch.owned)
                self._record(proc.pid, rl_started, watch)
            if state.error_windows:
                for w in state.error_windows:
                    who = "RocketLauncher showed a pop-up" if w.pid == proc.pid else "Pop-up window appeared"
                    msg = f"{who}: '{w.title}'"
                    if msg not in fails:
                        fails.append(msg)
                break
            if state.crash:
                fails.append("The emulator crashed (Windows crash report appeared)")
                break
            now = p.now()
            if state.busy and deadline < now + 10:
                deadline = now + 10  # still unpacking
            if not started:
                if state.game_windows:
                    started, opened_at, judge_at = True, now, now + s.game_seconds
                elif now >= deadline:
                    if state.alive_game:
                        started, opened_at, judge_at = True, now, now
                        warns.append("The emulator is running but no game window was seen")
                    else:
                        fails.append(f"Game didn't start: nothing opened within {s.launch_timeout} seconds")
                        break
            if started and now >= judge_at:
                break

        result = LaunchResult(PASS, "Opened and ran normally")
        if ended_early:
            elapsed = int(p.now() - t0)
            if started:
                fails.append(f"Game closed by itself {int(p.now() - opened_at)} seconds after it opened")
            else:
                fails.append(f"Game didn't start: RocketLauncher closed after {elapsed} seconds")
        elif not stopped:
            self._judge_running(item, proc, state, started, fails, warns, result)

        how = self._close(proc, watch, state, item.system)
        if how == "forced":
            warns.append("The exit key didn't close it; SpinDoctor had to force-close the emulator")
        elif how == "killed":
            warns.append("The exit key didn't close it; SpinDoctor had to force-close RocketLauncher")
        self._stop_owned(watch)
        for pid, hit in watch.wer_hits.items():
            if hit:
                p.terminate(pid)
        if stopped:
            return None

        text = read_log(self.rl_log, since=t0)
        if text:
            rel = f"logs/{_safe_name(item.system)}/{_safe_name(item.game)}.log"
            try:
                path = self.run_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                result.log = rel
            except OSError:
                pass
        errors = log_errors(text, s.ignore_log_errors)
        if fails:
            result.status, result.reason = FAIL, fails[0]
            if ended_early and errors:
                result.reason += f". RocketLauncher said: {errors[0]}"
        else:
            if errors:
                warns.append(f"RocketLauncher logged an error: {errors[0]}")
            if warns:
                result.status, result.reason = WARN, warns[0]
        result.details = fails + warns + [f"Log: {e}" for e in errors]
        result.seconds = int(p.now() - t0)
        return result

    def _judge_running(self, item, proc, state, started, fails, warns, result) -> None:
        """Screenshot, black screen, window in front and not responding, for a
        game that is still running at judging time."""
        p = self.platform
        if state is not None and started and not fails:
            fg = p.foreground_pid()
            if not (fg == proc.pid or fg in state.alive_game) and state.game_windows:
                p.bring_to_front(state.game_windows[0].hwnd)
                p.sleep(0.7)
                fg = p.foreground_pid()
                if not (fg == proc.pid or fg in state.alive_game):
                    warns.append("The game window was not in front")
        region = None
        if state is not None and state.game_windows:
            w = max(state.game_windows, key=lambda win: win.width * win.height)
            region = (w.left, w.top, w.width, w.height)
        try:
            shot = p.capture(self.settings.screenshot_width)
        except OSError:
            shot = None
        if shot is not None:
            result.capture = shot.method
            data, ext = encode_image(shot.thumb_width, shot.thumb_height, shot.thumb)
            rel = f"screenshots/{_safe_name(item.system)}/{_safe_name(item.game)}.{ext}"
            try:
                path = self.run_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                result.screenshot = rel
            except OSError:
                pass
            if started and not fails and looks_black(shot.pixels, shot.width, shot.height, region):
                warns.append("Screen looked black (the game may still be loading, "
                             "or it uses a mode screenshots cannot capture)")
        if state is not None and not fails:
            for w in state.game_windows:
                name = state.alive_game.get(w.pid)
                if name and p.is_hung(w.hwnd):
                    msg = f"{re.sub(r'(?i)[.]exe$', '', name)} stopped responding"
                    if msg not in fails:
                        fails.append(msg)

    def _close(self, proc, watch: LaunchWatch, state: Optional[Observation], system: str) -> str:
        """Close the game with the system's exit key; force it if it won't go.
        ``closed``, ``forced`` (the emulator was ended) or ``killed`` (RocketLauncher too)."""
        p = self.platform
        if proc.poll() is not None:
            return "closed"
        key = exit_key(self.look, system)
        hs = next((pr.pid for pr in p.list_processes() if pr.name.lower() == "hyperspin.exe"), 0)
        fg = p.foreground_pid()
        in_front = fg == proc.pid or (state is not None and fg in state.alive_game)
        if not in_front and state is not None and state.game_windows:
            p.bring_to_front(state.game_windows[0].hwnd)
            p.sleep(0.5)
            fg = p.foreground_pid()
        if not hs or fg != hs:  # Esc in HyperSpin itself would open its exit menu
            p.press_keys(key.vks, key.hold_ms)
        if _wait_exit(p, proc, self.settings.close_timeout):
            return "closed"
        self._stop_owned(watch)
        if _wait_exit(p, proc, 15):
            return "forced"
        p.terminate(proc.pid)
        _wait_exit(p, proc, 5)
        return "killed"

    def _stop_owned(self, watch: LaunchWatch) -> None:
        """End what RocketLauncher started, checking each PID's name first in
        case Windows gave it to another program."""
        alive = {pr.pid: pr.name for pr in self.platform.list_processes()}
        for pid, name in list(watch.owned.items()) + list(watch.seen.items()):
            if alive.get(pid) == name:
                self.platform.terminate(pid)


# ─── play statistics ──────────────────────────────────────────────────────────

def backup_stats(rl_dir: Path, folder: Path) -> Path:
    """Copy every RocketLauncher statistics file into *folder*; returns its
    ``manifest.json``, in the format ``spindoctor scrub-restore`` reads."""
    from .playtime import stat_files

    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for path in stat_files(rl_dir):
        try:
            rel = path.relative_to(rl_dir)
        except ValueError:
            rel = Path(path.name)
        dest = folder / "stats" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        files.append({"original": str(path), "backup": str(Path("stats") / rel)})
    manifest = folder / "manifest.json"
    data = {"created": datetime.now().isoformat(timespec="seconds"),
            "rocketlauncher_dir": str(rl_dir), "files": files}
    atomic_write_bytes(manifest, json.dumps(data, indent=2).encode("utf-8"))
    return manifest


def restore_stats(rl_dir: Path, manifest: Path) -> tuple[int, int]:
    """Put the statistics files listed in *manifest* back where they differ,
    and delete statistics files that weren't there when it was written.
    Returns ``(restored, removed)``."""
    from .playtime import stat_files

    data = json.loads(manifest.read_text(encoding="utf-8"))
    folder = manifest.parent
    saved = {os.path.normcase(e["original"]): e for e in data.get("files", [])}
    restored = removed = 0
    for path in stat_files(rl_dir):
        if os.path.normcase(str(path)) not in saved:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    for entry in saved.values():
        target = Path(entry["original"])
        backup = (folder / entry["backup"]).read_bytes()
        try:
            if target.read_bytes() == backup:
                continue
        except OSError:
            target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, backup)
        restored += 1
    return restored, removed


# ─── run folders, journal and results ─────────────────────────────────────────

RESULT_FIELDS = ["System", "Game", "Status", "Reason", "Details", "Emulator", "Seconds",
                 "Screenshot", "Log", "Fix", "Doctor", "Cleaned", "Tested"]
PLAN_FIELDS = ["System", "Game", "Description", "Genre", "Emulator", "Reason", "Fix", "Doctor"]


class Journal:
    """``journal.json`` in a run folder, rewritten atomically before each step
    that changes something outside it, so :func:`recover` knows what to undo."""

    def __init__(self, path: Path, data: Optional[dict] = None):
        self.path = path
        self.data = data if data is not None else {}

    @classmethod
    def load(cls, path: Path) -> "Journal":
        try:
            return cls(path, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return cls(path)

    def save(self) -> None:
        checkpoint(self.path, self.data)


def _write_csv(path: Path, fields: list[str], rows: list[dict], append: bool = False) -> None:
    new = not append or not path.exists()
    with open(path, "a" if append else "w", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def read_run(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_run(run_dir: Path, info: dict) -> None:
    atomic_write_bytes(run_dir / "run.json", json.dumps(info, indent=2).encode("utf-8"))


def write_results_json(run_dir: Path) -> None:
    """``results.json`` and ``report.html`` from ``run.json`` and ``results.csv``."""
    from .gametest_report import write_report

    data = {"run": read_run(run_dir), "results": read_csv(run_dir / "results.csv")}
    atomic_write_bytes(run_dir / "results.json", json.dumps(data, indent=2).encode("utf-8"))
    write_report(run_dir, data)


def list_runs(root: Path) -> list[tuple[Path, dict]]:
    """``(run folder, run.json)`` for every run under *root*, newest first."""
    if not root.is_dir():
        return []
    runs = [(d, read_run(d)) for d in root.iterdir() if (d / "run.json").is_file()]
    return sorted(runs, key=lambda r: r[0].name, reverse=True)


def plan_rows(plan: Plan) -> list[dict]:
    return [{"System": g.system, "Game": g.game, "Description": g.description, "Genre": g.genre,
             "Emulator": g.emulator, "Reason": g.reason, "Fix": g.fix, "Doctor": g.doctor}
            for g in plan.games]


def plan_from_rows(rows: list[dict]) -> Plan:
    return Plan(games=[PlannedGame(r.get("System", ""), r.get("Game", ""), r.get("Description", ""),
                                   r.get("Genre", ""), r.get("Emulator", ""), r.get("Reason", ""),
                                   r.get("Fix", ""), r.get("Doctor", "")) for r in rows])


def recheck(config: Config, items: list[tuple[str, str]]) -> Plan:
    """A plan for these ``(system, game)`` pairs (``--only-failed``), each
    checked again by :func:`check_game`."""
    look = _RomLookup(Path(config.rocketlauncher_dir))
    plan = Plan()
    entries: dict[str, dict] = {}
    for system, game in items:
        if system not in entries:
            entries[system] = {e.name: e for e in _wheel_entries(config, system)}
        e = entries[system].get(game)
        emu, problem, fix = check_game(look, system, game, _raw_game_names(system, config.databases_dir))
        plan.games.append(PlannedGame(system, game, e.description if e else "", e.genre if e else "",
                                      emu, problem, fix))
    from .gametest_notes import add_notes

    add_notes(config, plan.games, look)
    return plan


# ─── a whole run ──────────────────────────────────────────────────────────────

@dataclass
class RunSummary:
    run_dir: Path
    planned: int = 0
    launched: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {PASS: 0, WARN: 0, FAIL: 0, SKIPPED: 0})
    finished: bool = False
    stats_restored: bool = False


def new_run_dir(root: Path) -> Path:
    path = unique_path(root / datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    path.mkdir(parents=True)
    return path


def rocketlauncher_running(platform) -> bool:
    names = {"rocketlauncher.exe", "rocketlaunchergame.exe"}
    return any(p.name.lower() in names for p in platform.list_processes())


def run_plan(
    config: Config,
    plan: Plan,
    settings: RunSettings,
    platform,
    *,
    run_dir: Optional[Path] = None,
    selection: Optional[dict] = None,
    on_result: Optional[Callable[[int, int, PlannedGame, LaunchResult, float], None]] = None,
    with_hyperspin: bool = False,
    play_intro: bool = False,
    leave_hyperspin_open: bool = False,
    on_hyperspin: Optional[Callable[[dict], None]] = None,
    cleanup: Optional[str] = None,
) -> RunSummary:
    """Launch every game of *plan* that can launch; a new run folder unless
    *run_dir* (``--resume``) is given.  The caller runs :func:`recover` first.

    *on_result* gets ``(number, total, game, result, seconds left)`` after each
    game.  Ctrl+C ends the run cleanly; the run folder then says it isn't
    finished, and ``--resume`` carries on.

    With *with_hyperspin*, HyperSpin is opened first and its startup judged
    (:mod:`spindoctor.gametest_hyperspin`; *on_hyperspin* gets the result),
    and closed again at the end unless *leave_hyperspin_open*.

    *cleanup* (``report`` / ``remove`` / ``off``, default ``test_cleanup``)
    decides what happens to files the games create
    (:mod:`spindoctor.gametest_cleanup`)."""
    from . import gametest_cleanup, gametest_hyperspin
    rl_dir = Path(config.rocketlauncher_dir)
    resumed = run_dir is not None
    if run_dir is None:
        run_dir = new_run_dir(_testrun.tests_dir(config))
        _save_run(run_dir, {
            "started": datetime.now().isoformat(timespec="seconds"), "ended": "",
            "finished": False, "interrupted": False, "seconds": settings.game_seconds,
            "selection": selection or {},
        })
        _write_csv(run_dir / "plan.csv", PLAN_FIELDS, plan_rows(plan))
        skipped = [{"System": g.system, "Game": g.game, "Status": SKIPPED, "Reason": g.reason,
                    "Emulator": g.emulator, "Fix": g.fix, "Seconds": 0, "Doctor": g.doctor,
                    "Tested": datetime.now().isoformat(sep=" ", timespec="seconds")}
                   for g in plan.games if not g.launch]
        _write_csv(run_dir / "results.csv", RESULT_FIELDS, skipped)
    summary = RunSummary(run_dir)
    rows = read_csv(run_dir / "results.csv")
    done = {(r["System"], r["Game"]) for r in rows}
    for r in rows:
        summary.counts[r["Status"]] = summary.counts.get(r["Status"], 0) + 1
    already = sum(1 for r in rows if r["Status"] != SKIPPED)
    remaining = [g for g in plan.to_launch if (g.system, g.game) not in done]
    summary.planned = len(plan.to_launch)

    journal = Journal(run_dir / "journal.json", {"run": run_dir.name, "current": {}})
    manifest = run_dir / "stats-backup" / "manifest.json"
    if not (resumed and manifest.is_file()):
        manifest = backup_stats(rl_dir, run_dir / "stats-backup")
    journal.data["stats"] = {"manifest": str(manifest), "restored": True}
    journal.save()
    pid = platform.worker_pid()
    _testrun.set_active(run_dir, {"pid": pid, "started": platform.start_time(pid)})
    stop_file = run_dir / "stop-request"
    n = 0
    cleaner = None
    try:
        try:
            stop_file.unlink()
        except FileNotFoundError:
            pass
        mode = cleanup or config.test_cleanup
        if mode in ("report", "remove"):
            roots = gametest_cleanup.watched_roots(config)
            images = [platform.image_path(p.pid) for p in platform.list_processes()]
            skip = gametest_cleanup.skip_folders(config, roots, [i for i in images if i])
            cleaner = gametest_cleanup.Cleanup(config, run_dir, mode, roots, skip, since=time.time(),
                                               watcher_factory=platform.watch_folder)
            journal.data["cleanup"] = {"mode": mode, "roots": roots, "skip": skip, "since": cleaner.since}
            journal.save()
            cleaner.start()
        runner = Runner(config, settings, platform, run_dir, journal, stop_requested=stop_file.exists)
        if with_hyperspin:
            hs = gametest_hyperspin.start_and_check(config, settings, platform, run_dir, journal,
                                                   play_intro=play_intro)
            info = read_run(run_dir)
            info["hyperspin"] = hs
            _save_run(run_dir, info)
            write_results_json(run_dir)
            if on_hyperspin is not None:
                on_hyperspin(hs)
        t_start = platform.now()
        for item in remaining:
            if stop_file.exists():
                break
            n += 1
            journal.data["stats"]["restored"] = False
            journal.save()
            result = runner.launch(item)
            restore_stats(rl_dir, manifest)
            journal.data["stats"]["restored"] = True
            journal.data["current"] = {}
            journal.save()
            cleaned = cleaner.after_game(f"{item.system} > {item.game}") if cleaner else ""
            if result is None:  # stop requested mid-launch
                break
            summary.launched += 1
            summary.counts[result.status] = summary.counts.get(result.status, 0) + 1
            _write_csv(run_dir / "results.csv", RESULT_FIELDS, [{
                "System": item.system, "Game": item.game, "Status": result.status,
                "Reason": result.reason, "Details": "\n".join(result.details),
                "Emulator": item.emulator, "Seconds": result.seconds,
                "Screenshot": result.screenshot, "Log": result.log, "Fix": "", "Doctor": item.doctor,
                "Cleaned": cleaned, "Tested": datetime.now().isoformat(sep=" ", timespec="seconds"),
            }], append=True)
            if on_result is not None:
                per_game = (platform.now() - t_start) / n
                on_result(already + n, len(plan.to_launch), item, result,
                          per_game * (len(remaining) - n))
            if n % 10 == 0:
                write_results_json(run_dir)
            if n < len(remaining):
                platform.sleep(settings.cooldown)
        else:
            summary.finished = True
    finally:
        if not journal.data["stats"]["restored"]:
            # Interrupted mid-launch (Ctrl+C): close what is still open first.
            _close_leftovers(platform, journal.data.get("current") or {})
            try:
                restore_stats(rl_dir, manifest)
                journal.data["stats"]["restored"] = True
                journal.data["current"] = {}
            except OSError:
                pass  # the pointer stays, so recover() tries again
            journal.save()
        hs_entry = journal.data.get("hyperspin") or {}
        if hs_entry.get("started_by_us"):
            if not leave_hyperspin_open:
                gametest_hyperspin.close(config, platform, hs_entry)
            journal.data["hyperspin"] = {}
            journal.save()
        info = read_run(run_dir)
        if cleaner is not None:
            try:
                cleaner.finish()
                info["cleanup"] = cleaner.summary()
                journal.data["cleanup"] = {}
                journal.save()
            except OSError:
                pass  # the journal still names the cleanup, so recover() sweeps again
        summary.stats_restored = journal.data["stats"]["restored"]
        info["ended"] = datetime.now().isoformat(timespec="seconds")
        info["finished"] = summary.finished
        _save_run(run_dir, info)
        write_results_json(run_dir)
        if summary.stats_restored and not (journal.data.get("cleanup") or {}):
            _testrun.clear_active()
    return summary


# ─── recovery ─────────────────────────────────────────────────────────────────

@dataclass
class RecoveryReport:
    run_dir: Path
    closed: list[str] = field(default_factory=list)
    stats_restored: tuple[int, int] = (0, 0)
    messages: list[str] = field(default_factory=list)


def _same_process(platform, alive: dict[int, ProcInfo], entry: dict) -> bool:
    """Whether the journal's *entry* (pid, name, start time) is still running
    as the same program."""
    proc = alive.get(entry.get("pid"))
    if proc is None or proc.name.lower() != str(entry.get("name", "")).lower():
        return False
    recorded = entry.get("started")
    if recorded is None:
        return True
    now = platform.start_time(proc.pid)
    return now is not None and abs(now - recorded) < 0.01


def _close_leftovers(platform, current: dict) -> list[str]:
    """End what the journal's current launch left running: the recorded
    processes, and anything they started after the launch.  Returns their names."""
    if platform is None or not current:
        return []
    procs = platform.list_processes()
    alive = {p.pid: p for p in procs}
    launch_at = current.get("launch_at") or 0
    targets: dict[int, str] = {}
    for entry in current.get("processes") or []:
        if _same_process(platform, alive, entry):
            targets[entry["pid"]] = alive[entry["pid"]].name
    if not targets and launch_at:
        # Killed between starting RocketLauncher and writing its PID down.
        for p in procs:
            if p.name.lower() == "rocketlauncher.exe":
                t = platform.start_time(p.pid)
                if t is not None and t >= launch_at - 1:
                    targets[p.pid] = p.name
    grew = True
    while grew:  # descendants started after the launch
        grew = False
        for p in procs:
            if p.parent in targets and p.pid not in targets:
                t = platform.start_time(p.pid)
                if t is not None and t >= launch_at - 1:
                    targets[p.pid] = p.name
                    grew = True
    names = []
    # The emulator first, RocketLauncher last, as a normal close does.
    for pid in sorted(targets, key=lambda k: targets[k].lower() == "rocketlauncher.exe"):
        if platform.terminate(pid):
            names.append(targets[pid])
    return names


def recover(config: Config, platform) -> Optional[RecoveryReport]:
    """Finish a run that didn't end (killed, crashed, power cut).  None when
    there is nothing to recover.  Raises :class:`_testrun.ActiveRunError`
    when the run is in fact still going.

    Each step is safe to repeat: close what the run left running (only
    programs whose PID, name *and* start time match the journal, and
    HyperSpin when the run opened it), put the play statistics back, mark
    the run interrupted (``--resume`` carries on), and clear the pointer to it."""
    active = _testrun.active_run()
    if active is None:
        return None
    run_dir = Path(active.get("run_dir") or "")
    worker = active.get("worker") or {}
    if platform is not None and worker.get("pid"):
        alive = {p.pid: p for p in platform.list_processes()}
        entry = {"pid": worker["pid"], "started": worker.get("started"),
                 "name": alive[worker["pid"]].name if worker["pid"] in alive else ""}
        if worker["pid"] in alive and _same_process(platform, alive, entry):
            raise _testrun.ActiveRunError(
                f"A test run is already running (process {worker['pid']}, {run_dir}).")
    report = RecoveryReport(run_dir)
    journal = Journal.load(run_dir / "journal.json")
    report.closed = _close_leftovers(platform, journal.data.get("current") or {})
    hs_entry = journal.data.get("hyperspin") or {}
    if platform is not None and hs_entry.get("started_by_us"):
        from . import gametest_hyperspin

        alive = {p.pid: p for p in platform.list_processes()}
        if hs_entry.get("pid") and _same_process(platform, alive, hs_entry):
            gametest_hyperspin.close(config, platform, hs_entry)
            report.closed.append("HyperSpin.exe")
        journal.data["hyperspin"] = {}
    stats = journal.data.get("stats") or {}
    manifest = Path(stats.get("manifest") or run_dir / "stats-backup" / "manifest.json")
    if not stats.get("restored", False) and manifest.is_file():
        rl_dir = Path(json.loads(manifest.read_text(encoding="utf-8")).get("rocketlauncher_dir")
                      or config.rocketlauncher_dir)
        report.stats_restored = restore_stats(rl_dir, manifest)
        report.messages.append("Put RocketLauncher's play statistics back.")
    swept = None
    clean = journal.data.get("cleanup") or {}
    if clean.get("mode") in ("report", "remove"):
        from .gametest_cleanup import Cleanup

        # No watcher survived the kill: a full listing against the saved baseline.
        cleaner = Cleanup(config, run_dir, clean["mode"], clean.get("roots") or [],
                          clean.get("skip") or [], since=clean.get("since") or 0)
        cleaner.finish("recovery")
        swept = cleaner.summary()
        verb = "removed" if clean["mode"] == "remove" else "found"
        report.messages.append(f"Checked for files the games created: {swept[verb]} {verb}.")
    if journal.data:
        journal.data.setdefault("stats", {})["restored"] = True
        journal.data["current"] = {}
        journal.data["cleanup"] = {}
        journal.save()
    if (run_dir / "run.json").is_file():
        info = read_run(run_dir)
        if swept is not None:
            info["cleanup"] = swept
        info["interrupted"] = True
        info["ended"] = info.get("ended") or datetime.now().isoformat(timespec="seconds")
        _save_run(run_dir, info)
        write_results_json(run_dir)
    _testrun.clear_active()
    return report


def as_dict(obj) -> dict:
    """A dataclass as JSON-ready data (for ``--json``)."""
    data = asdict(obj)
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in data.items()}
