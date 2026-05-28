# Command reference

The full per-command reference: every command, every flag, every option. If you just want a copy-paste cheatsheet of the most-used commands grouped by intent, start at [CLI cheatsheet](cli-cheatsheet.md) — it links back here for the per-flag detail.

Every `spindoctor` command, grouped by purpose. Commands that modify files default to **dry-run** — re-run with `--apply` to commit. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `find-global`, `verify`, `check-discs`, `stats`, `doctor`, `self-doctor`, `mainmenu show`, `find-misplaced` without `--apply`, `theme-scan`, `tools-audit`, `lightgun detect` / `audit`) need no flag and never modify anything.

Most destructive commands write a manifest under `~/.spindoctor/<category>/` and accept `--undo` to roll back. See [Workflows → Recovery](workflows.md#recovery-from-mistakes) for the full manifest map. The GUI's `File → View logs & manifests…` window has a one-click **Undo this run** button that runs the right `--undo` command for any selected manifest, so you don't have to remember which CLI invocation owns each category.

**Interrupting a long run is safe.** Hitting `Ctrl+C` (or the GUI's Stop button) mid-`backup`, mid-`migrate`, or mid-`curate` cleans up the in-flight component and writes a *partial manifest* for whatever finished. The backup still appears in the Restore picker; an interrupted move-mode migrate is reversible via `migrate --undo`; an interrupted curate-archive is reversible via `curate --undo`. The completed work is committed by design — the manifest exists so *you* can decide whether to roll it back.

## Contents

- [Core library](#core-library) — `systems`, `audit`, `inspect`, `update-db`, `fetch-meta`, `fetch-media`, `media-add`, `media-scan`, `report`, `find-global`
- [Editing](#editing) — `batch-edit`, `rename`, `clone`
- [Library generation](#library-generation) — `generate-config`, `mainmenu`, `organize`, `add-system`, `add-pc-system`, `pc-rename`, `migrate`, `backup`
- [Health & integrity](#health--integrity) — `find-dupes`, `find-misplaced`, `curate`, `find-orphan-media`, `check-discs`, `verify`, `stats`, `preview`
- [Custom wheels](#custom-wheels) — `fav`, `recent`, `install-tools`, `uninstall-tools`
- [Playtime stats](#playtime-stats) — `stats-report`
- [Resetting cabinet data](#resetting-cabinet-data) — `scrub`
- [Themes](#themes) — `theme-scan`, `theme-apply`, `theme-pack-create`
- [Diff](#diff) — `diff`
- [LEDBlinky](#ledblinky)
- [Light guns](#light-guns) — `lightgun detect`, `lightgun audit`, `lightgun configure`
- [Maintenance](#maintenance) — `doctor`, `self-doctor`, `tools-audit`, `ignore`, `match`, `cleanup`, `lint`

---

## Core library

> **Synthetic wheels (Favorites, Recently Played, Most Played) are automatically excluded when `--all` is used.** These wheels mirror their media from source systems — scanning or scraping them wastes API calls. A dim banner is printed for each skipped wheel. Passing `--system Favorites` (or any synthetic name) explicitly exits with an error directing you to the source system.

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

> **GUI alternative:** the **Metadata & Media** tab wraps `fetch-meta`, `fetch-media`, `media-scan`, `update-db`, and `generate-config` behind one shared "System (or All systems) + Apply" header. See [GUI walkthrough](gui.md).

Download metadata (description, year, manufacturer, genre, rating, players) and write it into the XML.

```bat
spindoctor fetch-meta --system MAME                          :: dry-run preview
spindoctor fetch-meta --system MAME --apply                  :: commit
spindoctor fetch-meta --all --apply
spindoctor fetch-meta --all --output-dir D:\Output --apply
spindoctor fetch-meta --all --auto-best --apply              :: never prompt — pick top result
spindoctor fetch-meta --all --skip-ambiguous --apply         :: log ambiguous matches, don't prompt or auto-pick
spindoctor fetch-meta --system SNES --all-games --apply      :: refresh complete entries too
```

API responses are cached at `~/.spindoctor/metadata_cache/`. TTL via `metadata_cache_ttl_days`. Pass `--no-cache` for a one-shot fresh run, or `--clear-cache` to wipe.

When multiple results match the picker prompts you. Three ways to override:

- `--auto-best` — pick the top candidate silently. Fast for big libraries; risks the occasional wrong match (review afterwards with `audit`).
- `--skip-ambiguous` — log ambiguous matches and move on without touching them. They stay incomplete and surface in the next `audit` pass for manual review. Required from non-TTY contexts (cron, CI, the GUI when "Auto-pick best match" is unticked) because the prompt path calls `input()` and would block.
- `--interactive` — force-prompt even when `config.interactive_matching=false`. Terminal users only.

Choices are cached at `~/.spindoctor/match_cache/<system>.json` so re-runs are silent.

### `fetch-media`

Download wheels, backgrounds, snaps, videos, etc. for games in the database.

```bat
spindoctor fetch-media --system MAME --types wheel,background           :: dry-run preview
spindoctor fetch-media --system MAME --types wheel,background --apply   :: commit
spindoctor fetch-media --all --apply
spindoctor fetch-media --all --output-dir D:\Output --apply
spindoctor fetch-media --system SNES --types trailer --overwrite --apply
spindoctor fetch-media --system MAME --types theme,fade,sound --apply
spindoctor fetch-media --all --skip-ambiguous --apply    :: skip multi-candidate slots
```

Concurrency is controlled by `max_concurrent_downloads`. The downloader retries on HTTP 429/503, honouring `Retry-After`.

When a media slot has multiple candidates (different regions / artwork variants), three modes are available:

- `--pick-media` — prompt interactively for each slot. Terminal-only — would hang from a GUI subprocess.
- `--skip-ambiguous` — log each ambiguous slot as a skip and move on. Required from non-TTY contexts (cron, CI, the GUI). Mirrors `fetch-meta --skip-ambiguous`.
- *Default (neither flag)* — auto-pick the first candidate. Fast; risks the occasional wrong pick.

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

### `find-global`

Search every configured system's HyperSpin database for a title. Replaces standalone Hypersearch utilities — type a title, get every system that has it.

```bat
spindoctor find-global "house of the dead"
spindoctor find-global "Pac-Man" --exact
spindoctor find-global "1942" --limit 10
```

`--exact` matches only when the query equals the entry name or description (case-insensitive). Otherwise substring search. `--limit` caps results per system (default 50).

### `report`

Read-only summary or CSV — never modifies anything.

```bat
spindoctor report --all --format summary
spindoctor report --all --format csv --output D:\weekly.csv
```

---

## Editing

Three commands for editing game metadata and identity without ever opening HyperHQ. All three default to dry-run; pass `--apply` to commit, and every apply writes a JSON manifest under `~/.spindoctor/` so the change can be reversed with `--undo`.

### `batch-edit`

Set, clear, or append metadata across many games. Filter games out of one system's database, then mutate one or more fields in lockstep. Filters: `name=*Mario*`, `genre=Action`, `year=1980-1989`, `manufacturer=Capcom`, `missing=rating`. Mutations: `--set field=value`, `--clear field`, `--append field=value`, `--prepend field=value`.

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

### `rename`

Atomic ROM + DB + media rename. Change a game's identity in one shot: ROM file, `<game>` entry, and every media slot (wheel, snap, video, theme, ...) all follow. RocketLauncher PCLauncher INIs (when present) are renamed too.

```bat
spindoctor rename --system MAME --game "1942" --to "1942 (USA)"
spindoctor rename --system MAME --game "1942" --to "1942 (USA)" --display-name "1942 (USA)" --apply
spindoctor rename --undo ~/.spindoctor/renames/rename-20260428_120000.json
```

The plan refuses to overwrite anything already at the target name. Each apply writes a manifest with each move recorded so undo can reverse it back to the source paths.

### `clone`

Duplicate a base ROM as a hack / translation variant. Same pipeline as `rename`, but the ROM and every media file are copied (not moved) and a new `<game>` entry is appended alongside the original. Useful for hacks or fan-translations that share assets with the base game.

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

> **GUI alternative:** the **Systems** tab wraps `add-system`, `add-pc-system`, and `pc-rename` (with `--no-system-media` / `--no-game-media` toggles, dry-run by default). See [GUI walkthrough](gui.md).

Bootstraps a brand-new console end-to-end: registers it in the Main Menu, creates database stub, generates RocketLauncher INI, scaffolds media folders, and walks the metadata + media fetch flow.

```bat
spindoctor add-system "Sega Saturn"             :: dry-run preview
spindoctor add-system "Sega Saturn" --apply     :: commit
```

### `add-pc-system`

Same as `add-system` but for PC / Windows / Steam libraries — handles recursive scanning of nested install folders, the title-picker for awkward layouts, and per-game PCLauncher INIs.

```bat
spindoctor add-pc-system "PC Games"                                     :: dry-run preview
spindoctor add-pc-system "PC Games" --apply                             :: commit (interactive title review)
spindoctor add-pc-system "PC Games" --no-interactive --apply            :: auto-accept every proposed title
spindoctor pc-rename "PC Games"                                         :: re-review titles after dropping new games in
spindoctor pc-rename "PC Games" --no-interactive                        :: auto-accept all (non-TTY contexts)
```

Both commands honour `--no-interactive`: skip the per-game `input()` prompt and auto-accept the proposed title for every game. **Required from non-TTY contexts** (the GUI uses it by default when adding a PC system, where the interactive review path would otherwise hang the subprocess on stdin). Users who want to curate titles by hand run `pc-rename <system>` from a terminal without the flag.

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

**After migrating the `roms` component**, RocketLauncher's per-system settings files still contain the old `Rom_Path`. Regenerate them immediately after the migrate:

```bat
spindoctor generate-config --apply
```

GUI: Metadata & Media tab → tick Apply → click **Run generate-config**. `generate-config` writes `<RocketLauncher>\Settings\<SystemName>.ini` for every configured system directly into the configured `rocketlauncher_dir`, so no manual copying is needed — the files land exactly where RocketLauncher expects them.

See [Workflows → Moving only your ROMs to a new drive](workflows.md#moving-only-your-roms-to-a-new-drive) for the full end-to-end example.

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

### `curate`

> **GUI alternative:** the **Curate** tab wraps `curate`, `cleanup`, and the `ignore` add/remove/list lifecycle in three sections of the same tab. The Curate section also has a **Preview (interactive)…** button that opens a Toplevel where every retirement candidate appears with a `☑/☐` checkbox — Space or double-click toggles a row, vetoing that file's retirement before you commit. The Ignore section gains a **View / un-ignore…** button that lists every currently-ignored entry in a multi-select listbox so you can un-ignore games with a click. See [GUI walkthrough](gui.md).

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

### `fav`

Cross-system Favorites. State lives in `~/.spindoctor/favorites.json` as `(system, rom_name)` pairs. The wheel is rebuilt **alphabetically by display title**.

```bat
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav add "Sony Playstation" "Final Fantasy VII" --display-name "FF VII"
spindoctor fav remove "Super Nintendo" "Chrono Trigger"
spindoctor fav list
spindoctor fav sync               :: pull HyperSpin's per-system F-key favorites into the store
spindoctor fav rebuild            :: dry-run preview
spindoctor fav rebuild --apply    :: regenerate Databases/Favorites/Favorites.xml + media + launchers
spindoctor fav rebuild --media-mode copy --apply   :: force file copies (FAT32 thumb drives)
spindoctor fav clear              :: dry-run preview of what would be removed
spindoctor fav clear --apply      :: remove the Favorites wheel and empty the store
```

`--media-mode` accepts `auto` (default — hardlink, fall back to copy), `link`, `symlink`, `copy`, or `none` (skip media mirroring).

**Theme fallback** — During the media mirror, if a game has no per-game `<GameName>.zip` in the source system's `Themes\` folder, SpinDoctor checks for `Default.zip` (HyperSpin's console-wide fallback theme) and mirrors it as `<GameName>.zip` in the synthetic wheel. This means games that rely on the console default theme (e.g. most NES games) display the same background and layout in Favorites / Recently Played / Most Played as they do in their native wheel.

**Navigate sound** — `rebuild --apply` also installs a bundled `navigate.mp3` to `Media\<SystemName>\Sound\navigate.mp3` for each synthetic wheel (skip-if-exists). HyperSpin plays this on every left/right cursor move while browsing the wheel's game list.

When two source systems both contain a game with the same ROM name (e.g. `Tetris` on SNES and Game Boy), the wheel labels them `Tetris (Super Nintendo)` and `Tetris (Game Boy)` automatically.

**`fav clear`** empties the favorites store and tears down the Favorites wheel — useful when starting fresh or before running `scrub`. Dry-run by default; pass `--apply` to commit. Files removed:

| File / directory | What it is |
|---|---|
| `~/.spindoctor/favorites.json` | Emptied (all `(system, rom)` entries removed) |
| `<hyperspin_dir>/Databases/Favorites/Favorites.xml` | Deleted |
| `<hyperspin_dir>/Media/Favorites/` | Entire directory deleted |
| `<rocketlauncher_dir>/Modules/PCLauncher/Favorites/` | All per-game `.ini` launchers deleted |

RocketLauncher `Statistics.ini` files are not modified — only the generated wheel artifacts are removed. The wheel can be rebuilt at any time with `fav rebuild --apply`.

### `recent`

Recently Played wheel. Reads RocketLauncher's `Statistics.ini` files (no extra hooks needed), keeps the most-recent N games across every system, and regenerates the wheel.

```bat
spindoctor recent rebuild                                :: dry-run preview
spindoctor recent rebuild --apply                        :: top 20 (default)
spindoctor recent rebuild --limit 10 --apply
spindoctor recent rebuild --target-system "Last Played" --apply
spindoctor recent list                                   :: print the current top-N
spindoctor recent clear                                  :: dry-run preview of what would be removed
spindoctor recent clear --apply                          :: remove the Recently Played wheel from disk
spindoctor recent clear --target-system "Last Played" --apply  :: clear a custom-named wheel
```

Sorted by `last_played` desc — newest game first, deduped on `(system, rom)`. See [Standalone tools](standalone-tools.md) for ordering and limit details.

**`recent clear`** removes the generated Recently Played wheel without touching RocketLauncher's `Statistics.ini` files. The wheel can be rebuilt at any time with `recent rebuild --apply`. Dry-run by default. Files removed:

| File / directory | What it is |
|---|---|
| `<hyperspin_dir>/Databases/Recently Played/Recently Played.xml` | Deleted |
| `<hyperspin_dir>/Media/Recently Played/` | Entire directory deleted |
| `<rocketlauncher_dir>/Modules/PCLauncher/Recently Played/` | All per-game `.ini` launchers deleted |

### `install-tools`

Writes `.bat` wrappers HyperSpin's Tools menu can invoke directly — so cabinet end-users can refresh wheels from the UI without a console.

```bat
spindoctor install-tools                                :: write to RocketLauncher Tools dir (HyperHQ → Tools)
spindoctor install-tools --output-dir D:\Tools          :: write somewhere else
spindoctor install-tools --add-to-system Toolkit        :: install as games inside an existing wheel
```

Four files are produced (Refresh Favorites, Refresh Recently Played, Refresh Most Played, Refresh All). See [Standalone tools → Tools menu](standalone-tools.md#hyperspin-tools-menu).

`--add-to-system <NAME>` is a second integration pattern for cabinets that already have a "Toolkit" or "Tools" wheel (a HyperSpin system whose "games" are maintenance tasks). Instead of writing the bats under `Modules\HyperLaunch\Tools\spindoctor\`, this mode:

1. Writes the bats and per-game PCLauncher INIs under `<RocketLauncher>\Modules\PCLauncher\<NAME>\`.
2. Adds matching `<game>` entries to `<HyperSpin>\Databases\<NAME>\<NAME>.xml`, with `genre=Tools` and `manufacturer=SpinDoctor` so they display correctly on the wheel.

Idempotent — re-running upserts the same four entries instead of duplicating them. The target system must already exist and use PCLauncher as its emulator (HyperHQ → Settings → Emulator → PCLauncher). Pair with `spindoctor mainmenu add "<NAME>" --apply` if the wheel isn't on the Main Menu yet.

The GUI's **Tools** tab covers both modes plus a Windows-only "Auto-refresh on cabinet startup" panel that wraps `schtasks.exe` (Schedule / Remove / Check Status buttons) — see [Standalone tools → Tools menu](standalone-tools.md#hyperspin-tools-menu).

### `uninstall-tools`

Reverses `install-tools`. Removes the `.bat` wrappers (and, when `--add-to-system` was used, the PCLauncher `.ini` files and database entries) that `install-tools` wrote. Dry-run by default — pass `--apply` to commit.

```bat
:: Standard Tools-menu install (bats in HyperLaunch\Tools\spindoctor\)
spindoctor uninstall-tools              :: dry-run — show what would be removed
spindoctor uninstall-tools --apply      :: remove the .bat files

:: Toolkit-wheel install (pass the same system name used with install-tools)
spindoctor uninstall-tools --add-to-system Toolkit
spindoctor uninstall-tools --add-to-system Toolkit --apply
```

When `--add-to-system <SYSTEM>` is given:

1. Removes the `.bat` and `.ini` files from the PCLauncher directory used for that system (reads the first `Rom_Path` from `Settings/<SYSTEM>/Emulators.ini`, falls back to `Modules/PCLauncher/<SYSTEM>`; also checks the legacy path so files written by older versions are cleaned up).
2. Deletes the four SpinDoctor `<game>` entries from `<HyperSpin>/Databases/<SYSTEM>/<SYSTEM>.xml`.

Only files and entries that exist are touched — missing ones are silently skipped.

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

### `stats-report clear-wheel` — remove the Most Played wheel

Removes the generated Most Played wheel without touching RocketLauncher's `Statistics.ini` files. The wheel can be rebuilt at any time with `stats-report build-wheel --apply`. Dry-run by default.

```bat
spindoctor stats-report clear-wheel              :: dry-run preview
spindoctor stats-report clear-wheel --apply      :: remove the Most Played wheel from disk
spindoctor stats-report clear-wheel --target-system "Hall of Fame" --apply  :: clear a custom-named wheel
```

Files removed:

| File / directory | What it is |
|---|---|
| `<hyperspin_dir>/Databases/Most Played/Most Played.xml` | Deleted |
| `<hyperspin_dir>/Media/Most Played/` | Entire directory deleted |
| `<rocketlauncher_dir>/Modules/PCLauncher/Most Played/` | All per-game `.ini` launchers deleted |

---

## Resetting cabinet data

### `scrub`

Destructively reset favorites and/or play statistics back to zero. **Requires `--apply`** — without it the command prints a dry-run preview and exits without touching anything.

> **⚠ `--stats` deletes `Statistics.ini` files permanently.** RocketLauncher has no built-in restore. Use `--backup-dir` to create a recoverable copy first, or run `scrub-restore` to undo. The favorites store (`favorites.json`) is only emptied and can be repopulated with `fav add` / `fav sync`.

```bat
:: Dry-run preview (nothing is written)
spindoctor scrub

:: Full scrub with backup — backs up then deletes everything
spindoctor scrub --backup-dir E:\Backups --apply

:: Clear only the favorites store and Favorites wheel
spindoctor scrub --favorites --apply

:: Delete all Statistics.ini files and clear Recently Played / Most Played wheels
spindoctor scrub --stats --backup-dir E:\Backups --apply

:: Start fresh for fav sync — clear per-system HyperSpin favorites
spindoctor scrub --hs-favorites --backup-dir E:\Backups --apply
```

Without `--favorites` or `--stats`, both are cleared (equivalent to passing both flags). `--hs-favorites` is never included in the default — it must always be requested explicitly.

#### Options

| Flag | Description |
|---|---|
| `--favorites` | Clear the SpinDoctor favorites store and Favorites wheel |
| `--stats` | Delete Statistics.ini files and clear Recently Played / Most Played wheels |
| `--hs-favorites` | Clear per-system HyperSpin favorites (`_Favorites.ini`, `favorites.txt`, `favorite="1"` in XML) so `fav sync` starts blank. Never included in the default — always opt-in. |
| `--backup-dir DIR` | Copy affected files to `DIR/scrub-<timestamp>/` before deleting. Strongly recommended for `--stats`. Skipped in dry-run mode. |
| `--apply` | Commit — without this flag nothing is changed |

#### What `--favorites` removes

| File / directory | What happens |
|---|---|
| `~/.spindoctor/favorites.json` | **Emptied** — all `(system, rom)` pairs removed; file is kept |
| `<hyperspin_dir>/Databases/Favorites/Favorites.xml` | Deleted |
| `<hyperspin_dir>/Media/Favorites/` | Entire directory deleted |
| `<rocketlauncher_dir>/Modules/PCLauncher/Favorites/` | All per-game `.ini` launchers deleted |

Per-system HyperSpin favorites (`<System>_Favorites.ini`, `favorites.txt`, `favorite="1"` in XML) are **not** touched. Use `--hs-favorites` to clear those too.

After a `--favorites` scrub the Favorites wheel is gone from HyperSpin. Running `fav add … && fav rebuild --apply` starts it fresh.

#### What `--hs-favorites` removes

Clears the per-system favorites that HyperSpin's F-key writes. Three sources across every configured system (synthetic wheels excluded):

| Source | What happens |
|---|---|
| `<hs>/Databases/<System>/<System>_Favorites.ini` | **Deleted** |
| `<hs>/Databases/<System>/favorites.txt` | **Deleted** (case-insensitive search) |
| `<hs>/Databases/<System>/<System>.xml` | `favorite="1"` attribute stripped from matching `<game>` elements; rest of file preserved |

After an `--hs-favorites` scrub, running `fav sync` imports zero HyperSpin favorites — the cross-system wheel starts blank. Use this when you want to curate your favorites from scratch (e.g. after trimming your ROM library).

#### What `--stats` removes

All `Statistics.ini` files that RocketLauncher has written, across all three layouts it may have used:

| Layout | Path pattern | Notes |
|---|---|---|
| Classic | `<rl>/Settings/Global Statistics/<System>.ini` | One file per system |
| Legacy | `<rl>/Settings/<System>/Statistics.ini` | Older RL builds |
| Newer | `<rl>/Data/Statistics/<System>.ini` | Per-system files |
| Newer (aggregate) | `<rl>/Data/Statistics/Global Statistics.ini` | RL's top-10 summary — included so refresh starts blank |

Every matching file is **permanently deleted** — RocketLauncher will create new (empty) files the next time games are launched. In addition, the generated Recently Played and Most Played wheels are cleared:

| File / directory | What happens |
|---|---|
| `<hyperspin_dir>/Databases/Recently Played/Recently Played.xml` | Deleted |
| `<hyperspin_dir>/Media/Recently Played/` | Entire directory deleted |
| `<rocketlauncher_dir>/Modules/PCLauncher/Recently Played/` | All per-game `.ini` launchers deleted |
| `<hyperspin_dir>/Databases/Most Played/Most Played.xml` | Deleted |
| `<hyperspin_dir>/Media/Most Played/` | Entire directory deleted |
| `<rocketlauncher_dir>/Modules/PCLauncher/Most Played/` | All per-game `.ini` launchers deleted |

After a `--stats` scrub all play history is gone. Running `recent rebuild --apply` and `stats-report build-wheel --apply` will produce empty wheels until RocketLauncher has logged new sessions.

#### What `--backup-dir` saves

When `--backup-dir DIR` is given alongside `--apply`, SpinDoctor creates `DIR/scrub-<timestamp>/` containing:

| File | Source |
|---|---|
| `favorites.json` | `~/.spindoctor/favorites.json` (if `--favorites`) |
| `stats/Settings/Global Statistics/<System>.ini` | Classic layout stats (if `--stats`) |
| `stats/Settings/<System>/Statistics.ini` | Legacy layout stats (if `--stats`) |
| `stats/Data/Statistics/<System>.ini` | Newer layout stats (if `--stats`) |
| `stats/Data/Statistics/Global Statistics.ini` | RL aggregate summary (if `--stats`, if present) |
| `hs_favorites/<System>/<System>_Favorites.ini` | Per-system INI favorites (if `--hs-favorites`) |
| `hs_favorites/<System>/favorites.txt` | Per-system txt favorites (if `--hs-favorites`) |
| `hs_favorites/<System>/<System>.xml` | System XML before attribute stripping (if `--hs-favorites`) |
| `manifest.json` | Index of all backed-up files with original paths |

Only files that exist at scrub time are copied. The backup is not a compressed archive — files can be inspected directly.

### `scrub-restore`

Restore files from a backup created by `scrub --backup-dir`.

```bat
:: Dry-run — show what would be restored without touching files
spindoctor scrub-restore E:\Backups\scrub-20260526_143012

:: Commit the restore
spindoctor scrub-restore E:\Backups\scrub-20260526_143012 --apply
```

`scrub-restore` reads the `manifest.json` inside the backup folder and copies each file back to its original location. Existing files are overwritten. Dry-run by default; pass `--apply` to commit.

#### Recommended workflow

```bat
:: 1. Preview what would be deleted
spindoctor scrub

:: 2. Scrub with backup (backs up then deletes in one step)
spindoctor scrub --backup-dir E:\Backups --apply

:: 3. If you need to undo — restore from the backup
spindoctor scrub-restore E:\Backups\scrub-20260526_143012 --apply
```

---

## `emulator-title`

Manage the per-emulator window-title correction table used by synthetic wheel launchers.

When a game is launched from Favorites, Recently Played, or Most Played, PCLauncher uses `FadeTitle=` in the system-level INI to locate the game window by title instead of PID (which fails for DirectX emulators in exclusive fullscreen). SpinDoctor uses the emulator's registered name as the default `FadeTitle` value — this works automatically for any emulator whose window title contains its name (the vast majority).

Use `emulator-title set` only when the emulator's window title has **no overlap** with its registered name:

```bat
:: Add or update a correction
spindoctor emulator-title set "Supermodel" "Supermodel 3"

:: Remove a correction (built-in entries cannot be removed, only overridden)
spindoctor emulator-title remove "Supermodel"

:: List all effective mappings — shows built-in defaults, user corrections, and overrides
spindoctor emulator-title list
```

Corrections are stored in `~/.spindoctor/config.json` under `emulator_window_titles`. The emulator name must match exactly what RocketLauncherUI shows as the `Default_Emulator` in `Settings/<System>/Emulators.ini`.

---

## Themes

Inventory, back up, and replace HyperSpin's frontend overlay art — the controller-hint glyphs that appear at the bottom of the cabinet UI (Special A / Special B). Three commands: a read-only `theme-scan` for figuring out what's there, a `theme-apply` that swaps a community pack onto the cabinet with full undo support, and a `theme-pack-create` that is the inverse — snapshot the cabinet's current art into a portable pack folder.

> **GUI alternative:** **`File → Browse HyperSpin themes…`** opens a sortable Treeview with a live filter box; double-click a row to open the file in your OS image viewer. The "Apply replacement pack…" button on that window opens a Plan/Apply window for swapping a community pack, with a scope picker that accepts comma-separated system names for multi-system swaps. The Logs & Manifests viewer's **Theme swaps** category surfaces previous applies for one-click undo, a **Show diff** button that renders the swap table as a before/after grid, and a **Revert just \<SYSTEM\>…** button for per-system partial rollback.

### `theme-scan`

Read-only inventory of every overlay file under `<hyperspin>/Media/Frontend/Images/` and per-system `<hyperspin>/Media/<system>/Images/{Special A,Special B}/`. These are the folders HyperHQ → Special A/B writes to and the most common place "controller hint glyph" art lives.

```bat
spindoctor theme-scan                                  :: rich table of every overlay file
spindoctor theme-scan --system MAME                    :: limit to one system
spindoctor theme-scan --keyword xbox                   :: case-insensitive filename filter
spindoctor theme-scan --output D:\theme_audit.csv      :: write CSV instead of table
```

If your bottom-of-screen glyphs are baked into a Flash `.swf` inside `<hyperspin>/Media/Main Menu/Themes/default.zip`, this command can't see them — SWFs need a Flash authoring tool to edit. The report flags that case at the end so you know the difference between "nothing to swap" and "glyphs are inside a SWF".

### `theme-apply`

Replace overlays by walking a source folder of replacement images and matching each filename against the cabinet's frontend art. Filename-based matching, so a single source file can swap multiple targets if the same filename exists in several Special A/B folders.

```bat
:: Dry-run preview — see what a "PS Buttons" pack would replace
spindoctor theme-apply C:\Packs\PS-Buttons

:: Commit the swap. Every overwritten file is backed up first.
spindoctor theme-apply C:\Packs\PS-Buttons --apply

:: Only replace the universal Frontend bucket (no per-system swaps)
spindoctor theme-apply C:\Packs\PS-Buttons --target frontend --apply

:: Limit to one system's Special A/B
spindoctor theme-apply C:\Packs\PS-Buttons --target "Sega Naomi" --apply

:: Apply to multiple systems at once (comma-separated)
spindoctor theme-apply C:\Packs\PS-Buttons --systems "MAME,Sega Naomi" --apply

:: Reverse the most recent run
spindoctor theme-apply --undo latest

:: Reverse a specific run
spindoctor theme-apply --undo ~/.spindoctor/themes/theme-apply-20260508_120000/manifest.json

:: Revert only one system from the most recent run (leave all other wheels untouched)
spindoctor theme-apply --undo latest --revert-system "Sega Naomi"

:: Revert only one system from a specific run
spindoctor theme-apply --undo ~/.spindoctor/themes/theme-apply-20260508_120000/manifest.json --revert-system "MAME"

:: List previous runs
spindoctor theme-apply --list-manifests
```

Every applied swap writes a manifest under `~/.spindoctor/themes/theme-apply-<timestamp>/` with the original files mirrored into a `backup/` subfolder. `--undo` reads the manifest and restores each backup back to its target path. `--revert-system` limits the restore to a single system's files — useful when a multi-system pack swap looks wrong on only one wheel. The GUI's **Show diff** button in the Logs & Manifests viewer renders the same swap table without raw JSON.

**Options:**

| Option | Description |
|--------|-------------|
| `--target` | `all` (default), `frontend` (only universal bucket), or a system name |
| `--systems` | Comma-separated system names — multi-system shortcut (overrides `--target` for system-name filtering) |
| `--apply` | Commit the swap; dry-run without this flag |
| `--undo` | `latest` or a manifest path — reverse a previous run |
| `--revert-system` | System name — pair with `--undo` to roll back only one system |
| `--list-manifests` | List all previous runs and exit |

### `theme-pack-create`

The inverse of `theme-apply`: snapshot the cabinet's current art into a directory tree shaped like a community pack. Use it to back up before installing a swap, share your setup, or migrate themed art alongside a library migration.

```bat
:: Back up all current art before applying a new pack
spindoctor theme-pack-create D:\Packs\MyCurrentArt

:: Only snapshot the universal Frontend bucket
spindoctor theme-pack-create D:\Packs\FrontendOnly --target frontend

:: Only snapshot one system's Special A/B
spindoctor theme-pack-create D:\Packs\MAME-only --target "MAME"
```

The output mirrors the art's scope/bucket: `<output_dir>/Frontend/Frontend/Images/` for universal art, `<output_dir>/<system>/Special A/` and `<output_dir>/<system>/Special B/` for per-system overlays. The folder is accepted directly by `theme-apply` — the cabinet itself is never modified.

**Options:**

| Option | Description |
|--------|-------------|
| `--target` | `all` (default), `frontend`, or a system name — same semantics as `theme-apply --target` |

---

## Diff

Answer "what changed since last week?" without manually diffing folders. Given a `spindoctor-backup-…/` folder (created by `backup create`), lists which files are added, deleted, or modified in each component compared to the live cabinet tree. Comparison is size + modification time (fast; no full hash). Read-only — the live tree and backup are never modified.

```bat
:: Compare a backup against the live cabinet
spindoctor diff E:\Backups\spindoctor-backup-20260101_120000

:: Limit to one component
spindoctor diff E:\Backups\spindoctor-backup-20260101_120000 --component databases
spindoctor diff E:\Backups\spindoctor-backup-20260101_120000 --component roms
```

Output per component:

```
databases
  + Media\Sega Model 3\Sega Model 3.xml       ← added since backup
  − Media\Sega Naomi\Sega Naomi.xml           ← deleted since backup
  ~ Databases\MAME\MAME.xml                   ← modified since backup
  → 1 added, 1 deleted, 1 modified
```

| Symbol | Meaning |
|--------|---------|
| `+`    | File exists in the live tree but not in the backup (added since snapshot) |
| `−`    | File exists in the backup but not in the live tree (deleted since snapshot) |
| `~`    | File exists in both but differs by size or modification time (modified) |

**Options:**

| Option | Description |
|--------|-------------|
| `--component` | Limit the report to one component (`roms`, `databases`, `media`, `emulators`, `rocketlauncher`, `ledblinky`, `settings`) |

---

## LEDBlinky

```bat
spindoctor ledblinky generate              :: dry-run preview
spindoctor ledblinky generate --apply      :: commit controls.ini / colors.ini
spindoctor ledblinky audit
spindoctor ledblinky check                 :: scan for HyperSpin Search-menu compatibility issues
spindoctor ledblinky fix                   :: dry-run preview of the patch
spindoctor ledblinky fix --apply           :: commit the patch
spindoctor ledblinky patch-settings        :: preview Settings.ini changes
spindoctor ledblinky patch-settings --apply                          :: fix in-game unused-button flash
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --apply :: also swap idle animation
spindoctor ledblinky colors list           :: show all Color-RGB.ini definitions
spindoctor ledblinky colors edit Blue      :: inspect current Blue definition
spindoctor ledblinky colors edit Blue --name Turquoise --hex 06BEE1 --apply  :: rename + recolor
```

`generate` builds `controls.ini` and `colors.ini` from MAME `-listxml`, preserving any community-maintained entries already present in `<ledblinky_dir>`. Data comes from a local `mame -listxml` cache — no scraper API, no quota.

`check` / `fix` diagnose and repair the well-known issue where HyperSpin's Search overlay crashes when LEDBlinky is installed:

1. LEDBlinky injects `Start_Hyperspin_Process` / `Exit_Hyperspin_Process` lines into per-menu `Settings.ini` — Search's overlay launcher doesn't tolerate them.
2. `LEDBlinkyControls.xml` has no entry for the Search special menu.

`fix` is reversible: timestamped `.bak` backups are saved next to every modified file, and disabled lines are commented out (not deleted), tagged so you can find them later.

```bat
spindoctor ledblinky fix --menus Search,Genre,Favorites --apply
spindoctor ledblinky fix --output-dir D:\SpinDoctorOutput --apply   :: stage instead of in-place
```

The global `<hyperspin_dir>/Settings/Settings.ini` is never touched — LEDBlinky needs those hooks during gameplay.

`patch-settings` makes two targeted tweaks to `<ledblinky_dir>/Settings.ini`:

| Key | Section | Default fix | Effect |
|-----|---------|-------------|--------|
| `GamePlayLWAFile` | `[GameOptions]` | `""` (empty) | Unassigned buttons go dark during gameplay instead of flashing randomly |
| `FELWAFile` | `[FEOptions]` | _(optional — specify `--fe-lwa`)_ | Swaps `<Random>` for a chosen animation file while browsing HyperSpin |

```bat
spindoctor ledblinky patch-settings --apply                          :: silence in-game unused-button flash
spindoctor ledblinky patch-settings --fe-lwa "" --apply              :: also use static colors while browsing
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --apply :: smooth fade instead of random flash
```

A timestamped `.bak` copy of `Settings.ini` is written before any change. Pass `--no-backup` to skip it.

### `ledblinky colors` — manage named color definitions

`Color-RGB.ini` is LedBlinky's master color dictionary (intensity values 0-48 per channel). Named colors from this file are referenced by value in `Colors.ini` (`P1_COIN=Orange`) and as XML attributes in `LEDBlinkyControls.xml` (`color="Red"`).

`colors list` shows the full table. `colors edit` renames a color and/or changes its intensity values, then propagates the new name throughout all three files atomically.

```bat
spindoctor ledblinky colors list                                                 :: show all definitions
spindoctor ledblinky colors edit Blue                                            :: inspect Blue
spindoctor ledblinky colors edit Blue --name Turquoise --hex 06BEE1 --apply     :: rename + recolor
spindoctor ledblinky colors edit Orange --name Amber --apply                    :: rename only
spindoctor ledblinky colors edit Red --rgb 48,0,12 --apply                      :: shift Red toward pink
```

`--hex RRGGBB` accepts standard 8-bit hex (0-255 per channel) and converts to the 0-48 intensity range stored in `Color-RGB.ini`. `--rgb R,G,B` accepts values directly in the 0-48 range.

Files updated by `edit --apply`:

| File | What changes |
|------|-------------|
| `Color-RGB.ini` | Entry is renamed and/or R,G,B values updated |
| `Colors.ini` | Every line whose value equals the old name exactly (e.g. `P1_COIN=Orange`) is updated |
| `LEDBlinkyControls.xml` | Every `color="<old-name>"` XML attribute is updated |

Hex-value entries in `Colors.ini` (e.g. `ledcolor1=FF0000`) are not touched — they reference colors by raw value, not by name.

A timestamped `.bak` backup is written next to each modified file before any change. Pass `--no-backup` to skip.

---

## Light guns

`spindoctor lightgun` wires Sinden / DemulShooter into RocketLauncher's per-system `Settings/<System>.ini` via `Pre_Launch_App` / `Post_Launch_App` keys. Module .ahk files are never touched, so a stock Tur build remains intact.

```bat
spindoctor lightgun detect                            :: read-only — find Sinden + DemulShooter, list pre-wired systems
spindoctor lightgun detect --apply                    :: also seed lightgun: true for each pre-wired system
spindoctor lightgun audit                             :: status table for every system marked lightgun
spindoctor lightgun configure --system "Sega Naomi"   :: dry-run preview of the INI hooks
spindoctor lightgun configure --system "Sega Naomi" --apply
spindoctor lightgun configure --system MAME --target mame --extra-args "-noresize"
```

Targets are auto-detected for MAME, Sega Naomi/Atomiswave, Model 2, Model 3 (Supermodel), Flycast, ChiHiro, Triforce and similar lightgun-supported emulators — pass `--target <name>` to override. Defaults to `-noresize` extra args (Sinden-friendly); change globally via `demulshooter_extra_args` in config.

A system is considered lightgun-enabled when its entry in `system_overrides` has `"lightgun": true`. `lightgun detect --apply` and `lightgun configure --apply` set the flag automatically.

See [Configuration → demulshooter_path](configuration.md) for setting an explicit DemulShooter location when auto-detection fails.

---

## Maintenance

### `doctor`

Self-diagnose your install: paths, binaries, XML DB integrity, match-cache hygiene, RocketLauncher / LEDBlinky files, optional `lxml`, `ffprobe`. Each check renders ✓ / ⚠ / ✗.

```bat
spindoctor doctor              :: read-only diagnosis
spindoctor doctor --apply      :: also run safe, idempotent repairs
```

`--apply` only does safe, idempotent repairs (prune stale cache, create media folder skeletons, regen `Global Emulators.ini`) — never deletes ROMs/DBs/media.

### `self-doctor`

Diagnose SpinDoctor's *own* state (not the cabinet library). Inspects `~/.spindoctor/` for orphan corrupt-config rescue copies (older than 30 days), oversized manifest dirs (curate / migrations / edits / renames / themes / media_imports / restructures over 50 MB), expired metadata cache size, broken `config.json` / `favorites.json`, stray `.part` files older than 7 days under `<HyperSpin>/Media/`, and orphan atomic-write `.tmp` files older than 5 minutes in the Databases tree or config dir (left behind after a forced shutdown mid-save). Each finding renders with the reclaimable bytes so you can decide whether a cleanup is worth it.

```bat
spindoctor self-doctor              :: read-only diagnosis
spindoctor self-doctor --fix        :: also delete orphan rescue copies, stale .part files, and orphan .tmp write temps
```

Read-only by default. `--fix` performs **only** safe deletions — orphan corrupt-config rescue copies (`config.json.broken-*`), stale `.part` download sidecars, and orphan atomic-write `.tmp` files. Manifests are never auto-deleted because they're the undo path for every destructive command; if a manifest dir is oversized, use `cleanup run` with the category checkboxes you want pruned.

Complements `doctor` (which checks the cabinet library): `self-doctor` answers "is my SpinDoctor install healthy?" while `doctor` answers "is my cabinet healthy?". Run both periodically.

### `tools-audit`

Read-only inventory of third-party arcade tools installed on this PC. Scans `HyperSpin\Tools`, `RocketLauncher\Modules` / `Plugins`, `<emulators_dir>`, Program Files, and the Start Menu for known utilities (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Sinden, DemulShooter, XPadder, JoyToKey, …) and groups them by category — flagging which spindoctor command supersedes each one.

```bat
spindoctor tools-audit
spindoctor tools-audit --extra-path "C:\arcade-utils"
spindoctor tools-audit --max-depth 6 --show-unknown
```

Best run on the arcade cabinet itself. The report is purely informational — it never uninstalls anything, but the "Replaced by" column tells you which tools are safely redundant once the spindoctor equivalent is wired up. `--show-unknown` lists `.exe` files the registry doesn't recognise so the project can grow the registry over time.

See [Standalone tools → Tools audit](standalone-tools.md) for the categorised mapping.

### `ignore`

> **GUI alternative:** the **Curate** tab's Ignore section has add / remove / list buttons, plus a **View / un-ignore…** button that opens a click-to-un-ignore viewer with a system dropdown and multi-select listbox. See [GUI walkthrough](gui.md).

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

One-stop inventory and removal of every cache, manifest, temp dir, and `.bak` backup SpinDoctor produces. Categories cover match / media-pick / pc-titles / metadata / MAME-listxml caches, the preview temp dir, **interrupted-download `.part` sidecars** under `Media/`, **orphan atomic-write `.tmp` files** (`stale-atomic-writes`) left next to XML/JSON files after a forced shutdown mid-save, audit-CSV exports, restructure / misplaced / migration manifests, and HyperSpin / LEDBlinky `.bak` files.

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
