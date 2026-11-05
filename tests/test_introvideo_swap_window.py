"""The logon swap waits as long as the intro clip HyperSpin is playing.

HyperSpin holds ``intro_video_target`` open for the clip's whole length, so
a fixed 3-minute retry window failed on every boot whose clip ran longer.
The swap now reads the clip's length from its MP4 movie header and retries
that long (plus a margin, capped), and ``doctor`` flags clips it can't wait
out. Every file here is built in a temp dir; nothing sleeps for real.
"""
from __future__ import annotations

import random
import shutil
import struct
import time

import pytest

from spindoctor import health
from spindoctor import introvideo as iv
from spindoctor.config import Config


def _box(kind: bytes, payload: bytes, large: bool = False) -> bytes:
    if large:
        return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _mvhd(seconds: float, version: int = 0, timescale: int = 600, duration=None) -> bytes:
    ticks = int(seconds * timescale) if duration is None else duration
    if version == 1:
        head = struct.pack(">B3xQQIQ", 1, 0, 0, timescale, ticks)
    else:
        head = struct.pack(">B3xIIII", 0, 0, 0, timescale, ticks)
    return _box(b"mvhd", head + b"\0" * 80)


def _mp4(path, seconds, *, version=0, moov_first=False, large_mdat=False, timescale=600, duration=None):
    """A minimal MP4: ftyp, mdat and a moov holding only the movie header."""
    ftyp = _box(b"ftyp", b"isom\0\0\x02\0isomiso2mp41")
    mdat = _box(b"mdat", b"\0" * 4096, large=large_mdat)
    moov = _box(b"moov", _mvhd(seconds, version, timescale, duration) + _box(b"trak", b"\0" * 32))
    path.write_bytes(ftyp + (moov + mdat if moov_first else mdat + moov))
    return path


@pytest.fixture
def pool(tmp_path):
    pool = tmp_path / "Intro Videos"
    pool.mkdir()
    cfg = Config()
    cfg.intro_randomizer_dir = str(pool)
    cfg.intro_video_target = str(tmp_path / "Intro.mp4")
    return cfg, pool, tmp_path / "Intro.mp4"


# ── reading the length ────────────────────────────────────────────────────────


@pytest.mark.parametrize("version", [0, 1])
@pytest.mark.parametrize("moov_first", [False, True])
def test_duration_from_the_movie_header(tmp_path, version, moov_first):
    clip = _mp4(tmp_path / "clip.mp4", 269.5, version=version, moov_first=moov_first)
    assert iv.video_duration_seconds(clip) == 269.5   # 161,700 ticks at 600 per second


def test_duration_skips_a_64_bit_mdat_and_reads_mov(tmp_path):
    assert iv.video_duration_seconds(_mp4(tmp_path / "a.MOV", 184.0, large_mdat=True)) == 184.0
    assert iv.video_duration_seconds(_mp4(tmp_path / "b.m4v", 35.0)) == 35.0


def test_duration_is_none_when_it_cant_be_read(tmp_path):
    assert iv.video_duration_seconds(tmp_path / "missing.mp4") is None
    (tmp_path / "junk.mp4").write_bytes(b"a" * 100)
    assert iv.video_duration_seconds(tmp_path / "junk.mp4") is None
    (tmp_path / "empty.mp4").write_bytes(b"")
    assert iv.video_duration_seconds(tmp_path / "empty.mp4") is None
    # Other containers aren't parsed.
    _mp4(tmp_path / "clip.avi", 60)
    assert iv.video_duration_seconds(tmp_path / "clip.avi") is None
    # "Unknown" duration and a zero timescale.
    assert iv.video_duration_seconds(_mp4(tmp_path / "u.mp4", 0, duration=0xFFFFFFFF)) is None
    assert iv.video_duration_seconds(_mp4(tmp_path / "z.mp4", 0, timescale=0, duration=5)) is None
    # A moov box with no mvhd.
    (tmp_path / "nomvhd.mp4").write_bytes(_box(b"moov", _box(b"trak", b"\0" * 8)))
    assert iv.video_duration_seconds(tmp_path / "nomvhd.mp4") is None


# ── how long the swap waits ───────────────────────────────────────────────────


def test_retry_window_covers_the_clip_in_the_target(tmp_path):
    target = _mp4(tmp_path / "Intro.mp4", 269.0)
    # (269 s + 60 s margin) / 2 s = 164.5 -> 165 tries, past the old fixed 90.
    assert iv.swap_retry_attempts(target) == 165
    # A short clip keeps the 3-minute floor.
    assert iv.swap_retry_attempts(_mp4(tmp_path / "short.mp4", 10.0)) == iv.SWAP_RETRY_ATTEMPTS
    # An hour-long file is capped at 30 minutes.
    assert iv.swap_retry_attempts(_mp4(tmp_path / "long.mp4", 3600.0)) == 900


def test_retry_window_falls_back_to_the_longest_pool_clip(pool):
    _cfg, pool_dir, target = pool
    _mp4(pool_dir / "short.mp4", 20.0)
    (pool_dir / iv.DISABLED_SUBFOLDER).mkdir()
    _mp4(pool_dir / iv.DISABLED_SUBFOLDER / "long.mp4", 221.0)
    # The target can't be read (missing here; locked on a cabinet).
    assert iv.swap_retry_attempts(target, pool_dir) == 141     # (221 + 60) / 2
    assert iv.swap_retry_attempts(target) == iv.SWAP_RETRY_ATTEMPTS
    target.write_bytes(b"locked or not an MP4")
    assert iv.swap_retry_attempts(target, pool_dir) == 141


def _locked_copies(monkeypatch, unlock_after=None):
    """copy2 fails with a sharing violation (until call *unlock_after*); sleep is counted."""
    real_copy2 = shutil.copy2
    calls = {"copy": 0, "sleep": 0}

    def copy2(src, dst):
        calls["copy"] += 1
        if unlock_after is None or calls["copy"] <= unlock_after:
            raise PermissionError(32, "The process cannot access the file")
        return real_copy2(src, dst)

    monkeypatch.setattr(shutil, "copy2", copy2)
    monkeypatch.setattr(time, "sleep", lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1))
    return calls


def test_swap_outlasts_a_clip_longer_than_three_minutes(pool, monkeypatch):
    cfg, pool_dir, target = pool
    _mp4(pool_dir / "next.mp4", 30.0)
    _mp4(target, 269.0)                      # the clip HyperSpin is playing
    calls = _locked_copies(monkeypatch, unlock_after=120)   # free after ~4 minutes
    result = iv.swap_video(cfg, apply=True, rng=random.Random(1))
    assert result.picked == "next.mp4"
    assert calls["copy"] == 121 and calls["sleep"] == 120
    assert iv.video_duration_seconds(target) == 30.0


def test_swap_gives_up_after_the_clip_length_plus_margin(pool, monkeypatch):
    cfg, pool_dir, target = pool
    _mp4(pool_dir / "next.mp4", 30.0)
    _mp4(target, 269.0)
    calls = _locked_copies(monkeypatch)
    with pytest.raises(iv.IntroVideoError, match="after 165 attempts"):
        iv.swap_video(cfg, apply=True, rng=random.Random(1))
    assert calls["copy"] == 165 and calls["sleep"] == 164


# ── doctor ────────────────────────────────────────────────────────────────────


def _child(check, name):
    return next(c for c in check.children if c.name == name)


def test_doctor_reports_the_longest_clip_and_the_wait(pool):
    cfg, pool_dir, _target = pool
    _mp4(pool_dir / "a.mp4", 35.0)
    _mp4(pool_dir / "Long Intro.mp4", 269.0)
    result = health.check_intro_video(cfg)
    child = _child(result, "clip length")
    assert child.status == health.Status.OK
    assert child.detail == "longest clip 4:29 (Long Intro.mp4); the logon swap waits up to 5:29 for it"
    assert result.status == health.Status.OK


def test_doctor_warns_about_a_clip_too_long_to_wait_out(pool):
    cfg, pool_dir, _target = pool
    _mp4(pool_dir / "a.mp4", 35.0)
    _mp4(pool_dir / "Concert.mp4", 45 * 60.0)
    result = health.check_intro_video(cfg)
    child = _child(result, "clip length")
    assert child.status == health.Status.WARN
    assert "Concert.mp4 (45:00)" in child.detail and "at most 30:00" in child.detail
    assert child.fix == 'spindoctor introvideo remove "Concert.mp4" --apply'
    assert result.status == health.Status.WARN


def test_doctor_notes_clips_whose_length_it_cant_read(pool):
    cfg, pool_dir, _target = pool
    _mp4(pool_dir / "a.mp4", 35.0)
    (pool_dir / "old.avi").write_bytes(b"RIFF....AVI ")
    child = _child(health.check_intro_video(cfg), "clip length (unread)")
    assert child.status == health.Status.INFO
    assert "old.avi" in child.detail and "--delay-minutes" in child.fix
