# Changelog

All notable changes to SpinDoctor are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **GUI: Inspect-a-single-game controls on the Diagnose tab.** A system dropdown + optional ROM entry + Inspect button drives `spindoctor inspect` directly — the highest-value diagnostic command after audit was previously only reachable via Custom Command.
- **GUI: Manage individual favorites on the Wheels tab.** System / ROM entry plus Add / Remove / List buttons wired to `spindoctor fav add|remove|list`, so curating the cross-system Favorites wheel doesn't require dropping to a terminal.
- **GUI: Rename and clone a single game on the Systems tab.** System / Game / New name fields drive `spindoctor rename` and `spindoctor clone` with the tab's existing Apply checkbox. Both commands write an undo manifest, so even a wrong rename is reversible from the Logs tab.
- **GUI: Indeterminate progress bar in the status bar.** Appears next to the Stop button while a subprocess is streaming, vanishes when it exits. Multi-hour migrate / audit runs no longer look like a hung GUI when the output panel is quiet.

### Fixed

- **GUI: `_mm_save_order` runs on a worker thread.** Saving a reordered Main Menu used to parse, mutate, and rewrite the XML on the Tk main thread; on a HDD-backed cabinet this froze the UI for several seconds. The worker handles parse + backup + atomic rename and marshals success/failure back to the main thread via `root.after(0, …)`.
- **GUI: Main Menu tab no longer blocks first paint.** `_mm_refresh` (XML parse + tree population) was called inline from the tab builder. It now runs via `after_idle`, so the window appears immediately and the table populates a moment later.
- **GUI: `Esc` dismisses every Toplevel dialog.** About, Logs viewer, Diff viewer, Curate preview, Theme browser, Ignore viewer, "revert one system" picker — all now bind `<Escape>` to `destroy`, previously only the OS window-manager close box would dismiss them.
- **GUI: `Return` in the Verify-DAT entry triggers Verify.** Matches the existing behaviour of the Global Search entry; the Verify-DAT entry previously required a mouse click on the Verify button after typing the path.
- **GUI: Backup Restore dropdown filters to `spindoctor-backup-*` folders only.** Pointing the backup target at a drive root (e.g. `E:\`) used to spam the dropdown with every unrelated subdirectory; now only SpinDoctor backups show up.
- **GUI: `tk.Spinbox` widgets switched to `ttk.Spinbox`.** The classic-Tk variants bypassed the dark-mode `ttk.Style` overrides, so their arrows rendered with the system's light chrome on macOS/Linux.
- **GUI: indeterminate Progressbar starts/stops with `_run_cli` / `_on_proc_done`.** See Added entry above — wires the new widget into the existing lifecycle.
- **GUI: Stop button disables itself immediately after click.** Previously it stayed armed for the ~50 ms drain delay before `_on_proc_done` fired; a frantic double-click could land on the next process before it was even spawned.
- **GUI: removed duplicate `Separator` on the Wheels tab.** Two consecutive `Separator` widgets with no content between them rendered as a slightly thicker line — visual noise, fixed.
- **GUI: `_pump_output` no longer relies on a stripped-out `assert`.** `assert proc.stdout is not None` would disappear under `python -O` (used in some PyInstaller builds) and the next iteration would throw a confusing `AttributeError` from a worker thread. Replaced with an explicit guard that posts a `DoneMarker` and returns.
- **GUI: `_READ_ONLY_COMMANDS` no longer hides the DRY RUN banner for dry-run-able verbs.** `add-system`, `add-pc-system`, `pc-rename`, and `batch-edit` were inadvertently listed there from the previous pass — they accept `--apply` and their preview output deserves the banner. Removed.
- **GUI: `curate --list-manifests` is now recognised as read-only.** It used to get a spurious "DRY RUN COMPLETE — re-run with --apply" footer even though listing manifests modifies nothing.

- **Main Menu.xml save is now atomic with a backup.** `_mm_save_order` previously called `tree.write(xml_path, …)` directly, so a power cut, full disk, or other I/O failure between starting the write and `fsync` could leave HyperSpin's top-level wheel half-written. The save path now mirrors the rest of the codebase: when `backup_before_modify` is on, copy the live file to `<name>.<stamp>.bak`, write the new content to `<name>.xml.tmp`, then `os.replace()` over the original.
- **`spindoctor doctor` (and every other read-only command) no longer shows a misleading "DRY RUN" banner in the GUI.** The Custom Command tab tagged any invocation lacking `--apply` as a dry run, even when the command itself never accepts `--apply`. Users running `doctor`, `audit`, `find-dupes`, `lint`, `theme-scan`, etc. saw "DRY RUN COMPLETE — nothing was written. Re-run with --apply to commit" — nonsense for a read-only check. Added a curated `_READ_ONLY_COMMANDS` set (matched at both verb and verb+subverb level) so the banner only fires for commands that genuinely have an apply mode.
- **GUI no longer raises `TclError` on close while a command is mid-stream.** `_drain_queue` rescheduled itself with `self.root.after(50, …)` but the pending callback fired on a destroyed root after the user closed the window, dumping a traceback to stderr. The `after` id is now tracked and cancelled in a `WM_DELETE_WINDOW` handler.
- **Corrupt `config.json` no longer silently overwrites itself with defaults.** `load_config()` now copies the unreadable file to `config.corrupt-<stamp>.json` and prints a warning to stderr before falling back to defaults — previously the next `save_config()` call would erase the hand-edited values without a trace.
- **`config set` now validates numeric ranges at write time.** Setting `match_threshold=99.0`, `max_concurrent_downloads=-5`, or any other out-of-range numeric value was silently accepted and only surfaced as a confusing failure deep inside a download/match loop later. Range checks now produce a clear error from the CLI immediately.
- **`_jpeg_dimensions` reads chunked instead of truncating at 64 KiB.** High-resolution progressive JPEGs (large EXIF / comment segments before the SOF marker) reported `width=None, height=None` in the Inspect tab because the SOF sat past the 65 536-byte buffer. The reader now walks segment markers via `seek()`, so the inspect/preview/audit columns work for any well-formed JPEG.
- **MP4 box walker handles 64-bit "extended-size" atoms correctly.** Big recordings (>4 GiB) use `size=1` with an 8-byte trailing length, but the recursion stepped 8 bytes past the type instead of 16 — the inner walk landed on garbage and `_duration_mp4_native` returned `None`. The header length is now computed per atom.
- **`_compat.et_indent` no longer relies on a leaked for-loop variable.** The Python 3.8 fallback indented the last child with `child.tail = i` after a `for child in elem:` loop, suppressed by `# noqa: F821`. Replaced with an explicit `last_child` accumulator so the polyfill is well-defined regardless of loop-variable persistence semantics.
- **`HyperspinDatabase.load` cleaned up redundant `except (ET.ParseError, Exception)` clause.** The tuple unconditionally caught both, then ran `isinstance` re-dispatch inside the handler — replaced with two separate `except` clauses for clarity.

### Changed

- **GUI hard-coded `Consolas` / `Menlo` font references replaced with `TkFixedFont`.** Three widgets (theme viewer, helper-script panel, scheduler help text) were pinned to a literal family and therefore bypassed the View → UI scale knob. They now use the named font alias that resolves to the platform monospace default *and* honours the scale setting.
- **GUI run-history switched from `list` + `pop(0)` to `collections.deque(maxlen=200)`.** Append-and-evict is now O(1) at both call sites, and the explicit `if len(...) > 200: pop(0)` blocks went away.
- **Added `spindoctor.fileinfo.reset_ffprobe_cache()`.** The module-level `_ffprobe_ok` flag is set once per process; tests that patch `subprocess.run` to simulate a missing/present `ffprobe` would otherwise poison every later test in the same process. The reset is also useful from the GUI after a user installs ffmpeg without restarting.

### Tooling

- **Tests: 29 new GUI cases covering `_is_read_only_invocation`** across read-only verbs, multi-token forms (`mainmenu show`, `fav list`, `curate --list-manifests`), and dry-run-able verbs that must *not* be flagged read-only.
- **New tests: 88 cases across `tests/test_config.py`, `tests/test_health.py`, `tests/test_fileinfo.py`, `tests/test_compat.py`.** The `health` (`doctor`) and `fileinfo` (`inspect`, `preview`, `audit` columns) modules previously had zero coverage; now every individual check plus the full orchestration path is exercised, including the destructive `check_match_cache --fix` branch. Total suite: 473 → 561 tests, still under 2 s.
- **`tests/test_themes.py::test_list_manifests_sorts_newest_first` no longer sleeps 1.1 s.** The test was using filesystem mtime second-resolution as a synchronization primitive; replaced with an injected `datetime.now()` shim and explicit `os.utime` calls. Shaves >1 s off every CI run.

---

## [1.9.1] - 2026-05-17

### Fixed

- **GUI crash on Windows: `_tkinter.TclError: bad event type or keysym "grave"`.** `_build_layout` called `root.bind_all("<Control-grave>", …)` for the Ctrl+\` Output-panel toggle. The X11 keysym `grave` (backtick) isn't present in the Tcl/Tk that ships with Python 3.8 on Windows — which is the exact interpreter PyInstaller bundles into the frozen cabinet exe — so the binding raised `TclError` and the whole GUI failed to construct before the main window appeared. CI ran on Python 3.12 / Windows whose newer Tk *does* know `grave`, so the bug slipped through. Introduced `_safe_bind_all`, a defensive wrapper around `root.bind_all` that swallows `TclError` so a missing keysym never crashes startup, and routed every shortcut binding (`Ctrl+1..9`, `Ctrl++/-/=/0`, `Ctrl+KP_Add`, `Ctrl+KP_Subtract`, `Ctrl+\``) through it. The Ctrl+\` binding additionally tries three keysym aliases (`grave`, `quoteleft`, `asciigrave`) so it lands on whichever the running Tk recognises.

### Tooling

- **CI: GUI smoke test now runs on Python 3.8.10 / Windows** (the build-smoke job) in addition to the existing 3.12 matrix. This is the exact Python/Tcl/Tk combo the released exe ships with, so keysym / option-table differences between bundled-Tk versions surface at PR time instead of via end-user crash reports. The v1.9.0 → v1.9.1 keysym bug would have failed this step.
- **Test: `test_gui_survives_missing_keysym_in_bind_all`** monkeypatches `tk.Misc.bind_all` to reject "grave"-style keysyms and asserts the GUI still constructs — a portable regression guard for the whole class of bug, runnable on any platform with a display.

---

## [1.9.0] - 2026-05-17

### Added

- **GUI dark mode (always on, no toggle).** The whole window now uses a hand-picked dark palette (`#1e1e1e` background, `#dcdcdc` primary text, `#007acc` focus / accent, `#094771` selection) applied through a combination of `ttk.Style` overrides (under the `clam` theme — the only stock theme that fully respects custom backgrounds) and `option_add` defaults for the non-themed classic-Tk widgets (`Menu`, `Listbox`, `Text` / `ScrolledText`, `Canvas`, `PanedWindow`, `Toplevel`, `Entry`). Every hard-coded `#444` / `#666` / `#888` / `gray` foreground in the codebase was redirected to two palette-aware constants (`_FG_DIM`, `_FG_DIMMER`) so subdued / disabled-look text stays readable on dark. The macOS native menubar still uses the system appearance — that's an OS-level limitation Tk can't override.
- **GUI right-click context menu on every text input.** Right-click (or `Button-2` on legacy macOS, `Control-click` on macOS trackpads) in any `Entry` / `Text` / `ScrolledText` widget surfaces a Cut / Copy / Paste / Select-All menu — Setup paths, scraper credentials, output panel, log viewers, every existing field. Read-only widgets get Copy + Select-All only; masked password fields suppress Copy/Cut so right-click can't trivially bypass the mask. Attached via a post-construction tree walker so new tabs pick this up for free.
- **GUI eyeball toggle on masked credential fields.** A `Show` / `Hide` button next to each password / API-key entry on the Setup tab flips `show="*"` on the entry so users can verify what they pasted. Covers ScreenScraper password and TheGamesDB API key — the only two masked fields in the GUI.
- **GUI `Test credentials` button on the Setup tab.** New module-level `verify_screenscraper()` and `verify_thegamesdb()` helpers in `spindoctor.scraper` make a single authenticated probe (`ssuserInfos.php` and `Games/ByGameName` respectively) and report pass/fail with a status line. The Setup tab runs both on a worker thread (so the UI stays responsive), renders a ✓ / ✗ summary directly under the credential rows, and leaves a "skipped" line for whichever credential isn't filled in. Catches bad keys before the first `fetch-meta` run.
- **GUI UI scale (View → UI scale + keyboard shortcuts).** Persisted `ui_scale` preference between `0.6` and `2.0`, applied at startup via `tk scaling` and to all named system fonts (`TkDefaultFont`, `TkFixedFont`, `TkMenuFont`, ...). View menu has preset radio entries at 0.8× / 0.9× / 1.0× / 1.1× / 1.25× / 1.5×; `Ctrl++` / `Ctrl+-` step by 0.1, `Ctrl+0` resets to 1.0×. Cabinet owners on 1280×720 can now fit the whole tab on screen at 0.9× without scrolling. Mid-session changes only resize the named fonts (live), since Tk's `tk scaling` is only reliably applied before widget construction.
- **GUI collapsible Output panel.** Status-bar button (`Hide output` / `Show output`), View menu checkbutton (`View → Show output pane`), and `Ctrl+\`` keyboard shortcut all toggle the bottom Output panel. State persists across restarts. Hides via `PanedWindow.forget()` and restores the previous sash position on re-show.
- **GUI window icon.** A chibi arcade-cabinet mark (cream cabinet, retro-game CRT, classic joystick + four buttons) authored as `scripts/icon-source.png` and downsampled by `scripts/make_icon.py` into `spindoctor/assets/icon.png` (256×256) and `spindoctor/assets/icon.ico` (multi-resolution 16 / 24 / 32 / 48 / 64 / 128 / 256). Loaded via `iconbitmap` on Windows and `iconphoto` elsewhere; missing-asset path is non-fatal. Assets ship in the wheel via `[tool.setuptools.package-data]`.
- **Two new config keys.** `ui_scale` (float, 0.6–2.0, default 1.0) and `output_visible` (bool, default true) persist the GUI's View-menu preferences across restarts.

---

## [1.8.0] - 2026-05-17

### Added

- **GUI Tk-construction smoke test (CI guard).** `tests/test_gui.py::test_gui_constructs_against_real_tk` actually instantiates `_SpinDoctorGUI` against a real `Tk()` root and asserts all 15 tabs build. CI installs `xvfb` + `python3-tk` on Linux runners and wraps pytest with `xvfb-run -a`; Windows runs unwrapped. The smoke catches the whole class of "GUI crashes on launch" regressions (the v1.7.0 `_output` AttributeError and the v1.7.2 `-foreground` TclError would both have failed this test at PR time).
- **GUI Setup tab unsaved-changes indicator.** Editing any field on the Setup tab — paths or scraper credentials — flips the Save button label to `Save configuration *`. Switching tabs without saving used to silently lose the change. The label clears on a successful save.
- **GUI Ctrl+1..9 tab shortcuts.** Press Ctrl+1 through Ctrl+9 to jump to the first nine notebook tabs from any focused widget. With 15 tabs, this saves a lot of clicking — especially on touchscreen cabinets.
- **GUI Copy output button.** A new Copy output button in the bottom status bar (next to Clear / Stop) copies the entire Output panel to the system clipboard. Mirrors the Logs tab's existing copy pattern.
- **GUI status-bar run summary.** When a command finishes the status bar reports the command name, result, and elapsed wall-clock — e.g. `doctor — OK in 3.2s.`, `migrate — FAILED (exit 1) in 1m12s.`, `audit — dry run OK in 0.4s. View results in Output…`. Uses `time.monotonic()` so a wall-clock adjustment during a long migration doesn't skew the displayed elapsed.
- **GUI startup health checks.** `_SpinDoctorGUI.__init__` now runs `Config.is_valid()` and a `resolve_cli_command("spindoctor")` probe before the status bar lands on "Ready.", so missing paths or a misplaced CLI binary surface at first paint instead of on the user's first Run click.
- **GUI `Compare to live` button on Backup & Restore tab.** Exposes the existing `spindoctor diff <backup>` subcommand (CLI-only since v1.5.0) alongside Show backup info and Restore backup. Same picker, read-only command, no Apply check.
- **GUI Batch-edit panel on Metadata & Media tab.** A minimal panel covering the 80% case for `spindoctor batch-edit`: one filter clause, one set clause, optional CSV report path, using the existing System selector and shared Apply checkbox.

### Fixed

- **GUI Curate tab `_tkinter.TclError: unknown option "-foreground"`.** `_build_curate_tab` passed `foreground="#888"` to `ttk.Checkbutton` to grey out the "unsafe" cleanup categories. `ttk.Checkbutton` has no `-foreground` constructor option — that's style-only on every ttk widget except `ttk.Label` / `ttk.Entry`. Launching v1.7.2 raised the TclError before the window painted. Configured a named `Unsafe.TCheckbutton` style in `__init__`; same visual result, no crash.
- **GUI `_refresh_systems` combo defaults inverted.** The condition `default and default not in systems` meant LEDBlinky / Tools combos defaulted to `'MAME'` / `'Toolkit'` even when those systems weren't configured, producing invalid argv on Run. Flipped to `default if default in systems else systems[0]`.
- **GUI Main Menu Add / Remove had no safety prompt.** Both subcommands rewrote `Main Menu.xml` on every click with no dry-run option and no confirmation, inconsistent with the existing safety pattern (Save Order, Curate delete, Backup Restore). Added an `askyesno` prompt before each action.
- **GUI Theme Apply blocked the Tk main thread.** `themes_mod.apply_plan` ran synchronously, freezing the entire window for large packs (sometimes minutes). Moved to a daemon worker thread; results marshalled back via `root.after(0, …)` so widget calls stay on the main thread. Curate Apply (`curate_mod.apply_curation`) got the same treatment.
- **GUI 'Revert just <SYSTEM>' raw traceback on manifest error.** `themes_mod.list_systems_in_manifest` was imported and called without exception handling, so any failure leaked a Python traceback to stderr instead of a messagebox. Wrapped in try/except → `messagebox.showerror`.
- **GUI inflated elapsed-time after a failed launch.** When `subprocess.Popen` raised `OSError` (binary missing, permission denied, etc.), `_run_cli`'s OSError handler bailed without clearing `_run_started_monotonic` / `_run_label`. The next successful run's `_on_proc_done` then picked up the stale monotonic timestamp and reported an inflated `OK in 142s` for a run that took 2s. Clear both before returning.
- **GUI dead code: unused `Config` import in `spindoctor/gui.py`** and seven unused imports across the test suite (`PreviewItem`, `EMULATOR_MAP`, `json`, `pytest` ×2, `Path` ×2) removed. No behavioural change; keeps pyflakes clean.

---

## [1.7.2] - 2026-05-17

### Fixed

- **`pyproject.toml` version metadata back in sync.** `pyproject.toml` had been stuck at `version = "1.6.0"` since the v1.6.0 release — both v1.7.0 and v1.7.1 bumped `spindoctor/__init__.py` but missed the project metadata. As a result `pip show spindoctor` reported `1.6.0` while `spindoctor --version` reported `1.7.x`. Bumped `pyproject.toml` to match `__version__`. No code changes.

---

## [1.7.1] - 2026-05-17

### Fixed

- **GUI launch crash on v1.7.0.** Starting `spindoctor-gui` raised `AttributeError: '_SpinDoctorGUI' object has no attribute '_output'` before the window painted. The Main Menu tab's builder (added in v1.7.0) calls `_mm_refresh()` during construction, which writes to the Output panel — but the panel widget was created *after* the tab-add block in `_build_layout`. Hoisted `self._output` and `self._status_var` creation to before the tab loop so any tab builder can safely call `_append_output` / `_set_status` at construction time. No visible layout changes.

---

## [1.7.0] - 2026-05-09

### Added

- **GUI status-bar feedback improvements.** Four gaps where the UI went silent after an action are now closed: (1) The "Reload list" button in the Audit & Doctor tab writes "Reloaded N system(s)." to the status bar on success, or "No systems found — check paths in the Setup tab." when config is incomplete; (2) The "Full metadata refresh" chain writes "Full metadata refresh complete." to the status bar when all three steps finish, making the end state visible without switching to the output panel; (3) Removing entries from the Ignore list viewer now writes "Removed N entry/entries from '<system>'." to the status bar immediately after the list refreshes; (4) All eight Diagnose tab scan buttons (Find duplicate ROMs, Find misplaced ROMs, etc.) now write "Scan complete — see output for results." to the status bar on exit 0, or a brief error note on non-zero exit.

- **Version bump to 1.6.0.** `spindoctor/__init__.py` was stuck at `1.3.0` — bumped to `1.6.0` to match the latest CHANGELOG release so `spindoctor --version` and the GUI title bar report the correct version.
- **Docs: accuracy pass.** `docs/standalone-tools.md` updated to describe the current Wheels tab (checkboxes + "Refresh selected") instead of the old button layout; `docs/images/.gitkeep` screenshot briefs updated to match current UI (wheels tab, setup tab with scraper credentials).

- **Docs: GUI tab tour updated.** `docs/windows-binaries.md` and `README.md` updated to reflect all GUI changes since v1.6.0: scraper credentials in Setup tab, Wheels checklist, Main Menu interactive Treeview, Metadata & Media type checkboxes and Full refresh button, Curate per-category cleanup checkboxes, Migrate systems multi-select Listbox and manifest dropdown, Backup Scan feedback. The README "15 dedicated GUI tabs" summary now describes current controls rather than pre-v1.6.0 ones.

- **GUI scraper credentials in Setup tab.** ScreenScraper username, ScreenScraper password, and TheGamesDB API key fields have been added to the Setup tab below the path fields. Password and key fields are masked (`***`). Values are persisted to `config.json` alongside the path settings and are used automatically by `spindoctor fetch-meta` and `spindoctor fetch-media`.
- **GUI Main Menu interactive reorder table.** The Main Menu tab now shows the live system order as a scrollable, selectable table (Treeview). Select any row then click Move Up or Move Down to reposition it, Toggle Visible to flip the enabled flag, and Save Order to write all changes to `Main Menu.xml` in a single operation. A Refresh button reloads the current file. Sort (alpha / manufacturer / year) and Add / Remove remain as separate controls.

### Changed

- **GUI system fields are now dropdowns.** Every free-text "System" entry across all tabs has been converted to a `Combobox` pre-populated from the cabinet's detected system list. Affected tabs: Metadata & Media, Main Menu, Diagnose (verify-against-DAT), Curate (system picker and ignore-list picker), LEDBlinky, Lightgun, and Tools. The single `_refresh_systems()` call now updates all pickers at once — no more typing system names by hand.
- **GUI media types → checkboxes.** The free-text "Types" field in Metadata & Media → Fetch media is now a row of checkboxes (wheel, background, snap, video, trailer, title, theme, fade, sound). `wheel` and `background` are checked by default. Leaving all unchecked sends no `--types` flag, using the project default.
- **GUI curate regions → checkboxes.** The free-text "Regions" field in Curate is now a row of checkboxes for the 11 most common regions (USA, World, Europe, Japan, Korea, Brazil, Australia, Spain, France, Germany, Italy). No region checked = use config default.
- **GUI Systems tab "Old name" → dropdown.** The rename-PC-system "Old name" field is now a readonly `Combobox` pre-populated from detected systems, consistent with all other system pickers.
- **GUI numeric fields → spinners.** Two free-text integer inputs are now constrained `Spinbox` controls: Curate "Older than (days)" (range 1–365) and Tools "Delay after log-on" (range 0–60 minutes).
- **GUI Migrate systems filter → multi-select list.** The free-text comma-separated "Systems filter" field in the Migrate tab is now a scrollable multi-select `Listbox` pre-populated from detected systems. Select individual systems to restrict the migration; nothing selected = migrate all. Select All and Clear buttons are provided.
- **GUI tab-level status badges.** Each notebook tab now shows a status glyph appended to its label: `⟳` while a command is running on that tab, `✓` after it exits cleanly, and `✗` if it exits with an error. The badge reflects the last command launched from that tab and persists until the next command clears it, making it easy to see at a glance which tabs have completed or failed work without switching tabs.
- **GUI Full metadata refresh button.** A single "Full metadata refresh" button at the bottom of the Metadata & Media tab chains `fetch-meta → fetch-media → update-db` in sequence, respecting all current tab settings (system selector, Apply toggle, type checkboxes, region/orphan options). The chain stops and reports the exit code if any step fails.
- **GUI safety confirmations and UX hints.** Four improvements to prevent accidental data loss: (1) Main Menu "Save Order" now asks for confirmation before overwriting `Main Menu.xml`; (2) Curate "Run curate" with action=delete + Apply now requires an explicit "are you sure?" confirmation explaining the operation is permanent; (3) Backup "Restore" with Apply now requires confirmation before overwriting files; (4) Curate action selector now shows an inline hint distinguishing archive (reversible) from delete (permanent). Additionally: Main Menu Move Up / Move Down / Toggle Visible now display a status-bar message when no row is selected instead of silently doing nothing, and the Curate interactive preview window now shows a legend explaining the ☑/☐ glyphs and how to toggle them.
- **GUI smarter field selectors.** Three previously free-text fields replaced with smarter controls: (1) Migrate undo manifest is now a `Combobox` populated from `~/.spindoctor/migrations/` via a Refresh button, with "latest" always at the top; (2) Lightgun DemulShooter target is now a `Combobox` listing all known `-target` values (`mame`, `demul07a`, `model2`, `supermodel`, `lindbergh`, `flycast`, `chihiro`, `dolphin`, `ringedge2`, `globalvr`) — leave blank to auto-detect; (3) Backup restore path is now a `Combobox` with a Scan button that reads the configured backup target directory and lists all available backup subfolders, with Browse still available for paths outside the target.
- **GUI cleanup category checkboxes.** The Cache cleanup section in the Curate tab now shows individual checkboxes for all 13 cleanup categories instead of a static hint label. The 9 safe categories (Scraper API responses, Match decisions, Media picker decisions, PC/Steam title confirmations, MAME -listxml cache, Preview thumbnails, Interrupted downloads, Misplaced-ROM reports, Audit CSV exports) are pre-checked. The 4 unsafe categories (Migration undo manifests, Restructure undo manifests, HyperSpin DB backups, LEDBlinky file backups) are unchecked with a warning that selecting them removes recovery options. A "Reset to defaults" button restores the original selection. The "Older than (days)" spinbox now defaults to 30 (previously empty) with a `(0 = any age)` label.
- **GUI Wheels tab → checklist.** The three individual Refresh buttons in the Wheels tab (Favorites, Recently Played, Most Played) are replaced by checkboxes (all pre-checked) plus a single "Refresh selected" button, making it easy to refresh any combination in one click. The run sequence shows "Step N/3: <wheel>…" in the status bar.
- **GUI multi-step progress indicators.** The "Full metadata refresh" button (fetch-meta → fetch-media → update-db) and the Wheels "Refresh selected" sequence now display a step counter ("Step 1/3: fetch-meta…") in the status bar so the user can see which stage is running in a chained operation.
- **GUI Backup Scan feedback.** The Scan button in the Backup & Restore tab now writes "Found N backup(s) in <folder>" to the status bar after successfully populating the restore dropdown, instead of silently updating the list.

## [1.6.0] - 2026-05-08

### Added

- **GUI draggable output panel.** The tab notebook and Output panel are now separated by a vertical `PanedWindow` sash. Drag the divider up to give the output area more room — useful on 1024×768 / 1280×720 arcade screens where the default height can be too short to read full command output. On window resize the notebook absorbs extra space and the output panel holds its dragged size; the output panel cannot be collapsed below 60 px.
- **GUI prominent pane dividers.** All horizontal `PanedWindow` sashes (Logs tab run-list / output-viewer split, and the View logs & manifests… tree / JSON-viewer split) are now rendered as a 6 px raised bar instead of the nearly-invisible theme default, making them easy to spot and grab on small or low-DPI screens.

### Fixed

- **GUI status bar always visible.** Switched the root-window layout from `pack` to `grid` so the status bar (Stop button, Clear output, status text) is guaranteed its natural height in row 1 (`weight=0`). Previously, `tk.PanedWindow` with `expand=True` could race with the `side=bottom` bar for remaining space and push the bar off-screen — particularly noticeable on smaller arcade cabinet resolutions.
- **GUI dialogs fit the screen.** All seven `Toplevel` dialogs (Logs & Manifests, Diff viewer, Theme browser, Theme apply, Curate preview, Ignore list viewer, Revert system) now cap their initial size to `screen_width − 40` × `screen_height − 80` via a shared `_fit_geometry()` helper. Previously the Theme browser (1080 px) and Curate preview (1100 px) were wider than a 1024-wide arcade monitor, clipping their right edge off-screen.

## [1.5.0] - 2026-05-08

### Added

- **GUI Logs tab.** New tab keeping a per-run timeline of every command since the GUI was launched, newest first. Tree on the left (Status / Started / Command columns); read-only viewer on the right showing the full output of the selected row. Each row tags as `DRY-RUN` (no `--apply`), `OK` (applied + exit 0), `FAIL <code>`, or `running`. Buffer caps at 200 entries with FIFO eviction so a long session doesn't leak memory. Buttons for Refresh, Copy selected output, and Clear in-memory log. Closes the "I just ran a dry-run, where did the output go?" gap — the bottom Output panel only shows the *current* run, the Logs tab indexes everything.
- **GUI dry-run banners + status messages.** Every dry-run command (anything without `--apply`) now emits an explicit `=== DRY RUN ===` opening banner in the Output panel, a `=== DRY RUN COMPLETE (exit N) — nothing was written. Re-run with --apply to commit. ===` closing banner on exit, and a status-bar message that reads `Dry run finished — nothing changed. View results in Output or the Logs tab.` Real applies stay quiet (no banner) so per-command success messages aren't drowned out.
- **GUI vertical scrollbar on every tab.** Each tab now lives inside a Canvas + always-visible Scrollbar so cabinet owners on smaller screens (1024×768 / 1280×720) can still reach widgets that overflow the window. Mouse-wheel scrolling works while the cursor is over the tab content; bind/unbind on Enter/Leave keeps the wheel from fighting with other scrollables (the Output panel, the Logs viewer).
- **GUI theme-apply Plan results now stream to Output panel and Logs tab.** Previously the "Plan" button in the Apply replacement pack… dialog showed a swap table only inside the Toplevel and discarded it when the window closed. It now mirrors the full swap table to the Output panel with `=== DRY RUN ===` banners and creates a `DRY-RUN`-tagged row in the Logs tab timeline, so the plan is accessible after the dialog closes and survives the next command.
- **`spindoctor theme-pack-create <DIR>` — inverse of `theme-apply`.** Snapshot the cabinet's current `Frontend / Special A / Special B` art into a directory tree shaped like a community pack. The output is accepted directly by `theme-apply` so users can back up before installing a swap, share their setup, or migrate themed art alongside a library migration. `--target` narrows the snapshot to one scope (`frontend`, a system name, or `all`). The cabinet itself is never modified — reversible only in the trivial sense that it just writes to a target directory.
- **`spindoctor theme-apply --systems "MAME,Sega Naomi"` — multi-system targeting.** `--target` previously accepted only one system at a time; `--systems` accepts a comma-separated list and applies the swap to all of them in one run, mirroring how `migrate --systems` already works. The resulting manifest records each file's scope so per-system undo still works. `--systems` overrides `--target` for the system-name filter when both are given.
- **`spindoctor theme-apply --revert-system <SYSTEM>` — per-system partial undo.** When a multi-system pack swap looks wrong on only one wheel, the previous only option was full undo + re-apply minus that system. `--revert-system` reads the manifest (paired with `--undo`; defaults to `latest`) and restores only the files belonging to the named system's Special A/B buckets, leaving every other wheel untouched.
- **`spindoctor diff <BACKUP_FOLDER>` — compare a backup to the live cabinet.** Given a `spindoctor-backup-…/` folder, lists which files are added, deleted, or modified in each component since the snapshot was taken. Comparison is size + modification time (fast; no full hash). `--component` limits the report to one component. Read-only; cabinet and backup are never modified. Closes the "what changed since last week?" gap cabinet owners have had since backup was added.
- **GUI Undo Center "Show diff" button.** New button on the Logs & Manifests viewer renders the selected manifest's recorded changes as a before/after table in a new window — Source/Target/Scope/Bucket columns for theme-apply manifests, Component/From/To for migration manifests, and a generic key/value fallback for other types. Replaces squinting at raw JSON for the two most common manifest formats.
- **GUI Logs viewer per-system theme revert.** New "Revert just \<SYSTEM\>…" button on the Logs & Manifests viewer, enabled for Theme swaps manifests. Opens a listbox populated from the manifest's unique `target_scope` values, then runs `theme-apply --undo <path> --revert-system <picked>` so a multi-system swap can be partially rolled back without touching every wheel. The full Undo this run button remains for whole-run reversal.

## [1.4.0] - 2026-05-08

### Added

- **`spindoctor theme-apply` + GUI "Apply replacement pack…".** Swap HyperSpin frontend overlay art (controller-hint glyphs etc.) for a community pack with one command. Walks a source folder, matches each filename against the cabinet's Frontend / Special A / Special B targets, and copies the source over each match. Every overwritten file is backed up under `~/.spindoctor/themes/theme-apply-<timestamp>/backup/` and recorded in a JSON manifest, so the whole run is reversible — either via `spindoctor theme-apply --undo latest` or one-click via the GUI's Logs & Manifests viewer (Theme swaps category + Undo this run button). `--target` narrows the swap pool to `frontend`, a specific system, or `all` (default). Dry-run by default; pass `--apply` to commit. New GUI button on the Theme browser opens a Plan / Apply window with a source-folder picker, scope dropdown, and a preview tree before committing.
- **`spindoctor theme-scan` + GUI theme browser.** Read-only inventory of HyperSpin's frontend overlay art — the controller-hint glyphs that appear at the bottom of the cabinet UI. Walks `<hyperspin>/Media/Frontend/Images/` and every per-system `Media/<system>/Images/{Special A,Special B}/` folder (the locations HyperHQ → Special A/B writes to). New `spindoctor.themes` module + `theme-scan` CLI command (`--system`, `--keyword`, `--output` CSV) ships in every deploy form (CLI / pip / frozen exe). New `File → Browse HyperSpin themes…` GUI window renders the inventory as a sortable Treeview with a live filter box; double-click a row to open the file in your OS image viewer, or click "Open containing folder" to jump to the directory in Explorer. Detects the "your glyphs are baked into a Flash .swf" case and warns instead of pretending to handle it (SpinDoctor can't edit SWFs).
- **GUI Ignore-list viewer.** New "View / un-ignore…" button on the Curate tab's Ignore section opens a Toplevel with a system dropdown (every system that has at least one ignored entry, plus a `_global  (cross-system)` bucket) and a multi-select listbox of every ignored ROM. Pick one or more, click "Remove selected" — `cfg.remove_ignore()` runs and `~/.spindoctor/config.json` is saved immediately. Closes the loop with `audit` / `fetch-meta` / `update-db` skipping logic: cabinet owners can finally see *what's currently being skipped* and un-ignore something with a click instead of grepping the JSON.
- **GUI Curate preview (interactive diff).** New "Preview (interactive)…" button on the Curate tab opens a Toplevel with the curate plan rendered as a tree — one parent row per multi-variant title, the kept ROM as a child, plus each retire candidate with a `☑ / ☐` checkbox. Space or double-click toggles a row, vetoing that file's retirement. Apply runs `curate.apply_curation` directly against the (possibly filtered) groups, bypassing the CLI so per-row vetoes don't have to round-trip through argv. Confirmation dialog before destructive action; archive writes a manifest the Undo Center can reverse, delete still has no undo. Worker thread keeps the GUI responsive during the initial scan.
- **GUI Undo Center.** New "Undo this run" button on the Logs & Manifests viewer that runs the matching `--undo` command for the selected manifest — `migrate --undo <path>`, `curate --undo`, `batch-edit --undo <path>`, `rename --undo <path>`, `media-scan --undo`. For categories whose CLI always reverses the most-recent run (curate, media-scan), a "this will undo the *most recent* run, not the manifest you selected" confirmation fires when you pick an older row, so you don't accidentally reverse the wrong one. Closes the loop with the existing viewer: tree on the left, JSON on the right, one click to roll back.
- **GUI gains three more tabs: Metadata & Media, Curate, Systems.** Brings the GUI total to 14 tabs and covers the rest of the high-traffic CLI surface that was previously Custom-Command-only.
  - **Metadata & Media** — wraps `fetch-meta` (with `--auto-best` / `--all-games`), `fetch-media` (with comma-separated `--types` and `--overwrite`), `media-scan` (source-folder picker + copy/move/link action), `update-db` (with `--remove-orphans` / `--strip-variant-tags`), and `generate-config`. Shared system field + Apply checkbox at the top.
  - **Curate** — wraps `curate` (region preferences, prefer-revision, archive vs delete, dry-run by default) plus a button row for `curate --undo` and `curate --list-manifests`. Companion sections for `cleanup` (categories / audit / run with optional --older-than days) and the `ignore` add/remove/list lifecycle.
  - **Systems** — wraps `add-system` (with `--no-system-media` / `--no-game-media` toggles), `add-pc-system`, and `pc-rename`, plus quick buttons for `systems` and `config system list`.
- **GUI Logs & Manifests viewer.** New File menu entry and Toplevel window that lists every per-run manifest under `~/.spindoctor/` (migrations, curation, edits, renames, media_imports, misplaced) — the JSON files `--undo` reads to reverse a run. Tree on the left (categorised + newest first), JSON viewer on the right, plus "Open in file explorer" / "Open ~/.spindoctor" buttons. Cabinets that lose track of "what did I do last week?" now have a click-and-look audit trail without leaving the GUI.
- **GUI checks GitHub for newer releases on launch.** New `spindoctor.update_check` module fetches the latest release tag from `api.github.com` (stdlib `urllib.request`, no third-party HTTP deps) on a background thread, so a slow / unreachable GitHub never blocks the first paint. When a newer tag is found, the status bar surfaces "Update available: vX.Y.Z" and the Output panel logs the release URL. `Help → Check for updates` runs the same check synchronously with a yes/no dialog that opens the release page on accept. Opt-out for hermetic launches via `SPINDOCTOR_NO_UPDATE_CHECK=1`.
- **GUI File / Help menu, About dialog, and on-disk shortcuts.** New menubar with `File → Open config.json / ~/.spindoctor / HyperSpin / ROMs` and `Help → About SpinDoctor`. Setup tab gains companion buttons for config.json and the SpinDoctor folder. Audit & Doctor tab gains "Open Media folder for selected system" / "Open ROMs folder for selected system" buttons so a "missing wheel" / "wrong title" audit row is one click away from the offending folder in Explorer (Finder / xdg-open on macOS / Linux). About dialog surfaces version, description, and links to the GitHub project / latest release / CHANGELOG.
- **GUI Backup & Restore tab.** New Tkinter tab wrapping `spindoctor backup create / list / info / restore`. Per-component checkboxes (default: all seven), shared target-folder picker for create/list, separate backup-folder picker for info/restore, optional label, dry-run by default with explicit Apply, plus restore-time toggles for `--use-current-paths` and `--overwrite`. Cabinet owners can now snapshot the library before a migration without dropping into `cmd.exe`.
- **GUI gains six more tabs and a Custom Command presets dropdown — most of the CLI is now click-and-go.** Cabinet owners no longer have to drop into `cmd.exe` for migrations, wheel ordering, LEDBlinky / Sinden wiring, or the read-only diagnostic suite.
  - **Custom Command** tab now ships an editable Combobox seeded with ~70 curated commands grouped by family (discovery, audit, curate, fetch, wheels, main menu, LEDBlinky, lightgun, backup, migrate, config). Default stays `--help`; unfilled `<PLACEHOLDER>` tokens get caught before launch.
  - **Migrate** tab wraps `spindoctor migrate` end-to-end: per-component checkboxes, target-root picker, optional system filter for partial roms migrations, toggles for `--keep-source` / `--verify` / `--no-update-config` / `--preserve-names`, and a separate Undo panel that pre-fills `latest` and exposes `--list-manifests`.
  - **Main Menu** tab wraps `spindoctor mainmenu`: Show / Sort (alpha · manufacturer · year) / Move up / Move down / Reorder / Hide / Show / Add / Remove with a single Apply checkbox shared by every action.
  - **LEDBlinky** tab wraps `spindoctor ledblinky`: per-system Generate (controls.ini + colors.ini), Audit coverage, Check existing INIs, and Fix INI issues — with an Overwrite toggle for community-maintained entries and dry-run by default.
  - **Lightgun** tab wraps `spindoctor lightgun`: Detect installed Sinden / DemulShooter gear, Audit per-system wiring, and Configure one system's RL INI with optional `-target` / extra-args overrides.
  - **Diagnose** tab surfaces the read-only inspectors as one-click buttons (find-dupes, find-misplaced, find-orphan-media, check-discs, lint, report, preview, stats) plus a Global Search box and a Verify-against-DAT mini-form.
  - **Tools** tab wraps `spindoctor install-tools` so the HyperSpin Tools-menu .bat helpers (Refresh Favorites / Recently Played / Most Played / Both) install with one click.
- **Wheels tab now explains HyperSpin integration.** Adds a paragraph clarifying that Most Played auto-registers in the Main Menu while Favorites and Recently Played do not, that none of the rebuilds auto-fire on cabinet startup, plus a one-click "Add wheels to Main Menu" helper and a shortcut to install the Tools-menu .bat helpers.
- **`install-tools --add-to-system <NAME>`** — install the wheel-refresh helpers as 'games' inside an existing HyperSpin wheel system (e.g. a 'Toolkit' or 'Tools' wheel) instead of (or in addition to) HyperHQ's Tools menu. Adds matching `<game>` entries to the system's database XML, writes per-game PCLauncher INIs alongside the bats, and is idempotent on re-run. Requires the target system to already exist and to use PCLauncher as its emulator.
- **GUI Tools tab gains "Auto-refresh on cabinet startup".** One-click Windows Task Scheduler integration: schedules an `ONLOGON` task with a configurable post-log-on delay (so HyperSpin / RocketLauncher can settle first) that runs Refresh Favorites + Recently Played + Most Played in sequence. Buttons for Schedule / Remove / Check task status. Falls back to manual setup instructions on macOS/Linux. New `spindoctor.autostart` module wraps `schtasks.exe` so we don't take a `pywin32` dependency in the frozen build.
- **GUI Tools tab "Install into an existing wheel system" section.** Surfaces `install-tools --add-to-system` with a target-wheel field defaulting to "Toolkit", plus inline manual-setup instructions for HyperHQ → Tools and Task Scheduler if you'd rather do it yourself.

## [1.3.0] - 2026-05-07

Windows-quality-of-life release. Fixes two papercuts cabinet owners hit on real installs and substantially speeds up CI on the Windows runner. No CLI surface changes.

### Fixed

- **GUI Browse buttons now write Windows-native paths.** The Tk file dialog returned POSIX-style separators (`D:/Arcade`) even on Windows, which leaked into `config.json` and tripped downstream path comparisons. The Setup tab now normalises every selection through `pathlib.Path` so saved configs match what every other Windows tool expects (`D:\Arcade`).
- **`spindoctor doctor` no longer crashes on cmd.exe.** The frozen exe inherited cmd's cp1252 codepage, which can't encode the Rich tree glyphs (`✓ ⚠ ✗`) that `doctor` prints — the command would `UnicodeEncodeError` mid-render. The CLI now switches the console to UTF-8 (`SetConsoleOutputCP(65001)`) and reconfigures `sys.stdout`/`sys.stderr` with `errors="replace"` *before* the Rich Console is constructed, so glyphs render correctly on modern Terminal builds and degrade gracefully on legacy consoles instead of crashing.

### Changed

- **CI is ~5× faster on PRs.** The test matrix dropped its `windows-2022 × Python 3.8` cell — Python 3.8 stdlib coverage stays via `ubuntu-latest × 3.8` and the actual frozen 3.8.10 Win 7 binary is still exercised end-to-end by the unchanged `build-smoke` job. The Windows leg of a PR now finishes in ~5 min instead of ~25 min.
- Test runs use `pytest-xdist` (`-n auto`) so the suite fans out across the runner's CPUs.
- `actions/setup-python` now caches the pip wheelhouse, keyed on `pyproject.toml` (and `build/requirements-build.txt` for the build-smoke job).

### Documentation

- New "`mame_executable` — which one if I have several?" section in `docs/configuration.md` for cabinets with multiple MAME folders (`MAME (driving)`, `MAME (gun games)(sinden)`, …). Explains that the field is only used for `mame -listxml` and that picking the newest vanilla-ish copy is the right answer — variant folders only differ in `mame.ini` / `cfg/` content, not in listxml output.

## [1.2.0] - 2026-05-07

GUI launcher release. Adds a windowed front-end so cabinet owners no longer have to open `cmd.exe` for routine setup and wheel refreshes, and threads the three install routes (binaries / pip / source-on-disk) and two usage modes (GUI / CLI) consistently through every doc.

### Added

- `spindoctor-gui.exe` — Tkinter GUI launcher bundled in the Windows release zip. Double-click to open a windowed front-end with tabs for **Setup** (config wizard), **Wheels** (one-click Favorites / Recently Played / Most Played refresh, plus Refresh All Three), **Audit & Doctor** (read-only diagnostics with a system dropdown), and **Custom Command** (free-form CLI args). Shells out to the existing CLI binaries sitting next to it — no `PATH` configuration required.
- `spindoctor.gui` Python module + `spindoctor-gui` console-script entry point so the GUI is also available from a `pip install` (`spindoctor-gui` from the shell, or `python -m spindoctor.gui`).
- GUI argument handling for `--version` / `--help` so the binary is testable on CI without spawning a Tk window.
- Documentation: every doc page (README, `docs/index.md`, `docs/installation.md`, `docs/setup.md`, `docs/windows-binaries.md`, `docs/standalone-tools.md`, `docs/troubleshooting.md`, `docs/workflows.md`, `scripts/README.md`, `build/README.md`) now surfaces the three install routes and the GUI/CLI usage modes consistently, with a route-picker table at the top of the README and `docs/index.md`.

### Changed

- `docs/windows-binaries.md` and the README quick-start now explicitly call out that double-clicking `spindoctor.exe` flashes a console window and exits — that's a CLI by design — and point users at `spindoctor-gui.exe` or `cmd.exe` instead.
- Release zip now contains five binaries (added `spindoctor-gui.exe`) and the CHANGELOG-driven release notes list it.
- `build/build_windows.py` adds the GUI as a `--windowed` PyInstaller target (CLIs stay `--console` so their pipes work when invoked from the GUI's `subprocess.Popen`).
- `docs/images/.gitkeep` now points at five GUI screenshot filenames; the previous five CLI screenshot placeholders were removed because the CLI surface is text-only and already documented inline.

## [1.1.0] - 2026-04-30

Supply-chain hardening release. No CLI surface or behaviour changes — purely build, release, and security infrastructure improvements on top of 1.0.0.

### Added — Supply-chain hardening

- `.github/workflows/security.yml` — runs Bandit (static analysis) and pip-audit (CVE scan) on every PR, every push to `main`, and weekly on Mondays.
- `.github/dependabot.yml` — weekly Dependabot scans for both pip dependencies and GitHub Actions versions.
- Release workflow now generates `SHA256SUMS.txt` next to the zip so users can verify their download with `sha256sum -c SHA256SUMS.txt`.
- Release workflow now publishes a [SLSA build provenance attestation](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds). Verify with `gh attestation verify spindoctor-windows-vX.Y.Z.zip --repo phillram/spindoctor`.
- `[tool.bandit]` in `pyproject.toml` documents which Bandit rules are skipped and why (non-cryptographic SHA-1 / MD5 use, locally-controlled XML inputs).

### Changed

- `requests` floor bumped from `2.28` to `2.32.4` (the latest 2.32.x patch release that still supports Python 3.8 — required by the Windows 7 SP1 binary build).
- All GitHub Actions in `ci.yml`, `release.yml`, `security.yml` are now pinned to commit SHAs (with the version in a comment) so a tag-rewrite supply-chain attack cannot silently swap action code. Dependabot keeps these current.

### Fixed

- Removed five unused imports surfaced by `spindoctor lint` (`shutil` in `cleanup.py`, `asdict` in `curate.py` / `media_scan.py`, `field` and `DEFAULT_LIMIT` in `playtime.py`).

## [1.0.0] - 2026-04-30

First public release. SpinDoctor is a command-line librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets — it audits ROMs, syncs HyperSpin XML, fetches metadata and media, manages cross-system Favorites / Recently Played / Most Played wheels, wires Sinden / DemulShooter for light-gun systems, and migrates entire libraries between drives.

### Highlights

- **Standalone Windows binaries** — `spindoctor.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, `spindoctor-stats.exe` ship attached to the GitHub Release. No Python install needed on the cabinet. Compatible with Windows 7 SP1, 8, 8.1, 10, and 11.
- **Dry-run by default** — every command that modifies files previews its plan unless invoked with `--apply`. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`, `tools-audit`, `find-global`, `lightgun detect`, `lightgun audit`) need no flag.
- **Reversible writes** — every destructive command writes a JSON manifest under `~/.spindoctor/<category>/` and accepts `--undo`. XML writes leave a `.YYYYMMDD_HHMMSS.bak` next to the original.
- **Replaces a graveyard of legacy tools** — Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, HyperT00ls, Don's HyperTools, Hypersearch, the CUE Renamer, plus assorted lightgun wiring scripts. `spindoctor tools-audit` inventories what's installed and tells you which command supersedes each one.

### Added — Core library management

- `systems` — list every detected system across `roms_dir` and `Databases/`.
- `audit` — compare ROM files vs. HyperSpin DB and media; reports exact + fuzzy matches, missing entries, missing media, and ignored counts; CSV export with `--report`.
- `inspect` — per-file deep-dive (image dimensions, video length, modification times) for one game or every game with issues.
- `update-db` — sync HyperSpin XML to ROM directories; adds stub entries for new ROMs, optionally removes orphans. `--strip-variant-tags` collapses `(Japan)` / `(USA)` displays.
- `fetch-meta` — download description / year / manufacturer / genre / rating / players from ScreenScraper or TheGamesDB. Cached at `~/.spindoctor/metadata_cache/` with TTL. Interactive disambiguation with cached choices; `--auto-best` to skip prompts.
- `fetch-media` — download wheels, backgrounds, snaps, videos, themes, fade images, sounds, trailers. **Resumable downloads** via HTTP Range requests — partial files survive interruptions and pick up where they left off. Concurrency-controlled, 429/503-aware retry.
- `media-add` — manually drop a local file into the right HyperSpin media slot.
- `media-scan` — inverse of `find-orphan-media`: bulk-import a folder of local media (EmuMovies pack, custom art) by fuzzy-matching against the database. `--apply` is reversible via `--undo`.
- `find-global` — search every configured system's HyperSpin database for a title. Replaces standalone Hypersearch utilities.
- `report` — read-only summary or CSV.

### Added — Editing

- `batch-edit` — set / clear / append / prepend metadata fields across many games filtered by name, genre, year, manufacturer, or `missing=<field>`. Reversible via `--undo`.
- `rename` — atomic ROM + DB entry + every media slot rename. RocketLauncher PCLauncher INIs follow. Reversible.
- `clone` — duplicate a base ROM as a hack/translation variant; ROM and media are copied (not moved); a new `<game>` entry is appended.

### Added — Library generation

- `generate-config` — generate RocketLauncher INI files and the HyperSpin Main Menu XML.
- `mainmenu` — inspect, reorder, hide, show, add, remove, sort (alpha / manufacturer / year), and interactively edit the top-level systems wheel.
- `organize` — populate genre / year / manufacturer / letter sort wheels and optionally restructure ROMs into per-game folders or multi-disc m3u playlists.
- `add-system` — bootstrap a brand-new console end-to-end: registers it in the Main Menu, creates database stub, generates RocketLauncher INI, scaffolds media folders, walks the metadata + media fetch flow.
- `add-pc-system` — same for PC / Windows / Steam libraries; recursive scanning of nested install folders, title-picker for awkward layouts, per-game PCLauncher INIs.
- `pc-rename` — re-run the PC title picker after dropping new games in.
- `migrate` — move (or copy) the entire library — or specific components — to a new drive in one shot. Updates `config.json` and writes a manifest you can `--undo`. Components: `roms`, `hyperspin`, `emulators`, `rocketlauncher`, `ledblinky`, or `all`. `--keep-source --verify` for a safe SHA1-verified copy that leaves originals intact.
- `backup` — copy any combination of library components into a dated folder on a different drive (`backup create` / `list` / `info` / `restore`). `--use-current-paths` reroutes a restore when drive letters change.

### Added — Health & integrity

- `find-dupes` — duplicate detection within a system or across systems; `--by-content` for byte-level pairing across `.zip` / `.7z` / `.rar` / `.gz` / `.chd` (the last three need `[archives]` extra).
- `find-misplaced` — flag ROMs whose extension doesn't match the folder's system; `--apply` moves each to its suggested system; reversible.
- `curate` — region & version curation: pick one canonical variant per game (configurable region preferences, latest revision); archive losers to `_retired/` (reversible) or delete (permanent).
- `find-orphan-media` — wheels / snaps / videos / themes whose game no longer exists.
- `check-discs` — validate multi-disc layouts and `.m3u` playlists.
- `verify` — verify ROM integrity against No-Intro / Redump / TOSEC DAT XMLs. Inner-content and wrapper-byte matching. Lazy hashing — files whose size doesn't appear in the DAT skip hashing entirely. `.zip` / `.gz` / `.chd` native; `.7z` / `.rar` via `[archives]` extra.
- `stats` — coverage dashboard: % matched to DB, % metadata complete, % media complete.
- `preview` — visual contact sheets and per-game cards (HTML by default; PNG via `[preview]` extra).

### Added — Custom wheels

- `fav` — cross-system Favorites wheel. Cabinet end-user can favorite from any system; the wheel pulls all games into a synthetic `Favorites` HyperSpin system, alphabetically sorted by display title, with media hardlinked from source systems. `fav sync` pulls HyperSpin's per-system F-key favorites into the cross-system store.
- `recent` — Recently Played wheel auto-derived from RocketLauncher's `Statistics.ini`. No extra hooks needed.
- `stats-report` — playtime reporting (totals, top games, per-system breakdown) and the `build-wheel` subcommand that generates a Most Played wheel.
- `install-tools` — write `.bat` wrappers HyperSpin's Tools menu can invoke directly so end-users can refresh wheels from the UI.
- **Three standalone CLIs** (`spindoctor-fav`, `spindoctor-recent`, `spindoctor-stats`) with light `argparse` entry points — fast enough to use as a Windows boot trigger without loading the full CLI.

### Added — LEDBlinky

- `ledblinky generate` / `audit` — generate `controls.ini` and `colors.ini` from MAME `-listxml`, preserving any community-maintained entries.
- `ledblinky check` / `fix` — diagnose and patch the well-known issue where HyperSpin's Search overlay crashes when LEDBlinky is installed. Fully reversible.

### Added — Light guns

- `lightgun detect` / `audit` / `configure` — wires Sinden + DemulShooter into RocketLauncher's per-system `Settings/<System>.ini` via `Pre_Launch_App` / `Post_Launch_App`. Auto-targeting for MAME, Naomi, Atomiswave, Dreamcast, Model 2, Model 3 (Supermodel), Flycast, ChiHiro, Triforce, Lindbergh, Ringedge, Global VR. Module `.ahk` files are never modified — a stock Tur build remains intact.

### Added — Maintenance

- `doctor` — self-diagnose paths, binaries, XML DB integrity, match-cache hygiene, RocketLauncher / LEDBlinky files, optional `lxml` / `ffprobe`. `--apply` runs safe idempotent repairs (prune stale cache, scaffold media folders, regen `Global Emulators.ini`).
- `tools-audit` — read-only inventory of third-party arcade tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Sinden, DemulShooter, XPadder, JoyToKey, DS4Windows, …); flags which `spindoctor` command replaces each one.
- `ignore` — per-system or global ignore lists honoured by `audit`, `fetch-meta`, `fetch-media`, `update-db`.
- `match` — manage cached metadata-match decisions made interactively during `fetch-meta`.
- `cleanup` — one-stop inventory and removal of every cache, manifest, temp dir, and `.bak` SpinDoctor produces, including stale `.part` sidecars from interrupted downloads.
- `lint` — AST pass over the SpinDoctor source itself; surfaces unused imports, bare `except:`, TODO markers, and near-duplicate function bodies.

### Added — Build & release infrastructure

- `build/build_windows.py` — PyInstaller driver producing four single-file `.exe` binaries.
- `.github/workflows/release.yml` — triggered by `v*` tag push; builds, smoke-tests, zips, and publishes a GitHub Release with the artefacts attached.
- `.github/workflows/ci.yml` — runs pytest on Linux + Windows (Python 3.8 and 3.12) and a PyInstaller smoke build on every PR.

### Compatibility

- **Operating systems** — Windows 7 SP1, 8, 8.1, 10, 11 (binaries). Windows 7 RTM (no Service Pack 1) is **not** supported. The CLI itself runs on macOS and Linux for development and testing, but the integration target is HyperSpin on Windows.
- **Python** — 3.8 or newer when installed from source. Binary releases bundle Python 3.8.10, so the cabinet doesn't need its own install.
- **Filesystems** — NTFS / ext4 / APFS for hardlink-based wheel media mirroring. FAT32 / exFAT fall back to copies via `--media-mode copy`.
- **Optional extras**:
  - `[xml]` (`lxml`) — lossless XML round-trips; preserves comments and attribute order written by HyperHQ.
  - `[archives]` (`py7zr`, `rarfile`) — `.7z` / `.rar` peeking for `verify` and `find-dupes --by-content`.
  - `[preview]` (`Pillow`) — PNG contact sheets for `spindoctor preview`.

### Security & data safety

- ROMs and BIOS files are never downloaded, by design. Source them from games and consoles you own.
- Metadata API credentials are stored in `~/.spindoctor/config.json`. Include `--include settings` in `backup create` to capture them; otherwise they're re-entered on a new install.
- Every XML write makes a timestamped `.bak` first (toggle via `backup_before_modify`). `curate --action delete` and `find-orphan-media --apply` are the only operations that aren't reversible — both prompt before acting.

### Known limitations

- Windows binaries are **not code-signed** — Windows 10/11 SmartScreen will warn the first time. Click "More info" → "Run anyway". Code signing is on the roadmap.
- `migrate` does not rewrite emulator-internal absolute paths (RetroArch's `retroarch.cfg`, PCSX2 INIs, Dolphin user folder, etc.). Re-test each emulator after a drive move.
- `fetch-media` theme / fade / sound coverage is sparse — these come from ScreenScraper only. For EmuMovies-style theme packs, drop the files into a folder and use `media-scan --apply`.
- ScreenScraper free tier is rate-limited to 500 requests/day.

[Unreleased]: https://github.com/phillram/spindoctor/compare/v1.9.1...HEAD
[1.9.1]: https://github.com/phillram/spindoctor/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/phillram/spindoctor/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/phillram/spindoctor/compare/v1.7.2...v1.8.0
[1.7.2]: https://github.com/phillram/spindoctor/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/phillram/spindoctor/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/phillram/spindoctor/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/phillram/spindoctor/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/phillram/spindoctor/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/phillram/spindoctor/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/phillram/spindoctor/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/phillram/spindoctor/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/phillram/spindoctor/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/phillram/spindoctor/releases/tag/v1.0.0
