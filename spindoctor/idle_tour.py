"""Make HyperSpin's idle mode tour the consoles: ``spindoctor toolkit idle-tour``.

HyperSpin's own idle mode (``Settings\\Settings.ini`` ``[AttractMode]``
``Active=true``) starts after ``Time`` seconds with no input, spins the wheel
you are on at random and lets each video play to its end.  It never changes
wheels, so on the main menu it only ever shows the console videos.  This
helper runs beside HyperSpin, started with it from the HyperSpin Startup
Script (`install-tools --tool idle-tour --apply` adds it), and changes wheels
while that idle mode runs:

* in a console, after ``GamesPerConsole`` games (the first one shown after
  the tour opened it counts) or ``ConsoleMinutes``, whichever comes first, it
  presses HyperSpin's Exit key, back to the main menu, as the last game's
  video ends;
* on the main menu, after ``ConsolesOnMainMenu`` consoles shown by idle spins
  or ``MainMenuMinutes``, it presses Start on the console whose video just
  played, as that video ends.  Skipped consoles count but are never opened
  (it waits for the next one).

"As the video ends" is ``EndMarginMs`` before its end, from the length in the
``.mp4`` file: HyperSpin spins as soon as a video ends and swallows keys
mid-spin.  The minutes are checked against "now + this video's length".
With no length (a file it can't read), or when the video ends sooner than
its file says (a spin starts first), it changes right after the next spin
lands instead.

An item with no video at all (no ``.mp4`` or ``.flv``: none, or only a
still) would hold HyperSpin's idle mode for its whole ``Time`` before the
next spin.  After ``NoVideoSeconds`` the tour presses HyperSpin's Down key
once instead, and the item that brings up counts like any other; if the
item with no video was the last one, it changes wheels then.  HyperSpin
plays the new item's video and spins as it ends, as after its own spins;
should it not spin within 5 s of that video's end, the tour presses Down
again.

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
answer is Yes, and that menu logs nothing.  So the tour presses only while the
item's video plays and nothing has been logged since the item appeared (no
spin, LEDBlinky call, selection, wheel or game), or right after an idle spin
has landed and the log has then been quiet for ``QuietMs``.  The item's own
selection line (an idle-spin landing, or the first game after the tour's own
Start) shows where HyperSpin is (a game line in a console, a "Main Menu" line
on the main menu), and that no exit menu is open, because HyperSpin's idle
spins stop while it is.  Exit is pressed only in a console, Start only on the
main menu and only on a console the tour may open.  Down only moves the
wheel one step, wherever it is, and gets the same checks.  Each key is held
``KeyHoldMs`` (HyperSpin drops presses that go down and up at once).  Nothing
is pressed while RocketLauncher runs, while HyperSpin isn't the front window
or shows a pop-up, while a program named in ``PauseWhile`` runs, or once
anyone has used a control: Windows' last-input time newer than the tour's own
last press.  No keyboard or mouse hook is installed.  A joystick HyperSpin
reads itself (``[P1 Joystick] Enabled=true``) doesn't move that time, so with
one the tour never presses as a video ends, only right after a spin lands,
and presses no Down past items with no video.

The Windows calls sit behind :class:`WindowsTourOps`, so the tests drive the
tour with a fake HyperSpin.
"""
from __future__ import annotations

import math
import os
import re
import struct
import time
from pathlib import Path, PureWindowsPath
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
    tour_max_minutes: float = 0.0       # 0 = never stop
    skip: tuple = DEFAULT_SKIP
    pause_while: tuple = ()
    key_hold_ms: int = 80
    quiet_ms: int = 1500
    end_margin_ms: int = 1500
    no_video_seconds: float = 8.0

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
                "whichever first; "
                + (f"tour limit {self.tour_max_minutes:g} min" if self.tour_max_minutes > 0
                   else "no tour limit")
                + f", {len(self.skip)} wheel(s) skipped, "
                + (f"Down past items with no video after {self.no_video_seconds:g} s"
                   if self.no_video_seconds > 0 else "no Down past items with no video"))


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
    "; SpinDoctor's GUI (Custom Wheels tab) and spindoctor toolkit\r\n"
    "; idle-tour-settings change these values; comments and other lines stay.\r\n"
    "Enabled=1\r\n"
    "; When to change wheels, whichever comes first (0 switches a limit off):\r\n"
    ";   in a console:     GamesPerConsole games (the first one shown after the\r\n"
    ";                     tour opened it counts), or ConsoleMinutes;\r\n"
    ";   on the main menu: ConsolesOnMainMenu consoles shown by idle spins, or\r\n"
    ";                     MainMenuMinutes.\r\n"
    "; The change happens just as the last one's video ends (EndMarginMs before,\r\n"
    "; from the .mp4 or .flv length): Exit in a console, and on the main menu Start\r\n"
    "; on the console whose video just played. Skipped consoles count but are never\r\n"
    "; opened. If a video's length can't be read it changes right after the next\r\n"
    "; spin lands.\r\n"
    "ConsoleMinutes=5\r\n"
    "GamesPerConsole=5\r\n"
    "MainMenuMinutes=5\r\n"
    "ConsolesOnMainMenu=5\r\n"
    "; Tour limit. 0 = never stop: it tours for as long as HyperSpin's idle mode\r\n"
    "; runs. With a number of minutes it stops changing wheels after that long,\r\n"
    "; ending on the main menu, so Windows can turn the screen off (the tour's key\r\n"
    "; presses count as input to Windows). It starts again after someone uses a\r\n"
    "; control.\r\n"
    "TourMaxMinutes=0\r\n"
    "; Consoles it never opens (main-menu names, separated by |). Wheels with no\r\n"
    "; database are skipped too.\r\n"
    "Skip=" + "|".join(DEFAULT_SKIP) + "\r\n"
    "; Programs (EXE names, separated by |) during which it presses nothing.\r\n"
    "PauseWhile=\r\n"
    "; A game or console with no video (none, or only a still): HyperSpin's idle\r\n"
    "; mode would sit on it for its whole idle time (Time=) before the next spin.\r\n"
    "; After this many seconds the tour presses Down once, to the next one, which\r\n"
    "; counts like any other (if it was the last one, it changes wheels then).\r\n"
    "; 0 = wait for HyperSpin.\r\n"
    "NoVideoSeconds=8\r\n"
    "; Milliseconds: how long each key is held (HyperSpin drops shorter presses);\r\n"
    "; how long the log must be quiet after a spin lands before it acts on it (the\r\n"
    "; fallback); how long before a video's end it changes wheels.\r\n"
    "KeyHoldMs=80\r\n"
    "QuietMs=1500\r\n"
    "EndMarginMs=1500\r\n"
)


def _number(raw: str, default, cast):
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    # "inf" or "1e999" would make int() raise; "nan" compares false with everything.
    return cast(value) if math.isfinite(value) and value >= 0 else default


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
        end_margin_ms=num("endmarginms", d.end_margin_ms, int),
        no_video_seconds=num("novideoseconds", d.no_video_seconds),
    )


# ─── changing the settings ────────────────────────────────────────────────────

class Editable(NamedTuple):
    """A setting SpinDoctor's GUI and `toolkit idle-tour-settings` change."""
    key: str        # as the settings file spells it
    field: str      # the Settings field
    kind: str       # "flag", "count", "minutes", "seconds" or "names"


#: In the order the GUI shows them.
EDITABLE: tuple = (
    Editable("Enabled", "enabled", "flag"),
    Editable("GamesPerConsole", "games_per_console", "count"),
    Editable("ConsoleMinutes", "console_minutes", "minutes"),
    Editable("ConsolesOnMainMenu", "consoles_on_main_menu", "count"),
    Editable("MainMenuMinutes", "main_menu_minutes", "minutes"),
    Editable("TourMaxMinutes", "tour_max_minutes", "minutes"),
    Editable("NoVideoSeconds", "no_video_seconds", "seconds"),
    Editable("Skip", "skip", "names"),
)


def _setting_value(kind: str, value):
    """*value* checked and in its :class:`Settings` form; ``ValueError`` if the
    settings file can't hold it."""
    if kind == "flag":
        return bool(value)
    if kind == "names":
        names = (value,) if isinstance(value, str) else tuple(value)
        if any("\r" in n or "\n" in n for n in names):
            raise ValueError("a console name can't hold a line break")
        unique: dict = {}
        for name in _names("|".join(names)):      # each once, ignoring case, as the tour reads them
            unique.setdefault(name.casefold(), name)
        return tuple(unique.values())
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{value!r} isn't a number")
    if number < 0:
        raise ValueError(f"{number:g} is below 0 (0 switches it off)")
    return int(number) if kind == "count" else number


def _same_setting(kind: str, a, b) -> bool:
    """The tour reads *a* and *b* the same way (``Skip`` is a set, any case)."""
    if kind == "names":
        return {n.casefold() for n in a} == {n.casefold() for n in b}
    return a == b


def setting_text(kind: str, value) -> str:
    """*value* the way the settings file writes it."""
    if kind == "flag":
        return "1" if value else "0"
    if kind == "names":
        return "|".join(value)
    return f"{int(value)}" if kind == "count" else f"{float(value):.10g}"


_VALUE = re.compile(r"([^=]*=[ \t]*)(.*?)([ \t]*(?:\r\n|\n|\r)?)\Z", re.DOTALL)


def set_settings_text(text: str, values: "dict[str, str]") -> str:
    """*text* with ``key=value`` for each of *values* set where the tour reads
    it (:func:`read_settings`): the first such key, in any case, in an
    ``[IdleTour]`` section.  Only those lines change, and only their value:
    the key's spelling, the spacing and the line end stay.  A key that isn't
    there yet goes after the first ``[IdleTour]`` section's last line, and a
    missing section at the end, in the file's own line ends.  *text* has no
    BOM (:func:`spindoctor._text.read_editable_text`).
    """
    lines = text.splitlines(keepends=True)
    eol = "\n" if "\n" in text and "\r\n" not in text else "\r\n"
    todo = {key.lower(): (key, value) for key, value in values.items()}
    seen: set = set()
    first_end: Optional[int] = None    # after the first [IdleTour] section's last line
    ours = in_first = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and "]" in s:
            ours = s[1:s.rindex("]")].strip().lower() == SECTION.lower()
            in_first = ours and first_end is None
            if in_first:
                first_end = i + 1
            continue
        if in_first and s:
            first_end = i + 1
        if not ours or "=" not in s or s.startswith((";", "#", "<")):
            continue
        key = s.split("=", 1)[0].strip().lower()
        if key in seen:                 # a later copy: the first one wins
            continue
        seen.add(key)
        if key in todo:
            m = _VALUE.match(line)
            lines[i] = m.group(1) + todo.pop(key)[1] + m.group(3)
    if todo:
        added = "".join(f"{key}={value}{eol}" for key, value in todo.values())
        if first_end is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += eol
            lines.append(f"[{SECTION}]{eol}{added}")
        else:
            if not lines[first_end - 1].endswith(("\n", "\r")):
                lines[first_end - 1] += eol
            lines.insert(first_end, added)
    return "".join(lines)


class SettingChange(NamedTuple):
    key: str
    old: str
    new: str


def change_settings(path: Path, **changes) -> "list[SettingChange]":
    """Set the :data:`EDITABLE` fields in *changes* (``games_per_console=10``,
    ``skip=("Toolkit", "MAME")`` …) in the settings file *path*.

    Every other byte of the file stays (encoding, BOM, comments, other keys,
    line ends).  Returns what changed; a value the tour already reads that
    way isn't written.  Raises ``OSError`` when the file can't be read or
    written, ``ValueError`` for a value it can't hold, and
    ``UnicodeEncodeError`` for a name its encoding can't hold.
    """
    from ._text import read_editable_text, write_windows_text

    fields = {e.field: e for e in EDITABLE}
    unknown = sorted(set(changes) - set(fields))
    if unknown:
        raise TypeError(f"not an idle tour setting: {', '.join(unknown)}")
    text = read_editable_text(Path(path))
    current = read_settings(Path(path))
    made, values = [], {}
    for e in EDITABLE:
        if e.field not in changes:
            continue
        new = _setting_value(e.kind, changes[e.field])
        old = getattr(current, e.field)
        if _same_setting(e.kind, new, _setting_value(e.kind, old)):
            continue
        values[e.key] = setting_text(e.kind, new)
        made.append(SettingChange(e.key, setting_text(e.kind, old), values[e.key]))
    if values:
        write_windows_text(Path(path), set_settings_text(text, values))
    return made


def settings_location(config) -> Optional[Path]:
    """The settings file the installed tour reads.

    ``Idle Tour settings.ini`` beside the ``Idle Tour.bat`` that HyperSpin's
    Startup Script starts (install-tools may have written it to any
    ``--output-dir``), else in install-tools' default folder,
    ``<rocketlauncher_dir>\\Modules\\HyperLaunch\\Tools\\spindoctor``;
    ``None`` with neither.  The file itself may not exist yet.
    """
    from . import startup_script as ss
    from . import toolkit_helpers as th
    from ._text import read_editable_text

    bat_name = f"{th.find('idle-tour').name}.bat"
    script = ss.find(getattr(config, "hyperspin_dir", "") or "")
    if script.path is not None:
        try:
            items = ss.entries(read_editable_text(script.path))
        except OSError:
            items = []
        for entry in items:
            target = entry.target.strip().strip('"')
            if PureWindowsPath(target).name.lower() != bat_name.lower():
                continue
            # The Startup Script runs each entry from its folder, its own when relative;
            # the .bat reads the settings beside itself (%~dp0).
            folder = Path(entry.working_dir.strip().strip('"') or ".")
            if not folder.is_absolute():
                folder = script.path.parent / folder
            bat = Path(target) if Path(target).is_absolute() else folder / target
            return bat.parent / SETTINGS_FILE
    rl = getattr(config, "rocketlauncher_dir", "") or ""
    if rl:
        return Path(rl) / "Modules" / "HyperLaunch" / "Tools" / "spindoctor" / SETTINGS_FILE
    return None


class Keys(NamedTuple):
    """HyperSpin's Start, Exit and Down keys, as Windows virtual-key codes."""
    start: int = 0x0D   # Enter
    exit: int = 0x1B    # Esc
    down: int = 0x28    # the down arrow


def hyperspin_keys(hyperspin_dir) -> Keys:
    """Player 1's Start, Exit and Down from HyperSpin's ``Settings\\Settings.ini``
    ``[P1 Controls]``, which stores them as virtual-key codes (Enter = 13,
    Esc = 27, the down arrow = 40); those when unset."""
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

    return Keys(start=vk("start", d.start), exit=vk("exit", d.exit), down=vk("down", d.down))


def hyperspin_setting(hyperspin_dir, section: str, key: str) -> str:
    """One value from HyperSpin's ``Settings\\Settings.ini``, or ``""``."""
    if not hyperspin_dir:
        return ""
    from .rocketlauncher import _rl_ini_value

    return _rl_ini_value(Path(hyperspin_dir) / "Settings" / "Settings.ini", section, key)


def own_joystick(hyperspin_dir) -> str:
    """The joystick HyperSpin reads itself (``[P1 Joystick]`` … with
    ``Enabled=true``), as "P1 Joystick", or ``""``.

    Windows' last-input time doesn't see those presses, so the tour can't
    tell someone is playing: a joystick Exit on the main menu opens the exit
    menu (default Yes) without a word in the log.  With one, the tour changes
    wheels only right after an idle spin lands, which proves HyperSpin's idle
    mode is still running, never as a video ends, and presses no Down.
    """
    if not hyperspin_dir:
        return ""
    from .rocketlauncher import _read_rl_ini

    for name, values in _read_rl_ini(Path(hyperspin_dir) / "Settings" / "Settings.ini").items():
        if name.endswith("joystick") and values.get("enabled", "").strip().lower() == "true":
            return name.title()
    return ""


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


class Activity(NamedTuple):
    """The log's counters at one moment: any of them moving means something
    happened since."""
    selection: int
    spin: int
    wheel: int
    launch: int
    call: int


def flv_seconds(path: Path) -> Optional[float]:
    """An ``.flv``'s length from its ``onMetaData`` header: the AMF0 number
    after ``duration`` (marker 0, then an 8-byte big-endian double), in the
    first 2 KB.  ``None`` when it isn't there or can't be read."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(2048)
    except OSError:
        return None
    if len(head) < 64 or head[:3] != b"FLV":
        return None
    at = head.find(b"duration\x00")
    if at < 0 or at + 17 > len(head):
        return None
    (seconds,) = struct.unpack(">d", head[at + 9:at + 17])
    return seconds if 0 < seconds < 36_000 else None


def _video_folder(hs: Path, wheel: str) -> Path:
    """:meth:`Tour.video_folder`, uncached."""
    from .rocketlauncher import _rl_ini_value

    raw = _rl_ini_value(hs / "Settings" / f"{wheel}.ini", "video defaults", "path")
    raw = raw.strip().strip('"').replace("\\", "/").rstrip("/")
    if raw:
        if re.match(r"[A-Za-z]:/|//", raw) or Path(raw).is_absolute():
            candidates = [Path(raw)]
        else:
            rel = re.sub(r"^(\./)+", "", raw)
            candidates = [hs / "Media" / rel, hs / rel]
        for folder in candidates:
            if folder.is_dir():
                return folder
    return hs / "Media" / wheel / "Video"


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
        self.joystick = own_joystick(hyperspin_dir)
        self.hs_pid = 0
        self.own_input = self._input_moment()
        self.phase_start: Optional[int] = None
        #: Items (games, or consoles on the main menu) shown in this wheel.
        self.phase_count = 0
        self.phase_wheel_seq = -1
        self.seen_landing_seq = 0
        self.session_start: Optional[int] = None
        self.suspended = False
        self.limit_reached = False
        #: What the log had counted when the item on screen appeared.
        self.item = self._activity()
        #: Change wheels at this tick, just before the item's video ends …
        self.act_at: Optional[int] = None
        #: … or right after the next idle spin lands (no video length).
        self.act_at_landing = False
        #: Press Down at this tick: past an item with no video, or after the
        #: tour's own Down when HyperSpin didn't spin as the video ended.
        self.step_at: Optional[int] = None
        self._video_dirs: dict = {}

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
        self.joystick = own_joystick(self.hs_dir)
        self._video_dirs = {}
        self.hs.reset(Path(self.hs_dir) / "log.txt" if self.hs_dir else None)
        self.hs.read()
        self.restart()
        if self.unusable:
            self.log(f"warning: {self.unusable}; the tour presses nothing")
        elif self.joystick:
            self.log(f"note: HyperSpin reads the {self.joystick} itself ([{self.joystick}] Enabled=true), "
                     "which Windows doesn't count as input, so the tour changes wheels only right "
                     "after an idle spin lands, never as a video ends, and presses no Down past "
                     "items with no video")
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
        hs = self.hs
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
        if hs.wheel_seq != self.phase_wheel_seq:   # the wheel changed by itself: counted from its next idle spin
            self.phase_wheel_seq = hs.wheel_seq
            self._new_phase()
        if self.suspended or self.limit_reached:
            self.seen_landing_seq = hs.landing_seq
            return
        if hs.landing_seq != self.seen_landing_seq:   # one of HyperSpin's idle spins has just landed
            self.seen_landing_seq = hs.landing_seq
            if self.act_at_landing:                   # the fallback: change wheels right after this landing
                self.act_at_landing = False
                self.landed_when_due()
                return
            if self.phase_start is None:
                self.phase_start, self.phase_count = self.ops.tick(), 0
                if self.session_start is None:
                    self.session_start = self.phase_start
                self.log(f"HyperSpin's idle mode is running in {hs.wheel}")
            self.phase_count += 1
            self.new_item()
            return
        if self.act_at is not None:
            if hs.spin_seq != self.item.spin:         # the video ended sooner than its file says
                self.act_at, self.act_at_landing = None, True
                self.log("  the video ended early; changing wheels right after the next spin lands")
            elif self.ops.tick() >= self.act_at:
                self.act_at = None
                self.change_wheel(after_landing=False)
        if self.step_at is not None:
            if hs.spin_seq != self.item.spin or hs.selection_seq != self.item.selection:
                self.step_at = None                   # HyperSpin moved on by itself
            elif self.ops.tick() >= self.step_at:
                self.step_at = None
                self.step_past()

    def new_item(self, stepped: bool = False) -> None:
        """A new item is on screen (a game in a console, a console on the main
        menu), its video just starting.

        If it is this wheel's last (the count is reached, or the minutes will
        be up by the end of its video), plan the change for just before its
        video ends: HyperSpin spins as soon as a video ends and swallows keys
        mid-spin.  With no video length: right after the next spin lands.

        An item with no video gets a Down after ``NoVideoSeconds`` (or, if it
        is the last, the change then).  *stepped*: the tour's own Down
        brought this item up; should HyperSpin not spin within 5 s of its
        video's end, Down again.  No Down with a joystick HyperSpin reads
        itself (see :meth:`down_past_no_video`).
        """
        hs, s = self.hs, self.s
        now = self.ops.tick()
        self.item, self.act_at, self.act_at_landing, self.step_at = self._activity(), None, False, None
        on_menu = _same(hs.wheel, MAIN_MENU)
        wheel = MAIN_MENU if on_menu else hs.wheel
        missing = not self.has_video(wheel, hs.selection)
        no_video = self.down_past_no_video() and missing
        seconds = self.video_seconds(wheel, hs.selection)
        wait_s = self._no_video_wait()
        step_at = None
        if no_video:
            step_at = now + int(wait_s * 1000)
        elif stepped and self.down_past_no_video() and seconds > 0:
            step_at = now + int((seconds + 5) * 1000)
        stepping = f"stepping on in {wait_s:g} s"
        due = False
        if self._over(now):
            if on_menu:
                self._stop_at_limit()
                return
            due = True                                # inside a console: back to the main menu first
        if on_menu and not self.allowed(hs.selection):
            self.step_at = step_at
            self.log(f"main menu: console {self.phase_count} is {hs.selection} (skipped, not opened"
                     + (f"; no video, {stepping}" if no_video else "") + ")")
            return
        minutes, count = ((s.main_menu_minutes, s.consoles_on_main_menu) if on_menu
                          else (s.console_minutes, s.games_per_console))
        started = self.phase_start if self.phase_start is not None else now
        if count > 0 and self.phase_count >= count:
            due = True
        if minutes > 0 and now - started + seconds * 1000 >= minutes * 60_000:
            due = True
        what = (f"main menu: console {self.phase_count} is {hs.selection}" if on_menu
                else f"  {hs.wheel}: game {self.phase_count} is {hs.selection}")
        if not due:
            self.step_at = step_at
            self.log(what + (f" (no video: {stepping})" if no_video else ""))
        elif seconds > 0 and not self.joystick:
            self.act_at = max(now + int(seconds * 1000) - s.end_margin_ms, now + 2000)
            self.log(f"{what} ({seconds:g} s): {'opening it' if on_menu else 'leaving'} as its video ends")
        elif no_video:
            self.act_at = now + int(wait_s * 1000)
            self.log(f"{what} (no video): {'opening it' if on_menu else 'leaving'} in {wait_s:g} s")
        else:
            # No length, or a joystick: the change waits for a spin to land.
            self.act_at_landing = True
            why = ("no video, joystick" if self.joystick and missing
                   else "joystick" if self.joystick and seconds else "video length unknown")
            self.log(f"{what} ({why}): "
                     + ("opening the console the next spin lands on" if on_menu
                        else "leaving right after the next spin lands"))

    def landed_when_due(self) -> None:
        """An idle spin landed while a wheel change waits for one (no video
        length, a video that ended early, or a press that didn't happen).

        In a console: Exit.  On the main menu: Start on the console it landed
        on; a skipped one counts, and the wait goes on to the next spin (or,
        when it has no video, to the item a Down brings up).
        """
        hs = self.hs
        now = self.ops.tick()
        self.step_at = None                           # a new item: no Down left over from the last one
        if hs.on_main_menu and self._over(now):
            self._stop_at_limit()                     # don't open one more console past the limit
            return
        if hs.on_main_menu and not self.allowed(hs.selection):
            self.phase_count += 1
            self.item, self.act_at_landing = self._activity(), True
            what = f"main menu: console {self.phase_count} is {hs.selection} (skipped, not opened"
            if self.down_past_no_video() and not self.has_video(MAIN_MENU, hs.selection):
                self.step_at = now + int(self._no_video_wait() * 1000)
                self.log(f"{what}; no video): stepping on in {self._no_video_wait():g} s")
            else:
                self.log(f"{what}); waiting for the next spin")
            return
        self.change_wheel(after_landing=True)

    def down_past_no_video(self) -> bool:
        """Whether the tour presses Down past items with no video.

        Not with ``NoVideoSeconds=0``, and not with a joystick HyperSpin reads
        itself: a player's joystick Exit opens the exit menu without a word in
        the log or to Windows, and a Down there would move its highlight
        (back onto Yes, in a menu that wraps)."""
        return self.s.no_video_seconds > 0 and not self.joystick

    def _no_video_wait(self) -> float:
        """Seconds on an item with no video before the Down (or the change):
        ``NoVideoSeconds``, but at least 2, as for a press as a video ends."""
        return max(self.s.no_video_seconds, 2.0)

    def _over(self, now: int) -> bool:
        """Past ``TourMaxMinutes`` since this tour began."""
        limit = self.s.tour_max_minutes
        return limit > 0 and self.session_start is not None and now - self.session_start >= limit * 60_000

    def _stop_at_limit(self) -> None:
        self.limit_reached = True
        self.log("tour limit reached: HyperSpin's idle mode carries on on the main menu, "
                 "no more wheel changes until someone uses a control")

    def _new_phase(self) -> None:
        """A new wheel: its count starts at its next idle spin."""
        self.phase_start, self.phase_count = None, 0
        self.act_at, self.act_at_landing, self.step_at = None, False, None

    def restart(self) -> None:
        """Start counting again from HyperSpin's next idle spin."""
        self._new_phase()
        self.session_start = None
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

    def _activity(self) -> "Activity":
        hs = self.hs
        return Activity(hs.selection_seq, hs.spin_seq, hs.wheel_seq, hs.launch_seq, hs.call_seq)

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

    def change_wheel(self, after_landing: bool) -> None:
        """Exit in a console, Start on an allowed console on the main menu.

        *after_landing*: right after an idle spin landed (the fallback), once
        the log has been quiet for ``QuietMs``.  Otherwise just before the
        item's video ends, and only if nothing at all has been logged since
        the item appeared: no spin, LEDBlinky call, selection, wheel or game
        (HyperSpin logs 8 and 7, or 4, a second before it changes wheels,
        also for a Start or Exit Windows doesn't see).  Either way the item's
        own selection line (an idle-spin landing, or the first game after the
        tour's Start) proves where HyperSpin is, and that its exit menu isn't
        open: HyperSpin's idle spins stop while it is.
        """
        hs = self.hs
        if after_landing:
            if not self.quiet(self.s.quiet_ms):   # anything new: try again after the next spin
                self.act_at_landing = True
                return
            self.item = self._activity()
        hs.read()
        if hs.spin_seq != self.item.spin or hs.spinning:   # a spin began: right after it lands
            self.act_at_landing = True
            return
        if self._activity() != self.item or not self.quiet(300):
            return                                          # something moved: leave it to the next item
        started = self.phase_start if self.phase_start is not None else self.ops.tick()
        what = f"{(self.ops.tick() - started) / 60_000:.1f} min, {self.phase_count}"
        if hs.in_console:
            name = hs.wheel
            if not self.press(self.keys.exit):
                return
            result = self.wait_wheel(MAIN_MENU, 15_000)
            if result == 1:
                self.log(f"back on the main menu after {what} games in {name}")
                self.phase_wheel_seq, self.seen_landing_seq = hs.wheel_seq, hs.landing_seq
                self._new_phase()
            elif result == 0:
                # No second Exit until a new idle spin lands inside the console (a game line).
                self.log(f"Exit in {name} didn't bring the main menu within 15 s; "
                         "trying again after the next idle spin there")
                self.act_at_landing = True
            return
        if hs.on_main_menu:
            name = hs.selection
            if not self.allowed(name):
                self.log(f"main menu: the idle spin landed on {name} (skipped, not opened)")
                return
            if not self.press(self.keys.start):
                return
            result = self.wait_wheel(name, 30_000)
            if result == 0:
                self.log(f"Start on {name} didn't open it within 30 s; trying again after the next idle spin")
                self.act_at_landing = True
                return
            if result != 1:
                return
            self.log(f"opened {name} after {what} consoles on the main menu")
            # Its first game, shown once the wheel has loaded, is game 1 of this console.
            start = self.ops.tick()
            while not (hs.in_console and _same(hs.wheel, name)):
                if self.ops.tick() - start > 15_000 or self.foreign_input():
                    return
                self.ops.sleep(0.1)
                hs.read()
            self.phase_wheel_seq, self.seen_landing_seq = hs.wheel_seq, hs.landing_seq
            self.phase_start, self.phase_count = self.ops.tick(), 1
            self.new_item()
        # Neither: a wheel is loading or the log doesn't say. Wait for the next spin.

    def step_past(self) -> None:
        """Down: past an item with no video, or after the tour's own Down when
        HyperSpin didn't spin as the video ended.  The item it brings up
        counts like one an idle spin landed on.

        Down only moves the wheel one step, wherever it is, but it gets the
        same checks as a press as a video ends: nothing logged since the item
        appeared, no spin, nobody touching, HyperSpin usable.
        """
        hs = self.hs
        hs.read()
        if hs.spinning or self._activity() != self.item:
            return
        if not (hs.in_console or hs.on_main_menu) or not self.quiet(300):
            return
        name, before = hs.selection, self._activity()
        if self.has_video(MAIN_MENU if hs.on_main_menu else hs.wheel, name):
            self.log(f"  HyperSpin didn't spin after {name}'s video: Down again")
        if not self.press(self.keys.down):
            return
        start = self.ops.tick()
        while hs.selection_seq == before.selection:
            if self.foreign_input():
                return
            if self.ops.tick() - start > 3000:
                self.log(f"  Down on {name} showed nothing new within 3 s; waiting for HyperSpin's next spin")
                return
            self.ops.sleep(0.1)
            hs.read()
        if hs.wheel_seq != before.wheel or hs.launch_seq != before.launch:
            self.suspend("!!! the log shows a wheel change or a game after the tour's Down")
            return
        self.seen_landing_seq = hs.landing_seq        # this item, however HyperSpin logged it
        self.phase_count += 1
        self.new_item(stepped=True)

    # ── video lengths ─────────────────────────────────────────────────────────

    def video_folder(self, wheel: str) -> Optional[Path]:
        """Where HyperSpin plays *wheel*'s videos from (the main menu's console
        videos are the "Main Menu" wheel's): ``Settings\\<wheel>.ini``
        ``[video defaults] path`` (a folder of its own, or one under
        ``Media`` or HyperSpin's folder), else ``Media\\<wheel>\\Video``."""
        if not self.hs_dir or not wheel:
            return None
        key = wheel.casefold()
        if key not in self._video_dirs:
            self._video_dirs[key] = _video_folder(Path(self.hs_dir), wheel)
        return self._video_dirs[key]

    def has_video(self, wheel: str, item: str) -> bool:
        """False when *item* in *wheel* has no video HyperSpin plays (no
        ``.mp4`` or ``.flv`` in its video folder, or no such folder: none, or
        only a still); True when it has one, and when the tour can't tell (an
        odd name, no HyperSpin folder)."""
        if not item or "�" in item or re.search(r'[\\/:*?"<>|]', item):
            return True                     # (U+FFFD: a name the log's code page couldn't hold)
        folder = self.video_folder(wheel)
        if folder is None:
            return True
        return (folder / f"{item}.mp4").is_file() or (folder / f"{item}.flv").is_file()

    def video_seconds(self, wheel: str, item: str) -> float:
        """Seconds of *item*'s video in *wheel*, read from its ``.mp4`` (first)
        or ``.flv``, as HyperSpin plays both; 0 when unknown (no video, a
        still, a file that can't be read)."""
        if not item or re.search(r'[\\/:*?"<>|]', item):
            return 0.0
        folder = self.video_folder(wheel)
        if folder is None:
            return 0.0
        mp4, flv = folder / f"{item}.mp4", folder / f"{item}.flv"
        if mp4.is_file():
            from .introvideo import video_duration_seconds

            seconds = video_duration_seconds(mp4)
        else:
            seconds = flv_seconds(flv) if flv.is_file() else None
        # Over 10 hours is a damaged header, not a HyperSpin video.
        return round(seconds, 1) if seconds and 0 < seconds < 36_000 else 0.0

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
        lines.append(f"keys: Start = virtual key {self.keys.start}, Exit = virtual key {self.keys.exit}, "
                     f"Down = virtual key {self.keys.down}")
        missing = [n for n in self.s.skip
                   if not folder or not (Path(folder) / "Databases" / n / f"{n}.xml").is_file()]
        lines.append(f"skip list: {len(self.s.skip)} wheel(s)"
                     + (f" (no database, fine: {', '.join(missing)})" if missing else ""))
        lines.append(f'log: wheel "{hs.wheel}", selection "{hs.selection}" (main menu '
                     f'{"yes" if hs.selection_on_main_menu else "no"}), idle spins {hs.spin_seq}, '
                     f"landings {hs.landing_seq}, launches {hs.launch_seq}")
        lines.append(f"state: {hs.where()}, allowed now: {'yes' if self.allowed(hs.selection) else 'no'}, "
                     f"blocked by: {self.not_eligible() or 'nothing'}")
        wheel = MAIN_MENU if _same(hs.wheel, MAIN_MENU) else hs.wheel
        seconds = self.video_seconds(wheel, hs.selection)
        if seconds:
            lines.append(f"video of the selection: {seconds:g} s")
        elif not self.has_video(wheel, hs.selection):
            lines.append("video of the selection: none (" + (
                f"the tour presses Down after {self._no_video_wait():g} s" if self.down_past_no_video()
                else "HyperSpin waits its idle Time before the next spin") + ")")
        else:
            lines.append("video of the selection: length unknown (the tour then changes wheels right "
                         "after the next spin lands)")
        lines.append(f"video folder: {self.video_folder(wheel) or '(unknown)'}")
        if self.joystick:
            lines.append(f"joystick: HyperSpin reads the {self.joystick} itself, so the tour changes "
                         "wheels only right after an idle spin lands and presses no Down")
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
