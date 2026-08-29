from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from darkweb_collector.adapters.base import SiteAdapter
from darkweb_collector.browser_client import (
    close_browser_client,
    fetch_html_with_browser,
    fetch_page_artifacts_with_browser,
    screenshot_html_with_browser,
)
from darkweb_collector.db import (
    get_db_connection,
    get_forum_detail_snapshot,
    get_forum_topic_snapshot,
    upsert_forum_detail,
    upsert_forum_topic,
)
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig
from darkweb_collector.session_cookies import resolve_session_cookie
from darkweb_collector.sites.cracked import parse_cracked_detail, parse_cracked_list
from darkweb_collector.tor_fetch import fetch_via_http_proxy, get_http_proxy_settings
from darkweb_collector.runtime import user_data_root
from darkweb_collector.utils import dump_json, dump_text, safe_stem, utc_now_iso


def _section_name(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if path.startswith("Forum-"):
        slug = path[6:].split("--", 1)[0]
        parts = [part for part in slug.lower().split("-") if part]
        return "_".join(parts) or "section"
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


def _browser_storage_state_path(config: SiteConfig) -> str | None:
    raw_path = str(config.extras.get("browser_storage_state_file") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = user_data_root() / path
    return str(path.resolve())


class CrackedAdapter(SiteAdapter):
    site_name = "cracked"

    @staticmethod
    def _is_valid_seed_html(html: str) -> bool:
        lowered = str(html or "").lower()
        challenge_markers = ("checking your browser", "cf-browser-verification", "verify you are human")
        if not lowered or any(marker in lowered for marker in challenge_markers):
            return False
        return "forum-" in lowered and ("thread-" in lowered or "subject_new" in lowered)

    def _fetch_with_fallback(
        self,
        url: str,
        config: SiteConfig,
        *,
        validator: Callable[[str], bool],
        capture_screenshot: bool,
    ) -> tuple[str, bytes | None]:
        cookie_header = resolve_session_cookie(config)
        proxy_host, proxy_port = get_http_proxy_settings()
        browser_engine = str(config.extras.get("browser_engine") or "chromium").strip().lower()
        storage_state_path = _browser_storage_state_path(config)
        routes: list[tuple[str, Callable[[], tuple[str, bytes | None]]]] = []

        def curl_route(*, bypass_proxy: bool, host: str | None = None, port: int | None = None):
            html = fetch_via_http_proxy(
                url,
                proxy_host=host,
                proxy_port=port,
                timeout=config.fetch_timeout_seconds,
                retries=0,
                bypass_proxy=bypass_proxy,
            )
            screenshot = None
            if capture_screenshot:
                try:
                    screenshot = screenshot_html_with_browser(
                        html,
                        url,
                        wait_seconds=config.render_wait_seconds,
                        timeout_seconds=config.fetch_timeout_seconds,
                        browser_engine=browser_engine,
                    )
                except Exception:
                    screenshot = None
            return html, screenshot

        def browser_route(cookie: str | None = None):
            route_storage_state = storage_state_path if not cookie else None
            if not capture_screenshot:
                return (
                    fetch_html_with_browser(
                        url,
                        wait_seconds=config.render_wait_seconds,
                        timeout_seconds=config.fetch_timeout_seconds,
                        proxy_server=None,
                        browser_engine=browser_engine,
                        storage_state_path=route_storage_state,
                        persist_storage_state=bool(route_storage_state),
                        cookie_header=cookie,
                    ),
                    None,
                )
            html, screenshot = fetch_page_artifacts_with_browser(
                url,
                wait_seconds=config.render_wait_seconds,
                timeout_seconds=config.fetch_timeout_seconds,
                proxy_server=None,
                browser_engine=browser_engine,
                screenshot_selectors=("#posts", ".post_body") if capture_screenshot else (),
                hide_selectors=("header", "#panel", "#quick-search", ".footer", "footer", ".signature"),
                storage_state_path=route_storage_state,
                persist_storage_state=bool(route_storage_state),
                cookie_header=cookie,
            )
            return html, screenshot or None

        routes.append(("direct", lambda: curl_route(bypass_proxy=True)))
        if proxy_host and proxy_port:
            routes.append(("proxy", lambda: curl_route(bypass_proxy=False, host=proxy_host, port=proxy_port)))
        routes.append(("browser", lambda: browser_route()))
        if cookie_header:
            routes.append(("browser_cookie", lambda: browser_route(cookie_header)))

        failures: list[str] = []
        for index, (route_name, fetcher) in enumerate(routes):
            try:
                html, screenshot = fetcher()
                if validator(html):
                    return html, screenshot
                failures.append(f"{route_name}:invalid_html")
            except Exception as exc:
                failures.append(f"{route_name}:{type(exc).__name__}:{str(exc)[:160]}")
            close_browser_client()
            if index + 1 < len(routes):
                time.sleep(1)
        raise RuntimeError(f"Cracked fetch failed after bounded fallback: {'; '.join(failures)}")

    def _fetch_html(self, url: str, config: SiteConfig, mode: str) -> str:
        del mode
        return self._fetch_with_fallback(
            url,
            config,
            validator=self._is_valid_seed_html,
            capture_screenshot=False,
        )[0]

    @staticmethod
    def _is_valid_detail_html(html: str) -> bool:
        if not html:
            return False
        nul_ratio = html.count("\x00") / max(len(html), 1)
        if nul_ratio > 0.01:
            return False
        required_markers = ('id="posts"', "post_body", "post-set")
        return any(marker in html for marker in required_markers)

    @staticmethod
    def _is_valid_detail_payload(detail: dict) -> bool:
        content = str(detail.get("content") or "").strip()
        author = str(detail.get("author") or "").strip()
        return bool(content) or (author and author != "Unknown")

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        sections: list[dict[str, object]] = []
        raw_html_by_url: dict[str, str] = {}
        collected_at_utc = utc_now_iso()
        for url in config.seed_urls:
            html = self._fetch_html(url, config, config.seed_fetch_mode)
            parsed = parse_cracked_list(url, html, max_topics=config.max_topics_per_run)
            section = _section_name(url)
            parsed["section"] = section
            for topic in parsed["topics"]:
                topic["section"] = section
            raw_html_by_url[url] = html
            sections.append(parsed)

        payload = {
            "site_name": self.site_name,
            "source_url": "cracked",
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
                    topic_changed = (
                        topic_snapshot is None
                        or topic_snapshot["content_hash"] != topic["content_hash"]
                    )
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

    def collect_detail(
        self, detail_task: DetailTask, config: SiteConfig, run_ctx: RunContext
    ) -> DetailResult | None:
        html, screenshot_png = self._fetch_with_fallback(
            detail_task.target_url,
            config,
            validator=self._is_valid_detail_html,
            capture_screenshot=True,
        )
        detail = parse_cracked_detail(detail_task.target_url, html)
        if not self._is_valid_detail_payload(detail):
            print(f"[cracked] skipping invalid detail persist for {detail_task.target_url}")
            return None
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
                    artifact_stem = str(
                        detail_result.metadata.get("artifact_stem")
                        or _detail_artifact_stem(detail_result.target_url)
                    )
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
                        published_at_utc=detail_result.payload.get("published_at_utc", ""),
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
                    print(f"[cracked] warning: failed to refresh normalized intelligence after detail persist: {exc}")
