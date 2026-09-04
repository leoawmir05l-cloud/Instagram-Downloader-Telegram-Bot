from telegram_bot.media import classify_entry, classify_extraction, entry_source_url, source_image_url
from telegram_bot.models import MediaType


def test_photo_without_video_stream_is_photo():
    info = {"id": "photo", "url": "https://cdn.example/photo.jpg", "ext": "jpg", "formats": []}
    assert classify_entry(info) == MediaType.PHOTO


def test_video_is_video_when_video_codec_exists():
    info = {"id": "video", "url": "https://cdn.example/video.mp4", "ext": "mp4", "vcodec": "avc1"}
    assert classify_entry(info) == MediaType.VIDEO


def test_carousel_preserves_every_entry_in_original_order():
    info = {
        "entries": [
            {"url": "https://cdn.example/1.jpg", "ext": "jpg"},
            {"url": "https://cdn.example/2.mp4", "ext": "mp4", "vcodec": "h264"},
            {"url": "https://cdn.example/3.png", "ext": "png"},
        ]
    }
    extracted = classify_extraction(info, "https://www.instagram.com/p/carousel/")
    assert extracted.media_type == MediaType.CAROUSEL
    assert [entry_source_url(entry, "") for entry in extracted.entries] == [
        "https://cdn.example/1.jpg",
        "https://cdn.example/2.mp4",
        "https://cdn.example/3.png",
    ]


def test_image_source_prefers_actual_high_quality_source():
    info = {
        "url": "https://cdn.example/photo.jpg",
        "thumbnails": [{"url": "https://cdn.example/thumb.jpg", "width": 320}],
    }
    assert source_image_url(info) == "https://cdn.example/photo.jpg"


def test_image_source_uses_declared_extension_when_cdn_url_has_no_suffix():
    info = {"url": "https://cdn.example/media?id=123", "ext": "jpg"}
    assert source_image_url(info) == "https://cdn.example/media?id=123"