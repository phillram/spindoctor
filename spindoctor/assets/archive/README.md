# Asset Archive

Reference copies and superseded assets. Files here are **not installed** by SpinDoctor
and are **not shipped** in the pip package (`pyproject.toml` package-data globs use
`assets/*.ext`, which is non-recursive and excludes this subdirectory).

## Emulator modules (reference copies)

These AHK files are the **canonical installed versions** of customised RocketLauncher
modules. The live files are on the cabinet; these copies exist so the changes are
documented in version control alongside the architecture notes.

| File | Cabinet path | Status |
|------|-------------|--------|
| `Phoenix.ahk` | `D:\Arcade\RocketLauncher\Modules\Phoenix\Phoenix.ahk` | Active — Atari Jaguar launch fix (D:→J: Dump path rewrite). See arch doc for details. |

## Superseded media assets

These files were bundled with SpinDoctor at one point and have since been replaced
or removed. They are kept in case the originals are ever needed again.

| File | Original spec | Why superseded |
|------|---------------|----------------|
| `bg_Favorites.png` | 2752×1536 PNG | HyperSpin renders backgrounds at 1:1 px; only the top-left corner was visible. Active assets are 1920×1080. |
| `bg_Most_Played.png` | 2752×1536 PNG | Same reason. |
| `bg_Recently_Played.png` | 2752×1536 PNG | Same reason. |
| `music_Favorites.mp3` | 192 kbps MP3, ~57.7 s | Active-browsing music slot no longer bundled — attract-mode audio comes from the MP4 video track. |
| `music_Most_Played.mp3` | 192 kbps MP3, ~57.9 s | Same reason. |
| `music_Recently_Played.mp3` | 192 kbps MP3, ~61.5 s | Same reason. |

## Restoring a superseded MP3

To re-enable active-browsing music for a wheel:
1. Copy the `.mp3` here to `spindoctor/assets/`
2. Add an entry to `_MUSIC_ASSETS` in `spindoctor/rocketlauncher.py`
3. Add `"assets/*.mp3"` back to `pyproject.toml` package-data

## Restoring an original background

The 2752×1536 originals were the raw export resolution. They are archived in
case a higher-resolution display ever needs them, or for re-generating MP4 video
files with different ffmpeg settings.
