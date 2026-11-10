"""The programs HyperSpin's Startup Script starts with HyperSpin.

HyperSpin runs one "Startup Program" when it opens: ``Settings\\Settings.ini``
``[Startup Program]`` ``Executable`` in ``Working_Directory`` (HyperHQ sets
it).  On many cabinets that is the community "HyperSpin Startup Script", an
AutoHotkey tool that reads the ``.ini`` of the same name beside it and starts
``[Startup]`` ``Program_To_Run_Target_N`` (in ``Program_To_Run_Working_Dir_N``,
shown as ``Program_To_Run_MaxMinHide_N``) for N = 1, 2, … up to the first
number that is missing; anything after a gap never starts.  Its ``[Exit]``
section has its own numbered keys, which nothing here touches.

`install-tools --tool idle-tour --apply` adds the idle tour to that list and
`uninstall-tools` takes it out again; `doctor` reads it.  Edits keep every
other byte of the file (encoding, BOM, line ends, comments, key order).
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from ._text import read_editable_text, write_windows_text
from ._utils import unique_path

SECTION = "Startup"
_KEY = re.compile(r"^(\s*Program_To_Run_(Target|Working_Dir|MaxMinHide)_)(\d+)(\s*=)(.*?)(\r?\n)?$",
                  re.IGNORECASE | re.DOTALL)
_FIELDS = {"target": "Target", "working_dir": "Working_Dir", "maxminhide": "MaxMinHide"}


class StartupScriptError(Exception):
    """The Startup Script's list can't be changed safely; the message says why."""


class Entry(NamedTuple):
    number: int
    target: str
    working_dir: str
    show: str


class Script(NamedTuple):
    """Where HyperSpin's Startup Script settings are, or why they weren't found."""
    path: Optional[Path]
    program: str          # the Startup Program as HyperSpin's Settings.ini names it
    problem: str = ""


def find(hyperspin_dir) -> Script:
    """The INI of HyperSpin's Startup Program, if that program is a Startup
    Script (its INI has a ``[Startup]`` section)."""
    if not hyperspin_dir:
        return Script(None, "", "hyperspin_dir is not set")
    from .rocketlauncher import _read_rl_ini

    hs = Path(hyperspin_dir)
    program = _read_rl_ini(hs / "Settings" / "Settings.ini").get("startup program", {})
    exe = program.get("executable", "").strip().strip('"')
    if not exe:
        return Script(None, "", "HyperSpin has no Startup Program (Settings\\Settings.ini "
                                "[Startup Program] Executable is empty)")
    folder = program.get("working_directory", "").strip().strip('"')
    if len(folder) > 3:          # HyperHQ ends it with a backslash; keep a bare "D:\"
        folder = folder.rstrip("\\/")
    base = Path(folder) if folder else hs
    if not base.is_absolute():
        base = hs / base
    exe_path = Path(exe) if Path(exe).is_absolute() else base / exe
    ini = exe_path.with_suffix(".ini")
    if not ini.is_file():
        return Script(None, exe, f"HyperSpin's Startup Program is {exe}, but {ini} doesn't exist")
    if section_bounds(read_editable_text(ini).splitlines(keepends=True), SECTION) is None:
        return Script(None, exe, f"{ini} has no [Startup] section: {exe} isn't the HyperSpin Startup Script")
    return Script(ini, exe)


def section_bounds(lines, name: str) -> "Optional[tuple[int, int]]":
    """``(header, end)`` line indexes of the first ``[name]`` section (any case)."""
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and "]" in s:
            if start is not None:
                return start, i
            if s[1:s.rindex("]")].strip().lower() == name.lower():
                start = i
    return (start, len(lines)) if start is not None else None


def _keys(lines, bounds):
    """``(index, match)`` for each Program_To_Run_* key line in *bounds*."""
    if bounds is None:
        return []
    out = []
    for i in range(bounds[0] + 1, bounds[1]):
        m = _KEY.match(lines[i])
        if m:
            out.append((i, m))
    return out


def entries(text: str) -> "list[Entry]":
    """The ``[Startup]`` entries in number order (the first of a repeated key wins)."""
    lines = text.splitlines(keepends=True)
    found: dict = {}
    for _, m in _keys(lines, section_bounds(lines, SECTION)):
        fields = found.setdefault(int(m.group(3)), {})
        fields.setdefault(m.group(2).lower(), m.group(5).strip())
    return [Entry(n, f.get("target", ""), f.get("working_dir", ""), f.get("maxminhide", ""))
            for n, f in sorted(found.items())]


def runs_to(items: "list[Entry]") -> int:
    """The last number the Script starts: it stops at the first one missing or blank."""
    targets = {e.number for e in items if e.target}
    n = 0
    while n + 1 in targets:
        n += 1
    return n


def _same_target(a: str, b: str) -> bool:
    return a.strip().strip('"').casefold() == b.strip().strip('"').casefold()


def add(text: str, target: str, working_dir: str, show: str = "Hide") -> "tuple[str, int, str]":
    """*text* with *target* started from *working_dir*: ``(new_text, number, action)``.

    *action* is ``"added"``, ``"updated"`` (it was there with another folder
    or window state) or ``"unchanged"``.  It goes at the first free number;
    raises :class:`StartupScriptError` when entries sit after a gap, since
    filling the gap would start them too.
    """
    lines = text.splitlines(keepends=True)
    bounds = section_bounds(lines, SECTION)
    if bounds is None:
        raise StartupScriptError("no [Startup] section")
    items = entries(text)
    last = runs_to(items)
    mine = [e for e in items if _same_target(e.target, target)]
    if mine:
        entry = mine[0]
        if entry.number > last:
            raise StartupScriptError(
                f"{target} is entry {entry.number}, after a gap at {last + 1}: the Startup Script "
                f"stops at the first missing number, so it never starts. Number the "
                f"[Startup] entries 1, 2, 3 … without gaps, then run this again")
        if entry.working_dir == working_dir and entry.show.lower() == show.lower():
            return text, entry.number, "unchanged"
        number, action = entry.number, "updated"
    else:
        after = [e.number for e in items if e.number > last and e.target]
        if after:
            raise StartupScriptError(
                f"[Startup] entry {after[0]} comes after a gap at {last + 1}: the Startup Script "
                f"stops at the first missing number, so it never starts, and adding at {last + 1} "
                f"would start it again. Number the entries 1, 2, 3 … without gaps, then run this again")
        number, action = last + 1, "added"
    values = {"target": target, "working_dir": working_dir, "maxminhide": show}
    keys = _keys(lines, bounds)
    for i, m in keys:   # fill or correct this number's existing keys in place
        if int(m.group(3)) == number and m.group(2).lower() in values:
            field = m.group(2).lower()
            lines[i] = f"{m.group(1)}{m.group(3)}{m.group(4)}{values.pop(field)}{m.group(6) or ''}"
    if values:
        # New keys go after the section's last Program_To_Run line, or its last
        # non-blank line, before any blank lines that end it.
        if keys:
            at = keys[-1][0]
        else:
            at = bounds[0]
            for i in range(bounds[0] + 1, bounds[1]):
                if lines[i].strip():
                    at = i
        newline = "\r\n" if "\r\n" in text or not text else "\n"
        if not lines[at].endswith(("\n", "\r")):
            lines[at] += newline
        new = [f"Program_To_Run_{_FIELDS[f]}_{number}={v}{newline}" for f, v in values.items()]
        lines[at + 1:at + 1] = new
    return "".join(lines), number, action


def remove(text: str, target: str) -> "tuple[str, list[int]]":
    """*text* without the ``[Startup]`` entries that start *target*, the later
    entries numbered down so the list stays without gaps: ``(new_text, removed)``."""
    lines = text.splitlines(keepends=True)
    bounds = section_bounds(lines, SECTION)
    removed = sorted({e.number for e in entries(text) if _same_target(e.target, target)})
    if not removed:
        return text, []
    drop = set()
    for i, m in _keys(lines, bounds):
        n = int(m.group(3))
        if n in removed:
            drop.add(i)
            continue
        shift = sum(1 for r in removed if r < n)
        if shift:
            lines[i] = f"{m.group(1)}{n - shift}{m.group(4)}{m.group(5)}{m.group(6) or ''}"
    return "".join(line for i, line in enumerate(lines) if i not in drop), removed


def backup(path: Path, config) -> Optional[Path]:
    """Copy *path* to ``<stem>.<YYYYMMDD_HHMMSS>.bak`` (beside it, or in
    ``backup_dir\\HyperSpin``) when ``backup_before_modify`` is on, as the
    database writers do, so ``spindoctor backup sidecar`` finds it."""
    if not getattr(config, "backup_before_modify", True) or not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = getattr(config, "backup_dir", "")
    if folder:
        target = Path(folder) / "HyperSpin" / f"{path.stem}.{stamp}.bak"
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = path.with_suffix(f".{stamp}.bak")
    target = unique_path(target)
    shutil.copy2(path, target)
    return target


def write(path: Path, text: str) -> None:
    """Write *text* over *path*, keeping its encoding and BOM."""
    write_windows_text(path, text)
