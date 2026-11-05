"""Can a game take a coin and start from a key?

An arcade panel's keyboard encoder (I-PAC, Mini-PAC and the like) sends keys.
MAME and Supermodel keep one binding per input, and a game's own settings
replace the folder-wide ones.  So when a game was set up for a steering wheel,
pad or gun, its own settings can bind Coin 1 or 1 Player Start to that
device's buttons only.  The game boots, but nothing on the panel inserts a
coin or starts it.  When the device is unplugged later, MAME makes it worse:
it saves a game's cfg as the game exits, writing ``JOYCODE_1_UNKNOWN_SWITCH``
for each binding it can't place, and the original is gone.

A cabinet whose panel is a joystick encoder binds these inputs to joystick
buttons on purpose, so "no key" alone isn't a fault.  A game is reported only
when its own binding has no key while the folder-wide one has (the game took
the key away), or when its binding names only a device that is gone.

:class:`MameInputs` and :class:`SupermodelInputs` read one emulator folder
each; ``doctor``'s Coin/Start check (:func:`spindoctor.health.check_coin_start`)
runs them over the games on the Main Menu's wheels.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Optional

from .rocketlauncher import _read_windows_text

# MAME port types, in the order findings name them.
PORTS = ("COIN1", "START1")
LABELS = {"COIN1": "Coin", "START1": "Start"}


@dataclass(frozen=True)
class Binding:
    """One input's binding and where it's set."""
    seq: str          # as written ("" = the emulator's built-in default)
    source: str       # file (and section) it comes from; "" = built in
    has_key: bool     # some alternative is pressed with keys alone
    lost: bool        # no key, and it names a device the emulator no longer finds

    def why(self) -> str:
        """Why it can't be pressed from a key, in a few words."""
        if self.lost:
            return "a device MAME no longer finds"
        devices = []
        for token in re.split(r"[\s,+]+", self.seq.upper()):
            token = token.lstrip("!")
            for prefix, name in (("JOY", "joystick"), ("MOUSE", "mouse"), ("GUN", "light gun")):
                if token.startswith(prefix) and name not in devices:
                    devices.append(name)
        return f"{' or '.join(devices)} only" if devices else "nothing"


BUILT_IN = Binding(seq="", source="", has_key=True, lost=False)


# ── MAME ──────────────────────────────────────────────────────────────────────

def _mame_alternative_is_key(tokens: list[str]) -> bool:
    """``KEYCODE_LSHIFT KEYCODE_1`` or ``KEYCODE_5 NOT KEYCODE_LALT``: keys only."""
    positive, skip = [], False
    for token in tokens:
        if skip:
            skip = False
        elif token == "NOT":
            skip = True
        else:
            positive.append(token)
    return bool(positive) and all(t.startswith("KEYCODE_") for t in positive)


def mame_binding(seq: str, source: str) -> Binding:
    """A MAME input sequence (``KEYCODE_5 OR JOYCODE_1_BUTTON9``)."""
    seq = " ".join(seq.split())
    has_key = any(_mame_alternative_is_key(alt.split()) for alt in seq.split(" OR "))
    lost = not has_key and "_UNKNOWN_" in seq.upper()
    return Binding(seq=seq, source=source, has_key=has_key, lost=lost)


def _mame_ini_values(folder: Path, exe: str) -> dict[str, str]:
    """``cfg_directory``, ``ctrlrpath`` and ``ctrlr`` from the folder's MAME ini
    (``mame64.exe`` reads ``mame.ini``), in the folder or its ``ini\\``."""
    names = [Path(exe).stem.replace("64", "") + ".ini", "mame.ini", "hbmame.ini", "mess.ini"]
    for name in dict.fromkeys(n.lower() for n in names):
        for cand in (folder / name, folder / "ini" / name):
            if not cand.is_file():
                continue
            try:
                text = _read_windows_text(cand).replace("\r\n", "\n")
            except OSError:
                return {}
            out = {}
            for key in ("cfg_directory", "ctrlrpath", "ctrlr"):
                # [ \t], not \s: a blank "ctrlr" line must not run on into the next one.
                m = re.search(rf"^{key}[ \t]+(\S[^\r\n]*?)[ \t]*$", text, re.M | re.I)
                if m:
                    out[key] = m.group(1).strip('"')
            return out
    return {}


def _folder_setting(folder: Path, value: str) -> Optional[Path]:
    """A MAME folder setting, relative to the emulator's folder (where
    RocketLauncher starts it).  A Windows drive path is only usable on Windows."""
    pw = PureWindowsPath(value)
    if pw.drive:
        return Path(value) if os.name == "nt" else None
    if Path(value).is_absolute():
        return Path(value)
    return folder.joinpath(*pw.parts)


def _mame_cfg_systems(path: Path) -> dict[str, dict[str, str]]:
    """``{system name (lower case): {port type: sequence}}`` for the Coin 1 and
    1 Player Start ports a MAME cfg or ctrlr file sets."""
    try:
        text = _read_windows_text(path)
    except OSError:
        return {}
    if not any(p in text for p in PORTS):
        return {}
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return {}
    out: dict[str, dict[str, str]] = {}
    for system in root.iter("system"):
        ports = out.setdefault((system.get("name") or "").lower(), {})
        for port in system.iter("port"):
            kind = port.get("type") or ""
            seq = port.find("newseq[@type='standard']")
            if kind in PORTS and kind not in ports and seq is not None:
                ports[kind] = " ".join((seq.text or "").split())
    return out


class MameInputs:
    """Coin 1 / 1 Player Start bindings of one MAME folder.

    MAME applies, lowest first: its built-in keys (5 and 1), the ctrlr file's
    ``default`` section, ``cfg\\default.cfg``, the ctrlr file's section for the
    game, and the game's own ``cfg\\<game>.cfg``.  The first two layers are the
    folder-wide binding (:meth:`folder_binding`), the last two the game's
    (:meth:`game_binding`).  The cfg folder is listed once.
    """

    kind = "MAME"

    def __init__(self, folder: Path, exe: str):
        self.folder = folder
        ini = _mame_ini_values(folder, exe)
        cfg_dir = _folder_setting(folder, ini.get("cfg_directory") or "cfg")
        self.cfg_label = ini.get("cfg_directory") or "cfg"
        self._cfgs: dict[str, Path] = {}
        if cfg_dir is not None:
            try:
                with os.scandir(cfg_dir) as it:
                    self._cfgs = {e.name.lower(): Path(e.path) for e in it
                                  if e.name.lower().endswith(".cfg") and e.is_file()}
            except OSError:
                pass
        self._ctrlr: dict[str, dict[str, str]] = {}
        self._ctrlr_label = ""
        ctrlr = ini.get("ctrlr", "")
        if ctrlr and ctrlr.lower() != "none":
            for base in (ini.get("ctrlrpath") or "ctrlr").split(";"):
                d = _folder_setting(folder, base.strip()) if base.strip() else None
                if d is not None and (d / f"{ctrlr}.cfg").is_file():
                    self._ctrlr = _mame_cfg_systems(d / f"{ctrlr}.cfg")
                    self._ctrlr_label = f"{base.strip()}\\{ctrlr}.cfg"
                    break
        default_cfg = self._cfgs.get("default.cfg")
        self._defaults = _mame_cfg_systems(default_cfg).get("default", {}) if default_cfg else {}
        self._games: dict[str, dict[str, str]] = {}

    def folder_binding(self, port: str) -> Binding:
        if port in self._defaults:
            return mame_binding(self._defaults[port], f"{self.cfg_label}\\default.cfg")
        if port in self._ctrlr.get("default", {}):
            return mame_binding(self._ctrlr["default"][port], self._ctrlr_label)
        return BUILT_IN

    def game_binding(self, game: str, port: str) -> Optional[Binding]:
        """The game's own binding, or None when the folder-wide one applies."""
        low = game.lower()
        path = self._cfgs.get(f"{low}.cfg")
        if path is not None:
            if low not in self._games:
                self._games[low] = _mame_cfg_systems(path).get(low, {})
            if port in self._games[low]:
                return mame_binding(self._games[low][port], f"{self.cfg_label}\\{path.name}")
        if port in self._ctrlr.get(low, {}):
            return mame_binding(self._ctrlr[low][port], self._ctrlr_label)
        return None

    def fix(self) -> str:
        return (f"with MAME closed, add a key to Coin 1 / 1 Player Start in {self.cfg_label}\\<game>.cfg "
                "(KEYCODE_5 OR JOYCODE_1_BUTTON9), or delete those <port> entries so "
                f"{self.cfg_label}\\default.cfg applies; MAME rewrites the cfg as the game exits")


# ── Supermodel ────────────────────────────────────────────────────────────────

_SUPERMODEL_KEYS = {"COIN1": "inputcoin1", "START1": "inputstart1"}


def supermodel_binding(value: str, source: str) -> Binding:
    """A Supermodel input value (``"KEY_S,JOY1_BUTTON7"``; ``+`` combines, ``!`` negates)."""
    value = value.strip().strip('"').strip()
    has_key = False
    for alt in value.split(","):
        positive = [p.strip() for p in alt.split("+") if p.strip() and not p.strip().startswith("!")]
        if positive and all(p.upper().startswith("KEY_") for p in positive):
            has_key = True
            break
    return Binding(seq=value, source=source, has_key=has_key, lost=False)


def _supermodel_sections(path: Path) -> dict[str, dict[str, str]]:
    """``{section (lower case, no spaces around it): {key (lower case): value}}``;
    Supermodel writes ``[ Global ]`` and ``[ srally2 ]``."""
    try:
        text = _read_windows_text(path)
    except OSError:
        return {}
    out: dict[str, dict[str, str]] = {}
    cur: Optional[dict[str, str]] = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        m = re.match(r"\[\s*(.*?)\s*\]$", s)
        if m:
            cur = out.setdefault(m.group(1).lower(), {})
        elif cur is not None and "=" in s:
            key, value = s.split("=", 1)
            cur.setdefault(key.strip().lower(), value.strip())
    return out


class SupermodelInputs:
    """Coin 1 / Start 1 bindings of one Supermodel folder (``Config\\Supermodel.ini``).

    A game's ``[ <game> ]`` section overrides ``[ Global ]``, which overrides
    Supermodel's built-in keys.
    """

    kind = "Supermodel"

    def __init__(self, folder: Path):
        self.folder = folder
        self._sections: dict[str, dict[str, str]] = {}
        config_dir = folder / "Config"
        try:
            with os.scandir(config_dir) as it:
                ini = next((Path(e.path) for e in it if e.name.lower() == "supermodel.ini"), None)
        except OSError:
            ini = None
        if ini is not None:
            self._sections = _supermodel_sections(ini)

    def folder_binding(self, port: str) -> Binding:
        value = self._sections.get("global", {}).get(_SUPERMODEL_KEYS[port])
        if value is None:
            return BUILT_IN
        return supermodel_binding(value, "Config\\Supermodel.ini [ Global ]")

    def game_binding(self, game: str, port: str) -> Optional[Binding]:
        value = self._sections.get(game.lower(), {}).get(_SUPERMODEL_KEYS[port])
        if value is None:
            return None
        return supermodel_binding(value, f"Config\\Supermodel.ini [ {game} ]")

    def fix(self) -> str:
        return ("add a KEY_ to InputCoin1 / InputStart1 in the game's [ <game> ] section of "
                "Config\\Supermodel.ini, or delete the line so [ Global ] applies")


def inputs_for(folder: Path, exe: str):
    """The reader for an emulator folder, or None for emulators not covered."""
    low = exe.lower()
    if low.startswith(("mame", "hbmame")):
        return MameInputs(folder, exe)
    if low.startswith("supermodel"):
        return SupermodelInputs(folder)
    return None


@dataclass
class GameFinding:
    """A game whose own Coin 1 / Start binding can't be pressed from a key."""
    game: str
    bindings: dict[str, Binding]   # port -> its binding

    def text(self) -> str:
        whys = {b.why() for b in self.bindings.values()}
        names = " and ".join(LABELS[p] for p in PORTS if p in self.bindings)
        return f"{self.game} ({names}: {' / '.join(sorted(whys))})"


def check_game(reader, game: str) -> Optional[GameFinding]:
    """The game's finding, if its own binding takes the key away or names only
    a device that's gone (see the module docstring)."""
    found: dict[str, Binding] = {}
    for port in PORTS:
        own = reader.game_binding(game, port)
        if own is None or own.has_key:
            continue
        if own.lost or reader.folder_binding(port).has_key:
            found[port] = own
    return GameFinding(game, found) if found else None
