"""Metadata scraping from ScreenScraper and TheGamesDB."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from .config import SCREENSCRAPER_API, THEGAMESDB_API, Config
from .romutils import normalize, similarity


SCREENSCRAPER_SYSTEMS: dict[str, int] = {
    "mame": 75,
    "arcade": 75,
    "nes": 3,
    "nintendo entertainment system": 3,
    "snes": 4,
    "super nintendo": 4,
    "genesis": 1,
    "mega drive": 1,
    "sega genesis": 1,
    "n64": 14,
    "nintendo 64": 14,
    "gba": 12,
    "game boy advance": 12,
    "gameboy": 9,
    "game boy": 9,
    "game boy color": 41,
    "gbc": 41,
    "psx": 57,
    "playstation": 57,
    "ps2": 58,
    "playstation 2": 58,
    "dreamcast": 23,
    "gamecube": 13,
    "atari 2600": 26,
    "atari 7800": 41,
    "cps1": 6,
    "cps2": 7,
    "neogeo": 142,
    "neo geo": 142,
    "master system": 2,
    "sega master system": 2,
    "game gear": 21,
    "turbografx": 31,
    "turbografx-16": 31,
    "pc engine": 31,
}

THEGAMESDB_PLATFORMS: dict[str, int] = {
    "mame": 1,
    "arcade": 1,
    "nes": 7,
    "nintendo entertainment system": 7,
    "snes": 6,
    "super nintendo": 6,
    "genesis": 18,
    "mega drive": 18,
    "n64": 3,
    "nintendo 64": 3,
    "gba": 5,
    "game boy advance": 5,
    "gameboy": 4,
    "game boy": 4,
    "psx": 10,
    "playstation": 10,
    "ps2": 11,
    "playstation 2": 11,
    "dreamcast": 16,
    "gamecube": 2,
    "atari 2600": 22,
    "master system": 35,
    "game gear": 20,
}


@dataclass
class GameMetadata:
    name: str
    description: str = ""
    manufacturer: str = ""
    year: str = ""
    genre: str = ""
    rating: str = ""
    players: str = ""
    source: str = ""

    # Identity — used for match caching
    source_id: str = ""
    source_url: str = ""
    match_score: float = 0.0

    # Media download URLs
    wheel_url: str = ""
    background_url: str = ""
    artwork_url: str = ""
    title_url: str = ""
    snap_url: str = ""
    video_url: str = ""
    trailer_url: str = ""
    sound_url: str = ""


class MetadataError(Exception):
    pass


class _FetchWithSearchMixin:
    """Shared fetch_with_search logic for all metadata clients."""

    def fetch_with_search(
        self,
        game_name: str,
        system_name: str,
        threshold: float = 0.80,
    ) -> "list[GameMetadata]":
        """Try direct fetch first; fall back to search if no result.

        Returns a scored, sorted list (best first). May return multiple
        candidates when the name is ambiguous.
        """
        try:
            direct = self.fetch(game_name, system_name)
        except MetadataError:
            direct = None

        if direct and direct.match_score >= threshold:
            return [direct]

        try:
            candidates = self.search(game_name, system_name)
        except MetadataError:
            candidates = []

        # Merge direct result in if it wasn't already found in search results.
        # Guard against empty source_id causing false dedup matches.
        if direct and direct.source_id and not any(
            c.source_id == direct.source_id for c in candidates
        ):
            candidates.append(direct)
            candidates.sort(key=lambda m: m.match_score, reverse=True)

        return candidates


class RateLimiter:
    def __init__(self, calls_per_second: float = 1.0):
        self._interval = 1.0 / calls_per_second
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_call = time.monotonic()


# ─── ScreenScraper ────────────────────────────────────────────────────────────

class ScreenScraperClient(_FetchWithSearchMixin):
    def __init__(self, username: str, password: str, rate_limit: float = 1.0):
        self.username = username
        self.password = password
        self._limiter = RateLimiter(rate_limit)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"

    def _base_params(self) -> dict:
        return {
            "devid": "SpinDoctor",
            "devpassword": "SpinDoctor",
            "softname": "SpinDoctor",
            "ssid": self.username,
            "sspassword": self.password,
            "output": "json",
        }

    def _system_id(self, system_name: str) -> Optional[int]:
        return SCREENSCRAPER_SYSTEMS.get(system_name.lower())

    def fetch(self, game_name: str, system_name: str) -> Optional[GameMetadata]:
        """Direct ROM-name lookup — returns best single match or None."""
        system_id = self._system_id(system_name)
        self._limiter.wait()
        params = {**self._base_params(), "romnom": f"{game_name}.zip"}
        if system_id:
            params["systemeid"] = system_id

        try:
            resp = self._session.get(f"{SCREENSCRAPER_API}/jeuInfos.php", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"ScreenScraper fetch failed: {e}") from e

        if "response" not in data or "jeu" not in data.get("response", {}):
            return None

        meta = _parse_screenscraper(game_name, data["response"]["jeu"])
        meta.match_score = similarity(game_name, meta.name)
        return meta

    def search(self, game_name: str, system_name: str, max_results: int = 8) -> list[GameMetadata]:
        """Broad text search — returns up to max_results candidates, scored."""
        system_id = self._system_id(system_name)
        self._limiter.wait()
        params = {**self._base_params(), "recherche": normalize(game_name)}
        if system_id:
            params["systemeid"] = system_id

        try:
            resp = self._session.get(f"{SCREENSCRAPER_API}/jeuRecherche.php", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"ScreenScraper search failed: {e}") from e

        jeux = data.get("response", {}).get("jeux", []) or []
        results = []
        for jeu in jeux[:max_results]:
            meta = _parse_screenscraper(game_name, jeu)
            meta.match_score = similarity(game_name, meta.name)
            results.append(meta)
        results.sort(key=lambda m: m.match_score, reverse=True)
        return results


# ─── TheGamesDB ───────────────────────────────────────────────────────────────

class TheGamesDBClient(_FetchWithSearchMixin):
    def __init__(self, api_key: str, rate_limit: float = 1.0):
        self.api_key = api_key
        self._limiter = RateLimiter(rate_limit)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"

    def _platform_id(self, system_name: str) -> Optional[int]:
        return THEGAMESDB_PLATFORMS.get(system_name.lower())

    def fetch(self, game_name: str, system_name: str) -> Optional[GameMetadata]:
        self._limiter.wait()
        params = {
            "apikey": self.api_key,
            "name": game_name,
            "fields": "overview,genres,developers,publishers,rating,players",
            "include": "boxart",
        }
        pid = self._platform_id(system_name)
        if pid:
            params["filter[platform]"] = pid

        try:
            resp = self._session.get(f"{THEGAMESDB_API}/Games/ByGameName", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"TheGamesDB fetch failed: {e}") from e

        games = data.get("data", {}).get("games", [])
        if not games:
            return None
        meta = _parse_thegamesdb(game_name, games[0], data)
        meta.match_score = similarity(game_name, meta.name)
        return meta

    def search(self, game_name: str, system_name: str, max_results: int = 8) -> list[GameMetadata]:
        self._limiter.wait()
        params = {
            "apikey": self.api_key,
            "name": normalize(game_name),
            "fields": "overview,genres,developers,publishers,rating,players",
            "include": "boxart",
        }
        pid = self._platform_id(system_name)
        if pid:
            params["filter[platform]"] = pid

        try:
            resp = self._session.get(f"{THEGAMESDB_API}/Games/ByGameName", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"TheGamesDB search failed: {e}") from e

        games = (data.get("data", {}).get("games", []) or [])[:max_results]
        results = []
        for g in games:
            meta = _parse_thegamesdb(game_name, g, data)
            meta.match_score = similarity(game_name, meta.name)
            results.append(meta)
        results.sort(key=lambda m: m.match_score, reverse=True)
        return results


# ─── factory ──────────────────────────────────────────────────────────────────

def build_client(config: Config, source: Optional[str] = None):
    source = source or config.default_metadata_source

    if source == "screenscraper":
        if not config.screenscraper_user or not config.screenscraper_pass:
            raise MetadataError(
                "ScreenScraper credentials not configured. "
                "Run: spindoctor config set screenscraper_user <user> screenscraper_pass <pass>"
            )
        return ScreenScraperClient(config.screenscraper_user, config.screenscraper_pass)

    if source == "thegamesdb":
        if not config.thegamesdb_key:
            raise MetadataError(
                "TheGamesDB API key not configured. "
                "Run: spindoctor config set thegamesdb_key <key>"
            )
        return TheGamesDBClient(config.thegamesdb_key)

    raise MetadataError(f"Unknown metadata source: {source}")


# ─── parsers ──────────────────────────────────────────────────────────────────

def _parse_screenscraper(rom_name: str, jeu: dict) -> GameMetadata:
    def _lang(items, lang: str = "en") -> str:
        if not items:
            return ""
        if isinstance(items, str):
            return items
        for item in items:
            if isinstance(item, dict) and item.get("langue") == lang:
                return item.get("text", "")
        return (items[0].get("text", "") if isinstance(items[0], dict) else "")

    jeu_id = str(jeu.get("id", ""))
    name = _lang(jeu.get("noms", [])) or rom_name
    description = _lang(jeu.get("synopsis", []))

    editeur = jeu.get("editeur", {})
    manufacturer = editeur.get("text", "") if isinstance(editeur, dict) else ""

    year = ""
    dates = jeu.get("dates", {})
    if dates:
        year = (dates.get("date_us") or dates.get("date_wor") or "")[:4]

    genres = jeu.get("genres", [])
    genre = _lang(genres[0].get("noms", [])) if genres else ""

    rating = ""
    for c in (jeu.get("classifications") or []):
        if c.get("type") == "ESRB":
            rating = c.get("text", "")
            break

    medias = jeu.get("medias", [])
    source_url = f"https://www.screenscraper.fr/gameinfos.php?gameid={jeu_id}" if jeu_id else ""

    return GameMetadata(
        name=name,
        description=description,
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        rating=rating,
        source="screenscraper",
        source_id=jeu_id,
        source_url=source_url,
        wheel_url=_find_media_url(medias, "wheel"),
        background_url=_find_media_url(medias, "ss") or _find_media_url(medias, "fanart"),
        artwork_url=_find_media_url(medias, "box-2D") or _find_media_url(medias, "box-3D"),
        title_url=_find_media_url(medias, "screenmarquee") or _find_media_url(medias, "sstitle"),
        snap_url=_find_media_url(medias, "ss"),
        video_url=_find_media_url(medias, "video-normalized") or _find_media_url(medias, "video"),
        trailer_url=_find_media_url(medias, "video-normalized"),
    )


def _find_media_url(medias: list, media_type: str) -> str:
    for m in medias:
        if isinstance(m, dict) and m.get("type") == media_type:
            return m.get("url", "")
    return ""


def _parse_thegamesdb(rom_name: str, game: dict, full_response: dict) -> GameMetadata:
    genres_map = full_response.get("include", {}).get("genres", {}).get("data", {})
    devs_map = full_response.get("include", {}).get("developers", {}).get("data", {})
    boxart = full_response.get("include", {}).get("boxart", {})

    genre_ids = game.get("genres") or []
    genre = genres_map.get(str(genre_ids[0]), {}).get("name", "") if genre_ids else ""

    dev_ids = game.get("developers") or []
    manufacturer = devs_map.get(str(dev_ids[0]), {}).get("name", "") if dev_ids else ""

    release_date = game.get("release_date") or ""
    year = release_date[:4]

    base_url = boxart.get("base_url", {}).get("medium", "")
    images = boxart.get("data", {}).get(str(game.get("id")), []) or []
    artwork_url = (base_url + images[0]["filename"]) if images and base_url else ""

    game_id = str(game.get("id", ""))
    source_url = f"https://thegamesdb.net/game/{game_id}/" if game_id else ""

    return GameMetadata(
        name=game.get("game_title", rom_name),
        description=game.get("overview", ""),
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        rating=game.get("rating", ""),
        players=str(game.get("players") or ""),
        source="thegamesdb",
        source_id=game_id,
        source_url=source_url,
        artwork_url=artwork_url,
    )
