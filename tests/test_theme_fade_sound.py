"""Theme / fade / sound media fetching across scraper, media maps, and CLI."""
from __future__ import annotations

from spindoctor.config import Config, MEDIA_TYPES
from spindoctor.media import MEDIA_DIR_MAP, MEDIA_EXTENSIONS, MediaDownloader
from spindoctor.scraper import (
    SCREENSCRAPER_MEDIA_TYPES,
    GameMetadata,
    _parse_screenscraper,
)


# ─── MEDIA_TYPES list ─────────────────────────────────────────────────────────


def test_media_types_includes_fade_after_snap_before_video():
    idx = {t: i for i, t in enumerate(MEDIA_TYPES)}
    assert "fade" in idx
    assert idx["snap"] < idx["fade"] < idx["video"]


def test_media_types_complete_set():
    assert set(MEDIA_TYPES) == {
        "wheel", "background", "artwork", "title", "snap",
        "fade", "video", "trailer", "sound", "theme",
    }


# ─── path / extension maps ────────────────────────────────────────────────────


def test_fade_path_and_extension():
    assert MEDIA_DIR_MAP["fade"] == ("Images", "Artwork4")
    assert MEDIA_EXTENSIONS["fade"] == ".png"


def test_theme_path_and_extension():
    assert MEDIA_DIR_MAP["theme"] == ("Themes",)
    assert MEDIA_EXTENSIONS["theme"] == ".zip"


def test_sound_path_and_extension():
    assert MEDIA_DIR_MAP["sound"] == ("Sound",)
    assert MEDIA_EXTENSIONS["sound"] == ".mp3"


def test_media_path_for_new_types(tmp_path):
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)

    fade = dl.media_path("MAME", "1942", "fade")
    assert fade == tmp_path / "Media" / "MAME" / "Images" / "Artwork4" / "1942.png"

    theme = dl.media_path("MAME", "1942", "theme")
    assert theme == tmp_path / "Media" / "MAME" / "Themes" / "1942.zip"

    sound = dl.media_path("MAME", "1942", "sound")
    assert sound == tmp_path / "Media" / "MAME" / "Sound" / "1942.mp3"


# ─── ScreenScraper response parsing ───────────────────────────────────────────


def test_screenscraper_media_type_mapping_includes_theme_fade_sound():
    assert "theme-hs" in SCREENSCRAPER_MEDIA_TYPES["theme"]
    assert "fanart" in SCREENSCRAPER_MEDIA_TYPES["fade"]
    assert "bgmusic" in SCREENSCRAPER_MEDIA_TYPES["sound"]


def test_parse_screenscraper_extracts_theme_fade_sound():
    jeu = {
        "id": "100",
        "noms": [{"langue": "en", "text": "1942"}],
        "medias": [
            {"type": "theme-hs", "url": "https://ss/1942-theme.zip", "region": "wor"},
            {"type": "fanart", "url": "https://ss/1942-fade.png", "region": "us"},
            {"type": "bgmusic", "url": "https://ss/1942-sound.mp3", "region": "us"},
        ],
    }
    meta = _parse_screenscraper("1942", jeu)
    assert meta.theme_url == "https://ss/1942-theme.zip"
    assert meta.fade_url == "https://ss/1942-fade.png"
    assert meta.sound_url == "https://ss/1942-sound.mp3"
    # Candidate lists are also populated
    assert meta.media_candidates["theme"][0].url.endswith(".zip")
    assert meta.media_candidates["fade"][0].url.endswith(".png")
    assert meta.media_candidates["sound"][0].url.endswith(".mp3")


def test_fade_falls_back_to_screenmarquee_when_no_fanart():
    jeu = {
        "id": "1",
        "noms": [{"langue": "en", "text": "Game"}],
        "medias": [
            {"type": "screenmarquee", "url": "https://ss/marquee.png", "region": "wor"},
        ],
    }
    meta = _parse_screenscraper("game", jeu)
    # screenmarquee is also the canonical title source; fade picks it as fallback.
    assert meta.fade_url == "https://ss/marquee.png"


# ─── download job fan-out from metadata ───────────────────────────────────────


def test_jobs_for_metadata_includes_new_types(tmp_path):
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)

    meta = GameMetadata(
        name="1942",
        theme_url="https://ss/theme.zip",
        fade_url="https://ss/fade.png",
        sound_url="https://ss/sound.mp3",
    )
    jobs = dl.jobs_for_metadata("1942", meta, media_types=["theme", "fade", "sound"])
    by_type = {mt: url for _, mt, url in jobs}
    assert by_type["theme"] == "https://ss/theme.zip"
    assert by_type["fade"] == "https://ss/fade.png"
    assert by_type["sound"] == "https://ss/sound.mp3"


def test_download_writes_to_correct_slot(tmp_path, monkeypatch):
    """Stub the network and confirm the downloader writes to Artwork4/Themes/Sound."""
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)

    class _FakeResp:
        status_code = 200
        headers: dict[str, str] = {}

        def __init__(self, payload: bytes):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 8192):
            yield self._payload

        def close(self) -> None:
            return None

    payloads = {
        "https://ss/theme.zip": b"PK\x03\x04zipdata",
        "https://ss/fade.png":  b"\x89PNGfade",
        "https://ss/sound.mp3": b"ID3sound",
    }

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payloads[url])

    monkeypatch.setattr(dl._session, "get", fake_get)

    r1 = dl.download("1942", "MAME", "theme", "https://ss/theme.zip")
    r2 = dl.download("1942", "MAME", "fade", "https://ss/fade.png")
    r3 = dl.download("1942", "MAME", "sound", "https://ss/sound.mp3")

    assert r1.success and r1.path is not None
    assert r1.path == tmp_path / "Media" / "MAME" / "Themes" / "1942.zip"
    assert r1.path.read_bytes() == payloads["https://ss/theme.zip"]

    assert r2.success and r2.path is not None
    assert r2.path == tmp_path / "Media" / "MAME" / "Images" / "Artwork4" / "1942.png"

    assert r3.success and r3.path is not None
    assert r3.path == tmp_path / "Media" / "MAME" / "Sound" / "1942.mp3"
