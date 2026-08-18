from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.ai_aggregation.adapters import FlocksTaskCenterAdapter
from darkweb_collector.ai_aggregation.config import Settings
from darkweb_collector.ai_aggregation.router import reset_service_for_tests, router


def _app(modules: list[str] | None = None) -> FastAPI:
    application = FastAPI()

    @application.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.current_user = {
            "role": "user",
            "modules": list(modules or ["ai_aggregation"]),
        }
        return await call_next(request)

    application.include_router(router)
    return application


def _wait_run(client: TestClient, run_id: str, timeout: float = 6.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/api/ai-aggregation/runs/{run_id}").json()
        if payload["analysis_status"] in {"succeeded", "failed"} and payload[
            "delivery_status"
        ] != "pending":
            return payload
        time.sleep(0.02)
    raise AssertionError("AI aggregation run did not finish")


def test_project_router_uses_shared_db_and_project_output(tmp_path: Path) -> None:
    db_path = tmp_path / "collector.db"
    output_path = tmp_path / "output"
    env = {
        "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
        "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_path),
        "DARKWEB_AI_AGGREGATION_MODE": "mock",
        "DARKWEB_AI_AGGREGATION_DELIVERY_MODE": "mock",
        "DARKWEB_AI_AGGREGATION_MOCK_DELAY_SECONDS": "0.15",
        "DARKWEB_AI_AGGREGATION_SCHEDULER_POLL_SECONDS": "100",
    }
    reset_service_for_tests()
    with patch.dict(os.environ, env, clear=False):
        with TestClient(_app()) as client:
            profile = client.post(
                "/api/ai-aggregation/profiles",
                json={
                    "name": "项目内聚合",
                    "keywords": ["默认关键词", "默认行业"],
                },
            ).json()
            assert profile["prompt_template"] == "搜索 {{keywords}} {{time_range}} 的威胁情报"
            assert profile["keyword"] == "默认关键词"
            assert profile["keywords"] == ["默认关键词", "默认行业"]
            assert profile["rendered_prompt"] == "搜索 默认关键词、默认行业 最近30天 的威胁情报"
            first = client.post(
                f"/api/ai-aggregation/profiles/{profile['id']}/run",
                json={"keywords": ["甲公司", "制造业"], "search_window_days": 7},
            )
            second = client.post(
                f"/api/ai-aggregation/profiles/{profile['id']}/run",
                json={"keyword": "乙公司"},
            )
            assert first.status_code == second.status_code == 202
            runs = [
                _wait_run(client, first.json()["run_id"]),
                _wait_run(client, second.json()["run_id"]),
            ]
            assert runs[0]["keyword"] == "甲公司"
            assert runs[0]["keywords"] == ["甲公司", "制造业"]
            assert runs[0]["search_window_days"] == 7
            assert runs[0]["rendered_prompt"] == "搜索 甲公司、制造业 最近7天 的威胁情报"
            assert runs[1]["keyword"] == "乙公司"
            assert runs[1]["keywords"] == ["乙公司"]
            assert runs[1]["search_window_days"] == 30
            unchanged = client.get(
                f"/api/ai-aggregation/profiles/{profile['id']}"
            ).json()
            assert unchanged["keywords"] == ["默认关键词", "默认行业"]
            history = client.get("/api/ai-aggregation/runs").json()["items"]
            assert {tuple(item["keywords"]) for item in history} == {
                ("甲公司", "制造业"),
                ("乙公司",),
            }
            for run in runs:
                report = run["report"]
                report_path = Path(report["file_path"])
                data = report_path.read_bytes()
                assert report_path.is_relative_to(output_path / "ai-aggregation" / "reports")
                assert hashlib.sha256(data).hexdigest() == report["sha256"]
            health = client.get("/api/ai-aggregation/health").json()
            assert health["queue"]["max_concurrent_runs"] == 2
            assert health["adapter"]["peak_active_runs"] == 2

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "ai_aggregation_profiles" in tables
    assert "ai_aggregation_runs" in tables
    assert not (tmp_path / "ai_aggregation.db").exists()


def test_router_requires_ai_aggregation_module(tmp_path: Path) -> None:
    reset_service_for_tests()
    with patch.dict(
        os.environ,
        {
            "DARKWEB_COLLECTOR_DB_PATH": str(tmp_path / "collector.db"),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(tmp_path / "output"),
        },
        clear=False,
    ):
        with TestClient(_app(modules=["ransomware"])) as client:
            response = client.get("/api/ai-aggregation/profiles")
            assert response.status_code == 403


def test_live_task_center_contract_extracts_report(tmp_path: Path) -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path == "/api/task-schedulers":
            return httpx.Response(201, json={"id": "scheduler-1"})
        if request.url.path == "/api/task-schedulers/scheduler-1/executions":
            return httpx.Response(200, json={"items": [{"id": "execution-1"}]})
        if request.url.path == "/api/task-schedulers/scheduler-1/disable":
            return httpx.Response(200, json={"status": "disabled"})
        if request.url.path == "/api/task-executions/execution-1":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "resultSummary": str(
                        {
                            "final_report": "# 项目内报告",
                            "source_coverage": {"darkweb": "completed"},
                        }
                    ),
                },
            )
        return httpx.Response(404)

    settings = Settings(
        database_path=tmp_path / "collector.db",
        reports_dir=tmp_path / "output" / "ai-aggregation" / "reports",
        adapter_mode="live",
        delivery_mode="mock",
        flocks_base_url="http://flocks.test",
        flocks_api_key="token",
        flocks_poll_interval_seconds=0.001,
        flocks_execution_timeout_seconds=1,
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://flocks.test"
    )
    adapter = FlocksTaskCenterAdapter(settings, client=client)
    run = {
        "id": "run-1",
        "keyword": "目标企业",
        "rendered_prompt": "搜索目标企业的威胁情报",
        "search_window_days": 30,
        "sources": ["darkweb", "telegram", "web"],
        "language": "zh-CN",
    }

    async def execute():
        try:
            return await adapter.generate(run)
        finally:
            await client.aclose()

    result = asyncio.run(execute())
    assert result.markdown == "# 项目内报告"
    create_payload = next(body for method, path, body in seen if path == "/api/task-schedulers")
    assert create_payload["type"] == "queued"
    assert create_payload["workflowID"] == "threat_intel_search_pipeline"
    assert create_payload["context"]["query"] == "搜索目标企业的威胁情报"
    assert create_payload["context"]["search_window_days"] == 30
    assert "keywords" not in create_payload["context"]
    assert "prompt_template" not in create_payload["context"]
    assert any(path.endswith("/disable") for _, path, _ in seen)


def test_live_delivery_configuration_is_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="FLOCKS_BASE_URL"):
        Settings(
            database_path=tmp_path / "collector.db",
            reports_dir=tmp_path / "reports",
            adapter_mode="mock",
            delivery_mode="live",
        ).validate()


def test_db_connect_initializes_all_ai_aggregation_tables(tmp_path: Path) -> None:
    from darkweb_collector.db import connect

    db_path = tmp_path / "collector.db"
    with connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    expected = {
        "ai_aggregation_profiles",
        "ai_aggregation_delivery_targets",
        "ai_aggregation_runs",
        "ai_aggregation_reports",
        "ai_aggregation_delivery_attempts",
        "ai_aggregation_schedule_claims",
        "ai_aggregation_flocks_profile_schedulers",
        "ai_aggregation_imported_flocks_executions",
    }
    assert expected.issubset(tables)


def test_live_base_url_must_be_a_safe_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute http"):
        Settings(
            database_path=tmp_path / "collector.db",
            reports_dir=tmp_path / "reports",
            adapter_mode="live",
            flocks_base_url="http://user:pass@127.0.0.1:8000/private?x=1",
            flocks_api_key="token",
        ).validate()



def test_legacy_keyword_rows_are_migrated_to_single_element_arrays(tmp_path: Path) -> None:
    from darkweb_collector.db import connect

    db_path = tmp_path / "legacy-collector.db"
    now = "2026-08-17T00:00:00+00:00"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE ai_aggregation_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                keyword TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                search_window_days INTEGER NOT NULL,
                sources_json TEXT NOT NULL,
                language TEXT NOT NULL,
                schedule_enabled INTEGER NOT NULL DEFAULT 0,
                cron TEXT,
                timezone TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE ai_aggregation_runs (
                id TEXT PRIMARY KEY,
                profile_id TEXT,
                profile_name TEXT NOT NULL,
                keyword TEXT NOT NULL,
                prompt_template TEXT NOT NULL,
                rendered_prompt TEXT NOT NULL,
                search_window_days INTEGER NOT NULL,
                sources_json TEXT NOT NULL,
                language TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                scheduled_for TEXT,
                analysis_status TEXT NOT NULL,
                delivery_status TEXT NOT NULL,
                source_coverage_json TEXT NOT NULL DEFAULT '{}',
                flocks_scheduler_id TEXT,
                flocks_execution_id TEXT,
                error TEXT,
                queued_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id, trigger_type, scheduled_for)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO ai_aggregation_profiles
            (id,name,keyword,enabled,search_window_days,sources_json,language,
             schedule_enabled,cron,timezone,created_at,updated_at)
            VALUES ('p1','legacy','旧关键词',1,30,'["darkweb"]','zh-CN',0,NULL,
                    'Asia/Shanghai',?,?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO ai_aggregation_runs
            (id,profile_id,profile_name,keyword,prompt_template,rendered_prompt,
             search_window_days,sources_json,language,trigger_type,scheduled_for,
             analysis_status,delivery_status,queued_at,updated_at)
            VALUES ('r1','p1','legacy','旧关键词','搜索{{keyword}}的威胁情报',
                    '搜索旧关键词的威胁情报',30,'["darkweb"]','zh-CN','manual',
                    NULL,'succeeded','not_configured',?,?)
            """,
            (now, now),
        )
        connection.commit()

    with connect(db_path) as connection:
        profile = connection.execute(
            "SELECT keyword,prompt_template,keywords_json FROM ai_aggregation_profiles WHERE id='p1'"
        ).fetchone()
        run = connection.execute(
            "SELECT keyword,keywords_json FROM ai_aggregation_runs WHERE id='r1'"
        ).fetchone()
    assert json.loads(profile["keywords_json"]) == ["旧关键词"]
    assert profile["prompt_template"] == "搜索 {{keywords}} {{time_range}} 的威胁情报"
    assert json.loads(run["keywords_json"]) == ["旧关键词"]


def test_prompt_template_requires_both_supported_variables() -> None:
    from darkweb_collector.ai_aggregation.schemas import ProfileInput

    with pytest.raises(ValueError, match="time_range"):
        ProfileInput(keywords=["能源"], prompt_template="搜索 {{keywords}} 的威胁情报")
    with pytest.raises(ValueError, match="unsupported"):
        ProfileInput(
            keywords=["能源"],
            prompt_template="搜索 {{keywords}} {{time_range}} {{unknown}}",
        )



def test_live_schedule_keeps_template_snapshot_namespaced(tmp_path: Path) -> None:
    from darkweb_collector.ai_aggregation.repository import Repository
    from darkweb_collector.ai_aggregation.schemas import ProfileInput
    from darkweb_collector.ai_aggregation.service import AnalysisService

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.method == "POST" and request.url.path == "/api/task-schedulers":
            seen.append(body)
            return httpx.Response(201, json={"id": "scheduled-template-1"})
        return httpx.Response(404)

    async def scenario() -> tuple[dict, int]:
        settings = Settings(
            database_path=tmp_path / "collector.db",
            reports_dir=tmp_path / "output" / "ai-aggregation" / "reports",
            adapter_mode="live",
            delivery_mode="mock",
            flocks_base_url="http://flocks.test",
            flocks_api_key="token",
        )
        repository = Repository(settings.database_path)
        repository.initialize()
        original = repository.create_profile(
            ProfileInput(
                name="旧模板",
                keywords=["能源", "制造业"],
                prompt_template="搜索 {{keywords}} 在 {{time_range}} 内的威胁情报",
                search_window_days=30,
                schedule={
                    "enabled": True,
                    "cron": "0 9 * * *",
                    "timezone": "Asia/Shanghai",
                },
            )
        )
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://flocks.test",
        )
        adapter = FlocksTaskCenterAdapter(settings, client=client)
        service = AnalysisService(settings, repository, analysis_adapter=adapter)
        try:
            scheduler_id = await service.sync_profile_schedule(original)
            payload = seen[0]
            context = payload["context"]
            assert scheduler_id == "scheduled-template-1"
            assert context["query"] == "搜索 能源、制造业 在 最近30天 内的威胁情报"
            assert context["search_window_days"] == 30
            assert "keywords" not in context
            assert "prompt_template" not in context
            assert context["_ai_aggregation"] == {
                "keywords": ["能源", "制造业"],
                "prompt_template": "搜索 {{keywords}} 在 {{time_range}} 内的威胁情报",
            }

            repository.update_profile(
                original["id"],
                ProfileInput(
                    name="新模板",
                    keywords=["新关键词"],
                    prompt_template="请分析 {{keywords}} 于 {{time_range}} 的威胁情报",
                    search_window_days=90,
                ),
            )
            current = repository.get_profile(original["id"])
            execution = {
                "id": "scheduled-execution-old-snapshot",
                "status": "completed",
                "queuedAt": "2026-08-17T01:00:00+00:00",
                "executionInputSnapshot": {"context": context},
                "resultSummary": str(
                    {
                        "final_report": "# 旧模板报告",
                        "source_coverage": {"darkweb": "completed"},
                    }
                ),
            }
            await service._import_live_execution(current, scheduler_id, execution)
            runs, total = repository.list_runs(limit=10)
            return runs[0], total
        finally:
            await service.delivery_adapter.close()
            await client.aclose()

    imported, total = asyncio.run(scenario())
    assert total == 1
    assert imported["keywords"] == ["能源", "制造业"]
    assert imported["keyword"] == "能源"
    assert imported["search_window_days"] == 30
    assert imported["prompt_template"] == "搜索 {{keywords}} 在 {{time_range}} 内的威胁情报"
    assert imported["rendered_prompt"] == "搜索 能源、制造业 在 最近30天 内的威胁情报"

