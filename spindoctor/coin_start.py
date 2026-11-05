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
from .rl_rom_paths import _resolve_rom_path

# MAME port types, in the order findings name them.
PORTS = ("COIN1", "START1")
LABELS = {"COIN1": "Coin", "START1": "Start"}


@dataclass(frozen=True)
class Binding:
    """One input's binding and where it's set."""
    seq: str          # as written ("" = the emulator's built-in default)
    source: str       # file (and section) it comes from; "" = built in
    has_key: bool     # some alternative is pressed with keys alone
    lost: bool        # every alternative requires an UNKNOWN device input

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

def _mame_positive_tokens(tokens: list[str]) -> list[str]:
    """Positive requirements; an absent negated input does not block an alternative."""
    positive, skip = [], False
    for token in tokens:
        if skip:
            skip = False
        elif token == "NOT":
            skip = True
        else:
            positive.append(token)
    return positive


def mame_binding(seq: str, source: str) -> Binding:
    """A MAME input sequence (``KEYCODE_5 OR JOYCODE_1_BUTTON9``)."""
    seq = " ".join(seq.split())
    alternatives = [_mame_positive_tokens(alt.split()) for alt in seq.upper().split(" OR ")]
    usable = [alt for alt in alternatives if alt and all(
        t.startswith(("KEYCODE_", "JOYCODE_", "MOUSECODE_", "GUNCODE_")) and "_UNKNOWN_" not in t
        for t in alt)]
    has_key = any(all(t.startswith("KEYCODE_") for t in alt) for alt in usable)
    lost = not usable and any("_UNKNOWN_" in t for alt in alternatives for t in alt)
    return Binding(seq=seq, source=source, has_key=has_key, lost=lost)


def _strip_comment(line: str, marker: str) -> str:
    """MAME (#) and Supermodel (;) comments stop at the first unquoted marker."""
    quoted = False
    for i, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == marker and not quoted:
            return line[:i]
    return line


def _mame_path(value: str, folder: Path) -> Optional[Path]:
    # Unlike an empty RL Rom_Path, "." is a valid MAME search directory.
    return folder if value.strip() in ("", ".") else _resolve_rom_path(value.strip(), folder)


def _mame_ini_values(folder: Path, exe: str) -> dict[str, str]:
    """Merge main INIs in search order, including the initial inipath bootstrap.

    This does not evaluate orientation/source/driver INIs or command-line
    overrides. The configuration name of custom builds cannot be inferred;
    the supported stock families use mame.ini and hbmame.ini respectively.
    """
    name = "hbmame.ini" if exe.lower().startswith("hbmame") else "mame.ini"

    def read(path):
        try:
            lines = _read_windows_text(path).splitlines()
        except OSError:
            return {}
        out = {}
        for line in lines:
            match = re.match(r"^\s*(\w+)[ \t]+(.*?)\s*$", _strip_comment(line, "#"))
            if match:
                out[match.group(1).lower()] = match.group(2).strip('"')
        return out

    def candidates(search):
        for base in search.split(";"):
            directory = _mame_path(base, folder)
            if directory is not None:
                yield directory / name

    search = ".;ini;ini/presets"
    for path in candidates(search):
        if path.is_file():
            search = read(path).get("inipath", search)
            break
    out = {}
    for path in candidates(search):
        out.update(read(path))
    return out


def _mame_cfg_root(path: Path) -> Optional[ET.Element]:
    try:
        text = _read_windows_text(path)
    except OSError:
        return None
    try:
        return ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return None


def _mame_cfg_systems(path: Path) -> dict[str, dict[str, str]]:
    """Coin/Start sequences in a default or game cfg; later entries win."""
    root = _mame_cfg_root(path)
    if root is None:
        return {}
    out: dict[str, dict[str, str]] = {}
    for system in root.iter("system"):
        ports = out.setdefault((system.get("name") or "").lower(), {})
        for port in system.iter("port"):
            kind = port.get("type") or ""
            seq = port.find("newseq[@type='standard']")
            if kind in PORTS and seq is not None and seq.text and seq.text.strip():
                ports[kind] = " ".join((seq.text or "").split())
    return out


def _cached_mame_drivers(folder: Path, exe: str) -> dict[str, tuple[str, str]]:
    """Source basename and clone parent from this executable's fresh XML cache.

    Never execute MAME, and never borrow metadata from a different MAME build.
    BIOS ancestry and field/tag validity are not established by this metadata.
    """
    from .ledblinky import listxml_cache_path

    binary = folder / exe
    cache = listxml_cache_path(str(binary))
    out = {}
    try:
        if not binary.is_file() or cache.stat().st_mtime < binary.stat().st_mtime:
            return {}
        with cache.open("rb") as fh:
            for _, node in ET.iterparse(fh, events=("end",)):
                if node.tag in ("machine", "game"):
                    name = node.get("name", "").lower()
                    source = PureWindowsPath(node.get("sourcefile", "")).name.lower()
                    out[name] = (source, node.get("cloneof", "").lower())
                    node.clear()
    except (OSError, ET.ParseError, ValueError):
        return {}
    return out


class MameInputs:
    """Coin 1 / 1 Player Start bindings of one MAME folder.

    The controller is applied in XML order before default.cfg. Its tagged
    game ports override individual fields, while untagged ports alter general
    defaults (which default.cfg can replace). Game cfgs win over both.
    Source/clone matching uses only fresh cached metadata for this executable;
    without it only default and exact-game sections are known. We cannot
    validate controller tags/masks against the driver's live input fields.
    """

    def __init__(self, folder: Path, exe: str):
        self.folder = folder
        ini = _mame_ini_values(folder, exe)
        cfg_dir = _mame_path(ini.get("cfg_directory") or "cfg", folder)
        self.cfg_label = ini.get("cfg_directory") or "cfg"
        self._cfgs: dict[str, Path] = {}
        if cfg_dir is not None:
            try:
                with os.scandir(cfg_dir) as it:
                    self._cfgs = {e.name.lower(): Path(e.path) for e in it
                                  if e.name.lower().endswith(".cfg") and e.is_file()}
            except OSError:
                pass
        self._ctrlr: list[ET.Element] = []
        self._ctrlr_label = ""
        self.limits: list[str] = []
        self._drivers: dict[str, tuple[str, str]] = {}
        ctrlr = ini.get("ctrlr", "")
        if ctrlr and ctrlr.lower() != "none":
            for base in (ini.get("ctrlrpath") or "ctrlr").split(";"):
                d = _mame_path(base, folder)
                if d is not None and (d / f"{ctrlr}.cfg").is_file():
                    root = _mame_cfg_root(d / f"{ctrlr}.cfg")
                    self._ctrlr = list(root.iter("system")) if root is not None else []
                    self._ctrlr_label = f"{base.strip()}\\{ctrlr}.cfg"
                    break
            if self._ctrlr:
                self._drivers = _cached_mame_drivers(folder, exe)
                if not self._drivers:
                    self.limits.append("no fresh -listxml cache for this executable; controller "
                                       "source/parent sections cannot be matched")
                self.limits.append("controller tag/mask/defvalue matches and BIOS ancestry "
                                   "are not validated against live driver fields")
        default_cfg = self._cfgs.get("default.cfg")
        self._defaults = _mame_cfg_systems(default_cfg).get("default", {}) if default_cfg else {}
        self._games: dict[str, dict[str, str]] = {}
        self._controller_cache: dict[str, dict[str, Binding]] = {}
        self._wide = self._controller_bindings("")

    def folder_binding(self, port: str) -> Binding:
        return self._wide.get(port, BUILT_IN)

    def _controller_bindings(self, game: str) -> dict[str, Binding]:
        """Resolve general defaults and tagged overrides without reordering XML."""
        names = {"default"}
        if game:
            names.add(game)
            source, parent = self._drivers.get(game, ("", ""))
            if source:
                names.add(source)
            for _ in range(2):
                if not parent:
                    break
                names.add(parent)
                parent = self._drivers.get(parent, ("", ""))[1]
        defaults: dict[str, Binding] = {}
        tagged: dict[str, Binding] = {}
        for system in self._ctrlr:
            name = system.get("name", "").lower()
            if name not in names:
                continue
            for remap in system.iter("remap"):
                old, new = remap.get("origcode", ""), remap.get("newcode", "")
                if not old or not new:
                    continue
                for port, built_in in (("COIN1", "KEYCODE_5"), ("START1", "KEYCODE_1")):
                    seq = defaults[port].seq if port in defaults else built_in
                    tokens = seq.split()
                    if old in tokens:
                        defaults[port] = mame_binding(
                            " ".join(new if t == old else t for t in tokens), self._ctrlr_label)
            for node in system.iter("port"):
                port = node.get("type", "")
                seq = node.find("newseq[@type='standard']")
                if port not in PORTS or seq is None or not seq.text or not seq.text.strip():
                    continue
                target = defaults
                if name != "default" and node.get("tag") is not None:
                    # MAME ignores tagged controller ports without a nonzero mask.
                    try:
                        mask = int(node.get("mask", "0"), 0)
                    except ValueError:
                        continue
                    if not mask:
                        continue
                    target = tagged
                target[port] = mame_binding(seq.text, self._ctrlr_label)
        for port, seq in self._defaults.items():
            defaults[port] = mame_binding(seq, f"{self.cfg_label}\\default.cfg")
        defaults.update(tagged)
        return defaults

    def game_binding(self, game: str, port: str) -> Optional[Binding]:
        """The game's own binding, or None when the folder-wide one applies."""
        low = game.lower()
        path = self._cfgs.get(f"{low}.cfg")
        if path is not None:
            if low not in self._games:
                self._games[low] = _mame_cfg_systems(path).get(low, {})
            if port in self._games[low]:
                return mame_binding(self._games[low][port], f"{self.cfg_label}\\{path.name}")
        if low not in self._controller_cache:
            self._controller_cache[low] = self._controller_bindings(low)
        binding = self._controller_cache[low].get(port)
        if binding is not None and binding != self.folder_binding(port):
            return binding
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
    current = [out.setdefault("global", {})]
    for line in text.splitlines():
        s = _strip_comment(line, ";").strip()
        if not s or s[0] in ";#":
            continue
        m = re.match(r"\[\s*(.*?)\s*\]$", s)
        if m:
            current = [out.setdefault(name.strip().lower() or "global", {})
                       for name in m.group(1).split(",")]
        elif "=" in s:
            key, value = s.split("=", 1)
            for section in current:
                section[key.strip().lower()] = value.strip()
    return out


class SupermodelInputs:
    """Coin 1 / Start 1 bindings of one Supermodel folder (``Config\\Supermodel.ini``).

    A game's ``[ <game> ]`` section overrides ``[ Global ]``, which overrides
    Supermodel's built-in NONE bindings.
    """

    def __init__(self, folder: Path):
        self.folder = folder
        self.limits: list[str] = []
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
            return supermodel_binding("NONE", "")
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
