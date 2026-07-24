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
| `Refresh All.bat` | All three in sequence |

The `.bat` files call `spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` by bare name. `cmd.exe` resolves that via `PATHEXT` — so any of these satisfy the call:

- the standalone Windows `.exe` binaries from a [GitHub Release](https://github.com/phillram/spindoctor/releases) (no Python needed), placed next to the `.bat` files or anywhere on `PATH`
- the `pip install -e .` entry-point shims (also on `PATH`)

For checkouts where neither is present, run the `.py` wrappers directly via `python scripts\spindoctor-fav.py …` — those require a Python install.

Full documentation — including how to wire these into the HyperSpin Tools menu and Windows startup, and what to do when you can't run `pip install` on the cabinet — lives at [`docs/standalone-tools.md`](../docs/standalone-tools.md).

> **Prefer a window over a `.bat` file?** `spindoctor-gui` (or `spindoctor-gui.exe` from the binary release) has a **Custom Wheels** tab (Step 2 — Refresh custom wheels) with a checkbox per wheel (all pre-ticked) and a **Refresh selected** button. Same outcome as `Refresh All.bat` when all three are checked, or any subset when you untick some — no `cmd.exe` required. The `.bat` files remain the right answer for HyperSpin Tools menu entries and Windows Startup tasks; the GUI is the right answer for ad-hoc manual refreshes. See [`docs/windows-binaries.md#gui-launcher`](../docs/windows-binaries.md#gui-launcher).

## LED animation batch generator

| File | Purpose |
|---|---|
| `generate_lwax_patterns.py` | Generate a full library of LEDBlinky `.lwax` LED animations (sweeps, pulses, rain, breathe, rainbow, etc.) |

Run `python scripts/generate_lwax_patterns.py` to write ~170 raw (unsigned) `.lwax` files + a `README.md` index into `~/Downloads/spindoctor-lwax-patterns/`. Deterministic — no AI, no arguments. It reads the cabinet LED layout from `~/Downloads/LEDBlinkyInputMap.xml` if present, else the committed reference at [`docs/reference/LEDBlinkyInputMap.xml`](../docs/reference/LEDBlinkyInputMap.xml). Each file still needs the one-time LedBlinky Animation Editor **Save As** signing step before use. Full walkthrough: [`docs/commands.md` → "Generating a full pattern batch"](../docs/commands.md#generating-a-full-pattern-batch-scriptsgenerate_lwax_patternspy). For a single simple fade, the built-in `spindoctor ledblinky lwax fade` command is usually enough.

## Other commands without standalone wrappers

These run only inside the full `spindoctor` CLI — no `.bat` shortcut needed because they're either read-only (no boot trigger value) or interactive:

| Command | Purpose |
|---|---|
| `spindoctor tools-audit` | Read-only inventory of installed third-party arcade utilities |
| `spindoctor find-global "title"` | Cross-system database search |
| `spindoctor lightgun {detect,audit,configure}` | Sinden + DemulShooter wiring per system |

See [`docs/standalone-tools.md`](../docs/standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have) for `tools-audit` and [`docs/lightgun.md`](../docs/lightgun.md) for the lightgun walkthrough.
