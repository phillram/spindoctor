"""Media asset downloading and local file management for SpinDoctor."""
from __future__ import annotations

import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

import requests

from .config import Config


# Maps media type → tuple of path segments under <Media>/<System>/
MEDIA_DIR_MAP: dict[str, tuple[str, ...]] = {
    "wheel":      ("Images", "Wheel"),
    "background": ("Images", "Backgrounds"),
    "artwork":    ("Images", "Artwork1"),
    "title":      ("Images", "Artwork2"),
    "snap":       ("Images", "Artwork3"),
    "video":      ("Video",),
    "trailer":    ("Video", "Trailers"),
    "sound":      ("Sound",),
    "theme":      ("Themes",),
}

MEDIA_EXTENSIONS: dict[str, str] = {
    "wheel":      ".png",
    "background": ".jpg",
    "artwork":    ".png",
    "title":      ".png",
    "snap":       ".png",
    "video":      ".mp4",
    "trailer":    ".mp4",
    "sound":      ".mp3",
    "theme":      ".zip",
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
        self._output_override = output_dir_override
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SpinDoctor/1.0"

    def _media_base(self) -> Path:
        if self._output_override:
            return self._output_override / "Media"
        return self.config.media_dir

    def media_path(self, system_name: str, game_name: str, media_type: str) -> Path:
        parts = MEDIA_DIR_MAP.get(media_type, (media_type.capitalize(),))
        ext = MEDIA_EXTENSIONS.get(media_type, "")
        return self._media_base() / system_name / Path(*parts) / f"{game_name}{ext}"

    # ── download from URL ──────────────────────────────────────────────────────

    def download(
        self,
        game_name: str,
        system_name: str,
        media_type: str,
        url: str,
        overwrite: bool = False,
        max_retries: int = 3,
    ) -> DownloadResult:
        if not url:
            return DownloadResult(game_name=game_name, media_type=media_type,
                                  success=False, error="No URL provided")

        dest = self.media_path(system_name, game_name, media_type)

        parsed = urlparse(url)
        url_ext = Path(parsed.path).suffix.lower()
        if url_ext and url_ext != dest.suffix:
            dest = dest.with_suffix(url_ext)

        if dest.exists() and not overwrite:
            return DownloadResult(game_name=game_name, media_type=media_type,
                                  success=True, path=dest, skipped=True)

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Retry with exponential backoff on 429 (Too Many Requests) and 503.
        # Other 4xx/5xx fail fast.
        attempt = 0
        backoff = 1.0
        last_error = ""
        while attempt < max_retries:
            attempt += 1
            try:
                resp = self._session.get(url, timeout=30, stream=True)
                if resp.status_code in (429, 503):
                    retry_after = float(resp.headers.get("Retry-After", backoff))
                    last_error = f"HTTP {resp.status_code}; retry after {retry_after:.1f}s"
                    resp.close()
                    time.sleep(min(retry_after, 30.0))
                    backoff *= 2
                    continue
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return DownloadResult(
                    game_name=game_name, media_type=media_type,
                    success=True, path=dest,
                )
            except requests.RequestException as e:
                last_error = str(e)
                # Network blip — back off and retry
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return DownloadResult(
                    game_name=game_name, media_type=media_type,
                    success=False, error=last_error,
                )

        return DownloadResult(
            game_name=game_name, media_type=media_type,
            success=False, error=f"Gave up after {max_retries} attempts: {last_error}",
        )

    def jobs_for_metadata(
        self,
        game_name: str,
        metadata,
        media_types: Optional[list[str]] = None,
    ) -> list[tuple[str, str, str]]:
        """Return ``[(game_name, media_type, url), ...]`` for downloadable assets."""
        from .config import MEDIA_TYPES
        types = media_types or MEDIA_TYPES

        url_map = {
            "wheel":      getattr(metadata, "wheel_url", ""),
            "background": getattr(metadata, "background_url", ""),
            "artwork":    getattr(metadata, "artwork_url", ""),
            "title":      getattr(metadata, "title_url", ""),
            "snap":       getattr(metadata, "snap_url", ""),
            "video":      getattr(metadata, "video_url", ""),
            "trailer":    getattr(metadata, "trailer_url", ""),
            "sound":      getattr(metadata, "sound_url", ""),
            "theme":      "",  # not provided by APIs
        }
        return [(game_name, mt, url_map.get(mt, "")) for mt in types]

    def download_from_metadata(
        self,
        game_name: str,
        system_name: str,
        metadata,
        media_types: Optional[list[str]] = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> list[DownloadResult]:
        """Sequential download for one game (kept for backwards-compat)."""
        results = []
        for game, media_type, url in self.jobs_for_metadata(
            game_name, metadata, media_types
        ):
            if dry_run:
                dest = self.media_path(system_name, game, media_type)
                note = "[dry-run]" if url else "[no URL available]"
                results.append(DownloadResult(
                    game_name=game, media_type=media_type,
                    success=True, path=dest, skipped=True, error=note,
                ))
            elif url:
                results.append(self.download(game, system_name, media_type, url, overwrite))
            else:
                results.append(DownloadResult(
                    game_name=game, media_type=media_type,
                    success=False, error="No URL from metadata source",
                ))
        return results

    def download_many(
        self,
        jobs: Iterable[tuple[str, str, str]],
        system_name: str,
        overwrite: bool = False,
        max_workers: int = 4,
        on_complete: Optional[Callable[[DownloadResult], None]] = None,
    ) -> list[DownloadResult]:
        """Download many assets concurrently.

        ``jobs`` is an iterable of ``(game_name, media_type, url)``.  Empty URLs
        produce a failed ``DownloadResult`` without hitting the network.
        ``on_complete`` (if provided) is called from the main thread for each
        finished job — useful for advancing a progress bar.
        """
        jobs_list = list(jobs)
        if not jobs_list:
            return []

        results: list[DownloadResult] = []
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            future_to_job = {}
            for game_name, media_type, url in jobs_list:
                if not url:
                    r = DownloadResult(
                        game_name=game_name, media_type=media_type,
                        success=False, error="No URL from metadata source",
                    )
                    results.append(r)
                    if on_complete:
                        on_complete(r)
                    continue
                fut = ex.submit(
                    self.download, game_name, system_name, media_type, url, overwrite,
                )
                future_to_job[fut] = (game_name, media_type)

            for fut in as_completed(future_to_job):
                r = fut.result()
                results.append(r)
                if on_complete:
                    on_complete(r)

        return results

    # ── add local file ─────────────────────────────────────────────────────────

    def add_local_file(
        self,
        source_path: Path,
        game_name: str,
        system_name: str,
        media_type: str,
        move: bool = False,
        overwrite: bool = False,
    ) -> DownloadResult:
        """Copy (or move) a local file into the correct HyperSpin media directory."""
        dest = self.media_path(system_name, game_name, media_type)

        # Use the source file's actual extension
        if source_path.suffix.lower() != dest.suffix.lower():
            dest = dest.with_suffix(source_path.suffix.lower())

        if dest.exists() and not overwrite:
            return DownloadResult(game_name=game_name, media_type=media_type,
                                  success=True, path=dest, skipped=True,
                                  error="File already exists (use --overwrite to replace)")

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if move:
                shutil.move(str(source_path), dest)
            else:
                shutil.copy2(source_path, dest)
            return DownloadResult(game_name=game_name, media_type=media_type,
                                  success=True, path=dest)
        except (OSError, shutil.Error) as e:
            return DownloadResult(game_name=game_name, media_type=media_type,
                                  success=False, error=str(e))
