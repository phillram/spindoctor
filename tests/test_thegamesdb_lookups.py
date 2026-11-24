"""TheGamesDB lookups: one request per name, and names it can find.

Regression coverage from a real-cabinet run against TheGamesDB's monthly
allowance. For a game with no match, ``fetch_with_search`` sent the same
``Games/ByGameName`` query twice (``fetch()`` and then ``search()``), and a
low-score match also fetched the same ``Games/Images`` gallery twice: 40
requests for 22 games. The name sent had all punctuation stripped, which
TheGamesDB's name search doesn't match: ``007 blood stone`` finds nothing
on the DS while ``007: Blood Stone`` finds the game, and ``Ready, Set,
Grover!`` needs its commas.
"""
from __future__ import annotations

import types

from spindoctor.scraper import TheGamesDBClient, _tgdb_name_queries


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def _client(answers):
    """A client whose ByGameName answers come from *answers* (name → games).

    Returns the client and the list of (endpoint, name-or-id) it was asked.
    """
    client = TheGamesDBClient("fake-key")
    client._limiter = types.SimpleNamespace(wait=lambda: None)
    asked: list[tuple[str, str]] = []

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        if url.endswith("/Games/Images"):
            asked.append(("images", str(params["games_id"])))
            gid = str(params["games_id"])
            return _FakeResp({"data": {
                "base_url": {"original": "https://cdn.example.invalid/"},
                "images": {gid: [{"type": "clearlogo", "filename": f"clearlogo/{gid}.png"}]},
            }})
        asked.append(("byname", params["name"]))
        return _FakeResp({"data": {"games": answers.get(params["name"], [])}})

    client._session = types.SimpleNamespace(get=fake_get)
    return client, asked


# ─── names sent ───────────────────────────────────────────────────────────────

def test_first_name_keeps_punctuation_and_writes_the_subtitle_colon():
    assert _tgdb_name_queries("007 - Blood Stone (USA)")[0] == "007: Blood Stone"
    assert _tgdb_name_queries("Holy Invasion of Privacy, Badman! (USA)")[0] == \
        "Holy Invasion of Privacy, Badman!"
    assert _tgdb_name_queries("Golden Sun - Dark Dawn (USA) (En,Fr,De,Es,It)")[0] == \
        "Golden Sun: Dark Dawn"


def test_parts_of_the_title_follow_longest_first():
    names = _tgdb_name_queries(
        "123 Sesame Street - Ready, Set, Grover! - With Elmo - The Videogame (USA)"
    )
    assert names == [
        "123 Sesame Street: Ready, Set, Grover!: With Elmo: The Videogame",
        "Ready, Set, Grover!",
        "123 Sesame Street",
    ]
    assert "Ankoku Bujutsu Kai Hen" in _tgdb_name_queries(
        "Yuu Yuu Hakusho Dai-2-Dan - Ankoku Bujutsu Kai Hen (Japan)"
    )


def test_trailing_article_moves_to_the_front():
    assert _tgdb_name_queries("Great Battle Pocket, The (Japan) (SGB Enhanced)")[0] == \
        "The Great Battle Pocket"


def test_no_repeats_and_at_most_three_names():
    assert _tgdb_name_queries("Mother 3 (Japan) (En) (1.2)") == ["Mother 3"]
    assert len(_tgdb_name_queries("A - Bb - Ccc - Dddd - Eeeee (USA)")) == 3


# ─── requests ─────────────────────────────────────────────────────────────────

def test_a_miss_asks_each_name_once():
    client, asked = _client({})

    assert client.fetch_with_search("007 - Blood Stone (USA)", "Nintendo DS") == []

    names = [n for kind, n in asked if kind == "byname"]
    assert names == _tgdb_name_queries("007 - Blood Stone (USA)")
    assert len(names) == len(set(names)), "the same name was sent twice"


def test_a_low_score_match_costs_one_lookup_and_one_gallery():
    game = {"id": 42, "game_title": "Something Else Entirely"}
    client, asked = _client({"007: Blood Stone": [game]})

    results = client.fetch_with_search("007 - Blood Stone (USA)", "Nintendo DS", threshold=0.99)

    assert results and results[0].name == "Something Else Entirely"
    assert asked == [("byname", "007: Blood Stone"), ("images", "42")]


def test_a_shorter_part_finds_the_game():
    game = {"id": 42541, "game_title": "Sesame Street: Ready, Set, Grover!"}
    client, asked = _client({"Ready, Set, Grover!": [game]})

    results = client.fetch_with_search(
        "123 Sesame Street - Ready, Set, Grover! - With Elmo - The Videogame (USA)",
        "Nintendo DS",
    )

    assert [r.name for r in results] == ["Sesame Street: Ready, Set, Grover!"]
    assert results[0].wheel_url.endswith("clearlogo/42541.png")
    assert [n for kind, n in asked if kind == "byname"] == [
        "123 Sesame Street: Ready, Set, Grover!: With Elmo: The Videogame",
        "Ready, Set, Grover!",
    ]


def test_a_good_first_match_stops_there():
    game = {"id": 31971, "game_title": "007: Blood Stone"}
    client, asked = _client({"007: Blood Stone": [game]})

    results = client.fetch_with_search("007 - Blood Stone (USA)", "Nintendo DS")

    assert [r.name for r in results] == ["007: Blood Stone"]
    assert asked == [("byname", "007: Blood Stone"), ("images", "31971")]


def test_another_game_is_looked_up_again():
    client, asked = _client({})
    client.fetch_with_search("Mother 3 (Japan)", "Nintendo Game Boy Advance")
    client.fetch_with_search("Golf Ou (Japan)", "Nintendo Game Boy Color")
    assert [n for kind, n in asked if kind == "byname"] == ["Mother 3", "Golf Ou"]
