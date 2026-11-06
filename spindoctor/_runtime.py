"""Embedded command workers for self-contained frozen GUI/CLI executables."""
from __future__ import annotations

import os
import sys
import traceback
from typing import Optional, Sequence


WORKER_FLAG = "--run-tool"
TOOL_MODULES = {
    "spindoctor": "spindoctor.cli",
    "spindoctor-fav": "spindoctor.favorites",
    "spindoctor-recent": "spindoctor.recent",
    "spindoctor-stats": "spindoctor.playtime",
}


def frozen_tool_command(name: str) -> list[str]:
    """Invoke a bundled worker, never a possibly stale sibling/PATH binary."""
    if name not in TOOL_MODULES:
        raise ValueError(f"Unknown SpinDoctor tool: {name!r}")
    return [sys.executable, WORKER_FLAG, name]


def tool_command_text(name: str) -> str:
    """Command prefix for generated Windows batch files and scheduled tasks."""
    if name not in TOOL_MODULES:
        raise ValueError(f"Unknown SpinDoctor tool: {name!r}")
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {WORKER_FLAG} {name}'
    return name


def _windows_stream(handle_id: int, mode: str):
    """Open a private fd for an inherited Windows pipe/redirected handle.

    Windowed PyInstaller executables set sys.std* to None even when Popen
    explicitly supplied pipes. The native standard handles still carry those
    pipes. Duplicate before wrapping so closing the Python stream cannot
    invalidate the process's original standard handle.
    """
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.GetStdHandle(handle_id)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise OSError("No inherited standard handle")
    process = kernel.GetCurrentProcess()
    duplicate = wintypes.HANDLE()
    if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        flags = (os.O_RDONLY if mode == "r" else os.O_WRONLY) | os.O_BINARY
        fd = msvcrt.open_osfhandle(duplicate.value, flags)
    except (OSError, ValueError):
        kernel.CloseHandle(duplicate)
        raise
    try:
        return os.fdopen(fd, mode, buffering=1, encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        os.close(fd)
        raise


def ensure_worker_stdio() -> None:
    """Restore redirected streams, or use EOF/devnull when truly detached."""
    for name, handle_id, mode in (("stdin", -10, "r"), ("stdout", -11, "w"), ("stderr", -12, "w")):
        if getattr(sys, name) is not None:
            continue
        stream = None
        if sys.platform == "win32":
            try:
                stream = _windows_stream(handle_id, mode)
            except (OSError, ValueError):
                pass
        if stream is None:
            stream = open(os.devnull, mode, encoding="utf-8", errors="replace")
        setattr(sys, name, stream)


def run_tool(name: str, args: Sequence[str]) -> int:
    """Run an allowlisted tool without opening Tk or entering the GUI lock."""
    ensure_worker_stdio()
    if name not in TOOL_MODULES:
        print(f"Unknown SpinDoctor tool: {name!r}", file=sys.stderr)
        return 2
    try:
        if name == "spindoctor":
            from .cli import cli

            cli.main(args=list(args), prog_name=name)
            return 0
        if name == "spindoctor-fav":
            from .favorites import main
        elif name == "spindoctor-recent":
            from .recent import main
        else:
            from .playtime import main
        return main(list(args)) or 0
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception:
        # A failed worker must report its traceback through the output pipe,
        # not trigger PyInstaller's windowed "failed to execute script" dialog.
        traceback.print_exc()
        return 1


def dispatch_worker(args: Sequence[str]) -> int:
    if not args:
        ensure_worker_stdio()
        print(f"{WORKER_FLAG} requires a tool name.", file=sys.stderr)
        return 2
    return run_tool(args[0], args[1:])


def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    """Frozen/pip CLI entry point; normal CLI arguments stay unchanged."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == [WORKER_FLAG]:
        return dispatch_worker(args[1:])
    return run_tool("spindoctor", args)
