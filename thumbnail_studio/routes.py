from __future__ import annotations

from http import HTTPStatus

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from thumbnail_studio.config import AppConfig
from thumbnail_studio.services.auth import (
    build_oauth_flow,
    clear_credentials,
    credentials_status,
    load_credentials,
    save_credentials,
)
from thumbnail_studio.services.gemini import GeminiService
from thumbnail_studio.services.setup import (
    reload_settings,
    save_gemini_api_key,
    save_google_client_secret,
)
from thumbnail_studio.services.youtube import YouTubeService


bp = Blueprint("app", __name__)


def settings() -> AppConfig:
    return current_app.config["APP_SETTINGS"]


def refresh_settings() -> AppConfig:
    refreshed = reload_settings(settings())
    current_app.config["APP_SETTINGS"] = refreshed
    return refreshed


def build_transform_result(video_id: str, source_name: str, generation) -> dict[str, object]:
    return {
        "videoId": video_id,
        "sourceUsed": source_name,
        "archiveUrl": url_for(
            "app.media_file",
            media_kind="generated",
            filename=generation.archive_path.name,
        ),
        "uploadReadyUrl": url_for(
            "app.media_file",
            media_kind="generated",
            filename=generation.upload_ready_path.name,
        ),
        "model": generation.model,
    }


def require_credentials():
    credentials = load_credentials(settings())
    if credentials is None or not credentials.valid:
        return None, (
            jsonify(
                {
                    "ok": False,
                    "message": "YouTube authentication is missing. Connect your Google account first.",
                }
            ),
            HTTPStatus.UNAUTHORIZED,
        )
    return credentials, None


def transform_video_with_services(
    youtube: YouTubeService,
    gemini: GeminiService,
    *,
    video_id: str,
    prompt: str,
    official_thumbnail_url: str | None,
    pytube_thumbnail_url: str | None,
) -> dict[str, object]:
    source_path, source_name = youtube.download_thumbnail(
        video_id=video_id,
        official_thumbnail_url=official_thumbnail_url,
        pytube_thumbnail_url=pytube_thumbnail_url,
    )
    generation = gemini.transform_thumbnail(
        source_path=source_path,
        prompt=prompt,
        video_id=video_id,
    )
    youtube.set_thumbnail(video_id, generation.upload_ready_path)
    return build_transform_result(video_id, source_name, generation)


def setup_feedback() -> tuple[str, str]:
    success_messages = {
        "gemini": "Clé Gemini enregistrée.",
        "oauth": "client_secret.json enregistré.",
        "ready": "La configuration de base est prête. Tu peux connecter YouTube.",
    }
    error_messages = {
        "missing_client_secret": "Ajoute d'abord ton fichier OAuth Google.",
    }

    success = request.args.get("success", "").strip()
    error = request.args.get("error", "").strip()
    message = request.args.get("message", "").strip()
    error_message = request.args.get("error_message", "").strip()

    return (
        message or success_messages.get(success, ""),
        error_message or error_messages.get(error, ""),
    )


@bp.get("/")
def index():
    app_settings = settings()
    if not app_settings.setup_complete:
        return redirect(url_for("app.setup"))

    status = credentials_status(app_settings)
    return render_template(
        "index.html",
        auth_status=status,
        default_prompt=app_settings.default_transform_prompt,
    )


@bp.get("/setup")
def setup():
    app_settings = settings()
    message, error_message = setup_feedback()
    return render_template(
        "setup.html",
        auth_status=credentials_status(app_settings),
        setup_message=message,
        setup_error=error_message,
    )


@bp.post("/setup/gemini")
def setup_gemini():
    try:
        save_gemini_api_key(settings(), request.form.get("gemini_api_key", ""))
        refreshed = refresh_settings()
    except ValueError as exc:
        return redirect(url_for("app.setup", error_message=str(exc)))

    success = "ready" if refreshed.setup_complete else "gemini"
    return redirect(url_for("app.setup", success=success))


@bp.post("/setup/google-client-secret")
def setup_google_client_secret():
    try:
        save_google_client_secret(settings(), request.files.get("client_secret_file"))
        refreshed = refresh_settings()
    except ValueError as exc:
        return redirect(url_for("app.setup", error_message=str(exc)))

    success = "ready" if refreshed.setup_complete else "oauth"
    return redirect(url_for("app.setup", success=success))


@bp.get("/auth/google/start")
def auth_google_start():
    app_settings = settings()
    if not app_settings.client_secrets_present:
        return redirect(
            url_for("app.setup", error="missing_client_secret"),
        )

    try:
        flow = build_oauth_flow(app_settings)
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
    except Exception as exc:  # noqa: BLE001
        return redirect(url_for("app.setup", error_message=str(exc)))

    session["oauth_state"] = state
    return redirect(authorization_url)


@bp.get("/auth/google/callback")
def auth_google_callback():
    flow = build_oauth_flow(settings(), state=session.get("oauth_state"))
    flow.fetch_token(authorization_response=request.url)
    save_credentials(settings().youtube_token_file, flow.credentials)
    session.pop("oauth_state", None)
    return redirect(url_for("app.index"))


@bp.post("/auth/google/disconnect")
def auth_google_disconnect():
    clear_credentials(settings().youtube_token_file)
    session.pop("oauth_state", None)
    return jsonify({"ok": True})


@bp.get("/api/session")
def api_session():
    status = credentials_status(settings())
    return jsonify(
        {
            "ok": True,
            "status": status,
            "defaultPrompt": settings().default_transform_prompt,
            "maxVideos": settings().max_videos,
            "imageModel": settings().gemini_image_model,
            "setupComplete": settings().setup_complete,
        }
    )


@bp.get("/api/videos")
def api_videos():
    credentials, error = require_credentials()
    if error:
        return error

    youtube = YouTubeService(settings(), credentials)
    channel, videos = youtube.list_recent_videos(limit=request.args.get("limit", type=int))
    return jsonify(
        {
            "ok": True,
            "channel": {
                "title": channel.title,
                "channelId": channel.channel_id,
            },
            "videos": [video.to_dict() for video in videos],
        }
    )


@bp.post("/api/videos/<video_id>/transform")
def api_transform_video(video_id: str):
    credentials, error = require_credentials()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or settings().default_transform_prompt).strip()
    official_thumbnail_url = payload.get("officialThumbnailUrl")
    pytube_thumbnail_url = payload.get("pytubeThumbnailUrl")

    if not prompt:
        return (
            jsonify({"ok": False, "message": "A transformation prompt is required."}),
            HTTPStatus.BAD_REQUEST,
        )

    try:
        youtube = YouTubeService(settings(), credentials)
        gemini = GeminiService(settings())
        result = transform_video_with_services(
            youtube,
            gemini,
            prompt=prompt,
            video_id=video_id,
            official_thumbnail_url=official_thumbnail_url,
            pytube_thumbnail_url=pytube_thumbnail_url,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            jsonify({"ok": False, "message": str(exc)}),
            HTTPStatus.BAD_REQUEST,
        )

    return jsonify(
        {
            "ok": True,
            "message": "Thumbnail transformed and uploaded to YouTube.",
            **result,
        }
    )


@bp.post("/api/videos/batch-transform")
def api_batch_transform():
    credentials, error = require_credentials()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or settings().default_transform_prompt).strip()
    videos = payload.get("videos") or []

    if not prompt:
        return (
            jsonify({"ok": False, "message": "A transformation prompt is required."}),
            HTTPStatus.BAD_REQUEST,
        )
    if not isinstance(videos, list) or not videos:
        return (
            jsonify({"ok": False, "message": "Select at least one video to transform."}),
            HTTPStatus.BAD_REQUEST,
        )

    try:
        youtube = YouTubeService(settings(), credentials)
        gemini = GeminiService(settings())
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": str(exc)}), HTTPStatus.BAD_REQUEST

    processed: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []

    for item in videos:
        video_id = str(item.get("id", "")).strip()
        if not video_id:
            failed.append(
                {
                    "videoId": "",
                    "message": "A selected video is missing its id.",
                }
            )
            continue

        try:
            result = transform_video_with_services(
                youtube,
                gemini,
                video_id=video_id,
                prompt=prompt,
                official_thumbnail_url=item.get("officialThumbnailUrl"),
                pytube_thumbnail_url=item.get("pytubeThumbnailUrl"),
            )
            processed.append(result)
        except Exception as exc:  # noqa: BLE001
            failed.append({"videoId": video_id, "message": str(exc)})

    success_count = len(processed)
    failure_count = len(failed)
    if success_count and failure_count:
        message = f"{success_count} thumbnails updated, {failure_count} failed."
    elif success_count:
        message = f"{success_count} thumbnails updated on YouTube."
    else:
        message = "No selected thumbnail could be updated."

    return jsonify(
        {
            "ok": True,
            "message": message,
            "processed": processed,
            "failed": failed,
            "successCount": success_count,
            "failureCount": failure_count,
            "hasFailures": bool(failed),
        }
    )


@bp.get("/media/<media_kind>/<path:filename>")
def media_file(media_kind: str, filename: str):
    folder_map = {
        "downloads": settings().downloads_dir,
        "generated": settings().generated_dir,
    }
    folder = folder_map.get(media_kind)
    if folder is None:
        return jsonify({"ok": False, "message": "Unknown media folder."}), HTTPStatus.NOT_FOUND
    return send_from_directory(folder, filename)
