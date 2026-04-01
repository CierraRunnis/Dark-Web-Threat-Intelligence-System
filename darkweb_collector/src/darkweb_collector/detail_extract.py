from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re


TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
LINK_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)


def _clean_text(value: str) -> str:
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_generic_detail(url: str, html: str) -> dict:
    title_match = TITLE_RE.search(html)
    page_title = _clean_text(title_match.group(1)) if title_match else ""
    links = [link for link in LINK_RE.findall(html) if link and not link.startswith("#")]
    text = _clean_text(html)
    return {
        "source_url": url,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "ok",
        "page_title": page_title,
        "text_excerpt": text[:1000],
        "outbound_link_count": len(links),
        "outbound_links_sample": links[:20],
    }
