"""Full-screen notices for the Toolkit helpers, drawn by Windows itself.

The power helpers (Shut Down Cabinet and the ones built on it) show a
countdown over HyperSpin.  It is a plain Win32 window through ``ctypes``, not
tkinter: the helpers run through either frozen EXE, and the CLI one has no
tkinter.  HyperSpin takes the front back as soon as RocketLauncher closes, so
the window re-asserts topmost and focus every quarter second, and Esc is a
system-wide hotkey while the countdown runs, so HyperSpin never sees it (it
would open its own exit menu).  :func:`note` is the small one-line notice the
quick helpers show at the top of the screen without taking the focus.
Windows only; nothing here runs at import.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from typing import Callable

VK_ESCAPE = 0x1B
_WM_DESTROY = 0x0002
_WM_PAINT = 0x000F
_WM_CLOSE = 0x0010
_WM_SETCURSOR = 0x0020
_WM_KEYDOWN = 0x0100
_WM_HOTKEY = 0x0312
_PM_REMOVE = 0x0001
_HOTKEY_ID = 1
_MOD_NOREPEAT = 0x4000

_api_cache: dict = {}


def _api():
    """user32 / gdi32 / kernel32 with the prototypes this module uses.

    Built once, on first use; raises ``OSError`` off Windows.
    """
    if _api_cache:
        return _api_cache["api"]
    if sys.platform != "win32":
        raise OSError("the Toolkit screen needs Windows")
    import ctypes
    from ctypes import wintypes as w

    lresult = ctypes.c_ssize_t
    wndproc = ctypes.WINFUNCTYPE(lresult, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", wndproc),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE),
            ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
            ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HICON),
        ]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hdc", w.HDC), ("fErase", w.BOOL), ("rcPaint", w.RECT),
            ("fRestore", w.BOOL), ("fIncUpdate", w.BOOL), ("rgbReserved", ctypes.c_byte * 32),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protos = (
        (user32, "RegisterClassExW", [ctypes.POINTER(WNDCLASSEXW)], w.ATOM),
        (user32, "UnregisterClassW", [w.LPCWSTR, w.HINSTANCE], w.BOOL),
        (user32, "CreateWindowExW", [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND,
                                     w.HMENU, w.HINSTANCE, w.LPVOID], w.HWND),
        (user32, "DestroyWindow", [w.HWND], w.BOOL),
        (user32, "DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], lresult),
        (user32, "ShowWindow", [w.HWND, ctypes.c_int], w.BOOL),
        (user32, "IsIconic", [w.HWND], w.BOOL),
        (user32, "SetWindowPos", [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, w.UINT], w.BOOL),
        (user32, "GetForegroundWindow", [], w.HWND),
        (user32, "SetForegroundWindow", [w.HWND], w.BOOL),
        (user32, "BringWindowToTop", [w.HWND], w.BOOL),
        (user32, "GetWindowThreadProcessId", [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
        (user32, "AttachThreadInput", [w.DWORD, w.DWORD, w.BOOL], w.BOOL),
        (user32, "GetSystemMetrics", [ctypes.c_int], ctypes.c_int),
        (user32, "SetProcessDPIAware", [], w.BOOL),
        (user32, "RegisterHotKey", [w.HWND, ctypes.c_int, w.UINT, w.UINT], w.BOOL),
        (user32, "UnregisterHotKey", [w.HWND, ctypes.c_int], w.BOOL),
        (user32, "PeekMessageW", [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT], w.BOOL),
        (user32, "TranslateMessage", [ctypes.POINTER(w.MSG)], w.BOOL),
        (user32, "DispatchMessageW", [ctypes.POINTER(w.MSG)], lresult),
        (user32, "InvalidateRect", [w.HWND, ctypes.POINTER(w.RECT), w.BOOL], w.BOOL),
        (user32, "UpdateWindow", [w.HWND], w.BOOL),
        (user32, "BeginPaint", [w.HWND, ctypes.POINTER(PAINTSTRUCT)], w.HDC),
        (user32, "EndPaint", [w.HWND, ctypes.POINTER(PAINTSTRUCT)], w.BOOL),
        (user32, "GetClientRect", [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
        (user32, "FillRect", [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH], ctypes.c_int),
        (user32, "DrawTextW", [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT],
         ctypes.c_int),
        (user32, "SetCursor", [w.HANDLE], w.HANDLE),
        (gdi32, "CreateFontW", [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
                                w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR], w.HFONT),
        (gdi32, "DeleteObject", [w.HGDIOBJ], w.BOOL),
        (gdi32, "SelectObject", [w.HDC, w.HGDIOBJ], w.HGDIOBJ),
        (gdi32, "GetStockObject", [ctypes.c_int], w.HGDIOBJ),
        (gdi32, "SetTextColor", [w.HDC, w.COLORREF], w.COLORREF),
        (gdi32, "SetBkMode", [w.HDC, ctypes.c_int], ctypes.c_int),
        (gdi32, "CreateSolidBrush", [w.COLORREF], w.HBRUSH),
        (user32, "GetDC", [w.HWND], w.HDC),
        (user32, "ReleaseDC", [w.HWND, w.HDC], ctypes.c_int),
        (kernel32, "GetModuleHandleW", [w.LPCWSTR], w.HMODULE),
        (kernel32, "GetCurrentThreadId", [], w.DWORD),
    )
    fns = {}
    for dll, name, args, res in protos:
        fn = getattr(dll, name)
        fn.argtypes = args
        fn.restype = res
        fns[name] = fn
    api = type("Win32", (), fns)
    api.ctypes, api.w = ctypes, w
    api.WNDPROC, api.WNDCLASSEXW, api.PAINTSTRUCT = wndproc, WNDCLASSEXW, PAINTSTRUCT
    _api_cache["api"] = api
    return api


def bring_to_front(hwnd) -> bool:
    """Make *hwnd* the foreground window, even from a background process.

    Windows only lets the foreground thread hand over the front, so this joins
    that thread's input queue for the moment it takes.
    """
    api = _api()
    if api.GetForegroundWindow() == hwnd:
        return True
    me = api.GetCurrentThreadId()
    fg = api.GetForegroundWindow()
    other = api.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(other and other != me and api.AttachThreadInput(me, other, True))
    try:
        if api.IsIconic(hwnd):
            api.ShowWindow(hwnd, 9)  # SW_RESTORE
        api.BringWindowToTop(hwnd)
        return bool(api.SetForegroundWindow(hwnd))
    finally:
        if attached:
            api.AttachThreadInput(me, other, False)


class Screen:
    """A black window over the whole primary screen, kept on top.

    ``count()`` shows "<verb> in N" with a cancel line and returns False if
    Esc was pressed; ``show()`` replaces the text; ``run()`` runs a function
    in a worker thread while the window stays responsive and on top;
    ``hold()`` just keeps it up.  Always ``close()`` it.
    """

    def __init__(self, title: str = "SpinDoctor") -> None:
        api = self._api = _api()
        try:
            api.SetProcessDPIAware()  # real pixels: sharp text, the window covers the screen
        except OSError:
            pass
        self._big, self._small = "", ""
        self._cancelled = False
        self._hotkey = False
        self._hinst = api.GetModuleHandleW(None)
        self._class = f"SpinDoctorScreen{id(self):x}"
        self._proc = api.WNDPROC(self._wndproc)  # keep a reference for the window's life
        wc = api.WNDCLASSEXW()
        wc.cbSize = api.ctypes.sizeof(wc)
        wc.lpfnWndProc = self._proc
        wc.hInstance = self._hinst
        wc.hbrBackground = api.GetStockObject(4)  # BLACK_BRUSH
        wc.lpszClassName = self._class
        if not api.RegisterClassExW(api.ctypes.byref(wc)):
            raise api.ctypes.WinError(api.ctypes.get_last_error())
        self.width = api.GetSystemMetrics(0)   # SM_CXSCREEN
        self.height = api.GetSystemMetrics(1)  # SM_CYSCREEN
        big_px = max(24, self.height * 7 // 100)
        small_px = max(14, self.height * 37 // 1000)
        # CreateFontW(height, …, weight, …, charset, …, quality, pitch, face)
        self._fonts = (
            api.CreateFontW(-big_px, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI Semibold"),
            api.CreateFontW(-small_px, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"),
        )
        self._big_px, self._small_px = big_px, small_px
        self.hwnd = api.CreateWindowExW(
            0x00000008 | 0x00000080,   # WS_EX_TOPMOST | WS_EX_TOOLWINDOW (no taskbar button)
            self._class, title, 0x80000000 | 0x10000000,  # WS_POPUP | WS_VISIBLE
            0, 0, self.width, self.height, None, None, self._hinst, None,
        )
        if not self.hwnd:
            err = api.ctypes.get_last_error()
            self._release()
            raise api.ctypes.WinError(err)
        self._last_front = 0.0
        self._keep_on_top(force=True)

    # ── public ────────────────────────────────────────────────────────────

    def count(self, verb: str, seconds: int, cancel_text: str = "Press Esc to cancel") -> bool:
        """Count down from *seconds*; False when Esc (or Alt+F4) cancels it."""
        api = self._api
        self._cancelled = False
        self._hotkey = bool(api.RegisterHotKey(self.hwnd, _HOTKEY_ID, _MOD_NOREPEAT, VK_ESCAPE))
        try:
            end = time.monotonic() + seconds
            while True:
                left = math.ceil(end - time.monotonic())
                if left <= 0:
                    return True
                self.show(f"{verb} in {left}", cancel_text)
                self._pump(min(0.25, max(0.01, end - time.monotonic())))
                if self._cancelled:
                    return False
        finally:
            if self._hotkey:
                api.UnregisterHotKey(self.hwnd, _HOTKEY_ID)
                self._hotkey = False

    def show(self, big: str, small: str = "") -> None:
        if (big, small) != (self._big, self._small):
            self._big, self._small = big, small
            self._api.InvalidateRect(self.hwnd, None, True)
            self._api.UpdateWindow(self.hwnd)

    def run(self, fn: Callable[[], object]):
        """``fn()`` in a worker thread, the window kept up meanwhile; its result."""
        box: dict = {}

        def work() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 — re-raised below, on this thread
                box["error"] = exc

        worker = threading.Thread(target=work, name="toolkit-screen-work", daemon=True)
        worker.start()
        while worker.is_alive():
            self._pump(0.1)
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def hold(self, seconds: float) -> None:
        self._pump(seconds)

    def close(self) -> None:
        if self.hwnd:
            self._api.DestroyWindow(self.hwnd)
            self.hwnd = None
            self._pump(0)
        self._release()

    # ── internals ─────────────────────────────────────────────────────────

    def _release(self) -> None:
        api = self._api
        for font in getattr(self, "_fonts", ()):
            if font:
                api.DeleteObject(font)
        self._fonts = ()
        if self._class:
            api.UnregisterClassW(self._class, self._hinst)
            self._class = ""

    def _pump(self, seconds: float) -> None:
        """Handle window messages for *seconds*, re-asserting the front."""
        api = self._api
        msg = api.w.MSG()
        end = time.monotonic() + seconds
        while True:
            while api.PeekMessageW(api.ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
                if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self._cancelled = True
                    continue
                api.TranslateMessage(api.ctypes.byref(msg))
                api.DispatchMessageW(api.ctypes.byref(msg))
            if self.hwnd:
                self._keep_on_top()
            if time.monotonic() >= end:
                return
            time.sleep(0.02)

    def _keep_on_top(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_front < 0.25:
            return
        self._last_front = now
        api = self._api
        # HWND_TOPMOST, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        api.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)
        if api.GetForegroundWindow() != self.hwnd:
            bring_to_front(self.hwnd)

    def _wndproc(self, hwnd, message, wparam, lparam):
        api = self._api
        try:
            if message == _WM_PAINT:
                self._paint(hwnd)
                return 0
            if message == _WM_SETCURSOR:
                api.SetCursor(None)  # no mouse pointer over the screen
                return 1
            if message == _WM_KEYDOWN and wparam == VK_ESCAPE:
                self._cancelled = True  # when the hotkey couldn't be registered
                return 0
            if message == _WM_CLOSE:
                self._cancelled = True  # Alt+F4 cancels too; close() destroys it
                return 0
        except Exception:  # noqa: BLE001 — never let an error escape into Windows
            pass
        return api.DefWindowProcW(hwnd, message, wparam, lparam)

    def _paint(self, hwnd) -> None:
        api = self._api
        ctypes, w = api.ctypes, api.w
        ps = api.PAINTSTRUCT()
        hdc = api.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            rect = w.RECT()
            api.GetClientRect(hwnd, ctypes.byref(rect))
            api.FillRect(hdc, ctypes.byref(rect), api.GetStockObject(4))
            api.SetBkMode(hdc, 1)  # TRANSPARENT
            mid = rect.bottom // 2
            flags = 0x1 | 0x4 | 0x20 | 0x800  # DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX
            old = api.SelectObject(hdc, self._fonts[0])
            api.SetTextColor(hdc, 0xFFFFFF)
            top = w.RECT(0, mid - self._big_px * 3 // 2, rect.right, mid)
            api.DrawTextW(hdc, self._big, -1, ctypes.byref(top), flags)
            if self._small:
                api.SelectObject(hdc, self._fonts[1])
                api.SetTextColor(hdc, 0xA0A0A0)
                low = w.RECT(0, mid + self._small_px // 2, rect.right, mid + self._small_px * 2)
                api.DrawTextW(hdc, self._small, -1, ctypes.byref(low), flags)
            api.SelectObject(hdc, old)
        finally:
            api.EndPaint(hwnd, ctypes.byref(ps))


def note(text: str, seconds: float = 3.0) -> None:
    """Show *text* in a small box at the top of the screen for *seconds*.

    The box never takes the focus and lets clicks through, so HyperSpin keeps
    the keyboard and its music; it just stays on top while it's shown.
    """
    api = _api()
    ctypes, w = api.ctypes, api.w
    try:
        api.SetProcessDPIAware()
    except OSError:
        pass
    height = api.GetSystemMetrics(1)
    font = api.CreateFontW(-max(16, height * 4 // 100), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0,
                           "Segoe UI Semibold")
    brush = api.CreateSolidBrush(0x1A1A1A)
    hinst = api.GetModuleHandleW(None)
    cls = f"SpinDoctorNote{id(text):x}{int(time.monotonic() * 1000) & 0xFFFF:x}"

    def wndproc(hwnd, message, wparam, lparam):
        try:
            if message == _WM_PAINT:
                ps = api.PAINTSTRUCT()
                hdc = api.BeginPaint(hwnd, ctypes.byref(ps))
                try:
                    rect = w.RECT()
                    api.GetClientRect(hwnd, ctypes.byref(rect))
                    api.FillRect(hdc, ctypes.byref(rect), brush)
                    api.SetBkMode(hdc, 1)  # TRANSPARENT
                    old = api.SelectObject(hdc, font)
                    api.SetTextColor(hdc, 0xFFFFFF)
                    api.DrawTextW(hdc, text, -1, ctypes.byref(rect), 0x1 | 0x4 | 0x20 | 0x800)
                    api.SelectObject(hdc, old)
                finally:
                    api.EndPaint(hwnd, ctypes.byref(ps))
                return 0
        except Exception:  # noqa: BLE001 — never let an error escape into Windows
            pass
        return api.DefWindowProcW(hwnd, message, wparam, lparam)

    proc = api.WNDPROC(wndproc)
    wc = api.WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(wc)
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.lpszClassName = cls
    hwnd = None
    try:
        if not api.RegisterClassExW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Size the box to the text: measure it with the font on the screen's DC.
        dc = api.GetDC(None)
        old = api.SelectObject(dc, font)
        size = w.RECT()
        api.DrawTextW(dc, text, -1, ctypes.byref(size), 0x400 | 0x20 | 0x800)  # DT_CALCRECT
        api.SelectObject(dc, old)
        api.ReleaseDC(None, dc)
        pad_x, pad_y = max(20, height * 37 // 1000), max(10, height * 18 // 1000)
        box_w, box_h = size.right + 2 * pad_x, size.bottom + 2 * pad_y
        x = (api.GetSystemMetrics(0) - box_w) // 2
        y = height * 74 // 1000
        # WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        hwnd = api.CreateWindowExW(0x8 | 0x80 | 0x08000000 | 0x20, cls, "SpinDoctor", 0x80000000,
                                   x, y, box_w, box_h, None, None, hinst, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        api.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        msg = w.MSG()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            # HWND_TOPMOST, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            api.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x2 | 0x1 | 0x10)
            stop = min(end, time.monotonic() + 0.25)
            while time.monotonic() < stop:
                while api.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
                    api.TranslateMessage(ctypes.byref(msg))
                    api.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.02)
    finally:
        if hwnd:
            api.DestroyWindow(hwnd)
        api.UnregisterClassW(cls, hinst)
        api.DeleteObject(font)
        api.DeleteObject(brush)
