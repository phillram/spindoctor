# Synthetic-wheel media

Favorites, Recently Played and Most Played mirror source games' art. Recompiled
also has bundled system assets but is not a fourth statistics/favorites builder.

## Two media locations

| Location | Shows |
|---|---|
| `Media/Main Menu/` | System selector logos, backgrounds, themes, video/music |
| `Media/<System>/` | Game-list art, themes, videos and navigation sound |

Rebuilds and supported main-menu registration install missing bundled system
assets: `<System>.png` in Main Menu `Images/Wheel` and `Images/Backgrounds`,
`<System>.mp4` in `Video`, `<System>.zip` in `Themes`, `<System>.mp3` in `Sound`,
and `Wheel Click.mp3` inside the system's `Sound`. Missing HyperSpin
`Settings/<System>.ini` is also created where supported.
Existing custom assets are preserved, not replaced.

## Mirrored game media

Wheel builders mirror from the original system; fetch missing artwork there,
then rebuild. Default `auto` tries hardlinks, falling back to copies.
Linked files share bytes: keep an independent backup before in-place edits.
Custom target systems need ownership evidence; a real PCLauncher wheel is not
safe to overwrite merely because its launcher type matches.

## Themes and video

Bundled main-menu themes hide the video visual while its audio plays over the
background. Custom themes can change this. For broad legacy compatibility,
replacement videos should use MP4/H.264 Main profile, level 4.0, yuv420p and AAC.
Avoid B-frames for very-low-frame-rate static-image videos to prevent delayed
first frames. This is a conservative encoding recipe, not every decoder's limit.

If video is absent, check:

- Filename stem exactly matches the database system/game name.
- Theme zip and video exist in the correct Main Menu versus game-list location.
- HyperSpin's volume/playback settings permit it.
- `[video defaults] path=` is blank or points to the intended folder: a redirect
  replaces the local Video lookup; there is no per-game fallback.

## Blank fallback themes

```text
spindoctor theme-fill --system MAME
spindoctor theme-fill --system MAME --default
```

The first previews missing per-game theme zips. `--default` installs one
`Themes/default.zip` fallback instead. Repeat with `--apply`; existing themes
are never overwritten. Use the default option when one shared fallback suffices.

See [wheel setup](standalone-tools.md), [cabinet formats](cabinet-architecture-reference.md)
and [troubleshooting](troubleshooting.md#media-and-wheels).
