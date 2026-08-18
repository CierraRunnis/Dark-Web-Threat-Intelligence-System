from __future__ import annotations

from darkweb_collector.adapters.base import SiteAdapter
from darkweb_collector.adapters.breached import BreachedAdapter
from darkweb_collector.adapters.chaos import ChaosAdapter
from darkweb_collector.adapters.cracked import CrackedAdapter
from darkweb_collector.adapters.darkforums import DarkforumsAdapter
from darkweb_collector.adapters.dragonforce import DragonforceAdapter
from darkweb_collector.adapters.dragonforceblog import DragonforceblogAdapter
from darkweb_collector.adapters.lynx import LynxAdapter
from darkweb_collector.adapters.pwnfrm import PwnfrmAdapter


ADAPTERS: dict[str, SiteAdapter] = {
    DragonforceAdapter.site_name: DragonforceAdapter(),
    DarkforumsAdapter.site_name: DarkforumsAdapter(),
    BreachedAdapter.site_name: BreachedAdapter(),
    CrackedAdapter.site_name: CrackedAdapter(),
    ChaosAdapter.site_name: ChaosAdapter(),
    LynxAdapter.site_name: LynxAdapter(),
    DragonforceblogAdapter.site_name: DragonforceblogAdapter(),
    PwnfrmAdapter.site_name: PwnfrmAdapter(),
}


def list_adapters() -> list[str]:
    return sorted(ADAPTERS)


def get_adapter(site_name: str) -> SiteAdapter:
    try:
        return ADAPTERS[site_name]
    except KeyError as exc:
        known = ", ".join(list_adapters())
        raise ValueError(f"unknown adapter '{site_name}', available adapters: {known}") from exc
