"""Detect third-party arcade tools installed alongside HyperSpin / RocketLauncher.

Read-only auditor.  Scans a configurable set of root directories (HyperSpin
Tools folder, RocketLauncher Modules / Plugins, Program Files trees, the
Start Menu, plus any user-supplied paths) for known arcade utilities, and
maps each find to the spindoctor command that supersedes it (or flags it
as a gap spindoctor doesn't cover).

The registry is intentionally a flat data table — adding a new tool means
appending one entry, no code changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config


# ─── tool registry ────────────────────────────────────────────────────────────

# Categories used in the report grouping.
CATEGORY_ROM_TOOL = "rom-tool"        # Librarian / audit / rename / dedupe / fetch
CATEGORY_FRONTEND = "frontend"        # HyperSpin itself, BigBox, etc.
CATEGORY_CONFIG_GUI = "config-gui"    # HyperHQ, RocketLauncherUI — config editors
CATEGORY_INPUT = "input"              # Joystick / keyboard mappers + drivers
CATEGORY_LIGHTGUN = "lightgun"        # Sinden, DemulShooter, Arcade Guns
CATEGORY_SHADER = "shader"            # SweetFX / ReShade
CATEGORY_UNKNOWN = "unknown"          # Found something we don't recognise

CATEGORY_ORDER = [
    CATEGORY_ROM_TOOL,
    CATEGORY_LIGHTGUN,
    CATEGORY_INPUT,
    CATEGORY_FRONTEND,
    CATEGORY_CONFIG_GUI,
    CATEGORY_SHADER,
    CATEGORY_UNKNOWN,
]


@dataclass(frozen=True)
class ToolEntry:
    """A single tool the auditor knows how to recognise."""
    name: str
    category: str
    # Executable basenames (case-insensitive) that identify this tool.
    executables: tuple[str, ...] = ()
    # Folder-name fragments (case-insensitive) that suggest this tool
    # without a matching .exe — useful for portable installs that ship
    # under unusual binary names.
    folder_hints: tuple[str, ...] = ()
    # Which spindoctor command(s) replace this tool, if any.
    superseded_by: Optional[str] = None
    notes: str = ""


# Order is irrelevant for matching; the report groups by category.
TOOL_REGISTRY: tuple[ToolEntry, ...] = (
    # ── HyperSpin ecosystem (frontend + config) ──────────────────────────────
    ToolEntry(
        name="HyperSpin",
        category=CATEGORY_FRONTEND,
        executables=("HyperSpin.exe",),
        folder_hints=("HyperSpin",),
        notes="The frontend itself. Required — do not remove.",
    ),
    ToolEntry(
        name="HyperHQ",
        category=CATEGORY_CONFIG_GUI,
        executables=("HyperHQ.exe",),
        notes="HyperSpin's config GUI. Keep — useful for one-off edits.",
    ),
    ToolEntry(
        name="RocketLauncherUI",
        category=CATEGORY_CONFIG_GUI,
        executables=("RocketLauncherUI.exe",),
        notes="RocketLauncher's config GUI. Keep.",
    ),

    # ── ROM / media librarian tools that spindoctor replaces ─────────────────
    ToolEntry(
        name="HyperSpin Rom & Media Manager (HyperSpin Checker)",
        category=CATEGORY_ROM_TOOL,
        executables=("HyperSpin Checker.exe", "HyperSpinChecker.exe",
                     "HSChecker.exe"),
        folder_hints=("HyperSpin Checker", "Rom & Media Manager"),
        superseded_by="spindoctor audit / verify / find-orphan-media",
        notes="Audits ROMs vs XML and reports missing media — same job as "
              "spindoctor's read-only audit/verify commands.",
    ),
    ToolEntry(
        name="HyperT00ls / HyperTools",
        category=CATEGORY_ROM_TOOL,
        executables=("HyperT00ls.exe", "HyperTools.exe"),
        folder_hints=("HyperT00ls", "HyperTools"),
        superseded_by="spindoctor audit / update-db / fetch-meta",
        notes="Grab-bag of HyperSpin XML utilities. Most functions are "
              "covered by spindoctor's audit + update-db commands.",
    ),
    ToolEntry(
        name="Don's HyperTools / Don's Hyperspin Tools",
        category=CATEGORY_ROM_TOOL,
        executables=("DonsHyperTools.exe", "DonsHyperspinTools.exe"),
        folder_hints=("Don's HyperTools", "Dons HyperTools",
                      "Don's Hyperspin Tools", "Dons Hyperspin Tools"),
        superseded_by="spindoctor audit / fetch-media / mainmenu",
        notes="Mixed-purpose toolkit; overlaps heavily with spindoctor.",
    ),
    ToolEntry(
        name="FatMatch",
        category=CATEGORY_ROM_TOOL,
        executables=("FatMatch.exe",),
        folder_hints=("FatMatch",),
        superseded_by="spindoctor audit (fuzzy) + rename",
        notes="Fuzzy ROM↔database matcher. spindoctor's audit does this and "
              "rename can fix the names.",
    ),
    ToolEntry(
        name="Tur-Matcher",
        category=CATEGORY_ROM_TOOL,
        executables=("Tur-Matcher.exe", "TurMatcher.exe"),
        folder_hints=("Tur-Matcher", "Tur Matcher"),
        superseded_by="spindoctor audit (fuzzy)",
        notes="Built into spindoctor audit's fuzzy-match pass.",
    ),
    ToolEntry(
        name="Tur-RemoveDupes",
        category=CATEGORY_ROM_TOOL,
        executables=("Tur-RemoveDupes.exe", "TurRemoveDupes.exe"),
        folder_hints=("Tur-RemoveDupes", "Tur RemoveDupes"),
        superseded_by="spindoctor find-dupes",
        notes="spindoctor find-dupes does SHA1 + title-based detection.",
    ),
    ToolEntry(
        name="HyperSpin CUE Renamer",
        category=CATEGORY_ROM_TOOL,
        executables=("HyperSpinCUERenamer.exe", "HSCUERenamer.exe",
                     "CUERenamer.exe"),
        folder_hints=("CUE Renamer",),
        superseded_by="spindoctor rename",
        notes="spindoctor rename already follows .cue/.bin sidecars when it "
              "renames a base ROM file.",
    ),
    ToolEntry(
        name="FuzzyRename 3",
        category=CATEGORY_ROM_TOOL,
        executables=("FuzzyRename.exe", "FuzzyRename3.exe"),
        folder_hints=("FuzzyRename",),
        superseded_by="spindoctor audit + rename",
        notes="Audit's fuzzy-match output drives rename.",
    ),
    ToolEntry(
        name="HyperSync",
        category=CATEGORY_ROM_TOOL,
        executables=("HyperSync.exe",),
        folder_hints=("HyperSync",),
        superseded_by="spindoctor fetch-meta / fetch-media / media-add",
        notes="Pulls media for HyperSpin systems. spindoctor uses "
              "ScreenScraper / TheGamesDB for the same job.",
    ),
    ToolEntry(
        name="Hypersearch",
        category=CATEGORY_ROM_TOOL,
        executables=("Hypersearch.exe", "HyperSearch.exe"),
        folder_hints=("HyperSearch", "Hypersearch"),
        superseded_by="spindoctor find-global",
        notes="Cross-system title search.",
    ),

    # ── Light gun gear ───────────────────────────────────────────────────────
    ToolEntry(
        name="Sinden Lightgun",
        category=CATEGORY_LIGHTGUN,
        executables=("Lightgun.exe", "SindenLightgun.exe"),
        folder_hints=("Sinden Lightgun", "SindenLightgun", "Sinden"),
        superseded_by="spindoctor lightgun (configure / audit)",
        notes="Driver/config app for Sinden guns. spindoctor wires Sinden + "
              "DemulShooter into per-system RocketLauncher launches.",
    ),
    ToolEntry(
        name="DemulShooter",
        category=CATEGORY_LIGHTGUN,
        executables=("DemulShooter.exe", "DemulShooterX64.exe"),
        folder_hints=("DemulShooter",),
        superseded_by="spindoctor lightgun configure --system <name>",
        notes="Required dep for lightgun support; spindoctor wires it into "
              "RL pre/post-launch hooks.",
    ),
    ToolEntry(
        name="Arcade Guns Utility",
        category=CATEGORY_LIGHTGUN,
        executables=("ArcadeGuns.exe", "ArcadeGunsUtility.exe"),
        folder_hints=("Arcade Guns",),
        notes="Ultimarc Arcade Guns config — keep, no spindoctor equivalent.",
    ),

    # ── Input / mapper tools (spindoctor doesn't absorb) ─────────────────────
    ToolEntry(
        name="XPadder",
        category=CATEGORY_INPUT,
        executables=("xpadder.exe", "XPadder.exe"),
        folder_hints=("XPadder",),
        notes="Joystick→keyboard mapper. Keep — register via install-tools.",
    ),
    ToolEntry(
        name="JoyToKey",
        category=CATEGORY_INPUT,
        executables=("JoyToKey.exe",),
        folder_hints=("JoyToKey",),
        notes="Joystick→keyboard mapper. Keep — register via install-tools.",
    ),
    ToolEntry(
        name="DS4Windows",
        category=CATEGORY_INPUT,
        executables=("DS4Windows.exe",),
        folder_hints=("DS4Windows",),
        notes="PS4/PS5 controller driver. Keep.",
    ),
    ToolEntry(
        name="XOutput",
        category=CATEGORY_INPUT,
        executables=("XOutput.exe",),
        folder_hints=("XOutput",),
        notes="DirectInput→XInput shim. Keep.",
    ),
    ToolEntry(
        name="Arcade-One Profiles (RRM controllers)",
        category=CATEGORY_INPUT,
        folder_hints=("Arcade-One", "ArcadeOne", "RRM"),
        notes="Profiles for RRM arcade controllers. Keep.",
    ),
    ToolEntry(
        name="Atari Fightstick",
        category=CATEGORY_INPUT,
        folder_hints=("Atari Fightstick", "AtariFightstick"),
        notes="Atari Fightstick config. Keep.",
    ),
    ToolEntry(
        name="Arcaid",
        category=CATEGORY_INPUT,
        executables=("Arcaid.exe",),
        folder_hints=("Arcaid",),
        notes="Arcade utility (purpose varies by build). Keep — review.",
    ),

    # ── Visual / shader ──────────────────────────────────────────────────────
    ToolEntry(
        name="SweetFX",
        category=CATEGORY_SHADER,
        executables=("SweetFX_settings.exe",),
        folder_hints=("SweetFX",),
        notes="Shader injector. Out of scope for spindoctor.",
    ),
)


# ─── scanning ─────────────────────────────────────────────────────────────────

@dataclass
class ToolFinding:
    """One installed tool that was identified during the scan."""
    entry: ToolEntry
    install_paths: list[Path] = field(default_factory=list)
    matched_executables: list[Path] = field(default_factory=list)


@dataclass
class UnknownExecutable:
    """An executable found in a scanned location that we don't recognise."""
    path: Path


@dataclass
class ToolsAuditResult:
    """Aggregate result of a tools-audit run."""
    findings: list[ToolFinding] = field(default_factory=list)
    unknown_executables: list[UnknownExecutable] = field(default_factory=list)
    scanned_roots: list[Path] = field(default_factory=list)
    missing_roots: list[Path] = field(default_factory=list)

    def by_category(self) -> dict[str, list[ToolFinding]]:
        grouped: dict[str, list[ToolFinding]] = {}
        for f in self.findings:
            grouped.setdefault(f.entry.category, []).append(f)
        for cat in grouped:
            grouped[cat].sort(key=lambda x: x.entry.name.lower())
        return grouped


def default_scan_roots(config: Config) -> list[Path]:
    """Return the default set of directories to scan for installed tools.

    Skips paths that don't exist; the caller can mix in extras from config.
    """
    roots: list[Path] = []

    # HyperSpin Tools folder (where the frontend's Tools menu lives).
    if config.hyperspin_dir:
        roots.append(Path(config.hyperspin_dir) / "Tools")
        roots.append(Path(config.hyperspin_dir))

    # RocketLauncher Modules + Plugins.
    if config.rocketlauncher_dir:
        rl = Path(config.rocketlauncher_dir)
        roots.append(rl / "Modules")
        roots.append(rl / "Plugins")
        roots.append(rl / "Lib")

    # Emulators tree (some tools install alongside emulators).
    if config.emulators_dir:
        roots.append(Path(config.emulators_dir))

    # Windows install trees.  These env vars are only present on Windows;
    # on dev boxes the loop below will skip them via the exists() check.
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        val = os.environ.get(env)
        if val:
            roots.append(Path(val))

    # Start Menu — a single shortcut here is often the only sign of a tool.
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu")
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        roots.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu")

    return roots


def scan_for_tools(
    roots: list[Path],
    *,
    extra_roots: Optional[list[Path]] = None,
    max_depth: int = 4,
    report_unknown: bool = False,
) -> ToolsAuditResult:
    """Walk *roots* up to *max_depth* looking for known tools.

    The scan is bounded — Program Files can have tens of thousands of
    files, so we stop descending once we hit *max_depth*.  This is enough
    to catch normal `Vendor/Tool/tool.exe` layouts without churning on
    every `node_modules` clone someone might have lying around.
    """
    all_roots = list(roots)
    if extra_roots:
        all_roots.extend(extra_roots)

    # de-dupe while preserving order
    seen_roots: set[Path] = set()
    deduped: list[Path] = []
    for r in all_roots:
        rp = r.resolve() if r.exists() else r
        if rp in seen_roots:
            continue
        seen_roots.add(rp)
        deduped.append(r)

    result = ToolsAuditResult()

    # Build O(1) lookups from the registry.
    exe_to_entry: dict[str, ToolEntry] = {}
    folder_hint_pairs: list[tuple[str, ToolEntry]] = []
    for entry in TOOL_REGISTRY:
        for exe in entry.executables:
            exe_to_entry[exe.lower()] = entry
        for hint in entry.folder_hints:
            folder_hint_pairs.append((hint.lower(), entry))

    # findings are merged by registry entry as we walk so the same tool
    # discovered via two paths isn't reported twice.
    findings_by_entry: dict[ToolEntry, ToolFinding] = {}

    def record(entry: ToolEntry, *, install_path: Optional[Path] = None,
               exe_path: Optional[Path] = None) -> None:
        f = findings_by_entry.setdefault(entry, ToolFinding(entry=entry))
        if install_path and install_path not in f.install_paths:
            f.install_paths.append(install_path)
        if exe_path and exe_path not in f.matched_executables:
            f.matched_executables.append(exe_path)

    for root in deduped:
        if not root.exists():
            result.missing_roots.append(root)
            continue
        result.scanned_roots.append(root)
        _walk(root, max_depth, exe_to_entry, folder_hint_pairs,
              record, result, report_unknown)

    result.findings = list(findings_by_entry.values())
    result.findings.sort(key=lambda f: (f.entry.category, f.entry.name.lower()))
    return result


def _walk(
    root: Path,
    max_depth: int,
    exe_to_entry: dict[str, ToolEntry],
    folder_hint_pairs: list[tuple[str, ToolEntry]],
    record,
    result: ToolsAuditResult,
    report_unknown: bool,
) -> None:
    """Bounded directory walk used by scan_for_tools."""
    root_resolved = root.resolve() if root.exists() else root
    base_depth = len(root_resolved.parts)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).resolve().parts) - base_depth
        if depth >= max_depth:
            dirnames[:] = []  # stop descending
            continue

        # Folder-hint matches — fire when a directory name contains a hint.
        dpath_lower = dirpath.lower()
        for hint, entry in folder_hint_pairs:
            if hint in dpath_lower:
                record(entry, install_path=Path(dirpath))

        for fname in filenames:
            lname = fname.lower()
            if not lname.endswith((".exe", ".lnk")):
                continue
            entry = exe_to_entry.get(lname)
            if entry:
                record(entry,
                       install_path=Path(dirpath),
                       exe_path=Path(dirpath) / fname)
            elif report_unknown and lname.endswith(".exe"):
                result.unknown_executables.append(
                    UnknownExecutable(path=Path(dirpath) / fname)
                )


# ─── reporting helpers (text output is rendered by the CLI layer) ─────────────

def category_label(category: str) -> str:
    return {
        CATEGORY_ROM_TOOL: "ROM / media tools",
        CATEGORY_LIGHTGUN: "Light gun",
        CATEGORY_INPUT: "Controllers / input",
        CATEGORY_FRONTEND: "Frontend",
        CATEGORY_CONFIG_GUI: "Config GUIs",
        CATEGORY_SHADER: "Shaders / visual",
        CATEGORY_UNKNOWN: "Unrecognised executables",
    }.get(category, category)
