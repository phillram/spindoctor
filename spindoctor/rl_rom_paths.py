"""Where RocketLauncher looks for a system's ROM files.

RocketLauncher finds a game through the system's ``Rom_Path`` (``|``-separated
folders; relative ones resolve from the RocketLauncher folder) and its
``Rom_Extension`` list, as ``<folder>\\<name>.<ext>`` or
``<folder>\\<name>\\<name>.<ext>``, with the game's name exactly as the
database XML writes it.  Shared by the ``doctor`` ROM paths check
(:mod:`spindoctor.health`) and ``audit`` (:mod:`spindoctor.audit`), so both
look for a wheel's games exactly where RocketLauncher does.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .database import find_database, load_database
from .rocketlauncher import _read_rl_ini


# RocketLauncher's default 7z_Extensions (RocketLauncher.ini [7z]).  With
# 7z_Enabled=true RL puts these in front of every emulator's Rom_Extension,
# PCLauncher's too -- which is why its "Cannot find Rom" error can quote
# "zip|rar|7z|lha|lzh|gzip|tar|" for an emulator that sets no extension.
_RL_7Z_DEFAULT_EXTENSIONS = "zip|rar|7z|lha|lzh|gzip|tar"

# Skipchecks values (Settings/<System>/RocketLauncher.ini) under which
# RocketLauncher never looks for the ROM file, so a missing one isn't an error.
_RL_SKIP_ROM_CHECKS = ("rom only", "rom and emu")


def _split_rom_extensions(value: str) -> list[str]:
    """``"zip|7z | .chd"`` → ``["zip", "7z", "chd"]`` (lower-cased, de-duplicated)."""
    exts: list[str] = []
    for part in value.split("|"):
        ext = part.strip().lstrip(".").lower()
        if ext and ext not in exts:
            exts.append(ext)
    return exts


def _resolve_rom_path(element: str, rl_dir: Path) -> Optional[Path]:
    """Resolve one ``Rom_Path`` element to a local folder.

    Relative elements are resolved against the RocketLauncher root, as RL does.
    Returns None when the element can't be checked on this OS (an absolute
    Windows drive path while running on POSIX), mirroring ``health._resolve_emu_path``.
    """
    from pathlib import PureWindowsPath

    if Path(element).is_absolute():
        return Path(element)
    pw = PureWindowsPath(element)
    if pw.drive:
        return Path(element) if os.name == "nt" else None
    if not pw.parts:
        return None
    return Path(os.path.normpath(rl_dir / Path(*pw.parts)))


@dataclass
class _RomSource:
    """Where RocketLauncher looks for one group of games: the Rom_Path folders
    from one system's settings, and the extensions RL tries with one emulator.

    An empty *exts* means RL doesn't look for these games' files: *stops* then
    says why RL gives up before looking (no ``Rom_Extension``, no emulator
    section), or is blank for PCLauncher, which needs no extension."""
    system: str
    ini: Path
    folders: list[tuple[str, Optional[Path]]]  # (Rom_Path element, resolved folder)
    exts: list[str]
    emulator: str = ""
    ext_where: str = ""  # where the extensions come from, e.g. "[MAME] in <file>"
    stops: str = ""
    stop_fix: str = ""

    def missing_folders(self) -> list[str]:
        """Rom_Path elements whose folder doesn't exist, for display."""
        out = []
        for element, folder in self.folders:
            if folder is not None and not folder.is_dir():
                out.append(element if element == str(folder) else f"{element} ({folder})")
        return out

    def checkable(self) -> bool:
        """False when a Rom_Path element can't be checked on this OS."""
        return all(folder is not None for _el, folder in self.folders)


class _RomLookup:
    """Settings and folder listings shared by every wheel in one run.

    Wheels share settings (``Games.ini`` ``System=`` overrides) and ROM folders
    (several MAME wheels point at one 36,000-file folder), so each settings
    file is parsed once and each folder is listed once with ``os.scandir``;
    games are then looked up case-insensitively in memory.
    """

    def __init__(self, rl_dir: Path):
        self.rl_dir = rl_dir
        self.settings_dir = rl_dir / "Settings"
        self.global_emus_ini = self.settings_dir / "Global Emulators.ini"
        self.global_emus = _read_rl_ini(self.global_emus_ini)
        self._systems: dict[str, Optional[tuple[Path, str, dict[str, dict[str, str]]]]] = {}
        self._sources: dict[tuple[str, str], Optional[_RomSource]] = {}
        self._listings: dict[str, Optional[tuple[dict[str, str], dict[str, str]]]] = {}
        self._launch: dict[str, tuple[str, bool]] = {}
        self._rl_inis: dict[str, dict[str, dict[str, str]]] = {}
        self._mame_names: Optional[dict[str, str]] = None

    def system(self, system: str) -> Optional[tuple[Path, str, dict[str, dict[str, str]]]]:
        """``(settings file, Rom_Path section, parsed file)`` for *system*: folder
        layout ``Settings/<System>/Emulators.ini`` ``[ROMS]`` first, then flat
        ``Settings/<System>.ini`` ``[Settings]``; None when neither exists."""
        key = system.lower()
        if key not in self._systems:
            found = None
            for ini, section in (
                (self.settings_dir / system / "Emulators.ini", "roms"),
                (self.settings_dir / f"{system}.ini", "settings"),
            ):
                data = _read_rl_ini(ini)
                if section in data:
                    found = (ini, section, data)
                    break
            self._systems[key] = found
        return self._systems[key]

    def source(self, system: str, emulator: str = "") -> Optional[_RomSource]:
        """Rom_Path folders and the extensions RL tries for *system*'s games
        launched with *emulator* (blank → the system's Default_Emulator)."""
        key = (system.lower(), emulator.lower())
        if key in self._sources:
            return self._sources[key]
        found = self.system(system)
        src = None
        if found is not None:
            ini, section, data = found
            sec = data[section]
            emu = (emulator or sec.get("default_emulator", "")).strip()
            low = emu.lower()
            folders = [
                (el.strip(), _resolve_rom_path(el.strip(), self.rl_dir))
                for el in sec.get("rom_path", "").split("|") if el.strip()
            ]
            # RocketLauncher 1.x reads every emulator key from the first file
            # with an [<emulator>] section -- this system's Emulators.ini, else
            # Global Emulators.ini -- and never Rom_Extension from [ROMS].  The
            # flat (HyperLaunch-era) layout keeps it in [Settings] instead.
            emu_sec: Optional[dict[str, str]] = None
            where = ""
            if low and low in data:
                emu_sec, where = data[low], f"[{emu}] in {ini}"
            elif low and low in self.global_emus:
                emu_sec, where = self.global_emus[low], f"[{emu}] in {self.global_emus_ini}"
            raw = emu_sec.get("rom_extension", "") if emu_sec is not None else ""
            if section == "settings" and sec.get("rom_extension"):
                raw, where = sec["rom_extension"], f"[Settings] in {ini}"
            exts = _split_rom_extensions(raw)
            src = _RomSource(system, ini, folders, exts, emu, where)
            if not sec.get("default_emulator", "").strip():
                # RL demands a Default_Emulator before it reads a game's
                # Games.ini Emulator=, so a blank one stops every game.
                src.stops = "no Default_Emulator is set"
                src.stop_fix = f"Set Default_Emulator in {ini}"
            elif emu_sec is None and not raw:
                src.stops = (f"there is no [{emu}] section in {ini} or {self.global_emus_ini} "
                             f'("Could not locate a section called [{emu}]")')
                src.stop_fix = (f"Add an [{emu}] section, with Emu_Path and Rom_Extension, "
                                f"to {self.global_emus_ini}")
            elif not exts and low != "pclauncher":
                # PCLauncher needs no extension: with none, RL just doesn't look.
                src.stops = f'{where} has no Rom_Extension ("Could not find a Rom_Extension for {emu}")'
                src.stop_fix = f"Add Rom_Extension=<extensions> to {where}"
                if section == "roms" and sec.get("rom_extension"):
                    src.stop_fix += f" (RocketLauncher doesn't read the Rom_Extension under [ROMS] in {ini})"
            if not src.stops and self.rl_setting(system, "7z", "7z_enabled", "false").lower() == "true":
                # RL adds each 7z_Extensions entry its list doesn't already
                # contain (a substring test on the "|"-joined list), in front.
                joined = "|".join(exts)
                seven = _split_rom_extensions(
                    self.rl_setting(system, "7z", "7z_extensions", _RL_7Z_DEFAULT_EXTENSIONS))
                added = [e for e in seven if e not in joined]
                # RL adds them as "<ext>|", so a list that was empty ends in an
                # empty entry: RL then also tries "<name>.", and Windows drops
                # the dot, matching a file or folder named exactly like the game.
                src.exts = added + (exts if exts or not added else [""])
        self._sources[key] = src
        return src

    def rl_setting(self, system: str, section: str, key: str, default: str) -> str:
        """A RocketLauncher.ini setting as RL's ``RIniLoadVar`` reads it: the
        system's own ``Settings/<System>/RocketLauncher.ini`` value unless it is
        missing or ``use_global``, then ``Global RocketLauncher.ini``, then
        *default*.  *section* and *key* are lower-case."""
        value = self._rl_ini(self.settings_dir / system / "RocketLauncher.ini").get(section, {}).get(key)
        if value is None or value.lower() == "use_global":
            value = self._rl_ini(self.settings_dir / "Global RocketLauncher.ini").get(section, {}).get(key)
        return default if value is None else value

    def _rl_ini(self, path: Path) -> dict[str, dict[str, str]]:
        """``_read_rl_ini``, parsed once per run."""
        key = os.path.normcase(str(path))
        if key not in self._rl_inis:
            self._rl_inis[key] = _read_rl_ini(path)
        return self._rl_inis[key]

    def listing(self, folder: Path) -> Optional[tuple[dict[str, str], dict[str, str]]]:
        """``({lower-cased file name: real name}, {lower-cased subfolder: real
        name})`` of *folder*, listed once per run; None when it can't be listed."""
        key = os.path.normcase(str(folder))
        if key not in self._listings:
            files: dict[str, str] = {}
            subdirs: dict[str, str] = {}
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        try:
                            if entry.is_dir():
                                subdirs[entry.name.lower()] = entry.name
                            else:
                                files[entry.name.lower()] = entry.name
                        except OSError:
                            continue
                self._listings[key] = (files, subdirs)
            except OSError:
                self._listings[key] = None
        return self._listings[key]

    def find_in(
        self, folder: Path, name: str, wanted: list[str], match_exts: Optional[list[str]] = None,
    ) -> Optional[Path]:
        """RL's own lookup in one folder: the file it would launch for *name*,
        ``<folder>\\<name>.<ext>`` or ``<folder>\\<name>\\<name>.<ext>``, or None.
        *name* is lower-cased and *wanted* holds the lower-cased
        ``<name>.<ext>`` file names in ``Rom_Extension`` order (just ``<name>``
        for the empty extension, which a ``<name>`` folder also satisfies).
        With *match_exts* (RL's ``Rom_Match_Extension=true``) any file with one
        of those extensions anywhere under ``<folder>\\<name>\\`` also counts."""
        lst = self.listing(folder)
        if lst is None:
            return None
        hit = next((lst[0][w] for w in wanted if w in lst[0]), None)
        if hit is not None:
            return folder / hit
        sub = lst[1].get(name)
        if sub is None:
            return None
        if name in wanted:
            return folder / sub
        inner = self.listing(folder / sub)
        hit = next((inner[0][w] for w in wanted if w in inner[0]), None) if inner else None
        if hit is not None:
            return folder / sub / hit
        if match_exts:
            suffixes = tuple(f".{ext}" for ext in match_exts)
            for root, _dirs, files in os.walk(folder / sub):
                hit = next((f for f in files if f.lower().endswith(suffixes)), None)
                if hit is not None:
                    return Path(root) / hit
        return None

    def found_in(
        self, folder: Path, name: str, wanted: list[str], match_exts: Optional[list[str]] = None,
    ) -> bool:
        """Whether :meth:`find_in` finds *name* in *folder*."""
        return self.find_in(folder, name, wanted, match_exts) is not None

    def find(self, src: _RomSource, names: list[str]) -> Optional[Path]:
        """The file RL launches for a game under any of *names* through *src*, or
        None, honoring the ``Rom_Match_Extension`` of the system the settings
        belong to."""
        folders = [f for _el, f in src.folders if f is not None]
        match_exts = src.exts if self.launch_settings(src.system)[1] else None
        for name in names:
            low = name.lower()
            wanted = [f"{low}.{ext}" if ext else low for ext in src.exts]
            for f in folders:
                hit = self.find_in(f, low, wanted, match_exts)
                if hit is not None:
                    return hit
        return None

    def found(self, src: _RomSource, names: list[str]) -> bool:
        """Whether RL finds a game under any of *names* through *src* (:meth:`find`)."""
        return self.find(src, names) is not None

    def launch_settings(self, system: str) -> tuple[str, bool]:
        """``(Skipchecks, Rom_Match_Extension)`` from ``Settings/<System>/RocketLauncher.ini``
        ``[Settings]``.  RL reads Skipchecks from the system file only;
        Rom_Match_Extension falls back to ``Global RocketLauncher.ini``."""
        key = system.lower()
        if key not in self._launch:
            sec = self._rl_ini(self.settings_dir / system / "RocketLauncher.ini").get("settings", {})
            match = self.rl_setting(system, "settings", "rom_match_extension", "false")
            self._launch[key] = (sec.get("skipchecks", ""), match.lower() == "true")
        return self._launch[key]

    def skips_rom_check(self, system: str) -> bool:
        """``Skipchecks=Rom Only`` / ``Rom and Emu``: RL never looks for the ROM."""
        return self.launch_settings(system)[0].lower() in _RL_SKIP_ROM_CHECKS

    def game_overrides(self, system: str) -> dict[str, tuple[str, str]]:
        """``Games.ini``: lower-cased game → (Emulator=, System=) overrides."""
        ini = _read_rl_ini(self.settings_dir / system / "Games.ini")
        return {
            game: (keys.get("emulator", ""), keys.get("system", ""))
            for game, keys in ini.items()
        }

    def mame_rom_names(self) -> dict[str, str]:
        """Lower-cased alternate name → ``MameRomName`` from the RL MAME module INI."""
        if self._mame_names is None:
            ini = _read_rl_ini(self.rl_dir / "Modules" / "MAME" / "MAME.ini")
            self._mame_names = {
                sec: keys["mameromname"] for sec, keys in ini.items()
                if keys.get("mameromname")
            }
        return self._mame_names


def _wheel_games(system: str, databases_dir: Path) -> tuple[list[str], dict[str, str]]:
    """The wheel's database names, plus ``{name: raw name}`` for names whose XML
    ``name`` attribute has leading or trailing spaces (:func:`_raw_game_names`)."""
    try:
        games = list(load_database(system, databases_dir).games().keys())
    except Exception:  # noqa: BLE001 — DB integrity is check_databases' job
        return [], {}
    return games, (_raw_game_names(system, databases_dir) if games else {})


def _raw_game_names(system: str, databases_dir: Path) -> dict[str, str]:
    """``{name: raw name}`` for database names whose XML ``name`` attribute has
    leading or trailing spaces.  ``load_database`` strips names, but RL gets the
    attribute exactly as written, so a game named ``"Some Hack V2 "`` launches
    ``Some Hack V2 .nes``."""
    raw: dict[str, str] = {}
    xml_path = find_database(system, databases_dir)
    if xml_path is None:
        return raw
    try:
        with open(xml_path, "rb") as fh:
            root = ET.parse(fh).getroot()
    except Exception:  # noqa: BLE001 — names stay stripped, as loaded
        return raw
    for g in root.findall("game"):
        name = g.get("name") or ""
        if name.strip() and name != name.strip():
            raw[name.strip()] = name
    return raw
