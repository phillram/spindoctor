"""Local media scan & audit: detection, matching, import, undo."""
from __future__ import annotations

from pathlib import Path

import pytest

import spindoctor.config as config_mod
import spindoctor.media_scan as media_scan_mod
from spindoctor.config import Config, save_config
from spindoctor.media_scan import (
    detect_media_type, import_media, list_manifests,
    match_to_database, scan_local_media, undo_import,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    # Redirect manifest dir into the temp tree as well
    monkeypatch.setattr(
        media_scan_mod, "MANIFEST_DIR",
        tmp_path / "spindoctor_home" / "media_imports",
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _write_db(hs_dir: Path, system: str, games: list[str]) -> None:
    db_dir = hs_dir / "Databases" / system
    db_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        f"<game name=\"{g}\"><description>{g}</description></game>"
        for g in games
    )
    (db_dir / f"{system}.xml").write_text(
        f"<menu>{body}</menu>", encoding="utf-8"
    )


def _build_layout(tmp_path: Path) -> tuple[Config, Path]:
    """Synthetic HyperSpin tree + a source media folder.

    Returns (config, source_dir). The source dir contains:
      Wheels/Mario.png         — matches game "Mario" (empty slot)
      Snaps/Sonic.png          — matches game "Sonic" (empty slot)
      Wheels/Luigi.png         — matches game "Luigi" but slot already filled
      Random/Foo.png           — image with no folder hint → unknown_type
      Random/NoSuchGame.mp4    — video, no DB match → unmatched
      Junk/notes.txt           — not media at all (skipped)
    """
    hs = tmp_path / "hs"
    roms_dir = tmp_path / "roms"
    (roms_dir / "nes").mkdir(parents=True)

    _write_db(hs, "nes", ["Mario", "Sonic", "Luigi"])

    # Pre-fill the Luigi wheel so it counts as a "replacement".
    luigi_slot = hs / "Media" / "nes" / "Images" / "Wheel"
    luigi_slot.mkdir(parents=True)
    (luigi_slot / "Luigi.png").write_text("existing", encoding="utf-8")

    src = tmp_path / "source"
    (src / "Wheels").mkdir(parents=True)
    (src / "Snaps").mkdir(parents=True)
    (src / "Random").mkdir(parents=True)
    (src / "Junk").mkdir(parents=True)
    (src / "Wheels" / "Mario.png").write_text("mario-wheel", encoding="utf-8")
    (src / "Wheels" / "Luigi.png").write_text("luigi-wheel", encoding="utf-8")
    (src / "Snaps" / "Sonic.png").write_text("sonic-snap", encoding="utf-8")
    (src / "Random" / "Foo.png").write_text("ambig", encoding="utf-8")
    (src / "Random" / "NoSuchGame.mp4").write_text("video", encoding="utf-8")
    (src / "Junk" / "notes.txt").write_text("not media", encoding="utf-8")

    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs)
    cfg.match_threshold = 0.80
    save_config(cfg)
    return cfg, src


# ─── detection ────────────────────────────────────────────────────────────────

def test_detect_type_from_folder_hint():
    assert detect_media_type(Path("Wheels/Mario.png")) == "wheel"
    assert detect_media_type(Path("logo/foo.jpg")) == "wheel"
    assert detect_media_type(Path("Snaps/sub/x.png")) == "snap"
    assert detect_media_type(Path("Backgrounds/bg.jpg")) == "background"
    assert detect_media_type(Path("BoxArt/box.png")) == "artwork"
    assert detect_media_type(Path("Titles/x.png")) == "title"


def test_detect_type_from_extension_only():
    assert detect_media_type(Path("anything/x.mp4")) == "video"
    assert detect_media_type(Path("anything/x.mp3")) == "sound"
    assert detect_media_type(Path("anything/x.zip")) == "theme"


def test_detect_type_returns_none_for_ambiguous_image():
    # A bare image with no folder hint is ambiguous → unknown.
    assert detect_media_type(Path("random/x.png")) is None


def test_detect_type_returns_none_for_unrecognised_extension():
    assert detect_media_type(Path("Wheels/x.txt")) is None


# ─── scanning ─────────────────────────────────────────────────────────────────

def test_scan_recursive_picks_up_media_files(tmp_path):
    src = tmp_path / "src"
    (src / "Wheels").mkdir(parents=True)
    (src / "Wheels" / "a.png").write_text("a", encoding="utf-8")
    (src / "notes.txt").write_text("ignored", encoding="utf-8")
    files = scan_local_media(src)
    assert len(files) == 1
    assert files[0].path.name == "a.png"
    assert files[0].media_type == "wheel"


def test_scan_no_recursive_only_top_level(tmp_path):
    src = tmp_path / "src"
    (src / "Wheels").mkdir(parents=True)
    (src / "Wheels" / "a.png").write_text("a", encoding="utf-8")
    (src / "top.mp4").write_text("v", encoding="utf-8")
    files = scan_local_media(src, recursive=False)
    names = {f.path.name for f in files}
    assert names == {"top.mp4"}


# ─── matching / bucketing ─────────────────────────────────────────────────────

def test_match_buckets(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg)

    matched_games = {sm.game_name for sm in rep.matched}
    replacement_games = {sm.game_name for sm in rep.replacement}
    unmatched_names = {sm.local.path.name for sm in rep.unmatched}
    unknown_names = {sm.local.path.name for sm in rep.unknown_type}

    assert "Mario" in matched_games
    assert "Sonic" in matched_games
    assert replacement_games == {"Luigi"}
    assert "NoSuchGame.mp4" in unmatched_names
    assert "Foo.png" in unknown_names


def test_match_respects_type_filter(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg, types=["wheel"])
    # Only wheel files end up in matched/replacement
    for sm in rep.matched + rep.replacement:
        assert sm.local.media_type == "wheel"
    # The Sonic snap is filtered out entirely (not matched, not replacement)
    games = {sm.game_name for sm in rep.matched + rep.replacement}
    assert "Sonic" not in games


# ─── import + undo ────────────────────────────────────────────────────────────

def test_import_copy_then_undo_round_trip(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg)

    result = import_media(rep, cfg, action="copy")

    # Mario + Sonic are the two matched targets
    assert len(result.imported) == 2
    targets = [t for _, t in result.imported]
    for t in targets:
        assert t.exists()
    assert result.manifest_path is not None
    assert result.manifest_path.exists()

    # Source files are still present (copy, not move)
    assert (src / "Wheels" / "Mario.png").exists()

    # Undo removes the copies and the manifest
    summary = undo_import(result.manifest_path)
    assert summary["reverted"] == 2
    for t in targets:
        assert not t.exists()
    assert not result.manifest_path.exists()


def test_import_skips_existing_without_overwrite(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg)

    # Pre-fill Mario's wheel so it lands in 'replacement' on a re-scan.
    mario_slot = (
        Path(cfg.hyperspin_dir) / "Media" / "nes" / "Images" / "Wheel" / "Mario.png"
    )
    mario_slot.parent.mkdir(parents=True, exist_ok=True)
    mario_slot.write_text("preexisting", encoding="utf-8")

    rep = match_to_database(files, "nes", cfg)
    # Without --overwrite (include_replacements=False) we don't touch them.
    result = import_media(rep, cfg, action="copy")
    # Pre-existing content should be untouched
    assert mario_slot.read_text(encoding="utf-8") == "preexisting"
    # Mario is now in replacement bucket, only Sonic should import
    assert len(result.imported) == 1
    assert result.imported[0][1].name == "Sonic.png"


def test_import_overwrite_replaces_existing(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg)

    # Luigi is in the replacement bucket; with overwrite + include_replacements
    # we should overwrite the slot.
    result = import_media(
        rep, cfg, action="copy", overwrite=True, include_replacements=True,
    )
    luigi_slot = (
        Path(cfg.hyperspin_dir) / "Media" / "nes" / "Images" / "Wheel" / "Luigi.png"
    )
    assert luigi_slot.read_text(encoding="utf-8") == "luigi-wheel"
    # Both matched and replacement entries imported (Mario, Sonic, Luigi)
    assert len(result.imported) == 3


def test_list_manifests_reflects_imports(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg)
    result = import_media(rep, cfg, action="copy")
    manifests = list_manifests()
    assert result.manifest_path in manifests


def test_import_move_then_undo_restores_source(isolated_config, tmp_path):
    cfg, src = _build_layout(tmp_path)
    files = scan_local_media(src)
    rep = match_to_database(files, "nes", cfg)

    mario_src = src / "Wheels" / "Mario.png"
    assert mario_src.exists()
    result = import_media(rep, cfg, action="move")
    assert not mario_src.exists()  # moved away

    summary = undo_import(result.manifest_path)
    assert summary["reverted"] == len(result.imported)
    assert mario_src.exists()
