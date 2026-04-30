# Standalone tools

Three minimal CLIs and a handful of `.bat` files designed to run on every system boot or directly from HyperSpin's Tools menu — **without loading the full SpinDoctor CLI**. They share `~/.spindoctor/config.json` with the main `spindoctor` command but use a light `argparse`-based entry point so they launch fast enough to use as a boot trigger.

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

The three `.bat` files call `spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` which only exist after `pip install`. There are three working setups:

1. **Full install (recommended).** `pip install -e .` from a checkout. Console scripts land on `PATH`, the .bat files work as-is.
2. **Source on disk, no install.** Copy the whole repo to the cabinet, install Python + dependencies (`pip install -r requirements.txt`, mainly `lxml`), and rewrite each `.bat` to call the wrappers directly:
   ```bat
   python C:\path\to\spindoctor\scripts\spindoctor-fav.py rebuild --apply
   ```
   The wrappers `sys.path.insert(0, repo_root)` so `import spindoctor` resolves without an editable install.
3. **`.bat` files only.** Won't work — they're shortcuts to a CLI that doesn't exist on the box.

Hard requirements regardless of approach: Python 3.9+, `lxml`, and the `spindoctor` package importable somehow.

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

Two equivalent options:

1. **Auto-install** — write the four `.bat` files into `<RocketLauncher>/Modules/HyperLaunch/Tools/spindoctor/`:
   ```bat
   spindoctor install-tools
   ```
2. **Manual** — copy the `.bat` files from `scripts/` into HyperSpin's Tools directory yourself.

Either way, register them in HyperHQ → Tools so they appear inside the cabinet UI as `Refresh Favorites`, `Refresh Recently Played`, `Refresh Most Played`, and `Refresh Both`.

## Wiring into Windows startup

Run the rebuilds at user log-on so wheels are fresh by the time HyperSpin loads:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Refresh Wheels" ^
  /tr "cmd /c spindoctor-fav rebuild --apply && spindoctor-recent rebuild --apply && spindoctor-stats build-wheel --apply"
```

Or drop one of the `.bat` files (from `scripts/`, or those written by `spindoctor install-tools`) into the Windows Startup folder (`shell:startup`).

## Why these are kept separate from the package

The actual logic lives in `spindoctor/favorites.py`, `spindoctor/recent.py`, and `spindoctor/playtime.py` so the rest of the package can import it. The `scripts/` folder holds only thin runnable shims and Windows convenience files — keeping them separate makes it obvious which files are package internals vs. things the cabinet end-user is meant to invoke directly.
