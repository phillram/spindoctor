"""Smooth, multi-colour "cute" LEDBlinky animations: the ``cute_*`` set.

Twenty patterns (gumballs rolling round the panel, fairy lights, two koi in a
pond, a sunrise, ...). Every pattern is a function of loop phase with
whole-number cycles, so each file loops without a seam, and nothing hard-cuts:
lights fade or glide. Built on the generic :class:`~spindoctor.lwax.LwaxAnimation`
and used by :func:`spindoctor.lwax_patterns.generate_batch` and
``spindoctor ledblinky lwax cute``.

Each pattern takes a :class:`CuteTheme`, its colourway:

- ``p1`` is the main palette;
- ``p2`` / ``p3`` hold backgrounds or a second palette (each pattern's
  :class:`CutePattern` entry says what it reads from them);
- ``seed`` drives random placement.

:data:`CUTE_THEMES` holds 60 themes: each pattern's original design plus two
colourways, named as the files are (``cute_koi_pond``, ``cute_koi_moonlight``,
...). :func:`build_cute` turns a theme into an animation.

The set was first built by a PowerShell/C# script on the example cabinet. This
port keeps its frame counts, frame durations and arithmetic, and seeds a port
of .NET's ``System.Random`` (:class:`DotNetRandom`), so the 60 themes come out
byte for byte the same as those files (``tests/test_lwax_cute.py`` checks it).

The patterns place controls with :data:`PANEL_POS`, the example cabinet's
confirmed physical layout, not the index grid in ``lwax_patterns.LABEL_POS``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .lwax import LwaxAnimation, LwaxController

FloatColor = Tuple[float, float, float]
Frames = List[List[FloatColor]]

TAU = math.pi * 2

# --------------------------------------------------------------------------- #
# Panel coordinates: (column, tier) from the Physical button layout table in
# docs/cabinet-architecture-reference.md. Columns 1-17 left to right; tiers
# 0 admin, 1 coin/start, 2 top row (B1-B4 and the trackball), 3 bottom row
# (B5-B8). The trackball sits at 2.4, a little below the top-row buttons, as in
# the approved designs.
# --------------------------------------------------------------------------- #
PANEL_POS: Dict[str, Tuple[float, float]] = {
    "LMOUSE": (6.0, 0.0), "RMOUSE": (7.0, 0.0), "SELECT": (8.0, 0.0),
    "EXIT": (10.0, 0.0), "SEARCH": (11.0, 0.0), "PAUSE": (12.0, 0.0),
    "P1START": (1.0, 1.0), "P1COIN": (2.0, 1.0), "P2START": (15.0, 1.0), "P2COIN": (16.0, 1.0),
    "P1B1": (2.0, 2.0), "P1B2": (3.0, 2.0), "P1B3": (4.0, 2.0), "P1B4": (5.0, 2.0),
    "TRACKBALL": (9.0, 2.4),
    "P2B1": (14.0, 2.0), "P2B2": (15.0, 2.0), "P2B3": (16.0, 2.0), "P2B4": (17.0, 2.0),
    "P1B5": (2.0, 3.0), "P1B6": (3.0, 3.0), "P1B7": (4.0, 3.0), "P1B8": (5.0, 3.0),
    "P2B5": (14.0, 3.0), "P2B6": (15.0, 3.0), "P2B7": (16.0, 3.0), "P2B8": (17.0, 3.0),
}


# --------------------------------------------------------------------------- #
# .NET System.Random
# --------------------------------------------------------------------------- #
_INT32_MIN = -(2 ** 31)
_INT32_MAX = 2 ** 31 - 1


def _i32(value: int) -> int:
    """Wrap to a signed 32-bit int, as unchecked C# arithmetic does."""
    return (value + 2 ** 31) % 2 ** 32 - 2 ** 31


class DotNetRandom:
    """Port of .NET's seeded ``System.Random`` (Knuth's subtractive generator).

    .NET Framework uses it for every ``new Random(seed)``, and .NET Core and
    .NET 5+ keep it for seeded instances, so a seed gives the same sequence as
    the C# that first placed the cute set's fireflies, sprinkles and petals.
    Python's :mod:`random` gives a different one.
    """

    _MBIG = _INT32_MAX
    _MSEED = 161803398

    def __init__(self, seed: int):
        if not _INT32_MIN <= seed <= _INT32_MAX:
            raise ValueError(f"Seed must fit a signed 32-bit int, got {seed}")
        mbig = self._MBIG
        subtraction = mbig if seed == _INT32_MIN else abs(seed)
        mj = self._MSEED - subtraction
        seeds = [0] * 56
        seeds[55] = mj
        mk = 1
        for i in range(1, 55):
            ii = (21 * i) % 55
            seeds[ii] = mk
            mk = _i32(mj - mk)
            if mk < 0:
                mk += mbig
            mj = seeds[ii]
        for _ in range(4):
            for i in range(1, 56):
                seeds[i] = _i32(seeds[i] - seeds[1 + (i + 30) % 55])
                if seeds[i] < 0:
                    seeds[i] += mbig
        self._seeds = seeds
        self._inext = 0
        self._inextp = 21

    def _internal_sample(self) -> int:
        inext = self._inext + 1
        if inext >= 56:
            inext = 1
        inextp = self._inextp + 1
        if inextp >= 56:
            inextp = 1
        value = _i32(self._seeds[inext] - self._seeds[inextp])
        if value == self._MBIG:
            value -= 1
        if value < 0:
            value += self._MBIG
        self._seeds[inext] = value
        self._inext = inext
        self._inextp = inextp
        return value

    def _sample(self) -> float:
        return self._internal_sample() * (1.0 / self._MBIG)

    def next(self, max_value: Optional[int] = None) -> int:
        """``Next()`` with no argument, or ``Next(maxValue)``: 0 <= n < max_value."""
        if max_value is None:
            return self._internal_sample()
        if max_value < 0:
            raise ValueError("max_value must be >= 0")
        return int(self._sample() * max_value)

    def next_range(self, min_value: int, max_value: int) -> int:
        """``Next(minValue, maxValue)``: min_value <= n < max_value."""
        if min_value > max_value:
            raise ValueError("min_value must be <= max_value")
        span = max_value - min_value
        if span > self._MBIG:
            raise ValueError("Ranges wider than 2**31 - 1 are not supported")
        return int(self._sample() * span) + min_value

    def next_double(self) -> float:
        """``NextDouble()``: 0.0 <= x < 1.0."""
        return self._sample()


# --------------------------------------------------------------------------- #
# Themes and patterns
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CuteTheme:
    """One colourway of a cute pattern.

    Colours are ``(r, g, b)`` tuples on the PAC-LED64's 0-48 scale. ``name`` is
    the file stem (``cute_koi_pond`` -> ``cute_koi_pond.lwax``).
    """

    pattern: str
    name: str
    title: str = ""
    blurb: str = ""
    p1: Tuple[Tuple[float, float, float], ...] = ()
    p2: Tuple[Tuple[float, float, float], ...] = ()
    p3: Tuple[Tuple[float, float, float], ...] = ()
    seed: int = 0

    def with_changes(self, **changes) -> "CuteTheme":
        """A copy with some fields replaced (palettes may be given as lists)."""
        for slot in ("p1", "p2", "p3"):
            if slot in changes:
                changes[slot] = tuple(tuple(c) for c in changes[slot])
        return replace(self, **changes)


@dataclass(frozen=True)
class CuteSlot:
    """What a pattern reads from one palette slot, and how many colours it needs."""

    meaning: str
    min_count: int = 1
    max_count: Optional[int] = None  # None: any number from min_count up

    def count_text(self) -> str:
        if self.max_count == self.min_count:
            return f"exactly {self.min_count}"
        if self.max_count is None:
            return f"{self.min_count} or more"
        return f"{self.min_count}-{self.max_count}"


@dataclass(frozen=True)
class CutePattern:
    key: str                  # e.g. "koi_pond"; the original theme is "cute_" + key
    family: str               # e.g. "Koi pond"
    builder: "Callable[[_Panel, CuteTheme], Tuple[int, Frames]]"
    p1: CuteSlot
    p2: Optional[CuteSlot] = None
    p3: Optional[CuteSlot] = None
    uses_seed: bool = False
    needs_trackball: bool = False

    def slots(self) -> "List[Tuple[str, Optional[CuteSlot]]]":
        return [("p1", self.p1), ("p2", self.p2), ("p3", self.p3)]

    def check(self, theme: CuteTheme, slot_labels: "Optional[Dict[str, str]]" = None) -> None:
        """Raise ``ValueError`` if ``theme`` can't drive this pattern.

        ``slot_labels`` renames the slots in the message (the CLI passes its
        ``--color`` / ``--color2`` / ``--color3`` flags).
        """
        for slot_name, slot in self.slots():
            label = (slot_labels or {}).get(slot_name, slot_name)
            colors = getattr(theme, slot_name)
            if slot is None:
                if colors:
                    raise ValueError(f"{self.key} doesn't use {label}; leave it out.")
                continue
            n = len(colors)
            if n < slot.min_count or (slot.max_count is not None and n > slot.max_count):
                raise ValueError(
                    f"{self.key} {label} ({slot.meaning}) needs {slot.count_text()} "
                    f"colour(s), got {n}."
                )
            for color in colors:
                if len(color) != 3 or not all(0 <= v <= 48 for v in color):
                    raise ValueError(f"{self.key} {label}: colour {tuple(color)} is not 3 values 0-48.")
        if not _INT32_MIN <= theme.seed <= _INT32_MAX:
            raise ValueError(f"Seed must fit a signed 32-bit int, got {theme.seed}")


class _Panel:
    """Label order and positions shared by the pattern functions.

    Labels are indexed in the order they first appear in the input map, as the
    original C# did; random placement picks label indexes, so this order is
    part of what a seed means.
    """

    def __init__(self, labels: Sequence[str]):
        missing = [label for label in labels if label not in PANEL_POS]
        if missing:
            raise ValueError(
                "The cute patterns use the example cabinet's panel layout; no position "
                f"for control label(s) {missing}. Add them to lwax_cute.PANEL_POS."
            )
        self.labels = list(labels)
        self.n = len(self.labels)
        self.x = [PANEL_POS[label][0] for label in self.labels]
        self.y = [PANEL_POS[label][1] for label in self.labels]
        self.tb = self.labels.index("TRACKBALL") if "TRACKBALL" in self.labels else -1

    def d2(self, l: int, x: float, y: float) -> float:
        dx = self.x[l] - x
        dy = self.y[l] - y
        return dx * dx + dy * dy


def labels_in_map_order(controllers: Sequence[LwaxController]) -> List[str]:
    """Wired control labels in the order they first appear in the input map."""
    seen: List[str] = []
    for controller in controllers:
        for port in controller.ports:
            if port.label and port.label not in seen:
                seen.append(port.label)
    return seen


# --------------------------------------------------------------------------- #
# Colour and easing helpers. Same operations, in the same order, as the C#
# original, so the floating-point results (and the rounded 0-48 values) match.
# --------------------------------------------------------------------------- #
def _cl(t: float) -> float:
    return 0 if t < 0 else 1 if t > 1 else t


def _sm(t: float) -> float:
    """Smoothstep on [0, 1]."""
    t = _cl(t)
    return t * t * (3 - 2 * t)


def _fr(u: float) -> float:
    return u - math.floor(u)


def _mix(a, b, t: float) -> FloatColor:
    t = _cl(t)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _sc(a, k: float) -> FloatColor:
    return (a[0] * k, a[1] * k, a[2] * k)


def _screen1(x: float, y: float) -> float:
    return 48 - (48 - min(48, x)) * (48 - min(48, y)) / 48


def _scr(a, b) -> FloatColor:
    """Screen blend: light added on top of light, never past 48."""
    return (_screen1(a[0], b[0]), _screen1(a[1], b[1]), _screen1(a[2], b[2]))


def _pal(p, u: float) -> FloatColor:
    """Cyclic smooth palette lookup."""
    u = _fr(u) * len(p)
    i = int(math.floor(u)) % len(p)
    return _mix(p[i], p[(i + 1) % len(p)], _sm(u - math.floor(u)))


def _pal_crisp(p, u: float) -> FloatColor:
    """Cyclic palette with firmer stripe edges (still faded)."""
    u = _fr(u) * len(p)
    i = int(math.floor(u)) % len(p)
    return _mix(p[i], p[(i + 1) % len(p)], _sm(_sm(u - math.floor(u))))


def _ramp(p, u: float) -> FloatColor:
    """Non-cyclic palette lookup, u clamped to [0, 1]."""
    u = _cl(u) * (len(p) - 1)
    i = min(int(u), len(p) - 2)
    return _mix(p[i], p[i + 1], _sm(u - i))


def _gs(d2: float, s: float) -> float:
    return math.exp(-d2 / (2 * s * s))


def _age(f: int, start: int, n: int) -> int:
    return (f - start) % n


def _tri(u: float) -> float:
    return 1 - abs(2 * _fr(u) - 1)


# --------------------------------------------------------------------------- #
# The patterns. Each returns (frame duration in ms, frames), one colour per
# label index per frame.
# --------------------------------------------------------------------------- #
def _gumball_roll(panel: _Panel, t: CuteTheme):
    pal = t.p1
    L, X, Y = panel.n, panel.x, panel.y
    step, hold = 36, 14
    n = step * len(pal)
    order = sorted(range(L), key=lambda l: math.atan2(Y[l] - 1.6, (X[l] - 9) / 3.0))
    rank = [0] * L
    for i, l in enumerate(order):
        rank[l] = i
    frames = []
    for f in range(n):
        s = f // step
        u = _sm((f % step) / (step - hold))
        frames.append([
            _mix(pal[(rank[l] + s) % len(pal)], pal[(rank[l] + s + 1) % len(pal)], u)
            for l in range(L)
        ])
    return 42, frames


def _fairy_lights(panel: _Panel, t: CuteTheme):
    pal = t.p1
    L, X, Y = panel.n, panel.x, panel.y
    n = 264
    rng = DotNetRandom(t.seed)
    k, ph, idx = [], [], []
    for l in range(L):
        k.append(1 + rng.next(3))
        ph.append(rng.next_double() * TAU)
        idx.append((int(X[l]) + 2 * int(Y[l])) % len(pal))
    frames = []
    for f in range(n):
        p = f / n
        frames.append([
            _sc(pal[idx[l]], 0.35 + 0.65 * (0.5 + 0.5 * math.sin(TAU * k[l] * p + ph[l])))
            for l in range(L)
        ])
    return 45, frames


def _cotton_candy_clouds(panel: _Panel, t: CuteTheme):
    pal = t.p1
    L, X, Y = panel.n, panel.x, panel.y
    n = 320
    frames = []
    for f in range(n):
        p = f / n
        row = []
        for l in range(L):
            x, y = X[l], Y[l]
            v = (0.5 + 0.22 * math.sin(0.45 * x + TAU * p)
                 + 0.18 * math.sin(0.9 * y - 0.25 * x + TAU * 2 * p)
                 + 0.1 * math.sin(0.7 * (x + y) - TAU * p))
            b = 0.8 + 0.2 * math.sin(0.35 * x + 0.8 * y + TAU * 2 * p)
            row.append(_sc(_pal(pal, v + p), b))
        frames.append(row)
    return 50, frames


def _rainbow_sherbet(panel: _Panel, t: CuteTheme):
    pal = t.p1
    L, X, Y = panel.n, panel.x, panel.y
    n = 300
    frames = []
    for f in range(n):
        p = f / n
        frames.append([_pal(pal, X[l] / 17 * 1.1 + Y[l] / 3 * 0.3 - 2 * p) for l in range(L)])
    return 45, frames


def _firefly_meadow(panel: _Panel, t: CuteTheme):
    flies = t.p1
    sky, ground = t.p2
    L, X, Y = panel.n, panel.x, panel.y
    n = 360
    rng = DotNetRandom(t.seed)
    ev = 46
    st, lab, dur, col = [], [], [], []
    for _ in range(ev):
        st.append(rng.next(n))
        lab.append(rng.next(L))
        dur.append(28 + rng.next(12))
        col.append(flies[rng.next(len(flies))])
    frames = []
    for f in range(n):
        p = f / n
        row = [sky if Y[l] < 1.5 else _sc(ground, 0.8 + 0.2 * math.sin(0.6 * X[l] + TAU * p))
               for l in range(L)]
        for e in range(ev):
            age = _age(f, st[e], n)
            if age >= dur[e]:
                continue
            s = math.sin(math.pi * age / dur[e])
            row[lab[e]] = _scr(row[lab[e]], _sc(col[e], s * s))
        frames.append(row)
    return 45, frames


def _koi_pond(panel: _Panel, t: CuteTheme):
    a, b = t.p1, t.p2
    w1, w2 = t.p3
    L, X, Y = panel.n, panel.x, panel.y
    n = 360
    wt = (1.0, 0.95, 0.75, 0.5)
    frames = []
    for f in range(n):
        p = f / n
        row = [_mix(w1, w2, 0.5 + 0.5 * math.sin(0.5 * X[l] + 1.1 * Y[l] + TAU * 2 * p))
               for l in range(L)]
        for s in (3, 2, 1, 0):
            th = TAU * p - 0.14 * s
            ax, ay = 9 + 7.6 * math.cos(th), 1.6 + 1.35 * math.sin(th)
            th2 = -TAU * 2 * p + math.pi + 0.2 * s
            bx, by = 9 + 5.5 * math.cos(th2), 1.5 + 1.1 * math.sin(th2)
            for l in range(L):
                row[l] = _mix(row[l], a[s], _gs(panel.d2(l, ax, ay), 0.62) * wt[s])
                row[l] = _mix(row[l], b[s], _gs(panel.d2(l, bx, by), 0.62) * wt[s])
        frames.append(row)
    return 45, frames


def _sprinkle_donut(panel: _Panel, t: CuteTheme):
    sp = t.p1
    f1, f2 = t.p2
    L, X, Y = panel.n, panel.x, panel.y
    n = 336
    rng = DotNetRandom(t.seed)
    ev = 64
    st, lab, dur, col = [], [], [], []
    for _ in range(ev):
        st.append(rng.next(n))
        lab.append(rng.next(L))
        dur.append(30 + rng.next(10))
        col.append(sp[rng.next(len(sp))])
    frames = []
    for f in range(n):
        p = f / n
        row = [_mix(f1, f2, 0.5 + 0.5 * math.sin(0.8 * X[l] + Y[l] + TAU * p)) for l in range(L)]
        for e in range(ev):
            age = _age(f, st[e], n)
            if age >= dur[e]:
                continue
            if age < 8:
                env = _sm(age / 8.0)
            elif age > dur[e] - 14:
                env = _sm((dur[e] - age) / 14.0)
            else:
                env = 1
            row[lab[e]] = _mix(row[lab[e]], col[e], env)
        frames.append(row)
    return 42, frames


_BUBBLE_COLUMNS = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 15.0, 16.0, 17.0)


def _bubble_tea(panel: _Panel, t: CuteTheme):
    bub = t.p1
    top, bottom = t.p2
    L, Y = panel.n, panel.y
    n = 320
    rng = DotNetRandom(t.seed)
    ev, dur = 34, 50
    st, bx, col = [], [], []
    for _ in range(ev):
        st.append(rng.next(n))
        bx.append(_BUBBLE_COLUMNS[rng.next(len(_BUBBLE_COLUMNS))])
        col.append(bub[rng.next(len(bub))])
    frames = []
    for f in range(n):
        row = [_mix(top, bottom, Y[l] / 3) for l in range(L)]
        for e in range(ev):
            age = _age(f, st[e], n)
            if age >= dur:
                continue
            a = age / dur
            env = _sm(age / 6.0) * _sm((dur - age) / 6.0)
            x, y = bx[e] + 0.25 * math.sin(age * 0.3), 3.7 - 4.4 * a
            for l in range(L):
                row[l] = _mix(row[l], col[e], _gs(panel.d2(l, x, y), 0.55) * env * 1.1)
        frames.append(row)
    return 45, frames


def _lollipop_swirl(panel: _Panel, t: CuteTheme):
    pal = t.p1
    L, X, Y = panel.n, panel.x, panel.y
    n = 288
    frames = []
    for f in range(n):
        p = f / n
        row = []
        for l in range(L):
            dx, dy = (X[l] - 9) / 2.6, Y[l] - 1.6
            u = math.atan2(dy, dx) / TAU + math.sqrt(dx * dx + dy * dy) * 0.18 - 2 * p
            row.append(_pal_crisp(pal, u))
        frames.append(row)
    return 42, frames


def _sakura_breeze(panel: _Panel, t: CuteTheme):
    pet = t.p1
    sky, ground = t.p2
    L, Y = panel.n, panel.y
    n = 360
    rng = DotNetRandom(t.seed)
    ev, dur = 40, 70
    st, x0, col = [], [], []
    for _ in range(ev):
        st.append(rng.next(n))
        x0.append(rng.next_double() * 20 - 2)
        col.append(pet[rng.next(len(pet))])
    frames = []
    for f in range(n):
        row = [_mix(sky, ground, Y[l] / 3) for l in range(L)]
        for e in range(ev):
            age = _age(f, st[e], n)
            if age >= dur:
                continue
            a = age / dur
            env = _sm(age / 8.0) * _sm((dur - age) / 8.0)
            x, y = x0[e] + 2.5 * a + 0.5 * math.sin(a * TAU * 1.5), -0.7 + 4.6 * a
            for l in range(L):
                row[l] = _mix(row[l], col[e], _gs(panel.d2(l, x, y), 0.55) * env)
        frames.append(row)
    return 45, frames


def _sunrise_sunset(panel: _Panel, t: CuteTheme):
    ramp = t.p1
    sun = t.p2[0]
    L, X, Y, tb = panel.n, panel.x, panel.y, panel.tb
    n = 400
    frames = []
    for f in range(n):
        p = f / n
        s = 0.5 - 0.5 * math.cos(TAU * p)
        row = []
        for l in range(L):
            lvl = s * 1.35 - (3 - Y[l]) / 3 * 0.35 + 0.04 * math.sin(0.6 * X[l] + TAU * p)
            row.append(_ramp(ramp, lvl))
        row[tb] = _mix(row[tb], sun, _sm((s - 0.25) / 0.5) * 0.8)
        frames.append(row)
    return 50, frames


def _aurora_dance(panel: _Panel, t: CuteTheme):
    ramp = t.p1
    sky = t.p2[0]
    L, X, Y = panel.n, panel.x, panel.y
    n = 360
    frames = []
    for f in range(n):
        p = f / n
        row = []
        for l in range(L):
            x, y = X[l], Y[l]
            intensity = ((0.55 + 0.45 * math.sin(0.55 * x + TAU * 2 * p))
                         * (0.6 + 0.4 * math.sin(0.23 * x - TAU * p + 1.3)))
            hang = 0.35 + 0.65 * (1 - y / 3.2)
            u = (1 - y / 3) * 0.8 + 0.2 * (0.5 + 0.5 * math.sin(0.3 * x + TAU * p))
            row.append(_scr(sky, _sc(_ramp(ramp, u), intensity * hang)))
        frames.append(row)
    return 45, frames


# A winding path through every button, in PANEL_POS coordinates.
_CATERPILLAR_PATH = (
    (1.0, 1.0), (2.0, 2.0), (5.0, 2.0), (6.0, 0.0), (12.0, 0.0), (14.0, 2.0), (15.0, 1.0),
    (16.0, 1.0), (17.0, 2.0), (17.0, 3.0), (14.0, 3.0), (9.0, 2.4), (5.0, 3.0), (2.0, 3.0),
)


def _rainbow_caterpillar(panel: _Panel, t: CuteTheme):
    wp = _CATERPILLAR_PATH
    m = len(wp)
    cum = [0.0] * (m + 1)
    for i in range(m):
        a, b = wp[i], wp[(i + 1) % m]
        cum[i + 1] = cum[i] + math.sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]))
    total = cum[m]

    def at(s: float) -> "Tuple[float, float]":
        s = _fr(s / total) * total
        i = 0
        while i < m - 1 and cum[i + 1] <= s:
            i += 1
        u = (s - cum[i]) / (cum[i + 1] - cum[i])
        a, b = wp[i], wp[(i + 1) % m]
        return a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u

    seg = t.p1
    ground = t.p2[0]
    L = panel.n
    n = 300
    frames = []
    for f in range(n):
        head = total * f / n
        row = [ground] * L
        for i in range(len(seg) - 1, -1, -1):
            px, py = at(head - i * 0.95)
            for l in range(L):
                row[l] = _mix(row[l], seg[i], _gs(panel.d2(l, px, py), 0.5))
        frames.append(row)
    return 40, frames


def _garden_bloom(panel: _Panel, t: CuteTheme):
    fl = t.p1
    leaf_color = t.p2[0]
    L, X = panel.n, panel.x
    n, dur = 400, 110
    rng = DotNetRandom(t.seed)
    s1, s2, c1, c2 = [], [], [], []
    for _ in range(L):
        first = rng.next(n)
        s1.append(first)
        s2.append((first + n // 2 + rng.next_range(-30, 31) + n) % n)
        a = rng.next(len(fl))
        b = (a + 1 + rng.next(len(fl) - 1)) % len(fl)
        c1.append(fl[a])
        c2.append(fl[b])

    def env(age: int) -> float:
        if age >= dur:
            return 0
        if age < 26:
            return _sm(age / 26.0)
        if age < 66:
            return 1
        return _sm((dur - age) / 44.0)

    frames = []
    for f in range(n):
        p = f / n
        row = []
        for l in range(L):
            leaf = _sc(leaf_color, 0.85 + 0.15 * math.sin(0.7 * X[l] + TAU * p))
            color = _mix(leaf, c1[l], env(_age(f, s1[l], n)))
            row.append(_mix(color, c2[l], env(_age(f, s2[l], n))))
        frames.append(row)
    return 45, frames


def _candy_cane_stripes(panel: _Panel, t: CuteTheme):
    seq = t.p1
    L, X, Y = panel.n, panel.x, panel.y
    n = 270
    frames = []
    for f in range(n):
        p = f / n
        frames.append([_pal_crisp(seq, X[l] * 0.11 + Y[l] * 0.27 - 2 * p) for l in range(L)])
    return 45, frames


def _fruit_punch(panel: _Panel, t: CuteTheme):
    bl = t.p1
    ax, ay = (1, 2, 1, 2, 1, 1), (2, 3, 1, 2, 3, 2)
    rng = DotNetRandom(t.seed)
    px, py = [], []
    for _ in range(6):
        px.append(rng.next_double() * TAU)
        py.append(rng.next_double() * TAU)
    L = panel.n
    n = 360
    frames = []
    for f in range(n):
        p = f / n
        centres = [
            (9 + 8 * math.sin(TAU * ax[i] * p + px[i]), 1.6 + 1.7 * math.sin(TAU * ay[i] * p + py[i]))
            for i in range(6)
        ]
        row = []
        for l in range(L):
            sw = r = g = b = 0.0
            for i, (x, y) in enumerate(centres):
                w = _gs(panel.d2(l, x, y), 2.2) + 1e-9
                sw += w
                r += w * bl[i][0]
                g += w * bl[i][1]
                b += w * bl[i][2]
            row.append((r / sw, g / sw, b / sw))
        frames.append(row)
    return 45, frames


def _bouncy_ball(panel: _Panel, t: CuteTheme):
    pal = t.p1
    bg = t.p2[0]
    L = panel.n
    kx, ky, n = 2, 5, 320

    def hits(q: float) -> int:
        return int(math.floor(2 * kx * _fr(q))) + int(math.floor(2 * ky * _fr(q)))

    lag, weight = (0.012, 0.006, 0.0), (0.2, 0.45, 1.0)
    frames = []
    for f in range(n):
        p = f / n
        sx, sy = _fr(2 * kx * p) / (2 * kx), _fr(2 * ky * p) / (2 * ky)
        since = min(sx, sy)
        now = pal[hits(p) % len(pal)]
        before = pal[hits(p - since - 1e-6 + 1) % len(pal)]
        ball = _mix(before, now, _sm(since * n / 7.0))
        row = [bg] * L
        for k in range(3):
            q = p - lag[k]
            x, y = 1 + 16 * _tri(kx * q), 3 * _tri(ky * q)
            for l in range(L):
                row[l] = _scr(row[l], _sc(ball, weight[k] * _gs(panel.d2(l, x, y), 0.7)))
        frames.append(row)
    return 45, frames


def _mermaid_scales(panel: _Panel, t: CuteTheme):
    pal = t.p1
    glint = t.p2[0]
    L, X, Y = panel.n, panel.x, panel.y
    n = 360
    frames = []
    for f in range(n):
        p = f / n
        sp = -5 + 30 * _fr(3 * p)
        row = []
        for l in range(L):
            u = X[l] * 0.09 + (round(Y[l]) % 2) * 0.1 + Y[l] * 0.12 + p
            gl = _gs(math.pow(X[l] - Y[l] * 1.5 - sp, 2), 1.1)
            row.append(_mix(_pal(pal, u), glint, gl * 0.55))
        frames.append(row)
    return 45, frames


def _starry_lullaby(panel: _Panel, t: CuteTheme):
    stars = t.p1
    sky_top, sky_bottom, moon, shoot = t.p2
    L, Y, tb = panel.n, panel.y, panel.tb
    n = 400
    rng = DotNetRandom(t.seed)
    k, ph, sc = [], [], []
    for _ in range(L):
        k.append(1 + rng.next(2))
        ph.append(rng.next_double() * TAU)
        sc.append(stars[rng.next(len(stars))])
    start, dur = 200, 40
    trail = (1.0, 0.6, 0.35, 0.15)
    frames = []
    for f in range(n):
        p = f / n
        row = []
        for l in range(L):
            sky = _mix(sky_top, sky_bottom, Y[l] / 3)
            e = math.pow(max(0.0, math.sin(TAU * k[l] * p + ph[l])), 3)
            row.append(_scr(sky, _sc(sc[l], 0.12 + 0.88 * e)))
        row[tb] = _sc(moon, 0.8 + 0.2 * math.sin(TAU * p))
        age = _age(f, start, n)
        if age < dur:
            a = age / dur
            env = _sm(age / 5.0) * _sm((dur - age) / 8.0)
            for q in (3, 2, 1, 0):
                x, y = 5 + 8 * a - 0.6 * q, -0.2 + 0.8 * a - 0.06 * q
                for l in range(L):
                    if l != tb:
                        row[l] = _scr(row[l], _sc(shoot, env * trail[q] * _gs(panel.d2(l, x, y), 0.6)))
        frames.append(row)
    return 45, frames


# Footprints out along the button rows and back along the top, in PANEL_POS coordinates.
_PAW_STEPS = (
    (2.0, 2.0), (3.0, 3.0), (4.0, 2.0), (5.0, 3.0), (9.0, 2.4), (14.0, 3.0), (15.0, 2.0),
    (16.0, 3.0), (17.0, 2.0), (16.0, 1.0), (15.0, 1.0), (12.0, 0.0), (11.0, 0.0), (10.0, 0.0),
    (8.0, 0.0), (7.0, 0.0), (6.0, 0.0), (2.0, 1.0), (1.0, 1.0),
)


def _paw_prints(panel: _Panel, t: CuteTheme):
    pal = t.p1
    bg = t.p2[0]
    L = panel.n
    every, nsteps, dur = 10, len(_PAW_STEPS) * 2, 60
    n = every * nsteps
    frames = []
    for f in range(n):
        row = [bg] * L
        for s in range(nsteps):
            age = _age(f, s * every, n)
            if age >= dur:
                continue
            if age < 7:
                env = _sm(age / 7.0)
            elif age < 19:
                env = 1
            else:
                env = _sm((dur - age) / 41.0)
            px, py = _PAW_STEPS[s % len(_PAW_STEPS)]
            for l in range(L):
                row[l] = _mix(row[l], pal[s % len(pal)], _gs(panel.d2(l, px, py), 0.42) * env)
        frames.append(row)
    return 45, frames


def _slot(meaning: str, min_count: int = 1, max_count: Optional[int] = None) -> CuteSlot:
    return CuteSlot(meaning, min_count, max_count)


def _exactly(meaning: str, count: int) -> CuteSlot:
    return CuteSlot(meaning, count, count)


CUTE_PATTERNS: Dict[str, CutePattern] = {p.key: p for p in (
    CutePattern("gumball_roll", "Gumball roll", _gumball_roll,
                _slot("gumball colours", 2)),
    CutePattern("fairy_lights", "Fairy lights", _fairy_lights,
                _slot("bulb colours"), uses_seed=True),
    CutePattern("cotton_candy_clouds", "Cotton candy clouds", _cotton_candy_clouds,
                _slot("cloud colours", 2)),
    CutePattern("rainbow_sherbet", "Rainbow sherbet", _rainbow_sherbet,
                _slot("band colours", 2)),
    CutePattern("firefly_meadow", "Firefly meadow", _firefly_meadow,
                _slot("glow colours"), _exactly("upper-row sky, lower-row ground", 2), uses_seed=True),
    CutePattern("koi_pond", "Koi pond", _koi_pond,
                _exactly("first fish, head to tail", 4), _exactly("second fish, head to tail", 4),
                _exactly("two water colours", 2)),
    CutePattern("sprinkle_donut", "Sprinkle donut", _sprinkle_donut,
                _slot("sprinkle colours"), _exactly("two frosting colours", 2), uses_seed=True),
    CutePattern("bubble_tea", "Bubble tea", _bubble_tea,
                _slot("bubble colours"), _exactly("tea at the top, tea at the bottom", 2), uses_seed=True),
    CutePattern("lollipop_swirl", "Lollipop swirl", _lollipop_swirl,
                _slot("pinwheel colours", 2)),
    CutePattern("sakura_breeze", "Sakura breeze", _sakura_breeze,
                _slot("falling-piece colours"), _exactly("sky at the top, ground at the bottom", 2),
                uses_seed=True),
    CutePattern("sunrise_sunset", "Sunrise sunset", _sunrise_sunset,
                _slot("sky ramp, night to day", 2), _exactly("sun (the trackball)", 1),
                needs_trackball=True),
    CutePattern("aurora_dance", "Aurora dance", _aurora_dance,
                _slot("curtain ramp, bottom to top", 2), _exactly("night sky", 1)),
    CutePattern("rainbow_caterpillar", "Rainbow caterpillar", _rainbow_caterpillar,
                _slot("body segments, head first"), _exactly("ground", 1)),
    CutePattern("garden_bloom", "Garden bloom", _garden_bloom,
                _slot("flower colours", 2), _exactly("leaves", 1), uses_seed=True),
    CutePattern("candy_cane_stripes", "Candy cane stripes", _candy_cane_stripes,
                _slot("stripe sequence", 2)),
    CutePattern("fruit_punch", "Fruit punch", _fruit_punch,
                _exactly("blob colours", 6), uses_seed=True),
    CutePattern("bouncy_ball", "Bouncy ball", _bouncy_ball,
                _slot("ball colours, one per wall hit"), _exactly("background", 1)),
    CutePattern("mermaid_scales", "Mermaid scales", _mermaid_scales,
                _slot("scale colours", 2), _exactly("glint", 1)),
    CutePattern("starry_lullaby", "Starry lullaby", _starry_lullaby,
                _slot("star colours"), _exactly("sky top, sky bottom, moon (the trackball), shooting star", 4),
                uses_seed=True, needs_trackball=True),
    CutePattern("paw_prints", "Paw prints", _paw_prints,
                _slot("print colours"), _exactly("background", 1)),
)}


def build_cute(controllers: Sequence[LwaxController], theme: CuteTheme) -> LwaxAnimation:
    """Build ``theme`` as an animation over ``controllers``.

    Raises ``ValueError`` for an unknown pattern, a palette the pattern can't
    use, or a wired control with no :data:`PANEL_POS` entry.
    """
    pattern = CUTE_PATTERNS.get(theme.pattern)
    if pattern is None:
        raise ValueError(f"Unknown cute pattern '{theme.pattern}'. Known: {', '.join(CUTE_PATTERNS)}")
    pattern.check(theme)
    panel = _Panel(labels_in_map_order(controllers))
    if pattern.needs_trackball and panel.tb < 0:
        raise ValueError(f"{pattern.key} lights the trackball, but the input map has no TRACKBALL control.")
    frame_ms, frames = pattern.builder(panel, theme)
    animation = LwaxAnimation(list(controllers))
    labels = panel.labels
    for row in frames:
        animation.add_frame(frame_ms, {
            labels[l]: (_level(c[0]), _level(c[1]), _level(c[2])) for l, c in enumerate(row)
        })
    return animation


def _level(v: float) -> int:
    """Round half to even (as C#'s Math.Round does), then clamp to 0-48."""
    return max(0, min(48, round(v)))


def _theme(pattern, name, title, blurb, p1, p2=(), p3=(), seed=0) -> CuteTheme:
    return CuteTheme(
        pattern=pattern, name=name, title=title, blurb=blurb,
        p1=tuple(p1), p2=tuple(p2), p3=tuple(p3), seed=seed,
    )


# --------------------------------------------------------------------------- #
# The 60 themes: each pattern's original ("cute_<pattern>") and two colourways.
# --------------------------------------------------------------------------- #
CUTE_THEMES: Tuple[CuteTheme, ...] = (
    # Gumball roll
    _theme("gumball_roll", "cute_gumball_roll", "Original",
           "Eight candy-coloured gumballs roll around the panel, each button handing its colour to the next.",
           p1=[(48, 2, 6), (48, 16, 0), (48, 40, 0), (18, 48, 2),
               (0, 40, 44), (4, 10, 48), (26, 4, 48), (48, 10, 28)]),
    _theme("gumball_roll", "cute_gumball_roll_sunset_sorbet", "Sunset sorbet",
           "Warm sorbet gumballs in raspberry, mango, plum, blood orange, rose and lemon roll around the panel.",
           p1=[(48, 0, 12), (48, 30, 0), (36, 0, 32), (48, 12, 0),
               (48, 8, 28), (48, 44, 6), (48, 20, 12), (40, 0, 20)]),
    _theme("gumball_roll", "cute_gumball_roll_sea_glass", "Sea glass",
           "Sea-glass gumballs in seafoam, cobalt, turquoise, kelp green and periwinkle tumble around the panel.",
           p1=[(0, 48, 30), (0, 22, 48), (0, 44, 44), (18, 48, 10),
               (6, 8, 48), (0, 40, 18), (22, 30, 48), (0, 34, 48)]),
    # Fairy lights
    _theme("fairy_lights", "cute_fairy_lights", "Original",
           "A string of vintage bulbs, every button a different colour, each softly brightening and dimming on its own.",
           p1=[(48, 24, 0), (48, 0, 8), (0, 44, 12), (0, 10, 48), (48, 36, 18), (40, 0, 40)],
           seed=2),
    _theme("fairy_lights", "cute_fairy_lights_pastel_party", "Pastel party",
           "Party bulbs in bubblegum, mint, lavender, peach, baby blue and lemon twinkle out of step.",
           p1=[(48, 10, 24), (8, 48, 24), (28, 12, 48), (48, 24, 8), (8, 28, 48), (44, 44, 6)],
           seed=3),
    _theme("fairy_lights", "cute_fairy_lights_winter_frost", "Winter frost",
           "Icy bulbs in frost white, ice blue, lilac, aqua and orchid twinkle like a frosty window.",
           p1=[(10, 26, 48), (40, 42, 48), (26, 8, 48), (0, 44, 44), (14, 14, 48), (40, 14, 48)],
           seed=4),
    # Cotton candy clouds
    _theme("cotton_candy_clouds", "cute_cotton_candy_clouds", "Original",
           "Pink, baby-blue and lavender clouds drift and swirl into each other.",
           p1=[(48, 10, 30), (10, 30, 48), (30, 16, 48), (48, 26, 36), (40, 6, 44)]),
    _theme("cotton_candy_clouds", "cute_cotton_candy_pink_lemonade", "Pink lemonade",
           "Pink-lemonade clouds of strawberry, lemon and peach swirl into each other.",
           p1=[(48, 10, 22), (48, 42, 4), (48, 22, 10), (48, 2, 10), (48, 34, 16)]),
    _theme("cotton_candy_clouds", "cute_cotton_candy_sour_apple", "Sour apple",
           "Sour-apple clouds in green apple, mint, lemon and aqua drift and swirl.",
           p1=[(16, 48, 0), (0, 48, 30), (44, 46, 4), (0, 38, 44), (30, 48, 16)]),
    # Rainbow sherbet
    _theme("rainbow_sherbet", "cute_rainbow_sherbet", "Original",
           "Raspberry, orange, lemon and lime bands slide across the panel like a melting scoop.",
           p1=[(48, 0, 16), (48, 20, 0), (48, 42, 6), (24, 48, 6), (48, 28, 10)]),
    _theme("rainbow_sherbet", "cute_sherbet_blue_raspberry", "Blue raspberry",
           "Blue raspberry, red raspberry, grape and ice-blue bands slide across the panel.",
           p1=[(0, 20, 48), (48, 0, 20), (30, 0, 48), (0, 40, 48), (48, 10, 40)]),
    _theme("rainbow_sherbet", "cute_sherbet_lavender_honey", "Lavender honey",
           "Lavender, honey, pink, violet and apricot bands glide across the panel.",
           p1=[(30, 10, 48), (48, 34, 0), (48, 10, 30), (20, 0, 40), (48, 24, 8)]),
    # Firefly meadow
    _theme("firefly_meadow", "cute_firefly_meadow", "Original",
           "A dusky meadow where little yellow, gold and aqua fireflies glow up and fade all over the panel.",
           p1=[(30, 48, 0), (48, 34, 0), (40, 48, 4), (10, 48, 30)],
           p2=[(3, 0, 10), (0, 7, 1)],
           seed=5),
    _theme("firefly_meadow", "cute_glowworm_cave", "Glowworm cave",
           "Blue and aqua glowworms light up and fade on the walls of a dark cave.",
           p1=[(0, 30, 48), (0, 48, 40), (10, 44, 48), (16, 20, 48)],
           p2=[(0, 1, 8), (0, 5, 6)],
           seed=6),
    _theme("firefly_meadow", "cute_lantern_festival", "Lantern festival",
           "Red, orange and gold paper lanterns glow up and fade across a purple night sky.",
           p1=[(48, 6, 0), (48, 26, 0), (48, 40, 8), (48, 0, 14)],
           p2=[(6, 0, 14), (2, 2, 10)],
           seed=7),
    # Koi pond
    _theme("koi_pond", "cute_koi_pond", "Original",
           "Two koi, one orange and one red-and-white, glide in loops through rippling teal water.",
           p1=[(48, 34, 22), (48, 14, 0), (48, 8, 0), (40, 2, 0)],
           p2=[(44, 40, 40), (48, 0, 6), (48, 20, 20), (36, 0, 4)],
           p3=[(0, 16, 20), (0, 5, 26)]),
    _theme("koi_pond", "cute_koi_moonlight", "Moonlit pond",
           "A gold koi and a lilac koi glide through a moonlit indigo pond.",
           p1=[(48, 46, 26), (48, 36, 0), (48, 28, 0), (40, 18, 0)],
           p2=[(48, 30, 48), (40, 10, 48), (34, 0, 40), (24, 0, 30)],
           p3=[(1, 3, 18), (6, 0, 22)]),
    _theme("koi_pond", "cute_koi_lily_pads", "Lily pads",
           "A pink koi and a sky-blue koi swim loops between green lily pads.",
           p1=[(48, 32, 38), (48, 8, 24), (48, 4, 18), (40, 0, 14)],
           p2=[(30, 44, 48), (0, 30, 48), (0, 22, 48), (0, 14, 40)],
           p3=[(2, 20, 4), (0, 14, 10)]),
    # Sprinkle donut
    _theme("sprinkle_donut", "cute_sprinkle_donut", "Original",
           "Strawberry-pink frosting with rainbow sprinkles popping up and melting away.",
           p1=[(48, 0, 0), (48, 40, 0), (0, 24, 48), (4, 48, 4), (40, 40, 40), (48, 16, 0), (26, 0, 48)],
           p2=[(24, 3, 11), (32, 7, 17)],
           seed=7),
    _theme("sprinkle_donut", "cute_donut_chocolate", "Chocolate",
           "Chocolate frosting with pink, mint, lemon, lilac, sky and vanilla sprinkles popping up and melting away.",
           p1=[(48, 10, 26), (6, 48, 24), (48, 44, 8), (30, 12, 48), (8, 30, 48), (48, 40, 30)],
           p2=[(12, 4, 1), (18, 7, 2)],
           seed=8),
    _theme("sprinkle_donut", "cute_donut_blueberry_glaze", "Blueberry glaze",
           "Blueberry glaze with gold, pink, white, green, orange and purple sprinkles.",
           p1=[(48, 40, 0), (48, 0, 20), (44, 44, 40), (0, 48, 20), (48, 16, 0), (40, 0, 48)],
           p2=[(3, 6, 28), (8, 10, 36)],
           seed=9),
    # Bubble tea
    _theme("bubble_tea", "cute_bubble_tea", "Original",
           "Taro, matcha, strawberry, mango and butterfly-pea bubbles float up through warm milk tea.",
           p1=[(30, 6, 48), (14, 40, 4), (48, 8, 18), (48, 22, 0), (6, 14, 48)],
           p2=[(18, 9, 3), (10, 4, 1)],
           seed=8),
    _theme("bubble_tea", "cute_bubble_tea_butterfly_pea", "Butterfly pea",
           "Cream, pink, honey, aqua and lilac bubbles rise through blue-to-purple butterfly-pea tea.",
           p1=[(48, 40, 30), (48, 10, 30), (48, 40, 0), (0, 44, 40), (36, 10, 48)],
           p2=[(4, 8, 30), (12, 2, 24)],
           seed=9),
    _theme("bubble_tea", "cute_bubble_tea_matcha", "Matcha latte",
           "Caramel, strawberry, cream, taro and mango bubbles float up through green matcha.",
           p1=[(48, 24, 4), (48, 6, 14), (48, 44, 24), (40, 0, 44), (48, 40, 0)],
           p2=[(8, 20, 2), (4, 12, 1)],
           seed=10),
    # Lollipop swirl
    _theme("lollipop_swirl", "cute_lollipop_swirl", "Original",
           "A six-colour candy pinwheel slowly spins around the middle of the panel.",
           p1=[(48, 0, 24), (48, 36, 0), (0, 40, 40), (26, 0, 48), (48, 40, 32), (48, 14, 0)]),
    _theme("lollipop_swirl", "cute_lollipop_unicorn", "Unicorn",
           "A unicorn pinwheel of pink, aqua, lavender, cream, mint and gold spins around the middle.",
           p1=[(48, 10, 36), (0, 40, 48), (30, 8, 48), (48, 40, 30), (10, 48, 30), (48, 34, 0)]),
    _theme("lollipop_swirl", "cute_lollipop_watermelon", "Watermelon",
           "A watermelon swirl of red, pink, creamy rind, green and lime spins slowly.",
           p1=[(48, 0, 10), (48, 18, 24), (40, 44, 30), (0, 44, 8), (24, 48, 10), (48, 6, 16)]),
    # Sakura breeze
    _theme("sakura_breeze", "cute_sakura_breeze", "Original",
           "Cherry-blossom petals in pinks and white drift down and sideways over a spring sky.",
           p1=[(48, 14, 24), (48, 4, 14), (48, 30, 36), (48, 18, 16)],
           p2=[(3, 10, 22), (4, 12, 4)],
           seed=10),
    _theme("sakura_breeze", "cute_autumn_leaves", "Autumn leaves",
           "Red, orange, amber and gold leaves tumble down over a purple dusk.",
           p1=[(48, 8, 0), (48, 26, 0), (48, 42, 4), (44, 2, 4)],
           p2=[(10, 4, 20), (8, 5, 0)],
           seed=11),
    _theme("sakura_breeze", "cute_confetti_drift", "Confetti",
           "Party confetti in pink, gold, aqua, lime, violet and orange drifts down over a midnight-blue sky.",
           p1=[(48, 0, 28), (48, 40, 0), (0, 44, 48), (20, 48, 0), (36, 0, 48), (48, 16, 0)],
           p2=[(4, 0, 16), (0, 2, 12)],
           seed=12),
    # Sunrise sunset
    _theme("sunrise_sunset", "cute_sunrise_sunset", "Original",
           "Night to dawn to day and back: indigo, magenta, coral, peach and gold rise from the bottom row, with the trackball as the sun.",
           p1=[(4, 0, 18), (18, 0, 36), (40, 0, 30), (48, 8, 10), (48, 22, 6), (48, 36, 4), (10, 28, 48)],
           p2=[(48, 40, 14)]),
    _theme("sunrise_sunset", "cute_tropical_sunset", "Tropical",
           "A tropical day: navy night turns teal, then hot pink, tangerine and gold, into a bright turquoise sky.",
           p1=[(0, 2, 16), (0, 10, 30), (0, 30, 34), (40, 6, 30), (48, 20, 4), (48, 40, 0), (0, 40, 48)],
           p2=[(48, 30, 4)]),
    _theme("sunrise_sunset", "cute_lavender_morning", "Lavender morning",
           "A soft morning over lavender fields: plum, violet, lavender, pink and apricot, then spring green and pale blue.",
           p1=[(6, 0, 14), (20, 0, 40), (36, 10, 48), (48, 14, 30), (48, 32, 18), (36, 48, 20), (26, 38, 48)],
           p2=[(48, 44, 24)]),
    # Aurora dance
    _theme("aurora_dance", "cute_aurora_dance", "Original",
           "Northern-lights curtains in emerald, teal, violet and pink sway across a night sky.",
           p1=[(0, 48, 14), (0, 40, 34), (26, 0, 48), (48, 4, 30)],
           p2=[(0, 1, 6)]),
    _theme("aurora_dance", "cute_aurora_fire_opal", "Fire opal",
           "Opal-coloured curtains of jade, gold, orange and rose sway across the night sky.",
           p1=[(0, 40, 30), (48, 40, 0), (48, 14, 0), (48, 0, 20)],
           p2=[(2, 0, 4)]),
    _theme("aurora_dance", "cute_aurora_unicorn", "Unicorn lights",
           "Aqua, chartreuse, pink and violet light curtains sway across the night sky.",
           p1=[(0, 48, 40), (40, 48, 0), (48, 10, 40), (24, 0, 48)],
           p2=[(1, 0, 6)]),
    # Rainbow caterpillar
    _theme("rainbow_caterpillar", "cute_rainbow_caterpillar", "Original",
           "A pink-headed rainbow caterpillar crawls a winding path through every button on the panel.",
           p1=[(48, 10, 30), (48, 0, 0), (48, 16, 0), (48, 40, 0), (4, 48, 4), (0, 18, 48), (26, 0, 48)],
           p2=[(1, 5, 0)]),
    _theme("rainbow_caterpillar", "cute_paper_dragon", "Paper dragon",
           "A gold-headed paper dragon in red, orange and gold dances its way through every button.",
           p1=[(48, 42, 6), (48, 0, 0), (48, 20, 0), (48, 0, 6), (48, 36, 0), (48, 2, 0), (48, 22, 0)],
           p2=[(4, 0, 0)]),
    _theme("rainbow_caterpillar", "cute_sea_serpent", "Sea serpent",
           "A friendly sea serpent fading from aqua through blue to purple winds around the panel.",
           p1=[(30, 48, 48), (0, 48, 40), (0, 36, 48), (0, 20, 48), (12, 0, 48), (30, 0, 48), (44, 0, 40)],
           p2=[(0, 2, 6)]),
    # Garden bloom
    _theme("garden_bloom", "cute_garden_bloom", "Original",
           "Green buds open into tulips, daffodils, violets and bluebells, then close again, all over the panel.",
           p1=[(48, 2, 4), (48, 40, 0), (28, 0, 48), (48, 20, 8), (6, 14, 48), (48, 0, 32), (44, 44, 36)],
           p2=[(3, 14, 1)],
           seed=14),
    _theme("garden_bloom", "cute_coral_reef", "Coral reef",
           "Coral, orange, purple, green, yellow and blue anemones open and close on a deep-blue reef.",
           p1=[(48, 10, 20), (48, 24, 0), (36, 0, 48), (0, 48, 30), (48, 40, 0), (0, 30, 48), (48, 0, 40)],
           p2=[(0, 4, 16)],
           seed=15),
    _theme("garden_bloom", "cute_cactus_flowers", "Cactus flowers",
           "Desert cacti bloom hot pink, amber, red-orange, yellow, purple and rose, then close again.",
           p1=[(48, 0, 24), (48, 30, 0), (48, 8, 0), (48, 44, 10), (30, 0, 48), (48, 18, 30)],
           p2=[(6, 12, 2)],
           seed=16),
    # Candy cane stripes
    _theme("candy_cane_stripes", "cute_candy_cane_stripes", "Original",
           "Red, mint and pink candy stripes with white between them roll diagonally across the panel.",
           p1=[(48, 0, 4), (44, 40, 40), (6, 48, 22), (44, 40, 40), (48, 6, 26), (44, 40, 40)]),
    _theme("candy_cane_stripes", "cute_circus_tent", "Circus tent",
           "Red, gold and blue big-top stripes with white between them roll across the panel.",
           p1=[(48, 0, 4), (44, 40, 40), (48, 36, 0), (44, 40, 40), (0, 14, 48), (44, 40, 40)]),
    _theme("candy_cane_stripes", "cute_beach_towel", "Beach towel",
           "Aqua, sunshine, pink, green, orange and violet towel stripes roll across the panel.",
           p1=[(0, 40, 48), (48, 40, 0), (48, 8, 20), (0, 48, 20), (48, 20, 0), (20, 0, 48)]),
    # Fruit punch
    _theme("fruit_punch", "cute_fruit_punch", "Original",
           "Mango, pineapple, watermelon, kiwi, passionfruit and blueberry blobs wander the panel and blend where they meet.",
           p1=[(48, 22, 0), (48, 40, 0), (48, 4, 14), (16, 44, 0), (30, 0, 44), (4, 8, 48)],
           seed=16),
    _theme("fruit_punch", "cute_berry_smoothie", "Berry smoothie",
           "Raspberry, blueberry, strawberry, boysenberry and yoghurt-pink blobs swirl and blend.",
           p1=[(48, 0, 20), (16, 0, 48), (48, 6, 6), (40, 0, 40), (48, 22, 32), (8, 4, 36)],
           seed=17),
    _theme("fruit_punch", "cute_galaxy_swirl", "Galaxy swirl",
           "Indigo, magenta, blue, cyan, pink and starlight clouds wander and blend like a galaxy.",
           p1=[(20, 0, 48), (48, 0, 36), (0, 24, 48), (0, 48, 48), (48, 24, 40), (30, 40, 48)],
           seed=18),
    # Bouncy ball
    _theme("bouncy_ball", "cute_bouncy_ball", "Original",
           "A glowing ball bounces around the panel and changes colour every time it hits an edge.",
           p1=[(48, 10, 8), (0, 18, 48), (48, 44, 0), (8, 48, 8), (48, 0, 40), (0, 48, 48), (48, 24, 0)],
           p2=[(0, 0, 2)]),
    _theme("bouncy_ball", "cute_bouncy_beach_ball", "Beach ball",
           "A beach ball bounces over the sand, turning red, yellow, blue, white, green and orange at each wall.",
           p1=[(48, 0, 4), (48, 44, 0), (0, 16, 48), (44, 44, 40), (0, 44, 8), (48, 20, 0)],
           p2=[(5, 3, 0)]),
    _theme("bouncy_ball", "cute_bouncy_bubble", "Soap bubble",
           "A soap bubble bounces around, shimmering pink, sky, lime, peach and lilac at each wall.",
           p1=[(48, 16, 36), (16, 40, 48), (36, 48, 20), (48, 36, 16), (30, 20, 48)],
           p2=[(0, 2, 6)]),
    # Mermaid scales
    _theme("mermaid_scales", "cute_mermaid_scales", "Original",
           "Teal, aqua, purple and pink scales shimmer, with a soft glint sweeping across every few seconds.",
           p1=[(0, 40, 36), (0, 30, 48), (24, 0, 48), (48, 4, 30), (8, 48, 30)],
           p2=[(36, 48, 48)]),
    _theme("mermaid_scales", "cute_dragon_scales", "Dragon scales",
           "Emerald, lime, gold and jade dragon scales shimmer, with a golden glint sweeping across.",
           p1=[(0, 40, 10), (30, 48, 0), (48, 40, 0), (0, 30, 20), (10, 48, 30)],
           p2=[(48, 48, 30)]),
    _theme("mermaid_scales", "cute_rose_gold_scales", "Rose gold",
           "Rose gold, apricot, rose, lilac and champagne scales shimmer, with a soft glint sweeping across.",
           p1=[(48, 18, 14), (48, 30, 10), (48, 6, 20), (40, 20, 48), (48, 36, 24)],
           p2=[(48, 44, 40)]),
    # Starry lullaby
    _theme("starry_lullaby", "cute_starry_lullaby", "Original",
           "Pastel stars twinkle slowly around a glowing trackball moon, with a shooting star now and then.",
           p1=[(48, 18, 30), (48, 44, 12), (12, 30, 48), (12, 48, 30), (34, 20, 48), (48, 28, 16)],
           p2=[(0, 2, 12), (1, 0, 6), (48, 40, 16), (48, 44, 36)],
           seed=19),
    _theme("starry_lullaby", "cute_candy_stars", "Candy stars",
           "Bright candy-coloured stars twinkle around a pale-blue trackball moon in a violet sky.",
           p1=[(48, 0, 24), (0, 44, 48), (48, 40, 0), (30, 0, 48), (0, 48, 20), (48, 16, 0)],
           p2=[(4, 0, 14), (6, 0, 8), (30, 40, 48), (48, 40, 48)],
           seed=20),
    _theme("starry_lullaby", "cute_starfish_lagoon", "Starfish lagoon",
           "Coral, orange, pink, lime, aqua and purple starfish glow in a deep lagoon under a pearl trackball moon.",
           p1=[(48, 14, 8), (48, 30, 0), (48, 6, 20), (30, 48, 10), (0, 48, 36), (40, 10, 48)],
           p2=[(0, 6, 14), (0, 3, 8), (40, 40, 48), (30, 48, 48)],
           seed=21),
    # Paw prints
    _theme("paw_prints", "cute_paw_prints", "Original",
           "Little paw prints in strawberry, honeydew, periwinkle, apricot, lilac and lemonade pad across the panel and back.",
           p1=[(48, 12, 20), (20, 48, 14), (16, 16, 48), (48, 22, 8), (36, 14, 48), (48, 44, 14)],
           p2=[(1, 1, 3)]),
    _theme("paw_prints", "cute_bunny_hops", "Bunny hops",
           "Bunny tracks in pink, spring green, yolk yellow, robin's-egg blue, violet and carrot hop across and back.",
           p1=[(48, 8, 28), (20, 48, 10), (48, 36, 0), (0, 36, 48), (32, 8, 48), (48, 20, 10)],
           p2=[(1, 3, 1)]),
    _theme("paw_prints", "cute_dino_stomps", "Dino stomps",
           "Dinosaur footprints in green, orange, blue, pink, lime and purple stomp across the panel and back.",
           p1=[(10, 48, 0), (48, 20, 0), (0, 30, 48), (48, 0, 30), (40, 48, 0), (30, 0, 48)],
           p2=[(2, 2, 0)]),
)

CUTE_THEMES_BY_NAME: Dict[str, CuteTheme] = {t.name: t for t in CUTE_THEMES}


def find_theme(name: str) -> CuteTheme:
    """Look a theme up by file name, with or without ``cute_`` and ``.lwax``."""
    key = name.strip()
    if key.lower().endswith(".lwax"):
        key = key[: -len(".lwax")]
    for candidate in (key, f"cute_{key}"):
        if candidate in CUTE_THEMES_BY_NAME:
            return CUTE_THEMES_BY_NAME[candidate]
    raise ValueError(f"Unknown cute theme '{name}'. Run `spindoctor ledblinky lwax cute --list`.")
