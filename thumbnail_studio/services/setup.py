from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv, set_key
from werkzeug.datastructures import FileStorage

from thumbnail_studio.config import AppConfig
from thumbnail_studio.services.auth import evaluate_oauth_client_config


def save_gemini_api_key(settings: AppConfig, api_key: str) -> None:
    cleaned = api_key.strip()
    if not cleaned:
        raise ValueError("Gemini API key cannot be empty.")

    settings.env_file.parent.mkdir(parents=True, exist_ok=True)
    settings.env_file.touch(exist_ok=True)
    set_key(str(settings.env_file), "GEMINI_API_KEY", cleaned, quote_mode="auto")
    os.environ["GEMINI_API_KEY"] = cleaned


def save_google_client_secret(settings: AppConfig, upload: FileStorage | None) -> Path:
    if upload is None or not upload.filename:
        raise ValueError("Upload a client_secret.json file.")

    raw_content = upload.read()
    if not raw_content:
        raise ValueError("The OAuth file is empty.")

    try:
        parsed = json.loads(raw_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The uploaded file is not valid JSON.") from exc

    web_config = parsed.get("web")
    if not isinstance(web_config, dict):
        raise ValueError("The JSON must come from a Google OAuth Web application client.")
    if not web_config.get("client_id") or not web_config.get("client_secret"):
        raise ValueError("The OAuth file is incomplete.")

    oauth_config = evaluate_oauth_client_config(settings, web_config=web_config)
    if not oauth_config["valid"]:
        raise ValueError(str(oauth_config["message"]))

    destination = settings.google_client_secrets_file
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    return destination


def delete_google_client_secret(settings: AppConfig) -> None:
    if settings.google_client_secrets_file.exists():
        settings.google_client_secrets_file.unlink()


def reload_settings(settings: AppConfig) -> AppConfig:
    load_dotenv(dotenv_path=settings.env_file, override=True)
    refreshed = AppConfig.from_env()
    refreshed.ensure_directories()
    return refreshed
