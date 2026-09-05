from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from darkweb_collector.db import (
    DATABASE_INTEGRITY_ERRORS,
    begin_write_transaction,
    connect,
    enable_foreign_keys,
)
from typing import Any, Iterator
from uuid import uuid4

from .schemas import PROMPT_TEMPLATE, ProfileInput, render_prompt


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Repository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def initialize(self) -> None:
        # darkweb_collector.db.connect owns schema initialization.
        with self.connection():
            pass

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # Reuse the collector's managed connection so WAL, WSL-mounted paths,
        # schema locking, busy timeouts, and close semantics stay consistent.
        with connect(self.database_path) as connection:
            enable_foreign_keys(connection)
            yield connection

    def create_profile(self, payload: ProfileInput) -> dict[str, Any]:
        profile_id = str(uuid4())
        now = utc_now()
        with self.connection() as connection:
            begin_write_transaction(connection)
            connection.execute(
                """
                INSERT INTO ai_aggregation_profiles
                (id, name, keyword, prompt_template, keywords_json, enabled,
                 search_window_days, sources_json, language, schedule_enabled,
                 cron, timezone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    payload.name,
                    payload.keyword,
                    payload.prompt_template,
                    _json(payload.keywords),
                    int(payload.enabled),
                    payload.search_window_days,
                    _json(payload.sources),
                    payload.language,
                    int(payload.schedule.enabled),
                    payload.schedule.cron,
                    payload.schedule.timezone,
                    now,
                    now,
                ),
            )
            self._replace_targets(connection, profile_id, payload, now)
            connection.commit()
        return self.get_profile(profile_id) or {}

    def update_profile(self, profile_id: str, payload: ProfileInput) -> dict[str, Any] | None:
        now = utc_now()
        with self.connection() as connection:
            begin_write_transaction(connection)
            cursor = connection.execute(
                """
                UPDATE ai_aggregation_profiles
                SET name = ?, keyword = ?, prompt_template = ?, keywords_json = ?,
                    enabled = ?, search_window_days = ?, sources_json = ?, language = ?,
                    schedule_enabled = ?, cron = ?, timezone = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.name,
                    payload.keyword,
                    payload.prompt_template,
                    _json(payload.keywords),
                    int(payload.enabled),
                    payload.search_window_days,
                    _json(payload.sources),
                    payload.language,
                    int(payload.schedule.enabled),
                    payload.schedule.cron,
                    payload.schedule.timezone,
                    now,
                    profile_id,
                ),
            )
            if cursor.rowcount == 0:
                connection.rollback()
                return None
            connection.execute("DELETE FROM ai_aggregation_delivery_targets WHERE profile_id = ?", (profile_id,))
            self._replace_targets(connection, profile_id, payload, now)
            connection.commit()
        return self.get_profile(profile_id)

    @staticmethod
    def _replace_targets(
        connection: sqlite3.Connection,
        profile_id: str,
        payload: ProfileInput,
        now: str,
    ) -> None:
        for target in payload.deliveries:
            target_id = str(uuid4())
            config = {"url": target.url} if target.type == "callback" else {
                "session_id": target.session_id
            }
            connection.execute(
                """
                INSERT INTO ai_aggregation_delivery_targets
                (id, profile_id, target_type, display_name, enabled, config_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    profile_id,
                    target.type,
                    target.display_name or ("报告回调" if target.type == "callback" else "企业微信"),
                    int(target.enabled),
                    _json(config),
                    now,
                ),
            )

    def list_profiles(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_aggregation_profiles ORDER BY created_at DESC"
            ).fetchall()
            return [self._profile_payload(connection, row) for row in rows]

    def list_scheduled_profiles(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM ai_aggregation_profiles
                WHERE enabled = 1 AND schedule_enabled = 1 AND cron IS NOT NULL
                ORDER BY created_at
                """
            ).fetchall()
            return [self._profile_payload(connection, row) for row in rows]

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM ai_aggregation_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            return self._profile_payload(connection, row) if row else None

    def set_profile_enabled(self, profile_id: str, enabled: bool) -> dict[str, Any] | None:
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE ai_aggregation_profiles SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), utc_now(), profile_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM ai_aggregation_profiles WHERE id = ?", (profile_id,))
            connection.execute("DELETE FROM ai_aggregation_schedule_claims WHERE profile_id = ?", (profile_id,))
            connection.commit()
            return cursor.rowcount > 0

    def _profile_payload(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        targets = connection.execute(
            "SELECT * FROM ai_aggregation_delivery_targets WHERE profile_id = ? ORDER BY created_at",
            (row["id"],),
        ).fetchall()
        deliveries = []
        for target in targets:
            config = json.loads(target["config_json"])
            deliveries.append(
                {
                    "id": target["id"],
                    "type": target["target_type"],
                    "display_name": target["display_name"],
                    "enabled": bool(target["enabled"]),
                    **config,
                }
            )
        legacy_keyword = str(row["keyword"] or "").strip()
        try:
            keywords = json.loads(row["keywords_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            keywords = []
        if not isinstance(keywords, list) or not keywords:
            keywords = [legacy_keyword] if legacy_keyword else []
        keywords = [str(item).strip() for item in keywords if str(item).strip()]
        keyword = keywords[0] if keywords else legacy_keyword
        prompt_template = str(row["prompt_template"] or PROMPT_TEMPLATE)
        return {
            "id": row["id"],
            "name": row["name"],
            "keyword": keyword,
            "keywords": keywords,
            "enabled": bool(row["enabled"]),
            "prompt_template": prompt_template,
            "rendered_prompt": render_prompt(
                prompt_template, keywords, int(row["search_window_days"])
            ),
            "search_window_days": row["search_window_days"],
            "sources": json.loads(row["sources_json"]),
            "language": row["language"],
            "schedule": {
                "enabled": bool(row["schedule_enabled"]),
                "cron": row["cron"],
                "timezone": row["timezone"],
            },
            "deliveries": deliveries,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def claim_schedule(self, profile_id: str, scheduled_for: str) -> bool:
        with self.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO ai_aggregation_schedule_claims(profile_id, scheduled_for, created_at) VALUES (?, ?, ?)",
                    (profile_id, scheduled_for, utc_now()),
                )
                connection.commit()
                return True
            except DATABASE_INTEGRITY_ERRORS:
                connection.rollback()
                return False

    def release_schedule(self, profile_id: str, scheduled_for: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM ai_aggregation_schedule_claims WHERE profile_id = ? AND scheduled_for = ?",
                (profile_id, scheduled_for),
            )
            connection.commit()

    def create_run(
        self,
        profile: dict[str, Any],
        *,
        trigger_type: str,
        scheduled_for: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        now = utc_now()
        enabled_targets = [target for target in profile["deliveries"] if target["enabled"]]
        delivery_status = "pending" if enabled_targets else "not_configured"
        with self.connection() as connection:
            begin_write_transaction(connection)
            connection.execute(
                """
                INSERT INTO ai_aggregation_runs
                (id, profile_id, profile_name, keyword, keywords_json, prompt_template,
                 rendered_prompt, search_window_days, sources_json, language, trigger_type,
                 scheduled_for, analysis_status, delivery_status, queued_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    run_id,
                    profile["id"],
                    profile["name"],
                    profile["keyword"],
                    _json(profile["keywords"]),
                    profile["prompt_template"],
                    profile["rendered_prompt"],
                    profile["search_window_days"],
                    _json(profile["sources"]),
                    profile["language"],
                    trigger_type,
                    scheduled_for,
                    delivery_status,
                    now,
                    now,
                ),
            )
            for target in enabled_targets:
                config = {"url": target.get("url")} if target["type"] == "callback" else {
                    "session_id": target.get("session_id")
                }
                connection.execute(
                    """
                    INSERT INTO ai_aggregation_delivery_attempts
                    (id, run_id, target_id, target_type, display_name, target_config_json,
                     status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        str(uuid4()),
                        run_id,
                        target["id"],
                        target["type"],
                        target["display_name"],
                        _json(config),
                        now,
                    ),
                )
            connection.commit()
        return self.get_run(run_id) or {}

    def list_runs(
        self,
        *,
        status: str | None = None,
        profile_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("analysis_status = ?")
            values.append(status)
        if profile_id:
            clauses.append("profile_id = ?")
            values.append(profile_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM ai_aggregation_runs{where}", values
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM ai_aggregation_runs{where} ORDER BY queued_at DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
            items = [self._run_payload(connection, row, include_markdown=False) for row in rows]
        return items, int(total)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM ai_aggregation_runs WHERE id = ?", (run_id,)).fetchone()
            return self._run_payload(connection, row, include_markdown=True) if row else None

    def _run_payload(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        include_markdown: bool,
    ) -> dict[str, Any]:
        report_row = connection.execute(
            "SELECT * FROM ai_aggregation_reports WHERE run_id = ?", (row["id"],)
        ).fetchone()
        report = None
        if report_row:
            report = {
                "id": report_row["id"],
                "file_path": report_row["file_path"],
                "sha256": report_row["sha256"],
                "generated_at": report_row["generated_at"],
                "metadata": json.loads(report_row["metadata_json"]),
            }
            if include_markdown:
                report["markdown"] = report_row["markdown"]
            else:
                report["excerpt"] = report_row["markdown"][:240]
        delivery_rows = connection.execute(
            "SELECT * FROM ai_aggregation_delivery_attempts WHERE run_id = ? ORDER BY created_at",
            (row["id"],),
        ).fetchall()
        deliveries = [self._delivery_payload(item) for item in delivery_rows]
        return {
            "id": row["id"],
            "profile_id": row["profile_id"],
            "profile_name": row["profile_name"],
            "keyword": row["keyword"],
            "keywords": json.loads(row["keywords_json"] or "[]") or [row["keyword"]],
            "prompt_template": row["prompt_template"],
            "rendered_prompt": row["rendered_prompt"],
            "search_window_days": row["search_window_days"],
            "sources": json.loads(row["sources_json"]),
            "language": row["language"],
            "trigger_type": row["trigger_type"],
            "scheduled_for": row["scheduled_for"],
            "analysis_status": row["analysis_status"],
            "delivery_status": row["delivery_status"],
            "source_coverage": json.loads(row["source_coverage_json"]),
            "flocks_scheduler_id": row["flocks_scheduler_id"],
            "flocks_execution_id": row["flocks_execution_id"],
            "error": row["error"],
            "queued_at": row["queued_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
            "report": report,
            "deliveries": deliveries,
        }

    @staticmethod
    def _delivery_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "target_id": row["target_id"],
            "type": row["target_type"],
            "display_name": row["display_name"],
            "target": json.loads(row["target_config_json"]),
            "status": row["status"],
            "attempt_count": row["attempt_count"],
            "last_error": row["last_error"],
            "last_attempted_at": row["last_attempted_at"],
            "delivered_at": row["delivered_at"],
        }

    def mark_run_running(self, run_id: str) -> None:
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE ai_aggregation_runs SET analysis_status = 'running', started_at = COALESCE(started_at, ?),
                    error = NULL, updated_at = ? WHERE id = ?
                """,
                (now, now, run_id),
            )
            connection.commit()

    def set_flocks_ids(self, run_id: str, scheduler_id: str, execution_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE ai_aggregation_runs SET flocks_scheduler_id = ?, flocks_execution_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (scheduler_id, execution_id, utc_now(), run_id),
            )
            connection.commit()

    def complete_run(
        self,
        run_id: str,
        *,
        markdown: str,
        file_path: str,
        sha256: str,
        source_coverage: dict[str, str],
        metadata: dict[str, Any],
        flocks_scheduler_id: str | None = None,
        flocks_execution_id: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connection() as connection:
            begin_write_transaction(connection)
            connection.execute(
                """
                INSERT INTO ai_aggregation_reports
                (id, run_id, markdown, file_path, sha256, generated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET markdown=excluded.markdown,
                    file_path=excluded.file_path, sha256=excluded.sha256,
                    generated_at=excluded.generated_at, metadata_json=excluded.metadata_json
                """,
                (str(uuid4()), run_id, markdown, file_path, sha256, now, _json(metadata)),
            )
            connection.execute(
                """
                UPDATE ai_aggregation_runs
                SET analysis_status = 'succeeded', source_coverage_json = ?,
                    flocks_scheduler_id = COALESCE(?, flocks_scheduler_id),
                    flocks_execution_id = COALESCE(?, flocks_execution_id),
                    error = NULL, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _json(source_coverage),
                    flocks_scheduler_id,
                    flocks_execution_id,
                    now,
                    now,
                    run_id,
                ),
            )
            connection.commit()

    def fail_run(self, run_id: str, error: str) -> None:
        now = utc_now()
        with self.connection() as connection:
            begin_write_transaction(connection)
            connection.execute(
                """
                UPDATE ai_aggregation_runs SET analysis_status = 'failed', delivery_status = 'not_attempted',
                    error = ?, completed_at = ?, updated_at = ? WHERE id = ?
                """,
                (error[:4000], now, now, run_id),
            )
            connection.execute(
                """
                UPDATE ai_aggregation_delivery_attempts SET status = 'skipped', last_error = ?
                WHERE run_id = ? AND status IN ('pending', 'sending')
                """,
                ("analysis failed; delivery was not attempted", run_id),
            )
            connection.commit()

    def pending_runs(self, limit: int) -> list[str]:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE ai_aggregation_runs SET analysis_status = 'queued', started_at = NULL,
                    error = 'recovered after service restart', updated_at = ?
                WHERE analysis_status = 'running'
                """,
                (utc_now(),),
            )
            connection.commit()
            rows = connection.execute(
                "SELECT id FROM ai_aggregation_runs WHERE analysis_status = 'queued' ORDER BY queued_at LIMIT ?",
                (limit,),
            ).fetchall()
            return [row["id"] for row in rows]

    def pending_delivery_attempts(self, run_id: str, *, retry_failed: bool = False) -> list[dict[str, Any]]:
        statuses = ("pending", "failed") if retry_failed else ("pending",)
        placeholders = ",".join("?" for _ in statuses)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM ai_aggregation_delivery_attempts
                WHERE run_id = ? AND status IN ({placeholders}) ORDER BY created_at
                """,
                (run_id, *statuses),
            ).fetchall()
            return [self._delivery_payload(row) for row in rows]

    def mark_delivery_sending(self, attempt_id: str) -> None:
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE ai_aggregation_delivery_attempts SET status = 'sending', attempt_count = attempt_count + 1,
                    last_attempted_at = ?, last_error = NULL WHERE id = ?
                """,
                (now, attempt_id),
            )
            connection.commit()

    def finish_delivery(self, attempt_id: str, *, success: bool, error: str = "") -> None:
        now = utc_now()
        with self.connection() as connection:
            begin_write_transaction(connection)
            row = connection.execute(
                "SELECT run_id FROM ai_aggregation_delivery_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if not row:
                connection.rollback()
                return
            connection.execute(
                """
                UPDATE ai_aggregation_delivery_attempts
                SET status = ?, last_error = ?, delivered_at = ?
                WHERE id = ?
                """,
                (
                    "succeeded" if success else "failed",
                    None if success else error[:4000],
                    now if success else None,
                    attempt_id,
                ),
            )
            self._refresh_delivery_status(connection, row["run_id"])
            connection.commit()

    @staticmethod
    def _refresh_delivery_status(connection: sqlite3.Connection, run_id: str) -> None:
        rows = connection.execute(
            "SELECT status FROM ai_aggregation_delivery_attempts WHERE run_id = ?", (run_id,)
        ).fetchall()
        statuses = [row["status"] for row in rows]
        if not statuses:
            status = "not_configured"
        elif any(value in {"pending", "sending"} for value in statuses):
            status = "pending"
        elif all(value == "succeeded" for value in statuses):
            status = "succeeded"
        elif any(value == "succeeded" for value in statuses):
            status = "partial"
        else:
            status = "failed"
        connection.execute(
            "UPDATE ai_aggregation_runs SET delivery_status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now(), run_id),
        )

    def runtime_counts(self) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT analysis_status, COUNT(*) AS count FROM ai_aggregation_runs GROUP BY analysis_status"
            ).fetchall()
            counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
            counts.update({row["analysis_status"]: row["count"] for row in rows})
            return counts
