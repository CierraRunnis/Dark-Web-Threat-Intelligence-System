from __future__ import annotations

import re

from darkweb_collector.sites.pwnfrm import parse_pwnfrm_detail, parse_pwnfrm_list


FORUM_SECTIONS = {
    "databases": "https://raidforums.im/Forum-Databases",
    "other_leaks": "https://raidforums.im/Forum-Other-Leaks",
    "sellers_place": "https://raidforums.im/Forum-Sellers-Place",
}


def parse_raidforums_list(url: str, html: str, max_topics: int = 5) -> dict:
    normal_threads = re.search(
        r'<td[^>]*class="[^"]*tcat[^"]*"[^>]*>\s*Normal Threads\s*</td>',
        html,
        re.IGNORECASE,
    )
    listing_html = html
    if normal_threads:
        title = re.search(r"<title>.*?</title>", html, re.IGNORECASE | re.DOTALL)
        listing_html = f"{title.group(0) if title else ''}{html[normal_threads.end():]}"
    return parse_pwnfrm_list(url, listing_html, max_topics=max_topics, site_name="raidforums")


def parse_raidforums_detail(url: str, html: str) -> dict:
    return parse_pwnfrm_detail(url, html, site_name="raidforums")


def get_raidforums_sections() -> dict[str, str]:
    return dict(FORUM_SECTIONS)
