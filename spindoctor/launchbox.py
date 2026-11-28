"""LaunchBox Games Database as a metadata and media source.

LaunchBox publishes its whole games database as one ``Metadata.zip``
(about 100 MB, rebuilt daily) at :data:`METADATA_URL`, with no API key and
no request allowance. ``spindoctor launchbox-db update --apply`` downloads
it once and indexes the parts SpinDoctor uses into a small SQLite file;
after that every lookup is local. Images are fetched from
:data:`IMAGE_BASE` only when ``fetch-media --apply`` downloads them.

The index keeps, per game: platform, name and alternate names (as match
keys), year, developer, publisher, genres, ESRB rating, players, and the
image types in :data:`IMAGE_SLOTS`.
"""
from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from .config import CONFIG_DIR, get_system_overrides
from .romutils import _find_best_normalized_match, normalize

METADATA_URL = "https://gamesdb.launchbox-app.com/Metadata.zip"
IMAGE_BASE = "https://images.launchbox-app.com/"
GAME_PAGE = "https://gamesdb.launchbox-app.com/games/details/"
LAUNCHBOX_DIR = CONFIG_DIR / "launchbox"
ZIP_NAME = "Metadata.zip"
INDEX_NAME = "launchbox.sqlite"

# LaunchBox image type → HyperSpin media slot (first type listed wins).
IMAGE_SLOTS: dict[str, str] = {
    "Clear Logo": "wheel",
    "Box - Front": "artwork",
    "Box - Front - Reconstructed": "artwork",
    "Screenshot - Gameplay": "snap",
    "Screenshot - Game Title": "title",
    "Fanart - Background": "background",
}

# HyperSpin wheel names whose LaunchBox platform has another name (or that
# can borrow a related platform's entries). A wheel whose name *is* a
# LaunchBox platform needs no entry; names not in the index are skipped.
# ``config system set NAME --launchbox-platform P`` overrides both.
PLATFORM_ALIASES: dict[str, tuple[str, ...]] = {
    "nintendo famicom": ("Nintendo Entertainment System", "Nintendo Famicom Disk System"),
    "nintendo famicom disk system": ("Nintendo Famicom Disk System", "Nintendo Entertainment System"),
    "nintendo super famicom": ("Super Nintendo Entertainment System",),
    "nintendo entertainment system hacks": ("Nintendo Entertainment System",),
    "super nintendo entertainment system hacks": ("Super Nintendo Entertainment System",),
    "nintendo game boy color": ("Nintendo Game Boy Color", "Nintendo Game Boy"),
    "nintendo dsi": ("Nintendo DSi", "Nintendo DS"),
    "sony playstation minis": ("Sony PSP Minis", "Sony PSP"),
    "sony psp minis": ("Sony PSP Minis", "Sony PSP"),
    "sony playstation portable": ("Sony PSP",),
    "nec pc engine": ("NEC TurboGrafx-16",),
    "nec pc engine-cd": ("NEC TurboGrafx-CD",),
    "nec turbografx-cd": ("NEC TurboGrafx-CD",),
    "sega mega drive": ("Sega Genesis",),
    "sega mega-cd": ("Sega CD",),
    "microsoft ms-dos": ("MS-DOS",),
    "pc games": ("Windows",),
    "nokia n-gage 2.0": ("Nokia N-Gage",),
}

_TAGS = re.compile(r"\s*(\([^)]*\)|\[[^\]]*\])")
_TRAILING_ARTICLE = re.compile(r"^(?P<rest>.+?),\s*(?P<art>the|a|an)\b(?P<tail>.*)$", re.IGNORECASE)

# ROM-name region tag → LaunchBox image regions to prefer, best first.
_REGION_PREFS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("usa", ("North America", "United States", "World", "")),
    ("world", ("World", "North America", "United States", "")),
    ("japan", ("Japan", "World", "")),
    ("europe", ("Europe", "World", "United Kingdom", "")),
    ("uk", ("United Kingdom", "Europe", "World", "")),
    ("germany", ("Germany", "Europe", "World", "")),
    ("france", ("France", "Europe", "World", "")),
    ("spain", ("Spain", "Europe", "World", "")),
    ("italy", ("Italy", "Europe", "World", "")),
)
_DEFAULT_REGIONS = ("North America", "United States", "World", "", "Europe")


class LaunchBoxError(Exception):
    """The LaunchBox database is missing, unreadable or couldn't be fetched."""


def name_key(name: str) -> str:
    """Match key for a ROM name or a LaunchBox title.

    Drops ``(...)``/``[...]`` tags, puts a trailing article back in front
    (``Legend of Zelda, The - …`` → ``The Legend of Zelda - …``), reads
    ``&`` as "and", strips accents, then :func:`normalize`s, so
    ``007 - Blood Stone (USA)`` and ``007: Blood Stone`` share a key.
    """
    s = _TAGS.sub("", name or "").strip()
    m = _TRAILING_ARTICLE.match(s)
    if m:
        s = f"{m.group('art')} {m.group('rest')}{m.group('tail')}"
    s = s.replace("&", " and ")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return normalize(s)


def region_order(game_name: str) -> tuple[str, ...]:
    """LaunchBox image regions to prefer for *game_name*'s region tags."""
    tags = " ".join(t.lower() for t in re.findall(r"\(([^)]*)\)", game_name or ""))
    for tag, prefs in _REGION_PREFS:
        if re.search(rf"\b{tag}\b", tags):
            return prefs
    return _DEFAULT_REGIONS


# ─── download ─────────────────────────────────────────────────────────────────

def remote_info(session, url: str = METADATA_URL) -> tuple[Optional[int], str]:
    """``(size in bytes, Last-Modified)`` of the published Metadata.zip."""
    try:
        resp = session.head(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 — reported to the user as is
        raise LaunchBoxError(f"LaunchBox database unreachable: {e}") from e
    size = resp.headers.get("Content-Length")
    return (int(size) if size and size.isdigit() else None,
            resp.headers.get("Last-Modified", ""))


def download(
    session,
    dest: Path,
    url: str = METADATA_URL,
    progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> int:
    """Download Metadata.zip to *dest* (via a ``.part`` file); return bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done = 0
    try:
        with session.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = resp.headers.get("Content-Length")
            total_n = int(total) if total and total.isdigit() else None
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total_n)
        if not zipfile.is_zipfile(part):
            raise LaunchBoxError("LaunchBox download is not a zip file")
        os.replace(part, dest)
    except Exception as e:  # noqa: BLE001 — a half file never replaces the old one
        try:
            part.unlink()
        except OSError:
            pass
        if isinstance(e, LaunchBoxError):
            raise
        raise LaunchBoxError(f"LaunchBox download failed: {e}") from e
    return done


# ─── index ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE games (id TEXT PRIMARY KEY, platform TEXT, name TEXT, year TEXT,
                    developer TEXT, publisher TEXT, genres TEXT, esrb TEXT, players TEXT);
CREATE TABLE names (key TEXT, id TEXT);
CREATE TABLE images (id TEXT, type TEXT, file TEXT, region TEXT);
CREATE TABLE info (k TEXT PRIMARY KEY, v TEXT);
"""
_INDEXES = """
CREATE INDEX names_by_key ON names(key);
CREATE INDEX names_by_id ON names(id);
CREATE INDEX games_by_platform ON games(platform);
CREATE INDEX images_by_id ON images(id);
"""


def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def build_index(zip_path: Path, index_path: Path) -> int:
    """Read ``Metadata.xml`` from *zip_path* into *index_path*; return games.

    Streams the XML (it is several hundred MB) and writes a fresh file
    beside the old one, which replaces it only when complete.
    """
    tmp = index_path.with_name(index_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(tmp))
    games = 0
    try:
        con.executescript(_SCHEMA)
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith("metadata.xml")), None)
            if member is None:
                raise LaunchBoxError(f"{zip_path.name} has no Metadata.xml")
            with zf.open(member) as stream:
                root = None
                for event, elem in ET.iterparse(stream, events=("start", "end")):
                    if root is None:
                        root = elem
                        continue
                    if event != "end":
                        continue
                    tag = elem.tag
                    if tag == "Game":
                        gid = _text(elem, "DatabaseID")
                        name = _text(elem, "Name")
                        if gid and name:
                            year = _text(elem, "ReleaseYear") or _text(elem, "ReleaseDate")[:4]
                            con.execute(
                                "INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?)",
                                (gid, _text(elem, "Platform"), name, year,
                                 _text(elem, "Developer"), _text(elem, "Publisher"),
                                 _text(elem, "Genres"), _text(elem, "ESRB"),
                                 _text(elem, "MaxPlayers")),
                            )
                            con.execute("INSERT INTO names VALUES (?,?)", (name_key(name), gid))
                            games += 1
                    elif tag == "GameAlternateName":
                        gid = _text(elem, "DatabaseID")
                        alt = _text(elem, "AlternateName")
                        if gid and alt:
                            con.execute("INSERT INTO names VALUES (?,?)", (name_key(alt), gid))
                    elif tag == "GameImage":
                        kind = _text(elem, "Type")
                        if kind in IMAGE_SLOTS:
                            gid = _text(elem, "DatabaseID")
                            fname = _text(elem, "FileName")
                            if gid and fname:
                                con.execute("INSERT INTO images VALUES (?,?,?,?)",
                                            (gid, kind, fname, _text(elem, "Region")))
                    else:
                        continue
                    # Each top-level entry is done with: drop it, and the
                    # root's growing list of finished children with it.
                    root.clear()
        con.executescript(_INDEXES)
        con.execute("INSERT INTO info VALUES ('built', ?)",
                    (datetime.now().isoformat(timespec="seconds"),))
        con.execute("INSERT INTO info VALUES ('games', ?)", (str(games),))
        con.commit()
    except Exception:
        con.close()
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    con.close()
    os.replace(tmp, index_path)
    return games


class LaunchBoxIndex:
    """Read-only lookups in the index :func:`build_index` writes."""

    def __init__(self, index_path: Path):
        if not index_path.is_file():
            raise LaunchBoxError(
                "LaunchBox database not downloaded yet. Run: "
                "spindoctor launchbox-db update --apply (about 100 MB, once)"
            )
        self._con = sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True)
        self._con.row_factory = sqlite3.Row
        self._platforms: Optional[dict[str, str]] = None
        self._keys: dict[tuple, dict[str, list[str]]] = {}

    def info(self) -> dict[str, str]:
        return {r["k"]: r["v"] for r in self._con.execute("SELECT k, v FROM info")}

    def platforms(self) -> dict[str, str]:
        """Casefolded platform name → LaunchBox's own spelling."""
        if self._platforms is None:
            self._platforms = {
                r[0].casefold(): r[0]
                for r in self._con.execute("SELECT DISTINCT platform FROM games") if r[0]
            }
        return self._platforms

    def _games(self, ids: Iterable[str], platforms: list[str]) -> list[sqlite3.Row]:
        ids = list(dict.fromkeys(ids))
        if not ids or not platforms:
            return []
        q = (f"SELECT * FROM games WHERE id IN ({','.join('?' * len(ids))}) "
             f"AND platform IN ({','.join('?' * len(platforms))})")
        rows = self._con.execute(q, [*ids, *platforms]).fetchall()
        order = {p: i for i, p in enumerate(platforms)}   # earlier platform first
        return sorted(rows, key=lambda r: order.get(r["platform"], len(order)))

    def exact(self, platforms: list[str], key: str) -> list[sqlite3.Row]:
        ids = [r[0] for r in self._con.execute("SELECT id FROM names WHERE key = ?", (key,))]
        return self._games(ids, platforms)

    def fuzzy(self, platforms: list[str], key: str, threshold: float) -> list[tuple[sqlite3.Row, float]]:
        """The closest title on *platforms* at or above *threshold*."""
        pkey = tuple(platforms)
        keys = self._keys.get(pkey)
        if keys is None:
            keys = {}
            q = (f"SELECT n.key, n.id FROM names n JOIN games g ON g.id = n.id "
                 f"WHERE g.platform IN ({','.join('?' * len(platforms))})")
            for k, gid in self._con.execute(q, platforms):
                keys.setdefault(k, []).append(gid)
            self._keys[pkey] = keys
        best = _find_best_normalized_match(key, ((k, k) for k in keys), threshold)
        if not best:
            return []
        return [(row, best[1]) for row in self._games(keys[best[0]], platforms)]

    def by_id(self, gid: str) -> Optional[sqlite3.Row]:
        return self._con.execute("SELECT * FROM games WHERE id = ?", (gid,)).fetchone()

    def images(self, gid: str) -> list[sqlite3.Row]:
        return self._con.execute(
            "SELECT type, file, region FROM images WHERE id = ? ORDER BY rowid", (gid,)
        ).fetchall()

    def close(self) -> None:
        self._con.close()


def platforms_for(system_name: str, known: dict[str, str]) -> list[str]:
    """LaunchBox platforms to search for HyperSpin wheel *system_name*."""
    ovr = get_system_overrides().get(system_name, {}).get("launchbox_platform")
    if ovr:
        wanted = [ovr] if isinstance(ovr, str) else list(ovr)
        return [known.get(p.casefold(), p) for p in wanted]
    found: list[str] = []
    own = known.get(system_name.casefold())
    if own:
        found.append(own)
    for alias in PLATFORM_ALIASES.get(system_name.casefold(), ()):
        name = known.get(alias.casefold())
        if name and name not in found:
            found.append(name)
    return found


def local_status(base: Optional[Path] = None) -> dict[str, object]:
    """What's on disk: zip size and date, index games and build time."""
    base = base or LAUNCHBOX_DIR
    zip_path, index_path = base / ZIP_NAME, base / INDEX_NAME
    out: dict[str, object] = {"zip": None, "index": None}
    if zip_path.is_file():
        st = zip_path.stat()
        out["zip"] = {"size": st.st_size,
                      "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}
    if index_path.is_file():
        try:
            idx = LaunchBoxIndex(index_path)
            out["index"] = idx.info()
            out["platforms"] = len(idx.platforms())
            idx.close()
        except (LaunchBoxError, sqlite3.Error) as e:
            out["index_error"] = str(e)
    return out
