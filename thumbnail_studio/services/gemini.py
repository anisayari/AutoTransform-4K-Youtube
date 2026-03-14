from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

from thumbnail_studio.config import AppConfig
from thumbnail_studio.services.image_tools import prepare_youtube_thumbnail


@dataclass(slots=True)
class GenerationResult:
    archive_path: Path
    upload_ready_path: Path
    model: str


class GeminiService:
    def __init__(self, settings: AppConfig) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is missing.")

        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)

    def transform_thumbnail(self, source_path: Path, prompt: str, video_id: str) -> GenerationResult:
        with Image.open(source_path) as source_image:
            source_image.load()
            response = self.client.models.generate_content(
                model=self.settings.gemini_image_model,
                contents=[prompt, source_image],
                config=self._build_generation_config(),
            )

        generated = self._extract_image(response)
        archive_path = self.settings.generated_dir / f"{video_id}_generated_4k.jpg"
        upload_ready_path = self.settings.generated_dir / f"{video_id}_youtube_upload.jpg"

        generated.convert("RGB").save(
            archive_path,
            format="JPEG",
            quality=96,
            optimize=True,
            progressive=True,
        )
        prepare_youtube_thumbnail(archive_path, upload_ready_path)

        return GenerationResult(
            archive_path=archive_path,
            upload_ready_path=upload_ready_path,
            model=self.settings.gemini_image_model,
        )

    def _build_generation_config(self) -> types.GenerateContentConfig:
        if self.settings.gemini_image_model.startswith("gemini-3.1"):
            image_config = types.ImageConfig(
                aspectRatio=self.settings.gemini_image_aspect_ratio,
                imageSize=self.settings.gemini_image_size,
            )
        else:
            image_config = types.ImageConfig(
                aspectRatio=self.settings.gemini_image_aspect_ratio,
            )

        return types.GenerateContentConfig(
            responseModalities=["IMAGE"],
            imageConfig=image_config,
        )

    def _extract_image(self, response: Any) -> Image.Image:
        parts = getattr(response, "parts", None)
        if parts:
            image = self._extract_from_parts(parts)
            if image is not None:
                return image

        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            candidate_parts = getattr(content, "parts", None) or []
            image = self._extract_from_parts(candidate_parts)
            if image is not None:
                return image

        raise ValueError("Gemini did not return an image for this prompt.")

    def _extract_from_parts(self, parts: list[Any]) -> Image.Image | None:
        for part in parts:
            if hasattr(part, "as_image"):
                return part.as_image().copy()

            inline_data = getattr(part, "inline_data", None)
            if inline_data is None or getattr(inline_data, "data", None) is None:
                continue

            payload = inline_data.data
            raw_bytes = base64.b64decode(payload) if isinstance(payload, str) else payload
            with Image.open(io.BytesIO(raw_bytes)) as generated:
                generated.load()
                return generated.copy()
        return None
