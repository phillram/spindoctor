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

The `.bat` files assume `spindoctor-fav` / `spindoctor-recent` / `spindoctor-stats` are on `PATH` (they are after `pip install -e .`). For setups without an install, the `.py` wrappers work directly from a checkout.

Full documentation — including how to wire these into the HyperSpin Tools menu and Windows startup, and what to do when you can't run `pip install` on the cabinet — lives at [`docs/standalone-tools.md`](../docs/standalone-tools.md).
