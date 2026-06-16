"""Regression tests for two metadata-matching bugs found on a real cabinet:

A Nintendo DS game ("Golden Sun - Dark Dawn (USA)") matched on
ScreenScraper via the text-search endpoint but came back with zero
media for every requested type, and ``--source both`` never filled the
gap from TheGamesDB because TheGamesDB's direct lookup was sent the raw,
un-normalized ROM name (region tag, hyphens and all) instead of the
cleaned-up name ``search()`` already used.
"""
from __future__ import annotations

from spindoctor.scraper import ScreenScraperClient, TheGamesDBClient


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


# ─── TheGamesDBClient.fetch() name normalization ──────────────────────────────

def test_thegamesdb_fetch_normalizes_region_tag_and_punctuation():
    """fetch()'s direct lookup must normalize the same way search() does.

    TheGamesDB's own titles never carry No-Intro region tags or romset
    punctuation, so sending "Golden Sun - Dark Dawn (USA)" verbatim made
    the direct lookup miss matches that the (already-normalizing)
    search() found just fine.
    """
    client = TheGamesDBClient("fake-key")
    captured: dict = {}

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        captured["params"] = params
        return _FakeResp({"data": {"games": []}})

    import types
    client._session = types.SimpleNamespace(get=fake_get)

    client.fetch("Golden Sun - Dark Dawn (USA)", "Nintendo DS")
    assert captured["params"]["name"] == "golden sun dark dawn"


# ─── ScreenScraperClient.search() media backfill ──────────────────────────────

def _ss_client() -> ScreenScraperClient:
    return ScreenScraperClient("user", "pass")


def test_search_backfills_media_via_fetch_by_id_when_top_result_is_empty():
    """A jeuRecherche.php hit with no `medias` array must be enriched by
    one follow-up jeuInfos.php?gameid= call instead of silently
    reporting "no URL" for every type."""
    client = _ss_client()
    calls: list[str] = []

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        calls.append(url)
        if "jeuRecherche" in url:
            return _FakeResp({
                "response": {"jeux": [
                    {"id": "5775", "noms": [{"langue": "en", "text": "Golden Sun: Dark Dawn"}]},
                ]},
            })
        assert "jeuInfos" in url
        assert params["gameid"] == "5775"
        return _FakeResp({
            "response": {"jeu": {
                "id": "5775",
                "noms": [{"langue": "en", "text": "Golden Sun: Dark Dawn"}],
                "medias": [
                    {"type": "wheel-hd", "url": "https://ss/wheel.png", "region": "us"},
                ],
            }},
        })

    import types
    client._session = types.SimpleNamespace(get=fake_get)

    results = client.search("Golden Sun - Dark Dawn (USA)", "Nintendo DS")
    assert len(results) == 1
    assert results[0].wheel_url == "https://ss/wheel.png"
    assert results[0].media_candidates.get("wheel")
    # Exactly one backfill call, not one per search result.
    assert sum(1 for u in calls if "jeuInfos" in u) == 1


def test_search_does_not_backfill_when_top_result_already_has_media():
    """No wasted API call when the search result already carries media."""
    client = _ss_client()
    calls: list[str] = []

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        calls.append(url)
        return _FakeResp({
            "response": {"jeux": [
                {
                    "id": "1",
                    "noms": [{"langue": "en", "text": "Some Game"}],
                    "medias": [
                        {"type": "wheel-hd", "url": "https://ss/wheel.png", "region": "us"},
                    ],
                },
            ]},
        })

    import types
    client._session = types.SimpleNamespace(get=fake_get)

    results = client.search("Some Game", "Nintendo DS")
    assert results[0].wheel_url == "https://ss/wheel.png"
    assert all("jeuInfos" not in u for u in calls)


def test_fetch_by_id_returns_none_when_jeu_missing():
    client = _ss_client()

    import types
    client._session = types.SimpleNamespace(
        get=lambda url, params=None, timeout=None: _FakeResp({"response": {}}),
    )
    assert client.fetch_by_id("999") is None


def test_fetch_by_id_returns_none_on_request_exception():
    client = _ss_client()

    def raising_get(url, params=None, timeout=None):  # noqa: ARG001
        raise RuntimeError("boom")

    import types
    client._session = types.SimpleNamespace(get=raising_get)
    assert client.fetch_by_id("999") is None


def test_fetch_by_id_returns_none_for_empty_game_id():
    client = _ss_client()
    assert client.fetch_by_id("") is None
    assert client.fetch_by_id(None) is None
