"""Media-candidate picker — cache + selection logic."""
from __future__ import annotations

import json

from spindoctor import matcher
from spindoctor.scraper import MediaCandidate


def _patch_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(matcher, "MEDIA_CACHE_DIR", tmp_path / "media_pick")


def test_pick_returns_only_candidate(tmp_path, monkeypatch):
    _patch_cache_dir(tmp_path, monkeypatch)
    cands = [MediaCandidate(url="only", source_type="wheel")]
    chosen = matcher.pick_media("Game", "wheel", cands, "MAME", interactive=True)
    assert chosen.url == "only"


def test_pick_skips_when_non_interactive_takes_first(tmp_path, monkeypatch):
    _patch_cache_dir(tmp_path, monkeypatch)
    cands = [MediaCandidate(url="a"), MediaCandidate(url="b")]
    chosen = matcher.pick_media("Game", "wheel", cands, "MAME", interactive=False)
    assert chosen.url == "a"


def test_pick_uses_cached_choice(tmp_path, monkeypatch):
    _patch_cache_dir(tmp_path, monkeypatch)
    cache_path = matcher._media_cache_path("MAME")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"Game::wheel": "b"}), encoding="utf-8")

    cands = [MediaCandidate(url="a"), MediaCandidate(url="b")]
    chosen = matcher.pick_media("Game", "wheel", cands, "MAME", interactive=True)
    assert chosen.url == "b"


def test_pick_interactive_writes_cache(tmp_path, monkeypatch):
    _patch_cache_dir(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
    cands = [MediaCandidate(url="a"), MediaCandidate(url="b")]
    chosen = matcher.pick_media("Game", "wheel", cands, "MAME", interactive=True)
    assert chosen.url == "b"
    cache = json.loads(matcher._media_cache_path("MAME").read_text(encoding="utf-8"))
    assert cache["Game::wheel"] == "b"


def test_pick_skip_records_sentinel(tmp_path, monkeypatch):
    _patch_cache_dir(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")
    cands = [MediaCandidate(url="a"), MediaCandidate(url="b")]
    chosen = matcher.pick_media("Game", "wheel", cands, "MAME", interactive=True)
    assert chosen is None
    cache = json.loads(matcher._media_cache_path("MAME").read_text(encoding="utf-8"))
    assert cache["Game::wheel"] == matcher.SKIP_SENTINEL


def test_clear_media_cache(tmp_path, monkeypatch):
    _patch_cache_dir(tmp_path, monkeypatch)
    p = matcher._media_cache_path("MAME")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    n = matcher.clear_media_cache("MAME")
    assert n == 1
    assert not p.exists()
