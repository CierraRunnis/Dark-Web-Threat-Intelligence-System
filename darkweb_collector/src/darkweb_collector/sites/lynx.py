"""Lynx site parser for darkweb_collector."""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urljoin

from darkweb_collector.normalize import content_hash


TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
LIST_BLOCK_RE = re.compile(
    r'<div class="news__block chat__block">(?P<block>.*?)'
    r'<a[^>]*href="(?P<href>[^"]+)"[^>]*>\s*Go to the publication\s*</a>\s*</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
DOMAIN_RE = re.compile(r"(?:https?://)?(?:www\.)?([A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.IGNORECASE)


def _clean_html_text(value: str) -> str:
    """Clean HTML text by removing tags and normalizing whitespace."""
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_list_item_from_context(context_before: str, views: str, html_after: str, base_url: str) -> dict | None:
    """Extract data from HTML context around a Views field."""
    # Combine context for parsing
    block = context_before + f"Views: <span>{views}</span>" + html_after
    
    # Extract title from chat__block-title (h4 tag)
    title = ""
    title_match = re.search(r'<h4[^>]*class="chat__block-title"[^>]*>([^<]+)</h4>', context_before, re.IGNORECASE)
    if title_match:
        title = _clean_html_text(title_match.group(1))
    
    if not title:
        # Fallback to description if title not found
        title_match = re.search(r'chat__block-descr>([^<]{10,200})', context_before, re.IGNORECASE)
        if title_match:
            title = _clean_html_text(title_match.group(1))
    
    if not title:
        return None

    # Extract publication date
    published_at = ""
    date_match = re.search(r'publication:\s*<span>([^<]+)</span>', context_before, re.IGNORECASE)
    if date_match:
        published_at = _clean_html_text(date_match.group(1))

    # Extract category
    category = ""
    category_match = re.search(r'Category:\s*<span>([^<]+)</span>', context_before, re.IGNORECASE)
    if category_match:
        category = _clean_html_text(category_match.group(1))

    # Extract views (already have it)
    views_int = int(views) if views.isdigit() else 0

    # Extract detail URL from the link after Views
    detail_url = ""
    link_match = re.search(r'href=(http://[^>]+)>\s*Go to the publication', html_after, re.IGNORECASE)
    if link_match:
        detail_url = link_match.group(1).strip().rstrip('"').rstrip("'")
    else:
        # Try alternative pattern
        link_match = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*Go to the publication', block, re.IGNORECASE)
        if link_match:
            detail_url = urljoin(base_url, link_match.group(1))

    if not detail_url:
        return None

    # Author and replies are not visible in the list view for Lynx
    author = ""
    replies = 0
    potential_victim = ""  # Could be extracted from title in some cases

    return {
        "title": title,
        "author": author,
        "published_at": published_at,
        "replies": replies,
        "views": views_int,
        "potential_victim": potential_victim,
        "detail_url": detail_url,
        "content_hash": content_hash(title, published_at, category),
    }


def _extract_domain_candidate(*values: str) -> str:
    for value in values:
        match = DOMAIN_RE.search(value or "")
        if match:
            return match.group(1).lower()
    return ""


def _extract_list_item_from_block(block_html: str, href: str, base_url: str) -> dict | None:
    title_match = re.search(r'<h4[^>]*class="chat__block-title"[^>]*>(.*?)</h4>', block_html, re.IGNORECASE | re.DOTALL)
    title = _clean_html_text(title_match.group(1)) if title_match else ""
    if not title:
        return None

    published_at = ""
    date_match = re.search(r"Date of publication:\s*<span>(.*?)</span>", block_html, re.IGNORECASE | re.DOTALL)
    if date_match:
        published_at = _clean_html_text(date_match.group(1))

    category = ""
    category_match = re.search(r"Category:\s*<span>(.*?)</span>", block_html, re.IGNORECASE | re.DOTALL)
    if category_match:
        category = _clean_html_text(category_match.group(1))

    views_int = 0
    views_match = re.search(r"Views:\s*<span>(\d+)</span>", block_html, re.IGNORECASE)
    if views_match:
        views_int = int(views_match.group(1))

    description = ""
    description_match = re.search(r'<p[^>]*class="chat__block-descr"[^>]*>(.*?)</p>', block_html, re.IGNORECASE | re.DOTALL)
    if description_match:
        description = _clean_html_text(description_match.group(1))

    detail_url = urljoin(base_url, href)
    if not detail_url:
        return None

    return {
        "title": title,
        "author": "",
        "published_at": published_at,
        "replies": 0,
        "views": views_int,
        "potential_victim": _extract_domain_candidate(title, description),
        "detail_url": detail_url,
        "content_hash": content_hash(title, published_at, category),
    }


def parse_lynx_list_page(url: str, html: str) -> dict:
    """Parse Lynx list page HTML and extract topic information."""
    title_match = TITLE_RE.search(html)
    page_title = _clean_html_text(title_match.group(1)) if title_match else ""

    topics = []

    for match in LIST_BLOCK_RE.finditer(html):
        item = _extract_list_item_from_block(match.group("block"), match.group("href"), url)
        if item:
            topics.append(item)

    if not topics:
        # Fallback for older or abnormal pages that do not expose full chat block markup.
        views_matches = list(re.finditer(r'Views:\s*<span>(\d+)</span>', html, re.IGNORECASE))

        for i, match in enumerate(views_matches):
            views_value = match.group(1)
            views_pos = match.start()

            context_start = max(0, views_pos - 1000)
            if i > 0:
                context_start = max(context_start, views_matches[i-1].end())
            context_before = html[context_start:views_pos]

            context_end = min(len(html), views_pos + 500)
            if i < len(views_matches) - 1:
                context_end = min(context_end, views_matches[i+1].start())
            html_after = html[match.end():context_end]

            item = _extract_list_item_from_context(context_before, views_value, html_after, url)
            if item:
                topics.append(item)

    # Transform topics to victims format for database compatibility
    victims = []
    for topic in topics:
        title = topic["title"]
        # Create display_label from title (first 50 chars)
        display_label = title[:50] if len(title) <= 50 else title[:47] + "..."
        
        victims.append({
            "site_name": "lynx",
            "source_url": topic["detail_url"],
            "detail_url": topic["detail_url"],
            "name": title,
            "display_label": display_label,
            "domain": topic.get("potential_victim") or "",
            "status": "active",
            "published_at_utc": topic.get("published_at", ""),
            "views": topic.get("views", 0),
            "content_hash": topic.get("content_hash", ""),
            "last_detail_fetch_status": None,
        })

    return {
        "site_name": "lynx",
        "source_url": url,
        "title": page_title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "victim_count": len(victims),
        "victims": victims,
    }


def parse_lynx_detail_page(url: str, html: str) -> dict:
    """Parse Lynx detail page HTML and extract content information."""
    title_match = TITLE_RE.search(html)
    page_title = _clean_html_text(title_match.group(1)) if title_match else ""

    content = ""
    company_name = ""

    title_in_panel_match = re.search(
        r'<div class="chat__window-header-wrap"[^>]*>.*?<div class="chat__block-title"[^>]*>(.*?)</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if title_in_panel_match:
        company_name = _clean_html_text(title_in_panel_match.group(1))

    detail_block_match = re.search(
        r'<div class="detailed">(.*?)</div>\s*</div>\s*</div>\s*</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    detail_block = detail_block_match.group(1) if detail_block_match else html

    content_match = re.search(
        r'<div class="detailed">.*?<span>\s*Description of the publication\s*</span>\s*<p>(.*?)</p>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not content_match:
        content_match = re.search(
            r'<p>(.*?)</p>\s*<div class="row">',
            detail_block,
            re.IGNORECASE | re.DOTALL,
        )
    if not content_match:
        content_match = re.search(r'chat__block-descr>([^<]+)', html, re.IGNORECASE)
    if content_match:
        content = _clean_html_text(content_match.group(1))
    if not content:
        text_matches = re.findall(r'>([^<]{50,800})<', detail_block)
        for text in text_matches:
            cleaned = _clean_html_text(text)
            if len(cleaned) > 50 and not any(x in cleaned.lower() for x in ['function', 'var ', 'const ', 'display:', 'margin:', 'padding:']):
                content = cleaned
                break

    # Extract publication date
    timestamp = ""
    date_match = re.search(r'Date of publication\s*</span>\s*<p>([^<]+)</p>', detail_block, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r'publication:\s*<span>([^<]+)</span>', html, re.IGNORECASE)
    if date_match:
        timestamp = _clean_html_text(date_match.group(1))

    # Extract category
    category = ""
    category_match = re.search(r'Category:\s*<span>([^<]+)</span>', html, re.IGNORECASE)
    if category_match:
        category = _clean_html_text(category_match.group(1))

    views = 0
    views_match = re.search(r'Views:\s*<span>(\d+)</span>', detail_block, re.IGNORECASE)
    if not views_match:
        views_match = re.search(r'Views:\s*<span>(\d+)</span>', html, re.IGNORECASE)
    if views_match:
        views = int(views_match.group(1))

    # Author is not explicitly shown in Lynx
    author = ""

    # Victims and attackers - try to extract from content
    victims = []
    attackers = []
    
    # Look for company/organization names in content
    if company_name:
        victims.append(company_name)
    elif content:
        # First sentence often contains the company name
        first_sentence = content.split('.')[0] if '.' in content else content
        if len(first_sentence) > 10:
            # Use first 50 chars as potential victim name
            potential = first_sentence[:50].strip()
            if potential:
                victims.append(potential)

    # Attachments - look for download links
    attachments = []
    attachment_patterns = [
        r'href="([^"]+\.(?:zip|rar|7z|tar|gz))"',
        r'href="([^"]+)"[^>]*download',
    ]
    for pattern in attachment_patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            href = match.group(1)
            if href:
                attachments.append({
                    "url": urljoin(url, href),
                    "name": href.split('/')[-1] or "attachment",
                })

    link_matches = re.findall(r'href="([^"]+)"', html, re.IGNORECASE)
    outbound_links_sample = [
        urljoin(url, href)
        for href in link_matches
        if href and not href.startswith("#")
    ][:20]

    # Calculate content hash
    content_hash_value = content_hash(content, timestamp, category)

    fetched_at_utc = datetime.now(timezone.utc).isoformat()

    return {
        "site_name": "lynx",
        "source_url": url,
        "fetched_at_utc": fetched_at_utc,
        "fetch_status": "ok",
        "page_title": page_title,
        "text_excerpt": content[:1000] if content else "",
        "outbound_link_count": len(outbound_links_sample),
        "outbound_links_sample": outbound_links_sample,
        "content": content,
        "company_name": company_name,
        "author": author,
        "timestamp": timestamp,
        "victims": victims,
        "attackers": attackers,
        "attachments": attachments,
        "content_hash": content_hash_value,
        "parsed_at_utc": fetched_at_utc,
    }
