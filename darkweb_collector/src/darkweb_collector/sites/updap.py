from __future__ import annotations

import re
from html import unescape

from darkweb_collector.normalize import content_hash
from darkweb_collector.sites.pwnfrm import (
    normalize_pwnfrm_timestamp,
    parse_pwnfrm_detail,
    parse_pwnfrm_list,
)


UPDAP_BASE_URL = "https://updap.com"
FORUM_SECTIONS = {
    "databases": (
        f"{UPDAP_BASE_URL}/Forum-Databases"
        "?sortby=started&order=desc&datecut=9999&prefix=0"
    ),
    "other_leaks": (
        f"{UPDAP_BASE_URL}/Forum-Other-Leaks"
        "?sortby=started&order=desc&datecut=9999&prefix=0"
    ),
}

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*inline_row[^"]*"[^>]*>.*?</tr>',
    re.IGNORECASE | re.DOTALL,
)
_INTERSTITIAL_MARKERS = (
    "checking your browser",
    "cf-browser-verification",
    "just a moment",
    "access denied",
    "forbidden",
)


class UpdapParseError(ValueError):
    """Raised when an UpDap response is not a usable forum page."""


def _clean_html_text(value: str) -> str:
    value = _TAG_RE.sub(" ", value or "")
    return _SPACE_RE.sub(" ", unescape(value)).strip()


def _row_for_tid(html: str, tid: str) -> str:
    marker = f'id="tid_{tid}"'
    for match in _ROW_RE.finditer(html):
        row = match.group(0)
        if marker in row:
            return row
    return ""


def _match_text(pattern: str, html: str) -> str:
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    return _clean_html_text(match.group(1)) if match else ""


def _enhance_topic(topic: dict, row: str) -> None:
    if not row:
        return
    author = _match_text(
        r'<span[^>]*class="[^"]*author[^"]*"[^>]*>(.*?)</span>',
        row,
    ).rstrip(" ,")
    published_at = _match_text(
        r'<span[^>]*class="[^"]*thread_start_datetime[^"]*"[^>]*>(.*?)</span>',
        row,
    )
    replies_match = re.search(
        r'<a[^>]*href="[^"]*(?:action=whoposted|action=whoposted&amp;)[^"]*"[^>]*>(.*?)</a>',
        row,
        re.IGNORECASE | re.DOTALL,
    )
    replies = _clean_html_text(replies_match.group(1)) if replies_match else ""
    views = ""
    if replies_match:
        views = _match_text(
            r'</td>\s*<td[^>]*class="[^"]*forumdisplay_regular[^"]*"[^>]*>(.*?)</td>',
            row[replies_match.end() :],
        )
    last_reply_at = _match_text(
        r'<span[^>]*class="[^"]*lastpost[^"]*"[^>]*>(.*?)<br\s*/?>',
        row,
    )
    topic.update(
        {
            "author": author,
            "replies": replies,
            "views": views,
            "published_at": published_at,
            "last_reply_at": last_reply_at,
        }
    )


def _validate_forum_html(html: str) -> None:
    lowered = (html or "").lower()
    has_threads = 'id="tid_' in lowered
    if not html or (not has_threads and any(marker in lowered for marker in _INTERSTITIAL_MARKERS)):
        raise UpdapParseError("UpDap returned an access/interstitial page")
    if "forumdisplay" not in lowered or not has_threads:
        raise UpdapParseError("UpDap forum response has no thread-list markers")


def normalize_updap_timestamp(
    value: str | None,
    *,
    collected_at_utc: str | None = None,
) -> str:
    """Normalize UpDap's MyBB MM-DD-YYYY timestamps."""

    return normalize_pwnfrm_timestamp(value, collected_at_utc=collected_at_utc)


def parse_updap_list(url: str, html: str, max_topics: int = 5) -> dict:
    _validate_forum_html(html)
    payload = parse_pwnfrm_list(url, html, max_topics=max_topics)
    payload["site_name"] = "updap"
    for topic in payload["topics"]:
        _enhance_topic(topic, _row_for_tid(html, str(topic["tid"])))
    if not payload["topics"]:
        raise UpdapParseError("UpDap forum response yielded no topics")
    return payload


def parse_updap_detail(url: str, html: str) -> dict:
    lowered = (html or "").lower()
    has_posts = 'id="posts"' in lowered and "post_body" in lowered
    if not html or (not has_posts and any(marker in lowered for marker in _INTERSTITIAL_MARKERS)):
        raise UpdapParseError("UpDap returned an access/interstitial page")
    if not has_posts:
        raise UpdapParseError("UpDap detail response has no post markers")

    payload = parse_pwnfrm_detail(url, html)
    description = _match_text(
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']',
        html,
    )
    excerpt = description or str(payload.get("content") or "")[:2000]
    excerpt = _EMAIL_RE.sub("[redacted-email]", excerpt)
    payload.update(
        {
            "site_name": "updap",
            "content": excerpt,
            "content_hash": content_hash(excerpt[:1000], str(payload.get("author") or "")),
            "published_at_utc": normalize_updap_timestamp(
                payload.get("timestamp"),
                collected_at_utc=payload.get("collected_at_utc"),
            ),
            "content_restricted": "hidecontent" in lowered,
            "content_scope": "public_description_or_redacted_excerpt",
        }
    )
    return payload


def get_updap_sections() -> dict[str, str]:
    return FORUM_SECTIONS
