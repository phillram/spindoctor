# scripts/

Standalone helpers for the **Favorites**, **Recently Played**, and
**Most Played** synthetic HyperSpin wheels (and the playtime reporter
that backs the latter). Everything in this folder is meant to run on
its own — on a Windows boot trigger, a scheduled task, or from a
HyperSpin Tools menu entry — without the user opening a console or
loading the full SpinDoctor CLI.

## What's here

| File | Purpose |
|------|---------|
| `spindoctor-fav.py` | Python wrapper that calls `spindoctor.favorites:main` |
| `spindoctor-recent.py` | Python wrapper that calls `spindoctor.recent:main` |
| `spindoctor-stats.py` | Python wrapper that calls `spindoctor.playtime:main` |
| `Refresh Favorites.bat` | Windows batch invoking `spindoctor-fav rebuild` |
| `Refresh Recently Played.bat` | Windows batch invoking `spindoctor-recent rebuild` |
| `Refresh Most Played.bat` | Windows batch invoking `spindoctor-stats build-wheel --apply` |
| `Refresh Both.bat` | Run fav + recent + most-played in sequence |

The Python wrappers exist so users without `pip install -e .` can still
run the tools directly:

```bat
python scripts\spindoctor-fav.py rebuild
python scripts\spindoctor-recent.py rebuild --limit 30
python scripts\spindoctor-stats.py summary
```

The `.bat` files assume `spindoctor-fav`, `spindoctor-recent`, and
`spindoctor-stats` are on `PATH` (they will be after `pip install -e .`).

## Wiring into HyperSpin's Tools menu

Either:

* Run `spindoctor install-tools` (writes copies into
  `<RocketLauncher>/Modules/HyperLaunch/Tools/spindoctor/`), **or**
* Manually copy the three `.bat` files from this folder into
  HyperSpin's Tools directory (path varies by install — typically
  `<HyperSpin>/Apps/` or `<RocketLauncher>/Modules/HyperLaunch/Tools/`).

Then register them via HyperHQ → Tools so they appear inside the cabinet
UI.

## Wiring into Windows startup

Schedule both rebuilds at user log-on so the wheels are fresh when the
user reaches HyperSpin:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Refresh Wheels" ^
  /tr "cmd /c spindoctor-fav rebuild && spindoctor-recent rebuild && spindoctor-stats build-wheel --apply"
```

Or drop `Refresh Both.bat` into the Windows Startup folder
(`shell:startup`).

## Why these aren't in `spindoctor/`

The actual logic lives in `spindoctor/favorites.py`,
`spindoctor/recent.py`, and `spindoctor/playtime.py` so the rest of
the package can import it. This folder holds only thin runnable shims
and Windows convenience files — keeping them separate makes it obvious
which files are package internals vs. things the cabinet end-user is
meant to invoke directly.
