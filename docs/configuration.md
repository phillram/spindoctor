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
| `mame_executable` | Path to a MAME binary (used by `ledblinky generate` — see below) |
| `metadata_cache_ttl_days` | Days to keep cached scraper responses (default `30`) |
| `backup_before_modify` | Whether XML writes leave a `.bak` next to the file (default `true`) |
| `region_preferences` | Default region order for `curate` (default `["USA", "World", "Europe", "Japan"]`) |
| `demulshooter_path` | Explicit path to `DemulShooter.exe` if auto-detection misses it |
| `demulshooter_extra_args` | Default extra args appended to DemulShooter (default `-noresize`, Sinden-friendly) |
| `ui_scale` | GUI font/widget scale multiplier (float, `0.6`–`2.0`, default `1.0`). Set from `View → UI scale` or `Ctrl++` / `Ctrl+-` / `Ctrl+0` in the GUI. Cabinet owners on 1280×720 typically want `0.9` to fit more on screen. |
| `output_visible` | Whether the GUI's bottom Output panel is shown (bool, default `true`). Toggled from `View → Show output pane`, the status-bar button, or `Ctrl+`` ` ``. |
| `gui_window_geometry` | Last `WIDTHxHEIGHT+X+Y` the GUI window was at when it closed (string, default unset). Restored on the next launch so cabinet owners don't re-resize / re-position every session. Managed automatically — delete it to reset window state. Hand-corrupted values are revalidated against a regex and silently discarded. |
| `gui_last_active_tab` | Index of the tab that was open the last time the GUI closed (int, default unset). Restored on the next launch so users who live in the Curate or Wheels tab don't re-navigate from Setup every time. Managed automatically — delete it to default back to the Setup tab. |
| `first_run_complete` | Whether the first-run wizard has been dismissed (bool, default `false`). Set to `true` after the wizard finishes; existing installs with a valid config silently flip it on first launch of the 2.0 GUI so long-term users aren't pestered. Reset it to `false` to re-trigger the wizard on next launch (or use `Help → First-run setup…`). |
| `last_seen_version` | Last SpinDoctor version that this user saw the GUI's `Help → What's new` dialog for (string, default unset). The dialog auto-opens once per upgraded version on first launch and then stamps this field with `__version__`. Pre-2.0 configs that lack the field are treated as upgraders (combined with `first_run_complete=True`) and shown the dialog on first 2.0 launch; fresh installs (no `first_run_complete`) are skipped because the first-run wizard owns that conversation. Delete the field to force the dialog on the next launch. |

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
- **System uses a Sinden lightgun** — set `"lightgun": true` in the override (or run `spindoctor lightgun configure --system <name> --apply`, which sets it automatically). `lightgun audit` reports on every system with this flag.

## `mame_executable` — which one if I have several?

Cabinet builders often keep multiple MAME folders side-by-side (`MAME (driving)`, `MAME (gun games)`, `MAME (sinden)`, …) so RocketLauncher can launch each ROM with the right `mame.ini` / `cfg/` / `ctrlr/` setup. SpinDoctor doesn't care about that — it only invokes MAME for one thing:

```
mame.exe -listxml
```

That dump is the canonical control schema for every machine MAME knows about, and it's baked into the MAME source. Every variant build produces the same data, so **pick whichever copy is most convenient** and point `mame_executable` at it. Suggested order:

1. The newest MAME version you have installed (newer MAME knows about strictly more ROMs, never fewer).
2. A "vanilla" build over a fork, if you have both — they differ in a handful of obscure machines, but for listxml purposes it's a wash.
3. Whichever folder is closest to your other `Emulators/` subfolders, just so the path is easy to remember.

The listxml output is cached under the SpinDoctor cache directory keyed by system, and only re-runs when the binary's mtime changes — so you pay the (slow) listxml dump once per MAME upgrade, not per audit. Your per-system MAME folders for driving / gun games / etc. are launched by RocketLauncher as usual; SpinDoctor never touches them.

You can leave `mame_executable` blank if you don't use `ledblinky generate` — `audit` and `doctor` will skip the MAME-controls check and warn instead of failing.

## Filesystem considerations

`fav rebuild` and `stats-report build-wheel` mirror media via hardlinks by default — same bytes, two filenames, near-zero extra disk. Hardlinks need a single filesystem that supports them:

| Filesystem | Hardlinks | What to do |
|---|---|---|
| NTFS (system drive on Windows) | ✓ | Default `auto` mode works. |
| ext4, APFS, HFS+ (macOS / Linux) | ✓ | Default `auto` mode works. |
| FAT32, exFAT (USB sticks, SD cards) | ✗ | Pass `--media-mode copy` to wheel rebuilds. |
| Across two different drives | ✗ | Pass `--media-mode copy`. |

`auto` (the default) tries hardlink and silently falls back to copy if it fails — so you usually don't need to think about this until you see media doubling your disk usage on FAT32.

## Environment variables

A small handful of runtime knobs live in environment variables rather than `config.json` because they're per-launch toggles, not persistent cabinet config.

| Variable | Effect |
|---|---|
| `SPINDOCTOR_NO_UPDATE_CHECK=1` | Disables the GUI's GitHub release-tag check on launch and from `Help → Check for updates`. Useful for cabinets behind strict firewalls or when you want a fully hermetic launch. The CLI doesn't run any update check, so this only affects `spindoctor-gui`. |
| `SPINDOCTOR_DISABLE_SINGLETON=1` | Disables the GUI single-instance lock. By default a second `spindoctor-gui` launch on the same machine refuses to start because two GUIs writing to the same HyperSpin XML can corrupt the library. Set this to `1` if you genuinely need two windows open at once (e.g. comparing two separate cabinet configs on one machine) — you're then responsible for not running destructive operations from both. |
| `PYTHONIOENCODING=utf-8` | Forced internally on the frozen Windows exe to keep Rich's tree glyphs (`✓ ⚠ ✗`) rendering on cmd.exe with cp1252. You don't normally need to set it yourself. |
| `PYTHONUNBUFFERED=1` | Set automatically when the GUI shells out so per-row progress (`fetch-meta`, `audit`) streams in real time instead of being buffered until the child exits. |

Anything else you might want to control (concurrency, cache TTL, region preferences, …) lives in `config.json` and is documented above.
