# Synthetic Wheel Media Setup

This guide covers all the visual and audio assets for the three SpinDoctor-managed
synthetic wheels: **Favorites**, **Most Played**, and **Recently Played**.

---

## HyperSpin media — two separate locations

It helps to understand that HyperSpin reads system-level media from **two different
directories** depending on what it is showing:

| Location | When it appears | Examples |
|----------|----------------|---------|
| `Media\Main Menu\` | **Main Menu** — the top-level wheel where you pick a system; attract mode | Wheel logo, background behind the logo, music during attract mode |
| `Media\<SystemName>\` | **Inside the system wheel** — the game list for that system | Per-game wheel art, per-game background, per-game theme |

The assets SpinDoctor bundles target the **Main Menu** — they appear during attract mode
on the top-level wheel, the same context where videos play for each console before
the wheel spins to the next one.  Per-game media inside the wheel is already handled
by the existing media-mirror step (mirrored from the source systems).

---

## What SpinDoctor installs automatically

Every `rebuild --apply` run installs these files without extra flags:

| File | Main Menu location | What it does |
|------|--------------------|-------------|
| `Favorites.png` | `Media\Main Menu\Images\Wheel\` | Wheel logo in the system selector |
| `Most Played.png` | `Media\Main Menu\Images\Wheel\` | Wheel logo in the system selector |
| `Recently Played.png` | `Media\Main Menu\Images\Wheel\` | Wheel logo in the system selector |
| `Favorites.png` | `Media\Main Menu\Images\Backgrounds\` | Background shown during attract mode |
| `Most Played.png` | `Media\Main Menu\Images\Backgrounds\` | Background shown during attract mode |
| `Recently Played.png` | `Media\Main Menu\Images\Backgrounds\` | Background shown during attract mode |
| `Favorites.mp3` | `Media\Main Menu\Sound\` | Music played during attract mode |
| `Most Played.mp3` | `Media\Main Menu\Sound\` | Music played during attract mode |
| `Recently Played.mp3` | `Media\Main Menu\Sound\` | Music played during attract mode |
| `Favorites.mp4` | `Media\Main Menu\Video\` | Attract-mode video (background + music, 57.7 s) |
| `Most Played.mp4` | `Media\Main Menu\Video\` | Attract-mode video (background + music, 57.9 s) |
| `Recently Played.mp4` | `Media\Main Menu\Video\` | Attract-mode video (background + music, 61.5 s) |
| `<System>.ini` | `HyperSpin\Settings\` | Lets HyperSpin open the sub-wheel |

**Install condition:** every asset is only written when the destination is absent —
SpinDoctor never overwrites a file you placed there yourself.

The rebuild summary reports each asset:
```
Wheel art:   installed → D:\Arcade\HyperSpin\Media\Main Menu\Images\Wheel\Favorites.png
Background:  installed → D:\Arcade\HyperSpin\Media\Main Menu\Images\Backgrounds\Favorites.png
Music:       installed → D:\Arcade\HyperSpin\Media\Main Menu\Sound\Favorites.mp3
Video:       installed → D:\Arcade\HyperSpin\Media\Main Menu\Video\Favorites.mp4
```

---

## Attract-mode behaviour

HyperSpin's attract mode (when the cabinet is idle) cycles through every system in
`Main Menu.xml`.  For each system it shows:

1. The **wheel logo** (`Images\Wheel\<System>.png`) — always shown
2. The **background image** (`Images\Backgrounds\<System>.png`) — shown behind the logo
3. The **video** (`Video\<System>.mp4`) — plays if present; attract mode timer controls
   when it advances regardless of video length (see `Attract_Mode_Time` in
   `HyperSpin\Settings\HyperSpin.ini`)
4. The **music** (`Sound\<System>.mp3`) — plays while this system is highlighted

The three synthetic wheels are part of this rotation.  Items 1, 2, and 4 are bundled
and installed automatically.  Item 3 (attract mode video) is **not** bundled — see below
if you want to add one.

---

## Media that requires manual placement

### Attract-mode video

> **Already bundled.** SpinDoctor installs attract-mode videos automatically.
> Follow these instructions only if you want to replace them with your own.

Each video is a static-frame MP4 (background image + music looped to exactly 2× the
music track duration).  HyperSpin plays the video and advances to the next system in
the attract rotation when it ends — no global timer setting is required.

| Wheel | Duration |
|-------|---------|
| Favorites | 57.7 s (2 × 28.8 s) |
| Most Played | 57.9 s (2 × 29.0 s) |
| Recently Played | 61.5 s (2 × 30.8 s) |

**File:** `Media\Main Menu\Video\<SystemName>.mp4`

**To replace with your own:** Drop your `.mp4` at the path above, then rebuild.
SpinDoctor detects the file exists and skips the install on every subsequent run.

---

### Attract-mode theme

A theme `.zip` controls the animated Main Menu background and layout for a system's
slot in the attract cycle.

**File:** `Media\Main Menu\Themes\<SystemName>.zip`

**Examples:**
```
Media\Main Menu\Themes\Favorites.zip
Media\Main Menu\Themes\Most Played.zip
Media\Main Menu\Themes\Recently Played.zip
```

**Finding themes:** HyperSpin theme packs are available on EmuMovies, HyperSpin forums,
and Hyperspin-FE.com.  Look for a "Main Menu" theme pack.

**Manually:** Copy the `.zip` file (do **not** extract it — HyperSpin reads the archive
directly) to the Themes path above.

---

### Navigation sounds (inside the game list)

These are separate from attract-mode music.  They play when you move the cursor or
select a game while browsing the game list **inside** a synthetic wheel.

**Directory:** `Media\<SystemName>\Sound\`  ← note: inside the system, not Main Menu

**Files HyperSpin looks for:**

| Filename | When it plays |
|----------|--------------|
| `navigate.mp3` | Every cursor move left/right |
| `select.mp3` | Game selected (before launch) |
| `back.mp3` | Wheel closed / back pressed |
| `letter.mp3` | Jump-to-letter navigation |

Not all files are required — HyperSpin falls back to its global sounds for any that
are missing.

**Via SpinDoctor CLI:**
```bat
spindoctor media-add "path\to\navigate.mp3" --system "Favorites" --type sound --game "navigate" --apply
spindoctor media-add "path\to\select.mp3"   --system "Favorites" --type sound --game "select"   --apply
```

**Manually:** Copy `.mp3` files to `Media\Favorites\Sound\` (or `Most Played`, etc.).

---

## Replacing a bundled file with your own

Drop your own file at the exact path shown in the table above, then run rebuild —
SpinDoctor detects the file already exists and skips it on every subsequent run.

---

## Complete media layout

```
HyperSpin\
└── Media\
    └── Main Menu\                         ← ALL system-level / attract-mode media lives here
        ├── Images\
        │   ├── Wheel\
        │   │   ├── Favorites.png          ← AUTO: wheel logo
        │   │   ├── Most Played.png        ← AUTO: wheel logo
        │   │   └── Recently Played.png    ← AUTO: wheel logo
        │   └── Backgrounds\
        │       ├── Favorites.png          ← AUTO: attract-mode background
        │       ├── Most Played.png        ← AUTO: attract-mode background
        │       └── Recently Played.png    ← AUTO: attract-mode background
        ├── Sound\
        │   ├── Favorites.mp3              ← AUTO: attract-mode music
        │   ├── Most Played.mp3            ← AUTO: attract-mode music
        │   └── Recently Played.mp3        ← AUTO: attract-mode music
        ├── Video\
        │   ├── Favorites.mp4              ← AUTO: attract-mode video (57.7 s)
        │   ├── Most Played.mp4            ← AUTO: attract-mode video (57.9 s)
        │   ├── Recently Played.mp4        ← AUTO: attract-mode video (61.5 s)
        │   └── ...
        └── Themes\
            ├── Favorites.zip              ← attract-mode theme (manual)
            └── ...

    └── Favorites\                         ← per-game media (auto-mirrored from source systems)
        ├── Images\
        │   ├── Wheel\      ← per-game logos
        │   ├── Backgrounds\ ← per-game backgrounds
        │   └── Artwork1\   ← per-game art
        ├── Themes\         ← per-game themes
        ├── Sound\          ← navigation sounds (manual, optional)
        └── Video\          ← per-game videos
```

**AUTO** = installed by `rebuild --apply` from bundled package assets.
Only written when absent — existing user files are never overwritten.

> The same layout applies to `Most Played\` and `Recently Played\`.
