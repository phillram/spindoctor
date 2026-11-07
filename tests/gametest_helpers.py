"""A fake cabinet and a fake Windows for the ``spindoctor test`` tests.

:func:`build_cabinet` writes a small HyperSpin + RocketLauncher install in a
temp dir.  :class:`FakeWindows` stands in for :class:`spindoctor.gametest.WindowsPlatform`:
a clock that only moves when the code sleeps, a process table, windows, key
presses and screenshots, all driven by a :class:`GameBehaviour` per launch,
so no real program is ever started.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from spindoctor._win32 import ProcInfo, Shot, WinInfo
from spindoctor.config import Config

WORKER_PID = 4000


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _db(path: Path, games: list[tuple]) -> None:
    rows = []
    for g in games:
        name, genre = g[0], g[1] if len(g) > 1 else ""
        enabled = g[2] if len(g) > 2 else "Yes"
        rows.append(f'  <game name="{name}" index="" image="">\n'
                    f"    <description>{name} (USA)</description>\n"
                    f"    <genre>{genre}</genre>\n"
                    f"    <enabled>{enabled}</enabled>\n"
                    f"  </game>")
    _write(path, '<?xml version="1.0"?>\n<menu>\n' + "\n".join(rows) + "\n</menu>\n")


def build_cabinet(tmp_path: Path) -> Config:
    """Wheels: NES (four games, one with no ROM, one disabled), MAME (two,
    using a Games.ini override), PC Games (PCLauncher), Direct (HyperSpin
    launches it itself), Favorites (a SpinDoctor Custom Wheel) and Orphan
    (no RocketLauncher settings)."""
    hs, rl, roms, emu = (tmp_path / n for n in ("hs", "rl", "roms", "emu"))
    menu = ["NES", "MAME", "PC Games", "Direct", "Favorites", "Orphan"]
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml",
           '<?xml version="1.0"?>\n<menu>\n'
           + "".join(f'  <game name="{m}"/>\n' for m in menu)
           + '  <game name="Search" exe="true"/>\n</menu>\n')
    _db(hs / "Databases" / "NES" / "NES.xml",
        [("Alpha", "Shooter"), ("Bravo", "Platform"), ("Charlie", "Shooter / Flying"),
         ("Missing", "Shooter"), ("Hidden", "Shooter", "No")])
    _db(hs / "Databases" / "MAME" / "MAME.xml", [("galaga", "Shooter"), ("pacman", "Maze")])
    _db(hs / "Databases" / "PC Games" / "PC Games.xml", [("Doom", "Shooter")])
    _db(hs / "Databases" / "Direct" / "Direct.xml", [("Thing", "Shooter")])
    _db(hs / "Databases" / "Favorites" / "Favorites.xml", [("Alpha", "Shooter")])
    _write(hs / "Databases" / "Favorites" / ".spindoctor-synthetic")
    _db(hs / "Databases" / "Orphan" / "Orphan.xml", [("Lost", "Shooter")])
    _write(hs / "Settings" / "Direct.ini", "[exe info]\nhyperlaunch=false\n")

    for name in ("Alpha", "Bravo", "Charlie", "Hidden"):
        _write(roms / "NES" / f"{name}.nes", "rom")
    for name in ("galaga", "pacman"):
        _write(roms / "MAME" / f"{name}.zip", "rom")
    for exe in ("nestopia.exe", "mame.exe", "mame2.exe"):
        _write(emu / exe, "exe")

    _write(rl / "RocketLauncher.exe", "exe")
    _write(rl / "Settings" / "Global RocketLauncher.ini",
           "[Exit]\nExit_Emulator_Key=Esc\nExit_Emulator_Key_Wait=0\n")
    _write(rl / "Settings" / "Global Emulators.ini",
           f"[MAME]\nEmu_Path={emu / 'mame.exe'}\nRom_Extension=zip\n")
    _write(rl / "Settings" / "NES" / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator=Nestopia\nRom_Path={roms / 'NES'}\n\n"
           f"[Nestopia]\nEmu_Path={emu / 'nestopia.exe'}\nRom_Extension=nes|zip\n")
    _write(rl / "Settings" / "MAME" / "Emulators.ini",
           f"[ROMS]\nDefault_Emulator=MAME\nRom_Path={roms / 'MAME'}\n\n"
           f"[MAME2]\nEmu_Path={emu / 'mame2.exe'}\nRom_Extension=zip\nModule=..\\MAME\\MAME.ahk\n")
    _write(rl / "Settings" / "MAME" / "Games.ini", "[pacman]\nEmulator=MAME2\n")
    for pc in ("PC Games", "Favorites"):
        _write(rl / "Settings" / pc / "Emulators.ini",
               "[ROMS]\nDefault_Emulator=PCLauncher\nRom_Path=\n\n[PCLauncher]\nRom_Extension=\n")
    for name in ("Nestopia\\Nestopia.ahk", "MAME\\MAME.ahk", "PCLauncher\\PCLauncher.ahk"):
        _write(rl / "Modules" / Path(*name.split("\\")), "; module")
    _write(rl / "Data" / "Statistics" / "NES.ini", "[Alpha]\nNumber_of_Times_Played=1\n")
    _write(rl / "Data" / "Statistics" / "Global Statistics.ini", "[General]\nx=1\n")

    return Config(roms_dir=str(roms), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl),
                  test_results_dir=str(tmp_path / "runs"))


# ─── the fake Windows ─────────────────────────────────────────────────────────

@dataclass
class GameBehaviour:
    """What one launch does, in seconds after RocketLauncher starts."""
    window_after: Optional[float] = 3     # the emulator opens its window (None = never)
    emulator: str = "nestopia.exe"         # "" = RocketLauncher starts nothing
    window: tuple = (0, 0, 1920, 1080)     # left, top, width, height
    title: str = "Nestopia"
    quits_after: Optional[float] = None    # RocketLauncher (and the emulator) end by themselves
    popup: Optional[tuple] = None          # (seconds, title, class, width, height)
    crash_after: Optional[float] = None    # WerFault appears for the emulator
    hung: bool = False
    black: bool = False
    exit_key_works: bool = True
    log: str = ""                          # RocketLauncher.log written at launch
    unzip_for: float = 0                   # a 7z.exe child runs this long first
    helper_window: bool = False            # an AutoHotkey child shows a big window
    other_program_after: Optional[float] = None  # an unrelated new program opens a big window
    writes_stats: bool = True              # RocketLauncher updates the statistics on close


class FakeProc:
    """What ``subprocess.Popen`` returns, for RocketLauncher."""

    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: Optional[int] = None
        self.args = ["RocketLauncher.exe"]

    def poll(self):
        return self.returncode


@dataclass
class HyperSpinBehaviour:
    """What a fake HyperSpin does, in seconds after it starts."""
    intro: bool = True                     # logs "Playing intro video" first
    intro_seconds: float = 110             # until the intro ends by itself
    load_seconds: float = 3                # from the end of the intro to the Main Menu
    reacts_to_keys: bool = True            # Space stops the intro, Esc + Enter quit
    popup: Optional[tuple] = None          # (seconds, title) of a #32770 dialog
    quits_after: Optional[float] = None
    log_lines: tuple = ()                  # extra lines logged at start


class FakeWindows:
    def __init__(self, rl_dir: Path, behaviours: Optional[list[GameBehaviour]] = None,
                 hyperspin: Optional[HyperSpinBehaviour] = None):
        self.rl_dir = rl_dir
        self.hs_dir = rl_dir.parent / "hs"
        self.hyperspin = hyperspin or HyperSpinBehaviour()
        self.hs: Optional[dict] = None         # the running fake HyperSpin
        self.typed: list[list[int]] = []
        self.closed_windows: list[int] = []
        self.behaviours = list(behaviours or [])
        self.t = time.time()
        self.next_pid = 5000
        self.procs: dict[int, ProcInfo] = {
            4: ProcInfo(4, 0, "System"),
            100: ProcInfo(100, 4, "explorer.exe"),
            WORKER_PID: ProcInfo(WORKER_PID, 100, "spindoctor-cli.exe"),
        }
        self.start_times: dict[int, float] = {pid: 1000.0 + pid for pid in self.procs}
        self.windows: list[WinInfo] = [WinInfo(1, 100, "", "Shell_TrayWnd", 0, 1040, 1920, 40)]
        self.fg = 100
        self.cmdlines: dict[int, str] = {}
        self.hung: set[int] = set()
        self.launches: list[list[str]] = []
        self.pressed: list[list[int]] = []
        self.terminated: list[str] = []
        self.current: Optional[dict] = None   # the running launch
        self.on_sleep = None                  # hook(fake) called after every sleep

    # -- process table helpers
    def add_proc(self, name: str, parent: int, started: Optional[float] = None) -> int:
        pid = self.next_pid
        self.next_pid += 7
        self.procs[pid] = ProcInfo(pid, parent, name)
        self.start_times[pid] = self.t if started is None else started
        return pid

    def remove(self, pid: int) -> None:
        self.procs.pop(pid, None)
        self.windows = [w for w in self.windows if w.pid != pid]
        self.hung.discard(pid)
        if self.current and pid == self.current["rl"].pid and self.current["rl"].returncode is None:
            self.current["rl"].returncode = 0
        if self.hs and pid == self.hs["proc"].pid:
            self.hs["proc"].returncode = 0
            if self.fg == pid:
                self.fg = 100

    def add_window(self, pid: int, title: str, cls: str, rect: tuple) -> int:
        hwnd = 100 + len(self.windows) * 3 + pid
        self.windows.insert(0, WinInfo(hwnd, pid, title, cls, *rect))
        return hwnd

    # -- the platform interface
    def list_processes(self):
        return list(self.procs.values())

    def list_windows(self):
        return list(self.windows)

    def foreground_pid(self) -> int:
        return self.fg

    def bring_to_front(self, hwnd: int) -> None:
        for w in self.windows:
            if w.hwnd == hwnd:
                self.fg = w.pid

    def is_hung(self, hwnd: int) -> bool:
        return any(w.hwnd == hwnd and w.pid in self.hung for w in self.windows)

    def press_keys(self, vks, hold_ms) -> None:
        self.pressed.append(list(vks))
        cur = self.current
        if cur and cur["b"].exit_key_works:
            self._game_over(cur)

    def type_keys(self, vks) -> None:
        self.typed.append(list(vks))
        hs = self.hs
        if not hs or hs["proc"].returncode is not None or self.fg != hs["proc"].pid:
            return
        if not hs["b"].reacts_to_keys:
            return
        for vk in vks:
            if vk == 0x20 and hs["stage"] == "intro":
                hs["stage"], hs["stage_at"] = "loading", self.t
            elif vk == 0x1B and hs["stage"] == "loaded":
                hs["exit_menu"] = True
            elif vk == 0x0D and hs.get("exit_menu"):
                self.remove(hs["proc"].pid)

    def close_window(self, hwnd: int) -> None:
        self.closed_windows.append(hwnd)
        for w in list(self.windows):
            if w.hwnd == hwnd:
                self.remove(w.pid)

    def terminate(self, pid: int) -> bool:
        if pid not in self.procs:
            return False
        self.terminated.append(self.procs[pid].name)
        cur = self.current
        self.remove(pid)
        if cur and pid == cur.get("emu"):
            # RocketLauncher notices its emulator is gone and quits.
            self._game_over(cur)
        return True

    def start_time(self, pid: int):
        return self.start_times.get(pid) if pid in self.procs else None

    def command_line(self, pid: int) -> str:
        return self.cmdlines.get(pid, "")

    def screen_size(self):
        return 1920, 1080

    def capture(self, thumb_width: int):
        cur = self.current
        black = bool(cur and cur["b"].black)
        w, h = 192, 108
        px = (b"\x00\x00\x00\x00" if black else b"\x80\x90\xa0\x00") * (w * h)
        tw, th = 48, 27
        return Shot(w, h, px, tw, th, px[: tw * th * 4], "fake")

    def start(self, args, cwd):
        self.launches.append(list(args))
        exe = Path(args[0]).name.lower()
        if exe == "hyperspin.exe":
            return self._start_hyperspin()
        if exe != "rocketlauncher.exe":  # e.g. LEDBlinky.exe 2: runs and ends at once
            proc = FakeProc(self.next_pid)
            proc.returncode = 0
            return proc
        b = self.behaviours.pop(0) if self.behaviours else GameBehaviour()
        proc = FakeProc(self.add_proc("RocketLauncher.exe", WORKER_PID))
        self.current = {"rl": proc, "b": b, "t0": self.t, "emu": None, "game": args[2],
                        "system": args[1], "popup": False, "crash": False, "other": False,
                        "helper": None, "zip": None}
        log = self.rl_dir / "RocketLauncher.log"
        log.write_text(b.log, encoding="utf-8")
        os.utime(log, (self.t, self.t))
        if b.unzip_for:
            self.current["zip"] = self.add_proc("7z.exe", proc.pid)
        if b.helper_window:
            ahk = self.add_proc("AutoHotkey.exe", proc.pid)
            self.add_window(ahk, "AHK overlay", "AutoHotkeyGUI", (0, 0, 1920, 1080))
        return proc

    def worker_pid(self) -> int:
        return WORKER_PID

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
        self._advance()
        self._advance_hyperspin()
        if self.on_sleep is not None:
            self.on_sleep(self)

    # -- what the fake HyperSpin does over time
    def _start_hyperspin(self) -> FakeProc:
        b = self.hyperspin
        proc = FakeProc(self.add_proc("HyperSpin.exe", WORKER_PID))
        hwnd = self.add_window(proc.pid, "HyperSpin", "ShockwaveFlash", (0, 0, 1920, 1080))
        self.fg = proc.pid
        self.hs = {"proc": proc, "b": b, "t0": self.t, "hwnd": hwnd, "popup": False,
                   "stage": "intro" if b.intro else "loading", "stage_at": self.t}
        self._hs_log("HyperSpin started", *b.log_lines, fresh=True)  # HyperSpin starts a new log.txt
        if b.intro:
            self._hs_log("Playing intro video")
        return proc

    def _hs_log(self, *lines: str, fresh: bool = False) -> None:
        log = self.hs_dir / "log.txt"
        with open(log, "w" if fresh else "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(f"12:00:00 PM |  {line}\n")
        os.utime(log, (self.t, self.t))

    def _advance_hyperspin(self) -> None:
        hs = self.hs
        if not hs or hs["proc"].returncode is not None:
            return
        b, e = hs["b"], self.t - hs["t0"]
        if hs["stage"] == "intro" and e >= b.intro_seconds:
            hs["stage"], hs["stage_at"] = "loading", self.t
        if hs["stage"] == "loading" and self.t - hs["stage_at"] >= b.load_seconds:
            hs["stage"] = "loaded"
            self._hs_log("Main Menu wheel loaded successfully")
        if b.popup and not hs["popup"] and e >= b.popup[0]:
            hs["popup"] = True
            self.add_window(hs["proc"].pid, b.popup[1], "#32770", (700, 400, 400, 200))
        if b.quits_after is not None and e >= b.quits_after:
            self.remove(hs["proc"].pid)

    # -- what the running game does over time
    def _advance(self) -> None:
        cur = self.current
        if not cur or cur["rl"].returncode is not None:
            return
        b, rl = cur["b"], cur["rl"]
        e = self.t - cur["t0"]
        if cur["zip"] and e >= b.unzip_for:
            self.remove(cur["zip"])
            cur["zip"] = None
        start_at = (b.window_after or 0) + b.unzip_for
        if cur["emu"] is None and b.emulator and e >= start_at and not cur["zip"]:
            if b.window_after is not None or b.quits_after is None:
                cur["emu"] = self.add_proc(b.emulator, rl.pid)
                if b.window_after is not None:
                    self.add_window(cur["emu"], b.title, "Emu", b.window)
                    self.fg = cur["emu"]
                if b.hung:
                    self.hung.add(cur["emu"])
        if b.popup and not cur["popup"] and e >= b.popup[0] and cur["emu"]:
            cur["popup"] = True
            self.add_window(cur["emu"], b.popup[1], b.popup[2], (700, 400, b.popup[3], b.popup[4]))
        if b.crash_after is not None and not cur["crash"] and e >= b.crash_after and cur["emu"]:
            cur["crash"] = True
            wer = self.add_proc("WerFault.exe", 900)
            self.cmdlines[wer] = f"C:\\Windows\\system32\\WerFault.exe -u -p {cur['emu']} -s 123"
        if b.other_program_after is not None and not cur["other"] and e >= b.other_program_after:
            cur["other"] = True
            other = self.add_proc("game.exe", 7777)
            self.add_window(other, "The Game", "GameWnd", (0, 0, 1920, 1080))
            self.fg = other
            if cur["emu"] is None:
                cur["emu"] = other
        if b.quits_after is not None and e >= b.quits_after:
            self._game_over(cur)

    def _game_over(self, cur: dict) -> None:
        """The emulator and RocketLauncher end; RocketLauncher writes the stats."""
        for pid in [cur["emu"], cur["rl"].pid]:
            if pid is not None:
                self.procs.pop(pid, None)
                self.windows = [w for w in self.windows if w.pid != pid]
        if cur["rl"].returncode is None:
            cur["rl"].returncode = 0
            if cur["b"].writes_stats:
                self.write_stats(cur["system"], cur["game"])
        self.fg = 100

    def write_stats(self, system: str, game: str) -> None:
        stats = self.rl_dir / "Data" / "Statistics"
        with open(stats / f"{system}.ini", "a", encoding="utf-8") as fh:
            fh.write(f"\n[{game}]\nNumber_of_Times_Played=99\n")
        (stats / "Global Statistics.ini").write_text("[General]\nx=2\n", encoding="utf-8")


@dataclass
class Recorder:
    """Collects ``run_plan``'s ``on_result`` calls."""
    calls: list = field(default_factory=list)

    def __call__(self, number, total, item, result, left):
        self.calls.append((number, total, item.game, result.status, result.reason))
