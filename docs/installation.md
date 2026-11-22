# Installation

For Windows without Python, use the [standalone binaries](windows-binaries.md).
Source installs require Python 3.8+; the cabinet integration target is Windows.
Library-management code also runs on macOS/Linux, but Windows hardware,
Task Scheduler and game-launch integration do not.

## Pip install from source

```text
git clone https://github.com/phillram/spindoctor
cd spindoctor
python -m pip install -e ".[all]"
spindoctor --version
spindoctor-gui
```

The GUI needs Tkinter (usually included with Windows Python; install your OS's
Tk package on Linux). A virtual environment is recommended.

| Extra | Adds |
|---|---|
| `xml` | `lxml`, preserving XML comments and attribute order |
| `archives` | `.7z`/`.rar` reading (`rarfile` can need an external extraction tool) |
| `preview` | Pillow for PNG previews |
| `gui` | Optional folder drag-and-drop |
| `all` | All runtime extras above |
| `dev` | pytest and lxml; see [testing](testing.md) for other tools |

Base install: `python -m pip install -e .`. ZIP/GZip reading and CHD-header
verification need no archive extra.

## Console scripts installed

`spindoctor`, `spindoctor-gui`, `spindoctor-fav`, `spindoctor-recent` and
`spindoctor-stats`. The three wheel helpers share the main configuration.

## Running without pip install

From the checkout root, with dependencies installed:

```text
python -m spindoctor.cli --help
python -m spindoctor.gui
python scripts/spindoctor-fav.py rebuild
python scripts/spindoctor-recent.py rebuild
python scripts/spindoctor-stats.py summary
```

Use **Setup** or `spindoctor config init` next. See [first-time setup](setup.md).
