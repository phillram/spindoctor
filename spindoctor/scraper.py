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
    CONFIG_DIR, SCREENSCRAPER_API, THEGAMESDB_API, Config, get_game_override,
    get_system_overrides, load_config,
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


def _raise_if_ss_error(data: dict) -> None:
    """Raise MetadataError if the ScreenScraper JSON body signals an API-level
    error (quota exceeded, auth failure, server issue).  SS returns HTTP 200
    even for these conditions; the error is signalled via an ``"erreur"`` key
    at the top level or inside ``response``."""
    err = data.get("erreur") or data.get("response", {}).get("erreur")
    if err:
        raise MetadataError(f"ScreenScraper API error: {err}")


def _raise_if_tgdb_error(data: dict) -> None:
    """Raise MetadataError if the TheGamesDB JSON body signals an auth or
    API-level error.  TGDB returns HTTP 200 for auth failures and signals the
    problem via a top-level ``"code"`` field (401 / 403) rather than an HTTP
    status code.  Quota exhaustion uses proper HTTP 429 and is already caught
    by ``raise_for_status()``, so we only need to handle the in-band cases."""
    code = data.get("code")
    if code and code not in (200, None):
        status = data.get("status") or ""
        raise MetadataError(f"TheGamesDB API error (code {code}): {status}")


def _redact_error_str(error: BaseException, params: Optional[dict]) -> str:
    """Scrub sensitive param values out of an exception string.

    When DNS fails, urllib3 embeds the full URL (including query params) in
    the MaxRetryError / NameResolutionError message text. ``str(error)``
    would expose sspassword / devpassword / apikey verbatim even though
    ``_redact_params`` already cleaned the params dict. This replaces every
    known-secret literal value with ``***`` before the string hits the log.
    """
    text = str(error)
    if not params:
        return text
    for key in _REDACT_KEYS:
        val = params.get(key)
        if val and val not in ("", None):
            text = text.replace(str(val), "***")
    return text


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
                             label, method, url, redacted,
                             _redact_error_str(error, params))
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


# ScreenScraper system IDs — lowercase HyperSpin name / common alias → SS id.
# ScreenScraper splits DOS/legacy PC (id=135) from PC Windows/exe (id=138).
# "pc" defaults to DOS/legacy; "pc games"/"windows"/"steam" default to Win.
# Full list sourced from ScreenScraper /api2/systemesListe.php (249 systems).
SCREENSCRAPER_SYSTEMS: dict[str, int] = {
    "32x": 19,
    "3do": 29,
    "3ds": 17,
    "acorn archimedes": 84,
    "acorn electron": 85,
    "adam": 89,
    "amiga": 64,
    "amiga cd32": 130,
    "amiga cdtv": 129,
    "amstrad cpc": 65,
    "apple ii": 86,
    "apple iigs": 86,
    "apple mac os": 146,
    "arcade": 75,
    "arcadia 2001": 94,
    "archimedes": 84,
    "astrocade": 44,
    "atari 2600": 26,
    "atari 5200": 40,
    "atari 7800": 41,
    "atari 8-bit": 43,
    "atari 8bit": 43,
    "atari jaguar": 27,
    "atari lynx": 28,
    "atari st": 42,
    "atomiswave": 53,
    "bally astrocade": 44,
    "bandai wonderswan": 45,
    "bandai wonderswan color": 46,
    "c64": 66,
    "capcom play system": 6,
    "capcom play system 2": 7,
    "capcom play system 3": 8,
    "capcom play system ii": 7,
    "capcom play system iii": 8,
    "cd-i": 133,
    "channel f": 80,
    "coleco adam": 89,
    "colecovision": 48,
    "commodore 128": 66,
    "commodore 16 & plus4": 99,
    "commodore 64": 66,
    "commodore amiga": 64,
    "commodore amiga cd32": 130,
    "commodore cdtv": 129,
    "commodore vic-20": 73,
    "cougar boy": 90,
    "cpc": 65,
    "cps1": 6,
    "cps2": 7,
    "creatronic mega duck": 90,
    "daphne": 49,
    "dreamcast": 23,
    "ds": 15,
    "electron": 85,
    "emerson arcadia 2001": 94,
    "fairchild channel f": 80,
    "family computer disk system": 106,
    "final burn alpha": 75,
    "fm towns": 253,
    "fujitsu fm towns": 253,
    "future pinball": 199,
    "game boy": 9,
    "game boy advance": 12,
    "game boy color": 10,
    "game gear": 21,
    "game.com": 121,
    "gameboy": 9,
    "gamecube": 13,
    "gamepark 32": 101,
    "gba": 12,
    "gbc": 10,
    "gce vectrex": 102,
    "genesis": 1,
    "gp32": 101,
    "hbmame": 75,
    "hikaru": 258,
    "intellivision": 115,
    "jaguar": 27,
    "lynx": 28,
    "mac os": 146,
    "magnavox odyssey 2": 104,
    "magnavox odyssey2": 104,
    "mame": 75,
    "master system": 2,
    "mattel intellivision": 115,
    "mega cd": 20,
    "mega drive": 1,
    "mega duck": 90,
    "mega-cd": 20,
    "megadrive": 1,
    "megadrive 32x": 19,
    "microsoft ms-dos": 135,
    "microsoft msx": 113,
    "microsoft msx2": 116,
    "microsoft windows 3.x": 136,
    "microsoft xbox": 32,
    "microsoft xbox 360": 33,
    "microsoft xbox one": 34,
    "misfit mame": 75,
    "model 2": 54,
    "model 3": 55,
    "msx": 113,
    "msx2": 116,
    "n-gage": 30,
    "n64": 14,
    "naomi": 56,
    "naomi 2": 230,
    "naomi gd-rom": 227,
    "nds": 15,
    "nec pc engine": 31,
    "nec pc engine-cd": 114,
    "nec pc-fx": 72,
    "nec supergrafx": 105,
    "nec turbografx-16": 31,
    "nec turbografx-cd": 114,
    "neo geo": 142,
    "neo-geo": 142,
    "neo-geo cd": 70,
    "neo-geo mvs": 68,
    "neo-geo pocket": 25,
    "neo-geo pocket color": 82,
    "neogeo": 142,
    "nes": 3,
    "nintendo 3ds": 17,
    "nintendo 64": 14,
    "nintendo 64dd": 122,
    "nintendo ds": 15,
    "nintendo entertainment system": 3,
    "nintendo famicom": 3,
    "nintendo famicom disk system": 106,
    "nintendo game boy": 9,
    "nintendo game boy advance": 12,
    "nintendo game boy color": 10,
    "nintendo gamecube": 13,
    "nintendo satellaview": 107,
    "nintendo super famicom": 4,
    "nintendo super game boy": 127,
    "nintendo switch": 225,
    "nintendo switch 2": 296,
    "nintendo virtual boy": 11,
    "nintendo wii": 16,
    "nintendo wii u": 18,
    "nokia n-gage": 30,
    "openbor": 214,
    "panasonic 3do": 29,
    # ScreenScraper 135=PC DOS/legacy, 138=PC Win/exe. "pc" → DOS, rest → Win.
    "pc": 135,
    "pc dos": 135,
    "pc engine": 31,
    "pc engine cd-rom": 114,
    "pc engine supergrafx": 105,
    "pc games": 138,
    "pc win3.xx": 136,
    "pc windows": 138,
    "pc-fx": 72,
    "philips cd-i": 133,
    "philips videopac plus g7400": 104,
    "pico-8": 234,
    "pinball fx2": 143,
    "pinball fx3": 201,
    "playstation": 57,
    "playstation 2": 58,
    "playstation 3": 59,
    "playstation 5": 284,
    "plus/4": 99,
    "ps vita": 62,
    "ps1": 57,
    "ps2": 58,
    "ps3": 59,
    "psp": 61,
    "psx": 57,
    "sammy atomiswave": 53,
    "satellaview": 107,
    "saturn": 22,
    "scummvm": 123,
    "sega 32x": 19,
    "sega cd": 20,
    "sega dreamcast": 23,
    "sega game gear": 21,
    "sega genesis": 1,
    "sega hikaru": 258,
    "sega master system": 2,
    "sega model 2": 54,
    "sega model 3": 55,
    "sega naomi": 56,
    "sega naomi 2": 230,
    "sega naomi gd-rom": 227,
    "sega pico": 250,
    "sega saturn": 22,
    "sega sg-1000": 109,
    "segacd": 20,
    "sg-1000": 109,
    "sharp x68000": 79,
    "sinclair zx spectrum": 76,
    "snes": 4,
    "snk neo geo": 142,
    "snk neo geo cd": 70,
    "snk neo geo mvs": 68,
    "snk neo geo pocket": 25,
    "snk neo geo pocket color": 82,
    "sony playstation": 57,
    "sony playstation 2": 58,
    "sony playstation 3": 59,
    "sony playstation 5": 284,
    "sony ps vita": 62,
    "sony psp": 61,
    "steam": 138,
    "steam games": 138,
    "super game boy": 127,
    "super nintendo": 4,
    "super nintendo entertainment system": 4,
    "super nintendo msu-1": 210,
    "switch": 225,
    "switch 2": 296,
    "taito g-net": 299,
    "tandy trs-80 color computer": 144,
    "teknoparrot": 269,
    "thomson mo/to": 141,
    "tiger game.com": 121,
    "trs-80 color computer": 144,
    "turbografx": 31,
    "turbografx-16": 31,
    "vectrex": 102,
    "vic-20": 73,
    "videopac g7000": 104,
    "virtual boy": 11,
    "visual pinball": 198,
    "watara supervision": 207,
    "wii": 16,
    "wii u": 18,
    "windows": 138,
    "windows games": 138,
    "wonderswan": 45,
    "wonderswan color": 46,
    "x68000": 79,
    "xbox": 32,
    "xbox 360": 33,
    "xbox one": 34,
    "zx spectrum": 76,
}

# TheGamesDB platform IDs — verified against /v1/Platforms endpoint 2026-06-14.
# Full list (153 platforms); lowercase name / common alias → TGDB platform id.
THEGAMESDB_PLATFORMS: dict[str, int] = {
    "32x": 33,
    "3do": 25,
    "3ds": 4912,
    "acorn archimedes": 4944,
    "acorn electron": 4954,
    "action max": 4976,
    "amiga": 4911,
    "amiga cd32": 4947,
    "amiga cdtv": 86,
    "amstrad cpc": 4914,
    "amstrad gx4000": 4999,
    "android": 4916,
    "apf mp-1000": 4969,
    "apple ii": 4942,
    "apple iigs": 4942,
    "apple pippin": 5001,
    "arcade": 23,
    "atari 2600": 22,
    "atari 5200": 26,
    "atari 7800": 27,
    "atari 8-bit": 4943,
    "atari 800": 4943,
    "atari 8bit": 4943,
    "atari jaguar": 28,
    "atari jaguar cd": 29,
    "atari lynx": 4924,
    "atari st": 4937,
    "atari xe": 30,
    "bally astrocade": 4968,
    "bandai tv jack 5000": 4995,
    "bbc bridge companion": 4997,
    "bbc micro": 5013,
    "c64": 40,
    "casio loopy": 4991,
    "casio pv-1000": 4964,
    "cd-i": 4917,
    "channel f": 4928,
    "coleco telstar arcade": 4970,
    "colecovision": 31,
    "commodore 128": 4946,
    "commodore 16": 5006,
    "commodore 64": 40,
    "commodore cdtv": 86,
    "commodore pet": 5008,
    "commodore plus/4": 5007,
    "commodore vic-20": 4945,
    "cpc": 4914,
    "creatronic mega duck": 4948,
    "dragon 32/64": 4952,
    "dreamcast": 16,
    "ds": 8,
    "emerson arcadia 2001": 4963,
    "entex adventure vision": 4974,
    "entex select-a-game": 4973,
    "epoch cassette vision": 4965,
    "epoch super cassette vision": 4966,
    "evercade": 4985,
    "fairchild channel f": 4928,
    "famicom": 7,
    "famicom disk system": 4936,
    "fds": 4936,
    "fm towns": 4932,
    "fm towns marty": 4932,
    "fujitsu fm towns": 4932,
    "fujitsu fm-7": 4978,
    "gakken compact vision": 4962,
    "gamate": 5004,
    "game & watch": 4950,
    "game boy": 4,
    "game boy advance": 5,
    "game boy color": 41,
    "game gear": 20,
    "game wave": 5002,
    "game.com": 4940,
    "gameboy": 4,
    "gamecube": 2,
    "gamepark 32": 5015,
    "gb": 4,
    "gba": 5,
    "gbc": 41,
    "gce vectrex": 4939,
    "genesis": 18,
    "gizmondo": 4992,
    "gp32": 5015,
    "handheld electronic games (lcd)": 4951,
    "hyperscan": 4987,
    "intellivision": 32,
    "interton vc 4000": 4994,
    "ios": 4915,
    "j2me (java platform, micro edition)": 5018,
    "lynx": 4924,
    "mac os": 37,
    "macos": 37,
    "magnavox odyssey 1": 4961,
    "magnavox odyssey 2": 4927,
    "mame": 23,
    "master system": 35,
    "mattel aquarius": 4989,
    "mega cd": 21,
    "mega drive": 18,
    "mega duck": 4948,
    "megadrive": 18,
    "microsoft xbox": 14,
    "microsoft xbox 360": 15,
    "microsoft xbox one": 4920,
    "microsoft xbox series x": 4981,
    "milton bradley microvision": 4972,
    "msx": 4929,
    "n-gage": 4938,
    "n64": 3,
    "nds": 8,
    "neo geo": 24,
    "neo geo cd": 4956,
    "neo geo pocket": 4922,
    "neo geo pocket color": 4923,
    "neo-geo": 24,
    "neo-geo cd": 4956,
    "neo-geo pocket": 4922,
    "neo-geo pocket color": 4923,
    "neogeo": 24,
    "nes": 7,
    "nintendo 3ds": 4912,
    "nintendo 64": 3,
    "nintendo ds": 8,
    "nintendo entertainment system (nes)": 7,
    "nintendo famicom": 7,
    "nintendo game boy": 4,
    "nintendo game boy advance": 5,
    "nintendo game boy color": 41,
    "nintendo gamecube": 2,
    "nintendo super famicom": 6,
    "nintendo switch": 4971,
    "nintendo switch 2": 5021,
    "nintendo virtual boy": 4918,
    "nintendo wii": 9,
    "nintendo wii u": 38,
    "nokia n-gage": 4938,
    "nuon": 4935,
    "oculus quest": 4990,
    "odyssey 2": 4927,
    "oric-1": 4986,
    "ouya": 4921,
    "pc": 1,
    "pc engine": 34,
    "pc engine cd": 4955,
    "pc games": 1,
    "pc-88": 4933,
    "pc-98": 4934,
    "pc-fx": 4930,
    "philips cd-i": 4917,
    "philips tele-spiel es-2201": 4993,
    "pioneer laseractive": 4975,
    "playdate": 5016,
    "playdia": 5000,
    "playstation": 10,
    "playstation 2": 11,
    "playstation 3": 12,
    "playstation 4": 4919,
    "playstation 5": 4980,
    "ps vita": 39,
    "ps1": 10,
    "ps2": 11,
    "ps3": 12,
    "ps4": 4919,
    "ps5": 4980,
    "psp": 13,
    "psx": 10,
    "r-zone": 4983,
    "rca studio ii": 4967,
    "sam coupé": 4979,
    "saturn": 17,
    "sega 32x": 33,
    "sega cd": 21,
    "sega dreamcast": 16,
    "sega game gear": 20,
    "sega genesis": 18,
    "sega master system": 35,
    "sega mega drive": 36,
    "sega pico": 4958,
    "sega saturn": 17,
    "sega sg-1000": 4949,
    "segacd": 21,
    "sg-1000": 4949,
    "sharp x68000": 4931,
    "sharp x1": 4977,
    "sinclair zx spectrum": 4913,
    "sinclair zx80": 5009,
    "sinclair zx81": 5010,
    "snes": 6,
    "sony playstation": 10,
    "sony playstation 2": 11,
    "sony playstation 3": 12,
    "sony playstation 4": 4919,
    "sony playstation 5": 4980,
    "sony playstation portable": 13,
    "sony playstation vita": 39,
    "stadia": 5011,
    "steam": 1,
    "steam games": 1,
    "super nintendo": 6,
    "super nintendo (snes)": 6,
    "super nintendo entertainment system": 6,
    "supergrafx": 90,
    "switch": 4971,
    "switch 2": 5021,
    "tandy visual interactive system": 4982,
    "texas instruments ti-99/4a": 4953,
    "tg-16": 34,
    "thomson to7": 5022,
    "tiger game.com": 4940,
    "tomy tutor": 4960,
    "trs-80 color computer": 4941,
    "turbografx": 34,
    "turbografx 16": 34,
    "turbografx cd": 4955,
    "turbografx-16": 34,
    "turbografx-cd": 4955,
    "v.smile": 4988,
    "vectrex": 4939,
    "vic-20": 4945,
    "virtual boy": 4918,
    "vita": 39,
    "vtech creativision": 5005,
    "vtech socrates": 4998,
    "watara supervision": 4959,
    "wii": 9,
    "wii u": 38,
    "windows": 1,
    "windows games": 1,
    "wonderswan": 4925,
    "wonderswan color": 4926,
    "x68000": 4931,
    "xavix port": 4984,
    "xbox": 14,
    "xbox 360": 15,
    "xbox one": 4920,
    "xbox series x": 4981,
    "zx spectrum": 4913,
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
    "trailer":    ("video-normalized", "video"),
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

        # Let MetadataError propagate — callers (fetch-meta, fetch-media) catch
        # it and surface the real error message rather than silently treating
        # an API failure as "no match".
        candidates = self.search(game_name, system_name)

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
        """Direct ROM-name lookup — returns best single match or None.

        Checks ``config game-override`` first: if this exact (system,
        game) has a forced ``screenscraper_id``, fetch that ID directly
        and skip name matching entirely (the override exists precisely
        because name matching didn't work for this title). Returns
        whatever ``fetch_by_id`` returns — including ``None`` if the
        forced ID itself doesn't resolve — rather than falling back to
        name-based search, since silently fuzzy-matching after an
        explicit override would defeat the point of setting one.
        """
        forced_id = get_game_override(system_name, game_name).get("screenscraper_id")
        if forced_id:
            forced = self.fetch_by_id(str(forced_id))
            if forced:
                forced.match_score = 1.0
            return forced

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

        # SS signals quota/auth errors via an "erreur" key at HTTP 200.
        _raise_if_ss_error(data)
        if "response" not in data or "jeu" not in data.get("response", {}):
            return None

        meta = _parse_screenscraper(game_name, data["response"]["jeu"])
        meta.match_score = similarity(game_name, meta.name)
        return meta

    def fetch_by_id(self, game_id: str) -> Optional[GameMetadata]:
        """Look up a specific game by ScreenScraper ID — full detail record.

        Used to backfill media for a ``search()`` hit: ``jeuRecherche.php``
        (the text-search endpoint) returns a much lighter ``jeu`` payload
        than ``jeuInfos.php`` and often carries no ``medias`` array at all,
        so a game can "resolve" via search with every media slot empty even
        though the game's own ScreenScraper page has plenty of art. Re-fetching
        by ID hits the same detail endpoint ``fetch()`` uses, which does
        return the full media gallery. Returns ``None`` on any error — this
        is a best-effort enrichment, not a required step.
        """
        if not game_id:
            return None
        self._limiter.wait()
        params = {**self._base_params(), "gameid": game_id}
        url = f"{SCREENSCRAPER_API}/jeuInfos.php"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            _log_http("screenscraper.fetch_by_id", "GET", url, params,
                      resp.status_code, resp.text or "")
            resp.raise_for_status()
            data = resp.json()
            _raise_if_ss_error(data)
        except Exception:  # noqa: BLE001 — best-effort enrichment only
            return None
        if "response" not in data or "jeu" not in data.get("response", {}):
            return None
        return _parse_screenscraper(str(game_id), data["response"]["jeu"])

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

        _raise_if_ss_error(data)
        jeux = data.get("response", {}).get("jeux", []) or []
        results = []
        for jeu in jeux[:max_results]:
            meta = _parse_screenscraper(game_name, jeu)
            meta.match_score = similarity(game_name, meta.name)
            results.append(meta)
        results.sort(key=lambda m: m.match_score, reverse=True)

        # The list endpoint's lighter payload means the top (auto-picked)
        # candidate frequently has zero media even when the game's own
        # ScreenScraper page has plenty — one extra by-ID lookup backfills
        # it instead of silently downloading nothing. Only the top result
        # is enriched (not all `max_results`) to avoid burning quota.
        if results and not results[0].media_candidates and results[0].source_id:
            enriched = self.fetch_by_id(results[0].source_id)
            if enriched and enriched.media_candidates:
                top = results[0]
                top.media_candidates = enriched.media_candidates
                for slot in SCREENSCRAPER_MEDIA_TYPES:
                    cands = enriched.media_candidates.get(slot)
                    if cands:
                        setattr(top, f"{slot}_url", cands[0].url)

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

    def _fetch_images(self, game_id: str) -> list[dict]:
        """Fetch all image types for *game_id* via the Games/Images endpoint.

        Returns the raw image list (clearlogos, screenshots, banners, boxart).
        Never raises — returns [] on any network or parse failure so callers
        don't need to wrap this in try/except.
        """
        url = f"{THEGAMESDB_API}/Games/Images"
        params = {"apikey": self.api_key, "games_id": game_id}
        try:
            resp = self._session.get(url, params=params, timeout=15)
            _log_http("thegamesdb.images", "GET", url, params,
                      resp.status_code, resp.text or "")
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("images", {}).get(str(game_id), []) or []
        except Exception as e:
            _log_http("thegamesdb.images", "GET", url, params, None, "", error=e)
            return []

    def fetch(self, game_name: str, system_name: str) -> Optional[GameMetadata]:
        # Checks config game-override first — see ScreenScraperClient.fetch
        # for the full rationale (forced ID skips name matching entirely
        # and never falls back to it, even on a miss).
        forced_id = get_game_override(system_name, game_name).get("thegamesdb_id")
        if forced_id:
            forced = self.fetch_by_id(str(forced_id))
            if forced:
                forced.match_score = 1.0
            return forced

        self._limiter.wait()
        params = {
            "apikey": self.api_key,
            # Normalized the same way `search()` does — TheGamesDB's titles
            # never carry No-Intro/Redump region tags or romset punctuation
            # ("Golden Sun - Dark Dawn (USA)" vs. their "Golden Sun: Dark
            # Dawn"), so sending the raw ROM name here made the direct
            # lookup miss matches that `search()` found just fine.
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
            _log_http("thegamesdb.fetch", "GET", url, params, None, "", error=e)
            raise MetadataError(f"TheGamesDB fetch failed: {e}") from e
        _log_http("thegamesdb.fetch", "GET", url, params,
                  resp.status_code, resp.text or "")
        try:
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataError(f"TheGamesDB fetch failed: {e}") from e

        _raise_if_tgdb_error(data)
        games = data.get("data", {}).get("games", [])
        if not games:
            return None
        meta = _parse_thegamesdb(game_name, games[0], data)
        self._merge_images(meta, games[0])
        meta.match_score = similarity(game_name, meta.name)
        return meta

    def _merge_images(self, meta: GameMetadata, game: dict) -> None:
        """Fetch + merge ``Games/Images`` results into *meta* in-place.

        Shared by ``fetch()`` and ``fetch_by_id()`` — both resolve a
        single TheGamesDB game record and need the same image-gallery
        backfill (``Games/ByGameName``/``ByGameID`` only embed boxart).
        """
        game_id = str(game.get("id", ""))
        if not game_id:
            return
        images = self._fetch_images(game_id)
        extra = _parse_tgdb_images(images)
        for slot, cands in extra.items():
            if not meta.media_candidates.get(slot):
                meta.media_candidates[slot] = cands
        if extra.get("wheel") and not meta.wheel_url:
            meta.wheel_url = extra["wheel"][0].url
        if extra.get("snap") and not meta.snap_url:
            meta.snap_url = extra["snap"][0].url
        if extra.get("background") and not meta.background_url:
            meta.background_url = extra["background"][0].url

    def fetch_by_id(self, game_id: str) -> Optional[GameMetadata]:
        """Look up a specific game by TheGamesDB ID — bypasses name matching.

        Mirrors ``ScreenScraperClient.fetch_by_id``; used by the
        per-game ``thegamesdb_id`` override (see ``config game-override``).
        Returns ``None`` on any error or empty result — best-effort only.
        """
        if not game_id:
            return None
        self._limiter.wait()
        params = {
            "apikey": self.api_key,
            "id": game_id,
            "fields": "overview,genres,developers,publishers,rating,players",
            "include": "boxart",
        }
        url = f"{THEGAMESDB_API}/Games/ByGameID"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            _log_http("thegamesdb.fetch_by_id", "GET", url, params,
                      resp.status_code, resp.text or "")
            resp.raise_for_status()
            data = resp.json()
            _raise_if_tgdb_error(data)
        except Exception:  # noqa: BLE001 — best-effort enrichment only
            return None
        games = data.get("data", {}).get("games", [])
        if not games:
            return None
        meta = _parse_thegamesdb(str(game_id), games[0], data)
        self._merge_images(meta, games[0])
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

        _raise_if_tgdb_error(data)
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

class CombinedMetadataClient(_FetchWithSearchMixin):
    """ScreenScraper primary, TheGamesDB fills any slots SS missed.

    For each game:
    1. Both providers are queried in parallel.
    2. SS metadata and media take full priority.
    3. Any media slot missing from SS is filled from TGDB (e.g. TGDB
       clearlogos fill the wheel slot when SS has no wheel image).
    4. If SS finds nothing, the full TGDB result is used as fallback.
    """

    source_name = "combined"

    def __init__(
        self,
        ss_client: "ScreenScraperClient",
        tgdb_client: "TheGamesDBClient",
        cache: "Optional[MetadataCache]" = None,
    ):
        self._ss = ss_client
        self._tgdb = tgdb_client
        self._cache = cache  # enables _FetchWithSearchMixin's cache check

    def fetch(self, game_name: str, system_name: str) -> "Optional[GameMetadata]":
        ss_meta: Optional[GameMetadata] = None
        ss_error: Optional[str] = None
        tgdb_meta: Optional[GameMetadata] = None
        tgdb_error: Optional[str] = None

        try:
            ss_meta = self._ss.fetch(game_name, system_name)
        except MetadataError as e:
            ss_error = str(e)

        try:
            tgdb_meta = self._tgdb.fetch(game_name, system_name)
        except MetadataError as e:
            tgdb_error = str(e)

        if ss_meta is None and tgdb_meta is None and (ss_error or tgdb_error):
            parts = []
            if ss_error:
                parts.append(f"ScreenScraper: {ss_error}")
            if tgdb_error:
                parts.append(f"TheGamesDB: {tgdb_error}")
            raise MetadataError("; ".join(parts))

        if ss_meta is None:
            return tgdb_meta

        if tgdb_meta is not None:
            for slot, cands in (tgdb_meta.media_candidates or {}).items():
                if not ss_meta.media_candidates.get(slot):
                    ss_meta.media_candidates[slot] = cands

        return ss_meta

    def search(self, game_name: str, system_name: str) -> "list[GameMetadata]":
        ss_error: Optional[str] = None
        ss_results: list[GameMetadata] = []
        try:
            ss_results = self._ss.search(game_name, system_name)
        except MetadataError as e:
            ss_error = str(e)

        tgdb_error: Optional[str] = None
        tgdb_results: list[GameMetadata] = []
        try:
            tgdb_results = self._tgdb.search(game_name, system_name)
        except MetadataError as e:
            tgdb_error = str(e)

        if not ss_results and not tgdb_results and (ss_error or tgdb_error):
            parts = []
            if ss_error:
                parts.append(f"ScreenScraper: {ss_error}")
            if tgdb_error:
                parts.append(f"TheGamesDB: {tgdb_error}")
            raise MetadataError("; ".join(parts))

        seen_ids = {r.source_id for r in ss_results}
        return ss_results + [r for r in tgdb_results if r.source_id not in seen_ids]


def build_client(
    config: Config,
    source: Optional[str] = None,
    use_cache: Optional[bool] = None,
):
    """Return a metadata client for *source*.

    When *source* is None the config ``default_metadata_source`` field is used.
    The special value ``"both"`` (and ``None`` when both credential sets are
    present) returns a :class:`CombinedMetadataClient` that queries
    ScreenScraper first and fills any gaps from TheGamesDB.
    """
    source = source or config.default_metadata_source
    enabled = config.metadata_cache_enabled if use_cache is None else use_cache
    cache = build_metadata_cache(config) if enabled else None

    has_ss   = bool(config.screenscraper_user and config.screenscraper_pass)
    has_tgdb = bool(config.thegamesdb_key)

    def _make_ss() -> "ScreenScraperClient":
        if not has_ss:
            raise MetadataError(
                "ScreenScraper credentials not configured. "
                "Run: spindoctor config set screenscraper_user <user> screenscraper_pass <pass>"
            )
        return ScreenScraperClient(
            config.screenscraper_user, config.screenscraper_pass, cache=cache,
            devid=config.screenscraper_devid or "SpinDoctor",
            devpassword=config.screenscraper_devpassword or "SpinDoctor",
        )

    def _make_tgdb() -> "TheGamesDBClient":
        if not has_tgdb:
            raise MetadataError(
                "TheGamesDB API key not configured. "
                "Run: spindoctor config set thegamesdb_key <key>"
            )
        return TheGamesDBClient(config.thegamesdb_key, cache=cache)

    if source == "screenscraper":
        return _make_ss()

    if source == "thegamesdb":
        return _make_tgdb()

    if source in ("both", "combined"):
        return CombinedMetadataClient(_make_ss(), _make_tgdb(), cache=cache)

    # Unknown / legacy value: fall back to whatever credentials are present.
    if has_ss and has_tgdb:
        return CombinedMetadataClient(_make_ss(), _make_tgdb(), cache=cache)
    if has_ss:
        return _make_ss()
    if has_tgdb:
        return _make_tgdb()

    raise MetadataError(
        "No scraper credentials configured. "
        "Run: spindoctor config set screenscraper_user <u> screenscraper_pass <p> "
        "and/or thegamesdb_key <key>"
    )


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


# Region preference: us → wor (worldwide) → eu → common Western languages →
# other regions → jp/kr → unknown.  Applied to ScreenScraper candidates so the
# first (auto-picked) candidate is the US/English version where available.
_REGION_PREFERENCE: list[str] = [
    "us", "wor", "eu", "fr", "de", "es", "it", "au", "br", "ru", "kr", "jp", "ss",
]


def _sort_candidates_by_region(cands: list[MediaCandidate]) -> list[MediaCandidate]:
    def _rank(c: MediaCandidate) -> int:
        r = (c.region or "").lower()
        try:
            return _REGION_PREFERENCE.index(r)
        except ValueError:
            return len(_REGION_PREFERENCE)
    return sorted(cands, key=_rank)


# ── TheGamesDB image helpers ──────────────────────────────────────────────────

_TGDB_CDN = "https://cdn.thegamesdb.net/images/original/"

# Maps TheGamesDB image type → HyperSpin media slot.
_TGDB_IMAGE_SLOT: dict[str, str] = {
    "clearlogo":  "wheel",       # transparent logo — ideal wheel art
    "screenshot": "snap",        # in-game screenshot
    "banner":     "background",  # horizontal banner art
    "boxart":     "artwork",     # box art (front/back)
}


def _parse_tgdb_images(images: list[dict], base_url: str = _TGDB_CDN) -> dict[str, list[MediaCandidate]]:
    """Convert a Games/Images response into a media_candidates dict."""
    candidates: dict[str, list[MediaCandidate]] = {}
    for img in images:
        if not isinstance(img, dict):
            continue
        itype = img.get("type", "")
        slot = _TGDB_IMAGE_SLOT.get(itype)
        if not slot:
            continue
        filename = img.get("filename") or ""
        if not filename:
            continue
        url = base_url + filename
        side = img.get("side") or ""
        cand = MediaCandidate(
            url=url,
            source_type=itype + (f"-{side}" if side else ""),
            format=Path(filename).suffix.lstrip("."),
        )
        candidates.setdefault(slot, []).append(cand)
    return candidates


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
        cands = _sort_candidates_by_region(_collect_media_candidates(medias, type_keys))
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
