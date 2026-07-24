"""Tests for spindoctor.autostart — the Windows Task Scheduler wrapper.

Headless on every platform: the Windows code path is exercised by
monkeypatching `_run_schtasks` so we don't need a real schtasks.exe (or
admin rights). The non-Windows code path raises `NotSupportedError`,
which is what we assert on macOS/Linux runners.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import pytest

from spindoctor import autostart


@dataclass
class _FakeProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


# ─── Platform gating ──────────────────────────────────────────────────────────

@pytest.mark.skipif(sys.platform == "win32",
                    reason="non-Windows guard test")
def test_create_raises_not_supported_off_windows():
    with pytest.raises(autostart.NotSupportedError):
        autostart.create_logon_task("doesn't matter")


@pytest.mark.skipif(sys.platform == "win32",
                    reason="non-Windows guard test")
def test_delete_raises_not_supported_off_windows():
    with pytest.raises(autostart.NotSupportedError):
        autostart.delete_logon_task()


@pytest.mark.skipif(sys.platform == "win32",
                    reason="non-Windows guard test")
def test_task_exists_raises_not_supported_off_windows():
    with pytest.raises(autostart.NotSupportedError):
        autostart.task_exists()


# ─── Windows-mocked behavior (runs on every OS via monkeypatch) ───────────────

def _force_windows(monkeypatch):
    """Pretend we're on Windows so the platform guard short-circuits.

    Used in every Windows-behaviour test so the same suite runs the same
    code path on macOS/Linux CI runners — schtasks.exe itself is mocked.
    """
    monkeypatch.setattr(autostart.sys, "platform", "win32")


def test_create_logon_task_invokes_schtasks_with_expected_args(monkeypatch):
    _force_windows(monkeypatch)
    captured: dict = {}

    def fake_run(args):
        captured["args"] = list(args)
        return _FakeProc(returncode=0, stdout="SUCCESS: ...\n")

    monkeypatch.setattr(autostart, "_run_schtasks", fake_run)

    result = autostart.create_logon_task("cmd.exe /c echo hi")
    assert "/Create" in captured["args"]
    assert "/SC" in captured["args"]
    assert "ONLOGON" in captured["args"]
    assert "/RL" in captured["args"]
    assert "LIMITED" in captured["args"]
    # /F = idempotent overwrite. Without it a second create would fail.
    assert "/F" in captured["args"]
    assert result.name == autostart.DEFAULT_LOGON_TASK
    assert result.command == "cmd.exe /c echo hi"


def test_create_logon_task_propagates_failure(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(
        autostart, "_run_schtasks",
        lambda _args: _FakeProc(returncode=1, stderr="ERROR: access denied"),
    )
    with pytest.raises(RuntimeError, match="access denied"):
        autostart.create_logon_task("cmd.exe /c echo hi")


def test_create_logon_task_rejects_empty_command(monkeypatch):
    _force_windows(monkeypatch)
    with pytest.raises(ValueError):
        autostart.create_logon_task("   ")


def test_create_logon_task_includes_delay_when_set(monkeypatch):
    _force_windows(monkeypatch)
    captured: dict = {}

    def fake_run(args):
        captured["args"] = list(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr(autostart, "_run_schtasks", fake_run)
    autostart.create_logon_task("cmd.exe /c x", delay_minutes=5)
    assert "/DELAY" in captured["args"]
    # schtasks expects HHHH:MM — five minutes → 0005:00.
    assert "0005:00" in captured["args"]


def test_create_logon_task_rejects_out_of_range_delay(monkeypatch):
    _force_windows(monkeypatch)
    with pytest.raises(ValueError):
        autostart.create_logon_task("cmd.exe /c x", delay_minutes=99999)


def test_task_exists_true_when_query_exits_zero(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(
        autostart, "_run_schtasks",
        lambda _args: _FakeProc(returncode=0, stdout="(task info)"),
    )
    assert autostart.task_exists() is True


def test_task_exists_false_when_query_fails(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(
        autostart, "_run_schtasks",
        lambda _args: _FakeProc(returncode=1, stderr="ERROR: not found"),
    )
    assert autostart.task_exists() is False


def test_delete_logon_task_propagates_failure(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(
        autostart, "_run_schtasks",
        lambda _args: _FakeProc(returncode=1, stderr="ERROR: not found"),
    )
    with pytest.raises(RuntimeError):
        autostart.delete_logon_task()


def test_delete_logon_task_returns_output_on_success(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(
        autostart, "_run_schtasks",
        lambda _args: _FakeProc(returncode=0, stdout="SUCCESS: deleted\n"),
    )
    out = autostart.delete_logon_task()
    assert "SUCCESS" in out


def test_run_schtasks_hides_console_window(monkeypatch):
    """``_run_schtasks`` must pass ``CREATE_NO_WINDOW`` to ``subprocess.run``.

    Without it, every ``task_exists`` / ``create_logon_task`` /
    ``delete_logon_task`` call from the GUI pops a black ``cmd``
    window on Windows — jarring for cabinet owners and the exact
    UX papercut we hide for the main CLI subprocess in
    ``gui.py``.
    """
    captured: dict = {}

    def fake_run(_args, **kwargs):
        captured.update(kwargs)
        return _FakeProc(returncode=0)

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    autostart._run_schtasks(["/Query", "/TN", "x"])
    # 0x08000000 == CREATE_NO_WINDOW. Hardcoded in the source rather
    # than imported from a constant — guard against the value being
    # accidentally cleared back to 0 in a refactor.
    assert captured.get("creationflags") == 0x08000000


# ─── friendly schtasks error interpretation (PR E polish) ────────────────────


def test_interpret_schtasks_access_denied_suggests_admin():
    from spindoctor.autostart import _interpret_schtasks_error

    msg = _interpret_schtasks_error(
        "create the task",
        "ERROR: Access is denied.",
    )
    assert "access denied" in msg.lower()
    assert "administrator" in msg.lower()


def test_interpret_schtasks_already_exists_points_at_remove():
    from spindoctor.autostart import _interpret_schtasks_error

    msg = _interpret_schtasks_error(
        "create the task",
        "ERROR: The task XML contains a value which is incorrectly formatted "
        "or out of range. The task with name X already exists.",
    )
    assert "already" in msg.lower()
    assert "remove" in msg.lower()


def test_interpret_schtasks_does_not_exist_suggests_schedule():
    from spindoctor.autostart import _interpret_schtasks_error

    msg = _interpret_schtasks_error(
        "remove the task",
        "ERROR: The system cannot find the file specified.\n"
        "The specified task does not exist.",
    )
    assert "does not exist" in msg.lower() or "no task is currently registered" in msg.lower()


def test_interpret_schtasks_unknown_error_falls_back_to_raw():
    from spindoctor.autostart import _interpret_schtasks_error

    msg = _interpret_schtasks_error(
        "create the task",
        "ERROR: Some bizarre Windows error code 0x80070043.",
    )
    # Falls back to including the raw output for power-user diagnosis.
    assert "0x80070043" in msg
