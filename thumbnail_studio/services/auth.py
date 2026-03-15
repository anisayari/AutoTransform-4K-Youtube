from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from thumbnail_studio.config import AppConfig


def _normalize_url(value: str) -> str:
    return value.strip().rstrip("/")


def _localhost_http_allowed(settings: AppConfig) -> bool:
    parsed = urlsplit(settings.google_redirect_uri)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def _string_list(payload: object) -> list[str]:
    if not isinstance(payload, (list, tuple)):
        return []
    return [str(item).strip() for item in payload if str(item).strip()]


def configure_oauth_transport(settings: AppConfig) -> None:
    if _localhost_http_allowed(settings):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)


def evaluate_oauth_client_config(
    settings: AppConfig,
    *,
    web_config: dict[str, object],
) -> dict[str, object]:
    parsed_redirect = urlsplit(settings.google_redirect_uri)
    expected_origin = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"

    configured_redirect_uris = _string_list(web_config.get("redirect_uris"))
    configured_origins = _string_list(web_config.get("javascript_origins"))

    expected_redirect = _normalize_url(settings.google_redirect_uri)
    expected_origin_normalized = _normalize_url(expected_origin)
    redirect_uri_configured = expected_redirect in {
        _normalize_url(item) for item in configured_redirect_uris
    }
    origin_configured = expected_origin_normalized in {
        _normalize_url(item) for item in configured_origins
    }

    if redirect_uri_configured and origin_configured:
        message = "Google OAuth client matches this app."
    else:
        missing_parts: list[str] = []
        if not redirect_uri_configured:
            missing_parts.append(f"redirect URI `{settings.google_redirect_uri}`")
        if not origin_configured:
            missing_parts.append(f"JavaScript origin `{expected_origin}`")
        message = "Missing from client_secret.json: " + " and ".join(missing_parts) + "."

    return {
        "checked": True,
        "valid": redirect_uri_configured and origin_configured,
        "redirectUriConfigured": redirect_uri_configured,
        "originConfigured": origin_configured,
        "expectedRedirectUri": settings.google_redirect_uri,
        "expectedOrigin": expected_origin,
        "configuredRedirectUris": configured_redirect_uris,
        "configuredOrigins": configured_origins,
        "message": message,
    }


def oauth_client_config_status(settings: AppConfig) -> dict[str, object]:
    parsed_redirect = urlsplit(settings.google_redirect_uri)
    expected_origin = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"

    default_status = {
        "checked": False,
        "valid": False,
        "redirectUriConfigured": False,
        "originConfigured": False,
        "expectedRedirectUri": settings.google_redirect_uri,
        "expectedOrigin": expected_origin,
        "configuredRedirectUris": [],
        "configuredOrigins": [],
        "message": "Upload client_secret.json to run the OAuth check.",
    }

    if not settings.client_secrets_present:
        return default_status

    try:
        parsed = json.loads(settings.google_client_secrets_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            **default_status,
            "checked": True,
            "message": f"Could not read client_secret.json: {exc}",
        }

    web_config = parsed.get("web")
    if not isinstance(web_config, dict):
        return {
            **default_status,
            "checked": True,
            "message": "client_secret.json must contain a Google OAuth web client.",
        }

    return evaluate_oauth_client_config(settings, web_config=web_config)


def build_oauth_flow(
    settings: AppConfig,
    state: str | None = None,
    code_verifier: str | None = None,
) -> Flow:
    configure_oauth_transport(settings)
    flow = Flow.from_client_secrets_file(
        str(settings.google_client_secrets_file),
        scopes=list(settings.youtube_scopes),
        state=state,
        code_verifier=code_verifier,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def load_credentials(settings: AppConfig) -> Credentials | None:
    token_path = settings.youtube_token_file
    if not token_path.exists():
        return None

    try:
        credentials = Credentials.from_authorized_user_file(
            str(token_path),
            settings.youtube_scopes,
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            save_credentials(settings.youtube_token_file, credentials)
        return credentials
    except Exception:  # noqa: BLE001
        return None


def save_credentials(token_path: Path, credentials: Credentials) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


def clear_credentials(token_path: Path) -> None:
    if token_path.exists():
        token_path.unlink()


def credentials_status(
    settings: AppConfig,
    *,
    include_gemini_secret: bool = False,
) -> dict[str, object]:
    creds = load_credentials(settings)
    oauth_config = oauth_client_config_status(settings)
    status = {
        "connected": creds is not None and creds.valid,
        "clientSecretsPresent": settings.client_secrets_present,
        "tokenPath": str(settings.youtube_token_file),
        "clientSecretsPath": str(settings.google_client_secrets_file),
        "clientSecretsFilename": settings.google_client_secrets_file.name,
        "geminiConfigured": settings.gemini_configured,
        "setupComplete": settings.gemini_configured and oauth_config["valid"],
        "envPath": str(settings.env_file),
        "redirectUri": oauth_config["expectedRedirectUri"],
        "redirectOrigin": oauth_config["expectedOrigin"],
        "oauthConfigChecked": oauth_config["checked"],
        "oauthConfigValid": oauth_config["valid"],
        "oauthRedirectUriConfigured": oauth_config["redirectUriConfigured"],
        "oauthOriginConfigured": oauth_config["originConfigured"],
        "oauthConfiguredRedirectUris": oauth_config["configuredRedirectUris"],
        "oauthConfiguredOrigins": oauth_config["configuredOrigins"],
        "oauthConfigMessage": oauth_config["message"],
    }
    if include_gemini_secret:
        status["geminiApiKey"] = settings.gemini_api_key
    return status
