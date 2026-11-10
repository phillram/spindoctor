"""Tests for spindoctor.fileinfo.

Covers the pieces the audit flagged as untested:
- human_size formatting (edge cases)
- _png_dimensions / _jpeg_dimensions (incl. the chunked SOF-walk fix)
- video length without ffprobe: the MP4 movie header wherever it sits
  (incl. the 64-bit extended-size atom path)
- scan_file / find_rom_file / find_media_file
- scan_game / scan_system
- _has_ffprobe + reset_ffprobe_cache (process-wide flag handling)
"""
from __future__ import annotations

import struct
import subprocess

import pytest

from spindoctor import fileinfo
from spindoctor.database import GameEntry


# ─── human_size ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("n,expected", [
    (0, "—"),
    (512, "512.0 B"),
    (1024, "1.0 KB"),
    (1024 * 1024, "1.0 MB"),
    (5 * 1024 * 1024, "5.0 MB"),
    (1024 ** 3, "1.0 GB"),
    (3 * 1024 ** 4, "3.0 TB"),
])
def test_human_size(n, expected):
    assert fileinfo.human_size(n) == expected


# ─── PNG dimensions ──────────────────────────────────────────────────────────


def _make_png_bytes(width: int, height: int) -> bytes:
    """Minimal PNG header sufficient for _png_dimensions."""
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: length(4) + type(4) + width(4) + height(4) + ...
    ihdr_len = struct.pack(">I", 13)
    ihdr_type = b"IHDR"
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    crc = b"\x00\x00\x00\x00"  # _png_dimensions doesn't check CRC
    return sig + ihdr_len + ihdr_type + ihdr_data + crc


def test_png_dimensions(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(_make_png_bytes(640, 480))
    assert fileinfo._png_dimensions(p) == (640, 480)


def test_png_dimensions_rejects_non_png(tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(b"not a png at all..." + b"\x00" * 32)
    with pytest.raises(ValueError):
        fileinfo._png_dimensions(p)


# ─── JPEG dimensions ─────────────────────────────────────────────────────────


def _make_jpeg_bytes(width: int, height: int, *, comment_padding: int = 0) -> bytes:
    """Build a synthetic JPEG with one COM segment (optional padding) + SOF0.

    ``comment_padding`` pushes the SOF marker past the given offset so we
    can exercise the chunked-read fix without slurping the whole file.
    """
    out = bytearray(b"\xff\xd8")  # SOI
    if comment_padding > 0:
        # COM segment: marker(2) + length(2) + payload. Length includes
        # the 2 length bytes themselves. Max segment length is 65535.
        remaining = comment_padding
        while remaining > 0:
            chunk = min(remaining, 0xFFFD)
            out += b"\xff\xfe"  # COM
            out += struct.pack(">H", chunk + 2)
            out += b"\x00" * chunk
            remaining -= chunk
    # SOF0 marker (baseline JPEG): FF C0, length(2), precision(1),
    # height(2), width(2), components(1)
    out += b"\xff\xc0"
    out += struct.pack(">H", 8 + 3)   # length covers prec/h/w/components(3)
    out += b"\x08"                     # precision
    out += struct.pack(">H", height)
    out += struct.pack(">H", width)
    out += b"\x03"                     # number of components
    out += b"\xff\xd9"                 # EOI
    return bytes(out)


def test_jpeg_dimensions_small_file(tmp_path):
    p = tmp_path / "tiny.jpg"
    p.write_bytes(_make_jpeg_bytes(320, 240))
    assert fileinfo._jpeg_dimensions(p) == (320, 240)


def test_jpeg_dimensions_with_sof_beyond_64kb(tmp_path):
    """The previous 65 536-byte read would return ValueError here.

    Builds a JPEG with ~96 KiB of padding before SOF0 so the marker sits
    past the legacy buffer boundary. The chunked walk must still find it.
    """
    p = tmp_path / "progressive.jpg"
    p.write_bytes(_make_jpeg_bytes(4096, 2160, comment_padding=96 * 1024))
    assert fileinfo._jpeg_dimensions(p) == (4096, 2160)


def test_jpeg_dimensions_rejects_non_jpeg(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"PNG\x00" + b"\x00" * 32)
    with pytest.raises(ValueError):
        fileinfo._jpeg_dimensions(p)


# ─── video length without ffprobe ────────────────────────────────────────────
#
# With no ffprobe, the length comes from the movie header (``moov`` → ``mvhd``).
# Many encoders write ``moov`` after the media data (``mdat``), so it can sit
# anywhere in the file, megabytes in.


def _atom(name: bytes, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return struct.pack(">I", size) + name + payload


def _atom64(name: bytes, payload: bytes) -> bytes:
    """64-bit extended-size box (size=1 sentinel + 8-byte length)."""
    total = 16 + len(payload)
    return struct.pack(">I", 1) + name + struct.pack(">Q", total) + payload


def _mvhd_v0(timescale: int, duration: int) -> bytes:
    # 4 bytes version+flags, 4 bytes ctime, 4 bytes mtime, 4 timescale,
    # 4 duration, then 80 bytes of trailing metadata we don't care about.
    return (
        b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00"
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration)
        + b"\x00" * 80
    )


def _mvhd_v1(timescale: int, duration: int) -> bytes:
    return (
        b"\x01\x00\x00\x00"
        + b"\x00" * 16  # 8-byte ctime + 8-byte mtime
        + struct.pack(">I", timescale)
        + struct.pack(">Q", duration)
        + b"\x00" * 80
    )


_FTYP = _atom(b"ftyp", b"isom" + b"\x00" * 12)
_PAST_FIRST_MB = 3 * 1024 * 1024


def _moov(seconds: float = 184.0, timescale: int = 600) -> bytes:
    mvhd = _atom(b"mvhd", _mvhd_v0(timescale=timescale, duration=int(seconds * timescale)))
    return _atom(b"moov", mvhd + _atom(b"trak", b"\x00" * 32))


def _clip(path, moov: bytes, *, mdat_bytes: int = 4096, moov_first: bool = False,
          mdat64: bool = False):
    """ftyp, then mdat and moov in either order."""
    mdat = (_atom64 if mdat64 else _atom)(b"mdat", b"\x00" * mdat_bytes)
    path.write_bytes(_FTYP + (moov + mdat if moov_first else mdat + moov))
    return path


@pytest.fixture
def no_ffprobe(monkeypatch):
    """As on a PC with no ffprobe (the flag is cached per process)."""
    monkeypatch.setattr(fileinfo, "_ffprobe_ok", False)


@pytest.mark.parametrize("version,timescale,duration,seconds", [
    (0, 1000, 5000, 5.0),
    (1, 600, 18_000, 30.0),     # version 1 carries a 64-bit duration
    (0, 0, 42, None),           # no timescale: no length
])
def test_video_length_from_movie_header(tmp_path, no_ffprobe, version, timescale, duration, seconds):
    mvhd = (_mvhd_v1 if version else _mvhd_v0)(timescale=timescale, duration=duration)
    clip = _clip(tmp_path / "clip.mp4", _atom(b"moov", _atom(b"mvhd", mvhd)))
    assert fileinfo._video_duration(clip) == seconds


def test_video_length_handles_64bit_box_size(tmp_path, no_ffprobe):
    """The size=1 sentinel uses a trailing 8-byte length field."""
    mvhd = _atom(b"mvhd", _mvhd_v0(timescale=100, duration=900))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(_FTYP + _atom64(b"moov", mvhd))
    assert fileinfo._video_duration(clip) == 9.0


def test_video_length_none_for_garbage(tmp_path, no_ffprobe):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"not an mp4 at all")
    assert fileinfo._video_duration(clip) is None


@pytest.mark.parametrize("mdat64", [False, True])
def test_video_length_found_after_large_media_data(tmp_path, no_ffprobe, mdat64):
    clip = _clip(tmp_path / "clip.mp4", _moov(184.0), mdat_bytes=_PAST_FIRST_MB, mdat64=mdat64)
    assert fileinfo._video_duration(clip) == 184.0


def test_scan_file_shows_length_when_movie_header_is_at_the_end(tmp_path, no_ffprobe):
    """What ``inspect`` and ``audit --detailed`` show for such a clip."""
    clip = _clip(tmp_path / "Game.mp4", _moov(184.0), mdat_bytes=_PAST_FIRST_MB)
    detail = fileinfo.scan_file(clip, "video")
    assert detail.duration_seconds == 184.0
    assert detail.duration_human == "3:04"


@pytest.mark.parametrize("name", ["clip.mp4", "clip.M4V", "clip.mov"])
@pytest.mark.parametrize("moov_first", [True, False])
def test_video_length_for_each_iso_container(tmp_path, no_ffprobe, name, moov_first):
    clip = _clip(tmp_path / name, _moov(35.0), moov_first=moov_first)
    assert fileinfo._video_duration(clip) == 35.0


@pytest.mark.parametrize("version", [0, 1])
def test_video_length_unknown_duration_is_none(tmp_path, no_ffprobe, version):
    """All ones means "length unknown", not a clip of 80 days or more."""
    if version == 0:
        mvhd = _mvhd_v0(timescale=600, duration=0xFFFFFFFF)
    else:
        mvhd = _mvhd_v1(timescale=600, duration=0xFFFFFFFFFFFFFFFF)
    clip = _clip(tmp_path / "clip.mp4", _atom(b"moov", _atom(b"mvhd", mvhd)))
    assert fileinfo._video_duration(clip) is None


def test_video_length_none_when_download_was_cut_short(tmp_path, no_ffprobe):
    """The media data claims more bytes than the file holds; no moov follows."""
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(_FTYP + struct.pack(">I", 50_000_000) + b"mdat" + b"\x00" * 1000)
    assert fileinfo._video_duration(clip) is None


def test_video_length_reads_headers_not_media_data(tmp_path, no_ffprobe, monkeypatch):
    """Box headers and the movie header only: ``audit --detailed`` reads
    thousands of clips, so the media data is skipped with a seek."""
    import builtins

    clip = _clip(tmp_path / "clip.mp4", _moov(184.0), mdat_bytes=_PAST_FIRST_MB)
    real_open = builtins.open
    sizes = []

    class _Counted:
        def __init__(self, fh):
            self._fh = fh

        def read(self, n=-1):
            data = self._fh.read(n)
            sizes.append(len(data))
            return data

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()

    def counting_open(file, *args, **kwargs):
        fh = real_open(file, *args, **kwargs)
        return _Counted(fh) if str(file) == str(clip) else fh

    monkeypatch.setattr(builtins, "open", counting_open)
    assert fileinfo._video_duration(clip) == 184.0
    assert 0 < sum(sizes) < 4096


# ─── ffprobe cache lifecycle ─────────────────────────────────────────────────


def test_has_ffprobe_caches_and_resets(monkeypatch):
    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1
        class _R: pass
        return _R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    fileinfo.reset_ffprobe_cache()
    assert fileinfo._has_ffprobe() is True
    assert fileinfo._has_ffprobe() is True
    assert calls["n"] == 1  # second call hit the cache

    fileinfo.reset_ffprobe_cache()

    def boom(*a, **k):
        raise FileNotFoundError("ffprobe")
    monkeypatch.setattr(subprocess, "run", boom)
    assert fileinfo._has_ffprobe() is False
    # Reset so other tests in the suite aren't poisoned.
    fileinfo.reset_ffprobe_cache()


# ─── scan_file ──────────────────────────────────────────────────────────────


def test_scan_file_returns_unknown_for_missing(tmp_path):
    detail = fileinfo.scan_file(tmp_path / "nope.png", media_type="wheel")
    assert detail.exists is False
    assert detail.size_bytes == 0


def test_scan_file_captures_size_and_dimensions_for_png(tmp_path):
    p = tmp_path / "w.png"
    p.write_bytes(_make_png_bytes(128, 64))
    detail = fileinfo.scan_file(p, media_type="wheel")
    assert detail.exists is True
    assert detail.size_bytes > 0
    assert (detail.width, detail.height) == (128, 64)
    assert detail.size_human.endswith("B") or detail.size_human.endswith("KB")


def test_scan_file_skips_dimensions_for_corrupt_image(tmp_path):
    """A bogus PNG must not raise — width/height stay None."""
    p = tmp_path / "bad.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nNOT-AN-IHDR")
    detail = fileinfo.scan_file(p, media_type="wheel")
    assert detail.exists is True
    assert detail.width is None
    assert detail.height is None


# ─── find_rom_file / find_media_file ─────────────────────────────────────────


def test_find_rom_file_locates_zip(tmp_path):
    sysdir = tmp_path / "NES"
    sysdir.mkdir()
    (sysdir / "Mario.zip").write_bytes(b"x")
    d = fileinfo.find_rom_file("Mario", "NES", tmp_path)
    assert d.exists is True
    assert d.path.suffix == ".zip"


def test_find_rom_file_returns_canonical_when_missing(tmp_path):
    (tmp_path / "NES").mkdir()
    d = fileinfo.find_rom_file("MissingGame", "NES", tmp_path)
    assert d.exists is False
    assert d.path.parent == tmp_path / "NES"


def test_find_media_file_locates_wheel_png(tmp_path):
    media_dir = tmp_path / "Media" / "NES" / "Images" / "Wheel"
    media_dir.mkdir(parents=True)
    (media_dir / "Mario.png").write_bytes(_make_png_bytes(10, 10))
    d = fileinfo.find_media_file("Mario", "NES", "wheel", tmp_path / "Media")
    assert d.exists is True
    assert d.path.suffix == ".png"


def test_find_media_file_falls_back_to_canonical_path(tmp_path):
    # No file on disk → expected canonical path returned, exists=False.
    d = fileinfo.find_media_file("Nope", "NES", "wheel", tmp_path / "Media")
    assert d.exists is False
    assert d.path.suffix in (".png", ".jpg", ".jpeg", ".gif")


def test_find_media_file_treats_theme_folder_as_present(tmp_path):
    """A theme can be either <name>.zip or a folder named <name>/."""
    themes_root = tmp_path / "Media" / "NES" / "Themes"
    (themes_root / "Mario").mkdir(parents=True)
    (themes_root / "Mario" / "background.png").write_bytes(b"x")
    d = fileinfo.find_media_file("Mario", "NES", "theme", tmp_path / "Media")
    assert d.exists is True
    assert d.path.is_dir()
    assert d.extension == "<dir>"


# ─── scan_game / scan_system ────────────────────────────────────────────────


def test_scan_game_attaches_db_entry(tmp_path):
    sysdir = tmp_path / "roms" / "NES"
    sysdir.mkdir(parents=True)
    (sysdir / "Mario.zip").write_bytes(b"x")
    entry = GameEntry(
        name="Mario", description="Super Mario Bros.",
        year="1985", manufacturer="Nintendo",
        genre="Platformer", rating="E", players="2 simultaneous",
    )
    report = fileinfo.scan_game(
        "Mario", "NES", tmp_path / "roms", tmp_path / "Media",
        db_entry=entry,
    )
    assert report.db_name == "Mario"
    assert report.db_year == "1985"
    assert report.rom is not None and report.rom.exists is True
    # media[*] entries are FileDetail with exists=False for every media type
    assert all(not d.exists for d in report.media.values())


def test_scan_system_iterates_all_games(tmp_path):
    sysdir = tmp_path / "roms" / "NES"
    sysdir.mkdir(parents=True)
    (sysdir / "Mario.zip").write_bytes(b"x")
    games = {
        "Mario": GameEntry(name="Mario"),
        "Luigi": GameEntry(name="Luigi"),
    }
    reports = fileinfo.scan_system(
        "NES", tmp_path / "roms", tmp_path / "Media", games,
    )
    assert {r.game_name for r in reports} == {"Mario", "Luigi"}


def test_game_file_report_missing_and_present_media(tmp_path):
    media_dir = tmp_path / "Media" / "NES" / "Images" / "Wheel"
    media_dir.mkdir(parents=True)
    (media_dir / "Mario.png").write_bytes(_make_png_bytes(10, 10))
    report = fileinfo.scan_game(
        "Mario", "NES", tmp_path / "roms", tmp_path / "Media",
    )
    assert "wheel" in report.present_media()
    assert "video" in report.missing_media()
