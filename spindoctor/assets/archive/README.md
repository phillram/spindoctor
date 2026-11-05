# Asset Archive

Reference copies and superseded assets. Files here are **not installed** by SpinDoctor
and are **not shipped** in the pip package (`pyproject.toml` package-data globs use
`assets/*.ext`, which is non-recursive and excludes this subdirectory).

## Emulator modules (reference copies)

These AHK files are historical reference copies of customised RocketLauncher modules,
not evidence of any user's current installation. Example paths correspond to the
[cabinet reference](../../../docs/cabinet-architecture-reference.md).

| File | Cabinet path | Status |
|------|-------------|--------|
| `Phoenix.ahk` | `<rocketlauncher_dir>\Modules\Phoenix\Phoenix.ahk` | Reference for the Atari Jaguar Dump-path rewrite described in the cabinet guide. |

## Superseded media assets

These files were bundled with SpinDoctor at one point and have since been replaced
or removed. They are kept in case the originals are ever needed again.

| File | Original spec | Why superseded |
|------|---------------|----------------|
| `bg_Favorites.png` | 2752×1536 PNG | HyperSpin renders backgrounds at 1:1 px; only the top-left corner was visible. Active assets are 1920×1080. |
| `bg_Most_Played.png` | 2752×1536 PNG | Same reason. |
| `bg_Recently_Played.png` | 2752×1536 PNG | Same reason. |
| `music_Favorites.mp3` | 192 kbps MP3, ~57.7 s | Archived copy; active-browsing music is also bundled in the current package. |
| `music_Most_Played.mp3` | 192 kbps MP3, ~57.9 s | Same reason. |
| `music_Recently_Played.mp3` | 192 kbps MP3, ~61.5 s | Same reason. |

## Active-browsing music

Current releases already include MP3 assets and `_MUSIC_ASSETS` entries for the
synthetic wheels. No packaging or code changes are needed. Rebuild installs missing
assets without replacing existing custom files. See
[Synthetic wheel media](../../../docs/synthetic-wheel-media.md#what-spindoctor-installs-automatically).

## Restoring an original background

The 2752×1536 originals were the raw export resolution. They are archived in
case a higher-resolution display ever needs them, or for re-generating MP4 video
files with different ffmpeg settings.
