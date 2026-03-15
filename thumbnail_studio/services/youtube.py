from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from pathlib import Path
import re

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pytube import YouTube

from thumbnail_studio.config import AppConfig
from thumbnail_studio.services.image_tools import download_image, pick_best_thumbnail_url

logger = logging.getLogger(__name__)

ISO_8601_DURATION_RE = re.compile(
    r"^P"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?$"
)
MIN_LONG_FORM_SECONDS = 180


@dataclass(slots=True)
class ChannelSummary:
    title: str
    uploads_playlist_id: str
    channel_id: str


@dataclass(slots=True)
class VideoSummary:
    id: str
    title: str
    description: str
    published_at: str
    privacy_status: str
    watch_url: str
    original_thumbnail_url: str | None
    current_thumbnail_url: str | None
    official_thumbnail_url: str | None
    pytube_thumbnail_url: str | None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


class YouTubeService:
    def __init__(self, settings: AppConfig, credentials) -> None:
        self.settings = settings
        self.api = build("youtube", "v3", credentials=credentials)

    def get_channel_summary(self) -> ChannelSummary:
        response = self.api.channels().list(part="snippet,contentDetails", mine=True).execute()
        items = response.get("items", [])
        if not items:
            raise ValueError("No YouTube channel found for the authenticated account.")

        channel = items[0]
        uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        return ChannelSummary(
            title=channel["snippet"]["title"],
            uploads_playlist_id=uploads_playlist_id,
            channel_id=channel["id"],
        )

    def list_recent_videos(self, limit: int | None = None) -> tuple[ChannelSummary, list[VideoSummary]]:
        channel = self.get_channel_summary()
        max_items = min(limit or self.settings.max_videos, 50)
        videos: list[VideoSummary] = []
        next_page_token: str | None = None

        while len(videos) < max_items:
            playlist_kwargs = {
                "part": "contentDetails",
                "playlistId": channel.uploads_playlist_id,
                "maxResults": 50,
            }
            if next_page_token:
                playlist_kwargs["pageToken"] = next_page_token

            playlist_response = self.api.playlistItems().list(**playlist_kwargs).execute()
            video_ids = [
                item["contentDetails"]["videoId"]
                for item in playlist_response.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            if not video_ids:
                break

            videos_response = (
                self.api.videos()
                .list(
                    part="snippet,status,contentDetails",
                    id=",".join(video_ids),
                    maxResults=len(video_ids),
                )
                .execute()
            )
            items_by_id = {
                item["id"]: item
                for item in videos_response.get("items", [])
                if item.get("id")
            }

            for video_id in video_ids:
                item = items_by_id.get(video_id)
                if item is None or self._is_short_video(item):
                    continue

                official_url = pick_best_thumbnail_url(item.get("snippet", {}).get("thumbnails"))
                pytube_url = self._resolve_pytube_thumbnail_url(video_id)
                videos.append(
                    VideoSummary(
                        id=video_id,
                        title=item["snippet"]["title"],
                        description=item["snippet"].get("description", ""),
                        published_at=item["snippet"].get("publishedAt", ""),
                        privacy_status=item.get("status", {}).get("privacyStatus", "unknown"),
                        watch_url=f"https://www.youtube.com/watch?v={video_id}",
                        original_thumbnail_url=official_url or pytube_url,
                        current_thumbnail_url=official_url or pytube_url,
                        official_thumbnail_url=official_url,
                        pytube_thumbnail_url=pytube_url,
                    )
                )
                if len(videos) >= max_items:
                    break

            next_page_token = playlist_response.get("nextPageToken")
            if not next_page_token:
                break

        return channel, videos[:max_items]

    def download_thumbnail(
        self,
        video_id: str,
        official_thumbnail_url: str | None,
        pytube_thumbnail_url: str | None,
    ) -> tuple[Path, str]:
        candidates = [
            ("official", official_thumbnail_url),
            ("pytube", pytube_thumbnail_url),
        ]
        destination = self.settings.downloads_dir / f"{video_id}_source.jpg"
        logger.info("Thumbnail download start video_id=%s destination=%s", video_id, destination.name)

        errors: list[str] = []
        for source_name, url in candidates:
            if not url:
                continue
            try:
                download_image(url, destination)
                logger.info(
                    "Thumbnail download success video_id=%s source=%s url=%s",
                    video_id,
                    source_name,
                    url,
                )
                return destination, source_name
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Thumbnail download failed video_id=%s source=%s error=%s",
                    video_id,
                    source_name,
                    exc,
                )
                errors.append(f"{source_name}: {exc}")

        raise ValueError("Unable to download thumbnail. " + " | ".join(errors))

    def set_thumbnail(self, video_id: str, image_path: Path) -> None:
        logger.info(
            "YouTube thumbnail upload start video_id=%s file=%s size_bytes=%s",
            video_id,
            image_path.name,
            image_path.stat().st_size if image_path.exists() else "missing",
        )
        media = MediaFileUpload(
            str(image_path),
            mimetype="image/jpeg",
            chunksize=-1,
            resumable=False,
        )
        self.api.thumbnails().set(videoId=video_id, media_body=media).execute()
        logger.info("YouTube thumbnail upload success video_id=%s file=%s", video_id, image_path.name)

    def _resolve_pytube_thumbnail_url(self, video_id: str) -> str | None:
        try:
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            return yt.thumbnail_url
        except Exception:  # noqa: BLE001
            return None

    def _is_short_video(self, item: dict) -> bool:
        duration_seconds = self._parse_duration_seconds(
            item.get("contentDetails", {}).get("duration"),
        )
        if duration_seconds is None:
            return False
        return duration_seconds < MIN_LONG_FORM_SECONDS

    @staticmethod
    def _parse_duration_seconds(raw_duration: str | None) -> int | None:
        if not raw_duration:
            return None

        match = ISO_8601_DURATION_RE.match(raw_duration)
        if match is None:
            return None

        days = int(match.group("days") or 0)
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
