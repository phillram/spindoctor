# Configuration

Settings live in `%USERPROFILE%\.spindoctor\config.json`
(`~/.spindoctor/config.json` on macOS/Linux). Save through **GUI → Setup** or:

```text
spindoctor config init
spindoctor config show
spindoctor config set default_metadata_source auto
spindoctor config set region_preferences "USA,World,Europe,Japan"
```

Settings save immediately, without `--apply`. The wizard requires existing
folders and offers current values on re-run. `config set` handles scalar/list
values; use dedicated commands for mappings. `config show` reflects your actual
settings, so review it before sharing.

## Paths

| Key | Purpose |
|---|---|
| `roms_dir` | ROM root, normally one folder per system |
| `hyperspin_dir` | Folder containing Databases, Media and Settings |
| `rocketlauncher_dir`, `emulators_dir` | Launcher and emulator roots |
| `ledblinky_dir` | LEDBlinky installation |
| `mame_executable` | MAME used for cached `-listxml` controls data |
| `output_dir` | Output for supporting commands and optional GUI logs, not universal staging |
| `backup_dir` | Default snapshot/backup root; supported writers mirror sidecars here |
| `atomic_tmp_dir` | Optional temp folder; must share the destination filesystem or writers fall back beside the destination |
| `auto_audit_export_dir` | Automatic post-write audit CSV destination where supported |
| `intro_randomizer_dir`, `intro_video_target` | Intro pool and the actual boot-video file to replace |
| `ffmpeg_path` | Explicit ffmpeg binary; otherwise auto-detected |
| `demulshooter_path`, `demulshooter_extra_args` | Gun-tool location and optional default arguments |

Choose a MAME build whose controls database fits your library; this does not
change which MAME RocketLauncher launches. Newer builds can have different
machine coverage. Listxml is cached per executable and invalidated by mtime.

Install compatible ffmpeg/ffprobe to inspect media and repair unsupported MP4
audio. Automatic repair copies video and re-encodes audio to AAC when needed.
[`generate-media`](generate-media.md) also records games and makes clips with them.

## Scraping and library policy

| Key | Default / meaning |
|---|---|
| `screenscraper_user`, `screenscraper_pass` | Optional ScreenScraper account |
| `screenscraper_devid`, `screenscraper_devpassword` | App credentials; override only with an issued developer pair (ScreenScraper issues them on request through its forum; it refuses the bundled `SpinDoctor` value) |
| `thegamesdb_key` | Optional TheGamesDB API key |
| `default_metadata_source` | `auto`: combine configured providers when both exist; or select `screenscraper`, `thegamesdb`, `launchbox`, `both`, or a comma list asked in order (`launchbox,thegamesdb`); see [media sources](media-sources.md) |
| `max_concurrent_downloads` | `4` |
| `match_threshold`, `interactive_matching` | `0.80`, `true` |
| `metadata_cache_enabled`, `metadata_cache_ttl_days` | `true`, `30` |
| `backup_before_modify` | `true`, for writers honoring this setting; not a universal undo guarantee |
| `region_preferences` | USA, World, Europe, Japan |
| `strip_variant_tags_in_display_name` | `false` |

Old configs using the previous metadata-source default migrate to `auto` once.
Set an explicit source again afterward if needed. Credentials are saved locally,
not encrypted; [protect settings and backups](privacy.md).

## Per-system overrides

```text
spindoctor config system set "MAME (Vector)" --rom-path J:\Games\MAME --emulator MAME
spindoctor config system list
spindoctor config system clear "MAME (Vector)"
```

Optional flags set only supplied values: `--screenscraper-id`, `--thegamesdb-id`,
`--rom-extensions` (CSV), `--layout` (`flat`, `per-game-folder`, `multi-disc-m3u`),
`--emulator`, `--rom-path` and `--launchbox-platform` (repeatable, searched in order).
Emulator names must match RocketLauncher's registry.
Existing launcher choices are not universally overwritten by config generation.

`lightgun configure --apply` also tracks a system as lightgun-enabled.
Turning its tracking flag off does not remove launch hooks.

## Per-game overrides

```text
spindoctor config game-override set "PC Games" Hades --steam-app-id 1145360
spindoctor config game-override list
spindoctor config game-override clear "PC Games" Hades
```

`--screenscraper-id`, `--thegamesdb-id` and `--steam-app-id` accept IDs or supported
provider URLs. Exact system/game names matter. Scraper IDs bypass name matching;
if an explicit ID fails, that source does not silently choose another game.

Use `ignore` for exclusions, `match` for cached match decisions, and
`emulator-title` for synthetic-launch window-title mappings.

## Launch-test settings

| Keys | Defaults / meaning |
|---|---|
| `test_skip_systems` | Empty list; explicit `--system` can include skipped wheels |
| `test_skip_pclauncher`, `test_skip_custom_wheels` | `true`, `true` |
| `test_per_system`, `test_game_seconds` | `3`, `20` |
| `test_launch_timeout`, `test_close_timeout`, `test_cooldown` | `90`, `25`, `3` seconds |
| `test_helper_processes` | Additional helper EXEs; `!name.exe` removes a built-in exclusion |
| `test_ignore_log_errors` | `["No CRC defined"]` |
| `test_error_window_words` | Blank uses built-in error-title regex |
| `test_screenshot_width`, `test_results_dir` | `480`; blank uses `.spindoctor/tests` |
| `test_hyperspin_timeout`, `test_skip_intro_video` | `180` seconds, `true` |
| `test_ignore_hyperspin_log` | Empty list of harmless log substrings |
| `test_cleanup` | `report`; alternatives `remove`, `off` |
| `test_cleanup_skip` | `cache`, `RocketLauncher\Data\Statistics`; statistics/extraction folders also protected |

See [launch tests](workflows.md#launch-tests) before enabling cleanup removal.

## GUI state

`ui_scale` defaults to `1.0` (range 0.6–2.0), `output_visible` to `true`.
`gui_window_geometry`, `gui_window_dpi_scale`, `gui_window_maximized` and
`gui_last_active_page` are managed automatically. `gui_last_active_tab` is a
legacy fallback; `gui_last_systems` is reserved, not a restored system selector.

`gui_meta_subset`, `gui_meta_auto_best`, `gui_meta_all_games`, `gui_meta_no_cache`
and `gui_curate_regions` retain form preferences. Apply is never persisted.

## Filesystem considerations

Synthetic-wheel media uses hardlinks where possible. Default `auto` falls back
to copies on another filesystem or FAT32/exFAT; `--media-mode copy` makes that
explicit. Hardlinks save space but share bytes, so in-place editing affects both
names. Do not mistake linked media for an independent backup.

## Environment variables

| Variable | Effect |
|---|---|
| `SPINDOCTOR_NO_UPDATE_CHECK=1` | Disable GUI GitHub release checks |
| `SPINDOCTOR_DISABLE_SINGLETON=1` | Bypass GUI lock; avoid concurrent cabinet writers |
| `PYTHONIOENCODING`, `PYTHONUNBUFFERED` | Worker encoding/streaming, managed internally where needed |

More on [storage](spindoctor-files.md) and [GUI controls](gui.md).
