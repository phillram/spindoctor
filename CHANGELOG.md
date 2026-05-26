# Changelog

All notable changes to SpinDoctor are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **HyperSpin themes were not copied during Favorites / Recently Played / Most Played wheel rebuilds**, leaving those wheels with no video preview or background artwork. Themes are almost always distributed as per-game `.zip` files (`Media/<system>/Themes/<game>.zip`). The media mirror code (`medialink.py`) treated the `Themes` subfolder as directory-only — looking for an extracted `Themes/<game>/` folder — so `.zip`-form themes were never found or copied. `"Themes"` has been added to `MEDIA_FILE_SUBDIRS` so zip-form themes are mirrored alongside video and wheel art. The extracted-directory path (`MEDIA_DIR_SUBDIRS`) is retained for the less common case.
- **`install-tools` wrote a bat named `Refresh Both.bat` even though it runs all three wheels (Favorites, Recently Played, Most Played).** The name was wrong and misleading — users reading the label assumed only two wheels would be refreshed. The file is now named `Refresh All.bat`. All GUI labels, documentation, and the scheduled-task description have been updated to match. Users who already have `Refresh Both.bat` on their cabinet can re-run `install-tools` (or the GUI's "Install helpers" button) to get the correctly named file.

## [2.4.1] - 2026-05-25

### Fixed

- **Archive-packed media files were silently skipped during Favorites / Recently Played / Most Played wheel rebuilds.** HyperSpin reads `.zip`-packed media natively, so source systems commonly store artwork as `.zip` archives rather than raw `.mp4` / `.png` files. Downloaded media packs may also use `.rar`, `.7z`, `.lha`, `.lzh`, `.gz`, or `.tar`. The `_FILE_EXTS` allowlist in `medialink.py` contained none of these, so they were never copied to `Media/Favorites/` etc., leaving the synthetic wheel with no video or background art even though the games displayed correctly in their source system's wheel. All seven archive extensions (`.zip`, `.rar`, `.7z`, `.lha`, `.lzh`, `.gz`, `.tar`) are now included.

- **Running `fav rebuild --apply`, `recent rebuild --apply`, or `stats build-wheel --apply` for the first time did not create `<hyperspin_dir>/Settings/<system>.ini`.** HyperSpin requires this file to open a sub-wheel; without it the frontend shows "Cannot find Recently Played.ini" (or "Favorites.ini" / "Most Played.ini") when the wheel is selected from the main menu, so the wheel never loads. SpinDoctor was already writing the RocketLauncher settings (`Settings/<system>/Emulators.ini`) but not the HyperSpin-side settings. Each rebuild command now writes a minimal `Settings/<system>.ini` containing `[exe info]\nhyperlaunch=true` when the file does not exist — existing files (created by HyperHQ or the user) are never overwritten.

- **`generate-config` was blind to folder-layout cabinets** (where RocketLauncher uses `Settings\<system>\Emulators.ini` instead of `Settings\<system>.ini`). On these cabinets — which are produced by HyperHQ and are common in the wild — `generate-config` would always report "(new file)" in its dry-run and write a flat `Settings\<system>.ini` that RL may not read, leaving the `Emulators.ini` with a stale `Rom_Path`. The command now detects which layout each system uses and writes to the matching file: folder-layout systems get their `Emulators.ini` updated (using the `[ROMS]` section that RL requires for this layout); flat-layout systems get their `.ini` updated as before; systems with neither file get both written so the cabinet works regardless of layout. The dry-run table also now shows the correct current `Rom_Path` read from whichever file actually exists.

- **`Settings/<system>/Emulators.ini` (folder-layout) included a `[PCLauncher]` section that caused RocketLauncher to blank out `Rom_Extension`.** On first launch after a wheel rebuild, RL's own AHK `IniWrite` filled in the `[PCLauncher]` section with empty values including `Rom_Extension=`. On the next launch RL read `Rom_Extension` from `[PCLauncher]`, found the blank value, and fell back to the global extension list (`zip|rar|7z|…`), producing "Cannot find Rom 1942 with any provided Rom_Extension: zip|rar|7z|lha|lzh|gzip|tar|" even after a successful rebuild. The working HyperHQ-generated `Emulators.ini` (confirmed on the same cabinet) contains only `[ROMS]`. The folder-layout `Emulators.ini` now writes only `[ROMS]`; the flat `Settings/<system>.ini` retains its `[PCLauncher]` block because the flat layout does not trigger RL's write-back.

- **"Schedule auto-refresh" and "Preflight" showed routine-outcome popup dialogs** instead of routing their result to the Output panel like every other action in the GUI. `_schedule_autorefresh` called `messagebox.showinfo` after already writing the full task detail to the Output panel — the popup was redundant and interrupted keyboard flow. `_summarise_preflight` similarly raised a "Preflight passed" dialog when the Output panel banner and status bar already conveyed the result. Both popups have been removed; `_schedule_autorefresh` now includes the bat path and reboot hint in `_append_output` and calls `_flash_status` for inline acknowledgement.

- **"Restore RocketLauncher INI from backup" (Meta tab) was hardcoded to the flat-layout path `Settings/<system>.ini`** and silently failed on HyperHQ cabinets that use the folder layout (`Settings/<system>/Emulators.ini`). The button now checks for the folder-layout file first and falls back to the flat-layout path, matching the detection order used by the rest of SpinDoctor.

## [2.4.0] - 2026-05-25

### Changed

- **GUI tab consolidation**: reduced from 15 tabs to 12 by merging related tabs.
  - "Audit & Doctor" + "Diagnose" → **Diagnostics** (one tab with "System audit", "Library-wide scans", and "Search & verify" sections).
  - "Curate" renamed to **Maintenance** (same content).
  - "Wheels" merged into **Tools** (wheel management sections appear first, then install helpers and scheduler).
  - "Main Menu" merged into **Systems** (carousel order section appears at top).

### Fixed

- **Four commands that write files when `--apply` is passed were incorrectly listed in `_READ_ONLY_COMMANDS`**, causing the GUI to show `# Dry-run: False` (no DRY RUN banner) even for their preview invocations. The affected commands: `generate-config`, `find-misplaced`, `find-orphan-media`, `lightgun configure`. These have been removed from `_READ_ONLY_COMMANDS`; the GUI now correctly labels a no-`--apply` run as `[DRY RUN]`. `doctor`, `lightgun detect`, and `mainmenu show` (no-arg) are kept in the read-only set — they are diagnostics / display commands, not write previews, so the DRY RUN banner is misleading for them.

- **Favorites, Recently Played, and Most Played media mirroring defaulted to hardlink mode (`auto`), which silently fell back to a copy on FAT32/exFAT but left no indication when hardlinks succeeded across-volume or failed entirely.** The default is now `copy` for all three wheels (`fav rebuild`, `recent rebuild`, `stats build-wheel`). Hardlinks and symlinks are still available via `--media-mode link` / `--media-mode symlink` for users who prefer them.

- **`fav rebuild`, `recent rebuild`, and `stats build-wheel` now accept `--verbose`**, which prints each media file as it is copied or linked (`copy  <src>\n   →  <dest>`). Without `--verbose` the summary counts are unchanged. The GUI's Logs tab "Save selected output…" button captures the full verbose output to a `.txt` file.

- **Six additional CLI commands now accept `--verbose`**: `find-misplaced`, `find-orphan-media`, `curate`, `theme-apply`, `media-scan`, and `cleanup run`. When `--verbose` is passed each command prints the full source → destination path (or full path for deletions) for every file it processes, in addition to the usual summary totals.

- **Wheels tab: added "Verbose" checkbox.** When ticked, passes `--verbose` to each rebuild command so the Logs tab records exactly which files were copied or linked. Off by default so normal refreshes stay concise.

- **Logs tab: added "Save selected output…" button.** Opens a file-save dialog and writes the selected run's full output (header + streamed CLI text) to a `.txt` file. Useful when verbose output or a long generate-config dry-run needs to be reviewed off-screen rather than copy-pasted.

- **`Settings/<system>/Emulators.ini` was written with a `[Settings]` section (introduced in v2.3.3) when it must use `[ROMS]`.** RocketLauncher's AHK code reads `Default_Emulator` from `[ROMS]` in folder-layout Emulators.ini files — the same section used by HyperHQ when it sets up PCLauncher systems (confirmed by Toolkit's working Emulators.ini). When the section was `[Settings]`, RL found no `Default_Emulator` key in `[ROMS]`, then wrote `[ROMS]\nDefault_Emulator=` (blank) back into the file via its own AHK IniWrite, causing "No Default_Emulator found in Settings\Favorites\Emulators.ini" on every game launch from the Favorites, Recently Played, and Most Played wheels — even after a successful `rebuild --apply`. The section is now `[ROMS]`. Note: the flat `Settings/<system>.ini` file correctly uses `[Settings]` and is unchanged — these two files follow different conventions.

## [2.3.4] - 2026-05-24

### Fixed

- **Multi-step wheel refresh ("Refresh selected" with all three boxes checked) ran only the first step, leaving the rest permanently "stuck running".** The root cause was a bug in `_on_proc_done`: the `finally` block unconditionally cleared `self._proc = None` after the chaining callback had already launched the next subprocess and stored it in `self._proc`. The overwrite disconnected the GUI from the new process so it never received a completion signal. The `finally` block now snapshots `old_proc` before the callback and only tears down GUI state when `self._proc` still points to the same object (i.e. no new subprocess was started by the chain callback).

- **`install-tools --add-to-system` overwrote the existing `Emulators.ini` for the target system (e.g. Toolkit), breaking all non-SpinDoctor entries in that wheel.** The command called `generate_synthetic_system_ini` unconditionally, which replaced the user's `[ROMS]`-section file and custom `Rom_Path` with SpinDoctor's generated `[Settings]`-section version. Existing Toolkit game entries then failed with "No Default_Emulator found" or "Cannot find ROM with wrong extension". The command now checks whether `Settings/<system>/Emulators.ini` or `Settings/<system>.ini` already exists; if so, it skips writing and prints the path the user needs to ensure includes `Modules/PCLauncher/<system>` in `Rom_Path`.

- **"Schedule auto-refresh" Task Scheduler button produced `ERROR: Value for '/TR' option cannot be more than 261 character(s)`.** The previous implementation embedded three full `.exe` paths in a PowerShell one-liner passed directly to `schtasks /TR`. On installs with a moderately long path this exceeded Windows Task Scheduler's 261-character `/TR` limit. The fix writes a companion `spindoctor-refresh-wheels.bat` file next to the exe (or in `~/.spindoctor/` for source installs) that contains the three rebuild commands with full paths, then passes `cmd /c "<bat_path>"` as the `/TR` value — keeping the task command well under the limit at any install path length.

- **`generate-config` dry run showed only the file path, not what was inside it**, making it impossible to verify a ROM drive change (e.g. D: → J:) before applying. The dry-run table now shows three columns: **Current Rom_Path** (read from the existing INI on disk, highlighted yellow if it differs), **New Rom_Path** (what would be written from `roms_dir` config), and **Status** (`new` / `update` / `no change`). The apply table is unchanged (shows written path + backup name).

- **`generate-config` included SpinDoctor-managed synthetic wheels (Favorites, Recently Played, Most Played) and the HyperSpin pseudo-system "Main Menu" in its run, writing incorrect `RetroArch` settings for them** (those names aren't in `EMULATOR_MAP` so `guess_emulator` fell back to `RetroArch`). Applying the generated INIs would overwrite the correct `PCLauncher` settings written by `fav rebuild` / `recent rebuild` / `stats build-wheel`, breaking every launch from those wheels. These four systems are now always skipped by `generate-config` and listed in a "skipped (managed)" note in the output. Additionally, any system whose existing `Settings/<system>/Emulators.ini` already declares `Default_Emulator=PCLauncher` (e.g. user-named Toolkit wheels) is detected and skipped automatically rather than being overwritten with the wrong emulator.

- **`spindoctor-recent rebuild --apply` and `spindoctor-stats build-wheel --apply` produced no output until the rebuild finished**, making the GUI look frozen during long media-copy operations. Progress lines (`[System] mirroring media for N game(s)…`, per-10-game counters, phase completion messages) are now printed with `flush=True` at each phase boundary inside `_build_synthetic_wheel` so the GUI output panel updates in real time.

## [2.3.3] - 2026-05-24

### Fixed

- **`Settings/<system>/Emulators.ini` used the wrong section name.** The folder-based settings file was written with a `[ROMS]` section header, but RocketLauncher's AHK `IniRead` looks for `Default_Emulator` in `[Settings]` — the same section used in the flat `Settings/<system>.ini`. The key was present but invisible to RL, causing "No Default_Emulator found in Settings\Favorites\Emulators.ini" on every game launch even after `fav rebuild --apply` ran successfully. The section is now `[Settings]`, with a `[PCLauncher]` block below it matching the flat-file layout.
- **`Settings/<system>/Emulators.ini` was also missing `Rom_Extension=ini`.** Without it RocketLauncher fell back to the global extension list (`zip|rar|7z|lha|lzh|gzip|tar|`) when searching the PCLauncher ROM directory, producing "Cannot find Rom `<name>` With any provided Rom_Extension: `zip|rar|7z|…`". The key is now written alongside `Default_Emulator`.
- **`install-tools` bat files and the scheduled startup task used bare command names** (`spindoctor-fav`, `spindoctor-recent`, `spindoctor-stats`) instead of full paths. When RocketLauncher / HyperSpin launch a bat, or when Windows Task Scheduler fires at log-on, the SpinDoctor install directory is not on `PATH` — so the commands silently failed and the wheels were never rebuilt. Both the bat files and the Task Scheduler `powershell.exe` command now embed the full path to the sibling `.exe` files resolved at write time from `sys.executable`, so they work regardless of what is on `PATH`.

## [2.3.2] - 2026-05-24

### Fixed

- **`fav rebuild` / `recent rebuild` wrote `Settings/<system>/Emulators.ini` to the wrong location.** RocketLauncher supports two layouts for emulator routing: a flat `Settings/<system>.ini` and a folder-based `Settings/<system>/Emulators.ini`. Only the flat file was written; installations using the folder layout produced "No default_emulator found in Settings\\Favorites\\Emulators.ini" on every launch. Both files are now written by `generate_synthetic_system_ini`, so SpinDoctor works correctly regardless of which layout is in use.
- **Per-game PCLauncher INIs used `[exe info]` format, which requires a monitored executable.** The INIs written into `Modules/PCLauncher/<system>/` used the `[exe info]` section (which requires `fadetitle` / a process to monitor), causing "PCLauncher does not know what exe, FadeTitle, and/or SteamID to watch for". Synthetic wheels invoke `RocketLauncher.exe -p HyperSpin`, and RL talks directly to HyperSpin for the fade/unfade cycle — no monitoring is needed. All per-game INIs are now written with the simpler `[Settings]` format (`ApplicationPath` / `ApplicationParameters` / `StartIn`).
- **Dry-run output showed "skipped (rocketlauncher_dir not set or invalid)" for the system INI even when RL dir was configured.** The dry-run path returned early before the system INI planning code, leaving `summary.system_ini_path = None`. The dry-run now computes and stores the planned path so the CLI correctly reports where the file *would* be written.

## [2.3.1] - 2026-05-24

### Added

- **Documentation: Toolkit / PCLauncher error.** Added a dedicated troubleshooting entry in `docs/troubleshooting.md` for the "PCLauncher does not know what exe, FadeTitle, and/or SteamID to watch for" error, explaining that `spindoctor install-tools --add-to-system Toolkit` writes the correct `[Settings]`-format INIs that don't require a monitored executable. Also added a "Cannot find recently played.ini" entry covering how to wire the Recently Played wheel via RocketLauncher's Global Emulator setting. `docs/standalone-tools.md` now cross-links to these entries.

### Fixed

- **`install-tools --add-to-system` did not write the RocketLauncher system INI.** The command wrote per-game PCLauncher INIs and updated the HyperSpin database XML, but never created `<RocketLauncher>/Settings/<system>.ini`. Without that file, RocketLauncher has no emulator mapping for the wheel — it doesn't know to use PCLauncher or where to find the per-game INIs — which produced the "PCLauncher does not know what exe, FadeTitle, and/or SteamID to watch for" error on every launch from the Toolkit wheel. The command now calls `generate_synthetic_system_ini` (the same function used by `fav rebuild` and `recent rebuild`) and prints the written path.

- **Recently Played and Most Played wheels showed 0 entries when stats live in `Data/Statistics/`.** Newer versions of RocketLauncher write per-system statistics to `<RL>/Data/Statistics/<system>.ini` instead of the classic `<RL>/Settings/Global Statistics/<system>.ini`. SpinDoctor now searches all three known locations (classic, oldest, and newer layout) and builds the wheel correctly regardless of which layout is in use.
- **The aggregate `Global Statistics.ini` was either ignored or misread.** RocketLauncher writes a summary file `Data/Statistics/Global Statistics.ini` (containing top-10 `[Last_Played_Games]`, `[TopTen_Time_Played]`, and `[TopTen_Times_Played]` sections). When no per-game stats files are found, SpinDoctor now falls back to reading this file so Recently Played and Most Played still show something useful. Toolkit pseudo-system entries (e.g. "Refresh Recently Played") are filtered out automatically.
- **RocketLauncher's `Global Statistics.ini` date format was not parsed.** The format `Friday May 22, 2026 07:19:22 AM` is now recognised by the stats date parser.
- **Favorites sync failed when `_Favorites.ini` was encoded as UTF-8-with-BOM or UTF-16.** HyperSpin on Windows can write per-system `<System>_Favorites.ini` files in several encodings. `sync_native` now tries `utf-8-sig`, `utf-16`, `cp1252`, and `latin-1` in order, so it correctly reads these files regardless of encoding.
- **`favorites.txt` (plain-text per-system list) was not recognised.** Some RocketLauncher / HyperSpin builds write a plain `favorites.txt` (one ROM name per line, no section headers) into each system's database folder (e.g. `Databases/MAME/favorites.txt`) instead of, or alongside, `_Favorites.ini`. `sync_native` now checks for this file as an additional source, with a case-insensitive search so `Favorites.txt` is also found. Both formats can coexist for the same system. An empty file produces a clear warning rather than silent failure.
- **The "no play history found" diagnostic note listed only the classic stats path.** It now lists all four paths searched (three per-system locations plus the Global Statistics.ini fallback) so users can quickly identify where their files actually are.
- **Recently Played, Most Played, and Favorites wheels gave no diagnostic output when empty.** All three CLIs now print a `source:` line per stats/favorites location that contributed data, so users can see exactly where records were found. When 0 favorites are found, the output lists the exact file pattern searched and explains how HyperSpin stores them, making it actionable without reading documentation.

---

## [2.3.0] - 2026-05-22

### Added

- **`backup_dir` config field — centralised backup root.** A new `backup_dir` setting (Setup tab → "Backup root directory", or `spindoctor config set backup_dir <path>`) specifies a root folder for all automatic backups. When set, the `.bak` file written before any in-place XML save goes to a named subfolder under that root (e.g. `D:\Backups\Main Menu\Main Menu.20260522_143012.bak`) instead of sitting next to the source file. All five `db.save()` call sites (fetch-meta, curate, sync-roms, install-tools, main-menu) now thread `backup_dir` through from config. `backup create` and `backup list` also use `backup_dir` as the default `--target` when no explicit path is given.
- **Backup & Restore tab defaults.** The "Target folder" and "Backup folder" fields in the Backup & Restore tab pre-populate from `backup_dir` when it is configured, so users don't have to retype the path each session.

### Fixed

- **Inaccessible `backup_dir` raised a raw `OSError` traceback.** If the configured `backup_dir` doesn't exist or isn't writable (wrong drive letter, missing directory, permission denied), the error is now caught and re-raised with a message that names the failing path and the configured `backup_dir`, so users know exactly what to fix. The live file is never written when the backup fails.

### Changed

- **`backup create --target` and `backup list --target` are now optional.** Both commands fall back to `config.backup_dir` when `--target` is not supplied, and exit with a clear error message if neither is set.
- **Window maximized state is now persisted.** The GUI saves whether the window was maximized when it closes and restores that state on the next launch (cross-platform: `state('zoomed')` on Windows, `wm_attributes('-zoomed')` on macOS/Linux). The stored normal-size geometry is preserved separately so un-maximizing later snaps back to the correct window size.

## [2.2.3] - 2026-05-22

### Fixed

- **`generate-config --apply` reordered the Main Menu wheel alphabetically.** Running `generate-config` (which has `--main-menu` on by default) would regenerate `Main Menu.xml` using a `sorted()` filesystem scan, discarding any manual ordering the user had set. The generator now reads the existing file first and preserves its entry order — existing systems keep their current positions, newly-discovered systems are appended at the end, and systems that are no longer detected on disk are dropped. `mainmenu add` and `add-system` were not affected by this bug; they always appended.
- **Corrupt `favorites.json` silently wiped all favorites on the next write.** `load_store` now emits a `RuntimeWarning` naming the file and the parse error when the file exists but is unreadable, instead of silently returning an empty store that would be saved over the corrupt one.
- **`fav rebuild` silently produced favorites with blank metadata when a system's database XML was missing or malformed.** `_safe_load` now emits a warning naming the system and the error before returning `None`, so users can tell why description/year/genre fields are empty.
- **`save_config` write failures surfaced as raw `OSError` tracebacks.** Failed config saves (disk full, permissions, file locked) now raise with a human-readable message via `humanize_oserror`, consistent with how other write failures are reported.
- **`doctor` LEDBlinky INI parse errors only showed the message string, not the exception type.** The detail field now includes `ExceptionType: message`, making it easier to diagnose the root cause from the doctor output.
- **Image dimension and video duration extraction failures were silently dropped.** `fileinfo` now logs a `DEBUG`-level message when reading image dimensions or video duration fails, naming the file and exception, so the root cause appears in the debug log instead of being invisible.
- **`media._open_in_default_app` swallowed OS errors without any trace.** The function now logs a `WARNING` when it can't open a file, so failures appear in the log rather than silently doing nothing.
- **ScreenScraper credential validation silently fell back to bundled dev credentials when `load_config()` raised.** The failure is now logged at `WARNING` level via `scraper_logger` so it appears in the scraper log file.
- **`mainmenu.py` accessed `HyperspinDatabase._root` directly** to iterate entries in XML element order. The logic is now behind the new public `HyperspinDatabase.iter_xml_order()` method, which falls back to dict order when the tree is unavailable.
- **Duplicate `import csv` inside `theme_scan`** (already imported at module level). Removed.
- **`_SpinDoctorGUI._format_bytes` was a copy of `_utils.format_bytes`** that could diverge silently. The GUI method now delegates to the shared utility.

### Added

- **`HyperspinDatabase.iter_xml_order()`** — public method that yields `GameEntry` objects in their original XML element order (using the parsed lxml tree when available, falling back to insertion-order dict iteration). Removes the need for callers to reach into the private `_root` attribute.

- **Favorites wheel always showed 0 entries.** `fav rebuild` (both the standalone binary and `spindoctor fav rebuild`) now automatically runs `fav sync` before building, importing HyperSpin's per-system F-key favorites (`favorite="1"` attribute and `_Favorites.ini` files) into SpinDoctor's store. Previously this was a separate command users had to know to run manually.
- **Silent failure when `rocketlauncher_dir` is not set or the path doesn't exist on disk.** The rebuild output now emits a clear WARNING before running if `rocketlauncher_dir` is absent from config or points to a directory that doesn't exist. Previously the build completed with `launchers: 0` and `system INI: (not written)` and no indication of why.
- **Rebuild output didn't show whether the system-level RocketLauncher INI was written.** All three wheel rebuilds now print a `System INI:` row showing the path written (e.g. `D:\Arcade\RocketLauncher\Settings\Recently Played.ini`) or `skipped` with a reason. The missing INI was the cause of HyperSpin's "Cannot find Recently Played.ini" / "Cannot find Most Played.ini" errors.
- **No hint when Recently Played / Most Played had 0 entries.** The rebuild now prints a note pointing to the expected RocketLauncher statistics path (`Settings/Global Statistics/<system>.ini`) when entries = 0, so users know where RL needs to be writing its stats.
- **Silent failures across CLI and shared modules now surfaced.** Several commands previously swallowed errors and returned empty results with no explanation. All affected paths now print actionable warnings or error messages:
  - `fav-sync` with no systems configured now prints a diagnostic hint instead of "Synced 0".
  - `recent-list` with `rocketlauncher_dir` unset now prints the missing-config message.
  - `stats show` with an empty stats file now prints context instead of exiting silently.
  - `ledblinky` commands with no ROMs found now print a path/config hint.
  - Orphan media and INI cleanup failures (in `fav` and `recent`) are now reported instead of silently swallowed.
  - Keyboard interrupt during `backup`, `migrate`, or `curate` now prints a warning naming what completed and what recovery command to run.
  - `themes undo` with a missing backup file now reports the error instead of exiting silently.
  - `doctor` with a corrupt match-cache JSON now reports `WARN` with the filename instead of silently skipping it.
  - RocketLauncher `Main Menu.xml` parse errors now print a warning to stderr instead of returning an empty system list.
- **`generate-config --apply` no longer overwrites files without a backup.** Before writing any file in-place, the previous version is copied to a timestamped `.bak` sibling (e.g. `MAME.20260521_143012.bak`). No backup is made when `--output-dir` is used (the live files are untouched). Affected files: `Settings/<System>.ini` per system, `Databases/Main Menu/Main Menu.xml`, and `Settings/Global Emulators.ini` (only when `--overwrite-global` is passed).

### Changed

- **Wheels tab: removed duplicate "Install Tools-menu helpers" button.** It already lives in the Tools tab; the copy in the Wheels tab was redundant and confusing.
- **Wheels tab: added "Sync favorites from HyperSpin" button.** Explicitly imports HyperSpin's per-system F-key favorites before rebuilding. The descriptive text now explains the intended Step 1 / Step 2 order.
- **Migrate tab: added "Current configuration" section.** "Show current paths" and "Run doctor" buttons let users verify what's configured before touching anything.
- **Migrate tab: added "Backup before migrating" section.** Pick a backup folder and create a full snapshot in one click before running a migration, so the previous state can be restored if anything goes wrong.
- **`generate-config --apply` output now shows exactly which files were written and backed up.** The per-system INI table gains a `Backup` column (`.bak` filename, or `new` for first-time writes). The `Main Menu.xml` section now prints the written path, the backup filename, and the count and names of systems listed.

### Added

- **Backup & Restore tab: component presets.** Two shortcut buttons now appear below the component checkboxes. "Config snapshot" selects `settings` + `databases` only — a lightweight backup (kilobytes, not gigabytes) of SpinDoctor's path configuration and HyperSpin game-list XMLs, ideal before moving files to a new drive. "Everything" restores all components ticked.
- **Metadata tab: "Restore DB backup…" buttons.** Appears in both the "Fetch metadata" and "Sync database to ROMs" sections. Picks from the timestamped `.bak` sidecars that `fetch-meta`, `update-db`, and `batch-edit` write automatically (when `config.backup_before_modify` is on) and restores the selected system's `<System>.xml` via the CLI — no file I/O in the GUI.
- **Metadata tab: "Restore RL INI backup…" button.** Appears in the "Sync database to ROMs" section alongside "Run generate-config". Restores the selected system's `RocketLauncher/Settings/<System>.ini` from the timestamped `.bak` sidecar that `generate-config --apply` writes before overwriting.

## [2.2.2] - 2026-05-20

### Fixed

- **Auto-refresh scheduled task no longer flashes a console window on log-on.** The Windows Task Scheduler command now uses `powershell.exe -WindowStyle Hidden` instead of `cmd.exe /c`, so the wheel-rebuild runs completely in the background. Re-register the task ("Schedule auto-refresh" in the Tools tab) to pick up the change.
- **"Cannot find recently Played.ini" in HyperSpin.** Rebuilding the Favorites, Recently Played, or Most Played synthetic wheel now also writes `<RocketLauncher>\Settings\<target_system>.ini` with `Default_Emulator=PCLauncher`. Without this file RocketLauncher had no system-level config and threw the error when HyperSpin tried to launch a game from those wheels. Re-run "Refresh selected" in the Wheels tab (or `spindoctor-recent rebuild --apply` / `spindoctor-fav rebuild --apply`) to generate the missing INI.
- **"PCLauncher does not know what exe, FadeTitle, and/or SteamID" for Toolbox entries.** The PCLauncher per-game INI written by `install-tools --add-to-system` was using the `[exe info]` format, which requires a `FadeTitle` (window-title to monitor). Refresh helpers are short-lived batch files with no persistent window; they now use `[Settings]` format (`ApplicationPath` / `StartIn`) which PCLauncher runs directly without window monitoring. Re-run "Install into wheel" in the Tools tab (or `spindoctor install-tools --add-to-system <system>`) to regenerate the INIs.

### Changed

- **`migrate --apply` (roms component) now prints a next-step reminder.** After a successful ROM migration, the CLI prints a one-line reminder to run `spindoctor generate-config --apply` with the GUI path, since RocketLauncher's per-system `Settings\<SystemName>.ini` files contain hardcoded `Rom_Path` values that are not rewritten by `migrate`.

### Docs

- **New "Moving only your ROMs to a new drive" workflow.** End-to-end example for the common case of moving a ROM folder to a new drive (e.g. `D:\Arcade\Games` → `J:\Games`) in `docs/workflows.md`, including the required `generate-config --apply` follow-up and the GUI path.
- **New "Already moved your ROMs manually" workflow.** Two-command recovery path for users who moved their games folder without using `spindoctor migrate` — update `roms_dir` in config, then run `generate-config --apply`.
- **"Things migrate does not move" — RocketLauncher system INIs now first bullet.** The omission of `Settings\<SystemName>.ini` from `migrate`'s scope was the most common post-migration surprise; it is now the first item in the list.
- **`generate-config` post-migration note added to `commands.md` and `gui.md`.** Both now explain that `generate-config --apply` writes directly into `rocketlauncher_dir` (no manual copying needed) and is required after any ROM migration.

## [2.2.1] - 2026-05-20

### Fixed

- **Main Menu.xml now matches the format HyperSpin itself ships.** Toggling "hide system" on the Main Menu tab was rewriting `Main Menu.xml` in the verbose HyperHQ schema — empty `<description>` / `<cloneof>` / `<crc>` / `<manufacturer>` / `<year>` / `<genre>` / `<rating>` children on every entry, `enabled="True"` on visible games, an XML declaration, and unknown attributes like `exe="true"` on the **Search** entry silently dropped. Without `exe="true"`, Hyperspin tried to render Search as a regular system wheel and bailed out with **"Error creating main menu"** (black screen). Main Menu entries now emit as `<game name="..."/>` — `enabled="False"` *only* on hidden entries, no children, no XML declaration, no `<header>` — exactly the shape HyperSpin's native Main Menu uses. `GameEntry` gains an `extra_attrs` round-trip bag so `exe="true"` (and any third-party HyperHQ-extension attributes) survive a rewrite end-to-end. The provisioning writer in `rocketlauncher.generate_hs_main_menu` / `upsert_main_menu_system` was rewritten to match, so freshly added systems aren't born broken.

### Changed

- **Per-system database round-trip preserves unknown `<game>` attributes.** Real-world per-system XMLs (HyperList exporter output, third-party HyperHQ tools) attach attributes like `index="true"` and `image="<letter>"` to game entries. These were previously dropped on first save through SpinDoctor; they now round-trip via the same `extra_attrs` mechanism. Per-system schema (full child elements + `<enabled>Yes|No</enabled>`) is otherwise unchanged.

## [2.2.0] - 2026-05-20

### Added

- **GUI: ScreenScraper developer-credential fields on the Setup tab.** ScreenScraper's api2 requires *both* per-user (`ssid`/`sspassword`) and per-app (`devid`/`devpassword`) credential pairs; without a registered dev pair every request returns HTTP 403 regardless of how correct the user creds are. The Setup tab now exposes `screenscraper_devid` and `screenscraper_devpassword` as first-class fields with the same `(saved)` / `(not set)` status surface as the user creds. The historical `"SpinDoctor"` placeholder values render as `(not set — bundled placeholder)` so users can immediately see that the dev pair is what's broken. Setup-tab help text + the `verify_screenscraper` 403 error both link to https://www.screenscraper.fr/membreinscription.php with copy-paste instructions for setting the new fields.
- **CLI: `config verify-credentials --ss-devid` / `--ss-devpassword`.** Unsaved Setup-form dev credentials can now be probed before saving, matching the existing `--ss-user` / `--ss-pass` flow.

### Changed

- **GUI: Setup-tab credential rows redesigned for clarity.** The previous `…abcd` last-4-chars hint was unreadable to users (it read as random text rather than "yep, there's a value saved"). Status text is now `(saved)` / `(not set)` and sits leftmost in the per-row control cell, followed by `[Show]` (or a button-width spacer on unmasked rows) and `[Clear]`. All five credential rows line up identically instead of looking ragged.
- **`verify_screenscraper` 403 error message.** When the rejected request used the bundled `"SpinDoctor"` placeholder devid, the failure message now explicitly names that as the cause and points at the registration page + Setup-tab fields, instead of letting users debug their user credentials in circles. Real devid values keep the terse failure message.

### Fixed

- **Main Menu "hide" actually hides items in Hyperspin.** SpinDoctor was writing `<enabled>No</enabled>` as a child element on Main Menu entries. Hyperspin's Main Menu loader honours the HyperHQ-style `enabled="True"|"False"` attribute on `<game>` (per-system game databases still use the child element, unchanged). A new `HyperspinDatabase.enabled_as_attribute` flag selects the schema; `spindoctor.mainmenu` opts in. Legacy child-element files migrate forward on the next save. Removed the previous self-heal logic in `database._update_game_element` that actively stripped the `enabled` attribute (it existed to fight a misdiagnosis of the same bug — both PR #144 and PR #148 were addressing the same broken UX from opposite directions).
- **XML saves are no longer single-line blobs.** The lxml parser was using `remove_blank_text=False`, which silently disables `pretty_print=True` on write. Switching to `remove_blank_text=True` restores indented, human-readable output across every XML round-trip (Main Menu, per-system databases, secondary sort axes). The cost is a cosmetic whitespace-only diff on first save against files that arrived single-line.

## [2.1.0] - 2026-05-20

### Added

- **GUI: "Restore from backup…" button on the Main Menu tab.** SpinDoctor writes a `Main Menu.YYYYMMDD_HHMMSS.bak` next to `Main Menu.xml` before every Save Order (when `backup_before_modify` is on — the default). The button opens a picker listing every sidecar backup with timestamp + size, and one-click restores the chosen snapshot. The pre-restore live file is itself sidecar-backed-up first, so the restore is undoable. No more dropping out of SpinDoctor and into Explorer to copy `.bak` files manually.
- **`spindoctor backup sidecar list / restore` CLI subcommands.** Canonical surface for the per-modify `.YYYYMMDD_HHMMSS.bak` files SpinDoctor's apply commands write next to mutated files. `list <file> [--json]` enumerates sibling backups newest-first; `restore <file> --from <bak> [--apply]` copies a sidecar back (dry-run by default, with a pre-restore backup of the live file so the restore is itself undoable).
- **`spindoctor config verify-credentials` CLI subcommand.** Probes ScreenScraper + TheGamesDB to check the configured credentials. Accepts `--ss-user` / `--ss-pass` / `--tgdb-key` overrides so candidate values can be tested without saving, falling back to saved config otherwise. `--json` output for the GUI Setup tab's Test credentials button.
- **`spindoctor backup list --json`.** Structured output of the SpinDoctor backups in a target folder (used by the GUI Backup tab's Scan button to populate the restore Combobox via the CLI instead of re-implementing the directory walk).
- **GUI: Setup tab masked-credential field UX.** Each masked credential field (`screenscraper_pass`, `thegamesdb_key`) now shows a small `…abcd` last-4 hint when a saved value is present (or `(empty)` / `(edited — not yet saved)` / `(cleared — not saved)`) plus a per-field **Clear** button. Removes the long-standing ambiguity where a masked-but-saved value looked identical to a blank field and the user couldn't tell whether the API key they thought was unset was actually being sent.
- **GUI: stuck-running detector.** If a subprocess exits but its stdout pipe never closes (Rich Live-display ANSI codes have been known to leave the GUI's line reader waiting on a missing newline), the drain loop now synthesises a `_DoneMarker` so the tab badge, Stop button, and status bar always escape the "running" state. Backup completes-but-the-UI-says-running is fixed.

### Changed

- **Main Menu tab now delegates to `spindoctor.mainmenu` instead of parsing/writing the XML itself.** The previous in-process implementation was the root cause of the Main Menu corruption (see Fixed). `_mm_refresh` / `_mm_save_order` now call `load_main_menu` / `save_main_menu` — same canonical reader and writer the CLI uses, with backup, XML declaration, and lxml comment preservation all handled in one place.
- **GUI Backup tab's "Scan" button shells out to `backup list --json`** instead of walking the target directory inline. Removes a duplicate folder-scan implementation.
- **GUI Setup tab's "Test credentials" button shells out to `config verify-credentials`** instead of importing `spindoctor.scraper` and calling `verify_*` in a worker thread. Output streams to the bottom Output panel + Logs tab through the standard `_run_cli` plumbing — same as every other command run.
- **GUI: credential-test output routed to the Output panel + Logs tab.** Previously the result was written to a small inline label inside the Setup form, which scrolled out of view and felt random. Now lives where every other action's output lives.
- **GUI: every scrollbar and pane sash uses the clam dark theme.** Replaced four `scrolledtext.ScrolledText` widgets (which embed classic `tk.Scrollbar`) with a themed `Text + ttk.Scrollbar` helper, and three `tk.PanedWindow` instances with `ttk.PanedWindow`. The Output panel, Logs tab viewer, first-run wizard panel, View-logs dialog, and every pane sash now match the rest of the app on Windows instead of showing native Win7 chrome.
- **`verify_screenscraper` returns include `devid=…` and the sent ssid-presence summary in every message** (success and failure). Makes a `HTTP 403 (Erreur de login)` debuggable from the Output panel alone — the user can immediately tell whether the default `devid="SpinDoctor"` is in use vs. a custom one, and whether the password was actually sent.
- **`verify_thegamesdb` rejects suspicious HTTP 200 responses.** TheGamesDB has been observed returning OK + public data for some invalid/empty keys; the verifier now treats a 200 with no `*allowance*` field as failure ("Suspicious 200 — response carries no per-key allowance counter"). Obvious-junk keys (whitespace / <8 chars) are short-circuited without contacting the API.
- **Rich `Progress` is auto-disabled in non-tty mode** via a `_make_progress` helper that auto-passes `disable=not sys.stdout.isatty()`. Terminal users see the live spinner as before; GUI-piped subprocesses get clean newline-terminated lines instead of ANSI cursor-control sequences. Removes a class of hang where the line iterator in the GUI's pipe reader waited indefinitely for a newline that Rich's Live display never emitted.

### Fixed

- **Main Menu.xml no longer gets corrupted by the GUI's Toggle Visible + Save Order flow.** The GUI was reading `enabled` from a `<game enabled="…">` XML attribute (which HyperSpin never sets) and writing it back the same way, while HyperSpin and SpinDoctor's CLI both use a `<enabled>Yes|No</enabled>` child element. Saving stamped a phantom `enabled="No"` attribute onto every game and left the real child element unchanged, producing a shape HyperSpin rejects with "Error creating main menu" on startup. Now reads and writes the child element exclusively (via `spindoctor.mainmenu`). The canonical writer also strips any stale `enabled` attribute on save (`database._update_game_element`) so files previously corrupted by this bug self-heal on the next save through either the GUI or the CLI.
- **GUI: `_on_proc_done` and `_drain_queue` are now exception-safe.** A `TclError` on a destroyed widget during `_on_proc_done` used to propagate out of `_drain_queue` and prevent the next `root.after(50, …)` re-registration, permanently stopping the drain loop and leaving the GUI stuck in "running" state. Both functions now wrap their bodies in try/finally; the busy state is always cleared, and the drain loop always re-arms.

## [2.0.1] - 2026-05-19

### Added

- **Scraper debug log file at `~/.spindoctor/scraper.log`.** Every ScreenScraper and TheGamesDB request now records its (redacted) URL + params, the response status, and the first ~500 chars of the body on any HTTP >= 400. A rotating handler (512 KB × 2 backups) keeps the file from growing. Verify dialog failures also surface the response body inline so the upstream error ("Erreur de login", "Invalid API key", rate-limit notice) is visible without opening the log. Closes the "verify returns 403, dialog says nothing useful" debugging gap.
- **`screenscraper_devid` / `screenscraper_devpassword` config keys.** Advanced override for ScreenScraper's per-app developer credential pair (separate from the user's `ssid`/`sspassword`). Defaults to the historical `"SpinDoctor"`/`"SpinDoctor"` values, but can now be overridden when ScreenScraper has issued you a real registered developer credential or rejects the defaults. Set from the GUI's Custom Command tab with `config set screenscraper_devid <value>` — no Setup-tab field, because cabinet owners shouldn't need to think about this.
- **`docs/cli-cheatsheet.md`** — punchy copy-paste cheatsheet grouped by intent (discover & diagnose, edit & curate, metadata & media, backup / diff / migrate, custom wheels, themes, light guns, config), complementing the deep per-flag reference in `docs/commands.md`.

### Changed

- **GUI: scrollbar thumb is now clearly distinguishable from the trough.** The dark-theme scrollbar had the thumb at `#3a3a3c` against a `#252526` trough with a hand-flattened bevel — readable only if you already knew where to look. New `_DARK_SCROLL_THUMB` (`#6a6a6e`) / `_DARK_SCROLL_THUMB_ACTIVE` (`#8a8a8e`) pair plus the restored clam bevel give the draggable element obvious affordance and a visible hover state.
- **Docs: README CLI section restructured + doc-wide cleanup pass.** The README's GUI tab description was a single ~1500-word run-on paragraph; now a scannable bullet list. The CLI cheatsheet sampler was moved out of the README into its own `docs/cli-cheatsheet.md`. Cross-doc cleanup removed duplicate Menubar / flashing-window / `schtasks` blocks, collapsed a 130-word `installation.md` table cell, added scannable summaries to `workflows.md` and `configuration.md`, and bullet-listed `setup.md` step 9.

### Fixed

- **Windows: bundled `.exe` icon now actually appears.** `build/build_windows.py` was invoking PyInstaller without `--icon`, so Explorer / taskbar / Alt-Tab always rendered the default Tk feather even though `spindoctor/assets/icon.ico` had been committed since 1.x. It was also missing `--add-data` for `spindoctor/assets/`, which meant the runtime `iconbitmap()` call in `_apply_icon()` silently failed inside the `--onefile` frozen process (assets weren't extracted alongside `__file__`), so the window-header icon was also the feather. Both flags are now wired into `run_pyinstaller()`; next release rebuild ships the custom icon everywhere Windows shows one.
- **Docs: broken README anchor + slugified `commands.md` heading anchors.** The README's `[CLI cheatsheet](#cli-cheatsheet)` pointed at a non-existent in-README anchor (the section had moved into its own doc); now links to `docs/cli-cheatsheet.md` directly. Several `commands.md` H3 headings carried em-dash descriptive suffixes (e.g. ``### `batch-edit` — set/clear/append…``) which slugified to long anchors and broke every `commands.md#batch-edit`-style link in the cheatsheet. Suffixes folded into the body text so the simple `#<command>` anchors resolve. The cheatsheet's `commands.md#stats-report` link was also broken (no such heading); now points at the parent `#playtime-stats` section.

## [2.0.0] - 2026-05-19

### Fixed

- **GUI: `_flash_status` revert no longer crashes if the window is closed mid-flash.** The 6-second auto-revert (added with the popup → status-bar conversion in #136) was wrapped in `try/except` at `root.after` registration, but the callback *body* (`_set_status` → `StringVar.set`) could still raise `TclError` after teardown — surfacing as a noise traceback via the unraisable hook (Py3.12 + pytest flake territory). The revert body is now guarded.
- **GUI: fresh-install users auto-land on the Setup tab.** With the first-run wizard now opt-in (#134) and the routine popups silenced (#136), a brand-new cabinet owner with no `config.json` yet had only the bottom-of-window status bar pointing them at "Setup incomplete — N path(s) need attention." The GUI now selects the Setup tab automatically when `config.json` doesn't exist yet; the `gui_last_active_tab` persistence is preserved for everyone else.

### Documentation

- **Comprehensive doc refresh for the friction-audit PR sequence (#123–#138).** All user-facing docs now reflect the actual shipped state:
  - `README.md` and `docs/setup.md`, `docs/installation.md`: first-run wizard described as opt-in (Setup-tab button + Help menu), with fresh-install Setup auto-focus mentioned.
  - `docs/gui.md`: async startup ("Scanning library…") and fresh-install Setup focus documented under Launching; new "Quiet success, audible validation" subsection covering `_flash_status` / `_flash_validation`; Curate delete confirm text updated to mention the regions/revision summary and the no-undo wording; Systems-tab section corrected to describe the single-dropdown "Re-review titles for a PC system" form; Up-to-date update-check result now noted as status-bar (not modal).
  - `docs/configuration.md`: five new persistent config keys documented (`gui_meta_subset`, `gui_curate_regions`, `gui_meta_auto_best`, `gui_meta_all_games`, `gui_meta_no_cache`) with the explicit "Apply / dry-run toggles are deliberately NOT persisted" note.
  - `docs/commands.md`: `fetch-media --skip-ambiguous`, `add-pc-system --no-interactive`, `pc-rename --no-interactive` documented with their use cases.
  - `docs/troubleshooting.md`: new entries for the Tools-tab "access denied" friendly schtasks errors, Ctrl+C recovery semantics for backup/migrate/curate, and disabling the update check; menubar reference updated to list Keyboard shortcuts.
  - `docs/migrating-from-1.x.md`: config-keys table expanded to seven, new-affordances list expanded with async startup / fresh-install Setup focus / popup demotion / Curate-delete clarity / re-review-titles form / friendly schtasks errors; new CLI-flags section covers `fetch-media --skip-ambiguous` and `add-pc-system` / `pc-rename --no-interactive`.

### Added

- **GUI: async startup.** The Setup-tab population scan (`_refresh_systems`) and the startup health checks (`_startup_health_checks`) used to run synchronously on the main Tk thread before the window painted — on a slow NAS-mounted HyperSpin Databases dir this caused a noticeable "is it frozen?" beat at launch. Both now run from `after_idle` while the status bar shows "Scanning library…"; the window is interactive immediately.
- **GUI: persistent non-destructive preferences.** Three new `Config` fields keep your last-used picker state across launches: `gui_meta_subset` (the multi-system fetch-meta picker), `gui_curate_regions` (Curate tab region tickboxes), and `gui_meta_auto_best` / `gui_meta_all_games` / `gui_meta_no_cache` (the fetch-meta checkbox row). Apply / dry-run toggles are deliberately NOT persisted — destructive operations always require an explicit per-run opt-in. New helper `_persist_meta_pref` wraps the load → setattr → save dance and swallows write errors so persistence failure never disrupts the workflow.
- **CLI: `add-pc-system --no-interactive` and `pc-rename --no-interactive`.** Auto-accept every proposed title without prompting. Required from non-TTY contexts (the GUI uses it by default when adding a PC system, where the interactive `input()` review path would otherwise hang the subprocess).
- **CLI: `fetch-media --skip-ambiguous`.** Mirrors `fetch-meta --skip-ambiguous`. When a media slot has multiple candidates, skip it instead of either prompting (`--pick-media`) or auto-picking. Cron / CI users now have a no-block escape for the per-media-slot picker.
- **`matcher.choose_match(skip_ambiguous=True)`** and **`matcher.pick_media(skip_ambiguous=True)`** library kwargs. Public API for callers that need the no-prompt no-auto-pick behaviour (returns `None` for ambiguous candidate lists).

### Changed

- **GUI: routine success / validation popups demoted to the status bar.** Cabinet owners hit `messagebox.showinfo` modals constantly during normal use — "Saved", "Auto-refresh task deleted", "Up to date", "No subset picked", "Nothing to apply", "Nothing selected", etc. These now use a new `_flash_status` helper (writes to the status bar, auto-reverts to "Ready." after 6 s) for success outcomes, and `_flash_validation` (status + an audible bell) for "fill in the field first" prompts. Multi-line dialogs that convey real result info (Preflight passed, Curate done with manifest, Scheduled with reboot instructions) stay as modals. Net: ~10 unnecessary click-throughs eliminated from a typical session.
- **GUI: Curate delete confirmation dialog rewritten for clarity.** The final destructive-confirm now includes the target system, the regions kept, and the revision preference so the user can re-verify their intent at a glance — and the wording explicitly notes there is no undo for delete mode and points at archive mode as the reversible alternative.
- **First-run wizard is now opt-in.** The wizard no longer auto-opens at GUI launch — it's available from a new **Setup tab → Run first-run wizard…** button and from the existing **Help → First-run setup…** menu item. Cabinet owners who already approved the upgrade by launching the binary don't need a modal between them and the Setup tab; the existing startup health-check status-bar message already surfaces missing-config problems. The `first_run_complete` config field is removed (no longer needed for auto-fire gating); pre-existing configs with the key set are silently ignored.

### Fixed

- **GUI `add-pc-system` no longer hangs on the title-review `input()` prompt.** The Systems tab's "Run add-pc-system" button now always passes `--no-interactive` so the subprocess auto-accepts every proposed title. Users who want to curate titles can run `spindoctor pc-rename <system>` from a terminal.

### Removed

- **GUI: Help → "What's new" dialog and the `last_seen_version` config field.** The auto-opening one-shot dialog (added earlier in the 2.0 cycle) was extra friction for cabinet owners who'd already approved the upgrade by launching the binary — they don't need a wall of bullets on launch. The full CHANGELOG is still one click away (Help → About → CHANGELOG link). The `last_seen_version` config key is removed; existing configs that have it set are silently ignored.

### Fixed

- **`backup` and `migrate` now write a partial manifest on Ctrl+C.** Previously, `apply_backup` / `apply_migration` re-raised `KeyboardInterrupt` without calling `_write_manifest`, so completed components in the backup root — or completed moves in a destructive migration — had no `manifest.json`. `list_backups` filters on the manifest existing, so the work was invisible from the GUI; `migrate --undo` had nothing to replay, so an interrupted move-mode migration was unrecoverable except by hand. Both functions now persist a manifest of whatever DID complete before re-raising. Move-mode migrate also stamps the config update for any completed moves so the config no longer points at empty old locations. Curate already did this correctly; backup and migrate now match.
- **GUI `fetch-meta` no longer hangs the subprocess on stdin.** When the "Auto-pick best match" checkbox was unticked, the GUI invoked `fetch-meta` with no `--auto-best` / `--skip-ambiguous` flag and the CLI fell back to `config.interactive_matching=True`, which called `input()` from `matcher._prompt` on ambiguous matches — a stdin wait the GUI cannot satisfy. The checkbox now defaults to ticked, and the unchecked path passes a new `--skip-ambiguous` flag so ambiguous matches are logged and surfaced in the next `audit` pass instead of prompting. The interactive `--interactive` flag still works for terminal users.
- **GUI singleton lock no longer races on release.** `SingletonLock.release()` previously closed the file handle and then unlinked the lock file; in the gap a second instance could open the same path, lock its inode, and then have the first instance unlink it out from under them — letting a *third* instance create a new inode and acquire its own lock. `release()` now leaves the file on disk and lets the OS drop the lock on close. The stamped PID is overwritten by the next acquire.
- **Main Menu.xml parse errors are now visible.** A malformed or locked `Main Menu.xml` previously printed a single line to the Output pane and left the Treeview showing stale rows from the last successful load — easy to act on without realising the data was wrong. The tab now clears the table on failure AND pops a modal naming the file path and the parser's error, so the failure is impossible to miss. The Output pane still gets the raw error for grepability.

### Added

- **`fetch-meta --skip-ambiguous`.** New CLI flag that logs ambiguous matches and moves on, instead of either auto-picking the top candidate (`--auto-best`) or prompting (`--interactive`). The GUI uses this so the subprocess never blocks on stdin; CLI users on non-TTY shells (cron, CI) can use it too.
- **GUI: Migrate now confirms before `--apply`.** Parity with the existing Backup-Restore confirm. The dialog wording adapts to the mode: `--keep-source` shows a milder "copy to new drive, originals stay" message; the default destructive move warns explicitly that originals will be removed and points at the undo-manifest escape hatch as the only recovery. Cancel and nothing runs.
- **GUI single-instance lock.** Launching `spindoctor-gui` while another window is already open now shows a warning and exits cleanly instead of starting a second process. Two windows editing the same HyperSpin XML at the same time can corrupt the library — the lock is a `fcntl.flock` / `msvcrt.locking` exclusive file handle stamped at `~/.spindoctor/gui.lock`, which the OS releases automatically when the process exits (so a crashed instance never poisons future launches). The check can be bypassed with `SPINDOCTOR_DISABLE_SINGLETON=1` for the rare power-user multi-window case.
- **GUI: Help → "Keyboard shortcuts" dialog.** Surfaces the full shortcut map (`Ctrl+1`…`Ctrl+9` jump to tab, `Ctrl+=` / `Ctrl++` / `Ctrl+-` / `Ctrl+0` zoom, `` Ctrl+` `` toggle Output, `Ctrl+F` open find bar, `Ctrl+Shift+F` toggle system quick-filter, `Esc` close dialogs). Previously defined in code but only documented in `docs/gui.md` — cabinet owners had no in-app discovery path.
- **GUI: About dialog now shows the app icon** next to the title when the bundled PNG icon loaded at startup.

### Fixed

- **Ctrl+C cleanup for `backup`, `migrate`, and `curate`.** Interrupting a long-running operation mid-copy previously left half-written state behind: a partial component directory in the backup root, a half-copied destination tree from `migrate --keep-source`, or files stranded in `_retired/` with no manifest record so `curate --undo` couldn't roll them back. `apply_backup` and `apply_migration` (keep-source mode) now `rmtree` the in-flight destination on `KeyboardInterrupt` before re-raising; `apply_curation` writes a partial manifest of the files it managed to archive so undo still works. Already-completed components are deliberately left in place — the user may want them — and `migrate`'s non-keep-source move path is deliberately not cleaned up (a partially-moved source is the one thing worth NOT making worse).

### Documentation

- **Removed broken screenshot references.** Every `![…](images/gui-launcher-*.png)` line in `docs/gui.md` and `docs/windows-binaries.md` pointed at files that never shipped (the `docs/images/` directory contained only a `.gitkeep`). Stripped the references and deleted the directory; the docs read fine without them. Screenshots can be re-added in a future PR.
- **`docs/gui.md` Migrate-tab + Main Menu-tab descriptions** now document the new confirm dialog and the parse-error modal respectively. **`docs/troubleshooting.md`** gains a "Main Menu.xml could not be parsed" entry with the three common causes and the fix recipe. **`docs/migrating-from-1.x.md`** lists the migrate confirm + main-menu modal in the new-affordances section.
- **2.0-readiness doc refresh.** Every audit gap closed: `docs/configuration.md` lists the `SPINDOCTOR_DISABLE_SINGLETON` env var; `docs/gui.md` documents the **Help → Keyboard shortcuts** dialog, the single-instance lock, and the Ctrl+C / Stop safe-interrupt semantics, and the keyboard-shortcut table now covers `Ctrl+=` and `Esc`; `docs/migrating-from-1.x.md` lists the new GUI affordances (singleton lock, Keyboard-shortcuts dialog, Ctrl+C safe interrupt, `--skip-ambiguous` wiring); `docs/commands.md` documents `fetch-meta --skip-ambiguous` with a full three-way override table (`--auto-best` / `--skip-ambiguous` / `--interactive`) and a top-of-doc note on safe interrupts; `docs/troubleshooting.md` adds entries for the Win 7 TLS-handshake symptom, the "second GUI won't open" by-design behaviour, and the post-crash `gui.lock` file; `README.md` line 84 surfaces the new Help-menu dialog, the About-dialog icon, and the singleton lock alongside the existing GUI feature paragraph. No semantic changes to existing docs — additive only.
- **New `docs/gui.md` — canonical GUI walkthrough.** The tab tour, menubar reference, keyboard-shortcut map, find bar, system quick-filter, dark-mode notes, dry-run-feedback walkthrough, first-run wizard, and per-tab health-badge legend now live in one platform-neutral page. Previously the tab tour lived inside `docs/windows-binaries.md` under the implicit assumption "GUI = Windows binary"; pip and source installs had no canonical home. The Windows-binaries page now links to `gui.md` instead of duplicating it.
- **New `docs/migrating-from-1.x.md` — upgrade guide.** Documents the visible 2.0 differences for existing 1.x users: tab reorder (with the keyboard-shortcut note that `Ctrl+1`…`Ctrl+9` still works), the new GUI config keys (`gui_window_geometry`, `gui_last_active_tab`, plus persistent picker state added later in the 2.0 cycle), new GUI affordances (find bar, drag-drop, badges, preflight, multi-system fetch-meta), new CLI commands (`self-doctor`) and audit flags (`--no-media`, `--detailed`, `--report`), and the rollback recipe.
- **`docs/commands.md` — `self-doctor` now has a Maintenance entry.** Previously the command was only mentioned in passing in the README. The new section explains the diff from `doctor` (cabinet vs SpinDoctor's own state), what `--fix` is allowed to delete (only orphan rescue copies + stale `.part` files — manifests are never auto-deleted), and the recommended cadence.
- **`docs/configuration.md` — new GUI config keys documented.** `gui_window_geometry` and `gui_last_active_tab` (initial 2.0) plus the picker-persistence keys added later (`gui_meta_subset`, `gui_curate_regions`, `gui_meta_auto_best`, `gui_meta_all_games`, `gui_meta_no_cache`) all with their semantics, defaults, and reset instructions.
- **`docs/setup.md` step 9 is now GUI-first.** Cabinet owners who land on the walkthrough fresh get pointed at `spindoctor-gui` (Setup tab + Save) as the primary path; CLI is listed as the equivalent power-user path rather than the equally-recommended alternative.
- **Read-only command lists in `docs/index.md` and `docs/commands.md` updated** to include `find-global`, `self-doctor`, `tools-audit`, and `lightgun detect` / `audit` — all of which were technically read-only but missed the canonical convention header.

### Changed

- **GUI: end-user-facing text no longer leaks CLI command names at cabinet owners.** The Setup tab intro previously said "These map 1:1 to `spindoctor config init`" and the scraper-credentials note pointed at "`spindoctor fetch-meta` and `spindoctor fetch-media`" — neither is meaningful to someone who only opens the GUI. Both now read as plain-English summaries of what the controls do. The undo dialog that pops on an unrecognised manifest type stopped pointing users at "`spindoctor --help`"; the curate-archive confirmation stopped saying "`spindoctor curate --undo`". Both now describe the GUI path (Help → About, Logs tab → Browse manifests / undo…).

### Fixed

- **CLI: `backup create`, `backup restore`, `migrate`, and `rename` / `clone` now humanize OSError output.** Previously these four `except (FileExistsError, OSError)` blocks printed `str(e)` verbatim — on Windows that surfaced as `[WinError 32] The process cannot access the file …`, technically correct and useless to a cabinet owner. They now route the exception through `spindoctor._errors.humanize_oserror`, matching the GUI's Main Menu save worker and "Could not launch" subprocess-spawn path. WinError 32 reads as "currently in use — close HyperSpin and try again"; ENOSPC reads as "free up some space"; EACCES reads as "Properties → untick Read-only"; etc.

### Internal

- **Shared `spindoctor._utils` module.** `format_bytes` (formerly duplicated in `backup.py` and `migrate.py`) and `free_bytes` (formerly duplicated in the same two modules) now live in `spindoctor._utils`. The byte formatter also subsumes `cleanup.format_size`, which is now an alias for `format_bytes`. Each owning module re-exports the helpers so existing callers like `from .backup import format_bytes` and `from .cleanup import format_size` keep working unchanged.
- **Dead code removed.** Deleted `cli._backup_format_includes` (defined but never called), the unused `import shutil` in `self_doctor.py`, and the unused `import pytest` in `tests/test_errors.py`. Ruff is now clean across `spindoctor/` and `tests/`.

### Tests

- **CliRunner smoke pass for 12 read-only / dry-run-by-default CLI commands.** New `tests/test_cli_read_only_smoke.py` exercises `audit`, `inspect`, `find-dupes`, `lint`, `find-orphan-media`, `cleanup audit`, `report` (summary + CSV), `doctor`, `tools-audit`, `systems`, plus dry-run gates for `update-db` and `add-system`. Closes the gap the 2.0 audit flagged — 60+ commands had zero end-to-end CLI coverage; the most-used diagnostic and database-mutating commands now have plumbing-level pins so an import error or option-parsing regression fails CI at PR time instead of on a user's cabinet. Per-command behaviour is still covered by the dedicated library-layer tests; this file's job is the CLI plumbing.
- **GUI 2.0-surface tests.** New tests in `tests/test_gui.py` cover the four multi-widget surfaces that shipped during the 2.0 cycle and previously had only the construction-smoke as coverage: the Output-panel find bar (`_find_open` → type → Next/Prev → `_find_close`), the first-run wizard (Help → First-run setup… dialog construction), the preflight chain button (`_run_preflight` dispatches `doctor` → `tools-audit` → `audit --all` then summarises), and the Setup-tab drag-and-drop wiring (`_register_path_drop_target` no-ops without `tkinterdnd2`, wires the StringVar from a brace-quoted or `file://`-prefixed drop payload when present). Same class of multi-widget construction bug as the v1.7.0 `_output` AttributeError that project memory warns about; previously zero coverage.

### Fixed

- **Win7 cabinet TLS handshake.** Outbound HTTPS sessions in `scraper.py` (ScreenScraper, TheGamesDB) and `media.py` (asset CDNs) now pin a TLS 1.2 floor via a shared `spindoctor._net.make_session()` helper, matching the same floor `update_check.py` already enforces for its urllib path. Frozen Win7 binaries ship Python 3.8.10 + OpenSSL 1.0.2u, which on a bare `requests.Session()` could otherwise negotiate TLS 1.0/1.1 against endpoints that have since dropped them — surfacing as a cryptic `EOF occurred in violation of protocol` rather than a clean handshake error. Credential-verify probes (`verify_screenscraper`, `verify_thegamesdb`) inherit the same floor via a new `request_get()` helper.
- **GUI dark-theme init on Tk 8.5.** `_apply_dark_theme` now strips Tk 8.6-only `arrowcolor` keys via a `_safe_configure` wrapper when the running Tk doesn't accept them, instead of raising mid-init and leaving the rest of the dark theme unapplied. Python 3.8 on Win7 ships Tk 8.5 where `arrowcolor` on `TCombobox` / `TSpinbox` / `T*Scrollbar` is unknown; previously the configure would raise a `TclError` partway through theming and the window would render with default light colours.

### Added

- **GUI: First-run wizard.** Opt-in 3-step modal (Welcome → pick `roms_dir` + `hyperspin_dir` → run `spindoctor doctor` inline and show a per-check ✓/⚠/✗ summary) reachable from the Setup tab's **Run first-run wizard…** button and from **Help → First-run setup…**. An earlier draft of the 2.0 cycle auto-opened the wizard on launch and stored a `first_run_complete` config flag; both were removed before release — see the corresponding `### Changed` / `### Removed` entries above.

- **GUI: Per-tab health badges.** Each tab shows ⚠ or ✗ next to its name when the relevant area has a problem detected by `spindoctor doctor`. Cabinet owners can scan the tab strip and see at a glance which areas need attention without running any command. Mappings include: `Paths` / `Metadata APIs` → Setup, `HyperSpin databases` → Audit & Doctor, `Match cache` → Curate, `LEDBlinky` → LEDBlinky, `Media folders` / `Global Emulators.ini` → Metadata & Media, `External binaries` → Tools + Setup. The doctor pass runs on a worker thread (doesn't delay first paint) and re-runs after every Setup save so badges stay current. Run-progress badges (⟳/✓/✗) still render at the right edge so a tab can show both at once — e.g. `LEDBlinky ⚠ ⟳`.

- **GUI: Metadata tab → multi-system selector for fetch-meta.** A "Pick subset…" button opens a modal multi-select `Listbox` of every configured system. Select-all / Clear / Cancel / OK; the picked subset is remembered for re-opening. A new "Run on subset…" button chains `fetch-meta --system X` once per picked system (with a confirmation dialog showing system count + dry-run / apply mode), aborting on the first non-zero exit code. Designed for cabinets with 20+ systems where the user wants to refresh half of them after a scraper-data improvement — previously this required either 15 manual clicks or dropping to a CLI loop.

- **GUI: Output panel find bar (Ctrl+F / Cmd+F).** Press Ctrl+F (Cmd+F on macOS) to open a slim search bar above the Output panel. Type to highlight every case-insensitive match in the buffer; Enter / Next jumps to the next match, Shift+Enter / Prev to the previous, Esc closes the bar. Match count ("3 of 17") shown next to the controls. Selected text pre-seeds the search field on open. The global binding works regardless of current focus.

- **GUI: Systems tab → Per-system overrides form.** Surfaces `config system set` with a system dropdown and form fields for ScreenScraper ID, TheGamesDB ID, ROM extensions (comma-separated, leading dot optional), layout (`per-game-folder` / `multi-disc-m3u` / `flat`), and emulator name. "Load current values" prefills the form from the saved override; "Save override" calls the CLI with only the flags the user actually filled in (so partial edits don't clear other keys). Designed for niche systems (homebrew consoles, PC libraries, custom MAME variants) that stock SpinDoctor doesn't know — previously CLI-only territory.

- **GUI: Curate tab → metadata-match cache controls.** "List cached matches" and "Clear cache…" buttons drive `spindoctor match list|clear` with an optional system filter. The clear button shows a confirmation dialog scoped to the selected system (or "ALL systems" if blank).
- **GUI: Systems tab → Organize a system.** Drives `spindoctor organize <SYSTEM>` with checkboxes for `--no-sort` and `--restructure`. Restructure honours the tab's existing Apply toggle, plus a separate "Undo latest restructure" button for the `--undo` flow.
- **GUI: Metadata & Media tab → Add one local media file.** System + game + media-type dropdowns plus file picker drive `spindoctor media-add`. Tickable "Move" and "Overwrite if target exists" flags. Useful for one-shot media additions (a manually-grabbed trailer, a hand-picked wheel) without dropping to the CLI.
- **GUI: Audit tab → CSV report path + flag toggles.** "Report CSV (optional)" entry + Browse… button feeds `audit --report`; new checkboxes for `--no-media` (skip media checks for faster runs) and `--detailed` (richer per-file output). Both `Audit selected system` and `Audit all systems` use the same options.
- **GUI: Diagnose tab → "Find cross-system dupes" button** drives `find-dupes --cross-systems` so users don't have to drop to Custom Command for cross-system duplicate detection.
- **GUI: Metadata tab → Fetch-meta source / threshold / no-cache.** A "Source" dropdown picks `screenscraper` / `thegamesdb` / config default; a "Threshold" entry overrides the project-default fuzzy-match floor; a "Skip cache" checkbox forces every game to hit the API. Threshold input is validated client-side (0.0–1.0) before launching the subprocess.
- **GUI: Setup tab → "Open" button next to every path field.** Verifies what the user just configured by jumping to the path in Explorer / Finder. For `mame_executable` it opens the containing folder, since that's what users actually want to see.
- **GUI: Update notification → one-click "Download…" button in the status bar.** When an update is available, a Download… button appears next to Stop and opens the release page directly. Previously users had to dig through Help → Check for updates and confirm a messagebox.
- **GUI: Tooltips on the most-confusing controls.** New `_attach_tooltip` helper shows a small dark Label after a 500 ms hover. Applied to fetch-meta's three checkboxes (`--auto-best`, `--all-games`, `--no-cache`) where the flag names alone don't capture what they actually do.
- **GUI: Persistent window geometry + last-active tab.** The GUI now remembers its window size, position, and which tab you were on the last time you closed it, and restores them on the next launch. Stored in `config.json` under `gui_window_geometry` / `gui_last_active_tab`. Saved once on close (not on every `<Configure>` event) so resizing the window doesn't thrash the config file. Hand-corrupted geometry strings are revalidated against a regex before being handed to Tk so a bad value can't break startup. Cabinet owners who live in the Curate or Wheels tab no longer re-navigate from Setup every launch.
- **GUI: Logs tab → "Browse manifests / undo…" shortcut button.** The existing `File → View logs & manifests…` modal already exposes per-run undo, but new users discovering the Logs tab had no signpost. Added a button next to Refresh/Copy/Clear (separated by a vertical Separator to mark it as related-but-distinct).
- **GUI: Determinate progress bar for chained workflows.** "Refresh all wheels", "Register wheels in Main Menu", and the Metadata tab's "Full refresh" each run multiple subprocesses end-to-end. The status-bar progress widget previously stayed in indeterminate-spinner mode for all of them, giving no sense of how far through the chain the user was. It now switches to a determinate fill anchored to step/total for chained runs, then reverts to the spinner for single-command runs. New `_chain_start` / `_chain_advance` / `_chain_end` helpers keep the call sites declarative.
- **GUI: Audit & Doctor tab → "Preflight check…" button.** One-button "is the cabinet ready for guests?" chain that runs `doctor` → `tools-audit` → `audit --all` end-to-end. Tallies pass/fail by exit code and pops a verdict messagebox at the end (green "Cabinet is ready" / yellow "N issues found"). Continues past failures so a partial cab state is still informative — if `tools-audit` reports missing MAME, the user wants to know about that *and* whether `audit --all` flagged broken media too. Designed for the "I'm taking the cab to a LAN event tomorrow" moment when running three commands by hand is error-prone.
- **CLI: `spindoctor self-doctor`.** New diagnostic command for SpinDoctor's own state (not the cabinet library). Inspects `~/.spindoctor/` for orphan corrupt-config rescue copies (older than 30 days), oversized manifest dirs (curate / migrations / edits / renames / themes / media_imports / restructures over 50 MB), expired metadata cache size, broken `config.json` / `favorites.json`, and stray `.part` files older than 7 days under `<HyperSpin>/Media/`. Read-only by default; `--fix` performs only safe deletions of rescue copies and stale `.part` files. Manifests are never auto-deleted (they're the undo path). Reports totals reclaimable bytes so the user can decide.
- **Humanized OSError messages.** New `spindoctor._errors.humanize_oserror()` translates the most common filesystem-error patterns into one-sentence, actionable messages: WinError 32 ("HyperSpin is currently open — close it and try again"), EACCES ("file is read-only / SpinDoctor lacks permission — Properties → untick Read-only"), ENOSPC ("no space on drive X — free up some"), ENOENT ("path moved or deleted — check the Setup tab"), EISDIR / ENOTDIR / EEXIST / EROFS / ENAMETOOLONG / WinError 206, with a graceful fallback to `str(exc)` for unrecognised codes. Wired into the GUI's "Could not launch" subprocess-spawn failure path and the Main Menu save worker's OSError handler. Library is available for any other call site to consume.
- **GUI: System quick-filter (Ctrl+Shift+F / Cmd+Shift+F).** A toggle-able filter bar above the tab notebook that narrows *every* system combobox across every tab to entries containing the typed text (case-insensitive). On a cabinet with 50+ systems, typing "mega" instantly shows only Mega Drive / Mega CD / Sega Mega-Tech everywhere. Esc closes the bar and clears the filter; the Clear button does the same without closing.
- **GUI: Drag-and-drop folders onto Setup-tab path fields.** When `tkinterdnd2` is installed (bundled into the frozen Windows .exe; `pip install spindoctor[gui]` or `[all]` for pip users), dropping a folder from Explorer / Finder onto any path Entry on the Setup tab fills the field with the dropped absolute path. The intro text gains a 💡 hint when the affordance is available. Graceful no-op when the dep isn't present.
- **GUI: `_fav_remove` confirms before removing.** Matches the pattern used by the other destructive controls (ignore remove, mainmenu remove, curate delete). The favorite itself is reversible via `fav add`, but the user shouldn't have to know that to feel safe clicking the button.
- **GUI: Tooltips on the most-confusing destructive controls.** Curate's action dropdown (archive vs delete — with the irreversibility caveat for delete), the curate / migrate / backup-restore Apply checkboxes (what dry-run vs apply actually does, where the manifest goes, whether undo is possible), and Migrate's `--preserve-names` flag (canonical vs verbatim folder names). Extends the same `_attach_tooltip` helper introduced for fetch-meta's flags.
- **GUI: Inspect-a-single-game controls on the Diagnose tab.** A system dropdown + optional ROM entry + Inspect button drives `spindoctor inspect` directly — the highest-value diagnostic command after audit was previously only reachable via Custom Command.
- **GUI: Manage individual favorites on the Wheels tab.** System / ROM entry plus Add / Remove / List buttons wired to `spindoctor fav add|remove|list`, so curating the cross-system Favorites wheel doesn't require dropping to a terminal.
- **GUI: Rename and clone a single game on the Systems tab.** System / Game / New name fields drive `spindoctor rename` and `spindoctor clone` with the tab's existing Apply checkbox. Both commands write an undo manifest, so even a wrong rename is reversible from the Logs tab.
- **GUI: Indeterminate progress bar in the status bar.** Appears next to the Stop button while a subprocess is streaming, vanishes when it exits. Multi-hour migrate / audit runs no longer look like a hung GUI when the output panel is quiet.

### Changed

- **Internal cleanup: deduplicated `_dir_size`, PCLauncher `[exe info]` body, and stray module-level re-imports.** `_dir_size` was implemented three times across `backup.py`, `migrate.py`, and `fileinfo.py` (the third copy was a one-liner that didn't tolerate missing paths or permission errors); the canonical version now lives in `fileinfo.py` and the other two import it. The `[exe info]` PCLauncher INI body was inlined in both `favorites.py` and `cli.py`; both now call a new `pclauncher_exe_info_text()` in `rocketlauncher.py`. The GUI's `_mm_save_order` worker thread re-imported `os` / `shutil` / `datetime` despite all three being available at module scope; `datetime` is now a top-level GUI import and the four inline `from datetime import datetime` statements scattered through `gui.py` are gone. No behaviour change.
- **`spindoctor.playtime.main_cli` alias removed.** The `spindoctor-stats` entry point now points directly at `spindoctor.playtime:main` (the alias was a vestige of a since-removed setup.py wrapper).
- **GUI: Tabs reordered for a workflow-oriented sequence.** The old order put `Wheels` and `Main Menu` (front-end composition) before `Audit & Doctor` (read-only diagnostics) — backwards for a new cabinet owner whose first instinct after Setup is to confirm the cabinet is healthy before touching anything. The two read-only-check tabs (`Audit & Doctor` and `Diagnose`) now sit adjacent right after Setup. New order: Setup → Audit & Doctor → Diagnose → Metadata & Media → Curate → Wheels → Main Menu → Systems → LEDBlinky → Lightgun → Backup & Restore → Tools → Migrate → Logs → Custom Command. Pinned in the Tk smoke test so a drive-by reorder can't regress it silently. No behaviour change beyond the visual sequence.
- **GUI hard-coded `Consolas` / `Menlo` font references replaced with `TkFixedFont`.** Three widgets (theme viewer, helper-script panel, scheduler help text) were pinned to a literal family and therefore bypassed the View → UI scale knob. They now use the named font alias that resolves to the platform monospace default *and* honours the scale setting.
- **GUI run-history switched from `list` + `pop(0)` to `collections.deque(maxlen=200)`.** Append-and-evict is now O(1) at both call sites, and the explicit `if len(...) > 200: pop(0)` blocks went away.
- **Added `spindoctor.fileinfo.reset_ffprobe_cache()`.** The module-level `_ffprobe_ok` flag is set once per process; tests that patch `subprocess.run` to simulate a missing/present `ffprobe` would otherwise poison every later test in the same process. The reset is also useful from the GUI after a user installs ffmpeg without restarting.

### Fixed

- **Windows 7 / older Tk: `iconbitmap(default=…)` switched to positional path.** Some Tk 8.5 builds bundled with Python 3.8 on Win7 silently ignore the `default=` keyword, so the app icon never set. Now uses `iconbitmap(str(ico))` directly — already wrapped in `try/except TclError`, so behaviour is unchanged on newer Tk that does accept the keyword.
- **Windows 7 / older Tk: `TNotebook` tabmargins switched from tuple to string.** Some Tk 8.5 builds reject the tuple form (`(2, 4, 2, 0)`) with a `bad screen distance` error and fall back to the default margins; the space-joined string form (`"2 4 2 0"`) is accepted everywhere.
- **Update check now enforces TLS 1.2+.** `update_check._fetch_latest_release` builds an explicit `ssl.create_default_context()` with `minimum_version = TLSv1_2` and passes it to `urlopen`. GitHub requires TLS 1.2 since 2018; without the explicit floor, frozen Win7 builds with older bundled OpenSSL could negotiate TLS 1.0 and get a cryptic "EOF occurred in violation of protocol" instead of a clean handshake.
- **GUI: `media-add` Custom Command preset corrected.** Old preset advertised `--source` but the CLI flag is `--file`; fixed. Pinned in tests so the same drift can't ship again.
- **GUI: Theme-apply button now guards against double-click.** Clicking Apply spins the event loop to show the confirmation dialog; a fast second click before the worker thread started launched two concurrent disk-copy workers, corrupting the manifest. The button now disables on entry and re-enables in the worker's `finally` clause regardless of success or failure.
- **GUI: Window-close now terminates the running subprocess.** `_on_close` cancelled the pending drain (added in 1.7.x) but left the child `spindoctor.exe` running headless on Windows until it finished on its own. Now calls `_proc.terminate()` if a process is still alive so the orphan goes away with the parent.
- **GUI: Full metadata refresh now honours `--source`, `--threshold`, and `--no-cache`.** `_run_full_metadata_refresh` hand-rolled its own `fetch-meta` argv and silently dropped those three flags — users who configured them in the Metadata tab and clicked "Full refresh" got a default-config run with no warning. It now reuses `_build_fetch_meta_args` (the same builder the single-system Run button uses) so the two paths cannot drift again. Threshold validation (0.0–1.0) now applies to the chained run too.
- **GUI: Backup tab's Restore button moved to its own row below a Separator.** Sharing a row with read-only buttons (Show backup info, Compare to live) made it easy to fat-finger a destructive restore. The destructive action is now visually quarantined.
- **GUI: `_mm_save_order` runs on a worker thread.** Saving a reordered Main Menu used to parse, mutate, and rewrite the XML on the Tk main thread; on a HDD-backed cabinet this froze the UI for several seconds. The worker handles parse + backup + atomic rename and marshals success/failure back to the main thread via `root.after(0, …)`.
- **GUI: Main Menu tab no longer blocks first paint.** `_mm_refresh` (XML parse + tree population) was called inline from the tab builder. It now runs via `after_idle`, so the window appears immediately and the table populates a moment later.
- **GUI: `Esc` dismisses every Toplevel dialog.** About, Logs viewer, Diff viewer, Curate preview, Theme browser, Ignore viewer, "revert one system" picker — all now bind `<Escape>` to `destroy`, previously only the OS window-manager close box would dismiss them.
- **GUI: `Return` in the Verify-DAT entry triggers Verify.** Matches the existing behaviour of the Global Search entry; the Verify-DAT entry previously required a mouse click on the Verify button after typing the path.
- **GUI: Backup Restore dropdown filters to `spindoctor-backup-*` folders only.** Pointing the backup target at a drive root (e.g. `E:\`) used to spam the dropdown with every unrelated subdirectory; now only SpinDoctor backups show up.
- **GUI: `tk.Spinbox` widgets switched to `ttk.Spinbox`.** The classic-Tk variants bypassed the dark-mode `ttk.Style` overrides, so their arrows rendered with the system's light chrome on macOS/Linux.
- **GUI: indeterminate Progressbar starts/stops with `_run_cli` / `_on_proc_done`.** Wires the new widget into the existing lifecycle.
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

### Tooling

- **Tests: 3 new GUI cases** covering `match list` / bare `organize` read-only classification and `media-add` preset flag-name accuracy. Suite: 590 → 593.
- **Tests: regression coverage for the TLS 1.2 and `config set` bounds Fixed entries above.** `test_update_check.test_fetch_latest_release_enforces_tls_1_2` mocks `urlopen` and asserts the SSL context's `minimum_version` is `TLSv1_2`. `test_config.test_config_set_rejects_out_of_range_value` (6 parametrized cases) covers `match_threshold`, `max_concurrent_downloads`, and `metadata_cache_ttl_days`; a paired `test_config_set_accepts_in_range_value` pins the happy path. Suite: 600 → 608.
- **Docs: stale references in `docs/index.md` and `docs/windows-binaries.md` corrected.** Read-only command list in `index.md` was missing `mainmenu show`, `find-misplaced`, `find-global`, and `theme-scan` (drift vs. `commands.md`). Wheels-tab screenshot alt-text said "four refresh buttons" but the tab has been "three checkboxes + Refresh selected" since 1.7.0. Added a "Find a control on the GUI launcher" row to the where-to-start table so pip-installed users find the tab tour without hunting through the Windows binaries page.
- **Packaging: `pyproject.toml` description + classifiers reflect GUI parity with CLI.** Description was "Command-line librarian" — now "Tkinter GUI + CLI librarian". Added `Environment :: Win32 (MS Windows)` and `Environment :: X11 Applications` classifiers alongside `Environment :: Console` so PyPI / pip search surface the project for both audiences.
- **Scripts: `Refresh Both.bat` fails loudly on any step's error.** Previously only paused if the *last* step (Most Played) exited non-zero — a Favorites or Recently Played failure silently passed through to the next step, then the window closed before the user saw anything. Each step now pauses with a step-named message on failure and exits non-zero.
- **Tests: 29 new GUI cases covering `_is_read_only_invocation`** across read-only verbs, multi-token forms (`mainmenu show`, `fav list`, `curate --list-manifests`), and dry-run-able verbs that must *not* be flagged read-only.
- **New tests: 88 cases across `tests/test_config.py`, `tests/test_health.py`, `tests/test_fileinfo.py`, `tests/test_compat.py`.** The `health` (`doctor`) and `fileinfo` (`inspect`, `preview`, `audit` columns) modules previously had zero coverage; now every individual check plus the full orchestration path is exercised, including the destructive `check_match_cache --fix` branch. Total suite: 473 → 561 tests, still under 2 s.
- **`tests/test_themes.py::test_list_manifests_sorts_newest_first` no longer sleeps 1.1 s.** The test was using filesystem mtime second-resolution as a synchronization primitive; replaced with an injected `datetime.now()` shim and explicit `os.utime` calls. Shaves >1 s off every CI run.
- **Tests: atomic-write fault injection, RateLimiter, and CLI dry-run gates.** `test_download_resume.py` gains two cases that mock `os.replace` to raise `OSError` and assert the destination file is intact + the failure surfaces as a clean `DownloadResult` (uncovered a latent bug — `_download_to` only caught `requests.RequestException`, so a disk-full mid-rename would crash with a stack trace; now caught and returned as a non-success result). New `tests/test_rate_limiter.py` (6 cases) pins the throttling contract for the scraper. New `tests/test_dry_run_gates.py` (6 cases) covers the CLI `--apply` gate for `rename`, `clone`, `batch-edit`, `organize --restructure`, `media-scan`, `find-misplaced` — the existing tests exercised the `apply_*` library functions directly, bypassing the CLI guard entirely.
- **Ruff + pre-commit.** New `[tool.ruff]` + `[tool.ruff.lint]` sections in `pyproject.toml` (rules `F` + `W` for now — real-bug rules only; not enabling `E501` line-length until a separate reformat pass). New `.pre-commit-config.yaml` wires `pre-commit-hooks` (trailing whitespace, EOF newline, merge-conflict markers, large files, mixed line endings) + `ruff --fix` + a local hook (`scripts/check_changelog_unreleased.py`) that blocks commits introducing a second `## [Unreleased]` section — the failure mode that caused PR conflict churn during the 2.0 cycle and that silently dropped entries from `extract_changelog.py`.
- **Latent bug fixes surfaced by ruff.** Two `lambda: …` callbacks captured `exc` from an enclosing `except Exception as exc:` block (`gui.py:3219`, `gui.py:6674`); per PEP 3134 the name is deleted when the except block exits, so the deferred `root.after(0, ...)` lambdas raised `NameError` instead of showing the intended error message. Now bound at lambda-creation time via `_exc=exc` default arg. Also removed three genuinely dead local variables (`database.py:271`, `favorites.py:174`, `playtime.py:397`, `tests/test_mainmenu.py:108`).

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

[Unreleased]: https://github.com/phillram/spindoctor/compare/v2.4.1...HEAD
[2.4.1]: https://github.com/phillram/spindoctor/compare/v2.4.0...v2.4.1
[2.4.0]: https://github.com/phillram/spindoctor/compare/v2.3.4...v2.4.0
[2.3.4]: https://github.com/phillram/spindoctor/compare/v2.3.3...v2.3.4
[2.3.3]: https://github.com/phillram/spindoctor/compare/v2.3.2...v2.3.3
[2.3.2]: https://github.com/phillram/spindoctor/compare/v2.3.1...v2.3.2
[2.3.1]: https://github.com/phillram/spindoctor/compare/v2.3.0...v2.3.1
[2.3.0]: https://github.com/phillram/spindoctor/compare/v2.2.3...v2.3.0
[2.2.3]: https://github.com/phillram/spindoctor/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/phillram/spindoctor/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/phillram/spindoctor/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/phillram/spindoctor/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/phillram/spindoctor/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/phillram/spindoctor/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/phillram/spindoctor/compare/v1.9.1...v2.0.0
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
