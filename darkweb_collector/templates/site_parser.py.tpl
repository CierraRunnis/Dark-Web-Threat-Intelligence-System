from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urljoin

from darkweb_collector.normalize import content_hash


TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
LIST_ENTRY_RE = re.compile(
    r'<!-- TODO: replace with the list-item regex for {{SITE_NAME}} -->',
    re.IGNORECASE | re.DOTALL,
)


def _clean_html_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_{{SITE_NAME}}_homepage(url: str, html: str) -> dict:
    title_match = TITLE_RE.search(html)
    title = _clean_html_text(title_match.group(1)) if title_match else ""

    victims = []
    for match in LIST_ENTRY_RE.finditer(html):
        # TODO: map regex groups into normalized fields
        relative_path = ""
        display_label = ""
        name = display_label
        published_at = ""
        claimed_size = ""
        detail_url = urljoin(url, relative_path)

        victims.append(
            {
                "site_name": "{{SITE_NAME}}",
                "source_url": url,
                "name": name,
                "display_label": display_label,
                "domain": None,
                "relative_path": relative_path,
                "detail_url": detail_url,
                "status": "unknown",
                "timer_class": "",
                "timer_status": "unknown",
                "published_at_utc": published_at,
                "claimed_size": claimed_size,
                "claimed_size_gb": None,
                "content_hash": content_hash(display_label, published_at, claimed_size, "unknown"),
            }
        )

    return {
        "site_name": "{{SITE_NAME}}",
        "source_url": url,
        "title": title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "victim_count": len(victims),
        "victims": victims,
    }
