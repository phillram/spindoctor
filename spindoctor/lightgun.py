"""Sinden / DemulShooter wiring for lightgun-enabled systems.

RocketLauncher's per-system INI supports ``Pre_Launch_App`` and
``Post_Launch_App`` keys that fire before the emulator starts and after
it exits.  We use that to start DemulShooter with the correct
``-target`` for the system, and to kill it on exit so it doesn't block
the next launch.

Detection runs in two passes:

1.  *File fingerprint* — check for the Sinden software (``Lightgun.exe``
    next to ``Lightgun.exe.config``) and DemulShooter executables in the
    configured tools/emulators trees.  This tells us whether the cabinet
    has the gear at all.

2.  *RL settings / User Functions scan* — for every per-system INI under
    ``RocketLauncher/Settings``, look for a ``DemulShooter``
    ``Pre_Launch_App``; and in ``RocketLauncher/Lib/User Functions``, for
    a line that runs ``Lightgun.exe`` or DemulShooter in the AHK files
    RocketLauncher runs for that system, its games or its emulators.
    Any system already wired either way is treated as lightgun-enabled
    and seeded into the spindoctor config.

``configure --system <name>`` writes/updates the per-system INI.  It
never touches the global module .ahk files (that's where Tur templates
live and breaking those would break every system at once), nor the
User Functions files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .config import Config


# ─── DemulShooter target mapping ──────────────────────────────────────────────
#
# DemulShooter's -target argument identifies the emulator process it should
# attach to.  Mapping HyperSpin/RocketLauncher system names → DemulShooter
# targets is well-defined for the supported emulators.

# Substring → -target value.  First match wins.  Lower-cased.
DEMULSHOOTER_TARGET_MAP: tuple[tuple[str, str], ...] = (
    # MAME
    ("mame", "mame"),
    # Demul (Sega Naomi / Atomiswave / etc.)
    ("naomi", "demul07a"),
    ("atomiswave", "demul07a"),
    ("dreamcast", "demul07a"),
    # Sega Model 2 / 3
    ("model 2", "model2"),
    ("model 3", "supermodel"),
    # Sega Lindbergh
    ("lindbergh", "lindbergh"),
    # Flycast (also runs Naomi/Atomiswave but attach key differs)
    ("flycast", "flycast"),
    # ChiHiro / Triforce
    ("chihiro", "chihiro"),
    ("triforce", "dolphin"),
    # Other lightgun-supported emulators handled by DemulShooter
    ("ringedge", "ringedge2"),
    ("global vr", "globalvr"),
)

# Default extra args for DemulShooter — Sinden-friendly defaults.
# Users can override via spindoctor config (demulshooter_extra_args).
DEFAULT_DEMULSHOOTER_ARGS = "-noresize"


def guess_demulshooter_target(system_name: str) -> Optional[str]:
    """Return the DemulShooter ``-target`` for *system_name*, if known."""
    lower = system_name.lower()
    for hint, target in DEMULSHOOTER_TARGET_MAP:
        if hint in lower:
            return target
    return None


# ─── installation detection ───────────────────────────────────────────────────

@dataclass
class LightgunInstall:
    """What the cabinet has installed for lightgun support."""
    sinden_software_dir: Optional[Path] = None
    demulshooter_exe: Optional[Path] = None
    arcade_guns_dir: Optional[Path] = None
    # Every DemulShooter executable found, in scan order.  More than one
    # means demulshooter_exe is a guess unless demulshooter_path is set.
    demulshooter_candidates: list[Path] = field(default_factory=list)
    demulshooter_from_config: bool = False

    @property
    def has_sinden(self) -> bool:
        return self.sinden_software_dir is not None

    @property
    def has_demulshooter(self) -> bool:
        return self.demulshooter_exe is not None


def detect_lightgun_install(config: Config,
                            extra_roots: Optional[Iterable[Path]] = None
                            ) -> LightgunInstall:
    """Search common locations for Sinden + DemulShooter + Arcade Guns.

    Returns a :class:`LightgunInstall` populated with whichever paths
    were found.  Reuses the same scan roots as :mod:`tools_audit`.

    The Sinden software is recognized by its files (``Lightgun.exe`` next
    to ``Lightgun.exe.config``), not by a folder name: a wheel called
    ``Gun Games (Sinden)`` has "sinden" in its database and media paths.
    A configured ``demulshooter_path`` that exists wins over the scan, so
    ``detect``, ``audit`` and ``configure`` all report the same exe.
    """
    from .tools_audit import default_scan_roots

    install = LightgunInstall()
    roots = list(default_scan_roots(config))
    if extra_roots:
        roots.extend(extra_roots)

    arcadeguns_hints = ("arcade guns", "arcadeguns")
    demul_exes = {"demulshooter.exe", "demulshooterx64.exe"}
    seen: set[str] = set()

    for root in roots:
        if not root.exists():
            continue
        # Bounded walk — Sinden + DemulShooter live ≤4 levels deep.
        for depth, dirpath in _bounded_walk(root, max_depth=4):
            lower = str(dirpath).lower()
            if not install.arcade_guns_dir and any(
                h in lower for h in arcadeguns_hints
            ):
                install.arcade_guns_dir = dirpath
            try:
                files = {f.name.lower(): f for f in dirpath.iterdir() if f.is_file()}
            except OSError:
                continue
            if (not install.sinden_software_dir and "lightgun.exe" in files
                    and "lightgun.exe.config" in files):
                install.sinden_software_dir = dirpath
            for name, f in files.items():
                key = str(f).lower()
                if name in demul_exes and key not in seen:
                    seen.add(key)
                    install.demulshooter_candidates.append(f)

    if install.demulshooter_candidates:
        install.demulshooter_exe = install.demulshooter_candidates[0]
    if config.demulshooter_path:
        forced = Path(config.demulshooter_path)
        if forced.is_file():
            install.demulshooter_exe = forced
            install.demulshooter_from_config = True
    return install


def _bounded_walk(root: Path, max_depth: int):
    """Yield ``(depth, dir)`` for every directory under *root*."""
    import os
    base = len(Path(os.path.abspath(root)).parts)
    for dirpath, dirnames, _ in os.walk(root):
        depth = len(Path(os.path.abspath(dirpath)).parts) - base
        if depth >= max_depth:
            # Don't descend further: without this, os.walk still visits
            # every folder under Program Files and LocalAppData.
            dirnames[:] = []
        yield depth, Path(dirpath)


# ─── per-system audit ─────────────────────────────────────────────────────────

# Both hooks are matched on their own line ([ \t], not \s), so an empty
# key can't take its value from the next line.  Callers strip the value.
DEMULSHOOTER_PRE_RE = re.compile(
    r"^[ \t]*Pre_Launch_App[ \t]*=[ \t]*(?P<value>[^\r\n]*demulshooter[^\r\n]*)",
    re.IGNORECASE | re.MULTILINE,
)
# Only a teardown that names DemulShooter counts: an unrelated
# Post_Launch_App (a resolution reset, say) leaves DemulShooter running.
DEMULSHOOTER_POST_RE = re.compile(
    r"^[ \t]*Post_Launch_App[ \t]*=[ \t]*(?P<value>[^\r\n]*demulshooter[^\r\n]*)",
    re.IGNORECASE | re.MULTILINE,
)
# Any Post_Launch_App: configure overwrites it, whatever it runs.
_POST_LAUNCH_RE = re.compile(
    r"^[ \t]*Post_Launch_App[ \t]*=[ \t]*([^\r\n]*)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class SystemLightgunStatus:
    """Status of DemulShooter wiring for one HyperSpin system."""
    system_name: str
    ini_path: Path
    pre_launch: Optional[str] = None
    post_launch: Optional[str] = None
    target: Optional[str] = None  # parsed from pre_launch -target arg
    # User Functions files with a line that runs Lightgun.exe or DemulShooter
    # for this system, as "Lib\User Functions\..." labels: the system's own
    # file and its emulators' files, then
    # per-game files.
    user_functions: list[str] = field(default_factory=list)
    user_functions_games: list[str] = field(default_factory=list)
    # What those lines run: "lightgun" and/or "demulshooter".
    user_functions_programs: set[str] = field(default_factory=set)
    # An emulator file runs only for games using that emulator. All launch
    # choices must be covered before doctor can call the whole system wired.
    user_functions_system_wide: bool = False

    @property
    def is_wired(self) -> bool:
        return self.pre_launch is not None

    @property
    def wired_via_user_functions(self) -> bool:
        return bool(self.user_functions or self.user_functions_games)

    def user_functions_where(self) -> str:
        """Where the User Functions wiring is, for messages: each system-wide
        file, then the game file or the number of them."""
        parts = list(self.user_functions)
        games = self.user_functions_games
        if len(games) == 1:
            parts.append(games[0])
        elif games:
            folder = games[0].rsplit("\\", 1)[0]
            parts.append(f"{len(games)} game files in {folder}")
        return ", ".join(parts)


def system_settings_ini(rocketlauncher_dir: Path, system_name: str
                        ) -> Optional[tuple[Path, str]]:
    """The RocketLauncher settings file for *system_name* and its main section.

    Folder layout first (``Settings/<System>/Emulators.ini``, ``[ROMS]``),
    then the flat ``Settings/<System>.ini`` (``[Settings]``), as
    :func:`~spindoctor.rocketlauncher.detect_rl_layout` decides.  None when
    the system has neither.
    """
    from .rocketlauncher import detect_rl_layout

    settings = Path(rocketlauncher_dir) / "Settings"
    layout = detect_rl_layout(settings, system_name)
    if layout == "folder":
        return settings / system_name / "Emulators.ini", "ROMS"
    if layout == "flat":
        return settings / f"{system_name}.ini", "Settings"
    return None


# DemulShooter takes -target=<name>; older SpinDoctor versions wrote
# "-target <name>", so both are read.
_TARGET_RE = re.compile(r"-target(?:=|\s+)(\S+)", re.IGNORECASE)


# ─── RocketLauncher User Functions ────────────────────────────────────────────
#
# Many cabinets start the gun software from RocketLauncher User Functions
# instead of a Pre_Launch_App hook: AHK files under Lib\User Functions that
# RL runs for one system (<System>.ahk), one of its games
# (<System>\<Game>.ahk) or one emulator (Emulators\<Emulator>.ahk, or
# <System>\Emulators\<Emulator>.ahk for that system only).  RL matches
# those names case-insensitively.  Global.ahk runs for every system, so it
# can't tell which systems are gun systems and isn't read.

# An AHK comment starts with ";" at the start of a line or after a space
# or tab ("`;" is a literal semicolon).
_AHK_COMMENT_RE = re.compile(r"(?:^|[ \t]);")
# Run / RunWait as a command ("Run, x" or "Run x") or a function ("Run(x)").
_AHK_RUN_RE = re.compile(r"^\s*Run(?:Wait)?\s*[,(\s]", re.IGNORECASE)
# Match the executable being launched, not a taskkill argument, working
# directory, or similarly named file. Paths may contain spaces after the
# first directory separator, as accepted by AHK's Run command.
_GUN_EXE_RE = re.compile(
    r'^(?:[^\s",]+[\\/](?:[^",]*[\\/])?)?(lightgun|demulshooter)(?:x64)?\.exe(?=["\s,)]|$)',
    re.IGNORECASE,
)
_AHK_TARGET_RE = re.compile(
    r'^[^",]*?\.(?:exe|com|bat|cmd|lnk|ahk)(?=["\s,)]|$)', re.IGNORECASE,
)
_AHK_SHELL_RE = re.compile(
    r"^%comspec%[ \t]+/[ck][ \t]+(?:start[ \t]+(?:\"\"[ \t]+)?)?",
    re.IGNORECASE,
)

_DEFAULT_EMULATOR_RE = re.compile(
    r"^[ \t]*Default_Emulator[ \t]*=[ \t]*([^\r\n]*?)[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE,
)
_GAME_EMULATOR_RE = re.compile(
    r"^[ \t]*Emulator[ \t]*=[ \t]*([^\r\n]*?)[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE,
)


def _ahk_code_lines(text: str) -> Iterable[str]:
    """The code on each line of AHK *text*: comments and ``/* … */`` blocks
    removed, blank lines skipped."""
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if in_block:
            in_block = not (s.startswith("*/") or s.endswith("*/"))
            continue
        if s.startswith("/*"):
            in_block = not (len(s) >= 4 and s.endswith("*/"))
            continue
        code = _AHK_COMMENT_RE.split(line, maxsplit=1)[0]
        if code.strip():
            yield code


def _read_ahk(path: Path) -> str:
    """An AHK file's text: UTF-8 with or without a BOM, ANSI, or UTF-16 with
    a BOM.  Bytes that don't decode are replaced, never fatal."""
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


@dataclass
class UserFunctionsIndex:
    """The ``.ahk`` files under ``Lib/User Functions`` RocketLauncher can run.

    *files* maps each file's path relative to that folder, lower-cased and
    ``/``-separated (``"emulators/mame.ahk"``), to the file.  Build it once
    with :func:`index_user_functions` and pass it to every
    :func:`audit_system_wiring` call; each file is read the first time it's
    asked about, and only then.
    """
    root: Path
    files: dict[str, Path] = field(default_factory=dict)
    _programs: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)

    def gun_programs(self, key: str) -> frozenset[str]:
        """``"lightgun"`` / ``"demulshooter"`` for each that the file at *key*
        runs on a line that isn't a comment; empty when it runs neither."""
        if key not in self._programs:
            found: set[str] = set()
            path = self.files.get(key)
            try:
                text = _read_ahk(path) if path is not None else ""
            except OSError:
                text = ""
            for code in _ahk_code_lines(text):
                run = _AHK_RUN_RE.match(code)
                if run:
                    command = code[run.end():].lstrip()
                    command = _AHK_SHELL_RE.sub("", command, count=1)
                    if command.lower().startswith("*runas "):
                        command = command[7:].lstrip()
                    # AHK expression-mode commands may start with "% ".
                    if command.startswith("% "):
                        command = command[2:].lstrip()
                    if command.startswith('"'):
                        target = command[1:].split('"', 1)[0]
                    else:
                        # Stop at the first executable/script, not a later
                        # argument such as taskkill's /IM path.
                        launched = _AHK_TARGET_RE.match(command)
                        target = launched.group(0) if launched else ""
                    exe = _GUN_EXE_RE.fullmatch(target)
                    if exe:
                        found.add(exe.group(1).lower())
            self._programs[key] = frozenset(found)
        return self._programs[key]

    def label(self, key: str) -> str:
        """``Lib\\User Functions\\...`` for the file at *key*, spelled as on disk."""
        rel = self.files[key].relative_to(self.root)
        return "\\".join(("Lib", "User Functions") + rel.parts)


def index_user_functions(rocketlauncher_dir: Path) -> UserFunctionsIndex:
    """List RocketLauncher's User Functions files in one pass.

    Only folder listings are read, never a file per game: ``<System>.ahk``,
    ``<System>/*.ahk`` (games), ``Emulators/*.ahk`` and
    ``<System>/Emulators/*.ahk``.  A missing folder gives an empty index.
    """
    import os

    root = Path(rocketlauncher_dir) / "Lib" / "User Functions"
    index = UserFunctionsIndex(root=root)

    def scan(folder: str, prefix: str, depth: int) -> None:
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            return
        for entry in entries:
            name = entry.name.lower()
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if not is_dir:
                if name.endswith(".ahk"):
                    index.files.setdefault(prefix + name, Path(entry.path))
            elif depth == 0 or (depth == 1 and name == "emulators"):
                scan(entry.path, f"{prefix}{name}/", depth + 1)

    scan(str(root), "", 0)
    return index


def _system_emulators(rocketlauncher_dir: Path, system_name: str, body: str
                      ) -> list[str]:
    """Lower-cased names of the emulators RocketLauncher can launch
    *system_name*'s games with: ``Default_Emulator`` in its settings *body*,
    then each ``Emulator=`` override in ``Settings/<System>/Games.ini``."""
    # Keep an empty default as an uncovered launch choice: overrides alone
    # do not establish system-wide wiring.
    names = [""]
    m = _DEFAULT_EMULATOR_RE.search(body)
    if m:
        names[0] = m.group(1)
    games_ini = Path(rocketlauncher_dir) / "Settings" / system_name / "Games.ini"
    try:
        games = games_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        games = ""
    names += [g.group(1) for g in _GAME_EMULATOR_RE.finditer(games) if g.group(1)]
    return list(dict.fromkeys(n.lower() for n in names))


def _add_user_functions(status: SystemLightgunStatus, index: UserFunctionsIndex,
                        emulators: list[str]) -> None:
    """Record in *status* the User Functions files that start the gun
    software for its system, the system's *emulators* or its games."""
    system = status.system_name.lower()
    system_wide = [f"{system}.ahk"]
    for emu in emulators:
        if emu:
            system_wide += [f"emulators/{emu}.ahk", f"{system}/emulators/{emu}.ahk"]
    games = sorted(k for k in index.files
                   if k.startswith(system + "/") and "/" not in k[len(system) + 1:])
    for keys, labels in ((system_wide, status.user_functions),
                         (games, status.user_functions_games)):
        for key in keys:
            programs = index.gun_programs(key) if key in index.files else frozenset()
            if programs:
                labels.append(index.label(key))
                status.user_functions_programs.update(programs)
    status.user_functions_system_wide = bool(
        index.gun_programs(f"{system}.ahk")
        or (emulators and all(
            emu and (index.gun_programs(f"emulators/{emu}.ahk")
                     or index.gun_programs(f"{system}/emulators/{emu}.ahk"))
            for emu in emulators
        ))
    )


def audit_system_wiring(system_name: str, config: Config,
                        user_functions: Optional[UserFunctionsIndex] = None,
                        ) -> Optional[SystemLightgunStatus]:
    """Return the gun wiring for *system_name*, or None if no INI.

    That's the DemulShooter ``Pre_Launch_App`` / ``Post_Launch_App`` hooks,
    plus the User Functions files that start the gun software.  When
    auditing several systems, pass one *user_functions* index to them all.
    """
    if not config.rocketlauncher_dir:
        return None
    found = system_settings_ini(Path(config.rocketlauncher_dir), system_name)
    if found is None:
        return None
    ini_path = found[0]

    from .rocketlauncher import _read_windows_text
    body = _read_windows_text(ini_path)
    status = SystemLightgunStatus(system_name=system_name, ini_path=ini_path)

    m = DEMULSHOOTER_PRE_RE.search(body)
    if m:
        status.pre_launch = m.group(1).strip()
        tgt = _TARGET_RE.search(status.pre_launch)
        if tgt:
            status.target = tgt.group(1).strip('"')

    m = DEMULSHOOTER_POST_RE.search(body)
    if m:
        status.post_launch = m.group(1).strip()

    if user_functions is None:
        user_functions = index_user_functions(Path(config.rocketlauncher_dir))
    if user_functions.files:
        emulators = _system_emulators(Path(config.rocketlauncher_dir), system_name, body)
        _add_user_functions(status, user_functions, emulators)
    return status


def detect_lightgun_wiring(config: Config) -> dict[str, str]:
    """Every system already wired for light guns → how, sorted by name.

    ``"Pre_Launch_App"`` for a DemulShooter hook in the system's RL INI,
    else ``"User Functions: <where>"`` when its User Functions files start
    the gun software (see :meth:`SystemLightgunStatus.user_functions_where`).
    """
    if not config.rocketlauncher_dir:
        return {}
    settings = Path(config.rocketlauncher_dir) / "Settings"
    if not settings.exists():
        return {}
    found: dict[str, str] = {}
    skip = {"global emulators.ini", "rocketlauncher.ini", "global rocketlauncher.ini"}
    # Flat Settings/<System>.ini and folder-layout Settings/<System>/Emulators.ini.
    candidates = [(ini, ini.stem) for ini in settings.glob("*.ini")
                  if ini.name.lower() not in skip]
    candidates += [(ini, ini.parent.name) for ini in settings.glob("*/Emulators.ini")]
    for ini, system in candidates:
        body = ini.read_text(encoding="utf-8", errors="replace")
        if DEMULSHOOTER_PRE_RE.search(body):
            found[system] = "Pre_Launch_App"
    user_functions = index_user_functions(Path(config.rocketlauncher_dir))
    if user_functions.files:
        for system in sorted({s for _ini, s in candidates} - set(found)):
            status = audit_system_wiring(system, config, user_functions=user_functions)
            if status is not None and status.wired_via_user_functions:
                found[system] = f"User Functions: {status.user_functions_where()}"
    return dict(sorted(found.items()))


def detect_lightgun_systems(config: Config) -> list[str]:
    """Return system names already wired for light guns: a DemulShooter
    ``Pre_Launch_App`` in their RL INI, or User Functions that start the gun
    software (see :func:`detect_lightgun_wiring`)."""
    return list(detect_lightgun_wiring(config))


# ─── per-system configuration writer ──────────────────────────────────────────

@dataclass
class WirePlan:
    """Dry-run preview of what a configure call would change."""
    system_name: str
    ini_path: Path
    target: str
    pre_launch_command: str
    post_launch_command: str
    create_ini: bool = False      # kept for callers; the plan never creates the INI
    section: str = "Settings"     # [ROMS] in a folder-layout Emulators.ini
    replace_pre: bool = False
    replace_post: bool = False
    notes: list[str] = field(default_factory=list)
    # Reasons the hooks may do harm, e.g. the gun software starting twice.
    warnings: list[str] = field(default_factory=list)


def plan_wire_system(
    system_name: str,
    config: Config,
    install: LightgunInstall,
    *,
    target_override: Optional[str] = None,
    extra_args: str = DEFAULT_DEMULSHOOTER_ARGS,
) -> WirePlan:
    """Build the WirePlan for wiring *system_name* into DemulShooter."""
    if not config.rocketlauncher_dir:
        raise ValueError(
            "rocketlauncher_dir not configured. "
            "Run: spindoctor config set rocketlauncher_dir <path>."
        )
    if not install.has_demulshooter:
        raise ValueError(
            "DemulShooter is not installed. "
            "Install it under your tools tree before wiring lightgun systems."
        )

    target = target_override or guess_demulshooter_target(system_name)
    if not target:
        raise ValueError(
            f"No DemulShooter target known for system '{system_name}'. "
            "Pass --target <name> explicitly (see DemulShooter docs)."
        )

    found = system_settings_ini(Path(config.rocketlauncher_dir), system_name)
    if found is None:
        # Generating the system's settings here would rewrite Rom_Path and
        # friends as a side effect of adding two hook keys.
        raise ValueError(
            f"No RocketLauncher settings for '{system_name}' "
            f"(Settings\\{system_name}\\Emulators.ini or Settings\\{system_name}.ini). "
            "Set the system up in RocketLauncherUI or run "
            "'spindoctor generate-config --apply' first."
        )
    ini_path, section = found
    demul_exe = install.demulshooter_exe
    # DemulShooter options take "=": -target=<name>, not "-target <name>".
    pre_cmd = f'"{demul_exe}" -target={target} {extra_args}'.strip()
    # taskkill is the standard RL post-launch teardown for DemulShooter.
    post_cmd = f'taskkill /IM "{demul_exe.name}" /F'

    plan = WirePlan(
        system_name=system_name,
        ini_path=ini_path,
        target=target,
        pre_launch_command=pre_cmd,
        post_launch_command=post_cmd,
        section=section,
    )
    body = ini_path.read_text(encoding="utf-8", errors="replace")
    existing_pre = DEMULSHOOTER_PRE_RE.search(body)
    existing_post = _POST_LAUNCH_RE.search(body)
    if existing_pre and existing_pre.group(1).strip() != pre_cmd:
        plan.replace_pre = True
        plan.notes.append(
            f"Existing Pre_Launch_App will be replaced "
            f"(was: {existing_pre.group(1).strip()})."
        )
    if existing_post and existing_post.group(1).strip() and existing_post.group(1).strip() != post_cmd:
        plan.replace_post = True
        plan.notes.append(
            f"Existing Post_Launch_App will be replaced "
            f"(was: {existing_post.group(1).strip()})."
        )

    # The hook comes on top of whatever User Functions already start.
    status = audit_system_wiring(system_name, config)
    if status is not None and status.wired_via_user_functions:
        where = status.user_functions_where()
        if "demulshooter" in status.user_functions_programs:
            plan.warnings.append(
                f"'{system_name}' already starts DemulShooter from RocketLauncher "
                f"User Functions ({where}). This Pre_Launch_App would start it a "
                "second time: keep only one of the two."
            )
        else:
            plan.warnings.append(
                f"'{system_name}' already starts the gun software from RocketLauncher "
                f"User Functions ({where}). If those files also start DemulShooter "
                "(directly or through a helper script), this Pre_Launch_App starts "
                "it a second time: keep only one of the two."
            )
    return plan


def apply_wire_plan(plan: WirePlan, config: Config) -> Path:
    """Execute *plan* — add the hook keys to the system's existing INI.

    Only ``Pre_Launch_App`` / ``Post_Launch_App`` change; the plan points at
    a settings file that already exists (see :func:`plan_wire_system`).
    """
    ini_path = plan.ini_path
    from .rocketlauncher import _read_windows_text_with_encoding
    from ._utils import atomic_write_bytes
    body, encoding = _read_windows_text_with_encoding(ini_path)
    bom = "\ufeff" if body.startswith("\ufeff") else ""
    body = body.lstrip("\ufeff")
    body = _upsert_ini_key(body, plan.section, "Pre_Launch_App",
                           plan.pre_launch_command)
    body = _upsert_ini_key(body, plan.section, "Post_Launch_App",
                           plan.post_launch_command)
    atomic_write_bytes(ini_path, (bom + body).encode(encoding, errors="surrogateescape"))
    return ini_path


def _upsert_ini_key(body: str, section: str, key: str, value: str) -> str:
    """Insert or replace ``key=value`` inside ``[section]`` in INI *body*.

    Stays line-oriented and preserves surrounding content.  If *section*
    is missing we append it.  Targets the simple flat INI layout used by
    RocketLauncher — full INI parsing would lose blank lines and the
    handwritten comments many Tur builds keep around.
    """
    section_re = re.compile(rf"^\[{re.escape(section)}\][ \t]*(?=\r?$)",
                            re.IGNORECASE | re.MULTILINE)
    key_re = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=[^\r\n]*",
                        re.IGNORECASE | re.MULTILINE)

    section_match = section_re.search(body)
    if not section_match:
        # Append a new section at end.
        eol = "\r\n" if "\r\n" in body else "\n"
        if body and not body.endswith(eol):
            body += eol
        body += f"{eol}[{section}]{eol}{key}={value}{eol}"
        return body

    # Find the bounds of the matched section (until next [section] or EOF).
    start = section_match.end()
    next_section = re.compile(r"^[ \t]*\[", re.MULTILINE).search(body, pos=start)
    end = next_section.start() if next_section else len(body)
    chunk = body[start:end]

    if key_re.search(chunk):
        # Use a callable replacement to avoid re.sub interpreting backslashes
        # in the value string (e.g. Windows paths like C:\Users\...) as
        # regex backreferences, which raises re.error on \U, \N, etc.
        replacement = f"{key}={value}"
        chunk = key_re.sub(lambda _: replacement, chunk, count=1)
    else:
        eol = "\r\n" if "\r\n" in body else "\n"
        chunk = chunk.rstrip() + f"{eol}{key}={value}{eol}"

    return body[:start] + chunk + body[end:]
