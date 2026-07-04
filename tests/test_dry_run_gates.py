"""CLI-level dry-run gate regression tests.

For every command with a `--apply` flag, the CLI is supposed to be
dry-run by default — print the plan, change nothing on disk. The
underlying library functions (``apply_rename``, ``apply_batch_edit``,
…) are already covered by direct unit tests, but those bypass the
CLI's `--apply` guard entirely. A future refactor that flips the
default polarity, or that forgets to thread the flag through to the
library call, would be invisible to the existing suite.

This file pins the gate: for each command, set up a realistic on-disk
fixture, snapshot every file's (path, size, mtime), invoke the CLI
*without* `--apply`, and assert the snapshot is byte-identical
afterwards. The matching `--apply` invocation is *not* part of this
file — there are dedicated apply tests in test_edit / test_organize /
etc. that already cover the write path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
import spindoctor.edit as edit_mod
import spindoctor.media_scan as media_scan_mod
import spindoctor.misplaced as misplaced_mod
from spindoctor.cli import cli
from spindoctor.config import Config, save_config
from spindoctor.database import GameEntry, HyperspinDatabase


# ─── shared fixture ──────────────────────────────────────────────────────────


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Re-home every CONFIG_DIR / manifest dir into tmp so dry-run gate
    tests can't accidentally write into the developer's real
    ``~/.spindoctor/``.

    Mirrors the helpers in ``test_edit.py`` / ``test_media_scan.py``
    but covers every manifest directory that the commands-under-test
    might touch, so a stray `os.replace` somewhere wouldn't sneak past
    by writing into a different config root.
    """
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(edit_mod, "EDIT_DIR", home / "edits")
    monkeypatch.setattr(edit_mod, "RENAME_DIR", home / "renames")
    monkeypatch.setattr(
        media_scan_mod, "MANIFEST_DIR", home / "media_imports",
    )
    # `organize --restructure` writes manifests under CONFIG_DIR / "restructures"
    # — that dir is computed from the live CONFIG_DIR at call time, so
    # re-homing CONFIG_DIR above is enough.
    # `find-misplaced --apply` writes into roms_dir, not CONFIG_DIR,
    # so no extra rebinding needed.
    _ = misplaced_mod  # touch the import so the linter doesn't strip it
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _build_nes_library(tmp_path: Path) -> Config:
    """Synthetic NES system: 3 games with ROMs + wheel + snap each."""
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    db_dir = hs_dir / "Databases" / "nes"
    media_dir = hs_dir / "Media" / "nes"
    db_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    (media_dir / "Images" / "Wheel").mkdir(parents=True)
    (media_dir / "Images" / "Artwork3").mkdir(parents=True)

    games = [
        GameEntry(name="mario", description="Super Mario", manufacturer="Nintendo",
                  year="1985", genre="Platformer", rating=""),
        GameEntry(name="zelda", description="Zelda", manufacturer="Nintendo",
                  year="1986", genre="Action", rating="5"),
        GameEntry(name="contra", description="Contra", manufacturer="Konami",
                  year="1988", genre="Action", rating=""),
    ]
    for g in games:
        (roms_dir / "nes" / f"{g.name}.nes").write_text("rom", encoding="utf-8")
        (media_dir / "Images" / "Wheel" / f"{g.name}.png").write_bytes(b"wheel")
        (media_dir / "Images" / "Artwork3" / f"{g.name}.png").write_bytes(b"snap")

    db = HyperspinDatabase("nes", db_dir / "nes.xml")
    for g in games:
        db.upsert_game(g)
    db.save()

    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)
    return cfg


def _snapshot(*roots: Path) -> set:
    """Build a (path, size, content) snapshot for every file under *roots*.

    Used to assert byte-identical state across a dry-run gate. We hash
    the full bytes rather than relying on mtime because dry-run code
    can legitimately stat files without modifying them.
    """
    snap: set = set()
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                snap.add((str(p), p.read_bytes()))
    return snap


# ─── rename ──────────────────────────────────────────────────────────────────


def test_rename_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    roms_dir = Path(cfg.roms_dir)

    before = _snapshot(hs_dir, roms_dir)
    manifests_dir = isolated_config / "renames"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["rename", "--system", "nes", "--game", "mario", "--to", "mario_v2"],
    )

    assert result.exit_code == 0, result.output
    assert _snapshot(hs_dir, roms_dir) == before
    assert not (manifests_dir.exists() and list(manifests_dir.glob("*.json")))


# ─── clone ───────────────────────────────────────────────────────────────────


def test_clone_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    roms_dir = Path(cfg.roms_dir)

    before = _snapshot(hs_dir, roms_dir)
    manifests_dir = isolated_config / "renames"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["clone", "--system", "nes", "--game", "mario", "--to", "mario_clone"],
    )

    assert result.exit_code == 0, result.output
    assert _snapshot(hs_dir, roms_dir) == before
    assert not (manifests_dir.exists() and list(manifests_dir.glob("*.json")))


# ─── batch-edit ──────────────────────────────────────────────────────────────


def test_batch_edit_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)

    before = _snapshot(hs_dir)
    manifests_dir = isolated_config / "edits"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["batch-edit",
         "--system", "nes",
         "--filter", "genre=Action",
         "--set", "rating=5"],
    )

    assert result.exit_code == 0, result.output
    assert _snapshot(hs_dir) == before
    assert not (manifests_dir.exists() and list(manifests_dir.glob("*.json")))


# ─── organize --restructure ──────────────────────────────────────────────────


def test_organize_restructure_dry_run_does_not_touch_disk(
    tmp_path, isolated_config,
):
    """`organize --restructure --no-sort` without --apply must not move
    any files. `--no-sort` skips the side-effect of XML sort so the
    test stays focused on the restructure gate; sort is already
    covered by `test_sort_databases.py`.
    """
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    roms_dir = Path(cfg.roms_dir)

    before = _snapshot(hs_dir, roms_dir)
    manifests_dir = isolated_config / "restructures"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["organize", "nes", "--restructure", "--no-sort"],
    )

    assert result.exit_code == 0, result.output
    assert _snapshot(hs_dir, roms_dir) == before
    assert not (manifests_dir.exists() and list(manifests_dir.glob("*.json")))


# ─── media-scan ──────────────────────────────────────────────────────────────


def test_media_scan_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    roms_dir = Path(cfg.roms_dir)

    # Build a source media folder that media-scan will see.
    source = tmp_path / "incoming"
    (source / "Wheels").mkdir(parents=True)
    (source / "Wheels" / "mario.png").write_bytes(b"new wheel art")

    before = _snapshot(hs_dir, roms_dir)
    manifests_dir = isolated_config / "media_imports"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["media-scan", str(source), "--system", "nes"],
    )

    assert result.exit_code == 0, result.output
    assert _snapshot(hs_dir, roms_dir) == before
    assert not (manifests_dir.exists() and list(manifests_dir.glob("*.json")))


# ─── find-misplaced --apply gate (bonus — find-misplaced writes into
#     roms_dir, not CONFIG_DIR, so worth pinning) ───────────────────────────


def test_find_misplaced_dry_run_does_not_move_files(tmp_path, isolated_config):
    """`find-misplaced` (without `--apply`) reports candidates but must
    leave every file exactly where it found it. Manifest goes into
    `roms_dir/.spindoctor-misplaced-manifests/`, so the assertion has
    to cover that subtree too.
    """
    cfg = _build_nes_library(tmp_path)
    roms_dir = Path(cfg.roms_dir)
    # Plant a "misplaced" ROM — an SNES file inside the NES folder.
    (roms_dir / "snes").mkdir()
    (roms_dir / "nes" / "kart.sfc").write_text("rom", encoding="utf-8")

    before = _snapshot(roms_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["find-misplaced", "--system", "nes"])

    assert result.exit_code == 0, result.output
    assert _snapshot(roms_dir) == before


# ─── fav clear dry-run gate ──────────────────────────────────────────────────


def _build_fav_wheel(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Write a small Favorites wheel to disk (DB XML + one media file).

    Returns (hs_dir, fav_json_path) so callers can snapshot both.
    """
    import json
    import spindoctor.favorites as fav_mod

    hs_dir = tmp_path / "hs"
    roms_dir = tmp_path / "roms"
    (roms_dir / "nes").mkdir(parents=True)

    # Source system
    db_dir = hs_dir / "Databases" / "nes"
    db_dir.mkdir(parents=True)
    (db_dir / "nes.xml").write_text(
        '<menu><game name="mario"><description>Mario</description></game></menu>',
        encoding="utf-8",
    )
    # Media for the source game
    wheel_dir = hs_dir / "Media" / "nes" / "Images" / "Wheel"
    wheel_dir.mkdir(parents=True)
    (wheel_dir / "mario.png").write_bytes(b"wheel")

    # Pre-existing Favorites wheel artifacts
    fav_db = hs_dir / "Databases" / "Favorites"
    fav_db.mkdir(parents=True)
    (fav_db / "Favorites.xml").write_text(
        '<menu><game name="mario"><description>Mario</description></game></menu>',
        encoding="utf-8",
    )
    fav_media = hs_dir / "Media" / "Favorites" / "Images" / "Wheel"
    fav_media.mkdir(parents=True)
    (fav_media / "mario.png").write_bytes(b"wheel")

    # Config
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)

    # Favorites store
    fav_json = tmp_path / "favorites.json"
    payload = {
        "target_system": "Favorites",
        "entries": [
            {
                "system": "nes",
                "rom_name": "mario",
                "display_name": "Mario",
                "added": "2026-01-01T00:00:00",
            }
        ],
    }
    fav_json.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(fav_mod, "FAVORITES_FILE", fav_json)

    return hs_dir, fav_json


def test_fav_clear_dry_run_does_not_touch_disk(tmp_path, isolated_config, monkeypatch):
    """`fav clear` (without --apply) must not modify any file on disk."""
    hs_dir, fav_json = _build_fav_wheel(tmp_path, monkeypatch)

    before = _snapshot(hs_dir, tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["fav", "clear"])

    assert result.exit_code == 0, result.output
    assert "[DRY RUN]" in result.output or "DRY RUN" in result.output
    assert _snapshot(hs_dir, tmp_path) == before


def test_fav_clear_apply_removes_artifacts(tmp_path, isolated_config, monkeypatch):
    """`fav clear --apply` removes wheel artifacts and empties the store."""
    import json

    hs_dir, fav_json = _build_fav_wheel(tmp_path, monkeypatch)
    fav_db_xml = hs_dir / "Databases" / "Favorites" / "Favorites.xml"
    fav_media_file = hs_dir / "Media" / "Favorites" / "Images" / "Wheel" / "mario.png"

    assert fav_db_xml.exists()
    assert fav_media_file.exists()

    runner = CliRunner()
    result = runner.invoke(cli, ["fav", "clear", "--apply"])

    assert result.exit_code == 0, result.output
    assert not fav_db_xml.exists(), "Favorites DB XML should have been removed"
    assert not fav_media_file.exists(), "Favorites media file should have been removed"
    # Store should be empty
    store_data = json.loads(fav_json.read_text())
    assert store_data["entries"] == [], "Favorites store should be emptied"


# ─── recent clear dry-run gate ───────────────────────────────────────────────


def _build_recent_wheel(tmp_path: Path) -> Path:
    """Write a small Recently Played wheel to disk.  Returns hs_dir."""
    hs_dir = tmp_path / "hs"
    rp_db = hs_dir / "Databases" / "Recently Played"
    rp_db.mkdir(parents=True)
    (rp_db / "Recently Played.xml").write_text(
        '<menu><game name="mario"><description>Mario</description></game></menu>',
        encoding="utf-8",
    )
    rp_media = hs_dir / "Media" / "Recently Played" / "Images" / "Wheel"
    rp_media.mkdir(parents=True)
    (rp_media / "mario.png").write_bytes(b"wheel")

    roms_dir = tmp_path / "roms"
    roms_dir.mkdir(parents=True)
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)
    return hs_dir


def test_recent_clear_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    """`recent clear` (without --apply) must not modify any file on disk."""
    hs_dir = _build_recent_wheel(tmp_path)
    before = _snapshot(hs_dir)

    runner = CliRunner()
    result = runner.invoke(cli, ["recent", "clear"])

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert _snapshot(hs_dir) == before


def test_recent_clear_apply_removes_artifacts(tmp_path, isolated_config):
    """`recent clear --apply` removes wheel artifacts from disk."""
    hs_dir = _build_recent_wheel(tmp_path)
    rp_db_xml = hs_dir / "Databases" / "Recently Played" / "Recently Played.xml"
    rp_media_file = hs_dir / "Media" / "Recently Played" / "Images" / "Wheel" / "mario.png"

    assert rp_db_xml.exists()
    assert rp_media_file.exists()

    runner = CliRunner()
    result = runner.invoke(cli, ["recent", "clear", "--apply"])

    assert result.exit_code == 0, result.output
    assert not rp_db_xml.exists(), "Recently Played DB XML should have been removed"
    assert not rp_media_file.exists(), "Recently Played media file should have been removed"


# ─── stats-report clear-wheel dry-run gate ───────────────────────────────────


def _build_most_played_wheel(tmp_path: Path) -> Path:
    """Write a small Most Played wheel to disk.  Returns hs_dir."""
    hs_dir = tmp_path / "hs"
    mp_db = hs_dir / "Databases" / "Most Played"
    mp_db.mkdir(parents=True)
    (mp_db / "Most Played.xml").write_text(
        '<menu><game name="mario"><description>Mario</description></game></menu>',
        encoding="utf-8",
    )
    mp_media = hs_dir / "Media" / "Most Played" / "Images" / "Wheel"
    mp_media.mkdir(parents=True)
    (mp_media / "mario.png").write_bytes(b"wheel")

    roms_dir = tmp_path / "roms"
    roms_dir.mkdir(parents=True)
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)
    return hs_dir


def test_stats_report_clear_wheel_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    """`stats-report clear-wheel` (without --apply) must not modify disk."""
    hs_dir = _build_most_played_wheel(tmp_path)
    before = _snapshot(hs_dir)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats-report", "clear-wheel"])

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert _snapshot(hs_dir) == before


def test_stats_report_clear_wheel_apply_removes_artifacts(tmp_path, isolated_config):
    """`stats-report clear-wheel --apply` removes wheel artifacts from disk."""
    hs_dir = _build_most_played_wheel(tmp_path)
    mp_db_xml = hs_dir / "Databases" / "Most Played" / "Most Played.xml"
    mp_media_file = hs_dir / "Media" / "Most Played" / "Images" / "Wheel" / "mario.png"

    assert mp_db_xml.exists()
    assert mp_media_file.exists()

    runner = CliRunner()
    result = runner.invoke(cli, ["stats-report", "clear-wheel", "--apply"])

    assert result.exit_code == 0, result.output
    assert not mp_db_xml.exists(), "Most Played DB XML should have been removed"
    assert not mp_media_file.exists(), "Most Played media file should have been removed"


# ─── media-add ───────────────────────────────────────────────────────────────


def _media_add_fixture(tmp_path):
    cfg = _build_nes_library(tmp_path)
    src = tmp_path / "incoming" / "mario_trailer.mp4"
    src.parent.mkdir()
    src.write_bytes(b"fake mp4 bytes")
    return cfg, src


def test_media_add_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    cfg, src = _media_add_fixture(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    before = _snapshot(hs_dir)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["media-add", "--system", "nes", "--game", "mario",
         "--type", "video", "--file", str(src)],
    )

    assert result.exit_code == 0, result.output
    assert "Would copy" in result.output
    assert "--apply" in result.output
    assert _snapshot(hs_dir) == before
    assert src.exists(), "dry-run must not move/consume the source file"


def test_media_add_apply_copies_file(tmp_path, isolated_config):
    cfg, src = _media_add_fixture(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["media-add", "--system", "nes", "--game", "mario",
         "--type", "video", "--file", str(src), "--apply"],
    )

    assert result.exit_code == 0, result.output
    copied = list(hs_dir.rglob("mario.mp4"))
    assert copied, f"expected mario.mp4 under {hs_dir}, output: {result.output}"
    assert copied[0].read_bytes() == b"fake mp4 bytes"


# ─── pc-rename ───────────────────────────────────────────────────────────────


def _pc_system_fixture(tmp_path, monkeypatch):
    """Synthetic PC Games system with an override entry and one game."""
    import spindoctor.pc_titles as pc_titles_mod
    monkeypatch.setattr(
        pc_titles_mod, "CACHE_DIR", tmp_path / "pc_titles_cache",
    )
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    rl_dir = tmp_path / "rl"
    pc_dir = roms_dir / "PC Games"
    pc_dir.mkdir(parents=True)
    (pc_dir / "Hades.lnk").touch()
    (hs_dir / "Databases").mkdir(parents=True)
    (rl_dir / "Modules").mkdir(parents=True)
    cfg = Config(
        roms_dir=str(roms_dir),
        hyperspin_dir=str(hs_dir),
        rocketlauncher_dir=str(rl_dir),
        system_overrides={
            "PC Games": {
                "rom_extensions": [".exe", ".lnk"],
                "recursive_scan": True,
                "title_strategy": "smart",
                "emulator": "PCLauncher",
            },
        },
    )
    save_config(cfg)
    config_mod.reset_override_cache()
    return cfg, rl_dir


def test_pc_rename_dry_run_does_not_write_inis(tmp_path, isolated_config, monkeypatch):
    cfg, rl_dir = _pc_system_fixture(tmp_path, monkeypatch)
    before = _snapshot(rl_dir)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["pc-rename", "PC Games", "--no-interactive"],
    )

    assert result.exit_code == 0, result.output
    assert "Would write" in result.output
    assert "--apply" in result.output
    assert _snapshot(rl_dir) == before


def test_pc_rename_apply_writes_inis(tmp_path, isolated_config, monkeypatch):
    cfg, rl_dir = _pc_system_fixture(tmp_path, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["pc-rename", "PC Games", "--no-interactive", "--apply"],
    )

    assert result.exit_code == 0, result.output
    inis = list((rl_dir / "Modules" / "PCLauncher").rglob("*.ini"))
    assert inis, f"expected PCLauncher INI(s) under {rl_dir}, output: {result.output}"


# ─── generate-config ─────────────────────────────────────────────────────────


def test_generate_config_dry_run_does_not_touch_disk(tmp_path, isolated_config):
    """generate-config's dry-run preview must run cleanly and write nothing.

    Regression test for the 2.9.1 NameError: the dry-run branch called
    ``re.search`` for the MAME-variant fallback without ``re`` being
    imported in cli.py, so the *default* invocation crashed for any
    config with ``roms_dir`` set while ``--apply`` (which skips that
    branch) worked. Library-level tests in test_rl_system_ini.py never
    caught it because they bypass the CLI. Includes a MAME-named system
    so both ``re.search`` call sites actually execute.
    """
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    roms_dir = Path(cfg.roms_dir)

    # A MAME-variant system exercises the fallback that inspects the
    # system name; an existing RL dir exercises the existing-INI probes.
    mame_db_dir = hs_dir / "Databases" / "MAME 2003"
    mame_db_dir.mkdir(parents=True)
    db = HyperspinDatabase("MAME 2003", mame_db_dir / "MAME 2003.xml")
    db.upsert_game(GameEntry(name="pacman", description="Pac-Man"))
    db.save()
    (roms_dir / "MAME").mkdir()

    rl_dir = tmp_path / "rl"
    (rl_dir / "Settings").mkdir(parents=True)
    cfg.rocketlauncher_dir = str(rl_dir)
    save_config(cfg)
    config_mod.reset_override_cache()

    before = _snapshot(hs_dir, roms_dir, rl_dir)

    runner = CliRunner()
    result = runner.invoke(cli, ["generate-config"])

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert _snapshot(hs_dir, roms_dir, rl_dir) == before
