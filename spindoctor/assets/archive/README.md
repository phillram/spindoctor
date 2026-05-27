# Asset Archive

Original versions of bundled assets, kept for reference.

These files are **not installed** by SpinDoctor and are **not shipped** in the
pip package (the `pyproject.toml` package-data globs use `assets/*.ext`, which
is non-recursive and does not match files in this subdirectory).

## Contents

| File | Original resolution / format | Why superseded |
|------|------------------------------|----------------|
| `bg_Favorites.png` | 2752×1536 | HyperSpin renders backgrounds at 1:1 px (no scale); only the top-left corner was visible. Active assets are 1920×1080. |
| `bg_Most_Played.png` | 2752×1536 | Same reason. |
| `bg_Recently_Played.png` | 2752×1536 | Same reason. |
| `music_Favorites.mp3` | 192 kbps MP3, ~57.7 s | Active-browsing music slot no longer bundled — attract-mode audio comes from the MP4 video track. |
| `music_Most_Played.mp3` | 192 kbps MP3, ~57.9 s | Same reason. |
| `music_Recently_Played.mp3` | 192 kbps MP3, ~61.5 s | Same reason. |

## Restoring an MP3

To re-enable active-browsing music for a wheel:
1. Copy the `.mp3` here to `spindoctor/assets/`
2. Add an entry to `_MUSIC_ASSETS` in `spindoctor/rocketlauncher.py`
3. Add `"assets/*.mp3"` back to `pyproject.toml` package-data

## Restoring an original background

The 2752×1536 originals were the raw export resolution. They are archived in
case a higher-resolution cabinet display ever needs them, or for re-generating
the MP4 video files with different ffmpeg settings.
