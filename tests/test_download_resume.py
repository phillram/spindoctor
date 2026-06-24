"""Resumable downloads + atomic rename behavior in MediaDownloader."""
from __future__ import annotations

from pathlib import Path

import pytest

from spindoctor.config import Config
from spindoctor.media import MediaDownloader


class _FakeResp:
    def __init__(
        self,
        payload: bytes,
        status_code: int = 200,
        headers: dict | None = None,
    ):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"raise_for_status hit {self.status_code}")

    def iter_content(self, chunk_size: int = 8192):
        # Yield in two chunks to exercise the streaming write path.
        mid = len(self._payload) // 2
        if mid:
            yield self._payload[:mid]
        yield self._payload[mid:]

    def close(self) -> None:
        return None


def _make_downloader(tmp_path: Path) -> MediaDownloader:
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    return MediaDownloader(cfg)


def test_successful_download_uses_part_then_atomic_rename(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    payload = b"\x89PNGfullbody"

    seen: dict = {}

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        seen["headers"] = headers
        return _FakeResp(payload, status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png")

    assert r.success and r.path is not None
    assert r.path.read_bytes() == payload
    # No headers passed when there's nothing to resume.
    assert seen["headers"] is None
    # No leftover .part file after success.
    assert not r.path.with_name(r.path.name + ".part").exists()


def test_resume_appends_partial_with_range_header(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    full = b"abcdefghijklmnopqrstuvwxyz"
    prefix, suffix = full[:10], full[10:]

    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(prefix)

    seen: dict = {}

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        seen["headers"] = headers
        return _FakeResp(suffix, status_code=206)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png")

    assert r.success
    assert seen["headers"] == {"Range": "bytes=10-"}
    assert r.path is not None and r.path.read_bytes() == full
    assert not part.exists()


def test_server_ignores_range_returns_200_truncates_partial(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    full = b"FULL-CONTENT-FROM-START"

    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"stale-junk")

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        # Server received Range but chose to send the whole file.
        assert headers == {"Range": "bytes=10-"}
        return _FakeResp(full, status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png")

    assert r.success and r.path is not None
    assert r.path.read_bytes() == full
    assert not part.exists()


def test_416_drops_partial_and_restarts(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    full = b"fresh-bytes"

    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"way-too-many-bytes-for-server")

    calls = {"n": 0}

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            assert "Range" in (headers or {})
            return _FakeResp(b"", status_code=416)
        # Second attempt: no partial → no Range header.
        assert headers is None
        return _FakeResp(full, status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png", max_retries=3)

    assert r.success and r.path is not None
    assert r.path.read_bytes() == full
    assert calls["n"] == 2
    assert not part.exists()


def test_http_404_fails_immediately_without_retry(tmp_path, monkeypatch):
    """Non-retriable HTTP errors (404, 403, 500, etc.) must fail on the first
    attempt, not be retried max_retries times.  The comment in the download
    loop says 'Other 4xx/5xx fail fast' — this test pins that contract.

    Previously requests.HTTPError (from raise_for_status) was caught by the
    broader requests.RequestException handler and retried, wasting seconds per
    miss on every absent media URL."""
    import requests as req_lib

    dl = _make_downloader(tmp_path)
    calls: dict = {"n": 0}

    class _Resp404(_FakeResp):
        def raise_for_status(self):
            raise req_lib.HTTPError(response=self)  # type: ignore[arg-type]

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        calls["n"] += 1
        return _Resp404(b"", status_code=404)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png", max_retries=3)

    assert not r.success
    assert calls["n"] == 1, (
        f"expected exactly 1 attempt for a 404, got {calls['n']} — "
        "HTTPError was being retried as a RequestException"
    )


def test_network_failure_preserves_part_for_next_run(tmp_path, monkeypatch):
    import requests

    dl = _make_downloader(tmp_path)

    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"already-downloaded-prefix")

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(dl._session, "get", fake_get)
    monkeypatch.setattr("spindoctor.media.time.sleep", lambda *_: None)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png", max_retries=2)

    assert not r.success
    # Partial preserved so the next run can pick up where we left off.
    assert part.exists() and part.read_bytes() == b"already-downloaded-prefix"
    assert not dest.exists()


def test_overwrite_drops_stale_partial(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    full = b"clean-rebuild"

    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"stale-from-old-run")

    seen: dict = {}

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        seen["headers"] = headers
        return _FakeResp(full, status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download(
        "1942", "MAME", "wheel", "https://x/1942.png", overwrite=True,
    )

    assert r.success and r.path is not None
    assert r.path.read_bytes() == full
    # overwrite=True wipes the stale .part before the request, so no Range header.
    assert seen["headers"] is None
    assert not part.exists()


def test_existing_complete_file_is_skipped_without_network(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"already here")

    def fake_get(*_a, **_kw):
        pytest.fail("network should not be hit when destination already exists")

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png")
    assert r.success and r.skipped
    assert r.path == dest


# ─── URL extension handling ──────────────────────────────────────────────────


def test_php_url_does_not_rename_destination(tmp_path, monkeypatch):
    """ScreenScraper serves all media via mediaJeu.php — the .php suffix must
    not override the destination extension (.png, .mp4, etc.)."""
    dl = _make_downloader(tmp_path)
    payload = b"\x89PNG fake-png-body"

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(dl._session, "get", fake_get)

    r = dl.download("1942", "MAME", "wheel",
                    "https://www.screenscraper.fr/api2/mediaJeu.php?devid=x&media=wheel")
    assert r.success and r.path is not None
    assert r.path.suffix == ".png", f"expected .png, got {r.path.suffix}"
    assert r.path.read_bytes() == payload


def test_url_extension_does_not_override_destination(tmp_path, monkeypatch):
    """The URL's file extension must never override the destination extension.

    HyperSpin locates media by exact filename (GameName.png, GameName.mp4,
    etc.).  If the CDN serves a JPEG at a .jpg URL but the slot expects .png,
    saving as .jpg means HyperSpin silently ignores the file.  The downloader
    must always honour the path returned by media_path(), regardless of what
    the URL path ends with.  Regression guard: the old _MEDIA_EXTS override
    block was removed in PR #350 for this reason.
    """
    dl = _make_downloader(tmp_path)
    payload = b"\xff\xd8\xff fake-jpeg-body"

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(dl._session, "get", fake_get)

    # URL says .jpg; slot expects .png — destination must stay .png
    r = dl.download("1942", "MAME", "wheel",
                    "https://cdn.example.com/media/1942.jpg")
    assert r.success and r.path is not None
    assert r.path.suffix == ".png", (
        f"URL extension overrode destination — got {r.path.suffix}, expected .png. "
        "The _MEDIA_EXTS override block must not be re-introduced."
    )


# ─── atomic-write fault injection ────────────────────────────────────────────


def test_os_replace_failure_preserves_existing_destination(tmp_path, monkeypatch):
    """If `os.replace(part, dest)` raises (disk full, antivirus lock, etc.)
    a pre-existing destination must remain bit-identical.

    Pins the atomic-write contract: SpinDoctor must never corrupt a real
    file with a half-written replacement. The `.part` sidecar is allowed
    to remain on disk — that's how resumable downloads work — but `dest`
    must be intact.
    """
    import os as _os

    dl = _make_downloader(tmp_path)
    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    original = b"original-bytes-do-not-touch"
    dest.write_bytes(original)

    payload = b"replacement-payload"

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload, status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)

    # Surgical fault injection: only fail the rename targeting *our* dest.
    real_replace = _os.replace

    def boom(src, dst, *a, **kw):
        if str(dst) == str(dest):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(_os, "replace", boom)

    # The download must complete with `overwrite=True` (default `False`
    # short-circuits before fetching since `dest` exists).
    r = dl.download(
        "1942", "MAME", "wheel", "https://x/1942.png", overwrite=True,
    )

    # The destination is the load-bearing assertion: under no
    # circumstances does an exception during the atomic swap corrupt
    # the file the user already had.
    assert dest.read_bytes() == original
    # And the failure surfaces as a non-success DownloadResult — not a
    # silent partial swallow.
    assert r.success is False


def test_retry_after_http_date_falls_back_to_backoff(tmp_path, monkeypatch):
    """A Retry-After header in HTTP-date format ('Wed, 21 Oct 2015 07:28:00 GMT')
    must not crash with ValueError.  float() on a date string raises ValueError;
    the fixed code catches it and falls back to the current backoff value."""
    dl = _make_downloader(tmp_path)
    calls: dict = {"n": 0}
    slept: list = []

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(
                b"",
                status_code=429,
                headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            )
        return _FakeResp(b"real-content", status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)
    monkeypatch.setattr("spindoctor.media.time.sleep", lambda t: slept.append(t))

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png", max_retries=3)

    assert r.success, f"expected success; got: {r}"
    assert calls["n"] == 2
    # Fell back to backoff (1.0 on first retry), not an HTTP-date string.
    assert slept and isinstance(slept[0], float) and slept[0] <= 30.0


def test_os_replace_failure_when_dest_absent_leaves_no_dest(tmp_path, monkeypatch):
    """The other half of the atomic-write contract: a failed swap must
    not leave a partially-written file *appearing* at `dest` (which would
    fool a subsequent skip-if-exists check on the next run)."""
    import os as _os

    dl = _make_downloader(tmp_path)
    dest = dl.media_path("MAME", "1942", "wheel")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # No pre-existing dest.

    payload = b"partial-replacement"

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload, status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)

    def boom(src, dst, *a, **kw):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(_os, "replace", boom)

    r = dl.download(
        "1942", "MAME", "wheel", "https://x/1942.png", overwrite=False,
    )
    assert not dest.exists()
    assert r.success is False


# ─── extension normalisation + PNG conversion ─────────────────────────────────


def test_uppercase_dest_extension_normalised_to_lowercase(tmp_path, monkeypatch):
    """A destination path with an uppercase extension (e.g. .PNG) must be
    normalised to lowercase before the file is written.  HyperSpin filename
    lookups are case-sensitive on Linux and the canonical extension is .png.
    """
    from pathlib import Path as _Path
    dl = _make_downloader(tmp_path)
    payload = b"\x89PNG fake-content"
    dest = _Path(str(tmp_path / "Media" / "MAME" / "Images" / "Wheel" / "1942.PNG"))

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(dl._session, "get", fake_get)
    # Monkeypatch _convert_to_png_inplace to a no-op so we're only testing
    # the extension normalisation, not the conversion.
    monkeypatch.setattr("spindoctor.media._convert_to_png_inplace", lambda _p: None)

    r = dl.download_to_path(dest, "https://cdn/img.png", label="1942", media_type="wheel")
    assert r.success and r.path is not None
    assert r.path.suffix == ".png", f"expected .png, got {r.path.suffix}"
    assert r.path.name == "1942.png"


def test_convert_to_png_inplace_called_after_png_download(tmp_path, monkeypatch):
    """_convert_to_png_inplace must be called after a successful download to a
    .png destination.  This is what converts Steam's JPEG bytes to real PNG.
    """
    dl = _make_downloader(tmp_path)
    payload = b"\xff\xd8\xff fake-jpeg"

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(dl._session, "get", fake_get)

    called_with: list = []
    monkeypatch.setattr(
        "spindoctor.media._convert_to_png_inplace",
        lambda p: called_with.append(p),
    )

    r = dl.download("1942", "MAME", "wheel", "https://cdn/1942.jpg")
    assert r.success and r.path is not None
    assert r.path.suffix == ".png"
    assert len(called_with) == 1, "expected _convert_to_png_inplace to be called once"
    assert called_with[0] == r.path


def test_convert_to_png_inplace_not_called_for_non_png_dest(tmp_path, monkeypatch):
    """_convert_to_png_inplace must NOT be called for non-.png destinations
    (e.g. video slots that land as .mp4).
    """
    dl = _make_downloader(tmp_path)
    payload = b"fake-video-bytes"

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(dl._session, "get", fake_get)

    called: list = []
    monkeypatch.setattr(
        "spindoctor.media._convert_to_png_inplace",
        lambda p: called.append(p),
    )

    r = dl.download("1942", "MAME", "video", "https://cdn/1942.mp4")
    assert r.success
    assert not called, "_convert_to_png_inplace must not be called for .mp4 dest"
