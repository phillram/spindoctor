"""Main Menu (system-level) media path layout."""
from __future__ import annotations

from spindoctor.config import Config
from spindoctor.media import MediaDownloader


def test_system_media_path_layout(tmp_path):
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)

    wheel = dl.system_media_path("Sony Playstation 3", "wheel")
    assert wheel == tmp_path / "Media" / "Main Menu" / "Images" / "Wheel" / "Sony Playstation 3.png"

    bg = dl.system_media_path("Sony Playstation 3", "background")
    assert bg == tmp_path / "Media" / "Main Menu" / "Images" / "Backgrounds" / "Sony Playstation 3.jpg"

    video = dl.system_media_path("Sony Playstation 3", "video")
    assert video == tmp_path / "Media" / "Main Menu" / "Video" / "Sony Playstation 3.mp4"

    theme = dl.system_media_path("Sony Playstation 3", "theme")
    assert theme == tmp_path / "Media" / "Main Menu" / "Themes" / "Sony Playstation 3.zip"


def test_media_path_sanitizes_colon_in_game_name(tmp_path):
    """Colon in a game name must be stripped — NTFS treats it as an ADS separator."""
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)
    path = dl.media_path("PC Games", "Submachine: Legacy", "wheel")
    assert path.name == "Submachine Legacy.png"


def test_media_path_sanitizes_reserved_name(tmp_path):
    """A game named exactly 'NUL' must become 'NUL_.png' to avoid the null device."""
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)
    path = dl.media_path("PC Games", "NUL", "wheel")
    assert path.name == "NUL_.png"


def test_system_media_path_sanitizes_slash_in_system_name(tmp_path):
    """Slash in a system name must be stripped before building the path."""
    cfg = Config()
    cfg.hyperspin_dir = str(tmp_path)
    dl = MediaDownloader(cfg)
    path = dl.system_media_path("PC/DOS Games", "wheel")
    assert path.name == "PCDOS Games.png"
