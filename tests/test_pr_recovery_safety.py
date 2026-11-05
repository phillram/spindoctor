"""Recovery follow-ups found in the PR audit."""
from pathlib import Path

from click.testing import CliRunner

from spindoctor import _utils, backup, config
from spindoctor.cli import cli


def test_relative_overlap_check_handles_legacy_windows_resolve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real_resolve = Path.resolve

    def legacy_resolve(path, *args, **kwargs):
        if not path.is_absolute() and not path.exists():
            return path
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", legacy_resolve)
    assert _utils.is_within(Path("live/backups/new"), tmp_path / "live")


def test_latest_backup_uses_numeric_collision_counter(tmp_path):
    names = ["spindoctor-backup-20261104_120000" + suffix for suffix in ("", "_2", "_9", "_10")]
    for name in names:
        root = tmp_path / name
        root.mkdir()
        (root / "manifest.json").write_text("{}")
    assert [p.name for p in backup.list_backups(tmp_path)] == names
    assert backup.find_latest_backup(tmp_path).name == names[-1]


def test_restore_overlap_reports_a_cli_error(tmp_path, monkeypatch):
    source = tmp_path / "saved"
    source.mkdir()
    plan = backup.RestorePlan(str(source), [
        backup.RestoreItem("roms", str(source), str(source / "nested")),
    ])
    monkeypatch.setattr(backup, "plan_restore", lambda *args, **kwargs: plan)
    monkeypatch.setattr(config, "load_config", lambda: config.Config())
    result = CliRunner().invoke(cli, ["backup", "restore", "--backup", str(source), "--apply"])
    assert result.exit_code == 1
    assert "overlap" in result.output
    assert "Aborted" in result.output
