"""Can a MAME driving game press its pedals from a key, one key per job?

MAME's pedals are analog inputs: ``P1_PEDAL`` (usually the gas),
``P1_PEDAL2`` (usually the brake) and ``P1_PEDAL3`` (a clutch or a third
pedal), and ``P2_PEDAL`` and on for more players.  A keyboard panel presses
a pedal through its *increment* key.  A game set up for a steering wheel
can keep only the wheel's axis in its own cfg
(``<newseq type="increment">NONE</newseq>``), so on the panel it starts,
steers and accelerates, but nothing brakes.  The same cfgs can give one key
two jobs, such as a clutch pedal and a Turbo button both on ``E``.

This reads files only, as :mod:`spindoctor.coin_start` reads Coin/Start:

* A game counts when its own cfg names a pedal.  MAME saves a port in a
  game's cfg only when its setting differs from the default, so the cfg names
  inputs the game has, though not all of them.
* **No key:** a pedal whose own increment has no key while the folder-wide
  one has (``default.cfg``, the ``ctrlr`` file's defaults, or MAME's own
  key), or names only a device MAME no longer finds.  A folder-wide pedal
  with no key is fine with real pedals, so it is only reported as INFO.
* **Two jobs:** one key alone bound to two inputs of different types, among
  the sequences the game's cfg writes itself (the standard one for buttons,
  increment and decrement for analog controls).  Key combinations and
  ``NOT`` terms are left out; two fields of one type share MAME's default
  key on purpose.

What files can't show: keys a driver gives its own inputs (``PORT_CODE``)
replace the folder-wide ones and never appear in a cfg, and an input the cfg
doesn't name may not exist at all.  So a second player's buttons that land
on the first player's Coin or Start through the driver's own keys need
MAME's port list from the running game; ``-listxml`` has no keys, and calls
every pedal just ``pedal``.  Dip switches (a "Gear shift" setting, say) have
no key sequence, so they never count as inputs.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .coin_start import BUILT_IN, Binding, _mame_cfg_root, _mame_ini_values, _mame_path, mame_binding

PEDAL = re.compile(r"^P(\d+)_PEDAL([23]?)$")
# Analog inputs: keys press them through increment / decrement; the standard
# sequence is the axis.
_ANALOG = re.compile(r"^P\d+_(?:PEDAL[23]?|PADDLE(?:_V)?|POSITIONAL(?:_V)?|DIAL(?:_V)?|"
                     r"TRACKBALL_[XY]|AD_STICK_[XYZ]|LIGHTGUN_[XY]|MOUSE_[XY])$")
# MAME's own pedal keys stop at player 4 (P1 LCONTROL / LALT / SPACE ...);
# players 5 and up get only a joystick button.
_BUILT_IN_KEY_PLAYERS = 4


def input_name(kind: str) -> str:
    """A port type in words: ``P1_PEDAL2`` -> ``P1 Pedal 2``, ``COIN1`` -> ``Coin 1``."""
    match = re.match(r"^(P\d+)_(.+)$", kind)
    player, rest = (match.group(1), match.group(2)) if match else ("", kind)
    words = [player] if player else []
    for word in rest.split("_"):
        part = re.match(r"^([A-Z]+)(\d+)$", word)
        words.extend([part.group(1).capitalize(), part.group(2)] if part else [word.capitalize()])
    if rest == "PEDAL":
        words.append("1")  # MAME calls the first one "Pedal 1"
    return " ".join(words)


def key_name(token: str) -> str:
    """``KEYCODE_E`` -> ``E``."""
    return token[len("KEYCODE_"):] if token.startswith("KEYCODE_") else token


def single_keys(seq: str) -> list[str]:
    """Keys that press an input alone: alternatives that are one ``KEYCODE_`` and nothing else."""
    out: list[str] = []
    for alt in " ".join(seq.split()).upper().split(" OR "):
        tokens = alt.split()
        if len(tokens) == 1 and tokens[0].startswith("KEYCODE_") and tokens[0] not in out:
            out.append(tokens[0])
    return out


def _pedal_order(kind: str) -> tuple[int, str]:
    match = PEDAL.match(kind)
    return (int(match.group(1)), match.group(2)) if match else (0, kind)


@dataclass
class Field:
    """One input a game's cfg names, with the sequences the cfg writes for it."""
    kind: str                     # port type, e.g. P1_PEDAL2
    tag: str
    mask: str
    seqs: dict[str, str]          # "standard" / "increment" / "decrement" -> sequence


def _fields(system) -> list[Field]:
    """Inputs of a ``<system>``; dip switches and settings carry no ``<newseq>``."""
    out = []
    for port in system.iter("port"):
        seqs = {}
        for node in port.findall("newseq"):
            text = " ".join((node.text or "").split())
            if text:
                seqs[(node.get("type") or "standard").lower()] = text
        if seqs and port.get("type"):
            out.append(Field(port.get("type", ""), port.get("tag", ""), port.get("mask", ""), seqs))
    return out


@dataclass
class GameKeys:
    """What a game's own cfg says about its pedals and keys."""
    game: str
    cfg: str                                      # e.g. cfg\\coolridr.cfg
    pedals: list[str]                             # pedal types the cfg names
    no_key: list[tuple[Field, Binding]] = field(default_factory=list)
    two_jobs: list[tuple[str, list[Field]]] = field(default_factory=list)
    # Pedal types that follow the folder-wide key (no increment of their own),
    # or have none just as the folder-wide one has none.
    as_folder: set[str] = field(default_factory=set)

    def no_key_text(self) -> str:
        parts = []
        for f, binding in self.no_key:
            why = binding.why()
            parts.append(f"{input_name(f.kind)}: {binding.seq if why == 'nothing' else why}")
        return f"{self.game} ({'; '.join(parts)})"

    def two_jobs_text(self) -> str:
        parts = []
        for key, fields in self.two_jobs:
            names: list[str] = []
            for f in fields:
                if input_name(f.kind) not in names:
                    names.append(input_name(f.kind))
            parts.append(f"{key_name(key)}: {' and '.join(names)}")
        return f"{self.game} ({'; '.join(parts)})"


class MamePedalKeys:
    """Pedals and keys of the games in one MAME folder.

    The folder-wide pedal keys come from the ``ctrlr`` file's ``default``
    section, then ``cfg\\default.cfg`` over it, then MAME's own keys; a
    game's cfg wins over all of them.
    """

    def __init__(self, folder: Path, exe: str):
        self.folder = folder
        ini = _mame_ini_values(folder, exe)
        self.cfg_label = ini.get("cfg_directory") or "cfg"
        cfg_dir = _mame_path(self.cfg_label, folder)
        self._cfgs: dict[str, Path] = {}
        if cfg_dir is not None:
            try:
                with os.scandir(cfg_dir) as it:
                    self._cfgs = {e.name.lower(): Path(e.path) for e in it
                                  if e.name.lower().endswith(".cfg") and e.is_file()}
            except OSError:
                pass
        self._wide: dict[str, Binding] = {}
        ctrlr = ini.get("ctrlr", "")
        if ctrlr and ctrlr.lower() != "none":
            for base in (ini.get("ctrlrpath") or "ctrlr").split(";"):
                d = _mame_path(base, folder)
                if d is not None and (d / f"{ctrlr}.cfg").is_file():
                    self._read_wide(d / f"{ctrlr}.cfg", f"{base.strip()}\\{ctrlr}.cfg")
                    break
        default_cfg = self._cfgs.get("default.cfg")
        if default_cfg is not None:
            self._read_wide(default_cfg, f"{self.cfg_label}\\{default_cfg.name}")

    def _read_wide(self, path: Path, label: str) -> None:
        """Pedal increments of a file's ``default`` section (later files win)."""
        root = _mame_cfg_root(path)
        if root is None:
            return
        for system in root.iter("system"):
            if (system.get("name") or "").lower() != "default":
                continue
            for port in system.iter("port"):
                kind = port.get("type") or ""
                if port.get("tag") is not None or not PEDAL.match(kind):
                    continue
                for node in port.findall("newseq"):
                    if (node.get("type") or "").lower() == "increment" and (node.text or "").strip():
                        self._wide[kind] = mame_binding(node.text, label)

    def folder_binding(self, kind: str) -> Binding:
        """A pedal type's folder-wide increment."""
        if kind in self._wide:
            return self._wide[kind]
        player, pedal = _pedal_order(kind)
        if player <= _BUILT_IN_KEY_PLAYERS:
            return BUILT_IN
        button = {"": 1, "2": 2, "3": 3}.get(pedal, 1)
        return Binding(seq=f"JOYCODE_{player}_BUTTON{button}", source="", has_key=False, lost=False)

    def game(self, game: str) -> Optional[GameKeys]:
        """The game's pedals and keys, or None when its cfg names no pedal."""
        low = game.lower()
        path = self._cfgs.get(f"{low}.cfg")
        if path is None or low == "default":
            return None
        root = _mame_cfg_root(path)
        if root is None:
            return None
        system = next((s for s in root.iter("system") if (s.get("name") or "").lower() == low), None)
        if system is None:
            return None
        fields = _fields(system)
        pedals = [f for f in fields if PEDAL.match(f.kind)]
        if not pedals:
            return None
        label = f"{self.cfg_label}\\{path.name}"
        found = GameKeys(game=game, cfg=label,
                         pedals=sorted({f.kind for f in pedals}, key=_pedal_order))
        for f in pedals:
            seq = f.seqs.get("increment")
            if seq is None:
                found.as_folder.add(f.kind)
                continue
            own = mame_binding(seq, label)
            if own.has_key:
                continue
            if own.lost or self.folder_binding(f.kind).has_key:
                found.no_key.append((f, own))
            else:
                found.as_folder.add(f.kind)

        users: dict[str, list[Field]] = {}
        for f in fields:
            kinds = ("increment", "decrement") if _ANALOG.match(f.kind) else ("standard",)
            for seq_type in kinds:
                for key in single_keys(f.seqs.get(seq_type, "")):
                    bucket = users.setdefault(key, [])
                    if not any(x is f for x in bucket):
                        bucket.append(f)
        for key in sorted(users):
            if len({f.kind for f in users[key]}) > 1:
                found.two_jobs.append((key, users[key]))
        return found

    def pedal_fix(self) -> str:
        return (f"in the game, open MAME's menu (Tab) > Input (this Machine) and give the pedal's "
                f"Inc entry a key; or with MAME closed, put a key (KEYCODE_B, say) in that <port>'s "
                f"<newseq type=\"increment\"> in {self.cfg_label}\\<game>.cfg, or delete that "
                f"<newseq> so {self.cfg_label}\\default.cfg applies; MAME rewrites the cfg as the "
                "game exits")

    def two_jobs_fix(self) -> str:
        return (f"give one of them a key nothing else in the game uses: in the game, Tab > Input "
                f"(this Machine), or with MAME closed in that <port>'s <newseq> in "
                f"{self.cfg_label}\\<game>.cfg (NONE for a button the game doesn't need)")
