from __future__ import annotations

from types import SimpleNamespace

from google.genai import types
from PIL import Image
import pytest

from thumbnail_studio.config import DEFAULT_TRANSFORM_PROMPT, normalize_gemini_image_size
from thumbnail_studio.services.gemini import GeminiGenerationError, GeminiService


def _build_service(model: str = "gemini-3.1-flash-image-preview", image_size: str = "4K") -> GeminiService:
    service = object.__new__(GeminiService)
    service.settings = SimpleNamespace(
        gemini_image_model=model,
        gemini_image_aspect_ratio="16:9",
        gemini_image_size=image_size,
    )
    return service


def test_build_generation_config_matches_supported_sdk_fields():
    service = _build_service()

    config = service._build_generation_config()

    assert config.response_modalities == ["IMAGE"]
    if hasattr(types, "ImageConfig"):
        assert config.image_config is not None
        assert config.image_config.aspect_ratio == "16:9"
        assert config.image_config.image_size == "4K"
    else:
        assert config.response_modalities == ["IMAGE"]


def test_build_generation_config_sets_4k_for_gemini_3_pro_image_preview():
    service = _build_service(model="gemini-3-pro-image-preview")

    config = service._build_generation_config()

    assert config.response_modalities == ["IMAGE"]
    assert config.image_config.image_size == "4K"


def test_normalize_gemini_image_size_uses_uppercase_k():
    assert normalize_gemini_image_size("4k") == "4K"
    assert normalize_gemini_image_size("2K") == "2K"
    assert normalize_gemini_image_size("512") == "512"


def test_gemini_service_requires_sdk_with_image_config(monkeypatch: pytest.MonkeyPatch):
    service = _build_service(image_size="4K")
    image_config = getattr(types, "ImageConfig", None)
    if image_config is None:
        pytest.skip("Current SDK already lacks ImageConfig.")

    monkeypatch.delattr(types, "ImageConfig")
    try:
        with pytest.raises(ValueError):
            GeminiService(SimpleNamespace(gemini_api_key="key"))  # type: ignore[arg-type]
    finally:
        monkeypatch.setattr(types, "ImageConfig", image_config, raising=False)


def test_extract_from_parts_supports_sdk_image_wrapper():
    service = _build_service()
    expected = Image.new("RGB", (16, 9), color=(12, 34, 56))

    class FakeSdkImage:
        def __init__(self, pil_image):
            self._pil_image = pil_image

    class FakePart:
        inline_data = None

        def as_image(self):
            return FakeSdkImage(expected)

    extracted = service._extract_from_parts([FakePart()])

    assert extracted is not None
    assert extracted.size == expected.size
    assert extracted is not expected


def test_normalize_prompt_appends_image_only_instruction_once():
    prompt = "Take this thumbnail and regenerate it in 4K."

    normalized = GeminiService._normalize_prompt(prompt)

    assert "Return only the generated image." in normalized
    assert normalized.count("Return only the generated image.") == 1
    assert "Additional note from user" in normalized


def test_normalize_prompt_returns_default_prompt_when_empty():
    assert GeminiService._normalize_prompt("") == DEFAULT_TRANSFORM_PROMPT


def test_generate_with_retry_uses_fresh_image_copy_each_attempt():
    service = _build_service()
    source_image = Image.new("RGB", (8, 8), color=(255, 0, 0))
    seen_object_ids: list[int] = []
    attempt_counter = {"count": 0}

    def fake_generate_content(image: Image.Image, prompt: str):
        seen_object_ids.append(id(image))
        attempt_counter["count"] += 1
        return object()

    def fake_extract_image(_response):
        if attempt_counter["count"] < 3:
            raise ValueError("Gemini did not return an image for this prompt.")
        return Image.new("RGB", (8, 8), color=(0, 255, 0))

    service._generate_content = fake_generate_content  # type: ignore[method-assign]
    service._extract_image = fake_extract_image  # type: ignore[method-assign]

    response = service._generate_with_retry(source_image, DEFAULT_TRANSFORM_PROMPT)

    assert response is not None
    assert len(seen_object_ids) == 3
    assert len(set(seen_object_ids)) == 3


def test_extract_image_surfaces_gemini_block_reason():
    service = _build_service()
    response = SimpleNamespace(
        parts=None,
        candidates=[],
        prompt_feedback=SimpleNamespace(
            block_reason=SimpleNamespace(value="OTHER"),
            block_reason_message=None,
        ),
        usage_metadata=SimpleNamespace(
            prompt_token_count=301,
            total_token_count=301,
        ),
        response_id="response-123",
        model_version="gemini-3.1-flash-image-preview",
    )

    with pytest.raises(GeminiGenerationError) as exc_info:
        service._extract_image(response)

    assert "OTHER" in str(exc_info.value)
    assert "Response id: response-123" in exc_info.value.log_details


def test_transform_thumbnail_raises_when_gemini_blocks(tmp_path):
    source_path = tmp_path / "source.jpg"
    Image.new("RGB", (1280, 720), color=(20, 40, 60)).save(source_path, format="JPEG")

    service = object.__new__(GeminiService)
    service.settings = SimpleNamespace(
        gemini_api_key="key",
        gemini_image_model="gemini-3.1-flash-image-preview",
        gemini_image_aspect_ratio="16:9",
        gemini_image_size="4K",
        generated_dir=tmp_path,
    )
    service._generate_with_retry = lambda image, prompt: (_ for _ in ()).throw(  # type: ignore[method-assign]
        GeminiGenerationError(
            "Gemini blocked this thumbnail request (OTHER).",
            log_details="Prompt feedback block reason: OTHER",
            block_reason="OTHER",
        )
    )

    with pytest.raises(GeminiGenerationError) as exc_info:
        service.transform_thumbnail(source_path, DEFAULT_TRANSFORM_PROMPT, "video-1")

    assert "OTHER" in str(exc_info.value)
