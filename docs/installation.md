# Installation

**Requirements:** Python 3.9+. Windows is the primary target (HyperSpin is a Windows app), but the CLI itself runs on macOS and Linux for development and testing.

## Install

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor
cd C:\spindoctor
pip install -e .[all]
```

`[all]` pulls in every optional extra. If you'd rather pick à-la-carte:

| Extra | Pulls in | What it enables |
|---|---|---|
| `[xml]` | `lxml` | Lossless XML round-trips — preserves comments and attribute order written by HyperHQ. Strongly recommended. |
| `[archives]` | `py7zr`, `rarfile` | `verify` and `find-dupes --by-content` can hash inside `.7z` / `.rar`. `.zip`, `.gz`, and `.chd` are built-in either way. |
| `[preview]` | `Pillow` | `spindoctor preview --format png` builds composited PNG contact sheets. HTML mode works without it. |
| `[all]` | All of the above | Everything in one install. |

```bat
pip install -e .[archives]
pip install -e .[preview]
```

## Verify

```bat
spindoctor --version
spindoctor systems         :: lists configured systems (after `config init`)
spindoctor tools-audit     :: inventory of third-party arcade utilities, read-only
```

`tools-audit` is the safest first command on a cabinet — it never touches files, and the report tells you which legacy tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Sinden, DemulShooter, …) are now redundant with built-in spindoctor commands. See [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have).

## Console scripts installed

| Command | Purpose |
|---|---|
| `spindoctor` | Full CLI |
| `spindoctor-fav` | Standalone Favorites wheel manager |
| `spindoctor-recent` | Standalone Recently Played rebuild |
| `spindoctor-stats` | Standalone playtime reports + Most Played wheel |

The three standalone scripts are minimal `argparse` wrappers around the same library functions — useful for boot triggers and Tools menu entries because they skip the rich/click overhead. See [Standalone tools](standalone-tools.md).

Other commonly-used commands that ship only inside the full `spindoctor` CLI (no separate console script):

| Command | Purpose | Read-only? |
|---|---|---|
| `spindoctor tools-audit` | Inventory installed arcade utilities; flags spindoctor replacements | yes |
| `spindoctor find-global "title"` | Search every system's HyperSpin database for a title | yes |
| `spindoctor lightgun detect / audit / configure` | Wire Sinden + DemulShooter into per-system RocketLauncher hooks | `detect`/`audit` read-only; `configure` dry-run by default |

See [Light guns](lightgun.md) for the Sinden / DemulShooter walkthrough.

## Running without `pip install`

If you can't (or don't want to) install the package, the wrappers in `scripts/` work directly from a checkout — they `sys.path.insert` the repo root so `import spindoctor` resolves:

```bat
python C:\spindoctor\scripts\spindoctor-fav.py rebuild --apply
python -m spindoctor.cli systems
```

You still need Python and the runtime dependencies (`pip install -r requirements.txt`).
