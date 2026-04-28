"""DAT-based ROM integrity verification."""
from __future__ import annotations

import hashlib
import zipfile
import zlib

from spindoctor import verify as verify_mod
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


# ─── dual-mode (inner / wrapper / auto) archive matching ────────────────────


def _make_zip(zpath, inner_name, payload):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, payload)


def test_auto_falls_back_to_wrapper_for_tosec_style_dat(tmp_path):
    """TOSEC-style DAT — sha1 is over the .zip wrapper bytes."""
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"inner rom payload" * 200
    zpath = sys_dir / "Mario.zip"
    _make_zip(zpath, "Mario.nes", payload)

    wrapper_bytes = zpath.read_bytes()
    wrapper_sha1 = hashlib.sha1(wrapper_bytes).hexdigest()
    wrapper_crc = f"{zlib.crc32(wrapper_bytes) & 0xFFFFFFFF:08x}"
    dat = tmp_path / "tosec.dat"
    _write_dat(dat, [("Mario", "Mario.zip", len(wrapper_bytes),
                      wrapper_crc, wrapper_sha1)])

    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.summary == {"good": 1}
    assert "(wrapper match)" in report.entries[0].detail


def test_inner_only_mode_does_not_fall_back(tmp_path):
    """`inner` mode must not consult wrapper bytes — TOSEC DAT stays unknown."""
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"inner rom payload" * 200
    zpath = sys_dir / "Mario.zip"
    _make_zip(zpath, "Mario.nes", payload)

    wrapper_bytes = zpath.read_bytes()
    wrapper_sha1 = hashlib.sha1(wrapper_bytes).hexdigest()
    dat = tmp_path / "tosec.dat"
    _write_dat(dat, [("Mario", "Mario.zip", len(wrapper_bytes),
                      "00000000", wrapper_sha1)])

    report = verify_system("nes", dat, tmp_path / "roms", match_mode="inner")
    assert report.summary == {"unknown": 1}


def test_inner_dat_classifies_under_all_modes(tmp_path):
    """No-Intro-style DAT — sha1 is over the inner ROM bytes."""
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"inner rom payload" * 200
    zpath = sys_dir / "Mario.zip"
    _make_zip(zpath, "Mario.nes", payload)

    inner_sha1 = hashlib.sha1(payload).hexdigest()
    inner_crc = f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"
    dat = tmp_path / "nointro.dat"
    _write_dat(dat, [("Mario", "Mario.nes", len(payload), inner_crc, inner_sha1)])

    # inner: hits via inner content
    r_inner = verify_system("nes", dat, tmp_path / "roms", match_mode="inner")
    assert r_inner.summary == {"good": 1}

    # auto: same — inner succeeds, no fallback
    r_auto = verify_system("nes", dat, tmp_path / "roms", match_mode="auto")
    assert r_auto.summary == {"good": 1}
    assert "(wrapper match)" not in r_auto.entries[0].detail

    # wrapper: doesn't match (DAT carries inner sha1, file size differs)
    r_wrap = verify_system("nes", dat, tmp_path / "roms", match_mode="wrapper")
    assert r_wrap.summary == {"unknown": 1}


def test_neither_mode_matches_when_dat_has_neither(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"inner rom payload" * 200
    zpath = sys_dir / "Mario.zip"
    _make_zip(zpath, "Mario.nes", payload)

    # DAT with a totally unrelated entry (different size + hashes)
    dat = tmp_path / "other.dat"
    _write_dat(dat, [("Other", "Other.nes", 9999, "deadbeef", "0" * 40)])

    for mode in ("inner", "wrapper", "auto"):
        report = verify_system("nes", dat, tmp_path / "roms", match_mode=mode)
        assert report.summary == {"unknown": 1}, mode


def test_wrapper_mode_skips_archive_parsing(tmp_path, monkeypatch):
    """`wrapper` mode must not invoke `archives.extract_inner_hash`."""
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    payload = b"inner rom payload" * 200
    zpath = sys_dir / "Mario.zip"
    _make_zip(zpath, "Mario.nes", payload)

    wrapper_bytes = zpath.read_bytes()
    wrapper_sha1 = hashlib.sha1(wrapper_bytes).hexdigest()
    dat = tmp_path / "tosec.dat"
    _write_dat(dat, [("Mario", "Mario.zip", len(wrapper_bytes),
                      "00000000", wrapper_sha1)])

    calls = {"n": 0}

    def boom(_path):
        calls["n"] += 1
        raise AssertionError("wrapper mode must not parse archive contents")

    monkeypatch.setattr(verify_mod.archives, "extract_inner_hash", boom)

    report = verify_system("nes", dat, tmp_path / "roms", match_mode="wrapper")
    assert report.summary == {"good": 1}
    assert calls["n"] == 0


def test_skips_spindoctor_manifests(tmp_path):
    sys_dir = tmp_path / "roms" / "nes"
    sys_dir.mkdir(parents=True)
    (sys_dir / "_spindoctor-misplaced-20240101.json").write_text("{}", encoding="utf-8")
    dat = tmp_path / "nes.dat"
    _write_dat(dat, [])
    report = verify_system("nes", dat, tmp_path / "roms")
    assert report.entries == []
