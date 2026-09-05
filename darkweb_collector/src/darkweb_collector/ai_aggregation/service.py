from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .adapters import (
    AnalysisResult,
    DeliveryAdapter,
    FlocksTaskCenterAdapter,
    MockAnalysisAdapter,
    extract_flocks_report,
    extract_source_coverage,
)
from .config import Settings
from .cron import CronExpression
from .repository import Repository, utc_now
from .schemas import normalize_keywords, render_prompt
from .timezone_utils import shanghai_timezone


MAX_REPORT_BYTES = 512 * 1024


class QueueCapacityError(RuntimeError):
    pass


class ProfileDisabledError(RuntimeError):
    pass


class ProfileOverlapError(RuntimeError):
    pass


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        *,
        analysis_adapter: MockAnalysisAdapter | FlocksTaskCenterAdapter | None = None,
        delivery_adapter: DeliveryAdapter | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self.analysis_adapter = analysis_adapter or (
            FlocksTaskCenterAdapter(settings)
            if settings.adapter_mode == "live"
            else MockAnalysisAdapter(settings)
        )
        self.delivery_adapter = delivery_adapter or DeliveryAdapter(settings)
        recovery_capacity = settings.max_queued_runs + settings.max_concurrent_runs
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=recovery_capacity)
        self.worker_tasks: list[asyncio.Task[None]] = []
        self.scheduler_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.settings.validate()
        self.repository.initialize()
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        self.worker_tasks = [
            asyncio.create_task(self._worker_loop(index), name=f"ai-aggregation-worker-{index}")
            for index in range(self.settings.max_concurrent_runs)
        ]
        recovery_limit = self.settings.max_queued_runs + self.settings.max_concurrent_runs
        for run_id in self.repository.pending_runs(recovery_limit):
            await self.queue.put(run_id)
        if self.settings.adapter_mode == "live":
            await self._best_effort_sync_all_live_schedules()
            self.scheduler_task = asyncio.create_task(
                self._live_schedule_loop(), name="ai-aggregation-flocks-schedule-reconciler"
            )
        else:
            self.scheduler_task = asyncio.create_task(
                self._mock_scheduler_loop(), name="ai-aggregation-mock-scheduler"
            )

    async def stop(self) -> None:
        tasks = [*self.worker_tasks]
        if self.scheduler_task:
            tasks.append(self.scheduler_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        close = getattr(self.analysis_adapter, "close", None)
        if close:
            await close()
        await self.delivery_adapter.close()

    def has_active_run(self, profile_id: str) -> bool:
        for run_status in ("queued", "running"):
            _, total = self.repository.list_runs(
                status=run_status, profile_id=profile_id, limit=1, offset=0
            )
            if total:
                return True
        return False

    async def enqueue_profile(
        self,
        profile_id: str,
        *,
        keyword_override: str | None = None,
        keywords_override: list[str] | None = None,
        search_window_days_override: int | None = None,
        trigger_type: str = "manual",
        scheduled_for: str | None = None,
    ) -> dict[str, Any]:
        profile = self.repository.get_profile(profile_id)
        if not profile:
            raise KeyError(profile_id)
        if not profile["enabled"]:
            raise ProfileDisabledError("profile is disabled")
        if trigger_type == "scheduled" and self.has_active_run(profile_id):
            raise ProfileOverlapError("this scheduled profile already has an active analysis")
        if self.queue.qsize() >= self.settings.max_queued_runs:
            raise QueueCapacityError(
                f"analysis queue is full (maximum {self.settings.max_queued_runs})"
            )
        profile = dict(profile)
        if keywords_override is not None:
            keywords = normalize_keywords(keywords_override)
        elif keyword_override:
            keywords = normalize_keywords([keyword_override])
        else:
            keywords = normalize_keywords(list(profile["keywords"]))
        search_window_days = int(
            search_window_days_override
            if search_window_days_override is not None
            else profile["search_window_days"]
        )
        profile["keywords"] = keywords
        profile["keyword"] = keywords[0]
        profile["search_window_days"] = search_window_days
        profile["rendered_prompt"] = render_prompt(
            profile["prompt_template"], keywords, search_window_days
        )
        run = self.repository.create_run(
            profile,
            trigger_type=trigger_type,
            scheduled_for=scheduled_for,
        )
        self.queue.put_nowait(run["id"])
        return run

    async def retry_deliveries(self, run_id: str) -> int:
        run = self.repository.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        if run["analysis_status"] != "succeeded" or not run["report"]:
            raise RuntimeError("deliveries can only be retried for a completed report")
        attempts = self.repository.pending_delivery_attempts(run_id, retry_failed=True)
        if not attempts:
            return 0
        await asyncio.gather(*(self._deliver_one(run, attempt) for attempt in attempts))
        return len(attempts)

    async def health(self) -> dict[str, Any]:
        adapter_health = await self.analysis_adapter.health()
        overall = "ok" if adapter_health.get("status") == "ready" else "degraded"
        return {
            "status": overall,
            "service": "ai-aggregation",
            "adapter": adapter_health,
            "delivery_mode": self.settings.delivery_mode,
            "workflow_id": self.settings.workflow_id,
            "queue": {
                "depth": self.queue.qsize(),
                "maximum": self.settings.max_queued_runs,
                "max_concurrent_runs": self.settings.max_concurrent_runs,
            },
            "runs": self.repository.runtime_counts(),
            "database_path": str(self.settings.database_path.resolve()),
            "reports_dir": str(self.settings.reports_dir.resolve()),
        }

    async def wait_until_idle(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self.queue.join(), timeout=timeout)

    async def _worker_loop(self, index: int) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                await self._process_run(run_id)
            finally:
                self.queue.task_done()

    async def _process_run(self, run_id: str) -> None:
        run = self.repository.get_run(run_id)
        if not run or run["analysis_status"] not in {"queued", "running"}:
            return
        self.repository.mark_run_running(run_id)
        run = self.repository.get_run(run_id) or run
        try:
            result = await self.analysis_adapter.generate(
                run,
                on_external_ids=lambda scheduler_id, execution_id: self.repository.set_flocks_ids(
                    run_id, scheduler_id, execution_id
                ),
            )
            await self._complete_with_result(run_id, result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.repository.fail_run(run_id, f"{type(exc).__name__}: {exc}")

    async def _complete_with_result(self, run_id: str, result: AnalysisResult) -> None:
        markdown_bytes = result.markdown.encode("utf-8")
        if len(markdown_bytes) > MAX_REPORT_BYTES:
            raise ValueError(f"report exceeds the {MAX_REPORT_BYTES // 1024} KiB report limit")
        report_path, digest = self._write_report(run_id, result.markdown)
        self.repository.complete_run(
            run_id,
            markdown=result.markdown,
            file_path=str(report_path.resolve()),
            sha256=digest,
            source_coverage=result.source_coverage,
            metadata=result.metadata,
            flocks_scheduler_id=result.flocks_scheduler_id,
            flocks_execution_id=result.flocks_execution_id,
        )
        completed_run = self.repository.get_run(run_id)
        if completed_run:
            attempts = self.repository.pending_delivery_attempts(run_id)
            await asyncio.gather(
                *(self._deliver_one(completed_run, attempt) for attempt in attempts)
            )

    def _write_report(self, run_id: str, markdown: str) -> tuple[Path, str]:
        today = datetime.now(shanghai_timezone()).strftime("%Y-%m-%d")
        directory = self.settings.reports_dir / today
        directory.mkdir(parents=True, exist_ok=True)
        report_path = directory / f"{run_id}.md"
        temporary_path = directory / f".{run_id}.tmp"
        payload = markdown.encode("utf-8")
        temporary_path.write_bytes(payload)
        temporary_path.replace(report_path)
        return report_path, hashlib.sha256(payload).hexdigest()

    async def _deliver_one(self, run: dict[str, Any], attempt: dict[str, Any]) -> None:
        self.repository.mark_delivery_sending(attempt["id"])
        try:
            await self.delivery_adapter.send(attempt, run)
        except Exception as exc:
            self.repository.finish_delivery(
                attempt["id"], success=False, error=f"{type(exc).__name__}: {exc}"
            )
        else:
            self.repository.finish_delivery(attempt["id"], success=True)

    async def _mock_scheduler_loop(self) -> None:
        while True:
            now = datetime.now(shanghai_timezone()).replace(second=0, microsecond=0)
            scheduled_for = now.isoformat()
            for profile in self.repository.list_scheduled_profiles():
                cron = profile["schedule"]["cron"]
                if not cron or not CronExpression.parse(cron).matches(now):
                    continue
                if not self.repository.claim_schedule(profile["id"], scheduled_for):
                    continue
                if self.has_active_run(profile["id"]):
                    continue
                try:
                    await self.enqueue_profile(
                        profile["id"],
                        trigger_type="scheduled",
                        scheduled_for=scheduled_for,
                    )
                except QueueCapacityError:
                    self.repository.release_schedule(profile["id"], scheduled_for)
                except (ProfileOverlapError, ProfileDisabledError):
                    pass
                except Exception:
                    self.repository.release_schedule(profile["id"], scheduled_for)
            await asyncio.sleep(self.settings.scheduler_poll_seconds)

    async def sync_profile_schedule(self, profile: dict[str, Any]) -> str | None:
        if self.settings.adapter_mode != "live":
            return None
        adapter = self.analysis_adapter
        if not isinstance(adapter, FlocksTaskCenterAdapter):
            return None
        with self.repository.connection() as connection:
            mapping = connection.execute(
                "SELECT * FROM ai_aggregation_flocks_profile_schedulers WHERE profile_id = ?",
                (profile["id"],),
            ).fetchone()
        schedule = profile["schedule"]
        should_enable = bool(profile["enabled"] and schedule["enabled"] and schedule["cron"])
        if not should_enable:
            if mapping:
                await self._post_flocks_scheduler_action(mapping["scheduler_id"], "disable")
            return mapping["scheduler_id"] if mapping else None

        context = {
            "query": profile["rendered_prompt"],
            "search_window_days": profile["search_window_days"],
            "_ai_aggregation": {
                "keywords": profile["keywords"],
                "prompt_template": profile["prompt_template"],
            },
            "include_sources": profile["sources"],
            "report_language": profile["language"],
            "delivery_targets": profile["deliveries"],
            "ai_aggregation_profile_id": profile["id"],
        }
        update_payload = {
            "title": f"AI聚合定时：{profile['name']}",
            "description": profile["rendered_prompt"],
            "priority": "normal",
            "executionMode": "workflow",
            "workflowID": self.settings.workflow_id,
            "agentName": "search-supervisor",
            "cron": schedule["cron"],
            "timezone": schedule["timezone"],
            "runOnce": False,
            "context": context,
            "tags": ["ai-aggregation", f"profile:{profile['id']}"],
        }
        signature = hashlib.sha256(
            json.dumps(update_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if mapping:
            response = await adapter.client.put(
                f"/api/task-schedulers/{mapping['scheduler_id']}", json=update_payload
            )
            if response.status_code == 404:
                mapping = None
            else:
                response.raise_for_status()
                await self._post_flocks_scheduler_action(mapping["scheduler_id"], "enable")
        if not mapping:
            response = await adapter.client.post(
                "/api/task-schedulers", json={"type": "scheduled", **update_payload}
            )
            response.raise_for_status()
            scheduler_id = response.json().get("id")
            if not scheduler_id:
                raise RuntimeError("Flocks did not return a scheduler id")
        else:
            scheduler_id = mapping["scheduler_id"]
        with self.repository.connection() as connection:
            connection.execute(
                """
                INSERT INTO ai_aggregation_flocks_profile_schedulers(profile_id, scheduler_id, config_signature, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET scheduler_id=excluded.scheduler_id,
                    config_signature=excluded.config_signature, updated_at=excluded.updated_at
                """,
                (profile["id"], scheduler_id, signature, utc_now()),
            )
            connection.commit()
        return scheduler_id

    async def disable_profile_schedule(self, profile_id: str) -> None:
        if self.settings.adapter_mode != "live":
            return
        with self.repository.connection() as connection:
            mapping = connection.execute(
                "SELECT scheduler_id FROM ai_aggregation_flocks_profile_schedulers WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if mapping:
            await self._post_flocks_scheduler_action(mapping["scheduler_id"], "disable")

    async def _post_flocks_scheduler_action(self, scheduler_id: str, action: str) -> None:
        adapter = self.analysis_adapter
        if not isinstance(adapter, FlocksTaskCenterAdapter):
            return
        response = await adapter.client.post(f"/api/task-schedulers/{scheduler_id}/{action}")
        if response.status_code != 404:
            response.raise_for_status()

    async def _best_effort_sync_all_live_schedules(self) -> None:
        for profile in self.repository.list_profiles():
            try:
                await self.sync_profile_schedule(profile)
            except Exception:
                continue

    async def _live_schedule_loop(self) -> None:
        while True:
            try:
                await self._reconcile_live_executions()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(self.settings.scheduler_poll_seconds)

    async def _reconcile_live_executions(self) -> None:
        adapter = self.analysis_adapter
        if not isinstance(adapter, FlocksTaskCenterAdapter):
            return
        with self.repository.connection() as connection:
            mappings = connection.execute(
                "SELECT profile_id, scheduler_id FROM ai_aggregation_flocks_profile_schedulers"
            ).fetchall()
        for mapping in mappings:
            profile = self.repository.get_profile(mapping["profile_id"])
            if not profile:
                continue
            response = await adapter.client.get(
                f"/api/task-schedulers/{mapping['scheduler_id']}/executions",
                params={"limit": 50, "offset": 0},
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            for execution in reversed(response.json().get("items") or []):
                if str(execution.get("status") or "").lower() not in {
                    "completed", "failed", "cancelled"
                }:
                    continue
                await self._import_live_execution(profile, mapping["scheduler_id"], execution)

    async def _import_live_execution(
        self,
        current_profile: dict[str, Any],
        scheduler_id: str,
        execution: dict[str, Any],
    ) -> None:
        execution_id = str(execution.get("id") or "")
        if not execution_id:
            return
        with self.repository.connection() as connection:
            existing = connection.execute(
                "SELECT run_id FROM ai_aggregation_imported_flocks_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if existing:
                return
            connection.execute(
                """
                INSERT INTO ai_aggregation_imported_flocks_executions(execution_id, profile_id, run_id, imported_at)
                VALUES (?, ?, NULL, ?)
                """,
                (execution_id, current_profile["id"], utc_now()),
            )
            connection.commit()

        run_id: str | None = None
        try:
            profile = self._profile_snapshot_from_execution(current_profile, execution)
            scheduled_for = (
                execution.get("queuedAt")
                or execution.get("createdAt")
                or f"flocks:{execution_id}"
            )
            run = self.repository.create_run(
                profile, trigger_type="scheduled", scheduled_for=str(scheduled_for)
            )
            run_id = run["id"]
            self.repository.mark_run_running(run_id)
            self.repository.set_flocks_ids(run_id, scheduler_id, execution_id)
            with self.repository.connection() as connection:
                connection.execute(
                    "UPDATE ai_aggregation_imported_flocks_executions SET run_id = ? WHERE execution_id = ?",
                    (run_id, execution_id),
                )
                connection.commit()
            run_status = str(execution.get("status") or "").lower()
            if run_status != "completed":
                raise RuntimeError(
                    execution.get("error")
                    or f"Flocks execution ended with status {run_status}"
                )
            markdown, extracted, parsed = extract_flocks_report(
                execution.get("resultSummary") or ""
            )
            if not markdown:
                raise RuntimeError("Flocks execution completed without a report")
            await self._complete_with_result(
                run_id,
                AnalysisResult(
                    markdown=markdown,
                    source_coverage=extract_source_coverage(parsed, profile["sources"]),
                    metadata={
                        "adapter": "live-scheduled-import",
                        "workflow_id": self.settings.workflow_id,
                        "report_extracted_from": extracted,
                    },
                    flocks_scheduler_id=scheduler_id,
                    flocks_execution_id=execution_id,
                ),
            )
        except Exception as exc:
            if run_id:
                self.repository.fail_run(run_id, f"{type(exc).__name__}: {exc}")
            else:
                with self.repository.connection() as connection:
                    connection.execute(
                        "DELETE FROM ai_aggregation_imported_flocks_executions WHERE execution_id = ?",
                        (execution_id,),
                    )
                    connection.commit()

    @staticmethod
    def _profile_snapshot_from_execution(
        profile: dict[str, Any], execution: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot = execution.get("executionInputSnapshot") or {}
        context = snapshot.get("context") or {}
        if not isinstance(context, dict):
            context = {}
        restored = dict(profile)
        ai_snapshot = context.get("_ai_aggregation") or {}
        if not isinstance(ai_snapshot, dict):
            ai_snapshot = {}
        raw_keywords = ai_snapshot.get("keywords")
        if isinstance(raw_keywords, list) and raw_keywords:
            keywords = normalize_keywords([str(item) for item in raw_keywords])
        else:
            keywords = normalize_keywords(list(profile["keywords"]))
        prompt_template = str(
            ai_snapshot.get("prompt_template") or profile["prompt_template"]
        )
        search_window_days = int(
            context.get("search_window_days") or profile["search_window_days"]
        )
        restored["keywords"] = keywords
        restored["keyword"] = keywords[0]
        restored["prompt_template"] = prompt_template
        restored["rendered_prompt"] = str(
            context.get("query")
            or render_prompt(prompt_template, keywords, search_window_days)
        )
        restored["search_window_days"] = search_window_days
        restored["sources"] = list(context.get("include_sources") or profile["sources"])
        restored["language"] = str(context.get("report_language") or profile["language"])
        if isinstance(context.get("delivery_targets"), list):
            restored["deliveries"] = context["delivery_targets"]
        return restored

