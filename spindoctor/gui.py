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
            var.set(path)

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

    # ── Custom command tab ────────────────────────────────────────────────────

    def _build_custom_tab(self, parent):
        frame = self.ttk.Frame(parent, padding=12)
        self.ttk.Label(
            frame,
            text=("Run any spindoctor sub-command. Type the arguments as "
                  "you would after `spindoctor` on the command line — for "
                  "example `verify --system NES --dat path\\to.dat` or "
                  "`migrate --target E:\\Cab --apply`."),
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        row = self.ttk.Frame(frame)
        row.pack(fill="x", pady=4)
        self.ttk.Label(row, text="spindoctor").pack(side="left")
        self._custom_var = self.tk.StringVar(value="--help")
        entry = self.ttk.Entry(row, textvariable=self._custom_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self._run_custom())
        self.ttk.Button(row, text="Run", command=self._run_custom).pack(side="left")

        return frame

    def _run_custom(self) -> None:
        raw = self._custom_var.get().strip()
        if not raw:
            self.messagebox.showinfo("Nothing to run", "Type some arguments first.")
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
