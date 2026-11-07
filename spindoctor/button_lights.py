"""Reset Button Lights: stop Ultimarc PAC-LED64 boards flashing on their own.

A PAC-LED64 keeps a flash speed for each port on the board.  After a USB
dropout some ports can be left flashing, whatever LEDBlinky plays, and
LEDBlinky never resets flash speeds (it sets colours and on/off).  This sets
every port's flash speed to 0 on every PAC-LED64 (product IDs 0x1401-0x1404)
through Ultimarc's ``PacDrive32.dll``, which LEDBlinky ships.  Colours and
on/off stay with LEDBlinky, which can keep running.

:func:`lights_off` uses the same DLL to set every LED to 0 once LEDBlinky
has quit (Exit To Windows calls it): LEDBlinky's quit can leave a board lit.

``PacDrive32.dll`` is 32-bit, so the calls run in 32-bit Windows PowerShell
(``SysWOW64``) whatever SpinDoctor's own bitness, with the DLL's path and the
job passed in environment variables.  The script prints one line per board
and a summary, which :func:`parse` reads.
"""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

DLL_NAME = "PacDrive32.dll"
DLL_ENV = "SPINDOCTOR_PACDRIVE"
JOB_ENV = "SPINDOCTOR_PACDRIVE_JOB"  # "flash": zero the flash speeds; "off": every LED to 0

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    if ([IntPtr]::Size -ne 4) { throw 'needs 32-bit PowerShell' }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SpinDoctorPacFlash {
    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr LoadLibraryW(string path);
    [DllImport("PacDrive32.dll")] public static extern int PacInitialize();
    [DllImport("PacDrive32.dll")] public static extern void PacShutdown();
    [DllImport("PacDrive32.dll")] public static extern int PacGetProductId(int id);
    [DllImport("PacDrive32.dll")] public static extern bool Pac64SetLEDFlashSpeeds(int id, int speed);
    [DllImport("PacDrive32.dll")] public static extern bool Pac64SetLEDFlashSpeed(int id, int port, int speed);
    [DllImport("PacDrive32.dll")] public static extern bool Pac64SetLEDIntensities(int id, byte[] data);
}
'@
    $dll = $env:SPINDOCTOR_PACDRIVE
    $off = $env:SPINDOCTOR_PACDRIVE_JOB -eq 'off'
    if ([SpinDoctorPacFlash]::LoadLibraryW($dll) -eq [IntPtr]::Zero) { throw "cannot load $dll" }
    $n = [SpinDoctorPacFlash]::PacInitialize()
    try {
        $boards = 0
        for ($i = 0; $i -lt $n; $i++) {
            $product = [SpinDoctorPacFlash]::PacGetProductId($i)
            if ($product -lt 0x1401 -or $product -gt 0x1404) { continue }
            $boards++
            if ($off) {
                $ok = [SpinDoctorPacFlash]::Pac64SetLEDIntensities($i, (New-Object byte[] 64))
                "BOARD $($product - 0x1400) $ok 0"
                continue
            }
            $all = [SpinDoctorPacFlash]::Pac64SetLEDFlashSpeeds($i, 0)
            $failed = 0
            for ($port = 0; $port -lt 64; $port++) {
                if (-not [SpinDoctorPacFlash]::Pac64SetLEDFlashSpeed($i, $port, 0)) { $failed++ }
            }
            "BOARD $($product - 0x1400) $all $failed"
        }
        "DONE $n $boards"
    } finally { [SpinDoctorPacFlash]::PacShutdown() }
} catch {
    "ERROR $($_.Exception.Message)"
}
"""


class Board(NamedTuple):
    number: int          # the board ID LEDBlinky shows (1-4)
    all_ok: bool         # Pac64SetLEDFlashSpeeds accepted
    port_failures: int   # ports whose Pac64SetLEDFlashSpeed failed


class Result(NamedTuple):
    devices: int = 0     # Ultimarc devices PacDrive found
    boards: tuple = ()
    error: str = ""

    @property
    def note(self) -> str:
        """The few words shown on screen."""
        if self.error:
            return "Button light reset failed"
        if not self.boards:
            return "No button light boards found"
        return "Button lights reset"

    def lines(self) -> "list[str]":
        """What happened, one line each, for the console and the log."""
        if self.error:
            return [f"button lights: {self.error}"]
        out = [f"  LED board {b.number}: flash speeds 0 (board-wide ok: {b.all_ok}, "
               f"ports that failed: {b.port_failures})" for b in self.boards]
        return out + [f"button lights: {self.devices} Ultimarc device(s), "
                      f"{len(self.boards)} LED board(s) reset"]


def parse(output: str) -> Result:
    """Read what the PowerShell script printed."""
    boards, devices, done = [], 0, False
    for raw in output.splitlines():
        parts = raw.strip().split(" ")
        if parts[0] == "ERROR":
            return Result(error=raw.strip()[len("ERROR "):] or "unknown error")
        try:
            if parts[0] == "BOARD" and len(parts) == 4:
                boards.append(Board(int(parts[1]), parts[2] == "True", int(parts[3])))
            elif parts[0] == "DONE" and len(parts) == 3:
                devices, done = int(parts[1]), True
        except ValueError:
            continue
    if not done:
        return Result(error="PowerShell printed no result" + (f": {output.strip()[:200]}" if output.strip() else ""))
    return Result(devices, tuple(boards))


def find_dll(config, explicit: Optional[str] = None) -> Optional[Path]:
    """*explicit*, else ``PacDrive32.dll`` in ``ledblinky_dir`` (any case); None if missing."""
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    folder = getattr(config, "ledblinky_dir", "")
    if not folder:
        return None
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.name.lower() == DLL_NAME.lower() and entry.is_file():
                    return Path(entry.path)
    except OSError:
        pass
    return None


def powershell_32() -> str:
    """32-bit Windows PowerShell: ``SysWOW64`` on 64-bit Windows, else ``System32``."""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    tail = os.path.join("WindowsPowerShell", "v1.0", "powershell.exe")
    wow = os.path.join(root, "SysWOW64", tail)
    return wow if os.path.isfile(wow) else os.path.join(root, "System32", tail)


def reset(dll: Path, run=subprocess.run) -> Result:
    """Zero every PAC-LED64 port's flash speed through *dll*."""
    return _run_script(dll, "flash", run)


def lights_off(dll: Path, run=subprocess.run) -> Result:
    """Set every LED on every PAC-LED64 to 0 through *dll*.

    For when LEDBlinky has quit: its quit can leave a board lit.  Never call
    it while LEDBlinky runs, or the two fight over the lights.
    """
    return _run_script(dll, "off", run)


def _run_script(dll: Path, job: str, run) -> Result:
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ)
    env[DLL_ENV] = str(dll)
    env[JOB_ENV] = job
    try:
        proc = run(
            [powershell_32(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, timeout=60, creationflags=0x08000000,  # CREATE_NO_WINDOW
            universal_newlines=True, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Result(error=f"could not run 32-bit PowerShell: {exc}")
    result = parse(proc.stdout or "")
    if result.error and proc.stderr and proc.stderr.strip():
        return Result(error=f"{result.error} ({proc.stderr.strip().splitlines()[-1][:200]})")
    return result
