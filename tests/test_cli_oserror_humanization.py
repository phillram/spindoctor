"""Regression guards for OSError → humanize_oserror plumbing in the CLI.

The 2.0 audit flagged four `except (FileExistsError, OSError) as e:`
blocks in `cli.py` (`backup create`, `backup restore`, `migrate`,
`rename` + `clone`) that printed `str(e)` verbatim. On Windows that
surfaces as `[WinError 32] The process cannot access the file …` —
technically correct, useless to a cabinet owner. They now route the
exception through `spindoctor._errors.humanize_oserror`. This file
pins the wiring so a refactor can't drop the humanizer call without
the test going red.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.backup as backup_mod
import spindoctor.config as config_mod
import spindoctor.migrate as migrate_mod
from spindoctor.cli import cli
from spindoctor.config import Config, save_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _make_winerror_32(action_target: str = "Main Menu.xml") -> OSError:
    """Build a Windows-style WinError 32 OSError without needing Windows.

    `OSError` accepts a winerror argument but only retains it on
    Windows; we always attach the attribute manually so the test
    surfaces the humanizer's WinError-32 branch on every host.
    """
    e = OSError(13, "permission denied", action_target)
    e.winerror = 32
    return e


def test_backup_create_humanizes_winerror_32(tmp_path, isolated_config, monkeypatch):
    """`backup create` on a locked target should emit the friendly
    "close HyperSpin and try again" sentence rather than `[WinError 32]`.
    """
    # Minimal config so the command can resolve roms_dir / hyperspin_dir.
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    (hs_dir / "Databases" / "nes").mkdir(parents=True)
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)

    target = tmp_path / "out"

    # Stub `apply_backup` so it doesn't actually try to copy anything;
    # it just raises the WinError-32 we want to test the handler on.
    def fake_apply_backup(_plan, _config, progress_cb=None):
        raise _make_winerror_32("nes.xml")

    monkeypatch.setattr(backup_mod, "apply_backup", fake_apply_backup)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["backup", "create", "--target", str(target),
         "--include", "databases", "--apply"],
    )
    assert result.exit_code == 1
    combined = result.output or ""
    # The humanized sentence — "close them and try again" — should appear
    # somewhere in the output. Don't pin the full string so future
    # wording tweaks stay free to land.
    assert "currently in use" in combined or "close them" in combined, (
        f"raw OSError leaked instead of humanized text: {combined!r}"
    )


def test_migrate_humanizes_oserror_when_apply_raises(tmp_path, isolated_config, monkeypatch):
    """`migrate` on disk-full / locked-target should emit a humanized
    sentence rather than `[Errno 28] No space left on device`.
    """
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    (hs_dir / "Databases" / "nes").mkdir(parents=True)
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)

    target = tmp_path / "newdrive"

    def fake_apply_migration(_plan, **_kw):
        # ENOSPC — "no space left on device" → humanized as "free up some"
        import errno
        raise OSError(errno.ENOSPC, "no space left on device", str(target))

    monkeypatch.setattr(migrate_mod, "apply_migration", fake_apply_migration)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["migrate", "--target", str(target), "--apply"],
    )
    assert result.exit_code == 1
    combined = result.output or ""
    # Humanizer's ENOSPC branch mentions "space" — pin the load-bearing word.
    assert "space" in combined.lower(), (
        f"raw OSError leaked instead of humanized text: {combined!r}"
    )
    # Bare `[Errno 28]` shouldn't survive the routing.
    assert "Errno 28" not in combined
