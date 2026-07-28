"""audit_system ROM↔DB matching: case-insensitivity and deterministic order."""
from __future__ import annotations

from spindoctor.audit import audit_system
from spindoctor.config import Config


def _cabinet(tmp_path, rom_stems, db_names):
    roms = tmp_path / "roms"
    hs = tmp_path / "hs"
    (roms / "NES").mkdir(parents=True)
    for stem in rom_stems:
        (roms / "NES" / f"{stem}.nes").write_bytes(b"x")
    dbdir = hs / "Databases" / "NES"
    dbdir.mkdir(parents=True)
    games = "".join(f'<game name="{n}"/>' for n in db_names)
    (dbdir / "NES.xml").write_text(f"<menu>{games}</menu>", encoding="utf-8")
    return Config(roms_dir=str(roms), hyperspin_dir=str(hs))


def test_audit_matches_rom_and_db_case_insensitively(tmp_path):
    """A ROM "Pac-Man" and DB entry "pac-man" are the same game, not two
    separate problems (NTFS + HyperSpin are case-insensitive)."""
    cfg = _cabinet(tmp_path, rom_stems=["Pac-Man"], db_names=["pac-man"])
    result = audit_system("NES", cfg, check_media_flag=False,
                          check_mame_controls=False)
    assert result.roms_in_db == 1
    assert result.roms_not_in_db == 0
    matched = [e for e in result.entries if e.rom_exists and e.in_database]
    assert len(matched) == 1
    # Canonical display name prefers the DB spelling.
    assert matched[0].rom_name == "pac-man"


def test_audit_entry_order_is_deterministic(tmp_path):
    """Entries come out sorted (case-folded), so the fuzzy pass is reproducible."""
    cfg = _cabinet(
        tmp_path,
        rom_stems=["Zelda", "Metroid", "Contra"],
        db_names=["Metroid", "Kirby"],
    )
    result = audit_system("NES", cfg, check_media_flag=False,
                          check_mame_controls=False)
    names = [e.rom_name for e in result.entries]
    assert names == sorted(names, key=str.lower)
