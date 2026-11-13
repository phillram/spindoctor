"""MAME key maps that a crash while saving has emptied, or will.

MAME keeps a folder's key map in ``cfg\\default.cfg`` and saves it again as
every game exits: it opens the file for writing, which empties it, builds the
new contents, and only then writes them (``config_save_settings`` in
``src/emu/config.c``).  A crash in between leaves the file at 0 bytes.  The
next run can't read it, says nothing, and starts from MAME's own keys (5 for
coin, 1 for start, Ctrl / Alt / Space).  At exit it saves only what differs
from those, which is nothing: ``<system name="default" />`` with no
``<input>``.  The panel's map is gone, and every launch still "works".

MAME 0.145 to 0.179 crash that way when ``default.cfg`` names a pad input
they can't place (read in MAME's ``src/emu/input.c``).  A pad input is either
one of MAME's standard names (``JOYCODE_1_BUTTON1``, ``JOYCODE_1_XAXIS``,
``JOYCODE_1_HAT1UP``), which MAME reads whether the pad is there or not, or
the pad's own name for it (``JOYCODE_1_HATSWITCHU``, a DirectInput pad's
d-pad in MAME 0.160), which MAME can look up only while that pad is
connected.  So can ``UNKNOWN``, which MAME itself writes for a pad that has
gone.  Without the pad MAME keeps the input as an invalid code, and at exit
turning that code back into text copies a null name: the crash.  MAME 0.180
drops such codes as it reads the file, and 0.228 also guards the save.

:func:`read_key_maps` reads one MAME folder; ``doctor``'s **MAME key maps**
check (:func:`spindoctor.health.check_mame_key_maps`) runs it over every
MAME-family emulator RocketLauncher lists.
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .coin_start import _mame_cfg_root, _mame_ini_values, _mame_path

# MAME minor versions (0.145 .. 0.179) that crash saving a pad code they couldn't place.
CRASH_VERSIONS = (145, 179)

# MAME's standard names for pad, mouse and gun items (``itemid_token_table`` in
# src/emu/input.c; 0.145 knew BUTTON1-16 only).  Any other name is the device's
# own, which MAME can look up only while that device is connected.
_STANDARD_ITEM = re.compile(
    r"(?:R?[XYZ]AXIS|SLIDER[12]|BUTTON(?:[1-9]|[12]\d|3[0-2])|START|SELECT"
    r"|HAT[1-4](?:UP|DOWN|LEFT|RIGHT)|ADD(?:SW|AXIS|REL)(?:[1-9]|1[0-6]))")
_DEVICE_CLASSES = ("JOYCODE", "MOUSECODE", "GUNCODE")

# Copies of a key map kept beside it, which MAME never reads.
_SPARE_NAMES = ("default.bak.cfg", "default.cfg.bak")

# The resource section holds icons too; the version block is near its start.
_RSRC_MAX = 8 * 1024 * 1024


def _needs_device(token: str) -> bool:
    """Whether MAME can read *token* (``JOYCODE_1_HATSWITCHU``) only while its device is there.

    Split like MAME's ``code_from_token``: class, then an index when more
    than two parts follow, then the item name.
    """
    parts = token.upper().split("_")
    if parts[0] not in _DEVICE_CLASSES:
        return False
    item = 2 if len(parts) > 2 and re.match(r"[+-]?\d", parts[1]) else 1
    return item >= len(parts) or not _STANDARD_ITEM.fullmatch(parts[item])


def unplaceable_codes(seq: str) -> list[str]:
    """The pad codes in *seq* that MAME 0.145-0.179 can't place without the pad.

    MAME skips a sequence whose first code is invalid (the port keeps its
    built-in keys), so only codes after a readable first one count.
    """
    tokens = seq.split()
    if not tokens or _needs_device(tokens[0]):
        return []
    return [t for t in tokens[1:] if _needs_device(t)]


@dataclass
class MapFile:
    """One key-map file and what MAME makes of it."""
    label: str                    # as shown: cfg\default.cfg
    path: Optional[Path] = None   # None = not there
    size: int = 0
    loads: bool = False           # MAME reads it: <mameconfig> with a "default" system
    ports: int = 0                # <port> entries in that system's <input>
    unplaceable: list[str] = field(default_factory=list)

    @property
    def has_map(self) -> bool:
        return self.loads and self.ports > 0


def _read_map_file(path: Path, label: str, size: int) -> MapFile:
    found = MapFile(label=label, path=path, size=size)
    if size == 0:
        return found
    root = _mame_cfg_root(path)
    if root is None or root.tag != "mameconfig":
        return found
    # MAME applies every <system name="default">, and the first <input> in each.
    systems = [s for s in root.findall("system") if s.get("name") == "default"]
    if not systems:
        return found
    found.loads = True
    for system in systems:
        node = system.find("input")
        for port in (node.findall("port") if node is not None else []):
            found.ports += 1
            for seq in port.findall("newseq"):
                for code in unplaceable_codes(" ".join((seq.text or "").split())):
                    if code not in found.unplaceable:
                        found.unplaceable.append(code)
    return found


@dataclass
class KeyMaps:
    """A MAME folder's key-map files."""
    folder: Path
    exe: str
    default: MapFile                     # cfg\default.cfg
    controller: Optional[MapFile]        # the ctrlr file mame.ini names, read before default.cfg
    controller_option: str               # mame.ini's ctrlr value ("" = none)
    ini_name: str                        # mame.ini or hbmame.ini
    spares: list[MapFile] = field(default_factory=list)  # copies holding a map MAME never reads
    empty_games: list[str] = field(default_factory=list)  # games whose cfg is 0 bytes
    version: str = ""                    # the exe's ProductVersion, read only when it matters

    @property
    def crashes_saving(self) -> bool:
        """Whether this MAME crashes saving a pad code it couldn't place."""
        minor = mame_minor(self.version)
        return minor is not None and CRASH_VERSIONS[0] <= minor <= CRASH_VERSIONS[1]


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def read_key_maps(folder: Path, exe: str) -> KeyMaps:
    """Read the key-map files of the MAME (or HBMAME) folder *folder*.

    ``cfg_directory``, ``ctrlr`` and ``ctrlrpath`` come from the folder's
    ``mame.ini`` / ``hbmame.ini``; command-line options (RocketLauncher's
    MAME module can pass ``-cfg_directory`` and ``-ctrlr``) aren't seen.
    """
    ini = _mame_ini_values(folder, exe)
    ini_name = "hbmame.ini" if exe.lower().startswith("hbmame") else "mame.ini"
    cfg_label = ini.get("cfg_directory") or "cfg"
    cfg_dir = _mame_path(cfg_label, folder)
    entries: dict[str, tuple[Path, int, str]] = {}
    if cfg_dir is not None:
        try:
            with os.scandir(cfg_dir) as it:
                for e in it:
                    if e.is_file():
                        entries[e.name.lower()] = (Path(e.path), e.stat().st_size, e.name)
        except OSError:
            pass

    hit = entries.get("default.cfg")
    default_label = f"{cfg_label}\\default.cfg"
    default = (_read_map_file(hit[0], default_label, hit[1]) if hit
               else MapFile(label=default_label))
    skip = {"default.cfg", *_SPARE_NAMES}
    empty_games = sorted((name[:-4] for low, (_, size, name) in entries.items()
                          if size == 0 and low.endswith(".cfg") and low not in skip),
                         key=str.lower)

    option = (ini.get("ctrlr") or "").strip()
    bases = [(b.strip(), _mame_path(b, folder))
             for b in (ini.get("ctrlrpath") or "ctrlr").split(";") if b.strip()]
    controller = None
    if option and option.lower() != "none":
        for base, d in bases:
            path = d / f"{option}.cfg" if d is not None else None
            if path is not None and path.is_file():
                controller = _read_map_file(path, f"{base}\\{option}.cfg", path.stat().st_size)
                break

    spares = []
    for base, d in bases:
        path = d / "default.cfg" if d is not None else None
        if path is None or not path.is_file():
            continue
        if controller is not None and controller.path is not None and _same(path, controller.path):
            continue
        spare = _read_map_file(path, f"{base}\\default.cfg", path.stat().st_size)
        if spare.has_map:
            spares.append(spare)
    for low in _SPARE_NAMES:
        if low in entries:
            path, size, name = entries[low]
            spare = _read_map_file(path, f"{cfg_label}\\{name}", size)
            if spare.has_map:
                spares.append(spare)

    maps = KeyMaps(folder=folder, exe=exe, default=default, controller=controller,
                   controller_option=option, ini_name=ini_name, spares=spares,
                   empty_games=empty_games)
    if default.unplaceable or any(s.unplaceable for s in spares):
        maps.version = exe_product_version(folder / exe)
    return maps


# ── Windows version resource ──────────────────────────────────────────────────

def mame_minor(version: str) -> Optional[int]:
    """160 for MAME's ``0.160`` (RocketLauncher's MAME module drops the ``0.`` too)."""
    match = re.match(r"\s*0\.(\d+)", version or "")
    return int(match.group(1)) if match else None


def _version_value(data: bytes, key: str) -> str:
    """The value of the ``StringFileInfo`` entry *key* in resource bytes *data*."""
    needle = (key + "\0").encode("utf-16-le")
    at = data.find(needle)
    while at != -1:
        head = at - 6  # wLength, wValueLength, wType, then the key
        if head >= 0:
            words = struct.unpack_from("<H", data, head + 2)[0]
            start = at + len(needle)
            start += (head - start) % 4  # the value starts on a 4-byte boundary
            text = data[start:start + 2 * words].decode("utf-16-le", "replace")
            text = text.split("\0", 1)[0].strip()
            if text:
                return text
        at = data.find(needle, at + 2)
    return ""


def exe_product_version(path: Path) -> str:
    """The ``ProductVersion`` of a Windows program (``0.160``), or ``""``.

    RocketLauncher's MAME module reads the same field to tell MAME versions
    apart.  Only the PE headers and the resource section are read, so a
    300 MB MAME costs a few small reads.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
            if len(head) < 64 or head[:2] != b"MZ":
                return ""
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            fh.seek(pe)
            coff = fh.read(24)
            if len(coff) < 24 or coff[:4] != b"PE\0\0":
                return ""
            sections = struct.unpack_from("<H", coff, 6)[0]
            optional = struct.unpack_from("<H", coff, 20)[0]
            fh.seek(pe + 24 + optional)
            table = fh.read(40 * min(sections, 96))
            for i in range(len(table) // 40):
                name, _, _, size, offset = struct.unpack_from("<8sIIII", table, i * 40)
                if name.rstrip(b"\0") == b".rsrc":
                    fh.seek(offset)
                    return _version_value(fh.read(min(size, _RSRC_MAX)), "ProductVersion")
    except (OSError, struct.error):
        return ""
    return ""
