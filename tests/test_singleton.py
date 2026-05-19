"""Cross-process file-lock tests for the GUI singleton.

Two GUI windows on the same machine racing on the HyperSpin XML is a
data-loss bug. The singleton lock is what prevents that, so it gets
real assertions — including the cross-process hand-off path.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spindoctor._singleton import SingletonLock


def test_acquire_then_release_round_trip(tmp_path: Path) -> None:
    lock_path = tmp_path / "gui.lock"
    lock = SingletonLock(lock_path)
    assert lock.acquire() is True
    assert lock_path.exists()
    lock.release()
    # release removes the file so a fresh launch never sees stale PID
    assert not lock_path.exists()


def test_second_acquire_in_same_process_succeeds_after_release(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "gui.lock"
    a = SingletonLock(lock_path)
    assert a.acquire() is True
    a.release()
    b = SingletonLock(lock_path)
    assert b.acquire() is True
    b.release()


def test_env_disable_short_circuits_acquire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPINDOCTOR_DISABLE_SINGLETON", "1")
    lock_path = tmp_path / "gui.lock"
    # Two locks in the same process can both acquire when disabled.
    a = SingletonLock(lock_path)
    b = SingletonLock(lock_path)
    assert a.acquire() is True
    assert b.acquire() is True


def test_cross_process_second_acquire_fails(tmp_path: Path) -> None:
    """The real bug class — a *second process* must be rejected."""
    lock_path = tmp_path / "gui.lock"
    repo_root = Path(__file__).resolve().parents[1]

    holder_script = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(repo_root)!r})
        from spindoctor._singleton import SingletonLock
        from pathlib import Path
        lock = SingletonLock(Path({str(lock_path)!r}))
        ok = lock.acquire()
        sys.stdout.write("HELD" if ok else "FAIL")
        sys.stdout.flush()
        time.sleep(5)
        """
    )

    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "SPINDOCTOR_DISABLE_SINGLETON": "0"},
    )
    try:
        # Wait for the holder to confirm it grabbed the lock.
        marker = holder.stdout.read(4)
        assert marker == b"HELD", f"holder failed to acquire: {marker!r}"

        # Now a second SingletonLock in *this* process must be rejected.
        contender = SingletonLock(lock_path)
        assert contender.acquire() is False
    finally:
        holder.terminate()
        holder.wait(timeout=5)
