from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urljoin

from darkweb_collector.normalize import content_hash, normalize_status, size_to_gb


TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
ENTRY_RE = re.compile(
    r'<div class="text"><a class="text-pointer-animations\s+(link-[^"]+)"\s+href="([^"]+)">'
    r"(.*?)</a></div>\s*"
    r'<div class="timer\s+([^"]+)">(.*?)</div>\s*'
    r"<div class=number><b>(.*?)</b></div>",
    re.IGNORECASE | re.DOTALL,
)
DOMAIN_RE = re.compile(r"\(([^()]+)\)\s*$")
ABSOLUTE_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
DOMAIN_PATH_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/.*)?$")


def _clean_html_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_domain(label: str) -> str | None:
    match = DOMAIN_RE.search(label)
    if not match:
        return None
    return match.group(1).strip()


def _extract_name(label: str, domain: str | None) -> str:
    if not domain:
        return label
    suffix = f"({domain})"
    if label.endswith(suffix):
        return label[: -len(suffix)].strip() or domain
    return label


def _normalize_detail_url(base_url: str, href: str) -> str:
    href = (href or "").strip()
    if not href:
        return base_url
    if ABSOLUTE_URL_RE.match(href):
        return href
    if href.startswith("/"):
        return urljoin(base_url, href)
    if DOMAIN_PATH_RE.match(href):
        return f"https://{href}"
    return urljoin(base_url, href)


def parse_dragonforce_homepage(url: str, html: str) -> dict:
    title_match = TITLE_RE.search(html)
    title = _clean_html_text(title_match.group(1)) if title_match else ""

    victims = []
    for match in ENTRY_RE.finditer(html):
        link_class, href, label, timer_class, published_at, size = match.groups()
        clean_label = _clean_html_text(label)
        published_at = _clean_html_text(published_at)
        size = _clean_html_text(size)
        status = normalize_status(link_class)
        domain = _extract_domain(clean_label)
        name = _extract_name(clean_label, domain)
        detail_url = _normalize_detail_url(url, href)
        timer_status = normalize_status(timer_class)

        victims.append(
            {
                "site_name": "dragonforce",
                "source_url": url,
                "name": name,
                "display_label": clean_label,
                "domain": domain,
                "relative_path": href,
                "detail_url": detail_url,
                "status": status,
                "timer_class": timer_class,
                "timer_status": timer_status,
                "published_at_utc": published_at,
                "claimed_size": size,
                "claimed_size_gb": size_to_gb(size),
                "content_hash": content_hash(clean_label, published_at, size, status),
            }
        )

    return {
        "site_name": "dragonforce",
        "source_url": url,
        "title": title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "victim_count": len(victims),
        "victims": victims,
    }
