"""Tests for spindoctor.gui — mostly headless, plus one Tk-construction smoke.

Most of the tests deliberately avoid spinning up Tk: they exercise the
argument-parsing and CLI-resolution helpers that constitute the testable
surface of the GUI module.

The Tk-construction smoke at the bottom (``test_gui_constructs_against_real_tk``)
is the exception — it actually instantiates ``_SpinDoctorGUI`` so that
class-of-bug regressions like ``AttributeError: ... has no attribute
'_output'`` or ``_tkinter.TclError: unknown option "-foreground"`` get
caught at PR time instead of by users running the frozen exe. On Linux
CI the workflow installs xvfb so a virtual display is available; in
environments without any display the test self-skips.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from spindoctor import __app_name__, __version__
from spindoctor import gui


# ─── main() argument handling ─────────────────────────────────────────────────

def test_main_version_prints_and_exits_zero(capsys):
    rc = gui.main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert __app_name__ in out


def test_main_help_prints_usage(capsys):
    rc = gui.main(["--help"])
    assert rc == 0
    assert "spindoctor-gui" in capsys.readouterr().out


def test_main_unknown_arg_returns_2(capsys):
    rc = gui.main(["--no-such-flag"])
    assert rc == 2
    assert "Unknown argument" in capsys.readouterr().err


# ─── resolve_cli_command ──────────────────────────────────────────────────────

def test_resolve_unknown_binary_raises():
    with pytest.raises(ValueError):
        gui.resolve_cli_command("not-a-real-binary")


def test_resolve_dev_install_falls_back_to_module(monkeypatch):
    """Without a frozen exe and without the binary on PATH, we should
    invoke the underlying module via `python -m`. This is the default
    code path for `pip install -e .` developer setups and for the
    headless CI smoke test."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(gui.shutil, "which", lambda _name: None)

    argv = gui.resolve_cli_command("spindoctor")
    assert argv[0] == sys.executable
    assert argv[1:] == ["-m", "spindoctor.cli"]


def test_resolve_dev_install_prefers_path_binary(monkeypatch, tmp_path):
    """If a real `spindoctor` is on PATH (e.g. installed via `pip install`
    rather than `-e .`), we should use it instead of falling back to
    `python -m` — both work, but the installed entry point is closer to
    what an end-user would invoke."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    fake = tmp_path / "spindoctor"
    fake.write_text("#!/bin/sh\necho ok\n")
    monkeypatch.setattr(gui.shutil, "which",
                        lambda name: str(fake) if name == "spindoctor" else None)

    argv = gui.resolve_cli_command("spindoctor")
    assert argv == [str(fake)]


def test_resolve_frozen_finds_sibling_binary(monkeypatch, tmp_path):
    """The frozen GUI exe locates its peer CLI exes by looking next to
    sys.executable — that's how the release zip ships them, and avoids
    forcing users to put the install folder on PATH."""
    fake_gui_exe = tmp_path / "spindoctor-gui"
    fake_gui_exe.write_bytes(b"")
    sibling = tmp_path / ("spindoctor.exe" if sys.platform == "win32" else "spindoctor")
    sibling.write_bytes(b"")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_gui_exe))

    argv = gui.resolve_cli_command("spindoctor")
    assert argv == [str(sibling)]


def test_resolve_frozen_missing_sibling_raises(monkeypatch, tmp_path):
    """If the user accidentally separates the GUI from the CLI exes,
    we should give a clear error rather than silently falling back to
    a `python -m` invocation that won't work in a frozen build."""
    fake_gui_exe = tmp_path / "spindoctor-gui"
    fake_gui_exe.write_bytes(b"")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_gui_exe))
    monkeypatch.setattr(gui.shutil, "which", lambda _name: None)

    with pytest.raises(gui.CliNotFoundError) as exc:
        gui.resolve_cli_command("spindoctor-fav")
    assert "spindoctor-fav" in str(exc.value)


# ─── Backup tab presets ───────────────────────────────────────────────────────

def test_backup_components_match_cli_components():
    """The Backup tab's checklist must stay in sync with `backup.ALL_COMPONENTS`
    or the GUI will silently omit (or invent) components when building
    `--include`."""
    from spindoctor import backup as backup_mod
    gui_keys = tuple(key for key, _desc in gui._BACKUP_COMPONENTS)
    assert gui_keys == backup_mod.ALL_COMPONENTS


# ─── Migrate tab presets ──────────────────────────────────────────────────────

def test_migrate_components_match_cli_components():
    """Keep the GUI's checkbox list in sync with `migrate.ALL_COMPONENTS`,
    or `--include` will reference components the CLI doesn't recognise."""
    from spindoctor import migrate as migrate_mod
    gui_keys = tuple(key for key, _desc in gui._MIGRATE_COMPONENTS)
    assert gui_keys == migrate_mod.ALL_COMPONENTS


# ─── custom-command presets ───────────────────────────────────────────────────

def test_custom_command_presets_first_is_help():
    # The Custom Command tab uses the first entry as its default value
    # (mirroring the previous hard-coded "--help"), so a regression here
    # would silently change the GUI's startup behaviour.
    assert gui._CUSTOM_COMMAND_PRESETS[0] == "--help"


def test_custom_command_presets_contains_canonical_examples():
    presets = set(gui._CUSTOM_COMMAND_PRESETS)
    # Spot-check a representative slice across each major command family
    # so the dropdown stays useful without enumerating every entry.
    for expected in (
        "doctor",
        "audit --all",
        "fav rebuild --apply",
        "mainmenu show",
        "backup create --target <PATH>",
        "migrate --target <PATH> --apply",
    ):
        assert expected in presets, f"missing preset: {expected}"


def test_custom_command_presets_are_unique():
    # A duplicate would just be visual noise in the Combobox dropdown,
    # but it usually means a copy-paste error during edits — fail loud.
    presets = list(gui._CUSTOM_COMMAND_PRESETS)
    assert len(presets) == len(set(presets))


# ─── Folder-open helpers ──────────────────────────────────────────────────────

def test_open_path_uses_platform_specific_command(monkeypatch, tmp_path):
    """`_open_path` must dispatch to the right OS-native opener.

    We don't actually launch the file explorer — that would pop up a
    real Finder/Explorer window on the dev machine — so the test
    swaps `subprocess.Popen` and `os.startfile` for capturing stubs.
    """
    real_dir = tmp_path / "spindoctor"
    real_dir.mkdir()

    captured: dict = {}

    class _FakeApp:
        # Minimal stand-in for `_SpinDoctorGUI` — just enough for
        # `_open_path` to bind self.messagebox and call the right
        # platform branch.
        messagebox = type("M", (), {
            "showwarning": staticmethod(lambda *_a, **_k: None),
            "showerror": staticmethod(lambda *_a, **_k: None),
        })

        def _open_path(self, path, *, missing_label):  # noqa: D401
            return gui._SpinDoctorGUI._open_path(self, path, missing_label=missing_label)

    monkeypatch.setattr(
        gui.subprocess, "Popen",
        lambda args, *a, **k: captured.setdefault("popen", list(args)),
    )
    # os.startfile only exists on Windows; patching it onto gui.os here
    # lets the win32 branch run on macOS / Linux CI without blowing up
    # before reaching our capture.
    monkeypatch.setattr(
        gui.os, "startfile", lambda p: captured.setdefault("startfile", p),
        raising=False,
    )

    for platform, expected_key in (
        ("win32", "startfile"),
        ("darwin", "popen"),
        ("linux", "popen"),
    ):
        captured.clear()
        monkeypatch.setattr(gui.sys, "platform", platform)
        _FakeApp()._open_path(real_dir, missing_label="ignored")
        assert expected_key in captured, f"{platform}: nothing captured"
        if expected_key == "popen":
            tool = captured["popen"][0]
            expected_tool = "open" if platform == "darwin" else "xdg-open"
            assert tool == expected_tool


def test_open_path_warns_on_missing(monkeypatch, tmp_path):
    """If the path doesn't exist, no OS call should fire — the user
    gets a warning dialog instead. Saves us from confusing 'silently
    nothing happened' behaviour on Windows when a stale config points
    at an unmounted drive."""
    captured: dict = {}

    class _FakeApp:
        messagebox = type("M", (), {
            "showwarning": staticmethod(
                lambda *args, **_k: captured.setdefault("warning", args)
            ),
            "showerror": staticmethod(lambda *_a, **_k: None),
        })

        def _open_path(self, path, *, missing_label):
            return gui._SpinDoctorGUI._open_path(self, path, missing_label=missing_label)

    monkeypatch.setattr(
        gui.subprocess, "Popen",
        lambda *a, **k: pytest.fail("Popen should not run for missing paths"),
    )
    _FakeApp()._open_path(tmp_path / "nope", missing_label="thing")
    assert "warning" in captured


# ─── log viewer helpers ───────────────────────────────────────────────────────

def test_format_bytes_bucketing():
    """Sanity check the byte formatter — same intent as backup.format_bytes
    but inlined to keep the GUI module light."""
    fb = gui._SpinDoctorGUI._format_bytes
    assert fb(0) == "0 B"
    assert fb(1023) == "1023 B"
    assert fb(1024) == "1.0 KB"
    assert fb(1024 * 1024) == "1.0 MB"
    assert fb(5 * 1024 * 1024 * 1024) == "5.0 GB"


def test_format_mtime_returns_iso_like():
    fm = gui._SpinDoctorGUI._format_mtime
    out = fm(1778243696.0)
    # Looks like "YYYY-MM-DD HH:MM:SS" — exact string depends on the
    # host's local TZ, so we just pin the layout.
    assert len(out) == 19
    assert out[4] == "-" and out[7] == "-" and out[10] == " "
    assert out[13] == ":" and out[16] == ":"


def test_log_categories_cover_known_manifest_dirs():
    """The viewer's category list must track manifest dirs the CLI writes
    to, or users can't find their history through the GUI."""
    expected_dirs = {entry[1] for entry in gui._SpinDoctorGUI._LOG_CATEGORIES}
    for required in ("migrations", "curation", "edits", "renames",
                     "media_imports"):
        assert required in expected_dirs


def test_undo_recipes_argv_includes_path_iff_uses_path():
    """Each recipe must produce an argv that includes the manifest path
    iff `uses_path` is True. Catches the off-by-one mistake of putting
    a path-taking command into the no-path bucket (or vice versa)."""
    recipes = gui._SpinDoctorGUI._UNDO_RECIPES
    fake_path = Path("/tmp/spindoctor-fake-manifest.json")
    for dirname, recipe in recipes.items():
        argv = recipe["argv"](fake_path)
        assert argv, f"{dirname}: recipe produced empty argv"
        assert "--undo" in argv, f"{dirname}: missing --undo"
        if recipe["uses_path"]:
            assert str(fake_path) in argv, (
                f"{dirname}: uses_path=True but argv omits the path"
            )
        else:
            assert str(fake_path) not in argv, (
                f"{dirname}: uses_path=False but argv mentions the path"
            )


def test_ignore_global_label_resolves_to_global_key():
    """The dropdown shows a friendlier `_global  (cross-system)` label,
    but ignore_lists is keyed on the literal `_global`. Catch any
    refactor that renames the label without keeping the mapping in
    sync — the viewer would silently fail to remove cross-system
    ignores."""
    label = gui._SpinDoctorGUI._IGNORE_GLOBAL_LABEL
    # The literal storage key must appear inside the label so the
    # mapping function (label → "_global" when label == sentinel) has
    # an obvious correspondence.
    assert "_global" in label


def test_curate_preview_glyphs_are_distinct():
    """The retire and skip glyphs must be different — otherwise the
    toggle handler can't tell which state a row is in. Easy to break
    on a copy-paste; cheap to assert."""
    assert (gui._SpinDoctorGUI._CURATE_RETIRE_GLYPH
            != gui._SpinDoctorGUI._CURATE_SKIP_GLYPH)


def test_undo_recipes_only_target_known_log_categories():
    """A recipe pointing at a category the viewer's tree never shows is
    a dead button — fail loud when that drifts."""
    recipe_dirs = set(gui._SpinDoctorGUI._UNDO_RECIPES)
    category_dirs = {entry[1] for entry
                     in gui._SpinDoctorGUI._LOG_CATEGORIES}
    extra = recipe_dirs - category_dirs
    assert not extra, f"recipes for categories not in tree: {extra}"


# ─── _RunRecord (Logs tab buffer) ─────────────────────────────────────────────

def test_run_record_tag_dry_run():
    """Dry-run + exit 0 should label as DRY-RUN so the Logs tab can
    distinguish "preview, nothing changed" from "applied, succeeded"."""
    rec = gui._RunRecord(started_at="2026-05-08 12:00:00",
                         argv_str="spindoctor audit --all", dry_run=True)
    rec.exit_code = 0
    assert rec.tag() == "DRY-RUN"


def test_run_record_tag_applied_ok():
    rec = gui._RunRecord(started_at="2026-05-08 12:00:00",
                         argv_str="spindoctor audit --all --apply",
                         dry_run=False)
    rec.exit_code = 0
    assert rec.tag() == "OK"


def test_run_record_tag_failed():
    rec = gui._RunRecord(started_at="2026-05-08 12:00:00",
                         argv_str="spindoctor doctor", dry_run=True)
    rec.exit_code = 2
    assert rec.tag() == "FAIL 2"


def test_run_record_tag_running():
    """Before the subprocess exits, exit_code is None and the row
    should show "running" so users can tell what's still in flight."""
    rec = gui._RunRecord(started_at="2026-05-08 12:00:00",
                         argv_str="spindoctor migrate --target X",
                         dry_run=True)
    assert rec.tag() == "running"


def test_run_record_joined_output_concatenates_fragments():
    rec = gui._RunRecord(started_at="t", argv_str="cmd", dry_run=False)
    rec.append("line1\n")
    rec.append("line2\n")
    # Per-line fragments are joined on demand — keeping them as a
    # list avoids O(n²) reallocation on long-running commands.
    assert rec.joined_output() == "line1\nline2\n"


# ─── _format_argv ─────────────────────────────────────────────────────────────

def test_format_argv_quotes_args_with_spaces():
    assert gui._format_argv(["spindoctor", "audit", "--system", "Sega Naomi"]) == \
        'spindoctor audit --system "Sega Naomi"'


def test_format_argv_leaves_simple_args_unquoted():
    assert gui._format_argv(["spindoctor", "doctor"]) == "spindoctor doctor"


# ─── Tk-construction smoke test ───────────────────────────────────────────────


def test_gui_constructs_against_real_tk():
    """Actually instantiate the GUI against a Tk root.

    This is the regression guard for whole-class bugs that only surface
    once the layout is built — e.g. tab builders referencing widgets
    that don't exist yet (the ``_output`` AttributeError, shipped in
    v1.7.0, fixed in v1.7.1), or ttk widgets configured with options
    they don't accept (the Checkbutton ``-foreground`` TclError,
    shipped in v1.7.2, fixed in v1.8.0).
    Both bugs slipped through earlier because every other test stops
    short of constructing a window. Skips if the host has no display
    (typical bare CI runner without xvfb; Linux CI here installs xvfb
    explicitly so this branch is exercised).
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError:
        pytest.skip("Tkinter not available")

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY — run under xvfb to exercise this test")

    try:
        app = gui._SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
    except tk.TclError as exc:
        # macOS without an active GUI session, or Windows headless CI
        # without a windowstation, both raise TclError on Tk() init —
        # treat that the same as "no display".
        msg = str(exc).lower()
        if "no display" in msg or "couldn't connect" in msg or "no windowstation" in msg:
            pytest.skip(f"Tk display unavailable: {exc}")
        raise

    try:
        app.root.update_idletasks()
        # Sanity: every tab builder ran without exception, including the
        # Curate tab (foreground TclError) and the Main Menu tab
        # (_output AttributeError). 15 = the documented tab count.
        assert len(app._tab_base_names) == 15
        # The hoisted widgets that have crashed in past releases:
        assert app._output is not None
        assert app._status_var is not None
    finally:
        app.root.destroy()
