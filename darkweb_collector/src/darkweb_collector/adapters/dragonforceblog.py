"""DragonForceBlog site adapter for darkweb_collector."""
from __future__ import annotations

from darkweb_collector.adapters.base import SiteAdapter
from darkweb_collector.db import get_db_connection, get_victim_snapshot, record_victim_detail
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig
from darkweb_collector.pipeline import persist_run
from darkweb_collector.runtime import default_db_path
from darkweb_collector.sites.dragonforceblog import parse_dragonforceblog_detail_page, parse_dragonforceblog_list_page
from darkweb_collector.tor_fetch import fetch_page_artifacts, fetch_url
from darkweb_collector.utils import dump_json, dump_text, safe_stem


class DragonforceblogAdapter(SiteAdapter):
    """Adapter for DragonForceBlog darkweb site."""

    site_name = "dragonforceblog"

    def _fetch_html(self, url: str, config: SiteConfig, mode: str) -> str:
        """Fetch HTML content from URL using specified mode."""
        return fetch_url(
            url=url,
            mode=mode,
            timeout_seconds=config.fetch_timeout_seconds,
            render_wait_seconds=config.render_wait_seconds,
            retries=1,
        )

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        """Collect seed/list page and parse topics.

        For DragonForceBlog, the list page contains all victim information,
        so we treat each publication as a victim entry.

        Args:
            config: Site configuration
            run_ctx: Run context

        Returns:
            SeedResult containing parsed victims
        """
        if len(config.seed_urls) != 1:
            raise ValueError("dragonforceblog adapter expects exactly one seed URL")

        target_url = config.seed_urls[0]
        html = self._fetch_html(target_url, config, config.seed_fetch_mode)
        parsed = parse_dragonforceblog_list_page(target_url, html)

        # Limit victims per run
        if len(parsed["victims"]) > config.max_topics_per_run:
            parsed["victims"] = parsed["victims"][: config.max_topics_per_run]
            parsed["victim_count"] = len(parsed["victims"])

        return SeedResult(
            site_name=self.site_name,
            collected_at_utc=parsed["collected_at_utc"],
            payload=parsed,
            raw_html_by_url={target_url: html},
        )

    def plan_details(self, seed_result: SeedResult, config: SiteConfig) -> list[DetailTask]:
        """Plan detail page fetching based on seed result.

        For DragonForceBlog, we need to fetch detail pages to get attachment links.
        The detail page URL is constructed based on the victim's domain.

        Args:
            seed_result: Result from seed collection
            config: Site configuration

        Returns:
            List of detail tasks to execute
        """
        tasks: list[DetailTask] = []

        with get_db_connection() as connection:
            for victim in seed_result.payload["victims"]:
                # Check if this victim already exists with same content hash
                snapshot = get_victim_snapshot(
                    connection,
                    site_name=self.site_name,
                    source_url=victim["source_url"],
                    name=victim["name"],
                    domain=victim.get("domain"),
                    status=victim.get("status", "active"),
                )

                # Skip if already exists with same hash and successful fetch
                if (
                    snapshot
                    and snapshot.get("content_hash") == victim.get("content_hash")
                    and snapshot.get("last_detail_fetch_status") == "ok"
                ):
                    continue

                detail_url = victim.get("detail_url") or ""
                if not detail_url:
                    continue

                tasks.append(
                    DetailTask(
                        site_name=self.site_name,
                        target_url=detail_url,
                        metadata={
                            "source_url": victim["source_url"],
                            "name": victim["name"],
                            "status": victim.get("status", "active"),
                            "domain": victim.get("domain", ""),
                            "display_label": victim.get("display_label", victim["name"]),
                            "content_hash": victim.get("content_hash", ""),
                            "victim_data": victim,  # Pass the full victim data from list page
                            "artifact_stem": safe_stem(
                                f"{victim.get('content_hash', '')[:10]}_{victim['name'][:30]}"
                            ),
                        },
                    )
                )

                if len(tasks) >= config.max_detail_pages_per_run:
                    break

        return tasks

    def collect_detail(
        self, detail_task: DetailTask, config: SiteConfig, run_ctx: RunContext
    ) -> DetailResult | None:
        """Collect and parse a detail page.

        For DragonForceBlog, we fetch the detail page to get attachment links.

        Args:
            detail_task: Detail task to execute
            config: Site configuration
            run_ctx: Run context

        Returns:
            DetailResult or None if failed
        """
        try:
            html, screenshot_png = fetch_page_artifacts(
                url=detail_task.target_url,
                mode=config.detail_fetch_mode,
                timeout_seconds=config.fetch_timeout_seconds,
                render_wait_seconds=config.render_wait_seconds,
                screenshot_selector=".publication",
                hide_selectors=(
                    ".publications-list",
                    ".header-promo",
                    ".blog-layout__header",
                    ".header-menu",
                ),
            )

            # Parse the detail page
            detail = parse_dragonforceblog_detail_page(detail_task.target_url, html)

            # Merge with victim data from list page
            victim_data = detail_task.metadata.get("victim_data", {})
            detail["claimed_size"] = detail.get("claimed_size") or victim_data.get("claimed_size", "")
            detail["location"] = detail.get("location") or victim_data.get("location", "")
            detail["company_name"] = detail.get("company_name") or victim_data.get("name", "")

            return DetailResult(
                site_name=self.site_name,
                target_url=detail_task.target_url,
                payload=detail,
                raw_html=html,
                screenshot_png=screenshot_png,
                metadata=detail_task.metadata,
            )
        except Exception as e:
            # Log error but don't fail the entire run
            print(f"Error collecting detail for {detail_task.target_url}: {e}")
            return None

    def persist(
        self,
        config: SiteConfig,
        run_ctx: RunContext,
        seed_result: SeedResult | None = None,
        detail_results: list[DetailResult] | None = None,
    ) -> None:
        """Persist results to storage.

        Args:
            config: Site configuration
            run_ctx: Run context
            seed_result: Optional seed result to persist
            detail_results: Optional list of detail results to persist
        """
        # Persist seed result
        if seed_result is not None:
            output_dir = config.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save raw HTML
            for url, html in seed_result.raw_html_by_url.items():
                dump_text(output_dir / "latest.html", html)

            # Save parsed JSON
            dump_json(output_dir / "latest.json", seed_result.payload)

            # Persist to database
            persist_run(default_db_path(), seed_result.payload)

        # Persist detail results
        if detail_results:
            details_dir = config.output_dir / "details"
            details_dir.mkdir(parents=True, exist_ok=True)

            with get_db_connection() as connection:
                for detail_result in detail_results:
                    if detail_result is None:
                        continue

                    artifact_stem = (
                        detail_result.metadata.get("artifact_stem")
                        or safe_stem(detail_result.target_url)
                    )
                    detail_result.payload["artifact_stem"] = artifact_stem

                    # Save raw HTML
                    if detail_result.raw_html is not None:
                        dump_text(details_dir / f"{artifact_stem}.html", detail_result.raw_html)
                    if detail_result.screenshot_png is not None:
                        (details_dir / f"{artifact_stem}.png").write_bytes(detail_result.screenshot_png)

                    # Save parsed JSON
                    dump_json(details_dir / f"{artifact_stem}.json", detail_result.payload)

                    # Record in database
                    record_victim_detail(
                        connection,
                        site_name=self.site_name,
                        source_url=str(detail_result.metadata.get("source_url", "")),
                        name=str(detail_result.metadata.get("name", "")),
                        domain=detail_result.metadata.get("domain"),
                        status=str(detail_result.metadata.get("status", "active")),
                        detail_payload=detail_result.payload,
                    )

                connection.commit()
