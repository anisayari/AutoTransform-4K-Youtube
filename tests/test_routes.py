from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest

from thumbnail_studio import create_app


@dataclass
class FakeCredentials:
    valid: bool = True


VALID_WEB_CLIENT = (
    '{"web":{"client_id":"id","client_secret":"secret",'
    '"redirect_uris":["http://localhost:5001/auth/google/callback"],'
    '"javascript_origins":["http://localhost:5001"]}}'
)


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text(VALID_WEB_CLIENT, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(client_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_index_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"4K Thumbnail Studio" in response.data
    assert b"Before you continue" in response.data
    assert b"data-oauth-warning-link" in response.data


def test_setup_prefills_existing_gemini_key_as_hidden_input(client):
    response = client.get("/setup")

    assert response.status_code == 200
    assert b'aria-label="Show Gemini API key"' in response.data
    assert b'value="test-gemini-key"' in response.data
    assert b"Before you continue" in response.data


def test_setup_hides_dropzone_when_client_secret_already_exists(client):
    response = client.get("/setup")

    assert response.status_code == 200
    assert b"Current OAuth client file" in response.data
    assert b"Recheck" in response.data
    assert b"Upload new file" in response.data
    assert b"Drop `client_secret.json` here" not in response.data
    assert b"<div class=\"info-box-label\">JavaScript origin</div>" not in response.data
    assert b"<div class=\"info-box-label\">Redirect URI</div>" not in response.data
    assert b"<div class=\"info-box-label\">Destination</div>" not in response.data
    assert b"http://localhost:5001/auth/google/callback" not in response.data
    assert b"/client_secret.json" not in response.data
    assert b"Open studio" not in response.data


def test_setup_shows_open_studio_only_when_youtube_is_connected(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("thumbnail_studio.services.auth.load_credentials", lambda _settings: FakeCredentials())

    response = client.get("/setup")

    assert response.status_code == 200
    assert b"Open studio" in response.data


def test_index_redirects_to_setup_when_project_is_not_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    missing_secret = tmp_path / "missing-client-secret.json"

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(missing_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    app = create_app()
    app.config.update(TESTING=True)
    test_client = app.test_client()

    response = test_client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/setup")


def test_oauth_start_redirects_with_clear_error_when_client_secret_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-gemini-key\n", encoding="utf-8")
    missing_secret = tmp_path / "missing-client-secret.json"

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(missing_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    app = create_app()
    app.config.update(TESTING=True)
    test_client = app.test_client()

    response = test_client.get("/auth/google/start", follow_redirects=True)

    assert response.status_code == 200
    assert b"Setup" in response.data
    assert str(missing_secret).encode() in response.data


def test_oauth_start_redirects_with_clear_error_when_oauth_config_is_mismatched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-gemini-key\n", encoding="utf-8")
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text(
        (
            '{"web":{"client_id":"id","client_secret":"secret",'
            '"redirect_uris":["http://localhost:9999/auth/google/callback"],'
            '"javascript_origins":["http://localhost:9999"]}}'
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(client_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    app = create_app()
    app.config.update(TESTING=True)
    test_client = app.test_client()

    response = test_client.get("/auth/google/start", follow_redirects=True)

    assert response.status_code == 200
    assert b"Missing from client_secret.json" in response.data
    assert b"http://localhost:5001/auth/google/callback" in response.data


def test_api_videos_requires_auth(client):
    response = client.get("/api/videos")

    assert response.status_code == 401
    assert response.json["ok"] is False


def test_api_batch_transform_requires_selection(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("thumbnail_studio.routes.load_credentials", lambda _settings: FakeCredentials())

    response = client.post(
        "/api/videos/batch-transform",
        json={"prompt": "upgrade", "videos": []},
    )

    assert response.status_code == 400
    assert response.json["message"] == "Select at least one video to transform."


def test_api_batch_transform_processes_only_selected_videos(
    client,
    app,
    monkeypatch: pytest.MonkeyPatch,
):
    processed_ids: list[str] = []

    class FakeYouTubeService:
        def __init__(self, settings, credentials):
            self.settings = settings

        def download_thumbnail(self, video_id, official_thumbnail_url, pytube_thumbnail_url):
            source = self.settings.downloads_dir / f"{video_id}_source.jpg"
            source.write_bytes(b"source")
            return source, "official" if official_thumbnail_url else "pytube"

        def set_thumbnail(self, video_id, image_path):
            processed_ids.append(video_id)
            assert image_path.exists()

    class FakeGeminiService:
        def __init__(self, settings):
            self.settings = settings

        def transform_thumbnail(self, source_path, prompt, video_id):
            archive = self.settings.generated_dir / f"{video_id}_generated_4k.jpg"
            upload = self.settings.generated_dir / f"{video_id}_youtube_upload.jpg"
            archive.write_bytes(b"archive")
            upload.write_bytes(b"upload")

            return type(
                "FakeGenerationResult",
                (),
                {
                    "archive_path": archive,
                    "upload_ready_path": upload,
                    "model": "fake-image-model",
                },
            )()

    monkeypatch.setattr("thumbnail_studio.routes.load_credentials", lambda _settings: FakeCredentials())
    monkeypatch.setattr("thumbnail_studio.routes.YouTubeService", FakeYouTubeService)
    monkeypatch.setattr("thumbnail_studio.routes.GeminiService", FakeGeminiService)

    response = client.post(
        "/api/videos/batch-transform",
        json={
            "prompt": "upgrade this thumbnail",
            "videos": [
                {
                    "id": "video-1",
                    "officialThumbnailUrl": "https://example.com/1.jpg",
                    "pytubeThumbnailUrl": None,
                },
                {
                    "id": "video-2",
                    "officialThumbnailUrl": None,
                    "pytubeThumbnailUrl": "https://example.com/2.jpg",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["successCount"] == 2
    assert response.json["failureCount"] == 0
    assert [item["videoId"] for item in response.json["processed"]] == ["video-1", "video-2"]
    assert processed_ids == ["video-1", "video-2"]

    with app.app_context():
        assert (app.config["APP_SETTINGS"].generated_dir / "video-1_youtube_upload.jpg").exists()


def test_api_transform_jobs_queues_async_batch(client, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeJobStore:
        def create_transform_job(self, *, prompt, videos, runner):
            captured["prompt"] = prompt
            captured["videos"] = videos
            captured["runner"] = runner
            return {
                "jobId": "job-123",
                "status": "queued",
                "message": "Queued 2 thumbnail transform(s).",
                "videoIds": ["video-1", "video-2"],
                "currentVideoId": None,
                "currentVideoTitle": None,
                "totalCount": 2,
                "completedCount": 0,
                "successCount": 0,
                "failureCount": 0,
                "processed": [],
                "failed": [],
                "createdAt": "2026-03-15T10:00:00+00:00",
                "updatedAt": "2026-03-15T10:00:00+00:00",
            }

    monkeypatch.setattr("thumbnail_studio.routes.load_credentials", lambda _settings: FakeCredentials())
    monkeypatch.setattr("thumbnail_studio.routes.YouTubeService", lambda settings, credentials: object())
    monkeypatch.setattr("thumbnail_studio.routes.GeminiService", lambda settings: object())
    monkeypatch.setattr("thumbnail_studio.routes.job_store", FakeJobStore())

    response = client.post(
        "/api/transform-jobs",
        json={
            "prompt": "keep the same thumbnail and regenerate it in 4K only",
            "videos": [
                {
                    "id": "video-1",
                    "title": "Video 1",
                    "officialThumbnailUrl": "https://example.com/1.jpg",
                    "pytubeThumbnailUrl": None,
                },
                {
                    "id": "video-2",
                    "title": "Video 2",
                    "officialThumbnailUrl": None,
                    "pytubeThumbnailUrl": "https://example.com/2.jpg",
                },
            ],
        },
    )

    assert response.status_code == 202
    assert response.json["ok"] is True
    assert response.json["jobId"] == "job-123"
    assert response.json["videoIds"] == ["video-1", "video-2"]
    assert response.json["estimatedCostUsd"] == pytest.approx(0.302)
    assert captured["prompt"] == "keep the same thumbnail and regenerate it in 4K only"
    assert len(captured["videos"]) == 2


def test_api_transform_job_status_serializes_generated_urls(client, monkeypatch: pytest.MonkeyPatch):
    class FakeJobStore:
        def get_job(self, job_id):
            assert job_id == "job-123"
            return {
                "jobId": "job-123",
                "status": "completed",
                "message": "1 thumbnails uploaded to YouTube.",
                "videoIds": ["video-1"],
                "currentVideoId": None,
                "currentVideoTitle": None,
                "totalCount": 1,
                "completedCount": 1,
                "successCount": 1,
                "failureCount": 0,
                "processed": [
                    {
                        "videoId": "video-1",
                        "sourceUsed": "official",
                        "archiveFilename": "video-1_generated_4k.jpg",
                        "uploadReadyFilename": "video-1_youtube_upload.jpg",
                        "model": "fake-image-model",
                        "notes": None,
                    }
                ],
                "failed": [],
                "createdAt": "2026-03-15T10:00:00+00:00",
                "updatedAt": "2026-03-15T10:01:00+00:00",
            }

    monkeypatch.setattr("thumbnail_studio.routes.job_store", FakeJobStore())

    response = client.get("/api/transform-jobs/job-123")

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["processed"][0]["videoId"] == "video-1"
    assert response.json["processed"][0]["notes"] is None
    assert response.json["processed"][0]["uploadReadyUrl"].endswith(
        "/media/generated/video-1_youtube_upload.jpg"
    )


def test_api_transform_job_status_includes_failure_log(client, monkeypatch: pytest.MonkeyPatch):
    class FakeJobStore:
        def get_job(self, job_id):
            assert job_id == "job-123"
            return {
                "jobId": "job-123",
                "status": "failed",
                "message": "No selected thumbnail could be updated.",
                "videoIds": ["video-1"],
                "currentVideoId": None,
                "currentVideoTitle": None,
                "totalCount": 1,
                "completedCount": 1,
                "successCount": 0,
                "failureCount": 1,
                "processed": [],
                "failed": [
                    {
                        "videoId": "video-1",
                        "message": "Gemini blocked this thumbnail request (OTHER).",
                        "log": "Summary\nGemini blocked this thumbnail request (OTHER).\n\nContext\nPrompt feedback block reason: OTHER",
                    }
                ],
                "createdAt": "2026-03-15T10:00:00+00:00",
                "updatedAt": "2026-03-15T10:01:00+00:00",
            }

    monkeypatch.setattr("thumbnail_studio.routes.job_store", FakeJobStore())

    response = client.get("/api/transform-jobs/job-123")

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["failed"][0]["videoId"] == "video-1"
    assert "Prompt feedback block reason: OTHER" in response.json["failed"][0]["log"]


def test_setup_gemini_saves_key_in_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text(VALID_WEB_CLIENT, encoding="utf-8")

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(client_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    app = create_app()
    app.config.update(TESTING=True)
    test_client = app.test_client()

    response = test_client.post(
        "/setup/gemini",
        data={"gemini_api_key": "AIza-test-setup"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Base setup is ready" in response.data
    assert "GEMINI_API_KEY='AIza-test-setup'" in env_file.read_text(encoding="utf-8")


def test_setup_google_client_secret_upload_saves_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-gemini-key\n", encoding="utf-8")
    client_secret = tmp_path / "client_secret.json"

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(client_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    app = create_app()
    app.config.update(TESTING=True)
    test_client = app.test_client()

    response = test_client.post(
        "/setup/google-client-secret",
        data={
            "client_secret_file": (
                BytesIO(VALID_WEB_CLIENT.encode("utf-8")),
                "client_secret.json",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Base setup is ready" in response.data
    assert '"client_id": "id"' in client_secret.read_text(encoding="utf-8")


def test_setup_google_client_secret_upload_rejects_mismatched_redirects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-gemini-key\n", encoding="utf-8")
    client_secret = tmp_path / "client_secret.json"

    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(client_secret))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "youtube_token.json"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    app = create_app()
    app.config.update(TESTING=True)
    test_client = app.test_client()

    response = test_client.post(
        "/setup/google-client-secret",
        data={
            "client_secret_file": (
                BytesIO(
                    (
                        '{"web":{"client_id":"id","client_secret":"secret",'
                        '"redirect_uris":["http://localhost:6000/auth/google/callback"],'
                        '"javascript_origins":["http://localhost:6000"]}}'
                    ).encode("utf-8")
                ),
                "client_secret.json",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Missing from client_secret.json" in response.data
    assert not client_secret.exists()


def test_setup_google_client_secret_recheck_reports_current_status(client):
    response = client.post(
        "/setup/google-client-secret/recheck",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Current uploaded client_secret.json still matches this app." in response.data


def test_setup_google_client_secret_reset_removes_file_and_restores_dropzone(
    client,
    app,
):
    response = client.post(
        "/setup/google-client-secret/reset",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"client_secret.json removed. Upload a new file to continue." in response.data
    assert b"Drop `client_secret.json` here" in response.data

    with app.app_context():
        assert not app.config["APP_SETTINGS"].google_client_secrets_file.exists()


def test_auth_google_start_stores_code_verifier_in_session(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeFlow:
        code_verifier = "verifier-abc"

        def authorization_url(self, **kwargs):
            return "https://accounts.google.com/o/oauth2/auth?state=state-123", "state-123"

    monkeypatch.setattr("thumbnail_studio.routes.build_oauth_flow", lambda settings: FakeFlow())

    response = client.get("/auth/google/start", follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["oauth_state"] == "state-123"
        assert session["oauth_code_verifier"] == "verifier-abc"


def test_auth_google_callback_allows_local_http_transport(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, str] = {}

    class FakeFlow:
        credentials = object()

        def fetch_token(self, *, authorization_response):
            captured["authorization_response"] = authorization_response

    monkeypatch.delenv("OAUTHLIB_INSECURE_TRANSPORT", raising=False)
    monkeypatch.setattr(
        "thumbnail_studio.routes.build_oauth_flow",
        lambda settings, state=None, code_verifier=None: captured.update(
            {
                "state": state or "",
                "code_verifier": code_verifier or "",
            }
        ) or FakeFlow(),
    )
    monkeypatch.setattr("thumbnail_studio.routes.save_credentials", lambda token_path, credentials: captured.update({"saved": str(token_path)}))

    with client.session_transaction() as session:
        session["oauth_state"] = "state-123"
        session["oauth_code_verifier"] = "verifier-abc"

    response = client.get("/auth/google/callback?state=state-123&code=abc123", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert captured
    assert captured["state"] == "state-123"
    assert captured["code_verifier"] == "verifier-abc"
    assert captured["authorization_response"].startswith("http://localhost/")
    assert captured["saved"].endswith("youtube_token.json")
    assert "OAUTHLIB_INSECURE_TRANSPORT" in os.environ


def test_app_logging_writes_to_log_file(app):
    log_file = app.config["APP_SETTINGS"].app_log_file
    logger = logging.getLogger("thumbnail_studio.tests")

    logger.info("test log write")

    for handler in logging.getLogger("thumbnail_studio").handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    assert log_file.exists()
    assert "test log write" in log_file.read_text(encoding="utf-8")
