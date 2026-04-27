"""LEDBlinky controls.ini / colors.ini export and audit.

Strategy: merge-then-fill.

1. Read existing ``<ledblinky_dir>/controls.ini`` and ``colors.ini``
   (community-maintained, trusted).
2. For ROMs not covered there, synthesise entries from
   ``mame -listxml <rom>`` output.
3. Emit a new combined file, never blindly overwriting existing entries.

This module also provides ``parse_listxml`` which is reused by ``audit.py`` to
flag ROMs that lack control metadata.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import CONFIG_DIR, Config


LISTXML_CACHE_DIR = CONFIG_DIR / "mame_listxml_cache"

# ─── data shapes ───────────────────────────────────────────────────────────────


@dataclass
class ControlInfo:
    """Per-ROM control summary derived from MAME -listxml."""
    rom_name: str
    description: str = ""
    num_players: int = 1
    num_buttons: int = 0
    control_types: list[str] = field(default_factory=list)  # e.g. ['joy', 'button']
    has_input: bool = False
    raw_input: list[dict] = field(default_factory=list)


@dataclass
class IniSection:
    """A free-form INI section: name + list of (key, value) pairs preserving order."""
    name: str
    lines: list[str] = field(default_factory=list)


# ─── INI parser (preserves line order, comments) ──────────────────────────────


_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")


def parse_ini_sections(path: Path) -> dict[str, IniSection]:
    """Parse an INI-style file into ``{section_name: IniSection}``.

    Section names are case-preserved.  Lines (including blank/comment lines)
    inside each section are kept verbatim so that round-tripping a section
    is byte-identical.
    """
    if not path.exists():
        return {}
    sections: dict[str, IniSection] = {}
    current: Optional[IniSection] = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            name = m.group("name").strip()
            current = IniSection(name=name)
            sections[name] = current
        elif current is not None:
            current.lines.append(line)
    return sections


def parse_existing_controls_ini(path: Path) -> dict[str, IniSection]:
    """Return ``{rom_name: IniSection}`` from an existing LEDBlinky controls.ini."""
    return parse_ini_sections(path)


def parse_existing_colors_ini(path: Path) -> dict[str, IniSection]:
    """Return ``{rom_name: IniSection}`` from an existing LEDBlinky colors.ini."""
    return parse_ini_sections(path)


# ─── MAME -listxml ─────────────────────────────────────────────────────────────


def run_mame_listxml(
    mame_executable: str,
    rom_filter: Optional[Iterable[str]] = None,
    cache_path: Optional[Path] = None,
) -> bytes:
    """Run ``mame -listxml`` and return raw XML bytes.

    If ``cache_path`` is provided and is fresh (newer than the MAME binary),
    the cached XML is returned instead.
    """
    mame_path = Path(mame_executable)
    use_cache = (
        cache_path is not None
        and cache_path.exists()
        and (not mame_path.exists()
             or cache_path.stat().st_mtime >= mame_path.stat().st_mtime)
    )
    if use_cache:
        return cache_path.read_bytes()

    cmd = [mame_executable, "-listxml"]
    if rom_filter:
        cmd.extend(rom_filter)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, check=False, timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Failed to run MAME: {e}") from e

    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(
            f"mame -listxml failed (rc={proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='replace')[:200]}"
        )

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(proc.stdout)

    return proc.stdout


def parse_listxml(xml_bytes: bytes) -> dict[str, ControlInfo]:
    """Parse MAME ``-listxml`` output into ``{rom_name: ControlInfo}``."""
    if not xml_bytes:
        return {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {}

    out: dict[str, ControlInfo] = {}
    for machine in root.iter("machine"):
        name = machine.get("name") or ""
        if not name:
            continue
        desc_el = machine.find("description")
        info = ControlInfo(
            rom_name=name,
            description=(desc_el.text or "") if desc_el is not None else "",
        )
        input_el = machine.find("input")
        if input_el is not None:
            info.has_input = True
            try:
                info.num_players = int(input_el.get("players") or "1")
            except ValueError:
                info.num_players = 1
            buttons = 0
            for ctrl in input_el.findall("control"):
                ctype = (ctrl.get("type") or "").strip()
                if ctype:
                    info.control_types.append(ctype)
                try:
                    btns = int(ctrl.get("buttons") or "0")
                except ValueError:
                    btns = 0
                buttons = max(buttons, btns)
                info.raw_input.append({
                    "type": ctype,
                    "player": ctrl.get("player") or "",
                    "buttons": ctrl.get("buttons") or "",
                    "ways": ctrl.get("ways") or "",
                })
            info.num_buttons = buttons
        out[name] = info
    return out


def load_listxml_for_system(config: Config, system_name: str) -> dict[str, ControlInfo]:
    """Cached wrapper around ``run_mame_listxml`` + ``parse_listxml``.

    Returns an empty dict (silently) if MAME is not configured.
    """
    if not config.mame_executable:
        return {}
    cache_path = LISTXML_CACHE_DIR / f"{_safe(system_name)}.xml"
    try:
        xml_bytes = run_mame_listxml(
            config.mame_executable, cache_path=cache_path,
        )
    except RuntimeError:
        return {}
    return parse_listxml(xml_bytes)


# ─── synthesis from -listxml ───────────────────────────────────────────────────


def synth_controls_section(info: ControlInfo) -> IniSection:
    """Build a controls.ini section from a ControlInfo.

    Format approximates LEDBlinky's controls.ini convention:
        [<rom>]
        description=<MAME description>
        numPlayers=<n>
        P<i>_NUMBUTTONS=<n>
        P<i>_CONTROLS=<comma-list>
    """
    lines = [
        f"description={info.description}",
        f"numPlayers={info.num_players}",
        f"alternating=0",
    ]

    # Per-player rollup
    by_player: dict[str, dict] = {}
    for ctrl in info.raw_input:
        pid = ctrl.get("player") or "1"
        slot = by_player.setdefault(pid, {"buttons": 0, "types": []})
        try:
            slot["buttons"] = max(slot["buttons"], int(ctrl.get("buttons") or "0"))
        except ValueError:
            pass
        ctype = ctrl.get("type") or ""
        if ctype and ctype not in slot["types"]:
            slot["types"].append(ctype)

    if not by_player and info.has_input:
        by_player["1"] = {"buttons": info.num_buttons, "types": info.control_types}

    for pid in sorted(by_player.keys()):
        slot = by_player[pid]
        ctrl_list = []
        for ctype in slot["types"]:
            cu = ctype.upper()
            if cu == "JOY":
                ctrl_list.append("JOYSTICK_8WAY")
            elif cu == "DOUBLEJOY":
                ctrl_list.append("DOUBLEJOY_8WAY")
            elif cu == "TRACKBALL":
                ctrl_list.append("TRACKBALL")
            elif cu == "PADDLE":
                ctrl_list.append("PADDLE")
            elif cu == "DIAL":
                ctrl_list.append("DIAL")
            elif cu == "LIGHTGUN":
                ctrl_list.append("LIGHTGUN")
            elif cu == "PEDAL":
                ctrl_list.append("PEDAL")
            elif cu == "STICK":
                ctrl_list.append("ANALOG_STICK")
            elif cu:
                ctrl_list.append(cu)
        for i in range(1, slot["buttons"] + 1):
            ctrl_list.append(f"BUTTON{i}")
        lines.append(f"P{pid}_NUMBUTTONS={slot['buttons']}")
        if ctrl_list:
            lines.append(f"P{pid}_CONTROLS={','.join(ctrl_list)}")

    return IniSection(name=info.rom_name, lines=lines)


def synth_colors_section(info: ControlInfo, palette: dict[str, str]) -> IniSection:
    """Build a colors.ini section using the configured default palette."""
    lines = []
    n = info.num_buttons or 6
    for i in range(1, n + 1):
        key = f"button{i}"
        color = palette.get(key) or palette.get(f"button{((i - 1) % 6) + 1}", "FFFFFF")
        lines.append(f"ledcolor{i}={color}")
    if "joystick" in palette:
        lines.append(f"joystick={palette['joystick']}")
    if "start" in palette:
        lines.append(f"start={palette['start']}")
    if "coin" in palette:
        lines.append(f"coin={palette['coin']}")
    return IniSection(name=info.rom_name, lines=lines)


# ─── merge + emit ──────────────────────────────────────────────────────────────


def emit_ini(sections: dict[str, IniSection], path: Path, header_lines: list[str]) -> None:
    """Write sections to disk in stable (case-insensitive) order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = list(header_lines)
    if header_lines:
        out.append("")
    for name in sorted(sections.keys(), key=str.lower):
        section = sections[name]
        out.append(f"[{name}]")
        out.extend(section.lines)
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def _backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


@dataclass
class GenerateResult:
    controls_path: Optional[Path] = None
    colors_path: Optional[Path] = None
    controls_existing_kept: int = 0
    colors_existing_kept: int = 0
    controls_synthesised: int = 0
    colors_synthesised: int = 0
    skipped_no_input: int = 0


def generate_for_roms(
    config: Config,
    rom_names: Iterable[str],
    output_dir: Optional[Path] = None,
    overwrite_existing: bool = False,
    dry_run: bool = False,
) -> GenerateResult:
    """Generate / merge controls.ini and colors.ini for the given ROMs.

    Existing entries are preserved unless ``overwrite_existing`` is True.
    When ``output_dir`` is given the files are written there instead of
    overwriting ``<ledblinky_dir>/controls.ini`` and ``colors.ini``.
    """
    rom_list = list(rom_names)
    result = GenerateResult()

    base = output_dir or (Path(config.ledblinky_dir) if config.ledblinky_dir else None)
    if base is None:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>  or pass --output-dir."
        )

    src_base = Path(config.ledblinky_dir) if config.ledblinky_dir else None
    src_controls = (src_base / "controls.ini") if src_base else None
    src_colors = (src_base / "colors.ini") if src_base else None

    existing_controls = (
        parse_existing_controls_ini(src_controls) if src_controls else {}
    )
    existing_colors = (
        parse_existing_colors_ini(src_colors) if src_colors else {}
    )

    listxml = load_listxml_for_system(config, "MAME")

    out_controls: dict[str, IniSection] = dict(existing_controls)
    out_colors: dict[str, IniSection] = dict(existing_colors)

    for rom in rom_list:
        info = listxml.get(rom)
        if info is None or not info.has_input:
            result.skipped_no_input += 1
            # Keep any existing entries verbatim.
            if rom in existing_controls:
                result.controls_existing_kept += 1
            if rom in existing_colors:
                result.colors_existing_kept += 1
            continue

        if rom in existing_controls and not overwrite_existing:
            result.controls_existing_kept += 1
        else:
            out_controls[rom] = synth_controls_section(info)
            result.controls_synthesised += 1

        if rom in existing_colors and not overwrite_existing:
            result.colors_existing_kept += 1
        else:
            out_colors[rom] = synth_colors_section(info, config.ledblinky_default_colors)
            result.colors_synthesised += 1

    controls_path = base / "controls.ini"
    colors_path = base / "colors.ini"

    if dry_run:
        result.controls_path = controls_path
        result.colors_path = colors_path
        return result

    header = [
        "; Generated/merged by SpinDoctor.",
        f"; {datetime.now().isoformat(timespec='seconds')}",
        "; Existing community-maintained entries are preserved as-is.",
    ]
    if output_dir is None and config.backup_before_modify:
        _backup(controls_path)
        _backup(colors_path)

    emit_ini(out_controls, controls_path, header)
    emit_ini(out_colors, colors_path, header)
    result.controls_path = controls_path
    result.colors_path = colors_path
    return result


# ─── audit ────────────────────────────────────────────────────────────────────


@dataclass
class CoverageRow:
    rom_name: str
    in_listxml: bool = False
    has_input: bool = False
    in_controls_ini: bool = False
    in_colors_ini: bool = False

    @property
    def status(self) -> str:
        if self.in_controls_ini and self.in_colors_ini:
            return "covered"
        if self.has_input:
            return "would-synth"
        if self.in_listxml:
            return "no-input"
        return "missing"


def audit_coverage(config: Config, rom_names: Iterable[str]) -> list[CoverageRow]:
    """Return per-ROM coverage info: existing entries vs. -listxml synthesis."""
    src_base = Path(config.ledblinky_dir) if config.ledblinky_dir else None
    existing_controls = (
        parse_existing_controls_ini(src_base / "controls.ini")
        if src_base else {}
    )
    existing_colors = (
        parse_existing_colors_ini(src_base / "colors.ini")
        if src_base else {}
    )
    listxml = load_listxml_for_system(config, "MAME")

    rows: list[CoverageRow] = []
    for rom in rom_names:
        info = listxml.get(rom)
        rows.append(CoverageRow(
            rom_name=rom,
            in_listxml=info is not None,
            has_input=bool(info and info.has_input),
            in_controls_ini=rom in existing_controls,
            in_colors_ini=rom in existing_colors,
        ))
    return rows


# ─── helpers ──────────────────────────────────────────────────────────────────


_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str) -> str:
    return _SAFE_RE.sub("_", name)[:120] or "_"
