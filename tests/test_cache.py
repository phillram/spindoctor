"""Shared JSON cache primitive."""
from __future__ import annotations
import json
from tests.helpers import write_bytes as _write_bytes

import pytest

from spindoctor import cache


def test_load_returns_empty_when_missing(tmp_path):
    assert cache.load(tmp_path / "nope", "MAME") == {}


def test_save_then_load_roundtrip(tmp_path):
    cache.save(tmp_path / "match", "MAME", {"rom": "id123"})
    assert cache.load(tmp_path / "match", "MAME") == {"rom": "id123"}


def test_corrupt_file_yields_empty(tmp_path):
    d = tmp_path / "match"
    d.mkdir()
    (d / "MAME.json").write_text("{ not json", encoding="utf-8")
    assert cache.load(d, "MAME") == {}


def test_clear_specific_system(tmp_path):
    cache.save(tmp_path / "c", "A", {"x": "1"})
    cache.save(tmp_path / "c", "B", {"y": "2"})
    assert cache.clear(tmp_path / "c", "A") == 1
    assert cache.load(tmp_path / "c", "A") == {}
    assert cache.load(tmp_path / "c", "B") == {"y": "2"}


def test_clear_all(tmp_path):
    cache.save(tmp_path / "c", "A", {"x": "1"})
    cache.save(tmp_path / "c", "B", {"y": "2"})
    assert cache.clear(tmp_path / "c") == 2


def test_list_all(tmp_path):
    cache.save(tmp_path / "c", "A", {"a": "1"})
    cache.save(tmp_path / "c", "B", {"b": "2"})
    listing = cache.list_all(tmp_path / "c")
    assert listing == {"A": {"a": "1"}, "B": {"b": "2"}}


@pytest.mark.parametrize("value", [[], None, 12, {"game": []}])
def test_shared_cache_rejects_wrong_json_shape(config_home, tmp_path, value):
    _write_bytes(tmp_path / "MAME.json", json.dumps(value).encode())
    assert cache.load(tmp_path, "MAME") == {}
    assert cache.list_all(tmp_path) == {}


def test_empty_valid_cache_remains_visible_in_listing(config_home, tmp_path):
    cache.save(tmp_path, "Empty", {})
    assert cache.list_all(tmp_path) == {"Empty": {}}
    assert cache.list_all(tmp_path, "Empty") == {"Empty": {}}
