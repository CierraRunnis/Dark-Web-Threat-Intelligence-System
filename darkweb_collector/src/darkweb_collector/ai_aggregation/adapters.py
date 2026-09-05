from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .config import Settings


@dataclass(slots=True)
class AnalysisResult:
    markdown: str
    source_coverage: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)
    flocks_scheduler_id: str | None = None
    flocks_execution_id: str | None = None


class MockAnalysisAdapter:
    name = "mock"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.active_runs = 0
        self.peak_active_runs = 0

    async def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "mode": self.name,
            "active_runs": self.active_runs,
            "peak_active_runs": self.peak_active_runs,
        }

    async def generate(
        self,
        run: dict[str, Any],
        on_external_ids: Callable[[str, str], None] | None = None,
    ) -> AnalysisResult:
        self.active_runs += 1
        self.peak_active_runs = max(self.peak_active_runs, self.active_runs)
        try:
            await asyncio.sleep(self.settings.mock_analysis_delay_seconds)
            keywords = list(run.get("keywords") or [run["keyword"]])
            keyword = "、".join(keywords)
            days = run["search_window_days"]
            sources = run["sources"]
            labels = {"darkweb": "暗网", "telegram": "Telegram", "web": "公开 Web"}
            coverage = {source: "completed" for source in sources}
            coverage_rows = "\n".join(
                f"| {labels[source]} | 已完成（模拟） | 已纳入聚合流程 |"
                for source in sources
            )
            markdown = f"""# {keyword}威胁情报报告

> 项目内 Mock 生成时间：{datetime.now(timezone.utc).isoformat()}  
> 固定任务模板：`{run['rendered_prompt']}`  
> 检索窗口：最近 {days} 天  
> 数据源：{'、'.join(labels[source] for source in sources)}

## 执行摘要

本报告由项目内 Mock 适配器生成结构化模拟结果，用于验证 AI 聚合模块的并发、持久化、报告查询与多目标投递链路。它不代表已核实的真实威胁事实，也不应直接作为处置依据。

## 来源覆盖

| 来源 | 状态 | 说明 |
| --- | --- | --- |
{coverage_rows}

## 关键发现

1. **品牌与资产暴露监测**：建议持续关注与“{keyword}”相关的仿冒域名、凭证交易及数据泄露讨论。[证据：mock-{run['id'][:8]}-01]
2. **攻击面变化**：公开来源与封闭社区的信号需交叉验证，单一来源命中不能直接判定事件真实性。[证据：mock-{run['id'][:8]}-02]
3. **供应链关联**：应同时检查关键供应商、子品牌与历史域名，避免只搜索主体名称造成漏报。[证据：mock-{run['id'][:8]}-03]

## 风险研判

| 风险维度 | 模拟等级 | 判断依据 |
| --- | --- | --- |
| 数据泄露 | 中 | 仅为链路测试生成的模拟观察项 |
| 凭证暴露 | 中 | 需要结合内部身份系统日志复核 |
| 勒索与敲诈 | 低 | 当前 Mock 适配器不提供真实事件证据 |
| 舆情与仿冒 | 中 | 建议结合域名与社交平台监测 |

## 处置建议

- 对命中事件执行来源真实性、时间与资产归属三项复核。
- 将已确认 IOC 送入 SIEM/EDR，未确认内容仅作为观察线索。
- 为高价值账号启用强认证，并检查最近 {days} 天的异常登录。
- 记录证据 ID、原始链接和复核人，保留审计链。

## 局限性

- 当前为 mock 模式，未调用 Flocks、模型或外部情报源。
- 所有发现、风险等级和证据编号均为演示数据。
- live 模式下仍需检查来源失败、模型幻觉、提示注入与 API 限流。
"""
            return AnalysisResult(
                markdown=markdown,
                source_coverage=coverage,
                metadata={
                    "adapter": self.name,
                    "mock": True,
                    "warning": "此报告为模拟数据，不代表真实威胁情报。",
                },
            )
        finally:
            self.active_runs -= 1


class FlocksTaskCenterAdapter:
    name = "live"
    terminal_statuses = {"completed", "failed", "cancelled"}

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        headers = {}
        if settings.flocks_api_key:
            headers["Authorization"] = f"Bearer {settings.flocks_api_key}"
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=settings.flocks_base_url,
            headers=headers,
            timeout=settings.http_timeout_seconds,
            trust_env=False,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def health(self) -> dict[str, Any]:
        try:
            response = await self.client.get("/api/task-system/queue/status")
            response.raise_for_status()
            payload = response.json()
            required = {"running", "queued", "max_concurrent"}
            if not isinstance(payload, dict) or not required.issubset(payload):
                raise RuntimeError("endpoint does not expose the Flocks Task Center status shape")
            return {"status": "ready", "mode": self.name, "flocks": payload}
        except Exception as exc:
            return {"status": "unavailable", "mode": self.name, "error": str(exc)}

    async def generate(
        self,
        run: dict[str, Any],
        on_external_ids: Callable[[str, str], None] | None = None,
    ) -> AnalysisResult:
        scheduler_id: str | None = None
        execution_id: str | None = None
        scheduler_disabled = False
        execution_terminal = False
        try:
            response = await self.client.post(
                "/api/task-schedulers",
                json={
                    "title": f"AI聚合：{run['keyword']}",
                    "description": run["rendered_prompt"],
                    "type": "queued",
                    "priority": "normal",
                    "executionMode": "workflow",
                    "workflowID": self.settings.workflow_id,
                    "agentName": "search-supervisor",
                    "tags": ["ai-aggregation", f"run:{run['id']}"],
                    "context": {
                        "query": run["rendered_prompt"],
                        "search_window_days": run["search_window_days"],
                        "include_sources": run["sources"],
                        "report_language": run["language"],
                        "ai_aggregation_run_id": run["id"],
                    },
                },
            )
            response.raise_for_status()
            scheduler_id = response.json().get("id")
            if not scheduler_id:
                raise RuntimeError("Flocks did not return a scheduler id")

            execution = await self._wait_for_scheduler_execution(scheduler_id)
            execution_id = execution.get("id")
            if not execution_id:
                raise RuntimeError("Flocks did not return an execution id")
            disable_response = await self.client.post(
                f"/api/task-schedulers/{scheduler_id}/disable"
            )
            disable_response.raise_for_status()
            scheduler_disabled = True
            if on_external_ids:
                on_external_ids(scheduler_id, execution_id)

            execution = await self._wait_for_terminal_execution(execution_id)
            execution_terminal = True
            status = str(execution.get("status") or "").lower()
            if status != "completed":
                raise RuntimeError(
                    execution.get("error") or f"Flocks execution ended with status {status}"
                )
            result_summary = execution.get("resultSummary") or ""
            markdown, extracted, parsed = extract_flocks_report(result_summary)
            if not markdown.strip():
                raise RuntimeError("Flocks execution completed without a report")
            return AnalysisResult(
                markdown=markdown,
                source_coverage=extract_source_coverage(parsed, run["sources"]),
                metadata={
                    "adapter": self.name,
                    "workflow_id": self.settings.workflow_id,
                    "report_extracted_from": extracted,
                    "flocks_status": status,
                },
                flocks_scheduler_id=scheduler_id,
                flocks_execution_id=execution_id,
            )
        finally:
            if execution_id and not execution_terminal:
                try:
                    await self.client.post(f"/api/task-executions/{execution_id}/cancel")
                except Exception:
                    pass
            if scheduler_id and not scheduler_disabled:
                try:
                    await self.client.post(f"/api/task-schedulers/{scheduler_id}/disable")
                except Exception:
                    pass

    async def _wait_for_scheduler_execution(self, scheduler_id: str) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + min(
            self.settings.flocks_execution_timeout_seconds, 30.0
        )
        while True:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Flocks did not create an execution for scheduler {scheduler_id}")
            response = await self.client.get(
                f"/api/task-schedulers/{scheduler_id}/executions",
                params={"limit": 1, "offset": 0},
            )
            response.raise_for_status()
            items = response.json().get("items") or []
            if items:
                return items[0]
            await asyncio.sleep(self.settings.flocks_poll_interval_seconds)

    async def _wait_for_terminal_execution(self, execution_id: str) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.settings.flocks_execution_timeout_seconds
        while True:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    f"Flocks execution {execution_id} exceeded "
                    f"{self.settings.flocks_execution_timeout_seconds:g} seconds"
                )
            response = await self.client.get(f"/api/task-executions/{execution_id}")
            response.raise_for_status()
            execution = response.json()
            if str(execution.get("status") or "").lower() in self.terminal_statuses:
                return execution
            await asyncio.sleep(self.settings.flocks_poll_interval_seconds)


def _parse_summary(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _find_key(value: Any, keys: tuple[str, ...]) -> tuple[Any, str | None]:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate, key
        for candidate in value.values():
            found, key = _find_key(candidate, keys)
            if found is not None:
                return found, key
    elif isinstance(value, list):
        for candidate in value:
            found, key = _find_key(candidate, keys)
            if found is not None:
                return found, key
    return None, None


def extract_flocks_report(result_summary: Any) -> tuple[str, str, Any]:
    parsed = _parse_summary(result_summary)
    report, key = _find_key(
        parsed,
        ("final_report", "report_markdown", "finalReport", "reportMarkdown"),
    )
    if isinstance(report, str):
        return report.strip(), str(key), parsed
    if isinstance(parsed, str) and parsed.strip():
        if parsed.lstrip().startswith("#"):
            return parsed.strip(), "resultSummary", parsed
        return (
            "# Flocks 威胁情报报告\n\n"
            "> 未能从结构化输出中定位 `final_report`，以下为 Flocks 原始结果摘要。\n\n"
            + parsed.strip(),
            "resultSummary-fallback",
            parsed,
        )
    return "", "missing", parsed


def extract_source_coverage(parsed: Any, requested_sources: list[str]) -> dict[str, str]:
    def find(value: Any) -> dict[str, str] | None:
        if isinstance(value, dict):
            coverage = value.get("source_coverage")
            if isinstance(coverage, dict):
                return {str(key): str(item) for key, item in coverage.items()}
            for candidate in value.values():
                found = find(candidate)
                if found:
                    return found
        elif isinstance(value, list):
            for candidate in value:
                found = find(candidate)
                if found:
                    return found
        return None

    return find(parsed) or {source: "unknown" for source in requested_sources}


class DeliveryAdapter:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def send(self, delivery: dict[str, Any], run: dict[str, Any]) -> None:
        if self.settings.delivery_mode == "mock":
            await asyncio.sleep(0)
            return
        if delivery["type"] == "callback":
            await self._send_callback(delivery, run)
        elif delivery["type"] == "wecom":
            await self._send_wecom(delivery, run)
        else:
            raise ValueError(f"unsupported delivery type: {delivery['type']}")

    async def _send_callback(self, delivery: dict[str, Any], run: dict[str, Any]) -> None:
        url = str(delivery["target"].get("url") or "")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("callback URL is not safe")
        allowed_hosts = {item.lower() for item in self.settings.allowed_callback_hosts}
        if host not in allowed_hosts:
            raise ValueError(
                f"callback host '{host}' is not allowed; configure "
                "AI_AGGREGATION_CALLBACK_ALLOWED_HOSTS explicitly"
            )
        report = run.get("report") or {}
        response = await self.client.post(
            url,
            json={
                "schema_version": "ai-aggregation.callback.v1",
                "run_id": run["id"],
                "profile_id": run["profile_id"],
                "keyword": run["keyword"],
                "analysis_status": run["analysis_status"],
                "report_markdown": report.get("markdown", ""),
                "source_coverage": run["source_coverage"],
                "completed_at": run["completed_at"],
            },
        )
        response.raise_for_status()

    async def _send_wecom(self, delivery: dict[str, Any], run: dict[str, Any]) -> None:
        session_id = str(delivery["target"].get("session_id") or "")
        report = run.get("report") or {}
        headers = {}
        if self.settings.flocks_api_key:
            headers["Authorization"] = f"Bearer {self.settings.flocks_api_key}"
        response = await self.client.post(
            f"{self.settings.flocks_base_url}/api/channel/session-send",
            json={
                "session_id": session_id,
                "channel_type": "wecom",
                "text": report.get("markdown", ""),
            },
            headers=headers,
        )
        response.raise_for_status()
