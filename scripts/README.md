# scripts/

Standalone helpers for the **Favorites**, **Recently Played**, and **Most Played** wheels — designed to run from a Windows boot trigger, a scheduled task, or a HyperSpin Tools menu entry without loading the full SpinDoctor CLI.

| File | Purpose |
|---|---|
| `spindoctor-fav.py` | Python wrapper → `spindoctor.favorites:main` |
| `spindoctor-recent.py` | Python wrapper → `spindoctor.recent:main` |
| `spindoctor-stats.py` | Python wrapper → `spindoctor.playtime:main` |
| `Refresh Favorites.bat` | `spindoctor-fav rebuild --apply` |
| `Refresh Recently Played.bat` | `spindoctor-recent rebuild --apply` |
| `Refresh Most Played.bat` | `spindoctor-stats build-wheel --apply` |
| `Refresh Both.bat` | All three in sequence |

The `.bat` files call `spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` by bare name. `cmd.exe` resolves that via `PATHEXT` — so any of these satisfy the call:

- the standalone Windows `.exe` binaries from a [GitHub Release](https://github.com/phillram/spindoctor/releases) (no Python needed), placed next to the `.bat` files or anywhere on `PATH`
- the `pip install -e .` entry-point shims (also on `PATH`)

For checkouts where neither is present, run the `.py` wrappers directly via `python scripts\spindoctor-fav.py …` — those require a Python install.

Full documentation — including how to wire these into the HyperSpin Tools menu and Windows startup, and what to do when you can't run `pip install` on the cabinet — lives at [`docs/standalone-tools.md`](../docs/standalone-tools.md).

## Other commands without standalone wrappers

These run only inside the full `spindoctor` CLI — no `.bat` shortcut needed because they're either read-only (no boot trigger value) or interactive:

| Command | Purpose |
|---|---|
| `spindoctor tools-audit` | Read-only inventory of installed third-party arcade utilities |
| `spindoctor find-global "title"` | Cross-system database search |
| `spindoctor lightgun {detect,audit,configure}` | Sinden + DemulShooter wiring per system |

See [`docs/standalone-tools.md`](../docs/standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have) for `tools-audit` and [`docs/lightgun.md`](../docs/lightgun.md) for the lightgun walkthrough.
