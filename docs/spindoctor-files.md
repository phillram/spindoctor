# SpinDoctor Files and Storage Locations

This document lists every file and directory SpinDoctor creates or manages, where it lives, and what it is for.

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
```

---

## Config Directory — `%USERPROFILE%\.spindoctor\`

Everything in this directory is created and managed by SpinDoctor. None of these files are read by HyperSpin, RocketLauncher, or any other cabinet software.

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

**Passwords and API keys are always redacted (`***`) before writing.** The log is safe to share with maintainers.

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
│   └── Nintendo Gamecube\
│       ├── Animal_Crossing__USA_.json
│       ├── Baten_Kaitos_-_Eternal_Wings.json
│       └── ...
├── thegamesdb\
│   └── Nintendo Gamecube\
│       └── ...
└── combined\
    └── ...
```

Each file is a JSON object with a `cached_at` timestamp. Entries older than `metadata_cache_ttl_days` (default: 30 days) are silently skipped on next read and a fresh API call is made.

**Management commands:**

```bat
spindoctor fetch-meta --no-cache           :: bypass cache for this run only
spindoctor fetch-meta --clear-cache        :: wipe all cached entries for the system
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

**Cache of MAME's `-listxml` output.** Used by `spindoctor ledblinky generate` to build `controls.ini` without running `mame -listxml` on every invocation (it takes 10–20 seconds for large MAME builds).

```
%USERPROFILE%\.spindoctor\mame_listxml_cache\
└── MAME.xml         :: raw listxml output, one file per MAME system name
```

The cache is automatically invalidated when the MAME executable is newer than the cached file (modification time comparison). Safe to delete — SpinDoctor will regenerate on next `ledblinky generate` run.

### Other caches

| Path | What it holds | Safe to delete? |
|------|---------------|-----------------|
| `media_pick_cache\` | Media-asset selections you made during `fetch-media` (one JSON per system) | Yes — you'll just be asked again |
| `pc_titles_cache\` | Confirmed display titles from `add-pc-system` / `pc-rename` title review (one JSON per system) | Yes — the review re-prompts on the next run |

Both are also covered by `spindoctor cleanup run` (categories `media-pick-cache` and `pc-titles-cache`).

### `favorites.json`

**The cross-system Favorites store** — one `(system, rom_name)` pair per favorited game. Read and written by `spindoctor fav add / remove / sync / rebuild / clear` and the GUI's Custom Wheels tab. Deleting it empties your Favorites (the generated wheel itself lives in the HyperSpin tree and is rebuilt by `fav rebuild --apply`). See [Commands → Custom wheels](commands.md#custom-wheels).

### `gui.lock`

**The GUI's single-instance lock.** Taken on `spindoctor-gui` startup so two windows can't write the same HyperSpin XML simultaneously; released automatically when the process exits, including after a crash. See [Troubleshooting → Install / startup](troubleshooting.md#install--startup).

### Undo manifest directories

Every destructive command records what it changed as a JSON manifest so `--undo` can reverse it. Most manifests live in per-category folders here:

| Directory | Written by |
|-----------|-----------|
| `curation\` | `curate --apply --action archive` |
| `edits\` | `batch-edit --apply` |
| `renames\` | `rename` / `clone --apply` |
| `migrations\` | `migrate --apply` |
| `media_imports\` | `media-scan --apply` |
| `themes\` | `theme-apply --apply` (manifest + a `backup\` mirror of every overwritten file) |

Two commands write their manifests into the ROM tree instead, next to the files they moved: `find-misplaced --apply` (`_spindoctor-misplaced-<stamp>.json` at the `roms_dir` root) and `organize --restructure --apply` (`_spindoctor-restructure-<stamp>.json` inside the system's ROM folder).

Manifests are small and are never deleted automatically — they are the undo path. The full command ↔ manifest ↔ undo map is at [Workflows → Recovery from mistakes](workflows.md#recovery-from-mistakes); `spindoctor cleanup run` can prune old ones once you're sure you won't roll back.

---

## Output Directories (configured in `config.json`)

These are **not** inside `%USERPROFILE%\.spindoctor\`. They live wherever you point the relevant config keys.

### `output_dir`

Example: `C:\SpinDoctor\output\`. Staging directory for files SpinDoctor generates before `--apply` commits them. Most commands write directly to their target (in-place) with atomic rename — `output_dir` is used only by commands that explicitly accept `--output-dir`.

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

Example: `C:\SpinDoctor\temps\`. Scratch area for the `.tmp` files written during atomic XML/JSON saves. **Must be on the same drive as your HyperSpin directory** — cross-drive atomic rename is not possible on Windows; SpinDoctor silently falls back to `target.parent` if it detects a drive mismatch.

If not configured, `.tmp` files land next to their targets inside the HyperSpin tree (safe but clutters the folders).

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

These files live inside your HyperSpin / RocketLauncher directories. SpinDoctor writes them only when `--apply` is passed and backs them up first.

| File | Location | Read? | Written? |
|------|----------|-------|---------|
| HyperSpin game database | `hyperspin_dir\Databases\<System>\<System>.xml` | ✅ | ✅ (update-db, fav/recent/stats rebuild) |
| HyperSpin Settings INI | `hyperspin_dir\Settings\<System>.ini` | ✅ | ✅ (generate-config for video defaults) |
| HyperSpin wheel media | `hyperspin_dir\Media\<System>\Images\Wheel\<game>.png` | ✅ | ✅ (fetch-media, media-scan, fav rebuild) |
| RL per-system Emulators.ini | `rocketlauncher_dir\Settings\<System>\Emulators.ini` | ✅ | ✅ (generate-config) |
| RL Global Emulators.ini | `rocketlauncher_dir\Settings\Global Emulators.ini` | ✅ | ✅ (generate-config, only if missing) |
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

---

## Files SpinDoctor Never Touches

SpinDoctor reads these but will **never write or delete** them:

- `RocketLauncher.exe` — never modified; `RocketLauncherGame.exe` is created as a separate copy
- `Global Emulators.ini` — only written if the file does not exist at all
- HyperSpin ROM files in `roms_dir`
- Emulator executables in `emulators_dir`
- LEDBlinky animation files (`.lwa`, `.lwax`)

---

## Full Directory Tree (this cabinet)

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
│   └── MAME.xml
├── curation\                           ← undo manifests: curate --action archive
├── edits\                              ← undo manifests: batch-edit
├── renames\                            ← undo manifests: rename / clone
├── migrations\                         ← undo manifests: migrate
├── media_imports\                      ← undo manifests: media-scan
└── themes\                             ← theme-apply manifests + file backups

C:\SpinDoctor\                          ← SpinDoctor output (configured in config.json)
├── output\                             ← generated files staging area
├── backups\                            ← timestamped .bak files
│   ├── HyperSpin\
│   ├── LEDBlinky\
│   └── RocketLauncher\
├── temps\                              ← atomic write staging (must be same drive as HyperSpin)
└── audits\                             ← auto-exported audit CSVs
    └── audit_YYYYMMDD_HHMMSS.csv

D:\Arcade\                              ← HyperSpin root (hyperspin_dir)
├── Databases\<System>\<System>.xml     ← SpinDoctor reads + writes
├── Media\<System>\Images\Wheel\        ← SpinDoctor reads + writes
├── Settings\<System>.ini               ← SpinDoctor reads + writes (video defaults)
└── RocketLauncher\
    ├── RocketLauncherGame.exe          ← SpinDoctor creates (copy of RocketLauncher.exe)
    ├── Settings\Global Emulators.ini   ← SpinDoctor reads; writes only if missing
    ├── Settings\<System>\Emulators.ini ← SpinDoctor reads + writes
    ├── Data\Statistics\<System>.ini    ← SpinDoctor reads only (play stats)
    └── Modules\PCLauncher\             ← SpinDoctor reads + writes
        ├── <System>.ini                ← system-level PCLauncher config
        └── <System>\<Game>.ini         ← per-game PCLauncher config / placeholder
```
