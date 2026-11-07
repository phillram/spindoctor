"""Make HyperSpin's idle mode tour the consoles: ``spindoctor toolkit idle-tour``.

HyperSpin's own idle mode (``Settings\\Settings.ini`` ``[AttractMode]``
``Active=true``) starts after ``Time`` seconds with no input, spins the wheel
you are on at random and lets each video play to its end.  It never changes
wheels, so on the main menu it only ever shows the console videos.  This
helper runs beside HyperSpin, started with it from the HyperSpin Startup
Script (`install-tools --tool idle-tour --apply` adds it), and changes wheels
while that idle mode runs:

* after ``ConsoleMinutes`` or ``GamesPerConsole`` idle spins in a console,
  whichever comes first, it presses HyperSpin's Exit key, back to the main
  menu;
* after ``MainMenuMinutes`` or ``ConsolesOnMainMenu`` idle spins on the main
  menu, it presses Start on the console the spin landed on, unless that
  console is skipped (then it waits for the next spin).

HyperSpin's idle mode carries on in the new wheel by itself: its timer ignores
key presses sent by a program.  When a player uses a control, the idle mode
stops as it always has, and so does the tour.

**How it knows where HyperSpin is.**  HyperSpin rewrites ``log.txt`` (in its
own folder) at every start and appends to it live:

* ``<wheel> wheel loaded successfully``: a wheel change (logged again for the
  same wheel on a letter jump, which isn't one);
* ``"...\\LEDBlinky.exe" 9 "<console>" "Main Menu"``: a selection on the main
  menu; ``... 9 "<game>"``: a selection inside a console;
* ``"...\\LEDBlinky.exe" 5`` / ``6``: an idle spin starts / stops; the
  selection logged right after the ``6`` is where it landed;
* ``Launching Game``: a game start.

The selection and spin lines are HyperSpin's LEDBlinky calls, so they are only
there while ``[LEDBlinky] Active=true``.

**Safety.**  Exit on the main menu opens HyperSpin's exit menu, whose default
answer is Yes, and that menu logs nothing.  So the tour acts only right after
an idle spin has landed and the log has then been quiet for ``QuietMs``: the
landing shows where HyperSpin is (a game line in a console, a "Main Menu"
line on the main menu), and that no exit menu is open, because HyperSpin's
idle spins stop while it is.  Exit is pressed only in a console, Start only
on the main menu and only on a console the tour may open.  Each key is held
``KeyHoldMs`` (HyperSpin drops presses that go down and up at once).  Nothing
is pressed while RocketLauncher runs, while HyperSpin isn't the front window
or shows a pop-up, while a program named in ``PauseWhile`` runs, or once
anyone has used a control: Windows' last-input time newer than the tour's own
last press.  No keyboard or mouse hook is installed.

The Windows calls sit behind :class:`WindowsTourOps`, so the tests drive the
tour with a fake HyperSpin.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional

HYPERSPIN = "HyperSpin.exe"
ROCKETLAUNCHER = "RocketLauncher.exe"
MAIN_MENU = "Main Menu"
#: Written next to ``Idle Tour.bat`` by install-tools, and kept on a re-install.
SETTINGS_FILE = "Idle Tour settings.ini"
SECTION = "IdleTour"
POLL = 0.25          # seconds between looks at HyperSpin
GONE_MS = 10_000     # HyperSpin gone this long: the tour quits
SLACK_MS = 40        # Windows' last-input time may trail the tour's own press by this much
MUTEX = "Local\\SpinDoctorIdleTour"
#: Skipped unless the settings say otherwise: SpinDoctor's own lists of other
#: wheels' games, and the maintenance wheel.
DEFAULT_SKIP = ("Toolkit", "Favorites", "Most Played", "Recently Played")


# ─── settings ─────────────────────────────────────────────────────────────────

class Settings(NamedTuple):
    enabled: bool = True
    console_minutes: float = 5.0
    games_per_console: int = 5
    main_menu_minutes: float = 5.0
    consoles_on_main_menu: int = 5
    tour_max_minutes: float = 60.0
    skip: tuple = DEFAULT_SKIP
    pause_while: tuple = ()
    key_hold_ms: int = 80
    quiet_ms: int = 1500

    def skips(self, name: str) -> bool:
        want = name.strip().casefold()
        return any(s.casefold() == want for s in self.skip)

    def summary(self) -> str:
        def limit(minutes, count, what):
            parts = [f"{minutes:g} min" if minutes > 0 else "", f"{count} {what}" if count > 0 else ""]
            parts = [p for p in parts if p]
            return " or ".join(parts) if parts else "never"
        return (f"a console for {limit(self.console_minutes, self.games_per_console, 'games')}, "
                f"the main menu for {limit(self.main_menu_minutes, self.consoles_on_main_menu, 'consoles')}, "
                "whichever first; tour limit "
                + (f"{self.tour_max_minutes:g} min" if self.tour_max_minutes > 0 else "none")
                + f", {len(self.skip)} wheel(s) skipped")


#: The settings file install-tools writes when there is none.  Every key is
#: optional; a missing or unreadable value keeps the default.
DEFAULT_SETTINGS_TEXT = (
    "; Settings for SpinDoctor's idle tour (spindoctor toolkit idle-tour).\r\n"
    "; Read when the tour starts, which is when HyperSpin starts.\r\n"
    ";\r\n"
    "; HyperSpin's own idle mode does the spinning and waits for each video\r\n"
    "; (Settings\\Settings.ini [AttractMode] Active=true; Time= is how many idle\r\n"
    "; seconds before it starts). The tour only changes wheels while it runs.\r\n"
    "[IdleTour]\r\n"
    "; 0 switches the tour off without touching the Startup Script.\r\n"
    "Enabled=1\r\n"
    "; When to change wheels, whichever comes first (0 switches a limit off):\r\n"
    ";   in a console:     ConsoleMinutes, or GamesPerConsole games shown by idle spins;\r\n"
    ";   on the main menu: MainMenuMinutes, or ConsolesOnMainMenu consoles shown.\r\n"
    "; Counted from the first idle spin in that wheel; the change happens right\r\n"
    "; after the next spin lands (after 5 games, at the 6th spin).\r\n"
    "ConsoleMinutes=5\r\n"
    "GamesPerConsole=5\r\n"
    "MainMenuMinutes=5\r\n"
    "ConsolesOnMainMenu=5\r\n"
    "; The tour's key presses keep the screen awake. After this many minutes it\r\n"
    "; stops changing wheels, ending on the main menu, so Windows can turn the\r\n"
    "; screen off. It starts again after someone uses a control. 0 = never stop.\r\n"
    "TourMaxMinutes=60\r\n"
    "; Consoles it never opens (main-menu names, separated by |). Wheels with no\r\n"
    "; database are skipped too.\r\n"
    "Skip=" + "|".join(DEFAULT_SKIP) + "\r\n"
    "; Programs (EXE names, separated by |) during which it presses nothing.\r\n"
    "PauseWhile=\r\n"
    "; How long each key is held (HyperSpin drops shorter presses), and how long\r\n"
    "; the log must be quiet after a spin lands before it acts (milliseconds).\r\n"
    "KeyHoldMs=80\r\n"
    "QuietMs=1500\r\n"
)


def _number(raw: str, default, cast):
    try:
        value = cast(float(raw.strip()))
    except ValueError:
        return default
    return value if value >= 0 else default


def _names(raw: str) -> tuple:
    return tuple(n.strip() for n in raw.split("|") if n.strip())


def read_settings(path: Optional[Path]) -> Settings:
    """The settings in *path*'s ``[IdleTour]`` section, read the way Windows
    reads an INI (names in any case); defaults for anything missing or bad."""
    if path is None:
        return Settings()
    from .rocketlauncher import _read_rl_ini

    values = _read_rl_ini(Path(path)).get(SECTION.lower(), {})
    d = Settings()

    def num(key, default, cast=float):
        return _number(values[key], default, cast) if key in values else default

    return Settings(
        enabled=bool(num("enabled", 1, int)),
        console_minutes=num("consoleminutes", d.console_minutes),
        games_per_console=num("gamesperconsole", d.games_per_console, int),
        main_menu_minutes=num("mainmenuminutes", d.main_menu_minutes),
        consoles_on_main_menu=num("consolesonmainmenu", d.consoles_on_main_menu, int),
        tour_max_minutes=num("tourmaxminutes", d.tour_max_minutes),
        skip=_names(values["skip"]) if "skip" in values else d.skip,
        pause_while=_names(values.get("pausewhile", "")),
        key_hold_ms=num("keyholdms", d.key_hold_ms, int),
        quiet_ms=num("quietms", d.quiet_ms, int),
    )


class Keys(NamedTuple):
    """HyperSpin's Start and Exit keys, as Windows virtual-key codes."""
    start: int = 0x0D   # Enter
    exit: int = 0x1B    # Esc


def hyperspin_keys(hyperspin_dir) -> Keys:
    """Player 1's Start and Exit from HyperSpin's ``Settings\\Settings.ini``
    ``[P1 Controls]``, which stores them as virtual-key codes (Enter = 13,
    Esc = 27); Enter and Esc when unset."""
    d = Keys()
    if not hyperspin_dir:
        return d
    from .rocketlauncher import _read_rl_ini

    section = _read_rl_ini(Path(hyperspin_dir) / "Settings" / "Settings.ini").get("p1 controls", {})

    def vk(key, default):
        try:
            code = int(section.get(key, ""))
        except ValueError:
            return default
        return code if 0 < code < 255 else default

    return Keys(start=vk("start", d.start), exit=vk("exit", d.exit))


def hyperspin_setting(hyperspin_dir, section: str, key: str) -> str:
    """One value from HyperSpin's ``Settings\\Settings.ini``, or ``""``."""
    if not hyperspin_dir:
        return ""
    from .rocketlauncher import _rl_ini_value

    return _rl_ini_value(Path(hyperspin_dir) / "Settings" / "Settings.ini", section, key)


def single_mode(hyperspin_dir) -> str:
    """Why the tour can't run when HyperSpin is in single mode, or ``""``.

    With ``[Main] Menu_Mode=single`` HyperSpin shows one wheel and no main
    menu: the log never says "Main Menu", every wheel looks like a console,
    and Exit there opens the exit menu (or closes HyperSpin).
    """
    mode = hyperspin_setting(hyperspin_dir, "Main", "Menu_Mode").strip().lower()
    if mode == "single":
        return "HyperSpin is in single mode ([Main] Menu_Mode=single): there is no main menu to tour"
    return ""


def other_tours(items, own_target: str) -> "list[str]":
    """Startup Script targets, other than *own_target*, that look like another
    idle tour (``IdleTour.exe``, ``Idle Tour.ahk`` …): two tours would press
    keys over each other."""
    def squash(name):
        return re.sub(r"[\s_.-]+", "", name.strip().strip('"').lower())
    own = squash(own_target)
    return [e.target for e in items if e.target and squash(e.target) != own
            and "idletour" in squash(e.target)]


# ─── HyperSpin's log ──────────────────────────────────────────────────────────

_WHEEL = re.compile(r"\|\s+(.+?) wheel loaded successfully")
_SELECT = re.compile(r'LEDBlinky\.exe"\s+9\s+"([^"]*)"(?:\s+"([^"]*)")?', re.IGNORECASE)
_SPIN_START = re.compile(r'LEDBlinky\.exe"\s+5(?:\s|$)', re.IGNORECASE)
_SPIN_STOP = re.compile(r'LEDBlinky\.exe"\s+6(?:\s|$)', re.IGNORECASE)
_CALL = re.compile(r'LEDBlinky\.exe"\s+\d', re.IGNORECASE)


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


class HyperSpinLog:
    """What HyperSpin's ``log.txt`` says, read as it grows.

    The ``*_seq`` counters only go up, so a caller notes one and later sees
    whether anything of that kind was logged since.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.offset = 0
        self.tail = ""
        self.wheel = ""
        self.wheel_seq = 0
        self.selection = ""
        self.selection_on_main_menu = False
        self.selection_seq = 0
        self.launch_seq = 0
        self.spinning = False
        self.after_spin = False
        self.spin_seq = 0
        self.landing_seq = 0
        #: Every LEDBlinky call HyperSpin logs (also 4, 7 and 8, which come
        #: just before a wheel change), so a wait for quiet sees them.
        self.call_seq = 0

    def reset(self, path: Optional[Path] = None) -> None:
        """A new log (HyperSpin started again): read it from the start."""
        if path is not None:
            self.path = path
        self.offset, self.tail = 0, ""
        self.wheel, self.selection, self.selection_on_main_menu = "", "", False
        self.spinning = self.after_spin = False
        self.wheel_seq += 1
        self.selection_seq += 1

    def read(self) -> bool:
        """Take in what HyperSpin has written since the last read; False when
        the log can't be read."""
        if self.path is None:
            return False
        try:
            size = os.stat(self.path).st_size
            if size < self.offset:          # rewritten: HyperSpin started again
                self.reset()
            if size == self.offset:
                return True
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
        except OSError:
            return False
        self.offset += len(chunk)
        self.feed(chunk.decode("cp1252", errors="replace"))
        return True

    def feed(self, text: str) -> None:
        self.tail += text
        while "\n" in self.tail:
            line, self.tail = self.tail.split("\n", 1)
            self.parse_line(line.rstrip("\r "))

    def parse_line(self, line: str) -> None:
        if _CALL.search(line):
            self.call_seq += 1
        m = _WHEEL.search(line)
        if m:
            if not _same(m.group(1), self.wheel):  # the same wheel again is a letter jump
                self.wheel = m.group(1)
                self.wheel_seq += 1
            return
        m = _SELECT.search(line)
        if m:
            self.selection = m.group(1)
            self.selection_on_main_menu = _same(m.group(2) or "", MAIN_MENU)
            self.selection_seq += 1
            if self.after_spin:
                self.after_spin = False
                self.landing_seq += 1
            return
        if _SPIN_START.search(line):
            self.spinning, self.after_spin = True, False
            self.spin_seq += 1
            return
        if _SPIN_STOP.search(line):
            self.spinning, self.after_spin = False, True
            return
        if "launching game" in line.lower():
            self.launch_seq += 1

    @property
    def on_main_menu(self) -> bool:
        return _same(self.wheel, MAIN_MENU) and self.selection_on_main_menu

    @property
    def in_console(self) -> bool:
        return bool(self.wheel) and not _same(self.wheel, MAIN_MENU) and not self.selection_on_main_menu

    def where(self) -> str:
        return "the main menu" if self.on_main_menu else (
            self.wheel if self.in_console else "unknown")


# ─── the tour ─────────────────────────────────────────────────────────────────

class Tour:
    """The tour, one look at HyperSpin per :meth:`step`.

    *ops* is :class:`WindowsTourOps` or a test's fake; *log* takes one line.
    *hyperspin_dir* is the folder to use when the running HyperSpin's own
    can't be found (SpinDoctor's ``hyperspin_dir``).
    """

    def __init__(self, settings: Settings, ops, log: Callable[[str], None],
                 hyperspin_dir: str = "") -> None:
        self.s = settings
        self.ops = ops
        self._log = log
        self.fallback_dir = hyperspin_dir
        self.hs_dir = hyperspin_dir
        self.hs = HyperSpinLog(Path(hyperspin_dir) / "log.txt" if hyperspin_dir else None)
        self.keys = hyperspin_keys(hyperspin_dir)
        self.unusable = single_mode(hyperspin_dir)
        self.hs_pid = 0
        self.own_input = self._input_moment()
        self.phase_start: Optional[int] = None
        self.phase_landings = 0
        self.phase_wheel_seq = -1
        self.seen_landing_seq = 0
        self.session_start: Optional[int] = None
        self.suspended = False
        self.limit_reached = False

    def log(self, line: str) -> None:
        self._log(f"idle-tour: {line}")

    # ── the loop ──────────────────────────────────────────────────────────────

    def run(self) -> int:
        """Look at HyperSpin every :data:`POLL` s until it has been gone for
        :data:`GONE_MS`; then 0."""
        self.log(f"started ({self.s.summary()})")
        self.attach(self.ops.hyperspin_pid())
        gone_since: Optional[int] = None
        while True:
            self.ops.sleep(POLL)
            pid = self.ops.hyperspin_pid()
            if not pid:
                now = self.ops.tick()
                gone_since = now if gone_since is None else gone_since
                if now - gone_since >= GONE_MS:
                    self.log("HyperSpin closed, quitting")
                    return 0
                continue
            gone_since = None
            if pid != self.hs_pid:
                self.attach(pid)
            self.step()

    def attach(self, pid: int) -> None:
        """Follow the HyperSpin with process ID *pid*: its folder, log and keys."""
        if not pid:
            return
        first = not self.hs_pid
        self.hs_pid = pid
        exe = self.ops.image_path(pid)
        self.hs_dir = os.path.dirname(exe) if exe else self.fallback_dir
        self.keys = hyperspin_keys(self.hs_dir)
        self.unusable = single_mode(self.hs_dir)
        self.hs.reset(Path(self.hs_dir) / "log.txt" if self.hs_dir else None)
        self.hs.read()
        self.restart()
        if self.unusable:
            self.log(f"warning: {self.unusable}; the tour presses nothing")
        if first:
            active = hyperspin_setting(self.hs_dir, "AttractMode", "Active")
            if active.strip().lower() != "true":
                self.log("warning: HyperSpin's own idle mode is off (Settings.ini [AttractMode] "
                         f"Active={active or '(not set)'}): the tour does nothing without it")
            ledblinky = hyperspin_setting(self.hs_dir, "LEDBlinky", "Active")
            if ledblinky.strip().lower() != "true":
                self.log("warning: HyperSpin's LEDBlinky calls are off (Settings.ini [LEDBlinky] "
                         f"Active={ledblinky or '(not set)'}): its log then shows no selections "
                         "or idle spins, and the tour does nothing")

    def step(self) -> None:
        """One look: read the log, then change wheels if it is time."""
        hs, s = self.hs, self.s
        hs.read()
        if self.foreign_input():
            self.own_input = self._input_moment()
            if self.phase_start is not None or self.suspended or self.limit_reached:
                self.log("a control was used: waiting for HyperSpin's idle mode to start again")
            self.restart()
            return
        why = self.not_eligible()
        if why:
            if self.phase_start is not None:
                self.log(f"paused: {why}")
            self.restart()
            return
        if hs.wheel_seq != self.phase_wheel_seq:   # a new wheel: its time starts at its first idle spin
            self.phase_wheel_seq, self.phase_start = hs.wheel_seq, None
        if hs.landing_seq == self.seen_landing_seq:
            return
        self.seen_landing_seq = hs.landing_seq     # one of HyperSpin's idle spins has just landed
        if self.suspended:
            return
        now = self.ops.tick()
        if self.phase_start is None:
            self.phase_start, self.phase_landings = now, 1
            if self.session_start is None:
                self.session_start = now
            self.log(f"HyperSpin's idle mode is running in {hs.wheel}")
            return
        self.phase_landings += 1
        if self.limit_reached:
            return
        over = s.tour_max_minutes > 0 and now - self.session_start >= s.tour_max_minutes * 60_000
        on_menu = _same(hs.wheel, MAIN_MENU)
        if over and on_menu:
            self.limit_reached = True
            self.log("tour limit reached: HyperSpin's idle mode carries on on the main menu, "
                     "no more wheel changes until someone uses a control")
            return
        minutes, count = ((s.main_menu_minutes, s.consoles_on_main_menu) if on_menu
                          else (s.console_minutes, s.games_per_console))
        # Whichever comes first: the minutes, or `count` spins shown (it changes at the spin after).
        due = ((minutes > 0 and now - self.phase_start >= minutes * 60_000)
               or (count > 0 and self.phase_landings > count))
        if over or due:
            self.change_wheel()

    def restart(self) -> None:
        """Start counting again from HyperSpin's next idle spin."""
        self.phase_start = self.session_start = None
        self.suspended = self.limit_reached = False
        self.seen_landing_seq, self.phase_wheel_seq = self.hs.landing_seq, self.hs.wheel_seq

    def suspend(self, reason: str) -> None:
        self.suspended = True
        self.log(f"{reason}; pausing until someone uses a control")

    # ── checks ────────────────────────────────────────────────────────────────

    def _input_moment(self) -> int:
        """When Windows last saw keyboard or mouse input, on the tour's clock."""
        return self.ops.tick() - self.ops.idle_ms()

    def foreign_input(self) -> bool:
        """True when someone (not the tour) used a control since its last press."""
        return self._input_moment() > self.own_input + SLACK_MS

    def not_eligible(self) -> str:
        """Why no key may be pressed now, or ``""``."""
        if self.unusable:
            return self.unusable
        pids = self.ops.pids(HYPERSPIN)
        if not pids:
            return "HyperSpin isn't running"
        if self.ops.pids(ROCKETLAUNCHER):
            return "a game is running (RocketLauncher)"
        front, window_class = self.ops.foreground()
        if front not in pids:
            return "HyperSpin isn't the front window"
        if window_class == "#32770":
            return "a HyperSpin pop-up is open"
        for name in self.s.pause_while:
            exe = name if name.lower().endswith(".exe") else f"{name}.exe"
            if self.ops.pids(exe):
                return f"{exe} is running"
        return ""

    def clear(self) -> bool:
        """Nobody touching, HyperSpin usable, no idle spin under way."""
        return not self.foreign_input() and not self.not_eligible() and not self.hs.spinning

    def allowed(self, name: str) -> bool:
        """A console the tour may open: not skipped, and it has a database."""
        if not name or _same(name, MAIN_MENU) or self.s.skips(name) or not self.hs_dir:
            return False
        return (Path(self.hs_dir) / "Databases" / name / f"{name}.xml").is_file()

    def _activity(self) -> tuple:
        hs = self.hs
        return hs.selection_seq, hs.spin_seq, hs.wheel_seq, hs.launch_seq, hs.call_seq

    def quiet(self, ms: int) -> bool:
        """Wait *ms* with nobody touching and no LEDBlinky call, wheel or game
        in the log (HyperSpin logs 7 / 8 or 4 a second before it changes
        wheels, also for a Start or Exit Windows doesn't count as input)."""
        before = self._activity()
        end = self.ops.tick() + ms
        while self.ops.tick() < end:
            self.ops.sleep(0.1)
            self.hs.read()
            if not self.clear() or self._activity() != before:
                return False
        return True

    # ── keys ──────────────────────────────────────────────────────────────────

    def press(self, vk: int) -> bool:
        """Hold *vk* for ``KeyHoldMs``, if nothing stands in the way."""
        if not self.clear():
            return False
        self.ops.press(vk, self.s.key_hold_ms)
        self.ops.sleep(0.03)
        self.own_input = self._input_moment()
        return True

    def wait_wheel(self, name: str, timeout_ms: int) -> int:
        """After a key press: 1 once the log shows wheel *name* loaded, 0 after
        *timeout_ms* with nothing, -1 if something else happened (a player,
        another wheel or a game; the last two suspend the tour)."""
        hs = self.hs
        wheel0, launch0, start = hs.wheel_seq, hs.launch_seq, self.ops.tick()
        while True:
            self.ops.sleep(0.1)
            hs.read()
            if hs.launch_seq != launch0:
                self.suspend("!!! a game started after the tour's key press")
                return -1
            if hs.wheel_seq != wheel0:
                if _same(hs.wheel, name):
                    return 1
                self.suspend(f'the log shows "{hs.wheel}" instead of "{name}"')
                return -1
            if self.foreign_input():
                return -1
            if self.ops.tick() - start > timeout_ms:
                return 0

    def change_wheel(self) -> None:
        """Right after an idle spin landed, once this wheel's time or count is up.

        The fresh landing proves where HyperSpin is, and that its exit menu
        isn't open: HyperSpin's idle spins stop while it is.
        """
        if not self.quiet(self.s.quiet_ms):   # anything new: try again at the next spin
            return
        hs = self.hs
        what = f"{(self.ops.tick() - self.phase_start) / 60_000:.1f} min and {self.phase_landings} idle spins"
        if hs.in_console:
            name = hs.wheel
            if not self.press(self.keys.exit):
                return
            result = self.wait_wheel(MAIN_MENU, 15_000)
            if result == 1:
                self.log(f"back on the main menu after {what} in {name}")
            elif result == 0:
                # No second Exit until a new idle spin lands inside the console.
                self.log(f"Exit in {name} didn't bring the main menu within 15 s; "
                         "trying again after the next idle spin there")
            return
        if hs.on_main_menu:
            name = hs.selection
            if not self.allowed(name):
                self.log(f"main menu: the idle spin landed on {name} (skipped); waiting for the next spin")
                return
            if not self.press(self.keys.start):
                return
            result = self.wait_wheel(name, 30_000)
            if result == 1:
                self.log(f"opened {name} after {what} on the main menu")
            elif result == 0:
                self.log(f"Start on {name} didn't open it within 30 s; trying again after the next idle spin")
        # Neither: a wheel is loading or the log doesn't say. Wait for the next spin.

    # ── self-test ─────────────────────────────────────────────────────────────

    def self_test(self) -> "list[str]":
        """What the tour sees now, pressing nothing."""
        self.attach(self.ops.hyperspin_pid())
        hs, folder = self.hs, self.hs_dir
        if not self.hs_pid:
            hs.read()   # HyperSpin isn't running: what its last log says
        lines = [f"settings: {self.s.summary()}, key hold {self.s.key_hold_ms} ms"]
        lines.append(f"HyperSpin folder: {folder or '(not found: is HyperSpin running, or hyperspin_dir set?)'}")
        lines.append(f"HyperSpin's idle mode: Active={hyperspin_setting(folder, 'AttractMode', 'Active') or '?'}, "
                     f"Time={hyperspin_setting(folder, 'AttractMode', 'Time') or '?'}; "
                     f"LEDBlinky calls: Active={hyperspin_setting(folder, 'LEDBlinky', 'Active') or '?'}")
        lines.append(f"keys: Start = virtual key {self.keys.start}, Exit = virtual key {self.keys.exit}")
        missing = [n for n in self.s.skip
                   if not folder or not (Path(folder) / "Databases" / n / f"{n}.xml").is_file()]
        lines.append(f"skip list: {len(self.s.skip)} wheel(s)"
                     + (f" (no database, fine: {', '.join(missing)})" if missing else ""))
        lines.append(f'log: wheel "{hs.wheel}", selection "{hs.selection}" (main menu '
                     f'{"yes" if hs.selection_on_main_menu else "no"}), idle spins {hs.spin_seq}, '
                     f"landings {hs.landing_seq}, launches {hs.launch_seq}")
        lines.append(f"state: {hs.where()}, allowed now: {'yes' if self.allowed(hs.selection) else 'no'}, "
                     f"blocked by: {self.not_eligible() or 'nothing'}")
        return lines


def run(config, settings_path: Optional[Path] = None, *, self_test: bool = False,
        ops=None, log: Optional[Callable[[str], None]] = None,
        echo: Optional[Callable[[str], None]] = None) -> int:
    """``spindoctor toolkit idle-tour``: tour until HyperSpin closes.

    0 when HyperSpin closed, when switched off (``Enabled=0``) or when another
    copy already runs.  *self_test* reports what the tour sees and returns.
    """
    from .cabinet_power import log_to_file

    log = log or log_to_file
    echo = echo or (lambda line: None)
    settings = read_settings(settings_path)
    ops = ops or WindowsTourOps()
    tour = Tour(settings, ops, log, getattr(config, "hyperspin_dir", "") or "")
    if self_test:
        tour.log("---- self-test (no keys are pressed)")
        for line in tour.self_test():
            tour.log(line)
            echo(line)
        return 0
    if not settings.enabled:
        echo(f"The idle tour is switched off (Enabled=0 in {settings_path}).")
        return 0
    if not ops.single_instance(MUTEX):
        echo("The idle tour is already running.")
        return 0
    return tour.run()


# ─── Windows ──────────────────────────────────────────────────────────────────

#: Virtual keys Windows sends as "extended" (the arrow and editing block, etc.).
_EXTENDED = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,
                       0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5})


class WindowsTourOps:
    """The process, window, input and key calls the tour needs, through ``ctypes``."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        from .cabinet_power import WindowsOps

        self._procs = WindowsOps()
        self._c, self._w = ctypes, w
        u = self._u = ctypes.WinDLL("user32", use_last_error=True)
        k = self._k = ctypes.WinDLL("kernel32", use_last_error=True)

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                        ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                        ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]

        class _INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]

        self._LASTINPUTINFO, self._INPUT = LASTINPUTINFO, INPUT
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = w.HWND
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.GetWindowThreadProcessId.restype = w.DWORD
        u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        u.GetClassNameW.restype = ctypes.c_int
        u.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        u.GetLastInputInfo.restype = w.BOOL
        u.MapVirtualKeyW.argtypes = [w.UINT, w.UINT]
        u.MapVirtualKeyW.restype = w.UINT
        u.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        u.SendInput.restype = w.UINT
        k.GetTickCount.argtypes = []
        k.GetTickCount.restype = w.DWORD
        k.GetTickCount64.argtypes = []
        k.GetTickCount64.restype = ctypes.c_ulonglong
        k.CreateMutexW.argtypes = [w.LPVOID, w.BOOL, w.LPCWSTR]
        k.CreateMutexW.restype = w.HANDLE
        self._mutex = None

    def pids(self, name: str) -> "list[int]":
        return self._procs.pids(name)

    def hyperspin_pid(self) -> int:
        pids = self._procs.pids(HYPERSPIN)
        return pids[0] if pids else 0

    def image_path(self, pid: int) -> Optional[str]:
        return self._procs.image_path(pid)

    def foreground(self) -> "tuple[int, str]":
        """The front window's process ID and window class."""
        hwnd = self._u.GetForegroundWindow()
        if not hwnd:
            return 0, ""
        pid = self._w.DWORD()
        self._u.GetWindowThreadProcessId(hwnd, self._c.byref(pid))
        buf = self._c.create_unicode_buffer(256)
        self._u.GetClassNameW(hwnd, buf, 256)
        return pid.value, buf.value

    def tick(self) -> int:
        return int(self._k.GetTickCount64())

    def idle_ms(self) -> int:
        """Milliseconds since the last keyboard or mouse input (any program's)."""
        info = self._LASTINPUTINFO()
        info.cbSize = self._c.sizeof(info)
        if not self._u.GetLastInputInfo(self._c.byref(info)):
            return 0
        return (self._k.GetTickCount() - info.dwTime) & 0xFFFFFFFF

    def _key(self, vk: int, up: bool) -> None:
        inp = self._INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.u.ki.wVk = vk
        inp.u.ki.wScan = self._u.MapVirtualKeyW(vk, 0) & 0xFFFF  # MAPVK_VK_TO_VSC
        inp.u.ki.dwFlags = (0x0001 if vk in _EXTENDED else 0) | (0x0002 if up else 0)
        self._u.SendInput(1, self._c.byref(inp), self._c.sizeof(inp))

    def press(self, vk: int, hold_ms: int) -> None:
        """Key down, held *hold_ms*, then up (also if anything goes wrong)."""
        self._key(vk, up=False)
        try:
            time.sleep(hold_ms / 1000)
        finally:
            self._key(vk, up=True)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def single_instance(self, name: str) -> bool:
        """Hold the named mutex; False if another process already does."""
        self._mutex = self._k.CreateMutexW(None, False, name)
        if not self._mutex:   # e.g. access denied: an elevated copy holds it
            return False
        return self._c.get_last_error() != 183  # ERROR_ALREADY_EXISTS
