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


def test_normal_post_page_open_graph_image_is_a_photo():
    page = '''
    <html><head>
      <meta property="og:image" content="https://cdn.example/post-image?id=42&amp;size=640" />
    </head></html>
    '''
    result = InstagramExtractor()._parse_official_page(
        page,
        "https://www.instagram.com/p/DcyQdT2s5nv/",
    )
    assert result.media_type is MediaType.PHOTO
    assert source_image_url(result.entries[0]) == "https://cdn.example/post-image?id=42&size=640"


def test_embed_image_selection_prefers_untransformed_full_frame_source():
    page = '''
    <img
      src="https://cdn.example/post.jpg?stp=dst-jpg_e35_tt6"
      srcset="https://cdn.example/post.jpg?stp=dst-jpg_e35_p1080x1080_tt6 1080w,
              https://cdn.example/post.jpg?stp=c0.409.3277.3277a_dst-jpg_e35_s1080x1080_tt6 1080w"
    />
    <img src="https://cdn.example/avatar.jpg?stp=dst-jpg_s100x100_tt6" />
    '''
    result = InstagramExtractor()._parse_official_page(
        page,
        "https://www.instagram.com/p/example/",
    )
    assert result.media_type is MediaType.PHOTO
    assert source_image_url(result.entries[0]) == "https://cdn.example/post.jpg?stp=dst-jpg_e35_tt6"