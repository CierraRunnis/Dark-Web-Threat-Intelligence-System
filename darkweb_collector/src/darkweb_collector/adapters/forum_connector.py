from __future__ import annotations

from hashlib import sha1
import json
import os
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from darkweb_collector.adapters.base import SiteAdapter
from darkweb_collector.db import get_db_connection, upsert_forum_detail, upsert_forum_topic
from darkweb_collector.models import DetailResult, DetailTask, RunContext, SeedResult, SiteConfig
from darkweb_collector.utils import dump_json, utc_now_iso


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    normalized = _text(value)
    return [normalized] if normalized else []


def _section_for(finding: dict[str, Any]) -> str:
    value = _text(finding.get("threat_type") or finding.get("category")).lower()
    if any(token in value for token in ("database", "dump", "sql", "数据库")):
        return "databases"
    if any(token in value for token in ("sell", "sale", "market", "售卖", "出售", "交易")):
        return "sellers_place"
    return "other_leaks"


class ForumConnectorAdapter(SiteAdapter):
    def __init__(self, site_name: str) -> None:
        self.site_name = site_name

    def _connector_url(self, config: SiteConfig) -> str:
        environment = _text(config.extras.get("connector_url_env"))
        connector_url = _text(os.environ.get(environment)) if environment else ""
        if not connector_url:
            raise RuntimeError(f"{self.site_name}: connector URL is not configured")
        if urlparse(connector_url).scheme not in {"http", "https"}:
            raise RuntimeError(f"{self.site_name}: connector URL must use http or https")
        return connector_url

    def _request_payload(self, config: SiteConfig) -> Any:
        connector_url = self._connector_url(config)
        headers = {"Accept": "application/json", "User-Agent": "DarkWebThreatIntel/0.11"}
        token_environment = _text(config.extras.get("connector_token_env"))
        token = _text(os.environ.get(token_environment)) if token_environment else ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(connector_url, headers=headers, method="GET")
        timeout = max(1, int(config.extras.get("connector_timeout_seconds", 25)))
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _normalize_finding(self, finding: dict[str, Any], collected_at: str) -> dict[str, Any]:
        title = _text(finding.get("title"))
        if not title:
            raise ValueError(f"{self.site_name}: connector finding requires title")

        source_url = _text(finding.get("source_url") or finding.get("url"))
        external_id = _text(finding.get("event_id") or finding.get("id") or finding.get("source_id"))
        if not source_url and not external_id:
            raise ValueError(f"{self.site_name}: connector finding requires source_url or event_id")
        if not source_url:
            source_url = f"connector://{self.site_name}/{quote(external_id, safe='')}"

        published_at = _text(
            finding.get("discovered_at")
            or finding.get("published_at")
            or finding.get("timestamp")
        ) or collected_at
        content = _text(
            finding.get("full_content")
            or finding.get("content")
            or finding.get("content_excerpt")
            or finding.get("summary")
        )
        target_name = _text(finding.get("target_name") or finding.get("victim"))
        victims = []
        if target_name:
            victims.append(
                {
                    "name": target_name,
                    "industry": _text(finding.get("target_industry") or finding.get("industry")) or None,
                    "region": _text(finding.get("region")) or None,
                }
            )
        attackers = _string_list(finding.get("attackers") or finding.get("attacker"))
        attachments = _string_list(finding.get("attachments"))
        screenshot_url = _text(finding.get("screenshot_url"))
        if screenshot_url and screenshot_url not in attachments:
            attachments.append(screenshot_url)

        normalized = {
            "title": title,
            "source_url": source_url,
            "section": _section_for(finding),
            "author": _text(finding.get("author")),
            "published_at": published_at,
            "content": content,
            "victims": victims,
            "attackers": attackers,
            "attachments": attachments,
            "collected_at_utc": collected_at,
        }
        normalized["content_hash"] = sha1(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return normalized

    def collect_seed(self, config: SiteConfig, run_ctx: RunContext) -> SeedResult:
        payload = self._request_payload(config)
        if isinstance(payload, list):
            findings = payload
        elif isinstance(payload, dict):
            findings = payload.get("findings") or payload.get("items") or payload.get("results") or []
        else:
            findings = []
        if not isinstance(findings, list):
            raise ValueError(f"{self.site_name}: connector response findings must be a list")

        collected_at = utc_now_iso()
        limit = max(0, config.max_topics_per_run)
        normalized = [
            self._normalize_finding(item, collected_at)
            for item in findings[:limit]
            if isinstance(item, dict)
        ]
        return SeedResult(
            site_name=self.site_name,
            collected_at_utc=collected_at,
            payload={"site_name": self.site_name, "findings": normalized},
            raw_html_by_url={},
        )

    def plan_details(self, seed_result: SeedResult, config: SiteConfig) -> list[DetailTask]:
        return []

    def collect_detail(
        self,
        detail_task: DetailTask,
        config: SiteConfig,
        run_ctx: RunContext,
    ) -> DetailResult | None:
        return None

    def persist(
        self,
        config: SiteConfig,
        run_ctx: RunContext,
        seed_result: SeedResult | None = None,
        detail_results: list[DetailResult] | None = None,
    ) -> None:
        if seed_result is None:
            return
        findings = seed_result.payload.get("findings") or []
        with get_db_connection() as connection:
            for finding in findings:
                upsert_forum_topic(
                    connection,
                    site_name=self.site_name,
                    section=finding["section"],
                    title=finding["title"],
                    url=finding["source_url"],
                    author=finding["author"],
                    published_at=finding["published_at"],
                    last_reply_at=finding["published_at"],
                    content_hash=finding["content_hash"],
                    collected_at_utc=finding["collected_at_utc"],
                )
                upsert_forum_detail(
                    connection,
                    site_name=self.site_name,
                    section=finding["section"],
                    topic_url=finding["source_url"],
                    content=finding["content"],
                    authors=finding["author"],
                    timestamps=finding["published_at"],
                    published_at_utc=finding["published_at"],
                    attachments=", ".join(finding["attachments"]),
                    victims=finding["victims"],
                    attackers=finding["attackers"],
                    content_hash=finding["content_hash"],
                    collected_at_utc=finding["collected_at_utc"],
                )
            connection.commit()
        dump_json(config.output_dir / "latest.json", seed_result.payload)
