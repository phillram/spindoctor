"""Tests for spindoctor.scraper.RateLimiter.

The class is load-bearing for ScreenScraper / TheGamesDB pacing — its
``wait()`` is the only thing keeping a multi-thousand-game fetch-meta
run from getting the cabinet's IP banned. Pin its behaviour so a
refactor can't silently break the throttling.
"""
from __future__ import annotations

import pytest

from spindoctor.scraper import RateLimiter


@pytest.mark.parametrize(
    "rate,start,deltas,expected_sleeps",
    [
        # _last_call starts at 0.0, so with the clock far above the interval
        # the first wait() passes straight through — the alternative reading
        # ("first call sleeps a full interval") would cost users 1 s per cold
        # start, multiplied across thousands of game lookups.
        pytest.param(1.0, 1_000_000.0, [], [],
                     id="first-call-does-not-sleep"),
        # Two calls in zero elapsed time → the second sleeps the full
        # interval (2 calls/s → 0.5 s).
        pytest.param(2.0, 5.0, [0.0], [0.5],
                     id="back-to-back-sleeps-full-interval"),
        # 0.3 s of the 1 s interval already elapsed → sleep only the
        # remaining 0.7 s. Over-sleeping would turn a 1 Hz limit into a
        # 0.5 Hz limit in practice.
        pytest.param(1.0, 10.0, [0.3], [0.7],
                     id="partial-elapsed-sleeps-remainder"),
        # Caller already paused well past the interval on its own → wait()
        # is a no-op: pacing is a floor, not a ceiling.
        pytest.param(1.0, 1_000.0, [1_000.0], [],
                     id="elapsed-beyond-interval-does-not-sleep"),
    ],
)
def test_wait_pacing(monkeypatch, rate, start, deltas, expected_sleeps):
    sleeps: list[float] = []
    monkeypatch.setattr("spindoctor.scraper.time.sleep", sleeps.append)
    # Controllable clock: start well above zero so the first wait() — which
    # measures against the constructor's _last_call = 0.0 — reads as
    # "already paused enough" and doesn't sleep a spurious full interval.
    clock = [start]
    monkeypatch.setattr("spindoctor.scraper.time.monotonic", lambda: clock[0])

    rl = RateLimiter(calls_per_second=rate)
    rl.wait()
    for delta in deltas:
        clock[0] += delta
        rl.wait()

    assert sleeps == pytest.approx(expected_sleeps)


def test_interval_derived_from_calls_per_second():
    """Spot-check the math: 4 calls/s = 0.25 s interval, 0.5 calls/s = 2 s."""
    assert RateLimiter(calls_per_second=4.0)._interval == pytest.approx(0.25)
    assert RateLimiter(calls_per_second=0.5)._interval == pytest.approx(2.0)
    assert RateLimiter(calls_per_second=1.0)._interval == pytest.approx(1.0)


def test_default_rate_is_one_per_second():
    """Pin the default. Both ScreenScraper and TheGamesDB documentation
    recommend ≤1 req/s for anonymous use; if a future refactor lifts
    the default to e.g. 5/s, callers relying on the polite default
    would silently start getting throttled remotely."""
    assert RateLimiter()._interval == pytest.approx(1.0)
