"""`spindoctor backup sidecar list/restore` — per-modify .bak restore CLI.

The cabinet owner needed a way to recover from a bad Save Order (the
Main Menu corruption that turned up in PR #144) without dropping out of
SpinDoctor and into Explorer to copy .bak files manually. These tests
pin the CLI contract that surface: the GUI's Restore-from-backup button
shells out to ``backup sidecar list --json`` and ``backup sidecar
restore --apply``, so this is what guarantees the GUI button keeps
working.
"""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from spindoctor.cli import cli


def _make_target(tmp_path: Path) -> Path:
    """Create a fake "live" file plus a couple of sidecar .bak snapshots."""
    target = tmp_path / "Main Menu.xml"
    target.write_text(
        "<?xml version=\"1.0\"?>\n<menu><game name=\"current\"/></menu>\n",
        encoding="utf-8",
    )
    # Two backups, distinct timestamps so the list is deterministic.
    bak_old = tmp_path / "Main Menu.20250101_120000.bak"
    bak_new = tmp_path / "Main Menu.20260519_153045.bak"
    bak_old.write_text(
        "<?xml version=\"1.0\"?>\n<menu><game name=\"old\"/></menu>\n",
        encoding="utf-8",
    )
    bak_new.write_text(
        "<?xml version=\"1.0\"?>\n<menu><game name=\"new\"/></menu>\n",
        encoding="utf-8",
    )
    return target


def test_list_returns_sidecars_newest_first(tmp_path):
    target = _make_target(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["backup", "sidecar", "list", str(target)],
    )
    assert result.exit_code == 0, result.output
    # Both .bak files must show up; the newer one must appear before the older.
    new_idx = result.output.find("20260519_153045")
    old_idx = result.output.find("20250101_120000")
    assert new_idx >= 0 and old_idx >= 0, result.output
    assert new_idx < old_idx, "newest .bak must be listed first"


def test_list_json_is_parseable_and_ordered(tmp_path):
    target = _make_target(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["backup", "sidecar", "list", str(target), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 2
    # Each entry has the four keys the GUI picker reads.
    for entry in data:
        assert set(entry).issuperset({"path", "name", "size", "mtime"})
    # Newest first by timestamp suffix.
    assert "20260519_153045" in data[0]["name"]
    assert "20250101_120000" in data[1]["name"]


def test_list_empty_when_no_sidecars(tmp_path):
    target = tmp_path / "fresh.xml"
    target.write_text("hello", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["backup", "sidecar", "list", str(target), "--json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_list_ignores_unrelated_bak_files(tmp_path):
    """Bakfiles for a different file in the same dir must not be returned."""
    target = _make_target(tmp_path)
    # Sidecar for a different live file — must be excluded.
    (tmp_path / "Settings.20260519_120000.bak").write_text(
        "unrelated", encoding="utf-8",
    )
    # Bare .bak (no timestamp) — also excluded; pattern requires the stamp.
    (tmp_path / "Main Menu.bak").write_text("not a stamped sidecar", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["backup", "sidecar", "list", str(target), "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    names = {e["name"] for e in data}
    assert "Settings.20260519_120000.bak" not in names
    assert "Main Menu.bak" not in names
    assert "Main Menu.20260519_153045.bak" in names
    assert "Main Menu.20250101_120000.bak" in names


def test_restore_dry_run_does_not_modify_files(tmp_path):
    target = _make_target(tmp_path)
    bak = tmp_path / "Main Menu.20250101_120000.bak"
    target_before = target.read_text(encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["backup", "sidecar", "restore", str(target), "--from", str(bak)],
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower() or "would copy" in result.output.lower()
    # Files unchanged.
    assert target.read_text(encoding="utf-8") == target_before


def test_restore_apply_overwrites_target_and_backs_up_live(tmp_path):
    target = _make_target(tmp_path)
    bak = tmp_path / "Main Menu.20250101_120000.bak"
    target_before = target.read_text(encoding="utf-8")
    bak_contents = bak.read_text(encoding="utf-8")
    sidecars_before = sorted(p.name for p in tmp_path.glob("Main Menu.*.bak"))

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["backup", "sidecar", "restore",
         str(target), "--from", str(bak), "--apply"],
    )
    assert result.exit_code == 0, result.output

    # Target now matches the backup we restored from.
    assert target.read_text(encoding="utf-8") == bak_contents
    # A NEW sidecar was created from the pre-restore live file, so the
    # restore is itself undoable.
    sidecars_after = sorted(p.name for p in tmp_path.glob("Main Menu.*.bak"))
    assert len(sidecars_after) == len(sidecars_before) + 1
    new_sidecar = next(p for p in tmp_path.glob("Main Menu.*.bak")
                       if p.name not in sidecars_before)
    assert new_sidecar.read_text(encoding="utf-8") == target_before


def test_restore_rejects_non_bak_source(tmp_path):
    target = _make_target(tmp_path)
    bogus = tmp_path / "not-a-backup.xml"
    bogus.write_text("data", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["backup", "sidecar", "restore",
         str(target), "--from", str(bogus), "--apply"],
    )
    assert result.exit_code != 0


def test_restore_rejects_sidecar_of_different_file(tmp_path):
    """Pass a Settings.*.bak as the source for Main Menu.xml — must reject."""
    target = _make_target(tmp_path)
    wrong = tmp_path / "Settings.20260519_120000.bak"
    wrong.write_text("nope", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["backup", "sidecar", "restore",
         str(target), "--from", str(wrong), "--apply"],
    )
    assert result.exit_code != 0
    assert "doesn't look like a sidecar" in result.output.lower() \
        or "doesn" in result.output.lower()


def test_restore_when_live_file_missing_still_succeeds(tmp_path):
    """Restoring when there is no current file is allowed — just copy the bak."""
    target = tmp_path / "Main Menu.xml"
    bak = tmp_path / "Main Menu.20250101_120000.bak"
    bak.write_text("payload", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["backup", "sidecar", "restore",
         str(target), "--from", str(bak), "--apply"],
    )
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == "payload"


# ─── backup list --json (consumed by the GUI's _scan_backup_folders) ─────────


def _make_backup_folder(parent: Path, stamp: str) -> Path:
    """Create a fake spindoctor-backup-XXXX folder with a minimal manifest."""
    folder = parent / f"spindoctor-backup-{stamp}"
    folder.mkdir()
    # ``backup list`` reads ``manifest.json``; a minimal valid one is enough.
    (folder / "manifest.json").write_text(
        json.dumps({
            "timestamp": stamp,
            "items": [
                {"component": "settings", "size_bytes": 123},
            ],
        }),
        encoding="utf-8",
    )
    return folder


def test_backup_list_json_emits_entries_with_paths(tmp_path):
    """``backup list --json`` produces the shape the GUI expects."""
    target = tmp_path / "backups"
    target.mkdir()
    _make_backup_folder(target, "20260101_120000")
    _make_backup_folder(target, "20260202_120000")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["backup", "list", "--target", str(target), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 2
    for entry in data:
        # GUI consumes ``path`` to populate the restore Combobox.
        assert "name" in entry and "path" in entry
        # And ``timestamp`` + ``components`` for the table view.
        assert entry["name"].startswith("spindoctor-backup-")
        assert entry["timestamp"]
        assert entry["components"] == ["settings"]


def test_backup_list_json_empty_when_no_backups(tmp_path):
    target = tmp_path / "backups"
    target.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        cli, ["backup", "list", "--target", str(target), "--json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == []
