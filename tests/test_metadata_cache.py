"""MetadataCache disk-cache tests."""
from __future__ import annotations

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
