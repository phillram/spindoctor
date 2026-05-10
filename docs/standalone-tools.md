# Standalone tools

Three minimal CLIs and a handful of `.bat` files designed to run on every system boot or directly from HyperSpin's Tools menu — without loading the full SpinDoctor CLI. They share `~/.spindoctor/config.json` with the main `spindoctor` command but use a light `argparse`-based entry point so they launch fast enough to use as a boot trigger.

```
scripts/
├── spindoctor-fav.py             ← Python wrapper (works without `pip install`)
├── spindoctor-recent.py          ← Python wrapper (works without `pip install`)
├── spindoctor-stats.py           ← Python wrapper (works without `pip install`)
├── Refresh Favorites.bat         ← Drop into HyperSpin Tools or Windows Startup
├── Refresh Recently Played.bat
├── Refresh Most Played.bat
└── Refresh Both.bat              ← Run all three in sequence
```

After `pip install -e .` the entry-point console scripts (`spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats`) are on PATH from any directory — equivalent to running the wrappers in `scripts/`.

## Do I need `pip install`?

The three `.bat` files call `spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` by bare name. `cmd.exe` resolves that via `PATHEXT`, so anything called `spindoctor-fav.exe` (or `.bat`, `.cmd`, …) on `PATH` — or sitting next to the `.bat` in the same folder — satisfies it. Three working setups:

1. **Standalone Windows binaries (no Python needed).** Download `spindoctor-windows-vX.Y.Z.zip` from the [GitHub Releases](https://github.com/phillram/spindoctor/releases) page, extract `spindoctor-fav.exe` / `spindoctor-recent.exe` / `spindoctor-stats.exe` (and `spindoctor-gui.exe` if you want one-click refreshes from a window), and either drop the `.bat` files into the same folder or add the folder to `PATH`. The `.bat` files work as-is. See [`docs/windows-binaries.md`](windows-binaries.md) for the full walkthrough.
2. **Full Python install.** `pip install -e .` from a checkout. Console scripts (`spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` / `spindoctor-gui`) land on `PATH`, the `.bat` files work as-is.
3. **Source on disk, no install.** Copy the whole repo to the cabinet, install Python + dependencies (`pip install click rich requests lxml`), and rewrite each `.bat` to call the `.py` wrappers directly:
   ```bat
   python C:\path\to\spindoctor\scripts\spindoctor-fav.py rebuild --apply
   ```
   The wrappers `sys.path.insert(0, repo_root)` so `import spindoctor` resolves without an editable install. The GUI is also available as `python -m spindoctor.gui`.

The `.py` wrappers in `scripts/` themselves require a Python install — they're for setup (3) only.

Hard requirements: either the standalone Windows binaries, or Python 3.8+ with `lxml` and the `spindoctor` package importable.

> **Want a windowed alternative to the `.bat` files?** The Wheels tab in `spindoctor-gui` has checkboxes for Favorites, Recently Played, and Most Played (all pre-ticked) plus a **Refresh selected** button — same outcome as `Refresh Both.bat` when all three are checked, or any subset when you untick some, and no `cmd.exe` required. The `.bat` files remain the right answer for HyperSpin Tools menu entries and Windows Startup tasks; the GUI is the right answer for ad-hoc manual refreshes.

## `spindoctor-fav`

Cross-system Favorites wheel manager.

```
spindoctor-fav add SYSTEM ROM_NAME [--display-name NAME]
spindoctor-fav remove SYSTEM ROM_NAME
spindoctor-fav list
spindoctor-fav sync
spindoctor-fav rebuild [--media-mode {link,symlink,copy,auto,none}] [--apply]
```

`list` and `rebuild` order entries alphabetically by display title (case-insensitive). `rebuild` is idempotent — safe on every boot.

```bat
spindoctor-fav add "Super Nintendo" "Chrono Trigger"
spindoctor-fav rebuild              :: dry-run preview
spindoctor-fav rebuild --apply      :: commit

:: Equivalent without `pip install`:
python scripts\spindoctor-fav.py rebuild --apply
python -m spindoctor.favorites rebuild --apply
```

## `spindoctor-recent`

Recently Played wheel from RocketLauncher's `Statistics.ini` files.

```
spindoctor-recent rebuild [--limit N] [--target-system NAME]
                          [--media-mode {link,symlink,copy,auto,none}] [--apply]
spindoctor-recent list
```

Default limit is 20; sorted by `last_played` desc (newest first), deduped on `(system, rom_name)`. `list` doesn't currently expose `--limit`.

```bat
spindoctor-recent rebuild --limit 20 --apply
python scripts\spindoctor-recent.py list
```

## `spindoctor-stats`

Playtime reports + Most Played wheel.

```
spindoctor-stats summary [--top N]
spindoctor-stats top     [--top N] [--system NAME]
spindoctor-stats recent  [--top N]
spindoctor-stats system
spindoctor-stats build-wheel [--limit N] [--target-system NAME]
                             [--media-mode {link,symlink,copy,auto,none}]
                             [--apply]
```

`top` sorts by `total_seconds` desc with `times_played` as tiebreaker. `recent` sorts by `last_played` desc; records with no timestamp are dropped. `summary` defaults to top 10. All others default to 20.

```bat
spindoctor-stats summary
spindoctor-stats top --system MAME --top 25
spindoctor-stats build-wheel --apply
```

## Wiring into HyperSpin Tools menu

Three integration patterns, in roughly increasing order of "how much you want it to feel like part of HyperSpin":

1. **HyperHQ → Tools menu (default).** The GUI's **Tools** tab → "Install for HyperHQ → Tools menu" runs:
   ```bat
   spindoctor install-tools
   ```
   Writes four `.bat` files into `<RocketLauncher>/Modules/HyperLaunch/Tools/spindoctor/`. Open `HyperHQ.exe`, go to the Tools tab, click Add, and point each entry at the matching `.bat`. They appear inside HyperSpin's in-cabinet Tools menu as `Refresh Favorites`, `Refresh Recently Played`, `Refresh Most Played`, and `Refresh Both`.

2. **As games inside an existing wheel system (`--add-to-system`).** If you've built a "Toolkit" or "Tools" wheel (a HyperSpin system whose "games" are maintenance tasks), expose the helpers as wheel entries inside it. The GUI's **Tools** tab → "Install into an existing wheel system" runs:
   ```bat
   spindoctor install-tools --add-to-system Toolkit
   ```
   Writes the bats and per-game PCLauncher INIs under `<RocketLauncher>/Modules/PCLauncher/Toolkit/`, and adds `<game>` entries (with `genre=Tools`, `manufacturer=SpinDoctor`) to `<HyperSpin>/Databases/Toolkit/Toolkit.xml`. Idempotent on re-run. The target system must already exist and use PCLauncher as its emulator.

3. **Manual** — copy the `.bat` files from `scripts/` into wherever you want and register them yourself.

## Wiring into Windows startup

The GUI's **Tools** tab has a Windows-only "Auto-refresh on cabinet startup" section: click *Schedule auto-refresh* to register a Task Scheduler `ONLOGON` task with a configurable post-log-on delay (default 2 min — gives HyperSpin / RocketLauncher time to settle before the rebuild kicks in). Companion *Remove scheduled task* and *Check task status* buttons round out the lifecycle. Internally it shells out to `schtasks.exe`, so no `pywin32` or admin rights required.

Equivalent CLI invocation:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Refresh Wheels" /rl LIMITED /f ^
  /tr "cmd.exe /c \"spindoctor-fav rebuild --apply & spindoctor-recent rebuild --apply & spindoctor-stats build-wheel --apply\""
```

(`&` rather than `&&` so a failing favorites rebuild doesn't kill the rest of the chain.)

Or drop one of the `.bat` files (from `scripts/`, or those written by `spindoctor install-tools`) into the Windows Startup folder (`shell:startup`).

For macOS, schedule via `crontab -e` with an `@reboot` line, or write a launchd plist under `~/Library/LaunchAgents/`. For Linux, `crontab -e` or a `systemd --user` unit.

## Tools audit — what other arcade utilities does this cabinet already have?

A typical HyperSpin cabinet accumulates a graveyard of third-party utilities — Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Don's HyperTools, HyperT00ls, the CUE Renamer, Hypersearch, plus drivers and mappers like Sinden, DemulShooter, XPadder, JoyToKey, DS4Windows, XOutput. `spindoctor tools-audit` scans `HyperSpin\Tools`, `RocketLauncher\Modules`, the emulators tree, and Program Files for known tools and tells you which ones spindoctor already replaces.

```bat
spindoctor tools-audit
spindoctor tools-audit --extra-path "C:\arcade-utils" --show-unknown
```

| Category | Tools | Replaced by |
|---|---|---|
| ROM / media tools | HyperSpin Checker, HyperT00ls, Don's HyperTools, FatMatch, Tur-Matcher, Tur-RemoveDupes, HyperSpin CUE Renamer, FuzzyRename 3, HyperSync, Hypersearch | `audit`, `verify`, `find-orphan-media`, `find-dupes`, `rename`, `fetch-meta`, `fetch-media`, `find-global` |
| Light gun | Sinden Lightgun, DemulShooter, Arcade Guns Utility | `lightgun configure` (Sinden + DemulShooter wiring per system) |
| Controllers / input | XPadder, JoyToKey, DS4Windows, XOutput, Arcade-One profiles, Atari Fightstick, Arcaid | not absorbed — keep external; expose via `install-tools` |
| Frontend / config GUIs | HyperSpin, HyperHQ, RocketLauncherUI | not absorbed — keep external, useful for one-offs |
| Shaders / visual | SweetFX | out of scope |

The audit never uninstalls anything. Once you've confirmed the spindoctor equivalent works on your library, the listed ROM/media tools are safe to remove. Lightgun and input gear stay installed — spindoctor wraps them rather than replacing them.

## Why these are kept separate from the package

The actual logic lives in `spindoctor/favorites.py`, `spindoctor/recent.py`, and `spindoctor/playtime.py` so the rest of the package can import it. The `scripts/` folder holds only thin runnable shims and Windows convenience files — keeping them separate makes it obvious which files are package internals vs. things the cabinet end-user is meant to invoke directly.
