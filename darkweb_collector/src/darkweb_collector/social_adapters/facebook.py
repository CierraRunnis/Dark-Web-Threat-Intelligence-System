from __future__ import annotations

import re
from typing import Any, Mapping

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


def _page_identifier(source: str) -> str:
    clean = source.strip().rstrip("/")
    if "facebook.com/groups/" in clean.lower():
        return ""
    if "facebook.com/" in clean.lower():
        clean = clean.split("facebook.com/", 1)[1].split("/", 1)[0]
    return clean if re.fullmatch(r"[A-Za-z0-9._-]+", clean or "") else ""


class FacebookAdapter:
    platform = "facebook"

    def __init__(
        self,
        transport: JSONTransport | None = None,
        access_token: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self.transport = transport or UrllibJSONTransport()
        self.access_token = access_token if access_token is not None else (
            env_value("SOCIAL_FACEBOOK_ACCESS_TOKEN") or env_value("FACEBOOK_ACCESS_TOKEN")
        )
        self.api_version = api_version or env_value("SOCIAL_FACEBOOK_API_VERSION") or env_value("FACEBOOK_API_VERSION") or "v23.0"

    def coverage_status(self) -> CoverageStatus:
        if self.access_token:
            return CoverageStatus(
                mode="api",
                configured=True,
                limited=True,
                reason="Meta API collection is limited to configured public pages allowed by the access token",
            )
        return CoverageStatus(
            mode="browser_fallback",
            configured=False,
            limited=True,
            reason="FACEBOOK_ACCESS_TOKEN is not configured; only authorized browser review is available",
        )

    def collect(self, request: CollectRequest) -> CollectResult:
        coverage = self.coverage_status()
        pages = tuple(
            (source, page_id)
            for source in request.sources
            for page_id in (_page_identifier(source),)
            if page_id
        )
        if not self.access_token or not pages:
            reason = coverage.reason if not self.access_token else "Facebook requires configured public page sources"
            return CollectResult((), request.cursor, CoverageStatus(coverage.mode, coverage.configured, True, reason))

        cursors = decode_cursor_map(request.cursor)
        next_cursors = dict(cursors)
        posts: list[SocialPost] = []
        for source_key, page_id in pages:
            payload = self.transport.get_json(
                f"https://graph.facebook.com/{self.api_version}/{page_id}/posts",
                params={
                    "access_token": self.access_token,
                    "fields": "id,message,created_time,permalink_url,from,attachments{media,type,url}",
                    "limit": min(max(request.limit, 1), 100),
                    "since": cursors.get(source_key) or request.since,
                },
            )
            ensure_api_success(payload, "Facebook")
            page_posts = parse_facebook_payload(payload)
            posts.extend(page_posts)
            published = [post.published_at for post in page_posts if post.published_at]
            if published:
                next_cursors[source_key] = max(published)
        return CollectResult(dedupe_posts(posts), encode_cursor_map(next_cursors), coverage)


def parse_facebook_payload(payload: Mapping[str, Any], *, collected_at: str | None = None) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in payload.get("data", []) or []:
        if not isinstance(item, Mapping) or not item.get("id"):
            continue
        author = item.get("from") if isinstance(item.get("from"), Mapping) else {}
        attachments = item.get("attachments") if isinstance(item.get("attachments"), Mapping) else {}
        media_urls = []
        for attachment in attachments.get("data", []) or []:
            if not isinstance(attachment, Mapping):
                continue
            media = attachment.get("media") if isinstance(attachment.get("media"), Mapping) else {}
            image = media.get("image") if isinstance(media.get("image"), Mapping) else {}
            url = str(image.get("src") or attachment.get("url") or "")
            if url:
                media_urls.append(url)
        post_id = str(item["id"])
        posts.append(
            SocialPost(
                platform="facebook",
                platform_post_id=post_id,
                source_url=str(item.get("permalink_url") or f"https://www.facebook.com/{post_id}"),
                original_text=str(item.get("message") or ""),
                published_at=normalize_timestamp(item.get("created_time")),
                author=str(author.get("name") or author.get("id") or ""),
                collected_at=collected,
                media_urls=tuple(media_urls),
                metadata={"author_id": str(author.get("id") or "")},
            )
        )
    return posts
