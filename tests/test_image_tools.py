from pathlib import Path

from PIL import Image

from thumbnail_studio.services.image_tools import (
    MAX_YOUTUBE_THUMBNAIL_BYTES,
    YOUTUBE_UPLOAD_SIZE,
    pick_best_thumbnail_url,
    prepare_youtube_thumbnail,
)


def test_pick_best_thumbnail_url_prefers_highest_available():
    thumbnails = {
        "default": {"url": "https://example.com/default.jpg"},
        "high": {"url": "https://example.com/high.jpg"},
        "maxres": {"url": "https://example.com/maxres.jpg"},
    }

    assert pick_best_thumbnail_url(thumbnails) == "https://example.com/maxres.jpg"


def test_prepare_youtube_thumbnail_resizes_and_compresses(tmp_path: Path):
    source = tmp_path / "source.png"
    output = tmp_path / "thumb.jpg"

    Image.new("RGB", (2200, 1600), color=(27, 98, 177)).save(source)

    prepare_youtube_thumbnail(source, output)

    with Image.open(output) as generated:
        assert generated.size == YOUTUBE_UPLOAD_SIZE

    assert output.stat().st_size <= MAX_YOUTUBE_THUMBNAIL_BYTES
