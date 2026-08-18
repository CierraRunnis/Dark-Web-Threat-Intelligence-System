from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urljoin, urlparse

from darkweb_collector.normalize import content_hash


TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
CARD_SPLIT_MARKER = '<div class=publications-list__publication'

WEBSITE_RE = re.compile(r"<p class=list-publication__website[^>]*>(.*?)<div style=", re.IGNORECASE | re.DOTALL)
NAME_RE = re.compile(r"<h3 class=list-publication__name[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
DESCRIPTION_RE = re.compile(r"<p class=list-publication__description[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
WEBSITE_HREF_RE = re.compile(r"<a href=([^ >]+)[^>]*>www\.", re.IGNORECASE | re.DOTALL)
DATE_RE = re.compile(
    r"<span class=publication-footer__date[^>]*>.*?</span>\s*([^<].*?)</span><button",
    re.IGNORECASE | re.DOTALL,
)
PUBLICATION_TIMER_RE = re.compile(
    r"class=list-publication__timer-publication[^>]*>.*?<span[^>]*>(.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
PUBLICATED_TIMER_RE = re.compile(
    r"class=list-publication__timer-publicated[^>]*>.*?</span>\s*(.*?)(?:</div>|<span class=publication-footer__date)",
    re.IGNORECASE | re.DOTALL,
)
ADDITIONAL_ROWS_RE = re.compile(
    r"<p class=publication-addictional__row[^>]*>.*?(?:<a [^>]*>|<span class=addictional-row__text[^>]*>)(.*?)(?:</a>|</span>)",
    re.IGNORECASE | re.DOTALL,
)


def _clean_html_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_domain(url: str) -> str | None:
    parsed = urlparse(url)
    return parsed.netloc or None


def _search_text(pattern: re.Pattern[str], chunk: str) -> str:
    match = pattern.search(chunk)
    if not match:
        return ""
    return _clean_html_text(match.group(1))


def _search_raw(pattern: re.Pattern[str], chunk: str) -> str:
    match = pattern.search(chunk)
    if not match:
        return ""
    return match.group(1).strip()


def parse_example_forum_homepage(url: str, html: str) -> dict:
    title_match = TITLE_RE.search(html)
    title = _clean_html_text(title_match.group(1)) if title_match else ""

    victims = []
    chunks = html.split(CARD_SPLIT_MARKER)[1:]
    for chunk in chunks:
        website = _search_text(WEBSITE_RE, chunk)
        name = _search_text(NAME_RE, chunk) or website
        description = _search_text(DESCRIPTION_RE, chunk)
        detail_href = _search_raw(WEBSITE_HREF_RE, chunk)
        detail_url = urljoin(url, detail_href)
        domain = _extract_domain(detail_href) or website or None
        published_at = _search_text(DATE_RE, chunk)
        publication_timer = _search_text(PUBLICATION_TIMER_RE, chunk)
        publicated_files = _search_text(PUBLICATED_TIMER_RE, chunk)
        status = "published" if publicated_files else "going" if publication_timer else "unknown"
        row_values = [_clean_html_text(value) for value in ADDITIONAL_ROWS_RE.findall(chunk)]
        row_values = [value for value in row_values if value]
        location = row_values[1] if len(row_values) > 1 else ""
        claimed_size = row_values[2] if len(row_values) > 2 else ""
        open_label = "Open" if "<button" in chunk else ""

        victims.append(
            {
                "site_name": "example_forum",
                "source_url": url,
                "name": name,
                "display_label": name,
                "domain": domain,
                "relative_path": detail_href,
                "detail_url": detail_url,
                "status": status,
                "timer_class": "list-publication__timer-publicated" if publicated_files else "list-publication__timer-publication",
                "timer_status": status,
                "published_at_utc": published_at,
                "claimed_size": claimed_size,
                "claimed_size_gb": None,
                "location": location or None,
                "website": website or None,
                "description": description or None,
                "publication_timer": publication_timer or None,
                "publicated_files": publicated_files or None,
                "open_label": open_label or None,
                "content_hash": content_hash(name, website, published_at, claimed_size, description, status),
            }
        )

    return {
        "site_name": "example_forum",
        "source_url": url,
        "title": title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "victim_count": len(victims),
        "victims": victims,
    }
