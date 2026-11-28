"""Per-game LEDBlinky profiles derived from the cabinet's real emulator keymaps.

LEDBlinky picks a profile for a launched game in this order (confirmed against
``Debug.log`` on the cabinet):

* The emulator name is the HyperSpin wheel name, upper-cased, spaces -> ``_``,
  cut at its last dot (``Nokia N-Gage 2.0`` -> ``NOKIA_N-GAGE_2``).  Game
  names keep their dots.
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

RocketLauncher's AHK keymapper can swap keys while a game runs (``r::1``: the
panel's R reaches the emulator as 1).  Where it is on, each key is mapped back
through the game's AHK profile to the panel keys that really send it.  Where
the emulator's own keys can't be read (a PC game launcher, a Flash player),
the keys the game's profile remaps or binds are lit instead.
"""
from __future__ import annotations

import configparser
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Iterable, Optional
from xml.sax.saxutils import quoteattr

from ._utils import atomic_write_bytes
from .config import CONFIG_DIR, Config
from .ledblinky import (
    COLORS_INI_NAME,
    CONTROLS_XML_NAME,
    _backup,
    _config_backup_dir,
    wheel_section_name,
)
from .ledblinky_library import Library, RawIni, find_community_controls, render_section
from .rl_rom_paths import _RomLookup
from ._text import read_editable_text, read_windows_text, write_windows_text

INPUT_MAP_NAME = "LEDBlinkyInputMap.xml"
CONTROLS_INI_FILE = "Controls.ini"

#: Wheels whose games are other wheels' games; profiles are copied per game.
COLLECTION_SYSTEMS = ("Favorites", "Most Played", "Recently Played")

#: Wheels LEDBlinky already treats as MAME (Controls.ini + MAME's cfg).
def is_mame_named(system: str) -> bool:
    return "MAME" in system.upper()


def emu_key(system: str) -> str:
    """LEDBlinky's emulator / game key: upper-case, spaces -> underscores."""
    return system.strip().upper().replace(" ", "_")


def system_key(system: str) -> str:
    """The key of the ``<emulator>`` section LEDBlinky uses for wheel *system*.

    Unlike a game's name, a wheel's is cut at its last dot first
    (``wheel_section_name``), so ``Tiger Game.com`` is ``TIGER_GAME``.
    """
    return emu_key(wheel_section_name(system))


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


# AutoHotkey key names (RocketLauncher's AHK keymapper) -> LEDBlinky / MAME names.
_AHK_NAMES = {
    "enter": "ENTER", "return": "ENTER", "space": "SPACE", "esc": "ESC", "escape": "ESC",
    "tab": "TAB", "backspace": "BACKSPACE", "bs": "BACKSPACE",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    "ctrl": "LCONTROL", "control": "LCONTROL", "lctrl": "LCONTROL", "lcontrol": "LCONTROL",
    "rctrl": "RCONTROL", "rcontrol": "RCONTROL", "alt": "LALT", "lalt": "LALT", "ralt": "RALT",
    "shift": "LSHIFT", "lshift": "LSHIFT", "rshift": "RSHIFT", "numpadenter": "ENTER_PAD",
    "/": "SLASH", "-": "MINUS", "=": "EQUALS", ",": "COMMA", ".": "STOP",
}


def key_from_ahk(name: str) -> Optional[str]:
    """``r`` / ``Enter`` / ``Numpad1`` / ``F2`` -> key code; None if not a known key."""
    n = name.lower()
    if re.fullmatch(r"[a-z0-9]", n):
        return _kc(n.upper())
    m = re.fullmatch(r"numpad(\d)", n)
    if m:
        return _kc(m.group(1) + "_PAD")
    if re.fullmatch(r"f\d{1,2}", n):
        return _kc(n.upper())
    return _kc(_AHK_NAMES[n]) if n in _AHK_NAMES else None


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
    #: Actions lit as Start / Coin / Select, besides the ones named so.
    system_actions: set[str] = field(default_factory=set)

    def get(self, player: int, action: str) -> list[str]:
        return self.keys.get((player, action), [])

    def remapped(self, remap: KeyRemap) -> Keymap:
        """The same actions, keyed by the panel keys that reach them through *remap*."""
        km = Keymap(source=f"{self.source} + AHK {remap.source}", labels=dict(self.labels),
                    verified=self.verified, system_actions=set(self.system_actions))
        for slot, keys in self.keys.items():
            out: list[str] = []
            for k in keys:
                for p in remap.panel_keys(k):
                    if p not in out:
                        out.append(p)
            km.keys[slot] = out
        return km


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
    return read_windows_text(path).replace("\r\n", "\n").replace("\r", "\n")


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
        self._cfgs: dict[Path, dict[str, str]] = {}
        base = folder / "retroarch.cfg"
        self.base = self._cfg(base) if base.is_file() else {}
        self.game_cfgs: dict[str, Path] = {}
        cfg_dir = folder / "config"
        if cfg_dir.is_dir():
            for core in cfg_dir.iterdir():
                if core.is_dir():
                    for f in core.glob("*.cfg"):
                        self.game_cfgs.setdefault(f.stem.lower(), f)

    def _cfg(self, path: Path) -> dict[str, str]:
        if path not in self._cfgs:
            self._cfgs[path] = _read_ra_cfg(path)
        return self._cfgs[path]

    def keymap(self, system: str, game: Optional[str] = None) -> Optional[Keymap]:
        sys_cfg = _ci_file(self.folder / "config", f"{system}.cfg")
        if sys_cfg is None:
            return None
        merged = dict(self.base)
        merged.update(self._cfg(sys_cfg))
        source = f"RetroArch {self.folder.name}\\config\\{sys_cfg.name}"
        if game:
            override = self.game_cfgs.get(game.lower())
            if override is None:
                return None
            game_cfg = self._cfg(override)
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
               "START": "Start", "COIN": "Select", "SELECT": "Select"}

#: A keypad or keyboard port's other key, which names it (``KEYCODE_9PAD OR KEYCODE_R``: "9").
_KEYPAD_NAMES = {**{f"KEYCODE_{d}{pad}": str(d) for d in range(10) for pad in ("PAD", "_PAD", "")},
                 "KEYCODE_ASTERISK": "*", "KEYCODE_ENTERPAD": "Enter", "KEYCODE_ENTER_PAD": "Enter"}


def _mame_console_ports(path: Path) -> list[tuple[str, int, str, list[str]]]:
    """A console driver's Start / Select, keypad and keyboard ports, in file order.

    ``(kind, player, id, keys)``: kind ``START`` / ``SELECT`` (``P1_START``,
    ``P2_SELECT``: *player* from the type) or ``KEYPAD`` / ``KEYBOARD`` /
    ``OTHER`` (a console's own switch, such as Option; player 0: the type
    doesn't say; *id* is the port's tag and mask).
    """
    out: list[tuple[str, int, str, list[str]]] = []
    if not path.is_file() or path.stat().st_size == 0:
        return out
    try:
        root = ET.fromstring(_read_text(path))
    except ET.ParseError:
        return out
    for port in root.iter("port"):
        t = port.get("type") or ""
        seq = port.find("newseq[@type='standard']")
        if seq is None or not (seq.text or "").strip():
            continue
        keys = keys_from_mame_seq(seq.text.strip())
        m = re.fullmatch(r"P(\d)_(START|SELECT)", t)
        if m:
            out.append((m.group(2), int(m.group(1)), "", keys))
        elif t in ("KEYPAD", "KEYBOARD", "OTHER"):
            out.append((t, 0, f"{port.get('tag') or ''}/{port.get('mask') or ''}", keys))
    return out


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
    """Keymaps from a MAME-family folder: ctrlr file, cfg/default.cfg, cfg/<game>.cfg.

    Only ports one of those files remaps count. A port left on MAME's built-in
    key (P2 Button 1 = A, P2 Button 4 = W, ...) was never set up for the panel,
    and lighting it would light whichever button happens to send that letter.
    """

    def __init__(self, folder: Path, exe: str):
        self.folder = folder
        self.base: dict[str, list[str]] = {}
        ctrlr = ""
        ini = folder / (Path(exe).stem.replace("64", "") + ".ini")
        for cand in (ini, folder / "mame.ini", folder / "hbmame.ini", folder / "mess.ini"):
            if cand.is_file():
                # [ \t], not \s: a blank "ctrlr" line must not run on into the next one.
                m = re.search(r"^ctrlr[ \t]+(\S[^\r\n]*?)[ \t]*$", _read_text(cand), re.M)
                ctrlr = m.group(1) if m else ""
                break
        if ctrlr and ctrlr.lower() != "none":
            self.base.update(_mame_cfg_ports(folder / "ctrlr" / f"{ctrlr}.cfg"))
        self.base.update(_mame_cfg_ports(folder / "cfg" / "default.cfg"))
        self._cache: dict[str, Keymap] = {}

    def driver_keymap(self, driver: str, panel: Optional[dict[str, str]] = None) -> Optional[Keymap]:
        """Keys a console driver's own cfg remaps — nothing inherited.

        A console driver has far fewer ports than MAME's defaults cover, and
        which ones it has isn't recorded outside the driver; the ports the
        cabinet remapped for it are the ones it uses.  Besides the buttons:
        Start / Select (``P1_START``, ``P1_SELECT``), and every keypad,
        keyboard or other key on *panel*, named by the port's other key
        ("Keypad 9") and given to the player whose side of *panel* it is on.
        """
        cfg = self.folder / "cfg" / f"{driver}.cfg"
        ports = _mame_cfg_ports(cfg)
        console = _mame_console_ports(cfg)
        if not ports and not console:
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
        panel = panel or {}
        for kind, player, ident, keys in console:
            if player:
                for k in keys:
                    _add_key(km, (player, kind), k)
                continue
            name = next((_KEYPAD_NAMES[k] for k in keys if k in _KEYPAD_NAMES and k not in panel), "")
            label = {"KEYPAD": "Keypad", "KEYBOARD": "Key"}.get(kind, "Other") + (f" {name}" if name else "")
            for k in keys:
                # Only a player's buttons: the admin keys (Pause, Exit) light anyway.
                if panel and not panel.get(k, "").upper().startswith(("P1", "P2")):
                    continue
                act = f"{kind}:{ident}"
                km.labels[act] = label
                _add_key(km, (2 if panel.get(k, "").upper().startswith("P2") else 1, act), k)
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


# melonDS 1.x keeps its binds in melonDS.toml as Qt key codes: letters and
# digits are their ASCII capitals, other keys 0x010000xx.  melonDS adds the
# modifiers held while binding and Qt's keypad flag, and sets bit 31 for a
# right-hand Shift / Control / Alt.
_QT_KEYS = {
    0x01000000: "ESC", 0x01000001: "TAB", 0x01000003: "BACKSPACE", 0x01000004: "ENTER",
    0x01000005: "ENTERPAD", 0x01000006: "INSERT", 0x01000007: "DEL",
    0x01000010: "HOME", 0x01000011: "END", 0x01000012: "LEFT", 0x01000013: "UP",
    0x01000014: "RIGHT", 0x01000015: "DOWN", 0x01000016: "PGUP", 0x01000017: "PGDN",
    0x01000020: "LSHIFT", 0x01000021: "LCONTROL", 0x01000023: "LALT",
    0x20: "SPACE", 0x2C: "COMMA", 0x2D: "MINUS", 0x2E: "STOP", 0x2F: "SLASH", 0x3D: "EQUALS",
}
_QT_KEYPAD_KEYS = {**{0x30 + d: f"{d}PAD" for d in range(10)}, 0x01000005: "ENTERPAD",
                   0x2B: "PLUSPAD", 0x2D: "MINUSPAD", 0x2A: "ASTERISK", 0x2F: "SLASHPAD"}
_QT_RIGHT = {"LSHIFT": "RSHIFT", "LCONTROL": "RCONTROL", "LALT": "RALT"}
_QT_RIGHT_BIT = 0x80000000
_QT_CHORD = 0x1E000000      # Shift / Control / Alt / Meta held with the key
_QT_KEYPAD = 0x20000000
_QT_GROUP_SWITCH = 0x40000000


def key_from_qt(code: int) -> Optional[str]:
    """A Qt key code as melonDS saves it -> key code; None if unbound (-1) or a chord."""
    if code == -1:
        return None
    code &= 0xFFFFFFFF
    right = bool(code & _QT_RIGHT_BIT)
    code &= ~(_QT_RIGHT_BIT | _QT_GROUP_SWITCH)
    if code & _QT_CHORD:
        return None     # one panel button can't press it
    if code & _QT_KEYPAD:
        name = _QT_KEYPAD_KEYS.get(code & ~_QT_KEYPAD)
        return _kc(name) if name else None
    if 0x41 <= code <= 0x5A or 0x30 <= code <= 0x39:
        return _kc(chr(code))
    if 0x01000030 <= code <= 0x0100003B:
        return _kc(f"F{code - 0x0100002F}")
    name = _QT_KEYS.get(code)
    if name and right:
        name = _QT_RIGHT.get(name, name)
    return _kc(name) if name else None


_TOML_TABLE_RE = re.compile(r"\[\s*([A-Za-z0-9_\-]+(?:\s*\.\s*[A-Za-z0-9_\-]+)*)\s*\]\s*(?:#.*)?$")
_TOML_KEY_RE = re.compile(r"([A-Za-z0-9_\-]+(?:\s*\.\s*[A-Za-z0-9_\-]+)*)\s*=\s*(.*)$")


def _toml_table(path: Path, table: str) -> dict[str, str]:
    """``key -> raw value`` for one TOML table (Python 3.8 has no ``tomllib``).

    Enough TOML for the files melonDS writes: ``[a.b]`` headers, bare and
    dotted keys in any order, comments.  Names match exactly, as melonDS reads
    them.  A ``[[array]]`` header ends the table.  The lines of a multi-line
    list of strings (melonDS's recent games) start with a quote, so they never
    read as keys.
    """
    want = [p.strip() for p in table.split(".")]
    out: dict[str, str] = {}
    cur: Optional[list[str]] = []
    for line in _read_text(path).splitlines():
        s = line.strip()
        if s.startswith("[["):
            cur = None
            continue
        m = _TOML_TABLE_RE.match(s)
        if m:
            cur = [p.strip() for p in m.group(1).split(".")]
            continue
        m = _TOML_KEY_RE.match(s)
        if m and cur is not None:
            parts = [p.strip() for p in m.group(1).split(".")]
            if cur + parts[:-1] == want:
                out[parts[-1]] = m.group(2).strip()
    return out


#: melonDS's DS buttons, then the hotkeys a game can need (blowing into the
#: microphone, closing the lid); unbound ones light nothing.
_MELONDS_LABELS = {
    "Y": "Button Y", "X": "Button X", "L": "L Button", "B": "Button B",
    "A": "Button A", "R": "R Button", "Start": "Start", "Select": "Select",
    "HK_Mic": "Microphone", "HK_Lid": "Lid"}


def melonds_keymap(folder: Path) -> Optional[Keymap]:
    """melonDS 1.x: the first instance's keyboard binds in ``melonDS.toml``."""
    toml = _ci_file(folder, "melonDS.toml")
    if toml is None:
        return None
    binds = _toml_table(toml, "Instance0.Keyboard")
    if not binds:
        return None
    km = Keymap(source="melonDS melonDS.toml", labels=dict(_MELONDS_LABELS))
    for act in km.labels:
        m = re.match(r"[+-]?\d+(?![\d.xXoObBeE_])", binds.get(act, ""))
        k = key_from_qt(int(m.group(0))) if m else None
        if k:
            km.keys[(1, act)] = [k]
    return km


# Flycast ----------------------------------------------------------------------

_SDL_NAMED = {40: "ENTER", 41: "ESC", 42: "BACKSPACE", 43: "TAB", 44: "SPACE", 45: "MINUS",
              46: "EQUALS", 54: "COMMA", 55: "STOP", 56: "SLASH", 79: "RIGHT", 80: "LEFT",
              81: "DOWN", 82: "UP", 88: "ENTER_PAD", 224: "LCONTROL", 225: "LSHIFT",
              226: "LALT", 228: "RCONTROL", 229: "RSHIFT", 230: "RALT"}


def key_from_sdl_scancode(code: int) -> Optional[str]:
    """SDL scancodes (Flycast's keyboard binds): 4-29 A-Z, 30-39 1-0, 58-69 F1-F12."""
    if 4 <= code <= 29:
        return _kc(chr(ord("A") + code - 4))
    if 30 <= code <= 39:
        return _kc(str((code - 29) % 10))
    if 58 <= code <= 69:
        return _kc(f"F{code - 57}")
    if 89 <= code <= 98:
        return _kc(f"{(code - 88) % 10}_PAD")
    return _kc(_SDL_NAMED[code]) if code in _SDL_NAMED else None


#: Flycast's Dreamcast pad actions -> (action, button name).
_FLYCAST_DC = {"btn_a": ("A", "Button A"), "btn_b": ("B", "Button B"), "btn_x": ("X", "Button X"),
               "btn_y": ("Y", "Button Y"), "btn_c": ("C", "Button C"), "btn_z": ("Z", "Button Z"),
               "btn_trigger_left": ("L", "L Trigger"), "btn_trigger_right": ("R", "R Trigger"),
               "btn_d": ("D", "Button D"), "btn_start": ("Start", "Start")}
#: The same actions on Naomi / Atomiswave boards: buttons 1-8, Start, Coin.
_FLYCAST_ARCADE = {"btn_a": "BUTTON1", "btn_b": "BUTTON2", "btn_c": "BUTTON3", "btn_x": "BUTTON4",
                   "btn_y": "BUTTON5", "btn_z": "BUTTON6", "btn_dpad2_left": "BUTTON7",
                   "btn_dpad2_right": "BUTTON8", "btn_start": "START", "btn_d": "COIN"}
#: Characters Flycast writes as "-" when it names a key file after a game.
_FLYCAST_ID_CHARS = re.compile(r'[/\\:?*|"<>]')


def is_flycast_arcade(system: str) -> bool:
    """Wheels Flycast runs as arcade boards, which read the ``_arcade`` key files."""
    low = system.lower()
    return "naomi" in low or "atomiswave" in low


def flycast_keymap(path: Path, arcade: bool) -> Optional[Keymap]:
    """One Flycast keyboard map (``mappings\\SDL_Keyboard*.cfg``).

    ``bindN = <SDL scancode>:<action>``; an action ending in ``1`` is port B
    (player 2), ``2`` / ``3`` ports C / D.  Dreamcast wheels get the pad's
    buttons; arcade boards Flycast's buttons 1-8, Start and Coin.
    """
    km = (Keymap(source=f"Flycast mappings\\{path.name}") if arcade else
          Keymap(source=f"Flycast mappings\\{path.name}", labels=dict(_FLYCAST_DC.values())))
    for line in _read_text(path).splitlines():
        m = re.fullmatch(r"\s*bind\d+\s*=\s*(\d+)\s*:\s*(\w+)\s*", line)
        if not m:
            continue
        action, player = m.group(2), 1
        if action[-1] in "123":
            action, player = action[:-1], int(action[-1]) + 1
        if player > 2:
            continue
        act = _FLYCAST_ARCADE.get(action) if arcade else _FLYCAST_DC.get(action, ("", ""))[0]
        key = key_from_sdl_scancode(int(m.group(1)))
        if act and key:
            keys = km.keys.setdefault((player, act), [])
            if key not in keys:
                keys.append(key)
    return km


def flycast_key_file(files: dict[str, Path], arcade: bool, game_id: str = "") -> Optional[Path]:
    """The keyboard map Flycast loads, from *files* (lower-cased name -> file in ``mappings``).

    A Dreamcast game: ``SDL_Keyboard_<ID>.cfg``, then ``SDL_Keyboard.cfg``.  An
    arcade game: ``SDL_Keyboard_<ID>_arcade.cfg``, then ``SDL_Keyboard_arcade.cfg``,
    then the two Dreamcast names.
    """
    gid = _FLYCAST_ID_CHARS.sub("-", game_id)
    names = [f"SDL_Keyboard_{gid}.cfg", "SDL_Keyboard.cfg"] if gid else ["SDL_Keyboard.cfg"]
    if arcade:
        names = ([f"SDL_Keyboard_{gid}_arcade.cfg"] if gid else []) + ["SDL_Keyboard_arcade.cfg"] + names
    return next((files[n.lower()] for n in names if n.lower() in files), None)


def naomi_boot_title(rom: Path) -> Optional[str]:
    """The title in a Naomi cartridge's ROM header, which Flycast takes as its game ID.

    The first ROM of the cartridge starts ``NAOMI`` (``Naomi2`` on Naomi 2)
    and holds the title at 0x30, 32 bytes padded with spaces.  None for
    GD-ROM sets, encrypted cartridges and Atomiswave sets, which don't show it.
    """
    try:
        with zipfile.ZipFile(rom) as z:
            names = sorted(z.namelist(), key=lambda n: not n.lower().endswith((".ic22", ".ic11")))
            for name in names:
                with z.open(name) as f:
                    head = f.read(0x50)
                if head[:16].rstrip(b" ") in (b"NAOMI", b"Naomi2") and len(head) == 0x50:
                    title = head[0x30:0x50]
                    # A blank title (0xFF) means Flycast reads one further on: not matched here.
                    return title.decode("latin-1").rstrip() if title.strip(b" \x00\xff") else None
    except (OSError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
        return None
    return None


# Sony emulators: PPSSPP, DuckStation, PCSX2 2.x, Vita3K ------------------------

# Android key codes, which PPSSPP uses for every device.
_ANDROID_NAMED = {19: "UP", 20: "DOWN", 21: "LEFT", 22: "RIGHT", 55: "COMMA", 56: "STOP",
                  57: "LALT", 58: "RALT", 59: "LSHIFT", 60: "RSHIFT", 61: "TAB", 62: "SPACE",
                  66: "ENTER", 67: "BACKSPACE", 69: "MINUS", 70: "EQUALS", 76: "SLASH",
                  111: "ESC", 113: "LCONTROL", 114: "RCONTROL", 160: "ENTER_PAD"}


def key_from_android(code: int) -> Optional[str]:
    """Android key codes (PPSSPP): 7-16 0-9, 29-54 A-Z, 131-142 F1-F12, 144-153 keypad."""
    if 29 <= code <= 54:
        return _kc(chr(ord("A") + code - 29))
    if 7 <= code <= 16:
        return _kc(str(code - 7))
    if 131 <= code <= 142:
        return _kc(f"F{code - 130}")
    if 144 <= code <= 153:
        return _kc(f"{code - 144}_PAD")
    return _kc(_ANDROID_NAMED[code]) if code in _ANDROID_NAMED else None


#: The PSP's buttons, as PPSSPP names them in ``[ControlMapping]``.
_PSP_LABELS = {"Square": "Square", "Triangle": "Triangle", "L": "L Button", "Cross": "Cross",
               "Circle": "Circle", "R": "R Button", "Start": "Start", "Select": "Select"}
_PPSSPP_KEYBOARD = 1      # PPSSPP's DEVICE_ID_KEYBOARD


def ppsspp_keymap(folder: Path) -> Optional[Keymap]:
    """PPSSPP: the keyboard binds in ``memstick\\PSP\\SYSTEM\\controls.ini`` (portable install).

    ``Cross = 1-32,10-189``: each bind is ``<device>-<Android key code>``,
    device 1 the keyboard.  ``1-29:1-30`` is a key combination, which one
    panel button can't press.  Hotkeys (fast-forward, save states) aren't lit.
    """
    ini = folder / "memstick" / "PSP" / "SYSTEM" / "controls.ini"
    if not ini.is_file():
        return None
    km = Keymap(source="PPSSPP controls.ini", labels=dict(_PSP_LABELS))
    section = ""
    for line in _read_text(ini).splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[(.+)\]", s)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = re.fullmatch(r"([^=]+?)\s*=\s*(.*)", s)
        if section != "controlmapping" or not m or m.group(1) not in km.labels:
            continue
        keys: list[str] = []
        for bind in m.group(2).split(","):
            b = re.fullmatch(r"\s*(\d+)-(\d+)\s*", bind)
            k = key_from_android(int(b.group(2))) if b and int(b.group(1)) == _PPSSPP_KEYBOARD else None
            if k and k not in keys:
                keys.append(k)
        if keys:
            km.keys[(1, m.group(1))] = keys
    return km


#: ``Keyboard/<name>`` names DuckStation and PCSX2 2.x write for keys other than letters and digits.
_KEYBOARD_NAMES = {"return": "ENTER", "enter": "ENTER", "space": "SPACE", "escape": "ESC",
                   "tab": "TAB", "backspace": "BACKSPACE", "up": "UP", "down": "DOWN",
                   "left": "LEFT", "right": "RIGHT", "shift": "LSHIFT", "control": "LCONTROL",
                   "alt": "LALT", "comma": "COMMA", "period": "STOP", "slash": "SLASH",
                   "minus": "MINUS", "equal": "EQUALS"}


def key_from_keyboard_name(name: str) -> Optional[str]:
    """A ``Keyboard/<name>`` bind (DuckStation, PCSX2 2.x): ``A``, ``1``, ``F2``, ``Return``."""
    n = name.strip()
    low = n.lower()
    if re.fullmatch(r"[a-z0-9]", low) or re.fullmatch(r"f\d{1,2}", low):
        return _kc(n.upper())
    m = re.fullmatch(r"(?:numpad|keypad)(\d)", low)
    if m:
        return _kc(m.group(1) + "_PAD")
    return _kc(_KEYBOARD_NAMES[low]) if low in _KEYBOARD_NAMES else None


#: PlayStation pad buttons, as DuckStation and PCSX2 name them in ``[Pad1]`` / ``[Pad2]``.
_PS_PAD_LABELS = {"Square": "Square", "Triangle": "Triangle", "L1": "L1", "L2": "L2",
                  "Cross": "Cross", "Circle": "Circle", "R1": "R1", "R2": "R2",
                  "L3": "L3", "R3": "R3", "Start": "Start", "Select": "Select", "Analog": "Analog"}


def pad_ini_keymap(ini: Path, source: str) -> Optional[Keymap]:
    """The ``[Pad1]`` / ``[Pad2]`` keyboard binds of a DuckStation or PCSX2 2.x settings file.

    A bind is a line ``Cross = Keyboard/D``.  A name comes once per device
    (``Cross = SDL-0/A`` on the next line), and ``Keyboard/A & Keyboard/B``
    is a key combination, which one panel button can't press.  A pad whose
    ``Type`` is ``None`` is unplugged.  None when the file has no pad section.
    """
    km = Keymap(source=source, labels=dict(_PS_PAD_LABELS))
    player, found, unplugged = 0, False, set()
    for line in _read_text(ini).splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[(.+)\]", s)
        if m:
            pm = re.fullmatch(r"pad([12])", m.group(1).strip().lower())
            player = int(pm.group(1)) if pm else 0
            found |= bool(pm)
            continue
        m = re.fullmatch(r"(\w+)\s*=\s*(.*)", s)
        if not player or not m:
            continue
        name, value = m.group(1), m.group(2).strip()
        if name.lower() == "type" and value.lower() == "none":
            unplugged.add(player)
        if name not in km.labels or "&" in value or not value.lower().startswith("keyboard/"):
            continue
        k = key_from_keyboard_name(value.split("/", 1)[1])
        keys = km.keys.setdefault((player, name), [])
        if k and k not in keys:
            keys.append(k)
    if not found:
        return None
    km.keys = {slot: keys for slot, keys in km.keys.items() if keys and slot[0] not in unplugged}
    return km


def duckstation_keymap(folder: Path) -> Optional[Keymap]:
    """DuckStation (portable): ``settings.ini`` beside the exe."""
    ini = _ci_file(folder, "settings.ini")
    return pad_ini_keymap(ini, "DuckStation settings.ini") if ini else None


def pcsx2_keymap(folder: Path) -> Optional[Keymap]:
    """PCSX2 2.x (portable): ``inis\\PCSX2.ini``.  1.x keeps its keys elsewhere and isn't read."""
    ini = _ci_file(folder / "inis", "PCSX2.ini")
    return pad_ini_keymap(ini, "PCSX2 inis\\PCSX2.ini") if ini else None


#: Vita buttons, as Vita3K's ``config.yml`` names them (``keyboard-button-<name>``).
_VITA_LABELS = {"square": "Square", "triangle": "Triangle", "l1": "L Button", "l2": "L2",
                "l3": "L3", "cross": "Cross", "circle": "Circle", "r1": "R Button", "r2": "R2",
                "r3": "R3", "start": "Start", "select": "Select", "psbutton": "PS Button",
                "up": "D-pad Up", "down": "D-pad Down", "left": "D-pad Left", "right": "D-pad Right"}
_WEB_KEY_NAMES = {"enter": "ENTER", "numpadenter": "ENTER_PAD", "space": "SPACE", "escape": "ESC",
                  "tab": "TAB", "backspace": "BACKSPACE", "arrowup": "UP", "arrowdown": "DOWN",
                  "arrowleft": "LEFT", "arrowright": "RIGHT", "shiftleft": "LSHIFT",
                  "shiftright": "RSHIFT", "controlleft": "LCONTROL", "controlright": "RCONTROL",
                  "altleft": "LALT", "altright": "RALT", "comma": "COMMA", "period": "STOP",
                  "slash": "SLASH", "minus": "MINUS", "equal": "EQUALS"}


def key_from_vita3k(value: str) -> Optional[str]:
    """A Vita3K key: a name (``KeyA``, ``Digit1``, ``Numpad1``, ``F2``, ``Enter``) or an SDL scancode."""
    v = value.strip().strip("'\"")
    if re.fullmatch(r"\d+", v):
        return key_from_sdl_scancode(int(v))     # older Vita3K builds save scancodes
    m = re.fullmatch(r"(?:Key([A-Za-z])|Digit(\d))", v)
    if m:
        return _kc((m.group(1) or m.group(2)).upper())
    m = re.fullmatch(r"Numpad(\d)", v)
    if m:
        return _kc(m.group(1) + "_PAD")
    if re.fullmatch(r"[Ff]\d{1,2}", v):
        return _kc(v.upper())
    return _kc(_WEB_KEY_NAMES[v.lower()]) if v.lower() in _WEB_KEY_NAMES else None


def vita3k_keymap(folder: Path) -> Optional[Keymap]:
    """Vita3K: ``keyboard-button-<button>[-alt]: <key>`` in ``portable\\config.yml`` or ``config.yml``."""
    cfg = _ci_file(folder / "portable", "config.yml") or _ci_file(folder, "config.yml")
    if cfg is None:
        return None
    where = "portable\\config.yml" if cfg.parent != folder else "config.yml"
    km = Keymap(source=f"Vita3K {where}", labels=dict(_VITA_LABELS))
    for line in _read_text(cfg).splitlines():
        m = re.fullmatch(r"keyboard-button-([a-z0-9]+?)(?:-alt)?\s*:\s*(\S+)\s*(?:#.*)?", line.strip())
        k = key_from_vita3k(m.group(2)) if m and m.group(1) in km.labels else None
        if k:
            keys = km.keys.setdefault((1, m.group(1)), [])
            if k not in keys:
                keys.append(k)
    return km


def _ci_path(folder: Path, *parts: str) -> Optional[Path]:
    """``folder / parts...`` with each part matched in any case (Windows names); None if missing."""
    cur = folder
    for part in parts:
        nxt = cur / part
        if not nxt.exists():
            low = part.lower()
            nxt = next((q for q in cur.iterdir() if q.name.lower() == low), None) if cur.is_dir() else None
            if nxt is None:
                return None
        cur = nxt
    return cur


def _add_key(km: Keymap, slot: tuple[int, str], key: Optional[str]) -> None:
    if key:
        keys = km.keys.setdefault(slot, [])
        if key not in keys:
            keys.append(key)


# EKA2L1 (Nokia N-Gage, Symbian phones) -----------------------------------------

#: Symbian key codes EKA2L1 binds keys to (``target``), with the phone's names.
_SYMBIAN_KEYS = {**{48 + d: f"Key {d}" for d in range(10)}, 42: "Key *", 127: "Key #",
                 164: "Left soft key", 165: "Right soft key", 167: "OK", 180: "Call key",
                 181: "End key", 14: "Left", 15: "Right", 16: "Up", 17: "Down"}


def eka2l1_keymap(folder: Path) -> Optional[Keymap]:
    """EKA2L1: the keyboard binds of its current profile, ``bindings\\<profile>.yml``.

    The profile is ``current-keybind-profile`` in ``config.yml`` (``default``).
    Each bind is a list entry: ``source`` (``type: key``, ``data: keycode:``
    a Qt key code) and ``target``, a Symbian key code.  Controller binds
    (``type: controller``) light nothing.
    """
    profile = "default"
    cfg = _ci_file(folder, "config.yml")
    if cfg is not None:
        m = re.search(r"^current-keybind-profile:\s*['\"]?([^'\"\r\n#]+?)['\"]?\s*$", _read_text(cfg), re.M)
        profile = m.group(1) if m else profile
    yml = _ci_path(folder, "bindings", f"{profile}.yml")
    if yml is None or not yml.is_file():
        return None
    km = Keymap(source=f"EKA2L1 bindings\\{yml.name}",
                labels={str(t): name for t, name in _SYMBIAN_KEYS.items()},
                system_actions={"164", "165", "180", "181"})
    kind = code = None
    for line in _read_text(yml).splitlines():
        s = line.strip()
        if s.startswith("- "):
            kind = code = None
            s = s[2:].strip()
        m = re.fullmatch(r"(type|keycode|target):\s*['\"]?(-?\w+)['\"]?", s)
        if not m:
            continue
        if m.group(1) == "type":
            kind = m.group(2).lower()
        elif m.group(1) == "keycode" and m.group(2).lstrip("-").isdigit():
            code = int(m.group(2))
        elif m.group(1) == "target" and kind == "key" and code is not None and m.group(2).isdigit():
            if int(m.group(2)) in _SYMBIAN_KEYS:
                _add_key(km, (1, m.group(2)), key_from_qt(code))
    return km


# Cxbx-Reloaded (Xbox) ------------------------------------------------------------

#: An Xbox pad's buttons, as Cxbx-R names them in ``settings.ini``.
_XBOX_LABELS = {"X": "X", "Y": "Y", "Black": "Black", "L Trigger": "Left Trigger",
                "A": "A", "B": "B", "White": "White", "R Trigger": "Right Trigger",
                "L Thumb": "Left Thumb", "R Thumb": "Right Thumb", "Start": "Start", "Back": "Back",
                "D Pad Up": "D-pad Up", "D Pad Down": "D-pad Down",
                "D Pad Left": "D-pad Left", "D Pad Right": "D-pad Right"}
_DINPUT_NAMES = {"return": "ENTER", "space": "SPACE", "escape": "ESC", "tab": "TAB", "back": "BACKSPACE",
                 "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT", "lshift": "LSHIFT",
                 "rshift": "RSHIFT", "lcontrol": "LCONTROL", "rcontrol": "RCONTROL", "lmenu": "LALT",
                 "rmenu": "RALT", "numpadenter": "ENTER_PAD", "comma": "COMMA", "period": "STOP",
                 "slash": "SLASH", "minus": "MINUS", "equals": "EQUALS"}


def key_from_dinput_name(name: str) -> Optional[str]:
    """A DirectInput key name as Cxbx-R saves it: ``A``, ``1``, ``F2``, ``RETURN``, ``NUMPAD1``."""
    low = name.strip().lower()
    if re.fullmatch(r"[a-z0-9]", low) or re.fullmatch(r"f\d{1,2}", low):
        return _kc(low.upper())
    m = re.fullmatch(r"numpad(\d)", low)
    if m:
        return _kc(m.group(1) + "_PAD")
    return _kc(_DINPUT_NAMES[low]) if low in _DINPUT_NAMES else None


def cxbxr_keymap(folder: Path) -> Optional[Keymap]:
    """Cxbx-R: the keyboard input profiles in ``settings.ini`` beside the exe.

    Player *n* uses the profile ``[input-port-<n-1>]`` names when that is a
    keyboard profile (``DeviceName = DInput/0/KeyboardMouse``).  A port set
    to a pad's profile takes the next keyboard profile instead, in file
    order: the one a cabinet switches to when no pad is on.
    """
    ini = _ci_file(folder, "settings.ini")
    if ini is None:
        return None
    sections = _read_ini_loose(ini)
    profiles: dict[str, dict[str, str]] = {}
    for name, keys in sections.items():
        if re.fullmatch(r"input-profile-\d+", name.lower()):
            pname = keys.get("ProfileName", "").strip().strip('"')
            profiles.setdefault(pname, keys)
    keyboard = [p for p, keys in profiles.items() if "keyboard" in keys.get("DeviceName", "").lower()]
    if not keyboard:
        return None
    km = Keymap(source="Cxbx-R settings.ini", labels=dict(_XBOX_LABELS), system_actions={"Back"})
    used: list[str] = []
    for player in (1, 2):
        port = sections.get(f"input-port-{player - 1}", {}).get("ProfileName", "").strip().strip('"')
        pick = port if port in keyboard and port not in used else next((p for p in keyboard if p not in used), None)
        if pick is None:
            break
        used.append(pick)
        for button in _XBOX_LABELS:
            _add_key(km, (player, button), key_from_dinput_name(profiles[pick].get(button, "")))
    km.source += " (" + ", ".join(used) + ")"
    return km


# WinUAE (Amiga, CD32, CDTV) ------------------------------------------------------

#: WinUAE's joystick events (``JOY2_`` is the joystick port, player 1; ``JOY1_`` player 2).
_UAE_EVENTS = {"FIRE_BUTTON": "Fire", "2ND_BUTTON": "2nd Button", "3RD_BUTTON": "3rd Button",
               "CD32_RED": "Red", "CD32_BLUE": "Blue", "CD32_GREEN": "Green", "CD32_YELLOW": "Yellow",
               "CD32_RWD": "Reverse", "CD32_FFW": "Forward", "CD32_PLAY": "Play"}


def winuae_host_config(folder: Path, system: str) -> Optional[Path]:
    """The host config RocketLauncher's WinUAE module starts a wheel's games with.

    ``Configurations\\host\\cd32host.uae`` (CD32), ``cdtvhost.uae`` (CDTV),
    ``amigacdhost.uae`` (Amiga CD) or ``amigahost.uae``.  A game with its own
    ``Configurations\\<game>.uae`` starts with that instead.
    """
    low = system.lower()
    host = ("cd32host.uae" if "cd32" in low else "cdtvhost.uae" if "cdtv" in low
            else "amigacdhost.uae" if "amiga cd" in low else "amigahost.uae")
    return _ci_path(folder, "Configurations", "host", host)


def winuae_keymap(path: Path) -> Keymap:
    """The keyboard binds of a WinUAE config: ``input.<n>.keyboard.<k>.button.<DIK>.<KEY>=<event>``.

    The set read is ``input.config``'s (0, Game Ports, keeps custom binds in
    set 4).  Events ``JOY2_*`` are the joystick port (player 1), ``JOY1_*``
    the mouse port (player 2); ``EVENT.<flags>.<slot>`` may repeat, comma-separated.
    """
    text = _read_text(path)
    m = re.search(r"^input\.config\s*=\s*(\d+)", text, re.M)
    want = "4" if not m or m.group(1) == "0" else m.group(1)
    km = Keymap(source=f"WinUAE {path.name}", labels=dict(_UAE_EVENTS), system_actions={"CD32_PLAY"})
    for line in text.splitlines():
        b = re.fullmatch(r"input\.(\d+)\.keyboard\.\d+\.button\.(\d+)\.[^=]*=(.*)", line.strip())
        if not b or b.group(1) != want:
            continue
        for event in b.group(3).split(","):
            e = re.match(r"JOY([12])_(\w+?)(?:\.|$)", event.strip())
            if e and e.group(2) in _UAE_EVENTS:
                _add_key(km, (2 if e.group(1) == "1" else 1, e.group(2)), key_from_dik(int(b.group(2))))
    return km


# BigPEmu (Atari Jaguar) -----------------------------------------------------------

#: BigPEmu's Jaguar pad inputs, by their place in a device's ``Bindings`` list.
_JAGUAR_INPUTS = ["C", "B", "A", "Pause", "Option", "Up", "Down", "Left", "Right",
                  *[f"Keypad {d}" for d in range(10)], "Keypad *", "Keypad #"]
_JAGUAR_LABELS = {**{n: f"Button {n}" for n in "ABC"}, "Pause": "Pause", "Option": "Option",
                  **{n: n for n in _JAGUAR_INPUTS[9:]}}


def bigpemu_keymap(folder: Path) -> Optional[Keymap]:
    """BigPEmu (``-localdata``): the keyboard triggers in ``UserData\\BigPEmuConfig.bigpcfg``.

    A JSON file; ``BigPEmuConfig.Input.Device0`` / ``Device1`` are players
    1 and 2, each a ``Bindings`` list in the Jaguar pad's input order (C, B,
    A, Pause, Option, the D-pad, keypad 0-9, *, #).  A trigger with
    ``B_KB: true`` is a keyboard key, ``B_ID`` its DirectInput scan code; one
    with a held modifier (``M_ID``) is a combination and isn't lit.  Only
    standard Jaguar pads (``DeviceType`` 0) are read.
    """
    import json

    cfg = _ci_path(folder, "UserData", "BigPEmuConfig.bigpcfg")
    if cfg is None or not cfg.is_file():
        return None
    try:
        data = json.loads(_read_text(cfg))
        devices = data["BigPEmuConfig"]["Input"]
    except (ValueError, KeyError, TypeError):
        return None
    labels = {name: _JAGUAR_LABELS[name] for name in ["A", "B", "C", "Pause", "Option"] + _JAGUAR_INPUTS[9:]}
    km = Keymap(source="BigPEmu BigPEmuConfig.bigpcfg", labels=labels, system_actions={"Pause"})
    for player in (1, 2):
        dev = devices.get(f"Device{player - 1}") if isinstance(devices, dict) else None
        if not isinstance(dev, dict) or dev.get("DeviceType", 0) != 0:
            continue
        for i, binding in enumerate(dev.get("Bindings") or []):
            if i >= len(_JAGUAR_INPUTS) or not isinstance(binding, dict):
                continue
            for t in binding.get("Triggers") or []:
                if isinstance(t, dict) and t.get("B_KB") is True and "M_ID" not in t \
                        and isinstance(t.get("B_ID"), int):
                    _add_key(km, (player, _JAGUAR_INPUTS[i]), key_from_dik(t["B_ID"]))
    return km


# SNESGT, Project64's N-Rage, Mugen: DirectInput scan codes ----------------------

_SNESGT_BUTTONS = {"Y": "Button Y", "X": "Button X", "L": "L Button", "B": "Button B",
                   "A": "Button A", "R": "R Button", "START": "Start", "SELECT": "Select"}


def snesgt_keymap(folder: Path) -> Optional[Keymap]:
    """SNESGT: ``[key_config]`` in ``SNESGT.ini``, ``1P_A=32`` (DirectInput scan codes, 0 unbound)."""
    ini = _ci_file(folder, "SNESGT.ini")
    if ini is None:
        return None
    km = Keymap(source="SNESGT SNESGT.ini", labels=dict(_SNESGT_BUTTONS))
    section = ""
    for line in _read_text(ini).splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[(.+)\]", s)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = re.fullmatch(r"([12])P_(\w+)\s*=\s*(\d+)", s, re.I)
        if section == "key_config" and m and m.group(2).upper() in _SNESGT_BUTTONS:
            _add_key(km, (int(m.group(1)), m.group(2).upper()), key_from_dik(int(m.group(3))))
    return km


#: N-Rage's N64 controller buttons, by the button number in its ``Button=`` lines.
_N64_BUTTONS = {0: "D-pad Right", 1: "D-pad Left", 2: "D-pad Down", 3: "D-pad Up", 4: "Start",
                5: "Z Trigger", 6: "Button B", 7: "Button A", 8: "C Right", 9: "C Left",
                10: "C Down", 11: "C Up", 12: "R Button", 13: "L Button"}
_NRAGE_KEY = 5      # N-Rage's DT_KEYBUTTON


def nrage_keymap(folder: Path) -> Optional[Keymap]:
    """Project64 with the N-Rage input plugin: ``Config\\NRage.ini`` ``[Controls]``.

    ``Button=<controller> <button> <DIK hex> <axis> <type>``: controller 0
    is player 1, type 5 a keyboard key.  Other input plugins aren't read.
    """
    ini = _ci_path(folder, "Config", "NRage.ini")
    if ini is None or not ini.is_file():
        return None
    km = Keymap(source="Project64 Config\\NRage.ini",
                labels={str(b): name for b, name in _N64_BUTTONS.items()})
    section = ""
    for line in _read_text(ini).splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[(.+)\]", s)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = re.fullmatch(r"Button\s*=\s*(\d+)\s+(\d+)\s+([0-9A-Fa-f]+)\s+\d+\s+(\d+)", s)
        if section != "controls" or not m or int(m.group(4)) != _NRAGE_KEY:
            continue
        player, button = int(m.group(1)) + 1, int(m.group(2))
        if player <= 2 and button in _N64_BUTTONS:
            _add_key(km, (player, str(button)), key_from_dik(int(m.group(3), 16)))
    return km


_MUGEN_BUTTONS = {"A": "Button A", "B": "Button B", "C": "Button C", "X": "Button X",
                  "Y": "Button Y", "Z": "Button Z", "Start": "Start"}


_SDL1_NAMED = {32: "SPACE", 27: "ESC", 9: "TAB", 8: "BACKSPACE", 273: "UP", 274: "DOWN",
               275: "RIGHT", 276: "LEFT", 271: "ENTER_PAD"}


def key_from_sdl1(code: int) -> Optional[str]:
    """SDL 1.2 key symbols (Mugen 1.x): ASCII letters and digits, Return, Space."""
    if 97 <= code <= 122 or 48 <= code <= 57 or code == 13:
        return key_from_ascii(code)
    if 256 <= code <= 265:
        return _kc(f"{code - 256}_PAD")
    if 282 <= code <= 293:
        return _kc(f"F{code - 281}")
    return _kc(_SDL1_NAMED[code]) if code in _SDL1_NAMED else None


def mugen_keymap_text(text: str, source: str) -> Optional[Keymap]:
    """``[P1 Keys]`` / ``[P2 Keys]`` of a ``data\\mugen.cfg``.

    WinMugen writes DirectInput scan codes, Mugen 1.x SDL key symbols; which
    one is told by ``Jump`` (the up arrow: 200 or 273).  Any other ``Jump``
    and the file isn't read.
    """
    keys: dict[tuple[int, str], int] = {}
    player = 0
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.split(";", 1)[0].strip()
        m = re.fullmatch(r"\[\s*P([12])\s+Keys\s*\]", s, re.I)
        if m or s.startswith("["):
            player = int(m.group(1)) if m else 0
            continue
        m = re.fullmatch(r"(\w+)\s*=\s*(-?\d+)", s)
        if player and m:
            keys[(player, m.group(1).lower())] = int(m.group(2))
    jump = keys.get((1, "jump"))
    decode = key_from_dik if jump == 200 else key_from_sdl1 if jump == 273 else None
    if decode is None:
        return None
    km = Keymap(source=source, labels=dict(_MUGEN_BUTTONS))
    for (player, name), code in keys.items():
        act = next((a for a in _MUGEN_BUTTONS if a.lower() == name), None)
        if act and code >= 0:
            _add_key(km, (player, act), decode(code))
    return km


def _read_7z_member(path: Path, member: str) -> Optional[bytes]:
    """One file from a 7z archive (``py7zr``, a soft dependency); None without it or on error."""
    try:
        import py7zr
    except ImportError:
        return None

    class _Sink:
        def __init__(self) -> None:
            self.data = bytearray()

        def write(self, b: bytes) -> int:
            self.data += b
            return len(b)

        def read(self, size: Optional[int] = None) -> bytes:
            return b""

        def seek(self, offset: int, whence: int = 0) -> int:
            return len(self.data)

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

        def size(self) -> int:
            return len(self.data)

    class _Factory:
        def __init__(self) -> None:
            self.sinks: dict[str, _Sink] = {}

        def create(self, filename: str) -> _Sink:
            return self.sinks.setdefault(filename, _Sink())

    try:
        with py7zr.SevenZipFile(path, mode="r") as z:
            name = next((n for n in z.getnames() if n.replace("\\", "/").lower() == member.lower()), None)
            if name is None:
                return None
            if hasattr(z, "read"):          # py7zr < 1.0
                buf = (z.read(targets=[name]) or {}).get(name)
                return buf.read() if buf is not None else None
            factory = _Factory()            # py7zr >= 1.0
            z.extract(targets=[name], factory=factory)
            sink = factory.sinks.get(name)
            return bytes(sink.data) if sink is not None else None
    except Exception:  # noqa: BLE001 — a damaged archive must not stop the run
        return None


#: ``data\\mugen.cfg`` texts read from ``.7z`` games, by archive, size and date:
#: reaching the file means decompressing the archive up to it (minutes for a
#: build of several GB), so each archive is read once until it changes.
MUGEN_CFG_CACHE = CONFIG_DIR / "ledblinky_mugen_cfg_cache.json"


def _cached_7z_member(rom: Path, member: str) -> Optional[bytes]:
    import json

    try:
        st = rom.stat()
    except OSError:
        return None
    try:
        cache = json.loads(MUGEN_CFG_CACHE.read_text(encoding="utf-8")) if MUGEN_CFG_CACHE.is_file() else {}
    except (OSError, ValueError):
        cache = {}
    key = f"{str(rom).lower()}|{member.lower()}"
    stamp = [st.st_size, st.st_mtime_ns]
    hit = cache.get(key) if isinstance(cache, dict) else None
    if isinstance(hit, dict) and hit.get("stamp") == stamp and isinstance(hit.get("text"), str):
        return hit["text"].encode("latin-1")
    data = _read_7z_member(rom, member)
    if data is not None:
        cache = cache if isinstance(cache, dict) else {}
        cache[key] = {"stamp": stamp, "text": data.decode("latin-1")}
        try:
            MUGEN_CFG_CACHE.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(MUGEN_CFG_CACHE, json.dumps(cache, indent=1).encode("utf-8"))
        except OSError:
            pass        # no cache: the next run reads the archive again
    return data


def mugen_game_cfg(rom: Path, member: str) -> Optional[str]:
    """``data\\mugen.cfg`` of one Mugen game: *member* in its folder, ``.zip`` or ``.7z``."""
    if rom.is_dir():
        cfg = _ci_path(rom.parent, *member.split("/"))
        return _read_text(cfg) if cfg is not None and cfg.is_file() else None
    data = None
    if rom.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(rom) as z:
                name = next((n for n in z.namelist() if n.replace("\\", "/").lower() == member.lower()), None)
                data = z.read(name) if name else None
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            data = None
    elif rom.suffix.lower() == ".7z":
        data = _cached_7z_member(rom, member)
    return data.decode("latin-1") if data is not None else None


_SSF_ORDER =("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "C", "X", "Y", "Z", "L", "R", "Start")


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
        # KEY_START1 = 114 49 0: two keyboard keys (R or 1), then a joystick button.
        m = re.match(r"(KEY_\w+)\s*=\s*(\d+)(?:\s+(\d+))?", line.strip())
        if m and m.group(1) in names:
            keys = [k for k in (key_from_ascii(int(c)) for c in m.group(2, 3) if c) if k]
            if keys:
                km.keys[names[m.group(1)]] = keys
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


def _ini_value(path: Path, section: str, key: str) -> Optional[str]:
    """One value from an RL ini, names matched in any case; None when it isn't there."""
    for sec, keys in _read_ini_loose(path).items():
        if sec.lower() == section.lower():
            for k, v in keys.items():
                if k.lower() == key.lower():
                    return v
    return None


@dataclass
class KeyRemap:
    """Plain one-key remaps (``r::1``) from an AHK keymapper profile."""

    source: str
    #: Key pressed on the panel -> key the emulator gets instead ("" = one we can't name).
    sends: dict[str, str] = field(default_factory=dict)
    #: ``~`` remaps, which let the pressed key through as well.
    passthrough: set[str] = field(default_factory=set)

    def panel_keys(self, key: str) -> list[str]:
        """Panel keys that reach the emulator as *key*."""
        out = [key] if key not in self.sends or key in self.passthrough else []
        return out + [src for src, dst in self.sends.items() if dst == key and src not in out]


# ``r::1``, ``$r::1``, ``~r::1``, optionally with a trailing comment.  Hotkeys
# with a body, Send lines, modifier combos and directives don't match.
_AHK_REMAP_RE = re.compile(r"([$~*]*)([^\s:]+)::(\S+?)(?:\s+;.*)?")
_AHK_CONTEXT_RE = re.compile(r"#If(?:Win(?:Not)?(?:Active|Exist))?(?=[ \t,]|$)[ \t]*,?[ \t]*(.*)$", re.I)
_AHK_MOUSE_KEYS = {"lbutton", "rbutton", "mbutton", "xbutton1", "xbutton2",
                   "wheelup", "wheeldown", "wheelleft", "wheelright"}


def read_ahk_remap(path: Path, source: str = "") -> KeyRemap:
    remap = KeyRemap(source=source or path.name)
    block_comment = conditional = False
    for line in _read_text(path).splitlines():
        s = line.strip()
        if block_comment:
            if s.startswith("*/"):
                block_comment = False
            continue
        if s.startswith("/*"):
            block_comment = True
            continue
        if s.startswith(";"):
            continue
        # AHK's context directives last until the next #If[Win...] directive,
        # not until a Return or a closing brace. Do not guess which window wins.
        context = _AHK_CONTEXT_RE.fullmatch(re.split(r"\s+;", s, maxsplit=1)[0].rstrip())
        if context:
            conditional = bool(context.group(1))
            continue
        if conditional:
            continue
        m = _AHK_REMAP_RE.fullmatch(s)
        src = key_from_ahk(m.group(2)) if m else None
        if src is None or src in remap.sends:
            continue
        target = m.group(3)
        # "r::Return" is a hotkey body, not a remap onto Enter. Likewise,
        # arbitrary commands (Reload, ExitApp, ...) are not unknown key names.
        if target.lower() == "return":
            continue
        dst = key_from_ahk(target)
        if dst is None and target.lower() not in _AHK_MOUSE_KEYS:
            continue
        remap.sends[src] = dst or ""
        if "~" in m.group(1):
            remap.passthrough.add(src)
    return remap


def ahk_profile_keymap(keys: Iterable, source: str, panel: dict[str, str],
                       always_lit: Iterable[str] = ()) -> Keymap:
    """An AHK profile's keys (``keymapper_hotkeys.profile_keys``) as a keymap.

    For an emulator whose own key config can't be read (a PC game launcher, a
    Flash player), the profile is all that says which buttons a game uses.
    One action per panel key, named by what the key does (``a::Space``:
    "Space"); the player and Start / Coin / Select come from the key's port
    label in *panel*.  Keys with no LED (the joystick, the mouse) are left out,
    and so are *always_lit* keys, which the admin block lights anyway (Exit,
    Pause).
    """
    km = Keymap(source=f"AHK {source}")
    skip = set(always_lit)
    for pk in keys:
        code = key_from_ahk(pk.key)
        if code is None or code not in panel or code in km.labels or code in skip:
            continue
        port = panel[code].upper()
        km.keys[(2 if port.startswith("P2") else 1, code)] = [code]
        km.labels[code] = pk.does or pk.key.upper()
        if any(word in port for word in ("START", "COIN", "SELECT")):
            km.system_actions.add(code)
    return km


@dataclass
class Launcher:
    emulator: str
    folder: Optional[Path]
    exe: str
    #: The section's ``Module`` (``MUGEN.ahk``); "" when it names none.
    module: str = ""


class RocketLauncherIndex:
    def __init__(self, config: Config):
        self.rl_dir = Path(config.rocketlauncher_dir)
        self.emulators_dir = Path(config.emulators_dir) if config.emulators_dir else None
        self.settings = self.rl_dir / "Settings"
        self.global_emus = _read_ini_loose(self.settings / "Global Emulators.ini")
        profiles = PureWindowsPath(_ini_value(self.settings / "RocketLauncher.ini", "Settings", "Profiles_Path")
                                   or ".\\Profiles")
        self.ahk_dir = (Path(str(profiles)) if profiles.is_absolute()
                        else self.rl_dir.joinpath(*profiles.parts)) / "AHK"
        self._ahk_on: dict[str, bool] = {}
        self._ahk_internal: dict[str, bool] = {}
        self._ahk_files: dict[Path, dict[str, Path]] = {}
        self._remaps: dict[Path, KeyRemap] = {}
        self._profile_keys: dict[tuple[Path, bool], list] = {}
        self._navigation: Optional[dict[str, tuple[str, str]]] = None
        self._games: dict[str, dict[str, tuple[str, str]]] = {}
        self._games_lower: dict[str, dict[str, tuple[str, str]]] = {}
        self._system_inis: dict[str, dict[str, dict[str, str]]] = {}

    def _system_ini(self, system: str) -> dict[str, dict[str, str]]:
        if system not in self._system_inis:
            self._system_inis[system] = _read_ini_loose(self.settings / system / "Emulators.ini")
        return self._system_inis[system]

    def default_emulator(self, system: str) -> str:
        ini = self._system_ini(system)
        return ini.get("ROMS", ini.get("Roms", {})).get("Default_Emulator", "")

    def game_overrides(self, system: str) -> dict[str, tuple[str, str]]:
        """``Games.ini``: game -> (emulator, system) for games not on the default emulator."""
        if system in self._games:
            return self._games[system]
        out = {}
        for game, keys in _read_ini_loose(self.settings / system / "Games.ini").items():
            emu, sysname = keys.get("Emulator", ""), keys.get("System", "")
            if emu or sysname:
                out[game] = (emu, sysname)
        self._games[system] = out
        lower = self._games_lower[system] = {}
        for game, override in out.items():
            lower.setdefault(game.lower(), override)
        return out

    def game_override(self, system: str, game: str) -> tuple[str, str]:
        self.game_overrides(system)
        return self._games_lower[system].get(game.lower(), ("", ""))

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
        return Launcher(emulator=emulator, folder=folder, exe=p.name,
                        module=PureWindowsPath(sec.get("Module", "")).name)

    def ahk_keymapper_on(self, system: str) -> bool:
        """Whether RocketLauncher loads AHK keymapper profiles for *system*.

        ``Keymapper_AHK_Method`` (Internal / External) from the wheel's
        ``RocketLauncher.ini``, or the global one where the wheel says
        ``use_global`` or has no key.  ``Keymapper_Enabled`` is for Xpadder /
        JoyToKey and plays no part.  Missing everywhere means ``false``,
        RocketLauncher's own default.
        """
        if system not in self._ahk_on:
            key = ("Keymapper", "Keymapper_AHK_Method")
            method = _ini_value(self.settings / system / "RocketLauncher.ini", *key)
            if method is None or method.lower() == "use_global":
                method = _ini_value(self.settings / "Global RocketLauncher.ini", *key)
            self._ahk_on[system] = (method or "").lower() in ("internal", "external")
            self._ahk_internal[system] = (method or "").lower() == "internal"
        return self._ahk_on[system]

    def _ahk_folder(self, folder: Path) -> dict[str, Path]:
        """Lower-cased file name -> file in one AHK profile folder (Windows names ignore case)."""
        if folder not in self._ahk_files:
            self._ahk_files[folder] = ({p.name.lower(): p for p in folder.iterdir() if p.is_file()}
                                       if folder.is_dir() else {})
        return self._ahk_files[folder]

    def ahk_profile(self, system: str, game: Optional[str], emulator: str) -> Optional[Path]:
        """The AHK keymapper profile RocketLauncher loads for *game* on *system*.

        The first that exists of ``<wheel>\\<game>.ahk``, ``<wheel>\\<emulator>.ahk``,
        ``<wheel>.ahk`` and ``_Default.ahk``: exact names, in any case.  Without
        *game*: the profile of a game that has no file of its own.
        """
        if not self.ahk_keymapper_on(system):
            return None
        wheel, top = self._ahk_folder(self.ahk_dir / system), self._ahk_folder(self.ahk_dir)
        for name, files in ((game, wheel), (emulator, wheel), (system, top), ("_Default", top)):
            if name and f"{name}.ahk".lower() in files:
                return files[f"{name}.ahk".lower()]
        return None

    def _ahk_source(self, path: Path) -> str:
        return path.name if path.parent == self.ahk_dir else f"{path.parent.name}\\{path.name}"

    def ahk_remap(self, system: str, game: Optional[str], emulator: str) -> Optional[KeyRemap]:
        path = self.ahk_profile(system, game, emulator)
        if path is None:
            return None
        if path not in self._remaps:
            self._remaps[path] = read_ahk_remap(path, self._ahk_source(path))
        return self._remaps[path]

    def ahk_profile_keys(self, system: str, game: Optional[str],
                         emulator: str) -> Optional[tuple[str, list]]:
        """(source, keys it acts on) of the AHK profile *game* loads, or None.

        With the Internal keymapper, plain hotkeys on RocketLauncher's menu
        navigation keys are left out: its ``Hotkey`` commands take them over.
        """
        path = self.ahk_profile(system, game, emulator)
        if path is None:
            return None
        # keymapper_hotkeys imports this module, so it is imported here.
        from .keymapper_hotkeys import navigation_keys, profile_keys
        internal = self._ahk_internal[system]
        if (path, internal) not in self._profile_keys:
            if self._navigation is None:
                self._navigation = navigation_keys(self.settings)
            self._profile_keys[(path, internal)] = profile_keys(
                _read_text(path), self._navigation if internal else {})
        return self._ahk_source(path), self._profile_keys[(path, internal)]


class KeymapResolver:
    """Resolve the keymap a (system, game) actually launches with."""

    def __init__(self, config: Config):
        self.rl = RocketLauncherIndex(config)
        self._ra: dict[Path, RetroArchIndex] = {}
        self._mame: dict[Path, MameIndex] = {}
        self._simple: dict[tuple[str, Path], Optional[Keymap]] = {}
        self._flycast: dict[tuple[Path, bool], Optional[Keymap]] = {}
        self._mapping_files: dict[Path, dict[str, Path]] = {}
        self._uae: dict[Path, Keymap] = {}
        self._mugen: dict[tuple[str, str], Optional[Keymap]] = {}
        self._roms: Optional[_RomLookup] = None
        self.config = config
        #: The panel's key -> port label (``ProfileBuilder`` sets it): which
        #: player a MESS keypad key belongs to.
        self.panel: dict[str, str] = {}

    def for_launcher(self, launcher: Optional[Launcher], system: str,
                     game: Optional[str] = None) -> Optional[Keymap]:
        """Keymap for *launcher*; with *game*, only a game-specific keymap (else None)."""
        if launcher is None or launcher.folder is None or not launcher.folder.is_dir():
            return None
        exe = launcher.exe.lower()
        folder = launcher.folder
        if exe.startswith("retroarch"):
            if folder not in self._ra:
                self._ra[folder] = RetroArchIndex(folder)
            ra = self._ra[folder]
            km = ra.keymap(system, game)
            if km is not None:
                km.labels = dict(CONSOLE_LABELS.get(system, {}))
            return km
        if exe.startswith(("mame", "hbmame", "mess")):
            if folder not in self._mame:
                self._mame[folder] = MameIndex(folder, launcher.exe)
            idx = self._mame[folder]
            if system in MESS_DRIVERS:
                # Console run through MESS/MAME: one driver for the whole wheel.
                km = idx.driver_keymap(MESS_DRIVERS[system], self.panel) if not game else None
            elif system in MESS_PER_GAME_DRIVER:
                km = idx.driver_keymap(game, self.panel) if game else None
            else:
                # Arcade ROM: default keys plus cfg/<game>.cfg.
                km = idx.keymap(game)
            if km is not None and (system in MESS_DRIVERS or system in MESS_PER_GAME_DRIVER):
                km.labels = {**MESS_LABELS, **km.labels}
            return km
        if launcher.module.lower().startswith("mugen") or exe.startswith(("mugen", "winmugen")):
            return self._mugen_keymap(launcher, system, game)
        if exe.startswith("flycast"):
            return self._flycast_keymap(folder / "mappings", system, game, launcher.emulator)
        if exe.startswith("winuae"):
            return self._winuae_keymap(folder, system, game)
        if game:
            return None
        readers = {"desmume": desmume_keymap, "melonds": melonds_keymap,
                   "ssf.exe": ssf_keymap, "zinc.exe": zinc_keymap,
                   "demul.exe": demul_keymap, "daphne.exe": daphne_keymap,
                   "pokemini.exe": pokemini_keymap, "ppsspp": ppsspp_keymap,
                   "duckstation": duckstation_keymap, "pcsx2": pcsx2_keymap,
                   "vita3k": vita3k_keymap, "eka2l1": eka2l1_keymap, "cxbx": cxbxr_keymap,
                   "bigpemu": bigpemu_keymap, "snesgt": snesgt_keymap, "project64": nrage_keymap}
        for prefix, reader in readers.items():
            if exe.startswith(prefix):
                key = (prefix, folder)
                if key not in self._simple:
                    self._simple[key] = reader(folder)
                return self._simple[key]
        return None

    def _winuae_keymap(self, folder: Path, system: str, game: Optional[str]) -> Optional[Keymap]:
        """WinUAE: with *game*, its own ``Configurations\\<game>.uae`` (else None); without, the host config."""
        if game:
            confs = _ci_path(folder, "Configurations")
            if confs is not None and confs not in self._mapping_files:
                self._mapping_files[confs] = ({p.name.lower(): p for p in confs.iterdir() if p.is_file()}
                                              if confs.is_dir() else {})
            path = self._mapping_files.get(confs, {}).get(f"{game}.uae".lower()) if confs else None
        else:
            path = winuae_host_config(folder, system)
        if path is None or not path.is_file():
            return None
        if path not in self._uae:
            self._uae[path] = winuae_keymap(path)
        return self._uae[path]

    def _mugen_game(self, launcher: Launcher, system: str, game: str) -> Optional[Keymap]:
        """One Mugen game's keys: ``data\\mugen.cfg`` beside the exe RocketLauncher's module starts.

        That exe is the game's ``gamePath`` in the module's ini
        (``Modules\\MUGEN\\MUGEN.ini``), else ``<game>\\MUGEN.exe``, inside the
        game's folder, ``.zip`` or ``.7z`` (``py7zr``) under the wheel's ``Rom_Path``.
        """
        key = (system.lower(), game.lower())
        if key in self._mugen:
            return self._mugen[key]
        stem = Path(launcher.module).stem or "MUGEN"
        exe = _ini_value(self.rl.rl_dir / "Modules" / stem / f"{stem}.ini", game, "gamePath")
        rel = PureWindowsPath(exe.strip().strip('"') if exe and exe.strip() else f"{game}\\MUGEN.exe")
        member = "/".join(rel.parent.parts + ("data", "mugen.cfg"))
        if self._roms is None:
            self._roms = _RomLookup(self.rl.rl_dir)
        src = self._roms.source(system, launcher.emulator)
        rom = self._roms.find(src, [game]) if src is not None else None
        if rom is None and src is not None:
            rom = next((f / game for _el, f in src.folders if f is not None and (f / game).is_dir()), None)
        text = mugen_game_cfg(rom, member) if rom is not None else None
        km = mugen_keymap_text(text, "Mugen " + member.replace("/", "\\")) if text else None
        self._mugen[key] = km
        return km

    def _mugen_keymap(self, launcher: Launcher, system: str, game: Optional[str]) -> Optional[Keymap]:
        """Mugen: every game is its own build with its own keys.

        With *game*, that game's keys.  Without, the layout most of the
        wheel's games share, so the games that differ get groups of their own.
        """
        if game:
            return self._mugen_game(launcher, system, game)
        counts: dict[tuple, list[Keymap]] = {}
        for g in load_db(self.config, system) or []:
            km = self._mugen_game(launcher, system, g.name)
            if km is not None:
                counts.setdefault(tuple(sorted((s, tuple(k)) for s, k in km.keys.items())), []).append(km)
        if not counts:
            return None
        best = max(counts.values(), key=len)
        km = Keymap(source=f"Mugen data\\mugen.cfg ({len(best)} of {sum(map(len, counts.values()))} games)",
                    keys=dict(best[0].keys), labels=dict(best[0].labels))
        return km

    def _flycast_keymap(self, mappings: Path, system: str, game: Optional[str],
                        emulator: str) -> Optional[Keymap]:
        """Flycast's keys for *system*, or with *game* that game's own file (else None).

        A Dreamcast game's file is named after the product number inside its
        disc image, which isn't read here.  A Naomi cartridge's is named after
        the title in its ROM header, read from the game's zip only when the
        ``mappings`` folder has per-game files at all.
        """
        if mappings not in self._mapping_files:
            self._mapping_files[mappings] = ({p.name.lower(): p for p in mappings.iterdir() if p.is_file()}
                                             if mappings.is_dir() else {})
        files = self._mapping_files[mappings]
        arcade = is_flycast_arcade(system)
        general = flycast_key_file(files, arcade)
        if not game:
            if general is None:
                return None
            # An arcade wheel can fall back to SDL_Keyboard.cfg, which then reads as arcade buttons.
            key = (general, arcade)
            if key not in self._flycast:
                self._flycast[key] = flycast_keymap(general, arcade)
            return self._flycast[key]
        if not arcade or not any(n.startswith("sdl_keyboard_") and n != "sdl_keyboard_arcade.cfg"
                                 for n in files):
            return None
        if self._roms is None:
            self._roms = _RomLookup(self.rl.rl_dir)
        src = self._roms.source(system, emulator)
        rom = self._roms.find(src, [game]) if src is not None else None
        title = naomi_boot_title(rom) if rom is not None and rom.suffix.lower() == ".zip" else None
        own = flycast_key_file(files, True, title) if title else None
        return flycast_keymap(own, True) if own is not None and own != general else None

    def system_launcher(self, system: str) -> Optional[Launcher]:
        return self.rl.launcher(self.rl.default_emulator(system), system)

    def game_launcher(self, system: str, game: str) -> tuple[Optional[Launcher], str]:
        """Effective emulator and config system, including Games.ini overrides."""
        emulator, other = self.rl.game_override(system, game)
        config_system = other or system
        return self.rl.launcher(emulator or self.rl.default_emulator(config_system), config_system), config_system

    def for_game(self, system: str, game: str) -> Optional[Keymap]:
        """Effective per-game emulator keys, then the launch wheel's AHK profile."""
        launcher, config_system = self.game_launcher(system, game)
        km = self.for_launcher(launcher, config_system, game)
        if km is None:
            km = self.for_launcher(launcher, config_system)
        return self.through_remap(km, system, game, launcher)

    def through_remap(self, km: Optional[Keymap], system: str, game: Optional[str],
                      launcher: Optional[Launcher]) -> Optional[Keymap]:
        """*km* in panel keys, through the AHK keymapper profile *game* launches with.

        An assumed keymap (``verified=False``) is already in panel keys and is
        returned as is, like any keymap no remapping profile applies to.
        """
        if km is None or not km.verified:
            return km
        remap = self.rl.ahk_remap(system, game, launcher.emulator if launcher else "")
        return km.remapped(remap) if remap is not None and remap.sends else km

    def profile_keymap(self, system: str, game: Optional[str], panel: dict[str, str],
                       always_lit: Iterable[str] = ()) -> Optional[Keymap]:
        """The AHK keymapper profile *game* launches with, as its keymap.

        For an emulator whose own keys can't be read; None when no profile
        applies.  Without *game*: the profile of a game with no file of its own.
        """
        if game:
            emulator, other = self.rl.game_override(system, game)
            emulator = emulator or self.rl.default_emulator(other or system)
        else:
            emulator = self.rl.default_emulator(system)
        found = self.rl.ahk_profile_keys(system, game, emulator)
        return ahk_profile_keymap(found[1], found[0], panel, always_lit) if found else None


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
_GENERATED_OVERRIDE = "<!-- spindoctor: generated keymap override -->"


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
    generated_override: bool = False

    def render(self) -> str:
        extra = ' defaultActive="48,48,48,48" defaultInactive="0,0,0,0"' if self.default_attrs else ""
        lines = [f"    <controlGroup groupName={quoteattr(self.name)} voice={quoteattr(self.voice)} "
                 f'numPlayers="{self.num_players}" alternating="{self.alternating}"{extra} jukebox="0">']
        if self.generated_override:
            lines.append("      " + _GENERATED_OVERRIDE)
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

    def rename_emulator(self, key: str, emuname: str) -> bool:
        """Give the section *key* the ``emuname`` *emuname*; its groups stay as they are."""
        m = self._emu_span(key)
        if m is None:
            return False
        block = re.sub(r'(<emulator\b[^>]*?\bemuname=)"[^"]*"', lambda t: t.group(1) + quoteattr(emuname),
                       m.group(0), count=1)
        self.text = self.text[:m.start()] + block + self.text[m.end():]
        return True

    def upsert_groups(self, system: str, groups: Iterable[GroupXml],
                      remove: Iterable[str] = ()) -> None:
        """Replace (or add) whole control groups under the emulator for wheel *system*."""
        groups = list(groups)
        key = system_key(system)
        m = self._emu_span(key)
        if m is None:
            block = (f"  <emulator emuname={quoteattr(wheel_section_name(system))} emuDesc=\"\">\n"
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


def _always_lit(player0: str) -> set[str]:
    """Key codes an admin block (``<player number="0">``) lights at all times."""
    out: set[str] = set()
    for tag in re.findall(r"<control\b[^>]*/>", player0):
        codes = re.search(r'inputCodes="([^"]*)"', tag)
        if 'alwaysActive="1"' in tag and codes:
            out.update(c for c in codes.group(1).split("|") if c)
    return out


def _existing_controls(group: Optional[ET.Element]) -> list[ET.Element]:
    return [] if group is None else [c for p in group.iter("player")
                                     if p.get("number") != "0" for c in p.iter("control")]


def build_console_group(name: str, keymap: Keymap, panel: dict[str, str],
                        existing: Optional[ET.Element], player0: str) -> GroupXml:
    """A console profile: one control per keymap action that reaches a panel LED."""
    old = _existing_controls(existing)
    # Each player's own colour for a voice first, then the first player's that has
    # one: keyed by voice alone, player 2's colours replaced player 1's on a rerun.
    old_color_by_voice: dict[tuple[int, str], str] = {}
    for pl in ([] if existing is None else existing.iter("player")):
        num = pl.get("number") or ""
        if not num.isdigit() or num == "0":
            continue
        for c in pl.iter("control"):
            voice_key = (c.get("voice") or "").lower()
            for who in (int(num), 0):
                old_color_by_voice.setdefault((who, voice_key), c.get("color") or "")
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
            is_system_button = (act.lower() in ("start", "select", "coin", "power", "mode", "run", "option")
                                or act in keymap.system_actions)
            if is_system_button:
                extra_n += 1
                cname = f"P{p}_BUTTON{extra_n}"
            else:
                n += 1
                cname = f"P{p}_BUTTON{n}"
            color = (old_color_by_voice.get((p, voice.lower())) or old_color_by_voice.get((0, voice.lower()))
                     or old_color_by_key.get(keys[0]) or "")
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
    return load_db_file(config.databases_dir / system / f"{system}.xml")


def load_db_file(path: Path) -> Optional[list[DbGame]]:
    """Games in a HyperSpin database XML (``None`` if there's no such file)."""
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
        self.resolver.panel = self.panel
        self.xml_path = self.lb_dir / CONTROLS_XML_NAME
        # The document's regex edits insert "\n"; keep the file's own line
        # endings by editing LF text and restoring CRLF on write.
        xml_text = read_editable_text(self.xml_path)
        self._xml_crlf = "\r\n" in xml_text
        self._xml_original = xml_text.replace("\r\n", "\n")
        self.doc = ControlsXmlDoc(self._xml_original)
        # In any case: LEDBlinky ships `Controls.ini`, while `ledblinky generate`
        # / `prune` name it `controls.ini`; one file on Windows, two on Linux.
        self.controls_path = _ci_file(self.lb_dir, CONTROLS_INI_FILE) or self.lb_dir / CONTROLS_INI_FILE
        self.colors_path = _ci_file(self.lb_dir, COLORS_INI_NAME) or self.lb_dir / COLORS_INI_NAME
        self.controls = read_ini_sections(self.controls_path)
        self.colors = read_ini_sections(self.colors_path)
        self.library = Library()
        community = find_community_controls(self.lb_dir, config)
        if community is None and self.library.community_path.is_file():
            # Moved out of ledblinky_dir: the library keeps a copy.
            community = self.library.community_path
        self.community = read_ini_sections(community) if community else {}
        self._lib_controls: Optional[dict[str, dict[str, str]]] = None
        self._lib_colors: Optional[dict[str, dict[str, str]]] = None
        self.result = ProfilesResult()
        # Controls.ini / Colors.ini edits: rom -> new body lines (None = unchanged)
        self._controls_new: dict[str, dict[str, str]] = {}
        self._colors_new: dict[str, dict[str, str]] = {}
        self._mame_groups = self.doc.groups(self.doc.emulators().get("MAME", ""))

    # -- helpers --------------------------------------------------------------

    def _default_block(self, system: str) -> tuple[Optional[ET.Element], str]:
        emu = self.doc.emulators().get(system_key(system))
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

    def _library_ini(self) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        """SpinDoctor's LEDBlinky library (entries pruned from the live files), read once."""
        if self._lib_controls is None or self._lib_colors is None:
            self._lib_controls = read_ini_sections(self.library.controls_path)
            self._lib_colors = read_ini_sections(self.library.colors_path)
        return self._lib_controls, self._lib_colors

    def donor_controls(self, rom: str) -> Optional[dict[str, str]]:
        """A donor's Controls.ini entry: live first, then the library.

        Donors may be games in no wheel, and ``ledblinky prune`` moves those
        to the library; looking there too keeps the same donors after a prune.
        """
        return self.controls_for(rom) or self._library_ini()[0].get(rom.lower())

    def donor_colors(self, rom: str) -> dict[str, str]:
        return self.colors_for(rom) or self._library_ini()[1].get(rom.lower()) or {}

    def _donor(self, game: DbGame, by_desc: dict[str, str],
               regional: Optional[dict[str, str]] = None) -> Optional[str]:
        """Best Controls.ini entry for a ROM that has none of its own (live, else library)."""
        for cand in (game.cloneof, _SUFFIX_RE.sub("", game.name)):
            if cand and cand.lower() != game.name.lower() and self.donor_controls(cand):
                return cand
        name = game.name.lower()
        for cut in range(len(name) - 1, len(name) - 3, -1):
            if cut > 2 and self.donor_controls(name[:cut]):
                return name[:cut]
        if len(name) > 4:
            # Regional clone differing only in its last letter (souledga -> souledge).
            if regional is None:
                regional = self._regional_donors()
            if name[:-1] in regional:
                return regional[name[:-1]]
        base = re.sub(r"\s*[\(\[].*$", "", game.description).strip().lower()
        return by_desc.get(base)

    def _regional_donors(self) -> dict[str, str]:
        regional: dict[str, str] = {}
        for name in set(self.controls) | set(self._controls_new) | set(self._library_ini()[0]):
            prefix = name[:-1]
            if prefix not in regional or name < regional[prefix]:
                regional[prefix] = name
        return regional

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
            if self.donor_controls(g.name):
                by_desc.setdefault(base, g.name)
        pending = [(s, g) for s in systems for g in load_db(self.config, s) or []
                   if not self.controls_for(g.name) and emu_key(g.name) not in self._mame_groups]
        added: dict[str, int] = {}
        regional = self._regional_donors()
        # Repeat until nothing new resolves: a hack's parent may itself be a
        # hack that only gets its entry earlier in this pass.
        while pending:
            left = []
            for system, game in pending:
                if self.controls_for(game.name):
                    continue   # same ROM in two wheels, already added
                # Its own entry, if `ledblinky prune` moved it to the library.
                own = game.name if self._library_ini()[0].get(game.name.lower()) else None
                donor = own or self._donor(game, by_desc, regional)
                if not donor:
                    left.append((system, game))
                    continue
                name = game.name.lower()
                self._controls_new[name] = dict(self.donor_controls(donor) or {})
                if name[:-1] not in regional or name < regional[name[:-1]]:
                    regional[name[:-1]] = name
                self._colors_new[game.name.lower()] = dict(self.donor_colors(donor))
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
        base = self.resolver.for_launcher(launcher, system)
        keymap = self.resolver.through_remap(base, system, None, launcher)
        # An emulator whose keys can't be read (a PC game launcher, a Flash
        # player): the AHK keymapper profiles are all that say what a game uses.
        profiles = keymap is None
        existing, player0 = self._default_block(system)
        if profiles:
            keymap = self.resolver.profile_keymap(system, None, self.panel,
                                                  _always_lit(player0 or self._admin_player0()))
        if keymap is None:
            emu = launcher.emulator if launcher else "(none)"
            if existing is None:
                self._admin_only(system, f"no readable keymap for {emu}")
            else:
                self.result.actions.append(SystemAction(system, "kept existing DEFAULT", 0, "",
                                                        f"keymap for {emu} not readable"))
            if self.resolver.rl.ahk_keymapper_on(system):
                # Games with a profile of their own still light from it.
                existing, player0 = self._default_block(system)
                self._game_overrides(system, Keymap(source=""), existing, player0, profiles=True)
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
        self._game_overrides(system, keymap, existing, player0, profiles=profiles)

    def _game_overrides(self, system: str, sys_keymap: Keymap,
                        existing: Optional[ET.Element], player0: str, profiles: bool = False) -> None:
        """Per-game groups using only the emulator/config actually launched.

        *profiles*: the wheel's emulator keys can't be read, so a game whose
        own keys can't be read either lights from its AHK keymapper profile.
        """
        games = {g.name for g in load_db(self.config, system) or []}
        groups = []
        old_groups = self.doc.groups(self.doc.emulators().get(system_key(system), ""))
        # Only remove groups we created, never unrelated hand-authored profiles.
        obsolete = {k for k, blocks in old_groups.items() if _GENERATED_OVERRIDE in blocks[0]}
        overridden = {g.lower() for g in self.resolver.rl.game_overrides(system)}
        always_lit = _always_lit(player0 or self._admin_player0())
        for game in sorted(games):
            km = self.resolver.for_game(system, game)
            if km is None and profiles:
                km = self.resolver.profile_keymap(system, game, self.panel, always_lit)
            if km is None:
                # A missing AHK profile no longer justifies a generated group.
                # Unreadable emulator configs still keep their previous lights.
                if not profiles:
                    obsolete.discard(emu_key(game))
                if game.lower() in overridden and not profiles:
                    self.result.warnings.append(f"{system}: '{game}' keymap isn't readable — kept system DEFAULT")
                continue
            # Profiles light the same keys with different voices ("Space", "Enter").
            same = km.keys == sys_keymap.keys and (not profiles or km.labels == sys_keymap.labels)
            if same and game.lower() not in overridden:
                continue
            km.labels = km.labels or sys_keymap.labels
            old = old_groups.get(emu_key(game))
            old_el, old_p0 = parse_group(old[0]) if old else (existing, "")
            grp = build_console_group(group_name(game), km, self.panel, old_el,
                                      old_p0 or player0 or self._admin_player0())
            grp.generated_override = not old or _GENERATED_OVERRIDE in old[0]
            groups.append(grp)
            obsolete.discard(emu_key(game))
        if groups or obsolete:
            self.doc.upsert_groups(system, groups, remove=obsolete)
            self.result.actions.append(SystemAction(system, "per-game groups (emulator/keymap overrides)",
                                                    len(groups), "Games.ini / RetroArch game cfg / AHK profile",
                                                    f"removed {len(obsolete)} obsolete generated groups" if obsolete else ""))

    def handheld_wheel(self, system: str) -> None:
        """Per-game groups for wheels where each game is its own MAME driver."""
        launcher = self.resolver.system_launcher(system)
        existing, player0 = self._default_block(system)
        groups = []
        for game in load_db(self.config, system) or []:
            km = self.resolver.for_game(system, game.name)
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
        player0 = self._default_block(system)[1] or self._admin_player0()
        existing_emu = self.doc.emulators().get(system_key(system), "")
        existing_groups = self.doc.groups(existing_emu)
        default_el = self._default_block(system)[0]
        default_colors = {c.get("name"): c.get("color") for c in _existing_controls(default_el)}
        groups, unresolved, assumed, remapped = [], 0, 0, 0
        for game in load_db(self.config, system) or []:
            lau, config_system = self.resolver.game_launcher(system, game.name)
            km = None
            if lau is not None:
                km = self.resolver.for_launcher(lau, config_system, game.name)
                if km is None:
                    km = self.resolver.for_launcher(lau, config_system)
                ahk_km = self.resolver.through_remap(km, system, game.name, lau)
                if ahk_km is not km:
                    remapped += 1
                km = ahk_km
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
                ctl = self.donor_controls(donor) if donor else None
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
        if remapped:
            note.append(f"{remapped} through AHK keymapper profiles")
        self.result.actions.append(SystemAction(system, "per-game arcade groups", len(groups), src, "; ".join(note)))

    def rekey_existing_arcade(self, system: str) -> None:
        """Fix the button 4-8 keys of an arcade emulator's existing groups."""
        launcher = self.resolver.system_launcher(system)
        km = self.resolver.for_launcher(launcher, system)
        if km is None or not km.keys:
            km = arcade_layout_keymap()
        emu_block = self.doc.emulators().get(system_key(system))
        if not emu_block:
            return
        db = load_db(self.config, system) or []
        names = {emu_key(g.name): g.name for g in db}
        fixed = 0
        new_emu = emu_block
        for key, blocks in self.doc.groups(emu_block).items():
            # DEFAULT and groups for games not in the database: the wheel's AHK profile.
            game_km = (self.resolver.for_game(system, names[key]) or arcade_layout_keymap()
                       if key in names else self.resolver.through_remap(km, system, None, launcher))
            for b in blocks:
                nb = self._ensure_admin(rekey_arcade_group(b, game_km, self.panel) or b)
                if nb != b:
                    new_emu = new_emu.replace(b, nb, 1)
                    fixed += 1
        if fixed:
            self.doc.text = self.doc.text.replace(emu_block, new_emu, 1)
        source = self.resolver.through_remap(km, system, None, launcher).source
        self.result.actions.append(SystemAction(system, "re-keyed existing arcade groups", fixed, source,
                                                "" if km.verified else "keys assumed from cabinet arcade layout"))
        # Games with no group of their own but with controls data get one.
        have = self.doc.groups(self.doc.emulators().get(system_key(system), ""))
        default_el, player0 = self._default_block(system)
        default_colors = {c.get("name"): c.get("color") for c in _existing_controls(default_el)}
        new = []
        for game in db:
            if emu_key(game.name) in have:
                continue
            ctl = self.controls_for(game.name)
            if ctl is None:
                continue
            community = self.community_for(game.name)
            new.append(build_arcade_group(
                game.name, ctl, self.colors_for(game.name),
                self.resolver.for_game(system, game.name) or arcade_layout_keymap(), self.panel,
                set_primary_joystick(player0 or self._admin_player0(), community_joystick(community)),
                community_button_labels(community), default_colors, game.description))
        if new:
            self.doc.upsert_groups(system, new)
            self.result.actions.append(SystemAction(system, "new per-game arcade groups", len(new), source))

    def migrate_legacy_section(self, system: str, legacy_emu: str) -> None:
        """Carry an old emulator section's groups over to a renamed wheel, re-keyed."""
        emus = self.doc.emulators()
        old = emus.get(emu_key(legacy_emu))
        if not old or system_key(system) in emus:
            return
        games = {emu_key(g.name) for g in load_db(self.config, system) or []} | {"DEFAULT"}
        km = arcade_layout_keymap()
        blocks = []
        for key, bl in self.doc.groups(old).items():
            if key in games:
                blocks.append(self._ensure_admin(rekey_arcade_group(bl[0], km, self.panel) or bl[0]))
        block = (f"  <emulator emuname={quoteattr(wheel_section_name(system))} emuDesc=\"\">\n"
                 + "".join(b if b.endswith("\n") else b + "\n" for b in blocks) + "  </emulator>\n")
        anchor = re.search(r'[ \t]*<emulator\b[^>]*emuname="OTHER"', self.doc.text)
        pos = anchor.start() if anchor else self.doc.text.rfind("</dat>")
        self.doc.text = self.doc.text[:pos] + block + self.doc.text[pos:]
        self.result.actions.append(SystemAction(system, f"groups carried over from {legacy_emu}", len(blocks),
                                                km.source, "keys assumed from cabinet arcade layout"))

    def rename_dotted_section(self, system: str) -> None:
        """Move a section named after the whole of a dotted wheel name to the name LEDBlinky asks for.

        LEDBlinky cuts a wheel's name at its last dot, so a ``Tiger_Game.com``
        section is never used for the ``Tiger Game.com`` wheel; ``Tiger_Game``
        is.  The section keeps its groups.  When both are there, neither is
        touched: the cut one is in use already.
        """
        full, cut = emu_key(system), system_key(system)
        emus = self.doc.emulators()
        if full == cut or full not in emus:
            return
        old_name = _unescape(re.search(r'emuname="([^"]*)"', emus[full]).group(1))
        if cut in emus:
            self.result.warnings.append(
                f"{system}: section '{old_name}' is never used (LEDBlinky looks this wheel up as "
                f"'{wheel_section_name(system)}', which is there too); delete it by hand")
            return
        self.doc.rename_emulator(full, wheel_section_name(system))
        self.result.actions.append(SystemAction(
            system, f"section {old_name} renamed {wheel_section_name(system)}",
            len(self.doc.groups(self.doc.emulators()[cut])), "",
            "LEDBlinky cuts a wheel name at its last dot"))

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
            km = self.resolver.for_game(system, rom) or arcade_layout_keymap()
            return build_arcade_group(rom, ctl, self.colors_for(rom), km, self.panel,
                                      set_primary_joystick(self._admin_player0(), joystick), voices)
        emu = self.doc.emulators().get(system_key(system))
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
        key = system_key(system)
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
        raw = RawIni(read_editable_text(path))
        replacements: dict[str, str] = {}
        for name, text in raw.sections:
            low = name.lower()
            if low not in new or low in replacements:
                continue
            values = dict(new[low])
            lines = text.splitlines(keepends=True)
            out = [lines[0]]
            for line in lines[1:]:
                stripped = line.strip()
                if "=" not in line or stripped.startswith((";", "#")):
                    out.append(line)
                    continue
                key, _, old_value = line.partition("=")
                if key.strip() in values:
                    value = values.pop(key.strip())
                    ending = line[len(line.rstrip("\r\n")):]
                    out.append(line if old_value.rstrip("\r\n") == value
                               else f"{key}={value}{ending}")
            if values and out and not out[-1].endswith(("\n", "\r")):
                out.append(raw.newline)
            out.extend(f"{key}={value}{raw.newline}" for key, value in values.items())
            replacements[low] = "".join(out)
        additions = {
            name: render_section(name, (f"{k}={v}" for k, v in values.items()), raw.newline)
            for name, values in new.items() if name not in raw
        }
        return raw.render(add=additions, replace=replacements)

    def write(self, dry_run: bool, backup: bool = True) -> ProfilesResult:
        self.result.dry_run = dry_run
        xml_text = None
        if self.doc.text != self._xml_original:
            xml_text = self.doc.text.replace("\n", "\r\n") if self._xml_crlf else self.doc.text
        outputs = [(self.xml_path, xml_text),
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
                write_windows_text(path, text)
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
        b.rename_dotted_section(system)
    for system in systems:
        if is_mame_named(system) or system in COLLECTION_SYSTEMS:
            continue
        if system in LEGACY_SECTIONS and system_key(system) in b.doc.emulators():
            continue
        launcher = b.resolver.system_launcher(system)
        exe = launcher.exe.lower() if launcher else ""
        if exe.startswith(("mame", "hbmame")) and system not in MESS_DRIVERS and system not in MESS_PER_GAME_DRIVER:
            b.arcade_wheel(system)
        elif exe.startswith(("zinc", "demul", "daphne", "emulator_multicpu", "supermodel", "aae")) \
                or system in ("Sega Model 3", "Sega Triforce", "Taito Type X") \
                or (exe.startswith("flycast") and is_flycast_arcade(system)):
            if system in ("Zinc", "Sega Hikaru") or system_key(system) not in b.doc.emulators():
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
