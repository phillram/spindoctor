# SpinDoctor 🩺🕹️

**SpinDoctor** is a command-line tool for managing your [HyperSpin](http://www.hyperspin-fe.com/) (and [RocketUI](https://rocketlauncher.net/)) arcade cabinet library.

Audit your ROM collection, sync Hyperspin XML databases, automatically fill in missing metadata, download media assets, and generate RocketLauncher + RocketUI config files — all from a single CLI with dry-run mode and a non-destructive output directory option.

---

## Table of Contents

- [Installation](#installation)
- [First-Time Setup](#first-time-setup)
- [Commands](#commands)
  - [config](#config)
  - [systems](#systems)
  - [audit](#audit)
  - [inspect](#inspect)
  - [update-db](#update-db)
  - [fetch-meta](#fetch-meta)
  - [fetch-media](#fetch-media)
  - [media-add](#media-add)
  - [generate-config](#generate-config)
  - [ignore](#ignore)
  - [match](#match)
  - [report](#report)
- [ROM Variant Handling](#rom-variant-handling)
- [Fuzzy Matching](#fuzzy-matching)
- [Interactive Match Selection](#interactive-match-selection)
- [Auto-Audit Export](#auto-audit-export)
- [Ignore Lists](#ignore-lists)
- [Media Types](#media-types)
- [Metadata Sources](#metadata-sources)
- [Directory Structure Expected](#directory-structure-expected)
- [Typical Workflows](#typical-workflows)
- [Options Reference](#options-reference)
- [FAQ](#faq)

---

## Installation

**Requirements:** Python 3.9+

```bat
cd C:\path\to\spindoctor
pip install -e .
```

Verify:

```bat
spindoctor --version
```

---

## First-Time Setup

Run once to point SpinDoctor at your directories. Settings are saved to `%USERPROFILE%\.spindoctor\config.json`.

```bat
spindoctor config set roms_dir           "D:\ROMs"
spindoctor config set hyperspin_dir      "D:\HyperSpin"
spindoctor config set emulators_dir      "D:\Emulators"
spindoctor config set rocketlauncher_dir "D:\RocketLauncher"
```

Optional — default output directory so nothing is ever overwritten in-place:

```bat
spindoctor config set output_dir "D:\SpinDoctorOutput"
```

Auto-export an audit CSV after every write operation:

```bat
spindoctor config set auto_audit_export_dir "D:\SpinDoctorAudits"
```

---

## Commands

### `config`

Show or change configuration.

```
spindoctor config show
spindoctor config set <key> <value>
```

**Keys:**

| Key | Description |
|-----|-------------|
| `roms_dir` | Root folder with one sub-folder per system |
| `hyperspin_dir` | Root HyperSpin folder (contains `Databases/` and `Media/`) |
| `emulators_dir` | Root folder with one sub-folder per emulator |
| `rocketlauncher_dir` | Root RocketLauncher folder |
| `output_dir` | Default output folder (blank = write in-place) |
| `auto_audit_export_dir` | Auto-export audit CSV here after any write operation |
| `screenscraper_user` | ScreenScraper username |
| `screenscraper_pass` | ScreenScraper password |
| `thegamesdb_key` | TheGamesDB API key |
| `default_metadata_source` | `screenscraper` or `thegamesdb` |
| `backup_before_modify` | `true` / `false` |
| `match_threshold` | Fuzzy confidence for auto-accept, `0.0`–`1.0` (default `0.80`) |
| `interactive_matching` | `true` / `false` — prompt on ambiguous matches |
| `max_concurrent_downloads` | Integer |
| `strip_variant_tags_in_display_name` | `true` / `false` — when `true`, strips `(Japan)` / `(Rev A)` etc. from stub display names (default `false`, i.e. tags are kept) |

---

### `systems`

List all systems detected across your ROMs and Databases directories.

```
spindoctor systems
```

Shows ROMs folder status, database XML status, and how many ignored games each system has.

---

### `audit`

Compare ROM files against the Hyperspin XML database and media assets.

```
spindoctor audit --system <name>
spindoctor audit --all
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | Audit one system |
| `--all` | Audit all systems |
| `--no-media` | Skip media checks (much faster) |
| `--no-fuzzy` | Skip fuzzy ROM/DB variant matching |
| `--detailed` | After the summary, print per-file detail (size, dimensions, video length) for every game that needs attention |
| `--report PATH` | Write full CSV report |
| `--show-matched` | Also list matched games |

**What it reports:**

- Exact ROM ↔ DB matches
- **Fuzzy matches** — ROMs with variant tags (region, version, revision) that closely match a DB entry
- ROMs with no database entry
- DB entries with no ROM file
- Games with incomplete metadata
- Games with missing media assets
- Ignored game counts

**Examples:**

```bat
spindoctor audit --system MAME
spindoctor audit --all --no-media
spindoctor audit --all --report D:\audit_report.csv
```

---

### `inspect`

Show detailed per-file information for a game or an entire system — the full picture of what's on disk.

```
spindoctor inspect --system <name> --game <rom-name>
spindoctor inspect --system <name> --all
spindoctor inspect --system <name>
```

With no `--game` or `--all`, inspect defaults to showing only games that need attention (missing ROM, metadata, or media).

For every game inspected, two tables are shown:

**ROM** — one row per ROM file on disk:

| Column | Description |
|--------|-------------|
| ✓ / ✗ | File found on disk |
| File | Filename |
| Size | Human-readable file size |
| Ext | File extension |
| Modified | Last modified date/time |
| Path | Full path on disk |

**MEDIA** — one row per media type:

| Column | Description |
|--------|-------------|
| Type | wheel, background, artwork, title, snap, video, trailer, sound, theme |
| ✓ / ✗ | File exists |
| Size | File size |
| Dim / Length | Image dimensions (e.g. `1920×1080`) or video duration (e.g. `0:43`) |
| Ext | Extension of the actual file found |
| Modified | Last modified |
| Path | Full path (or expected path if missing) |

A footer summary shows total on-disk size and missing-media counts across all inspected games.

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | System to inspect (required) |
| `--game NAME` | Single game to inspect |
| `--all` | Every game in the database |
| `--format table\|csv` | Output format |
| `--output PATH` | Write CSV output to file |
| `--no-path` | Show only filenames instead of full paths (narrower output) |

**Video length** is read using `ffprobe` (if FFmpeg is installed) or by parsing the MP4 file header directly — no extra Python packages required.

**Image dimensions** (width × height) are read from PNG and JPEG file headers directly — no Pillow required.

**Examples:**

```bat
rem Single game deep-dive
spindoctor inspect --system MAME --game 1942

rem All games with issues in SNES (compact paths)
spindoctor inspect --system SNES --no-path

rem Full file manifest for all MAME games as CSV
spindoctor inspect --system MAME --all --format csv --output D:\mame_manifest.csv

rem Show only games needing attention in NES (default when no --game or --all)
spindoctor inspect --system "Nintendo Entertainment System"
```

You can also get this same per-file detail appended to the regular `audit` output:

```bat
spindoctor audit --system MAME --detailed
spindoctor audit --all --detailed --no-media   rem skip media scan for speed, then detailed fills it in
```

---

### `update-db`

Sync HyperSpin XML databases to match ROM directories.

```
spindoctor update-db --system <name> [options]
spindoctor update-db --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--add-missing` | Add stub entries for ROMs not in the DB (default: on) |
| `--remove-orphans` | Remove DB entries with no matching ROM |
| `--dry-run` | Show what would change |
| `--output-dir PATH` | Write XMLs here instead of in-place |
| `--keep-variant-tags` | Keep `(Japan)` / `(Rev A)` tags in display names (default) |
| `--strip-variant-tags` | Strip variant tags so all regions/revisions share a base display name |

Every ROM variant (`Mario (v1.2)`, `Mario (USA)`, `Mario (patched)`) is treated as its own independent database entry with its own display name.

By default, the display name keeps the variant tag, so `1942 (Japan).zip` shows as **`1942 (Japan)`** and `1942 (USA).zip` shows as **`1942 (USA)`** — the two are easy to tell apart in HyperSpin / RocketLauncher menus. Pass `--strip-variant-tags` (or set `strip_variant_tags_in_display_name true` in your config) if you'd rather have both render as just **`1942`**.

Backups: a `.YYYYMMDD_HHMMSS.bak` copy is saved before in-place overwrites unless `backup_before_modify` is `false`.

**Examples:**

```bat
spindoctor update-db --system MAME --dry-run
spindoctor update-db --all --remove-orphans --output-dir D:\Output
spindoctor update-db --system "Nintendo Entertainment System"

rem strip region/revision tags from display names for one run
spindoctor update-db --system SNES --strip-variant-tags

rem make stripping the persistent default
spindoctor config set strip_variant_tags_in_display_name true
```

---

### `fetch-meta`

Download and write game metadata (description, year, manufacturer, genre, rating) into the XML database.

```
spindoctor fetch-meta --system <name> [options]
spindoctor fetch-meta --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--source` | `screenscraper` or `thegamesdb` |
| `--all-games` | Refresh every game, even complete ones (default: only updates games with incomplete metadata) |
| `--interactive` / `--auto-best` | Prompt on ambiguous matches / always pick best |
| `--threshold FLOAT` | Minimum confidence for auto-accept (overrides config) |
| `--dry-run` | Show what would be updated, write nothing |
| `--output-dir PATH` | Write updated XMLs here |

**How matching works** (see also [Fuzzy Matching](#fuzzy-matching) and [Interactive Match Selection](#interactive-match-selection)):

1. ROM name is normalised (regions, versions, revisions stripped).
2. A direct lookup is tried first.
3. If no result or confidence is below threshold, a broader search runs.
4. If one candidate clears the threshold — it's accepted automatically.
5. If multiple candidates exist and `interactive_matching` is on — you're prompted to choose.
6. Your choice is cached in `~/.spindoctor/match_cache/` so re-runs skip the prompt.

**Examples:**

```bat
rem Dry run — see what would change for MAME
spindoctor fetch-meta --system MAME --dry-run

rem Fetch all missing metadata, prompt when ambiguous
spindoctor fetch-meta --all --output-dir D:\Output

rem Non-interactive: always accept the best match
spindoctor fetch-meta --all --auto-best

rem Force refresh everything for SNES
spindoctor fetch-meta --system SNES --all-games
```

---

### `fetch-media`

Download media assets from a metadata source.

```
spindoctor fetch-media --system <name> [options]
spindoctor fetch-media --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--types LIST` | Comma-separated media types (default: all) |
| `--source` | Metadata source to use for media URLs |
| `--overwrite` | Re-download and replace existing files |
| `--dry-run` | Show what would be downloaded |
| `--output-dir PATH` | Save media here instead of inside `hyperspin_dir` |

See [Media Types](#media-types) for the full list.

**Examples:**

```bat
rem Download wheel art and backgrounds for MAME (dry run first)
spindoctor fetch-media --system MAME --types wheel,background --dry-run
spindoctor fetch-media --system MAME --types wheel,background

rem Download everything for all systems into staging
spindoctor fetch-media --all --output-dir D:\Output

rem Re-download trailer videos for SNES
spindoctor fetch-media --system SNES --types trailer --overwrite

rem Wheel, title screen, and background only
spindoctor fetch-media --system MAME --types wheel,title,background
```

---

### `media-add`

Manually copy or move a local file into the correct HyperSpin media directory.

```
spindoctor media-add --system <name> --game <rom-name> --type <type> --file <path>
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | System the game belongs to |
| `--game NAME` | ROM name (without extension) |
| `--type TYPE` | One of the [Media Types](#media-types) |
| `--file PATH` | Local source file |
| `--move` | Move the file instead of copying |
| `--overwrite` | Overwrite if file already exists |
| `--output-dir PATH` | Place in this directory instead of `hyperspin_dir` |

**Examples:**

```bat
rem Add a trailer video for 1942
spindoctor media-add --system MAME --game 1942 --type trailer ^
    --file C:\Downloads\1942_trailer.mp4

rem Add a custom title screen image, moving the file
spindoctor media-add --system SNES --game "Super Mario World (USA)" ^
    --type title --file C:\Art\smworld_title.png --move

rem Add background for an NES game, output to staging
spindoctor media-add --system NES --game Castlevania --type background ^
    --file C:\Art\castlevania_bg.jpg --output-dir D:\Output
```

---

### `generate-config`

Generate RocketLauncher system INI files and the HyperSpin Main Menu XML.

```
spindoctor generate-config [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--all` | All systems (default when neither `--all` nor `--system` is given) |
| `--system NAME` | Single system only |
| `--rl / --no-rl` | Generate RocketLauncher INI files (default: on) |
| `--main-menu / --no-main-menu` | Generate `Main Menu.xml` (default: on) |
| `--db-stubs / --no-db-stubs` | Create empty DB XMLs for systems that have none |
| `--dry-run` | Show what would be written |
| `--output-dir PATH` | Write here instead of in-place |

**What gets generated:**

| File | Description |
|------|-------------|
| `RocketLauncher/Settings/<System>.ini` | Per-system emulator and ROM path settings |
| `Databases/Main Menu/Main Menu.xml` | HyperSpin system list (RocketUI reads this) |
| `Databases/<System>/<System>.xml` | Empty database stubs (with `--db-stubs`) |

Emulators are guessed from the system name (MAME → MAME, SNES → RetroArch, N64 → Project64, PS2 → PCSX2, etc.). You can edit the generated INI files to override.

**Examples:**

```bat
rem Preview what would be generated
spindoctor generate-config --dry-run

rem Generate into a staging folder for review
spindoctor generate-config --output-dir D:\Output

rem Generate in-place (rocketlauncher_dir must be configured)
spindoctor generate-config

rem Only regenerate the main menu (e.g. after adding a new system)
spindoctor generate-config --no-rl

rem Generate everything including empty database XMLs for new systems
spindoctor generate-config --db-stubs --output-dir D:\Output
```

---

### `ignore`

Manage per-system and global ignore lists.

Ignored games are skipped by `audit`, `fetch-meta`, `fetch-media`, and `update-db`.

```
spindoctor ignore add <game-name> [--system NAME]
spindoctor ignore remove <game-name> [--system NAME]
spindoctor ignore list [--system NAME]
spindoctor ignore clear [--system NAME]
```

Omit `--system` to add/remove from the **global** ignore list (applies to all systems).

**Examples:**

```bat
rem Ignore a specific MAME ROM globally
spindoctor ignore add "pacman"

rem Ignore a patched ROM only for NES
spindoctor ignore add "Super Mario Bros (patched)" --system "Nintendo Entertainment System"

rem See everything being ignored
spindoctor ignore list

rem Remove from ignore
spindoctor ignore remove "pacman"

rem Clear all ignores for MAME
spindoctor ignore clear --system MAME
```

---

### `match`

View and manage cached metadata match decisions.

When you select a match interactively during `fetch-meta`, your choice is saved to `~/.spindoctor/match_cache/`. SpinDoctor reuses it on the next run so you aren't prompted again.

```
spindoctor match list [--system NAME]
spindoctor match clear [--system NAME]
```

Use `match clear` if you want to re-evaluate your selections (e.g., after updating to a new metadata source).

---

### `report`

Read-only audit report — no changes made.

```
spindoctor report --system <name> [options]
spindoctor report --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--format` | `summary` (default), `table`, or `csv` |
| `--output PATH` | Write report to file |
| `--no-media` | Skip media checks |
| `--no-fuzzy` | Skip fuzzy matching |

**Examples:**

```bat
spindoctor report --all --format summary
spindoctor report --system MAME --format table
spindoctor report --all --format csv --output D:\arcade_report.csv
```

---

## ROM Variant Handling

SpinDoctor treats every ROM file as an independent entry. A ROM named `Super Mario Bros (USA, Rev 1).nes` is a distinct game from `Super Mario Bros (USA).nes` — each gets its own database entry with its own display name, its own metadata fetch, and its own media slot.

By default, the **display name** used as `<description>` in the XML keeps the region / revision tag so that multiple variants of the same game stay distinguishable in HyperSpin / RocketLauncher menus. The base name still gets light cleanup (underscores → spaces, title-case):

| ROM filename | Display name (default) | With `--strip-variant-tags` |
|---|---|---|
| `1942 (Japan)` | `1942 (Japan)` | `1942` |
| `1942 (USA)` | `1942 (USA)` | `1942` |
| `Super Mario Bros (USA, Rev 1)` | `Super Mario Bros (USA, Rev 1)` | `Super Mario Bros` |
| `Earthbound (USA) [patched]` | `Earthbound (USA) [patched]` | `Earthbound` |
| `super_mario_bros` | `Super Mario Bros` | `Super Mario Bros` |

If you'd rather have both `1942 (Japan)` and `1942 (USA)` appear as just `1942`, pass `--strip-variant-tags` to `update-db` for a single run, or set it as the default:

```bat
spindoctor config set strip_variant_tags_in_display_name true
```

The `name` attribute (used by HyperSpin as the key) is always the exact ROM filename stem, preserving all variant tags regardless of the display-name setting.

---

## Fuzzy Matching

During `audit` and `fetch-meta`, SpinDoctor can fuzzy-match ROM filenames against database entries and metadata search results.

**How it works:**

1. Region codes, version numbers, revision labels, and bracket tags are stripped.
2. Punctuation is normalised.
3. A sequence-similarity ratio is computed between the cleaned names.
4. Matches above `match_threshold` (default `0.80`) are accepted; below it they're flagged for review.

**In `audit`:** fuzzy matches are shown as a separate "ROM variants" table rather than as "ROMs not in DB", so you can see `1942 (Japan, Rev A)` → `1942` with 100% confidence at a glance.

**In `fetch-meta`:** the same normalisation is applied to search queries so `Super Mario Bros. (USA)` searches for `Super Mario Bros` rather than the raw filename.

Adjust the threshold:

```bat
spindoctor config set match_threshold 0.75
```

Disable fuzzy matching in a single run:

```bat
spindoctor audit --no-fuzzy
spindoctor report --no-fuzzy
```

---

## Interactive Match Selection

When a metadata search returns multiple candidates and confidence is below `match_threshold`, SpinDoctor shows a selection table and asks you to pick:

```
┌────────────────────────────── Multiple matches for 'earthbound' ────────────────────────────────┐
│  #  │ Title                  │ Year  │ Publisher    │ Conf. │ Review link                       │
│─────┼────────────────────────┼───────┼──────────────┼───────┼───────────────────────────────────│
│  1  │ EarthBound             │ 1995  │ Nintendo     │  87%  │ https://screenscraper.fr/...      │
│  2  │ Earthbound Beginnings  │ 1989  │ Nintendo     │  71%  │ https://screenscraper.fr/...      │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
Number to select · 0 to skip · Enter to accept #1
  Choice for 'earthbound' [1]:
```

- The **Review link** opens the game's page on ScreenScraper or TheGamesDB so you can verify before committing.
- Enter `0` to skip this game entirely this run.
- Your choice is **cached** in `~/.spindoctor/match_cache/<system>.json` and reused automatically on future runs.
- To re-evaluate: `spindoctor match clear --system MAME`.
- To skip all prompts and always pick the highest-scoring result: `--auto-best`.

Toggle interactive mode globally:

```bat
spindoctor config set interactive_matching false
```

---

## Auto-Audit Export

When `auto_audit_export_dir` is configured, SpinDoctor automatically runs a full audit and saves a timestamped CSV after every write operation (`update-db`, `fetch-meta`, `fetch-media`, `generate-config`).

```bat
spindoctor config set auto_audit_export_dir "D:\SpinDoctorAudits"
```

This creates files like `D:\SpinDoctorAudits\audit_20260427_143021.csv` after each run so you always have a record of what's still missing.

Dry runs also trigger an auto-export so you can review the full state before committing to changes.

---

## Ignore Lists

Use ignore lists to permanently exclude games from all SpinDoctor operations — useful for prototypes, regional duplicates, hacks, or demos you don't care about.

Ignored games appear in `audit` output with a count but are not flagged as problems, and are skipped by `fetch-meta`, `fetch-media`, and `update-db`.

```bat
rem Ignore globally (all systems)
spindoctor ignore add "cheat_rom"

rem Ignore only for MAME
spindoctor ignore add "1942c" --system MAME

rem See what's ignored
spindoctor ignore list

rem Remove from ignore
spindoctor ignore remove "1942c" --system MAME
```

---

## Media Types

| Type | HyperSpin path | Description |
|------|---------------|-------------|
| `wheel` | `Media/<System>/Images/Wheel/` | Transparent PNG logo for the spinner |
| `background` | `Media/<System>/Images/Backgrounds/` | Full-screen background |
| `artwork` | `Media/<System>/Images/Artwork1/` | Box art |
| `title` | `Media/<System>/Images/Artwork2/` | Title screen screenshot |
| `snap` | `Media/<System>/Images/Artwork3/` | Gameplay screenshot |
| `video` | `Media/<System>/Video/` | Attract / intro video |
| `trailer` | `Media/<System>/Video/Trailers/` | Full game trailer |
| `sound` | `Media/<System>/Sound/` | Sound clip on game select |
| `theme` | `Media/<System>/Themes/` | HyperSpin SWF/ZIP theme |

Use `media-add` to manually place a local file into any of these slots.

---

## Metadata Sources

### ScreenScraper (recommended)

[ScreenScraper](https://www.screenscraper.fr/) has the most complete arcade and console database including media URLs (wheel, fanart, title, gameplay video).

1. Register free at https://www.screenscraper.fr/
2. Configure:
   ```bat
   spindoctor config set screenscraper_user your_username
   spindoctor config set screenscraper_pass your_password
   ```

### TheGamesDB

[TheGamesDB](https://thegamesdb.net/) is a community database with broad platform coverage.

1. Get a free API key at https://thegamesdb.net/
2. Configure:
   ```bat
   spindoctor config set thegamesdb_key your_api_key
   ```

### Switching sources

```bat
rem Use TheGamesDB for a single run
spindoctor fetch-meta --system SNES --source thegamesdb

rem Change the global default
spindoctor config set default_metadata_source thegamesdb
```

---

## Directory Structure Expected

```
roms_dir/
├── MAME/
│   ├── 1942.zip
│   ├── 1942 (Japan, Rev B).zip       ← treated individually
│   └── pacman.zip
├── Nintendo Entertainment System/
│   ├── Super Mario Bros (USA).nes
│   └── Super Mario Bros (USA, Rev 1).nes   ← its own DB entry
└── ...

hyperspin_dir/
├── Databases/
│   ├── Main Menu/
│   │   └── Main Menu.xml             ← generated by generate-config
│   ├── MAME/
│   │   └── MAME.xml
│   └── Nintendo Entertainment System/
│       └── Nintendo Entertainment System.xml
└── Media/
    ├── MAME/
    │   ├── Images/
    │   │   ├── Wheel/                ← wheel art
    │   │   ├── Backgrounds/          ← backgrounds
    │   │   ├── Artwork1/             ← box art
    │   │   ├── Artwork2/             ← title screens
    │   │   └── Artwork3/             ← gameplay snaps
    │   ├── Video/
    │   │   └── Trailers/             ← trailer videos
    │   ├── Sound/
    │   └── Themes/
    └── ...

rocketlauncher_dir/
└── Settings/
    ├── MAME.ini                      ← generated by generate-config
    └── Nintendo Entertainment System.ini

emulators_dir/
├── MAME/
└── RetroArch/
```

---

## Typical Workflows

### Initial setup — new arcade build

```bat
rem 1. Configure paths
spindoctor config set roms_dir D:\ROMs
spindoctor config set hyperspin_dir D:\HyperSpin
spindoctor config set rocketlauncher_dir D:\RocketLauncher
spindoctor config set screenscraper_user myuser
spindoctor config set screenscraper_pass mypass
spindoctor config set output_dir D:\SpinDoctorOutput
spindoctor config set auto_audit_export_dir D:\SpinDoctorAudits

rem 2. See what systems you have
spindoctor systems

rem 3. Generate RocketLauncher INIs and Main Menu XML (into staging first)
spindoctor generate-config --dry-run
spindoctor generate-config --output-dir D:\SpinDoctorOutput

rem 4. Sync all databases (dry run first)
spindoctor update-db --all --dry-run
spindoctor update-db --all --output-dir D:\SpinDoctorOutput

rem 5. Review the auto-exported audit CSV, then fetch metadata
spindoctor fetch-meta --all --output-dir D:\SpinDoctorOutput

rem 6. Download priority media (wheel and background first — fastest visible improvement)
spindoctor fetch-media --all --types wheel,background --output-dir D:\SpinDoctorOutput
```

### Handling ROM variants

```bat
rem Each variant shows up individually in the audit
spindoctor audit --system MAME

rem Fuzzy matches show ROMs that are variants of DB entries
rem e.g. "1942 (Japan, Rev B).zip"  →  DB entry "1942" at 100%

rem update-db adds each variant as its own entry with a cleaned name
spindoctor update-db --system MAME --dry-run
```

### Dealing with ambiguous matches

```bat
rem Run fetch-meta interactively to hand-pick correct matches
spindoctor fetch-meta --system MAME --interactive

rem Review what you've selected so far
spindoctor match list --system MAME

rem Re-evaluate selections for a system (clear cache)
spindoctor match clear --system MAME
```

### Ignoring prototypes and hacks

```bat
rem Add individual games to the ignore list
spindoctor ignore add "mame_cheat" --system MAME
spindoctor ignore add "Super Mario Bros (hack)"  --system "Nintendo Entertainment System"

rem Or add globally
spindoctor ignore add "test_rom"

rem See the full ignore list
spindoctor ignore list
```

### Add custom media manually

```bat
rem You found a great trailer for Street Fighter II — add it directly
spindoctor media-add --system MAME --game "sf2" --type trailer ^
    --file "C:\Downloads\sf2_trailer.mp4"

rem Add a hi-res background, moving the file into place
spindoctor media-add --system MAME --game "1942" --type background ^
    --file "C:\Art\1942_bg.jpg" --move

rem Preview what would happen without writing
spindoctor media-add --system MAME --game "1942" --type title ^
    --file "C:\Art\1942_title.png" --output-dir D:\Output
```

### Regular maintenance

```bat
rem Full health check
spindoctor report --all --format summary

rem Export detailed CSV for review
spindoctor report --all --format csv --output D:\weekly_audit.csv

rem Grab any missing media that's appeared since last run
spindoctor fetch-media --all --types wheel,background,video
```

---

## Options Reference

All commands that write files accept these options:

| Option | Effect |
|--------|--------|
| `--dry-run` | Print what would happen — nothing is written |
| `--output-dir PATH` | Write all output here (mirrors HyperSpin folder structure) |

When `--output-dir` is used, the tool mirrors the exact folder structure so you can inspect results and manually copy them over to your live cabinet.

---

## FAQ

**My ROM filenames have region codes like `(USA)` or `(Japan)`. Will they match correctly?**

Yes. SpinDoctor strips region/version/revision tags before searching (e.g., `Super Mario Bros (USA, Rev 1)` searches for `Super Mario Bros`). If the result is ambiguous you'll be shown options to pick from interactively, with a link to the game page for verification.

**I have `1942 (Japan).zip` and `1942 (USA).zip` — will they both get entries?**

Yes. Each ROM file gets its own individual database entry. The DB `name` is the exact stem (`1942 (Japan)`, `1942 (USA)`), and by default the display name keeps the variant tag too (`1942 (Japan)`, `1942 (USA)`) so the two stay distinguishable in your menus. If you'd rather both appear as just `1942`, pass `--strip-variant-tags` to `update-db` or run `spindoctor config set strip_variant_tags_in_display_name true`. They are never merged either way.

**Will SpinDoctor overwrite my existing data?**

No, by default it backs up every XML it modifies (`.YYYYMMDD_HHMMSS.bak`). Use `--output-dir` to write everything to a staging directory first. Set `backup_before_modify false` to disable backups if you use version control instead.

**Does this work with RocketUI / RocketLauncher?**

Yes. RocketUI uses the same HyperSpin `Databases/` and `Media/` structure. SpinDoctor reads and writes those directories directly. The `generate-config` command also creates RocketLauncher's per-system `Settings/<System>.ini` files.

**ScreenScraper rate-limits me. What do I do?**

SpinDoctor rate-limits itself to 1 request/second. If you hit the daily quota (500 requests on the free tier), wait until midnight UTC. A paid ScreenScraper subscription raises this limit significantly.

**I selected the wrong match. How do I redo it?**

```bat
spindoctor match clear --system <system>
```

Then re-run `fetch-meta`. Your previous XML changes won't be rolled back — only the cached match decision is cleared.

**A game I added to the ignore list still shows up in the audit CSV.**

The game will still appear in the CSV with `ignored=True` but won't be counted in the "needs attention" totals or flagged as a problem.

---

## Ideas & Suggested Additions

Potential future commands that would complement the current feature set:

| Command | What it would do |
|---------|-----------------|
| `sync` | One-shot: `update-db` + `fetch-meta` + `fetch-media` in a single command |
| `clean` | Find and optionally delete orphaned media files that have no matching ROM or DB entry |
| `verify-roms` | Check ZIP/7z integrity and report corrupt archives before you discover them mid-session |
| `stats` | Library statistics dashboard — total ROMs, coverage percentages, media completeness per system |
| `export-list` | Export a printable / shareable game list (HTML or text) with artwork thumbnails |

To request a feature or report a bug: open an issue at the project repository.
