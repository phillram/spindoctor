# Configuration

Settings live at `%USERPROFILE%\.spindoctor\config.json` (or `~/.spindoctor/config.json` on macOS / Linux). Run the wizard once, then refine individual values as needed.

## The wizard

```bat
spindoctor config init
```

Prompts for every path-based setting with sensible Windows defaults. Press Enter to accept, type `-` to leave an optional path blank. Re-running uses your current values as defaults — safe to refine.

## Showing and changing values

```bat
spindoctor config show
spindoctor config set <key> <value>
```

## Most-used keys

| Key | Description |
|---|---|
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
| `backup_before_modify` | Whether XML writes leave a `.bak` next to the file (default `true`) |
| `region_preferences` | Default region order for `curate` (default `["USA", "World", "Europe", "Japan"]`) |

## Per-system overrides

Teach SpinDoctor about a system it doesn't natively know — custom emulators, unusual extensions, alternative scraper IDs, layout (per-rom-file vs. per-game-folder):

```bat
spindoctor config system set "Sony Playstation 7" ^
    --screenscraper-id 999 ^
    --rom-extensions ps7,iso ^
    --layout per-game-folder ^
    --emulator RPCS7

spindoctor config system list
spindoctor config system clear "Sony Playstation 7"
```

Common reasons to use overrides:

- **`add-system` reports "no ROMs found"** — the file extension isn't in the recognized set. Add it via `--rom-extensions`.
- **System has its own metadata IDs on ScreenScraper** — set `--screenscraper-id`.
- **Multi-disc consoles where each game is a folder** — `--layout per-game-folder`.

## Filesystem considerations

`fav rebuild` and `stats-report build-wheel` mirror media via hardlinks by default — same bytes, two filenames, near-zero extra disk. Hardlinks need a single filesystem that supports them:

| Filesystem | Hardlinks | What to do |
|---|---|---|
| NTFS (system drive on Windows) | ✓ | Default `auto` mode works. |
| ext4, APFS, HFS+ (macOS / Linux) | ✓ | Default `auto` mode works. |
| FAT32, exFAT (USB sticks, SD cards) | ✗ | Pass `--media-mode copy` to wheel rebuilds. |
| Across two different drives | ✗ | Pass `--media-mode copy`. |

`auto` (the default) tries hardlink and silently falls back to copy if it fails — so you usually don't need to think about this until you see media doubling your disk usage on FAT32.
