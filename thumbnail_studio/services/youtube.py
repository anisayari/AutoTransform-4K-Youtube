from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pytube import YouTube

from thumbnail_studio.config import AppConfig
from thumbnail_studio.services.image_tools import download_image, pick_best_thumbnail_url


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

        playlist_response = (
            self.api.playlistItems()
            .list(
                part="contentDetails",
                playlistId=channel.uploads_playlist_id,
                maxResults=max_items,
            )
            .execute()
        )
        video_ids = [
            item["contentDetails"]["videoId"]
            for item in playlist_response.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]
        if not video_ids:
            return channel, []

        videos_response = (
            self.api.videos()
            .list(
                part="snippet,status",
                id=",".join(video_ids),
                maxResults=max_items,
            )
            .execute()
        )

        videos = []
        for item in videos_response.get("items", []):
            official_url = pick_best_thumbnail_url(item.get("snippet", {}).get("thumbnails"))
            pytube_url = self._resolve_pytube_thumbnail_url(item["id"])
            videos.append(
                VideoSummary(
                    id=item["id"],
                    title=item["snippet"]["title"],
                    description=item["snippet"].get("description", ""),
                    published_at=item["snippet"].get("publishedAt", ""),
                    privacy_status=item.get("status", {}).get("privacyStatus", "unknown"),
                    watch_url=f"https://www.youtube.com/watch?v={item['id']}",
                    current_thumbnail_url=official_url or pytube_url,
                    official_thumbnail_url=official_url,
                    pytube_thumbnail_url=pytube_url,
                )
            )

        videos.sort(key=lambda video: video.published_at, reverse=True)
        return channel, videos

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

        errors: list[str] = []
        for source_name, url in candidates:
            if not url:
                continue
            try:
                download_image(url, destination)
                return destination, source_name
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{source_name}: {exc}")

        raise ValueError("Unable to download thumbnail. " + " | ".join(errors))

    def set_thumbnail(self, video_id: str, image_path: Path) -> None:
        media = MediaFileUpload(
            str(image_path),
            mimetype="image/jpeg",
            chunksize=-1,
            resumable=False,
        )
        self.api.thumbnails().set(videoId=video_id, media_body=media).execute()

    def _resolve_pytube_thumbnail_url(self, video_id: str) -> str | None:
        try:
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            return yt.thumbnail_url
        except Exception:  # noqa: BLE001
            return None
