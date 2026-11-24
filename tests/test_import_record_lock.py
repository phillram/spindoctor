"""Saving the import record while another program holds it for a moment.

On Windows a virus scanner or the search indexer can have a file open just
after it is written, and renaming the temp file over it then fails with
``[WinError 5] Access is denied`` (or 32, in use).  ``atomic_write_bytes``
waits that out, and ``import_media`` (``media-scan`` / ``generate-media
put-in``) no longer stops halfway when a save of its record still fails.
"""
from __future__ import annotations

import errno
import os
import threading
import time
from pathlib import Path

import pytest

from spindoctor import _utils, media_scan
from spindoctor.config import Config
from spindoctor.media_scan import (
    ImportResult, LocalMediaFile, MediaScanReport, ScanMatch, import_media, undo_import,
)


def _busy(winerror: int, src="file.tmp", dst="file.json") -> PermissionError:
    """The error Windows gives when another program has the file open."""
    exc = PermissionError(errno.EACCES, "Access is denied", str(src), winerror, str(dst))
    exc.winerror = winerror     # only Windows sets it from the constructor
    return exc


@pytest.fixture
def sleeps(monkeypatch):
    waited: list[float] = []
    monkeypatch.setattr(time, "sleep", waited.append)
    return waited


def _refuse(monkeypatch, first: int, count: int, name_prefix: str = "") -> list:
    """``os.replace`` that refuses calls *first* .. *first* + *count* - 1
    (counted from 1) onto files whose name starts with *name_prefix*."""
    real = os.replace
    calls: list = []

    def replace(src, dst):
        if Path(dst).name.startswith(name_prefix):
            calls.append(dst)
            if first <= len(calls) < first + count:
                raise _busy(5, src, dst)
        return real(src, dst)

    monkeypatch.setattr(_utils.os, "replace", replace)
    return calls


# ─── atomic_write_bytes ──────────────────────────────────────────────────────

@pytest.mark.parametrize("winerror", [5, 32])
def test_a_brief_lock_is_waited_out(tmp_path, monkeypatch, sleeps, winerror):
    target = tmp_path / "import-1.json"
    target.write_bytes(b"old")
    real = os.replace
    refused = []

    def replace(src, dst):
        if len(refused) < 3:
            refused.append(dst)
            raise _busy(winerror, src, dst)
        return real(src, dst)

    monkeypatch.setattr(_utils.os, "replace", replace)
    _utils.atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert len(refused) == 3 and sleeps == [_utils._REPLACE_RETRY_SECONDS] * 3
    assert [p.name for p in tmp_path.iterdir()] == ["import-1.json"]


def test_a_lock_that_stays_fails_after_about_two_seconds(tmp_path, monkeypatch, sleeps):
    target = tmp_path / "import-1.json"
    target.write_bytes(b"old")
    calls = _refuse(monkeypatch, 1, 1000)
    with pytest.raises(PermissionError, match="Access is denied"):
        _utils.atomic_write_bytes(target, b"new")
    assert len(calls) == _utils._REPLACE_ATTEMPTS == 10
    assert len(sleeps) == 9 and 1.5 <= sum(sleeps) <= 2.5
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["import-1.json"]     # temp file removed


@pytest.mark.parametrize("error", [
    PermissionError(errno.EACCES, "Permission denied"),     # POSIX: no winerror
    _busy(3),                                               # path not found
    OSError("disk full"),
])
def test_other_errors_are_not_retried(tmp_path, monkeypatch, sleeps, error):
    def replace(src, dst):
        raise error

    monkeypatch.setattr(_utils.os, "replace", replace)
    with pytest.raises(OSError) as info:
        _utils.atomic_write_bytes(tmp_path / "file.json", b"new")
    assert info.value is error and sleeps == []


@pytest.mark.skipif(os.name != "nt", reason="a Windows file lock")
def test_a_real_windows_lock_is_waited_out(tmp_path, monkeypatch):
    target = tmp_path / "import-1.json"
    target.write_bytes(b"old")
    # Python opens files without FILE_SHARE_DELETE, so while this handle is
    # open Windows refuses to rename anything over the file, as it does
    # while a scanner reads it.
    holder = open(target, "rb")
    timer = threading.Timer(0.3, holder.close)
    try:
        monkeypatch.setattr(_utils, "_REPLACE_ATTEMPTS", 1)
        with pytest.raises(PermissionError) as info:
            _utils.atomic_write_bytes(target, b"new")
        assert info.value.winerror in (5, 32)
        monkeypatch.setattr(_utils, "_REPLACE_ATTEMPTS", 10)
        timer.start()
        _utils.atomic_write_bytes(target, b"new")
    finally:
        if timer.is_alive():
            timer.join()
        holder.close()
    assert target.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["import-1.json"]


# ─── import_media ────────────────────────────────────────────────────────────

def _import(tmp_path: Path, games=("Alpha", "Bravo", "Charlie")) -> tuple[ImportResult, Path, Path]:
    """Copy one wheel picture per game into an empty Media folder."""
    src = tmp_path / "staged"
    media = tmp_path / "Media" / "NES" / "Images" / "Wheel"
    src.mkdir()
    report = MediaScanReport(source_dir=src)
    for game in games:
        (src / f"{game}.png").write_bytes(game.encode())
        report.matched.append(ScanMatch(
            local=LocalMediaFile(src / f"{game}.png", "wheel"), system="NES", game_name=game,
            score=1.0, target_path=media / f"{game}.png", bucket="matched"))
    records = tmp_path / "media_imports"
    return import_media(report, Config(), manifest_dir=records, label="test"), media, records


def test_a_brief_lock_on_the_record_puts_everything_in(tmp_path, monkeypatch, sleeps):
    calls = _refuse(monkeypatch, 3, 4, media_scan.MANIFEST_PREFIX)
    result, media, _records = _import(tmp_path)
    assert len(result.imported) == 3 and result.record_error == ""
    assert len(calls) == 6 + 4 and len(sleeps) == 4


def test_a_save_that_fails_mid_batch_is_caught_up_by_the_next(tmp_path, monkeypatch, sleeps):
    # Bravo's first save (the 3rd) is refused all 10 times; its second works.
    _refuse(monkeypatch, 3, 10, media_scan.MANIFEST_PREFIX)
    result, media, _records = _import(tmp_path)
    assert len(result.imported) == 3 and result.record_error == ""
    assert sorted(p.name for p in media.iterdir()) == ["Alpha.png", "Bravo.png", "Charlie.png"]
    assert undo_import(result.manifest_path) == {"reverted": 3, "errors": []}
    assert list(media.iterdir()) == []


def test_a_record_that_stays_locked_still_puts_everything_in_and_says_so(tmp_path, monkeypatch, sleeps):
    # Alpha's first save works, then the record stays locked to the end.
    _refuse(monkeypatch, 2, 1000, media_scan.MANIFEST_PREFIX)
    result, media, _records = _import(tmp_path)
    assert len(result.imported) == 3
    assert sorted(p.name for p in media.iterdir()) == ["Alpha.png", "Bravo.png", "Charlie.png"]
    assert result.manifest_path.name in result.record_error
    assert "[WinError 5] Access is denied" in result.record_error
    assert "undo won't take out the last 2 file(s)" in result.record_error
    # The record on disk still has Alpha (as begun), so undo takes it out.
    monkeypatch.undo()
    assert undo_import(result.manifest_path) == {"reverted": 1, "errors": []}
    assert sorted(p.name for p in media.iterdir()) == ["Bravo.png", "Charlie.png"]


def test_without_a_first_record_nothing_goes_in(tmp_path, monkeypatch, sleeps):
    _refuse(monkeypatch, 1, 1000, media_scan.MANIFEST_PREFIX)
    with pytest.raises(PermissionError):
        _import(tmp_path)
    assert not (tmp_path / "Media").exists()
    assert not (tmp_path / "media_imports").exists() or not any((tmp_path / "media_imports").iterdir())
