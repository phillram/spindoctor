"""Capture the real GUI with synthetic data, never the user's cabinet.

Authoring tool only: Windows 10+, Python 3.10+, Pillow 11.2.1+ and an installed
source checkout are required. Run from a fresh Python process. No scraper,
hardware, scheduled-task modification or Apply command is invoked.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from unittest.mock import patch
from xml.sax.saxutils import escape


def _prepare_sample(root: Path) -> None:
    """Create original sample titles and empty folders, not real ROMs."""
    from spindoctor.config import Config, save_config

    cabinet = Path("ExampleCabinet")
    systems = ("MAME", "Nintendo Entertainment System", "PC Games")
    titles = ("Orbit Runner", "Pixel Rally", "Sample Quest")
    for folder in ("HyperSpin", "ROMs", "Emulators", "RocketLauncher",
                   "LEDBlinky", "Output", "Backups", "Intros", "AuditExports", "Temp"):
        (cabinet / folder).mkdir(parents=True, exist_ok=True)
    database = cabinet / "HyperSpin" / "Databases"
    (database / "Main Menu").mkdir(parents=True)
    menu = "".join(
        '<game name="{}"><description>{}</description></game>'.format(
            escape(system), escape(system),
        ) for system in systems
    )
    (database / "Main Menu" / "Main Menu.xml").write_text(
        "<menu>{}</menu>".format(menu), encoding="utf-8",
    )
    for system in systems:
        (database / system).mkdir()
        (cabinet / "ROMs" / system).mkdir()
        games = "".join(
            '<game name="{0}"><description>{0}</description><year>2026</year>'
            "<manufacturer>Example Studio</manufacturer><genre>Sample</genre>"
            "</game>".format(escape(title)) for title in titles
        )
        (database / system / (system + ".xml")).write_text(
            "<menu>{}</menu>".format(games), encoding="utf-8",
        )
        (cabinet / "HyperSpin" / "Media" / system).mkdir(parents=True)
    for title in titles:
        (cabinet / "ROMs" / "PC Games" / title).mkdir()
    cfg = Config(
        roms_dir=str(cabinet / "ROMs"),
        hyperspin_dir=str(cabinet / "HyperSpin"),
        emulators_dir=str(cabinet / "Emulators"),
        rocketlauncher_dir=str(cabinet / "RocketLauncher"),
        ledblinky_dir=str(cabinet / "LEDBlinky"),
        mame_executable=str(cabinet / "Emulators" / "MAME" / "mame.exe"),
        output_dir=str(cabinet / "Output"),
        backup_dir=str(cabinet / "Backups"),
        auto_audit_export_dir=str(cabinet / "AuditExports"),
        atomic_tmp_dir=str(cabinet / "Temp"),
        intro_randomizer_dir=str(cabinet / "Intros"),
        intro_video_target=str(cabinet / "HyperSpin" / "Media" / "Frontend" / "Intro.mp4"),
        screenscraper_devid="",
        screenscraper_devpassword="",
        ui_scale=1.25,
        output_visible=False,
        gui_window_geometry="1680x1080+40+40",
    )
    save_config(cfg)
    assert Path.home() == root


def _pump(root, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)


def _capture(output: Path) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    from PIL import ImageGrab
    from spindoctor import __version__, gui

    def unexpected_dialog(title, message, **kwargs):
        raise RuntimeError("Unexpected GUI dialog: {}: {}".format(title, message))

    def sample_cli(name):
        return [sys.executable, "-m", gui._DEV_MODULE_MAP[name]]

    real_format_argv = gui._format_argv

    def display_argv(argv):
        # Execute the real interpreter, but keep the developer's absolute
        # interpreter path out of the displayed command.
        argv = list(argv)
        if argv and argv[0] == sys.executable:
            argv[0] = "python"
        return real_format_argv(argv)

    # Avoid network checks and querying the real cabinet's scheduled tasks.
    # The task fixture represents a sample cabinet with no auto-run installed.
    with patch.object(gui._SpinDoctorGUI, "_start_update_check"), \
            patch.object(gui, "resolve_cli_command", sample_cli), \
            patch.object(gui, "_format_argv", display_argv), \
            patch("spindoctor.autostart.task_exists", return_value=False), \
            patch.object(messagebox, "showerror", unexpected_dialog), \
            patch.object(messagebox, "showwarning", unexpected_dialog), \
            patch.object(messagebox, "showinfo", unexpected_dialog):
        app = gui._SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
        try:
            _pump(app.root, 0.4)
            app._mm_refresh()
            app._on_games_system_change()
            app._gwm_load()
            app._run_cli("spindoctor", ["systems"])
            deadline = time.monotonic() + 30
            while app._current_run is not None and app._current_run.exit_code is None:
                if time.monotonic() > deadline:
                    raise RuntimeError("Sample systems command did not finish")
                _pump(app.root, 0.05)
            if not app._run_history or app._run_history[-1].exit_code != 0:
                detail = app._run_history[-1].joined_output() if app._run_history else "No run record"
                raise RuntimeError("Sample systems command failed:\n" + detail)
            rows = app._logs_tree.get_children()
            app._logs_tree.selection_set(rows[0])
            app._logs_tree.event_generate("<<TreeviewSelect>>")
            app.root.lift()
            manifest = {"version": __version__, "ui_scale": 1.25, "tabs": []}
            for index, label in enumerate(app._tab_base_names):
                app._nb.select(index)
                show_output = label in ("Diagnostics", "Console")
                if app._output_visible != show_output:
                    app._toggle_output(show_output)
                _pump(app.root, 0.2)
                if show_output:
                    app._main_paned.sashpos(0, app._main_paned.winfo_height() - 230)
                    _pump(app.root, 0.1)
                slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
                filename = "{:02d}-{}.png".format(index + 1, slug)
                # Pillow's HWND capture targets this window, not the desktop.
                hwnd = int(app.root.wm_frame(), 0)
                if not hwnd:
                    raise RuntimeError("Tk returned no application window handle")
                image = ImageGrab.grab(window=hwnd)
                if not (
                    app.root.winfo_width() <= image.width <= app.root.winfo_width() + 50
                    and app.root.winfo_height() <= image.height <= app.root.winfo_height() + 100
                ):
                    raise RuntimeError("Capture dimensions do not match the application")
                image.save(output / filename, optimize=True)
                manifest["tabs"].append({"tab": label, "file": filename})
                print("{}: {}x{}".format(filename, image.width, image.height))
            (output / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
            )
        finally:
            if app._proc is not None and app._proc.poll() is None:
                app._proc.terminate()
                app._proc.wait(timeout=10)
            app.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Window-only capture currently requires Windows")
    from PIL import ImageGrab
    if "window" not in inspect.signature(ImageGrab.grab).parameters:
        parser.error("Window-only capture requires Pillow 11.2.1 or newer")
    if "spindoctor.config" in sys.modules:
        parser.error("Run in a fresh process so config isolation happens before import")
    repo = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repo))
    old_cwd = Path.cwd()
    keys = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "PYTHONPATH")
    previous = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(prefix="gui-docs-", dir=str(repo / "build")) as folder:
        root = Path(folder)
        try:
            os.environ["HOME"] = os.environ["USERPROFILE"] = str(root)
            os.environ["HOMEDRIVE"] = root.drive
            os.environ["HOMEPATH"] = str(root)[len(root.drive):]
            os.environ["PYTHONPATH"] = str(repo) + os.pathsep + os.environ.get("PYTHONPATH", "")
            os.chdir(root)
            _prepare_sample(root)
            _capture(output)
        finally:
            os.chdir(old_cwd)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    main()
