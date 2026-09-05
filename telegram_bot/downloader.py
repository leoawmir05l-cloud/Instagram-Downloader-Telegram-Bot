from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yt_dlp
from PIL import Image, UnidentifiedImageError

from .media import entry_source_url, source_image_url
from .models import DownloadBundle, ExtractedMedia, MediaItem, MediaType

logger = logging.getLogger(__name__)
TELEGRAM_MAX_UPLOAD_BYTES = 48_000_000


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
        "-count_frames",
        "-of",
        "json",
        str(path),
    ]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise DownloadError("ffprobe_error", result.stderr[-500:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DownloadError("ffprobe_error", "ffprobe returned invalid JSON") from exc
    if not any(stream.get("codec_type") == "video" for stream in payload.get("streams", [])):
        raise DownloadError("corrupted_media", "video stream is missing")
    logger.info("[FFPROBE] file=%s elapsed=%.2fs", path.name, time.perf_counter() - started)
    return payload


def _first_stream(metadata: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    return next(
        (stream for stream in metadata.get("streams", []) if stream.get("codec_type") == codec_type),
        None,
    )


def _stream_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    video = _first_stream(metadata, "video") or {}
    audio = _first_stream(metadata, "audio") or {}
    return {
        "container": (metadata.get("format") or {}).get("format_name"),
        "duration": (metadata.get("format") or {}).get("duration"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "pixel_format": video.get("pix_fmt"),
        "fps": video.get("r_frame_rate"),
        "time_base": video.get("time_base"),
        "video_start": video.get("start_time"),
        "audio_start": audio.get("start_time"),
        "video_frames": video.get("nb_read_frames") or video.get("nb_frames"),
        "audio_frames": audio.get("nb_read_frames") or audio.get("nb_frames"),
        "video_bitrate": video.get("bit_rate"),
        "audio_bitrate": audio.get("bit_rate"),
    }


def _log_video_probe(label: str, path: Path, metadata: dict[str, Any]) -> None:
    logger.info("video %s file=%s probe=%s", label, path.name, _stream_summary(metadata))


def validate_video_frames(path: Path, metadata: dict[str, Any] | None = None) -> None:
    metadata = metadata or probe_video(path)
    try:
        duration = float((metadata.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise DownloadError("corrupted_media", "video duration is invalid")
    sample_times = sorted({0.0, min(duration * 0.5, max(duration - 0.05, 0)), max(duration - 0.1, 0)})
    for timestamp in sample_times:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise DownloadError("corrupted_media", f"video frame failed at {timestamp:.3f}s: {result.stderr[-300:]}")


def _is_telegram_compatible(metadata: dict[str, Any]) -> bool:
    video = _first_stream(metadata, "video") or {}
    audio = _first_stream(metadata, "audio")
    format_name = str((metadata.get("format") or {}).get("format_name") or "")
    return (
        any(name in format_name.split(",") for name in ("mp4", "mov"))
        and video.get("codec_name") == "h264"
        and str(video.get("pix_fmt") or "").startswith(("yuv420", "yuvj420"))
        and (audio is None or audio.get("codec_name") == "aac")
        and int(video.get("nb_read_frames") or video.get("nb_frames") or 0) > 0
    )


def _transcode_for_telegram(
    source: Path,
    destination: Path,
    source_metadata: dict[str, Any],
    target_bytes: int = TELEGRAM_MAX_UPLOAD_BYTES,
) -> None:
    video = _first_stream(source_metadata, "video") or {}
    audio = _first_stream(source_metadata, "audio") or {}
    try:
        duration = float((source_metadata.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    total_bitrate_budget = int(target_bytes * 8 / duration * 0.96) if duration else 2_000_000
    source_audio_bitrate = int(audio.get("bit_rate") or 0)
    audio_bitrate = max(96_000, min(source_audio_bitrate or 128_000, 192_000))
    video_bitrate_budget = max(300_000, total_bitrate_budget - audio_bitrate)
    source_video_bitrate = int(video.get("bit_rate") or 0)
    video_bitrate = min(source_video_bitrate or video_bitrate_budget, video_bitrate_budget)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        str(video_bitrate),
        "-maxrate",
        str(video_bitrate),
        "-bufsize",
        str(video_bitrate * 2),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        str(audio_bitrate),
        "-af",
        "aresample=async=1:first_pts=0",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "0",
        str(destination),
    ]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        logger.error("FFmpeg compatibility conversion failed for %s: %s", source.name, result.stderr[-2000:])
        raise DownloadError("ffmpeg_error", result.stderr[-500:])
    logger.info(
        "[FFMPEG] source=%s destination=%s elapsed=%.2fs video_bitrate=%s audio_bitrate=%s output_bytes=%s",
        source.name,
        destination.name,
        time.perf_counter() - started,
        video_bitrate,
        audio_bitrate,
        destination.stat().st_size if destination.exists() else 0,
    )


def ensure_telegram_video(path: Path, directory: Path, index: int) -> Path:
    source_metadata = probe_video(path)
    _log_video_probe("source", path, source_metadata)
    if _is_telegram_compatible(source_metadata) and path.stat().st_size <= TELEGRAM_MAX_UPLOAD_BYTES:
        validate_video_frames(path, source_metadata)
        _log_video_probe("final", path, source_metadata)
        return path
    destination = directory / f"validated_{index:04d}.mp4"
    _transcode_for_telegram(path, destination, source_metadata)
    final_metadata = probe_video(destination)
    validate_video_frames(destination, final_metadata)
    if not _is_telegram_compatible(final_metadata):
        raise DownloadError("corrupted_media", "final video is not Telegram-compatible")
    if destination.stat().st_size > TELEGRAM_MAX_UPLOAD_BYTES:
        raise DownloadError("telegram_file_too_large", "final video exceeds Telegram's upload limit")
    _log_video_probe("final", destination, final_metadata)
    return destination


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

    def _download_with_ytdlp_sync(
        self,
        source_url: str,
        directory: Path,
        index: int,
        media_type: MediaType,
        info: dict[str, Any] | None = None,
    ) -> Path:
        output_template = str(directory / f"item_{index:04d}.%(ext)s")
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": output_template,
            "retries": 2,
            "socket_timeout": self.timeout,
            "restrictfilenames": True,
            "noplaylist": True,
            "concurrent_fragment_downloads": 4,
        }
        if media_type == MediaType.VIDEO:
            options.update(
                {
                    "format": "bestvideo+bestaudio/best",
                    "merge_output_format": "mp4",
                    "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
                    "postprocessor_args": {"ffmpeg": ["-movflags", "+faststart"]},
                }
            )
        with yt_dlp.YoutubeDL(options) as ydl:
            if info is not None:
                ydl.process_ie_result(dict(info), download=True)
            else:
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
            started = time.perf_counter()
            path = await asyncio.wait_for(
                asyncio.to_thread(self._download_with_ytdlp_sync, source_url, directory, index, MediaType.PHOTO),
                timeout=self.timeout,
            )
            validate_image(path)
            logger.info(
                "[DOWNLOAD] type=photo index=%s bytes=%s elapsed=%.2fs throughput=%.1fKB/s",
                index,
                path.stat().st_size,
                time.perf_counter() - started,
                path.stat().st_size / max(time.perf_counter() - started, 0.001) / 1024,
            )
            return path
        except Exception as primary_error:
            logger.warning("yt-dlp photo download failed; using extracted URL fallback: %s", primary_error)
            fallback_path = directory / f"item_{index:04d}.jpg"
            return await self._http_image_fallback(source_url, fallback_path)

    async def _download_video(self, entry: dict[str, Any], directory: Path, index: int, fallback_url: str) -> Path:
        source_url = entry_source_url(entry, fallback_url)
        try:
            started = time.perf_counter()
            path = await asyncio.wait_for(
                asyncio.to_thread(
                    self._download_with_ytdlp_sync,
                    source_url,
                    directory,
                    index,
                    MediaType.VIDEO,
                    entry if entry.get("formats") or entry.get("requested_formats") else None,
                ),
                timeout=self.timeout,
            )
            logger.info(
                "[DOWNLOAD] type=video index=%s bytes=%s elapsed=%.2fs throughput=%.1fKB/s",
                index,
                path.stat().st_size,
                time.perf_counter() - started,
                path.stat().st_size / max(time.perf_counter() - started, 0.001) / 1024,
            )
            return ensure_telegram_video(path, directory, index)
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError("video_extraction_error", str(exc)) from exc

    async def download(self, url: str, extracted: ExtractedMedia) -> DownloadBundle:
        job_directory = Path(tempfile.mkdtemp(prefix="instagram_", dir=self.work_root))

        async def download_one(index: int, entry: dict[str, Any]) -> MediaItem:
            async with self.semaphore:
                entry_type = extracted.media_type
                if extracted.media_type == MediaType.CAROUSEL:
                    from .media import classify_entry

                    entry_type = classify_entry(entry)
                if entry_type == MediaType.PHOTO:
                    path = await self._download_photo(entry, job_directory, index, url)
                else:
                    path = await self._download_video(entry, job_directory, index, url)
                return MediaItem(
                    index=index,
                    media_type=entry_type,
                    path=path,
                    source_url=entry_source_url(entry, url),
                    is_reel=extracted.is_reel,
                )

        try:
            # gather preserves input order even when independent items finish
            # out of order, so Telegram output remains Instagram-ordered.
            items = await asyncio.gather(
                *(download_one(index, entry) for index, entry in enumerate(extracted.entries))
            )
            return DownloadBundle(extracted.media_type, list(items), job_directory)
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