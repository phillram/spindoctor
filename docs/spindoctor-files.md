# SpinDoctor Files and Storage Locations

This document describes SpinDoctor's main storage locations and the cabinet files it manages. Paths are examples, not a required drive layout. See [Privacy and sharing diagnostics](privacy.md) before sharing any of these files.

---

## Quick Reference — Copy-Paste Paths

### Windows (cabinet)

```bat
:: SpinDoctor config directory (all app-managed files)
%USERPROFILE%\.spindoctor\

:: Open in Explorer:
explorer %USERPROFILE%\.spindoctor

:: Individual files
%USERPROFILE%\.spindoctor\config.json
%USERPROFILE%\.spindoctor\favorites.json
%USERPROFILE%\.spindoctor\scraper.log
%USERPROFILE%\.spindoctor\scraper.log.1
%USERPROFILE%\.spindoctor\scraper.log.2
%USERPROFILE%\.spindoctor\metadata_cache\
%USERPROFILE%\.spindoctor\match_cache\
%USERPROFILE%\.spindoctor\mame_listxml_cache\
%USERPROFILE%\.spindoctor\ledblinky_library\
```

On a typical Windows cabinet, `%USERPROFILE%` expands to `C:\Users\<YourWindowsUsername>`, so the full path looks like:

```
C:\Users\<YourWindowsUsername>\.spindoctor\
```

### macOS / Linux (developer machine)

```bash
# SpinDoctor config directory
~/.spindoctor/

# Open in Finder (macOS):
open ~/.spindoctor

# Individual files
~/.spindoctor/config.json
~/.spindoctor/scraper.log
~/.spindoctor/metadata_cache/
~/.spindoctor/match_cache/
~/.spindoctor/mame_listxml_cache/
~/.spindoctor/ledblinky_library/
```

---

## Config Directory — `%USERPROFILE%\.spindoctor\`

This directory holds SpinDoctor's settings, caches, recovery records and library data. HyperSpin and LEDBlinky do not read these stores directly. Generated autorun scripts may also live here and are run by Windows Task Scheduler.

### `config.json`

**SpinDoctor's main settings file.** Created the first time you run any SpinDoctor command or open the GUI. All paths in this file are absolute. Example:

```json
{
  "roms_dir":              "D:\\Games",
  "hyperspin_dir":         "D:\\Arcade",
  "emulators_dir":         "D:\\Arcade\\Emulators",
  "rocketlauncher_dir":    "D:\\Arcade\\RocketLauncher",
  "ledblinky_dir":         "D:\\Arcade\\LEDBlinky",
  "output_dir":            "C:\\SpinDoctor\\output",
  "backup_dir":            "C:\\SpinDoctor\\backups",
  "atomic_tmp_dir":        "C:\\SpinDoctor\\temps",
  "auto_audit_export_dir": "C:\\SpinDoctor\\audits",
  "screenscraper_user":    "...",
  "screenscraper_pass":    "...",
  "screenscraper_devid":   "...",
  "screenscraper_devpassword": "...",
  "thegamesdb_key":        "...",
  "max_concurrent_downloads": 4,
  "metadata_cache_ttl_days": 30,
  "metadata_cache_enabled": true
}
```

Read with `spindoctor config show`. Written by `spindoctor config set <key> <value>` or via the GUI **Setup** tab.

If this file is corrupt (invalid JSON), SpinDoctor backs it up as `config.corrupt-YYYYMMDD_HHMMSS.json` in the same directory and starts fresh with defaults.

### `scraper.log`, `scraper.log.1`, `scraper.log.2`

**Rotating log of every ScreenScraper and TheGamesDB HTTP call SpinDoctor makes.**

| Property | Value |
|----------|-------|
| Location | `%USERPROFILE%\.spindoctor\scraper.log` |
| Max size per file | 512 KB |
| Backups kept | 2 (`scraper.log.1`, `scraper.log.2`) |
| Encoding | UTF-8 |

Each line is one request:

```
2026-06-14 17:46:36,260 ERROR thegamesdb.fetch GET https://api.thegamesdb.net/v1/Games/ByGameName
  params={'apikey': '***', 'name': 'Animal Crossing (USA)', ...}
  → HTTPSConnectionPool(...): Max retries exceeded ... (Caused by NameResolutionError(...))

2026-06-14 12:45:16,968 INFO screenscraper.fetch GET https://www.screenscraper.fr/api2/jeuInfos.php
  params={'devid': '...', 'devpassword': '***', 'ssid': '...', ...}
  → HTTP 404 (40 bytes)
2026-06-14 12:45:17,015 DEBUG screenscraper.fetch body: Erreur : Rom/Iso/Dossier non trouvée !
```

SpinDoctor redacts scraper passwords and API keys (`***`), but that does not anonymize the log. Account identifiers, game names, URLs and error paths may remain. Review a small relevant excerpt before sharing it; see [Privacy and sharing diagnostics](privacy.md#sharing-logs-and-reports).

Log prefixes by call site:

| Prefix | Endpoint |
|--------|----------|
| `screenscraper.verify` | `ssuserInfos.php` — credential check |
| `screenscraper.fetch` | `jeuInfos.php` — direct ROM lookup |
| `screenscraper.search` | `jeuRecherche.php` — text search |
| `screenscraper.systems` | `systemesListe.php` — system list (used for Main Menu media) |
| `thegamesdb.verify` | `Games/ByGameName?name=test` — credential check |
| `thegamesdb.fetch` | `Games/ByGameName?name=<game>` — direct lookup |
| `thegamesdb.search` | `Games/ByGameName?name=<normalized>` — search |
| `thegamesdb.images` | `Games/Images?games_id=<id>` — image fetch |

**When to check this file:** any time `fetch-meta`, `fetch-media`, or a credential test returns unexpected results. See [Troubleshooting → Metadata / scraping](troubleshooting.md#metadata--scraping).

### `metadata_cache\`

**Disk cache of scraped game metadata.** Avoids re-querying ScreenScraper / TheGamesDB on every `fetch-meta` run and protects your monthly TheGamesDB quota.

```
%USERPROFILE%\.spindoctor\metadata_cache\
├── screenscraper\
│   └── Nintendo_Gamecube\
│       ├── Animal_Crossing_USA_-<sha256>.json
│       ├── Baten_Kaitos_-_Eternal_Wings-<sha256>.json
│       └── ...
├── thegamesdb\
│   └── Nintendo_Gamecube\
│       └── ...
└── combined\
    └── ...
```

Source and system folder names are filename-sanitized. Each filename contains a sanitized ROM stem (up to 80 characters) and a SHA-256 hash of the full source/system/stem identity, preventing sanitized-name collisions. Legacy unhashed files are read only when their recorded identity matches the request.

Each file is a JSON object with a `cached_at` timestamp. Entries older than `metadata_cache_ttl_days` (default: 30 days) are silently skipped on next read and a fresh API call is made.

**Management commands:**

```bat
spindoctor fetch-meta --system MAME --no-cache     :: bypass cache for this run only
spindoctor fetch-meta --system MAME --clear-cache  :: clear this system's API cache and exit
spindoctor cleanup run --include metadata-cache          :: preview cache deletion
spindoctor cleanup run --include metadata-cache --apply  :: delete it
```

The cache can be deleted manually — SpinDoctor will re-populate it on next run. There is no risk of data loss.

### `match_cache\`

**Stores your manual match decisions from `fetch-meta`.** When `fetch-meta` finds multiple candidates and you pick one interactively, the choice is saved here so future runs on the same game auto-select the same match without prompting.

```
%USERPROFILE%\.spindoctor\match_cache\
├── MAME.json
├── Nintendo Gamecube.json
└── ...
```

One JSON file per system. Each entry maps a ROM name to the chosen metadata source ID.

**Management commands:**

```bat
spindoctor match list                                  :: show every cached decision
spindoctor match clear --system "Nintendo Gamecube"    :: clear decisions for one system
spindoctor match clear                                 :: clear all decisions (prompts; --yes to skip)
spindoctor cleanup run --include match-cache --apply   :: same, via the cleanup tool
```

Clearing match decisions only resets which candidate was chosen — it does **not** roll back any metadata already written to the HyperSpin databases. To undo writes, restore from the `.bak` backup next to the XML file.

### `mame_listxml_cache\`

**Cache of MAME's `-listxml` output.** Used by `spindoctor audit` (MAME control data for arcade systems) and `spindoctor ledblinky generate` / `audit` / `inspect-rom`, so `mame -listxml` doesn't run on every invocation (it takes 10–20 seconds for large MAME builds, and a full dump is about 200 MB). The `doctor` LED coverage check only reads it.

```
%USERPROFILE%\.spindoctor\mame_listxml_cache\
└── mame-1a2b3c4d.xml    :: raw listxml output, one file per MAME executable
```

The file is named after the `mame_executable` binary plus a short hash of its full path. Every system shares that one file, and two MAME installs that are both called `mame.exe` get separate files. The cache is automatically invalidated when the MAME executable is newer than the cached file (modification time comparison). Safe to delete — SpinDoctor will regenerate it on the next run that needs it.

Older versions wrote one identical copy per MAME system instead (`MAME.xml`, `Neo Geo.xml`, …), each the size of the full dump. Those files are no longer read. Remove them with `spindoctor cleanup run --include listxml-cache --apply`, which also removes the current file (it is rebuilt on the next run), or delete them by hand.

### Other caches

| Path | What it holds | Safe to delete? |
|------|---------------|-----------------|
| `media_pick_cache\` | Media-asset selections you made during `fetch-media` (one JSON per system) | Yes — you'll just be asked again |
| `pc_titles_cache\` | Confirmed display titles from `add-pc-system` / `pc-rename` title review (one JSON per system) | Yes — the review re-prompts on the next run |

Both are also covered by `spindoctor cleanup run` (categories `media-pick-cache` and `pc-titles-cache`).

### `ledblinky_library\`

**Preserved LEDBlinky entries, not a disposable cache.** `ledblinky prune --apply` saves removed live sections here before pruning them. The library contains `controls.ini`, `Colors.ini` and, when available, `community-controls.ini` (a saved community controls file). LEDBlinky never reads this folder.

`ledblinky generate` and `setup` restore missing entries from the library before synthesizing them from MAME data. `profiles` can also use it for donor and community data. Keep it in your independent backups: deleting it can discard custom sections that are no longer in the live files. See [Command reference → LEDBlinky](commands.md#ledblinky) for pruning and regeneration.

### `favorites.json`

**The cross-system Favorites store** — one `(system, rom_name)` pair per favorited game. Read and written by `spindoctor fav add / remove / sync / rebuild / clear` and the GUI's Custom Wheels tab. Deleting it empties your Favorites (the generated wheel itself lives in the HyperSpin tree and is rebuilt by `fav rebuild --apply`). See [Commands → Custom wheels](commands.md#custom-wheels).

### `gui.lock`

**The GUI's single-instance lock.** Taken on `spindoctor-gui` startup so two windows can't write the same HyperSpin XML simultaneously; released automatically when the process exits, including after a crash. See [Troubleshooting → Install / startup](troubleshooting.md#install--startup).

### `tests\`

**Game launch test runs** from `spindoctor test --apply`, one folder per run named by its start time (`test_results_dir` moves them elsewhere). Each holds `report.html` (open this), `results.csv` / `results.json`, `plan.csv`, `run.json`, `HyperSpin log.txt` with `--with-hyperspin`, RocketLauncher's log per launch under `logs\`, a screenshot per game under `screenshots\`, `stats-backup\` (RocketLauncher's play statistics from before the run, with a `scrub`-style `manifest.json`) and `journal.json` (what the run was doing, for `spindoctor test --recover`). `tests\active.json` exists only while a run is unfinished; don't delete it by hand, run `spindoctor test --recover`. Old run folders are safe to delete. Screenshots show the whole monitor and logs contain paths, so check them before sharing. See [Command reference → test](commands.md#test).

### Undo manifest directories

Commands with manifest-based undo record their changes here or in the ROM tree. This is not universal: deletion modes such as `curate --action delete` have no undo. Most manifests live in per-category folders here:

| Directory | Written by |
|-----------|-----------|
| `curation\` | `curate --apply --action archive` |
| `edits\` | `batch-edit --apply` |
| `renames\` | `rename` / `clone --apply` |
| `migrations\` | `migrate --apply` |
| `media_imports\` | `media-scan --apply` |
| `themes\` | `theme-apply --apply` (manifest + a `backup\` mirror of every overwritten file) |

Two commands write their manifests into the ROM tree instead, next to the files they moved: `find-misplaced --apply` (`_spindoctor-misplaced-<stamp>.json` at the `roms_dir` root) and `organize --restructure --apply` (`_spindoctor-restructure-<stamp>.json` inside the system's ROM folder).

Successful undo may remove its manifest; failed partial undo retains unfinished work where supported. Manifests are not expired automatically, but `spindoctor cleanup run` can prune old ones once you're sure you won't roll back. The full command ↔ manifest ↔ undo map is at [Workflows → Recovery from mistakes](workflows.md#recovery-from-mistakes).

---

## Output Directories (configured in `config.json`)

These are **not** inside `%USERPROFILE%\.spindoctor\`. They live wherever you point the relevant config keys.

### `output_dir`

Example: `C:\SpinDoctor\output\`. A destination for generated output, not a universal staging area. Commands that accept `--output-dir` can write a separate output tree instead of editing live files. Other commands use `config.output_dir` directly, such as the GUI's saved run logs and `ledblinky lwax fade`. Check each command's destination and Apply behavior in the [command reference](commands.md).

### `backup_dir`

Example: `C:\SpinDoctor\backups\`. Root folder for all timestamped backups SpinDoctor writes before any destructive change (database saves, LEDBlinky file edits, etc.).

```
C:\SpinDoctor\backups\
├── HyperSpin\
│   └── Databases\
│       └── Nintendo Gamecube\
│           └── Nintendo Gamecube.xml.20260614_174635.bak
├── LEDBlinky\
│   ├── Colors.ini.20260614_174635.bak
│   └── controls.ini.20260614_174635.bak
└── RocketLauncher\
    └── Settings\
        └── Nintendo Gamecube\
            └── Emulators.ini.20260614_174635.bak
```

(The Intro Video pool doesn't use `backup_dir` — `introvideo add`/`remove`/`restore` only ever copy or move video files, both trivially reversible by doing the opposite operation, so there's nothing to snapshot first.)

If `backup_dir` is not configured, `.bak` files are written **next to the source file** instead (e.g. `Nintendo Gamecube.xml.20260614_174635.bak` in the same folder as `Nintendo Gamecube.xml`).

### `atomic_tmp_dir`

Example: `C:\SpinDoctor\temps\`. Optional scratch area for atomic writes that support it. It must be on the **same filesystem as the individual destination**, not necessarily the HyperSpin directory. The shared writer falls back to the destination's parent if the configured scratch directory is unavailable or on another filesystem.

If not configured, temporary files land next to their targets, which may be in the cabinet tree or SpinDoctor's own data directory.

### `auto_audit_export_dir`

Example: `C:\SpinDoctor\audits\` (optional; off by default). When set, SpinDoctor automatically exports an audit CSV here after any command that modifies media or databases.

```
C:\SpinDoctor\audits\
└── audit_20260614_174958.csv
```

The CSV contains one row per game per system with columns for ROM presence, database entry, media presence per slot, and (after a `fetch-media` run) a `{slot}_result` column showing what happened to each slot this run: `downloaded`, `existing`, `no_url`, `no_match`, `no_metadata`, or `failed`, plus a `{slot}_before` column showing whether that slot already had media *before* the run — so a `False`/`downloaded` pair means the run actually filled a gap, while `True`/`existing` means it was already there.

Running `fetch-meta`/`fetch-media` with `--game NAME` scopes the export to that one game instead of every game on the system — the CSV used to always list the whole console regardless of `--game`.

After a `fetch-media` run, the CSV ends with a consolidated footer section — a blank line, then a `Games with missing media this run` header, then one row per game that still has at least one slot in a non-success state (`no_url`, `no_match`, `no_metadata`, or `failed`) with a semicolon-joined list of which slots:

```
...
NES,Mario,True,True,False,,,,,True,True,True,True,True,True,True,True,True,True,downloaded,existing,...

Games with missing media this run
system,rom_name,missing_types
NES,Golden Sun - Dark Dawn (USA),wheel;background;video;title;theme;fade
```

The footer is omitted entirely on a clean run (nothing missing) or when the CSV was written without a `download_log` (e.g. plain `audit --report`).

---

## HyperSpin Files SpinDoctor Reads and Writes

These files live inside your cabinet directories. Cabinet write commands normally require `--apply`; backup and recovery behavior is command-specific. Read the [recovery guide](workflows.md#recovery-from-mistakes) before destructive operations. Downloaded media, generated files and the intro-video target do not all receive sidecar backups.

| File | Location | Read? | Written? |
|------|----------|-------|---------|
| HyperSpin game database | `hyperspin_dir\Databases\<System>\<System>.xml` | ✅ | ✅ (update-db, fav/recent/stats rebuild) |
| HyperSpin Settings INI | `hyperspin_dir\Settings\<System>.ini` | ✅ | ✅ (generate-config for video defaults) |
| HyperSpin wheel media | `hyperspin_dir\Media\<System>\Images\Wheel\<game>.png` | ✅ | ✅ (fetch-media, media-scan, fav rebuild) |
| RL per-system Emulators.ini | `rocketlauncher_dir\Settings\<System>\Emulators.ini` | ✅ | ✅ (generate-config) |
| RL Global Emulators.ini | `rocketlauncher_dir\Settings\Global Emulators.ini` | ✅ | ✅ (generate-config: creates if missing; replaces existing only with `--overwrite-global`) |
| RL play stats | `rocketlauncher_dir\Data\Statistics\<System>.ini` | ✅ | ✗ |
| PCLauncher per-game INI | `rocketlauncher_dir\Modules\PCLauncher\<System>\<Game>.ini` | ✅ | ✅ (pc-rename, fav/recent/stats rebuild) |
| PCLauncher system INI | `rocketlauncher_dir\Modules\PCLauncher\<System>.ini` | ✅ | ✅ (fav/recent/stats rebuild) |
| RocketLauncherGame.exe | `rocketlauncher_dir\RocketLauncherGame.exe` | ✗ | ✅ (fav/recent/stats rebuild — copy of RL.exe) |
| LEDBlinky Controls.ini | `ledblinky_dir\controls.ini` | ✅ | ✅ (ledblinky generate) |
| LEDBlinky Colors.ini | `ledblinky_dir\Colors.ini` | ✅ | ✅ (ledblinky generate, colors sync-players) |
| LEDBlinky Controls.xml | `ledblinky_dir\LEDBlinkyControls.xml` | ✅ | ✅ (ledblinky generate, fix) |
| LEDBlinky Settings.ini | `ledblinky_dir\Settings.ini` | ✅ | ✅ (ledblinky patch-settings) |
| Intro video pool | `intro_randomizer_dir\` (and its `Disabled\` subfolder) | ✅ | ✅ (introvideo add — copies in, never overwrites; remove/restore — moves between pool root and `Disabled\`, never deletes) |
| Intro video target | `intro_video_target` (e.g. `Intro.mp4`) | ✗ | ✅ (introvideo swap — overwritten on every swap, by design) |
| Intro-swap launcher bat/vbs | next to the frozen exe, or `~/.spindoctor/` for source installs | ✗ | ✅ (introvideo install-autorun) |
| ROM files and folders | `roms_dir\<System>\` and other resolved ROM paths | ✅ | ✅ (rename/clone, curate, find-misplaced, organize/restructure, migrate; scope depends on command) |
| Generated LED animations | `<output_dir>\LEDBlinky\lwax\` for fade/calibrate; Downloads pattern folder for batch, unless overridden | ✗ | ✅ (`ledblinky lwax ... --apply`; unsigned output requires manual signing) |

---

## Executables and destructive operations

SpinDoctor does not patch the executable contents of RocketLauncher or your emulators. `RocketLauncherGame.exe` is a separate copy of `RocketLauncher.exe`. Backup, migration and restore can still copy, move or replace whole emulator/RocketLauncher trees.

ROMs are **not read-only** to SpinDoctor: curation can permanently delete them, and rename, restructure and migration can move them. Animation generators also write files, and the batch generator refreshes its output directory. Keep backups outside the affected trees and inspect each dry-run plan.

---

## Example Directory Tree

```
C:\Users\<YourWindowsUsername>\.spindoctor\    ← SpinDoctor app data (always here)
├── config.json                         ← main settings
├── favorites.json                      ← cross-system Favorites store
├── gui.lock                            ← GUI single-instance lock (auto-released)
├── scraper.log                         ← API request log (current)
├── scraper.log.1                       ← API request log (previous rotation)
├── scraper.log.2                       ← API request log (oldest rotation)
├── metadata_cache\                     ← scraped metadata cache (30-day TTL)
│   ├── screenscraper\<System>\*.json
│   ├── thegamesdb\<System>\*.json
│   └── combined\<System>\*.json
├── match_cache\                        ← manual match decisions
│   └── <System>.json
├── media_pick_cache\                   ← media-asset picks from fetch-media
├── pc_titles_cache\                    ← confirmed PC/Steam display titles
├── mame_listxml_cache\                 ← MAME listxml cache (auto-invalidated)
│   └── mame-<hash>.xml                 ← one per MAME exe; old <System>.xml copies: spindoctor cleanup
├── ledblinky_library\                  ← preserved pruned entries; keep backed up
│   ├── controls.ini
│   ├── Colors.ini
│   └── community-controls.ini         ← when a community copy is available
├── curation\                           ← undo manifests: curate --action archive
├── edits\                              ← undo manifests: batch-edit
├── renames\                            ← undo manifests: rename / clone
├── migrations\                         ← undo manifests: migrate
├── media_imports\                      ← undo manifests: media-scan
└── themes\                             ← theme-apply manifests + file backups

C:\SpinDoctor\                          ← SpinDoctor output (configured in config.json)
├── output\                             ← selected generated output and saved logs
├── backups\                            ← timestamped .bak files
│   ├── HyperSpin\
│   ├── LEDBlinky\
│   └── RocketLauncher\
├── temps\                              ← optional same-filesystem atomic write staging
└── audits\                             ← auto-exported audit CSVs
    └── audit_YYYYMMDD_HHMMSS.csv

D:\Arcade\                              ← HyperSpin root (hyperspin_dir)
├── Databases\<System>\<System>.xml     ← SpinDoctor reads + writes
├── Media\<System>\Images\Wheel\        ← SpinDoctor reads + writes
├── Settings\<System>.ini               ← SpinDoctor reads + writes (video defaults)
└── RocketLauncher\
    ├── RocketLauncherGame.exe          ← SpinDoctor creates (copy of RocketLauncher.exe)
    ├── Settings\Global Emulators.ini   ← creates if missing; --overwrite-global permits replacement
    ├── Settings\<System>\Emulators.ini ← SpinDoctor reads + writes
    ├── Data\Statistics\<System>.ini    ← SpinDoctor reads only (play stats)
    └── Modules\PCLauncher\             ← SpinDoctor reads + writes
        ├── <System>.ini                ← system-level PCLauncher config
        └── <System>\<Game>.ini         ← per-game PCLauncher config / placeholder
```
