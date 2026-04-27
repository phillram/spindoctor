"""Metadata scraping from ScreenScraper and TheGamesDB."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from .config import SCREENSCRAPER_API, THEGAMESDB_API, Config


SCREENSCRAPER_SYSTEMS: dict[str, int] = {
    "mame": 75,
    "arcade": 75,
    "nes": 3,
    "nintendo entertainment system": 3,
    "snes": 4,
    "super nintendo": 4,
    "genesis": 1,
    "mega drive": 1,
    "n64": 14,
    "nintendo 64": 14,
    "gba": 12,
    "game boy advance": 12,
    "psx": 57,
    "playstation": 57,
    "ps2": 58,
    "playstation 2": 58,
    "dreamcast": 23,
    "gamecube": 13,
    "atari 2600": 26,
    "cps1": 6,
    "cps2": 7,
    "neogeo": 142,
    "neo geo": 142,
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
    "psx": 10,
    "playstation": 10,
    "ps2": 11,
    "playstation 2": 11,
    "dreamcast": 16,
    "gamecube": 2,
    "atari 2600": 22,
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

    # Media URLs
    wheel_url: str = ""
    background_url: str = ""
    artwork_url: str = ""
    video_url: str = ""
    sound_url: str = ""


class MetadataError(Exception):
    pass


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


class ScreenScraperClient:
    def __init__(self, username: str, password: str, rate_limit: float = 1.0):
        self.username = username
        self.password = password
        self._limiter = RateLimiter(rate_limit)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"

    def _system_id(self, system_name: str) -> Optional[int]:
        return SCREENSCRAPER_SYSTEMS.get(system_name.lower())

    def fetch(self, game_name: str, system_name: str) -> Optional[GameMetadata]:
        system_id = self._system_id(system_name)
        self._limiter.wait()
        params = {
            "devid": "SpinDoctor",
            "devpassword": "SpinDoctor",
            "softname": "SpinDoctor",
            "ssid": self.username,
            "sspassword": self.password,
            "output": "json",
            "romnom": f"{game_name}.zip",
        }
        if system_id:
            params["systemeid"] = system_id

        try:
            resp = self._session.get(
                f"{SCREENSCRAPER_API}/jeuInfos.php",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"ScreenScraper request failed: {e}") from e

        if "response" not in data or "jeu" not in data["response"]:
            return None

        jeu = data["response"]["jeu"]
        return _parse_screenscraper(game_name, jeu)

    def search(self, game_name: str, system_name: str) -> list[GameMetadata]:
        system_id = self._system_id(system_name)
        self._limiter.wait()
        params = {
            "devid": "SpinDoctor",
            "devpassword": "SpinDoctor",
            "softname": "SpinDoctor",
            "ssid": self.username,
            "sspassword": self.password,
            "output": "json",
            "recherche": game_name,
        }
        if system_id:
            params["systemeid"] = system_id

        try:
            resp = self._session.get(
                f"{SCREENSCRAPER_API}/jeuRecherche.php",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"ScreenScraper search failed: {e}") from e

        jeux = data.get("response", {}).get("jeux", []) or []
        return [_parse_screenscraper(game_name, j) for j in jeux[:5]]


class TheGamesDBClient:
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
        platform_id = self._platform_id(system_name)
        if platform_id:
            params["filter[platform]"] = platform_id

        try:
            resp = self._session.get(
                f"{THEGAMESDB_API}/Games/ByGameName",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"TheGamesDB request failed: {e}") from e

        games = data.get("data", {}).get("games", [])
        if not games:
            return None
        return _parse_thegamesdb(game_name, games[0], data)


def build_client(config: Config, source: Optional[str] = None):
    """Build the appropriate metadata client based on config and source preference."""
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


def _parse_screenscraper(rom_name: str, jeu: dict) -> GameMetadata:
    def _lang(items, lang="en") -> str:
        if not items:
            return ""
        if isinstance(items, str):
            return items
        for item in items:
            if isinstance(item, dict) and item.get("langue") == lang:
                return item.get("text", "")
        if isinstance(items[0], dict):
            return items[0].get("text", "")
        return ""

    noms = jeu.get("noms", [])
    name = _lang(noms) or rom_name

    synopsis = jeu.get("synopsis", [])
    description = _lang(synopsis)

    editeur = jeu.get("editeur", {})
    manufacturer = editeur.get("text", "") if isinstance(editeur, dict) else ""

    year = jeu.get("dates", {}).get("date_us", "")[:4] if jeu.get("dates") else ""

    genres = jeu.get("genres", [])
    genre = _lang(genres[0].get("noms", [])) if genres else ""

    classification = jeu.get("classifications", [])
    rating = ""
    if classification:
        for c in classification:
            if c.get("type") == "ESRB":
                rating = c.get("text", "")
                break

    medias = jeu.get("medias", [])
    wheel_url = _find_media_url(medias, "wheel")
    bg_url = _find_media_url(medias, "ss") or _find_media_url(medias, "fanart")
    artwork_url = _find_media_url(medias, "box-2D") or _find_media_url(medias, "box-3D")
    video_url = _find_media_url(medias, "video-normalized") or _find_media_url(medias, "video")

    return GameMetadata(
        name=name,
        description=description,
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        rating=rating,
        wheel_url=wheel_url,
        background_url=bg_url,
        artwork_url=artwork_url,
        video_url=video_url,
        source="screenscraper",
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

    genre_ids = game.get("genres", []) or []
    genre = genres_map.get(str(genre_ids[0]), {}).get("name", "") if genre_ids else ""

    dev_ids = game.get("developers", []) or []
    manufacturer = devs_map.get(str(dev_ids[0]), {}).get("name", "") if dev_ids else ""

    release_date = game.get("release_date", "") or ""
    year = release_date[:4] if release_date else ""

    base_url = boxart.get("base_url", {}).get("medium", "")
    images = boxart.get("data", {}).get(str(game.get("id")), []) or []
    artwork_url = (base_url + images[0]["filename"]) if images and base_url else ""

    return GameMetadata(
        name=game.get("game_title", rom_name),
        description=game.get("overview", ""),
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        rating=game.get("rating", ""),
        players=str(game.get("players", "")),
        artwork_url=artwork_url,
        source="thegamesdb",
    )
