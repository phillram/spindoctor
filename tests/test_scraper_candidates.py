"""Multi-candidate media parsing for ScreenScraper responses."""
from __future__ import annotations

from spindoctor.scraper import (
    MediaCandidate,
    _collect_media_candidates,
    _metadata_from_dict,
    _parse_screenscraper,
)


def test_collect_collects_all_matching_types():
    medias = [
        {"type": "wheel", "url": "u-wheel-us", "region": "us", "format": "png"},
        {"type": "wheel", "url": "u-wheel-eu", "region": "eu", "format": "png"},
        {"type": "wheel-hd", "url": "u-wheel-hd", "region": "wor"},
        {"type": "ss", "url": "u-ss-us", "region": "us"},
    ]
    cands = _collect_media_candidates(medias, ("wheel", "wheel-hd"))
    # Type priority preserved: all "wheel" before "wheel-hd"
    assert [c.url for c in cands] == ["u-wheel-us", "u-wheel-eu", "u-wheel-hd"]
    assert cands[0].region == "us"
    assert cands[2].source_type == "wheel-hd"


def test_collect_skips_entries_without_url():
    medias = [{"type": "wheel", "url": ""}, {"type": "wheel", "url": "real"}]
    cands = _collect_media_candidates(medias, ("wheel",))
    assert len(cands) == 1 and cands[0].url == "real"


def test_parse_screenscraper_populates_candidates_and_first_url():
    jeu = {
        "id": "42",
        "noms": [{"langue": "en", "text": "Test Game"}],
        "medias": [
            {"type": "wheel", "url": "wheel-1", "region": "us"},
            {"type": "wheel", "url": "wheel-2", "region": "eu"},
            {"type": "box-2D", "url": "art-1"},
        ],
    }
    meta = _parse_screenscraper("test", jeu)
    assert meta.wheel_url == "wheel-1"
    assert "wheel" in meta.media_candidates
    assert len(meta.media_candidates["wheel"]) == 2
    assert meta.media_candidates["artwork"][0].url == "art-1"


def test_metadata_from_dict_round_trips_candidates():
    payload = {
        "name": "x",
        "wheel_url": "u",
        "media_candidates": {
            "wheel": [
                {"url": "u1", "region": "us", "source_type": "wheel"},
                {"url": "u2", "region": "eu", "source_type": "wheel"},
            ],
            "artwork": [],
        },
    }
    meta = _metadata_from_dict(payload)
    assert meta.wheel_url == "u"
    assert isinstance(meta.media_candidates["wheel"][0], MediaCandidate)
    assert meta.media_candidates["wheel"][1].region == "eu"
