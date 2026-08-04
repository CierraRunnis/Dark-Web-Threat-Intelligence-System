from __future__ import annotations

from urllib.parse import urlparse

from darkweb_collector.adapters.dragonforceblog import DragonforceblogAdapter
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig


CONFIRMED_DRAGONFORCE_HOST = "z3wqggtxft7id3ibr7srivv5gjof5fwg76slewnzwwakjuf3nlhukdid.onion"


class DragonforceAdapter(DragonforceblogAdapter):
    """DragonForce adapter for the confirmed z3wqgg...onion leak site."""

    site_name = "dragonforce"

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        result = super().collect_seed(config, run_ctx)
        result.site_name = self.site_name
        result.payload["site_name"] = self.site_name
        for victim in result.payload.get("victims", []):
            victim["site_name"] = self.site_name
        if not result.payload.get("victims"):
            raise RuntimeError("dragonforce page loaded but no victim entries were parsed")
        return result

    def collect_detail(
        self,
        detail_task: DetailTask,
        config: SiteConfig,
        run_ctx: RunContext,
    ) -> DetailResult | None:
        if (urlparse(detail_task.target_url).hostname or "").lower() != CONFIRMED_DRAGONFORCE_HOST:
            raise ValueError("dragonforce detail URL must use the confirmed DragonForce leak site")
        result = super().collect_detail(detail_task, config, run_ctx)
        if result is not None:
            result.payload["site_name"] = self.site_name
        return result
