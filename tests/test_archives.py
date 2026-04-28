"""Archive-aware ROM hashing (zip / 7z / rar / gz / chd)."""
from __future__ import annotations

import gzip
import hashlib
import struct
import zipfile

import pytest

from spindoctor import archives


# ─── archive_kind / is_archive ────────────────────────────────────────────────


def test_archive_kind_recognises_known_extensions(tmp_path):
    samples = {
        "rom.zip": "zip",
        "rom.7z": "7z",
        "rom.RAR": "rar",     # case-insensitive
        "rom.gz": "gz",
        "disc.chd": "chd",
    }
    for fname, kind in samples.items():
        p = tmp_path / fname
        p.write_bytes(b"")
        assert archives.archive_kind(p) == kind, fname
        assert archives.is_archive(p), fname


def test_archive_kind_rejects_unknown(tmp_path):
    p = tmp_path / "rom.nes"
    p.write_bytes(b"")
    assert archives.archive_kind(p) is None
    assert not archives.is_archive(p)


# ─── zip ──────────────────────────────────────────────────────────────────────


def test_zip_inner_hash(tmp_path):
    payload = b"hello rom world" * 1000
    expected_sha1 = hashlib.sha1(payload).hexdigest()

    zpath = tmp_path / "Mario.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Mario.nes", payload)

    info = archives.extract_inner_hash(zpath)
    assert info is not None
    assert info["kind"] == "zip"
    assert info["error"] is None
    assert len(info["entries"]) == 1
    assert info["entries"][0]["name"] == "Mario.nes"
    assert info["entries"][0]["sha1"] == expected_sha1
    assert info["entries"][0]["size"] == len(payload)


# ─── gzip ─────────────────────────────────────────────────────────────────────


def test_gzip_inner_hash(tmp_path):
    payload = b"some uncompressed bytes" * 500
    expected_sha1 = hashlib.sha1(payload).hexdigest()

    gpath = tmp_path / "Zelda.nes.gz"
    with gzip.open(gpath, "wb") as f:
        f.write(payload)

    info = archives.extract_inner_hash(gpath)
    assert info is not None
    assert info["kind"] == "gz"
    assert info["error"] is None
    assert len(info["entries"]) == 1
    assert info["entries"][0]["sha1"] == expected_sha1
    assert info["entries"][0]["size"] == len(payload)


# ─── 7z ───────────────────────────────────────────────────────────────────────


def test_sevenz_inner_hash(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    payload = b"7z payload bytes" * 300
    expected_sha1 = hashlib.sha1(payload).hexdigest()

    sp = tmp_path / "Sonic.7z"
    with py7zr.SevenZipFile(sp, "w") as zf:
        zf.writestr(payload, "Sonic.gen")

    info = archives.extract_inner_hash(sp)
    assert info is not None
    assert info["kind"] == "7z"
    assert info["error"] is None
    names = {e["name"] for e in info["entries"]}
    assert "Sonic.gen" in names
    sonic = next(e for e in info["entries"] if e["name"] == "Sonic.gen")
    assert sonic["sha1"] == expected_sha1


# ─── chd ──────────────────────────────────────────────────────────────────────


def _build_chd_v5_header(raw_sha1: bytes) -> bytes:
    """Build a 124-byte CHD v5 header with the supplied rawsha1.

    Only the tag, length, version, and rawsha1 fields matter for the parser
    under test; everything else is zero-filled.
    """
    assert len(raw_sha1) == 20
    header = bytearray(124)
    header[0:8] = b"MComprHD"
    struct.pack_into(">I", header, 8, 124)   # length
    struct.pack_into(">I", header, 12, 5)    # version
    header[84:104] = raw_sha1                # rawsha1 (offset 84 in v5)
    return bytes(header)


def test_chd_v5_rawsha1_extraction(tmp_path):
    expected = hashlib.sha1(b"fake disc image bytes").digest()
    cpath = tmp_path / "GameDisc.chd"
    cpath.write_bytes(_build_chd_v5_header(expected))

    info = archives.extract_inner_hash(cpath)
    assert info is not None
    assert info["kind"] == "chd"
    assert info["error"] is None
    assert len(info["entries"]) == 1
    assert info["entries"][0]["sha1"] == expected.hex()
    assert info["entries"][0]["chd_version"] == 5


def test_chd_unsupported_version_errors(tmp_path):
    header = bytearray(60)
    header[0:8] = b"MComprHD"
    struct.pack_into(">I", header, 8, 60)
    struct.pack_into(">I", header, 12, 2)   # too old
    cpath = tmp_path / "old.chd"
    cpath.write_bytes(bytes(header))

    info = archives.extract_inner_hash(cpath)
    assert info is not None
    assert info["entries"] == []
    assert info["error"] is not None
    assert "version" in info["error"].lower()


def test_chd_missing_tag_errors(tmp_path):
    cpath = tmp_path / "garbage.chd"
    cpath.write_bytes(b"\x00" * 200)
    info = archives.extract_inner_hash(cpath)
    assert info is not None
    assert info["error"] is not None
    assert "MComprHD" in info["error"]


# ─── support_status ───────────────────────────────────────────────────────────


def test_support_status_always_includes_builtins():
    status = archives.support_status()
    assert status["zip"][0] is True
    assert status["gz"][0] is True
    assert status["chd"][0] is True
    assert "7z" in status
    assert "rar" in status


# ─── verify integration ──────────────────────────────────────────────────────


def test_verify_classifies_zip_inner_match_as_good(tmp_path):
    from spindoctor.verify import verify_system

    payload = b"verify me please" * 256
    sha1 = hashlib.sha1(payload).hexdigest()

    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    zpath = sys_dir / "Mario.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Mario.nes", payload)

    dat = tmp_path / "nes.dat"
    dat.write_text(
        '<?xml version="1.0"?>\n<datafile>\n'
        '  <game name="Mario">\n'
        f'    <rom name="Mario.nes" size="{len(payload)}" '
        f'crc="" sha1="{sha1}"/>\n'
        '  </game>\n</datafile>\n',
        encoding="utf-8",
    )

    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.summary == {"good": 1}


def test_verify_classifies_chd_rawsha1_match(tmp_path):
    from spindoctor.verify import verify_system

    raw_sha1 = hashlib.sha1(b"saturn disc data").digest()
    sys_dir = tmp_path / "roms" / "saturn"
    sys_dir.mkdir(parents=True)
    cpath = sys_dir / "Panzer Dragoon.chd"
    cpath.write_bytes(_build_chd_v5_header(raw_sha1))

    dat = tmp_path / "saturn.dat"
    dat.write_text(
        '<?xml version="1.0"?>\n<datafile>\n'
        '  <game name="Panzer Dragoon">\n'
        f'    <rom name="Panzer Dragoon.chd" size="124" '
        f'crc="" sha1="{raw_sha1.hex()}"/>\n'
        '  </game>\n</datafile>\n',
        encoding="utf-8",
    )

    report = verify_system("saturn", dat, tmp_path / "roms")
    assert report.summary == {"good": 1}
