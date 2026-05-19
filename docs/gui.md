# GUI walkthrough

The canonical reference for `spindoctor-gui` — the same window whether you launched it from `spindoctor-gui.exe` (Windows binary) or `spindoctor-gui` (pip install). Cabinet owners who'd rather click than type live here.

> ![SpinDoctor GUI showing the Setup tab and the output panel](images/gui-launcher-overview.png)
>
> *Screenshot: `spindoctor-gui` after launch, with the output panel showing a completed `doctor` run.*

## Contents

- [Launching](#launching)
- [First-run wizard](#first-run-wizard)
- [Layout primer](#layout-primer)
- [Per-tab health badges](#per-tab-health-badges)
- [Tab tour](#tab-tour)
- [Menubar](#menubar)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Find bar](#find-bar)
- [System quick-filter](#system-quick-filter)
- [Dry-run feedback](#dry-run-feedback)
- [Dark mode and right-click menus](#dark-mode-and-right-click-menus)
- [Stopping a long-running command](#stopping-a-long-running-command)

---

## Launching

| Install route | How to launch |
|---|---|
| **Windows binary** | Double-click `spindoctor-gui.exe` in the extracted folder (e.g. `C:\spindoctor\`). |
| **pip install** | Run `spindoctor-gui` from any terminal — the console script ships with the wheel. |
| **Source checkout, no install** | `python -m spindoctor.gui` from the repo root. |

The GUI is a thin wrapper — it shells out to the `spindoctor` CLI (and the three standalone wheel binaries on Windows) for every command. Anything you can do here is also available — and identical — on the command line. The GUI's job is the input form, the progress bar, and the output panel.

## First-run wizard

On the very first launch (no `config.json`, or saved config still has the placeholder `D:\…` defaults), a three-step modal opens:

1. **Welcome** — a one-sentence intro and a "Skip" / "Next" pair.
2. **Pick paths** — required: `roms_dir` and `hyperspin_dir`. Browse… buttons next to each field; drag-and-drop a folder from Explorer / Finder also fills the field.
3. **Run doctor** — runs `spindoctor doctor` inline against the just-saved paths and renders the per-check ✓/⚠/✗ summary so you can fix anything obvious before clicking Finish.

The wizard sets `first_run_complete = true` in `config.json` so it never auto-opens again. Existing installs with a valid config silently flip the flag on first launch of the 2.0 GUI so long-term users aren't pestered. **Help → First-run setup…** re-opens the wizard manually any time.

## Layout primer

A single window with a workflow-ordered tab strip across the top, a shared **Output** panel along the bottom (resizable via a draggable sash), and a status bar showing the current command + a Stop button. Every tab scrolls vertically with an always-visible scrollbar so cabinet owners on 1024×768 / 1280×720 displays can still reach widgets that overflow.

## Per-tab health badges

Each tab name carries a small badge whenever the area it covers has a problem detected by `spindoctor doctor`:

| Badge | Meaning |
|---|---|
| (none) | Area is healthy. |
| ⚠ | Warning — paths missing optional bits, scraper credentials blank, etc. |
| ✗ | Failure — required path is broken, database file unreadable, etc. |

The doctor pass runs on a worker thread on launch (doesn't delay first paint) and re-runs after every Setup save so badges stay current. Run-progress badges (⟳/✓/✗) render at the right edge so a tab can show both at once — e.g. `LEDBlinky ⚠ ⟳`.

## Tab tour

Tabs appear in workflow order: setup first, then read-only diagnostics, then curation / wheel composition, then per-system overrides and peripheral tabs, then infrastructure (Backup → Tools → Migrate) trailing into Logs / Custom Command.

### Setup

Every path-based config key in a single form, pre-populated with your current `config.json` values (or sensible Windows defaults on first run). Each row has a **Browse…** button (native folder picker) and an **Open** button (jumps to the path in Explorer / Finder to verify your choice). When `tkinterdnd2` is available (Windows binary install or `pip install spindoctor[gui]` / `[all]`), drag a folder from Explorer / Finder onto any path field to fill it in.

Below the path fields, a **Scraper credentials** section stores your ScreenScraper username, ScreenScraper password, and TheGamesDB API key — password and key fields are masked (`***`) with a Show/Hide eyeball toggle. A **Test credentials** button pings both endpoints and reports ✓ / ✗ inline before you click Save.

Click **Save configuration** to validate and write everything to `config.json` in one step. CLI equivalent: `spindoctor config init`.

> ![Setup tab populated with cabinet paths](images/gui-launcher-setup-tab.png)

### Audit & Doctor

The cabinet's "is everything OK?" diagnostic surface. Pick a system from the dropdown to run a per-system audit, or click **Run doctor** / **Tools audit** / **Audit all systems** for library-wide checks. None of these write to disk.

A **Preflight check…** button (added in 2.0) chains `doctor` → `tools-audit` → `audit --all` end-to-end with a determinate "step N of 3" progress bar, then pops a verdict messagebox at the end (green "Cabinet is ready" / yellow "N issues found"). Continues past failures so a partial cab state is still informative. Designed for the "I'm taking the cab to a LAN event tomorrow" moment when running three commands by hand is error-prone.

Audit options: a **Report CSV (optional)** entry + Browse… button feeds `audit --report`; checkboxes for `--no-media` (skip media checks for faster runs) and `--detailed` (richer per-file output). Both *Audit selected system* and *Audit all systems* use the same options.

**Open Media folder for selected system** and **Open ROMs folder for selected system** buttons jump straight to `<hyperspin>\Media\<system>\` or `<roms_dir>\<system>\` — useful when an audit row reports "missing wheel" and you want to eyeball the offending folder.

CLI equivalents: `spindoctor audit`, `spindoctor doctor`, `spindoctor tools-audit`.

> ![Audit & Doctor tab with the system dropdown expanded](images/gui-launcher-audit-tab.png)

### Diagnose

One-click read-only inspectors that don't change anything on disk: **Find duplicate ROMs**, **Find cross-system dupes**, **Find misplaced ROMs**, **Find orphan media**, **Check disc-set consistency**, **Lint**, **Generate report**, **Preview HyperSpin XML**, **Stats**. Each button writes "Scan complete — see output for results." to the status bar.

Plus a **Global Search** box (`spindoctor find-global`), a **Verify-against-DAT** mini-form (`spindoctor verify --system X --dat …`), and an **Inspect** form (system dropdown + optional game name) for the deep-dive companion to audit.

### Metadata & Media

Fetch metadata + media from ScreenScraper / TheGamesDB and sync the database XML. Shared system dropdown at the top, plus an Apply toggle.

Four sections wrap `fetch-meta` (with `--auto-best` / `--all-games` / `--no-cache`, plus a **Source** dropdown picking `screenscraper` / `thegamesdb` / config default, and a **Threshold** entry that overrides the project-default fuzzy-match floor — client-side validated 0.0–1.0), `fetch-media` (media-type checkboxes — wheel, background, snap, video, trailer, title, theme, fade, sound — defaulting to wheel + background, plus `--overwrite`), `media-scan` (source-folder picker + copy/move/link action), and `update-db` (with `--remove-orphans` / `--strip-variant-tags`).

**Multi-system fetch-meta** (added in 2.0): the **Pick subset…** button opens a modal multi-select Listbox of every configured system. Ticking subsystems opens a multi-select picker; the **Run on subset…** button chains `fetch-meta --system X` once per picked system (with a confirmation dialog showing system count + dry-run / apply mode), aborting on the first non-zero exit code. Designed for cabinets with 20+ systems where the user wants to refresh a handful after a scraper-data improvement.

A **Full metadata refresh** button at the bottom chains all three fetch/update steps in sequence with a determinate "Step N/3" progress bar. A separate **Add one local media file** form (system + game + media-type dropdowns + file picker) drives `media-add` with optional **Move** and **Overwrite if target exists** flags.

### Curate

Thin out region/revision duplicates, prune library caches, and manage ignore lists.

**Curate region/revision variants** wraps `spindoctor curate` (region checkboxes, prefer-revision latest/oldest, `--include-proto`, archive vs delete with an inline tooltip explaining archive is reversible and delete is permanent, dry-run by default). The **Preview (interactive)…** button opens a Toplevel with a `☑/☐` per-row keep/skip toggle so you can veto specific retirements before committing. Choosing delete + Apply shows a confirmation dialog naming the target system before anything is removed.

**Cache cleanup** shows 13 per-category checkboxes — the 9 safe caches pre-checked; the 4 unsafe categories (migration / restructure undo manifests, HyperSpin DB backups, LEDBlinky file backups) unchecked with a warning. **Audit caches** shows disk usage before you commit.

**Ignore list** wires up `ignore add / remove / list` with system dropdown + game-name fields, plus a **View / un-ignore…** button.

**Metadata-match cache controls**: **List cached matches** and **Clear cache…** buttons drive `spindoctor match list|clear` with an optional system filter.

### Wheels

Three checkboxes (Favorites / Recently Played / Most Played, all ticked by default) plus a **Refresh selected** button that rebuilds only the ticked wheels in sequence, showing "Step N/3: &lt;wheel&gt;…" in the status bar.

Below: a HyperSpin integration explainer (Most Played auto-registers in the Main Menu, Favorites and Recently Played do not, none auto-fire on cabinet startup) plus two helpers: **Add wheels to Main Menu** (chains `mainmenu add Favorites/Recently Played/Most Played --apply`) and **Install Tools-menu helpers** (a shortcut into the Tools tab's `install-tools` action).

A **Favorites** sub-section adds **Add / Remove / List** buttons that drive `fav add / remove / list` directly on the cabinet's favorites file. Remove asks for confirmation before unfavoriting.

CLI equivalents: `spindoctor-fav rebuild --apply` / `spindoctor-recent rebuild --apply` / `spindoctor-stats build-wheel --apply`.

> ![Wheels tab — three checkboxes (Favorites / Recently Played / Most Played) plus a Refresh selected button](images/gui-launcher-wheels-tab.png)

### Main Menu

Reorder, show/hide, sort, add, or remove the systems on HyperSpin's top-level wheel (`Main Menu.xml`). The tab renders the current file as a scrollable, selectable table (Treeview) with columns for position, system name, and visibility.

Select any row, then click **Move Up** / **Move Down** to reposition it or **Toggle Visible** to flip its enabled flag. **Save Order** asks for confirmation before writing the full reordered list back to `Main Menu.xml`. A **Refresh** button reloads the live file. Sort, Add, and Remove remain as separate controls below the table. CLI equivalent: `spindoctor mainmenu *`.

### Systems

Add or rename HyperSpin systems. **Add a new system** runs `add-system` (or `add-pc-system` for a PC-games system) on a typed system name with optional `--no-system-media` / `--no-game-media` toggles. **Rename an existing PC system** runs `pc-rename` with old / new fields.

**Per-system overrides** (added in 2.0): surfaces `config system set` with a system dropdown and form fields for ScreenScraper ID, TheGamesDB ID, ROM extensions (comma-separated, leading dot optional), layout (`per-game-folder` / `multi-disc-m3u` / `flat`), and emulator name. **Load current values** prefills the form from the saved override; **Save override** calls the CLI with only the flags the user actually filled in. Designed for niche systems (homebrew consoles, PC libraries, custom MAME variants) that stock SpinDoctor doesn't know.

**Organize a system** drives `spindoctor organize <SYSTEM>` with checkboxes for `--no-sort` and `--restructure`. Restructure honours the tab's existing Apply toggle, plus a separate **Undo latest restructure** button for the `--undo` flow.

Inspect buttons run `spindoctor systems` and `config system list`. Dry-run by default.

### LEDBlinky

**Generate** (controls.ini + colors.ini), **Audit coverage**, **Check**, and **Fix**. Per-system field defaults to MAME, plus an Overwrite toggle for community-maintained entries. Dry-run by default. CLI equivalent: `spindoctor ledblinky generate / audit / check / fix`.

### Lightgun

**Detect** installed Sinden / DemulShooter gear (with optional `--apply` to persist the discovered systems into config), **Audit** per-system wiring, and **Configure** one system's RocketLauncher INI with optional `-target` / extra-args overrides. CLI equivalent: `spindoctor lightgun detect / audit / configure`.

### Backup & Restore

Per-component checkboxes (default: all seven — roms, databases, media, emulators, rocketlauncher, ledblinky, settings), shared target-folder picker for create/list, separate backup-folder picker for info/restore, optional label, dry-run by default. Restore-time toggles for `--use-current-paths` (drive letters changed since backup) and `--overwrite`. The **Scan** button populates the restore dropdown from your configured backup folder. CLI equivalent: `spindoctor backup create / list / info / restore`.

### Tools

Three sections that cover the HyperSpin-integration surface:

1. **Install for HyperHQ → Tools menu** — writes the four `Refresh *.bat` helpers into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\`. Register them in HyperHQ → Tools to expose them inside HyperSpin's in-cabinet Tools menu.
2. **Install into an existing wheel system** — adds the four helpers as `<game>` entries inside an existing HyperSpin wheel (e.g. a `Toolkit` wheel where the "games" are maintenance tasks), with per-game PCLauncher INIs alongside the bats. CLI equivalent: `spindoctor install-tools --add-to-system <NAME>`.
3. **Auto-refresh on cabinet startup** (Windows-only) — Schedule auto-refresh registers a Task Scheduler `ONLOGON` task with a configurable post-log-on delay (default 2 min). Remove and Check round out the lifecycle.

### Migrate

Per-component checkboxes (default: all five — roms, hyperspin, emulators, rocketlauncher, ledblinky), target-root picker, a scrollable multi-select Listbox pre-populated from detected systems for partial-roms migrations (nothing selected = migrate all), toggles for `--keep-source` / `--verify` / `--no-update-config` / `--preserve-names`, and a separate **Undo** panel whose manifest dropdown is pre-populated from `~/.spindoctor/migrations/` (with "latest" at the top) and a Refresh button. Dry-run by default. CLI equivalent: `spindoctor migrate`.

### Logs

Persistent timeline of every command run since the GUI was launched, newest first. Tree on the left (Status / Started / Command); read-only viewer on the right showing the full output of the selected row. Each row tags as `DRY-RUN`, `OK`, `FAIL <code>`, or `running`.

The bottom Output panel only shows the *current* run; this tab indexes everything since launch so you can answer "what did that dry-run output again?" without re-running. Buffer caps at 200 entries (FIFO) and is in-memory only — restarting the GUI clears it. For longer-term history of apply-mode commands that wrote a JSON manifest, use **File → View logs & manifests…**.

A **Browse manifests / undo…** button next to Refresh/Copy/Clear (separated by a vertical Separator) signposts the menu's "Logs & Manifests" viewer for new users who land on the Logs tab first.

### Custom Command

Anything the dedicated tabs don't cover. The entry field is an editable Combobox seeded with ~70 canonical commands grouped by family (discovery, audit, curate, fetch, wheels, main menu, LEDBlinky, lightgun, backup, migrate, config). Default value is `--help`. Pick a preset, edit `<PLACEHOLDER>` tokens (`<SYSTEM>`, `<PATH>`, …), press Enter or click Run. Unfilled placeholders trigger a warning instead of silently shelling out.

> ![Custom Command tab with `audit --all` typed into the entry](images/gui-launcher-custom-tab.png)

## Menubar

A `File` / `View` / `Help` menubar runs across the top of the window:

- **File → Open config.json** — opens `~/.spindoctor/config.json` in your OS default editor.
- **File → Open SpinDoctor folder** — opens `~/.spindoctor/` in Explorer / Finder / xdg-open.
- **File → Open HyperSpin folder** / **Open ROMs folder** — same, for the paths set in `config.json`.
- **File → View logs & manifests…** — opens a Toplevel listing every per-run JSON manifest under `~/.spindoctor/{migrations,curation,edits,renames,media_imports,themes,misplaced}/` with a tree on the left and a read-only JSON viewer on the right. Three buttons at the bottom: **Undo this run** (runs the matching `--undo` for the selected manifest), **Show diff** (renders changes as a before/after table), **Revert just \<SYSTEM\>…** (theme swaps only — one-system revert via `--revert-system`).
- **File → Browse HyperSpin themes…** — opens a Toplevel inventorying every overlay file under `Media/Frontend/Images/` and per-system `Media/<system>/Images/{Special A,Special B}/`.
- **View → Show output pane** — checkbutton (also bound to `Ctrl+`` ` ``) that collapses or restores the bottom Output panel. State persists across restarts via the `output_visible` config key.
- **View → UI scale** — radio submenu with presets `0.8×` / `0.9×` / `1.0×` / `1.1×` / `1.25×` / `1.5×`. `Ctrl++` / `Ctrl+-` step by 0.1; `Ctrl+0` resets. Persisted via the `ui_scale` config key.
- **Help → First-run setup…** — re-opens the first-run wizard manually.
- **Help → About SpinDoctor** — version, description, and links to GitHub project / latest release / CHANGELOG.
- **Help → Check for updates** — pings GitHub Releases and reports if a newer tag is available, with a yes/no dialog that opens the release page on accept. The same check runs silently in the background on every launch — when newer, the status bar shows "Update available: vX.Y.Z" plus a one-click **Download…** button. Set `SPINDOCTOR_NO_UPDATE_CHECK=1` to disable for cabinets behind a strict firewall.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+1`–`Ctrl+9` | Jump to the Nth tab. |
| `Ctrl+F` | Open the Output-panel find bar (see below). |
| `Ctrl+Shift+F` | Toggle the system quick-filter bar (see below). |
| `Ctrl+`` ` `` | Show / hide the bottom Output panel. |
| `Ctrl++` / `Ctrl+-` | Step UI scale by 0.1. |
| `Ctrl+0` | Reset UI scale to 1.0×. |

## Find bar

Press `Ctrl+F` (`Cmd+F` on macOS) to open a slim search bar above the Output panel. Type to highlight every case-insensitive match in the buffer; **Next** / `Enter` jumps to the next match, **Prev** / `Shift+Enter` to the previous, `Esc` closes the bar. A match count ("3 of 17") shows next to the controls. Selected text pre-seeds the search field on open. The global binding works regardless of current focus — useful for scanning long audit / migrate output for a game name.

## System quick-filter

Press `Ctrl+Shift+F` (`Cmd+Shift+F` on macOS) to open a filter bar above the tab notebook. Type to narrow *every* system combobox across every tab to entries containing the typed text (case-insensitive). On a cabinet with 50+ systems, typing "mega" instantly shows only Mega Drive / Mega CD / Sega Mega-Tech everywhere. `Esc` closes the bar and clears the filter; the Clear button does the same without closing.

## Dry-run feedback

Every command without `--apply` is a dry-run. The GUI bookends those with explicit banners:

```
=== DRY RUN ===

$ spindoctor curate --all

(plan output…)

=== DRY RUN COMPLETE (exit 0) — nothing was written. Re-run with --apply to commit. ===
```

The status bar at the bottom switches to `Dry run finished — nothing changed. View results in Output or the Logs tab.` so the difference between "preview" and "applied" is unmissable. Real applies (with `--apply`) stay quiet so command-specific success messages aren't drowned out.

Chained workflows (Refresh all wheels, Register wheels in Main Menu, Full metadata refresh, Preflight check) show a **determinate** progress bar anchored to step/total; single-command runs use the indeterminate spinner.

## Dark mode and right-click menus

The GUI is dark by default — no toggle, no setting. The palette (deep grey background, off-white text, blue selection / focus accents) is applied via `ttk.Style` overrides on the `clam` theme plus `option_add` defaults for the non-themed Tk widgets (Menu, Listbox, Text, Canvas, PanedWindow). The macOS native menubar still uses the system appearance because Tk can't override it.

Every `Entry` / `Text` / `ScrolledText` widget in the GUI — Setup paths, scraper credentials, the Output panel, log viewers — has a right-click (or `Button-2` on macOS) context menu with Cut / Copy / Paste / Select-All. Read-only views show only Copy + Select-All; masked password fields suppress Copy/Cut so right-click can't bypass the mask.

## Stopping a long-running command

The **Stop** button in the bottom-right of the window terminates the current subprocess (sends `SIGTERM` / Windows `TerminateProcess`). The GUI re-enables the Run buttons once the child exits.
