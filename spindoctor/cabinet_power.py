"""Leave the cabinet from HyperSpin: the Toolkit power helpers.

`install-tools --tool shut-down-cabinet` adds a helper that runs
``spindoctor toolkit shutdown``.  Every helper that leaves HyperSpin shares
the one sequence in :func:`run`:

1. A full-screen countdown, "Shutting down in 5" over "Press Esc to cancel"
   (:mod:`spindoctor.toolkit_screen`).  Esc stops here and puts HyperSpin back
   in front.
2. HyperSpin is closed the polite way, with ``WM_CLOSE``, so it saves its
   settings and runs its exit programs.  A RocketLauncher still running is
   ended first: HyperSpin waiting for its "game" ignores the close.  HyperSpin
   is forced after 3 s.
3. LEDBlinky is told to quit (``LEDBlinky.exe 2``), because HyperSpin sends
   that only on its own exit, not when it is closed from outside, and the
   panel would stay on the last layout.  Not twice: if HyperSpin's
   ``log.txt`` shows it sent the quit, none is sent.  Nothing waits for its
   quit animation, which can run for half a minute.
4. The action, at once.  Shut Down runs ``shutdown.exe /s /f /t 0`` and
   Restart ``shutdown.exe /r /f /t 0`` (``/f`` so an "app is preventing
   shutdown" screen can't stall it; Windows ends LEDBlinky and HyperSpin's
   exit programs with everything else).  If Windows refuses, HyperSpin is
   started again so the cabinet isn't left on the desktop.  Exit To Windows:
   the screen goes, Explorer is restarted so the taskbar HyperSpin hid comes
   back, and only then, with no window, are HyperSpin's startup script and
   LEDBlinky's quit waited for (:func:`settle`), and every PAC-LED64 light is
   set to 0 (:func:`lights_off`), since LEDBlinky's quit can leave a board lit.

Every step is logged to ``~/.spindoctor/toolkit.log``.  The Windows calls sit
behind :class:`WindowsOps`, so tests drive the sequence with fakes.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional

from . import config as config_mod

HYPERSPIN = "HyperSpin.exe"
ROCKETLAUNCHER = "RocketLauncher.exe"
LEDBLINKY = "LEDBlinky.exe"
#: HyperSpin's own helper, which runs the exit programs set in HyperHQ.
STARTUP_SCRIPT = "HyperSpin Startup Script.exe"
CLOSE_WAIT = 3.0     # HyperSpin closes in under a second; one that hasn't by then won't
FORCE_WAIT = 5.0     # … and to go after it is terminated
HOLD_AFTER = 30.0    # the black screen stays up while Windows closes everything
EXPLORER_WAIT = 1.5  # Windows usually starts a new Explorer by itself within this
HELPER_WAIT = 5.0    # HyperSpin's startup script, once on the desktop
LEDBLINKY_WAIT = 30.0  # LEDBlinky's random quit animation (8-25 s seen on a real cabinet)
LOG_NAME = "toolkit.log"
LOG_LIMIT = 256 * 1024


class Action(NamedTuple):
    verb: str                     # "Shutting down": the countdown's first word(s)
    finish: Callable[..., int]    # (ctx) -> exit code, once HyperSpin is closed


class _Context(NamedTuple):
    mode: str
    config: object
    ops: "WindowsOps"
    log: Callable[[str], None]
    screen: object
    hyperspin: Optional[str]      # the HyperSpin.exe that was running, if any


def log_to_file(line: str) -> None:
    """Append *line* to ``~/.spindoctor/toolkit.log``, keeping one older file."""
    path = Path(config_mod.CONFIG_DIR) / LOG_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > LOG_LIMIT:
            os.replace(str(path), str(path.with_name(LOG_NAME + ".1")))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
    except OSError:
        pass  # a log that can't be written must not stop the helper


def _system32(name: str) -> str:
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", name)


def _windows_power(flag: str) -> Callable[[_Context], int]:
    """Finish with ``shutdown.exe <flag> /f /t 0``; start HyperSpin again if refused."""
    def finish(ctx: _Context) -> int:
        args = [_system32("shutdown.exe"), flag, "/f", "/t", "0"]
        ctx.log(f"{ctx.mode}: running shutdown.exe {flag} /f /t 0")
        code = ctx.screen.run(lambda: ctx.ops.run(args))
        if code == 0:
            ctx.log(f"{ctx.mode}: Windows accepted it")
            ctx.screen.hold(HOLD_AFTER)
            return 0
        ctx.log(f"{ctx.mode}: shutdown.exe failed (exit code {code}), starting HyperSpin again")
        ctx.screen.close()
        restart_hyperspin(ctx)
        return 1
    return finish


def _to_desktop(ctx: _Context) -> int:
    """Finish on the Windows desktop, with the taskbar back.

    HyperSpin hides the taskbar and shows it again only on its own exit, not
    after an outside ``WM_CLOSE``; a fresh Explorer draws it again.  Only the
    countdown should take time, so the screen goes first, and LEDBlinky's quit
    animation is waited for afterwards, with no window.
    """
    ctx.screen.close()
    ctx.log(f"{ctx.mode}: restarting Explorer")
    old = set(ctx.ops.pids("explorer.exe"))
    ctx.ops.run([_system32("taskkill.exe"), "/F", "/IM", "explorer.exe"])
    end = time.monotonic() + EXPLORER_WAIT
    while not [pid for pid in ctx.ops.pids("explorer.exe") if pid not in old]:
        if time.monotonic() >= end:
            explorer = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "explorer.exe")
            try:
                ctx.ops.start(explorer)
                ctx.log(f"  started {explorer}")
            except OSError as exc:
                ctx.log(f"  could not start {explorer}: {exc}")
                return 1
            break
        time.sleep(0.1)
    else:
        ctx.log("  Windows started Explorer again by itself")
    ctx.log(f"{ctx.mode}: on the desktop")
    settle(ctx)
    return 0


#: The helpers that leave HyperSpin, by ``spindoctor toolkit`` command.
ACTIONS: dict = {
    "shutdown": Action("Shutting down", _windows_power("/s")),
    "restart": Action("Restarting", _windows_power("/r")),
    "exit-to-windows": Action("Exiting to Windows", _to_desktop),
}


def run(mode: str, config, *, seconds: int = 5, screen=None, ops=None,
        log: Optional[Callable[[str], None]] = None) -> int:
    """Count down, close HyperSpin, then do *mode*'s action.

    Returns 0 when it went ahead or was cancelled, 1 when Windows refused.
    *screen*, *ops* and *log* default to the real window, Windows and the log
    file.
    """
    action = ACTIONS[mode]
    log = log or log_to_file
    ops = ops or WindowsOps()
    if screen is None:
        from .toolkit_screen import Screen

        screen = Screen("SpinDoctor")
    log(f"{mode}: countdown started ({seconds} s)")
    try:
        if not screen.count(action.verb, seconds):
            log(f"{mode}: cancelled with Esc")
            screen.close()
            ops.activate(HYPERSPIN)
            return 0
        screen.show(f"{action.verb}…")
        log(f"{mode}: closing HyperSpin")
        hyperspin = screen.run(lambda: close_hyperspin(ops, log))
        quit_ledblinky(ops, config, hyperspin, log)
        return action.finish(_Context(mode, config, ops, log, screen, hyperspin))
    finally:
        screen.close()


def close_hyperspin(ops, log: Callable[[str], None]) -> Optional[str]:
    """Close HyperSpin the way its own exit does; the EXE it ran from, or None."""
    pids = ops.pids(HYPERSPIN)
    if not pids:
        log("  HyperSpin was not running")
        return None
    exe = ops.image_path(pids[0])
    # HyperSpin still waiting for RocketLauncher's "game" ignores WM_CLOSE.
    launcher = ops.pids(ROCKETLAUNCHER)
    if launcher:
        for pid in launcher:
            ops.terminate(pid)
        ops.wait_exit(launcher, FORCE_WAIT)
        log("  RocketLauncher was still running, closed it")
    ops.post_close(pids)
    if ops.wait_exit(pids, CLOSE_WAIT):
        log("  HyperSpin closed")
    else:
        log(f"  HyperSpin did not close within {CLOSE_WAIT:g} s, forcing it")
        for pid in pids:
            ops.terminate(pid)
        ops.wait_exit(pids, FORCE_WAIT)
    return exe


def _hyperspin_sent_quit(hyperspin: Optional[str], config) -> bool:
    """True when the last LEDBlinky command in HyperSpin's ``log.txt`` is its
    quit (``2``): HyperSpin closed by itself and already told LEDBlinky."""
    folder = os.path.dirname(hyperspin) if hyperspin else getattr(config, "hyperspin_dir", "")
    if not folder:
        return False
    from ._text import read_windows_text

    try:
        text = read_windows_text(Path(folder) / "log.txt")
    except OSError:
        return False
    # Lines read  Command Line is: "D:\...\LEDBlinky.exe" 2  (a quoted EXE, then the command).
    sent = re.findall(r'LEDBlinky\.exe"[ \t]+(\S+)', text, flags=re.IGNORECASE)
    return bool(sent) and sent[-1].strip('"') == "2"


def quit_ledblinky(ops, config, hyperspin: Optional[str], log: Callable[[str], None]) -> None:
    """Tell a running LEDBlinky to quit (``LEDBlinky.exe 2``), without waiting.

    HyperSpin sends this only on its own exit, so after an outside close the
    panel would stay on the last game's layout.  A second quit can restart the
    quit animation, so none is sent when HyperSpin's log shows it sent one.
    """
    pids = ops.pids(LEDBLINKY)
    if not pids:
        log("  LEDBlinky was not running")
        return
    if _hyperspin_sent_quit(hyperspin, config):
        log("  HyperSpin already sent LEDBlinky its quit")
        return
    exe = ops.image_path(pids[0])
    if not exe and getattr(config, "ledblinky_dir", ""):
        exe = str(Path(config.ledblinky_dir) / LEDBLINKY)
    if not exe:
        log("  LEDBlinky is running, but its EXE wasn't found: not told to quit")
        return
    try:
        ops.start(exe, ["2"])
        log("  sent LEDBlinky its quit (LEDBlinky.exe 2)")
    except OSError as exc:
        log(f"  could not run {exe} 2: {exc}")


def settle(ctx: _Context) -> None:
    """Wait for HyperSpin's startup script and LEDBlinky to finish quitting.

    Exit To Windows runs this once the desktop is back, with no window.
    LEDBlinky still running after :data:`LEDBLINKY_WAIT` (its quit animation)
    is ended.  Then every PAC-LED64 light is turned off.
    """
    script = ctx.ops.pids(STARTUP_SCRIPT)
    if script and not ctx.ops.wait_exit(script, HELPER_WAIT):
        ctx.log(f"  {STARTUP_SCRIPT} still running after {HELPER_WAIT:g} s")
    ledblinky = ctx.ops.pids(LEDBLINKY)
    if ledblinky:
        started = time.monotonic()
        if ctx.ops.wait_exit(ledblinky, LEDBLINKY_WAIT):
            ctx.log(f"  LEDBlinky quit (waited {time.monotonic() - started:.1f} s)")
        else:
            for pid in ledblinky:
                ctx.ops.terminate(pid)
            ctx.ops.wait_exit(ledblinky, FORCE_WAIT)
            ctx.log(f"  LEDBlinky still running after {LEDBLINKY_WAIT:g} s, ended it")
    lights_off(ctx)


def lights_off(ctx: _Context) -> None:
    """Every PAC-LED64 light to 0, through the ``PacDrive32.dll`` in ``ledblinky_dir``.

    LEDBlinky's quit can leave a board lit (on a real cabinet, the second board
    stayed purple).  Skipped while LEDBlinky runs, so the two never fight, and
    when there's no DLL to use.
    """
    if ctx.ops.pids(LEDBLINKY):
        ctx.log("  LEDBlinky is running: lights left to it")
        return
    from . import button_lights

    dll = button_lights.find_dll(ctx.config)
    if dll is None:
        if getattr(ctx.config, "ledblinky_dir", ""):
            ctx.log(f"  no {button_lights.DLL_NAME} in ledblinky_dir: lights left as they are")
        return
    result = button_lights.lights_off(dll)
    if result.error:
        ctx.log(f"  lights off failed: {result.error}")
    elif result.boards:
        ctx.log("  lights off: " + ", ".join(f"board {b.number} off: {b.all_ok}" for b in result.boards)
                + f" ({result.devices} Ultimarc device(s))")


def restart_hyperspin(ctx: _Context) -> None:
    """Start the HyperSpin that was closed (or the configured one) again."""
    exe = ctx.hyperspin
    if not exe and getattr(ctx.config, "hyperspin_dir", ""):
        candidate = Path(ctx.config.hyperspin_dir) / HYPERSPIN
        exe = str(candidate) if candidate.is_file() else None
    if not exe:
        ctx.log("  no HyperSpin.exe to start")
        return
    try:
        ctx.ops.start(exe)
        ctx.log(f"  started {exe}")
    except OSError as exc:
        ctx.log(f"  could not start {exe}: {exc}")


# ─── Windows ──────────────────────────────────────────────────────────────────

class WindowsOps:
    """The process and window calls :func:`run` needs, through ``ctypes``."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        self._c, self._w = ctypes, w
        k = self._k = ctypes.WinDLL("kernel32", use_last_error=True)
        u = self._u = ctypes.WinDLL("user32", use_last_error=True)
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.WaitForSingleObject.restype = w.DWORD
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.QueryFullProcessImageNameW.restype = w.BOOL
        self._enum_proc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        u.EnumWindows.argtypes = [self._enum_proc, w.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.GetWindowThreadProcessId.restype = w.DWORD
        u.IsWindowVisible.argtypes = [w.HWND]
        u.GetWindow.argtypes = [w.HWND, w.UINT]
        u.GetWindow.restype = w.HWND
        u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]

    def pids(self, name: str) -> "list[int]":
        """Process IDs whose EXE file name is *name*, ignoring case."""
        ctypes, w = self._c, self._w

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD),
                ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", w.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        k = self._k
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        snapshot = k.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
        if snapshot in (None, ctypes.c_void_p(-1).value):
            return []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            found, me, want = [], os.getpid(), name.lower()
            ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == want and entry.th32ProcessID != me:
                    found.append(entry.th32ProcessID)
                ok = k.Process32NextW(snapshot, ctypes.byref(entry))
            return found
        finally:
            k.CloseHandle(snapshot)

    def image_path(self, pid: int) -> Optional[str]:
        handle = self._k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = self._w.DWORD(32768)
            buf = self._c.create_unicode_buffer(size.value)
            if self._k.QueryFullProcessImageNameW(handle, 0, buf, self._c.byref(size)):
                return buf.value
            return None
        finally:
            self._k.CloseHandle(handle)

    def _top_windows(self, pids, owned: bool = False) -> list:
        """Visible top-level windows of *pids*, in z-order; owned ones too if *owned*."""
        wanted, found = set(pids), []

        def each(hwnd, _lparam):
            owner = self._w.DWORD()
            self._u.GetWindowThreadProcessId(hwnd, self._c.byref(owner))
            if (owner.value in wanted and self._u.IsWindowVisible(hwnd)
                    and (owned or not self._u.GetWindow(hwnd, 4))):  # GW_OWNER
                found.append(hwnd)
            return True

        self._u.EnumWindows(self._enum_proc(each), 0)
        return found

    def post_close(self, pids) -> int:
        """Ask every visible window of *pids* to close (``WM_CLOSE``); how many."""
        windows = self._top_windows(pids, owned=True)
        for hwnd in windows:
            self._u.PostMessageW(hwnd, 0x0010, 0, 0)
        return len(windows)

    def wait_exit(self, pids, timeout: float) -> bool:
        """Wait up to *timeout* seconds for all *pids* to end; True if they did."""
        end = time.monotonic() + timeout
        for pid in pids:
            handle = self._k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                continue  # already gone
            try:
                left = max(0, int((end - time.monotonic()) * 1000))
                if self._k.WaitForSingleObject(handle, left) != 0:  # WAIT_OBJECT_0
                    return False
            finally:
                self._k.CloseHandle(handle)
        return True

    def terminate(self, pid: int) -> None:
        from ._runtime import _terminate_pid

        _terminate_pid(pid)

    def run(self, args) -> int:
        """Run *args* without a window; its exit code (-1 if it can't start)."""
        try:
            return subprocess.run(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=0x08000000,  # CREATE_NO_WINDOW
            ).returncode
        except OSError:
            return -1

    def start(self, exe: str, args=()) -> None:
        """Start *exe* with *args* from its own folder, detached from this process."""
        subprocess.Popen(
            [exe, *args], cwd=os.path.dirname(exe) or None, close_fds=True,
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        )

    def activate(self, name: str) -> bool:
        """Bring *name*'s main window to the front, if it is running."""
        windows = self._top_windows(self.pids(name))
        if not windows:
            return False
        from .toolkit_screen import bring_to_front

        return bring_to_front(windows[0])
