"""``spindoctor._win32``: import-safe everywhere, and a smoke test on Windows.

The ctypes calls only run on Windows; elsewhere every call raises
``UnsupportedPlatform``.  The Windows tests only read (processes, windows,
the screen) and start nothing.
"""
from __future__ import annotations

import os
import sys

import pytest

from spindoctor import _win32

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


def test_calls_off_windows_raise(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    for call, args in ((_win32.list_processes, ()), (_win32.list_windows, ()),
                       (_win32.terminate, (1,)), (_win32.capture_screen, (480,)),
                       (_win32.press_keys, ([0x1B], 100))):
        with pytest.raises(_win32.UnsupportedPlatform):
            call(*args)


def test_runtime_still_finds_child_processes_through_win32(monkeypatch):
    from spindoctor import _runtime

    procs = [_win32.ProcInfo(10, 1, "spindoctor.exe"), _win32.ProcInfo(11, 10, "SpinDoctor.EXE"),
             _win32.ProcInfo(12, 10, "other.exe"), _win32.ProcInfo(13, 99, "spindoctor.exe")]
    monkeypatch.setattr(_win32, "list_processes", lambda: procs)
    assert _runtime._child_pids(10, "spindoctor.exe") == [11]


@windows_only
def test_process_list_has_this_process_with_a_start_time():
    me = os.getpid()
    procs = {p.pid: p for p in _win32.list_processes()}
    assert me in procs and procs[me].name.lower().endswith(".exe")
    started = _win32.process_start_time(me)
    assert started is not None and started > 946684800  # after 2000-01-01
    assert _win32.process_image_path(me).lower().endswith(procs[me].name.lower())
    assert isinstance(_win32.command_line(me), str)


@windows_only
def test_window_list_and_foreground_do_not_fail():
    windows = _win32.list_windows()
    assert all(isinstance(w.title, str) and w.width >= 0 for w in windows)
    assert isinstance(_win32.foreground_pid(), int)
    _l, _t, width, height = _win32.screen_rect()
    assert width >= 0 and height >= 0


@windows_only
def test_screen_capture_returns_matching_sizes_or_none():
    shot = _win32.capture_screen(64)
    if shot is None:  # e.g. a service session with no desktop
        pytest.skip("no screen to capture")
    assert len(shot.pixels) == shot.width * shot.height * 4
    assert shot.thumb_width == 64
    assert len(shot.thumb) == shot.thumb_width * shot.thumb_height * 4
    assert shot.method
