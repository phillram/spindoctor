"""Multi-disc and m3u-playlist validation."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.discs import check_discs


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _cfg(roms_dir):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    save_config(cfg)
    return cfg


def test_no_issues_for_complete_set(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "ps1"
    sys_dir.mkdir(parents=True)
    game = sys_dir / "FF VII"
    game.mkdir()
    for n in (1, 2, 3):
        (game / f"FF VII (Disc {n}).cue").touch()
    cfg = _cfg(tmp_path / "roms")

    report = check_discs("ps1", cfg)
    assert report.issues == []
    assert report.games_checked == 1


def test_missing_intermediate_disc_flagged(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "ps1"
    sys_dir.mkdir(parents=True)
    game = sys_dir / "FF VII"
    game.mkdir()
    (game / "FF VII (Disc 1).cue").touch()
    (game / "FF VII (Disc 3).cue").touch()
    cfg = _cfg(tmp_path / "roms")

    report = check_discs("ps1", cfg)
    assert len(report.issues) == 1
    assert report.issues[0].kind == "missing-disc"
    assert "[2]" in report.issues[0].detail


def test_m3u_with_missing_target(isolated_config, tmp_path):
    sys_dir = tmp_path / "roms" / "ps1"
    sys_dir.mkdir(parents=True)
    game = sys_dir / "FF VII"
    game.mkdir()
    (game / "FF VII (Disc 1).cue").touch()
    (game / "FF VII (Disc 2).cue").touch()
    (game / "FF VII.m3u").write_text(
        "FF VII (Disc 1).cue\nFF VII (Disc 2).cue\nFF VII (Disc 3).cue\n",
        encoding="utf-8",
    )
    cfg = _cfg(tmp_path / "roms")

    report = check_discs("ps1", cfg)
    kinds = [i.kind for i in report.issues]
    assert "playlist-references-missing" in kinds


def test_missing_directory_returns_empty(isolated_config, tmp_path):
    cfg = _cfg(tmp_path / "roms")
    report = check_discs("nope", cfg)
    assert report.issues == []
    assert report.games_checked == 0
