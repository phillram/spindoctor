"""Tests for spindoctor._utils — the shared format_bytes / free_bytes helpers.

The same `format_bytes` shape used to live three times (in `backup.py`,
`migrate.py`, and as `format_size` in `cleanup.py`) with subtly
different floor / decimal behaviour. These tests pin the unified
implementation so a future refactor can't regress the bucketing.
"""
from __future__ import annotations

import shutil

from spindoctor._utils import format_bytes, free_bytes, unique_path


def test_format_bytes_zero():
    assert format_bytes(0) == "0 B"


def test_format_bytes_under_kb_renders_as_integer_b():
    assert format_bytes(512) == "512 B"


def test_format_bytes_kb_renders_with_one_decimal():
    assert format_bytes(2048).startswith("2.0 KB")


def test_format_bytes_mb_renders_with_one_decimal():
    assert format_bytes(5 * 1024 * 1024).endswith(" MB")


def test_format_bytes_clamps_at_tb_for_huge_inputs():
    # 5 PB worth of bytes — still renders as a TB string, not an
    # un-translated PB unit that didn't exist in the historical code.
    assert format_bytes(5 * 1024**5).endswith(" TB")


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
