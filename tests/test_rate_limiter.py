"""Tests for spindoctor.scraper.RateLimiter.

The class is load-bearing for ScreenScraper / TheGamesDB pacing — its
``wait()`` is the only thing keeping a multi-thousand-game fetch-meta
run from getting the cabinet's IP banned. Pin its behaviour so a
refactor can't silently break the throttling.
"""
from __future__ import annotations

import pytest

from spindoctor.scraper import RateLimiter


def test_first_call_does_not_sleep(monkeypatch):
    """``_last_call`` starts at 0.0, so the first ``wait()`` should
    pass straight through — no sleep, no delay.

    Worth pinning because the alternative reading ("first call sleeps
    a full interval") would cost users 1 s per cold start, multiplied
    across thousands of game lookups.
    """
    sleeps: list[float] = []
    monkeypatch.setattr("spindoctor.scraper.time.sleep", sleeps.append)
    # Pin monotonic so we don't accidentally roll past the interval
    # before the assertion fires on a slow CI runner.
    monkeypatch.setattr("spindoctor.scraper.time.monotonic", lambda: 1_000_000.0)

    rl = RateLimiter(calls_per_second=1.0)
    rl.wait()

    assert sleeps == []


def test_back_to_back_calls_sleep_for_full_interval(monkeypatch):
    """Two calls in zero elapsed time → second sleeps the full interval."""
    sleeps: list[float] = []
    monkeypatch.setattr("spindoctor.scraper.time.sleep", sleeps.append)
    # Freeze time so elapsed == 0 between calls.
    monkeypatch.setattr("spindoctor.scraper.time.monotonic", lambda: 5.0)

    rl = RateLimiter(calls_per_second=2.0)  # interval = 0.5 s
    rl.wait()
    rl.wait()

    # Exactly one sleep — the second call — for the full 0.5 s interval.
    assert sleeps == pytest.approx([0.5])


def test_partial_elapsed_sleeps_only_the_remainder(monkeypatch):
    """If half the interval has already elapsed, sleep only the
    remaining half. The throttle must not over-sleep — that turns a
    1 Hz limit into a 0.5 Hz limit in practice."""
    sleeps: list[float] = []
    monkeypatch.setattr("spindoctor.scraper.time.sleep", sleeps.append)

    clock = [10.0]

    def fake_monotonic() -> float:
        return clock[0]

    monkeypatch.setattr("spindoctor.scraper.time.monotonic", fake_monotonic)

    rl = RateLimiter(calls_per_second=1.0)  # interval = 1.0 s
    rl.wait()           # first call: free, _last_call = 10.0
    clock[0] = 10.3     # 0.3 s later → 0.7 s remaining
    rl.wait()

    assert sleeps == pytest.approx([0.7])


def test_elapsed_greater_than_interval_does_not_sleep(monkeypatch):
    """If the caller already paused long enough on its own, ``wait()``
    must be a no-op — pacing is a floor, not a ceiling."""
    sleeps: list[float] = []
    monkeypatch.setattr("spindoctor.scraper.time.sleep", sleeps.append)

    # Start the clock well above zero so the first wait() — which
    # measures against the constructor's _last_call = 0.0 — also reads
    # as "already paused enough" and doesn't sleep. Without this offset
    # the first wait() would sleep one full interval, which is the
    # behaviour pinned by other tests.
    clock = [1_000.0]
    monkeypatch.setattr(
        "spindoctor.scraper.time.monotonic", lambda: clock[0],
    )

    rl = RateLimiter(calls_per_second=1.0)
    rl.wait()
    clock[0] = 2_000.0  # way past the interval
    rl.wait()

    assert sleeps == []


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
