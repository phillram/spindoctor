"""Per-game LEDBlinky profiles derived from the cabinet's real emulator keymaps.

LEDBlinky picks a profile for a launched game in this order (confirmed against
``Debug.log`` on the cabinet):

* The emulator name is the HyperSpin wheel name, upper-cased, spaces -> ``_``.
* Emulators with ``MAME`` in the name use ``Controls.ini`` / ``Colors.ini`` and
  take each control's key from MAME's own cfg.
* Everything else: ``<emulator>/<game>`` group -> ``<emulator>/DEFAULT`` ->
  ``OTHER/DEFAULT`` (which lights nothing at all).
* A control lights the LED whose ``LEDBlinkyInputMap.xml`` port lists one of
  the control's ``inputCodes``.  The control's *name* plays no part in routing.

This module reads the keymap each wheel really launches with (RocketLauncher
``Emulators.ini`` / ``Games.ini`` -> emulator folder -> that emulator's key
config) and writes profiles whose ``inputCodes`` are those keys, so only the
buttons a game can use light up.
"""
from __future__ import annotations

import configparser
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Iterable, Optional
from xml.sax.saxutils import quoteattr

from .config import Config
from .ledblinky import (
    COLORS_INI_NAME,
    CONTROLS_XML_NAME,
    _backup,
    _config_backup_dir,
    _split_ini_by_sections,
)

INPUT_MAP_NAME = "LEDBlinkyInputMap.xml"
CONTROLS_INI_FILE = "Controls.ini"
COMMUNITY_CONTROLS_GLOB = "controls.ini.*.bak"

#: Wheels whose games are other wheels' games; profiles are copied per game.
COLLECTION_SYSTEMS = ("Favorites", "Most Played", "Recently Played")

#: Wheels LEDBlinky already treats as MAME (Controls.ini + MAME's cfg).
def is_mame_named(system: str) -> bool:
    return "MAME" in system.upper()


def emu_key(system: str) -> str:
    """LEDBlinky's emulator / game key: upper-case, spaces -> underscores."""
    return system.strip().upper().replace(" ", "_")


def group_name(game: str) -> str:
    return game.strip().replace(" ", "_")


# ── Key-code normalisation ─────────────────────────────────────────────────────

# DirectInput scan codes (Zinc, Demul, SSF).
_DIK = {
    0x1E: "A", 0x30: "B", 0x2E: "C", 0x20: "D", 0x12: "E", 0x21: "F", 0x22: "G",
    0x23: "H", 0x17: "I", 0x24: "J", 0x25: "K", 0x26: "L", 0x32: "M", 0x31: "N",
    0x18: "O", 0x19: "P", 0x10: "Q", 0x13: "R", 0x1F: "S", 0x14: "T", 0x16: "U",
    0x2F: "V", 0x11: "W", 0x2D: "X", 0x15: "Y", 0x2C: "Z", 0x1C: "ENTER",
    0x01: "ESC", 0x39: "SPACE", 0x35: "SLASH",
    0x02: "1", 0x03: "2", 0x04: "3", 0x05: "4", 0x06: "5", 0x07: "6",
    0x08: "7", 0x09: "8", 0x0A: "9", 0x0B: "0",
}

_RETROARCH_NAMES = {
    "enter": "ENTER", "space": "SPACE", "escape": "ESC", "slash": "SLASH",
    "rshift": "RSHIFT", "shift": "LSHIFT", "ctrl": "LCONTROL", "alt": "LALT",
    "kp_enter": "ENTERPAD", "multiply": "ASTERISK", "tab": "TAB",
}


def _kc(name: str) -> str:
    return "KEYCODE_" + name


def key_from_dik(code: int) -> Optional[str]:
    return _kc(_DIK[code]) if code in _DIK else None


def key_from_ascii(code: int) -> Optional[str]:
    """Windows virtual-key / SDL / ASCII letter and digit codes."""
    if 65 <= code <= 90 or 48 <= code <= 57:
        return _kc(chr(code))
    if 97 <= code <= 122:
        return _kc(chr(code).upper())
    if code == 13:
        return _kc("ENTER")
    return None


def key_from_retroarch(name: str) -> Optional[str]:
    n = name.strip().strip('"').lower()
    if not n or n == "nul":
        return None
    if len(n) == 1 and n.isalnum():
        return _kc(n.upper())
    m = re.fullmatch(r"num(\d)", n)
    if m:
        return _kc(m.group(1))
    m = re.fullmatch(r"keypad(\d)", n)
    if m:
        return _kc(m.group(1) + "PAD")
    return _kc(_RETROARCH_NAMES.get(n, n.upper()))


def keys_from_mame_seq(seq: str) -> list[str]:
    """``KEYCODE_A OR JOYCODE_1_BUTTON3`` -> ``["KEYCODE_A"]``; ``NONE`` -> []."""
    out = []
    for alt in seq.split(" OR "):
        toks = alt.split()
        if len(toks) == 1 and toks[0].startswith("KEYCODE_"):
            out.append(toks[0])
    return out


# ── Panel (input map) ─────────────────────────────────────────────────────────

def load_panel(ledblinky_dir: Path) -> dict[str, str]:
    """Map every key code in ``LEDBlinkyInputMap.xml`` to the port label it lights."""
    text = (ledblinky_dir / INPUT_MAP_NAME).read_text(encoding="utf-8", errors="replace")
    panel: dict[str, str] = {}
    for label, codes in re.findall(r'label="([^"]*)"[^>]*inputCodes="([^"]*)"', text):
        for c in filter(None, codes.split("|")):
            panel.setdefault(c, label)
    return panel


# ── Keymaps ───────────────────────────────────────────────────────────────────

@dataclass
class Keymap:
    """Keys an emulator sends for each (player, action)."""

    source: str
    keys: dict[tuple[int, str], list[str]] = field(default_factory=dict)
    #: Actions in display order with the console's own button names.
    labels: dict[str, str] = field(default_factory=dict)
    verified: bool = True

    def get(self, player: int, action: str) -> list[str]:
        return self.keys.get((player, action), [])


#: The cabinet's arcade layout, shared by MAME, HBMAME, Zinc, Demul and Daphne:
#: B1-B3 on the top row, B4-B6 on the bottom row.  Used where an emulator's own
#: key config can't be read (Model 2/3, Triforce, Type X, AAE).
ARCADE_LAYOUT = {
    1: dict(zip([f"BUTTON{i}" for i in range(1, 7)] + ["START", "COIN"], "ABCDEFRS")),
    2: dict(zip([f"BUTTON{i}" for i in range(1, 7)] + ["START", "COIN"], "GHIJKLTU")),
}


def arcade_layout_keymap(source: str = "arcade layout (assumed)") -> Keymap:
    km = Keymap(source=source, verified=False)
    for p, acts in ARCADE_LAYOUT.items():
        for act, letter in acts.items():
            km.keys[(p, act)] = [_kc(letter)]
    return km


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


# RetroArch --------------------------------------------------------------------

_RA_ACTIONS = ("b", "a", "y", "x", "l", "r", "l2", "r2", "l3", "r3", "start", "select")


def _read_ra_cfg(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in _read_text(path).splitlines():
        m = re.match(r'\s*(\w+)\s*=\s*"?(.*?)"?\s*$', line)
        if m:
            d[m.group(1)] = m.group(2)
    return d


def _ci_file(folder: Path, name: str) -> Optional[Path]:
    p = folder / name
    if p.is_file():
        return p
    if folder.is_dir():
        low = name.lower()
        for q in folder.iterdir():
            if q.name.lower() == low and q.is_file():
                return q
    return None


class RetroArchIndex:
    """Per-install cache of retroarch.cfg and per-game override locations."""

    def __init__(self, folder: Path):
        self.folder = folder
        base = folder / "retroarch.cfg"
        self.base = _read_ra_cfg(base) if base.is_file() else {}
        self.game_cfgs: dict[str, Path] = {}
        cfg_dir = folder / "config"
        if cfg_dir.is_dir():
            for core in cfg_dir.iterdir():
                if core.is_dir():
                    for f in core.glob("*.cfg"):
                        self.game_cfgs.setdefault(f.stem.lower(), f)

    def keymap(self, system: str, game: Optional[str] = None) -> Optional[Keymap]:
        sys_cfg = _ci_file(self.folder / "config", f"{system}.cfg")
        if sys_cfg is None:
            return None
        merged = dict(self.base)
        merged.update(_read_ra_cfg(sys_cfg))
        source = f"RetroArch {self.folder.name}\\config\\{sys_cfg.name}"
        if game:
            override = self.game_cfgs.get(game.lower())
            if override is None:
                return None
            game_cfg = _read_ra_cfg(override)
            if not any(k.startswith("input_player") for k in game_cfg):
                return None
            merged.update(game_cfg)
            source = f"RetroArch {self.folder.name}\\config\\{override.parent.name}\\{override.name}"
        km = Keymap(source=source)
        for p in (1, 2):
            for act in _RA_ACTIONS:
                k = key_from_retroarch(merged.get(f"input_player{p}_{act}", "nul"))
                if k:
                    km.keys[(p, act)] = [k]
        return km


# RetroPad action -> console button name, by console family.
_SNES = {"y": "Button Y", "x": "Button X", "l": "L Button", "b": "Button B",
         "a": "Button A", "r": "R Button", "start": "Start", "select": "Select"}
_NES = {"b": "Button B", "a": "Button A", "start": "Start", "select": "Select"}
_GBA = {"b": "Button B", "a": "Button A", "l": "L Button", "r": "R Button",
        "start": "Start", "select": "Select"}
_GENESIS = {"y": "Button A", "b": "Button B", "a": "Button C", "l": "Button X",
            "x": "Button Y", "r": "Button Z", "start": "Start", "select": "Mode"}
_SMS = {"b": "Button 1", "a": "Button 2", "start": "Start"}
_PCE = {"b": "Button II", "a": "Button I", "start": "Run", "select": "Select"}
_PSX = {"y": "Square", "x": "Triangle", "l": "L1", "b": "Cross", "a": "Circle",
        "r": "R1", "l2": "L2", "r2": "R2", "start": "Start", "select": "Select"}
_WSWAN = {"b": "Button B", "a": "Button A", "start": "Start"}
_NGP = {"b": "Button B", "a": "Button A", "start": "Option"}

CONSOLE_LABELS: dict[str, dict[str, str]] = {
    "Nintendo Entertainment System": _NES,
    "Nintendo Entertainment System Hacks": _NES,
    "Nintendo Famicom": _NES,
    "Nintendo Famicom Disk System": _NES,
    "Nintendo Game Boy": _NES,
    "Nintendo Game Boy Color": _NES,
    "Nintendo Game Boy Advance": _GBA,
    "Nintendo Virtual Boy": _GBA,
    "Super Nintendo Entertainment System": _SNES,
    "Super Nintendo Entertainment System Hacks": _SNES,
    "Nintendo Super Famicom": _SNES,
    "Nintendo Super Game Boy": _SNES,
    "Nintendo Satellaview": _SNES,
    "Nintendo Sufami Turbo": _SNES,
    "SNES CD": _SNES,
    "Sega Genesis": _GENESIS,
    "Sega CD": _GENESIS,
    "Sega 32X": _GENESIS,
    "Sega Master System": _SMS,
    "Sega Game Gear": _SMS,
    "Sega SG-1000": _SMS,
    "Sega Mark III": _SMS,
    "NEC PC Engine": _PCE,
    "NEC PC Engine-CD": _PCE,
    "NEC SuperGrafx": _PCE,
    "NEC Turbografx-16": _PCE,
    "NEC Turbografx-CD": _PCE,
    "Sony Playstation": _PSX,
    "Sony PSP": _PSX,
    "Sony Playstation Minis": _PSX,
    "Bandai WonderSwan": _WSWAN,
    "Bandai WonderSwan Color": _WSWAN,
    "SNK Neo Geo Pocket": _NGP,
    "SNK Neo Geo Pocket Color": _NGP,
}


# MAME family --------------------------------------------------------------------

#: MAME's built-in keys, used for ports no cfg remaps.
_MAME_BUILTIN = {
    "P1_BUTTON1": ["KEYCODE_LCONTROL"], "P1_BUTTON2": ["KEYCODE_LALT"],
    "P1_BUTTON3": ["KEYCODE_SPACE"], "P1_BUTTON4": ["KEYCODE_LSHIFT"],
    "P1_BUTTON5": ["KEYCODE_Z"], "P1_BUTTON6": ["KEYCODE_X"],
    "P2_BUTTON1": ["KEYCODE_A"], "P2_BUTTON2": ["KEYCODE_S"],
    "P2_BUTTON3": ["KEYCODE_Q"], "P2_BUTTON4": ["KEYCODE_W"],
    "START1": ["KEYCODE_1"], "START2": ["KEYCODE_2"],
    "COIN1": ["KEYCODE_5"], "COIN2": ["KEYCODE_6"],
}

#: MESS / MAME system driver per wheel, for console wheels run through MAME.
MESS_DRIVERS = {
    "Amstrad GX4000": "gx4000", "Bally Astrocade": "astrocde",
    "Casio PV-1000": "pv1000", "Casio PV-2000": "pv2000",
    "Colecovision": "coleco", "Creatronic Mega Duck": "megaduck",
    "Emerson Arcadia 2001": "arcadia", "Entex Adventure Vision": "advision",
    "Epoch Game Pocket Computer": "gamepock", "Epoch Super Cassette Vision": "scv",
    "Funtech Super Acan": "supracan", "Hartung Game Master": "gmaster",
    "Magnavox Odyssey 2": "odyssey2", "Mattel Intellivision": "intv",
    "SNK Neo Geo CD": "neocdz", "Sord M5": "m5", "Tiger Game.com": "gamecom",
    "Watara Supervision": "svision",
}

#: Wheels whose MAME driver is the game itself (one driver per handheld).
MESS_PER_GAME_DRIVER = {"Konami Handheld", "Tiger Handheld Electronics"}

MESS_LABELS = {**{f"BUTTON{i}": f"Button {i}" for i in range(1, 9)},
               "START": "Start", "COIN": "Select"}


def _mame_cfg_ports(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not path.is_file() or path.stat().st_size == 0:
        return out
    try:
        root = ET.fromstring(_read_text(path))
    except ET.ParseError:
        return out
    for port in root.iter("port"):
        t = port.get("type") or ""
        seq = port.find("newseq[@type='standard']")
        if seq is not None and seq.text is not None and re.match(r"(P\d_BUTTON\d+|START\d|COIN\d)$", t):
            out[t] = keys_from_mame_seq(seq.text.strip())
    return out


class MameIndex:
    """Keymaps from a MAME-family folder: ctrlr file, cfg/default.cfg, cfg/<game>.cfg."""

    def __init__(self, folder: Path, exe: str):
        self.folder = folder
        self.base: dict[str, list[str]] = dict(_MAME_BUILTIN)
        ctrlr = ""
        ini = folder / (Path(exe).stem.replace("64", "") + ".ini")
        for cand in (ini, folder / "mame.ini", folder / "hbmame.ini", folder / "mess.ini"):
            if cand.is_file():
                m = re.search(r"^ctrlr\s+(\S.*?)\s*$", _read_text(cand), re.M)
                ctrlr = m.group(1) if m else ""
                break
        if ctrlr and ctrlr.lower() != "none":
            self.base.update(_mame_cfg_ports(folder / "ctrlr" / f"{ctrlr}.cfg"))
        self.base.update(_mame_cfg_ports(folder / "cfg" / "default.cfg"))
        self._cache: dict[str, Keymap] = {}

    def driver_keymap(self, driver: str) -> Optional[Keymap]:
        """Keys a console driver's own cfg remaps — nothing inherited.

        A console driver has far fewer ports than MAME's defaults cover, and
        which ones it has isn't recorded outside the driver; the ports the
        cabinet remapped for it are the ones it uses.
        """
        ports = _mame_cfg_ports(self.folder / "cfg" / f"{driver}.cfg")
        if not ports:
            return None
        km = Keymap(source=f"{self.folder.name}\\cfg\\{driver}.cfg")
        for port, keys in ports.items():
            m = re.match(r"P(\d)_(BUTTON\d+)$", port) or re.match(r"(START|COIN)(\d)$", port)
            if not m:
                continue
            if port.startswith("P"):
                km.keys[(int(m.group(1)), m.group(2))] = keys
            else:
                km.keys[(int(m.group(2)), m.group(1))] = keys
        return km

    def keymap(self, game: Optional[str] = None) -> Keymap:
        key = (game or "").lower()
        if key in self._cache:
            return self._cache[key]
        ports = dict(self.base)
        if game:
            ports.update(_mame_cfg_ports(self.folder / "cfg" / f"{game}.cfg"))
        km = Keymap(source=f"{self.folder.name}\\cfg")
        for port, keys in ports.items():
            m = re.match(r"P(\d)_(BUTTON\d+)$", port)
            if m:
                km.keys[(int(m.group(1)), m.group(2))] = keys
            m = re.match(r"(START|COIN)(\d)$", port)
            if m:
                km.keys[(int(m.group(2)), m.group(1))] = keys
        self._cache[key] = km
        return km


# Standalone emulators -----------------------------------------------------------

def desmume_keymap(folder: Path) -> Optional[Keymap]:
    ini = folder / "desmume.ini"
    if not ini.is_file():
        return None
    cp = configparser.RawConfigParser(strict=False)
    cp.optionxform = str
    cp.read_string(_read_text(ini))
    if not cp.has_section("Controls"):
        return None
    km = Keymap(source="DeSmuME desmume.ini", labels={
        "Y": "Button Y", "X": "Button X", "L": "L Button", "B": "Button B",
        "A": "Button A", "R": "R Button", "Start": "Start", "Select": "Select"})
    for act in km.labels:
        k = key_from_ascii(cp.getint("Controls", act, fallback=0))
        if k:
            km.keys[(1, act)] = [k]
    return km


_SSF_ORDER = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "C", "X", "Y", "Z", "L", "R", "Start")


def ssf_keymap(folder: Path) -> Optional[Keymap]:
    ini = folder / "SSF.ini"
    if not ini.is_file():
        return None
    text = _read_text(ini)
    km = Keymap(source="SSF SSF.ini", labels={
        "X": "Button X", "Y": "Button Y", "Z": "Button Z", "A": "Button A",
        "B": "Button B", "C": "Button C", "L": "L Button", "R": "R Button", "Start": "Start"})
    for player, pad in ((1, "Pad0_0_0"), (2, "Pad1_0_0")):
        m = re.search(rf'^{pad}="([^"]*)"', text, re.M)
        if not m:
            continue
        nums = m.group(1).split("/")
        for i, act in enumerate(_SSF_ORDER):
            if 2 * i + 1 < len(nums) and nums[2 * i] == "2":
                k = key_from_dik(int(nums[2 * i + 1]))
                if k and act in km.labels:
                    km.keys[(player, act)] = [k]
    return km


def zinc_keymap(folder: Path) -> Optional[Keymap]:
    cfg = folder / "controller.cfg"
    if not cfg.is_file():
        return None
    km = Keymap(source="ZiNc controller.cfg")
    section = None
    for line in _read_text(cfg).splitlines():
        m = re.match(r"\[player(\d)\]", line.strip())
        if m:
            section = int(m.group(1))
            continue
        m = re.match(r"(btn([1-6])|start|coin)\s*=\s*k([0-9A-Fa-f]+)", line.strip())
        if m and section in (1, 2):
            act = f"BUTTON{m.group(2)}" if m.group(2) else m.group(1).upper()
            k = key_from_dik(int(m.group(3), 16))
            if k:
                km.keys[(section, act)] = [k]
    return km


def demul_keymap(folder: Path) -> Optional[Keymap]:
    ini = folder / "padDemul.ini"
    if not ini.is_file():
        return None
    km = Keymap(source=f"{folder.name} padDemul.ini")
    section = None
    for line in _read_text(ini).splitlines():
        m = re.match(r"\[JAMMA0_(\d)\]", line.strip())
        if m:
            section = int(m.group(1)) + 1
            continue
        if line.strip().startswith("["):
            section = None
        m = re.match(r"(PUSH([1-6])|START|COIN)\s*=\s*(\d+)", line.strip())
        if m and section in (1, 2):
            act = f"BUTTON{m.group(2)}" if m.group(2) else m.group(1)
            k = key_from_dik(int(m.group(3)))
            if k:
                km.keys[(section, act)] = [k]
    return km


def daphne_keymap(folder: Path) -> Optional[Keymap]:
    ini = folder / "dapinput.ini"
    if not ini.is_file():
        return None
    km = Keymap(source="Daphne dapinput.ini")
    names = {"KEY_BUTTON1": (1, "BUTTON1"), "KEY_BUTTON2": (1, "BUTTON2"),
             "KEY_BUTTON3": (1, "BUTTON3"), "KEY_START1": (1, "START"),
             "KEY_COIN1": (1, "COIN"), "KEY_START2": (2, "START"), "KEY_COIN2": (2, "COIN")}
    for line in _read_text(ini).splitlines():
        m = re.match(r"(KEY_\w+)\s*=\s*(\d+)", line.strip())
        if m and m.group(1) in names:
            k = key_from_ascii(int(m.group(2)))
            if k:
                km.keys[names[m.group(1)]] = [k]
    return km


def pokemini_keymap(folder: Path) -> Optional[Keymap]:
    cfg = folder / "pokemini.cfg"
    if not cfg.is_file():
        return None
    km = Keymap(source="PokeMini pokemini.cfg", labels={
        "a": "Button A", "b": "Button B", "c": "Button C", "power": "Power"})
    for line in _read_text(cfg).splitlines():
        m = re.match(r"keyb_(a|b|c|power)\s*=\s*(\d+)", line.strip())
        if m:
            k = key_from_ascii(int(m.group(2)))
            if k:
                km.keys[(1, m.group(1))] = [k]
    return km


# ── RocketLauncher ────────────────────────────────────────────────────────────

def _read_ini_loose(path: Path) -> dict[str, dict[str, str]]:
    """Section -> {key: value}; tolerates the HTML-style comments RL files carry."""
    out: dict[str, dict[str, str]] = {}
    cur: Optional[dict[str, str]] = None
    if not path.is_file():
        return out
    for line in _read_text(path).splitlines():
        s = line.strip()
        m = re.match(r"\[(.+)\]$", s)
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        if cur is not None and "=" in s and not s.startswith((";", "#", "<")):
            k, v = s.split("=", 1)
            cur[k.strip()] = v.strip()
    return out


@dataclass
class Launcher:
    emulator: str
    folder: Optional[Path]
    exe: str


class RocketLauncherIndex:
    def __init__(self, config: Config):
        self.rl_dir = Path(config.rocketlauncher_dir)
        self.emulators_dir = Path(config.emulators_dir) if config.emulators_dir else None
        self.settings = self.rl_dir / "Settings"
        self.global_emus = _read_ini_loose(self.settings / "Global Emulators.ini")

    def _system_ini(self, system: str) -> dict[str, dict[str, str]]:
        return _read_ini_loose(self.settings / system / "Emulators.ini")

    def default_emulator(self, system: str) -> str:
        ini = self._system_ini(system)
        return ini.get("ROMS", ini.get("Roms", {})).get("Default_Emulator", "")

    def game_overrides(self, system: str) -> dict[str, tuple[str, str]]:
        """``Games.ini``: game -> (emulator, system) for games not on the default emulator."""
        out = {}
        for game, keys in _read_ini_loose(self.settings / system / "Games.ini").items():
            emu, sysname = keys.get("Emulator", ""), keys.get("System", "")
            if emu or sysname:
                out[game] = (emu, sysname)
        return out

    def launcher(self, emulator: str, system: str) -> Optional[Launcher]:
        if not emulator:
            return None
        sec = self._system_ini(system).get(emulator) or self.global_emus.get(emulator)
        if not sec or not sec.get("Emu_Path"):
            return None
        p = PureWindowsPath(sec["Emu_Path"])
        folder: Optional[Path]
        parts = [x for x in p.parent.parts if x not in ("..", ".")]
        if not p.is_absolute() and parts and parts[0].lower() == "emulators" and self.emulators_dir:
            folder = self.emulators_dir.joinpath(*parts[1:])
        elif p.is_absolute():
            folder = Path(str(p.parent))
        else:
            folder = self.rl_dir.joinpath(*p.parent.parts)
        return Launcher(emulator=emulator, folder=folder, exe=p.name)


class KeymapResolver:
    """Resolve the keymap a (system, game) actually launches with."""

    def __init__(self, config: Config):
        self.rl = RocketLauncherIndex(config)
        self._ra: dict[Path, RetroArchIndex] = {}
        self._mame: dict[Path, MameIndex] = {}
        self._simple: dict[tuple[str, Path], Optional[Keymap]] = {}

    def for_launcher(self, launcher: Optional[Launcher], system: str,
                     game: Optional[str] = None) -> Optional[Keymap]:
        """Keymap for *launcher*; with *game*, only a game-specific keymap (else None)."""
        if launcher is None or launcher.folder is None or not launcher.folder.is_dir():
            return None
        exe = launcher.exe.lower()
        folder = launcher.folder
        if exe.startswith("retroarch"):
            ra = self._ra.setdefault(folder, RetroArchIndex(folder))
            km = ra.keymap(system, game)
            if km is not None:
                km.labels = dict(CONSOLE_LABELS.get(system, {}))
            return km
        if exe.startswith(("mame", "hbmame", "mess")):
            idx = self._mame.setdefault(folder, MameIndex(folder, launcher.exe))
            if system in MESS_DRIVERS:
                # Console run through MESS/MAME: one driver for the whole wheel.
                km = idx.driver_keymap(MESS_DRIVERS[system]) if not game else None
            elif system in MESS_PER_GAME_DRIVER:
                km = idx.driver_keymap(game) if game else None
            else:
                # Arcade ROM: default keys plus cfg/<game>.cfg.
                km = idx.keymap(game)
            if km is not None and (system in MESS_DRIVERS or system in MESS_PER_GAME_DRIVER):
                km.labels = dict(MESS_LABELS)
            return km
        if game:
            return None
        readers = {"desmume": desmume_keymap, "ssf.exe": ssf_keymap, "zinc.exe": zinc_keymap,
                   "demul.exe": demul_keymap, "daphne.exe": daphne_keymap,
                   "pokemini.exe": pokemini_keymap}
        for prefix, reader in readers.items():
            if exe.startswith(prefix):
                key = (prefix, folder)
                if key not in self._simple:
                    self._simple[key] = reader(folder)
                return self._simple[key]
        return None

    def system_launcher(self, system: str) -> Optional[Launcher]:
        return self.rl.launcher(self.rl.default_emulator(system), system)


# ── Controls.ini / Colors.ini ─────────────────────────────────────────────────

def read_ini_sections(path: Path) -> dict[str, dict[str, str]]:
    """Lower-cased section -> ordered {KEY: value} (keys keep their case)."""
    out: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return out
    cur: Optional[dict[str, str]] = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*\[(.+?)\]\s*$", line)
        if m:
            cur = out.setdefault(m.group(1).lower(), {})
        elif cur is not None and "=" in line and not line.lstrip().startswith(";"):
            k, v = line.split("=", 1)
            cur[k.strip()] = v.strip()
    return out


_UNKNOWN_LABEL_RE = re.compile(r"unknown|\?\?|not used|unused", re.I)


def community_joystick(section: dict[str, str]) -> Optional[str]:
    """Primary joystick control from a community ``P1Controls`` value.

    LEDBlinky switches the ServoStik from the profile's primary control, so a
    4-way game needs ``CONTROL_JOY4WAY`` rather than the 8-way default.
    """
    ctl = section.get("P1Controls", "").lower()
    if "joy4way" in ctl:
        return "CONTROL_JOY4WAY"
    if "joy2way" in ctl:
        return "CONTROL_JOY2WAY"
    return None


def set_primary_joystick(player0: str, control: Optional[str]) -> str:
    """Swap the CONTROL_JOY* primary control in a player-0 block."""
    if not control:
        return player0
    return re.sub(r'name="CONTROL_JOY\w+"', f'name="{control}"', player0, count=1)


def community_button_labels(section: dict[str, str]) -> dict[int, str]:
    """``{button_number: label}`` for P1, dropping unknown / unused buttons."""
    out = {}
    for k, v in section.items():
        m = re.fullmatch(r"P1_BUTTON(\d+)", k)
        if m and not _UNKNOWN_LABEL_RE.search(v):
            out[int(m.group(1))] = v
    return out


# ── LEDBlinkyControls.xml text editing ────────────────────────────────────────

_EMU_RE = re.compile(r'[ \t]*<emulator\b[^>]*emuname="([^"]*)"[^>]*>.*?</emulator>[ \t]*\n?', re.S)
_GROUP_RE = re.compile(r'[ \t]*<controlGroup\b[^>]*groupName="([^"]*)"[^>]*>.*?</controlGroup>[ \t]*\n?', re.S)


def _unescape(s: str) -> str:
    return s.replace("&amp;", "&").replace("&apos;", "'").replace("&quot;", '"')


@dataclass
class ControlXml:
    player: int
    name: str
    voice: str
    color: str
    input_codes: list[str]
    always_active: str = "0"
    extra: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        attrs = [f"name={quoteattr(self.name)}", f"voice={quoteattr(self.voice)}"]
        for k, v in self.extra.items():
            attrs.append(f"{k}={quoteattr(v)}")
        attrs += [f'alwaysActive="{self.always_active}"', f"color={quoteattr(self.color)}",
                  f"inputCodes={quoteattr('|'.join(self.input_codes))}"]
        return f"        <control {' '.join(attrs)} />"


@dataclass
class GroupXml:
    name: str
    voice: str = ""
    num_players: int = 2
    alternating: str = "0"
    player0: str = ""          # raw <player number="0">…</player> block, reused verbatim
    controls: list[ControlXml] = field(default_factory=list)
    default_attrs: bool = False

    def render(self) -> str:
        extra = ' defaultActive="48,48,48,48" defaultInactive="0,0,0,0"' if self.default_attrs else ""
        lines = [f"    <controlGroup groupName={quoteattr(self.name)} voice={quoteattr(self.voice)} "
                 f'numPlayers="{self.num_players}" alternating="{self.alternating}"{extra} jukebox="0">']
        if self.player0:
            lines.append("      " + self.player0.strip())
        for p in sorted({c.player for c in self.controls}):
            lines.append(f'      <player number="{p}">')
            lines.extend(c.render() for c in self.controls if c.player == p)
            lines.append("      </player>")
        lines.append("    </controlGroup>")
        return "\n".join(lines) + "\n"


def parse_group(block: str) -> tuple[ET.Element, str]:
    """Parse a controlGroup block; also return its raw player-0 block."""
    el = ET.fromstring(block.strip())
    m = re.search(r'<player number="0">.*?</player>', block, re.S)
    return el, (m.group(0) if m else "")


class ControlsXmlDoc:
    """Text-preserving editor for LEDBlinkyControls.xml."""

    def __init__(self, text: str):
        self.text = text

    def emulators(self) -> dict[str, str]:
        """emu_key -> raw emulator block (first occurrence)."""
        out = {}
        for m in _EMU_RE.finditer(self.text):
            out.setdefault(emu_key(_unescape(m.group(1))), m.group(0))
        return out

    @staticmethod
    def groups(emu_block: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for m in _GROUP_RE.finditer(emu_block):
            out.setdefault(emu_key(_unescape(m.group(1))), []).append(m.group(0))
        return out

    def _emu_span(self, key: str) -> Optional[re.Match]:
        for m in _EMU_RE.finditer(self.text):
            if emu_key(_unescape(m.group(1))) == key:
                return m
        return None

    def upsert_groups(self, system: str, groups: Iterable[GroupXml],
                      remove: Iterable[str] = ()) -> None:
        """Replace (or add) whole control groups under the emulator for *system*."""
        groups = list(groups)
        key = emu_key(system)
        m = self._emu_span(key)
        if m is None:
            block = (f"  <emulator emuname={quoteattr(system.replace(' ', '_'))} emuDesc=\"\">\n"
                     f"  </emulator>\n")
            anchor = re.search(r'[ \t]*<emulator\b[^>]*emuname="OTHER"', self.text)
            pos = anchor.start() if anchor else self.text.rfind("</dat>")
            self.text = self.text[:pos] + block + self.text[pos:]
            m = self._emu_span(key)
            assert m is not None
        block = m.group(0)
        drop = {emu_key(g.name) for g in groups} | {emu_key(r) for r in remove}
        placed: set[str] = set()
        rendered = {emu_key(g.name): g.render() for g in groups}

        def sub(gm: re.Match) -> str:
            k = emu_key(_unescape(gm.group(1)))
            if k not in drop:
                return gm.group(0)
            if k in rendered and k not in placed:
                placed.add(k)
                return rendered[k]
            return ""  # duplicate or removed group

        new_block = _GROUP_RE.sub(sub, block)
        missing = "".join(v for k, v in rendered.items() if k not in placed)
        if missing:
            close = new_block.rfind("</emulator>")
            line_start = new_block.rfind("\n", 0, close) + 1
            new_block = new_block[:line_start] + missing + new_block[line_start:]
        self.text = self.text[:m.start()] + new_block + self.text[m.end():]


# ── Profile building ──────────────────────────────────────────────────────────

_JOY_RE = re.compile(r"P\d_(JOYSTICK|JOYSTICKLEFT|JOYSTICKRIGHT)")
_FALLBACK_COLORS = ["Red", "Blue", "Yellow", "Lime", "Orange", "Magenta", "Cyan", "White"]


def _routed(keys: list[str], panel: dict[str, str]) -> bool:
    return any(k in panel for k in keys)


def _existing_controls(group: Optional[ET.Element]) -> list[ET.Element]:
    return [] if group is None else [c for p in group.iter("player")
                                     if p.get("number") != "0" for c in p.iter("control")]


def build_console_group(name: str, keymap: Keymap, panel: dict[str, str],
                        existing: Optional[ET.Element], player0: str) -> GroupXml:
    """A console profile: one control per keymap action that reaches a panel LED."""
    old = _existing_controls(existing)
    old_color_by_voice = {(c.get("voice") or "").lower(): c.get("color") or "" for c in old}
    old_color_by_key = {}
    for c in old:
        for k in (c.get("inputCodes") or "").split("|"):
            old_color_by_key.setdefault(k, c.get("color") or "")
    g = GroupXml(name=name, player0=player0, default_attrs=(name == "DEFAULT"),
                 voice="" if existing is None else existing.get("voice", ""))
    if existing is not None:
        g.num_players = int(existing.get("numPlayers") or 2)
        g.alternating = existing.get("alternating") or "0"
    labels = keymap.labels or {}
    actions = list(labels) + sorted({a for (_, a) in keymap.keys if a not in labels})
    for p in (1, 2):
        n = 0
        extra_n = 8
        player_controls: list[ControlXml] = []
        needs_color: list[ControlXml] = []
        for act in actions:
            keys = keymap.get(p, act)
            if not keys or not _routed(keys, panel):
                continue
            voice = labels.get(act) or f"Button {act.upper()}"
            is_system_button = act.lower() in ("start", "select", "coin", "power", "mode", "run", "option")
            if is_system_button:
                extra_n += 1
                cname = f"P{p}_BUTTON{extra_n}"
            else:
                n += 1
                cname = f"P{p}_BUTTON{n}"
            color = old_color_by_voice.get(voice.lower()) or old_color_by_key.get(keys[0]) or ""
            ctl = ControlXml(p, cname, voice, color, keys)
            if is_system_button:
                ctl.color = color or "Black"   # the cabinet's dim white for Start / Select
            elif color in ("", "Black") or re.fullmatch(r"[\d, ]+", color):
                needs_color.append(ctl)        # a used button must be visibly lit
            player_controls.append(ctl)
        # Kept colors first, then palette colors this player isn't using yet.
        used = {c.color for c in player_controls if c not in needs_color}
        spare = [c for c in _FALLBACK_COLORS if c not in used] or _FALLBACK_COLORS
        for i, ctl in enumerate(needs_color):
            ctl.color = spare[i % len(spare)]
        g.controls.extend(player_controls)
        # Joystick controls carry no LED but keep the player's direction voices.
        for c in old:
            if c.get("name", "").startswith(f"P{p}_") and _JOY_RE.match(c.get("name", "")):
                g.controls.append(ControlXml(p, c.get("name"), c.get("voice") or "",
                                             c.get("color") or "", (c.get("inputCodes") or "").split("|")))
    return g


_ARCADE_KEY_RE = re.compile(r"P(\d)_(BUTTON\d+|START|COIN|TRACKBALL)$")


def build_arcade_group(game: str, controls: dict[str, str], colors: dict[str, str],
                       keymap: Keymap, panel: dict[str, str], player0: str,
                       voices: Optional[dict[int, str]] = None,
                       default_colors: Optional[dict[str, str]] = None,
                       description: str = "") -> GroupXml:
    """A per-game arcade profile from a Controls.ini section and the emulator's keys."""
    voices = voices or {}
    default_colors = default_colors or {}
    g = GroupXml(name=group_name(game), voice=description, player0=player0,
                 num_players=max(1, min(int(controls.get("numPlayers") or 1), 2)),
                 alternating=controls.get("alternating", "0") or "0")
    for key in controls:
        m = _ARCADE_KEY_RE.match(key)
        if not m or int(m.group(1)) > 2:
            continue
        p, act = int(m.group(1)), m.group(2)
        if act == "TRACKBALL":
            keys = ["TRACKBALL"]
            name, voice = f"P{p}_TRACKBALL", "Trackball"
        else:
            keys = keymap.get(p, act)
            name = {"START": f"START{p}", "COIN": f"COIN{p}"}.get(act, f"P{p}_{act}")
            voice = {"START": "Start Game", "COIN": "Insert Coin"}.get(
                act, voices.get(int(act[6:]), "") if act.startswith("BUTTON") else "")
        if not _routed(keys, panel):
            continue
        color = (colors.get(key) or colors.get(f"P1_{act}") or default_colors.get(name)
                 or default_colors.get(f"P1_{act}") or "White")
        g.controls.append(ControlXml(p, name, voice, color, keys))
    return g


def rekey_arcade_group(block: str, keymap: Keymap, panel: dict[str, str]) -> Optional[str]:
    """Re-key P{n}_BUTTON{k} / START / COIN controls of an existing group to *keymap*.

    Returns the new block, or None when nothing changes.
    """
    changed = False

    def sub(m: re.Match) -> str:
        nonlocal changed
        tag = m.group(0)
        nm = re.search(r'name="([^"]*)"', tag)
        if not nm:
            return tag
        name = nm.group(1)
        mm = re.fullmatch(r"P(\d)_(BUTTON\d+)", name) or re.fullmatch(r"(START|COIN)(\d)", name)
        if not mm:
            return tag
        if name.startswith(("START", "COIN")):
            p, act = int(mm.group(2)), mm.group(1)
        else:
            p, act = int(mm.group(1)), mm.group(2)
        keys = [k for k in keymap.get(p, act) if k in panel]
        new = "|".join(keys)
        if re.search(r'inputCodes="([^"]*)"', tag):
            out = re.sub(r'inputCodes="[^"]*"', f'inputCodes="{new}"', tag)
        else:
            out = tag.replace("/>", f'inputCodes="{new}" />')
        changed |= out != tag
        return out

    new_block = re.sub(r"<control\b[^>]*/>", sub, block)
    return new_block if changed else None


# ── Plan / result ─────────────────────────────────────────────────────────────

@dataclass
class SystemAction:
    system: str
    action: str             # what was done
    groups: int = 0
    source: str = ""        # keymap source
    note: str = ""


@dataclass
class ProfilesResult:
    dry_run: bool = True
    actions: list[SystemAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    controls_ini_added: list[tuple[str, str]] = field(default_factory=list)   # (rom, donor)
    controls_ini_community: list[str] = field(default_factory=list)
    unresolved_roms: list[tuple[str, str]] = field(default_factory=list)      # (system, rom)
    unroutable_keys: dict[str, set[str]] = field(default_factory=dict)        # key -> systems
    written: list[Path] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)

    @property
    def groups_written(self) -> int:
        return sum(a.groups for a in self.actions)


# ── Databases ─────────────────────────────────────────────────────────────────

@dataclass
class DbGame:
    name: str
    description: str
    cloneof: str


def load_db(config: Config, system: str) -> Optional[list[DbGame]]:
    path = config.databases_dir / system / f"{system}.xml"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        root = ET.fromstring(text.encode("utf-8"))
        games = root.iter("game")
        return [DbGame(g.get("name") or "", g.findtext("description") or "",
                       g.findtext("cloneof") or "") for g in games]
    except ET.ParseError:
        return [DbGame(n, "", "") for n in re.findall(r'<game name="([^"]*)"', text)]


def main_menu_systems(config: Config) -> list[str]:
    games = load_db(config, "Main Menu") or []
    return [g.name for g in games]


# ── Engine ────────────────────────────────────────────────────────────────────

#: Wheels played with a light gun or wheel: when their keymap can't be read,
#: only Start / Coin light (plus the admin buttons).
_START_COIN_ONLY_WHEELS = ("Driving Games", "Gun Games", "Gun Games (Sinden)", "Gun Games (Other)")

_SUFFIX_RE = re.compile(r"(xbox|2play|4play)$", re.I)

#: Wheels renamed since their LEDBlinky section was set up: new wheel -> old section.
LEGACY_SECTIONS = {"Doujin Games": "Doujin_Soft"}


class ProfileBuilder:
    def __init__(self, config: Config):
        if not config.ledblinky_dir:
            raise ValueError("ledblinky_dir not configured. Run: spindoctor config set ledblinky_dir <path>")
        if not config.rocketlauncher_dir:
            raise ValueError("rocketlauncher_dir not configured.")
        self.config = config
        self.lb_dir = Path(config.ledblinky_dir)
        self.panel = load_panel(self.lb_dir)
        self.resolver = KeymapResolver(config)
        self.xml_path = self.lb_dir / CONTROLS_XML_NAME
        self.doc = ControlsXmlDoc(self.xml_path.read_text(encoding="utf-8", errors="replace"))
        self.controls_path = self.lb_dir / CONTROLS_INI_FILE
        self.colors_path = self.lb_dir / COLORS_INI_NAME
        self.controls = read_ini_sections(self.controls_path)
        self.colors = read_ini_sections(self.colors_path)
        community = sorted(self.lb_dir.glob(COMMUNITY_CONTROLS_GLOB))
        self.community = read_ini_sections(community[0]) if community else {}
        self.result = ProfilesResult()
        # Controls.ini / Colors.ini edits: rom -> new body lines (None = unchanged)
        self._controls_new: dict[str, dict[str, str]] = {}
        self._colors_new: dict[str, dict[str, str]] = {}
        self._mame_groups = self.doc.groups(self.doc.emulators().get("MAME", ""))

    # -- helpers --------------------------------------------------------------

    def _default_block(self, system: str) -> tuple[Optional[ET.Element], str]:
        emu = self.doc.emulators().get(emu_key(system))
        blocks = self.doc.groups(emu).get("DEFAULT") if emu else None
        if blocks:
            return parse_group(blocks[0])
        return None, ""

    def _admin_player0(self) -> str:
        """Admin block (Exit / Pause / Select) with explicit key codes.

        MAME's own DEFAULT leaves ``inputCodes`` empty because LEDBlinky reads
        MAME's cfg for them; copied under any other emulator that lights
        nothing.  Take the block from a console DEFAULT that carries codes,
        which also keeps whatever ``admin-leds`` last set.
        """
        if hasattr(self, "_admin_cache"):
            return self._admin_cache
        emus = self.doc.emulators()
        order = ["NINTENDO_ENTERTAINMENT_SYSTEM"] + sorted(emus)
        for key in order:
            blocks = self.doc.groups(emus.get(key, "")).get("DEFAULT")
            if not blocks:
                continue
            p0 = parse_group(blocks[0])[1]
            if re.search(r'name="UI_CANCEL"[^>]*inputCodes="KEYCODE_', p0):
                self._admin_cache = p0
                return p0
        self._admin_cache = (
            '<player number="0">\n'
            '        <control name="UI_CANCEL" voice="" alwaysActive="1" color="Plum" inputCodes="KEYCODE_ESC" />\n'
            '        <control name="UI_PAUSE" voice="" alwaysActive="1" color="Amber" inputCodes="KEYCODE_P|KEY_MAMEPAUSE" />\n'
            '      </player>')
        return self._admin_cache

    def _ensure_admin(self, block: str) -> str:
        """Add the Exit / Pause admin controls to a group that has none."""
        if "UI_CANCEL" in block:
            return block
        admin = self._admin_player0()
        ui_lines = [ln for ln in admin.splitlines() if re.search(r'name="UI_', ln)]
        if not ui_lines:
            return block
        m = re.search(r'(<player number="0">.*?)(\s*</player>)', block, re.S)
        if m:
            return block[:m.end(1)] + "\n" + "\n".join(ln.rstrip() for ln in ui_lines) + block[m.end(1):]
        m = re.search(r"<controlGroup\b[^>]*>", block)
        assert m is not None
        return block[:m.end()] + "\n      " + admin.strip() + block[m.end():]

    def _note_unroutable(self, keymap: Keymap, system: str) -> None:
        for (p, act), keys in keymap.keys.items():
            for k in keys:
                if k in ("KEYCODE_V", "KEYCODE_W", "KEYCODE_Y", "KEYCODE_X") and k not in self.panel:
                    self.result.unroutable_keys.setdefault(k, set()).add(system)

    def community_for(self, rom: str) -> dict[str, str]:
        """Community controls.dat entry for *rom*, falling back to its parent ROM."""
        if not hasattr(self, "_parents"):
            self._parents = {g.name.lower(): g.cloneof.lower()
                             for s in ("MAME", "HBMAME") for g in load_db(self.config, s) or [] if g.cloneof}
        low = rom.lower()
        for cand in (low, _SUFFIX_RE.sub("", low), self._parents.get(low, "")):
            if cand and cand in self.community:
                return self.community[cand]
        return {}

    def controls_for(self, rom: str) -> Optional[dict[str, str]]:
        low = rom.lower()
        if low in self._controls_new:
            return self._controls_new[low]
        return self.controls.get(low)

    def colors_for(self, rom: str) -> dict[str, str]:
        low = rom.lower()
        return self._colors_new.get(low) or self.colors.get(low) or {}

    def _donor(self, game: DbGame, by_desc: dict[str, str]) -> Optional[str]:
        """Best Controls.ini entry for a ROM that has none of its own."""
        for cand in (game.cloneof, _SUFFIX_RE.sub("", game.name)):
            if cand and cand.lower() != game.name.lower() and self.controls_for(cand):
                return cand
        name = game.name.lower()
        for cut in range(len(name) - 1, len(name) - 3, -1):
            if cut > 2 and self.controls_for(name[:cut]):
                return name[:cut]
        if len(name) > 4:
            # Regional clone differing only in its last letter (souledga -> souledge).
            known = set(self.controls) | set(self._controls_new)
            same = sorted(k for k in known if len(k) == len(name) and k[:-1] == name[:-1])
            if same:
                return same[0]
        base = re.sub(r"\s*[\(\[].*$", "", game.description).strip().lower()
        return by_desc.get(base)

    # -- steps ----------------------------------------------------------------

    def apply_community(self, library: set[str]) -> None:
        """Use the curated community button count where it disagrees with MAME's.

        Only ROMs in *library* (lower-cased names from the arcade wheels) are
        touched, so games nobody launches don't churn Controls.ini.
        """
        mame = self.resolver.system_launcher("MAME")
        mame_cfg = mame.folder / "cfg" if mame and mame.folder else None
        for rom, sec in self.community.items():
            cur = self.controls.get(rom)
            if rom not in library or cur is None or "P1NumButtons" not in sec:
                continue
            if emu_key(rom) in self._mame_groups:
                continue  # LEDBlinky uses the XML group, not Controls.ini
            if mame_cfg and any(p.startswith("P1_BUTTON") for p in _mame_cfg_ports(mame_cfg / f"{rom}.cfg")):
                continue  # the cabinet remapped this game's buttons: trust that

            labels = community_button_labels(sec)
            want = len(labels)
            have = len([k for k in cur if re.fullmatch(r"P1_BUTTON\d+", k)])
            if int(sec.get("P1NumButtons") or 0) == have:
                continue
            new = {k: v for k, v in cur.items() if not re.fullmatch(r"P\d_BUTTON\d+", k)}
            players = sorted({int(m.group(1)) for k in cur for m in [re.match(r"P(\d)_", k)] if m} or {1})
            ordered: dict[str, str] = {k: new[k] for k in ("numPlayers", "alternating") if k in new}
            for p in players:
                for b in sorted(labels)[:want]:
                    ordered[f"P{p}_BUTTON{b}"] = "1"
                for k, v in new.items():
                    if k.startswith(f"P{p}_"):
                        ordered[k] = v
            if ordered == cur:
                continue
            self._controls_new[rom] = ordered
            col = dict(self.colors.get(rom, {}))
            fill = col.get("P1_BUTTON1") or "Red"
            col = {k: v for k, v in col.items()
                   if not re.fullmatch(r"P\d_BUTTON\d+", k) or k in ordered}
            for k in ordered:
                if re.fullmatch(r"P\d_BUTTON\d+", k) and k not in col:
                    col[k] = col.get("P1_" + k.split("_", 1)[1]) or fill
            self._colors_new[rom] = col
            self.result.controls_ini_community.append(rom)

    def fill_mame_family(self, systems: list[str]) -> None:
        """Give every ROM in a MAME-named wheel a Controls.ini + Colors.ini entry."""
        mame_db = load_db(self.config, "MAME") or []
        by_desc = {}
        for g in mame_db:
            base = re.sub(r"\s*[\(\[].*$", "", g.description).strip().lower()
            if self.controls_for(g.name):
                by_desc.setdefault(base, g.name)
        pending = [(s, g) for s in systems for g in load_db(self.config, s) or []
                   if not self.controls_for(g.name) and emu_key(g.name) not in self._mame_groups]
        added: dict[str, int] = {}
        # Repeat until nothing new resolves: a hack's parent may itself be a
        # hack that only gets its entry earlier in this pass.
        while pending:
            left = []
            for system, game in pending:
                if self.controls_for(game.name):
                    continue   # same ROM in two wheels, already added
                donor = self._donor(game, by_desc)
                if not donor:
                    left.append((system, game))
                    continue
                self._controls_new[game.name.lower()] = dict(self.controls_for(donor) or {})
                self._colors_new[game.name.lower()] = dict(self.colors_for(donor))
                self.result.controls_ini_added.append((game.name, donor))
                added[system] = added.get(system, 0) + 1
            if len(left) == len(pending):
                break
            pending = left
        self.result.unresolved_roms.extend((s, g.name) for s, g in pending)
        for system in systems:
            if added.get(system):
                self.result.actions.append(SystemAction(system, "Controls.ini entries from parent/base ROM",
                                                        added[system], "Controls.ini"))

    def console_default(self, system: str) -> None:
        launcher = self.resolver.system_launcher(system)
        keymap = self.resolver.for_launcher(launcher, system)
        existing, player0 = self._default_block(system)
        if keymap is None:
            emu = launcher.emulator if launcher else "(none)"
            if existing is None:
                self._admin_only(system, f"no readable keymap for {emu}")
            else:
                self.result.actions.append(SystemAction(system, "kept existing DEFAULT", 0, "",
                                                        f"keymap for {emu} not readable"))
            return
        self._note_unroutable(keymap, system)
        grp = build_console_group("DEFAULT", keymap, self.panel, existing, player0 or self._admin_player0())
        self.doc.upsert_groups(system, [grp])
        # Per-game variants take their colors from the new DEFAULT, so a rerun
        # produces the same file.
        existing = ET.fromstring(grp.render())
        lit = sorted({self.panel[k] for c in grp.controls for k in c.input_codes if k in self.panel})
        self.result.actions.append(SystemAction(system, "DEFAULT from keymap", 1, keymap.source,
                                                "lights " + (", ".join(lit) if lit else "nothing (pad-only)")))
        self._game_overrides(system, launcher, keymap, existing, player0)

    def _game_overrides(self, system: str, launcher: Optional[Launcher], sys_keymap: Keymap,
                        existing: Optional[ET.Element], player0: str) -> None:
        """Per-game groups where a game launches with different keys than its system."""
        games = {g.name for g in load_db(self.config, system) or []}
        groups = []
        for game, (emu, other_sys) in self.resolver.rl.game_overrides(system).items():
            if game not in games or not emu:
                continue
            lau = self.resolver.rl.launcher(emu, other_sys or system)
            km = self.resolver.for_launcher(lau, other_sys or system)
            if km is None:
                self.result.warnings.append(f"{system}: '{game}' uses {emu}; its keymap isn't readable — kept system DEFAULT")
                continue
            km.labels = km.labels or sys_keymap.labels
            groups.append(build_console_group(group_name(game), km, self.panel, existing,
                                              player0 or self._admin_player0()))
        if launcher and launcher.exe.lower().startswith("retroarch"):
            for game in sorted(games):
                km = self.resolver.for_launcher(launcher, system, game)
                if km is not None and km.keys != sys_keymap.keys:
                    km.labels = sys_keymap.labels
                    groups.append(build_console_group(group_name(game), km, self.panel, existing,
                                                      player0 or self._admin_player0()))
        if groups:
            self.doc.upsert_groups(system, groups)
            self.result.actions.append(SystemAction(system, "per-game groups (emulator/keymap overrides)",
                                                    len(groups), "Games.ini / RetroArch game cfg"))

    def handheld_wheel(self, system: str) -> None:
        """Per-game groups for wheels where each game is its own MAME driver."""
        launcher = self.resolver.system_launcher(system)
        existing, player0 = self._default_block(system)
        groups = []
        for game in load_db(self.config, system) or []:
            km = self.resolver.for_launcher(launcher, system, game.name)
            if km is not None:
                groups.append(build_console_group(group_name(game.name), km, self.panel, None,
                                                  player0 or self._admin_player0()))
        if existing is None:
            groups.append(GroupXml(name="DEFAULT", player0=self._admin_player0(), default_attrs=True))
        self.doc.upsert_groups(system, groups)
        src = launcher.emulator if launcher else "?"
        self.result.actions.append(SystemAction(system, "per-game handheld groups", len(groups), src))

    def _admin_only(self, system: str, why: str) -> None:
        grp = GroupXml(name="DEFAULT", player0=self._admin_player0(), default_attrs=True)
        self.doc.upsert_groups(system, [grp])
        self.result.actions.append(SystemAction(system, "admin-only DEFAULT (Exit/Pause)", 1, "", why))

    def arcade_wheel(self, system: str) -> None:
        """Per-game groups for an arcade wheel LEDBlinky doesn't treat as MAME."""
        launcher = self.resolver.system_launcher(system)
        overrides = self.resolver.rl.game_overrides(system)
        player0 = self._default_block(system)[1] or self._admin_player0()
        existing_emu = self.doc.emulators().get(emu_key(system), "")
        existing_groups = self.doc.groups(existing_emu)
        default_el = self._default_block(system)[0]
        default_colors = {c.get("name"): c.get("color") for c in _existing_controls(default_el)}
        groups, unresolved, assumed = [], 0, 0
        for game in load_db(self.config, system) or []:
            emu, other = overrides.get(game.name, ("", ""))
            lau = self.resolver.rl.launcher(emu, other or system) if emu else launcher
            km = None
            if lau is not None:
                exe = lau.exe.lower()
                if exe.startswith(("mame", "hbmame")):
                    km = self.resolver.for_launcher(lau, system, game.name)
                else:
                    km = self.resolver.for_launcher(lau, other or system)
            if km is None:
                if system in _START_COIN_ONLY_WHEELS:
                    km = Keymap(source="start/coin only", verified=False,
                                keys={k: v for k, v in arcade_layout_keymap().keys.items()
                                      if k[1] in ("START", "COIN")})
                else:
                    km = arcade_layout_keymap()
                assumed += 1
            ctl = self.controls_for(game.name)
            if ctl is None:
                donor = self._donor(game, {})
                ctl = self.controls_for(donor) if donor else None
            if ctl is None:
                if emu_key(game.name) in existing_groups:
                    continue
                unresolved += 1
                self.result.unresolved_roms.append((system, game.name))
                ctl = {"numPlayers": "2", **{f"P{p}_{a}": "1" for p in (1, 2) for a in ("START", "COIN")}}
            base = _SUFFIX_RE.sub("", game.name).lower()
            community = self.community_for(game.name)
            voices = community_button_labels(community)
            colors = self.colors_for(game.name) or self.colors_for(base)
            groups.append(build_arcade_group(game.name, ctl, colors, km, self.panel,
                                             set_primary_joystick(player0, community_joystick(community)),
                                             voices, default_colors, game.description))
        self.doc.upsert_groups(system, groups)
        src = f"{launcher.emulator} ({launcher.folder.name if launcher and launcher.folder else '?'})" if launcher else "?"
        note = []
        if assumed:
            note.append(f"{assumed} on unreadable emulators (assumed layout)")
        if unresolved:
            note.append(f"{unresolved} with no controls data (start/coin only)")
        self.result.actions.append(SystemAction(system, "per-game arcade groups", len(groups), src, "; ".join(note)))

    def rekey_existing_arcade(self, system: str) -> None:
        """Fix the button 4-8 keys of an arcade emulator's existing groups."""
        launcher = self.resolver.system_launcher(system)
        km = self.resolver.for_launcher(launcher, system)
        if km is None or not km.keys:
            km = arcade_layout_keymap()
        emu_block = self.doc.emulators().get(emu_key(system))
        if not emu_block:
            return
        fixed = 0
        new_emu = emu_block
        for blocks in self.doc.groups(emu_block).values():
            for b in blocks:
                nb = self._ensure_admin(rekey_arcade_group(b, km, self.panel) or b)
                if nb != b:
                    new_emu = new_emu.replace(b, nb, 1)
                    fixed += 1
        if fixed:
            self.doc.text = self.doc.text.replace(emu_block, new_emu, 1)
        self.result.actions.append(SystemAction(system, "re-keyed existing arcade groups", fixed, km.source,
                                                "" if km.verified else "keys assumed from cabinet arcade layout"))
        # Games with no group of their own but with controls data get one.
        have = self.doc.groups(self.doc.emulators().get(emu_key(system), ""))
        default_el, player0 = self._default_block(system)
        default_colors = {c.get("name"): c.get("color") for c in _existing_controls(default_el)}
        new = []
        for game in load_db(self.config, system) or []:
            if emu_key(game.name) in have:
                continue
            ctl = self.controls_for(game.name)
            if ctl is None:
                continue
            community = self.community_for(game.name)
            new.append(build_arcade_group(
                game.name, ctl, self.colors_for(game.name), km, self.panel,
                set_primary_joystick(player0 or self._admin_player0(), community_joystick(community)),
                community_button_labels(community), default_colors, game.description))
        if new:
            self.doc.upsert_groups(system, new)
            self.result.actions.append(SystemAction(system, "new per-game arcade groups", len(new), km.source))

    def migrate_legacy_section(self, system: str, legacy_emu: str) -> None:
        """Carry an old emulator section's groups over to a renamed wheel, re-keyed."""
        emus = self.doc.emulators()
        old = emus.get(emu_key(legacy_emu))
        if not old or emu_key(system) in emus:
            return
        games = {emu_key(g.name) for g in load_db(self.config, system) or []} | {"DEFAULT"}
        km = arcade_layout_keymap()
        blocks = []
        for key, bl in self.doc.groups(old).items():
            if key in games:
                blocks.append(self._ensure_admin(rekey_arcade_group(bl[0], km, self.panel) or bl[0]))
        block = (f"  <emulator emuname={quoteattr(system.replace(' ', '_'))} emuDesc=\"\">\n"
                 + "".join(b if b.endswith("\n") else b + "\n" for b in blocks) + "  </emulator>\n")
        anchor = re.search(r'[ \t]*<emulator\b[^>]*emuname="OTHER"', self.doc.text)
        pos = anchor.start() if anchor else self.doc.text.rfind("</dat>")
        self.doc.text = self.doc.text[:pos] + block + self.doc.text[pos:]
        self.result.actions.append(SystemAction(system, f"groups carried over from {legacy_emu}", len(blocks),
                                                km.source, "keys assumed from cabinet arcade layout"))

    # -- collections ----------------------------------------------------------

    def resolved_group(self, system: str, rom: str) -> Optional[GroupXml | str]:
        """The profile LEDBlinky would use for *rom* launched from *system* (post-edit)."""
        if is_mame_named(system):
            ctl = self.controls_for(rom)
            xml_blocks = self._mame_groups.get(emu_key(rom))
            if xml_blocks:
                # LEDBlinky uses the MAME XML group's control list for this ROM.
                el = parse_group(xml_blocks[0])[0]
                ctl = {"numPlayers": el.get("numPlayers") or "2"}
                rename = {"START1": "P1_START", "START2": "P2_START", "COIN1": "P1_COIN", "COIN2": "P2_COIN"}
                for c in _existing_controls(el):
                    name = c.get("name", "")
                    ctl[rename.get(name, name)] = "1"
                ctl.setdefault("P1_START", "1")
                ctl.setdefault("P1_COIN", "1")
            if ctl is None:
                return None
            community = self.community_for(rom)
            joystick = community_joystick(community)
            if xml_blocks:
                voices = {int(m.group(1)): c.get("voice") or ""
                          for c in _existing_controls(parse_group(xml_blocks[0])[0])
                          for m in [re.fullmatch(r"P1_BUTTON(\d+)", c.get("name", ""))] if m}
                m = re.search(r'name="(CONTROL_JOY\w+)"', xml_blocks[0])
                joystick = m.group(1) if m else joystick
            else:
                voices = community_button_labels(community)
            mame_launcher = self.resolver.system_launcher(system)
            km = self.resolver.for_launcher(mame_launcher, system, rom) or arcade_layout_keymap()
            return build_arcade_group(rom, ctl, self.colors_for(rom), km, self.panel,
                                      set_primary_joystick(self._admin_player0(), joystick), voices)
        emu = self.doc.emulators().get(emu_key(system))
        if not emu:
            return None
        groups = self.doc.groups(emu)
        blocks = groups.get(emu_key(rom)) or groups.get("DEFAULT")
        return blocks[0] if blocks else None

    def collection(self, system: str, members: Optional[list[tuple[str, str, str]]] = None) -> None:
        """Per-game groups for a collection wheel, copied from each game's source system."""
        if members is None:
            members = collection_members(self.config, system)
        groups: list[GroupXml] = []
        raw: list[str] = []
        for target, src_sys, src_rom in members:
            g = self.resolved_group(src_sys, src_rom)
            if g is None:
                self.result.unresolved_roms.append((system, target))
                continue
            if isinstance(g, GroupXml):
                g.name = group_name(target)
                groups.append(g)
            else:
                raw.append(re.sub(r'groupName="[^"]*"', f"groupName={quoteattr(group_name(target))}", g, count=1))
        # Rebuild the collection's emulator section from scratch: members change.
        key = emu_key(system)
        m = self.doc._emu_span(key)
        if m is not None:
            self.doc.text = self.doc.text[:m.start()] + self.doc.text[m.end():]
        self.doc.upsert_groups(system, groups)
        if raw:
            m = self.doc._emu_span(key)
            assert m is not None
            block = m.group(0)
            close = block.rfind("</emulator>")
            line_start = block.rfind("\n", 0, close) + 1
            block = block[:line_start] + "".join(r if r.endswith("\n") else r + "\n" for r in raw) + block[line_start:]
            self.doc.text = self.doc.text[:m.start()] + block + self.doc.text[m.end():]
        self.result.actions.append(SystemAction(system, "collection groups (copied from source system)",
                                                len(groups) + len(raw), "source profiles"))

    # -- write ----------------------------------------------------------------

    def _rewrite_ini(self, path: Path, new: dict[str, dict[str, str]]) -> Optional[str]:
        if not new:
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        parts: list[str] = []
        seen: set[str] = set()
        for name, header, body in _split_ini_by_sections(text):
            if name is None or name.lower() not in new:
                if header:
                    parts.append(header)
                parts.extend(body)
                continue
            seen.add(name.lower())
            parts.append(header)
            parts.extend(f"{k}={v}\n" for k, v in new[name.lower()].items())
            parts.append("\n")
        tail = [r for r in new if r not in seen]
        if tail and parts and not parts[-1].endswith("\n"):
            parts.append("\n")
        for rom in tail:
            parts.append(f"[{rom}]\n")
            parts.extend(f"{k}={v}\n" for k, v in new[rom].items())
            parts.append("\n")
        return "".join(parts)

    def write(self, dry_run: bool, backup: bool = True) -> ProfilesResult:
        self.result.dry_run = dry_run
        outputs = [(self.xml_path, self.doc.text if self.doc.text != self.xml_path.read_text(
            encoding="utf-8", errors="replace") else None),
            (self.controls_path, self._rewrite_ini(self.controls_path, self._controls_new)),
            (self.colors_path, self._rewrite_ini(self.colors_path, self._colors_new))]
        for path, text in outputs:
            if text is None:
                continue
            if path.suffix.lower() == ".xml":
                ET.fromstring(text.encode("utf-8"))  # refuse to write a broken file
            if not dry_run:
                if backup:
                    b = _backup(path, _config_backup_dir(self.config))
                    if b:
                        self.result.backups.append(b)
                path.write_text(text, encoding="utf-8")
            self.result.written.append(path)
        return self.result


def collection_members(config: Config, system: str) -> list[tuple[str, str, str]]:
    """(target_name, source_system, source_rom) for a collection wheel.

    Uses RocketLauncher's PCLauncher system INI (exact) when present, else the
    ``(System)`` suffix SpinDoctor appends to each description.
    """
    out = []
    ini = Path(config.rocketlauncher_dir) / "Modules" / "PCLauncher" / f"{system}.ini"
    if ini.is_file():
        for name, keys in _read_ini_loose(ini).items():
            m = re.search(r'-s "([^"]+)" -r "([^"]+)"', keys.get("Parameters", ""))
            if m:
                out.append((name, m.group(1), m.group(2)))
        return out
    cache: dict[str, list[DbGame]] = {}
    # Longest first so "MAME (Vector)" wins over a bare "(Vector)" suffix.
    known = sorted(main_menu_systems(config), key=len, reverse=True)
    for g in load_db(config, system) or []:
        src = next((s for s in known if g.description.lower().endswith(f" ({s.lower()})")), None)
        if src is None:
            continue
        base = g.description[: -len(src) - 3]
        src_games = cache.setdefault(src, load_db(config, src) or [])
        names = {x.name for x in src_games}
        rom = g.name if g.name in names else next((x.name for x in src_games if x.description == base), g.name)
        out.append((g.name, src, rom))
    return out


# ── Entry points ──────────────────────────────────────────────────────────────

def plan_profiles(config: Config) -> ProfileBuilder:
    """Build every profile in memory; call ``.write()`` on the result to persist."""
    b = ProfileBuilder(config)
    systems = main_menu_systems(config)
    library: set[str] = set()
    for s in systems:
        lau = b.resolver.system_launcher(s)
        if is_mame_named(s) or (lau and lau.exe.lower().startswith(("mame", "hbmame", "zinc"))):
            library |= {g.name.lower() for g in load_db(config, s) or []}
    b.apply_community(library)
    b.fill_mame_family([s for s in systems if is_mame_named(s)])
    for system, legacy in LEGACY_SECTIONS.items():
        if system in systems:
            b.migrate_legacy_section(system, legacy)
    for system in systems:
        if is_mame_named(system) or system in COLLECTION_SYSTEMS:
            continue
        if system in LEGACY_SECTIONS and emu_key(system) in b.doc.emulators():
            continue
        launcher = b.resolver.system_launcher(system)
        exe = launcher.exe.lower() if launcher else ""
        if exe.startswith(("mame", "hbmame")) and system not in MESS_DRIVERS and system not in MESS_PER_GAME_DRIVER:
            b.arcade_wheel(system)
        elif exe.startswith(("zinc", "demul", "daphne", "emulator_multicpu", "supermodel", "aae")) \
                or system in ("Sega Model 3", "Sega Triforce", "Taito Type X"):
            if system in ("Zinc", "Sega Hikaru") or emu_key(system) not in b.doc.emulators():
                b.arcade_wheel(system)
            else:
                b.rekey_existing_arcade(system)
        elif system in MESS_PER_GAME_DRIVER:
            b.handheld_wheel(system)
        else:
            b.console_default(system)
    for system in COLLECTION_SYSTEMS:
        if system in systems:
            b.collection(system)
    return b


def sync_collection(config: Config, system: str, dry_run: bool = True,
                    backup: bool = True) -> ProfilesResult:
    """Refresh one collection wheel's profiles (called after a wheel rebuild)."""
    b = ProfileBuilder(config)
    b.collection(system)
    return b.write(dry_run=dry_run, backup=backup)
