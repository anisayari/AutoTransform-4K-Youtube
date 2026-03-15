from __future__ import annotations

from http import HTTPStatus
import logging

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
    configure_oauth_transport,
    credentials_status,
    load_credentials,
    oauth_client_config_status,
    save_credentials,
)
from thumbnail_studio.services.gemini import GeminiService
from thumbnail_studio.services.jobs import TransformJobStore
from thumbnail_studio.services.setup import (
    delete_google_client_secret,
    reload_settings,
    save_gemini_api_key,
    save_google_client_secret,
)
from thumbnail_studio.services.youtube import YouTubeService


bp = Blueprint("app", __name__)
job_store = TransformJobStore()
logger = logging.getLogger(__name__)


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
        "archiveFilename": generation.archive_path.name,
        "uploadReadyFilename": generation.upload_ready_path.name,
        "model": generation.model,
        "notes": getattr(generation, "notes", None),
    }


def serialize_transform_result(result: dict[str, object]) -> dict[str, object]:
    return {
        "videoId": result["videoId"],
        "sourceUsed": result["sourceUsed"],
        "archiveUrl": url_for(
            "app.media_file",
            media_kind="generated",
            filename=str(result["archiveFilename"]),
        ),
        "uploadReadyUrl": url_for(
            "app.media_file",
            media_kind="generated",
            filename=str(result["uploadReadyFilename"]),
        ),
        "model": result["model"],
        "notes": result.get("notes"),
    }


def serialize_transform_job(job: dict[str, object]) -> dict[str, object]:
    return {
        "jobId": job["jobId"],
        "status": job["status"],
        "message": job["message"],
        "videoIds": job["videoIds"],
        "currentVideoId": job["currentVideoId"],
        "currentVideoTitle": job["currentVideoTitle"],
        "totalCount": job["totalCount"],
        "completedCount": job["completedCount"],
        "successCount": job["successCount"],
        "failureCount": job["failureCount"],
        "processed": [
            serialize_transform_result(result) for result in job.get("processed", [])
        ],
        "failed": job["failed"],
        "createdAt": job["createdAt"],
        "updatedAt": job["updatedAt"],
        "hasFailures": bool(job["failed"]),
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


def build_async_transform_runner(app_settings: AppConfig):
    youtube = None
    gemini = None

    def run(item: dict[str, object], prompt: str) -> dict[str, object]:
        nonlocal youtube, gemini

        if youtube is None or gemini is None:
            credentials = load_credentials(app_settings)
            if credentials is None or not credentials.valid:
                raise ValueError(
                    "YouTube authentication is missing. Connect your Google account first."
                )
            youtube = YouTubeService(app_settings, credentials)
            gemini = GeminiService(app_settings)

        return transform_video_with_services(
            youtube,
            gemini,
            video_id=str(item.get("id", "")).strip(),
            prompt=prompt,
            official_thumbnail_url=item.get("officialThumbnailUrl"),
            pytube_thumbnail_url=item.get("pytubeThumbnailUrl"),
        )

    return run


def setup_feedback() -> tuple[str, str]:
    success_messages = {
        "gemini": "Gemini API key saved.",
        "oauth": "client_secret.json uploaded.",
        "ready": "Base setup is ready. You can connect YouTube now.",
    }
    error_messages = {
        "missing_client_secret": "Upload your Google OAuth file first.",
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
    status = credentials_status(app_settings)
    if not status["setupComplete"]:
        return redirect(url_for("app.setup"))

    return render_template(
        "index.html",
        auth_status=status,
        default_prompt=app_settings.default_transform_prompt,
        gemini_cost_per_image=app_settings.gemini_estimated_cost_per_4k_image_usd,
    )


@bp.get("/setup")
def setup():
    app_settings = settings()
    message, error_message = setup_feedback()
    return render_template(
        "setup.html",
        auth_status=credentials_status(app_settings, include_gemini_secret=True),
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

    refreshed_status = credentials_status(refreshed)
    success = "ready" if refreshed_status["setupComplete"] else "gemini"
    return redirect(url_for("app.setup", success=success))


@bp.post("/setup/google-client-secret")
def setup_google_client_secret():
    try:
        save_google_client_secret(settings(), request.files.get("client_secret_file"))
        refreshed = refresh_settings()
    except ValueError as exc:
        return redirect(url_for("app.setup", error_message=str(exc)))

    refreshed_status = credentials_status(refreshed)
    success = "ready" if refreshed_status["setupComplete"] else "oauth"
    return redirect(url_for("app.setup", success=success))


@bp.post("/setup/google-client-secret/recheck")
def setup_google_client_secret_recheck():
    refreshed = refresh_settings()
    oauth_config = oauth_client_config_status(refreshed)
    if not refreshed.client_secrets_present:
        return redirect(url_for("app.setup", error_message="No uploaded client_secret.json to recheck."))

    if oauth_config["valid"]:
        return redirect(
            url_for(
                "app.setup",
                message=(
                    "Current uploaded client_secret.json still matches this app. "
                    "If you changed Google Cloud settings, download a new file and use Upload new file."
                ),
            )
        )
    return redirect(
        url_for(
            "app.setup",
            error_message=(
                f"{oauth_config['message']} "
                "If you changed the OAuth client in Google Cloud, download a new client_secret.json and upload it here."
            ),
        )
    )


@bp.post("/setup/google-client-secret/reset")
def setup_google_client_secret_reset():
    delete_google_client_secret(settings())
    refresh_settings()
    return redirect(
        url_for(
            "app.setup",
            message="client_secret.json removed. Upload a new file to continue.",
        )
    )


@bp.get("/auth/google/start")
def auth_google_start():
    app_settings = settings()
    if not app_settings.client_secrets_present:
        return redirect(
            url_for("app.setup", error="missing_client_secret"),
        )

    oauth_config = oauth_client_config_status(app_settings)
    if not oauth_config["valid"]:
        return redirect(url_for("app.setup", error_message=oauth_config["message"]))

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
    session["oauth_code_verifier"] = flow.code_verifier
    return redirect(authorization_url)


@bp.get("/auth/google/callback")
def auth_google_callback():
    app_settings = settings()
    configure_oauth_transport(app_settings)

    try:
        flow = build_oauth_flow(
            app_settings,
            state=session.get("oauth_state"),
            code_verifier=session.get("oauth_code_verifier"),
        )
        flow.fetch_token(authorization_response=request.url)
        save_credentials(app_settings.youtube_token_file, flow.credentials)
        session.pop("oauth_state", None)
        session.pop("oauth_code_verifier", None)
        return redirect(url_for("app.index"))
    except Exception as exc:  # noqa: BLE001
        session.pop("oauth_state", None)
        session.pop("oauth_code_verifier", None)
        return redirect(url_for("app.setup", error_message=str(exc)))


@bp.post("/auth/google/disconnect")
def auth_google_disconnect():
    clear_credentials(settings().youtube_token_file)
    session.pop("oauth_state", None)
    session.pop("oauth_code_verifier", None)
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
            "geminiCostPerImageUsd": settings().gemini_estimated_cost_per_4k_image_usd,
            "setupComplete": status["setupComplete"],
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
        logger.info("Single transform requested video_id=%s", video_id)
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
        logger.exception("Single transform failed video_id=%s", video_id)
        return (
            jsonify({"ok": False, "message": str(exc)}),
            HTTPStatus.BAD_REQUEST,
        )

    return jsonify(
        {
            "ok": True,
            "message": "Thumbnail transformed and uploaded to YouTube.",
            **serialize_transform_result(result),
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
        logger.exception("Batch transform setup failed")
        return jsonify({"ok": False, "message": str(exc)}), HTTPStatus.BAD_REQUEST

    logger.info("Batch transform requested count=%s", len(videos))
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
            logger.exception("Batch transform failed video_id=%s", video_id)
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
            "processed": [serialize_transform_result(result) for result in processed],
            "failed": failed,
            "successCount": success_count,
            "failureCount": failure_count,
            "hasFailures": bool(failed),
        }
    )


@bp.post("/api/transform-jobs")
def api_create_transform_job():
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
        YouTubeService(settings(), credentials)
        GeminiService(settings())
        logger.info("Async transform job requested count=%s", len(videos))
        job = job_store.create_transform_job(
            prompt=prompt,
            videos=videos,
            runner=build_async_transform_runner(settings()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Async transform job creation failed")
        return jsonify({"ok": False, "message": str(exc)}), HTTPStatus.BAD_REQUEST

    estimated_cost = (
        len(videos) * settings().gemini_estimated_cost_per_4k_image_usd
    )
    return (
        jsonify(
            {
                "ok": True,
                "message": "Transform job queued.",
                "estimatedCostUsd": round(estimated_cost, 3),
                **serialize_transform_job(job),
            }
        ),
        HTTPStatus.ACCEPTED,
    )


@bp.get("/api/transform-jobs/<job_id>")
def api_transform_job_status(job_id: str):
    job = job_store.get_job(job_id)
    if job is None:
        return jsonify({"ok": False, "message": "Transform job not found."}), HTTPStatus.NOT_FOUND

    return jsonify(
        {
            "ok": True,
            **serialize_transform_job(job),
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
