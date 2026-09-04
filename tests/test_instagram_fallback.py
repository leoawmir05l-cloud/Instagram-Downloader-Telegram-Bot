from telegram_bot.instagram import InstagramExtractor
from telegram_bot.media import source_image_url
from telegram_bot.models import MediaType


def test_official_embed_metadata_classifies_image_only_carousel():
    page = r'''
    <script type="application/json">
    {"is_video\":false,\"display_url\":\"https:\\\/\\\/cdn.example\\\/one.jpg?token=1\"}
    {"is_video\":false,\"display_url\":\"https:\\\/\\\/cdn.example\\\/two.jpg?token=2\"}
    </script>
    '''
    result = InstagramExtractor()._parse_official_page(page, "https://www.instagram.com/p/example/")
    assert result.media_type is MediaType.CAROUSEL
    assert [source_image_url(entry) for entry in result.entries] == [
        "https://cdn.example/one.jpg?token=1",
        "https://cdn.example/two.jpg?token=2",
    ]


def test_official_page_metadata_uses_og_image_when_embed_has_no_entries():
    page = '<meta property="og:image" content="https://cdn.example/image?id=1&amp;size=large" />'
    result = InstagramExtractor()._parse_official_page(page, "https://www.instagram.com/p/example/")
    assert result.media_type is MediaType.PHOTO
    assert source_image_url(result.entries[0]) == "https://cdn.example/image?id=1&size=large"