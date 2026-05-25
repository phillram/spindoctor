"""CLI --verbose flag tests for the six commands added in PR #178.

Each test:
  1. Builds a minimal on-disk fixture.
  2. Invokes the command with --apply --verbose via CliRunner.
  3. Asserts that a known *full path* appears in the output — proving
     that verbose mode expands the short-name summary into full paths.

Rich wraps long paths at the terminal width, inserting bare newlines
into the output. All path assertions therefore check against a
newline-stripped version of the output (``output.replace("\\n", "")``);
the path itself never contains newlines so this is safe.

Without --verbose (not tested here) the existing unit tests already
cover the write path; those tests assert on counts and on-disk state
rather than on output strings.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.cleanup as cleanup_mod
import spindoctor.config as config_mod
import spindoctor.curate as curate_mod
import spindoctor.media_scan as media_scan_mod
import spindoctor.themes as themes_mod
from spindoctor.cli import cli
from spindoctor.config import Config, save_config
from spindoctor.database import GameEntry, HyperspinDatabase


# ─── shared helpers ──────────────────────────────────────────────────────────


def _reset(monkeypatch, tmp_path):
    """Re-home every CONFIG_DIR / manifest dir into tmp_path.

    Returns the synthetic home directory so callers can place fixture
    files under it.
    """
    home = tmp_path / "spindoctor_home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(cleanup_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(curate_mod, "CURATION_DIR", home / "curation")
    monkeypatch.setattr(media_scan_mod, "MANIFEST_DIR", home / "media_imports")
    monkeypatch.setattr(themes_mod, "THEMES_DIR", home / "themes")
    config_mod.reset_override_cache()
    return home


@pytest.fixture(autouse=True)
def _teardown_config():
    """Always reset config cache, even if the test errors."""
    yield
    config_mod.reset_override_cache()


def _flat(output: str) -> str:
    """Strip Rich's terminal-width line wrapping from captured output.

    Rich inserts bare newlines when a path exceeds the terminal width.
    Removing them lets us assert ``str(path) in _flat(result.output)``
    without caring about how wide the runner's virtual terminal is.
    The path itself never contains newlines, so this is safe.
    """
    return output.replace("\n", "")


def _make_hs(tmp_path: Path) -> Path:
    """Create the minimal HyperSpin directory layout and return its path."""
    hs = tmp_path / "hs"
    (hs / "Databases").mkdir(parents=True)
    (hs / "Media").mkdir(parents=True)
    return hs


# ─── find-misplaced --verbose ─────────────────────────────────────────────────


def test_find_misplaced_verbose_prints_full_paths(tmp_path, monkeypatch):
    """--verbose shows the full source and destination paths for each
    moved file, not just the short filename + parent folder."""
    _reset(monkeypatch, tmp_path)

    roms = tmp_path / "roms"
    hs = _make_hs(tmp_path)
    (roms / "nes").mkdir(parents=True)
    (roms / "snes").mkdir()
    # An SNES ROM sitting inside the NES folder — clearly misplaced.
    wrong = roms / "nes" / "Kart.sfc"
    wrong.write_text("rom", encoding="utf-8")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    save_config(cfg)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["find-misplaced", "--system", "nes", "--apply", "--verbose"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # Full source path must appear in the verbose output.
    assert str(wrong) in flat
    # The destination folder path must also appear (file moved to snes/).
    assert str(roms / "snes") in flat


# ─── curate --verbose ─────────────────────────────────────────────────────────


def test_curate_verbose_archive_prints_full_paths(tmp_path, monkeypatch):
    """curate --apply --verbose shows the full source → dest path for
    every archived ROM, not just the filename."""
    _reset(monkeypatch, tmp_path)

    roms = tmp_path / "roms"
    hs = _make_hs(tmp_path)
    nes = roms / "nes"
    nes.mkdir(parents=True)
    usa_rom = nes / "Mario (USA).nes"
    jpn_rom = nes / "Mario (Japan).nes"
    usa_rom.write_text("rom-usa", encoding="utf-8")
    jpn_rom.write_text("rom-jpn", encoding="utf-8")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    save_config(cfg)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["curate", "--system", "nes", "--apply", "--verbose"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # The retired ROM (Japan, lower region priority) must appear as a
    # full path; USA wins, Japan is archived.
    assert str(jpn_rom) in flat


# ─── find-orphan-media --verbose ──────────────────────────────────────────────


def test_find_orphan_media_verbose_prints_full_paths(tmp_path, monkeypatch):
    """find-orphan-media --apply --verbose prints the full path of each
    orphan file before deleting it."""
    _reset(monkeypatch, tmp_path)

    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    (roms / "nes").mkdir(parents=True)

    # Empty DB — no games → every media file is an orphan.
    db_dir = hs / "Databases" / "nes"
    db_dir.mkdir(parents=True)
    (db_dir / "nes.xml").write_text("<menu></menu>", encoding="utf-8")

    wheel_dir = hs / "Media" / "nes" / "Images" / "Wheel"
    wheel_dir.mkdir(parents=True)
    orphan = wheel_dir / "GhostGame.png"
    orphan.write_bytes(b"art")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    save_config(cfg)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["find-orphan-media", "--system", "nes", "--apply", "--verbose"],
        input="y\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # The full path of the orphan must appear in the verbose output,
    # printed before the actual deletion.
    assert str(orphan) in flat
    # The file itself must be gone (we actually ran --apply).
    assert not orphan.exists()


# ─── theme-apply --verbose ────────────────────────────────────────────────────


def test_theme_apply_verbose_prints_full_paths(tmp_path, monkeypatch):
    """theme-apply --apply --verbose logs source → target for each swap."""
    _reset(monkeypatch, tmp_path)

    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    roms.mkdir(parents=True)

    # Minimal frontend art in the cabinet.
    fe_imgs = hs / "Media" / "Frontend" / "Images"
    fe_imgs.mkdir(parents=True)
    target_file = fe_imgs / "specialA1_xbox.png"
    target_file.write_bytes(b"original-art")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    save_config(cfg)

    # Pack contains a replacement with the same filename.
    pack = tmp_path / "pack"
    pack.mkdir()
    source_file = pack / "specialA1_xbox.png"
    source_file.write_bytes(b"new-art")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["theme-apply", str(pack), "--apply", "--verbose"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # Both the source path and the target path must appear in verbose output.
    assert str(source_file) in flat
    assert str(target_file) in flat


# ─── media-scan --verbose ─────────────────────────────────────────────────────


def test_media_scan_verbose_prints_full_paths(tmp_path, monkeypatch):
    """media-scan --apply --verbose prints source → destination path for
    each imported file."""
    _reset(monkeypatch, tmp_path)

    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    (roms / "nes").mkdir(parents=True)

    # DB with one game so the scanner has something to match against.
    db_dir = hs / "Databases" / "nes"
    db_dir.mkdir(parents=True)
    db = HyperspinDatabase("nes", db_dir / "nes.xml")
    db.upsert_game(GameEntry(
        name="mario", description="Super Mario Bros.",
        manufacturer="Nintendo", year="1985", genre="Platform", rating="",
    ))
    db.save()

    # Media destination slot — must exist for the import to land.
    wheel_dir = hs / "Media" / "nes" / "Images" / "Wheel"
    wheel_dir.mkdir(parents=True)

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    save_config(cfg)

    # Source pack: a Wheels folder with a file whose stem matches "mario".
    source = tmp_path / "incoming"
    (source / "Wheels").mkdir(parents=True)
    source_file = source / "Wheels" / "mario.png"
    source_file.write_bytes(b"wheel-art")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["media-scan", str(source), "--system", "nes", "--apply", "--verbose"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # The source file path must appear in the verbose output.
    assert str(source_file) in flat
    # The destination path (under the wheel dir) must also appear.
    assert str(wheel_dir) in flat


# ─── cleanup run --verbose ────────────────────────────────────────────────────


def test_cleanup_run_verbose_prints_full_paths(tmp_path, monkeypatch):
    """cleanup run --apply --verbose prints the full path of each deleted
    file, grouped by category."""
    home = _reset(monkeypatch, tmp_path)

    hs = _make_hs(tmp_path)
    roms = tmp_path / "roms"
    roms.mkdir(parents=True)

    # Plant a fake match-cache file so the scanner has something to delete.
    cache_file = home / "match_cache" / "MAME.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("{}", encoding="utf-8")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    save_config(cfg)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cleanup", "run",
         "--include", "match-cache",
         "--apply", "--yes", "--verbose"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # The full path of the deleted cache file must appear in the output.
    assert str(cache_file) in flat
    # The file itself must be gone.
    assert not cache_file.exists()
