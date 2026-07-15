from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Mapping
from urllib.parse import quote_plus, urljoin

from .base import (
    CollectRequest,
    CollectResult,
    CoverageStatus,
    JSONTransport,
    SocialAdapterError,
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


FacebookBrowserFetcher = Callable[[CollectRequest], tuple[list[Mapping[str, Any]], str | None]]


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
        browser_fetcher: FacebookBrowserFetcher | None = None,
        browser_storage_state: str | None = None,
    ) -> None:
        self.transport = transport or UrllibJSONTransport()
        self.access_token = access_token if access_token is not None else (
            env_value("SOCIAL_FACEBOOK_ACCESS_TOKEN") or env_value("FACEBOOK_ACCESS_TOKEN")
        )
        self.api_version = api_version or env_value("SOCIAL_FACEBOOK_API_VERSION") or env_value("FACEBOOK_API_VERSION") or "v23.0"
        self.browser_fetcher = browser_fetcher
        self.browser_storage_state = browser_storage_state if browser_storage_state is not None else env_value(
            "SOCIAL_FACEBOOK_STORAGE_STATE"
        )

    def coverage_status(self) -> CoverageStatus:
        if self.access_token:
            return CoverageStatus(
                mode="api",
                configured=True,
                limited=True,
                reason="Meta API collection is limited to configured public pages allowed by the access token",
            )
        if self.browser_fetcher or (self.browser_storage_state and Path(self.browser_storage_state).is_file()):
            return CoverageStatus(
                mode="browser_fallback",
                configured=True,
                limited=True,
                reason="Authorized browser collection is limited to accessible public search results, pages, and groups",
            )
        return CoverageStatus(
            mode="browser_fallback",
            configured=False,
            limited=True,
            reason="FACEBOOK_ACCESS_TOKEN is not configured; only authorized browser review is available",
        )

    def collect(self, request: CollectRequest) -> CollectResult:
        coverage = self.coverage_status()
        if not self.access_token:
            if not coverage.configured:
                return CollectResult((), request.cursor, coverage)
            fetcher = self.browser_fetcher or self._playwright_fetch
            rows, next_cursor = fetcher(request)
            return CollectResult(dedupe_posts(parse_facebook_browser_rows(rows)), next_cursor or request.cursor, coverage)

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

    def _playwright_fetch(self, request: CollectRequest) -> tuple[list[Mapping[str, Any]], str | None]:
        storage_state = Path(self.browser_storage_state).expanduser().resolve()
        if not storage_state.is_file():
            raise SocialAdapterError("Facebook browser storage state was not found")
        urls = []
        for source in request.sources:
            clean = source.strip()
            if not clean:
                continue
            urls.append(clean if clean.startswith(("https://", "http://")) else f"https://www.facebook.com/{clean.lstrip('@/')}")
        keywords = " ".join(item.strip() for item in request.keywords if item.strip())
        if keywords:
            urls.append(f"https://www.facebook.com/search/posts?q={quote_plus(keywords)}")
        if not urls:
            return [], request.cursor
        rows: list[Mapping[str, Any]] = []
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    storage_state=str(storage_state),
                    viewport={"width": 1440, "height": 1000},
                )
                page = context.new_page()
                try:
                    for url in urls:
                        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                        page.wait_for_timeout(2_000)
                        body_text = page.locator("body").inner_text(timeout=10_000).casefold()
                        if any(marker in body_text for marker in ("this group is private", "private group", "content isn't available")):
                            continue
                        articles = page.locator('[role="article"]')
                        for index in range(min(articles.count(), max(request.limit, 1))):
                            article = articles.nth(index)
                            row = article.evaluate(
                                r"""node => {
                                  const message = node.querySelector('[data-ad-preview="message"], [data-ad-comet-preview="message"]');
                                  const links = [...node.querySelectorAll('a[href]')];
                                  const permalink = links.find(link => /\/posts\/|\/permalink\/|story_fbid=/.test(link.href));
                                  return { text: (message || node).innerText || '', source_url: permalink?.href || '' };
                                }"""
                            )
                            if isinstance(row, Mapping) and str(row.get("text") or "").strip():
                                rows.append({**row, "source_page": url})
                finally:
                    context.close()
                    browser.close()
        except SocialAdapterError:
            raise
        except Exception as exc:
            raise SocialAdapterError(f"Facebook authorized browser collection failed: {exc}") from exc
        return rows, utc_now_iso()


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


def parse_facebook_browser_rows(
    rows: list[Mapping[str, Any]], *, collected_at: str | None = None
) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in rows:
        text = str(item.get("text") or "").strip()
        source_url = urljoin(str(item.get("source_page") or "https://www.facebook.com/"), str(item.get("source_url") or ""))
        if not text or not source_url:
            continue
        match = re.search(r"(?:/posts/|/permalink/)([A-Za-z0-9._-]+)|[?&]story_fbid=([A-Za-z0-9._-]+)", source_url)
        post_id = next((value for value in (match.groups() if match else ()) if value), "")
        if not post_id:
            import hashlib

            post_id = hashlib.sha256(f"{source_url}\n{text}".encode("utf-8")).hexdigest()
        posts.append(
            SocialPost(
                platform="facebook",
                platform_post_id=post_id,
                source_url=source_url,
                original_text=text,
                published_at=normalize_timestamp(item.get("published_at"), default=collected),
                author=str(item.get("author") or ""),
                collected_at=collected,
                metadata={"collection_mode": "authorized_browser"},
            )
        )
    return posts
