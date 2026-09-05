from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from darkweb_collector.adapters.pwnfrm import PwnfrmAdapter
from darkweb_collector.db import (
    get_db_connection,
    get_forum_detail_snapshot,
    get_forum_topic_snapshot,
)
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig
from darkweb_collector.session_cookies import resolve_session_cookie
from darkweb_collector.sites.updap import (
    UpdapParseError,
    parse_updap_detail,
    parse_updap_list,
)
from darkweb_collector.tor_fetch import fetch_url
from darkweb_collector.utils import safe_stem, utc_now_iso


def _section_name(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if path.startswith("Forum-"):
        return path[6:].replace("-", "_").lower()
    return safe_stem(path or "section")


def _detail_artifact_stem(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _detail_json_exists(output_dir, section_name: str, topic_url: str) -> bool:
    artifact_stem = _detail_artifact_stem(topic_url)
    return (output_dir / section_name / "details" / f"{artifact_stem}.json").exists()


class UpdapAdapter(PwnfrmAdapter):
    """Low-volume adapter for UpDap's public MyBB pages.

    Raw thread HTML and screenshots are intentionally not persisted. The parser
    stores the public meta description (or a redacted excerpt) so accidental
    samples of personal data are not copied into local artifacts.
    """

    site_name = "updap"

    def _fetch_html(self, url: str, config: SiteConfig, mode: str) -> str:
        return fetch_url(
            url=url,
            mode=mode,
            timeout_seconds=config.fetch_timeout_seconds,
            render_wait_seconds=config.render_wait_seconds,
            retries=0,
            cookie_header=resolve_session_cookie(config),
        )

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        sections: list[dict[str, object]] = []
        raw_html_by_url: dict[str, str] = {}
        collected_at_utc = utc_now_iso()
        for url in config.seed_urls:
            html = self._fetch_html(url, config, config.seed_fetch_mode)
            parsed = parse_updap_list(url, html, max_topics=config.max_topics_per_run)
            section = _section_name(url)
            parsed["section"] = section
            for topic in parsed["topics"]:
                topic["section"] = section
            raw_html_by_url[url] = html
            sections.append(parsed)

        payload = {
            "site_name": self.site_name,
            "source_url": self.site_name,
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
                    topic_url = str(topic["full_url"])
                    topic_snapshot = get_forum_topic_snapshot(
                        connection,
                        site_name=self.site_name,
                        section=section_name,
                        url=topic_url,
                    )
                    detail_snapshot = get_forum_detail_snapshot(
                        connection,
                        site_name=self.site_name,
                        section=section_name,
                        topic_url=topic_url,
                    )
                    topic_changed = (
                        topic_snapshot is None
                        or topic_snapshot["content_hash"] != topic["content_hash"]
                    )
                    detail_json_ready = _detail_json_exists(
                        config.output_dir,
                        section_name,
                        topic_url,
                    )
                    if not topic_changed and detail_snapshot is not None and detail_json_ready:
                        continue
                    section_tasks.append(
                        DetailTask(
                            site_name=self.site_name,
                            target_url=topic_url,
                            metadata={
                                "section": section_name,
                                "artifact_stem": _detail_artifact_stem(topic_url),
                                "title": topic["title"],
                                "raw_capture_policy": "sanitized_json_only",
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

    def collect_detail(
        self,
        detail_task: DetailTask,
        config: SiteConfig,
        run_ctx: RunContext,
    ) -> DetailResult:
        html = self._fetch_html(
            detail_task.target_url,
            config,
            config.detail_fetch_mode,
        )
        if not self._is_valid_detail_html(html):
            raise UpdapParseError(
                f"UpDap detail response is not a usable thread: {detail_task.target_url}"
            )
        detail = parse_updap_detail(detail_task.target_url, html)
        if not self._is_valid_detail_payload(detail):
            raise UpdapParseError(
                f"UpDap detail response has no usable public payload: {detail_task.target_url}"
            )
        return DetailResult(
            site_name=self.site_name,
            target_url=detail_task.target_url,
            payload=detail,
            raw_html=None,
            screenshot_png=None,
            metadata=detail_task.metadata,
        )
