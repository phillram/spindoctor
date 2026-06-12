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
| `Favorites.mp4` | `Media\Main Menu\Video\` | Attract-mode video (background image + music, 57.7 s) |
| `Most Played.mp4` | `Media\Main Menu\Video\` | Attract-mode video (background image + music, 57.9 s) |
| `Recently Played.mp4` | `Media\Main Menu\Video\` | Attract-mode video (background image + music, 61.5 s) |
| `Favorites.zip` | `Media\Main Menu\Themes\` | Theme zip — required for HyperSpin to play the video |
| `Most Played.zip` | `Media\Main Menu\Themes\` | Theme zip — required for HyperSpin to play the video |
| `Recently Played.zip` | `Media\Main Menu\Themes\` | Theme zip — required for HyperSpin to play the video |
| `navigate.mp3` | `Media\Favorites\Sound\` | Sound played on every left/right cursor move inside the Favorites wheel |
| `navigate.mp3` | `Media\Most Played\Sound\` | Sound played on every left/right cursor move inside the Most Played wheel |
| `navigate.mp3` | `Media\Recently Played\Sound\` | Sound played on every left/right cursor move inside the Recently Played wheel |
| `<System>.ini` | `HyperSpin\Settings\` | Lets HyperSpin open the sub-wheel |

**Install condition:** every asset is only written when the destination is absent —
SpinDoctor never overwrites a file you placed there yourself.

The rebuild summary reports each asset:
```
Wheel art:      installed → D:\Arcade\HyperSpin\Media\Main Menu\Images\Wheel\Favorites.png
Background:     installed → D:\Arcade\HyperSpin\Media\Main Menu\Images\Backgrounds\Favorites.png
Music:          no bundled asset
Video:          installed → D:\Arcade\HyperSpin\Media\Main Menu\Video\Favorites.mp4
Theme zip:      installed → D:\Arcade\HyperSpin\Media\Main Menu\Themes\Favorites.zip
Navigate sound: installed → D:\Arcade\HyperSpin\Media\Favorites\Sound\navigate.mp3
```

---

## Attract-mode behaviour

HyperSpin's attract mode (when the cabinet is idle) cycles through every system in
`Main Menu.xml`.  For each system it shows:

1. The **wheel logo** (`Images\Wheel\<System>.png`) — always shown
2. The **background image** (`Images\Backgrounds\<System>.png`) — shown behind the logo
3. The **video** (`Video\<System>.mp4`) + **theme zip** (`Themes\<System>.zip`) —
   the theme zip is required for HyperSpin to play the video; the video's visual
   is hidden (1×1 px) so only its audio track plays and the background PNG shows
4. The **active-browsing music** (`Sound\<System>.mp3`) — plays while the user
   is *scrolling* the main-menu wheel (not during attract idle). SpinDoctor does
   **not** bundle MP3 files — this slot plays silence during active browsing.

The three synthetic wheels are part of this rotation.  Items 1, 2, and 3 are
bundled and installed automatically.  Item 4 is intentionally silent.

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

**Required video format (HyperSpin / Windows 7 compatibility):**

HyperSpin is built on Adobe AIR, which uses the AIR runtime's H.264 decoder.
Windows 7 (without hardware-accelerated codec packs) and older DirectShow
filters only support H.264 up to **Main Profile, Level 4.0**.

| Property | Required value |
|----------|---------------|
| Container | MP4 |
| Video codec | H.264 (libx264) |
| Profile | **Main** (not High) |
| Level | **4.0** (not 5.0+) |
| Resolution | **1920×1080** (HyperSpin scales to fit; large resolutions force higher levels) |
| Pixel format | yuv420p |
| Audio codec | AAC |

> **Why not High Profile or 4K?**  The original 2752×1536 resolution forces H.264
> Level 5.0, which the Windows 7 Adobe AIR runtime cannot decode — the video
> track is silently dropped while audio still plays.  Encoding at 1920×1080 keeps
> the level at 4.0 and plays correctly on all tested HyperSpin setups.

**If you replace with your own video:** encode with the settings above.  An ffmpeg
one-liner that produces a compatible file:

```bat
ffmpeg -loop 1 -i background.png -stream_loop -1 -i music.mp3 -t 57.7 ^
  -vf scale=1920:1080 -c:v libx264 -profile:v main -level 4.0 -crf 28 ^
  -c:a aac -b:a 192k -pix_fmt yuv420p -movflags +faststart Favorites.mp4
```

**To replace with your own:** Drop your `.mp4` at the path above, then rebuild.
SpinDoctor detects the file exists and skips the install on every subsequent run.

---

### HyperSpin video / audio not playing — settings checklist

If attract-mode audio/video is not playing for a synthetic wheel, check:

**`HyperSpin\Settings\HyperSpin.ini` — `[Main Menu]` section:**
```ini
[Main Menu]
Use_Last_Playlist=false
```

**Theme zip must exist** — `Media\Main Menu\Themes\<System>.zip` is required.
Without it HyperSpin ignores the video entirely.  SpinDoctor installs this
automatically during `rebuild --apply` and `mainmenu add --apply`.

**Videos only play during attract mode** (when the cabinet is idle).
They do not play while you are actively browsing the main menu wheel.
The `Attract_Mode_Time` setting controls how long the cabinet must be idle
before attract mode starts; videos advance automatically when they end.

> **Note on active-browsing music** — HyperSpin can play a separate `.mp3`
> from `Media\Main Menu\Sound\<System>.mp3` while the user scrolls the wheel.
> SpinDoctor does not bundle these files, so active-browsing plays silence.
> To add browsing music, drop your own `.mp3` at that path manually.

---

### Attract-mode theme

A theme `.zip` contains `Theme.xml`, which tells HyperSpin where to render the video
slot for a system during attract mode.  **Without a theme zip HyperSpin silently skips
the attract-mode audio/video entirely**, even if the `.mp4` file exists and is
correctly encoded.

**File:** `Media\Main Menu\Themes\<SystemName>.zip`

**SpinDoctor installs this automatically** — `rebuild --apply` and `mainmenu add --apply`
both write the bundled theme zip for each synthetic wheel (skip-if-exists on rebuild,
always overwrite on `mainmenu add`).

The bundled `Theme.xml` matches the reference layout provided by the cabinet owner:

```xml
<video w="1024" h="768" x="512" y="384" forceaspect="both"
       time="0" delay="0" type="none" start="none" rest="none" .../>
```

Full-screen (1024×768), centred on HyperSpin's 1024×768 canvas, aspect ratio
preserved.  The zip contains **only `Theme.xml`** — no `Info.txt`, no SWF files.

#### Custom themes

If you want a more animated or elaborate theme, replace the installed zip with your own:

```
Media\Main Menu\Themes\Favorites.zip
Media\Main Menu\Themes\Most Played.zip
Media\Main Menu\Themes\Recently Played.zip
```

Copy the `.zip` file (do **not** extract it — HyperSpin reads the archive directly).
SpinDoctor's `rebuild --apply` will not overwrite a file that already exists.

**Community themes:** available on EmuMovies, HyperSpin forums, and Hyperspin-FE.com.
Look for a "Main Menu" theme pack.  If the community theme shows a full-size video
overlay, the background PNG is still shown underneath — both layers are visible.

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

**`navigate.mp3` is bundled** — SpinDoctor installs it automatically during
`rebuild --apply` (skip-if-exists).  The other navigation sounds (`select.mp3`,
`back.mp3`, `letter.mp3`) are not bundled; add them manually if wanted.

**Manually (non-navigate sounds):**
```bat
spindoctor media-add --system "Favorites" --game "select" --type sound --file "path\to\select.mp3" --apply
```

Or copy `.mp3` files directly to `Media\Favorites\Sound\` (or `Most Played`, etc.).

---

### Per-game theme fallback (`Default.zip`)

When a game has no per-game theme zip in the source system, HyperSpin falls back
to `Default.zip` in that system's Themes folder — a console-wide template that
provides the layout (background, video position, overlays) for all games without
their own theme.

**During a media mirror, SpinDoctor copies the source system's `Default.zip` as
`<GameName>.zip` in the synthetic wheel's Themes folder** whenever no per-game
theme exists.  This gives the game the same themed background and video layout
in Favorites / Recently Played / Most Played that it has in its native wheel.

Example — Kirby's Adventure has no `Kirby's Adventure.zip` in the NES Themes
folder.  SpinDoctor copies `Media\Nintendo Entertainment System\Themes\Default.zip`
to `Media\Favorites\Themes\Kirby's Adventure.zip` so HyperSpin renders it with
the NES console theme rather than a blank layout.

**Fallback only fires when:** `Default.zip` exists at
`Media\<SourceSystem>\Themes\Default.zip` and the game has no per-game theme.
Systems that already have per-game themes are unaffected.

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
        ├── Sound\                         ← active-browsing music (not bundled; plays silence)
        ├── Video\
        │   ├── Favorites.mp4              ← AUTO: attract-mode video + audio (57.7 s)
        │   ├── Most Played.mp4            ← AUTO: attract-mode video + audio (57.9 s)
        │   ├── Recently Played.mp4        ← AUTO: attract-mode video + audio (61.5 s)
        │   └── ...
        └── Themes\
            ├── Favorites.zip              ← AUTO: attract-mode theme (Theme.xml — 1×1 video, top-left)
            ├── Most Played.zip            ← AUTO: attract-mode theme
            ├── Recently Played.zip        ← AUTO: attract-mode theme
            └── ...

    └── Favorites\                         ← per-game media (auto-mirrored from source systems)
        ├── Images\
        │   ├── Wheel\       ← per-game logos
        │   ├── Backgrounds\ ← per-game backgrounds
        │   ├── Artwork1\    ← per-game art (slot 1)
        │   ├── Artwork2\    ← per-game art (slot 2)
        │   ├── Artwork3\    ← per-game art (slot 3)
        │   ├── Titles\      ← title-screen captures (shown in theme side-panels)
        │   └── Letters\     ← alphabetic scroll-bar letter art
        ├── Themes\          ← per-game themes (mirrored; Default.zip fallback applied)
        ├── Sound\
        │   └── navigate.mp3 ← AUTO: cursor-move click sound
        └── Video\           ← per-game videos (.mp4 .wmv .mpeg .mpg .flv .avi .mkv …)
            └── Trailers\    ← per-game trailers
```

**AUTO** = installed by `rebuild --apply` from bundled package assets.
Only written when absent — existing user files are never overwritten.

> The same layout applies to `Most Played\` and `Recently Played\`.
