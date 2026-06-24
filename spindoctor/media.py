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


_WIN_FILENAME_FORBIDDEN = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")

# Windows device names that cannot be used as filenames regardless of extension.
# "NUL.png" writes to the null device; "CON.mp4" maps to the console, etc.
_WIN_RESERVED_NAMES: frozenset = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM0", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT0", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def _win_safe_stem(name: str) -> str:
    """Strip Windows-invalid characters from *name* to produce a safe filename stem.

    Mirrors the function of the same name in rocketlauncher.py — kept local
    here to avoid a circular import.  HyperSpin itself applies the same
    stripping when resolving media filenames from game database names, so
    ``media_path()`` must use this function to produce paths that HyperSpin
    can actually find.
    """
    out = name
    for ch in _WIN_FILENAME_FORBIDDEN:
        out = out.replace(ch, "")
    out = out.strip().rstrip(".")
    if out.upper() in _WIN_RESERVED_NAMES:
        out = out + "_"
    return out


def _convert_to_png_inplace(path: Path) -> None:
    """Convert *path* to real PNG bytes in-place when Pillow is available.

    HyperSpin's Wheel / Artwork / Snap folders only load .png files.  Steam
    serves these as JPEG, so after downloading we need either actual PNG bytes
    or at minimum the .png extension (Windows GDI+ reads format from magic
    bytes, so JPEG content under a .png name works on the cabinet too, but
    real PNG is cleaner and avoids any renderer edge-cases).

    No-op when: Pillow is not installed, the file is already PNG, or any
    error occurs during conversion (the JPEG-named-.png fallback still loads).
    """
    try:
        from PIL import Image  # type: ignore[import]
    except ImportError:
        return
    try:
        with Image.open(path) as img:
            if img.format == "PNG":
                return
            out = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            out.save(path, format="PNG")
    except Exception as exc:
        _log.warning("PNG conversion failed for %s: %s", path, exc)


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

# HLS downloads below this size or duration are likely truncated (ffmpeg exited
# 0 with only the first 1-2 segments).  A Steam trailer at any reasonable quality
# runs well over 5 MB / 30 s; flag anything smaller so the user gets an
# actionable warning.
_HLS_MIN_BYTES: int = 5_000_000
_HLS_MIN_DURATION_SECS: float = 30.0


def _probe_hls_duration(path: Path, ffprobe: Optional[str]) -> Optional[float]:
    """Return the video duration in seconds via ffprobe, or None if unavailable."""
    if not ffprobe:
        return None
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0:
            return float((r.stdout or b"").strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _hls_truncation_warning(
    label: str, size: int, duration: Optional[float], stderr_text: str
) -> str:
    """Return a non-empty warning string when the HLS output looks truncated."""
    size_ok = size >= _HLS_MIN_BYTES
    dur_ok = duration is None or duration >= _HLS_MIN_DURATION_SECS
    if size_ok and dur_ok:
        return ""
    reasons: list[str] = []
    if not size_ok:
        reasons.append(f"{size / 1_000_000:.1f} MB")
    if not dur_ok:
        assert duration is not None
        mins, secs = divmod(int(duration), 60)
        reasons.append(f"{mins}:{secs:02d}" if mins else f"{int(duration)}s")
    warn = (
        f"HLS output looks truncated ({', '.join(reasons)} — expected ≥30 s / 5 MB "
        f"for a full trailer). Re-run with --overwrite --apply or try a different "
        f"candidate index. See docs/troubleshooting.md."
    )
    _log.warning("Possible HLS truncation for %s (%d bytes, duration=%s):\n%s",
                 label, size, f"{duration:.1f}s" if duration is not None else "unknown",
                 stderr_text[-2000:])
    return warn


def _pick_hls_variant(master_url: str, max_height: int, session) -> str:
    """Return the variant playlist URL whose height best fits within max_height.

    Fetches the master HLS playlist, parses EXT-X-STREAM-INF entries, and
    returns the highest-bandwidth variant whose height <= max_height.  Falls
    back to master_url on any parse/network error so the caller can still
    attempt a download (ffmpeg will pick the best quality itself).
    """
    try:
        resp = session.get(master_url, timeout=15)
        resp.raise_for_status()
        base = master_url.split("?")[0].rsplit("/", 1)[0]
        variants: list[tuple[int, int, str]] = []  # (bandwidth, height, url)
        lines = resp.text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("#EXT-X-STREAM-INF:"):
                bandwidth = height = 0
                for part in line[18:].split(","):
                    k, _, v = part.partition("=")
                    if k == "BANDWIDTH":
                        try:
                            bandwidth = int(v)
                        except ValueError:
                            pass
                    elif k == "RESOLUTION" and "x" in v:
                        try:
                            height = int(v.split("x")[-1])
                        except ValueError:
                            pass
                i += 1
                while i < len(lines) and (not lines[i].strip() or lines[i].startswith("#")):
                    i += 1
                if i < len(lines):
                    uri = lines[i].strip()
                    if not uri.startswith("http"):
                        uri = f"{base}/{uri}"
                    if bandwidth and height:
                        variants.append((bandwidth, height, uri))
            i += 1
        if not variants:
            return master_url
        eligible = [(bw, h, url) for bw, h, url in variants if h <= max_height]
        if eligible:
            return max(eligible, key=lambda x: x[0])[2]
        # All variants exceed max_height — use the smallest available.
        return min(variants, key=lambda x: x[1])[2]
    except Exception:
        _log.debug("HLS variant parse failed for %s — using master", master_url)
        return master_url


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
    file_size_bytes: Optional[int] = None
    duration_secs: Optional[float] = None


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
        # Strip Windows-invalid characters (especially ':') from the filename
        # stem — HyperSpin applies the same rule when resolving media lookups,
        # and Windows NTFS treats colons as Alternate Data Stream separators
        # (e.g. "Submachine: Legacy.png" → 0-byte "Submachine" + ADS).
        safe = _win_safe_stem(game_name)
        return self._media_base() / system_name / Path(*parts) / f"{safe}{ext}"

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
            / Path(*parts) / f"{_win_safe_stem(system_name)}{ext}"
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
        hls_max_height: Optional[int] = None,
    ) -> DownloadResult:
        """Download a URL to a specific destination path (any HyperSpin location)."""
        if not url:
            return DownloadResult(game_name=label, media_type=media_type,
                                  success=False, error="No URL provided")
        return self._download_to(dest, url, label=label, media_type=media_type,
                                 overwrite=overwrite, max_retries=max_retries,
                                 hls_max_height=hls_max_height)

    def _download_hls(
        self,
        dest: Path,
        url: str,
        *,
        label: str,
        media_type: str,
        overwrite: bool,
        hls_max_height: Optional[int] = None,
    ) -> DownloadResult:
        """Download an HLS (.m3u8) stream to an MP4 file via ffmpeg."""
        ffmpeg_hint = getattr(self.config, "ffmpeg_path", "")
        ffmpeg, ffprobe = _find_ffmpeg(ffmpeg_hint)
        if not ffmpeg:
            return DownloadResult(
                game_name=label, media_type=media_type, success=False,
                error=(
                    "This Steam video uses HLS streaming (no direct MP4 available). "
                    "Install ffmpeg and place ffmpeg.exe + ffprobe.exe next to "
                    "spindoctor.exe to download it. See docs/troubleshooting.md."
                ),
            )

        dest = dest.with_suffix(".mp4")
        if dest.exists() and not overwrite:
            return DownloadResult(game_name=label, media_type=media_type,
                                  success=True, path=dest, skipped=True)

        if hls_max_height is not None:
            url = _pick_hls_variant(url, hls_max_height, self._session)

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.stem + "._hlstmp.mp4")
        try:
            # -protocol_whitelist: ffmpeg's default whitelist excludes https, so
            #   without this flag it cannot fetch segment URLs embedded in the
            #   variant playlist on Akamai's CDN — causing a silent early abort.
            # -c copy: stream-copy both video and audio without re-encoding.
            #   For fMP4/CMAF HLS the audio is already in MP4-ASC format so no
            #   bitstream filter is needed; the MP4 muxer handles the ADTS→ASC
            #   conversion automatically for TS-based HLS.  Re-encoding with
            #   -c:a aac introduced timestamp discontinuities that caused ffmpeg
            #   to exit 0 with only the first 2-3 seconds muxed.
            # -movflags +faststart: writes moov atom at the start so WMP can play
            #   the file without seeking to the end first.
            cmd = [
                ffmpeg, "-y",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-i", url,
                "-c", "copy",
                "-movflags", "+faststart",
                str(tmp),
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            stderr_text = (result.stderr or b"").decode("utf-8", errors="replace")
            if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                size = tmp.stat().st_size
                _log.debug("ffmpeg HLS OK for %s (%d bytes):\n%s",
                           label, size, stderr_text[-2000:])
                os.replace(tmp, dest)
                duration = _probe_hls_duration(dest, ffprobe)
                warn = _hls_truncation_warning(label, size, duration, stderr_text)
                return DownloadResult(game_name=label, media_type=media_type,
                                      success=True, path=dest, warning=warn,
                                      file_size_bytes=size, duration_secs=duration)
            _log.error("ffmpeg HLS failed (rc=%d) for %s:\n%s",
                       result.returncode, label, stderr_text)
            return DownloadResult(
                game_name=label, media_type=media_type, success=False,
                error=f"ffmpeg HLS download failed (rc={result.returncode}): "
                      f"{stderr_text[-400:]}",
            )
        except subprocess.TimeoutExpired:
            return DownloadResult(game_name=label, media_type=media_type,
                                  success=False, error="ffmpeg HLS download timed out")
        except OSError as exc:
            return DownloadResult(game_name=label, media_type=media_type,
                                  success=False, error=f"OSError: {exc}")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _download_to(
        self,
        dest: Path,
        url: str,
        *,
        label: str,
        media_type: str,
        overwrite: bool,
        max_retries: int,
        hls_max_height: Optional[int] = None,
    ) -> DownloadResult:
        parsed = urlparse(url)
        url_ext = Path(parsed.path).suffix.lower()

        if url_ext == ".m3u8":
            return self._download_hls(dest, url, label=label,
                                      media_type=media_type, overwrite=overwrite,
                                      hls_max_height=hls_max_height)

        # Normalize destination extension to lowercase — HyperSpin filename
        # lookups are case-sensitive and expect lower-case extensions.
        if dest.suffix and dest.suffix != dest.suffix.lower():
            dest = dest.with_suffix(dest.suffix.lower())


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
                    _ra = resp.headers.get("Retry-After", "")
                    try:
                        retry_after = float(_ra) if _ra else backoff
                    except ValueError:
                        retry_after = backoff
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

                # Check for empty body BEFORE replacing dest so a server that
                # returns HTTP 200 with 0 bytes can't overwrite a valid file.
                try:
                    if part.stat().st_size == 0:
                        part.unlink(missing_ok=True)
                        last_error = "server returned an empty response (0 bytes)"
                        if attempt < max_retries:
                            time.sleep(backoff)
                            backoff *= 2
                            continue
                        return DownloadResult(
                            game_name=label, media_type=media_type,
                            success=False, error=last_error,
                        )
                except OSError:
                    pass

                os.replace(part, dest)

                if dest.suffix == ".png":
                    _convert_to_png_inplace(dest)

                audio_warn = _maybe_fix_video_audio(
                    dest, media_type,
                    getattr(self.config, "ffmpeg_path", ""),
                )
                return DownloadResult(
                    game_name=label, media_type=media_type,
                    success=True, path=dest,
                    warning=audio_warn or "",
                )
            except requests.HTTPError as e:
                # Non-retriable HTTP error (4xx/5xx other than 429/503/416,
                # which are handled above). A 404 or 500 won't go away on
                # retry — fail immediately so the caller gets a fast result
                # instead of waiting through max_retries × backoff.
                return DownloadResult(
                    game_name=label, media_type=media_type,
                    success=False, error=str(e),
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
        # _download_hls saves HLS streams as .mp4, not .m3u8 — use the same
        # extension so tmp_path matches the file the downloader actually creates.
        if ext == ".m3u8":
            ext = ".mp4"
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
