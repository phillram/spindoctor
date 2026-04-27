"""LedBlinky / HyperSpin Search compatibility scan + patch.

Two known conflicts when LedBlinky is installed alongside HyperSpin's Search
(and Genre/Favorites) special menus:

1. LedBlinky's process hooks (``Start_Hyperspin_Process`` /
   ``Exit_Hyperspin_Process``) get injected into the Search menu's
   ``Settings.ini`` and crash the overlay launcher when it tries to fire.

2. ``LEDBlinkyControls.xml`` has no entry for the Search special menu, so
   the menu-change lookup fails and LedBlinky errors out — sometimes
   taking HyperSpin down with it.

This module provides:

- :func:`scan` — read-only audit of both conditions.
- :func:`apply_fix` — patch ``LEDBlinkyControls.xml`` and the relevant
  HyperSpin per-menu ``Settings.ini`` files. Honors ``output_base``,
  ``dry_run``, and ``backup`` the same way the rest of SpinDoctor does.
"""
from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config


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
            tree = ET.parse(src_path)
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
    ET.indent(tree, space="  ")
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
