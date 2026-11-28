"""libretro-thumbnails as a media source.

libretro keeps box art, screenshots, title screens and some logos in
No-Intro naming, one GitHub repository per system, with no key or request
allowance. thumbnails.libretro.com answers 404, so files come from
raw.githubusercontent.com. Fake sessions stand in for GitHub here.
"""
from __future__ import annotations

import json

import pytest

from spindoctor import libretro as lr
from spindoctor.config import Config, reset_override_cache, save_config
from spindoctor.scraper import ChainedMetadataClient, LibretroClient, build_client


class _Resp:
    def __init__(self, status=200, payload=None, content=b"", ctype="image/png"):
        self.status_code, self._payload, self.content = status, payload, content
        self.headers = {"Content-Type": ctype}

    def json(self):
        return self._payload


class _Session:
    """GitHub stand-in: a tree per repo (or a status), files that exist, links."""

    def __init__(self, trees=None, tree_status=200, files=(), links=None):
        self.trees, self.tree_status = trees or {}, tree_status
        self.files, self.links = set(files), links or {}
        self.calls: list[tuple[str, str]] = []

    def get(self, url, timeout=None):
        self.calls.append(("get", url))
        if url.startswith("https://api.github.com/"):
            repo = url.split("/repos/libretro-thumbnails/")[1].split("/")[0]
            if self.tree_status != 200:
                return _Resp(self.tree_status)
            if repo not in self.trees or "/master?" not in url:
                return _Resp(404)
            return _Resp(200, self.trees[repo])
        for path, target in self.links.items():
            if url.endswith(lr.quote(path)):
                return _Resp(200, content=target.encode(), ctype="text/plain")
        return _Resp(404)

    def head(self, url, timeout=None, allow_redirects=True):
        self.calls.append(("head", url))
        ok = any(url.endswith(lr.quote(p)) for p in self.files)
        return _Resp(200 if ok else 404)


def _tree(*paths, links=(), truncated=False):
    return {"truncated": truncated, "tree": [
        {"path": p, "type": "blob", "mode": "120000" if p in links else "100644"} for p in paths
    ]}


DS = "Nintendo_-_Nintendo_DS"


def _client(tmp_path, session):
    return LibretroClient(session=session, cache_dir=tmp_path / "cache", ttl_days=30)


# ─── names and systems ────────────────────────────────────────────────────────

def test_file_names_replace_the_characters_libretro_replaces():
    assert lr.file_stem('Q*bert: "Arcade" (USA)') == "Q_bert_ _Arcade_ (USA)"
    assert lr.file_stem("Mario & Luigi (USA)") == "Mario _ Luigi (USA)"


def test_wheels_map_to_repositories():
    assert lr.repos_for("Nintendo DS") == [DS]
    assert lr.repos_for("Sony Playstation Minis") == ["Sony_-_PlayStation_Portable"]
    assert lr.repos_for("Atari Jaguar") == ["Atari_-_Jaguar"]     # <Maker>_-_<Rest>
    assert lr.repos_for("Watara Supervision") == ["Watara_-_Supervision"]
    assert lr.repos_for("MAME") == [] and lr.repos_for("Some Wheel") == []


def test_libretro_system_override(config_home):
    cfg = Config()
    cfg.system_overrides = {"My DS": {"libretro_system": "Nintendo - Nintendo DS"}}
    save_config(cfg)
    reset_override_cache()
    assert lr.repos_for("My DS") == [DS]


def test_tree_listing_keeps_the_four_folders_and_marks_links():
    listing = lr.parse_tree(DS, "master", _tree(
        "Named_Boxarts/A (USA).png", "Named_Logos/A (USA).png", "README.md",
        "Named_Snaps/B (Europe).png", "Other/C.png", links={"Named_Snaps/B (Europe).png"},
    ))
    assert set(listing.files["Named_Boxarts"]) == {"A (USA)"}
    assert listing.files["Named_Snaps"]["B (Europe)"] == ["Named_Snaps/B (Europe).png", True]
    assert lr.parse_tree(DS, "master", _tree("x", truncated=True)) is None


def test_matching_prefers_the_same_name_then_the_same_title():
    listing = lr.parse_tree(DS, "master", _tree(
        "Named_Boxarts/007 - Blood Stone (USA).png",
        "Named_Boxarts/Golf Ou (Japan).png", "Named_Boxarts/Golf Ou (Japan) (Rev 1).png",
        "Named_Boxarts/Bakugan - Defenders of the Core (USA).png",
    ))
    assert lr.best_stem(listing, "Named_Boxarts", "007 - Blood Stone (USA)", 0.8) == (
        "007 - Blood Stone (USA)", 1.0)
    assert lr.best_stem(listing, "Named_Boxarts", "Golf Ou (Japan) (SGB Enhanced)", 0.8) == (
        "Golf Ou (Japan)", 0.95)
    stem, score = lr.best_stem(listing, "Named_Boxarts", "Bakugan - Defender of the Core (USA)", 0.8)
    assert stem.startswith("Bakugan") and 0.8 <= score < 0.95
    assert lr.best_stem(listing, "Named_Boxarts", "Something Else (USA)", 0.8) is None


# ─── client ───────────────────────────────────────────────────────────────────

def test_client_gives_raw_github_urls_and_caches_the_listing(tmp_path):
    session = _Session(trees={DS: _tree(
        "Named_Boxarts/007 - Blood Stone (USA).png", "Named_Snaps/007 - Blood Stone (USA).png",
    )})
    [meta] = _client(tmp_path, session).fetch_with_search("007 - Blood Stone (USA)", "Nintendo DS")
    assert (meta.source, meta.name, meta.match_score) == ("libretro", "007 - Blood Stone (USA)", 1.0)
    assert meta.artwork_url == (
        "https://raw.githubusercontent.com/libretro-thumbnails/Nintendo_-_Nintendo_DS/master/"
        "Named_Boxarts/007%20-%20Blood%20Stone%20%28USA%29.png")
    assert meta.snap_url and not meta.wheel_url and not meta.title_url
    saved = json.loads((tmp_path / "cache" / f"{DS}.json").read_text(encoding="utf-8"))
    assert saved["branch"] == "master"

    offline = _Session()                      # a second run reads the saved listing
    assert _client(tmp_path, offline).fetch("007 - Blood Stone (USA)", "Nintendo DS").snap_url
    assert offline.calls == []


def test_symlinked_thumbnails_point_at_their_target(tmp_path):
    session = _Session(
        trees={DS: _tree("Named_Boxarts/Clone (USA).png", "Named_Boxarts/Parent (USA).png",
                         links={"Named_Boxarts/Clone (USA).png"})},
        links={"Named_Boxarts/Clone (USA).png": "Parent (USA).png"},
    )
    meta = _client(tmp_path, session).fetch("Clone (USA)", "Nintendo DS")
    assert meta.artwork_url.endswith("Named_Boxarts/Parent%20%28USA%29.png")


def test_without_a_listing_exact_names_are_checked_one_by_one(tmp_path):
    session = _Session(tree_status=403, files={"Named_Titles/Brainpipe (USA).png"})
    meta = _client(tmp_path, session).fetch("Brainpipe (USA)", "Sony PSP")
    assert meta.title_url.endswith("Named_Titles/Brainpipe%20%28USA%29.png")
    assert not meta.artwork_url
    assert sum(1 for kind, _ in session.calls if kind == "head") == 4


def test_unknown_wheels_ask_nothing(tmp_path):
    session = _Session()
    assert _client(tmp_path, session).fetch_with_search("pacman", "MAME") == []
    assert session.calls == []


def test_build_client_names_libretro():
    assert isinstance(build_client(Config(), "libretro", use_cache=False), LibretroClient)
    chain = build_client(Config(thegamesdb_key="k"), "libretro,thegamesdb", use_cache=False)
    assert isinstance(chain, ChainedMetadataClient) and chain.names == ["libretro", "thegamesdb"]


@pytest.mark.parametrize("value", ["libretro", "launchbox,libretro,thegamesdb"])
def test_cli_accepts_libretro(value):
    from spindoctor.cli import _SourceParam
    assert _SourceParam().convert(value, None, None) == value
