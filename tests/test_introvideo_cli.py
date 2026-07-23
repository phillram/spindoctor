"""CLI-level smoke tests for `spindoctor introvideo`."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.autostart as autostart_mod
import spindoctor.config as config_mod
from spindoctor.cli import cli


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()

    pool_dir = tmp_path / "Intro Video Randomizer"
    pool_dir.mkdir(parents=True)
    (pool_dir / "Existing.mp4").write_bytes(b"x" * 10)
    intro_mp4 = tmp_path / "Intro.mp4"
    cfg = config_mod.Config(
        intro_randomizer_dir=str(pool_dir),
        intro_video_target=str(intro_mp4),
    )
    config_mod.save_config(cfg)
    yield {"pool_dir": pool_dir, "target": intro_mp4}
    config_mod.reset_override_cache()


def test_introvideo_list_shows_existing_video(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "list"])
    assert result.exit_code == 0, result.output
    assert "Existing.mp4" in result.output
    assert "enabled" in result.output


def test_introvideo_add_dry_run_then_apply(cabinet, tmp_path):
    source = tmp_path / "brand_new.mp4"
    source.write_bytes(b"video bytes")
    runner = CliRunner()

    dry = runner.invoke(cli, ["introvideo", "add", str(source)])
    assert dry.exit_code == 0, dry.output
    assert "Re-run with --apply" in dry.output
    assert not (cabinet["pool_dir"] / "brand_new.mp4").exists()

    applied = runner.invoke(cli, ["introvideo", "add", str(source), "--apply"])
    assert applied.exit_code == 0, applied.output
    assert (cabinet["pool_dir"] / "brand_new.mp4").exists()


def test_introvideo_add_already_present_is_noop(cabinet):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["introvideo", "add", str(cabinet["pool_dir"] / "Existing.mp4"), "--apply"],
    )
    assert result.exit_code == 0, result.output
    assert "already in pool" in result.output


def test_introvideo_remove_moves_to_disabled_not_deleted(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "remove", "Existing.mp4", "--apply"])
    assert result.exit_code == 0, result.output
    assert not (cabinet["pool_dir"] / "Existing.mp4").exists()
    assert (cabinet["pool_dir"] / "Disabled" / "Existing.mp4").exists()


def test_introvideo_remove_not_found_reports_cleanly(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "remove", "Ghost.mp4", "--apply"])
    assert result.exit_code == 0, result.output
    assert "not found" in result.output.lower()


def test_introvideo_restore_moves_back_to_pool(cabinet):
    runner = CliRunner()
    remove = runner.invoke(cli, ["introvideo", "remove", "Existing.mp4", "--apply"])
    assert remove.exit_code == 0, remove.output

    restore = runner.invoke(cli, ["introvideo", "restore", "Existing.mp4", "--apply"])
    assert restore.exit_code == 0, restore.output
    assert (cabinet["pool_dir"] / "Existing.mp4").exists()
    assert not (cabinet["pool_dir"] / "Disabled" / "Existing.mp4").exists()


def test_introvideo_add_multiple_sources_in_one_call(cabinet, tmp_path):
    source_a = tmp_path / "a.mp4"
    source_a.write_bytes(b"a")
    source_b = tmp_path / "b.mp4"
    source_b.write_bytes(b"b")
    runner = CliRunner()

    result = runner.invoke(
        cli, ["introvideo", "add", str(source_a), str(source_b), "--apply"],
    )
    assert result.exit_code == 0, result.output
    assert (cabinet["pool_dir"] / "a.mp4").exists()
    assert (cabinet["pool_dir"] / "b.mp4").exists()


def test_introvideo_remove_multiple_filenames_in_one_call(cabinet):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["introvideo", "remove", "Existing.mp4", "Ghost.mp4", "--apply"],
    )
    assert result.exit_code == 0, result.output
    assert (cabinet["pool_dir"] / "Disabled" / "Existing.mp4").exists()
    assert "not found" in result.output.lower()


def test_introvideo_swap_dry_run_then_apply(cabinet):
    # A single enabled video makes the random pick deterministic.
    runner = CliRunner()
    before = cabinet["target"].exists()
    assert not before

    dry = runner.invoke(cli, ["introvideo", "swap"])
    assert dry.exit_code == 0, dry.output
    assert "Existing.mp4" in dry.output
    assert not cabinet["target"].exists()

    applied = runner.invoke(cli, ["introvideo", "swap", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert cabinet["target"].exists()
    assert cabinet["target"].read_bytes() == (cabinet["pool_dir"] / "Existing.mp4").read_bytes()


def test_introvideo_swap_empty_pool_reports_noop(cabinet):
    (cabinet["pool_dir"] / "Existing.mp4").unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "swap", "--apply"])
    assert result.exit_code == 0, result.output
    assert "No videos in the pool" in result.output
    assert not cabinet["target"].exists()


def test_introvideo_unconfigured_errors_cleanly(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "list"])
    assert result.exit_code != 0
    assert "intro_randomizer_dir is not set" in result.output
    config_mod.reset_override_cache()


def test_introvideo_install_autorun_dry_run_does_not_touch_task_scheduler(cabinet, monkeypatch):
    # Dry-run must not call into autostart.py at all — no Windows needed.
    def _boom(*a, **k):
        raise AssertionError("dry-run must not touch Task Scheduler")
    monkeypatch.setattr(autostart_mod, "create_logon_task", _boom)

    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "install-autorun"])
    assert result.exit_code == 0, result.output
    assert "Would write" in result.output
    assert "Would register" in result.output


def test_introvideo_install_autorun_apply_registers_task(cabinet, tmp_path, monkeypatch):
    # _write_swap_bat/_write_swap_vbs fall back to ~/.spindoctor/ for
    # non-frozen installs — redirect Path.home() so this test never
    # touches the real developer machine's home directory.
    fake_home = tmp_path / "home2"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    calls = {}

    def _fake_create(command, *, name, delay_minutes=None):
        calls["command"] = command
        calls["name"] = name
        return autostart_mod.TaskCreateResult(name=name, command=command, output="SUCCESS")

    monkeypatch.setattr(autostart_mod, "create_logon_task", _fake_create)

    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "install-autorun", "--apply"])
    assert result.exit_code == 0, result.output
    assert calls["name"] == "SpinDoctor Intro Swap"
    assert "wscript.exe" in calls["command"]
    assert (fake_home / ".spindoctor" / "spindoctor-intro-swap.bat").exists()
    assert (fake_home / ".spindoctor" / "spindoctor-intro-swap.vbs").exists()


def test_introvideo_uninstall_autorun_apply_removes_task(cabinet, monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    calls = {}

    def _fake_delete(name):
        calls["name"] = name
        return "SUCCESS"
    monkeypatch.setattr(autostart_mod, "delete_logon_task", _fake_delete)

    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "uninstall-autorun", "--apply"])
    assert result.exit_code == 0, result.output
    assert calls["name"] == "SpinDoctor Intro Swap"


def test_introvideo_uninstall_autorun_nothing_registered(cabinet, monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: False)

    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "uninstall-autorun"])
    assert result.exit_code == 0, result.output
    assert "not registered" in result.output
