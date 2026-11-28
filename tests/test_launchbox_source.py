"""LaunchBox Games Database source, and sources asked in turn.

LaunchBox publishes its whole database as one Metadata.zip with no key or
request allowance. On a real cabinet it had clear logos for hundreds of
handheld games TheGamesDB couldn't supply. These tests build a tiny
Metadata.zip in a temp folder: nothing goes over the network.
"""
from __future__ import annotations

import zipfile

import pytest
from click import unstyle
from click.testing import CliRunner

from spindoctor import launchbox as lb
from spindoctor.cli import cli
from spindoctor.config import Config, reset_override_cache, save_config
from spindoctor.scraper import (
    ChainedMetadataClient, GameMetadata, LaunchBoxClient, MetadataError,
    build_client, parse_source_list,
)

_XML = """<?xml version="1.0" standalone="yes"?>
<LaunchBox>
  <Platform><Name>Nintendo DS</Name></Platform>
  <Game><Name>007: Blood Stone</Name><ReleaseYear>2010</ReleaseYear>
    <Developer>n-Space</Developer><Publisher>Activision</Publisher>
    <Genres>Action; Shooter</Genres><ESRB>T - Teen</ESRB><MaxPlayers>1</MaxPlayers>
    <DatabaseID>101</DatabaseID><Platform>Nintendo DS</Platform></Game>
  <Game><Name>The Legend of Zelda: Phantom Hourglass</Name><ReleaseDate>2007-10-01T00:00:00-07:00</ReleaseDate>
    <Developer>Nintendo</Developer><DatabaseID>102</DatabaseID><Platform>Nintendo DS</Platform></Game>
  <Game><Name>Brainpipe</Name><DatabaseID>201</DatabaseID><Platform>Sony PSP Minis</Platform></Game>
  <Game><Name>Pokémon Diamond Version</Name><DatabaseID>103</DatabaseID><Platform>Nintendo DS</Platform></Game>
  <GameAlternateName><AlternateName>Blood Stone 007</AlternateName><DatabaseID>101</DatabaseID></GameAlternateName>
  <GameImage><DatabaseID>101</DatabaseID><FileName>aaa-eu.png</FileName><Type>Clear Logo</Type><Region>Europe</Region></GameImage>
  <GameImage><DatabaseID>101</DatabaseID><FileName>aaa-na.png</FileName><Type>Clear Logo</Type><Region>North America</Region></GameImage>
  <GameImage><DatabaseID>101</DatabaseID><FileName>box.jpg</FileName><Type>Box - Front</Type></GameImage>
  <GameImage><DatabaseID>101</DatabaseID><FileName>shot.png</FileName><Type>Screenshot - Gameplay</Type></GameImage>
  <GameImage><DatabaseID>101</DatabaseID><FileName>back.jpg</FileName><Type>Box - Back</Type></GameImage>
  <GameImage><DatabaseID>201</DatabaseID><FileName>pipe.png</FileName><Type>Clear Logo</Type></GameImage>
</LaunchBox>
"""


def _zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Metadata.xml", _XML)
    return path


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "launchbox.sqlite"
    assert lb.build_index(_zip(tmp_path / "Metadata.zip"), path) == 4
    return path


# ─── names ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom,title", [
    ("007 - Blood Stone (USA)", "007: Blood Stone"),
    ("Legend of Zelda, The - Phantom Hourglass (USA) (En,Fr,De,Es,It)",
     "The Legend of Zelda: Phantom Hourglass"),
    ("Pokemon - Diamond Version (USA) (Rev 5)", "Pokémon Diamond Version"),
    ("Mario & Luigi - Partners in Time (USA)", "Mario and Luigi: Partners in Time"),
])
def test_rom_names_and_launchbox_titles_share_a_key(rom, title):
    assert lb.name_key(rom) == lb.name_key(title)


def test_region_tags_choose_the_image_region():
    assert lb.region_order("Game (USA)")[0] == "North America"
    assert lb.region_order("Game (Japan)")[0] == "Japan"
    assert lb.region_order("Game (Europe) (En,Fr)")[0] == "Europe"


# ─── index and client ─────────────────────────────────────────────────────────

def test_index_keeps_only_the_image_types_it_uses(index):
    idx = lb.LaunchBoxIndex(index)
    assert set(idx.platforms().values()) == {"Nintendo DS", "Sony PSP Minis"}
    assert [r["type"] for r in idx.images("101")] == [
        "Clear Logo", "Clear Logo", "Box - Front", "Screenshot - Gameplay",
    ]                                   # "Box - Back" isn't indexed
    assert idx.info()["games"] == "4"


def test_exact_match_with_metadata_and_images(index):
    client = LaunchBoxClient(index)
    [meta] = client.fetch_with_search("007 - Blood Stone (USA)", "Nintendo DS")
    assert (meta.name, meta.match_score, meta.source) == ("007: Blood Stone", 1.0, "launchbox")
    assert (meta.year, meta.manufacturer, meta.genre, meta.rating, meta.players) == (
        "2010", "n-Space", "Action", "T - Teen", "1")
    assert meta.wheel_url == lb.IMAGE_BASE + "aaa-na.png"      # North America for (USA)
    assert [c.region for c in meta.media_candidates["wheel"]] == ["North America", "Europe"]
    assert meta.artwork_url.endswith("box.jpg") and meta.snap_url.endswith("shot.png")
    assert meta.source_url == lb.GAME_PAGE + "101"


def test_europe_rom_prefers_the_europe_logo(index):
    [meta] = LaunchBoxClient(index).fetch_with_search("007 - Blood Stone (Europe)", "Nintendo DS")
    assert meta.wheel_url.endswith("aaa-eu.png")


def test_alternate_names_and_article_and_year_from_date(index):
    client = LaunchBoxClient(index)
    assert client.fetch("Blood Stone 007 (USA)", "Nintendo DS").source_id == "101"
    zelda = client.fetch("Legend of Zelda, The - Phantom Hourglass (USA)", "Nintendo DS")
    assert (zelda.source_id, zelda.year) == ("102", "2007")


def test_close_spelling_matches_by_score(index):
    [meta] = LaunchBoxClient(index).fetch_with_search("007 - Bloodstone (USA)", "Nintendo DS")
    assert meta.source_id == "101" and 0.8 <= meta.match_score < 1.0


def test_wheel_name_aliases_and_unknown_wheels(index):
    client = LaunchBoxClient(index)
    assert client.fetch("Brainpipe (USA)", "Sony Playstation Minis").source_id == "201"
    assert client.fetch_with_search("Brainpipe (USA)", "Nintendo DS") == []
    assert client.fetch_with_search("007 - Blood Stone (USA)", "Some Wheel") == []


def test_launchbox_platform_override(index, config_home):
    cfg = Config()
    cfg.system_overrides = {"My Minis": {"launchbox_platform": ["Sony PSP Minis"]}}
    save_config(cfg)
    reset_override_cache()
    assert LaunchBoxClient(index).fetch("Brainpipe (USA)", "My Minis").source_id == "201"


def test_missing_database_says_how_to_get_it(tmp_path):
    with pytest.raises(MetadataError, match="launchbox-db update --apply"):
        LaunchBoxClient(tmp_path / "none.sqlite")


# ─── sources in turn ──────────────────────────────────────────────────────────

class _Fake:
    def __init__(self, name, score=1.0, error=None, **urls):
        self.source_name, self.score, self.error, self.urls = name, score, error, urls
        self.asked = 0

    def fetch_with_search(self, game_name, system_name, threshold=0.80):
        self.asked += 1
        if self.error:
            raise MetadataError(self.error)
        if self.score is None:
            return []
        meta = GameMetadata(name=game_name, source=self.source_name, source_id=self.source_name,
                            match_score=self.score, year="1999" if self.source_name == "b" else "")
        for attr, url in self.urls.items():     # wheel_url=…, snap_url=…
            setattr(meta, attr, url)
        return [meta]


def test_later_sources_fill_what_earlier_ones_lack():
    a, b = _Fake("a", snap_url="s-a"), _Fake("b", wheel_url="w-b", snap_url="s-b")
    [meta, _] = ChainedMetadataClient([a, b]).fetch_with_search("G", "Sys")
    assert (meta.source, meta.wheel_url, meta.snap_url, meta.year) == ("a", "w-b", "s-a", "1999")


def test_wanted_types_stop_the_chain_early():
    a, b = _Fake("a", wheel_url="w-a"), _Fake("b", wheel_url="w-b")
    chain = ChainedMetadataClient([a, b])
    chain.wanted_types = {"wheel"}
    [meta] = chain.fetch_with_search("G", "Sys")
    assert meta.wheel_url == "w-a" and b.asked == 0
    chain.wanted_types = {"wheel", "video"}
    chain.fetch_with_search("G", "Sys")
    assert b.asked == 1


def test_a_poor_match_fills_nothing_and_a_good_later_one_leads():
    a, b = _Fake("a", score=0.5, wheel_url="w-a"), _Fake("b", wheel_url="w-b")
    [meta, *_] = ChainedMetadataClient([a, b]).fetch_with_search("G", "Sys")
    assert (meta.source, meta.wheel_url) == ("b", "w-b")


def test_errors_count_only_when_nothing_was_found():
    good, bad = _Fake("a", wheel_url="w"), _Fake("b", error="HTTP 403")
    assert ChainedMetadataClient([bad, good]).fetch_with_search("G", "S")[0].wheel_url == "w"
    with pytest.raises(MetadataError, match="HTTP 403"):
        ChainedMetadataClient([bad, _Fake("c", score=None)]).fetch_with_search("G", "S")


def test_source_lists():
    assert parse_source_list("LaunchBox, thegamesdb") == ["launchbox", "thegamesdb"]
    assert parse_source_list("launchbox,launchbox") == ["launchbox"]
    assert parse_source_list("weird") == ["weird"]            # single: build_client → auto
    with pytest.raises(ValueError, match="both"):
        parse_source_list("launchbox,both")


def test_build_client_makes_a_chain(index, monkeypatch):
    monkeypatch.setattr(lb, "LAUNCHBOX_DIR", index.parent)
    monkeypatch.setattr(lb, "INDEX_NAME", index.name)
    client = build_client(Config(thegamesdb_key="k"), "launchbox,thegamesdb", use_cache=False)
    assert isinstance(client, ChainedMetadataClient)
    assert client.names == ["launchbox", "thegamesdb"]
    assert [type(c).__name__ for c in client.clients] == ["LaunchBoxClient", "TheGamesDBClient"]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_accepts_lists_and_refuses_unknown_sources(config_home, tmp_path):
    from tests.helpers import build_nes_library
    build_nes_library(tmp_path)
    runner = CliRunner()
    bad = runner.invoke(cli, ["fetch-media", "--system", "nes", "--source", "launchbox,nope"])
    assert bad.exit_code == 2 and "unknown source 'nope'" in unstyle(bad.output)
    ok = runner.invoke(cli, ["config", "set", "default_metadata_source", "LaunchBox,TheGamesDB"])
    assert ok.exit_code == 0, ok.output
    from spindoctor import config as config_mod
    assert config_mod.load_config().default_metadata_source == "launchbox,thegamesdb"


def test_fetch_media_tells_the_chain_what_each_game_lacks(config_home, tmp_path, monkeypatch):
    import spindoctor.scraper as scraper_mod
    from tests.helpers import build_nes_library
    build_nes_library(tmp_path)          # mario, zelda, contra: wheel + snap each
    (tmp_path / "hs" / "Media" / "nes" / "Images" / "Wheel" / "zelda.png").unlink()
    seen = {}

    class _Chain(ChainedMetadataClient):
        def fetch_with_search(self, game_name, system_name, threshold=0.80):
            seen[game_name] = set(self.wanted_types)
            return []

    monkeypatch.setattr(scraper_mod, "build_client", lambda *_a, **_k: _Chain([]))
    result = CliRunner().invoke(cli, ["fetch-media", "--system", "nes", "--types", "wheel,snap",
                                      "--source", "launchbox,thegamesdb"])
    assert result.exit_code == 0, result.output
    assert seen == {"zelda": {"wheel"}}


def test_launchbox_db_update_dry_run_then_apply(config_home, tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "LAUNCHBOX_DIR", tmp_path / "lbdir")
    monkeypatch.setattr(lb, "remote_info", lambda session, url=lb.METADATA_URL: (2048, "Fri, 27 Nov 2026"))
    downloads = []

    def fake_download(session, dest, url=lb.METADATA_URL, progress=None):
        downloads.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        _zip(dest)
        return dest.stat().st_size

    monkeypatch.setattr(lb, "download", fake_download)
    runner = CliRunner()

    dry = runner.invoke(cli, ["launchbox-db", "update"])
    assert dry.exit_code == 0, dry.output
    assert "DRY RUN" in dry.output and "Would download" in unstyle(dry.output)
    assert not (tmp_path / "lbdir").exists() and downloads == []

    applied = runner.invoke(cli, ["launchbox-db", "update", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert "4 games indexed" in unstyle(applied.output)
    assert (tmp_path / "lbdir" / lb.INDEX_NAME).is_file()

    again = runner.invoke(cli, ["launchbox-db", "update", "--apply"])
    assert "Nothing to do" in unstyle(again.output) and len(downloads) == 1

    status = runner.invoke(cli, ["launchbox-db", "status", "--offline"])
    assert "4 games on 2 platforms" in unstyle(status.output)
