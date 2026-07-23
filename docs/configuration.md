# Configuration

Every persistent setting SpinDoctor reads — cabinet paths, scraper credentials, MAME location, per-system overrides, GUI window state — and how to change them from the CLI or by editing `config.json` directly. For environment-variable knobs (per-launch toggles like `SPINDOCTOR_NO_UPDATE_CHECK`), see [Environment variables](#environment-variables) at the bottom.

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
| `intro_randomizer_dir` | Folder containing the Intro Video Randomizer's `Random.ini` (e.g. `D:\Arcade\Media\Frontend\Video\Intro Video Randomizer`). Used by `spindoctor introvideo` — see [Command reference → Intro Video Randomizer](commands.md#intro-video-randomizer). |
| `screenscraper_user` / `screenscraper_pass` | ScreenScraper credentials |
| `screenscraper_devid` / `screenscraper_devpassword` | **Advanced.** ScreenScraper's per-app developer credential pair, sent on every request alongside the user credentials. Default `"SpinDoctor"` / `"SpinDoctor"` — the historical baked-in values. Override only if ScreenScraper has issued you a real registered developer credential or starts rejecting the default pair with HTTP 403. No Setup-tab field; set from the Console tab with `config set screenscraper_devid <value>`. See also [Troubleshooting → 403 from ScreenScraper or TheGamesDB](troubleshooting.md#403-from-screenscraper-or-thegamesdb). |
| `thegamesdb_key` | TheGamesDB API key |
| `default_metadata_source` | `screenscraper` or `thegamesdb` |
| `match_threshold` | Fuzzy auto-accept confidence, `0.0`–`1.0` (default `0.80`) |
| `interactive_matching` | Prompt on ambiguous matches (default `true`) |
| `mame_executable` | Path to a MAME binary (used by `ledblinky generate` — see below) |
| `metadata_cache_ttl_days` | Days to keep cached scraper responses (default `30`) |
| `backup_dir` | Root folder for all automatic `.bak` backups written before in-place XML saves. Also the default target for `backup create`. Blank = `.bak` lands next to the source file. |
| `atomic_tmp_dir` | **Scratch folder for atomic write temp files.** When blank (the default), each `*.tmp` file lands beside the real XML or JSON file it is replacing — which is safe but scatters temp files through the HyperSpin Databases tree. Set this to a dedicated folder (e.g. `D:\SpinDoctorTemp`) to keep all temp files in one predictable place. **Must be on the same drive as `hyperspin_dir`** — SpinDoctor silently falls back to writing next to the target for any file on a different drive. Set via the GUI Setup tab or `spindoctor config set atomic_tmp_dir D:\SpinDoctorTemp`. |
| `backup_before_modify` | Whether XML writes leave a `.bak` next to the file (default `true`) |
| `region_preferences` | Default region order for `curate` (default `["USA", "World", "Europe", "Japan"]`) |
| `ffmpeg_path` | Explicit path to `ffmpeg` / `ffmpeg.exe` for post-download audio re-encoding (auto-detected from `PATH` when blank — see below) |
| `demulshooter_path` | Explicit path to `DemulShooter.exe` if auto-detection misses it |
| `demulshooter_extra_args` | Default extra args appended to DemulShooter (default `-noresize`, Sinden-friendly) |
| `ui_scale` | GUI font/widget scale multiplier (float, `0.6`–`2.0`, default `1.0`). Set from `View → UI scale` or `Ctrl++` / `Ctrl+-` / `Ctrl+0` in the GUI. Cabinet owners on 1280×720 typically want `0.9` to fit more on screen. |
| `output_visible` | Whether the GUI's bottom Output panel is shown (bool, default `true`). Toggled from `View → Show output pane`, the status-bar button, or `Ctrl+`` ` ``. |
| `gui_window_geometry` | Last `WIDTHxHEIGHT+X+Y` the GUI window was at when it closed (string, default unset). Restored on the next launch so cabinet owners don't re-resize / re-position every session. Managed automatically — delete it to reset window state. Hand-corrupted values are revalidated against a regex and silently discarded. |
| `gui_window_maximized` | Whether the GUI window was maximized when it closed (bool, default `false`). Restored on the next launch. Managed automatically — delete it to default to a normal window. |
| `gui_last_active_tab` | Index of the tab that was open the last time the GUI closed (int, default unset). Restored on the next launch so users who live in a specific tab don't re-navigate from Setup every time. Managed automatically — delete it to default back to the Setup tab. On a true fresh install (no `config.json` yet), the GUI auto-focuses the Setup tab regardless. |
| `gui_meta_subset` | Last-picked subset of systems for the Metadata & Media tab's "Pick subset" picker (list[str], default `[]`). Restored on the next launch so the "refresh the same five systems" workflow doesn't require re-ticking each time. |
| `gui_curate_regions` | User-chosen ScreenScraper region tickboxes on the Maintenance tab (list[str], default `[]`). Empty list falls back to the top-level `region_preferences`. |
| `gui_meta_auto_best` | Persisted state of the "Auto-pick best match for ambiguous results" checkbox on the Metadata & Media tab (bool, default `true`). Off makes the GUI pass `--skip-ambiguous` so ambiguous matches are logged for the next audit pass instead of auto-picking. |
| `gui_meta_all_games` | Persisted state of the "Refresh complete entries too" checkbox (bool, default `false`). |
| `gui_meta_no_cache` | Persisted state of the "Skip cache, hit the API every game" checkbox (bool, default `false`). |

Apply / dry-run toggles for destructive operations (backup restore, migrate, curate apply, etc.) are deliberately NOT persisted across launches — those re-arm to OFF on every GUI startup so cabinet owners always make an explicit per-run opt-in.

## Per-system overrides

Teach SpinDoctor about a system it doesn't natively know — custom emulators, unusual extensions, alternative scraper IDs, layout (per-rom-file vs. per-game-folder):

```bat
spindoctor config system set "Sony Playstation 7" ^
    --screenscraper-id 999 ^
    --thegamesdb-id 4971 ^
    --rom-extensions ps7,iso ^
    --layout per-game-folder ^
    --emulator RPCS7

spindoctor config system list
spindoctor config system clear "Sony Playstation 7"
```

All flags are optional — only the keys you supply are written; everything else is left unchanged.

| Flag | What it controls |
|------|-----------------|
| `--screenscraper-id INT` | ScreenScraper platform ID used by `fetch-meta` / `fetch-media` |
| `--thegamesdb-id INT` | TheGamesDB platform ID |
| `--rom-extensions csv` | Extensions used by `add-system`, `audit`, and `generate-config` (e.g. `iso,bin,chd`) |
| `--layout` | ROM folder layout: `per-game-folder`, `multi-disc-m3u`, or `flat` |
| `--emulator NAME` | RocketLauncher emulator name written as `Default_Emulator=` in new per-system INIs |
| `--rom-path PATH` | Exact ROM folder path — used by `generate-config` as `Rom_Path=` instead of `roms_dir\<SystemName>` |

Common reasons to use overrides:

- **`add-system` reports "no ROMs found"** — the file extension isn't in the recognized set. Add it via `--rom-extensions`.
- **System has its own metadata IDs on ScreenScraper / TheGamesDB** — set `--screenscraper-id` / `--thegamesdb-id`.
- **Multi-disc consoles where each game is a folder** — `--layout per-game-folder`.
- **System uses a Sinden lightgun** — set `"lightgun": true` in the override (or run `spindoctor lightgun configure --system <name> --apply`, which sets it automatically). `lightgun audit` reports on every system with this flag.
- **System's emulator is not in SpinDoctor's built-in map** — set `--emulator` to the exact name from `Global Emulators.ini` (e.g. `--emulator Daphne`, `--emulator 4DO`). Only affects newly-created INI files; existing `Default_Emulator=` values are never overwritten.
- **MAME variants or any system sharing a ROM folder** — set `--rom-path` to the shared directory. `generate-config` derives `Rom_Path` as `roms_dir\<SystemName>` by default; for systems like `MAME (Vector)`, `4-Player Games`, or any system where the ROM folder name doesn't match the system name, `--rom-path` makes the mapping permanent and immune to future drive migrations:

  ```bat
  spindoctor config system set "MAME (Vector)" --rom-path "J:\Games\MAME"
  spindoctor config system set "Panasonic 3DO"  --emulator RetroArch --rom-path "J:\Games\3DO"
  spindoctor config system set "Daphne"         --emulator Daphne    --rom-path "J:\Games\Daphne"
  ```

  The raw JSON / TOML representation (for reference — edit via CLI or GUI, not by hand):

  ```toml
  [system_overrides."MAME (Vector)"]
  rom_path = 'J:\Games\MAME'

  [system_overrides."Panasonic 3DO"]
  emulator = 'RetroArch'
  rom_path = 'J:\Games\3DO'
  ```

## Per-game overrides

Force a specific ScreenScraper / TheGamesDB game ID for one title, or store a Steam App ID for Steam media fetching:

```bat
spindoctor config game-override set "Nintendo DS" "Golden Sun - Dark Dawn (USA)" ^
    --screenscraper-id 5775 ^
    --thegamesdb-id 11251
spindoctor config game-override set "PC Games" "Hades" ^
    --steam-app-id 1145360

spindoctor config game-override list
spindoctor config game-override list --system "Nintendo DS"
spindoctor config game-override clear "Nintendo DS" "Golden Sun - Dark Dawn (USA)"
```

All three ID options (`--screenscraper-id`, `--thegamesdb-id`, `--steam-app-id`) accept either a bare numeric ID **or a full URL** copied from the browser — the ID is extracted automatically:

```bat
spindoctor config game-override set "PC Games" "Hades" ^
    --steam-app-id "https://store.steampowered.com/app/1145360/Hades/" ^
    --screenscraper-id "https://www.screenscraper.fr/gameinfos.php?gameid=12345"
```

Find ScreenScraper / TheGamesDB IDs on the scraper's own site — it's the `gameid=`/`id=` query parameter on the game's detail page. You don't need all three — set whichever source(s) you actually use.

**How scraper ID overrides are used:** Every future `fetch-meta`/`fetch-media` run for that exact (system, game) name uses the stored ID automatically — the game is fetched directly, treated as a 100%-confidence match, and name search is bypassed entirely. If the forced ID fails to resolve, that source returns nothing rather than falling back to name matching. A stored `steam_app_id` is used automatically by `fetch-steam-media` when `--steam-id` is not passed on the command line.

Also exposed in the GUI: Metadata & Media tab → **Per-game & override (Optional)** panel.

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

## `ffmpeg_path` — automatic video audio fix

ScreenScraper's standardised (`video-normalized`) video files encode audio as MP3 inside an MP4 container. Both macOS AVFoundation and Windows Media Foundation expect AAC behind an `mp4a` tag and silently drop the track, so the video plays but has no sound.

When `ffmpeg` and `ffprobe` are available, SpinDoctor automatically re-encodes the audio to AAC after every video/trailer download (video stream is copied — no quality loss). No configuration is required if `ffmpeg` is on your `PATH`:

- **macOS** — install with Homebrew: `brew install ffmpeg`
- **Windows** — download from <https://ffmpeg.org/download.html> and add the `bin\` folder to your `PATH`, or drop `ffmpeg.exe` and `ffprobe.exe` next to the SpinDoctor binary

If `ffmpeg` is installed in a non-standard location, point SpinDoctor at it:

```
spindoctor config set ffmpeg_path "C:\tools\ffmpeg\bin\ffmpeg.exe"
```

If neither `ffmpeg` nor `ffprobe` is found the download still succeeds — the audio just won't be fixed automatically.

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
