"""libretro-thumbnails as a media source.

The libretro project keeps box art, screenshots, title screens and, for some
systems, logos for every game in No-Intro / Redump naming, one GitHub
repository per system (``github.com/libretro-thumbnails/<System>``). No key
and no request allowance. ``thumbnails.libretro.com`` serves the same files
but has answered 404 since late 2026, so images come from
``raw.githubusercontent.com``.

One GitHub API call per system lists its files (cached on disk for
``metadata_cache_ttl_days``); matching a game is then local. When the
listing is unavailable (GitHub's 60-calls-an-hour limit for anonymous use,
or a repository too big to list in one call, like MAME's), exact file names
are checked one request each instead.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .config import CONFIG_DIR, get_system_overrides
from .launchbox import name_key
from .romutils import _find_best_normalized_match

ORG = "libretro-thumbnails"
API_TREE = "https://api.github.com/repos/" + ORG + "/{repo}/git/trees/{branch}?recursive=1"
RAW = "https://raw.githubusercontent.com/" + ORG + "/{repo}/{branch}/{path}"
REPO_PAGE = "https://github.com/" + ORG + "/{repo}"
LIBRETRO_DIR = CONFIG_DIR / "libretro"
BRANCHES = ("master", "main")

# libretro folder → HyperSpin media slot.
FOLDER_SLOTS: dict[str, str] = {
    "Named_Logos": "wheel",
    "Named_Boxarts": "artwork",
    "Named_Snaps": "snap",
    "Named_Titles": "title",
}

# libretro names its files after the game with these characters as "_".
_UNSAFE = re.compile(r'[&*/:`<>?\\|"]')

# HyperSpin wheel name (casefolded) → libretro repositories, searched in
# order. Wheels not listed try "<Maker>_-_<Rest>" against KNOWN_REPOS
# ("Atari Jaguar" → Atari_-_Jaguar); ``config system set NAME
# --libretro-system REPO`` overrides both.
SYSTEMS: dict[str, tuple[str, ...]] = {
    "nintendo ds": ("Nintendo_-_Nintendo_DS",),
    "nintendo dsi": ("Nintendo_-_Nintendo_DSi", "Nintendo_-_Nintendo_DS"),
    "nintendo 3ds": ("Nintendo_-_Nintendo_3DS", "Nintendo_-_Nintendo_3DS_Digital"),
    "nintendo game boy color": ("Nintendo_-_Game_Boy_Color", "Nintendo_-_Game_Boy"),
    "nintendo entertainment system": ("Nintendo_-_Nintendo_Entertainment_System",),
    "nintendo entertainment system hacks": ("Nintendo_-_Nintendo_Entertainment_System",),
    "nintendo famicom": ("Nintendo_-_Nintendo_Entertainment_System",
                         "Nintendo_-_Family_Computer_Disk_System"),
    "nintendo famicom disk system": ("Nintendo_-_Family_Computer_Disk_System",),
    "super nintendo entertainment system": ("Nintendo_-_Super_Nintendo_Entertainment_System",),
    "super nintendo entertainment system hacks": ("Nintendo_-_Super_Nintendo_Entertainment_System",),
    "nintendo super famicom": ("Nintendo_-_Super_Nintendo_Entertainment_System",),
    "nintendo gamecube": ("Nintendo_-_GameCube",),
    "sega genesis": ("Sega_-_Mega_Drive_-_Genesis",),
    "sega mega drive": ("Sega_-_Mega_Drive_-_Genesis",),
    "sega master system": ("Sega_-_Master_System_-_Mark_III",),
    "sega cd": ("Sega_-_Mega-CD_-_Sega_CD",),
    "sega mega-cd": ("Sega_-_Mega-CD_-_Sega_CD",),
    "sony psp": ("Sony_-_PlayStation_Portable",),
    "sony playstation minis": ("Sony_-_PlayStation_Portable",),
    "atari 8-bit": ("Atari_-_8-bit_Family",),
    "nec pc engine": ("NEC_-_PC_Engine_-_TurboGrafx_16",),
    "nec turbografx-16": ("NEC_-_PC_Engine_-_TurboGrafx_16",),
    "nec pc engine-cd": ("NEC_-_PC_Engine_CD_-_TurboGrafx-CD",),
    "nec turbografx-cd": ("NEC_-_PC_Engine_CD_-_TurboGrafx-CD",),
    "nec supergrafx": ("NEC_-_PC_Engine_SuperGrafx",),
    "magnavox odyssey 2": ("Magnavox_-_Odyssey2",),
    "commodore amiga cd32": ("Commodore_-_CD32",),
    "panasonic 3do": ("The_3DO_Company_-_3DO",),
    "microsoft ms-dos": ("DOS",),
}

KNOWN_REPOS = frozenset({
    "Amstrad_-_CPC", "Amstrad_-_GX4000", "Atari_-_2600", "Atari_-_5200", "Atari_-_7800",
    "Atari_-_8-bit_Family", "Atari_-_Jaguar", "Atari_-_Lynx", "Atari_-_ST", "Bandai_-_WonderSwan",
    "Bandai_-_WonderSwan_Color", "Casio_-_Loopy", "Casio_-_PV-1000", "Coleco_-_ColecoVision",
    "Commodore_-_64", "Commodore_-_Amiga", "Commodore_-_CD32", "Commodore_-_CDTV",
    "Commodore_-_PET", "Commodore_-_Plus-4", "Commodore_-_VIC-20", "Emerson_-_Arcadia_2001",
    "Entex_-_Adventure_Vision", "Epoch_-_Super_Cassette_Vision", "Fairchild_-_Channel_F",
    "Funtech_-_Super_Acan", "GamePark_-_GP32", "GCE_-_Vectrex", "Hartung_-_Game_Master",
    "Magnavox_-_Odyssey2", "Mattel_-_Intellivision", "Microsoft_-_MSX", "Microsoft_-_MSX2",
    "Microsoft_-_Xbox", "Microsoft_-_Xbox_360", "NEC_-_PC_Engine_-_TurboGrafx_16",
    "NEC_-_PC_Engine_CD_-_TurboGrafx-CD", "NEC_-_PC_Engine_SuperGrafx", "NEC_-_PC-88",
    "NEC_-_PC-98", "NEC_-_PC-FX", "Nintendo_-_Family_Computer_Disk_System", "Nintendo_-_Game_Boy",
    "Nintendo_-_Game_Boy_Advance", "Nintendo_-_Game_Boy_Color", "Nintendo_-_GameCube",
    "Nintendo_-_Nintendo_3DS", "Nintendo_-_Nintendo_3DS_Digital", "Nintendo_-_Nintendo_64",
    "Nintendo_-_Nintendo_64DD", "Nintendo_-_Nintendo_DS", "Nintendo_-_Nintendo_DSi",
    "Nintendo_-_Nintendo_Entertainment_System", "Nintendo_-_Pokemon_Mini",
    "Nintendo_-_Satellaview", "Nintendo_-_Sufami_Turbo",
    "Nintendo_-_Super_Nintendo_Entertainment_System", "Nintendo_-_Virtual_Boy", "Nintendo_-_Wii",
    "Nintendo_-_Wii_U", "Philips_-_CD-i", "Philips_-_Videopac", "RCA_-_Studio_II",
    "Sega_-_32X", "Sega_-_Dreamcast", "Sega_-_Game_Gear", "Sega_-_Master_System_-_Mark_III",
    "Sega_-_Mega_Drive_-_Genesis", "Sega_-_Mega-CD_-_Sega_CD", "Sega_-_PICO", "Sega_-_Saturn",
    "Sega_-_SG-1000", "Sharp_-_X1", "Sharp_-_X68000", "Sinclair_-_ZX_81",
    "Sinclair_-_ZX_Spectrum", "SNK_-_Neo_Geo_CD", "SNK_-_Neo_Geo_Pocket",
    "SNK_-_Neo_Geo_Pocket_Color", "Sony_-_PlayStation", "Sony_-_PlayStation_2",
    "Sony_-_PlayStation_3", "Sony_-_PlayStation_Portable", "Sony_-_PlayStation_Vita",
    "Spectravideo_-_SVI-318_-_SVI-328", "The_3DO_Company_-_3DO", "Thomson_-_MOTO",
    "Tiger_-_Game.com", "VTech_-_CreatiVision", "VTech_-_V.Smile", "Watara_-_Supervision",
    "DOS", "ScummVM",
})
_KNOWN_CASEFOLD = {r.casefold(): r for r in KNOWN_REPOS}


class LibretroError(Exception):
    """A repository couldn't be listed or a file couldn't be checked."""


def file_stem(game_name: str) -> str:
    """The name libretro gives *game_name*'s thumbnail files."""
    return _UNSAFE.sub("_", game_name)


def _tags(name: str) -> set[str]:
    """``"Golf Ou (Japan) (SGB Enhanced)"`` → ``{"japan", "sgb enhanced"}``."""
    return {t.strip().lower() for t in re.findall(r"\(([^)]*)\)", name)}


def repos_for(system_name: str) -> list[str]:
    """libretro repositories to search for HyperSpin wheel *system_name*."""
    ovr = get_system_overrides().get(system_name, {}).get("libretro_system")
    if ovr:
        wanted = [ovr] if isinstance(ovr, str) else list(ovr)
        return [_KNOWN_CASEFOLD.get(r.replace(" ", "_").casefold(), r.replace(" ", "_"))
                for r in wanted]
    listed = SYSTEMS.get(system_name.casefold())
    if listed:
        return list(listed)
    maker, _, rest = system_name.strip().partition(" ")
    guess = f"{maker}_-_{rest}".replace(" ", "_").casefold() if rest else ""
    return [_KNOWN_CASEFOLD[guess]] if guess in _KNOWN_CASEFOLD else []


def raw_url(repo: str, branch: str, path: str) -> str:
    return RAW.format(repo=repo, branch=branch, path=quote(path))


class Listing:
    """One repository's thumbnail files: folder → {stem: (path, is_link)}."""

    def __init__(self, repo: str, branch: str, files: dict[str, dict[str, list]]):
        self.repo, self.branch, self.files = repo, branch, files
        self._keys: dict[str, dict[str, list[str]]] = {}

    def keys(self, folder: str) -> dict[str, list[str]]:
        if folder not in self._keys:
            out: dict[str, list[str]] = {}
            for stem in self.files.get(folder, {}):
                out.setdefault(name_key(stem), []).append(stem)
            self._keys[folder] = out
        return self._keys[folder]


def parse_tree(repo: str, branch: str, data: dict) -> Optional[Listing]:
    """A Listing from a git-trees API answer, or None when it was cut short."""
    if not isinstance(data, dict) or data.get("truncated") or "tree" not in data:
        return None
    files: dict[str, dict[str, list]] = {f: {} for f in FOLDER_SLOTS}
    for entry in data.get("tree") or []:
        path = entry.get("path") or ""
        folder, _, name = path.partition("/")
        if folder in files and name.lower().endswith(".png") and "/" not in name:
            files[folder][name[:-4]] = [path, entry.get("mode") == "120000"]
    return Listing(repo, branch, files)


def best_stem(listing: Listing, folder: str, game_name: str,
              threshold: float) -> Optional[tuple[str, float]]:
    """The file in *folder* for *game_name*: same name (1.0), same title with
    other tags (0.95, the closest tags), else the closest title above
    *threshold*."""
    stems = listing.files.get(folder) or {}
    exact = file_stem(game_name)
    if exact in stems:
        return exact, 1.0
    keys = listing.keys(folder)
    key = name_key(game_name)
    if not key:
        return None
    same = keys.get(key)
    if same:
        want = _tags(game_name)
        low = exact.lower()

        def closeness(stem: str) -> tuple:
            have = _tags(stem)
            # most tags in common, then fewest extra ones ("(Rev 1)"), then spelling
            return (len(want & have), -len(have - want),
                    SequenceMatcher(None, low, stem.lower()).ratio())
        return max(same, key=closeness), 0.95
    hit = _find_best_normalized_match(key, ((k, k) for k in keys), threshold)
    if not hit:
        return None
    # A close spelling never ranks with the same title.
    return keys[hit[0]][0], min(hit[1], 0.94)


class ListingCache:
    """Repository listings, cached as JSON in ``~/.spindoctor/libretro``."""

    def __init__(self, session, base: Optional[Path] = None, ttl_days: int = 30,
                 refresh: bool = False):
        self.session = session
        self.base = base or LIBRETRO_DIR
        self.ttl = timedelta(days=ttl_days) if ttl_days > 0 else None
        self.refresh = refresh           # --no-cache: list again, then save
        self._mem: dict[str, Optional[Listing]] = {}

    def _path(self, repo: str) -> Path:
        return self.base / f"{repo}.json"

    def get(self, repo: str) -> Optional[Listing]:
        """The listing, or None when GitHub can't give it (then check names one by one)."""
        if repo in self._mem:
            return self._mem[repo]
        listing = None if self.refresh else self._read(repo)
        if listing is None:
            listing = self._fetch(repo)
        self._mem[repo] = listing
        return listing

    def _read(self, repo: str) -> Optional[Listing]:
        try:
            data = json.loads(self._path(repo).read_text(encoding="utf-8"))
            if self.ttl and datetime.now() - datetime.fromisoformat(data["fetched"]) > self.ttl:
                return None
            return Listing(repo, data["branch"], data["files"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _fetch(self, repo: str) -> Optional[Listing]:
        for branch in BRANCHES:
            try:
                resp = self.session.get(API_TREE.format(repo=repo, branch=branch), timeout=30)
            except Exception:  # noqa: BLE001 — fall back to name checks
                return None
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                return None          # 403: the anonymous hourly limit, among others
            try:
                listing = parse_tree(repo, branch, resp.json())
            except ValueError:
                return None
            if listing is not None:
                try:
                    self.base.mkdir(parents=True, exist_ok=True)
                    self._path(repo).write_text(json.dumps({
                        "fetched": datetime.now().isoformat(timespec="seconds"),
                        "branch": branch, "files": listing.files,
                    }), encoding="utf-8")
                except OSError:
                    pass
            return listing
        return None


def resolve_link(session, repo: str, branch: str, path: str) -> Optional[str]:
    """Follow a symlinked thumbnail (libretro links clones to their parent).

    raw.githubusercontent.com serves a link as its target path, relative to
    the link's folder; returns the target's repository path.
    """
    try:
        resp = session.get(raw_url(repo, branch, path), timeout=20)
        if resp.status_code != 200 or len(resp.content) > 1024:
            return None
        target = resp.content.decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return None
    parts = path.split("/")[:-1]
    for bit in target.split("/"):
        if bit == "..":
            if parts:
                parts.pop()
        elif bit and bit != ".":
            parts.append(bit)
    resolved = "/".join(parts)
    return resolved if resolved.lower().endswith(".png") else None


def exists(session, repo: str, branch: str, path: str) -> bool:
    """One HEAD request: is *path* in the repository?"""
    try:
        resp = session.head(raw_url(repo, branch, path), timeout=20, allow_redirects=True)
    except Exception:  # noqa: BLE001
        return False
    return resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/")
