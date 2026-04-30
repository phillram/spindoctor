# Command reference

Every `spindoctor` command, grouped by purpose. Commands that modify files default to **dry-run** — re-run with `--apply` to commit. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`, `mainmenu show`, `find-misplaced` without `--apply`) need no flag and never modify anything.

Most destructive commands write a manifest under `~/.spindoctor/<category>/` and accept `--undo` to roll back. See [Workflows → Recovery](workflows.md#recovery-from-mistakes) for the full manifest map.

## Contents

- [Core library](#core-library) — `systems`, `audit`, `inspect`, `update-db`, `fetch-meta`, `fetch-media`, `media-add`, `media-scan`, `report`
- [Editing](#editing) — `batch-edit`, `rename`, `clone`
- [Library generation](#library-generation) — `generate-config`, `mainmenu`, `organize`, `add-system`, `add-pc-system`, `pc-rename`, `migrate`, `backup`
- [Health & integrity](#health--integrity) — `find-dupes`, `find-misplaced`, `curate`, `find-orphan-media`, `check-discs`, `verify`, `stats`, `preview`
- [Custom wheels](#custom-wheels) — `fav`, `recent`, `install-tools`
- [Playtime stats](#playtime-stats) — `stats-report`
- [LEDBlinky](#ledblinky)
- [Maintenance](#maintenance) — `doctor`, `ignore`, `match`, `cleanup`, `lint`

---

## Core library

### `systems`

List every system detected across `roms_dir` and `Databases/`.

```bat
spindoctor systems
```

### `audit`

Compare ROM files against the HyperSpin database and media assets. Reports exact + fuzzy matches, ROMs without DB entries, DB entries without ROMs, incomplete metadata, missing media, and ignored counts.

```bat
spindoctor audit --system MAME
spindoctor audit --all --no-media
spindoctor audit --all --report D:\audit_report.csv
spindoctor audit --system MAME --detailed   :: append per-file dimensions/sizes
```

### `inspect`

Per-file deep-dive for a single game or every game with issues in a system. Shows the ROM file, every media slot, image dimensions, video length, and modification times.

```bat
spindoctor inspect --system MAME --game 1942
spindoctor inspect --system SNES --no-path                  :: compact view
spindoctor inspect --system MAME --all --format csv --output D:\manifest.csv
```

### `update-db`

Sync HyperSpin XML databases to match the ROM directories — adds stub entries for new ROMs, optionally removes orphan entries.

```bat
spindoctor update-db --system MAME                                :: dry-run preview
spindoctor update-db --system MAME --apply                        :: commit
spindoctor update-db --all --remove-orphans --apply
spindoctor update-db --all --remove-orphans --output-dir D:\Output --apply
spindoctor update-db --system SNES --strip-variant-tags --apply   :: collapse "(Japan)"/"(USA)" displays
```

A `.YYYYMMDD_HHMMSS.bak` is saved before in-place writes (toggle via `backup_before_modify`).

### `fetch-meta`

Download metadata (description, year, manufacturer, genre, rating, players) and write it into the XML.

```bat
spindoctor fetch-meta --system MAME                          :: dry-run preview
spindoctor fetch-meta --system MAME --apply                  :: commit
spindoctor fetch-meta --all --apply
spindoctor fetch-meta --all --output-dir D:\Output --apply
spindoctor fetch-meta --all --auto-best --apply              :: never prompt — pick top result
spindoctor fetch-meta --system SNES --all-games --apply      :: refresh complete entries too
```

API responses are cached at `~/.spindoctor/metadata_cache/`. TTL via `metadata_cache_ttl_days`. Pass `--no-cache` for a one-shot fresh run, or `--clear-cache` to wipe.

When multiple results match, the picker prompts you (or use `--auto-best`). Choices are cached at `~/.spindoctor/match_cache/<system>.json` so re-runs are silent.

### `fetch-media`

Download wheels, backgrounds, snaps, videos, etc. for games in the database.

```bat
spindoctor fetch-media --system MAME --types wheel,background           :: dry-run preview
spindoctor fetch-media --system MAME --types wheel,background --apply   :: commit
spindoctor fetch-media --all --apply
spindoctor fetch-media --all --output-dir D:\Output --apply
spindoctor fetch-media --system SNES --types trailer --overwrite --apply
spindoctor fetch-media --system MAME --types theme,fade,sound --apply
```

Concurrency is controlled by `max_concurrent_downloads`. The downloader retries on HTTP 429/503, honouring `Retry-After`.

`theme`, `fade`, and `sound` come from ScreenScraper only (TheGamesDB has no equivalents) and coverage is sparse. For EmuMovies-style theme packs, drop the files into a folder and run `spindoctor media-scan SOURCE_DIR --apply` to bulk-import them.

### `media-add`

Manually drop a local file into the right HyperSpin media slot.

```bat
spindoctor media-add --system MAME --game 1942 --type trailer ^
    --file C:\Downloads\1942_trailer.mp4
spindoctor media-add --system SNES --game "Super Mario World" ^
    --type title --file C:\Art\smw_title.png --move
```

### `media-scan`

Inverse of `find-orphan-media`: scan a folder of local media files (a downloaded EmuMovies pack, a custom-art directory, a wheel set you grabbed off the wiki) and audit it against HyperSpin databases.

Each file is recognised by folder name (`Wheels`, `Snaps`, `Backgrounds`, `BoxArt`, `Titles`, `Videos`, `Trailers`, `Themes`, `Sounds`) and/or extension, then fuzzy-matched against the chosen system's `<game>` entries. Results bucket as:

| Bucket | Meaning |
|---|---|
| `matched` | Game found in DB, slot is empty (importable). |
| `replacement` | Game found in DB, slot already filled. |
| `unmatched` | No DB match above the fuzzy threshold. |
| `unknown-type` | Couldn't infer media type (e.g. ambiguous bare image). |

```bat
spindoctor media-scan D:\Downloads\MAME-pack --system MAME
spindoctor media-scan D:\Art --all --detail --report scan.csv
spindoctor media-scan D:\Art --system SNES --apply --action copy
spindoctor media-scan D:\Art --system SNES --apply --overwrite
spindoctor media-scan --undo
spindoctor media-scan --list-manifests
```

`--apply` defaults to `--action copy`; `--action move` relocates files, `--action link` creates symlinks (falls back to copy on filesystems that reject them). `--overwrite` also imports the `replacement` bucket. Imports write a manifest to `~/.spindoctor/media_imports/` so `--undo` can reverse the most recent one.

### `report`

Read-only summary or CSV — never modifies anything.

```bat
spindoctor report --all --format summary
spindoctor report --all --format csv --output D:\weekly.csv
```

---

## Editing

Three commands for editing game metadata and identity without ever opening HyperHQ. All three default to dry-run; pass `--apply` to commit, and every apply writes a JSON manifest under `~/.spindoctor/` so the change can be reversed with `--undo`.

### `batch-edit` — set/clear/append metadata across many games

Filter games out of one system's database, then mutate one or more fields in lockstep. Filters: `name=*Mario*`, `genre=Action`, `year=1980-1989`, `manufacturer=Capcom`, `missing=rating`. Mutations: `--set field=value`, `--clear field`, `--append field=value`, `--prepend field=value`.

```bat
:: Tag every Capcom game from the 80s as Action
spindoctor batch-edit --system MAME --filter manufacturer=Capcom --filter year=1980-1989 --set genre=Action

:: Set rating=5 on every Action game (dry-run shows the table first)
spindoctor batch-edit --system MAME --filter genre=Action --set rating=5 --apply

:: Fill in a default rating for everything that's blank
spindoctor batch-edit --system NES --filter missing=rating --set rating=3 --apply

:: Reverse the most recent edit
spindoctor batch-edit --undo ~/.spindoctor/edits/edit-20260428_120000.json
spindoctor batch-edit --list-manifests
```

`--report path.csv` dumps a `(game,field,before,after)` preview before you commit. The DB is saved with a `.bak` next to it on each apply.

### `rename` — atomic ROM + DB + media rename

Change a game's identity in one shot: ROM file, `<game>` entry, and every media slot (wheel, snap, video, theme, ...) all follow. RocketLauncher PCLauncher INIs (when present) are renamed too.

```bat
spindoctor rename --system MAME --game "1942" --to "1942 (USA)"
spindoctor rename --system MAME --game "1942" --to "1942 (USA)" --display-name "1942 (USA)" --apply
spindoctor rename --undo ~/.spindoctor/renames/rename-20260428_120000.json
```

The plan refuses to overwrite anything already at the target name. Each apply writes a manifest with each move recorded so undo can reverse it back to the source paths.

### `clone` — duplicate a base ROM as a hack/translation variant

Same pipeline as `rename`, but the ROM and every media file are copied (not moved) and a new `<game>` entry is appended alongside the original. Useful for hacks or fan-translations that share assets with the base game.

```bat
spindoctor clone --system NES --game "Zelda" --to "Zelda (Speed Hack)"
spindoctor clone --system NES --game "Zelda" --to "Zelda (Speed Hack)" \
                 --display-name "Zelda (Speed Hack)" --apply
spindoctor clone --undo ~/.spindoctor/renames/rename-20260428_120000.json
```

Undo deletes only the copies — the original is untouched.

---

## Library generation

### `generate-config`

Generate RocketLauncher INI files and the HyperSpin Main Menu XML.

```bat
spindoctor generate-config                                :: dry-run preview
spindoctor generate-config --apply                        :: commit
spindoctor generate-config --output-dir D:\Output --apply
spindoctor generate-config --no-rl --apply                :: only regenerate the main menu
spindoctor generate-config --db-stubs --apply             :: also create empty DB stubs
```

Emulators are guessed from the system name (MAME → MAME, SNES → RetroArch, N64 → Project64, PS2 → PCSX2, etc.). Edit the generated INIs to override.

### `mainmenu`

Inspect and edit the HyperSpin Main Menu — the top-level wheel of systems. `generate-config` writes this file; `mainmenu` lets you review the order, hide stale systems, and add forgotten ones.

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
```

Write commands are dry-run by default — pass `--apply` to commit. Each write makes a `.YYYYMMDD_HHMMSS.bak` of `Main Menu.xml` first.

```bat
spindoctor mainmenu reorder "Nintendo 64" 1 --apply
spindoctor mainmenu up "Sony Playstation" --apply
spindoctor mainmenu down MAME --apply

spindoctor mainmenu hide "Atari Jaguar" --apply
spindoctor mainmenu show "Atari Jaguar" --apply       :: un-hide

spindoctor mainmenu add "Sega Saturn" --apply
spindoctor mainmenu remove "Atari Jaguar" --apply

spindoctor mainmenu sort alpha --apply
spindoctor mainmenu sort manufacturer --apply
spindoctor mainmenu sort year --apply

spindoctor mainmenu reorder MAME 1 --apply --output-dir D:\Output
```

For larger reshuffles, the interactive editor accepts commands like `up 3`, `move 3 to 1`, `hide 4`, `add Sega Saturn`, and confirms before saving on `q`:

```bat
spindoctor mainmenu edit
```

### `organize`

Populate per-axis sort wheels (genre/year/manufacturer/letter) and optionally restructure ROMs into per-game folders or multi-disc m3u playlists.

```bat
spindoctor organize "Sony Playstation"                         :: sort wheels only
spindoctor organize "Sony Playstation 3" --restructure         :: dry-run plan
spindoctor organize "Sony Playstation 3" --restructure --apply :: execute
spindoctor organize "Sony Playstation 3" --undo                :: revert last apply
```

### `add-system`

Bootstraps a brand-new console end-to-end: registers it in the Main Menu, creates database stub, generates RocketLauncher INI, scaffolds media folders, and walks the metadata + media fetch flow.

```bat
spindoctor add-system "Sega Saturn"             :: dry-run preview
spindoctor add-system "Sega Saturn" --apply     :: commit
```

### `add-pc-system`

Same as `add-system` but for PC / Windows / Steam libraries — handles recursive scanning of nested install folders, the title-picker for awkward layouts, and per-game PCLauncher INIs.

```bat
spindoctor add-pc-system "PC Games"             :: dry-run preview
spindoctor add-pc-system "PC Games" --apply     :: commit
spindoctor pc-rename "PC Games"   :: re-run the title picker after dropping new games in
```

### `migrate`

Move (or copy) the entire library — or just specific parts — to a new drive in one shot. Updates `~/.spindoctor/config.json` with the new paths and writes a manifest you can undo. See [Workflows → Migration](workflows.md#migration) for the typical end-to-end flow.

The components map directly to your config paths:

| Component | What moves | Default subfolder | Config field updated |
|---|---|---|---|
| `roms` | `roms_dir` | `Games/` | `roms_dir` |
| `hyperspin` | `hyperspin_dir` | `HyperSpin/` | `hyperspin_dir` |
| `emulators` | `emulators_dir` | `Emulators/` | `emulators_dir` |
| `rocketlauncher` | `rocketlauncher_dir` | `RocketLauncher/` | `rocketlauncher_dir` |
| `ledblinky` | `ledblinky_dir` | `LEDBlinky/` | `ledblinky_dir` |
| `all` | every component above | all of the above | every field above |

Aliases: `games` → `roms`; `media` / `data` / `databases` → `hyperspin` (Databases and Media live inside `hyperspin_dir` and travel together).

```bat
spindoctor migrate --target E:\NewCab                                    :: dry-run
spindoctor migrate --target E:\NewCab --apply
spindoctor migrate --target E:\NewCab --include roms,hyperspin --apply
spindoctor migrate --target E:\NewCab --include emulators --apply

:: Per-system ROM moves (split-library mode — leaves roms_dir alone)
spindoctor migrate --target E:\NewCab --include roms ^
    --systems "MAME,Sony Playstation 3" --apply

:: Keep original folder names instead of standardizing
spindoctor migrate --target E:\NewCab --apply --preserve-names

:: Safer: copy first, SHA1-verify, leave originals intact, skip config rewrite
spindoctor migrate --target E:\NewCab --apply --keep-source --verify

:: Reverse a migration
spindoctor migrate --list-manifests
spindoctor migrate --undo latest
spindoctor migrate --undo C:\Users\you\.spindoctor\migrations\migrate-20260427_213345.json
```

Other useful flags:

| Flag | Purpose |
|---|---|
| `--no-update-config` | Skip the config rewrite even on a real move |
| `--include hyperspin,emulators` | Multi-component selection — comma-separated |

The pre-flight plan reports total bytes to transfer and free space at the target, and aborts the apply if there isn't enough room.

### `backup`

Copy any combination of library components into a dated backup folder on a different drive — and restore it later, in full or in part. See [Workflows → Backup](workflows.md#backup--restore) for example flows.

| Component | What it covers | Subfolder in the backup |
|---|---|---|
| `roms` (alias `games`) | `roms_dir` | `Games/` |
| `databases` (alias `db`, `data`) | `<hyperspin_dir>/Databases/` | `HyperSpin/Databases/` |
| `media` | `<hyperspin_dir>/Media/` | `HyperSpin/Media/` |
| `emulators` | `emulators_dir` | `Emulators/` |
| `rocketlauncher` (alias `rl`) | `rocketlauncher_dir` | `RocketLauncher/` |
| `ledblinky` (alias `led`) | `ledblinky_dir` | `LEDBlinky/` |
| `settings` (alias `config`) | `~/.spindoctor/` (config, favorites, ignore lists, caches) | `Settings/` |
| `all` | every component above | all of the above |

Composite alias `hyperspin` (also `hs`) expands to `databases,media`. Each backup lives at `<target>/spindoctor-backup-YYYYMMDD_HHMMSS[-LABEL]/` with a `manifest.json`.

```bat
spindoctor backup create --target E:\Backups                                  :: dry-run
spindoctor backup create --target E:\Backups --apply                          :: full
spindoctor backup create --target E:\Backups --include settings,databases --apply
spindoctor backup create --target E:\Backups --label pre-migration --apply

spindoctor backup list --target E:\Backups
spindoctor backup info --backup E:\Backups\spindoctor-backup-20260428_120000

spindoctor backup restore --backup E:\Backups\spindoctor-backup-... --apply
spindoctor backup restore --backup E:\Backups\... --include settings --apply
spindoctor backup restore --backup E:\Backups\... --use-current-paths --apply  :: drive letters changed
spindoctor backup restore --backup E:\Backups\... --overwrite --apply          :: clobber non-empty dirs
```

---

## Health & integrity

### `find-dupes`

Detect duplicate ROMs within a system or across systems.

```bat
spindoctor find-dupes --system MAME
spindoctor find-dupes --all --cross-systems         :: same title in multiple folders
spindoctor find-dupes --system NES --by-content     :: SHA1 match (catches renamed copies)
```

Two ROMs are duplicates by default when their stems collapse to the same normalised title (region/version tags stripped). `--by-content` adds byte-level pairing — archive-aware, so `mario.zip` and `mario.7z` containing the same payload pair up (install `[archives]` for `.7z` / `.rar` peeking).

### `find-misplaced`

Flag ROMs whose extension doesn't match the folder's system (e.g. a `.nes` inside `snes/`). Generic containers (`.zip`, `.iso`, `.bin`) are skipped because they're ambiguous.

```bat
spindoctor find-misplaced --all                  :: report only
spindoctor find-misplaced --system snes --apply  :: move each to its suggested system
spindoctor find-misplaced --undo                 :: reverse the most recent --apply
```

### `curate` — region & version curation

Where `find-dupes` only reports collisions, `curate` actively picks one canonical variant per game (by region preference and revision number) and groups the rest as retirement candidates.

```bat
spindoctor curate --system NES                            :: dry-run
spindoctor curate --all --regions USA,Japan               :: override preferences
spindoctor curate --system NES --apply                    :: archive losers to _retired/
spindoctor curate --system NES --apply --action delete --yes
spindoctor curate --undo                                  :: reverse the last archive
spindoctor curate --list-manifests
```

Selection rules, in order: exclude prototypes/demos/betas (pass `--include-proto` to keep them), pick the highest-priority region, prefer the latest revision (`--prefer-revision oldest` to invert), tiebreak by filename. Default preferences come from `config.region_preferences` — `["USA", "World", "Europe", "Japan"]` out of the box. `--action archive` (the default) moves retired ROMs to `<roms_dir>/<system>/_retired/` and is reversible. `--action delete` is permanent.

### `find-orphan-media`

Wheels, snaps, videos, and themes whose game no longer exists in the database or ROMs. `--apply` removes them after a confirmation prompt (irreversible — no undo).

```bat
spindoctor find-orphan-media --all                    :: dry-run report
spindoctor find-orphan-media --system SNES --apply    :: remove (prompts)
```

### `check-discs`

Validate multi-disc layouts: every `(Disc N)` file has its `(Disc 1..N-1)` siblings, and every `.m3u` line resolves to a real file.

```bat
spindoctor check-discs --system "Sony Playstation"
spindoctor check-discs --all
```

### `verify`

Verify ROM file integrity against a No-Intro / Redump / TOSEC DAT XML. Each ROM is classified `good` / `renamed` / `bad` / `unknown`. Hashing is lazy — files whose size doesn't appear in the DAT skip hashing entirely.

By default `verify` tries inner-content matching first then falls back to wrapper-byte matching, so the same command works against both No-Intro/Redump-style DATs (inner hashes) and TOSEC-style DATs (wrapper hashes). Pass `--match inner` or `--match wrapper` to force one.

```bat
spindoctor verify --system NES --dat C:\Dats\Nintendo - Nintendo Entertainment System.dat
spindoctor verify --system NES --dat ... --show-good   :: also list verified-good files
spindoctor verify --system NES --dat tosec.dat --match wrapper
```

| Status | Meaning |
|---|---|
| `good` | Hash + filename match the DAT |
| `renamed` | Hash matches but filename differs |
| `bad` | Size matches a known entry but hashes don't — likely a bad dump |
| `unknown` | DAT doesn't list anything of this size — homebrew, hack, or unsupported |

Archive support: `.zip`, `.gz`, and `.chd` are read natively (CHD `rawsha1` is parsed straight from the header — no decompression). `.7z` and `.rar` need `pip install -e .[archives]`; without them those files report `unknown` with an install hint.

### `stats`

Coverage dashboard: % ROMs matched to DB, % metadata complete, % media complete, plus the most commonly missing media types.

```bat
spindoctor stats
spindoctor stats --system MAME
```

### `preview`

Generate a visual preview of a system's media — wheels, snaps, backgrounds, themes — so you can sanity-check what your library looks like in HyperSpin without opening every PNG by hand.

Two output modes:

- **Contact sheet** — a grid of every wheel with the game name underneath. Default output is a self-contained HTML page (no Pillow required) using `file://` paths. Pass `--format png` for a single composited PNG (requires Pillow).
- **Per-game card** — a full-page HTML mock of a HyperSpin entry: full-bleed background, wheel logo center-bottom, snap top-right, title image top-left, and a metadata strip at the bottom.

```bat
spindoctor preview --system MAME --output-dir D:\Preview
spindoctor preview --all --output-dir D:\Preview --columns 8
spindoctor preview --system NES --output-dir D:\Out --format both --open
spindoctor preview --system NES --output-dir D:\Out --game "Super Mario Bros"
spindoctor preview --system NES --output-dir D:\Out --include-missing
```

PNG mode is gated on `pip install -e .[preview]` (Pillow). When Pillow isn't installed, `--format png` falls back to HTML with a warning.

---

## Custom wheels

Two synthetic HyperSpin systems — **Favorites** and **Recently Played** — and a third (**Most Played**) generated from playtime stats. Each pulls entries from any number of source systems into a single wheel, routes through RocketLauncher so the original emulator config is reused, and is idempotent — safe to run on every boot.

### `fav` — cross-system Favorites

State lives in `~/.spindoctor/favorites.json` as `(system, rom_name)` pairs. The wheel is rebuilt **alphabetically by display title**.

```bat
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav add "Sony Playstation" "Final Fantasy VII" --display-name "FF VII"
spindoctor fav remove "Super Nintendo" "Chrono Trigger"
spindoctor fav list
spindoctor fav sync               :: pull HyperSpin's per-system F-key favorites into the store
spindoctor fav rebuild            :: dry-run preview
spindoctor fav rebuild --apply    :: regenerate Databases/Favorites/Favorites.xml + media + launchers
spindoctor fav rebuild --media-mode copy --apply   :: force file copies (FAT32 thumb drives)
```

`--media-mode` accepts `auto` (default — hardlink, fall back to copy), `link`, `symlink`, `copy`, or `none` (skip media mirroring).

When two source systems both contain a game with the same ROM name (e.g. `Tetris` on SNES and Game Boy), the wheel labels them `Tetris (Super Nintendo)` and `Tetris (Game Boy)` automatically.

### `recent` — Recently Played

Reads RocketLauncher's `Statistics.ini` files (no extra hooks needed), keeps the most-recent N games across every system, and regenerates the wheel.

```bat
spindoctor recent rebuild                                :: dry-run preview
spindoctor recent rebuild --apply                        :: top 20 (default)
spindoctor recent rebuild --limit 10 --apply
spindoctor recent rebuild --target-system "Last Played" --apply
spindoctor recent list                                   :: print the current top-N
```

Sorted by `last_played` desc — newest game first, deduped on `(system, rom)`. See [Standalone tools](standalone-tools.md) for ordering and limit details.

### `install-tools`

Writes `.bat` wrappers HyperSpin's Tools menu can invoke directly — so cabinet end-users can refresh wheels from the UI without a console.

```bat
spindoctor install-tools                                :: write to RocketLauncher Tools dir
spindoctor install-tools --output-dir D:\Tools          :: write somewhere else
```

Four files are produced (Refresh Favorites, Refresh Recently Played, Refresh Most Played, Refresh Both). See [Standalone tools → Tools menu](standalone-tools.md#hyperspin-tools-menu).

---

## Playtime stats

RocketLauncher silently logs how many times each game has been launched and how long the user spent in it. `stats-report` aggregates those into useful views, and `stats-report build-wheel` turns the top-N into a synthetic **Most Played** HyperSpin system.

```bat
:: Overall summary — totals + Top 10 played + Top 10 recent + per-system table
spindoctor stats-report

spindoctor stats-report --system MAME
spindoctor stats-report --top 50
spindoctor stats-report --by-system
spindoctor stats-report --recent

spindoctor stats-report --export D:\Reports\playtime.csv
spindoctor stats-report --json   D:\Reports\playtime.json
```

Example output:

```
╭─ Playtime ───────────────────────────────────╮
│ Total playtime:  3d 4h 12m                   │
│ Unique games:    127                         │
│ Sessions:        842                         │
│ Top system:      MAME  (1d 22h)              │
╰──────────────────────────────────────────────╯
```

### `stats-report build-wheel` — Most Played wheel

Generates `Databases/Most Played/Most Played.xml` with the top-N games (sorted by `total_seconds` desc), hardlinks media into `Media/Most Played/`, writes per-game launchers under `Modules/PCLauncher/Most Played/`, and registers `Most Played` in the HyperSpin Main Menu.

```bat
spindoctor stats-report build-wheel --limit 25                                 :: dry-run
spindoctor stats-report build-wheel --limit 25 --apply                         :: commit
spindoctor stats-report build-wheel --target-system "Hall of Fame" --media-mode copy --apply
```

`--media-mode` accepts the same values as `fav rebuild`.

---

## LEDBlinky

```bat
spindoctor ledblinky generate              :: dry-run preview
spindoctor ledblinky generate --apply      :: commit controls.ini / colors.ini
spindoctor ledblinky audit
spindoctor ledblinky check                 :: scan for HyperSpin Search-menu compatibility issues
spindoctor ledblinky fix                   :: dry-run preview of the patch
spindoctor ledblinky fix --apply           :: commit the patch
```

`generate` builds `controls.ini` and `colors.ini` from MAME `-listxml`, preserving any community-maintained entries already present in `<ledblinky_dir>`.

`check` / `fix` diagnose and repair the well-known issue where HyperSpin's Search overlay crashes when LEDBlinky is installed:

1. LEDBlinky injects `Start_Hyperspin_Process` / `Exit_Hyperspin_Process` lines into per-menu `Settings.ini` — Search's overlay launcher doesn't tolerate them.
2. `LEDBlinkyControls.xml` has no entry for the Search special menu.

`fix` is reversible: timestamped `.bak` backups are saved next to every modified file, and disabled lines are commented out (not deleted), tagged so you can find them later.

```bat
spindoctor ledblinky fix --menus Search,Genre,Favorites --apply
spindoctor ledblinky fix --output-dir D:\SpinDoctorOutput --apply   :: stage instead of in-place
```

The global `<hyperspin_dir>/Settings/Settings.ini` is never touched — LEDBlinky needs those hooks during gameplay.

---

## Maintenance

### `doctor`

Self-diagnose your install: paths, binaries, XML DB integrity, match-cache hygiene, RocketLauncher / LEDBlinky files, optional `lxml`, `ffprobe`. Each check renders ✓ / ⚠ / ✗.

```bat
spindoctor doctor              :: read-only diagnosis
spindoctor doctor --apply      :: also run safe, idempotent repairs
```

`--apply` only does safe, idempotent repairs (prune stale cache, create media folder skeletons, regen `Global Emulators.ini`) — never deletes ROMs/DBs/media.

### `ignore`

Per-system or global ignore lists. Ignored games are skipped by `audit`, `fetch-meta`, `fetch-media`, and `update-db`.

```bat
spindoctor ignore add "pacman"                          :: global
spindoctor ignore add "Mario (hack)" --system NES
spindoctor ignore list
spindoctor ignore remove "pacman"
spindoctor ignore clear --system MAME
```

### `match`

Manage cached metadata-match decisions made interactively during `fetch-meta`.

```bat
spindoctor match list --system MAME
spindoctor match clear --system MAME
```

### `cleanup`

One-stop inventory and removal of every cache, manifest, temp dir, and `.bak` backup SpinDoctor produces. Categories cover match / media-pick / pc-titles / metadata / MAME-listxml caches, the preview temp dir, **interrupted-download `.part` sidecars** under `Media/`, audit-CSV exports, restructure / misplaced / migration manifests, and HyperSpin / LEDBlinky `.bak` files.

```bat
spindoctor cleanup categories                                                :: list categories
spindoctor cleanup audit                                                     :: disk usage by category
spindoctor cleanup audit --detail
spindoctor cleanup audit -c metadata-cache -c db-backups

spindoctor cleanup run --include safe                                        :: dry-run
spindoctor cleanup run --include metadata-cache,match-cache --apply
spindoctor cleanup run --include metadata-cache --older-than 90 --apply
spindoctor cleanup run --include db-backups --keep-recent 5 --apply

spindoctor cleanup run --include all --include-unsafe --apply --prune-empty-dirs
```

`safe` covers the regenerable caches and audit exports; `db-backups`, `migration-manifests`, and `restructure-manifests` are flagged unsafe — naming them in `--include` is an explicit opt-in. `--prune-empty-dirs` collapses now-empty cache folders. `--yes` skips the final confirmation prompt for scripted runs.

### `lint`

AST pass over the SpinDoctor source itself — surfaces unused imports, bare `except:`, TODO markers, and near-duplicate function bodies. Useful as a pre-commit sanity check if you fork or modify SpinDoctor.

```bat
spindoctor lint
spindoctor lint --category unused-import,bare-except
```

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
│   │   └── Main Menu.xml             ← generated by generate-config; edit with `mainmenu`
│   ├── MAME/
│   │   └── MAME.xml
│   ├── Favorites/                    ← generated by `spindoctor fav rebuild`
│   ├── Recently Played/              ← generated by `spindoctor recent rebuild`
│   └── Most Played/                  ← generated by `spindoctor stats-report build-wheel`
└── Media/
    ├── MAME/
    │   ├── Images/{Wheel,Backgrounds,Artwork1,Artwork2,Artwork3,Artwork4}/
    │   ├── Video/{,Trailers}/
    │   ├── Sound/
    │   └── Themes/
    ├── Favorites/                    ← hardlinked / copied from source systems
    ├── Recently Played/
    └── Most Played/

rocketlauncher_dir/
├── Settings/{<System>.ini, Global Emulators.ini}
├── Settings/Global Statistics/<System>.ini   ← read by `recent` and `stats-report`
└── Modules/PCLauncher/{Favorites,Recently Played,Most Played}/<game>.ini
```

### Media types

| Type | HyperSpin path | Description |
|---|---|---|
| `wheel` | `Images/Wheel/` | Transparent PNG logo |
| `background` | `Images/Backgrounds/` | Full-screen background |
| `artwork` | `Images/Artwork1/` | Box art |
| `title` | `Images/Artwork2/` | Title screen screenshot |
| `snap` | `Images/Artwork3/` | Gameplay screenshot |
| `fade` | `Images/Artwork4/` | Fade-in image between wheel and game launch |
| `video` | `Video/` | Attract / intro video |
| `trailer` | `Video/Trailers/` | Full trailer |
| `sound` | `Sound/` | Sound clip on game select |
| `theme` | `Themes/` | HyperSpin SWF/ZIP theme |

`theme`, `fade`, and `sound` come from ScreenScraper only and coverage is sparse — for EmuMovies-style theme packs, drop the files into a folder and run `spindoctor media-scan SOURCE_DIR --apply`.

## ROM variant handling

Every ROM file is treated as an independent entry. `Super Mario Bros (USA, Rev 1).nes` and `Super Mario Bros (USA).nes` get separate database entries with separate display names, separate metadata fetches, and separate media slots.

By default the `<description>` keeps the variant tag so the two stay distinguishable in HyperSpin / RocketLauncher menus. Pass `--strip-variant-tags` to `update-db` (or set `strip_variant_tags_in_display_name true`) to collapse all variants to a shared display name.

| ROM filename | Display name (default) | With `--strip-variant-tags` |
|---|---|---|
| `1942 (Japan)` | `1942 (Japan)` | `1942` |
| `1942 (USA)` | `1942 (USA)` | `1942` |
| `Super Mario Bros (USA, Rev 1)` | `Super Mario Bros (USA, Rev 1)` | `Super Mario Bros` |
| `super_mario_bros` | `Super Mario Bros` | `Super Mario Bros` |

Fuzzy matching (used by `audit` and `fetch-meta`) strips region/version/revision tags before comparing, so `1942 (Japan, Rev B)` matches the DB entry `1942` with high confidence.
