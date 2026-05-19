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


def test_health_to_tabs_only_references_real_tab_labels():
    """Every tab label in `_HEALTH_TO_TABS` must be a real tab name
    the GUI builds, otherwise `_tab_base_names.index(label)` raises
    ValueError and silently drops the badge. Pin the mapping so a
    rename of any tab triggers a test failure."""
    # Tab labels SpinDoctor's `_build_layout` adds to `_tab_base_names`.
    # Kept in sync manually — mirroring the order in `_build_layout`.
    expected_tabs = {
        "Setup", "Wheels", "Main Menu", "Audit & Doctor", "Diagnose",
        "Metadata & Media", "Curate", "Systems", "LEDBlinky", "Lightgun",
        "Tools", "Backup & Restore", "Migrate", "Logs", "Custom Command",
    }
    for check_name, tab_labels in gui._SpinDoctorGUI._HEALTH_TO_TABS.items():
        for label in tab_labels:
            assert label in expected_tabs, (
                f"_HEALTH_TO_TABS[{check_name!r}] references unknown "
                f"tab {label!r}; tab strip has: {sorted(expected_tabs)}"
            )


def test_health_badge_mapping_covers_warn_and_fail():
    badges = gui._SpinDoctorGUI._HEALTH_BADGE
    # `ok` and `info` are deliberately absent — clean areas should NOT
    # decorate their tab. Pin the absence so a future "always show ✓"
    # change is intentional.
    assert "ok" not in badges
    assert "info" not in badges
    # warn and fail must produce visible glyphs.
    assert badges["warn"]
    assert badges["fail"]


@pytest.mark.parametrize("s,expected", [
    ("1024x768", True),
    ("1280x800+120+60", True),
    ("960x720+0+0", True),
    ("1920x1080-50+200", True),       # negative X offset (multi-monitor)
    ("1920x1080+50-200", True),       # negative Y offset
    ("960x720+-30+-40", True),        # the form Tk emits for negative offsets
    # rejections
    ("", False),
    ("garbage", False),
    ("x", False),
    ("1024", False),                  # no height
    ("1024x", False),
    ("1024x800x", False),             # trailing junk
    ("1x1", False),                   # too small (require 2+ digits)
    ("100000x100000", False),         # implausibly huge
])
def test_is_plausible_geometry(s, expected):
    """Persisted geometry strings are revalidated on launch — a
    hand-corrupted config.json must not be able to raise TclError out
    of the splash path."""
    assert gui._is_plausible_geometry(s) is expected


def test_build_fetch_meta_args_round_trip():
    """The fetch-meta arg builder is the single source of truth shared
    by the single-system Run button and the multi-system chainer.
    Smoke-check that it produces the canonical CLI shape for a typical
    invocation."""
    # Construct a minimal mock with just the vars the method reads.
    class _FakeVar:
        def __init__(self, v): self._v = v
        def get(self): return self._v

    class _FakeGUI:
        _meta_auto_best_var = _FakeVar(True)
        _meta_all_games_var = _FakeVar(False)
        _meta_no_cache_var = _FakeVar(True)
        _meta_source_var = _FakeVar("screenscraper")
        _meta_threshold_var = _FakeVar("0.5")
        _meta_apply_var = _FakeVar(True)
        messagebox = type("M", (), {
            "showerror": staticmethod(lambda *_a, **_k: None),
        })

    args = gui._SpinDoctorGUI._build_fetch_meta_args(
        _FakeGUI, ["--system", "NES"],
    )
    assert args is not None
    assert args[0] == "fetch-meta"
    assert "--system" in args and "NES" in args
    assert "--auto-best" in args
    assert "--no-cache" in args
    assert "--source" in args and "screenscraper" in args
    assert "--threshold" in args and "0.5" in args
    assert "--apply" in args


def test_build_fetch_meta_args_rejects_out_of_range_threshold():
    class _FakeVar:
        def __init__(self, v): self._v = v
        def get(self): return self._v

    captured: dict = {}

    class _FakeGUI:
        _meta_auto_best_var = _FakeVar(False)
        _meta_all_games_var = _FakeVar(False)
        _meta_no_cache_var = _FakeVar(False)
        _meta_source_var = _FakeVar("config default")
        _meta_threshold_var = _FakeVar("1.5")  # out of range
        _meta_apply_var = _FakeVar(False)
        messagebox = type("M", (), {
            "showerror": staticmethod(
                lambda *a, **_k: captured.update({"err": a}),
            ),
        })

    args = gui._SpinDoctorGUI._build_fetch_meta_args(
        _FakeGUI, ["--all"],
    )
    # Returns None on validation failure so the caller can abort.
    assert args is None
    assert "err" in captured


def test_custom_command_presets_match_actual_cli_syntax():
    """Preset hints must use real flag names — `media-add` was shipped
    with `--source` in earlier presets even though the CLI flag is
    `--file`. Fail loud if a similar drift happens again.
    """
    presets = set(gui._CUSTOM_COMMAND_PRESETS)
    media_add = next((p for p in presets if p.startswith("media-add")), None)
    assert media_add is not None
    # The CLI is `media-add --system X --game Y --type Z --file PATH`;
    # if a future refactor renames any of these flags the preset will
    # be wrong again. Pin the current shape.
    assert "--file" in media_add
    assert "--game" in media_add
    assert "--type" in media_add
    assert "--source" not in media_add  # the old, wrong flag name


# ─── _is_read_only_invocation ─────────────────────────────────────────────────


@pytest.mark.parametrize("args", [
    ("doctor",),
    ("audit", "--all"),
    ("find-dupes", "--all"),
    ("lint",),
    ("preview",),
    ("mainmenu", "show"),
    ("mainmenu", "edit"),
    ("backup", "list", "--target", "/x"),
    ("fav", "list"),
    ("curate", "--list-manifests"),
    ("config", "show"),
])
def test_read_only_invocations_are_recognised(args):
    """Read-only commands must NOT get the DRY RUN banner.

    Regressions here either drown the user in fake "preview" banners
    on read-only checks (annoying) or, the other direction, hide the
    DRY RUN banner on a real preview run (dangerous — the user could
    think `cleanup run` without --apply was a real apply).
    """
    assert gui._is_read_only_invocation(args) is True


@pytest.mark.parametrize("args", [
    # match list is read-only — match clear isn't (it deletes cache
    # files), but the GUI invokes it with --yes so the confirmation
    # dialog the GUI shows is the only safety gate. The DRY RUN banner
    # would only confuse users since --yes already commits.
    ("match", "list"),
    ("organize", "MAME"),  # organize without --restructure --apply is XML-only
])
def test_extra_read_only_invocations(args):
    # match list and bare `organize` write sort wheels but don't move
    # ROMs — close enough to "read-only" that the DRY RUN banner is
    # noise. Confirms _is_read_only_invocation handles both shapes.
    if args[0] == "match":
        assert gui._is_read_only_invocation(args) is True
    else:
        # `organize` without sub-tokens isn't in the read-only set
        # (it does touch XML); the banner is acceptable for it.
        # This test pins the negative case so a future "should be
        # read-only" expansion is intentional.
        assert gui._is_read_only_invocation(args) is False


@pytest.mark.parametrize("args", [
    # Commands that *do* accept --apply must be flagged as dry-run-able
    # so the banner appears for their preview invocations.
    ("cleanup", "run"),
    ("mainmenu", "sort", "alpha"),
    ("mainmenu", "reorder", "SNES", "3"),
    ("fav", "rebuild"),
    ("recent", "rebuild"),
    ("backup", "create", "--target", "/x"),
    ("migrate", "--target", "/x"),
    ("theme-apply", "/some/pack"),
    ("rename", "--system", "MAME", "--game", "x", "--to", "y"),
    ("clone", "--system", "MAME", "--game", "x", "--to", "y"),
    ("add-system", "NES"),
    ("add-pc-system", "Steam"),
    ("pc-rename", "Old", "New"),
    ("batch-edit", "--system", "MAME"),
    ("ledblinky", "fix"),
    ("organize", "--all"),
    ("media-scan", "--all"),
    ("fetch-meta", "--all"),
])
def test_dry_run_capable_invocations_are_not_read_only(args):
    assert gui._is_read_only_invocation(args) is False


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
        # Pin the workflow-oriented order so a drive-by reorder doesn't
        # regress UX without anyone noticing. See `_build_layout` for
        # the rationale behind the sequencing.
        assert app._tab_base_names == [
            "Setup",
            "Audit & Doctor",
            "Diagnose",
            "Metadata & Media",
            "Curate",
            "Wheels",
            "Main Menu",
            "Systems",
            "LEDBlinky",
            "Lightgun",
            "Backup & Restore",
            "Tools",
            "Migrate",
            "Logs",
            "Custom Command",
        ]
        # The hoisted widgets that have crashed in past releases:
        assert app._output is not None
        assert app._status_var is not None

        # v1.9: live UI-scale changes must not raise and must round-trip
        # back to the named-font sizes. Pick a non-default scale, then
        # reset — we only care that the API works without exceptions.
        app._set_ui_scale(0.8)
        app.root.update_idletasks()
        assert abs(app._ui_scale - 0.8) < 1e-6
        app._set_ui_scale(1.25)
        app.root.update_idletasks()
        assert abs(app._ui_scale - 1.25) < 1e-6
        app._set_ui_scale(1.0)

        # Output pane toggle must flip both ways and update the button
        # label so the status-bar control stays in sync.
        assert app._output_visible is True
        app._toggle_output(False)
        assert app._output_visible is False
        assert app._output_toggle_btn.cget("text") == "Show output"
        app._toggle_output(True)
        assert app._output_visible is True
        assert app._output_toggle_btn.cget("text") == "Hide output"

        # Eyeball toggle: flipping must clear and restore show="*".
        # The setup tab builds the credential entries lazily, but the
        # construction above triggers _build_setup_tab so they exist.
        pw_entry = app._cred_entries.get("screenscraper_pass")
        assert pw_entry is not None
        assert str(pw_entry.cget("show")) == "*"
        app._toggle_password_visibility("screenscraper_pass")
        assert str(pw_entry.cget("show")) == ""
        app._toggle_password_visibility("screenscraper_pass")
        assert str(pw_entry.cget("show")) == "*"

        # Right-click context menu must be attached to credential
        # entries (covered by the walker, not a per-call-site attach).
        assert getattr(pw_entry, "_spindoctor_ctxmenu_attached", False)
    finally:
        app.root.destroy()


def test_gui_menu_commands_are_safe_to_invoke(monkeypatch):
    """Walk every File / View / Help menu entry and invoke it.

    Regression guard for menu commands that reference widgets or
    methods that don't exist — same class of bug as v1.7.0's `_output`
    AttributeError, but for the menubar rather than tab builders. The
    base smoke test exercises construction; this one proves every
    menu item can actually be clicked.

    External side effects are stubbed at the module level (``gui.os``,
    ``gui.subprocess``), heavy Toplevel-opening handlers that scan
    the filesystem are stubbed on the instance, and ``Exit`` is
    skipped (it destroys ``root`` and would tear down the test).
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError:
        pytest.skip("Tkinter not available")

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY — run under xvfb to exercise this test")

    # Patch external surfaces before the GUI is constructed so the
    # post-construction startup checks don't fire real OS commands.
    monkeypatch.setattr(gui.subprocess, "Popen", lambda *_a, **_k: None)
    monkeypatch.setattr(gui.os, "startfile",
                        lambda *_a, **_k: None, raising=False)
    from spindoctor import update_check
    monkeypatch.setattr(update_check, "check_for_update", lambda _v: None)
    # The heavy Toplevel-opening menu commands spawn worker threads
    # that hit the filesystem and call ``root.after`` — neither is
    # safe in a unit test that destroys the root immediately after.
    # Stub them out on the CLASS *before* construction so the
    # ``command=self._show_…`` references the menu captures point at
    # the no-op, not the real method.
    monkeypatch.setattr(gui._SpinDoctorGUI,
                        "_show_log_viewer", lambda self: None)
    monkeypatch.setattr(gui._SpinDoctorGUI,
                        "_show_theme_browser", lambda self: None)
    # ``_manual_update_check`` spawns a worker thread that calls
    # ``root.after(...)`` to marshal its result back to the main loop;
    # if that thread fires after the test destroys ``root`` it leaks
    # a thread-level exception. The dedicated
    # ``test_manual_update_check_does_not_block_main_thread`` already
    # covers the behaviour — here we only need the menu command to
    # resolve without blowing up.
    monkeypatch.setattr(gui._SpinDoctorGUI,
                        "_manual_update_check", lambda self: None)

    try:
        app = gui._SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
    except tk.TclError as exc:
        msg = str(exc).lower()
        if "no display" in msg or "couldn't connect" in msg or "no windowstation" in msg:
            pytest.skip(f"Tk display unavailable: {exc}")
        raise

    try:
        # Silence the messagebox dialogs that some handlers open — they
        # would otherwise block until the user clicks OK.
        for fn in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(app.messagebox, fn,
                                lambda *_a, **_k: None, raising=False)
        monkeypatch.setattr(app.messagebox, "askyesno",
                            lambda *_a, **_k: False, raising=False)
        # Suppress preference persistence — the View menu's UI-scale
        # radiobuttons and "Show output pane" checkbutton would
        # otherwise write to the real ``~/.spindoctor/config.json``,
        # leaking state into subsequent tests that read it back.
        monkeypatch.setattr(app, "_persist_ui_pref", lambda **_k: None)

        # Walk the menubar and invoke every command-bearing entry.
        # ``Menu.invoke`` is the documented way to fire a menu entry
        # from code — it's exactly what Tk does on a real click.
        menubar = app.root.nametowidget(app.root.cget("menu"))
        invoked = 0
        for sub_name in menubar.children:
            submenu = menubar.children[sub_name]
            last = submenu.index("end")
            if last is None:
                continue
            for i in range(last + 1):
                entry_type = submenu.type(i)
                if entry_type not in ("command", "checkbutton", "radiobutton"):
                    continue
                # Skip Exit — it destroys root and would kill the test.
                try:
                    label = submenu.entrycget(i, "label")
                except tk.TclError:
                    label = ""
                if label == "Exit":
                    continue
                submenu.invoke(i)
                invoked += 1
        # Sanity: at least every File/Help/View entry minus Exit got
        # invoked. If this drops to a tiny number the walker is silently
        # skipping things.
        assert invoked >= 10, f"only invoked {invoked} menu entries"
        # Pump the loop so background `root.after(0, …)` callbacks
        # (e.g. the manual update check's result handler) run before
        # we destroy the root.
        app.root.update_idletasks()
        app.root.update()
    finally:
        app.root.destroy()


def test_manual_update_check_does_not_block_main_thread():
    """`_manual_update_check` must run the network call on a worker
    thread so a slow GitHub doesn't freeze the GUI.

    Regression guard: the original implementation called
    ``update_check.check_for_update`` synchronously on the menu-click
    handler. With urllib's 5 s timeout that meant the entire window
    hung for up to 5 s on offline machines (the exact target user is
    cabinet owners with intermittent network). Make this test fail if
    anyone "simplifies" the helper back to a synchronous call.
    """
    import threading
    import time
    from spindoctor import update_check

    # Stub the GUI's external surfaces just enough that the handler
    # can run without a real Tk root.
    class _Root:
        def after(self, _delay, func, *args):
            # Run the marshalled callback inline so the worker's
            # "hop back to the main thread" path completes promptly —
            # we're testing that the *outer* call doesn't block, not
            # the after-marshal mechanics.
            func(*args)

    class _Messagebox:
        @staticmethod
        def showinfo(*_a, **_k):
            pass

        @staticmethod
        def askyesno(*_a, **_k):
            return False

    worker_done = threading.Event()
    started = threading.Event()
    finish_check = threading.Event()

    stub = type("Stub", (), {})()
    stub.root = _Root()
    stub.messagebox = _Messagebox
    stub._set_status = lambda _msg: None
    stub._open_url = lambda _u: None
    # The worker hits one of these after ``check_for_update`` returns;
    # provide no-op stubs so the worker thread doesn't raise on exit.
    stub._on_manual_update_result = lambda _r: worker_done.set()
    stub._on_manual_update_failed = lambda _m: worker_done.set()
    stub._on_manual_update_disabled = lambda _m: worker_done.set()

    def slow_check(_version):
        started.set()
        # Block until the test releases us — proves the call is on a
        # worker thread, not the test thread.
        finish_check.wait(timeout=5.0)
        return None

    original = update_check.check_for_update
    update_check.check_for_update = slow_check
    try:
        t0 = time.monotonic()
        gui._SpinDoctorGUI._manual_update_check(stub)
        elapsed = time.monotonic() - t0
        # Must return promptly — if it blocked on the network call
        # this would be ≥ 5 s. Even a generous bound catches the
        # regression while staying robust on slow CI.
        assert elapsed < 0.5, f"_manual_update_check blocked for {elapsed:.2f}s"
        # And the worker thread must have actually been started.
        assert started.wait(timeout=2.0), "worker thread never started"
    finally:
        finish_check.set()
        # Wait for the worker to drain so it doesn't surface as an
        # unhandled thread exception after the test returns.
        worker_done.wait(timeout=2.0)
        update_check.check_for_update = original


def test_gui_survives_missing_keysym_in_bind_all():
    """Simulate a Tk build whose keysym table is missing ``grave`` — the
    exact failure mode that shipped to Windows users on v1.9.0, where
    the Python 3.8 Tcl/Tk that PyInstaller bundles doesn't know the X11
    ``grave`` keysym and ``bind_all("<Control-grave>", ...)`` raised
    ``TclError: bad event type or keysym "grave"``, crashing startup
    before the main window appeared.

    Windows CI runs Python 3.12 (a newer Tk that *does* recognise
    ``grave``), so the smoke test above passes on Windows even though
    the frozen 3.8 build is broken. This test patches ``bind_all`` to
    reject any "grave-ish" keysym and asserts the GUI still constructs
    — proving keyboard shortcuts degrade gracefully instead of taking
    the whole app down with them.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError:
        pytest.skip("Tkinter not available")

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY — run under xvfb to exercise this test")

    try:
        root_probe = tk.Tk()
    except tk.TclError as exc:
        msg = str(exc).lower()
        if "no display" in msg or "couldn't connect" in msg or "no windowstation" in msg:
            pytest.skip(f"Tk display unavailable: {exc}")
        raise
    root_probe.destroy()

    original_bind_all = tk.Misc.bind_all

    # Simulate every X11-only keysym we use in shortcut bindings —
    # any of these may be absent from the Tcl/Tk that ships with
    # Python 3.8 on Windows. The GUI must degrade gracefully on all
    # of them, not just `grave`.
    missing = ("grave", "quoteleft", "asciigrave", "KP_Add", "KP_Subtract")

    def picky_bind_all(self, sequence=None, func=None, add=None):
        if sequence and any(name in sequence for name in missing):
            raise tk.TclError(f'bad event type or keysym in "{sequence}"')
        return original_bind_all(self, sequence, func, add)

    tk.Misc.bind_all = picky_bind_all
    try:
        app = gui._SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
        try:
            app.root.update_idletasks()
            assert len(app._tab_base_names) == 15
            # Pin the workflow-oriented order so a future drive-by
            # reorder doesn't regress UX without anyone noticing.
            # See `_build_layout` for the rationale.
            assert app._tab_base_names == [
                "Setup",
                "Audit & Doctor",
                "Diagnose",
                "Metadata & Media",
                "Curate",
                "Wheels",
                "Main Menu",
                "Systems",
                "LEDBlinky",
                "Lightgun",
                "Backup & Restore",
                "Tools",
                "Migrate",
                "Logs",
                "Custom Command",
            ]
        finally:
            app.root.destroy()
    finally:
        tk.Misc.bind_all = original_bind_all


def test_safe_bind_all_swallows_tclerror():
    """Pure-unit guard: ``_safe_bind_all`` must never propagate a
    ``TclError`` to the caller, regardless of which keysym Tk rejects.

    The whole-GUI smoke above is the integration check; this one runs
    everywhere (no display required) and protects the helper itself
    from being "simplified" back into a bare ``bind_all`` during a
    future refactor.
    """
    class _FakeTclError(Exception):
        pass

    class _FakeTk:
        TclError = _FakeTclError

    class _FakeRoot:
        def __init__(self):
            self.accepted = []

        def bind_all(self, sequence, callback):
            if "grave" in sequence:
                raise _FakeTclError('bad event type or keysym "grave"')
            self.accepted.append(sequence)

    stub = type("Stub", (), {})()
    stub.tk = _FakeTk
    stub.root = _FakeRoot()

    # Bound method invocation mirrors how `_build_layout` calls it.
    assert gui._SpinDoctorGUI._safe_bind_all(
        stub, "<Control-Key-1>", lambda _e: None) is True
    assert gui._SpinDoctorGUI._safe_bind_all(
        stub, "<Control-grave>", lambda _e: None) is False
    assert stub.root.accepted == ["<Control-Key-1>"]


# ─── module-level helpers reachable without Tk ────────────────────────────────

def test_clamp_ui_scale_clamps_extremes():
    assert gui._clamp_ui_scale(0.1) == gui.UI_SCALE_MIN
    assert gui._clamp_ui_scale(5.0) == gui.UI_SCALE_MAX
    assert gui._clamp_ui_scale(1.0) == 1.0
    assert gui._clamp_ui_scale("garbage") == 1.0


def test_ui_scale_presets_includes_1x():
    # The reset action snaps to 1.0; if the presets ever lose that entry
    # the View menu radio would have no preset corresponding to "default".
    assert 1.0 in gui.UI_SCALE_PRESETS


# ─── 2.0-era surfaces with no smoke coverage before now ──────────────────────
#
# All four of the GUI features added during the 2.0 cycle — the Output
# find bar, the first-run wizard dialog, the preflight chain button,
# and the drag-and-drop folder hook — multi-widget surfaces that are
# *exactly* the shape of bug the project memory flags as having shipped
# twice already (the v1.7.0 `_output` AttributeError, the v1.7.2
# Checkbutton `-foreground` TclError). The construction smoke at the
# top of this file catches whole-window failures; these tests pin the
# specific construct / invoke / teardown paths for each surface so a
# refactor can't silently break them.


def _build_gui_for_test(monkeypatch):
    """Construct a real `_SpinDoctorGUI` for the 2.0-surface tests.

    Returns ``(app, tk_module)`` or calls ``pytest.skip`` when no display
    is available (CI without xvfb, macOS without a GUI session, headless
    Windows). Mirrors the harness used by ``test_gui_constructs_against_real_tk``
    and ``test_gui_menu_commands_are_safe_to_invoke``.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError:
        pytest.skip("Tkinter not available")

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY — run under xvfb to exercise this test")

    # Stub the subprocess + startfile surfaces so any post-construction
    # callbacks (notably the manual update check on first paint) can't
    # touch the real shell.
    monkeypatch.setattr(gui.subprocess, "Popen", lambda *_a, **_k: None)
    monkeypatch.setattr(gui.os, "startfile",
                        lambda *_a, **_k: None, raising=False)
    from spindoctor import update_check
    monkeypatch.setattr(update_check, "check_for_update", lambda _v: None)

    try:
        app = gui._SpinDoctorGUI(tk, ttk, filedialog, messagebox, scrolledtext)
    except tk.TclError as exc:
        msg = str(exc).lower()
        if "no display" in msg or "couldn't connect" in msg or "no windowstation" in msg:
            pytest.skip(f"Tk display unavailable: {exc}")
        raise
    return app, tk


def test_find_bar_open_navigates_and_close(monkeypatch):
    """Open the find bar, seed the Output buffer, walk matches, close.

    Regression guard for `_find_open` / `_refresh_find_matches` /
    `_find_next` / `_find_prev` / `_find_close` — multi-widget
    construction in `_build_layout` plus runtime tag-management against
    the ScrolledText. Previously zero coverage despite being a primary
    Ctrl+F-driven UX surface.
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        # Seed the Output panel with content the find bar can scan over.
        # Use `_append_output` so the same insert path users hit is
        # exercised (write to a disabled Text widget via re-enable hack).
        app._append_output(
            "Audit complete: nes ok\nAudit complete: snes ok\n"
            "Audit complete: gba failed\n"
        )

        # Open: the find bar should be packed (manager set to 'pack'),
        # the entry focused, and `_refresh_find_matches` should have
        # run (empty query → 0 matches).
        app._find_open()
        app.root.update_idletasks()
        app.root.update()
        assert app._find_bar.winfo_manager() == "pack"
        assert app._find_match_var.get() == ""

        # Typing a query updates the count via the StringVar trace.
        app._find_var.set("Audit")
        app.root.update_idletasks()
        assert app._find_matches, "expected matches for 'Audit'"
        assert "of" in app._find_match_var.get()

        # Next/Prev rotate the cursor through the match list without raising.
        starting_cursor = app._find_cursor
        app._find_next()
        assert app._find_cursor != starting_cursor or len(app._find_matches) == 1
        app._find_prev()
        # Prev from the original position wraps; either way it must not raise.

        # Close clears highlights and unpacks the bar (no manager).
        app._find_close()
        app.root.update_idletasks()
        assert app._find_bar.winfo_manager() == ""
        assert app._find_matches == []
        assert app._find_match_var.get() == ""
    finally:
        app.root.destroy()


def test_find_bar_handles_no_matches_gracefully(monkeypatch):
    """A query that matches nothing should report '0 matches' and not
    crash subsequent Next/Prev calls (they're guarded against empty match lists).
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        app._append_output("only the lonely\n")
        app._find_open()
        app._find_var.set("zzz-never-matches")
        app.root.update_idletasks()
        assert app._find_match_var.get() == "0 matches"
        # Both navigation calls should no-op rather than raise.
        app._find_next()
        app._find_prev()
        app._find_close()
    finally:
        app.root.destroy()


def test_first_run_wizard_dialog_constructs(monkeypatch):
    """`_show_first_run_wizard` opens a three-step Toplevel without raising.

    The wizard is opt-in (Setup-tab button or Help menu) — no auto-
    fire. This test exercises the manually-invoked path. Construction-
    time bugs in this dialog are the precise shape of the
    `_output`-style AttributeError the project memory warns about.
    """
    app, tk_mod = _build_gui_for_test(monkeypatch)
    try:
        # `_show_first_run_wizard` opens a modal Toplevel; we want to
        # build it and immediately destroy it. Capture the new Toplevel
        # by snapshotting the root's children before/after.
        before = set(app.root.winfo_children())
        app._show_first_run_wizard()
        app.root.update_idletasks()
        after = set(app.root.winfo_children())
        new_windows = after - before
        # At least one Toplevel should have been created; the wizard's
        # path-step Browse buttons can lazily build a hidden filedialog
        # Toplevel as a side effect on some Tk builds, so we don't pin
        # an exact count — just that the wizard window itself exists.
        toplevels = [
            w for w in new_windows
            if isinstance(w, tk_mod.Toplevel)
        ]
        assert toplevels, f"expected a wizard Toplevel, got {new_windows}"
        wizard_windows = [w for w in toplevels if "Welcome" in w.title()]
        assert wizard_windows, (
            f"expected a Welcome window, got titles {[w.title() for w in toplevels]}"
        )
        for w in toplevels:
            w.destroy()
    finally:
        app.root.destroy()


def test_run_preflight_dispatches_three_step_chain(monkeypatch):
    """`_run_preflight` chains `doctor`, `tools-audit`, `audit --all`.

    Mock `_run_cli` so the actual subprocesses never fire — we only
    want to verify that the chain *would* invoke the three commands in
    the documented order and the summariser runs at the end.
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        calls: list[tuple[str, tuple[str, ...]]] = []

        def fake_run_cli(binary, args, on_complete=None):
            calls.append((binary, tuple(args)))
            # Simulate a synchronous successful run so the chain
            # advances without spinning on a real process.
            if on_complete is not None:
                on_complete(0)

        summaries: list[list[tuple[str, int]]] = []
        original_summarise = app._summarise_preflight

        def fake_summarise(results):
            summaries.append(list(results))
            # Suppress the messagebox the real summariser opens.

        monkeypatch.setattr(app, "_run_cli", fake_run_cli)
        monkeypatch.setattr(app, "_summarise_preflight", fake_summarise)
        # Sanity reference so the linter doesn't strip the import-style
        # binding above — the original is restored on tearDown.
        _ = original_summarise

        app._run_preflight()
        app.root.update_idletasks()

        # The three documented steps, in order:
        assert [c[1][0] for c in calls] == ["doctor", "tools-audit", "audit"]
        # Final step should be `audit --all`.
        assert calls[-1] == ("spindoctor", ("audit", "--all"))
        # Summariser received one (name, exit_code) tuple per step.
        assert summaries, "summariser never ran"
        assert [r[0] for r in summaries[-1]] == [
            "doctor", "tools-audit", "audit --all",
        ]
        assert all(rc == 0 for _, rc in summaries[-1])
    finally:
        app.root.destroy()


def test_register_path_drop_target_no_op_without_tkdnd(monkeypatch):
    """When `tkinterdnd2` isn't available, `_register_path_drop_target`
    must silently no-op rather than raising. This is the most common
    code path for the binary install (where tkdnd ships) and for the
    pip install (where it doesn't ship unless `[gui]` or `[all]` was
    specified) — both have to behave.
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        # Force the "no tkdnd" branch even on a machine that has it.
        app._dnd_available = False
        app._tkdnd = None
        # A dummy widget with no drop_target_register attribute would
        # crash a non-defensive implementation. The function must
        # short-circuit before touching the widget.

        class _DummyWidget:
            def drop_target_register(self, *_a, **_k):  # pragma: no cover
                raise AssertionError(
                    "drop_target_register called when tkdnd is unavailable"
                )

        dummy_var = app.tk.StringVar()
        # Should return without raising and without touching the widget.
        app._register_path_drop_target(_DummyWidget(), dummy_var)
    finally:
        app.root.destroy()


def test_register_path_drop_target_wires_callback_when_tkdnd_present(monkeypatch):
    """With a fake tkdnd module, `_register_path_drop_target` should
    register the widget for DND_FILES and bind a `<<Drop>>` callback
    whose body sets the StringVar from a parsed event payload.
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        registered: list[object] = []
        bindings: dict[str, object] = {}

        class _FakeTkDnd:
            DND_FILES = "DND_Files"

        class _FakeWidget:
            def drop_target_register(self, *types):
                registered.append(types)

            def dnd_bind(self, sequence, callback):
                bindings[sequence] = callback

        app._dnd_available = True
        app._tkdnd = _FakeTkDnd()
        var = app.tk.StringVar()
        widget = _FakeWidget()
        app._register_path_drop_target(widget, var)

        assert registered == [("DND_Files",)]
        assert "<<Drop>>" in bindings

        # Simulate a drop event with a brace-quoted path containing spaces.
        class _Event:
            data = "{C:/Games/My ROMs}"
            action = "copy"

        callback = bindings["<<Drop>>"]
        result = callback(_Event())
        assert result == "copy"
        assert var.get() == "C:/Games/My ROMs"

        # And a plain (non-brace) drop with a file:// scheme prefix.
        class _Event2:
            data = "file:///tmp/MyFolder"
            action = "link"

        callback(_Event2())
        assert var.get() == "/tmp/MyFolder"
    finally:
        app.root.destroy()


# ─── 2.0 polish: What's-new + keyboard shortcuts dialogs ──────────────────────


def test_keyboard_shortcuts_dialog_constructs(monkeypatch):
    """Help → Keyboard shortcuts opens a Toplevel without raising."""
    app, tk_mod = _build_gui_for_test(monkeypatch)
    try:
        before = set(app.root.winfo_children())
        app._show_keyboard_shortcuts()
        app.root.update_idletasks()
        after = set(app.root.winfo_children())
        new_windows = [
            w for w in (after - before) if isinstance(w, tk_mod.Toplevel)
        ]
        titles = [w.title() for w in new_windows]
        assert any("Keyboard shortcuts" in t for t in titles), titles
        for w in new_windows:
            w.destroy()
    finally:
        app.root.destroy()


# ─── 2.0 follow-up fixes ──────────────────────────────────────────────────────


def test_fetch_meta_args_always_avoid_interactive_prompt(monkeypatch):
    """The GUI can't drive an interactive input() prompt. The argv MUST
    contain either --auto-best (checkbox on) or --skip-ambiguous
    (checkbox off) — never the bare default which would prompt.
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        # Default (checkbox on) → --auto-best
        app._meta_auto_best_var.set(True)
        args = app._build_fetch_meta_args(["--system", "MAME"])
        assert args is not None
        assert "--auto-best" in args
        assert "--skip-ambiguous" not in args

        # Checkbox off → --skip-ambiguous (NOT bare default)
        app._meta_auto_best_var.set(False)
        args = app._build_fetch_meta_args(["--system", "MAME"])
        assert args is not None
        assert "--skip-ambiguous" in args
        assert "--auto-best" not in args
    finally:
        app.root.destroy()


# ─── 2.0 loose-ends bundle ────────────────────────────────────────────────────


def test_run_migrate_apply_shows_confirm_dialog_keep_source(monkeypatch):
    """Apply-mode migrate must ask for confirmation before shelling out.
    The keep-source path uses the "reversible by deleting the
    destination" wording so the user understands the blast radius is
    smaller than a destructive move.
    """
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        app._migrate_target_var.set("/tmp/spindoctor-test-dest")
        app._migrate_keep_source_var.set(True)
        app._migrate_apply_var.set(True)
        # All other component checkboxes default to True per the tab
        # builder, so _selected_migrate_components returns None (which
        # passes the guard).

        asks: list[str] = []
        monkeypatch.setattr(
            app.messagebox, "askyesno",
            lambda title, msg: asks.append((title, msg)) or False,
        )
        ran: list[list[str]] = []
        monkeypatch.setattr(app, "_run_cli", lambda binary, args: ran.append(args))

        app._run_migrate()

        assert len(asks) == 1, "expected exactly one confirm dialog"
        assert "Migrate library" in asks[0][0]
        assert "--keep-source" in asks[0][1] or "originals stay" in asks[0][1]
        assert not ran, "user said No — subprocess must not start"
    finally:
        app.root.destroy()


def test_run_migrate_apply_shows_confirm_dialog_destructive_move(monkeypatch):
    """The destructive-move path must warn that originals will be
    removed AND surface the undo-manifest path as the only recovery."""
    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        app._migrate_target_var.set("/tmp/spindoctor-test-dest")
        app._migrate_keep_source_var.set(False)
        app._migrate_apply_var.set(True)

        asks: list[tuple[str, str]] = []
        monkeypatch.setattr(
            app.messagebox, "askyesno",
            lambda title, msg: asks.append((title, msg)) or True,
        )
        ran: list[list[str]] = []
        monkeypatch.setattr(app, "_run_cli", lambda binary, args: ran.append(args))

        app._run_migrate()

        assert len(asks) == 1
        # The wording must mention the irreversible nature and the
        # undo-manifest escape hatch — that's the load-bearing UX.
        body = asks[0][1]
        assert "MOVE" in body
        assert "undo" in body.lower()
        assert "manifest" in body.lower()
        assert ran and "--apply" in ran[0]
    finally:
        app.root.destroy()


def test_main_menu_parse_error_surfaces_error_dialog(monkeypatch, tmp_path):
    """A malformed Main Menu.xml must trigger a showerror modal so the
    user actually notices — not just a line in the Output pane.
    """
    from spindoctor import config as cfg_mod

    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        hyperspin = tmp_path / "HyperSpin"
        (hyperspin / "Databases" / "Main Menu").mkdir(parents=True)
        xml = hyperspin / "Databases" / "Main Menu" / "Main Menu.xml"
        xml.write_text("<menu><game name=", encoding="utf-8")  # malformed

        cfg = cfg_mod.Config()
        cfg.hyperspin_dir = str(hyperspin)

        monkeypatch.setattr(
            "spindoctor.gui.load_config", lambda: cfg,
        )

        errors: list[tuple[str, str]] = []
        monkeypatch.setattr(
            app.messagebox, "showerror",
            lambda title, msg: errors.append((title, msg)),
        )

        app._mm_refresh()

        assert errors, "malformed XML must trigger an error dialog"
        title, body = errors[0]
        assert "Main Menu.xml" in title or "Main Menu.xml" in body
        # The Treeview must reset so the user doesn't see stale rows.
        assert app._mm_data == []
    finally:
        app.root.destroy()
