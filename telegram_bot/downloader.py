from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
import yt_dlp
from PIL import Image, UnidentifiedImageError

from .media import entry_source_url, source_image_url
from .models import DownloadBundle, ExtractedMedia, MediaItem, MediaType

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_image(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise DownloadError("corrupted_media", "image file is empty or missing")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise DownloadError("corrupted_media", "image could not be decoded") from exc


def probe_video(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise DownloadError("corrupted_media", "video file is empty or missing")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise DownloadError("ffprobe_error", result.stderr[-500:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DownloadError("ffprobe_error", "ffprobe returned invalid JSON") from exc
    if not any(stream.get("codec_type") == "video" for stream in payload.get("streams", [])):
        raise DownloadError("corrupted_media", "video stream is missing")
    return payload


def _newest_media_file(directory: Path, index: int) -> Path | None:
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        return None
    preferred = [
        path
        for path in candidates
        if path.stem.startswith(f"item_{index:04d}") or path.stem.startswith(f"video_{index:04d}")
    ]
    return max(preferred or candidates, key=lambda path: path.stat().st_mtime)


class MediaDownloader:
    def __init__(self, work_root: Path, timeout: int = 300, concurrency: int = 3):
        self.work_root = work_root
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.work_root.mkdir(parents=True, exist_ok=True)

    def _download_with_ytdlp_sync(self, source_url: str, directory: Path, index: int, media_type: MediaType) -> Path:
        output_template = str(directory / f"item_{index:04d}.%(ext)s")
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": output_template,
            "retries": 2,
            "socket_timeout": self.timeout,
            "restrictfilenames": True,
            "noplaylist": True,
        }
        if media_type == MediaType.VIDEO:
            options.update(
                {
                    "format": "bestvideo*+bestaudio/best",
                    "merge_output_format": "mp4",
                    "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
                    "postprocessor_args": {"ffmpeg": ["-movflags", "+faststart"]},
                }
            )
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([source_url])
        path = _newest_media_file(directory, index)
        if path is None:
            raise DownloadError("download_error", "yt-dlp did not create a media file")
        return path

    async def _http_image_fallback(self, source_url: str, destination: Path) -> Path:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
                async with client.stream("GET", source_url, headers={"User-Agent": "Mozilla/5.0"}) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith("image/"):
                        raise DownloadError("corrupted_media", "fallback URL did not return an image")
                    with destination.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
        except httpx.HTTPError as exc:
            raise DownloadError("network_error", str(exc)) from exc
        validate_image(destination)
        return destination

    async def _download_photo(self, entry: dict[str, Any], directory: Path, index: int, fallback_url: str) -> Path:
        source_url = source_image_url(entry)
        if not source_url:
            raise DownloadError("photo_extraction_error", "no extracted image URL was returned")
        try:
            path = await asyncio.wait_for(
                asyncio.to_thread(self._download_with_ytdlp_sync, source_url, directory, index, MediaType.PHOTO),
                timeout=self.timeout,
            )
            validate_image(path)
            return path
        except Exception as primary_error:
            logger.warning("yt-dlp photo download failed; using extracted URL fallback: %s", primary_error)
            fallback_path = directory / f"item_{index:04d}.jpg"
            return await self._http_image_fallback(source_url, fallback_path)

    async def _download_video(self, entry: dict[str, Any], directory: Path, index: int, fallback_url: str) -> Path:
        source_url = entry_source_url(entry, fallback_url)
        try:
            path = await asyncio.wait_for(
                asyncio.to_thread(self._download_with_ytdlp_sync, source_url, directory, index, MediaType.VIDEO),
                timeout=self.timeout,
            )
            probe_video(path)
            return path
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError("video_extraction_error", str(exc)) from exc

    async def download(self, url: str, extracted: ExtractedMedia) -> DownloadBundle:
        async with self.semaphore:
            job_directory = Path(tempfile.mkdtemp(prefix="instagram_", dir=self.work_root))
            items: list[MediaItem] = []
            try:
                for index, entry in enumerate(extracted.entries):
                    entry_type = MediaType.PHOTO if extracted.media_type == MediaType.CAROUSEL and source_image_url(entry) else extracted.media_type
                    if extracted.media_type == MediaType.CAROUSEL:
                        from .media import classify_entry

                        entry_type = classify_entry(entry)
                    if entry_type == MediaType.PHOTO:
                        path = await self._download_photo(entry, job_directory, index, url)
                    else:
                        path = await self._download_video(entry, job_directory, index, url)
                    items.append(
                        MediaItem(
                            index=index,
                            media_type=entry_type,
                            path=path,
                            source_url=entry_source_url(entry, url),
                            is_reel=extracted.is_reel,
                        )
                    )
                return DownloadBundle(extracted.media_type, items, job_directory)
            except Exception:
                shutil.rmtree(job_directory, ignore_errors=True)
                raise

    def cleanup(self, bundle: DownloadBundle) -> None:
        shutil.rmtree(bundle.job_directory, ignore_errors=True)

    @staticmethod
    def make_telegram_photo_copy(source: Path, directory: Path) -> Path:
        destination = directory / f"{source.stem}_telegram.jpg"
        with Image.open(source) as image:
            image.convert("RGB").save(destination, "JPEG", quality=95)
        return destination