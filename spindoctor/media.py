"""Media asset downloading for SpinDoctor."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from .config import Config


MEDIA_DIR_MAP = {
    "wheel": ("Images", "Wheel"),
    "background": ("Images", "Backgrounds"),
    "artwork": ("Images", "Artwork1"),
    "video": ("Video",),
    "sound": ("Sound",),
    "theme": ("Themes",),
}

MEDIA_EXTENSIONS = {
    "wheel": ".png",
    "background": ".jpg",
    "artwork": ".png",
    "video": ".mp4",
    "sound": ".mp3",
    "theme": ".zip",
}


@dataclass
class DownloadResult:
    game_name: str
    media_type: str
    success: bool
    path: Optional[Path] = None
    skipped: bool = False
    error: str = ""


class MediaDownloader:
    def __init__(self, config: Config, output_dir_override: Optional[Path] = None):
        self.config = config
        self._output_dir_override = output_dir_override
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"

    def _media_base(self) -> Path:
        if self._output_dir_override:
            return self._output_dir_override / "Media"
        return self.config.media_dir

    def _media_path(self, system_name: str, game_name: str, media_type: str) -> Path:
        parts = MEDIA_DIR_MAP.get(media_type, (media_type.capitalize(),))
        ext = MEDIA_EXTENSIONS.get(media_type, "")
        return self._media_base() / system_name / Path(*parts) / f"{game_name}{ext}"

    def download(
        self,
        game_name: str,
        system_name: str,
        media_type: str,
        url: str,
        overwrite: bool = False,
    ) -> DownloadResult:
        if not url:
            return DownloadResult(
                game_name=game_name,
                media_type=media_type,
                success=False,
                error="No URL provided",
            )

        dest = self._media_path(system_name, game_name, media_type)

        # Infer extension from URL if possible
        parsed = urlparse(url)
        url_ext = Path(parsed.path).suffix.lower()
        if url_ext and url_ext != dest.suffix:
            dest = dest.with_suffix(url_ext)

        if dest.exists() and not overwrite:
            return DownloadResult(
                game_name=game_name,
                media_type=media_type,
                success=True,
                path=dest,
                skipped=True,
            )

        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            resp = self._session.get(url, timeout=30, stream=True)
            resp.raise_for_status()

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            return DownloadResult(
                game_name=game_name,
                media_type=media_type,
                success=True,
                path=dest,
            )
        except requests.RequestException as e:
            return DownloadResult(
                game_name=game_name,
                media_type=media_type,
                success=False,
                error=str(e),
            )

    def download_from_metadata(
        self,
        game_name: str,
        system_name: str,
        metadata,
        media_types: Optional[list[str]] = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> list[DownloadResult]:
        from .config import MEDIA_TYPES

        types = media_types or MEDIA_TYPES
        results = []
        url_map = {
            "wheel": getattr(metadata, "wheel_url", ""),
            "background": getattr(metadata, "background_url", ""),
            "artwork": getattr(metadata, "artwork_url", ""),
            "video": getattr(metadata, "video_url", ""),
            "sound": getattr(metadata, "sound_url", ""),
        }

        for media_type in types:
            url = url_map.get(media_type, "")
            if dry_run:
                dest = self._media_path(system_name, game_name, media_type)
                results.append(
                    DownloadResult(
                        game_name=game_name,
                        media_type=media_type,
                        success=True,
                        path=dest,
                        skipped=True,
                        error="[dry-run]" if url else "[no URL available]",
                    )
                )
            else:
                if url:
                    results.append(
                        self.download(game_name, system_name, media_type, url, overwrite)
                    )
                    time.sleep(0.2)
                else:
                    results.append(
                        DownloadResult(
                            game_name=game_name,
                            media_type=media_type,
                            success=False,
                            error="No URL available from metadata source",
                        )
                    )
        return results
