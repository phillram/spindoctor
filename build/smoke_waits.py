"""Bounded readiness checks for the real, isolated Windows EXE smoke tests."""
from contextlib import contextmanager
import time

from spindoctor import _win32
from spindoctor._runtime import _child_pids


def wait_until(check, label, proc=None, timeout=30, stable_for=0):
    """Return the truthy check result, failing on early exit or a deadline."""
    deadline = time.monotonic() + timeout
    ready_since = None
    while True:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"{label}: process exited early ({proc.returncode})")
        value = check()
        now = time.monotonic()
        if value:
            if ready_since is None:
                ready_since = now
            if now - ready_since >= stable_for:
                return value
        else:
            ready_since = None
        if now >= deadline:
            raise TimeoutError(f"timed out waiting for {label}")
        time.sleep(min(0.05, deadline - now))


def worker_identities(proc, exe_name):
    """Record the original children before Stop, not their later parentage."""
    identities = {
        pid: _win32.process_start_time(pid)
        for pid in _child_pids(proc.pid, exe_name)
    }
    return identities if identities and None not in identities.values() else {}


@contextmanager
def owned_workers(identities):
    """Pin original process handles, including failure cleanup after reparenting."""
    from ctypes import wintypes

    kernel = _win32._kernel32()
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    handles = {}
    try:
        for pid, started in identities.items():
            handle = kernel.OpenProcess(0x00100001, False, pid)  # SYNCHRONIZE | TERMINATE
            if not handle:
                raise OSError(f"cannot open smoke worker {pid}")
            if _win32.process_start_time(pid) != started:
                kernel.CloseHandle(handle)
                raise RuntimeError(f"smoke worker {pid} changed before observation")
            handles[pid] = handle

        def alive():
            return [pid for pid, handle in handles.items()
                    if kernel.WaitForSingleObject(handle, 0) != 0]

        yield alive
    finally:
        for handle in handles.values():
            try:
                if kernel.WaitForSingleObject(handle, 0) == 258:  # WAIT_TIMEOUT
                    kernel.TerminateProcess(handle, 1)
                    kernel.WaitForSingleObject(handle, 5000)
            finally:
                kernel.CloseHandle(handle)


def gui_window_ready(proc, exe_name):
    """Require a visible, responsive Tk window owned by this isolated EXE."""
    pids = {proc.pid, *_child_pids(proc.pid, exe_name)}
    return any(
        win.pid in pids and win.cls == "TkTopLevel"
        and win.width > 100 and win.height > 100
        and not _win32.is_hung(win.hwnd)
        for win in _win32.list_windows()
    )
