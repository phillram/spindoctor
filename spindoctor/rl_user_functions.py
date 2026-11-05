"""Programs started from RocketLauncher User Functions.

RocketLauncher runs AutoHotkey "User Functions" files around every launch:
``Lib\\User Functions\\Global.ahk`` for every system, ``<System>.ahk`` for one
system, ``<System>\\<Game>.ahk`` for one game, and ``Emulators\\<Emulator>.ahk``
(or ``<System>\\Emulators\\<Emulator>.ahk``) for one emulator.  Cabinets use
them to start helper programs around a game: gun software, key mappers,
launchers.  Two mistakes there stay invisible until someone plays the game:

* A ``Run`` line names a program that isn't there any more (moved,
  uninstalled, archived).  AutoHotkey then shows "Failed attempt to launch
  program or document" and ends the running thread, so the launch stops at
  that line.
* A key mapper (JoyToKey, Xpadder, antimicro) stays running in the front end:
  it's started for a game and never closed, or started as the game ends to
  switch to a "front end" profile.  Back in HyperSpin it turns pad presses
  into keys as well, so when DS4Windows Auto Profiles (or another mapper) map
  the same pad, every press arrives twice.

:func:`scan_user_functions` finds both and reads each file once;
``doctor``'s User Functions check (:func:`spindoctor.health.check_user_functions`)
reports them.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Iterator, Optional

from .lightgun import (
    _AHK_COMMENT_RE,
    _AHK_RUN_RE,
    _AHK_SHELL_RE,
    _AHK_TARGET_RE,
    UserFunctionsIndex,
    _read_ahk,
)

# Key mappers by executable name (lower case) -> the name shown.
KEYMAPPERS = {
    "joytokey.exe": "JoyToKey",
    "joy2key.exe": "JoyToKey",
    "xpadder.exe": "Xpadder",
    "antimicro.exe": "antimicro",
    "antimicrox.exe": "antimicroX",
}

# User Functions methods RocketLauncher calls once the game has ended.
EXIT_METHODS = frozenset({"stopuserfeatures", "postexit"})

# Finding kinds.
MISSING = "missing"
MAPPER_AT_EXIT = "mapper at exit"
MAPPER_LEFT_RUNNING = "mapper left running"

# A method header, "PostExit() {" (the "{" may be on the next line).  Calls
# such as "RLLog.Info(...)" have a dot, so they don't match; control-flow
# words are excluded.
_METHOD_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\([^()]*\)\s*(\{)?\s*$")
_NOT_METHODS = frozenset({"if", "while", "for", "loop", "switch", "catch",
                          "return", "until", "else"})
_URL_RE = re.compile(r"^\s*[a-z][a-z0-9+.-]*://", re.IGNORECASE)


@dataclass(frozen=True)
class RunLine:
    """One ``Run`` / ``RunWait`` line of a User Functions file."""
    line: int          # 1-based line number
    method: str        # lower-cased method it's in ("postexit"), "" outside one
    program: str       # the program as written, without arguments; "" if unreadable
    arguments: str     # the rest of the target ("Hyperspin" in "JoyToKey.exe Hyperspin")
    working_dir: str   # the WorkingDir parameter when written out, else ""

    @property
    def exe(self) -> str:
        """The program's file name, lower-cased (``"joytokey.exe"``)."""
        return PureWindowsPath(self.program).name.lower() if self.program else ""

    @property
    def at_exit(self) -> bool:
        return self.method in EXIT_METHODS


@dataclass(frozen=True)
class Finding:
    """One problem in one User Functions file."""
    kind: str      # MISSING, MAPPER_AT_EXIT or MAPPER_LEFT_RUNNING
    line: int
    program: str
    text: str      # one line for doctor
    fix: str


def code_lines(text: str) -> Iterator[tuple[int, str, str]]:
    """``(line number, method, code)`` for each line of AHK *text* that holds
    code, with comments and ``/* ... */`` blocks removed.  *method* is the
    lower-cased name of the method the line is in, ``""`` outside one."""
    method = ""
    pending = ""  # a method header whose "{" is on the next line
    in_block = False
    for number, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if in_block:
            in_block = not (s.startswith("*/") or s.endswith("*/"))
            continue
        if s.startswith("/*"):
            in_block = not (len(s) >= 4 and s.endswith("*/"))
            continue
        code = _AHK_COMMENT_RE.split(line, maxsplit=1)[0]
        if not code.strip():
            continue
        if pending:
            if code.strip() == "{":
                method, pending = pending, ""
                continue
            pending = ""
        m = _METHOD_RE.match(code)
        if m and m.group(1).lower() not in _NOT_METHODS:
            if m.group(2):
                method = m.group(1).lower()
                continue
            pending = m.group(1).lower()
        yield number, method, code


def _split_target(target: str) -> tuple[str, str]:
    """``(program, rest)`` for an unquoted Run target.  A first word with no
    folder or extension is a command found on PATH (``taskkill /im x.exe``,
    whose ``x.exe`` is only an argument); otherwise the program runs to the
    first ``.exe`` / ``.bat`` / ``.ahk`` / ... (paths may hold spaces)."""
    if _URL_RE.match(target):  # a web page, opened in the browser
        return "", ""
    first = target.split(None, 1)[0].split(",", 1)[0] if target.strip() else ""
    if first and not re.search(r"[\\/.%]", first):
        return first, target[target.index(first) + len(first):]
    launched = _AHK_TARGET_RE.match(target)
    if not launched:
        return "", ""
    return launched.group(0), target[launched.end():]


def parse_run(code: str) -> Optional[tuple[str, str, str]]:
    """``(program, arguments, working_dir)`` for a Run / RunWait line, or None
    when *code* isn't one.  *program* is ``""`` when the target is an
    expression, or names no ``.exe`` / ``.bat`` / ``.ahk`` / ... file."""
    run = _AHK_RUN_RE.match(code)
    if not run:
        return None
    function_form = code[run.end() - 1] == "("
    rest = code[run.end():].lstrip()
    rest = _AHK_SHELL_RE.sub("", rest, count=1)
    if rest.lower().startswith("*runas "):
        rest = rest[7:].lstrip()
    if rest.startswith("% "):  # an expression: only known at launch
        return "", "", ""
    if function_form:
        # Run("target", "WorkingDir"): the quoted string is the whole target.
        if not rest.startswith('"'):
            return "", "", ""
        target, _, after = rest[1:].partition('"')
        program, arguments = _split_target(target)
        tail = after.lstrip().lstrip(",").strip()
        working_dir = tail[1:].partition('"')[0] if tail.startswith('"') else ""
        return program.strip(), arguments.strip(), working_dir.strip()
    if rest.startswith('"'):
        program, _, after = rest[1:].partition('"')
    else:
        program, after = _split_target(rest)
        if not program:
            return "", "", ""
    # Command form: Run, Target [, WorkingDir, Options, OutputVarPID]
    arguments, _, tail = after.partition(",")
    working_dir = tail.partition(",")[0].strip().strip('"')
    return program.strip(), arguments.strip(), working_dir


def _checkable(path: str) -> Optional[Path]:
    """*path* as a Path when it's absolute and can be checked here: a Windows
    drive or UNC path only on Windows, a POSIX path anywhere."""
    if PureWindowsPath(path).drive:
        return Path(path) if os.name == "nt" else None
    if path.startswith("/"):
        return Path(path)
    return None


def program_exists(program: str, working_dir: str = "") -> Optional[bool]:
    """Whether *program* is on disk, or None when that can't be told.

    Only plain paths are checked: a full path (``D:\\Tools\\x.exe``), or a
    relative one next to a full *working_dir* (AutoHotkey's
    ``Run, x.exe, D:\\Tools`` starts ``D:\\Tools\\x.exe``).  A bare name with
    no working folder may be found on PATH, and anything holding a
    ``%variable%`` is only known at launch, so those are None.
    """
    if not program or "%" in program or "%" in working_dir:
        return None
    path = _checkable(program)
    if path is None and working_dir and not program.startswith(("\\", "/")):
        base = _checkable(working_dir)
        if base is not None:
            path = base.joinpath(*PureWindowsPath(program).parts)
    if path is None:
        return None
    return path.exists()


@dataclass
class _File:
    runs: list[RunLine]
    # Lower-cased code of each line in an exit method, with the program it
    # runs when it's a Run line ("" otherwise).
    exit_lines: list[tuple[str, str]]


def _read(index: UserFunctionsIndex, key: str) -> _File:
    try:
        text = _read_ahk(index.files[key])
    except OSError:
        text = ""
    runs: list[RunLine] = []
    exit_lines: list[tuple[str, str]] = []
    for number, method, code in code_lines(text):
        parsed = parse_run(code)
        run = RunLine(number, method, *parsed) if parsed is not None else None
        if run is not None:
            runs.append(run)
        if method in EXIT_METHODS:
            exit_lines.append((code.lower(), run.exe if run is not None else ""))
    return _File(runs, exit_lines)


def _system_of(key: str) -> str:
    """The lower-cased system a file belongs to, ``""`` for ``Global.ahk``
    and the shared ``Emulators\\`` files."""
    parts = key.split("/")
    if len(parts) == 1:
        return "" if parts[0] == "global.ahk" else parts[0][:-4]
    return "" if parts[0] == "emulators" else parts[0]


def scan_user_functions(index: UserFunctionsIndex,
                        emulator_systems: Optional[dict[str, set[str]]] = None,
                        ) -> dict[str, list[Finding]]:
    """Problems in every User Functions file, keyed like ``index.files``.

    A file is listed when a ``Run`` line names a program that isn't there, or
    starts a key mapper that keeps running after the game: started in an exit
    method (``PostExit()`` / ``StopUserFeatures()``), or started elsewhere and
    never closed.  A close is any line in an exit method that names the
    mapper's program (``Process, Close, JoyToKey.exe``, a ``WinClose`` or a
    ``taskkill``), in the same file, its system's file or ``Global.ahk``.  For
    a shared ``Emulators\\<Emulator>.ahk``, *emulator_systems* (lower-cased
    emulator -> the systems that launch with it) lets the systems' own files
    count, when every one of them closes it.
    """
    files = {key: _read(index, key) for key in index.files}

    def closes(key: str, exe: str) -> bool:
        """Whether an exit method in the file at *key* names *exe*'s program
        on a line that doesn't start it (a Process Close, WinClose, taskkill)."""
        f = files.get(key)
        stem = exe[:-4]
        return f is not None and any(stem in line and run_exe != exe
                                     for line, run_exe in f.exit_lines)

    findings: dict[str, list[Finding]] = {}
    for key in sorted(files):
        f = files[key]
        found: list[Finding] = []
        at_exit = {r.exe for r in f.runs if r.at_exit and r.exe in KEYMAPPERS}
        for r in f.runs:
            file_name = PureWindowsPath(r.program).name
            if program_exists(r.program, r.working_dir) is False:
                where = (os.path.join(r.working_dir, r.program)
                         if r.working_dir and _checkable(r.program) is None else r.program)
                found.append(Finding(
                    MISSING, r.line, where,
                    f"line {r.line} runs {where}, which isn't there: AutoHotkey "
                    "stops with an error when it reaches this line",
                    f"correct the path on line {r.line}, or comment the line out "
                    f"(;) if {file_name} is gone for good",
                ))
                continue  # a missing mapper can't be left running
            if r.exe not in KEYMAPPERS:
                continue
            name = KEYMAPPERS[r.exe]
            fix = (f"close {name} in PostExit() (Process, Close, {file_name}), or stop "
                   "starting it if DS4Windows Auto Profiles already map the pad in HyperSpin")
            if r.at_exit:
                profile_name = r.arguments.strip().strip('"')
                profile = f' (profile "{profile_name}")' if profile_name else ""
                found.append(Finding(
                    MAPPER_AT_EXIT, r.line, r.program,
                    f"line {r.line} starts {name} as the game ends{profile}, so it "
                    "keeps running in HyperSpin",
                    fix,
                ))
                continue
            if r.exe in at_exit:
                continue  # the at-exit row already covers it
            system = _system_of(key)
            closers = [key, "global.ahk"] + ([f"{system}.ahk"] if system else [])
            if any(closes(k, r.exe) for k in closers):
                continue
            if key.startswith("emulators/") and emulator_systems:
                users = emulator_systems.get(key.split("/", 1)[1][:-4], set())
                if users and all(closes(f"{s}.ahk", r.exe) for s in users):
                    continue
            found.append(Finding(
                MAPPER_LEFT_RUNNING, r.line, r.program,
                f"line {r.line} starts {name} and nothing closes it when the game "
                "ends, so it keeps running in HyperSpin",
                fix,
            ))
        if found:
            findings[key] = found
    return findings
