"""Tests for audit.check_media / _exists zero-byte detection."""
from __future__ import annotations
from tests.helpers import write_bytes as _write_bytes

from spindoctor import audit
from spindoctor import fileinfo
from spindoctor import medialink

from pathlib import Path

import pytest

from spindoctor.audit import MediaIndex, check_media, _exists


# ─── _exists ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "files,stem,extensions,expected",
    [
        pytest.param(None, "game", {".png"}, False,
                     id="directory-missing"),
        pytest.param({"game.png": b"\x89PNG\r\n\x1a\n"}, "game", {".png"}, True,
                     id="normal-file"),
        pytest.param({"game.png": b""}, "game", {".png"}, False,
                     id="zero-byte-file"),
        pytest.param({"game.png": b"", "game.jpg": b"\xff\xd8"}, "game",
                     {".png", ".jpg"}, True,
                     id="falls-through-to-real-second-extension"),
        pytest.param({"game.png": b"", "game.jpg": b""}, "game",
                     {".png", ".jpg"}, False,
                     id="all-extensions-zero-byte"),
        pytest.param({"other.png": b"\x89PNG\r\n\x1a\n"}, "game", {".png"}, False,
                     id="no-matching-stem"),
    ],
)
def test_exists(tmp_path, files, stem, extensions, expected):
    if files is None:
        directory = tmp_path / "no_such_dir"
    else:
        directory = tmp_path
        for name, content in files.items():
            (tmp_path / name).write_bytes(content)
    assert _exists(directory, stem, extensions) is expected


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


@pytest.mark.parametrize(
    "slot,rel_path",
    [
        pytest.param("wheel", "Images/Wheel/Zelda.png", id="wheel"),
        pytest.param("video", "Video/Zelda.mp4", id="video"),
    ],
)
def test_check_media_zero_byte_counts_as_missing(media_base, slot, rel_path):
    base = media_base / "SNES"
    (base / rel_path).write_bytes(b"")  # zero-byte
    status = check_media("Zelda", "SNES", media_base)
    assert getattr(status, slot) is False
    assert slot in status.missing()


def test_check_media_nonzero_wheel_not_missing(media_base):
    base = media_base / "SNES"
    _write(base / "Images/Wheel/Zelda.png")
    status = check_media("Zelda", "SNES", media_base)
    assert status.wheel is True
    assert "wheel" not in status.missing()


def test_media_index_matches_individual_checks(media_base):
    base = media_base / "SNES"
    _write(base / "Images/Wheel/Zelda.jpg")
    _write(base / "Images/Artwork4/Zelda.png", b"")
    _write(base / "Themes/Zelda.zip")
    (base / "Themes" / "Mario").mkdir()
    _write(base / "Images/Wheel/CON_.png")
    index = MediaIndex("SNES", media_base)
    for name in ("Zelda", "Mario", "CON", "Absent"):
        assert index.check(name) == check_media(name, "SNES", media_base)
    assert index.check("zelda").wheel
    assert not index.check("zelda").fade


def test_media_index_looks_up_case_insensitive_names_and_extensions(media_base):
    _write(media_base / "SNES" / "Images/Wheel/ZELDA.PNG")
    _write(media_base / "SNES" / "Themes/ZELDA.ZIP")
    status = MediaIndex("SNES", media_base).check("zelda")
    assert status.wheel and status.theme


def test_media_index_does_not_touch_disk_per_game(media_base, monkeypatch):
    _write(media_base / "SNES" / "Images/Wheel/Zelda.png")
    index = MediaIndex("SNES", media_base)
    def unexpected_stat(*args, **kwargs):
        pytest.fail("indexed media lookup must not stat files")
    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "stat", unexpected_stat)
        assert index.check("Zelda").wheel
        assert not index.check("Missing").wheel


def test_media_index_is_an_operation_local_snapshot(media_base):
    first = MediaIndex("SNES", media_base)
    _write(media_base / "SNES" / "Images/Wheel/Zelda.png")
    assert not first.check("Zelda").wheel
    assert MediaIndex("SNES", media_base).check("Zelda").wheel


def test_media_checks_ignore_directories_named_like_images(media_base):
    (media_base / "SNES" / "Images/Wheel/Zelda.png").mkdir()
    assert not check_media("Zelda", "SNES", media_base).wheel
    assert not MediaIndex("SNES", media_base).check("Zelda").wheel


def test_media_index_handles_missing_system(media_base):
    assert MediaIndex("Missing", media_base).check("Zelda").present() == []


def test_fade_discovery_and_safe_media_names(config_home, tmp_path):
    name = "Metal Gear: VR"
    stem = "Metal Gear VR"
    media = tmp_path / "Media"
    _write_bytes(media / "MAME" / "Images" / "Artwork4" / f"{stem}.png")
    assert audit.check_media(name, "MAME", media).fade
    assert fileinfo.find_media_file(name, "MAME", "fade", media).exists
    assert medialink.remove_target(media, "MAME", name) == 1
