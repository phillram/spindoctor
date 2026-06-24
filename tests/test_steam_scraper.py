"""Tests for Steam-specific scraper logic.

Covers _fmt_duration, _hls_duration, _parse_steam, _convert_to_png_inplace,
and SteamClient.fetch_by_app_id duration enrichment — all added as part of
the Steam media downloader feature.
"""
from __future__ import annotations

import pytest

from spindoctor.scraper import _fmt_duration, _hls_duration, _parse_steam


# ─── _fmt_duration ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("secs,expected", [
    (0.0,    "0:00"),
    (59.0,   "0:59"),
    (60.0,   "1:00"),
    (74.0,   "1:14"),
    (74.9,   "1:15"),   # rounds to nearest second
    (3599.0, "59:59"),
    (3600.0, "1:00:00"),
    (3661.0, "1:01:01"),
    (7384.0, "2:03:04"),
])
def test_fmt_duration(secs, expected):
    assert _fmt_duration(secs) == expected


# ─── _hls_duration ────────────────────────────────────────────────────────────


class _FakeHLSSession:
    """Minimal session stub that returns pre-canned responses in order."""

    def __init__(self, responses: list[tuple[int, str]]):
        self._iter = iter(responses)

    def get(self, url, timeout=10):  # noqa: ARG002
        code, text = next(self._iter)
        return _FakeHLSResp(code, text)


class _FakeHLSResp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)


def _master(variant_line: str) -> str:
    return f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n{variant_line}\n"


def _variant(*extinf_secs: float) -> str:
    lines = ["#EXTM3U"]
    for s in extinf_secs:
        lines.append(f"#EXTINF:{s:.3f},")
        lines.append("segment.ts")
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines)


def test_hls_duration_happy_path():
    """Master playlist with a relative variant URL → sum of all #EXTINF values."""
    session = _FakeHLSSession([
        (200, _master("chunklist.m3u8")),
        (200, _variant(30.0, 44.5)),
    ])
    result = _hls_duration("https://cdn/master.m3u8", session)
    assert result == pytest.approx(74.5)


def test_hls_duration_absolute_variant_url():
    """Variant URL starting with http must be used as-is, not prepended with base."""
    session = _FakeHLSSession([
        (200, _master("https://other-cdn.example.com/variant.m3u8")),
        (200, _variant(60.0)),
    ])
    result = _hls_duration("https://cdn/master.m3u8", session)
    assert result == pytest.approx(60.0)


def test_hls_duration_no_variant_line_returns_none():
    """Master playlist with no non-comment lines → None."""
    master = "#EXTM3U\n#EXT-X-INDEPENDENT-SEGMENTS\n"
    session = _FakeHLSSession([(200, master)])
    assert _hls_duration("https://cdn/master.m3u8", session) is None


def test_hls_duration_zero_total_returns_none():
    """All #EXTINF values sum to 0 → None (not a valid duration)."""
    session = _FakeHLSSession([
        (200, _master("chunklist.m3u8")),
        (200, "#EXTM3U\n#EXT-X-ENDLIST\n"),
    ])
    assert _hls_duration("https://cdn/master.m3u8", session) is None


def test_hls_duration_http_error_returns_none():
    """HTTP error on the master playlist request → None, no exception raised."""
    session = _FakeHLSSession([(404, "")])
    assert _hls_duration("https://cdn/master.m3u8", session) is None


def test_hls_duration_malformed_extinf_skipped():
    """Unparseable #EXTINF lines are skipped; valid lines still contribute."""
    variant = "#EXTM3U\n#EXTINF:abc,\nseg1.ts\n#EXTINF:30.0,\nseg2.ts\n#EXT-X-ENDLIST\n"
    session = _FakeHLSSession([
        (200, _master("chunklist.m3u8")),
        (200, variant),
    ])
    result = _hls_duration("https://cdn/master.m3u8", session)
    assert result == pytest.approx(30.0)


# ─── _parse_steam ─────────────────────────────────────────────────────────────


def _steam_data(*, movies=None, screenshots=None, header=None, name="Hades"):
    """Build a minimal Steam appdetails data block."""
    data: dict = {"name": name, "short_description": "A rogue-like dungeon crawler."}
    if movies is not None:
        data["movies"] = movies
    if screenshots is not None:
        data["screenshots"] = screenshots
    if header is not None:
        data["header_image"] = header
    return data


def test_parse_steam_both_mp4_and_hls_present():
    """When a movie entry has both mp4.max and hls_h264, both must appear as
    independent video candidates — not in an if/else where HLS is only offered
    when MP4 is absent."""
    data = _steam_data(movies=[{
        "name": "Hades Trailer",
        "mp4": {"max": "https://cdn/trailer.mp4"},
        "hls_h264": "https://cdn/master.m3u8",
    }])
    meta = _parse_steam("1145360", data)
    video = meta.media_candidates.get("video", [])
    assert len(video) == 2
    formats = {c.format for c in video}
    assert formats == {"mp4", "m3u8"}


def test_parse_steam_mp4_only():
    data = _steam_data(movies=[{
        "name": "Trailer",
        "mp4": {"max": "https://cdn/trailer.mp4"},
    }])
    meta = _parse_steam("1145360", data)
    video = meta.media_candidates.get("video", [])
    assert len(video) == 1
    assert video[0].format == "mp4"


def test_parse_steam_hls_only():
    data = _steam_data(movies=[{
        "name": "Trailer",
        "hls_h264": "https://cdn/master.m3u8",
    }])
    meta = _parse_steam("1145360", data)
    video = meta.media_candidates.get("video", [])
    assert len(video) == 1
    assert video[0].format == "m3u8"


def test_parse_steam_video_aliased_to_trailer_slot():
    """video and trailer slots must share the same candidate list."""
    data = _steam_data(movies=[{
        "name": "Trailer",
        "mp4": {"max": "https://cdn/trailer.mp4"},
    }])
    meta = _parse_steam("1145360", data)
    assert meta.media_candidates.get("video") is meta.media_candidates.get("trailer")


def test_parse_steam_screenshots_become_snap_candidates():
    data = _steam_data(screenshots=[
        {"path_full": "https://cdn/ss1.jpg"},
        {"path_full": "https://cdn/ss2.jpg"},
        {"path_full": "https://cdn/ss3.jpg"},
    ])
    meta = _parse_steam("1145360", data)
    snaps = meta.media_candidates.get("snap", [])
    assert len(snaps) == 3
    assert all(c.format == "jpg" for c in snaps)


def test_parse_steam_header_image_becomes_artwork_and_wheel():
    """A single header image candidate must appear in both artwork and wheel slots."""
    data = _steam_data(header="https://cdn/header.jpg")
    meta = _parse_steam("1145360", data)
    artwork = meta.media_candidates.get("artwork", [])
    wheel = meta.media_candidates.get("wheel", [])
    assert len(artwork) == 1 and len(wheel) == 1
    assert artwork[0] is wheel[0], "artwork and wheel should share the same candidate object"


def test_parse_steam_video_url_set_to_first_candidate():
    data = _steam_data(movies=[
        {"name": "Clip", "mp4": {"max": "https://cdn/clip.mp4"}},
        {"name": "Trailer", "hls_h264": "https://cdn/master.m3u8"},
    ])
    meta = _parse_steam("1145360", data)
    assert meta.video_url == "https://cdn/clip.mp4"


def test_parse_steam_no_movies_empty_video():
    data = _steam_data(movies=[])
    meta = _parse_steam("1145360", data)
    assert meta.media_candidates.get("video", []) == []
    assert meta.video_url == ""


# ─── SteamClient.fetch_by_app_id — duration enrichment ───────────────────────


def test_fetch_by_app_id_sets_duration_secs_on_hls_candidate(monkeypatch):
    """After fetch_by_app_id, HLS candidates must have duration_secs populated;
    MP4 candidates must have duration_secs=None (can't be probed cheaply).
    """
    import json
    from spindoctor.scraper import SteamClient

    api_payload = {
        "1145360": {
            "success": True,
            "data": {
                "name": "Hades",
                "short_description": "",
                "movies": [{
                    "name": "Hades Trailer",
                    "mp4": {"max": "https://cdn/trailer.mp4"},
                    "hls_h264": "https://cdn/master.m3u8",
                }],
                "screenshots": [],
                "header_image": "",
            },
        }
    }

    class _FakeResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
            self.text = ""
        def raise_for_status(self): pass
        def json(self): return self._data

    client = SteamClient()
    monkeypatch.setattr(
        client._session, "get",
        lambda url, **_kw: _FakeResp(api_payload),
    )
    monkeypatch.setattr(
        "spindoctor.scraper._hls_duration",
        lambda url, session: 74.0,
    )

    meta = client.fetch_by_app_id("1145360")
    assert meta is not None

    video_cands = meta.media_candidates.get("video", [])
    assert len(video_cands) == 2

    hls_cand = next(c for c in video_cands if c.format == "m3u8")
    mp4_cand = next(c for c in video_cands if c.format == "mp4")

    assert hls_cand.duration_secs == pytest.approx(74.0)
    assert mp4_cand.duration_secs is None


# ─── _convert_to_png_inplace ──────────────────────────────────────────────────


def test_convert_to_png_inplace_no_op_when_pillow_missing(tmp_path, monkeypatch):
    """Without Pillow the function must silently do nothing."""
    from spindoctor.media import _convert_to_png_inplace

    jpeg_bytes = b"\xff\xd8\xff\xe0fake-jpeg"
    path = tmp_path / "img.png"
    path.write_bytes(jpeg_bytes)

    import builtins
    real_import = builtins.__import__

    def _block_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("Pillow not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_pil)
    _convert_to_png_inplace(path)
    assert path.read_bytes() == jpeg_bytes  # file unchanged


def test_convert_to_png_inplace_no_op_on_corrupt_file(tmp_path):
    """Corrupt/unreadable files must not propagate exceptions."""
    from spindoctor.media import _convert_to_png_inplace
    pytest.importorskip("PIL")

    path = tmp_path / "img.png"
    path.write_bytes(b"this is not an image")
    _convert_to_png_inplace(path)  # must not raise
    assert path.exists()


def test_convert_to_png_inplace_already_png_unchanged(tmp_path):
    """A file that is already valid PNG must be left bit-identical."""
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    from io import BytesIO
    from spindoctor.media import _convert_to_png_inplace

    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(255, 0, 0)).save(buf, format="PNG")
    original = buf.getvalue()

    path = tmp_path / "img.png"
    path.write_bytes(original)
    _convert_to_png_inplace(path)
    assert path.read_bytes() == original


def test_convert_to_png_inplace_converts_jpeg_to_png(tmp_path):
    """JPEG content must be converted to real PNG bytes in-place."""
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    from io import BytesIO
    from spindoctor.media import _convert_to_png_inplace

    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(0, 128, 255)).save(buf, format="JPEG")
    path = tmp_path / "img.png"
    path.write_bytes(buf.getvalue())

    _convert_to_png_inplace(path)

    with Image.open(path) as result:
        assert result.format == "PNG"
