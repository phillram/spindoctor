"""Metadata scraping from ScreenScraper and TheGamesDB."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import requests

from ._net import make_session, request_get
from .config import (
    CONFIG_DIR, SCREENSCRAPER_API, THEGAMESDB_API, Config, get_system_overrides,
    load_config,
)
from .romutils import normalize, similarity


METADATA_CACHE_DIR = CONFIG_DIR / "metadata_cache"
SCRAPER_LOG_PATH = CONFIG_DIR / "scraper.log"


# ─── debug logging ────────────────────────────────────────────────────────────
#
# A dedicated logger writes every ScreenScraper / TheGamesDB request and the
# first slice of its response to ``~/.spindoctor/scraper.log``. The point is to
# unstick "verify returns 403 and the dialog says nothing useful" debugging
# without having to teach a cabinet owner to run Wireshark — the upstream JSON
# error body usually names the failing field ("Erreur de login", "Invalid API
# Key", rate-limit notice) and that gets surfaced in both the file and the UI
# dialog. Secrets (passwords, dev passwords, API keys) are redacted before any
# log line is written.

scraper_logger = logging.getLogger("spindoctor.scraper")
scraper_logger.setLevel(logging.DEBUG)
_LOG_HANDLER_INSTALLED = False
_REDACT_KEYS = frozenset({"sspassword", "devpassword", "apikey"})

# Historical placeholder devid values shipped by SpinDoctor that were
# never registered with ScreenScraper. ``verify_screenscraper`` uses
# this set to recognise a 403 caused by missing dev credentials so the
# error message can point users at the registration page rather than
# leave them suspecting their own user/password.
_SCREENSCRAPER_PLACEHOLDER_DEVIDS = frozenset({"SpinDoctor", ""})


def _install_scraper_log_handler() -> None:
    """Attach the rotating file handler once per process.

    Idempotent — every verify click otherwise stacks another handler and the
    file balloons. Failures (config dir on a read-only mount, permission
    denied) are swallowed: logging is diagnostic, never load-bearing.
    """
    global _LOG_HANDLER_INSTALLED
    if _LOG_HANDLER_INSTALLED:
        return
    try:
        SCRAPER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            SCRAPER_LOG_PATH, maxBytes=512_000, backupCount=2, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
        ))
        handler.setLevel(logging.DEBUG)
        scraper_logger.addHandler(handler)
        scraper_logger.propagate = False
    except OSError:
        pass
    _LOG_HANDLER_INSTALLED = True


def _redact_params(params: Optional[dict]) -> dict:
    """Return a copy of *params* with sensitive values replaced by ``***``."""
    if not params:
        return {}
    return {
        k: ("***" if k in _REDACT_KEYS and v not in ("", None) else v)
        for k, v in params.items()
    }


def _body_snippet(body: str, limit: int = 500) -> str:
    """Compact, single-line slice of a response body for log + dialog use."""
    if not body:
        return ""
    cleaned = " ".join(body.split())
    return cleaned[:limit] + ("\u2026" if len(cleaned) > limit else "")


def _log_http(
    label: str,
    method: str,
    url: str,
    params: Optional[dict],
    status: Optional[int],
    body: str,
    *,
    error: Optional[BaseException] = None,
) -> None:
    """Write a one-line request summary + body snippet on error.

    ``label`` is the human-readable call site (e.g. ``"screenscraper.verify"``).
    Errors (network failures with no response) log the exception text; HTTP
    status >= 400 dumps the first slice of the body so the upstream message
    survives. Healthy 2xx calls just log the URL + status to keep the file
    skim-friendly.
    """
    _install_scraper_log_handler()
    redacted = _redact_params(params)
    if error is not None:
        scraper_logger.error("%s %s %s params=%s — %s",
                             label, method, url, redacted, error)
        return
    size = len(body or "")
    scraper_logger.info("%s %s %s params=%s → HTTP %s (%d bytes)",
                        label, method, url, redacted, status, size)
    if status is not None and (status >= 400 or status == 0):
        scraper_logger.debug("%s body: %s", label, _body_snippet(body))


def _failure_with_body(message: str, body: str) -> str:
    """Compose ``message`` with a parenthetical raw-body hint when present."""
    snippet = _body_snippet(body, limit=300)
    return f"{message} (raw: {snippet})" if snippet else message


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
    "game boy color": 10,
    "gbc": 10,
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
    # Fade-in image shown between wheel and game launch.
    # Prefer the dedicated fanart variant; fall back to mixrbv2 / screenmarquee.
    "fade":       ("fanart", "mixrbv2", "screenmarquee"),
    "video":      ("video-normalized", "video"),
    "trailer":    ("video-normalized",),
    # ScreenScraper uses ``bgmusic`` for the short audio clip on game select.
    "sound":      ("bgmusic", "themetheme"),
    # HyperSpin per-game theme zip (rare; only ScreenScraper exposes it).
    "theme":      ("theme-hs",),
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
    fade_url: str = ""
    video_url: str = ""
    trailer_url: str = ""
    sound_url: str = ""
    theme_url: str = ""

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
        devid: str = "SpinDoctor",
        devpassword: str = "SpinDoctor",
    ):
        self.username = username
        self.password = password
        self.devid = devid or "SpinDoctor"
        self.devpassword = devpassword or "SpinDoctor"
        self._limiter = RateLimiter(rate_limit)
        self._session = make_session()
        self._cache = cache

    def _base_params(self) -> dict:
        return {
            "devid": self.devid,
            "devpassword": self.devpassword,
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

        url = f"{SCREENSCRAPER_API}/jeuInfos.php"
        try:
            resp = self._session.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            _log_http("screenscraper.fetch", "GET", url, params, None, "", error=e)
            raise MetadataError(f"ScreenScraper fetch failed: {e}") from e
        _log_http("screenscraper.fetch", "GET", url, params,
                  resp.status_code, resp.text or "")
        try:
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

        url = f"{SCREENSCRAPER_API}/jeuRecherche.php"
        try:
            resp = self._session.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            _log_http("screenscraper.search", "GET", url, params, None, "", error=e)
            raise MetadataError(f"ScreenScraper search failed: {e}") from e
        _log_http("screenscraper.search", "GET", url, params,
                  resp.status_code, resp.text or "")
        try:
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
        url = f"{SCREENSCRAPER_API}/systemesListe.php"
        try:
            resp = self._session.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            _log_http("screenscraper.systems", "GET", url, params, None, "", error=e)
            raise MetadataError(f"ScreenScraper system list failed: {e}") from e
        _log_http("screenscraper.systems", "GET", url, params,
                  resp.status_code, resp.text or "")
        try:
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
        self._session = make_session()
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

        url = f"{THEGAMESDB_API}/Games/ByGameName"
        try:
            resp = self._session.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            _log_http("thegamesdb.fetch", "GET", url, params, None, "", error=e)
            raise MetadataError(f"TheGamesDB fetch failed: {e}") from e
        _log_http("thegamesdb.fetch", "GET", url, params,
                  resp.status_code, resp.text or "")
        try:
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

        url = f"{THEGAMESDB_API}/Games/ByGameName"
        try:
            resp = self._session.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            _log_http("thegamesdb.search", "GET", url, params, None, "", error=e)
            raise MetadataError(f"TheGamesDB search failed: {e}") from e
        _log_http("thegamesdb.search", "GET", url, params,
                  resp.status_code, resp.text or "")
        try:
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


# ─── credential verification ──────────────────────────────────────────────────
#
# Lightweight "do these credentials work?" probes used by the GUI Setup tab's
# "Test credentials" button. Each returns (ok, message); never raises so the
# UI can render the result without wrapping in try/except.

def verify_screenscraper(
    username: str, password: str, timeout: float = 8.0,
    devid: Optional[str] = None, devpassword: Optional[str] = None,
) -> tuple[bool, str]:
    """Probe ScreenScraper's ssuserInfos.php to validate credentials.

    Hits the same authenticated endpoint the live clients use, so a pass
    here means the credentials are good for real fetches too. Read-only,
    one HTTP GET, ~1s on a healthy network.

    ``devid`` / ``devpassword`` default to the per-process ``Config`` values
    (so a user-overridden developer credential is used here too); pass
    explicit values from tests if you want to bypass disk I/O.
    """
    if not username or not password:
        return False, "username and password are required"

    if devid is None or devpassword is None:
        try:
            cfg = load_config()
        except Exception as exc:
            scraper_logger.warning("Failed to load config for dev credentials: %s", exc)
            cfg = None
        if devid is None:
            devid = (getattr(cfg, "screenscraper_devid", None) or "SpinDoctor")
        if devpassword is None:
            devpassword = (getattr(cfg, "screenscraper_devpassword", None)
                           or "SpinDoctor")

    params = {
        "devid": devid,
        "devpassword": devpassword,
        "softname": "SpinDoctor",
        "ssid": username,
        "sspassword": password,
        "output": "json",
    }
    # ``devid`` is the developer-credential ScreenScraper issues per
    # application; surfacing it in every message lets the user
    # distinguish "my user/password is wrong" from "the SpinDoctor
    # default devid has been blocked/changed upstream". Never echo
    # ``devpassword`` — it doesn't belong in any UI surface.
    devid_str = devid or ""
    # presence-only summary of what was actually sent on the wire, so a
    # 403 is debuggable from the failure message alone.
    sent_summary = (
        f"sent ssid='{username}' (password set: yes), devid={devid_str}"
    )
    url = f"{SCREENSCRAPER_API}/ssuserInfos.php"
    try:
        resp = request_get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        _log_http("screenscraper.verify", "GET", url, params, None, "", error=e)
        return False, f"Network error: {e} ({sent_summary})"

    body = resp.text or ""
    _log_http("screenscraper.verify", "GET", url, params, resp.status_code, body)

    if resp.status_code in (401, 403):
        msg = f"Authentication rejected (HTTP {resp.status_code}, {sent_summary})"
        # ScreenScraper rejects the *whole request* with 403 when devid /
        # devpassword aren't a registered developer pair — regardless of
        # whether ssid / sspassword would otherwise be valid. The bundled
        # "SpinDoctor" placeholder is the most common cause of this in
        # the wild; surface it explicitly so users stop chasing their
        # user credentials instead of their dev credentials.
        if devid in _SCREENSCRAPER_PLACEHOLDER_DEVIDS:
            msg += (
                ". The bundled developer credentials (devid='SpinDoctor') "
                "are not registered with ScreenScraper and will never "
                "authenticate. Register a developer account at "
                "https://www.screenscraper.fr/membreinscription.php and "
                "set the values via Setup → ScreenScraper devid / devpassword "
                "(or `spindoctor config set screenscraper_devid <value>` "
                "and `screenscraper_devpassword`)."
            )
        return False, _failure_with_body(msg, body)
    if resp.status_code >= 500:
        return False, _failure_with_body(
            f"ScreenScraper server error (HTTP {resp.status_code}, devid={devid_str})",
            body,
        )
    if resp.status_code != 200:
        return False, _failure_with_body(
            f"Unexpected HTTP {resp.status_code} ({sent_summary})", body,
        )

    # ScreenScraper signals auth errors via a JSON `erreur` key with a 200
    # status, or sometimes via a plain-text body that doesn't parse as JSON.
    try:
        data = resp.json()
    except ValueError:
        text = body.strip()
        # The auth-failure body is short ("Erreur de login : ..."). Anything
        # else is more useful as a truncated snippet than as "ok".
        snippet = text[:200] if text else "no response body"
        return False, f"Unexpected response: {snippet} ({sent_summary})"

    response = data.get("response") or {}
    if "erreur" in data:
        err = str(data["erreur"]).strip() or "ScreenScraper rejected the credentials"
        return False, f"{err} ({sent_summary})"
    ssuser = response.get("ssuser")
    if not isinstance(ssuser, dict):
        return False, f"ScreenScraper response did not include ssuser ({sent_summary})"

    user_id = ssuser.get("id") or username
    level = ssuser.get("niveau") or ssuser.get("level") or "?"
    max_threads = ssuser.get("maxthreads") or ssuser.get("requestsmax") or ""
    extra = f", threads {max_threads}" if max_threads else ""
    return True, (
        f"OK \u2014 user '{user_id}', level {level}{extra}, devid={devid_str}"
    )


def verify_thegamesdb(api_key: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Probe TheGamesDB to validate an API key.

    Hits ``/Games/ByGameName`` with a trivial query — the same endpoint
    used by the live client — and inspects the response code + remaining
    monthly-allowance counter. Conservatively rejects an HTTP 200 that
    carries no per-key allowance fields at all; TheGamesDB has been
    observed to return 200 with public/anonymous data for some
    invalid keys, which would otherwise present as a fake "OK" in the
    Setup tab Test credentials button.
    """
    if not api_key:
        return False, "API key is required"

    # Obviously-malformed keys never reach TheGamesDB — saves a
    # round-trip and gives the user a clearer message than the API's
    # generic error.
    if any(ch.isspace() for ch in api_key) or len(api_key) < 8:
        return False, "API key looks malformed — refusing to send."

    params = {"apikey": api_key, "name": "test"}
    url = f"{THEGAMESDB_API}/Games/ByGameName"
    try:
        resp = request_get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        _log_http("thegamesdb.verify", "GET", url, params, None, "", error=e)
        return False, f"Network error: {e}"

    body = resp.text or ""
    _log_http("thegamesdb.verify", "GET", url, params, resp.status_code, body)

    if resp.status_code in (401, 403):
        return False, _failure_with_body("Invalid API key (HTTP 403)", body)
    if resp.status_code == 429:
        return False, _failure_with_body(
            "Rate limited (HTTP 429) \u2014 key may be exhausted", body,
        )
    if resp.status_code >= 500:
        return False, _failure_with_body(
            f"TheGamesDB server error (HTTP {resp.status_code})", body,
        )
    if resp.status_code != 200:
        return False, _failure_with_body(
            f"Unexpected HTTP {resp.status_code}", body,
        )

    try:
        data = resp.json()
    except ValueError:
        return False, _failure_with_body("Response was not valid JSON", body)

    code = data.get("code")
    if code in (401, 403):
        return False, str(data.get("status") or "Invalid API key")
    if code and code != 200:
        return False, f"{data.get('status') or 'Error'} (code {code})"

    # A valid authenticated response always carries at least one
    # ``*allowance*`` field (``remaining_monthly_allowance``,
    # ``extended_allowance``, ``allowance_refresh_timer``, etc.). If
    # ``code == 200`` and *none* of those are present, treat as
    # anonymous / un-authenticated and refuse to report success — this
    # is the failure mode where TheGamesDB returns OK + public data
    # for an empty / invalid key.
    has_allowance = any(
        k for k in data if isinstance(k, str) and "allowance" in k.lower()
    )
    if not has_allowance:
        return False, (
            "Suspicious 200 \u2014 response carries no per-key allowance "
            "counter. Treating as invalid."
        )

    remaining = data.get("remaining_monthly_allowance")
    if remaining is None:
        return True, "OK"
    return True, f"OK \u2014 {remaining} monthly requests remaining"


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
            devid=config.screenscraper_devid or "SpinDoctor",
            devpassword=config.screenscraper_devpassword or "SpinDoctor",
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
        if isinstance(dates, dict):
            year = (dates.get("date_us") or dates.get("date_wor") or "")[:4]
        elif isinstance(dates, list):
            # ScreenScraper returns dates as [{region, text}] for some systems
            date_map = {
                d.get("region", ""): d.get("text", "")
                for d in dates
                if isinstance(d, dict)
            }
            year = (date_map.get("us") or date_map.get("wor")
                    or next(iter(date_map.values()), ""))[:4]

    genres = jeu.get("genres", [])
    genre = _lang(genres[0].get("noms", [])) if genres else ""

    rating = ""
    for c in (jeu.get("classifications") or []):
        if c.get("type") == "ESRB":
            rating = c.get("text", "")
            break

    # ScreenScraper exposes the player count via ``joueurs``.  The value can
    # be a plain string ("2"), a range ("1-4"), or a dict with a ``text``
    # key in some payloads — handle all three.
    joueurs = jeu.get("joueurs", "")
    if isinstance(joueurs, dict):
        players = str(joueurs.get("text", "") or "").strip()
    else:
        players = str(joueurs or "").strip()

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
        players=players,
        source="screenscraper",
        source_id=jeu_id,
        source_url=source_url,
        wheel_url=_first("wheel"),
        background_url=_first("background"),
        artwork_url=_first("artwork"),
        title_url=_first("title"),
        snap_url=_first("snap"),
        fade_url=_first("fade"),
        video_url=_first("video"),
        trailer_url=_first("trailer"),
        sound_url=_first("sound"),
        theme_url=_first("theme"),
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
