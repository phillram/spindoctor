"""Tests for spindoctor._utils — the shared format_bytes / free_bytes helpers.

The same `format_bytes` shape used to live three times (in `backup.py`,
`migrate.py`, and as `format_size` in `cleanup.py`) with subtly
different floor / decimal behaviour. These tests pin the unified
implementation so a future refactor can't regress the bucketing.
"""
from __future__ import annotations
from pathlib import Path
from spindoctor import _utils
from spindoctor._text import write_windows_text

import shutil

from tests.helpers import write_bytes as _write_bytes

import pytest

from spindoctor._utils import dir_size, format_bytes, free_bytes, unique_path


@pytest.mark.parametrize("value,expected", [
    (0, "0 B"),                       # zero renders as integer B
    (512, "512 B"),                   # under KB renders as integer B
    (2048, "2.0 KB"),                 # KB renders with one decimal
    (5 * 1024 * 1024, "5.0 MB"),      # MB renders with one decimal
    # 5 PB worth of bytes — still renders as a TB string, not an
    # un-translated PB unit that didn't exist in the historical code.
    (5 * 1024**5, "5120.0 TB"),
], ids=["zero", "under-kb", "kb", "mb", "clamps-at-tb"])
def test_format_bytes_units(value, expected):
    assert format_bytes(value) == expected


def test_format_bytes_backup_module_re_export_matches():
    """The historical `from .backup import format_bytes` callers must
    get back the same function the shared module owns now."""
    from spindoctor import backup
    assert backup.format_bytes is format_bytes


def test_format_bytes_migrate_module_re_export_matches():
    from spindoctor import migrate
    assert migrate.format_bytes is format_bytes


def test_cleanup_format_size_is_format_bytes():
    """`from .cleanup import format_size` was the historical alias."""
    from spindoctor import cleanup
    assert cleanup.format_size is format_bytes


def test_free_bytes_walks_up_for_nonexistent_path(tmp_path):
    """`free_bytes` is called with backup / migrate destinations that
    don't exist yet; it must report the volume's free space rather
    than 0 by walking up the parent chain.
    """
    nonexistent = tmp_path / "does" / "not" / "exist" / "yet"
    reported = free_bytes(nonexistent)
    # Free space should be > 0 on any sane test machine; matches the
    # value `shutil.disk_usage` returns for the existing tmp_path.
    actual = shutil.disk_usage(str(tmp_path)).free
    assert reported > 0
    # Same volume → same answer (within a small jitter for concurrent
    # filesystem activity). Pin to within 1 GB so the test doesn't flake.
    assert abs(reported - actual) < 1024**3


def test_free_bytes_returns_zero_on_oserror(monkeypatch, tmp_path):
    """If `shutil.disk_usage` raises OSError, the helper returns 0
    rather than propagating — callers use this for hints, not gates.
    """
    def boom(_p):
        raise OSError("no")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    assert free_bytes(tmp_path) == 0


def test_unique_path_returns_free_path_unchanged(tmp_path):
    target = tmp_path / "Emulators.20260614_174635.bak"
    assert unique_path(target) == target


def test_unique_path_never_returns_an_existing_file(tmp_path):
    """Backups stamped in the same second must not overwrite each other."""
    first = tmp_path / "Emulators.20260614_174635.bak"
    first.write_text("one", encoding="utf-8")
    second = unique_path(first)
    assert second.name == "Emulators.20260614_174635_2.bak"
    second.write_text("two", encoding="utf-8")
    assert unique_path(first).name == "Emulators.20260614_174635_3.bak"
    assert first.read_text(encoding="utf-8") == "one"


def test_unique_path_appends_counter_to_folder_names(tmp_path):
    folder = tmp_path / "scrub-20260614_174635"
    folder.mkdir()
    assert unique_path(folder).name == "scrub-20260614_174635_2"


def test_dir_size_handles_files_trees_and_missing_paths(tmp_path):
    assert dir_size(tmp_path / "missing") == 0
    first = tmp_path / "first"
    first.write_bytes(b"123")
    child = tmp_path / "child"
    child.mkdir()
    (child / "second").write_bytes(b"4567")
    assert dir_size(first) == 3
    assert dir_size(tmp_path) == 7


def test_dir_size_skips_unreadable_files(tmp_path, monkeypatch):
    from pathlib import Path

    unreadable = tmp_path / "unreadable"
    unreadable.write_bytes(b"123")
    (tmp_path / "readable").write_bytes(b"4567")
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == unreadable:
            raise PermissionError("test permission error")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    assert dir_size(tmp_path) == 4


def test_dir_size_legacy_aliases_share_one_implementation():
    from spindoctor import backup, fileinfo, migrate, self_doctor

    assert backup._dir_size is dir_size
    assert fileinfo._dir_size is dir_size
    assert migrate._dir_size is dir_size
    assert self_doctor._walk_size is dir_size


def test_atomic_cleanup_does_not_hide_original_failure(config_home, tmp_path, monkeypatch):
    from spindoctor import _utils
    target = _write_bytes(tmp_path / "document", b"original")
    def replace(*args):
        raise OSError("original replace failure")
    def unlink(*args):
        raise PermissionError("cleanup failure")
    monkeypatch.setattr(_utils.os, "replace", replace)
    monkeypatch.setattr(_utils.os, "unlink", unlink)
    with pytest.raises(OSError, match="original replace failure"):
        _utils.atomic_write_bytes(target, b"replacement")
    assert target.read_bytes() == b"original"


def test_relative_overlap_check_handles_legacy_windows_resolve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real_resolve = Path.resolve

    def legacy_resolve(path, *args, **kwargs):
        if not path.is_absolute() and not path.exists():
            return path
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", legacy_resolve)
    assert _utils.is_within(Path("live/backups/new"), tmp_path / "live")


def test_atomic_edit_failure_leaves_live_bytes_and_no_temp_files(tmp_path, monkeypatch):
    import spindoctor._utils as utils

    path = tmp_path / "Settings.ini"
    path.write_bytes(b"original")

    def fail_replace(*args):
        raise OSError("locked")

    monkeypatch.setattr(utils.os, "replace", fail_replace)
    with pytest.raises(OSError, match="locked"):
        write_windows_text(path, "changed")
    assert path.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Settings.ini"]
