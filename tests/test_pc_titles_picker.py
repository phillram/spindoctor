"""PC title-review picker — interactive UX, cache I/O."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import spindoctor.pc_titles as pc_titles
from spindoctor.matcher import SKIP_SENTINEL


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_titles, "CACHE_DIR", tmp_path / "pc_titles_cache")
    return tmp_path / "pc_titles_cache"


def _proposals(tmp_path) -> list[tuple[Path, str]]:
    a = tmp_path / "Hades.lnk"
    b = tmp_path / "Cyberpunk 2077" / "bin" / "launcher.exe"
    b.parent.mkdir(parents=True)
    a.touch()
    b.touch()
    return [(a, "Hades"), (b, "Cyberpunk 2077")]


def test_non_interactive_accepts_all_proposals(isolated_cache, tmp_path):
    proposals = _proposals(tmp_path)
    out = pc_titles.review_titles("PC Games", proposals, interactive=False)
    assert out[proposals[0][0]] == "Hades"
    assert out[proposals[1][0]] == "Cyberpunk 2077"


def test_interactive_accept_default_writes_cache(
    isolated_cache, tmp_path, monkeypatch,
):
    proposals = _proposals(tmp_path)
    # Empty input → accept proposed title for both files.
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    out = pc_titles.review_titles("PC Games", proposals, interactive=True)
    assert out[proposals[0][0]] == "Hades"
    assert out[proposals[1][0]] == "Cyberpunk 2077"

    cache = json.loads(
        (isolated_cache / "PC Games.json").read_text(encoding="utf-8")
    )
    assert cache[str(proposals[0][0].resolve())] == "Hades"
    assert cache[str(proposals[1][0].resolve())] == "Cyberpunk 2077"


def test_interactive_edit_overrides_proposal(isolated_cache, tmp_path, monkeypatch):
    proposals = _proposals(tmp_path)
    answers = iter(["Hades II", "Cyberpunk 2077"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    out = pc_titles.review_titles("PC Games", proposals, interactive=True)
    assert out[proposals[0][0]] == "Hades II"
    assert out[proposals[1][0]] == "Cyberpunk 2077"


def test_interactive_skip_excludes_file(isolated_cache, tmp_path, monkeypatch):
    proposals = _proposals(tmp_path)
    answers = iter(["s", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    out = pc_titles.review_titles("PC Games", proposals, interactive=True)
    assert proposals[0][0] not in out
    assert out[proposals[1][0]] == "Cyberpunk 2077"

    cache = json.loads(
        (isolated_cache / "PC Games.json").read_text(encoding="utf-8")
    )
    assert cache[str(proposals[0][0].resolve())] == SKIP_SENTINEL


def test_cached_decision_skips_prompt(isolated_cache, tmp_path):
    proposals = _proposals(tmp_path)
    # Pre-populate cache with prior choices.
    isolated_cache.mkdir(parents=True, exist_ok=True)
    cache = {
        str(proposals[0][0].resolve()): "Hades II",
        str(proposals[1][0].resolve()): SKIP_SENTINEL,
    }
    (isolated_cache / "PC Games.json").write_text(
        json.dumps(cache), encoding="utf-8",
    )

    out = pc_titles.review_titles("PC Games", proposals, interactive=False)
    assert out[proposals[0][0]] == "Hades II"
    assert proposals[1][0] not in out


def test_clear_cache(isolated_cache, tmp_path):
    isolated_cache.mkdir(parents=True, exist_ok=True)
    (isolated_cache / "PC Games.json").write_text("{}", encoding="utf-8")
    (isolated_cache / "Steam Games.json").write_text("{}", encoding="utf-8")
    assert pc_titles.clear_cache("PC Games") == 1
    assert not (isolated_cache / "PC Games.json").exists()
    assert (isolated_cache / "Steam Games.json").exists()
    assert pc_titles.clear_cache() == 1
