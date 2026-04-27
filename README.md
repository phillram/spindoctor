# SpinDoctor 🩺🕹️

**SpinDoctor** is a command-line tool for managing your [HyperSpin](http://www.hyperspin-fe.com/) (and [RocketUI](https://rocketlauncher.net/)) arcade cabinet library.

Audit your ROM collection against the HyperSpin XML databases, find and fix missing metadata, and automatically download wheel art, backgrounds, videos, and sounds — all from a single CLI with a built-in dry-run mode so nothing surprises you.

---

## Table of Contents

- [Installation](#installation)
- [First-Time Setup](#first-time-setup)
- [Commands](#commands)
  - [config](#config)
  - [systems](#systems)
  - [audit](#audit)
  - [update-db](#update-db)
  - [fetch-meta](#fetch-meta)
  - [fetch-media](#fetch-media)
  - [report](#report)
- [Media Types](#media-types)
- [Metadata Sources](#metadata-sources)
- [Directory Structure Expected](#directory-structure-expected)
- [Typical Workflows](#typical-workflows)
- [Options Reference](#options-reference)
- [Frequently Asked Questions](#frequently-asked-questions)

---

## Installation

**Requirements:** Python 3.9+

```bat
cd C:\path\to\spindoctor
pip install -e .
```

This installs the `spindoctor` command globally in your Python environment.

Verify it works:

```bat
spindoctor --version
```

---

## First-Time Setup

Run these once to point SpinDoctor at your directories. Settings are saved to `%USERPROFILE%\.spindoctor\config.json`.

```bat
spindoctor config set roms_dir      "D:\ROMs"
spindoctor config set hyperspin_dir "D:\HyperSpin"
spindoctor config set emulators_dir "D:\Emulators"
```

Optional — set a default output directory so SpinDoctor never writes over your live files:

```bat
spindoctor config set output_dir "D:\SpinDoctorOutput"
```

Confirm everything looks right:

```bat
spindoctor config show
```

---

## Commands

### `config`

Show or change configuration values.

```
spindoctor config show
spindoctor config set <key> <value>
```

**Keys:**

| Key | Description |
|-----|-------------|
| `roms_dir` | Root folder that contains one sub-folder per system |
| `hyperspin_dir` | Root HyperSpin folder (must contain `Databases/` and `Media/`) |
| `emulators_dir` | Root folder that contains one sub-folder per emulator |
| `output_dir` | Default output folder (leave blank to write in-place) |
| `screenscraper_user` | ScreenScraper username |
| `screenscraper_pass` | ScreenScraper password |
| `thegamesdb_key` | TheGamesDB API key |
| `default_metadata_source` | `screenscraper` or `thegamesdb` |
| `backup_before_modify` | `true` / `false` — auto-backup XML before overwriting |
| `max_concurrent_downloads` | Integer, default `3` |

**Examples:**

```bat
spindoctor config set screenscraper_user myuser
spindoctor config set screenscraper_pass mypassword
spindoctor config set backup_before_modify true
```

---

### `systems`

List all systems SpinDoctor can find, based on your `roms_dir` and `Databases/` folder.

```
spindoctor systems
```

**Output:** A table showing each system name, whether a ROM folder exists, and whether a database XML file exists.

---

### `audit`

Compare your ROM files against the HyperSpin XML database entries and media assets.

```
spindoctor audit --system <name>
spindoctor audit --all
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | Audit a single system |
| `--all` | Audit every detected system |
| `--no-media` | Skip media file checks (much faster) |
| `--report PATH` | Write results to a CSV file |
| `--show-matched` | Also list correctly matched games |

**What it checks:**

- ROMs present in the folder but **not listed** in the XML database
- Database entries that have **no corresponding ROM** file
- Games with **incomplete metadata** (missing year, manufacturer, genre, or description)
- Games with **missing media** (wheel art, backgrounds, videos, sounds)

**Examples:**

```bat
rem Audit MAME only
spindoctor audit --system MAME

rem Audit everything, skip slow media check
spindoctor audit --all --no-media

rem Audit and export a CSV for review
spindoctor audit --all --report D:\audit_report.csv
```

---

### `update-db`

Sync the HyperSpin XML database files to match the contents of your ROM folders.

```
spindoctor update-db --system <name> [options]
spindoctor update-db --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | Target one system |
| `--all` | Update all systems |
| `--add-missing` | Add stub entries for ROMs not in the DB (default: on) |
| `--remove-orphans` | Remove DB entries that have no matching ROM |
| `--dry-run` | Show what would change — write nothing |
| `--output-dir PATH` | Write updated XMLs here instead of in-place |

> **Stub entries** contain only the ROM name and a cleaned-up display name. Run `fetch-meta` afterward to fill in the rest of the metadata.

> **Backups:** When writing in-place, SpinDoctor saves a `.YYYYMMDD_HHMMSS.bak` copy of the original XML unless `backup_before_modify` is `false`.

**Examples:**

```bat
rem Preview what would be added to the MAME database
spindoctor update-db --system MAME --dry-run

rem Add missing games and remove orphans, output to a staging folder
spindoctor update-db --all --remove-orphans --output-dir D:\Output

rem Update in-place (backups created automatically)
spindoctor update-db --system "Nintendo Entertainment System"
```

---

### `fetch-meta`

Download game metadata (description, year, manufacturer, genre, rating) from a metadata source and write it into the XML database.

```
spindoctor fetch-meta --system <name> [options]
spindoctor fetch-meta --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | Target one system |
| `--all` | All systems |
| `--source` | `screenscraper` or `thegamesdb` (overrides config default) |
| `--missing-only` | Only update games with incomplete metadata (default: on) |
| `--all-games` | Refresh metadata for every game, even complete ones |
| `--dry-run` | Fetch data and show what would change — write nothing |
| `--output-dir PATH` | Write updated XMLs here instead of in-place |

**Requirements:** Configure credentials first (see [Metadata Sources](#metadata-sources)).

**Examples:**

```bat
rem Dry run — see what metadata would be fetched for MAME
spindoctor fetch-meta --system MAME --dry-run

rem Fetch missing metadata for all systems, save to staging folder
spindoctor fetch-meta --all --output-dir D:\Output

rem Force a full refresh of all SNES metadata
spindoctor fetch-meta --system SNES --all-games
```

---

### `fetch-media`

Download media assets from a metadata source and save them into the correct HyperSpin `Media/` folder structure.

```
spindoctor fetch-media --system <name> [options]
spindoctor fetch-media --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | Target one system |
| `--all` | All systems |
| `--types LIST` | Comma-separated media types (default: all). See [Media Types](#media-types) |
| `--source` | Metadata source to use for media URLs |
| `--missing-only` | Only download media that doesn't already exist (default: on) |
| `--overwrite` | Re-download and overwrite existing media files |
| `--dry-run` | Show what would be downloaded — write nothing |
| `--output-dir PATH` | Save media here instead of inside `hyperspin_dir` |

**Examples:**

```bat
rem Download only wheel art and backgrounds for MAME (dry run first)
spindoctor fetch-media --system MAME --types wheel,background --dry-run
spindoctor fetch-media --system MAME --types wheel,background

rem Download everything for all systems into a staging folder
spindoctor fetch-media --all --output-dir D:\Output

rem Re-download only videos for SNES
spindoctor fetch-media --system SNES --types video --overwrite

rem Download artwork and sounds only
spindoctor fetch-media --system MAME --types artwork,sound
```

---

### `report`

Generate a read-only audit report without modifying anything.

```
spindoctor report --system <name> [options]
spindoctor report --all [options]
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--system NAME` | One system |
| `--all` | All systems |
| `--format` | `table` (default), `summary`, or `csv` |
| `--output PATH` | Write the report to a file |
| `--no-media` | Skip media checks |

**Examples:**

```bat
rem Quick summary table for all systems
spindoctor report --all --format summary

rem Full table report for MAME
spindoctor report --system MAME

rem Export CSV report for spreadsheet review
spindoctor report --all --format csv --output D:\arcade_report.csv
```

---

## Media Types

| Type | HyperSpin Path | Description |
|------|---------------|-------------|
| `wheel` | `Media/<System>/Images/Wheel/` | PNG logo/wheel art used in the spinner |
| `background` | `Media/<System>/Images/Backgrounds/` | Full-screen background image |
| `artwork` | `Media/<System>/Images/Artwork1/` | Box art / cabinet art |
| `video` | `Media/<System>/Video/` | Attract / intro video (MP4) |
| `sound` | `Media/<System>/Sound/` | Sound clip played on game select |
| `theme` | `Media/<System>/Themes/` | HyperSpin SWF/ZIP theme package |

---

## Metadata Sources

### ScreenScraper (recommended)

[ScreenScraper](https://www.screenscraper.fr/) has the most complete arcade and console database, including media URLs (wheel, fanart, video).

1. Register a free account at https://www.screenscraper.fr/
2. Configure credentials:
   ```bat
   spindoctor config set screenscraper_user your_username
   spindoctor config set screenscraper_pass your_password
   ```

### TheGamesDB

[TheGamesDB](https://thegamesdb.net/) is a community-maintained database with broad platform coverage.

1. Register and get a free API key at https://thegamesdb.net/
2. Configure:
   ```bat
   spindoctor config set thegamesdb_key your_api_key
   ```

### Switching Sources

```bat
rem Use TheGamesDB for a single fetch-meta run
spindoctor fetch-meta --system SNES --source thegamesdb

rem Change the default for all future runs
spindoctor config set default_metadata_source thegamesdb
```

---

## Directory Structure Expected

```
roms_dir/
├── MAME/
│   ├── 1942.zip
│   └── pacman.zip
├── Nintendo Entertainment System/
│   └── Super Mario Bros (USA).nes
└── ...

hyperspin_dir/
├── Databases/
│   ├── MAME/
│   │   └── MAME.xml
│   └── Nintendo Entertainment System/
│       └── Nintendo Entertainment System.xml
└── Media/
    ├── MAME/
    │   ├── Images/
    │   │   ├── Wheel/
    │   │   ├── Backgrounds/
    │   │   └── Artwork1/
    │   ├── Video/
    │   ├── Sound/
    │   └── Themes/
    └── ...

emulators_dir/
├── MAME/
└── RetroArch/
```

---

## Typical Workflows

### First run — full audit

```bat
rem 1. See what systems you have
spindoctor systems

rem 2. Full audit (skip media check for speed)
spindoctor audit --all --no-media --report D:\first_audit.csv

rem 3. Review the CSV, then update databases
spindoctor update-db --all --dry-run
spindoctor update-db --all
```

### Fill in missing metadata

```bat
rem Dry run first
spindoctor fetch-meta --system MAME --dry-run

rem Run for real, save to staging so you can review before committing
spindoctor fetch-meta --all --output-dir D:\SpinDoctorOutput
```

### Download missing media

```bat
rem Start with just wheel art — fastest and most visible improvement
spindoctor fetch-media --all --types wheel --output-dir D:\SpinDoctorOutput

rem Once happy, add backgrounds and videos
spindoctor fetch-media --all --types background,video --output-dir D:\SpinDoctorOutput
```

### Check what's still missing after a download pass

```bat
spindoctor report --all --format summary
```

---

## Options Reference

All commands that modify data accept `--dry-run` and `--output-dir`:

| Option | Effect |
|--------|--------|
| `--dry-run` | Print what would happen — nothing is written |
| `--output-dir PATH` | Write all output (XMLs, media) here instead of in-place |

When `--output-dir` is used, the tool mirrors the HyperSpin folder structure under that directory, so you can inspect the results and manually copy them over.

---

## Frequently Asked Questions

**My ROM filenames have region codes like `(USA)` or `(Japan)` — will SpinDoctor match them?**

SpinDoctor uses the ROM filename stem (without extension) as the database `name` attribute, which is how HyperSpin works. The ScreenScraper API can often match regional filenames via its ROM name lookup. For best results, use No-Intro or TOSEC named ROMs.

**Will SpinDoctor overwrite my existing HyperSpin data?**

Not without permission. When writing in-place, SpinDoctor creates a `.bak` backup of every XML it modifies (unless `backup_before_modify` is set to `false`). Use `--output-dir` to write everything to a staging directory first.

**Does this work with RocketUI / RocketLauncher?**

Yes. RocketUI uses the same HyperSpin `Databases/` and `Media/` directory structure. SpinDoctor reads and writes those directories directly, so changes are immediately visible in both frontends.

**ScreenScraper says "too many requests" — what do I do?**

SpinDoctor rate-limits itself to 1 request per second by default, which respects ScreenScraper's free-tier limits. If you hit the daily quota, wait until midnight UTC and re-run. Paid ScreenScraper accounts have higher quotas.

**Can I run just one game instead of a whole system?**

Not currently — the minimum scope is a system. Filter the output with `--report` and a CSV if you need to inspect individual games.
