"""Region/version curation: pick the canonical ROM and archive/undo the rest."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
import spindoctor.curate as curate_mod
from spindoctor.config import Config, save_config
from spindoctor.curate import (
    apply_curation, curate_system, find_latest_manifest, undo_curation,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    # Curation manifests live under CONFIG_DIR/curation — mirror the patch.
    monkeypatch.setattr(curate_mod, "CURATION_DIR", home / "curation")
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _cfg(roms_dir):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    save_config(cfg)
    return cfg


def _make(roms, system, *names):
    sys_dir = roms / system
    sys_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        p = sys_dir / name
        p.write_text("rom-bytes", encoding="utf-8")
        paths.append(p)
    return paths


def test_region_priority_usa_beats_japan(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Mario (USA).nes",
          "Mario (Japan).nes",
          "Mario (Europe).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["USA", "World", "Europe", "Japan"])
    assert len(groups) == 1
    g = groups[0]
    assert g.keep.name == "Mario (USA).nes"
    retire_names = sorted(p.name for p in g.retire)
    assert retire_names == ["Mario (Europe).nes", "Mario (Japan).nes"]


def test_region_preference_can_invert(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Mario (USA).nes",
          "Mario (Japan).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["Japan", "USA"])
    assert groups[0].keep.name == "Mario (Japan).nes"


def test_revision_latest_beats_earlier(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Zelda (USA) (Rev 1).nes",
          "Zelda (USA) (Rev 2).nes",
          "Zelda (USA).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["USA"])
    assert len(groups) == 1
    assert groups[0].keep.name == "Zelda (USA) (Rev 2).nes"


def test_revision_oldest_when_inverted(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Zelda (USA) (Rev 1).nes",
          "Zelda (USA) (Rev 2).nes")
    cfg = _cfg(roms)

    groups = curate_system(
        "nes", cfg, preferences=["USA"], prefer_revision_latest=False,
    )
    assert groups[0].keep.name == "Zelda (USA) (Rev 1).nes"


def test_prototype_excluded_by_default(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Earthbound (USA).nes",
          "Earthbound (Proto).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["USA"])
    assert len(groups) == 1
    g = groups[0]
    assert g.keep.name == "Earthbound (USA).nes"
    assert [p.name for p in g.retire] == ["Earthbound (Proto).nes"]
    assert "prototype" in g.reasons["Earthbound (Proto).nes"].lower()


def test_prototype_included_when_flag_off(isolated_config, tmp_path):
    """If only a proto exists for a title, it shouldn't get filtered to nothing."""
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "OnlyProto (Proto).nes",
          "OnlyProto (Beta).nes")
    cfg = _cfg(roms)

    groups = curate_system(
        "nes", cfg, preferences=["USA"], prefer_no_proto=False,
    )
    assert len(groups) == 1
    # With flag off, both are eligible; tiebreak picks lexicographically.
    assert groups[0].keep.name in {"OnlyProto (Beta).nes", "OnlyProto (Proto).nes"}


def test_proto_fallback_when_only_protos_exist(isolated_config, tmp_path):
    """prefer_no_proto on, but every variant is a proto: still return a group."""
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Mystery (Proto).nes",
          "Mystery (Beta).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["USA"])
    assert len(groups) == 1


def test_single_variant_titles_dropped(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes", "Solo (USA).nes")
    cfg = _cfg(roms)

    assert curate_system("nes", cfg, preferences=["USA"]) == []


def test_archive_move_then_undo_round_trip(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Mario (USA).nes",
          "Mario (Japan).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["USA", "Japan"])
    result, manifest = apply_curation(groups, cfg, "nes", action="archive")

    assert manifest is not None and manifest.exists()
    assert len(result.archived) == 1
    src, dest = result.archived[0]
    assert src.name == "Mario (Japan).nes"
    assert dest.parent.name == "_retired"
    assert not src.exists()
    assert dest.exists()
    # Kept ROM stayed put
    assert (roms / "nes" / "Mario (USA).nes").exists()

    # Undo
    summary = undo_curation(manifest)
    assert summary["reverted"] == 1
    assert (roms / "nes" / "Mario (Japan).nes").exists()
    assert not dest.exists()
    assert not manifest.exists()


def test_delete_action_removes_files_no_manifest(isolated_config, tmp_path):
    roms = tmp_path / "roms"
    _make(roms, "nes",
          "Mario (USA).nes",
          "Mario (Japan).nes")
    cfg = _cfg(roms)

    groups = curate_system("nes", cfg, preferences=["USA", "Japan"])
    result, manifest = apply_curation(groups, cfg, "nes", action="delete")

    assert manifest is None  # delete is destructive — no undo
    assert len(result.deleted) == 1
    assert result.deleted[0].name == "Mario (Japan).nes"
    assert not (roms / "nes" / "Mario (Japan).nes").exists()
    assert (roms / "nes" / "Mario (USA).nes").exists()


def test_find_latest_manifest_picks_newest(isolated_config, tmp_path):
    curation_dir = curate_mod.CURATION_DIR
    curation_dir.mkdir(parents=True)
    (curation_dir / "curate-20240101_000000.json").write_text(
        '{"moves": []}', encoding="utf-8")
    (curation_dir / "curate-20990101_000000.json").write_text(
        '{"moves": []}', encoding="utf-8")
    latest = find_latest_manifest()
    assert latest is not None
    assert latest.name.endswith("20990101_000000.json")
