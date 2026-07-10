from __future__ import annotations

from calendar import monthrange
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha1
import json
import os
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from darkweb_collector.bot_assistant import build_markdown_payload, load_bot_config, post_bot_payload
from darkweb_collector.db import get_db_connection
from darkweb_collector.monitoring_rules import enrich_events
from darkweb_collector.normalized_intelligence import load_normalized_events
from darkweb_collector.utils import utc_now_iso


SLA_MINUTES = 30
FINAL_VERIFICATION_STATUSES = {"verified", "false_positive", "monitoring"}
VALID_VERIFICATION_STATUSES = {"pending", *FINAL_VERIFICATION_STATUSES}
VALID_CONFIDENCE_LEVELS = {"high", "medium", "low"}

MONITORING_PLATFORMS = (
    {
        "key": "changan-night-city",
        "name": "长安不夜城",
        "kind": "暗网论坛",
        "environment": "DARKWEB_CHANGAN_CONNECTOR_URL",
        "tokenEnvironment": "DARKWEB_CHANGAN_CONNECTOR_TOKEN",
        "configurationHint": "配置论坛登录会话或连接器地址后接入。",
    },
    {
        "key": "xss",
        "name": "XSS",
        "kind": "数据交易论坛",
        "environment": "DARKWEB_XSS_CONNECTOR_URL",
        "tokenEnvironment": "DARKWEB_XSS_CONNECTOR_TOKEN",
        "configurationHint": "配置授权账号会话或连接器地址后接入。",
    },
    {
        "key": "breachforums",
        "name": "BreachForums",
        "kind": "数据交易论坛",
        "environment": "DARKWEB_BREACHFORUMS_CONNECTOR_URL",
        "tokenEnvironment": "DARKWEB_BREACHFORUMS_CONNECTOR_TOKEN",
        "configurationHint": "配置可用域名、授权会话或连接器地址后接入。",
    },
    {
        "key": "telegram",
        "name": "Telegram",
        "kind": "即时通信软件",
        "environment": "DARKWEB_TELEGRAM_CONNECTOR_URL",
        "tokenEnvironment": "DARKWEB_TELEGRAM_CONNECTOR_TOKEN",
        "configurationHint": "配置合规账号、频道清单和连接器地址后接入。",
    },
)

PLATFORM_NAME_BY_KEY = {item["key"]: item["name"] for item in MONITORING_PLATFORMS}
PLATFORM_KEY_BY_NAME = {item["name"].lower(): item["key"] for item in MONITORING_PLATFORMS}
PLATFORM_ALIASES = {
    "长安不夜城": "长安不夜城",
    "changan-night-city": "长安不夜城",
    "xss": "XSS",
    "xss.is": "XSS",
    "breachforums": "BreachForums",
    "breached": "BreachForums",
    "telegram": "Telegram",
    "tg": "Telegram",
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


def _parse_datetime(value: Any) -> datetime | None:
    raw = _normalize_text(value)
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _platform_name(value: Any) -> str:
    raw = _normalize_text(value)
    if not raw:
        return "未知平台"
    alias = PLATFORM_ALIASES.get(raw.lower()) or PLATFORM_ALIASES.get(raw)
    return alias or raw


def _confidence_level(event: dict[str, Any]) -> str:
    score = int(event.get("confidence_score") or event.get("rule_risk_score") or event.get("risk_score") or 0)
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _threat_type(event: dict[str, Any]) -> str:
    raw = _normalize_text(event.get("leak_type") or event.get("category"))
    if raw:
        return raw
    event_type = _normalize_text(event.get("event_type"))
    return {
        "data_leak": "数据售卖",
        "ransomware": "扬言攻击",
        "forum_topic": "数据售卖",
    }.get(event_type, "待研判")


def _suggested_action(threat_type: str, confidence_level: str) -> str:
    normalized = _normalize_text(threat_type)
    if any(token in normalized for token in ("售卖", "泄露", "数据库", "凭证", "源码")):
        action = "核验样本真实性和数据归属，固定证据并通知关联单位开展泄露排查。"
    elif any(token in normalized for token in ("勒索", "攻击", "入侵", "扬言")):
        action = "核查目标单位外网暴露与近期异常，保全原始内容并启动事件跟踪。"
    else:
        action = "复核来源可信度和目标关联性，保全证据后交由责任单位研判。"
    if confidence_level == "low":
        return f"当前置信度较低，先开展交叉验证；{action}"
    return action


def _first_resource_url(resources: Any) -> str:
    for item in resources if isinstance(resources, list) else []:
        if isinstance(item, dict):
            url = _normalize_text(item.get("url") or item.get("path"))
        else:
            url = _normalize_text(item)
        if url:
            return url
    return ""


def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "monitoring_matches": event.get("monitoring_matches") or [],
        "risk_reasons": event.get("risk_reasons") or [],
        "risk_score": int(event.get("rule_risk_score") or event.get("risk_score") or 0),
        "source_kind": event.get("source_kind") or "",
        "raw_source_type": event.get("raw_source_type") or "",
    }


def _upsert_case(connection, payload: dict[str, Any]) -> int:
    connection.execute(
        """
        INSERT INTO darkweb_monitoring_cases (
            event_id, source_platform, source_url, threat_title, threat_type,
            target_name, target_industry, discovered_at, first_detected_at,
            sla_due_at, verification_status, confidence_level, suggested_action,
            screenshot_url, screenshot_compliant, content_excerpt, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            source_platform = excluded.source_platform,
            source_url = excluded.source_url,
            threat_title = excluded.threat_title,
            threat_type = CASE WHEN darkweb_monitoring_cases.threat_type IN ('', '待研判') THEN excluded.threat_type ELSE darkweb_monitoring_cases.threat_type END,
            target_name = CASE WHEN darkweb_monitoring_cases.target_name = '' THEN excluded.target_name ELSE darkweb_monitoring_cases.target_name END,
            target_industry = CASE WHEN darkweb_monitoring_cases.target_industry = '' THEN excluded.target_industry ELSE darkweb_monitoring_cases.target_industry END,
            discovered_at = excluded.discovered_at,
            confidence_level = CASE WHEN darkweb_monitoring_cases.verification_status = 'pending' THEN excluded.confidence_level ELSE darkweb_monitoring_cases.confidence_level END,
            suggested_action = CASE WHEN darkweb_monitoring_cases.suggested_action = '' THEN excluded.suggested_action ELSE darkweb_monitoring_cases.suggested_action END,
            screenshot_url = CASE WHEN darkweb_monitoring_cases.screenshot_url = '' THEN excluded.screenshot_url ELSE darkweb_monitoring_cases.screenshot_url END,
            content_excerpt = CASE WHEN excluded.content_excerpt <> '' THEN excluded.content_excerpt ELSE darkweb_monitoring_cases.content_excerpt END,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            payload["event_id"],
            payload["source_platform"],
            payload.get("source_url") or "",
            payload["threat_title"],
            payload.get("threat_type") or "待研判",
            payload.get("target_name") or "",
            payload.get("target_industry") or "",
            payload["discovered_at"],
            payload["first_detected_at"],
            payload["sla_due_at"],
            payload.get("verification_status") or "pending",
            payload.get("confidence_level") or "medium",
            payload.get("suggested_action") or "",
            payload.get("screenshot_url") or "",
            int(bool(payload.get("screenshot_compliant"))),
            payload.get("content_excerpt") or "",
            _json_dumps(payload.get("metadata") or {}),
            payload["created_at"],
            payload["updated_at"],
        ),
    )
    row = connection.execute(
        "SELECT id FROM darkweb_monitoring_cases WHERE event_id = ?",
        (payload["event_id"],),
    ).fetchone()
    return int(row["id"])


def sync_cases_from_normalized_events(connection) -> int:
    events = enrich_events(connection, load_normalized_events(connection))
    now = datetime.now(timezone.utc)
    created = 0
    for event in events:
        if not event.get("monitoring_matches"):
            continue
        event_id = _normalize_text(event.get("event_id"))
        title = _normalize_text(event.get("title"))
        if not event_id or not title:
            continue
        exists = connection.execute(
            "SELECT id FROM darkweb_monitoring_cases WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        confidence = _confidence_level(event)
        first_detected = now
        payload = {
            "event_id": event_id,
            "source_platform": _platform_name(event.get("source_site_name")),
            "source_url": _normalize_text(event.get("source_url")),
            "threat_title": title,
            "threat_type": _threat_type(event),
            "target_name": _normalize_text(event.get("victim")),
            "target_industry": _normalize_text(event.get("industry")),
            "discovered_at": _normalize_text(event.get("disclosure_time") or event.get("updated_at")) or _iso(now),
            "first_detected_at": _iso(first_detected),
            "sla_due_at": _iso(first_detected + timedelta(minutes=SLA_MINUTES)),
            "verification_status": "pending",
            "confidence_level": confidence,
            "suggested_action": _suggested_action(_threat_type(event), confidence),
            "screenshot_url": _first_resource_url(event.get("screenshot_resources")),
            "screenshot_compliant": False,
            "content_excerpt": _normalize_text(event.get("detail_text"))[:1200],
            "metadata": _event_metadata(event),
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        _upsert_case(connection, payload)
        if exists is None:
            created += 1
    connection.commit()
    return created


def ingest_finding(payload: dict[str, Any]) -> dict[str, Any]:
    raw_platform = _normalize_text(payload.get("source_platform") or payload.get("platform"))
    platform_key = raw_platform.lower()
    if platform_key in PLATFORM_NAME_BY_KEY:
        platform_name = PLATFORM_NAME_BY_KEY[platform_key]
    else:
        resolved_key = PLATFORM_KEY_BY_NAME.get(platform_key)
        if not resolved_key:
            raise ValueError("source_platform must be one of: 长安不夜城, XSS, BreachForums, Telegram")
        platform_name = PLATFORM_NAME_BY_KEY[resolved_key]
    title = _normalize_text(payload.get("title") or payload.get("threat_title"))
    if not title:
        raise ValueError("title is required")
    now = datetime.now(timezone.utc)
    source_url = _normalize_text(payload.get("source_url"))
    discovered_at = _parse_datetime(payload.get("discovered_at")) or now
    confidence = _normalize_text(payload.get("confidence_level")).lower() or "medium"
    if confidence not in VALID_CONFIDENCE_LEVELS:
        raise ValueError("confidence_level must be high, medium, or low")
    event_id = _normalize_text(payload.get("event_id"))
    if not event_id:
        fingerprint = f"{platform_name}|{source_url}|{title}|{_iso(discovered_at)}"
        event_id = f"connector:{sha1(fingerprint.encode('utf-8')).hexdigest()}"
    threat_type = _normalize_text(payload.get("threat_type")) or "待研判"
    case_payload = {
        "event_id": event_id,
        "source_platform": platform_name,
        "source_url": source_url,
        "threat_title": title,
        "threat_type": threat_type,
        "target_name": _normalize_text(payload.get("target_name")),
        "target_industry": _normalize_text(payload.get("target_industry")),
        "discovered_at": _iso(discovered_at),
        "first_detected_at": _iso(now),
        "sla_due_at": _iso(now + timedelta(minutes=SLA_MINUTES)),
        "verification_status": "pending",
        "confidence_level": confidence,
        "suggested_action": _normalize_text(payload.get("suggested_action")) or _suggested_action(threat_type, confidence),
        "screenshot_url": _normalize_text(payload.get("screenshot_url")),
        "screenshot_compliant": bool(payload.get("screenshot_compliant", False)),
        "content_excerpt": _normalize_text(payload.get("content_excerpt"))[:1200],
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "created_at": _iso(now),
        "updated_at": _iso(now),
    }
    with get_db_connection() as connection:
        case_id = _upsert_case(connection, case_payload)
        connection.commit()
        return get_case_payload(connection, case_id)


def _sla_fields(row: dict[str, Any], *, now: datetime | None = None) -> tuple[str, int]:
    current = now or datetime.now(timezone.utc)
    due = _parse_datetime(row.get("sla_due_at")) or current
    verified = _parse_datetime(row.get("verified_at"))
    if verified is not None:
        return ("completed" if verified <= due else "breached"), int((due - verified).total_seconds() // 60)
    remaining = int((due - current).total_seconds() // 60)
    return ("pending" if remaining >= 0 else "breached"), remaining


def _case_payload(row: dict[str, Any]) -> dict[str, Any]:
    sla_status, remaining = _sla_fields(row)
    return {
        "id": int(row["id"]),
        "eventId": row.get("event_id") or "",
        "title": row.get("threat_title") or "",
        "sourcePlatform": row.get("source_platform") or "未知平台",
        "sourceUrl": row.get("source_url") or "",
        "threatType": row.get("threat_type") or "待研判",
        "targetName": row.get("target_name") or "待确认",
        "targetIndustry": row.get("target_industry") or "待确认",
        "discoveredAt": row.get("discovered_at") or "",
        "firstDetectedAt": row.get("first_detected_at") or "",
        "slaDueAt": row.get("sla_due_at") or "",
        "slaStatus": sla_status,
        "slaMinutesRemaining": remaining,
        "verificationStatus": row.get("verification_status") or "pending",
        "verifiedAt": row.get("verified_at") or "",
        "catalogedAt": row.get("cataloged_at") or "",
        "catalogStatus": row.get("catalog_status") or "unfiled",
        "catalogNumber": row.get("catalog_number") or "",
        "reviewer": row.get("reviewer") or "",
        "confidenceLevel": row.get("confidence_level") or "medium",
        "suggestedAction": row.get("suggested_action") or "",
        "disposition": row.get("disposition") or "",
        "note": row.get("note") or "",
        "screenshotUrl": row.get("screenshot_url") or "",
        "screenshotCompliant": bool(row.get("screenshot_compliant")),
        "contentExcerpt": row.get("content_excerpt") or "",
        "pushedAt": row.get("pushed_at") or "",
        "slaAlertedAt": row.get("sla_alerted_at") or "",
        "metadata": _json_loads(row.get("metadata_json"), {}),
    }


def get_case_payload(connection, case_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM darkweb_monitoring_cases WHERE id = ?",
        (int(case_id),),
    ).fetchone()
    if row is None:
        raise KeyError(case_id)
    return _case_payload(dict(row))


def list_cases_payload(connection, *, limit: int = 500) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM darkweb_monitoring_cases
        ORDER BY datetime(first_detected_at) DESC, id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 2000)),),
    ).fetchall()
    return [_case_payload(dict(row)) for row in rows]


def review_case(case_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    status = _normalize_text(payload.get("verification_status")).lower()
    if status not in VALID_VERIFICATION_STATUSES:
        raise ValueError("verification_status is invalid")
    confidence = _normalize_text(payload.get("confidence_level")).lower() or "medium"
    if confidence not in VALID_CONFIDENCE_LEVELS:
        raise ValueError("confidence_level must be high, medium, or low")
    now = utc_now_iso()
    completed = status in FINAL_VERIFICATION_STATUSES
    with get_db_connection() as connection:
        existing = connection.execute(
            "SELECT id, catalog_number FROM darkweb_monitoring_cases WHERE id = ?",
            (int(case_id),),
        ).fetchone()
        if existing is None:
            raise KeyError(case_id)
        if status == "false_positive":
            catalog_status = "excluded"
            catalog_number = ""
        elif completed:
            catalog_status = "cataloged"
            catalog_number = _normalize_text(existing["catalog_number"]) or f"XZ-DW-{datetime.now(timezone.utc):%Y%m%d}-{int(case_id):06d}"
        else:
            catalog_status = "unfiled"
            catalog_number = ""
        connection.execute(
            """
            UPDATE darkweb_monitoring_cases SET
                verification_status = ?,
                confidence_level = ?,
                target_name = ?,
                target_industry = ?,
                threat_type = ?,
                suggested_action = ?,
                screenshot_compliant = ?,
                reviewer = ?,
                disposition = ?,
                note = ?,
                verified_at = CASE WHEN ? THEN COALESCE(verified_at, ?) ELSE NULL END,
                cataloged_at = CASE WHEN ? THEN COALESCE(cataloged_at, ?) ELSE NULL END,
                catalog_status = ?,
                catalog_number = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                confidence,
                _normalize_text(payload.get("target_name")),
                _normalize_text(payload.get("target_industry")),
                _normalize_text(payload.get("threat_type")) or "待研判",
                _normalize_text(payload.get("suggested_action")),
                int(bool(payload.get("screenshot_compliant"))),
                _normalize_text(payload.get("reviewer")),
                _normalize_text(payload.get("disposition")),
                _normalize_text(payload.get("note")),
                completed,
                now,
                completed,
                now,
                catalog_status,
                catalog_number,
                now,
                int(case_id),
            ),
        )
        connection.commit()
        return get_case_payload(connection, case_id)


def build_case_markdown(case: dict[str, Any]) -> str:
    screenshot = "无"
    if case.get("screenshotUrl") and case.get("screenshotCompliant"):
        screenshot = f"[查看合规截图]({case['screenshotUrl']})"
    elif case.get("screenshotUrl"):
        screenshot = "已留存，尚未完成合规处理，未附图"
    confidence = {"high": "高", "medium": "中", "low": "低"}.get(case.get("confidenceLevel"), "中")
    return "\n".join(
        [
            "# 暗网威胁监测告警",
            f"> **威胁标题：** {case.get('title') or '未命名威胁'}",
            f"> **来源平台/网址：** {case.get('sourcePlatform') or '未知'} / {case.get('sourceUrl') or '未提供'}",
            f"> **威胁类型：** {case.get('threatType') or '待研判'}",
            f"> **关联目标：** {case.get('targetName') or '待确认'} / {case.get('targetIndustry') or '待确认'}",
            f"> **发现时间：** {case.get('firstDetectedAt') or case.get('discoveredAt') or '未知'}",
            f"> **原始内容截图：** {screenshot}",
            f"> **初步置信度：** {confidence}",
            f"> **建议处置方向：** {case.get('suggestedAction') or '请尽快开展人工复核'}",
            f"> **初步验证状态：** {case.get('verificationStatus') or 'pending'} / SLA {case.get('slaStatus') or 'pending'}",
            f"> **情报编目：** {case.get('catalogNumber') or '未编目'} / {case.get('catalogStatus') or 'unfiled'}",
            f"> **研判人员：** {case.get('reviewer') or '未填写'}",
            f"> **处置状态：** {case.get('disposition') or '待处置'}",
            f"> **内容摘要：** {case.get('contentExcerpt') or '未提供'}",
            f"> **研判备注：** {case.get('note') or '无'}",
            f"> **事件编号：** {case.get('eventId') or '-'}",
        ]
    )


def push_case(case_id: int) -> dict[str, Any]:
    with get_db_connection() as connection:
        case = get_case_payload(connection, case_id)
        if case["verificationStatus"] == "pending":
            raise ValueError("case must complete initial verification before push")
        if case["screenshotUrl"] and not case["screenshotCompliant"]:
            raise ValueError("screenshot must be marked compliant before push")
        response = post_bot_payload(build_markdown_payload(build_case_markdown(case)), load_bot_config())
        if not bool(response.get("dry_run")):
            pushed_at = utc_now_iso()
            connection.execute(
                "UPDATE darkweb_monitoring_cases SET pushed_at = ?, updated_at = ? WHERE id = ?",
                (pushed_at, pushed_at, int(case_id)),
            )
            connection.commit()
        return {"case": get_case_payload(connection, case_id), "response": response}


def _update_source_state(
    source_key: str,
    *,
    status: str,
    finding_count: int = 0,
    error: str = "",
) -> None:
    now = utc_now_iso()
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO darkweb_monitoring_source_states (
                source_key, status, last_success_at, last_error_at, last_error,
                last_finding_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                status = excluded.status,
                last_success_at = CASE WHEN excluded.status = 'connected' THEN excluded.last_success_at ELSE darkweb_monitoring_source_states.last_success_at END,
                last_error_at = CASE WHEN excluded.status = 'error' THEN excluded.last_error_at ELSE darkweb_monitoring_source_states.last_error_at END,
                last_error = excluded.last_error,
                last_finding_count = excluded.last_finding_count,
                updated_at = excluded.updated_at
            """,
            (
                source_key,
                status,
                now if status == "connected" else "",
                now if status == "error" else "",
                error[:1000],
                int(finding_count),
                now,
            ),
        )
        connection.commit()


def _source_states() -> dict[str, dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute("SELECT * FROM darkweb_monitoring_source_states").fetchall()
    return {str(row["source_key"]): dict(row) for row in rows}


def poll_configured_connectors() -> dict[str, Any]:
    states = _source_states()
    try:
        poll_interval = max(60, int(os.environ.get("DARKWEB_CONNECTOR_POLL_INTERVAL_SECONDS", "300")))
    except ValueError:
        poll_interval = 300
    now = datetime.now(timezone.utc)
    results = []
    for platform in MONITORING_PLATFORMS:
        connector_url = _normalize_text(os.environ.get(platform["environment"]))
        if not connector_url:
            results.append({"key": platform["key"], "status": "waiting_configuration", "ingested": 0})
            continue
        state = states.get(platform["key"], {})
        last_checked = _parse_datetime(state.get("updated_at"))
        if last_checked is not None and (now - last_checked).total_seconds() < poll_interval:
            results.append(
                {
                    "key": platform["key"],
                    "status": state.get("status") or "configured",
                    "ingested": 0,
                    "skipped": True,
                }
            )
            continue
        parsed = urlparse(connector_url)
        if parsed.scheme not in {"http", "https"}:
            message = "connector URL must use http or https"
            _update_source_state(platform["key"], status="error", error=message)
            results.append({"key": platform["key"], "status": "error", "ingested": 0, "error": message})
            continue
        headers = {"Accept": "application/json", "User-Agent": "DarkWebThreatIntel/0.11"}
        token = _normalize_text(os.environ.get(platform["tokenEnvironment"]))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            request = Request(connector_url, headers=headers, method="GET")
            with urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, list):
                findings = payload
            elif isinstance(payload, dict):
                findings = payload.get("findings") or payload.get("items") or []
            else:
                findings = []
            if not isinstance(findings, list):
                raise ValueError("connector response findings must be a list")
            ingested = 0
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                ingest_finding({**finding, "source_platform": platform["name"]})
                ingested += 1
            _update_source_state(platform["key"], status="connected", finding_count=ingested)
            results.append({"key": platform["key"], "status": "connected", "ingested": ingested})
        except Exception as exc:
            message = _normalize_text(exc) or exc.__class__.__name__
            _update_source_state(platform["key"], status="error", error=message)
            results.append({"key": platform["key"], "status": "error", "ingested": 0, "error": message})
    return {
        "configuredCount": sum(1 for item in results if item["status"] != "waiting_configuration"),
        "connectedCount": sum(1 for item in results if item["status"] == "connected"),
        "results": results,
    }


def _platforms_payload(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_platform.setdefault(case["sourcePlatform"], []).append(case)
    states = _source_states()
    rows = []
    for item in MONITORING_PLATFORMS:
        platform_cases = by_platform.get(item["name"], [])
        configured = bool(_normalize_text(os.environ.get(item["environment"])))
        state = states.get(item["key"], {})
        last_seen = max(
            [case["firstDetectedAt"] for case in platform_cases] + [_normalize_text(state.get("last_success_at"))],
            default="",
        )
        if not configured:
            status = "waiting_configuration"
        elif state.get("status") == "error":
            status = "error"
        elif state.get("status") == "connected":
            status = "connected"
        else:
            status = "configured"
        rows.append(
            {
                "key": item["key"],
                "name": item["name"],
                "kind": item["kind"],
                "enabled": True,
                "status": status,
                "lastSeenAt": last_seen,
                "findingCount": len(platform_cases),
                "configurationHint": item["configurationHint"],
                "lastError": _normalize_text(state.get("last_error")),
            }
        )
    return rows


def build_overview() -> dict[str, Any]:
    with get_db_connection() as connection:
        sync_cases_from_normalized_events(connection)
        cases = list_cases_payload(connection)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    month = now.strftime("%Y-%m")
    platforms = _platforms_payload(cases)
    periods = sorted({case["firstDetectedAt"][:7] for case in cases if case["firstDetectedAt"]}, reverse=True)
    return {
        "service": {
            "slaMinutes": SLA_MINUTES,
            "monitoredPlatformCount": len(platforms),
            "connectedPlatformCount": sum(1 for item in platforms if item["status"] == "connected"),
            "lastUpdatedAt": utc_now_iso(),
            "autoMonitoringEnabled": any(
                _normalize_text(os.environ.get(name, "0")).lower() not in {"0", "false", "no", "off"}
                for name in ("DARKWEB_AUTO_MONITORING", "DARKWEB_SCHEDULER_ENABLED")
            ),
        },
        "metrics": {
            "todayFindings": sum(1 for case in cases if case["firstDetectedAt"].startswith(today)),
            "pendingVerification": sum(1 for case in cases if case["verificationStatus"] == "pending"),
            "slaBreached": sum(1 for case in cases if case["slaStatus"] == "breached"),
            "verifiedThisMonth": sum(1 for case in cases if case["verifiedAt"].startswith(month)),
        },
        "platforms": platforms,
        "cases": cases,
        "monthlyPeriods": periods or [month],
    }


def scan_sla_breaches() -> dict[str, int]:
    now = utc_now_iso()
    result = {"breached": 0, "alerted": 0, "failed": 0}
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM darkweb_monitoring_cases
            WHERE verification_status = 'pending'
              AND datetime(sla_due_at) <= datetime(?)
              AND sla_alerted_at IS NULL
            ORDER BY datetime(sla_due_at), id
            """,
            (now,),
        ).fetchall()
        for row in rows:
            result["breached"] += 1
            case = _case_payload(dict(row))
            content = "\n".join(
                [
                    "# 暗网监测 SLA 超时提醒",
                    f"> **威胁标题：** {case['title']}",
                    f"> **来源平台：** {case['sourcePlatform']}",
                    f"> **关联目标：** {case['targetName']} / {case['targetIndustry']}",
                    f"> **发现时间：** {case['firstDetectedAt']}",
                    f"> **SLA 截止：** {case['slaDueAt']}",
                    "> **要求：** 请立即完成初步验证、情报编目和报送判断。",
                ]
            )
            try:
                response = post_bot_payload(build_markdown_payload(content), load_bot_config())
            except Exception:
                result["failed"] += 1
                continue
            if bool(response.get("dry_run")):
                continue
            connection.execute(
                "UPDATE darkweb_monitoring_cases SET sla_alerted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, case["id"]),
            )
            connection.commit()
            result["alerted"] += 1
    return result


def _report_payload(start: datetime, end: datetime, *, report_type: str, period: str) -> dict[str, Any]:
    with get_db_connection() as connection:
        sync_cases_from_normalized_events(connection)
        all_cases = list_cases_payload(connection, limit=2000)
    cases = []
    for case in all_cases:
        detected = _parse_datetime(case["firstDetectedAt"])
        if detected is not None and start <= detected < end:
            cases.append(case)
    effective_cases = [case for case in cases if case["verificationStatus"] != "false_positive"]
    platform_counter = Counter(case["sourcePlatform"] for case in effective_cases)
    type_counter = Counter(case["threatType"] for case in effective_cases)
    target_counter = Counter(
        case["targetName"] if case["targetName"] != "待确认" else case["targetIndustry"]
        for case in effective_cases
    )
    daily_counter = Counter(case["firstDetectedAt"][:10] for case in effective_cases)
    metrics = {
        "findingCount": len(cases),
        "verifiedCount": sum(1 for case in cases if case["verificationStatus"] in FINAL_VERIFICATION_STATUSES),
        "falsePositiveCount": sum(1 for case in cases if case["verificationStatus"] == "false_positive"),
        "slaBreachedCount": sum(1 for case in cases if case["slaStatus"] == "breached"),
        "pushedCount": sum(1 for case in cases if case["pushedAt"]),
    }
    markdown_lines = [
        f"# 暗网监测{'月报' if report_type == 'monthly' else '日报'}（{period}）",
        "",
        "## 监测概况",
        f"- 监测平台：{len(MONITORING_PLATFORMS)} 家（长安不夜城、XSS、BreachForums、Telegram）",
        f"- 发现线索：{metrics['findingCount']} 条",
        f"- 完成初验：{metrics['verifiedCount']} 条",
        f"- SLA 超时：{metrics['slaBreachedCount']} 条",
        f"- 已报送：{metrics['pushedCount']} 条",
        "",
        "## 重点威胁",
    ]
    for index, case in enumerate(effective_cases[:20], start=1):
        markdown_lines.append(
            f"{index}. {case['title']}｜{case['sourcePlatform']}｜{case['threatType']}｜{case['targetName']}｜{case['confidenceLevel']}"
        )
    if not effective_cases:
        markdown_lines.append("本周期未发现符合监测范围的有效威胁。")
    payload = {
        "reportType": report_type,
        "period": period,
        "generatedAt": utc_now_iso(),
        "periodStart": _iso(start),
        "periodEnd": _iso(end),
        "metrics": metrics,
        "platformDistribution": [{"name": key, "value": value} for key, value in platform_counter.most_common()],
        "threatTypeDistribution": [{"name": key, "value": value} for key, value in type_counter.most_common()],
        "targetDistribution": [{"name": key, "value": value} for key, value in target_counter.most_common(10)],
        "dailyTrend": [{"date": key, "value": daily_counter[key]} for key in sorted(daily_counter)],
        "cases": cases,
        "markdown": "\n".join(markdown_lines),
    }
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO darkweb_monitoring_reports (report_type, period, payload_json, generated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(report_type, period) DO UPDATE SET
                payload_json = excluded.payload_json,
                generated_at = excluded.generated_at
            """,
            (report_type, period, _json_dumps(payload), payload["generatedAt"]),
        )
        connection.commit()
    return payload


def build_daily_report(day: str | None = None) -> dict[str, Any]:
    try:
        target = date.fromisoformat(day) if day else datetime.now(timezone.utc).date()
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc
    start = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    return _report_payload(start, start + timedelta(days=1), report_type="daily", period=target.isoformat())


def build_monthly_report(month: str | None = None) -> dict[str, Any]:
    raw = _normalize_text(month) or datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        target = datetime.strptime(raw, "%Y-%m")
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM") from exc
    start = datetime(target.year, target.month, 1, tzinfo=timezone.utc)
    days = monthrange(target.year, target.month)[1]
    return _report_payload(start, start + timedelta(days=days), report_type="monthly", period=raw)


def _report_exists(report_type: str, period: str) -> bool:
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT id FROM darkweb_monitoring_reports WHERE report_type = ? AND period = ?",
            (report_type, period),
        ).fetchone()
    return row is not None


def generate_due_reports() -> list[dict[str, str]]:
    now = datetime.now(timezone.utc)
    generated = []
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    if not _report_exists("daily", yesterday):
        build_daily_report(yesterday)
        generated.append({"reportType": "daily", "period": yesterday})
    if now.day <= 3:
        previous_month_last_day = now.replace(day=1) - timedelta(days=1)
        previous_month = previous_month_last_day.strftime("%Y-%m")
        if not _report_exists("monthly", previous_month):
            build_monthly_report(previous_month)
            generated.append({"reportType": "monthly", "period": previous_month})
    return generated


def run_monitoring_cycle() -> dict[str, Any]:
    from darkweb_collector.api_actions import dispatch_run_all_enabled_sites_once

    dispatch = dispatch_run_all_enabled_sites_once(force=False)
    connectors = poll_configured_connectors()
    with get_db_connection() as connection:
        created = sync_cases_from_normalized_events(connection)
    return {
        "dispatch": dispatch,
        "connectors": connectors,
        "newCaseCount": created,
        "sla": scan_sla_breaches(),
        "generatedReports": generate_due_reports(),
        "startedAt": utc_now_iso(),
    }
