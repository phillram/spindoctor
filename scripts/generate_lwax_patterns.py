#!/usr/bin/env python3
"""Generate a fresh, colour-diverse batch of LEDBlinky ``.lwax`` animations.

One-off generator (per the ``lwax-animation`` skill's "spatial effects are
one-off scripts" guidance). It imports the builders from ``spindoctor.lwax`` and
this cabinet's real layout groups, then emits ~35 raw *unsigned* ``.lwax`` files
into ``~/Downloads/spindoctor-lwax-patterns/``.

Design goals (from Phill):
- 7 effect families x 5 variants = 35 files.
- Exactly one "moving fading rainbow" variant per family.
- The 4 fixed-colour variants per family draw from a single global palette with
  **no colour reused anywhere in the batch** -- every button value differs from
  file to file.
- Each family spreads over slow / medium / fast timing.

These files still need signing on the cabinet (open in
LEDBlinkyAnimationEditor.exe -> Save As) before LedBlinky Config will manage
them; runtime playback via Settings.ini does not check the signature.
"""
from __future__ import annotations

import colorsys
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from spindoctor.lwax import (  # noqa: E402
    LwaxAnimation,
    build_color_cycle,
    build_fill,
    build_drain,
    build_rain,
    build_rainbow_scroll,
    build_wave,
    parse_input_map,
)

# --------------------------------------------------------------------------- #
# This cabinet's layout groups -- copied verbatim from
# .claude/skills/lwax-animation/SKILL.md (single source of truth).
# --------------------------------------------------------------------------- #
LEFT_RIGHT_ORDER = [
    ["P1START", "P1COIN", "P1B1", "P1B5"],
    ["P1B2", "P1B6"],
    ["P1B3", "P1B7"],
    ["P1B4", "P1B8"],
    ["LMOUSE"], ["RMOUSE"], ["SELECT"],
    ["TRACKBALL"],
    ["EXIT"], ["SEARCH"], ["PAUSE"],
    ["P2B1", "P2B5"],
    ["P2B2", "P2START", "P2B6"],
    ["P2B3", "P2COIN", "P2B7"],
    ["P2B4", "P2B8"],
]

ROW_ABOVE = ["P1START", "P1COIN", "LMOUSE", "RMOUSE", "SELECT", "EXIT", "SEARCH", "PAUSE", "P2COIN", "P2START"]
ROW_TOP = ["P1B1", "P1B2", "P1B3", "P1B4", "TRACKBALL", "P2B1", "P2B2", "P2B3", "P2B4"]
ROW_BOTTOM = ["P1B5", "P1B6", "P1B7", "P1B8", "P2B5", "P2B6", "P2B7", "P2B8"]
ROWS = [ROW_ABOVE, ROW_TOP, ROW_BOTTOM]

TRACKBALL_INDEX = next(i for i, g in enumerate(LEFT_RIGHT_ORDER) if "TRACKBALL" in g)
_ring_map: dict[int, list[str]] = {}
for _i, _group in enumerate(LEFT_RIGHT_ORDER):
    _ring_map.setdefault(abs(_i - TRACKBALL_INDEX), []).extend(_group)
RADIAL_RINGS = [_ring_map[d] for d in sorted(_ring_map)]

CYCLONE_LOOP = [[l] for l in ROW_TOP] + [[l] for l in ROW_BOTTOM[::-1]]

RAIN_DROP_GROUPS = [
    ["P1B1", "P1B5"], ["P1B2", "P1B6"], ["P1B3", "P1B7"], ["P1B4", "P1B8"],
    ["P2B1", "P2B5"], ["P2B2", "P2B6"], ["P2B3", "P2B7"], ["P2B4", "P2B8"],
    ["TRACKBALL"], ["LMOUSE"], ["RMOUSE"], ["P1COIN"], ["P1START"],
    ["SELECT"], ["EXIT"], ["SEARCH"], ["PAUSE"], ["P2COIN"], ["P2START"],
]

# Checkerboard: split the left-to-right columns by parity.
CHECKER_A = [l for i, g in enumerate(LEFT_RIGHT_ORDER) if i % 2 == 0 for l in g]
CHECKER_B = [l for i, g in enumerate(LEFT_RIGHT_ORDER) if i % 2 == 1 for l in g]

# --------------------------------------------------------------------------- #
# Colour helpers.
# --------------------------------------------------------------------------- #
Color = tuple

def hsv48(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (round(r * 48), round(g * 48), round(b * 48))

def dim(color, factor: float):
    return tuple(round(c * factor) for c in color)

def lighten(color, factor: float):
    return tuple(min(48, round(c + (48 - c) * factor)) for c in color)

# A full-spectrum rainbow used by the rainbow fade + rainbow rain variants.
SPECTRUM = [hsv48(i / 12, 1.0, 1.0) for i in range(12)]

_HUE_NAMES = [
    "red", "orange", "amber", "yellow", "lime", "green",
    "spring", "aqua", "cyan", "azure", "blue", "indigo",
    "violet", "magenta", "rose", "crimson",
]

def _hue_name(h: float) -> str:
    return _HUE_NAMES[int((h % 1.0) * len(_HUE_NAMES)) % len(_HUE_NAMES)]

_SHADES = [
    (1.00, 1.00, "vivid"),
    (1.00, 0.72, "deep"),
    (0.55, 1.00, "soft"),
    (0.85, 0.58, "dark"),
]

def _build_master_palette(n: int = 48):
    """A globally unique, well-spread palette of vivid distinct colours.

    Walks the hue wheel and rotates through four shade profiles so neighbours
    differ in both hue and lightness. Returns ``[(shade, hue, (r,g,b)), ...]``
    where ``shade``/``hue`` are plain lower-case words (e.g. "vivid", "red") --
    the hue word is what ends up in the file name, the shade adds detail in the
    README only.
    """
    palette = []
    for i in range(n):
        h = i / n
        s, v, shade = _SHADES[i % len(_SHADES)]
        palette.append((shade, _hue_name(h), hsv48(h, s, v)))
    return palette

def _stride(entries, step: int):
    """Reorder so sequential consumption hops far around the hue wheel each
    time -- gives every family a diverse, contrasting spread of hues instead of
    a run of near-neighbours. ``step`` must be coprime with ``len(entries)`` so
    the result is a full permutation (48 & 13 are coprime)."""
    n = len(entries)
    return [entries[(i * step) % n] for i in range(n)]

MASTER_PALETTE = _stride(_build_master_palette(48), 13)


class Palette:
    """Hands out colours from MASTER_PALETTE with no repeats across the batch."""

    def __init__(self, entries):
        self._entries = list(entries)
        self._i = 0

    def take(self):
        if self._i >= len(self._entries):
            raise RuntimeError("Ran out of unique palette colours; enlarge MASTER_PALETTE.")
        entry = self._entries[self._i]
        self._i += 1
        return entry  # (shade, hue, color)

    def take_n(self, k: int):
        return [self.take() for _ in range(k)]

    @property
    def used(self) -> int:
        return self._i


# --------------------------------------------------------------------------- #
# Speed tiers.
# --------------------------------------------------------------------------- #
FADE_SPEED = {"slow": (64, 45), "medium": (48, 40), "fast": (24, 30)}          # steps_per_leg, duration_ms
WAVE_SPEED = {"slow": (10, 45), "medium": (6, 40), "fast": (3, 30)}            # frames_per_step, duration_ms
BAR_SPEED = {"slow": (7, 45), "medium": (4, 40), "fast": (2, 30)}             # frames_per_step, duration_ms (fill/drain)
RAIN_SPEED = {                                                                 # fps, dur, min_gap, max_gap, total
    "slow": (8, 45, 20, 90, 700),
    "medium": (5, 40, 10, 60, 600),
    "fast": (3, 30, 6, 36, 500),
}
SCROLL_SPEED = {                                                               # total_frames, cycles, duration_ms
    "slow": (160, 1, 45),
    "medium": (96, 1, 40),
    "fast": (60, 2, 30),
}
CHECKER_SPEED = {"slow": 600, "medium": 400, "fast": 200}                      # hold_ms

# Speed assigned to the 5 variants of each family (index 4 = the rainbow one).
# Guarantees at least one slow, one medium and one fast per family.
VARIANT_SPEEDS = ["slow", "medium", "fast", "slow", "medium"]


# --------------------------------------------------------------------------- #
# Local "moving fading rainbow" builders (family rainbow variants for effects
# whose library builder only takes a single fixed colour). Same HSV->0-48
# technique as build_rainbow_scroll; built on the generic add_frame primitive.
# --------------------------------------------------------------------------- #
def build_rainbow_comet(controllers, groups, frames_per_step=6, duration_ms=40, trail=3):
    """A single bright front that shifts hue as it travels the loop, dragging a
    fading multi-hue tail behind it -- a glowing rainbow comet."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    for pos in range(n):
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for t in range(trail + 1):
                p = (pos - t) % n
                bright = 1.0 - (t / (trail + 1)) * 0.85
                col = hsv48(p / n, 1.0, bright)
                for l in groups[p]:
                    colors[l] = col
            anim.add_frame(duration_ms, colors)
    return anim

def build_rainbow_fill(controllers, groups, frames_per_step=4, duration_ms=40, hold_frames=40):
    """Accumulating bar where each group joins at its own hue, so the panel fills
    into a full rainbow gradient, then the gradient scrolls (glows) once and the
    file loops back to empty."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    lit: list[int] = []
    for idx in range(n):
        lit.append(idx)
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for j in lit:
                col = hsv48(j / n, 1.0, 1.0)
                for l in groups[j]:
                    colors[l] = col
            anim.add_frame(duration_ms, colors)
    for f in range(hold_frames):
        phase = f / max(1, hold_frames)
        colors = {}
        for j in range(n):
            col = hsv48(j / n + phase, 1.0, 1.0)
            for l in groups[j]:
                colors[l] = col
        anim.add_frame(duration_ms, colors)
    return anim

def build_rainbow_drain(controllers, groups, frames_per_step=4, duration_ms=40, hold_full_frames=25, hold_empty_frames=10):
    """Starts as a full rainbow gradient, then extinguishes groups one at a time
    -- a rainbow countdown -- holds empty, and loops back to full."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)

    def full_frame(phase=0.0):
        colors = {}
        for j in range(n):
            col = hsv48(j / n + phase, 1.0, 1.0)
            for l in groups[j]:
                colors[l] = col
        return colors

    for f in range(hold_full_frames):
        anim.add_frame(duration_ms, full_frame(f / max(1, hold_full_frames) * 0.5))

    remaining = list(range(n))
    for gi in range(n):
        remaining.remove(gi)
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for j in remaining:
                col = hsv48(j / n, 1.0, 1.0)
                for l in groups[j]:
                    colors[l] = col
            anim.add_frame(duration_ms, colors)

    for _ in range(hold_empty_frames):
        anim.add_frame(duration_ms, {l: off for l in all_labels})
    return anim

def build_rainbow_checker(controllers, group_a, group_b, hold_ms=400, cycles=16):
    """Two interleaved halves swapping in lockstep, with both hues advancing
    around the wheel every cycle -- a glowing rainbow checkerboard."""
    anim = LwaxAnimation(controllers)
    for c in range(cycles):
        hue_a = c / cycles
        hue_b = hue_a + 0.5
        col_a = hsv48(hue_a, 1.0, 1.0)
        col_b = hsv48(hue_b, 1.0, 1.0)
        anim.add_frame(hold_ms, {**{l: col_a for l in group_a}, **{l: col_b for l in group_b}})
        anim.add_frame(hold_ms, {**{l: col_b for l in group_a}, **{l: col_a for l in group_b}})
    return anim


# --------------------------------------------------------------------------- #
# Build the batch.
# --------------------------------------------------------------------------- #
# File-name rule: plain, readable, lower-case words joined by single
# underscores -- e.g. ``fade_red_lime_slow.lwax``. Never use spaces, em dashes
# (--), en dashes, or runs of hyphens in a file name. ``slugify`` enforces this
# by collapsing every non-alphanumeric run to a single underscore.
def slugify(text: str) -> str:
    out: list[str] = []
    prev_us = False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def main() -> int:
    # Prefer a fresh export dropped in ~/Downloads; otherwise use the reference
    # copy committed to the repo so this runs without re-uploading the map.
    downloads_map = Path.home() / "Downloads" / "LEDBlinkyInputMap.xml"
    repo_map = REPO_ROOT / "docs" / "reference" / "LEDBlinkyInputMap.xml"
    input_map = downloads_map if downloads_map.exists() else repo_map
    if not input_map.exists():
        print(f"ERROR: no LEDBlinkyInputMap.xml found at {downloads_map} or "
              f"{repo_map}.", file=sys.stderr)
        return 1
    print(f"Using input map: {input_map}")
    controllers = parse_input_map(input_map)

    out_dir = Path.home() / "Downloads" / "spindoctor-lwax-patterns"
    out_dir.mkdir(parents=True, exist_ok=True)

    pal = Palette(MASTER_PALETTE)
    # (family, filename, animation, human description)
    batch: list[tuple[str, str, LwaxAnimation, str]] = []
    used_names: set[str] = set()

    def add(family, color_slug, speed, animation, colorway, effect):
        """Queue a file named ``family_color_speed.lwax`` (underscores only)."""
        base = slugify(f"{family}_{color_slug}_{speed}")
        name = base
        n = 2
        while name in used_names:
            name = f"{base}_{n}"
            n += 1
        used_names.add(name)
        batch.append((family, f"{name}.lwax", animation, f"{effect}; {colorway}; {speed}"))

    # 1. FADE -- whole-panel cross-fade between two unique colours.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        spl, dur = FADE_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        anim = build_color_cycle(controllers, [ca, cb], steps_per_leg=spl, duration_ms=dur)
        add("fade", f"{ha}_{hb}", speed, anim, f"{sa} {ha} and {sb} {hb}", "whole panel cross fade")
    anim = build_color_cycle(controllers, SPECTRUM, steps_per_leg=FADE_SPEED["medium"][0],
                             duration_ms=FADE_SPEED["medium"][1])
    add("fade", "rainbow", "medium", anim, "full spectrum", "whole panel rainbow fade")

    # 2. SWEEP / CHASE -- travelling fronts across the left-to-right order.
    s = VARIANT_SPEEDS[0]; fps, dur = WAVE_SPEED[s]
    (sh0, h0, c0) = pal.take()
    add("sweep", h0, s, build_wave(controllers, LEFT_RIGHT_ORDER, c0, trail_color=dim(c0, 0.30),
                                   frames_per_step=fps, duration_ms=dur), f"{sh0} {h0}", "left to right comet")
    s = VARIANT_SPEEDS[1]; fps, dur = WAVE_SPEED[s]
    (sh1, h1, c1) = pal.take()
    add("sweep", h1, s, build_wave(controllers, list(reversed(LEFT_RIGHT_ORDER)), c1, trail_color=dim(c1, 0.30),
                                   frames_per_step=fps, duration_ms=dur), f"{sh1} {h1}", "right to left comet")
    s = VARIANT_SPEEDS[2]; fps, dur = WAVE_SPEED[s]
    (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
    add("sweep", f"{ha}_{hb}", s, build_wave(controllers, LEFT_RIGHT_ORDER, ca, trail_color=cb,
                                             lag=len(LEFT_RIGHT_ORDER) // 2, frames_per_step=fps, duration_ms=dur),
        f"{sa} {ha} chasing {sb} {hb}", "two colour rivalry chase")
    s = VARIANT_SPEEDS[3]; fps, dur = WAVE_SPEED[s]
    (sh3, h3, c3) = pal.take()
    cylon = LEFT_RIGHT_ORDER + LEFT_RIGHT_ORDER[-2:0:-1]
    add("sweep", h3, s, build_wave(controllers, cylon, c3, trail_color=dim(c3, 0.30),
                                   frames_per_step=fps, duration_ms=dur), f"{sh3} {h3}", "cylon ping pong scanner")
    fps, dur = WAVE_SPEED["fast"]
    add("sweep", "rainbow", "fast", build_rainbow_comet(controllers, LEFT_RIGHT_ORDER, frames_per_step=fps,
                                                         duration_ms=dur), "full spectrum", "glowing rainbow comet")

    # 3. RAIN / CONFETTI -- randomly-timed drops.
    for i in range(3):
        speed = VARIANT_SPEEDS[i]
        fps, dur, mn, mx, tot = RAIN_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        anim = build_rain(controllers, RAIN_DROP_GROUPS, [ca, cb], frames_per_step=fps,
                          duration_ms=dur, total_frames=tot, min_gap_frames=mn, max_gap_frames=mx, seed=i)
        add("rain", f"{ha}_{hb}", speed, anim, f"{sa} {ha} and {sb} {hb}", "rain falling top to bottom")
    # confetti: one-label groups so it twinkles instead of streaking.
    speed = VARIANT_SPEEDS[3]
    fps, dur, mn, mx, tot = RAIN_SPEED[speed]
    (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
    confetti_groups = [[l] for g in RAIN_DROP_GROUPS for l in g]
    add("confetti", f"{ha}_{hb}", speed,
        build_rain(controllers, confetti_groups, [ca, cb], frames_per_step=fps, duration_ms=dur,
                   total_frames=tot, min_gap_frames=mn, max_gap_frames=mx, seed=42),
        f"{sa} {ha} and {sb} {hb}", "confetti twinkle")
    fps, dur, mn, mx, tot = RAIN_SPEED["medium"]
    add("rain", "rainbow", "medium",
        build_rain(controllers, RAIN_DROP_GROUPS, SPECTRUM, frames_per_step=fps, duration_ms=dur,
                   total_frames=tot, min_gap_frames=mn, max_gap_frames=mx, seed=7),
        "full spectrum", "rainbow rain")

    # 4. SCROLL -- the whole family is rainbow; vary speed / direction / tone.
    tf, cy, dur = SCROLL_SPEED["slow"]
    add("scroll", "right", "slow", build_rainbow_scroll(controllers, LEFT_RIGHT_ORDER, total_frames=tf,
                                                        cycles=cy, duration_ms=dur), "full spectrum",
        "hue gradient scrolling right")
    tf, cy, dur = SCROLL_SPEED["medium"]
    add("scroll", "right", "medium", build_rainbow_scroll(controllers, LEFT_RIGHT_ORDER, total_frames=tf,
                                                          cycles=cy, duration_ms=dur), "full spectrum",
        "hue gradient scrolling right")
    tf, cy, dur = SCROLL_SPEED["fast"]
    add("scroll", "right", "fast", build_rainbow_scroll(controllers, LEFT_RIGHT_ORDER, total_frames=tf,
                                                        cycles=cy, duration_ms=dur), "full spectrum",
        "hue gradient scrolling right, 2 cycles")
    tf, cy, dur = SCROLL_SPEED["medium"]
    add("scroll", "left", "medium", build_rainbow_scroll(controllers, list(reversed(LEFT_RIGHT_ORDER)),
                                                         total_frames=tf, cycles=cy, duration_ms=dur),
        "full spectrum", "hue gradient scrolling left")
    tf, cy, dur = SCROLL_SPEED["slow"]
    add("scroll", "radial", "slow", build_rainbow_scroll(controllers, RADIAL_RINGS, total_frames=tf, cycles=cy,
                                                         duration_ms=dur, saturation=0.8, value=1.0),
        "full spectrum pastel", "rainbow radiating from trackball")

    # 5. FILL (combo-meter) -- accumulating bar radiating from the trackball.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = BAR_SPEED[speed]
        (sh, h, ca) = pal.take()
        add("fill", h, speed, build_fill(controllers, RADIAL_RINGS, ca, flash_color=lighten(ca, 0.6),
                                         frames_per_step=fps, duration_ms=dur), f"{sh} {h}",
            "combo meter fill and flash")
    fps, dur = BAR_SPEED["fast"]
    add("fill", "rainbow", "fast", build_rainbow_fill(controllers, RADIAL_RINGS, frames_per_step=fps,
                                                      duration_ms=dur), "full spectrum",
        "rainbow gradient fill and glow")

    # 6. DRAIN (countdown / fuse) -- extinguish left-to-right.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = BAR_SPEED[speed]
        (sh, h, ca) = pal.take()
        add("drain", h, speed, build_drain(controllers, LEFT_RIGHT_ORDER, ca, flash_color=lighten(ca, 0.6),
                                           frames_per_step=fps, duration_ms=dur), f"{sh} {h}",
            "countdown drain and flash")
    fps, dur = BAR_SPEED["medium"]
    add("drain", "rainbow", "medium", build_rainbow_drain(controllers, LEFT_RIGHT_ORDER, frames_per_step=fps,
                                                          duration_ms=dur), "full spectrum",
        "rainbow countdown drain")

    # 7. CHECKERBOARD -- interleaved halves swapping in lockstep.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        hold = CHECKER_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        add("checker", f"{ha}_{hb}", speed, build_alternate_wrapper(controllers, CHECKER_A, CHECKER_B, ca, cb, hold),
            f"{sa} {ha} and {sb} {hb}", "checkerboard blink")
    add("checker", "rainbow", "medium", build_rainbow_checker(controllers, CHECKER_A, CHECKER_B,
                                                              hold_ms=CHECKER_SPEED["medium"]),
        "full spectrum", "rainbow checkerboard")

    # --- validate + write ---
    written = []
    for family, filename, animation, desc in batch:
        xml_text = animation.render()
        ET.fromstring(xml_text)  # raises if malformed
        (out_dir / filename).write_text(xml_text, encoding="utf-8", newline="")
        written.append((filename, len(animation.frames), desc))

    # --- README / index ---
    lines = [
        "SpinDoctor LEDBlinky pattern batch",
        "=" * 42,
        "",
        f"{len(written)} raw (UNSIGNED) .lwax animations for the cabinet's two",
        "PAC-LED64 boards. Every fixed-colour variant uses a colour that appears",
        "nowhere else in this batch; each family also has one moving/fading",
        "rainbow variant, and spreads over slow / medium / fast timing.",
        "",
        "TO USE ON THE CABINET (signing is required for LedBlinky Config):",
        "  1. Copy a .lwax to the cabinet.",
        "  2. Open it in LEDBlinkyAnimationEditor.exe (Plugins\\LEDBlinky\\).",
        "  3. Animation -> Save As, same name, no edits (this signs it).",
        "  4. Copy into <ledblinky_dir>\\lwa\\ and assign, e.g.:",
        "       spindoctor ledblinky patch-settings --fe-lwa \"<name>.lwax\" --apply",
        "  (Runtime playback via Settings.ini does NOT need signing; the signature",
        "   check only gates LedBlinky Config's own management UI.)",
        "",
        "Speed = frame duration (ms) x frames-per-step. slow/medium/fast below are",
        "this batch's tiers, not a LedBlinky setting.",
        "",
        "FILES",
        "-----",
    ]
    for filename, frames, desc in written:
        lines.append(f"  {filename:<44} {frames:>4} frames  {desc}")
    (out_dir / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(written)} .lwax files + README.txt to {out_dir}")
    print(f"Unique palette colours consumed: {pal.used} / {len(MASTER_PALETTE)}")
    return 0


# build_alternate lives in the library; wrap so the call site above reads the
# same as the local rainbow builders.
def build_alternate_wrapper(controllers, group_a, group_b, color_a, color_b, hold_ms):
    from spindoctor.lwax import build_alternate
    return build_alternate(controllers, group_a, group_b, color_a, color_b, hold_ms=hold_ms, cycles=8)


if __name__ == "__main__":
    raise SystemExit(main())
