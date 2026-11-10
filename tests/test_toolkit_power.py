"""`spindoctor toolkit shutdown` and the countdown every power helper shares.

The sequence in `cabinet_power.run` is driven with a fake screen and fake
Windows calls, so nothing here shuts anything down or opens a window.  The
Windows-only tests at the end only read the process list and build the
ctypes prototypes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import cabinet_power as cp
from spindoctor import health
from spindoctor import toolkit_helpers as th
from spindoctor.cli import cli
from spindoctor.config import Config


class FakeScreen:
    def __init__(self, go=True):
        self.go = go
        self.calls = []

    def count(self, verb, seconds):
        self.calls.append(("count", verb, seconds))
        return self.go

    def show(self, big, small=""):
        self.calls.append(("show", big))

    def run(self, fn):
        self.calls.append(("run",))
        return fn()

    def hold(self, seconds):
        self.calls.append(("hold", seconds))

    def close(self):
        self.calls.append(("close",))


HYPERSPIN_EXE = r"Z:\NoSuchCabinet\HyperSpin.exe"
LEDBLINKY_EXE = r"Z:\NoSuchCabinet\LEDBlinky\LEDBlinky.exe"


class FakeOps:
    """Processes by name.  HyperSpin closes on WM_CLOSE and LEDBlinky quits on
    ``LEDBlinky.exe 2``, unless their names are in *stubborn*."""

    def __init__(self, running=("HyperSpin.exe", "LEDBlinky.exe"), stubborn=(),
                 shutdown_code=0, images=None):
        self.running = {name: [100 + i] for i, name in enumerate(running)}
        self.stubborn = set(stubborn)
        self.shutdown_code = shutdown_code
        # A drive that doesn't exist, so no test reads a real HyperSpin log.txt.
        self.images = {"HyperSpin.exe": HYPERSPIN_EXE, "LEDBlinky.exe": LEDBLINKY_EXE}
        self.images.update(images or {})
        self.calls = []

    def pids(self, name):
        return list(self.running.get(name, []))

    def image_path(self, pid):
        name = next((n for n, p in self.running.items() if pid in p), None)
        return self.images.get(name)

    def post_close(self, pids):
        self.calls.append(("post_close", tuple(pids)))
        if "HyperSpin.exe" not in self.stubborn:
            self._gone(pids)
        return len(pids)

    def _gone(self, pids):
        for name in list(self.running):
            if self.running[name] == list(pids):
                del self.running[name]

    def wait_exit(self, pids, timeout):
        self.calls.append(("wait_exit", tuple(pids), timeout))
        return not any(list(pids) == p for p in self.running.values())

    def terminate(self, pid):
        self.calls.append(("terminate", pid))
        self._gone([pid])

    def run(self, args):
        self.calls.append(("run", tuple(args[1:]), Path(args[0]).name))
        return self.shutdown_code

    def start(self, exe, args=()):
        self.calls.append(("start", exe, tuple(args)) if args else ("start", exe))
        if list(args) == ["2"] and "LEDBlinky.exe" not in self.stubborn:
            self.running.pop("LEDBlinky.exe", None)  # LEDBlinky plays its quit and goes

    def activate(self, name):
        self.calls.append(("activate", name))
        return True


def _go(**kw):
    screen, ops, lines = FakeScreen(kw.pop("go", True)), FakeOps(**kw), []
    code = cp.run("shutdown", Config(), screen=screen, ops=ops, log=lines.append)
    return code, screen, ops, lines


def test_esc_cancels_before_anything_is_closed():
    code, screen, ops, lines = _go(go=False)
    assert code == 0
    assert screen.calls[0] == ("count", "Shutting down", 5)
    assert ("close",) in screen.calls
    assert ops.calls == [("activate", "HyperSpin.exe")]
    assert any("cancelled" in line for line in lines)


QUIT = ("start", LEDBLINKY_EXE, ("2",))


def test_shutdown_closes_hyperspin_politely_then_shuts_windows_down():
    code, screen, ops, lines = _go()
    assert code == 0
    assert "terminate" not in [c[0] for c in ops.calls]
    # HyperSpin closes, LEDBlinky is told to quit, then Windows goes at once.
    order = [ops.calls.index(c) for c in (("post_close", (100,)), QUIT,
                                          ("run", ("/s", "/f", "/t", "0"), "shutdown.exe"))]
    assert order == sorted(order)
    assert not any(c[0] == "wait_exit" and c[1] == (101,) for c in ops.calls)
    # The black screen stays up while Windows closes everything.
    assert ("hold", cp.HOLD_AFTER) in screen.calls
    assert ("show", "Shutting down…") in screen.calls
    assert any("HyperSpin closed" in line for line in lines)
    assert any("sent LEDBlinky its quit" in line for line in lines)
    assert not any(c[0] == "start" and c[1].endswith("HyperSpin.exe") for c in ops.calls)


def test_hyperspin_that_ignores_wm_close_is_forced_after_three_seconds():
    assert cp.CLOSE_WAIT == 3.0
    code, _screen, ops, lines = _go(stubborn=("HyperSpin.exe",))
    assert code == 0
    assert ("wait_exit", (100,), cp.CLOSE_WAIT) in ops.calls
    assert ("terminate", 100) in ops.calls
    assert any("forcing it" in line for line in lines)


def test_rocketlauncher_still_running_is_ended_before_the_close():
    # HyperSpin waiting for RocketLauncher's "game" ignores WM_CLOSE.
    code, _screen, ops, lines = _go(running=("HyperSpin.exe", "RocketLauncher.exe"))
    assert code == 0
    assert ops.calls.index(("terminate", 101)) < ops.calls.index(("post_close", (100,)))
    assert any("RocketLauncher was still running" in line for line in lines)


def test_shutdown_does_not_wait_for_ledblinkys_quit_animation():
    # LEDBlinky still playing its quit (up to 30 s) is left to Windows, which ends it.
    code, _screen, ops, _lines = _go(stubborn=("LEDBlinky.exe",))
    assert code == 0
    names = [c[0] for c in ops.calls]
    assert names[names.index("start"):] == ["start", "run"]  # the quit, then shutdown.exe
    assert ("terminate", 101) not in ops.calls


def test_no_second_quit_when_hyperspin_already_sent_one(tmp_path):
    exe = tmp_path / "HyperSpin.exe"
    (tmp_path / "log.txt").write_text(
        '09:04:40 PM |  Found LEDBlinky.exe \n'
        '09:04:46 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 9 "MAME" "Main Menu" \n'
        '09:30:00 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 2 \n'
        '09:30:01 PM |  Found LEDBlinky.exe \n', encoding="utf-8")
    screen, ops, lines = FakeScreen(), FakeOps(images={"HyperSpin.exe": str(exe)}), []
    cp.run("shutdown", Config(), screen=screen, ops=ops, log=lines.append)
    assert QUIT not in ops.calls
    assert ops.calls[-1] == ("run", ("/s", "/f", "/t", "0"), "shutdown.exe")
    assert any("already sent" in line for line in lines)


def test_quit_is_sent_when_hyperspins_last_ledblinky_command_was_another(tmp_path):
    exe = tmp_path / "HyperSpin.exe"
    (tmp_path / "log.txt").write_text(
        '09:04:40 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 2 \n'
        '09:04:41 PM |  Command Line is: "D:\\Arcade\\LEDBlinky\\LEDBlinky.exe" 1 \n', encoding="utf-8")
    ops = FakeOps(images={"HyperSpin.exe": str(exe)})
    cp.run("shutdown", Config(), screen=FakeScreen(), ops=ops, log=lambda _l: None)
    assert QUIT in ops.calls


def test_ledblinky_found_through_ledblinky_dir_when_its_path_is_unknown(tmp_path):
    ops = FakeOps(images={"LEDBlinky.exe": None})
    cp.run("shutdown", Config(ledblinky_dir=str(tmp_path)), screen=FakeScreen(), ops=ops,
           log=lambda _l: None)
    assert ("start", str(tmp_path / "LEDBlinky.exe"), ("2",)) in ops.calls


def test_shutdown_still_runs_when_hyperspin_is_not_running():
    code, _screen, ops, lines = _go(running=())
    assert code == 0
    assert [c[0] for c in ops.calls] == ["run"]
    assert any("not running" in line for line in lines)


def test_refused_shutdown_starts_the_same_hyperspin_again():
    code, screen, ops, lines = _go(shutdown_code=1190)
    assert code == 1
    assert ops.calls[-1] == ("start", HYPERSPIN_EXE)
    assert ("hold", cp.HOLD_AFTER) not in screen.calls
    assert any("exit code 1190" in line for line in lines)


def test_refused_shutdown_falls_back_to_the_configured_hyperspin(tmp_path):
    exe = tmp_path / "HyperSpin.exe"
    exe.write_bytes(b"MZ")
    screen, ops, lines = FakeScreen(), FakeOps(running=(), shutdown_code=5), []
    assert cp.run("shutdown", Config(hyperspin_dir=str(tmp_path)), screen=screen,
                  ops=ops, log=lines.append) == 1
    assert ops.calls[-1] == ("start", str(exe))


def test_the_countdown_length_reaches_the_screen():
    screen, ops = FakeScreen(), FakeOps()
    cp.run("shutdown", Config(), seconds=0, screen=screen, ops=ops, log=lambda _l: None)
    assert screen.calls[0] == ("count", "Shutting down", 0)


def test_log_file_is_written_and_kept_small(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".spindoctor")
    monkeypatch.setattr(cp, "LOG_LIMIT", 10)
    cp.log_to_file("shutdown: countdown started (5 s)")
    cp.log_to_file("shutdown: cancelled with Esc")
    log = tmp_path / ".spindoctor" / "toolkit.log"
    assert log.read_text(encoding="utf-8").endswith("shutdown: cancelled with Esc\n")
    assert "countdown started" in (tmp_path / ".spindoctor" / "toolkit.log.1").read_text(encoding="utf-8")


# ── the helper install-tools writes ──────────────────────────────────────────

def test_shut_down_helper_starts_the_command_without_waiting(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor.exe")
    body = th.find("shut-down-cabinet").body()
    assert 'start "" "C:\\Apps\\spindoctor.exe" --run-tool spindoctor toolkit shutdown\r\n' in body
    assert "/WAIT" not in body
    assert body.endswith("exit\r\n") and body.count("\n") == body.count("\r\n")


def test_doctor_checks_the_shut_down_helper(tmp_path, monkeypatch):
    exe = tmp_path / "spindoctor" / "spindoctor.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    menu = tmp_path / "RocketLauncher" / "Modules" / "HyperLaunch" / "Tools" / "spindoctor"
    menu.mkdir(parents=True)
    (menu / "Shut Down Cabinet.bat").write_text(th.find("shut-down-cabinet").body(), encoding="utf-8")
    monkeypatch.undo()
    cfg = Config(rocketlauncher_dir=str(tmp_path / "RocketLauncher"))
    assert health.check_refresh_helpers(cfg).children[0].status == health.Status.OK
    exe.unlink()
    row = health.check_refresh_helpers(cfg).children[0]
    assert row.status == health.Status.WARN
    assert row.fix == "spindoctor install-tools --tool shut-down-cabinet"


# ── the CLI ──────────────────────────────────────────────────────────────────

def test_toolkit_shutdown_runs_the_sequence_with_its_countdown(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cp, "run", lambda mode, config, seconds: seen.append((mode, seconds)) or 0)
    result = CliRunner().invoke(cli, ["toolkit", "shutdown", "--seconds", "3"])
    assert result.exit_code == 0, result.output
    assert seen == [("shutdown", 3)]


def test_toolkit_shutdown_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cp, "run", lambda *a, **k: pytest.fail("ran off Windows"))
    result = CliRunner().invoke(cli, ["toolkit", "shutdown"])
    assert result.exit_code == 1 and "Windows only" in result.output


def test_countdown_longer_than_a_minute_is_refused():
    result = CliRunner().invoke(cli, ["toolkit", "shutdown", "--seconds", "61"])
    assert result.exit_code == 2


# ── Windows only: real calls that change nothing ─────────────────────────────

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


@windows_only
def test_screen_prototypes_all_resolve():
    from spindoctor import toolkit_screen

    api = toolkit_screen._api()
    for name in ("RegisterHotKey", "CreateWindowExW", "DrawTextW", "CreateFontW",
                 "AttachThreadInput", "PeekMessageW", "GetModuleHandleW"):
        assert callable(getattr(api, name)), name


@windows_only
def test_windows_ops_read_the_process_list():
    ops = cp.WindowsOps()
    assert ops.pids("no-such-program-here.exe") == []
    import os

    assert Path(ops.image_path(os.getpid()) or "x").suffix.lower() == ".exe"
    assert ops.wait_exit([], 0.01) is True
