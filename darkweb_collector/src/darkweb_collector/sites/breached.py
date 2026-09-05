from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin, urlparse

from darkweb_collector.normalize import content_hash
from darkweb_collector.sites.darkforums import (
    determine_industry,
    determine_region,
    extract_attackers_from_content,
    extract_victims_from_content,
)


FORUM_SECTIONS = {
    "databases": "http://breach5yz2b5lepmq4gaqwcon3jippw3bislhvvdavem5git55sy2nid.onion/forums/databases.14/?order=post_date&direction=desc",
    "cracked": "http://breach5yz2b5lepmq4gaqwcon3jippw3bislhvvdavem5git55sy2nid.onion/forums/cracked-accounts.16/?order=post_date&direction=desc",
    "leaks": "http://breach5yz2b5lepmq4gaqwcon3jippw3bislhvvdavem5git55sy2nid.onion/forums/leaks-market.18/?order=post_date&direction=desc",
}


# --- list page (XenForo structItem) ---------------------------------------

STRUCT_ITEM_RE = re.compile(
    r'<div[^>]*class="[^"]*structItem\s+structItem--thread[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*structItem\s+structItem--thread|<div\s+class="block-outer block-outer--after">|</div>\s*</div>\s*</div>\s*<div\s+class="block-outer)',
    re.IGNORECASE | re.DOTALL,
)
THREAD_ID_RE = re.compile(
    r'js-threadListItem-(\d+)',
    re.IGNORECASE,
)
TITLE_LINK_RE = re.compile(
    r'<div[^>]*class="[^"]*structItem-title[^"]*"[^>]*>(?P<inner>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
THREAD_HREF_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]*/threads/[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
AUTHOR_ATTR_RE = re.compile(r'data-author="([^"]+)"', re.IGNORECASE)
USERNAME_RE = re.compile(
    r'<a[^>]*class="[^"]*username[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
META_PAIR_RE = re.compile(
    r'<dl[^>]*class="[^"]*pairs[^"]*"[^>]*>\s*<dt[^>]*>(?P<label>.*?)</dt>\s*<dd[^>]*>(?P<value>.*?)</dd>',
    re.IGNORECASE | re.DOTALL,
)
TIME_TAG_RE = re.compile(
    r'<time[^>]*datetime="(?P<dt>[^"]+)"[^>]*>(?P<text>.*?)</time>',
    re.IGNORECASE | re.DOTALL,
)


# --- detail page (XenForo article.message) --------------------------------

POST_BLOCK_RE = re.compile(
    r'<article[^>]*class="[^"]*message\s+message--post[^"]*"[^>]*data-content="post-\d+"[^>]*>.*?</article>',
    re.IGNORECASE | re.DOTALL,
)
BBWRAPPER_RE = re.compile(
    r'<div[^>]*class="[^"]*bbWrapper[^"]*"[^>]*>(?P<body>.*?)</div>\s*(?:<div[^>]*class="[^"]*message-signature|<aside|<footer|</article>)',
    re.IGNORECASE | re.DOTALL,
)
QUOTE_BLOCK_RE = re.compile(
    r'<blockquote[^>]*class="[^"]*bbCodeBlock[^"]*"[^>]*>.*?</blockquote>',
    re.IGNORECASE | re.DOTALL,
)
ATTACHMENT_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*class="[^"]*(?:file-preview|bbCodeBlock-shareLink|js-attachmentLink)[^"]*"',
    re.IGNORECASE,
)
EXTERNAL_LINK_RE = re.compile(
    r'<a[^>]+class="[^"]*link\s+link--external[^"]*"[^>]+href="(?P<href>[^"]+)"',
    re.IGNORECASE,
)


# --- text helpers ---------------------------------------------------------

def _clean_html_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_domain(url: str) -> str:
    return urlparse(url).netloc


def _parse_reference_dt(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    return datetime.now(timezone.utc)


def normalize_breached_timestamp(value: str | None, *, collected_at_utc: str | None = None) -> str:
    """Return ISO date for a XenForo time string. Accepts ISO datetime, relative phrases, etc."""
    raw = (value or "").strip()
    if not raw:
        return ""

    # XenForo emits ISO-8601 in <time datetime="..."> attributes, so try that first.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    except ValueError:
        pass

    reference_dt = _parse_reference_dt(collected_at_utc)
    lowered = raw.lower()
    if "yesterday" in lowered:
        return (reference_dt - timedelta(days=1)).date().isoformat()
    if "today" in lowered:
        return reference_dt.date().isoformat()

    rel = re.search(
        r"(?P<n>\d+)\s+(?P<u>minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago",
        lowered,
    )
    if rel:
        n = int(rel.group("n"))
        unit = rel.group("u")
        if unit.startswith("minute"):
            delta = timedelta(minutes=n)
        elif unit.startswith("hour"):
            delta = timedelta(hours=n)
        elif unit.startswith("day"):
            delta = timedelta(days=n)
        elif unit.startswith("week"):
            delta = timedelta(weeks=n)
        elif unit.startswith("month"):
            delta = timedelta(days=30 * n)
        else:
            delta = timedelta(days=365 * n)
        return (reference_dt - delta).date().isoformat()

    return ""


def _extract_victim_from_title(title: str) -> str:
    patterns = [
        r"([^|\-]+)\s*Database",
        r"([^|\-]+)\s*Leak",
        r"([^|\-]+)\s*Breached?",
        r"([^|\-]+)\s*Dump",
        r"([^|\-]+)\s*Data",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            victim = match.group(1).strip(" -|\t")
            victim = re.sub(r"^(?:The|A|An)\s+", "", victim, flags=re.IGNORECASE)
            return victim
    return ""


def _section_name_from_url(url: str) -> str:
    """`/forums/databases.14/?...` -> `databases`."""
    path = urlparse(url).path.strip("/")
    if path.startswith("forums/"):
        last = path.split("/")[1]
        slug = last.split(".")[0]
        return slug.replace("-", "_").lower() or "section"
    return path.replace("/", "_") or "section"


# --- public parsers -------------------------------------------------------

def parse_breached_list(url: str, html: str, max_topics: int = 5) -> dict:
    start_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] [breached] parsing list: {url}")

    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    title = _clean_html_text(title_match.group(1)) if title_match else ""
    domain = _extract_domain(url)
    section = _section_name_from_url(url)

    topics: list[dict] = []
    seen_urls: set[str] = set()

    # XenForo wraps every thread row in <div class="structItem structItem--thread ...">.
    # We split on that boundary and then mine each chunk for the title link, author,
    # reply/view counts and the latest post timestamp.
    chunks = re.split(
        r'(?=<div[^>]*class="[^"]*structItem\s+structItem--thread[^"]*")',
        html,
        flags=re.IGNORECASE,
    )

    for chunk in chunks:
        if "structItem--thread" not in chunk:
            continue

        title_block = TITLE_LINK_RE.search(chunk)
        if not title_block:
            continue
        thread_link = THREAD_HREF_RE.search(title_block.group("inner"))
        if not thread_link:
            continue

        href = thread_link.group("href").strip()
        clean_title = _clean_html_text(thread_link.group("title"))
        if not clean_title:
            continue

        full_url = urljoin(url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        tid_match = THREAD_ID_RE.search(chunk)
        tid = tid_match.group(1) if tid_match else re.search(r"\.(\d+)/?$", href.rstrip("/") + "/").group(1) if re.search(r"\.(\d+)/?$", href.rstrip("/") + "/") else ""

        author_match = AUTHOR_ATTR_RE.search(chunk)
        if author_match:
            author = _clean_html_text(author_match.group(1))
        else:
            user_match = USERNAME_RE.search(chunk)
            author = _clean_html_text(user_match.group(1)) if user_match else ""

        replies = ""
        views = ""
        for pair in META_PAIR_RE.finditer(chunk):
            label = _clean_html_text(pair.group("label")).lower()
            value = _clean_html_text(pair.group("value"))
            if label.startswith("repl"):
                replies = value
            elif label.startswith("view"):
                views = value

        # The first <time> in the row = thread start; the last = latest reply.
        time_tags = TIME_TAG_RE.findall(chunk)
        published_at = time_tags[0][0] if time_tags else ""
        last_reply_at = time_tags[-1][0] if time_tags else published_at

        victim = _extract_victim_from_title(clean_title)

        topic = {
            "tid": tid,
            "title": clean_title,
            "relative_url": href,
            "full_url": full_url,
            "section": section,
            "author": author,
            "replies": replies,
            "views": views,
            "published_at": published_at,
            "last_reply_at": last_reply_at,
            "content_hash": content_hash(clean_title, tid, last_reply_at),
            "potential_victim": victim,
        }
        topics.append(topic)
        print(
            f"[{time.strftime('%H:%M:%S')}] [breached] topic {len(topics)}: "
            f"{clean_title[:70]}"
        )

        if len(topics) >= max_topics:
            break

    elapsed = time.time() - start_time
    print(
        f"[{time.strftime('%H:%M:%S')}] [breached] list parse done in "
        f"{elapsed:.2f}s, {len(topics)} topics"
    )

    return {
        "site_name": "breached",
        "source_url": url,
        "domain": domain,
        "section": section,
        "title": title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "topic_count": len(topics),
        "topics": topics,
    }


def parse_breached_detail(url: str, html: str) -> dict:
    start_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] [breached] parsing detail: {url}")

    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    title = _clean_html_text(title_match.group(1)) if title_match else ""
    # XenForo prepends the forum name; strip the trailing site label if present.
    title = re.sub(r"\s*\|\s*[^|]+$", "", title).strip()
    domain = _extract_domain(url)

    post_block_match = POST_BLOCK_RE.search(html)
    post_block = post_block_match.group(0) if post_block_match else html

    body_match = BBWRAPPER_RE.search(post_block)
    if body_match:
        raw_body = body_match.group("body")
    else:
        # Fallback: any bbWrapper, then any message-body article tag.
        body_match = re.search(
            r'<div[^>]*class="[^"]*bbWrapper[^"]*"[^>]*>(.*?)</div>',
            post_block, re.IGNORECASE | re.DOTALL,
        )
        raw_body = body_match.group(1) if body_match else ""

    # Strip quoted replies before extracting plain text — they pollute victim/attacker NER.
    cleaned_body = QUOTE_BLOCK_RE.sub(" ", raw_body)
    content = _clean_html_text(cleaned_body)
    print(f"[{time.strftime('%H:%M:%S')}] [breached] content length: {len(content)} chars")

    author_attr = AUTHOR_ATTR_RE.search(post_block)
    if author_attr:
        author = _clean_html_text(author_attr.group(1))
    else:
        user_match = USERNAME_RE.search(post_block)
        author = _clean_html_text(user_match.group(1)) if user_match else "Unknown"
    print(f"[{time.strftime('%H:%M:%S')}] [breached] author: {author}")

    time_match = TIME_TAG_RE.search(post_block)
    timestamp = time_match.group("dt") if time_match else ""
    print(f"[{time.strftime('%H:%M:%S')}] [breached] timestamp: {timestamp}")

    # Attachments + outbound paste/mirror links.
    attachments: list[str] = []
    for match in ATTACHMENT_LINK_RE.finditer(post_block):
        attachments.append(urljoin(url, match.group("href")))
    for match in EXTERNAL_LINK_RE.finditer(post_block):
        attachments.append(match.group("href"))
    # de-dup, keep order
    seen = set()
    deduped: list[str] = []
    for href in attachments:
        if href not in seen:
            seen.add(href)
            deduped.append(href)
    attachments = deduped[:50]

    victims = extract_victims_from_content(content, title)
    attackers = extract_attackers_from_content(content)
    print(
        f"[{time.strftime('%H:%M:%S')}] [breached] victims={len(victims)} "
        f"attackers={len(attackers)} attachments={len(attachments)}"
    )

    victim_info = []
    for victim in victims:
        victim_info.append({
            "name": victim,
            "industry": determine_industry(victim, f"{title} {content}"),
            "region": determine_region(victim),
        })

    elapsed = time.time() - start_time
    print(f"[{time.strftime('%H:%M:%S')}] [breached] detail parse done in {elapsed:.2f}s")

    collected_at_utc = datetime.now(timezone.utc).isoformat()
    return {
        "site_name": "breached",
        "source_url": url,
        "domain": domain,
        "title": title,
        "collected_at_utc": collected_at_utc,
        "content": content,
        "author": author,
        "timestamp": timestamp,
        "published_at_utc": normalize_breached_timestamp(timestamp, collected_at_utc=collected_at_utc),
        "attachments": attachments,
        "victims": victim_info,
        "attackers": attackers,
        "content_hash": content_hash(content[:1000], author, timestamp),
    }


def get_breached_sections() -> dict:
    return FORUM_SECTIONS
