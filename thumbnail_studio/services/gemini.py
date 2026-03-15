from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

from thumbnail_studio.config import AppConfig, DEFAULT_TRANSFORM_PROMPT
from thumbnail_studio.services.image_tools import prepare_youtube_thumbnail

logger = logging.getLogger(__name__)

CANONICAL_4K_PROMPT = DEFAULT_TRANSFORM_PROMPT


@dataclass(slots=True)
class GenerationResult:
    archive_path: Path
    upload_ready_path: Path
    model: str
    notes: str | None = None


class GeminiGenerationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        log_details: str | None = None,
        block_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.log_details = log_details or message
        self.block_reason = block_reason


class GeminiService:
    def __init__(self, settings: AppConfig) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is missing.")
        if not hasattr(types, "ImageConfig"):
            raise ValueError(
                "google-genai is too old for native 4K image generation. "
                "Run `python -m pip install -r requirements.txt` and restart the app."
            )

        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)

    def transform_thumbnail(self, source_path: Path, prompt: str, video_id: str) -> GenerationResult:
        effective_prompt = self._normalize_prompt(prompt)
        logger.info(
            "Gemini request start video_id=%s model=%s aspect=%s size=%s source=%s prompt=%s",
            video_id,
            self.settings.gemini_image_model,
            self.settings.gemini_image_aspect_ratio,
            self.settings.gemini_image_size,
            source_path.name,
            self._prompt_preview(effective_prompt),
        )
        archive_path = self.settings.generated_dir / f"{video_id}_generated_4k.jpg"
        upload_ready_path = self.settings.generated_dir / f"{video_id}_youtube_upload.jpg"

        with Image.open(source_path) as source_image:
            source_image.load()
            response = self._generate_with_retry(source_image, effective_prompt)

        generated = self._extract_image(response)
        generated.convert("RGB").save(
            archive_path,
            format="JPEG",
            quality=96,
            optimize=True,
            progressive=True,
        )

        prepare_youtube_thumbnail(archive_path, upload_ready_path)
        with Image.open(archive_path) as generated:
            generated.load()
            generated_width = generated.width
            generated_height = generated.height
        logger.info(
            "Gemini request success video_id=%s archive=%s upload_ready=%s generated_size=%sx%s",
            video_id,
            archive_path.name,
            upload_ready_path.name,
            generated_width,
            generated_height,
        )

        return GenerationResult(
            archive_path=archive_path,
            upload_ready_path=upload_ready_path,
            model=self.settings.gemini_image_model,
            notes=None,
        )

    def _build_generation_config(self) -> types.GenerateContentConfig | None:
        image_config_kwargs = {
            "aspect_ratio": self.settings.gemini_image_aspect_ratio,
        }
        if self._supports_native_4k():
            image_config_kwargs["image_size"] = self.settings.gemini_image_size
        elif self.settings.gemini_image_size:
            logger.info(
                "Gemini image_size=%s requested but ignored for model=%s because native 4K is only supported on Gemini 3 image models with image preview support.",
                self.settings.gemini_image_size,
                self.settings.gemini_image_model,
            )

        return types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(**image_config_kwargs),
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

            dumped_content = None
            if hasattr(content, "model_dump"):
                dumped_content = content.model_dump()
            elif isinstance(content, dict):
                dumped_content = content
            if dumped_content:
                image = self._extract_from_serialized_parts(dumped_content.get("parts") or [])
                if image is not None:
                    return image

        if hasattr(response, "model_dump"):
            image = self._extract_from_serialized_parts(
                self._collect_serialized_parts(response.model_dump())
            )
            if image is not None:
                return image

        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None)
        block_reason_value = getattr(block_reason, "value", None) or str(block_reason or "").strip()
        block_message = getattr(prompt_feedback, "block_reason_message", None)
        usage = getattr(response, "usage_metadata", None)
        response_id = getattr(response, "response_id", None)
        model_version = getattr(response, "model_version", None)

        details = [
            "Gemini returned no image candidates.",
            f"Model: {model_version or self.settings.gemini_image_model}",
        ]
        if response_id:
            details.append(f"Response id: {response_id}")
        if block_reason_value:
            details.append(f"Prompt feedback block reason: {block_reason_value}")
        if block_message:
            details.append(f"Prompt feedback message: {block_message}")
        if usage is not None:
            prompt_token_count = getattr(usage, "prompt_token_count", None)
            total_token_count = getattr(usage, "total_token_count", None)
            if prompt_token_count is not None:
                details.append(f"Prompt tokens: {prompt_token_count}")
            if total_token_count is not None:
                details.append(f"Total tokens: {total_token_count}")

        message = "Gemini did not return an image for this prompt."
        if block_reason_value:
            message = f"Gemini blocked this thumbnail request ({block_reason_value})."

        raise GeminiGenerationError(
            message,
            log_details="\n".join(details),
            block_reason=block_reason_value or None,
        )

    def _generate_with_retry(self, source_image: Image.Image, prompt: str) -> Any:
        errors: list[Exception] = []
        attempts = [
            prompt,
            CANONICAL_4K_PROMPT,
            f"{CANONICAL_4K_PROMPT}\n\nAdditional note: keep every visible detail identical to the source thumbnail.",
        ]

        for attempt_number, current_prompt in enumerate(attempts, start=1):
            try:
                logger.info(
                    "Gemini request attempt=%s model=%s prompt=%s",
                    attempt_number,
                    self.settings.gemini_image_model,
                    self._prompt_preview(current_prompt),
                )
                response = self._generate_content(source_image.copy(), current_prompt)
                self._extract_image(response)
                return response
            except ValueError as exc:
                logger.warning(
                    "Gemini request attempt=%s returned no image: %s",
                    attempt_number,
                    exc,
                )
                errors.append(exc)

        raise errors[-1]

    def _generate_content(self, source_image: Image.Image, prompt: str) -> Any:
        generation_kwargs = {
            "model": self.settings.gemini_image_model,
            "contents": [prompt, source_image],
        }
        generation_config = self._build_generation_config()
        if generation_config is not None:
            generation_kwargs["config"] = generation_config
        return self.client.models.generate_content(**generation_kwargs)

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        prompt = prompt.strip()
        if not prompt:
            return CANONICAL_4K_PROMPT
        if prompt.lower() == CANONICAL_4K_PROMPT.lower():
            return CANONICAL_4K_PROMPT
        return (
            f"{CANONICAL_4K_PROMPT}\n\n"
            f"Additional note from user: {prompt}\n"
            "Follow the note only if it does not conflict with keeping the thumbnail identical."
        )

    def _extract_from_parts(self, parts: list[Any]) -> Image.Image | None:
        for part in parts:
            if hasattr(part, "as_image"):
                image = part.as_image()
                pil_image = getattr(image, "_pil_image", None)
                if pil_image is not None:
                    return pil_image.copy()
                if isinstance(image, Image.Image):
                    return image.copy()

            inline_data = getattr(part, "inline_data", None)
            if inline_data is None or getattr(inline_data, "data", None) is None:
                continue

            payload = inline_data.data
            raw_bytes = base64.b64decode(payload) if isinstance(payload, str) else payload
            with Image.open(io.BytesIO(raw_bytes)) as generated:
                generated.load()
                return generated.copy()
        return None

    def _extract_from_serialized_parts(self, parts: list[Any]) -> Image.Image | None:
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline_data = part.get("inline_data") or {}
            payload = inline_data.get("data")
            if payload is None:
                continue
            raw_bytes = base64.b64decode(payload) if isinstance(payload, str) else payload
            with Image.open(io.BytesIO(raw_bytes)) as generated:
                generated.load()
                return generated.copy()
        return None

    def _collect_serialized_parts(self, payload: Any) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            maybe_parts = payload.get("parts")
            if isinstance(maybe_parts, list):
                parts.extend(item for item in maybe_parts if isinstance(item, dict))
            for value in payload.values():
                parts.extend(self._collect_serialized_parts(value))
        elif isinstance(payload, list):
            for item in payload:
                parts.extend(self._collect_serialized_parts(item))
        return parts

    @staticmethod
    def _prompt_preview(prompt: str) -> str:
        collapsed = " ".join(prompt.split())
        return collapsed[:180]

    def _supports_native_4k(self) -> bool:
        model = self.settings.gemini_image_model
        return model.startswith("gemini-3.1-flash-image-preview") or model.startswith(
            "gemini-3-pro-image-preview"
        )
