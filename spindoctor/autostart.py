"""Windows Task Scheduler helpers for the wheel-refresh tools.

Wraps ``schtasks.exe`` so cabinet owners can register a "refresh on log
on" task without dropping into ``cmd.exe`` or fighting with the
``Task Scheduler`` MMC snap-in. The CLI surface is deliberately thin:
:func:`create_logon_task`, :func:`delete_logon_task`, :func:`task_exists`.

We deliberately *don't* depend on ``pywin32`` — ``schtasks.exe`` ships
with every supported Windows version (7 SP1+) and produces parseable
text output, so a subprocess wrapper keeps the build small (PyInstaller
bundle stays under the size budget) and works on the frozen exe without
extra DLLs.

On non-Windows the functions raise :class:`NotSupportedError` so the GUI
can surface a clear "Windows-only" message instead of failing mid-call.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Sequence


# Default task name used by SpinDoctor's GUI. Kept as a module constant so
# both the CLI helper (future) and the GUI agree on what to delete.
DEFAULT_LOGON_TASK = "SpinDoctor Refresh Wheels"


class NotSupportedError(RuntimeError):
    """Raised when called on a platform without Task Scheduler (i.e. not Windows)."""


@dataclass
class TaskCreateResult:
    name: str
    command: str
    output: str


def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise NotSupportedError(
            "Windows Task Scheduler integration is only available on Windows. "
            "On macOS/Linux, the equivalent is `crontab -e` with an "
            "`@reboot` line, or a launchd / systemd-user unit."
        )


def _run_schtasks(args: Sequence[str]) -> subprocess.CompletedProcess:
    """Run schtasks.exe with the given args and return the completed process.

    Capture stdout/stderr together so the GUI can show a single blob if
    something goes wrong — schtasks tends to write its actual error
    messages to stderr while emitting "SUCCESS" to stdout, so merging
    them keeps the user-facing message coherent.
    """
    return subprocess.run(  # noqa: S603 — args are constants, not user-supplied
        ["schtasks.exe", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def task_exists(name: str = DEFAULT_LOGON_TASK) -> bool:
    """Return True iff a scheduled task named *name* exists."""
    _ensure_windows()
    proc = _run_schtasks(["/Query", "/TN", name])
    # `/Query /TN` exits 0 when the task exists, 1 (or higher) when it
    # doesn't — schtasks doesn't have a dedicated "not found" exit code.
    return proc.returncode == 0


def create_logon_task(
    command: str,
    *,
    name: str = DEFAULT_LOGON_TASK,
    delay_minutes: Optional[int] = None,
) -> TaskCreateResult:
    """Register *command* to run at log-on under the current user.

    *command* is the literal command line schtasks will invoke (already
    quoted as needed). ``/RL LIMITED`` keeps the task running with the
    user's normal privileges — we don't need elevation to run the CLI
    helpers, and asking for it would force a UAC prompt every log-on.

    *delay_minutes* maps to schtasks' ``/DELAY`` flag — useful when
    other startup tasks (HyperSpin, RocketLauncher) take a moment to
    settle and you don't want the rebuild fighting them for the disk.
    """
    _ensure_windows()
    if not command.strip():
        raise ValueError("command must not be empty")

    args = [
        "/Create",
        "/TN", name,
        "/TR", command,
        "/SC", "ONLOGON",
        "/RL", "LIMITED",
        # /F = overwrite an existing task with the same name; without it
        # schtasks errors on a second create. Idempotent-by-default
        # matches the rest of SpinDoctor's apply commands.
        "/F",
    ]
    if delay_minutes is not None:
        if delay_minutes < 0 or delay_minutes > 9999:
            raise ValueError("delay_minutes must be between 0 and 9999")
        args += ["/DELAY", f"{delay_minutes:04d}:00"]

    proc = _run_schtasks(args)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(
            f"schtasks /Create exited with code {proc.returncode}.\n"
            f"Output:\n{output.strip() or '(no output)'}"
        )
    return TaskCreateResult(name=name, command=command, output=output.strip())


def delete_logon_task(name: str = DEFAULT_LOGON_TASK) -> str:
    """Delete the scheduled task named *name*. Returns schtasks output.

    Raises :class:`RuntimeError` if the task doesn't exist OR the delete
    fails — callers that want "delete-if-exists" semantics should check
    :func:`task_exists` first.
    """
    _ensure_windows()
    proc = _run_schtasks(["/Delete", "/TN", name, "/F"])
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(
            f"schtasks /Delete exited with code {proc.returncode}.\n"
            f"Output:\n{output.strip() or '(no output)'}"
        )
    return output.strip()
