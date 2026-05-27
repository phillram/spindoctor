"""Tests for _resolve_systems — synthetic wheel filtering."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from spindoctor.cli import cli


# ─── helpers ─────────────────────────────────────────────────────────────────

def _build_layout(tmp_path: Path, systems: list[str]) -> tuple[Path, Path, Path]:
    """Create a minimal cabinet layout with the given source systems plus
    synthetic wheels already present on disk (as SpinDoctor would leave them).
    """
    hs = tmp_path / "hs"
    rl = tmp_path / "rl"
    roms = tmp_path / "roms"
    for d in (hs, rl, roms):
        d.mkdir()

    # Config
    cfg_file = tmp_path / ".spindoctor" / "config.json"
    cfg_file.parent.mkdir()
    cfg_file.write_text(
        json.dumps({
            "hyperspin_dir": str(hs),
            "rocketlauncher_dir": str(rl),
            "roms_dir": str(roms),
        }),
        encoding="utf-8",
    )

    # Main Menu.xml so get_systems can enumerate systems
    mm = hs / "Databases" / "Main Menu"
    mm.mkdir(parents=True)
    game_tags = "".join(f'<game name="{s}"/>' for s in systems)
    (mm / "Main Menu.xml").write_text(
        f"<menu>{game_tags}</menu>", encoding="utf-8"
    )

    # Databases and ROM dirs for each system + the three synthetic wheels
    all_dirs = systems + ["Favorites", "Recently Played", "Most Played"]
    for sys_name in all_dirs:
        db_dir = hs / "Databases" / sys_name
        db_dir.mkdir(parents=True, exist_ok=True)
        (db_dir / f"{sys_name}.xml").write_text(
            f'<menu><game name="game1"><description>Game 1</description></game></menu>',
            encoding="utf-8",
        )
        (roms / sys_name).mkdir(exist_ok=True)

    return hs, rl, cfg_file


# ─── _resolve_systems (unit) ──────────────────────────────────────────────────

def test_resolve_systems_all_filters_synthetic(tmp_path, monkeypatch):
    """When --all is used, synthetic wheels are silently excluded from the list."""
    from spindoctor.cli import _resolve_systems
    from spindoctor.config import load_config

    hs, rl, cfg_file = _build_layout(tmp_path, ["Super Nintendo", "MAME"])
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    config = load_config()

    result = _resolve_systems(config, system=None, all_systems=True)

    assert "Favorites" not in result
    assert "Recently Played" not in result
    assert "Most Played" not in result
    assert "Super Nintendo" in result
    assert "MAME" in result


def test_resolve_systems_explicit_synthetic_exits_nonzero(tmp_path, monkeypatch):
    """Explicitly naming a synthetic wheel with --system exits with code 1."""
    from spindoctor.cli import _resolve_systems
    from spindoctor.config import load_config
    import sys as _sys

    hs, rl, cfg_file = _build_layout(tmp_path, ["MAME"])
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    config = load_config()

    with pytest.raises(SystemExit) as exc_info:
        _resolve_systems(config, system="Favorites", all_systems=False)
    assert exc_info.value.code == 1


def test_resolve_systems_explicit_synthetic_all_three(tmp_path, monkeypatch):
    """All three synthetic wheel names are rejected when passed as --system."""
    from spindoctor.cli import _resolve_systems
    from spindoctor.config import load_config

    hs, rl, cfg_file = _build_layout(tmp_path, ["MAME"])
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)
    config = load_config()

    for name in ("Favorites", "Recently Played", "Most Played"):
        with pytest.raises(SystemExit) as exc_info:
            _resolve_systems(config, system=name, all_systems=False)
        assert exc_info.value.code == 1, f"{name} should exit 1"


# ─── CLI integration: fetch-meta skips synthetics ────────────────────────────

def test_fetch_meta_all_skips_synthetic_wheels(tmp_path, monkeypatch):
    """spindoctor fetch-meta --all prints the skip message and never processes
    synthetic wheels as individual systems.  Credentials are absent so the
    command will error — we only care the skip message appeared first."""
    hs, rl, cfg_file = _build_layout(tmp_path, ["MAME"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch-meta", "--all"])
    # The skip banner must appear
    assert "Skipping synthetic" in result.output
    # Synthetic names must not appear as bold system headers (they can appear
    # inside the "Skipping …" line itself, but that's fine)
    lines_without_skip = [
        l for l in result.output.splitlines() if "Skipping" not in l
    ]
    combined = "\n".join(lines_without_skip)
    assert "Favorites" not in combined
    assert "Most Played" not in combined
    assert "Recently Played" not in combined


def test_fetch_meta_explicit_synthetic_fails(tmp_path, monkeypatch):
    """spindoctor fetch-meta --system Favorites should exit non-zero with a hint."""
    hs, rl, cfg_file = _build_layout(tmp_path, ["MAME"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch-meta", "--system", "Favorites"])
    assert result.exit_code != 0
    assert "synthetic" in result.output.lower()


def test_fetch_media_all_skips_synthetic_wheels(tmp_path, monkeypatch):
    """spindoctor fetch-media --all prints the skip message."""
    hs, rl, cfg_file = _build_layout(tmp_path, ["MAME"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch-media", "--all"])
    assert "Skipping synthetic" in result.output
    lines_without_skip = [l for l in result.output.splitlines() if "Skipping" not in l]
    combined = "\n".join(lines_without_skip)
    assert "Favorites" not in combined
    assert "Most Played" not in combined


def test_update_db_all_skips_synthetic_wheels(tmp_path, monkeypatch):
    """spindoctor update-db --all prints the skip message."""
    hs, rl, cfg_file = _build_layout(tmp_path, ["MAME"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("spindoctor.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(cli, ["update-db", "--all"])
    assert "Skipping synthetic" in result.output
    lines_without_skip = [l for l in result.output.splitlines() if "Skipping" not in l]
    combined = "\n".join(lines_without_skip)
    assert "Favorites" not in combined
    assert "Most Played" not in combined
