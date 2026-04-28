"""Metadata scraping from ScreenScraper and TheGamesDB."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from .config import (
    CONFIG_DIR, SCREENSCRAPER_API, THEGAMESDB_API, Config, get_system_overrides,
)
from .romutils import normalize, similarity


METADATA_CACHE_DIR = CONFIG_DIR / "metadata_cache"


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
    # PC / Windows / Steam — ScreenScraper splits "PC" (DOS, 135) from
    # "PC Win" (138).  We default to PC Win for shortcut/exe libraries;
    # users can override either via system_overrides.screenscraper_id.
    "pc": 135,
    "pc games": 138,
    "windows": 138,
    "windows games": 138,
    "steam": 138,
    "steam games": 138,
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
    # PC / Windows / Steam — TheGamesDB platform 1 is "PC".
    "pc": 1,
    "pc games": 1,
    "windows": 1,
    "windows games": 1,
    "steam": 1,
    "steam games": 1,
}


@dataclass
class MediaCandidate:
    """One concrete URL for a media slot, with metadata for picker display."""
    url: str
    region: str = ""          # e.g. "us", "eu", "wor", "jp"
    version: str = ""         # ScreenScraper "version" or extension hint
    format: str = ""          # file extension/format ("png", "mp4", ...)
    source_type: str = ""     # raw API type tag ("box-2D", "screenmarquee", ...)
    width: str = ""           # ScreenScraper "size" / dims (when present)
    height: str = ""

    def label(self) -> str:
        bits = [b for b in (self.region.upper() or "—",
                            self.source_type or "",
                            self.format or "") if b]
        return " · ".join(bits)


# Maps logical media slot → ordered list of ScreenScraper "type" values to try.
# First entry is the canonical type; later entries are fallbacks.
SCREENSCRAPER_MEDIA_TYPES: dict[str, tuple[str, ...]] = {
    "wheel":      ("wheel", "wheel-hd", "wheel-carbon", "wheel-steel"),
    "background": ("ss", "fanart"),
    "artwork":    ("box-2D", "box-3D"),
    "title":      ("screenmarquee", "sstitle"),
    "snap":       ("ss",),
    "video":      ("video-normalized", "video"),
    "trailer":    ("video-normalized",),
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

    # Media download URLs (best/first candidate; auto-pick path)
    wheel_url: str = ""
    background_url: str = ""
    artwork_url: str = ""
    title_url: str = ""
    snap_url: str = ""
    video_url: str = ""
    trailer_url: str = ""
    sound_url: str = ""

    # Full candidate list per slot — populated when --pick-media is used.
    # Maps media slot name (wheel, background, ...) → list of MediaCandidate.
    # Empty by default to keep cache files small for the common case.
    media_candidates: dict[str, list[MediaCandidate]] = field(default_factory=dict)


class MetadataError(Exception):
    pass


# ─── disk cache ───────────────────────────────────────────────────────────────

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(value: str) -> str:
    return _FILENAME_SAFE.sub("_", value)[:160] or "_"


class MetadataCache:
    """Disk-backed cache for fetch_with_search results.

    Avoids re-querying ScreenScraper / TheGamesDB on iterative re-runs and
    saves your monthly TheGamesDB quota.
    """

    def __init__(
        self,
        root: Path = METADATA_CACHE_DIR,
        ttl_days: int = 30,
        enabled: bool = True,
    ):
        self.root = root
        self.ttl = timedelta(days=ttl_days) if ttl_days > 0 else None
        self.enabled = enabled

    def _path(self, source: str, system: str, rom_stem: str) -> Path:
        return (
            self.root
            / _safe_name(source)
            / _safe_name(system)
            / f"{_safe_name(rom_stem)}.json"
        )

    def get(self, source: str, system: str, rom_stem: str) -> Optional[list["GameMetadata"]]:
        if not self.enabled:
            return None
        p = self._path(source, system, rom_stem)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        ts = data.get("cached_at")
        if self.ttl and ts:
            try:
                cached_at = datetime.fromisoformat(ts)
                if datetime.now() - cached_at > self.ttl:
                    return None
            except ValueError:
                return None
        return [_metadata_from_dict(entry) for entry in data.get("results", [])]

    def put(
        self,
        source: str,
        system: str,
        rom_stem: str,
        results: list["GameMetadata"],
    ) -> None:
        if not self.enabled:
            return
        p = self._path(source, system, rom_stem)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "system": system,
            "rom_stem": rom_stem,
            "results": [asdict(r) for r in results],
        }
        try:
            p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def clear(
        self,
        source: Optional[str] = None,
        system: Optional[str] = None,
    ) -> int:
        """Delete cache files; returns number of files removed."""
        if not self.root.exists():
            return 0
        if source is None:
            target = self.root
        elif system is None:
            target = self.root / _safe_name(source)
        else:
            target = self.root / _safe_name(source) / _safe_name(system)
        if not target.exists():
            return 0
        n = 0
        for p in target.rglob("*.json"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n


def build_metadata_cache(config: Config) -> MetadataCache:
    return MetadataCache(
        root=METADATA_CACHE_DIR,
        ttl_days=config.metadata_cache_ttl_days,
        enabled=config.metadata_cache_enabled,
    )


# ─── fetch + search mixin ─────────────────────────────────────────────────────


class _FetchWithSearchMixin:
    """Shared fetch_with_search logic for all metadata clients."""

    # Subclasses set these.
    source_name: str = ""
    _cache: Optional[MetadataCache] = None

    def fetch_with_search(
        self,
        game_name: str,
        system_name: str,
        threshold: float = 0.80,
    ) -> "list[GameMetadata]":
        """Try direct fetch first; fall back to search if no result.

        Returns a scored, sorted list (best first). May return multiple
        candidates when the name is ambiguous.  Results are cached on disk
        when a ``MetadataCache`` is configured.
        """
        if self._cache is not None:
            cached = self._cache.get(self.source_name, system_name, game_name)
            if cached is not None:
                return cached

        try:
            direct = self.fetch(game_name, system_name)
        except MetadataError:
            direct = None

        if direct and direct.match_score >= threshold:
            results = [direct]
            if self._cache is not None:
                self._cache.put(self.source_name, system_name, game_name, results)
            return results

        try:
            candidates = self.search(game_name, system_name)
        except MetadataError:
            candidates = []

        # Merge direct result in if it wasn't already found in search results.
        if direct and direct.source_id and not any(
            c.source_id == direct.source_id for c in candidates
        ):
            candidates.append(direct)
            candidates.sort(key=lambda m: m.match_score, reverse=True)

        if self._cache is not None and candidates:
            self._cache.put(self.source_name, system_name, game_name, candidates)
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
    source_name = "screenscraper"

    def __init__(
        self,
        username: str,
        password: str,
        rate_limit: float = 1.0,
        cache: Optional["MetadataCache"] = None,
    ):
        self.username = username
        self.password = password
        self._limiter = RateLimiter(rate_limit)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"
        self._cache = cache

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
        ovr = get_system_overrides().get(system_name, {})
        if isinstance(ovr.get("screenscraper_id"), int):
            return ovr["screenscraper_id"]
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

    def fetch_system_media(self, system_name: str) -> dict[str, list[MediaCandidate]]:
        """Fetch system-level Main Menu media candidates from ScreenScraper.

        Returns a dict keyed by HyperSpin Main Menu slot
        (``wheel`` / ``background`` / ``video``) of candidate URLs.

        ScreenScraper's ``/systemesListe.php`` endpoint exposes a ``medias``
        array per system with type tags such as ``logo-monochrome``,
        ``wheel``, ``photo``, ``video``.  We map those to HyperSpin's
        Main Menu slots; missing types yield an empty list.
        """
        system_id = self._system_id(system_name)
        if not system_id:
            return {}

        self._limiter.wait()
        params = self._base_params()
        try:
            resp = self._session.get(
                f"{SCREENSCRAPER_API}/systemesListe.php", params=params, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"ScreenScraper system list failed: {e}") from e

        systems = data.get("response", {}).get("systemes", []) or []
        target = next(
            (s for s in systems if str(s.get("id")) == str(system_id)),
            None,
        )
        if not target:
            return {}

        medias = target.get("medias", []) or []
        slot_map: dict[str, tuple[str, ...]] = {
            "wheel":      ("wheel", "logo-monochrome", "logo", "illustration"),
            "background": ("photo", "fanart", "ss"),
            "video":      ("video-normalized", "video"),
        }
        return {
            slot: cands
            for slot, types in slot_map.items()
            if (cands := _collect_media_candidates(medias, types))
        }


# ─── TheGamesDB ───────────────────────────────────────────────────────────────

class TheGamesDBClient(_FetchWithSearchMixin):
    source_name = "thegamesdb"

    def __init__(
        self,
        api_key: str,
        rate_limit: float = 1.0,
        cache: Optional["MetadataCache"] = None,
    ):
        self.api_key = api_key
        self._limiter = RateLimiter(rate_limit)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"
        self._cache = cache

    def _platform_id(self, system_name: str) -> Optional[int]:
        ovr = get_system_overrides().get(system_name, {})
        if isinstance(ovr.get("thegamesdb_id"), int):
            return ovr["thegamesdb_id"]
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

def build_client(
    config: Config,
    source: Optional[str] = None,
    use_cache: Optional[bool] = None,
):
    source = source or config.default_metadata_source
    enabled = config.metadata_cache_enabled if use_cache is None else use_cache
    cache = build_metadata_cache(config) if enabled else None

    if source == "screenscraper":
        if not config.screenscraper_user or not config.screenscraper_pass:
            raise MetadataError(
                "ScreenScraper credentials not configured. "
                "Run: spindoctor config set screenscraper_user <user> screenscraper_pass <pass>"
            )
        return ScreenScraperClient(
            config.screenscraper_user, config.screenscraper_pass, cache=cache,
        )

    if source == "thegamesdb":
        if not config.thegamesdb_key:
            raise MetadataError(
                "TheGamesDB API key not configured. "
                "Run: spindoctor config set thegamesdb_key <key>"
            )
        return TheGamesDBClient(config.thegamesdb_key, cache=cache)

    raise MetadataError(f"Unknown metadata source: {source}")


# ─── parsers ──────────────────────────────────────────────────────────────────

def _metadata_from_dict(entry: dict) -> GameMetadata:
    """Reconstruct GameMetadata from a JSON-serialised dict, including candidates."""
    candidates_raw = entry.get("media_candidates") or {}
    candidates: dict[str, list[MediaCandidate]] = {}
    for slot, items in candidates_raw.items():
        candidates[slot] = [
            MediaCandidate(**{k: v for k, v in item.items()
                              if k in MediaCandidate.__dataclass_fields__})
            for item in items
            if isinstance(item, dict)
        ]
    known = {k: v for k, v in entry.items()
             if k in GameMetadata.__dataclass_fields__ and k != "media_candidates"}
    meta = GameMetadata(**known)
    meta.media_candidates = candidates
    return meta


def _collect_media_candidates(
    medias: list,
    type_keys: tuple[str, ...],
) -> list[MediaCandidate]:
    """Return all matching candidates from a ScreenScraper medias[] array.

    Iterates *all* entries that match any of ``type_keys`` (so different regions
    / versions / formats become separate candidates).  Order: API order, with
    type_keys priority preserved.
    """
    out: list[MediaCandidate] = []
    for type_key in type_keys:
        for m in medias:
            if not isinstance(m, dict):
                continue
            if m.get("type") != type_key:
                continue
            url = m.get("url") or ""
            if not url:
                continue
            out.append(MediaCandidate(
                url=url,
                region=str(m.get("region") or ""),
                version=str(m.get("version") or ""),
                format=str(m.get("format") or ""),
                source_type=type_key,
                width=str(m.get("width") or ""),
                height=str(m.get("height") or ""),
            ))
    return out


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

    candidates: dict[str, list[MediaCandidate]] = {}
    for slot, type_keys in SCREENSCRAPER_MEDIA_TYPES.items():
        cands = _collect_media_candidates(medias, type_keys)
        if cands:
            candidates[slot] = cands

    def _first(slot: str) -> str:
        cs = candidates.get(slot)
        return cs[0].url if cs else ""

    meta = GameMetadata(
        name=name,
        description=description,
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        rating=rating,
        source="screenscraper",
        source_id=jeu_id,
        source_url=source_url,
        wheel_url=_first("wheel"),
        background_url=_first("background"),
        artwork_url=_first("artwork"),
        title_url=_first("title"),
        snap_url=_first("snap"),
        video_url=_first("video"),
        trailer_url=_first("trailer"),
    )
    meta.media_candidates = candidates
    return meta


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

    artwork_candidates: list[MediaCandidate] = []
    if base_url:
        for img in images:
            filename = img.get("filename") if isinstance(img, dict) else None
            if not filename:
                continue
            artwork_candidates.append(MediaCandidate(
                url=base_url + filename,
                source_type=str(img.get("side") or img.get("type") or "boxart"),
                format=Path(filename).suffix.lstrip("."),
            ))
    artwork_url = artwork_candidates[0].url if artwork_candidates else ""

    game_id = str(game.get("id", ""))
    source_url = f"https://thegamesdb.net/game/{game_id}/" if game_id else ""

    meta = GameMetadata(
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
    if artwork_candidates:
        meta.media_candidates = {"artwork": artwork_candidates}
    return meta
