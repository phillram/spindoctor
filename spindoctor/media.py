"""Media asset downloading and local file management for SpinDoctor."""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

import requests

from ._net import make_session
from .config import Config


# Maps media type → tuple of path segments under <Media>/<System>/
MEDIA_DIR_MAP: dict[str, tuple[str, ...]] = {
    "wheel":      ("Images", "Wheel"),
    "background": ("Images", "Backgrounds"),
    "artwork":    ("Images", "Artwork1"),
    "title":      ("Images", "Artwork2"),
    "snap":       ("Images", "Artwork3"),
    "fade":       ("Images", "Artwork4"),
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
    "fade":       ".png",
    "video":      ".mp4",
    "trailer":    ".mp4",
    "sound":      ".mp3",
    "theme":      ".zip",
}


# HyperSpin Main Menu (top-level system tile) media layout.
# Files live under <Media>/Main Menu/<...>/<SYSTEM>.<ext>.
SYSTEM_MEDIA_DIR_MAP: dict[str, tuple[str, ...]] = {
    "wheel":      ("Images", "Wheel"),
    "background": ("Images", "Backgrounds"),
    "video":      ("Video",),
    "theme":      ("Themes",),
}

MAIN_MENU_DIR = "Main Menu"


def _open_in_default_app(path: Path) -> None:
    """Open *path* with the OS default app (best-effort; never raises)."""
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("Couldn't open %s in default app: %s", path, exc)


_VIDEO_CONTAINER_EXTS: frozenset[str] = frozenset({".mp4", ".mkv", ".avi", ".webm", ".mov"})


def _find_ffmpeg(hint: str = "") -> tuple[Optional[str], Optional[str]]:
    """Return (ffmpeg, ffprobe) paths, or (None, None) if unavailable.

    Search order: user-configured hint → PATH → alongside the SpinDoctor
    binary (Windows cabinet installs where ffmpeg.exe lives next to the exe).
    """
    def _probe_for(ffmpeg_bin: str) -> Optional[str]:
        probe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        sibling = Path(ffmpeg_bin).parent / probe_name
        return str(sibling) if sibling.exists() else shutil.which("ffprobe")

    if hint:
        p = Path(hint)
        if p.exists():
            probe = _probe_for(str(p))
            if probe:
                return str(p), probe

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        probe = _probe_for(ffmpeg)
        if probe:
            return ffmpeg, probe

    if sys.platform == "win32":
        here = Path(sys.executable).parent
        fb, fp = here / "ffmpeg.exe", here / "ffprobe.exe"
        if fb.exists() and fp.exists():
            return str(fb), str(fp)

    return None, None


def _audio_needs_reencode(ffprobe: str, path: Path) -> bool:
    """Return True when the first audio stream is not AAC.

    ScreenScraper's video-normalized files use MP3 audio inside an MP4
    container with an mp4a tag (mime_codec mp4a.40.34). AVFoundation on macOS
    and Windows Media Foundation on Windows 7 both expect AAC behind the mp4a
    tag and silently drop the track. Any non-AAC codec in an MP4 container
    gets the same treatment, so we flag everything except "aac".
    """
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a:0", str(path)],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            return False
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            return False
        return streams[0].get("codec_name", "").lower() != "aac"
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return False


def _reencode_audio_aac(ffmpeg: str, path: Path) -> bool:
    """Re-encode the audio track of *path* to AAC in-place, video stream copied.

    Uses a temp file + atomic replace so the original is never clobbered on
    failure. Returns True on success, False on any error.
    """
    tmp = path.with_name(path.stem + "._aactmp" + path.suffix)
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(path),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
             str(tmp)],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, path)
            return True
        _log.debug("ffmpeg audio re-encode failed (rc=%d): %s",
                   result.returncode, result.stderr[-300:] if result.stderr else "")
        return False
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log.debug("ffmpeg audio re-encode error: %s", exc)
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


_FFMPEG_MISSING_WARNING = (
    "ffmpeg not found — video audio may be silent on macOS and Windows 7. "
    "Install ffmpeg and place ffmpeg.exe + ffprobe.exe next to spindoctor.exe "
    "(or set ffmpeg_path in config). See docs/troubleshooting.md."
)


def _maybe_fix_video_audio(path: Path, media_type: str, ffmpeg_hint: str = "") -> Optional[str]:
    """Post-process a downloaded video to ensure audio plays on all platforms.

    Called after every successful video/trailer download. Returns a warning
    string when ffmpeg is unavailable (so callers can surface it to the user),
    or None when the fix succeeded or was not needed.
    """
    if media_type not in ("video", "trailer"):
        return None
    if path.suffix.lower() not in _VIDEO_CONTAINER_EXTS:
        return None
    ffmpeg, ffprobe = _find_ffmpeg(ffmpeg_hint)
    if not (ffmpeg and ffprobe):
        return _FFMPEG_MISSING_WARNING
    if not _audio_needs_reencode(ffprobe, path):
        return None
    if _reencode_audio_aac(ffmpeg, path):
        _log.info("Re-encoded audio to AAC: %s", path.name)
        return None
    warn = f"ffmpeg audio re-encode failed for {path.name} — video may be silent"
    _log.warning(warn)
    return warn


@dataclass
class DownloadResult:
    game_name: str
    media_type: str
    success: bool
    path: Optional[Path] = None
    skipped: bool = False
    error: str = ""
    warning: str = ""


class MediaDownloader:
    def __init__(self, config: Config, output_dir_override: Optional[Path] = None):
        self.config = config
        self._output_override = output_dir_override
        self._session = make_session()

    def _media_base(self) -> Path:
        if self._output_override:
            return self._output_override / "Media"
        return self.config.media_dir

    def media_path(self, system_name: str, game_name: str, media_type: str) -> Path:
        parts = MEDIA_DIR_MAP.get(media_type, (media_type.capitalize(),))
        ext = MEDIA_EXTENSIONS.get(media_type, "")
        return self._media_base() / system_name / Path(*parts) / f"{game_name}{ext}"

    def system_media_path(self, system_name: str, media_type: str) -> Path:
        """Return the HyperSpin Main Menu media path for *system_name*.

        Layout: ``<Media>/Main Menu/<Type>/<System>.<ext>``
        """
        parts = SYSTEM_MEDIA_DIR_MAP.get(
            media_type, MEDIA_DIR_MAP.get(media_type, (media_type.capitalize(),))
        )
        ext = MEDIA_EXTENSIONS.get(media_type, "")
        return (
            self._media_base() / MAIN_MENU_DIR
            / Path(*parts) / f"{system_name}{ext}"
        )

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
        return self._download_to(
            dest, url, label=game_name, media_type=media_type,
            overwrite=overwrite, max_retries=max_retries,
        )

    def download_to_path(
        self,
        dest: Path,
        url: str,
        *,
        label: str = "",
        media_type: str = "",
        overwrite: bool = False,
        max_retries: int = 3,
    ) -> DownloadResult:
        """Download a URL to a specific destination path (any HyperSpin location)."""
        if not url:
            return DownloadResult(game_name=label, media_type=media_type,
                                  success=False, error="No URL provided")
        return self._download_to(dest, url, label=label, media_type=media_type,
                                 overwrite=overwrite, max_retries=max_retries)

    def _download_to(
        self,
        dest: Path,
        url: str,
        *,
        label: str,
        media_type: str,
        overwrite: bool,
        max_retries: int,
    ) -> DownloadResult:
        parsed = urlparse(url)
        url_ext = Path(parsed.path).suffix.lower()
        _MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp",
                       ".mp4", ".webm", ".avi", ".mkv", ".flv", ".mpg", ".mpeg",
                       ".zip", ".mp3", ".ogg", ".wav"}
        if url_ext and url_ext in _MEDIA_EXTS and url_ext != dest.suffix:
            dest = dest.with_suffix(url_ext)

        if dest.exists() and not overwrite:
            return DownloadResult(game_name=label, media_type=media_type,
                                  success=True, path=dest, skipped=True)

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Sidecar partial file. Bytes accumulate here; on success we atomically
        # rename to *dest*.  An interrupted run leaves only the .part behind, so
        # the next run can resume via HTTP Range without serving a half-written
        # file as if it were complete.
        part = dest.with_name(dest.name + ".part")
        if overwrite and part.exists():
            try:
                part.unlink()
            except OSError:
                pass

        # Retry with exponential backoff on 429 (Too Many Requests) and 503.
        # Other 4xx/5xx fail fast.
        attempt = 0
        backoff = 1.0
        last_error = ""
        while attempt < max_retries:
            attempt += 1
            try:
                existing = part.stat().st_size if part.exists() else 0
                kwargs: dict = {"timeout": 30, "stream": True}
                if existing > 0:
                    kwargs["headers"] = {"Range": f"bytes={existing}-"}
                resp = self._session.get(url, **kwargs)

                if resp.status_code in (429, 503):
                    retry_after = float(resp.headers.get("Retry-After", backoff))
                    last_error = f"HTTP {resp.status_code}; retry after {retry_after:.1f}s"
                    resp.close()
                    time.sleep(min(retry_after, 30.0))
                    backoff *= 2
                    continue

                if resp.status_code == 416 and existing > 0:
                    # Range unsatisfiable — partial is stale or larger than the
                    # current resource. Drop it and retry from scratch.
                    resp.close()
                    try:
                        part.unlink()
                    except OSError:
                        pass
                    last_error = "HTTP 416; resetting partial download"
                    continue

                resp.raise_for_status()

                # 206 → server honored Range; append. Otherwise (incl. 200)
                # the server is sending the full body, so truncate.
                mode = "ab" if (resp.status_code == 206 and existing > 0) else "wb"
                with open(part, mode) as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)

                os.replace(part, dest)
                audio_warn = _maybe_fix_video_audio(
                    dest, media_type,
                    getattr(self.config, "ffmpeg_path", ""),
                )
                return DownloadResult(
                    game_name=label, media_type=media_type,
                    success=True, path=dest,
                    warning=audio_warn or "",
                )
            except requests.RequestException as e:
                last_error = str(e)
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return DownloadResult(
                    game_name=label, media_type=media_type,
                    success=False, error=last_error,
                )
            except OSError as e:
                # Disk full, antivirus lock, permission denied, etc. The
                # atomic-write contract guarantees the destination file
                # (if any pre-existed) is intact — os.replace is atomic
                # on POSIX and on Windows since Python 3.3. Surface the
                # OS error as a clean DownloadResult so callers don't
                # see a stack trace; leave the .part file in place so
                # the next run can resume.
                return DownloadResult(
                    game_name=label, media_type=media_type,
                    success=False, error=f"OSError: {e}",
                )

        return DownloadResult(
            game_name=label, media_type=media_type,
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
            "fade":       getattr(metadata, "fade_url", ""),
            "video":      getattr(metadata, "video_url", ""),
            "trailer":    getattr(metadata, "trailer_url", ""),
            "sound":      getattr(metadata, "sound_url", ""),
            "theme":      getattr(metadata, "theme_url", ""),
        }
        return [(game_name, mt, url_map.get(mt, "")) for mt in types]

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

    # ── multi-candidate picker ────────────────────────────────────────────────

    def preview_candidate(self, candidate, idx: int = 0) -> Optional[Path]:
        """Download a media candidate to a temp file and open it with the OS app.

        Returns the temp file path on success, or None if download failed.
        Caller owns the temp file lifecycle (kept for the duration of the
        picker session so the user can compare candidates).
        """
        url = candidate.url
        if not url:
            return None
        ext = Path(urlparse(url).path).suffix or f".{candidate.format or 'bin'}"
        tmp_dir = Path(tempfile.gettempdir()) / "spindoctor_preview"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"candidate_{idx}_{abs(hash(url))}{ext}"
        if not tmp_path.exists():
            r = self.download_to_path(
                tmp_path, url, label="preview",
                media_type=candidate.source_type, overwrite=False,
            )
            if not r.success:
                return None
        _open_in_default_app(tmp_path)
        return tmp_path

    def download_with_picker(
        self,
        item_name: str,
        system_name: str,
        media_type: str,
        candidates: list,
        dest: Path,
        *,
        interactive: bool = True,
        skip_ambiguous: bool = False,
        overwrite: bool = False,
    ) -> DownloadResult:
        """Pick a candidate (interactive if needed) and download it to *dest*.

        Designed for both per-game and system-level media: caller computes the
        destination path (via ``media_path`` or ``system_media_path``) and
        passes the candidate list from ScreenScraper.

        ``skip_ambiguous`` returns a "skipped by user" result when there are
        multiple candidates, instead of either prompting or auto-picking.
        Used by non-TTY callers (GUI subprocesses, cron, CI).

        Returns a DownloadResult.  When the user skips, returns a skipped
        result with ``error`` set to "skipped by user".
        """
        from .matcher import pick_media

        if not candidates:
            return DownloadResult(game_name=item_name, media_type=media_type,
                                  success=False, error="No candidates available")

        chosen = pick_media(
            item_name, media_type, candidates, system_name,
            interactive=interactive,
            skip_ambiguous=skip_ambiguous,
            previewer=(self.preview_candidate if interactive else None),
        )
        if chosen is None:
            return DownloadResult(
                game_name=item_name, media_type=media_type,
                success=False, skipped=True, error="skipped by user",
            )
        return self.download_to_path(
            dest, chosen.url, label=item_name, media_type=media_type,
            overwrite=overwrite,
        )

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
