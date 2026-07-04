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
3. **Run Health Check** — runs `spindoctor doctor` inline against the just-saved paths and renders the per-check ✓/⚠/✗ summary so you can fix anything obvious before clicking Finish.

Existing installs and re-runs use the same dialog. There is no auto-open behaviour and no `first_run_complete` flag — start it when you want it.

## Layout primer

A single window with a workflow-ordered tab strip across the top, a shared **Output** panel along the bottom (resizable via a draggable sash), and a status bar at the very bottom showing the current command and control buttons. Every tab scrolls vertically with an always-visible scrollbar so cabinet owners on 1024×768 / 1280×720 displays can still reach widgets that overflow.

The status bar text is automatically truncated with … when a command string is too long to fit — the right-side buttons and checkboxes are always visible regardless of command length.

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

Tabs appear in new-user journey order: configure paths first (Setup), then confirm the cabinet is healthy (Diagnostics — read-only, so it's safe to explore before touching anything), then build out systems (Systems), then manage games within those systems (Games), enrich metadata (Metadata & Media), curate the library (Maintenance), manage cross-system wheels (Toolkit), configure hardware (LEDBlinky / Lightgun), then infrastructure (Backup & Restore → Migration), and finally power-user escapes (Console) and the session log (History) at the very end.

Most action tabs use numbered **Step N** sections that read top-to-bottom — follow them in order when setting something up for the first time, or jump directly to the step you need for ongoing maintenance.

### Setup

A **Run first-run wizard…** button sits at the very top — the friendliest entry point for a brand-new cabinet owner (also reachable any time from **Help → First-run setup…**).

Below it, every path-based config key in a single form, pre-populated with your current `config.json` values (or sensible Windows defaults on first run), grouped into **Core paths** (ROMs, HyperSpin, Emulators, RocketLauncher — what every feature relies on) and **Optional paths** (LEDBlinky, MAME executable, output/backup/audit-export/temp dirs — fine to leave blank until a feature needs them). Each row has a **Browse…** button (native folder picker) and an **Open** button (jumps to the path in Explorer / Finder to verify your choice). When `tkinterdnd2` is available (Windows binary install or `pip install spindoctor[gui]` / `[all]`), drag a folder from Explorer / Finder onto any path field to fill it in.

Below the path fields, a **Scraper credentials** section stores your ScreenScraper username, ScreenScraper password, and TheGamesDB API key — password and key fields are masked (`***`) with a Show/Hide eyeball toggle. A **Test credentials** button pings both endpoints and reports ✓ / ✗ inline before you click Save.

Click **Save configuration** to validate and write everything to `config.json` in one step. A History tab entry is created recording the saved path, any validation warnings, and an exit code (0 = valid, 1 = warnings). CLI equivalent: `spindoctor config init`.

### Diagnostics

The cabinet's "is everything OK?" diagnostic surface — nothing on this tab writes to disk. Four numbered steps cover the main diagnostic workflow.

**Step 1 — Cabinet health check (no inputs needed):** Three one-click, library-wide checks that need nothing filled in first — the natural next stop straight after Setup. **Preflight check…** chains `doctor` → `tools-audit` → `audit --all` end-to-end with a determinate "step N of 3" progress bar, then pops a verdict messagebox at the end (green "Cabinet is ready" / yellow "N issues found"). Continues past failures so a partial cab state is still informative. Designed for the "I'm taking the cab to a LAN event tomorrow" moment when running three commands by hand is error-prone. **Run Health Check** and **Check Installed Tools** run the individual checks.

**Step 2 — Audit a system:** Pick a system from the dropdown, then **Audit selected system** (or **Audit all systems** for the whole library). Audit options: a **Report CSV (optional)** entry + Browse… button feeds `audit --report`; checkboxes for `--no-media` (skip media checks for faster runs) and `--detailed` (richer per-file output).

**Open Media folder for selected system** and **Open ROMs folder for selected system** buttons jump straight to `<hyperspin>\Media\<system>\` or `<roms_dir>\<system>\` — useful when an audit row reports "missing wheel" and you want to eyeball the offending folder.

**Step 3 — Library-wide scans:** One-click read-only inspectors: **Find duplicate ROMs**, **Find cross-system dupes**, **Find misplaced ROMs**, **Find orphan media**, **Check disc-set consistency**, **Check archive extensions**, **Lint**, **Generate report**, **Preview HyperSpin XML**, **Stats**. Each button writes "Scan complete — see output for results." to the status bar.

**Check archive extensions** peeks inside every `.zip`/`.7z`/`.rar` archive in each configured ROM folder and compares the inner file extensions against the `Rom_Extension=` list in `Global Emulators.ini` (falling back to SpinDoctor's built-in emulator-extension map when the RL config is unavailable). Archives whose inner extension is not in the configured list are flagged — this is the most common reason RocketLauncher reports *"No valid roms found in the archive"* at launch time.

**Step 4 — Search & verify:** A **Global Search** box (`spindoctor find-global`), a **Verify-against-DAT** mini-form (`spindoctor verify --system X --dat …`), and an **Inspect** form. Selecting a system in the Inspect form auto-populates the **ROM (optional)** dropdown from that system's database; leave it blank (first item) to run `inspect --all`. Click **↻** to refresh the game list.

CLI equivalents: `spindoctor audit`, `spindoctor doctor`, `spindoctor tools-audit`, `spindoctor find-dupes`, `spindoctor find-misplaced`, `spindoctor find-orphan-media`, `spindoctor check-discs`, `spindoctor check-archive-ext`, `spindoctor lint`, `spindoctor report`, `spindoctor preview`, `spindoctor stats`.

### Systems

Manage the systems that HyperSpin exposes. Three numbered steps cover the common setup journey; the remaining sections are optional. To add, remove, reorder, or rename individual games within a system, use the **Games** tab (next tab along).

**Step 1 — Main menu carousel:** Reorder, show/hide, sort, add, or remove the systems on HyperSpin's top-level wheel (`Main Menu.xml`). The tab renders the current file as a scrollable, selectable table (Treeview) with columns for position, system name, and visibility.

Select any row, then reposition it with one of three methods: click **Move Up** / **Move Down**, press **Alt+Up** / **Alt+Down** to nudge without leaving the keyboard, or type a target position in the **Move to #** field and click **Go** to jump directly in a single action. Click **Toggle Visible** to flip its enabled flag. **Save Order** asks for confirmation before writing the full reordered list back to `Main Menu.xml`; on completion a History tab entry records the target file, the outcome, and an exit code. A **Refresh** button reloads the live file. Sort, Add, and Remove remain as separate controls below the table. CLI equivalent: `spindoctor mainmenu *`.

If `Main Menu.xml` can't be parsed (file open in HyperHQ, malformed XML, truncated mid-write) the tab pops a modal naming the file path and the parse error, and clears the table so you don't see stale rows from the previous successful load. Fix the file and click Refresh to retry.

**Step 2 — Add a new system:** **Add Arcade System** (or **Add PC System** for a PC-games system) on a typed system name with optional skip-media toggles. For PC systems the GUI automatically appends `--no-interactive` so the title-review step doesn't hang on stdin. To add newly installed games to an existing PC system (not a brand-new one), use the **Games** tab → Step 3.

**Step 3 — Organize a system (sort wheels + optional restructure):** Drives `spindoctor organize <SYSTEM>` with checkboxes for `--no-sort` and `--restructure`. Restructure honours the global Apply toggle, plus a separate **Undo latest restructure** button for the `--undo` flow.

**Per-system overrides** (advanced): surfaces `config system set` with a system dropdown and form fields for ScreenScraper ID, TheGamesDB ID, ROM extensions (comma-separated, leading dot optional), layout (`per-game-folder` / `multi-disc-m3u` / `flat`), emulator name, and **ROM folder path**. **Load current values** prefills the form from the saved override; **Save override** calls the CLI with only the flags the user actually filled in. Designed for niche systems (homebrew consoles, PC libraries, custom MAME variants, Daphne-based systems, etc.) that stock SpinDoctor doesn't recognize. The **ROM folder path** field overrides the default `roms_dir\<SystemName>` derivation used by `generate-config` — set it when the ROM folder name differs from the HyperSpin system name (e.g. `J:\Games\3DO` for a system named "Panasonic 3DO"). CLI equivalent: `config system set --emulator <name> --rom-path <path>`.

**Inspect** buttons run `spindoctor systems` and `config system list`. Read-only.

---

### Games

Manage individual games across any system. A single **System** picker at the top of the tab drives all four steps — pick the system once and every step below operates on that selection. The tab is the central place for day-to-day game management: reordering the wheel, removing stale entries, renaming or cloning, adding freshly installed PC games, and fixing a bad executable path.

**System picker:** Select any system from the dropdown. When a system named “PC Games” exists it is pre-selected (this tab is used almost exclusively for PC-game repairs); otherwise the first system alphabetically is. Changing the selection automatically clears the game-wheel table (Step 1), reloads the rename/clone game list (Step 2), and reloads the fix-exe game list (Step 4). All four steps read from the same selection — no need to re-pick in each section.

**Step 1 — Manage the game wheel:** Click **Load Games** to populate a scrollable table showing every game in that system's XML database in wheel order — position number, ROM name, and display title.

Reposition games with one of three methods: click **Move Up** / **Move Down**, press **Alt+↑** / **Alt+↓** to nudge without leaving the keyboard, or type a target position in the **Jump to #** field and click **Go** to jump directly. **Sort A→Z (by title)** sorts by display name with leading articles stripped (The / A / An), matching HyperSpin's own wheel sort convention; **Sort A→Z (by ROM name)** sorts by filename. **Remove Game** shows a dry-run message when Apply is off; with Apply ticked it confirms and shells out to `game remove --apply` (the table row is removed only after the command reports success). Tick **Also remove PCLauncher INI (PC systems only)** to also delete `Modules/PCLauncher/<system>/<game>.ini` — use this for PC systems so RocketLauncher no longer finds the game; the checkbox is a no-op for systems that have no PCLauncher INI. **Save Order** writes the full reordered list back to the system XML — dry-run preview when Apply is off, background-thread save when Apply is on. Changing the system picker clears the table so a loaded game list can't accidentally be saved to the wrong database. CLI: `spindoctor game list / remove / move / move-up / move-down / sort`.

**Step 2 — Rename or clone a game:** Rename moves the ROM file, database entry, and every media file in one operation and writes an undo manifest so the change is reversible. Clone duplicates everything under a new name — useful for keeping a speed-hack alongside the clean dump or creating a multi-language variant. Both are dry-run until you tick Apply. The **Game** dropdown auto-populates from the selected system's database; click **↻** to refresh after a database change. CLI: `spindoctor rename / clone`.

**Step 3 — Add new PC games / refresh the wheel:** For PC / Windows / Steam systems only. Scans every install folder inside `<roms_dir>/<system>/` and adds any new games to the HyperSpin wheel database — one entry per folder, junk shortcuts silently ignored. Also writes per-game PCLauncher INIs and the RocketLauncher system settings files (`Settings/<system>/Emulators.ini` and `Settings/<system>.ini` with `Default_Emulator=PCLauncher`, `Rom_Path=Modules/PCLauncher/<system>`, `Rom_Extension=ini`). Run this after installing a new game to the PC Games folder. **Overwrite existing PCLauncher INIs** rewrites every existing per-game INI — use after a drive migration or when a game launches the wrong executable. This step is not needed for MAME, SNES, or other ROM-based systems. CLI: `spindoctor add-pc-system <system> --no-menu --no-system-media --no-game-media --no-interactive [--overwrite-pclauncher] [--apply]`.

**Step 4 — Fix a game that launches the wrong executable:** For PC games that open an uninstaller, GOG/Steam cache file, NW.js runtime, or wrong `.ahk` launcher. SpinDoctor scans the game folder and ranks candidates: real `.exe` files first (shallower paths ranked above deeper ones), then `.ahk` scripts, then `.bat` files, then known junk at the bottom. Select the game from the dropdown (the list reads from disk so it includes newly installed games not yet in the XML), pick the correct candidate, and click **Apply fix** to update `Application=` and `WorkingFolder=` in the PCLauncher INI. Other keys (`FadeTitle=`, `AppWaitExe=`, etc.) are left untouched. **INI targeting:** the per-game INI (`Modules/PCLauncher/<System>/<game>.ini`) is updated when it exists — this is the file used by PC Games, Windows Games, and any system set up by `add-pc-system`. The system-level INI (`Modules/PCLauncher/<System>.ini`) is the fallback for Taito Type X / NESiCAxLive systems that have no per-game subfolder. CLI: `spindoctor pc-fix-exe <system> <game> [--exe <path>] --apply`.

### Metadata & Media

Fetch metadata + media from ScreenScraper / TheGamesDB and sync the database XML. Shared system dropdown at the top, plus a **Game** dropdown below it (auto-populated when a system is selected). Leave Game blank to process all games; pick one to target only that game. An Apply toggle governs all steps. Changing the System dropdown always blanks the Game dropdown — a game from the previous system never carries over.

**Step 1 — Full metadata refresh:** One-click chain: `fetch-meta → fetch-media → update-db` in sequence for the selected system (and game, if one is picked). Stops on first error. Use the individual steps below to run or troubleshoot each phase separately.

**Step 2 — Fetch metadata:** Wraps `fetch-meta` with `--auto-best` / `--all-games` / `--no-cache`, a **Source** dropdown (`both (SS primary)` / `screenscraper` / `thegamesdb` / config default), and a **Threshold** entry (client-side validated 0.0–1.0). "Both (SS primary)" is the recommended default — ScreenScraper is tried first and TheGamesDB fills any gaps.

**Multi-system fetch-meta** (added in 2.0): the **Pick subset…** button opens a modal multi-select Listbox. The **Download for Selected Systems…** button chains `fetch-meta --system X` once per picked system, aborting on the first non-zero exit code. Designed for cabinets with 20+ systems where the user wants to refresh a handful after a scraper-data improvement.

**Step 3 — Fetch media:** Media-type checkboxes (wheel, background, snap, video, trailer, title, theme, fade, sound — defaulting to wheel + background), plus `--overwrite`. The **Source** dropdown (`both (SS primary)` / `screenscraper` / `thegamesdb` / config default) controls which provider is queried. With "both", ScreenScraper fills slots first; TheGamesDB fills any that SS missed — including clearlogos (→ wheel) and screenshots (→ snap). Video, title, fade, sound, and theme require ScreenScraper. See [commands.md → fetch-media provider capabilities](commands.md#fetch-media) for the full comparison table. If **Game** is selected in the shared header, only that game's media is touched. If the Output panel shows `metadata error: … NameResolutionError` or `Network unreachable`, the cabinet's internet connection was down — see [Troubleshooting → fetch-media reports "Failed: 500"](troubleshooting.md#fetch-media-reports-failed-500-with-no-explanation).

**Step 4 — Scan local media folder:** Source-folder picker + copy/move/link action. CLI: `spindoctor media-scan`.

**Step 5 — Sync database to ROMs:** `update-db` with `--remove-orphans` / `--strip-variant-tags`. **Update RocketLauncher INIs** (alongside) regenerates RocketLauncher's per-system settings INIs — **run this after every ROM migration** so RocketLauncher's `Rom_Path` entries reflect the new drive. CLI: `spindoctor update-db`, `spindoctor generate-config --apply`.

**Batch edit metadata** (advanced, unnumbered): One filter clause + one set clause + optional CSV report path. Drives `spindoctor batch-edit`.

**Add one local media file** (unnumbered): System + game + media-type dropdowns + file picker, drives `media-add` with optional **Move** and **Overwrite if target exists** flags. Honours the global Apply toggle — unticked shows the would-copy destination as a dry-run preview. Selecting a system auto-populates the **Game** dropdown from that system's database; click **↻** to refresh.

**Fill missing game themes** (unnumbered): Installs a blank HyperSpin theme zip for every game in the selected system that has a video or background screenshot but no per-game theme zip. The blank theme shows `Images\Backgrounds\<game>.png` as a full-screen backdrop and overlays the game video on top when one is present — existing theme zips are never overwritten. **Preview missing themes** runs a dry-run; **Fill blank themes (apply)** writes. Tick **All systems** in the System row to scan all systems at once. CLI: `spindoctor theme-fill --system <SYSTEM> [--all] [--apply]`.

**Per-game & override (Optional)** — appears directly below the System selector, before Step 1. Contains two related controls in one collapsible box:

- **Game selector** (blank = all games): Limits every operation on the tab to one specific game. The dropdown auto-populates when a system is selected. Clear it with **✕** to run all games again.
- **Override IDs** (optional): Forces a specific ScreenScraper / TheGamesDB game ID instead of fuzzy name matching — for titles that don't match by name (language barrier, alternate punctuation, remaster subtitle). All three fields (ScreenScraper ID, TheGamesDB ID, Steam App ID) accept either a bare numeric ID or a full URL pasted from the browser — the ID is extracted automatically. Find ScreenScraper IDs at `screenscraper.fr/gameinfos.php?gameid=XXXX`, TheGamesDB IDs at `thegamesdb.net/game.php?id=XXXX`. **Load current override** reads whatever's saved; **Save override** / **Clear override** drive `config game-override set / clear`. Once a scraper ID is saved, the metadata cache is automatically bypassed for that game so the forced ID takes effect immediately on the next run — no cache clearing needed. CLI: `spindoctor config game-override set / list / clear` — see [Configuration → Per-game overrides](configuration.md#per-game-overrides).

- **Steam media** (optional, PC games only): Download trailer video(s), screenshots, per-game background images, header artwork, and/or a wheel image for a specific game directly from the Steam Store — no account or API key needed. Only useful for PC/Steam titles that ScreenScraper/TheGamesDB don't cover well. Workflow: (1) pick System + Game above; (2) click **Find** to auto-populate the **Steam URL / App ID** field and immediately scan for media (see below) — or paste a URL/App ID manually and click **Scan**; (3) pick the desired candidate from each dropdown — **Video**, **Screenshot**, **Background**, **Artwork**, and **Wheel** — each also offers **"— do not download —"** as its first option; set any picker to that to skip that type (e.g. leave Wheel on "— do not download —" if you already have better wheel art from ScreenScraper); the **Background** picker uses the same screenshot list as Screenshot — pick the screenshot you want to use as the per-game background (`Images\Backgrounds\<game>.png`); (4) click **Apply selected** to download only the selected types. Dropdowns show "— scan first —" until a scan completes, or "— none —" if Steam has nothing for that type. Each picker row has a **View** button — opens the selected candidate's direct URL in the browser for all types (images, video). For MP4 video candidates the browser will download or play inline; for HLS `.m3u8` candidates the browser downloads the manifest (use a separate player to view it). View buttons are disabled until a Scan has been run and reset when you switch game or system. **Store page** button (next to Scan) opens the game's Steam store page in the browser — enabled after a successful scan. Video candidates served via HLS (most 2024+ titles) are labelled `(HLS — needs ffmpeg)` in the dropdown — ffmpeg must be present next to `spindoctor.exe` or on `PATH` for these to download. The **Overwrite existing** checkbox controls whether an already-present file is replaced. The **Quality** dropdown (`Best (1080p)` / `720p` / `480p` / `360p`) controls the HLS resolution for video downloads — `Best (1080p)` picks the highest available quality (default); lower settings produce much smaller files (e.g. a 400 MB 1080p trailer becomes ~25 MB at 480p). Quality has no effect on MP4 or image candidates. Maps to `--hls-quality` on the CLI. A stored Steam App ID (saved via **Save override**) is pre-filled automatically when a game is loaded — so after saving once you can just click Scan without re-pasting the URL. Switching to a different game resets the URL field and all five pickers automatically. **Image format:** Steam serves wheel, artwork, background, and screenshot images as JPEG; SpinDoctor saves them as `.png` (HyperSpin requires PNG in those folders) and converts to real PNG when Pillow is installed. The **Wheel** slot uses Steam's header capsule image; it is not a transparent-logo equivalent but works as a placeholder when ScreenScraper has no wheel art. **Find (Steam App ID lookup):** Click **Find** (next to the Steam URL / App ID field) to search the Steam store by the selected game's name, auto-populate the field with the best match, and immediately trigger a Scan — no copy-pasting or separate Scan click required. The search runs in the background; the status bar shows progress. If the auto-match is wrong (e.g. a DLC page instead of the base game), paste the correct URL manually and click **Scan**. CLI equivalent: `spindoctor fetch-steam-media` — see [commands.md → fetch-steam-media](commands.md#fetch-steam-media).

### Maintenance

Thin out region/revision duplicates, prune library caches, and manage ignore lists.

**Step 1 — Curate region/revision variants:** Wraps `spindoctor curate` (region checkboxes, prefer-revision latest/oldest, `--include-proto`, archive vs delete with an inline tooltip explaining archive is reversible and delete is permanent, dry-run by default). Region tickboxes persist across launches via the `gui_curate_regions` config key. The **Preview (interactive)…** button opens a Toplevel with a `☑/☐` per-row keep/skip toggle so you can veto specific retirements before committing. Choosing delete + Apply shows a final confirmation dialog.

**Cache cleanup:** 13 per-category checkboxes — the 9 safe caches pre-checked; the 4 unsafe categories (migration / restructure undo manifests, HyperSpin DB backups, LEDBlinky file backups) unchecked with a warning. **Check Cache Status** shows disk usage before you commit.

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

Six numbered steps walk through the full migration workflow.

**Step 1 — Current configuration:** **Show current paths** and **Run Health Check** let you verify what's configured before moving anything.

**Step 2 — Backup before migrating:** Create a snapshot of your current setup. Strongly recommended — if anything goes wrong you can restore from it.

**Step 3 — Migration settings:** Target root picker, component checkboxes (default: all five — roms, hyperspin, emulators, rocketlauncher, ledblinky), an optional systems-filter Listbox for partial-roms migrations (nothing selected = migrate all), and option toggles: `--keep-source` / `--verify` / `--no-update-config` / `--preserve-names`. Click **Start Migration** to execute. Dry-run by default. CLI: `spindoctor migrate`.

**Step 4 — Undo a previous migration:** Manifest dropdown pre-populated from `~/.spindoctor/migrations/` (with "latest" at the top). **Refresh** reloads. **List manifests** and **Undo** complete the lifecycle.

**Step 5 — Update RocketLauncher after migration:** Click **Update RocketLauncher INIs** (respects the global Apply toggle) to rewrite `Rom_Path=` in every per-system `Settings\<SystemName>\Emulators.ini`. Only `Rom_Path` changes — `Default_Emulator`, `Emu_Path`, `Module`, and all other emulator settings are left exactly as configured. Without this step RocketLauncher can't find your games at the new location and HyperSpin displays empty wheels. See [Workflows → Moving only your ROMs to a new drive](workflows.md#moving-only-your-roms-to-a-new-drive).

**Step 6 — Re-prefix game paths after a drive change:** For systems like **Taito Type X** whose game folders were moved to a different drive outside of a SpinDoctor `migrate` run. Pick the system, enter the new absolute game folder path (e.g. `J:\Games\Taito Type X`), then click **Preview** to see what would change or **Apply** to write. Rewrites `Application=` in `Modules\PCLauncher\<System>.ini` and `Rom_Path=` in `Settings\<System>\Emulators.ini`. Only those two keys change — `FadeTitle=`, `AppWaitExe=`, `ExitMethod=`, `PostExit=`, and all other per-game keys survive untouched. Use this step (not Step 5) when only one system's game folder was relocated manually. CLI: `spindoctor repath-system <System> --rom-path <NewPath> --apply`.

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

## "(Not in wheel)" system and game badges

System pickers across every GUI tab annotate any system that exists as a folder in `roms_dir` or `databases_dir` but is absent from `Main Menu.xml` with a `(Not in wheel)` suffix — for example, `Taito Type X (Not in wheel)`. This makes it easy to spot systems you've added to disk but not yet registered in the wheel.

The **Fix game executable** game picker also badges any game folder on disk that has no matching entry in the system's HyperSpin XML database. This is the only game dropdown that reads from the filesystem rather than the XML, so it is the only one where the discrepancy can arise; all other game pickers read the XML directly.

Both badges are display-only — the suffix is stripped automatically before any CLI command runs, so file paths and `--system` / `--game` arguments are never affected.

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
