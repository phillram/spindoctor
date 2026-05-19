# First-time setup

A complete walkthrough for standing up a cabinet on a blank Windows PC. Steps 1–7 are prerequisites SpinDoctor itself never touches; 8–11 are SpinDoctor.

> **Two install routes for SpinDoctor itself.** Step 8 below uses `pip install` because the rest of this walkthrough assumes Python is already on the box (`add-system`, `fetch-meta`, etc. all run from `cmd.exe`). If you're locking the cabinet down so end-users never see Python, install the [prebuilt Windows binaries](windows-binaries.md) instead — they include a GUI launcher (`spindoctor-gui.exe`) that wraps the same Setup wizard described in step 9 in a windowed form. Everything from step 9 onward works identically; the binary names are just `spindoctor.exe` instead of the `pip` console scripts.

> **Hardware sanity.** NTFS is recommended for the system drive — `fav rebuild` and `stats-report build-wheel` use hardlinks to mirror media without duplicating bytes. FAT32 / exFAT fall back to copies via `--media-mode copy`.

> **Legal.** Source ROMs and BIOS files only from games and consoles you own. SpinDoctor never downloads either, by design.

## 1. Install Python 3.8+

Download from [python.org/downloads/windows](https://www.python.org/downloads/windows/). During the installer, tick **"Add Python to PATH"** so `python` and `pip` work from any command prompt.

## 2. Install HyperSpin

Install [HyperSpin](http://www.hyperspin-fe.com/) to a stable location, e.g. `C:\HyperSpin`. After install:

```
C:\HyperSpin\
├── Databases\
└── Media\
```

These are the two folders SpinDoctor reads and writes.

## 3. Install RocketLauncher

Install [RocketLauncher](https://rocketlauncher.net/) to e.g. `C:\RocketLauncher`. After install:

```
C:\RocketLauncher\
├── Settings\
│   └── Global Statistics\   ← `recent` and `stats-report` read these
├── Modules\
└── ...
```

## 4. Install your emulators

Install one emulator per system you want on the wheel into a single parent folder, e.g. `C:\Emulators`. The systems below are what `generate-config` knows about — see `spindoctor/rocketlauncher.py` for the full mapping.

| System | Emulator | Source |
|---|---|---|
| Arcade | MAME | [mamedev.org](https://www.mamedev.org/) |
| NES, SNES, GB, GBA, Genesis, MD, … | RetroArch | [retroarch.com](https://www.retroarch.com/) |
| PlayStation 1 | DuckStation | [duckstation.org](https://www.duckstation.org/) |
| PlayStation 2 | PCSX2 | [pcsx2.net](https://pcsx2.net/) |
| Nintendo 64 | Project64 | [pj64-emu.com](https://www.pj64-emu.com/) |
| GameCube / Wii | Dolphin | [dolphin-emu.org](https://dolphin-emu.org/) |
| Sega Saturn / Dreamcast | RetroArch (Beetle Saturn / Flycast cores) | [retroarch.com](https://www.retroarch.com/) |

Each emulator's executable lives in its own folder under `<emulators_dir>` (e.g. `C:\Emulators\MAME\mame.exe`). RocketLauncher launches them by that folder name.

## 5. Place BIOS files

Some emulators (PS1, PS2, Saturn, Dreamcast, GBA in some configs) won't run without a BIOS dump. Drop BIOS files where each emulator expects them — see that emulator's docs. **SpinDoctor does not manage BIOS files.** They migrate along with `<emulators_dir>` only if they live underneath it.

## 6. Drop in your ROMs

Create one root ROM folder (e.g. `C:\Games`) with one sub-folder per system, using HyperSpin's canonical system names:

```
C:\Games\
├── MAME\
├── Nintendo Entertainment System\
├── Super Nintendo Entertainment System\
├── Sony Playstation\
├── Sony Playstation 2\
└── Nintendo 64\
```

The folder name is what SpinDoctor matches against HyperSpin's database name and the Main Menu wheel entry — keep the spelling identical to the HyperSpin convention. (Use `Sony Playstation`, not `PS1` or `psx`.)

## 7. (Optional) LEDBlinky

Skip this unless your cabinet has LED-lit buttons. If you have it, install LEDBlinky to a known folder (e.g. `C:\LEDBlinky`); SpinDoctor's `ledblinky` commands operate on it later.

## 7b. (Optional) Light guns

Skip this unless the cabinet has Sinden (or compatible) light guns. If you do:

1. Install the **Sinden Lightgun** software per the manufacturer's instructions.
2. Place **DemulShooter** somewhere reachable — `C:\RocketLauncher\Modules\DemulShooter\` and `C:\HyperSpin\Tools\DemulShooter\` are both auto-detected by spindoctor. (If you keep it elsewhere, you'll set `demulshooter_path` later.)
3. (Optional) Install the **Arcade Guns Utility** for any Ultimarc Arcade Guns kit.

SpinDoctor wires Sinden + DemulShooter into RocketLauncher per-system *after* you've done `config init` — see step 12 below. Module `.ahk` files (typically Tur-built) are never modified.

## 8. Install SpinDoctor

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor
cd C:\spindoctor
pip install -e .[all]
spindoctor --version
```

See [Installation](installation.md) for à-la-carte extras.

## 9. Configure paths

**Recommended path — the GUI.** Launch SpinDoctor and fill out the Setup tab:

```bat
spindoctor-gui
```

A first-run wizard opens automatically on a fresh cabinet: Welcome → pick `roms_dir` + `hyperspin_dir` (the two required paths) → run `doctor` and read the per-check ✓/⚠/✗ summary. Click Finish and you land on the Setup tab where every other path field has a Browse button. Each row also has an **Open** button next to it that jumps to the configured path in Explorer / Finder so you can verify you picked the right folder. Drag a folder from Explorer / Finder onto any path field to fill it in (Windows binary install; pip users `pip install spindoctor[gui]` or `[all]` for drag-and-drop). Press **Save configuration** and you're done.

**Power users — the CLI.** Same effect, every key prompted in order at the terminal. Both routes write the same `%USERPROFILE%\.spindoctor\config.json`:

```bat
spindoctor config init    :: CLI wizard equivalent of the Setup tab
```

The wizard (either route) prompts for every path (ROMs, HyperSpin, Emulators, RocketLauncher, LEDBlinky, MAME, default output, audit export) with sensible Windows defaults pre-filled. In the CLI, press Enter to accept, type `-` to leave an optional path blank.

**All paths must already exist** — that's why steps 2–7 come first. If a path is rejected, create the folder and re-run.

Re-running the wizard later uses your current values as defaults, so it's safe to refine.

## 10. (Optional) Add a metadata source

`fetch-meta` and `fetch-media` need at least one:

- **[ScreenScraper](https://www.screenscraper.fr/)** — broadest arcade + console coverage; bundles media URLs. Recommended.
- **[TheGamesDB](https://thegamesdb.net/)** — lighter coverage; useful as a fallback.

```bat
spindoctor config set screenscraper_user your_username
spindoctor config set screenscraper_pass your_password
:: or
spindoctor config set thegamesdb_key your_api_key
spindoctor config set default_metadata_source thegamesdb
```

In the GUI, the same fields live at the bottom of the Setup tab under **Scraper credentials**. Password / API-key entries are masked by default — click **Show** next to a field to verify what you pasted, and **Hide** to re-mask. Once both fields are populated, click **Test credentials**: SpinDoctor makes a single authenticated call to ScreenScraper and TheGamesDB and prints a ✓ / ✗ summary directly under the rows, so you catch a bad key before the first `fetch-meta` run instead of after it.

## 11. Bootstrap your wheel

For each system that has ROMs but no database:

```bat
spindoctor systems                                  :: see what's missing
spindoctor add-system "Sony Playstation"            :: dry-run preview
spindoctor add-system "Sony Playstation" --apply    :: commit
spindoctor generate-config --apply                  :: write RocketLauncher INIs + Main Menu
spindoctor doctor                                   :: validate
```

`add-system` registers the system in the Main Menu, creates the database, fetches system-level wheel art, builds per-game entries from your ROMs, and walks the metadata + media fetch flow.

For PC / Steam / Windows libraries use `add-pc-system` instead — it scans nested folders and prompts a title-picker for awkward layouts.

## 12. (Optional) Audit existing tools and wire light guns

If this is an *existing* cabinet that already has a pile of third-party utilities (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Don's HyperTools, Hypersearch, …), get an inventory:

```bat
spindoctor tools-audit
```

The report groups every recognised tool by category and lists which spindoctor command supersedes it. Read-only — never uninstalls anything. See [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have).

If you completed step 7b (light guns):

```bat
spindoctor lightgun detect            :: confirm Sinden + DemulShooter are found
spindoctor lightgun detect --apply    :: seed any RL-INI-pre-wired systems into spindoctor config
spindoctor lightgun configure --system "Sega Naomi" --apply
```

Full walkthrough at [Light guns](lightgun.md).

## 13. Final boot

After this, the cabinet should boot HyperSpin and show your systems. From here the [Workflows](workflows.md) page covers daily refresh, weekly maintenance, backup, migration, and search.
