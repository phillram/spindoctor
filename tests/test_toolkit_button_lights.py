"""`spindoctor toolkit reset-button-lights`: zero the PAC-LED64 flash speeds.

The PowerShell run is faked everywhere except one Windows-only test that runs
the real script against a DLL that doesn't exist (it stops at loading it, so
no board is touched).  The on-screen note is replaced by a recorder.
"""
from __future__ import annotations

import base64
import os
import sys
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import button_lights as bl
from spindoctor import toolkit_helpers as th
from spindoctor import toolkit_screen
from spindoctor.cli import cli
from spindoctor.config import Config

OK_OUTPUT = "BOARD 1 True 0\r\nBOARD 2 True 0\r\nDONE 4 2\r\n"


# ── reading the script's output ──────────────────────────────────────────────

def test_parse_two_boards_reset():
    result = bl.parse(OK_OUTPUT)
    assert result.devices == 4 and not result.error
    assert result.boards == (bl.Board(1, True, 0), bl.Board(2, True, 0))
    assert result.note == "Button lights reset"
    assert result.lines()[-1] == "button lights: 4 Ultimarc device(s), 2 LED board(s) reset"


def test_parse_no_boards_and_failed_ports():
    assert bl.parse("DONE 1 0\n").note == "No button light boards found"
    board = bl.parse("BOARD 3 False 5\nDONE 2 1\n").boards[0]
    assert board == bl.Board(3, False, 5)


def test_parse_error_and_silence():
    err = bl.parse("ERROR cannot load D:\\LEDBlinky\\PacDrive32.dll\n")
    assert err.error == "cannot load D:\\LEDBlinky\\PacDrive32.dll"
    assert err.note == "Button light reset failed"
    assert "no result" in bl.parse("").error
    assert "no result" in bl.parse("BOARD 1 True 0\n").error  # cut off before DONE


# ── finding the DLL and PowerShell ───────────────────────────────────────────

def test_find_dll_in_ledblinky_dir_any_case(tmp_path):
    (tmp_path / "pacdrive32.DLL").write_bytes(b"MZ")
    assert bl.find_dll(Config(ledblinky_dir=str(tmp_path))).name == "pacdrive32.DLL"
    assert bl.find_dll(Config(ledblinky_dir=str(tmp_path / "missing"))) is None
    assert bl.find_dll(Config()) is None


def test_find_dll_explicit_path(tmp_path):
    dll = tmp_path / "Ultimarc" / "PacDrive32.dll"
    dll.parent.mkdir()
    dll.write_bytes(b"MZ")
    assert bl.find_dll(Config(), str(dll)) == dll
    assert bl.find_dll(Config(), str(tmp_path / "nope.dll")) is None


def test_32_bit_powershell_is_preferred(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert bl.powershell_32() == os.path.join(str(tmp_path), "System32", "WindowsPowerShell",
                                               "v1.0", "powershell.exe")
    wow = tmp_path / "SysWOW64" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    wow.parent.mkdir(parents=True)
    wow.write_bytes(b"MZ")
    assert bl.powershell_32() == str(wow)


def test_reset_runs_the_script_with_the_dll_in_the_environment(tmp_path):
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["env"] = args, kw["env"]
        return SimpleNamespace(stdout=OK_OUTPUT, stderr="")

    dll = tmp_path / "PacDrive32.dll"
    result = bl.reset(dll, run=fake_run)
    assert result.note == "Button lights reset"
    args = seen["args"]
    assert args[0].lower().endswith("powershell.exe") and args[-2] == "-EncodedCommand"
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    for call in ("PacInitialize", "Pac64SetLEDFlashSpeeds", "Pac64SetLEDFlashSpeed", "PacShutdown"):
        assert call in script
    assert "0x1401" in script and "0x1404" in script
    assert seen["env"][bl.DLL_ENV] == str(dll)
    assert seen["env"][bl.JOB_ENV] == "flash"


def test_lights_off_runs_the_same_script_with_the_off_job(tmp_path):
    seen = {}

    def fake_run(args, **kw):
        seen["env"], seen["script"] = kw["env"], base64.b64decode(args[-1]).decode("utf-16-le")
        return SimpleNamespace(stdout="BOARD 1 True 0\nBOARD 2 True 0\nDONE 3 2\n", stderr="")

    result = bl.lights_off(tmp_path / "PacDrive32.dll", run=fake_run)
    assert [b.number for b in result.boards] == [1, 2] and not result.error
    assert seen["env"][bl.JOB_ENV] == "off"
    assert "Pac64SetLEDIntensities" in seen["script"]


# ── lights off at the end of the power helpers ───────────────────────────────

def _power_run(monkeypatch, tmp_path, mode="exit-to-windows", ops=None):
    from spindoctor import cabinet_power as cp
    from tests.test_toolkit_power import FakeOps, FakeScreen

    (tmp_path / "PacDrive32.dll").write_bytes(b"MZ")
    ops = ops or FakeOps()
    monkeypatch.setattr(cp, "EXPLORER_WAIT", 0, raising=False)
    monkeypatch.setattr(bl, "lights_off", lambda dll: ops.calls.append(("lights_off", dll))
                        or bl.parse("BOARD 1 True 0\nBOARD 2 True 0\nDONE 3 2\n"))
    lines = []
    cp.run(mode, Config(ledblinky_dir=str(tmp_path)), screen=FakeScreen(), ops=ops, log=lines.append)
    return ops, lines


def test_exit_to_windows_turns_the_lights_off_after_ledblinky_quits(monkeypatch, tmp_path):
    from spindoctor import cabinet_power as cp
    from tests.test_toolkit_power import FakeOps

    class SlowQuit(FakeOps):
        """LEDBlinky plays its quit animation until it's waited for."""

        def start(self, exe, args=()):
            self.calls.append(("start", exe, tuple(args)) if args else ("start", exe))

        def wait_exit(self, pids, timeout):
            if timeout == cp.LEDBLINKY_WAIT:
                self._gone(pids)
            return super().wait_exit(pids, timeout)

    ops, lines = _power_run(monkeypatch, tmp_path, ops=SlowQuit())
    order = [ops.calls.index(c) for c in (("wait_exit", (101,), cp.LEDBLINKY_WAIT),
                                          ("lights_off", tmp_path / "PacDrive32.dll"))]
    assert order == sorted(order)
    assert "  lights off: board 1 off: True, board 2 off: True (3 Ultimarc device(s))" in lines


def test_exit_to_windows_turns_the_lights_off_once_on_the_desktop(monkeypatch, tmp_path):
    ops, _lines = _power_run(monkeypatch, tmp_path, mode="exit-to-windows")
    names = [c[0] for c in ops.calls]
    assert names.index("lights_off") > max(i for i, c in enumerate(ops.calls)
                                           if c[0] == "run" and c[2] == "taskkill.exe")


@pytest.mark.parametrize("mode", ["shutdown", "restart"])
def test_shutdown_and_restart_leave_the_lights_to_windows(monkeypatch, tmp_path, mode):
    # No waiting for LEDBlinky's quit there, so no lights-off either: Windows ends LEDBlinky.
    ops, _lines = _power_run(monkeypatch, tmp_path, mode=mode)
    assert "lights_off" not in [c[0] for c in ops.calls]
    assert ops.calls[-1][0] == "run" and ops.calls[-1][2] == "shutdown.exe"


def test_lights_are_left_to_ledblinky_while_it_runs(monkeypatch, tmp_path):
    from tests.test_toolkit_power import FakeOps

    class Immortal(FakeOps):
        def terminate(self, pid):
            self.calls.append(("terminate", pid))  # LEDBlinky survives being ended

    ops, lines = _power_run(monkeypatch, tmp_path, ops=Immortal(stubborn=("LEDBlinky.exe",)))
    assert "lights_off" not in [c[0] for c in ops.calls]
    assert any("lights left to it" in line for line in lines)


def test_no_dll_in_ledblinky_dir_leaves_the_lights(monkeypatch, tmp_path):
    from spindoctor import cabinet_power as cp
    from tests.test_toolkit_power import FakeOps, FakeScreen

    monkeypatch.setattr(bl, "lights_off", lambda dll: pytest.fail("no DLL to use"))
    monkeypatch.setattr(cp, "EXPLORER_WAIT", 0)
    lines = []
    cp.run("exit-to-windows", Config(ledblinky_dir=str(tmp_path)), screen=FakeScreen(), ops=FakeOps(),
           log=lines.append)
    assert any("lights left as they are" in line for line in lines)


def test_reset_reports_powershell_that_cannot_start(tmp_path):
    def broken(_args, **_kw):
        raise OSError("not found")

    assert "could not run" in bl.reset(tmp_path / "x.dll", run=broken).error


# ── the command and its helper ───────────────────────────────────────────────

@pytest.fixture
def toolkit_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".spindoctor")
    notes = []
    monkeypatch.setattr(toolkit_screen, "note", lambda text, seconds=3.0: notes.append(text))
    return SimpleNamespace(tmp=tmp_path, notes=notes, monkeypatch=monkeypatch)


def test_command_resets_shows_a_note_and_logs(toolkit_cli, tmp_path):
    dll = tmp_path / "PacDrive32.dll"
    dll.write_bytes(b"MZ")
    toolkit_cli.monkeypatch.setattr(bl, "reset", lambda d: bl.parse(OK_OUTPUT) if d == dll else None)
    result = CliRunner().invoke(cli, ["toolkit", "reset-button-lights", "--dll", str(dll)])
    assert result.exit_code == 0, result.output
    assert "2 LED board(s) reset" in result.output
    assert toolkit_cli.notes == ["Button lights reset"]
    log = (tmp_path / ".spindoctor" / "toolkit.log").read_text(encoding="utf-8")
    assert "LED board 2: flash speeds 0" in log


def test_command_without_the_dll_fails_with_a_note(toolkit_cli):
    toolkit_cli.monkeypatch.setattr(bl, "reset", lambda d: pytest.fail("ran without a DLL"))
    result = CliRunner().invoke(cli, ["toolkit", "reset-button-lights", "--dll",
                                      str(toolkit_cli.tmp / "missing.dll")])
    assert result.exit_code == 1
    assert "PacDrive32.dll not found" in result.output
    assert toolkit_cli.notes == ["Button light reset failed"]


def test_no_note_skips_the_on_screen_note(toolkit_cli, tmp_path):
    dll = tmp_path / "PacDrive32.dll"
    dll.write_bytes(b"MZ")
    toolkit_cli.monkeypatch.setattr(bl, "reset", lambda d: bl.parse("DONE 1 0\n"))
    result = CliRunner().invoke(cli, ["toolkit", "reset-button-lights", "--dll", str(dll), "--no-note"])
    assert result.exit_code == 0 and toolkit_cli.notes == []


def test_command_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    result = CliRunner().invoke(cli, ["toolkit", "reset-button-lights"])
    assert result.exit_code == 1 and "Windows only" in result.output


def test_helper_starts_the_command_without_waiting(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor.exe")
    helper = th.find("reset-button-lights")
    assert helper.name == "Reset Button Lights"
    assert 'start "" "C:\\Apps\\spindoctor.exe" --run-tool spindoctor toolkit reset-button-lights\r\n' in helper.body()


# ── Windows only: the real script, stopped before any board is touched ──────

@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
def test_real_script_compiles_and_reports_a_missing_dll(tmp_path):
    result = bl.reset(tmp_path / "PacDrive32.dll")
    assert result.error.startswith("cannot load"), result.error


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API")
def test_note_prototypes_resolve():
    api = toolkit_screen._api()
    for name in ("CreateSolidBrush", "GetDC", "ReleaseDC", "ShowWindow"):
        assert callable(getattr(api, name)), name
