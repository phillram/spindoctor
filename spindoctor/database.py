"""Hyperspin XML database read/write.

Uses ``lxml`` when available so that comments, attribute order, and any custom
elements added by HyperHQ / Don's tools survive a save round-trip.  Falls back
to ``xml.etree.ElementTree`` (which loses comments) with a one-time warning.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from ._compat import et_indent

# lxml is imported lazily so PyInstaller can exclude it from the lightweight
# standalone EXEs (spindoctor-fav, spindoctor-recent, spindoctor-stats) via
# --exclude-module lxml.  The full CLI and GUI still get lxml bundled because
# they list lxml.etree as a hidden import.  Without lxml the stdlib ET fallback
# is used, which loses XML comment round-tripping but is otherwise correct.
_LXML_NOT_CHECKED = object()
_LET = _LXML_NOT_CHECKED  # type: ignore


def _lxml_etree():
    """Return the lxml.etree module if available, else None."""
    global _LET
    if _LET is _LXML_NOT_CHECKED:
        try:
            from lxml import etree  # type: ignore  # noqa: PLC0415
            _LET = etree
        except ImportError:
            _LET = None
    return _LET

# Order in which fields are emitted for new <game> elements (HyperSpin convention).
# ``players`` sits next to ``rating`` — both are short, optional descriptors and
# HyperHQ-exported XMLs typically place them adjacent.
_FIELD_ORDER = (
    "description", "cloneof", "crc", "manufacturer",
    "year", "genre", "rating", "players", "enabled",
)

_LXML_WARNED = False


def resolve_atomic_tmp_dir(target: Path, configured: Optional[Path]) -> Path:
    """Return the directory to use for the atomic temp file.

    *configured* is the user's ``atomic_tmp_dir`` setting (or ``None`` when
    unset).  When set we try to use it — but ``os.replace()`` only works
    within the same filesystem/volume, so we verify that *configured* and
    *target.parent* are on the same device before committing to it.  If
    they're on different drives, or the directory can't be created, we fall
    back silently to *target.parent* (the original behaviour).

    This function is public so ``favorites.py`` (and any future write path)
    can use the same resolution logic without duplicating it.
    """
    if configured is None:
        return target.parent
    try:
        configured.mkdir(parents=True, exist_ok=True)
        if os.stat(configured).st_dev == os.stat(target.parent).st_dev:
            return configured
    except OSError:
        pass
    return target.parent


def _atomic_write_bytes(target: Path, data: bytes,
                        tmp_dir: Optional[Path] = None) -> None:
    """Write *data* to *target* via a temp file + atomic rename.

    Direct writes leave a window where an interrupted save (power cut,
    forced shutdown) produces a truncated, unparseable XML — HyperSpin
    can't open the wheel until the file is manually restored from the
    ``.bak``.  Writing to a sibling temp file and then calling
    ``os.replace`` guarantees the live path is always either the previous
    complete version or the new complete version — never a partial write.

    *tmp_dir* is the directory for the temp file (from ``config.atomic_tmp_dir``).
    Pass ``None`` to fall back to ``target.parent`` (the previous default).
    :func:`resolve_atomic_tmp_dir` handles the same-filesystem check.
    """
    write_dir = resolve_atomic_tmp_dir(target, tmp_dir)
    fd, tmp = tempfile.mkstemp(dir=write_dir, suffix=".tmp")
    try:
        os.write(fd, data)
        os.close(fd)
        fd = -1
        os.replace(tmp, target)
        tmp = None
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def _atomic_write_via_tree(target: Path, tree_write_fn,
                           tmp_dir: Optional[Path] = None) -> None:
    """Call *tree_write_fn(file_obj)* into a temp file, then rename atomically.

    *tmp_dir* has the same semantics as in :func:`_atomic_write_bytes`.
    """
    write_dir = resolve_atomic_tmp_dir(target, tmp_dir)
    fd, tmp = tempfile.mkstemp(dir=write_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            tree_write_fn(f)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _warn_no_lxml_once() -> None:
    global _LXML_WARNED
    if not _LXML_WARNED:
        _LXML_WARNED = True
        warnings.warn(
            "lxml not installed; XML comments and attribute order will not be "
            "preserved on round-trip. Install with: pip install spindoctor[xml]",
            RuntimeWarning,
            stacklevel=2,
        )


_KNOWN_GAME_ATTRS = frozenset({"name", "enabled"})


@dataclass
class GameEntry:
    name: str
    description: str = ""
    cloneof: str = ""
    crc: str = ""
    manufacturer: str = ""
    year: str = ""
    genre: str = ""
    rating: str = ""
    players: str = ""
    enabled: str = "Yes"
    # Round-trip bag for attributes SpinDoctor doesn't model natively
    # (e.g. HyperSpin's ``exe="true"`` on the Search entry). Anything not in
    # _KNOWN_GAME_ATTRS is captured here on load and re-applied on save so
    # third-party / HyperHQ extensions survive a rewrite.
    extra_attrs: dict = field(default_factory=dict)

    def is_metadata_complete(self) -> bool:
        return all([self.description, self.manufacturer, self.year, self.genre])

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.description:
            missing.append("description")
        if not self.manufacturer:
            missing.append("manufacturer")
        if not self.year:
            missing.append("year")
        if not self.genre:
            missing.append("genre")
        return missing


class HyperspinDatabase:
    def __init__(
        self,
        system_name: str,
        xml_path: Path,
        enabled_as_attribute: bool = False,
    ):
        self.system_name = system_name
        self.xml_path = xml_path
        # Main Menu.xml uses ``<game name="..." enabled="False"/>`` (attribute),
        # while per-system game databases use ``<enabled>No</enabled>`` (child).
        # Hyperspin's two loaders honour different conventions, so callers tell
        # us which schema to read and write.
        self._enabled_as_attribute = enabled_as_attribute
        self._games: dict[str, GameEntry] = {}
        self._loaded = False
        # Tracks the parsed tree and per-game element refs for in-place updates
        # so comments / custom attributes survive round-trip.
        self._tree: Any = None
        self._root: Any = None
        self._game_elements: dict[str, Any] = {}

    # ── load ───────────────────────────────────────────────────────────────────

    def load(self) -> None:
        if not self.xml_path.exists():
            self._loaded = True
            return
        LET = _lxml_etree()
        try:
            # Open the file ourselves and pass the handle into the
            # parser so the OS lock is released as soon as parsing
            # finishes. Passing a *path* to lxml/ET keeps the file
            # open on Windows until the tree is GC'd — which then
            # blocks any concurrent rename / save / migrate touching
            # the same XML.
            if LET is not None:
                # ``remove_blank_text=True`` strips whitespace-only text nodes
                # at parse time, which is the precondition for lxml's
                # ``pretty_print=True`` to actually re-indent on write. Without
                # it, single-line input files round-trip as single-line output.
                parser = LET.XMLParser(remove_comments=False, remove_blank_text=True)
                with open(self.xml_path, "rb") as fh:
                    self._tree = LET.parse(fh, parser)
            else:
                _warn_no_lxml_once()
                with open(self.xml_path, "rb") as fh:
                    self._tree = ET.parse(fh)

            self._root = self._tree.getroot()
            for game_el in self._root.findall("game"):
                name = (game_el.get("name") or "").strip()
                if not name:
                    continue
                extras = {
                    k: v for k, v in game_el.attrib.items()
                    if k not in _KNOWN_GAME_ATTRS
                }
                self._games[name] = GameEntry(
                    name=name,
                    description=_text(game_el, "description"),
                    cloneof=_text(game_el, "cloneof"),
                    crc=_text(game_el, "crc"),
                    manufacturer=_text(game_el, "manufacturer"),
                    year=_text(game_el, "year"),
                    genre=_text(game_el, "genre"),
                    rating=_text(game_el, "rating"),
                    players=_text(game_el, "players"),
                    enabled=_read_enabled(game_el, self._enabled_as_attribute),
                    extra_attrs=extras,
                )
                self._game_elements[name] = game_el
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse {self.xml_path}: {e}") from e
        except Exception as e:  # noqa: BLE001 - re-raise non-parse errors
            if LET is not None and isinstance(e, LET.XMLSyntaxError):
                raise ValueError(f"Failed to parse {self.xml_path}: {e}") from e
            raise
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ── accessors ──────────────────────────────────────────────────────────────

    def games(self) -> dict[str, GameEntry]:
        self._ensure_loaded()
        return self._games

    def iter_xml_order(self) -> Iterator[GameEntry]:
        """Yield games in their original XML element order.

        When lxml is available, the order is derived from the parsed element
        tree rather than the insertion-order dict — this matters for the Main
        Menu XML, where HyperSpin honours wheel position by element order.
        Falls back to dict iteration (which preserves insertion order in
        Python 3.7+) when the tree is not available.
        """
        self._ensure_loaded()
        if self._root is not None:
            for game_el in self._root.findall("game"):
                name = (game_el.get("name") or "").strip()
                if name and name in self._games:
                    yield self._games[name]
        else:
            yield from self._games.values()

    def get(self, name: str) -> Optional[GameEntry]:
        self._ensure_loaded()
        return self._games.get(name)

    def contains(self, name: str) -> bool:
        self._ensure_loaded()
        return name in self._games

    def update_game(self, game: GameEntry) -> None:
        self._ensure_loaded()
        if game.name in self._games:
            self._games[game.name] = game

    def upsert_game(self, game: GameEntry) -> None:
        self._ensure_loaded()
        self._games[game.name] = game

    def remove_game(self, name: str) -> bool:
        self._ensure_loaded()
        if name in self._games:
            del self._games[name]
            return True
        return False

    def reset_games(self) -> None:
        """Drop every game from both the dict and the parsed XML tree.

        Synthetic systems (Favorites, Recently Played, Most Played) own
        their XML end-to-end and want full control over entry order on
        each rebuild. Without this, ``_merge_into_tree`` would leave
        surviving ``<game>`` elements in their original positions.
        """
        self._ensure_loaded()
        self._games.clear()
        if self._root is not None:
            for el in list(self._game_elements.values()):
                self._root.remove(el)
        self._game_elements.clear()

    def iter_incomplete(self) -> Iterator[GameEntry]:
        self._ensure_loaded()
        return (g for g in self._games.values() if not g.is_metadata_complete())

    # ── save ───────────────────────────────────────────────────────────────────

    def save(
        self,
        output_path: Optional[Path] = None,
        backup: bool = True,
        backup_dir: Optional[Path] = None,
        tmp_dir: Optional[Path] = None,
    ) -> Path:
        """Persist the database to disk.

        *tmp_dir* is the scratch directory for the atomic temp file —
        pass ``config.effective_atomic_tmp_dir`` here.  When ``None``
        the temp file lands next to the target (original behaviour).
        :func:`resolve_atomic_tmp_dir` handles the same-filesystem check
        so a cross-drive *tmp_dir* is silently ignored.
        """
        self._ensure_loaded()
        target = output_path or self.xml_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if backup and target.exists() and output_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if backup_dir is not None:
                subfolder = backup_dir / "HyperSpin"
                try:
                    subfolder.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise OSError(
                        f"Cannot create backup folder '{subfolder}': {exc}. "
                        f"Check that backup_dir '{backup_dir}' exists and is writable."
                    ) from exc
                bak_path = subfolder / f"{target.stem}.{stamp}.bak"
            else:
                bak_path = target.with_suffix(f".{stamp}.bak")
            try:
                shutil.copy2(target, bak_path)
            except OSError as exc:
                raise OSError(
                    f"Cannot write backup '{bak_path}': {exc}"
                ) from exc

        # In-place merge path: an original tree exists, so update it so that
        # comments / unknown elements are preserved.
        if self._tree is not None and self._root is not None:
            self._merge_into_tree()
            self._write_tree(target, tmp_dir=tmp_dir)
        else:
            self._write_fresh(target, tmp_dir=tmp_dir)

        return target

    # Update the existing tree in place to match self._games.
    def _merge_into_tree(self) -> None:
        attr_mode = self._enabled_as_attribute
        # 1) Update / remove existing <game> elements.
        for name, el in list(self._game_elements.items()):
            if name in self._games:
                _update_game_element(el, self._games[name], enabled_as_attribute=attr_mode)
            else:
                self._root.remove(el)
                del self._game_elements[name]

        # 2) Append new <game> elements for games not already present.
        for name, game in self._games.items():
            if name not in self._game_elements:
                el = _new_game_element(game, enabled_as_attribute=attr_mode)
                self._root.append(el)
                self._game_elements[name] = el

        # Refresh header timestamp if present.
        hdr = self._root.find("header")
        if hdr is not None:
            last = hdr.find("lastlistupdate")
            if last is not None:
                last.text = datetime.now().strftime("%Y-%m-%d")

    def _write_tree(self, target: Path,
                    tmp_dir: Optional[Path] = None) -> None:
        # HyperSpin's native Main Menu.xml has no XML declaration; emitting
        # one is tolerated by some skins but ships strictly without it.
        want_decl = not self._enabled_as_attribute
        LET = _lxml_etree()
        if LET is not None and isinstance(self._tree, LET._ElementTree):
            xml_bytes = LET.tostring(
                self._tree,
                pretty_print=True,
                xml_declaration=want_decl,
                encoding="UTF-8" if want_decl else None,
            )
            _atomic_write_bytes(target, xml_bytes, tmp_dir=tmp_dir)
        else:
            et_indent(self._tree)
            def _et_write(f):
                if want_decl:
                    f.write(b'<?xml version="1.0"?>\n')
                self._tree.write(f, encoding="utf-8", xml_declaration=False)
            _atomic_write_via_tree(target, _et_write, tmp_dir=tmp_dir)

    # Build a brand-new tree from scratch.  Used the first time a DB is created.
    def _write_fresh(self, target: Path,
                     tmp_dir: Optional[Path] = None) -> None:
        attr_mode = self._enabled_as_attribute
        LET = _lxml_etree()
        if LET is not None:
            root = LET.Element("menu")
        else:
            _warn_no_lxml_once()
            root = ET.Element("menu")

        # Main Menu native format has no <header> block — only per-system DBs do.
        if not attr_mode:
            hdr = LET.SubElement(root, "header") if LET is not None else ET.SubElement(root, "header")
            _set_text(hdr, "listname", self.system_name)
            _set_text(hdr, "lastlistupdate", datetime.now().strftime("%Y-%m-%d"))
            _set_text(hdr, "listversion", "2.0")
            _set_text(hdr, "exporterversion", "SpinDoctor")

        # Main Menu preserves the user's order (HyperSpin honours XML order
        # for the wheel); per-system DBs sort alphabetically for stability.
        if attr_mode:
            games_iter = self._games.values()
        else:
            games_iter = sorted(self._games.values(), key=lambda g: g.name.lower())
        for game in games_iter:
            _new_game_element(game, root=root, enabled_as_attribute=attr_mode)

        want_decl = not attr_mode
        if LET is not None:
            tree = LET.ElementTree(root)
            xml_bytes = LET.tostring(
                tree,
                pretty_print=True,
                xml_declaration=want_decl,
                encoding="UTF-8" if want_decl else None,
            )
            _atomic_write_bytes(target, xml_bytes, tmp_dir=tmp_dir)
        else:
            tree = ET.ElementTree(root)
            et_indent(tree)
            def _et_write_fresh(f):
                if want_decl:
                    f.write(b'<?xml version="1.0"?>\n')
                tree.write(f, encoding="utf-8", xml_declaration=False)
            _atomic_write_via_tree(target, _et_write_fresh, tmp_dir=tmp_dir)


# ─── helpers ───────────────────────────────────────────────────────────────────

def find_database(system_name: str, databases_dir: Path) -> Optional[Path]:
    """Locate the XML database file for a system."""
    system_db_dir = databases_dir / system_name
    if not system_db_dir.exists():
        return None
    candidates = list(system_db_dir.glob("*.xml"))
    if not candidates:
        return None
    for c in candidates:
        if c.stem.lower() == system_name.lower():
            return c
    return candidates[0]


def load_database(system_name: str, databases_dir: Path) -> HyperspinDatabase:
    xml_path = find_database(system_name, databases_dir)
    if xml_path is None:
        xml_path = databases_dir / system_name / f"{system_name}.xml"
    db = HyperspinDatabase(system_name, xml_path)
    db.load()
    return db


def _text(el, tag: str) -> str:
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _set_text(parent, tag: str, text: str):
    """Append a child <tag>text</tag> to ``parent`` and return it."""
    LET = _lxml_etree()
    if LET is not None and hasattr(parent, "nsmap"):
        el = LET.SubElement(parent, tag)
    else:
        el = ET.SubElement(parent, tag)
    el.text = text or ""
    return el


def _update_game_element(el, game: "GameEntry", enabled_as_attribute: bool = False) -> None:
    """Update text on existing field children; add any missing fields.

    When ``enabled_as_attribute`` is True (Main Menu.xml), the entry uses
    HyperSpin's native minimal format: ``<game name="..." />`` with no child
    elements. ``enabled="False"`` is written ONLY when the system is hidden;
    visible systems have no ``enabled`` attribute at all (matching the format
    HyperSpin itself ships). Any legacy ``<enabled>`` child is stripped so
    files migrate forward, and unknown attributes (e.g. ``exe="true"`` on the
    Search entry) are preserved via ``game.extra_attrs``.
    """
    if enabled_as_attribute:
        if el.get("name") != game.name:
            el.set("name", game.name)
        if _enabled_to_bool_str(game.enabled or "Yes") == "False":
            el.set("enabled", "False")
        elif "enabled" in el.attrib:
            del el.attrib["enabled"]
        stale = el.find("enabled")
        if stale is not None:
            el.remove(stale)
        for key, value in (game.extra_attrs or {}).items():
            if key in _KNOWN_GAME_ATTRS:
                continue
            el.set(key, value)
        return

    el.set("name", game.name)
    if "enabled" in el.attrib:
        # Per-system databases: HyperSpin reads the ``<enabled>`` child;
        # a stray attribute is meaningless and confuses validators.
        del el.attrib["enabled"]
    for field_name in _FIELD_ORDER:
        value = getattr(game, field_name, "") or ""
        # Preserve description fallback to game name (HyperSpin requires a value).
        if field_name == "description" and not value:
            value = game.name
        if field_name == "enabled" and not value:
            value = "Yes"
        child = el.find(field_name)
        if child is None:
            # Skip optional fields that have no value rather than emitting
            # empty placeholder elements.  ``players`` is an opt-in tag and
            # adding ``<players></players>`` would be misleading.
            if field_name == "players" and not value:
                continue
            _set_text(el, field_name, value)
        else:
            child.text = value
    for key, value in (game.extra_attrs or {}).items():
        if key in _KNOWN_GAME_ATTRS:
            continue
        el.set(key, value)


# ─── secondary sort databases ─────────────────────────────────────────────────

# HyperSpin reads these per-system sub-folders to build "Sort by …" wheels.
SORT_AXES: tuple[str, ...] = ("genre", "manufacturer", "year", "letter")


def _letter_bucket(name: str) -> str:
    """Return the alphabetical bucket for *name* — A–Z, "0–9" for digits, "#" else."""
    if not name:
        return "#"
    first = name.lstrip().lstrip("[(").lstrip()[:1].upper()
    if first.isalpha():
        return first
    if first.isdigit():
        return "0-9"
    return "#"


def _bucket_value(game: "GameEntry", axis: str) -> str:
    if axis == "genre":
        return (game.genre or "").strip()
    if axis == "manufacturer":
        return (game.manufacturer or "").strip()
    if axis == "year":
        return (game.year or "").strip()
    if axis == "letter":
        return _letter_bucket(game.description or game.name)
    return ""


def write_sort_databases(
    system_name: str,
    games: list["GameEntry"],
    databases_dir: Path,
    *,
    axes: tuple[str, ...] = SORT_AXES,
    overwrite: bool = False,
    tmp_dir: Optional[Path] = None,
) -> dict[str, list[Path]]:
    """Write per-axis HyperSpin sort databases for *system_name*.

    Files go to ``<databases_dir>/<system_name>/<Axis>/<Bucket>.xml`` where
    *Axis* is one of "Genre", "Manufacturer", "Year", "Letter".  Each XML
    lists the games belonging to that bucket.

    By default existing files are skipped (so user-curated lists survive).
    Pass ``overwrite=True`` to replace them.

    *tmp_dir* is the scratch directory for atomic temp files — pass
    ``config.effective_atomic_tmp_dir`` so writes land on the same
    filesystem as the target and ``os.replace`` stays atomic.

    Returns a dict {axis: [written_paths]}.
    """
    written: dict[str, list[Path]] = {a: [] for a in axes}
    sys_dir = databases_dir / system_name

    for axis in axes:
        if axis not in SORT_AXES:
            continue
        buckets: dict[str, list["GameEntry"]] = {}
        for g in games:
            value = _bucket_value(g, axis)
            if not value:
                continue
            buckets.setdefault(value, []).append(g)

        if not buckets:
            continue

        axis_dir = sys_dir / axis.capitalize()
        axis_dir.mkdir(parents=True, exist_ok=True)

        for bucket_name, bucket_games in buckets.items():
            safe = _safe_bucket_filename(bucket_name)
            out_path = axis_dir / f"{safe}.xml"
            if out_path.exists() and not overwrite:
                continue

            root = ET.Element("menu")
            hdr = ET.SubElement(root, "header")
            _set_text(hdr, "listname", f"{system_name} — {axis}: {bucket_name}")
            _set_text(hdr, "lastlistupdate", datetime.now().strftime("%Y-%m-%d"))
            _set_text(hdr, "listversion", "2.0")
            _set_text(hdr, "exporterversion", "SpinDoctor")

            for g in sorted(bucket_games, key=lambda x: (x.description or x.name).lower()):
                _new_game_element(g, root=root)

            tree = ET.ElementTree(root)
            et_indent(tree)
            _atomic_write_via_tree(
                out_path,
                lambda f, _t=tree: (
                    f.write(b'<?xml version="1.0"?>\n'),
                    _t.write(f, encoding="utf-8", xml_declaration=False),
                ),
                tmp_dir=tmp_dir,
            )
            written[axis].append(out_path)

    return written


_BUCKET_FILE_SAFE = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")


def _safe_bucket_filename(name: str) -> str:
    """Sanitize a bucket value so it's a legal Windows/macOS/Linux filename."""
    for ch in _BUCKET_FILE_SAFE:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".") or "_"


def _new_game_element(game: "GameEntry", root=None, enabled_as_attribute: bool = False):
    """Build a fresh <game> element.

    For Main Menu (``enabled_as_attribute=True``), produces HyperSpin's
    native minimal format: ``<game name="..."/>`` with ``enabled="False"``
    only when hidden, and no child elements. Unknown attributes are carried
    over from ``game.extra_attrs`` so HyperSpin-specific attrs like
    ``exe="true"`` on the Search entry survive a rewrite.

    For per-system databases (``enabled_as_attribute=False``), produces the
    full HyperHQ schema with ``<description>``, ``<manufacturer>``, etc.
    """
    LET = _lxml_etree()
    if LET is not None and (root is None or hasattr(root, "nsmap")):
        if root is not None:
            el = LET.SubElement(root, "game")
        else:
            el = LET.Element("game")
    else:
        if root is not None:
            el = ET.SubElement(root, "game")
        else:
            el = ET.Element("game")

    el.set("name", game.name)
    if enabled_as_attribute:
        if _enabled_to_bool_str(game.enabled or "Yes") == "False":
            el.set("enabled", "False")
        for key, value in (game.extra_attrs or {}).items():
            if key in _KNOWN_GAME_ATTRS:
                continue
            el.set(key, value)
        return el

    _set_text(el, "description", game.description or game.name)
    _set_text(el, "cloneof", game.cloneof)
    _set_text(el, "crc", game.crc)
    _set_text(el, "manufacturer", game.manufacturer)
    _set_text(el, "year", game.year)
    _set_text(el, "genre", game.genre)
    _set_text(el, "rating", game.rating)
    # Only emit <players> when populated — HyperSpin treats an empty
    # element as "1 player" in some skins, which is misleading.
    if game.players:
        _set_text(el, "players", game.players)
    _set_text(el, "enabled", game.enabled or "Yes")
    for key, value in (game.extra_attrs or {}).items():
        if key in _KNOWN_GAME_ATTRS:
            continue
        el.set(key, value)
    return el


def _enabled_to_bool_str(value: str) -> str:
    """Map internal Yes/No (and tolerated True/False) → HyperHQ True/False."""
    v = (value or "").strip().lower()
    if v in ("no", "false", "0", "off"):
        return "False"
    return "True"


def _read_enabled(game_el, enabled_as_attribute: bool) -> str:
    """Return the entry's enabled state as the internal Yes/No string.

    Accepts both the attribute form (``enabled="False"``) and the child-element
    form (``<enabled>No</enabled>``) regardless of mode, so files written by
    older SpinDoctor builds or third-party tools still load cleanly.
    """
    if enabled_as_attribute:
        attr = (game_el.get("enabled") or "").strip()
        if attr:
            return "No" if attr.lower() in ("false", "no", "0", "off") else "Yes"
    child_text = _text(game_el, "enabled")
    if child_text:
        return "No" if child_text.strip().lower() in ("no", "false", "0", "off") else "Yes"
    attr = (game_el.get("enabled") or "").strip()
    if attr:
        return "No" if attr.lower() in ("false", "no", "0", "off") else "Yes"
    return "Yes"
