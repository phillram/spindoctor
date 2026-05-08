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
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import __app_name__, __version__
from .config import (
    CONFIG_DIR, CONFIG_FILE, Config, get_systems, load_config, save_config,
)


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
)


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


# Curated dropdown for the Custom Command tab. Each entry is the argv
# string the user would type after `spindoctor` on the command line, in
# canonical form. Picking one populates the entry field; the user can
# then edit placeholders (<SYSTEM>, <PATH>, ...) before clicking Run.
# Order is roughly "discover → audit → curate → fetch → wheels → admin"
# so the list reads top-to-bottom like a guided tour of the CLI.
_CUSTOM_COMMAND_PRESETS: tuple[str, ...] = (
    "--help",
    "--version",
    # Discovery / health
    "doctor",
    "tools-audit",
    "systems",
    "report",
    "preview",
    # Audit & inspect
    "audit --all",
    "audit --system <SYSTEM>",
    "inspect --system <SYSTEM>",
    "inspect --system <SYSTEM> --all",
    "find-dupes --all",
    "find-dupes --cross-systems",
    "find-misplaced --all",
    "find-orphan-media --all",
    "check-discs --all",
    "verify --system <SYSTEM> --dat <DAT_PATH>",
    "lint",
    "stats",
    # Curate & cleanup
    "curate --all",
    "curate --all --apply",
    "cleanup categories",
    "cleanup audit",
    "cleanup run --apply",
    "ignore list",
    "match list",
    # Metadata & media
    "fetch-meta --all",
    "fetch-media --all",
    "media-scan --all",
    "media-add <SYSTEM> <ROM> --type wheel --source <PATH>",
    "update-db --system <SYSTEM>",
    "generate-config",
    # Wheels (favorites / recent / most-played)
    "fav list",
    "fav rebuild --apply",
    "recent list",
    "recent rebuild --apply",
    "stats-report",
    "stats-report build-wheel --apply",
    # Main Menu (HyperSpin top-level wheel)
    "mainmenu show",
    "mainmenu sort alpha --apply",
    "mainmenu sort manufacturer --apply",
    "mainmenu sort year --apply",
    "mainmenu reorder <SYSTEM> <POSITION> --apply",
    "mainmenu hide <SYSTEM> --apply",
    "mainmenu add <SYSTEM> --apply",
    "mainmenu remove <SYSTEM> --apply",
    "mainmenu edit",
    # LEDBlinky
    "ledblinky generate",
    "ledblinky audit",
    "ledblinky check",
    "ledblinky fix",
    # Lightgun
    "lightgun detect",
    "lightgun audit",
    "lightgun configure",
    # Add / rename / batch edit
    "add-system <SYSTEM>",
    "add-pc-system <SYSTEM>",
    "pc-rename <OLD> <NEW>",
    "rename <SYSTEM> <OLD_ROM> <NEW_ROM> --apply",
    "clone <SYSTEM> <ROM> <NEW_ROM> --apply",
    "batch-edit --system <SYSTEM>",
    "organize --apply",
    "find-global <QUERY>",
    # Backup & migration
    "backup create --target <PATH>",
    "backup create --target <PATH> --apply",
    "backup list --target <PATH>",
    "backup info --backup <PATH>",
    "backup restore --backup <PATH> --apply",
    "migrate --target <PATH>",
    "migrate --target <PATH> --apply",
    "migrate --list-manifests",
    "migrate --undo latest --apply",
    # Config
    "config show",
    "config init",
    "config set <KEY> <VALUE>",
    "config system list",
    "config system set <SYSTEM> --layout wheel",
    # Tools
    "install-tools",
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

    app = _SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
    app.mainloop()
    return 0


class _SpinDoctorGUI:
    """The Tkinter window. Constructed via :func:`main`."""

    def __init__(self, tk_mod, ttk_mod, filedialog_mod, messagebox_mod, scrolledtext_mod):
        self.tk = tk_mod
        self.ttk = ttk_mod
        self.filedialog = filedialog_mod
        self.messagebox = messagebox_mod
        self.scrolledtext = scrolledtext_mod

        self.root = tk_mod.Tk()
        self.root.title(f"{__app_name__} {__version__}")
        self.root.geometry("960x720")
        self.root.minsize(720, 540)

        self._proc: Optional[subprocess.Popen] = None
        self._line_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None

        # Setup-tab field vars; populated in _build_setup_tab().
        self._setup_vars: dict[str, "tk_mod.StringVar"] = {}

        self._build_layout()
        self._refresh_systems()
        self._set_status("Ready.")
        # 50 ms polling is fast enough to feel real-time without busy-looping.
        self.root.after(50, self._drain_queue)
        # Kick off the GitHub release-tag check on a background thread
        # so a slow / unreachable GitHub doesn't delay the first paint.
        # Result lands in the status bar via _on_update_check_done.
        self._start_update_check()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self._build_menubar()
        nb = self.ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        nb.add(self._build_setup_tab(nb), text="Setup")
        nb.add(self._build_wheels_tab(nb), text="Wheels")
        nb.add(self._build_mainmenu_tab(nb), text="Main Menu")
        nb.add(self._build_audit_tab(nb), text="Audit & Doctor")
        nb.add(self._build_diagnose_tab(nb), text="Diagnose")
        nb.add(self._build_ledblinky_tab(nb), text="LEDBlinky")
        nb.add(self._build_lightgun_tab(nb), text="Lightgun")
        nb.add(self._build_tools_tab(nb), text="Tools")
        nb.add(self._build_backup_tab(nb), text="Backup & Restore")
        nb.add(self._build_migrate_tab(nb), text="Migrate")
        nb.add(self._build_custom_tab(nb), text="Custom Command")

        out_frame = self.ttk.LabelFrame(self.root, text="Output")
        out_frame.pack(fill="both", expand=True, padx=8, pady=4)
        mono = "Consolas" if sys.platform == "win32" else "Menlo"
        self._output = self.scrolledtext.ScrolledText(
            out_frame, height=14, wrap="word", font=(mono, 10),
        )
        self._output.configure(state="disabled")
        self._output.pack(fill="both", expand=True, padx=4, pady=4)

        bar = self.ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom", padx=8, pady=(0, 8))
        self._status_var = self.tk.StringVar(value="")
        self.ttk.Label(bar, textvariable=self._status_var, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        self._stop_btn = self.ttk.Button(
            bar, text="Stop", command=self._stop_running, state="disabled"
        )
        self._stop_btn.pack(side="right")
        self.ttk.Button(bar, text="Clear output", command=self._clear_output).pack(
            side="right", padx=(0, 6)
        )

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
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = self.tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About SpinDoctor", command=self._show_about)
        help_menu.add_command(
            label="Check for updates", command=self._manual_update_check,
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

        body = self.ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)

        self.ttk.Label(
            body, text=f"{__app_name__}",
            font=("TkDefaultFont", 14, "bold"),
        ).pack(anchor="w")
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
                # Hop back to the Tk main loop before touching widgets.
                self.root.after(0, self._on_update_check_done, result)

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
        # When the user is up to date, stay quiet — no point cluttering
        # the output panel with an "all good" line on every launch.

    def _manual_update_check(self) -> None:
        """Help → Check for updates: synchronous variant with feedback.

        The launch check runs silently on success, but a manual
        invocation should always tell the user *something* — otherwise
        clicking the menu entry feels broken when the user is up to
        date.
        """
        from . import update_check

        try:
            result = update_check.check_for_update(__version__)
        except update_check.UpdateCheckDisabled as exc:
            self.messagebox.showinfo("Update check disabled", str(exc))
            return
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
            self.messagebox.showinfo(
                "Up to date",
                f"{__app_name__} {result.current} is the latest release.",
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
    _LOG_CATEGORIES: tuple[tuple[str, str], ...] = (
        ("Migrations",     "migrations"),
        ("Curation",       "curation"),
        ("Edits",          "edits"),
        ("Renames",        "renames"),
        ("Media imports",  "media_imports"),
        ("Misplaced ROMs", "misplaced"),
    )

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
        win.geometry("960x600")
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
        paned.add(tree_frame, weight=2)

        # ── Right pane: viewer ───────────────────────────────────────────────
        viewer_frame = self.ttk.Frame(paned)
        mono = "Consolas" if sys.platform == "win32" else "Menlo"
        viewer = self.scrolledtext.ScrolledText(
            viewer_frame, wrap="none", font=(mono, 9),
        )
        viewer.configure(state="disabled")
        viewer.pack(fill="both", expand=True, padx=4, pady=4)
        paned.add(viewer_frame, weight=3)

        # Path → file text. Cached so re-clicking a row doesn't re-read
        # disk; manifests don't change after they're written.
        loaded: dict[str, str] = {}
        # Tree iid → manifest path. Populated below; consulted in the
        # selection handler.
        item_paths: dict[str, Path] = {}

        def populate() -> None:
            tree.delete(*tree.get_children())
            item_paths.clear()
            any_found = False
            for label, dirname in self._LOG_CATEGORIES:
                cat_dir = CONFIG_DIR / dirname
                if not cat_dir.exists():
                    continue
                files = sorted(
                    (p for p in cat_dir.iterdir() if p.is_file()),
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
                for f in files:
                    stat = f.stat()
                    iid = tree.insert(
                        cat_iid, "end", text=f.name,
                        values=(
                            self._format_mtime(stat.st_mtime),
                            self._format_bytes(stat.st_size),
                        ),
                    )
                    item_paths[iid] = f
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
            path = item_paths.get(sel[0])
            if path is None:
                return
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
            btn_row, text="Open in file explorer",
            command=lambda: self._open_selected_manifest_in_explorer(
                tree, item_paths,
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

    def _open_selected_manifest_in_explorer(
        self, tree, item_paths: dict,
    ) -> None:
        sel = tree.selection()
        if not sel:
            return
        path = item_paths.get(sel[0])
        if path is None or not path.exists():
            return
        # Open the *parent* — the file selected handler already showed
        # the contents, so what's useful here is "show me where this
        # lives so I can poke around its siblings".
        self._open_path(path.parent, missing_label=str(path.parent))

    @staticmethod
    def _format_mtime(ts: float) -> str:
        from datetime import datetime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _format_bytes(n: int) -> str:
        # Identical units to backup.format_bytes — kept inline so the
        # viewer doesn't pull in the heavier backup module just for
        # display formatting.
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        intro = self.ttk.Label(
            frame,
            text=("Point SpinDoctor at your library. These map 1:1 to "
                  "`spindoctor config init`. Saves to "
                  f"{CONFIG_FILE}."),
            wraplength=860, justify="left",
        )
        intro.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        cfg = load_config()
        for i, (key, label, win_default, _allow_blank) in enumerate(_SETUP_FIELDS, start=1):
            existing = getattr(cfg, key, "") or ""
            initial = existing or win_default
            var = self.tk.StringVar(value=initial)
            self._setup_vars[key] = var
            self.ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=2)
            self.ttk.Entry(frame, textvariable=var, width=60).grid(
                row=i, column=1, sticky="ew", padx=6, pady=2
            )
            self.ttk.Button(
                frame, text="Browse…",
                command=lambda v=var, k=key: self._browse_dir(v, k),
            ).grid(row=i, column=2, sticky="w", pady=2)

        frame.columnconfigure(1, weight=1)

        btn_row = self.ttk.Frame(frame)
        btn_row.grid(row=len(_SETUP_FIELDS) + 1, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.ttk.Button(btn_row, text="Save configuration", command=self._save_setup).pack(side="left")
        self.ttk.Button(btn_row, text="Run doctor", command=lambda: self._run_cli(
            "spindoctor", ["doctor"]
        )).pack(side="left", padx=6)
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

    def _save_setup(self) -> None:
        cfg = load_config()
        for key, _label, _default, _allow_blank in _SETUP_FIELDS:
            setattr(cfg, key, self._setup_vars[key].get().strip())
        save_config(cfg)
        ok, errors = cfg.is_valid()
        self._append_output(f"Saved {CONFIG_FILE}\n")
        if ok:
            self._append_output("Config validates. Try the Wheels or Audit tabs next.\n")
            self.messagebox.showinfo("Saved", "Configuration saved.")
        else:
            for err in errors:
                self._append_output(f"  ! {err}\n")
            self.messagebox.showwarning(
                "Saved with warnings",
                "Configuration saved, but some required paths still need attention:\n\n"
                + "\n".join(errors),
            )
        # System dropdown depends on roms_dir/hyperspin_dir; refresh it.
        self._refresh_systems()

    # ── Wheels tab ────────────────────────────────────────────────────────────

    def _build_wheels_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Rebuild the cross-system wheels HyperSpin shows on the "
                  "main menu. Each click runs the corresponding standalone "
                  "binary with --apply, the same way the .bat shortcuts do."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        for label, binary, args in (
            ("Refresh Favorites",       "spindoctor-fav",    ["rebuild", "--apply"]),
            ("Refresh Recently Played", "spindoctor-recent", ["rebuild", "--apply"]),
            ("Refresh Most Played",     "spindoctor-stats",  ["build-wheel", "--apply"]),
        ):
            self.ttk.Button(
                frame, text=label, width=28,
                command=lambda b=binary, a=args: self._run_cli(b, a),
            ).pack(anchor="w", pady=3)

        self.ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)
        self.ttk.Button(
            frame, text="Refresh All Three", width=28,
            command=self._refresh_all_wheels,
        ).pack(anchor="w", pady=3)

        # ── HyperSpin integration helpers ────────────────────────────────────
        # The custom wheels (Favorites / Recently Played / Most Played) write
        # synthetic HyperSpin systems with media + per-game PCLauncher INIs,
        # but they don't auto-fire on cabinet startup and only Most Played
        # auto-registers in the Main Menu. The buttons below close those
        # gaps so users don't have to drop into cmd.exe to wire them up.
        self.ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)
        self.ttk.Label(
            frame, text="HyperSpin integration",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(2, 4))
        self.ttk.Label(
            frame,
            text=(
                "• Refresh writes a synthetic HyperSpin system (media + "
                "per-game INIs delegating to the original system via "
                "RocketLauncher).\n"
                "• Most Played auto-registers in the Main Menu wheel; "
                "Favorites and Recently Played do not — use the Main Menu "
                "tab (or the buttons below) to add them.\n"
                "• None of these auto-fire on cabinet startup. Use the "
                "Tools tab to install Tools-menu .bat helpers, or schedule "
                "the rebuild commands via Windows Task Scheduler "
                "(trigger: 'At log on') for hands-off updates."
            ),
            wraplength=860, justify="left", foreground="#444",
        ).pack(anchor="w", pady=(0, 6))

        btn_row = self.ttk.Frame(frame)
        btn_row.pack(anchor="w", pady=(2, 4))
        self.ttk.Button(
            btn_row, text="Add wheels to Main Menu", width=28,
            command=self._register_wheels_in_main_menu,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Install Tools-menu helpers", width=28,
            command=lambda: self._run_cli("spindoctor", ["install-tools"]),
        ).pack(side="left", padx=6)

        return frame

    def _register_wheels_in_main_menu(self) -> None:
        # Each `mainmenu add` runs only after the previous one finishes so
        # the underlying XML write doesn't race with itself. Using `--apply`
        # here matches the user's intent: they clicked the button.
        steps = [
            ("Favorites",        ["mainmenu", "add", "Favorites", "--apply"]),
            ("Recently Played",  ["mainmenu", "add", "Recently Played", "--apply"]),
            ("Most Played",      ["mainmenu", "add", "Most Played", "--apply"]),
        ]

        def run_next(remaining, rc: int) -> None:
            if rc != 0:
                self._append_output(
                    f"\nStopped — previous step exited with code {rc}.\n"
                )
                return
            if not remaining:
                self._append_output("\nWheels registered in Main Menu.\n")
                return
            _label, args = remaining[0]
            self._run_cli(
                "spindoctor", args,
                on_complete=lambda code: run_next(remaining[1:], code),
            )

        run_next(steps, 0)

    def _refresh_all_wheels(self) -> None:
        # Chained via a callback queue so each subprocess runs to completion
        # before the next starts and they share the output panel cleanly.
        steps: list[tuple[str, list[str]]] = [
            ("spindoctor-fav",    ["rebuild", "--apply"]),
            ("spindoctor-recent", ["rebuild", "--apply"]),
            ("spindoctor-stats",  ["build-wheel", "--apply"]),
        ]

        def run_next(remaining: list[tuple[str, list[str]]], rc: int) -> None:
            if rc != 0:
                self._append_output(f"\nStopped — previous step exited with code {rc}.\n")
                return
            if not remaining:
                self._append_output("\nAll wheels refreshed.\n")
                return
            binary, args = remaining[0]
            self._run_cli(binary, args, on_complete=lambda code: run_next(remaining[1:], code))

        run_next(steps, 0)

    # ── Audit & Doctor tab ────────────────────────────────────────────────────

    def _build_audit_tab(self, parent):
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
        self.ttk.Button(frame, text="Reload list", command=self._refresh_systems).grid(
            row=1, column=2, sticky="w"
        )

        btn_row = self.ttk.Frame(frame)
        btn_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=12)
        self.ttk.Button(btn_row, text="Audit selected system",
                        command=self._run_audit).pack(side="left")
        self.ttk.Button(btn_row, text="Audit all systems",
                        command=lambda: self._run_cli("spindoctor", ["audit", "--all"])
                        ).pack(side="left", padx=6)
        self.ttk.Button(btn_row, text="Run doctor",
                        command=lambda: self._run_cli("spindoctor", ["doctor"])
                        ).pack(side="left", padx=6)
        self.ttk.Button(btn_row, text="Tools audit",
                        command=lambda: self._run_cli("spindoctor", ["tools-audit"])
                        ).pack(side="left", padx=6)

        # Browse buttons — when an audit reports "wrong wheel" or
        # "missing video", jumping to the relevant folder in Explorer
        # is faster than copy-pasting the path. Picks the system from
        # the dropdown above so they always agree on what's selected.
        browse_row = self.ttk.Frame(frame)
        browse_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.ttk.Label(
            browse_row, text="Browse on disk:",
            foreground="#666",
        ).pack(side="left")
        self.ttk.Button(
            browse_row, text="Open Media folder for selected system",
            command=self._open_audit_media_folder,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            browse_row, text="Open ROMs folder for selected system",
            command=self._open_audit_roms_folder,
        ).pack(side="left", padx=6)

        return frame

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

    def _refresh_systems(self) -> None:
        try:
            systems = get_systems(load_config())
        except Exception as exc:  # noqa: BLE001 — surface any config error to UI
            systems = []
            self._set_status(f"Could not list systems: {exc}")
        # Combobox may not exist yet during __init__'s first call.
        combo = getattr(self, "_system_combo", None)
        if combo is None:
            return
        combo["values"] = systems
        if systems and not self._system_var.get():
            self._system_var.set(systems[0])

    def _run_audit(self) -> None:
        system = self._system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "No system selected",
                "Pick a system from the dropdown (or click Reload list "
                "after configuring paths in the Setup tab).",
            )
            return
        self._run_cli("spindoctor", ["audit", "--system", system])

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

        # ── Target folder (shared by Create / List) ──────────────────────────
        self.ttk.Label(frame, text="Target folder").grid(
            row=1, column=0, sticky="w", pady=2,
        )
        self._backup_target_var = self.tk.StringVar()
        self.ttk.Entry(frame, textvariable=self._backup_target_var, width=60).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=2,
        )
        self.ttk.Button(
            frame, text="Browse…",
            command=lambda: self._browse_backup_dir(self._backup_target_var,
                                                   "Pick backup target folder"),
        ).grid(row=1, column=3, sticky="w", pady=2)

        # ── Components (shared by Create / Restore) ──────────────────────────
        comp_frame = self.ttk.LabelFrame(frame, text="Components")
        comp_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        # Default to "everything" so a click-and-go user gets a full backup.
        # Cabinet owners who want a partial backup can untick.
        self._backup_component_vars: dict[str, "self.tk.BooleanVar"] = {}
        for i, (key, desc) in enumerate(_BACKUP_COMPONENTS):
            var = self.tk.BooleanVar(value=True)
            self._backup_component_vars[key] = var
            self.ttk.Checkbutton(
                comp_frame, text=f"{key}  —  {desc}", variable=var,
            ).grid(row=i, column=0, sticky="w", padx=6, pady=1)

        # ── Create section ───────────────────────────────────────────────────
        create_frame = self.ttk.LabelFrame(frame, text="Create backup")
        create_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        create_frame.columnconfigure(1, weight=1)

        self.ttk.Label(create_frame, text="Label (optional)").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._backup_label_var = self.tk.StringVar()
        self.ttk.Entry(create_frame, textvariable=self._backup_label_var, width=30).grid(
            row=0, column=1, sticky="w", padx=6, pady=2,
        )

        self._backup_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            create_frame, text="Apply (uncheck for dry-run)",
            variable=self._backup_apply_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self.ttk.Button(
            create_frame, text="Create backup",
            command=self._run_backup_create,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

        # ── List section ─────────────────────────────────────────────────────
        list_frame = self.ttk.LabelFrame(frame, text="List backups")
        list_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        self.ttk.Button(
            list_frame, text="List backups under target",
            command=self._run_backup_list,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)

        # ── Restore section ──────────────────────────────────────────────────
        restore_frame = self.ttk.LabelFrame(frame, text="Restore from a backup")
        restore_frame.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        restore_frame.columnconfigure(1, weight=1)

        self.ttk.Label(restore_frame, text="Backup folder").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._backup_restore_path_var = self.tk.StringVar()
        self.ttk.Entry(
            restore_frame, textvariable=self._backup_restore_path_var, width=50,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self.ttk.Button(
            restore_frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._backup_restore_path_var, "Pick backup folder to restore",
            ),
        ).grid(row=0, column=2, sticky="w", padx=6, pady=2)

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

        self._backup_restore_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            restore_frame, text="Apply (uncheck for dry-run)",
            variable=self._backup_restore_apply_var,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        btn_row = self.ttk.Frame(restore_frame)
        btn_row.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            btn_row, text="Show backup info",
            command=self._run_backup_info,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Restore backup",
            command=self._run_backup_restore,
        ).pack(side="left", padx=6)

        frame.columnconfigure(1, weight=1)
        return frame

    def _browse_backup_dir(self, var, title: str) -> None:
        path = self.filedialog.askdirectory(
            title=title, initialdir=var.get() or str(Path.home()),
        )
        if path:
            # Match the Setup tab: keep separators native to the OS so
            # paths copy-pasted into a Windows shell don't trip on
            # forward slashes.
            var.set(str(Path(path)))

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
        if self._backup_apply_var.get():
            args.append("--apply")
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
        args = ["backup", "restore", "--backup", backup_path]
        if include is not None:
            args += ["--include", include]
        if self._backup_use_current_var.get():
            args.append("--use-current-paths")
        if self._backup_overwrite_var.get():
            args.append("--overwrite")
        if self._backup_restore_apply_var.get():
            args.append("--apply")
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

        # ── Target root ──────────────────────────────────────────────────────
        self.ttk.Label(frame, text="Target root").grid(
            row=1, column=0, sticky="w", pady=2,
        )
        self._migrate_target_var = self.tk.StringVar()
        self.ttk.Entry(frame, textvariable=self._migrate_target_var, width=60).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=2,
        )
        self.ttk.Button(
            frame, text="Browse…",
            command=lambda: self._browse_backup_dir(
                self._migrate_target_var, "Pick migration target root",
            ),
        ).grid(row=1, column=3, sticky="w", pady=2)

        # ── Components ───────────────────────────────────────────────────────
        comp_frame = self.ttk.LabelFrame(frame, text="Components")
        comp_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        self._migrate_component_vars: dict = {}
        for i, (key, desc) in enumerate(_MIGRATE_COMPONENTS):
            var = self.tk.BooleanVar(value=True)
            self._migrate_component_vars[key] = var
            self.ttk.Checkbutton(
                comp_frame, text=f"{key}  —  {desc}", variable=var,
            ).grid(row=i, column=0, sticky="w", padx=6, pady=1)

        # ── Options ──────────────────────────────────────────────────────────
        opt_frame = self.ttk.LabelFrame(frame, text="Options")
        opt_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        opt_frame.columnconfigure(1, weight=1)

        self.ttk.Label(opt_frame, text="Systems filter (optional)").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._migrate_systems_var = self.tk.StringVar()
        self.ttk.Entry(
            opt_frame, textvariable=self._migrate_systems_var, width=40,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            opt_frame,
            text="Comma-separated. Only applies to the roms component.",
            foreground="#666",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6)

        self._migrate_keep_source_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            opt_frame, text="Copy instead of move (--keep-source)",
            variable=self._migrate_keep_source_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self._migrate_verify_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            opt_frame,
            text="SHA1-verify after copy (--verify; only with Copy)",
            variable=self._migrate_verify_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self._migrate_no_update_config_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            opt_frame,
            text="Don't rewrite config.json with new paths "
                 "(--no-update-config)",
            variable=self._migrate_no_update_config_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self._migrate_preserve_names_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            opt_frame,
            text="Keep original folder names (--preserve-names)",
            variable=self._migrate_preserve_names_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self._migrate_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            opt_frame, text="Apply (uncheck for dry-run)",
            variable=self._migrate_apply_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self.ttk.Button(
            opt_frame, text="Run migration", command=self._run_migrate,
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

        # ── Undo / list manifests ────────────────────────────────────────────
        undo_frame = self.ttk.LabelFrame(frame, text="Undo a previous migration")
        undo_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        undo_frame.columnconfigure(1, weight=1)

        self.ttk.Label(undo_frame, text="Manifest").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._migrate_undo_var = self.tk.StringVar(value="latest")
        self.ttk.Entry(
            undo_frame, textvariable=self._migrate_undo_var, width=40,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            undo_frame,
            text="'latest' to undo the most recent migration, or a path "
                 "under ~/.spindoctor/migrations/.",
            foreground="#666",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6)

        self._migrate_undo_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            undo_frame, text="Apply (uncheck for dry-run)",
            variable=self._migrate_undo_apply_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        btn_row = self.ttk.Frame(undo_frame)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))
        self.ttk.Button(
            btn_row, text="List manifests",
            command=lambda: self._run_cli(
                "spindoctor", ["migrate", "--list-manifests"],
            ),
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Undo", command=self._run_migrate_undo,
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
        systems = self._migrate_systems_var.get().strip()
        if systems:
            args += ["--systems", systems]
        if self._migrate_keep_source_var.get():
            args.append("--keep-source")
        if self._migrate_verify_var.get():
            args.append("--verify")
        if self._migrate_no_update_config_var.get():
            args.append("--no-update-config")
        if self._migrate_preserve_names_var.get():
            args.append("--preserve-names")
        if self._migrate_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_migrate_undo(self) -> None:
        manifest = self._migrate_undo_var.get().strip()
        if not manifest:
            self.messagebox.showwarning(
                "Manifest required",
                "Type 'latest' or paste a manifest path before running Undo.",
            )
            return
        args = ["migrate", "--undo", manifest]
        if self._migrate_undo_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    # ── Main Menu tab ─────────────────────────────────────────────────────────

    def _build_mainmenu_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Reorder, hide, or sort the systems on HyperSpin's "
                  "top-level wheel (Main Menu.xml). Click Show to render "
                  "the current order in the output panel; pick a system "
                  "and use Move up / Move down / Hide to nudge it. Sort "
                  "rewrites the whole wheel alphabetically, by "
                  "manufacturer, or by year. Every action is dry-run "
                  "unless you tick Apply."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        self._mainmenu_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            frame, text="Apply (uncheck for dry-run)",
            variable=self._mainmenu_apply_var,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 6))

        # ── Show / Sort (don't need a system pick) ───────────────────────────
        view_frame = self.ttk.LabelFrame(frame, text="View / Sort")
        view_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 4))

        self.ttk.Button(
            view_frame, text="Show current order",
            command=lambda: self._run_cli("spindoctor", ["mainmenu", "show"]),
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)

        self.ttk.Label(view_frame, text="Sort strategy").grid(
            row=0, column=1, sticky="e", padx=(20, 4),
        )
        self._mainmenu_sort_var = self.tk.StringVar(value="alpha")
        self.ttk.Combobox(
            view_frame, textvariable=self._mainmenu_sort_var,
            values=["alpha", "manufacturer", "year"],
            state="readonly", width=14,
        ).grid(row=0, column=2, sticky="w", padx=4)
        self.ttk.Button(
            view_frame, text="Sort", command=self._run_mainmenu_sort,
        ).grid(row=0, column=3, sticky="w", padx=4)

        # ── System-targeted actions ──────────────────────────────────────────
        sys_frame = self.ttk.LabelFrame(
            frame, text="System actions (move, hide/show, add, remove)",
        )
        sys_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        sys_frame.columnconfigure(1, weight=1)

        self.ttk.Label(sys_frame, text="System").grid(
            row=0, column=0, sticky="w", padx=6, pady=4,
        )
        self._mainmenu_system_var = self.tk.StringVar()
        self.ttk.Entry(
            sys_frame, textvariable=self._mainmenu_system_var, width=40,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        self.ttk.Label(sys_frame, text="Position (for Reorder)").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._mainmenu_position_var = self.tk.StringVar()
        self.ttk.Entry(
            sys_frame, textvariable=self._mainmenu_position_var, width=10,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        action_row = self.ttk.Frame(sys_frame)
        action_row.grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))
        for label, sub in (
            ("Move up",   "up"),
            ("Move down", "down"),
            ("Reorder",   "reorder"),
            ("Hide",      "hide"),
            ("Show",      "show"),
            ("Add",       "add"),
            ("Remove",    "remove"),
        ):
            self.ttk.Button(
                action_row, text=label,
                command=lambda s=sub: self._run_mainmenu_action(s),
            ).pack(side="left", padx=2)

        frame.columnconfigure(1, weight=1)
        return frame

    def _run_mainmenu_sort(self) -> None:
        strategy = self._mainmenu_sort_var.get()
        args = ["mainmenu", "sort", strategy]
        if self._mainmenu_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_mainmenu_action(self, sub: str) -> None:
        system = self._mainmenu_system_var.get().strip()
        if not system:
            self.messagebox.showwarning(
                "System required",
                "Type a system name (or its 1-based index from Show) "
                "before clicking a Main Menu action.",
            )
            return
        args = ["mainmenu", sub, system]
        if sub == "reorder":
            position = self._mainmenu_position_var.get().strip()
            if not position.isdigit():
                self.messagebox.showwarning(
                    "Position required",
                    "Reorder needs a 1-based position (an integer).",
                )
                return
            args.append(position)
        if self._mainmenu_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    # ── Diagnose tab ──────────────────────────────────────────────────────────

    def _build_diagnose_tab(self, parent):
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
        for i, (label, args) in enumerate(rows):
            r, c = divmod(i, 2)
            self.ttk.Button(
                grid, text=label, width=32,
                command=lambda a=args: self._run_cli("spindoctor", a),
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
            foreground="#444",
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
        self.ttk.Entry(
            verify_row, textvariable=self._verify_system_var, width=24,
        ).pack(side="left", padx=6)
        self.ttk.Label(verify_row, text="DAT path").pack(side="left", padx=(8, 0))
        self._verify_dat_var = self.tk.StringVar()
        self.ttk.Entry(
            verify_row, textvariable=self._verify_dat_var,
        ).pack(side="left", fill="x", expand=True, padx=6)
        self.ttk.Button(
            verify_row, text="Browse…",
            command=self._browse_verify_dat,
        ).pack(side="left")
        self.ttk.Button(
            verify_row, text="Verify",
            command=self._run_verify,
        ).pack(side="left", padx=6)

        return frame

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

    # ── LEDBlinky tab ─────────────────────────────────────────────────────────

    def _build_ledblinky_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Generate and audit LEDBlinky controls.ini / colors.ini "
                  "from MAME's -listxml output. Generate is dry-run by "
                  "default and preserves community-maintained entries; "
                  "tick Overwrite if you want to replace them."),
            wraplength=860, justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        self.ttk.Label(frame, text="System").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._led_system_var = self.tk.StringVar(value="MAME")
        self.ttk.Entry(
            frame, textvariable=self._led_system_var, width=24,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        self._led_overwrite_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            frame, text="Overwrite existing entries (--overwrite)",
            variable=self._led_overwrite_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        self._led_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            frame, text="Apply (uncheck for dry-run)",
            variable=self._led_apply_var,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        btn_row = self.ttk.Frame(frame)
        btn_row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 4))
        self.ttk.Button(
            btn_row, text="Generate (controls + colors)",
            command=self._run_led_generate,
        ).pack(side="left")
        self.ttk.Button(
            btn_row, text="Audit coverage",
            command=self._run_led_audit,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Check existing INIs",
            command=lambda: self._run_cli(
                "spindoctor", ["ledblinky", "check"],
            ),
        ).pack(side="left", padx=6)
        self.ttk.Button(
            btn_row, text="Fix INI issues",
            command=self._run_led_fix,
        ).pack(side="left", padx=6)

        self.ttk.Label(
            frame,
            text=("Tip: configure ledblinky_dir in the Setup tab if your "
                  "LEDBlinky install isn't at the default location. The "
                  "Backup tab can snapshot the LEDBlinky install before "
                  "you run Generate with --overwrite."),
            wraplength=860, justify="left", foreground="#666",
        ).grid(row=5, column=0, columnspan=4, sticky="w", padx=6, pady=(10, 0))

        return frame

    def _run_led_generate(self) -> None:
        system = self._led_system_var.get().strip() or "MAME"
        args = ["ledblinky", "generate", "--system", system]
        if self._led_overwrite_var.get():
            args.append("--overwrite")
        if self._led_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    def _run_led_audit(self) -> None:
        system = self._led_system_var.get().strip() or "MAME"
        self._run_cli(
            "spindoctor", ["ledblinky", "audit", "--system", system],
        )

    def _run_led_fix(self) -> None:
        # `ledblinky fix` is a writer; it respects --apply, so we forward
        # the same Apply checkbox the Generate path uses.
        args = ["ledblinky", "fix"]
        if self._led_apply_var.get():
            args.append("--apply")
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

        # ── Detect / Audit ───────────────────────────────────────────────────
        det_frame = self.ttk.LabelFrame(frame, text="Detect & audit")
        det_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 4))

        self._lg_detect_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            det_frame,
            text="Persist detected systems into config (--apply)",
            variable=self._lg_detect_apply_var,
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=2)

        btn_row = self.ttk.Frame(det_frame)
        btn_row.grid(row=1, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 6))
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

        # ── Configure one system ─────────────────────────────────────────────
        cfg_frame = self.ttk.LabelFrame(
            frame, text="Configure one system",
        )
        cfg_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        cfg_frame.columnconfigure(1, weight=1)

        self.ttk.Label(cfg_frame, text="System").grid(
            row=0, column=0, sticky="w", padx=6, pady=2,
        )
        self._lg_system_var = self.tk.StringVar()
        self.ttk.Entry(
            cfg_frame, textvariable=self._lg_system_var, width=30,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=2)

        self.ttk.Label(cfg_frame, text="Target (optional)").grid(
            row=1, column=0, sticky="w", padx=6, pady=2,
        )
        self._lg_target_var = self.tk.StringVar()
        self.ttk.Entry(
            cfg_frame, textvariable=self._lg_target_var, width=30,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=2)
        self.ttk.Label(
            cfg_frame,
            text="DemulShooter -target value. Auto-detected for known systems.",
            foreground="#666",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        self.ttk.Label(cfg_frame, text="Extra args (optional)").grid(
            row=3, column=0, sticky="w", padx=6, pady=2,
        )
        self._lg_extra_args_var = self.tk.StringVar()
        self.ttk.Entry(
            cfg_frame, textvariable=self._lg_extra_args_var, width=30,
        ).grid(row=3, column=1, sticky="w", padx=6, pady=2)

        self._lg_configure_apply_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(
            cfg_frame, text="Apply (uncheck for dry-run)",
            variable=self._lg_configure_apply_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        self.ttk.Button(
            cfg_frame, text="Configure system",
            command=self._run_lg_configure,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

        return frame

    def _run_lg_detect(self) -> None:
        args = ["lightgun", "detect"]
        if self._lg_detect_apply_var.get():
            args.append("--apply")
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
        if self._lg_configure_apply_var.get():
            args.append("--apply")
        self._run_cli("spindoctor", args)

    # ── Tools tab (HyperSpin Tools-menu helpers + install-tools) ─────────────

    def _build_tools_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Install .bat helpers so Favorites / Recently Played / "
                  "Most Played can be refreshed from inside HyperSpin "
                  "without dropping to a console — either via HyperHQ → "
                  "Tools (the default), or as 'games' inside an existing "
                  "wheel system like 'Toolkit' (the second section)."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        self.ttk.Label(
            frame,
            text=(
                "Helpers written:\n"
                "  • Refresh Favorites.bat        → spindoctor-fav rebuild --apply\n"
                "  • Refresh Recently Played.bat  → spindoctor-recent rebuild --apply\n"
                "  • Refresh Most Played.bat      → spindoctor-stats build-wheel --apply\n"
                "  • Refresh Both.bat             → all three in sequence"
            ),
            justify="left", foreground="#444",
            font=("Consolas" if sys.platform == "win32" else "Menlo", 9),
        ).pack(anchor="w", pady=(0, 8))

        # ── HyperHQ → Tools install (default) ─────────────────────────────────
        hhq_frame = self.ttk.LabelFrame(
            frame, text="Install for HyperHQ → Tools menu",
        )
        hhq_frame.pack(fill="x", pady=(2, 8))
        self.ttk.Label(
            hhq_frame,
            text=("Output directory (optional). Defaults to "
                  "<rocketlauncher_dir>/Modules/HyperLaunch/Tools/spindoctor "
                  "if blank. After installing, register the .bat files in "
                  "HyperHQ → Tools tab so they show up in the in-cabinet "
                  "Tools menu."),
            wraplength=860, justify="left", foreground="#666",
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

        # ── Wheel-integration mode (e.g. user's 'Toolkit' wheel) ──────────────
        wheel_frame = self.ttk.LabelFrame(
            frame, text="Install into an existing wheel system",
        )
        wheel_frame.pack(fill="x", pady=(2, 8))
        self.ttk.Label(
            wheel_frame,
            text=("Adds matching <game> entries to the named system's "
                  "database XML and writes per-game PCLauncher INIs "
                  "alongside the bats. Use this if you have a 'Toolkit' "
                  "or 'Tools' wheel (a HyperSpin system whose 'games' "
                  "are maintenance tasks). The system must already exist "
                  "under <hyperspin_dir>/Databases/<NAME>/<NAME>.xml and "
                  "use PCLauncher as its emulator."),
            wraplength=860, justify="left", foreground="#666",
        ).pack(anchor="w", padx=6, pady=(2, 4))

        sys_row = self.ttk.Frame(wheel_frame)
        sys_row.pack(fill="x", padx=6, pady=2)
        self.ttk.Label(sys_row, text="Target wheel system").pack(side="left")
        self._tools_wheel_var = self.tk.StringVar(value="Toolkit")
        self.ttk.Entry(
            sys_row, textvariable=self._tools_wheel_var, width=30,
        ).pack(side="left", padx=6)
        self.ttk.Button(
            sys_row, text="Install into wheel",
            command=self._run_install_tools_into_wheel,
        ).pack(side="left", padx=6)

        # ── Auto-refresh on cabinet startup ───────────────────────────────────
        sched_frame = self.ttk.LabelFrame(
            frame, text="Auto-refresh on cabinet startup",
        )
        sched_frame.pack(fill="x", pady=(2, 8))
        if sys.platform == "win32":
            self.ttk.Label(
                sched_frame,
                text=("Schedule a Windows Task Scheduler 'At log on' task "
                      "that runs Refresh Both at every cabinet startup. "
                      "The task runs as the current user with limited "
                      "privileges (no UAC prompt). Optional delay lets "
                      "HyperSpin / RocketLauncher settle before the "
                      "rebuild kicks in."),
                wraplength=860, justify="left", foreground="#666",
            ).pack(anchor="w", padx=6, pady=(2, 4))

            delay_row = self.ttk.Frame(sched_frame)
            delay_row.pack(fill="x", padx=6, pady=2)
            self.ttk.Label(delay_row, text="Delay after log-on (minutes)").pack(
                side="left",
            )
            self._tools_delay_var = self.tk.StringVar(value="2")
            self.ttk.Entry(
                delay_row, textvariable=self._tools_delay_var, width=6,
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
                wraplength=860, justify="left", foreground="#666",
            ).pack(anchor="w", padx=6, pady=(2, 6))

        # ── Manual fallback instructions ──────────────────────────────────────
        manual_frame = self.ttk.LabelFrame(
            frame, text="Manual setup (if you'd rather do it yourself)",
        )
        manual_frame.pack(fill="x", pady=(2, 8))
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
                "  1. Win+R → 'taskschd.msc'.\n"
                "  2. Action → Create Task… name: 'SpinDoctor Refresh Wheels'.\n"
                "  3. Triggers → New → Begin: 'At log on' → Delay: 2 minutes.\n"
                "  4. Actions → New → Program: cmd.exe → Args:\n"
                "     /c spindoctor-fav rebuild --apply ^&^& "
                "spindoctor-recent rebuild --apply ^&^& "
                "spindoctor-stats build-wheel --apply\n"
                "  5. Settings → uncheck 'Stop the task if it runs longer than'."
            ),
            justify="left", foreground="#444",
            font=("Consolas" if sys.platform == "win32" else "Menlo", 9),
        ).pack(anchor="w", padx=6, pady=(2, 6))

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

    # ── Auto-refresh on startup (Windows Task Scheduler) ──────────────────────

    def _autorefresh_command(self) -> str:
        # Run all three rebuilds in sequence via cmd.exe so a failing
        # earlier rebuild doesn't kill the rest. `&&` would short-circuit;
        # `&` runs unconditionally so a flaky favorites build still lets
        # recent/most-played update.
        return (
            'cmd.exe /c '
            '"spindoctor-fav rebuild --apply & '
            'spindoctor-recent rebuild --apply & '
            'spindoctor-stats build-wheel --apply"'
        )

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
        try:
            delay = self._parse_delay_minutes()
            if delay == -1:
                return
            result = autostart.create_logon_task(
                self._autorefresh_command(),
                delay_minutes=delay,
            )
        except autostart.NotSupportedError as exc:
            self.messagebox.showinfo("Not supported on this OS", str(exc))
            return
        except (ValueError, RuntimeError) as exc:
            self.messagebox.showerror("Could not schedule task", str(exc))
            return
        self._append_output(
            f"\n[Task Scheduler] created '{result.name}' → "
            f"{result.command}\n{result.output}\n"
        )
        self.messagebox.showinfo(
            "Scheduled",
            f"Auto-refresh task '{result.name}' is registered. "
            "Reboot or log out and back in to test it; the GUI's Output "
            "panel shows the schtasks message above.",
        )

    def _remove_autorefresh(self) -> None:
        from . import autostart
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
        self._append_output(f"\n[Task Scheduler] removed task.\n{output}\n")
        self.messagebox.showinfo("Removed", "Auto-refresh task deleted.")

    def _check_autorefresh(self) -> None:
        from . import autostart
        try:
            exists = autostart.task_exists()
        except autostart.NotSupportedError as exc:
            self.messagebox.showinfo("Not supported on this OS", str(exc))
            return
        msg = (
            f"Task '{autostart.DEFAULT_LOGON_TASK}' is "
            f"{'REGISTERED' if exists else 'not registered'}."
        )
        self._append_output(f"\n[Task Scheduler] {msg}\n")
        self.messagebox.showinfo("Auto-refresh status", msg)

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
        combo = self.ttk.Combobox(
            row,
            textvariable=self._custom_var,
            values=list(_CUSTOM_COMMAND_PRESETS),
            state="normal",
        )
        combo.pack(side="left", fill="x", expand=True, padx=6)
        combo.bind("<Return>", lambda _e: self._run_custom())
        self.ttk.Button(row, text="Run", command=self._run_custom).pack(side="left")

        hint = self.ttk.Label(
            frame,
            text=("Tip: anything in <ANGLE_BRACKETS> is a placeholder you "
                  "need to replace before running. Append --help to any "
                  "command to see its full option list in the Output panel."),
            wraplength=860, justify="left", foreground="#666",
        )
        hint.pack(anchor="w", pady=(8, 0))

        return frame

    def _run_custom(self) -> None:
        raw = self._custom_var.get().strip()
        if not raw:
            self.messagebox.showinfo("Nothing to run", "Type some arguments first.")
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
            self.messagebox.showerror("Couldn't parse arguments", str(exc))
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
            self.messagebox.showerror("Binary not found", str(exc))
            return

        self._append_output(f"\n$ {_format_argv(argv)}\n")
        self._set_status(f"Running: {binary} {' '.join(args)}")
        self._stop_btn.configure(state="normal")

        # Force unbuffered output from the child so progress bars / per-row
        # status lines arrive in real time. PyInstaller-frozen Click apps
        # otherwise buffer aggressively when stdout isn't a tty.
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        try:
            self._proc = subprocess.Popen(
                argv,
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
            self.messagebox.showerror("Could not launch", f"{argv[0]}: {exc}")
            self._stop_btn.configure(state="disabled")
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
        assert proc.stdout is not None
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
        try:
            while True:
                item = self._line_queue.get_nowait()
                if isinstance(item, _DoneMarker):
                    self._on_proc_done(item)
                else:
                    self._append_output(item)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_queue)

    def _on_proc_done(self, marker: "_DoneMarker") -> None:
        self._proc = None
        self._stop_btn.configure(state="disabled")
        self._set_status(
            "Ready." if marker.rc == 0 else f"Last command exited with code {marker.rc}."
        )
        if marker.callback is not None:
            try:
                marker.callback(marker.rc)
            except Exception as exc:  # noqa: BLE001 — never let a callback crash the UI
                self._append_output(f"\n[callback error: {exc}]\n")

    def _stop_running(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            self._proc.terminate()
        except OSError:
            pass
        self._set_status("Stopping…")

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

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)

    def mainloop(self) -> None:
        self.root.mainloop()


class _DoneMarker:
    """Sentinel pushed onto the line queue when a subprocess exits."""

    __slots__ = ("rc", "callback")

    def __init__(self, rc: int, callback: Optional[Callable[[int], None]]) -> None:
        self.rc = rc
        self.callback = callback


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
