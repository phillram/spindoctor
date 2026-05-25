"""Sinden / DemulShooter wiring for lightgun-enabled systems.

RocketLauncher's per-system INI supports ``Pre_Launch_App`` and
``Post_Launch_App`` keys that fire before the emulator starts and after
it exits.  We use that to start DemulShooter with the correct
``-target`` for the system, and to kill it on exit so it doesn't block
the next launch.

Detection runs in two passes:

1.  *Folder fingerprint* — check for a Sinden install (driver folder)
    and a DemulShooter executable in the configured tools/emulators
    trees.  This tells us whether the cabinet has the gear at all.

2.  *RL module / INI scan* — for every per-system INI under
    ``RocketLauncher/Settings``, look for ``DemulShooter`` references in
    ``Pre_Launch_App`` / ``Post_Launch_App`` (and the older AHK-module
    pattern).  Any system already wired this way is treated as
    lightgun-enabled and seeded into the spindoctor config.

``configure --system <name>`` writes/updates the per-system INI.  It
never touches the global module .ahk files (that's where Tur templates
live and breaking those would break every system at once).
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
    """
    from .tools_audit import default_scan_roots

    install = LightgunInstall()
    roots = list(default_scan_roots(config))
    if extra_roots:
        roots.extend(extra_roots)

    sinden_hints = ("sinden lightgun", "sindenlightgun", "sinden")
    arcadeguns_hints = ("arcade guns", "arcadeguns")
    demul_exes = {"demulshooter.exe", "demulshooterx64.exe"}

    for root in roots:
        if not root.exists():
            continue
        # Bounded walk — Sinden + DemulShooter live ≤4 levels deep.
        for depth, dirpath in _bounded_walk(root, max_depth=4):
            lower = str(dirpath).lower()
            if not install.sinden_software_dir and any(
                h in lower for h in sinden_hints
            ):
                install.sinden_software_dir = dirpath
            if not install.arcade_guns_dir and any(
                h in lower for h in arcadeguns_hints
            ):
                install.arcade_guns_dir = dirpath
            if not install.demulshooter_exe:
                for f in dirpath.iterdir() if dirpath.is_dir() else []:
                    if f.is_file() and f.name.lower() in demul_exes:
                        install.demulshooter_exe = f
                        break

    return install


def _bounded_walk(root: Path, max_depth: int):
    """Yield ``(depth, dir)`` for every directory under *root*."""
    import os
    base = len(root.resolve().parts) if root.exists() else len(root.parts)
    for dirpath, _, _ in os.walk(root):
        depth = len(Path(dirpath).resolve().parts) - base
        if depth > max_depth:
            continue
        yield depth, Path(dirpath)


# ─── per-system audit ─────────────────────────────────────────────────────────

DEMULSHOOTER_PRE_RE = re.compile(
    r"^\s*Pre_Launch_App\s*=\s*(?P<value>.*demulshooter.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
DEMULSHOOTER_POST_RE = re.compile(
    r"^\s*Post_Launch_App\s*=\s*(.+)",
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

    @property
    def is_wired(self) -> bool:
        return self.pre_launch is not None


def audit_system_wiring(system_name: str, config: Config
                        ) -> Optional[SystemLightgunStatus]:
    """Return the DemulShooter wiring for *system_name*, or None if no INI."""
    if not config.rocketlauncher_dir:
        return None
    ini_path = (Path(config.rocketlauncher_dir) / "Settings"
                / f"{system_name}.ini")
    if not ini_path.exists():
        return None

    body = ini_path.read_text(encoding="utf-8", errors="replace")
    status = SystemLightgunStatus(system_name=system_name, ini_path=ini_path)

    m = DEMULSHOOTER_PRE_RE.search(body)
    if m:
        status.pre_launch = m.group(1).strip()
        tgt = re.search(r"-target\s+(\S+)", status.pre_launch)
        if tgt:
            status.target = tgt.group(1)

    m = DEMULSHOOTER_POST_RE.search(body)
    if m:
        status.post_launch = m.group(1).strip()

    return status


def detect_lightgun_systems(config: Config) -> list[str]:
    """Return system names whose RL INI already has DemulShooter wiring."""
    if not config.rocketlauncher_dir:
        return []
    settings = Path(config.rocketlauncher_dir) / "Settings"
    if not settings.exists():
        return []
    found: list[str] = []
    for ini in settings.glob("*.ini"):
        if ini.name.lower() in {"global emulators.ini", "rocketlauncher.ini"}:
            continue
        body = ini.read_text(encoding="utf-8", errors="replace")
        if DEMULSHOOTER_PRE_RE.search(body):
            found.append(ini.stem)
    return sorted(found)


# ─── per-system configuration writer ──────────────────────────────────────────

@dataclass
class WirePlan:
    """Dry-run preview of what a configure call would change."""
    system_name: str
    ini_path: Path
    target: str
    pre_launch_command: str
    post_launch_command: str
    create_ini: bool = False
    replace_pre: bool = False
    replace_post: bool = False
    notes: list[str] = field(default_factory=list)


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

    ini_path = (Path(config.rocketlauncher_dir) / "Settings"
                / f"{system_name}.ini")
    demul_exe = install.demulshooter_exe
    pre_cmd = f'"{demul_exe}" -target {target} {extra_args}'.strip()
    # taskkill is the standard RL post-launch teardown for DemulShooter.
    post_cmd = f'taskkill /IM "{demul_exe.name}" /F'

    plan = WirePlan(
        system_name=system_name,
        ini_path=ini_path,
        target=target,
        pre_launch_command=pre_cmd,
        post_launch_command=post_cmd,
    )
    if not ini_path.exists():
        plan.create_ini = True
        plan.notes.append("Settings/<system>.ini does not exist — it will be "
                          "generated and the DemulShooter hooks added.")
    else:
        body = ini_path.read_text(encoding="utf-8", errors="replace")
        existing_pre = DEMULSHOOTER_PRE_RE.search(body)
        existing_post = DEMULSHOOTER_POST_RE.search(body)
        if existing_pre and existing_pre.group(1).strip() != pre_cmd:
            plan.replace_pre = True
            plan.notes.append(
                f"Existing Pre_Launch_App will be replaced "
                f"(was: {existing_pre.group(1).strip()})."
            )
        if existing_post and existing_post.group(1).strip() != post_cmd:
            plan.replace_post = True
            plan.notes.append(
                f"Existing Post_Launch_App will be replaced "
                f"(was: {existing_post.group(1).strip()})."
            )
    return plan


def apply_wire_plan(plan: WirePlan, config: Config) -> Path:
    """Execute *plan* — write the INI changes."""
    from .rocketlauncher import generate_rl_system_ini

    ini_path = plan.ini_path
    if plan.create_ini:
        # Use the standard generator so the INI is shaped like every other
        # spindoctor-generated system file, then append the hook keys.
        generate_rl_system_ini(plan.system_name, config)

    body = ini_path.read_text(encoding="utf-8", errors="replace")
    body = _upsert_ini_key(body, "Settings", "Pre_Launch_App",
                           plan.pre_launch_command)
    body = _upsert_ini_key(body, "Settings", "Post_Launch_App",
                           plan.post_launch_command)
    ini_path.write_text(body, encoding="utf-8")
    return ini_path


def _upsert_ini_key(body: str, section: str, key: str, value: str) -> str:
    """Insert or replace ``key=value`` inside ``[section]`` in INI *body*.

    Stays line-oriented and preserves surrounding content.  If *section*
    is missing we append it.  Targets the simple flat INI layout used by
    RocketLauncher — full INI parsing would lose blank lines and the
    handwritten comments many Tur builds keep around.
    """
    section_re = re.compile(rf"^\[{re.escape(section)}\]\s*$",
                            re.IGNORECASE | re.MULTILINE)
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=.*$",
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
    next_section = re.compile(r"^\s*\[", re.MULTILINE).search(body, pos=start)
    end = next_section.start() if next_section else len(body)
    chunk = body[start:end]

    if key_re.search(chunk):
        # Use a callable replacement to avoid re.sub interpreting backslashes
        # in the value string (e.g. Windows paths like C:\Users\...) as
        # regex backreferences, which raises re.error on \U, \N, etc.
        replacement = f"{key}={value}"
        chunk = key_re.sub(lambda _: replacement, chunk, count=1)
    else:
        eol = "\r\n" if "\r\n" in chunk else "\n"
        chunk = chunk.rstrip() + f"{eol}{key}={value}{eol}"

    return body[:start] + chunk + body[end:]
