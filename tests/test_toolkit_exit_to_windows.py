"""`spindoctor toolkit exit-to-windows`: the countdown, then Explorer restarted.

Driven with the fake screen and fake Windows calls from test_toolkit_power,
so nothing is closed or restarted.
"""
from __future__ import annotations

import sys
from pathlib import Path

from click.testing import CliRunner

from spindoctor import cabinet_power as cp
from spindoctor import toolkit_helpers as th
from spindoctor.cli import cli
from spindoctor.config import Config
from tests.test_toolkit_power import QUIT, FakeOps, FakeScreen

TASKKILL = ("run", ("/F", "/IM", "explorer.exe"), "taskkill.exe")


class ExplorerOps(FakeOps):
    """taskkill ends Explorer; Windows starts a new one by itself if *respawns*."""

    def __init__(self, respawns=True, **kw):
        kw.setdefault("running", ("HyperSpin.exe", "LEDBlinky.exe", "explorer.exe"))
        super().__init__(**kw)
        self.respawns = respawns

    def run(self, args):
        code = super().run(args)
        if Path(args[0]).name == "taskkill.exe":
            self.running.pop("explorer.exe", None)
            if self.respawns:
                self.running["explorer.exe"] = [900]
        return code


def _exit(monkeypatch, ops):
    monkeypatch.setattr(cp, "EXPLORER_WAIT", 0)
    screen, lines = FakeScreen(), []
    code = cp.run("exit-to-windows", Config(), screen=screen, ops=ops, log=lines.append)
    return code, screen, lines


def test_exit_closes_hyperspin_then_restarts_explorer_without_waiting_for_the_lights(monkeypatch):
    ops = ExplorerOps(stubborn=("LEDBlinky.exe",))  # still playing its quit animation
    code, screen, lines = _exit(monkeypatch, ops)
    assert code == 0
    assert screen.calls[0] == ("count", "Exiting to Windows", 5)
    # HyperSpin closes and LEDBlinky is told to quit, then Explorer restarts, and only
    # then is LEDBlinky waited for: the screen takes no longer than the countdown.
    order = [ops.calls.index(c) for c in (("post_close", (100,)), QUIT, TASKKILL,
                                          ("wait_exit", (101,), cp.LEDBLINKY_WAIT))]
    assert order == sorted(order)
    assert ("close",) in screen.calls and ("hold", cp.HOLD_AFTER) not in screen.calls
    assert not any(c[0] == "run" and c[2] == "shutdown.exe" for c in ops.calls)
    assert any("by itself" in line for line in lines)
    assert "exit-to-windows: on the desktop" in lines
    assert not any(c[0] == "start" and c[1].lower().endswith("explorer.exe") for c in ops.calls)


def test_ledblinky_still_quitting_on_the_desktop_is_ended_after_thirty_seconds(monkeypatch):
    ops = ExplorerOps(stubborn=("LEDBlinky.exe",))
    code, _screen, lines = _exit(monkeypatch, ops)
    assert code == 0
    assert ops.calls.index(TASKKILL) < ops.calls.index(("terminate", 101))
    assert any("ended it" in line for line in lines)


def test_ledblinky_that_quits_in_time_is_not_ended(monkeypatch):
    ops = ExplorerOps()
    code, _screen, _lines = _exit(monkeypatch, ops)
    assert code == 0
    assert ("terminate", 101) not in ops.calls


def test_explorer_is_started_when_windows_does_not_bring_it_back(monkeypatch):
    ops = ExplorerOps(respawns=False)
    code, _screen, lines = _exit(monkeypatch, ops)
    assert code == 0
    started = [c for c in ops.calls if c[0] == "start" and c[1].lower().endswith("explorer.exe")]
    assert len(started) == 1
    assert any(line.startswith("  started ") for line in lines)


def test_the_old_explorer_still_shutting_down_is_not_taken_for_a_new_one(monkeypatch):
    class Lingering(ExplorerOps):
        def run(self, args):
            code = FakeOps.run(self, args)  # taskkill returns while the old Explorer lingers
            return code

    ops = Lingering(respawns=False)
    _exit(monkeypatch, ops)
    assert any(c[0] == "start" and c[1].lower().endswith("explorer.exe") for c in ops.calls)


def test_explorer_that_cannot_start_exits_1(monkeypatch):
    class NoStart(ExplorerOps):
        def start(self, exe, args=()):
            if exe.lower().endswith("explorer.exe"):
                raise OSError("denied")
            super().start(exe, args)

    code, _screen, lines = _exit(monkeypatch, NoStart(respawns=False))
    assert code == 1 and any("could not start" in line for line in lines)


def test_cancelled_exit_closes_nothing():
    screen, ops = FakeScreen(go=False), ExplorerOps()
    assert cp.run("exit-to-windows", Config(), screen=screen, ops=ops, log=lambda _l: None) == 0
    assert ops.calls == [("activate", "HyperSpin.exe")]


def test_exit_helper_starts_the_command_without_waiting(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor.exe")
    helper = th.find("Exit To Windows")
    assert helper.key == "exit-to-windows"
    body = helper.body()
    assert 'start "" "C:\\Apps\\spindoctor.exe" --run-tool spindoctor toolkit exit-to-windows\r\n' in body
    assert "/WAIT" not in body


def test_toolkit_exit_to_windows_cli(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cp, "run", lambda mode, config, seconds: seen.append((mode, seconds)) or 0)
    result = CliRunner().invoke(cli, ["toolkit", "exit-to-windows"])
    assert result.exit_code == 0, result.output
    assert seen == [("exit-to-windows", 5)]
