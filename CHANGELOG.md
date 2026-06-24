# Changelog

All notable changes to SpinDoctor are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **Windows reserved device names (NUL, CON, PRN, COM1, LPT1, etc.) used as game or system names would silently write to system devices instead of files.** On Windows, filenames like `NUL.png` or `CON.mp4` map to built-in device handles regardless of path or extension — writes succeed with no error but no file is created. `_win_safe_stem()` in both `media.py` and `rocketlauncher.py` now appends `_` when the sanitised stem matches a reserved name (e.g. the hypothetical game "NUL" → `NUL_.png`).

- **Steam video downloads only got the short highlight clip (~11 s), not the full trailer.** Steam's `appdetails` API provides two separate video assets per movie entry: `mp4.max` (a short autoplay highlight used on Steam store browse pages, typically 10–15 s) and `hls_h264` (the full-length HLS trailer). `_parse_steam` was using `if mp4 … else hls` — when `mp4.max` was present it was added as the only candidate and the `else` branch (HLS) never ran, so the full trailer was never offered. Both are now added independently. The GUI and interactive CLI picker label them `(MP4 — may be highlight clip)` and `(HLS — full length, needs ffmpeg)` so the distinction is visible before clicking Apply.

- **Game names with colons (e.g. "Submachine: Legacy") produced 0-byte files and WinError 87 on Windows.** Windows NTFS treats a colon in a filename as an Alternate Data Stream separator — `Submachine: Legacy.png` is parsed as the file `Submachine` (main stream, 0 bytes) with an ADS named ` Legacy.png`. `os.replace()` then fails with WinError 87 because you cannot atomically rename an ADS to a regular file. `MediaDownloader.media_path()` and `system_media_path()` now apply `_win_safe_stem()` (the same stripping function already used for PCLauncher INI filenames) to the game/system name before building the path, matching what HyperSpin itself does when resolving media filenames.

- **Steam media images saved as `.jpg` instead of `.png`, breaking HyperSpin load.** `MediaDownloader._download_to` was replacing the canonical `.png` destination suffix with the URL's extension. Steam's header capsule (wheel) and screenshots are served as JPEG, so the files landed in `Images/Wheel/` as `GameName.jpg` — a filename HyperSpin never finds, since it only looks for `.png`. The extension-override is now skipped when the destination is already `.png`. After download, `_convert_to_png_inplace` converts the JPEG bytes to real PNG when Pillow (`pip install spindoctor[preview]`) is available; without Pillow the file keeps JPEG content but the `.png` name, which Windows GDI+ still loads via magic-byte detection.

### Added

- **HLS video duration shown in picker and CLI listing.** After a Steam scan, `SteamClient` fetches the HLS M3U8 playlist for each video candidate and sums `#EXTINF` segment durations. The result is stored in `MediaCandidate.duration_secs` and shown as `M:SS` in the GUI dropdown (e.g. `Master Key Trailer  1:14  (HLS — full length, needs ffmpeg)`), in the `fetch-steam-media` dry-run listing, and in the interactive media picker table. MP4 candidates carry no duration (can't cheaply probe an MP4 without downloading it); the `(MP4 — may be highlight clip)` label is the signal to try HLS if the clip is too short.

- **Steam media dropdowns now include a "— do not download —" option.** After a Steam scan, each picker (Video / Screenshot / Artwork / Wheel) gains a sentinel entry as its first value. The default selection remains the first real candidate (no behaviour change for users who want everything), but changing any picker to "— do not download —" tells Apply to skip that type entirely. Useful for games where you only want the video, or already have a better wheel image from ScreenScraper.

## [2.7.8] - 2026-06-24

### Fixed

- **`fetch-steam-media` crash on every run (`TypeError: output_dir`).** The `fetch_steam_media` command was constructing `MediaDownloader(config, output_dir=output_dir)`, but `MediaDownloader.__init__` only accepts `output_dir_override`. This caused an unconditional `TypeError` before any Steam data was fetched, making the command completely non-functional.

- **Steam video dropdown always empty for newer games.** Steam's `appdetails` API no longer returns `mp4.max` for newer titles — it serves only HLS (`.m3u8`) and DASH (`.mpd`) streaming manifests. The parser was skipping every movie entry that lacked `mp4.max`, leaving the video candidate list empty and showing `— none —` in the GUI picker and the interactive CLI picker. SpinDoctor now falls back to `hls_h264` for any movie that has no direct MP4 URL, and the downloader uses `ffmpeg -i <m3u8_url> -c copy` to pull the HLS stream down as a local MP4. `ffmpeg.exe` must be available (bundled next to `spindoctor.exe` or in `PATH`); without it a clear error message is shown instead of a silent failure.

- **`preview_candidate` silently failed for HLS candidates.** The method derived `tmp_path` with a `.m3u8` extension, then passed it to `download_to_path` which routed the URL to `_download_hls` — which saves the output as `.mp4`. The file was created at `tmp_path.with_suffix(".mp4")` but `_open_in_default_app` was called on the original `.m3u8` path that never existed. Fixed by normalising the temp file extension to `.mp4` before the download when the URL is an HLS stream.

### Added

- **Steam media panel — per-type View buttons.** Each candidate picker (Video / Screenshot / Artwork / Wheel) now has a **View** button that opens a preview in the default browser. Images (snap, artwork, wheel) open the direct CDN URL so the browser renders the image inline. Videos open the Steam store page so the user can watch the trailer in the Steam web player (HLS `.m3u8` manifests don't play directly in browsers, and direct MP4 would trigger a download rather than a preview). Buttons are disabled until a Scan has been run and candidates are available.

- **HLS video candidates labelled in the GUI picker.** Steam videos served via HLS now show `(HLS — needs ffmpeg)` in the dropdown label so it's clear before clicking Apply that ffmpeg must be available on the cabinet.

## [2.7.7] - 2026-06-23

### Fixed

- **Steam scan stall.** `_scan_steam._worker` called `self.tk.after(0, ...)` to schedule its main-thread callback. `self.tk` is the Tkinter *module*, which has no `after()` method — only Tk widget instances do. This raised `AttributeError` inside the thread, which was silently swallowed (only `MetadataError` was caught), leaving the status bar permanently stuck on "Scanning…" with no error shown even with verbose logging. Fixed by changing both calls to `self.root.after(...)` and adding a broad `except Exception` handler so any future unexpected thread errors surface as an error dialog.

- **Steam media panel not cleared on game/system change.** The `_meta_game_var` trace cleared the ScreenScraper/TGDB/Steam ID fields when a new game was selected but left the Steam URL box and all three candidate pickers showing stale results from the previous game. A new `_clear_steam_media_panel()` helper resets the URL field, empties `_steam_cands`, and resets all pickers to "— scan first —" / disabled; it is now wired into the existing trace.

- **`fetch-steam-media` output distinguishes overwrites from fresh downloads.** When `--overwrite` replaces an existing file the output now prints `overwrote: <path>` (yellow) instead of `downloaded: <path>` (green), making it clear a file was replaced rather than freshly added. Skips when `--overwrite` is absent are unchanged.

### Added

- **Wheel image slot for `fetch-steam-media`.** Steam's header capsule image is now also placed in the `wheel` media slot. `--wheel-index N` (1-based) selects a specific candidate non-interactively; without it the interactive picker includes a **Wheel** row. The GUI's Steam media panel gains a second picker row below the existing Video / Screenshot / Artwork row. The `--types` default remains `video,snap,artwork` so existing scripts that omit `--types` are unaffected.

## [2.7.6] - 2026-06-24

### Fixed

- **`pc-fix-exe --apply` now creates the game section when it is missing from the system INI.** Previously, if the PCLauncher INI existed but had no `[Game Name]` section for the target game, `rewrite_pclauncher_application` silently skipped the file and returned `False`, causing the CLI to print "no change needed — Application= is already correct" even though nothing had been written. The section is now appended to the existing INI, preserving all other game entries.

- **GUI "Fix PC game executable" executables list now has a vertical scrollbar.** The Listbox showing candidate `.exe` files had no scrollbar, making games with many executables inaccessible. The list is now wrapped in a frame with a linked `ttk.Scrollbar` so all entries are reachable.

- **GUI "Fix game executable" Apply button now respects the global Apply toggle.** The `_run_fixexe` method was hardcoding `--apply` unconditionally, meaning clicking the button always wrote the INI change even when the global Apply checkbox was unchecked. It now follows the same pattern as every other write operation in the GUI — `--apply` is only passed when the global toggle is on; without it the CLI runs in preview/dry-run mode and prints what it would change.

- **GUI output panel no longer flooded with `────` box-drawing lines.** The subprocess environment previously forced `COLUMNS=9999`, which told Rich to render `Panel()` borders spanning 9,999 characters. Now that every Rich `Console` instance uses `soft_wrap=True` (added in v2.7.5), the `COLUMNS` override is redundant for its original purpose (preventing path wrapping) and has been removed. Rich now uses its pipe default (~80 columns) for panel borders, giving a compact header line instead of thousands of horizontal dashes.

- **Save Log no longer fails with "Invalid argument" when the command slug contains Windows path characters.** For commands that accept a `--exe` path (e.g. `pc-fix-exe`), the exe path value was treated as a positional argument and joined into the auto-saved log filename — producing characters such as `\` and `:` that are illegal in Windows filenames. The filename builder now strips all Windows-invalid characters (`\ / : * ? " < > |`) from the slug and caps it at 80 characters before constructing the path.

### Added

- **"(Not in wheel)" badge in system and game dropdowns.** System pickers across every GUI tab now annotate any system that exists as a folder in `roms_dir` or `databases_dir` but is absent from `Main Menu.xml` with a `(Not in wheel)` suffix. The **Fix PC game executable** game picker also badges any game folder on disk that has no matching entry in the system's HyperSpin XML database — the only game dropdown that reads from the filesystem rather than the XML, so the only one where the discrepancy can arise. The suffix is stripped before any CLI command runs — file paths and command arguments are never affected.

- **`fetch-steam-media` command** — download trailer videos, in-game screenshots, and/or header artwork for a specific game directly from the Steam Store (no API key or account required). Accepts a bare App ID or a full `store.steampowered.com/app/<ID>/` URL. Runs an interactive numbered picker by default (identical to `fetch-media --pick-media`); `--video-index N`, `--snap-index N`, and `--artwork-index N` flags enable non-interactive/scripted use. If `--steam-id` is omitted, the stored `steam_app_id` game override is used automatically. GUI: **Metadata & Media → Per-game & override → Steam media** panel (Scan + candidate dropdowns + Apply).

- **`config game-override set --steam-app-id`** — new per-game override key that stores a Steam App ID alongside the existing `screenscraper_id` / `thegamesdb_id` fields. Used by `fetch-steam-media` as the default App ID when `--steam-id` is not passed.

- **URL support for all `config game-override set` ID options** — `--screenscraper-id`, `--thegamesdb-id`, and `--steam-app-id` now accept full browser URLs in addition to bare numeric IDs. The ID is extracted automatically (`gameid=` param for ScreenScraper, `/game/<id>/` or `?id=` for TheGamesDB, `/app/<id>/` for Steam) so users can paste directly from the browser without manually extracting the number. GUI integer validation for scraper ID fields removed accordingly — the CLI handles extraction and validation.

- **Steam media panel in the GUI** (Metadata & Media → Per-game & override): paste a Steam URL or App ID, click **Scan** to fetch available candidates in the background, pick from **Video** / **Screenshot** / **Artwork** dropdowns, then click **Apply selected**. The stored Steam App ID (via **Save override**) is pre-filled on load so repeat scans require no re-pasting. **Overwrite existing** checkbox controls file replacement.

- **`SteamClient`** in `scraper.py` with `fetch_by_app_id(app_id)` and `search(game_name)`. Populates `video`, `snap` (full-resolution screenshot), and `artwork` (header capsule) media candidates. No wheel support (Steam has no transparent-logo equivalent).

- **`extract_screenscraper_id()`, `extract_thegamesdb_id()`, `extract_steam_app_id()`** helper functions in `scraper.py` — shared by the CLI and GUI for URL-to-ID extraction.

## [2.7.5] - 2026-06-22

### Fixed

- **XML comments in `Main Menu.xml` no longer float to the top of the file after a save.** When SpinDoctor processed a `Main Menu.xml` that contained interleaved XML comments (e.g. `<!-- ARCADE CABINETS -->`), the comments were left behind as orphaned nodes after the `<game>` elements were removed and re-appended, causing them to cluster at the top of the output with box-drawing characters encoded as XML entities. SpinDoctor now strips all comment nodes from the root when rewriting the file — HyperSpin-native Main Menu files never contain comments, and stripping them is cleaner than attempting to preserve their positions through reorder/hide operations.

- **File paths no longer wrap mid-line in saved output logs.** All Rich console instances now use `soft_wrap=True`, which prevents Rich from breaking long lines (file paths, URLs) at the detected console width. This is belt-and-suspenders on top of the existing `COLUMNS=9999` subprocess environment fix — if the cabinet's Windows 7 / PyInstaller environment ignores `COLUMNS`, `soft_wrap` guarantees paths stay on a single line regardless.

### Added

- **Trailing actionable summaries for `generate-config` and `update-db`.** These commands process every system in the cabinet in a single run; any error or per-system result was previously buried inside a long table or scrolled-off list.
  - `generate-config --apply`: if any system INI fails to write (e.g. `rocketlauncher_dir` not configured, bad path), the failing system names and error messages are repeated as an "Actionable items" section at the very end of output — visible without scrolling back through a 40-system table.
  - `update-db`: after processing all systems, a one-line grand total is printed (`+N added  −M removed  K already in sync`) so the result of a full-library run is legible at a glance from the bottom of the terminal.

- **`repath-system` — re-prefix game paths in a PCLauncher system INI after moving games to a new drive.** Designed for systems like Taito Type X whose games live in a system-level INI (`Modules\PCLauncher\<System>.ini`) and were moved to a different drive outside of a full SpinDoctor `migrate` run. In one command, rewrites `Application=` for every game whose path contains the system name as a directory component, and updates `Rom_Path=` in the matching `Emulators.ini`. All other per-game keys (`FadeTitle=`, `AppWaitExe=`, `ExitMethod=`, `PostExit=`, etc.) are left untouched. Dry-run by default; `--apply` commits. GUI: Migration tab → Step 6. CLI: `spindoctor repath-system "Taito Type X" --rom-path "J:\Games\Taito Type X" --apply`.

- **`pc-fix-exe` now handles system-level PCLauncher INIs (Taito Type X, NESiCAxLive, etc.).** Previously the command only looked for per-game INIs under `Modules\PCLauncher\<System>\<game>.ini`. It now detects whether a system-level INI (`Modules\PCLauncher\<System>.ini`) exists and uses it automatically — the correct format for arcade-PC systems configured outside of SpinDoctor. The `--exe` flag works the same way; use it to point at `.ahk` launchers or any non-`.exe` application type.

- **GUI — Migration tab gains Step 6 "Re-prefix game paths after a drive change".** System picker, new game folder path entry with Browse, and separate Preview / Apply buttons driving the new `repath-system` command.

- **GUI — "Fix game executable" panel is now system-agnostic.** The panel (previously labelled "Fix PC game executable" and documented as PC-only) now accepts any PCLauncher-backed system in the system picker. Selecting Taito Type X, NESiCAxLive, or any other system-level INI system and clicking Apply writes the correct INI automatically.

- **Fix game executable — candidate list now includes `.ahk` and `.bat` launchers.** `list_exe_candidates` previously only returned `.exe` files, making Taito Type X's `CleanLaunch.ahk` invisible in the GUI listbox and `--list-candidates` output. Non-excluded `.exe` files are still ranked first (so auto-detect still favours `.exe`); `.ahk` files follow, then `.bat`, then excluded `.exe` files. The Browse dialog in the GUI now lists AHK scripts and batch files as named filetypes alongside executables. `pc-fix-exe` also prints a warning when auto-detect picks a `.exe` but the existing `Application=` is already a `.ahk` or `.bat` script — the warning is duplicated at the very end of output so it's never buried.

- **`repath-system` and `pc-fix-exe` now duplicate actionable warnings at the end of output.** For `repath-system`, games whose `Application=` path did not contain the system name as a directory component (and therefore could not be re-pathed automatically) are listed as actionable items at the very bottom with a suggested `pc-fix-exe` command. For `pc-fix-exe`, the auto-detect/`.ahk` mismatch warning is repeated at the bottom. This prevents important messages from being scrolled off when a system has many games. `repath-system` also backs up the PCLauncher system INI to a timestamped `.bak` file before writing, so a failed or interrupted write cannot destroy the original.

- **`--report PATH` flag added to all audit commands for consistent CSV output.** Every audit-type command now supports `--report PATH` to write a machine-readable CSV alongside the terminal output:
  - `tools-audit --report PATH` — one row per detected tool with category, tool name, replaced-by spindoctor command, notes, and install path(s).
  - `cleanup audit --report PATH` — one row per category with file count, total bytes, human-readable size, oldest/newest timestamps, and storage location.
  - `ledblinky audit --report PATH` — one row per ROM with `in_listxml`, `has_input`, `in_controls_ini`, `in_colors_ini`, and `status` (covered / would-synth / no-input / missing).
  - `fetch-media --report PATH` — post-fetch ROM+media audit CSV identical to `audit --report`, with additional before/after download-result columns per media slot.
  Commands that already had `--report` (`audit`, `media-scan`) are unchanged. `fetch-media`'s existing auto-export via `auto_audit_export_dir` is also unchanged and now supports writing to *both* the auto path and an explicit `--report` path in the same run.

- **`game` CLI command group — list, remove, and reorder individual games within a system's wheel database.**
  - `spindoctor game list --system <System> [--verbose]` — lists all games in XML order with position numbers; `--verbose` adds year, manufacturer, genre, and enabled state.
  - `spindoctor game remove --system <System> <game_name> [--apply] [--verbose]` — removes a single game entry from the database XML (ROM and media files are untouched). Dry-run by default; `--verbose` prints full metadata and the file path before removing.
  - `spindoctor game move --system <System> <game_name> <position> [--apply] [--verbose]` — moves a game to a specific 1-based wheel position.
  - `spindoctor game move-up --system <System> <game_name> [--apply] [--verbose]` — moves a game up one position.
  - `spindoctor game move-down --system <System> <game_name> [--apply] [--verbose]` — moves a game down one position.
  - `spindoctor game sort --system <System> [--by description|name] [--apply] [--verbose]` — sorts all games alphabetically, ignoring leading articles (The, A, An) to match HyperSpin's own wheel convention. Default sort key is display title (`description`); `--by name` sorts by ROM filename instead.
  All write commands are dry-run until `--apply` is passed; `--output-dir` writes the result alongside the live HyperSpin tree.

- **GUI: "Manage games in a system wheel" panel in the Systems tab.** Mirrors the Main Menu carousel UX — pick a system, click Load Games to populate the table, then Move Up / Move Down (or Alt+↑ / Alt+↓), Move to # (jump directly to a position number), Sort A→Z by display title or ROM name, or Remove Game. Save Order writes the new order; dry-run unless Apply is ticked. Remove Game shells out to `game remove --apply` for auditability; Save Order uses the shared database module the same way the Main Menu carousel uses `mainmenu.save_main_menu`.

- **Fix PC game executable — recursive subfolder scan.** `list_exe_candidates` (used by `pc-fix-exe` and the GUI picker) now uses `rglob` instead of `glob`, so executables nested inside subdirectories are included (e.g. `J:\Games\PC Games\Coolio\coolio.exe` **and** `J:\Games\PC Games\Coolio\data\coolio.exe`). Sort order still prefers top-level, non-setup-like executables that best match the game title; deeper paths sort after same-depth candidates. The GUI label updated to "Executables in game folder and subfolders".

- **Fix PC game executable — Browse… button.** A **Browse…** button now sits alongside the Executable path field in the Fix PC game executable panel. Clicking it opens the native OS file browser (Windows Explorer file picker on the cabinet) pre-navigated to the current game folder. The selected path is normalised to native path separators and written into the Executable path field, so the user can target any `.exe` anywhere on the system.

- **American Laser Games (ALG) documented in cabinet architecture reference.** Covers the hardcoded absolute D: path problem in the original `.singe` scripts, how `SingePathUpdate=true` + `ForcePathUpdate=true` in `Daphne Singe.ini` rewrites those paths to J: (then calls `exitapp` — Daphne does not launch on the rewrite run, and no `daphne_log` is produced, which is correct), and the dual-copy requirement: after rewriting, `.singe` files must be copied from J: to `D:\Arcade\Emulators\American Laser Games\data\singe\[gamename]\` because `dofile()` relative paths in scripts resolve against Daphne's D: CWD. Assets (sprites, sounds, fonts, `.cfg` files) only need to be on J:. The `.cfg` file (game settings + high scores) must exist at the J: path before first launch — if missing, `io.input()` crashes the game on the first overlay frame even after video starts. `SingePathUpdate` is per-game and must be run for each ALG title individually. Includes one-time setup procedure and comparison table with WoW Action Max.

- **Daphne Singe (WoW Action Max) documented in cabinet architecture reference.** Covers the custom Daphne Singe 1.0.10 build layout, five failure modes in launch order with distinct symptoms and fixes, and the unusual dual-copy requirement: engine assets (Emulator.singe, sprites, sounds, fonts) must be present in **both** `D:\Arcade\Emulators\WoW Action Max\data\singe\ActionMax\` (as `singe/ActionMax/<file>` paths relative to daphne.exe's CWD) and flat in `J:\Games\WoW Action Max\` — removing them from either location breaks the games. Per-game `.singe` scripts and video files live on J: only. `SingePathUpdate` in `Daphne Singe.ini` is not useful for WoW Action Max and should be left off.

- **Phoenix (Atari Jaguar) emulator documented in cabinet architecture reference.** Covers the `phoenix.config.xml` launch mechanism (RL rewrites `attach` + `<Dump>` paths before each launch), the root cause of the *"You must select CARTRIDGE"* error (Phoenix only auto-selects a game if `attach` matches a `<Dump>` entry path exactly — J: paths failed because the library was built from D:), and the fix (RL module rewrites `D:/Arcade/Games/Atari Jaguar/` → `J:/Games/Atari Jaguar/` in all Dump entries on each launch). Reference copy of the customised `Phoenix.ahk` RL module added to `spindoctor/assets/archive/`.

- **Daphne LaserDisc file layout documented in cabinet architecture reference.** Covers the three-file-type split (`.txt` framefile in `J:\Games\Daphne\`, chip ROMs in `J:\Games\Daphne\roms\`, VLDP video in `J:\Games\Daphne\vldp\<game>\`), framefile format (first line = relative VLDP path), `homedir` configuration in `Daphne.ini` (must be set to `J:\Games\Daphne` for each game section so daphne.exe finds chip ROMs on J: rather than its own install folder), common path mistakes, and PowerShell bulk-repair commands. ROM storage layout in the directory tree updated to show the Daphne folder structure.

- **`config system set --rom-path PATH`** — new flag that permanently pins the ROM folder path for a system in `config.json`. `generate-config` now uses this value as `Rom_Path=` instead of deriving `roms_dir\<SystemName>`. Fixes "Can't find Rom in any rom_paths provided" for systems whose ROM folder name doesn't match the HyperSpin system name (e.g. "Panasonic 3DO" with ROMs in `J:\Games\3DO`, or any Daphne-based system). The override survives drive migrations and RL config restores. CLI: `spindoctor config system set "<System>" --emulator <Name> --rom-path <Path>`.

- **GUI: ROM folder path field in Per-system overrides form.** The system override panel in the Systems tab now includes a "ROM folder path" entry. **Load current values** populates it from the saved override; **Save override** passes `--rom-path` to the CLI. Pairs with the existing Emulator field to configure non-standard systems without touching source code.

- **Expanded EMULATOR_MAP** — `generate-config` now correctly assigns `Default_Emulator=` for many more systems when creating new per-system INI files: Daphne-based systems (Daphne, Action Max, American Laser Games, Wow Action Max → `Daphne`), 3DO (→ `RetroArch`), Taito Type X / X2 / X3 and NESiCAxLive (→ `PCLauncher`), Doujin / Doujin Games (→ `PCLauncher`), Sega Naomi / Atomiswave / TriForce (→ `MAME`), ZiNc (→ `ZiNc`), Sega Saturn (→ `SSF`), NDS / 3DS, PSP, and many more. Existing INIs are unaffected — `Default_Emulator=` is never overwritten for files that already exist.

- **Expanded ROM extension coverage** — the default extension list (used for systems not in SpinDoctor's built-in map) now includes `.iso`, `.bin`, `.chd`, `.cue`, `.img`, and `.rom` in addition to `.zip`, `.7z`, `.rar`. Added targeted entries for 3DO, Daphne, Entex Adventure Vision, CD-i, PC Engine CD, Neo Geo CD, Atari Jaguar / ST, Amiga, Commodore 64, WonderSwan, Vectrex, Colecovision, Intellivision, Fairchild Channel F, Naomi/Atomiswave, Nintendo DS/3DS/GameCube/Wii U, PSP, and more. Per-system `--rom-extensions` overrides are unaffected.

- **Generic emulator-family shared-folder fallback in `generate-config`** — for emulator families where multiple HyperSpin wheels share one ROM folder (like Daphne-based systems), `generate-config` now detects that the system-named folder doesn't exist and falls back to the canonical family folder (`roms_dir/Daphne`) instead of writing a phantom path. Mirrors the existing MAME shared-folder logic. For example, "American Laser Games" (emulator `Daphne Singe`) will resolve to `J:\Games\Daphne` rather than the non-existent `J:\Games\American Laser Games`. When an existing per-system INI already points at a valid directory, that path is preserved unchanged.

### Changed

- **GUI: all action buttons now use plain-English labels instead of CLI command names.** Twenty-four buttons across six tabs were renamed so users never need to know a CLI sub-command to understand what a button does. Full mapping: "Run doctor" → "Run Health Check"; "Tools audit" → "Check Installed Tools"; "Run migration" → "Start Migration"; "Run generate-config" → "Update RocketLauncher INIs" (both Metadata & Media and Migration tabs); "Run fetch-meta" → "Download Game Info"; "Run on subset…" → "Download for Selected Systems…"; "Run fetch-media" → "Download Media Files"; "Run media-scan" → "Import Local Media"; "Run update-db" → "Sync Database to ROMs"; "Run batch-edit" → "Run Bulk Edit"; "Run curate" → "Archive / Delete Duplicates"; "Audit caches" → "Check Cache Status"; "Run cleanup" → "Clean Up Caches"; "Run add-system" → "Add Arcade System"; "Run add-pc-system" → "Add PC System"; "Run rename" → "Rename Game"; "Run clone" → "Clone Game"; "Run organize" → "Build Sort Wheels". CLI commands and behaviour are unchanged.

### Fixed

- **GUI: Game wheel manager — removed game stays visible until save confirms success.** `Remove Game` previously popped the entry from the in-memory table before the `game remove --apply` CLI call returned. On a subprocess failure (e.g. file-permission error) the game had already disappeared from the table but still existed in the XML — state desync on error. The table update is now deferred to an `on_complete` callback that fires only when the exit code is 0; on failure the row stays put so the user can retry.

- **GUI: Game wheel manager — changing the system dropdown no longer silently overwrites the wrong database.** If a user loaded games for "Nintendo 64" then changed the dropdown to "MAME" before clicking Save Order, the MAME database would be overwritten with the Nintendo 64 game order. The panel now tracks which system is actually loaded (`_gwm_loaded_system`) independently of the combo's live value; changing the dropdown clears the table and count label so the mismatch is immediately obvious.

- **`_Hasher.close()` missing — `test_sevenz_inner_hash` failed on Python 3.12.** py7zr ≥ 1.0 calls `close()` on each writer object after streaming inner files. The `_Hasher` file-like class had `write`/`read`/`seek`/`flush`/`size` but no `close()`, raising `AttributeError: '_Hasher' object has no attribute 'close'`. Added a no-op `close()`. py7zr 0.22 (the Windows 7 / Python 3.8 build) does not call `close()`, so the 3.8 CI job was unaffected.

- **Corrected stale Daphne+RL ROM layout callout in cabinet architecture reference.** The callout in the `generate-config` section incorrectly described `.txt` files as empty placeholders, cited a wrong chip ROM path (`D:\Arcade\Games\Daphne\roms\`), and described the Daphne.ahk module as stripping the extension rather than passing `-framefile`. Updated to match the verified file layout: framefiles are data files (not placeholders), chip ROMs live at `J:\Games\Daphne\roms\<game>.zip` via `homedir = J:\Games\Daphne` in `Daphne.ini`, and the module passes the full `-framefile` path to daphne.exe.

- **GUI: "Fix PC game executable" section now auto-loads games on startup.** The game dropdown was empty when the Systems tab first opened because setting the system var programmatically doesn't fire `<<ComboboxSelected>>`. SpinDoctor now populates the game list automatically after pre-selecting "PC Games". The ↻ refresh button next to the Game dropdown now refreshes the game list (as the rename section's ↻ does) instead of trying to load exe candidates for an empty selection; selecting a game from the list or clicking ↻ also immediately populates the executable candidates.

- **GUI: Override ID fields (ScreenScraper ID / TheGamesDB ID) now clear automatically when the game or system selection changes.** Previously, IDs entered for one game would linger in the form after navigating to a different game or switching systems, risking saving the wrong override. "Load current override" and manual typing are unaffected.

- **GUI: Saved log `.txt` files no longer contain mid-path line breaks.** The CLI subprocess inherited the parent shell's `COLUMNS` value, causing Rich and Click to hard-wrap long file paths and URLs at that width. The GUI now sets `COLUMNS=9999` before launching the subprocess so output lines are preserved intact. Rich tables are unaffected (they size to their content by default, not the console width).

---

## [2.7.4] - 2026-06-15

### Fixed

- **`recent rebuild` / `stats build-wheel` no longer risk losing media or PCLauncher INIs on a mid-run failure.** The orphan-cleanup step previously ran *before* new files were written. A crash or disk-full between the two steps left the wheel with less content than before. Both the media phase and the PCLauncher INI phase now write all new files first and remove orphans only after the writes complete — matching the fix applied to `fav rebuild` in the previous release.

- **Media downloader now fails immediately on non-retriable HTTP errors** (404 Not Found, 403 Forbidden, 500 Server Error, etc.) instead of retrying up to `max_retries` times with exponential backoff. Only transient errors (429 Too Many Requests, 503 Service Unavailable) and stale-partial resets (416 Range Not Satisfiable) trigger retries. A missing media URL previously wasted several seconds per game before giving up.

- **`spindoctor config game-override` no longer crashes with `NameError` when a forced scraper ID returns no result.** Both the ScreenScraper and TheGamesDB override paths called `_log.warning()`, but the module logger is `scraper_logger`. The NameError meant the expected "verify this ID" warning was never written to `scraper.log` — instead the run crashed silently. Both sites now call `scraper_logger.warning()`.

- **`spindoctor config credentials test` (TGDB) now reports the correct HTTP status code when authentication is rejected.** A 401 Unauthorized response produced the message "Invalid API key (HTTP 403)"; the status code is now included dynamically so 401 and 403 are distinguished.

- **Downloader no longer crashes with `ValueError` on a `Retry-After` header in HTTP-date format.** RFC 7231 allows `Retry-After` to be either a number of seconds or a date string (`Wed, 21 Oct 2015 07:28:00 GMT`). `float()` on a date string raises `ValueError`; the code now catches it and falls back to the current exponential backoff value.

- **Sort-database bucket files (`organize`) are now written atomically.** `write_sort_databases` previously used a direct `open()` write that left a half-written XML file on disk if the process was interrupted mid-write. It now uses the same temp-file + `os.replace()` atomic pattern as every other database write in SpinDoctor.

- **`fav rebuild` no longer silently deletes media and PCLauncher INIs before writing the new ones.** The previous ordering (delete orphans, then write new files) meant any failure between the two steps left the wheel with less content than before. Writes now happen first; orphan cleanup runs only after all new files are confirmed on disk.

- **`scrub --hs-favorites` now only strips `favorite="1"` from system XML files**, not any `favorite="..."` value. The previous regex was too broad and would have stripped e.g. `favorite="0"` or custom values written by third-party tools. The behavior now matches the documented spec.

- **`fetch-media` now respects `config.match_threshold`** (set via `config set match_threshold`). Previously `fetch-media` always used the hardcoded default of 0.80 regardless of configuration; `fetch-meta` was correctly reading from config. Both commands now use the same threshold.

- **TheGamesDB media fill-in now actually reaches the download queue.** `CombinedMetadataClient` fills TGDB media into `media_candidates` when ScreenScraper has an empty slot, but `fetch-media`'s download job builder reads the scalar `wheel_url` / `background_url` / `snap_url` fields — not `media_candidates`. Those scalars were never updated from the fill, so TGDB's gap-fill produced no downloads. The scalar fields are now synced alongside `media_candidates` when TGDB contributes.

- **TheGamesDB search results now include wheel, snap, and background images.** `TheGamesDBClient.search()` was missing the `_merge_images()` call that `fetch()` and `fetch_by_id()` both make to pull wheel/snap/background from the `Games/Images` endpoint. Search-path results (games below the name-match threshold that fell through to fuzzy search) had only boxart populated.

- **`_parse_screenscraper` no longer crashes with `AttributeError` when genre entries are plain strings.** The lighter ScreenScraper search payload can return `genres` as a list of strings rather than `{"id": ..., "noms": [...]}` dicts. Calling `.get()` on a string raised `AttributeError`, crashing the per-game loop. Genre is now safely skipped when the first entry is not a dict.

- **Zero-byte server response can no longer overwrite a valid existing media file.** The empty-body guard previously checked `dest.stat().st_size == 0` *after* `os.replace(part, dest)`, which atomically wiped the destination before the check. The guard now inspects the `.part` file *before* replacing, so a server that returns HTTP 200 with an empty body leaves the existing file untouched and retries.

- **Save Log filenames now include the CLI action name** (`2026-06-16_22-15-35_recent_rebuild.txt`) instead of the last flag (`date_--apply.txt` / `date_--verbose.txt`). The action slug is derived from the binary suffix and positional arguments: `spindoctor-recent rebuild` → `recent_rebuild`, `spindoctor fetch-media` → `fetch-media`, `spindoctor fav rebuild` → `fav_rebuild`.

- **`spindoctor-recent rebuild` / `spindoctor-stats build-wheel` no longer crash with `UnicodeDecodeError` when a RocketLauncher Statistics.ini file contains game names written in the Windows system codepage** (e.g. accented letters like `ü` at byte 0xfc which is invalid UTF-8). Both `recent.py` and `playtime.py` now retry with CP1252 on a decode error. The same fix is applied to the Global Statistics and HyperSpin media-link INI readers in `recent.py`, `playtime.py`, and `medialink.py`.

- **Per-game scraper ID overrides now take effect even when the metadata cache holds a pre-override result.** `fetch_with_search()` previously checked the cache before calling `fetch()` (where the override is applied), so setting an override after a prior run had already cached a "no media" result left the cache returning the stale answer on every subsequent run — the override appeared to do nothing. The cache is now bypassed (both read and write) whenever a per-game override is active for a game, so the forced ID is always tried fresh. Setting an override takes effect on the very next `fetch-meta` / `fetch-media` run without needing to clear the cache manually.

- **`fetch-media --verbose` now shows active override IDs alongside the resolved source** (`override: ss=XXXX, tgdb=XXXX`), making it easy to confirm the forced ID was used rather than a cached or name-matched result.

- **Warning logged to `scraper.log` when a forced override ID returns no result** (typo, deleted listing, quota issue). Previously `fetch_by_id()` returned `None` silently; the new `WARNING` line names the ID and points to the scraper site URL so the owner knows to verify it.

- **`save_config()` now writes `config.json` atomically.** A crash or disk-full error mid-write could leave `config.json` truncated and unreadable. The function now writes to a `.tmp` sidecar and renames it into place with `os.replace()`, matching the atomic-write contract used by every other file SpinDoctor writes.

- **RocketLauncher `Statistics.ini` files with a UTF-8 BOM no longer silently lose the first game.** The plain `"utf-8"` codec keeps the BOM as `﻿` in the first section header, so `[1942]` became `[﻿1942]` — a section the parser couldn't match, silently discarding that game's playtime with no error. The reader now uses `"utf-8-sig"`, which strips the BOM automatically (consistent with how `Global Statistics.ini` was already read). The change also aligns the per-system and global readers so both use the same first-attempt codec.

- **`install-tools --add-to-system` now requires `--apply` before mutating the HyperSpin database XML.** Previously the command wrote game entries into the target system's XML immediately, with no dry-run preview and no confirmation step. Without `--apply`, the command now prints a preview of what would be added and exits cleanly. The `.bat` helper files are still written unconditionally (they are non-HyperSpin files and safe to create); only the XML mutation is gated.

### Changed

- **GUI Metadata & Media tab: game selector and per-game override IDs are now in one combined "(Optional)" box above Step 1.** The "Game (blank = all games)" dropdown has moved out of the bare shared header and into a labelled "Per-game & override (Optional)" frame that sits between the System selector and Step 1, keeping targeting controls visually together. Override IDs remain in the same frame; Load/Save/Clear buttons are unchanged.

---

## [2.7.3] - 2026-06-15

### Added

- **New GUI "Save Log" checkbox in the status bar, next to Apply and Verbose.** When checked, every finished command's exact Output panel text (command line, full stdout/stderr, exit code) is written as a `.txt` backup file into your configured Default output directory. Unchecked by default; if `output_dir` isn't set, the Output panel notes the run wasn't saved instead of writing anywhere unexpected.

- **Letter-key type-ahead on every GUI dropdown.** Pressing a letter while a Combobox (System, Game, etc.) has focus jumps straight to the next entry starting with that letter — repeat presses of the same letter cycle through further matches instead of always landing on the first one. This restores the native combobox behaviour that the dark theme's custom styling otherwise loses, and matters most on the Metadata & Media tab's Game dropdown, where a console can list hundreds of titles.

- **Auto-exported audit CSVs now show before/after media status.** When `auto_audit_export_dir` is configured, `fetch-media`'s CSV gains a `{slot}_before` column alongside the existing `{slot}` (after-state) and `{slot}_result` (action taken) columns, so a row reads as a full before → action → after story instead of just the post-run snapshot.

- **Consolidated "missing media" / "unresolved metadata" summary at the end of `fetch-media` / `fetch-meta` console output, and a matching footer section at the bottom of the auto-exported audit CSV.** A long `--all` run used to require scrolling back through every system's per-game output (or scanning every row's `{slot}_result` column) to find what still needs attention; both now end with one consolidated list of just the games that came up short.

- **New `config game-override` command (and GUI panel) to force a specific ScreenScraper / TheGamesDB game ID for one title.** For games that just don't match well by name (language barrier, alternate punctuation, a remaster's subtitle), find the right game on the scraper's own site, copy its ID, and set it once with `spindoctor config game-override set <system> <game> --screenscraper-id <id> --thegamesdb-id <id>`. Every future `fetch-meta`/`fetch-media` run for that exact game uses the forced ID automatically, bypassing name matching entirely. Also exposed in the GUI's Metadata & Media tab ("Per-game overrides") and via `config game-override list / clear`.

### Fixed

- **Metadata & Media tab: selecting a new console no longer leaves the previous console's game selected.** The Game dropdown is now blanked automatically whenever the System dropdown changes, instead of silently carrying over a stale (and potentially same-named-but-unrelated) game selection from the prior console.

- **`fetch-meta` / `fetch-media --game NAME` no longer dumps the whole console into the auto-exported audit CSV.** The CSV is now scoped to just the targeted game, matching what the command itself actually touched, instead of always auditing every game on the system.

- **ScreenScraper matches found via text search could come back with zero media for every type, even when the game's own ScreenScraper page has plenty of art.** The search endpoint (`jeuRecherche.php`) returns a lighter record than the per-game detail endpoint and can omit the media gallery entirely. `fetch-media`/`fetch-meta` now re-fetch the matched game by ID to backfill its media when the initial search hit comes back empty — one extra API call, only when needed.

- **`--source both` silently skipped TheGamesDB for ROM names with region tags or romset punctuation** (e.g. `Golden Sun - Dark Dawn (USA)` vs. TheGamesDB's own `Golden Sun: Dark Dawn`). TheGamesDB's direct-lookup path sent the raw ROM name while its search path already normalized it first; both now normalize consistently, so the "both" combined source actually queries TheGamesDB with a name it can match.

- **Zero-byte media files are now treated as missing by `audit` and `fetch-media`.** A 0-byte file — left by a failed or empty server response — previously satisfied the presence check, so `audit` reported the slot as covered and `fetch-media` silently skipped it on every subsequent run, never re-downloading. The check now uses `stat().st_size > 0` so a zero-byte file is indistinguishable from a missing one: it appears in the audit's missing-media list and triggers a fresh download on the next `fetch-media` run.

- **`fetch-media` now reports failure (and retries) when the server returns an empty response.** A download that received an HTTP 200 with an empty body previously created a 0-byte file and returned `DownloadResult(success=True)` — the console showed "downloaded ✓" but the file was useless. The downloader now detects a 0-byte result after `os.replace`, removes the empty dest, and retries up to `max_retries` (respecting the existing exponential backoff) before returning a descriptive failure.

- **`media-scan` import and `preview` no longer treat zero-byte files as present.** `media-scan match-to-database` classified a 0-byte target slot as "replacement" (already filled), so `import_media` would skip incoming art for that slot unless `--overwrite` was passed. The `preview` command would resolve the zero-byte path and try to open it in the OS default app. Both now use `stat().st_size > 0` — consistent with `audit`'s presence check — so a zero-byte stub is treated as absent: `media-scan` classifies the slot as "matched" (free to fill), and `preview` falls through to the next extension or reports the slot as missing.

- **Removed duplicate variable declarations in `CombinedMetadataClient.search()`.** `ss_error` and `tgdb_error` were each declared `= None` twice in sequence — a merge artifact. Harmless in practice today, but shadowing the first assignment would become a latent bug if code were ever inserted between the two declarations.

---

## [2.7.2] - 2026-06-14

### Fixed

- **Downloaded videos now play with audio on macOS and Windows.** ScreenScraper's standardised (`video-normalized`) files encode audio as MP3 inside an MP4 container using an `mp4a` tag (`mp4a.40.34`). Both macOS AVFoundation (QuickTime, Finder preview) and Windows Media Foundation (used by HyperSpin on Windows 7) expect AAC behind any `mp4a` tag and silently drop an MP3 bitstream, so the file appeared to play but had no sound. SpinDoctor now detects this condition with `ffprobe` after every successful video/trailer download and, if the audio codec is not AAC, re-encodes it to proper AAC in-place with `ffmpeg` (video stream is copied — no re-encode, no quality loss). The fix is automatic when `ffmpeg`/`ffprobe` are on `PATH`; no action required. A new `ffmpeg_path` config key lets cabinet owners point to a non-`PATH` install.

- **`trailer` downloads now fall back to the `video` ScreenScraper type** when no normalised variant exists for a game. Previously only `video-normalized` was tried, so any game whose only ScreenScraper video was the raw `video` type received no trailer file.

---

## [2.7.1] - 2026-06-14

### Fixed

- **`fetch-meta` and `fetch-media` both stop immediately when a fatal scraper error is detected, protecting your API quota.** When a rate-limit (HTTP 429), server error (HTTP 500), or SS quota-exceeded response is received for any game, the metadata-resolution loop aborts at once rather than hammering the API for every remaining game. Remaining games are marked `aborted` in the per-game summary and in the audit CSV `{slot}_result` columns.

- **ScreenScraper and TheGamesDB API errors embedded in HTTP 200 responses are now surfaced.** SS signals quota/auth problems via an `"erreur"` key in a 200 body; TGDB signals auth failures via a `"code": 401/403` field in a 200 body. Both were previously silently treated as "game not found". These are now raised as `MetadataError` so they appear in the per-game summary and trigger the circuit breaker above.

- **`fetch-media` / `fetch-meta` now surfaces API errors instead of silently reporting "no match".** When both ScreenScraper and TheGamesDB are used (`--source both`) and both return an error (e.g. rate-limit exceeded, bad credentials, network failure), the combined client previously swallowed both errors and returned an empty result — causing every game to appear as "no match" and every slot to be counted as "Failed", with no indication of what went wrong. The combined client now re-raises a `MetadataError` containing both sources' error messages, which is shown in the per-game summary as `metadata error: ScreenScraper: <reason>`. This turns a completely opaque `Failed: 500` into a clear diagnostic.

- **`scraper.log` no longer exposes passwords in plaintext on DNS failures.** When a `NameResolutionError` or `MaxRetryError` occurs, urllib3 embeds the full request URL — including all query parameters — in the exception string. `_log_http` was logging `str(error)` verbatim, so `sspassword=<value>` and `devpassword=<value>` / `apikey=<value>` bypassed the `_redact_params()` sanitisation that correctly masked the `params` dict. A new `_redact_error_str()` function strips known secret values from the exception text before it hits the log file.

- **`fetch-media` now aborts early and surfaces the real error when DNS / network is down.** Previously, a DNS failure (`getaddrinfo failed`, `Max retries exceeded`) caused `CombinedMetadataClient.search()` to silently return an empty list for every game, producing "Failed: 500" with no diagnostic output — indistinguishable from 500 "no match" results. Two fixes: (1) `CombinedMetadataClient.search()` now re-raises `MetadataError` when both ScreenScraper and TheGamesDB fail (same pattern already applied to `fetch()`), so the error message reaches the console. (2) A circuit breaker stops Phase 1 metadata resolution after 3 consecutive network failures, prints the reason, and counts remaining games as failed rather than grinding through the whole list — turning a silent 500-failure run into an immediate, actionable error.

- **Metadata cache now works in combined (`--source both`) mode.** `CombinedMetadataClient` previously bypassed the on-disk cache entirely, so every `fetch-media` run made fresh API calls even when `fetch-meta` had already fetched and cached all game metadata. Games cached from a prior `fetch-meta --source both` run are now returned from cache, consuming zero API quota.

- **`fetch-meta --game` no longer fails with "not found" when the game already has complete metadata.** Previously `--game` filtered from `db.iter_incomplete()`, so explicitly targeting a game whose metadata was already filled in (e.g. to re-scrape after a bad import) always returned an error. The filter now falls through to the full game list when the named game is absent from the incomplete set, so re-fetching a specific complete game works as expected.

- **`fetch-media` per-game download log — verbose output now shows what actually happened per slot.** Instead of only printing a final `Downloaded: X  Skipped: Y  Failed: Z` summary, `fetch-media` now prints a separator and per-slot status for every game processed:
  - `existing` — file was already present; shows full destination path
  - `downloaded` — newly fetched; shows full destination path
  - `no URL` — scraper returned no candidate for this slot (common for video/theme on PC games)
  - `failed` — download error with the reason
  - `no metadata` / `no match` — scraper lookup failed entirely

- **`fetch-media` now accepts `--verbose` / `-v` for real-time per-game progress.** Without `--verbose`, output is unchanged: a spinner during metadata resolution and a per-game summary block after downloads complete. With `--verbose`: each game name is printed as its metadata is fetched (`Fetching: GameName → resolved`), and each download result is printed the moment it finishes (`downloaded: GameName · wheel  <path>`, `no URL: GameName · video`, etc.), so long runs show activity as it happens rather than all at once at the end. The GUI's global **Verbose** checkbox now wires this flag to both the "Run fetch-media" button and the "Full metadata refresh" chain.

- **GUI source dropdown no longer shows "config default".** The option was identical to "both (SS primary)" for any user with both ScreenScraper and TheGamesDB credentials configured (the normal case). "config default" has been removed and "both (SS primary)" is now the default selection, eliminating the confusion.

- **"Full metadata refresh" now correctly scopes `fetch-media` to the selected game.** When a single game was chosen from the GUI dropdown and "Full metadata refresh" was clicked, `fetch-meta` received `--game GameName` but `fetch-media` did not — it would then scan and attempt media downloads for every game on the system. The chain now passes `--game` to both steps.

- **Audit CSV now includes `{slot}_result` columns after a `fetch-media` run.** The auto-exported CSV gains `wheel_result`, `background_result`, … `theme_result` columns recording the per-slot outcome (`downloaded`, `existing`, `no_url`, `no_metadata`, `no_match`, `failed`) for the current run, so you can filter the spreadsheet to see exactly which games got new media.

---

## [2.7.0] - 2026-06-14

### Fixed

- **`pc-fix-exe` / `pc-rename` no longer pick `chromedriver.exe` or NW.js runtime files as the game executable.** Games packaged with NW.js (e.g. RPGMaker titles with `Game.exe`) bundle `chromedriver.exe` alongside the real launcher. `chromedriver` was not in the exclusion-prefix list, so it sorted before `Game.exe` alphabetically and was incorrectly selected. `chromedriver`, `nwjc`, and `nacl_irt` are now excluded, matching the existing treatment of uninstallers and redistributables.

- **"Fix PC game executable" panel now lists all game folders, not just games in the HyperSpin XML.** The game dropdown previously read from the HyperSpin database, so games that exist on disk but have not yet been added to the XML (e.g. newly installed GOG titles) did not appear. The dropdown now scans `roms_dir/<system>/` directly, matching the source used by the `pc-rename` CLI command. A case-insensitive folder name fallback is also applied so a "PC GAMES" ROM folder is found correctly when the selected system name is "PC Games".

- **"Fix PC game executable" system selector now defaults to the "PC Games" system on startup.** Previously the first system alphabetically was pre-selected. The GUI now checks whether any loaded system name matches `"pc games"` (case-insensitive) and, if so, selects it automatically — so the fix-exe panel is ready to use without needing to change the system picker.

- **`fetch-media` no longer crashes on PC GAMES entries when ScreenScraper returns `dates` as a list.** The ScreenScraper API returns the `dates` field as a list of `{region, text}` objects for some systems (notably PC GAMES) instead of the flat dict `{date_us, date_wor}` seen on other systems. The parser now handles both shapes, so release-year extraction works regardless of which format the API returns.

- **`fetch-media` no longer saves ScreenScraper media files as `.php`.** ScreenScraper serves all media through PHP scripts (`mediaJeu.php`, `mediaVideoJeu.php`) — the downloader was using the URL path's `.php` extension to rename the destination file, so every download landed as `Pikmin.php` instead of `Pikmin.png`. The extension-override logic now only fires when the URL contains a recognised media extension (`.png`, `.jpg`, `.mp4`, etc.); script endpoints like `.php` are ignored and the destination keeps its correct HyperSpin extension.

- **Nintendo DS is now recognised by both scrapers.** `"Nintendo DS"`, `"NDS"`, and `"DS"` are added to `SCREENSCRAPER_SYSTEMS` (ID 15) and `THEGAMESDB_PLATFORMS` (ID 8). Previously DS games were scraped without a platform filter, returning random matches instead of DS-specific results.

### Added

- **Comprehensive platform / system ID maps.** `SCREENSCRAPER_SYSTEMS` now covers all 249 ScreenScraper systems (237 lookup keys including aliases); `THEGAMESDB_PLATFORMS` now covers all 153 TheGamesDB platforms (235 keys). Both were verified against the live APIs on 2026-06-14. Previously each dict had only ~15–30 entries — systems not listed fell back to no platform filter, producing poor search results.

- **ScreenScraper wheel images now prefer US English over Japanese.** When ScreenScraper returns multiple region variants for the same media slot (e.g. a JP and a US wheel image), candidates are sorted by a fixed preference order: `us → wor → eu → fr → de → es → it → au → br → ru → kr → jp`. The first candidate in the sorted list is used for the slot URL and for auto-pick. Previously the API's arbitrary response order was used, which could return a Japanese wheel image for a game with a US version.

- **TheGamesDB now supplies wheel (clearlogo) and snap (screenshot) media.** A second API call to `GET /v1/Games/Images` is made after the main game search and fetches clearlogos, screenshots, and banners that are not returned by the primary boxart endpoint. Clearlogos map to the `wheel` slot and screenshots to the `snap` slot. ScreenScraper results always take priority; TGDB fills only slots that ScreenScraper did not populate. Previously only boxart was fetched from TheGamesDB.

- **GUI Fetch-media Source dropdown.** Step 3 — Fetch media in the Metadata & Media tab now has a **Source** dropdown (`screenscraper` / `thegamesdb` / config default), matching the equivalent control already present on the Fetch-meta step. Selecting a specific provider passes `--source <provider>` to `fetch-media`; "config default" sends no flag and lets the project config decide.

- **ScreenScraper + TheGamesDB combined client — SS primary, TGDB fills gaps.** `CombinedMetadataClient` queries both providers per game: ScreenScraper metadata and media take full priority; any slot that SS leaves empty (e.g. a missing wheel image) is filled from TheGamesDB. If SS finds nothing at all, the full TGDB result is used as fallback. `build_client()` now automatically returns the combined client when both credential sets are configured and no `--source` is forced. Previously running without `--source` only queried ScreenScraper.

- **`fetch-meta` and `fetch-media` now accept `--game` to target a single game.** `--game "Game Name"` (requires `--system`) limits the run to that one entry in the database, skipping all other games. Useful for re-scraping a single problem game or downloading missing media for one title without touching the rest of the system. Also accepted: `--source both` on both commands.

- **GUI Game picker on the Metadata & Media tab.** A **Game** dropdown appears below the System selector. When a system is chosen, the dropdown auto-populates with every game name from that system's database. Leave it blank to process all games (the existing behaviour). When a game is selected, `--game <name>` is passed to both `fetch-meta` and `fetch-media`.

---

## [2.6.3] - 2026-06-14

### Fixed

- **`pc-rename` and `add-pc-system` now write the correct `.exe` when the "rom" RL finds is a non-exe file.** RocketLauncher's extension-matching picks up whichever file matches the configured ROM extensions — for GOG games this is often `webcache.zip`, a cache file, or a redistributable archive rather than the actual game executable. SpinDoctor was forwarding this path verbatim to `Application=` in the per-game PCLauncher INI, causing the game to launch the wrong file. Both commands now call `_pick_best_exe` on the game folder whenever the proposed path is not an `.exe`: they filter out uninstallers, setup helpers, and other non-game executables, then prefer the file whose name best matches the game title. Applies to all write paths: initial `add-pc-system`, `pc-rename --apply`, and `pc-rename --overwrite-pclauncher --apply`. The `--verbose` table now also shows the resolved exe (not the raw ROM path) so stale entries are correctly flagged — a game whose INI was already fixed with `pc-fix-exe` no longer appears as "stale" on the next scan.

---

## [2.6.2] - 2026-06-14

### Added

- **`pc-fix-exe` command + GUI panel — fix a PC game launching the wrong executable.** When a PCLauncher INI has an uninstaller, GOG/Steam cache file, or redistributable set as `Application=` (e.g. `webcache.zip` instead of `ElecHead.exe`), run `spindoctor pc-fix-exe "PC GAMES" "ElecHead" --apply` to auto-detect and correct the entry. Auto-detection scans the game folder, filters out common non-game executables (`unins*`, `setup*`, `vcredist*`, `crashpad*`, etc.), and prefers the file whose name matches the game title; largest file wins ties. Use `--exe <path>` to override. The **Systems** tab now has a "Fix PC game executable" panel (directly below "Add new games / refresh a PC system") with system/game dropdowns and a candidate listbox. Also adds `list_exe_candidates()` (public) and `rewrite_pclauncher_application()` helpers in `rocketlauncher.py` so only `Application=` and `WorkingFolder=` are updated — user-set keys like `FadeTitle=` survive untouched.

### Fixed

- **GUI — game dropdowns (PR 292) always blank.** `_load_games_for_system` called `db.games.keys()` instead of `db.games().keys()` — `games` is a method, so accessing `.keys()` on the bound-method object raised `AttributeError`, which the bare `except Exception: return []` silently swallowed. All six game selectors (Systems rename/clone, Tools favorites, Diagnostics inspect, Metadata inspect, Metadata media, Maintenance ignore) now populate correctly. Exceptions are also logged at WARNING level to aid future diagnosis.

- **PCLauncher per-game INIs — section name mismatch when game title contains colons (or other Windows-invalid filename characters).** Game names like `Submachine: Legacy` cannot appear verbatim in a Windows filename, so SpinDoctor wrote the INI as `Submachine Legacy.ini` — but also used the same colon-stripped string as the INI section header (`[Submachine Legacy]`). PCLauncher receives the exact HyperSpin dbName (`Submachine: Legacy`, colon intact) from RocketLauncher and looks for that section; not finding it, it fell through to any stale system-level `PC GAMES.ini` entries, producing `Cannot find this Application: D:\…` errors. The INI filename now uses a Windows-safe stem while the section header preserves the original dbName (e.g. filename `Submachine Legacy.ini`, section `[Submachine: Legacy]`). `pc-rename` and `add-pc-system` both consult the HyperSpin XML to discover the correct dbName before writing INIs. The stale-detection path also passes the dbName so a mismatched section is correctly reported as stale rather than "current". The rename/clone command additionally rewrites the section header inside the INI file after moving it, so a rename from `Foo` to `Foo: The Sequel` produces a correct `[Foo: The Sequel]` section.

---

## [2.6.1] - 2026-06-13

### Added

- **GUI — Main Menu system reordering improvements.** The Treeview now supports two faster ways to reposition a system without clicking Move Up/Down one step at a time: (1) **Alt+Up / Alt+Down** keyboard shortcuts nudge the selected row up or down; (2) a **"Move to #"** entry field + **Go** button jumps the selected system directly to any position in a single action.

- **GUI — game dropdowns replace free-text entry fields across six locations.** Selecting a system now auto-populates a sorted **Game** dropdown from that system's HyperSpin database XML, with a **↻** refresh button to reload without switching tabs. Affected locations:
  - **Systems → Step 3 — Rename or clone a game** (Game field)
  - **Tools → Step 4 — Manage favorites** (Game field)
  - **Diagnostics → Step 4 — Inspect** (ROM optional dropdown; blank = `inspect --all`)
  - **Metadata & Media → Inspect** (same, second occurrence)
  - **Metadata & Media → Add one local media file** (Game field)
  - **Maintenance → Ignore list** (Game name field)

- **`pc-rename` now detects stale PCLauncher INIs** — per-game INIs whose `Application=` no longer matches the live executable path (e.g. after a drive migration or file rename). Stale entries are flagged in `--verbose` output and in the dry-run summary. Pass `--overwrite-pclauncher` to rewrite them. INIs previously written in the old `[Settings]` / `ApplicationPath=` format are also flagged as stale so they are regenerated in the correct format.

- **GUI — four previously CLI-only `--overwrite` flags are now exposed:**
  - **Metadata & Media → Step 4 (media-scan):** "Overwrite existing files (--overwrite)" checkbox — imports files into already-filled slots and includes the "replacement" bucket.
  - **Metadata & Media → Step 5 (generate-config):** "Overwrite Global Emulators.ini (--overwrite-global)" checkbox — replaces an existing `Global Emulators.ini` instead of leaving user customisations alone.
  - **Systems → Sort & Organize (organize):** "Overwrite existing sort files (--overwrite-sort)" checkbox — replaces existing sort-database XMLs instead of skipping them.
  - **Systems → Add system (add-pc-system):** "Overwrite existing PCLauncher INIs (--overwrite-pclauncher)" checkbox — rewrites stale or wrong-path per-game INIs when re-running `add-pc-system`.

- **GUI — Systems tab: "Add new games / refresh a PC system" section redesigned.** The section was labelled "Re-review titles for a PC system" with a "Run pc-rename" button — neither name indicated it scans for new games. Renamed with a plain-English description. New **Overwrite existing INIs** checkbox exposes `--overwrite-pclauncher` so stale paths (wrong drive, renamed exe) can be fixed without leaving the GUI.

- **`pc-rename --verbose` now shows a per-game table** with Title, Executable path, and INI status (`new` / `stale` / `current`). Stale entries show the wrong path currently in the INI so you can confirm the problem before re-running with `--overwrite-pclauncher`.

### Fixed

- **`pc-rename` dry-run now reports accurate write counts.** Previously "Would write N PCLauncher INI(s)" counted all titles regardless of whether their INI already existed, overstating what would actually be written. The dry-run now separately counts new, stale, and current entries and reports only the number that would actually change.

- **PC game per-game PCLauncher INIs now use the correct format.** SpinDoctor previously wrote `[Settings]` / `ApplicationPath=` in per-game INIs (`Modules\PCLauncher\<System>\<Game>.ini`). PCLauncher.ahk reads `[<game_name>]` / `Application=` — it does not recognise `ApplicationPath=`, so the stale system-level `<System>.ini` (often left over from RLUI with old relative paths) was being used instead, causing "Cannot find this Application" errors. Per-game INIs now use the correct `[<game_name>]` / `Application=` format that PCLauncher.ahk actually reads. Any existing INIs in the old format are detected as stale and can be rewritten by running `pc-rename --overwrite-pclauncher --apply`.

- **GUI system dropdowns showed case-variant duplicates** (e.g. "PC GAMES" and "PC Games") when the ROMs folder and Databases folder used different capitalisation for the same system name. On Windows, filesystem names are case-insensitive but Python's `set` is not. `get_systems()` now deduplicates case-insensitively and prefers the `databases_dir` spelling (which matches the name HyperSpin uses).

- **GUI — Output panel "Show output" restored at minimum height.** `after_idle` fired before Tk had finished laying out the re-added pane, so the sash position wasn't applied and the panel appeared as a tiny draggable sliver. Changed to `after(100)` so layout has settled first. When no prior sash position was saved (first show), the panel now opens at `window_height − 160 px` instead of collapsing.

- **Synthetic-wheel navigate sound now installs as `Wheel Click.mp3`.** The cabinet requires the filename `Wheel Click.mp3` in `Media\<SystemName>\Sound\`; it was previously being written as `navigate.mp3`. No bundled asset change — only the destination filename is corrected.

- **GUI — four tabs renamed for clarity:** "Tools" → **Toolkit**, "Migrate" → **Migration**, "Custom Command" → **Console**, "Logs" → **History**. All documentation and in-GUI status messages updated to match.

- **GUI — all tabs now open with a one-line purpose statement.** Systems, Toolkit, and LEDBlinky previously dropped straight into controls; they now show a brief description at the top consistent with the other nine tabs.

---

## [2.6.0] - 2026-06-13

### Changed

- **Build: standalone tool EXEs no longer bundle `click`, `rich`, or GUI modules.** `spindoctor-fav.exe`, `spindoctor-recent.exe`, and `spindoctor-stats.exe` use `argparse` directly and have no transitive dependency on `click`, `rich`, `tkinter`, or `PIL`. The build script's hidden-import list now splits `_CORE_CLI` (click + rich) from `_CORE_BASE`, and passes `--exclude-module` for those libraries when building the standalone targets.

- **Build: standalone tool EXEs no longer bundle `lxml`.** `database.py` now imports `lxml.etree` lazily via `_lxml_etree()` instead of at module level. The standalone tools (`spindoctor-fav`, `spindoctor-recent`, `spindoctor-stats`) use `--exclude-module lxml` and take the stdlib `xml.etree.ElementTree` fallback path, shedding ~7–9 MB of libxml2/libxslt C extensions. The full CLI and GUI continue to use lxml for comment-preserving XML round-trips. HyperSpin XML files written by the standalone tools are valid; comments are not present in those files in practice.

### Fixed

- **Several GUI actions wrote to the Output panel but never appeared in the Logs tab.** Theme-apply Apply, Curate Apply, Ignore viewer "Remove selected", and all three Task Scheduler actions (Schedule / Remove / Check status) now each create a `_RunRecord` entry so the result is visible in the Logs tab alongside CLI-based runs.

- **MAME subsystem videos still not copied when `Media\<System>\Video\` directory exists but is empty.** The v2.5.3 fix for the HyperSpin `[video defaults]` redirect only activated when the system's `Video\` folder was completely absent. HyperSpin creates the directory skeleton (`Media\4-Player Games\Video\`, etc.) without populating it, so SpinDoctor found the empty folder, skipped the MAME redirect, iterated an empty directory, and produced no copy actions — leaving `iceclmrdxbox.mp4` and similar videos missing from the Favorites wheel. Fixed by checking whether the system's `Video\` folder actually contains a file for the specific game, not just whether the folder exists.

---

## [2.5.3] - 2026-06-13

### Fixed

- **Recently Played wheel returns 0 entries on cabinets running newer RocketLauncher builds.** Newer RL writes `Last_Time_Played` in per-system Statistics.ini files (e.g. `MAME.ini`), but SpinDoctor was only checking the older `Last_Played` / `LastPlayed` key names. Every record was silently skipped → the rebuilt wheel was always empty. Most Played was unaffected because it can rank games by `Number_of_Times_Played` without needing a timestamp. Fixed by trying `Last_Time_Played` first, then falling back to the older key names.

- **Synthetic wheel media copy now follows HyperSpin's `[video defaults]` video redirect for MAME subsystems.** MAME subsystem wheels ("4-Player Games", "Driving Games", "Gun Games", etc.) store all their videos in `Media\MAME\Video\` rather than a per-system folder. HyperSpin reads the redirect from `D:\Arcade\Settings\<System>.ini` under `[video defaults]` / `path=`. SpinDoctor was ignoring this redirect and only looking in `Media\<System>\Video\`, so videos for subsystem games (e.g. `iceclmrdxbox.mp4` in "4-Player Games") were silently skipped during `fav rebuild` and `recent rebuild`. The mirror now reads the redirect path from the HyperSpin settings INI via `_read_hs_video_dir` and falls back to that directory when the system's own `Video\` folder is absent.

- **GUI: seven operations ignored the global Apply checkbox and always wrote to disk.** The following buttons/actions now correctly dry-run when Apply is unchecked and write only when it is checked:
  - **Refresh selected wheels** (`_refresh_all_wheels`) — `spindoctor-fav rebuild`, `spindoctor-recent rebuild`, `spindoctor-stats build-wheel`
  - **Add wheels to Main Menu** (`_register_wheels_in_main_menu`) — `mainmenu add` for Favorites / Recently Played / Most Played
  - **Undo this run (migrations)** in File → View logs & manifests — `migrate --undo`
  - **Pre-migration backup Create button** (`_run_pre_migrate_backup`) — `backup create`
  - **Restore from sidecar .bak** (`_restore_sidecar`) — `backup sidecar restore`
  - **Main Menu add / remove** (`_run_mainmenu_action`) — `mainmenu add` / `mainmenu remove` (the GUI comment claiming these had no dry-run path was incorrect; the CLI has supported `_apply_or_preview` for both since they were added)
  - **Uninstall from wheel** (`_run_uninstall_tools_from_wheel`) — `uninstall-tools`

---

## [2.5.2] - 2026-06-13

### Fixed

- **`generate-config` now handles all MAME-variant systems robustly without requiring per-system overrides.** Three new behaviours extend the existing preservation guard:
  - *System name contains "MAME" (new or missing file):* `Default_Emulator` is inferred as `MAME` and `Rom_Path` falls back to `roms_dir\MAME` instead of the non-existent `roms_dir\<SystemName>` folder (covers `MAME (Vector)`, `MAME Atari Classics`, etc.).
  - *Existing file declares a MAME-family emulator with a relative `Rom_Path`:* the relative path is resolved from the RL root directory (how RocketLauncher itself resolves it). If the resolved directory exists, the path is preserved. If it no longer exists (e.g. ROMs were moved from D: to J: after the backup was taken), the path is replaced with `roms_dir\MAME`. Dry-run shows `preserved (MAME emulator)` for the preserved case.
  - *Existing file declares a MAME-family emulator with an absolute `Rom_Path` that no longer exists:* path is replaced with `roms_dir\MAME` (if that folder exists). This fixes the post-restore breakage for non-MAME-named systems like `4-Player Games` whose `Default_Emulator` is `MAME (XBOX 4P DSW)` — their ROMs live in `J:\Games\MAME`, not `J:\Games\4-Player Games`.

---

## [2.5.1] - 2026-06-13

### Changed

- **Windows release zip reverts to five standalone self-contained EXEs (rolling back the v2.5.0 shared-runtime folder).** The v2.5.0 `--onedir` bundle produced a flat directory of ~60 files rather than the clean nested layout the PR intended: PyInstaller 6.x nests its shared runtime under `_internal/`, but upgrading is blocked by the Windows 7 SP1 cabinet requirement — PyInstaller 6.x's bootloader references `api-ms-win-core-path-l1-1-0.dll`, which doesn't exist on Windows 7 even with SP1. PyInstaller 5.x's bootloader hardcodes `sys._MEIPASS = Path(sys.executable).parent`, so DLLs must land next to the EXEs and cannot be nested. Result: the v2.5.0 zip was an unusable flat mess. Reverted to `--onefile`. Each binary is self-contained — extract the zip, move the EXEs wherever you like, double-click `spindoctor-gui.exe`. Note: hidden imports are now split per-target as a hygiene measure, but EXE sizes remain similar across all five — each pays the full Python 3.8 runtime cost and the transitive import graph from shared spindoctor modules means the standalone tools pull in nearly as much as the full CLI regardless.

---

## [2.5.0] - 2026-06-12

### Changed

- **Windows release zip is now a shared-runtime folder instead of five separate self-extracting EXEs.** The zip now contains a `spindoctor\` folder; extract it, optionally rename it (e.g. `C:\spindoctor\`), and double-click `spindoctor-gui.exe`. All five executables share a single Python 3.8 runtime bundled in that folder, roughly halving the total download size. Individual EXEs must remain in the folder alongside the shared runtime — do not move them out. The GUI's peer-discovery (`resolve_cli_command`) and the autostart scheduled-task bat files are unaffected; both already used `Path(sys.executable).parent` to locate sibling binaries, which resolves correctly in `--onedir` mode.

### Fixed

- **Tools-menu terminal windows now close automatically after a refresh completes.** When launched from HyperSpin's Tools menu via RocketLauncher/PCLauncher, the `Refresh Favorites`, `Refresh Recently Played`, `Refresh Most Played`, and `Refresh All` bat files would leave a blank cmd window visible on the desktop after HyperSpin was closed. The bat scripts now end with an explicit `exit` command, which forces the cmd.exe process to close even when the launcher opens the bat with a persistent console (as PCLauncher does on Windows 7). Run `install-tools` again to redeploy the updated bat files to the cabinet.

---

## [2.4.27] - 2026-06-12

### Fixed

- **Toolkit tool runs (Refresh Favorites, Refresh Most Played, etc.) no longer appear in Recently Played or Most Played wheels.** When a user launches a Toolkit tool from within HyperSpin, RocketLauncher records that run in the Toolkit system's statistics file. Previously, `collect_play_records` and `load_all_playtime` included Toolkit stats when building synthetic wheels, so tool runs appeared as "games" and could push real games out of Recently Played entirely. Toolkit is now part of the `_STATS_EXCLUDE` set (alongside the synthetic wheel names) and is excluded from both the per-system stats reader and the `known`-systems filter in every synthetic wheel rebuild.

- **Recently Played wheel no longer appears empty after running Toolkit refresh tools.** The root cause was the above: if a user ran Refresh Favorites / Most Played from HyperSpin several times, the most-recent-20 play records were dominated by Toolkit runs. The DB validation from v2.4.26 then dropped those runs because they fail to match any real-game database, leaving the wheel with zero entries. Excluding Toolkit from stats collection restores real game plays as the top candidates.

- **`install-tools` now removes the stale `Refresh Both.bat` (and its companion `.ini`) left by older versions when re-run.** `Refresh Both` was silently renamed to `Refresh All` in v2.4.26; without active cleanup the old bat remained on disk and appeared as a confusing duplicate entry in the HyperSpin Tools menu alongside `Refresh All`. Running `install-tools` again now removes any stale bat/ini for tools that no longer exist and, when `--add-to-system` is used, also removes the stale `Refresh Both` database entry from the target system's XML so the wheel no longer shows the dead entry.

- **`generate-config --apply` no longer overwrites a working custom `Rom_Path` with a non-existent per-system folder.** Some MAME variants (`MAME (Vector)`, `MAME (Vertical)`, etc.) share a single ROM directory (e.g. `J:\Games\MAME`) rather than having their own sibling folder (`J:\Games\MAME (Vector)`). Previously, `generate-config` derived `Rom_Path` as `roms_dir\<system_name>` for every system, so running it on a cabinet with MAME variants replaced the working shared path with a non-existent folder, breaking every launch in those systems. The fix adds a preservation guard: if the existing `Emulators.ini` already points at a directory that exists and the computed new path does not, the current value is left untouched. For explicit control, a `rom_path` key in `system_overrides` always takes precedence over the derived path.

---

## [2.4.26] - 2026-06-12

### Fixed

- **Recently Played and Most Played wheels no longer produce broken PCLauncher INIs for games with stale statistics entries.** When a game is launched from a synthetic wheel via RL#2 and the launch fails (e.g. wrong ROM name), RL#2 still records playtime stats against the source system under whatever name PCLauncher passed as `-r`. On the next rebuild, SpinDoctor would read that stale entry and write a PCLauncher INI with the wrong `-r` parameter, causing every future launch to fail — a self-reinforcing cycle. `_build_synthetic_wheel` now cross-references each statistics entry against the source system's HyperSpin database XML before writing any launcher. Entries whose `rom_name` does not appear in the database are logged and skipped, so only valid, launchable games are included in the wheel. Entries from systems whose database cannot be read are preserved unchanged (safe default).

- **Standalone wheel tools no longer crash with `PermissionError: [WinError 31]` when launched from HyperSpin's Tools menu on Windows 7.** On Windows 7, calling `SetConsoleOutputCP(65001)` can leave the console handle in a broken state where every subsequent `write()` or `flush()` raises `PermissionError` (ERROR_GEN_FAILURE). `enable_windows_utf8_console()` now wraps `sys.stdout` and `sys.stderr` in a `_SafeWriter` shim that silently swallows `OSError` on those two calls, so the process continues normally. Previously all three Tools-menu helpers (`spindoctor-fav`, `spindoctor-recent`, `spindoctor-stats`) crashed before doing any work, leaving the "Press any key to continue…" prompt in a console window hidden behind HyperSpin. The fix also means the Recently Played wheel now builds correctly — the crash was happening at the very first `print()` inside `_build_synthetic_wheel`, preventing any database write or media copy.

---

## [2.4.25] - 2026-06-12

### Fixed

- **GUI — startup update-check thread no longer raises an unraisable exception on Python 3.12 during test teardown.** The background worker in `_start_update_check` called `self.root.after()` after the Tkinter root was destroyed (a race: monkeypatch reverts before the daemon thread exits, so the real `check_for_update` could return a non-`None` result). The call is now wrapped in `try/except` so a destroyed root is silently ignored. Fixes three `test_gui.py` failures on CI.

### Performance

- **Favorites sync no longer parses every console's database.** `fav sync` / `fav rebuild` previously full-parsed each system's `<System>.xml` while crawling for favorites — cost scaled with *(consoles × games per console)* even when most consoles had no favorites. The crawl now does a fast text pre-scan for the `favorite="1"` marker and only parses a database when a favorites source (XML flag / `_Favorites.ini` / `favorites.txt`) is actually present, so favorite-free consoles cost a few `stat` calls instead of a full parse.
- **Synthetic wheel rebuilds parse each source database once.** `fav rebuild`, `recent rebuild`, and `stats-report build-wheel` re-loaded a source system's database once *per entry* drawn from it (50 SNES favorites → 50 SNES XML parses). Source databases are now memoised per rebuild, so each source system is parsed a single time.

### Changed

- **Synthetic wheel commands gained a live per-console progress indicator and `--verbose`.** `fav sync` and `fav rebuild` show an in-place `Scanning <System> (i/N)…` counter while crawling consoles (suppressed automatically when output is captured, e.g. by the GUI); `--verbose`/`-v` additionally prints per-console detail (which consoles contributed favorites, and each media file mirrored). `recent rebuild` and `stats-report build-wheel` also gained `--verbose`/`-v` for media-mirror detail. The GUI's existing global **Verbose** toggle already routes through these.

- **GUI — tab strip and per-tab layouts reordered around the new-user journey.**
  - **Diagnostics now sits second (Setup → Diagnostics → Systems)** — after pointing SpinDoctor at the library, the natural next click is "is everything wired up?", and Diagnostics is entirely read-only so it's safe to explore before touching anything.
  - **Setup tab:** the **Run first-run wizard…** button moved from the bottom button row (after Save) to the top of the tab — it's the new-user entry point, so it leads rather than trails. Path fields are now grouped under **Core paths** (ROMs / HyperSpin / Emulators / RocketLauncher) and **Optional paths** (feature-specific; fine to leave blank), and the credentials header reads **Scraper credentials (optional)**.
  - **Diagnostics tab:** new **Step 1 — Cabinet health check** leads with the three zero-input buttons (Preflight check / Run doctor / Tools audit); the per-system audit becomes Step 2; library-wide scans and search & verify renumber to Steps 3–4. Previously Preflight — the headline one-click — was buried mid-section as the sixth button.
  - **Tools tab:** **Sync favorites from HyperSpin** is promoted to **Step 1 — Import HyperSpin favorites (optional)**. It previously lived inside the register section *after* the wheel rebuild, while its own tooltip said to run it *before* the rebuild — the layout contradicted the instructions. Refresh / Register / Manage favorites renumber to Steps 2–4.
  - **Systems tab:** the unnumbered "Re-review titles for a PC system" form moved below Step 4 with the other occasional-use forms, so Steps 1–4 read contiguously (this also matches the order gui.md already documented).
- **GUI — removed the dead legacy `_build_wheels_tab` builder** (~175 lines) — never called since the Wheels tab was merged into Tools; it also re-created the wheel checkbox variables and would have shadowed the live ones if ever invoked.

### Fixed

- **`Images/Titles/` and `Images/Letters/` are now mirrored to synthetic wheels (Favorites / Recently Played / Most Played).** Both directories were absent from `MEDIA_FILE_SUBDIRS` in `medialink.py`. HyperSpin themes display title-screen captures from `Images/Titles/` (shown in a side panel or preview slot when a game is selected), so games in synthetic wheels showed a blank title-image slot even though the source system had the files. Regression tests added.
- **`.wmv`, `.mpeg`, and `.mpg` video files are now mirrored to synthetic wheels.** Windows Media Video (`.wmv`) and legacy MPEG formats were absent from `_FILE_EXTS`. `.wmv` is native to Windows 7 and very common in older HyperSpin video packs — games whose preview videos used these formats showed no video in any synthetic wheel. Regression tests added.
- **Synthetic-wheel media cleanup no longer crashes on first run when the target media directory does not yet exist.** The orphan-cleanup loop in `_build_synthetic_wheel` (used by all three synthetic wheels) and in the Favorites `rebuild` called `Path.rglob()` on the target media directory without first checking that it exists. On Python 3.8 (the frozen-binary floor for Win 7 cabinets), iterating a nonexistent directory raises `FileNotFoundError` rather than returning an empty iterator, so `recent rebuild` / `stats-report build-wheel` / `fav rebuild` would crash before copying any media on a fresh cabinet install. Both loops are now guarded with `if …is_dir():`.

- **Standalone wheel tools no longer risk crashing mid-render on the Windows 7 console.** The `spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` binaries are separate frozen executables that never imported the main CLI module, so they skipped the UTF-8 console setup (`SetConsoleOutputCP(65001)` + stream reconfigure) the primary CLI has always run — yet they print em-dashes, ellipses, and middle dots that the cabinet's default codepage can't encode. That setup is now a shared `_compat.enable_windows_utf8_console()` helper called by every entry point (the main CLI and all three standalone `main()`s), so all of them render identically on Win 7. No-op off Windows.
- **Favorites sync now actually reads `favorite="1"` XML attributes.** `sync_native` checked `getattr(game, "favorite", …)`, but the database loader keeps unmodelled attributes (including HyperSpin's `favorite="1"`) in `GameEntry.extra_attrs`, so the attribute was never read — the XML-flag path was dead code and only `_Favorites.ini` / `favorites.txt` favorites were picked up. It now reads the flag from `extra_attrs`, so favorites set directly in the system XML are imported as documented.
- **`media-add` and `pc-rename` are now dry-run by default with `--apply`** — both commands wrote to the cabinet immediately (`media-add` copied/moved into the Media tree; `pc-rename` wrote PCLauncher INIs into `Modules/PCLauncher/`) with no `--apply` gate, violating the project-wide dry-run contract. Worse, the docs already showed `--apply` examples for both, so following the documentation produced an unknown-option error — and the GUI's "Run pc-rename" button with the global Apply toggle ticked failed the same way. Both commands now preview without `--apply` and commit with it; the GUI passes the flag per the global Apply toggle.
- **GUI — DRY RUN banner no longer lies for write-always commands** — `fav add/remove/sync`, `ignore add/remove/clear`, `match clear`, and `emulator-title set/remove` write immediately (single-record mutations with no `--apply` concept), but were missing from `_READ_ONLY_COMMANDS`, so the GUI wrapped them in a `=== DRY RUN ===` banner while they actually wrote — the same class of bug as the historical `uninstall-tools` banner lie. They are now classified as N/A. Also added genuinely read-only commands that were missing from the set (`self-doctor`, `config verify-credentials`, `backup sidecar list`, `ledblinky colors list`, `ledblinky inspect-rom`) and taught the matcher three-token command forms.
- **GUI — runs with `--apply` are always recorded as actual writes** — commands that are read-only without `--apply` but write with it (`doctor --apply`, `lightgun detect --apply`) were tagged `# Dry-run: N/A` in the Logs tab even when they wrote. The `--apply` check now takes precedence over the read-only classification.
- **GUI — child processes get `stdin=DEVNULL`** — the CLI subprocess previously inherited the GUI's stdin; when the GUI was launched from a terminal, any prompting command (`mainmenu edit`, `config init`, an unexpected picker) blocked forever on the *terminal's* stdin and the run appeared hung. Prompts now see EOF and abort cleanly.
- **GUI — broken Custom Command presets corrected** — all `organize` presets omitted the required system argument (and two used a nonexistent `--system` flag); `config system set <SYSTEM> --layout wheel` used an invalid choice (now `flat`). Every preset is now validated against the real Click command tree by a regression test.
- **`update-db --add-missing` gained a working off-switch** — the flag was declared `is_flag=True, default=True`, so it was always on and passing it changed nothing. Now declared as `--add-missing/--no-add-missing` so orphan-removal-only runs are possible.

### Removed

- **Dead code** — `Config.effective_output_dir`, `MediaDownloader.download_from_metadata`, `rocketlauncher._read_existing_emu_path`, `rocketlauncher.pclauncher_exe_info_text` (generator for the `[exe info]` INI dialect the project deliberately avoids), two unused imports, two unused local variables, and ~25 lint-level cleanups (f-strings without placeholders, unused test variables). `ruff check` is now clean.

### Documentation

- **commands.md now documents every flag it promised** — added the previously-undocumented `audit --no-fuzzy/--show-matched`, `fetch-meta --source/--threshold`, `fetch-media --source`, `update-db --no-add-missing`, `generate-config --no-main-menu/--no-global-emulators/--overwrite-global/--system`, `organize --no-sort/--axes/--overwrite-sort`, `media-scan --types/--no-recursive`, `add-system --no-menu/--no-db/--source`, `add-pc-system` step-skipping flags, `pc-rename --no-pclauncher/--overwrite-pclauncher`, `cleanup run --exclude`, `lint --source`, `report --system/--no-media/--no-fuzzy`, and `config system set --thegamesdb-id` (configuration.md).
- **Removed the false claim that `pc-rename` writes a rename manifest with `--undo` support** (neither `add-pc-system` nor `pc-rename` has an `--undo` flag); fixed the `media-add` example in synthetic-wheel-media.md that passed the file as a positional argument instead of `--file`; corrected gui.md's read-only/write-always command list; refreshed README preset counts (~255 across 19 sections).
- **CLI `--help` text added to bare options** — `--source` (four commands), `--show-matched`, `--add-missing`, `report --output/--no-media/--no-fuzzy`.

### Fixed

- **GUI — Logs tab `# Dry-run:` header now shows `N/A` for read-only commands** — previously every read-only command (e.g. `audit --all`, `doctor`, `tools-audit`) showed `# Dry-run: False`, which appeared to say "this wrote to disk." The field now shows `N/A` for commands where the dry-run concept does not apply (genuinely read-only or write-always-no-`--apply`), `Yes` for dry-run previews, and `No` for actual writes. The same fix applies to the "Save selected output…" export header.
- **GUI — `stats-report build-wheel` / `stats-report clear-wheel` now correctly classified as dry-run-capable** — both subcommands support `--apply` and are dry-run by default, but the `stats-report` single-token entry in `_READ_ONLY_COMMANDS` caused them to be marked as N/A instead of showing the `=== DRY RUN ===` banner and `DRY-RUN` Logs tag when run without `--apply`. A new `_WRITE_SUBCOMMAND_PAIRS` set is checked before the single-token lookup so the subcommand-level rule wins.
- **GUI — removed invalid `--apply` from `install-tools` Custom Command presets** — `install-tools` has no `--apply` flag; the preset entries `install-tools --apply` and `install-tools --add-to-system <SYSTEM> --apply` would have failed at runtime with an unknown-option error. Corrected to `install-tools` and `install-tools --add-to-system <SYSTEM>`.
- **GUI — `check-archive-ext` added to `_READ_ONLY_COMMANDS`** — the new read-only diagnostic was missing from the set, so running it via Custom Command would have incorrectly shown the `=== DRY RUN ===` banner.

### Added

- **`install-tools` — now writes the PCLauncher module INI** — `install-tools --add-to-system <SYSTEM>` now writes (or updates) `Modules/PCLauncher/<SYSTEM>.ini` with `[<tool_name>]` sections containing `Application=<bat_path>` and `WorkingFolder=`. Without this file PCLauncher.ahk had no game configuration to read and errored immediately with *"You have not set up \<tool\> in RocketLauncherUI yet, so PCLauncher does not know what exe, FadeTitle, and/or SteamID to watch for."* The per-game placeholder `.ini` files in the `Rom_Path` are only used by RocketLauncher for ROM discovery; PCLauncher.ahk reads game settings exclusively from the module INI. Existing non-SpinDoctor sections in the module INI are preserved; SpinDoctor tool sections are replaced on re-run.
- **GUI — Logs tab entry for "Save Order" (Main Menu tab)** — clicking "Save Order" now creates a `_RunRecord` entry visible in the Logs tab, matching the behaviour of all other GUI actions that write files.
- **GUI — Logs tab entry for "Save configuration" (Setup tab)** — saving setup configuration now creates a `_RunRecord` entry in the Logs tab.
- **GUI — Logs tab entry for "Save selected output…" (Logs tab)** — exporting a log entry to a `.txt` file now creates a `_RunRecord` entry recording the saved path.
- **`rocketlauncher.py` — `write_toolkit_module_ini()` function** — writes or updates the PCLauncher module INI for Toolkit-style wheels, merging SpinDoctor tool sections while preserving user-configured entries.
- **`uninstall-tools` — now removes PCLauncher module INI sections** — `uninstall-tools --add-to-system <SYSTEM>` now strips the SpinDoctor-written `[Refresh …]` sections from `Modules/PCLauncher/<SYSTEM>.ini`, preserving any non-SpinDoctor sections. If the file is left empty it is deleted entirely. Mirrors the new `install-tools` module INI writing so uninstall is a clean reverse.

- **GUI — wheel refresh progress feedback** — the "Refresh selected" button in the Tools tab now shows a pulsing (indeterminate) progress bar for the full duration of the rebuild, and each phase of `fav rebuild` is now reported to the Output panel in real time: `building wheel`, `writing database`, `database done`, `mirroring media`, `media done`, `writing PCLauncher INIs`, `PCLauncher INIs done`, `wheel build complete`. Previously the bar showed a static empty fill with no animation and no per-phase output until the entire rebuild finished. `recent rebuild` and `stats build-wheel` already emitted phase output; only `fav rebuild` was silent.
- **`check-archive-ext` command** — new read-only diagnostic that peeks inside `.zip`, `.7z`, and `.rar` archives across all configured ROM directories and reports any archive whose inner file extension is not listed in the RocketLauncher `Rom_Extension=` configuration for that system's emulator. Cross-references `Global Emulators.ini` first, falls back to SpinDoctor's built-in emulator-extension map. Addresses the *"No valid roms found in the archive"* RocketLauncher error at diagnosis time rather than launch time. Run `spindoctor check-archive-ext --system <NAME>` or `--all`.
- **GUI — Diagnostics — "Check archive extensions" button added to Step 2** — one-click equivalent of `check-archive-ext --all`; output and status routing follow the standard library-wide scan pattern.
- **`rocketlauncher.py` — `read_rl_rom_extensions()` function** — reads the configured `Rom_Extension` set for a given system from `Global Emulators.ini` (or per-system `Emulators.ini`), with fallback to `EMULATOR_EXTENSIONS`. Used by `check-archive-ext`.
- **`rocketlauncher.py` — Nintendo-prefixed system name entries added to `EMULATOR_MAP`** — `"nintendo gamecube"`, `"nintendo wii"`, `"nintendo wiiware"` now resolve correctly alongside the existing short-form entries. Fixes `guess_emulator()` misses when HyperSpin system names carry the full manufacturer prefix.
- **`rocketlauncher.py` — Dolphin `EMULATOR_EXTENSIONS` expanded** — added `gcz` and `ciso` to the built-in Dolphin extension list (was `iso|gcm|wbfs|rvz`; now `iso|gcm|gcz|wbfs|ciso|rvz`).
- **`docs/cabinet-architecture-reference.md` — Dolphin version and ROM format notes added** — new section covering: version history table (Ishiiruka 2017 → 5.0-16101, last Win7 build with RVZ support), portable-mode directory layout, ROM format table with RVZ compatibility notes, upgrade procedure (replace exe, preserve `User\` settings folder), and second-instance emulator setup in `Global Emulators.ini`.

### Fixed

- **`generate-config` — synthetic wheels (Favorites, Recently Played, Most Played) are no longer removed from `Main Menu.xml` on every run** — `generate_hs_main_menu` builds the ordered system list from `existing ∩ systems_set`, and those three wheel names are excluded from `systems_set` by `SKIP_GENERATE_CONFIG`. This caused them to be silently dropped every time generate-config ran. The fix preserves any existing Main Menu.xml entry whose name is in `SKIP_GENERATE_CONFIG − {"Main Menu"}` (i.e. the three synthetic wheel names) even when they are absent from the `systems` list.

- **Synthetic wheels — `[PCLauncher]` section with `Rom_Extension=ini` now written to the folder-layout `Settings/<system>/Emulators.ini`** — RocketLauncher v1.2 reads `Rom_Extension` from the emulator section (`[PCLauncher]`) first; when that section is absent from the system file RL falls back to `Global Emulators.ini`'s `[PCLauncher]` which may not carry `Rom_Extension=ini`. The fallback then uses RL's built-in default extension list (`zip|rar|7z|lha|lzh|gzip|tar|`) and fails with *"Cannot find Rom \<game\> In any Rom_Paths provided … with any provided Rom_Extension: zip|rar|7z|…"*. Fix: `generate_synthetic_system_ini` now writes `[PCLauncher]` with `Rom_Extension=ini` in both the flat-layout and folder-layout files so RL always finds the correct extension directly in the system file, regardless of `Global Emulators.ini` content.

- **`mainmenu add` — now regenerates RL system settings when adding a synthetic wheel** — the GUI "Register in Main Menu" button calls `mainmenu add Favorites/Recently Played/Most Played --apply`. Previously this only added the entry to `Main Menu.xml` and installed bundled media; if the `Settings/<system>/Emulators.ini` was missing or stale the wheel would appear in HyperSpin but games would fail to launch with the wrong-extension error above. `mainmenu add` now also calls `generate_synthetic_system_ini` for synthetic wheel systems so the RL settings are always correct after clicking the button.

- **`EMULATOR_EXTENSIONS["PCLauncher"]` corrected to `"ini"`** — the extension was previously set to `"exe|lnk|url|bat"` (the application file types that live _inside_ a per-game INI). PCLauncher "ROMs" are always `.ini` files stored in `Modules/PCLauncher/<system>/`; the executable is referenced inside the INI, not used directly as a ROM file. The corrected value means `generate_global_emulators_ini` now writes `Rom_Extension=ini` for the `[PCLauncher]` section in new or overwritten `Global Emulators.ini` files.

---

## [2.4.24] - 2026-06-10

### Changed

- **GUI — tab order resequenced to match new-user journey** — tabs now appear in this order: Setup → Systems → Diagnostics → Metadata & Media → Maintenance → Tools → LEDBlinky → Lightgun → Backup & Restore → Migrate → Custom Command → Logs. Systems (formerly tab 6) is now tab 2 so cabinet owners configure their library before running diagnostics. Logs (formerly tab 11) is now the last tab. Custom Command (formerly last) is now tab 11. The `Ctrl+1–9` shortcuts still jump to tab N by visible position.
- **GUI — all action tabs now use numbered Step sections** — Diagnostics (3 steps), Systems (4 steps), Metadata & Media (5 steps + 2 unnumbered advanced sections), Maintenance (Step 1), Lightgun (2 steps), Backup & Restore (3 steps), Migrate (5 steps). Tools tab split into Step 1 — Refresh custom wheels, Step 2 — Register in HyperSpin main menu, Step 3 — Manage favorites (formerly all packed into one "Custom wheels" LabelFrame). LEDBlinky already had Steps 1–9 from the previous release.
- **GUI — Metadata & Media — "Full metadata refresh" chain button promoted to Step 1** — the one-click fetch-meta → fetch-media → update-db chain was previously a bare separator + button buried after Sync database to ROMs. It is now a prominent "Step 1 — Full metadata refresh" LabelFrame at the top of the tab with a description of what it does, so the common "refresh everything" workflow is the first thing a user sees.
- **GUI — Backup & Restore — target folder + components merged into Step 1** — the shared target folder and component checkboxes were previously floating bare rows above the LabelFrames. They are now inside a "Step 1 — Target folder & components" LabelFrame. "List backups" is now a button inside Step 2 (Create backup) rather than its own thin LabelFrame.
- **GUI — Migrate — Step 5 "Update RocketLauncher after migration" added** — a new LabelFrame at the bottom of the Migrate tab surfaces **Run generate-config** directly so users don't have to switch tabs after a migration. The description explains that only `Rom_Path=` changes — `Default_Emulator`, `Emu_Path`, `Module`, and all other emulator assignments are preserved. The previous hint (which appeared in the Step 2 backup section and was easy to miss after scrolling down to run the migration) has been removed. The button calls the same `_run_generate_config()` used in the Metadata & Media tab and respects the global Apply checkbox.
- **GUI — Migrate — target root + components + options merged into Step 3** — previously three separate LabelFrames (Target root bare row, Components, Options). Now a single "Step 3 — Migration settings" LabelFrame containing all three, numbered Step 3 to place it after the "Step 2 — Backup before migrating" safety step.
- **GUI — Tools — "Install wheel helpers" renamed to "Install .bat helpers (optional)"** — clearer label indicating the section is optional and installs .bat files specifically.
- **`docs/gui.md` — tab tour rewritten to match new tab order and step numbering** — all 12 tab sections appear in the new order; per-tab descriptions updated to reference numbered steps; "Custom Command" moved before "Logs"; tab tour intro paragraph updated.
- **`docs/workflows.md` — stale tab names corrected** — "Diagnose tab" → "Diagnostics tab" (three occurrences); "Wheels tab" → "Tools tab" with updated description reflecting that `fav add / remove / list` is now accessible directly from the Tools tab (Step 3).
- **`docs/standalone-tools.md` — "Wheels tab" reference corrected to "Tools tab"** — also updated to mention "Step 1 — Refresh custom wheels" for clarity.
- **`docs/troubleshooting.md` — "Main Menu tab" heading corrected to "Systems tab"** — the Main Menu treeview lives inside the Systems tab.
- **`ledblinky.py` — clarified `sync-players` skip-comment in `sync_player_colors`** — added an inline comment explaining that the `continue` on an already-present key is the intended idempotent path, and a note confirming the underscore in the key suffix is always present by regex construction.

### Fixed

- **`generate-config` — per-system `Emulators.ini` files are now updated in-place: only `Rom_Path=` changes** — `generate_rl_system_ini` previously replaced the entire file with a generated template. This had two fatal effects after a ROM drive migration: (1) `Default_Emulator` was overwritten with SpinDoctor's fallback guess (`RetroArch`) for any system not in its built-in map — cabinets with SSF for Sega Saturn, Mednafen for TurboGrafx-16, NullDC/Demul for Dreamcast, ZiNc, etc. all broke silently; (2) a bare `[<Emulator>]` section without `Emu_Path=` was injected into the per-system file, which caused RocketLauncher to stop its emulator-path lookup at that file instead of falling back to `Global Emulators.ini`. Both issues produced the same error for every game on every console: *"Could not find an Emu_path for RetroArch in either of these two files: Settings\<System>\Emulators.ini / Settings\Global Emulators.ini"*. The fix: for existing files, a regex replaces every `Rom_Path=` line in-place; `Default_Emulator`, `Emu_Path`, `Module`, `Pause_Save_State_Keys`, and all other keys are preserved verbatim.
- **`generate-config` — `Global Emulators.ini` now uses `Emu_Path` / `Rom_Extension` (the keys RocketLauncher actually reads)** — `generate_global_emulators_ini` previously wrote `Emulator_Application_Path=` and `Emulator_Extension=`, which RocketLauncher does not recognise. Any `Global Emulators.ini` created by SpinDoctor (when the file was absent) was effectively unreadable by RL. The correct keys — confirmed from the real cabinet `Global Emulators.ini` — are `Emu_Path=` and `Rom_Extension=`.
- **`generate-config` — `re.error: bad escape \U` crash on Windows paths fixed** — `_update_rom_path_in_ini` passed the replacement string `f"Rom_Path={new_rom_path}"` directly to `re.subn`. Python's regex engine processes replacement strings for backreference escapes; on Windows, paths containing `\U`, `\N`, or `\A` (e.g. `C:\Users\...`) were misread as invalid regex escapes and raised `re.error: bad escape \U at position 11`. The fix uses a callable replacement (`lambda m: replacement`) which bypasses that processing entirely. The cabinet runs Windows 7 — this crashed `generate-config --apply` for any ROM path under `C:\Users\` or similar.
- **`_errors.py` — OS error messages now show the full file path, not just the filename** — `humanize_oserror` was calling `_basename()` on `exc.filename`, so permission-denied and file-in-use errors only showed the bare filename (e.g. `A Visual Commpendium.xml`) with no folder context. When databases or ROMs are spread across dozens of system subfolders that is useless. All error messages now include the full path from `exc.filename`. Regression test added.
- **GUI — Backup & Restore — Scan no longer pops a spurious console window on Windows** — `_scan_backup_folders` called `subprocess.run` without `CREATE_NO_WINDOW`, causing a brief black terminal to flash on screen. The `creationflags=_CREATE_NO_WINDOW` flag (already defined at module level for this purpose) is now applied to both the `backup list --json` and `backup sidecar list --json` calls.
- **GUI — Backup & Restore — restore combobox no longer pre-fills with the backup root** — the "Backup folder" combobox in Step 3 was initialised with the `backup_dir` config value (e.g. `J:\spindoctor\backups`), which is the root holding all backup *subfolders*, not a specific backup. Clicking "Show backup info" or "Compare to live" on that root path produced *"No manifest at …/manifest.json — Not a spindoctor backup?"*. The combobox now starts empty; use **Scan** to populate it with valid backup subfolders from the target set in Step 1, or **Browse…** to pick one manually.
- **`backup` — partial cleanup now applies to all mid-copy failures, not just Ctrl+C** — the in-flight component sweep and partial-manifest write on interrupted backups previously only ran on `KeyboardInterrupt`. Other failures mid-copy (e.g. full disk, permission error) would leave a half-written component behind with no manifest. Broadened the handler to `BaseException` so cleanup and partial-manifest persistence run for any failure.
- **`favorites.py` — encoding fallback now emits a `RuntimeWarning`** — `_read_text_robust()` silently mangled data when all four encoding probes failed and it fell through to UTF-8 byte replacement. It now warns with the file path and a description so encoding issues are visible in logs.
- **`database.py` — atomic write cleanup correctly tracks fd/tmp state** — after `os.close(fd)` the fd variable is reset to `-1` and after `os.replace()` the tmp variable is set to `None`, so the exception cleanup path cannot double-close the descriptor or attempt to unlink an already-renamed temp file.
- **`mainmenu.py` — `index_of()` `KeyError` raises stripped system name** — previously the error was raised with the original (possibly whitespace-padded) input; it now strips whitespace to match what the lookup actually compared.

### Added

- **`ledblinky patch-settings --ss-lwa` — new option to set the screen saver animation** — `Settings.ini` has two separate FE animation keys: `FELWAFile` (active browsing) and `FEScreenSaverLWAFile` (screen saver). Only `FELWAFile` was previously patchable via SpinDoctor. The new `--ss-lwa` option patches `FEScreenSaverLWAFile` in the same pass. Pass a `.lwa` filename to set the animation, `""` to silence it, or omit to leave unchanged. Both the CLI and GUI one-time setup (Step 2 — Settings.ini) have been updated with the new field. GUI label for the existing FE field updated from "FE idle animation" to "FE active animation" to match LedBlinky's own terminology.
- **GUI — Settings.ini animation comboboxes now pre-populate from current Settings.ini values** — previously all three animation dropdowns (FE active, screen saver, in-game) always opened showing default placeholder values (`<Random>` / blank) regardless of what was actually set in `Settings.ini`. They now read the current values from `Settings.ini` on load and on every **Refresh list** click, so the GUI accurately reflects the current configuration. New `read_ledblinky_settings_keys` function added to `ledblinky.py`.
- **`docs/commands.md` — `pc-rename` now has its own dedicated section** — the command was previously documented only as a companion note inside the `add-pc-system` section. It now has a standalone `### pc-rename` entry under Library generation covering dry-run vs `--apply`, `--no-interactive`, and `--undo`.
- **`docs/commands.md` — new `## Config` section documenting all `config` subcommands** — `config init`, `config set`, `config show`, and `config verify-credentials` (with all credential override flags and JSON output mode) are now documented with examples. Previously `verify-credentials` had no dedicated reference entry.
- **`docs/cli-cheatsheet.md` — `pc-rename` and `config verify-credentials` added** — `pc-rename` added to Edit & curate section; `verify-credentials` added to the Config section with credential-override examples.
- **`docs/cli-cheatsheet.md` — Custom Command preset count corrected** — two references to "~70 presets" updated to "~246 presets" to match the 2.4.22 expansion.
- **`docs/configuration.md` — GUI preferences section updated** — `gui_window_maximized` (bool) added; `gui_last_active_tab` and `gui_curate_regions` descriptions updated to use current tab names (Maintenance instead of Curate).
- **`README.md` — GUI section updated for current tab structure** — "15 dedicated tabs" corrected to 12; tab list updated to use current names (Diagnostics, Maintenance, Tools, Systems) replacing the old separate Audit & Doctor / Diagnose / Curate / Wheels / Main Menu entries; Custom Command dropdown count corrected from ~70 to ~246.
- **`docs/gui.md` — tab tour restructured to match current GUI** — "Audit & Doctor" and "Diagnose" sections merged into a single "Diagnostics" section; "Curate" renamed to "Maintenance"; standalone "Wheels" and "Main Menu" sections removed and their content integrated into the "Tools" and "Systems" sections respectively.

---

## [2.4.23] - 2026-06-09

### Fixed

- **`ledblinky patch-settings --verbose` — output no longer repeats per key** — the verbose block was inside the `for change in result.changes:` loop, causing it to print the full summary once per patched key instead of once total. Moved outside the loop.
- **`Colors.ini` casing standardised throughout codebase** — `generate_for_roms`, `sync_player_colors`, and two helper functions were opening `"colors.ini"` (lowercase) while every other function and all tests used `"Colors.ini"` (capital C — LedBlinky's own filename). On Windows the case-insensitive filesystem hid the mismatch; on Linux CI it produced `FileNotFoundError` in every `sync_player_colors` test. Fixed by introducing named constants `COLORS_INI_NAME = "Colors.ini"` and `CONTROLS_INI_NAME = "controls.ini"` in `ledblinky.py` (matching the existing `CONTROLS_XML_NAME` and `COLOR_RGB_NAME` pattern) and replacing all inline string literals with those constants. `health.py` also updated to use the constants. Two regression tests added: `test_filename_constants_exact_casing` asserts the exact spelling of all four filename constants; `test_no_bare_colors_ini_string_in_module` scans the module source to reject any future bare `"colors.ini"` string literal. Architecture reference updated with a dedicated "Filename casing" section documenting the rule and its history.

### Added

- **`ledblinky colors sync-players` — new command to mirror P1 colors to all additional players** — `ledblinky generate` writes `Colors.ini` sections with P1 keys only. When a game has multiple players (P2, P3, P4, …), those buttons had no color entry and fell back to the XML default color rather than the game-specific palette. The new `sync-players` command closes that gap for **any number of players**: for every ROM that has both a `Colors.ini` section and a `controls.ini` entry, it reads `controls.ini` to discover all P{n≥2} keys, then adds any missing entries to `Colors.ini` by mirroring the matching P1 color (e.g. `P3_BUTTON1` gets the same color as `P1_BUTTON1`). Keys already present in `Colors.ini` are never overwritten unless `--override` is passed. Run after `generate` and `colors normalize`: `spindoctor ledblinky colors sync-players --apply`.
- **`ledblinky colors sync-players --override`** — new flag that replaces existing P2/P3/P4+ color entries with the current P1-mirrored color. Without this flag, existing entries are always preserved. P1 keys are never affected regardless of `--override`.
- **`ledblinky setup` — new one-step MAME setup command** — chains `generate` (writes `controls.ini` + `Colors.ini` from MAME listxml) then `sync-players` (mirrors P1 colors to P2/P3/P4+ for all multi-player ROMs) in a single invocation. Run once after initial setup and again whenever you add new MAME ROMs. Accepts `--overwrite`, `--apply`, `--no-backup`, and `--verbose`.
- **GUI — LEDBlinky tab fully renumbered and reordered into a 9-step user journey** — sections are now labeled Step 1 through Step 9 in the recommended workflow order: **Step 1 — Overlay Hook Fix** (one-time) → **Step 2 — Settings.ini** (one-time) → **Step 3 — MAME: Generate, Normalize & Sync Players** → **Step 4 — Fill Default Colors** (any console) → **Step 5 — Randomize Entry Colors** → **Step 6 — Admin Button Colors** → **Step 7 — Brightness** → **Step 8 — Color Definitions** → **Step 9 — Backup / Restore**. One-time setup steps are promoted to the top so first-time users see them before any color-data steps.
- **GUI — "Run Full MAME Setup (3a + 3c)" chain button in Step 3** — single-click button that runs `ledblinky setup` (generate + sync-players) with the current Apply and Verbose flags. Eliminates the need to click Generate, Normalize (if needed), and Sync Players individually for a fresh MAME import.
- **GUI — Inspect ROM inline field in Step 3** — text field + Inspect button in the MAME section; enter a ROM name and click Inspect to run `ledblinky inspect-rom <ROM>` directly from the tab without switching to the Custom Command tab.
- **GUI — Step 6 (Admin Button Colors) dependency note** — the section description now reminds users to run Admin Colors after Step 5 (Randomize), since Randomize overwrites all button colors including admin buttons.
- **GUI — "1c. Sync player colors" button in LEDBlinky Step 3** — added alongside the existing Generate and Normalize buttons; runs `ledblinky colors sync-players` with the global Apply and Verbose flags. To use `--override`, use the Custom Command preset `ledblinky colors sync-players --apply --override`.
- **GUI — LEDBlinky tab Step 3 / Step 4 restructured for clarity** — Step 3 is now explicitly "MAME: Generate, Normalize & Sync Players" with the system selector removed (these three commands are all MAME-only and do not need a per-system choice). Step 4 is now "Fill Default Colors (any console)" with the Console selector promoted to the top of the form so it reads as the scope control. The hint text in Step 3 correctly notes that 3b (Normalize) is for legacy Colors.ini files only and is not required after a fresh Generate.

---

## [2.4.22] - 2026-06-09

### Changed

- **GUI Custom Command preset dropdown reorganised with section headers and alphabetical ordering** — entries are now grouped under 19 named sections (`─── Health & Discovery ───`, `─── Reports & Stats ───`, `─── Audit & Inspect ───`, `─── Curate & Cleanup ───`, `─── Metadata & Media ───`, `─── Database ───`, `─── Wheels ───`, `─── Main Menu ───`, `─── Generate & Organize ───`, `─── Add & Bootstrap ───`, `─── Rename & Clone ───`, `─── LEDBlinky ───`, `─── Lightgun ───`, `─── Emulator Titles ───`, `─── Backup & Migration ───`, `─── Scrub & Restore ───`, `─── Themes ───`, `─── Tools ───`, `─── Config ───`). Commands within each section are sorted alphabetically. Selecting a section header auto-advances the Combobox to the first real command in that section; clicking Run while a header is selected flashes a validation hint instead of shelling out.
- **GUI Custom Command presets expanded to ~246 entries** — every CLI command now has flag variants in the Custom Command dropdown. New coverage across all command groups: health/discovery (`doctor`, `self-doctor`, `tools-audit`), reports (`stats`, `preview`), audit (`find-dupes --by-content`, `find-misplaced --apply`, per-system variants), curate (`--regions`, `--action delete`), metadata/media (`fetch-meta --all-games`, `--no-cache`, per-source variants; `fetch-media --types`, `--overwrite`; `media-scan --action move`), database (`update-db --add-missing`, `--remove-orphans`; full `batch-edit` suite), wheels (`fav add/remove/sync`; `stats-report` top/export), generate/organize (full flag set), add/bootstrap/rename/clone (dry-run + apply pairs), lightgun (`configure --system`), emulator-title (`list/set/remove`), scrub/restore (`scrub --stats/--favorites`, `scrub-restore`), backup (`migrate --keep-source`), themes (unchanged), tools (`install-tools --apply`, `uninstall-tools`), diff (all four components), config (`hyperspin_dir`, `rocketlauncher_dir`, `ledblinky_dir`, `verify-credentials`).

### Fixed

- **`ledblinky generate` — `controls.ini` now written in correct LedBlinky key format** — `generate` previously wrote `controls.ini` entries using SpinDoctor-internal metadata keys (`P1_NUMBUTTONS=1`, `P1_CONTROLS=JOYSTICK_8WAY,BUTTON1`). LedBlinky treats every unrecognised key as a literal control identifier, so those keys were silently replacing the real button names in the control list at game launch — causing player action buttons to appear completely dark (not lit even when pressed) while Coin and Start buttons continued to work. `generate` now writes LedBlinky's runtime key names instead (`P1_BUTTON1=1`, `P1_JOYSTICK=1`, `P1_START=1`, `P1_COIN=1`), matching the same naming convention already used in `Colors.ini`. If you have an existing `controls.ini` generated by SpinDoctor 2.4.21 or earlier, regenerate it: `spindoctor ledblinky generate --overwrite --apply`.
- **`ledblinky patch-settings` — `--fe-lwa` / `--game-lwa` values no longer include a spurious `lwa\` prefix** — the animation file picker (`list_lwa_files`) was returning paths relative to `ledblinky_dir` (e.g. `lwa\Slow Fade.lwax`), but LedBlinky itself always prepends `lwa\` when resolving `FELWAFile` and `GamePlayLWAFile` in `Settings.ini`, producing a double-prefix path (`lwa\lwa\Slow Fade.lwax`) and a "Missing FE Active animation file" error at runtime. The picker now returns paths relative to the `lwa\` subdirectory (e.g. `Slow Fade.lwax`), matching what LedBlinky expects.

---

## [2.4.21] - 2026-06-07

### Added

- **GUI — LEDBlinky tab fully reorganized into a step-by-step workflow** — sections are now labeled Step 1 through Step 6 and ordered logically: **Step 1 — Generate & Normalize** (MAME import) → **Step 2 — Fill Default Colors** (console/other gaps) → **Step 3 — Randomize Entry Colors** → **Step 4 — Admin Button Colors** → **Step 5 — Brightness** → **Step 6 — Settings.ini** → **Overlay Hook Fix** (one-time setup) → **Color Definitions** (advanced palette editing) → **Backup / Restore**. Previously Brightness appeared before Randomize and Admin Buttons, Overlay Hook buttons were mixed into the Generate area, and Color Definitions came after Backup.

- **GUI — "Normalize Colors.ini" button added to the Generate section** — the button previously existed only in the Color Definitions section at the bottom of the LEDBlinky tab. It is now also in the top button row (Generate → **Normalize Colors.ini** → Audit coverage → …) so the step is immediately visible after generating. The section description now explains the four-step workflow: Generate → Normalize → Fill Defaults → Randomize. The tip text also explains that "Check overlay hooks" / "Fix overlay hooks" always write in-place.

- **`ledblinky colors normalize --verbose`** — new `--verbose` flag that prints per-section conversion detail: for each section converted, lists every key mapping applied (`ledcolor1=FF0000 → P1_BUTTON1=Red`, `joystick=FFFFFF → P1_JOYSTICK=White`, etc.). First 50 sections are shown; a summary count follows if there are more.

### Fixed

- **`ledblinky fix` / `batch-edit` / `rename` / `clone` — wrong output path when `output_dir` is configured** — these commands were calling `config.effective_output_dir()`, which falls back to the global `output_dir` config setting when no explicit `--output-dir` flag is given. If `output_dir` was set (e.g. `J:\spindoctor\output`), files were written there instead of in-place. All four commands now use the explicit `--output-dir` value only, never falling back to `config.output_dir`.

- **`ledblinky fix` — "not found" Settings.ini shown as an error** — now shows "✓ no Settings.ini → no hooks to remove" to clarify this is expected and non-fatal.

- **`ledblinky inspect-rom <ROM>` — new diagnostic command** — reads Colors.ini, controls.ini, `LEDBlinkyControls.xml`, and MAME listxml for a given ROM and reports everything LEDBlinky would see when the game launches: whether each file has an entry, what keys are present, whether the XML has a per-game entry (vs DEFAULT fallback), the path to `LEDBlinkyLog.txt`, and guided next-steps for the most common failure modes (missing Colors.ini section, DEFAULT XML fallback, name mismatch). When `output_dir` is configured the full report is also saved to `<output_dir>/diagnostics/inspect-rom-<ROM>-<timestamp>.txt`. The LEDBlinky log section clearly labels `LEDBlinkyLog.txt` as written by LEDBlinky itself (not SpinDoctor). Run this first when game colors are showing white despite Colors.ini having correct entries.

- **`ledblinky generate` — Colors.ini now written in native `P1_BUTTON1=` format** — `generate` previously wrote `Colors.ini` entries in SpinDoctor's internal hex format (`ledcolor1=FF0000`, `joystick=FFFFFF`), which **LedBlinky itself cannot read**. LedBlinky requires the named format (`P1_BUTTON1=Red`, `P1_JOYSTICK=White`). This was why every game showed White after running `generate` — LedBlinky was falling back to its default color because it couldn't parse the entries. `generate` now loads `Color-RGB.ini` at generation time and converts each hex value to the nearest named color, writing native format directly. The separate `normalize` step is no longer required after `generate` (though it remains useful for existing old-format files). If `Color-RGB.ini` is missing, `generate` falls back to the old hex format and warns the user to run `normalize` after.

- **`ledblinky colors randomize` — skipped MAME sections now identified as old-format, not silently dropped** — existing `Colors.ini` files in the legacy hex format (`ledcolor1=FF0000`, `joystick=FFFFFF`, etc.) cannot be reached by `randomize` because it only matches `P*_BUTTON*` / `P*_JOYSTICK` keys. Previously these appeared as "no player keys — left unchanged" with no explanation. Now they are counted separately as "old format" and the output prints an actionable yellow warning: *Run `colors normalize --apply` first, then re-run randomize.* After running normalize, all legacy sections will be converted and randomize will cover them.

### Changed

- **GUI — "Fix INI issues" button renamed to "Fix overlay hooks"** — more accurately describes what the command does. The paired "Check existing INIs" button is also renamed to "Check overlay hooks".

- **`ledblinky fix` — improved CLI docstring and output** — explicitly states it writes in-place to `ledblinky_dir` / `hyperspin_dir` (not `output_dir`).

- **`ledblinky colors randomize --verbose`** — now shows per-section color assignments (first 50 sections) and breaks down skips into `skipped_old_fmt` vs `skipped_empty`.

- **`ledblinky colors brightness --verbose`** — now shows per-color before→after with R,G,B and hex.

- **`ledblinky patch-settings --verbose`** — now prints each key changed with old→new values.

---

## [2.4.20] - 2026-06-07

### Added

- **`rename` / `clone` — `--verbose` flag** — after `--apply` completes, prints every file path moved or copied (ROM, all media types, DB entry) so you can confirm exactly what changed on disk.

- **`backup sidecar` — new subcommand group** — `backup sidecar list <FILE>` lists the timestamped `.YYYYMMDD_HHMMSS.bak` siblings SpinDoctor writes next to each modified file. `backup sidecar restore <FILE> --from <SIDECAR> --apply` restores the file from a chosen sidecar (backing up the current live file first so the restore itself is undoable). Documented in `commands.md` and `cli-cheatsheet.md`.

### Fixed

- **`ledblinky fix` — backups now route to `config.backup_dir`** — the `apply_fix()` function backed up `LEDBlinkyControls.xml` and per-menu `Settings.ini` using `shutil.copy2` directly next to the source file, ignoring the configured `backup_dir`. Fixed to use the same `_backup(path, _config_backup_dir(config))` call used by every other LEDBlinky command.

- **`batch-edit` / `rename` / `clone` — DB backups now route to `config.backup_dir`** — `apply_batch_edit` and the rename/clone apply path called `db.save(tmp_dir=_tmp)` without passing `backup_dir`, so the `.bak` database backup landed next to the live XML. Both paths now pass `backup_dir=Path(config.backup_dir)` consistent with `update-db` and `fetch-meta`.

- **`ledblinky fill-defaults --verbose` — now emits per-ROM detail** — the previous verbose output was identical to the non-verbose summary (just counts). Now prints each ROM name added (`+ romname`) and each ROM name overridden (`~ romname`), plus the mixed-skipped count.

- **`ledblinky admin-buttons set --verbose` — now emits per-section detail** — previously printed only the total section count. Now prints each section name updated (`~ romname`).

- **`cli-cheatsheet.md` — corrected seven broken examples**:
  - `doctor --verbose` removed (flag does not exist on `doctor`).
  - `verify --report` removed (flag does not exist on `verify`; only `audit` has `--report`).
  - `find-global zelda --fuzzy` → `find-global zelda --limit 20` (`--fuzzy` does not exist).
  - `rename` / `clone` corrected from positional syntax to named options (`--system`, `--game`, `--to`).
  - `curate --revision newest` → `curate --prefer-revision latest` (correct flag name and value).
  - `ignore add/remove --rom` → positional argument (`spindoctor ignore add "rom" --system MAME`).
  - `migrate --move` → `migrate --keep-source` (default is already a move; `--keep-source` is the copy flag).

- **Global Apply / Verbose checkboxes in status bar** — the per-tab Apply checkboxes that previously lived inside individual tab sections have been consolidated into two persistent controls at the very bottom of the GUI window, always visible regardless of which tab is active. **Apply** gates whether commands write to disk (unchecked = dry-run, the safe default). **Verbose** passes `--verbose` to every command that supports it, printing file paths written, per-item counts (added / overridden / skipped), and key→value detail.

- **`--verbose` flag added to**: `ledblinky generate` (prints controls + colors paths), `ledblinky patch-settings` (prints each key patched + file path), `ledblinky colors brightness` (prints Color-RGB.ini path + color count), `ledblinky fill-defaults` (prints Colors.ini path + added/overridden/skipped counts), `ledblinky admin-buttons set` (prints Colors.ini path + sections updated), `ledblinky colors randomize` (prints Colors.ini path + palette size + sections updated), `migrate` (prints each file/folder as it moves), `lightgun detect` (prints install paths + system counts), `lightgun configure` (prints INI path + Pre/Post launch hook values). `backup create` and `backup restore` already had `--verbose`; all others now consistently support it.

- **`ledblinky colors randomize` — new CLI command** — assigns each game in `Colors.ini` its own independent random button color. All `P*_BUTTON*` / `P*_JOYSTICK` keys in a section get one randomly chosen color; all `P*_COIN` / `P*_START` keys get a second independently drawn color. Only **existing** keys are updated — buttons intentionally absent from a section (dark) are never touched. Pure-black / off colors are excluded from the draw. Supports `--seed N` for reproducible runs. Auto-backup before write. `randomize_entry_colors()` + `_randomize_section_body()` + `RandomizeColorsResult` added to `ledblinky.py`. GUI: new **Randomize Entry Colors** panel in the LEDBlinky tab with optional seed field.

### Changed

- **CI — `actions/checkout` bumped from 6.0.2 → 6.0.3** — patch update across `ci.yml`, `release.yml`, and `security.yml`. Fixes SHA-256 repository checkout init; no user-facing impact.

---

## [2.4.19] - 2026-05-28

### Added

- **`ledblinky fill-defaults --override-uniform`** — new flag that also updates existing `Colors.ini` sections where **every** button color is identical. If any button in a section has a different color, that section is left completely untouched (so hand-crafted mixed-color entries are always safe). Reports separate counts for entries added (new ROMs), overridden (uniform), and skipped (mixed).

- **`ledblinky fill-defaults --no-add-keys`** — companion to `--override-uniform`. When set, only the *values* of already-present `P*_BUTTON/JOYSTICK/START/COIN` keys are replaced; no new button keys are inserted. Use when a section intentionally has fewer buttons than the `--buttons` count (e.g. a 3-button game entry) and you don't want it extended.

- **`ledblinky fill-defaults` — multi-player support (`--players 1-4`)** — generates `P1`…`P{N}` button blocks for every new entry. All players are mirrored to the same color. A 2-player, 8-button-per-side cabinet: `fill-defaults --players 2 --buttons 8 --apply`. `n_players` param added to `fill_default_colors()`.

- **`ledblinky fill-defaults` — admin/cabinet button block (`--admin-buttons N --admin-color COLOR`)** — appends an extra `P{players+1}` block (e.g. P3 for a 2-player cabinet) using a separate color for cabinet-level buttons (Select, Exit, Search, Pause, etc.). Admin block gets `P{n}_BUTTON1…N`, `P{n}_COIN`, `P{n}_START`. `admin_buttons` + `admin_color` params added to `fill_default_colors()`.

- **`ledblinky fill-defaults` — synthetic wheels included by default** — Favorites, Recently Played, and Most Played are no longer excluded from the scan. ROMs in those wheels whose name already appears in a real-system `Colors.ini` entry are automatically covered (Colors.ini is keyed by ROM name, not system). ROMs that only exist in synthetic wheels now receive a default entry.

- **`ledblinky colors brightness` — new CLI command** — sets all `Color-RGB.ini` R,G,B intensities to a uniform brightness level. Each color's dominant channel is normalized to 48 first, then scaled by the target percentage. `--scale 100` = maximum brightness (all dim colors boosted to full); `--scale 50` = half brightness; `--scale 10` = night mode; `--scale 0` = all off. This ensures every button (P1, P2, admin, Start) is at the same brightness regardless of prior stored values. Auto-backup before write. `scale_colors_brightness()` + `_normalize_scale_entry()` + `BrightnessResult` added to `ledblinky.py`.

- **`ledblinky admin-buttons set` — per-button admin/cabinet color override** — walks **every** section in `Colors.ini` and updates or inserts `P{player}_BUTTON*` keys with individual per-button colors. Complements `fill-defaults --admin-buttons` (which only touches new ROM entries) by ensuring all existing entries also carry the correct admin button colors. Supports `--player N` (1–6, default 3), `--colors "C1,C2,..."` (per-button), `--color C --count N` (uniform), `--apply`, `--no-backup`. `patch_admin_button_colors()` + `AdminButtonPatchResult` + `_patch_admin_buttons_in_text()` added to `ledblinky.py`.

- **GUI — Fill Default Colors: Players spinner and Admin Buttons row** — "Players (1-4)" Spinbox generates P1–P4 blocks. "Admin buttons" Spinbox (0=disabled) + separate color dropdown for the admin block. Both color dropdowns auto-refresh when Color-RGB.ini changes.

- **GUI — Brightness section (LEDBlinky tab)** — slider (0–100 %), Apply checkbox, and **Scale Brightness** button. Equivalent to `spindoctor ledblinky colors brightness`.

- **GUI — Admin Button Colors section (LEDBlinky tab)** — player-slot Spinbox (1–6), button-count Spinbox (1–8), eight per-button color dropdowns (BUTTON1–BUTTON8, all populated from `Color-RGB.ini`), **Refresh colors** button (reloads palette from `Color-RGB.ini`), Apply checkbox, and **Set Admin Button Colors** button. Only the first `button count` dropdowns are sent. Equivalent to `spindoctor ledblinky admin-buttons set`.

- **GUI — "Refresh colors" button added to Fill Default Colors and Admin Button Colors sections** — both sections previously relied on the Color Definitions "Refresh list" button (at the bottom of the tab) to load the `Color-RGB.ini` palette into their color dropdowns. Each section now has its own **Refresh colors** button so the palette can be reloaded without scrolling.

### Fixed

- **`get_systems()` — `AttributeError` when `databases_dir` is a string** — the function called `.exists()` directly on `config.databases_dir` which is a `Path` on the real `Config` but a plain `str` in test and SimpleNamespace configs. Changed to `Path(config.databases_dir)` (consistent with the `roms_dir` handling on the line above).

- **LEDBlinky auto-backups now respect `config.backup_dir`** — the `_backup()` helper in `ledblinky.py` previously always wrote `.bak` files next to the source file, ignoring the `backup_dir` setting. Now when `backup_dir` is configured, all auto-backups (fill-defaults, patch-settings, normalize, colors edit, brightness, admin-buttons set) are written to `backup_dir/LEDBlinky/<filename>.<stamp>.bak`. The subdirectory is created automatically.

- **HyperSpin database backups now use `backup_dir/HyperSpin/` subfolder** — `HyperspinDatabase.save()` previously placed backups in `backup_dir/<system-name>/` (e.g. `backup_dir/MAME/`). Changed to the tab-consistent `backup_dir/HyperSpin/` subfolder so all HyperSpin database backups (from update-db, batch-edit, fav/recent/stats rebuild) land in one predictable location.

- **RocketLauncher INI backups now respect `config.backup_dir`** — `generate-config`'s internal `_backup_if_exists()` closure always wrote `.bak` siblings next to source INI files, ignoring `backup_dir`. Now routes to `backup_dir/RocketLauncher/<filename>.<stamp>.bak` when configured.

### Changed

- **`ledblinky colors brightness` — behavior changed from relative-scale to normalize-to-max** — the previous implementation multiplied each channel by `scale_pct/100`, which preserved existing brightness differences between colors (a dim color stored at intensity 20 would stay at 20 after a 100% run). The new implementation normalizes each color's dominant channel to 48 first, then scales — so 100% always produces the maximum possible intensity for every color regardless of what was previously stored. The practical effect: running at 100% guarantees all buttons (P1, P2, admin, Start) are at identical LED output levels; running at 50% halves that uniformly. Pure-black (0,0,0) entries are left untouched. 20 new unit tests cover the normalization math and integration paths.

- **Docs** — `commands.md` fill-defaults table updated (new flags, synthetic-wheel note, recommended 2-player workflow); new `colors brightness` and `admin-buttons set` subsections. `cli-cheatsheet.md` updated with multi-player, brightness, and admin-buttons examples. `gui.md` Fill Default Colors section rewritten; Brightness and Admin Button Colors sections added; Refresh colors notes added. `cabinet-architecture-reference.md` adds multi-player key naming table, admin block convention, per-button override, normalize-to-max brightness model, and unified backup routing table.

---

## [2.4.18] - 2026-05-28

### Fixed

- **`ledblinky fill-defaults` — `TypeError: 'method' object is not iterable`** — `fill_default_colors()` iterated `db.games` (the method object) instead of calling `db.games()`. Every other call site in the codebase uses `db.games()` correctly; this was the only exception. The crash made `fill-defaults` completely unusable on any real cabinet config.

- **`ledblinky colors normalize` — `NameError: name 'lb' is not defined`** — `ledblinky_colors_normalize` in `cli.py` called `lb.normalize_colors_ini(...)` without first importing the module locally (`from . import ledblinky as lb`). Every sibling command (`patch-settings`, `colors edit`, `fill-defaults`) had the import; `normalize` was the only one missing it. The command crashed immediately on every invocation.

- **LEDBlinky animation dropdowns empty — `.lwax` files not found** — `list_lwa_files()` only searched for `*.lwa` files. LedBlinky's current animation format is `.lwax` (extended); the older `*.lwa` format is rarely used in practice. Changed to match both extensions so the FE idle animation and In-game unused buttons pickers populate correctly when the LedBlinky `lwa/` directory contains `.lwax` files.

- **`fill_default_colors` — duplicate `Colors.ini` sections when a ROM name appears in multiple system databases** — `existing_sections` was populated once from the on-disk `Colors.ini` but never updated as new entries were accumulated. A ROM name present in two system XMLs (e.g. the same game in both a `MAME` and an `Arcade` database) was emitted twice, producing duplicate `[rom_name]` sections. LedBlinky reads only the first; the second was dead weight and confused subsequent `normalize` / `colors edit` passes. Fix: mark each ROM name in `existing_sections` immediately after queuing its entry.

- **`write_color_rgb_ini` — `\r\r\n` line endings on Windows corrupted `Color-RGB.ini`** — The function joined lines with `"\r\n"` then called `path.write_text(..., encoding="utf-8")` in Python's default text mode. On Windows, text mode translates every `\n` → `\r\n`, so each `\r\n` separator became `\r\r\n`. LedBlinky failed to parse the resulting file or showed garbled color names. Fix: pass `newline=""` to `write_text` to suppress the translation.

---

## [2.4.17] - 2026-05-28

### Changed

- **LEDBlinky tab — Settings.ini Patch — in-game unused buttons** — replaced the "Turn off unused buttons during gameplay" checkbox with an **In-game unused buttons** animation picker (combobox, same style as FE idle animation). Leave blank to silence unused buttons (the recommended default, same as before); select any `.lwa` file to play that animation on all unmapped buttons during gameplay. The same **Refresh list** button populates both animation pickers. `GamePlayLWAFile` is always written explicitly so the setting is never left at LedBlinky's default `<Random>`.

- **Docs** — `commands.md`, `cli-cheatsheet.md`, `gui.md`, and `cabinet-architecture-reference.md` updated: `GamePlayLWAFile` table entry now documents the animation-file option; cheatsheet adds `--game-lwa` example; architecture reference clarifies that `.lwa` files live under `lwa/` subdirectories and that `GamePlayLWAFile` is global (no per-system override).

---

## [2.4.16] - 2026-05-28

### Added

- **`spindoctor ledblinky colors normalize`** — converts SpinDoctor-generated hex-format `Colors.ini` entries to LedBlinky's native named format. `ledcolor1=FF0000` → `P1_BUTTON1=Red`, `joystick=FFFFFF` → `P1_JOYSTICK=White`, etc. Each hex value is matched to the nearest entry in `Color-RGB.ini` using Euclidean distance in RGB space (exact matches are found immediately; custom colors fall back to nearest neighbour). Sections already in named format are untouched. Run before `colors edit` so renames reach every section. Dry-run by default; `--apply` commits; `--no-backup` skips the `.bak` copy. `normalize_colors_ini()` + `NormalizeResult` + `_is_hex_color()` + `_nearest_color_name()` + `_LEDCOLOR_RE` + `_LEGACY_KEY_MAP` added to `ledblinky.py`.

- **`spindoctor ledblinky colors list / edit`** — manage named color definitions in `Color-RGB.ini`. `list` shows all entries as a table (name, R/G/B in 0-48 range, #RRGGBB hex). `edit <NAME>` renames a color and/or updates its value (`--hex RRGGBB` converts from standard 8-bit hex to the 0-48 intensity range; `--rgb R,G,B` for native values) and propagates the rename to: (1) `Color-RGB.ini`, (2) every exact-value reference in `Colors.ini`, (3) every `color="<NAME>"` attribute in `LEDBlinkyControls.xml`. Dry-run by default; `--apply` commits; `.bak` backups written for each modified file. `apply_color_rename()` + `parse_color_rgb_ini()` + `write_color_rgb_ini()` + `ColorEntry` + `ColorRenameResult` added to `ledblinky.py`.

- **LEDBlinky tab — Color Definitions section** — Treeview showing all entries from `Color-RGB.ini` (Name, R, G, B, Hex columns). Refresh button populates from `ledblinky_dir`. Click a row to load it into the edit fields; edit the name and/or hex color code (live preview swatch); Apply checkbox + **Update & Rename** button runs the propagation; **Normalize Colors.ini** button converts the whole file from hex format to named format in one click. After either action completes successfully the color list (and the Fill Defaults color dropdown) auto-refresh. Equivalent to `spindoctor ledblinky colors edit` / `spindoctor ledblinky colors normalize`.

- **`spindoctor ledblinky patch-settings`** — patches `<ledblinky_dir>/Settings.ini` to fix two common LED annoyances without requiring access to LedBlinky's configuration UI: (1) sets `GamePlayLWAFile=` (empty) in `[GameOptions]` so buttons not used by the current game go dark in-game instead of flashing randomly; (2) optionally sets `FELWAFile` in `[FEOptions]` to a user-supplied `.lwa` animation file (or empty for static colors) instead of the jarring `<Random>` selection. `--fe-lwa`, `--game-lwa`, `--apply`, and `--no-backup` flags. A `.bak` copy of `Settings.ini` is written before any change. `list_lwa_files()` scans `ledblinky_dir` for available animation files. `_patch_ini_keys()` helper preserves line endings, comments, and key ordering exactly.

- **LEDBlinky tab — Settings.ini Patch section** — "FE idle animation" combobox auto-populated from `.lwa` files in `ledblinky_dir` (Refresh button), "Turn off unused buttons during gameplay" checkbox (on by default), Apply checkbox, and **Patch Settings.ini** button. Equivalent to `spindoctor ledblinky patch-settings`.

- **LEDBlinky tab — Backup / Restore section** — Quick backup and restore scoped to the `ledblinky` component only. Both folder fields default to `config.backup_dir`. Dry-run by default. Equivalent to `spindoctor backup create/restore --include ledblinky`.

- **`spindoctor ledblinky fill-defaults`** — adds a default `Colors.ini` entry for every ROM in the HyperSpin databases that has no LED mapping yet. Without an entry LedBlinky treats all buttons as inactive (off); after running `fill-defaults`, unmapped games glow a steady color instead of going dark. Each generated entry uses `P1_BUTTON1`…`P1_BUTTONn`, `P1_JOYSTICK`, `P1_START`, `P1_COIN` in named format. Options: `--color` (default White, validated against `Color-RGB.ini`), `--buttons` (1-8, default 6), `--system` (limit to one system), `--apply`, `--no-backup`. Existing entries are never modified. `fill_default_colors()` + `FillDefaultsResult` added to `ledblinky.py`.

- **`spindoctor ledblinky patch-settings` — only `GamePlayLWAFile` is patched** — the in-game unused-button flash is silenced; the brief flash at game-load start is intentional and left alone.

- **LEDBlinky tab — Fill Default Colors section** — color dropdown (auto-populated from `Color-RGB.ini`; refreshes automatically after **Update & Rename** or **Normalize Colors.ini** completes), button-count Spinbox (1-8), optional system filter (leave blank for all systems), Apply checkbox, and **Fill Default Colors** button. Equivalent to `spindoctor ledblinky fill-defaults`.

- **Docs** — LEDBlinky section added to `cabinet-architecture-reference.md` (key files, `Settings.ini` key anatomy, `LEDBlinkyControls.xml` / Search compatibility). LEDBlinky section added to `cli-cheatsheet.md` (was entirely absent). `commands.md`, `gui.md`, `cli-cheatsheet.md`, and `troubleshooting.md` updated for `patch-settings`, `colors normalize`, `fill-defaults`, new GUI sections (Normalize button, Fill Default Colors, Settings.ini Patch, Backup/Restore), and three new FAQ entries.

### Fixed

- **`ledblinky fill-defaults` / `colors normalize` — `NameError: '_load_config' is not defined`** — both commands accidentally called `_load_config()` instead of the correct `_cfg()` helper, causing an immediate crash on every invocation. All other `ledblinky` commands used `_cfg()` correctly; these two were copied with the wrong name.

- **`ledblinky patch-settings` — FE idle animation dropdown empty** — `list_lwa_files()` only performed a flat `glob("*.lwa")` on `ledblinky_dir`, missing the standard `lwa/` subdirectory (and its nested subdirectories) where LedBlinky ships its animation files. Changed to `rglob("*.lwa")` returning paths relative to `ledblinky_dir` (e.g. `lwa\Slow Fade.lwa`) so dropdown values match exactly what LedBlinky expects in `Settings.ini`.

- **Release zip reduced by ~120 MB** — The `assets/archive/` subfolder (deprecated oversized originals kept for reference) was accidentally bundled into every PyInstaller exe via a recursive `--add-data` on the whole assets directory. The pip package already excluded it (non-recursive glob in `pyproject.toml`); the build script now does the same by adding only top-level asset files.

---

## [2.4.15] - 2026-05-27

### Fixed

- **`Kirby's Adventure (Favorites)` no longer appears in Recently Played / Most Played** — Two gaps in the synthetic-system exclusion logic allowed `system="Favorites"` entries to leak into the rebuilt wheels. (1) The `Global Statistics.ini` fallback parser (`_read_global_statistics_ini`) in both `recent.py` and `playtime.py` only skipped the `Toolkit` pseudo-system; it now also respects the full `exclude_systems` set, so `Favorites` / `Recently Played` / `Most Played` entries are dropped even when the fallback path is active. (2) `get_systems()` returns synthetic wheel names as "known systems" because SpinDoctor creates `Databases/Favorites/` etc. on disk; `rebuild` and `build_most_played_wheel` now strip `SYNTHETIC_SYSTEM_NAMES` from `known` before the source-system filter runs, closing the second path. Galaga played directly from MAME still appears in both wheels — only entries whose recorded system is a synthetic wheel name are excluded.

---

## [2.4.14] - 2026-05-27

### Added

- **`Default.zip` theme fallback for per-game media mirror** — When a game has no per-game `<GameName>.zip` in the source system's Themes folder, SpinDoctor now copies the source system's `Default.zip` (HyperSpin's console-wide fallback theme) as `<GameName>.zip` in the synthetic wheel's Themes folder. This means games like Kirby's Adventure — which rely on the NES console theme rather than a dedicated per-game zip — now display the same themed background and video layout in Favorites / Recently Played / Most Played that they show in their native wheel. The fallback only fires when `Default.zip` exists in the source system's Themes folder and the game has no per-game theme; games with per-game themes are unaffected.

- **Bundled `Wheel Click.mp3` for all three synthetic wheels** — SpinDoctor now ships a wheel-click navigation sound and installs it as `Media\<SystemName>\Sound\Wheel Click.mp3` for `Favorites`, `Most Played`, and `Recently Played` during every `rebuild --apply` (skip-if-exists). HyperSpin plays this file on every left/right cursor move while browsing the game list inside the wheel. `install_system_navigate_sound()` added to `rocketlauncher.py`; `install_bundled_system_assets()` now returns a sixth key `"navigate_sound"`. Rebuild summary shows a `Wheel Click sound:` row. `pyproject.toml` package-data glob updated to include `assets/*.mp3`.

---

## [2.4.13] - 2026-05-27

### Fixed

- **`scrub --stats` now clears `Global Statistics.ini`** — RocketLauncher's aggregate `Data/Statistics/Global Statistics.ini` was not deleted during a stats scrub. After the per-system files were removed, the "Recently Played" and "Most Played" refresh fell back to reading this file and repopulated the wheels with the same old games. The aggregate is now included in the scrub (backed up when `--backup-dir` is given); RL regenerates it fresh on the next game launch.

---

## [2.4.12] - 2026-05-27

### Added

- **HyperSpin theme zips for synthetic wheels** — SpinDoctor now bundles and installs `Media\Main Menu\Themes\<SystemName>.zip` for `Favorites`, `Most Played`, and `Recently Played`. Without a theme zip HyperSpin silently skips the attract-mode audio/video entirely. Each zip contains only `Theme.xml` (no `Info.txt`, no SWF files), matching the reference layout provided by the cabinet owner: `<video w="1024" h="768" x="512" y="384" forceaspect="both" .../>` — full-screen, centred on HyperSpin's 1024×768 canvas. Installed by `rebuild --apply` (skip-if-exists) and `mainmenu add --apply` (always overwrite). Theme zips ship via the `assets/*.zip` package-data glob.

- **Bundled MP3 files removed** — The three `music_*.mp3` assets are no longer bundled or installed. The attract-mode MP4 carries its own audio track, which covers the idle/attract use-case. HyperSpin's active-browsing music slot (`Media\Main Menu\Sound\<System>.mp3`, which plays while the user is scrolling the main-menu wheel) now plays silence. `_MUSIC_ASSETS` is intentionally empty; `install_system_music()` returns `"no_asset"` for all systems. The `assets/*.mp3` glob is removed from `pyproject.toml`.

- **`mainmenu add` now installs bundled media for synthetic wheels** — When `spindoctor mainmenu add Favorites --apply` (or `Recently Played` / `Most Played`) is run, SpinDoctor now installs all five bundled assets (wheel logo, attract-mode background, music, video, **theme zip**) to `Media\Main Menu\` in addition to updating `Main Menu.xml`. Unlike `rebuild --apply` which skips files that already exist, `mainmenu add` always writes the bundled assets so the wheel gets a fresh copy — useful for first-installs and for resetting media after an upgrade. The GUI "Add wheels to Main Menu" button calls `mainmenu add --apply` for each wheel and automatically gets this behaviour. Dry-run (`mainmenu add` without `--apply`) shows what would be installed/overwritten.

- **`install_bundled_system_assets()` and all individual install functions gain an `overwrite` keyword argument** — `overwrite=False` (default, used by rebuild) preserves user-placed files; `overwrite=True` (used by `mainmenu add`) always writes the bundled asset. New status value `"overwritten"` returned when a file was replaced. `_add_bundled_asset_rows()` helper extracted from `_print_synth_summary()` for reuse in `mainmenu add` output. Function now returns five keys: `wheel_art`, `background`, `music`, `video`, `theme`.

### Fixed

- **Bundled background images were zoomed in / showing only top-left corner** — Background PNGs were stored at the original export resolution (2752×1536). HyperSpin renders them at 1:1 pixels rather than scaling to fit, so only the top-left fraction of each image was visible. All three backgrounds are now **1920×1080** (center-crop scale, matching the video resolution and typical cabinet display), which HyperSpin renders at full screen. The video files are unchanged.

- **Attract-mode videos not playing on Windows 7 / HyperSpin** — Bundled videos were encoded at 2752×1536 (native background resolution) with H.264 High Profile, Level 5.0. The HyperSpin Adobe AIR runtime and Windows 7's DirectShow decoders only support H.264 up to Main Profile, Level 4.0; Level 5.0 causes the video track to be silently dropped while audio continues playing. All three attract-mode videos are now encoded at **1920×1080, H.264 Main Profile, Level 4.0** (`-vf scale=1920:1080 -profile:v main -level 4.0`). HyperSpin scales the video to fit the screen — the resolution of the source frame does not need to match the cabinet display.

- **`scrub --backup-dir` was silently skipped in dry-run mode** — Passing `--backup-dir` alongside a dry-run (`spindoctor scrub --backup-dir /path`) previously printed `"(--backup-dir is skipped in dry-run mode)"` and created no backup. The option now works in **both** dry-run and apply modes: in dry-run it creates the `scrub-<timestamp>/` snapshot (useful for capturing current state before deciding to apply), in apply mode it backs up then deletes as before. Output in dry-run: `"Snapshot created (N files) → <path>  (dry-run: no data was deleted)"`.

### Changed

- **GUI scrub panel**: "Backup first to" label updated to "Backup to" and helper text updated to clarify the backup runs on both dry-run and apply.

---

## [2.4.11] - 2026-05-27

### Added

- **Bundled system media for all three synthetic wheels** — SpinDoctor now ships twelve media assets (wheel logo + attract-mode background + attract-mode music + attract-mode video, one of each per wheel) for `Favorites`, `Most Played`, and `Recently Played`. Every `rebuild --apply` automatically installs them to `Media\Main Menu\` — the directory HyperSpin reads for attract-mode / system-selector display:
  - `Media\Main Menu\Images\Wheel\<SystemName>.png` — wheel selector logo (1536 × 1024 px)
  - `Media\Main Menu\Images\Backgrounds\<SystemName>.png` — background shown during attract mode (2752 × 1536 px)
  - `Media\Main Menu\Sound\<SystemName>.mp3` — music played during attract mode (192 kbps MP3)
  - `Media\Main Menu\Video\<SystemName>.mp4` — attract-mode video: static background frame + looped music, duration = 2× the music track (Favorites 57.7 s, Most Played 57.9 s, Recently Played 61.5 s). HyperSpin advances to the next system when the video ends — no global timer configuration required.

  All installs are idempotent: if a file already exists (user-placed or previously installed), SpinDoctor skips it. The rebuild summary shows a `Wheel art / Background / Music / Video` row for each asset. MP3 and MP4 files are now included in the `pyproject.toml` package-data glob.

- **`install_bundled_system_assets()`** — new umbrella function in `rocketlauncher.py` that runs `install_system_wheel_art()`, `install_system_background()`, `install_system_music()`, and `install_system_video()` in one call. Returns `{type: (path, status)}`.

- **`docs/synthetic-wheel-media.md`** — new guide covering all media layers for the synthetic wheels: full table of what gets auto-installed, and step-by-step instructions for themes, navigation sounds, and custom video replacement.

### Fixed

- **Scheduled wheel refresh froze the arcade** — The Windows Task Scheduler task previously ran `cmd.exe /c bat.bat` at normal process priority, competing directly with HyperSpin and RocketLauncher for CPU and disk I/O. On cabinet hardware this stalled the frontend visibly. Two changes fix it:
  1. The generated `.bat` file now wraps each rebuild command with `START /LOW /B /WAIT` — the three spindoctor executables run at Windows **IDLE** process priority and only consume cycles that the cabinet software isn't using.
  2. The scheduled task now points at a companion `spindoctor-refresh-wheels.vbs` shim instead of `cmd.exe` directly. The shim calls the bat with `WshShell.Run(bat, 0, True)` (window style 0 = hidden), so no `cmd.exe` console window ever appears on the cabinet screen. To pick up the fix, click *Remove scheduled task* then *Schedule auto-refresh* again in the GUI Tools tab.

- **XML writes were not shutdown-safe** — Direct `file.write_bytes(data)` calls left a window where a forced shutdown mid-save produced a truncated, unparseable HyperSpin XML. All XML and JSON store writes in `database.py` and `favorites.py` now use a **temp-file + `os.replace` atomic rename**: the live path is only swapped in once the new content is fully flushed. The previous `.bak` mechanism is unchanged — shutdown safety now operates at the write level as well as the backup level.

- **New `stale-atomic-writes` cleanup category** — If a write was interrupted before the atomic rename completed (power cut, `SIGKILL`), a `.tmp` sidecar file is left next to the live XML. `cleanup audit` and `cleanup run --include stale-atomic-writes` now surface and remove these. `self-doctor --fix` also removes them automatically (5-minute age threshold — a write normally completes in milliseconds).

- **`atomic_tmp_dir` config option** — All atomic-write `*.tmp` files now land in a single user-configured scratch directory instead of scattered next to their respective XML/JSON targets throughout the HyperSpin Databases tree. Set via `spindoctor config set atomic_tmp_dir D:\SpinDoctorTemp` or the new **Atomic write temp directory** field in the GUI Setup tab. Must be on the same drive as `hyperspin_dir`; cross-drive values are silently ignored (falls back to writing next to the target). `cleanup` and `self-doctor` both scan the configured dir in addition to the default fallback locations.

---

## [2.4.10] - 2026-05-26

### Fixed

- **`scrub --stats` crashed on Python 3.8 (cabinet build) with `AttributeError: 'WindowsPath' object has no attribute 'is_relative_to'`** — `Path.is_relative_to()` was added in Python 3.9; the cabinet binary is built on Python 3.8.10. The bug was in the file-listing display loop in `scrub_cmd` (the `_scrub_backup` helper already used the correct `try/except` pattern). Fixed by replacing the `is_relative_to` one-liner with `try/except ValueError` around `f.relative_to(rl)`. Two regression tests added to `tests/test_scrub_backup.py` that require a real Statistics.ini to be present so the listing loop is actually entered.

- **Scrub backup directory timestamp used an inconsistent separator** — `scrub --backup-dir` produced `scrub-YYYYMMDD-HHMMSS/` (hyphen between date and time) while every other backup-creating operation in SpinDoctor uses `YYYYMMDD_HHMMSS` (underscore). Changed strftime format from `%Y%m%d-%H%M%S` to `%Y%m%d_%H%M%S`. Example paths in `scrub-restore` docstring, `docs/commands.md`, and `docs/cli-cheatsheet.md` updated to match.

---

## [2.4.9] - 2026-05-26

### Added

- **`scrub --backup-dir DIR`** — copy all affected files to `DIR/scrub-<timestamp>/` before deleting. Creates `favorites.json` and every `Statistics.ini` file (across all three RL layouts) in a plain folder with a `manifest.json` index. The backup is skipped in dry-run mode. Strongly recommended before `--stats` (Statistics.ini files are not regenerable by SpinDoctor).

- **`scrub-restore <backup-path> [--apply]`** — restore files from a `scrub --backup-dir` backup. Reads `manifest.json` and copies each file back to its original location. Dry-run by default; `--apply` to commit.

- **Scrub panel in GUI (Tools tab)** — "Reset wheel data (scrub)" section added to the Tools tab alongside the other wheel controls. Provides checkboxes for Favorites / Play statistics, optional backup directory (with Browse), Apply checkbox, and a nested Restore sub-panel. Confirmation dialogs warn before destructive applies and require extra confirmation when `--stats` is selected without a backup directory.

- **System name in synthetic wheel descriptions** — every entry in the Favorites, Recently Played, and Most Played wheels now shows its source console in the description, e.g. "Kirby's Dream Land (Super Nintendo Entertainment System)". This resolves the common case where the same title exists on multiple platforms and the wheel gave no indication of which version was which.

- **Synthetic wheels skipped in `--all` system commands** — `fetch-meta`, `fetch-media`, `media-scan`, `update-db`, `audit`, `find-dupes`, `find-misplaced`, `find-orphan-media`, `curate`, `check-discs`, `report`, and all other commands that accept `--system` / `--all` now automatically exclude Favorites, Recently Played, and Most Played when `--all` is used. These wheels mirror their media from the source systems — scraping or scanning them wastes API calls and produces meaningless results. A dim banner is printed for each skipped wheel. Explicitly naming a synthetic wheel with `--system` exits with a helpful error directing the user to the original source system instead.

- **`scrub --hs-favorites`** — new flag that clears per-system HyperSpin favorites so `fav sync` starts from a blank slate. Three sources are cleared: `<System>_Favorites.ini` files (deleted), `favorites.txt` files (deleted), and `favorite="1"` attributes in system XML databases (stripped in-place via targeted regex — no XML reformatting). Covered by `--backup-dir` (backed up to `hs_favorites/` subfolder) and dry-run. Not included in the no-flag default (must be requested explicitly). GUI: new "HyperSpin per-system favorites (start fresh for fav sync)" checkbox in the Tools tab scrub panel, unchecked by default.

### Changed

- **`scrub` now exposes file lists per flag** — the `--favorites` and `--stats` options are independent; selecting neither defaults to both (existing behaviour preserved). The `--backup-dir` option is additive on top of either flag.

---

## [2.4.8] - 2026-05-26

### Fixed

- **Synthetic wheel plays polluted Recently Played / Most Played** — when a game is launched from Favorites (or Recently Played / Most Played), RL#1 records the session under the synthetic system name (e.g. "Favorites"). SpinDoctor's stats reader previously included those entries, so playing "Strider" from Favorites would also add it to Recently Played attributed to "Favorites" instead of its real system. `collect_play_records` and `load_all_playtime` now skip statistics files for all three synthetic wheel names by default. Stats from real system wheels are unaffected.

- **"Error waiting for window ahk_pid XXXX" 30 seconds after game launches from synthetic wheel** — root cause identified from PCLauncher.ahk v2.2.7 source (lines 214-224). When `AppWaitExe` is set without `FadeTitle`, PCLauncher finds the emulator process (correct) then tries to locate that process's window by PID. DirectX emulators running in exclusive fullscreen or creating their game window in a child process don't produce a Win32 window detectable by that PID. The 30-second wait times out, RL#1 aborts, the game keeps running as an orphan (user must ALT+TAB).

  Fix: SpinDoctor now writes `FadeTitle=<title>` and `FadeTitleTimeout=30` alongside `AppWaitExe=` for known emulators. Setting `FadeTitle` causes PCLauncher to skip the PID-based window search entirely (`If !FadeTitle` block at PCLauncher.ahk line 215) and instead find the game window by title, which works regardless of child-process hierarchy. `AppWaitExe.Process("WaitClose")` then handles exit detection cleanly. `FadeTitleTimeout=30` prevents an infinite hang if the emulator crashes before showing a window.

  `FadeTitle` now works for **every emulator automatically** — no per-emulator registration required. `_get_fade_title` falls back to the emulator's registered name when it isn't found in the correction table. AHK `WinWait` uses case-insensitive partial matching, so "Supermodel" matches "Supermodel 3.1 UI", "Model 2" matches "Sega Model 2 Emulator", etc. The `EMULATOR_WINDOW_TITLES` table is now a correction-only override for the rare case where an emulator's window title contains no part of its registered name.

### Added

- **`scrub` command** — destructively reset cabinet data behind `--apply`. Without flags, both favorites and statistics are cleared. `--favorites` clears `favorites.json` and removes the Favorites wheel from disk. `--stats` deletes every RocketLauncher Statistics.ini file and clears the Recently Played and Most Played wheel content. Dry-run preview shown without `--apply`.

- **User-configurable emulator window-title corrections** — for the rare emulator whose window title doesn't contain its registered name, custom `emulator → title-fragment` pairs can be registered via the new `emulator-title` CLI group, stored in `config.json` under `emulator_window_titles`. User-supplied entries take precedence over the built-in correction table so built-in entries can also be overridden without editing source code.

  Commands:
  - `spindoctor emulator-title set <EmulatorName> <window title fragment>` — add or update a correction
  - `spindoctor emulator-title remove <EmulatorName>` — remove a correction (built-in entries cannot be removed, only overridden)
  - `spindoctor emulator-title list` — display all effective mappings, marking which are built-in, user-defined, or user overrides of a built-in

---

## [2.4.7] - 2026-05-26

### Fixed

- **Games in Favorites / Recently Played / Most Played never launched the emulator** — root cause identified as AHK `#SingleInstance`. `RocketLauncher.exe` is a compiled AutoHotkey script. When PCLauncher launches a second instance (RL#2) to run the actual game while RL#1 is already running for the synthetic wheel, AHK's single-instance mutex detects the collision and exits RL#2 immediately — before it opens the log file, before it loads the emulator module, before it starts anything. PCLauncher's `AppWaitExe` timer then ran out waiting for an emulator process that would never appear. Diagnosed by observing only one `RocketLauncher.exe*32` process in Task Manager throughout the 15-second failure window; RL#2 never appeared as a separate process.

  Fix: SpinDoctor now creates `RocketLauncherGame.exe` as a copy of `RocketLauncher.exe` in the same RocketLauncher directory during wheel refresh. PCLauncher entries in the system-level INI use `Application=RocketLauncherGame.exe` instead of `Application=RocketLauncher.exe`. AHK's single-instance mutex is keyed to the executable's full path, so the renamed copy has a unique identity and both RL instances coexist freely. The copy is created or refreshed automatically when its size differs from the source (handles RL updates). Falls back to `RocketLauncher.exe` if the source is missing or the copy cannot be written.

---

## [2.4.6] - 2026-05-26

### Fixed

- **Games in Favorites / Recently Played / Most Played still failed with "error waiting for window ahk_pid XXXX"** after the `-p HyperSpin` fix in v2.4.5. Root cause: RL#2 running in standalone mode (no `-p HyperSpin`) never creates a visible window. PCLauncher.ahk's default behaviour is to wait for a window owned by the Application's PID — when no window appears it times out after ~30 s. Fix: SpinDoctor now resolves the source system's emulator executable and writes `AppWaitExe=<emulator.exe>` in each entry of the system-level PCLauncher INI. This tells PCLauncher to poll for the named process instead of waiting for a window. For standard emulator source systems (MAME, RetroArch, etc.) the exe is resolved from `Settings/<system>/Emulators.ini` or `Settings/<system>.ini`, with a fallback to the built-in `EMULATOR_EXECUTABLES` table. For PCLauncher-based source systems (PC Games, Windows, etc.) the exe is read from the per-game `Modules/PCLauncher/<source_system>/<game>.ini`; entries with `.lnk`, `.bat`, or `.url` paths omit `AppWaitExe` since those are not monitorable process names.

---

## [2.4.5] - 2026-05-26

### Fixed

- **Games in Favorites / Recently Played / Most Played failed with "error waiting for window ahk_pid XXXX"** after launching correctly from PCLauncher. Root cause: the recursive `RocketLauncher.exe` call in the system-level PCLauncher INI was launched with `-p HyperSpin`. RocketLauncher #1 (launched by HyperSpin for the Favorites wheel) already owns the HyperSpin IPC pipe and has faded the UI. When RL#2 also starts with `-p HyperSpin` it tries to send a second FadeOut to an already-owned pipe — the startup sequence stalls and RL#2 can't detect the emulator's window. Removed `-p HyperSpin` from the recursive call so RL#2 runs in standalone mode: it launches the emulator, waits for it to exit, and exits cleanly. PCLauncher (inside RL#1) detects RL#2's exit and returns control to RL#1, which handles the HyperSpin fade-back normally.

### Added

- **`docs/cabinet-architecture-reference.md`** — documents the HyperSpin + RocketLauncher + PCLauncher file layout, the two-file PCLauncher system (ROM placeholders vs system-level INI), the recursive RL launch chain, and other cabinet-specific configuration details discovered during debugging. Framed as "this is how one cabinet is set up — yours may differ."

---

## [2.4.3] - 2026-05-26

### Added

- **`fav clear` / `recent clear` / `stats-report clear-wheel` CLI commands** — tear down the on-disk artifacts for the Favorites, Recently Played, and Most Played synthetic wheels respectively. All three are dry-run by default (preview only); pass `--apply` to commit. `fav clear --apply` also empties `~/.spindoctor/favorites.json`. RocketLauncher's `Statistics.ini` files are never touched — the derived wheels can always be rebuilt.

- **GUI "Clear wheels" section** in the Wheels tab — two new buttons: "Preview clear (dry run)" runs the clear commands without `--apply` so you can inspect what would be removed; "Clear selected (--apply)" shows a confirmation dialog then permanently removes artifacts for the checked wheels. Both buttons respect the Favorites / Recently Played / Most Played checkboxes.

### Fixed

- **`uninstall-tools` deleted files immediately when run from the GUI, even though the GUI showed a DRY RUN banner.** The command had no `--apply` gate, so the GUI's dry-run heuristic (`"--apply" not in args`) correctly showed the banner but the command ignored it and deleted anyway. `uninstall-tools` now requires `--apply` to make any changes — without it, it prints a preview table of what would be removed and exits. The GUI's **Uninstall from wheel** button now shows a confirmation dialog and passes `--apply` only after the user confirms.

- **`fav rebuild --apply --verbose` crashed on Windows** with `UnicodeEncodeError: 'charmap' codec can't encode character '→'`. The `→` arrow in the per-file log line (`copy src\n     →  dest`) cannot be encoded by the Windows cp1252 console. Replaced with `->`.

- **Games in Favorites / Recently Played / Most Played still failed to launch** with "You have not set up `<game>` in RocketLauncherUI yet, so PCLauncher does not know what exe, FadeTitle, and/or SteamID to watch for." Root cause: PCLauncher.ahk reads game configuration from a **system-level** `Modules/PCLauncher/<SystemName>.ini` file, looking for `[<game_name>]` sections with `Application=` / `Parameters=` / `WorkingFolder=` keys. SpinDoctor was only writing per-game placeholder files in the same-named subdirectory — those are used only by RocketLauncher for ROM discovery; PCLauncher.ahk never reads their content. SpinDoctor now also writes `Modules/PCLauncher/<SystemName>.ini` (e.g., `Favorites.ini`, `Recently Played.ini`, `Most Played.ini`) with the correct per-game sections during every rebuild.

---

## [2.4.2] - 2026-05-25

### Added

- **`uninstall-tools` CLI command** — the reverse of `install-tools --add-to-system`. Removes the SpinDoctor-written `.bat` and `.ini` files from both the detected `Rom_Path` directory and the legacy `Modules/PCLauncher/<system>/` fallback, then deletes the matching `<game>` entries (`Refresh Favorites`, `Refresh Recently Played`, `Refresh Most Played`, `Refresh All`, and the legacy `Refresh Both`) from the system's database XML. Without `--add-to-system`, removes the helpers from the default HyperLaunch Tools folder instead. Only files and entries that exist are touched; missing ones are silently skipped. The GUI's Tools tab gains an **Uninstall from wheel** button next to the existing **Install into wheel** button — it uses the same system name field.

### Fixed

- **Games in Favorites / Recently Played / Most Played wheels failed to launch** with "Cannot find Rom X with any provided Rom_Extension: zip|rar|7z|…" even after a successful rebuild. The flat-layout `Settings/<system>.ini` written by SpinDoctor had `Rom_Extension=ini` in `[Settings]` but was missing it from `[PCLauncher]`. RocketLauncher reads `Rom_Extension` from the `[PCLauncher]` section when that section exists and ignores the `[Settings]` value entirely when the key is absent — falling back to the global extension list. `[PCLauncher]` now includes `Rom_Extension=ini` so RL looks for the per-game `.ini` files instead of searching for non-existent `.zip` or `.rar` ROMs.

- **HyperSpin themes were not copied during Favorites / Recently Played / Most Played wheel rebuilds**, leaving those wheels with no video preview or background artwork. Themes are almost always distributed as per-game `.zip` files (`Media/<system>/Themes/<game>.zip`). The media mirror code (`medialink.py`) treated the `Themes` subfolder as directory-only — looking for an extracted `Themes/<game>/` folder — so `.zip`-form themes were never found or copied. `"Themes"` has been added to `MEDIA_FILE_SUBDIRS` so zip-form themes are mirrored alongside video and wheel art. The extracted-directory path (`MEDIA_DIR_SUBDIRS`) is retained for the less common case.

- **`install-tools --add-to-system` wrote helper files to `Modules/PCLauncher/<system>/` even when the system's existing `Settings/<system>/Emulators.ini` pointed `Rom_Path` elsewhere.** PCLauncher resolves per-game INI files from `Rom_Path` — if that path is, for example, `D:\Arcade\Utilities\Toolkit`, PCLauncher never looks in `Modules/PCLauncher/Toolkit/` and shows "You have not set up Refresh Favorites in RocketLauncherUI yet." `install-tools` now reads the first `Rom_Path` entry from the existing folder-layout `Emulators.ini` (resolving relative paths relative to `rocketlauncher_dir`) and writes bat + ini files there. Systems with no pre-existing INI continue to use the `Modules/PCLauncher/<system>` default.

- **`uninstall-tools --add-to-system` only looked in `Modules/PCLauncher/<system>/` for files to remove.** After the `install-tools` fix above, files may live in the detected `Rom_Path` directory instead. `uninstall-tools` now searches both the detected path and the legacy default, so cabinets that had files written by an older version of SpinDoctor are fully cleaned up.

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
  - **LEDBlinky** tab wraps `spindoctor ledblinky`: per-system Generate (controls.ini + Colors.ini), Audit coverage, Check existing INIs, and Fix INI issues — with an Overwrite toggle for community-maintained entries and dry-run by default.
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

- `ledblinky generate` / `audit` — generate `controls.ini` and `Colors.ini` from MAME `-listxml`, preserving any community-maintained entries.
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

- `build/build_windows.py` — PyInstaller driver producing five `.exe` binaries in a shared-runtime `--onedir` bundle (`dist/spindoctor/`).
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

[Unreleased]: https://github.com/phillram/spindoctor/compare/v2.7.8...HEAD
[2.7.8]: https://github.com/phillram/spindoctor/compare/v2.7.7...v2.7.8
[2.7.7]: https://github.com/phillram/spindoctor/compare/v2.7.6...v2.7.7
[2.7.6]: https://github.com/phillram/spindoctor/compare/v2.7.5...v2.7.6
[2.7.5]: https://github.com/phillram/spindoctor/compare/v2.7.4...v2.7.5
[2.7.4]: https://github.com/phillram/spindoctor/compare/v2.7.3...v2.7.4
[2.7.3]: https://github.com/phillram/spindoctor/compare/v2.7.2...v2.7.3
[2.7.2]: https://github.com/phillram/spindoctor/compare/v2.7.1...v2.7.2
[2.7.1]: https://github.com/phillram/spindoctor/compare/v2.7.0...v2.7.1
[2.7.0]: https://github.com/phillram/spindoctor/compare/v2.6.3...v2.7.0
[2.6.3]: https://github.com/phillram/spindoctor/compare/v2.6.2...v2.6.3
[2.6.2]: https://github.com/phillram/spindoctor/compare/v2.6.1...v2.6.2
[2.6.1]: https://github.com/phillram/spindoctor/compare/v2.6.0...v2.6.1
[2.6.0]: https://github.com/phillram/spindoctor/compare/v2.5.3...v2.6.0
[2.5.3]: https://github.com/phillram/spindoctor/compare/v2.5.2...v2.5.3
[2.5.2]: https://github.com/phillram/spindoctor/compare/v2.5.1...v2.5.2
[2.5.1]: https://github.com/phillram/spindoctor/compare/v2.5.0...v2.5.1
[2.5.0]: https://github.com/phillram/spindoctor/compare/v2.4.27...v2.5.0
[2.4.27]: https://github.com/phillram/spindoctor/compare/v2.4.26...v2.4.27
[2.4.26]: https://github.com/phillram/spindoctor/compare/v2.4.25...v2.4.26
[2.4.25]: https://github.com/phillram/spindoctor/compare/v2.4.24...v2.4.25
[2.4.24]: https://github.com/phillram/spindoctor/compare/v2.4.23...v2.4.24
[2.4.23]: https://github.com/phillram/spindoctor/compare/v2.4.22...v2.4.23
[2.4.22]: https://github.com/phillram/spindoctor/compare/v2.4.21...v2.4.22
[2.4.21]: https://github.com/phillram/spindoctor/compare/v2.4.20...v2.4.21
[2.4.20]: https://github.com/phillram/spindoctor/compare/v2.4.19...v2.4.20
[2.4.19]: https://github.com/phillram/spindoctor/compare/v2.4.18...v2.4.19
[2.4.18]: https://github.com/phillram/spindoctor/compare/v2.4.17...v2.4.18
[2.4.17]: https://github.com/phillram/spindoctor/compare/v2.4.16...v2.4.17
[2.4.16]: https://github.com/phillram/spindoctor/compare/v2.4.15...v2.4.16
[2.4.15]: https://github.com/phillram/spindoctor/compare/v2.4.14...v2.4.15
[2.4.14]: https://github.com/phillram/spindoctor/compare/v2.4.13...v2.4.14
[2.4.13]: https://github.com/phillram/spindoctor/compare/v2.4.12...v2.4.13
[2.4.12]: https://github.com/phillram/spindoctor/compare/v2.4.11...v2.4.12
[2.4.11]: https://github.com/phillram/spindoctor/compare/v2.4.10...v2.4.11
[2.4.10]: https://github.com/phillram/spindoctor/compare/v2.4.9...v2.4.10
[2.4.9]: https://github.com/phillram/spindoctor/compare/v2.4.8...v2.4.9
[2.4.8]: https://github.com/phillram/spindoctor/compare/v2.4.7...v2.4.8
[2.4.7]: https://github.com/phillram/spindoctor/compare/v2.4.6...v2.4.7
[2.4.6]: https://github.com/phillram/spindoctor/compare/v2.4.5...v2.4.6
[2.4.5]: https://github.com/phillram/spindoctor/compare/v2.4.3...v2.4.5
[2.4.3]: https://github.com/phillram/spindoctor/compare/v2.4.2...v2.4.3
[2.4.2]: https://github.com/phillram/spindoctor/compare/v2.4.1...v2.4.2
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
