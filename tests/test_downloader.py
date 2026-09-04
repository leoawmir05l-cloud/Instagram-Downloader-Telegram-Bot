import subprocess

import pytest
from PIL import Image

from telegram_bot.downloader import DownloadError, MediaDownloader, probe_video, validate_image


def test_image_validation_accepts_real_image(tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (32, 32), "purple").save(path)
    validate_image(path)


def test_image_validation_rejects_corrupt_file(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    with pytest.raises(DownloadError, match="could not be decoded"):
        validate_image(path)


def test_ffprobe_validates_a_generated_video(tmp_path):
    path = tmp_path / "video.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=0.2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg could not generate a test video in this environment")
    metadata = probe_video(path)
    assert any(stream["codec_type"] == "video" for stream in metadata["streams"])


def test_telegram_photo_copy_preserves_readable_image(tmp_path):
    source = tmp_path / "source.webp"
    Image.new("RGBA", (20, 20), (255, 0, 0, 128)).save(source)
    downloader = MediaDownloader(tmp_path / "jobs")
    copy = downloader.make_telegram_photo_copy(source, tmp_path)
    validate_image(copy)