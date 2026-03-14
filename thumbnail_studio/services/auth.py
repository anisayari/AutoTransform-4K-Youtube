from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from thumbnail_studio.config import AppConfig


def build_oauth_flow(settings: AppConfig, state: str | None = None) -> Flow:
    flow = Flow.from_client_secrets_file(
        str(settings.google_client_secrets_file),
        scopes=list(settings.youtube_scopes),
        state=state,
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


def credentials_status(settings: AppConfig) -> dict[str, object]:
    creds = load_credentials(settings)
    parsed_redirect = urlsplit(settings.google_redirect_uri)
    redirect_origin = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"
    return {
        "connected": creds is not None and creds.valid,
        "clientSecretsPresent": settings.client_secrets_present,
        "tokenPath": str(settings.youtube_token_file),
        "clientSecretsPath": str(settings.google_client_secrets_file),
        "geminiConfigured": settings.gemini_configured,
        "setupComplete": settings.setup_complete,
        "envPath": str(settings.env_file),
        "redirectUri": settings.google_redirect_uri,
        "redirectOrigin": redirect_origin,
    }
