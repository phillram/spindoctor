"""ffmpeg jobs for ``generate-media``: grab the screen, judge a take, make clips.

ffmpeg and ffprobe are found the way downloads find them
(``media._find_ffmpeg``): the ``ffmpeg_path`` setting, PATH, or beside the EXE.
Everything runs on the PC; nothing here opens a network connection.

Every ffmpeg is started without a window: a console window that opens while a
full-screen game runs takes the keyboard away from it.

The clips HyperSpin gets are H.264 Main, yuv420p, about 30 fps, faststart, with
AAC sound.  HyperSpin plays MP3 sound inside an MP4 silent.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config
from .media import _find_ffmpeg

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

CLIP_SIZE = (640, 480)          # the size most HyperSpin videos have; a clip fits inside it
FPS = 30
TAKE_WIDTH = 1280               # a take is recorded no wider than this
MEAN_DB = -20.0                 # the loudness a clip's sound is brought to
PEAK_DB = -1.0
SILENT_DB = -60.0               # quieter than this is no sound at all
PLACEHOLDER_SECONDS = 8

GRAB_METHODS = ("ddagrab", "gdigrab")


class ClipError(RuntimeError):
    """ffmpeg is missing, or a job failed."""


def _even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def fit_size(width: int, height: int, box: tuple[int, int] = CLIP_SIZE) -> tuple[int, int]:
    """*width* x *height* scaled to fit inside *box*, with even sides.  A
    picture within 3% of 4:3 or 16:9 (a crop a few lines off) gets exactly
    that shape, as the wheel's other videos have."""
    if width <= 0 or height <= 0:
        return box
    for shape in (4 / 3, 16 / 9):
        if abs(width / height / shape - 1) <= 0.03:
            width, height = shape, 1.0
            break
    scale = min(box[0] / width, box[1] / height)
    return (min(box[0], max(2, round(width * scale / 2) * 2)),
            min(box[1], max(2, round(height * scale / 2) * 2)))


# ─── what a take looks like ───────────────────────────────────────────────────

@dataclass
class Analysis:
    """What ffmpeg's filters found in a recording."""
    seconds: float = 0.0
    black: float = 0.0              # seconds of black picture
    frozen: float = 0.0             # seconds in which the picture didn't change
    crop: Optional[tuple[int, int, int, int]] = None    # width, height, x, y of the picture
    width: int = 0
    height: int = 0
    mean_db: Optional[float] = None     # None: no sound track
    peak_db: Optional[float] = None
    problem: str = ""               # why it can't be read

    @property
    def is_black(self) -> bool:
        return self.seconds > 0 and self.black >= self.seconds * 0.75

    @property
    def is_frozen(self) -> bool:
        return self.seconds > 0 and self.frozen >= self.seconds * 0.85

    @property
    def has_sound(self) -> bool:
        return self.mean_db is not None and self.mean_db > SILENT_DB

    @property
    def verdict(self) -> str:
        """Why this isn't a usable video, or ""."""
        if self.problem:
            return self.problem
        if self.seconds < 1:
            return "nothing was recorded"
        if self.is_black:
            return "the picture was black"
        if self.is_frozen:
            return "the picture didn't move"
        return ""


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
_SIZE_RE = re.compile(r"Stream #\d+:\d+.*?Video:.*?, (\d{2,5})x(\d{2,5})")
_BLACK_RE = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")
_CHANGE_RE = re.compile(r"\[Parsed_showinfo_\d+ @ [^\]]*\]\s*n:\s*\d+\s+pts:\s*\S+\s+pts_time:([\d.]+)")
FROZEN_AFTER = 2.0          # a picture unchanged this long is standing still
_FREEZE_START_RE = re.compile(r"freeze_start:\s*([\d.]+)")
_FREEZE_END_RE = re.compile(r"freeze_end:\s*([\d.]+)")
_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
_MEAN_RE = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf) dB")
_PEAK_RE = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")


_WHY_RE = re.compile(r"\b(error|fail\w*|denied|unknown|invalid|cannot|can't|couldn't|no such|not found)\b", re.I)


def why_failed(log: str) -> str:
    """The line of an ffmpeg log that says what went wrong: the first
    complaint, since the ones after it only follow from it."""
    lines = [re.sub(r"^\[[^\]]*\]\s*", "", line.strip()) for line in log.splitlines() if line.strip()]
    return next((line for line in lines if _WHY_RE.search(line)), lines[-1] if lines else "")


def _clock(match) -> float:
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def _db(text: str) -> float:
    return -120.0 if text == "-inf" else float(text)


def parse_analysis(text: str) -> Analysis:
    """:class:`Analysis` from the log of :func:`analyse_command`."""
    out = Analysis()
    times = [_clock(m) for m in _TIME_RE.finditer(text)]
    m = _DURATION_RE.search(text)
    out.seconds = max(times + ([_clock(m)] if m else []), default=0.0)
    m = _SIZE_RE.search(text)
    if m:
        out.width, out.height = int(m.group(1)), int(m.group(2))
    out.black = sum(float(b) - float(a) for a, b in _BLACK_RE.findall(text))
    changes = [float(v) for v in _CHANGE_RE.findall(text)]
    if changes:
        out.frozen = frozen_seconds(changes, out.seconds)
        return _rest(out, text)
    events = [(m.start(), "start", float(m.group(1))) for m in _FREEZE_START_RE.finditer(text)]
    events += [(m.start(), "end", float(m.group(1))) for m in _FREEZE_END_RE.finditer(text)]
    began: Optional[float] = None
    for _pos, what, at in sorted(events):
        if what == "start":
            began = at
        elif began is not None:
            out.frozen += max(0.0, at - began)
            began = None
    if began is not None:  # still frozen at the end
        out.frozen += max(0.0, out.seconds - began)
    return _rest(out, text)


def frozen_seconds(changes: list[float], seconds: float, still: float = FROZEN_AFTER) -> float:
    """How long a take of *seconds* stood still: the gaps of at least *still*
    seconds between the moments it changed (*changes*, from the start)."""
    out = 0.0
    last = 0.0
    for at in sorted(changes) + [seconds]:
        if at - last >= still:
            out += at - last
        last = max(last, at)
    return min(out, seconds)


def _rest(out: Analysis, text: str) -> Analysis:
    crops = _CROP_RE.findall(text)
    if crops:
        w, h, x, y = (int(v) for v in crops[-1])
        if plausible_crop(w, h, out.width, out.height):
            out.crop = (w, h, x, y)
    m = _MEAN_RE.search(text)
    if m:
        out.mean_db = _db(m.group(1))
    m = _PEAK_RE.search(text)
    if m:
        out.peak_db = _db(m.group(1))
    return out


def plausible_crop(w: int, h: int, width: int, height: int) -> bool:
    """Whether a *w* x *h* picture inside a *width* x *height* take is the game
    rather than a dark scene that made it look small.  A tall game (a vertical
    arcade game, a handheld's portrait screen) is narrow, and its own edges
    often stay dark (an unlit score), so at least 60% of the height and 5% of
    the width is a real picture; likewise a wide, short one.  Anything else
    under 40% of a side is taken for a dark scene, and the whole frame is kept."""
    if not width or not height or w <= 0 or h <= 0:
        return False
    if w >= width * 0.4 and h >= height * 0.4:
        return True
    return (h >= height * 0.6 and w >= width * 0.05) or (w >= width * 0.6 and h >= height * 0.05)


# The brightest picture of a take, a few frames a second (``lagfun`` with no
# decay keeps each pixel's brightest value): what lit up at any moment.
MAX_FRAME_WIDTH = 480
LIT = 32                    # brighter than this (of 255) is part of the picture
LIT_PIXELS = 2              # a row or column needs this many to count: one stray pixel doesn't


def read_pgm(data: bytes) -> Optional[tuple[int, int, bytes]]:
    """``(width, height, pixels)`` of a binary 8-bit PGM (``P5``), else None."""
    m = re.match(rb"P5\s+(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s+(\d+)\s", data)
    if not m or int(m.group(3)) > 255:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    pixels = data[m.end():m.end() + w * h]
    return (w, h, pixels) if w and h and len(pixels) == w * h else None


def content_box(width: int, height: int, pixels: bytes, lit: int = LIT,
                count: int = LIT_PIXELS) -> Optional[tuple[int, int, int, int]]:
    """``(left, top, right, bottom)`` (right and bottom exclusive) of the rows
    and columns of a grey picture with at least *count* pixels brighter than
    *lit*; None when there are none.  Unlike ffmpeg's ``cropdetect``, which
    judges a row by its average, a score line or a row of LEDs on black counts."""
    rows = [0] * height
    cols = [0] * width
    for y in range(height):
        line = pixels[y * width:(y + 1) * width]
        n = 0
        for x, v in enumerate(line):
            if v > lit:
                cols[x] += 1
                n += 1
        rows[y] = n
    ys = [y for y, n in enumerate(rows) if n >= count]
    xs = [x for x, n in enumerate(cols) if n >= count]
    if not ys or not xs:
        return None
    return xs[0], ys[0], xs[-1] + 1, ys[-1] + 1


def crop_from_max_frame(data: bytes, width: int, height: int) -> Optional[tuple[int, int, int, int]]:
    """The crop (``width, height, x, y`` of the take) that drops the black bars
    around a take whose brightest picture is the PGM *data*; None when it keeps
    everything, when the picture is all black, or when what's lit is too small
    to be the game (see :func:`plausible_crop`)."""
    pgm = read_pgm(data)
    if pgm is None or not width or not height:
        return None
    pw, ph, pixels = pgm
    box = content_box(pw, ph, pixels)
    if box is None:
        return None
    sx, sy = width / pw, height / ph
    # Outward to whole, even take pixels: a small picture's edge pixel stands for a few of the take's.
    left = max(0, int(box[0] * sx) // 2 * 2)
    top = max(0, int(box[1] * sy) // 2 * 2)
    right = min(width, -(-int(-(-box[2] * sx // 1)) // 2) * 2)
    bottom = min(height, -(-int(-(-box[3] * sy // 1)) // 2) * 2)
    w, h = _even(right - left), _even(bottom - top)
    if left + w > width:
        left = max(0, width - w)
    if top + h > height:
        top = max(0, height - h)
    if (w >= width - 8 and h >= height - 8) or not plausible_crop(w, h, width, height):
        return None
    return w, h, left, top


def gain_db(mean: Optional[float], peak: Optional[float]) -> float:
    """How much louder (or quieter) to make the sound: the mean to
    :data:`MEAN_DB`, unless that would push the peak over :data:`PEAK_DB`."""
    if mean is None:
        return 0.0
    gain = MEAN_DB - mean
    if peak is not None:
        gain = min(gain, PEAK_DB - peak)
    return round(max(-30.0, min(30.0, gain)), 1)


def choose_crop(mode: str, a: Analysis) -> Optional[tuple[int, int, int, int]]:
    """The part of a take to keep: ``auto`` drops black bars, ``4:3`` keeps the
    4:3 middle, ``full`` keeps everything."""
    if not a.width or not a.height or mode == "full":
        return None
    if mode == "4:3":
        w = min(a.width, _even(a.height * 4 / 3))
        return None if w == a.width else (w, a.height, _even((a.width - w) / 2), 0)
    if a.crop and (a.crop[0] < a.width - 8 or a.crop[1] < a.height - 8):
        return a.crop
    return None


# ─── command lines (pure, so tests can read them) ─────────────────────────────

def grab_input(method: str, fps: int = FPS) -> list[str]:
    """ffmpeg's input options for the whole primary screen."""
    if method == "ddagrab":
        return ["-f", "lavfi", "-i", f"ddagrab=output_idx=0:framerate={fps}:draw_mouse=0"]
    return ["-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "0", "-i", "desktop"]


def _grab_filters(method: str, region: Optional[tuple[int, int, int, int]]) -> list[str]:
    filters = ["hwdownload", "format=bgra"] if method == "ddagrab" else []
    if region:
        left, top, width, height = region
        filters.append(f"crop={_even(width)}:{_even(height)}:{left}:{top}")
    return filters


def take_command(ffmpeg: str, method: str, out: Path, seconds: float,
                 region: Optional[tuple[int, int, int, int]] = None, fps: int = FPS) -> list[str]:
    """Record the screen (or the *region* ``left, top, width, height`` of it)."""
    filters = _grab_filters(method, region)
    filters += [f"scale='min({TAKE_WIDTH},iw)':-2", "format=yuv420p"]
    return ([ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1"]
            + grab_input(method, fps)
            + ["-t", f"{seconds:g}", "-vf", ",".join(filters), "-an",
               "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "16", str(out)])


# A picture is black when at least this share of it is dark: under about 92
# lit pixels of 1280x720.  ffmpeg's own 0.98 calls a handheld's LCD, LEDs or
# VFD on a black screen black: in a full-screen take they light 0.3-2.5% of
# it, and a pinball's few LEDs 0.03-0.4%.
BLACK_PICTURE = 0.9999


def _blackdetect(seconds: float) -> str:
    return f"blackdetect=d={seconds:g}:pix_th=0.10:pic_th={BLACK_PICTURE:g}"


def probe_command(ffmpeg: str, method: str, seconds: float = 1.5,
                  region: Optional[tuple[int, int, int, int]] = None) -> list[str]:
    """Watch the screen for a moment, keeping nothing: is it black or frozen?"""
    filters = _grab_filters(method, region)
    filters += ["scale=320:-2", "format=yuv420p", _blackdetect(0.2),
                "freezedetect=n=-50dB:d=0.4"]
    return ([ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info"]
            + grab_input(method)
            + ["-t", f"{seconds:g}", "-vf", ",".join(filters), "-an", "-f", "null", "-"])


# When the picture changes: ``mpdecimate`` passes only frames with an 8x8
# block that differs from the last one passed, ``showinfo`` logs their times.
# Unlike ``freezedetect``, which averages the change over the whole frame, a
# small ball or a few LEDs changing on black counts as movement.
CHANGES = "fps=10,mpdecimate=hi=256:lo=128:frac=0.33,showinfo"


def analyse_command(ffmpeg: str, take: Path, max_frame: Optional[Path] = None) -> list[str]:
    """Black, changing and crop findings in the log; with *max_frame*, also
    the take's brightest picture as a grey PGM there (needs ffmpeg's
    ``lagfun``), which :func:`crop_from_max_frame` reads the black bars from."""
    detect = _blackdetect(0.5) + ",cropdetect=limit=24:round=2:reset=0"
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", str(take)]
    graph = f"[0:v]split={3 if max_frame else 2}[d][c]{'[m]' if max_frame else ''};[d]{detect}[dout];[c]{CHANGES}[cout]"
    cmd += ["-filter_complex", graph if max_frame is None else
            graph + f";[m]fps=4,scale={MAX_FRAME_WIDTH}:-2:flags=area,format=gray,lagfun=decay=1[mout]"]
    cmd += ["-map", "[dout]", "-an", "-f", "null", "-", "-map", "[cout]", "-an", "-f", "null", "-"]
    if max_frame is not None:
        cmd += ["-map", "[mout]", "-an", "-update", "1", "-f", "image2", "-y", str(max_frame)]
    return cmd


def volume_command(ffmpeg: str, sound: "SoundFile", skip: float, seconds: float) -> list[str]:
    return ([ffmpeg, "-hide_banner", "-nostdin"] + sound.input_args(skip)
            + ["-t", f"{seconds:g}", "-af", "volumedetect", "-f", "null", "-"])


@dataclass
class SoundFile:
    """Raw sound from :mod:`spindoctor._loopback`."""
    path: Path
    sample_format: str      # ffmpeg's name: f32le, s16le, s24le, s32le
    rate: int
    channels: int

    def input_args(self, skip: float = 0.0) -> list[str]:
        args = ["-ss", f"{skip:.3f}"] if skip > 0 else []
        return args + ["-f", self.sample_format, "-ar", str(self.rate), "-ac", str(self.channels),
                       "-i", str(self.path)]


_VIDEO_OUT = ["-c:v", "libx264", "-profile:v", "main", "-level", "4.0", "-pix_fmt", "yuv420p"]
_SOUND_OUT = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]


def clip_command(ffmpeg: str, take: Path, out: Path, *, crop=None, size: tuple[int, int] = CLIP_SIZE,
                 sound: Optional[SoundFile] = None, sound_skip: float = 0.0, gain: float = 0.0,
                 seconds: Optional[float] = None) -> list[str]:
    """The finished clip from a take and, with *sound*, its sound."""
    filters = []
    if crop:
        filters.append("crop={}:{}:{}:{}".format(*crop))
    filters += [f"scale={size[0]}:{size[1]}:flags=lanczos", "setsar=1", f"fps={FPS}"]
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(take)]
    if sound:
        cmd += sound.input_args(sound_skip)
    cmd += ["-map", "0:v:0"]
    if sound:
        cmd += ["-map", "1:a:0"]
    cmd += ["-vf", ",".join(filters)] + _VIDEO_OUT + [
        "-preset", "medium", "-crf", "21", "-maxrate", "2500k", "-bufsize", "5000k"]
    if sound:
        cmd += ["-af", f"volume={gain:g}dB,aresample=async=1"] + _SOUND_OUT + ["-shortest"]
    if seconds:
        cmd += ["-t", f"{seconds:g}"]
    return cmd + ["-movflags", "+faststart", str(out)]


def still_command(ffmpeg: str, take: Path, out: Path, *, crop=None,
                  size: tuple[int, int] = CLIP_SIZE) -> list[str]:
    """One typical frame of a take as a PNG."""
    filters = ["thumbnail=300"]
    if crop:
        filters.append("crop={}:{}:{}:{}".format(*crop))
    filters.append(f"scale={size[0]}:{size[1]}:flags=lanczos")
    return [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(take),
            "-vf", ",".join(filters), "-frames:v", "1", "-update", "1", str(out)]


def card_clip_command(ffmpeg: str, card: Path, out: Path,
                      seconds: int = PLACEHOLDER_SECONDS) -> list[str]:
    """A still card as an MP4.  No B-frames: with a picture that never changes
    they delay the first frame on old decoders.  A silent sound track, so
    HyperSpin treats it like its other videos."""
    return ([ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
             "-loop", "1", "-framerate", str(FPS), "-i", str(card),
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(seconds)]
            + _VIDEO_OUT + ["-preset", "medium", "-crf", "24", "-bf", "0", "-g", str(FPS)]
            + ["-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", str(out)])


def card_flv_command(ffmpeg: str, card: Path, out: Path, seconds: int = 5) -> list[str]:
    """A still card as the Flash video HyperSpin's own ``No Video.flv`` is."""
    return [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-loop", "1", "-framerate", "25", "-i", str(card), "-t", str(seconds),
            "-c:v", "flv", "-q:v", "3", "-g", "25", "-an", str(out)]


# ─── running ffmpeg ───────────────────────────────────────────────────────────

class Take:
    """A recording in progress."""

    def __init__(self, proc: subprocess.Popen, started: float):
        self.proc = proc
        self.started = started
        self.first_frame: Optional[float] = None    # time.time() of the first recorded frame
        self._errors: list[str] = []
        self._threads = [threading.Thread(target=self._read_progress, daemon=True),
                         threading.Thread(target=self._read_errors, daemon=True)]
        for t in self._threads:
            t.start()

    def _read_progress(self) -> None:
        frames = 0
        for line in self.proc.stdout or ():
            key, _eq, value = line.strip().partition("=")
            if key == "frame" and value.isdigit():
                frames = int(value)
            elif key == "progress" and frames and self.first_frame is None:
                self.first_frame = time.time() - frames / FPS

    def _read_errors(self) -> None:
        for line in self.proc.stderr or ():
            if line.strip():
                self._errors.append(line.strip())
                del self._errors[20:]

    def running(self) -> bool:
        return self.proc.poll() is None

    @property
    def error(self) -> str:
        return why_failed("\n".join(self._errors))

    def finish(self, timeout: float = 20) -> bool:
        """Wait for the recording to be written; False if it had to be ended."""
        try:
            self.proc.wait(timeout=timeout)
            ok = True
        except subprocess.TimeoutExpired:
            self.kill()
            ok = False
        for t in self._threads:
            t.join(timeout=2)
        return ok

    def kill(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


@dataclass
class Tools:
    """ffmpeg on this PC."""
    ffmpeg: str
    ffprobe: str
    _filters: Optional[str] = field(default=None, repr=False)

    def _run(self, cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout,
                                  creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise ClipError(f"ffmpeg took longer than {timeout:g} seconds") from exc
        except OSError as exc:
            raise ClipError(f"Couldn't run ffmpeg ({self.ffmpeg}): {exc}") from exc

    def _make(self, cmd: list[str], out: Path, timeout: float) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        done = self._run(cmd, timeout)
        if done.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            try:
                out.unlink()
            except OSError:
                pass
            raise ClipError(f"ffmpeg couldn't make {out.name}: {why_failed(done.stderr or '') or 'no reason given'}")
        return out

    def methods(self) -> list[str]:
        """The ways this ffmpeg can record the screen, best first."""
        if self._filters is None:
            try:
                self._filters = self._run([self.ffmpeg, "-hide_banner", "-filters"], 20).stdout or ""
            except ClipError:
                self._filters = ""
        return [m for m in GRAB_METHODS if m != "ddagrab" or " ddagrab " in self._filters]

    def probe(self, method: str, region=None) -> Analysis:
        """A moment of the screen through *method*."""
        try:
            done = self._run(probe_command(self.ffmpeg, method, region=region), 20)
        except ClipError as exc:
            return Analysis(problem=str(exc))
        if done.returncode != 0:
            return Analysis(problem=why_failed(done.stderr) or "ffmpeg couldn't record the screen")
        a = parse_analysis(done.stderr)
        a.seconds = a.seconds or 1.5
        return a

    def start_take(self, method: str, out: Path, seconds: float, region=None) -> Take:
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.Popen(
                take_command(self.ffmpeg, method, out, seconds, region), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            raise ClipError(f"Couldn't run ffmpeg ({self.ffmpeg}): {exc}") from exc
        return Take(proc, time.time())

    def analyse(self, take: Path) -> Analysis:
        if not take.is_file() or take.stat().st_size == 0:
            return Analysis(problem="nothing was recorded")
        self.methods()      # reads the filter list once
        max_frame = take.with_name(take.stem + ".max.pgm") if " lagfun " in (self._filters or "") else None
        try:
            done = self._run(analyse_command(self.ffmpeg, take, max_frame), 180)
        except ClipError as exc:
            return Analysis(problem=str(exc))
        a = parse_analysis(done.stderr)
        if max_frame is not None and done.returncode == 0:
            try:
                data = max_frame.read_bytes()
            except OSError:
                data = b""
            if data and a.width and a.height:
                # The brightest picture knows the bars better than cropdetect's averages.
                a.crop = crop_from_max_frame(data, a.width, a.height)
            try:
                max_frame.unlink()
            except OSError:
                pass
        return a

    def volume(self, sound: SoundFile, skip: float, seconds: float) -> tuple[Optional[float], Optional[float]]:
        """``(mean, peak)`` in dB, ``(None, None)`` when it can't be read."""
        try:
            done = self._run(volume_command(self.ffmpeg, sound, skip, seconds), 60)
        except ClipError:
            return None, None
        a = parse_analysis(done.stderr)
        return a.mean_db, a.peak_db

    def make_clip(self, take: Path, out: Path, **kwargs) -> Path:
        return self._make(clip_command(self.ffmpeg, take, out, **kwargs), out, 300)

    def make_still(self, take: Path, out: Path, **kwargs) -> Path:
        return self._make(still_command(self.ffmpeg, take, out, **kwargs), out, 120)

    def make_card_clip(self, card: Path, out: Path) -> Path:
        return self._make(card_clip_command(self.ffmpeg, card, out), out, 60)

    def make_card_flv(self, card: Path, out: Path) -> Path:
        return self._make(card_flv_command(self.ffmpeg, card, out), out, 60)


def find_tools(config: Config) -> Tools:
    """ffmpeg and ffprobe, or :class:`ClipError` saying where to put them."""
    ffmpeg, ffprobe = _find_ffmpeg(getattr(config, "ffmpeg_path", "") or "")
    if not ffmpeg or not ffprobe:
        raise ClipError("ffmpeg not found. Put ffmpeg.exe and ffprobe.exe next to SpinDoctor's EXE, "
                        "or set ffmpeg_path (spindoctor config set ffmpeg_path <path to ffmpeg.exe>).")
    return Tools(ffmpeg, ffprobe)
