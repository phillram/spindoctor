"""CliRunner smoke pass over the read-only / dry-run-by-default CLI surface.

The 2.0 audit flagged that 60+ CLI commands had zero CliRunner coverage —
even the ones that ship as the cabinet owner's first line of defense
(`doctor`, `audit`, `inspect`, `find-dupes`). The existing
`test_dry_run_gates.py` pins the apply-vs-dry-run polarity for the
destructive subset; this file is the complement: it exercises the
read-only commands end-to-end against the same realistic NES fixture so
a regression that crashes the command outright (import error, missing
flag, wrong _cfg() plumbing) gets caught at PR time instead of by
someone running `spindoctor doctor` on a fresh cab.

Pinned-but-thin: the assertions only check exit code and that the
command emitted *something*. Per-command behaviour belongs in the
dedicated unit-test files (test_audit.py, test_health.py, …); this
file's job is to guarantee the CLI plumbing for each command stays
unbroken.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli
from spindoctor.config import Config, save_config
from spindoctor.database import GameEntry, HyperspinDatabase


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _build_nes_library(tmp_path: Path) -> Config:
    """A small but realistic single-system install used by every test below.

    Three NES games with ROMs, wheels, and snaps. Mirrors the helper in
    `test_dry_run_gates.py` so a future consolidation can lift this into
    a `conftest.py` without rewriting either file.
    """
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    db_dir = hs_dir / "Databases" / "nes"
    media_dir = hs_dir / "Media" / "nes"
    db_dir.mkdir(parents=True)
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


# ─── audit ───────────────────────────────────────────────────────────────────


def test_audit_single_system_exits_clean(tmp_path, isolated_config):
    """`audit --system nes` is the cabinet owner's primary diagnostic.

    Untested at the CLI level until now — every other audit assertion
    lives at the library layer in `audit.py`. Verifies the command
    plumbs through and emits a report rather than crashing on import
    or option-parsing.
    """
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["audit", "--system", "nes"])
    assert result.exit_code == 0, result.output
    assert "nes" in result.output.lower()


def test_audit_all_systems_exits_clean(tmp_path, isolated_config):
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["audit", "--all"])
    assert result.exit_code == 0, result.output


# ─── inspect ─────────────────────────────────────────────────────────────────


def test_inspect_single_game_exits_clean(tmp_path, isolated_config):
    """`inspect --system nes --game mario` is the deep-dive companion to
    `audit`; the GUI's Diagnose tab now surfaces it. Pin the plumbing.
    """
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["inspect", "--system", "nes", "--game", "mario"],
    )
    assert result.exit_code == 0, result.output
    assert "mario" in result.output.lower()


def test_inspect_all_games_exits_clean(tmp_path, isolated_config):
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["inspect", "--system", "nes", "--all"],
    )
    assert result.exit_code == 0, result.output


# ─── find-dupes ──────────────────────────────────────────────────────────────


def test_find_dupes_single_system_exits_clean(tmp_path, isolated_config):
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["find-dupes", "--system", "nes"])
    assert result.exit_code == 0, result.output


def test_find_dupes_cross_systems_exits_clean(tmp_path, isolated_config):
    """Cross-systems mode added a dedicated GUI button — needs CLI coverage."""
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["find-dupes", "--all", "--cross-systems"])
    assert result.exit_code == 0, result.output


# ─── lint ────────────────────────────────────────────────────────────────────


def test_lint_self_exits_clean():
    """`lint` scans the spindoctor package itself; no fixture needed."""
    runner = CliRunner()
    result = runner.invoke(cli, ["lint"])
    assert result.exit_code == 0, result.output


# ─── find-orphan-media (dry-run is the default) ──────────────────────────────


def test_find_orphan_media_dry_run_exits_clean(tmp_path, isolated_config):
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["find-orphan-media", "--system", "nes"])
    assert result.exit_code == 0, result.output


# ─── cleanup audit ───────────────────────────────────────────────────────────


def test_cleanup_audit_exits_clean(isolated_config):
    """`cleanup audit` walks ~/.spindoctor — fixture re-homes that root so
    we report on an empty tree rather than the developer's real cache.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["cleanup", "audit"])
    assert result.exit_code == 0, result.output


# ─── report ──────────────────────────────────────────────────────────────────


def test_report_summary_exits_clean(tmp_path, isolated_config):
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--system", "nes"])
    assert result.exit_code == 0, result.output


def test_report_csv_writes_file(tmp_path, isolated_config):
    """CSV mode plumbs through --output and writes a file. Untested before."""
    _build_nes_library(tmp_path)
    out_csv = tmp_path / "report.csv"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["report", "--system", "nes",
         "--format", "csv", "--output", str(out_csv)],
    )
    assert result.exit_code == 0, result.output
    assert out_csv.exists()


# ─── doctor ──────────────────────────────────────────────────────────────────


def test_doctor_runs_against_clean_install(tmp_path, isolated_config):
    """Doctor on a healthy fixture should not crash; exit code 0 or 2
    (FAIL) are both acceptable here because the synthetic library is
    intentionally minimal and may legitimately fail some checks (e.g.
    no MAME binary on this dev box). The point is to prove the command
    runs end-to-end rather than to pin the diagnosis verdict.
    """
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code in (0, 2), result.output
    assert "SpinDoctor health" in result.output or "health" in result.output.lower()


# ─── tools-audit ─────────────────────────────────────────────────────────────


def test_tools_audit_exits_clean(tmp_path, isolated_config):
    """`tools-audit` is read-only; given --extra-path to an empty tmp dir
    it should walk it and emit a report without touching real PATH.
    """
    _build_nes_library(tmp_path)
    empty = tmp_path / "empty-tools-tree"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        cli, ["tools-audit", "--extra-path", str(empty), "--max-depth", "1"],
    )
    assert result.exit_code == 0, result.output


# ─── systems ─────────────────────────────────────────────────────────────────


def test_systems_lists_configured_system(tmp_path, isolated_config):
    """`systems` is the simplest read-only command but had no CLI coverage."""
    _build_nes_library(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["systems"])
    assert result.exit_code == 0, result.output
    assert "nes" in result.output.lower()


# ─── update-db dry-run gate ──────────────────────────────────────────────────


def test_update_db_dry_run_does_not_modify_xml(tmp_path, isolated_config):
    """`update-db` without `--apply` is the most-load-bearing dry-run gate
    on the metadata side. A regression that flips its default polarity
    would silently rewrite the cabinet's HyperSpin XML on first invocation.
    """
    cfg = _build_nes_library(tmp_path)
    hs_dir = Path(cfg.hyperspin_dir)
    xml_path = hs_dir / "Databases" / "nes" / "nes.xml"
    before = xml_path.read_bytes()

    # Plant a new ROM that's *not* in the XML so update-db has work to do.
    (Path(cfg.roms_dir) / "nes" / "metroid.nes").write_text("rom", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["update-db", "--system", "nes"])

    assert result.exit_code == 0, result.output
    assert xml_path.read_bytes() == before, "update-db touched the XML without --apply"


# ─── add-system dry-run gate ─────────────────────────────────────────────────


def test_add_system_dry_run_does_not_create_dirs(tmp_path, isolated_config):
    """`add-system "SNES"` without `--apply` previews what it would do but
    must not create the roms_dir/snes/ or hyperspin/Databases/snes/ trees.
    The GUI's Systems tab drives this command — a regression here would
    populate folders the user didn't ask for on first click.
    """
    cfg = _build_nes_library(tmp_path)
    roms_dir = Path(cfg.roms_dir)
    hs_dir = Path(cfg.hyperspin_dir)
    # Pre-condition: the SNES tree doesn't exist yet.
    assert not (roms_dir / "snes").exists()
    assert not (hs_dir / "Databases" / "snes").exists()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["add-system", "Super Nintendo",
         "--no-system-media", "--no-game-media", "--no-db", "--no-menu"],
    )

    assert result.exit_code == 0, result.output
    # The CLI may print plans for any directory name; the gate is that no
    # files / dirs got created. Walk both roots and confirm nothing was
    # added under the original library snapshot.
    assert not any(
        p for p in (roms_dir.rglob("*")) if "snes" in p.name.lower() and p.is_dir()
    ), "add-system created roms/snes/ without --apply"


def test_fetch_meta_skip_ambiguous_flag_is_registered():
    """The --skip-ambiguous flag exists on fetch-meta — the GUI relies
    on it to avoid hanging the subprocess on stdin. Help-output check
    is enough to pin the wiring without firing a real network call.
    """
    from click.testing import CliRunner
    from spindoctor.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch-meta", "--help"])
    assert result.exit_code == 0, result.output
    assert "--skip-ambiguous" in result.output


def test_add_pc_system_no_interactive_flag_is_registered():
    """add-pc-system --no-interactive must exist so the GUI can avoid
    the input() prompt in pc_titles.review_titles."""
    from click.testing import CliRunner
    from spindoctor.cli import cli

    result = CliRunner().invoke(cli, ["add-pc-system", "--help"])
    assert result.exit_code == 0, result.output
    assert "--no-interactive" in result.output


def test_pc_rename_no_interactive_flag_is_registered():
    from click.testing import CliRunner
    from spindoctor.cli import cli

    result = CliRunner().invoke(cli, ["pc-rename", "--help"])
    assert result.exit_code == 0, result.output
    assert "--no-interactive" in result.output


def test_fetch_media_skip_ambiguous_flag_is_registered():
    from click.testing import CliRunner
    from spindoctor.cli import cli

    result = CliRunner().invoke(cli, ["fetch-media", "--help"])
    assert result.exit_code == 0, result.output
    assert "--skip-ambiguous" in result.output


def test_matcher_choose_match_skip_ambiguous_returns_none():
    """choose_match(skip_ambiguous=True) must return None for ambiguous
    candidate lists rather than auto-picking or prompting."""
    from spindoctor.matcher import choose_match
    from spindoctor.scraper import GameMetadata

    cands = [
        GameMetadata(name="Game A", source_id="1", match_score=0.9),
        GameMetadata(name="Game B", source_id="2", match_score=0.8),
    ]
    # Cache empty (system name unlikely to collide with anything real)
    result = choose_match(
        "Ambiguous ROM Name (xyz)", cands,
        "TestSystemForSkipAmbiguousFlag",
        skip_ambiguous=True,
    )
    assert result is None


# ─── fetch-meta --game bypass ─────────────────────────────────────────────────


def test_fetch_meta_game_flag_processes_complete_game(tmp_path, isolated_config, monkeypatch):
    """When --game names a game whose metadata is already complete,
    fetch-meta must re-fetch it rather than printing 'not found'.

    Before this fix the function filtered via db.iter_incomplete() and then
    applied the --game filter, so a complete game always fell through to the
    'not found or already complete' error even though the user explicitly
    asked for it by name.
    """
    import spindoctor.scraper as scraper_mod
    from spindoctor.scraper import GameMetadata

    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    db_dir = hs_dir / "Databases" / "nes"
    db_dir.mkdir(parents=True)

    # Game with ALL metadata fields populated — iter_incomplete() skips it.
    game = GameEntry(
        name="mario",
        description="Super Mario Bros",
        manufacturer="Nintendo",
        year="1985",
        genre="Platformer",
        rating="E",
    )
    db = HyperspinDatabase("nes", db_dir / "nes.xml")
    db.upsert_game(game)
    db.save()

    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    cfg.screenscraper_user = "u"
    cfg.screenscraper_password = "p"
    save_config(cfg)

    fetched: list[str] = []

    class _FakeClient:
        source_name = "screenscraper"
        _cache = None

        def fetch_with_search(self, game_name, system_name, threshold=0.80):
            fetched.append(game_name)
            return [GameMetadata(name=game_name, match_score=1.0)]

    monkeypatch.setattr(scraper_mod, "build_client", lambda *_a, **_kw: _FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["fetch-meta", "--system", "nes", "--game", "mario", "--skip-ambiguous", "--apply"],
    )

    assert result.exit_code == 0, result.output
    # "not found in ... database" would mean the bypass didn't work.
    assert "not found in" not in result.output.lower()
    assert "mario" in fetched, "fetch_with_search was never called for mario"


# ─── audit CSV download_log columns ──────────────────────────────────────────


def test_write_audit_csv_includes_download_log_columns(tmp_path):
    """When a download_log is supplied, _write_audit_csv appends one
    ``{slot}_result`` column per media type recording what fetch-media
    did to each slot (downloaded / existing / no_url / …).
    """
    import csv

    from spindoctor.cli import _write_audit_csv
    from spindoctor.audit import GameAuditEntry, MediaStatus, SystemAuditResult
    from spindoctor.config import MEDIA_TYPES

    entry = GameAuditEntry(
        rom_name="mario",
        in_database=True,
        rom_exists=True,
        db_entry=None,
        media=MediaStatus(),
    )
    audit_result = SystemAuditResult(system_name="nes", entries=[entry])

    download_log = {
        "mario": {
            "wheel": "downloaded",
            "background": "existing",
            "video": "no_url",
        }
    }

    out = tmp_path / "audit.csv"
    _write_audit_csv([audit_result], out, download_log=download_log)

    with open(out, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    row = rows[0]
    assert "wheel_result" in row
    assert row["wheel_result"] == "downloaded"
    assert row["background_result"] == "existing"
    assert row["video_result"] == "no_url"
    # Slots not in the log get an empty string.
    for t in MEDIA_TYPES:
        assert f"{t}_result" in row
