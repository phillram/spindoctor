"""Credentials, executable previews and empty media names stay contained."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import requests

from spindoctor import media, medialink, scraper
from spindoctor.config import Config


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("no json body")


def test_redact_text_masks_raw_and_percent_encoded_secrets():
    params = {"sspassword": "a+b&c d", "apikey": "k3y"}
    text = "pw a+b&c d / a%2Bb%26c%20d / a%2Bb%26c+d / key k3y"
    out = scraper._redact_text(text, params)
    assert "a+b" not in out and "a%2B" not in out and "k3y" not in out


def test_redact_text_masks_query_secrets_without_params():
    url = "https://x/api?devid=SpinDoctor&devpassword=dp1&ssid=u&sspassword=sp1&apikey=ak1"
    out = scraper._redact_text(f"Max retries exceeded with url: {url}")
    assert "dp1" not in out and "sp1" not in out and "ak1" not in out
    assert "devid=SpinDoctor" in out and "sspassword=***" in out


def test_metadata_error_message_never_carries_query_secrets():
    err = scraper.MetadataError(
        "ScreenScraper fetch failed: HTTPSConnectionPool: /api2/jeuInfos.php?sspassword=hunter2&x=1"
    )
    assert "hunter2" not in str(err)


def test_verify_screenscraper_network_error_hides_password():
    boom = requests.ConnectionError(
        "Max retries exceeded with url: /api2/ssuserInfos.php?sspassword=pa%24%24word&devpassword=dpw"
    )
    with patch.object(scraper, "request_get", side_effect=boom):
        ok, msg = scraper.verify_screenscraper("testuser", "pa$$word", devid="d", devpassword="dpw")
    assert ok is False
    assert "pa%24%24word" not in msg and "pa$$word" not in msg and "dpw" not in msg


def test_verify_thegamesdb_redacts_key_echoed_in_body():
    with patch.object(scraper, "request_get",
                      return_value=_FakeResponse(401, "bad key: secretkey123")):
        ok, msg = scraper.verify_thegamesdb("secretkey123")
    assert ok is False
    assert "secretkey123" not in msg


def test_preview_refuses_non_media_extension(tmp_path):
    dl = media.MediaDownloader(Config())
    opened, fetched = [], []
    cand = SimpleNamespace(url="https://media.example/boxart.bat", format="exe", source_type="box-2D")
    with patch.object(media, "_open_in_default_app", side_effect=opened.append), \
            patch.object(dl, "download_to_path", side_effect=lambda *a, **k: fetched.append(a)):
        assert dl.preview_candidate(cand, 0) is None
    assert opened == [] and fetched == []


def test_preview_still_opens_images(tmp_path, monkeypatch):
    monkeypatch.setattr(media.tempfile, "gettempdir", lambda: str(tmp_path))
    dl = media.MediaDownloader(Config())
    opened = []

    def fake_download(path, url, **kwargs):
        path.write_bytes(b"\x89PNG")
        return SimpleNamespace(success=True)

    for i, url in enumerate(("https://media.example/mediaJeu.php?id=1",
                             "https://media.example/boxart.bat")):
        cand = SimpleNamespace(url=url, format="PNG", source_type="ss")
        with patch.object(media, "_open_in_default_app", side_effect=opened.append), \
                patch.object(dl, "download_to_path", side_effect=fake_download):
            path = dl.preview_candidate(cand, i)
        assert path is not None and path.suffix == ".png"
        assert opened[-1] == path


def test_remove_target_ignores_names_that_normalize_to_nothing(tmp_path):
    sub = medialink.MEDIA_DIR_SUBDIRS[0]
    keep = tmp_path / "Favorites" / sub / "Other Game"
    keep.mkdir(parents=True)
    for name in ("..", ".", "...", "  "):
        assert medialink.remove_target(tmp_path, "Favorites", name) == 0
    assert keep.is_dir()
