"""Tests for spindoctor._errors.humanize_oserror.

Each test fakes the specific errno / winerror it cares about and
asserts the resulting message contains the load-bearing actionable
phrase ("close HyperSpin", "free up space", etc.). We don't assert on
the full message text — that would make the messages annoying to edit.
"""
from __future__ import annotations

import errno

from spindoctor._errors import humanize_oserror


def _make(code=None, winerror=None, filename="", msg="boom"):
    """Build an OSError with the specified errno / winerror / filename.

    OSError accepts (errno, strerror, filename, winerror) but the
    winerror constructor arg is silently ignored on non-Windows
    Python builds. We always set `winerror` as an attribute after
    construction so the test runs identically on macOS / Linux CI.
    """
    e = OSError(code or 0, msg, filename) if filename else OSError(code or 0, msg)
    if winerror is not None:
        e.winerror = winerror
    return e


def test_file_in_use_winerror_32():
    e = _make(winerror=32, filename=r"C:\HyperSpin\Main Menu.xml")
    msg = humanize_oserror(e, action="save Main Menu.xml")
    assert "save Main Menu.xml" in msg
    assert "Main Menu.xml" in msg
    assert "HyperSpin" in msg or "in use" in msg


def test_eacces_mentions_read_only_attribute():
    e = _make(code=errno.EACCES, filename="/foo/bar.xml")
    msg = humanize_oserror(e, action="write config.json")
    assert "permission" in msg.lower()
    # The 3 most common Windows causes should all be mentioned so the
    # user has something to try.
    assert "read-only" in msg.lower() or "Read-only" in msg


def test_enospc_includes_freeup_hint():
    e = _make(code=errno.ENOSPC, filename="/data/HyperSpin")
    msg = humanize_oserror(e, action="back up")
    assert "space" in msg.lower()
    assert "free up" in msg.lower() or "Free" in msg


def test_enoent_suggests_setup_tab():
    e = _make(code=errno.ENOENT, filename="/missing/path.xml")
    msg = humanize_oserror(e)
    assert "path.xml" in msg
    assert "Setup" in msg or "config" in msg.lower()


def test_eisdir_explains_file_vs_dir():
    e = _make(code=errno.EISDIR, filename="/a/dir/")
    msg = humanize_oserror(e)
    assert "directory" in msg.lower()


def test_eexist_mentions_overwrite_flag():
    e = _make(code=errno.EEXIST, filename="/x/y.zip")
    msg = humanize_oserror(e)
    assert "overwrite" in msg.lower() or "--overwrite" in msg


def test_path_too_long_mentions_260_chars():
    e = _make(winerror=206, filename="C:\\very\\deep\\path")
    msg = humanize_oserror(e)
    assert "260" in msg or "long" in msg.lower()


def test_unknown_falls_back_to_str_exc():
    """An OSError with no recognised errno still produces something
    informative — we don't lose the OS's own message."""
    # errno 999 doesn't exist on any platform.
    e = OSError(999, "some weird filesystem driver said no")
    msg = humanize_oserror(e, action="do thing")
    assert "do thing" in msg
    # str(exc) typically renders as "[Errno 999] some weird ..."
    assert "weird" in msg or "999" in msg


def test_no_action_phrase_when_action_blank():
    e = _make(code=errno.ENOENT, filename="/x")
    msg = humanize_oserror(e)
    # Sentence is still parseable without the leading "Couldn't X:" clause.
    assert "Couldn't" not in msg
    assert msg  # non-empty


def test_filename_missing_does_not_crash():
    """Some OSErrors have no filename attached. Still produces a
    coherent sentence."""
    e = OSError(errno.EACCES, "denied")
    msg = humanize_oserror(e)
    assert isinstance(msg, str) and msg
    # Don't reference the (absent) basename — should fall back to "the target file".
    assert "the target file" in msg or "permission" in msg.lower()


def test_full_path_shown_not_just_basename():
    """Error messages must include the full path so the user can locate
    the file — basename-only was useless when databases span many
    system subfolders (e.g. 'A Visual Commpendium.xml' with no folder)."""
    full = r"D:\Arcade\Databases\Nintendo 64\A Visual Commpendium.xml"
    e = _make(code=errno.EACCES, filename=full)
    msg = humanize_oserror(e, action="restore from the backup")
    assert full in msg, f"Expected full path in message, got: {msg!r}"


def test_does_not_raise_on_garbage_exc():
    """Resilience: even a hand-constructed OSError with no useful
    attributes must not raise from the humanizer."""

    class WeirdError(OSError):
        pass

    e = WeirdError()
    msg = humanize_oserror(e)
    assert isinstance(msg, str)
