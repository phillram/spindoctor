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
        db.add_game(g)
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
