---
name: lwax-animation
description: Build and sign a new LedBlinky .lwax animation file for this cabinet's LED buttons. Use whenever asked to create, adjust, or troubleshoot a LED animation/fade/pattern for the arcade cabinet's PAC-LED64 boards, or when a .lwax file fails to load with a "Missing Signature" error.
---

# LedBlinky .lwax animation workflow

Full background/investigation: `docs/cabinet-architecture-reference.md` → **"LEDBlinky Animation Files (.lwax)"**. Read that section before doing anything non-routine here — it has the confirmed file format, the hardware channel map, and every gotcha discovered so far. This skill is the short version for routine "make me a new pattern" requests.

## The one hard rule

**Never hand-author or hand-edit `.lwax` XML directly and expect it to load in LedBlinky.** LedBlinky Config validates a per-file signature that cannot be reproduced outside its own `LEDBlinkyAnimationEditor.exe` — every attempt to reverse it (SHA-1/256/384/512/MD5/RIPEMD-160, many canonicalizations) failed. There is a two-step workflow that reliably works; don't skip step 2.

## Step 1 — generate the raw (unsigned) file

Use `spindoctor ledblinky lwax fade` (in `spindoctor/lwax.py` + the `ledblinky lwax` CLI group in `spindoctor/cli.py`). It reads the cabinet's real board/port layout from `<ledblinky_dir>\LEDBlinkyInputMap.xml`, so it's correct for any controller count/type without hardcoding.

```bat
spindoctor ledblinky lwax fade --color FF0000 --color 00FF00 --color 0000FF
:: dry-run: shows detected controllers, control count, frame count -- writes nothing

spindoctor ledblinky lwax fade --color FF0000 --color 00FF00 --color 0000FF --apply
:: writes <output_dir>/LEDBlinky/lwax/fade.lwax

spindoctor ledblinky lwax fade --color FF0000 --color 0000FF --labels P1B1,P1B2,P1B3 --name red_blue_fade --apply
:: only fades specific controls, custom output name
```

Key options:
- `--color RRGGBB` (repeatable, ≥2 required) — colors cycle in the order given and loop back to the first.
- `--labels a,b,c` — restrict to specific control labels (see `LEDBlinkyInputMap.xml` for the exact label spelling per board; defaults to every wired control).
- `--steps-per-leg N` (default 48) and `--duration-ms N` (default 40) — tune fade smoothness/speed. Total per-leg time ≈ `steps-per-leg * duration-ms` ms. Lower `steps-per-leg` = choppier/faster; higher `duration-ms` = slower overall.
- `--output PATH` — write to an exact path instead of the default `output_dir` location.

The CLI only builds a **uniform color-cycle fade** across the chosen controls. For anything spatial (sweeps, chases, radial pulses, rain), don't extend the CLI — the column/row/ring groupings needed are cabinet-specific data, not general-purpose flags, and a one-off script is faster than designing flag syntax for it. This matches explicit user feedback: CLI flags felt like *more* work than the Animation Editor's built-in wizard for a single simple fade; the CLI only pays for itself on effects that are tedious to hand-build frame-by-frame in the editor (spatial/randomized ones). Use the Python API directly:

- `LwaxAnimation.add_frame(duration_ms, {label: (r, g, b), ...})` — fully generic per-frame, per-control primitive. Everything else is built on this.
- `build_color_cycle(controllers, colors, steps_per_leg, duration_ms, labels)` — uniform fade through N colors (what the CLI wraps).
- `build_wave(controllers, groups, lead_color, trail_color=None, lag=1, frames_per_step, duration_ms)` — moves a leading color (plus an optional trailing second color `lag` groups behind) across an ordered list of label-groups, wrapping continuously. `groups[i]` is "whatever occupies position i" — reuse this same function for left/right sweeps, up/down sweeps, radial pulses, a Cylon-style scanner (double the group list as `groups + groups[-2:0:-1]` to ping-pong instead of wrap), a "cyclone"/racetrack loop (concatenate two parallel rows, one forward + one reversed), and a "chase the leader" rivalry effect (large `lag`, e.g. half the loop length, so the two colors stay a fixed distance apart forever instead of one closely trailing the other).
- `build_rain(controllers, drop_groups, colors, frames_per_step, total_frames, min_gap_frames, max_gap_frames, seed)` — independent, randomly-timed drop sequences per group (each lights its labels in order, e.g. top-then-bottom), so multiple columns flash out of sync. Deterministic given `seed` — regenerating with "make it slower" just means changing one parameter, output is otherwise identical. Passing one-label-per-group (instead of multi-row columns) turns this into a confetti/twinkle effect instead of rain.
- `build_rainbow_scroll(controllers, groups, total_frames, cycles, duration_ms, saturation, value)` — a continuous hue gradient across `groups`, scrolling over time (uses `colorsys.hsv_to_rgb`), instead of one solid color sweeping.
- `build_fill(controllers, groups, fill_color, flash_color, frames_per_step, hold_frames, flash_cycles, flash_frames)` — accumulating fill (each group joins and *stays* lit, unlike `build_wave`), holds full, flashes, then the whole file loops back to empty and refills.
- `build_drain(controllers, groups, fill_color, flash_color, frames_per_step, hold_full_frames, hold_empty_frames, flash_cycles, flash_frames)` — the inverse of `build_fill`: starts fully lit, extinguishes groups one at a time (a countdown/fuse-burning-down effect), holds empty, flashes an alert color, loops back to full.
- `build_alternate(controllers, group_a, group_b, color_a, color_b, hold_ms, cycles)` — no motion at all, just two groups swapping colors in lockstep (a checkerboard blink).
- `merge_animations(animation, *others)` — layers multiple frame-synchronized animations into one (later non-off colors win per label). Use for independent effects meant to play at once, e.g. two `build_wave` calls racing outward from a shared center in different colors.

### This cabinet's layout groups

Getting this right from a text description alone is genuinely hard. Three attempts, in order of how well each worked:

1. **An ASCII table** — needed two rounds of correction against a rendered visual preview before it was even close. Don't trust an ASCII table's column alignment *across different rows* as meaningful — cross-row alignment in a markdown table is usually accidental spacing from typing it out, not a claim about physical position (confirmed here: admin-row cells lined up in the same text-column as button-row cells several rows below that aren't actually above them).
2. **A rendered HTML diagram, confirmed against the ASCII table** — better, but still wrong, because it was only as good as the (flawed) text description underneath it. Two rounds of "no, that's not right" on Start/Coin placement.
3. **An actual photo of the panel** — got it right in one shot. Where a photo is available, prefer parsing it directly over any text/table description, even one that's already been through a visual-preview round.

**Whenever a photo is available, ask for it first, rather than starting from a text/table description at all.** If only text is available, still render a visual diagram and get it confirmed before generating more than one or two files against it — a ring/perimeter-derived effect in particular means one wrong position skews everything built on top of it.

**Confirmed layout (from the panel photo):**

- P1 Start sits directly above P1's joystick; P1 Coin sits directly above P1 Button 1.
- P2 Start sits above P2 Button 2; P2 Coin sits above P2 Button 3 — **not mirrored** to P1's pattern (P1 uses joystick+B1, P2 uses B2+B3). Both sides read Start-then-Coin left to right; neither side is Coin-then-Start.
- The trackball sits in the same row as the joysticks and action buttons — not the admin row above it — in the column between `SELECT` and `EXIT`.
- Left Click/Right Click sit next to `SELECT`, not next to the trackball.
- The admin row (`LMOUSE`/`RMOUSE`/`SELECT`/`EXIT`/`SEARCH`/`PAUSE`) is evenly spaced with no real gap — the empty column between `SELECT` and `EXIT` in any rendering that shares one grid across all tiers is just where the trackball happens to align from the row below, not a real gap in the admin row itself.

> **Bug fixed after real-hardware testing**: `LEFT_RIGHT_ORDER` originally only spanned the admin/start-coin/top-row tier — it never included the bottom row (`P1B5-8`/`P2B5-8`) at all, so any effect built from it (or from `RADIAL_RINGS`, which derives from it: sweeps left/right, both radial pulses, the breathing pulse, the P1-vs-P2 race, the rainbow scroll, the combo-meter fill, the countdown/fuse) silently skipped 8 of the 27 controls. Confirmed on the cabinet via `pulse_outward_from_trackball_toxic.lwax` never lighting Buttons 5-8. Fixed by folding each bottom-row button into its top-row column-mate's group below — `ROWS`/`CYCLONE_LOOP`/`RAIN_DROP_GROUPS` were never affected (they already included the bottom row through a different path) and didn't need touching. Ring/column *spacing* (how many steps the admin row takes vs. how soon player buttons appear) was checked against real hardware too and confirmed correct as index-based — not compressed to account for the admin row's tighter physical spacing.

> **Deliberate stylistic override, not a physical-position claim**: `P1START` is physically its own column (above P1's joystick — see the confirmed layout above), but by user request it's grouped with `P1COIN`/`P1B1`/`P1B5` below anyway so it never fires as an isolated single-control blip in animations built from this list. This is the one place `LEFT_RIGHT_ORDER` deliberately diverges from the [Physical button layout](../../../docs/cabinet-architecture-reference.md#physical-button-layout) table — that table still (correctly) shows P1START one column over. Don't "fix" this back to match the physical table without checking with the user first. Side effect (welcome, not incidental): this also makes `RADIAL_RINGS` come out perfectly symmetric — 7 groups on each side of the trackball instead of the previous 8-vs-7 split.

```python
# Left-to-right column order, as ordered GROUPS (a position can hold more
# than one label when two controls are lit at the same physical spot --
# e.g. P1 Coin and P1's bottom-row counterpart both share P1B1's position).
# P1START is folded into that same first group by deliberate request even
# though it's physically one column over (see the callout above) -- don't
# revert this to match the physical table without checking first.
# Single source of truth: ROWS, RADIAL_RINGS, and CYCLONE_LOOP below are all
# derived from this instead of hand-listed, so a future correction only has
# to happen in one place.
LEFT_RIGHT_ORDER = [
    ["P1START", "P1COIN", "P1B1", "P1B5"], # P1START pulled in from its own column by request
    ["P1B2", "P1B6"],
    ["P1B3", "P1B7"],
    ["P1B4", "P1B8"],
    ["LMOUSE"], ["RMOUSE"], ["SELECT"],
    ["TRACKBALL"],
    ["EXIT"], ["SEARCH"], ["PAUSE"],
    ["P2B1", "P2B5"],
    ["P2B2", "P2START", "P2B6"],           # P2START above P2B2 (not mirrored to P1)
    ["P2B3", "P2COIN", "P2B7"],            # P2COIN above P2B3
    ["P2B4", "P2B8"],
]

# 3 vertical bands -- this cabinet's button grid only has 2 rows per player,
# so a real up/down sweep only ever has 3 meaningfully distinct steps.
ROW_ABOVE = ["P1START", "P1COIN", "LMOUSE", "RMOUSE", "SELECT", "EXIT", "SEARCH", "PAUSE", "P2COIN", "P2START"]
ROW_TOP = ["P1B1", "P1B2", "P1B3", "P1B4", "TRACKBALL", "P2B1", "P2B2", "P2B3", "P2B4"]
ROW_BOTTOM = ["P1B5", "P1B6", "P1B7", "P1B8", "P2B5", "P2B6", "P2B7", "P2B8"]
ROWS = [ROW_ABOVE, ROW_TOP, ROW_BOTTOM]

# Symmetric distance-from-trackball rings, derived from LEFT_RIGHT_ORDER --
# don't hand-list these, they're easy to get subtly wrong by inspection.
# The group list is exactly 7 groups either side of the trackball (folding
# P1START into P1COIN/P1B1/P1B5 above made both sides even -- it used to be
# 8 vs. 7 before that merge).
TRACKBALL_INDEX = next(i for i, g in enumerate(LEFT_RIGHT_ORDER) if "TRACKBALL" in g)
_ring_map = {}
for i, group in enumerate(LEFT_RIGHT_ORDER):
    _ring_map.setdefault(abs(i - TRACKBALL_INDEX), []).extend(group)
RADIAL_RINGS = [_ring_map[d] for d in sorted(_ring_map)]

# Racetrack loop for a "cyclone"/spinning effect: across the top row, then
# back across the bottom row. Reverse the whole list for the other direction.
CYCLONE_LOOP = [[l] for l in ROW_TOP] + [[l] for l in ROW_BOTTOM[::-1]]

# Rain/confetti drop groups: top-to-bottom per 2-row column, plus a
# degenerate 1-element "drop" for every single-row control so the whole
# panel participates, not just the two player button grids.
RAIN_DROP_GROUPS = [
    ["P1B1", "P1B5"], ["P1B2", "P1B6"], ["P1B3", "P1B7"], ["P1B4", "P1B8"],
    ["P2B1", "P2B5"], ["P2B2", "P2B6"], ["P2B3", "P2B7"], ["P2B4", "P2B8"],
    ["TRACKBALL"], ["LMOUSE"], ["RMOUSE"], ["P1COIN"], ["P1START"],
    ["SELECT"], ["EXIT"], ["SEARCH"], ["PAUSE"], ["P2COIN"], ["P2START"],
]
```

`build_rainbow_scroll()` also takes grouped positions (not a flat label list), for the same reason — two labels sharing a spot should get the identical hue, not two neighboring-but-different ones.

Two side effects of the grouped model worth knowing about: (1) when two independent effects need to run on either side of an uneven split (e.g. `p1_vs_p2_race`, where P1's side has 8 groups and P2's has 7), cross the `frames_per_step` values (`len(other_side)`) so both `build_wave` calls land on the exact same total frame count before `merge_animations()` — no padding needed. (2) `build_fill`/`build_wave` naturally light co-grouped labels together, which is correct for a spot two controls share.

A worked example generating 16 effects (4 directional sweeps, rainfall, radial pulse in/out, a ping-pong "breathing" pulse, confetti, a two-color race from center, a rainbow scroll, a Cylon scanner, cyclone loops both directions, an accumulating combo-meter fill, and a heartbeat brightness pulse) lives in this session's history — recreate similarly: parse the real `LEDBlinkyInputMap.xml`, derive groups from `LEFT_RIGHT_ORDER` as above, call the relevant `build_*` function(s), validate with `xml.etree.ElementTree.fromstring()` before handing files over.

### Batch generator + file-naming rule

`scripts/generate_lwax_patterns.py` is the maintained batch generator: 22 effect families × 5 variants (fade, sweep, rain/confetti, scroll, fill, drain, checker, radial, cyclone, race, heartbeat, strobe, marquee, bounce, rowblink, ripple, spiral, comet, lavalamp, twinkle, candle, gradient), each family with one moving/fading rainbow variant, every fixed-colour variant a globally-unique hue (hue-strided palette), spread over slow/medium/fast — plus a `breathe_*` solid-colour library (standard, `vivid_*`, `pastel_*`, `breathe_rainbow`) and two colour-cycle files (`breathe_cycle`, `pulse_cycle`) that step through several unique solids and loop. The library builders in `spindoctor/lwax.py` cover the base effects; the script adds local helpers (`build_heartbeat`, `build_strobe`, `build_marquee`, `build_bounce`, `build_race_from_center`, `build_ripple`, `build_spiral`, `build_comet`, `build_plasma`, `build_twinkle`, `build_candle`, `build_gradient_breathe`, `build_breathe_cycle`, `build_pulse_cycle`, `build_rainbow_*`) for the rest. Geometry-aware effects use `LABEL_POS`, an approximate 2D position map (x = column index, y = row band) derived from the layout groups. It regenerates the whole batch each run (clearing stale `.lwax` first), parsing `~/Downloads/LEDBlinkyInputMap.xml` if present, else the committed reference copy at `docs/reference/LEDBlinkyInputMap.xml`, and writes to `~/Downloads/spindoctor-lwax-patterns/` with a `README.txt` index.

**File-naming rule (applies to every generated `.lwax`):** plain, readable, lower-case words joined by single underscores — `family_color_speed.lwax`, e.g. `fade_red_lime_slow.lwax`, `scroll_right_medium.lwax`, `checker_rainbow_medium.lwax`. **Never** use spaces, em dashes (`—`), en dashes (`–`), or runs of hyphens (`---`) in a file name. The generator's `slugify()` enforces this by collapsing every non-alphanumeric run to one underscore; keep it that way.

## Step 2 — sign it (manual, on the cabinet, every time)

The generated file **will not load** until this happens:

1. Copy the file to the cabinet if not already there.
2. Open `LEDBlinkyAnimationEditor.exe` (`<ledblinky_dir>\Plugins\LEDBlinky\LEDBlinkyAnimationEditor.exe` — already installed, no download needed).
3. **Animation → Open**, select the generated file.
4. **Animation → Save As**, same filename, no edits. This is the step that signs it and rewrites the placeholder `Device="PACLED64" Id="0"` attributes to the real `LedHwType=<code> Id=<real id>` pairing.
5. Copy the signed output into `<ledblinky_dir>\lwa\`.
6. Assign it via `spindoctor ledblinky patch-settings --fe-lwa "<name>.lwax" --apply` (or `--ss-lwa`, or by hand in LedBlinky Config) and test through the real HyperSpin frontend — **not** the Animation Editor's own "Run LED Animation" preview, which is known to flash/stutter unreliably on this cabinet even when the real playback path is smooth.

Do not attempt to automate step 2 with GUI scripting (AutoHotkey etc.) unless explicitly asked — it was considered and deliberately skipped as not worth the fragility for a 10-second manual step.

## Known gotcha: `LightFEControls=1`

If the resulting animation looks right except some buttons stay a static color (commonly white) while browsing HyperSpin: that's `Settings.ini`'s `[FEOptions] LightFEControls=1` (UI label: **"Light HyperSpin Controls"**) overriding HyperSpin's active-navigation buttons with a fixed color, by design — not a bug in the generated file. It's an either/or: fixed "this button is usable" color on those specific controls (`=1`, customizable via LedBlinky Config's Controls Editor FE edit mode, not stuck at white) or full-panel synced animation with no exceptions (`=0`). Confirmed fix already applied on this cabinet: `LightFEControls=0`.

## Tests

`tests/test_lwax.py` covers the parser, the generic builder, and all presets (`build_color_cycle`, `build_wave`, `build_rain`, `build_rainbow_scroll`, `build_fill`, `build_drain`, `build_alternate`, `merge_animations`) against a small synthetic `LEDBlinkyInputMap.xml`. Run `python3 -m pytest tests/test_lwax.py -q` after touching `spindoctor/lwax.py`.
