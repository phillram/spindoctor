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

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        nb = self.ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        nb.add(self._build_setup_tab(nb), text="Setup")
        nb.add(self._build_wheels_tab(nb), text="Wheels")
        nb.add(self._build_audit_tab(nb), text="Audit & Doctor")
        nb.add(self._build_backup_tab(nb), text="Backup & Restore")
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

        return frame

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

        return frame

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
