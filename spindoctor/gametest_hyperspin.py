"""HyperSpin itself, for ``spindoctor test --with-hyperspin``.

:func:`start_and_check` opens ``<hyperspin_dir>\\HyperSpin.exe`` and judges its
startup from its ``log.txt``: it must log ``wheel loaded successfully`` within
``test_hyperspin_timeout`` seconds, show no error dialog and not close.  The
intro video is skipped the way a player would, by pressing a key while
HyperSpin's log says ``Playing intro video`` (HyperSpin's own
``[IntroVideo] Stop_On_Keypress=true``); Space, because no HyperSpin control
uses it, so a press that lands as the intro ends does nothing.  :func:`close`
leaves through HyperSpin's exit menu (Esc, then Enter), and only closes or
ends it when that doesn't work, then tells LEDBlinky the frontend quit as
HyperSpin would have.

HyperSpin reacts to keys sent the way .NET's ``SendKeys`` sends them (down and
up at once, :func:`spindoctor._win32.type_keys`), not to the held raw key
events games get, so this module uses ``platform.type_keys``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .config import Config
from .rocketlauncher import _read_rl_ini

VK_RETURN, VK_ESCAPE, VK_SPACE = 0x0D, 0x1B, 0x20
_LOADED = "wheel loaded successfully"
_INTRO = "playing intro video"
_ERROR_LINE = re.compile(r"error|fail|unable|cannot|could not|not found|missing|exception", re.I)


def hyperspin_pid(platform) -> int:
    """The running HyperSpin's PID, 0 when it isn't running."""
    return next((p.pid for p in platform.list_processes() if p.name.lower() == "hyperspin.exe"), 0)


def _main_window(platform, pid: int):
    wins = [w for w in platform.list_windows() if w.pid == pid]
    return max(wins, key=lambda w: w.width * w.height) if wins else None


def _type_into(platform, pid: int, vks: list[int]) -> bool:
    """Send *vks* to HyperSpin; False when its window couldn't be brought to the front."""
    if platform.foreground_pid() != pid:
        win = _main_window(platform, pid)
        if win is not None:
            platform.bring_to_front(win.hwnd)
            platform.sleep(0.3)
    if platform.foreground_pid() != pid:
        return False
    platform.type_keys(vks)
    return True


def _wait_gone(platform, pid: int, timeout: float) -> bool:
    end = platform.now() + timeout
    while any(p.pid == pid for p in platform.list_processes()):
        if platform.now() >= end:
            return False
        platform.sleep(0.5)
    return True


def _screenshot(platform, run_dir: Path, width: int) -> str:
    from .gametest import encode_image

    try:
        shot = platform.capture(width)
    except OSError:
        return ""
    if shot is None:
        return ""
    data, ext = encode_image(shot.thumb_width, shot.thumb_height, shot.thumb)
    rel = f"screenshots/HyperSpin.{ext}"
    try:
        (run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (run_dir / rel).write_bytes(data)
    except OSError:
        return ""
    return rel


def start_and_check(config: Config, settings, platform, run_dir: Path, journal,
                    play_intro: bool = False) -> dict:
    """Open HyperSpin and judge its startup (the tester's ``Invoke-HyperSpinCheck``).

    Returns ``{"status", "reason", "details", "screenshot", "seconds"}``.  The
    journal's ``hyperspin`` entry names the process while it runs, so a
    killed run's :func:`spindoctor.gametest.recover` can close it."""
    from .gametest import FAIL, PASS, WARN, read_log

    res = {"status": PASS, "reason": "", "details": [], "screenshot": "", "seconds": 0}
    if hyperspin_pid(platform):
        res["reason"] = "HyperSpin was already open, so its startup was not tested"
        return res
    hs_dir = Path(config.hyperspin_dir)
    log = hs_dir / "log.txt"
    skip = settings.skip_intro and not play_intro
    t0 = platform.now()
    journal.data["hyperspin"] = {"name": "HyperSpin.exe", "pid": 0, "started": None,
                                 "launch_at": t0, "started_by_us": True}
    journal.save()
    try:
        proc = platform.start([str(hs_dir / "HyperSpin.exe")], str(hs_dir))
    except OSError as exc:
        journal.data["hyperspin"] = {}
        journal.save()
        res.update(status=FAIL, reason=f"Couldn't start HyperSpin: {exc}")
        return res
    journal.data["hyperspin"].update(pid=proc.pid, started=platform.start_time(proc.pid))
    journal.save()

    loaded = False
    loaded_at = last_press = intro_seen = None
    popup = ""
    presses = 0
    deadline = t0 + settings.hyperspin_timeout
    while platform.now() < deadline:
        platform.sleep(1)
        if proc.poll() is not None:
            break
        popup = next((w.title for w in platform.list_windows()
                      if w.pid == proc.pid and w.cls == "#32770"), "")
        if popup:
            break
        text = read_log(log, since=t0)
        if _LOADED in text.lower():
            loaded, loaded_at = True, platform.now()
            break
        lines = text.rstrip().splitlines()
        if skip and lines and _INTRO in lines[-1].lower():
            now = platform.now()
            if intro_seen is None:
                intro_seen = now
            if presses < 5 and now >= intro_seen + 2 + 3 * presses:  # the video needs a moment to start
                presses += 1
                if _type_into(platform, proc.pid, [VK_SPACE]):
                    last_press = platform.now()
    res["seconds"] = seconds = int(platform.now() - t0)
    note = ""
    if intro_seen is not None:
        if loaded and last_press is not None and loaded_at - last_press <= 6:
            note = " (intro video skipped)"
        elif last_press is not None:
            note = " (HyperSpin ignored the key press meant to skip its intro video)"
        elif presses:
            note = " (the intro video wasn't skipped: HyperSpin's window couldn't be brought to the front)"

    if loaded:
        platform.sleep(3)  # let the Main Menu settle before the screenshot
    text = read_log(log, since=t0)
    if text:
        try:
            (run_dir / "HyperSpin log.txt").write_text(text, encoding="utf-8")
        except OSError:
            pass
    ignore = [i.lower() for i in settings.ignore_hyperspin_log]
    res["details"] = [line.strip() for line in text.splitlines()
                      if _ERROR_LINE.search(line) and not any(i in line.lower() for i in ignore)]

    if proc.poll() is not None:
        res.update(status=FAIL, reason=f"HyperSpin closed by itself {seconds} seconds after opening")
        journal.data["hyperspin"] = {}
    elif popup or not loaded:
        res["status"] = FAIL
        res["reason"] = (f"HyperSpin showed a pop-up: '{popup}'" if popup else
                         f"HyperSpin didn't finish loading the Main Menu within "
                         f"{settings.hyperspin_timeout} seconds")
        res["screenshot"] = _screenshot(platform, run_dir, settings.screenshot_width)
        platform.terminate(proc.pid)
        journal.data["hyperspin"] = {}
    else:
        res["screenshot"] = _screenshot(platform, run_dir, settings.screenshot_width)
        res["reason"] = f"HyperSpin opened and loaded the Main Menu in {seconds} seconds"
        if res["details"]:
            res["status"] = WARN
            res["reason"] += f", but its log has {len(res['details'])} error line(s)"
    journal.save()
    res["reason"] += note
    return res


def close(config: Config, platform, entry: Optional[dict] = None) -> str:
    """Close HyperSpin (the tester's ``Stop-HyperSpin``): its exit menu (Esc,
    then Enter once the menu has animated in), else close its window, else
    end it.  Returns how: ``exit menu``, ``window``, ``killed`` or ``gone``."""
    pid = (entry or {}).get("pid") or hyperspin_pid(platform)
    if not pid or not any(p.pid == pid for p in platform.list_processes()):
        return "gone"
    win = _main_window(platform, pid)
    if platform.foreground_pid() != pid and win is not None:
        platform.bring_to_front(win.hwnd)
        platform.sleep(0.7)
    if platform.foreground_pid() == pid:
        platform.type_keys([VK_ESCAPE])
        platform.sleep(3.5)  # the menu ignores Enter while it is still animating in
        if platform.foreground_pid() == pid:
            platform.type_keys([VK_RETURN])
        if _wait_gone(platform, pid, 20):
            return "exit menu"
    how = "window"
    if win is not None:
        platform.close_window(win.hwnd)
    if not _wait_gone(platform, pid, 10):
        platform.terminate(pid)
        _wait_gone(platform, pid, 5)
        how = "killed"
    _tell_ledblinky(config, platform)
    return how


def _tell_ledblinky(config: Config, platform) -> None:
    """HyperSpin didn't run its own exit steps: tell LEDBlinky the frontend
    quit (``LEDBlinky.exe 2``), as HyperSpin's ``[LEDBlinky]`` settings would."""
    hs_dir = Path(config.hyperspin_dir)
    section = _read_rl_ini(hs_dir / "Settings" / "Settings.ini").get("ledblinky", {})
    if section.get("active", "").strip().lower() != "true":
        return
    folder = Path(section.get("path", "").strip().strip('"'))
    if not folder.is_absolute():
        folder = hs_dir / folder
    exe = folder / "LEDBlinky.exe"
    if exe.is_file():
        try:
            platform.start([str(exe), "2"], str(folder))
        except OSError:
            pass
