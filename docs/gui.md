# GUI walkthrough

The canonical reference for `spindoctor-gui` — the same window whether you launched it from `spindoctor-gui.exe` (Windows binary) or `spindoctor-gui` (pip install). Cabinet owners who'd rather click than type live here.

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
- [Dropdown letter-key jump](#dropdown-letter-key-jump)
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

**Async startup.** The window paints immediately, then runs the library scan (populating every system combobox across every tab from your HyperSpin Databases directory) and the startup health checks (config validation + CLI-binary probe) in the background. While the scan is in flight the status bar reads "Scanning library…"; once it finishes the bar lands on either "Ready." or the first detected problem (e.g. "Setup incomplete — N path(s) need attention"). On a slow NAS-mounted library this avoids the "is it frozen?" beat the older synchronous behaviour had on launch.

**Fresh-install Setup focus.** When no `config.json` exists yet, the GUI auto-selects the Setup tab so a brand-new cabinet owner lands on the form that needs filling. Once any config has been saved, your last-active tab (`gui_last_active_tab`) is restored as usual.

**Single-instance lock.** The GUI takes an OS-level file lock at `~/.spindoctor/gui.lock` on startup. Launching a second `spindoctor-gui` on the same machine will show a warning and exit cleanly — two GUIs editing the same HyperSpin XML simultaneously can corrupt the library, so the second instance refuses to start by default. If you genuinely need two windows open (comparing two cabinet configs on one box, for example) set `SPINDOCTOR_DISABLE_SINGLETON=1` in your environment before launching — you're then responsible for not running destructive operations from both. The lock file is released automatically when the process exits, so a crash never poisons future launches.

## First-run wizard

The wizard is opt-in — it does not auto-fire at launch. New cabinet owners reach it from the **Run first-run wizard…** button at the top of the Setup tab; the same dialog is also available from **Help → First-run setup…** at any time. A three-step modal opens:

1. **Welcome** — a one-sentence intro and a "Skip" / "Next" pair.
2. **Pick paths** — required: `roms_dir` and `hyperspin_dir`. Browse… buttons next to each field; drag-and-drop a folder from Explorer / Finder also fills the field.
3. **Run doctor** — runs `spindoctor doctor` inline against the just-saved paths and renders the per-check ✓/⚠/✗ summary so you can fix anything obvious before clicking Finish.

Existing installs and re-runs use the same dialog. There is no auto-open behaviour and no `first_run_complete` flag — start it when you want it.

## Layout primer

A single window with a workflow-ordered tab strip across the top, a shared **Output** panel along the bottom (resizable via a draggable sash), and a status bar at the very bottom showing the current command and control buttons. Every tab scrolls vertically with an always-visible scrollbar so cabinet owners on 1024×768 / 1280×720 displays can still reach widgets that overflow.

### Global Apply, Verbose, and Save Log checkboxes

The status bar contains three checkboxes that apply to **every command in every tab**:

| Checkbox | Effect |
|---|---|
| **Apply** | When checked, commands run with `--apply` and write changes to disk. When unchecked (default), commands run in dry-run mode — output shows what *would* happen, nothing is written. |
| **Verbose** | When checked, commands run with `--verbose` and print additional detail: file paths being written, per-item counts (added / overridden / skipped), old→new values. When unchecked (default), only the summary line is shown. |
| **Save Log** | When checked, every finished command's exact Output panel text (command line, full stdout/stderr, exit code) is written as a `.txt` backup file into your configured **Default output directory** (Setup tab). Unchecked by default. If `output_dir` isn't set, the Output panel notes the run wasn't saved instead of writing anywhere unexpected. |

Apply and Verbose replace the per-section Apply checkboxes that previously lived inside each tab. The single always-visible location makes it impossible to forget which mode you're in before clicking a button. Save Log is a convenience copy of what the Logs tab already keeps in memory for the session — use it when you want a durable record after the GUI closes (e.g. to attach to a bug report).

## Per-tab health badges

Each tab name carries a small badge whenever the area it covers has a problem detected by `spindoctor doctor`:

| Badge | Meaning |
|---|---|
| (none) | Area is healthy. |
| ⚠ | Warning — paths missing optional bits, scraper credentials blank, etc. |
| ✗ | Failure — required path is broken, database file unreadable, etc. |

The doctor pass runs on a worker thread on launch (doesn't delay first paint) and re-runs after every Setup save so badges stay current. Run-progress badges (⟳/✓/✗) render at the right edge so a tab can show both at once — e.g. `LEDBlinky ⚠ ⟳`.

## Tab tour

Tabs appear in new-user journey order: configure paths first (Setup), then confirm the cabinet is healthy (Diagnostics — read-only, so it's safe to explore before touching anything), then build out systems (Systems), then enrich metadata (Metadata & Media), curate the library (Maintenance), manage cross-system wheels (Toolkit), configure hardware (LEDBlinky / Lightgun), then infrastructure (Backup & Restore → Migration), and finally power-user escapes (Console) and the session log (History) at the very end.

Most action tabs use numbered **Step N** sections that read top-to-bottom — follow them in order when setting something up for the first time, or jump directly to the step you need for ongoing maintenance.

### Setup

A **Run first-run wizard…** button sits at the very top — the friendliest entry point for a brand-new cabinet owner (also reachable any time from **Help → First-run setup…**).

Below it, every path-based config key in a single form, pre-populated with your current `config.json` values (or sensible Windows defaults on first run), grouped into **Core paths** (ROMs, HyperSpin, Emulators, RocketLauncher — what every feature relies on) and **Optional paths** (LEDBlinky, MAME executable, output/backup/audit-export/temp dirs — fine to leave blank until a feature needs them). Each row has a **Browse…** button (native folder picker) and an **Open** button (jumps to the path in Explorer / Finder to verify your choice). When `tkinterdnd2` is available (Windows binary install or `pip install spindoctor[gui]` / `[all]`), drag a folder from Explorer / Finder onto any path field to fill it in.

Below the path fields, a **Scraper credentials** section stores your ScreenScraper username, ScreenScraper password, and TheGamesDB API key — password and key fields are masked (`***`) with a Show/Hide eyeball toggle. A **Test credentials** button pings both endpoints and reports ✓ / ✗ inline before you click Save.

Click **Save configuration** to validate and write everything to `config.json` in one step. A History tab entry is created recording the saved path, any validation warnings, and an exit code (0 = valid, 1 = warnings). CLI equivalent: `spindoctor config init`.

### Diagnostics

The cabinet's "is everything OK?" diagnostic surface — nothing on this tab writes to disk. Four numbered steps cover the main diagnostic workflow.

**Step 1 — Cabinet health check (no inputs needed):** Three one-click, library-wide checks that need nothing filled in first — the natural next stop straight after Setup. **Preflight check…** chains `doctor` → `tools-audit` → `audit --all` end-to-end with a determinate "step N of 3" progress bar, then pops a verdict messagebox at the end (green "Cabinet is ready" / yellow "N issues found"). Continues past failures so a partial cab state is still informative. Designed for the "I'm taking the cab to a LAN event tomorrow" moment when running three commands by hand is error-prone. **Run doctor** and **Tools audit** run the individual checks.

**Step 2 — Audit a system:** Pick a system from the dropdown, then **Audit selected system** (or **Audit all systems** for the whole library). Audit options: a **Report CSV (optional)** entry + Browse… button feeds `audit --report`; checkboxes for `--no-media` (skip media checks for faster runs) and `--detailed` (richer per-file output).

**Open Media folder for selected system** and **Open ROMs folder for selected system** buttons jump straight to `<hyperspin>\Media\<system>\` or `<roms_dir>\<system>\` — useful when an audit row reports "missing wheel" and you want to eyeball the offending folder.

**Step 3 — Library-wide scans:** One-click read-only inspectors: **Find duplicate ROMs**, **Find cross-system dupes**, **Find misplaced ROMs**, **Find orphan media**, **Check disc-set consistency**, **Check archive extensions**, **Lint**, **Generate report**, **Preview HyperSpin XML**, **Stats**. Each button writes "Scan complete — see output for results." to the status bar.

**Check archive extensions** peeks inside every `.zip`/`.7z`/`.rar` archive in each configured ROM folder and compares the inner file extensions against the `Rom_Extension=` list in `Global Emulators.ini` (falling back to SpinDoctor's built-in emulator-extension map when the RL config is unavailable). Archives whose inner extension is not in the configured list are flagged — this is the most common reason RocketLauncher reports *"No valid roms found in the archive"* at launch time.

**Step 4 — Search & verify:** A **Global Search** box (`spindoctor find-global`), a **Verify-against-DAT** mini-form (`spindoctor verify --system X --dat …`), and an **Inspect** form. Selecting a system in the Inspect form auto-populates the **ROM (optional)** dropdown from that system's database; leave it blank (first item) to run `inspect --all`. Click **↻** to refresh the game list.

CLI equivalents: `spindoctor audit`, `spindoctor doctor`, `spindoctor tools-audit`, `spindoctor find-dupes`, `spindoctor find-misplaced`, `spindoctor find-orphan-media`, `spindoctor check-discs`, `spindoctor check-archive-ext`, `spindoctor lint`, `spindoctor report`, `spindoctor preview`, `spindoctor stats`.

### Systems

Manage the systems that HyperSpin exposes. Four numbered steps cover the common setup journey; the remaining sections are optional.

**Step 1 — Main menu carousel:** Reorder, show/hide, sort, add, or remove the systems on HyperSpin's top-level wheel (`Main Menu.xml`). The tab renders the current file as a scrollable, selectable table (Treeview) with columns for position, system name, and visibility.

Select any row, then reposition it with one of three methods: click **Move Up** / **Move Down**, press **Alt+Up** / **Alt+Down** to nudge without leaving the keyboard, or type a target position in the **Move to #** field and click **Go** to jump directly in a single action. Click **Toggle Visible** to flip its enabled flag. **Save Order** asks for confirmation before writing the full reordered list back to `Main Menu.xml`; on completion a History tab entry records the target file, the outcome, and an exit code. A **Refresh** button reloads the live file. Sort, Add, and Remove remain as separate controls below the table. CLI equivalent: `spindoctor mainmenu *`.

If `Main Menu.xml` can't be parsed (file open in HyperHQ, malformed XML, truncated mid-write) the tab pops a modal naming the file path and the parse error, and clears the table so you don't see stale rows from the previous successful load. Fix the file and click Refresh to retry.

**Step 2 — Add a new system:** **Run add-system** (or **Run add-pc-system** for a PC-games system) on a typed system name with optional `--no-system-media` / `--no-game-media` toggles. For PC systems the GUI automatically appends `--no-interactive` so the title-review step doesn't hang the subprocess on stdin — users who want to curate titles by hand can run `spindoctor pc-rename <system>` from a terminal.

**Step 3 — Rename or clone a game:** Rename moves the ROM, database entry, and every media file in one shot (and writes an undo manifest). Clone duplicates them under a new name. Both are dry-run until you tick Apply. Select a system to auto-populate the **Game** dropdown from that system's database; click **↻** to refresh the list if you've changed the database since opening the tab. CLI: `spindoctor rename / clone`.

**Step 4 — Organize a system (sort wheels + optional restructure):** Drives `spindoctor organize <SYSTEM>` with checkboxes for `--no-sort` and `--restructure`. Restructure honours the tab-level Apply toggle, plus a separate **Undo latest restructure** button for the `--undo` flow.

**Add new games / refresh a PC system** (unnumbered — for PC systems only): wraps `spindoctor pc-rename <system>`. Scans `<roms_dir>/<system>/` for new or changed installs, updates title decisions, and writes PCLauncher INIs for any new entries. Run this after dropping new `.exe` / `.lnk` files into the folder. Each INI is written with the actual game executable — when RocketLauncher's extension-matching picks up a non-exe file (e.g. `webcache.zip` from a GOG install), SpinDoctor scans the game folder and resolves the correct `.exe` automatically. With **Verbose** ticked, prints each game's resolved executable path and INI status (`new` / `stale` / `ok`) on separate lines with full paths — no truncation. **Overwrite existing INIs** (maps to `--overwrite-pclauncher`) rewrites every INI — use this after a drive migration, file rename, or to bulk-fix games previously written with the wrong executable (e.g. `webcache.zip`).

**Fix PC game executable** (unnumbered — for PC systems only): for games that launch the wrong executable (uninstaller, GOG/Steam cache file, NW.js runtime, etc.). The system picker defaults to "PC Games" on startup (case-insensitive match). The game dropdown lists all subdirectories found on disk — including games not yet in the HyperSpin XML — so it matches what `pc-rename` sees. The candidate listbox auto-populates with every `.exe` found in the game folder, recommended first (uninstallers, `vcredist*`, `chromedriver.exe`, NW.js runtime files, etc. are ranked last). Pick the correct executable (or type a custom path in the field below the list), then click **Apply** to update `Application=` and `WorkingFolder=` in the per-game PCLauncher INI. Other user-set keys like `FadeTitle=` are left untouched. CLI: `spindoctor pc-fix-exe <system> <game> [--exe <path>] --apply`.

**Per-system overrides** (advanced): surfaces `config system set` with a system dropdown and form fields for ScreenScraper ID, TheGamesDB ID, ROM extensions (comma-separated, leading dot optional), layout (`per-game-folder` / `multi-disc-m3u` / `flat`), and emulator name. **Load current values** prefills the form from the saved override; **Save override** calls the CLI with only the flags the user actually filled in. Designed for niche systems (homebrew consoles, PC libraries, custom MAME variants) that stock SpinDoctor doesn't know.

**Inspect** buttons run `spindoctor systems` and `config system list`. Read-only.

### Metadata & Media

Fetch metadata + media from ScreenScraper / TheGamesDB and sync the database XML. Shared system dropdown at the top, plus a **Game** dropdown below it (auto-populated when a system is selected). Leave Game blank to process all games; pick one to target only that game. An Apply toggle governs all steps. Changing the System dropdown always blanks the Game dropdown — a game from the previous system never carries over.

**Step 1 — Full metadata refresh:** One-click chain: `fetch-meta → fetch-media → update-db` in sequence for the selected system (and game, if one is picked). Stops on first error. Use the individual steps below to run or troubleshoot each phase separately.

**Step 2 — Fetch metadata:** Wraps `fetch-meta` with `--auto-best` / `--all-games` / `--no-cache`, a **Source** dropdown (`both (SS primary)` / `screenscraper` / `thegamesdb` / config default), and a **Threshold** entry (client-side validated 0.0–1.0). "Both (SS primary)" is the recommended default — ScreenScraper is tried first and TheGamesDB fills any gaps.

**Multi-system fetch-meta** (added in 2.0): the **Pick subset…** button opens a modal multi-select Listbox. The **Run on subset…** button chains `fetch-meta --system X` once per picked system, aborting on the first non-zero exit code. Designed for cabinets with 20+ systems where the user wants to refresh a handful after a scraper-data improvement.

**Step 3 — Fetch media:** Media-type checkboxes (wheel, background, snap, video, trailer, title, theme, fade, sound — defaulting to wheel + background), plus `--overwrite`. The **Source** dropdown (`both (SS primary)` / `screenscraper` / `thegamesdb` / config default) controls which provider is queried. With "both", ScreenScraper fills slots first; TheGamesDB fills any that SS missed — including clearlogos (→ wheel) and screenshots (→ snap). Video, title, fade, sound, and theme require ScreenScraper. See [commands.md → fetch-media provider capabilities](commands.md#fetch-media) for the full comparison table. If **Game** is selected in the shared header, only that game's media is touched. If the Output panel shows `metadata error: … NameResolutionError` or `Network unreachable`, the cabinet's internet connection was down — see [Troubleshooting → fetch-media reports "Failed: 500"](troubleshooting.md#fetch-media-reports-failed-500-with-no-explanation).

**Step 4 — Scan local media folder:** Source-folder picker + copy/move/link action. CLI: `spindoctor media-scan`.

**Step 5 — Sync database to ROMs:** `update-db` with `--remove-orphans` / `--strip-variant-tags`. **Run generate-config** (alongside) regenerates RocketLauncher's per-system settings INIs — **run this after every ROM migration** so RocketLauncher's `Rom_Path` entries reflect the new drive. CLI: `spindoctor update-db`, `spindoctor generate-config --apply`.

**Batch edit metadata** (advanced, unnumbered): One filter clause + one set clause + optional CSV report path. Drives `spindoctor batch-edit`.

**Add one local media file** (unnumbered): System + game + media-type dropdowns + file picker, drives `media-add` with optional **Move** and **Overwrite if target exists** flags. Honours the global Apply toggle — unticked shows the would-copy destination as a dry-run preview. Selecting a system auto-populates the **Game** dropdown from that system's database; click **↻** to refresh.

**Per-game & override (Optional)** — appears directly below the System selector, before Step 1. Contains two related controls in one collapsible box:

- **Game selector** (blank = all games): Limits every operation on the tab to one specific game. The dropdown auto-populates when a system is selected. Clear it with **✕** to run all games again.
- **Override IDs** (optional): Forces a specific ScreenScraper / TheGamesDB game ID instead of fuzzy name matching — for titles that don't match by name (language barrier, alternate punctuation, remaster subtitle). Find the ID at `screenscraper.fr/gameinfos.php?gameid=XXXX` or `thegamesdb.net/game.php?id=XXXX`. **Load current override** reads whatever's saved; **Save override** / **Clear override** drive `config game-override set / clear`. Once saved, the metadata cache is automatically bypassed for that game so the forced ID takes effect immediately on the next run — no cache clearing needed. `fetch-media --verbose` shows `override: ss=XXXX` alongside the resolved source to confirm it was used. CLI: `spindoctor config game-override set / list / clear` — see [Configuration → Per-game overrides](configuration.md#per-game-overrides).

### Maintenance

Thin out region/revision duplicates, prune library caches, and manage ignore lists.

**Step 1 — Curate region/revision variants:** Wraps `spindoctor curate` (region checkboxes, prefer-revision latest/oldest, `--include-proto`, archive vs delete with an inline tooltip explaining archive is reversible and delete is permanent, dry-run by default). Region tickboxes persist across launches via the `gui_curate_regions` config key. The **Preview (interactive)…** button opens a Toplevel with a `☑/☐` per-row keep/skip toggle so you can veto specific retirements before committing. Choosing delete + Apply shows a final confirmation dialog.

**Cache cleanup:** 13 per-category checkboxes — the 9 safe caches pre-checked; the 4 unsafe categories (migration / restructure undo manifests, HyperSpin DB backups, LEDBlinky file backups) unchecked with a warning. **Audit caches** shows disk usage before you commit.

**Ignore list:** Wires up `ignore add / remove / list` with system dropdown + game-name dropdown (auto-populated from the selected system's database; click **↻** to refresh), plus a **View / un-ignore…** button.

**Metadata-match cache:** **List cached matches** and **Clear cache…** buttons drive `spindoctor match list|clear` with an optional system filter.

### Toolkit

Four numbered steps cover building and wiring up the custom wheels; the remaining sections are optional one-time setup.

**Step 1 — Import HyperSpin favorites (optional):** **Sync favorites from HyperSpin** imports HyperSpin's per-system F-key favorites into SpinDoctor's store so the Step 2 rebuild includes them. Skip this if you only manage favorites from this tab. (It leads the tab because the import must happen *before* the rebuild reads the store — the previous layout placed it after the rebuild while its own tooltip said to run it first.) The favorites import scans every console for favorite markers; with the global **Verbose** toggle ticked, the Output panel lists each console as it is scanned and which ones contributed favorites. The scan only parses a console's database when a favorites source is actually present, so consoles with no favorites cost almost nothing.

**Step 2 — Refresh custom wheels:** Three checkboxes (Favorites / Recently Played / Most Played, all ticked by default) plus a **Refresh selected** button that rebuilds only the ticked wheels. The progress bar pulses continuously while the rebuild runs; the status bar shows "Step N/M: &lt;wheel&gt;…" so you can track which wheel is active. Each wheel streams phase-by-phase updates to the Output panel (`building wheel`, `writing database`, `mirroring media`, `PCLauncher INIs done`, etc.) — rebuilding a large Favorites collection can take several minutes, so watch the Output panel rather than waiting for silence. With **Verbose** ticked, the rebuild additionally lists each media file mirrored and each console scanned during the favorites import. CLI: `spindoctor-fav rebuild --apply` / `spindoctor-recent rebuild --apply` / `spindoctor-stats build-wheel --apply`.

**Step 3 — Register in HyperSpin main menu:** **Add wheels to Main Menu** chains `mainmenu add` for each ticked wheel (Favorites and Recently Played need this; Most Played auto-registers). As of v2.4.25, this also regenerates the RocketLauncher system settings files (`Settings/<system>.ini` and `Settings/<system>/Emulators.ini`) with `Rom_Extension=ini` and installs the bundled wheel media — so clicking the button is sufficient to fully restore a synthetic wheel that has been accidentally removed (e.g. by running generate-config after a ROM drive migration).

**Step 4 — Manage favorites:** **Add / Remove / List** drive `fav add / remove / list` directly. Remove asks for confirmation. Run Step 2 (Favorites checked) afterwards to push changes into HyperSpin. Select a system to auto-populate the **Game** dropdown from that system's database; click **↻** to refresh the list after database changes.

**Install .bat helpers (optional):** Two sub-sections:

1. **Install for HyperHQ → Tools menu** — writes `Refresh Favorites.bat`, `Refresh Recently Played.bat`, `Refresh Most Played.bat`, and `Refresh All.bat` into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\`. Register them in HyperHQ → Tools to expose them inside HyperSpin's in-cabinet Tools menu.
2. **Install into an existing wheel system** — adds the helpers as `<game>` entries inside an existing HyperSpin wheel (e.g. a `Toolkit` wheel), with per-game PCLauncher INIs alongside the bats. CLI: `spindoctor install-tools --add-to-system <NAME>`.

**Auto-refresh on cabinet startup** (Windows-only): **Schedule auto-refresh** registers a Task Scheduler `ONLOGON` task with a configurable post-log-on delay (default 2 min). **Remove scheduled task** and **Check task status** round out the lifecycle.

**Reset wheel data (scrub):** Permanently delete favorites and/or play statistics to start fresh. Backup folder field creates a restorable snapshot before scrubbing. Statistics.ini files cannot be regenerated — always back up first. **Restore** button recovers from a previous scrub backup.

### LEDBlinky

The LEDBlinky tab is organized as a numbered step-by-step workflow. Follow the sections top to bottom when setting up LED colors for the first time. Steps 1 and 2 are one-time setup; Steps 3 onward are the regular ongoing workflow.

**Step 1 — Overlay Hook Fix (one-time setup)**

Fixes HyperSpin Search / Genre / Favorites overlay crashes: adds a stub entry to `LEDBlinkyControls.xml` and comments out LEDBlinky process hooks in per-menu `Settings.ini`. Run once after installing LEDBlinky. Always writes in-place to `ledblinky_dir` / `hyperspin_dir`.

- **Check overlay hooks** — read-only scan. CLI: `spindoctor ledblinky check`.
- **Fix overlay hooks** — commits both patches. CLI: `spindoctor ledblinky fix --apply`.

**Step 2 — Settings.ini (one-time setup)**

Configure LEDBlinky's animation behaviour. Run once after installing, then only when you want to change the animation style.

- **FE active animation** — `FELWAFile`: animation played while actively browsing HyperSpin. Leave blank for static colors; pick a `.lwa` file for a smooth fade effect. Leave as `<Random>` to keep unchanged.
- **Screen saver animation** — `FEScreenSaverLWAFile`: animation played during the HyperSpin screen saver. Leave blank to silence; pick a `.lwa` file for a specific animation. Leave as `<Random>` to keep unchanged.
- **In-game unused buttons** — `GamePlayLWAFile`: leave **blank** to silence unmapped buttons during gameplay (recommended); select an `.lwa` file to animate them instead.

**Refresh list** populates all three dropdowns from your LEDBlinky `lwa\` folder and pre-selects each dropdown to the value currently set in `Settings.ini`. The dropdowns also pre-populate on startup if `ledblinky_dir` is already configured. Apply checkbox + **Patch Settings.ini**. CLI: `spindoctor ledblinky patch-settings`.

**Step 3 — MAME: Generate, Normalize & Sync Players**

These steps build MAME-sourced LED data using `mame -listxml`. Use **▶ Run Full MAME Setup (3a + 3c)** for a single-click workflow, or run individual steps below. Re-run after adding new MAME ROMs — existing entries are preserved unless Overwrite is ticked.

- **▶ Run Full MAME Setup (3a + 3c)** — chains Generate + Sync player colors in one step. CLI: `spindoctor ledblinky setup --apply`.
- **3a. Generate (controls + colors)** — reads MAME's `-listxml` to write `controls.ini` + `Colors.ini` for every MAME ROM. Dry-run by default; tick **Overwrite existing entries — 3a Generate** to replace existing entries. Since 2.4.21, output uses native `P1_BUTTON1=` format (not legacy hex). CLI: `spindoctor ledblinky generate`.
- **3b. Normalize Colors.ini** — only needed for a legacy Colors.ini in hex format (`ledcolor1=FF0000`). Not required after a fresh Generate. CLI: `spindoctor ledblinky colors normalize`.
- **3c. Sync player colors** — adds missing P2/P3/P4+ entries to `Colors.ini` by mirroring the matching P1 color for each button listed in `controls.ini`. Never overwrites existing entries (use `--override` via Custom Command to replace them). CLI: `spindoctor ledblinky colors sync-players`.
- **Audit MAME coverage** — shows which MAME ROMs have and lack control data. CLI: `spindoctor ledblinky audit`.
- **Inspect ROM** — type a ROM name and click **Inspect** to diagnose why a specific game's LEDs may not be working. CLI: `spindoctor ledblinky inspect-rom <rom>`.

**Step 4 — Fill Default Colors (any console)**

Adds `Colors.ini` entries for every ROM that has no LED mapping — works for MAME, SNES, NES, or any other console. Games without an entry go completely dark; after fill-defaults they glow a steady color. Leave **Console** blank to cover all systems at once, including Favorites and Recently Played.

- **Console** — select a specific system or leave blank for all consoles (including Favorites / Recently Played / Most Played).
- **Default color** — dropdown from `Color-RGB.ini`; **Refresh colors** reloads the palette.
- **Buttons (1-8)** — how many `P{n}_BUTTON` keys per player.
- **Players (1-4)** — number of player blocks (P1–P4), all mirrored to the same color.
- **Admin buttons** — optional extra block using the next player slot. Set to 0 to disable.
- **Override existing entries if all buttons are the same color** — updates uniform sections; leaves mixed-color entries untouched.
- **Don't add new keys when overriding** — only updates values of already-present keys.

Apply checkbox + **Fill Default Colors** button. CLI: `spindoctor ledblinky fill-defaults`.

**Step 5 — Randomize Entry Colors**

Gives each game its own independent random button color. All `P*_BUTTON*` / `P*_JOYSTICK` keys get one random color; `P*_COIN` / `P*_START` get a second. Only existing keys are updated — buttons intentionally absent (dark) stay dark. Requires normalized format (Step 3b for legacy files). If most sections are skipped, run Normalize first.

- **Seed (optional)** — integer for reproducible output; blank = fresh shuffle every run.

Apply checkbox + **Randomize Entry Colors** button. CLI: `spindoctor ledblinky colors randomize [--seed N]`.

**Step 6 — Admin Button Colors**

Sets fixed per-button colors for cabinet-level (admin) buttons (Select, Exit, Search, Pause) across **every** ROM section. **Run after Step 5 (Randomize)** — Randomize overwrites all button colors, so admin colors must be set last to stick.

- **Player slot (1–6)** — default `3` for a 2-player cabinet.
- **Button count (1–8)** — how many buttons to update.
- **BUTTON1–BUTTON8** — per-button color dropdowns. **Refresh colors** reloads from `Color-RGB.ini`.

Apply checkbox + **Set Admin Button Colors** button. CLI: `spindoctor ledblinky admin-buttons set`.

**Step 7 — Brightness**

Sets all `Color-RGB.ini` colors to a uniform brightness: **100 % = maximum** (dim colors boosted); 50 % = half; 10 % = night mode; 0 % = all off. Drag slider and click **Scale Brightness**. CLI: `spindoctor ledblinky colors brightness`.

**Step 8 — Color Definitions (Color-RGB.ini)**

Treeview of all named colors (Name, R/G/B 0-48, hex). Click a row to load it; edit name and/or paste `#RRGGBB`; click **Update & Rename** to propagate through `Color-RGB.ini`, `Colors.ini`, and `LEDBlinkyControls.xml`. **Normalize Colors.ini** also available here as a shortcut. CLI: `spindoctor ledblinky colors edit / normalize`.

**Step 9 — Backup / Restore**

Quick backup and restore scoped to LEDBlinky files. Both folder fields default to `config.backup_dir`. Dry-run by default. CLI: `spindoctor backup create --include ledblinky` / `spindoctor backup restore --include ledblinky`.

### Lightgun

Two numbered steps cover the lightgun setup workflow.

**Step 1 — Detect & audit:** **Detect installed gear** reads existing RocketLauncher INIs and seeds SpinDoctor config with discovered DemulShooter targets (optional `--apply` to persist). **Audit wiring** shows per-system hook status. CLI: `spindoctor lightgun detect / audit`.

**Step 2 — Configure one system:** Pick a system, optionally choose a DemulShooter `-target` value (auto-detected from system name if left blank), and add optional extra args. **Configure system** writes the Pre/Post launch hooks. CLI: `spindoctor lightgun configure --system <NAME>`.

### Backup & Restore

Three numbered steps walk through the full backup / restore workflow.

**Step 1 — Target folder & components:** Set the destination folder and tick the components to include (default: all seven — roms, databases, media, emulators, rocketlauncher, ledblinky, settings). **Config snapshot** preset selects settings + databases only for a lightweight backup; **Everything** ticks all.

**Step 2 — Create backup:** Optional label, then **Create backup**. **List backups under target** lists existing snapshots under the same folder. CLI: `spindoctor backup create / list`.

**Step 3 — Restore from a backup:** **Scan** populates the dropdown from your configured backup folder; **Browse…** picks a folder manually. **Show backup info** and **Compare to live** are read-only. **Restore backup** (separated by a visual divider from the safe buttons) triggers the actual restore. Restore-time toggles: `--use-current-paths` (drive letters changed since backup) and `--overwrite`. CLI: `spindoctor backup info / diff / restore`.

### Migration

Five numbered steps walk through the full migration workflow.

**Step 1 — Current configuration:** **Show current paths** and **Run doctor** let you verify what's configured before moving anything.

**Step 2 — Backup before migrating:** Create a snapshot of your current setup. Strongly recommended — if anything goes wrong you can restore from it.

**Step 3 — Migration settings:** Target root picker, component checkboxes (default: all five — roms, hyperspin, emulators, rocketlauncher, ledblinky), an optional systems-filter Listbox for partial-roms migrations (nothing selected = migrate all), and option toggles: `--keep-source` / `--verify` / `--no-update-config` / `--preserve-names`. Click **Run migration** to execute. Dry-run by default. CLI: `spindoctor migrate`.

**Step 4 — Undo a previous migration:** Manifest dropdown pre-populated from `~/.spindoctor/migrations/` (with "latest" at the top). **Refresh** reloads. **List manifests** and **Undo** complete the lifecycle.

**Step 5 — Update RocketLauncher after migration:** Click **Run generate-config** (respects the global Apply toggle) to rewrite `Rom_Path=` in every per-system `Settings\<SystemName>\Emulators.ini`. Only `Rom_Path` changes — `Default_Emulator`, `Emu_Path`, `Module`, and all other emulator settings are left exactly as configured. Without this step RocketLauncher can't find your games at the new location and HyperSpin displays empty wheels. See [Workflows → Moving only your ROMs to a new drive](workflows.md#moving-only-your-roms-to-a-new-drive).

Ticking **Apply** pops a confirmation dialog before running — the wording adapts to the chosen mode. `--keep-source` shows a milder "copy to new drive, originals stay" message; the default destructive move warns explicitly that originals will be removed and points at the undo-manifest as the only recovery path.

### Console

Anything the dedicated tabs don't cover. The entry field is an editable Combobox seeded with canonical commands organised into named sections (`─── Health & Discovery ───`, `─── LEDBlinky ───`, etc.). Every CLI command with meaningful flag variants is represented, and commands within each section are alphabetically sorted. Selecting a section header auto-advances to the first real command in that section. Default value is `--help`. Pick a preset, edit `<PLACEHOLDER>` tokens (`<SYSTEM>`, `<PATH>`, `<ROM>`, …), press Enter or click Run. Unfilled placeholders trigger a warning instead of silently shelling out.

### History

Persistent timeline of every action taken since the GUI was launched, newest first. Tree on the left (Status / Started / Command); read-only viewer on the right showing the full output of the selected row. Each row tags as `DRY-RUN`, `OK`, `FAIL <code>`, or `running`. The viewer header shows `# Dry-run: Yes` (preview), `# Dry-run: No` (wrote to disk), or `# Dry-run: N/A` (read-only or write-always command where the concept does not apply). **Save selected output…** exports the selected entry to a `.txt` file and appends its own log entry recording the saved path.

The History tab captures both CLI subprocess invocations *and* in-process GUI operations that write data: Save configuration, Save Main Menu order, Theme-apply Apply, Curate Apply, Ignore viewer Remove, and the three Task Scheduler actions (Schedule / Remove / Check status). Everything that changes state on disk appears here.

The bottom Output panel only shows the *current* run; this tab indexes everything since launch so you can answer "what did that dry-run output again?" without re-running. Buffer caps at 200 entries (FIFO) and is in-memory only — restarting the GUI clears it. For longer-term history of apply-mode commands that wrote a JSON manifest, use **File → View logs & manifests…**.

A **Browse manifests / undo…** button next to Refresh/Copy/Clear (separated by a vertical Separator) signposts the menu's "Logs & Manifests" viewer for new users who land on the History tab first.

## Menubar

A `File` / `View` / `Help` menubar runs across the top of the window:

- **File → Open config.json** — opens `~/.spindoctor/config.json` in your OS default editor.
- **File → Open SpinDoctor folder** — opens `~/.spindoctor/` in Explorer / Finder / xdg-open.
- **File → Open HyperSpin folder** / **Open ROMs folder** — same, for the paths set in `config.json`.
- **File → View logs & manifests…** — opens a Toplevel listing every per-run JSON manifest under `~/.spindoctor/{migrations,curation,edits,renames,media_imports,themes,misplaced}/` with a tree on the left and a read-only JSON viewer on the right. Three buttons at the bottom: **Undo this run** (runs the matching `--undo` for the selected manifest), **Show diff** (renders changes as a before/after table), **Revert just \<SYSTEM\>…** (theme swaps only — one-system revert via `--revert-system`).
- **File → Browse HyperSpin themes…** — opens a Toplevel inventorying every overlay file under `Media/Frontend/Images/` and per-system `Media/<system>/Images/{Special A,Special B}/`.
- **View → Show output pane** — checkbutton (also bound to `Ctrl+`` ` ``) that collapses or restores the bottom Output panel. State persists across restarts via the `output_visible` config key.
- **View → UI scale** — radio submenu with presets `0.8×` / `0.9×` / `1.0×` / `1.1×` / `1.25×` / `1.5×`. `Ctrl++` / `Ctrl+-` step by 0.1; `Ctrl+0` resets. Persisted via the `ui_scale` config key.
- **Help → About SpinDoctor** — version, description, and links to GitHub project / latest release / CHANGELOG. Shows the app icon next to the title when the bundled PNG icon is available.
- **Help → Keyboard shortcuts** — opens an in-app reference for the shortcut map listed below.
- **Help → Check for updates** — pings GitHub Releases and reports if a newer tag is available, with a yes/no dialog that opens the release page on accept. If you're already on the latest tag, the result is surfaced in the status bar ("vX.Y.Z is the latest release.") rather than a modal — only newer-available results pop a dialog so you can decide whether to open the release page. The same check runs silently in the background on every launch — when newer, the status bar shows "Update available: vX.Y.Z" plus a one-click **Download…** button. Set `SPINDOCTOR_NO_UPDATE_CHECK=1` to disable for cabinets behind a strict firewall.
- **Help → First-run setup…** — re-opens the first-run wizard manually.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+1`–`Ctrl+9` | Jump to the Nth tab. |
| `Ctrl+F` | Open the Output-panel find bar (see below). |
| `Ctrl+Shift+F` | Toggle the system quick-filter bar (see below). |
| `Ctrl+`` ` `` | Show / hide the bottom Output panel. |
| `Ctrl++` / `Ctrl+=` | Zoom in (step UI scale by +0.1). Both keys are bound. |
| `Ctrl+-` | Zoom out (step UI scale by -0.1). |
| `Ctrl+0` | Reset UI scale to 1.0×. |
| `Esc` | Close any open dialog (About, Keyboard shortcuts, find bar, etc.). |

The same table is reachable in-app via **Help → Keyboard shortcuts**.

## Find bar

Press `Ctrl+F` (`Cmd+F` on macOS) to open a slim search bar above the Output panel. Type to highlight every case-insensitive match in the buffer; **Next** / `Enter` jumps to the next match, **Prev** / `Shift+Enter` to the previous, `Esc` closes the bar. A match count ("3 of 17") shows next to the controls. Selected text pre-seeds the search field on open. The global binding works regardless of current focus — useful for scanning long audit / migrate output for a game name.

## System quick-filter

Press `Ctrl+Shift+F` (`Cmd+Shift+F` on macOS) to open a filter bar above the tab notebook. Type to narrow *every* system combobox across every tab to entries containing the typed text (case-insensitive). On a cabinet with 50+ systems, typing "mega" instantly shows only Mega Drive / Mega CD / Sega Mega-Tech everywhere. `Esc` closes the bar and clears the filter; the Clear button does the same without closing.

## Dropdown letter-key jump

Every dropdown in the GUI (system pickers, the Metadata & Media Game dropdown, etc.) supports letter-key type-ahead: with the dropdown focused, pressing a letter jumps straight to the next entry starting with that letter — no need to scroll a list of hundreds of games by hand. Pressing the same letter again moves to the next match instead of looping back to the first one. This is wired up once, globally, so any dropdown added in the future gets it automatically.

## Dry-run feedback

Commands fall into three categories, which the GUI tracks and displays in the History tab:

| Category | `--apply` concept | History tab `# Dry-run:` header | Logs tag |
|---|---|---|---|
| **Dry-run preview** | Supported; not passed | `Yes` | `DRY-RUN` |
| **Actual write** | Supported; passed | `No` | `OK` |
| **Read-only / write-always** | N/A (no `--apply` flag) | `N/A` | `OK` |

For dry-run previews the GUI wraps the output in explicit banners:

```
=== DRY RUN ===

$ spindoctor curate --all

(plan output…)

=== DRY RUN COMPLETE (exit 0) — nothing was written. Re-run with --apply to commit. ===
```

The status bar at the bottom switches to `Dry run finished — nothing changed. View results in Output or the History tab.` so the difference between "preview" and "applied" is unmissable. Real applies (with `--apply`) stay quiet so command-specific success messages aren't drowned out.

Read-only and write-always commands (`audit`, `doctor`, `tools-audit`, `inspect`, `find-dupes`, `stats`, `check-discs`, `check-archive-ext`, `verify`, `lint`, `report`, `preview`, `systems`, `find-global`, `diff`, `self-doctor`, `backup list/info`, `backup sidecar list`, `fav list/add/remove/sync`, `recent list`, `ignore add/remove/clear`, `match clear`, `emulator-title list/set/remove`, `mainmenu show/edit`, `ledblinky audit/check/inspect-rom`, `ledblinky colors list`, `lightgun audit`, `config show/init/set/system/verify-credentials`, `install-tools`) never show the DRY RUN banner — for the read-only ones it would mislead users into thinking a health check was a preview of something committable, and for the write-always single-record ones (`fav add`, `ignore add`, …) it would falsely suggest nothing was written. Commands that are read-only *without* `--apply` but write *with* it (`doctor --apply`, `lightgun detect --apply`) are recorded as actual writes whenever `--apply` is present.

Long-running single commands and chained wheel rebuilds use a **pulsing (indeterminate)** progress bar; multi-step chains that have a known step count (Full metadata refresh, Preflight check) additionally advance a **determinate** fill between steps.

### Quiet success, audible validation

Routine GUI outcomes are surfaced in the status bar at the bottom of the window rather than a modal you have to click through. Two patterns:

- **Status flash** (`_flash_status`): "Configuration saved.", "Auto-refresh task deleted.", "vX.Y.Z is the latest release.", etc. The bar shows the message and auto-reverts to "Ready." after 6 seconds. No click-through.
- **Validation flash** (`_flash_validation`): "No subset picked — click 'Pick subset…' first.", "Nothing to apply — every retirement is unchecked.", "Pick a PC system first.", etc. Same status-bar update, plus an audible bell — so a user focused on a form widget at the top of the window doesn't miss the bottom-of-window feedback.

Modal dialogs are reserved for: multi-line result summaries (Preflight passed, Curate done with manifest path, Auto-refresh scheduled with reboot instructions), destructive-action confirmations (Backup restore, Migrate apply, Curate delete), and errors. Up-to-date update checks, save successes, "nothing selected" prompts, and similar one-line outcomes go through the status bar instead.

## Dark mode and right-click menus

The GUI is dark by default — no toggle, no setting. The palette (deep grey background, off-white text, blue selection / focus accents) is applied via `ttk.Style` overrides on the `clam` theme plus `option_add` defaults for the non-themed Tk widgets (Menu, Listbox, Text, Canvas, PanedWindow). The macOS native menubar still uses the system appearance because Tk can't override it.

Scrollbar thumbs (the draggable rectangle inside the trough) are intentionally several stops brighter than the surrounding panel so the grabby part is obvious against the dark theme; they also brighten further on hover. If your scrollbars previously felt invisible, you're on an older build — upgrade and the thumb pops.

Every `Entry` / `Text` / `ScrolledText` widget in the GUI — Setup paths, scraper credentials, the Output panel, log viewers — has a right-click (or `Button-2` on macOS) context menu with Cut / Copy / Paste / Select-All. Read-only views show only Copy + Select-All; masked password fields suppress Copy/Cut so right-click can't bypass the mask.

## Stopping a long-running command

The **Stop** button in the bottom-right of the window terminates the current subprocess (sends `SIGTERM` / Windows `TerminateProcess`). The GUI re-enables the Run buttons once the child exits.

Interrupting a long-running `backup`, `migrate`, or `curate` operation is safe — the CLI cleans up the in-flight component and writes a *partial manifest* of whatever finished before it died. That means:

- An interrupted **backup** still shows up in the Restore picker, and you can replay it like any other backup. Only the partially-copied component is missing.
- An interrupted **move-mode migrate** is reversible via `Logs → Browse manifests… → Undo`. The completed moves are recorded; the source folders that were already migrated can be put back. (Move-mode is the one operation where Stop without this safety net would be unrecoverable, since the source is destroyed during the move.)
- An interrupted **curate** in archive mode is reversible the same way — files moved to `_retired/` before the interrupt are recorded in the partial manifest.

Stopping does not roll back work already committed — a manifest exists so that *you* can roll it back if you choose to.
