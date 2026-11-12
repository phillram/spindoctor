"""Windows calls for ``spindoctor test``: processes, windows, keys and the screen.

Thin ctypes wrappers with no test policy; :mod:`spindoctor.gametest` decides
what the results mean.  ``ctypes.wintypes`` is imported inside the functions,
as :mod:`spindoctor._runtime` does, so importing this module is safe on any
OS.  Every call raises :class:`UnsupportedPlatform` off Windows.

Everything here also works on Windows 7: Toolhelp32, ``EnumWindows``,
``IsHungAppWindow``, ``QueryFullProcessImageNameW``, ``keybd_event`` and GDI
exist there.  DXGI Desktop Duplication (Windows 8+) and the command-line query
(Windows 8.1+) have fallbacks.
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Optional


class UnsupportedPlatform(OSError):
    """A Windows-only call made on another OS."""


def _require() -> None:
    if sys.platform != "win32":
        raise UnsupportedPlatform("this needs Windows")


@dataclass
class ProcInfo:
    pid: int
    parent: int
    name: str


@dataclass
class WinInfo:
    hwnd: int
    pid: int
    title: str
    cls: str
    left: int
    top: int
    width: int
    height: int


@dataclass
class Shot:
    """One screen capture: the full screen and a thumbnail, both 32-bit BGRA rows, top-down."""
    width: int
    height: int
    pixels: bytes
    thumb_width: int
    thumb_height: int
    thumb: bytes
    method: str


_LIBS: dict = {}


def _kernel32():
    lib = _LIBS.get("kernel32")
    if lib is None:
        import ctypes
        from ctypes import wintypes as w

        lib = ctypes.WinDLL("kernel32", use_last_error=True)
        lib.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        lib.CreateToolhelp32Snapshot.restype = w.HANDLE
        lib.Process32FirstW.argtypes = [w.HANDLE, ctypes.c_void_p]
        lib.Process32FirstW.restype = w.BOOL
        lib.Process32NextW.argtypes = [w.HANDLE, ctypes.c_void_p]
        lib.Process32NextW.restype = w.BOOL
        lib.CloseHandle.argtypes = [w.HANDLE]
        lib.CloseHandle.restype = w.BOOL
        lib.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        lib.OpenProcess.restype = w.HANDLE
        lib.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        lib.GetProcessTimes.restype = w.BOOL
        lib.QueryFullProcessImageNameW.argtypes = [
            w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        lib.QueryFullProcessImageNameW.restype = w.BOOL
        lib.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        lib.TerminateProcess.restype = w.BOOL
        lib.GetCurrentThreadId.argtypes = []
        lib.GetCurrentThreadId.restype = w.DWORD
        _LIBS["kernel32"] = lib
    return lib


def _user32():
    lib = _LIBS.get("user32")
    if lib is None:
        import ctypes
        from ctypes import wintypes as w

        lib = ctypes.WinDLL("user32", use_last_error=True)
        _LIBS["enum_proc"] = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        lib.EnumWindows.argtypes = [_LIBS["enum_proc"], w.LPARAM]
        lib.EnumWindows.restype = w.BOOL
        lib.IsWindowVisible.argtypes = [w.HWND]
        lib.IsWindowVisible.restype = w.BOOL
        lib.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        lib.GetWindowThreadProcessId.restype = w.DWORD
        lib.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        lib.GetWindowTextW.restype = ctypes.c_int
        lib.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        lib.GetClassNameW.restype = ctypes.c_int
        lib.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        lib.GetWindowRect.restype = w.BOOL
        lib.GetForegroundWindow.argtypes = []
        lib.GetForegroundWindow.restype = w.HWND
        lib.SetForegroundWindow.argtypes = [w.HWND]
        lib.SetForegroundWindow.restype = w.BOOL
        lib.BringWindowToTop.argtypes = [w.HWND]
        lib.BringWindowToTop.restype = w.BOOL
        lib.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        lib.ShowWindow.restype = w.BOOL
        lib.IsIconic.argtypes = [w.HWND]
        lib.IsIconic.restype = w.BOOL
        lib.IsHungAppWindow.argtypes = [w.HWND]
        lib.IsHungAppWindow.restype = w.BOOL
        lib.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
        lib.AttachThreadInput.restype = w.BOOL
        lib.keybd_event.argtypes = [w.BYTE, w.BYTE, w.DWORD, ctypes.c_size_t]
        lib.keybd_event.restype = None
        lib.MapVirtualKeyW.argtypes = [w.UINT, w.UINT]
        lib.MapVirtualKeyW.restype = w.UINT
        lib.GetSystemMetrics.argtypes = [ctypes.c_int]
        lib.GetSystemMetrics.restype = ctypes.c_int
        lib.GetDC.argtypes = [w.HWND]
        lib.GetDC.restype = w.HDC
        lib.ReleaseDC.argtypes = [w.HWND, w.HDC]
        lib.ReleaseDC.restype = ctypes.c_int
        _LIBS["user32"] = lib
    return lib


def _gdi32():
    lib = _LIBS.get("gdi32")
    if lib is None:
        import ctypes
        from ctypes import wintypes as w

        lib = ctypes.WinDLL("gdi32", use_last_error=True)
        lib.CreateCompatibleDC.argtypes = [w.HDC]
        lib.CreateCompatibleDC.restype = w.HDC
        lib.CreateDIBSection.argtypes = [
            w.HDC, ctypes.c_void_p, w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
        lib.CreateDIBSection.restype = w.HBITMAP
        lib.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
        lib.SelectObject.restype = w.HGDIOBJ
        lib.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD]
        lib.BitBlt.restype = w.BOOL
        lib.StretchBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.DWORD]
        lib.StretchBlt.restype = w.BOOL
        lib.SetStretchBltMode.argtypes = [w.HDC, ctypes.c_int]
        lib.SetStretchBltMode.restype = ctypes.c_int
        lib.SetBrushOrgEx.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        lib.SetBrushOrgEx.restype = w.BOOL
        lib.DeleteObject.argtypes = [w.HGDIOBJ]
        lib.DeleteObject.restype = w.BOOL
        lib.DeleteDC.argtypes = [w.HDC]
        lib.DeleteDC.restype = w.BOOL
        _LIBS["gdi32"] = lib
    return lib


# ─── processes ────────────────────────────────────────────────────────────────

def _proc_entry_type():
    cls = _LIBS.get("PROCESSENTRY32W")
    if cls is None:
        import ctypes
        from ctypes import wintypes as w

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", w.DWORD), ("szExeFile", ctypes.c_wchar * 260),
            ]

        cls = _LIBS["PROCESSENTRY32W"] = PROCESSENTRY32W
    return cls


def list_processes() -> list[ProcInfo]:
    """Every running process: PID, parent PID and program file name."""
    _require()
    import ctypes

    k = _kernel32()
    snapshot = k.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return []
    out: list[ProcInfo] = []
    try:
        entry = _proc_entry_type()()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            out.append(ProcInfo(entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return out


_QUERY_LIMITED = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION (Vista+)


def process_start_time(pid: int) -> Optional[float]:
    """When *pid* started, as a Unix timestamp; None when it can't be opened.

    A PID plus its start time names one process for good: Windows reuses
    PIDs, so a name check alone can match a different program later."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    k = _kernel32()
    handle = k.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return None
    try:
        times = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return ticks / 1e7 - 11644473600.0
    finally:
        k.CloseHandle(handle)


def process_image_path(pid: int) -> str:
    """The full path of *pid*'s program, or "" when it can't be read."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    k = _kernel32()
    handle = k.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return ""
    try:
        size = w.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        k.CloseHandle(handle)


def command_line(pid: int) -> str:
    """*pid*'s command line, or "" when it can't be read.

    ``NtQueryInformationProcess(ProcessCommandLineInformation)`` needs
    Windows 8.1; older systems fall back to ``wmic``."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    k = _kernel32()
    handle = k.OpenProcess(_QUERY_LIMITED, False, pid)
    if handle:
        try:
            nt = ctypes.WinDLL("ntdll")
            nt.NtQueryInformationProcess.argtypes = [
                w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
            nt.NtQueryInformationProcess.restype = ctypes.c_long
            size = 4096
            for _attempt in range(2):
                buf = ctypes.create_string_buffer(size)
                needed = w.ULONG(0)
                status = nt.NtQueryInformationProcess(handle, 60, buf, size, ctypes.byref(needed))
                if status == 0:
                    # UNICODE_STRING { USHORT Length; USHORT MaximumLength; PWSTR Buffer; }
                    length = struct.unpack_from("<H", buf.raw, 0)[0]
                    address = ctypes.c_void_p.from_buffer(buf, ctypes.sizeof(ctypes.c_void_p)).value
                    if address:
                        return ctypes.wstring_at(address, length // 2)
                    return ""
                if needed.value > size:
                    size = needed.value
                    continue
                break
        except (OSError, AttributeError, ValueError):
            pass
        finally:
            k.CloseHandle(handle)
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={int(pid)}", "get", "CommandLine", "/value"],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"CommandLine=(.*)", out)
    return m.group(1).strip() if m else ""


def terminate(pid: int) -> bool:
    """End *pid* at once (TerminateProcess).  False when it can't be opened."""
    _require()
    k = _kernel32()
    handle = k.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
    if not handle:
        return False
    try:
        return bool(k.TerminateProcess(handle, 1))
    finally:
        k.CloseHandle(handle)


# ─── windows and keys ─────────────────────────────────────────────────────────

def make_dpi_aware() -> None:
    """Report real pixels, not 96-DPI ones, for window sizes and screen captures."""
    _require()
    import ctypes

    try:
        ctypes.WinDLL("user32").SetProcessDPIAware()
    except (OSError, AttributeError):
        pass


def screen_rect() -> tuple[int, int, int, int]:
    """``(left, top, width, height)`` of the primary monitor."""
    _require()
    u = _user32()
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def list_windows() -> list[WinInfo]:
    """Every visible top-level window, in Z order (front first)."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    u = _user32()
    out: list[WinInfo] = []

    def visit(hwnd, _lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        pid = w.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        r = w.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        out.append(WinInfo(int(hwnd or 0), pid.value, title.value, cls.value,
                           r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    callback = _LIBS["enum_proc"](visit)
    u.EnumWindows(callback, 0)
    return out


def foreground_pid() -> int:
    """The PID owning the foreground window, 0 when there is none."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    u = _user32()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = w.DWORD(0)
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def bring_to_front(hwnd: int) -> None:
    """Move *hwnd* to the foreground, the way a click on it would."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    if not hwnd:
        return
    u = _user32()
    k = _kernel32()
    fg = u.GetForegroundWindow()
    if fg and int(fg) == hwnd:
        return  # already in front; an Alt tap now would open the window's menu
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    ignored = w.DWORD(0)
    fg_thread = u.GetWindowThreadProcessId(fg, ctypes.byref(ignored)) if fg else 0
    me = k.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and u.AttachThreadInput(me, fg_thread, True))
    u.BringWindowToTop(hwnd)
    u.SetForegroundWindow(hwnd)
    if attached:
        u.AttachThreadInput(me, fg_thread, False)
    now = u.GetForegroundWindow()
    if now and int(now) == hwnd:
        return
    # Last resort: an Alt tap lets this process move another window to the front.
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    u.SetForegroundWindow(hwnd)


def is_hung(hwnd: int) -> bool:
    """Windows' own "Not Responding" test (no messages handled for 5 seconds)."""
    _require()
    return bool(_user32().IsHungAppWindow(hwnd))


def press_keys(vks: list[int], hold_ms: int) -> None:
    """Hold *vks* down together for *hold_ms*, then let go in reverse order.

    Raw key events with scan codes, which games that read the keyboard
    through DirectInput also see."""
    _require()
    u = _user32()
    for vk in vks:
        u.keybd_event(vk, u.MapVirtualKeyW(vk, 0) & 0xFF, 0, 0)
    time.sleep(max(60, hold_ms) / 1000.0)
    for vk in reversed(vks):
        u.keybd_event(vk, u.MapVirtualKeyW(vk, 0) & 0xFF, 2, 0)  # KEYEVENTF_KEYUP


def type_keys(vks: list[int]) -> None:
    """Tap each of *vks* in turn with one ``SendInput`` call: key down and key
    up back to back, as .NET's ``SendKeys`` does.  HyperSpin reacts to keys
    sent this way, not to the held raw events :func:`press_keys` sends games."""
    _require()
    import ctypes
    from ctypes import wintypes as w

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                    ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):  # the union's largest member, for its size
        _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                    ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("u", _U)]

    u = _user32()
    events = (INPUT * (2 * len(vks)))()
    for i, vk in enumerate(vks):
        for j, flags in enumerate((0, 2)):  # down, then KEYEVENTF_KEYUP
            e = events[2 * i + j]
            e.type = 1  # INPUT_KEYBOARD
            e.u.ki.wVk = vk
            e.u.ki.wScan = u.MapVirtualKeyW(vk, 0) & 0xFFFF
            e.u.ki.dwFlags = flags
    send = ctypes.WinDLL("user32", use_last_error=True).SendInput
    send.argtypes = [w.UINT, ctypes.c_void_p, ctypes.c_int]
    send.restype = w.UINT
    send(len(events), ctypes.addressof(events), ctypes.sizeof(INPUT))


def close_window(hwnd: int) -> None:
    """Ask *hwnd* to close (``WM_CLOSE``), as its title bar's X does."""
    _require()
    from ctypes import wintypes as w

    post = _user32().PostMessageW
    post.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    post.restype = w.BOOL
    post(hwnd, 0x0010, 0, 0)


# ─── screen capture ───────────────────────────────────────────────────────────

def _bitmap_header(width: int, height: int):
    import ctypes
    from ctypes import wintypes as w

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
            ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
            ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG),
            ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD),
            ("bmiColors", w.DWORD),  # one RGBQUAD: BITMAPINFO with no colour table
        ]

    hdr = BITMAPINFOHEADER()
    hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER) - 4
    hdr.biWidth = width
    hdr.biHeight = -height  # top-down rows
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    return hdr


def _dib(dc, width: int, height: int):
    """A 32-bit top-down DIB section: ``(bitmap handle, pointer to its pixels)``."""
    import ctypes

    hdr = _bitmap_header(width, height)
    bits = ctypes.c_void_p()
    bmp = _gdi32().CreateDIBSection(dc, ctypes.byref(hdr), 0, ctypes.byref(bits), None, 0)
    if not bmp or not bits.value:
        raise OSError("CreateDIBSection failed")
    return bmp, bits


def _com_call(obj: int, index: int, *args, argtypes=(), restype=None):
    """Call vtable slot *index* of COM object *obj* (an interface pointer)."""
    import ctypes

    vtbl = ctypes.cast(ctypes.c_void_p(obj), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long if restype is None else restype,
                               ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])(obj, *args)


def _com_release(obj) -> None:
    import ctypes

    if obj:
        _com_call(obj, 2, restype=ctypes.c_ulong)


def _dxgi_capture(left: int, top: int) -> tuple[Optional[tuple[int, int, bytes]], str]:
    """What is really on the monitor at (*left*, *top*), through DXGI Desktop
    Duplication: ``((width, height, BGRA pixels), "")`` or ``(None, why)``.

    A GDI screen copy of a full-screen game often returns a frozen frame from
    before the game started drawing; Desktop Duplication sees the real one.
    Windows 8+ only (Windows 7 has no ``IDXGIOutput1``)."""
    import ctypes
    from ctypes import wintypes as w

    vp = ctypes.c_void_p
    out_ptr = ctypes.POINTER(vp)

    def guid(text):
        return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)

    class TexDesc(ctypes.Structure):
        _fields_ = [("Width", w.UINT), ("Height", w.UINT), ("MipLevels", w.UINT),
                    ("ArraySize", w.UINT), ("Format", ctypes.c_int), ("SampleCount", w.UINT),
                    ("SampleQuality", w.UINT), ("Usage", ctypes.c_int), ("BindFlags", w.UINT),
                    ("CPUAccessFlags", w.UINT), ("MiscFlags", w.UINT)]

    class Mapped(ctypes.Structure):
        _fields_ = [("pData", vp), ("RowPitch", w.UINT), ("DepthPitch", w.UINT)]

    try:
        dxgi = ctypes.WinDLL("dxgi")
        d3d = ctypes.WinDLL("d3d11")
    except OSError as exc:
        return None, str(exc)
    dxgi.CreateDXGIFactory1.argtypes = [vp, out_ptr]
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long
    d3d.D3D11CreateDevice.argtypes = [vp, ctypes.c_int, vp, w.UINT, vp, w.UINT, w.UINT,
                                      out_ptr, ctypes.POINTER(ctypes.c_int), out_ptr]
    d3d.D3D11CreateDevice.restype = ctypes.c_long

    iid_factory1 = guid("770aae78-f26f-4dba-a829-253c83d1b387")
    iid_output1 = guid("00cddea8-939b-4b83-a340-a685226666cc")
    iid_texture2d = guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")
    held: list[int] = []  # interfaces to release, in creation order
    frame: list[int] = []  # the frame's resource, texture and staging copy
    dup = None
    acquired = False
    try:
        factory = vp()
        hr = dxgi.CreateDXGIFactory1(ctypes.addressof(iid_factory1), ctypes.byref(factory))
        if hr != 0:
            return None, f"CreateDXGIFactory1 {hr & 0xFFFFFFFF:08X}"
        held.append(factory.value)
        desc = ctypes.create_string_buffer(256)
        adapter = output = None
        a = 0
        while output is None:
            ad = vp()
            if _com_call(factory.value, 12, a, ctypes.byref(ad), argtypes=(w.UINT, out_ptr)) != 0:
                break  # EnumAdapters1: no more adapters
            o = 0
            while True:
                op = vp()
                if _com_call(ad.value, 7, o, ctypes.byref(op), argtypes=(w.UINT, out_ptr)) != 0:
                    break  # EnumOutputs: no more outputs
                _com_call(op.value, 7, ctypes.addressof(desc), argtypes=(vp,))  # GetDesc
                if output is None and struct.unpack_from("<ii", desc.raw, 64) == (left, top):
                    output, adapter = op.value, ad.value
                else:
                    _com_release(op.value)
                o += 1
            if adapter != ad.value:
                _com_release(ad.value)
            a += 1
        if output is None:
            return None, "monitor not found"
        held += [adapter, output]
        device, context, level = vp(), vp(), ctypes.c_int()
        hr = d3d.D3D11CreateDevice(adapter, 0, None, 0x20, None, 0, 7,  # BGRA support, SDK 7
                                   ctypes.byref(device), ctypes.byref(level), ctypes.byref(context))
        if hr != 0:
            return None, f"D3D11CreateDevice {hr & 0xFFFFFFFF:08X}"
        held += [device.value, context.value]
        output1 = vp()
        hr = _com_call(output, 0, ctypes.addressof(iid_output1), ctypes.byref(output1),
                       argtypes=(vp, out_ptr))
        if hr != 0:
            return None, f"IDXGIOutput1 {hr & 0xFFFFFFFF:08X}"
        held.append(output1.value)
        dup_p = vp()
        hr = _com_call(output1.value, 22, device.value, ctypes.byref(dup_p), argtypes=(vp, out_ptr))
        if hr != 0:
            return None, f"DuplicateOutput {hr & 0xFFFFFFFF:08X}"
        dup = dup_p.value
        info = ctypes.create_string_buffer(128)
        res = vp()
        # The first frames can be empty: wait for one with a real present.
        for _i in range(15):
            hr = _com_call(dup, 8, 200, ctypes.addressof(info), ctypes.byref(res),
                           argtypes=(w.UINT, vp, out_ptr))  # AcquireNextFrame
            if hr & 0xFFFFFFFF == 0x887A0027:  # DXGI_ERROR_WAIT_TIMEOUT
                continue
            if hr != 0:
                return None, f"AcquireNextFrame {hr & 0xFFFFFFFF:08X}"
            acquired = True
            if struct.unpack_from("<q", info.raw, 0)[0] != 0:  # LastPresentTime
                break
            _com_release(res.value)
            res = vp()
            _com_call(dup, 14)  # ReleaseFrame
            acquired = False
        if not acquired:
            return None, "no new frame"
        frame.append(res.value)
        tex = vp()
        hr = _com_call(res.value, 0, ctypes.addressof(iid_texture2d), ctypes.byref(tex),
                       argtypes=(vp, out_ptr))
        if hr != 0:
            return None, f"texture {hr & 0xFFFFFFFF:08X}"
        frame.append(tex.value)
        d = TexDesc()
        _com_call(tex.value, 10, ctypes.byref(d), argtypes=(ctypes.POINTER(TexDesc),),
                  restype=ctypes.c_void_p)  # GetDesc returns void
        if d.Format not in (87, 91):  # B8G8R8A8 (UNORM / UNORM_SRGB)
            return None, f"unsupported format {d.Format}"
        d.MipLevels, d.ArraySize, d.SampleCount, d.SampleQuality = 1, 1, 1, 0
        d.Usage, d.BindFlags, d.CPUAccessFlags, d.MiscFlags = 3, 0, 0x20000, 0  # staging, CPU read
        staging = vp()
        hr = _com_call(device.value, 5, ctypes.byref(d), None, ctypes.byref(staging),
                       argtypes=(ctypes.POINTER(TexDesc), vp, out_ptr))  # CreateTexture2D
        if hr != 0:
            return None, f"staging {hr & 0xFFFFFFFF:08X}"
        frame.append(staging.value)
        _com_call(context.value, 47, staging.value, tex.value, argtypes=(vp, vp),
                  restype=ctypes.c_void_p)  # CopyResource
        m = Mapped()
        hr = _com_call(context.value, 14, staging.value, 0, 1, 0, ctypes.byref(m),
                       argtypes=(vp, w.UINT, ctypes.c_int, w.UINT, ctypes.POINTER(Mapped)))  # Map
        if hr != 0:
            return None, f"Map {hr & 0xFFFFFFFF:08X}"
        try:
            row = d.Width * 4
            if m.RowPitch == row:
                pixels = ctypes.string_at(m.pData, row * d.Height)
            else:
                pixels = b"".join(ctypes.string_at(m.pData + y * m.RowPitch, row)
                                  for y in range(d.Height))
        finally:
            _com_call(context.value, 15, staging.value, 0, argtypes=(vp, w.UINT),
                      restype=ctypes.c_void_p)  # Unmap
        return (d.Width, d.Height, pixels), ""
    except (OSError, ValueError) as exc:
        return None, str(exc)
    finally:
        for obj in reversed(frame):
            _com_release(obj)
        if acquired and dup:
            _com_call(dup, 14)  # ReleaseFrame
        if dup:
            _com_release(dup)
        for obj in reversed(held):
            _com_release(obj)


def capture_screen(thumb_width: int) -> Optional[Shot]:
    """The primary monitor now, plus a *thumb_width*-wide thumbnail scaled by
    GDI (HALFTONE).  Desktop Duplication first, a GDI screen copy otherwise;
    ``method`` says which.  None when both fail."""
    _require()
    import ctypes

    make_dpi_aware()
    left, top, width, height = screen_rect()
    try:
        got, why = _dxgi_capture(left, top)
    except Exception as exc:  # noqa: BLE001 - a broken driver must not stop the run
        got, why = None, str(exc)
    method = "desktop duplication" if got else f"screen copy ({why})"
    if got:
        width, height = got[0], got[1]
    if width <= 0 or height <= 0:
        return None
    u, g = _user32(), _gdi32()
    screen = u.GetDC(None)
    if not screen:
        return None
    mem = thumb_dc = None
    bitmaps = []
    try:
        mem = g.CreateCompatibleDC(screen)
        bmp, bits = _dib(screen, width, height)
        bitmaps.append(bmp)
        old = g.SelectObject(mem, bmp)
        size = width * height * 4
        if got:
            ctypes.memmove(bits, got[2], min(size, len(got[2])))
        elif not g.BitBlt(mem, 0, 0, width, height, screen, left, top,
                          0x00CC0020 | 0x40000000):  # SRCCOPY | CAPTUREBLT
            g.SelectObject(mem, old)
            return None
        pixels = ctypes.string_at(bits, size)
        tw = max(1, min(int(thumb_width), width))
        th = max(1, round(tw * height / width))
        thumb_dc = g.CreateCompatibleDC(screen)
        tbmp, tbits = _dib(screen, tw, th)
        bitmaps.append(tbmp)
        told = g.SelectObject(thumb_dc, tbmp)
        g.SetStretchBltMode(thumb_dc, 4)  # HALFTONE
        g.SetBrushOrgEx(thumb_dc, 0, 0, None)
        g.StretchBlt(thumb_dc, 0, 0, tw, th, mem, 0, 0, width, height, 0x00CC0020)
        thumb = ctypes.string_at(tbits, tw * th * 4)
        g.SelectObject(thumb_dc, told)
        g.SelectObject(mem, old)
        return Shot(width, height, pixels, tw, th, thumb, method)
    except OSError:
        return None
    finally:
        for dc in (thumb_dc, mem):
            if dc:
                g.DeleteDC(dc)
        for bmp in bitmaps:
            g.DeleteObject(bmp)
        u.ReleaseDC(None, screen)


# ─── launching ────────────────────────────────────────────────────────────────

def start_process(args: list[str], cwd: str) -> subprocess.Popen:
    """Start a program the way HyperSpin does.  Its standard handles are
    ``NUL``, so a launched emulator never holds on to the GUI's output pipe."""
    _require()
    return subprocess.Popen(args, cwd=cwd, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─── folder watching ──────────────────────────────────────────────────────────

class DirectoryWatcher:
    """Names created anywhere under one folder, from ``ReadDirectoryChangesW``
    on a background thread.

    Only additions are kept (a new file or folder, or the new name of a
    rename); what they mean is the caller's business.  When Windows' buffer
    overflows, events were lost: :meth:`drain` then reports ``overflowed``
    and the caller has to list the folder itself."""

    _ADDED, _RENAMED_NEW = 1, 5

    def __init__(self, root: str):
        import threading

        _require()
        import ctypes
        from ctypes import wintypes as w

        k = _kernel32()
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        k.CreateFileW.restype = w.HANDLE
        k.ReadDirectoryChangesW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.BOOL, w.DWORD,
                                            ctypes.POINTER(w.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        k.ReadDirectoryChangesW.restype = w.BOOL
        k.CancelIoEx.argtypes = [w.HANDLE, ctypes.c_void_p]
        k.CancelIoEx.restype = w.BOOL
        self.root = root
        self._k = k
        self._lock = threading.Lock()
        self._added: set[str] = set()
        self._overflowed = False
        self._stop = False
        # FILE_LIST_DIRECTORY, share everything, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS
        self._handle = k.CreateFileW(root, 0x1, 0x7, None, 3, 0x02000000, None)
        if self._handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        self._thread = threading.Thread(target=self._run, name="spindoctor-watch", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        buf = ctypes.create_string_buffer(64 * 1024)
        got = w.DWORD(0)
        while not self._stop:
            # FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME, whole tree
            ok = self._k.ReadDirectoryChangesW(self._handle, ctypes.addressof(buf), len(buf), True,
                                               0x1 | 0x2, ctypes.byref(got), None, None)
            if self._stop:
                return
            if not ok:
                with self._lock:
                    self._overflowed = True
                return
            if got.value == 0:  # the buffer overflowed: events were lost
                with self._lock:
                    self._overflowed = True
                continue
            raw, offset, found = buf.raw[:got.value], 0, []
            while True:
                nxt, action, length = struct.unpack_from("<III", raw, offset)
                name = raw[offset + 12:offset + 12 + length].decode("utf-16-le", errors="replace")
                if action in (self._ADDED, self._RENAMED_NEW):
                    found.append(name)
                if not nxt:
                    break
                offset += nxt
            with self._lock:
                self._added.update(os.path.join(self.root, n) for n in found)

    def drain(self) -> tuple[set[str], bool]:
        """``(paths added since the last call, whether events were lost)``."""
        with self._lock:
            added, over = self._added, self._overflowed
            self._added, self._overflowed = set(), False
        return added, over

    def close(self) -> None:
        """Stop watching: cancel the thread's blocked read (``CancelSynchronousIo``)."""
        from ctypes import wintypes as w

        self._stop = True
        k = self._k
        k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenThread.restype = w.HANDLE
        k.CancelSynchronousIo.argtypes = [w.HANDLE]
        k.CancelSynchronousIo.restype = w.BOOL
        native = getattr(self._thread, "native_id", None)
        thread = k.OpenThread(0x0001, False, native) if native else None  # THREAD_TERMINATE
        for _attempt in range(20):
            if not self._thread.is_alive():
                break
            if thread:
                k.CancelSynchronousIo(thread)
            k.CancelIoEx(self._handle, None)
            self._thread.join(timeout=0.25)
        if thread:
            k.CloseHandle(thread)
        k.CloseHandle(self._handle)
