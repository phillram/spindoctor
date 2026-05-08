"""Tests for spindoctor.themes — the HyperSpin frontend art scanner.

Builds a fake `<HyperSpin>/Media/...` tree under tmp_path and verifies
the scanner finds every overlay file in the right scope/bucket without
walking off into per-game theme zips or random images.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spindoctor import themes
from spindoctor.config import Config


def _make_cabinet(tmp_path: Path) -> Config:
    """Spin up a minimal HyperSpin layout and return a matching Config."""
    hs = tmp_path / "hyperspin"
    media = hs / "Media"
    # Frontend universal art.
    fe_imgs = media / "Frontend" / "Images"
    fe_imgs.mkdir(parents=True)
    (fe_imgs / "specialA1_xbox.png").write_bytes(b"x")
    (fe_imgs / "ignoreme.txt").write_text("not an image")

    # Per-system Special A.
    nes_special_a = media / "Nintendo Entertainment System" / "Images" / "Special A"
    nes_special_a.mkdir(parents=True)
    (nes_special_a / "select_button.png").write_bytes(b"sel")
    # Nested sub-folder — should be picked up by rglob.
    (nes_special_a / "alt").mkdir()
    (nes_special_a / "alt" / "alt_select.jpg").write_bytes(b"alt")

    # Per-system Special B.
    snes_special_b = media / "Super Nintendo Entertainment System" / "Images" / "Special B"
    snes_special_b.mkdir(parents=True)
    (snes_special_b / "start_button.png").write_bytes(b"st")

    # Per-game theme — we should NOT walk into Themes/ here; that's
    # per-game art, not frontend overlays.
    game_themes = media / "Nintendo Entertainment System" / "Themes"
    game_themes.mkdir(parents=True)
    (game_themes / "Mario.zip").write_bytes(b"PK\x03\x04")  # zip magic

    return Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(hs),
        emulators_dir=str(tmp_path / "emulators"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )


# ─── scan_frontend_art ────────────────────────────────────────────────────────

def test_scan_finds_frontend_and_special_buckets(tmp_path):
    cfg = _make_cabinet(tmp_path)
    assets = themes.scan_frontend_art(cfg)
    names = {a.path.name for a in assets}
    # Frontend universal + per-system Special A + nested + Special B.
    assert "specialA1_xbox.png" in names
    assert "select_button.png" in names
    assert "alt_select.jpg" in names
    assert "start_button.png" in names
    # Per-game theme zip must not leak in — that's not a frontend
    # overlay even though it lives under Media/.
    assert "Mario.zip" not in names
    # The .txt sentinel must not leak in either.
    assert "ignoreme.txt" not in names


def test_scan_returns_empty_when_hyperspin_dir_unset(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir="",
        emulators_dir=str(tmp_path / "emulators"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    # Empty hyperspin_dir is the "freshly installed, not configured
    # yet" state; we degrade silently rather than raising.
    assert themes.scan_frontend_art(cfg) == []


def test_scan_returns_empty_when_media_missing(tmp_path):
    hs = tmp_path / "hyperspin"
    hs.mkdir()
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(hs),
        emulators_dir=str(tmp_path / "emulators"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    # hyperspin_dir set but no Media/ folder yet — same story, no
    # crash, just nothing to report.
    assert themes.scan_frontend_art(cfg) == []


def test_scan_records_scope_and_bucket(tmp_path):
    cfg = _make_cabinet(tmp_path)
    assets = themes.scan_frontend_art(cfg)
    by_name = {a.path.name: a for a in assets}
    # Universal Frontend art lives in scope "Frontend".
    assert by_name["specialA1_xbox.png"].scope == "Frontend"
    assert by_name["specialA1_xbox.png"].bucket == "Frontend / Images"
    # Per-system art carries the system folder name as scope and the
    # Special A/B subfolder as bucket — that's how the GUI groups.
    assert by_name["select_button.png"].scope == "Nintendo Entertainment System"
    assert by_name["select_button.png"].bucket == "Special A"
    assert by_name["start_button.png"].bucket == "Special B"


# ─── filter_assets ────────────────────────────────────────────────────────────

def test_filter_by_system(tmp_path):
    cfg = _make_cabinet(tmp_path)
    assets = themes.scan_frontend_art(cfg)
    nes_only = themes.filter_assets(
        assets, system="Nintendo Entertainment System",
    )
    scopes = {a.scope for a in nes_only}
    assert scopes == {"Nintendo Entertainment System"}


def test_filter_by_keyword_is_case_insensitive(tmp_path):
    cfg = _make_cabinet(tmp_path)
    assets = themes.scan_frontend_art(cfg)
    # Filename has uppercase A in "specialA1" — make sure lowercase
    # search still hits it. This is the "Type 'xbox' to find Xbox
    # glyphs" UX from the GUI.
    hits = themes.filter_assets(assets, keyword="XBOX")
    names = {a.path.name for a in hits}
    assert "specialA1_xbox.png" in names


def test_filter_with_empty_keyword_returns_all(tmp_path):
    cfg = _make_cabinet(tmp_path)
    assets = themes.scan_frontend_art(cfg)
    # Empty / None keyword should not filter anything out — covers the
    # case where the GUI filter box is empty.
    assert len(themes.filter_assets(assets, keyword=None)) == len(assets)


# ─── known glyph keywords ─────────────────────────────────────────────────────

def test_known_glyph_keywords_cover_common_console_families():
    """Light sanity check on the keyword list — if someone deletes the
    common controller families by accident the GUI filter dropdown
    (future) would lose its predictability."""
    kw = {k.lower() for k in themes.KNOWN_GLYPH_KEYWORDS}
    for required in ("xbox", "playstation", "arcade", "controller"):
        assert required in kw, f"{required} missing from KNOWN_GLYPH_KEYWORDS"


# ─── has_swf_themes ───────────────────────────────────────────────────────────

def test_has_swf_themes_detects_default_zip(tmp_path):
    hs = tmp_path / "hyperspin"
    main_themes = hs / "Media" / "Main Menu" / "Themes"
    main_themes.mkdir(parents=True)
    (main_themes / "default.zip").write_bytes(b"PK")
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(hs),
        emulators_dir=str(tmp_path / "emulators"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    # Cabinet owners with stock HyperSpin themes have default.zip —
    # we want the warning to fire so they know SpinDoctor can't edit
    # those.
    assert themes.has_swf_themes(cfg) is True


def test_has_swf_themes_false_when_no_main_menu_folder(tmp_path):
    cfg = _make_cabinet(tmp_path)
    # The fake cabinet has no Main Menu/Themes directory at all, so
    # the heuristic must say "no SWF concern".
    assert themes.has_swf_themes(cfg) is False
