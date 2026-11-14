"""MetadataCache disk-cache tests."""
from __future__ import annotations
import json
from tests.helpers import write_bytes as _write_bytes

import pytest
from spindoctor import scraper

from datetime import datetime, timedelta

from spindoctor.scraper import GameMetadata, MetadataCache


def _meta(name: str, score: float = 1.0) -> GameMetadata:
    return GameMetadata(
        name=name, year="1984", manufacturer="Capcom", source="screenscraper",
        source_id="42", match_score=score,
    )


def test_put_then_get_returns_results(tmp_path):
    cache = MetadataCache(root=tmp_path, ttl_days=30, enabled=True)
    cache.put("screenscraper", "MAME", "1942", [_meta("1942")])
    got = cache.get("screenscraper", "MAME", "1942")
    assert got is not None
    assert len(got) == 1
    assert got[0].name == "1942"


def test_get_returns_none_when_disabled(tmp_path):
    cache = MetadataCache(root=tmp_path, ttl_days=30, enabled=False)
    cache.put("screenscraper", "MAME", "1942", [_meta("1942")])
    assert cache.get("screenscraper", "MAME", "1942") is None


def test_get_returns_none_when_expired(tmp_path):
    cache = MetadataCache(root=tmp_path, ttl_days=1, enabled=True)
    cache.put("screenscraper", "MAME", "1942", [_meta("1942")])

    # Hand-edit the cached_at to be expired.
    p = cache._path("screenscraper", "MAME", "1942")
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    data["cached_at"] = (datetime.now() - timedelta(days=10)).isoformat()
    p.write_text(json.dumps(data), encoding="utf-8")

    assert cache.get("screenscraper", "MAME", "1942") is None


def test_clear_removes_files(tmp_path):
    cache = MetadataCache(root=tmp_path, ttl_days=30, enabled=True)
    cache.put("screenscraper", "MAME", "1942", [_meta("1942")])
    cache.put("screenscraper", "SNES", "mario", [_meta("mario")])
    cache.put("thegamesdb", "MAME", "1942", [_meta("1942")])

    n = cache.clear(source="screenscraper")
    assert n == 2
    assert cache.get("screenscraper", "MAME", "1942") is None
    assert cache.get("thegamesdb", "MAME", "1942") is not None

    n2 = cache.clear()
    assert n2 == 1


def test_metadata_cache_does_not_collide(config_home, tmp_path):
    c = scraper.MetadataCache(root=tmp_path)
    names = ["忍者", "将棋", "A" * 170 + "1", "A" * 170 + "2", "a:b", "a?b"]
    for name in names:
        c.put("screenscraper", "MAME", name, [scraper.GameMetadata(name=name)])
    for name in names:
        assert c.get("screenscraper", "MAME", name)[0].name == name


@pytest.mark.parametrize("value", [[], None, {"results": [{}]}, {"cached_at": []}])
def test_metadata_cache_treats_wrong_schema_as_miss(config_home, tmp_path, value):
    c = scraper.MetadataCache(root=tmp_path)
    path = c._path("screenscraper", "MAME", "A")
    _write_bytes(path, json.dumps(value).encode())
    assert c.get("screenscraper", "MAME", "A") is None


def test_cached_direct_match_is_reconsidered_at_higher_threshold(config_home, tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "get_game_override", lambda *args: {})
    class Client(scraper._FetchWithSearchMixin):
        source_name = "test"
        _cache = scraper.MetadataCache(root=tmp_path)
        searches = 0

        def fetch(self, *args):
            return scraper.GameMetadata(name="near", source_id="1", match_score=.81)

        def search(self, *args):
            self.searches += 1
            return [scraper.GameMetadata(name="best", source_id="2", match_score=.99)]

    client = Client()
    assert client.fetch_with_search("game", "system", .8)[0].name == "near"
    assert client.fetch_with_search("game", "system", .95)[0].name == "best"
    assert client.searches == 1


def test_legacy_metadata_cache_requires_original_identity(config_home, tmp_path):
    from dataclasses import asdict
    c = scraper.MetadataCache(root=tmp_path)
    legacy = tmp_path / "screenscraper" / "MAME" / "_.json"
    payload = {
        "cached_at": datetime.now().isoformat(), "source": "screenscraper", "system": "MAME",
        "rom_stem": "忍者", "results": [asdict(scraper.GameMetadata(name="Ninja"))],
    }
    _write_bytes(legacy, json.dumps(payload).encode())
    assert c.get("screenscraper", "MAME", "忍者")[0].name == "Ninja"
    assert c.get("screenscraper", "MAME", "将棋") is None
