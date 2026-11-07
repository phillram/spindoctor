"""Set Windows Resolution: put the desktop back to HyperSpin's resolution.

A game that crashes, or an emulator that doesn't restore the display mode,
can leave Windows at its own resolution, and HyperSpin then starts stretched
or in a corner.  HyperSpin's own size is ``Settings\\Settings.ini``
``[Resolution] Width`` / ``Height``.  :func:`set_resolution` sets the primary
display to it with ``ChangeDisplaySettingsExW``, after testing the mode
(``CDS_TEST``), and saves it (``CDS_UPDATEREGISTRY``) so it sticks after a
restart.  Colour depth and refresh rate are left to Windows.  No bundled
resolution tool is needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Optional

ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002

#: ``ChangeDisplaySettingsExW`` results, in words.
RESULTS = {
    0: "done",
    1: "Windows has to restart first",
    -1: "the display driver failed",
    -2: "the display doesn't support it",
    -3: "Windows couldn't save it",
    -4: "bad flags",
    -5: "bad parameters",
    -6: "the display is in dual view",
}


class Outcome(NamedTuple):
    width: int
    height: int
    before: tuple       # (width, height) the display had
    code: int           # ChangeDisplaySettingsExW result; 0 also when nothing had to change

    @property
    def changed(self) -> bool:
        return self.code == 0 and self.before != (self.width, self.height)

    @property
    def note(self) -> str:
        size = f"{self.width} × {self.height}"
        if self.code != 0:
            return f"Couldn't set {size}"
        return f"Resolution set to {size}" if self.changed else f"Already {size}"

    def line(self) -> str:
        size = f"{self.width}x{self.height}"
        if self.code != 0:
            why = RESULTS.get(self.code, f"error {self.code}")
            return f"set-resolution: {size} not set: {why} (still {self.before[0]}x{self.before[1]})"
        if not self.changed:
            return f"set-resolution: already {size}"
        return f"set-resolution: {self.before[0]}x{self.before[1]} -> {size}"


def hyperspin_resolution(config) -> Optional["tuple[int, int]"]:
    """HyperSpin's ``[Resolution] Width`` / ``Height``, or None if unset or not numbers."""
    folder = getattr(config, "hyperspin_dir", "")
    if not folder:
        return None
    from .rocketlauncher import _read_rl_ini

    section = _read_rl_ini(Path(folder) / "Settings" / "Settings.ini").get("resolution", {})
    try:
        width, height = int(section.get("width", "")), int(section.get("height", ""))
    except ValueError:
        return None
    return (width, height) if width > 0 and height > 0 else None


class WindowsDisplay:
    """The primary display, through ``EnumDisplaySettingsW`` / ``ChangeDisplaySettingsExW``."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", ctypes.c_wchar * 32),
                ("dmSpecVersion", w.WORD), ("dmDriverVersion", w.WORD),
                ("dmSize", w.WORD), ("dmDriverExtra", w.WORD), ("dmFields", w.DWORD),
                ("dmPositionX", w.LONG), ("dmPositionY", w.LONG),
                ("dmDisplayOrientation", w.DWORD), ("dmDisplayFixedOutput", w.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", w.WORD), ("dmBitsPerPel", w.DWORD),
                ("dmPelsWidth", w.DWORD), ("dmPelsHeight", w.DWORD),
                ("dmDisplayFlags", w.DWORD), ("dmDisplayFrequency", w.DWORD),
                ("dmICMMethod", w.DWORD), ("dmICMIntent", w.DWORD),
                ("dmMediaType", w.DWORD), ("dmDitherType", w.DWORD),
                ("dmReserved1", w.DWORD), ("dmReserved2", w.DWORD),
                ("dmPanningWidth", w.DWORD), ("dmPanningHeight", w.DWORD),
            ]

        self._c, self.DEVMODEW = ctypes, DEVMODEW
        u = self._u = ctypes.WinDLL("user32", use_last_error=True)
        u.EnumDisplaySettingsW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(DEVMODEW)]
        u.EnumDisplaySettingsW.restype = w.BOOL
        u.ChangeDisplaySettingsExW.argtypes = [w.LPCWSTR, ctypes.POINTER(DEVMODEW), w.HWND,
                                               w.DWORD, w.LPVOID]
        u.ChangeDisplaySettingsExW.restype = ctypes.c_long

    def _current_mode(self):
        mode = self.DEVMODEW()
        mode.dmSize = self._c.sizeof(mode)
        if not self._u.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS & 0xFFFFFFFF,
                                            self._c.byref(mode)):
            raise OSError("Windows didn't report the current display mode")
        return mode

    def current(self) -> "tuple[int, int]":
        mode = self._current_mode()
        return mode.dmPelsWidth, mode.dmPelsHeight

    def change(self, width: int, height: int, flags: int) -> int:
        mode = self._current_mode()
        mode.dmPelsWidth, mode.dmPelsHeight = width, height
        mode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
        return self._u.ChangeDisplaySettingsExW(None, self._c.byref(mode), None, flags, None)


def set_resolution(width: int, height: int, display=None) -> Outcome:
    """Set the primary display to *width* x *height*, tested first and saved."""
    display = display or WindowsDisplay()
    before = tuple(display.current())
    if before == (width, height):
        return Outcome(width, height, before, 0)
    code = display.change(width, height, CDS_TEST)
    if code == 0:
        code = display.change(width, height, CDS_UPDATEREGISTRY)
    return Outcome(width, height, before, code)
