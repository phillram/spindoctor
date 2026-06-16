"""Tests for audit.check_media / _exists zero-byte detection."""
from __future__ import annotations

from pathlib import Path

import pytest

from spindoctor.audit import MediaStatus, check_media, _exists


# ─── _exists ──────────────────────────────────────────────────────────────────

def test_exists_returns_false_when_directory_missing(tmp_path):
    assert _exists(tmp_path / "no_such_dir", "game", {".png"}) is False


def test_exists_returns_true_for_normal_file(tmp_path):
    (tmp_path / "game.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _exists(tmp_path, "game", {".png"}) is True


def test_exists_returns_false_for_zero_byte_file(tmp_path):
    (tmp_path / "game.png").write_bytes(b"")
    assert _exists(tmp_path, "game", {".png"}) is False


def test_exists_checks_all_extensions_before_giving_up(tmp_path):
    (tmp_path / "game.png").write_bytes(b"")   # zero-byte — should not count
    (tmp_path / "game.jpg").write_bytes(b"\xff\xd8")  # real JPEG header
    assert _exists(tmp_path, "game", {".png", ".jpg"}) is True


def test_exists_returns_false_when_only_zero_byte_among_multiple_extensions(tmp_path):
    (tmp_path / "game.png").write_bytes(b"")
    (tmp_path / "game.jpg").write_bytes(b"")
    assert _exists(tmp_path, "game", {".png", ".jpg"}) is False


def test_exists_returns_false_when_no_matching_stem(tmp_path):
    (tmp_path / "other.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _exists(tmp_path, "game", {".png"}) is False


# ─── check_media ──────────────────────────────────────────────────────────────

@pytest.fixture()
def media_base(tmp_path):
    """Return a tmp_path wired up as a HyperSpin Media root for system 'SNES'."""
    sys_dir = tmp_path / "SNES"
    for subdir in (
        "Images/Wheel",
        "Images/Backgrounds",
        "Images/Artwork1",
        "Images/Artwork2",
        "Images/Artwork3",
        "Images/Artwork4",
        "Video",
        "Video/Trailers",
        "Sound",
        "Themes",
    ):
        (sys_dir / subdir).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(path: Path, content: bytes = b"\x89PNG\r\n\x1a\n") -> None:
    path.write_bytes(content)


def test_check_media_all_present(media_base):
    base = media_base / "SNES"
    _write(base / "Images/Wheel/Zelda.png")
    _write(base / "Images/Backgrounds/Zelda.jpg")
    _write(base / "Images/Artwork1/Zelda.png")
    _write(base / "Images/Artwork2/Zelda.png")
    _write(base / "Images/Artwork3/Zelda.png")
    _write(base / "Images/Artwork4/Zelda.png")
    _write(base / "Video/Zelda.mp4")
    _write(base / "Video/Trailers/Zelda.mp4")
    _write(base / "Sound/Zelda.mp3")
    _write(base / "Themes/Zelda.zip")
    status = check_media("Zelda", "SNES", media_base)
    assert status.has_all()
    assert status.missing() == []


def test_check_media_zero_byte_wheel_counts_as_missing(media_base):
    base = media_base / "SNES"
    (base / "Images/Wheel/Zelda.png").write_bytes(b"")  # zero-byte
    status = check_media("Zelda", "SNES", media_base)
    assert status.wheel is False
    assert "wheel" in status.missing()


def test_check_media_zero_byte_video_counts_as_missing(media_base):
    base = media_base / "SNES"
    (base / "Video/Zelda.mp4").write_bytes(b"")
    status = check_media("Zelda", "SNES", media_base)
    assert status.video is False
    assert "video" in status.missing()


def test_check_media_nonzero_wheel_not_missing(media_base):
    base = media_base / "SNES"
    _write(base / "Images/Wheel/Zelda.png")
    status = check_media("Zelda", "SNES", media_base)
    assert status.wheel is True
    assert "wheel" not in status.missing()


def test_check_media_fetch_media_would_redownload_zero_byte(media_base):
    """fetch-media filters on status.missing(); a zero-byte file must appear there."""
    base = media_base / "SNES"
    (base / "Images/Wheel/Zelda.png").write_bytes(b"")
    status = check_media("Zelda", "SNES", media_base)
    assert status.missing()  # gate that fetch-media uses to decide to (re-)download
