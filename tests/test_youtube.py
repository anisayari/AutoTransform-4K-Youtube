from __future__ import annotations

from types import SimpleNamespace

from thumbnail_studio.services.youtube import YouTubeService


class _FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeChannelsAPI:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "items": [
                    {
                        "id": "channel-1",
                        "snippet": {"title": "Test Channel"},
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": "uploads-playlist"}
                        },
                    }
                ]
            }
        )


class _FakePlaylistItemsAPI:
    def __init__(self):
        self.calls = 0

    def list(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _FakeRequest(
                {
                    "items": [
                        {"contentDetails": {"videoId": "short-1"}},
                        {"contentDetails": {"videoId": "long-1"}},
                    ],
                    "nextPageToken": "page-2",
                }
            )
        return _FakeRequest(
            {
                "items": [
                    {"contentDetails": {"videoId": "short-2"}},
                    {"contentDetails": {"videoId": "long-2"}},
                ]
            }
        )


class _FakeVideosAPI:
    def list(self, **kwargs):
        ids = kwargs["id"].split(",")
        items = []
        for video_id in ids:
            if video_id == "short-1":
                items.append(
                    {
                        "id": "short-1",
                        "snippet": {
                            "title": "Short 1",
                            "publishedAt": "2025-01-10T10:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.com/short1.jpg"}},
                        },
                        "status": {"privacyStatus": "public"},
                        "contentDetails": {"duration": "PT45S"},
                    }
                )
            elif video_id == "long-1":
                items.append(
                    {
                        "id": "long-1",
                        "snippet": {
                            "title": "Long 1",
                            "publishedAt": "2025-01-09T10:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.com/long1.jpg"}},
                        },
                        "status": {"privacyStatus": "public"},
                        "contentDetails": {"duration": "PT10M"},
                    }
                )
            elif video_id == "short-2":
                items.append(
                    {
                        "id": "short-2",
                        "snippet": {
                            "title": "Short 2",
                            "publishedAt": "2025-01-08T10:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.com/short2.jpg"}},
                        },
                        "status": {"privacyStatus": "public"},
                        "contentDetails": {"duration": "PT2M30S"},
                    }
                )
            elif video_id == "long-2":
                items.append(
                    {
                        "id": "long-2",
                        "snippet": {
                            "title": "Long 2",
                            "publishedAt": "2025-01-07T10:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.com/long2.jpg"}},
                        },
                        "status": {"privacyStatus": "public"},
                        "contentDetails": {"duration": "PT4M"},
                    }
                )
        return _FakeRequest({"items": items})


class _FakeAPI:
    def __init__(self):
        self._playlist_items = _FakePlaylistItemsAPI()
        self._videos = _FakeVideosAPI()

    def channels(self):
        return _FakeChannelsAPI()

    def playlistItems(self):
        return self._playlist_items

    def videos(self):
        return self._videos


def _build_service(max_videos: int = 2) -> YouTubeService:
    service = object.__new__(YouTubeService)
    service.settings = SimpleNamespace(max_videos=max_videos)
    service.api = _FakeAPI()
    service._resolve_pytube_thumbnail_url = lambda _video_id: None
    return service


def test_list_recent_videos_skips_videos_shorter_than_three_minutes():
    service = _build_service(max_videos=2)

    channel, videos = service.list_recent_videos()

    assert channel.title == "Test Channel"
    assert [video.id for video in videos] == ["long-1", "long-2"]


def test_is_short_video_uses_simple_under_three_minutes_rule():
    service = _build_service()

    assert service._is_short_video(
        {
            "contentDetails": {"duration": "PT59S"},
        }
    )
    assert service._is_short_video(
        {
            "contentDetails": {"duration": "PT2M30S"},
        }
    )
    assert not service._is_short_video(
        {
            "contentDetails": {"duration": "PT3M"},
        }
    )
    assert not service._is_short_video(
        {
            "contentDetails": {"duration": "PT4M"},
        }
    )
