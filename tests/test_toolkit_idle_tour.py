"""`spindoctor toolkit idle-tour`: HyperSpin's idle mode, touring the consoles.

The tour reads HyperSpin's live ``log.txt`` and presses HyperSpin's Exit and
Start keys.  Here it runs against :class:`FakeHyperSpin`, which writes a real
``log.txt`` (the lines HyperSpin 1.5 writes) under tmp_path on a fake clock,
spins like HyperSpin's idle mode and reacts to the keys the way HyperSpin
does, so no window, key or process of this PC is touched.  The Windows-only
tests at the end only build the ctypes structures and read the process list.
"""
from __future__ import annotations

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
EXIT, START = 0x1B, 0x0D
LEDBLINKY = '"D:\\Arcade\\LEDBlinky\\LEDBlinky.exe"'


def _line(text):
    return f"02:40:10 PM |  {text} \r\n"


def _call(args):
    return _line(f"Command Line is: {LEDBLINKY} {args}")


class Press(NamedTuple):
    at: int
    vk: int
    hold: int
    wheel: str
    selection: str
    exit_menu: bool


class FakeHyperSpin:
    """HyperSpin, as far as the tour can see it.

    Its idle mode spins every *interval* ms (each spin *spin* ms long) and
    lands on the next name of the wheel's list.  Exit in a console goes back
    to the main menu, Start on the main menu opens the console selected, each
    *delay* ms later; Exit on the main menu opens the exit menu, which logs
    nothing and stops the idle spins.  A player's touch stops the idle mode.
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
        self.idle_on = True
        self.ignore_keys = False
        self.interval, self.spin, self.delay = 30_000, 5_000, 800
        self.next_spin = self.now + self.interval
        self.turn = {}
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
        self.at(delay // 2, lambda: (self.write(_call("8")), self.write(_call(f'7 "{name}"'))))
        self.at(delay, lambda: self.load(name, f"{name} game 1"))

    def load(self, wheel, selection):
        self.wheel = wheel
        self.write(_line(f"{wheel} wheel loaded successfully"))
        self.select(selection)
        self.next_spin = self.now + self.interval

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
                landing = self._next_name()

                def land(name=landing):
                    self.write(_call("6"))
                    self.select(name)
                self.events.append((self.now + self.spin, land))
                self.next_spin = self.now + self.spin + self.interval
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
        self.presses.append(Press(self.now, vk, hold_ms, self.wheel, self.selection, self.exit_menu))
        self.now += hold_ms
        self.last_input = self.now          # Windows counts the tour's own presses as input too
        if self.ignore_keys or self.exit_menu:
            return
        if vk == EXIT:
            if self.wheel == MAIN:
                self.exit_menu = True       # logs nothing
            else:
                left = self.wheel
                self.at(self.delay // 2, lambda: self.write(_call("4")))
                self.at(self.delay, lambda: self.load(MAIN, left))
        elif vk == START and self.wheel == MAIN:
            self.open_console(self.selection, self.delay * 2)

    def single_instance(self, name):
        return True


def _settings(**kw):
    base = dict(console_minutes=0, games_per_console=2, main_menu_minutes=0, consoles_on_main_menu=2,
                tour_max_minutes=0, skip=("Toolkit",))
    base.update(kw)
    return it.Settings(**base)


def _tour(tmp_path, settings=None, **fake_kw):
    fake = FakeHyperSpin(tmp_path / "HyperSpin", **fake_kw)
    lines = []
    tour = it.Tour(settings or _settings(), fake, lines.append, "")
    tour.attach(fake.hyperspin_pid())
    return tour, fake, lines


def _drive(tour, fake, seconds):
    end = fake.now + int(seconds * 1000)
    while fake.now < end:
        fake.sleep(it.POLL)
        tour.step()


def _assert_safe(fake, tour=None):
    """Exit only inside a console, Start only on the main menu on a console the
    tour may open, never with the exit menu open, every key held 80 ms."""
    for p in fake.presses:
        assert not p.exit_menu, p
        assert p.hold == 80, p
        if p.vk == EXIT:
            assert p.wheel != MAIN, p
        else:
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
            s.tour_max_minutes, s.key_hold_ms, s.quiet_ms) == (5, 5, 5, 5, 60, 80, 1500)
    assert s.skips("toolkit") and s.skips("Favorites ") and not s.skips("MAME")


def test_the_settings_file_install_tools_writes_reads_back_as_the_defaults(tmp_path):
    path = tmp_path / it.SETTINGS_FILE
    path.write_bytes(it.DEFAULT_SETTINGS_TEXT.encode("utf-8"))
    assert it.read_settings(path) == it.Settings()
    assert b"\r\n" in path.read_bytes() and b"\r\r" not in path.read_bytes()


def test_settings_are_read_like_windows_reads_an_ini(tmp_path):
    path = tmp_path / "s.ini"
    path.write_text(
        "\ufeff[idletour]\nenabled=0\nCONSOLEMINUTES=2.5\nGamesPerConsole=abc\nMainMenuMinutes=-1\n"
        "ConsolesOnMainMenu=0\nSkip= Toolkit | Sony PSP ||\nPauseWhile=Tester.exe\nKeyHoldMs=120\n",
        encoding="utf-8")
    s = it.read_settings(path)
    assert not s.enabled and s.console_minutes == 2.5
    assert s.games_per_console == 5 and s.main_menu_minutes == 5    # bad values keep the default
    assert s.consoles_on_main_menu == 0 and s.key_hold_ms == 120
    assert s.skip == ("Toolkit", "Sony PSP") and s.pause_while == ("Tester.exe",)


def test_keys_come_from_hyperspins_player_1_controls(tmp_path):
    (tmp_path / "Settings").mkdir()
    ini = tmp_path / "Settings" / "Settings.ini"
    assert it.hyperspin_keys(tmp_path) == it.Keys(13, 27) == it.hyperspin_keys("")
    ini.write_text("[P1 Controls]\nStart=49\nExit=8\n[P2 Controls]\nStart=50\n", encoding="utf-8")
    assert it.hyperspin_keys(tmp_path) == it.Keys(49, 8)
    ini.write_text("[P1 Controls]\nStart=x\nExit=999\n", encoding="utf-8")
    assert it.hyperspin_keys(tmp_path) == it.Keys(13, 27)


# ── the tour ─────────────────────────────────────────────────────────────────

def test_main_menu_opens_the_console_a_spin_landed_on_after_the_count(tmp_path):
    tour, fake, lines = _tour(tmp_path)
    fake.lists[MAIN] = ["Sega Genesis", "Sega Genesis", "Atari 2600"]
    _drive(tour, fake, 110)             # landings at 35, 70 and 105 s
    # Counted from the first spin: 2 consoles shown, then the 3rd landing is opened.
    assert [p.vk for p in fake.presses] == [START]
    assert fake.presses[0].selection == "Atari 2600" and fake.wheel == "Atari 2600"
    assert any("opened Atari 2600 after" in line and "3 idle spins" in line for line in lines)
    _assert_safe(fake, tour)


def test_console_goes_back_to_the_main_menu_after_the_count(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 75)
    assert fake.wheel == "Atari 2600"
    _drive(tour, fake, 110)
    assert [p.vk for p in fake.presses] == [START, EXIT]
    assert fake.presses[1].wheel == "Atari 2600" and fake.wheel == MAIN
    assert any("back on the main menu after" in line and "in Atari 2600" in line for line in lines)
    _assert_safe(fake, tour)


def test_a_long_tour_only_ever_presses_safely(tmp_path):
    tour, fake, lines = _tour(tmp_path)
    fake.lists[MAIN] = ["Toolkit", "Atari 2600", "No Database", "Sega Genesis", "Toolkit"]
    _drive(tour, fake, 60 * 60)
    assert len(fake.presses) >= 20
    assert {p.vk for p in fake.presses} == {START, EXIT}
    assert {p.selection for p in fake.presses if p.vk == START} <= {"Atari 2600", "Sega Genesis"}
    _assert_safe(fake, tour)
    assert any("(skipped)" in line for line in lines)


def test_minutes_count_too_whichever_comes_first(tmp_path):
    tour, fake, _ = _tour(tmp_path, _settings(main_menu_minutes=1, consoles_on_main_menu=0))
    fake.lists[MAIN] = ["Atari 2600"]
    _drive(tour, fake, 64)      # landings at 35 and 70 s: the first starts the count
    assert fake.presses == []
    _drive(tour, fake, 60)      # 70 s is 35 s in; 105 s is past the minute
    assert [p.vk for p in fake.presses] == [START]
    assert fake.presses[0].at - 1_105_000 < 2_000
    # Both limits off: it never changes wheels.
    tour2, fake2, _ = _tour(tmp_path / "b", _settings(main_menu_minutes=0, consoles_on_main_menu=0))
    _drive(tour2, fake2, 600)
    assert fake2.presses == []


def test_skipped_and_database_less_consoles_are_never_opened(tmp_path):
    tour, fake, lines = _tour(tmp_path, _settings(consoles_on_main_menu=1))
    fake.lists[MAIN] = ["Toolkit", "No Database"]
    _drive(tour, fake, 600)
    assert fake.presses == []
    assert any("landed on Toolkit (skipped)" in line for line in lines)
    assert any("landed on No Database (skipped)" in line for line in lines)
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
    assert fake.wheel == "Atari 2600"
    fake.ignore_keys = True
    _drive(tour, fake, 100)             # landings in the console at 108 and 143 s: one Exit
    exits = [p for p in fake.presses if p.vk == EXIT]
    assert len(exits) == 1
    assert any("didn't bring the main menu within 15 s" in line for line in lines)
    _drive(tour, fake, 40)              # the next landing (178 s): tried once more
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
    _drive(tour, fake, 3 * 60)          # over the limit inside a console: back to the main menu
    assert [p.vk for p in fake.presses] == [START, EXIT] and fake.wheel == MAIN
    _drive(tour, fake, 30 * 60)
    assert len(fake.presses) == 2
    assert any("tour limit reached" in line for line in lines)


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
    assert "keys: Start = virtual key 13, Exit = virtual key 27" in text
    assert "no database, fine: Favorites, Most Played, Recently Played" in text
    assert lines[0] == "idle-tour: ---- self-test (no keys are pressed)"


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
