# Command reference

Generated from the current CLI. Use `spindoctor <command> --help` for argument
types, defaults and full behavior; use the [cheatsheet](cli-cheatsheet.md) for recipes.
Windows binary users substitute `spindoctor-cli` for `spindoctor`.

## Safety

- Cabinet writers generally preview until `--apply`. Preview can still populate
  caches or write explicitly requested reports; it is not a filesystem sandbox.
- Settings and list commands can save immediately, including `config`, `ignore`,
  `match`, `fav add/remove/sync` and `emulator-title set`. Check their help.
- `install-tools` writes helper files even without `--apply`; the flag gates
  cabinet registration. Undo, restore, scheduling and live Toolkit actions have
  command-specific gates, not one universal Apply policy.
- Toolkit shutdown/restart, exit-to-Windows, resolution and LED-board reset are
  **live actions**, not dry runs. Shutdown/restart force-close Windows apps.
- `curate --action delete`, orphan-media deletion, scrub and cleanup can remove
  data. An Apply flag does not promise undo.
- Keep an independent backup. Multi-file changes are not transactions; Stop,
  crashes and power loss can leave partial work. See [recovery](workflows.md#recovery-from-mistakes).

## Commands

Each entry lists its summary and accepted option names. Subcommands are indented.
Options belong to the command on that line, not its children.


## `add-pc-system`

Bootstrap a PC/Windows/Steam games system end-to-end.

Arguments: `SYSTEM_NAME`.

Options: `--rename/--no-rename`, `--no-interactive`, `--no-menu`, `--no-system-media`, `--no-db`, `--no-game-media`, `--no-pclauncher`, `--overwrite-pclauncher`, `--pick-media`, `--source`, `--apply`, `--output-dir`, `--verbose`, `--help`.


## `add-system`

Bootstrap a top-level console end-to-end (e.g. PS3, Dreamcast).

Arguments: `SYSTEM_NAME`.

Options: `--no-menu`, `--no-system-media`, `--no-db`, `--no-game-media`, `--pick-media`, `--source`, `--apply`, `--output-dir`, `--help`.


## `audit`

Audit ROM files against the Hyperspin database and media assets.

Options: `--system/-s`, `--all`, `--no-media`, `--no-fuzzy`, `--detailed`, `--report/-r`, `--show-matched`, `--help`.


## `backup`

Back up or restore the SpinDoctor library.

Options: `--help`.

- `backup create`: Create a new backup of selected library components. Options: `--target`, `--include`, `--label`, `--apply`, `--verbose`, `--help`.
- `backup info`: Show what's inside a backup. Options: `--backup`, `--help`.
- `backup list`: List backups under a target folder. Options: `--target`, `--json`, `--help`.
- `backup restore`: Restore from a backup back to the library paths. Options: `--backup`, `--include`, `--use-current-paths`, `--overwrite`, `--apply`, `--verbose`, `--help`.
- `backup sidecar`: List and restore the per-modify ``.YYYYMMDD_HHMMSS.bak`` sidecars SpinDoctor's apply commands write next to each mutated file. Options: `--help`.
  - `backup sidecar list FILE`: List ``.YYYYMMDD_HHMMSS.bak`` siblings of FILE, newest first. Options: `--json`, `--help`.
  - `backup sidecar restore FILE`: Restore FILE from a ``.YYYYMMDD_HHMMSS.bak`` sidecar. Options: `--from`, `--apply`, `--help`.

## `batch-edit`

Edit metadata fields across many games in one shot.

Options: `--system/-s`, `--filter`, `--set`, `--clear`, `--append`, `--prepend`, `--apply`, `--report`, `--undo`, `--list-manifests`, `--output-dir`, `--help`.


## `check-archive-ext`

Scan ROM archives and report inner files whose extensions are not in the RocketLauncher config.

Options: `--system/-s`, `--all`, `--help`.


## `check-discs`

Validate multi-disc games and .m3u playlists.

Options: `--system/-s`, `--all`, `--help`.


## `cleanup`

Audit and remove SpinDoctor caches, manifests, and temp files.

Options: `--help`.

- `cleanup audit`: Show disk usage for each SpinDoctor cache and manifest category. Options: `--detail`, `--category/-c`, `--report`, `--help`.
- `cleanup categories`: List every cleanup category and its purpose. Options: `--help`.
- `cleanup run`: Remove cached files. Defaults to dry-run; pass --apply to actually delete. Options: `--include/-i`, `--exclude/-x`, `--include-unsafe`, `--older-than`, `--keep-recent`, `--apply`, `--prune-empty-dirs`, `--yes/-y`, `--verbose`, `--help`.

## `clone`

Duplicate a game (ROM, DB entry, all media) under a new name.

Options: `--system/-s`, `--game`, `--to`, `--display-name`, `--apply`, `--undo`, `--list-manifests`, `--output-dir`, `--verbose`, `--help`.


## `config`

Show or update SpinDoctor configuration.

Options: `--help`.

- `config game-override`: Per-(system, game) overrides forcing a specific scraper game ID. Options: `--help`.
  - `config game-override clear SYSTEM_NAME GAME_NAME`: Remove the override for SYSTEM_NAME / GAME_NAME (falls back to normal matching). Options: `--help`.
  - `config game-override list`: Show all per-game scraper-ID overrides. Options: `--system`, `--help`.
  - `config game-override set SYSTEM_NAME GAME_NAME`: Force specific scraper IDs or a Steam App ID for SYSTEM_NAME / GAME_NAME. Options: `--screenscraper-id`, `--thegamesdb-id`, `--steam-app-id`, `--help`.
- `config init`: First-run setup wizard — prompt for every path-based config key in order. Options: `--help`.
- `config set KEY VALUE`: Set a configuration value. Options: `--help`.
- `config show`: Display current configuration. Options: `--help`.
- `config system`: Per-system overrides for ROM extensions, scraper IDs, layout, emulator. Options: `--help`.
  - `config system clear SYSTEM_NAME`: Remove all overrides for SYSTEM_NAME (falls back to built-in defaults). Options: `--help`.
  - `config system list`: Show all per-system overrides. Options: `--help`.
  - `config system set SYSTEM_NAME`: Add or update overrides for SYSTEM_NAME. Options: `--screenscraper-id`, `--thegamesdb-id`, `--rom-extensions`, `--layout`, `--emulator`, `--rom-path`, `--help`.
- `config verify-credentials`: Probe ScreenScraper and TheGamesDB to check the configured credentials. Options: `--ss-user`, `--ss-pass`, `--ss-devid`, `--ss-devpassword`, `--tgdb-key`, `--json`, `--help`.

## `curate`

Curate region/version variants — keep the best, retire the rest.

Options: `--system/-s`, `--all`, `--regions`, `--include-proto`, `--prefer-revision`, `--apply`, `--action`, `--yes`, `--undo`, `--list-manifests`, `--verbose`, `--help`.


## `diff`

Compare a spindoctor-backup-… folder against the live cabinet tree.

Arguments: `BACKUP_FOLDER`.

Options: `--component`, `--help`.


## `doctor`

Self-diagnose: paths, binaries, DB integrity, cache hygiene, integrations.

Options: `--apply`, `--help`.


## `emulator-title`

Manage emulator window-title mappings for synthetic wheel launches.

Options: `--help`.

- `emulator-title list`: List all emulator window-title mappings (built-in + custom overrides). Options: `--help`.
- `emulator-title remove EMULATOR_NAME`: Remove a custom window-title mapping (falls back to built-in default). Options: `--help`.
- `emulator-title set EMULATOR_NAME WINDOW_TITLE`: Map EMULATOR_NAME to WINDOW_TITLE for FadeTitle detection. Options: `--help`.

## `fav`

Manage the cross-system Favorites wheel.

Options: `--help`.

- `fav add SYSTEM_NAME ROM_NAME`: Add a favorite. Run [cyan]fav rebuild[/cyan] afterwards to update HyperSpin. Options: `--display-name`, `--help`.
- `fav clear`: Empty the favorites store and remove the synthetic Favorites wheel. Options: `--apply`, `--help`.
- `fav list`: List every entry in the favorites store. Options: `--help`.
- `fav rebuild`: Regenerate the Favorites HyperSpin system + media + launchers. Options: `--media-mode`, `--apply`, `--verbose/-v`, `--help`.
- `fav remove SYSTEM_NAME ROM_NAME`: Remove a favorite from the cross-system wheel. Options: `--help`.
- `fav sync`: Pull HyperSpin's per-system favorites into the cross-system store. Options: `--verbose/-v`, `--help`.

## `fetch-media`

Download media assets for games in the database.

Options: `--system/-s`, `--all`, `--game/-g`, `--types`, `--source`, `--overwrite`, `--pick-media`, `--skip-ambiguous`, `--apply`, `--verbose/-v`, `--output-dir`, `--report`, `--help`.


## `fetch-meta`

Fetch and update game metadata in the Hyperspin XML databases.

Options: `--system/-s`, `--all`, `--game/-g`, `--source`, `--all-games`, `--interactive/--auto-best`, `--skip-ambiguous`, `--threshold`, `--no-cache`, `--clear-cache`, `--apply`, `--output-dir`, `--help`.


## `fetch-steam-media`

Download media for a specific game from the Steam Store.

Options: `--system/-s`, `--game/-g`, `--steam-id`, `--types`, `--video-index`, `--snap-index`, `--background-index`, `--artwork-index`, `--wheel-index`, `--overwrite`, `--output-dir`, `--hls-quality`, `--apply`, `--help`.


## `find-dupes`

Scan for duplicated games within a system (and optionally across systems).

Options: `--system/-s`, `--all`, `--cross-systems`, `--by-content`, `--help`.


## `find-global`

Search every configured system's HyperSpin database for *query*.

Arguments: `QUERY`.

Options: `--limit`, `--exact`, `--help`.


## `find-misplaced`

Scan for ROMs whose extension doesn't match the folder's system.

Options: `--system/-s`, `--all`, `--apply`, `--undo`, `--verbose`, `--help`.


## `find-orphan-media`

Find media files whose game no longer exists in DB or ROMs.

Options: `--system/-s`, `--all`, `--apply`, `--verbose`, `--help`.


## `game`

List, remove, or reorder individual games within a system's wheel database.

Options: `--help`.

- `game list`: List all games in a system's wheel database with their position. Options: `--system/-s`, `--verbose/-v`, `--help`.
- `game move GAME_NAME POSITION`: Move a game to a specific position in the wheel order. Options: `--system/-s`, `--apply`, `--verbose/-v`, `--output-dir`, `--help`.
- `game move-down GAME_NAME`: Move a game down one position in the wheel order. Options: `--system/-s`, `--apply`, `--verbose/-v`, `--output-dir`, `--help`.
- `game move-up GAME_NAME`: Move a game up one position in the wheel order. Options: `--system/-s`, `--apply`, `--verbose/-v`, `--output-dir`, `--help`.
- `game remove GAME_NAME`: Remove a specific game from a system's wheel database. Options: `--system/-s`, `--apply`, `--verbose/-v`, `--remove-pclauncher`, `--output-dir`, `--help`.
- `game save-order`: Save a custom game order to a system's wheel database. Options: `--system/-s`, `--order-file`, `--apply`, `--output-dir`, `--help`.
- `game sort`: Sort all games in a system's wheel database alphabetically. Options: `--system/-s`, `--by`, `--apply`, `--verbose/-v`, `--output-dir`, `--help`.

## `generate-config`

Generate RocketLauncher INI files and the HyperSpin Main Menu database.

Options: `--all`, `--system/-s`, `--rl/--no-rl`, `--main-menu/--no-main-menu`, `--db-stubs/--no-db-stubs`, `--global-emulators/--no-global-emulators`, `--overwrite-global`, `--apply`, `--output-dir`, `--help`.


## `ignore`

Manage per-system and global ignore lists.

Options: `--help`.

- `ignore add GAME_NAME`: Add a game to the ignore list. Options: `--system/-s`, `--help`.
- `ignore clear`: Clear ignore list entries. Options: `--system/-s`, `--yes`, `--help`.
- `ignore list`: List all ignored games. Options: `--system/-s`, `--help`.
- `ignore remove GAME_NAME`: Remove a game from the ignore list. Options: `--system/-s`, `--help`.

## `inspect`

Show detailed per-file information for one game or a whole system.

Options: `--system/-s`, `--game/-g`, `--all`, `--format`, `--output/-o`, `--no-path`, `--help`.


## `install-tools`

Install the HyperSpin helpers you pick with --tool, one by one.

Options: `--tool`, `--output-dir`, `--add-to-system`, `--apply`, `--help`.


## `introvideo`

Manage the pool of intro videos HyperSpin plays on boot.

Options: `--help`.

- `introvideo add SOURCES`: Add one or more videos to the intro pool. Options: `--apply`, `--help`.
- `introvideo install-autorun`: Register a Windows logon task that runs 'swap --apply' automatically. Options: `--delay-minutes`, `--apply`, `--help`.
- `introvideo list`: List every intro video — enabled (in rotation) or disabled. Options: `--help`.
- `introvideo remove FILENAMES`: Take one or more videos out of rotation (moved to Disabled\, never deleted). Options: `--apply`, `--help`.
- `introvideo restore FILENAMES`: Put one or more disabled videos back into rotation. Options: `--apply`, `--help`.
- `introvideo swap`: Pick a random enabled video and copy it over intro_video_target. Options: `--apply`, `--help`.
- `introvideo uninstall-autorun`: Remove the Windows logon task registered by 'install-autorun'. Options: `--apply`, `--help`.

## `ledblinky`

Generate and audit LEDBlinky controls.ini / Colors.ini.

Options: `--help`.

- `ledblinky admin-buttons`: Manage cabinet-level (admin) button colors across all Colors.ini entries. Options: `--help`.
  - `ledblinky admin-buttons set`: Set individual admin/cabinet button colors across ALL Colors.ini sections. Options: `--player`, `--colors`, `--color`, `--count`, `--apply`, `--no-backup`, `--verbose`, `--help`.
- `ledblinky admin-leds`: Manage the admin LED buttons that stay lit *during gameplay*. Options: `--help`.
  - `ledblinky admin-leds add`: Add the admin LED buttons to games/consoles that don't have them. Options: `--emulator`, `--exit`, `--pause`, `--select`, `--apply`, `--no-backup`, `--help`.
  - `ledblinky admin-leds randomize`: Assign a random admin color per control group (per-game variety). Options: `--buttons`, `--seed`, `--emulator`, `--games`, `--apply`, `--no-backup`, `--help`.
  - `ledblinky admin-leds remove`: Remove the admin LED buttons (they go dark in-game). Options: `--emulator`, `--apply`, `--no-backup`, `--help`.
  - `ledblinky admin-leds set`: Set uniform in-game admin colors/state across all games (default mode). Options: `--exit`, `--pause`, `--select`, `--search-off`, `--lmouse-off`, `--rmouse-off`, `--search-on`, `--lmouse-on`, `--rmouse-on`, `--emulator`, `--apply`, `--no-backup`, `--help`.
  - `ledblinky admin-leds show`: Print which admin buttons light in-game, and in what colors. Options: `--emulator`, `--by-console`, `--help`.
- `ledblinky audit`: Show LEDBlinky coverage of the wheel games: covered / can be added / no data. Options: `--system/-s`, `--all-roms`, `--report`, `--help`.
- `ledblinky check`: Scan HyperSpin + LedBlinky configs for known Search-menu conflicts. Options: `--menus`, `--help`.
- `ledblinky colors`: Manage named color definitions in Color-RGB.ini. Options: `--help`.
  - `ledblinky colors add NAME`: Add a brand-new named color to Color-RGB.ini. Options: `--hex`, `--rgb`, `--apply`, `--no-backup`, `--help`.
  - `ledblinky colors brightness`: Set all Color-RGB.ini colors to a uniform brightness level. Options: `--scale`, `--apply`, `--no-backup`, `--verbose`, `--help`.
  - `ledblinky colors edit COLOR_NAME`: Edit a color definition and propagate the rename to all LEDBlinky files. Options: `--name`, `--hex`, `--rgb`, `--apply`, `--no-backup`, `--help`.
  - `ledblinky colors list`: List all named color definitions from Color-RGB.ini. Options: `--help`.
  - `ledblinky colors normalize`: Convert hex-format Colors.ini entries to named P1_BUTTON format. Options: `--apply`, `--no-backup`, `--verbose`, `--help`.
  - `ledblinky colors randomize`: Give each game its own random button colors. Options: `--seed`, `--apply`, `--no-backup`, `--verbose`, `--help`.
  - `ledblinky colors sync-players`: Mirror P1 colors to all additional players based on controls.ini. Options: `--apply`, `--no-backup`, `--override`, `--verbose`, `--help`.
- `ledblinky fill-defaults`: Add default Colors.ini entries for ROMs with no LED mapping. Options: `--color`, `--buttons`, `--players`, `--admin-buttons`, `--admin-color`, `--override-uniform`, `--no-add-keys`, `--system`, `--apply`, `--no-backup`, `--verbose`, `--help`.
- `ledblinky fix`: Fix LEDBlinky overlay hooks so Search / Genre / Favorites don't hang HyperSpin. Options: `--apply`, `--output-dir`, `--no-backup`, `--menus`, `--help`.
- `ledblinky generate`: Add the missing LEDBlinky controls.ini and Colors.ini entries. Options: `--system/-s`, `--all-roms`, `--overwrite`, `--apply`, `--output-dir`, `--verbose`, `--help`.
- `ledblinky inspect-rom ROM_NAME`: Diagnose why a ROM's LED colors may not be applying. Options: `--help`.
- `ledblinky lwax`: Build raw (unsigned) .lwax animation files from LEDBlinkyInputMap.xml. Options: `--help`.
  - `ledblinky lwax batch`: Generate the whole colour-diverse pattern library (~280 raw .lwax files). Options: `--output`, `--apply`, `--help`.
  - `ledblinky lwax calibrate`: Light each control a distinct, named colour to map buttons to positions. Options: `--labels`, `--name`, `--output`, `--apply`, `--help`.
  - `ledblinky lwax cute`: Build a smooth multi-colour cute_* animation, or a new colourway of one. Options: `--list`, `--theme`, `--pattern`, `--color`, `--color2`, `--color3`, `--seed`, `--name`, `--output`, `--apply`, `--help`.
  - `ledblinky lwax fade`: Generate a raw .lwax color-cycle fade animation. Options: `--color`, `--labels`, `--steps-per-leg`, `--duration-ms`, `--name`, `--output`, `--apply`, `--help`.
  - `ledblinky lwax flash-check PATHS`: Score .lwax animations for flashing. Read-only. Options: `--help`.
- `ledblinky patch-settings`: Patch Settings.ini to fix animations and silence unused buttons. Options: `--fe-lwa`, `--ss-lwa`, `--game-lwa`, `--apply`, `--no-backup`, `--verbose`, `--help`.
- `ledblinky profiles`: Give every game a profile that lights only the buttons it can use. Options: `--apply`, `--no-backup`, `--verbose/-v`, `--help`.
- `ledblinky prune`: Remove controls.ini / Colors.ini entries for games in no wheel. Options: `--apply`, `--no-backup`, `--verbose`, `--help`.
- `ledblinky setup`: Run the full MAME LED setup in one step: generate + sync-players. Options: `--all-roms`, `--overwrite`, `--apply`, `--no-backup`, `--verbose`, `--help`.

## `lightgun`

Sinden / DemulShooter wiring for lightgun-enabled systems.

Options: `--help`.

- `lightgun audit`: Show gun wiring (INI hooks, User Functions) for every lightgun system in config. Options: `--help`.
- `lightgun configure`: Wire DemulShooter pre/post-launch hooks into a system's RL INI. Options: `--system/-s`, `--target`, `--extra-args`, `--apply`, `--verbose`, `--help`.
- `lightgun detect`: Detect installed lightgun gear and pre-wired systems. Options: `--apply`, `--verbose`, `--help`.

## `lint`

Static-analysis pass over the SpinDoctor codebase itself.

Options: `--source`, `--category/-c`, `--help`.


## `mainmenu`

Inspect and edit the HyperSpin Main Menu (top-level system wheel).

Options: `--help`.

- `mainmenu add SYSTEM`: Append SYSTEM to the Main Menu (idempotent). Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu down SYSTEM`: Move SYSTEM down by one slot. Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu edit`: Interactive editor — accept commands at a prompt and confirm on quit. Options: `--output-dir`, `--help`.
- `mainmenu hide SYSTEM`: Hide SYSTEM (sets enabled="No"). Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu remove SYSTEM`: Remove SYSTEM from the Main Menu. Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu reorder SYSTEM POSITION`: Move SYSTEM to POSITION (1-indexed). Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu show SYSTEM`: Render the menu, or unhide SYSTEM if one is given. Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu sort STRATEGY`: Sort the menu: alpha, manufacturer, or year. Options: `--apply`, `--output-dir`, `--help`.
- `mainmenu up SYSTEM`: Move SYSTEM up by one slot. Options: `--apply`, `--output-dir`, `--help`.

## `match`

Manage cached metadata match decisions.

Options: `--help`.

- `match clear`: Delete cached match selections so games are re-evaluated. Options: `--system/-s`, `--yes`, `--help`.
- `match list`: Show cached match selections. Options: `--system/-s`, `--help`.

## `media-add`

Manually add a local media file for a specific game.

Options: `--system/-s`, `--game/-g`, `--type`, `--file`, `--move`, `--overwrite`, `--output-dir`, `--apply`, `--help`.


## `media-scan`

Audit a folder of local media files against HyperSpin databases.

Arguments: `SOURCE_DIR`.

Options: `--system/-s`, `--all`, `--detail`, `--types`, `--no-recursive`, `--report`, `--apply`, `--action`, `--overwrite`, `--output-dir`, `--undo`, `--list-manifests`, `--verbose`, `--help`.


## `migrate`

Migrate the library to a new drive.

Options: `--target`, `--include`, `--systems`, `--apply`, `--keep-source`, `--verify`, `--no-update-config`, `--preserve-names`, `--undo`, `--list-manifests`, `--verbose`, `--help`.


## `organize`

Populate sort wheels and (optionally) restructure ROMs into folders.

Arguments: `SYSTEM_NAME`.

Options: `--no-sort`, `--axes`, `--overwrite-sort`, `--restructure`, `--apply`, `--undo`, `--help`.


## `pc-fix-exe`

Fix the Application= path in a per-game PCLauncher INI.

Arguments: `SYSTEM_NAME`, `GAME`.

Options: `--exe`, `--list-candidates`, `--apply`, `--help`.


## `pc-rename`

Scan for new/changed games in an existing PC system and refresh PCLauncher INIs.

Arguments: `SYSTEM_NAME`.

Options: `--no-pclauncher`, `--overwrite-pclauncher`, `--no-interactive`, `--apply`, `--verbose`, `--help`.


## `preview`

Generate visual previews of a system's wheels / themes / media.

Options: `--system/-s`, `--all`, `--output-dir/-o`, `--format`, `--columns`, `--include-missing`, `--game`, `--open`, `--help`.


## `recent`

Manage the Recently Played wheel (auto-derived from RocketLauncher stats).

Options: `--help`.

- `recent clear`: Remove the synthetic Recently Played wheel from disk. Options: `--target-system`, `--apply`, `--help`.
- `recent list`: Print the top-N games by last-played timestamp. Options: `--limit`, `--help`.
- `recent rebuild`: Rebuild the Recently Played system from RocketLauncher Statistics.ini files. Options: `--limit`, `--target-system`, `--media-mode`, `--apply`, `--verbose/-v`, `--help`.

## `rename`

Rename a game's ROM, DB entry, and every media file in one shot.

Options: `--system/-s`, `--game`, `--to`, `--display-name`, `--apply`, `--undo`, `--list-manifests`, `--output-dir`, `--verbose`, `--help`.


## `repath-system`

Re-prefix game paths in a PCLauncher system INI after moving games to a new drive.

Arguments: `SYSTEM_NAME`.

Options: `--rom-path`, `--apply`, `--help`.


## `report`

Generate a read-only audit report without making any changes.

Options: `--system/-s`, `--all`, `--format`, `--output/-o`, `--no-media`, `--no-fuzzy`, `--help`.


## `scrub`

Destructively reset cabinet data. Requires --apply.

Options: `--favorites`, `--stats`, `--hs-favorites`, `--backup-dir`, `--apply`, `--help`.


## `scrub-restore`

Restore files from a backup created by scrub --backup-dir.

Arguments: `BACKUP_PATH`.

Options: `--apply`, `--help`.


## `self-doctor`

Diagnose SpinDoctor's own state (not the cabinet library).

Options: `--fix`, `--help`.


## `stats`

Coverage dashboard: % of games with metadata + media per system.

Options: `--system/-s`, `--all`, `--help`.


## `stats-report`

Playtime / launch-stats reporting from RocketLauncher.

Options: `--system`, `--top`, `--by-system`, `--recent`, `--export`, `--json`, `--help`.

- `stats-report build-wheel`: Build a synthetic 'Most Played' HyperSpin wheel from playtime stats. Options: `--limit`, `--target-system`, `--media-mode`, `--output-dir`, `--apply`, `--verbose/-v`, `--help`.
- `stats-report clear-wheel`: Remove the synthetic Most Played wheel from disk. Options: `--target-system`, `--apply`, `--help`.

## `systems`

List all detected systems.

Options: `--help`.


## `test`

Launch games through RocketLauncher, the way HyperSpin does, and judge them.

Options: `--system/-s`, `--all-systems`, `--genre`, `--game/-g`, `--all`, `--count`, `--per-system`, `--seed`, `--include-skipped`, `--seconds`, `--resume`, `--only-failed`, `--recover`, `--list-runs`, `--json`, `--verbose/-v`, `--with-hyperspin`, `--play-intro`, `--leave-hyperspin-open`, `--cleanup`, `--apply`, `--help`.


## `theme-apply`

Replace HyperSpin frontend overlay art from a community pack.

Arguments: `SOURCE_DIR`.

Options: `--target`, `--systems`, `--apply`, `--undo`, `--revert-system`, `--list-manifests`, `--verbose`, `--help`.


## `theme-fill`

Install a blank theme zip for every game that has a video but no theme.

Options: `--system/-s`, `--all`, `--default`, `--apply`, `--verbose/-v`, `--help`.


## `theme-pack-create`

Snapshot the cabinet's current frontend art into a community-pack tree.

Arguments: `OUTPUT_DIR`.

Options: `--target`, `--help`.


## `theme-scan`

Inventory HyperSpin frontend overlay art (Special A/B + Frontend).

Options: `--system/-s`, `--keyword/-k`, `--output/-o`, `--help`.


## `toolkit`

Cabinet helpers for a Toolkit wheel or HyperSpin's Tools menu.

Options: `--help`.

- `toolkit exit-to-windows`: Close HyperSpin and go to the Windows desktop, after a countdown. Options: `--seconds`, `--help`.
- `toolkit idle-tour`: Make HyperSpin's idle mode visit random consoles. Options: `--settings`, `--self-test`, `--help`.
- `toolkit idle-tour-settings`: Show or change the idle tour's settings. Options: `--settings`, `--enabled/--disabled`, `--games-per-console`, `--console-minutes`, `--consoles-on-main-menu`, `--main-menu-minutes`, `--tour-max-minutes`, `--no-video-seconds`, `--skip`, `--help`.
- `toolkit reset-button-lights`: Stop Ultimarc PAC-LED64 boards flashing on their own. Options: `--dll`, `--no-note`, `--help`.
- `toolkit restart`: Close HyperSpin, then restart Windows, after a countdown. Options: `--seconds`, `--help`.
- `toolkit set-resolution`: Put Windows back to HyperSpin's resolution. Options: `--width`, `--height`, `--no-note`, `--help`.
- `toolkit shutdown`: Close HyperSpin, then shut Windows down, after a countdown. Options: `--seconds`, `--help`.

## `tools-audit`

Audit third-party arcade tools installed on this PC.

Options: `--extra-path`, `--max-depth`, `--show-unknown`, `--report`, `--help`.


## `uninstall-tools`

Remove SpinDoctor tool helpers installed by install-tools.

Options: `--tool`, `--add-to-system`, `--apply`, `--help`.


## `update-db`

Sync Hyperspin XML databases to match ROM directories.

Options: `--system/-s`, `--all`, `--add-missing/--no-add-missing`, `--remove-orphans`, `--apply`, `--output-dir`, `--strip-variant-tags/--keep-variant-tags`, `--help`.


## `verify`

Verify ROM file integrity against a No-Intro / Redump / TOSEC DAT.

Options: `--system/-s`, `--dat`, `--show-good`, `--match`, `--help`.


## `wheel-start`

Show or change where HyperSpin wheels start: first, last or random game.

Options: `--system/-s`, `--all`, `--set`, `--apply`, `--help`.
