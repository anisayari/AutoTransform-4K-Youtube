from __future__ import annotations

import io
from pathlib import Path

import requests
from PIL import Image, ImageOps


THUMBNAIL_PRIORITY = ("maxres", "standard", "high", "medium", "default")
MAX_YOUTUBE_THUMBNAIL_BYTES = 50 * 1024 * 1024
YOUTUBE_UPLOAD_SIZE = (3840, 2160)


def pick_best_thumbnail_url(thumbnails: dict | None) -> str | None:
    if not thumbnails:
        return None

    for key in THUMBNAIL_PRIORITY:
        payload = thumbnails.get(key)
        if payload and payload.get("url"):
            return payload["url"]
    return None


def download_image(url: str, destination: Path) -> Path:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def normalize_image(source_path: Path) -> Image.Image:
    with Image.open(source_path) as image:
        normalized = ImageOps.exif_transpose(image)
        if normalized.mode not in ("RGB", "L"):
            normalized = normalized.convert("RGB")
        elif normalized.mode == "L":
            normalized = normalized.convert("RGB")
        return normalized.copy()


def save_jpeg(image: Image.Image, destination: Path, quality: int) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        destination,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )
    return destination


def prepare_youtube_thumbnail(source_path: Path, destination: Path) -> Path:
    image = normalize_image(source_path)
    fitted = ImageOps.fit(image, YOUTUBE_UPLOAD_SIZE, method=Image.Resampling.LANCZOS)

    for quality in (96, 92, 88, 84, 80):
        save_jpeg(fitted, destination, quality=quality)
        if destination.stat().st_size <= MAX_YOUTUBE_THUMBNAIL_BYTES:
            return destination

    raise ValueError("Unable to compress the generated thumbnail under YouTube's 50 MB limit.")
