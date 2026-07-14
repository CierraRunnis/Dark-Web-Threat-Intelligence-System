from __future__ import annotations

from html import escape
import hashlib
import json
import shutil
import subprocess
from urllib.parse import urlencode, urlsplit, urlunsplit

from darkweb_collector.adapters.base import SiteAdapter
from darkweb_collector.browser_client import fetch_page_artifacts_with_browser
from darkweb_collector.db import (
    get_db_connection,
    get_forum_detail_snapshot,
    get_forum_topic_snapshot,
    upsert_forum_detail,
    upsert_forum_topic,
)
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig
from darkweb_collector.site_auth import (
    SiteAuthenticationRequired,
    mark_site_auth_invalid,
    require_site_auth_token,
)
from darkweb_collector.sites.changan import parse_changan_detail, parse_changan_list
from darkweb_collector.tor_fetch import browser_proxy_server_for_url, get_tor_socks_settings
from darkweb_collector.utils import dump_json, dump_text, utc_now_iso


AUTH_ERROR_CODES = {4009, 4087}
SECTION = "sellers_place"


def _base_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _artifact_stem(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _fallback_html(detail: dict) -> str:
    title = escape(str(detail.get("title") or "长安不夜城商品详情"))
    content = escape(str(detail.get("content") or "")).replace("\n", "<br>")
    return f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title></head><body><article><h1>{title}</h1><p>{content}</p></article></body></html>"


class ChanganAdapter(SiteAdapter):
    site_name = "changan"

    def _api_get(
        self,
        config: SiteConfig,
        path: str,
        params: dict[str, object] | None = None,
    ) -> dict:
        token, _ = require_site_auth_token(config)
        base_url = _base_url(config.seed_urls[0])
        query = urlencode(params or {})
        url = f"{base_url}{path}{'?' + query if query else ''}"
        curl = shutil.which("curl")
        if not curl:
            raise RuntimeError("curl not found in PATH")
        socks_host, socks_port = get_tor_socks_settings()
        command = [
            curl,
            "--socks5-hostname",
            f"{socks_host}:{socks_port}",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(config.fetch_timeout_seconds),
            "--header",
            "Accept: application/json",
            "--header",
            f"Authorization: Bearer {token}",
            "--header",
            f"Referer: {base_url}/#/home",
            "--user-agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            url,
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip() or "unknown curl error"
            raise RuntimeError(f"changan API request failed: {error}")
        body = result.stdout.decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("changan API returned invalid JSON") from exc
        code = int(payload.get("code") or 0)
        if code in AUTH_ERROR_CODES:
            message = str(payload.get("msg") or "长安不夜城登录会话已失效")
            mark_site_auth_invalid(config, message)
            raise SiteAuthenticationRequired(str(config.extras.get("auth_platform") or "changan"), message)
        if code != 2000:
            raise RuntimeError(f"changan API error {code}: {payload.get('msg') or 'unknown error'}")
        return payload

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        collected_at_utc = utc_now_iso()
        base_url = _base_url(config.seed_urls[0])
        raw = self._api_get(
            config,
            "/api/category/goods",
            {
                "cid": 0,
                "page_num": 1,
                "page_size": config.max_topics_per_run,
                "order": "",
                "order_by": "",
            },
        )
        section = parse_changan_list(
            raw,
            base_url=base_url,
            collected_at_utc=collected_at_utc,
            max_topics=config.max_topics_per_run,
            excluded_categories=config.extras.get("excluded_categories"),
        )
        stored_raw = dict(raw)
        stored_items = [topic["raw"] for topic in section["topics"]]
        if isinstance(raw.get("data"), dict):
            stored_data = dict(raw["data"])
            stored_data.pop("list", None)
            stored_data["goods"] = stored_items
            stored_data["total"] = section["total"]
            stored_raw["data"] = stored_data
        else:
            stored_raw.pop("list", None)
            stored_raw["goods"] = stored_items
            stored_raw["total"] = section["total"]
        payload = {
            "site_name": self.site_name,
            "source_url": section["source_url"],
            "collected_at_utc": collected_at_utc,
            "section_count": 1,
            "topic_count": section["topic_count"],
            "sections": [section],
        }
        return SeedResult(
            site_name=self.site_name,
            collected_at_utc=collected_at_utc,
            payload=payload,
            raw_html_by_url={config.seed_urls[0]: json.dumps(stored_raw, ensure_ascii=False, indent=2)},
        )

    def plan_details(self, seed_result: SeedResult, config: SiteConfig) -> list[DetailTask]:
        tasks: list[DetailTask] = []
        section = seed_result.payload["sections"][0]
        with get_db_connection() as connection:
            for topic in section["topics"]:
                topic_url = str(topic["full_url"])
                topic_snapshot = get_forum_topic_snapshot(connection, self.site_name, SECTION, topic_url)
                detail_snapshot = get_forum_detail_snapshot(connection, self.site_name, SECTION, topic_url)
                stem = _artifact_stem(topic_url)
                detail_dir = config.output_dir / SECTION / "details"
                artifacts_ready = all(
                    (detail_dir / f"{stem}.{suffix}").exists()
                    for suffix in ("html", "json", "png")
                )
                unchanged = topic_snapshot is not None and topic_snapshot["content_hash"] == topic["content_hash"]
                if unchanged and detail_snapshot is not None and artifacts_ready:
                    continue
                tasks.append(
                    DetailTask(
                        site_name=self.site_name,
                        target_url=topic_url,
                        metadata={
                            "section": SECTION,
                            "artifact_stem": stem,
                            "goods_id": topic["goods_id"],
                            "title": topic["title"],
                        },
                    )
                )
                if len(tasks) >= max(config.max_detail_pages_per_run, 0):
                    break
        return tasks

    def collect_detail(
        self,
        detail_task: DetailTask,
        config: SiteConfig,
        run_ctx: RunContext,
    ) -> DetailResult | None:
        raw = self._api_get(config, "/api/goods/detail", {"gid": detail_task.metadata["goods_id"]})
        detail = parse_changan_detail(
            raw,
            detail_url=detail_task.target_url,
            collected_at_utc=utc_now_iso(),
        )
        raw_html = _fallback_html(detail)
        screenshot_png = None
        _, storage_state_path = require_site_auth_token(config)
        try:
            raw_html, screenshot_png = fetch_page_artifacts_with_browser(
                url=detail_task.target_url,
                wait_seconds=config.render_wait_seconds,
                timeout_seconds=config.fetch_timeout_seconds,
                proxy_server=browser_proxy_server_for_url(detail_task.target_url),
                screenshot_selectors=(".product-detail-info",),
                hide_selectors=("header", ".header", ".sidebar", ".nav"),
                storage_state_path=storage_state_path,
            )
        except Exception as exc:
            print(f"[changan] warning: detail screenshot failed for {detail_task.target_url}: {exc}")
        return DetailResult(
            site_name=self.site_name,
            target_url=detail_task.target_url,
            payload=detail,
            raw_html=raw_html,
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
            config.output_dir.mkdir(parents=True, exist_ok=True)
            dump_json(config.output_dir / "latest.json", seed_result.payload)
            dump_text(config.output_dir / "latest.raw.json", seed_result.raw_html_by_url[config.seed_urls[0]])
            with get_db_connection() as connection:
                for section in seed_result.payload["sections"]:
                    for topic in section["topics"]:
                        upsert_forum_topic(
                            connection,
                            site_name=self.site_name,
                            section=SECTION,
                            title=topic["title"],
                            url=topic["full_url"],
                            author=topic.get("author", ""),
                            replies="",
                            views=topic.get("views", ""),
                            published_at=topic.get("published_at", ""),
                            last_reply_at="",
                            content_hash=topic["content_hash"],
                            collected_at_utc=section["collected_at_utc"],
                        )
                connection.commit()

        if detail_results:
            detail_dir = config.output_dir / SECTION / "details"
            detail_dir.mkdir(parents=True, exist_ok=True)
            with get_db_connection() as connection:
                for result in detail_results:
                    stem = str(result.metadata.get("artifact_stem") or _artifact_stem(result.target_url))
                    if result.raw_html is not None:
                        dump_text(detail_dir / f"{stem}.html", result.raw_html)
                    if result.screenshot_png is not None:
                        (detail_dir / f"{stem}.png").write_bytes(result.screenshot_png)
                    dump_json(detail_dir / f"{stem}.json", result.payload)
                    upsert_forum_detail(
                        connection,
                        site_name=self.site_name,
                        section=SECTION,
                        topic_url=result.target_url,
                        content=result.payload.get("content", ""),
                        authors=result.payload.get("author", ""),
                        timestamps=result.payload.get("timestamp", ""),
                        published_at_utc=result.payload.get("published_at_utc", ""),
                        attachments=", ".join(result.payload.get("attachments", [])),
                        victims=result.payload.get("victims", []),
                        attackers=result.payload.get("attackers", []),
                        content_hash=result.payload["content_hash"],
                        collected_at_utc=result.payload.get("collected_at_utc", ""),
                    )
                connection.commit()
