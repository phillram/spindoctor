"""`spindoctor toolkit restart`: Shut Down Cabinet's sequence, ending in a restart.

Driven with the fake screen and fake Windows calls from test_toolkit_power,
so nothing restarts or opens a window.
"""
from __future__ import annotations

import sys

from click.testing import CliRunner

from spindoctor import cabinet_power as cp
from spindoctor import toolkit_helpers as th
from spindoctor.cli import cli
from spindoctor.config import Config
from tests.test_toolkit_power import HYPERSPIN_EXE, QUIT, FakeOps, FakeScreen


def test_restart_counts_down_closes_hyperspin_then_restarts_windows():
    screen, ops, lines = FakeScreen(), FakeOps(), []
    assert cp.run("restart", Config(), screen=screen, ops=ops, log=lines.append) == 0
    assert screen.calls[0] == ("count", "Restarting", 5)
    assert ("show", "Restarting…") in screen.calls
    # HyperSpin closes and LEDBlinky is told to quit, then Windows restarts at once.
    order = [ops.calls.index(c) for c in (("post_close", (100,)), QUIT,
                                          ("run", ("/r", "/f", "/t", "0"), "shutdown.exe"))]
    assert order == sorted(order)
    assert not any(c[0] == "wait_exit" and c[1] == (101,) for c in ops.calls)
    assert ("hold", cp.HOLD_AFTER) in screen.calls
    assert any(line.startswith("restart: running shutdown.exe /r") for line in lines)


def test_cancelled_restart_closes_nothing():
    screen, ops = FakeScreen(go=False), FakeOps()
    assert cp.run("restart", Config(), screen=screen, ops=ops, log=lambda _l: None) == 0
    assert ops.calls == [("activate", "HyperSpin.exe")]


def test_refused_restart_starts_hyperspin_again():
    screen, ops = FakeScreen(), FakeOps(shutdown_code=1115)
    assert cp.run("restart", Config(), screen=screen, ops=ops, log=lambda _l: None) == 1
    assert ops.calls[-1] == ("start", HYPERSPIN_EXE)


def test_restart_helper_starts_toolkit_restart_without_waiting(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor.exe")
    helper = th.find("Restart Cabinet")
    assert helper.key == "restart-cabinet"
    body = helper.body()
    assert 'start "" "C:\\Apps\\spindoctor.exe" --run-tool spindoctor toolkit restart\r\n' in body
    assert "/WAIT" not in body


def test_toolkit_restart_cli(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cp, "run", lambda mode, config, seconds: seen.append((mode, seconds)) or 0)
    result = CliRunner().invoke(cli, ["toolkit", "restart", "--seconds", "0"])
    assert result.exit_code == 0, result.output
    assert seen == [("restart", 0)]
