from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .base import (
    CollectRequest,
    CollectResult,
    CoverageStatus,
    JSONTransport,
    SocialPost,
    UrllibJSONTransport,
    decode_cursor_map,
    dedupe_posts,
    encode_cursor_map,
    env_value,
    ensure_api_success,
    normalize_timestamp,
    utc_now_iso,
)


def youtube_channel_reference(source: str) -> tuple[str, str] | None:
    clean = source.strip().rstrip("/")
    if not clean:
        return None
    if re.fullmatch(r"UC[A-Za-z0-9_-]{10,}", clean):
        return "id", clean
    if clean.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_.-]{3,}", clean):
        return "forHandle", clean
    parsed = urlparse(clean if "://" in clean else f"https://{clean}")
    if parsed.netloc.lower() not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "channel" and re.fullmatch(r"UC[A-Za-z0-9_-]{10,}", parts[1]):
        return "id", parts[1]
    if parts and parts[0].startswith("@") and re.fullmatch(r"@[A-Za-z0-9_.-]{3,}", parts[0]):
        return "forHandle", parts[0]
    if len(parts) >= 2 and parts[0] == "user":
        return "forUsername", parts[1]
    return None


class YouTubeAdapter:
    platform = "youtube"
    api_root = "https://www.googleapis.com/youtube/v3"

    def __init__(self, transport: JSONTransport | None = None, api_key: str | None = None) -> None:
        self.transport = transport or UrllibJSONTransport()
        self.api_key = api_key if api_key is not None else (
            env_value("SOCIAL_YOUTUBE_API_KEY") or env_value("YOUTUBE_API_KEY")
        )

    def coverage_status(self) -> CoverageStatus:
        if self.api_key:
            return CoverageStatus(mode="api", configured=True)
        return CoverageStatus(
            mode="browser_fallback",
            configured=False,
            limited=True,
            reason="YOUTUBE_API_KEY is not configured; only authorized browser review is available",
        )

    def collect(self, request: CollectRequest) -> CollectResult:
        coverage = self.coverage_status()
        if not self.api_key:
            return CollectResult((), request.cursor, coverage)

        query = "|".join(item.strip() for item in request.keywords if item.strip())
        if not query and not request.sources:
            return CollectResult(
                (),
                request.cursor,
                CoverageStatus("api", True, True, "no YouTube keywords or channel sources are configured"),
            )

        cursors = decode_cursor_map(request.cursor)
        next_cursors = dict(cursors)
        posts: list[SocialPost] = []
        coverage_issues: list[str] = []
        if query:
            payload = self.transport.get_json(
                f"{self.api_root}/search",
                params={
                    "key": self.api_key,
                    "part": "snippet",
                    "type": "video",
                    "order": "date",
                    "maxResults": min(max(request.limit, 1), 50),
                    "q": query,
                    "publishedAfter": cursors.get("__global__") or request.since,
                },
            )
            ensure_api_success(payload, "YouTube")
            search_posts = parse_youtube_payload(payload)
            posts.extend(search_posts)
            published = [post.published_at for post in search_posts if post.published_at]
            if published:
                next_cursors["__global__"] = max(published)

        for source in request.sources:
            reference = youtube_channel_reference(source)
            if reference is None:
                coverage_issues.append(f"unsupported YouTube channel source: {source}")
                continue
            channel_payload = self.transport.get_json(
                f"{self.api_root}/channels",
                params={"key": self.api_key, "part": "contentDetails", reference[0]: reference[1]},
            )
            ensure_api_success(channel_payload, "YouTube")
            uploads_playlist = _uploads_playlist_id(channel_payload)
            if not uploads_playlist:
                coverage_issues.append(f"YouTube channel source was not found: {source}")
                continue
            playlist_payload = self.transport.get_json(
                f"{self.api_root}/playlistItems",
                params={
                    "key": self.api_key,
                    "part": "snippet,contentDetails",
                    "playlistId": uploads_playlist,
                    "maxResults": min(max(request.limit, 1), 50),
                },
            )
            ensure_api_success(playlist_payload, "YouTube")
            source_posts = parse_youtube_playlist_payload(playlist_payload)
            after = normalize_timestamp(cursors.get(source) or request.since)
            if after:
                source_posts = [post for post in source_posts if post.published_at > after]
            posts.extend(source_posts)
            published = [post.published_at for post in source_posts if post.published_at]
            if published:
                next_cursors[source] = max(published)

        result_coverage = coverage
        if coverage_issues:
            result_coverage = CoverageStatus("api", True, True, "; ".join(coverage_issues))
        return CollectResult(dedupe_posts(posts), encode_cursor_map(next_cursors), result_coverage)


def _uploads_playlist_id(payload: Mapping[str, Any]) -> str:
    for item in payload.get("items", []) or []:
        if not isinstance(item, Mapping):
            continue
        details = item.get("contentDetails") if isinstance(item.get("contentDetails"), Mapping) else {}
        related = details.get("relatedPlaylists") if isinstance(details.get("relatedPlaylists"), Mapping) else {}
        if related.get("uploads"):
            return str(related["uploads"])
    return ""


def parse_youtube_playlist_payload(
    payload: Mapping[str, Any], *, collected_at: str | None = None
) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in payload.get("items", []) or []:
        if not isinstance(item, Mapping):
            continue
        snippet = item.get("snippet") if isinstance(item.get("snippet"), Mapping) else {}
        details = item.get("contentDetails") if isinstance(item.get("contentDetails"), Mapping) else {}
        resource = snippet.get("resourceId") if isinstance(snippet.get("resourceId"), Mapping) else {}
        video_id = str(details.get("videoId") or resource.get("videoId") or "")
        if not video_id:
            continue
        thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), Mapping) else {}
        thumbnail_urls = []
        for key in ("maxres", "standard", "high", "medium", "default"):
            thumbnail = thumbnails.get(key) if isinstance(thumbnails.get(key), Mapping) else {}
            if thumbnail.get("url"):
                thumbnail_urls.append(str(thumbnail["url"]))
                break
        posts.append(
            SocialPost(
                platform="youtube",
                platform_post_id=video_id,
                source_url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(snippet.get("title") or ""),
                original_text=str(snippet.get("description") or ""),
                published_at=normalize_timestamp(details.get("videoPublishedAt") or snippet.get("publishedAt")),
                author=str(snippet.get("channelTitle") or snippet.get("channelId") or ""),
                collected_at=collected,
                media_urls=tuple(thumbnail_urls),
                metadata={"channel_id": str(snippet.get("channelId") or "")},
            )
        )
    return posts


def parse_youtube_payload(payload: Mapping[str, Any], *, collected_at: str | None = None) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in payload.get("items", []) or []:
        if not isinstance(item, Mapping):
            continue
        identifier = item.get("id") if isinstance(item.get("id"), Mapping) else {}
        video_id = str(identifier.get("videoId") or "")
        if not video_id:
            continue
        snippet = item.get("snippet") if isinstance(item.get("snippet"), Mapping) else {}
        thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), Mapping) else {}
        thumbnail_urls = []
        for key in ("maxres", "standard", "high", "medium", "default"):
            thumbnail = thumbnails.get(key) if isinstance(thumbnails.get(key), Mapping) else {}
            if thumbnail.get("url"):
                thumbnail_urls.append(str(thumbnail["url"]))
                break
        posts.append(
            SocialPost(
                platform="youtube",
                platform_post_id=video_id,
                source_url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(snippet.get("title") or ""),
                original_text=str(snippet.get("description") or ""),
                published_at=normalize_timestamp(snippet.get("publishedAt")),
                author=str(snippet.get("channelTitle") or snippet.get("channelId") or ""),
                collected_at=collected,
                media_urls=tuple(thumbnail_urls),
                metadata={"channel_id": str(snippet.get("channelId") or "")},
            )
        )
    return posts
