from telegram_bot.url_utils import extract_instagram_urls, normalize_instagram_url


def test_extracts_urls_from_text_and_removes_punctuation():
    text = "ببین اینو 😂 https://instagram.com/p/ABC123/?utm_source=x."
    assert extract_instagram_urls(text) == ["https://www.instagram.com/p/ABC123/?utm_source=x"]


def test_supports_all_requested_instagram_paths():
    text = "https://www.instagram.com/p/a https://instagram.com/reel/b https://instagram.com/reels/c https://www.instagram.com/tv/d"
    assert extract_instagram_urls(text) == [
        "https://www.instagram.com/p/a",
        "https://www.instagram.com/reel/b",
        "https://www.instagram.com/reels/c",
        "https://www.instagram.com/tv/d",
    ]


def test_normalization_deduplicates_and_drops_fragment():
    assert normalize_instagram_url("http://instagram.com/p/id/#comments") == "https://www.instagram.com/p/id"
    assert len(extract_instagram_urls("https://instagram.com/p/id https://www.instagram.com/p/id")) == 1