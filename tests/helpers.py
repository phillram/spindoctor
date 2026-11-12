"""Explicit fixture builders shared by tests; never imported by conftest."""
from datetime import datetime
from pathlib import Path

from spindoctor.config import Config, save_config
from spindoctor.database import GameEntry, HyperspinDatabase


def write_bytes(path, data=b"original"):
    """Seed a file and its parents, returning the path for later assertions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def freeze_time(monkeypatch, *modules):
    """Give collision tests the same timestamp for every manifest or backup."""
    class Frozen:
        @classmethod
        def now(cls):
            return datetime(2026, 11, 4, 12, 0, 0)

    for module in modules:
        monkeypatch.setattr(module, "datetime", Frozen)


def encode_legacy_text(text, encoding):
    """Encode fixture bytes, including the BOM expected for UTF-16 BE."""
    data = text.encode(encoding, errors="surrogateescape")
    return b"\xfe\xff" + data if encoding == "utf-16-be" else data


def build_nes_library(tmp_path: Path) -> Config:
    """Create and save the three-game NES install used by edit and CLI tests.

    This writes config.json as well as the database, ROMs, wheels and snaps;
    callers must opt into config isolation before invoking it.
    """
    roms_dir = tmp_path / "roms"
    hs_dir = tmp_path / "hs"
    (roms_dir / "nes").mkdir(parents=True)
    db_dir = hs_dir / "Databases" / "nes"
    media_dir = hs_dir / "Media" / "nes"
    db_dir.mkdir(parents=True)
    (media_dir / "Images" / "Wheel").mkdir(parents=True)
    (media_dir / "Images" / "Artwork3").mkdir(parents=True)

    games = [
        GameEntry(name="mario", description="Super Mario", manufacturer="Nintendo",
                  year="1985", genre="Platformer", rating=""),
        GameEntry(name="zelda", description="Zelda", manufacturer="Nintendo",
                  year="1986", genre="Action", rating="5"),
        GameEntry(name="contra", description="Contra", manufacturer="Konami",
                  year="1988", genre="Action", rating=""),
    ]
    for game in games:
        (roms_dir / "nes" / f"{game.name}.nes").write_text("rom", encoding="utf-8")
        (media_dir / "Images" / "Wheel" / f"{game.name}.png").write_bytes(b"wheel")
        (media_dir / "Images" / "Artwork3" / f"{game.name}.png").write_bytes(b"snap")

    db = HyperspinDatabase("nes", db_dir / "nes.xml")
    for game in games:
        db.upsert_game(game)
    db.save()

    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs_dir)
    save_config(cfg)
    return cfg
