"""Humanize OS-level errors into actionable user-facing text.

Cabinet owners hit `[WinError 32] The process cannot access the file …
because it is being used by another process` regularly — HyperSpin or
RocketLauncher holds open handles on the XML/INI files SpinDoctor wants
to rewrite. The verbatim ``OSError`` repr is technically correct but
useless: the user needs to know "close HyperSpin and try again", not
to look up Windows error code 32.

This module wraps an ``OSError`` (or ``PermissionError`` / ``FileNotFoundError`` /
``IsADirectoryError`` etc., which all subclass it) and returns a sentence
the user can act on. Falls back to the str(exc) message when the pattern
doesn't match anything we recognise — never raises, never lies.

Usage::

    try:
        do_thing()
    except OSError as e:
        print(humanize_oserror(e, action="save Main Menu.xml"))
"""
from __future__ import annotations

import errno
import os
from typing import Optional


def humanize_oserror(exc: OSError, *, action: str = "") -> str:
    """Return a one-sentence, actionable explanation of *exc*.

    *action* is an optional verb phrase the caller knows about — "save
    Main Menu.xml", "open the metadata cache". When supplied, the
    output reads naturally: "Couldn't save Main Menu.xml — HyperSpin is
    currently open. Close HyperSpin and try again." When absent, the
    sentence still parses but skips the leading clause.

    Never raises. If the pattern doesn't match anything specific, falls
    back to including ``str(exc)`` so the user at least sees the OS's
    own message.
    """
    code = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    filename = getattr(exc, "filename", "") or ""

    prefix = f"Couldn't {action}: " if action else ""

    # ── Permission / file-in-use ─────────────────────────────────────────────

    # Windows error 32: file is locked by another process (HyperSpin /
    # RocketLauncher / a text editor). Most frequent failure mode on cabs.
    if winerror == 32:
        return (
            f"{prefix}{filename or 'the target file'} is "
            "currently in use by another program. The most common cause "
            "on a cabinet is HyperSpin or RocketLauncher being open — "
            "close them and try again."
        )

    # Windows error 5 (access denied) or POSIX EACCES (13). Could be a
    # locked file, a read-only attribute (common on copies pulled off
    # SD cards), or insufficient privileges.
    if winerror == 5 or code == errno.EACCES:
        return (
            f"{prefix}permission denied on "
            f"{filename or 'the target file'}. Common causes: "
            "(1) the file is open in HyperSpin / RocketLauncher — close "
            "them, (2) the file has Windows' read-only attribute set — "
            "right-click → Properties and untick Read-only, "
            "(3) SpinDoctor doesn't have permission on the folder."
        )

    # POSIX EPERM (1) — "operation not permitted". On macOS / Linux this
    # is usually a sandbox or attribute issue.
    if code == errno.EPERM:
        return (
            f"{prefix}operation not permitted on "
            f"{filename or 'the target file'}. The file may "
            "have an immutable / locked attribute (chflags / chattr) or "
            "be inside a sandbox SpinDoctor can't write to."
        )

    # ── Disk full ────────────────────────────────────────────────────────────

    if code == errno.ENOSPC:
        drive = _drive_hint(filename)
        drive_clause = f" on {drive}" if drive else ""
        return (
            f"{prefix}no space left on disk{drive_clause}. Free up some "
            "space (the Diagnose tab's 'Find duplicate ROMs' or the "
            "Backup tab's 'Show backup info' are common starting points) "
            "and try again."
        )

    # ── Path missing ─────────────────────────────────────────────────────────

    if code == errno.ENOENT:
        return (
            f"{prefix}can't find {filename or 'the path'}. "
            "It may have been moved or deleted since SpinDoctor last "
            "saw it — check it still exists, or update the relevant "
            "field on the Setup tab."
        )

    # ── Path is a directory when a file was expected (or vice-versa) ────────

    if code == errno.EISDIR:
        return (
            f"{prefix}{filename or 'the target'} is a "
            "directory, but SpinDoctor expected a file. Check the path "
            "in your config — you probably want to point one level "
            "deeper into the folder."
        )

    if code == errno.ENOTDIR:
        return (
            f"{prefix}part of the path "
            f"({filename or 'the target'}) is a file, not a "
            "directory. Likely an old path in config.json that now "
            "points at a renamed file."
        )

    # ── Already exists when we tried to create ───────────────────────────────

    if code == errno.EEXIST:
        return (
            f"{prefix}{filename or 'the target'} already "
            "exists. Pass --overwrite (CLI) or tick the Overwrite "
            "checkbox (GUI) if you actually want to replace it."
        )

    # ── Cross-device link / move ─────────────────────────────────────────────

    if code == errno.EXDEV:
        return (
            f"{prefix}can't move {filename or 'the file'} "
            "across drives with a rename — SpinDoctor must copy it "
            "first. This is usually transparent; if you're seeing it, "
            "the destination drive may be a network share or removable "
            "media that doesn't support fast rename."
        )

    # ── Read-only filesystem ─────────────────────────────────────────────────

    if code == errno.EROFS:
        return (
            f"{prefix}the target filesystem is read-only "
            f"(path: {filename or 'the target'}). If this is "
            "an external drive, check its read-only switch; if it's a "
            "mount, remount with write permission."
        )

    # ── Path too long (Windows) ──────────────────────────────────────────────

    if winerror == 206 or code == errno.ENAMETOOLONG:
        return (
            f"{prefix}path is too long for the OS to handle. Windows "
            "caps most APIs at 260 characters by default. Move the "
            "cabinet library closer to the drive root (e.g. C:\\HS\\ "
            "instead of C:\\Users\\…\\Documents\\HyperSpin\\…), or "
            "enable Windows 10's long-path support."
        )

    # ── Fallback ─────────────────────────────────────────────────────────────

    # Include the OS error verbatim so the user at least has something
    # to paste into a support thread. Strip the noisy "[Errno N]" prefix
    # since the str(exc) form already includes it.
    raw = str(exc)
    return f"{prefix}{raw}" if raw else f"{prefix}unknown filesystem error."


# ─── helpers ─────────────────────────────────────────────────────────────────


def _drive_hint(path: str) -> Optional[str]:
    """Return the drive root for *path* on Windows, else None."""
    if not path:
        return None
    if os.name != "nt":
        return None
    try:
        drive, _ = os.path.splitdrive(path)
        return drive or None
    except Exception:  # noqa: BLE001
        return None
