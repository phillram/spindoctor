"""Daphne's keyboard file, ``dapinput.ini``, and its 0 key-slot trap.

Daphne 1.0.x, and the Singe builds made from it (American Laser Games,
WoW Action Max), use SDL 1.2 and read each ``[KEYBOARD]`` line as
``KEY_QUIT = 27 0 0``: two keyboard keys (SDL 1.2 key codes), then a joystick
button.  A 0 in a key slot doesn't mean "no key".  SDL 1.2 reports every key
it has no name for, such as the volume and media keys a keyboard or an
I-PAC's shift functions send, as ``SDLK_UNKNOWN``, which is 0, and Daphne
compares each key press with both key slots of every action.  So one Volume Up
press sets off every action with a 0 slot: quit, pause, service, test, reset,
tilt and any button whose second slot was left at 0.  (A 0 joystick button is
fine: Daphne only maps buttons above 0.)

Actions the file leaves out keep Daphne's built-in keys, and most of those
have a 0 second slot.  Daphne also stops reading the file at the first line it
can't parse, and ignores the whole file when it never finds the ``[KEYBOARD]``
line, so the built-in keys apply to everything after that point.

Putting a key nothing sends, 296 (F15), in every 0 key slot removes the trap.
:func:`read_key_file` follows Daphne's own reader (``CFG_Keys``) and reports
which actions are left on 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

KEY_FILE = "dapinput.ini"

# SDLK_F15 in SDL 1.2: a real key code that no panel or keyboard sends.
FILLER = 296

# Daphne 1.0's built-in keys, read from daphne.exe 1.0.10 (the Singe builds
# carry the same table).  An action missing from dapinput.ini keeps these.
DEFAULT_KEYS = {
    "KEY_UP": (273, 264),          # Up, keypad 8
    "KEY_LEFT": (276, 260),
    "KEY_DOWN": (274, 258),
    "KEY_RIGHT": (275, 262),
    "KEY_START1": (49, 0),         # 1
    "KEY_START2": (50, 0),         # 2
    "KEY_BUTTON1": (32, 306),      # Space, left Ctrl
    "KEY_BUTTON2": (308, 0),       # left Alt
    "KEY_BUTTON3": (304, 0),       # left Shift
    "KEY_COIN1": (53, 99),         # 5, C
    "KEY_COIN2": (54, 0),
    "KEY_SKILL1": (267, 0),        # keypad / * -
    "KEY_SKILL2": (268, 0),
    "KEY_SKILL3": (269, 0),
    "KEY_SERVICE": (57, 0),        # 9
    "KEY_TEST": (283, 0),          # F2
    "KEY_RESET": (284, 0),         # F3
    "KEY_SCREENSHOT": (293, 292),  # F12, F11
    "KEY_QUIT": (27, 113),         # Esc, Q
    "KEY_PAUSE": (112, 0),         # P
    "KEY_CONSOLE": (96, 0),        # `
    "KEY_TILT": (116, 0),          # T
}

# KEY_CONSOLE does nothing in Daphne 1.0, so a 0 there is harmless.
IGNORED = frozenset({"KEY_CONSOLE"})

# The actions a stray key press hurts most, listed first.
PRIORITY = ("KEY_QUIT", "KEY_PAUSE", "KEY_SERVICE", "KEY_TEST", "KEY_RESET", "KEY_TILT",
            "KEY_COIN1", "KEY_COIN2", "KEY_START1", "KEY_START2", "KEY_SCREENSHOT")

_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")


@dataclass
class KeySlots:
    """One action's two key slots, as Daphne ends up with them."""
    action: str
    keys: tuple[int, int]
    joystick: str = "0"
    line: int = 0               # line number in the file; 0 = Daphne's built-in keys

    def fixed(self) -> str:
        """The line with every 0 key slot filled, as it should read."""
        a, b = (k or FILLER for k in self.keys)
        return f"{self.action} = {a} {b} {self.joystick}"


@dataclass
class KeyFileReport:
    """What Daphne reads from one ``dapinput.ini``."""
    path: Path
    exists: bool = True
    header: bool = True         # a [KEYBOARD] line was found
    bom: bool = False           # the file starts with a byte-order mark
    stopped: str = ""           # why Daphne stopped reading early ...
    stopped_line: int = 0       # ... at this line
    slots: dict[str, KeySlots] = field(default_factory=dict)

    def zero_slots(self) -> list[KeySlots]:
        """Actions with a 0 key slot, the ones that hurt most first."""
        hits = [s for a, s in self.slots.items() if a not in IGNORED and 0 in s.keys]
        order = list(PRIORITY) + [a for a in DEFAULT_KEYS if a not in PRIORITY]
        return sorted(hits, key=lambda s: order.index(s.action))


def _atoi(word: str) -> int:
    """C ``atoi``: the leading number, or 0 (so ``none`` in a key slot is 0)."""
    m = re.match(r"\s*([+-]?\d+)", word)
    return int(m.group(1)) if m else 0


def read_key_file(path: Path) -> KeyFileReport:
    """Read *path* the way Daphne 1.0's ``CFG_Keys`` does.

    Lines before ``[KEYBOARD]`` and from ``END`` on are ignored, blank lines
    are skipped, and each other line must be ``<name> = <key> <key> <button>``
    (whitespace-separated, three numbers) with a known name, or Daphne stops
    reading there.  Daphne doesn't skip a byte-order mark, so a file saved as
    UTF-8 with BOM or as Unicode never matches ``[KEYBOARD]`` on its first line.
    Every action the file doesn't set keeps its built-in keys.
    """
    report = KeyFileReport(path=path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = None
        report.exists = False
    if data is not None:
        report.bom = data.startswith(_BOMS)
        # Bytes as Daphne sees them; a line ends at CR, LF or CRLF.
        lines = re.split(r"\r\n|\r|\n", data.decode("latin-1"))
        start = next((i for i, line in enumerate(lines)
                      if line.strip().upper() == "[KEYBOARD]"), None)
        report.header = start is not None
        for number, line in enumerate(lines[start + 1:] if start is not None else [],
                                      start=(start or 0) + 2):
            words = line.split()
            if not words:
                continue
            if words[0].upper() == "END":
                break
            name = words[0].upper()
            if len(words) < 5 or words[1] != "=":
                report.stopped = f"not '<name> = <key> <key> <button>': {line.strip()}"
            elif name not in DEFAULT_KEYS:
                report.stopped = f"an action Daphne doesn't know: {words[0]}"
            if report.stopped:
                report.stopped_line = number
                break
            report.slots[name] = KeySlots(name, (_atoi(words[2]), _atoi(words[3])),
                                          words[4], number)
    for action, keys in DEFAULT_KEYS.items():
        report.slots.setdefault(action, KeySlots(action, keys))
    return report


def label(action: str) -> str:
    """``KEY_QUIT`` -> ``quit``."""
    return action[4:].lower()
