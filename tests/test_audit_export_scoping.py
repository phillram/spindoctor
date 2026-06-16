"""`_auto_export_audit` / `_write_audit_csv` — scoping and before/after columns.

Regression coverage for a real-cabinet complaint: running
``fetch-media --game X`` produced an audit CSV listing every game on
the console instead of just X, and gave no way to see what a media
slot's status was *before* the run alongside the after-state.
"""
from __future__ import annotations

import csv

import pytest

import spindoctor.config as config_mod
from spindoctor.audit import GameAuditEntry, MediaStatus, SystemAuditResult
from spindoctor.cli import _auto_export_audit, _write_audit_csv
from spindoctor.config import Config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _build_layout(tmp_path):
    """One system (NES) with two games: Mario and Zelda."""
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    (roms / "NES").mkdir(parents=True)
    (roms / "NES" / "Mario.nes").touch()
    (roms / "NES" / "Zelda.nes").touch()

    (hs / "Databases" / "NES").mkdir(parents=True)
    (hs / "Databases" / "NES" / "NES.xml").write_text(
        "<menu>"
        "<game name=\"Mario\"><description>Mario</description></game>"
        "<game name=\"Zelda\"><description>Zelda</description></game>"
        "</menu>",
        encoding="utf-8",
    )
    (hs / "Media" / "NES").mkdir(parents=True)
    return roms, hs


def _cfg(roms, hs, export_dir):
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hs)
    cfg.auto_audit_export_dir = str(export_dir)
    return cfg


def _read_csv(export_dir):
    [csv_path] = list(export_dir.glob("audit_*.csv"))
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ─── game_filter scoping ───────────────────────────────────────────────────

def test_game_filter_limits_export_to_one_game(isolated_config, tmp_path):
    roms, hs = _build_layout(tmp_path)
    export_dir = tmp_path / "exports"
    cfg = _cfg(roms, hs, export_dir)

    _auto_export_audit(cfg, ["NES"], game_filter="Mario")

    rows = _read_csv(export_dir)
    assert len(rows) == 1
    assert rows[0]["rom_name"] == "Mario"


def test_no_game_filter_exports_every_game(isolated_config, tmp_path):
    """Sanity check: without a filter, both games still show up — the
    scoping is opt-in, not a regression in the unfiltered case."""
    roms, hs = _build_layout(tmp_path)
    export_dir = tmp_path / "exports"
    cfg = _cfg(roms, hs, export_dir)

    _auto_export_audit(cfg, ["NES"])

    rows = _read_csv(export_dir)
    assert {r["rom_name"] for r in rows} == {"Mario", "Zelda"}


def test_game_filter_for_nonexistent_game_exports_no_rows(isolated_config, tmp_path):
    roms, hs = _build_layout(tmp_path)
    export_dir = tmp_path / "exports"
    cfg = _cfg(roms, hs, export_dir)

    _auto_export_audit(cfg, ["NES"], game_filter="Does Not Exist")

    assert _read_csv(export_dir) == []


# ─── before/after columns ──────────────────────────────────────────────────

def _entry(rom_name, **media_kwargs):
    return GameAuditEntry(
        rom_name=rom_name, in_database=True, rom_exists=True, db_entry=None,
        media=MediaStatus(**media_kwargs),
    )


def test_write_audit_csv_adds_before_columns_alongside_result_columns(tmp_path):
    """``{type}_before`` columns must appear, independent of and in
    addition to the existing ``{type}`` (after-state) and
    ``{type}_result`` (action-taken) columns."""
    result = SystemAuditResult(system_name="NES")
    result.entries = [_entry("Mario", wheel=True)]
    path = tmp_path / "audit.csv"

    _write_audit_csv(
        [result], path,
        download_log={"Mario": {"wheel": "downloaded"}},
        before_log={"Mario": {"wheel": "False"}},
    )

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    row = rows[0]
    assert row["wheel"] == "True"            # after state
    assert row["wheel_result"] == "downloaded"  # action taken this run
    assert row["wheel_before"] == "False"       # state prior to the run


def test_write_audit_csv_omits_before_columns_when_not_provided(tmp_path):
    """Plain `audit --report` callers (no before_log) must see the CSV
    shape unchanged — this is purely additive."""
    result = SystemAuditResult(system_name="NES")
    result.entries = [_entry("Mario", wheel=True)]
    path = tmp_path / "audit.csv"

    _write_audit_csv([result], path)

    with open(path, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert not any(h.endswith("_before") for h in header)
    assert not any(h.endswith("_result") for h in header)
