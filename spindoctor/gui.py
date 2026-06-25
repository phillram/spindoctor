"""SpinDoctor GUI — Tkinter front-end for the CLI.

A double-clickable launcher for cabinet owners who don't want to drop into
``cmd.exe``. Wraps the most common SpinDoctor operations behind tabs and
forms, and shells out to the underlying CLI binaries in a background thread
so output streams into the window without blocking the UI.

The GUI deliberately does not duplicate command logic — it just builds an
argv and spawns ``spindoctor.exe`` (or one of the standalone wheel binaries)
sitting next to it. Two side benefits:

* The frozen GUI binary stays small — it doesn't bundle lxml/Pillow/etc.,
  those live in the CLI exes that ship in the same release zip.
* Behaviour stays identical to the CLI, so a bug fix in either surface
  never has to be ported to the other.

Run via:

    spindoctor-gui                 # console-script entry point
    python -m spindoctor.gui       # module form
    spindoctor-gui.exe             # frozen Windows binary
"""
from __future__ import annotations

import os
import queue
import re
import shlex
import shutil
import json
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, Deque, Optional, Sequence

from . import __app_name__, __version__
from .config import (
    CONFIG_DIR, CONFIG_FILE, get_systems, load_config, save_config,
)
from .database import load_database
from .rocketlauncher import list_exe_candidates
from ._utils import format_bytes as _format_bytes_util


# ─── Subprocess plumbing (importable without Tk) ──────────────────────────────

# CREATE_NO_WINDOW (Windows-only) keeps subprocess invocations from popping a
# second cmd window when the GUI shells out — without it, every Run click
# briefly flashes a console window on top of the GUI.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Map "console script name" → "module to run with -m" for dev installs where
# the frozen exes don't exist. Mirrors [project.scripts] in pyproject.toml.
_DEV_MODULE_MAP = {
    "spindoctor": "spindoctor.cli",
    "spindoctor-fav": "spindoctor.favorites",
    "spindoctor-recent": "spindoctor.recent",
    "spindoctor-stats": "spindoctor.playtime",
}


class CliNotFoundError(RuntimeError):
    """Raised when the GUI can't locate a sibling CLI binary at runtime."""


def resolve_cli_command(name: str) -> list[str]:
    """Return the argv prefix that invokes the named SpinDoctor binary.

    *name* is one of the keys in :data:`_DEV_MODULE_MAP` (``"spindoctor"``,
    ``"spindoctor-fav"``, ``"spindoctor-recent"``, ``"spindoctor-stats"``).

    Resolution order:

    1. **Frozen GUI** — sibling exe in the same directory as ``sys.executable``.
       This is how the release zip ships them, so the user doesn't need to
       configure ``PATH`` for the GUI to find its peers.
    2. **PATH lookup** — for users who installed the binaries via a package
       manager or symlinked them somewhere on ``PATH``.
    3. **Dev install** — fall back to ``sys.executable -m <module>`` so
       ``pip install -e .`` checkouts work without first running the build.
    """
    if name not in _DEV_MODULE_MAP:
        raise ValueError(f"Unknown SpinDoctor binary: {name!r}")

    suffix = ".exe" if sys.platform == "win32" else ""

    if getattr(sys, "frozen", False):
        sibling = Path(sys.executable).resolve().parent / f"{name}{suffix}"
        if sibling.exists():
            return [str(sibling)]
        on_path = shutil.which(name)
        if on_path:
            return [on_path]
        raise CliNotFoundError(
            f"Could not find {name}{suffix} next to the GUI binary "
            f"({Path(sys.executable).parent}) or on PATH. "
            "Make sure all spindoctor*.exe files are kept in the same folder."
        )

    on_path = shutil.which(name)
    if on_path:
        return [on_path]
    return [sys.executable, "-m", _DEV_MODULE_MAP[name]]


# ─── Dark-mode palette (module-level so tests can reach in too) ───────────────
#
# Hand-picked from the VS Code Dark+ ecosystem so the colours have already
# been validated for readability and colour-blind contrast. Apply with
# :func:`_SpinDoctorGUI._apply_dark_theme`. There is no light-mode toggle —
# everywhere that previously hard-coded "#444" / "#666" / "#888" / "gray"
# for dimmed text is now redirected at ``_FG_DIM`` / ``_FG_DIMMER`` so the
# values stay readable against the dark background.

_DARK_BG          = "#1e1e1e"  # primary window background
_DARK_BG_RAISE    = "#252526"  # raised panels (LabelFrame, status bar, tab strip)
_DARK_BG_INPUT    = "#2d2d30"  # Entry, Combobox, Text, Listbox
_DARK_BG_BUTTON   = "#3a3a3c"  # ttk.Button face
_DARK_BG_ACTIVE   = "#505052"  # hover / pressed
_DARK_BG_SELECT   = "#094771"  # selection highlight (VS Code blue)
_DARK_FG          = "#dcdcdc"  # primary text
_FG_DIM           = "#aaaaaa"  # subdued text (replaces #444 / #666 on light)
_FG_DIMMER        = "#7a7a7a"  # disabled-look text (replaces #888 / "gray")
_DARK_BORDER      = "#3c3c3c"
_DARK_ACCENT      = "#007acc"  # focus ring / progress bar / hyperlink-ish

# Scrollbar thumb (the draggable rectangle) needs noticeably more contrast
# against the trough than the regular button face — picked by eye so the
# thumb reads as "obviously the grabby part" without yelling.
_DARK_SCROLL_THUMB        = "#6a6a6e"  # rests well above _DARK_BG_RAISE trough
_DARK_SCROLL_THUMB_ACTIVE = "#8a8a8e"  # hover / pressed


# Suffix appended to system names in all dropdowns when the system exists on
# disk (roms_dir / databases_dir) but is absent from Main Menu.xml.  The GUI
# strips this suffix before passing the name to any CLI command so it never
# appears in file paths or output.
_NOT_IN_WHEEL_SUFFIX = " (Not in wheel)"

# ─── UI scale helpers (module-level for test access) ──────────────────────────

# Hard clamp for `ui_scale`. Below 0.6 the UI is unreadable; above 2.0 the
# layout starts overflowing minsize on most cabinet displays.
UI_SCALE_MIN = 0.6
UI_SCALE_MAX = 2.0
UI_SCALE_PRESETS: tuple[float, ...] = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5)


def _clamp_ui_scale(value: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(UI_SCALE_MIN, min(UI_SCALE_MAX, round(f, 2)))


# Matches Tk's "WIDTHxHEIGHT" or "WIDTHxHEIGHT+X+Y" / "...-X-Y" geometry
# string form. Used to validate persisted geometry before handing it
# back to Tk on the next launch — a malformed string would raise
# `TclError` and break the splash, so we'd rather drop the saved value
# and use the scaled default.
_GEOMETRY_RE = re.compile(
    r"^\d{2,5}x\d{2,5}([+-]-?\d{1,5}[+-]-?\d{1,5})?$"
)


def _is_plausible_geometry(s: str) -> bool:
    """True iff *s* looks like a Tk geometry string we'd be safe to apply."""
    return bool(_GEOMETRY_RE.match(s or ""))


def _is_maximized(root) -> bool:
    """Return True when *root* is currently maximised (cross-platform)."""
    try:
        if sys.platform == "win32":
            return root.state() == "zoomed"
        return bool(root.wm_attributes("-zoomed"))
    except Exception:  # noqa: BLE001
        return False


def _set_maximized(root) -> None:
    """Maximise *root* in a cross-platform way."""
    try:
        if sys.platform == "win32":
            root.state("zoomed")
        else:
            root.wm_attributes("-zoomed", True)
    except Exception:  # noqa: BLE001
        pass


# Named Tk fonts whose sizes we scale alongside `ui_scale`. Keeping the
# list central means any widget that uses a non-default font (e.g. the
# bold headings) opts into scaling just by referencing the right name.
_SCALED_FONT_NAMES: tuple[str, ...] = (
    "TkDefaultFont",
    "TkTextFont",
    "TkFixedFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkSmallCaptionFont",
    "TkCaptionFont",
    "TkTooltipFont",
    "TkIconFont",
)


# ─── Tk context-menu helper (module-level so smoke tests can call it) ─────────

def _attach_context_menu(widget, tk_mod) -> None:
    """Attach a Cut/Copy/Paste/Select-All right-click context menu.

    Behaviour rules:

    * Read-only ``Text`` widgets (``state="disabled"``) and password
      ``Entry`` widgets (``show="*"``) get a stripped-down menu — no
      Cut/Paste for read-only, no Copy/Cut for masked fields (so the
      mask can't be trivially bypassed via right-click).
    * Binds both ``<Button-3>`` (Linux/Windows + modern macOS) and
      ``<Button-2>`` (legacy macOS / some trackpad configs).
    * Idempotent: tagging widgets we've already handled with a custom
      attribute keeps the tree walker from double-binding.
    """
    if getattr(widget, "_spindoctor_ctxmenu_attached", False):
        return

    def _post(event):
        # Build the menu lazily so widget state (show=, state=) is read
        # at popup time rather than at attach time — that way the
        # eyeball toggle's `entry.config(show="")` immediately enables
        # Copy without the entry having to be re-attached.
        try:
            cls = type(widget).__name__
        except Exception:  # noqa: BLE001
            cls = ""

        is_entry = cls in ("Entry", "TEntry")
        is_text = cls in ("Text", "ScrolledText")
        try:
            state = str(widget.cget("state"))
        except tk_mod.TclError:
            state = "normal"
        editable = state not in ("disabled", "readonly")
        masked = bool(is_entry and widget.cget("show"))

        menu = tk_mod.Menu(widget, tearoff=0)
        if editable and not masked:
            menu.add_command(
                label="Cut",
                command=lambda: widget.event_generate("<<Cut>>"),
            )
        if not masked:
            menu.add_command(
                label="Copy",
                command=lambda: widget.event_generate("<<Copy>>"),
            )
        if editable:
            menu.add_command(
                label="Paste",
                command=lambda: widget.event_generate("<<Paste>>"),
            )
        if menu.index("end") is not None:
            menu.add_separator()
        menu.add_command(
            label="Select all",
            command=lambda: _select_all(widget, is_entry=is_entry, is_text=is_text),
        )
        try:
            widget.focus_set()
        except tk_mod.TclError:
            pass
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # Button-3 covers Win/Linux/modern macOS; Button-2 catches legacy mac.
    widget.bind("<Button-3>", _post, add="+")
    widget.bind("<Button-2>", _post, add="+")
    # macOS sometimes reports right-click as Control-Button-1.
    widget.bind("<Control-Button-1>", _post, add="+")
    widget._spindoctor_ctxmenu_attached = True  # type: ignore[attr-defined]


def _select_all(widget, *, is_entry: bool, is_text: bool) -> None:
    """Best-effort 'Select All' that works for both Entry and Text."""
    try:
        if is_entry:
            widget.select_range(0, "end")
            widget.icursor("end")
        elif is_text:
            widget.tag_add("sel", "1.0", "end-1c")
        else:
            widget.event_generate("<<SelectAll>>")
    except Exception:  # noqa: BLE001
        pass


def _attach_tooltip(widget, text: str, tk_mod) -> None:
    """Show *text* in a floating Label while the cursor hovers over *widget*.

    Implemented with a single hidden ``Toplevel`` per attachment, shown
    on ``<Enter>`` (after a 500 ms grace period so cursors merely
    passing through don't flash) and destroyed on ``<Leave>`` or
    ``<ButtonPress>``. No third-party tooltip library — the cabinet
    target ships a frozen exe and every extra dependency bloats the
    install.
    """
    if not text:
        return
    state = {"tip": None, "after_id": None}

    def _show(_event=None):
        if state["tip"] is not None:
            return
        try:
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip = tk_mod.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            # Match the dark palette without importing the colour
            # constants — the literals here mirror _DARK_BG_RAISE +
            # _DARK_FG so the tooltip blends with the rest of the UI.
            lbl = tk_mod.Label(
                tip, text=text, justify="left",
                background="#2d2d30", foreground="#dcdcdc",
                relief="solid", borderwidth=1,
                padx=6, pady=3, wraplength=360,
            )
            lbl.pack()
            state["tip"] = tip
        except Exception:  # noqa: BLE001 - never block UI on tooltip failure
            state["tip"] = None

    def _schedule(event=None):
        # 500 ms feels right — long enough that drive-by hover doesn't
        # flicker, short enough that an intentional pause produces help
        # before the user gives up.
        _cancel()
        try:
            state["after_id"] = widget.after(500, _show)
        except Exception:  # noqa: BLE001
            state["after_id"] = None

    def _cancel(_event=None):
        aid = state["after_id"]
        if aid is not None:
            try:
                widget.after_cancel(aid)
            except Exception:  # noqa: BLE001
                pass
            state["after_id"] = None

    def _hide(_event=None):
        _cancel()
        tip = state["tip"]
        if tip is not None:
            try:
                tip.destroy()
            except Exception:  # noqa: BLE001
                pass
            state["tip"] = None

    widget.bind("<Enter>", _schedule, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")


def _walk_attach_context_menus(root_widget, tk_mod) -> None:
    """Recursively attach the context menu to every Entry/Text descendant.

    Called once after the whole window is built; future-proofs new
    fields because nothing has to be wired up at construction time.
    """
    try:
        cls = type(root_widget).__name__
    except Exception:  # noqa: BLE001
        cls = ""
    if cls in ("Entry", "TEntry", "Text", "ScrolledText"):
        _attach_context_menu(root_widget, tk_mod)
    try:
        children = root_widget.winfo_children()
    except Exception:  # noqa: BLE001
        children = []
    for child in children:
        _walk_attach_context_menus(child, tk_mod)


def _typeahead_find_match(
    values: Sequence[str], ch: str, start: int,
) -> Optional[int]:
    """Return the index of the first ``values`` entry starting with ``ch``.

    Searches cyclically beginning at ``start`` (not just index 0) so a
    repeat press of the same letter can resume after the previous
    match instead of always landing back on the first one. Comparison
    is case-insensitive. Returns ``None`` if nothing matches or
    ``values`` is empty.
    """
    if not values:
        return None
    ch_lower = ch.lower()
    for offset in range(len(values)):
        idx = (start + offset) % len(values)
        if values[idx].lower().startswith(ch_lower):
            return idx
    return None


def _attach_combobox_typeahead(combo) -> None:
    """Bind letter-key type-ahead to a single Combobox.

    Pressing a letter jumps the selection to the next value starting
    with that letter, cycling to the next match on repeat presses
    within a second (mirrors the native OS combobox behaviour the
    dark ttk theme's custom rendering otherwise loses — readonly
    Comboboxes only cycle on Up/Down without this). Long system/game
    lists (hundreds of entries) are otherwise a scroll-fest.
    """
    if getattr(combo, "_spindoctor_typeahead_attached", False):
        return
    state = {"char": None, "index": -1, "at": 0.0}

    def _on_key(event):
        ch = event.char
        if not ch or not ch.isalnum():
            return None
        try:
            values = list(combo["values"])
        except Exception:  # noqa: BLE001
            return None
        now = time.monotonic()
        repeat = ch.lower() == state["char"] and now - state["at"] < 1.0
        start = state["index"] + 1 if repeat else 0
        state["char"] = ch.lower()
        state["at"] = now
        idx = _typeahead_find_match(values, ch, start)
        if idx is None:
            return None
        state["index"] = idx
        combo.set(values[idx])
        combo.event_generate("<<ComboboxSelected>>")
        return "break"

    combo.bind("<KeyPress>", _on_key, add="+")
    combo._spindoctor_typeahead_attached = True  # type: ignore[attr-defined]


def _walk_attach_combobox_typeahead(root_widget) -> None:
    """Recursively attach letter-key type-ahead to every Combobox.

    Called once after the whole window is built, same pattern as
    ``_walk_attach_context_menus``, so every System/Game dropdown
    across every tab gets it for free — including ones added later.
    """
    try:
        cls = type(root_widget).__name__
    except Exception:  # noqa: BLE001
        cls = ""
    if cls in ("Combobox", "TCombobox"):
        _attach_combobox_typeahead(root_widget)
    try:
        children = root_widget.winfo_children()
    except Exception:  # noqa: BLE001
        children = []
    for child in children:
        _walk_attach_combobox_typeahead(child)


# ─── Tk GUI (lazy imports so the helpers above stay test-importable) ──────────

# Wizard fields used by the Setup tab. Mirrors `_INIT_FIELDS` in cli.py so
# the windowed setup matches what `spindoctor config init` asks for.
# (key, label, hardcoded Windows default, allow_blank)
_SETUP_FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("roms_dir",              "ROMs directory",                       r"D:\ROMs",                    False),
    ("hyperspin_dir",         "HyperSpin directory",                  r"D:\HyperSpin",               False),
    ("emulators_dir",         "Emulators directory",                  r"D:\Emulators",               False),
    ("rocketlauncher_dir",    "RocketLauncher directory",             r"D:\RocketLauncher",          False),
    ("ledblinky_dir",         "LEDBlinky install directory",          r"C:\LEDBlinky",               True),
    ("mame_executable",       "MAME executable",                      r"D:\Emulators\MAME\mame.exe", True),
    ("output_dir",            "Default output directory",             r"D:\SpinDoctorOutput",        True),
    ("auto_audit_export_dir", "Auto-audit export directory",          r"D:\SpinDoctorAudits",        True),
    ("backup_dir",            "Backup root directory",                r"D:\Backups",                 True),
    ("atomic_tmp_dir",        "Atomic write temp directory",          r"D:\SpinDoctorTemp",          True),
)

# Scraper credential fields shown below the path fields in the Setup tab.
# Tuples: (config_key, label, is_password)
_CRED_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("screenscraper_user",        "ScreenScraper username",     False),
    ("screenscraper_pass",        "ScreenScraper password",     True),
    ("screenscraper_devid",       "ScreenScraper devid",        False),
    ("screenscraper_devpassword", "ScreenScraper devpassword",  True),
    ("thegamesdb_key",            "TheGamesDB API key",         True),
)

# Values that should display as "not set" even though they're technically
# stored. ``SpinDoctor`` is the historical placeholder for the dev
# credentials — it never authenticated against the live API, so showing
# it as "saved" misleads the user into thinking everything is wired up.
_CRED_PLACEHOLDER_VALUES: frozenset = frozenset({"SpinDoctor"})


def _format_secret_hint(value: str, key: str = "") -> str:
    """Render a status hint next to a saved credential field.

    The previous design showed ``"…abcd"`` — the last 4 characters of
    the stored secret — to help users tell a populated field from an
    empty one. That reads as cryptic random text on reopen ("what does
    `…WBfo` mean?"), so we now surface a plain-language status:
    ``"(saved)"`` when populated, ``"(not set)"`` when blank. The
    follow-up labels ``"(edited — not yet saved)"`` and
    ``"(cleared — not saved)"`` come from the live-edit trace.

    ``key`` is consulted only to treat the bundled developer-credential
    placeholder ``"SpinDoctor"`` as "not set" for the dev fields, since
    that literal value never authenticates upstream.
    """
    if not value:
        return "(not set)"
    if key.startswith("screenscraper_dev") and value in _CRED_PLACEHOLDER_VALUES:
        return "(not set — bundled placeholder)"
    return "(saved)"


# Components offered as checkboxes on the Backup tab. Mirrors
# `backup.ALL_COMPONENTS` and the `--include` choices in
# `spindoctor backup create`. Kept here as a static tuple so the GUI
# module stays import-light (it doesn't pull `spindoctor.backup` until
# the user actually runs a command).
_BACKUP_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("roms",            "ROM / game files"),
    ("databases",       "HyperSpin database XMLs"),
    ("media",           "HyperSpin media (wheels, snaps, video, themes)"),
    ("emulators",       "Emulator binaries"),
    ("rocketlauncher",  "RocketLauncher install"),
    ("ledblinky",       "LEDBlinky install"),
    ("settings",        "SpinDoctor config & state (~/.spindoctor/)"),
)


# Components offered as checkboxes on the Migration tab. Mirrors
# `migrate.ALL_COMPONENTS` (only 5 entries — `databases`/`media`
# collapse into `hyperspin` here, unlike the Backup tab which lists
# them separately).
_MIGRATE_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("roms",            "ROM / game files"),
    ("hyperspin",       "HyperSpin install (Databases + Media + bin)"),
    ("emulators",       "Emulator binaries"),
    ("rocketlauncher",  "RocketLauncher install"),
    ("ledblinky",       "LEDBlinky install"),
)

# Cleanup categories exposed as checkboxes on the Curate tab.
# Each entry: (cli-key, friendly-label, safe-by-default).
# Safe categories are pre-checked; unsafe ones start unchecked with a
# warning that they remove undo/recovery options.
_CLEANUP_CATEGORIES: tuple[tuple[str, str, bool], ...] = (
    ("metadata-cache",        "Scraper API responses",          True),
    ("match-cache",           "Match decisions",                True),
    ("media-pick-cache",      "Media picker decisions",         True),
    ("pc-titles-cache",       "PC/Steam title confirmations",   True),
    ("listxml-cache",         "MAME -listxml cache",            True),
    ("preview-temp",          "Preview thumbnails",             True),
    ("partial-downloads",     "Interrupted downloads",          True),
    ("misplaced-manifests",   "Misplaced-ROM reports",          True),
    ("audit-exports",         "Audit CSV exports",              True),
    ("migration-manifests",   "Migration undo manifests",       False),
    ("restructure-manifests", "Restructure undo manifests",     False),
    ("db-backups",            "HyperSpin DB backups",           False),
    ("ledblinky-backups",     "LEDBlinky file backups",         False),
)


# Verbs that never modify disk state and therefore never accept --apply.
# Used to suppress the "DRY RUN" banner the GUI prepends to commands that
# lack --apply — the banner would mislead users into thinking a read-only
# check (e.g. `audit`) was a preview of something that could be committed.
#
# Single-token entries match `args[0]`. Two-token entries (e.g.
# "mainmenu show") match `"args[0] args[1]"`. Verbs that *do* have an
# --apply mode (e.g. `cleanup run`, `mainmenu sort`) are deliberately
# absent so the banner still appears for their preview invocations.
# Commands (or "verb subverb" pairs) that are always non-dry-run:
# either genuinely read-only (audit, inspect, …) or write-always with
# no --apply flag (install-tools, config set, …).  Commands that have
# an --apply flag must NOT appear here — when run without --apply they
# ARE dry-runs and the GUI must label them as such.
#
# Confirmed --apply commands removed from this set (DRY RUN banner is correct
# for these when called without --apply — they are previewing real writes):
#   generate-config  find-misplaced  find-orphan-media
#   lightgun configure
#
# Commands intentionally kept even though they technically have --apply:
#   doctor          — The GUI only ever calls `doctor` (no --apply).  Running
#                     it is a health diagnostic, not a preview of writes.
#                     Showing "DRY RUN" for a health check actively misleads
#                     the user.  doctor --apply is available via Custom Command
#                     for those who need it; the Logs tab will show "N/A" in
#                     that case (acceptable — power users know they wrote).
#   lightgun detect — Same reasoning: detect scans for hardware, it isn't
#                     a preview of config writes.
#   mainmenu show   — No-arg form (the only form the GUI generates) is
#                     genuinely display-only.  The write variant
#                     "mainmenu show SYSTEM --apply" is Custom-Command-only.
#
# NOTE: `stats-report` appears here but its write subcommands
# (build-wheel, clear-wheel) are listed in _WRITE_SUBCOMMAND_PAIRS below so
# they are correctly classified as dry-run-capable rather than read-only.
_READ_ONLY_COMMANDS: frozenset[str] = frozenset({
    "--help", "--version",
    "tools-audit", "systems", "report", "preview",
    "audit", "inspect", "find-dupes",
    "check-discs", "check-archive-ext", "verify", "lint", "stats",
    "find-global", "theme-scan", "theme-pack-create", "diff",
    "install-tools", "stats-report", "self-doctor",
    "cleanup categories", "cleanup audit",
    "ignore list", "match list",
    "fav list", "recent list",
    "mainmenu show", "mainmenu edit",
    "ledblinky audit", "ledblinky check", "ledblinky inspect-rom",
    "ledblinky colors list",
    "lightgun audit", "lightgun detect",
    "doctor",
    "config show", "config init", "config set", "config system",
    "config verify-credentials",
    "backup list", "backup info", "backup sidecar list",
    "migrate --list-manifests", "theme-apply --list-manifests",
    # `curate --list-manifests` is a separate flag-only invocation, not
    # a subcommand — match it as the verb+token form.
    "curate --list-manifests",
    # Write-always commands (no --apply concept — single-record mutations
    # of SpinDoctor's own store / config). Listing them here suppresses
    # the DRY RUN banner, which would otherwise lie: these commands write
    # immediately. The Logs tab shows "# Dry-run: N/A" for them.
    "fav add", "fav remove", "fav sync",
    "ignore add", "ignore remove", "ignore clear",
    "match clear",
    "emulator-title list", "emulator-title set", "emulator-title remove",
})

# Two-token subcommand pairs that ARE dry-run-capable (they support --apply)
# even though their parent verb is in _READ_ONLY_COMMANDS.  Checked before
# the single-token lookup so the more-specific rule wins.
_WRITE_SUBCOMMAND_PAIRS: frozenset[str] = frozenset({
    "stats-report build-wheel",
    "stats-report clear-wheel",
})


def _is_read_only_invocation(args: tuple) -> bool:
    if not args:
        return True
    # Two-token write subcommands override a read-only parent verb.
    if len(args) >= 2 and f"{args[0]} {args[1]}" in _WRITE_SUBCOMMAND_PAIRS:
        return False
    if args[0] in _READ_ONLY_COMMANDS:
        return True
    if len(args) >= 2 and f"{args[0]} {args[1]}" in _READ_ONLY_COMMANDS:
        return True
    # Three-token leaf commands (e.g. "backup sidecar list",
    # "ledblinky colors list") — exact-form entries only.
    if len(args) >= 3 and f"{args[0]} {args[1]} {args[2]}" in _READ_ONLY_COMMANDS:
        return True
    return False


# Curated dropdown for the Custom Command tab. Each entry is the argv
# string the user would type after `spindoctor` on the command line, in
# canonical form. Picking one populates the entry field; the user can
# then edit placeholders (<SYSTEM>, <PATH>, ...) before clicking Run.
# Sections are separated by "─── Name ───" header strings. Within each
# section the entries are sorted alphabetically by full command text.
# Selecting a header auto-advances to the first real command beneath it
# (handled in _SpinDoctorGUI._on_custom_preset_selected). Running a
# header is a no-op (guarded in _run_custom).
_PRESET_SECTION_HEADER_PREFIX = "───"
_CUSTOM_COMMAND_PRESETS: tuple[str, ...] = (
    "--help",
    "--version",
    # ── Health & Discovery ────────────────────────────────────────────────────
    "─── Health & Discovery ───",
    "doctor",
    "doctor --apply",
    "self-doctor",
    "self-doctor --fix",
    "systems",
    "tools-audit",
    "tools-audit --extra-path <PATH>",
    "tools-audit --show-unknown",
    # ── Reports & Stats ───────────────────────────────────────────────────────
    "─── Reports & Stats ───",
    "preview --all",
    "preview --system <SYSTEM>",
    "preview --system <SYSTEM> --format png",
    "preview --system <SYSTEM> --open",
    "report --all",
    "report --all --format csv",
    "report --all --no-media",
    "report --system <SYSTEM>",
    "stats",
    "stats --all",
    "stats --system <SYSTEM>",
    "stats-report",
    "stats-report --by-system",
    "stats-report --export <PATH>",
    "stats-report --recent",
    "stats-report --top 20",
    "stats-report build-wheel --apply",
    "stats-report build-wheel --limit 30 --apply",
    "stats-report clear-wheel",
    "stats-report clear-wheel --apply",
    # ── Audit & Inspect ───────────────────────────────────────────────────────
    "─── Audit & Inspect ───",
    "audit --all",
    "audit --all --detailed",
    "audit --all --no-media",
    "audit --all --report <PATH>",
    "audit --system <SYSTEM>",
    "audit --system <SYSTEM> --detailed",
    "check-discs --all",
    "check-discs --system <SYSTEM>",
    "find-dupes --all",
    "find-dupes --all --by-content",
    "find-dupes --all --cross-systems",
    "find-dupes --system <SYSTEM>",
    "find-misplaced --all",
    "find-misplaced --all --apply",
    "find-misplaced --all --verbose --apply",
    "find-misplaced --system <SYSTEM>",
    "find-orphan-media --all",
    "find-orphan-media --all --apply",
    "find-orphan-media --system <SYSTEM>",
    "inspect --system <SYSTEM>",
    "inspect --system <SYSTEM> --all",
    "inspect --system <SYSTEM> --all --format csv",
    "inspect --system <SYSTEM> --game <ROM>",
    "lint",
    "verify --system <SYSTEM> --dat <DAT_PATH>",
    "verify --system <SYSTEM> --dat <DAT_PATH> --show-good",
    # ── Curate & Cleanup ──────────────────────────────────────────────────────
    "─── Curate & Cleanup ───",
    "cleanup audit",
    "cleanup categories",
    "cleanup run --apply",
    "curate --all",
    "curate --all --action delete --apply --yes",
    "curate --all --apply",
    "curate --all --apply --yes",
    "curate --all --regions \"USA,EUR,JPN\" --apply",
    "curate --system <SYSTEM>",
    "ignore add <ROM>",
    "ignore add <ROM> --system <SYSTEM>",
    "ignore clear --system <SYSTEM> --yes",
    "ignore clear --yes",
    "ignore list",
    "ignore remove <ROM> --system <SYSTEM>",
    "match clear",
    "match list",
    # ── Metadata & Media ──────────────────────────────────────────────────────
    "─── Metadata & Media ───",
    "fetch-media --all",
    "fetch-media --all --apply",
    "fetch-media --all --source screenscraper --apply",
    "fetch-media --all --source thegamesdb --apply",
    "fetch-media --system <SYSTEM> --apply",
    "fetch-media --system <SYSTEM> --overwrite --apply",
    "fetch-media --system <SYSTEM> --types video --apply",
    "fetch-media --system <SYSTEM> --types wheel,background --apply",
    "fetch-meta --all",
    "fetch-meta --all --all-games --apply",
    "fetch-meta --all --apply",
    "fetch-meta --all --source screenscraper --apply",
    "fetch-meta --all --source thegamesdb --apply",
    "fetch-meta --system <SYSTEM> --apply",
    "fetch-meta --system <SYSTEM> --no-cache --apply",
    "media-add --system <SYSTEM> --game <ROM> --type video --file <PATH> --apply",
    "media-add --system <SYSTEM> --game <ROM> --type wheel --file <PATH> --apply",
    "media-scan --all",
    "media-scan --all --action move --apply",
    "media-scan --all --apply",
    "media-scan --all --detail",
    "media-scan --all --overwrite --apply",
    "media-scan --system <SYSTEM> --apply",
    # ── Database ──────────────────────────────────────────────────────────────
    "─── Database ───",
    "batch-edit --system <SYSTEM>",
    "batch-edit --system <SYSTEM> --filter \"name=*<QUERY>*\" --set genre=<GENRE> --apply",
    "batch-edit --system <SYSTEM> --list-manifests",
    "batch-edit --system <SYSTEM> --set genre=<GENRE> --apply",
    "batch-edit --system <SYSTEM> --undo <MANIFEST>",
    "update-db --all",
    "update-db --all --add-missing --remove-orphans --apply",
    "update-db --all --apply",
    "update-db --system <SYSTEM>",
    "update-db --system <SYSTEM> --add-missing --apply",
    "update-db --system <SYSTEM> --apply",
    "update-db --system <SYSTEM> --remove-orphans --apply",
    # ── Wheels ────────────────────────────────────────────────────────────────
    "─── Wheels ───",
    "fav add <SYSTEM> <ROM>",
    "fav clear",
    "fav clear --apply",
    "fav list",
    "fav rebuild --apply",
    "fav remove <SYSTEM> <ROM>",
    "fav sync",
    "recent clear",
    "recent clear --apply",
    "recent list",
    "recent rebuild --apply",
    # ── Main Menu ─────────────────────────────────────────────────────────────
    "─── Main Menu ───",
    "mainmenu add <SYSTEM> --apply",
    "mainmenu edit",
    "mainmenu hide <SYSTEM> --apply",
    "mainmenu remove <SYSTEM> --apply",
    "mainmenu reorder <SYSTEM> <POSITION> --apply",
    "mainmenu show",
    "mainmenu sort alpha --apply",
    "mainmenu sort manufacturer --apply",
    "mainmenu sort year --apply",
    # ── Generate & Organize ───────────────────────────────────────────────────
    "─── Generate & Organize ───",
    "generate-config",
    "generate-config --all --apply",
    "generate-config --all --no-main-menu --apply",
    "generate-config --all --no-rl --apply",
    "generate-config --system <SYSTEM> --apply",
    "organize <SYSTEM>",
    "organize <SYSTEM> --apply",
    "organize <SYSTEM> --overwrite-sort --apply",
    "organize <SYSTEM> --restructure --apply",
    "organize <SYSTEM> --restructure --undo",
    # ── Add & Bootstrap ───────────────────────────────────────────────────────
    "─── Add & Bootstrap ───",
    "add-pc-system <SYSTEM>",
    "add-pc-system <SYSTEM> --apply",
    "add-pc-system <SYSTEM> --no-game-media --apply",
    "add-system <SYSTEM>",
    "add-system <SYSTEM> --apply",
    "add-system <SYSTEM> --no-game-media --apply",
    "pc-rename <SYSTEM>",
    "pc-rename <SYSTEM> --no-interactive",
    "pc-rename <SYSTEM> --no-interactive --apply",
    # ── Rename & Clone ────────────────────────────────────────────────────────
    "─── Rename & Clone ───",
    "clone --list-manifests",
    "clone --system <SYSTEM> --game <ROM> --to <NEW_ROM>",
    "clone --system <SYSTEM> --game <ROM> --to <NEW_ROM> --apply",
    "find-global <QUERY>",
    "find-global <QUERY> --exact",
    "rename --list-manifests",
    "rename --system <SYSTEM> --game <ROM> --to <NEW_ROM>",
    "rename --system <SYSTEM> --game <ROM> --to <NEW_ROM> --apply",
    # ── LEDBlinky ─────────────────────────────────────────────────────────────
    "─── LEDBlinky ───",
    "ledblinky admin-buttons set --player 3 --colors \"<C1,C2,C3,C4,C5,C6>\" --apply",
    "ledblinky audit",
    "ledblinky audit --system MAME",
    "ledblinky check",
    "ledblinky colors brightness --scale 100",
    "ledblinky colors brightness --scale 100 --apply",
    "ledblinky colors brightness --scale <PCT> --apply",
    "ledblinky colors edit <NAME> --hex <RRGGBB> --apply",
    "ledblinky colors edit <NAME> --name <NEW_NAME> --apply",
    "ledblinky colors list",
    "ledblinky colors normalize",
    "ledblinky colors normalize --apply",
    "ledblinky colors normalize --apply --verbose",
    "ledblinky colors randomize",
    "ledblinky colors randomize --apply",
    "ledblinky colors randomize --seed <N> --apply",
    "ledblinky colors sync-players",
    "ledblinky colors sync-players --apply",
    "ledblinky colors sync-players --apply --verbose",
    "ledblinky colors sync-players --apply --override",
    "ledblinky colors sync-players --apply --override --verbose",
    "ledblinky fill-defaults",
    "ledblinky fill-defaults --admin-buttons 6 --admin-color <COLOR> --apply",
    "ledblinky fill-defaults --apply",
    "ledblinky fill-defaults --color <COLOR> --buttons 6 --players 2 --apply",
    "ledblinky fill-defaults --override-uniform --apply",
    "ledblinky fill-defaults --override-uniform --no-add-keys --apply",
    "ledblinky fill-defaults --system <SYSTEM> --apply",
    "ledblinky fix",
    "ledblinky fix --apply",
    "ledblinky setup",
    "ledblinky setup --apply",
    "ledblinky setup --apply --verbose",
    "ledblinky setup --overwrite --apply",
    "ledblinky generate",
    "ledblinky generate --apply",
    "ledblinky generate --overwrite --apply",
    "ledblinky generate --system MAME --apply",
    "ledblinky inspect-rom <ROM>",
    "ledblinky patch-settings",
    "ledblinky patch-settings --apply",
    "ledblinky patch-settings --fe-lwa \"\" --apply",
    "ledblinky patch-settings --fe-lwa \"<FILE>\" --apply",
    "ledblinky patch-settings --ss-lwa \"<FILE>\" --apply",
    "ledblinky patch-settings --game-lwa \"<FILE>\" --apply",
    # ── Lightgun ──────────────────────────────────────────────────────────────
    "─── Lightgun ───",
    "lightgun audit",
    "lightgun configure",
    "lightgun configure --system <SYSTEM> --apply",
    "lightgun detect",
    # ── Emulator Titles ───────────────────────────────────────────────────────
    "─── Emulator Titles ───",
    "emulator-title list",
    "emulator-title remove <EMULATOR>",
    "emulator-title set <EMULATOR> <WINDOW_TITLE>",
    # ── Backup & Migration ────────────────────────────────────────────────────
    "─── Backup & Migration ───",
    "backup create --target <PATH>",
    "backup create --target <PATH> --apply",
    "backup info --backup <PATH>",
    "backup list --target <PATH>",
    "backup restore --backup <PATH> --apply",
    "diff <BACKUP_FOLDER>",
    "diff <BACKUP_FOLDER> --component databases",
    "diff <BACKUP_FOLDER> --component media",
    "diff <BACKUP_FOLDER> --component roms",
    "migrate --list-manifests",
    "migrate --target <PATH>",
    "migrate --target <PATH> --apply",
    "migrate --target <PATH> --apply --keep-source",
    "migrate --undo latest --apply",
    # ── Scrub & Restore ───────────────────────────────────────────────────────
    "─── Scrub & Restore ───",
    "scrub --favorites",
    "scrub --favorites --apply",
    "scrub --hs-favorites --apply",
    "scrub --stats",
    "scrub --stats --apply",
    "scrub-restore <BACKUP_PATH>",
    "scrub-restore <BACKUP_PATH> --apply",
    # ── Themes ────────────────────────────────────────────────────────────────
    "─── Themes ───",
    "theme-apply --list-manifests",
    "theme-apply --undo latest",
    "theme-apply --undo latest --revert-system <SYSTEM>",
    "theme-apply <SOURCE_DIR>",
    "theme-apply <SOURCE_DIR> --apply",
    "theme-apply <SOURCE_DIR> --systems \"<SYSTEM1,SYSTEM2>\" --apply",
    "theme-apply <SOURCE_DIR> --target frontend --apply",
    "theme-pack-create <OUTPUT_DIR>",
    "theme-pack-create <OUTPUT_DIR> --target frontend",
    "theme-scan",
    "theme-scan --keyword xbox",
    "theme-scan --output <PATH>",
    "theme-scan --system <SYSTEM>",
    # ── Tools ─────────────────────────────────────────────────────────────────
    "─── Tools ───",
    "install-tools",
    "install-tools --add-to-system <SYSTEM>",
    "uninstall-tools --apply",
    # ── Config ────────────────────────────────────────────────────────────────
    "─── Config ───",
    "config init",
    "config set <KEY> <VALUE>",
    "config set hyperspin_dir <PATH>",
    "config set ledblinky_dir <PATH>",
    "config set rocketlauncher_dir <PATH>",
    # ScreenScraper per-app developer credentials. The "SpinDoctor" defaults
    # in `Config` are kept for backwards-compat; override these if ScreenScraper
    # has issued you a real registered developer credential or rejects the
    # defaults with HTTP 403. Surfaces only here in the dropdown.
    "config set screenscraper_devid <VALUE>",
    "config set screenscraper_devpassword <VALUE>",
    "config show",
    "config system list",
    "config system set <SYSTEM> --layout flat",
    "config verify-credentials",
)


_HELP_TEXT = (
    f"{__app_name__} GUI {__version__} — Tkinter launcher for the SpinDoctor CLI.\n"
    "\n"
    "Usage:\n"
    "  spindoctor-gui              Open the windowed launcher.\n"
    "  spindoctor-gui --version    Print the version and exit.\n"
    "  spindoctor-gui --help       Print this help and exit.\n"
    "\n"
    "Use spindoctor.exe for the full CLI; this binary just wraps it in a window.\n"
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point referenced by the ``spindoctor-gui`` console script.

    Accepts ``--version`` / ``--help`` so the release smoke test can verify
    the frozen exe loads without spawning a real Tk window on the CI runner.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(_HELP_TEXT)
        return 0
    if args and args[0] in ("-V", "--version"):
        print(f"{__app_name__} GUI, version {__version__}")
        return 0
    if args:
        print(f"Unknown argument: {args[0]}", file=sys.stderr)
        print(_HELP_TEXT, file=sys.stderr)
        return 2

    # Imported lazily so unit tests can import the module on headless CI
    # (where Tk's display init would otherwise fail) and so `--version`
    # works on a frozen exe even if Tk's runtime files are missing.
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError as exc:  # pragma: no cover — stdlib on supported platforms
        print(
            f"Tkinter is not available in this Python install: {exc}\n"
            "On Linux, install the python3-tk package; on Windows the "
            "standard python.org installer ships it.",
            file=sys.stderr,
        )
        return 1

    from ._singleton import SingletonLock, default_lock_path

    lock = SingletonLock(default_lock_path())
    if not lock.acquire():
        try:
            import tkinter as _tk_warn
            from tkinter import messagebox as _mb_warn

            _root = _tk_warn.Tk()
            _root.withdraw()
            _mb_warn.showwarning(
                f"{__app_name__} already running",
                f"Another {__app_name__} window is already open on this "
                "machine. Two GUIs editing the same HyperSpin XML at the "
                "same time can corrupt your library. Bring the existing "
                "window to the front instead, or close it and re-launch.",
            )
            _root.destroy()
        except Exception:  # noqa: BLE001 — last-ditch user notice
            print(
                f"{__app_name__} is already running on this machine.",
                file=sys.stderr,
            )
        return 1

    try:
        app = _SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
        app.mainloop()
    finally:
        lock.release()
    return 0


class _SpinDoctorGUI:
    """The Tkinter window. Constructed via :func:`main`."""

    def __init__(self, tk_mod, ttk_mod, filedialog_mod, messagebox_mod, scrolledtext_mod):
        self.tk = tk_mod
        self.ttk = ttk_mod
        self.filedialog = filedialog_mod
        self.messagebox = messagebox_mod
        self.scrolledtext = scrolledtext_mod

        # Use tkinterdnd2's TkinterDnD.Tk() when available so Setup-tab
        # path Entries can accept dragged folders from Explorer/Finder.
        # Falls back to plain tk.Tk() when the dependency isn't
        # installed — DnD is a nice-to-have, not a hard requirement.
        # Detected once, cached on self so _build_setup_tab knows
        # whether to register drop targets.
        self._dnd_available = False
        try:
            from tkinterdnd2 import TkinterDnD  # type: ignore

            self.root = TkinterDnD.Tk()
            self._dnd_available = True
            # Stash the module ref so the Setup tab can call
            # `tkinterdnd2.DND_FILES` without re-importing.
            self._tkdnd = __import__("tkinterdnd2")
        except Exception:  # noqa: BLE001 - any import failure → no DnD
            self.root = tk_mod.Tk()
        self.root.title(f"{__app_name__} {__version__}")

        # Load persisted GUI prefs once, before any widgets are built —
        # tk scaling and the initial geometry both have to honour the
        # saved ui_scale, and tk scaling MUST be applied before widget
        # construction to take effect on geometry metrics.
        try:
            _bootstrap_cfg = load_config()
            self._ui_scale = _clamp_ui_scale(getattr(_bootstrap_cfg, "ui_scale", 1.0))
            self._output_visible = bool(getattr(_bootstrap_cfg, "output_visible", True))
        except Exception:  # noqa: BLE001 — never let a bad config block launch
            self._ui_scale = 1.0
            self._output_visible = True

        # Named-font baseline (captured once so subsequent zooms don't
        # compound rounding error). Filled in by _apply_ui_scale().
        self._base_font_sizes: dict[str, int] = {}
        self._base_tk_scaling: float = 1.0
        self._apply_ui_scale(self._ui_scale, initial=True)

        # Geometry honours the persisted scale so 1.5× on a small screen
        # still opens to a usable size, not a Postage-stamp.
        base_w, base_h = 960, 720
        min_w, min_h = 720, 540
        scaled_w = max(min_w, int(base_w * self._ui_scale))
        scaled_h = max(min_h, int(base_h * self._ui_scale))
        # If the user resized / moved the window last session, restore
        # that geometry instead of the scaled default. Validate it's a
        # plausible "WxH+X+Y" or "WxH" string so a hand-corrupted
        # config.json can't pass garbage to Tk.
        restored = False
        saved_geom = getattr(_bootstrap_cfg, "gui_window_geometry", "") or ""
        if saved_geom and _is_plausible_geometry(saved_geom):
            try:
                self.root.geometry(saved_geom)
                restored = True
            except Exception:  # noqa: BLE001 - Tk rejects malformed strings
                restored = False
        if not restored:
            self.root.geometry(f"{scaled_w}x{scaled_h}")
        self.root.minsize(min_w, min_h)
        # Restore maximized state after the normal geometry is set so
        # un-maximizing later snaps back to the saved window size.
        if getattr(_bootstrap_cfg, "gui_window_maximized", False):
            self.root.after_idle(lambda: _set_maximized(self.root))
        # Stash the persisted last-active tab for _build_layout to read
        # after the notebook is built.
        self._restore_tab_idx = int(getattr(_bootstrap_cfg, "gui_last_active_tab", -1))

        # Window icon — cosmetic, must never block startup.
        self._load_window_icon()

        # ttk widgets (Checkbutton, Radiobutton, Button, …) don't accept
        # `foreground=` as a direct constructor option — it must come
        # from a named ttk.Style. Define the styles we need up front so
        # tab builders can reference them by name (`style="Unsafe…"`).
        self._ttk_style = ttk_mod.Style(self.root)

        # Apply dark theme BEFORE any tab builders run so every widget
        # they create inherits the palette. _apply_dark_theme installs
        # the ttk style overrides AND the option_add defaults that
        # non-ttk widgets (Menu, Listbox, Text, Canvas, PanedWindow,
        # Toplevel) read at construction time.
        self._apply_dark_theme()

        self._ttk_style.configure("Unsafe.TCheckbutton", foreground=_FG_DIMMER)

        self._proc: Optional[subprocess.Popen] = None
        self._line_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        # First monotonic time we saw ``_proc.poll()`` return non-None
        # without a DoneMarker landing in the queue. The stuck detector
        # in ``_drain_queue`` uses this to synthesise a marker when the
        # subprocess has exited but its stdout pipe never produced EOF
        # (a known Rich-progress-in-pipe-mode failure mode).
        self._stuck_check_since: Optional[float] = None

        # Chained-workflow state. None means "single command — show the
        # indeterminate spinner"; a (step, total) tuple means "switch
        # the progress bar to determinate at step/total of the way". See
        # `_chain_start` / `_chain_advance` / `_chain_end`.
        self._chain_progress: Optional[tuple[int, int]] = None

        # Per-run history buffered for the Logs tab. The Output panel
        # at the bottom of the window only shows the current run; the
        # Logs tab indexes everything since launch so you can scroll
        # back to "what did that dry-run say?" without re-running.
        # 200 is hours of cabinet use — more than the user scrolls; the
        # bounded deque caps memory without explicit pop(0) calls.
        self._run_history: Deque[_RunRecord] = deque(maxlen=200)
        self._current_run: Optional[_RunRecord] = None

        # Tab-badge state — tracks which notebook tab launched the
        # currently running command so we can stamp ✓/✗ on finish.
        self._tab_base_names: list[str] = []  # base label per tab index
        self._running_tab_idx: Optional[int] = None
        # Per-tab status overlays. Run badges (⟳/✓/✗) are stamped by
        # _run_cli / _on_proc_done; health badges (✓/⚠/✗/·) are stamped
        # by the startup doctor pass and reflect the overall health of
        # the area each tab covers. Both render through _render_tab_label
        # so neither one overwrites the other.
        self._tab_run_badges: dict[int, str] = {}
        self._tab_health_badges: dict[int, str] = {}

        # Setup-tab field vars; populated in _build_setup_tab().
        self._setup_vars: dict[str, "tk_mod.StringVar"] = {}

        # Global Apply / Verbose flags — shared across all tabs.
        # The actual BooleanVar objects are initialised inside _build_layout()
        # (they need self.tk to exist and the root window to be ready).
        # Declare as None here so type-checkers and any early references
        # survive without AttributeError.
        self._global_apply_var = None  # type: ignore[assignment]
        self._global_verbose_var = None  # type: ignore[assignment]

        self._build_layout()
        # Defer the system scan and health checks until after the first
        # paint. They touch disk (HyperSpin databases dir) and spawn a
        # subprocess (resolve_cli_command), which on a slow NAS or
        # large library can stall the window for noticeable beats.
        # Status-bar message keeps the user informed; the work then
        # populates the system combos and writes the real status when
        # done. See _initial_scan for the orchestration.
        self._set_status("Scanning library…")
        self.root.after_idle(self._initial_scan)
        # 50 ms polling is fast enough to feel real-time without busy-looping.
        # Track the `after` id so _on_close can cancel it; otherwise the
        # callback re-fires on a destroyed root and raises TclError.
        self._drain_after_id: Optional[str] = self.root.after(
            50, self._drain_queue
        )
        try:
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:  # noqa: BLE001 - protocol() can fail in test stubs
            pass
        # Kick off the GitHub release-tag check on a background thread
        # so a slow / unreachable GitHub doesn't delay the first paint.
        # Result lands in the status bar via _on_update_check_done.
        self._start_update_check()
        # First-run wizard is opt-in via the Setup-tab button and the
        # Help menu — no longer auto-fires at launch. Cabinet owners who
        # already approved the upgrade by launching the binary don't
        # need a modal in their face on first paint; `_startup_health_
        # checks` already surfaces missing-config problems in the
        # status bar, and the Setup tab is the natural starting point.

    # ── Dark theme ────────────────────────────────────────────────────────────

    def _apply_dark_theme(self) -> None:
        """Apply the dark palette to ttk styles and tk widget defaults.

        Two pieces:

        * ``ttk.Style`` overrides — themed widgets read these.
        * ``option_add`` defaults for ``Menu`` / ``Listbox`` / ``Text`` /
          ``Canvas`` / ``Toplevel`` — these are classic Tk widgets that
          ttk doesn't theme. The defaults take effect for any widget
          *constructed after* ``option_add`` runs, which is why this
          method must run before the tab builders touch anything.

        Idempotent: safe to call more than once. There's no light-mode
        toggle — dark is always on. The native macOS menubar can't be
        themed by Tk; that's an OS limitation.
        """
        # Force the `clam` theme as the base — it's the only stock Tk
        # theme that fully respects custom backgrounds across all
        # widgets (the platform-native themes "aqua" / "vista" /
        # "winnative" override our colours on buttons, scrollbars, and
        # combobox internals).
        try:
            self._ttk_style.theme_use("clam")
        except self.tk.TclError:
            pass

        s = self._ttk_style

        # Tk 8.5 (Python 3.8 on Win7 cabinets) doesn't recognise some
        # clam-theme style options that landed in 8.6 — `arrowcolor` is
        # the one we use. Passing it to `style.configure` on 8.5 raises
        # a TclError mid-init and the rest of the theming below would
        # never apply, leaving the window with default colours. Wrap
        # the at-risk configures so we strip the unknown key and retry,
        # rather than letting the whole dark theme silently break.
        def _safe_configure(style_name, **kwargs):
            try:
                s.configure(style_name, **kwargs)
            except self.tk.TclError:
                kwargs.pop("arrowcolor", None)
                try:
                    s.configure(style_name, **kwargs)
                except self.tk.TclError:
                    pass

        # ── Root + every container ──────────────────────────────────────────
        self.root.configure(background=_DARK_BG)
        s.configure(".", background=_DARK_BG, foreground=_DARK_FG,
                    fieldbackground=_DARK_BG_INPUT, bordercolor=_DARK_BORDER,
                    lightcolor=_DARK_BG_RAISE, darkcolor=_DARK_BORDER,
                    troughcolor=_DARK_BG_RAISE, insertcolor=_DARK_FG,
                    selectbackground=_DARK_BG_SELECT, selectforeground=_DARK_FG)
        s.configure("TFrame", background=_DARK_BG)
        s.configure("TLabel", background=_DARK_BG, foreground=_DARK_FG)
        s.configure("TLabelframe", background=_DARK_BG,
                    bordercolor=_DARK_BORDER)
        s.configure("TLabelframe.Label", background=_DARK_BG,
                    foreground=_DARK_FG)
        s.configure("TSeparator", background=_DARK_BORDER)

        # ── Buttons ──────────────────────────────────────────────────────────
        s.configure("TButton", background=_DARK_BG_BUTTON,
                    foreground=_DARK_FG, bordercolor=_DARK_BORDER,
                    lightcolor=_DARK_BG_BUTTON, darkcolor=_DARK_BG_BUTTON,
                    focusthickness=1, focuscolor=_DARK_ACCENT, padding=4)
        s.map("TButton",
              background=[("active", _DARK_BG_ACTIVE),
                          ("pressed", _DARK_BG_ACTIVE),
                          ("disabled", _DARK_BG_RAISE)],
              foreground=[("disabled", _FG_DIMMER)])

        # ── Entry / Combobox / Spinbox ───────────────────────────────────────
        s.configure("TEntry", fieldbackground=_DARK_BG_INPUT,
                    foreground=_DARK_FG, bordercolor=_DARK_BORDER,
                    insertcolor=_DARK_FG, lightcolor=_DARK_BORDER,
                    darkcolor=_DARK_BORDER)
        s.map("TEntry",
              fieldbackground=[("disabled", _DARK_BG_RAISE)],
              foreground=[("disabled", _FG_DIMMER)])
        _safe_configure("TCombobox", fieldbackground=_DARK_BG_INPUT,
                        background=_DARK_BG_BUTTON, foreground=_DARK_FG,
                        arrowcolor=_DARK_FG, bordercolor=_DARK_BORDER,
                        lightcolor=_DARK_BORDER, darkcolor=_DARK_BORDER,
                        insertcolor=_DARK_FG)
        s.map("TCombobox",
              fieldbackground=[("readonly", _DARK_BG_INPUT),
                               ("disabled", _DARK_BG_RAISE)],
              foreground=[("disabled", _FG_DIMMER)],
              selectbackground=[("readonly", _DARK_BG_SELECT)],
              selectforeground=[("readonly", _DARK_FG)])
        _safe_configure("TSpinbox", fieldbackground=_DARK_BG_INPUT,
                        foreground=_DARK_FG, bordercolor=_DARK_BORDER,
                        arrowcolor=_DARK_FG)

        # ── Check / Radio buttons ────────────────────────────────────────────
        s.configure("TCheckbutton", background=_DARK_BG, foreground=_DARK_FG,
                    indicatorbackground=_DARK_BG_INPUT,
                    indicatorforeground=_DARK_FG, focuscolor=_DARK_ACCENT)
        s.map("TCheckbutton",
              background=[("active", _DARK_BG)],
              indicatorbackground=[("selected", _DARK_BG_SELECT),
                                   ("pressed", _DARK_BG_ACTIVE)])
        s.configure("TRadiobutton", background=_DARK_BG, foreground=_DARK_FG,
                    indicatorbackground=_DARK_BG_INPUT,
                    indicatorforeground=_DARK_FG)
        s.map("TRadiobutton",
              background=[("active", _DARK_BG)],
              indicatorbackground=[("selected", _DARK_BG_SELECT)])

        # ── Notebook (tab strip) ─────────────────────────────────────────────
        # Pass tabmargins as a space-joined string rather than a tuple
        # — some older Tk 8.5 builds (Python 3.8 on Win7) reject the
        # tuple form with `bad screen distance`; the string form is
        # accepted everywhere.
        s.configure("TNotebook", background=_DARK_BG, borderwidth=0,
                    tabmargins="2 4 2 0")
        s.configure("TNotebook.Tab", background=_DARK_BG_RAISE,
                    foreground=_FG_DIM, padding=(10, 4),
                    bordercolor=_DARK_BORDER, lightcolor=_DARK_BG_RAISE)
        s.map("TNotebook.Tab",
              background=[("selected", _DARK_BG),
                          ("active", _DARK_BG_ACTIVE)],
              foreground=[("selected", _DARK_FG),
                          ("active", _DARK_FG)],
              expand=[("selected", (1, 1, 1, 0))])

        # ── Scrollbars / Progressbar / Separator ─────────────────────────────
        # Thumb (_DARK_SCROLL_THUMB) is deliberately much lighter than the
        # trough (_DARK_BG_RAISE) so the draggable part is obvious. Letting
        # clam draw its native lightcolor / darkcolor bevel keeps a faint
        # 3-D edge that helps the thumb pop without looking cartoonish.
        _safe_configure("Vertical.TScrollbar",
                        background=_DARK_SCROLL_THUMB,
                        troughcolor=_DARK_BG_RAISE,
                        bordercolor=_DARK_BORDER, arrowcolor=_DARK_FG)
        _safe_configure("Horizontal.TScrollbar",
                        background=_DARK_SCROLL_THUMB,
                        troughcolor=_DARK_BG_RAISE,
                        bordercolor=_DARK_BORDER, arrowcolor=_DARK_FG)
        s.map("Vertical.TScrollbar",
              background=[("active", _DARK_SCROLL_THUMB_ACTIVE)])
        s.map("Horizontal.TScrollbar",
              background=[("active", _DARK_SCROLL_THUMB_ACTIVE)])
        s.configure("TProgressbar", background=_DARK_ACCENT,
                    troughcolor=_DARK_BG_RAISE, bordercolor=_DARK_BORDER,
                    lightcolor=_DARK_ACCENT, darkcolor=_DARK_ACCENT)

        # ── Treeview (Logs tab, Main Menu, Log viewer dialog) ────────────────
        s.configure("Treeview", background=_DARK_BG_INPUT,
                    fieldbackground=_DARK_BG_INPUT, foreground=_DARK_FG,
                    bordercolor=_DARK_BORDER, rowheight=22)
        s.map("Treeview",
              background=[("selected", _DARK_BG_SELECT)],
              foreground=[("selected", _DARK_FG)])
        s.configure("Treeview.Heading", background=_DARK_BG_RAISE,
                    foreground=_DARK_FG, bordercolor=_DARK_BORDER,
                    relief="flat")
        s.map("Treeview.Heading",
              background=[("active", _DARK_BG_ACTIVE)])

        # ── PanedWindow sash (themed indirectly via Tk options) ──────────────
        s.configure("TPanedwindow", background=_DARK_BG)
        s.configure("Sash", background=_DARK_BORDER, sashthickness=6)

        # ── option_add defaults for the classic-Tk widgets ───────────────────
        # These take effect at widget construction time, so the call MUST
        # run before _build_layout(). That's enforced by the call site in
        # __init__.
        opts = {
            "*background": _DARK_BG,
            "*foreground": _DARK_FG,
            "*Toplevel.background": _DARK_BG,
            "*Menu.background": _DARK_BG_RAISE,
            "*Menu.foreground": _DARK_FG,
            "*Menu.activeBackground": _DARK_BG_SELECT,
            "*Menu.activeForeground": _DARK_FG,
            "*Menu.selectColor": _DARK_FG,
            "*Menu.borderWidth": 0,
            "*Menu.relief": "flat",
            "*Menubutton.background": _DARK_BG_RAISE,
            "*Menubutton.foreground": _DARK_FG,
            "*Listbox.background": _DARK_BG_INPUT,
            "*Listbox.foreground": _DARK_FG,
            "*Listbox.selectBackground": _DARK_BG_SELECT,
            "*Listbox.selectForeground": _DARK_FG,
            "*Listbox.highlightBackground": _DARK_BORDER,
            "*Listbox.highlightColor": _DARK_ACCENT,
            "*Listbox.borderWidth": 1,
            "*Listbox.relief": "flat",
            "*Text.background": _DARK_BG_INPUT,
            "*Text.foreground": _DARK_FG,
            "*Text.selectBackground": _DARK_BG_SELECT,
            "*Text.selectForeground": _DARK_FG,
            "*Text.insertBackground": _DARK_FG,
            "*Text.highlightBackground": _DARK_BORDER,
            "*Text.highlightColor": _DARK_ACCENT,
            "*Text.borderWidth": 1,
            "*Text.relief": "flat",
            "*Canvas.background": _DARK_BG,
            "*Canvas.highlightBackground": _DARK_BG,
            "*Entry.background": _DARK_BG_INPUT,
            "*Entry.foreground": _DARK_FG,
            "*Entry.insertBackground": _DARK_FG,
            "*Entry.selectBackground": _DARK_BG_SELECT,
            "*Entry.selectForeground": _DARK_FG,
            "*PanedWindow.background": _DARK_BORDER,
            "*PanedWindow.sashRelief": "flat",
            # ScrolledText is two widgets stacked — these set the *frame*
            # backgrounds; the inner Text widget picks up *Text.* above.
            "*ScrolledText.background": _DARK_BG,
            "*Frame.background": _DARK_BG,
            "*LabelFrame.background": _DARK_BG,
            "*Label.background": _DARK_BG,
            "*Label.foreground": _DARK_FG,
        }
        for key, value in opts.items():
            try:
                self.root.option_add(key, value)
            except self.tk.TclError:
                pass

    # ── UI scale ──────────────────────────────────────────────────────────────

    def _apply_ui_scale(self, scale: float, *, initial: bool = False) -> None:
        """Apply ``scale`` to named fonts (live) and tk scaling (initial only).

        See the plan: ``tk scaling`` only takes effect when applied before
        widget construction, so we set it once during __init__ and never
        again. Mid-session zoom updates only touch the named-font sizes,
        which Tk's geometry managers pick up on the next idle tick.
        """
        scale = _clamp_ui_scale(scale)
        try:
            from tkinter import font as tkfont
        except ImportError:
            return

        # Capture baselines on first call so repeated zooms stay precise.
        if not self._base_font_sizes:
            for name in _SCALED_FONT_NAMES:
                try:
                    f = tkfont.nametofont(name)
                    size = int(f.cget("size"))
                except Exception:  # noqa: BLE001
                    continue
                # Tk reports negative sizes when the font was created in
                # pixels rather than points; preserve sign on rescale.
                self._base_font_sizes[name] = size if size != 0 else 9

        if initial:
            try:
                self._base_tk_scaling = float(
                    self.root.tk.call("tk", "scaling")
                )
                self.root.tk.call(
                    "tk", "scaling", self._base_tk_scaling * scale,
                )
            except Exception:  # noqa: BLE001
                self._base_tk_scaling = 1.0

        for name, base in self._base_font_sizes.items():
            try:
                f = tkfont.nametofont(name)
            except Exception:  # noqa: BLE001
                continue
            sign = -1 if base < 0 else 1
            new = int(round(abs(base) * scale)) * sign
            if abs(new) < 6:
                new = 6 * sign
            try:
                f.configure(size=new)
            except Exception:  # noqa: BLE001
                continue

        self._ui_scale = scale
        if not initial:
            # Force pending geometry recomputations to flush now so the
            # window resizes immediately rather than on the next event.
            try:
                self.root.update_idletasks()
            except Exception:  # noqa: BLE001
                pass

    def _set_ui_scale(self, scale: float) -> None:
        """Apply a new scale, refresh the View menu radio, and persist."""
        scale = _clamp_ui_scale(scale)
        if abs(scale - self._ui_scale) < 1e-3:
            # Still refresh the radio var in case the user clicked the
            # currently-active preset — keeps the UI consistent.
            if hasattr(self, "_ui_scale_var"):
                self._ui_scale_var.set(f"{scale:g}")
            return
        self._apply_ui_scale(scale)
        if hasattr(self, "_ui_scale_var"):
            self._ui_scale_var.set(f"{scale:g}")
        self._persist_ui_pref(ui_scale=scale)
        self._set_status(f"UI scale set to {scale:g}\u00d7.")

    def _ui_scale_step(self, delta: float) -> None:
        """Bump scale by ``delta`` (clamped). Snaps to one decimal place."""
        new = round(self._ui_scale + delta, 1)
        self._set_ui_scale(new)

    def _persist_ui_pref(self, **kwargs) -> None:
        """Save one or more GUI preferences back to config.json.

        Read-modify-write so we don't clobber settings other tabs may
        have just changed — the Setup tab writes the full config, but
        the View menu only touches its own keys.
        """
        try:
            cfg = load_config()
            for key, value in kwargs.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
            save_config(cfg)
        except Exception as exc:  # noqa: BLE001 — non-critical
            self._append_output(
                f"Note: could not persist UI preference: {exc}\n"
            )

    # ── Output pane toggle ────────────────────────────────────────────────────

    def _register_path_drop_target(self, widget, var) -> None:
        """Wire a Setup-tab path Entry as a drag-drop target for folders.

        No-op when ``tkinterdnd2`` isn't installed — the GUI still
        works, the user just has to type / paste / Browse like before.
        Available everywhere when the optional dep is installed; on
        Windows the user can drag a folder from Explorer onto the
        Entry and the absolute path lands in the StringVar.
        """
        if not getattr(self, "_dnd_available", False):
            return
        tkdnd = getattr(self, "_tkdnd", None)
        if tkdnd is None:
            return
        try:
            widget.drop_target_register(tkdnd.DND_FILES)
        except Exception:  # noqa: BLE001 - tkdnd APIs vary across versions
            return

        def _on_drop(event, _var=var):
            # event.data is a brace-quoted string for paths with spaces:
            #   "{C:/Games/My ROMs}" or "C:/Games/ROMs"
            # Tk's splitlist handles both shapes.
            try:
                parts = self.root.tk.splitlist(event.data)
            except Exception:  # noqa: BLE001
                parts = [event.data]
            if not parts:
                return event.action
            path = str(parts[0]).strip()
            # Strip the file:// URI scheme some platforms wrap around it.
            if path.startswith("file://"):
                from urllib.parse import unquote
                path = unquote(path[len("file://"):])
            _var.set(path)
            return event.action

        try:
            widget.dnd_bind("<<Drop>>", _on_drop)
        except Exception:  # noqa: BLE001
            pass

    def _toggle_system_filter(self) -> None:
        """Show / hide the system quick-filter bar.

        Toggle via Ctrl+Shift+F (Cmd+Shift+F on macOS). On open the bar
        is added above the notebook (the PanedWindow keeps the
        notebook + output panel below it pushed down), the Entry takes
        focus, and any existing filter is preserved. On close the
        filter pattern is cleared so the next launch starts with a
        full system list.
        """
        paned = getattr(self, "_main_paned", None)
        frame = getattr(self, "_system_filter_frame", None)
        if paned is None or frame is None:
            return
        if self._system_filter_visible:
            try:
                paned.forget(frame)
            except self.tk.TclError:
                pass
            self._system_filter_visible = False
            # Clear the filter on close so re-opening starts fresh.
            try:
                self._system_filter_var.set("")
            except self.tk.TclError:
                pass
            return
        try:
            # Insert at index 0 so the filter sits above the notebook.
            # ttk.PanedWindow uses ``insert`` for positional inserts; the
            # filter row carries weight=0 so the notebook + output panel
            # below it keep their share of the vertical real estate.
            paned.insert(0, frame, weight=0)
        except self.tk.TclError:
            return
        self._system_filter_visible = True
        try:
            self._system_filter_entry.focus_set()
        except self.tk.TclError:
            pass

    def _toggle_output(self, visible: Optional[bool] = None) -> None:
        """Show/hide the bottom Output panel.

        Called from the status-bar button, the View menu checkbutton, and
        the Ctrl+\\` shortcut. State is persisted so it survives restarts.
        """
        if visible is None:
            visible = not self._output_visible

        out_frame = getattr(self, "_out_frame", None)
        paned = getattr(self, "_main_paned", None)
        if out_frame is None or paned is None:
            return

        try:
            if visible:
                # paned.add() is a no-op if the pane is already managed.
                try:
                    paned.add(out_frame, weight=1)
                except self.tk.TclError:
                    pass
                # Restore the saved sash position after a short delay so
                # Tk has time to lay out the re-added pane before we move
                # the sash.  after_idle fires too early (before relayout),
                # so after(100) is used instead.
                target = getattr(self, "_output_saved_sash", None)
                def _restore_sash():
                    try:
                        h = paned.winfo_height()
                        pos = target if target is not None else max(200, h - 160)
                        paned.sashpos(0, pos)
                    except self.tk.TclError:
                        pass
                self.root.after(100, _restore_sash)
            else:
                # Capture the current sash so re-showing puts the output
                # back at the same height the user dragged it to.
                try:
                    pos = paned.sashpos(0)
                    if pos:
                        self._output_saved_sash = int(pos)
                except self.tk.TclError:
                    pass
                try:
                    paned.forget(out_frame)
                except self.tk.TclError:
                    pass
        finally:
            self._output_visible = bool(visible)

        # Update the status-bar button label + View menu checkbox so all
        # three entry points stay in lockstep.
        btn = getattr(self, "_output_toggle_btn", None)
        if btn is not None:
            btn.configure(text="Hide output" if visible else "Show output")
        var = getattr(self, "_output_visible_var", None)
        if var is not None:
            var.set(bool(visible))

        self._persist_ui_pref(output_visible=bool(visible))

    # ── Window icon ───────────────────────────────────────────────────────────

    def _load_window_icon(self) -> None:
        """Set the window icon if an asset is shipped with the package.

        Pure cosmetic — never propagate a failure. Stash the PhotoImage
        on ``self`` so Python's GC doesn't reclaim it (a classic Tk
        footgun: drop the reference and the icon disappears).
        """
        icon_dir = Path(__file__).parent / "assets"
        try:
            if sys.platform == "win32":
                ico = icon_dir / "icon.ico"
                if ico.exists():
                    # Pass the path positionally rather than via
                    # `default=` — older Tk 8.5 builds (Python 3.8.10
                    # for some Win7 cabinet setups) silently ignore
                    # the `default=` keyword and the icon never sets.
                    self.root.iconbitmap(str(ico))
                    return
            png = icon_dir / "icon.png"
            if png.exists():
                self._icon_photo = self.tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon_photo)
        except self.tk.TclError:
            pass

    def _initial_scan(self) -> None:
        """Deferred startup work: populate system pickers, run health
        checks. Runs from ``after_idle`` so the first frame paints
        immediately; on a slow NAS-mounted library this avoids a
        multi-second "is it frozen?" beat at launch.
        """
        try:
            self._refresh_systems()
        except Exception as exc:  # noqa: BLE001 — never let scan errors kill the GUI
            self._append_output(f"[startup scan] error: {exc}\n")
        self._startup_health_checks()

    def _startup_health_checks(self) -> None:
        """Surface obvious environment problems at first paint.

        Two problems used to hide until the user tried to do something:

        - Config paths missing / unset. Previously silent — the user
          only saw the error when they clicked Run on a tab that needed
          the missing path. Now we run cfg.is_valid() at startup and
          report any errors in the status bar.
        - The spindoctor CLI binary missing from PATH (frozen builds
          that got separated from their sibling exes, dev installs
          without `pip install -e .`). Previously raised CliNotFoundError
          on the user's first Run click. Now we probe at startup and
          surface a persistent status message.

        Both checks are read-only and fast — no subprocess, no disk
        writes — so doing them inline during __init__ is fine.
        """
        problems: list[str] = []
        try:
            ok, errors = load_config().is_valid()
            if not ok:
                problems.append(
                    f"Setup incomplete — {len(errors)} path(s) need "
                    "attention. Check the Setup tab."
                )
        except Exception as exc:  # noqa: BLE001 — surface in UI
            problems.append(f"Could not read config: {exc}")

        try:
            resolve_cli_command("spindoctor")
        except CliNotFoundError as exc:
            problems.append(f"spindoctor CLI not found — {exc}")

        if problems:
            # If there's more than one problem, join them with ' · '.
            # The status bar is a single line so a longer string gets
            # truncated visually, but the user can still hover or copy.
            self._set_status(" · ".join(problems))
        else:
            self._set_status("Ready.")

        # Fresh install — no config.json on disk at all — has nothing
        # to read in the status bar at the bottom of the window and no
        # context on which tab to click. Auto-select the Setup tab so
        # the new user lands on the form that needs filling in. (Only
        # on a true fresh install: once any config has been saved we
        # keep whatever tab was last active per `gui_last_active_tab`.)
        try:
            if not CONFIG_FILE.exists():
                setup_idx = self._tab_base_names.index("Setup")
                self._nb.select(setup_idx)
        except Exception:  # noqa: BLE001 — best-effort focus only
            pass

        # Kick off the deeper doctor pass on a worker thread so per-tab
        # health badges can populate without delaying first paint.
        # `_startup_health_checks` (this method) is cheap and runs
        # synchronously; `_compute_tab_health_badges` calls `doctor`
        # which touches disk and may take 100+ ms on a slow drive.
        threading.Thread(
            target=self._compute_tab_health_badges, daemon=True,
        ).start()

    # ── First-run wizard ──────────────────────────────────────────────────────

    def _show_first_run_wizard(self) -> None:
        """Three-step modal: welcome → pick paths → run doctor."""
        try:
            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = None

        win = self.tk.Toplevel(self.root)
        win.title(f"Welcome to {__app_name__}")
        win.transient(self.root)
        self._fit_geometry(win, 640, 480)
        try:
            win.grab_set()
        except Exception:  # noqa: BLE001 - WM that can't grab is fine
            pass

        # Stepped container — only one ttk.Frame is packed at a time;
        # navigation buttons swap which one is visible.
        step_holder = self.ttk.Frame(win, padding=18)
        step_holder.pack(fill="both", expand=True)

        nav = self.ttk.Frame(win, padding=(18, 8))
        nav.pack(fill="x")

        state: dict = {
            "step": 0,
            "frames": [],
            "path_vars": {},
            "doctor_text": None,
        }

        def show_step(idx: int) -> None:
            for f in state["frames"]:
                f.pack_forget()
            state["frames"][idx].pack(fill="both", expand=True)
            state["step"] = idx
            for child in nav.winfo_children():
                child.destroy()
            _nav_buttons(idx)

        # ── step 0: welcome ──────────────────────────────────────────────────
        welcome = self.ttk.Frame(step_holder)
        state["frames"].append(welcome)
        self.ttk.Label(
            welcome, text=f"Welcome to {__app_name__}!",
            font=("TkDefaultFont", 14, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        self.ttk.Label(
            welcome,
            text=(
                "Looks like this is your first run. Let's set up the "
                "paths SpinDoctor needs, then run a quick health check. "
                "Takes about 90 seconds.\n\n"
                "You can change everything later from the Setup tab, "
                "and re-open this wizard from Help → First-run setup…"
            ),
            wraplength=560, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # ── step 1: pick the two required paths ──────────────────────────────
        paths = self.ttk.Frame(step_holder)
        state["frames"].append(paths)
        self.ttk.Label(
            paths, text="Step 1 / 2 — Pick your cabinet folders",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self.ttk.Label(
            paths,
            text=("These two paths are required. Optional paths "
                  "(emulators, RocketLauncher, LEDBlinky) can be filled "
                  "in later from the Setup tab."),
            wraplength=560, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", pady=(0, 8))

        for key, label, win_default, _allow_blank in _SETUP_FIELDS:
            if key not in ("roms_dir", "hyperspin_dir"):
                continue
            initial = (getattr(cfg, key, "") if cfg else "") or win_default
            var = self.tk.StringVar(value=initial)
            state["path_vars"][key] = var
            row = self.ttk.Frame(paths)
            row.pack(fill="x", pady=4)
            self.ttk.Label(row, text=label, width=18).pack(side="left")
            self.ttk.Entry(row, textvariable=var, width=40).pack(
                side="left", padx=6, fill="x", expand=True,
            )
            self.ttk.Button(
                row, text="Browse…",
                command=lambda v=var, k=key: self._browse_dir(v, k),
            ).pack(side="left")

        # ── step 2: doctor output ────────────────────────────────────────────
        doctor = self.ttk.Frame(step_holder)
        state["frames"].append(doctor)
        self.ttk.Label(
            doctor, text="Step 2 / 2 — Health check",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self.ttk.Label(
            doctor,
            text=("Running spindoctor doctor — checks every dependency "
                  "and reports anything missing. Read the results below; "
                  "you can re-run this any time from the Audit tab."),
            wraplength=560, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", pady=(0, 6))
        doctor_txt = self._make_scrolled_text(
            doctor, height=14, wrap="word", font="TkFixedFont",
        )
        doctor_txt.pack(fill="both", expand=True, pady=(0, 4))
        doctor_txt.insert("end", "Running doctor…\n")
        doctor_txt.configure(state="disabled")
        state["doctor_text"] = doctor_txt

        # ── nav-button factory (rebuilt on each step transition) ─────────────
        def _save_and_close(skip: bool = False) -> None:
            try:
                cfg2 = load_config()
            except Exception:  # noqa: BLE001
                from .config import Config
                cfg2 = Config()
            if not skip:
                for key, var in state["path_vars"].items():
                    setattr(cfg2, key, var.get().strip())
            try:
                save_config(cfg2)
            except Exception as exc:  # noqa: BLE001
                self.messagebox.showerror(
                    "Could not save config", str(exc),
                )
                return
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass
            # Refresh tabs that depend on config (system pickers, etc.)
            self._refresh_systems()
            self._startup_health_checks()
            if not skip:
                self._set_status(
                    "Setup saved. Try Audit → Run doctor next."
                )

        def _run_doctor_async() -> None:
            from . import health
            try:
                cfg2 = load_config()
                report = health.run_health_checks(cfg2, fix=False)
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0, _doctor_done,
                    f"Could not run doctor: {exc}\n", health.Status.FAIL,
                )
                return
            # Render a tiny summary the user can act on.
            lines: list[str] = []
            symbol = {
                health.Status.OK: "✓",
                health.Status.WARN: "⚠",
                health.Status.FAIL: "✗",
                health.Status.INFO: "·",
            }
            for c in report.checks:
                lines.append(
                    f"{symbol.get(c.status, '·')} {c.name}: {c.detail}"
                )
                for child in c.children:
                    lines.append(
                        f"    {symbol.get(child.status, '·')} "
                        f"{child.name}: {child.detail}"
                    )
            text = "\n".join(lines) + "\n"
            self.root.after(0, _doctor_done, text, report.overall())

        def _doctor_done(text: str, _overall) -> None:
            doctor_txt.configure(state="normal")
            doctor_txt.delete("1.0", "end")
            doctor_txt.insert("end", text)
            doctor_txt.configure(state="disabled")

        def _nav_buttons(idx: int) -> None:
            if idx == 0:
                self.ttk.Button(
                    nav, text="Skip", command=lambda: _save_and_close(skip=True),
                ).pack(side="left")
                self.ttk.Button(
                    nav, text="Next →", command=lambda: show_step(1),
                ).pack(side="right")
            elif idx == 1:
                self.ttk.Button(
                    nav, text="← Back", command=lambda: show_step(0),
                ).pack(side="left")
                self.ttk.Button(
                    nav, text="Skip", command=lambda: _save_and_close(skip=True),
                ).pack(side="left", padx=8)
                self.ttk.Button(
                    nav, text="Save and continue →",
                    command=lambda: (
                        _save_paths_and_advance()
                    ),
                ).pack(side="right")
            elif idx == 2:
                self.ttk.Button(
                    nav, text="← Back", command=lambda: show_step(1),
                ).pack(side="left")
                self.ttk.Button(
                    nav, text="Finish", command=lambda: _save_and_close(),
                ).pack(side="right")

        def _save_paths_and_advance() -> None:
            # Persist the two paths immediately so the doctor run sees
            # them — without this, doctor would re-read the OLD config
            # from disk and complain about missing roms_dir/hyperspin_dir.
            try:
                cfg2 = load_config()
            except Exception:  # noqa: BLE001
                from .config import Config
                cfg2 = Config()
            for key, var in state["path_vars"].items():
                setattr(cfg2, key, var.get().strip())
            try:
                save_config(cfg2)
            except Exception as exc:  # noqa: BLE001
                self.messagebox.showerror(
                    "Could not save config", str(exc),
                )
                return
            show_step(2)
            threading.Thread(target=_run_doctor_async, daemon=True).start()

        show_step(0)
        win.bind("<Escape>", lambda _e: _save_and_close(skip=True))

    # ── tab health badges ─────────────────────────────────────────────────────
    #
    # Maps each doctor check name to one or more tabs that surface that
    # area. Maintained alongside `health.run_health_checks` — when a new
    # check ships there, add an entry here (or accept the default
    # "unmapped checks don't badge any tab" behaviour).
    _HEALTH_TO_TABS: dict[str, tuple[str, ...]] = {
        "Paths":                  ("Setup",),
        "External binaries":      ("Toolkit", "Setup"),
        "HyperSpin databases":    ("Diagnostics",),
        "Match cache":            ("Maintenance",),
        "Global Emulators.ini":   ("Metadata & Media",),
        "LEDBlinky":              ("LEDBlinky",),
        "Metadata APIs":          ("Setup",),
        "Media folders":          ("Metadata & Media",),
        # "lxml", "Archive support", "Preview support" are install-level
        # — no single tab owns them, so they don't badge anything. They
        # still surface via the Diagnostics tab's "Run doctor" output.
    }

    _HEALTH_BADGE = {
        # "ok" → no badge; user shouldn't need to see anything for
        # working areas (the absence of a warning IS the signal).
        "warn": "⚠",
        "fail": "✗",
        # "info" → no badge; not actionable enough to draw attention.
    }

    def _compute_tab_health_badges(self) -> None:
        """Run `doctor` in the background and stamp tabs with the
        worst status of every check that maps to them.

        Runs on a worker thread. Widget mutations marshal back to the
        main thread via `root.after(0, …)`.
        """
        try:
            from . import health
            cfg = load_config()
            report = health.run_health_checks(cfg, fix=False)
        except Exception:  # noqa: BLE001 - badges are best-effort
            return

        order = {"ok": 0, "info": 0, "warn": 1, "fail": 2}
        # tab label → worst seen status string
        worst_per_tab: dict[str, str] = {}
        for check in report.checks:
            tabs = self._HEALTH_TO_TABS.get(check.name)
            if not tabs:
                continue
            for tab_label in tabs:
                current = worst_per_tab.get(tab_label, "ok")
                if order[check.status.value] > order[current]:
                    worst_per_tab[tab_label] = check.status.value

        # Resolve tab labels → indices and schedule the badge update.
        updates: list[tuple[int, str]] = []
        for tab_label, status_str in worst_per_tab.items():
            try:
                idx = self._tab_base_names.index(tab_label)
            except ValueError:
                continue
            badge = self._HEALTH_BADGE.get(status_str, "")
            updates.append((idx, badge))

        if updates:
            try:
                self.root.after(0, self._apply_tab_health_badges, updates)
            except Exception:  # noqa: BLE001 - root may be destroyed in tests
                pass

    def _apply_tab_health_badges(self, updates: list) -> None:
        try:
            for idx, badge in updates:
                self._set_tab_health_badge(idx, badge)
        except Exception:  # noqa: BLE001 - widget race during teardown
            pass

    # ── themed scrolled text ──────────────────────────────────────────────────

    def _make_scrolled_text(self, parent, **text_options):
        """Build a Text + ttk.Scrollbar pair inside a Frame.

        ``scrolledtext.ScrolledText`` from the stdlib embeds a classic
        ``tk.Scrollbar``, which on Windows renders with the platform-native
        Win7 chrome and ignores our clam-based dark theme. This helper
        replaces it with a themed equivalent: a ``ttk.Frame`` containing
        a ``tk.Text`` plus a ``ttk.Scrollbar``. The Text widget is
        ``pack``-ed into the frame and is returned so call sites can
        keep their existing API (``insert`` / ``delete`` / ``see`` /
        ``configure`` / ``tag_configure`` / ``yview`` etc.). The owning
        frame is exposed via ``widget.master`` for layout calls (each
        call site already uses ``widget.pack(fill="both", …)``, which
        works because the frame fills its parent and the Text fills the
        frame).
        """
        # Outer frame holds the Text + Scrollbar so call sites get a
        # single widget to ``pack`` / ``grid``. ``ttk.Frame`` so the
        # background matches the dark theme without needing option_add.
        container = self.ttk.Frame(parent)
        text = self.tk.Text(container, **text_options)
        vsb = self.ttk.Scrollbar(
            container, orient="vertical", command=text.yview,
        )
        text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        # Stash the frame on the text so callers that want to ``pack``
        # the *outer* container (e.g. the Output panel's
        # ``fill="both", expand=True``) can do so via the same
        # variable they already hold. Tk's pack/grid on the Text widget
        # would only fill the inner cell, so we proxy those calls.
        text._spindoctor_outer_frame = container  # type: ignore[attr-defined]
        # Override pack / grid / place / pack_forget / grid_forget on
        # the text widget to operate on the *outer frame* instead, so
        # the four call sites that previously used a single ScrolledText
        # don't need to learn about the frame. This mirrors the
        # stdlib's own ScrolledText approach.
        for geom in ("pack", "grid", "place", "pack_forget", "grid_forget"):
            outer_method = getattr(container, geom)
            setattr(text, geom, outer_method)
        return text

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self._build_menubar()

        # Use grid on the root so the status bar (row 1, weight=0) is
        # ALWAYS allocated its natural height — pack's expand=True can
        # race with side=bottom items and push the bar off-screen on
        # smaller displays. Grid separates the concerns completely.
        self.root.rowconfigure(0, weight=1)   # main_paned grows/shrinks
        self.root.rowconfigure(1, weight=0)   # bar: fixed height, never hidden
        self.root.columnconfigure(0, weight=1)

        # Vertical PanedWindow splits the tab notebook (top) from the
        # Output panel (bottom). ttk.PanedWindow picks up the dark
        # ``TPanedwindow`` / ``Sash`` style so the sash matches the rest
        # of the theme instead of rendering with native Win7 chrome.
        main_paned = self.ttk.PanedWindow(self.root, orient="vertical")
        main_paned.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        # Stash the paned window so _toggle_output can forget/add the
        # output pane and restore the sash on demand.
        self._main_paned = main_paned

        # System quick-filter bar. Hidden by default; toggled via
        # Ctrl+Shift+F / Cmd+Shift+F. When visible, typing into it
        # narrows every system combobox across every tab to entries
        # whose name contains the filter text (case-insensitive). Lives
        # above the notebook so it's discoverable but doesn't steal
        # vertical space when not in use. The trace on the var calls
        # `_refresh_systems` so the dropdowns update live as the user
        # types — no commit-and-search step.
        self._system_filter_var = self.tk.StringVar(value="")
        self._system_filter_frame = self.ttk.Frame(main_paned)
        self._system_filter_visible = False
        self.ttk.Label(
            self._system_filter_frame,
            text="Filter systems: ", foreground=_FG_DIM,
        ).pack(side="left", padx=(8, 4))
        self._system_filter_entry = self.ttk.Entry(
            self._system_filter_frame,
            textvariable=self._system_filter_var,
            width=32,
        )
        self._system_filter_entry.pack(side="left", fill="x", expand=True)
        self.ttk.Button(
            self._system_filter_frame, text="Clear",
            command=lambda: self._system_filter_var.set(""),
        ).pack(side="left", padx=(4, 4))
        self.ttk.Button(
            self._system_filter_frame, text="Close",
            command=self._toggle_system_filter,
        ).pack(side="left", padx=(0, 8))
        # Trace fires on every keystroke (write mode). _refresh_systems
        # is cheap (≤ 1 ms for typical cabinets) so this stays snappy.
        self._system_filter_var.trace_add(
            "write", lambda *_a: self._refresh_systems(),
        )
        self._system_filter_entry.bind(
            "<Escape>", lambda _e: self._toggle_system_filter(),
        )

        nb = self.ttk.Notebook(main_paned)
        self._nb = nb

        # StringVar backing the status bar label — created early so
        # tab builders can safely call self._set_status() during
        # construction, mirroring the self._output hoist below.
        self._status_var = self.tk.StringVar(value="")

        # Create the Output panel widget BEFORE any tab builders run.
        # Tab builders (e.g. Main Menu's _mm_refresh) may call
        # self._append_output during construction; if self._output
        # doesn't exist yet, that raises AttributeError and the GUI
        # never paints. See also the matching note at _append_output.
        out_frame = self.ttk.LabelFrame(main_paned, text="Output")
        self._out_frame = out_frame

        # Find bar — hidden by default; toggled via Ctrl+F / Cmd+F.
        # Lives ABOVE the ScrolledText so showing it doesn't shrink the
        # output area (just nudges it down by one row).
        self._find_bar = self.ttk.Frame(out_frame)
        self.ttk.Label(self._find_bar, text="Find:").pack(side="left", padx=(4, 2))
        self._find_var = self.tk.StringVar(value="")
        self._find_entry = self.ttk.Entry(
            self._find_bar, textvariable=self._find_var, width=30,
        )
        self._find_entry.pack(side="left", padx=2)
        self._find_entry.bind("<Return>", lambda _e: self._find_next())
        self._find_entry.bind("<Shift-Return>", lambda _e: self._find_prev())
        self._find_entry.bind("<Escape>", lambda _e: self._find_close())
        # Refresh match highlights as the user types so the count
        # updates live. Trace on the StringVar fires on every change,
        # including programmatic ones (so the seed-from-selection in
        # _find_open also triggers a refresh).
        self._find_var.trace_add(
            "write", lambda *_a: self._refresh_find_matches(),
        )
        self.ttk.Button(
            self._find_bar, text="Next",
            command=self._find_next,
        ).pack(side="left", padx=2)
        self.ttk.Button(
            self._find_bar, text="Prev",
            command=self._find_prev,
        ).pack(side="left", padx=2)
        self._find_match_var = self.tk.StringVar(value="")
        self.ttk.Label(
            self._find_bar, textvariable=self._find_match_var,
            foreground=_FG_DIM,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            self._find_bar, text="✕",
            width=3, command=self._find_close,
        ).pack(side="right", padx=4)
        # Find-bar is packed/unpacked lazily by _find_open/_find_close.

        # Use TkFixedFont so the Output panel honours the UI scale knob
        # alongside the rest of the window. The named-font path also
        # picks up platform-appropriate monospace defaults (Consolas on
        # Windows, Menlo on macOS) without us hardcoding family names.
        self._output = self._make_scrolled_text(
            out_frame, height=14, wrap="word", font="TkFixedFont",
        )
        # Tags for find-bar match highlighting. Configured here so the
        # palette stays consistent with the dark theme without needing
        # to know which theme is active at tag-create time.
        self._output.tag_configure(
            "find-match", background="#503010", foreground=_DARK_FG,
        )
        self._output.tag_configure(
            "find-current", background="#a06000", foreground="#ffffff",
        )
        self._output.configure(state="disabled")
        self._output.pack(fill="both", expand=True, padx=4, pady=4)

        # Wrap each tab in a Canvas + always-visible Scrollbar so
        # cabinet owners on smaller screens (1024×768, 1280×720) can
        # still reach widgets that overflow the window. Each tab
        # builder creates its frame as before; the helper just bolts
        # a vertical scrollbar onto whichever container holds it.
        # Tab order follows the new-user journey: configure paths first
        # (Setup), then confirm the cabinet is healthy (Diagnostics is
        # read-only, so it's safe to explore before touching anything),
        # then build out systems (Systems), enrich metadata
        # (Metadata & Media), curate (Maintenance), manage cross-system
        # wheels (Toolkit), then peripheral hardware (LEDBlinky /
        # Lightgun), then infrastructure (Backup → Migration), and finally
        # power-user escapes (Console) and the session log (History)
        # at the very end.
        self._add_scrollable_tab(nb, self._build_setup_tab,        "Setup")
        self._add_scrollable_tab(nb, self._build_diagnostics_tab,  "Diagnostics")
        self._add_scrollable_tab(nb, self._build_systems_tab,      "Systems")
        self._add_scrollable_tab(nb, self._build_games_tab,        "Games")
        self._add_scrollable_tab(nb, self._build_metadata_tab,     "Metadata & Media")
        self._add_scrollable_tab(nb, self._build_maintenance_tab,  "Maintenance")
        self._add_scrollable_tab(nb, self._build_tools_tab,        "Toolkit")
        self._add_scrollable_tab(nb, self._build_ledblinky_tab,    "LEDBlinky")
        self._add_scrollable_tab(nb, self._build_lightgun_tab,     "Lightgun")
        self._add_scrollable_tab(nb, self._build_backup_tab,       "Backup & Restore")
        self._add_scrollable_tab(nb, self._build_migrate_tab,      "Migration")
        self._add_scrollable_tab(nb, self._build_custom_tab,       "Console")
        # History tab is the only one that intentionally fills its own
        # vertical space (tree + viewer panes), so it doesn't need
        # the wrapping scrollbar.
        nb.add(self._build_logs_tab(nb), text="History")
        self._tab_base_names.append("History")
        main_paned.add(nb, weight=4)
        main_paned.add(out_frame, weight=1)

        # Set initial sash position after the window has been painted so
        # we know the real allocated height. Target: output panel gets
        # ~160 px; notebook takes the rest. ttk.PanedWindow uses
        # ``sashpos`` (not the classic ``sash_place``).
        def _place_initial_sash():
            try:
                h = main_paned.winfo_height()
                if h > 300:
                    main_paned.sashpos(0, max(200, h - 160))
            except Exception:  # noqa: BLE001 - widget race during teardown
                pass
        self.root.after(100, _place_initial_sash)

        # Status bar — grid row 1, always visible.
        # NB: self._status_var is created earlier in this method so
        # tab builders can call _set_status() during construction.
        bar = self.ttk.Frame(self.root)
        bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.ttk.Label(bar, textvariable=self._status_var, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        # Indeterminate progress bar sits between the status text and
        # the Stop button. Hidden by default; _run_cli starts it and
        # _on_proc_done stops it. Without this the only visual cue that
        # a long migrate/audit is doing work is the streaming Output
        # panel — a hung process and a quiet one are indistinguishable.
        self._busy_bar = self.ttk.Progressbar(
            bar, mode="indeterminate", length=120,
        )
        # _busy_bar is packed lazily by _set_busy(True) so the slot
        # doesn't take up status-bar width while idle.
        self._stop_btn = self.ttk.Button(
            bar, text="Stop", command=self._stop_running, state="disabled"
        )
        self._stop_btn.pack(side="right")
        self.ttk.Button(bar, text="Clear output", command=self._clear_output).pack(
            side="right", padx=(0, 6)
        )
        # Copy-to-clipboard mirrors the Logs tab's copy pattern. Lives
        # next to Clear so long audit / migrate output can be grabbed
        # without scrolling-and-selecting.
        self.ttk.Button(
            bar, text="Copy output", command=self._copy_output,
        ).pack(side="right", padx=(0, 6))
        # Hide / Show output toggle — sits at the left of the cluster so
        # muscle-memory positions of Copy/Clear/Stop don't shift when
        # cabinet owners reach for the familiar buttons.
        self._output_toggle_btn = self.ttk.Button(
            bar,
            text=("Hide output" if self._output_visible else "Show output"),
            command=self._toggle_output,
        )
        self._output_toggle_btn.pack(side="right", padx=(0, 6))

        # Global Apply / Verbose / Save Log checkboxes — shared across all
        # tabs. Packed side="right" AFTER the other right-side buttons so
        # they appear to the left of Hide/Copy/Clear/Stop in the status
        # bar. Pack order below (Save Log, then Verbose, then Apply) is
        # deliberate: each side="right" pack lands to the *left* of the
        # previous one, so packing last-to-first-visually gives the
        # requested left-to-right reading order of Apply, Verbose, Save Log.
        self._global_apply_var = self.tk.BooleanVar(value=False)
        self._global_verbose_var = self.tk.BooleanVar(value=False)
        self._global_savelog_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            bar, text="Save Log", variable=self._global_savelog_var,
        ).pack(side="right", padx=(6, 0))
        self.ttk.Checkbutton(
            bar, text="Verbose", variable=self._global_verbose_var,
        ).pack(side="right", padx=(6, 0))
        self.ttk.Checkbutton(
            bar, text="Apply", variable=self._global_apply_var,
        ).pack(side="right", padx=(6, 0))

        # Ctrl+1..9 jump to notebook tabs by 1-based index. Cabinet
        # owners on touchscreens benefit from a keyboard fallback, and
        # 15 tabs means a lot of clicking otherwise. bind_all so the
        # shortcut works from any focused widget.
        for n in range(1, 10):
            self._safe_bind_all(
                f"<Control-Key-{n}>",
                lambda _evt, idx=n - 1: self._select_tab(idx),
            )

        # UI-scale keyboard shortcuts.
        # Ctrl++ / Ctrl+= → zoom in; Ctrl+- → zoom out; Ctrl+0 → reset.
        # bind_all so the shortcut works from any focused widget.
        self._safe_bind_all(
            "<Control-equal>", lambda _e: self._ui_scale_step(+0.1),
        )
        self._safe_bind_all(
            "<Control-plus>", lambda _e: self._ui_scale_step(+0.1),
        )
        self._safe_bind_all(
            "<Control-KP_Add>", lambda _e: self._ui_scale_step(+0.1),
        )
        self._safe_bind_all(
            "<Control-minus>", lambda _e: self._ui_scale_step(-0.1),
        )
        self._safe_bind_all(
            "<Control-KP_Subtract>", lambda _e: self._ui_scale_step(-0.1),
        )
        self._safe_bind_all(
            "<Control-Key-0>", lambda _e: self._set_ui_scale(1.0),
        )

        # Ctrl+` → toggle the Output panel — standard "show/hide terminal"
        # shortcut (VS Code, JetBrains). The backtick key has different
        # keysym names across Tk builds (X11 ships `grave`; some Windows
        # Tk builds, notably the Tcl/Tk that ships with Python 3.8, only
        # know `quoteleft` or `asciigrave`). Try each so the binding
        # lands on whichever the running Tk recognises.
        for _seq in ("<Control-grave>", "<Control-quoteleft>",
                     "<Control-asciigrave>"):
            self._safe_bind_all(_seq, lambda _e: self._toggle_output())

        # Ctrl+Shift+F (Cmd+Shift+F on macOS) → toggle the system
        # quick-filter bar at the top of the window. Narrows every
        # system combobox across every tab. The shortcut is distinct
        # from Ctrl+F (output find bar) and Ctrl+1..9 (jump-to-tab) so
        # there's no muscle-memory collision.
        self._safe_bind_all(
            "<Control-F>", lambda _e: self._toggle_system_filter(),
        )
        self._safe_bind_all(
            "<Command-F>", lambda _e: self._toggle_system_filter(),
        )

        # Ctrl+F (Cmd+F on macOS) → toggle the Output panel's find bar.
        # Standard text-editor shortcut — same key opens it and Esc
        # closes it. The bind_all path means the user can be focused
        # anywhere (a tab's Entry, the Custom Command field, …) and
        # still pull the find bar up; the entry steals focus on open.
        self._safe_bind_all(
            "<Control-f>", lambda _e: self._find_open(),
        )
        self._safe_bind_all(
            "<Command-f>", lambda _e: self._find_open(),
        )

        # If the user previously hid the output pane, honour that
        # preference now (after the initial sash placement runs).
        if not self._output_visible:
            # Defer slightly so the placement helper has set the sash;
            # otherwise the captured "saved sash" would be the
            # uninitialised default.
            self.root.after(150, lambda: self._toggle_output(visible=False))

        # Right-click context menus on every Entry/Text widget — walked
        # post-construction so future tabs pick this up for free without
        # touching every call site.
        try:
            _walk_attach_context_menus(self.root, self.tk)
        except Exception:  # noqa: BLE001 — never block startup
            pass

        # Letter-key type-ahead on every dropdown — same walk-once
        # pattern as the context menus above. Cabinet systems can have
        # hundreds of games in a single Combobox; this lets a key press
        # jump straight to it instead of scrolling.
        try:
            _walk_attach_combobox_typeahead(self.root)
        except Exception:  # noqa: BLE001 — never block startup
            pass

        # If the previous session saved a last-active tab, restore it
        # now. Done at the end of layout so every tab builder has run
        # (touching a not-yet-built tab is fine — the notebook can
        # select an unrealised pane — but the user-visible result is
        # cleaner when we restore after all pages exist).
        if 0 <= self._restore_tab_idx < len(self._tab_base_names):
            try:
                self._nb.select(self._restore_tab_idx)
            except Exception:  # noqa: BLE001 - guard against teardown races
                pass

    def _safe_bind_all(self, sequence: str, callback) -> bool:
        """Best-effort ``root.bind_all`` that never crashes startup.

        Different Tk builds ship different keysym tables — most painfully,
        the Tcl/Tk bundled with Python 3.8 on Windows (which the frozen
        cabinet build still uses) doesn't recognise the X11 keysym
        ``grave`` for the backtick key, so a bare ``bind_all`` raises
        ``TclError`` and the whole GUI fails to construct. Keyboard
        shortcuts are conveniences, not load-bearing; swallow the error
        and let the rest of the layout finish. Returns True if the
        binding was accepted.
        """
        try:
            self.root.bind_all(sequence, callback)
            return True
        except self.tk.TclError:
            return False

    def _select_tab(self, idx: int) -> None:
        """Switch to tab at zero-based index, ignoring out-of-range."""
        if 0 <= idx < len(self._tab_base_names):
            self._nb.select(idx)

    def _copy_output(self) -> None:
        """Copy the current Output panel contents to the clipboard."""
        try:
            text = self._output.get("1.0", "end-1c")
        except self.tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        # update() forces the X11/Win32 clipboard owner to update before
        # the Tk window deletes the buffer on exit. Otherwise on Linux
        # the clipboard goes empty as soon as the GUI closes.
        self.root.update()
        self._set_status(f"Copied {len(text)} char(s) from output.")

    def _add_scrollable_tab(self, nb, builder, label: str) -> None:
        """Add a Notebook tab that scrolls vertically when content overflows.

        ``builder`` is one of the existing ``_build_*_tab`` callables —
        each takes a parent and returns a Frame. We wrap the result in
        a Canvas + Scrollbar so cabinet owners on 1024×768 / 1280×720
        screens can still reach options at the bottom of long tabs
        (Migrate, Curate, Tools have ~10+ rows of widgets).
        """
        container = self.ttk.Frame(nb)
        canvas = self.tk.Canvas(container, highlightthickness=0)
        vsb = self.ttk.Scrollbar(
            container, orient="vertical", command=canvas.yview,
        )
        canvas.configure(yscrollcommand=vsb.set)
        # Scrollbar always packed (not auto-hide) so users on the
        # smallest screens always know scrolling is available, even
        # before they realise content is clipped.
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Builder packs its widgets into `inner`. The builder still
        # creates its own Frame inside `inner` (existing pattern); we
        # pack that frame edge-to-edge.
        inner = self.ttk.Frame(canvas)
        builder_frame = builder(inner)
        builder_frame.pack(fill="both", expand=True)

        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_evt):
            # As widgets get added to the inner frame, expand the
            # canvas's scrollable region so the scrollbar reflects the
            # full content height.
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(evt):
            # Stretch the inner frame to match the canvas's width so
            # widgets `pack(fill="x")` actually fill the visible area
            # (without this they collapse to their natural width).
            canvas.itemconfigure(inner_id, width=evt.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse-wheel scrolling. `bind_all` is global, so we only
        # activate it while the cursor is over this canvas — Enter
        # binds, Leave unbinds. Otherwise Output-panel scrolling and
        # tab-content scrolling fight each other.
        def _scroll(evt):
            # Windows / macOS use evt.delta (±120 per notch); Linux
            # uses Button-4 / Button-5. Normalise to a signed step.
            if hasattr(evt, "delta") and evt.delta:
                step = -1 if evt.delta > 0 else 1
            elif getattr(evt, "num", None) == 4:
                step = -1
            elif getattr(evt, "num", None) == 5:
                step = 1
            else:
                return
            canvas.yview_scroll(step, "units")

        def _bind_wheel(_evt):
            canvas.bind_all("<MouseWheel>", _scroll)
            canvas.bind_all("<Button-4>", _scroll)
            canvas.bind_all("<Button-5>", _scroll)

        def _unbind_wheel(_evt):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        nb.add(container, text=label)
        self._tab_base_names.append(label)

    # ── Logs tab ──────────────────────────────────────────────────────────────

    def _build_logs_tab(self, parent):
        """Persistent timeline of every command run since GUI launch.

        The bottom Output panel only shows the *current* run; it scrolls
        away the moment the next command starts. This tab keeps every
        run's full output addressable by row, so cabinet owners can
        answer "what did that dry-run actually say?" without re-running.

        Layout: tree on the left (newest first, with status / time /
        command columns), read-only viewer on the right showing the
        full output of the selected row.
        """
        frame = self.ttk.Frame(parent, padding=4)

        intro = self.ttk.Label(
            frame,
            text=("Every command run since the GUI was launched, newest "
                  "first. Click a row to see its full output. "
                  "DRY-RUN rows are previews (no --apply was passed); "
                  "OK rows committed; FAIL rows exited non-zero. The "
                  "buffer is in-memory only — restarting the GUI "
                  "clears it. Manifest-based history (apply runs that "
                  "wrote a JSON manifest under ~/.spindoctor/) lives in "
                  "File → View logs & manifests…"),
            wraplength=900, justify="left", padding=(6, 4),
        )
        intro.pack(fill="x")

        paned = self.ttk.PanedWindow(frame, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # Left pane: tree of runs.
        tree_frame = self.ttk.Frame(paned)
        tree = self.ttk.Treeview(
            tree_frame, columns=("status", "time", "command"),
            show="headings", selectmode="browse",
        )
        tree.heading("status", text="Status")
        tree.heading("time", text="Started")
        tree.heading("command", text="Command")
        tree.column("status", width=90, stretch=False)
        tree.column("time", width=140, stretch=False)
        tree.column("command", width=420, stretch=True)
        tscroll = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=tree.yview,
        )
        tree.configure(yscrollcommand=tscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        tscroll.pack(side="right", fill="y")
        paned.add(tree_frame, weight=1)

        # Right pane: full output of the selected run.
        viewer_frame = self.ttk.Frame(paned)
        viewer = self._make_scrolled_text(
            viewer_frame, wrap="word", font="TkFixedFont",
        )
        viewer.configure(state="disabled")
        viewer.pack(fill="both", expand=True, padx=4, pady=4)
        paned.add(viewer_frame, weight=2)

        # Stash widgets so _refresh_logs_tab() can update them.
        self._logs_tree = tree
        self._logs_viewer = viewer
        # iid → record index, so selecting a row knows which record
        # to render. Indexes are recomputed every refresh.
        self._logs_iid_to_idx: dict[str, int] = {}

        def on_select(_evt) -> None:
            sel = tree.selection()
            if not sel:
                return
            idx = self._logs_iid_to_idx.get(sel[0])
            if idx is None or idx >= len(self._run_history):
                return
            record = self._run_history[idx]
            viewer.configure(state="normal")
            viewer.delete("1.0", "end")
            _dr = ("N/A" if record.dry_run is None
                   else ("Yes" if record.dry_run else "No"))
            header = (
                f"# Started: {record.started_at}\n"
                f"# Status:  {record.tag()}\n"
                f"# Dry-run: {_dr}\n"
                f"# Command: {record.argv_str}\n\n"
            )
            viewer.insert("end", header)
            viewer.insert("end", record.joined_output())
            viewer.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", on_select)

        btn_row = self.ttk.Frame(frame)
        btn_row.pack(fill="x", padx=4, pady=(0, 4))
        self.ttk.Button(
            btn_row, text="Refresh", command=self._refresh_logs_tab,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Copy selected output to clipboard",
            command=self._copy_selected_log,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Save selected output…",
            command=self._save_selected_log,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Clear in-memory log",
            command=self._clear_logs,
        ).pack(side="left", padx=6)
        # The in-memory log doesn't track manifest paths, but the
        # File → View logs & manifests… modal does — and it has the
        # "Undo this run" button per manifest. Surface a shortcut here
        # so users discovering the Logs tab for the first time don't
        # have to hunt through the menu for the undo workflow.
        self.ttk.Separator(btn_row, orient="vertical").pack(
            side="left", fill="y", padx=6,
        )
        self.ttk.Button(
            btn_row, text="Browse manifests / undo…",
            command=self._show_log_viewer,
        ).pack(side="left")

        # First paint.
        self._refresh_logs_tab()
        return frame

    def _refresh_logs_tab(self) -> None:
        """Re-render the Logs tab tree from ``self._run_history``.

        Called whenever a run starts or finishes so the tree updates
        live. Cheap to re-render: even at the 200-entry cap the whole
        operation is sub-millisecond.
        """
        tree = getattr(self, "_logs_tree", None)
        if tree is None:
            # Tab hasn't been built yet (first call from _run_cli
            # during construction). Will catch up on next refresh.
            return
        tree.delete(*tree.get_children())
        self._logs_iid_to_idx.clear()
        # Newest first — cabinet owners want "what did I just do?"
        # not "what did I do an hour ago?".
        for offset, record in enumerate(reversed(self._run_history)):
            real_idx = len(self._run_history) - 1 - offset
            iid = tree.insert(
                "", "end",
                values=(record.tag(), record.started_at, record.argv_str),
            )
            self._logs_iid_to_idx[iid] = real_idx

    def _copy_selected_log(self) -> None:
        tree = getattr(self, "_logs_tree", None)
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            self.messagebox.showinfo(
                "Pick a row first",
                "Select a row in the tree, then click Copy.",
            )
            return
        idx = self._logs_iid_to_idx.get(sel[0])
        if idx is None or idx >= len(self._run_history):
            return
        record = self._run_history[idx]
        text = (
            f"# {record.started_at}  [{record.tag()}]  "
            f"{record.argv_str}\n\n{record.joined_output()}"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status(
            f"Copied {len(text)} characters to clipboard."
        )

    def _save_selected_log(self) -> None:
        """Write the selected log entry to a .txt file chosen by the user."""
        tree = getattr(self, "_logs_tree", None)
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            self.messagebox.showinfo(
                "Pick a row first",
                "Select a row in the tree, then click Save.",
            )
            return
        idx = self._logs_iid_to_idx.get(sel[0])
        if idx is None or idx >= len(self._run_history):
            return
        record = self._run_history[idx]
        text = _format_run_log_text(record)
        from tkinter import filedialog
        default_name = _default_run_log_filename(record)
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=default_name,
            title="Save log output",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self._set_status(f"Saved log to {path}")
            export_record = _RunRecord(
                started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                argv_str=f"logs export → {Path(path).name}",
                dry_run=False,
            )
            export_record.append(f"$ logs export\n  saved: {path}\n")
            export_record.exit_code = 0
            self._run_history.append(export_record)
            self._refresh_logs_tab()
        except OSError as exc:
            self.messagebox.showerror("Save failed", str(exc))

    def _clear_logs(self) -> None:
        if self._proc is not None:
            self.messagebox.showinfo(
                "Wait for the current run to finish",
                "A command is still running — wait for it (or Stop) "
                "before clearing the log.",
            )
            return
        self._run_history.clear()
        self._refresh_logs_tab()
        viewer = getattr(self, "_logs_viewer", None)
        if viewer is not None:
            viewer.configure(state="normal")
            viewer.delete("1.0", "end")
            viewer.configure(state="disabled")

    # ── Menubar / About / cross-tab folder helpers ────────────────────────────

    def _build_menubar(self) -> None:
        # Tk's Menu sits in a `Menu` subwidget rather than a `ttk.Menu`
        # (which doesn't exist) — but a plain Tk Menu is fine here, the
        # rest of the UI doesn't visually clash with native menubars.
        menubar = self.tk.Menu(self.root)

        file_menu = self.tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Open config.json", command=self._open_config_file,
        )
        file_menu.add_command(
            label="Open SpinDoctor folder (~/.spindoctor)",
            command=self._open_spindoctor_folder,
        )
        file_menu.add_command(
            label="Open HyperSpin folder", command=self._open_hyperspin_folder,
        )
        file_menu.add_command(
            label="Open ROMs folder", command=self._open_roms_folder,
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="View logs & manifests…", command=self._show_log_viewer,
        )
        file_menu.add_command(
            label="Browse HyperSpin themes…",
            command=self._show_theme_browser,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        # ── View menu ────────────────────────────────────────────────────────
        # UI scale + output-pane visibility. Both also have keyboard
        # shortcuts; the menu exists for discoverability.
        view_menu = self.tk.Menu(menubar, tearoff=0)

        # Output pane visibility (checkbutton, two-way bound).
        self._output_visible_var = self.tk.BooleanVar(value=self._output_visible)
        view_menu.add_checkbutton(
            label="Show output pane",
            variable=self._output_visible_var,
            command=lambda: self._toggle_output(
                visible=self._output_visible_var.get(),
            ),
            accelerator="Ctrl+`",
        )
        view_menu.add_separator()

        # UI-scale presets (radio group). The radio var stores the scale
        # as a string ("1.0", "1.25", ...) so radiobuttons can compare it
        # by value reliably across platforms.
        self._ui_scale_var = self.tk.StringVar(value=f"{self._ui_scale:g}")
        scale_menu = self.tk.Menu(view_menu, tearoff=0)
        for preset in UI_SCALE_PRESETS:
            scale_menu.add_radiobutton(
                label=f"{preset:g}\u00d7",
                value=f"{preset:g}",
                variable=self._ui_scale_var,
                command=lambda p=preset: self._set_ui_scale(p),
            )
        view_menu.add_cascade(label="UI scale", menu=scale_menu)
        view_menu.add_command(
            label="Zoom in", accelerator="Ctrl+=",
            command=lambda: self._ui_scale_step(+0.1),
        )
        view_menu.add_command(
            label="Zoom out", accelerator="Ctrl+-",
            command=lambda: self._ui_scale_step(-0.1),
        )
        view_menu.add_command(
            label="Reset zoom", accelerator="Ctrl+0",
            command=lambda: self._set_ui_scale(1.0),
        )
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = self.tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About SpinDoctor", command=self._show_about)
        help_menu.add_command(
            label="Keyboard shortcuts", command=self._show_keyboard_shortcuts,
        )
        help_menu.add_command(
            label="Check for updates", command=self._manual_update_check,
        )
        help_menu.add_command(
            label="First-run setup…", command=self._show_first_run_wizard,
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.configure(menu=menubar)

    def _show_about(self) -> None:
        # Plain modal — Tkinter's `Toplevel` is enough; we don't need
        # platform-native About panels (and can't easily get them through
        # tkinter without trading portability).
        win = self.tk.Toplevel(self.root)
        win.title(f"About {__app_name__}")
        win.transient(self.root)
        win.resizable(False, False)
        win.bind("<Escape>", lambda _e: win.destroy())

        body = self.ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)

        # Show the app icon next to the title if the PNG icon loaded at
        # startup. The .ico path used on Windows won't help here — Tk's
        # PhotoImage doesn't read .ico — but the PNG fallback does.
        icon = getattr(self, "_icon_photo", None)
        header = self.ttk.Frame(body)
        header.pack(anchor="w", fill="x")
        if icon is not None:
            try:
                self.ttk.Label(header, image=icon).pack(side="left", padx=(0, 10))
            except self.tk.TclError:
                pass
        self.ttk.Label(
            header, text=f"{__app_name__}",
            font=("TkDefaultFont", 14, "bold"),
        ).pack(side="left", anchor="w")
        self.ttk.Label(body, text=f"version {__version__}").pack(
            anchor="w", pady=(0, 8),
        )
        self.ttk.Label(
            body,
            text=("A librarian for HyperSpin + RocketLauncher arcade "
                  "cabinets — full CLI plus this Tkinter GUI launcher.\n\n"
                  "SpinDoctor is a librarian, not an installer: it does "
                  "not install HyperSpin, RocketLauncher, or any "
                  "emulator, and it does not download ROMs or BIOS."),
            wraplength=420, justify="left",
        ).pack(anchor="w")

        link_row = self.ttk.Frame(body)
        link_row.pack(anchor="w", pady=(12, 4))
        self.ttk.Button(
            link_row, text="Open project on GitHub",
            command=lambda: self._open_url(
                "https://github.com/phillram/spindoctor",
            ),
        ).pack(side="left")
        self.ttk.Button(
            link_row, text="Latest release",
            command=lambda: self._open_url(
                "https://github.com/phillram/spindoctor/releases/latest",
            ),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            link_row, text="CHANGELOG",
            command=lambda: self._open_url(
                "https://github.com/phillram/spindoctor/blob/main/CHANGELOG.md",
            ),
        ).pack(side="left", padx=6)

        self.ttk.Button(body, text="Close", command=win.destroy).pack(
            anchor="e", pady=(12, 0),
        )

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def _show_keyboard_shortcuts(self) -> None:
        win = self.tk.Toplevel(self.root)
        win.title("Keyboard shortcuts")
        win.transient(self.root)
        win.bind("<Escape>", lambda _e: win.destroy())
        self._fit_geometry(win, 520, 460)

        body = self.ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)

        self.ttk.Label(
            body, text="Keyboard shortcuts",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        shortcuts = [
            ("Ctrl+1 … Ctrl+9", "Jump to notebook tab 1–9"),
            ("Ctrl+=  /  Ctrl++", "Zoom in (larger UI)"),
            ("Ctrl+-", "Zoom out (smaller UI)"),
            ("Ctrl+0", "Reset zoom to 1.0×"),
            ("Ctrl+`", "Show or hide the Output panel"),
            ("Ctrl+F", "Open the Output find bar"),
            ("Ctrl+Shift+F", "Toggle the system quick-filter bar"),
            ("Esc", "Close any open dialog"),
        ]

        grid = self.ttk.Frame(body)
        grid.pack(fill="both", expand=True, pady=(4, 0))
        for row, (keys, desc) in enumerate(shortcuts):
            self.ttk.Label(
                grid, text=keys, font=("TkFixedFont", 10, "bold"),
            ).grid(row=row, column=0, sticky="w", padx=(0, 18), pady=2)
            self.ttk.Label(grid, text=desc).grid(
                row=row, column=1, sticky="w", pady=2,
            )

        self.ttk.Button(body, text="Close", command=win.destroy).pack(
            anchor="e", pady=(12, 0),
        )

    # ── Update check ──────────────────────────────────────────────────────────

    def _start_update_check(self) -> None:
        """Kick off the GitHub release-tag check on a background thread.

        Runs at GUI launch — silently no-ops on opt-out via the
        ``SPINDOCTOR_NO_UPDATE_CHECK`` env var, on offline machines, on
        GitHub outages, and on any other failure. The thread is
        daemonic so it won't keep the process alive after the user
        closes the window.
        """
        # Imported lazily so the module's import cost stays out of the
        # GUI launch critical path on machines that opt out via env.
        from . import update_check

        def worker() -> None:
            try:
                result = update_check.check_for_update(__version__)
            except update_check.UpdateCheckDisabled:
                return
            except Exception:  # noqa: BLE001 — never let this kill the UI
                return
            if result is not None:
                try:
                    # Hop back to the Tk main loop before touching widgets.
                    self.root.after(0, self._on_update_check_done, result)
                except Exception:  # noqa: BLE001 — root may be destroyed (test teardown)
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, result) -> None:
        if result.newer_available:
            self._set_status(
                f"Update available: {result.latest} "
                f"(running {result.current}). Help → Check for updates."
            )
            self._append_output(
                f"\n[update check] {__app_name__} {result.latest} is "
                f"available. Current: {__version__}.\n"
                f"  {result.release_url or 'https://github.com/phillram/spindoctor/releases'}\n"
            )
            # Surface a one-click Download button in the status bar so
            # users don't have to dig through the Help menu. Removed
            # automatically the first time `_set_status` runs without
            # an update message — see _clear_update_download_button.
            self._show_update_download_button(
                result.release_url
                or "https://github.com/phillram/spindoctor/releases/latest"
            )
        # When the user is up to date, stay quiet — no point cluttering
        # the output panel with an "all good" line on every launch.

    def _show_update_download_button(self, url: str) -> None:
        # Lazily-created — only built when an update is actually
        # available, so no widget overhead on up-to-date launches.
        existing = getattr(self, "_update_download_btn", None)
        if existing is not None:
            try:
                existing.destroy()
            except Exception:  # noqa: BLE001 - widget race during teardown
                pass
        btn = self.ttk.Button(
            self._status_bar_frame
            if hasattr(self, "_status_bar_frame")
            else self._stop_btn.master,
            text="Download…",
            command=lambda u=url: self._open_url(u),
        )
        # Sit immediately to the left of Stop so it's the first thing
        # the user's eye lands on when checking the bottom bar.
        btn.pack(side="right", padx=(0, 6), before=self._stop_btn)
        self._update_download_btn = btn

    def _manual_update_check(self) -> None:
        """Help → Check for updates: background variant with feedback.

        The launch check runs silently on success, but a manual
        invocation should always tell the user *something* — otherwise
        clicking the menu entry feels broken when the user is up to
        date. Runs the network call on a worker thread so a slow or
        unreachable GitHub doesn't freeze the Tk main loop (a 5 s
        urllib timeout is plenty of time for the window to feel hung).
        """
        from . import update_check

        self._set_status("Checking for updates…")

        def worker() -> None:
            try:
                result = update_check.check_for_update(__version__)
            except update_check.UpdateCheckDisabled as exc:
                # Capture into the closure so the main-thread handler
                # can render the messagebox without re-raising.
                self.root.after(
                    0, self._on_manual_update_disabled, str(exc),
                )
                return
            except Exception as exc:  # noqa: BLE001 — surface in UI
                self.root.after(
                    0, self._on_manual_update_failed, str(exc),
                )
                return
            self.root.after(0, self._on_manual_update_result, result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_manual_update_disabled(self, message: str) -> None:
        self._set_status("Ready.")
        self.messagebox.showinfo("Update check disabled", message)

    def _on_manual_update_failed(self, _message: str) -> None:
        self._set_status("Ready.")
        self.messagebox.showinfo(
            "Update check failed",
            "Could not reach GitHub. Check your connection and try "
            "again, or visit "
            "https://github.com/phillram/spindoctor/releases/latest "
            "manually.",
        )

    def _on_manual_update_result(self, result) -> None:
        self._set_status("Ready.")
        if result is None:
            self.messagebox.showinfo(
                "Update check failed",
                "Could not reach GitHub. Check your connection and try "
                "again, or visit "
                "https://github.com/phillram/spindoctor/releases/latest "
                "manually.",
            )
            return
        if result.newer_available:
            if self.messagebox.askyesno(
                "Update available",
                f"{__app_name__} {result.latest} is available.\n"
                f"You're running {result.current}.\n\n"
                "Open the release page in your browser?",
            ):
                self._open_url(
                    result.release_url
                    or "https://github.com/phillram/spindoctor/releases/latest",
                )
        else:
            # "You're on the latest version" doesn't need a click-through
            # — the status bar conveys it just as well.
            self._flash_status(
                f"{__app_name__} {result.current} is the latest release."
            )

    def _open_url(self, url: str) -> None:
        # webbrowser.open hands off to the OS default browser without
        # blocking the Tk main loop, so the GUI stays responsive while
        # the browser is starting up.
        import webbrowser
        webbrowser.open(url)

    def _open_path(self, path: Path, *, missing_label: str) -> None:
        """Open *path* in the OS's file explorer / Finder / xdg-open.

        Falls back to a warning dialog when the path doesn't exist —
        better than asking the OS to open `D:\\Arcade` on a machine
        where that drive isn't mounted, which silently no-ops on
        Windows and pops a Finder error on macOS.
        """
        if not path.exists():
            self.messagebox.showwarning(
                "Path not found",
                f"{missing_label} doesn't exist on disk:\n  {path}\n\n"
                "Set the corresponding path in the Setup tab first.",
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # noqa: S606 — user-initiated open
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])  # noqa: S603,S607
            else:
                subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
        except OSError as exc:
            self.messagebox.showerror(
                "Could not open folder",
                f"OS refused to open {path}:\n{exc}",
            )

    def _open_config_file(self) -> None:
        self._open_path(CONFIG_FILE, missing_label="config.json")

    def _open_spindoctor_folder(self) -> None:
        self._open_path(CONFIG_DIR, missing_label="~/.spindoctor")

    def _open_hyperspin_folder(self) -> None:
        cfg = load_config()
        if not cfg.hyperspin_dir:
            self.messagebox.showwarning(
                "Not configured",
                "hyperspin_dir is unset. Fill it in on the Setup tab.",
            )
            return
        self._open_path(Path(cfg.hyperspin_dir), missing_label="hyperspin_dir")

    def _open_roms_folder(self) -> None:
        cfg = load_config()
        if not cfg.roms_dir:
            self.messagebox.showwarning(
                "Not configured",
                "roms_dir is unset. Fill it in on the Setup tab.",
            )
            return
        self._open_path(Path(cfg.roms_dir), missing_label="roms_dir")

    def _open_system_media_folder(self, system: str) -> None:
        """Open `<hyperspin>/Media/<system>/` so the user can eyeball art.

        Used by the Audit tab so a cabinet owner spotting "missing
        wheel" or "wrong title" output can jump straight to the
        offending folder without copy-pasting paths into Explorer.
        """
        cfg = load_config()
        if not cfg.hyperspin_dir:
            self.messagebox.showwarning(
                "hyperspin_dir not set",
                "Fill in the HyperSpin directory on the Setup tab "
                "before browsing media.",
            )
            return
        media_dir = Path(cfg.hyperspin_dir) / "Media" / system
        self._open_path(media_dir, missing_label=f"Media/{system}")

    # ── Log / manifest viewer ─────────────────────────────────────────────────

    # Where SpinDoctor's apply-mode commands write their per-run
    # manifests. Tuple is (label, dirname under ~/.spindoctor/) — order
    # matters: newest-style categories near the top so they win the
    # default selection. The viewer scans whichever of these exist on
    # disk; users without `migrate` history just see fewer rows.
    # (label, dirname, depth) — depth=0 means "files directly inside
    # the dir"; depth=1 means "manifest.json one level deep" which is
    # how theme-apply organises a run-folder per swap. Adding categories
    # at unusual depths is rare enough that we keep the populator
    # simple instead of accepting a callable.
    _LOG_CATEGORIES: tuple[tuple[str, str, int], ...] = (
        ("Migrations",     "migrations",     0),
        ("Curation",       "curation",       0),
        ("Edits",          "edits",          0),
        ("Renames",        "renames",        0),
        ("Media imports",  "media_imports",  0),
        ("Theme swaps",    "themes",         1),
        ("Misplaced ROMs", "misplaced",      0),
    )

    # Per-category undo recipes for the "Undo this run" button on the
    # Logs & Manifests viewer. Each entry maps a manifest dir name to a
    # callable that builds the argv (without the leading `spindoctor`)
    # for the matching `--undo --apply` invocation.
    #
    # Some commands (curate, media-scan) only undo the *most recent*
    # run and ignore the path argument — those still appear here, but
    # the Undo Center warns the user when they pick a non-most-recent
    # manifest of that category to avoid the surprise of a different
    # run getting reversed.
    #
    # `find-misplaced` writes its manifests *into the roms_dir*, not
    # under ~/.spindoctor/, so it's not in the viewer's tree at all and
    # therefore not in this map.
    _UNDO_RECIPES: dict = {
        "migrations": {
            "argv": lambda path: ["migrate", "--undo", str(path)],
            "uses_path": True,
        },
        "curation": {
            "argv": lambda _path: ["curate", "--undo"],
            "uses_path": False,
        },
        "edits": {
            "argv": lambda path: ["batch-edit", "--undo", str(path)],
            "uses_path": True,
        },
        "renames": {
            "argv": lambda path: ["rename", "--undo", str(path)],
            "uses_path": True,
        },
        "media_imports": {
            "argv": lambda _path: ["media-scan", "--undo"],
            "uses_path": False,
        },
        "themes": {
            "argv": lambda path: ["theme-apply", "--undo", str(path)],
            "uses_path": True,
        },
    }

    def _show_log_viewer(self) -> None:
        """Open a Toplevel window listing recent manifests on the left
        and showing the selected file's contents on the right.

        SpinDoctor's destructive commands write JSON / NDJSON manifests
        under ~/.spindoctor/<category>/ for `--undo` to consume. They
        also serve as an audit trail — but until now the only way to
        browse them was a file explorer + a text editor. This window
        is a quick read-only viewer for that pile.
        """
        win = self.tk.Toplevel(self.root)
        win.title(f"{__app_name__} — Logs & Manifests")
        self._fit_geometry(win, 960, 600)
        win.transient(self.root)

        # Top description so first-time users understand what the panel
        # is showing — these aren't application logs (SpinDoctor doesn't
        # have a logfile), they're per-run manifests.
        self.ttk.Label(
            win,
            text=("Per-run manifests written by SpinDoctor's apply-mode "
                  "commands (curate, migrate, batch-edit, rename, "
                  "media-scan, find-misplaced --apply). Each one is the "
                  "file `--undo` reads to reverse a run. Read-only — "
                  "use the file menu's 'Open ~/.spindoctor' to edit."),
            wraplength=920, justify="left", padding=(10, 6),
        ).pack(fill="x")

        paned = self.ttk.PanedWindow(win, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        # ── Left pane: tree ──────────────────────────────────────────────────
        tree_frame = self.ttk.Frame(paned)
        tree = self.ttk.Treeview(
            tree_frame, columns=("modified", "size"), show="tree headings",
            selectmode="browse",
        )
        tree.heading("#0", text="File")
        tree.heading("modified", text="Modified")
        tree.heading("size", text="Size")
        tree.column("#0", width=320, stretch=True)
        tree.column("modified", width=160, stretch=False, anchor="w")
        tree.column("size", width=80, stretch=False, anchor="e")
        scrollbar = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=tree.yview,
        )
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        paned.add(tree_frame, weight=1)

        # ── Right pane: viewer ───────────────────────────────────────────────
        viewer_frame = self.ttk.Frame(paned)
        # TkFixedFont resolves to the platform monospace default and
        # honours the user's ui_scale setting (Consolas/Menlo hard-codes
        # bypass the scale knob — papercut from earlier releases).
        viewer = self._make_scrolled_text(
            viewer_frame, wrap="none", font="TkFixedFont",
        )
        viewer.configure(state="disabled")
        viewer.pack(fill="both", expand=True, padx=4, pady=4)
        paned.add(viewer_frame, weight=2)

        # Path → file text. Cached so re-clicking a row doesn't re-read
        # disk; manifests don't change after they're written.
        loaded: dict[str, str] = {}
        # Tree iid → (manifest path, category dirname, is_most_recent).
        # is_most_recent matters for the Undo button's safety check:
        # `curate --undo` and `media-scan --undo` ignore the path arg
        # and reverse only the newest run, so we warn if the user
        # picks an older manifest from those categories.
        item_meta: dict[str, tuple] = {}

        def populate() -> None:
            tree.delete(*tree.get_children())
            item_meta.clear()
            any_found = False
            for label, dirname, depth in self._LOG_CATEGORIES:
                cat_dir = CONFIG_DIR / dirname
                if not cat_dir.exists():
                    continue
                if depth == 0:
                    candidates = (p for p in cat_dir.iterdir()
                                  if p.is_file())
                else:
                    # depth=1: subdir-per-run with a manifest.json
                    # inside (theme-apply layout). The manifest.json
                    # is what the Undo command consumes, so that's
                    # what the user sees in the tree.
                    candidates = (sub / "manifest.json"
                                  for sub in cat_dir.iterdir()
                                  if sub.is_dir()
                                  and (sub / "manifest.json").exists())
                files = sorted(
                    candidates,
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not files:
                    continue
                any_found = True
                cat_iid = tree.insert(
                    "", "end", text=f"{label}  ({len(files)})",
                    values=("", ""), open=True,
                )
                for i, f in enumerate(files):
                    stat = f.stat()
                    iid = tree.insert(
                        cat_iid, "end", text=f.name,
                        values=(
                            self._format_mtime(stat.st_mtime),
                            self._format_bytes(stat.st_size),
                        ),
                    )
                    item_meta[iid] = (f, dirname, i == 0)
            if not any_found:
                tree.insert(
                    "", "end",
                    text="No manifests yet — run something with --apply.",
                    values=("", ""),
                )

        def on_select(_evt) -> None:
            sel = tree.selection()
            if not sel:
                return
            meta = item_meta.get(sel[0])
            if meta is None:
                return
            path, _dirname, _is_recent = meta
            key = str(path)
            if key not in loaded:
                try:
                    loaded[key] = path.read_text(
                        encoding="utf-8", errors="replace",
                    )
                except OSError as exc:
                    loaded[key] = f"[could not read {path}]\n{exc}"
            viewer.configure(state="normal")
            viewer.delete("1.0", "end")
            # Header line shows the absolute path so the viewer pane is
            # self-describing if the user takes a screenshot.
            viewer.insert("end", f"# {path}\n\n")
            viewer.insert("end", loaded[key])
            viewer.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", on_select)

        # ── Bottom button row ────────────────────────────────────────────────
        btn_row = self.ttk.Frame(win)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        self.ttk.Button(
            btn_row, text="Refresh", command=populate,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Undo this run",
            command=lambda: self._undo_selected_manifest(tree, item_meta),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Show diff",
            command=lambda: self._show_manifest_diff(tree, item_meta),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Revert just <SYSTEM>…",
            command=lambda: self._revert_system_from_manifest(tree, item_meta),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Open in file explorer",
            command=lambda: self._open_selected_manifest_in_explorer(
                tree, item_meta,
            ),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Open ~/.spindoctor",
            command=self._open_spindoctor_folder,
        ).pack(side="left", padx=6)
        self.ttk.Button(btn_row, text="Close", command=win.destroy).pack(
            side="right",
        )

        populate()

    def _undo_selected_manifest(self, tree, item_meta: dict) -> None:
        """Run the matching `--undo` command for the selected manifest.

        Looks up the recipe in ``_UNDO_RECIPES`` keyed by the manifest's
        category dirname. For commands that always reverse the most-
        recent run (curate, media-scan), warns the user if they picked
        an older manifest — that's the most surprising failure mode.
        """
        sel = tree.selection()
        if not sel:
            self.messagebox.showinfo(
                "Nothing selected",
                "Pick a manifest from the tree first.",
            )
            return
        meta = item_meta.get(sel[0])
        if meta is None:
            self.messagebox.showinfo(
                "Pick a file",
                "Selected row is a category folder. Pick a specific "
                "manifest underneath it.",
            )
            return
        path, dirname, is_most_recent = meta
        recipe = self._UNDO_RECIPES.get(dirname)
        if recipe is None:
            self.messagebox.showwarning(
                "No undo for this category",
                f"Undo isn't wired up for the '{dirname}' manifest "
                "type. Open the file in your editor and reverse the "
                "changes manually, or see Help → About for where to "
                "find the documentation.",
            )
            return
        if not recipe["uses_path"] and not is_most_recent:
            # `curate --undo` / `media-scan --undo` ignore which file
            # you picked and always reverse the most recent run. Make
            # that explicit so users don't think they're undoing the
            # row they clicked on.
            if not self.messagebox.askyesno(
                "This will undo the *most recent* run",
                f"`{recipe['argv'](path)[0]} --undo` always reverses "
                "the most recent run, not the manifest you selected. "
                "Continue?",
            ):
                return
        if not self.messagebox.askyesno(
            "Confirm undo",
            f"Run the matching `--undo` command for {path.name}?\n\n"
            "Output streams to the panel below the tree window. "
            "Most undos are themselves reversible by re-running the "
            "original apply, but back up first if you're unsure.",
        ):
            return
        argv = recipe["argv"](path)
        if self._global_apply_var.get():
            argv = argv + ["--apply"]
        self._run_cli("spindoctor", argv)

    def _open_selected_manifest_in_explorer(
        self, tree, item_meta: dict,
    ) -> None:
        sel = tree.selection()
        if not sel:
            return
        meta = item_meta.get(sel[0])
        if meta is None:
            return
        path, _dirname, _is_recent = meta
        if path is None or not path.exists():
            return
        # Open the *parent* — the file selected handler already showed
        # the contents, so what's useful here is "show me where this
        # lives so I can poke around its siblings".
        self._open_path(path.parent, missing_label=str(path.parent))

    def _show_manifest_diff(self, tree, item_meta: dict) -> None:
        """Render the selected manifest's recorded changes as a readable
        before/after table instead of raw JSON.

        Handles theme-apply manifests (source → target swaps) and
        migration manifests (component → from/to moves). Other manifest
        types fall back to a nicely formatted JSON view.
        """
        import json as _json

        sel = tree.selection()
        if not sel:
            self.messagebox.showinfo(
                "Pick a row first",
                "Select a manifest from the tree, then click Show diff.",
            )
            return
        meta = item_meta.get(sel[0])
        if meta is None:
            self.messagebox.showinfo(
                "Pick a file",
                "Selected row is a category folder. Pick a specific "
                "manifest underneath it.",
            )
            return
        path, dirname, _is_recent = meta
        try:
            data = _json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            from ._errors import humanize_oserror
            self.messagebox.showerror(
                "Could not read manifest",
                humanize_oserror(exc, action=f"read {path.name}")
                if isinstance(exc, OSError) else
                f"The manifest is not valid JSON:\n  {path}\n\n{exc}",
            )
            return

        win = self.tk.Toplevel(self.root)
        win.title(f"Diff — {path.name}")
        self._fit_geometry(win, 960, 540)
        win.transient(self.root)

        self.ttk.Label(
            win,
            text=f"Changes recorded in {path.name}",
            font=("TkDefaultFont", 10, "bold"),
            padding=(10, 6),
        ).pack(anchor="w")
        self.ttk.Label(
            win,
            text=f"Timestamp: {data.get('timestamp', 'unknown')}",
            foreground=_FG_DIM, padding=(10, 0),
        ).pack(anchor="w")

        tree_frame = self.ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        if dirname == "themes" and "swaps" in data:
            cols = ("scope", "bucket", "source", "target")
            diff_tree = self.ttk.Treeview(
                tree_frame, columns=cols, show="headings",
            )
            diff_tree.heading("scope", text="Scope")
            diff_tree.heading("bucket", text="Bucket")
            diff_tree.heading("source", text="Source file")
            diff_tree.heading("target", text="Target path (overwritten)")
            diff_tree.column("scope", width=120, stretch=False)
            diff_tree.column("bucket", width=110, stretch=False)
            diff_tree.column("source", width=200, stretch=False)
            diff_tree.column("target", width=460, stretch=True)
            for swap in data["swaps"]:
                diff_tree.insert("", "end", values=(
                    swap.get("target_scope", ""),
                    swap.get("target_bucket", ""),
                    Path(swap.get("source", "")).name,
                    swap.get("target", ""),
                ))
            n = len(data["swaps"])
            self.ttk.Label(
                win, text=f"{n} swap(s) recorded.",
                padding=(10, 4),
            ).pack(anchor="w")

        elif dirname == "migrations" and "moves" in data:
            cols = ("component", "from_path", "to_path")
            diff_tree = self.ttk.Treeview(
                tree_frame, columns=cols, show="headings",
            )
            diff_tree.heading("component", text="Component")
            diff_tree.heading("from_path", text="From")
            diff_tree.heading("to_path", text="To")
            diff_tree.column("component", width=120, stretch=False)
            diff_tree.column("from_path", width=380, stretch=True)
            diff_tree.column("to_path", width=380, stretch=True)
            for move in data["moves"]:
                diff_tree.insert("", "end", values=(
                    move.get("component", ""),
                    move.get("src", ""),
                    move.get("dest", ""),
                ))

        else:
            # Generic: render keys as rows.
            cols = ("key", "value")
            diff_tree = self.ttk.Treeview(
                tree_frame, columns=cols, show="headings",
            )
            diff_tree.heading("key", text="Field")
            diff_tree.heading("value", text="Value")
            diff_tree.column("key", width=180, stretch=False)
            diff_tree.column("value", width=720, stretch=True)
            for k, v in data.items():
                if isinstance(v, (list, dict)):
                    display = _json.dumps(v, indent=2)[:200]
                else:
                    display = str(v)
                diff_tree.insert("", "end", values=(k, display))

        vsb = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=diff_tree.yview,
        )
        diff_tree.configure(yscrollcommand=vsb.set)
        diff_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.ttk.Button(win, text="Close", command=win.destroy).pack(
            anchor="e", padx=8, pady=(0, 8),
        )

    def _revert_system_from_manifest(self, tree, item_meta: dict) -> None:
        """Open a dialog to pick one system from a theme-apply manifest
        and revert only that system's swaps, leaving all other wheels
        untouched.

        Only available for Theme swaps manifests — other manifest types
        don't have per-system scope so the button shows an info message
        for those.
        """
        sel = tree.selection()
        if not sel:
            self.messagebox.showinfo(
                "Pick a row first",
                "Select a theme-apply manifest from the tree first.",
            )
            return
        meta = item_meta.get(sel[0])
        if meta is None:
            self.messagebox.showinfo(
                "Pick a file",
                "Selected row is a category folder. Pick a specific "
                "manifest underneath it.",
            )
            return
        path, dirname, _is_recent = meta
        if dirname != "themes":
            self.messagebox.showinfo(
                "Theme manifests only",
                "Per-system revert is only available for Theme swaps "
                "manifests. Select a row under the 'Theme swaps' category.",
            )
            return

        try:
            from . import themes as themes_mod
            systems = themes_mod.list_systems_in_manifest(path)
        except Exception as exc:  # noqa: BLE001 — surface in UI, not stderr
            self.messagebox.showerror(
                "Could not read manifest",
                f"{type(exc).__name__}: {exc}",
            )
            return
        if not systems:
            self.messagebox.showwarning(
                "No systems found",
                f"Could not read system names from {path.name}.",
            )
            return

        # Small dialog: label + listbox + OK/Cancel.
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Revert just one system")
        self._fit_geometry(dialog, 380, 260)
        dialog.transient(self.root)
        dialog.resizable(False, False)

        self.ttk.Label(
            dialog,
            text=(f"Pick the system to revert from\n{path.name}.\n\n"
                  "Only that system's files will be restored from the\n"
                  "backup — all other wheels are left as-is."),
            wraplength=350, justify="left", padding=(12, 8),
        ).pack(fill="x")

        lb_frame = self.ttk.Frame(dialog)
        lb_frame.pack(fill="both", expand=True, padx=12)
        lb = self.tk.Listbox(lb_frame, selectmode="single", height=6)
        for s in systems:
            lb.insert("end", s)
        lb.selection_set(0)
        lb_sb = self.ttk.Scrollbar(lb_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=lb_sb.set)
        lb.pack(side="left", fill="both", expand=True)
        lb_sb.pack(side="right", fill="y")

        chosen: list = []

        def _ok() -> None:
            sel_idx = lb.curselection()
            if not sel_idx:
                return
            chosen.append(lb.get(sel_idx[0]))
            dialog.destroy()

        btn_row = self.ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=12, pady=(4, 10))
        self.ttk.Button(btn_row, text="Revert", command=_ok).pack(side="left")
        self.ttk.Button(
            btn_row, text="Cancel", command=dialog.destroy,
        ).pack(side="left", padx=6)

        dialog.wait_window()

        if not chosen:
            return
        system = chosen[0]
        if not self.messagebox.askyesno(
            "Confirm per-system revert",
            f"Revert '{system}' files from {path.name}?\n\n"
            "Only that system's overwritten files will be restored. "
            "Other wheels are untouched.",
        ):
            return
        self._run_cli(
            "spindoctor",
            ["theme-apply", "--undo", str(path), "--revert-system", system],
        )

    @staticmethod
    def _format_mtime(ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _format_bytes(n: int) -> str:
        return _format_bytes_util(n)

    # ── Theme browser ─────────────────────────────────────────────────────────

    def _show_theme_browser(self) -> None:
        """Open a Toplevel window inventorying HyperSpin frontend art.

        Shells out to ``spindoctor.themes.scan_frontend_art`` so the
        scanner logic stays testable without Tk. Each row is a
        :class:`ThemeAsset`; double-clicking (or Enter) opens the
        file in the OS image viewer so users can eyeball whether
        a "specialA1.png" really is the Xbox glyph they want to swap.
        """
        win = self.tk.Toplevel(self.root)
        win.title(f"{__app_name__} — HyperSpin theme browser")
        self._fit_geometry(win, 1080, 600)
        win.transient(self.root)

        self.ttk.Label(
            win,
            text=("Inventory of HyperSpin frontend overlay art — the "
                  "controller-hint glyphs at the bottom of the cabinet UI. "
                  "Walks <hyperspin>/Media/Frontend/Images/ and every "
                  "system's Special A / Special B folders. Double-click "
                  "(or press Enter) to open the file in your OS image "
                  "viewer. Use Filter to narrow the list — type 'xbox', "
                  "'arcade', etc."),
            wraplength=1060, justify="left", padding=(10, 6),
        ).pack(fill="x")

        # ── Filter row ────────────────────────────────────────────────
        filter_row = self.ttk.Frame(win)
        filter_row.pack(fill="x", padx=8, pady=2)
        self.ttk.Label(filter_row, text="Filter").pack(side="left")
        filter_var = self.tk.StringVar()
        filter_entry = self.ttk.Entry(
            filter_row, textvariable=filter_var,
        )
        filter_entry.pack(side="left", fill="x", expand=True, padx=6)
        count_var = self.tk.StringVar(value="Loading…")
        self.ttk.Label(filter_row, textvariable=count_var, width=24).pack(
            side="right",
        )

        # ── Tree ──────────────────────────────────────────────────────
        tree_frame = self.ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
        tree = self.ttk.Treeview(
            tree_frame,
            columns=("scope", "bucket", "kind", "size", "modified"),
            show="tree headings", selectmode="browse",
        )
        tree.heading("#0", text="File")
        tree.heading("scope", text="Scope")
        tree.heading("bucket", text="Bucket")
        tree.heading("kind", text="Kind")
        tree.heading("size", text="Size")
        tree.heading("modified", text="Modified")
        tree.column("#0", width=320, stretch=True)
        tree.column("scope", width=140, stretch=False)
        tree.column("bucket", width=140, stretch=False)
        tree.column("kind", width=60, stretch=False, anchor="w")
        tree.column("size", width=80, stretch=False, anchor="e")
        tree.column("modified", width=140, stretch=False, anchor="w")
        scrollbar = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=tree.yview,
        )
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # iid → ThemeAsset, used by the open-in-viewer / open-folder
        # handlers. Tree text is the file *name* not the full path so
        # the column width stays manageable; we look the path back up
        # from this dict on selection.
        item_assets: dict = {}
        # All assets, unfiltered. Re-rendered when the filter box
        # changes — no re-scan needed since this is a pure in-memory
        # filter pass.
        all_assets: list = []

        def render(filtered) -> None:
            tree.delete(*tree.get_children())
            item_assets.clear()
            for a in filtered:
                iid = tree.insert(
                    "", "end", text=a.path.name,
                    values=(
                        a.scope, a.bucket, a.kind,
                        self._format_bytes(a.size_bytes),
                        a.modified.strftime("%Y-%m-%d %H:%M"),
                    ),
                )
                item_assets[iid] = a
            count_var.set(
                f"{len(filtered)} of {len(all_assets)} file(s)"
            )

        def apply_filter(_evt=None) -> None:
            from . import themes as themes_mod
            kw = filter_var.get().strip()
            filtered = themes_mod.filter_assets(
                all_assets, keyword=kw or None,
            )
            render(filtered)

        filter_entry.bind("<KeyRelease>", apply_filter)

        def open_selected(_evt=None) -> None:
            sel = tree.selection()
            if not sel:
                return
            asset = item_assets.get(sel[0])
            if asset is None:
                return
            # Re-uses the same cross-platform opener as the File menu
            # shortcuts; the OS picks the right image viewer.
            self._open_path(asset.path, missing_label=str(asset.path))

        def open_folder() -> None:
            sel = tree.selection()
            if not sel:
                self.messagebox.showinfo(
                    "Pick a row first",
                    "Click a row in the table, then click Open folder.",
                )
                return
            asset = item_assets.get(sel[0])
            if asset is None:
                return
            self._open_path(
                asset.path.parent, missing_label=str(asset.path.parent),
            )

        tree.bind("<Double-Button-1>", open_selected)
        tree.bind("<Return>", open_selected)

        # ── Worker thread for the scan itself ─────────────────────────
        def worker() -> None:
            from . import themes as themes_mod
            try:
                cfg = load_config()
                assets = themes_mod.scan_frontend_art(cfg)
                has_swfs = themes_mod.has_swf_themes(cfg)
            except Exception as exc:  # noqa: BLE001 — surface in UI
                # Bind `exc` at lambda-creation time. Without the
                # `_exc=exc` default arg, the lambda would close over
                # the name `exc`, which is deleted when the `except`
                # block exits (PEP 3134) — so the deferred callback
                # would raise NameError instead of showing the error.
                self.root.after(
                    0, lambda _exc=exc: count_var.set(f"Error: {_exc}"),
                )
                return
            self.root.after(0, on_scan_done, assets, has_swfs)

        def on_scan_done(assets, has_swfs) -> None:
            all_assets.clear()
            all_assets.extend(assets)
            apply_filter()
            if not assets:
                self._append_output(
                    "\n[theme browser] No PNG/JPG/etc. overlays found "
                    "under <hyperspin>/Media/Frontend or any "
                    "<system>/Images/Special A|B folder.\n"
                )
            if has_swfs:
                self._append_output(
                    "\n[theme browser] Heads-up: your Main Menu folder "
                    "contains .swf / .zip theme files — those embed "
                    "glyph art that SpinDoctor can't edit.\n"
                )

        # ── Bottom button row ─────────────────────────────────────────
        btn_row = self.ttk.Frame(win)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        self.ttk.Button(
            btn_row, text="Open in image viewer",
            command=open_selected,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Open containing folder",
            command=open_folder,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Apply replacement pack…",
            command=self._show_theme_apply,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Refresh",
            command=lambda: threading.Thread(
                target=worker, daemon=True,
            ).start(),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Close", command=win.destroy,
        ).pack(side="right")

        threading.Thread(target=worker, daemon=True).start()

    def _show_theme_apply(self) -> None:
        """Open a Toplevel that runs `theme-apply` against a user-picked
        source directory.

        Two-step UI: pick a folder + scope, click Plan to see the dry-
        run table, then Apply to commit. Apply writes a manifest under
        ``~/.spindoctor/themes/`` that the Logs & Manifests viewer's
        Undo this run button can reverse later.
        """
        win = self.tk.Toplevel(self.root)
        win.title(f"{__app_name__} — Apply theme replacement pack")
        self._fit_geometry(win, 960, 600)
        win.transient(self.root)

        self.ttk.Label(
            win,
            text=("Replace HyperSpin frontend overlay art with a "
                  "community pack. Pick the folder containing the "
                  "replacement images (PNGs/JPGs etc.); SpinDoctor "
                  "looks up each filename in the cabinet's Frontend / "
                  "Special A / Special B folders and copies the "
                  "source over each match. Every overwritten file is "
                  "backed up so the run is reversible via the Logs & "
                  "Manifests viewer."),
            wraplength=940, justify="left", padding=(10, 6),
        ).pack(fill="x")

        # ── Source folder picker ──────────────────────────────────────
        src_row = self.ttk.Frame(win)
        src_row.pack(fill="x", padx=8, pady=2)
        self.ttk.Label(src_row, text="Source folder").pack(side="left")
        src_var = self.tk.StringVar()
        self.ttk.Entry(
            src_row, textvariable=src_var,
        ).pack(side="left", fill="x", expand=True, padx=6)
        self.ttk.Button(
            src_row, text="Browse…",
            command=lambda: self._browse_backup_dir(
                src_var, "Pick theme replacement folder",
            ),
        ).pack(side="left")

        # ── Target scope ──────────────────────────────────────────────
        scope_row = self.ttk.Frame(win)
        scope_row.pack(fill="x", padx=8, pady=2)
        self.ttk.Label(scope_row, text="Target scope").pack(side="left")
        scope_var = self.tk.StringVar(value="all")
        self.ttk.Combobox(
            scope_row, textvariable=scope_var,
            values=["all", "frontend", "<system name>",
                    "<SYSTEM1,SYSTEM2>"],
            state="normal", width=28,
        ).pack(side="left", padx=6)
        self.ttk.Label(
            scope_row,
            text=("'all' = every match; 'frontend' = only "
                  "Media/Frontend/Images; a system name = that "
                  "system's Special A/B; comma-separated names = "
                  "multiple systems at once (e.g. 'MAME,Sega Naomi')."),
            foreground=_FG_DIM, wraplength=580, justify="left",
        ).pack(side="left", padx=6)

        # ── Plan tree ─────────────────────────────────────────────────
        tree_frame = self.ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
        tree = self.ttk.Treeview(
            tree_frame, columns=("scope", "bucket", "target"),
            show="tree headings",
        )
        tree.heading("#0", text="Source filename")
        tree.heading("scope", text="Scope")
        tree.heading("bucket", text="Bucket")
        tree.heading("target", text="Target path")
        tree.column("#0", width=240, stretch=True)
        tree.column("scope", width=140, stretch=False)
        tree.column("bucket", width=130, stretch=False)
        tree.column("target", width=420, stretch=True)
        tscroll = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=tree.yview,
        )
        tree.configure(yscrollcommand=tscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        tscroll.pack(side="right", fill="y")

        status_var = self.tk.StringVar(
            value="Pick a source folder and click Plan to preview the swaps.",
        )
        self.ttk.Label(
            win, textvariable=status_var, padding=(10, 4),
            wraplength=940, justify="left",
        ).pack(fill="x")

        # State carried between Plan and Apply.
        plans_holder: list = []

        def run_plan() -> None:
            from . import themes as themes_mod
            src = src_var.get().strip()
            if not src:
                self.messagebox.showwarning(
                    "Source folder required",
                    "Pick the folder containing the replacement images "
                    "first (Browse…).",
                )
                return
            src_path = Path(src)
            if not src_path.exists():
                self.messagebox.showerror(
                    "Folder not found",
                    f"{src_path} doesn't exist.",
                )
                return

            cfg = load_config()
            scope = scope_var.get().strip()
            # Comma-separated → multi-system; "frontend"/"all"/blank → target.
            systems_arg = None
            target_arg = None
            if scope.lower() not in ("", "all"):
                if scope.lower() == "frontend":
                    target_arg = "frontend"
                elif "," in scope:
                    systems_arg = [s.strip() for s in scope.split(",") if s.strip()]
                else:
                    target_arg = scope
            try:
                plans = themes_mod.plan_apply(
                    cfg, src_path, target=target_arg, systems=systems_arg,
                )
            except Exception as exc:  # noqa: BLE001 — surface in UI
                self.messagebox.showerror(
                    "Plan failed", f"{type(exc).__name__}: {exc}",
                )
                return

            tree.delete(*tree.get_children())
            plans_holder.clear()
            plans_holder.extend(plans)
            for p in plans:
                tree.insert(
                    "", "end", text=p.source.name,
                    values=(p.target_scope, p.target_bucket,
                            str(p.target)),
                )
            if plans:
                status_var.set(
                    f"{len(plans)} swap(s) planned. Click Apply to "
                    "commit — every overwritten file is backed up "
                    "first."
                )
            else:
                status_var.set(
                    "No filename matches between the source pack and "
                    "your cabinet's frontend art. Either the pack is "
                    "for a different layout or the filenames don't "
                    "line up. Open the Theme browser to see what your "
                    "cabinet has."
                )

            # Mirror plan results to the Output panel and Logs tab so
            # users can answer "what would that plan have swapped?" after
            # closing this window, and the row shows in the Logs timeline.
            scope_label = scope or "all"
            argv_display = f"theme-apply plan ← {src_path.name}  (scope: {scope_label})"
            record = _RunRecord(
                started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                argv_str=argv_display,
                dry_run=True,
            )
            header = (
                f"\n=== DRY RUN ===\n"
                f"$ theme-apply plan ← {src_path}\n"
                f"Target scope: {scope_label}\n\n"
            )
            self._append_output(header)
            record.append(header)
            if plans:
                for p in plans:
                    line = (
                        f"  {p.source.name}  →  {p.target}"
                        f"  [{p.target_scope} / {p.target_bucket}]\n"
                    )
                    self._append_output(line)
                    record.append(line)
                footer = (
                    f"\n=== DRY RUN COMPLETE ({len(plans)} swap(s) planned) — "
                    "nothing written. Click Apply to commit. ===\n"
                )
            else:
                footer = "\n=== DRY RUN COMPLETE — no matches. ===\n"
            self._append_output(footer)
            record.append(footer)
            record.exit_code = 0
            self._run_history.append(record)
            self._refresh_logs_tab()
            self._set_status(
                f"Dry run: {len(plans)} swap(s) planned. "
                "View details in Output or the History tab."
            )

        def run_apply() -> None:
            from . import themes as themes_mod
            if not plans_holder:
                self.messagebox.showinfo(
                    "Nothing to apply",
                    "Click Plan first. If the planned table is empty, "
                    "there are no matches to apply.",
                )
                return
            if not self.messagebox.askyesno(
                "Confirm apply",
                f"Replace {len(plans_holder)} file(s) on disk? Every "
                "overwritten file is backed up under "
                "~/.spindoctor/themes/ — reversible via the Logs & "
                "Manifests viewer (or `theme-apply --undo latest`).",
            ):
                return
            # Guard against double-click: the user can click Apply, then
            # the messagebox-askyesno spins the event loop and the click
            # registers a second time before the first run's worker
            # thread starts. Two concurrent threads doing file copies
            # would corrupt the manifest. Disable on entry; re-enable in
            # _on_done's finally clause.
            try:
                apply_btn.configure(state="disabled")
            except Exception:  # noqa: BLE001 - widget may not exist yet on first call
                pass
            # apply_plan does the actual disk copies — on a big theme pack
            # this can take many seconds. Run it on a worker thread so
            # the Tk event loop keeps drawing; marshal results back to
            # the main thread via root.after(0, …) (Tk widget calls are
            # only safe from the main thread).
            self._set_status(
                f"Applying {len(plans_holder)} theme swap(s)…"
            )
            _apply_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            def _worker(plans=list(plans_holder)):
                try:
                    return themes_mod.apply_plan(plans), None
                except Exception as exc:  # noqa: BLE001 — surface in UI
                    return None, exc

            def _on_done(result, exc):
                record = _RunRecord(
                    started_at=_apply_started,
                    argv_str="theme-apply apply",
                    dry_run=False,
                )
                try:
                    if exc is not None:
                        err_text = f"\n[theme-apply] apply FAILED: {type(exc).__name__}: {exc}\n"
                        record.append(err_text)
                        record.exit_code = 1
                        self._set_status("Theme apply failed.")
                        self.messagebox.showerror(
                            "Apply failed", f"{type(exc).__name__}: {exc}",
                        )
                        return
                    output_text = (
                        f"\n[theme-apply] swapped {result.swapped} file(s)"
                        + (f", skipped {len(result.skipped)}"
                           if result.skipped else "")
                        + (f"\n  manifest: {result.manifest_path}"
                           if result.manifest_path else "")
                        + "\n"
                    )
                    self._append_output(output_text)
                    record.append(output_text)
                    record.exit_code = 0
                    self._set_status(
                        f"Theme apply: swapped {result.swapped} file(s)."
                    )
                    self.messagebox.showinfo(
                        "Theme applied",
                        f"Swapped {result.swapped} file(s).\n\n"
                        + (f"Manifest: {result.manifest_path}\n"
                           "Undo via File → View logs & manifests… → Theme "
                           "swaps → Undo this run."
                           if result.manifest_path else
                           "No manifest written."),
                    )
                    win.destroy()
                finally:
                    self._run_history.append(record)
                    self._refresh_logs_tab()
                    # Re-enable so the user can retry (e.g. after fixing a
                    # write-protected source) without reopening the dialog.
                    try:
                        apply_btn.configure(state="normal")
                    except Exception:  # noqa: BLE001 - window may be destroyed
                        pass

            def _run_in_thread():
                result, exc = _worker()
                self.root.after(0, _on_done, result, exc)

            threading.Thread(target=_run_in_thread, daemon=True).start()

        btn_row = self.ttk.Frame(win)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        self.ttk.Button(
            btn_row, text="Plan", command=run_plan,
        ).pack(side="left")
        apply_btn = self.ttk.Button(
            btn_row, text="Apply", command=run_apply,
        )
        apply_btn.pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Close", command=win.destroy,
        ).pack(side="right")

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        intro_text = (
            "Point SpinDoctor at your library — fill in the paths below "
            "and click Save. Settings are stored automatically and you "
            "can come back to change them any time."
        )
        if getattr(self, "_dnd_available", False):
            intro_text += (
                "  💡 Drag a folder from Explorer / Finder onto any "
                "path field to fill it in."
            )
        intro = self.ttk.Label(
            frame, text=intro_text, wraplength=860, justify="left",
        )
        intro.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # First-run wizard CTA — the friendliest entry point for a brand-
        # new cabinet owner, so it sits at the very top of the very first
        # tab rather than buried in the button row at the bottom (where
        # it previously lived, after Save). Also reachable any time from
        # Help → First-run setup….
        wizard_row = self.ttk.Frame(frame)
        wizard_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.ttk.Label(
            wizard_row,
            text="New here? The wizard walks you through the two required "
                 "paths and runs a health check:",
            foreground=_FG_DIM,
        ).pack(side="left")
        self.ttk.Button(
            wizard_row, text="Run first-run wizard…",
            command=self._show_first_run_wizard,
        ).pack(side="left", padx=(8, 0))

        cfg = load_config()
        # Tracks whether any setup field has been edited since last save.
        # The Save button label flips to "Save configuration *" when True
        # so the user gets immediate feedback that there are pending edits
        # — switching tabs without clicking Save used to silently lose
        # changes.
        self._setup_dirty = False

        # Path rows use a running row counter so the required/optional
        # group headers can be interleaved without grid arithmetic.
        row = 2

        def _add_path_row(key, label, win_default):
            nonlocal row
            existing = getattr(cfg, key, "") or ""
            initial = existing or win_default
            var = self.tk.StringVar(value=initial)
            self._setup_vars[key] = var
            var.trace_add("write", lambda *_a, k=key: self._setup_mark_dirty())
            self.ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = self.ttk.Entry(frame, textvariable=var, width=60)
            entry.grid(row=row, column=1, sticky="ew", padx=6, pady=2)
            # Register the Entry as a drop target if tkinterdnd2 loaded
            # at startup. Dropping a folder from Explorer/Finder fills
            # the path field with the dropped folder's absolute path —
            # massively shorter than the typical "click Browse, navigate
            # through five levels, click OK" flow.
            self._register_path_drop_target(entry, var)
            btn_cell = self.ttk.Frame(frame)
            btn_cell.grid(row=row, column=2, sticky="w", pady=2)
            self.ttk.Button(
                btn_cell, text="Browse…",
                command=lambda v=var, k=key: self._browse_dir(v, k),
            ).pack(side="left")
            # Open-folder button — lets the user verify what they
            # configured by jumping to it in Explorer/Finder. Common
            # post-setup workflow: "did I really pick the right HyperSpin
            # folder?" Previously required clicking Browse… and reading
            # the dialog's current selection. Disabled visually-only via
            # the `?` label when the path is blank.
            self.ttk.Button(
                btn_cell, text="Open",
                command=lambda v=var, k=key: self._open_setup_path(v, k),
            ).pack(side="left", padx=(4, 0))
            row += 1

        def _add_group_header(text, subtitle=None, separator=False):
            nonlocal row
            if separator:
                self.ttk.Separator(frame, orient="horizontal").grid(
                    row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4)
                )
                row += 1
            self.ttk.Label(
                frame, text=text, font=("TkDefaultFont", 9, "bold"),
            ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 2))
            row += 1
            if subtitle:
                self.ttk.Label(
                    frame, text=subtitle, foreground=_FG_DIM,
                    wraplength=780, justify="left",
                ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
                row += 1

        # The _allow_blank flag in _SETUP_FIELDS doubles as the
        # required/optional split: blank-not-allowed fields are the core
        # cabinet paths every feature relies on; the rest only matter to
        # specific features and stay blank on most cabinets.
        core_fields = [f for f in _SETUP_FIELDS if not f[3]]
        optional_fields = [f for f in _SETUP_FIELDS if f[3]]

        _add_group_header("Core paths")
        for key, label, win_default, _allow_blank in core_fields:
            _add_path_row(key, label, win_default)

        _add_group_header(
            "Optional paths",
            subtitle="Used by specific features (LEDBlinky tab, backups, "
                     "audit exports). Fine to leave blank until you need them.",
            separator=True,
        )
        for key, label, win_default, _allow_blank in optional_fields:
            _add_path_row(key, label, win_default)

        # ── Scraper credentials ───────────────────────────────────────────────
        cred_sep_row = row
        self.ttk.Separator(frame, orient="horizontal").grid(
            row=cred_sep_row, column=0, columnspan=3, sticky="ew", pady=(10, 4)
        )
        self.ttk.Label(
            frame, text="Scraper credentials (optional)",
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=cred_sep_row + 1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.ttk.Label(
            frame,
            text=(
                "Used by the Metadata & Media tab to fetch artwork, videos, "
                "and metadata. Leave blank if you don't need them.\n"
                "ScreenScraper also requires a developer-account devid + "
                "devpassword issued at "
                "https://www.screenscraper.fr/membreinscription.php — the "
                "bundled \"SpinDoctor\" placeholders will not authenticate."
            ),
            wraplength=780, justify="left",
        ).grid(row=cred_sep_row + 2, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # Track credential entries so the eyeball toggle and the Test
        # credentials button can address them by key. Built lazily so a
        # second build (e.g. tab re-render) doesn't leak old references.
        self._cred_entries: dict = {}
        self._cred_pw_shown: dict = {}
        # ``key → StringVar`` for the next-to-the-entry "last-4-chars"
        # hint that tells the user whether a masked field has a stale
        # saved value behind the dots. Seeded from the saved config at
        # build time; flipped to "(edited — not yet saved)" the moment
        # the entry text changes.
        self._cred_hint_vars: dict = {}

        for j, (key, label, is_password) in enumerate(_CRED_FIELDS):
            row = cred_sep_row + 3 + j
            existing = getattr(cfg, key, "") or ""
            var = self.tk.StringVar(value=existing)
            self._setup_vars[key] = var
            var.trace_add("write", lambda *_a, k=key: self._setup_mark_dirty())
            self.ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = self.ttk.Entry(
                frame, textvariable=var, width=60,
                show="*" if is_password else "",
            )
            entry.grid(row=row, column=1, sticky="ew", padx=6, pady=2)
            self._cred_entries[key] = entry

            # Per-credential controls live in a small frame in column 2
            # so eyeball / hint / Clear stack horizontally and don't
            # fight with the existing grid column layout.
            ctrl_cell = self.ttk.Frame(frame)
            ctrl_cell.grid(row=row, column=2, sticky="w", pady=2)

            # Status hint — tells the user at a glance whether the
            # field has a saved value behind it. Sits leftmost in the
            # control cell so the eye matches the field it describes
            # before the user reaches the Show / Clear buttons.
            # ``_format_secret_hint`` returns ``"(saved)"`` / ``"(not set)"``.
            # Flips to ``"(edited — not yet saved)"`` on the first keystroke.
            hint_var = self.tk.StringVar(value=_format_secret_hint(existing, key))
            self._cred_hint_vars[key] = hint_var
            hint_label = self.ttk.Label(
                ctrl_cell, textvariable=hint_var, foreground=_FG_DIM,
                width=22, anchor="w",
            )
            hint_label.pack(side="left")
            # First-keystroke trace flips the hint to "edited". Tracked
            # via a per-key one-shot so subsequent edits don't churn.
            self._install_cred_hint_trace(key, var, hint_var, existing)

            if is_password:
                # Eyeball toggle — Show button starts on "Show" (entry
                # is masked); clicking flips both the entry's `show`
                # option and the label.
                self._cred_pw_shown[key] = False
                btn = self.ttk.Button(
                    ctrl_cell, text="Show", width=6,
                    command=lambda k=key: self._toggle_password_visibility(k),
                )
                btn.pack(side="left", padx=(6, 0))
                # Stash the button on the entry so the toggle handler
                # can flip its label without a second lookup table.
                entry._spindoctor_eye_btn = btn  # type: ignore[attr-defined]
            else:
                # Non-masked rows (username, devid) reserve a button-
                # width spacer so the [status] [Show] [Clear] columns
                # line up across every credential row. Without this,
                # the username row's Clear button sits where password
                # rows' Show button sits, and the layout looks ragged.
                spacer = self.ttk.Frame(ctrl_cell, width=48, height=1)
                spacer.pack(side="left", padx=(6, 0))
                spacer.pack_propagate(False)

            # Clear button — wipes the in-memory StringVar (does NOT
            # touch disk; the user still has to click Save
            # configuration). After Clear the hint reads "(cleared —
            # not saved)" so the user can definitively test the "no
            # API key set" scenario.
            self.ttk.Button(
                ctrl_cell, text="Clear", width=6,
                command=lambda k=key: self._clear_cred_field(k),
            ).pack(side="left", padx=(6, 0))

        frame.columnconfigure(1, weight=1)

        btn_row = self.ttk.Frame(frame)
        btn_row_index = cred_sep_row + 3 + len(_CRED_FIELDS)
        btn_row.grid(row=btn_row_index, column=0, columnspan=3, sticky="w", pady=(12, 0))
        # Save button label gets a trailing " *" when any field is dirty
        # so the user can tell at a glance that there are unsaved edits.
        # See _setup_mark_dirty / _setup_mark_clean below.
        self._setup_save_btn = self.ttk.Button(
            btn_row, text="Save configuration", command=self._save_setup,
        )
        self._setup_save_btn.pack(side="left")
        # Test credentials — pings ScreenScraper + TheGamesDB with the
        # values currently in the entries (not from disk) so the user
        # can verify a key before Saving. Async to keep the UI snappy.
        self._cred_test_btn = self.ttk.Button(
            btn_row, text="Test credentials", command=self._test_credentials,
        )
        self._cred_test_btn.pack(side="left", padx=6)
        self.ttk.Button(btn_row, text="Run Health Check", command=lambda: self._run_cli(
            "spindoctor", ["doctor"]
        )).pack(side="left", padx=6)
        # (The first-run wizard button lives at the top of this tab —
        # it's the new-user entry point, so it leads rather than trails.)
        # Folder shortcuts — same actions are also under File menu, but
        # surfacing them here saves a click for the Setup-tab use case
        # ("opened the GUI to fix a bad path, want to peek at the
        # current value on disk").
        self.ttk.Button(
            btn_row, text="Open config.json",
            command=self._open_config_file,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Open ~/.spindoctor",
            command=self._open_spindoctor_folder,
        ).pack(side="left", padx=6)

        return frame

    def _open_setup_path(self, var, key: str) -> None:
        """Open the path currently in *var* in Explorer / Finder.

        Mirrors the Browse… button next to it, but for verification:
        a cabinet owner who has just typed (or pasted) a path can
        confirm visually that it points where they expect — no need
        to re-open the file dialog.
        """
        path = var.get().strip()
        if not path:
            self._flash_validation(
                f"The {key} field is empty — use Browse… or type a "
                "path first."
            )
            return
        target = Path(path)
        # For file paths (currently just mame_executable) open the
        # containing folder instead — most users want to see "where
        # is this exe?" not "launch it".
        if target.is_file():
            target = target.parent
        self._open_path(target, missing_label=key)

    def _browse_dir(self, var, key: str) -> None:
        # mame_executable is a file, not a directory; everything else is a dir.
        if key == "mame_executable":
            path = self.filedialog.askopenfilename(
                title="Select MAME executable",
                initialdir=var.get() or str(Path.home()),
            )
        else:
            path = self.filedialog.askdirectory(
                title=f"Select {key}",
                initialdir=var.get() or str(Path.home()),
            )
        if path:
            # Tk's filedialog returns POSIX-style separators even on Windows
            # ("D:/Arcade"). Normalise to native separators so the saved
            # config matches what Windows tools expect ("D:\Arcade") and
            # downstream path comparisons don't trip over the mix.
            var.set(str(Path(path)))

    def _setup_mark_dirty(self) -> None:
        """Flip the Save button label to indicate unsaved edits.

        Called from a write-trace on every Setup tab StringVar. We only
        re-configure the button when the state actually changes, since
        keystrokes fire the trace on every character.
        """
        if self._setup_dirty:
            return
        self._setup_dirty = True
        btn = getattr(self, "_setup_save_btn", None)
        if btn is not None:
            btn.configure(text="Save configuration *")

    def _setup_mark_clean(self) -> None:
        """Clear the unsaved-edits indicator after a successful save."""
        self._setup_dirty = False
        btn = getattr(self, "_setup_save_btn", None)
        if btn is not None:
            btn.configure(text="Save configuration")

    def _toggle_password_visibility(self, key: str) -> None:
        """Flip the show=* mask on a credential Entry and its button label.

        Used by the eyeball-style toggle on the Setup tab so the user can
        verify what they pasted into a password / API-key field without
        having to clear and re-type.
        """
        entry = self._cred_entries.get(key)
        if entry is None:
            return
        shown = self._cred_pw_shown.get(key, False)
        if shown:
            entry.configure(show="*")
            self._cred_pw_shown[key] = False
        else:
            entry.configure(show="")
            self._cred_pw_shown[key] = True
        btn = getattr(entry, "_spindoctor_eye_btn", None)
        if btn is not None:
            btn.configure(text=("Hide" if self._cred_pw_shown[key] else "Show"))

    def _install_cred_hint_trace(
        self, key: str, var, hint_var, initial: str,
    ) -> None:
        """Wire the masked-cred Entry's StringVar to the hint label.

        The hint shows last-4-chars of the saved value at build time;
        the first user keystroke flips it to "(edited — not yet saved)"
        so the user knows the saved value is no longer what they're
        about to test. ``_save_setup`` re-seeds the hint from disk.
        """
        # One-shot flag — subsequent edits don't re-render the hint.
        state = {"edited": False, "initial": initial}

        def _on_change(*_args: object) -> None:
            if state["edited"]:
                return
            try:
                current = var.get()
            except Exception:  # noqa: BLE001 — Tk teardown race
                return
            if current == state["initial"]:
                return
            state["edited"] = True
            try:
                hint_var.set("(edited — not yet saved)")
            except Exception:  # noqa: BLE001
                pass

        var.trace_add("write", _on_change)
        # Stash the state so ``_save_setup`` / ``_clear_cred_field`` can
        # reset it after a save / clear.
        if not hasattr(self, "_cred_hint_state"):
            self._cred_hint_state: dict = {}
        self._cred_hint_state[key] = state

    def _clear_cred_field(self, key: str) -> None:
        """Empty a credential field's in-memory value (does not save).

        Used by the per-field Clear button on the Setup tab. The user
        still has to click Save configuration to persist the clear to
        disk — until then ``config.json`` keeps the old value (and any
        ``spindoctor`` subprocess launched from the GUI will still use
        the old value). The hint label says so explicitly.
        """
        var = self._setup_vars.get(key)
        if var is None:
            return
        var.set("")
        hint_var = self._cred_hint_vars.get(key)
        if hint_var is not None:
            hint_var.set("(cleared — not saved)")
        # Mark the field as edited so the hint trace doesn't fight back.
        state = getattr(self, "_cred_hint_state", {}).get(key)
        if state is not None:
            state["edited"] = True

    def _reseed_cred_hints_after_save(self) -> None:
        """Refresh the last-4 hints from the just-saved config.

        After ``_save_setup`` writes to disk, the hint labels should
        flip from "(edited — not yet saved)" back to "…abcd" / "(empty)"
        so the user gets immediate visual confirmation that the saved
        state now matches what's on disk.
        """
        try:
            cfg = load_config()
        except Exception:  # noqa: BLE001
            return
        for key, _label, _is_password in _CRED_FIELDS:
            hint_var = self._cred_hint_vars.get(key)
            if hint_var is None:
                continue
            saved = getattr(cfg, key, "") or ""
            try:
                hint_var.set(_format_secret_hint(saved, key))
            except Exception:  # noqa: BLE001
                continue
            state = getattr(self, "_cred_hint_state", {}).get(key)
            if state is not None:
                state["edited"] = False
                state["initial"] = saved

    def _test_credentials(self) -> None:
        """Ping ScreenScraper and TheGamesDB to verify the entered creds.

        Reads from the in-memory Setup vars (NOT disk) so users can test
        a value they haven't saved yet. Runs on a worker thread; results
        marshal back to the Tk main thread via ``root.after``. Output
        is dual-written to the bottom Output panel **and** the Logs
        tab's per-run buffer, matching the in-process pattern used by
        theme-apply — so test output lives where every other run's
        output lives instead of stuck inline in the Setup form.
        """
        btn = getattr(self, "_cred_test_btn", None)
        if btn is None:
            return

        # Snapshot the values up-front so the worker doesn't touch Tk vars
        # from a non-main thread.
        ss_user = (self._setup_vars.get("screenscraper_user")
                   or self.tk.StringVar()).get().strip()
        ss_pass = (self._setup_vars.get("screenscraper_pass")
                   or self.tk.StringVar()).get().strip()
        ss_devid = (self._setup_vars.get("screenscraper_devid")
                    or self.tk.StringVar()).get().strip()
        ss_devpassword = (self._setup_vars.get("screenscraper_devpassword")
                          or self.tk.StringVar()).get().strip()
        tgdb_key = (self._setup_vars.get("thegamesdb_key")
                    or self.tk.StringVar()).get().strip()

        # Diff the in-memory Setup vars against the saved config so the
        # user can see whether the values they're testing are what the
        # CLI will actually use. Resolves the user's "are GUI/CLI creds
        # actually being used?" confusion at the source.
        try:
            saved_cfg = load_config()
        except Exception:  # noqa: BLE001
            saved_cfg = None
        saved_user = (getattr(saved_cfg, "screenscraper_user", "") or "").strip()
        saved_pass = (getattr(saved_cfg, "screenscraper_pass", "") or "").strip()
        saved_devid = (getattr(saved_cfg, "screenscraper_devid", "") or "").strip()
        saved_devpassword = (getattr(saved_cfg, "screenscraper_devpassword", "") or "").strip()
        saved_key = (getattr(saved_cfg, "thegamesdb_key", "") or "").strip()
        diverges = (
            ss_user != saved_user
            or ss_pass != saved_pass
            or ss_devid != saved_devid
            or ss_devpassword != saved_devpassword
            or tgdb_key != saved_key
        )

        if diverges:
            self._append_output(
                "\n⚠ These values differ from saved config — "
                "metadata download / curate will still use the SAVED values "
                "until you click Save configuration.\n"
            )

        def _source(current: str, saved: str) -> str:
            if not current:
                return "(empty)"
            if current == saved:
                return "from saved config"
            return "from Setup form (unsaved)"

        self._append_output(
            f"ScreenScraper user: {_source(ss_user, saved_user)}"
            + (f" — '{ss_user}'\n" if ss_user else "\n")
        )
        self._append_output(
            f"ScreenScraper password: {_source(ss_pass, saved_pass)}"
            f" (set: {'yes' if ss_pass else 'no'})\n"
        )
        # ScreenScraper's API requires a registered developer-account
        # devid/devpassword PAIR in addition to the user account. The
        # bundled "SpinDoctor" placeholder doesn't authenticate — without
        # real dev credentials, every probe returns HTTP 403 regardless
        # of how correct the user creds are. Surface this state plainly.
        devid_eff = ss_devid or saved_devid
        devid_label = devid_eff or "(not set)"
        if devid_eff in _CRED_PLACEHOLDER_VALUES:
            devid_label = f"{devid_eff} (bundled placeholder — won't authenticate)"
        self._append_output(
            f"ScreenScraper devid: {_source(ss_devid, saved_devid)}"
            f" — {devid_label}\n"
        )
        self._append_output(
            f"ScreenScraper devpassword: {_source(ss_devpassword, saved_devpassword)}"
            f" (set: {'yes' if ss_devpassword else 'no'})\n"
        )
        self._append_output(
            f"TheGamesDB API key: {_source(tgdb_key, saved_key)}"
            f" (set: {'yes' if tgdb_key else 'no'})\n"
        )

        # Delegate the actual probes to the CLI. The shared
        # ``spindoctor.scraper.verify_*`` functions are called from one
        # place (the CLI subcommand) — no parallel implementation in
        # the GUI. ``_run_cli`` handles streaming output to the Output
        # panel, recording in the Logs tab, and finalising busy state.
        args = ["config", "verify-credentials"]
        # Pass unsaved Setup-form values as overrides so the user can
        # test creds before saving. Empty strings mean "no override —
        # use saved config", which `--ss-user ""` would set explicitly;
        # so we only add a flag when the GUI has a non-empty value.
        if ss_user:
            args += ["--ss-user", ss_user]
        if ss_pass:
            args += ["--ss-pass", ss_pass]
        if ss_devid:
            args += ["--ss-devid", ss_devid]
        if ss_devpassword:
            args += ["--ss-devpassword", ss_devpassword]
        if tgdb_key:
            args += ["--tgdb-key", tgdb_key]

        btn.configure(state="disabled", text="Testing\u2026")
        self._set_status("Contacting ScreenScraper and TheGamesDB…")

        def _on_done(rc: int) -> None:
            try:
                btn.configure(state="normal", text="Test credentials")
            except Exception:  # noqa: BLE001
                pass
            self._set_status(
                "Credential test complete." if rc == 0 else
                f"Credential test failed (exit {rc})."
            )

        self._run_cli("spindoctor", args, on_complete=_on_done)

    def _save_setup(self) -> None:
        cfg = load_config()
        for key, _label, _default, _allow_blank in _SETUP_FIELDS:
            setattr(cfg, key, self._setup_vars[key].get().strip())
        for key, _label, _is_password in _CRED_FIELDS:
            setattr(cfg, key, self._setup_vars[key].get().strip())
        save_config(cfg)
        self._setup_mark_clean()
        # Re-seed last-4 hints from the just-saved values so the
        # masked fields show the new ``…abcd`` (or ``(empty)``)
        # immediately instead of staying on "(edited — not yet saved)".
        self._reseed_cred_hints_after_save()
        ok, errors = cfg.is_valid()
        record = _RunRecord(
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            argv_str=f"setup save-configuration → {CONFIG_FILE}",
            dry_run=False,
        )
        record.append(f"$ setup save-configuration\n  saved: {CONFIG_FILE}\n")
        self._append_output(f"Saved {CONFIG_FILE}\n")
        if ok:
            record.append("Config validates OK.\n")
            self._append_output("Config validates. Try the Wheels or Audit tabs next.\n")
            self._flash_status("Configuration saved.")
        else:
            for err in errors:
                record.append(f"  ! {err}\n")
                self._append_output(f"  ! {err}\n")
            self.messagebox.showwarning(
                "Saved with warnings",
                "Configuration saved, but some required paths still need attention:\n\n"
                + "\n".join(errors),
            )
        record.exit_code = 0 if ok else 1
        self._run_history.append(record)
        self._refresh_logs_tab()
        # System dropdown depends on roms_dir/hyperspin_dir; refresh it.
        self._refresh_systems()
        # Health badges may have just changed (e.g. user set the
        # previously-missing ledblinky_dir). Re-compute in the
        # background so the tab strip stays accurate.
        threading.Thread(
            target=self._compute_tab_health_badges, daemon=True,
        ).start()

    # ── Wheels tab (LEGACY — content merged into _build_tools_tab) ──────────────

    def _fav_add(self) -> None:
        sys_ = self._fav_system_var.get().strip()
        rom = self._fav_rom_var.get().strip()
        if not sys_ or not rom:
            self.messagebox.showwarning(
                "Missing arguments",
                "Pick a system and select a game.",
            )
            return
        self._run_cli("spindoctor", ["fav", "add", sys_, rom])

    def _fav_remove(self) -> None:
        sys_ = self._fav_system_var.get().strip()
        rom = self._fav_rom_var.get().strip()
        if not sys_ or not rom:
            self.messagebox.showwarning(
                "Missing arguments",
                "Pick a system and select a game.",
            )
            return
        # Confirm before removing — matches the pattern used by the
        # other destructive controls (ignore remove, mainmenu remove,
        # curate delete). The favorite itself is reversible via
        # `fav add` but the user shouldn't have to know that to feel
        # safe clicking the button.
        if not self.messagebox.askyesno(
            "Remove favorite?",
            f"Remove {rom!r} (from {sys_}) from the cross-system "
            f"Favorites wheel?\n\nThe next `fav rebuild --apply` will "
            "regenerate the wheel without this entry. Adding it back "
            "later is a one-click operation via the Add button above.",
        ):
            return
        self._run_cli("spindoctor", ["fav", "remove", sys_, rom])

    def _fav_list(self) -> None:
        self._run_cli("spindoctor", ["fav", "list"])

    def _register_wheels_in_main_menu(self) -> None:
        # Each `mainmenu add` runs only after the previous one finishes so
        # the underlying XML write doesn't race with itself.
        apply_flag = ["--apply"] if self._global_apply_var.get() else []
        steps = [
            ("Favorites",        ["mainmenu", "add", "Favorites"]       + apply_flag),
            ("Recently Played",  ["mainmenu", "add", "Recently Played"] + apply_flag),
            ("Most Played",      ["mainmenu", "add", "Most Played"]     + apply_flag),
        ]
        total = len(steps)
        self._chain_start(total)

        def run_next(remaining, rc: int) -> None:
            if rc != 0:
                self._chain_end()
                self._append_output(
                    f"\nStopped — previous step exited with code {rc}.\n"
                )
                return
            if not remaining:
                self._chain_end()
                self._append_output("\nWheels registered in Main Menu.\n")
                return
            step_num = total - len(remaining) + 1
            self._chain_advance(step_num)
            _label, args = remaining[0]
            self._run_cli(
                "spindoctor", args,
                on_complete=lambda code: run_next(remaining[1:], code),
            )

        run_next(steps, 0)

    def _refresh_all_wheels(self) -> None:
        extra = ["--verbose"] if self._global_verbose_var.get() else []
        apply_flag = ["--apply"] if self._global_apply_var.get() else []
        all_steps: list[tuple[str, str, list[str]]] = [
            ("Favorites",        "spindoctor-fav",    ["rebuild"]     + apply_flag + extra),
            ("Recently Played",  "spindoctor-recent", ["rebuild"]     + apply_flag + extra),
            ("Most Played",      "spindoctor-stats",  ["build-wheel"] + apply_flag + extra),
        ]
        check_vars = [self._wheel_fav_var, self._wheel_recent_var, self._wheel_stats_var]
        steps = [
            (name, binary, args)
            for (name, binary, args), var in zip(all_steps, check_vars)
            if var.get()
        ]
        if not steps:
            self.messagebox.showwarning(
                "Nothing selected",
                "Tick at least one wheel to refresh.",
            )
            return
        total = len(steps)

        def run_next(remaining: list[tuple[str, str, list[str]]], rc: int) -> None:
            if rc != 0:
                self._append_output(f"\nStopped — previous step exited with code {rc}.\n")
                return
            if not remaining:
                self._append_output("\nWheel refresh complete.\n")
                return
            step_num = total - len(remaining) + 1
            name, binary, args = remaining[0]
            self._set_status(f"Step {step_num}/{total}: {name}…")
            self._run_cli(binary, args, on_complete=lambda code: run_next(remaining[1:], code))

        run_next(steps, 0)

    def _selected_clear_steps(self) -> "list[tuple[str, str, list[str]]]":
        """Return the clear-wheel CLI steps for the currently checked wheels."""
        all_steps: list[tuple[str, str, list[str]]] = [
            ("Favorites",       "spindoctor",       ["fav", "clear"]),
            ("Recently Played", "spindoctor-recent", ["clear"]),
            ("Most Played",     "spindoctor-stats",  ["clear-wheel"]),
        ]
        check_vars = [self._wheel_fav_var, self._wheel_recent_var, self._wheel_stats_var]
        return [
            (name, binary, args)
            for (name, binary, args), var in zip(all_steps, check_vars)
            if var.get()
        ]

    def _preview_clear_wheels(self) -> None:
        """Run the clear commands in dry-run mode (no --apply)."""
        steps = self._selected_clear_steps()
        if not steps:
            self.messagebox.showwarning(
                "Nothing selected",
                "Tick at least one wheel to preview the clear.",
            )
            return
        total = len(steps)
        self._chain_start(total)

        def run_next(remaining: list, rc: int) -> None:
            if rc != 0:
                self._chain_end()
                self._append_output(f"\nStopped — previous step exited with code {rc}.\n")
                return
            if not remaining:
                self._chain_end()
                self._append_output(
                    "\nDry-run complete. "
                    "Click 'Clear selected' to permanently delete.\n"
                )
                return
            step_num = total - len(remaining) + 1
            self._chain_advance(step_num)
            name, binary, args = remaining[0]
            self._set_status(f"Step {step_num}/{total}: preview clear {name}…")
            self._run_cli(binary, args, on_complete=lambda code: run_next(remaining[1:], code))

        run_next(steps, 0)

    def _clear_wheels_apply(self) -> None:
        """Run the clear commands with --apply after a confirmation prompt."""
        steps = self._selected_clear_steps()
        if not steps:
            self.messagebox.showwarning(
                "Nothing selected",
                "Tick at least one wheel to clear.",
            )
            return
        names = ", ".join(name for name, _b, _a in steps)
        fav_selected = any(name == "Favorites" for name, _b, _a in steps)
        extra_warning = (
            "\n\nNote: For Favorites, the cross-system store "
            "(~/.spindoctor/favorites.json) will also be emptied."
            if fav_selected else ""
        )
        if not self.messagebox.askyesno(
            "Clear wheels?",
            f"This will permanently delete all on-disk artifacts for:\n\n"
            f"  {names}\n\n"
            f"Deleted items include: database XML, media files, "
            f"PCLauncher INIs.{extra_warning}\n\n"
            f"RocketLauncher Statistics.ini files will NOT be modified.\n\n"
            f"Continue?",
        ):
            return
        apply_steps = [
            (name, binary, args + ["--apply"])
            for name, binary, args in steps
        ]
        total = len(apply_steps)
        self._chain_start(total)

        def run_next(remaining: list, rc: int) -> None:
            if rc != 0:
                self._chain_end()
                self._append_output(f"\nStopped — previous step exited with code {rc}.\n")
                return
            if not remaining:
                self._chain_end()
                self._append_output("\nWheel clear complete.\n")
                return
            step_num = total - len(remaining) + 1
            self._chain_advance(step_num)
            name, binary, args = remaining[0]
            self._set_status(f"Step {step_num}/{total}: clear {name}…")
            self._run_cli(binary, args, on_complete=lambda code: run_next(remaining[1:], code))

        run_next(apply_steps, 0)

    def _run_preflight(self) -> None:
        """One-button "is the cabinet ready for guests?" health check.

        Chains the three high-signal read-only commands — `doctor`,
        `tools-audit`, `audit --all` — through the existing chained-
        workflow infrastructure (so the user sees a determinate "step
        2 of 3" progress bar). Tallies pass / fail by exit code and
        pops a verdict messagebox at the end.

        The chain continues past a non-zero exit code (unlike the wheel
        workflows) because a partial cab state is still informative:
        if `tools-audit` reports missing MAME, the user wants to know
        about that *and* whether `audit --all` flagged broken media too.
        Cabinet owners about to ship cabs to LAN events have repeatedly
        asked for "one button that tells me everything's OK" — this is
        that button.
        """
        steps: list[tuple[str, list[str]]] = [
            ("doctor",      ["doctor"]),
            ("tools-audit", ["tools-audit"]),
            ("audit --all", ["audit", "--all"]),
        ]
        total = len(steps)
        self._chain_start(total)
        results: list[tuple[str, int]] = []

        self._append_output(
            "\n=== Preflight check — running "
            f"{total} read-only diagnostics. ===\n"
        )

        def run_next(remaining: list[tuple[str, list[str]]], last_rc: int) -> None:
            # Record the previous step's result before deciding next.
            if results or last_rc != 0:
                # Skip the synthetic "kicked off chain" rc=0 on first call.
                if results:
                    pass  # already recorded by the inline append below
            if not remaining:
                self._chain_end()
                self._summarise_preflight(results)
                return
            step_num = total - len(remaining) + 1
            self._chain_advance(step_num)
            name, args = remaining[0]
            self._set_status(f"Preflight step {step_num}/{total}: {name}…")
            self._append_output(
                f"\n--- Preflight {step_num}/{total}: spindoctor {name} ---\n"
            )

            def on_complete(code: int, _name=name) -> None:
                results.append((_name, code))
                # Continue past failures — partial cab health is still
                # information the user needs to act on.
                run_next(remaining[1:], code)

            self._run_cli(
                "spindoctor", args, on_complete=on_complete,
            )

        run_next(steps, 0)

    def _summarise_preflight(self, results: list[tuple[str, int]]) -> None:
        """Render the final pass/fail verdict for a preflight chain."""
        failed = [(name, rc) for name, rc in results if rc != 0]
        if not failed:
            self._append_output(
                "\n=== Preflight complete — all 3 checks passed. "
                "Cabinet is ready. ===\n"
            )
            self._set_status("Preflight: all checks passed.")
            return
        body = "\n".join(f"  ✗ {name}  (exit {rc})" for name, rc in failed)
        self._append_output(
            f"\n=== Preflight complete — {len(failed)} of "
            f"{len(results)} check(s) failed: ===\n{body}\n"
            "Read the per-step output above (or open the History tab) for "
            "details.\n"
        )
        self._set_status(
            f"Preflight: {len(failed)} of {len(results)} check(s) failed."
        )
        self.messagebox.showwarning(
            "Preflight: issues found",
            f"{len(failed)} of {len(results)} preflight check(s) failed:\n\n"
            f"{body}\n\n"
            "Read the Output panel for per-check details, then drill into "
            "the relevant tab (Audit & Doctor, Tools) to fix.",
        )

    # ── Audit & Doctor tab (LEGACY — superseded by _build_diagnostics_tab) ──────

    def _build_audit_tab(self, parent):  # LEGACY — superseded by _build_diagnostics_tab
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Run read-only diagnostics. Audit reports ROM/database "
                  "drift for one system; Doctor and Tools-Audit are "
                  "library-wide health checks and need no system pick."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.ttk.Label(frame, text="System").grid(row=1, column=0, sticky="w")
        self._system_var = self.tk.StringVar()
        self._system_combo = self.ttk.Combobox(
            frame, textvariable=self._system_var, state="readonly", width=40
        )
        self._system_combo.grid(row=1, column=1, sticky="w", padx=6)
        self.ttk.Button(frame, text="Reload list", command=lambda: self._refresh_systems(notify=True)).grid(
            row=1, column=2, sticky="w"
        )

        btn_row = self.ttk.Frame(frame)
        btn_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=12)
        self.ttk.Button(btn_row, text="Audit selected system",
                        command=self._run_audit).pack(side="left")
        self.ttk.Button(btn_row, text="Audit all systems",
                        command=self._run_audit_all,
                        ).pack(side="left", padx=6)
        self.ttk.Button(btn_row, text="Run Health Check",
                        command=lambda: self._run_cli("spindoctor", ["doctor"])
                        ).pack(side="left", padx=6)
        self.ttk.Button(btn_row, text="Check Installed Tools",
                        command=lambda: self._run_cli("spindoctor", ["tools-audit"])
                        ).pack(side="left", padx=6)

        # Preflight — the one-button "is the cab ready for guests?" check.
        # Chains doctor → tools-audit → audit --all so a user about to
        # haul the cab to an event or hand it off to a friend can get a
        # single green/red verdict without remembering which read-only
        # commands to run in which order.
        preflight_row = self.ttk.Frame(frame)
        preflight_row.grid(row=2, column=3, sticky="e", pady=12)
        self.ttk.Separator(preflight_row, orient="vertical").pack(
            side="left", fill="y", padx=(8, 8),
        )
        self.ttk.Button(
            preflight_row, text="✈  Preflight check…",
            command=self._run_preflight,
        ).pack(side="left")

        # Browse buttons — when an audit reports "wrong wheel" or
        # "missing video", jumping to the relevant folder in Explorer
        # is faster than copy-pasting the path. Picks the system from
        # the dropdown above so they always agree on what's selected.
        browse_row = self.ttk.Frame(frame)
        browse_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.ttk.Label(
            browse_row, text="Browse on disk:",
            foreground=_FG_DIM,
        ).pack(side="left")
        self.ttk.Button(
            browse_row, text="Open Media folder for selected system",
            command=self._open_audit_media_folder,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            browse_row, text="Open ROMs folder for selected system",
            command=self._open_audit_roms_folder,
        ).pack(side="left", padx=6)

        # ── Audit options: CSV report + flag toggles ─────────────────────────
        # `audit --report path.csv` writes a machine-readable summary of
        # every missing / extra / mismatched file. Cabinet owners use it
        # to share findings, paste into a spreadsheet, or feed into a
        # follow-up cleanup script. Without this row it was Custom-
        # Command-only territory.
        opts_row = self.ttk.Frame(frame)
        opts_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.ttk.Label(opts_row, text="Report CSV (optional)").pack(side="left")
        self._audit_report_var = self.tk.StringVar()
        _rep_entry = self.ttk.Entry(
            opts_row, textvariable=self._audit_report_var, width=42,
        )
        _rep_entry.pack(side="left", padx=6, fill="x", expand=True)
        self.ttk.Button(
            opts_row, text="Browse…",
            command=self._browse_audit_report,
        ).pack(side="left")

        flags_row = self.ttk.Frame(frame)
        flags_row.grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self._audit_no_media_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Skip media checks",
            variable=self._audit_no_media_var,
        ).pack(side="left")
        self._audit_detailed_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Show detailed output",
            variable=self._audit_detailed_var,
        ).pack(side="left", padx=10)

        return frame

    # ── Diagnostics tab (combines Audit & Doctor + Diagnose) ─────────────────

    def _build_diagnostics_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text="Run read-only diagnostics. No changes are made to disk.",
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # ── Step 1 — Cabinet health check ────────────────────────────────────
        # The one-click "is my cab OK?" surface leads the tab: a brand-new
        # user lands here straight after Setup, and these three buttons
        # need no inputs at all. The per-system audit (which needs a
        # system picked first) follows as Step 2.
        health_lf = self.ttk.LabelFrame(
            frame, text="Step 1 — Cabinet health check (no inputs needed)",
        )
        health_lf.pack(fill="x", pady=(0, 8))
        self.ttk.Label(
            health_lf,
            text=("Doctor validates config paths and installs; Tools audit "
                  "inventories third-party cabinet utilities; Preflight "
                  "chains doctor → tools-audit → audit --all with a "
                  "verdict at the end — the \"taking the cab to a LAN "
                  "event tomorrow\" button."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 4))
        health_row = self.ttk.Frame(health_lf)
        health_row.pack(anchor="w", padx=6, pady=(0, 6))
        self.ttk.Button(
            health_row, text="✈  Preflight check…",
            command=self._run_preflight,
        ).pack(side="left")
        self.ttk.Button(health_row, text="Run Health Check",
                        command=lambda: self._run_cli("spindoctor", ["doctor"])
                        ).pack(side="left", padx=6)
        self.ttk.Button(health_row, text="Check Installed Tools",
                        command=lambda: self._run_cli("spindoctor", ["tools-audit"])
                        ).pack(side="left", padx=6)

        # ── Step 2 — Audit a system ──────────────────────────────────────────
        audit_lf = self.ttk.LabelFrame(frame, text="Step 2 — Audit a system")
        audit_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(audit_lf, text="System").grid(row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        self._system_var = self.tk.StringVar()
        self._system_combo = self.ttk.Combobox(
            audit_lf, textvariable=self._system_var, state="readonly", width=40
        )
        self._system_combo.grid(row=0, column=1, sticky="w", padx=6, pady=(6, 2))
        self.ttk.Button(
            audit_lf, text="Reload list",
            command=lambda: self._refresh_systems(notify=True),
        ).grid(row=0, column=2, sticky="w", pady=(6, 2))

        btn_row = self.ttk.Frame(audit_lf)
        btn_row.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 2))
        self.ttk.Button(btn_row, text="Audit selected system",
                        command=self._run_audit).pack(side="left")
        self.ttk.Button(btn_row, text="Audit all systems",
                        command=self._run_audit_all,
                        ).pack(side="left", padx=6)

        browse_row = self.ttk.Frame(audit_lf)
        browse_row.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 2))
        self.ttk.Label(
            browse_row, text="Browse on disk:",
            foreground=_FG_DIM,
        ).pack(side="left")
        self.ttk.Button(
            browse_row, text="Open Media folder for selected system",
            command=self._open_audit_media_folder,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            browse_row, text="Open ROMs folder for selected system",
            command=self._open_audit_roms_folder,
        ).pack(side="left", padx=6)

        opts_row = self.ttk.Frame(audit_lf)
        opts_row.grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 2))
        self.ttk.Label(opts_row, text="Report CSV (optional)").pack(side="left")
        self._audit_report_var = self.tk.StringVar()
        _rep_entry = self.ttk.Entry(
            opts_row, textvariable=self._audit_report_var, width=42,
        )
        _rep_entry.pack(side="left", padx=6, fill="x", expand=True)
        self.ttk.Button(
            opts_row, text="Browse…",
            command=self._browse_audit_report,
        ).pack(side="left")

        flags_row = self.ttk.Frame(audit_lf)
        flags_row.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))
        self._audit_no_media_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Skip media checks",
            variable=self._audit_no_media_var,
        ).pack(side="left")
        self._audit_detailed_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Show detailed output",
            variable=self._audit_detailed_var,
        ).pack(side="left", padx=10)

        # ── Step 3 — Library-wide scans ──────────────────────────────────────
        scans_lf = self.ttk.LabelFrame(frame, text="Step 3 — Library-wide scans")
        scans_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            scans_lf,
            text=("Read-only inspectors that don't change anything on "
                  "disk. Each click runs the corresponding command and "
                  "streams output below — handy when something looks "
                  "off but you don't know which command will surface it."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 6))

        rows_scan: list[tuple[str, list[str]]] = [
            ("Find duplicate ROMs",        ["find-dupes", "--all"]),
            ("Find cross-system dupes",    ["find-dupes", "--cross-systems"]),
            ("Find misplaced ROMs",        ["find-misplaced", "--all"]),
            ("Find orphan media",          ["find-orphan-media", "--all"]),
            ("Check disc-set consistency", ["check-discs", "--all"]),
            ("Check archive extensions",   ["check-archive-ext", "--all"]),
            ("Lint config + databases",    ["lint"]),
            ("Generate report",            ["report"]),
            ("Preview HyperSpin XML",      ["preview"]),
            ("Stats — playtime overview",  ["stats"]),
        ]
        scan_grid = self.ttk.Frame(scans_lf)
        scan_grid.pack(anchor="w", padx=6, pady=(0, 6))

        def _scan_done(code: int) -> None:
            if code == 0:
                self._set_status("Scan complete — see output for results.")
            else:
                self._set_status(f"Scan finished with errors (exit {code}) — see output for details.")

        for i, (label, args) in enumerate(rows_scan):
            r, c = divmod(i, 2)
            self.ttk.Button(
                scan_grid, text=label, width=32,
                command=lambda a=args: self._run_cli("spindoctor", a, on_complete=_scan_done),
            ).grid(row=r, column=c, sticky="w", padx=4, pady=2)

        # ── Step 4 — Search & verify ─────────────────────────────────────────
        sv_lf = self.ttk.LabelFrame(frame, text="Step 4 — Search & verify")
        sv_lf.pack(fill="x", pady=(0, 8))

        # Global search
        self.ttk.Label(
            sv_lf, text="Global search",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", padx=6, pady=(6, 2))
        self.ttk.Label(
            sv_lf,
            text="Search every system's database for a ROM or display name.",
            foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(0, 4))
        search_row = self.ttk.Frame(sv_lf)
        search_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(search_row, text="Query").pack(side="left")
        self._diagnose_query_var = self.tk.StringVar()
        _search_entry = self.ttk.Entry(
            search_row, textvariable=self._diagnose_query_var,
        )
        _search_entry.pack(side="left", fill="x", expand=True, padx=6)
        _search_entry.bind("<Return>", lambda _e: self._run_find_global())
        self.ttk.Button(
            search_row, text="Search", command=self._run_find_global,
        ).pack(side="left")

        # Verify against a DAT
        self.ttk.Separator(sv_lf, orient="horizontal").pack(fill="x", padx=6, pady=8)
        self.ttk.Label(
            sv_lf, text="Verify ROMs against a DAT file",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", padx=6, pady=(0, 4))

        verify_row = self.ttk.Frame(sv_lf)
        verify_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(verify_row, text="System").pack(side="left")
        self._verify_system_var = self.tk.StringVar()
        self._verify_system_combo = self.ttk.Combobox(
            verify_row, textvariable=self._verify_system_var,
            state="readonly", width=24,
        )
        self._verify_system_combo.pack(side="left", padx=6)
        self.ttk.Label(verify_row, text="DAT path").pack(side="left", padx=(8, 0))
        self._verify_dat_var = self.tk.StringVar()
        _verify_entry = self.ttk.Entry(
            verify_row, textvariable=self._verify_dat_var,
        )
        _verify_entry.pack(side="left", fill="x", expand=True, padx=6)
        _verify_entry.bind("<Return>", lambda _e: self._run_verify())
        self.ttk.Button(
            verify_row, text="Browse…",
            command=self._browse_verify_dat,
        ).pack(side="left")
        self.ttk.Button(
            verify_row, text="Verify",
            command=self._run_verify,
        ).pack(side="left", padx=6)

        # Inspect a single game
        self.ttk.Separator(sv_lf, orient="horizontal").pack(fill="x", padx=6, pady=8)
        self.ttk.Label(
            sv_lf, text="Inspect a single game (or whole system)",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", padx=6, pady=(0, 4))
        self.ttk.Label(
            sv_lf,
            text=("Pick a system; leave ROM blank for `inspect --all`. "
                  "Read-only — never modifies disk."),
            foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(0, 4))
        inspect_row = self.ttk.Frame(sv_lf)
        inspect_row.pack(fill="x", padx=6, pady=(2, 8))
        self.ttk.Label(inspect_row, text="System").pack(side="left")
        self._inspect_system_var = self.tk.StringVar()
        self._inspect_system_combo = self.ttk.Combobox(
            inspect_row, textvariable=self._inspect_system_var,
            state="readonly", width=24,
        )
        self._inspect_system_combo.pack(side="left", padx=6)
        self._inspect_system_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_inspect_games(),
        )
        self.ttk.Label(inspect_row, text="ROM (optional)").pack(
            side="left", padx=(8, 0),
        )
        self._inspect_rom_var = self.tk.StringVar()
        self._inspect_rom_combo = self.ttk.Combobox(
            inspect_row, textvariable=self._inspect_rom_var,
            state="readonly",
        )
        self._inspect_rom_combo.pack(side="left", fill="x", expand=True, padx=6)
        self._inspect_rom_combo.bind("<Return>", lambda _e: self._run_inspect())
        self.ttk.Button(
            inspect_row, text="↻", width=3,
            command=self._refresh_inspect_games,
        ).pack(side="left")
        self.ttk.Button(
            inspect_row, text="Inspect", command=self._run_inspect,
        ).pack(side="left", padx=(6, 0))

        return frame

    def _browse_audit_report(self) -> None:
        path = self.filedialog.asksaveasfilename(
            title="Save audit CSV as…",
            defaultextension=".csv",
            initialfile="audit.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self._audit_report_var.set(str(Path(path)))

    def _open_audit_media_folder(self) -> None:
        system = self._system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "No system selected",
                "Pick a system from the dropdown above first.",
            )
            return
        self._open_system_media_folder(system)

    def _open_audit_roms_folder(self) -> None:
        system = self._system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "No system selected",
                "Pick a system from the dropdown above first.",
            )
            return
        cfg = load_config()
        if not cfg.roms_dir:
            self.messagebox.showwarning(
                "roms_dir not set",
                "Fill in the ROMs directory on the Setup tab first.",
            )
            return
        self._open_path(
            Path(cfg.roms_dir) / system,
            missing_label=f"roms_dir/{system}",
        )

    def _refresh_systems(self, *, notify: bool = False) -> None:
        try:
            _cfg = load_config()
            systems = get_systems(_cfg)
        except Exception as exc:  # noqa: BLE001 — surface any config error to UI
            _cfg = None
            systems = []
            self._set_status(f"Could not list systems: {exc}")

        # Build the set of system names that are on the HyperSpin wheel so we
        # can badge any orphan folders with "(Not in wheel)" in every dropdown.
        # Failures (missing Main Menu.xml, bad config) silently skip annotation
        # — the badge is cosmetic and should never block normal operation.
        _wheel: set[str] = set()
        if _cfg is not None:
            try:
                from . import mainmenu as _mm_mod
                _mm = _mm_mod.load_main_menu(_cfg)
                _wheel = {e.system.lower() for e in _mm.entries}
            except Exception:  # noqa: BLE001
                pass
        display_systems = [
            s if s.lower() in _wheel else s + _NOT_IN_WHEEL_SUFFIX
            for s in systems
        ]

        # Apply the optional quick-filter (toggled by Ctrl+Shift+F).
        # Case-insensitive substring match against the system name.
        # When the filter is empty, every system shows — matches the
        # behaviour before the filter existed.
        filter_pattern = ""
        try:
            filter_pattern = self._system_filter_var.get().strip().lower()
        except Exception:  # noqa: BLE001 - var may not exist on early calls
            filter_pattern = ""
        if filter_pattern:
            unfiltered_count = len(systems)
            systems = [s for s in systems if filter_pattern in s.lower()]
            # Cheap user feedback: show what's actually visible vs hidden.
            if notify or unfiltered_count != len(systems):
                self._set_status(
                    f"System filter: {filter_pattern!r} → "
                    f"{len(systems)} of {unfiltered_count} systems shown."
                )

        # Every tab that has a system picker. Attributes may not exist yet
        # on the first call (tabs build lazily), so we guard with getattr.
        # The fix-exe tab is PC-specific, so pre-select the "PC Games" system
        # (case-insensitive) when one exists.
        pc_system = next((s for s in systems if s.lower() == "pc games"), None)
        combos_and_vars = [
            ("_system_combo",          "_system_var",          None),
            ("_mainmenu_system_combo", "_mainmenu_system_var", None),
            ("_meta_system_combo",     "_meta_system_var",     None),
            ("_verify_system_combo",   "_verify_system_var",   None),
            ("_inspect_system_combo",  "_inspect_system_var",  None),
            ("_fav_system_combo",      "_fav_system_var",      None),
            ("_match_system_combo",    "_match_system_var",    None),
            ("_games_system_combo",    "_games_system_var",    None),
            ("_organize_system_combo", "_organize_system_var", None),
            ("_madd_system_combo",     "_madd_system_var",     None),
            ("_ovr_system_combo",      "_ovr_system_var",      None),
            ("_curate_system_combo",   "_curate_system_var",   None),
            ("_ignore_system_combo",   "_ignore_system_var",   None),
            ("_repath_system_combo",   "_repath_system_var",   None),
            # _led_system_combo removed — Step 1 is MAME-only, hardcoded in _run_led_generate/_run_led_audit
            ("_lg_system_combo",       "_lg_system_var",       None),
            ("_tools_wheel_combo",     "_tools_wheel_var",     "Toolkit"),
        ]
        # Track which combos already have the badge-stripping binding so we
        # don't accumulate duplicate bindings across repeated _refresh_systems()
        # calls (tabs build lazily, so combos may be created mid-session).
        _badge_bound: set[str] = getattr(self, "_system_badge_bound", set())
        self._system_badge_bound = _badge_bound

        for combo_attr, var_attr, default in combos_and_vars:
            combo = getattr(self, combo_attr, None)
            if combo is None:
                continue
            combo["values"] = display_systems
            var = getattr(self, var_attr, None)
            if var is None:
                continue
            if systems and not var.get():
                # If a default is supplied AND that default is in the list,
                # use it. Otherwise fall back to systems[0] — never set the
                # var to a value that isn't in the dropdown, or the user
                # sees a system that doesn't exist and the resulting argv
                # references it.
                var.set(default if default in systems else systems[0])
            # Add a one-time binding that strips the "(Not in wheel)" badge
            # from the var the moment the user picks from the dropdown so that
            # every downstream CLI call always receives the clean system name.
            if combo_attr not in _badge_bound:
                _badge_bound.add(combo_attr)
                def _strip_badge(event, _v=var):
                    val = _v.get()
                    if val.endswith(_NOT_IN_WHEEL_SUFFIX):
                        _v.set(val[:-len(_NOT_IN_WHEEL_SUFFIX)])
                combo.bind("<<ComboboxSelected>>", _strip_badge, add=True)

        # Auto-populate the fixexe game list when the section is first built
        # with a pre-selected system.  Setting a var via .set() does NOT fire
        # <<ComboboxSelected>>, so the game list would otherwise stay empty
        # until the user manually picks a system from the dropdown.
        fixexe_game_combo = getattr(self, "_fixexe_game_combo", None)
        if fixexe_game_combo is not None and not fixexe_game_combo["values"]:
            if getattr(self, "_games_system_var", None) and self._games_system_var.get():
                self._refresh_fixexe_games()

        # Fill Defaults system combo — populate values but never auto-select;
        # blank = all systems is the intended default.
        fd_combo = getattr(self, "_fd_system_combo", None)
        if fd_combo is not None:
            fd_combo["values"] = display_systems
            if fd_combo not in _badge_bound:
                _badge_bound.add("_fd_system_combo")
                _fd_var = getattr(self, "_fd_system_var", None)
                if _fd_var is not None:
                    def _strip_fd(event, _v=_fd_var):
                        val = _v.get()
                        if val.endswith(_NOT_IN_WHEEL_SUFFIX):
                            _v.set(val[:-len(_NOT_IN_WHEEL_SUFFIX)])
                    fd_combo.bind("<<ComboboxSelected>>", _strip_fd, add=True)

        # Migrate systems Listbox — different widget type, handled separately.
        lb = getattr(self, "_migrate_systems_lb", None)
        if lb is not None:
            lb.delete(0, self.tk.END)
            for s in display_systems:
                lb.insert(self.tk.END, s)

        if notify:
            if systems:
                self._set_status(f"Reloaded {len(systems)} system(s).")
            else:
                self._set_status("No systems found — check paths in the Setup tab.")

    def _run_audit_all(self) -> None:
        args = ["audit", "--all"]
        self._audit_args_extend(args)
        self._run_cli("spindoctor", args)

    def _run_audit(self) -> None:
        system = self._system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "No system selected",
                "Pick a system from the dropdown (or click Reload list "
                "after configuring paths in the Setup tab).",
            )
            return
        args = ["audit", "--system", system]
        self._audit_args_extend(args)
        self._run_cli("spindoctor", args)

    def _audit_args_extend(self, args: list[str]) -> None:
        """Append the shared audit-options row's flags to *args*.

        Used by both `Audit selected system` and `Audit all systems`
        so the CSV / no-media / detailed toggles work for either.
        """
        report = getattr(self, "_audit_report_var", None)
        if report is not None:
            path = report.get().strip()
            if path:
                args += ["--report", path]
        no_media = getattr(self, "_audit_no_media_var", None)
        if no_media is not None and no_media.get():
            args.append("--no-media")
        detailed = getattr(self, "_audit_detailed_var", None)
        if detailed is not None and detailed.get():
            args.append("--detailed")

    # ── Backup & Restore tab ──────────────────────────────────────────────────

    def _build_backup_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Snapshot the library to a target folder, list previous "
                  "backups, or restore from one. Pick the components to "
                  "include — the default is everything. Every action is a "
                  "dry-run unless you tick Apply, mirroring the CLI."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        # ── Step 1 — Target folder & components ─────────────────────────────
        cfg_frame = self.ttk.LabelFrame(
            frame, text="Step 1 — Target folder & components",
        )
        cfg_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        cfg_frame.columnconfigure(1, weight=1)

        self.ttk.Label(cfg_frame, text="Target folder").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        _backup_cfg = load_config()
        _backup_dir_default = getattr(_backup_cfg, "backup_dir", "") or ""
        self._backup_target_var = self.tk.StringVar(value=_backup_dir_default)
        self.ttk.Entry(cfg_frame, textvariable=self._backup_target_var, width=60).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=6, pady=2,
        )
        self.ttk.Button(
            cfg_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(self._backup_target_var,
                                                   "Pick backup target folder"),
        ).grid(row=0, column=3, sticky="w", pady=2)

        # Components — default to "everything" so a click-and-go user gets
        # a full backup. Cabinet owners who want a partial backup can untick.
        self._backup_component_vars: dict[str, "self.tk.BooleanVar"] = {}
        for i, (key, desc) in enumerate(_BACKUP_COMPONENTS):
            var = self.tk.BooleanVar(value=True)
            self._backup_component_vars[key] = var
            self.ttk.Checkbutton(
                cfg_frame, text=f"{key}  —  {desc}", variable=var,
            ).grid(row=i + 1, column=0, columnspan=4, sticky="w", padx=6, pady=1)

        # Preset shortcut buttons — quick selections for common use cases.
        preset_row = self.ttk.Frame(cfg_frame)
        preset_row.grid(
            row=len(_BACKUP_COMPONENTS) + 1, column=0, columnspan=4,
            sticky="w", padx=6, pady=(6, 4),
        )
        self.ttk.Label(preset_row, text="Presets:").pack(side="left", padx=(0, 6))

        _config_snapshot_btn = self.ttk.Button(
            preset_row,
            text="Config snapshot",
            command=self._preset_config_snapshot,
        )
        _config_snapshot_btn.pack(side="left", padx=(0, 4))
        _attach_tooltip(
            _config_snapshot_btn,
            "Selects settings + databases only.\n\n"
            "A lightweight snapshot of your SpinDoctor configuration "
            "(~/.spindoctor/config.json — all configured paths) and your "
            "HyperSpin game-list XMLs. Ideal before moving files to a new "
            "drive: the snapshot is small (kilobytes, not gigabytes) and "
            "lets you restore SpinDoctor's path configuration and game "
            "lists without copying ROMs or media.",
            self.tk,
        )

        _full_backup_btn = self.ttk.Button(
            preset_row,
            text="Everything",
            command=self._preset_full_backup,
        )
        _full_backup_btn.pack(side="left", padx=(0, 4))
        _attach_tooltip(
            _full_backup_btn,
            "Ticks all components for a complete library backup.",
            self.tk,
        )

        # ── Step 2 — Create backup ────────────────────────────────────────────
        create_frame = self.ttk.LabelFrame(frame, text="Step 2 — Create backup")
        create_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        create_frame.columnconfigure(1, weight=1)

        self.ttk.Label(create_frame, text="Label (optional)").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._backup_label_var = self.tk.StringVar()
        self.ttk.Entry(create_frame, textvariable=self._backup_label_var, width=30).grid(
            row=0, column=1, sticky="w", padx=6, pady=2,
        )

        bk_btn_row = self.ttk.Frame(create_frame)
        bk_btn_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            bk_btn_row, text="Create backup",
            command=self._run_backup_create,
        ).pack(side="left")
        self.ttk.Button(
            bk_btn_row, text="List backups under target",
            command=self._run_backup_list,
        ).pack(side="left", padx=(10, 0))

        # ── (removed standalone List section — now a button inside Step 2) ──
        # ── Step 3 — Restore from a backup ───────────────────────────────────
        restore_frame = self.ttk.LabelFrame(frame, text="Step 3 — Restore from a backup")
        restore_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        restore_frame.columnconfigure(1, weight=1)

        self.ttk.Label(restore_frame, text="Backup folder").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._backup_restore_path_var = self.tk.StringVar(value="")
        self._backup_restore_combo = self.ttk.Combobox(
            restore_frame, textvariable=self._backup_restore_path_var, width=48,
        )
        self._backup_restore_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        restore_btn_frame = self.ttk.Frame(restore_frame)
        restore_btn_frame.grid(row=0, column=2, sticky="w", padx=(0, 6), pady=2)
        self.ttk.Button(
            restore_btn_frame, text="Scan",
            command=self._scan_backup_folders,
        ).pack(side="left", padx=(0, 4))
        self.ttk.Button(
            restore_btn_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._backup_restore_path_var, "Pick backup folder to restore",
            ),
        ).pack(side="left")

        self._backup_use_current_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            restore_frame,
            text="Use current config paths (drive letters changed since backup)",
            variable=self._backup_use_current_var,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        self._backup_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            restore_frame,
            text="Overwrite existing folders at the destination",
            variable=self._backup_overwrite_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        # Two button rows: read-only inspection on top, destructive
        # action (Restore) on its own row beneath a Separator. Sharing
        # the row with Info / Compare made it easy to fat-finger Restore
        # while reaching for a safe button.
        btn_row = self.ttk.Frame(restore_frame)
        btn_row.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 2))
        self.ttk.Button(
            btn_row, text="Show backup info",
            command=self._run_backup_info,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Compare to live",
            command=self._run_backup_diff,
        ).pack(side="left", padx=6)

        self.ttk.Separator(restore_frame, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 4),
        )
        destructive_row = self.ttk.Frame(restore_frame)
        destructive_row.grid(row=6, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))
        self.ttk.Button(
            destructive_row, text="Restore backup",
            command=self._run_backup_restore,
        ).pack(side="left")

        frame.columnconfigure(1, weight=1)

        return frame

    def _run_scrub(self) -> None:
        do_fav = self._scrub_favorites_var.get()
        do_stats = self._scrub_stats_var.get()
        do_hs_fav = self._scrub_hs_favorites_var.get()
        if not do_fav and not do_stats and not do_hs_fav:
            self.messagebox.showwarning(
                "Nothing selected",
                "Tick at least one option to scrub.",
            )
            return
        backup_dir = self._scrub_backup_var.get().strip()
        apply_ = self._global_apply_var.get()
        if apply_ and not backup_dir and do_stats:
            if not self.messagebox.askyesno(
                "No backup configured",
                "You are about to permanently delete Statistics.ini files "
                "with no backup.\n\n"
                "Statistics cannot be regenerated by SpinDoctor — all play "
                "history will be lost permanently.\n\n"
                "Continue without a backup?",
            ):
                return
        if apply_:
            what = []
            if do_fav:
                what.append("favorites store")
            if do_stats:
                what.append("play statistics")
            if do_hs_fav:
                what.append("HyperSpin per-system favorites")
            if not self.messagebox.askyesno(
                "Confirm scrub",
                f"This will permanently delete: {' + '.join(what)}.\n\n"
                + ("A backup will be created first.\n\n" if backup_dir else "")
                + "This cannot be undone. Continue?",
            ):
                return
        args = ["scrub"]
        # Build flag list — when both fav+stats but not hs_fav, omit flags
        # (scrub defaults to both). Always pass explicit flags when hs_fav
        # is involved, since it never defaults on.
        if do_hs_fav or not (do_fav and do_stats):
            if do_fav:
                args.append("--favorites")
            if do_stats:
                args.append("--stats")
            if do_hs_fav:
                args.append("--hs-favorites")
        if backup_dir:
            args += ["--backup-dir", backup_dir]
        if apply_:
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_scrub_restore(self) -> None:
        path = self._scrub_restore_path_var.get().strip()
        if not path:
            self.messagebox.showwarning(
                "Backup folder required",
                "Pick the scrub backup folder to restore from "
                "(the scrub-<timestamp> folder created by scrub --backup-dir).",
            )
            return
        args = ["scrub-restore", path]
        if self._global_apply_var.get():
            if not self.messagebox.askyesno(
                "Confirm restore",
                f"Restore files from:\n{path}\n\n"
                "Existing files will be overwritten. Continue?",
            ):
                return
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _browse_backup_dir(self, var, title: str) -> None:
        path = self.filedialog.askdirectory(
            title=title, initialdir=var.get() or str(Path.home()),
        )
        if path:
            # Match the Setup tab: keep separators native to the OS so
            # paths copy-pasted into a Windows shell don't trip on
            # forward slashes.
            var.set(str(Path(path)))

    def _scan_backup_folders(self) -> None:
        """Populate the restore Combobox by shelling out to ``backup list --json``.

        The GUI used to walk the target directory inline — a second
        implementation of what ``spindoctor backup list`` already does.
        That kind of drift is exactly the bug pattern that corrupted
        Main Menu.xml: two implementations diverge silently. The CLI is
        now the single source of truth for "which SpinDoctor backups
        exist under <target>"; the GUI just renders the result.
        """
        target = self._backup_target_var.get().strip()
        if not target:
            self.messagebox.showwarning(
                "No target folder",
                "Set the backup target folder at the top of this tab first.",
            )
            return
        target_path = Path(target)
        if not target_path.exists():
            self.messagebox.showwarning(
                "Folder not found",
                f"Backup target folder does not exist:\n{target_path}",
            )
            return
        try:
            argv = resolve_cli_command("spindoctor") + [
                "backup", "list", "--target", str(target_path), "--json",
            ]
            proc = subprocess.run(
                argv,
                check=True, capture_output=True, text=True,
                timeout=30,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.messagebox.showerror(
                "Could not list backups",
                f"Failed to enumerate backups via "
                f"`spindoctor backup list`:\n\n{exc}",
            )
            return
        try:
            entries = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            self.messagebox.showerror(
                "Could not list backups",
                f"`spindoctor backup list --json` produced unparseable "
                f"output:\n\n{exc}\n\n{proc.stdout!r}",
            )
            return
        folders = sorted(
            (e["path"] for e in entries if isinstance(e, dict) and "path" in e),
            reverse=True,
        )
        if not folders:
            self._flash_validation(
                f"No SpinDoctor backups in {target_path}."
            )
            return
        self._backup_restore_combo["values"] = folders
        if not self._backup_restore_path_var.get():
            self._backup_restore_path_var.set(folders[0])
        self._set_status(f"Found {len(folders)} backup(s) in {target_path.name}.")

    def _preset_config_snapshot(self) -> None:
        """Tick settings + databases only; untick everything else.

        A config snapshot is a lightweight alternative to a full backup —
        it saves SpinDoctor's path configuration (config.json) and the
        HyperSpin game-list XMLs without touching ROMs, media, or
        emulator binaries. Ideal before moving files to a new drive.
        """
        snapshot_components = {"settings", "databases"}
        for key, var in self._backup_component_vars.items():
            var.set(key in snapshot_components)
        # Pre-fill a descriptive label so the resulting folder is
        # self-documenting (e.g. spindoctor-backup-20260521_143012-config).
        if not self._backup_label_var.get():
            self._backup_label_var.set("config")
        self._set_status(
            "Config snapshot preset: settings + databases selected. "
            "Set a target folder, then click Create backup."
        )

    def _preset_full_backup(self) -> None:
        """Tick all components for a complete library backup."""
        for var in self._backup_component_vars.values():
            var.set(True)
        self._backup_label_var.set("")
        self._set_status("All components selected for a full backup.")

    def _selected_backup_components(self) -> Optional[str]:
        """Return a comma-separated `--include` value, or None for "all".

        ``None`` lets the underlying CLI pick its default ("all"), which
        matches what most users want and avoids re-listing every component
        in the argv.
        """
        selected = [k for k, v in self._backup_component_vars.items() if v.get()]
        if not selected:
            return ""  # signal to caller: nothing picked
        if len(selected) == len(_BACKUP_COMPONENTS):
            return None
        return ",".join(selected)

    def _run_backup_create(self) -> None:
        target = self._backup_target_var.get().strip()
        if not target:
            self.messagebox.showwarning(
                "Target folder required",
                "Pick the folder where backups should be written before "
                "running Create.",
            )
            return
        include = self._selected_backup_components()
        if include == "":
            self.messagebox.showwarning(
                "No components selected",
                "Tick at least one component to back up.",
            )
            return
        args = ["backup", "create", "--target", target]
        if include is not None:
            args += ["--include", include]
        label = self._backup_label_var.get().strip()
        if label:
            args += ["--label", label]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_backup_list(self) -> None:
        target = self._backup_target_var.get().strip()
        if not target:
            self.messagebox.showwarning(
                "Target folder required",
                "Pick the folder where backups live before listing.",
            )
            return
        self._run_cli("spindoctor", ["backup", "list", "--target", target])

    def _run_backup_info(self) -> None:
        backup_path = self._backup_restore_path_var.get().strip()
        if not backup_path:
            self.messagebox.showwarning(
                "Backup folder required",
                "Pick a backup folder first (one that was produced by "
                "`backup create`).",
            )
            return
        self._run_cli("spindoctor", ["backup", "info", "--backup", backup_path])

    def _run_backup_diff(self) -> None:
        """Run `spindoctor diff <backup>` against the current selection.

        Surfaces the existing CLI-only `diff` subcommand alongside the
        Show backup info / Restore controls — same picker, no extra
        config required. Pure read-only command, so no confirmation
        and no Apply check.
        """
        backup_path = self._backup_restore_path_var.get().strip()
        if not backup_path:
            self.messagebox.showwarning(
                "Backup folder required",
                "Pick a backup folder first — diff compares its "
                "contents against the live cabinet tree.",
            )
            return
        self._run_cli("spindoctor", ["diff", backup_path])

    def _run_backup_restore(self) -> None:
        backup_path = self._backup_restore_path_var.get().strip()
        if not backup_path:
            self.messagebox.showwarning(
                "Backup folder required",
                "Pick the backup folder you want to restore from.",
            )
            return
        include = self._selected_backup_components()
        if include == "":
            self.messagebox.showwarning(
                "No components selected",
                "Tick at least one component to restore.",
            )
            return
        if self._global_apply_var.get():
            if not self.messagebox.askyesno(
                "Restore backup?",
                f"This will restore files from:\n{backup_path}\n\n"
                "Existing files on disk may be overwritten. "
                "This cannot be undone.\n\nContinue?",
            ):
                return
        args = ["backup", "restore", "--backup", backup_path]
        if include is not None:
            args += ["--include", include]
        if self._backup_use_current_var.get():
            args.append("--use-current-paths")
        if self._backup_overwrite_var.get():
            args.append("--overwrite")
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    # ── Migrate tab ───────────────────────────────────────────────────────────

    def _build_migrate_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Move (or copy) the library to a new drive in one shot. "
                  "Per-component checkboxes default to all five — uncheck "
                  "to migrate a subset. Dry-run by default; tick Apply to "
                  "execute. Every applied migration writes a manifest you "
                  "can undo from the panel below."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        # ── Step 1 — Current configuration ───────────────────────────────────
        cur_cfg_frame = self.ttk.LabelFrame(frame, text="Step 1 — Current configuration")
        cur_cfg_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        self.ttk.Label(
            cur_cfg_frame,
            text="Check what paths are currently configured before migrating.",
            foreground=_FG_DIM,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 2))
        cur_cfg_btn_row = self.ttk.Frame(cur_cfg_frame)
        cur_cfg_btn_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))
        self.ttk.Button(
            cur_cfg_btn_row, text="Show current paths",
            command=lambda: self._run_cli("spindoctor", ["config", "show"]),
        ).pack(side="left")
        self.ttk.Button(
            cur_cfg_btn_row, text="Run Health Check",
            command=lambda: self._run_cli("spindoctor", ["doctor"]),
        ).pack(side="left", padx=6)

        # ── Step 2 — Backup before migrating ─────────────────────────────────
        pre_bkp_frame = self.ttk.LabelFrame(frame, text="Step 2 — Backup before migrating")
        pre_bkp_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        pre_bkp_frame.columnconfigure(1, weight=1)
        self.ttk.Label(
            pre_bkp_frame,
            text=(
                "Create a snapshot of your current setup before migrating. "
                "You can restore from it if anything goes wrong."
            ),
            wraplength=800, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 2))
        self.ttk.Label(pre_bkp_frame, text="Backup folder").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        _migrate_cfg = load_config()
        self._pre_migrate_backup_var = self.tk.StringVar(
            value=getattr(_migrate_cfg, "backup_dir", "") or ""
        )
        self.ttk.Entry(
            pre_bkp_frame, textvariable=self._pre_migrate_backup_var, width=50,
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            pre_bkp_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._pre_migrate_backup_var, "Pick backup target folder",
            ),
        ).grid(row=1, column=2, sticky="w", pady=2)
        self.ttk.Button(
            pre_bkp_frame, text="Create backup now",
            command=self._run_pre_migrate_backup,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 4))

        # ── Step 3 — Migration settings (target, components, options) ────────
        mig_frame = self.ttk.LabelFrame(
            frame, text="Step 3 — Migration settings",
        )
        mig_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        mig_frame.columnconfigure(1, weight=1)

        # Target root
        self.ttk.Label(mig_frame, text="Target root").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._migrate_target_var = self.tk.StringVar()
        self.ttk.Entry(mig_frame, textvariable=self._migrate_target_var, width=60).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=6, pady=2,
        )
        self.ttk.Button(
            mig_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._migrate_target_var, "Pick migration target root",
            ),
        ).grid(row=0, column=3, sticky="w", pady=2)

        # Components
        self.ttk.Label(mig_frame, text="Components:").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=6, pady=(6, 0),
        )
        self._migrate_component_vars: dict = {}
        for i, (key, desc) in enumerate(_MIGRATE_COMPONENTS):
            var = self.tk.BooleanVar(value=True)
            self._migrate_component_vars[key] = var
            self.ttk.Checkbutton(
                mig_frame, text=f"{key}  —  {desc}", variable=var,
            ).grid(row=i + 2, column=0, columnspan=4, sticky="w", padx=6, pady=1)

        _comp_row_end = 2 + len(_MIGRATE_COMPONENTS)

        # Systems filter
        self.ttk.Label(
            mig_frame,
            text="Systems filter (optional — only applies to roms component):",
        ).grid(row=_comp_row_end, column=0, columnspan=4, sticky="w", padx=6, pady=(8, 0))
        migrate_list_frame = self.ttk.Frame(mig_frame)
        migrate_list_frame.grid(
            row=_comp_row_end + 1, column=0, columnspan=4,
            sticky="ew", padx=6, pady=(2, 0),
        )
        migrate_list_frame.columnconfigure(0, weight=1)
        self._migrate_systems_lb = self.tk.Listbox(
            migrate_list_frame,
            selectmode=self.tk.MULTIPLE,
            height=5,
            exportselection=False,
        )
        migrate_lb_vsb = self.ttk.Scrollbar(
            migrate_list_frame, orient="vertical",
            command=self._migrate_systems_lb.yview,
        )
        self._migrate_systems_lb.configure(yscrollcommand=migrate_lb_vsb.set)
        self._migrate_systems_lb.grid(row=0, column=0, sticky="ew")
        migrate_lb_vsb.grid(row=0, column=1, sticky="ns")
        migrate_lb_btns = self.ttk.Frame(mig_frame)
        migrate_lb_btns.grid(
            row=_comp_row_end + 2, column=0, columnspan=4,
            sticky="w", padx=6, pady=(2, 4),
        )
        self.ttk.Button(
            migrate_lb_btns, text="Select all",
            command=lambda: self._migrate_systems_lb.selection_set(0, self.tk.END),
        ).pack(side="left")
        self.ttk.Button(
            migrate_lb_btns, text="Clear",
            command=lambda: self._migrate_systems_lb.selection_clear(0, self.tk.END),
        ).pack(side="left", padx=6)
        self.ttk.Label(
            migrate_lb_btns,
            text="(nothing selected = migrate all systems)",
            foreground=_FG_DIM,
        ).pack(side="left", padx=4)

        # Options
        self.ttk.Label(mig_frame, text="Options:").grid(
            row=_comp_row_end + 3, column=0, columnspan=4,
            sticky="w", padx=6, pady=(8, 0),
        )
        self._migrate_keep_source_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            mig_frame, text="Copy instead of move (keep source files)",
            variable=self._migrate_keep_source_var,
        ).grid(row=_comp_row_end + 4, column=0, columnspan=4, sticky="w", padx=6, pady=2)

        self._migrate_verify_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            mig_frame,
            text="SHA1-verify each file after copying (Copy mode only)",
            variable=self._migrate_verify_var,
        ).grid(row=_comp_row_end + 5, column=0, columnspan=4, sticky="w", padx=6, pady=2)

        self._migrate_no_update_config_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            mig_frame,
            text="Don't update config.json with the new paths",
            variable=self._migrate_no_update_config_var,
        ).grid(row=_comp_row_end + 6, column=0, columnspan=4, sticky="w", padx=6, pady=2)

        self._migrate_preserve_names_var = self.tk.BooleanVar(value=False)
        _mig_preserve = self.ttk.Checkbutton(
            mig_frame,
            text="Keep original folder names",
            variable=self._migrate_preserve_names_var,
        )
        _mig_preserve.grid(row=_comp_row_end + 7, column=0, columnspan=4,
                           sticky="w", padx=6, pady=2)
        _attach_tooltip(
            _mig_preserve,
            "Default off: the migrated layout uses canonical folder "
            "names (Games / HyperSpin / Emulators / RocketLauncher / "
            "LEDBlinky) under the target root regardless of what your "
            "source folders were called. Tick to carry the exact source "
            "folder names through — useful when scripts elsewhere on "
            "the cabinet reference those names by path.",
            self.tk,
        )

        self.ttk.Button(
            mig_frame, text="Start Migration", command=self._run_migrate,
        ).grid(row=_comp_row_end + 8, column=0, columnspan=4,
               sticky="w", padx=6, pady=(4, 6))

        # ── Step 4 — Undo a previous migration ───────────────────────────────
        undo_frame = self.ttk.LabelFrame(frame, text="Step 4 — Undo a previous migration")
        undo_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        undo_frame.columnconfigure(1, weight=1)

        self.ttk.Label(undo_frame, text="Manifest").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._migrate_undo_var = self.tk.StringVar(value="latest")
        self._migrate_undo_combo = self.ttk.Combobox(
            undo_frame, textvariable=self._migrate_undo_var, width=50,
        )
        self._migrate_undo_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            undo_frame, text="Refresh",
            command=self._refresh_migrate_manifests,
        ).grid(row=0, column=2, sticky="w", padx=(0, 6), pady=2)
        self.ttk.Label(
            undo_frame,
            text="Select a manifest or leave as 'latest'. Click Refresh to load available manifests.",
            foreground=_FG_DIM,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=6)

        btn_row = self.ttk.Frame(undo_frame)
        btn_row.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            btn_row, text="List manifests",
            command=lambda: self._run_cli(
                "spindoctor", ["migrate", "--list-manifests"],
            ),
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Undo", command=self._run_migrate_undo,
        ).pack(side="left", padx=6)

        # ── Step 5 — Update RocketLauncher after migration ───────────────────
        post_frame = self.ttk.LabelFrame(
            frame, text="Step 5 — Update RocketLauncher after migration",
        )
        post_frame.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        self.ttk.Label(
            post_frame,
            text=(
                "After migrating your ROM drive, run generate-config to update "
                "RocketLauncher's per-system INIs with the new Rom_Path. "
                "Only Rom_Path= is changed — your emulator assignments "
                "(Default_Emulator, Emu_Path, Module, etc.) are preserved."
            ),
            wraplength=800, justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 4))
        self.ttk.Button(
            post_frame, text="Update RocketLauncher INIs",
            command=self._run_generate_config,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=(0, 6))
        self.ttk.Label(
            post_frame,
            text="Tip: tick Apply (top toolbar) to write the updated INIs.",
            foreground=_FG_DIM,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=(0, 6))

        # ── Step 6 — Repath a PCLauncher system ──────────────────────────────
        repath_frame = self.ttk.LabelFrame(
            frame, text="Step 6 — Re-prefix game paths after a drive change",
        )
        repath_frame.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        repath_frame.columnconfigure(1, weight=1)
        self.ttk.Label(
            repath_frame,
            text=(
                "For systems like Taito Type X whose games moved to a new drive "
                "without a full SpinDoctor migration. Rewrites Application= in the "
                "system's PCLauncher INI and Rom_Path= in its Emulators.ini. "
                "Only those two values change — FadeTitle=, AppWaitExe=, ExitMethod=, "
                "and all other per-game keys are left exactly as configured. "
                "CLI: spindoctor repath-system <System> --rom-path <NewPath> --apply"
            ),
            wraplength=800, justify="left", foreground=_FG_DIM,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 4))

        self.ttk.Label(repath_frame, text="System").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._repath_system_var = self.tk.StringVar()
        self._repath_system_combo = self.ttk.Combobox(
            repath_frame, textvariable=self._repath_system_var,
            state="readonly", width=28,
        )
        self._repath_system_combo.grid(row=1, column=1, sticky="w", padx=6, pady=2)

        self.ttk.Label(repath_frame, text="New game folder").grid(
            row=2, column=0, sticky="w", padx=6, pady=2,
        )
        self._repath_path_var = self.tk.StringVar()
        self.ttk.Entry(
            repath_frame, textvariable=self._repath_path_var, width=60,
        ).grid(row=2, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            repath_frame, text="Browse…",
            command=self._browse_repath_path,
        ).grid(row=2, column=2, sticky="w", pady=2)

        repath_btn_row = self.ttk.Frame(repath_frame)
        repath_btn_row.grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            repath_btn_row, text="Preview",
            command=lambda: self._run_repath_system(apply=False),
        ).pack(side="left")
        self.ttk.Button(
            repath_btn_row, text="Apply",
            command=lambda: self._run_repath_system(apply=True),
        ).pack(side="left", padx=6)

        frame.columnconfigure(1, weight=1)
        return frame

    def _selected_migrate_components(self) -> Optional[str]:
        """Return a comma-separated `--include` value, or None for "all"."""
        selected = [k for k, v in self._migrate_component_vars.items() if v.get()]
        if not selected:
            return ""
        if len(selected) == len(_MIGRATE_COMPONENTS):
            return None
        return ",".join(selected)

    def _run_migrate(self) -> None:
        target = self._migrate_target_var.get().strip()
        if not target:
            self.messagebox.showwarning(
                "Target root required",
                "Pick the destination root folder before running migrate.",
            )
            return
        include = self._selected_migrate_components()
        if include == "":
            self.messagebox.showwarning(
                "No components selected",
                "Tick at least one component to migrate.",
            )
            return
        args = ["migrate", "--target", target]
        if include is not None:
            args += ["--include", include]
        selected_indices = self._migrate_systems_lb.curselection()
        if selected_indices:
            systems = ",".join(
                self._migrate_systems_lb.get(i).removesuffix(_NOT_IN_WHEEL_SUFFIX)
                for i in selected_indices
            )
            args += ["--systems", systems]
        if self._migrate_keep_source_var.get():
            args.append("--keep-source")
        if self._migrate_verify_var.get():
            args.append("--verify")
        if self._migrate_no_update_config_var.get():
            args.append("--no-update-config")
        if self._migrate_preserve_names_var.get():
            args.append("--preserve-names")
        if self._global_apply_var.get():
            keep_source = self._migrate_keep_source_var.get()
            if keep_source:
                msg = (
                    f"Migrate library to:\n{target}\n\n"
                    "This will copy the selected components to the new "
                    "drive. The originals stay in place. "
                    "Reversible by deleting the destination copy.\n\n"
                    "Continue?"
                )
            else:
                msg = (
                    f"Migrate library to:\n{target}\n\n"
                    "This will MOVE the selected components — the "
                    "originals will be removed from their current "
                    "location, and config paths will be updated to "
                    "point at the new drive.\n\n"
                    "Reversible only via the matching undo manifest "
                    "(Logs → Browse manifests… → Undo, or "
                    "`spindoctor migrate --undo`).\n\n"
                    "Continue?"
                )
            if not self.messagebox.askyesno("Migrate library?", msg):
                return
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_migrate_undo(self) -> None:
        manifest = self._migrate_undo_var.get().strip()
        if not manifest:
            self.messagebox.showwarning(
                "Manifest required",
                "Select a manifest or type 'latest' before running Undo.",
            )
            return
        args = ["migrate", "--undo", manifest]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_pre_migrate_backup(self) -> None:
        target = self._pre_migrate_backup_var.get().strip()
        if not target:
            self.messagebox.showwarning(
                "Backup folder required",
                "Enter or browse to a backup target folder before creating a backup.",
            )
            return
        args = ["backup", "create", "--target", target]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_repath_system(self, apply: bool = False) -> None:
        system = self._repath_system_var.get().strip()
        new_path = self._repath_path_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required", "Select a system before re-pathing.",
            )
            return
        if not new_path:
            self.messagebox.showwarning(
                "New game folder required",
                "Enter the new absolute path to the system's game folder.",
            )
            return
        args = ["repath-system", system, "--rom-path", new_path]
        if apply:
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _browse_repath_path(self) -> None:
        path = self.filedialog.askdirectory(title="Select new game folder for this system")
        if path:
            self._repath_path_var.set(str(Path(path)))

    def _refresh_migrate_manifests(self) -> None:
        """Populate the undo Combobox with manifests from the migrations dir."""
        from .config import CONFIG_DIR
        migrations_dir = CONFIG_DIR / "migrations"
        manifests = sorted(migrations_dir.glob("migrate-*.json"), reverse=True)
        names = ["latest"] + [p.name for p in manifests]
        self._migrate_undo_combo["values"] = names
        if not self._migrate_undo_var.get():
            self._migrate_undo_var.set("latest")

    def _on_games_system_change(self) -> None:
        """Shared system picker on the Games tab changed.

        Cascades to all four steps: clears the game-wheel table so stale
        entries from the previous system don't linger, and refreshes both
        the rename/clone and fix-exe game dropdowns for the new system.
        """
        self._gwm_on_system_change()
        self._refresh_rename_games()
        self._refresh_fixexe_games()

    def _build_games_tab(self, parent):  # noqa: PLR0915
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Manage games within any HyperSpin system. Pick a system "
                  "from the dropdown below and all four steps operate on that "
                  "selection — no need to re-pick the system in each section. "
                  "Step 1 loads the game list and lets you reorder or remove "
                  "entries. Step 2 renames or clones a game. Step 3 adds "
                  "newly-installed PC games. Step 4 fixes a game that launches "
                  "the wrong executable."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 6))

        # ── Shared system picker ──────────────────────────────────────────────
        picker_lf = self.ttk.LabelFrame(frame, text="System")
        picker_lf.pack(fill="x", pady=(0, 10))

        picker_row = self.ttk.Frame(picker_lf)
        picker_row.pack(fill="x", padx=6, pady=6)
        self.ttk.Label(picker_row, text="System:").pack(side="left")

        self._games_system_var = self.tk.StringVar()
        # Aliases so every existing handler reads the same StringVar without
        # needing individual changes — one picker drives all four steps.
        self._gwm_system_var = self._games_system_var
        self._rename_system_var = self._games_system_var
        self._fixexe_system_var = self._games_system_var
        self._systems_old_var = self._games_system_var

        self._games_system_combo = self.ttk.Combobox(
            picker_row, textvariable=self._games_system_var,
            state="readonly", width=34,
        )
        self._games_system_combo.pack(side="left", padx=8)
        self._games_system_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_games_system_change(),
        )
        self.ttk.Label(
            picker_row,
            text="Select a system here — Steps 1–4 below all operate on this system.",
            foreground=_FG_DIM,
        ).pack(side="left", padx=(4, 0))

        # ── Step 1 — Manage the game wheel ───────────────────────────────────
        self._gwm_data: list[dict] = []
        self._gwm_loaded_system: str = ""

        gwm_lf = self.ttk.LabelFrame(
            frame, text="Step 1 — Manage the game wheel",
        )
        gwm_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            gwm_lf,
            text=("Load the game list for the selected system, then reorder "
                  "or remove entries. All changes are held in memory — you can "
                  "reorder freely and only write to disk when you click Save "
                  "Order. Removing a game only removes it from the wheel "
                  "database (XML); ROM and media files are not deleted unless "
                  "you tick 'Also remove PCLauncher INI' (PC systems)."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 2))
        self.ttk.Label(
            gwm_lf,
            text="Tip: select a row and use Alt+Up / Alt+Down to nudge without leaving the keyboard.",
            foreground=_FG_DIMMER,
        ).pack(anchor="w", padx=6, pady=(0, 4))

        gwm_load_row = self.ttk.Frame(gwm_lf)
        gwm_load_row.pack(fill="x", padx=6, pady=(0, 4))
        self.ttk.Button(
            gwm_load_row, text="Load Games",
            command=self._gwm_load,
        ).pack(side="left")
        self._gwm_count_label = self.ttk.Label(
            gwm_load_row, text="", foreground=_FG_DIM,
        )
        self._gwm_count_label.pack(side="left", padx=8)

        gwm_tree_frame = self.ttk.Frame(gwm_lf)
        gwm_tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        gwm_tree_frame.columnconfigure(0, weight=1)
        gwm_tree_frame.rowconfigure(0, weight=1)

        self._gwm_tree = self.ttk.Treeview(
            gwm_tree_frame,
            columns=("pos", "name", "desc"),
            show="headings",
            selectmode="browse",
            height=14,
        )
        self._gwm_tree.heading("pos",  text="#",             anchor="center")
        self._gwm_tree.heading("name", text="ROM Name",      anchor="w")
        self._gwm_tree.heading("desc", text="Display Title", anchor="w")
        self._gwm_tree.column("pos",  width=50,  stretch=False, anchor="center")
        self._gwm_tree.column("name", width=280, stretch=True,  anchor="w")
        self._gwm_tree.column("desc", width=320, stretch=True,  anchor="w")

        gwm_vsb = self.ttk.Scrollbar(
            gwm_tree_frame, orient="vertical", command=self._gwm_tree.yview,
        )
        self._gwm_tree.configure(yscrollcommand=gwm_vsb.set)
        self._gwm_tree.grid(row=0, column=0, sticky="nsew")
        gwm_vsb.grid(row=0, column=1, sticky="ns")
        self._gwm_tree.bind("<Alt-Up>",   lambda e: self._gwm_move_up())
        self._gwm_tree.bind("<Alt-Down>", lambda e: self._gwm_move_down())

        # Reorder controls + sort buttons on one row to reduce visual noise.
        gwm_reorder_row = self.ttk.Frame(gwm_lf)
        gwm_reorder_row.pack(anchor="w", padx=6, pady=(4, 2))
        self.ttk.Button(
            gwm_reorder_row, text="Move Up",   command=self._gwm_move_up,
        ).pack(side="left")
        self.ttk.Button(
            gwm_reorder_row, text="Move Down", command=self._gwm_move_down,
        ).pack(side="left", padx=(4, 0))
        self._gwm_goto_var = self.tk.StringVar()
        self.ttk.Label(gwm_reorder_row, text="Jump to #").pack(
            side="left", padx=(10, 2),
        )
        self.ttk.Entry(
            gwm_reorder_row, textvariable=self._gwm_goto_var, width=5,
        ).pack(side="left", padx=(0, 2))
        self.ttk.Button(
            gwm_reorder_row, text="Go", command=self._gwm_move_to_pos,
        ).pack(side="left", padx=(0, 14))
        self.ttk.Button(
            gwm_reorder_row, text="Sort A→Z (by title)",
            command=lambda: self._gwm_sort("description"),
        ).pack(side="left", padx=(0, 4))
        self.ttk.Button(
            gwm_reorder_row, text="Sort A→Z (by ROM name)",
            command=lambda: self._gwm_sort("name"),
        ).pack(side="left")

        # Remove + save on a separate row so destructive/commit buttons
        # are visually separated from the reorder controls.
        gwm_action_row = self.ttk.Frame(gwm_lf)
        gwm_action_row.pack(anchor="w", padx=6, pady=(2, 8))
        self.ttk.Button(
            gwm_action_row, text="Remove Game", command=self._gwm_remove,
        ).pack(side="left")
        self._gwm_remove_pclauncher_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            gwm_action_row,
            text="Also remove PCLauncher INI (PC systems only)",
            variable=self._gwm_remove_pclauncher_var,
        ).pack(side="left", padx=(6, 16))
        self.ttk.Button(
            gwm_action_row, text="Save Order", command=self._gwm_save_order,
        ).pack(side="left")
        self.ttk.Label(
            gwm_action_row,
            text=" — commits the current table order to the wheel XML",
            foreground=_FG_DIM,
        ).pack(side="left", padx=(2, 0))

        # ── Step 2 — Rename or clone a game ──────────────────────────────────
        rc_lf = self.ttk.LabelFrame(frame, text="Step 2 — Rename or clone a game")
        rc_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            rc_lf,
            text=("Rename moves the ROM file, database entry, and every media "
                  "file in one operation and writes an undo manifest so the "
                  "change is reversible. Clone duplicates everything under a "
                  "new name — useful for keeping a speed-hack alongside the "
                  "clean dump, or creating a multi-language variant."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 2))
        self.ttk.Label(
            rc_lf,
            text="Tip: both operations are dry-run until you tick Apply at the top of the window.",
            foreground=_FG_DIMMER,
        ).pack(anchor="w", padx=6, pady=(0, 4))

        rc_row = self.ttk.Frame(rc_lf)
        rc_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(rc_row, text="Game").pack(side="left")
        self._rename_game_var = self.tk.StringVar()
        self._rename_game_combo = self.ttk.Combobox(
            rc_row, textvariable=self._rename_game_var,
            state="readonly", width=34,
        )
        self._rename_game_combo.pack(side="left", padx=6)
        self.ttk.Button(
            rc_row, text="↻", width=3,
            command=self._refresh_rename_games,
        ).pack(side="left")
        self.ttk.Label(rc_row, text="→ New name").pack(
            side="left", padx=(10, 0),
        )
        self._rename_to_var = self.tk.StringVar()
        self.ttk.Entry(
            rc_row, textvariable=self._rename_to_var, width=26,
        ).pack(side="left", padx=6, fill="x", expand=True)

        rc_btns = self.ttk.Frame(rc_lf)
        rc_btns.pack(anchor="w", padx=6, pady=(4, 8))
        self.ttk.Button(
            rc_btns, text="Rename Game",
            command=lambda: self._run_rename_or_clone("rename"),
        ).pack(side="left")
        self.ttk.Button(
            rc_btns, text="Clone Game",
            command=lambda: self._run_rename_or_clone("clone"),
        ).pack(side="left", padx=6)

        # ── Step 3 — Add new PC games / refresh ──────────────────────────────
        pc_lf = self.ttk.LabelFrame(
            frame, text="Step 3 — Add new PC games / refresh the wheel",
        )
        pc_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            pc_lf,
            text=("For PC / Windows / Steam systems only. Scans every install "
                  "folder inside <roms_dir>/<system>/ and adds any new games "
                  "to the HyperSpin wheel database — one entry per folder, "
                  "junk shortcuts silently ignored. Also writes PCLauncher INIs "
                  "for new entries so RocketLauncher can launch them. Run this "
                  "after installing a game to the PC Games folder."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 2))
        self.ttk.Label(
            pc_lf,
            text=("Not needed for MAME, SNES, or other ROM-based systems — "
                  "use Diagnostics → Audit or Metadata & Media → "
                  "Sync DB to ROMs for those."),
            wraplength=860, justify="left", foreground=_FG_DIMMER,
        ).pack(anchor="w", padx=6, pady=(0, 4))

        self.ttk.Label(
            pc_lf,
            text=("Overwrite mode rewrites every existing INI, including ones with a "
                  "stale executable path (wrong drive, renamed file). Use after a drive "
                  "migration or when a game launches the wrong executable. Leave unticked "
                  "for a normal scan that only adds missing entries."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 0))
        self._pc_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            pc_lf,
            text="Overwrite existing PCLauncher INIs (--overwrite-pclauncher)",
            variable=self._pc_overwrite_var,
        ).pack(anchor="w", padx=6, pady=(2, 2))

        pc_btns = self.ttk.Frame(pc_lf)
        pc_btns.pack(anchor="w", padx=6, pady=(4, 8))
        self.ttk.Button(
            pc_btns, text="Scan & add new games",
            command=self._run_pc_rename,
        ).pack(side="left")
        self.ttk.Label(
            pc_btns,
            text="Run dry-run first (Apply unticked) to preview what will be added.",
            foreground=_FG_DIM,
        ).pack(side="left", padx=10)

        # ── Step 4 — Fix a game's executable ─────────────────────────────────
        fixexe_lf = self.ttk.LabelFrame(
            frame, text="Step 4 — Fix a game that launches the wrong executable",
        )
        fixexe_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            fixexe_lf,
            text=("Fix a PC game that launches the wrong file — uninstaller, "
                  "GOG/Steam cache file, NW.js runtime, etc. SpinDoctor scans "
                  "the game folder and ranks candidates: real executables first "
                  "(shallower paths ranked above deeper ones), then .ahk scripts, "
                  "then .bat files, then known junk at the bottom. Pick the correct "
                  "one and click Apply to update the PCLauncher INI. Other keys in "
                  "the INI (FadeTitle, AppWaitExe, etc.) are left untouched."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 2))
        self.ttk.Label(
            fixexe_lf,
            text=("Works for any PCLauncher-backed system — not just PC Games. "
                  "Change the system picker above to target Taito Type X or any "
                  "other arcade-PC system."),
            wraplength=860, justify="left", foreground=_FG_DIMMER,
        ).pack(anchor="w", padx=6, pady=(0, 4))

        fixexe_game_row = self.ttk.Frame(fixexe_lf)
        fixexe_game_row.pack(fill="x", padx=6, pady=(0, 4))
        self.ttk.Label(fixexe_game_row, text="Game").pack(side="left")
        self._fixexe_game_var = self.tk.StringVar()
        self._fixexe_game_combo = self.ttk.Combobox(
            fixexe_game_row, textvariable=self._fixexe_game_var,
            state="readonly", width=36,
        )
        self._fixexe_game_combo.pack(side="left", padx=6)
        self._fixexe_game_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._fixexe_load_candidates(),
        )
        self.ttk.Button(
            fixexe_game_row, text="↻", width=3,
            command=self._refresh_fixexe_games,
        ).pack(side="left")

        self.ttk.Label(
            fixexe_lf,
            text="Candidates in game folder and subfolders (ranked — real .exe files first):",
        ).pack(anchor="w", padx=6, pady=(4, 0))
        fixexe_lb_frame = self.ttk.Frame(fixexe_lf)
        fixexe_lb_frame.pack(fill="x", padx=6, pady=(2, 4))
        self._fixexe_listbox = self.tk.Listbox(
            fixexe_lb_frame, height=5, selectmode="single",
            activestyle="none",
        )
        fixexe_lb_vsb = self.ttk.Scrollbar(
            fixexe_lb_frame, orient="vertical",
            command=self._fixexe_listbox.yview,
        )
        self._fixexe_listbox.configure(yscrollcommand=fixexe_lb_vsb.set)
        self._fixexe_listbox.pack(side="left", fill="both", expand=True)
        fixexe_lb_vsb.pack(side="right", fill="y")
        self._fixexe_listbox.bind(
            "<<ListboxSelect>>", lambda _e: self._fixexe_on_select(),
        )

        fixexe_path_row = self.ttk.Frame(fixexe_lf)
        fixexe_path_row.pack(fill="x", padx=6, pady=(0, 4))
        self.ttk.Label(fixexe_path_row, text="Executable path:").pack(side="left")
        self._fixexe_path_var = self.tk.StringVar()
        self.ttk.Entry(
            fixexe_path_row, textvariable=self._fixexe_path_var, width=55,
        ).pack(side="left", padx=6, fill="x", expand=True)
        self.ttk.Button(
            fixexe_path_row, text="Browse…",
            command=self._fixexe_browse,
        ).pack(side="left", padx=(0, 2))

        fixexe_btns = self.ttk.Frame(fixexe_lf)
        fixexe_btns.pack(anchor="w", padx=6, pady=(0, 8))
        self.ttk.Button(
            fixexe_btns, text="Apply fix",
            command=self._run_fixexe,
        ).pack(side="left")
        self.ttk.Label(
            fixexe_btns,
            text="Updates Application= and WorkingFolder= in the PCLauncher INI.",
            foreground=_FG_DIM,
        ).pack(side="left", padx=10)

        return frame

    # ── Main Menu tab (LEGACY — content merged into _build_systems_tab) ─────────

    def _build_mainmenu_tab(self, parent):  # LEGACY — content merged into _build_systems_tab
        # All I/O on Main Menu.xml goes through spindoctor.mainmenu —
        # the same module the CLI uses. The GUI never parses or writes
        # the XML itself; that would be a parallel implementation and
        # is exactly what caused the previous Main Menu corruption bug.
        self._mm_data: list[dict] = []  # [{system, enabled}]

        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Edit the order and visibility of systems on HyperSpin's "
                  "top-level wheel (Main Menu.xml). Click Refresh to load "
                  "the current order, drag-select a row then use Move Up / "
                  "Move Down (or Alt+Up / Alt+Down) to reposition it one "
                  "step at a time, or type a position number and press Go to "
                  "jump directly. Toggle Visible to hide/unhide, then Save "
                  "Order to write all changes at once."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        # ── Treeview ─────────────────────────────────────────────────────────
        tree_frame = self.ttk.Frame(frame)
        tree_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._mm_tree = self.ttk.Treeview(
            tree_frame,
            columns=("pos", "system", "visible"),
            show="headings",
            selectmode="browse",
            height=16,
        )
        self._mm_tree.heading("pos",     text="#",       anchor="center")
        self._mm_tree.heading("system",  text="System",  anchor="w")
        self._mm_tree.heading("visible", text="Visible", anchor="center")
        self._mm_tree.column("pos",     width=50,  stretch=False, anchor="center")
        self._mm_tree.column("system",  width=340, stretch=True,  anchor="w")
        self._mm_tree.column("visible", width=80,  stretch=False, anchor="center")
        self._mm_tree.tag_configure("hidden", foreground=_FG_DIMMER)

        vsb = self.ttk.Scrollbar(tree_frame, orient="vertical",
                                 command=self._mm_tree.yview)
        self._mm_tree.configure(yscrollcommand=vsb.set)
        self._mm_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._mm_tree.bind("<Alt-Up>",   lambda e: self._mm_move_up())
        self._mm_tree.bind("<Alt-Down>", lambda e: self._mm_move_down())

        # ── Table action buttons ──────────────────────────────────────────────
        tbl_btn_row = self.ttk.Frame(frame)
        tbl_btn_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 8))
        self.ttk.Button(
            tbl_btn_row, text="Refresh",
            command=self._mm_refresh,
        ).pack(side="left")
        self.ttk.Button(
            tbl_btn_row, text="Move Up",
            command=self._mm_move_up,
        ).pack(side="left", padx=(6, 2))
        self.ttk.Button(
            tbl_btn_row, text="Move Down",
            command=self._mm_move_down,
        ).pack(side="left", padx=2)
        self._mm_goto_var = self.tk.StringVar()
        self.ttk.Label(tbl_btn_row, text="Move to #").pack(side="left", padx=(8, 2))
        self.ttk.Entry(tbl_btn_row, textvariable=self._mm_goto_var, width=4).pack(side="left")
        self.ttk.Button(
            tbl_btn_row, text="Go",
            command=self._mm_move_to_pos,
        ).pack(side="left", padx=(2, 0))
        self.ttk.Button(
            tbl_btn_row, text="Toggle Visible",
            command=self._mm_toggle_visible,
        ).pack(side="left", padx=(6, 2))
        self.ttk.Button(
            tbl_btn_row, text="Save Order",
            command=self._mm_save_order,
        ).pack(side="left", padx=(20, 0))
        # Restore from sidecar backup — surfaces the .YYYYMMDD_HHMMSS.bak
        # files SpinDoctor writes before every Save Order so the user
        # can recover from a bad edit without leaving the GUI. Shells
        # out to ``spindoctor backup sidecar`` so the file I/O lives in
        # one place (CLI / shared library), not duplicated in the GUI.
        self.ttk.Button(
            tbl_btn_row, text="Restore from backup…",
            command=self._mm_restore_from_backup,
        ).pack(side="left", padx=(6, 0))

        # ── Sort ─────────────────────────────────────────────────────────────
        sort_frame = self.ttk.LabelFrame(frame, text="Sort all systems")
        sort_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.ttk.Label(sort_frame, text="Strategy").grid(
            row=0, column=0, sticky="w", padx=6, pady=4,
        )
        self._mainmenu_sort_var = self.tk.StringVar(value="alpha")
        self.ttk.Combobox(
            sort_frame, textvariable=self._mainmenu_sort_var,
            values=["alpha", "manufacturer", "year"],
            state="readonly", width=14,
        ).grid(row=0, column=1, sticky="w", padx=4)
        self.ttk.Button(
            sort_frame, text="Sort", command=self._run_mainmenu_sort,
        ).grid(row=0, column=2, sticky="w", padx=4, pady=4)

        # ── Add / Remove ─────────────────────────────────────────────────────
        mgmt_frame = self.ttk.LabelFrame(frame, text="Add / Remove system")
        mgmt_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        mgmt_frame.columnconfigure(1, weight=1)

        self.ttk.Label(mgmt_frame, text="System").grid(
            row=0, column=0, sticky="w", padx=6, pady=4,
        )
        self._mainmenu_system_var = self.tk.StringVar()
        self._mainmenu_system_combo = self.ttk.Combobox(
            mgmt_frame, textvariable=self._mainmenu_system_var,
            state="readonly", width=40,
        )
        self._mainmenu_system_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        mgmt_btn_row = self.ttk.Frame(mgmt_frame)
        mgmt_btn_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))
        for label, sub in (("Add", "add"), ("Remove", "remove")):
            self.ttk.Button(
                mgmt_btn_row, text=label,
                command=lambda s=sub: self._run_mainmenu_action(s),
            ).pack(side="left", padx=2)

        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        # Defer the XML parse + tree population until the rest of the
        # GUI has painted. Doing it inline used to delay first-paint by
        # 1–3 seconds on slow drives (HyperSpin's Main Menu.xml lives on
        # the cabinet's storage drive, not a fast local disk).
        self.root.after_idle(self._mm_refresh)
        return frame

    # ── Main Menu table helpers ───────────────────────────────────────────────

    def _mm_xml_path(self):
        """Return the Path to Main Menu.xml, or None if hyperspin_dir unset."""
        cfg = load_config()
        hdir = (cfg.hyperspin_dir or "").strip()
        if not hdir:
            return None
        from pathlib import Path as _Path
        return _Path(hdir) / "Databases" / "Main Menu" / "Main Menu.xml"

    def _mm_refresh(self) -> None:
        """Re-read Main Menu.xml via :mod:`spindoctor.mainmenu`.

        Going through the shared module (rather than parsing the XML
        in-process) ensures the GUI sees the file the same way the CLI
        does — there's only one reader, so the GUI can't disagree with
        ``spindoctor mainmenu`` about whether a system is hidden, which
        previously corrupted Main Menu.xml on save.
        """
        xml_path = self._mm_xml_path()
        if xml_path is None:
            self._mm_data = []
            self._mm_repopulate_tree()
            self._append_output(
                "Main Menu: HyperSpin directory not configured — "
                "set it in the Setup tab first.\n"
            )
            return
        if not xml_path.exists():
            self._mm_data = []
            self._mm_repopulate_tree()
            self._append_output(f"Main Menu.xml not found: {xml_path}\n")
            return
        try:
            from . import mainmenu as _mm_mod
            cfg = load_config()
            menu = _mm_mod.load_main_menu(cfg)
        except Exception as exc:  # noqa: BLE001 — surface every parse error
            # Reset to an empty Treeview so the user doesn't see stale
            # rows from the last successful load, then surface the error
            # in BOTH a modal dialog (so they actually notice) and the
            # Output pane (so the message is grep-able from the log).
            self._mm_data = []
            self._mm_repopulate_tree()
            self._append_output(
                f"Error reading Main Menu.xml: {exc}\n"
                f"  Path: {xml_path}\n"
            )
            self.messagebox.showerror(
                "Main Menu.xml could not be parsed",
                f"Could not read Main Menu.xml:\n  {xml_path}\n\n"
                f"{exc}\n\n"
                "Common causes: the file is open in another editor, the "
                "XML is malformed (re-save it from HyperHQ if so), or the "
                "file was truncated mid-write. The Output pane has the "
                "raw error if you need to share it.",
            )
            return
        self._mm_data = [
            {"system": entry.system, "enabled": entry.enabled or "Yes"}
            for entry in menu.entries
        ]
        self._mm_repopulate_tree()
        self._append_output(
            f"Main Menu loaded: {len(self._mm_data)} system(s) from {xml_path}\n"
        )

    def _mm_repopulate_tree(self) -> None:
        self._mm_tree.delete(*self._mm_tree.get_children())
        for i, entry in enumerate(self._mm_data, start=1):
            visible = "Yes" if entry["enabled"].strip().lower() != "no" else "No"
            tag = "hidden" if visible == "No" else ""
            self._mm_tree.insert(
                "", "end", iid=str(i),
                values=(i, entry["system"], visible),
                tags=(tag,),
            )

    def _mm_selected_index(self) -> int:
        """Return 0-based index of the selected row, or -1 if nothing selected."""
        sel = self._mm_tree.selection()
        if not sel:
            return -1
        values = self._mm_tree.item(sel[0], "values")
        return int(values[0]) - 1  # values[0] is 1-based position

    def _mm_move_up(self) -> None:
        idx = self._mm_selected_index()
        if idx < 0:
            self._set_status("Select a row in the table first.")
            return
        if idx == 0:
            self._set_status("Already at the top.")
            return
        self._mm_data[idx], self._mm_data[idx - 1] = (
            self._mm_data[idx - 1], self._mm_data[idx]
        )
        self._mm_repopulate_tree()
        new_iid = str(idx)       # item is now at 1-based position idx
        self._mm_tree.selection_set(new_iid)
        self._mm_tree.see(new_iid)

    def _mm_move_down(self) -> None:
        idx = self._mm_selected_index()
        if idx < 0:
            self._set_status("Select a row in the table first.")
            return
        if idx >= len(self._mm_data) - 1:
            self._set_status("Already at the bottom.")
            return
        self._mm_data[idx], self._mm_data[idx + 1] = (
            self._mm_data[idx + 1], self._mm_data[idx]
        )
        self._mm_repopulate_tree()
        new_iid = str(idx + 2)   # item is now at 1-based position idx+2
        self._mm_tree.selection_set(new_iid)
        self._mm_tree.see(new_iid)

    def _mm_move_to_pos(self) -> None:
        idx = self._mm_selected_index()
        if idx < 0:
            self._set_status("Select a row in the table first.")
            return
        raw = self._mm_goto_var.get().strip()
        try:
            target = int(raw)
        except ValueError:
            self._set_status("Enter a valid position number.")
            return
        total = len(self._mm_data)
        if not 1 <= target <= total:
            self._set_status(f"Position must be between 1 and {total}.")
            return
        target_idx = target - 1
        if target_idx == idx:
            return
        item = self._mm_data.pop(idx)
        self._mm_data.insert(target_idx, item)
        self._mm_repopulate_tree()
        iid = str(target)
        self._mm_tree.selection_set(iid)
        self._mm_tree.see(iid)

    def _mm_toggle_visible(self) -> None:
        idx = self._mm_selected_index()
        if idx < 0:
            self._set_status("Select a row in the table first.")
            return
        current = self._mm_data[idx]["enabled"].strip().lower()
        self._mm_data[idx]["enabled"] = "No" if current != "no" else "Yes"
        self._mm_repopulate_tree()
        iid = str(idx + 1)
        self._mm_tree.selection_set(iid)
        self._mm_tree.see(iid)

    def _mm_save_order(self) -> None:
        """Persist the table's current order + visibility via
        :func:`spindoctor.mainmenu.save_main_menu`.

        Single canonical writer (the one the CLI uses) handles backup,
        XML declaration, lxml comment preservation, and the legacy
        ``enabled``-attribute self-heal in
        :func:`spindoctor.database._update_game_element`. The GUI just
        composes the desired :class:`MainMenu` state and hands it off.
        """
        xml_path = self._mm_xml_path()
        if xml_path is None or not xml_path.exists():
            self.messagebox.showerror(
                "Cannot save",
                "Main Menu.xml not found. Refresh the tab after configuring "
                "HyperSpin directory in Setup.",
            )
            return
        if not self._mm_data:
            self.messagebox.showwarning("Nothing to save", "No systems loaded.")
            return
        if not self.messagebox.askyesno(
            "Save Main Menu order",
            f"This will overwrite {xml_path.name} with the current table order "
            "and visibility settings.\n\nContinue?",
        ):
            return
        # Snapshot the table data BEFORE leaving the main thread — Tk
        # vars can't be touched from a worker. Order matters: the new
        # ``entries`` list mirrors this list.
        data_snapshot = [dict(entry) for entry in self._mm_data]
        self._set_status(f"Saving {xml_path.name}…")

        record = _RunRecord(
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            argv_str=f"mainmenu save-order → {xml_path.name}",
            dry_run=False,
        )
        record.append(f"$ mainmenu save-order\n  target: {xml_path}\n")
        self._run_history.append(record)
        self._refresh_logs_tab()

        def _worker():
            try:
                from . import mainmenu as _mm_mod
                cfg = load_config()
                # Load fresh inside the worker so we get the full
                # metadata (description / manufacturer / year / genre)
                # for every entry — not just the {system, enabled} the
                # GUI table tracks. Without this round-trip the saved
                # file would drop those fields.
                menu = _mm_mod.load_main_menu(cfg)
                by_name = {e.system: e for e in menu.entries}
                new_entries = []
                for row in data_snapshot:
                    name = row["system"]
                    entry = by_name.get(name)
                    if entry is None:
                        continue
                    entry.enabled = (row.get("enabled") or "Yes").strip() or "Yes"
                    new_entries.append(entry)
                menu.entries = new_entries
                saved_path = _mm_mod.save_main_menu(menu, cfg)
            except OSError as exc:
                # OSError (file in use, disk full, etc.) — humanize for
                # the user rather than dumping the bare repr. Most
                # frequent cause is HyperSpin holding Main Menu.xml open.
                from ._errors import humanize_oserror
                self.root.after(
                    0, self._mm_save_failed, record,
                    humanize_oserror(exc, action="save Main Menu.xml"),
                )
                return
            except Exception as exc:  # noqa: BLE001 - report to UI thread
                self.root.after(0, self._mm_save_failed, record, str(exc))
                return
            self.root.after(0, self._mm_save_succeeded, record, saved_path)

        threading.Thread(target=_worker, daemon=True).start()

    def _mm_save_succeeded(self, record: "_RunRecord", xml_path) -> None:
        record.append(f"Main Menu order saved to {xml_path}\n")
        record.exit_code = 0
        self._append_output(f"Main Menu order saved to {xml_path}\n")
        self._flash_status(f"Saved {xml_path.name}.")
        self._refresh_logs_tab()

    def _mm_save_failed(self, record: "_RunRecord", msg: str) -> None:
        record.append(f"ERROR: {msg}\n")
        record.exit_code = 1
        self._set_status("Save failed.")
        self._refresh_logs_tab()
        self.messagebox.showerror("Save failed", msg)

    def _restore_sidecar(
        self,
        target: "Path",
        *,
        no_backups_hint: str = "",
        on_complete=None,
    ) -> None:
        """List .bak sidecars for *target* via CLI, let user pick, then restore.

        Shells out to ``spindoctor backup sidecar list --json`` and
        ``spindoctor backup sidecar restore --apply`` so all file I/O
        stays in the CLI — no drift between GUI and CLI paths.
        """
        try:
            argv = resolve_cli_command("spindoctor") + [
                "backup", "sidecar", "list", str(target), "--json",
            ]
            proc = subprocess.run(
                argv,
                check=True, capture_output=True, text=True,
                timeout=30,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.messagebox.showerror(
                "Could not list backups",
                f"Failed to enumerate backups via "
                f"`spindoctor backup sidecar list`:\n\n{exc}",
            )
            return
        try:
            backups = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            self.messagebox.showerror(
                "Could not list backups",
                f"`spindoctor backup sidecar list --json` produced "
                f"unparseable output:\n\n{exc}\n\n{proc.stdout!r}",
            )
            return
        if not backups:
            msg = no_backups_hint or (
                f"No .YYYYMMDD_HHMMSS.bak sidecars exist next to "
                f"{target.name}.\n\nSpinDoctor writes one before every "
                f"in-place write when config.backup_before_modify is on "
                f"(the default)."
            )
            self.messagebox.showinfo("No backups found", msg)
            return
        chosen = self._ask_pick_sidecar(target.name, backups)
        if chosen is None:
            return
        if not self.messagebox.askyesno(
            "Confirm restore",
            f"Replace {target.name} with the contents of "
            f"{Path(chosen).name}?\n\nThe current file will itself be "
            f"backed up as a new .YYYYMMDD_HHMMSS.bak first, so this "
            f"action is undoable via the same Restore button.",
        ):
            return
        args = ["backup", "sidecar", "restore", str(target), "--from", str(chosen)]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args, on_complete=on_complete)

    def _mm_restore_from_backup(self) -> None:
        """Pick a sidecar ``.YYYYMMDD_HHMMSS.bak`` of Main Menu.xml and restore it."""
        xml_path = self._mm_xml_path()
        if xml_path is None:
            self.messagebox.showerror(
                "Cannot restore",
                "HyperSpin directory is not configured — set it in the "
                "Setup tab first.",
            )
            return
        self._restore_sidecar(
            xml_path,
            no_backups_hint=(
                f"No .YYYYMMDD_HHMMSS.bak sidecars exist next to "
                f"{xml_path.name}.\n\nSpinDoctor writes one before every "
                f"Save Order when config.backup_before_modify is on "
                f"(the default)."
            ),
            on_complete=self._mm_restore_done,
        )

    def _mm_restore_done(self, rc: int) -> None:
        if rc == 0:
            self._mm_refresh()
            self._flash_status("Main Menu.xml restored from backup.")
        # Non-zero rc — _on_proc_done already showed the error in
        # status + output; no extra dialog needed.

    def _ask_pick_sidecar(self, file_name: str, backups: list[dict]) -> Optional[str]:
        """Modal listing the available sidecar backups; returns chosen path."""
        win = self.tk.Toplevel(self.root)
        win.title(f"Restore {file_name} from backup")
        win.transient(self.root)
        win.grab_set()
        self._fit_geometry(win, 720, 320)

        self.ttk.Label(
            win,
            text=(f"Pick a backup of {file_name} to restore. Newest "
                  f"first. The current file will be saved as a fresh "
                  f"sidecar first so you can re-restore it if needed."),
            wraplength=680, justify="left", padding=(10, 8),
        ).pack(fill="x")

        list_frame = self.ttk.Frame(win, padding=(10, 4))
        list_frame.pack(fill="both", expand=True)
        tree = self.ttk.Treeview(
            list_frame, columns=("when", "size"),
            show="tree headings", selectmode="browse",
        )
        tree.heading("#0", text="File")
        tree.heading("when", text="Modified")
        tree.heading("size", text="Size")
        tree.column("#0", width=380, stretch=True)
        tree.column("when", width=180, stretch=False, anchor="w")
        tree.column("size", width=90, stretch=False, anchor="e")
        vsb = self.ttk.Scrollbar(
            list_frame, orient="vertical", command=tree.yview,
        )
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # ``backups`` shape: [{path, name, size, mtime}, ...]
        iid_to_path: dict[str, str] = {}
        for i, b in enumerate(backups):
            iid = str(i)
            when = datetime.fromtimestamp(b["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            tree.insert(
                "", "end", iid=iid, text=b["name"],
                values=(when, f"{b['size']:,} B"),
            )
            iid_to_path[iid] = b["path"]
        if iid_to_path:
            first = next(iter(iid_to_path))
            tree.selection_set(first)
            tree.see(first)

        choice: dict = {"path": None}

        def _ok() -> None:
            sel = tree.selection()
            if sel:
                choice["path"] = iid_to_path.get(sel[0])
            win.destroy()

        def _cancel() -> None:
            win.destroy()

        btn_row = self.ttk.Frame(win, padding=(10, 8))
        btn_row.pack(fill="x")
        self.ttk.Button(btn_row, text="Restore", command=_ok).pack(side="right")
        self.ttk.Button(btn_row, text="Cancel", command=_cancel).pack(
            side="right", padx=(0, 6),
        )
        tree.bind("<Double-Button-1>", lambda _e: _ok())
        win.bind("<Escape>", lambda _e: _cancel())
        win.bind("<Return>", lambda _e: _ok())

        self.root.wait_window(win)
        return choice["path"]

    def _run_mainmenu_sort(self) -> None:
        strategy = self._mainmenu_sort_var.get()
        args = ["mainmenu", "sort", strategy]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_mainmenu_action(self, sub: str) -> None:
        system = self._mainmenu_system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required",
                "Select a system from the dropdown before clicking Add or Remove.",
            )
            return
        verb = "add to" if sub == "add" else "remove from"
        if not self.messagebox.askyesno(
            f"Confirm Main Menu {sub}",
            f"{sub.capitalize()} '{system}' {verb} Main Menu.xml?\n\n"
            "If Apply is checked this writes the file immediately. "
            "If config.backup_before_modify is enabled (the default), a "
            "timestamped .bak is kept next to the file.",
        ):
            return
        args = ["mainmenu", sub, system]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    # ── Diagnose tab (LEGACY — superseded by _build_diagnostics_tab) ────────────

    def _build_diagnose_tab(self, parent):  # LEGACY — superseded by _build_diagnostics_tab
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Read-only inspectors that don't change anything on "
                  "disk. Each click runs the corresponding command and "
                  "streams output below — handy when something looks "
                  "off but you don't know which command will surface it."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        # Two-column grid of buttons so all checks fit without scrolling.
        # `(label, argv_after_spindoctor)` — argv built lazily so a CLI
        # change in one command doesn't ripple here.
        rows: list[tuple[str, list[str]]] = [
            ("Find duplicate ROMs",        ["find-dupes", "--all"]),
            ("Find cross-system dupes",    ["find-dupes", "--cross-systems"]),
            ("Find misplaced ROMs",        ["find-misplaced", "--all"]),
            ("Find orphan media",          ["find-orphan-media", "--all"]),
            ("Check disc-set consistency", ["check-discs", "--all"]),
            ("Lint config + databases",    ["lint"]),
            ("Generate report",            ["report"]),
            ("Preview HyperSpin XML",      ["preview"]),
            ("Stats — playtime overview",  ["stats"]),
        ]
        grid = self.ttk.Frame(frame)
        grid.pack(anchor="w", pady=4)
        def _scan_done(code: int) -> None:
            if code == 0:
                self._set_status("Scan complete — see output for results.")
            else:
                self._set_status(f"Scan finished with errors (exit {code}) — see output for details.")

        for i, (label, args) in enumerate(rows):
            r, c = divmod(i, 2)
            self.ttk.Button(
                grid, text=label, width=32,
                command=lambda a=args: self._run_cli("spindoctor", a, on_complete=_scan_done),
            ).grid(row=r, column=c, sticky="w", padx=4, pady=2)

        # ── Find global ──────────────────────────────────────────────────────
        self.ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)
        self.ttk.Label(
            frame, text="Global search",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        self.ttk.Label(
            frame,
            text="Search every system's database for a ROM or display name.",
            foreground=_FG_DIM,
        ).pack(anchor="w", pady=(0, 4))
        search_row = self.ttk.Frame(frame)
        search_row.pack(fill="x", pady=2)
        self.ttk.Label(search_row, text="Query").pack(side="left")
        self._diagnose_query_var = self.tk.StringVar()
        entry = self.ttk.Entry(
            search_row, textvariable=self._diagnose_query_var,
        )
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self._run_find_global())
        self.ttk.Button(
            search_row, text="Search", command=self._run_find_global,
        ).pack(side="left")

        # ── Verify against a DAT ─────────────────────────────────────────────
        self.ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)
        self.ttk.Label(
            frame, text="Verify ROMs against a DAT file",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        verify_row = self.ttk.Frame(frame)
        verify_row.pack(fill="x", pady=2)
        self.ttk.Label(verify_row, text="System").pack(side="left")
        self._verify_system_var = self.tk.StringVar()
        self._verify_system_combo = self.ttk.Combobox(
            verify_row, textvariable=self._verify_system_var,
            state="readonly", width=24,
        )
        self._verify_system_combo.pack(side="left", padx=6)
        self.ttk.Label(verify_row, text="DAT path").pack(side="left", padx=(8, 0))
        self._verify_dat_var = self.tk.StringVar()
        _verify_entry = self.ttk.Entry(
            verify_row, textvariable=self._verify_dat_var,
        )
        _verify_entry.pack(side="left", fill="x", expand=True, padx=6)
        _verify_entry.bind("<Return>", lambda _e: self._run_verify())
        self.ttk.Button(
            verify_row, text="Browse…",
            command=self._browse_verify_dat,
        ).pack(side="left")
        self.ttk.Button(
            verify_row, text="Verify",
            command=self._run_verify,
        ).pack(side="left", padx=6)

        # ── Inspect a single game ──────────────────────────────────────────────
        # `spindoctor inspect` is one of the highest-leverage diagnostic
        # commands — given a system (and optionally a ROM) it dumps DB
        # entry + ROM + every media file's path, size, dimensions, and
        # duration. Surfacing it here keeps users from dropping to the
        # Custom Command tab for what's a routine triage workflow.
        self.ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)
        self.ttk.Label(
            frame, text="Inspect a single game (or whole system)",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        self.ttk.Label(
            frame,
            text=("Pick a system; leave ROM blank for `inspect --all`. "
                  "Read-only — never modifies disk."),
            foreground=_FG_DIM,
        ).pack(anchor="w", pady=(0, 4))
        inspect_row = self.ttk.Frame(frame)
        inspect_row.pack(fill="x", pady=2)
        self.ttk.Label(inspect_row, text="System").pack(side="left")
        self._inspect_system_var = self.tk.StringVar()
        self._inspect_system_combo = self.ttk.Combobox(
            inspect_row, textvariable=self._inspect_system_var,
            state="readonly", width=24,
        )
        self._inspect_system_combo.pack(side="left", padx=6)
        self._inspect_system_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_inspect_games(),
        )
        self.ttk.Label(inspect_row, text="ROM (optional)").pack(
            side="left", padx=(8, 0),
        )
        self._inspect_rom_var = self.tk.StringVar()
        self._inspect_rom_combo = self.ttk.Combobox(
            inspect_row, textvariable=self._inspect_rom_var,
            state="readonly",
        )
        self._inspect_rom_combo.pack(side="left", fill="x", expand=True, padx=6)
        self._inspect_rom_combo.bind("<Return>", lambda _e: self._run_inspect())
        self.ttk.Button(
            inspect_row, text="↻", width=3,
            command=self._refresh_inspect_games,
        ).pack(side="left")
        self.ttk.Button(
            inspect_row, text="Inspect", command=self._run_inspect,
        ).pack(side="left", padx=(6, 0))

        return frame

    def _run_inspect(self) -> None:
        system = self._inspect_system_var.get().strip()
        rom = self._inspect_rom_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "Pick a system", "Select a system from the dropdown first.",
            )
            return
        args = ["inspect", "--system", system]
        if rom:
            args.append(rom)
        else:
            args.append("--all")
        self._run_cli("spindoctor", args)

    def _browse_verify_dat(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Pick a DAT file",
            initialdir=str(Path.home()),
            filetypes=[("DAT files", "*.dat *.xml"), ("All files", "*.*")],
        )
        if path:
            self._verify_dat_var.set(str(Path(path)))

    def _run_find_global(self) -> None:
        query = self._diagnose_query_var.get().strip()
        if not query:
            self.messagebox.showinfo(
                "Query required", "Type something to search for first.",
            )
            return
        self._run_cli("spindoctor", ["find-global", query])

    def _run_verify(self) -> None:
        system = self._verify_system_var.get().strip()
        dat = self._verify_dat_var.get().strip()
        if not system or not dat:
            self.messagebox.showwarning(
                "System and DAT required",
                "Verify needs both a system name and a DAT file path.",
            )
            return
        self._run_cli(
            "spindoctor", ["verify", "--system", system, "--dat", dat],
        )

    # ── Metadata & Media tab ──────────────────────────────────────────────────

    def _build_metadata_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Fetch metadata + media from ScreenScraper / TheGamesDB, "
                  "scan local media folders into the right HyperSpin "
                  "slots, and sync database XML to your ROM directories. "
                  "Each section is dry-run by default; tick Apply to "
                  "commit."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # Shared system field — every command on this tab takes one.
        sys_row = self.ttk.Frame(frame)
        sys_row.pack(fill="x", pady=(0, 6))
        self.ttk.Label(sys_row, text="System (or tick All systems)").pack(
            side="left",
        )
        self._meta_system_var = self.tk.StringVar()
        self._meta_system_combo = self.ttk.Combobox(
            sys_row, textvariable=self._meta_system_var,
            state="readonly", width=30,
        )
        self._meta_system_combo.pack(side="left", padx=6)
        self._meta_all_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            sys_row, text="All systems", variable=self._meta_all_var,
        ).pack(side="left", padx=6)

        # Multi-system selector — for cabinets with 20+ systems where
        # the user wants to refresh metadata for an arbitrary subset
        # (often "the 5 systems whose scraper data just got better"),
        # neither single-pick nor --all is right. The button opens a
        # multi-select Listbox; on OK the subset is stored and a
        # "Run fetch-meta on subset" button below chains a per-system
        # invocation. Empty subset = button hidden, normal single/all
        # behaviour applies.
        # Restore the last-picked subset from config so cabinet owners
        # who refresh "the same 5 systems" don't re-tick every launch.
        try:
            _persisted_subset = list(
                getattr(load_config(), "gui_meta_subset", []) or []
            )
        except Exception:  # noqa: BLE001
            _persisted_subset = []
        self._meta_subset: list[str] = _persisted_subset
        self.ttk.Button(
            sys_row, text="Pick subset…",
            command=self._pick_meta_subset,
        ).pack(side="left", padx=(10, 6))
        self._meta_subset_label_var = self.tk.StringVar(
            value=(
                f"{len(self._meta_subset)} system(s) picked"
                if self._meta_subset else ""
            )
        )
        self.ttk.Label(
            sys_row, textvariable=self._meta_subset_label_var,
            foreground=_FG_DIM,
        ).pack(side="left")

        # ── Per-game & override (Optional) ───────────────────────────────────
        # Combined game selector + forced scraper IDs, placed before the step
        # buttons so it's clear this targets every operation below.
        gameovr_frame = self.ttk.LabelFrame(
            frame, text="Per-game & override (Optional)",
        )
        gameovr_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            gameovr_frame,
            text=("Select a specific game to target, or leave blank to "
                  "process all games in the selected system. Optionally "
                  "force the exact scraper game ID for titles that don't "
                  "match well by name (language barrier, alternate "
                  "punctuation, remaster subtitle). Find the ID at "
                  "screenscraper.fr/gameinfos.php?gameid=XXXX or "
                  "thegamesdb.net/game.php?id=XXXX. "
                  "Tip: all ID fields accept the full URL — paste it "
                  "directly and the ID is extracted automatically."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 2))

        # Game row — populated automatically when a system is selected.
        game_row = self.ttk.Frame(gameovr_frame)
        game_row.pack(fill="x", padx=6, pady=(2, 0))
        self.ttk.Label(game_row, text="Game (blank = all games)").pack(side="left")
        self._meta_game_var = self.tk.StringVar()
        self._meta_game_combo = self.ttk.Combobox(
            game_row, textvariable=self._meta_game_var,
            state="normal", width=40,
        )
        self._meta_game_combo.pack(side="left", padx=6)
        self.ttk.Button(
            game_row, text="✕",
            command=lambda: self._meta_game_var.set(""),
            width=2,
        ).pack(side="left")
        self.ttk.Label(
            game_row,
            text="← clear to process all games",
            foreground=_FG_DIMMER,
        ).pack(side="left", padx=4)
        # Populate game list when the system selection changes.
        self._meta_system_var.trace_add(
            "write", lambda *_: self._populate_meta_game_list()
        )

        # Override ID fields.
        gameovr_form = self.ttk.Frame(gameovr_frame)
        gameovr_form.pack(fill="x", padx=6, pady=(6, 2))
        self.ttk.Label(gameovr_form, text="ScreenScraper ID").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=2,
        )
        self._gameovr_ss_id_var = self.tk.StringVar()
        self.ttk.Entry(
            gameovr_form, textvariable=self._gameovr_ss_id_var, width=18,
        ).grid(row=0, column=1, sticky="w", pady=2)
        self.ttk.Label(gameovr_form, text="TheGamesDB ID").grid(
            row=0, column=2, sticky="w", padx=(16, 6), pady=2,
        )
        self._gameovr_tgdb_id_var = self.tk.StringVar()
        self.ttk.Entry(
            gameovr_form, textvariable=self._gameovr_tgdb_id_var, width=18,
        ).grid(row=0, column=3, sticky="w", pady=2)
        self.ttk.Label(gameovr_form, text="Steam App ID").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=2,
        )
        self._gameovr_steam_id_var = self.tk.StringVar()
        self.ttk.Entry(
            gameovr_form, textvariable=self._gameovr_steam_id_var, width=40,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=2)
        self.ttk.Label(
            gameovr_form,
            text="← bare ID or full store URL",
            foreground=_FG_DIMMER,
        ).grid(row=1, column=4, sticky="w", padx=(6, 0), pady=2)

        # Clear override ID fields and Steam scan panel when the game selection
        # changes so stale IDs and previous scan results never linger.  System
        # changes also fire this trace because _populate_meta_game_list calls
        # _meta_game_var.set(""), which counts as a write.
        self._meta_game_var.trace_add(
            "write",
            lambda *_: (
                self._gameovr_ss_id_var.set(""),
                self._gameovr_tgdb_id_var.set(""),
                self._gameovr_steam_id_var.set(""),
                self._clear_steam_media_panel(),
            ),
        )

        gameovr_btns = self.ttk.Frame(gameovr_frame)
        gameovr_btns.pack(anchor="w", padx=6, pady=(4, 2))
        self.ttk.Button(
            gameovr_btns, text="Load current override",
            command=self._load_game_override,
        ).pack(side="left")
        self.ttk.Button(
            gameovr_btns, text="Save override",
            command=self._save_game_override,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            gameovr_btns, text="Clear override",
            command=self._clear_game_override,
        ).pack(side="left")

        # ── Steam media panel ─────────────────────────────────────────────────
        # One-off per-game tool: paste a Steam store URL or App ID, scan for
        # available media, pick which video / screenshot / artwork to download.
        # Only useful for PC/Steam games that SS/TGDB don't cover well.
        steam_sep = self.ttk.Separator(gameovr_frame, orient="horizontal")
        steam_sep.pack(fill="x", padx=6, pady=(8, 0))

        steam_hdr = self.ttk.Frame(gameovr_frame)
        steam_hdr.pack(fill="x", padx=6, pady=(6, 2))
        self.ttk.Label(
            steam_hdr,
            text="Steam media  (optional, PC games only)",
            font=("", 0, "bold"),
        ).pack(side="left")
        self.ttk.Label(
            steam_hdr,
            text="— click Find to look up the App ID, or paste a URL and click Scan",
            foreground=_FG_DIM,
        ).pack(side="left", padx=(6, 0))

        steam_url_row = self.ttk.Frame(gameovr_frame)
        steam_url_row.pack(fill="x", padx=6, pady=(2, 4))
        self.ttk.Label(steam_url_row, text="Steam URL / App ID").pack(side="left")
        self._steam_url_var = self.tk.StringVar()
        self.ttk.Entry(
            steam_url_row, textvariable=self._steam_url_var, width=52,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            steam_url_row, text="Find",
            command=self._find_steam_app,
        ).pack(side="left", padx=(0, 4))
        self.ttk.Button(
            steam_url_row, text="Scan",
            command=self._scan_steam,
        ).pack(side="left")
        self._steam_store_btn = self.ttk.Button(
            steam_url_row, text="Store page",
            state="disabled",
            command=lambda: self._open_url(self._steam_source_url),
        )
        self._steam_store_btn.pack(side="left", padx=(4, 0))

        # Per-type candidate pickers (populated by _scan_steam).
        steam_pick_frame = self.ttk.Frame(gameovr_frame)
        steam_pick_frame.pack(fill="x", padx=6, pady=(0, 4))
        self._steam_cands: dict[str, list] = {}  # filled by _scan_steam
        self._steam_pick_vars: dict[str, "tk.StringVar"] = {}
        self._steam_pick_combos: dict[str, "ttk.Combobox"] = {}
        self._steam_preview_btns: dict[str, "ttk.Button"] = {}
        self._steam_source_url: str = ""  # Steam store page URL, set by _on_steam_scan_done

        _picker_layout = [
            ("video",   "Video",      0, 0),
            ("snap",    "Screenshot", 0, 1),
            ("artwork", "Artwork",    1, 0),
            ("wheel",   "Wheel",      1, 1),
        ]
        _cb_widths = {"video": 60}
        for mt, lbl_text, row, col in _picker_layout:
            self.ttk.Label(steam_pick_frame, text=lbl_text).grid(
                row=row, column=col * 3, sticky="w",
                padx=(0 if col == 0 else 12, 4), pady=(0 if row == 0 else 4, 0),
            )
            var = self.tk.StringVar(value="— scan first —")
            cb = self.ttk.Combobox(
                steam_pick_frame, textvariable=var,
                state="disabled", width=_cb_widths.get(mt, 30),
            )
            cb.grid(row=row, column=col * 3 + 1, sticky="w",
                    padx=(0, 0), pady=(0 if row == 0 else 4, 0))
            self._steam_pick_vars[mt] = var
            self._steam_pick_combos[mt] = cb
            preview_btn = self.ttk.Button(
                steam_pick_frame, text="View",
                state="disabled",
                command=lambda m=mt: self._preview_steam_candidate(m),
            )
            preview_btn.grid(row=row, column=col * 3 + 2, sticky="w",
                             padx=(4, 0), pady=(0 if row == 0 else 4, 0))
            self._steam_preview_btns[mt] = preview_btn

        self._steam_overwrite_var = self.tk.BooleanVar(value=False)
        self._steam_quality_var = self.tk.StringVar(value="Best (1080p)")
        self._steam_quality_var.trace_add("write", self._on_steam_quality_changed)
        steam_apply_row = self.ttk.Frame(gameovr_frame)
        steam_apply_row.pack(anchor="w", padx=6, pady=(2, 8))
        self.ttk.Button(
            steam_apply_row, text="▶  Apply selected",
            command=self._apply_steam_selection,
        ).pack(side="left")
        self.ttk.Checkbutton(
            steam_apply_row, text="Overwrite existing",
            variable=self._steam_overwrite_var,
        ).pack(side="left", padx=10)
        self.ttk.Label(steam_apply_row, text="Quality:").pack(side="left", padx=(10, 2))
        self.ttk.Combobox(
            steam_apply_row, textvariable=self._steam_quality_var,
            values=["Best (1080p)", "720p", "480p", "360p"],
            state="readonly", width=12,
        ).pack(side="left")

        # ── Step 1 — Full metadata refresh ───────────────────────────────────
        full_frame = self.ttk.LabelFrame(
            frame, text="Step 1 — Full metadata refresh",
        )
        full_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            full_frame,
            text=("Downloads metadata, artwork, and syncs the database for the "
                  "selected system in one pass. Stops on first error. "
                  "Use the individual steps below to run or troubleshoot each "
                  "phase separately."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 2))
        full_chain_row = self.ttk.Frame(full_frame)
        full_chain_row.pack(anchor="w", padx=6, pady=(2, 6))
        self.ttk.Button(
            full_chain_row, text="▶  Full metadata refresh",
            command=self._run_full_metadata_refresh,
        ).pack(side="left")
        self.ttk.Label(
            full_chain_row,
            text="  — metadata + artwork + database sync in one click",
            foreground=_FG_DIM,
        ).pack(side="left")

        # ── Step 2 — Fetch metadata ──────────────────────────────────────────
        meta_frame = self.ttk.LabelFrame(frame, text="Step 2 — Fetch metadata")
        meta_frame.pack(fill="x", pady=(4, 4))
        # Defaults to True: the GUI cannot drive an interactive `input()`
        # prompt, so the alternative used to be a frozen subprocess. The
        # unchecked path now passes --skip-ambiguous instead so ambiguous
        # matches are logged and surfaced in the next audit pass rather
        # than hanging the GUI. Hydrated from config so the user's last
        # choice persists across launches.
        try:
            _meta_cfg = load_config()
            _ab_default = bool(getattr(_meta_cfg, "gui_meta_auto_best", True))
            _ag_default = bool(getattr(_meta_cfg, "gui_meta_all_games", False))
            _nc_default = bool(getattr(_meta_cfg, "gui_meta_no_cache", False))
        except Exception:  # noqa: BLE001
            _ab_default, _ag_default, _nc_default = True, False, False
        self._meta_auto_best_var = self.tk.BooleanVar(value=_ab_default)
        self._meta_auto_best_var.trace_add(
            "write", lambda *_a: self._persist_meta_pref(
                "gui_meta_auto_best", self._meta_auto_best_var.get(),
            ),
        )
        _meta_ab = self.ttk.Checkbutton(
            meta_frame, text="Auto-pick best match for ambiguous results",
            variable=self._meta_auto_best_var,
        )
        _meta_ab.pack(anchor="w", padx=6, pady=2)
        _attach_tooltip(
            _meta_ab,
            "When the scraper returns multiple candidates, pick the "
            "highest-confidence one automatically. Fast for big "
            "libraries; risks the occasional wrong match — review the "
            "audit afterwards. Untick to skip ambiguous matches and "
            "review them later instead of auto-picking.",
            self.tk,
        )
        self._meta_all_games_var = self.tk.BooleanVar(value=_ag_default)
        self._meta_all_games_var.trace_add(
            "write", lambda *_a: self._persist_meta_pref(
                "gui_meta_all_games", self._meta_all_games_var.get(),
            ),
        )
        _meta_ag = self.ttk.Checkbutton(
            meta_frame,
            text="Re-scrape already-complete entries too",
            variable=self._meta_all_games_var,
        )
        _meta_ag.pack(anchor="w", padx=6, pady=2)
        _attach_tooltip(
            _meta_ag,
            "By default fetch-meta only touches games that are missing "
            "fields. Tick this to re-scrape every game, overwriting "
            "existing metadata (useful when scraper data improves).",
            self.tk,
        )
        self._meta_no_cache_var = self.tk.BooleanVar(value=_nc_default)
        self._meta_no_cache_var.trace_add(
            "write", lambda *_a: self._persist_meta_pref(
                "gui_meta_no_cache", self._meta_no_cache_var.get(),
            ),
        )
        _meta_nc = self.ttk.Checkbutton(
            meta_frame,
            text="Bypass cache — hit the scraper API fresh for every game",
            variable=self._meta_no_cache_var,
        )
        _meta_nc.pack(anchor="w", padx=6, pady=2)
        _attach_tooltip(
            _meta_nc,
            "Bypass the local metadata cache for this run. Slower and "
            "uses more API quota; use when you suspect the cache holds "
            "stale data from a scraper outage.",
            self.tk,
        )
        # Source + threshold inputs sit in their own row so the
        # checkbox column above doesn't get visually crowded.
        meta_opts_row = self.ttk.Frame(meta_frame)
        meta_opts_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(meta_opts_row, text="Source").pack(side="left")
        self._meta_source_var = self.tk.StringVar(value="both (SS primary)")
        self.ttk.Combobox(
            meta_opts_row, textvariable=self._meta_source_var,
            values=["both (SS primary)", "screenscraper", "thegamesdb"],
            state="readonly", width=18,
        ).pack(side="left", padx=6)
        self.ttk.Label(meta_opts_row, text="Threshold").pack(
            side="left", padx=(10, 0),
        )
        self._meta_threshold_var = self.tk.StringVar(value="")
        self.ttk.Entry(
            meta_opts_row, textvariable=self._meta_threshold_var, width=6,
        ).pack(side="left", padx=6)
        self.ttk.Label(
            meta_opts_row,
            text="(0.0–1.0, blank = config default)",
            foreground=_FG_DIMMER,
        ).pack(side="left")
        meta_run_row = self.ttk.Frame(meta_frame)
        meta_run_row.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            meta_run_row, text="Download Game Info",
            command=self._run_fetch_meta,
        ).pack(side="left")
        self.ttk.Button(
            meta_run_row, text="Download for Selected Systems…",
            command=self._run_fetch_meta_subset,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            meta_run_row, text="Restore DB backup…",
            command=self._meta_restore_db_from_backup,
        ).pack(side="left", padx=6)

        # ── fetch-media ──────────────────────────────────────────────────────
        media_frame = self.ttk.LabelFrame(frame, text="Step 3 — Fetch media")
        media_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            media_frame,
            text="Media types to fetch (leave all unchecked for project default):",
            foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(4, 2))
        types_grid = self.ttk.Frame(media_frame)
        types_grid.pack(anchor="w", padx=6, pady=(0, 2))
        _MEDIA_TYPES = [
            "wheel", "background", "snap", "video",
            "trailer", "title", "theme", "fade", "sound",
        ]
        _MEDIA_DEFAULTS = {"wheel", "background"}
        self._meta_type_vars: dict[str, "tk_mod.BooleanVar"] = {}  # noqa: F821 - string annotation, runtime is self.tk.BooleanVar
        for col, mtype in enumerate(_MEDIA_TYPES):
            var = self.tk.BooleanVar(value=(mtype in _MEDIA_DEFAULTS))
            self._meta_type_vars[mtype] = var
            self.ttk.Checkbutton(
                types_grid, text=mtype, variable=var,
            ).grid(row=0, column=col, sticky="w", padx=(0, 8))
        media_opts_row = self.ttk.Frame(media_frame)
        media_opts_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(media_opts_row, text="Source").pack(side="left")
        self._media_source_var = self.tk.StringVar(value="both (SS primary)")
        self.ttk.Combobox(
            media_opts_row, textvariable=self._media_source_var,
            values=["both (SS primary)", "screenscraper", "thegamesdb"],
            state="readonly", width=18,
        ).pack(side="left", padx=6)
        self._meta_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            media_frame, text="Overwrite existing files",
            variable=self._meta_overwrite_var,
        ).pack(anchor="w", padx=6, pady=2)
        self.ttk.Button(
            media_frame, text="Download Media Files",
            command=self._run_fetch_media,
        ).pack(anchor="w", padx=6, pady=(4, 6))

        # ── media-scan ───────────────────────────────────────────────────────
        scan_frame = self.ttk.LabelFrame(frame, text="Step 4 — Scan local media folder")
        scan_frame.pack(fill="x", pady=(4, 4))
        scan_row = self.ttk.Frame(scan_frame)
        scan_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(scan_row, text="Source folder").pack(side="left")
        self._meta_scan_dir_var = self.tk.StringVar()
        self.ttk.Entry(
            scan_row, textvariable=self._meta_scan_dir_var,
        ).pack(side="left", fill="x", expand=True, padx=6)
        self.ttk.Button(
            scan_row, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._meta_scan_dir_var, "Pick media folder to scan",
            ),
        ).pack(side="left")
        self.ttk.Label(scan_row, text="Action").pack(side="left", padx=(10, 0))
        self._meta_scan_action_var = self.tk.StringVar(value="copy")
        self.ttk.Combobox(
            scan_row, textvariable=self._meta_scan_action_var,
            values=["copy", "move", "link"],
            state="readonly", width=8,
        ).pack(side="left", padx=4)
        self._meta_scan_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            scan_frame,
            text="Overwrite existing files",
            variable=self._meta_scan_overwrite_var,
        ).pack(anchor="w", padx=6, pady=2)
        self.ttk.Button(
            scan_frame, text="Import Local Media",
            command=self._run_media_scan,
        ).pack(anchor="w", padx=6, pady=(4, 6))

        # ── update-db ────────────────────────────────────────────────────────
        db_frame = self.ttk.LabelFrame(frame, text="Step 5 — Sync database to ROMs")
        db_frame.pack(fill="x", pady=(4, 4))
        self._meta_remove_orphans_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            db_frame, text="Remove database entries that have no matching ROM",
            variable=self._meta_remove_orphans_var,
        ).pack(anchor="w", padx=6, pady=2)
        self._meta_strip_variant_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            db_frame, text="Strip region/version tags from display names",
            variable=self._meta_strip_variant_var,
        ).pack(anchor="w", padx=6, pady=2)
        self._generate_overwrite_global_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            db_frame,
            text="Overwrite RocketLauncher global emulator config",
            variable=self._generate_overwrite_global_var,
        ).pack(anchor="w", padx=6, pady=2)
        btn_row = self.ttk.Frame(db_frame)
        btn_row.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            btn_row, text="Sync Database to ROMs",
            command=self._run_update_db,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Update RocketLauncher INIs",
            command=self._run_generate_config,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Restore DB backup…",
            command=self._meta_restore_db_from_backup,
        ).pack(side="left", padx=(18, 0))
        self.ttk.Button(
            btn_row, text="Restore RL INI backup…",
            command=self._meta_restore_rl_ini_from_backup,
        ).pack(side="left", padx=6)

        # ── batch-edit ───────────────────────────────────────────────────────
        # Minimal exposure of the batch-edit CLI command — one filter,
        # one set clause, optional CSV report path. Power users with
        # multiple filters / sets can still drop into Custom Command.
        be_frame = self.ttk.LabelFrame(frame, text="Batch edit metadata")
        be_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            be_frame,
            text=("Bulk-edit DB fields across many games (uses the System "
                  "selector above). Examples: filter=year=1980-1989 + "
                  "set=genre=Action ; filter=missing=rating + set=rating=3."),
            wraplength=820, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 2))

        be_grid = self.ttk.Frame(be_frame)
        be_grid.pack(fill="x", padx=6, pady=(0, 4))
        self.ttk.Label(be_grid, text="Filter (e.g. genre=Action)").grid(
            row=0, column=0, sticky="w", pady=2
        )
        self._batch_edit_filter_var = self.tk.StringVar()
        self.ttk.Entry(
            be_grid, textvariable=self._batch_edit_filter_var, width=40,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=2)

        self.ttk.Label(be_grid, text="Set (e.g. rating=5)").grid(
            row=1, column=0, sticky="w", pady=2
        )
        self._batch_edit_set_var = self.tk.StringVar()
        self.ttk.Entry(
            be_grid, textvariable=self._batch_edit_set_var, width=40,
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=2)

        self.ttk.Label(be_grid, text="Report CSV (optional path)").grid(
            row=2, column=0, sticky="w", pady=2
        )
        self._batch_edit_report_var = self.tk.StringVar()
        self.ttk.Entry(
            be_grid, textvariable=self._batch_edit_report_var, width=40,
        ).grid(row=2, column=1, sticky="ew", padx=6, pady=2)
        be_grid.columnconfigure(1, weight=1)

        self.ttk.Button(
            be_frame, text="Run Bulk Edit",
            command=self._run_batch_edit,
        ).pack(anchor="w", padx=6, pady=(2, 6))

        # ── media-add ────────────────────────────────────────────────────────
        # `media-add` registers ONE local file (wheel/snap/trailer/etc.)
        # for ONE game by copying it into the correct HyperSpin Media
        # folder. Common workflow: user grabs a trailer manually, or
        # repairs a missing wheel — they shouldn't have to drop to the
        # terminal for a one-shot media file.
        madd_frame = self.ttk.LabelFrame(frame, text="Add one local media file")
        madd_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            madd_frame,
            text=("Copy a single file into HyperSpin's Media folder for "
                  "one game. Tick 'Move' to remove the source after "
                  "copy. Doesn't honour the Apply checkbox — it always "
                  "writes (the chosen file is the user's explicit input)."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(2, 4))

        madd_row1 = self.ttk.Frame(madd_frame)
        madd_row1.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(madd_row1, text="System").pack(side="left")
        self._madd_system_var = self.tk.StringVar()
        self._madd_system_combo = self.ttk.Combobox(
            madd_row1, textvariable=self._madd_system_var,
            state="readonly", width=22,
        )
        self._madd_system_combo.pack(side="left", padx=6)
        self._madd_system_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_madd_games(),
        )
        self.ttk.Label(madd_row1, text="Game").pack(side="left", padx=(8, 0))
        self._madd_game_var = self.tk.StringVar()
        self._madd_game_combo = self.ttk.Combobox(
            madd_row1, textvariable=self._madd_game_var,
            state="readonly", width=20,
        )
        self._madd_game_combo.pack(side="left", padx=6)
        self.ttk.Button(
            madd_row1, text="↻", width=3,
            command=self._refresh_madd_games,
        ).pack(side="left")
        self.ttk.Label(madd_row1, text="Type").pack(side="left", padx=(8, 0))
        self._madd_type_var = self.tk.StringVar(value="wheel")
        self.ttk.Combobox(
            madd_row1, textvariable=self._madd_type_var,
            values=["wheel", "background", "artwork", "title", "snap",
                    "fade", "video", "trailer", "sound", "theme"],
            state="readonly", width=10,
        ).pack(side="left", padx=6)

        madd_row2 = self.ttk.Frame(madd_frame)
        madd_row2.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(madd_row2, text="File").pack(side="left")
        self._madd_file_var = self.tk.StringVar()
        self.ttk.Entry(
            madd_row2, textvariable=self._madd_file_var,
        ).pack(side="left", fill="x", expand=True, padx=6)
        self.ttk.Button(
            madd_row2, text="Browse…",
            command=self._browse_media_file,
        ).pack(side="left")

        madd_opts = self.ttk.Frame(madd_frame)
        madd_opts.pack(fill="x", padx=6, pady=2)
        self._madd_move_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            madd_opts, text="Move (remove source after copy)",
            variable=self._madd_move_var,
        ).pack(side="left")
        self._madd_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            madd_opts, text="Overwrite if target exists",
            variable=self._madd_overwrite_var,
        ).pack(side="left", padx=10)

        madd_btns = self.ttk.Frame(madd_frame)
        madd_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            madd_btns, text="Add media file",
            command=self._run_media_add,
        ).pack(side="left")

        return frame

    def _browse_media_file(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Pick a media file",
            initialdir=str(Path.home()),
            filetypes=[("All files", "*.*")],
        )
        if path:
            self._madd_file_var.set(str(Path(path)))

    def _run_media_add(self) -> None:
        sys_ = self._madd_system_var.get().strip()
        game = self._madd_game_var.get().strip()
        path = self._madd_file_var.get().strip()
        if not (sys_ and game and path):
            self.messagebox.showwarning(
                "Missing arguments",
                "Pick a system, select a game, and pick a file.",
            )
            return
        if not Path(path).exists():
            self.messagebox.showerror(
                "File not found", f"No such file:\n{path}",
            )
            return
        args = [
            "media-add",
            "--system", sys_,
            "--game", game,
            "--type", self._madd_type_var.get(),
            "--file", path,
        ]
        if self._madd_move_var.get():
            args.append("--move")
        if self._madd_overwrite_var.get():
            args.append("--overwrite")
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_batch_edit(self) -> None:
        sys_args = self._meta_system_args()
        if sys_args is None:
            return
        filter_clause = self._batch_edit_filter_var.get().strip()
        set_clause = self._batch_edit_set_var.get().strip()
        report = self._batch_edit_report_var.get().strip()
        if not filter_clause and not set_clause and not report:
            self.messagebox.showwarning(
                "Nothing to do",
                "Provide at least one of: filter clause, set clause, "
                "or report path.",
            )
            return
        args = ["batch-edit", *sys_args]
        if filter_clause:
            args += ["--filter", filter_clause]
        if set_clause:
            args += ["--set", set_clause]
        if report:
            args += ["--report", report]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _populate_meta_game_list(self) -> None:
        """Refresh the Game dropdown from the selected system's database.

        Always blanks the current Game selection first — a game name
        from the previous system is meaningless (or, worse, coincides
        with an unrelated game of the same name) once the System
        dropdown changes, so it must never carry over.
        """
        self._meta_game_var.set("")
        system = self._meta_system_var.get().strip()
        if not system:
            self._meta_game_combo["values"] = []
            return
        try:
            cfg = load_config()
            db = load_database(system, cfg.databases_dir)
            names = sorted(db.games().keys())
            self._meta_game_combo["values"] = names
        except Exception:  # noqa: BLE001
            self._meta_game_combo["values"] = []

    def _meta_system_args(self) -> Optional[list[str]]:
        """Return the `--system X` or `--all` argv tail, or None on error."""
        if self._meta_all_var.get():
            return ["--all"]
        system = self._meta_system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required",
                "Type a system name (e.g. 'MAME') or tick All systems.",
            )
            return None
        return ["--system", system]

    def _meta_game_args(self) -> list[str]:
        """Return `["--game", name]` if a single game is selected, else []."""
        game = self._meta_game_var.get().strip()
        return ["--game", game] if game else []

    def _gameovr_selection(self) -> Optional[tuple[str, str]]:
        """Return (system, game) from the shared header, or None + a warning.

        Per-game overrides need both — a blank Game means "all games",
        which doesn't make sense for a single-game ID override.
        """
        sys_ = self._meta_system_var.get().strip()
        game_ = self._meta_game_var.get().strip()
        if not sys_ or not game_:
            self.messagebox.showwarning(
                "System and Game required",
                "Pick a System above and select a Game in the optional "
                "override box — a per-game override needs to know exactly "
                "which game.",
            )
            return None
        return sys_, game_

    def _load_game_override(self) -> None:
        """Populate the override form from the saved override for the
        System/Game currently selected in the optional override box."""
        selection = self._gameovr_selection()
        if selection is None:
            return
        sys_, game_ = selection
        try:
            from .config import get_game_override, reset_override_cache
            reset_override_cache()  # force re-read from disk
            current = get_game_override(sys_, game_)
        except Exception as exc:  # noqa: BLE001
            self.messagebox.showerror("Could not load override", str(exc))
            return
        ss = current.get("screenscraper_id")
        self._gameovr_ss_id_var.set("" if ss is None else str(ss))
        tg = current.get("thegamesdb_id")
        self._gameovr_tgdb_id_var.set("" if tg is None else str(tg))
        steam = current.get("steam_app_id")
        self._gameovr_steam_id_var.set("" if steam is None else str(steam))
        # Also pre-fill the Steam scan URL box so Scan works right away.
        if steam:
            self._steam_url_var.set(str(steam))
        if not current:
            self._set_status(
                f"No override saved for '{game_}' on {sys_} yet — fill the "
                "form and click Save."
            )

    def _save_game_override(self) -> None:
        """Build a `config game-override set` argv from the form and run it."""
        selection = self._gameovr_selection()
        if selection is None:
            return
        sys_, game_ = selection
        args = ["config", "game-override", "set", sys_, game_]
        ss = self._gameovr_ss_id_var.get().strip()
        if ss:
            args += ["--screenscraper-id", ss]
        tg = self._gameovr_tgdb_id_var.get().strip()
        if tg:
            args += ["--thegamesdb-id", tg]
        steam = self._gameovr_steam_id_var.get().strip()
        if steam:
            args += ["--steam-app-id", steam]
        if len(args) == 5:
            self._flash_validation(
                "Nothing to save — fill in at least one of ScreenScraper ID "
                "/ TheGamesDB ID / Steam App ID first."
            )
            return
        self._run_cli("spindoctor", args)

    def _clear_game_override(self) -> None:
        """Build a `config game-override clear` argv from the optional
        override box selection and run it."""
        selection = self._gameovr_selection()
        if selection is None:
            return
        sys_, game_ = selection
        self._run_cli("spindoctor", ["config", "game-override", "clear", sys_, game_])
        self._gameovr_ss_id_var.set("")
        self._gameovr_tgdb_id_var.set("")
        self._gameovr_steam_id_var.set("")

    def _clear_steam_media_panel(self) -> None:
        """Reset the Steam scan panel to its initial empty state.

        Called whenever the system or game selection changes so results from
        a previous scan don't persist for the newly-selected game.
        """
        if not hasattr(self, "_steam_url_var"):
            return  # called before the panel is built (system-change trace on init)
        self._steam_url_var.set("")
        self._steam_source_url = ""
        self._steam_cands = {}
        for mt, var in self._steam_pick_vars.items():
            var.set("— scan first —")
        for mt, cb in self._steam_pick_combos.items():
            cb.configure(values=[], state="disabled")
        for mt, btn in self._steam_preview_btns.items():
            btn.configure(state="disabled")
        self._steam_store_btn.configure(state="disabled")

    def _find_steam_app(self) -> None:
        """Search the Steam store by the selected game name and auto-populate
        the Steam URL / App ID field with the best matching result.

        Runs the search on a background thread; updates the URL entry on the
        main thread when done.
        """
        selection = self._gameovr_selection()
        if selection is None:
            return
        _sys, game_name = selection
        if not game_name:
            self.messagebox.showwarning(
                "No game selected",
                "Select a game from the Game dropdown first.",
            )
            return

        self._set_status(f"Searching Steam for '{game_name}'…")

        def _worker() -> None:
            try:
                import json
                import urllib.parse
                import urllib.request

                term = urllib.parse.quote(game_name)
                url = (
                    f"https://store.steampowered.com/api/storesearch/"
                    f"?term={term}&l=english&cc=US"
                )
                # nosec B310 — URL is the hardcoded Steam store search
                # endpoint with a URL-encoded game name; not user-controlled.
                # Bandit flags every urlopen because it could theoretically
                # receive a file:// scheme from a caller.
                with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
                    data = json.loads(resp.read())

                items = data.get("items") or []
                games = [i for i in items if i.get("type") == "game"] or items
                if not games:
                    self.root.after(0, lambda: (
                        self._set_status(f"Steam: no results for '{game_name}'"),
                        self.messagebox.showinfo(
                            "Not found on Steam",
                            f"Steam returned no results for '{game_name}'.\n"
                            "Try a shorter or variant title.",
                        ),
                    ))
                    return

                from .romutils import similarity
                best = max(games, key=lambda i: similarity(i["name"], game_name))
                app_id = str(best["id"])
                store_url = f"https://store.steampowered.com/app/{app_id}/"
                label = best["name"]
                self.root.after(0, lambda u=store_url, n=label, a=app_id: (
                    self._steam_url_var.set(u),
                    self._set_status(f"Steam: found '{n}' (App {a}) — scanning…"),
                    self._scan_steam(),
                ))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: (
                    self._set_status(f"Steam search error: {e}"),
                    self.messagebox.showerror("Steam search error", str(e)),
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _scan_steam(self) -> None:
        """Fetch Steam media candidates for the current System/Game/URL and
        populate the per-type picker dropdowns.

        Runs the Steam API call on a background thread so the GUI stays
        responsive; updates the comboboxes on the main thread when done.
        """
        selection = self._gameovr_selection()
        if selection is None:
            return
        sys_, game_ = selection

        raw = self._steam_url_var.get().strip()
        if not raw:
            self.messagebox.showwarning(
                "No Steam URL / App ID",
                "Paste a Steam store URL or App ID into the Steam URL field first.",
            )
            return

        from .scraper import extract_steam_app_id as _extract, SteamClient, MetadataError, _fmt_duration

        app_id = _extract(raw)
        if app_id is None:
            self.messagebox.showerror(
                "Cannot parse App ID",
                f"Could not extract a Steam App ID from:\n{raw}\n\n"
                "Paste the full store URL (e.g. store.steampowered.com/app/1145360/Hades/) "
                "or just the numeric App ID.",
            )
            return

        self._set_status(f"Scanning Steam App {app_id}…")
        for mt in ("video", "snap", "artwork"):
            cb = self._steam_pick_combos[mt]
            cb.configure(state="disabled")
            self._steam_pick_vars[mt].set("scanning…")

        def _worker():
            try:
                meta = SteamClient().fetch_by_app_id(app_id)
            except MetadataError as exc:
                self.root.after(0, lambda e=exc: (
                    self._set_status(f"Steam scan failed: {e}"),
                    self.messagebox.showerror("Steam scan failed", str(e)),
                ))
                return
            except Exception as exc:  # noqa: BLE001 — surface unexpected errors
                self.root.after(0, lambda e=exc: (
                    self._set_status(f"Steam scan error: {e}"),
                    self.messagebox.showerror("Steam scan error", str(e)),
                ))
                return
            self.root.after(0, lambda m=meta: self._on_steam_scan_done(app_id, m))

        threading.Thread(target=_worker, daemon=True).start()

    # Maps Quality dropdown label → resolution height (None = best available).
    _STEAM_QUALITY_MAP: dict[str, Optional[int]] = {
        "Best (1080p)": None, "720p": 720, "480p": 480, "360p": 360,
    }

    def _steam_video_label(self, c, i: int) -> str:
        """Build a video candidate dropdown label reflecting the current Quality selection."""
        from .scraper import _fmt_duration
        dur = f"  {_fmt_duration(c.duration_secs)}" if c.duration_secs else ""
        height = self._STEAM_QUALITY_MAP.get(self._steam_quality_var.get())
        if c.size_by_height:
            if height is None:
                sz_bytes = c.size_by_height.get(max(c.size_by_height))
            else:
                # Exact match or closest smaller variant (e.g. 720p requested but only 480p exists).
                candidates = sorted(k for k in c.size_by_height if k <= height)
                sz_bytes = c.size_by_height[candidates[-1]] if candidates else None
        else:
            sz_bytes = c.estimated_bytes
        sz = f"  ~{sz_bytes / 1_000_000:.0f} MB" if sz_bytes else ""
        if c.format == "m3u8":
            suffix = f"{dur}{sz}  (HLS — full length, needs ffmpeg)"
        else:
            suffix = f"{dur}{sz}  (MP4 — may be highlight clip)"
        return f"{i}. {c.version or c.source_type}{suffix}"

    def _on_steam_quality_changed(self, *_) -> None:
        """Refresh video candidate labels when the Quality dropdown changes."""
        cands = self._steam_cands.get("video", [])
        if not cands:
            return
        _SKIP = "— do not download —"
        var = self._steam_pick_vars.get("video")
        cb = self._steam_pick_combos.get("video")
        if not var or not cb:
            return
        # Preserve the selected index so the same clip stays chosen after label rebuild.
        old_label = var.get()
        try:
            old_idx = int(old_label.split(".")[0].strip()) if old_label not in (_SKIP, "") else 0
        except (ValueError, IndexError):
            old_idx = 0
        new_labels = [self._steam_video_label(c, i) for i, c in enumerate(cands, 1)]
        cb.configure(values=[_SKIP] + new_labels)
        if old_label == _SKIP:
            var.set(_SKIP)
        elif 1 <= old_idx <= len(new_labels):
            var.set(new_labels[old_idx - 1])

    def _on_steam_scan_done(self, app_id: str, meta) -> None:
        """Called on the main thread when the Steam scan worker finishes.

        Wrapped in a broad try/except so any unexpected exception resets the
        dropdowns and shows a visible error instead of silently freezing on
        'scanning…'.  Tkinter swallows exceptions thrown inside root.after()
        callbacks, making silent failures indistinguishable from a hung thread.
        """
        try:
            self._on_steam_scan_done_inner(app_id, meta)
        except Exception as exc:  # noqa: BLE001
            import traceback
            detail = traceback.format_exc()
            for mt in self._steam_pick_vars:
                self._steam_pick_vars[mt].set("— scan error —")
                self._steam_pick_combos[mt].configure(state="disabled")
                self._steam_preview_btns[mt].configure(state="disabled")
            self._set_status(f"Steam scan error (App {app_id}): {exc}")
            self.messagebox.showerror(
                "Steam scan error",
                f"An unexpected error occurred while processing Steam results "
                f"for App {app_id}:\n\n{exc}\n\nSee the Logs tab for the full "
                f"traceback.",
            )
            import logging as _logging
            _logging.getLogger(__name__).error(
                "_on_steam_scan_done crashed for App %s:\n%s", app_id, detail,
            )

    def _on_steam_scan_done_inner(self, app_id: str, meta) -> None:
        from .scraper import _fmt_duration
        if meta is None:
            self._set_status(f"Steam App {app_id} not found.")
            self.messagebox.showwarning(
                "App not found",
                f"Steam App ID {app_id} returned no data — verify the ID at "
                f"store.steampowered.com/app/{app_id}/",
            )
            for mt in ("video", "snap", "artwork"):
                self._steam_pick_vars[mt].set("— not found —")
            return

        self._steam_cands = {}
        self._steam_source_url = meta.source_url or ""
        if self._steam_source_url:
            self._steam_store_btn.configure(state="normal")

        label_map = {
            "video":   self._steam_video_label,
            "snap":    lambda c, i: f"{i}. {c.version or c.source_type}",
            "artwork": lambda c, i: f"{i}. {c.source_type} ({c.format})",
            "wheel":   lambda c, i: f"{i}. {c.source_type} ({c.format})",
        }
        _SKIP = "— do not download —"
        any_found = False
        for mt in ("video", "snap", "artwork", "wheel"):
            cands = meta.media_candidates.get(mt, [])
            self._steam_cands[mt] = cands
            cb = self._steam_pick_combos[mt]
            var = self._steam_pick_vars[mt]
            if cands:
                real_labels = [label_map[mt](c, i) for i, c in enumerate(cands, 1)]
                # Prepend skip sentinel; default to first real candidate so
                # existing workflows are unchanged — user can set to skip.
                cb.configure(values=[_SKIP] + real_labels, state="readonly")
                var.set(real_labels[0])
                self._steam_preview_btns[mt].configure(state="normal")
                any_found = True
            else:
                cb.configure(values=[], state="disabled")
                var.set("— none —")
                self._steam_preview_btns[mt].configure(state="disabled")

        found_parts = []
        for mt in ("video", "snap", "artwork", "wheel"):
            n = len(self._steam_cands.get(mt, []))
            if n:
                found_parts.append(f"{n} {mt}")
        summary = ", ".join(found_parts) if found_parts else "no media"
        self._set_status(
            f"Steam: {meta.name}  —  {summary}. "
            "Pick candidates then click 'Apply selected'."
        )
        if not any_found:
            self.messagebox.showinfo(
                "No media found",
                f"Steam returned no video, screenshot, or artwork for App {app_id}.",
            )

    def _preview_steam_candidate(self, mt: str) -> None:
        """Open the selected candidate's direct URL in the system browser."""
        cands = self._steam_cands.get(mt, [])
        if not cands:
            return
        label = self._steam_pick_vars[mt].get()
        if label.startswith("—"):
            return
        try:
            idx = int(label.split(".")[0].strip()) - 1
            cand = cands[idx]
        except (ValueError, IndexError):
            return
        if cand.url:
            self._open_url(cand.url)

    def _apply_steam_selection(self) -> None:
        """Shell out to fetch-steam-media with the currently selected candidates."""
        selection = self._gameovr_selection()
        if selection is None:
            return
        sys_, game_ = selection

        raw = self._steam_url_var.get().strip()
        if not raw:
            self.messagebox.showwarning(
                "No Steam URL / App ID",
                "Fill the Steam URL / App ID field and click Scan first.",
            )
            return

        from .scraper import extract_steam_app_id as _extract
        app_id = _extract(raw)
        if app_id is None:
            self.messagebox.showerror(
                "Cannot parse App ID",
                f"Could not extract a Steam App ID from:\n{raw}",
            )
            return

        args = [
            "fetch-steam-media",
            "--system", sys_,
            "--game", game_,
            "--steam-id", app_id,
        ]
        _SKIP = "— do not download —"
        types_to_fetch = []
        for mt in ("video", "snap", "artwork", "wheel"):
            cands = self._steam_cands.get(mt, [])
            if not cands:
                continue
            label = self._steam_pick_vars[mt].get()
            if label == _SKIP:
                continue
            # Label format: "1. <description>" — extract 1-based index.
            try:
                idx = int(label.split(".")[0].strip())
            except (ValueError, IndexError):
                continue
            if 1 <= idx <= len(cands):
                types_to_fetch.append(mt)
                args += [f"--{mt}-index", str(idx)]

        if not types_to_fetch:
            self.messagebox.showwarning(
                "Nothing selected",
                "Scan first, then pick at least one video, screenshot, artwork, or wheel.",
            )
            return

        args += ["--types", ",".join(types_to_fetch)]
        if self._steam_overwrite_var.get():
            args.append("--overwrite")
        quality = self._steam_quality_var.get()
        if quality != "Best (1080p)":
            args += ["--hls-quality", quality.lower()]
        args.append("--apply")
        self._run_cli("spindoctor", args)

    def _build_fetch_meta_args(self, sys_args: list[str]) -> Optional[list[str]]:
        """Compose the full `fetch-meta` argv given a system selector.

        Shared by the single-system Run button and the multi-system
        subset chainer so they always feed the same flags to the CLI.
        Returns None if the threshold field fails validation (caller
        renders the error and aborts).
        """
        args = ["fetch-meta", *sys_args, *self._meta_game_args()]
        if self._meta_auto_best_var.get():
            args.append("--auto-best")
        else:
            # GUI can't satisfy an interactive `input()` prompt — the
            # subprocess would hang. Skip mode logs ambiguous matches
            # and surfaces them in the next audit instead.
            args.append("--skip-ambiguous")
        if self._meta_all_games_var.get():
            args.append("--all-games")
        if self._meta_no_cache_var.get():
            args.append("--no-cache")
        source = self._meta_source_var.get().strip()
        source_cli = source.split()[0] if source else ""
        if source_cli:
            args += ["--source", source_cli]
        thresh = self._meta_threshold_var.get().strip()
        if thresh:
            try:
                t = float(thresh)
            except ValueError:
                self.messagebox.showerror(
                    "Invalid threshold",
                    f"Threshold must be a number between 0.0 and 1.0; "
                    f"got {thresh!r}.",
                )
                return None
            if not (0.0 <= t <= 1.0):
                self.messagebox.showerror(
                    "Invalid threshold",
                    f"Threshold must be between 0.0 and 1.0; got {t}.",
                )
                return None
            args += ["--threshold", str(t)]
        if self._global_apply_var.get():
            args.append("--apply")
        return args

    def _run_fetch_meta(self) -> None:
        sys_args = self._meta_system_args()
        if sys_args is None:
            return
        args = self._build_fetch_meta_args(sys_args)
        if args is None:
            return
        self._run_cli("spindoctor", args)

    def _run_fetch_meta_subset(self) -> None:
        """Chain `fetch-meta --system X` once per system in the picked subset.

        Aborts the chain on the first non-zero exit code — failing fast
        is friendlier than silently rolling through 20 systems while
        only the first one produced useful output.
        """
        if not self._meta_subset:
            self._flash_validation(
                "No subset picked — click 'Pick subset…' first, then "
                "try again."
            )
            return

        # Confirm before launching — chained fetch-meta on 20 systems
        # can take an hour, and the apply toggle is easy to miss.
        n = len(self._meta_subset)
        will_apply = self._global_apply_var.get()
        mode = "WRITING (--apply)" if will_apply else "DRY RUN"
        if not self.messagebox.askyesno(
            "Run fetch-meta on subset?",
            f"Run fetch-meta on {n} system(s) sequentially, in "
            f"{mode} mode?\n\n"
            + "\n".join(f"  · {s}" for s in self._meta_subset[:10])
            + ("\n  …" if n > 10 else "")
            + "\n\nThe chain stops on the first failure.",
        ):
            return

        # Snapshot the queue so a user editing the subset mid-run
        # doesn't change what the chain is doing.
        queue = list(self._meta_subset)
        total = len(queue)

        def run_next(remaining: list[str], rc: int) -> None:
            if rc != 0:
                self._append_output(
                    f"\nStopped — previous step exited with code {rc}.\n"
                )
                self._set_status(f"fetch-meta chain stopped at exit {rc}.")
                return
            if not remaining:
                self._append_output(
                    f"\nfetch-meta subset chain complete ({total} system(s)).\n"
                )
                self._set_status(
                    f"fetch-meta on {total} system(s) done."
                )
                return
            head, *rest = remaining
            step_num = total - len(remaining) + 1
            self._set_status(f"Step {step_num}/{total}: {head}…")
            args = self._build_fetch_meta_args(["--system", head])
            if args is None:
                # Threshold validation already showed an error; abort.
                return
            self._run_cli(
                "spindoctor", args,
                on_complete=lambda code: run_next(rest, code),
            )

        run_next(queue, 0)

    def _pick_meta_subset(self) -> None:
        """Modal Listbox picker for the multi-system fetch-meta selector."""
        try:
            systems = get_systems(load_config())
        except Exception as exc:  # noqa: BLE001 - surface in dialog
            self.messagebox.showerror(
                "Could not list systems", str(exc),
            )
            return
        if not systems:
            self._flash_validation(
                "No systems found — configure the Setup tab first."
            )
            return

        win = self.tk.Toplevel(self.root)
        win.title("Pick systems for fetch-meta")
        win.transient(self.root)
        self._fit_geometry(win, 360, 520)
        try:
            win.grab_set()
        except Exception:  # noqa: BLE001
            pass

        self.ttk.Label(
            win, padding=(12, 8, 12, 4),
            text=(
                "Tick the systems you want to refresh. The run chains "
                "them sequentially; on the first failure it stops so "
                "you can fix the cause before continuing."
            ),
            wraplength=320, justify="left",
        ).pack(anchor="w")

        lb_frame = self.ttk.Frame(win, padding=(12, 4))
        lb_frame.pack(fill="both", expand=True)
        lb = self.tk.Listbox(
            lb_frame, selectmode="extended", height=14,
            exportselection=False,
        )
        sb = self.ttk.Scrollbar(
            lb_frame, orient="vertical", command=lb.yview,
        )
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for s in systems:
            lb.insert("end", s)
        # Pre-select whatever the user picked last time.
        for i, s in enumerate(systems):
            if s in self._meta_subset:
                lb.selection_set(i)

        btns = self.ttk.Frame(win, padding=(12, 4, 12, 12))
        btns.pack(fill="x")

        def _select_all() -> None:
            lb.selection_set(0, "end")

        def _clear_all() -> None:
            lb.selection_clear(0, "end")

        def _commit() -> None:
            picks = [lb.get(i) for i in lb.curselection()]
            self._meta_subset = picks
            if picks:
                self._meta_subset_label_var.set(
                    f"({len(picks)} picked)"
                )
            else:
                self._meta_subset_label_var.set("")
            # Persist so the same subset is pre-selected next launch.
            self._persist_meta_pref("gui_meta_subset", list(picks))
            win.destroy()

        self.ttk.Button(btns, text="Select all", command=_select_all).pack(
            side="left",
        )
        self.ttk.Button(btns, text="Clear", command=_clear_all).pack(
            side="left", padx=6,
        )
        self.ttk.Button(btns, text="Cancel", command=win.destroy).pack(
            side="right",
        )
        self.ttk.Button(btns, text="OK", command=_commit).pack(
            side="right", padx=6,
        )

    def _run_fetch_media(self) -> None:
        sys_args = self._meta_system_args()
        if sys_args is None:
            return
        args = ["fetch-media", *sys_args, *self._meta_game_args()]
        selected_types = ",".join(
            t for t, v in self._meta_type_vars.items() if v.get()
        )
        if selected_types:
            args += ["--types", selected_types]
        source = self._media_source_var.get().strip()
        source_cli = source.split()[0] if source else ""
        if source_cli:
            args += ["--source", source_cli]
        if self._meta_overwrite_var.get():
            args.append("--overwrite")
        if self._global_verbose_var.get():
            args.append("--verbose")
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_media_scan(self) -> None:
        source = self._meta_scan_dir_var.get().strip()
        if not source:
            self.messagebox.showwarning(
                "Source folder required",
                "Pick the media folder to scan first.",
            )
            return
        sys_args = self._meta_system_args()
        if sys_args is None:
            return
        args = ["media-scan", source, *sys_args]
        if self._meta_scan_overwrite_var.get():
            args.append("--overwrite")
        if self._global_apply_var.get():
            args += ["--apply", "--action", self._meta_scan_action_var.get()]
        self._run_cli("spindoctor", args)

    def _run_update_db(self) -> None:
        sys_args = self._meta_system_args()
        if sys_args is None:
            return
        args = ["update-db", *sys_args]
        if self._meta_remove_orphans_var.get():
            args.append("--remove-orphans")
        if self._meta_strip_variant_var.get():
            args.append("--strip-variant-tags")
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_generate_config(self) -> None:
        args = ["generate-config"]
        if getattr(self, "_generate_overwrite_global_var", None) and self._generate_overwrite_global_var.get():
            args.append("--overwrite-global")
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _meta_restore_db_from_backup(self) -> None:
        """Restore the selected system's HyperSpin XML database from a .bak sidecar.

        Delegates entirely to ``spindoctor backup sidecar list/restore`` —
        no file I/O in the GUI.  Covers databases written by fetch-meta,
        update-db, and batch-edit.
        """
        sys_name = self._meta_system_var.get().strip()
        if not sys_name:
            self.messagebox.showwarning(
                "No system selected",
                "Pick a system in the selector above first.",
            )
            return
        try:
            cfg = load_config()
        except Exception as exc:  # noqa: BLE001
            self.messagebox.showerror("Config error", str(exc))
            return
        xml_path = Path(cfg.databases_dir) / sys_name / f"{sys_name}.xml"
        self._restore_sidecar(xml_path)

    def _meta_restore_rl_ini_from_backup(self) -> None:
        """Restore the selected system's RocketLauncher INI from a .bak sidecar.

        Delegates entirely to ``spindoctor backup sidecar list/restore`` —
        no file I/O in the GUI.  Covers INIs written by generate-config.

        Detects which layout the system uses before resolving the path:

        - **Folder layout** (HyperHQ): ``Settings/<system>/Emulators.ini``
        - **Flat layout**: ``Settings/<system>.ini``
        """
        sys_name = self._meta_system_var.get().strip()
        if not sys_name:
            self.messagebox.showwarning(
                "No system selected",
                "Pick a system in the selector above first.",
            )
            return
        try:
            cfg = load_config()
        except Exception as exc:  # noqa: BLE001
            self.messagebox.showerror("Config error", str(exc))
            return
        if not cfg.rocketlauncher_dir:
            self.messagebox.showwarning(
                "RocketLauncher not configured",
                "Set rocketlauncher_dir in the Setup tab first.",
            )
            return
        settings_dir = Path(cfg.rocketlauncher_dir) / "Settings"
        folder_ini = settings_dir / sys_name / "Emulators.ini"
        flat_ini = settings_dir / f"{sys_name}.ini"
        ini_path = folder_ini if folder_ini.exists() else flat_ini
        self._restore_sidecar(ini_path)

    def _run_full_metadata_refresh(self) -> None:
        """Chain fetch-meta → fetch-media → update-db, stopping on first error."""
        sys_args = self._meta_system_args()
        if sys_args is None:
            return

        # Reuse the single-system Run path's builder so the chained
        # version honours --source, --threshold, and --no-cache too.
        # Earlier this composed a hand-rolled argv list that silently
        # dropped those flags — users who set them and clicked "Full
        # refresh" got a default-config run with no warning.
        fetch_meta_args = self._build_fetch_meta_args(sys_args)
        if fetch_meta_args is None:
            return

        fetch_media_args = ["fetch-media", *sys_args, *self._meta_game_args()]
        selected_types = ",".join(
            t for t, v in self._meta_type_vars.items() if v.get()
        )
        if selected_types:
            fetch_media_args += ["--types", selected_types]
        if self._meta_overwrite_var.get():
            fetch_media_args.append("--overwrite")
        if self._global_verbose_var.get():
            fetch_media_args.append("--verbose")
        if self._global_apply_var.get():
            fetch_media_args.append("--apply")

        update_db_args = ["update-db", *sys_args]
        if self._meta_remove_orphans_var.get():
            update_db_args.append("--remove-orphans")
        if self._meta_strip_variant_var.get():
            update_db_args.append("--strip-variant-tags")
        if self._global_apply_var.get():
            update_db_args.append("--apply")

        step_defs: list[tuple[str, list[str]]] = [
            ("fetch-meta",  fetch_meta_args),
            ("fetch-media", fetch_media_args),
            ("update-db",   update_db_args),
        ]
        total = len(step_defs)
        self._chain_start(total)

        def run_next(remaining: list[tuple[str, list[str]]], rc: int) -> None:
            if rc != 0:
                self._chain_end()
                self._append_output(
                    f"\nFull refresh stopped — previous step exited with code {rc}.\n"
                )
                return
            if not remaining:
                self._chain_end()
                self._append_output("\nFull metadata refresh complete.\n")
                self._set_status("Full metadata refresh complete.")
                return
            step_num = total - len(remaining) + 1
            self._chain_advance(step_num)
            name, args = remaining[0]
            self._set_status(f"Step {step_num}/{total}: {name}…")
            self._run_cli(
                "spindoctor", args,
                on_complete=lambda code: run_next(remaining[1:], code),
            )

        run_next(step_defs, 0)

    # ── Maintenance tab (formerly Curate) ─────────────────────────────────────

    def _build_maintenance_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Curate region/revision duplicates, prune library caches, "
                  "and manage the ignore and match-cache lists. Curate keeps "
                  "one canonical variant per title and archives the rest "
                  "(reversible). Cleanup trims SpinDoctor's caches. Ignore "
                  "lists silence games from audits."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # ── Step 1 — Curate region/revision variants ─────────────────────────
        cur_frame = self.ttk.LabelFrame(frame, text="Step 1 — Curate region/revision variants")
        cur_frame.pack(fill="x", pady=(4, 4))

        cur_top = self.ttk.Frame(cur_frame)
        cur_top.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(cur_top, text="System (or tick All systems)").pack(
            side="left",
        )
        self._curate_system_var = self.tk.StringVar()
        self._curate_system_combo = self.ttk.Combobox(
            cur_top, textvariable=self._curate_system_var,
            state="readonly", width=24,
        )
        self._curate_system_combo.pack(side="left", padx=6)
        self._curate_all_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            cur_top, text="All systems", variable=self._curate_all_var,
        ).pack(side="left", padx=6)

        cur_regions_label = self.ttk.Frame(cur_frame)
        cur_regions_label.pack(fill="x", padx=6, pady=(4, 0))
        self.ttk.Label(
            cur_regions_label,
            text="Regions to prefer (none checked = use config default):",
        ).pack(side="left")
        cur_regions_grid = self.ttk.Frame(cur_frame)
        cur_regions_grid.pack(fill="x", padx=6, pady=(2, 2))
        _CURATE_REGIONS = [
            "USA", "World", "Europe", "Japan",
            "Korea", "Brazil", "Australia", "Spain",
            "France", "Germany", "Italy",
        ]
        # Restore the last-picked region set from config (non-destructive
        # preference). Empty list = no rows ticked = fall back to
        # config.region_preferences at run time.
        try:
            _persisted_regions = set(
                getattr(load_config(), "gui_curate_regions", []) or []
            )
        except Exception:  # noqa: BLE001
            _persisted_regions = set()
        self._curate_region_vars: dict[str, "tk_mod.BooleanVar"] = {}  # noqa: F821
        for col, region in enumerate(_CURATE_REGIONS):
            var = self.tk.BooleanVar(value=region in _persisted_regions)
            self._curate_region_vars[region] = var
            var.trace_add(
                "write",
                lambda *_a: self._persist_meta_pref(
                    "gui_curate_regions",
                    [r for r, v in self._curate_region_vars.items() if v.get()],
                ),
            )
            self.ttk.Checkbutton(
                cur_regions_grid, text=region, variable=var,
            ).grid(row=0, column=col, sticky="w", padx=(0, 6))

        cur_opts = self.ttk.Frame(cur_frame)
        cur_opts.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(cur_opts, text="Prefer revision").pack(side="left")
        self._curate_revision_var = self.tk.StringVar(value="latest")
        self.ttk.Combobox(
            cur_opts, textvariable=self._curate_revision_var,
            values=["latest", "oldest"], state="readonly", width=8,
        ).pack(side="left", padx=4)

        cur_flags = self.ttk.Frame(cur_frame)
        cur_flags.pack(fill="x", padx=6, pady=2)
        self._curate_proto_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            cur_flags, text="Treat prototypes as candidates "
                              "(--include-proto)",
            variable=self._curate_proto_var,
        ).pack(side="left")
        self.ttk.Label(cur_flags, text="Action").pack(side="left", padx=(20, 0))
        self._curate_action_var = self.tk.StringVar(value="archive")
        _curate_action_combo = self.ttk.Combobox(
            cur_flags, textvariable=self._curate_action_var,
            values=["archive", "delete"], state="readonly", width=10,
        )
        _curate_action_combo.pack(side="left", padx=4)
        _attach_tooltip(
            _curate_action_combo,
            "archive (default, recommended): retired ROMs are moved to "
            "a per-system zip under ~/.spindoctor/curate-archive/ and "
            "are fully recoverable via 'Undo most recent curate'. "
            "delete: ROMs are permanently removed from disk with no "
            "undo path. Pick delete only when you've already curated "
            "the system once and confirmed the archive is correct.",
            self.tk,
        )
        self.ttk.Label(
            cur_frame,
            text="archive = moves duplicates to a zip archive (reversible via Undo)."
                 "  delete = permanently removes ROMs from disk.",
            foreground=_FG_DIMMER,
        ).pack(anchor="w", padx=6, pady=(0, 2))

        cur_btns = self.ttk.Frame(cur_frame)
        cur_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            cur_btns, text="Preview (interactive)…",
            command=self._show_curate_preview,
        ).pack(side="left")
        self.ttk.Button(
            cur_btns, text="Archive / Delete Duplicates", command=self._run_curate,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            cur_btns, text="Undo most recent curate",
            command=self._run_curate_undo,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            cur_btns, text="List manifests",
            command=lambda: self._run_cli(
                "spindoctor", ["curate", "--list-manifests"],
            ),
        ).pack(side="left", padx=6)

        # ── cleanup ──────────────────────────────────────────────────────────
        cln_frame = self.ttk.LabelFrame(frame, text="Cache cleanup")
        cln_frame.pack(fill="x", pady=(4, 4))

        # Category checkboxes — safe ones pre-checked, unsafe unchecked.
        cln_cats_frame = self.ttk.Frame(cln_frame)
        cln_cats_frame.pack(fill="x", padx=6, pady=(4, 2))
        self._cleanup_cat_vars: dict[str, "tk.BooleanVar"] = {}  # noqa: F821
        safe_cats  = [(k, lbl) for k, lbl, s in _CLEANUP_CATEGORIES if s]
        unsafe_cats = [(k, lbl) for k, lbl, s in _CLEANUP_CATEGORIES if not s]
        cols = 3
        for i, (key, lbl) in enumerate(safe_cats):
            var = self.tk.BooleanVar(value=True)
            self._cleanup_cat_vars[key] = var
            self.ttk.Checkbutton(
                cln_cats_frame, text=lbl, variable=var,
            ).grid(row=i // cols, column=i % cols, sticky="w", padx=4, pady=1)

        unsafe_row = (len(safe_cats) + cols - 1) // cols
        self.ttk.Label(
            cln_cats_frame,
            text="Unsafe (removes undo/recovery options):",
            foreground=_FG_DIMMER,
        ).grid(row=unsafe_row, column=0, columnspan=cols, sticky="w",
               padx=4, pady=(6, 1))
        unsafe_row += 1
        for i, (key, lbl) in enumerate(unsafe_cats):
            var = self.tk.BooleanVar(value=False)
            self._cleanup_cat_vars[key] = var
            # ttk.Checkbutton has no `-foreground` constructor option;
            # the grey tint comes from the Unsafe.TCheckbutton style
            # configured in __init__.
            self.ttk.Checkbutton(
                cln_cats_frame, text=lbl, variable=var,
                style="Unsafe.TCheckbutton",
            ).grid(row=unsafe_row + i // cols, column=i % cols,
                   sticky="w", padx=4, pady=1)

        cln_opts = self.ttk.Frame(cln_frame)
        cln_opts.pack(fill="x", padx=6, pady=(4, 2))
        self.ttk.Label(cln_opts, text="Older than (days, 0 = any age)").pack(
            side="left",
        )
        self._cleanup_older_var = self.tk.StringVar(value="30")
        self.ttk.Spinbox(
            cln_opts, from_=0, to=365, textvariable=self._cleanup_older_var,
            width=6,
        ).pack(side="left", padx=6)
        cln_reset_row = self.ttk.Frame(cln_frame)
        cln_reset_row.pack(anchor="w", padx=6, pady=(0, 2))
        self.ttk.Button(
            cln_reset_row, text="Reset to defaults",
            command=self._cleanup_reset_cats,
        ).pack(side="left")

        cln_btns = self.ttk.Frame(cln_frame)
        cln_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            cln_btns, text="Check Cache Status",
            command=lambda: self._run_cli("spindoctor", ["cleanup", "audit"]),
        ).pack(side="left")
        self.ttk.Button(
            cln_btns, text="Clean Up Caches",
            command=self._run_cleanup,
        ).pack(side="left", padx=6)

        # ── ignore ───────────────────────────────────────────────────────────
        ign_frame = self.ttk.LabelFrame(frame, text="Ignore list")
        ign_frame.pack(fill="x", pady=(4, 4))
        ign_top = self.ttk.Frame(ign_frame)
        ign_top.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(ign_top, text="System (blank = global)").pack(side="left")
        self._ignore_system_var = self.tk.StringVar()
        self._ignore_system_combo = self.ttk.Combobox(
            ign_top, textvariable=self._ignore_system_var,
            state="readonly", width=24,
        )
        self._ignore_system_combo.pack(side="left", padx=6)
        self._ignore_system_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_ignore_games(),
        )
        self.ttk.Label(ign_top, text="Game name").pack(side="left", padx=(10, 0))
        self._ignore_game_var = self.tk.StringVar()
        self._ignore_game_combo = self.ttk.Combobox(
            ign_top, textvariable=self._ignore_game_var,
            state="readonly", width=30,
        )
        self._ignore_game_combo.pack(side="left", padx=6)
        self.ttk.Button(
            ign_top, text="↻", width=3,
            command=self._refresh_ignore_games,
        ).pack(side="left")

        ign_btns = self.ttk.Frame(ign_frame)
        ign_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            ign_btns, text="Add to ignore",
            command=lambda: self._run_ignore("add"),
        ).pack(side="left")
        self.ttk.Button(
            ign_btns, text="Remove from ignore",
            command=lambda: self._run_ignore("remove"),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            ign_btns, text="List entries",
            command=self._run_ignore_list,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            ign_btns, text="View / un-ignore…",
            command=self._show_ignore_viewer,
        ).pack(side="left", padx=6)

        # ── match cache ──────────────────────────────────────────────────────
        # Cached scraper-match decisions live in ~/.spindoctor/match_cache/.
        # After fetch-meta the user's pick for each game is remembered so
        # re-running fetch-meta doesn't re-prompt. List shows the cache;
        # Clear wipes it so games get re-evaluated (e.g. after scraper
        # data improves). Doctor already prunes stale cache entries;
        # this surface is for deliberate full resets.
        match_frame = self.ttk.LabelFrame(frame, text="Metadata-match cache")
        match_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            match_frame,
            text=("Each fetch-meta run remembers which scraper result you "
                  "picked per game. Clear the cache (for one system or "
                  "all) when scraper data improves and you want fresh "
                  "matches. Doctor --fix already drops stale entries."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(2, 4))

        match_row = self.ttk.Frame(match_frame)
        match_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(match_row, text="System (blank = all)").pack(side="left")
        self._match_system_var = self.tk.StringVar()
        self._match_system_combo = self.ttk.Combobox(
            match_row, textvariable=self._match_system_var,
            state="readonly", width=24,
        )
        self._match_system_combo.pack(side="left", padx=6)

        match_btns = self.ttk.Frame(match_frame)
        match_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            match_btns, text="List cached matches",
            command=self._match_list,
        ).pack(side="left")
        self.ttk.Button(
            match_btns, text="Clear cache…",
            command=self._match_clear,
        ).pack(side="left", padx=6)

        return frame

    def _refresh_fixexe_games(self) -> None:
        system = self._fixexe_system_var.get().strip()
        # Scan the ROM directory so games that exist on disk but are not yet
        # in the HyperSpin XML (e.g. newly installed GOG titles) still appear.
        games: list[str] = []
        if system:
            try:
                cfg = load_config()
                system_dir = Path(cfg.roms_dir) / system
                if not system_dir.exists():
                    # Try a case-insensitive match in case the ROM folder name
                    # differs in case from the selected system name.
                    roms_root = Path(cfg.roms_dir)
                    system_dir = next(
                        (p for p in roms_root.iterdir()
                         if p.is_dir() and p.name.lower() == system.lower()),
                        system_dir,
                    )
                games = sorted(
                    p.name for p in system_dir.iterdir() if p.is_dir()
                )
            except Exception:  # noqa: BLE001
                games = []

        # Badge any game folder that has no matching entry in the system's
        # HyperSpin XML.  Other game pickers read from the XML directly so
        # all their entries are already in the database — only this picker
        # needs the annotation.
        _db_names: set[str] = set()
        if games and system:
            try:
                cfg = load_config()  # already loaded above; cheap re-call
                _db = load_database(system, cfg.databases_dir)
                _db_names = {n.lower() for n in _db.games().keys()}
            except Exception:  # noqa: BLE001
                pass  # missing / bad XML — skip annotation
        display_games = [
            g if g.lower() in _db_names else g + _NOT_IN_WHEEL_SUFFIX
            for g in games
        ]

        combo = getattr(self, "_fixexe_game_combo", None)
        if combo is None:
            return
        combo["values"] = display_games
        # Keep the var clean so all three _fixexe_game_var.get() call sites
        # receive the raw game name without the badge.
        self._fixexe_game_var.set(games[0] if games else "")
        # Strip badge on user selection (one-time binding per combo lifetime).
        if not getattr(combo, "_game_badge_bound", False):
            combo._game_badge_bound = True  # type: ignore[attr-defined]
            def _strip_game_badge(event, _v=self._fixexe_game_var):
                val = _v.get()
                if val.endswith(_NOT_IN_WHEEL_SUFFIX):
                    _v.set(val[:-len(_NOT_IN_WHEEL_SUFFIX)])
            combo.bind("<<ComboboxSelected>>", _strip_game_badge, add=True)
        lb = getattr(self, "_fixexe_listbox", None)
        if lb is not None:
            lb.delete(0, "end")
        self._fixexe_path_var.set("")
        if games:
            self._fixexe_load_candidates()

    def _fixexe_load_candidates(self) -> None:
        """Populate the exe listbox for the selected game."""
        system = self._fixexe_system_var.get().strip()
        game = self._fixexe_game_var.get().strip()
        lb = getattr(self, "_fixexe_listbox", None)
        if lb is None:
            return
        lb.delete(0, "end")
        self._fixexe_path_var.set("")
        if not (system and game):
            return
        try:
            cfg = load_config()
            game_dir = Path(cfg.roms_dir) / system / game
            paths = list_exe_candidates(game_dir, game)
        except Exception:  # noqa: BLE001
            paths = []
        for p in paths:
            lb.insert("end", str(p))
        if paths:
            lb.selection_set(0)
            self._fixexe_path_var.set(str(paths[0]))

    def _fixexe_on_select(self) -> None:
        lb = getattr(self, "_fixexe_listbox", None)
        if lb is None:
            return
        sel = lb.curselection()
        if sel:
            self._fixexe_path_var.set(lb.get(sel[0]))

    def _run_fixexe(self) -> None:
        system = self._fixexe_system_var.get().strip()
        game = self._fixexe_game_var.get().strip()
        exe = self._fixexe_path_var.get().strip()
        if not (system and game):
            self.messagebox.showwarning(
                "Input required", "Select a system and game first.",
            )
            return
        args = ["pc-fix-exe", system, game]
        if self._global_apply_var.get():
            args.append("--apply")
        if exe:
            args.extend(["--exe", exe])
        self._run_cli("spindoctor", args)

    def _fixexe_browse(self) -> None:
        """Open a native file browser to locate any executable on the system."""
        current = self._fixexe_path_var.get().strip()
        if current and Path(current).parent.exists():
            initial_dir = str(Path(current).parent)
        else:
            try:
                cfg = load_config()
                system = self._fixexe_system_var.get().strip()
                game = self._fixexe_game_var.get().strip()
                candidate = Path(cfg.roms_dir) / system / game
                initial_dir = str(candidate) if candidate.is_dir() else str(Path(cfg.roms_dir))
            except Exception:  # noqa: BLE001
                initial_dir = str(Path.home())
        path = self.filedialog.askopenfilename(
            title="Select executable",
            initialdir=initial_dir,
            filetypes=[
                    ("Executables & scripts", "*.exe;*.ahk;*.bat"),
                    ("AHK scripts", "*.ahk"),
                    ("Batch files", "*.bat"),
                    ("All files", "*.*"),
                ],
        )
        if path:
            # Normalise to native path separators (Tk returns POSIX-style on Windows).
            self._fixexe_path_var.set(str(Path(path)))

    def _match_list(self) -> None:
        args = ["match", "list"]
        system = self._match_system_var.get().strip()
        if system:
            args.extend(["--system", system])
        self._run_cli("spindoctor", args)

    def _match_clear(self) -> None:
        system = self._match_system_var.get().strip()
        scope = f"the '{system}' system" if system else "ALL systems"
        if not self.messagebox.askyesno(
            "Clear match cache?",
            f"This will delete cached scraper-match selections for "
            f"{scope}. The next 'fetch-meta' run will re-evaluate "
            "every game (and may re-prompt on ambiguous matches).\n\n"
            "Continue?",
        ):
            return
        args = ["match", "clear", "--yes"]
        if system:
            args.extend(["--system", system])
        self._run_cli("spindoctor", args)

    def _curate_system_args(self) -> Optional[list[str]]:
        if self._curate_all_var.get():
            return ["--all"]
        system = self._curate_system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required",
                "Type a system name or tick All systems first.",
            )
            return None
        return ["--system", system]

    def _run_curate(self) -> None:
        sys_args = self._curate_system_args()
        if sys_args is None:
            return
        args = ["curate", *sys_args,
                "--prefer-revision", self._curate_revision_var.get()]
        regions = ",".join(
            r for r, v in self._curate_region_vars.items() if v.get()
        )
        if regions:
            args += ["--regions", regions]
        if self._curate_proto_var.get():
            args.append("--include-proto")
        action = self._curate_action_var.get()
        if action != "archive":
            args += ["--action", action]
        if self._global_apply_var.get():
            if action == "delete":
                system_label = (
                    "ALL systems" if self._curate_all_var.get()
                    else self._curate_system_var.get()
                )
                # Final-confirmation dialog. This is the ONLY destructive
                # confirm — the Apply checkbox is "I want to do this for
                # real" and Run is "execute"; this dialog is the last
                # gate before files are permanently removed (no undo for
                # delete-mode curate). Kept blunt and short so users who
                # already meant it can confirm fast.
                if not self.messagebox.askyesno(
                    "Permanently delete duplicate ROMs?",
                    f"Targeting: {system_label}\n"
                    f"Regions kept: {regions or 'config default'}\n"
                    f"Revision preference: {self._curate_revision_var.get()}\n\n"
                    "All ROMs flagged for retirement will be permanently "
                    "DELETED from disk — there is no undo for delete "
                    "mode. (Use action=archive instead if you want a "
                    "reversible operation.)\n\n"
                    "Proceed?",
                ):
                    return
                args.append("--yes")
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_curate_undo(self) -> None:
        self._run_cli("spindoctor", ["curate", "--undo"])

    # ── Curate preview (interactive diff) ─────────────────────────────────────

    # Glyphs used in the per-row checkboxes. ☑ = retire, ☐ = keep
    # (i.e. user vetoed the retirement). Picked over Tk's `tristatevalue`
    # because it doesn't require a custom style and renders identically
    # across platforms.
    _CURATE_RETIRE_GLYPH = "☑"
    _CURATE_SKIP_GLYPH = "☐"

    def _show_curate_preview(self) -> None:
        """Open a Toplevel with the curate plan rendered as a tree.

        Each title is a parent row; under it the kept ROM appears with
        an unchecked status, and each retire candidate appears with a
        checkbox. Toggling a checkbox vetoes that row's retirement.
        Apply runs `apply_curation` against the (possibly filtered)
        groups — bypassing the CLI so we don't have to round-trip a
        list of "skip these specific files" through argv.
        """
        # Multi-system preview is unwieldy in a single tree and the
        # scan can take minutes. Force one-system-at-a-time here.
        if self._curate_all_var.get():
            self._flash_validation(
                "Preview handles one system at a time — untick "
                "'All systems' and pick a specific one (or use Run "
                "curate for a multi-system pass)."
            )
            return
        system = self._curate_system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required",
                "Type a system name (e.g. 'NES') first.",
            )
            return

        regions = ",".join(
            r for r, v in self._curate_region_vars.items() if v.get()
        )
        prefer_latest = self._curate_revision_var.get() == "latest"
        prefer_no_proto = not self._curate_proto_var.get()

        # ── Build the window shell synchronously, fill the tree async ───────
        win = self.tk.Toplevel(self.root)
        win.title(f"Curate preview — {system}")
        self._fit_geometry(win, 1100, 650)
        win.transient(self.root)

        status_var = self.tk.StringVar(
            value=f"Scanning {system} — this can take a while on large libraries…",
        )
        self.ttk.Label(
            win, textvariable=status_var, padding=(10, 6),
            wraplength=1080, justify="left",
        ).pack(fill="x")

        tree_frame = self.ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
        tree = self.ttk.Treeview(
            tree_frame, columns=("status", "reason"),
            show="tree headings", selectmode="extended",
        )
        tree.heading("#0", text="Title / file")
        tree.heading("status", text="Action")
        tree.heading("reason", text="Reason")
        tree.column("#0", width=440, stretch=True)
        tree.column("status", width=110, stretch=False, anchor="w")
        tree.column("reason", width=420, stretch=True)
        scrollbar = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=tree.yview,
        )
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.ttk.Label(
            win,
            text=(f"  {self._CURATE_RETIRE_GLYPH} = will be retired  "
                  f"  {self._CURATE_SKIP_GLYPH} = kept (vetoed)  "
                  "  — Click a retire row and press Space or double-click to toggle."),
            foreground=_FG_DIM,
        ).pack(anchor="w", padx=8, pady=(0, 2))

        # iid → (group_index, retire_path). Only retire rows are in here;
        # keep rows aren't toggleable so don't need an entry.
        retire_iids: dict[str, tuple] = {}
        # group_index → CurationGroup, to round-trip into apply_curation.
        groups_by_idx: dict[int, object] = {}

        # ── Worker: run curate_system on a thread, post result via after() ──
        def worker() -> None:
            from . import curate as curate_mod
            try:
                cfg = load_config()
                prefs = (curate_mod.parse_regions(regions) if regions
                         else list(cfg.region_preferences))
                groups = curate_mod.curate_system(
                    system, cfg,
                    preferences=prefs,
                    prefer_revision_latest=prefer_latest,
                    prefer_no_proto=prefer_no_proto,
                )
            except Exception as exc:  # noqa: BLE001 — surface in UI
                # `exc` is deleted when the except block exits (PEP
                # 3134), and `root.after(0, ...)` fires asynchronously
                # — bind `exc` at lambda-creation time so the deferred
                # callback can still read it.
                self.root.after(0, lambda _exc=exc: status_var.set(
                    f"Error scanning {system}: {_exc}",
                ))
                return
            self.root.after(0, populate, groups)

        def populate(groups) -> None:
            if not groups:
                status_var.set(
                    f"No multi-variant titles found for {system}. "
                    "Either every title has only one variant, or your "
                    "filters retired everything (try toggling "
                    "--include-proto).",
                )
                return
            total_retire = sum(len(g.retire) for g in groups)
            status_var.set(
                f"{len(groups)} title(s) with {total_retire} retire "
                "candidate(s). Click a row and press Space (or "
                "double-click) to toggle a retirement on/off. Then "
                "click Apply to commit only the rows still marked "
                f"{self._CURATE_RETIRE_GLYPH}."
            )
            for g_idx, g in enumerate(groups):
                groups_by_idx[g_idx] = g
                parent = tree.insert(
                    "", "end",
                    text=f"{g.title}  ({1 + len(g.retire)} variants)",
                    values=("", ""), open=False,
                )
                # Keep row first (no checkbox; can't be vetoed).
                tree.insert(
                    parent, "end",
                    text=f"      {g.keep.name}",
                    values=("KEEP", g.reasons.get(g.keep.name, "")),
                )
                for r in g.retire:
                    iid = tree.insert(
                        parent, "end",
                        text=f"  {self._CURATE_RETIRE_GLYPH}  {r.name}",
                        values=("RETIRE", g.reasons.get(r.name, "")),
                    )
                    retire_iids[iid] = (g_idx, r)

        def toggle_selected(_evt=None) -> None:
            for iid in tree.selection():
                if iid not in retire_iids:
                    continue
                text = tree.item(iid, "text")
                if self._CURATE_RETIRE_GLYPH in text:
                    new = text.replace(
                        self._CURATE_RETIRE_GLYPH,
                        self._CURATE_SKIP_GLYPH, 1,
                    )
                    tree.item(iid, text=new, values=("SKIP",
                              tree.item(iid, "values")[1]))
                elif self._CURATE_SKIP_GLYPH in text:
                    new = text.replace(
                        self._CURATE_SKIP_GLYPH,
                        self._CURATE_RETIRE_GLYPH, 1,
                    )
                    tree.item(iid, text=new, values=("RETIRE",
                              tree.item(iid, "values")[1]))

        tree.bind("<space>", toggle_selected)
        tree.bind("<Double-Button-1>", toggle_selected)

        # ── Bottom bar ──────────────────────────────────────────────────────
        btn_row = self.ttk.Frame(win)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        self.ttk.Label(
            btn_row,
            text=("Action:"),
        ).pack(side="left")
        action_var = self.tk.StringVar(value=self._curate_action_var.get())
        self.ttk.Combobox(
            btn_row, textvariable=action_var,
            values=["archive", "delete"], state="readonly", width=10,
        ).pack(side="left", padx=4)

        def apply() -> None:
            self._apply_curate_preview(
                win, system, retire_iids, groups_by_idx, tree, action_var.get(),
            )

        self.ttk.Button(
            btn_row, text="Apply selected retirements",
            command=apply,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Toggle selected", command=toggle_selected,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Close", command=win.destroy,
        ).pack(side="right")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_curate_preview(
        self, win, system: str, retire_iids: dict, groups_by_idx: dict,
        tree, action: str,
    ) -> None:
        """Build a filtered list of CurationGroups from the tree state and
        run ``apply_curation`` against it.

        Per-group rule: drop retire entries the user un-checked. If a
        group ends up with zero retirements, drop the whole group — the
        CLI's ``--undo`` only stores groups with at least one retire.
        """
        from . import curate as curate_mod

        # Bucket the still-checked retire paths by group index.
        retain: dict[int, list] = {}
        for iid, (g_idx, retire_path) in retire_iids.items():
            text = tree.item(iid, "text")
            if self._CURATE_RETIRE_GLYPH in text:
                retain.setdefault(g_idx, []).append(retire_path)

        if not retain:
            self._flash_validation(
                "Nothing to apply — every retirement is unchecked. "
                f"Toggle some rows back to {self._CURATE_RETIRE_GLYPH} "
                "and try again."
            )
            return

        filtered = []
        for g_idx, kept_retires in retain.items():
            g = groups_by_idx[g_idx]
            filtered.append(curate_mod.CurationGroup(
                title=g.title, keep=g.keep,
                retire=sorted(kept_retires, key=lambda p: p.name.lower()),
                reasons=g.reasons,
            ))

        # Confirm before destructive action — `delete` has no undo.
        if action == "delete":
            if not self.messagebox.askyesno(
                "Confirm DELETE",
                f"Delete {sum(len(g.retire) for g in filtered)} ROM "
                f"file(s) across {len(filtered)} title(s)?\n\n"
                "There is NO undo for delete. Use 'archive' if you "
                "might want to recover them later.",
            ):
                return
        else:
            if not self.messagebox.askyesno(
                "Confirm archive",
                f"Archive {sum(len(g.retire) for g in filtered)} ROM "
                f"file(s) across {len(filtered)} title(s) under "
                f"<roms_dir>/{system}/_retired/?\n\n"
                "Reversible: open the History tab → Browse manifests / undo… "
                "and pick the run you want to reverse.",
            ):
                return

        # apply_curation moves or deletes ROM files — on a large run
        # this can block for many seconds. Run on a worker thread so
        # the window keeps redrawing; marshal results back via after(0).
        cfg = load_config()
        self._set_status(
            f"Curating {sum(len(g.retire) for g in filtered)} file(s) "
            f"({action})…"
        )

        def _worker(filtered=filtered, cfg=cfg, system=system, action=action):
            try:
                return curate_mod.apply_curation(
                    filtered, cfg, system, action=action,
                ), None
            except Exception as exc:  # noqa: BLE001 — surface in UI
                return None, exc

        def _on_done(payload, exc):
            if exc is not None:
                self._set_status("Curate failed.")
                self.messagebox.showerror(
                    "Curate failed", f"{type(exc).__name__}: {exc}",
                )
                return
            result, manifest = payload
            msg_parts = []
            if result.archived:
                msg_parts.append(f"{len(result.archived)} archived")
            if result.deleted:
                msg_parts.append(f"{len(result.deleted)} deleted")
            if result.skipped:
                msg_parts.append(f"{len(result.skipped)} skipped")
            msg = ", ".join(msg_parts) or "nothing"
            output_text = (
                f"\n[curate] {system}: {msg}.\n"
                f"  manifest: {manifest}\n" if manifest
                else f"\n[curate] {system}: {msg}.\n"
            )
            self._append_output(output_text)
            record = _RunRecord(
                started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                argv_str=f"curate apply {action} {system}",
                dry_run=False,
            )
            record.append(output_text)
            record.exit_code = 0
            self._run_history.append(record)
            self._refresh_logs_tab()
            self._set_status(f"Curate done: {msg}.")
            self.messagebox.showinfo(
                "Curate done",
                f"{msg}.\n\n"
                + (f"Manifest: {manifest}\n"
                   "Reverse via Logs & Manifests viewer → Undo this run."
                   if manifest
                   else "No manifest written (delete leaves no undo)."),
            )
            win.destroy()

        def _run_in_thread():
            payload, exc = _worker()
            self.root.after(0, _on_done, payload, exc)

        threading.Thread(target=_run_in_thread, daemon=True).start()

    def _cleanup_reset_cats(self) -> None:
        for key, _lbl, safe in _CLEANUP_CATEGORIES:
            var = self._cleanup_cat_vars.get(key)
            if var is not None:
                var.set(safe)

    def _run_cleanup(self) -> None:
        selected_safe   = [k for k, _l, s in _CLEANUP_CATEGORIES if s     and self._cleanup_cat_vars.get(k, self.tk.BooleanVar()).get()]
        selected_unsafe = [k for k, _l, s in _CLEANUP_CATEGORIES if not s and self._cleanup_cat_vars.get(k, self.tk.BooleanVar()).get()]
        selected = selected_safe + selected_unsafe
        if not selected:
            self.messagebox.showwarning(
                "Nothing selected",
                "Tick at least one category before running cleanup.",
            )
            return
        args = ["cleanup", "run"]
        args += ["--include", ",".join(selected)]
        if selected_unsafe:
            args.append("--include-unsafe")
        older = self._cleanup_older_var.get().strip()
        if older and older != "0":
            if not older.isdigit():
                self.messagebox.showwarning(
                    "Invalid value",
                    "Older-than must be a non-negative integer (days).",
                )
                return
            args += ["--older-than", older]
        if self._global_apply_var.get():
            args += ["--apply", "--yes"]
        self._run_cli("spindoctor", args)

    def _run_ignore(self, sub: str) -> None:
        game = self._ignore_game_var.get().strip()
        if not game:
            self.messagebox.showwarning(
                "Game name required",
                "Select a system first to load the game list, then pick a game.",
            )
            return
        args = ["ignore", sub, game]
        system = self._ignore_system_var.get().strip()
        if system:
            args += ["--system", system]
        self._run_cli("spindoctor", args)

    def _run_ignore_list(self) -> None:
        args = ["ignore", "list"]
        system = self._ignore_system_var.get().strip()
        if system:
            args += ["--system", system]
        self._run_cli("spindoctor", args)

    # Sentinel value used by the ignore viewer's system dropdown for the
    # cross-system "_global" bucket. The CLI uses `_global` literally,
    # but a label is friendlier to a UI user who's never read the
    # config schema.
    _IGNORE_GLOBAL_LABEL = "_global  (cross-system)"

    def _show_ignore_viewer(self) -> None:
        """Open a Toplevel listing every ignored entry for the picked
        system, with a "Remove selected" button that updates config.

        Closes the loop with `audit` / `fetch-meta` skipping logic:
        you can finally see what's currently being skipped *and*
        un-ignore something with a click, without grepping
        ``~/.spindoctor/config.json``.
        """
        win = self.tk.Toplevel(self.root)
        win.title(f"{__app_name__} — Ignore list viewer")
        self._fit_geometry(win, 700, 520)
        win.transient(self.root)

        self.ttk.Label(
            win,
            text=("Every entry on the ignore list for the selected "
                  "system. The `_global` bucket applies cross-system "
                  "(matches `cfg.is_ignored(rom, system)` for every "
                  "system). Pick rows and click Remove selected to "
                  "un-ignore them — saves immediately to "
                  "~/.spindoctor/config.json."),
            wraplength=680, justify="left", padding=(10, 6),
        ).pack(fill="x")

        # ── System picker ──────────────────────────────────────────────
        picker_row = self.ttk.Frame(win)
        picker_row.pack(fill="x", padx=8, pady=2)
        self.ttk.Label(picker_row, text="System").pack(side="left")
        sys_var = self.tk.StringVar()
        sys_combo = self.ttk.Combobox(
            picker_row, textvariable=sys_var, state="readonly", width=40,
        )
        sys_combo.pack(side="left", padx=6, fill="x", expand=True)
        count_var = self.tk.StringVar(value="")
        self.ttk.Label(picker_row, textvariable=count_var, width=24).pack(
            side="right", padx=6,
        )

        # ── Listbox ────────────────────────────────────────────────────
        list_frame = self.ttk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=8, pady=4)
        listbox = self.tk.Listbox(list_frame, selectmode="extended")
        scrollbar = self.ttk.Scrollbar(
            list_frame, orient="vertical", command=listbox.yview,
        )
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def picked_system() -> str:
            """Map the dropdown's display label back to the storage key."""
            label = sys_var.get()
            if label == self._IGNORE_GLOBAL_LABEL:
                return "_global"
            return label

        def refresh_systems() -> None:
            cfg = load_config()
            # Include every key with at least one entry, plus _global
            # always so the user can pick it even when empty (so they
            # can confirm "nothing's ignored cross-system").
            keys = [k for k, v in (cfg.ignore_lists or {}).items() if v]
            display = []
            if "_global" in keys:
                keys.remove("_global")
            display.append(self._IGNORE_GLOBAL_LABEL)
            display.extend(sorted(keys))
            sys_combo["values"] = display
            # Default selection: prefer the system field on the Curate
            # tab if it's filled and present, else the first non-_global,
            # else _global.
            preferred = self._ignore_system_var.get().strip()
            if preferred and preferred in keys:
                sys_var.set(preferred)
            elif keys:
                sys_var.set(sorted(keys)[0])
            else:
                sys_var.set(self._IGNORE_GLOBAL_LABEL)

        def refresh_list(_evt=None) -> None:
            listbox.delete(0, "end")
            cfg = load_config()
            entries = sorted(
                cfg.ignore_lists.get(picked_system(), []),
                key=str.lower,
            )
            for name in entries:
                listbox.insert("end", name)
            count_var.set(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")

        sys_combo.bind("<<ComboboxSelected>>", refresh_list)

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = self.ttk.Frame(win)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))

        def remove_selected() -> None:
            selection = listbox.curselection()
            if not selection:
                self._flash_validation(
                    "Nothing selected — click one or more entries "
                    "first (Ctrl/Shift-click for multi-select)."
                )
                return
            target = picked_system()
            names = [listbox.get(i) for i in selection]
            if not self.messagebox.askyesno(
                "Remove from ignore list?",
                f"Remove {len(names)} entr{'y' if len(names) == 1 else 'ies'} "
                f"from the '{target}' ignore list?\n\n"
                + "\n".join(f"  · {n}" for n in names[:10])
                + ("\n  …" if len(names) > 10 else "")
                + "\n\nAffects audit / fetch-meta skipping immediately.",
            ):
                return
            cfg = load_config()
            removed = 0
            for name in names:
                if cfg.remove_ignore(name, target):
                    removed += 1
            save_config(cfg)
            output_text = (
                f"\n[ignore viewer] removed {removed}/{len(names)} entr"
                f"{'y' if len(names) == 1 else 'ies'} from '{target}'.\n"
            )
            self._append_output(output_text)
            record = _RunRecord(
                started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                argv_str=f"ignore remove {target}",
                dry_run=False,
            )
            record.append(output_text)
            record.exit_code = 0
            self._run_history.append(record)
            self._refresh_logs_tab()
            self._set_status(
                f"Removed {removed} entr{'y' if removed == 1 else 'ies'} "
                f"from '{target}'."
            )
            refresh_systems()
            refresh_list()

        self.ttk.Button(
            btn_row, text="Remove selected", command=remove_selected,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Refresh",
            command=lambda: (refresh_systems(), refresh_list()),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Open config.json",
            command=self._open_config_file,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Close", command=win.destroy,
        ).pack(side="right")

        refresh_systems()
        refresh_list()

    # ── Systems tab (Main menu carousel + system management) ─────────────────

    def _build_systems_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Manage HyperSpin's game systems — reorder the main menu "
                  "wheel, add new systems, and organize sort order. To add, "
                  "remove, or rename individual games, use the Games tab. "
                  "Follow the numbered Steps in sequence when setting up a "
                  "new system for the first time, or jump to the step you need."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # ── Step 1 — Main menu carousel (formerly Main Menu tab) ────────────
        # All I/O on Main Menu.xml goes through spindoctor.mainmenu —
        # the same module the CLI uses. The GUI never parses or writes
        # the XML itself; that would be a parallel implementation and
        # is exactly what caused the previous Main Menu corruption bug.
        self._mm_data: list[dict] = []  # [{system, enabled}]

        mm_lf = self.ttk.LabelFrame(frame, text="Step 1 — Main menu carousel")
        mm_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            mm_lf,
            text=("Edit the order and visibility of systems on HyperSpin's "
                  "top-level wheel (Main Menu.xml). Click Refresh to load "
                  "the current order, drag-select a row then use Move Up / "
                  "Move Down (or Alt+Up / Alt+Down) to reposition it one "
                  "step at a time, or type a position number and press Go to "
                  "jump directly. Toggle Visible to hide/unhide, then Save "
                  "Order to write all changes at once."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 8))

        # Treeview
        tree_frame = self.ttk.Frame(mm_lf)
        tree_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=(0, 4))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._mm_tree = self.ttk.Treeview(
            tree_frame,
            columns=("pos", "system", "visible"),
            show="headings",
            selectmode="browse",
            height=16,
        )
        self._mm_tree.heading("pos",     text="#",       anchor="center")
        self._mm_tree.heading("system",  text="System",  anchor="w")
        self._mm_tree.heading("visible", text="Visible", anchor="center")
        self._mm_tree.column("pos",     width=50,  stretch=False, anchor="center")
        self._mm_tree.column("system",  width=340, stretch=True,  anchor="w")
        self._mm_tree.column("visible", width=80,  stretch=False, anchor="center")
        self._mm_tree.tag_configure("hidden", foreground=_FG_DIMMER)

        vsb = self.ttk.Scrollbar(tree_frame, orient="vertical",
                                 command=self._mm_tree.yview)
        self._mm_tree.configure(yscrollcommand=vsb.set)
        self._mm_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._mm_tree.bind("<Alt-Up>",   lambda e: self._mm_move_up())
        self._mm_tree.bind("<Alt-Down>", lambda e: self._mm_move_down())

        # Table action buttons
        tbl_btn_row = self.ttk.Frame(mm_lf)
        tbl_btn_row.grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 8))
        self.ttk.Button(
            tbl_btn_row, text="Refresh",
            command=self._mm_refresh,
        ).pack(side="left")
        self.ttk.Button(
            tbl_btn_row, text="Move Up",
            command=self._mm_move_up,
        ).pack(side="left", padx=(6, 2))
        self.ttk.Button(
            tbl_btn_row, text="Move Down",
            command=self._mm_move_down,
        ).pack(side="left", padx=2)
        self._mm_goto_var = self.tk.StringVar()
        self.ttk.Label(tbl_btn_row, text="Move to #").pack(side="left", padx=(8, 2))
        self.ttk.Entry(tbl_btn_row, textvariable=self._mm_goto_var, width=4).pack(side="left")
        self.ttk.Button(
            tbl_btn_row, text="Go",
            command=self._mm_move_to_pos,
        ).pack(side="left", padx=(2, 0))
        self.ttk.Button(
            tbl_btn_row, text="Toggle Visible",
            command=self._mm_toggle_visible,
        ).pack(side="left", padx=(6, 2))
        self.ttk.Button(
            tbl_btn_row, text="Save Order",
            command=self._mm_save_order,
        ).pack(side="left", padx=(20, 0))
        self.ttk.Button(
            tbl_btn_row, text="Restore from backup…",
            command=self._mm_restore_from_backup,
        ).pack(side="left", padx=(6, 0))

        # Sort
        sort_frame = self.ttk.LabelFrame(mm_lf, text="Sort all systems")
        sort_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))

        self.ttk.Label(sort_frame, text="Strategy").grid(
            row=0, column=0, sticky="w", padx=6, pady=4,
        )
        self._mainmenu_sort_var = self.tk.StringVar(value="alpha")
        self.ttk.Combobox(
            sort_frame, textvariable=self._mainmenu_sort_var,
            values=["alpha", "manufacturer", "year"],
            state="readonly", width=14,
        ).grid(row=0, column=1, sticky="w", padx=4)
        self.ttk.Button(
            sort_frame, text="Sort", command=self._run_mainmenu_sort,
        ).grid(row=0, column=2, sticky="w", padx=4, pady=4)

        # Add / Remove
        mgmt_frame = self.ttk.LabelFrame(mm_lf, text="Add / Remove system")
        mgmt_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 8))
        mgmt_frame.columnconfigure(1, weight=1)

        self.ttk.Label(mgmt_frame, text="System").grid(
            row=0, column=0, sticky="w", padx=6, pady=4,
        )
        self._mainmenu_system_var = self.tk.StringVar()
        self._mainmenu_system_combo = self.ttk.Combobox(
            mgmt_frame, textvariable=self._mainmenu_system_var,
            state="readonly", width=40,
        )
        self._mainmenu_system_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        mgmt_btn_row = self.ttk.Frame(mgmt_frame)
        mgmt_btn_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))
        for label, sub in (("Add", "add"), ("Remove", "remove")):
            self.ttk.Button(
                mgmt_btn_row, text=label,
                command=lambda s=sub: self._run_mainmenu_action(s),
            ).pack(side="left", padx=2)

        mm_lf.columnconfigure(0, weight=1)
        mm_lf.rowconfigure(1, weight=1)

        # Defer the XML parse + tree population until the rest of the
        # GUI has painted. Doing it inline used to delay first-paint by
        # 1–3 seconds on slow drives.
        self.root.after_idle(self._mm_refresh)

        # ── Step 2 — Add a new system ────────────────────────────────────────
        add_frame = self.ttk.LabelFrame(frame, text="Step 2 — Add a new system")
        add_frame.pack(fill="x", pady=(4, 4))
        add_row = self.ttk.Frame(add_frame)
        add_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(add_row, text="System name").pack(side="left")
        self._systems_name_var = self.tk.StringVar()
        self.ttk.Entry(
            add_row, textvariable=self._systems_name_var, width=40,
        ).pack(side="left", padx=6, fill="x", expand=True)

        flags_row = self.ttk.Frame(add_frame)
        flags_row.pack(fill="x", padx=6, pady=2)
        self._systems_no_sys_media_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Skip system artwork download",
            variable=self._systems_no_sys_media_var,
        ).pack(side="left")
        self._systems_no_game_media_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Skip per-game artwork download",
            variable=self._systems_no_game_media_var,
        ).pack(side="left", padx=10)
        self._add_pc_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            flags_row, text="Overwrite existing launcher configs",
            variable=self._add_pc_overwrite_var,
        ).pack(side="left", padx=10)

        add_btns = self.ttk.Frame(add_frame)
        add_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            add_btns, text="Add Arcade System",
            command=lambda: self._run_add_system(False),
        ).pack(side="left")
        self.ttk.Button(
            add_btns, text="Add PC System",
            command=lambda: self._run_add_system(True),
        ).pack(side="left", padx=6)
        self.ttk.Label(
            add_btns,
            text=("PC System auto-accepts the best title for each game. "
                  "Use 'Add / Refresh Games' below to pick up new installs after initial setup."),
            foreground=_FG_DIM,
        ).pack(side="left", padx=10)

        # ── Organize a system ────────────────────────────────────────────────
        # `organize` does two things: (a) writes sort wheels (per-axis
        # sub-databases under Databases/<sys>/{Genre,Year,...}) so
        # HyperSpin can show "Sort by …", (b) for systems that need
        # per-game folders (PS3, multi-disc PS2/Saturn/Dreamcast) plans
        # ROM restructuring with an undo manifest. Restructure honours
        # the tab-level Apply checkbox.
        org_frame = self.ttk.LabelFrame(
            frame, text="Step 3 — Organize a system (sort wheels + optional restructure)",
        )
        org_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            org_frame,
            text=("Sort wheels add 'Sort by Genre / Year / Letter / "
                  "Manufacturer' sub-wheels to HyperSpin without touching "
                  "ROMs. Restructure (opt-in) plans per-game folders for "
                  "PS3 / multi-disc systems; honours Apply above for "
                  "real file moves and writes an undo manifest."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(2, 4))

        org_row = self.ttk.Frame(org_frame)
        org_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(org_row, text="System").pack(side="left")
        self._organize_system_var = self.tk.StringVar()
        self._organize_system_combo = self.ttk.Combobox(
            org_row, textvariable=self._organize_system_var,
            state="readonly", width=24,
        )
        self._organize_system_combo.pack(side="left", padx=6)
        self._organize_no_sort_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            org_row, text="Skip sort wheels",
            variable=self._organize_no_sort_var,
        ).pack(side="left", padx=10)
        self._organize_restructure_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            org_row, text="Restructure ROMs into per-game subfolders",
            variable=self._organize_restructure_var,
        ).pack(side="left", padx=10)
        self._organize_overwrite_sort_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            org_row, text="Overwrite existing sort files",
            variable=self._organize_overwrite_sort_var,
        ).pack(side="left", padx=10)

        org_btns = self.ttk.Frame(org_frame)
        org_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            org_btns, text="Build Sort Wheels",
            command=self._run_organize,
        ).pack(side="left")
        self.ttk.Button(
            org_btns, text="Undo latest restructure",
            command=self._run_organize_undo,
        ).pack(side="left", padx=6)

        # ── Per-system overrides ─────────────────────────────────────────────
        # Surfaces `config system set` so users with niche systems
        # (homebrew consoles, PC libraries, custom MAME variants) can
        # configure scraper IDs, ROM extensions, layout, and emulator
        # without crafting an exact CLI invocation. Most cabinet owners
        # never need this — stock systems Just Work — but for the ~5%
        # who do, this was previously CLI-only territory.
        ovr_frame = self.ttk.LabelFrame(frame, text="Per-system overrides")
        ovr_frame.pack(fill="x", pady=(4, 4))
        self.ttk.Label(
            ovr_frame,
            text=("Customise scraper IDs, ROM extensions, layout, "
                  "and emulator for one system. Leave any field blank "
                  "to inherit SpinDoctor's defaults. Run 'Show config "
                  "— system list' above to see what's currently set."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(2, 4))

        ovr_top = self.ttk.Frame(ovr_frame)
        ovr_top.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(ovr_top, text="System").pack(side="left")
        self._ovr_system_var = self.tk.StringVar()
        self._ovr_system_combo = self.ttk.Combobox(
            ovr_top, textvariable=self._ovr_system_var,
            state="readonly", width=28,
        )
        self._ovr_system_combo.pack(side="left", padx=6)
        self.ttk.Button(
            ovr_top, text="Load current values",
            command=self._load_system_override,
        ).pack(side="left", padx=10)

        ovr_form = self.ttk.Frame(ovr_frame)
        ovr_form.pack(fill="x", padx=6, pady=4)
        # Compact 2-column grid keeps the form scannable.
        self._ovr_ss_id_var = self.tk.StringVar()
        self._ovr_tgdb_id_var = self.tk.StringVar()
        self._ovr_exts_var = self.tk.StringVar()
        self._ovr_layout_var = self.tk.StringVar()
        self._ovr_emulator_var = self.tk.StringVar()
        self._ovr_rom_path_var = self.tk.StringVar()

        rows: list[tuple[str, "tk_mod.StringVar", str]] = [  # noqa: F821
            ("ScreenScraper ID (int)",   self._ovr_ss_id_var,    ""),
            ("TheGamesDB ID (int)",      self._ovr_tgdb_id_var,  ""),
            ("ROM extensions (csv)",     self._ovr_exts_var,
             "e.g. .ps7,iso  — leading dot optional"),
            ("Emulator",                 self._ovr_emulator_var,
             "RocketLauncher emulator name (RetroArch, Daphne, …)"),
            ("ROM folder path",          self._ovr_rom_path_var,
             "Overrides roms_dir\\<System> for generate-config (e.g. J:\\Games\\3DO)"),
        ]
        for r, (label, var, hint) in enumerate(rows):
            self.ttk.Label(ovr_form, text=label).grid(
                row=r, column=0, sticky="w", padx=(0, 6), pady=2,
            )
            self.ttk.Entry(
                ovr_form, textvariable=var, width=24,
            ).grid(row=r, column=1, sticky="w", pady=2)
            if hint:
                self.ttk.Label(
                    ovr_form, text=hint, foreground=_FG_DIMMER,
                ).grid(row=r, column=2, sticky="w", padx=8, pady=2)

        # Layout is a closed set; render as a Combobox so users don't
        # have to memorise the three valid strings.
        layout_row = len(rows)
        self.ttk.Label(ovr_form, text="Layout").grid(
            row=layout_row, column=0, sticky="w", padx=(0, 6), pady=2,
        )
        self.ttk.Combobox(
            ovr_form, textvariable=self._ovr_layout_var,
            values=["", "per-game-folder", "multi-disc-m3u", "flat"],
            state="readonly", width=22,
        ).grid(row=layout_row, column=1, sticky="w", pady=2)
        self.ttk.Label(
            ovr_form,
            text="(blank = inherit default; 'flat' disables a built-in rule)",
            foreground=_FG_DIMMER,
        ).grid(row=layout_row, column=2, sticky="w", padx=8, pady=2)

        ovr_btns = self.ttk.Frame(ovr_frame)
        ovr_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            ovr_btns, text="Save override",
            command=self._save_system_override,
        ).pack(side="left")
        self.ttk.Button(
            ovr_btns, text="Clear form",
            command=self._clear_system_override_form,
        ).pack(side="left", padx=6)

        # ── List existing systems ─────────────────────────────────────────────
        list_frame = self.ttk.LabelFrame(frame, text="Inspect")
        list_frame.pack(fill="x", pady=(4, 4))
        list_btns = self.ttk.Frame(list_frame)
        list_btns.pack(anchor="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            list_btns, text="List systems",
            command=lambda: self._run_cli("spindoctor", ["systems"]),
        ).pack(side="left")
        self.ttk.Button(
            list_btns, text="Show config — system list",
            command=lambda: self._run_cli(
                "spindoctor", ["config", "system", "list"],
            ),
        ).pack(side="left", padx=6)

        return frame

    def _load_system_override(self) -> None:
        """Populate the override form from the saved overrides for
        the currently-picked system."""
        sys_ = self._ovr_system_var.get().strip()
        if not sys_:
            self.messagebox.showwarning(
                "Pick a system",
                "Choose a system from the dropdown first.",
            )
            return
        try:
            from .config import get_system_overrides, reset_override_cache
            reset_override_cache()  # force re-read from disk
            overrides = get_system_overrides()
        except Exception as exc:  # noqa: BLE001
            self.messagebox.showerror(
                "Could not load overrides", str(exc),
            )
            return
        current = overrides.get(sys_, {})
        # Numeric IDs render as strings in the entry; blank if absent.
        ss = current.get("screenscraper_id")
        self._ovr_ss_id_var.set("" if ss is None else str(ss))
        tg = current.get("thegamesdb_id")
        self._ovr_tgdb_id_var.set("" if tg is None else str(tg))
        exts = current.get("rom_extensions") or []
        # Strip leading dots when displaying — the CLI accepts both
        # with and without; the form-builder reads them back the same.
        self._ovr_exts_var.set(",".join(
            e.lstrip(".") for e in exts
        ))
        self._ovr_layout_var.set(current.get("layout") or "")
        self._ovr_emulator_var.set(current.get("emulator") or "")
        self._ovr_rom_path_var.set(current.get("rom_path") or "")
        if not current:
            self._set_status(
                f"No override saved for '{sys_}' yet — fill the form "
                "and click Save."
            )

    def _clear_system_override_form(self) -> None:
        for var in (
            self._ovr_ss_id_var, self._ovr_tgdb_id_var,
            self._ovr_exts_var, self._ovr_layout_var,
            self._ovr_emulator_var, self._ovr_rom_path_var,
        ):
            var.set("")

    def _save_system_override(self) -> None:
        """Build a `config system set` argv from the form and run it.

        Only fields the user filled in get forwarded — empty entries
        leave the corresponding CLI flag off, which (per the CLI's
        own semantics) means "don't touch that key".
        """
        sys_ = self._ovr_system_var.get().strip()
        if not sys_:
            self.messagebox.showwarning(
                "Pick a system",
                "Choose a system from the dropdown first.",
            )
            return
        args = ["config", "system", "set", sys_]
        ss = self._ovr_ss_id_var.get().strip()
        if ss:
            try:
                int(ss)
            except ValueError:
                self.messagebox.showerror(
                    "Invalid ScreenScraper ID",
                    f"Must be an integer; got {ss!r}.",
                )
                return
            args += ["--screenscraper-id", ss]
        tg = self._ovr_tgdb_id_var.get().strip()
        if tg:
            try:
                int(tg)
            except ValueError:
                self.messagebox.showerror(
                    "Invalid TheGamesDB ID",
                    f"Must be an integer; got {tg!r}.",
                )
                return
            args += ["--thegamesdb-id", tg]
        exts = self._ovr_exts_var.get().strip()
        if exts:
            args += ["--rom-extensions", exts]
        layout = self._ovr_layout_var.get().strip()
        if layout:
            args += ["--layout", layout]
        emu = self._ovr_emulator_var.get().strip()
        if emu:
            args += ["--emulator", emu]
        rom_path = self._ovr_rom_path_var.get().strip()
        if rom_path:
            args += ["--rom-path", rom_path]
        # No field provided beyond the system name? Bail with a hint.
        if len(args) == 4:
            self._flash_validation(
                "Nothing to save — fill in at least one field first "
                "(only the keys you provide get written)."
            )
            return
        self._run_cli("spindoctor", args)

    def _run_organize(self) -> None:
        sys_ = self._organize_system_var.get().strip()
        if not sys_:
            self.messagebox.showwarning(
                "System required", "Pick a system from the dropdown.",
            )
            return
        args = ["organize", sys_]
        if self._organize_no_sort_var.get():
            args.append("--no-sort")
        if self._organize_overwrite_sort_var.get():
            args.append("--overwrite-sort")
        if self._organize_restructure_var.get():
            args.append("--restructure")
            # Restructure honours the same Apply checkbox as add-system /
            # rename / clone above so users don't accidentally move ROMs
            # while learning the tool. Sort-wheel writes are XML-only and
            # always live (no apply flag exists for them).
            if self._global_apply_var.get():
                args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_organize_undo(self) -> None:
        sys_ = self._organize_system_var.get().strip()
        if not sys_:
            self.messagebox.showwarning(
                "System required",
                "Pick the system whose restructure you want to undo.",
            )
            return
        if not self.messagebox.askyesno(
            "Undo restructure?",
            f"Reverse the latest 'organize --restructure --apply' for "
            f"'{sys_}'? Files will be moved back to their original "
            "locations using the saved manifest.",
        ):
            return
        self._run_cli("spindoctor", ["organize", sys_, "--undo"])

    def _load_games_for_system(self, system: str) -> list:
        try:
            cfg = load_config()
            db = load_database(system, cfg.databases_dir)
            return sorted(db.games().keys())
        except Exception as exc:  # noqa: BLE001
            log.warning("_load_games_for_system(%r): %s", system, exc)
            return []

    # ── Game Wheel Manager handlers ──────────────────────────────────────────

    def _gwm_on_system_change(self) -> None:
        """Clear loaded game data when the system dropdown is changed."""
        self._gwm_data = []
        self._gwm_loaded_system = ""
        self._gwm_repopulate_tree()
        self._gwm_count_label.configure(text="")

    def _gwm_load(self) -> None:
        system = self._gwm_system_var.get().strip()
        if not system:
            self._set_status("Select a system first.")
            return
        try:
            cfg = load_config()
            db = load_database(system, cfg.databases_dir)
            games = list(db.iter_xml_order())
        except Exception as exc:  # noqa: BLE001
            self.messagebox.showerror("Load failed", str(exc))
            return
        self._gwm_data = [{"name": g.name, "description": g.description} for g in games]
        self._gwm_loaded_system = system
        self._gwm_repopulate_tree()
        count = len(self._gwm_data)
        self._gwm_count_label.configure(text=f"{count} game{'s' if count != 1 else ''}")
        self._set_status(f"Loaded {count} games from {system}.")

    def _gwm_repopulate_tree(self) -> None:
        self._gwm_tree.delete(*self._gwm_tree.get_children())
        for i, entry in enumerate(self._gwm_data, 1):
            self._gwm_tree.insert("", "end", iid=str(i), values=(
                i, entry["name"], entry["description"],
            ))

    def _gwm_selected_index(self) -> int:
        sel = self._gwm_tree.selection()
        if not sel:
            return -1
        return int(sel[0]) - 1  # iid is 1-based

    def _gwm_move_up(self) -> None:
        idx = self._gwm_selected_index()
        if idx < 0:
            self._set_status("Select a game in the table first.")
            return
        if idx == 0:
            self._set_status("Already at the top.")
            return
        self._gwm_data[idx], self._gwm_data[idx - 1] = (
            self._gwm_data[idx - 1], self._gwm_data[idx]
        )
        self._gwm_repopulate_tree()
        new_iid = str(idx)
        self._gwm_tree.selection_set(new_iid)
        self._gwm_tree.see(new_iid)

    def _gwm_move_down(self) -> None:
        idx = self._gwm_selected_index()
        if idx < 0:
            self._set_status("Select a game in the table first.")
            return
        if idx >= len(self._gwm_data) - 1:
            self._set_status("Already at the bottom.")
            return
        self._gwm_data[idx], self._gwm_data[idx + 1] = (
            self._gwm_data[idx + 1], self._gwm_data[idx]
        )
        self._gwm_repopulate_tree()
        new_iid = str(idx + 2)
        self._gwm_tree.selection_set(new_iid)
        self._gwm_tree.see(new_iid)

    def _gwm_move_to_pos(self) -> None:
        idx = self._gwm_selected_index()
        if idx < 0:
            self._set_status("Select a game in the table first.")
            return
        raw = self._gwm_goto_var.get().strip()
        try:
            target = int(raw)
        except ValueError:
            self._set_status("Enter a valid position number.")
            return
        total = len(self._gwm_data)
        if not 1 <= target <= total:
            self._set_status(f"Position must be between 1 and {total}.")
            return
        target_idx = target - 1
        if target_idx == idx:
            return
        item = self._gwm_data.pop(idx)
        self._gwm_data.insert(target_idx, item)
        self._gwm_repopulate_tree()
        iid = str(target)
        self._gwm_tree.selection_set(iid)
        self._gwm_tree.see(iid)

    def _gwm_sort(self, key: str) -> None:
        """Sort the in-memory game list alphabetically by *key* ('description' or 'name').

        Falls back to ROM name when description is blank so no entry
        floats to the top as an empty string.
        """
        if not self._gwm_data:
            self._set_status("Load a system's games first.")
            return
        label = "title" if key == "description" else "ROM name"

        def _sort_key(entry: dict) -> str:
            value = (entry.get(key) or "").strip()
            if not value:
                value = (entry.get("name") or "").strip()
            # Strip leading "The ", "A ", "An " for natural sort (same as HyperSpin).
            lower = value.lower()
            for article in ("the ", "a ", "an "):
                if lower.startswith(article):
                    value = value[len(article):]
                    break
            return value.lower()

        self._gwm_data.sort(key=_sort_key)
        self._gwm_repopulate_tree()
        self._set_status(f"Sorted {len(self._gwm_data)} games A→Z by {label}. Click Save Order to write.")

    def _gwm_remove(self) -> None:
        idx = self._gwm_selected_index()
        if idx < 0:
            self._set_status("Select a game to remove.")
            return
        game_name = self._gwm_data[idx]["name"]
        system = self._gwm_loaded_system or self._gwm_system_var.get().strip()
        apply_ = self._global_apply_var.get()
        rm_pc = getattr(self, "_gwm_remove_pclauncher_var", None) and self._gwm_remove_pclauncher_var.get()

        if not apply_:
            extra = " + PCLauncher INI" if rm_pc else ""
            self._set_status(
                f"[DRY RUN] Would remove '{game_name}' from {system}{extra}. "
                "Tick Apply and click Remove Game again to commit."
            )
            dry_flags = "--remove-pclauncher " if rm_pc else ""
            self._append_output(
                f"[DRY RUN] game remove --system {system!r} {game_name!r} {dry_flags}\n"
                "  (pass --apply to write)\n"
            )
            return

        ini_note = (
            "\n\nThe matching PCLauncher INI will also be deleted."
            if rm_pc else
            "\n\nThe ROM and media files are NOT deleted — only the XML entry."
        )
        if not self.messagebox.askyesno(
            "Remove game?",
            f"Remove '{game_name}' from the {system} wheel database?{ini_note}",
        ):
            return

        args = ["game", "remove", "--system", system, game_name, "--apply", "--verbose"]
        if rm_pc:
            args.append("--remove-pclauncher")

        def _on_done(rc: int) -> None:
            if rc != 0:
                return
            # Search by name in case the user reordered during the CLI run.
            for i, entry in enumerate(self._gwm_data):
                if entry["name"] == game_name:
                    self._gwm_data.pop(i)
                    break
            self._gwm_repopulate_tree()
            count = len(self._gwm_data)
            self._gwm_count_label.configure(text=f"{count} game{'s' if count != 1 else ''}")

        self._run_cli("spindoctor", args, on_complete=_on_done)

    def _gwm_save_order(self) -> None:
        system = self._gwm_loaded_system
        if not system:
            self._set_status("Load a system's games first.")
            return
        if not self._gwm_data:
            self._set_status("No games loaded — click Load Games first.")
            return

        apply_ = self._global_apply_var.get()
        names = [entry["name"] for entry in self._gwm_data]

        if not apply_:
            self._set_status(
                f"[DRY RUN] Would save new game order for {system} "
                f"({len(names)} games). Tick Apply and click Save Order to commit."
            )
            self._append_output(
                f"[DRY RUN] game save-order --system {system!r}\n"
                f"  New order ({len(names)} games):\n"
                + "".join(f"  {i+1:>4}  {n}\n" for i, n in enumerate(names))
                + "  (pass --apply to write)\n"
            )
            return

        if not self.messagebox.askyesno(
            "Save game order?",
            f"Write the new game order for {system} to its XML database?\n\n"
            f"{len(names)} games will be saved in the current table order.",
        ):
            return

        # Write names to a temp file so we stay within Win7's ~32 KB
        # command-line limit even for systems with thousands of ROMs.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False,
        )
        tmp.write("\n".join(names))
        tmp.close()
        tmp_path = tmp.name

        def _cleanup(rc: int) -> None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

        args = ["game", "save-order", "--system", system,
                "--order-file", tmp_path, "--apply"]
        self._run_cli("spindoctor", args, on_complete=_cleanup)

    def _refresh_rename_games(self) -> None:
        system = self._rename_system_var.get().strip()
        games = self._load_games_for_system(system) if system else []
        self._rename_game_combo["values"] = games
        self._rename_game_var.set(games[0] if games else "")

    def _refresh_fav_games(self) -> None:
        system = self._fav_system_var.get().strip()
        games = self._load_games_for_system(system) if system else []
        self._fav_rom_combo["values"] = games
        self._fav_rom_var.set(games[0] if games else "")

    def _refresh_inspect_games(self) -> None:
        system = self._inspect_system_var.get().strip()
        games = self._load_games_for_system(system) if system else []
        combo = getattr(self, "_inspect_rom_combo", None)
        if combo is None:
            return
        combo["values"] = [""] + games
        self._inspect_rom_var.set("")

    def _refresh_madd_games(self) -> None:
        system = self._madd_system_var.get().strip()
        games = self._load_games_for_system(system) if system else []
        self._madd_game_combo["values"] = games
        self._madd_game_var.set(games[0] if games else "")

    def _refresh_ignore_games(self) -> None:
        system = self._ignore_system_var.get().strip()
        games = self._load_games_for_system(system) if system else []
        combo = getattr(self, "_ignore_game_combo", None)
        if combo is None:
            return
        combo["values"] = games
        self._ignore_game_var.set(games[0] if games else "")

    def _run_rename_or_clone(self, verb: str) -> None:
        """Shared dispatcher for the `rename` / `clone` buttons.

        Both CLI commands accept the same `--system / --game / --to`
        flag triple; only the verb differs.
        """
        sys_ = self._rename_system_var.get().strip()
        game = self._rename_game_var.get().strip()
        to = self._rename_to_var.get().strip()
        if not (sys_ and game and to):
            self.messagebox.showwarning(
                "Missing arguments",
                "Pick a system, select a game, and fill in New name.",
            )
            return
        args = [verb, "--system", sys_, "--game", game, "--to", to]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_add_system(self, pc: bool) -> None:
        name = self._systems_name_var.get().strip()
        if not name:
            self.messagebox.showwarning(
                "System name required",
                "Type a system name (e.g. 'Nintendo Entertainment "
                "System' or 'PC Games') first.",
            )
            return
        args = ["add-pc-system" if pc else "add-system", name]
        if self._systems_no_sys_media_var.get():
            args.append("--no-system-media")
        if self._systems_no_game_media_var.get():
            args.append("--no-game-media")
        if pc:
            # The CLI's title-review step calls input() on each game.
            # The GUI can't satisfy stdin, so always auto-accept the
            # proposed title. Users who want to curate titles can run
            # `spindoctor pc-rename <system>` from a terminal.
            args.append("--no-interactive")
            if getattr(self, "_add_pc_overwrite_var", None) and self._add_pc_overwrite_var.get():
                args.append("--overwrite-pclauncher")
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_pc_rename(self) -> None:
        system = self._systems_old_var.get().strip()
        if not system:
            self._flash_validation(
                "Pick a PC system first (the dropdown shows your existing PC systems)."
            )
            return
        # Use add-pc-system with --no-menu/--no-system-media/--no-game-media so
        # only the database XML and PCLauncher INIs are updated (the wheel entry
        # and system artwork were already set up when the system was first added).
        # --no-interactive auto-accepts proposed titles so stdin is never needed.
        args = [
            "add-pc-system", system,
            "--no-menu", "--no-system-media", "--no-game-media",
            "--no-interactive",
        ]
        if self._global_apply_var.get():
            args.append("--apply")
        if getattr(self, "_pc_overwrite_var", None) and self._pc_overwrite_var.get():
            args.append("--overwrite-pclauncher")
        self._run_cli("spindoctor", args)

    # ── LEDBlinky tab ─────────────────────────────────────────────────────────

    def _build_ledblinky_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Configure LED button colors for every system in your "
                  "cabinet via LEDBlinky. Steps 1 and 2 are one-time setup "
                  "(overlay-hook fix and Settings.ini); Steps 3–9 cover the "
                  "ongoing workflow: MAME LED data, fill defaults, randomize "
                  "colors, admin button colors, brightness, color definitions, "
                  "and backup/restore."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        # ── Step 3 — MAME: Generate, Normalize & Sync Players ────────────────
        gen_frame = self.ttk.LabelFrame(
            frame, text="Step 3 — MAME: Generate, Normalize & Sync Players",
        )
        gen_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        gen_frame.columnconfigure(1, weight=1)

        self.ttk.Label(
            gen_frame,
            text=("These three steps build MAME-sourced LED data using mame -listxml. "
                  "Click Run Full MAME Setup to run 3a + 3c in one go, or use the "
                  "individual buttons below. "
                  "3b (Normalize) is only needed for a legacy Colors.ini in hex format "
                  "(ledcolor1=FF0000) — skip it after a fresh Generate. "
                  "Added new MAME ROMs? Re-run Full Setup — existing entries are "
                  "preserved unless Overwrite is ticked."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(6, 4))

        self._led_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            gen_frame, text="Overwrite existing entries (Generate step only)",
            variable=self._led_overwrite_var,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        # Chain button — runs 3a + 3c via ledblinky setup
        gen_chain_row = self.ttk.Frame(gen_frame)
        gen_chain_row.grid(row=2, column=0, columnspan=4, sticky="w",
                           padx=6, pady=(6, 2))
        self.ttk.Button(
            gen_chain_row, text="▶  Run Full MAME Setup (3a + 3c)",
            command=self._run_led_setup,
        ).pack(side="left")
        self.ttk.Label(
            gen_chain_row,
            text="  — generate + sync player colors in one click",
            foreground=_FG_DIM,
        ).pack(side="left")

        # Individual step buttons
        gen_btn_row = self.ttk.Frame(gen_frame)
        gen_btn_row.grid(row=3, column=0, columnspan=4, sticky="w",
                         padx=6, pady=(2, 4))
        self.ttk.Button(
            gen_btn_row, text="3a. Generate (controls + colors)",
            command=self._run_led_generate,
        ).pack(side="left")
        self.ttk.Button(
            gen_btn_row, text="3b. Normalize Colors.ini",
            command=self._run_color_normalize,
        ).pack(side="left", padx=(8, 0))
        self.ttk.Button(
            gen_btn_row, text="3c. Sync player colors",
            command=self._run_led_sync_players,
        ).pack(side="left", padx=(8, 0))
        self.ttk.Button(
            gen_btn_row, text="Audit MAME coverage",
            command=self._run_led_audit,
        ).pack(side="left", padx=(8, 0))

        # Inspect ROM row
        gen_inspect_row = self.ttk.Frame(gen_frame)
        gen_inspect_row.grid(row=4, column=0, columnspan=4, sticky="w",
                             padx=6, pady=(2, 4))
        self.ttk.Label(gen_inspect_row, text="Inspect ROM:").pack(side="left")
        self._led_inspect_rom_var = self.tk.StringVar()
        self.ttk.Entry(
            gen_inspect_row, textvariable=self._led_inspect_rom_var, width=20,
        ).pack(side="left", padx=(6, 0))
        self.ttk.Button(
            gen_inspect_row, text="Inspect",
            command=self._run_led_inspect_rom,
        ).pack(side="left", padx=(6, 0))
        self.ttk.Label(
            gen_inspect_row,
            text="  — diagnose why a specific ROM's LEDs may not be working",
            foreground=_FG_DIM,
        ).pack(side="left")

        self.ttk.Label(
            gen_frame,
            text=("All writes auto-backup before modifying files. "
                  "3b (Normalize) is for legacy files only — skip if you started "
                  "fresh with SpinDoctor 2.4.21+. "
                  "Audit MAME coverage shows which ROMs have / lack control data."),
            wraplength=820, justify="left", foreground=_FG_DIM,
        ).grid(row=5, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 6))

        # ── Fill Defaults ────────────────────────────────────────────────────
        fd_frame = self.ttk.LabelFrame(
            frame, text="Step 4 — Fill Default Colors (any console)",
        )
        fd_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        fd_frame.columnconfigure(1, weight=1)

        self.ttk.Label(
            fd_frame,
            text=("Add a default Colors.ini entry for every ROM that has no LED "
                  "mapping yet — works for MAME, SNES, NES, or any other console. "
                  "Without an entry LedBlinky treats all buttons as inactive (off). "
                  "After running fill-defaults, unmapped games will glow a steady "
                  "color instead of going dark. Leave console blank to cover all "
                  "systems at once, including Favorites and Recently Played."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 4))

        self.ttk.Label(fd_frame, text="Console").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._fd_system_var = self.tk.StringVar(value="")
        self._fd_system_combo = self.ttk.Combobox(
            fd_frame, textvariable=self._fd_system_var, width=24,
        )
        self._fd_system_combo.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            fd_frame,
            text="(leave blank = all consoles incl. Favorites / Recently Played)",
            foreground=_FG_DIM,
        ).grid(row=1, column=2, sticky="w", padx=(0, 6))

        self.ttk.Label(fd_frame, text="Default color").grid(
            row=2, column=0, sticky="w", padx=6, pady=2,
        )
        self._fd_color_var = self.tk.StringVar(value="White")
        self._fd_color_combo = self.ttk.Combobox(
            fd_frame, textvariable=self._fd_color_var, width=16, state="readonly",
        )
        self._fd_color_combo.grid(row=2, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Button(
            fd_frame, text="Refresh colors",
            command=self._refresh_color_list,
        ).grid(row=2, column=2, sticky="w", padx=(0, 4), pady=2)

        self.ttk.Label(fd_frame, text="Buttons (1-8)").grid(
            row=3, column=0, sticky="w", padx=6, pady=2,
        )
        self._fd_buttons_var = self.tk.StringVar(value="6")
        self.ttk.Spinbox(
            fd_frame, textvariable=self._fd_buttons_var,
            from_=1, to=8, width=5,
        ).grid(row=3, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            fd_frame, text="per player", foreground=_FG_DIM,
        ).grid(row=3, column=2, sticky="w", padx=(0, 6))

        self.ttk.Label(fd_frame, text="Players (1-4)").grid(
            row=4, column=0, sticky="w", padx=6, pady=2,
        )
        self._fd_players_var = self.tk.StringVar(value="1")
        self.ttk.Spinbox(
            fd_frame, textvariable=self._fd_players_var,
            from_=1, to=4, width=5,
        ).grid(row=4, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            fd_frame,
            text="P1–P4 blocks, all mirrored to same color",
            foreground=_FG_DIM,
        ).grid(row=4, column=2, sticky="w", padx=(0, 6))

        self.ttk.Label(fd_frame, text="Admin buttons").grid(
            row=5, column=0, sticky="w", padx=6, pady=2,
        )
        _fd_admin_inner = self.ttk.Frame(fd_frame)
        _fd_admin_inner.grid(row=5, column=1, columnspan=2, sticky="w",
                             padx=6, pady=2)
        self._fd_admin_buttons_var = self.tk.StringVar(value="0")
        self.ttk.Spinbox(
            _fd_admin_inner, textvariable=self._fd_admin_buttons_var,
            from_=0, to=12, width=5,
        ).grid(row=0, column=0, sticky="w")
        self.ttk.Label(_fd_admin_inner, text="  Color:").grid(
            row=0, column=1, sticky="w",
        )
        self._fd_admin_color_var = self.tk.StringVar(value="White")
        self._fd_admin_color_combo = self.ttk.Combobox(
            _fd_admin_inner, textvariable=self._fd_admin_color_var,
            width=14, state="readonly",
        )
        self._fd_admin_color_combo.grid(row=0, column=2, sticky="w", padx=(4, 0))
        self.ttk.Label(
            _fd_admin_inner,
            text="  (0 = disabled, uses next player slot P{players+1})",
            foreground=_FG_DIM,
        ).grid(row=0, column=3, sticky="w", padx=(4, 0))

        # Override options
        _fd_override_inner = self.ttk.Frame(fd_frame)
        _fd_override_inner.grid(row=6, column=0, columnspan=3, sticky="w",
                                padx=6, pady=(4, 2))
        self._fd_override_uniform_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            _fd_override_inner,
            text="Override existing entries if all buttons are the same color",
            variable=self._fd_override_uniform_var,
        ).grid(row=0, column=0, sticky="w")
        self.ttk.Label(
            _fd_override_inner,
            text="  (mixed-color entries are never touched)",
            foreground=_FG_DIM,
        ).grid(row=0, column=1, sticky="w")

        self._fd_no_add_keys_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            _fd_override_inner,
            text="Don't add new keys when overriding",
            variable=self._fd_no_add_keys_var,
        ).grid(row=1, column=0, sticky="w")
        self.ttk.Label(
            _fd_override_inner,
            text="  (only update values of existing keys)",
            foreground=_FG_DIM,
        ).grid(row=1, column=1, sticky="w")

        self.ttk.Button(
            fd_frame, text="Fill Default Colors",
            command=self._run_fill_defaults,
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 8))

        # ── Step 3 — Randomize Entry Colors ─────────────────────────────────
        rz_frame = self.ttk.LabelFrame(frame, text="Step 5 — Randomize Entry Colors")
        rz_frame.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        rz_frame.columnconfigure(1, weight=1)

        self.ttk.Label(
            rz_frame,
            text=("Give each game its own random button color drawn from the Color-RGB.ini "
                  "palette. Every ROM section receives an independent random color for all "
                  "P*_BUTTON* / P*_JOYSTICK keys, and a second independent random color for "
                  "P*_COIN / P*_START keys. Only existing keys are updated — buttons "
                  "intentionally left dark stay dark.\n"
                  "Requires normalized format (Step 1b). If most sections are skipped, "
                  "run Normalize Colors.ini first."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 4))

        self.ttk.Label(rz_frame, text="Seed (optional)").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._rz_seed_var = self.tk.StringVar(value="")
        self.ttk.Entry(
            rz_frame, textvariable=self._rz_seed_var, width=12,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            rz_frame,
            text="(leave blank for a fresh random shuffle each run; "
                 "enter an integer for reproducible output)",
            foreground=_FG_DIM,
        ).grid(row=1, column=2, sticky="w", padx=(0, 6))

        self.ttk.Button(
            rz_frame, text="Randomize Entry Colors",
            command=self._run_randomize_entry_colors,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 8))

        # ── Step 4 — Admin Button Colors ─────────────────────────────────────
        ab_frame = self.ttk.LabelFrame(frame, text="Step 6 — Admin Button Colors")
        ab_frame.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(12, 0))

        self.ttk.Label(
            ab_frame,
            text=("Set fixed colors for your cabinet-level (admin) buttons across "
                  "ALL Colors.ini ROM sections — e.g. Select=Green, Exit=Red. "
                  "Colors are written to the player slot you choose (P3 for a 2-player "
                  "cabinet). Run after Step 5 (Randomize) — Randomize overwrites all "
                  "button colors, so admin colors must be set last."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=9, sticky="w", padx=6, pady=(6, 4))

        # Player slot + button count + refresh button on one row
        self.ttk.Label(ab_frame, text="Player slot").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._admin_player_var = self.tk.StringVar(value="3")
        self.ttk.Spinbox(
            ab_frame, textvariable=self._admin_player_var,
            from_=1, to=6, width=4,
        ).grid(row=1, column=1, sticky="w", padx=(4, 8), pady=2)
        self.ttk.Label(ab_frame, text="Button count").grid(
            row=1, column=2, sticky="w", padx=(0, 2), pady=2,
        )
        self._admin_button_count_var = self.tk.StringVar(value="6")
        self.ttk.Spinbox(
            ab_frame, textvariable=self._admin_button_count_var,
            from_=1, to=8, width=4,
        ).grid(row=1, column=3, sticky="w", padx=(4, 8), pady=2)
        self.ttk.Button(
            ab_frame, text="Refresh colors",
            command=self._refresh_color_list,
        ).grid(row=1, column=4, sticky="w", padx=(0, 4), pady=2)
        self.ttk.Label(
            ab_frame,
            text="(1–8; only this many buttons are sent)",
            foreground=_FG_DIM,
        ).grid(row=1, column=5, columnspan=4, sticky="w", padx=4, pady=2)

        # 8 per-button color comboboxes: BUTTON1..BUTTON8, laid out 4 per row
        # Colors are populated from Color-RGB.ini via _refresh_color_list().
        self._admin_color_vars: list = []
        self._admin_color_combos: list = []
        for i in range(8):
            row_offset = 2 + (i // 4)
            col_offset = (i % 4) * 2
            self.ttk.Label(
                ab_frame, text=f"BUTTON{i + 1}:",
            ).grid(row=row_offset, column=col_offset, sticky="e",
                   padx=(8 if col_offset == 0 else 4, 2), pady=2)
            var = self.tk.StringVar(value="White")
            combo = self.ttk.Combobox(
                ab_frame, textvariable=var, width=14, state="readonly",
            )
            combo.grid(row=row_offset, column=col_offset + 1, sticky="w",
                       padx=(0, 4), pady=2)
            self._admin_color_vars.append(var)
            self._admin_color_combos.append(combo)

        self.ttk.Button(
            ab_frame, text="Set Admin Button Colors",
            command=self._run_admin_button_colors,
        ).grid(row=4, column=0, columnspan=4, sticky="w", padx=6, pady=(4, 8))

        # ── Step 5 — Brightness ───────────────────────────────────────────────
        br2_frame = self.ttk.LabelFrame(frame, text="Step 7 — Brightness")
        br2_frame.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        br2_frame.columnconfigure(1, weight=1)

        self.ttk.Label(
            br2_frame,
            text=("Set all Color-RGB.ini colors to a uniform brightness level. "
                  "100% = every color at maximum brightness (dominant channel = 48, "
                  "any dim colors are boosted up). "
                  "50% = half brightness. 10% = night mode. 0% = all off. "
                  "All buttons (P1, P2, admin) are normalized to the same level."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(6, 4))

        self.ttk.Label(br2_frame, text="Brightness %").grid(
            row=1, column=0, sticky="w", padx=6, pady=4,
        )
        self._led_brightness_var = self.tk.IntVar(value=100)
        self.ttk.Scale(
            br2_frame, from_=0, to=100,
            variable=self._led_brightness_var, orient="horizontal",
            command=lambda _: self._led_brightness_label.config(
                text=f"{self._led_brightness_var.get()}%"
            ),
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        self._led_brightness_label = self.ttk.Label(br2_frame, text="100%", width=6)
        self._led_brightness_label.grid(row=1, column=2, sticky="w", padx=(0, 6))

        self.ttk.Button(
            br2_frame, text="Scale Brightness",
            command=self._run_led_brightness,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 8))

        # ── Step 6 — Settings.ini Patch ───────────────────────────────────────
        _led_cfg = load_config()

        sp_frame = self.ttk.LabelFrame(frame, text="Step 2 — Settings.ini (one-time setup)")
        sp_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        sp_frame.columnconfigure(1, weight=1)

        self.ttk.Label(
            sp_frame,
            text=("Configure LEDBlinky's animation behavior. "
                  "FE idle animation plays while browsing HyperSpin; "
                  "In-game unused buttons controls what happens to unassigned buttons during gameplay."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 4))

        self.ttk.Label(sp_frame, text="FE active animation").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._led_fe_lwa_var = self.tk.StringVar(value="<Random>")
        self._led_fe_lwa_combo = self.ttk.Combobox(
            sp_frame, textvariable=self._led_fe_lwa_var, width=36,
        )
        self._led_fe_lwa_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            sp_frame, text="Refresh list",
            command=self._refresh_led_lwa_list,
        ).grid(row=1, column=2, sticky="w", padx=(0, 6), pady=2)

        self.ttk.Label(
            sp_frame,
            text="Animation while actively browsing HyperSpin (FELWAFile). "
                 "Leave blank for static colors. Use Refresh list to populate from your LEDBlinky folder.",
            wraplength=700, justify="left", foreground=_FG_DIM,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        self.ttk.Label(sp_frame, text="Screen saver animation").grid(
            row=3, column=0, sticky="w", padx=6, pady=2,
        )
        self._led_ss_lwa_var = self.tk.StringVar(value="<Random>")
        self._led_ss_lwa_combo = self.ttk.Combobox(
            sp_frame, textvariable=self._led_ss_lwa_var, width=36,
        )
        self._led_ss_lwa_combo.grid(row=3, column=1, sticky="ew", padx=6, pady=2)

        self.ttk.Label(
            sp_frame,
            text="Animation during the HyperSpin screen saver (FEScreenSaverLWAFile). "
                 "Leave blank to silence. Omit (leave as <Random>) to leave unchanged.",
            wraplength=700, justify="left", foreground=_FG_DIM,
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        self.ttk.Label(sp_frame, text="In-game unused buttons").grid(
            row=5, column=0, sticky="w", padx=6, pady=2,
        )
        self._led_game_lwa_var = self.tk.StringVar(value="")
        self._led_game_lwa_combo = self.ttk.Combobox(
            sp_frame, textvariable=self._led_game_lwa_var, width=36,
        )
        self._led_game_lwa_combo.grid(row=5, column=1, sticky="ew", padx=6, pady=2)

        self.ttk.Label(
            sp_frame,
            text=("Leave blank to turn unused buttons off during gameplay (recommended). "
                  "Select an animation to play on all unmapped buttons instead — "
                  "applies globally to every game on every system."),
            wraplength=700, justify="left", foreground=_FG_DIM,
        ).grid(row=6, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        self.ttk.Button(
            sp_frame, text="Patch Settings.ini",
            command=self._run_led_patch_settings,
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 8))

        # Populate .lwa list immediately if ledblinky_dir is already set
        self._refresh_led_lwa_list()

        # ── Overlay Hooks (one-time fix) ──────────────────────────────────────
        oh_frame = self.ttk.LabelFrame(
            frame, text="Step 1 — Overlay Hook Fix (one-time setup)",
        )
        oh_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 0))
        oh_frame.columnconfigure(0, weight=1)

        self.ttk.Label(
            oh_frame,
            text=("Fixes HyperSpin Search / Genre / Favorites overlay crashes caused "
                  "by LEDBlinky process hooks. Two patches: (1) adds a stub entry to "
                  "LEDBlinkyControls.xml for each overlay menu so LEDBlinky's lookup "
                  "succeeds; (2) comments out Start_Hyperspin_Process / "
                  "Exit_Hyperspin_Process lines in the per-menu Settings.ini files. "
                  "Always writes in-place to ledblinky_dir / hyperspin_dir — "
                  "not affected by the output_dir setting."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 4))

        oh_btn_row = self.ttk.Frame(oh_frame)
        oh_btn_row.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 8))
        self.ttk.Button(
            oh_btn_row, text="Check overlay hooks",
            command=lambda: self._run_cli("spindoctor", ["ledblinky", "check"]),
        ).pack(side="left")
        self.ttk.Button(
            oh_btn_row, text="Fix overlay hooks",
            command=self._run_led_fix,
        ).pack(side="left", padx=(8, 0))

        # ── Color Definitions (advanced) ──────────────────────────────────────
        self._color_original_hex: str = ""   # set when a row is selected

        cd_frame = self.ttk.LabelFrame(
            frame, text="Step 8 — Color Definitions (Color-RGB.ini)",
        )
        cd_frame.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        cd_frame.columnconfigure(0, weight=1)

        self.ttk.Label(
            cd_frame,
            text=("View and edit the named color palette used by all other sections. "
                  "Renaming a color propagates the change through Color-RGB.ini, "
                  "Colors.ini, and LEDBlinkyControls.xml in one operation."),
            wraplength=820, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 4))

        # Treeview + vertical scrollbar
        tree_outer = self.ttk.Frame(cd_frame)
        tree_outer.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 2))
        tree_outer.columnconfigure(0, weight=1)

        _led_cols = ("name", "r", "g", "b", "hex")
        self._color_tree = self.ttk.Treeview(
            tree_outer, columns=_led_cols, show="headings",
            height=6, selectmode="browse",
        )
        for _col, _heading, _w, _stretch in [
            ("name", "Name",     110, True),
            ("r",    "R (0-48)",  70, False),
            ("g",    "G (0-48)",  70, False),
            ("b",    "B (0-48)",  70, False),
            ("hex",  "Hex",       86, False),
        ]:
            self._color_tree.heading(_col, text=_heading)
            self._color_tree.column(_col, width=_w, stretch=_stretch)
        _led_vsb = self.ttk.Scrollbar(
            tree_outer, orient="vertical", command=self._color_tree.yview,
        )
        self._color_tree.configure(yscrollcommand=_led_vsb.set)
        self._color_tree.grid(row=0, column=0, sticky="nsew")
        _led_vsb.grid(row=0, column=1, sticky="ns")
        self._color_tree.bind("<<TreeviewSelect>>", self._on_color_tree_select)

        self.ttk.Button(
            cd_frame, text="Refresh list",
            command=self._refresh_color_list,
        ).grid(row=2, column=0, sticky="w", padx=6, pady=(2, 4))

        # Edit fields
        edit_f = self.ttk.Frame(cd_frame)
        edit_f.grid(row=3, column=0, columnspan=3, sticky="ew", padx=6, pady=2)

        self.ttk.Label(edit_f, text="New name:").grid(
            row=0, column=0, sticky="w", padx=(0, 4),
        )
        self._color_new_name_var = self.tk.StringVar()
        self.ttk.Entry(
            edit_f, textvariable=self._color_new_name_var, width=16,
        ).grid(row=0, column=1, sticky="w")

        self.ttk.Label(edit_f, text="New color (#RRGGBB):").grid(
            row=0, column=2, sticky="w", padx=(14, 4),
        )
        self._color_hex_var = self.tk.StringVar()
        self.ttk.Entry(
            edit_f, textvariable=self._color_hex_var, width=10,
        ).grid(row=0, column=3, sticky="w")

        # Plain tk.Label so background= is honoured (ttk.Label uses styles)
        self._color_preview = self.tk.Label(
            edit_f, text="  ", background="#FFFFFF",
            relief="solid", width=3,
        )
        self._color_preview.grid(row=0, column=4, sticky="w", padx=(4, 0))
        self._color_hex_var.trace_add("write", self._update_color_preview)

        cd_btn_row = self.ttk.Frame(cd_frame)
        cd_btn_row.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 8))

        self.ttk.Button(
            cd_btn_row, text="Update & Rename",
            command=self._run_color_edit,
        ).pack(side="left", padx=(0, 8))

        self.ttk.Button(
            cd_btn_row, text="Normalize Colors.ini",
            command=self._run_color_normalize,
        ).pack(side="left")

        # Populate immediately if ledblinky_dir is already configured
        self._refresh_color_list()

        # ── Backup / Restore ─────────────────────────────────────────────────
        _led_backup_default = getattr(_led_cfg, "backup_dir", "") or ""

        br_frame = self.ttk.LabelFrame(frame, text="Step 9 — Backup / Restore")
        br_frame.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        br_frame.columnconfigure(1, weight=1)

        self.ttk.Label(br_frame, text="Backup folder").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._led_backup_dir_var = self.tk.StringVar(value=_led_backup_default)
        self.ttk.Entry(
            br_frame, textvariable=self._led_backup_dir_var, width=48,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            br_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._led_backup_dir_var, "Pick LEDBlinky backup folder",
            ),
        ).grid(row=0, column=2, sticky="w", padx=(0, 6), pady=2)

        self.ttk.Button(
            br_frame, text="Create backup",
            command=self._run_led_backup,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

        self.ttk.Separator(br_frame, orient="horizontal").grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 4),
        )

        self.ttk.Label(br_frame, text="Restore from").grid(
            row=3, column=0, sticky="w", padx=6, pady=2,
        )
        self._led_restore_path_var = self.tk.StringVar(value=_led_backup_default)
        self.ttk.Entry(
            br_frame, textvariable=self._led_restore_path_var, width=48,
        ).grid(row=3, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            br_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._led_restore_path_var, "Pick LEDBlinky backup to restore",
            ),
        ).grid(row=3, column=2, sticky="w", padx=(0, 6), pady=2)

        self.ttk.Button(
            br_frame, text="Restore backup",
            command=self._run_led_restore,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

        frame.columnconfigure(1, weight=1)
        return frame

    def _run_led_setup(self) -> None:
        """Run ledblinky setup (3a generate + 3c sync-players) in one step."""
        args = ["ledblinky", "setup"]
        if self._led_overwrite_var.get():
            args.append("--overwrite")
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_led_inspect_rom(self) -> None:
        """Run ledblinky inspect-rom to diagnose a specific ROM."""
        rom = self._led_inspect_rom_var.get().strip()
        if not rom:
            self._flash_validation("Enter a ROM name to inspect.")
            return
        self._run_cli("spindoctor", ["ledblinky", "inspect-rom", rom])

    def _run_led_generate(self) -> None:
        args = ["ledblinky", "generate", "--system", "MAME"]
        if self._led_overwrite_var.get():
            args.append("--overwrite")
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_led_audit(self) -> None:
        self._run_cli(
            "spindoctor", ["ledblinky", "audit", "--system", "MAME"],
        )

    def _run_led_fix(self) -> None:
        # `ledblinky fix` is a writer; it respects --apply, so we forward
        # the same Apply checkbox the Generate path uses.
        args = ["ledblinky", "fix"]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_led_backup(self) -> None:
        target = self._led_backup_dir_var.get().strip()
        if not target:
            self.messagebox.showwarning(
                "Backup folder required",
                "Pick the folder where the backup should be written.",
            )
            return
        args = ["backup", "create", "--target", target, "--include", "ledblinky"]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_led_restore(self) -> None:
        backup_path = self._led_restore_path_var.get().strip()
        if not backup_path:
            self.messagebox.showwarning(
                "Backup folder required",
                "Pick the backup folder to restore from.",
            )
            return
        if self._global_apply_var.get():
            if not self.messagebox.askyesno(
                "Restore LEDBlinky backup?",
                f"This will restore LEDBlinky files from:\n{backup_path}\n\n"
                "Existing files on disk may be overwritten. "
                "This cannot be undone.\n\nContinue?",
            ):
                return
        args = ["backup", "restore", "--backup", backup_path, "--include", "ledblinky"]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _refresh_led_lwa_list(self) -> None:
        """Populate the FE, screen saver, and in-game animation comboboxes from ledblinky_dir.

        Also reads Settings.ini and pre-selects each combobox to the currently
        configured value so the GUI reflects what is actually set on disk.
        """
        try:
            from . import ledblinky as lb
            cfg = load_config()
            lwa_files = lb.list_lwa_files(cfg)
            current = lb.read_ledblinky_settings_keys(cfg)
        except Exception:
            lwa_files = []
            current = {}
        # Always include a blank entry (silent / no animation).
        values = [""] + lwa_files
        self._led_fe_lwa_combo["values"] = values
        if hasattr(self, "_led_ss_lwa_combo"):
            self._led_ss_lwa_combo["values"] = values
        if hasattr(self, "_led_game_lwa_combo"):
            self._led_game_lwa_combo["values"] = values
        # Pre-select current values from Settings.ini; fall back to defaults if
        # the key is missing (ledblinky_dir not set, file absent, etc.).
        if "FELWAFile" in current:
            self._led_fe_lwa_var.set(current["FELWAFile"])
        if "FEScreenSaverLWAFile" in current and hasattr(self, "_led_ss_lwa_var"):
            self._led_ss_lwa_var.set(current["FEScreenSaverLWAFile"])
        if "GamePlayLWAFile" in current and hasattr(self, "_led_game_lwa_var"):
            self._led_game_lwa_var.set(current["GamePlayLWAFile"])

    def _run_led_patch_settings(self) -> None:
        fe_lwa = self._led_fe_lwa_var.get().strip()
        ss_lwa = self._led_ss_lwa_var.get().strip()
        # Treat "<Random>" sentinel as "leave unchanged" (None) so an accidental
        # click doesn't write "<Random>" literally into Settings.ini.
        fe_lwa_arg = None if fe_lwa == "<Random>" else fe_lwa
        ss_lwa_arg = None if ss_lwa == "<Random>" else ss_lwa

        game_lwa = self._led_game_lwa_var.get().strip()
        args = ["ledblinky", "patch-settings", "--game-lwa", game_lwa]
        if fe_lwa_arg is not None:
            args += ["--fe-lwa", fe_lwa_arg]
        if ss_lwa_arg is not None:
            args += ["--ss-lwa", ss_lwa_arg]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    # ── Color Definitions helpers ─────────────────────────────────────────────

    def _refresh_color_list(self) -> None:
        """Load Color-RGB.ini entries into the Treeview and Fill Defaults combo."""
        try:
            from . import ledblinky as lb
            from pathlib import Path as _Path
            cfg = load_config()
            if not getattr(cfg, "ledblinky_dir", ""):
                return
            path = _Path(cfg.ledblinky_dir) / lb.COLOR_RGB_NAME
            if not path.exists():
                return
            _, entries = lb.parse_color_rgb_ini(path)
        except Exception:
            return
        self._color_tree.delete(*self._color_tree.get_children())
        color_names: list[str] = []
        for e in entries:
            self._color_tree.insert(
                "", "end", iid=e.name,
                values=(e.name, e.r, e.g, e.b, e.to_hex()),
            )
            color_names.append(e.name)
        # Also populate the Fill Defaults color dropdowns (default + admin)
        for combo_attr, var_attr in (
            ("_fd_color_combo", "_fd_color_var"),
            ("_fd_admin_color_combo", "_fd_admin_color_var"),
        ):
            combo = getattr(self, combo_attr, None)
            var = getattr(self, var_attr, None)
            if combo is not None and var is not None:
                combo["values"] = color_names
                if color_names and var.get() not in color_names:
                    var.set("White" if "White" in color_names else color_names[0])

        # Populate admin button per-button color combos
        for combo, var in zip(
            getattr(self, "_admin_color_combos", []),
            getattr(self, "_admin_color_vars", []),
        ):
            combo["values"] = color_names
            if color_names and var.get() not in color_names:
                var.set("White" if "White" in color_names else color_names[0])

    def _on_color_tree_select(self, _event=None) -> None:
        """Populate the edit fields when the user clicks a color row."""
        sel = self._color_tree.selection()
        if not sel:
            return
        values = self._color_tree.item(sel[0], "values")
        if len(values) >= 5:
            name, _r, _g, _b, hex_val = values
            self._color_new_name_var.set(name)
            clean = hex_val.lstrip("#")
            self._color_original_hex = clean
            self._color_hex_var.set(clean)

    def _update_color_preview(self, *_) -> None:
        """Update the color swatch when the hex entry changes."""
        raw = self._color_hex_var.get().strip().lstrip("#")
        if len(raw) == 6:
            try:
                int(raw, 16)   # validate before applying
                try:
                    self._color_preview.configure(background=f"#{raw}")
                except Exception:
                    pass
            except ValueError:
                pass

    def _run_color_edit(self) -> None:
        """Run ``ledblinky colors edit`` for the selected color."""
        sel = self._color_tree.selection()
        if not sel:
            self.messagebox.showwarning(
                "No color selected",
                "Click a color row in the list, then edit its name or value.",
            )
            return
        old_name = sel[0]   # iid is the old name
        new_name = self._color_new_name_var.get().strip()
        hex_val = self._color_hex_var.get().strip().lstrip("#")

        if not new_name:
            self.messagebox.showwarning("Name required", "Enter a name for the color.")
            return

        name_changed = (new_name != old_name)
        hex_changed = (len(hex_val) == 6 and hex_val != self._color_original_hex)

        # Validate hex string before sending to CLI
        if len(hex_val) > 0 and len(hex_val) != 6:
            self.messagebox.showwarning(
                "Invalid hex color",
                f"'{hex_val}' must be exactly 6 hex characters (e.g. FF0000 for red).",
            )
            return
        if hex_changed:
            import re as _re
            if not _re.fullmatch(r"[0-9A-Fa-f]{6}", hex_val):
                self.messagebox.showwarning(
                    "Invalid hex color",
                    f"'{hex_val}' contains non-hex characters.\n"
                    "Use digits 0-9 and letters A-F only (e.g. FF0000 for red).",
                )
                return

        if not name_changed and not hex_changed:
            self.messagebox.showinfo(
                "No changes",
                "Change the name or the hex color value to make an edit.",
            )
            return

        args = ["ledblinky", "colors", "edit", old_name]
        if name_changed:
            args += ["--name", new_name]
        if hex_changed and len(hex_val) == 6:
            args += ["--hex", hex_val]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli(
            "spindoctor", args,
            on_complete=lambda rc: self._refresh_color_list() if rc == 0 else None,
        )

    def _run_color_normalize(self) -> None:
        """Run ``ledblinky colors normalize`` to convert hex entries to named format."""
        args = ["ledblinky", "colors", "normalize"]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli(
            "spindoctor", args,
            on_complete=lambda rc: self._refresh_color_list() if rc == 0 else None,
        )

    def _run_led_sync_players(self) -> None:
        """Mirror P1 colors to all additional players (P2, P3, P4, …) based on controls.ini."""
        args = ["ledblinky", "colors", "sync-players"]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_fill_defaults(self) -> None:
        """Run ``ledblinky fill-defaults`` to add default entries for unmapped ROMs."""
        args = ["ledblinky", "fill-defaults"]
        color = self._fd_color_var.get().strip()
        if color and color != "White":
            args += ["--color", color]
        try:
            n = int(self._fd_buttons_var.get())
        except ValueError:
            n = 6
        if n != 6:
            args += ["--buttons", str(n)]
        try:
            players = int(self._fd_players_var.get())
        except ValueError:
            players = 1
        if players != 1:
            args += ["--players", str(players)]
        try:
            admin_n = int(self._fd_admin_buttons_var.get())
        except ValueError:
            admin_n = 0
        if admin_n > 0:
            args += ["--admin-buttons", str(admin_n)]
            admin_color = self._fd_admin_color_var.get().strip()
            if admin_color and admin_color != "White":
                args += ["--admin-color", admin_color]
        system = self._fd_system_var.get().strip()
        if system:
            args += ["--system", system]
        if self._fd_override_uniform_var.get():
            args.append("--override-uniform")
        if self._fd_no_add_keys_var.get():
            args.append("--no-add-keys")
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_led_brightness(self) -> None:
        """Run ``ledblinky colors brightness`` to scale Color-RGB.ini values."""
        try:
            scale = int(self._led_brightness_var.get())
        except (ValueError, AttributeError):
            scale = 100
        args = ["ledblinky", "colors", "brightness", "--scale", str(scale)]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_randomize_entry_colors(self) -> None:
        """Run ``ledblinky colors randomize`` to assign random colors per game."""
        args = ["ledblinky", "colors", "randomize"]
        seed_raw = self._rz_seed_var.get().strip()
        if seed_raw:
            try:
                int(seed_raw)
                args += ["--seed", seed_raw]
            except ValueError:
                pass  # ignore non-integer seed input
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_admin_button_colors(self) -> None:
        """Run ``ledblinky admin-buttons set`` with per-button colors."""
        try:
            player = int(self._admin_player_var.get())
        except (ValueError, AttributeError):
            player = 3
        try:
            count = max(1, min(8, int(self._admin_button_count_var.get())))
        except (ValueError, AttributeError):
            count = 6
        colors = [
            var.get().strip() or "White"
            for var in self._admin_color_vars[:count]
        ]
        args = [
            "ledblinky", "admin-buttons", "set",
            "--player", str(player),
            "--colors", ",".join(colors),
        ]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    # ── Lightgun tab ──────────────────────────────────────────────────────────

    def _build_lightgun_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Wire Sinden / DemulShooter into RocketLauncher INIs "
                  "for lightgun systems. Detect inventories your install "
                  "and seeds spindoctor config from any RL INIs already "
                  "wired to DemulShooter; Audit shows the wiring status; "
                  "Configure adds (or repairs) the Pre/Post launch hooks "
                  "for one system."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        # ── Step 1 — Detect & audit ──────────────────────────────────────────
        det_frame = self.ttk.LabelFrame(frame, text="Step 1 — Detect & audit")
        det_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 4))

        btn_row = self.ttk.Frame(det_frame)
        btn_row.grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 6))
        self.ttk.Button(
            btn_row, text="Detect installed gear",
            command=self._run_lg_detect,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Audit wiring",
            command=lambda: self._run_cli(
                "spindoctor", ["lightgun", "audit"],
            ),
        ).pack(side="left", padx=6)

        # ── Step 2 — Configure one system ───────────────────────────────────
        cfg_frame = self.ttk.LabelFrame(
            frame, text="Step 2 — Configure one system",
        )
        cfg_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        cfg_frame.columnconfigure(1, weight=1)

        self.ttk.Label(cfg_frame, text="System").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._lg_system_var = self.tk.StringVar()
        self._lg_system_combo = self.ttk.Combobox(
            cfg_frame, textvariable=self._lg_system_var,
            state="readonly", width=30,
        )
        self._lg_system_combo.grid(row=0, column=1, sticky="w", padx=6, pady=2)

        self.ttk.Label(cfg_frame, text="Target (optional)").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._lg_target_var = self.tk.StringVar()
        _DEMUL_TARGETS = [
            "", "mame", "demul07a", "model2", "supermodel",
            "lindbergh", "flycast", "chihiro", "dolphin",
            "ringedge2", "globalvr",
        ]
        self.ttk.Combobox(
            cfg_frame, textvariable=self._lg_target_var,
            values=_DEMUL_TARGETS, width=28,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            cfg_frame,
            text="DemulShooter -target value. Leave blank to auto-detect from system name.",
            foreground=_FG_DIM,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        self.ttk.Label(cfg_frame, text="Extra args (optional)").grid(
            row=3, column=0, sticky="w", padx=6, pady=2,
        )
        self._lg_extra_args_var = self.tk.StringVar()
        self.ttk.Entry(
            cfg_frame, textvariable=self._lg_extra_args_var, width=30,
        ).grid(row=3, column=1, sticky="w", padx=6, pady=2)

        self.ttk.Button(
            cfg_frame, text="Configure system",
            command=self._run_lg_configure,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

        return frame

    def _run_lg_detect(self) -> None:
        args = ["lightgun", "detect"]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    def _run_lg_configure(self) -> None:
        system = self._lg_system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required",
                "Configure needs a system name (e.g. 'Sega Naomi').",
            )
            return
        args = ["lightgun", "configure", "--system", system]
        target = self._lg_target_var.get().strip()
        if target:
            args += ["--target", target]
        extra = self._lg_extra_args_var.get().strip()
        if extra:
            args += ["--extra-args", extra]
        if self._global_apply_var.get():
            args.append("--apply")
        if self._global_verbose_var.get():
            args.append("--verbose")
        self._run_cli("spindoctor", args)

    # ── Tools tab (Custom wheels + Install wheel helpers) ─────────────────────

    def _build_tools_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Build and maintain SpinDoctor's custom wheels: Favorites, "
                  "Recently Played, and Most Played. Import F-key favorites "
                  "from HyperSpin, rebuild the wheels, and register them on "
                  "the main menu. Also installs refresh helpers as HyperSpin "
                  "Tools-menu entries and schedules auto-refresh on startup."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # ── Step 1 — Import HyperSpin favorites (optional) ───────────────────
        # fav sync must run BEFORE the wheel rebuild reads the store, so
        # it leads the tab. It used to live inside the register section
        # (after the rebuild) while its own tooltip said "run this before
        # Refresh selected" — the layout contradicted the instructions.
        sync_lf = self.ttk.LabelFrame(
            frame, text="Step 1 — Import HyperSpin favorites (optional)",
        )
        sync_lf.pack(fill="x", pady=(0, 8))
        self.ttk.Label(
            sync_lf,
            text=("Only needed if you mark favorites with HyperSpin's F-key. "
                  "Imports those per-system favorites into SpinDoctor's "
                  "store so the Step 2 rebuild includes them. Skip this if "
                  "you only manage favorites from this tab."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 4))
        sync_btn = self.ttk.Button(
            sync_lf, text="Sync favorites from HyperSpin", width=28,
            command=lambda: self._run_cli("spindoctor", ["fav", "sync"]),
        )
        sync_btn.pack(anchor="w", padx=6, pady=(0, 6))
        _attach_tooltip(
            sync_btn,
            "Reads HyperSpin's per-system F-key favorites and imports them "
            "into SpinDoctor's store. Run this before 'Refresh selected' "
            "if you use HyperSpin's F-key favorites.",
            self.tk,
        )

        # ── Step 2 — Refresh custom wheels ───────────────────────────────────
        rebuild_lf = self.ttk.LabelFrame(
            frame, text="Step 2 — Refresh custom wheels",
        )
        rebuild_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            rebuild_lf,
            text=("Build (or rebuild) the game databases and PCLauncher INIs "
                  "for each cross-system wheel. Run this after adding new "
                  "ROMs or changing your favorites. None of the wheels "
                  "auto-update on cabinet startup — see 'Install .bat helpers' "
                  "below to set that up."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 6))

        wheels_checks = self.ttk.Frame(rebuild_lf)
        wheels_checks.pack(anchor="w", padx=6, pady=(0, 4))
        self._wheel_fav_var    = self.tk.BooleanVar(value=True)
        self._wheel_recent_var = self.tk.BooleanVar(value=True)
        self._wheel_stats_var  = self.tk.BooleanVar(value=True)
        for var, label in (
            (self._wheel_fav_var,    "Favorites"),
            (self._wheel_recent_var, "Recently Played"),
            (self._wheel_stats_var,  "Most Played"),
        ):
            self.ttk.Checkbutton(
                wheels_checks, text=label, variable=var,
            ).pack(anchor="w", pady=2)

        self.ttk.Button(
            rebuild_lf, text="Refresh selected", width=28,
            command=self._refresh_all_wheels,
        ).pack(anchor="w", padx=6, pady=(0, 6))

        # ── Step 3 — Register in HyperSpin main menu ─────────────────────────
        register_lf = self.ttk.LabelFrame(
            frame, text="Step 3 — Register in HyperSpin main menu",
        )
        register_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            register_lf,
            text=("Add the wheel systems to HyperSpin's main carousel. "
                  "Favorites and Recently Played are not auto-registered; "
                  "Most Played is. Also a one-click repair: it regenerates "
                  "the RocketLauncher settings and bundled media for a "
                  "synthetic wheel that has gone missing."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 6))

        reg_btn_row = self.ttk.Frame(register_lf)
        reg_btn_row.pack(anchor="w", padx=6, pady=(0, 6))
        self.ttk.Button(
            reg_btn_row, text="Add wheels to Main Menu", width=28,
            command=self._register_wheels_in_main_menu,
        ).pack(side="left")

        # ── Step 4 — Manage favorites ─────────────────────────────────────────
        fav_lf = self.ttk.LabelFrame(
            frame, text="Step 4 — Manage favorites",
        )
        fav_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            fav_lf,
            text=("Add or remove single games in the cross-system Favorites "
                  "wheel. Run Step 2 (with Favorites checked) afterwards to "
                  "push the change into HyperSpin."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 4))

        fav_row = self.ttk.Frame(fav_lf)
        fav_row.pack(fill="x", padx=6, pady=(2, 6))
        self.ttk.Label(fav_row, text="System").pack(side="left")
        self._fav_system_var = self.tk.StringVar()
        self._fav_system_combo = self.ttk.Combobox(
            fav_row, textvariable=self._fav_system_var,
            state="readonly", width=22,
        )
        self._fav_system_combo.pack(side="left", padx=6)
        self._fav_system_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_fav_games(),
        )
        self.ttk.Label(fav_row, text="Game").pack(side="left", padx=(8, 0))
        self._fav_rom_var = self.tk.StringVar()
        self._fav_rom_combo = self.ttk.Combobox(
            fav_row, textvariable=self._fav_rom_var,
            state="readonly",
        )
        self._fav_rom_combo.pack(side="left", fill="x", expand=True, padx=6)
        self._fav_rom_combo.bind("<Return>", lambda _e: self._fav_add())
        self.ttk.Button(
            fav_row, text="↻", width=3,
            command=self._refresh_fav_games,
        ).pack(side="left", padx=(0, 6))
        self.ttk.Button(
            fav_row, text="Add", command=self._fav_add,
        ).pack(side="left")
        self.ttk.Button(
            fav_row, text="Remove", command=self._fav_remove,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            fav_row, text="List", command=self._fav_list,
        ).pack(side="left")

        # ── Install .bat helpers (optional) ──────────────────────────────────
        helpers_lf = self.ttk.LabelFrame(frame, text="Install .bat helpers (optional)")
        helpers_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            helpers_lf,
            text=("Install .bat helpers so Favorites / Recently Played / "
                  "Most Played can be refreshed from inside HyperSpin "
                  "without dropping to a console — either via HyperHQ → "
                  "Tools (the default), or as 'games' inside an existing "
                  "wheel system like 'Toolkit' (the second section)."),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 6))

        self.ttk.Label(
            helpers_lf,
            text=(
                "Helpers written:\n"
                "  • Refresh Favorites.bat        → spindoctor-fav rebuild --apply\n"
                "  • Refresh Recently Played.bat  → spindoctor-recent rebuild --apply\n"
                "  • Refresh Most Played.bat      → spindoctor-stats build-wheel --apply\n"
                "  • Refresh All.bat              → all three in sequence"
            ),
            justify="left", foreground=_FG_DIM,
            font="TkFixedFont",
        ).pack(anchor="w", padx=6, pady=(0, 8))

        # HyperHQ → Tools install (default)
        hhq_frame = self.ttk.LabelFrame(
            helpers_lf, text="Install for HyperHQ → Tools menu",
        )
        hhq_frame.pack(fill="x", padx=6, pady=(2, 8))
        self.ttk.Label(
            hhq_frame,
            text=("Output directory (optional). Defaults to "
                  "<rocketlauncher_dir>/Modules/HyperLaunch/Tools/spindoctor "
                  "if blank. After installing, register the .bat files in "
                  "HyperHQ → Tools tab so they show up in the in-cabinet "
                  "Tools menu."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(2, 4))

        out_row = self.ttk.Frame(hhq_frame)
        out_row.pack(fill="x", padx=6, pady=2)
        self._tools_outdir_var = self.tk.StringVar()
        self.ttk.Entry(
            out_row, textvariable=self._tools_outdir_var,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.ttk.Button(
            out_row, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._tools_outdir_var, "Pick output directory",
            ),
        ).pack(side="left")
        self.ttk.Button(
            hhq_frame, text="Install Tools-menu helpers",
            command=self._run_install_tools,
        ).pack(anchor="w", padx=6, pady=(4, 6))

        # Wheel-integration mode (e.g. user's 'Toolkit' wheel)
        wheel_frame = self.ttk.LabelFrame(
            helpers_lf, text="Install into an existing wheel system",
        )
        wheel_frame.pack(fill="x", padx=6, pady=(2, 8))
        self.ttk.Label(
            wheel_frame,
            text=("Adds matching <game> entries to the named system's "
                  "database XML and writes per-game PCLauncher INIs "
                  "alongside the bats. Use this if you have a 'Toolkit' "
                  "or 'Tools' wheel (a HyperSpin system whose 'games' "
                  "are maintenance tasks). The system must already exist "
                  "under <hyperspin_dir>/Databases/<NAME>/<NAME>.xml and "
                  "use PCLauncher as its emulator."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        ).pack(anchor="w", padx=6, pady=(2, 4))

        sys_row = self.ttk.Frame(wheel_frame)
        sys_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(sys_row, text="Target wheel system").pack(side="left")
        self._tools_wheel_var = self.tk.StringVar(value="Toolkit")
        self._tools_wheel_combo = self.ttk.Combobox(
            sys_row, textvariable=self._tools_wheel_var,
            state="readonly", width=30,
        )
        self._tools_wheel_combo.pack(side="left", padx=6)
        self.ttk.Button(
            sys_row, text="Install into wheel",
            command=self._run_install_tools_into_wheel,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            sys_row, text="Uninstall from wheel",
            command=self._run_uninstall_tools_from_wheel,
        ).pack(side="left", padx=6)

        # Auto-refresh on cabinet startup
        sched_frame = self.ttk.LabelFrame(
            helpers_lf, text="Auto-refresh on cabinet startup",
        )
        sched_frame.pack(fill="x", padx=6, pady=(2, 8))
        if sys.platform == "win32":
            self.ttk.Label(
                sched_frame,
                text=("Schedule a Windows Task Scheduler 'At log on' task "
                      "that runs Refresh All at every cabinet startup. "
                      "The task runs as the current user with limited "
                      "privileges (no UAC prompt). Optional delay lets "
                      "HyperSpin / RocketLauncher settle before the "
                      "rebuild kicks in."),
                wraplength=860, justify="left", foreground=_FG_DIM,
            ).pack(anchor="w", padx=6, pady=(2, 4))

            delay_row = self.ttk.Frame(sched_frame)
            delay_row.pack(fill="x", padx=6, pady=2)
            self.ttk.Label(delay_row, text="Delay after log-on (minutes)").pack(
                side="left",
            )
            self._tools_delay_var = self.tk.StringVar(value="2")
            self.ttk.Spinbox(
                delay_row, from_=0, to=60, textvariable=self._tools_delay_var,
                width=6,
            ).pack(side="left", padx=6)

            sched_btns = self.ttk.Frame(sched_frame)
            sched_btns.pack(fill="x", padx=6, pady=(4, 6))
            self.ttk.Button(
                sched_btns, text="Schedule auto-refresh",
                command=self._schedule_autorefresh,
            ).pack(side="left")
            self.ttk.Button(
                sched_btns, text="Remove scheduled task",
                command=self._remove_autorefresh,
            ).pack(side="left", padx=6)
            self.ttk.Button(
                sched_btns, text="Check task status",
                command=self._check_autorefresh,
            ).pack(side="left", padx=6)
        else:
            self.ttk.Label(
                sched_frame,
                text=("Windows-only — Task Scheduler doesn't exist on "
                      "this OS. macOS equivalent: launchd plist (~/Library/"
                      "LaunchAgents/com.spindoctor.refresh.plist with a "
                      "RunAtLoad key). Linux equivalent: a "
                      "`@reboot spindoctor-fav rebuild --apply && "
                      "spindoctor-recent rebuild --apply && "
                      "spindoctor-stats build-wheel --apply` line in "
                      "`crontab -e`, or a systemd-user unit."),
                wraplength=860, justify="left", foreground=_FG_DIM,
            ).pack(anchor="w", padx=6, pady=(2, 6))

        # Manual fallback instructions
        manual_frame = self.ttk.LabelFrame(
            helpers_lf, text="Manual setup (if you'd rather do it yourself)",
        )
        manual_frame.pack(fill="x", padx=6, pady=(2, 8))
        self.ttk.Label(
            manual_frame,
            text=(
                "HyperHQ → Tools menu:\n"
                "  1. Open HyperHQ.exe (sits next to HyperSpin.exe).\n"
                "  2. Go to the Tools tab.\n"
                "  3. Click Add and point each entry at the matching .bat\n"
                "     under <rocketlauncher>/Modules/HyperLaunch/Tools/spindoctor.\n"
                "  4. Save. The helpers appear in HyperSpin's in-cabinet Tools menu.\n"
                "\n"
                "Windows Task Scheduler (manual):\n"
                "  Use the 'Schedule auto-refresh' button above — it writes\n"
                "  both a launcher .bat (with IDLE process priority so HyperSpin\n"
                "  is never starved) and a hidden-run .vbs shim so no cmd.exe\n"
                "  window surfaces on the cabinet screen.\n"
                "\n"
                "  If you need to register the task by hand instead:\n"
                "  1. Win+R → 'taskschd.msc'.\n"
                "  2. Action → Create Task → name: 'SpinDoctor Refresh Wheels'.\n"
                "  3. Triggers → New → Begin: 'At log on' → Delay: 2 minutes.\n"
                "  4. Actions → New → Program: wscript.exe\n"
                "     Arguments: //B \"<path>\\spindoctor-refresh-wheels.vbs\"\n"
                "     (generate the .bat/.vbs pair first with 'Schedule auto-refresh',\n"
                "      then remove and re-register by hand if needed)\n"
                "  5. Settings → uncheck 'Stop the task if it runs longer than'."
            ),
            justify="left", foreground=_FG_DIM,
            font="TkFixedFont",
        ).pack(anchor="w", padx=6, pady=(2, 6))

        # ── Scrub wheel data ───────────────────────────────────────────────────
        scrub_lf = self.ttk.LabelFrame(frame, text="Reset wheel data (scrub)")
        scrub_lf.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            scrub_lf,
            text=(
                "Permanently delete favorites and/or play statistics so you can start "
                "fresh. Use 'Backup to' to create a restorable snapshot — "
                "Statistics.ini files are written by RocketLauncher and cannot be "
                "regenerated by SpinDoctor. The backup runs in both dry-run and apply modes."
            ),
            wraplength=860, justify="left",
        ).pack(anchor="w", padx=6, pady=(4, 6))

        # What to scrub
        scrub_what_row = self.ttk.Frame(scrub_lf)
        scrub_what_row.pack(anchor="w", padx=6, pady=2)
        self.ttk.Label(scrub_what_row, text="What to clear:").pack(side="left")
        self._scrub_favorites_var = self.tk.BooleanVar(value=True)
        self._scrub_stats_var = self.tk.BooleanVar(value=True)
        self._scrub_hs_favorites_var = self.tk.BooleanVar(value=False)
        _scrub_fav_chk = self.ttk.Checkbutton(
            scrub_what_row, text="Favorites", variable=self._scrub_favorites_var,
        )
        _scrub_fav_chk.pack(side="left", padx=(10, 4))
        _attach_tooltip(
            _scrub_fav_chk,
            "Empties ~/.spindoctor/favorites.json and removes:\n"
            "  • Databases/Favorites/Favorites.xml\n"
            "  • Media/Favorites/ (all files)\n"
            "  • Modules/PCLauncher/Favorites/ (all .ini launchers)\n\n"
            "Does NOT touch per-system HyperSpin favorites\n"
            "(<System>_Favorites.ini / favorites.txt). Tick\n"
            "'HyperSpin per-system favorites' below to clear those too.",
            self.tk,
        )
        _scrub_stats_chk = self.ttk.Checkbutton(
            scrub_what_row, text="Play statistics", variable=self._scrub_stats_var,
        )
        _scrub_stats_chk.pack(side="left", padx=4)
        _attach_tooltip(
            _scrub_stats_chk,
            "Deletes all RocketLauncher Statistics.ini files. Scans:\n"
            "  • Settings/Global Statistics/<System>.ini  (classic)\n"
            "  • Settings/<System>/Statistics.ini  (legacy)\n"
            "  • Data/Statistics/<System>.ini  (newer RL)\n\n"
            "Also removes the Recently Played and Most Played wheel content.\n\n"
            "WARNING: Statistics.ini files cannot be regenerated — use\n"
            "'Backup first' below before scrubbing.",
            self.tk,
        )

        # Second row: HyperSpin per-system favorites (separate row — longer label)
        scrub_hs_row = self.ttk.Frame(scrub_lf)
        scrub_hs_row.pack(anchor="w", padx=6, pady=(0, 2))
        _scrub_hs_chk = self.ttk.Checkbutton(
            scrub_hs_row,
            text="HyperSpin per-system favorites (start fresh for fav sync)",
            variable=self._scrub_hs_favorites_var,
        )
        _scrub_hs_chk.pack(side="left", padx=(10, 4))
        _attach_tooltip(
            _scrub_hs_chk,
            "Clears the favorites that HyperSpin's F-key writes on a\n"
            "per-console basis. Three sources are removed:\n"
            "  • Databases/<System>/<System>_Favorites.ini\n"
            "  • Databases/<System>/favorites.txt\n"
            "  • favorite=\"1\" attributes in <System>.xml databases\n\n"
            "Use this when you want 'fav sync' to start from a blank\n"
            "slate — e.g. after curating your library and wanting only\n"
            "the games you still have to appear as favorites.\n\n"
            "Not ticked by default — must be requested explicitly.\n"
            "Backupable via 'Backup first'.",
            self.tk,
        )

        # Optional backup directory
        scrub_bk_row = self.ttk.Frame(scrub_lf)
        scrub_bk_row.pack(fill="x", padx=6, pady=(4, 2))
        self.ttk.Label(scrub_bk_row, text="Backup to:").pack(side="left")
        _scrub_cfg = load_config()
        self._scrub_backup_var = self.tk.StringVar(
            value=getattr(_scrub_cfg, "backup_dir", "") or ""
        )
        self.ttk.Entry(scrub_bk_row, textvariable=self._scrub_backup_var, width=50).pack(
            side="left", padx=6, fill="x", expand=True,
        )
        self.ttk.Button(
            scrub_bk_row, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._scrub_backup_var, "Pick folder to save scrub backup"
            ),
        ).pack(side="left")

        self.ttk.Label(
            scrub_lf,
            text=(
                "Backup runs on both dry-run and apply. "
                "Leave blank to skip — not recommended for play statistics."
            ),
            foreground="#888888",
        ).pack(anchor="w", padx=6, pady=(0, 4))

        # Scrub button
        scrub_btn_row = self.ttk.Frame(scrub_lf)
        scrub_btn_row.pack(anchor="w", padx=6, pady=(2, 6))
        self.ttk.Button(
            scrub_btn_row, text="Scrub",
            command=self._run_scrub,
        ).pack(side="left")

        # Restore section
        scrub_restore_lf = self.ttk.LabelFrame(scrub_lf, text="Restore from scrub backup")
        scrub_restore_lf.pack(fill="x", padx=6, pady=(8, 6))

        scrub_restore_path_row = self.ttk.Frame(scrub_restore_lf)
        scrub_restore_path_row.pack(fill="x", padx=6, pady=(4, 2))
        self.ttk.Label(scrub_restore_path_row, text="Backup folder:").pack(side="left")
        self._scrub_restore_path_var = self.tk.StringVar(
            value=getattr(_scrub_cfg, "backup_dir", "") or ""
        )
        self.ttk.Entry(
            scrub_restore_path_row, textvariable=self._scrub_restore_path_var, width=50,
        ).pack(side="left", padx=6, fill="x", expand=True)
        self.ttk.Button(
            scrub_restore_path_row, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._scrub_restore_path_var,
                "Pick scrub backup folder (scrub-<timestamp>)",
            ),
        ).pack(side="left")

        scrub_restore_btn_row = self.ttk.Frame(scrub_restore_lf)
        scrub_restore_btn_row.pack(anchor="w", padx=6, pady=(2, 6))
        self.ttk.Button(
            scrub_restore_btn_row, text="Restore",
            command=self._run_scrub_restore,
        ).pack(side="left")

        return frame

    def _run_install_tools(self) -> None:
        args = ["install-tools"]
        outdir = self._tools_outdir_var.get().strip()
        if outdir:
            args += ["--output-dir", outdir]
        self._run_cli("spindoctor", args)

    def _run_install_tools_into_wheel(self) -> None:
        wheel = self._tools_wheel_var.get().strip()
        if not wheel:
            self.messagebox.showwarning(
                "Wheel name required",
                "Type the HyperSpin system name to install into "
                "(e.g. 'Toolkit') before clicking Install into wheel.",
            )
            return
        self._run_cli(
            "spindoctor", ["install-tools", "--add-to-system", wheel],
        )

    def _run_uninstall_tools_from_wheel(self) -> None:
        wheel = self._tools_wheel_var.get().strip()
        if not wheel:
            self.messagebox.showwarning(
                "Wheel name required",
                "Type the HyperSpin system name to uninstall from "
                "(e.g. 'Toolkit') before clicking Uninstall from wheel.",
            )
            return
        if not self.messagebox.askyesno(
            "Confirm uninstall",
            f"Remove all SpinDoctor helper files and database entries "
            f"from the '{wheel}' wheel?\n\n"
            "This deletes the .bat and .ini files from the PCLauncher "
            "folder and removes the matching <game> entries from "
            f"{wheel}.xml. This cannot be undone (except by re-running "
            "'Install into wheel').",
        ):
            return
        args = ["uninstall-tools", "--add-to-system", wheel]
        if self._global_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    # ── Auto-refresh on startup (Windows Task Scheduler) ──────────────────────

    def _write_refresh_bat(self) -> Path:
        """Write spindoctor-refresh-wheels.bat and return its path.

        The bat is written next to the exe when running as a frozen binary,
        or to ~/.spindoctor/ for source installs.  Keeping the bat short
        (three lines, no embedded paths) lets the schtasks /TR command stay
        well under the 261-character limit — the bat itself can embed the
        full paths.

        Each sub-command is wrapped with ``START /LOW /B /WAIT`` so the
        spindoctor executables run at Windows IDLE process priority — they
        only consume CPU cycles that HyperSpin and RocketLauncher don't
        need, keeping the cabinet fully responsive during the refresh.
        """
        if getattr(sys, "frozen", False):
            bat_dir = Path(sys.executable).parent
            fav    = bat_dir / "spindoctor-fav.exe"
            recent = bat_dir / "spindoctor-recent.exe"
            stats  = bat_dir / "spindoctor-stats.exe"
            lines = (
                "@echo off\r\n"
                f'start /LOW /B /WAIT "" "{fav}" rebuild --apply\r\n'
                f'start /LOW /B /WAIT "" "{recent}" rebuild --apply\r\n'
                f'start /LOW /B /WAIT "" "{stats}" build-wheel --apply\r\n'
            )
        else:
            bat_dir = Path.home() / ".spindoctor"
            bat_dir.mkdir(parents=True, exist_ok=True)
            lines = (
                "@echo off\r\n"
                'start /LOW /B /WAIT "" spindoctor-fav rebuild --apply\r\n'
                'start /LOW /B /WAIT "" spindoctor-recent rebuild --apply\r\n'
                'start /LOW /B /WAIT "" spindoctor-stats build-wheel --apply\r\n'
            )
        bat_path = bat_dir / "spindoctor-refresh-wheels.bat"
        bat_path.write_text(lines, encoding="utf-8")
        return bat_path

    def _write_vbs_shim(self, bat_path: Path) -> Path:
        """Write a VBScript shim that invokes *bat_path* in a hidden window.

        ``wscript.exe //B shim.vbs`` is the task's actual /TR command.  The
        VBS calls ``WshShell.Run(bat, 0, True)`` — window style 0 = hidden,
        bWaitOnReturn = True — so no cmd.exe console window ever surfaces on
        the cabinet screen during the scheduled refresh.

        The shim derives the bat's path from its own location so the files
        can be moved together without re-registering the task.
        """
        vbs_content = (
            "' SpinDoctor wheel-refresh hidden launcher\r\n"
            "' Generated by spindoctor-gui — do not edit.\r\n"
            "Set ws = CreateObject(\"WScript.Shell\")\r\n"
            "Dim batPath\r\n"
            "batPath = Left(WScript.ScriptFullName, "
            "InStrRev(WScript.ScriptFullName, \"\\\\\")) "
            "& \"spindoctor-refresh-wheels.bat\"\r\n"
            "ws.Run Chr(34) & batPath & Chr(34), 0, True\r\n"
        )
        vbs_path = bat_path.with_suffix(".vbs")
        vbs_path.write_text(vbs_content, encoding="utf-8")
        return vbs_path

    def _autorefresh_command(self, vbs_path: Path) -> str:
        # schtasks /TR has a 261-character hard limit.  Embedding three
        # full exe paths in a PowerShell one-liner easily blows past that
        # on cabinet installs where the SpinDoctor folder lives under a
        # long user path.  Solution: write a companion bat + VBS pair and
        # point the task at the VBS.
        # "wscript.exe //B path" is ~24 chars + the vbs path — stays
        # short regardless of install location.
        # //B suppresses any MsgBox / InputBox dialogs the script might
        # accidentally trigger; the VBS itself uses ws.Run(..., 0, True)
        # so no console window ever appears on the cabinet screen.
        return f'wscript.exe //B "{vbs_path}"'

    def _parse_delay_minutes(self) -> Optional[int]:
        raw = self._tools_delay_var.get().strip()
        if not raw:
            return None
        if not raw.isdigit():
            self.messagebox.showwarning(
                "Invalid delay",
                "Delay must be a non-negative integer (minutes).",
            )
            return -1  # sentinel: caller should bail
        return int(raw)

    def _schedule_autorefresh(self) -> None:
        from . import autostart
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = _RunRecord(
            started_at=started_at,
            argv_str="autorefresh schedule",
            dry_run=False,
        )
        try:
            delay = self._parse_delay_minutes()
            if delay == -1:
                return
            bat_path = self._write_refresh_bat()
            vbs_path = self._write_vbs_shim(bat_path)
            bat_text = (
                f"\n[Auto-refresh] wrote launcher bat → {bat_path}\n"
                f"[Auto-refresh] wrote hidden-run shim → {vbs_path}\n"
            )
            self._append_output(bat_text)
            record.append(bat_text)
            result = autostart.create_logon_task(
                self._autorefresh_command(vbs_path),
                delay_minutes=delay,
            )
        except autostart.NotSupportedError as exc:
            self.messagebox.showinfo("Not supported on this OS", str(exc))
            return
        except (ValueError, RuntimeError) as exc:
            self.messagebox.showerror("Could not schedule task", str(exc))
            return
        except OSError as exc:
            self.messagebox.showerror(
                "Could not write bat/vbs file",
                f"Failed to write the companion script files:\n{exc}",
            )
            return
        task_text = (
            f"\n[Task Scheduler] created '{result.name}' → "
            f"{result.command}\n{result.output}\n"
            f"Launcher bat: {bat_path}\n"
            f"Hidden-run shim: {vbs_path}\n"
            "Reboot or log out and back in to activate it.\n"
        )
        self._append_output(task_text)
        record.append(task_text)
        record.exit_code = 0
        self._run_history.append(record)
        self._refresh_logs_tab()
        self._flash_status(f"Auto-refresh task '{result.name}' registered.")

    def _remove_autorefresh(self) -> None:
        from . import autostart
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not autostart.task_exists():
                self.messagebox.showinfo(
                    "Nothing to remove",
                    f"No task named '{autostart.DEFAULT_LOGON_TASK}' is "
                    "registered.",
                )
                return
            output = autostart.delete_logon_task()
        except autostart.NotSupportedError as exc:
            self.messagebox.showinfo("Not supported on this OS", str(exc))
            return
        except RuntimeError as exc:
            self.messagebox.showerror("Could not remove task", str(exc))
            return
        output_text = f"\n[Task Scheduler] removed task.\n{output}\n"
        self._append_output(output_text)
        record = _RunRecord(
            started_at=started_at,
            argv_str="autorefresh remove",
            dry_run=False,
        )
        record.append(output_text)
        record.exit_code = 0
        self._run_history.append(record)
        self._refresh_logs_tab()
        self._flash_status("Auto-refresh task deleted.")

    def _check_autorefresh(self) -> None:
        from . import autostart
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            exists = autostart.task_exists()
        except autostart.NotSupportedError as exc:
            self.messagebox.showinfo("Not supported on this OS", str(exc))
            return
        msg = (
            f"Task '{autostart.DEFAULT_LOGON_TASK}' is "
            f"{'REGISTERED' if exists else 'not registered'}."
        )
        output_text = f"\n[Task Scheduler] {msg}\n"
        self._append_output(output_text)
        record = _RunRecord(
            started_at=started_at,
            argv_str="autorefresh check-status",
            dry_run=None,
        )
        record.append(output_text)
        record.exit_code = 0
        self._run_history.append(record)
        self._refresh_logs_tab()
        self._flash_status(msg)

    # ── Custom command tab ────────────────────────────────────────────────────

    def _build_custom_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Run any spindoctor sub-command. Pick a preset from the "
                  "dropdown to start, then edit placeholders like <SYSTEM> "
                  "or <PATH> before hitting Run. You can also type any "
                  "arguments by hand — the field is fully editable."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        row = self.ttk.Frame(frame)
        row.pack(fill="x", pady=4)
        self.ttk.Label(row, text="spindoctor").pack(side="left")
        self._custom_var = self.tk.StringVar(value=_CUSTOM_COMMAND_PRESETS[0])
        # Editable Combobox = "dropdown of presets + free-text entry" in
        # one widget, which is what cabinet owners actually want here:
        # they don't know the full command surface yet, but once they
        # pick a preset they may need to tweak <SYSTEM> or <PATH>.
        self._custom_combo = self.ttk.Combobox(
            row,
            textvariable=self._custom_var,
            values=list(_CUSTOM_COMMAND_PRESETS),
            state="normal",
        )
        self._custom_combo.pack(side="left", fill="x", expand=True, padx=6)
        self._custom_combo.bind("<Return>", lambda _e: self._run_custom())
        self._custom_combo.bind(
            "<<ComboboxSelected>>", self._on_custom_preset_selected
        )
        self.ttk.Button(row, text="Run", command=self._run_custom).pack(side="left")

        hint = self.ttk.Label(
            frame,
            text=("Tip: anything in <ANGLE_BRACKETS> is a placeholder you "
                  "need to replace before running. Append --help to any "
                  "command to see its full option list in the Output panel."),
            wraplength=860, justify="left", foreground=_FG_DIM,
        )
        hint.pack(anchor="w", pady=(8, 0))

        return frame

    def _on_custom_preset_selected(self, _event=None) -> None:
        """Auto-advance past section-header entries in the preset dropdown.

        Header strings start with ``_PRESET_SECTION_HEADER_PREFIX`` (``───``).
        They're purely visual dividers; selecting one moves the Combobox value
        forward to the first real command that follows.
        """
        val = self._custom_var.get()
        if not val.startswith(_PRESET_SECTION_HEADER_PREFIX):
            return
        values: list[str] = list(self._custom_combo["values"])
        try:
            idx = values.index(val)
        except ValueError:
            return
        for candidate in values[idx + 1:]:
            if not candidate.startswith(_PRESET_SECTION_HEADER_PREFIX):
                self._custom_var.set(candidate)
                return

    def _run_custom(self) -> None:
        raw = self._custom_var.get().strip()
        if not raw:
            self._flash_validation("Type some arguments first.")
            return
        # Section-header entries (e.g. "─── LEDBlinky ───") are visual
        # dividers, not commands. Guard against accidentally clicking Run
        # after the Combobox auto-advance didn't fire for some reason.
        if raw.startswith(_PRESET_SECTION_HEADER_PREFIX):
            self._flash_validation("That's a section header — pick a command below it.")
            return
        # Catch unfilled `<PLACEHOLDER>` tokens before we shell out — the
        # CLI would just complain about a literal "<SYSTEM>" path which is
        # confusing if the user didn't realise the dropdown was a template.
        if "<" in raw and ">" in raw:
            self.messagebox.showwarning(
                "Replace placeholders first",
                "The command still contains <PLACEHOLDER> tokens. Replace "
                "them with real values (e.g. a system name or a path) "
                "before clicking Run.",
            )
            return
        try:
            # posix=False matches Windows quoting (`"foo bar"` stays one token,
            # backslashes in paths don't get eaten as escapes).
            args = shlex.split(raw, posix=(sys.platform != "win32"))
        except ValueError as exc:
            self.messagebox.showerror(
                "Couldn't parse arguments",
                f"Could not split your command into arguments:\n  {exc}\n\n"
                "Common cause: an unmatched quote — make sure every "
                '"" or \'\' you opened is closed.',
            )
            return
        self._run_cli("spindoctor", args)

    # ── Subprocess execution ──────────────────────────────────────────────────

    def _run_cli(
        self,
        binary: str,
        args: Sequence[str],
        on_complete: Optional[Callable[[int], None]] = None,
    ) -> None:
        """Spawn `binary args…` in the background and stream output to the panel."""
        if self._proc is not None and self._proc.poll() is None:
            self.messagebox.showinfo(
                "Busy",
                "Another command is still running. Wait for it to finish or "
                "click Stop in the bottom bar.",
            )
            return
        try:
            argv = resolve_cli_command(binary) + list(args)
        except CliNotFoundError as exc:
            # CliNotFoundError already carries an actionable message
            # explaining where the binary was looked for; surface that
            # plus the most common fix (pip install -e .) for dev
            # checkouts and (keep all 5 exes in one folder) for frozen
            # builds.
            self.messagebox.showerror(
                "SpinDoctor CLI not found",
                f"{exc}\n\n"
                "Common fixes:\n"
                "• Frozen / Windows binary install: keep all five .exe files "
                "in the same folder — the GUI finds its peers by looking "
                "next to itself.\n"
                "• Source install: re-run `pip install -e .` from the "
                "repo root so the console scripts get registered.",
            )
            return

        # Heuristic: anything without `--apply` is a dry-run for our
        # apply-mode commands. Tag the run so the Logs tab can label
        # it, and prepend a banner to the streaming output so the
        # user can't miss "this was a preview, not a real change".
        # Read-only verbs (doctor, audit, find-dupes, etc.) never
        # accept --apply, so suppress the banner for them — otherwise
        # `spindoctor doctor` shows "DRY RUN COMPLETE — re-run with
        # --apply to commit", which is nonsense for a read-only check.
        # None  = N/A (read-only command — dry-run concept doesn't apply)
        # True  = dry-run preview (has --apply concept, flag not passed)
        # False = actual write (--apply was passed)
        # The --apply check runs first so commands that are read-only
        # *without* the flag but write *with* it (doctor --apply,
        # lightgun detect --apply) are still recorded as actual writes.
        if "--apply" in args:
            is_dry_run: Optional[bool] = False
        elif _is_read_only_invocation(tuple(args)):
            is_dry_run = None
        else:
            is_dry_run = True
        argv_str = _format_argv(argv)
        record = _RunRecord(
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            argv_str=argv_str,
            dry_run=is_dry_run,
        )
        # Build a human-readable slug from the binary tag + positional args
        # so auto-saved log files get a meaningful name (e.g. "recent_rebuild"
        # rather than "--apply" or "--verbose").
        _bin_tag = binary[len("spindoctor-"):] if binary.startswith("spindoctor-") else ""
        _positional = [a for a in args if not a.startswith("-")]
        _slug_parts = ([_bin_tag] if _bin_tag else []) + _positional
        record.command_slug = "_".join(_slug_parts) if _slug_parts else "run"
        # _run_history is a bounded deque(maxlen=200) — append is O(1)
        # and oldest entries are evicted automatically.
        self._run_history.append(record)
        self._current_run = record

        banner = "\n=== DRY RUN ===\n" if is_dry_run else ""
        self._append_output(f"{banner}\n$ {argv_str}\n")
        record.append(f"$ {argv_str}\n")
        # Monotonic clock so we can report "OK in 3s" / "FAILED in 12s"
        # when the run finishes, without being skewed by wall-clock
        # adjustments during a long migration.
        self._run_started_monotonic = time.monotonic()
        self._run_label = f"{binary} {args[0] if args else ''}".strip()
        self._set_status(
            f"{'[DRY RUN] ' if is_dry_run else ''}Running: "
            f"{binary} {' '.join(args)}"
        )
        self._running_tab_idx = self._nb.index("current")
        self._set_tab_badge(self._running_tab_idx, "⟳")
        self._stop_btn.configure(state="normal")
        self._set_busy(True)
        # Logs tab refreshes itself from _run_history when it's open;
        # nudge it now so the new row appears immediately.
        self._refresh_logs_tab()

        # Force unbuffered output from the child so progress bars / per-row
        # status lines arrive in real time. PyInstaller-frozen Click apps
        # otherwise buffer aggressively when stdout isn't a tty.
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        try:
            self._proc = subprocess.Popen(
                argv,
                # DEVNULL, not inherit: when the GUI is launched from a
                # terminal the child would otherwise share that terminal's
                # stdin, and any prompt (mainmenu edit, config init, an
                # unexpected picker) would block forever waiting for input
                # the GUI window can't supply. With /dev/null the prompt
                # sees EOF and the CLI aborts cleanly instead of hanging.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            from ._errors import humanize_oserror
            self.messagebox.showerror(
                "Could not launch",
                humanize_oserror(exc, action=f"launch {argv[0]}"),
            )
            self._stop_btn.configure(state="disabled")
            self._set_busy(False)
            # Clear the per-run timing state before bailing — otherwise
            # the next successful run's _on_proc_done picks up the
            # stale monotonic timestamp and reports a hugely inflated
            # "OK in N s" elapsed.
            self._run_started_monotonic = None
            self._run_label = ""
            self._set_status("Ready.")
            return

        self._reader_thread = threading.Thread(
            target=self._pump_output,
            args=(self._proc, on_complete),
            daemon=True,
        )
        self._reader_thread.start()

    def _pump_output(
        self,
        proc: subprocess.Popen,
        on_complete: Optional[Callable[[int], None]],
    ) -> None:
        # Runs on a worker thread; everything it touches goes through the queue
        # so the Tk main loop stays the only thread mutating widgets.
        # Explicit guard rather than `assert` — assertions are stripped
        # under `python -O` (used in some PyInstaller builds) and the
        # NoneType iteration below would otherwise throw a confusing
        # AttributeError into the worker.
        if proc.stdout is None:
            self._line_queue.put(_DoneMarker(proc.wait(), on_complete))
            return
        try:
            for line in proc.stdout:
                self._line_queue.put(line)
        finally:
            rc = proc.wait()
            self._line_queue.put(f"\n[exit code {rc}]\n")
            # Sentinel — the queue drain handler uses this to flip UI state
            # back to idle and fire the optional completion callback.
            self._line_queue.put(_DoneMarker(rc, on_complete))

    def _drain_queue(self) -> None:
        # CRITICAL: this loop is the only path that transitions the GUI
        # out of the "running" state. If anything inside raises and
        # propagates, the ``root.after(50, …)`` re-registration at the
        # bottom never runs, and the user is left with a permanently
        # busy GUI (the symptom: backup finishes, files appear in the
        # destination, but the tab badge / Stop button / status bar
        # never clear). Wrap *everything* in try/except so the loop
        # always re-arms.
        try:
            while True:
                try:
                    item = self._line_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if isinstance(item, _DoneMarker):
                        self._on_proc_done(item)
                    else:
                        self._append_output(item)
                        # Mirror into the current run's per-record buffer
                        # so the Logs tab can replay the same content
                        # later. The Output panel and the Logs tab show
                        # identical text at the moment a run finishes.
                        if self._current_run is not None:
                            self._current_run.append(item)
                except Exception as exc:  # noqa: BLE001 — never break drain
                    try:
                        self._append_output(
                            f"\n[drain error: {exc!r}]\n"
                        )
                    except Exception:  # noqa: BLE001
                        pass

            # Stuck detector. If the subprocess has exited (poll() is
            # non-None) but no DoneMarker has shown up after a couple of
            # drain ticks, Rich's pipe-mode progress output may have
            # buffered without a trailing newline and the
            # ``for line in proc.stdout`` loop in _pump_output is still
            # waiting on EOF. Synthesise a marker so we don't sit in
            # the running state forever.
            self._check_stuck_proc()
        except Exception as exc:  # noqa: BLE001 — outer guard
            try:
                self._append_output(f"\n[drain error: {exc!r}]\n")
            except Exception:  # noqa: BLE001
                pass

        # Always re-arm, even if the body above raised.
        try:
            self._drain_after_id = self.root.after(50, self._drain_queue)
        except Exception:  # noqa: BLE001 — root may be destroyed
            self._drain_after_id = None

    def _check_stuck_proc(self) -> None:
        """Detect a subprocess that exited but never sent a DoneMarker.

        Rich's ``Progress`` in non-tty (pipe) mode can leave the
        ``for line in proc.stdout`` iterator in ``_pump_output`` waiting
        on a missing trailing newline, so the ``finally`` block that
        enqueues the DoneMarker never runs. When we detect that
        ``self._proc`` has exited but no marker has been processed for
        ≥ 2 drain ticks (~100 ms), synthesise one so the UI un-sticks.
        """
        proc = self._proc
        if proc is None:
            self._stuck_check_since = None
            return
        try:
            rc = proc.poll()
        except Exception:  # noqa: BLE001
            self._stuck_check_since = None
            return
        if rc is None:
            # Still running — no stuck condition.
            self._stuck_check_since = None
            return

        now = time.monotonic()
        first_seen = getattr(self, "_stuck_check_since", None)
        if first_seen is None:
            self._stuck_check_since = now
            return
        if now - first_seen < 0.1:
            return
        # Subprocess has been exited for at least 100 ms with no
        # DoneMarker. Force a finalisation. Reset the marker first so
        # we don't re-fire if a real marker shows up later.
        self._stuck_check_since = None
        try:
            self._append_output(
                "\n[recovered: subprocess exited but stdout did not "
                "close cleanly — finalising run anyway]\n"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._on_proc_done(_DoneMarker(rc, None))
        except Exception:  # noqa: BLE001
            pass

    def _on_close(self) -> None:
        """Persist GUI state, cancel the pending _drain_queue, terminate
        any running child, then let the window destroy.

        Without the after-cancel guard, the next ``after`` callback fires
        on a destroyed root and raises ``TclError`` on stderr, which
        startles users closing the GUI while a command is mid-stream.

        Without the process terminate, closing the window while a
        multi-minute audit or migrate is mid-stream leaves the child
        running headless on Windows (the reader thread is daemonic, so
        its parent GUI process exits cleanly, but the orphan
        ``spindoctor.exe`` keeps eating CPU until it finishes on its own).

        Window geometry and the last-active tab are saved here (not on
        every Configure / TabChanged event) so we don't thrash
        config.json during a window-edge drag.
        """
        # Best-effort save — never block close on an I/O error.
        try:
            self._save_gui_state()
        except Exception:  # noqa: BLE001 - persistence is non-load-bearing
            pass
        try:
            if getattr(self, "_drain_after_id", None) is not None:
                self.root.after_cancel(self._drain_after_id)
                self._drain_after_id = None
        except Exception:  # noqa: BLE001 - after_cancel can race on destroy
            pass
        # Terminate the child if one is still running. SIGTERM-equivalent
        # on POSIX, TerminateProcess on Windows — either way the child
        # gets a chance to flush stdout (the reader thread is daemonic
        # and we don't wait, so a slow flush just drops on the floor).
        proc = getattr(self, "_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (OSError, AttributeError):
                pass
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _save_gui_state(self) -> None:
        """Persist window geometry, maximized state, and last-active tab into config.json.

        Called from `_on_close` only — not on every <Configure> event —
        so the save happens once per session and config.json doesn't
        thrash during a window-edge drag.

        Geometry is only updated when the window is *not* maximized so
        the saved normal-state size is preserved for when the user later
        un-maximizes the window.
        """
        maximized = _is_maximized(self.root)
        if not maximized:
            try:
                geom = self.root.geometry()
            except Exception:  # noqa: BLE001
                geom = ""
        else:
            geom = getattr(load_config(), "gui_window_geometry", "") or ""
        try:
            tab_idx = int(self._nb.index("current"))
        except Exception:  # noqa: BLE001
            tab_idx = -1
        cfg = load_config()
        if (
            getattr(cfg, "gui_window_geometry", "") == geom
            and getattr(cfg, "gui_window_maximized", False) == maximized
            and getattr(cfg, "gui_last_active_tab", -1) == tab_idx
        ):
            return
        cfg.gui_window_geometry = geom
        cfg.gui_window_maximized = maximized
        cfg.gui_last_active_tab = tab_idx
        save_config(cfg)

    def _on_proc_done(self, marker: "_DoneMarker") -> None:
        # CRITICAL: every transition out of the "running" UI state lives
        # in this method. If any single step raises (e.g. ``_set_tab_badge``
        # on a destroyed widget, ``_refresh_logs_tab`` after a tab swap),
        # the rest of the cleanup is skipped and the GUI stays busy
        # forever. Wrap the body in try/finally and re-do the essentials
        # in ``finally`` so the user always escapes the running state.
        #
        # Chaining guard: if marker.callback calls _run_cli (the normal
        # pattern for multi-step workflows like _refresh_all_wheels), that
        # call stores the *next* Popen into self._proc before this
        # finally block runs.  We must NOT overwrite that with None or
        # call _set_busy(False) — doing so disconnects the GUI from the
        # new subprocess and leaves it stuck in the "running" state with
        # no DoneMarker ever arriving.  Snapshot self._proc here; the
        # finally block only tears down state when self._proc is still the
        # same object (i.e. the callback did NOT start a new process).
        old_proc = self._proc
        try:
            # Stamp the exit code on the run record + emit a closing
            # banner for dry-runs so the user always sees "preview done,
            # nothing changed on disk". Real applies don't get a banner —
            # the output panel already shows command-specific success
            # messages and we don't want to drown those out.
            was_dry_run = False
            if self._current_run is not None:
                self._current_run.exit_code = marker.rc
                was_dry_run = self._current_run.dry_run
                if was_dry_run:
                    footer = (
                        f"\n=== DRY RUN COMPLETE (exit {marker.rc}) — "
                        "nothing was written. Re-run with --apply to commit. ===\n"
                    )
                    self._append_output(footer)
                    self._current_run.append(footer)
                self._maybe_save_run_log(self._current_run)

            # Compute elapsed wall-clock for the status bar summary.
            # Falls back to '' if _run_cli wasn't called via the normal path
            # (e.g. older code paths that didn't stamp the monotonic clock).
            start = getattr(self, "_run_started_monotonic", None)
            elapsed_str = ""
            if start is not None:
                elapsed = time.monotonic() - start
                if elapsed < 60:
                    elapsed_str = f" in {elapsed:.1f}s"
                else:
                    mins, secs = divmod(int(elapsed), 60)
                    elapsed_str = f" in {mins}m{secs:02d}s"
            label = getattr(self, "_run_label", "") or "Last command"

            if marker.rc == 0:
                if was_dry_run:
                    self._set_status(
                        f"{label} — dry run OK{elapsed_str}. "
                        "View results in Output or the History tab."
                    )
                else:
                    self._set_status(f"{label} — OK{elapsed_str}.")
            else:
                self._set_status(
                    f"{label} — FAILED (exit {marker.rc}){elapsed_str}."
                )

            if self._running_tab_idx is not None:
                try:
                    self._set_tab_badge(
                        self._running_tab_idx,
                        "✓" if marker.rc == 0 else "✗",
                    )
                except Exception:  # noqa: BLE001 — widget race
                    pass

            # Re-render the Logs tab so the row's exit-code column updates.
            try:
                self._refresh_logs_tab()
            except Exception:  # noqa: BLE001 — widget race
                pass

            if marker.callback is not None:
                try:
                    marker.callback(marker.rc)
                except Exception as exc:  # noqa: BLE001 — never let a callback crash the UI
                    self._append_output(f"\n[callback error: {exc}]\n")
        except Exception as exc:  # noqa: BLE001 — surface but never swallow cleanup
            try:
                self._append_output(
                    f"\n[internal error finalising run: {exc!r}]\n"
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            # The stuck-checker is per-subprocess; always reset it.
            self._stuck_check_since = None
            # Only tear down the running state when the callback did NOT
            # start a new process.  If self._proc changed, _run_cli has
            # already set up fresh state (new _RunRecord, busy=True, etc.)
            # and we must leave it intact so the next subprocess gets its
            # own DoneMarker.
            chain_started = self._proc is not old_proc
            if not chain_started:
                # Guarantee the GUI leaves the running state regardless of
                # what raised above. Each of these is individually guarded
                # because a TclError on one widget shouldn't stop the others.
                self._proc = None
                self._current_run = None
                self._run_started_monotonic = None
                self._run_label = ""
                self._running_tab_idx = None
                try:
                    self._stop_btn.configure(state="disabled")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._set_busy(False)
                except Exception:  # noqa: BLE001
                    pass

    def _maybe_save_run_log(self, record: "_RunRecord") -> None:
        """Back up a finished run's exact output to output_dir as a .txt file.

        Only fires when the "Save Log" checkbox is ticked. The Logs tab
        already keeps this same content in memory for the session — this
        is purely a durable copy for cabinet owners who want to keep or
        share a record after the GUI closes.
        """
        if not self._global_savelog_var.get():
            return
        cfg = load_config()
        if not cfg.output_dir:
            self._append_output(
                "\n[Save Log] output_dir is not set — configure a "
                "Default output directory on the Setup tab to enable "
                "automatic log saving.\n"
            )
            return
        out_dir = Path(cfg.output_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / _default_run_log_filename(record)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_format_run_log_text(record))
            self._append_output(f"\n[Save Log] wrote {path}\n")
        except OSError as exc:
            from ._errors import humanize_oserror
            self._append_output(
                f"\n[Save Log] failed: "
                f"{humanize_oserror(exc, action='write log file')}\n"
            )

    def _stop_running(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            self._proc.terminate()
        except OSError:
            pass
        self._set_status("Stopping…")
        # Disable Stop immediately so a frantic double-click doesn't
        # land on the next process before it's even spawned. The
        # eventual _on_proc_done sets state back to disabled too, but
        # without this the button stays "armed" while we wait for the
        # 50 ms drain to deliver the DoneMarker.
        self._stop_btn.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        """Show / hide the progress bar in the status bar.

        Called by ``_run_cli`` when a subprocess is launched and by
        ``_on_proc_done`` when it exits. Defaults to the indeterminate
        spinner; when ``_chain_progress`` is set (active chained workflow,
        e.g. Full Metadata Refresh's fetch-meta → fetch-media → update-db),
        switches to a determinate bar so the user can see "step 2 of 3"
        progress visually, not just in the status text.

        Failures are swallowed because Tk widgets can race with window
        destruction during shutdown.
        """
        bar = getattr(self, "_busy_bar", None)
        if bar is None:
            return
        try:
            if busy:
                chain = getattr(self, "_chain_progress", None)
                bar.pack(side="right", padx=(0, 6))
                if chain is not None:
                    step, total = chain
                    # Determinate fill: the bar advances at the *start*
                    # of each step (step-1)/total → step/total just
                    # before _on_proc_done would tick it forward. So at
                    # step 2 of 3 we show ~33% (the previous step
                    # finished), filling toward 67% as the user waits.
                    bar.stop()  # in case it was already animating
                    bar.configure(mode="determinate", maximum=total)
                    bar["value"] = max(0, step - 1)
                else:
                    bar.configure(mode="indeterminate")
                    bar.start(80)
            else:
                bar.stop()
                bar.pack_forget()
        except Exception:  # noqa: BLE001 - widget race during teardown
            pass

    def _chain_start(self, total: int) -> None:
        """Open a chained-workflow progress session.

        Records the total step count so subsequent `_run_cli` calls
        in the chain render a determinate progress bar instead of an
        indeterminate spinner. Cleared by `_chain_end`.
        """
        self._chain_progress = (0, max(1, total))

    def _chain_advance(self, step: int) -> None:
        """Move the chained progress bar to *step* / total."""
        chain = getattr(self, "_chain_progress", None)
        if chain is None:
            return
        _, total = chain
        self._chain_progress = (min(step, total), total)

    def _chain_end(self) -> None:
        """Close a chained-workflow progress session.

        Reverts `_set_busy(True)` to the indeterminate spinner so the
        next standalone command's bar behaves normally.
        """
        self._chain_progress = None

    # ── output panel helpers ──────────────────────────────────────────────────

    def _append_output(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.insert("end", text)
        self._output.see("end")
        self._output.configure(state="disabled")

    def _clear_output(self) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.configure(state="disabled")
        # If the find bar is open, drop its match state — the indices
        # captured for the old buffer are stale now.
        self._find_matches = []
        self._find_cursor = -1
        if getattr(self, "_find_match_var", None) is not None:
            self._find_match_var.set("")

    # ── find-in-output ────────────────────────────────────────────────────────

    _find_matches: list[str] = []  # list of "line.col" start indices
    _find_cursor: int = -1

    def _find_open(self) -> None:
        """Show the find bar above the Output panel and focus its Entry.

        If the panel is currently hidden (Ctrl+`), reveal it first so
        the find bar isn't operating on an invisible widget. Pre-fills
        the entry with the user's current text selection when one
        exists — matches the find-on-selection idiom of every text
        editor since the 90s.
        """
        try:
            self._toggle_output(visible=True)
        except Exception:  # noqa: BLE001 - toggle_output is defensive enough
            pass
        if not self._find_bar.winfo_ismapped():
            self._find_bar.pack(
                fill="x", padx=4, pady=(4, 0),
                before=self._output,
            )
        try:
            seed = self._output.get("sel.first", "sel.last")
        except Exception:  # noqa: BLE001 - no selection is fine
            seed = ""
        if seed and "\n" not in seed:
            self._find_var.set(seed)
        self._find_entry.focus_set()
        self._find_entry.selection_range(0, "end")
        self._refresh_find_matches()

    def _find_close(self) -> None:
        """Hide the find bar and remove every highlight tag."""
        try:
            self._output.tag_remove("find-match", "1.0", "end")
            self._output.tag_remove("find-current", "1.0", "end")
        except Exception:  # noqa: BLE001 - widget race during teardown
            pass
        self._find_matches = []
        self._find_cursor = -1
        if getattr(self, "_find_match_var", None) is not None:
            self._find_match_var.set("")
        if self._find_bar.winfo_ismapped():
            self._find_bar.pack_forget()
        # Return focus to the output panel so the user can keep
        # scrolling with the keyboard.
        try:
            self._output.focus_set()
        except Exception:  # noqa: BLE001
            pass

    def _refresh_find_matches(self) -> None:
        """Re-scan the Output buffer for the current query string.

        Called on every keystroke in the find Entry (via a trace) and
        on Next/Prev so adding output mid-search updates the count.
        """
        query = self._find_var.get()
        try:
            self._output.tag_remove("find-match", "1.0", "end")
            self._output.tag_remove("find-current", "1.0", "end")
        except Exception:  # noqa: BLE001
            pass
        if not query:
            self._find_matches = []
            self._find_cursor = -1
            self._find_match_var.set("")
            return

        # Walk the buffer with Text.search(); each match advances `pos`
        # by the match length to avoid infinite loops on overlapping
        # patterns (the Tk text widget allows them, we don't want them).
        matches: list[str] = []
        pos = "1.0"
        count_var = self.tk.IntVar()
        while True:
            try:
                idx = self._output.search(
                    query, pos, stopindex="end",
                    nocase=1, count=count_var,
                )
            except Exception:  # noqa: BLE001
                break
            if not idx:
                break
            length = count_var.get() or len(query)
            end_idx = f"{idx}+{length}c"
            try:
                self._output.tag_add("find-match", idx, end_idx)
            except Exception:  # noqa: BLE001
                break
            matches.append(idx)
            pos = end_idx

        self._find_matches = matches
        if not matches:
            self._find_cursor = -1
            self._find_match_var.set("0 matches")
            return
        # Re-center on first match (or preserve cursor if it's still valid).
        if self._find_cursor < 0 or self._find_cursor >= len(matches):
            self._find_cursor = 0
        self._highlight_current_match()

    def _highlight_current_match(self) -> None:
        if not self._find_matches:
            return
        try:
            self._output.tag_remove("find-current", "1.0", "end")
        except Exception:  # noqa: BLE001
            return
        idx = self._find_matches[self._find_cursor]
        query = self._find_var.get()
        end_idx = f"{idx}+{len(query)}c"
        try:
            self._output.tag_add("find-current", idx, end_idx)
            self._output.see(idx)
        except Exception:  # noqa: BLE001
            pass
        self._find_match_var.set(
            f"{self._find_cursor + 1} of {len(self._find_matches)}"
        )

    def _find_next(self) -> None:
        if not self._find_matches:
            self._refresh_find_matches()
            if not self._find_matches:
                return
        self._find_cursor = (self._find_cursor + 1) % len(self._find_matches)
        self._highlight_current_match()

    def _find_prev(self) -> None:
        if not self._find_matches:
            self._refresh_find_matches()
            if not self._find_matches:
                return
        self._find_cursor = (self._find_cursor - 1) % len(self._find_matches)
        self._highlight_current_match()

    def _persist_meta_pref(self, key: str, value) -> None:
        """Save a non-destructive GUI preference back into config.json.

        Wraps the load → setattr → save sequence with broad error
        suppression: persistence failure must never disrupt the user's
        workflow. Used by tabs that persist UI state (system pickers,
        non-destructive checkboxes).
        """
        try:
            cfg = load_config()
            setattr(cfg, key, value)
            save_config(cfg)
        except Exception:  # noqa: BLE001 — best-effort save
            pass

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)

    def _flash_validation(self, text: str) -> None:
        """Status-bar variant of `_flash_status` for "click again with X
        filled in" prompts. Adds an audible bell so the user notices
        the bottom-of-window status update even when they're focused
        on a form widget at the top of the window.
        """
        try:
            self.root.bell()
        except Exception:  # noqa: BLE001 — silent terminals are fine
            pass
        self._flash_status(text)

    def _flash_status(self, text: str, *, revert_after_ms: int = 6000) -> None:
        """Show a transient status-bar message that reverts to "Ready." after a few seconds.

        Used in place of `messagebox.showinfo` for routine outcomes
        ("Saved", "Removed", "Up to date") so the user isn't forced to
        click through a dialog for normal happy-path work. Reverts to
        the standard "Ready." idle text after `revert_after_ms` so the
        bar doesn't get stuck on the last operation's name.
        """
        self._set_status(text)
        token = object()
        self._flash_token = token

        def revert():
            # The window may have been destroyed between schedule and
            # fire (cabinet owner closed it inside the 6 s window).
            # `_status_var.set` on a dead StringVar raises TclError;
            # swallow it so the unraisable hook doesn't surface a
            # noise traceback. The `_flash_token` identity check also
            # short-circuits if a newer flash superseded this one.
            if getattr(self, "_flash_token", None) is not token:
                return
            try:
                self._set_status("Ready.")
            except Exception:  # noqa: BLE001 — widget gone, nothing to do
                pass

        try:
            self.root.after(revert_after_ms, revert)
        except Exception:  # noqa: BLE001 — Tk teardown or no main loop
            pass

    def _set_tab_badge(self, idx: int, badge: str) -> None:
        """Stamp the run-progress glyph (⟳/✓/✗) on a tab (main thread only)."""
        if idx < 0 or idx >= len(self._tab_base_names):
            return
        if badge:
            self._tab_run_badges[idx] = badge
        else:
            self._tab_run_badges.pop(idx, None)
        self._render_tab_label(idx)

    def _set_tab_health_badge(self, idx: int, badge: str) -> None:
        """Stamp the area-health glyph (✓/⚠/✗) on a tab.

        Health badges persist across runs (they're driven by the
        startup `doctor` pass, not by command outcomes), so a tab can
        show both a run badge AND a health badge at once — e.g.
        "LEDBlinky ⚠ ⟳" means "the LEDBlinky area has a configuration
        warning, and a command is currently streaming output from
        this tab".
        """
        if idx < 0 or idx >= len(self._tab_base_names):
            return
        if badge:
            self._tab_health_badges[idx] = badge
        else:
            self._tab_health_badges.pop(idx, None)
        self._render_tab_label(idx)

    def _render_tab_label(self, idx: int) -> None:
        """Combine base + health badge + run badge into the tab title."""
        if idx < 0 or idx >= len(self._tab_base_names):
            return
        base = self._tab_base_names[idx]
        health = self._tab_health_badges.get(idx, "")
        run = self._tab_run_badges.get(idx, "")
        # Health sits closer to the base name (semantic state),
        # run sits at the far right (transient activity).
        parts = [base]
        if health:
            parts.append(health)
        if run:
            parts.append(run)
        self._nb.tab(idx, text=" ".join(parts))

    def _fit_geometry(self, win, ideal_w: int, ideal_h: int) -> None:
        """Set dialog geometry capped to the current screen size minus margins.

        Hard-coded pixel values (960x600, 1100x650 …) overflow on arcade
        cabinet monitors at 1024×768. This method uses the real screen
        dimensions so dialogs are always fully on-screen and resizable.

        Also wires Escape → destroy so every Toplevel that calls this
        method (which is all of them in this codebase) can be dismissed
        from the keyboard — previously dialogs only closed via the OS
        window-manager close box.
        """
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(ideal_w, sw - 40)
        h = min(ideal_h, sh - 80)
        win.geometry(f"{w}x{h}")
        try:
            win.bind("<Escape>", lambda _e, _w=win: _w.destroy())
        except Exception:  # noqa: BLE001 - bind() can race during teardown
            pass

    def mainloop(self) -> None:
        self.root.mainloop()


class _DoneMarker:
    """Sentinel pushed onto the line queue when a subprocess exits."""

    __slots__ = ("rc", "callback")

    def __init__(self, rc: int, callback: Optional[Callable[[int], None]]) -> None:
        self.rc = rc
        self.callback = callback


class _RunRecord:
    """One historical command run captured for the Logs tab.

    The Output panel at the bottom of the window shows whichever
    command is *currently* running — useful while watching progress,
    useless for "what did I do an hour ago?". The Logs tab solves
    that by keeping a per-run buffer indexed by start time.

    ``dry_run`` is a three-value flag:
    - ``True``  — dry-run preview (command supports --apply, flag not passed)
    - ``False`` — actual write (--apply was passed)
    - ``None``  — N/A (read-only command; dry-run concept doesn't apply)
    """

    __slots__ = ("started_at", "argv_str", "command_slug", "output", "exit_code", "dry_run")

    def __init__(self, started_at: str, argv_str: str, dry_run: Optional[bool]) -> None:
        self.started_at = started_at
        self.argv_str = argv_str
        self.command_slug: str = ""
        self.output: list[str] = []
        self.exit_code: Optional[int] = None
        self.dry_run = dry_run

    def append(self, text: str) -> None:
        # Per-run buffer is plain str fragments, joined on demand.
        # Keeping fragments rather than a single growing string avoids
        # repeated O(n²) string copies on long-running commands like
        # `audit --all` that emit thousands of lines.
        self.output.append(text)

    def joined_output(self) -> str:
        return "".join(self.output)

    def tag(self) -> str:
        """Short label for the Logs tree's leftmost column."""
        if self.exit_code is None:
            return "running"
        if self.exit_code == 0:
            return "DRY-RUN" if self.dry_run is True else "OK"
        return f"FAIL {self.exit_code}"


def _format_run_log_text(record: "_RunRecord") -> str:
    """Render a run record as the header+output text written to a log file."""
    _dr = ("N/A" if record.dry_run is None
           else ("Yes" if record.dry_run else "No"))
    return (
        f"# Started: {record.started_at}\n"
        f"# Status:  {record.tag()}\n"
        f"# Dry-run: {_dr}\n"
        f"# Command: {record.argv_str}\n\n"
        f"{record.joined_output()}"
    )


def _default_run_log_filename(record: "_RunRecord") -> str:
    """Filesystem-safe default filename for a run record's log file."""
    action = getattr(record, "command_slug", "") or "run"
    safe_action = re.sub(r'[\\/:*?"<>|]', "_", action)[:80]
    return (
        record.started_at.replace(":", "-").replace(" ", "_")
        + "_" + safe_action
        + ".txt"
    )


def _format_argv(argv: Sequence[str]) -> str:
    """Render argv for display in the output panel — quotes spaces, nothing more."""
    parts = []
    for a in argv:
        if any(c.isspace() for c in a):
            parts.append(f'"{a}"')
        else:
            parts.append(a)
    return " ".join(parts)


if __name__ == "__main__":
    sys.exit(main())
