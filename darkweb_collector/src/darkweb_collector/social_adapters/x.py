from __future__ import annotations

from typing import Any, Mapping

from .base import (
    CollectRequest,
    CollectResult,
    CoverageStatus,
    JSONTransport,
    SocialPost,
    UrllibJSONTransport,
    dedupe_posts,
    decode_cursor_map,
    env_value,
    encode_cursor_map,
    ensure_api_success,
    normalize_timestamp,
    quote_search_term,
    utc_now_iso,
)


class XAdapter:
    platform = "x"
    endpoint = "https://api.x.com/2/tweets/search/recent"

    def __init__(self, transport: JSONTransport | None = None, bearer_token: str | None = None) -> None:
        self.transport = transport or UrllibJSONTransport()
        self.bearer_token = bearer_token if bearer_token is not None else (
            env_value("SOCIAL_X_BEARER_TOKEN") or env_value("X_BEARER_TOKEN")
        )

    def coverage_status(self) -> CoverageStatus:
        if self.bearer_token:
            return CoverageStatus(mode="api", configured=True)
        return CoverageStatus(
            mode="browser_fallback",
            configured=False,
            limited=True,
            reason="X_BEARER_TOKEN is not configured; only authorized browser review is available",
        )

    @staticmethod
    def _query(request: CollectRequest) -> str:
        terms = [quote_search_term(item) for item in request.keywords if quote_search_term(item)]
        sources = [f"from:{item.lstrip('@').strip()}" for item in request.sources if item.strip()]
        groups = []
        if terms:
            groups.append(f"({' OR '.join(terms)})")
        if sources:
            groups.append(f"({' OR '.join(sources)})")
        if not groups:
            return ""
        return f"({' OR '.join(groups)}) -is:retweet -is:reply"

    def collect(self, request: CollectRequest) -> CollectResult:
        coverage = self.coverage_status()
        query = self._query(request)
        if not self.bearer_token or not query:
            reason = coverage.reason or "no X keywords or sources are configured"
            return CollectResult((), request.cursor, CoverageStatus(coverage.mode, coverage.configured, True, reason))

        payload = self.transport.get_json(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            params={
                "query": query,
                "max_results": min(max(request.limit, 10), 100),
                "since_id": _since_id(request.cursor),
                "start_time": request.since,
                "expansions": "author_id,attachments.media_keys",
                "tweet.fields": "id,text,author_id,created_at,attachments",
                "user.fields": "id,username,name",
                "media.fields": "media_key,url,preview_image_url,type",
            },
        )
        ensure_api_success(payload, "X")
        posts = parse_x_payload(payload)
        newest_id = str((payload.get("meta") or {}).get("newest_id") or "")
        if not newest_id and posts:
            newest_id = max((post.platform_post_id for post in posts), key=lambda value: int(value))
        next_cursor = encode_cursor_map({"__global__": newest_id}) if newest_id else request.cursor
        return CollectResult(dedupe_posts(posts), next_cursor, coverage)


def parse_x_payload(payload: Mapping[str, Any], *, collected_at: str | None = None) -> list[SocialPost]:
    includes = payload.get("includes") if isinstance(payload.get("includes"), Mapping) else {}
    users = {
        str(item.get("id")): item
        for item in includes.get("users", []) or []
        if isinstance(item, Mapping) and item.get("id")
    }
    media = {
        str(item.get("media_key")): item
        for item in includes.get("media", []) or []
        if isinstance(item, Mapping) and item.get("media_key")
    }
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in payload.get("data", []) or []:
        if not isinstance(item, Mapping) or not item.get("id"):
            continue
        author_data = users.get(str(item.get("author_id")), {})
        username = str(author_data.get("username") or item.get("author_id") or "")
        media_urls = []
        attachments = item.get("attachments") if isinstance(item.get("attachments"), Mapping) else {}
        for media_key in attachments.get("media_keys", []) or []:
            media_item = media.get(str(media_key), {})
            url = str(media_item.get("url") or media_item.get("preview_image_url") or "")
            if url:
                media_urls.append(url)
        post_id = str(item["id"])
        posts.append(
            SocialPost(
                platform="x",
                platform_post_id=post_id,
                source_url=f"https://x.com/{username}/status/{post_id}" if username else f"https://x.com/i/status/{post_id}",
                original_text=str(item.get("text") or ""),
                published_at=normalize_timestamp(item.get("created_at")),
                author=username,
                collected_at=collected,
                media_urls=tuple(media_urls),
                metadata={"author_id": str(item.get("author_id") or "")},
            )
        )
    return posts


def _since_id(cursor: str | None) -> str | None:
    cursor_map = decode_cursor_map(cursor)
    if cursor_map.get("__global__"):
        return cursor_map["__global__"]
    for value in cursor_map.values():
        nested = decode_cursor_map(value)
        candidate = nested.get("__global__") or (value if value.isdigit() else "")
        if candidate:
            return candidate
    return None
