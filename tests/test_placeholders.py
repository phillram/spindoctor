"""Stand-ins for missing media: the lists beside them, and everything that must
go on treating their games as missing the real thing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindoctor import media_scan, placeholders
from spindoctor.audit import MediaIndex, check_media
from spindoctor.config import Config
from spindoctor.fileinfo import find_media_file, scan_system
from spindoctor.media import MediaDownloader


def _put(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _standin(path: Path, data: bytes = b"no video found", kind: str = "clip", game: str = "Alpha") -> Path:
    _put(path, data)
    placeholders.record(path.parent, [placeholders.describe(path, kind, game)])
    return path


def test_a_listed_file_is_a_placeholder_until_it_changes(tmp_path):
    video = _standin(tmp_path / "Alpha.mp4")
    assert placeholders.is_placeholder(video) and not placeholders.taken(video)
    assert placeholders.is_placeholder(tmp_path / "alpha.MP4") or not (tmp_path / "alpha.MP4").exists()
    video.write_bytes(b"the real video, another size")
    assert not placeholders.is_placeholder(video) and placeholders.taken(video)
    assert not placeholders.taken(tmp_path / "Missing.mp4")


def test_every_list_in_a_folder_counts(tmp_path):
    a = _standin(tmp_path / "Alpha.mp4")
    b = _put(tmp_path / "Bravo.mp4", b"another")
    placeholders.record(tmp_path, [placeholders.describe(b, "clip", "Bravo")],
                        "spindoctor-placeholders-20261122.json")
    assert set(placeholders.read(tmp_path)) == {"alpha.mp4", "bravo.mp4"}
    assert placeholders.is_placeholder(a) and placeholders.is_placeholder(b)


@pytest.mark.parametrize("text", ["", "{", "[]", '{"files": 3}', '{"files": [{"name": "Alpha.mp4"}]}'])
def test_a_broken_list_makes_its_files_real_media(tmp_path, text):
    video = _standin(tmp_path / "Alpha.mp4")
    (tmp_path / placeholders.LIST_NAME).write_text(text, encoding="utf-8")
    assert not placeholders.is_placeholder(video)


def test_remove_deletes_only_unchanged_files_of_the_asked_kinds(tmp_path):
    clip = _standin(tmp_path / "Alpha.mp4")
    drawn = _standin(tmp_path / "Alpha.png", b"drawn title", "drawn")
    other = _standin(tmp_path / "Bravo.mp4", b"clip of bravo", "clip", "Bravo")
    same_size = _standin(tmp_path / "Charlie.mp4", b"0123456789", "clip", "Charlie")
    same_size.write_bytes(b"9876543210")  # edited since, same length
    _put(tmp_path / "Delta.mp4", b"real")

    result = placeholders.remove(tmp_path, ("clip", "picture"), ["alpha", "Charlie"])
    assert result.removed == [clip] and result.changed == [same_size] and not result.errors
    assert not clip.exists() and drawn.exists() and other.exists() and (tmp_path / "Delta.mp4").exists()
    assert "alpha.mp4" not in placeholders.read(tmp_path)
    assert placeholders.remove(tmp_path, ("clip",), keep=[other]).removed == []
    assert [p for p, _e in placeholders.find(tmp_path, ("drawn",))] == [drawn]


def test_removing_the_last_one_removes_the_list(tmp_path):
    _standin(tmp_path / "Alpha.mp4")
    placeholders.remove(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_recording_keeps_the_entries_an_undo_may_need(tmp_path):
    first = _standin(tmp_path / "Alpha.mp4")
    data = first.read_bytes()
    first.write_bytes(b"the real video")
    _standin(tmp_path / "Bravo.mp4", b"another", game="Bravo")
    first.write_bytes(data)  # an undo put the stand-in back
    assert placeholders.is_placeholder(first)


def _media(tmp_path) -> tuple[Config, Path]:
    cfg = Config(hyperspin_dir=str(tmp_path / "hs"), roms_dir=str(tmp_path / "roms"))
    return cfg, cfg.media_dir / "NES"


def test_audits_still_count_the_game_as_missing(tmp_path):
    cfg, nes = _media(tmp_path)
    _standin(nes / "Video" / "Alpha.mp4")
    _put(nes / "Video" / "Bravo.mp4", b"a real video")
    _standin(nes / "Images" / "Wheel" / "Alpha.png", b"drawn title", "drawn")
    index = MediaIndex("NES", cfg.media_dir)
    assert not index.check("Alpha").video and not index.check("Alpha").wheel
    assert index.check("bravo").video
    assert not check_media("Alpha", "NES", cfg.media_dir).video
    assert check_media("Bravo", "NES", cfg.media_dir).video
    # A folder without a list is judged as before, whatever else is in it.
    _put(nes / "Images" / "Artwork1" / "Alpha.png", b"box")
    _put(nes / "Images" / "Artwork1" / "notes.json", b"{}")
    assert MediaIndex("NES", cfg.media_dir).check("Alpha").artwork


def test_inspect_says_only_a_placeholder_is_there(tmp_path):
    cfg, nes = _media(tmp_path)
    _standin(nes / "Video" / "Alpha.mp4")
    detail = find_media_file("Alpha", "NES", "video", cfg.media_dir)
    assert not detail.exists and detail.placeholder
    _put(nes / "Video" / "Alpha.flv", b"a real video")
    detail = find_media_file("Alpha", "NES", "video", cfg.media_dir)
    assert detail.exists and not detail.placeholder and detail.path.suffix == ".flv"
    report = scan_system("NES", tmp_path / "roms", cfg.media_dir, {}, ["Alpha"], ["video"])[0]
    assert report.media["video"].exists


class _Response:
    status_code = 200
    headers: dict = {}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield b"downloaded logo"

    def close(self):
        pass


def test_a_download_replaces_a_placeholder_without_overwrite(tmp_path):
    cfg, nes = _media(tmp_path)
    logo = _standin(nes / "Images" / "Wheel" / "Alpha.png", b"drawn title", "drawn")
    downloader = MediaDownloader(cfg)
    downloader._session = type("S", (), {"get": staticmethod(lambda *a, **k: _Response())})()
    result = downloader.download("Alpha", "NES", "wheel", "https://example.invalid/logo.png")
    assert result.success and not result.skipped and logo.read_bytes() == b"downloaded logo"
    again = downloader.download("Alpha", "NES", "wheel", "https://example.invalid/logo.png")
    assert again.skipped  # real media now, so kept


def test_media_add_replaces_a_placeholder_without_overwrite(tmp_path):
    cfg, nes = _media(tmp_path)
    video = _standin(nes / "Video" / "Alpha.mp4")
    source = _put(tmp_path / "mine.mp4", b"my own video")
    assert not MediaDownloader(cfg).add_local_file(source, "Alpha", "NES", "video").skipped
    assert video.read_bytes() == b"my own video"


def test_an_import_replaces_a_placeholder_and_undo_puts_it_back(tmp_path):
    cfg, nes = _media(tmp_path)
    db = cfg.databases_dir / "NES" / "NES.xml"
    _put(db, b'<?xml version="1.0"?><menu><game name="Alpha"><description>Alpha</description></game></menu>')
    video = _standin(nes / "Video" / "Alpha.mp4")
    before = video.read_bytes()
    _put(tmp_path / "pack" / "Videos" / "Alpha.mp4", b"a real video")
    found = media_scan.scan_local_media(tmp_path / "pack")
    report = media_scan.match_to_database(found, "NES", cfg)
    assert [m.bucket for m in report.all()] == ["matched"]
    result = media_scan.import_media(report, cfg, manifest_dir=tmp_path / "manifests", label="from a test")
    assert video.read_bytes() == b"a real video" and not placeholders.is_placeholder(video)
    assert json.loads(result.manifest_path.read_text(encoding="utf-8"))["label"] == "from a test"
    assert media_scan.undo_import(result.manifest_path)["errors"] == []
    assert video.read_bytes() == before and placeholders.is_placeholder(video)
    # A second import of real media over real media still needs --overwrite.
    video.write_bytes(b"somebody's video")
    report = media_scan.match_to_database(found, "NES", cfg)
    assert [m.bucket for m in report.all()] == ["replacement"]
