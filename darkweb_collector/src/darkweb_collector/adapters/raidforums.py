from __future__ import annotations

from darkweb_collector.adapters.darkforums import DarkforumsAdapter
from darkweb_collector.sites.raidforums import parse_raidforums_detail, parse_raidforums_list


class RaidforumsAdapter(DarkforumsAdapter):
    site_name = "raidforums"
    list_parser = staticmethod(parse_raidforums_list)
    detail_parser = staticmethod(parse_raidforums_detail)
    detail_screenshot_selectors = ("#thread-info", "#posts", ".post")
