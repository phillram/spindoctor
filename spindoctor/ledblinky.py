"""LEDBlinky integration: controls.ini export + HyperSpin Search compatibility.

This module covers two related concerns:

**1. controls.ini / colors.ini export and audit (merge-then-fill).**

   - Read existing ``<ledblinky_dir>/controls.ini`` and ``colors.ini``
     (community-maintained, trusted).
   - For ROMs not covered there, synthesise entries from
     ``mame -listxml <rom>`` output.
   - Emit a new combined file, never blindly overwriting existing entries.
   - ``parse_listxml`` is reused by ``audit.py`` to flag ROMs that lack
     control metadata.

**2. HyperSpin Search special-menu compatibility (:func:`scan` / :func:`apply_fix`).**

   Two known conflicts when LedBlinky is installed alongside HyperSpin's
   Search (and Genre/Favorites) special menus:

   - LedBlinky's process hooks (``Start_Hyperspin_Process`` /
     ``Exit_Hyperspin_Process``) get injected into the Search menu's
     ``Settings.ini`` and crash the overlay launcher when it tries to fire.
   - ``LEDBlinkyControls.xml`` has no entry for the Search special menu,
     so the menu-change lookup fails and LedBlinky errors out — sometimes
     taking HyperSpin down with it.

   :func:`scan` audits both conditions read-only; :func:`apply_fix` patches
   them, honoring the standard ``output_base`` / ``dry_run`` / ``backup``
   conventions used elsewhere in SpinDoctor.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from ._compat import et_indent
from .config import CONFIG_DIR, Config

# Hide the console window when ``subprocess.run`` launches MAME from
# the GUI on Windows. Without this, every ``audit`` / ``controls
# export`` run pops a black ``cmd.exe`` window that flashes for the
# duration of ``mame -listxml`` (can be many seconds for a full set).
# 0 on non-Windows so the flag is harmless to pass on macOS / Linux.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0



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


def parse_ini_sections(path: Path, *, warnings: "list[str] | None" = None) -> dict[str, IniSection]:
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
    except OSError as exc:
        if warnings is not None:
            warnings.append(
                f"Could not read LEDBlinky INI {path}: {type(exc).__name__}: {exc}"
            )
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


def parse_existing_controls_ini(
    path: Path,
    *,
    warnings: "list[str] | None" = None,
) -> dict[str, IniSection]:
    """Return ``{rom_name: IniSection}`` from an existing LEDBlinky controls.ini."""
    return parse_ini_sections(path, warnings=warnings)


def parse_existing_colors_ini(
    path: Path,
    *,
    warnings: "list[str] | None" = None,
) -> dict[str, IniSection]:
    """Return ``{rom_name: IniSection}`` from an existing LEDBlinky colors.ini."""
    return parse_ini_sections(path, warnings=warnings)


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
            creationflags=_CREATE_NO_WINDOW,
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


def parse_listxml(
    xml_bytes: bytes,
    *,
    warnings: "list[str] | None" = None,
) -> dict[str, ControlInfo]:
    """Parse MAME ``-listxml`` output into ``{rom_name: ControlInfo}``."""
    if not xml_bytes:
        return {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        if warnings is not None:
            warnings.append(
                f"Could not parse MAME -listxml output: {exc} — "
                "LEDBlinky and audit MAME control data will be unavailable. "
                "Try deleting the listxml cache and re-running."
            )
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


def load_listxml_for_system(
    config: Config,
    system_name: str,
    *,
    warnings: "list[str] | None" = None,
) -> dict[str, ControlInfo]:
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
    except RuntimeError as exc:
        if warnings is not None:
            warnings.append(
                f"MAME -listxml failed for {system_name}: {exc} — "
                "LEDBlinky control data will be unavailable."
            )
        return {}
    return parse_listxml(xml_bytes, warnings=warnings)


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
        "alternating=0",
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
    warnings: list[str] = field(default_factory=list)


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
        parse_existing_controls_ini(src_controls, warnings=result.warnings) if src_controls else {}
    )
    existing_colors = (
        parse_existing_colors_ini(src_colors, warnings=result.warnings) if src_colors else {}
    )

    listxml = load_listxml_for_system(config, "MAME", warnings=result.warnings)

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

# ═══════════════════════════════════════════════════════════════════════════
# HyperSpin Search special-menu compatibility (scan / apply_fix)
# ═══════════════════════════════════════════════════════════════════════════


# Known problematic special menus. Search is the typical offender; Genre /
# Favorites have the same root cause and are supported via --menus.
SEARCH_MENU_NAMES = ["Search", "Genre", "Favorites"]

LEDBLINKY_HOOK_KEYS = ["Start_Hyperspin_Process", "Exit_Hyperspin_Process"]
LEDBLINKY_HOOK_MARKER = "LEDBlinky"   # the binary referenced in the hook value
LEDBLINKY_DISABLE_TAG = "; disabled by spindoctor ledblinky fix"

CONTROLS_XML_NAME = "LEDBlinkyControls.xml"


# ─── path helpers ─────────────────────────────────────────────────────────────

def _controls_xml_path(config: Config) -> Optional[Path]:
    if not config.ledblinky_dir:
        return None
    return Path(config.ledblinky_dir) / CONTROLS_XML_NAME


def _menu_ini_path(config: Config, menu_name: str) -> Optional[Path]:
    """Locate a HyperSpin special-menu Settings.ini.

    HyperSpin stores these under ``<hyperspin_dir>/Menu/<MenuName>/Settings.ini``.
    Returns ``None`` if ``hyperspin_dir`` is unset.
    """
    if not config.hyperspin_dir:
        return None
    return Path(config.hyperspin_dir) / "Menu" / menu_name / "Settings.ini"


def _hs_settings_ini(config: Config) -> Optional[Path]:
    if not config.hyperspin_dir:
        return None
    return Path(config.hyperspin_dir) / "Settings" / "Settings.ini"


# ─── INI scanning / patching ──────────────────────────────────────────────────

_HOOK_LINE_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(k) for k in LEDBLINKY_HOOK_KEYS) + r")\s*=",
    re.IGNORECASE,
)


def _ini_has_ledblinky_hook(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        if not _HOOK_LINE_RE.match(line):
            continue
        if LEDBLINKY_HOOK_MARKER.lower() in line.lower():
            return True
    return False


def _comment_out_hooks(text: str) -> tuple[str, int]:
    """Comment out any active LedBlinky hook lines.

    Returns ``(new_text, lines_changed)``. Lines that are already commented
    (``;`` or ``#`` prefix) are left alone.
    """
    out_lines: list[str] = []
    changed = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(";") or stripped.startswith("#"):
            out_lines.append(line)
            continue
        if not _HOOK_LINE_RE.match(line):
            out_lines.append(line)
            continue
        if LEDBLINKY_HOOK_MARKER.lower() not in line.lower():
            out_lines.append(line)
            continue
        out_lines.append(f";{line}  {LEDBLINKY_DISABLE_TAG}")
        changed += 1
    new_text = "\n".join(out_lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, changed


# ─── controls XML scanning / patching ─────────────────────────────────────────

def _controls_xml_menu_names(path: Path) -> set[str]:
    """Return the set of menu names already declared in LEDBlinkyControls.xml.

    LEDBlinkyControls.xml uses a ``<game name="...">`` element per entry,
    where the name doubles as the system / menu identifier (this matches
    LedBlinky's own emulator-list convention). We tolerate alternative
    schemas by also inspecting any ``<menu>`` children.
    """
    if not path.exists():
        return set()
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return set()
    root = tree.getroot()
    names: set[str] = set()
    for tag in ("game", "menu", "system"):
        for el in root.iter(tag):
            n = el.get("name")
            if n:
                names.add(n)
    return names


def _ensure_controls_xml_entries(
    src_path: Path,
    dst_path: Path,
    menus: list[str],
) -> tuple[bool, list[str]]:
    """Make sure ``dst_path`` contains a stub entry for each menu name.

    Reads from ``src_path`` (which may equal ``dst_path``), mutates the tree
    in memory, and writes to ``dst_path``. Returns ``(wrote, added_names)``.
    If no changes were needed, returns ``(False, [])`` and writes nothing.

    The stub entry is intentionally minimal — a ``<game>`` element with the
    menu name and an explanatory comment. LedBlinky treats unknown profiles
    as "use the default", which is exactly what we want for a static
    placeholder during the Search overlay.
    """
    if src_path.exists():
        try:
            # Read-then-parse so the file handle releases before the
            # in-place write below. ET.parse(path) keeps the file
            # open on Windows until the tree is GC'd, which can
            # collide with the subsequent ``open(dst_path, "wb")``
            # when ``src_path == dst_path``.
            with open(src_path, "rb") as fh:
                tree = ET.parse(fh)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse {src_path}: {e}") from e
    else:
        # LEDBlinky hasn't created the file yet — start a fresh one with the
        # element name LedBlinky's own controls editor uses.
        root = ET.Element("EmulatorList")
        tree = ET.ElementTree(root)

    existing = {el.get("name") for el in root.iter() if el.get("name")}
    added: list[str] = []
    for menu in menus:
        if menu in existing:
            continue
        entry = ET.SubElement(root, "game", name=menu)
        # An inline comment helps users understand where the entry came from
        # if they open the file in LedBlinky's editor.
        entry.set("controlGroup", "default")
        entry.set("spindoctor", "compat-stub")
        added.append(menu)

    if not added:
        return False, []

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    et_indent(tree)
    with open(dst_path, "wb") as f:
        f.write(b'<?xml version="1.0"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)
    return True, added


# ─── public API ───────────────────────────────────────────────────────────────

def scan(config: Config, menus: Optional[list[str]] = None) -> dict:
    """Audit the current setup for known LedBlinky × Search conflicts.

    Read-only. Always safe to run.
    """
    menus = menus or [SEARCH_MENU_NAMES[0]]   # default: Search

    controls_xml = _controls_xml_path(config)
    controls_xml_exists = controls_xml is not None and controls_xml.exists()
    declared = _controls_xml_menu_names(controls_xml) if controls_xml_exists else set()

    menu_inis: list[dict] = []
    for menu in menus:
        p = _menu_ini_path(config, menu)
        if p is None:
            continue
        menu_inis.append({
            "menu": menu,
            "path": p,
            "exists": p.exists(),
            "has_hooks": _ini_has_ledblinky_hook(p),
            "has_controls_entry": menu in declared,
        })

    # Also surface hooks in the global Settings.ini — informational only,
    # SpinDoctor does NOT touch this one (LedBlinky needs it to function).
    global_ini = _hs_settings_ini(config)
    global_has_hooks = _ini_has_ledblinky_hook(global_ini) if global_ini else False

    issues: list[str] = []
    if not config.ledblinky_dir:
        issues.append(
            "ledblinky_dir is not set. Run: "
            "spindoctor config set ledblinky_dir <path-to-LEDBlinky-folder>"
        )
    elif controls_xml is not None and not controls_xml_exists:
        issues.append(
            f"LEDBlinkyControls.xml not found at {controls_xml}. "
            "LedBlinky may not be installed at the configured ledblinky_dir."
        )

    for info in menu_inis:
        if info["has_hooks"]:
            issues.append(
                f"{info['menu']} menu Settings.ini contains a LedBlinky process hook "
                f"({info['path']}). This is the most common Search-crash trigger."
            )
        if controls_xml_exists and not info["has_controls_entry"]:
            issues.append(
                f"LEDBlinkyControls.xml has no entry for the '{info['menu']}' menu. "
                "LedBlinky's lookup will fail when this menu activates."
            )

    return {
        "ledblinky_dir_set": bool(config.ledblinky_dir),
        "ledblinky_dir_exists": bool(config.ledblinky_dir) and Path(config.ledblinky_dir).exists(),
        "controls_xml_path": controls_xml,
        "controls_xml_exists": controls_xml_exists,
        "menu_inis": menu_inis,
        "global_settings_ini": global_ini,
        "global_settings_has_hooks": global_has_hooks,
        "issues": issues,
        "ok": not issues,
    }


def apply_fix(
    config: Config,
    output_base: Optional[Path] = None,
    dry_run: bool = False,
    backup: bool = True,
    menus: Optional[list[str]] = None,
) -> dict:
    """Patch LEDBlinkyControls.xml and per-menu Settings.ini files.

    - When ``output_base`` is set, mirror the source folder structure under
      it instead of writing in-place. Backups are skipped in this mode.
    - When ``dry_run`` is set, return the same shape but write nothing.
    - When ``backup`` is True (default) and writing in-place, save a
      timestamped ``.YYYYMMDD_HHMMSS.bak`` next to each modified file.
    """
    menus = menus or [SEARCH_MENU_NAMES[0]]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    results: dict = {
        "dry_run": dry_run,
        "backup": backup and output_base is None,
        "menus": menus,
        "controls_xml": None,        # {"path": Path, "added": [...], "wrote": bool}
        "menu_inis": [],             # [{"menu":..., "path": Path, "lines_changed": int, "wrote": bool}]
        "errors": [],
    }

    # ── 1. LEDBlinkyControls.xml ──────────────────────────────────────────────
    src_xml = _controls_xml_path(config)
    if src_xml is None:
        results["errors"].append(
            "ledblinky_dir is not set; skipping LEDBlinkyControls.xml patch."
        )
    else:
        if output_base is not None:
            dst_xml = output_base / "LEDBlinky" / CONTROLS_XML_NAME
        else:
            dst_xml = src_xml

        # Figure out what would be added (without writing) so dry-run is honest.
        existing = _controls_xml_menu_names(src_xml)
        would_add = [m for m in menus if m not in existing]

        entry: dict = {
            "path": dst_xml,
            "src": src_xml,
            "added": would_add,
            "wrote": False,
        }

        if would_add and not dry_run:
            try:
                if backup and output_base is None and src_xml.exists():
                    shutil.copy2(src_xml, src_xml.with_suffix(src_xml.suffix + f".{stamp}.bak"))
                wrote, added = _ensure_controls_xml_entries(src_xml, dst_xml, menus)
                entry["added"] = added
                entry["wrote"] = wrote
            except (OSError, ValueError) as e:
                results["errors"].append(f"LEDBlinkyControls.xml: {e}")

        results["controls_xml"] = entry

    # ── 2. HyperSpin per-menu Settings.ini ────────────────────────────────────
    for menu in menus:
        src_ini = _menu_ini_path(config, menu)
        if src_ini is None:
            results["errors"].append(
                f"hyperspin_dir is not set; skipping {menu} menu INI patch."
            )
            continue

        if output_base is not None:
            dst_ini = output_base / "Menu" / menu / "Settings.ini"
        else:
            dst_ini = src_ini

        info: dict = {
            "menu": menu,
            "path": dst_ini,
            "src": src_ini,
            "lines_changed": 0,
            "wrote": False,
        }

        if not src_ini.exists():
            info["error"] = f"not found: {src_ini}"
            results["menu_inis"].append(info)
            continue

        try:
            text = src_ini.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            results["errors"].append(f"{menu} INI: {e}")
            results["menu_inis"].append(info)
            continue

        new_text, changed = _comment_out_hooks(text)
        info["lines_changed"] = changed

        if changed and not dry_run:
            try:
                if backup and output_base is None:
                    shutil.copy2(src_ini, src_ini.with_suffix(src_ini.suffix + f".{stamp}.bak"))
                dst_ini.parent.mkdir(parents=True, exist_ok=True)
                dst_ini.write_text(new_text, encoding="utf-8")
                info["wrote"] = True
            except OSError as e:
                results["errors"].append(f"{menu} INI: {e}")

        results["menu_inis"].append(info)

    return results


# ─── Settings.ini patch ────────────────────────────────────────────────────────


def list_lwa_files(config: Config) -> list[str]:
    """Return a sorted list of ``.lwa`` filenames found in ``ledblinky_dir``.

    These are the animation files LedBlinky can play.  The list is used to
    populate the FE-animation picker in the GUI and the dry-run hint in the CLI.
    Returns an empty list if ``ledblinky_dir`` is not set or the directory does
    not exist yet.
    """
    if not config.ledblinky_dir:
        return []
    base = Path(config.ledblinky_dir)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.glob("*.lwa") if p.is_file())


def _patch_ini_keys(
    text: str, patches: "dict[str, dict[str, str]]"
) -> "tuple[str, list[str]]":
    """Patch ``key=value`` pairs in specific sections of an INI text blob.

    ``patches`` maps ``{section_name: {key: new_value}}``.  Only lines whose
    key matches exactly (case-sensitive) are touched; everything else —
    comments, blank lines, ordering, line endings — is preserved verbatim.

    Returns ``(patched_text, list_of_human_readable_change_descriptions)``.
    """
    lines = text.splitlines(keepends=True)
    current_section: Optional[str] = None
    result: list[str] = []
    changes: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Track current [Section]
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
            result.append(line)
            continue

        if current_section and current_section in patches:
            section_patches = patches[current_section]
            replaced = False
            for key, new_value in section_patches.items():
                # Match "Key=..." or "Key =..." (with optional space before =)
                if re.match(rf"^{re.escape(key)}\s*=", stripped):
                    old_value = stripped.split("=", 1)[1]
                    if old_value != new_value:
                        ending = (
                            "\r\n" if line.endswith("\r\n")
                            else "\n" if line.endswith("\n")
                            else ""
                        )
                        result.append(f"{key}={new_value}{ending}")
                        changes.append(
                            f"[{current_section}] {key}: "
                            f"'{old_value}' → '{new_value}'"
                        )
                    else:
                        result.append(line)
                    replaced = True
                    break
            if not replaced:
                result.append(line)
        else:
            result.append(line)

    return "".join(result), changes


@dataclass
class SettingsPatchResult:
    """Outcome of :func:`patch_ledblinky_settings`."""

    settings_path: Optional[Path] = None
    backup_path: Optional[Path] = None
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False


def patch_ledblinky_settings(
    config: Config,
    fe_lwa_file: Optional[str] = None,
    game_play_lwa_file: str = "",
    dry_run: bool = True,
    backup: bool = True,
) -> SettingsPatchResult:
    """Patch ``<ledblinky_dir>/Settings.ini`` for better idle and in-game behavior.

    Parameters
    ----------
    fe_lwa_file:
        Animation file (basename only, e.g. ``"Slow Fade.lwa"``) to set as the
        frontend idle animation (``FELWAFile`` in ``[FEOptions]``).
        Pass ``None`` to leave the key unchanged.
        Pass ``""`` to silence all animation (static colors while browsing).
    game_play_lwa_file:
        Animation file for buttons *not* used by the current game during
        gameplay (``GamePlayLWAFile`` in ``[GameOptions]``).
        Defaults to ``""`` (empty string), which silences the random-flash on
        unused buttons and lets them fall back to their ``defaultInactive``
        color (typically ``0,0,0,0`` = off in the default control group).

    Raises
    ------
    ValueError
        If ``ledblinky_dir`` is not configured or ``Settings.ini`` is absent.
    """
    result = SettingsPatchResult(dry_run=dry_run)

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )

    settings_path = Path(config.ledblinky_dir) / "Settings.ini"
    result.settings_path = settings_path

    if not settings_path.exists():
        raise ValueError(f"Settings.ini not found at {settings_path}")

    text = settings_path.read_text(encoding="utf-8", errors="replace")

    # Build patch map — only include FELWAFile if caller explicitly passed a value.
    patches: dict[str, dict[str, str]] = {
        "GameOptions": {"GamePlayLWAFile": game_play_lwa_file},
    }
    if fe_lwa_file is not None:
        patches.setdefault("FEOptions", {})["FELWAFile"] = fe_lwa_file

    new_text, changes = _patch_ini_keys(text, patches)
    result.changes = changes

    if changes and not dry_run:
        if backup:
            result.backup_path = _backup(settings_path)
        settings_path.write_text(new_text, encoding="utf-8")

    return result


# ─── Color-RGB.ini management ─────────────────────────────────────────────────

COLOR_RGB_NAME = "Color-RGB.ini"


@dataclass
class ColorEntry:
    """One named color from ``Color-RGB.ini`` (intensity 0-48 per channel)."""

    name: str
    r: int   # 0-48
    g: int   # 0-48
    b: int   # 0-48

    def to_hex(self) -> str:
        """Return ``#RRGGBB`` string (0-48 intensity scaled to 0-255)."""
        return "#{:02X}{:02X}{:02X}".format(
            round(self.r / 48 * 255),
            round(self.g / 48 * 255),
            round(self.b / 48 * 255),
        )

    @classmethod
    def from_hex(cls, name: str, hex_str: str) -> "ColorEntry":
        """Build a :class:`ColorEntry` from a ``RRGGBB`` or ``#RRGGBB`` string.

        The 0-255 channel values are scaled down to the 0-48 intensity range
        used by ``Color-RGB.ini``.
        """
        h = hex_str.lstrip("#")
        if len(h) != 6:
            raise ValueError(
                f"Expected exactly 6 hex digits (RRGGBB), got '{hex_str}'"
            )
        r255 = int(h[0:2], 16)
        g255 = int(h[2:4], 16)
        b255 = int(h[4:6], 16)
        return cls(
            name=name,
            r=round(r255 / 255 * 48),
            g=round(g255 / 255 * 48),
            b=round(b255 / 255 * 48),
        )


def parse_color_rgb_ini(path: Path) -> "tuple[list[str], list[ColorEntry]]":
    """Parse ``Color-RGB.ini`` into header lines and ordered color entries.

    The *header* is every line that appears before ``[Colors]`` (comments,
    blanks, version sections) and is preserved verbatim on write so the file
    round-trips cleanly.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    header: list[str] = []
    entries: list[ColorEntry] = []
    in_colors = False

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.lower() == "[colors]":
            in_colors = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_colors = False
        if not in_colors:
            header.append(line)
            continue
        if not stripped or stripped.startswith(";"):
            continue
        if "=" in stripped:
            name_part, _, val = stripped.partition("=")
            parts = [p.strip() for p in val.split(",")]
            if len(parts) == 3:
                try:
                    entries.append(ColorEntry(
                        name=name_part.strip(),
                        r=int(parts[0]),
                        g=int(parts[1]),
                        b=int(parts[2]),
                    ))
                except ValueError:
                    pass  # skip malformed lines silently

    return header, entries


def write_color_rgb_ini(
    header: "list[str]",
    entries: "list[ColorEntry]",
    path: Path,
) -> None:
    """Write ``Color-RGB.ini``, reproducing the original header verbatim.

    Uses ``\\r\\n`` line endings (standard for LedBlinky Windows files).
    """
    lines: list[str] = list(header)
    # Drop trailing blank lines from the header — we'll add a fresh one
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append("")
    lines.append("[Colors]")
    for e in entries:
        lines.append(f"{e.name}={e.r},{e.g},{e.b}")
    lines.append("")
    path.write_text("\r\n".join(lines), encoding="utf-8")


def _replace_color_in_colors_ini(
    path: Path, old_name: str, new_name: str
) -> "tuple[str, int]":
    """Replace exact color-name values in ``Colors.ini``.

    Only touches lines where the entire value (right-hand side of ``=``) is
    exactly ``old_name``.  Hex-value entries such as ``ledcolor1=FF0000`` are
    not affected.

    Returns ``(new_text, replacement_count)``.  Does **not** write to disk.
    """
    if not path.exists():
        return "", 0
    text = path.read_text(encoding="utf-8", errors="replace")
    # ^(?!;)([^=]+=)  — non-comment line with a key=
    # \s*<OldName>\s*\r?$  — value is exactly old_name (with optional blanks)
    pattern = re.compile(
        rf"^(?!;)([^=]+=)\s*{re.escape(old_name)}\s*\r?$",
        re.MULTILINE,
    )
    new_text, count = pattern.subn(rf"\g<1>{new_name}", text)
    return new_text, count


def _replace_color_in_controls_xml(
    path: Path, old_name: str, new_name: str
) -> "tuple[str, int]":
    """Replace ``color="<old_name>"`` XML attributes in ``LEDBlinkyControls.xml``.

    Returns ``(new_text, replacement_count)``.  Does **not** write to disk.
    """
    if not path.exists():
        return "", 0
    text = path.read_text(encoding="utf-8", errors="replace")
    new_text, count = re.subn(
        rf'color="{re.escape(old_name)}"',
        f'color="{new_name}"',
        text,
    )
    return new_text, count


@dataclass
class ColorRenameResult:
    """Outcome of :func:`apply_color_rename`."""

    old_name: str
    new_name: str
    color_rgb_path: Optional[Path] = None
    colors_ini_replacements: int = 0
    controls_xml_replacements: int = 0
    backup_paths: list[Path] = field(default_factory=list)
    dry_run: bool = False


def apply_color_rename(
    config: Config,
    old_name: str,
    new_name: str,
    new_r: Optional[int] = None,
    new_g: Optional[int] = None,
    new_b: Optional[int] = None,
    dry_run: bool = True,
    backup: bool = True,
) -> ColorRenameResult:
    """Rename (and optionally recolor) a named color across all LEDBlinky files.

    The three files touched in order:

    1. ``Color-RGB.ini`` — the entry is renamed; R,G,B updated when provided.
    2. ``Colors.ini`` — every line whose value is exactly ``old_name`` is
       updated to ``new_name``.
    3. ``LEDBlinkyControls.xml`` — every ``color="<old_name>"`` attribute is
       updated to ``color="<new_name>"``.

    Parameters
    ----------
    new_r, new_g, new_b:
        New intensity values (0-48).  Pass ``None`` to keep the existing
        values (rename-only, no recolor).

    Raises
    ------
    ValueError
        If ``ledblinky_dir`` is not configured, ``Color-RGB.ini`` is absent,
        or ``old_name`` is not found in the file.
    """
    result = ColorRenameResult(
        old_name=old_name, new_name=new_name, dry_run=dry_run
    )

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )
    base = Path(config.ledblinky_dir)

    # ── 1. Color-RGB.ini ─────────────────────────────────────────────────────
    color_rgb_path = base / COLOR_RGB_NAME
    result.color_rgb_path = color_rgb_path
    if not color_rgb_path.exists():
        raise ValueError(f"{COLOR_RGB_NAME} not found at {color_rgb_path}")

    header, entries = parse_color_rgb_ini(color_rgb_path)
    names = [e.name for e in entries]
    if old_name not in names:
        raise ValueError(
            f"Color '{old_name}' not found in {COLOR_RGB_NAME}. "
            f"Available: {', '.join(names)}"
        )

    updated_entries = [
        ColorEntry(
            name=new_name,
            r=new_r if new_r is not None else e.r,
            g=new_g if new_g is not None else e.g,
            b=new_b if new_b is not None else e.b,
        )
        if e.name == old_name
        else e
        for e in entries
    ]

    # ── 2. Pre-compute replacements (safe, no writes yet) ────────────────────
    colors_ini_path = base / "Colors.ini"
    new_colors_ini_text, colors_ini_count = _replace_color_in_colors_ini(
        colors_ini_path, old_name, new_name
    )
    result.colors_ini_replacements = colors_ini_count

    controls_xml_path = base / CONTROLS_XML_NAME
    new_controls_xml_text, controls_xml_count = _replace_color_in_controls_xml(
        controls_xml_path, old_name, new_name
    )
    result.controls_xml_replacements = controls_xml_count

    if dry_run:
        return result

    # ── 3. Write with backups ─────────────────────────────────────────────────
    if backup:
        bp = _backup(color_rgb_path)
        if bp:
            result.backup_paths.append(bp)
    write_color_rgb_ini(header, updated_entries, color_rgb_path)

    if colors_ini_count > 0:
        if backup and colors_ini_path.exists():
            bp = _backup(colors_ini_path)
            if bp:
                result.backup_paths.append(bp)
        colors_ini_path.write_text(new_colors_ini_text, encoding="utf-8")

    if controls_xml_count > 0:
        if backup and controls_xml_path.exists():
            bp = _backup(controls_xml_path)
            if bp:
                result.backup_paths.append(bp)
        controls_xml_path.write_text(new_controls_xml_text, encoding="utf-8")

    return result
