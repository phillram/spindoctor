"""Record what the PC plays, through Windows' own WASAPI loopback.

ffmpeg on Windows has no loopback device unless one is installed, so the sound
of a recorded game comes from here: the default playback device opened in
loopback mode, its packets written to a raw file, with silence where nothing
plays.  ``ctypes`` only; Windows 7 and later.  Without it (no sound device, a
device another program holds exclusively) the recording is simply silent.
"""
from __future__ import annotations

import struct
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from ._win32 import _com_call, _com_release

_CLSID_ENUMERATOR = "bcde0395-e52f-467c-8e3d-c4579291692e"
_IID_ENUMERATOR = "a95664d2-9614-4f35-a746-de8db63617e6"
_IID_AUDIO_CLIENT = "1cb9ad4c-dbfa-4c32-b178-c2f568a703b2"
_IID_CAPTURE_CLIENT = "c8adbd64-e71e-48a0-a4de-185c395cd317"

_LOOPBACK = 0x00020000          # AUDCLNT_STREAMFLAGS_LOOPBACK
_SILENT = 0x2                   # AUDCLNT_BUFFERFLAGS_SILENT


class SoundError(OSError):
    """The PC's sound can't be recorded."""


def sample_format(wave: bytes) -> tuple[str, int, int, int]:
    """``(ffmpeg format, rate, channels, bytes per frame)`` from the
    ``WAVEFORMATEX(TENSIBLE)`` in *wave*."""
    tag, channels, rate, _per_second, block, bits = struct.unpack_from("<HHIIHH", wave, 0)
    if tag == 0xFFFE and len(wave) >= 40:  # WAVE_FORMAT_EXTENSIBLE: the real tag starts the sub-format
        tag = struct.unpack_from("<H", wave, 24)[0]
    if tag == 3 and bits == 32:
        name = "f32le"
    elif tag == 1 and bits in (16, 24, 32):
        name = f"s{bits}le"
    else:
        raise SoundError(f"unknown sound format (tag {tag}, {bits} bits)")
    if not rate or not channels or block != channels * bits // 8:
        raise SoundError("the sound format makes no sense")
    return name, rate, channels, block


def missing_frames(elapsed: float, rate: int, written: int) -> int:
    """How many frames of silence to write: none come while nothing plays.
    A quarter of a second of slack, so a late packet isn't counted twice."""
    short = int(elapsed * rate) - written
    return short if short > rate // 4 else 0


class LoopbackRecorder:
    """Writes the PC's sound to *path* from :meth:`start` to :meth:`stop`."""

    def __init__(self, path: Path):
        self.path = path
        self.error = ""
        self.format = ""
        self.rate = 0
        self.channels = 0
        self.frames = 0
        self.started_at: Optional[float] = None     # time.time() of the first frame
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="spindoctor-sound", daemon=True)

    def start(self) -> bool:
        """Whether recording has begun; ``error`` says why not."""
        if sys.platform != "win32":
            self.error = "sound is recorded on Windows only"
            return False
        self._thread.start()
        self._ready.wait(5)
        if not self.error and self.started_at is None:
            self.error = "the sound device didn't answer"
            self._stop.set()
        return not self.error

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        try:
            self._record()
        except Exception as exc:  # noqa: BLE001 - a clip without sound beats no clip
            self.error = self.error or str(exc) or type(exc).__name__
        finally:
            self._ready.set()

    def _record(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        ole32 = ctypes.WinDLL("ole32")
        vp, out_ptr = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)

        def guid(text):
            return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)

        def check(what, hr):
            if hr & 0xFFFFFFFF >= 0x80000000:
                raise SoundError(f"{what} failed ({hr & 0xFFFFFFFF:08X})")

        ole32.CoInitializeEx.argtypes = [vp, w.DWORD]
        ole32.CoCreateInstance.argtypes = [vp, vp, w.DWORD, vp, out_ptr]
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [vp]
        ole32.CoTaskMemFree.restype = None
        hr = ole32.CoInitializeEx(None, 0)  # multithreaded
        initialized = hr in (0, 1)
        held: list[int] = []
        client = None
        try:
            clsid, iid = guid(_CLSID_ENUMERATOR), guid(_IID_ENUMERATOR)
            enumerator = vp()
            check("Opening the sound devices", ole32.CoCreateInstance(
                ctypes.addressof(clsid), None, 0x17, ctypes.addressof(iid), ctypes.byref(enumerator)))
            held.append(enumerator.value)
            device = vp()
            check("Finding the playback device", _com_call(
                enumerator.value, 4, 0, 0, ctypes.byref(device),
                argtypes=(ctypes.c_int, ctypes.c_int, out_ptr)))  # GetDefaultAudioEndpoint
            held.append(device.value)
            iid_client = guid(_IID_AUDIO_CLIENT)
            client_p = vp()
            check("Opening the playback device", _com_call(
                device.value, 3, ctypes.addressof(iid_client), 0x17, None, ctypes.byref(client_p),
                argtypes=(vp, w.DWORD, vp, out_ptr)))  # Activate
            client = client_p.value
            held.append(client)
            mix = vp()
            check("Reading its format", _com_call(client, 8, ctypes.byref(mix), argtypes=(out_ptr,)))
            try:
                extra = struct.unpack("<H", ctypes.string_at(mix.value + 16, 2))[0]
                wave = ctypes.string_at(mix.value, 18 + extra)
                self.format, self.rate, self.channels, block = sample_format(wave)
                check("Recording it", _com_call(
                    client, 3, 0, _LOOPBACK, 10_000_000, 0, mix.value, None,
                    argtypes=(ctypes.c_int, w.DWORD, ctypes.c_longlong, ctypes.c_longlong, vp, vp)))
            finally:
                ole32.CoTaskMemFree(mix.value)
            iid_capture = guid(_IID_CAPTURE_CLIENT)
            capture_p = vp()
            check("Recording it", _com_call(client, 14, ctypes.addressof(iid_capture),
                                            ctypes.byref(capture_p), argtypes=(vp, out_ptr)))
            capture = capture_p.value
            held.append(capture)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "wb") as out:
                check("Starting the recording", _com_call(client, 10))
                begun = time.perf_counter()
                self.started_at = time.time()
                self._ready.set()
                while True:
                    self._drain(capture, out, block, check)
                    gap = missing_frames(time.perf_counter() - begun, self.rate, self.frames)
                    if gap:
                        out.write(bytes(gap * block))
                        self.frames += gap
                    if self._stop.wait(0.01):
                        break
                _com_call(client, 11)  # Stop
        finally:
            for obj in reversed(held):
                _com_release(obj)
            if initialized:
                ole32.CoUninitialize()

    def _drain(self, capture: int, out, block: int, check) -> None:
        import ctypes
        from ctypes import wintypes as w

        size = w.UINT(0)
        check("Reading the sound", _com_call(capture, 5, ctypes.byref(size),
                                             argtypes=(ctypes.POINTER(w.UINT),)))  # GetNextPacketSize
        while size.value:
            data, frames, flags = ctypes.c_void_p(), w.UINT(0), w.DWORD(0)
            check("Reading the sound", _com_call(
                capture, 3, ctypes.byref(data), ctypes.byref(frames), ctypes.byref(flags), None, None,
                argtypes=(ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.UINT),
                          ctypes.POINTER(w.DWORD), ctypes.c_void_p, ctypes.c_void_p)))  # GetBuffer
            length = frames.value * block
            silent = flags.value & _SILENT or not data.value
            out.write(bytes(length) if silent else ctypes.string_at(data.value, length))
            self.frames += frames.value
            _com_call(capture, 4, frames.value, argtypes=(w.UINT,))  # ReleaseBuffer
            check("Reading the sound", _com_call(capture, 5, ctypes.byref(size),
                                                 argtypes=(ctypes.POINTER(w.UINT),)))
