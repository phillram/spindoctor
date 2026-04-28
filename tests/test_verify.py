"""DAT-based ROM integrity verification."""
from __future__ import annotations

import hashlib
import zlib

from spindoctor.verify import verify_system


def _write_dat(path, entries):
    """*entries* is a list of (game_name, rom_name, size, crc, sha1)."""
    lines = ['<?xml version="1.0"?>', "<datafile>"]
    for name, rom, size, crc, sha1 in entries:
        lines.append(f'  <game name="{name}">')
        lines.append(
            f'    <rom name="{rom}" size="{size}" '
            f'crc="{crc or ""}" sha1="{sha1 or ""}"/>'
        )
        lines.append("  </game>")
    lines.append("</datafile>")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_good_match(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"perfect bytes" * 100
    (sys_dir / "Mario.nes").write_bytes(payload)

    sha1 = hashlib.sha1(payload).hexdigest()
    crc = f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"
    dat = tmp_path / "nes.dat"
    _write_dat(dat, [("Mario", "Mario.nes", len(payload), crc, sha1)])

    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.summary == {"good": 1}


def test_renamed_file_classified(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"perfect bytes" * 100
    (sys_dir / "Mario_Bad_Name.nes").write_bytes(payload)

    sha1 = hashlib.sha1(payload).hexdigest()
    crc = f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"
    dat = tmp_path / "nes.dat"
    _write_dat(dat, [("Mario", "Mario.nes", len(payload), crc, sha1)])

    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.summary == {"renamed": 1}
    assert report.entries[0].expected_name == "Mario.nes"


def test_bad_dump_classified(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    correct = b"correct bytes" * 100
    bad = b"corrupted bx!" * 100   # same length, different content
    (sys_dir / "Mario.nes").write_bytes(bad)

    sha1 = hashlib.sha1(correct).hexdigest()
    crc = f"{zlib.crc32(correct) & 0xFFFFFFFF:08x}"
    dat = tmp_path / "nes.dat"
    _write_dat(dat, [("Mario", "Mario.nes", len(correct), crc, sha1)])

    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.summary == {"bad": 1}


def test_unknown_file_classified(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Homebrew.nes").write_bytes(b"x" * 999)

    dat = tmp_path / "nes.dat"
    _write_dat(dat, [("Mario", "Mario.nes", 1234, "deadbeef",
                      "0" * 40)])

    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.summary == {"unknown": 1}


def test_skips_spindoctor_manifests(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "_spindoctor-misplaced-20240101.json").write_text("{}", encoding="utf-8")
    dat = tmp_path / "nes.dat"
    _write_dat(dat, [])
    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.entries == []
