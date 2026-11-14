"""ROM restructure plan / apply / undo round-trips."""
from __future__ import annotations
import json
from tests.helpers import write_bytes as _write_bytes

from spindoctor import organize
import pytest
import shutil

from pathlib import Path

from spindoctor.organize import (
    apply_restructure,
    find_latest_manifest,
    plan_restructure,
    required_layout,
    undo_restructure,
)


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("rom", encoding="utf-8")


def test_required_layout_lookup():
    assert required_layout("Sony Playstation 3") == "per-game-folder"
    assert required_layout("Sega Saturn") == "multi-disc-m3u"
    assert required_layout("Nintendo Entertainment System") is None


def test_plan_flat_system_is_empty(tmp_path):
    sys_dir = tmp_path / "Nintendo Entertainment System"
    sys_dir.mkdir()
    _touch(sys_dir / "smb.nes")
    plan = plan_restructure("Nintendo Entertainment System", tmp_path)
    assert plan.empty
    assert any("flat layout" in n for n in plan.notes)


def test_per_game_folder_plan(tmp_path):
    sys_dir = tmp_path / "Sony Playstation 3"
    _touch(sys_dir / "GameA.iso")
    _touch(sys_dir / "GameB.iso")
    plan = plan_restructure("Sony Playstation 3", tmp_path)
    assert len(plan.moves) == 2
    dests = {Path(m.dest).relative_to(sys_dir).as_posix() for m in plan.moves}
    assert dests == {"GameA/GameA.iso", "GameB/GameB.iso"}


def test_multi_disc_groups_only_when_multiple_discs(tmp_path):
    sys_dir = tmp_path / "Sega Saturn"
    _touch(sys_dir / "Single Game (USA).cue")
    _touch(sys_dir / "Multi Game (Disc 1).bin")
    _touch(sys_dir / "Multi Game (Disc 2).bin")
    plan = plan_restructure("Sega Saturn", tmp_path)
    # Single-disc game stays put
    moved_srcs = {Path(m.src).name for m in plan.moves}
    assert "Single Game (USA).cue" not in moved_srcs
    assert "Multi Game (Disc 1).bin" in moved_srcs
    assert "Multi Game (Disc 2).bin" in moved_srcs
    assert any(c.path.endswith("Multi Game.m3u") for c in plan.creates)


def test_apply_then_undo_round_trip(tmp_path):
    sys_dir = tmp_path / "Sony Playstation 3"
    _touch(sys_dir / "GameA.iso")
    _touch(sys_dir / "GameB.iso")
    initial = sorted(p.relative_to(sys_dir).as_posix() for p in sys_dir.rglob("*") if p.is_file())

    plan = plan_restructure("Sony Playstation 3", tmp_path)
    manifest = apply_restructure(plan)
    assert manifest.exists()
    assert (sys_dir / "GameA" / "GameA.iso").exists()

    summary = undo_restructure(manifest)
    assert summary["moves_reverted"] == 2
    assert not manifest.exists()
    after = sorted(p.relative_to(sys_dir).as_posix() for p in sys_dir.rglob("*") if p.is_file())
    assert after == initial


def test_undo_with_m3u_creates(tmp_path):
    sys_dir = tmp_path / "Sega Saturn"
    _touch(sys_dir / "G (Disc 1).bin")
    _touch(sys_dir / "G (Disc 2).bin")
    plan = plan_restructure("Sega Saturn", tmp_path)
    manifest = apply_restructure(plan)
    assert (sys_dir / "G" / "G.m3u").exists()
    summary = undo_restructure(manifest)
    assert summary["creates_removed"] == 1
    # Originals back, group folder cleaned up
    assert (sys_dir / "G (Disc 1).bin").exists()
    assert not (sys_dir / "G").exists()


def test_apply_refuses_to_overwrite(tmp_path):
    sys_dir = tmp_path / "Sony Playstation 3"
    _touch(sys_dir / "GameA.iso")
    target_dir = sys_dir / "GameA"
    _touch(target_dir / "preexisting.bin")
    # Plan would skip when target exists; create a plan manually that conflicts.
    plan = plan_restructure("Sony Playstation 3", tmp_path)
    # The pre-existing target dir means the planner skipped this file.
    assert not plan.moves
    assert plan.skipped


def test_find_latest_manifest_returns_newest(tmp_path):
    sys_dir = tmp_path / "Sony Playstation 3"
    sys_dir.mkdir(parents=True)
    older = sys_dir / "_spindoctor-restructure-20200101_000000.json"
    newer = sys_dir / "_spindoctor-restructure-20250101_000000.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    found = find_latest_manifest("Sony Playstation 3", tmp_path)
    assert found == newer


def test_organize_does_not_move_its_own_manifest(config_home, tmp_path):
    folder = tmp_path / "Sony Playstation 3"
    _write_bytes(folder / "Game.iso")
    manifest = organize.apply_restructure(organize.plan_restructure(folder.name, tmp_path))
    plan = organize.plan_restructure(folder.name, tmp_path)
    assert plan.empty
    assert manifest.exists()


def test_organize_counts_discs_not_bin_cue_files(config_home, tmp_path):
    folder = tmp_path / "Sega Saturn"
    for ext in (".bin", ".cue"):
        _write_bytes(folder / f"Game (Disc 1){ext}")
    assert organize.plan_restructure(folder.name, tmp_path).empty
    for ext in (".bin", ".cue"):
        _write_bytes(folder / f"Game (Disc 2){ext}")
    plan = organize.plan_restructure(folder.name, tmp_path)
    assert len(plan.moves) == 4
    assert plan.creates[0].content.splitlines() == ["Game (Disc 1).cue", "Game (Disc 2).cue"]


@pytest.mark.parametrize("exception", [OSError, KeyboardInterrupt])
def test_organize_interruption_keeps_partial_undo(config_home, tmp_path, monkeypatch, exception):
    folder = tmp_path / "Sony Playstation 3"
    _write_bytes(folder / "A.iso")
    _write_bytes(folder / "B.iso")
    plan = organize.plan_restructure(folder.name, tmp_path)
    real_move = shutil.move
    calls = []

    def interrupted(src, dest, *args, **kwargs):
        if calls:
            raise exception("interrupted")
        calls.append(src)
        return real_move(src, dest, *args, **kwargs)

    monkeypatch.setattr(shutil, "move", interrupted)
    with pytest.raises(exception):
        organize.apply_restructure(plan)
    manifests = list(folder.glob("_spindoctor-restructure-*.json"))
    assert len(manifests) == 1
    record = json.loads(manifests[0].read_text())
    assert len(record["moves"]) == 2
    assert record["pending"] == [plan.moves[1].dest]
    monkeypatch.setattr(shutil, "move", real_move)
    assert organize.undo_restructure(manifests[0])["errors"] == []
    assert (folder / "A.iso").exists()
    assert (folder / "B.iso").exists()


def test_organize_partial_undo_never_deletes_recreated_playlist(config_home, tmp_path):
    original = _write_bytes(tmp_path / "original.iso", b"conflicting")
    moved = _write_bytes(tmp_path / "organized" / "disc.iso")
    playlist = _write_bytes(moved.parent / "game.m3u")
    payload = {
        "moves": [{"src": str(original), "dest": str(moved)}],
        "creates": [{"path": str(playlist), "content": "disc.iso\n"}],
    }
    manifest = _write_bytes(tmp_path / "manifest.json", json.dumps(payload).encode())
    assert organize.undo_restructure(manifest)["errors"]
    assert not playlist.exists()
    assert json.loads(manifest.read_text())["creates"] == []
    _write_bytes(playlist, b"new user playlist")
    original.unlink()
    assert not organize.undo_restructure(manifest)["errors"]
    assert playlist.read_bytes() == b"new user playlist"
