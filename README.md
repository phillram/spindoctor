# SpinDoctor 🩺🕹️

**SpinDoctor** is a command-line tool for managing your [HyperSpin](http://www.hyperspin-fe.com/) and [RocketLauncher](https://rocketlauncher.net/) arcade cabinet library.

Audit ROMs, sync HyperSpin XML databases, fetch metadata and media, generate RocketLauncher configs, validate ROM integrity against No-Intro / Redump DATs, manage cross-system Favorites and Recently Played wheels, and more — all from a single CLI with dry-run mode and a non-destructive output directory option.

---

## Table of Contents

- [Installation](#installation)
- [First-Time Setup](#first-time-setup)
- [Configuration](#configuration)
- [Commands](#commands)
  - [Core library](#core-library) — `systems`, `audit`, `inspect`, `update-db`, `fetch-meta`, `fetch-media`, `media-add`, `report`
  - [Library generation](#library-generation) — `generate-config`, `mainmenu`, `organize`, `add-system`, `add-pc-system`, `pc-rename`, `migrate`, `backup`
  - [Health & integrity](#health--integrity) — `find-dupes`, `find-misplaced`, `curate`, `find-orphan-media`, `check-discs`, `verify`, `stats`
  - [Custom wheels](#custom-wheels) — `fav`, `recent`, `install-tools`
  - [LEDBlinky](#ledblinky)
  - [Maintenance](#maintenance) — `doctor`, `ignore`, `match`, `lint`
- [Standalone scripts](#standalone-scripts) — `spindoctor-fav`, `spindoctor-recent`
- [Directory structure expected](#directory-structure-expected)
- [ROM variant handling](#rom-variant-handling)
- [Typical workflows](#typical-workflows)
- [FAQ](#faq)

---

## Installation

**Requirements:** Python 3.9+

```bat
cd C:\path\to\spindoctor
pip install -e .
```

Optional but recommended: install with the `[xml]` extra so XML databases round-trip losslessly (preserves comments and attribute order from HyperHQ).

```bat
pip install -e .[xml]
```

Verify:

```bat
spindoctor --version
```

This installs three console scripts:

| Command | Purpose |
|---------|---------|
| `spindoctor` | Full CLI |
| `spindoctor-fav` | Standalone Favorites wheel manager (no `spindoctor` CLI required) |
| `spindoctor-recent` | Standalone Recently Played rebuild (no `spindoctor` CLI required) |

---

## First-Time Setup

Run the interactive wizard once. It prompts for every path-based setting (ROMs, HyperSpin, Emulators, RocketLauncher, LEDBlinky, MAME, default output, audit export) with sensible Windows defaults pre-filled. Press Enter to accept, type `-` to leave an optional path blank.

```bat
spindoctor config init
```

Settings are saved to `%USERPROFILE%\.spindoctor\config.json`. Re-running the wizard uses your existing values as defaults, so it's safe to refine later.

---

## Configuration

Show or change individual values:

```bat
spindoctor config show
spindoctor config set <key> <value>
```

**Most-used keys:**

| Key | Description |
|-----|-------------|
| `roms_dir` | Root folder with one sub-folder per system |
| `hyperspin_dir` | Root HyperSpin folder (contains `Databases/` and `Media/`) |
| `emulators_dir` | Root folder with one sub-folder per emulator |
| `rocketlauncher_dir` | Root RocketLauncher folder |
| `ledblinky_dir` | LEDBlinky install directory |
| `output_dir` | Default output folder (blank = write in-place) |
| `auto_audit_export_dir` | Auto-export an audit CSV here after every write operation |
| `screenscraper_user` / `screenscraper_pass` | ScreenScraper credentials |
| `thegamesdb_key` | TheGamesDB API key |
| `default_metadata_source` | `screenscraper` or `thegamesdb` |
| `match_threshold` | Fuzzy auto-accept confidence, `0.0`–`1.0` (default `0.80`) |
| `interactive_matching` | Prompt on ambiguous matches (default `true`) |
| `mame_executable` | Path to MAME (used by `ledblinky generate`) |
| `metadata_cache_ttl_days` | Days to keep cached scraper responses (default `30`) |

**Per-system overrides** let you teach SpinDoctor about a system it doesn't know natively (custom emulators, unusual extensions, alternative scraper IDs):

```bat
spindoctor config system set "Sony Playstation 7" ^
    --screenscraper-id 999 ^
    --rom-extensions ps7,iso ^
    --layout per-game-folder ^
    --emulator RPCS7

spindoctor config system list
spindoctor config system clear "Sony Playstation 7"
```

---

## Commands

### Core library

#### `systems`

List every system detected across `roms_dir` and `Databases/`.

```bat
spindoctor systems
```

#### `audit`

Compare ROM files against the HyperSpin database and media assets. Reports exact + fuzzy matches, ROMs without DB entries, DB entries without ROMs, incomplete metadata, missing media, and ignored counts.

```bat
spindoctor audit --system MAME
spindoctor audit --all --no-media
spindoctor audit --all --report D:\audit_report.csv
spindoctor audit --system MAME --detailed   :: append per-file dimensions/sizes
```

#### `inspect`

Per-file deep-dive for a single game or every game with issues in a system. Shows the ROM file, every media slot, image dimensions, video length, and modification times.

```bat
spindoctor inspect --system MAME --game 1942
spindoctor inspect --system SNES --no-path                  :: compact view
spindoctor inspect --system MAME --all --format csv --output D:\manifest.csv
```

#### `update-db`

Sync HyperSpin XML databases to match the ROM directories — adds stub entries for new ROMs, optionally removes orphan entries.

```bat
spindoctor update-db --system MAME --dry-run
spindoctor update-db --all --remove-orphans --output-dir D:\Output
spindoctor update-db --system SNES --strip-variant-tags     :: collapse "(Japan)"/"(USA)" displays
```

A `.YYYYMMDD_HHMMSS.bak` is saved before in-place writes (toggle via `backup_before_modify`).

#### `fetch-meta`

Download metadata (description, year, manufacturer, genre, rating) and write it into the XML.

```bat
spindoctor fetch-meta --system MAME --dry-run
spindoctor fetch-meta --all --output-dir D:\Output
spindoctor fetch-meta --all --auto-best          :: never prompt — pick top result
spindoctor fetch-meta --system SNES --all-games  :: refresh complete entries too
```

API responses are cached at `~/.spindoctor/metadata_cache/`. TTL via `metadata_cache_ttl_days`. Pass `--no-cache` for a one-shot fresh run, or `--clear-cache` to wipe.

When multiple results match, the picker prompts you (or use `--auto-best`). Choices are cached at `~/.spindoctor/match_cache/<system>.json` so re-runs are silent.

#### `fetch-media`

Download wheels, backgrounds, snaps, videos, etc. for games in the database.

```bat
spindoctor fetch-media --system MAME --types wheel,background --dry-run
spindoctor fetch-media --all --output-dir D:\Output
spindoctor fetch-media --system SNES --types trailer --overwrite
```

Concurrency is controlled by `max_concurrent_downloads`. The downloader retries on HTTP 429/503, honouring `Retry-After`.

#### `media-add`

Manually drop a local file into the right HyperSpin media slot.

```bat
spindoctor media-add --system MAME --game 1942 --type trailer ^
    --file C:\Downloads\1942_trailer.mp4
spindoctor media-add --system SNES --game "Super Mario World" ^
    --type title --file C:\Art\smw_title.png --move
```

#### `report`

Read-only summary or CSV — never modifies anything.

```bat
spindoctor report --all --format summary
spindoctor report --all --format csv --output D:\weekly.csv
```

---

### Library generation

#### `generate-config`

Generate RocketLauncher INI files and the HyperSpin Main Menu XML.

```bat
spindoctor generate-config --dry-run
spindoctor generate-config --output-dir D:\Output
spindoctor generate-config --no-rl                 :: only regenerate the main menu
spindoctor generate-config --db-stubs              :: also create empty DB stubs
```

Emulators are guessed from the system name (MAME → MAME, SNES → RetroArch, N64 → Project64, PS2 → PCSX2, etc.). Edit the generated INIs to override.

#### `mainmenu`

Inspect and edit the HyperSpin Main Menu — the top-level wheel of systems shown when the cabinet boots. `generate-config` writes this file; `mainmenu` lets you review the order, hide systems you've stopped using, and add the ones you forgot.

```text
spindoctor mainmenu show

#   System                  Status    In Databases
1   MAME                    Visible   yes
2   Sony Playstation        Visible   yes
3   Nintendo 64             Hidden    yes
4   Atari Jaguar            Visible   ✗ missing

Systems found in Databases/ but not in the Main Menu:
  · Sega Saturn
  · Sega Dreamcast

Run `spindoctor mainmenu add <system>` to include them.
```

All write commands are dry-run by default — pass `--apply` to commit. Each write makes a `.YYYYMMDD_HHMMSS.bak` of `Main Menu.xml` first (when `backup_before_modify` is on).

```bat
:: Re-order systems
spindoctor mainmenu reorder "Nintendo 64" 1 --apply
spindoctor mainmenu up "Sony Playstation" --apply
spindoctor mainmenu down MAME --apply

:: Hide a system from the wheel without deleting its database
spindoctor mainmenu hide "Atari Jaguar" --apply
spindoctor mainmenu show "Atari Jaguar" --apply       :: un-hide

:: Add or remove an entry
spindoctor mainmenu add "Sega Saturn" --apply
spindoctor mainmenu remove "Atari Jaguar" --apply

:: Bulk sort the menu
spindoctor mainmenu sort alpha --apply
spindoctor mainmenu sort manufacturer --apply
spindoctor mainmenu sort year --apply

:: Stage changes to a different folder instead of writing in place
spindoctor mainmenu reorder MAME 1 --apply --output-dir D:\Output
```

For larger reshuffles, use the interactive editor — it shows the numbered list, accepts commands like `up 3`, `move 3 to 1`, `hide 4`, `add Sega Saturn`, `remove 5`, and confirms before saving on `q`:

```bat
spindoctor mainmenu edit
```

#### `organize`

Populate per-axis sort wheels (genre/year/manufacturer/letter) and optionally restructure ROMs into per-game folders or multi-disc m3u playlists.

```bat
spindoctor organize "Sony Playstation"                         :: sort wheels only
spindoctor organize "Sony Playstation 3" --restructure         :: dry-run plan
spindoctor organize "Sony Playstation 3" --restructure --apply :: execute
spindoctor organize "Sony Playstation 3" --undo                :: revert last apply
```

#### `add-system`

Bootstraps a brand-new console end-to-end: registers it in the Main Menu, creates database stub, generates RocketLauncher INI, scaffolds media folders, and (optionally) walks the metadata + media fetch flow.

```bat
spindoctor add-system "Sega Saturn"
```

#### `add-pc-system`

The same as `add-system` but for PC / Windows / Steam libraries — handles recursive scanning of nested install folders, the title-picker for awkward layouts, and per-game PCLauncher INIs.

```bat
spindoctor add-pc-system "PC Games"
spindoctor pc-rename "PC Games"   :: re-run the title picker after dropping new games in
```

#### `migrate`

Move (or copy) the entire library — or just specific parts — to a new drive in one shot. Updates `~/.spindoctor/config.json` with the new paths and writes a manifest you can undo.

The components map directly to your config paths:

| Component | What moves | Default subfolder at target | Config field updated |
|-----------|------------|------------------------------|----------------------|
| `roms` | `roms_dir` (every system folder) | `Games/` | `roms_dir` |
| `hyperspin` | `hyperspin_dir` (Databases + Media) | `HyperSpin/` | `hyperspin_dir` |
| `emulators` | `emulators_dir` | `Emulators/` | `emulators_dir` |
| `rocketlauncher` | `rocketlauncher_dir` | `RocketLauncher/` | `rocketlauncher_dir` |
| `ledblinky` | `ledblinky_dir` | `LEDBlinky/` | `ledblinky_dir` |
| `all` | every component above | all of the above | every field above |

The default subfolder is `Games/` (not `ROMs/`) because the same folder also holds non-ROM titles — PC games, Steam shortcuts, multi-disc folders, and so on.

Aliases for convenience: `games` → `roms`, and `media` / `data` / `databases` all → `hyperspin` (because the Databases and Media folders both live inside `hyperspin_dir` and travel together).

**Dry-run is the default.** Pass `--apply` to actually move anything.

```bat
:: 1. See what would move (every component, dry-run)
spindoctor migrate --target E:\NewCab

:: 2. Move the whole library and update config in one shot
spindoctor migrate --target E:\NewCab --apply

:: 3. Move only specific components
spindoctor migrate --target E:\NewCab --include roms,hyperspin --apply
spindoctor migrate --target E:\NewCab --include games,media --apply        :: same thing, aliases
spindoctor migrate --target E:\NewCab --include emulators --apply

:: 4. Move only specific systems' ROMs to the new drive (split-library mode)
spindoctor migrate --target E:\NewCab --include roms ^
    --systems "MAME,Sony Playstation 3" --apply
```

**Per-system ROM moves:** when `--systems` is set, only those system folders move. `roms_dir` is left pointing at the original drive, since the library is being split. Symlink the moved folders back under the original `roms_dir` if you want SpinDoctor to keep finding them in one place — or run `spindoctor config set roms_dir E:\NewCab\Games` afterwards if you'd rather flip everything over.

**Preserve original folder names:**

By default the migration normalizes folder names at the target (`ROMs/`, `HyperSpin/`, `Emulators/`, etc.). Pass `--preserve-names` to keep each component's original top-level folder name instead — useful if you've already settled on a folder layout you like and don't want SpinDoctor to rename anything.

```bat
:: Source layout                       Target layout
::   D:\MyArcade\GameFiles\              E:\NewCab\GameFiles\        (preserved)
::   D:\MyArcade\HS\                     E:\NewCab\HS\               (preserved)
spindoctor migrate --target E:\NewCab --apply --preserve-names

:: vs. default (standardized):
::   D:\MyArcade\GameFiles\  →  E:\NewCab\Games\
::   D:\MyArcade\HS\         →  E:\NewCab\HyperSpin\
```

If two components have folders with the same basename (e.g. both `roms_dir` and `emulators_dir` end in `\Cab`), `--preserve-names` skips the second one and prints a clear message — drop the flag or rename one of the source folders.

**Safer "copy then delete by hand" workflow:**

```bat
:: Copy without deleting the originals, and SHA1-verify every file afterwards.
spindoctor migrate --target E:\NewCab --apply --keep-source --verify
```

`--keep-source` leaves the original intact and skips the config rewrite, so you can keep the old drive plugged in as a hot spare until you're confident the new one works. Once you're happy, delete the old folders by hand and update the config: `spindoctor config set roms_dir E:\NewCab\ROMs` (and so on per component).

**Reverse a migration:**

```bat
spindoctor migrate --list-manifests        :: show every migration on disk
spindoctor migrate --undo latest           :: reverse the most recent one
spindoctor migrate --undo C:\Users\you\.spindoctor\migrations\migrate-20260427_213345.json
```

Undo moves the files back, restores the previous config snapshot, and deletes the manifest. For `--keep-source` migrations, undo just removes the copied destinations (your originals were never touched).

**Other useful flags:**

| Flag | Purpose |
|------|---------|
| `--preserve-names` | Keep each component's original top-level folder name at the target instead of using `Games/`, `HyperSpin/`, etc. |
| `--no-update-config` | Skip the config rewrite even on a real move (e.g. when you're scripting and want to flip paths yourself) |
| `--include hyperspin,emulators` | Multi-component selection — comma-separated list |
| `--target` | Required unless using `--undo` or `--list-manifests` |

The pre-flight plan tells you total bytes to transfer and free space at the target, and aborts the apply if there isn't enough room.

---

### Health & integrity

These commands surface issues in your library without making changes (unless you opt in).

#### `find-dupes`

Detect duplicate ROMs within a system or across systems.

```bat
spindoctor find-dupes --system MAME
spindoctor find-dupes --all --cross-systems         :: same title in multiple folders
spindoctor find-dupes --system NES --by-content     :: SHA1 match (catches renamed copies)
```

Two ROMs are duplicates by default when their stems collapse to the same normalised title (region/version tags stripped). `--by-content` adds byte-level pairing.

#### `find-misplaced`

Flag ROMs whose extension doesn't match the folder's system (e.g. a `.nes` inside `snes/`). Generic containers (`.zip`, `.iso`, `.bin`) are skipped because they're ambiguous.

```bat
spindoctor find-misplaced --all                  :: report only
spindoctor find-misplaced --system snes --apply  :: move each to its suggested system
spindoctor find-misplaced --undo                 :: reverse the most recent --apply
```

`--apply` writes a manifest so the move can be undone in one command.

#### `curate` — region & version curation

Where `find-dupes` only reports collisions, `curate` actively picks one canonical variant per game (by region preference and revision number) and groups the rest as retirement candidates. Use it to thin a No-Intro set down to one ROM per title without manually clicking through each duplicate.

```bat
spindoctor curate --system NES                            :: dry-run
spindoctor curate --all --regions USA,Japan               :: override preferences
spindoctor curate --system NES --apply                    :: archive losers to _retired/
spindoctor curate --system NES --apply --action delete --yes
spindoctor curate --undo                                  :: reverse the last archive
spindoctor curate --list-manifests
```

Selection rules, in order: exclude prototypes/demos/betas (pass `--include-proto` to keep them), pick the highest-priority region from the preferences list, prefer the latest revision (`--prefer-revision oldest` to invert), tiebreak by filename. Default preferences come from `config.region_preferences` — `["USA", "World", "Europe", "Japan"]` out of the box. `--apply --action archive` moves retired ROMs to `<roms_dir>/<system>/_retired/` and writes a manifest under `~/.spindoctor/curation/`; `--undo` reverses the most recent one. `--action delete` is permanent and has no undo.

#### `find-orphan-media`

Wheels, snaps, videos, and themes whose game no longer exists in the database or ROMs. `--delete` removes them after a confirmation prompt.

```bat
spindoctor find-orphan-media --all
spindoctor find-orphan-media --system SNES --delete
```

#### `check-discs`

Validate multi-disc layouts: every `(Disc N)` file has its `(Disc 1..N-1)` siblings, and every `.m3u` line resolves to a real file.

```bat
spindoctor check-discs --system "Sony Playstation"
spindoctor check-discs --all
```

#### `verify`

Verify ROM file integrity against a No-Intro / Redump / TOSEC DAT XML. Each ROM is classified `good` / `renamed` / `bad` / `unknown`. Hashing is lazy — files whose size doesn't appear in the DAT skip hashing entirely.

```bat
spindoctor verify --system NES --dat C:\Dats\Nintendo - Nintendo Entertainment System.dat
spindoctor verify --system NES --dat ... --show-good   :: also list verified-good files
```

| Status | Meaning |
|--------|---------|
| `good` | Hash + filename match the DAT |
| `renamed` | Hash matches but filename differs (DAT calls it something else) |
| `bad` | Size matches a known entry but hashes don't — likely a bad dump |
| `unknown` | DAT doesn't list anything of this size — homebrew, hack, or unsupported |

#### `stats`

Coverage dashboard: % ROMs matched to DB, % metadata complete, % media complete, plus the most commonly missing media types.

```bat
spindoctor stats
spindoctor stats --system MAME
```

---

### Custom wheels

Two synthetic HyperSpin systems — **Favorites** and **Recently Played** — that pull entries from any number of source systems into a single wheel. Each entry routes back through RocketLauncher so the original emulator config (cores, overlays, controls, savestates) is reused.

#### `fav` — cross-system Favorites

State lives in `~/.spindoctor/favorites.json` as `(system, rom_name)` pairs. Re-running `rebuild` is idempotent — safe to run on every boot.

```bat
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav add "Sony Playstation" "Final Fantasy VII" --display-name "FF VII"
spindoctor fav remove "Super Nintendo" "Chrono Trigger"
spindoctor fav list
spindoctor fav sync       :: pull HyperSpin's per-system F-key favorites into the store
spindoctor fav rebuild    :: regenerate Databases/Favorites/Favorites.xml + media + launchers
spindoctor fav rebuild --media-mode copy   :: force file copies (for FAT32 thumb drives)
```

`--media-mode` accepts `auto` (default — hardlink, fall back to copy), `link`, `symlink`, `copy`, or `none` (skip media mirroring).

When two source systems both contain a game with the same ROM name (e.g. `Tetris` on SNES and Game Boy), the wheel labels them `Tetris (Super Nintendo)` and `Tetris (Game Boy)` automatically.

#### `recent` — Recently Played

Reads RocketLauncher's `Statistics.ini` files (no extra hooks needed), keeps the most-recent N games across every system, and regenerates the wheel.

```bat
spindoctor recent rebuild                       :: top 20 (default)
spindoctor recent rebuild --limit 10
spindoctor recent rebuild --target-system "Last Played"
spindoctor recent list                          :: just print the current top-N
```

#### `install-tools`

Writes `.bat` wrappers HyperSpin's Tools menu can invoke directly — so users can refresh wheels from the cabinet UI without opening a console.

```bat
spindoctor install-tools                                :: write to RocketLauncher Tools dir
spindoctor install-tools --output-dir D:\Tools          :: write somewhere else
```

Three files are produced:

```
Refresh Favorites.bat          → calls spindoctor-fav rebuild
Refresh Recently Played.bat    → calls spindoctor-recent rebuild
Refresh Both.bat               → calls both
```

Register them in HyperHQ → Tools, or schedule them via Windows Task Scheduler (trigger: "At log on") to refresh on every boot.

---

### LEDBlinky

```bat
spindoctor ledblinky generate
spindoctor ledblinky audit
spindoctor ledblinky check     :: scan for HyperSpin Search-menu compatibility issues
spindoctor ledblinky fix       :: patch them (dry-run first with --dry-run)
```

`generate` builds `controls.ini` and `colors.ini` from MAME `-listxml`, preserving any community-maintained entries already present in `<ledblinky_dir>`.

`check` / `fix` diagnose and repair the well-known issue where HyperSpin's Search overlay crashes when LEDBlinky is installed:

1. LEDBlinky injects `Start_Hyperspin_Process` / `Exit_Hyperspin_Process` lines into per-menu `Settings.ini` — Search's overlay launcher doesn't tolerate them.
2. `LEDBlinkyControls.xml` has no entry for the Search special menu.

`fix` is reversible: timestamped `.bak` backups are saved next to every modified file, and disabled lines are commented out (not deleted), tagged so you can find them later.

```bat
spindoctor ledblinky fix --menus Search,Genre,Favorites
spindoctor ledblinky fix --output-dir D:\SpinDoctorOutput   :: stage instead of in-place
```

The global `<hyperspin_dir>/Settings/Settings.ini` is never touched — LEDBlinky needs those hooks during gameplay.

---

### Maintenance

#### `doctor`

Self-diagnose your install: paths, binaries, XML DB integrity, match-cache hygiene, RocketLauncher / LEDBlinky files, optional `lxml`, `ffprobe`. Each check renders ✓ / ⚠ / ✗.

```bat
spindoctor doctor
spindoctor doctor --fix    :: prune stale cache entries, create media folder skeletons, etc.
```

`--fix` only does safe, idempotent repairs.

#### `ignore`

Per-system or global ignore lists. Ignored games are skipped by `audit`, `fetch-meta`, `fetch-media`, and `update-db`.

```bat
spindoctor ignore add "pacman"                          :: global
spindoctor ignore add "Mario (hack)" --system NES
spindoctor ignore list
spindoctor ignore remove "pacman"
spindoctor ignore clear --system MAME
```

#### `match`

Manage cached metadata-match decisions made interactively during `fetch-meta`.

```bat
spindoctor match list --system MAME
spindoctor match clear --system MAME
```

#### `cleanup`

One-stop inventory and removal of every cache, manifest, temp dir, and `.bak` backup SpinDoctor produces. Categories cover match / media-pick / pc-titles / metadata / MAME-listxml caches, the preview temp dir, audit-CSV exports, restructure / misplaced / migration manifests, and HyperSpin / LEDBlinky `.bak` files.

```bat
:: See what categories exist and which are flagged unsafe to delete
spindoctor cleanup categories

:: Audit disk usage by category
spindoctor cleanup audit
spindoctor cleanup audit --detail
spindoctor cleanup audit -c metadata-cache -c db-backups

:: Dry-run by default — re-run with --apply to actually delete
spindoctor cleanup run --include safe
spindoctor cleanup run --include metadata-cache,match-cache --apply

:: Time-window and quota filters
spindoctor cleanup run --include metadata-cache --older-than 90 --apply
spindoctor cleanup run --include db-backups --keep-recent 5 --apply

:: Wipe everything (caches + backups + undo manifests)
spindoctor cleanup run --include all --include-unsafe --apply --prune-empty-dirs
```

`safe` covers the regenerable caches and audit exports; `db-backups`, `migration-manifests`, and `restructure-manifests` are flagged unsafe — naming them in `--include` is an explicit opt-in. Use `--prune-empty-dirs` to collapse now-empty cache folders after deletion, and `--yes` to skip the final confirmation prompt for scripted runs.

#### `lint`

AST pass over the SpinDoctor source itself — surfaces unused imports, bare `except:`, TODO markers, and near-duplicate function bodies. Useful as a pre-commit sanity check if you fork or modify SpinDoctor.

```bat
spindoctor lint
spindoctor lint --category unused-import,bare-except
```

---

## Standalone scripts

Both wheel rebuilds are designed to run on every system boot or directly from HyperSpin's Tools menu, with **no SpinDoctor CLI loaded**. They share `~/.spindoctor/config.json` with the main `spindoctor` command but use a minimal `argparse`-based entry point.

The standalone helpers live in their own folder, separate from the rest of the package, so it's clear which files are package internals vs. things the cabinet end-user is meant to invoke directly:

```
scripts/
├── spindoctor-fav.py             ← Python wrapper (works without `pip install`)
├── spindoctor-recent.py          ← Python wrapper (works without `pip install`)
├── Refresh Favorites.bat         ← Drop into HyperSpin Tools or Windows Startup
├── Refresh Recently Played.bat   ← ditto
├── Refresh Both.bat              ← Run both in sequence
└── README.md                     ← Quick-start for the folder
```

After `pip install -e .` you can also call the entry-point console scripts (`spindoctor-fav` / `spindoctor-recent`) directly from any working directory — they're equivalent to running the wrappers in `scripts/`.

### `spindoctor-fav`

```
spindoctor-fav add SYSTEM ROM_NAME [--display-name NAME]
spindoctor-fav remove SYSTEM ROM_NAME
spindoctor-fav list
spindoctor-fav sync
spindoctor-fav rebuild [--media-mode {link,symlink,copy,auto,none}]
```

Equivalent to `spindoctor fav <subcommand>` but lighter and faster to launch — no rich/click overhead. Examples:

```bat
spindoctor-fav add "Super Nintendo" "Chrono Trigger"
spindoctor-fav rebuild
```

Or directly from a clone (no `pip install` needed):

```bat
python scripts\spindoctor-fav.py rebuild
python -m spindoctor.favorites rebuild     :: equivalent
```

### `spindoctor-recent`

```
spindoctor-recent rebuild [--limit N] [--target-system NAME]
                          [--media-mode {link,symlink,copy,auto,none}]
spindoctor-recent list
```

Examples:

```bat
spindoctor-recent rebuild --limit 20
python scripts\spindoctor-recent.py list
python -m spindoctor.recent list           :: equivalent
```

### Wiring into Windows startup

Run once on log-on so the wheels are fresh when the user reaches HyperSpin:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Refresh Wheels" ^
  /tr "cmd /c spindoctor-fav rebuild && spindoctor-recent rebuild"
```

Or drop one of the `.bat` files from `scripts/` (or those written by `spindoctor install-tools`) into the Windows Startup folder (`shell:startup`).

### Wiring into HyperSpin Tools menu

Two equivalent options:

1. **Auto-install:** `spindoctor install-tools` writes the three `.bat` files into `<RocketLauncher>/Modules/HyperLaunch/Tools/spindoctor/`.
2. **Manual:** copy the `.bat` files from `scripts/` into HyperSpin's Tools directory yourself.

Either way, register them in HyperHQ → Tools so they appear inside the cabinet UI as `Refresh Favorites`, `Refresh Recently Played`, and `Refresh Both`.

---

## Directory structure expected

```
roms_dir/
├── MAME/
│   ├── 1942.zip
│   ├── 1942 (Japan, Rev B).zip       ← treated individually
│   └── pacman.zip
├── Nintendo Entertainment System/
│   ├── Super Mario Bros (USA).nes
│   └── Super Mario Bros (USA, Rev 1).nes
└── ...

hyperspin_dir/
├── Databases/
│   ├── Main Menu/
│   │   └── Main Menu.xml             ← generated by generate-config
│   ├── MAME/
│   │   └── MAME.xml
│   ├── Favorites/                    ← generated by spindoctor fav rebuild
│   │   └── Favorites.xml
│   └── Recently Played/              ← generated by spindoctor recent rebuild
│       └── Recently Played.xml
└── Media/
    ├── MAME/
    │   ├── Images/{Wheel,Backgrounds,Artwork1,Artwork2,Artwork3}/
    │   ├── Video/{,Trailers}/
    │   ├── Sound/
    │   └── Themes/
    ├── Favorites/                    ← hardlinked / copied from source systems
    └── Recently Played/

rocketlauncher_dir/
├── Settings/{<System>.ini, Global Emulators.ini}
├── Settings/Global Statistics/<System>.ini   ← read by spindoctor recent
└── Modules/PCLauncher/{Favorites,Recently Played}/<game>.ini
```

### Media types

| Type | HyperSpin path | Description |
|------|---------------|-------------|
| `wheel` | `Images/Wheel/` | Transparent PNG logo |
| `background` | `Images/Backgrounds/` | Full-screen background |
| `artwork` | `Images/Artwork1/` | Box art |
| `title` | `Images/Artwork2/` | Title screen screenshot |
| `snap` | `Images/Artwork3/` | Gameplay screenshot |
| `video` | `Video/` | Attract / intro video |
| `trailer` | `Video/Trailers/` | Full trailer |
| `sound` | `Sound/` | Sound clip on game select |
| `theme` | `Themes/` | HyperSpin SWF/ZIP theme |

---

## ROM variant handling

Every ROM file is treated as an independent entry. `Super Mario Bros (USA, Rev 1).nes` and `Super Mario Bros (USA).nes` get separate database entries with separate display names, separate metadata fetches, and separate media slots.

By default the `<description>` keeps the variant tag so the two stay distinguishable in HyperSpin / RocketLauncher menus. Pass `--strip-variant-tags` to `update-db` (or set `strip_variant_tags_in_display_name true`) to collapse all variants of one game to a shared display name.

| ROM filename | Display name (default) | With `--strip-variant-tags` |
|---|---|---|
| `1942 (Japan)` | `1942 (Japan)` | `1942` |
| `1942 (USA)` | `1942 (USA)` | `1942` |
| `Super Mario Bros (USA, Rev 1)` | `Super Mario Bros (USA, Rev 1)` | `Super Mario Bros` |
| `super_mario_bros` | `Super Mario Bros` | `Super Mario Bros` |

Fuzzy matching (used by `audit` and `fetch-meta`) strips region/version/revision tags before comparing, so `1942 (Japan, Rev B)` matches the DB entry `1942` with high confidence.

---

## Metadata sources

### ScreenScraper (recommended)

[ScreenScraper](https://www.screenscraper.fr/) has the broadest arcade + console coverage and bundles media URLs.

```bat
spindoctor config set screenscraper_user your_username
spindoctor config set screenscraper_pass your_password
```

### TheGamesDB

```bat
spindoctor config set thegamesdb_key your_api_key
spindoctor config set default_metadata_source thegamesdb
```

---

## Typical workflows

### New cabinet build

```bat
spindoctor config init
spindoctor systems
spindoctor generate-config --dry-run
spindoctor generate-config --output-dir D:\SpinDoctorOutput
spindoctor update-db --all --output-dir D:\SpinDoctorOutput
spindoctor fetch-meta --all --output-dir D:\SpinDoctorOutput
spindoctor fetch-media --all --types wheel,background --output-dir D:\SpinDoctorOutput
```

### Health check

```bat
spindoctor stats
spindoctor doctor
spindoctor find-dupes --all
spindoctor find-misplaced --all
spindoctor find-orphan-media --all
spindoctor check-discs --all
```

### ROM integrity sweep

```bat
spindoctor verify --system NES --dat "C:\Dats\Nintendo - NES - No-Intro.dat"
spindoctor verify --system "Sony Playstation" --dat "C:\Dats\Sony - PS - Redump.dat"
```

### Adding a Favorite

```bat
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav rebuild
```

After this the cabinet user sees Chrono Trigger inside the new `Favorites` system in HyperSpin, with its original SNES wheel art and snap mirrored across.

### Migrating to a new drive

```bat
:: 1. Plug in the new drive (e.g. E:) and dry-run the plan.
spindoctor migrate --target E:\Cab

:: 2. (Recommended) Copy first, verify hashes, keep the originals as a fallback.
spindoctor migrate --target E:\Cab --apply --keep-source --verify

:: 3. Smoke-test the cabinet from the new drive — point the config at it.
spindoctor config set roms_dir E:\Cab\Games
spindoctor config set hyperspin_dir E:\Cab\HyperSpin
spindoctor config set emulators_dir E:\Cab\Emulators
spindoctor config set rocketlauncher_dir E:\Cab\RocketLauncher
spindoctor doctor

:: 4. Once the new drive looks good, delete the old folders by hand.
::    Or skip steps 2–3 and do a one-shot move that updates config automatically:
spindoctor migrate --target E:\Cab --apply

:: To keep the old folder names (e.g. you had D:\MyArcade\GameFiles instead of
:: D:\Old\ROMs and prefer it stays "GameFiles" on the new drive too):
spindoctor migrate --target E:\Cab --apply --preserve-names
```

If something goes wrong, `spindoctor migrate --undo latest` puts everything back where it was and restores the previous config.

#### `backup`

Copy any combination of library components into a dated backup folder on a different drive — and restore it later, in full or in part. Useful before risky operations (drive migration, big metadata refresh) or as a periodic safety net.

Components are à la carte — pick exactly what you want to preserve:

| Component | What it covers | Default subfolder in the backup |
|-----------|---------------|---------------------------------|
| `roms` (alias `games`) | `roms_dir` (every system folder) | `Games/` |
| `databases` (alias `db`, `data`) | `<hyperspin_dir>/Databases/` | `HyperSpin/Databases/` |
| `media` | `<hyperspin_dir>/Media/` (wheels, snaps, video, themes) | `HyperSpin/Media/` |
| `emulators` | `emulators_dir` | `Emulators/` |
| `rocketlauncher` (alias `rl`) | `rocketlauncher_dir` | `RocketLauncher/` |
| `ledblinky` (alias `led`) | `ledblinky_dir` | `LEDBlinky/` |
| `settings` (alias `config`) | `~/.spindoctor/` (config, favorites, ignore lists, caches) | `Settings/` |
| `all` | every component above | all of the above |

Composite alias `hyperspin` (also `hs`) expands to `databases,media`.

Each backup lives at `<target>/spindoctor-backup-YYYYMMDD_HHMMSS[-LABEL]/` and contains a `manifest.json` describing what was copied and where it came from. Backups are plain folders — you can browse, copy, or zip them with any file explorer.

**Dry-run is the default.** Pass `--apply` to actually copy.

```bat
:: 1. See what a full backup would copy
spindoctor backup create --target E:\Backups

:: 2. Full backup of everything
spindoctor backup create --target E:\Backups --apply

:: 3. Just the small stuff: settings + databases (no huge media folder)
spindoctor backup create --target E:\Backups --include settings,databases --apply

:: 4. Just games and media
spindoctor backup create --target E:\Backups --include games,media --apply

:: 5. Tag a backup before doing something risky
spindoctor backup create --target E:\Backups --label pre-migration --apply
```

**Inspecting backups:**

```bat
spindoctor backup list --target E:\Backups
spindoctor backup info --backup E:\Backups\spindoctor-backup-20260428_120000
```

**Restoring:**

```bat
:: Dry-run a full restore
spindoctor backup restore --backup E:\Backups\spindoctor-backup-20260428_120000

:: Restore everything back to the paths recorded in the backup
spindoctor backup restore --backup E:\Backups\... --apply

:: Restore just the settings (e.g. after a fresh install)
spindoctor backup restore --backup E:\Backups\... --include settings --apply

:: Drive letters changed since the backup — route restores to whatever
:: paths config.json currently has instead of the originals
spindoctor backup restore --backup E:\Backups\... --use-current-paths --apply

:: Replace existing folders (default refuses to clobber non-empty dirs)
spindoctor backup restore --backup E:\Backups\... --overwrite --apply
```

The pre-flight plan tells you total bytes to copy and free space at the target, and aborts the apply if there isn't enough room.

### Auto-refresh wheels on every boot

```bat
:: One-time setup
spindoctor install-tools

:: Schedule the rebuilds at log-on
schtasks /create /sc onlogon /tn "SpinDoctor Wheels" ^
  /tr "cmd /c spindoctor-fav rebuild && spindoctor-recent rebuild"
```

---

## FAQ

**ROM filenames have region tags like `(USA)`. Will they match correctly?**

Yes — region/version/revision tags are stripped before searching. Ambiguous matches prompt you with a review link to the metadata source.

**Will SpinDoctor overwrite my data?**

Every XML write makes a `.YYYYMMDD_HHMMSS.bak` first (toggle via `backup_before_modify`). Use `--output-dir` to write to a staging folder first. For larger snapshots — full ROMs, media, settings — use `spindoctor backup create` to copy a labelled, dated backup off to another drive that `backup restore` can replay later.

**Does it work with RocketUI / RocketLauncher?**

Yes. RocketUI uses the same HyperSpin `Databases/` and `Media/` structure.

**ScreenScraper is rate-limiting me.**

SpinDoctor caps itself at 1 request/second. The free tier is 500/day — wait for midnight UTC or upgrade.

**I picked the wrong metadata match.**

```bat
spindoctor match clear --system MAME
spindoctor fetch-meta --system MAME
```

Your previous XML changes aren't rolled back — only the cached match decision is cleared.

**HyperSpin's Search menu crashes when LEDBlinky is enabled.**

```bat
spindoctor ledblinky check
spindoctor ledblinky fix
```

The fix is reversible — `.bak` files are written and disabled lines are commented out (not deleted) and tagged.

**Can I edit favorites from inside HyperSpin?**

HyperSpin's built-in F-key writes per-system favorite lists. Run `spindoctor fav sync` to merge those into the cross-system Favorites wheel. For explicit add/remove, use `spindoctor-fav add` / `remove`.

**Does favoriting a game double its disk usage?**

No — by default media is hardlinked from the source system into `Media/Favorites/`. Both pathnames point at the same bytes on NTFS. Pass `--media-mode copy` if you're on a filesystem that doesn't support hardlinks (FAT32, exFAT).

**How do I get cross-system "Recently Played" working?**

It's automatic — `spindoctor recent rebuild` reads RocketLauncher's `Statistics.ini` files (which RocketLauncher already writes on every game launch). Schedule it at log-on or run it from the Tools menu.

---

To request a feature or report a bug, open an issue at the project repository.
