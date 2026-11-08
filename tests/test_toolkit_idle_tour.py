"""`spindoctor toolkit idle-tour`: HyperSpin's idle mode, touring the consoles.

The tour reads HyperSpin's live ``log.txt`` and presses HyperSpin's Exit,
Start and Down keys.  Here it runs against :class:`FakeHyperSpin`, which writes a real
``log.txt`` (the lines HyperSpin 1.5 writes) under tmp_path on a fake clock,
spins like HyperSpin's idle mode (after each video, whose ``.mp4`` it writes
with a real movie header) and reacts to the keys the way HyperSpin does, so
no window, key or process of this PC is touched.  The Windows-only tests at
the end only build the ctypes structures and read the process list.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import idle_tour as it
from spindoctor.cli import cli
from spindoctor.config import Config

MAIN = "Main Menu"
EXIT, START, DOWN = 0x1B, 0x0D, 0x28
LEDBLINKY = '"D:\\Arcade\\LEDBlinky\\LEDBlinky.exe"'


def _line(text):
    return f"02:40:10 PM |  {text} \r\n"


def _call(args):
    return _line(f"Command Line is: {LEDBLINKY} {args}")


def _box(kind, payload):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _mp4(path, seconds, timescale=600):
    """A minimal MP4 laid out as many HyperSpin videos are: ftyp, the media,
    then the movie header with the length."""
    mvhd = _box(b"mvhd", struct.pack(">B3xIIII", 0, 0, 0, timescale, int(seconds * timescale)) + b"\0" * 80)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_box(b"ftyp", b"isom\0\0\x02\0isomiso2mp41") + _box(b"mdat", b"\0" * 2048)
                     + _box(b"moov", mvhd))
    return path


def _flv(path, seconds):
    """A minimal FLV: its header, then a script tag whose onMetaData holds
    the duration (an AMF0 number) and the width."""
    def prop(name, value):
        return struct.pack(">H", len(name)) + name + b"\0" + struct.pack(">d", value)
    meta = (b"\x02" + struct.pack(">H", 10) + b"onMetaData" + b"\x08" + struct.pack(">I", 2)
            + prop(b"duration", seconds) + prop(b"width", 640) + b"\0\0\x09")
    tag = b"\x12" + struct.pack(">I", len(meta))[1:] + b"\0" * 7 + meta
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"FLV\x01\x05\0\0\0\x09" + b"\0" * 4 + tag + b"\0" * 64)
    return path


class Press(NamedTuple):
    at: int
    vk: int
    hold: int
    wheel: str
    selection: str
    exit_menu: bool
    spinning: bool


class FakeHyperSpin:
    """HyperSpin, as far as the tour can see it.

    Its idle mode spins as each item's video ends (*interval* ms for an item
    with no video; each spin *spin* ms long) and lands on the next name of
    the wheel's list.  Exit in a console goes back to the main menu, Start on
    the main menu opens the console selected, each *delay* ms later; Exit on
    the main menu opens the exit menu, which logs nothing and stops the idle
    spins.  Down selects the next name (a selection line, no spin) and, as
    real HyperSpin does, its idle mode spins again as that video ends
    (``down_spins = False``: it doesn't).  A player's touch stops the idle mode.
    """

    PID = 4242

    def __init__(self, folder: Path, *, consoles=("Toolkit", "Atari 2600", "Sega Genesis", "No Database"),
                 databases=("Toolkit", "Atari 2600", "Sega Genesis"), settings=None):
        self.folder = folder
        self.log = folder / "log.txt"
        (folder / "Settings").mkdir(parents=True, exist_ok=True)
        (folder / "Settings" / "Settings.ini").write_text(
            settings if settings is not None else
            "[AttractMode]\r\nActive=true\r\nTime=300\r\n[LEDBlinky]\r\nActive=true\r\n",
            encoding="utf-8")
        for name in databases:
            (folder / "Databases" / name).mkdir(parents=True, exist_ok=True)
            (folder / "Databases" / name / f"{name}.xml").write_text("<menu/>", encoding="utf-8")
        self.lists = {MAIN: list(consoles)}
        self.now = 1_000_000
        self.last_input = self.now - 600_000
        self.running = {"HyperSpin.exe": [self.PID]}
        self.front = (self.PID, "ShockwaveFlash")
        self.presses = []
        self.events = []          # (time, fn)
        self.wheel = self.selection = ""
        self.exit_menu = False
        self.spinning = False
        self.idle_on = True
        self.ignore_keys = False
        self.down_spins = True
        self.down_spin_lines = False
        self.interval, self.spin, self.delay = 30_000, 5_000, 800
        self.next_spin = self.now + self.interval
        self.turn = {}
        self.plays = {}           # (wheel, item) -> how long its video really plays, ms
        self.log.write_bytes(b"")
        self.write(_line("HyperSpin Started"))
        self.load(MAIN, "MAME")

    # ── what HyperSpin does ──────────────────────────────────────────────────

    def write(self, text):
        with open(self.log, "ab") as fh:
            fh.write(text.encode("cp1252"))

    def select(self, name):
        self.selection = name
        if self.wheel == MAIN:
            self.write(_call(f'9 "{name}" "Main Menu"'))
        else:
            self.write(_call(f'9 "{name}"'))      # as HyperSpin 1.5 logs a game

    def open_console(self, name, delay):
        """What HyperSpin logs for Start on the main menu: 8 and 7, then the wheel."""
        self.next_spin = self.now + 10 ** 12          # no idle spin while a wheel loads
        self.at(delay // 2, lambda: (self.write(_call("8")), self.write(_call(f'7 "{name}"'))))
        self.at(delay, lambda: self.load(name, f"{name} game 1"))

    def load(self, wheel, selection):
        self.wheel = wheel
        self.write(_line(f"{wheel} wheel loaded successfully"))
        self.select(selection)
        self.next_spin = self.now + self._plays(selection)

    def video(self, wheel, item, seconds, plays=None):
        """Give *item* in *wheel* an .mp4 of *seconds*, which HyperSpin plays
        for *plays* seconds (a video that ends sooner than its file says)."""
        _mp4(self.folder / "Media" / wheel / "Video" / f"{item}.mp4", seconds)
        self.plays[(wheel, item)] = int((seconds if plays is None else plays) * 1000)

    def _plays(self, item):
        return self.plays.get((self.wheel, item), self.interval)

    def at(self, delay, fn):
        self.events.append((self.now + delay, fn))

    def _next_name(self):
        names = self.lists.get(self.wheel) or [f"{self.wheel} game {i}" for i in range(1, 30)]
        i = self.turn.get(self.wheel, 0)
        self.turn[self.wheel] = i + 1
        return names[i % len(names)]

    def _advance(self, ms):
        end = self.now + ms
        while True:
            due = [e for e in self.events if e[0] <= end]
            spin_due = (self.idle_on and not self.exit_menu and self.next_spin <= end
                        and "HyperSpin.exe" in self.running)
            if not due and not spin_due:
                break
            t_event = min(e[0] for e in due) if due else None
            if spin_due and (t_event is None or self.next_spin <= t_event):
                self.now = max(self.now, self.next_spin)
                self.write(_call("5"))
                self.spinning = True
                landing = self._next_name()

                def land(name=landing):
                    self.spinning = False
                    self.write(_call("6"))
                    self.select(name)
                    self.next_spin = self.now + self._plays(name)   # it spins again as the video ends
                self.events.append((self.now + self.spin, land))
                self.next_spin = self.now + 10 ** 12                # not while this spin runs
                continue
            event = min(due, key=lambda e: e[0])
            self.events.remove(event)
            self.now = max(self.now, event[0])
            event[1]()
        self.now = end

    def player(self):
        """Someone uses a control: HyperSpin's idle mode stops."""
        self.last_input = self.now
        self.idle_on = False

    # ── the calls the tour makes ─────────────────────────────────────────────

    def hyperspin_pid(self):
        return self.PID if "HyperSpin.exe" in self.running else 0

    def pids(self, name):
        return list(self.running.get(name, []))

    def image_path(self, pid):
        return str(self.folder / "HyperSpin.exe") if pid == self.PID else None

    def foreground(self):
        return self.front

    def tick(self):
        return self.now

    def idle_ms(self):
        return self.now - self.last_input

    def sleep(self, seconds):
        self._advance(int(round(seconds * 1000)))

    def press(self, vk, hold_ms):
        self.presses.append(Press(self.now, vk, hold_ms, self.wheel, self.selection, self.exit_menu,
                                  self.spinning))
        self.now += hold_ms
        self.last_input = self.now          # Windows counts the tour's own presses as input too
        if self.ignore_keys or self.exit_menu or self.spinning:   # swallowed mid-spin, as HyperSpin does
            return
        if vk == EXIT:
            if self.wheel == MAIN:
                self.exit_menu = True       # logs nothing
            else:
                left = self.wheel
                self.next_spin = self.now + 10 ** 12  # no idle spin while a wheel loads
                self.at(self.delay // 2, lambda: self.write(_call("4")))
                self.at(self.delay, lambda: self.load(MAIN, left))
        elif vk == START and self.wheel == MAIN:
            self.open_console(self.selection, self.delay * 2)
        elif vk == DOWN:
            name = self._next_name()
            if self.down_spin_lines:            # as if this HyperSpin logged a Down like a spin
                self.write(_call("5") + _call("6"))
            self.select(name)
            self.next_spin = self.now + self._plays(name) if self.down_spins else self.now + 10 ** 12

    def single_instance(self, name):
        return True


def _settings(**kw):
    # No Down past items with no video unless a test asks for it: the items
    # these tests give no video stand for videos whose length can't be read.
    base = dict(console_minutes=0, games_per_console=2, main_menu_minutes=0, consoles_on_main_menu=2,
                tour_max_minutes=0, skip=("Toolkit",), no_video_seconds=0)
    base.update(kw)
    return it.Settings(**base)


def _tour(tmp_path, settings=None, **fake_kw):
    fake = FakeHyperSpin(tmp_path / "HyperSpin", **fake_kw)
    lines = []
    tour = it.Tour(settings or _settings(), fake, lines.append, "")
    tour.attach(fake.hyperspin_pid())
    return tour, fake, lines


def _at(fake, i=0):
    """When press *i* came, in ms after the fake HyperSpin started."""
    return fake.presses[i].at - 1_000_000


def _drive(tour, fake, seconds):
    end = fake.now + int(seconds * 1000)
    while fake.now < end:
        fake.sleep(it.POLL)
        tour.step()


def _assert_safe(fake, tour=None):
    """Exit only inside a console, Start only on the main menu on a console the
    tour may open, Down anywhere, never with the exit menu open or during a
    spin, every key held 80 ms."""
    for p in fake.presses:
        assert not p.exit_menu and not p.spinning, p
        assert p.hold == 80, p
        if p.vk == EXIT:
            assert p.wheel != MAIN, p
        elif p.vk != DOWN:
            assert p.vk == START and p.wheel == MAIN, p
            if tour is not None:
                assert tour.allowed(p.selection), p


# ── HyperSpin's log ──────────────────────────────────────────────────────────

REAL_LOG = (
    "02:39:54 PM |  HyperSpin Started \r\n"
    "02:39:54 PM |  LEDBlinky is set to active \r\n"
    '02:39:54 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 1 \r\n'
    "02:39:54 PM |  Startup program: HyperSpin Startup Script.exe \r\n"
    "02:40:09 PM |  Loading Main Menu.xml \r\n"
    "02:40:09 PM |  Main Menu.xml successfully loaded \r\n"
    "02:40:10 PM |  Main Menu wheel loaded successfully \r\n"
    '02:40:10 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 9 "MAME" "Main Menu" \r\n'
    '02:40:40 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 5 \r\n'
    '02:40:47 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 6 \r\n'
    '02:40:47 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 9 "Sammy Atomiswave" "Main Menu" \r\n'
)


def test_log_reads_wheels_selections_and_idle_spin_landings():
    log = it.HyperSpinLog()
    log.feed(REAL_LOG)
    assert log.wheel == MAIN and log.selection == "Sammy Atomiswave" and log.on_main_menu
    assert (log.spin_seq, log.landing_seq) == (1, 1) and not log.spinning
    assert log.where() == "the main menu"


def test_a_selection_without_a_spin_is_not_a_landing():
    log = it.HyperSpinLog()
    log.feed(REAL_LOG)
    log.feed(_call('9 "Sega Saturn" "Main Menu"'))
    assert log.selection == "Sega Saturn" and log.landing_seq == 1
    log.feed(_call("5"))
    assert log.spinning and log.landing_seq == 1
    log.feed(_call("6"))
    assert not log.spinning and log.landing_seq == 1   # landed, but not logged where yet
    log.feed(_call('9 "Sony Playstation" "Main Menu"'))
    assert log.landing_seq == 2


def test_inside_a_console_selections_are_games():
    log = it.HyperSpinLog()
    log.feed(_line("Atari 2600 wheel loaded successfully") + _call('9 "Pitfall!" "Atari 2600"'))
    assert log.in_console and not log.on_main_menu and log.where() == "Atari 2600"
    log.feed(_call('9 "Combat"'))      # a game line with no second name
    assert log.in_console and log.selection == "Combat"


def test_the_same_wheel_loaded_again_is_a_letter_jump_not_a_change():
    log = it.HyperSpinLog()
    log.feed(_line("MAME wheel loaded successfully"))
    seq = log.wheel_seq
    log.feed(_line("MAME wheel loaded successfully") + _line("mame wheel loaded successfully"))
    assert log.wheel_seq == seq
    log.feed(_line("Main Menu wheel loaded successfully"))
    assert log.wheel_seq == seq + 1


def test_game_launches_are_counted():
    log = it.HyperSpinLog()
    log.feed(_line("Launching Game: pacman") + _line("launching game"))
    assert log.launch_seq == 2


def test_every_ledblinky_call_is_counted():
    log = it.HyperSpinLog()
    log.feed(_call("8") + _call('7 "Sega CD"') + _call("4") + _line("Loading Sega CD.xml"))
    assert log.call_seq == 3 and log.selection_seq == 0 and log.landing_seq == 0


def test_other_idle_tours_in_the_startup_list_are_spotted():
    from spindoctor.startup_script import Entry

    items = [Entry(1, "HyperSearch.exe", "", ""), Entry(2, "IdleTour.exe", "", ""),
             Entry(3, "Idle Tour.bat", "", ""), Entry(4, '"idle_tour.ahk"', "", "")]
    assert it.other_tours(items, "Idle Tour.bat") == ["IdleTour.exe", '"idle_tour.ahk"']
    assert it.other_tours(items[:1], "Idle Tour.bat") == []


def test_log_file_is_read_as_it_grows_and_again_when_rewritten(tmp_path):
    path = tmp_path / "log.txt"
    path.write_bytes(REAL_LOG.encode("cp1252") + b"02:41:00 PM |  Command Line is: \"D:\\x\\LEDBlinky.exe\" 5")
    log = it.HyperSpinLog(path)
    assert log.read() and log.landing_seq == 1 and not log.spinning   # the half line waits
    with open(path, "ab") as fh:
        fh.write(b" \r\n")
    assert log.read() and log.spinning
    path.write_bytes(b"02:50:00 PM |  HyperSpin Started \r\n")   # HyperSpin started again
    wheel_seq = log.wheel_seq
    assert log.read() and log.wheel == "" and log.wheel_seq > wheel_seq and not log.spinning
    assert not it.HyperSpinLog(tmp_path / "missing.txt").read()


# ── settings and keys ────────────────────────────────────────────────────────

def test_settings_default_without_a_file(tmp_path):
    assert it.read_settings(None) == it.Settings()
    assert it.read_settings(tmp_path / "none.ini") == it.Settings()
    s = it.Settings()
    assert (s.console_minutes, s.games_per_console, s.main_menu_minutes, s.consoles_on_main_menu,
            s.tour_max_minutes, s.key_hold_ms, s.quiet_ms, s.end_margin_ms, s.no_video_seconds) == (
        5, 5, 5, 5, 0, 80, 1500, 1500, 8)
    assert s.skips("toolkit") and s.skips("Favorites ") and not s.skips("MAME")
    assert s.summary().endswith("Down past items with no video after 8 s")
    assert "; no tour limit," in s.summary()
    assert "; tour limit 60 min," in s._replace(tour_max_minutes=60).summary()
    assert s._replace(no_video_seconds=0).summary().endswith("no Down past items with no video")


def test_the_settings_file_install_tools_writes_reads_back_as_the_defaults(tmp_path):
    path = tmp_path / it.SETTINGS_FILE
    path.write_bytes(it.DEFAULT_SETTINGS_TEXT.encode("utf-8"))
    assert it.read_settings(path) == it.Settings()
    assert b"\r\n" in path.read_bytes() and b"\r\r" not in path.read_bytes()


def test_settings_are_read_like_windows_reads_an_ini(tmp_path):
    path = tmp_path / "s.ini"
    path.write_text(
        "\ufeff[idletour]\nenabled=0\nCONSOLEMINUTES=2.5\nGamesPerConsole=abc\nMainMenuMinutes=-1\n"
        "ConsolesOnMainMenu=0\nSkip= Toolkit | Sony PSP ||\nPauseWhile=Tester.exe\nKeyHoldMs=120\n"
        "novideoseconds=2.5\n",
        encoding="utf-8")
    s = it.read_settings(path)
    assert not s.enabled and s.console_minutes == 2.5
    assert s.games_per_console == 5 and s.main_menu_minutes == 5    # bad values keep the default
    assert s.consoles_on_main_menu == 0 and s.key_hold_ms == 120 and s.no_video_seconds == 2.5
    assert s.skip == ("Toolkit", "Sony PSP") and s.pause_while == ("Tester.exe",)
    # Numbers that aren't finite keep the default too, instead of breaking the GUI and the tour.
    path.write_text("[IdleTour]\nGamesPerConsole=inf\nKeyHoldMs=1e999\nConsoleMinutes=nan\nEndMarginMs=-inf\n",
                    encoding="utf-8")
    s = it.read_settings(path)
    assert (s.games_per_console, s.key_hold_ms, s.console_minutes, s.end_margin_ms) == (5, 80, 5, 1500)


def test_set_settings_text_changes_only_the_values_the_tour_reads():
    text = ("; my notes\r\n[General]\r\nGamesPerConsole=99\r\n[idletour]\r\n; keep me\r\n"
            "enabled = 1   \r\nGAMESPERCONSOLE=5\r\nSkip=Toolkit\r\n\r\n[Other]\r\nx=1\r\n"
            "[IdleTour]\r\nGamesPerConsole=7\r\n")
    out = it.set_settings_text(text, {"GamesPerConsole": "10", "Enabled": "0", "TourMaxMinutes": "30"})
    # The key's spelling and spacing stay; a later copy of a key (which the
    # tour doesn't read) and other sections are left alone; a new key goes
    # after the first [IdleTour] section's last line.
    assert out == ("; my notes\r\n[General]\r\nGamesPerConsole=99\r\n[idletour]\r\n; keep me\r\n"
                   "enabled = 0   \r\nGAMESPERCONSOLE=10\r\nSkip=Toolkit\r\nTourMaxMinutes=30\r\n\r\n"
                   "[Other]\r\nx=1\r\n[IdleTour]\r\nGamesPerConsole=7\r\n")
    # No section yet, the file's own line ends, no newline at the end.
    assert it.set_settings_text("[Other]\nx=1", {"Skip": "A|B"}) == "[Other]\nx=1\n[IdleTour]\nSkip=A|B\n"
    assert it.set_settings_text("", {"Enabled": "1"}) == "[IdleTour]\r\nEnabled=1\r\n"
    assert it.set_settings_text("[IdleTour]", {"Enabled": "0"}) == "[IdleTour]\r\nEnabled=0\r\n"


def test_change_settings_keeps_every_other_byte(tmp_path):
    path = tmp_path / it.SETTINGS_FILE
    original = b"\xef\xbb\xbf" + it.DEFAULT_SETTINGS_TEXT.encode("utf-8")
    path.write_bytes(original)
    made = it.change_settings(path, enabled=True, games_per_console=10, console_minutes=0,
                              consoles_on_main_menu=1, main_menu_minutes=0.0, tour_max_minutes=0,
                              no_video_seconds=8, skip=("Toolkit", "Apple II"))
    assert made == [
        it.SettingChange("GamesPerConsole", "5", "10"),
        it.SettingChange("ConsoleMinutes", "5", "0"),
        it.SettingChange("ConsolesOnMainMenu", "5", "1"),
        it.SettingChange("MainMenuMinutes", "5", "0"),
        it.SettingChange("Skip", "Toolkit|Favorites|Most Played|Recently Played", "Toolkit|Apple II"),
    ]
    expected = original
    for old, new in ((b"GamesPerConsole=5\r", b"GamesPerConsole=10\r"),
                     (b"ConsoleMinutes=5\r", b"ConsoleMinutes=0\r"),
                     (b"ConsolesOnMainMenu=5\r", b"ConsolesOnMainMenu=1\r"),
                     (b"MainMenuMinutes=5\r", b"MainMenuMinutes=0\r"),
                     (b"Skip=Toolkit|Favorites|Most Played|Recently Played\r", b"Skip=Toolkit|Apple II\r")):
        assert expected.count(old) == 1
        expected = expected.replace(old, new)
    assert path.read_bytes() == expected          # BOM, comments and line ends kept
    s = it.read_settings(path)
    assert (s.games_per_console, s.consoles_on_main_menu, s.console_minutes, s.skip) == (
        10, 1, 0, ("Toolkit", "Apple II"))
    # The same values again, also written another way (Skip in another order
    # and case, or twice): nothing to change.
    assert it.change_settings(path, games_per_console=10, console_minutes=0.0, skip="Toolkit | Apple II") == []
    assert it.change_settings(path, skip=("apple ii", "Toolkit", "TOOLKIT")) == []
    assert path.read_bytes() == expected
    # A new list is written once per name.
    assert it.change_settings(path, skip=("MAME", "mame", "Toolkit")) == [
        it.SettingChange("Skip", "Toolkit|Apple II", "MAME|Toolkit")]


def test_change_settings_adds_a_key_an_older_settings_file_lacks(tmp_path):
    # Written by an install before NoVideoSeconds existed: the tour reads the
    # default (8) until the key is set, which then goes after the section's
    # last line, in the file's own line ends.
    path = tmp_path / it.SETTINGS_FILE
    path.write_bytes(b"; mine\r\n[IdleTour]\r\nEnabled=1\r\nSkip=Toolkit\r\n\r\n[Other]\r\nx=1\r\n")
    assert it.read_settings(path).no_video_seconds == 8
    assert it.change_settings(path, no_video_seconds=8) == []
    assert it.change_settings(path, no_video_seconds=12.5) == [it.SettingChange("NoVideoSeconds", "8", "12.5")]
    assert path.read_bytes() == (b"; mine\r\n[IdleTour]\r\nEnabled=1\r\nSkip=Toolkit\r\nNoVideoSeconds=12.5\r\n"
                                 b"\r\n[Other]\r\nx=1\r\n")
    assert it.change_settings(path, no_video_seconds=0) == [it.SettingChange("NoVideoSeconds", "12.5", "0")]
    assert it.read_settings(path).no_video_seconds == 0
    # Written as given (not rounded to 6 digits), so saving it again changes nothing.
    assert it.change_settings(path, no_video_seconds=1234.5678)[0].new == "1234.5678"
    assert it.change_settings(path, no_video_seconds=1234.5678) == []


def test_change_settings_refuses_what_the_file_cant_hold(tmp_path):
    path = tmp_path / "s.ini"
    path.write_bytes(b"[IdleTour]\r\nSkip=Pok\xe9mon Mini\r\n")      # ANSI, as Notepad saves it
    with pytest.raises(ValueError):
        it.change_settings(path, games_per_console=-1)
    with pytest.raises(ValueError):
        it.change_settings(path, no_video_seconds=-0.5)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            it.change_settings(path, console_minutes=bad)
    with pytest.raises(ValueError):
        it.change_settings(path, skip=("Line\nbreak",))
    with pytest.raises(ValueError):                    # not in the file's code page
        it.change_settings(path, skip=("Pokémon Mini", "漢字"))
    with pytest.raises(TypeError):
        it.change_settings(path, key_hold_ms=50)
    assert path.read_bytes() == b"[IdleTour]\r\nSkip=Pok\xe9mon Mini\r\n"
    assert it.change_settings(path, skip=("Pokémon Mini", "MAME")) == [
        it.SettingChange("Skip", "Pokémon Mini", "Pokémon Mini|MAME")]
    assert path.read_bytes() == b"[IdleTour]\r\nSkip=Pok\xe9mon Mini|MAME\r\n"
    with pytest.raises(OSError):
        it.change_settings(tmp_path / "missing.ini", enabled=False)


def test_keys_come_from_hyperspins_player_1_controls(tmp_path):
    (tmp_path / "Settings").mkdir()
    ini = tmp_path / "Settings" / "Settings.ini"
    assert it.hyperspin_keys(tmp_path) == it.Keys(13, 27, 40) == it.hyperspin_keys("")
    ini.write_text("[P1 Controls]\nStart=49\nExit=8\nDown=98\n[P2 Controls]\nStart=50\n", encoding="utf-8")
    assert it.hyperspin_keys(tmp_path) == it.Keys(49, 8, 98)
    ini.write_text("[P1 Controls]\nStart=x\nExit=999\nDown=0\n", encoding="utf-8")
    assert it.hyperspin_keys(tmp_path) == it.Keys(13, 27, 40)


# ── the tour ─────────────────────────────────────────────────────────────────

def test_main_menu_opens_the_console_a_spin_landed_on_after_the_count(tmp_path):
    tour, fake, lines = _tour(tmp_path)
    fake.lists[MAIN] = ["Sega Genesis", "Sega Genesis", "Atari 2600"]
    _drive(tour, fake, 110)             # landings at 35, 70 and 105 s
    # 2 consoles shown; with no video length the console the next spin
    # lands on (the 3rd) is opened.
    assert [p.vk for p in fake.presses] == [START]
    assert fake.presses[0].selection == "Atari 2600" and fake.wheel == "Atari 2600"
    assert any("console 2 is Sega Genesis (video length unknown)" in line for line in lines)
    assert any("opened Atari 2600 after" in line and "2 consoles on the main menu" in line for line in lines)
    _assert_safe(fake, tour)


def test_console_goes_back_to_the_main_menu_after_the_count(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 75)
    assert fake.wheel == "Atari 2600"
    _drive(tour, fake, 110)
    assert [p.vk for p in fake.presses] == [START, EXIT]
    assert fake.presses[1].wheel == "Atari 2600" and fake.wheel == MAIN
    # The first game shown after Start is game 1, so the 1st idle spin there shows game 2.
    assert any("Atari 2600: game 1 is Atari 2600 game 1" in line for line in lines)
    assert any("back on the main menu after" in line and "2 games in Atari 2600" in line for line in lines)
    _assert_safe(fake, tour)


# ── video-end timing ─────────────────────────────────────────────────────────

def test_main_menu_opens_the_console_just_shown_as_its_video_ends(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    fake.video(MAIN, "Atari 2600", 40)
    _drive(tour, fake, 80)              # lands at 35 s; its video ends at 75 s
    assert [(p.vk, p.selection) for p in fake.presses] == [(START, "Atari 2600")]
    # EndMarginMs (1.5 s) before the end, then 0.3 s of quiet: before the next spin.
    assert 73_500 <= _at(fake) <= 74_200
    assert fake.wheel == "Atari 2600"
    assert any("console 1 is Atari 2600 (40 s): opening it as its video ends" in line for line in lines)
    _assert_safe(fake, tour)


def test_console_counts_its_first_game_and_leaves_as_the_last_video_ends(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1, games_per_console=2))
    fake.lists[MAIN] = ["Atari 2600"]
    fake.lists["Atari 2600"] = ["Combat", "Adventure"]
    fake.video(MAIN, "Atari 2600", 40)
    fake.video("Atari 2600", "Atari 2600 game 1", 20)
    fake.video("Atari 2600", "Combat", 25)
    _drive(tour, fake, 130)
    # Start at 73.8 s; the console shows game 1 at 75.5 s (20 s), the next
    # spin lands on Combat at 100.5 s (25 s): Exit as Combat's video ends.
    assert [(p.vk, p.selection) for p in fake.presses] == [(START, "Atari 2600"), (EXIT, "Combat")]
    assert 123_900 <= _at(fake, 1) <= 124_800
    assert fake.wheel == MAIN
    assert any("game 2 is Combat (25 s): leaving as its video ends" in line for line in lines)
    assert any("back on the main menu after" in line and "2 games in Atari 2600" in line for line in lines)
    _assert_safe(fake, tour)


def test_a_video_that_ends_early_changes_right_after_the_next_spin(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    fake.video(MAIN, "Atari 2600", 60, plays=30)   # the file says 60 s; HyperSpin spins after 30
    _drive(tour, fake, 80)
    assert "idle-tour:   the video ended early; changing wheels right after the next spin lands" in lines
    # The spin at 65 s lands at 70 s; 1.5 s of quiet, then Start.
    assert [p.vk for p in fake.presses] == [START]
    assert 71_500 <= _at(fake) <= 72_500
    _assert_safe(fake, tour)


def test_minutes_are_checked_against_the_end_of_this_video(tmp_path):
    tour, fake, _ = _tour(tmp_path, _settings(main_menu_minutes=1, consoles_on_main_menu=0))
    fake.lists[MAIN] = ["Atari 2600"]
    fake.video(MAIN, "Atari 2600", 30)
    _drive(tour, fake, 64)      # landing at 35 s: 0 s in + 30 s of video is under the minute
    assert fake.presses == []
    # Landing at 70 s: 35 s in + 30 s of video reaches it, so Start as that video ends (100 s).
    _drive(tour, fake, 60)
    assert [p.vk for p in fake.presses] == [START]
    assert 98_500 <= _at(fake) <= 99_200
    # Both limits off: it never changes wheels.
    tour2, fake2, _ = _tour(tmp_path / "b", _settings(main_menu_minutes=0, consoles_on_main_menu=0))
    _drive(tour2, fake2, 600)
    assert fake2.presses == []


def test_skipped_consoles_count_but_are_never_opened(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Toolkit", "Atari 2600"]
    fake.video(MAIN, "Toolkit", 30)
    fake.video(MAIN, "Atari 2600", 30)
    _drive(tour, fake, 110)
    assert "idle-tour: main menu: console 1 is Toolkit (skipped, not opened)" in lines
    # Console 2 is past the count: opened as its video ends (70 + 30 s).
    assert [(p.vk, p.selection) for p in fake.presses] == [(START, "Atari 2600")]
    assert 98_500 <= _at(fake) <= 99_200
    _assert_safe(fake, tour)


def test_waiting_for_a_spin_goes_past_skipped_consoles(tmp_path):
    # Console 1 is due but has no video length: the next spin decides. It
    # lands on Toolkit (skipped): wait for the one after, Sega Genesis.
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600", "Toolkit", "Sega Genesis"]
    _drive(tour, fake, 110)
    assert "idle-tour: main menu: console 2 is Toolkit (skipped, not opened); waiting for the next spin" in lines
    assert [(p.vk, p.selection) for p in fake.presses] == [(START, "Sega Genesis")]
    assert 106_500 <= _at(fake) <= 107_200      # right after it lands (105 s)
    _assert_safe(fake, tour)


def test_anything_logged_during_the_video_stops_the_press_at_its_end(tmp_path):
    # A pad HyperSpin reads itself moves the selection (a 9 line), or HyperSpin
    # logs 8 / 7 for a Start Windows can't see: nothing is pressed at the end.
    for i, event in enumerate((
        lambda fake: fake.select("Sega Genesis"),
        lambda fake: fake.write(_call("8")),
    )):
        tour, fake, lines = _tour(tmp_path / str(i), _settings(consoles_on_main_menu=1))
        fake.lists[MAIN] = ["Atari 2600"]
        fake.video(MAIN, "Atari 2600", 40)
        fake.at(50_000, lambda fake=fake, event=event: event(fake))
        _drive(tour, fake, 76)          # the video ends at 75 s
        assert fake.presses == [], i
        _assert_safe(fake, tour)


def _joystick_tour(folder, **kw):
    fake = FakeHyperSpin(folder, settings=(
        "[AttractMode]\nActive=true\n[LEDBlinky]\nActive=true\n"
        "[P1 Joystick]\nEnabled=false\n[P2 Joystick]\nEnabled=true\nJoy=1\n"))
    lines = []
    tour = it.Tour(_settings(consoles_on_main_menu=1, **kw), fake, lines.append, "")
    tour.attach(fake.hyperspin_pid())
    return tour, fake, lines


def test_a_joystick_hyperspin_reads_itself_keeps_to_the_landings(tmp_path):
    tour, fake, lines = _joystick_tour(tmp_path / "a")
    assert tour.joystick == "P2 Joystick"
    assert any("reads the P2 Joystick itself" in line for line in lines)
    fake.lists[MAIN] = ["Atari 2600"]
    fake.video(MAIN, "Atari 2600", 40)
    _drive(tour, fake, 90)
    # Not as the video ends (75 s): right after the next spin lands (80 s).
    assert [p.vk for p in fake.presses] == [START]
    assert 81_500 <= _at(fake) <= 82_500
    assert any("console 1 is Atari 2600 (joystick): opening the console the next spin lands on" in line
               for line in lines)
    # A joystick Exit mid-video opens the exit menu: no log line, no Windows
    # input, no more idle spins, and so no press at all.
    tour, fake, _ = _joystick_tour(tmp_path / "b")
    fake.lists[MAIN] = ["Atari 2600"]
    fake.video(MAIN, "Atari 2600", 40)
    fake.at(50_000, lambda: setattr(fake, "exit_menu", True))
    _drive(tour, fake, 30 * 60)
    assert fake.presses == []
    assert it.own_joystick(tmp_path / "none") == "" and it.own_joystick("") == ""


def test_video_lengths_come_from_the_wheels_video_folder(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin")
    tour = it.Tour(_settings(), fake, [].append, "")
    tour.attach(fake.hyperspin_pid())
    hs = fake.folder
    _mp4(hs / "Media" / "MAME" / "Video" / "pacman.mp4", 46.25)
    assert tour.video_folder("MAME") == hs / "Media" / "MAME" / "Video"
    assert tour.video_seconds("MAME", "pacman") == 46.2
    assert tour.video_seconds("MAME", "missing") == 0
    assert tour.video_seconds("MAME", "bad|name") == 0 and tour.video_seconds("MAME", "") == 0
    _mp4(hs / "Media" / "MAME" / "Video" / "broken.mp4", 50_000)    # a damaged header: 14 hours
    assert tour.video_seconds("MAME", "broken") == 0
    # HyperSpin plays .flv too: its length is in its onMetaData header. The .mp4 comes first.
    video = hs / "Media" / "MAME" / "Video"
    _flv(video / "galaga.flv", 52.53)
    assert tour.video_seconds("MAME", "galaga") == 52.5
    _flv(video / "pacman.flv", 99)
    assert tour.video_seconds("MAME", "pacman") == 46.2
    (video / "digdug.flv").write_bytes(b"FLV" + b"\0" * 100)       # no onMetaData duration
    (video / "mappy.flv").write_bytes(b"FLV")
    assert tour.video_seconds("MAME", "digdug") == 0 == tour.video_seconds("MAME", "mappy")
    # A video is an .mp4 or .flv, readable or not; a still or nothing is none,
    # also in a wheel with no video folder. With an odd name the tour can't tell.
    (video / "frogger.png").write_bytes(b"\x89PNG")
    assert all(tour.has_video("MAME", n) for n in ("pacman", "galaga", "digdug", "broken"))
    assert not tour.has_video("MAME", "frogger") and not tour.has_video("MAME", "missing")
    assert not tour.has_video("Nowhere", "anything")
    assert tour.has_video("MAME", "bad|name") and tour.has_video("MAME", "")
    assert tour.has_video("MAME", "Pok�mon")         # a name the log's code page couldn't hold
    # Settings\<wheel>.ini [video defaults] path=: under Media, under HyperSpin's
    # folder, or a folder of its own; one that doesn't exist falls back.
    shared = hs / "Media" / "Shared" / "Video"
    _mp4(shared / "sf2.mp4", 12)
    own = tmp_path / "Videos"
    own.mkdir()
    for wheel, path, folder in (
        ("A", "Shared\\Video\\", shared),
        ("B", ".\\Media\\Shared\\Video", shared),
        ("C", str(own), own),
        ("D", "Nowhere\\Video", hs / "Media" / "D" / "Video"),
    ):
        (hs / "Settings" / f"{wheel}.ini").write_text(
            f"[themes]\ndefault=true\n[Video Defaults]\nPath={path}\n", encoding="utf-8")
        assert tour.video_folder(wheel) == folder, wheel
    assert tour.video_seconds("B", "sf2") == 12


# ── past items with no video ─────────────────────────────────────────────────

def _no_video_tour(tmp_path, **kw):
    """Down past items with no video after 8 s; HyperSpin itself waits its
    idle Time (5 minutes) on one before it spins again."""
    kw.setdefault("no_video_seconds", 8)
    tour, fake, lines = _tour(tmp_path, _settings(**kw))
    fake.interval = 300_000
    return tour, fake, lines


def test_a_game_with_no_video_gets_a_down_and_the_next_one_counts(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, consoles_on_main_menu=1, games_per_console=4)
    fake.lists[MAIN] = ["Atari 2600"]
    fake.lists["Atari 2600"] = ["Combat", "Adventure"]
    fake.video(MAIN, "Atari 2600", 40)
    fake.video("Atari 2600", "Atari 2600 game 1", 20)
    fake.video("Atari 2600", "Adventure", 25)          # Combat has none
    _drive(tour, fake, 160)
    # Start at 73.8 s; game 1 at 75.4 s (20 s); the spin lands on Combat at
    # 100.4 s; Down 8 s later shows Adventure, game 3, and HyperSpin spins as
    # its video ends, onto Combat again: game 4, the last, with no video, so
    # Exit 8 s after it appeared.
    assert [(p.vk, p.selection) for p in fake.presses] == [
        (START, "Atari 2600"), (DOWN, "Combat"), (EXIT, "Combat")]
    assert 108_400 <= _at(fake, 1) <= 109_300
    assert 146_800 <= _at(fake, 2) <= 147_800
    assert fake.wheel == MAIN
    assert "idle-tour:   Atari 2600: game 2 is Combat (no video: stepping on in 8 s)" in lines
    assert "idle-tour:   Atari 2600: game 3 is Adventure" in lines
    assert "idle-tour:   Atari 2600: game 4 is Combat (no video): leaving in 8 s" in lines
    assert any("back on the main menu after" in line and "4 games in Atari 2600" in line for line in lines)
    assert not any("Down again" in line for line in lines)      # HyperSpin spun after Adventure
    _assert_safe(fake, tour)


def test_a_skipped_console_with_no_video_gets_a_down_too(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, consoles_on_main_menu=1)
    fake.lists[MAIN] = ["Toolkit", "Atari 2600"]
    fake.video(MAIN, "Atari 2600", 30)                  # Toolkit has none
    _drive(tour, fake, 80)
    assert [(p.vk, p.selection) for p in fake.presses] == [(DOWN, "Toolkit"), (START, "Atari 2600")]
    assert 43_300 <= _at(fake) <= 44_200
    # Atari 2600 appears with the Down: console 2, past the count, so Start as its video ends.
    assert 71_800 <= _at(fake, 1) <= 72_900
    assert "idle-tour: main menu: console 1 is Toolkit (skipped, not opened; no video, stepping on in 8 s)" in lines
    assert any("console 2 is Atari 2600 (30 s): opening it as its video ends" in line for line in lines)
    _assert_safe(fake, tour)


def test_a_due_console_with_no_video_is_opened_after_no_video_seconds(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, consoles_on_main_menu=1)
    fake.lists[MAIN] = ["Sega Genesis"]
    (fake.folder / "Media" / MAIN / "Video").mkdir(parents=True)     # its video is missing
    _drive(tour, fake, 50)
    assert [(p.vk, p.selection) for p in fake.presses] == [(START, "Sega Genesis")]
    assert 43_300 <= _at(fake) <= 44_200                # landed at 35 s, + 8 s, + 0.3 s of quiet
    assert "idle-tour: main menu: console 1 is Sega Genesis (no video): opening it in 8 s" in lines
    _assert_safe(fake, tour)


def _in_console(tour, fake, games):
    """HyperSpin's idle mode already running in Atari 2600, on a game with a
    10-second video; the next spins land on *games* in turn."""
    fake.lists["Atari 2600"] = list(games)
    fake.video("Atari 2600", "Pitfall!", 10)
    fake.load("Atari 2600", "Pitfall!")


def test_down_again_when_hyperspin_doesnt_spin_after_the_video_a_down_showed(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, games_per_console=0)
    _in_console(tour, fake, ["Combat", "Adventure"])
    fake.video("Atari 2600", "Adventure", 25)
    fake.down_spins = False             # its idle timer doesn't count a scripted Down
    _drive(tour, fake, 70)
    # Combat (no video) lands at 15 s: Down at 23 s shows Adventure (25 s);
    # no spin by 5 s after its end: Down again, onto Combat, and on 8 s later.
    assert [(p.vk, p.selection) for p in fake.presses] == [
        (DOWN, "Combat"), (DOWN, "Adventure"), (DOWN, "Combat")]
    assert 23_300 <= _at(fake, 0) <= 24_200
    assert 53_300 <= _at(fake, 1) <= 54_400
    assert 61_500 <= _at(fake, 2) <= 62_800
    assert "idle-tour:   HyperSpin didn't spin after Adventure's video: Down again" in lines
    _assert_safe(fake, tour)


def test_a_down_that_shows_nothing_waits_for_hyperspins_next_spin(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, games_per_console=0)
    _in_console(tour, fake, ["Combat"])
    (fake.folder / "Media" / "Atari 2600" / "Video" / "Combat.png").write_bytes(b"\x89PNG")   # a still
    fake.ignore_keys = True
    _drive(tour, fake, 200)             # HyperSpin's own next spin: 300 s after Combat landed
    assert [(p.vk, p.selection) for p in fake.presses] == [(DOWN, "Combat")]
    assert "idle-tour:   Down on Combat showed nothing new within 3 s; waiting for HyperSpin's next spin" in lines
    _assert_safe(fake, tour)


def test_a_wheel_change_or_a_game_after_a_down_suspends_the_tour(tmp_path):
    for i, after in enumerate((
        lambda fake: fake.write(_line("Launching Game")),
        lambda fake: fake.write(_line("Sega Genesis wheel loaded successfully")),
    )):
        tour, fake, lines = _no_video_tour(tmp_path / str(i), games_per_console=0)
        _in_console(tour, fake, ["Combat", "Adventure"])
        original = fake.press

        def press(vk, hold_ms, fake=fake, original=original, after=after):
            original(vk, hold_ms)
            after(fake)
        fake.press = press
        _drive(tour, fake, 600)
        assert [p.vk for p in fake.presses] == [DOWN], i
        assert "idle-tour: !!! the log shows a wheel change or a game after the tour's Down; " \
               "pausing until someone uses a control" in lines, i


def test_a_down_logged_with_spin_lines_counts_once(tmp_path):
    # Should a HyperSpin log a scripted Down with 5 / 6 around it, the item it
    # brings up is still one item, not a Down and a landing.
    tour, fake, lines = _no_video_tour(tmp_path, games_per_console=0)
    _in_console(tour, fake, ["Combat", "Adventure", "Pitfall!"])
    fake.video("Atari 2600", "Adventure", 25)
    fake.down_spin_lines = True
    _drive(tour, fake, 45)              # Combat at 15 s, Down at 23 s; Adventure plays till 48 s
    games = [line for line in lines if ": game " in line]
    assert games == ["idle-tour:   Atari 2600: game 1 is Combat (no video: stepping on in 8 s)",
                     "idle-tour:   Atari 2600: game 2 is Adventure"]


def test_a_pending_down_is_dropped_when_a_control_is_used_or_a_game_runs(tmp_path):
    for i, event in enumerate((
        lambda fake: fake.player(),
        lambda fake: fake.running.__setitem__("RocketLauncher.exe", [77]),
    )):
        tour, fake, lines = _no_video_tour(tmp_path / str(i), games_per_console=0)
        _in_console(tour, fake, ["Combat"])
        fake.at(20_000, lambda fake=fake, event=event: event(fake))
        _drive(tour, fake, 60)          # Combat lands at 15 s; the Down would come at 23 s
        assert fake.presses == [], i
        if i == 1:
            del fake.running["RocketLauncher.exe"]
            _drive(tour, fake, 60)      # back: nothing until a new idle spin lands
            assert fake.presses == []


def test_no_video_seconds_under_2_waits_2_seconds(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, games_per_console=0, no_video_seconds=0.5)
    _in_console(tour, fake, ["Combat", "Adventure"])
    _drive(tour, fake, 25)
    assert "idle-tour:   Atari 2600: game 1 is Combat (no video: stepping on in 2 s)" in lines
    assert fake.presses and 17_000 <= _at(fake) <= 17_800      # Combat landed at 15 s
    _assert_safe(fake, tour)


def test_anything_logged_before_the_down_stops_it(tmp_path):
    # A pad HyperSpin reads itself moves the selection, or a call is logged:
    # no Down for that item.
    for i, event in enumerate((
        lambda fake: fake.select("Adventure"),
        lambda fake: fake.write(_call("8")),
    )):
        tour, fake, lines = _no_video_tour(tmp_path / str(i), games_per_console=0)
        _in_console(tour, fake, ["Combat"])
        fake.at(20_000, lambda fake=fake, event=event: event(fake))
        _drive(tour, fake, 60)          # Combat lands at 15 s; the Down would come at 23 s
        assert fake.presses == [], i


def test_no_down_when_no_video_seconds_is_0(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(games_per_console=0))
    fake.interval = 300_000
    _in_console(tour, fake, ["Combat"])
    _drive(tour, fake, 200)
    assert fake.presses == [] and "game 1 is Combat" in lines[-1]


def test_with_a_joystick_there_is_no_down(tmp_path):
    # A joystick Exit opens the exit menu unseen, and a Down there would move
    # its highlight: no Down at all, and the change waits for a spin to land.
    tour, fake, lines = _joystick_tour(tmp_path, no_video_seconds=8)
    fake.interval = 300_000
    fake.lists[MAIN] = ["Sega Genesis", "Atari 2600"]
    fake.video(MAIN, "Atari 2600", 40)                  # Sega Genesis has none
    _drive(tour, fake, 350)
    # HyperSpin sits on Sega Genesis for its 300 s, then lands on Atari 2600 at 340 s.
    assert [(p.vk, p.selection) for p in fake.presses] == [(START, "Atari 2600")]
    assert 341_300 <= _at(fake) <= 342_500
    assert ("idle-tour: main menu: console 1 is Sega Genesis (no video, joystick): "
            "opening the console the next spin lands on") in lines
    assert any("presses no Down" in line for line in lines)
    _assert_safe(fake, tour)


def test_a_long_tour_with_items_without_video_only_ever_presses_safely(tmp_path):
    tour, fake, lines = _no_video_tour(tmp_path, games_per_console=3, consoles_on_main_menu=2)
    fake.lists[MAIN] = ["Toolkit", "Atari 2600", "No Database", "Sega Genesis", "Toolkit"]
    fake.video(MAIN, "Atari 2600", 30)
    fake.video(MAIN, "No Database", 20)
    for i in range(1, 30, 2):
        fake.video("Atari 2600", f"Atari 2600 game {i}", 15 + i)
    (fake.folder / "Media" / "Sega Genesis" / "Video").mkdir(parents=True)    # none of its games has one
    _drive(tour, fake, 60 * 60)
    vks = [p.vk for p in fake.presses]
    assert {START, EXIT, DOWN} <= set(vks) and len(vks) >= 30
    assert {p.selection for p in fake.presses if p.vk == START} <= {"Atari 2600", "Sega Genesis"}
    _assert_safe(fake, tour)
    # Each Down comes after its item has been up a while: never two within 8 s.
    downs = [p.at for p in fake.presses if p.vk == DOWN]
    assert all(b - a >= 8_000 for a, b in zip(downs, downs[1:]))


def test_a_long_tour_only_ever_presses_safely(tmp_path):
    tour, fake, lines = _tour(tmp_path)
    fake.lists[MAIN] = ["Toolkit", "Atari 2600", "No Database", "Sega Genesis", "Toolkit"]
    _drive(tour, fake, 60 * 60)
    assert len(fake.presses) >= 20
    assert {p.vk for p in fake.presses} == {START, EXIT}
    assert {p.selection for p in fake.presses if p.vk == START} <= {"Atari 2600", "Sega Genesis"}
    _assert_safe(fake, tour)
    assert any("(skipped, not opened)" in line for line in lines)


def test_minutes_count_too_whichever_comes_first(tmp_path):
    tour, fake, _ = _tour(tmp_path, _settings(main_menu_minutes=1, consoles_on_main_menu=0))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 64)      # landings at 35 and 70 s: the first starts the count
    assert fake.presses == []
    _drive(tour, fake, 60)      # 105 s is past the minute; no video length, so not yet
    assert fake.presses == []
    _drive(tour, fake, 20)      # right after the next spin lands, at 140 s
    assert [p.vk for p in fake.presses] == [START]
    assert 141_500 <= _at(fake) <= 142_500


def test_skipped_and_database_less_consoles_are_never_opened(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Toolkit", "No Database"]
    _drive(tour, fake, 600)
    assert fake.presses == []
    assert "idle-tour: main menu: console 1 is Toolkit (skipped, not opened)" in lines
    assert "idle-tour: main menu: console 2 is No Database (skipped, not opened)" in lines
    assert not tour.allowed(MAIN) and not tour.allowed("")


def test_nothing_is_pressed_without_a_fresh_landing(tmp_path):
    # A player opened HyperSpin's exit menu: no idle spins come, so however
    # long it waits, the tour presses nothing.
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    _drive(tour, fake, 40)              # the first landing starts the count
    fake.player()
    fake.exit_menu = True
    fake.idle_on = True
    _drive(tour, fake, 30 * 60)
    assert fake.presses == []


def test_a_control_used_stops_the_tour_until_idle_mode_starts_again(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=3))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 100)            # 3 landings, counting
    fake.player()
    _drive(tour, fake, 1)
    assert "idle-tour: a control was used: waiting for HyperSpin's idle mode to start again" in lines
    fake.idle_on = True
    fake.next_spin = fake.now + 30_000
    _drive(tour, fake, 100)            # the count starts again at the first new spin
    assert fake.presses == []
    _drive(tour, fake, 40)
    assert [p.vk for p in fake.presses] == [START]


def test_input_while_waiting_for_quiet_stops_the_press(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 69)
    # The second landing is at 70 s; a touch half a second later, while the
    # tour waits for the log to be quiet (HyperSpin's idle mode carries on).
    fake.at(1_500, lambda: setattr(fake, "last_input", fake.now))
    _drive(tour, fake, 5)
    assert fake.presses == []
    assert "idle-tour: a control was used: waiting for HyperSpin's idle mode to start again" in lines


def test_a_spin_right_after_the_landing_waits_for_the_next_landing(tmp_path):
    tour, fake, _ = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    fake.interval = 1_000             # the next spin starts before the log has been quiet 1.5 s
    _drive(tour, fake, 60)
    assert fake.presses == []
    fake.interval = 30_000
    _drive(tour, fake, 60)
    assert [p.vk for p in fake.presses] == [START]


def test_a_start_windows_cant_see_stops_the_press(tmp_path):
    # A pad HyperSpin reads itself presses Start during the quiet wait: Windows
    # sees no input, but HyperSpin logs 8 and 7 before it opens the console.
    tour, fake, _ = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 69)
    fake.at(1_400, lambda: fake.open_console("Atari 2600", 1_000))
    _drive(tour, fake, 10)
    assert fake.presses == [] and fake.wheel == "Atari 2600"
    _drive(tour, fake, 30)              # in the console now: no Start there
    assert all(p.vk != START for p in fake.presses)
    _assert_safe(fake, tour)


def test_single_mode_presses_nothing(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin", settings=(
        "[Main]\nMenu_Mode=single\n[AttractMode]\nActive=true\n[LEDBlinky]\nActive=true\n"))
    fake.load("MAME", "pacman")          # single mode: one wheel, no main menu
    lines = []
    tour = it.Tour(_settings(games_per_console=1), fake, lines.append, "")
    tour.attach(fake.hyperspin_pid())
    _drive(tour, fake, 600)
    assert fake.presses == []
    assert tour.not_eligible().startswith("HyperSpin is in single mode")
    assert any("single mode" in line and "presses nothing" in line for line in lines)
    assert it.single_mode("") == "" and it.single_mode(tmp_path) == ""


@pytest.mark.parametrize("block, reason", [
    ("rocketlauncher", "a game is running (RocketLauncher)"),
    ("front", "HyperSpin isn't the front window"),
    ("popup", "a HyperSpin pop-up is open"),
    ("pause", "Tester.exe is running"),
])
def test_nothing_is_pressed_while_hyperspin_isnt_usable(tmp_path, block, reason):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1, pause_while=("Other.exe", "Tester")))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 40)             # the first landing starts the count
    if block == "rocketlauncher":
        fake.running["RocketLauncher.exe"] = [77]
    elif block == "front":
        fake.front = (999, "Notepad")
    elif block == "popup":
        fake.front = (fake.PID, "#32770")
    else:
        fake.running["Tester.exe"] = [88]
    _drive(tour, fake, 300)
    assert fake.presses == []
    assert f"idle-tour: paused: {reason}" in lines
    assert tour.not_eligible() == reason


def test_hyperspins_own_keys_are_pressed(tmp_path):
    folder = tmp_path / "HyperSpin"
    fake = FakeHyperSpin(folder, settings=(
        "[AttractMode]\nActive=true\n[LEDBlinky]\nActive=true\n[P1 Controls]\nStart=49\nExit=8\n"))
    fake.lists[MAIN] = ["Atari 2600"]
    tour = it.Tour(_settings(consoles_on_main_menu=1), fake, [].append, "")
    tour.attach(fake.hyperspin_pid())
    assert tour.keys == it.Keys(49, 8) and tour.hs_dir == str(folder)
    _drive(tour, fake, 70)
    assert [p.vk for p in fake.presses] == [49]


def test_exit_that_brings_nothing_is_not_repeated_until_the_next_landing(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1, games_per_console=1))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 70)
    assert fake.wheel == "Atari 2600"   # game 1 is the last; no video length
    fake.ignore_keys = True
    _drive(tour, fake, 60)              # the landing in the console at 108 s: one Exit
    exits = [p for p in fake.presses if p.vk == EXIT]
    assert len(exits) == 1
    assert any("didn't bring the main menu within 15 s" in line for line in lines)
    _drive(tour, fake, 40)              # the next landing (143 s): tried once more
    exits = [p.at for p in fake.presses if p.vk == EXIT]
    assert len(exits) >= 2
    # Never twice for one landing: a new idle spin (every 35 s here) between any two.
    assert all(b - a >= fake.interval for a, b in zip(exits, exits[1:]))
    _assert_safe(fake, tour)


def test_the_wrong_wheel_after_start_suspends_the_tour(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    original = fake.press

    def press(vk, hold_ms):
        original(vk, hold_ms)
        fake.events.clear()
        fake.at(500, lambda: fake.load("Sega Genesis", "Sonic"))
    fake.press = press
    _drive(tour, fake, 70)
    assert any('the log shows "Sega Genesis" instead of "Atari 2600"' in line for line in lines)
    _drive(tour, fake, 600)
    assert len(fake.presses) == 1      # suspended: nothing more until a control is used


def test_a_game_starting_after_a_press_suspends_the_tour(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    original = fake.press

    def press(vk, hold_ms):
        original(vk, hold_ms)
        fake.events.clear()
        fake.at(300, lambda: fake.write(_line("Launching Game")))
    fake.press = press
    _drive(tour, fake, 600)
    assert len(fake.presses) == 1
    assert any("a game started after the tour's key press" in line for line in lines)


def test_tour_limit_ends_on_the_main_menu(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(tour_max_minutes=3, consoles_on_main_menu=1,
                                                  games_per_console=50))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 75)
    assert fake.wheel == "Atari 2600"
    # Over the limit inside a console (the landing at 248 s): back to the
    # main menu right after the next spin lands (no video length).
    _drive(tour, fake, 3 * 60 + 45)
    assert [p.vk for p in fake.presses] == [START, EXIT] and fake.wheel == MAIN
    _drive(tour, fake, 30 * 60)
    assert len(fake.presses) == 2
    assert any("tour limit reached" in line for line in lines)


def test_tour_limit_reached_while_waiting_for_a_spin_opens_nothing_more(tmp_path):
    # Console 1 (35 s) is due but has no video length; by the next landing
    # (70 s) the 30-second tour limit has passed: stop on the main menu.
    tour, fake, lines = _tour(tmp_path, _settings(tour_max_minutes=0.5, consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 10 * 60)
    assert fake.presses == []
    assert any("tour limit reached" in line for line in lines)


def test_by_default_the_tour_never_stops(tmp_path):
    # TourMaxMinutes is 0 by default: still changing wheels well past an hour.
    assert it.Settings().tour_max_minutes == 0
    tour, fake, lines = _tour(tmp_path, _settings(tour_max_minutes=it.Settings().tour_max_minutes))
    fake.lists[MAIN] = ["Atari 2600", "Sega Genesis"]
    _drive(tour, fake, 90 * 60)
    late = [p.vk for i, p in enumerate(fake.presses) if _at(fake, i) > 75 * 60_000]
    assert START in late and EXIT in late
    assert not any("tour limit reached" in line for line in lines)
    _assert_safe(fake, tour)


def test_letter_jumps_dont_restart_the_count(tmp_path):
    tour, fake, _ = _tour(tmp_path, _settings(consoles_on_main_menu=2))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 70)              # 2 landings
    fake.write(_line("Main Menu wheel loaded successfully"))
    _drive(tour, fake, 35)              # the 3rd landing opens it
    assert [p.vk for p in fake.presses] == [START]


def test_run_quits_once_hyperspin_has_been_closed_10_seconds(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin")
    lines = []
    tour = it.Tour(_settings(), fake, lines.append, "")
    original = fake.sleep
    calls = []

    def sleep(seconds):
        calls.append(fake.now)
        if len(calls) == 20:
            del fake.running["HyperSpin.exe"]
        original(seconds)
    fake.sleep = sleep
    assert tour.run() == 0
    assert lines[0].startswith("idle-tour: started (a console for 2 games")
    assert lines[-1] == "idle-tour: HyperSpin closed, quitting"
    assert 10_000 <= fake.now - calls[19] <= 10_600


def test_a_restarted_hyperspin_is_followed_from_its_new_log(tmp_path):
    tour, fake, _ = _tour(tmp_path)
    _drive(tour, fake, 40)
    assert tour.hs.landing_seq == 1
    fake.PID = 5151
    fake.running["HyperSpin.exe"] = [5151]
    fake.front = (5151, "ShockwaveFlash")
    fake.log.write_bytes(_line("HyperSpin Started").encode("cp1252"))
    fake.load(MAIN, "MAME")
    tour.attach(5151)
    assert tour.hs_pid == 5151 and tour.hs.wheel == MAIN and tour.hs.selection == "MAME"
    assert tour.seen_landing_seq == tour.hs.landing_seq


def test_warns_when_hyperspins_idle_mode_or_ledblinky_calls_are_off(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin", settings="[AttractMode]\nActive=false\n")
    lines = []
    it.Tour(_settings(), fake, lines.append, "").attach(fake.hyperspin_pid())
    assert any("idle mode is off" in line and "Active=false" in line for line in lines)
    assert any("LEDBlinky calls are off" in line and "(not set)" in line for line in lines)


def test_self_test_reports_and_presses_nothing(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin")
    lines, echoed = [], []
    assert it.run(Config(), None, self_test=True, ops=fake, log=lines.append, echo=echoed.append) == 0
    assert fake.presses == []
    text = "\n".join(echoed)
    assert "HyperSpin's idle mode: Active=true, Time=300" in text
    assert 'wheel "Main Menu", selection "MAME" (main menu yes)' in text
    assert "keys: Start = virtual key 13, Exit = virtual key 27, Down = virtual key 40" in text
    assert "no database, fine: Favorites, Most Played, Recently Played" in text
    assert "Down past items with no video after 8 s" in text
    assert "video of the selection: none (the tour presses Down after 8 s)" in text
    assert lines[0] == "idle-tour: ---- self-test (no keys are pressed)"
    fake.video(MAIN, "MAME", 46.5)
    echoed.clear()
    assert it.run(Config(), None, self_test=True, ops=fake, log=[].append, echo=echoed.append) == 0
    assert "video of the selection: 46.5 s" in echoed
    (fake.folder / "Media" / MAIN / "Video" / "MAME.mp4").write_bytes(b"not a movie")
    echoed.clear()
    assert it.run(Config(), None, self_test=True, ops=fake, log=[].append, echo=echoed.append) == 0
    assert any(line.startswith("video of the selection: length unknown") for line in echoed)


def test_run_does_nothing_when_switched_off_or_already_running(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin")
    off = tmp_path / "off.ini"
    off.write_text("[IdleTour]\nEnabled=0\n", encoding="utf-8")
    echoed = []
    assert it.run(Config(), off, ops=fake, log=[].append, echo=echoed.append) == 0
    assert "switched off" in echoed[-1]
    fake.single_instance = lambda name: False
    assert it.run(Config(), None, ops=fake, log=[].append, echo=echoed.append) == 0
    assert echoed[-1] == "The idle tour is already running."
    assert fake.presses == []


def test_hyperspin_dir_is_the_fallback_when_the_running_exe_isnt_found(tmp_path):
    fake = FakeHyperSpin(tmp_path / "HyperSpin")
    fake.image_path = lambda pid: None
    tour = it.Tour(_settings(), fake, [].append, str(fake.folder))
    tour.attach(fake.hyperspin_pid())
    assert tour.hs_dir == str(fake.folder) and tour.hs.wheel == MAIN


# ── the command ──────────────────────────────────────────────────────────────

def test_command_runs_the_tour_with_the_settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".spindoctor")
    fake = FakeHyperSpin(tmp_path / "HyperSpin")
    monkeypatch.setattr(it, "WindowsTourOps", lambda: fake)
    monkeypatch.setattr("spindoctor.cli._cfg", lambda: Config())
    settings = tmp_path / it.SETTINGS_FILE
    settings.write_text("[IdleTour]\nGamesPerConsole=7\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["toolkit", "idle-tour", "--settings", str(settings), "--self-test"])
    assert result.exit_code == 0, result.output
    assert "a console for 5 min or 7 games" in result.output
    log = (tmp_path / ".spindoctor" / "toolkit.log").read_text(encoding="utf-8")
    assert "idle-tour: ---- self-test" in log and fake.presses == []


def test_command_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    result = CliRunner().invoke(cli, ["toolkit", "idle-tour"])
    assert result.exit_code == 1 and "Windows only" in result.output


# ── Windows ──────────────────────────────────────────────────────────────────

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


@windows_only
def test_windows_ops_build_and_read_without_pressing_anything():
    import ctypes

    ops = it.WindowsTourOps()
    assert ctypes.sizeof(ops._INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    assert ops.tick() > 0 and ops.idle_ms() >= 0
    pid, window_class = ops.foreground()
    assert isinstance(pid, int) and isinstance(window_class, str)
    assert ops.pids("no-such-program.exe") == []
