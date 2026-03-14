from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_env_file() -> Path:
    env_file = Path(os.getenv("APP_ENV_FILE", ".env"))
    if not env_file.is_absolute():
        env_file = BASE_DIR / env_file
    return env_file


@dataclass(slots=True)
class AppConfig:
    env_file: Path
    secret_key: str
    google_client_secrets_file: Path
    google_redirect_uri: str
    youtube_token_file: Path
    youtube_scopes: tuple[str, ...]
    gemini_api_key: str
    gemini_image_model: str
    gemini_image_aspect_ratio: str
    gemini_image_size: str
    default_transform_prompt: str
    media_root: Path
    downloads_dir: Path
    generated_dir: Path
    max_videos: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        env_file = resolve_env_file()
        media_root = BASE_DIR / "instance" / "media"
        token_file = Path(os.getenv("YOUTUBE_TOKEN_FILE", "instance/youtube_token.json"))
        if not token_file.is_absolute():
            token_file = BASE_DIR / token_file

        client_secrets = Path(os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json"))
        if not client_secrets.is_absolute():
            client_secrets = BASE_DIR / client_secrets

        return cls(
            env_file=env_file,
            secret_key=os.getenv("FLASK_SECRET_KEY", secrets.token_hex(24)),
            google_client_secrets_file=client_secrets,
            google_redirect_uri=os.getenv(
                "GOOGLE_REDIRECT_URI",
                "http://localhost:5001/auth/google/callback",
            ),
            youtube_token_file=token_file,
            youtube_scopes=(
                "https://www.googleapis.com/auth/youtube",
            ),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_image_model=os.getenv(
                "GEMINI_IMAGE_MODEL",
                "gemini-3.1-flash-image-preview",
            ).strip(),
            gemini_image_aspect_ratio=os.getenv(
                "GEMINI_IMAGE_ASPECT_RATIO",
                "16:9",
            ).strip(),
            gemini_image_size=os.getenv("GEMINI_IMAGE_SIZE", "4K").strip(),
            default_transform_prompt=os.getenv(
                "DEFAULT_TRANSFORM_PROMPT",
                (
                    "Transform this YouTube thumbnail into a sharper, premium, "
                    "high-click-through version. Preserve the main composition, keep "
                    "text readable, improve contrast, color grading, subject separation, "
                    "and face detail. Keep it clean, cinematic, and optimized for a "
                    "16:9 YouTube thumbnail. No watermarks, no borders, no layout "
                    "changes that break the original idea."
                ),
            ).strip(),
            media_root=media_root,
            downloads_dir=media_root / "downloads",
            generated_dir=media_root / "generated",
            max_videos=max(1, int(os.getenv("YOUTUBE_MAX_VIDEOS", "18"))),
        )

    def ensure_directories(self) -> None:
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)

    @property
    def client_secrets_present(self) -> bool:
        return self.google_client_secrets_file.exists()

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def setup_complete(self) -> bool:
        return self.client_secrets_present and self.gemini_configured
