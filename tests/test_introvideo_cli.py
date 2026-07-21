"""CLI-level smoke tests for `spindoctor introvideo`."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()

    randomizer_dir = tmp_path / "Intro Video Randomizer"
    videos_dir = randomizer_dir / "Intro Videos"
    videos_dir.mkdir(parents=True)
    (videos_dir / "Backup").mkdir()
    (videos_dir / "Existing.mp4").write_bytes(b"x" * 10)
    intro_mp4 = tmp_path / "Intro.mp4"
    (randomizer_dir / "Random.ini").write_text(
        "[Randomize1]\n"
        "Option=1\n"
        f"Folder={videos_dir}\n"
        f"FileToRandomize={intro_mp4}\n"
        "FileList=Existing.mp4\n"
        "RandomList=Existing.mp4\n",
        encoding="utf-8",
    )
    cfg = config_mod.Config(intro_randomizer_dir=str(randomizer_dir))
    config_mod.save_config(cfg)
    yield {"videos_dir": videos_dir, "randomizer_dir": randomizer_dir}
    config_mod.reset_override_cache()


def test_introvideo_list_shows_existing_video(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "list"])
    assert result.exit_code == 0, result.output
    assert "Existing.mp4" in result.output


def test_introvideo_add_dry_run_then_apply(cabinet, tmp_path):
    source = tmp_path / "brand_new.mp4"
    source.write_bytes(b"video bytes")
    runner = CliRunner()

    dry = runner.invoke(cli, ["introvideo", "add", str(source)])
    assert dry.exit_code == 0, dry.output
    assert "Re-run with --apply" in dry.output
    assert not (cabinet["videos_dir"] / "brand_new.mp4").exists()

    applied = runner.invoke(cli, ["introvideo", "add", str(source), "--apply"])
    assert applied.exit_code == 0, applied.output
    assert (cabinet["videos_dir"] / "brand_new.mp4").exists()
    assert "registered" in applied.output.lower()


def test_introvideo_remove_leaves_file_on_disk(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "remove", "Existing.mp4", "--apply"])
    assert result.exit_code == 0, result.output
    assert "file left on disk" in result.output
    assert (cabinet["videos_dir"] / "Existing.mp4").exists()

    ini_text = (cabinet["randomizer_dir"] / "Random.ini").read_text()
    assert "Existing.mp4" not in ini_text.split("\n")[4]  # FileList= line


def test_introvideo_remove_unregistered_reports_noop(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "remove", "Ghost.mp4", "--apply"])
    assert result.exit_code == 0, result.output
    assert "not registered" in result.output


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
    assert (cabinet["videos_dir"] / "a.mp4").exists()
    assert (cabinet["videos_dir"] / "b.mp4").exists()
    assert result.output.count("registered in Random.ini") == 2


def test_introvideo_remove_multiple_filenames_in_one_call(cabinet):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["introvideo", "remove", "Existing.mp4", "Ghost.mp4", "--apply"],
    )
    assert result.exit_code == 0, result.output
    assert "file left on disk" in result.output
    assert "not registered" in result.output
    ini_text = (cabinet["randomizer_dir"] / "Random.ini").read_text()
    assert "Existing.mp4" not in ini_text.split("\n")[4]  # FileList= line


def test_introvideo_shuffle_dry_run_then_apply(cabinet):
    randomizer_dir = cabinet["randomizer_dir"]
    (cabinet["videos_dir"] / "Second.mp4").write_bytes(b"y" * 10)
    (randomizer_dir / "Random.ini").write_text(
        (randomizer_dir / "Random.ini").read_text()
        .replace("FileList=Existing.mp4", "FileList=Existing.mp4|Second.mp4")
        .replace("RandomList=Existing.mp4", "RandomList=Existing.mp4|Second.mp4"),
        encoding="utf-8",
    )
    before = (randomizer_dir / "Random.ini").read_text()
    runner = CliRunner()

    dry = runner.invoke(cli, ["introvideo", "shuffle", "--seed", "42"])
    assert dry.exit_code == 0, dry.output
    assert (randomizer_dir / "Random.ini").read_text() == before

    applied = runner.invoke(cli, ["introvideo", "shuffle", "--seed", "42", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert "Existing.mp4" in applied.output
    assert "Second.mp4" in applied.output


def test_introvideo_shuffle_single_video_reports_noop(cabinet):
    runner = CliRunner()
    result = runner.invoke(cli, ["introvideo", "shuffle", "--apply"])
    assert result.exit_code == 0, result.output
    assert "Nothing to shuffle" in result.output


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
