# Synthetic Wheel Media Setup

This guide covers all the visual and audio assets for the three SpinDoctor-managed
synthetic wheels: **Favorites**, **Most Played**, and **Recently Played**.

---

## What SpinDoctor installs automatically

Every `rebuild` / `--apply` run installs these files without extra flags:

| File | Location | What it does |
|------|----------|-------------|
| `Favorites.png` | `Media\Main Menu\Images\Wheel\` | Logo shown in HyperSpin's system selector |
| `Most Played.png` | `Media\Main Menu\Images\Wheel\` | Logo shown in HyperSpin's system selector |
| `Recently Played.png` | `Media\Main Menu\Images\Wheel\` | Logo shown in HyperSpin's system selector |
| `Favorites.png` | `Media\Favorites\Images\Backgrounds\` | Background image while browsing |
| `Most Played.png` | `Media\Most Played\Images\Backgrounds\` | Background image while browsing |
| `Recently Played.png` | `Media\Recently Played\Images\Backgrounds\` | Background image while browsing |
| `Favorites.mp3` | `Media\Favorites\Sound\` | Background music while browsing |
| `Most Played.mp3` | `Media\Most Played\Sound\` | Background music while browsing |
| `Recently Played.mp3` | `Media\Recently Played\Sound\` | Background music while browsing |
| `<System>.ini` | `HyperSpin\Settings\` | Lets HyperSpin open the sub-wheel |

**Install condition:** every asset is only written when the destination is absent —
SpinDoctor never overwrites a file you placed there yourself.  To replace any bundled
file with your own version, drop your file at the path shown above and rebuild will leave
it alone on every subsequent run.

The rebuild summary shows the status of each asset:
```
Wheel art:   installed → D:\Arcade\HyperSpin\Media\Main Menu\Images\Wheel\Favorites.png
Background:  installed → D:\Arcade\HyperSpin\Media\Favorites\Images\Backgrounds\Favorites.png
Music:       installed → D:\Arcade\HyperSpin\Media\Favorites\Sound\Favorites.mp3
```

Per-game media (wheel logos, backgrounds, videos, themes for each individual game in the
list) is mirrored from the source system automatically by the media-mirror step.

---

## Media that requires manual setup

The assets below are **not** bundled with SpinDoctor and require manual placement.
They live under `Media\<SystemName>\` — for example `Media\Favorites\`.

### System background image

> **Already bundled.** SpinDoctor installs a default background automatically.
> Follow these instructions only if you want to replace it with your own.

Shown as the backdrop when you're browsing inside the wheel.

**File:** `Media\<SystemName>\Images\Backgrounds\<SystemName>.png`

**Examples:**
```
Media\Favorites\Images\Backgrounds\Favorites.png
Media\Most Played\Images\Backgrounds\Most Played.png
Media\Recently Played\Images\Backgrounds\Recently Played.png
```

**Via SpinDoctor CLI:**
```bat
spindoctor media-add "path\to\background.png" --system "Favorites" --type background --game "Favorites" --apply
```

**Manually:** Copy your PNG to the path above.  HyperSpin accepts `.png` and `.jpg`.

---

### System theme

A HyperSpin theme controls the animated background, the font, wheel item sizing, and
optionally embeds sounds.  Themes ship as `.zip` files.

**File:** `Media\<SystemName>\Themes\<SystemName>.zip`

**Examples:**
```
Media\Favorites\Themes\Favorites.zip
Media\Most Played\Themes\Most Played.zip
Media\Recently Played\Themes\Recently Played.zip
```

**Finding themes:** HyperSpin theme packs are available on EmuMovies, HyperSpin forums,
and Hyperspin-FE.com.  Look for a "Main Menu" or "System" theme pack that matches the
system name, or repurpose any existing `.zip` theme.

**Via SpinDoctor CLI:**
```bat
spindoctor media-add "path\to\Favorites.zip" --system "Favorites" --type theme --game "Favorites" --apply
```

**Manually:** Copy the `.zip` file (do **not** extract it — HyperSpin reads the archive
directly) to the Themes path above.

---

### Background music

> **Already bundled.** SpinDoctor installs default background music automatically.
> Follow these instructions only if you want to replace it with your own.

Plays on loop while browsing the wheel.

**File:** `Media\<SystemName>\Sound\<SystemName>.mp3`

**Examples:**
```
Media\Favorites\Sound\Favorites.mp3
Media\Most Played\Sound\Most Played.mp3
Media\Recently Played\Sound\Recently Played.mp3
```

**Via SpinDoctor CLI:**
```bat
spindoctor media-add "path\to\Favorites.mp3" --system "Favorites" --type sound --game "Favorites" --apply
```

**Manually:** Copy your `.mp3` to the Sound path above.

---

### Navigation sounds

HyperSpin plays sounds when the wheel cursor moves and when a game is selected.
Per-system sounds override the global HyperSpin defaults.

**Directory:** `Media\<SystemName>\Sound\`

**Files HyperSpin looks for inside that folder:**

| Filename | When it plays |
|----------|--------------|
| `navigate.mp3` | Every cursor move left/right |
| `select.mp3` | Game selected (before launch) |
| `back.mp3` | Wheel closed / back pressed |
| `letter.mp3` | Jump-to-letter navigation |
| `game_over.mp3` | Optional; played after a session |

Not all files are required — HyperSpin falls back to its global sounds for any that are missing.

**Via SpinDoctor CLI:**
```bat
spindoctor media-add "path\to\navigate.mp3" --system "Favorites" --type sound --game "navigate" --apply
spindoctor media-add "path\to\select.mp3"   --system "Favorites" --type sound --game "select"   --apply
```

**Manually:** Copy `.mp3` files to `Media\<SystemName>\Sound\`.

---

### System video preview

Shown when the wheel is idle (intro video / attract mode for the system itself, not for a
specific game).

**File:** `Media\<SystemName>\Video\<SystemName>.mp4`

**Examples:**
```
Media\Favorites\Video\Favorites.mp4
Media\Most Played\Video\Most Played.mp4
Media\Recently Played\Video\Recently Played.mp4
```

**Via SpinDoctor CLI:**
```bat
spindoctor media-add "path\to\Favorites.mp4" --system "Favorites" --type video --game "Favorites" --apply
```

**Manually:** Copy your `.mp4` (or `.avi`, `.flv`) to the Video path above.

---

## Complete media layout for one synthetic wheel

```
HyperSpin\
└── Media\
    ├── Main Menu\
    │   └── Images\
    │       └── Wheel\
    │           ├── Favorites.png          ← AUTO: wheel selector logo
    │           ├── Most Played.png        ← AUTO: wheel selector logo
    │           └── Recently Played.png    ← AUTO: wheel selector logo
    │
    └── Favorites\
        ├── Images\
        │   ├── Wheel\                     ← per-game wheel art (mirrored from source)
        │   ├── Backgrounds\
        │   │   └── Favorites.png          ← AUTO: system background image
        │   └── Artwork1\                  ← per-game art (mirrored from source)
        ├── Themes\
        │   ├── Favorites.zip              ← system theme (manual — see above)
        │   └── <game>.zip                 ← per-game themes (mirrored from source)
        ├── Sound\
        │   ├── Favorites.mp3              ← AUTO: background music
        │   ├── navigate.mp3               ← navigation sounds (manual — see above)
        │   ├── select.mp3
        │   └── ...
        └── Video\
            ├── Favorites.mp4              ← system intro video (manual — see above)
            └── <game>.mp4                 ← per-game videos (mirrored from source)
```

**AUTO** = installed by `rebuild --apply` from the bundled package assets.  Only written
when absent — user files at these paths are never overwritten.

> The same layout applies to `Most Played\` and `Recently Played\` — substitute the
> system name everywhere `Favorites` appears.

---

## Fetching system-level media from ScreenScraper

SpinDoctor can download Main Menu media (backgrounds, system videos, system wheel art) for
standard consoles via ScreenScraper.  The synthetic wheels are not in the ScreenScraper
database, so this approach works only for real arcade / console systems.  For synthetic
wheels, manual placement (as above) is the only option.

```bat
spindoctor fetch-media --system "MAME" --media-type background --apply
```

---

## Replacing the bundled wheel art images

SpinDoctor ships wheel art for all three synthetic wheels.  To use your own images instead:

1. Create your PNG at the correct path (see table above).
2. Run `spindoctor favorites rebuild --apply` (or the equivalent for the wheel).
3. SpinDoctor detects the file already exists and leaves it untouched.

The bundled images are `1536 × 1024 px` RGBA PNGs on a transparent background.
HyperSpin renders wheel art at a size controlled by your theme; a wide landscape
aspect ratio (roughly `4:1`) tends to look best in the standard wheel layout.
