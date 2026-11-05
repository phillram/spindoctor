"""Intro Video pool — manage the videos HyperSpin plays on boot, and the
Windows logon task that swaps between them.

The pool folder (``config.intro_randomizer_dir``) *is* the database: every
video file directly inside it is "enabled" (eligible to be picked); a
``Disabled\\`` subfolder (created on demand) holds videos taken out of
rotation by ``remove`` — nothing is ever deleted, and ``restore`` moves a
file back. There is no separate list file to keep in sync with what's
actually on disk.

``swap_video`` performs the actual boot-video swap: a live scan of the pool
root, a uniform random pick, and a copy over ``config.intro_video_target``
(the file HyperSpin itself reads, e.g. ``Intro.mp4``). It's re-randomized
on every call — no persisted order to shuffle or go stale.

``install_autorun``/``uninstall_autorun`` register (or remove) a Windows
Task Scheduler logon task that runs ``spindoctor introvideo swap --apply``
automatically, via :mod:`spindoctor.autostart` — the same ``schtasks.exe``
wrapper already used by the GUI's wheel-refresh auto-run feature. This has
no dependency on HyperSpin, RocketLauncher, or HyperHQ: the swap is a plain
file copy, and Task Scheduler is a plain Windows mechanism, so it can be
wired up (and torn down) without touching any cabinet-specific config.

Earlier versions of this module read/wrote a third-party ``Random.ini``
(the file format a 2015 forum tool called "Randomizer" used, wired into
HyperHQ's Startup/Exit tab). That's gone — this module no longer reads or
writes ``Random.ini`` at all.
"""
from __future__ import annotations

import math
import os
import random
import shutil
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import autostart
from .config import Config

DISABLED_SUBFOLDER = "Disabled"
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".avi", ".wmv", ".mkv", ".mov", ".m4v", ".flv",
})

#: Windows Task Scheduler task name for the logon-triggered swap. Distinct
#: from autostart.DEFAULT_LOGON_TASK (the wheel-refresh task) so the two
#: features can be enabled/disabled independently.
AUTORUN_TASK_NAME = "SpinDoctor Intro Swap"
SWAP_BAT_FILENAME = "spindoctor-intro-swap.bat"

#: Retry window for copying over intro_video_target while it's locked —
#: expected at boot, since HyperSpin itself may still be holding the file
#: open playing the *previous* intro video at the exact moment the
#: logon-triggered swap runs. Confirmed on a real cabinet: the lock is held
#: for the clip's *entire* playback (a PermissionError reproduces on demand
#: by running `swap` while an intro is actively playing, and succeeds
#: immediately once it finishes) — not just a brief moment. Clips there run
#: from 2 seconds to 4.5 minutes, so no fixed window fits every pool: the
#: swap waits for the clip in the target to finish (its length plus
#: SWAP_RETRY_MARGIN_SECONDS, at most SWAP_RETRY_MAX_SECONDS; see
#: swap_retry_attempts), and never less than these 90 attempts x 2 s
#: = 3 minutes, which is also the window when the length can't be read.
SWAP_RETRY_ATTEMPTS = 90
SWAP_RETRY_DELAY_SECONDS = 2.0
#: Slack on top of the clip's length: HyperSpin starts the intro a few
#: seconds after it opens, and the swap can start before HyperSpin does.
SWAP_RETRY_MARGIN_SECONDS = 60.0
#: Upper bound, so a mislabelled hour-long file can't hold the logon task
#: for an hour. ``doctor`` warns about clips longer than this.
SWAP_RETRY_MAX_SECONDS = 30 * 60.0

#: Containers whose length :func:`video_duration_seconds` can read (ISO base
#: media / QuickTime: the movie header, ``mvhd``).
DURATION_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov"})


class IntroVideoError(Exception):
    """intro_randomizer_dir / intro_video_target unset, or a source file is missing."""


@dataclass
class VideoStatus:
    filename: str
    enabled: bool  # True = pool root ("in rotation"), False = Disabled\
    size_bytes: int


@dataclass
class AddResult:
    dest: Path
    copied: bool
    already_present: bool


@dataclass
class RemoveResult:
    filename: str
    moved: bool
    reason: Optional[str] = None  # "not_found" | "conflict" (set iff not moved)


@dataclass
class RestoreResult:
    filename: str
    moved: bool
    reason: Optional[str] = None  # "not_found" | "conflict" (set iff not moved)


@dataclass
class SwapResult:
    picked: Optional[str]  # None iff the pool is empty
    target: Path
    pool_size: int


@dataclass
class AutorunResult:
    bat_path: Path
    vbs_path: Path
    task_name: str
    registered: bool
    output: str = ""


@dataclass
class AutorunStatus:
    registered: bool
    stale: bool = False  # registered, but the .bat no longer references
                          # the currently-running spindoctor.exe (or the
                          # .bat is simply missing) — re-running
                          # install_autorun fixes it. Always False when
                          # not registered, or on a non-frozen install
                          # (nothing version-specific to go stale there).


def _pool_dir(config: Config) -> Path:
    if not config.intro_randomizer_dir:
        raise IntroVideoError(
            "intro_randomizer_dir is not set — configure the folder holding "
            "your intro videos via the Setup tab or "
            "`spindoctor config set intro_randomizer_dir <path>`."
        )
    return Path(config.intro_randomizer_dir)


def _target_file(config: Config) -> Path:
    if not config.intro_video_target:
        raise IntroVideoError(
            "intro_video_target is not set — configure the full path to the "
            "video HyperSpin plays on boot via the Setup tab or "
            "`spindoctor config set intro_video_target <path>`."
        )
    return Path(config.intro_video_target)


def _disabled_dir(pool: Path) -> Path:
    return pool / DISABLED_SUBFOLDER


def _list_dir_videos(d: Path) -> "dict[str, int]":
    """{filename (on-disk casing): size_bytes} — non-recursive, video exts only."""
    out: "dict[str, int]" = {}
    if not d.exists():
        return out
    for p in d.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            out[p.name] = p.stat().st_size
    return out


def _find_case_insensitive(d: Path, filename: str) -> Optional[Path]:
    if not d.exists():
        return None
    target = filename.lower()
    for p in d.iterdir():
        if p.is_file() and p.name.lower() == target:
            return p
    return None


# ── clip length ───────────────────────────────────────────────────────────────

def _find_box(fh, start: int, end: int, kind: bytes) -> "Optional[tuple[int, int]]":
    """``(payload start, box end)`` of the first *kind* box in ``[start, end)``.

    Walks one level of ISO base media boxes by their sizes, so a large
    ``mdat`` before the ``moov`` box is skipped with a seek, not read.
    """
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        head = fh.read(8)
        if len(head) < 8:
            return None
        size, box = struct.unpack(">I4s", head)
        header = 8
        if size == 1:                      # 64-bit size follows
            big = fh.read(8)
            if len(big) < 8:
                return None
            size = struct.unpack(">Q", big)[0]
            header = 16
        elif size == 0:                    # runs to the end of its parent
            size = end - pos
        if size < header:
            return None
        if box == kind:
            return pos + header, min(pos + size, end)
        pos += size
    return None


def video_duration_seconds(path: Path) -> Optional[float]:
    """Length of an MP4 / M4V / MOV file from its movie header, or ``None``.

    Pure Python, reading a few header bytes (no ffprobe). ``None`` for other
    containers, a file that can't be read (it may be locked), or one with no
    usable ``mvhd`` box.
    """
    if Path(path).suffix.lower() not in DURATION_EXTENSIONS:
        return None
    try:
        with open(path, "rb") as fh:
            end = os.fstat(fh.fileno()).st_size
            moov = _find_box(fh, 0, end, b"moov")
            mvhd = _find_box(fh, moov[0], moov[1], b"mvhd") if moov else None
            if mvhd is None:
                return None
            fh.seek(mvhd[0])
            head = fh.read(32)
            if len(head) >= 32 and head[0] == 1:
                timescale, duration = struct.unpack(">IQ", head[20:32])
                unknown = duration == 0xFFFFFFFFFFFFFFFF
            elif len(head) >= 20 and head[0] == 0:
                timescale, duration = struct.unpack(">II", head[12:20])
                unknown = duration == 0xFFFFFFFF
            else:
                return None
    except (OSError, struct.error):
        return None
    if not timescale or unknown:
        return None
    return duration / timescale


def swap_retry_attempts(target: Path, pool: Optional[Path] = None) -> int:
    """How many times :func:`swap_video` tries the copy before giving up.

    Enough to outlast the clip in *target* (the one HyperSpin may be playing,
    holding the file open): its length plus :data:`SWAP_RETRY_MARGIN_SECONDS`,
    capped at :data:`SWAP_RETRY_MAX_SECONDS`, and never fewer than
    :data:`SWAP_RETRY_ATTEMPTS`. If the target can't be read (HyperSpin's
    lock may block reading too), the longest clip in *pool* stands in for
    it, enabled or disabled, since the target is always a copy of one of
    them. With no length at all, it's :data:`SWAP_RETRY_ATTEMPTS`.
    """
    attempts = SWAP_RETRY_ATTEMPTS
    length = video_duration_seconds(target)
    if length is None and pool is not None:
        lengths = [video_duration_seconds(d / name)
                   for d in (pool, _disabled_dir(pool)) for name in _list_dir_videos(d)]
        length = max((s for s in lengths if s is not None), default=None)
    if length is not None and SWAP_RETRY_DELAY_SECONDS > 0:
        window = min(length + SWAP_RETRY_MARGIN_SECONDS, SWAP_RETRY_MAX_SECONDS)
        attempts = max(attempts, int(math.ceil(window / SWAP_RETRY_DELAY_SECONDS)))
    return attempts


@dataclass
class ClipLengths:
    """Lengths of the enabled pool videos, for ``doctor``."""
    longest: Optional[str] = None        # file name of the longest readable clip
    longest_seconds: float = 0.0
    #: Clips the swap can't wait out (length + margin over SWAP_RETRY_MAX_SECONDS).
    too_long: "list[tuple[str, float]]" = field(default_factory=list)
    #: Enabled videos whose length can't be read (the swap waits 3 minutes).
    unreadable: "list[str]" = field(default_factory=list)


def pool_clip_lengths(config: Config) -> ClipLengths:
    """Read the length of every enabled pool video (headers only)."""
    pool = _pool_dir(config)
    out = ClipLengths()
    for name in sorted(_list_dir_videos(pool), key=str.lower):
        seconds = video_duration_seconds(pool / name)
        if seconds is None:
            out.unreadable.append(name)
            continue
        if seconds > out.longest_seconds:
            out.longest, out.longest_seconds = name, seconds
        if seconds + SWAP_RETRY_MARGIN_SECONDS > SWAP_RETRY_MAX_SECONDS:
            out.too_long.append((name, seconds))
    return out


# ── pool management ──────────────────────────────────────────────────────────

def list_videos(config: Config) -> "list[VideoStatus]":
    """Every enabled (pool root) and disabled (``Disabled\\``) video, sorted by name."""
    pool = _pool_dir(config)
    enabled = _list_dir_videos(pool)
    disabled = _list_dir_videos(_disabled_dir(pool))
    out = [VideoStatus(filename=n, enabled=True, size_bytes=s) for n, s in enabled.items()]
    out += [VideoStatus(filename=n, enabled=False, size_bytes=s) for n, s in disabled.items()]
    out.sort(key=lambda v: v.filename.lower())
    return out


def add_videos(
    config: Config, sources: "list[Path]", *, apply: bool = False,
) -> "list[AddResult]":
    """Copy each of *sources* into the pool root. Never overwrites an existing file.

    Every source is validated up front — before any copy happens — so a
    missing file anywhere in the batch aborts cleanly with nothing copied,
    rather than leaving earlier files in the batch copied but the rest
    silently skipped.
    """
    pool = _pool_dir(config)
    for source in sources:
        if not source.exists() or not source.is_file():
            raise IntroVideoError(f"Source video not found: {source}")

    results = []
    for source in sources:
        existing = _find_case_insensitive(pool, source.name)
        already_present = existing is not None
        dest = existing if existing is not None else pool / source.name
        copied = False
        if apply:
            if not already_present:
                pool.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                copied = True
        else:
            copied = not already_present
        results.append(AddResult(dest=dest, copied=copied, already_present=already_present))
    return results


def add_video(config: Config, source: Path, *, apply: bool = False) -> AddResult:
    return add_videos(config, [source], apply=apply)[0]


def remove_videos(
    config: Config, filenames: "list[str]", *, apply: bool = False,
) -> "list[RemoveResult]":
    """Move each named, currently-enabled video into ``Disabled\\``.

    The video file is never deleted — ``restore`` moves it back later.
    """
    pool = _pool_dir(config)
    disabled = _disabled_dir(pool)
    results = []
    for filename in filenames:
        match = _find_case_insensitive(pool, filename)
        if match is None:
            results.append(RemoveResult(filename=filename, moved=False, reason="not_found"))
            continue
        dest = disabled / match.name
        if _find_case_insensitive(disabled, match.name) is not None:
            results.append(RemoveResult(filename=filename, moved=False, reason="conflict"))
            continue
        if apply:
            disabled.mkdir(parents=True, exist_ok=True)
            shutil.move(str(match), str(dest))
        results.append(RemoveResult(filename=filename, moved=True))
    return results


def remove_video(config: Config, filename: str, *, apply: bool = False) -> RemoveResult:
    return remove_videos(config, [filename], apply=apply)[0]


def restore_videos(
    config: Config, filenames: "list[str]", *, apply: bool = False,
) -> "list[RestoreResult]":
    """Move each named, currently-disabled video back to the pool root."""
    pool = _pool_dir(config)
    disabled = _disabled_dir(pool)
    results = []
    for filename in filenames:
        match = _find_case_insensitive(disabled, filename)
        if match is None:
            results.append(RestoreResult(filename=filename, moved=False, reason="not_found"))
            continue
        dest = pool / match.name
        if _find_case_insensitive(pool, match.name) is not None:
            results.append(RestoreResult(filename=filename, moved=False, reason="conflict"))
            continue
        if apply:
            pool.mkdir(parents=True, exist_ok=True)
            shutil.move(str(match), str(dest))
        results.append(RestoreResult(filename=filename, moved=True))
    return results


def restore_video(config: Config, filename: str, *, apply: bool = False) -> RestoreResult:
    return restore_videos(config, [filename], apply=apply)[0]


# ── the swap itself ──────────────────────────────────────────────────────────

def swap_video(
    config: Config, *, apply: bool = False, rng: "Optional[random.Random]" = None,
) -> SwapResult:
    """Pick a random enabled video and copy it over ``intro_video_target``.

    A live directory scan every call — no persisted order, nothing to go
    stale. An empty pool is a clean no-op (never raises): this is the
    function the unattended logon task calls, and it must run reliably
    unattended. *rng* lets callers (tests) pass a seeded ``random.Random``
    instead of the module-level RNG.

    The copy is retried, :data:`SWAP_RETRY_DELAY_SECONDS` apart, while the
    target file is locked — expected at boot, since HyperSpin itself may
    still be holding ``intro_video_target`` open playing the *previous*
    intro video at the exact moment the logon-triggered swap runs, for the
    clip's whole length. :func:`swap_retry_attempts` sizes the window from
    that clip's length (3 minutes at least). Raises
    :class:`IntroVideoError` (not the raw ``OSError``) if every attempt
    fails, so the CLI reports it clearly and — once wired through the
    logon task's bat/vbs — Task Scheduler's Last Result reflects the
    real failure instead of silently reporting success.
    """
    pool = _pool_dir(config)
    target = _target_file(config)
    candidates = sorted(_list_dir_videos(pool).keys())
    if not candidates:
        return SwapResult(picked=None, target=target, pool_size=0)
    picker = rng if rng is not None else random
    picked = picker.choice(candidates)
    if apply:
        attempts = swap_retry_attempts(target, pool)
        last_exc: Optional[OSError] = None
        for attempt in range(attempts):
            try:
                shutil.copy2(pool / picked, target)
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    time.sleep(SWAP_RETRY_DELAY_SECONDS)
        if last_exc is not None:
            raise IntroVideoError(
                f"Could not copy {picked!r} over {target} after "
                f"{attempts} attempts, {SWAP_RETRY_DELAY_SECONDS}s "
                f"apart — still in use? ({last_exc})"
            ) from last_exc
    return SwapResult(picked=picked, target=target, pool_size=len(candidates))


# ── Windows logon auto-run ───────────────────────────────────────────────────

def _sibling_spindoctor_exe() -> str:
    """Resolve the `spindoctor` executable, frozen or dev install.

    Mirrors gui.py's `_write_refresh_bat` branching so both auto-run
    features resolve executables the same way.
    """
    if getattr(sys, "frozen", False):
        sibling = Path(sys.executable).parent / "spindoctor.exe"
        if sibling.exists():
            return f'"{sibling}"'
    return "spindoctor"


def _swap_bat_dir() -> Path:
    """Directory the swap bat/vbs live in — always ``~/.spindoctor/``, the
    same stable location ``config.json`` already uses, regardless of
    frozen/source install. NOT next to the frozen exe: portable Windows
    installs unzip each release into its own version-numbered folder
    (e.g. ``spindoctor-win10-v2.11.0\\``), so a bat/vbs pair stored there
    gets silently orphaned the next time the cabinet owner upgrades into
    a new folder — the registered Task Scheduler entry would keep
    pointing at a script that may no longer exist. Writing here instead
    means the Task Scheduler task's target path never needs to change
    across upgrades; only its *contents* (which reference the
    per-version ``spindoctor.exe`` on a frozen install, via
    :func:`_sibling_spindoctor_exe`) need a refresh — re-run
    ``introvideo install-autorun --apply`` once after upgrading. Does NOT
    create the directory; only :func:`_write_swap_bat` does that, so
    computing a preview path (dry-run) never touches disk.
    """
    return Path.home() / ".spindoctor"


def _swap_bat_path() -> Path:
    return _swap_bat_dir() / SWAP_BAT_FILENAME


def _write_swap_bat() -> Path:
    """Write the .bat the logon task runs — `introvideo swap --apply`, then
    an explicit ``exit /b`` so the bat's own process exit code reliably
    reflects whether the swap succeeded (cmd.exe does not propagate a
    batch's last errorlevel as its own exit code unless told to)."""
    exe = _sibling_spindoctor_exe()
    lines = (
        "@echo off\r\n"
        f'start /LOW /B /WAIT "" {exe} introvideo swap --apply\r\n'
        "exit /b %errorlevel%\r\n"
    )
    bat_dir = _swap_bat_dir()
    bat_dir.mkdir(parents=True, exist_ok=True)
    bat_path = bat_dir / SWAP_BAT_FILENAME
    bat_path.write_text(lines, encoding="utf-8")
    return bat_path


def _write_swap_vbs(bat_path: Path) -> Path:
    """Hidden-window shim so the logon task never flashes a console window.

    Embeds *bat_path*'s full, already-known absolute path directly, rather
    than having the VBS re-derive its own folder at runtime from
    ``WScript.ScriptFullName`` (the previous approach). That runtime
    derivation had a real, confirmed-on-a-real-cabinet bug: the Python
    string literal building the VBS's `InStrRev` search argument had one
    backslash too many, so instead of searching for a single backslash
    (a normal Windows path separator), the generated VBS searched for
    two consecutive backslashes — which a normal path never contains.
    That search always returned "not found", so `Left(path, 0)` always
    returned an empty string, and the computed bat path silently
    collapsed to a bare filename with no folder at all. A bare relative
    filename resolves against the *caller's* working directory: Explorer
    sets that to the double-clicked file's own folder (so manual
    double-click testing always "worked"), but Task Scheduler does not
    use that folder as an action's working directory — so the exact same
    command silently failed to even find the .bat, every single time, at
    any delay. No error, nothing in Task Scheduler history, no log file,
    nothing — every symptom this bug produced. Embedding the full path
    here removes the dependency on the caller's working directory
    entirely, and with it this whole class of bug (there's no runtime
    path derivation left to get subtly wrong).

    Captures ``ws.Run``'s return value and exits with it via
    ``WScript.Quit`` — without this, wscript.exe always exits 0 regardless
    of whether the bat (and thus the swap) actually succeeded, which is
    exactly what made Task Scheduler's "Last Result" untrustworthy for
    diagnosing a real swap failure. Otherwise the same shape as gui.py's
    `_write_vbs_shim` for the wheel-refresh task (which has the same gap,
    not fixed here — out of scope for the intro-video swap).
    """
    vbs_content = (
        "' SpinDoctor intro-swap hidden launcher\r\n"
        "' Generated by spindoctor introvideo install-autorun — do not edit.\r\n"
        'Set ws = CreateObject("WScript.Shell")\r\n'
        f'rc = ws.Run(Chr(34) & "{bat_path}" & Chr(34), 0, True)\r\n'
        "WScript.Quit(rc)\r\n"
    )
    vbs_path = bat_path.with_suffix(".vbs")
    vbs_path.write_text(vbs_content, encoding="utf-8")
    return vbs_path


def _autorun_command(vbs_path: Path) -> str:
    return f'wscript.exe //B "{vbs_path}"'


def install_autorun(
    config: Config, *, apply: bool = False, delay_minutes: Optional[int] = None,
) -> AutorunResult:
    """Register a Windows logon task that runs `introvideo swap --apply`.

    Validates intro_randomizer_dir / intro_video_target are configured
    first (same pre-flight `swap_video` does), so install can't succeed
    against a config the swap itself would immediately fail against.
    Dry-run previews the bat/vbs paths and task name without writing
    anything or touching Task Scheduler — the only step that needs
    Windows is the `--apply` registration itself.
    """
    _pool_dir(config)
    _target_file(config)
    bat_path = _swap_bat_path()
    vbs_path = bat_path.with_suffix(".vbs")
    if not apply:
        return AutorunResult(
            bat_path=bat_path, vbs_path=vbs_path,
            task_name=AUTORUN_TASK_NAME, registered=False,
        )

    bat_path = _write_swap_bat()
    vbs_path = _write_swap_vbs(bat_path)
    result = autostart.create_logon_task(
        _autorun_command(vbs_path), name=AUTORUN_TASK_NAME, delay_minutes=delay_minutes,
    )
    return AutorunResult(
        bat_path=bat_path, vbs_path=vbs_path, task_name=AUTORUN_TASK_NAME,
        registered=True, output=result.output,
    )


def uninstall_autorun(*, apply: bool = False) -> AutorunResult:
    """Remove the logon task. Leaves the bat/vbs files (harmless leftovers)."""
    bat_path = _swap_bat_path()
    vbs_path = bat_path.with_suffix(".vbs")
    exists = autostart.task_exists(name=AUTORUN_TASK_NAME)
    if not apply:
        return AutorunResult(
            bat_path=bat_path, vbs_path=vbs_path,
            task_name=AUTORUN_TASK_NAME, registered=exists,
        )
    output = autostart.delete_logon_task(name=AUTORUN_TASK_NAME) if exists else ""
    return AutorunResult(
        bat_path=bat_path, vbs_path=vbs_path, task_name=AUTORUN_TASK_NAME,
        registered=False, output=output,
    )


def autorun_status() -> AutorunStatus:
    """Whether the logon task is registered, and whether it's stale.

    "Stale" means the task is registered but the generated `.bat` no
    longer reflects the currently-running install: either the file is
    missing outright, or (frozen installs only) it doesn't reference the
    `spindoctor.exe` this process is actually running from — the
    situation after upgrading to a new version extracted into a new
    folder without re-running `install_autorun`. Re-running it fixes a
    stale task in place (same task name, `/F` overwrite — no need to
    uninstall first). Always not-stale on a non-frozen install: the
    `.bat` calls bare `spindoctor` there, which isn't tied to any
    specific folder, so there's nothing version-specific to go stale.

    Windows-only — raises `autostart.NotSupportedError` elsewhere, same
    as autostart.py.
    """
    registered = autostart.task_exists(name=AUTORUN_TASK_NAME)
    if not registered:
        return AutorunStatus(registered=False, stale=False)
    stale = False
    if getattr(sys, "frozen", False):
        bat_path = _swap_bat_path()
        if not bat_path.exists():
            stale = True
        else:
            current_exe = _sibling_spindoctor_exe()
            bat_text = bat_path.read_text(encoding="utf-8", errors="replace")
            stale = current_exe not in bat_text
    return AutorunStatus(registered=True, stale=stale)
