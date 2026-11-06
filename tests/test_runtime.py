"""Embedded worker dispatch used by the standalone frozen executables."""
from __future__ import annotations

import subprocess
import sys

import pytest

from spindoctor import _runtime, cli as cli_mod, favorites, gui


def test_frozen_tool_command_uses_running_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor-gui.exe")
    assert _runtime.frozen_tool_command("spindoctor-fav") == [
        r"C:\Apps\spindoctor-gui.exe", "--run-tool", "spindoctor-fav",
    ]
    assert _runtime.tool_command_text("spindoctor-stats") == (
        r'"C:\Apps\spindoctor-gui.exe" --run-tool spindoctor-stats'
    )


def test_source_tool_command_text_is_bare_name(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _runtime.tool_command_text("spindoctor-recent") == "spindoctor-recent"


@pytest.mark.parametrize("func", [_runtime.frozen_tool_command, _runtime.tool_command_text])
def test_unknown_tool_rejected(func):
    with pytest.raises(ValueError):
        func("calc.exe")


def test_ensure_worker_stdio_falls_back_to_devnull(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def _fail(*_a):
        raise OSError("no handle")

    monkeypatch.setattr(_runtime, "_windows_stream", _fail)
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", None)
    _runtime.ensure_worker_stdio()
    try:
        assert sys.stdin.read() == ""
        sys.stdout.write("discarded")
    finally:
        sys.stdin.close()
        sys.stdout.close()


def test_run_tool_reports_cli_version(capsys):
    assert _runtime.run_tool("spindoctor", ["--version"]) == 0
    assert "version" in capsys.readouterr().out


def test_run_tool_unknown_name_exit_2(capsys):
    assert _runtime.run_tool("nope", []) == 2
    assert "Unknown SpinDoctor tool" in capsys.readouterr().err


def test_run_tool_reports_exceptions_without_raising(monkeypatch, capsys):
    def _boom(_args):
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(favorites, "main", _boom)
    assert _runtime.run_tool("spindoctor-fav", []) == 1
    assert "worker exploded" in capsys.readouterr().err


def test_run_tool_maps_system_exit(monkeypatch, capsys):
    def _exit(code):
        def _main(_args):
            raise SystemExit(code)
        return _main

    monkeypatch.setattr(favorites, "main", _exit(3))
    assert _runtime.run_tool("spindoctor-fav", []) == 3
    monkeypatch.setattr(favorites, "main", _exit("bad input"))
    assert _runtime.run_tool("spindoctor-fav", []) == 1
    assert "bad input" in capsys.readouterr().err


def test_cli_main_dispatches_worker_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(_runtime, "run_tool", lambda n, a: calls.append((n, list(a))) or 0)
    assert _runtime.cli_main(["--run-tool", "spindoctor-recent", "list"]) == 0
    assert _runtime.cli_main(["doctor"]) == 0
    assert calls == [("spindoctor-recent", ["list"]), ("spindoctor", ["doctor"])]
    assert _runtime.dispatch_worker([]) == 2


def test_gui_main_runs_worker_before_tk_or_singleton(monkeypatch):
    monkeypatch.setattr(gui, "dispatch_worker", lambda args: 7 if args == ["spindoctor", "x"] else 0)
    import builtins

    real_import = builtins.__import__

    def _guard(name, *a, **kw):
        if name in ("tkinter", "spindoctor._singleton") or name.endswith("_singleton"):
            pytest.fail(f"worker mode imported {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _guard)
    assert gui.main(["--run-tool", "spindoctor", "x"]) == 7


def test_install_tools_bats_wait_for_embedded_workers(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor-gui.exe")
    bats = cli_mod._make_install_tools_bats()
    body = bats["Refresh All.bat"]
    assert 'start "" /B /WAIT "C:\\Apps\\spindoctor-gui.exe" --run-tool spindoctor-fav rebuild --apply' in body
    assert "--run-tool spindoctor-stats build-wheel --apply" in body
    assert "spindoctor-fav.exe" not in "".join(bats.values())


def test_worker_restores_output_when_python_streams_are_none():
    code = (
        "import sys; sys.stdin = sys.stdout = sys.stderr = None; "
        "from spindoctor._runtime import run_tool; "
        "raise SystemExit(run_tool('spindoctor', ['--version']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    if sys.platform == "win32":
        assert "version" in result.stdout


class _FakeProc:
    def __init__(self, args, running=True):
        self.args, self.pid, self._running = args, 4321, running
        self.terminated = self.waited = False

    def poll(self):
        return None if self._running else 0

    def wait(self, timeout=None):
        self.waited = True
        self._running = False
        return 1

    def terminate(self):
        self.terminated = True


def test_stop_worker_ends_one_file_child_before_launcher(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    seen = {}
    monkeypatch.setattr(_runtime, "_child_pids", lambda pid, name: seen.update(pid=pid, name=name) or [99])
    killed = []
    monkeypatch.setattr(_runtime, "_terminate_pid", killed.append)
    proc = _FakeProc(["C:/Apps/spindoctor-gui.exe", "--run-tool", "spindoctor"])
    _runtime.stop_worker(proc)
    assert seen == {"pid": 4321, "name": "spindoctor-gui.exe"}
    assert killed == [99] and proc.waited and not proc.terminated


def test_stop_worker_without_child_terminates_directly(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_runtime, "_child_pids", lambda pid, name: [])
    proc = _FakeProc(["spindoctor.exe", "doctor"])
    _runtime.stop_worker(proc)
    assert proc.terminated


def test_stop_worker_ignores_finished_process():
    proc = _FakeProc(["x"], running=False)
    _runtime.stop_worker(proc)
    assert not proc.terminated


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process snapshot")
def test_stop_worker_leaves_no_same_named_child():
    """Real process: a venv python.exe is itself a launcher with a python.exe child."""
    import os
    import time

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(120)"],
        stdout=subprocess.PIPE, text=True,
    )
    assert proc.stdout.readline().strip() == "ready"
    _runtime.stop_worker(proc, timeout=20)
    proc.wait(timeout=20)
    assert proc.poll() is not None
    time.sleep(0.5)
    assert _runtime._child_pids(proc.pid, os.path.basename(sys.executable)) == []
