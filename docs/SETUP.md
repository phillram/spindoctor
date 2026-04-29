# SpinDoctor Setup & Migration Guide

A step-by-step companion to the [README](../README.md). Covers what you need to do *outside* SpinDoctor to stand up a fresh arcade cabinet, how to physically migrate one PC to another, how to organize files so SpinDoctor detects them, and a short troubleshooting list.

> **TL;DR.** SpinDoctor is a librarian, not an installer. It manages an existing HyperSpin + RocketLauncher cabinet — it does not install HyperSpin, RocketLauncher, emulators, or supply ROMs / BIOS. Get those in place first, then SpinDoctor automates the rest.

---

## Contents

1. [Before you start](#1-before-you-start)
2. [Fresh install on a blank Windows PC](#2-fresh-install-on-a-blank-windows-pc)
3. [Detecting and organizing your files](#3-detecting-and-organizing-your-files)
4. [Migrating to a new PC](#4-migrating-to-a-new-pc)
5. [Troubleshooting](#5-troubleshooting)
6. [Tips](#6-tips)

---

## 1. Before you start

**What SpinDoctor is not.** It does not install HyperSpin, RocketLauncher, or any emulator. It does not download ROMs or BIOS files. It assumes a working frontend stack already exists and helps you organize, audit, enrich, migrate, and back it up.

**Hardware sanity.** A Windows PC. NTFS is recommended for the system drive — SpinDoctor's `fav rebuild` and `stats-report build-wheel` use hardlinks to mirror media without duplicating bytes (FAT32 / exFAT fall back to copies via `--media-mode copy`).

**Legal.** Source ROMs and BIOS files only from games / consoles you own. SpinDoctor never downloads either, by design.

---

## 2. Fresh install on a blank Windows PC

Do these steps in order. Steps 1–7 are *prerequisites* SpinDoctor itself never touches. Steps 8–10 are SpinDoctor.

### 1. Install Python 3.9+

Download from [python.org/downloads/windows](https://www.python.org/downloads/windows/). During the installer, tick **"Add Python to PATH"** so `python` and `pip` work from any command prompt.

### 2. Install HyperSpin

Download and install [HyperSpin](http://www.hyperspin-fe.com/) to a stable location, e.g. `C:\HyperSpin`. After install, you should see at least:

```
C:\HyperSpin\
├── Databases\
└── Media\
```

Those are the two folders SpinDoctor reads and writes. Don't move them.

### 3. Install RocketLauncher

Download and install [RocketLauncher](https://rocketlauncher.net/) to e.g. `C:\RocketLauncher`. After install, you should see:

```
C:\RocketLauncher\
├── Settings\
│   └── Global Statistics\   ← `recent` and `stats-report` read these
├── Modules\
└── ...
```

### 4. Install your emulators

Install one emulator per system you want on the wheel, into a single parent folder you can point SpinDoctor at later (e.g. `C:\Emulators`). Pick from the canonical sources below — these are the ones SpinDoctor's `generate-config` command targets when it produces RocketLauncher INIs (see `spindoctor/rocketlauncher.py:14-69` for the full system → emulator name mapping).

| System | Recommended emulator | Download |
|---|---|---|
| Arcade | MAME | [mamedev.org](https://www.mamedev.org/) |
| NES, SNES, GB, GBA, Genesis, MD, … | RetroArch | [retroarch.com](https://www.retroarch.com/) |
| PlayStation 1 | DuckStation | [duckstation.org](https://www.duckstation.org/) |
| PlayStation 2 | PCSX2 | [pcsx2.net](https://pcsx2.net/) |
| Nintendo 64 | Project64 | [pj64-emu.com](https://www.pj64-emu.com/) |
| GameCube / Wii | Dolphin | [dolphin-emu.org](https://dolphin-emu.org/) |
| Sega Saturn / Dreamcast | RetroArch (Beetle Saturn / Flycast cores) | [retroarch.com](https://www.retroarch.com/) |

Each emulator's executable should live in its own folder under `<emulators_dir>` (e.g. `C:\Emulators\MAME\mame.exe`, `C:\Emulators\RetroArch\retroarch.exe`). RocketLauncher launches them by that folder name; SpinDoctor's generated configs assume the same convention.

### 5. Place BIOS files

Some emulators (PS1, PS2, Saturn, Dreamcast, GBA in some configs) won't run without a BIOS dump. Drop the BIOS files into the location each emulator expects — see that emulator's docs. **SpinDoctor does not manage BIOS files.** They'll be migrated along with the emulator folder if you later run `spindoctor migrate --include emulators`, but only if they live under `<emulators_dir>`.

### 6. Drop in your ROMs

Create a single root ROM folder (e.g. `C:\Games`) and one sub-folder per system, using HyperSpin's canonical system names. Examples:

```
C:\Games\
├── MAME\
├── Nintendo Entertainment System\
├── Super Nintendo Entertainment System\
├── Sony Playstation\
├── Sony Playstation 2\
└── Nintendo 64\
```

The folder name is what SpinDoctor matches against HyperSpin's database name and the Main Menu wheel entry — keep the spelling identical to the HyperSpin convention. (See the [Directory structure expected](../README.md#directory-structure-expected) section of the README for the full layout.)

### 7. (Optional) LEDBlinky

Skip this unless your cabinet has LED-lit buttons. If you have it, install LEDBlinky to a known folder (e.g. `C:\LEDBlinky`). SpinDoctor's `ledblinky generate / audit / check / fix` commands operate on it later. See [LEDBlinky in the README](../README.md#ledblinky).

### 8. Install SpinDoctor

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor
cd C:\spindoctor
pip install -e .[all]
spindoctor --version
```

The `[all]` extra pulls in `lxml` (lossless XML round-trips), `py7zr` + `rarfile` (7z/rar hashing), and `Pillow` (PNG contact sheets). See [Installation](../README.md#installation) for à-la-carte options.

### 9. Configure paths

```bat
spindoctor config init
```

The wizard prompts for every path (ROMs, HyperSpin, Emulators, RocketLauncher, LEDBlinky) and saves to `%USERPROFILE%\.spindoctor\config.json`. **All paths must already exist** — that's why steps 2–7 come first. If a path is rejected, create the folder, then re-run.

### 10. (Optional) Add a metadata source

For the `fetch-meta` and `fetch-media` commands to work, sign up for one of:

- [ScreenScraper](https://www.screenscraper.fr/) — broadest arcade + console coverage; bundles media URLs. Recommended.
- [TheGamesDB](https://thegamesdb.net/) — lighter coverage; useful as a fallback.

Then store the credentials:

```bat
spindoctor config set screenscraper_user your_username
spindoctor config set screenscraper_pass your_password
```

See [Metadata sources](../README.md#metadata-sources) for the full set of keys.

---

## 3. Detecting and organizing your files

### Canonical layout

SpinDoctor expects this shape (full reference at [Directory structure expected](../README.md#directory-structure-expected)):

```
roms_dir\
├── MAME\…
├── Nintendo Entertainment System\…
└── …

hyperspin_dir\
├── Databases\
│   ├── Main Menu\Main Menu.xml
│   ├── MAME\MAME.xml
│   └── …
└── Media\
    ├── MAME\
    └── …

rocketlauncher_dir\
├── Settings\{<System>.ini, Global Emulators.ini}
└── Settings\Global Statistics\<System>.ini
```

Folder names matter. The ROM-folder name is matched against the HyperSpin database name and the Main Menu wheel entry — use HyperSpin's official spelling (e.g. `Sony Playstation`, not `PS1` or `psx`).

### Detect what's there

```bat
spindoctor systems
```

Lists every folder SpinDoctor has discovered across `<roms_dir>` and `<hyperspin_dir>\Databases\` and shows whether each has a database. Folders with `Database: ✗` are unconfigured — no wheel entry yet.

### Bootstrap each unconfigured system

> **SpinDoctor convention:** every command that writes is **dry-run by default**. Run it bare to preview what would happen, then re-run with `--apply` to commit.

For each system showing `Database: ✗`:

```bat
spindoctor add-system "Sony Playstation"           :: preview
spindoctor add-system "Sony Playstation" --apply   :: commit
```

`add-system` (see the [add-system section](../README.md#add-system) of the README) does, in one shot:

1. Adds the system to the HyperSpin Main Menu wheel
2. Creates the database stub
3. Fetches the system-level wheel art / background / intro video
4. Builds the per-game database from your ROMs
5. Fetches per-game metadata + media

For PC / Steam / Windows libraries, use [`add-pc-system`](../README.md#add-pc-system) instead — it recursively scans nested folders and prompts a title-picker for awkward layouts.

### Wire up RocketLauncher

```bat
spindoctor generate-config              :: preview
spindoctor generate-config --apply      :: commit
```

Writes a per-system RocketLauncher INI (mapping ROMs → emulator) and the HyperSpin Main Menu XML. Emulators are guessed from the system name (MAME → MAME, SNES → RetroArch, PS2 → PCSX2, …); edit the generated INIs to override.

### Verify

```bat
spindoctor doctor              :: read-only diagnosis
spindoctor doctor --apply      :: also run safe, idempotent repairs (prune stale cache,
                                  ::   create media folder skeletons, regen Global Emulators.ini)
```

Validates paths, binaries, XML integrity, RocketLauncher / LEDBlinky files. Each check renders ✓ / ⚠ / ✗.

### Spot-check organization

```bat
spindoctor find-misplaced --all     :: a .nes accidentally dropped into snes\
spindoctor find-dupes --all         :: same title in multiple folders / variants
spindoctor check-discs --all        :: PS1 / Saturn multi-disc layouts
spindoctor stats                    :: % matched / % metadata / % media
```

---

## 4. Migrating to a new PC

Pick the scenario that matches your situation.

### Scenario A — moving the same drive to a new PC

Easiest case. The drive holding ROMs / HyperSpin / RocketLauncher / Emulators plugs into the new PC at the same letters.

1. Install Python, then `pip install -e .[all]` from the SpinDoctor source.
2. `spindoctor config init` — point at the existing folders on the moved drive.
3. `spindoctor doctor` to verify.

That's it — no data move needed.

### Scenario B — copying everything to a fresh PC (network or external drive)

This is the case where SpinDoctor's own `migrate` command isn't quite what you want (`migrate` moves files between drives within one PC). Use `backup` to bridge the gap.

**On the old PC:** snapshot everything to an external drive.

```bat
spindoctor backup create --target E:\Backups --label cabinet-move --include all --apply
```

`--include all` covers ROMs, HyperSpin (databases + media), Emulators, RocketLauncher, LEDBlinky, and SpinDoctor's own settings. See [the backup section](../README.md#backup) for the full component list.

**On the new PC:**

1. Do steps 1–8 of [section 2](#2-fresh-install-on-a-blank-windows-pc) — Python, HyperSpin, RocketLauncher, emulators, BIOS, SpinDoctor itself. **Don't drop in ROMs yet** — the restore brings them.
2. Run `spindoctor config init` and point at where you *want* things on the new PC (e.g. `D:\Games`, `D:\HyperSpin`, …). Folders need to exist; create empty ones first.
3. Restore from the external drive, rerouting paths to match the new PC's config:

   ```bat
   spindoctor backup restore ^
       --backup E:\Backups\spindoctor-backup-YYYYMMDD_HHMMSS-cabinet-move ^
       --use-current-paths --apply
   ```

   `--use-current-paths` ([README:574-577](../README.md#backup)) writes restored files to whatever paths `config.json` currently has — drive letters and folder names can differ from the old PC.
4. `spindoctor doctor` to verify.

### Scenario C — moving to a new drive on the same PC

The README already documents this end-to-end with `spindoctor migrate`. See [Migrating to a new drive](../README.md#migrating-to-a-new-drive) for the dry-run / `--keep-source --verify` / undo workflow.

### Things SpinDoctor does *not* migrate

Be aware before you assume the new PC is fully wired up:

- **Emulator-internal paths.** RetroArch's `retroarch.cfg`, PCSX2's INI, Dolphin's user folder, etc. often hardcode absolute paths to BIOS, save folders, or shaders. SpinDoctor moves the emulator's files but does not rewrite those internal configs. Re-test each emulator and adjust.
- **BIOS files outside `emulators_dir`.** Only included if they live under `<emulators_dir>` and you `--include emulators`.
- **Hardcoded paths inside HyperSpin XML.** SpinDoctor preserves `<game>` content verbatim (intentional, for round-trip safety). If a previous tool wrote absolute Windows paths into the XML, those are not rewritten — the data is what it is. Most well-formed HyperSpin XMLs reference games by name, not by path, so this rarely bites.
- **API credentials.** ScreenScraper / TheGamesDB credentials live in `~/.spindoctor/config.json`. They're covered by `backup --include settings` (or `--include all`) — make sure the backup includes settings so the new PC doesn't have to re-enter them.

---

## 5. Troubleshooting

**`spindoctor: command not found`.** The console scripts didn't end up on PATH. Re-run `pip install -e .` from the repo root, and confirm Python's `Scripts\` directory is on your `Path` environment variable. As a fallback, `python -m spindoctor.cli ...` works without the entry point.

**`config init` rejects a path.** Folders must exist before they can be configured (`spindoctor/config.py:148-154`). Create the folder first, then re-run.

**`spindoctor systems` shows `Database: ✗` next to a folder.** That system has ROMs but no HyperSpin database yet. Run `spindoctor add-system "<exact folder name>"` to bootstrap it.

**`add-system` reports "no ROMs found, drop ROMs in and re-run".** The ROM folder is empty, or the file extensions aren't in SpinDoctor's recognized set for that system. Either drop ROMs in, or teach SpinDoctor about a custom extension via `spindoctor config system set "<System>" --rom-extensions ext1,ext2` (see the [Configuration](../README.md#configuration) section).

**ScreenScraper rate-limiting.** SpinDoctor caps itself at 1 req/sec; the free tier allows 500/day. Wait until midnight UTC or upgrade.

**HyperSpin's Search menu crashes when LEDBlinky is enabled.**

```bat
spindoctor ledblinky check
spindoctor ledblinky fix             :: dry-run preview
spindoctor ledblinky fix --apply     :: commit the patch
```

The fix is reversible — `.bak` files are written and disabled lines are commented out, not deleted. See [LEDBlinky](../README.md#ledblinky).

**Wrong metadata picked during `fetch-meta`.**

```bat
spindoctor match clear --system MAME
spindoctor fetch-meta --system MAME --apply
```

Cached match decisions live at `~/.spindoctor/match_cache/<system>.json`; the previous XML edits are not rolled back, only the cached choice.

**After a migration, wheel art is missing.** Run `spindoctor doctor` to see which paths failed validation. If you migrated with `--keep-source` and later removed the originals, restore the missing component from a `backup`. Hardcoded paths inside HyperSpin XML are not rewritten by `migrate` (rare).

**Recovering from any apply.** Every destructive command writes a manifest to `~/.spindoctor/<category>/` and supports `--undo`. The manifest map is at the [bottom of the README](../README.md#faq) ("Where do the various manifests live?").

---

## 6. Tips

- **Always dry-run first.** Every write command defaults to dry-run; promote to `--apply` only after the preview looks right.
- **Stage to a side folder.** `--output-dir D:\Staging` writes XML changes into a sandbox you can diff before overwriting in place.
- **Snapshot before risky operations.** `spindoctor backup create --target E:\Backups --include settings,databases --label pre-<thing> --apply` is small, fast, and fully reversible.
- **Install the `[xml]` extra.** Lossless XML round-trips (preserves comments + attribute order from HyperHQ). Already included in `[all]`.
- **Audit disk usage before pruning caches.** `spindoctor cleanup audit --detail` lists every category and its size before `cleanup run --apply` deletes anything.
- **Cabinet end-users shouldn't touch a CLI.** Run `spindoctor install-tools` to write Refresh Favorites / Recently Played / Most Played `.bat` files into the HyperSpin Tools menu — the user can refresh wheels from inside the cabinet UI. Schedule them at log-on for fully automatic behavior (see [Auto-refresh wheels on every boot](../README.md#auto-refresh-wheels-on-every-boot)).

---

[← Back to README](../README.md)
