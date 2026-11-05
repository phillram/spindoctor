"""Keep LEDBlinky's Controls.ini / Colors.ini to the games in the wheels.

LEDBlinky reads the whole of ``Controls.ini`` and ``Colors.ini`` when it
starts (``LoadMameFilesAtStartup=1``), and only then answers the front end.
With an entry for every MAME ROM on disk (tens of thousands) that takes tens
of seconds, and the front end's LED events are dropped meanwhile. So the live
files hold what the wheels need, and SpinDoctor keeps the rest:

* :func:`wheel_scope` lists the games in every wheel that uses MAME ROM
  names, and their parents (``cloneof``).
* ``ledblinky generate`` (:func:`spindoctor.ledblinky.generate_for_roms`)
  adds an entry only for a game that has none, from the library when it
  holds one, else synthesised from MAME ``-listxml``. Existing entries are
  never changed.
* :func:`prune_entries` removes the entries for games in no wheel, after
  saving them to the library.

The library (:class:`Library`, ``~/.spindoctor/ledblinky_library``) is
SpinDoctor's own store, outside ``ledblinky_dir``, so LEDBlinky never loads
it. It holds every entry pruned from the live files, exactly as it was, and a
copy of the community controls.dat file ``ledblinky profiles`` reads.
Anything else is synthesised from ``-listxml`` when it's needed.

Files are edited in place: sections are inserted or removed and every other
byte stays as it was. They are read with ``surrogateescape`` so bytes that
aren't UTF-8 (old community files are often ANSI) are written back unchanged.
"""
from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .config import CONFIG_DIR, Config
from .ledblinky import (
    COLORS_INI_NAME,
    CONTROLS_INI_NAME,
    _backup,
    _config_backup_dir,
    _split_ini_by_sections,
)

#: SpinDoctor's LEDBlinky library (module attribute so tests can redirect it).
LIBRARY_DIR = CONFIG_DIR / "ledblinky_library"
#: Copy of the community controls.dat file, kept in the library.
LIBRARY_COMMUNITY_NAME = "community-controls.ini"

#: ``doctor`` warns when the live Controls.ini holds at least this many
#: entries for games in no wheel.
PRUNE_WARN_ENTRIES = 5000

#: Default emulators whose wheels use MAME ROM names (as ``ledblinky profiles``).
_MAME_NAMED_EXES = ("mame", "hbmame", "zinc")


# ── raw INI text ──────────────────────────────────────────────────────────────


def read_raw(path: Path) -> str:
    """The file's text with every byte kept; ``""`` when it doesn't exist."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def write_raw(path: Path, text: str) -> None:
    """Write *text* exactly (no newline translation) through a temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(text)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _ends_blank(tail: str) -> bool:
    """True when *tail* ends with an empty line."""
    for nl in ("\r\n", "\n"):
        if tail.endswith(nl):
            return tail[: -len(nl)].endswith("\n")
    return False


def render_section(name: str, lines: Iterable[str], newline: str) -> str:
    """``[name]`` + *lines* + a blank line, with *newline* line endings."""
    return newline.join([f"[{name}]", *lines, "", ""])


class RawIni:
    """An INI file split into sections, each kept exactly as written."""

    def __init__(self, text: str = ""):
        self.bom = "﻿" if text.startswith("﻿") else ""
        body = text[len(self.bom):]
        if "\r\n" in body:
            self.newline = "\r\n"
        elif "\n" in body:
            self.newline = "\n"
        else:
            self.newline = os.linesep
        parts = _split_ini_by_sections(body)
        self.preamble = "".join(parts[0][2])
        #: ``(name, text)`` in file order; *text* is the header line and
        #: every line up to the next header.
        self.sections: list[tuple[str, str]] = [
            (name or "", (header or "") + "".join(lines)) for name, header, lines in parts[1:]
        ]
        self._entries: Optional[dict[str, str]] = None
        self._spelling: Optional[dict[str, str]] = None
        #: Size of the file this was loaded from, in bytes (0 if none).
        self.size = 0

    @classmethod
    def load(cls, path: Optional[Path]) -> "RawIni":
        if path is None:
            return cls()
        raw = cls(read_raw(path))
        try:
            raw.size = path.stat().st_size
        except OSError:
            pass
        return raw

    def entries(self) -> dict[str, str]:
        """Lower-cased name -> section text (a repeated section's copies joined)."""
        if self._entries is None:
            out: dict[str, str] = {}
            for name, text in self.sections:
                low = name.lower()
                out[low] = out.get(low, "") + text
            self._entries = out
        return self._entries

    def spelling(self, low: str) -> str:
        """The name as first written in the file."""
        if self._spelling is None:
            self._spelling = {}
            for name, _text in self.sections:
                self._spelling.setdefault(name.lower(), name)
        return self._spelling.get(low, low)

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.entries()

    def __len__(self) -> int:
        return len(self.entries())

    def render(
        self,
        add: Optional[dict[str, str]] = None,
        remove: Iterable[str] = (),
        replace: Optional[dict[str, str]] = None,
    ) -> str:
        """The file with sections inserted, removed or replaced; nothing else changes.

        *add* maps lower-cased names to section text. Each goes in name order,
        before the first section that sorts after it, so a sorted file stays
        sorted and a pruned entry goes back where it was. Names already in
        the file are ignored (use *replace*). *remove* drops every section of
        a name; *replace* swaps the first one's text and drops any repeats.
        A blank line is added next to an inserted section only where one is
        missing; existing sections are never edited.
        """
        have = self.entries()
        pending = sorted((k, v) for k, v in (add or {}).items() if k not in have)
        drop = {n.lower() for n in remove}
        swap = dict(replace or {})
        pieces: list[tuple[str, bool]] = []   # (text, inserted)
        swapped: set[str] = set()
        i = 0
        for name, text in self.sections:
            low = name.lower()
            while i < len(pending) and pending[i][0] < low:
                pieces.append((pending[i][1], True))
                i += 1
            if low in drop:
                continue
            if low in swap:
                if low not in swapped:
                    swapped.add(low)
                    pieces.append((swap[low], True))
                continue
            pieces.append((text, False))
        pieces.extend((text, True) for _low, text in pending[i:])

        nl = self.newline
        out = [self.preamble]
        tail = self.preamble[-8:]
        prev_inserted = False
        for text, inserted in pieces:
            if not text:
                continue
            if tail and not tail.endswith("\n"):
                out.append(nl)
                tail += nl
            if (inserted or prev_inserted) and tail and not _ends_blank(tail):
                out.append(nl)
                tail += nl
            out.append(text)
            tail = (tail + text)[-8:]
            prev_inserted = inserted
        return self.bom + "".join(out)


# ── the library ───────────────────────────────────────────────────────────────


def find_community_controls(ledblinky_dir: Path) -> Optional[Path]:
    """The community controls.dat file ``ledblinky profiles`` reads, if any.

    It's the oldest ``controls.ini.*.bak`` next to the live file: the file
    LEDBlinky shipped with, backed up the first time SpinDoctor wrote
    Controls.ini. Only a file that looks like controls.dat data counts.
    """
    from .ledblinky_profiles import COMMUNITY_CONTROLS_GLOB

    try:
        found = sorted(Path(ledblinky_dir).glob(COMMUNITY_CONTROLS_GLOB))
    except OSError:
        return None
    for path in found:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(65536)
        except OSError:
            continue
        if "P1NumButtons=" in head:
            return path
    return None


class Library:
    """SpinDoctor's own Controls.ini / Colors.ini store, outside ``ledblinky_dir``."""

    HEADER = (
        "; SpinDoctor's LEDBlinky library: entries kept out of LEDBlinky's live files.",
        "; LEDBlinky never reads this file. 'spindoctor ledblinky generate' copies",
        "; entries back from it, exactly as they were.",
    )

    def __init__(self, folder: Optional[Path] = None):
        self.folder = Path(folder) if folder is not None else LIBRARY_DIR
        self.controls_path = self.folder / CONTROLS_INI_NAME
        self.colors_path = self.folder / COLORS_INI_NAME
        self.community_path = self.folder / LIBRARY_COMMUNITY_NAME
        self._controls: Optional[RawIni] = None
        self._colors: Optional[RawIni] = None

    @property
    def controls(self) -> RawIni:
        if self._controls is None:
            self._controls = RawIni.load(self.controls_path)
        return self._controls

    @property
    def colors(self) -> RawIni:
        if self._colors is None:
            self._colors = RawIni.load(self.colors_path)
        return self._colors

    def __bool__(self) -> bool:
        return bool(len(self.controls) or len(self.colors))

    def save(self, controls: dict[str, str], colors: dict[str, str]) -> None:
        """Store sections (lower-cased name -> text), replacing any of the same name."""
        for path, attr, new in ((self.controls_path, "_controls", controls),
                                (self.colors_path, "_colors", colors)):
            if not new:
                continue
            raw = RawIni.load(path)
            if not raw.sections and not raw.preamble.strip():
                raw = RawIni(os.linesep.join(self.HEADER + ("", "")))
            have = raw.entries()
            text = raw.render(
                add={k: v for k, v in new.items() if k not in have},
                replace={k: v for k, v in new.items() if k in have},
            )
            write_raw(path, text)
            setattr(self, attr, None)

    def keep_community(self, ledblinky_dir: Path) -> Optional[Path]:
        """Copy the community controls.dat file into the library, once."""
        if self.community_path.is_file():
            return None
        src = find_community_controls(ledblinky_dir)
        if src is None:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(self.community_path))
        return self.community_path


# ── which games the live files need ───────────────────────────────────────────


@dataclass
class WheelScope:
    """The games LEDBlinky's live Controls.ini / Colors.ini are for."""
    #: Wheels whose games use MAME ROM names (in the order read).
    systems: list[str] = field(default_factory=list)
    #: Lower-cased name -> name as in the database, for those wheels' games.
    games: dict[str, str] = field(default_factory=dict)
    #: Lower-cased game name -> the wheels listing it.
    wheels_of: dict[str, list[str]] = field(default_factory=dict)
    #: Parents (``cloneof``) of those games that aren't wheel games themselves:
    #: lower-cased parent -> name.
    parents: dict[str, str] = field(default_factory=dict)
    #: Lower-cased parent -> one of its clones in a wheel.
    parent_of: dict[str, str] = field(default_factory=dict)
    #: Every game in every wheel (any system, hidden wheels included), lower-cased.
    any_wheel: set[str] = field(default_factory=set)
    #: Parents of any of those, lower-cased.
    any_parent: set[str] = field(default_factory=set)
    #: Wheel databases read.
    databases: int = 0

    def names(self) -> list[str]:
        """Wheel games and their parents, in name order."""
        merged = dict(self.games)
        for low, name in self.parents.items():
            merged.setdefault(low, name)
        return [merged[k] for k in sorted(merged)]

    def keep(self) -> set[str]:
        """Lower-cased names whose live entries prune must keep."""
        return self.any_wheel | self.any_parent


def uses_mame_rom_names(system: str, rl=None) -> bool:
    """Whether a wheel's games are MAME ROM names, as ``ledblinky profiles`` judges it.

    True for wheels LEDBlinky treats as MAME (``MAME`` in the name) and wheels
    whose default emulator is MAME, HBMAME or Zinc (*rl* is a
    :class:`~spindoctor.ledblinky_profiles.RocketLauncherIndex`). Consoles run
    through MAME's MESS drivers don't count: their games aren't ROM names.
    """
    from .ledblinky_profiles import MESS_DRIVERS, MESS_PER_GAME_DRIVER, is_mame_named

    if system in MESS_DRIVERS or system in MESS_PER_GAME_DRIVER:
        return False
    if is_mame_named(system):
        return True
    if rl is None:
        return False
    launcher = rl.launcher(rl.default_emulator(system), system)
    return bool(launcher and launcher.exe.lower().startswith(_MAME_NAMED_EXES))


def mame_rom_names(config: Config) -> dict[str, str]:
    """RocketLauncher's ``MameRomName`` keys: lower-cased game -> the ROM MAME runs.

    The MAME module renames such a game's file and starts MAME under the
    other name (the 4-player ``...xbox`` hacks, for one), so that's the name
    LEDBlinky can be told. Every module INI is read (``Modules\\*\\*.ini``),
    so a module copy that isn't in use only means an entry is kept.
    """
    out: dict[str, str] = {}
    if not config.rocketlauncher_dir:
        return out
    try:
        folders = [e.path for e in os.scandir(Path(config.rocketlauncher_dir) / "Modules") if e.is_dir()]
    except OSError:
        return out
    for folder in folders:
        try:
            inis = [e.path for e in os.scandir(folder) if e.name.lower().endswith(".ini") and e.is_file()]
        except OSError:
            continue
        for ini in inis:
            try:
                text = Path(ini).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "mameromname" not in text.lower():
                continue
            section = ""
            for line in text.splitlines():
                s = line.strip()
                m = re.match(r"\[(.+)\]$", s)
                if m:
                    section = m.group(1).strip().lower()
                elif section and s.lower().startswith("mameromname="):
                    value = s.split("=", 1)[1].strip()
                    if value:
                        out.setdefault(section, value)
    return out


def wheel_scope(
    config: Config,
    system: Optional[str] = None,
    listxml: Optional[dict] = None,
) -> WheelScope:
    """Read every wheel database once and work out which games need entries.

    A wheel's games are those in ``<System>\\<System>.xml`` and in each genre
    database its ``Genre.xml`` lists, as HyperSpin's genre menu shows them.
    *system* limits the games (not :attr:`WheelScope.any_wheel`) to that one
    wheel, whatever its emulator. Parents come from each database's
    ``cloneof``, from MAME's when *listxml* is given, and from RocketLauncher
    ``MameRomName`` keys; with *listxml*, a parent MAME doesn't know (some
    databases put other data in ``cloneof``) isn't added to the games. For
    prune, a game's name without an ``xbox`` / ``2play`` / ``4play`` suffix
    counts as a parent too, as it does for ``ledblinky profiles``.
    """
    from .ledblinky_profiles import _SUFFIX_RE, RocketLauncherIndex, load_db_file

    scope = WheelScope()
    if not config.hyperspin_dir:
        return scope
    db_root = config.databases_dir
    try:
        folders = sorted((p for p in db_root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return scope
    rl = None
    if config.rocketlauncher_dir and Path(config.rocketlauncher_dir).is_dir():
        rl = RocketLauncherIndex(config)
    listxml = listxml or {}
    want = system.lower() if system else None
    db_parents: dict[str, str] = {}   # lower game -> its cloneof, any wheel
    for folder in folders:
        name = folder.name
        if name.casefold() == "main menu":
            # Main Menu lists wheels, not games.
            continue
        games = load_db_file(folder / f"{name}.xml")
        if games is None:
            continue
        for genre_db in _genre_databases(folder):
            games.extend(load_db_file(genre_db) or [])
        scope.databases += 1
        in_scope = (name.lower() == want) if want else uses_mame_rom_names(name, rl)
        if in_scope:
            scope.systems.append(name)
        for g in games:
            game = g.name.strip()
            if not game:
                continue
            low = game.lower()
            scope.any_wheel.add(low)
            if g.cloneof.strip():
                db_parents.setdefault(low, g.cloneof.strip())
            if in_scope:
                scope.games.setdefault(low, game)
                wheels = scope.wheels_of.setdefault(low, [])
                if name not in wheels:
                    wheels.append(name)

    renamed = mame_rom_names(config)

    def parents_of(low: str) -> list[str]:
        parent = db_parents.get(low, "")
        if not parent:
            info = listxml.get(low)
            parent = getattr(info, "cloneof", "") if info is not None else ""
        return [p for p in (parent, renamed.get(low, "")) if p and p.lower() != low]

    for low in scope.any_wheel:
        for parent in parents_of(low) + [_SUFFIX_RE.sub("", low)]:
            if parent and parent.lower() != low:
                scope.any_parent.add(parent.lower())
    for low, game in scope.games.items():
        for parent in parents_of(low):
            plow = parent.lower()
            if plow in scope.games or (listxml and plow not in listxml):
                continue
            scope.parents.setdefault(plow, parent)
            scope.parent_of.setdefault(plow, game)
    return scope


def _genre_databases(folder: Path) -> list[Path]:
    """The genre databases a wheel's ``Genre.xml`` lists (file names matched in any case)."""
    try:
        files = {e.name.lower(): Path(e.path) for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return []
    genre_xml = files.get("genre.xml")
    if genre_xml is None:
        return []
    from .ledblinky_profiles import load_db_file

    out = []
    for genre in load_db_file(genre_xml) or []:
        path = files.get(f"{genre.name.strip()}.xml".lower())
        if path is not None and path.name.lower() != f"{folder.name}.xml".lower():
            out.append(path)
    return out


def listxml_cache_fresh(config: Config) -> bool:
    """Whether a ``-listxml`` cache newer than the MAME binary exists."""
    if not config.mame_executable:
        return False
    from .ledblinky import _resolved_mame_path, listxml_cache_path

    cache = listxml_cache_path(config.mame_executable)
    mame = Path(_resolved_mame_path(config.mame_executable))
    try:
        return cache.exists() and (not mame.exists() or cache.stat().st_mtime >= mame.stat().st_mtime)
    except OSError:
        return False


def listxml_if_cached(config: Config) -> dict:
    """MAME's ``-listxml`` data from the cache, or ``{}``; never runs MAME."""
    if not listxml_cache_fresh(config):
        return {}
    from .ledblinky import load_listxml_for_system

    return load_listxml_for_system(config, "MAME")


@dataclass
class UnusedEntries:
    """Live entries for games in no wheel (what :func:`prune_entries` would remove)."""
    controls: int = 0
    controls_total: int = 0
    colors: int = 0
    colors_total: int = 0


def unused_entries(config: Config, scope: WheelScope) -> UnusedEntries:
    """Count the live entries :func:`prune_entries` would remove; reads nothing else."""
    out = UnusedEntries()
    if not config.ledblinky_dir or not scope.any_wheel:
        return out
    keep = scope.keep()
    lb_dir = Path(config.ledblinky_dir)
    controls = RawIni.load(lb_dir / CONTROLS_INI_NAME).entries()
    colors = RawIni.load(lb_dir / COLORS_INI_NAME).entries()
    out.controls_total, out.colors_total = len(controls), len(colors)
    out.controls = sum(1 for low in controls if low not in keep)
    out.colors = sum(1 for low in colors if low not in keep)
    return out


# ── prune ─────────────────────────────────────────────────────────────────────

def _validate_prune_databases(config: Config) -> None:
    """Refuse destructive pruning from a missing or partially readable cabinet."""
    if not config.hyperspin_dir:
        raise ValueError("No wheel databases found: check hyperspin_dir.")

    def read_menu(path):
        try:
            root = ET.parse(path).getroot()
            if root.tag != "menu":
                raise ValueError("expected a HyperSpin <menu> database")
            return root
        except (OSError, ET.ParseError, ValueError) as exc:
            raise ValueError(f"Cannot safely prune: unreadable wheel database {path}: {exc}") from exc

    try:
        folders = {p.name.casefold(): p for p in config.databases_dir.iterdir() if p.is_dir()}
    except OSError as exc:
        raise ValueError(f"No wheel databases found under {config.databases_dir}.") from exc
    for folder in folders.values():
        menu = read_menu(folder / f"{folder.name}.xml")
        if folder.name.casefold() == "main menu":
            for game in menu.iter("game"):
                name = (game.get("name") or "").strip()
                if name and name.casefold() not in folders:
                    raise ValueError(f"Cannot safely prune: missing wheel database for {name}.")
            continue
        files = {p.name.casefold(): p for p in folder.iterdir() if p.is_file()}
        if "genre.xml" in files:
            for genre in read_menu(files["genre.xml"]).iter("game"):
                name = (genre.get("name") or "").strip()
                if name:
                    read_menu(files.get(f"{name}.xml".casefold(), folder / f"{name}.xml"))


@dataclass
class PruneResult:
    dry_run: bool = True
    controls_path: Optional[Path] = None
    colors_path: Optional[Path] = None
    databases: int = 0
    controls_before: int = 0
    colors_before: int = 0
    #: Names (as written) of the entries removed / to remove.
    controls_removed: list[str] = field(default_factory=list)
    colors_removed: list[str] = field(default_factory=list)
    #: Entries kept only because a wheel game is their clone.
    parents_kept: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    library_dir: Optional[Path] = None
    community_saved: Optional[Path] = None
    backups: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def prune_entries(
    config: Config,
    dry_run: bool = True,
    backup: bool = True,
    library: Optional[Library] = None,
    scope: Optional[WheelScope] = None,
) -> PruneResult:
    """Remove live Controls.ini / Colors.ini entries for games in no wheel.

    Games in any wheel (hidden wheels included) and their parents keep their
    entries. Removed entries are saved to the library first, exactly as they
    were, so ``ledblinky generate`` can put them back; if that save fails,
    the live files aren't touched. The live files are backed up (``_backup``,
    honouring ``backup_dir``) unless *backup* is False.
    """
    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. Run: spindoctor config set ledblinky_dir <path>"
        )
    lb_dir = Path(config.ledblinky_dir)
    _validate_prune_databases(config)
    if scope is None:
        from .ledblinky import load_listxml_for_system

        listxml = load_listxml_for_system(config, "MAME")
        if config.mame_executable and not listxml:
            raise ValueError("Cannot safely prune: MAME parent data is unavailable. Check mame_executable.")
        scope = wheel_scope(config, listxml=listxml)
    if not scope.any_wheel:
        raise ValueError(
            f"No wheel databases found under {config.databases_dir}: every entry would be "
            "removed. Check hyperspin_dir."
        )
    lib = library if library is not None else Library()
    result = PruneResult(dry_run=dry_run, databases=scope.databases, library_dir=lib.folder)
    result.controls_path = lb_dir / CONTROLS_INI_NAME
    result.colors_path = lb_dir / COLORS_INI_NAME
    keep = scope.keep()

    plans = []
    for path, removed in ((result.controls_path, result.controls_removed),
                          (result.colors_path, result.colors_removed)):
        raw = RawIni.load(path)
        drop = [low for low in raw.entries() if low not in keep]
        removed.extend(raw.spelling(low) for low in drop)
        plans.append((path, raw, drop))
    controls_raw, colors_raw = plans[0][1], plans[1][1]
    result.controls_before = len(controls_raw)
    result.colors_before = len(colors_raw)
    result.parents_kept = sum(1 for low in controls_raw.entries()
                              if low in scope.any_parent and low not in scope.any_wheel)
    if controls_raw.sections and len(result.controls_removed) == len(controls_raw):
        if not dry_run:
            raise ValueError(
                "Refusing to remove every Controls.ini entry: none matches a wheel game. Check hyperspin_dir."
            )
        result.warnings.append(
            "None of the Controls.ini entries is for a game in a wheel: is hyperspin_dir "
            "the cabinet LEDBlinky belongs to?"
        )

    new_texts = []
    for path, raw, drop in plans:
        text = raw.render(remove=drop) if drop else None
        result.bytes_before += raw.size
        result.bytes_after += (len(text.encode("utf-8", errors="surrogateescape"))
                               if text is not None else raw.size)
        new_texts.append((path, text))

    if dry_run or not (result.controls_removed or result.colors_removed):
        return result

    # Library first: if it can't be written, the live files stay as they are.
    entries_c, entries_k = controls_raw.entries(), colors_raw.entries()
    lib.save(controls={low: entries_c[low] for low in plans[0][2]},
             colors={low: entries_k[low] for low in plans[1][2]})
    try:
        result.community_saved = lib.keep_community(lb_dir)
    except OSError as exc:
        result.warnings.append(f"Could not copy the community controls file to the library: {exc}")
    for path, text in new_texts:
        if text is None:
            continue
        if backup:
            b = _backup(path, _config_backup_dir(config))
            if b:
                result.backups.append(b)
        write_raw(path, text)
    return result
