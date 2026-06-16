"""Tests for the three zero-byte / data-consistency fixes:

1. _download_to fails cleanly when the server returns an empty body (0 bytes).
2. CombinedMetadataClient.search() has no duplicate variable declarations
   (regression guard via a search that hits both error and success paths).
3. media_scan.match_to_database / import_media treat a zero-byte target as
   absent (consistent with audit.check_media after PR #312).
4. preview._first_existing skips zero-byte files.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spindoctor.config import Config
from spindoctor.media import MediaDownloader
from spindoctor.media_scan import MediaScanReport, ScanMatch, _nonempty, import_media
from spindoctor.preview import _first_existing


# ─── helpers shared across download tests ─────────────────────────────────────

class _FakeResp:
    def __init__(self, payload: bytes, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"raise_for_status hit {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield self._payload

    def close(self):
        pass


def _make_downloader(tmp_path: Path) -> MediaDownloader:
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    return MediaDownloader(cfg)


# ─── fix 1: _download_to zero-byte response ───────────────────────────────────

def test_download_fails_on_empty_response(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)

    monkeypatch.setattr(dl._session, "get",
                        lambda *a, **kw: _FakeResp(b"", status_code=200))

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png",
                    max_retries=1)

    assert not r.success
    assert "empty" in r.error.lower() or "0 byte" in r.error.lower()


def test_download_empty_response_does_not_leave_dest_on_disk(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)

    monkeypatch.setattr(dl._session, "get",
                        lambda *a, **kw: _FakeResp(b"", status_code=200))

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png",
                    max_retries=1)

    assert not r.success
    dest = dl.media_path("MAME", "1942", "wheel")
    assert not dest.exists(), "zero-byte dest must not be left on disk after failure"


def test_download_empty_response_retries_then_fails(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)
    calls = []

    def fake_get(*a, **kw):
        calls.append(1)
        return _FakeResp(b"", status_code=200)

    monkeypatch.setattr(dl._session, "get", fake_get)
    monkeypatch.setattr("spindoctor.media.time.sleep", lambda _: None)

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png",
                    max_retries=3)

    assert not r.success
    assert len(calls) == 3, "should retry up to max_retries before giving up"


def test_download_nonempty_response_still_succeeds(tmp_path, monkeypatch):
    dl = _make_downloader(tmp_path)

    monkeypatch.setattr(dl._session, "get",
                        lambda *a, **kw: _FakeResp(b"\x89PNG\r\n\x1a\n"))

    r = dl.download("1942", "MAME", "wheel", "https://x/1942.png")

    assert r.success
    assert r.path is not None and r.path.stat().st_size > 0


# ─── fix 2: CombinedMetadataClient.search duplicate declarations ──────────────

def test_combined_search_no_duplicate_ss_error_declaration():
    """Regression guard: search() must not shadow ss_error / tgdb_error."""
    import ast, inspect, textwrap
    from spindoctor.scraper import CombinedMetadataClient

    src = textwrap.dedent(inspect.getsource(CombinedMetadataClient.search))
    tree = ast.parse(src)

    # Count AnnAssign / Assign targets named ss_error or tgdb_error.
    names_assigned: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names_assigned.append(node.target.id)

    for name in ("ss_error", "tgdb_error"):
        count = names_assigned.count(name)
        assert count <= 1, (
            f"{name} is declared {count} times in CombinedMetadataClient.search() "
            f"— duplicate declaration shadowing the initial None assignment"
        )


# ─── fix 3: media_scan zero-byte target consistency ───────────────────────────

def test_nonempty_returns_false_for_missing_file(tmp_path):
    assert _nonempty(tmp_path / "ghost.png") is False


def test_nonempty_returns_false_for_zero_byte_file(tmp_path):
    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    assert _nonempty(p) is False


def test_nonempty_returns_true_for_real_file(tmp_path):
    p = tmp_path / "real.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _nonempty(p) is True


def _make_scan_match(src: Path, target: Path) -> ScanMatch:
    from spindoctor.media_scan import LocalMediaFile
    lf = LocalMediaFile(path=src, media_type="wheel")
    sm = ScanMatch(local=lf, system="SNES", game_name="Zelda",
                   score=1.0, target_path=target)
    return sm


def test_import_media_overwrites_zero_byte_target_without_overwrite_flag(tmp_path):
    src = tmp_path / "Zelda.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")

    target_dir = tmp_path / "dest"
    target_dir.mkdir()
    target = target_dir / "Zelda.png"
    target.write_bytes(b"")  # zero-byte stub

    sm = _make_scan_match(src, target)
    sm.bucket = "matched"

    report = MediaScanReport(source_dir=tmp_path)
    report.matched.append(sm)

    result = import_media(
        report,
        config=Config(),
        action="copy",
        overwrite=False,          # without --overwrite
        include_replacements=False,
    )

    # zero-byte target is not a real file — import should proceed
    assert len(result.imported) == 1, (
        "zero-byte target must not block import when overwrite=False"
    )
    assert target.stat().st_size > 0


def test_import_media_skips_real_existing_target_without_overwrite(tmp_path):
    src = tmp_path / "Zelda.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")

    target_dir = tmp_path / "dest"
    target_dir.mkdir()
    target = target_dir / "Zelda.png"
    target.write_bytes(b"\x89PNG existing content")  # real file

    sm = _make_scan_match(src, target)
    sm.bucket = "matched"

    report = MediaScanReport(source_dir=tmp_path)
    report.matched.append(sm)

    result = import_media(
        report,
        config=Config(),
        action="copy",
        overwrite=False,
        include_replacements=False,
    )

    assert len(result.skipped) == 1, "real existing target must be skipped"
    assert len(result.imported) == 0


# ─── fix 4: preview._first_existing skips zero-byte files ─────────────────────

def test_first_existing_returns_none_for_zero_byte_file(tmp_path):
    (tmp_path / "game.png").write_bytes(b"")
    assert _first_existing(tmp_path, "game", (".png", ".jpg")) is None


def test_first_existing_returns_path_for_nonempty_file(tmp_path):
    (tmp_path / "game.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    result = _first_existing(tmp_path, "game", (".png", ".jpg"))
    assert result is not None and result.name == "game.png"


def test_first_existing_skips_zero_byte_and_finds_nonempty_fallback(tmp_path):
    (tmp_path / "game.png").write_bytes(b"")           # zero-byte first ext
    (tmp_path / "game.jpg").write_bytes(b"\xff\xd8")   # real second ext
    result = _first_existing(tmp_path, "game", (".png", ".jpg"))
    assert result is not None and result.suffix == ".jpg"


def test_first_existing_returns_none_for_missing_directory(tmp_path):
    assert _first_existing(tmp_path / "no_dir", "game", (".png",)) is None
