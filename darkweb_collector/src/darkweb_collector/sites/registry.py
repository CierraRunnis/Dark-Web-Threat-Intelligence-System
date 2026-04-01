from __future__ import annotations

from collections.abc import Callable

from darkweb_collector.sites.example_forum import parse_example_forum_homepage
from darkweb_collector.sites.dragonforce import parse_dragonforce_homepage
from darkweb_collector.sites.darkforums import parse_darkforums_list, parse_darkforums_detail
from darkweb_collector.sites.chaos import parse_chaos_homepage, parse_chaos_detail


Parser = Callable[[str, str], dict]


PARSERS: dict[str, Parser] = {
    "dragonforce": parse_dragonforce_homepage,
    "example_forum": parse_example_forum_homepage,
    "darkforums_list": parse_darkforums_list,
    "darkforums_detail": parse_darkforums_detail,
    "chaos": parse_chaos_homepage,
    "chaos_detail": parse_chaos_detail,
}


def list_parsers() -> list[str]:
    return sorted(PARSERS)


def get_parser(site_name: str) -> Parser:
    try:
        return PARSERS[site_name]
    except KeyError as exc:
        known = ", ".join(list_parsers())
        raise ValueError(f"unknown site '{site_name}', available parsers: {known}") from exc
