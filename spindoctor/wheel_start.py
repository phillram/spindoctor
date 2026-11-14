"""Where a HyperSpin wheel starts: on a random game, the last game, or the first.

HyperSpin reads two keys from the ``[navigation]`` section of a wheel's
``<hyperspin_dir>\\Settings\\<System>.ini`` (HyperHQ's wheel settings write
them):

* ``random_game=true``: a random game each time the wheel opens, so it lands
  on a different letter every time;
* ``use_last_game=true``: the game it was on last time, which HyperSpin keeps
  in ``last_game=`` in the same section;
* both ``false``, or missing: the wheel's first game.

:func:`read_wheel_start` reports which one a file asks for, and
:func:`set_wheel_start` changes it.  Only those two keys' values change: every
other byte of the file stays (encoding, BOM, comments, other keys, the keys'
spelling, spacing and line ends).  HyperSpin writes these files itself (it
keeps ``last_game=`` there), so they are changed only while it's closed.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from ._text import read_editable_text, write_windows_text
from ._utils import unique_path

SECTION = "navigation"
RANDOM_KEY = "random_game"
LAST_KEY = "use_last_game"

#: The modes a wheel can be set to, in the order the help lists them.
MODES = ("first", "last", "random")

#: What each mode writes.
_VALUES = {
    "first": {RANDOM_KEY: "false", LAST_KEY: "false"},
    "last": {RANDOM_KEY: "false", LAST_KEY: "true"},
    "random": {RANDOM_KEY: "true", LAST_KEY: "false"},
}

#: How each mode reads in a sentence ("starts on ...").  ``both`` is a file
#: with both keys on, which HyperHQ doesn't write; setting a mode clears it.
DESCRIPTIONS = {
    "first": "the first game",
    "last": "the last game it was on",
    "random": "a random game",
    "both": "random_game and use_last_game both on",
}

#: Files in HyperSpin's Settings folder that belong to HyperSpin itself, not
#: to a game wheel (lower case, without ``.ini``).
NOT_WHEELS = frozenset({"settings", "main menu", "global plugins", "hyperlaunchhq"})


class WheelStart(NamedTuple):
    """What a wheel's settings file asks HyperSpin for."""
    random_game: bool
    use_last_game: bool

    @property
    def mode(self) -> str:
        """``first``, ``last``, ``random``, or ``both`` when both keys are on."""
        if self.random_game and self.use_last_game:
            return "both"
        if self.random_game:
            return "random"
        return "last" if self.use_last_game else "first"


class Change(NamedTuple):
    """One settings file :func:`set_wheel_start` changed."""
    old: str                    # the mode before
    new: str
    backup: Optional[Path]      # the copy made first, if any


def _section(stripped: str) -> Optional[str]:
    """The section a ``[name]`` line opens, in lower case; None for other lines."""
    if stripped.startswith("[") and "]" in stripped:
        return stripped[1:stripped.index("]")].strip().lower()
    return None


def _key(stripped: str) -> Optional[str]:
    """The key of a ``key=value`` line, in lower case; None for other lines."""
    if "=" not in stripped or stripped.startswith((";", "#")):
        return None
    return stripped.split("=", 1)[0].strip().lower()


def read_text(text: str) -> WheelStart:
    """What *text* asks for: the first copy of each key in a ``[navigation]``
    section, in any case.  ``true`` in any case is on; anything else, or a
    missing key, is off."""
    found: dict = {}
    ours = False
    for line in text.splitlines():
        s = line.strip()
        name = _section(s)
        if name is not None:
            ours = name == SECTION
            continue
        key = _key(s) if ours else None
        if key in (RANDOM_KEY, LAST_KEY) and key not in found:
            found[key] = s.split("=", 1)[1].strip().lower() == "true"
    return WheelStart(found.get(RANDOM_KEY, False), found.get(LAST_KEY, False))


_VALUE = re.compile(r"([^=]*=[ \t]*)(.*?)([ \t]*(?:\r\n|\n|\r)?)\Z", re.DOTALL)


def set_text(text: str, mode: str) -> str:
    """*text* asking for *mode* (one of :data:`MODES`).

    Every copy of the two keys in every ``[navigation]`` section gets the
    mode's value, so HyperSpin reads it whichever copy it uses; only the value
    changes, and only where it differs.  A key that isn't in any such section
    goes after the first one's last line, and a missing section at the end,
    in the file's own line ends.  *text* has no BOM
    (:func:`spindoctor._text.read_editable_text`).
    """
    values = _VALUES[mode]
    lines = text.splitlines(keepends=True)
    eol = "\n" if "\n" in text and "\r\n" not in text else "\r\n"
    missing = dict(values)
    first_end: Optional[int] = None    # after the first [navigation] section's last line
    ours = in_first = False
    for i, line in enumerate(lines):
        s = line.strip()
        name = _section(s)
        if name is not None:
            ours = name == SECTION
            in_first = ours and first_end is None
            if in_first:
                first_end = i + 1
            continue
        if in_first and s:
            first_end = i + 1
        key = _key(s) if ours else None
        if key not in values:
            continue
        missing.pop(key, None)
        m = _VALUE.match(line)
        if m.group(2).strip().lower() != values[key]:
            lines[i] = m.group(1) + values[key] + m.group(3)
    if missing:
        added = "".join(f"{key}={value}{eol}" for key, value in missing.items())
        if first_end is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += eol
            if lines and lines[-1].strip():
                lines.append(eol)            # a blank line between sections, as HyperHQ writes
            lines.append(f"[{SECTION}]{eol}{added}")
        else:
            if not lines[first_end - 1].endswith(("\n", "\r")):
                lines[first_end - 1] += eol
            lines.insert(first_end, added)
    return "".join(lines)


def read_wheel_start(path: Path) -> WheelStart:
    """What the settings file *path* asks for.  Raises ``OSError`` when it
    can't be read."""
    return read_text(read_editable_text(Path(path)))


def backup_settings_file(path: Path, config) -> Optional[Path]:
    """Copy *path* to ``<name>.<YYYYMMDD_HHMMSS>.bak`` (beside it, or in
    ``backup_dir\\HyperSpin``) when ``backup_before_modify`` is on, so
    ``spindoctor backup sidecar`` finds it.  The name keeps ``.ini`` to tell
    it apart from the backups of the wheel's ``<System>.xml``, which go to the
    same folder under the same stem."""
    if config is None or not getattr(config, "backup_before_modify", True) or not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = getattr(config, "backup_dir", "")
    if folder:
        target = Path(folder) / "HyperSpin" / f"{path.name}.{stamp}.bak"
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = path.with_name(f"{path.name}.{stamp}.bak")
    target = unique_path(target)
    shutil.copy2(path, target)
    return target


def set_wheel_start(path: Path, mode: str, config=None) -> Optional[Change]:
    """Make the settings file *path* ask for *mode*; None when it already does.

    With a *config*, the file is backed up first (:func:`backup_settings_file`).
    Raises ``ValueError`` for a mode not in :data:`MODES` and ``OSError`` when
    the file can't be read or written.
    """
    if mode not in _VALUES:
        raise ValueError(f"not a wheel start: {mode!r} (use {', '.join(MODES)})")
    path = Path(path)
    text = read_editable_text(path)
    old = read_text(text).mode
    if old == mode:
        return None
    backup = backup_settings_file(path, config)
    write_windows_text(path, set_text(text, mode))
    return Change(old, mode, backup)


def settings_files(config) -> "dict[str, Path]":
    """Every ``<hyperspin_dir>\\Settings\\*.ini`` by its wheel name in lower
    case (the folder is read once)."""
    folder = Path(config.hyperspin_dir) / "Settings"
    if not config.hyperspin_dir or not folder.is_dir():
        return {}
    return {p.name[:-4].lower(): p for p in folder.iterdir()
            if p.suffix.lower() == ".ini" and p.is_file()}


def main_menu_wheels(config) -> "list[str]":
    """The wheels on HyperSpin's main menu, in its order (hidden ones too),
    leaving out entries that run a program instead (``exe="true"``, such as
    Search)."""
    from .mainmenu import load_main_menu

    return [e.system for e in load_main_menu(config).entries
            if str((e.extra_attrs or {}).get("exe", "")).strip().lower() != "true"]


class WheelRow(NamedTuple):
    """One wheel in :func:`overview`."""
    name: str                   # as its settings file spells it, else as asked for
    path: Optional[Path]        # its settings file; None when it has none
    mode: Optional[str]         # where it starts; None without a readable file
    error: str = ""             # why the file couldn't be read


def overview(config, names=None) -> "list[WheelRow]":
    """Where each wheel starts: the main menu's wheels (:func:`main_menu_wheels`),
    or the wheels in *names*, each once in any case and in that order.  The
    CLI's listing and the GUI's table both read it here.  Raises ``OSError``,
    ``ValueError`` or ``SyntaxError`` (XML) when the main menu can't be read."""
    files = settings_files(config)
    wanted: dict = {}
    for name in (names if names else main_menu_wheels(config)):
        wanted.setdefault(name.lower(), name)
    rows = []
    for key, name in wanted.items():
        path = files.get(key)
        if path is None:
            rows.append(WheelRow(name, None, None))
            continue
        try:
            rows.append(WheelRow(path.name[:-4], path, read_wheel_start(path).mode))
        except OSError as exc:
            rows.append(WheelRow(path.name[:-4], path, None, str(exc)))
    return rows


def hyperspin_running() -> bool:
    """HyperSpin.exe is running (Windows only; False elsewhere or when the
    process list can't be read)."""
    from . import _win32

    try:
        return any(p.name.lower() == "hyperspin.exe" for p in _win32.list_processes())
    except OSError:                      # _win32.UnsupportedPlatform off Windows
        return False
