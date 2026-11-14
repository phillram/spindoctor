"""Readiness, failure and exact-process checks for the real EXE smoke harness."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "smoke_waits", Path(__file__).resolve().parent.parent / "build" / "smoke_waits.py")
waits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(waits)


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(waits, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds)))
    return now


def test_readiness_returns_the_observed_value_without_sleep(clock):
    observed = {12: 123.0}
    assert waits.wait_until(lambda: observed, "ready") is observed
    assert clock[0] == 0


def test_readiness_requires_continuous_stability(clock):
    observations = iter([True, False, True, True, True])
    assert waits.wait_until(lambda: next(observations), "window", stable_for=0.09)
    assert clock[0] == pytest.approx(0.2)


def test_readiness_timeout_is_bounded(clock):
    with pytest.raises(TimeoutError, match="worker prompt"):
        waits.wait_until(lambda: False, "worker prompt", timeout=0.12)
    assert clock[0] == pytest.approx(0.12)


def test_early_exit_fails_even_if_the_check_would_pass(clock):
    check = Mock(return_value=True)
    proc = SimpleNamespace(poll=lambda: 2, returncode=2)
    with pytest.raises(RuntimeError, match="exited early"):
        waits.wait_until(check, "worker", proc=proc)
    check.assert_not_called()


@pytest.mark.parametrize("children, starts, expected", [
    ([], {}, {}),
    ([12], {12: None}, {}),
    ([12, 13], {12: 123.0, 13: 124.0}, {12: 123.0, 13: 124.0}),
])
def test_worker_readiness_requires_original_process_identities(monkeypatch, children, starts, expected):
    monkeypatch.setattr(waits, "_child_pids", lambda pid, name: children)
    monkeypatch.setattr(waits._win32, "process_start_time", starts.get)
    assert waits.worker_identities(SimpleNamespace(pid=1), "worker.exe") == expected


@pytest.mark.parametrize("exited, fail", [(True, False), (False, True)])
def test_original_worker_handles_are_closed_and_survivors_cleaned(monkeypatch, exited, fail):
    kernel = Mock()
    kernel.OpenProcess.return_value = 100
    kernel.WaitForSingleObject.return_value = 0 if exited else 258
    monkeypatch.setattr(waits._win32, "_kernel32", lambda: kernel)
    monkeypatch.setattr(waits._win32, "process_start_time", lambda pid: 123.0)
    try:
        with waits.owned_workers({12: 123.0}) as alive:
            assert alive() == ([] if exited else [12])
            if fail:
                raise ValueError("smoke failed")
    except ValueError:
        assert fail
    kernel.CloseHandle.assert_called_once_with(100)
    if exited:
        kernel.TerminateProcess.assert_not_called()
    else:
        kernel.TerminateProcess.assert_called_once_with(100, 1)
        assert kernel.WaitForSingleObject.call_args.args == (100, 5000)


def test_reused_worker_pid_is_closed_but_never_terminated(monkeypatch):
    kernel = Mock()
    kernel.OpenProcess.return_value = 100
    kernel.WaitForSingleObject.return_value = 258
    monkeypatch.setattr(waits._win32, "_kernel32", lambda: kernel)
    monkeypatch.setattr(waits._win32, "process_start_time", lambda pid: 456.0)
    with pytest.raises(RuntimeError, match="changed before observation"):
        with waits.owned_workers({12: 123.0}):
            pytest.fail("a reused PID must not be treated as our worker")
    kernel.CloseHandle.assert_called_once_with(100)
    kernel.TerminateProcess.assert_not_called()


@pytest.mark.parametrize("pid, cls, width, hung, expected", [
    (12, "TkTopLevel", 800, False, True),
    (99, "TkTopLevel", 800, False, False),  # another application's window
    (12, "OtherWindow", 800, False, False),
    (12, "TkTopLevel", 1, False, False),    # not laid out yet
    (12, "TkTopLevel", 800, True, False),
])
def test_gui_readiness_checks_ownership_layout_and_responsiveness(
        monkeypatch, pid, cls, width, hung, expected):
    monkeypatch.setattr(waits, "_child_pids", lambda pid, name: [12])
    window = SimpleNamespace(pid=pid, cls=cls, width=width, height=600, hwnd=100)
    monkeypatch.setattr(waits._win32, "list_windows", lambda: [window])
    monkeypatch.setattr(waits._win32, "is_hung", lambda hwnd: hung)
    assert waits.gui_window_ready(SimpleNamespace(pid=1), "gui.exe") is expected
