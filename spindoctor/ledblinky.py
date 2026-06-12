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

import random as _random
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

    Uses LedBlinky's runtime key naming convention so the file is read
    correctly at game launch.  Each key is a recognised LedBlinky control
    name; LedBlinky treats any unknown key as a literal control identifier,
    so using the wrong names (e.g. ``P1_NUMBUTTONS``) would silently break
    LED mapping for the affected ROM.

    Output format::

        [<rom>]
        numPlayers=<n>
        alternating=0
        P<i>_BUTTON1=1
        P<i>_BUTTON2=1
        ...
        P<i>_JOYSTICK=1   (if the player has a joystick/stick input)
        P<i>_START=1
        P<i>_COIN=1

    ``numPlayers`` and ``alternating`` are metadata keys that LedBlinky
    recognises as such; they are not treated as control names.  Start and
    Coin entries are always written for every player present.  The key
    pattern matches ``synth_colors_section`` so that Colors.ini entries
    and Controls.ini entries refer to the same identifiers.

    Note: ``alternating`` is always written as ``0`` because MAME
    ``-listxml`` does not expose an alternating flag; this matches the
    behaviour of LedBlinky's own Controls Editor for MAME games.
    """
    # JOYSTICK_TYPES covers every MAME control type that maps to P{n}_JOYSTICK
    # in LedBlinky's naming convention (directional / analog stick inputs).
    _JOYSTICK_TYPES = frozenset({"joy", "doublejoy", "stick", "positional"})

    lines = [
        f"numPlayers={info.num_players}",
        "alternating=0",
    ]

    # Per-player rollup: track button count and whether a joystick is present.
    by_player: dict[str, dict] = {}
    for ctrl in info.raw_input:
        pid = ctrl.get("player") or "1"
        slot = by_player.setdefault(pid, {"buttons": 0, "has_joystick": False})
        try:
            slot["buttons"] = max(slot["buttons"], int(ctrl.get("buttons") or "0"))
        except ValueError:
            pass
        if (ctrl.get("type") or "").lower() in _JOYSTICK_TYPES:
            slot["has_joystick"] = True

    if not by_player and info.has_input:
        has_joy = any(ct.lower() in _JOYSTICK_TYPES for ct in info.control_types)
        by_player["1"] = {"buttons": info.num_buttons, "has_joystick": has_joy}

    for pid in sorted(by_player.keys()):
        slot = by_player[pid]
        for i in range(1, slot["buttons"] + 1):
            lines.append(f"P{pid}_BUTTON{i}=1")
        if slot["has_joystick"]:
            lines.append(f"P{pid}_JOYSTICK=1")
        lines.append(f"P{pid}_START=1")
        lines.append(f"P{pid}_COIN=1")

    return IniSection(name=info.rom_name, lines=lines)


def synth_colors_section(
    info: ControlInfo,
    palette: dict[str, str],
    named_palette: "Optional[list]" = None,
) -> IniSection:
    """Build a Colors.ini section for *info* using the configured default palette.

    When *named_palette* (a list of :class:`ColorEntry`) is supplied the
    output uses LedBlinky's native **named** format::

        P1_BUTTON1=Red
        P1_JOYSTICK=White
        P1_START=White
        P1_COIN=Orange

    When *named_palette* is ``None`` the legacy hex format is used instead
    (``ledcolor1=FF0000``, ``joystick=FFFFFF``, …).  The legacy format is not
    readable by LedBlinky itself; callers should always provide *named_palette*
    when ``Color-RGB.ini`` is available.
    """
    lines = []
    n = info.num_buttons or 6
    for i in range(1, n + 1):
        key = f"button{i}"
        hex_color = palette.get(key) or palette.get(f"button{((i - 1) % 6) + 1}", "FFFFFF")
        if named_palette is not None:
            color_name = _nearest_color_name(hex_color, named_palette)
            lines.append(f"P1_BUTTON{i}={color_name}")
        else:
            lines.append(f"ledcolor{i}={hex_color}")
    for old_key, new_key in (("joystick", "P1_JOYSTICK"), ("start", "P1_START"), ("coin", "P1_COIN")):
        if old_key in palette:
            hex_color = palette[old_key]
            if named_palette is not None:
                color_name = _nearest_color_name(hex_color, named_palette)
                lines.append(f"{new_key}={color_name}")
            else:
                lines.append(f"{old_key}={hex_color}")
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


def _backup(path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """Create a timestamped backup of *path*.

    When *backup_dir* is provided the backup is written to
    ``backup_dir / "LEDBlinky" / "<filename>.<stamp>.bak"`` (the subdirectory
    is created on demand).  When omitted the backup sits next to the source
    file as before.
    """
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if backup_dir:
        dest_dir = backup_dir / "LEDBlinky"
        dest_dir.mkdir(parents=True, exist_ok=True)
        backup = dest_dir / f"{path.name}.{stamp}.bak"
    else:
        backup = path.with_suffix(path.suffix + f".{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def _config_backup_dir(config: "Config") -> Optional[Path]:
    """Return ``Path(config.backup_dir)`` when configured, else ``None``."""
    return Path(config.backup_dir) if getattr(config, "backup_dir", None) else None


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
    src_controls = (src_base / CONTROLS_INI_NAME) if src_base else None
    src_colors = (src_base / COLORS_INI_NAME) if src_base else None

    existing_controls = (
        parse_existing_controls_ini(src_controls, warnings=result.warnings) if src_controls else {}
    )
    existing_colors = (
        parse_existing_colors_ini(src_colors, warnings=result.warnings) if src_colors else {}
    )

    # Load Color-RGB.ini so generate writes native P1_BUTTON1=Red format that
    # LedBlinky can actually read.  Fall back to legacy hex format with a warning
    # when Color-RGB.ini is absent so generate still works on a fresh install.
    named_palette = None
    if src_base is not None:
        color_rgb_path = src_base / COLOR_RGB_NAME
        if color_rgb_path.exists():
            try:
                _, named_palette = parse_color_rgb_ini(color_rgb_path)
            except Exception as exc:
                result.warnings.append(
                    f"Could not load {COLOR_RGB_NAME}: {exc} — "
                    f"colors.ini will use legacy ledcolor= format instead of P1_BUTTON1= named format. "
                    f"Run 'ledblinky colors normalize --apply' after generating."
                )
        else:
            result.warnings.append(
                f"{COLOR_RGB_NAME} not found at {color_rgb_path} — "
                f"colors.ini will use legacy ledcolor= format instead of P1_BUTTON1= named format. "
                f"Run 'ledblinky colors normalize --apply' after generating."
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
            out_colors[rom] = synth_colors_section(
                info, config.ledblinky_default_colors, named_palette=named_palette,
            )
            result.colors_synthesised += 1

    controls_path = base / CONTROLS_INI_NAME
    colors_path = base / COLORS_INI_NAME

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
        _bd = _config_backup_dir(config)
        _backup(controls_path, _bd)
        _backup(colors_path, _bd)

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


def inspect_rom(config: Config, rom_name: str) -> dict:
    """Collect all LEDBlinky-relevant data for one ROM for diagnostic purposes.

    Returns a dict with keys:

    ``rom_name``        — the name looked up
    ``colors_ini_path`` — Path to Colors.ini (may not exist)
    ``colors_entry``    — list of ``"key=value"`` strings from Colors.ini, or ``[]``
    ``controls_ini_path`` — Path to controls.ini
    ``controls_entry``  — list of ``"key=value"`` strings from controls.ini, or ``[]``
    ``xml_path``        — Path to LEDBlinkyControls.xml
    ``xml_emulators``   — list of emulator names found in the XML
    ``xml_rom_entries`` — list of ``{"emulator": ..., "attrs": {...}}`` for any
                          ``<game>``/``<rom>`` XML elements whose ``name`` attribute
                          matches *rom_name* (case-insensitive)
    ``log_path``        — guessed path to LEDBlinkyLog.txt
    ``listxml``         — ``{"players": N, "buttons": N, "controls": [...]}`` or ``None``
    ``warnings``        — list of diagnostic warning strings
    """
    result: dict = {
        "rom_name": rom_name,
        "colors_ini_path": None,
        "colors_entry": [],
        "controls_ini_path": None,
        "controls_entry": [],
        "xml_path": None,
        "xml_emulators": [],
        "xml_rom_entries": [],
        "log_path": None,
        "listxml": None,
        "warnings": [],
    }

    if not config.ledblinky_dir:
        result["warnings"].append("ledblinky_dir is not configured.")
        return result

    base = Path(config.ledblinky_dir)

    # Colors.ini
    colors_path = base / COLORS_INI_NAME
    result["colors_ini_path"] = colors_path
    if colors_path.exists():
        sections = parse_existing_colors_ini(colors_path)
        entry = sections.get(rom_name)
        if entry is None:
            # Try case-insensitive search
            lower = rom_name.lower()
            for k, v in sections.items():
                if k.lower() == lower:
                    entry = v
                    result["warnings"].append(
                        f"Colors.ini: found [{k}] (case differs from [{rom_name}]). "
                        f"LEDBlinky lookup is case-sensitive on some versions."
                    )
                    break
        result["colors_entry"] = entry.lines if entry else []
        if not entry:
            result["warnings"].append(
                f"Colors.ini: no section [{rom_name}] found — "
                f"LEDBlinky will use its DEFAULT control group colors."
            )
    else:
        result["warnings"].append(f"Colors.ini not found at {colors_path}.")

    # controls.ini
    controls_path = base / CONTROLS_INI_NAME
    result["controls_ini_path"] = controls_path
    if controls_path.exists():
        sections = parse_existing_controls_ini(controls_path)
        entry = sections.get(rom_name)
        if entry is None:
            lower = rom_name.lower()
            for k, v in sections.items():
                if k.lower() == lower:
                    entry = v
                    result["warnings"].append(
                        f"controls.ini: found [{k}] (case differs from [{rom_name}])."
                    )
                    break
        result["controls_entry"] = entry.lines if entry else []
        if not entry:
            result["warnings"].append(
                f"controls.ini: no section [{rom_name}] found — "
                f"LEDBlinky may not know which buttons this game uses."
            )
    else:
        result["warnings"].append(f"controls.ini not found at {controls_path}.")

    # LEDBlinkyControls.xml — scan for the ROM name and emulator structure
    xml_path = base / CONTROLS_XML_NAME
    result["xml_path"] = xml_path
    if xml_path.exists():
        try:
            import xml.etree.ElementTree as _ET
            tree = _ET.parse(xml_path)
            root = tree.getroot()
            # Collect emulator names
            emulators = []
            for el in root.iter():
                if el.tag.lower() in ("emulator", "game") and el.get("name"):
                    # "emulator" tag = top-level emulator entries
                    if el.tag.lower() == "emulator":
                        emulators.append(el.get("name"))
            result["xml_emulators"] = emulators
            # Search for rom_name as game/rom entry under any emulator
            lower = rom_name.lower()
            xml_entries = []
            for el in root.iter():
                n = el.get("name") or el.get("romName") or ""
                if n.lower() == lower and el.tag.lower() not in ("emulator",):
                    # find parent emulator name
                    parent_name = ""
                    for anc in root.iter():
                        if el in list(anc):
                            parent_name = anc.get("name") or anc.tag
                    xml_entries.append({
                        "tag": el.tag,
                        "emulator": parent_name,
                        "attrs": dict(el.attrib),
                    })
            result["xml_rom_entries"] = xml_entries
            if not xml_entries:
                result["warnings"].append(
                    f"LEDBlinkyControls.xml: no entry for [{rom_name}] found. "
                    f"LEDBlinky will use the DEFAULT control group for the emulator. "
                    f"Colors.ini overrides may or may not apply depending on LEDBlinky version."
                )
        except Exception as exc:
            result["warnings"].append(f"LEDBlinkyControls.xml could not be parsed: {exc}")
    else:
        result["warnings"].append(f"LEDBlinkyControls.xml not found at {xml_path}.")

    # LEDBlinky log file
    for log_name in ("LEDBlinkyLog.txt", "LedBlinkyLog.txt", "log.txt"):
        lp = base / log_name
        if lp.exists():
            result["log_path"] = lp
            break
    if result["log_path"] is None:
        result["log_path"] = base / "LEDBlinkyLog.txt"  # guessed path
        result["warnings"].append(
            f"LEDBlinky log not found at expected path ({result['log_path']}). "
            f"Enable logging in LEDBlinky's Settings to capture game-launch events."
        )

    # MAME listxml
    listxml = load_listxml_for_system(config, "MAME", warnings=result["warnings"])
    info = listxml.get(rom_name)
    if info:
        result["listxml"] = {
            "description": info.description,
            "players": info.num_players,
            "buttons": info.num_buttons,
            "controls": info.control_types,
            "has_input": info.has_input,
        }
    else:
        result["warnings"].append(
            f"MAME listxml: no entry for [{rom_name}] — "
            f"either MAME is not configured, or this ROM is not in MAME's database."
        )

    return result


def audit_coverage(config: Config, rom_names: Iterable[str]) -> list[CoverageRow]:
    """Return per-ROM coverage info: existing entries vs. -listxml synthesis."""
    src_base = Path(config.ledblinky_dir) if config.ledblinky_dir else None
    existing_controls = (
        parse_existing_controls_ini(src_base / CONTROLS_INI_NAME)
        if src_base else {}
    )
    existing_colors = (
        parse_existing_colors_ini(src_base / COLORS_INI_NAME)
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

# ── LedBlinky filename constants ──────────────────────────────────────────────
# All LedBlinky filenames are defined here as constants so there is a single
# source of truth for their exact casing.  LedBlinky is a Windows application
# and uses mixed-case names; Linux filesystems are case-sensitive, so even a
# single character difference (e.g. "colors.ini" vs "Colors.ini") silently
# breaks path lookups on CI and in real Linux deployments.
#
# Rule: never write a LedBlinky filename as a bare string literal anywhere in
# this module.  Always reference the constant.
CONTROLS_XML_NAME = "LEDBlinkyControls.xml"   # XML control database
CONTROLS_INI_NAME = "controls.ini"            # per-ROM button layout (lowercase — LedBlinky's own casing)
COLORS_INI_NAME   = "Colors.ini"              # per-ROM named colors  (capital C — LedBlinky's own casing)
# COLOR_RGB_NAME is defined further down, near its related functions.


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
      timestamped ``.YYYYMMDD_HHMMSS.bak`` for each modified file (under
      ``config.backup_dir/LEDBlinky/`` when set, else next to the file).
    """
    menus = menus or [SEARCH_MENU_NAMES[0]]

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
                    _backup(src_xml, _config_backup_dir(config))
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
                    _backup(src_ini, _config_backup_dir(config))
                dst_ini.parent.mkdir(parents=True, exist_ok=True)
                dst_ini.write_text(new_text, encoding="utf-8")
                info["wrote"] = True
            except OSError as e:
                results["errors"].append(f"{menu} INI: {e}")

        results["menu_inis"].append(info)

    return results


# ─── Settings.ini patch ────────────────────────────────────────────────────────


def list_lwa_files(config: Config) -> list[str]:
    """Return a sorted list of ``.lwa`` / ``.lwax`` paths relative to the ``lwa`` subdirectory.

    LedBlinky stores animation files in ``<ledblinky_dir>/lwa/`` and its
    subdirectories.  Both the classic ``.lwa`` and the newer ``.lwax`` (extended)
    formats are included.  The returned paths are relative to ``lwa/``
    (e.g. ``Slow Fade.lwax`` or ``subdir\\pattern.lwax``) because LedBlinky
    always prepends the ``lwa\\`` prefix itself when resolving ``FELWAFile``
    and ``GamePlayLWAFile`` in ``Settings.ini``.  Returning the full
    ``lwa\\Slow Fade.lwax`` path would produce a double ``lwa\\lwa\\`` prefix.

    Returns an empty list if ``ledblinky_dir`` is not set or the ``lwa``
    subdirectory does not exist yet.
    """
    if not config.ledblinky_dir:
        return []
    lwa_dir = Path(config.ledblinky_dir) / "lwa"
    if not lwa_dir.is_dir():
        return []
    matches = [
        p
        for p in lwa_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".lwa", ".lwax")
    ]
    return sorted(str(p.relative_to(lwa_dir)) for p in matches)


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
    ss_lwa_file: Optional[str] = None,
    game_play_lwa_file: str = "",
    dry_run: bool = True,
    backup: bool = True,
) -> SettingsPatchResult:
    """Patch ``<ledblinky_dir>/Settings.ini`` for better idle and in-game behavior.

    Parameters
    ----------
    fe_lwa_file:
        Animation file (basename only, e.g. ``"Slow Fade.lwa"``) to set as the
        frontend active animation (``FELWAFile`` in ``[FEOptions]``).
        Pass ``None`` to leave the key unchanged.
        Pass ``""`` to silence all animation (static colors while browsing).
    ss_lwa_file:
        Animation file to set as the screen saver animation
        (``FEScreenSaverLWAFile`` in ``[FEOptions]``).
        Pass ``None`` to leave the key unchanged.
        Pass ``""`` to silence the screen saver animation.
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

    # Build patch map — only include FE/SS keys if caller explicitly passed a value.
    patches: dict[str, dict[str, str]] = {
        "GameOptions": {
            "GamePlayLWAFile": game_play_lwa_file,
        },
    }
    if fe_lwa_file is not None:
        patches.setdefault("FEOptions", {})["FELWAFile"] = fe_lwa_file
    if ss_lwa_file is not None:
        patches.setdefault("FEOptions", {})["FEScreenSaverLWAFile"] = ss_lwa_file

    new_text, changes = _patch_ini_keys(text, patches)
    result.changes = changes

    if changes and not dry_run:
        if backup:
            result.backup_path = _backup(settings_path, _config_backup_dir(config))
        settings_path.write_text(new_text, encoding="utf-8")

    return result


def read_ledblinky_settings_keys(config: Config) -> "dict[str, str]":
    """Read current values of the patchable animation keys from ``Settings.ini``.

    Returns a dict keyed by INI key name
    (e.g. ``{"FELWAFile": "Slow Fade.lwa", "FEScreenSaverLWAFile": "Slow Fade.lwa"}``).
    Keys absent from the file are absent from the result.
    Returns an empty dict if ``ledblinky_dir`` is not configured or
    ``Settings.ini`` is absent.
    """
    if not config.ledblinky_dir:
        return {}
    settings_path = Path(config.ledblinky_dir) / "Settings.ini"
    if not settings_path.exists():
        return {}

    targets: dict[str, set[str]] = {
        "FEOptions": {"FELWAFile", "FEScreenSaverLWAFile"},
        "GameOptions": {"GamePlayLWAFile"},
    }
    result: dict[str, str] = {}
    current_section: Optional[str] = None

    for line in settings_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
            continue
        if current_section and current_section in targets:
            for key in targets[current_section]:
                if re.match(rf"^{re.escape(key)}\s*=", stripped):
                    result[key] = stripped.split("=", 1)[1]
                    break

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
        try:
            r255 = int(h[0:2], 16)
            g255 = int(h[2:4], 16)
            b255 = int(h[4:6], 16)
        except ValueError:
            raise ValueError(
                f"'{hex_str}' contains invalid characters. "
                "Expected 6 hex digits (0-9, A-F), e.g. 'FF0000' for red."
            )
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
    # Write with explicit newline="" so Python's text-mode translation does not
    # double the \r on Windows (open() newline="" has been supported since
    # Python 3.0; write_text(newline=) only exists from Python 3.10+).
    with path.open("w", encoding="utf-8", newline="") as _fh:
        _fh.write("\r\n".join(lines))


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
    # Validate new RGB values are within the 0-48 intensity range
    for _ch, _val in (("R", new_r), ("G", new_g), ("B", new_b)):
        if _val is not None and not (0 <= _val <= 48):
            raise ValueError(
                f"{_ch} value {_val} is outside the valid 0-48 intensity range "
                f"(LedBlinky uses 0-48, not 0-255). "
                f"Use --hex for standard 8-bit hex input."
            )

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
    colors_ini_path = base / COLORS_INI_NAME
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
    _bd = _config_backup_dir(config)
    if backup:
        bp = _backup(color_rgb_path, _bd)
        if bp:
            result.backup_paths.append(bp)
    write_color_rgb_ini(header, updated_entries, color_rgb_path)

    if colors_ini_count > 0:
        if backup and colors_ini_path.exists():
            bp = _backup(colors_ini_path, _bd)
            if bp:
                result.backup_paths.append(bp)
        colors_ini_path.write_text(new_colors_ini_text, encoding="utf-8")

    if controls_xml_count > 0:
        if backup and controls_xml_path.exists():
            bp = _backup(controls_xml_path, _bd)
            if bp:
                result.backup_paths.append(bp)
        controls_xml_path.write_text(new_controls_xml_text, encoding="utf-8")

    return result


# ─── Colors.ini normalisation ─────────────────────────────────────────────────

# Regex matching SpinDoctor-generated hex button keys: ledcolor1, ledcolor2, …
_LEDCOLOR_RE = re.compile(r"^ledcolor(\d+)$", re.IGNORECASE)

# Other legacy hex-value keys → canonical P1_ names
_LEGACY_KEY_MAP: dict[str, str] = {
    "joystick": "P1_JOYSTICK",
    "start":    "P1_START",
    "coin":     "P1_COIN",
}


def _is_hex_color(val: str) -> bool:
    """Return ``True`` if *val* is a bare 6-character hex string (``FF0000``)."""
    return bool(re.fullmatch(r"[0-9A-Fa-f]{6}", val))


def _nearest_color_name(hex_code: str, palette: "list[ColorEntry]") -> str:
    """Return the palette entry name closest to *hex_code* (``RRGGBB``) in RGB space.

    Distance is Euclidean in 0-255 space; ties broken by palette insertion order.
    An exact match short-circuits the search immediately.
    """
    r = int(hex_code[0:2], 16)
    g = int(hex_code[2:4], 16)
    b = int(hex_code[4:6], 16)
    best_name = palette[0].name
    best_dist: float = float("inf")
    for entry in palette:
        er = round(entry.r / 48 * 255)
        eg = round(entry.g / 48 * 255)
        eb = round(entry.b / 48 * 255)
        dist = (r - er) ** 2 + (g - eg) ** 2 + (b - eb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = entry.name
        if dist == 0:
            break  # exact match — stop early
    return best_name


@dataclass
class NormalizeResult:
    """Return value from :func:`normalize_colors_ini`."""

    colors_ini_path: Optional[Path] = None
    sections_converted: int = 0
    keys_converted: int = 0
    backup_path: Optional[Path] = None
    dry_run: bool = False
    # Per-section detail for --verbose: (section_name, [(old_key, new_key, color_name), ...])
    converted_details: "list[tuple[str, list[tuple[str, str, str]]]]" = field(default_factory=list)


def normalize_colors_ini(
    config,
    dry_run: bool = True,
    backup: bool = True,
) -> NormalizeResult:
    """Convert hex-format ``Colors.ini`` entries to named ``P1_*`` format.

    SpinDoctor generates ``Colors.ini`` sections using bare hex values::

        [powerins]
        ledcolor1=FF0000
        ledcolor2=FFFF00
        joystick=FFFFFF
        start=FFFFFF
        coin=FF8000

    The preferred (LedBlinky-native) form uses named colours::

        [powerins]
        P1_BUTTON1=Red
        P1_BUTTON2=Yellow
        P1_JOYSTICK=White
        P1_START=White
        P1_COIN=Orange

    This function rewrites every section that contains convertible hex-format
    keys using nearest-colour matching against ``Color-RGB.ini``.  Sections
    that already use named keys (``P1_BUTTON1=White``) are left **completely
    untouched**.

    Key mapping
    -----------
    ``ledcolor1`` → ``P1_BUTTON1``, ``ledcolor2`` → ``P1_BUTTON2``, …
    ``joystick``  → ``P1_JOYSTICK``,  ``start`` → ``P1_START``,
    ``coin``      → ``P1_COIN``

    Any other key whose value happens to be a 6-char hex string is left alone
    (only the explicitly mapped keys are converted).

    Raises
    ------
    ValueError
        If ``ledblinky_dir`` is not configured, or ``Colors.ini`` /
        ``Color-RGB.ini`` is absent or empty.
    """
    result = NormalizeResult(dry_run=dry_run)

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )
    base = Path(config.ledblinky_dir)

    colors_ini_path = base / COLORS_INI_NAME
    result.colors_ini_path = colors_ini_path
    if not colors_ini_path.exists():
        raise ValueError(f"Colors.ini not found at {colors_ini_path}")

    color_rgb_path = base / COLOR_RGB_NAME
    if not color_rgb_path.exists():
        raise ValueError(f"{COLOR_RGB_NAME} not found at {color_rgb_path}")

    _, palette = parse_color_rgb_ini(color_rgb_path)
    if not palette:
        raise ValueError(f"{COLOR_RGB_NAME} contains no colour entries")

    text = colors_ini_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    # key_changes accumulates (old_key, new_key, color_name) per converted line
    def _flush(
        buf: "list[str]", has_hex: bool
    ) -> "tuple[list[str], int, int, list[tuple[str, str, str]]]":
        """Rewrite *buf* if *has_hex*; return (lines, secs_delta, keys_delta, key_changes)."""
        if not has_hex:
            return buf, 0, 0, []
        new_buf: list[str] = []
        kc = 0
        key_changes: "list[tuple[str, str, str]]" = []
        for ln in buf:
            stripped = ln.rstrip("\r\n")
            eol = ln[len(stripped):]
            if "=" in stripped and not stripped.lstrip().startswith(";"):
                key_s, _, val_s = stripped.partition("=")
                key_s = key_s.strip()
                val_s = val_s.strip()
                if _is_hex_color(val_s):
                    m = _LEDCOLOR_RE.match(key_s)
                    if m:
                        new_key = f"P1_BUTTON{m.group(1)}"
                        color_name = _nearest_color_name(val_s, palette)
                        new_buf.append(f"{new_key}={color_name}{eol}")
                        key_changes.append((key_s, new_key, color_name))
                        kc += 1
                        continue
                    mapped = _LEGACY_KEY_MAP.get(key_s.lower())
                    if mapped:
                        color_name = _nearest_color_name(val_s, palette)
                        new_buf.append(f"{mapped}={color_name}{eol}")
                        key_changes.append((key_s, mapped, color_name))
                        kc += 1
                        continue
            new_buf.append(ln)
        return new_buf, 1, kc, key_changes

    out_lines: list[str] = []
    section_buffer: list[str] = []
    current_section_name: str = ""
    section_has_hex = False
    sections_converted = 0
    keys_converted = 0
    converted_details: "list[tuple[str, list[tuple[str, str, str]]]]" = []

    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
            # Flush the previous section
            if section_buffer:
                flushed, sc, kc, kchanges = _flush(section_buffer, section_has_hex)
                out_lines.extend(flushed)
                sections_converted += sc
                keys_converted += kc
                if kchanges:
                    converted_details.append((current_section_name, kchanges))
            # Start a new section
            current_section_name = stripped[1:-1]
            section_buffer = [line]
            section_has_hex = False
        elif section_buffer:
            # Detect whether this section needs conversion
            if "=" in stripped and not stripped.lstrip().startswith(";"):
                k, _, v = stripped.partition("=")
                k = k.strip()
                v = v.strip()
                if _is_hex_color(v) and (
                    _LEDCOLOR_RE.match(k) or k.lower() in _LEGACY_KEY_MAP
                ):
                    section_has_hex = True
            section_buffer.append(line)
        else:
            # Lines before the first section header
            out_lines.append(line)

    # Flush the final section
    if section_buffer:
        flushed, sc, kc, kchanges = _flush(section_buffer, section_has_hex)
        out_lines.extend(flushed)
        sections_converted += sc
        keys_converted += kc
        if kchanges:
            converted_details.append((current_section_name, kchanges))

    result.sections_converted = sections_converted
    result.keys_converted = keys_converted
    result.converted_details = converted_details

    if keys_converted > 0 and not dry_run:
        if backup:
            result.backup_path = _backup(colors_ini_path, _config_backup_dir(config))
        colors_ini_path.write_text("".join(out_lines), encoding="utf-8")

    return result


# ─── Colors.ini default-entry fill ────────────────────────────────────────────

# Controls that make up the "default" entry for an unsupported ROM.
_DEFAULT_FILL_CONTROLS = (
    ("P1_BUTTON1", "P1_BUTTON2", "P1_BUTTON3",
     "P1_BUTTON4", "P1_BUTTON5", "P1_BUTTON6"),  # indexed, trimmed to n_buttons
    ("P1_JOYSTICK", "P1_START", "P1_COIN"),       # always included
)


@dataclass
class FillDefaultsResult:
    """Return value from :func:`fill_default_colors`."""

    colors_ini_path: Optional[Path] = None
    roms_checked: int = 0
    roms_added: int = 0
    roms_overridden: int = 0      # existing uniform sections updated
    roms_skipped_mixed: int = 0   # existing mixed-color sections left untouched
    backup_path: Optional[Path] = None
    dry_run: bool = False
    added_rom_names: "list[str]" = field(default_factory=list)
    overridden_rom_names: "list[str]" = field(default_factory=list)


# ── fill-defaults helpers ──────────────────────────────────────────────────────

#: Matches P{n}_BUTTON{i}, P{n}_JOYSTICK, P{n}_START, P{n}_COIN (all players).
_PLAYER_KEY_RE = re.compile(
    r"^P(\d+)_(BUTTON\d+|JOYSTICK|START|COIN)\s*=\s*(.*?)\s*$",
    re.IGNORECASE,
)


def _split_ini_by_sections(
    text: str,
) -> "list[tuple[Optional[str], Optional[str], list[str]]]":
    """Split INI text into ``(section_name, original_header_line, body_lines)`` tuples.

    The very first tuple has ``section_name=None`` and ``header_line=None``
    for any content that precedes the first ``[header]`` line.  Each
    ``body_lines`` list contains the raw lines (with original line endings)
    that belong to that section, *excluding* the header line itself.
    """
    result: "list[tuple[Optional[str], Optional[str], list[str]]]" = []
    current_name: Optional[str] = None
    current_header: Optional[str] = None
    current_lines: "list[str]" = []

    for line in text.splitlines(keepends=True):
        m = re.match(r"^\[([^\]]+)\]", line.rstrip("\r\n"))
        if m:
            result.append((current_name, current_header, current_lines))
            current_name = m.group(1).strip()
            current_header = line
            current_lines = []
        else:
            current_lines.append(line)

    result.append((current_name, current_header, current_lines))
    return result


def _uniform_section_color(body_lines: "list[str]") -> "Optional[str]":
    """Return the single color if **every** ``P*_BUTTON/JOYSTICK/START/COIN``
    key in *body_lines* shares the same value.

    Returns ``None`` when the colors are mixed, or when there are no matching
    keys at all (can't determine uniformity for an empty / hex-only section).
    """
    values: "set[str]" = set()
    for line in body_lines:
        m = _PLAYER_KEY_RE.match(line.strip())
        if m:
            values.add(m.group(3))  # the value after "="
    if len(values) == 1:
        return values.pop()
    return None


def _rewrite_section_body(
    body_lines: "list[str]",
    new_color: str,
    n_players: int,
    n_buttons: int,
    admin_player: int,
    admin_buttons: int,
    admin_color: str,
    no_add_keys: bool,
) -> "list[str]":
    """Return *body_lines* with every ``P*_BUTTON/JOYSTICK/START/COIN``
    value replaced by *new_color* (or *admin_color* for the admin player).

    When *no_add_keys* is ``False``, any missing keys (up to ``n_players ×
    n_buttons`` plus optional admin block) are **appended** before trailing
    blank lines so the section stays compact.

    When *no_add_keys* is ``True``, only existing keys are updated — no new
    keys are inserted.
    """
    result: "list[str]" = []
    existing_upper: "set[str]" = set()

    for line in body_lines:
        stripped = line.strip()
        m = _PLAYER_KEY_RE.match(stripped)
        if m:
            key_full = f"P{m.group(1)}_{m.group(2)}"
            p_num = int(m.group(1))
            upper_key = key_full.upper()
            existing_upper.add(upper_key)
            color = (
                admin_color
                if admin_buttons > 0 and p_num == admin_player
                else new_color
            )
            # Preserve original line ending
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            result.append(f"{key_full}={color}{ending}")
        else:
            result.append(line)

    if no_add_keys:
        return result

    # Build the list of keys to add (preserving the generated ordering)
    to_add: "list[str]" = []
    for p in range(1, n_players + 1):
        px = f"P{p}"
        for i in range(1, n_buttons + 1):
            if f"{px}_BUTTON{i}".upper() not in existing_upper:
                to_add.append(f"{px}_BUTTON{i}={new_color}\n")
        for suffix in ("JOYSTICK", "START", "COIN"):
            if f"{px}_{suffix}".upper() not in existing_upper:
                to_add.append(f"{px}_{suffix}={new_color}\n")
    if admin_buttons > 0:
        ap = f"P{admin_player}"
        for i in range(1, admin_buttons + 1):
            if f"{ap}_BUTTON{i}".upper() not in existing_upper:
                to_add.append(f"{ap}_BUTTON{i}={admin_color}\n")
        for suffix in ("COIN", "START"):
            if f"{ap}_{suffix}".upper() not in existing_upper:
                to_add.append(f"{ap}_{suffix}={admin_color}\n")

    if not to_add:
        return result

    # Insert additions before any trailing blank lines to keep structure tidy
    insert_idx = len(result)
    while insert_idx > 0 and result[insert_idx - 1].strip() == "":
        insert_idx -= 1
    for addition in reversed(to_add):
        result.insert(insert_idx, addition)

    return result


def _rewrite_colors_ini_with_overrides(
    text: str,
    roms_to_override: "set[str]",
    new_color: str,
    n_players: int,
    n_buttons: int,
    admin_player: int,
    admin_buttons: int,
    admin_color: str,
    no_add_keys: bool,
) -> "tuple[str, int]":
    """Rewrite *text* (a full Colors.ini) so that every section whose name is
    in *roms_to_override* has its player-button values replaced in-place.

    Returns ``(new_text, count_of_sections_updated)``.
    """
    sections = _split_ini_by_sections(text)
    parts: "list[str]" = []
    updated = 0

    for section_name, header_line, body_lines in sections:
        if section_name is None:
            # Content before the first [header] — preserve verbatim
            parts.extend(body_lines)
            continue

        assert header_line is not None  # guaranteed when section_name is set
        parts.append(header_line)

        if section_name in roms_to_override:
            new_body = _rewrite_section_body(
                body_lines,
                new_color,
                n_players,
                n_buttons,
                admin_player,
                admin_buttons,
                admin_color,
                no_add_keys,
            )
            parts.extend(new_body)
            updated += 1
        else:
            parts.extend(body_lines)

    return "".join(parts), updated


def fill_default_colors(
    config: Config,
    default_color: str = "White",
    n_buttons: int = 6,
    n_players: int = 1,
    admin_buttons: int = 0,
    admin_color: str = "White",
    override_uniform: bool = False,
    no_add_keys: bool = False,
    system: Optional[str] = None,
    dry_run: bool = True,
    backup: bool = True,
) -> FillDefaultsResult:
    """Add default ``Colors.ini`` entries for ROMs that have no LED mapping yet.

    SpinDoctor's ``ledblinky generate`` populates ``Colors.ini`` from MAME
    data.  ROMs from other systems (consoles, non-MAME arcade boards) have no
    entry, so LedBlinky treats all their buttons as inactive and turns them
    off.  This function closes that gap by appending a uniform default entry
    for every ROM in the HyperSpin databases that is not already covered.

    With ``n_players=2`` and ``n_buttons=8`` each generated entry looks like::

        [rom_name]
        P1_BUTTON1=White
        ...
        P1_BUTTON8=White
        P1_JOYSTICK=White
        P1_START=White
        P1_COIN=White
        P2_BUTTON1=White
        ...
        P2_BUTTON8=White
        P2_JOYSTICK=White
        P2_START=White
        P2_COIN=White

    If ``admin_buttons > 0`` an additional admin block is appended using the
    next available player number (``n_players + 1``) with ``admin_color``::

        P3_BUTTON1=Green
        ...
        P3_BUTTON6=Green
        P3_COIN=Green
        P3_START=Green

    **Overriding existing uniform entries** (``override_uniform=True``):

    When *override_uniform* is ``True``, ROMs that already have a section in
    ``Colors.ini`` are also examined.  If **every** ``P*_BUTTON/JOYSTICK/START/
    COIN`` key in that section has the **same** value (i.e. the entry is
    uniform), that section is updated in-place with *default_color*.  Sections
    with mixed colors are left completely untouched — only all-the-same entries
    qualify for override.

    The ``no_add_keys`` flag (only meaningful with ``override_uniform=True``)
    controls whether missing button keys are added:

    * ``no_add_keys=False`` (default): override the existing values **and**
      fill in any missing ``P*_BUTTON`` / ``JOYSTICK`` / ``START`` / ``COIN``
      keys up to the requested ``n_players × n_buttons`` count.
    * ``no_add_keys=True``: **only** replace the values of keys that are
      already present — do not add any new keys.  Use this when a section
      intentionally has fewer buttons (e.g. a 3-button game) and you don't
      want to extend it.

    Synthetic wheels (Favorites, Recently Played, Most Played) are included in
    the scan so that games that appear only in those wheels also receive a
    default entry.  Because ``Colors.ini`` is keyed by ROM name (not by
    system), any ROM whose name already appears in a real-system entry is
    automatically covered for synthetic wheels too.

    Parameters
    ----------
    default_color:
        Named color from ``Color-RGB.ini`` to assign to every player button.
        Defaults to ``"White"``.
    n_buttons:
        Number of ``P{n}_BUTTON`` entries to generate per player (1-8).
        Defaults to 6.
    n_players:
        Number of player blocks to generate (1-4).  Blocks are always
        mirrored — every player gets the same ``default_color``.  Defaults to 1.
    admin_buttons:
        Number of extra "admin/cabinet" button entries to add using the next
        player slot (``n_players + 1``).  0 disables the admin block.
    admin_color:
        Named color for the admin button block.  Validated against
        ``Color-RGB.ini`` the same as ``default_color``.
    override_uniform:
        When ``True``, existing sections where all button colors are identical
        are updated with *default_color*.  Mixed-color sections are never
        modified.  Defaults to ``False``.
    no_add_keys:
        Only meaningful when *override_uniform* is ``True``.  When ``True``,
        only update values of **already-present** keys; do not add new
        ``P*_BUTTON``, ``JOYSTICK``, ``START``, or ``COIN`` keys.  Defaults
        to ``False``.
    system:
        If given, only process ROMs for this one system.  By default all
        systems (including synthetic wheels) are processed.

    Raises
    ------
    ValueError
        If ``ledblinky_dir`` or ``databases_dir`` is not configured, or
        ``Colors.ini`` is absent.
    """
    from .config import get_systems
    from .database import find_database, load_database

    result = FillDefaultsResult(dry_run=dry_run)

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )
    if not config.databases_dir or not Path(config.databases_dir).exists():
        raise ValueError(
            "databases_dir not configured or not found. "
            "Run: spindoctor config set databases_dir <path>"
        )

    colors_ini_path = Path(config.ledblinky_dir) / COLORS_INI_NAME
    result.colors_ini_path = colors_ini_path
    if not colors_ini_path.exists():
        raise ValueError(f"Colors.ini not found at {colors_ini_path}")

    # Validate color names against Color-RGB.ini palette
    color_rgb_path = Path(config.ledblinky_dir) / COLOR_RGB_NAME
    if color_rgb_path.exists():
        _, palette = parse_color_rgb_ini(color_rgb_path)
        valid_names = {e.name for e in palette}
        for label, color in (("default", default_color), ("admin", admin_color)):
            if color not in valid_names:
                raise ValueError(
                    f"{label.capitalize()} color '{color}' not found in "
                    f"{COLOR_RGB_NAME}. Available: {', '.join(sorted(valid_names))}"
                )

    n_buttons = max(1, min(8, n_buttons))
    n_players = max(1, min(4, n_players))
    admin_buttons = max(0, admin_buttons)
    admin_player = n_players + 1  # e.g. P3 when n_players=2

    # Read existing Colors.ini sections (strip whitespace from names to be safe)
    existing_text = colors_ini_path.read_text(encoding="utf-8", errors="replace")
    existing_sections: set[str] = {
        m.strip()
        for m in re.findall(r"^\[([^\]]+)\]", existing_text, re.MULTILINE)
    }

    # Pre-parse section bodies for the override path (only when needed)
    if override_uniform:
        _ini_sections = _split_ini_by_sections(existing_text)
        _section_bodies: "dict[str, list[str]]" = {
            name: lines
            for name, _hdr, lines in _ini_sections
            if name is not None
        }
    else:
        _section_bodies = {}

    # Discover which systems to scan — include synthetic wheels so games that
    # only appear in Favorites / Recently Played / Most Played are covered too.
    if system:
        systems_to_scan = [system]
    else:
        systems_to_scan = list(get_systems(config))

    new_entries: list[str] = []
    new_entry_names: list[str] = []
    roms_to_override: "set[str]" = set()
    _seen_override_check: "set[str]" = set()  # prevent double-counting across systems
    roms_checked = 0

    for sys_name in systems_to_scan:
        db_path = find_database(sys_name, Path(config.databases_dir))
        if db_path is None:
            continue
        try:
            db = load_database(sys_name, Path(config.databases_dir))
        except Exception:
            continue
        for rom_name in db.games():
            roms_checked += 1
            if rom_name in existing_sections:
                # ROM already has a Colors.ini section.  Check for override.
                if override_uniform and rom_name not in _seen_override_check:
                    _seen_override_check.add(rom_name)
                    body = _section_bodies.get(rom_name, [])
                    if _uniform_section_color(body) is not None:
                        roms_to_override.add(rom_name)
                    else:
                        result.roms_skipped_mixed += 1
                continue
            # ROM has no section at all — build a full default entry
            lines = [f"[{rom_name}]"]
            for p in range(1, n_players + 1):
                prefix = f"P{p}"
                for i in range(1, n_buttons + 1):
                    lines.append(f"{prefix}_BUTTON{i}={default_color}")
                lines.append(f"{prefix}_JOYSTICK={default_color}")
                lines.append(f"{prefix}_START={default_color}")
                lines.append(f"{prefix}_COIN={default_color}")
            # Admin/cabinet button block (optional)
            if admin_buttons > 0:
                ap = f"P{admin_player}"
                for i in range(1, admin_buttons + 1):
                    lines.append(f"{ap}_BUTTON{i}={admin_color}")
                lines.append(f"{ap}_COIN={admin_color}")
                lines.append(f"{ap}_START={admin_color}")
            lines.append("")  # blank line between sections
            new_entries.append("\n".join(lines))
            new_entry_names.append(rom_name)
            # Mark as seen so a ROM appearing in multiple system databases
            # is only emitted once (Colors.ini does not support duplicate sections).
            existing_sections.add(rom_name)

    result.roms_checked = roms_checked
    result.roms_added = len(new_entries)
    result.roms_overridden = len(roms_to_override)
    result.added_rom_names = new_entry_names
    result.overridden_rom_names = sorted(roms_to_override)

    needs_write = bool(new_entries) or bool(roms_to_override)

    if needs_write and not dry_run:
        if backup:
            result.backup_path = _backup(colors_ini_path, _config_backup_dir(config))

        if roms_to_override:
            new_text, _ = _rewrite_colors_ini_with_overrides(
                existing_text,
                roms_to_override,
                default_color,
                n_players,
                n_buttons,
                admin_player,
                admin_buttons,
                admin_color,
                no_add_keys,
            )
        else:
            new_text = existing_text

        if new_entries:
            separator = "\n" if new_text.endswith("\n") else "\n\n"
            new_text = new_text + separator + "\n".join(new_entries)

        colors_ini_path.write_text(new_text, encoding="utf-8")

    return result


# ─── Color-RGB.ini brightness scaling ─────────────────────────────────────────


@dataclass
class BrightnessResult:
    """Return value from :func:`scale_colors_brightness`."""

    dry_run: bool
    color_rgb_path: Optional[Path] = None
    colors_scaled: int = 0
    backup_path: Optional[Path] = None
    scale_pct: float = 100.0
    # Per-color detail for --verbose: (name, old_r,g,b, new_r,g,b)
    color_changes: "list[tuple[str, int, int, int, int, int, int]]" = field(default_factory=list)


def _normalize_scale_entry(entry: ColorEntry, factor: float) -> ColorEntry:
    """Return *entry* with channels normalized to max intensity, then scaled.

    The dominant channel (``max(R, G, B)``) is always brought to 48 before
    applying *factor*, so ``factor=1.0`` produces the brightest possible
    representation of every color regardless of how dimly it was previously
    stored.  Hue and saturation ratios are preserved exactly.

    Pure-black entries (all-zero) are returned unchanged so true "off"
    buttons remain off.
    """
    mx = max(entry.r, entry.g, entry.b)
    if mx == 0:
        return ColorEntry(name=entry.name, r=0, g=0, b=0)
    scale = (48.0 / mx) * factor
    return ColorEntry(
        name=entry.name,
        r=min(48, round(entry.r * scale)),
        g=min(48, round(entry.g * scale)),
        b=min(48, round(entry.b * scale)),
    )


def scale_colors_brightness(
    config: Config,
    scale_pct: float,
    dry_run: bool = True,
    backup: bool = True,
) -> BrightnessResult:
    """Set all ``Color-RGB.ini`` colors to a uniform brightness level.

    Every color is first **normalized to its maximum possible intensity**
    (dominant channel → 48), then scaled down by ``scale_pct / 100``.  This
    means:

    * ``scale_pct=100`` — every color at **full brightness** (dominant channel
      = 48).  Colors that were previously stored at reduced intensity are
      brought up to their maximum.
    * ``scale_pct=50``  — half brightness; all dominant channels = 24.
    * ``scale_pct=10``  — near-dark night mode; dominant channel ≈ 5.
    * ``scale_pct=0``   — all buttons off.

    Because the normalization step is applied before scaling, **all buttons
    across all player slots are guaranteed to be at the same brightness level**
    at any given percentage — the Start button is never dimmer than P1_BUTTON1,
    and admin buttons are never dimmer than game buttons.

    Pure-black entries (0,0,0) are left untouched.

    Parameters
    ----------
    scale_pct:
        Target brightness as a percentage (0–100).  Values above 100 are
        clamped to 100.
    dry_run:
        When ``True`` (default) no files are written.
    backup:
        When ``True`` (default) a timestamped backup of ``Color-RGB.ini`` is
        created before writing.

    Raises
    ------
    ValueError
        If ``ledblinky_dir`` is not configured or ``Color-RGB.ini`` is absent.
    """
    result = BrightnessResult(dry_run=dry_run, scale_pct=scale_pct)

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )

    color_rgb_path = Path(config.ledblinky_dir) / COLOR_RGB_NAME
    if not color_rgb_path.exists():
        raise ValueError(f"{COLOR_RGB_NAME} not found at {color_rgb_path}")

    result.color_rgb_path = color_rgb_path

    header, entries = parse_color_rgb_ini(color_rgb_path)

    # Clamp scale to 0–100 %
    factor = max(0.0, min(1.0, scale_pct / 100.0))

    scaled_entries = [_normalize_scale_entry(e, factor) for e in entries]
    result.colors_scaled = len(scaled_entries)
    result.color_changes = [
        (e.name, old.r, old.g, old.b, e.r, e.g, e.b)
        for old, e in zip(entries, scaled_entries)
    ]

    if not dry_run:
        if backup:
            result.backup_path = _backup(color_rgb_path, _config_backup_dir(config))
        write_color_rgb_ini(header, scaled_entries, color_rgb_path)

    return result


# ─── Admin/cabinet button color override ──────────────────────────────────────


@dataclass
class AdminButtonPatchResult:
    """Return value from :func:`patch_admin_button_colors`."""

    dry_run: bool
    colors_ini_path: Optional[Path] = None
    sections_updated: int = 0
    backup_path: Optional[Path] = None
    admin_player: int = 0
    button_colors: list = field(default_factory=list)
    updated_section_names: "list[str]" = field(default_factory=list)


def _patch_admin_buttons_in_text(
    text: str,
    admin_player: int,
    button_colors: "list[str]",
) -> "tuple[str, list[str]]":
    """Update or insert ``P{admin_player}_BUTTON{i}=color`` in every INI section.

    Returns ``(new_text, modified_section_names)``.  Only
    ``P{admin_player}_BUTTON*`` keys are touched; all other lines are
    preserved verbatim.
    """
    admin_keys: dict[str, str] = {
        f"P{admin_player}_BUTTON{i}": color
        for i, color in enumerate(button_colors, start=1)
    }

    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_section = False
    current_section_name: str = ""
    seen_keys: set[str] = set()
    section_changed = False
    modified_sections: list[str] = []

    def _flush_missing() -> "list[str]":
        missing = []
        for i, color in enumerate(button_colors, start=1):
            key = f"P{admin_player}_BUTTON{i}"
            if key not in seen_keys:
                missing.append(f"{key}={color}\n")
        return missing

    for line in lines:
        stripped = line.strip()

        # Section header — flush any missing keys for the outgoing section
        if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
            if in_section:
                missing = _flush_missing()
                if missing:
                    section_changed = True
                    result.extend(missing)
                if section_changed:
                    modified_sections.append(current_section_name)
            in_section = True
            current_section_name = stripped[1:-1]
            seen_keys = set()
            section_changed = False
            result.append(line)
            continue

        if in_section:
            # Replace matching admin button keys in-place
            m = re.match(r"^(P\d+_BUTTON\d+)\s*=\s*(.+)", stripped)
            if m:
                key = m.group(1)
                if key in admin_keys:
                    new_val = admin_keys[key]
                    old_val = m.group(2).strip()
                    if old_val != new_val:
                        ending = (
                            "\r\n" if line.endswith("\r\n")
                            else "\n" if line.endswith("\n")
                            else ""
                        )
                        result.append(f"{key}={new_val}{ending}")
                        section_changed = True
                    else:
                        result.append(line)
                    seen_keys.add(key)
                    continue

        result.append(line)

    # End of file — flush missing keys for the last section
    if in_section:
        missing = _flush_missing()
        if missing:
            section_changed = True
            result.extend(missing)
        if section_changed:
            modified_sections.append(current_section_name)

    return "".join(result), modified_sections


def patch_admin_button_colors(
    config: Config,
    button_colors: "list[str]",
    admin_player: int = 3,
    dry_run: bool = True,
    backup: bool = True,
) -> AdminButtonPatchResult:
    """Set individual admin/cabinet button colors globally in ``Colors.ini``.

    Unlike :func:`fill_default_colors` which only touches ROMs with no
    existing entry, this function walks **every** section in ``Colors.ini``
    and updates (or inserts) ``P{admin_player}_BUTTON{i}`` keys so that the
    cabinet-level buttons always display the configured colors regardless of
    which game is running.

    With ``admin_player=3`` and ``button_colors=["Red","Blue","Green","White","White","Yellow"]``
    every ROM section gets::

        P3_BUTTON1=Red
        P3_BUTTON2=Blue
        P3_BUTTON3=Green
        P3_BUTTON4=White
        P3_BUTTON5=White
        P3_BUTTON6=Yellow

    Parameters
    ----------
    button_colors:
        Ordered list of color names — one per cabinet button.  The length of
        the list determines how many button keys are written.  All names are
        validated against the ``Color-RGB.ini`` palette.
    admin_player:
        Player slot used for the admin/cabinet buttons (default ``3``).
        For a 2-player cabinet the admin buttons typically use ``P3``.
        For a 1-player cabinet use ``2``.
    dry_run:
        When ``True`` (default) no files are written.
    backup:
        When ``True`` (default) a timestamped backup of ``Colors.ini`` is
        created before writing.

    Raises
    ------
    ValueError
        If ``ledblinky_dir`` is not configured, ``Colors.ini`` is absent,
        ``button_colors`` is empty, or a color name is not in the palette.
    """
    result = AdminButtonPatchResult(
        dry_run=dry_run,
        admin_player=admin_player,
        button_colors=list(button_colors),
    )

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )
    if not button_colors:
        raise ValueError("button_colors must not be empty.")

    colors_ini_path = Path(config.ledblinky_dir) / COLORS_INI_NAME
    if not colors_ini_path.exists():
        raise ValueError(f"Colors.ini not found at {colors_ini_path}")
    result.colors_ini_path = colors_ini_path

    # Validate color names against Color-RGB.ini palette
    color_rgb_path = Path(config.ledblinky_dir) / COLOR_RGB_NAME
    if color_rgb_path.exists():
        _, palette = parse_color_rgb_ini(color_rgb_path)
        valid_names = {e.name for e in palette}
        bad = [c for c in button_colors if c not in valid_names]
        if bad:
            raise ValueError(
                f"Unknown color(s): {', '.join(repr(c) for c in bad)}. "
                f"Available: {', '.join(sorted(valid_names))}"
            )

    existing_text = colors_ini_path.read_text(encoding="utf-8", errors="replace")
    new_text, updated_names = _patch_admin_buttons_in_text(
        existing_text, admin_player, list(button_colors)
    )
    result.sections_updated = len(updated_names)
    result.updated_section_names = updated_names

    if not dry_run and result.sections_updated > 0:
        if backup:
            result.backup_path = _backup(colors_ini_path, _config_backup_dir(config))
        colors_ini_path.write_text(new_text, encoding="utf-8")

    return result


# ─── Colors.ini per-entry colour randomisation ────────────────────────────────


@dataclass
class RandomizeColorsResult:
    """Return value from :func:`randomize_entry_colors`."""

    dry_run: bool
    colors_ini_path: Optional[Path] = None
    sections_updated: int = 0        # sections that had P*_BUTTON* keys and were recoloured
    sections_skipped: int = 0        # sections with no player keys at all (empty/unknown)
    sections_skipped_old_format: int = 0  # sections using ledcolor1=/joystick= hex format
    backup_path: Optional[Path] = None
    seed: Optional[int] = None
    palette_size: int = 0
    # Per-section detail for --verbose output: (section_name, button_color, coin_start_color)
    updated_details: "list[tuple[str, str, str]]" = field(default_factory=list)
    palette_size: int = 0        # number of non-black colors available to draw from


#: Matches P{n}_BUTTON{i} or P{n}_JOYSTICK keys — the "gameplay" button family.
_RAND_BUTTON_KEY_RE = re.compile(
    r"^P(\d+)_(BUTTON\d+|JOYSTICK)\s*=",
    re.IGNORECASE,
)

#: Matches P{n}_COIN or P{n}_START keys — the "meta" button family.
_RAND_COIN_START_KEY_RE = re.compile(
    r"^P(\d+)_(COIN|START)\s*=",
    re.IGNORECASE,
)


def _randomize_section_body(
    body_lines: "list[str]",
    button_color: str,
    coin_start_color: str,
) -> "tuple[list[str], bool]":
    """Return ``(new_lines, had_any_player_key)`` with existing key values randomized.

    * ``P*_BUTTON*`` / ``P*_JOYSTICK`` keys → *button_color*.
    * ``P*_COIN`` / ``P*_START`` keys → *coin_start_color*.
    * All other lines are preserved exactly.
    * **No new keys are ever inserted.**

    Returns the rewritten body and a flag indicating whether at least one
    player key was found (used to count sections as updated vs skipped).
    """
    result: "list[str]" = []
    had_keys = False

    for line in body_lines:
        stripped = line.strip()
        bm = _RAND_BUTTON_KEY_RE.match(stripped)
        csm = _RAND_COIN_START_KEY_RE.match(stripped)
        if bm:
            key = f"P{bm.group(1)}_{bm.group(2)}"
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            result.append(f"{key}={button_color}{ending}")
            had_keys = True
        elif csm:
            key = f"P{csm.group(1)}_{csm.group(2)}"
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            result.append(f"{key}={coin_start_color}{ending}")
            had_keys = True
        else:
            result.append(line)

    return result, had_keys


def randomize_entry_colors(
    config: Config,
    dry_run: bool = True,
    backup: bool = True,
    seed: Optional[int] = None,
) -> RandomizeColorsResult:
    """Assign a random color to each game section's existing button keys.

    For **every** section in ``Colors.ini`` that contains at least one
    player-button key:

    * One random non-black color from ``Color-RGB.ini`` is chosen for all
      ``P*_BUTTON*`` and ``P*_JOYSTICK`` keys across every player slot —
      so all buttons in a game glow the same color.
    * A **second** independent random draw picks a color for all ``P*_COIN``
      and ``P*_START`` keys — the coin/start buttons get their own accent color
      (which may happen to match the button color by chance).
    * Both picks are **per-section** — each game gets its own independent draw,
      so the cabinet looks varied.
    * Only **existing** keys are updated.  New button entries are **never** added,
      so buttons that are intentionally dark (absent from the section) stay dark.
    * Pure-black / off colors (all R,G,B = 0) are excluded from the draw.

    Pass *seed* to make the run reproducible — the same *seed* on the same
    ``Colors.ini`` always produces the same per-game color assignments.

    Parameters
    ----------
    seed:
        Optional integer seed for the PRNG.  ``None`` (default) uses system
        entropy so each run produces a fresh shuffle.
    """
    result = RandomizeColorsResult(dry_run=dry_run, seed=seed)

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )

    colors_ini_path = Path(config.ledblinky_dir) / COLORS_INI_NAME
    result.colors_ini_path = colors_ini_path
    if not colors_ini_path.exists():
        raise ValueError(f"Colors.ini not found at {colors_ini_path}")

    # Build the palette of non-black named colors from Color-RGB.ini
    color_rgb_path = Path(config.ledblinky_dir) / COLOR_RGB_NAME
    if not color_rgb_path.exists():
        raise ValueError(
            f"{COLOR_RGB_NAME} not found at {color_rgb_path}. "
            "The palette file is required to build the random color pool."
        )
    _, palette = parse_color_rgb_ini(color_rgb_path)
    non_black = [e.name for e in palette if max(e.r, e.g, e.b) > 0]
    if not non_black:
        raise ValueError(
            "Color-RGB.ini contains no non-black colors to draw from. "
            "Add at least one color with non-zero R, G, or B."
        )
    result.palette_size = len(non_black)

    # Seed the PRNG — None means system entropy (different every run)
    rng = _random.Random(seed)

    # Parse Colors.ini into (name, header, body) sections
    existing_text = colors_ini_path.read_text(encoding="utf-8", errors="replace")
    sections = _split_ini_by_sections(existing_text)

    # Pre-compile the regex for old-format keys so we can classify skips.
    _OLD_FORMAT_RE = re.compile(
        r"^(ledcolor\d+|joystick|start|coin)\s*=",
        re.IGNORECASE,
    )

    parts: "list[str]" = []
    sections_updated = 0
    sections_skipped = 0
    sections_skipped_old_format = 0
    updated_details: "list[tuple[str, str, str]]" = []

    for section_name, header_line, body_lines in sections:
        if section_name is None:
            # Preamble before the first [header] — preserve verbatim
            parts.extend(body_lines)
            continue

        assert header_line is not None
        parts.append(header_line)

        # Independent random picks for this game (drawn even if skipped so
        # the PRNG sequence stays stable regardless of format classification).
        button_color = rng.choice(non_black)
        coin_start_color = rng.choice(non_black)

        new_body, had_keys = _randomize_section_body(
            body_lines, button_color, coin_start_color
        )
        parts.extend(new_body)

        if had_keys:
            sections_updated += 1
            updated_details.append((section_name, button_color, coin_start_color))
        else:
            # Classify the skip: old hex-format keys vs genuinely empty section.
            is_old_format = any(
                _OLD_FORMAT_RE.match(line.strip())
                for line in body_lines
                if line.strip()
            )
            if is_old_format:
                sections_skipped_old_format += 1
            else:
                sections_skipped += 1

    result.sections_updated = sections_updated
    result.sections_skipped = sections_skipped
    result.sections_skipped_old_format = sections_skipped_old_format
    result.updated_details = updated_details

    if not dry_run and sections_updated > 0:
        if backup:
            result.backup_path = _backup(colors_ini_path, _config_backup_dir(config))
        colors_ini_path.write_text("".join(parts), encoding="utf-8")

    return result


# ─── Colors.ini multi-player key sync ─────────────────────────────────────────


#: Matches P{n}_BUTTON{i} / P{n}_JOYSTICK / P{n}_START / P{n}_COIN in controls.ini
_CONTROLS_PLAYER_KEY_RE = re.compile(
    r"^P(\d+)_(BUTTON\d+|JOYSTICK|START|COIN)\s*=",
    re.IGNORECASE,
)


@dataclass
class SyncPlayersResult:
    """Result of :func:`sync_player_colors`."""

    dry_run: bool = True
    colors_ini_path: Optional[Path] = None
    backup_path: Optional[Path] = None
    #: Number of ROM sections that had at least one key added.
    roms_updated: int = 0
    #: Total new ``P{n}_KEY=COLOR`` lines written across all ROMs.
    keys_added: int = 0
    #: ROMs in Colors.ini that have no controls.ini entry (skipped).
    roms_skipped_no_controls: int = 0
    #: ROMs that already had all player keys present (nothing to add).
    roms_skipped_complete: int = 0
    #: Total existing ``P{n}_KEY`` lines replaced when ``override=True``.
    keys_overwritten: int = 0
    #: Per-ROM breakdown: list of (rom_name, [added_key_strings])
    details: "list[tuple[str, list[str]]]" = field(default_factory=list)


def sync_player_colors(
    config: "Config",
    dry_run: bool = True,
    backup: bool = True,
    verbose: bool = False,
    override: bool = False,
) -> SyncPlayersResult:
    """Mirror P1 colors to all additional players based on ``controls.ini``.

    ``ledblinky generate`` writes ``Colors.ini`` sections that only include P1
    keys (``P1_BUTTON1``, ``P1_JOYSTICK``, ``P1_START``, ``P1_COIN``).  When
    ``controls.ini`` lists buttons for additional players (P2, P3, P4, …),
    those players have no color entries and LedBlinky lights their buttons using
    the XML fallback color rather than the game-specific palette chosen in
    ``Colors.ini``.

    This function closes that gap for **any number of players**:

    * For every ROM that has both a ``Colors.ini`` section and a
      ``controls.ini`` section, it inspects ``controls.ini`` to find all
      ``P{n}_KEY`` entries where ``n >= 2`` (P2, P3, P4, …).
    * Any such key that is **absent** from the ``Colors.ini`` section is added
      with the same color as the matching ``P1_KEY`` (e.g. ``P3_BUTTON1`` gets
      the same color as ``P1_BUTTON1``).
    * If ``P1_KEY`` itself is absent from ``Colors.ini`` (nothing to mirror
      from), that key is skipped — no defaults are invented.
    * Keys already present in ``Colors.ini`` for that ROM are **never**
      overwritten unless ``override=True``.
    * When ``override=True``, existing ``P{n≥2}`` entries are replaced with the
      current P1-mirrored color.  P1 keys are never affected.
    * ROMs with no ``controls.ini`` entry are left untouched.

    Run after ``ledblinky generate`` (and ``colors normalize`` if the output
    was in legacy hex format) to ensure all player buttons light correctly.

    Examples::

        spindoctor ledblinky colors sync-players            # preview
        spindoctor ledblinky colors sync-players --apply    # commit
        spindoctor ledblinky colors sync-players --apply --override  # replace existing P2+ entries
    """
    result = SyncPlayersResult(dry_run=dry_run)

    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. "
            "Run: spindoctor config set ledblinky_dir <path>"
        )

    base = Path(config.ledblinky_dir)
    controls_ini_path = base / CONTROLS_INI_NAME
    colors_ini_path = base / COLORS_INI_NAME
    result.colors_ini_path = colors_ini_path

    if not controls_ini_path.exists():
        raise FileNotFoundError(
            f"controls.ini not found at {controls_ini_path}. "
            "Run: spindoctor ledblinky generate --apply"
        )
    if not colors_ini_path.exists():
        raise FileNotFoundError(
            f"colors.ini not found at {colors_ini_path}. "
            "Run: spindoctor ledblinky generate --apply"
        )

    # Parse controls.ini: for each ROM, collect the set of P{n}_KEY names
    # where n >= 2 (these are the keys we may need to add to Colors.ini).
    controls_sections = parse_existing_controls_ini(controls_ini_path)
    # Build: { rom_lower: { "P2_BUTTON1", "P2_JOYSTICK", ... } }
    controls_multi: dict[str, set[str]] = {}
    for rom, section in controls_sections.items():
        multi_keys: set[str] = set()
        for line in section.lines:
            m = _CONTROLS_PLAYER_KEY_RE.match(line.strip())
            if m and int(m.group(1)) >= 2:
                multi_keys.add(f"P{m.group(1)}_{m.group(2).upper()}")
        if multi_keys:
            controls_multi[rom.lower()] = multi_keys

    # Rewrite Colors.ini in-place, section by section.
    colors_text = colors_ini_path.read_text(encoding="utf-8", errors="replace")
    sections = _split_ini_by_sections(colors_text)
    parts: list[str] = []

    for section_name, header_line, body_lines in sections:
        if section_name is None:
            parts.extend(body_lines)
            continue

        assert header_line is not None
        parts.append(header_line)

        rom_lower = section_name.lower()
        if rom_lower not in controls_multi:
            # No multi-player controls.ini entry for this ROM — leave as-is.
            parts.extend(body_lines)
            result.roms_skipped_no_controls += 1
            continue

        needed_keys = controls_multi[rom_lower]  # e.g. {"P2_BUTTON1", "P2_JOYSTICK"}

        # Parse existing Colors.ini body: build { "P1_BUTTON1": "Red", ... }
        existing_colors: dict[str, str] = {}
        for line in body_lines:
            m = _PLAYER_KEY_RE.match(line.strip())
            if m:
                key = f"P{m.group(1)}_{m.group(2).upper()}"
                existing_colors[key] = m.group(3)

        # Build P1 lookup: strip player prefix → { "BUTTON1": "Red", ... }
        p1_colors: dict[str, str] = {}
        for key, color in existing_colors.items():
            if key.upper().startswith("P1_"):
                suffix = key[3:].upper()  # e.g. "BUTTON1"
                p1_colors[suffix] = color

        # Determine which keys to add (and which existing lines to replace
        # when override=True).
        existing_upper = {k.upper() for k in existing_colors}
        to_write: list[str] = []      # all lines to append (new + replacements)
        to_replace: set[str] = set()  # uppercase key names whose old lines to drop
        new_count = 0                 # genuinely new keys (not previously present)
        override_count = 0            # existing keys being replaced

        for full_key in sorted(needed_keys):
            upper = full_key.upper()
            already_present = upper in existing_upper
            if already_present and not override:
                # Key already present and caller did not request an override —
                # skip silently; this is the normal path for idempotent runs.
                continue
            # e.g. "P3_BUTTON1" → suffix "BUTTON1"
            # needed_keys are built from _CONTROLS_PLAYER_KEY_RE which always
            # emits "P<n>_<KEY>", so the underscore is guaranteed to be present.
            suffix = upper[upper.index("_") + 1:]
            color = p1_colors.get(suffix)
            if color is None:
                continue  # P1 key absent — nothing to mirror from
            if already_present:
                to_replace.add(upper)
                override_count += 1
            else:
                new_count += 1
            to_write.append(f"{full_key}={color}\n")

        if not to_write:
            parts.extend(body_lines)
            result.roms_skipped_complete += 1
            continue

        # Insert additions (and replacements) before any trailing blank lines.
        non_trailing = list(body_lines)
        trailing: list[str] = []
        while non_trailing and non_trailing[-1].strip() == "":
            trailing.insert(0, non_trailing.pop())

        # Strip old lines for keys being overridden.
        if to_replace:
            filtered: list[str] = []
            for line in non_trailing:
                m = _PLAYER_KEY_RE.match(line.strip())
                if m:
                    existing_upper_key = f"P{m.group(1)}_{m.group(2).upper()}"
                    if existing_upper_key.upper() in to_replace:
                        continue  # drop — replacement written below
                filtered.append(line)
            non_trailing = filtered

        parts.extend(non_trailing)
        parts.extend(to_write)
        parts.extend(trailing)

        result.roms_updated += 1
        result.keys_added += new_count
        result.keys_overwritten += override_count
        result.details.append((section_name, [line.rstrip("\n") for line in to_write]))

    if not dry_run and result.roms_updated > 0:
        if backup:
            result.backup_path = _backup(colors_ini_path, _config_backup_dir(config))
        colors_ini_path.write_text("".join(parts), encoding="utf-8")

    return result
