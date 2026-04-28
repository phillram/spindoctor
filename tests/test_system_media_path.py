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
