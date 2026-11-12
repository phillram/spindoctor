"""`find-dupes --by-content` leaves ROM headers out of the match.

SNES copier headers (512 bytes, on a file 512 bytes over a whole KiB), iNES
headers (``NES\\x1a``, 16 bytes) and fwNES headers (``FDS\\x1a``, 16 bytes)
are not game data, so two copies that differ only by one are the same game.
"""
from __future__ import annotations

import gzip
import hashlib
import zipfile

import pytest
from click import unstyle
from click.testing import CliRunner
from rich.console import Console

from spindoctor import archives
from spindoctor.config import Config, save_config
from spindoctor.dupes import find_duplicates_in_system
from spindoctor.romheaders import HeaderlessSHA1, header_length
from tests.helpers import build_nes_library

BODY = bytes(range(256)) * 16  # 4 KiB of "cartridge data"
SNES_HEADER = b"\x80\x00" + b"\x00" * 510
INES_A = b"NES\x1a\x02\x01\x01\x00" + b"\x00" * 8
INES_B = b"NES\x1a\x02\x01\x01\x00DiskDude"  # same game, junk in the last bytes
FWNES = b"FDS\x1a\x01" + b"\x00" * 11


def _library(tmp_path, system):
    roms = tmp_path / "roms"
    folder = roms / system
    folder.mkdir(parents=True)
    cfg = Config()
    cfg.roms_dir = str(roms)
    save_config(cfg)
    return cfg, folder


def _content_groups(system, cfg):
    return [g for g in find_duplicates_in_system(system, cfg, by_content=True)
            if g.reason == "content"]


# ─── raw files ───────────────────────────────────────────────────────────────


def test_snes_copier_header_matches_unheadered_copy(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "snes")
    (folder / "Game [T+Eng].smc").write_bytes(SNES_HEADER + BODY)
    (folder / "Game (Translated En).sfc").write_bytes(BODY)

    groups = _content_groups("snes", cfg)

    assert len(groups) == 1
    assert sorted(p.name for p in groups[0].files) == [
        "Game (Translated En).sfc", "Game [T+Eng].smc"]
    assert [p.name for p in groups[0].headers_ignored] == ["Game [T+Eng].smc"]
    assert groups[0].key == hashlib.sha1(BODY).hexdigest()[:12]


@pytest.mark.parametrize("ext", [".swc", ".fig", ".SMC"])
def test_other_snes_copier_extensions_match(isolated_config, tmp_path, ext):
    cfg, folder = _library(tmp_path, "snes")
    (folder / ("copier" + ext)).write_bytes(SNES_HEADER + BODY)
    (folder / "plain.sfc").write_bytes(BODY)

    groups = _content_groups("snes", cfg)

    assert len(groups) == 1
    assert [p.name for p in groups[0].headers_ignored] == ["copier" + ext]


def test_nes_copies_with_different_ines_headers_match(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "nes")
    (folder / "Game (U).nes").write_bytes(INES_A + BODY)
    (folder / "Game (U) [o1].nes").write_bytes(INES_B + BODY)
    (folder / "Game (headerless).nes").write_bytes(BODY)

    groups = _content_groups("nes", cfg)

    assert len(groups) == 1
    assert groups[0].count == 3
    assert sorted(p.name for p in groups[0].headers_ignored) == [
        "Game (U) [o1].nes", "Game (U).nes"]


def test_fds_fwnes_header_matches_bare_disk_image(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "fds")
    (folder / "Disk (fwNES).fds").write_bytes(FWNES + BODY)
    (folder / "Disk.fds").write_bytes(BODY)

    groups = _content_groups("fds", cfg)

    assert len(groups) == 1
    assert [p.name for p in groups[0].headers_ignored] == ["Disk (fwNES).fds"]


@pytest.mark.parametrize("ext", [".bin", ".md", ".gen", ".zzz"])
def test_odd_sized_non_snes_file_is_not_trimmed(isolated_config, tmp_path, ext):
    # 512 bytes over a whole KiB is a copier header only on SNES files.
    cfg, folder = _library(tmp_path, "genesis")
    (folder / ("a" + ext)).write_bytes(SNES_HEADER + BODY)
    (folder / ("b" + ext)).write_bytes(BODY)

    assert _content_groups("genesis", cfg) == []


def test_snes_file_on_a_whole_kib_is_not_trimmed(isolated_config, tmp_path):
    # Two 4 KiB .sfc files that differ only in their first 512 bytes have no
    # header to leave out, so they're different games.
    cfg, folder = _library(tmp_path, "snes")
    (folder / "a.sfc").write_bytes(b"\x01" * 512 + BODY[512:])
    (folder / "b.sfc").write_bytes(b"\x02" * 512 + BODY[512:])

    assert _content_groups("snes", cfg) == []


def test_nes_file_without_the_magic_is_not_trimmed(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "nes")
    (folder / "a.nes").write_bytes(b"NEZ\x1a" + b"\x00" * 12 + BODY)
    (folder / "b.nes").write_bytes(b"\x00" * 16 + BODY)
    (folder / "c.nes").write_bytes(BODY)

    assert _content_groups("nes", cfg) == []


def test_ines_magic_on_another_extension_is_not_trimmed(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "nes")
    (folder / "a.unf").write_bytes(INES_A + BODY)
    (folder / "b.unf").write_bytes(INES_B + BODY)

    assert _content_groups("nes", cfg) == []


@pytest.mark.parametrize("system,name,data", [
    ("snes", "game.sfc", BODY),
    ("snes", "game.smc", SNES_HEADER + BODY),
    ("nes", "game.nes", INES_A + BODY),
])
def test_byte_for_byte_copies_have_no_header_note(isolated_config, tmp_path, system, name, data):
    # Nearly every .nes file has a header; noting it on exact copies is noise.
    cfg, folder = _library(tmp_path, system)
    (folder / ("a " + name)).write_bytes(data)
    (folder / ("b " + name)).write_bytes(data)

    groups = _content_groups(system, cfg)

    assert len(groups) == 1
    assert groups[0].headers_ignored == []


def test_header_note_names_every_headered_copy_when_copies_differ(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "nes")
    (folder / "a.nes").write_bytes(INES_A + BODY)
    (folder / "b.nes").write_bytes(INES_A + BODY)
    (folder / "c.nes").write_bytes(BODY)

    groups = _content_groups("nes", cfg)

    assert len(groups) == 1
    assert sorted(p.name for p in groups[0].headers_ignored) == ["a.nes", "b.nes"]


# ─── archives ────────────────────────────────────────────────────────────────


def _zip(path, name, data):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, data)


def test_zipped_headered_and_unheadered_copies_match(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "snes")
    _zip(folder / "Game [T+Eng].zip", "Game [T+Eng].smc", SNES_HEADER + BODY)
    _zip(folder / "Game (Translated En).zip", "roms/Game (Translated En).sfc", BODY)

    groups = _content_groups("snes", cfg)

    assert len(groups) == 1
    assert [p.name for p in groups[0].headers_ignored] == ["Game [T+Eng].zip"]


def test_gzipped_nes_copies_with_different_headers_match(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "nes")
    for name, data in (("a.nes.gz", INES_A + BODY), ("b.nes.gz", INES_B + BODY)):
        with gzip.open(folder / name, "wb") as f:
            f.write(data)

    groups = _content_groups("nes", cfg)

    assert len(groups) == 1
    assert groups[0].count == 2


def test_7z_headered_and_unheadered_copies_match(isolated_config, tmp_path):
    py7zr = pytest.importorskip("py7zr")
    cfg, folder = _library(tmp_path, "snes")
    for archive, name, data in (("a.7z", "a.smc", SNES_HEADER + BODY), ("b.7z", "b.sfc", BODY)):
        with py7zr.SevenZipFile(folder / archive, "w") as zf:
            zf.writestr(data, name)

    groups = _content_groups("snes", cfg)

    assert len(groups) == 1
    assert [p.name for p in groups[0].headers_ignored] == ["a.7z"]


def test_identical_zips_of_a_headered_rom_have_no_header_note(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "nes")
    _zip(folder / "a.zip", "a.nes", INES_A + BODY)
    _zip(folder / "b.zip", "b.nes", INES_A + BODY)

    groups = _content_groups("nes", cfg)

    assert len(groups) == 1
    assert groups[0].headers_ignored == []


def test_zipped_odd_sized_non_snes_entry_is_not_trimmed(isolated_config, tmp_path):
    cfg, folder = _library(tmp_path, "genesis")
    _zip(folder / "a.zip", "a.bin", SNES_HEADER + BODY)
    _zip(folder / "b.zip", "b.bin", BODY)

    assert _content_groups("genesis", cfg) == []


def test_inner_hash_adds_headerless_sha1_only_on_request(tmp_path):
    path = tmp_path / "game.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("game.smc", SNES_HEADER + BODY)
        zf.writestr("readme.txt", b"x" * 1536)  # 512 over a KiB, not a ROM

    plain = archives.extract_inner_hash(path)
    assert all("sha1_headerless" not in e for e in plain["entries"])

    entries = {e["name"]: e for e in archives.extract_inner_hash(path, headerless=True)["entries"]}
    assert entries["game.smc"]["sha1"] == hashlib.sha1(SNES_HEADER + BODY).hexdigest()
    assert entries["game.smc"]["sha1_headerless"] == hashlib.sha1(BODY).hexdigest()
    assert "sha1_headerless" not in entries["readme.txt"]


# ─── the header rules ────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,size,head,expected", [
    ("game.smc", 4096 + 512, b"", 512),
    ("game.sfc", 4096, b"", 0),
    ("game.sfc", 4096 + 100, b"", 0),
    ("game.smc", 512, b"", 0),               # nothing left after the header
    ("dir/Game.SFC", 2048 + 512, b"", 512),  # archive entry, any case
    ("game.bin", 4096 + 512, b"", 0),
    ("game.nes", 16 + 4096, b"NES\x1a\x02", 16),
    ("game.nes", 16, b"NES\x1a", 0),         # a header with no game
    ("game.nes", 16 + 4096, b"NES\x00", 0),
    ("game.fds", 16 + 4096, b"FDS\x1a\x01", 16),
    ("game.fds", 16 + 4096, b"NES\x1a", 0),
    ("game.zip", 16 + 4096, b"NES\x1a", 0),
])
def test_header_length(name, size, head, expected):
    assert header_length(name, size, head) == expected


@pytest.mark.parametrize("chunk", [1, 7, 16, 511, 513, 1 << 20])
@pytest.mark.parametrize("name,data", [
    ("game.smc", SNES_HEADER + BODY),
    ("game.nes", INES_A + BODY),
    ("game.fds", FWNES + BODY),
])
def test_streamed_headerless_sha1_matches_any_chunk_size(chunk, name, data):
    h = HeaderlessSHA1(name)
    for i in range(0, len(data), chunk):
        h.update(data[i:i + chunk])
    assert h.hexdigest() == hashlib.sha1(BODY).hexdigest()


@pytest.mark.parametrize("name,data", [
    ("game.sfc", BODY),                  # whole KiB: no copier header
    ("game.nes", BODY),                  # no magic
    ("game.bin", SNES_HEADER + BODY),    # not a ROM with a known header
])
def test_streamed_headerless_sha1_is_none_without_a_header(name, data):
    h = HeaderlessSHA1(name)
    h.update(data)
    assert h.hexdigest() is None


# ─── CLI ─────────────────────────────────────────────────────────────────────


def test_cli_marks_files_whose_header_was_ignored(tmp_path, config_home, monkeypatch):
    from spindoctor import cli as cli_mod

    build_nes_library(tmp_path)
    folder = tmp_path / "roms" / "nes"
    (folder / "Contra (U) [h1].nes").write_bytes(INES_A + BODY)
    (folder / "Contra (U) [b1].nes").write_bytes(BODY)
    monkeypatch.setattr(cli_mod, "console", Console(soft_wrap=True, width=1000))

    result = CliRunner().invoke(cli_mod.cli, ["find-dupes", "--system", "nes", "--by-content"])

    assert result.exit_code == 0, result.output
    lines = [line.rstrip() for line in unstyle(result.output).splitlines()]
    headered = [line for line in lines if line.endswith("Contra (U) [h1].nes (ROM header ignored)")]
    bare = [line for line in lines if line.endswith("Contra (U) [b1].nes")]
    assert len(headered) == 1, result.output
    assert len(bare) == 2, result.output  # in the title group and the content group
