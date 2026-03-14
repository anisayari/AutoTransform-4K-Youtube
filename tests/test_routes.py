from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest

from thumbnail_studio import create_app


@dataclass
class FakeCredentials:
    valid: bool = True


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")
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
    assert b"Setup rapide" in response.data
    assert str(missing_secret).encode() in response.data


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


def test_setup_gemini_saves_key_in_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text('{"web":{"client_id":"id","client_secret":"secret"}}', encoding="utf-8")

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
    assert b"configuration de base est pr" in response.data
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
                BytesIO(b'{"web":{"client_id":"id","client_secret":"secret"}}'),
                "client_secret.json",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"configuration de base est pr" in response.data
    assert '"client_id": "id"' in client_secret.read_text(encoding="utf-8")
