from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from darkweb_collector.adapters.base import SiteAdapter
from darkweb_collector.db import (
    get_db_connection,
    get_forum_detail_snapshot,
    get_forum_topic_snapshot,
    upsert_forum_detail,
    upsert_forum_topic,
)
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig
from darkweb_collector.sites.darkforums import parse_darkforums_detail, parse_darkforums_list
from darkweb_collector.tor_fetch import fetch_page_artifacts, fetch_url
from darkweb_collector.utils import dump_json, dump_text, safe_stem, utc_now_iso


def _section_name(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if path.startswith("Forum-"):
        return path[6:].replace("-", "_").lower()
    return safe_stem(path or "section")


def _detail_artifact_stem(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _detail_artifacts_exist(output_dir, section_name: str, topic_url: str) -> bool:
    artifact_stem = _detail_artifact_stem(topic_url)
    details_dir = output_dir / section_name / "details"
    required = [
        details_dir / f"{artifact_stem}.html",
        details_dir / f"{artifact_stem}.json",
        details_dir / f"{artifact_stem}.png",
    ]
    return all(path.exists() for path in required)


class DarkforumsAdapter(SiteAdapter):
    site_name = "darkforums"

    def _fetch_html(self, url: str, config: SiteConfig, mode: str) -> str:
        return fetch_url(
            url=url,
            mode=mode,
            timeout_seconds=config.fetch_timeout_seconds,
            render_wait_seconds=config.render_wait_seconds,
            retries=1,
        )

    @staticmethod
    def _is_valid_detail_html(html: str) -> bool:
        if not html:
            return False
        nul_ratio = html.count("\x00") / max(len(html), 1)
        if nul_ratio > 0.01:
            return False
        required_markers = ("id=\"posts\"", "post_body", "post_content", "post classic")
        return any(marker in html for marker in required_markers)

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        sections: list[dict[str, object]] = []
        raw_html_by_url: dict[str, str] = {}
        collected_at_utc = utc_now_iso()
        for url in config.seed_urls:
            html = self._fetch_html(url, config, config.seed_fetch_mode)
            parsed = parse_darkforums_list(url, html, max_topics=config.max_topics_per_run)
            section = _section_name(url)
            parsed["section"] = section
            for topic in parsed["topics"]:
                topic["section"] = section
            raw_html_by_url[url] = html
            sections.append(parsed)

        payload = {
            "site_name": self.site_name,
            "source_url": "darkforums",
            "collected_at_utc": collected_at_utc,
            "section_count": len(sections),
            "topic_count": sum(int(section["topic_count"]) for section in sections),
            "sections": sections,
        }
        return SeedResult(
            site_name=self.site_name,
            collected_at_utc=collected_at_utc,
            payload=payload,
            raw_html_by_url=raw_html_by_url,
        )

    def plan_details(self, seed_result: SeedResult, config: SiteConfig) -> list[DetailTask]:
        per_section_tasks: list[list[DetailTask]] = []
        with get_db_connection() as connection:
            for section in seed_result.payload["sections"]:
                section_name = str(section["section"])
                section_tasks: list[DetailTask] = []
                for topic in section["topics"]:
                    topic_snapshot = get_forum_topic_snapshot(
                        connection,
                        site_name=self.site_name,
                        section=section_name,
                        url=str(topic["full_url"]),
                    )
                    detail_snapshot = get_forum_detail_snapshot(
                        connection,
                        site_name=self.site_name,
                        section=section_name,
                        topic_url=str(topic["full_url"]),
                    )
                    topic_changed = topic_snapshot is None or topic_snapshot["content_hash"] != topic["content_hash"]
                    detail_artifacts_ready = _detail_artifacts_exist(
                        config.output_dir,
                        section_name,
                        str(topic["full_url"]),
                    )
                    if not topic_changed and detail_snapshot is not None and detail_artifacts_ready:
                        continue
                    section_tasks.append(
                        DetailTask(
                            site_name=self.site_name,
                            target_url=str(topic["full_url"]),
                            metadata={
                                "section": section_name,
                                "artifact_stem": _detail_artifact_stem(str(topic["full_url"])),
                                "title": topic["title"],
                            },
                        )
                    )
                if section_tasks:
                    per_section_tasks.append(section_tasks)

        tasks: list[DetailTask] = []
        max_details = max(config.max_detail_pages_per_run, 0)
        while len(tasks) < max_details and any(per_section_tasks):
            next_round: list[list[DetailTask]] = []
            for bucket in per_section_tasks:
                if len(tasks) >= max_details:
                    break
                if not bucket:
                    continue
                tasks.append(bucket.pop(0))
                if bucket:
                    next_round.append(bucket)
            per_section_tasks = next_round
        return tasks

    def collect_detail(self, detail_task: DetailTask, config: SiteConfig, run_ctx: RunContext) -> DetailResult | None:
        html = ""
        screenshot_png = None
        last_html = ""
        for attempt in range(2):
            html, screenshot_png = fetch_page_artifacts(
                url=detail_task.target_url,
                mode=config.detail_fetch_mode,
                timeout_seconds=config.fetch_timeout_seconds,
                render_wait_seconds=config.render_wait_seconds,
                screenshot_selectors=(
                    "#thread-info",
                    ".post.classic",
                ),
                hide_selectors=(
                    "header",
                    "#panel",
                    "#quick-search",
                    ".bam_wrapper",
                    ".footer",
                    "footer",
                ),
                render_html_for_screenshot=True,
            )
            last_html = html
            if self._is_valid_detail_html(html):
                break
            print(
                f"[darkforums] invalid detail html on attempt {attempt + 1} for {detail_task.target_url}; retrying"
            )
        html = last_html
        detail = parse_darkforums_detail(detail_task.target_url, html)
        return DetailResult(
            site_name=self.site_name,
            target_url=detail_task.target_url,
            payload=detail,
            raw_html=html,
            screenshot_png=screenshot_png,
            metadata=detail_task.metadata,
        )

    def persist(
        self,
        config: SiteConfig,
        run_ctx: RunContext,
        seed_result: SeedResult | None = None,
        detail_results: list[DetailResult] | None = None,
    ) -> None:
        if seed_result is not None:
            output_dir = config.output_dir
            with get_db_connection() as connection:
                for section in seed_result.payload["sections"]:
                    section_name = str(section["section"])
                    section_dir = output_dir / section_name
                    section_url = str(section["source_url"])
                    html = seed_result.raw_html_by_url[section_url]
                    dump_text(section_dir / "section_page.html", html)
                    dump_json(section_dir / "topics_list.json", section)
                    for topic in section["topics"]:
                        upsert_forum_topic(
                            connection,
                            site_name=self.site_name,
                            section=section_name,
                            title=topic["title"],
                            url=topic["full_url"],
                            author=topic.get("author", ""),
                            replies=topic.get("replies", ""),
                            views=topic.get("views", ""),
                            published_at=topic.get("published_at", ""),
                            last_reply_at=topic.get("last_reply_at", ""),
                            content_hash=topic["content_hash"],
                            collected_at_utc=section["collected_at_utc"],
                        )
                connection.commit()
            dump_json(output_dir / "latest.json", seed_result.payload)

        if detail_results:
            with get_db_connection() as connection:
                for detail_result in detail_results:
                    section_name = str(detail_result.metadata["section"])
                    section_dir = config.output_dir / section_name / "details"
                    artifact_stem = str(detail_result.metadata.get("artifact_stem") or _detail_artifact_stem(detail_result.target_url))
                    if detail_result.raw_html is not None:
                        dump_text(section_dir / f"{artifact_stem}.html", detail_result.raw_html)
                    if detail_result.screenshot_png is not None:
                        (section_dir / f"{artifact_stem}.png").write_bytes(detail_result.screenshot_png)
                    dump_json(section_dir / f"{artifact_stem}.json", detail_result.payload)
                    upsert_forum_detail(
                        connection,
                        site_name=self.site_name,
                        section=section_name,
                        topic_url=detail_result.target_url,
                        content=detail_result.payload.get("content", ""),
                        authors=detail_result.payload.get("author", ""),
                        timestamps=detail_result.payload.get("timestamp", ""),
                        attachments=", ".join(detail_result.payload.get("attachments", [])),
                        victims=detail_result.payload.get("victims", []),
                        attackers=detail_result.payload.get("attackers", []),
                        content_hash=detail_result.payload["content_hash"],
                        collected_at_utc=detail_result.payload.get("collected_at_utc", ""),
                    )
                connection.commit()
                try:
                    from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence

                    ensure_normalized_intelligence(connection, force=True)
                except Exception as exc:
                    print(f"[darkforums] warning: failed to refresh normalized intelligence after detail persist: {exc}")
