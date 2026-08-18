from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
from threading import Lock
from typing import Any

from darkweb_collector.db import get_db_connection, get_normalized_intelligence_cache_state, get_readonly_db_connection
from darkweb_collector.intelligence_queries import _NORMALIZED_COLUMNS, _VULNERABILITY_CTE
from darkweb_collector.monitoring_rules import load_monitoring_snapshot, persist_monitoring_snapshot
from darkweb_collector.normalized_intelligence import (
    _build_vulnerability_base_event,
    _hydrate_event_row,
    build_display_title,
    load_normalized_events,
    normalized_event_to_list_item,
)
from darkweb_collector.utils import utc_now_iso

DASHBOARD_DAYS = (1, 7, 30)
DASHBOARD_EVENT_TYPES = {"all", "data_leak", "ransomware", "vulnerability", "document_exposure"}
SHANGHAI_TZ = timezone(timedelta(hours=8))
_CACHE_LOCK = Lock()
_MONITORING_LOCK = Lock()
_CACHE: dict[str, dict[str, Any]] = {}


def _range_start(days: int) -> datetime:
    now = datetime.now(SHANGHAI_TZ)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)).astimezone(timezone.utc)


def _sql_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _days(days: int) -> tuple[list[str], list[str]]:
    today = datetime.now(SHANGHAI_TZ).date()
    keys = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    return keys, [key[5:] for key in keys]


def _marker(connection, table: str, time_sql: str) -> tuple[int, str, str]:
    row = connection.execute(f"SELECT COUNT(*), MAX(id), MAX({time_sql}) FROM {table}").fetchone()
    return int(row[0] or 0), str(row[1] or ""), str(row[2] or "")


def aggregate_revision(connection) -> str:
    state = get_normalized_intelligence_cache_state(connection) or {}
    monitoring = connection.execute("SELECT COUNT(*), MAX(updated_at) FROM monitoring_keywords").fetchone()
    database_row = connection.execute("PRAGMA database_list").fetchone()
    value = {
        "version": "2026-08-06-v1",
        "database": str(database_row[2] or "") if database_row else "",
        "revision": int(state.get("applied_revision") or 0),
        "signature": str(state.get("source_signature") or ""),
        "events": int(state.get("event_count") or 0),
        "vulnerabilities": _marker(connection, "vulnerability_records", "last_seen_at"),
        "documents": _marker(connection, "document_hits", "last_seen_at"),
        "code": _marker(connection, "code_hits", "last_seen_at"),
        "jobs": _marker(connection, "crawl_jobs", "COALESCE(finished_at, started_at, enqueued_at)"),
        "monitoring": (int(monitoring[0] or 0), str(monitoring[1] or "")),
    }
    return sha1(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _cache_get(namespace: str, key: str) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        row = _CACHE.get(namespace)
        return row.get("payload") if row and row.get("key") == key else None


def _cache_set(namespace: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _CACHE_LOCK:
        _CACHE[namespace] = {"key": key, "payload": payload}
    return payload


def _rows(connection, sql: str, parameters: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _materialize_vulnerability(row: dict[str, Any]) -> dict[str, Any]:
    event = _build_vulnerability_base_event(row)
    severity = str(event.get("severity") or "").lower()
    risk = 85 if severity == "critical" else 72 if severity == "high" else 58 if severity == "medium" else 55
    if bool((event.get("metadata") or {}).get("is_exploited")):
        risk = min(100, risk + 10)
    return normalized_event_to_list_item({**event, "risk_score": risk, "risk_reasons": []})


def _normalized_events(connection, start: str, types: list[str], severity: str, keyword: str) -> list[dict[str, Any]]:
    if not types:
        return []
    clauses = [f"n.event_type IN ({','.join('?' for _ in types)})", "datetime(COALESCE(NULLIF(n.disclosure_time,''),n.updated_at)) >= datetime(?)"]
    parameters: list[Any] = [*types, start]
    if severity:
        clauses.append("LOWER(n.severity)=?")
        parameters.append(severity)
    if keyword:
        pattern = f"%{_escape_like(keyword)}%"
        fields = ("n.title", "n.attacker", "n.victim", "n.industry", "n.region", "n.category", "n.detail_text", "n.event_metadata_json")
        clauses.append("(" + " OR ".join(f"{field} LIKE ? ESCAPE '\\' COLLATE NOCASE" for field in fields) + ")")
        parameters.extend([pattern] * len(fields))
    result = connection.execute(
        f"""SELECT {_NORMALIZED_COLUMNS} FROM normalized_intelligence_events n
            WHERE {' AND '.join(clauses)}
            ORDER BY n.risk_score DESC, datetime(COALESCE(NULLIF(n.disclosure_time,''),n.updated_at)) DESC
            LIMIT 40""",
        parameters,
    ).fetchall()
    return [normalized_event_to_list_item(_hydrate_event_row(dict(row))) for row in result]


def _vulnerability_events(connection, start: str, severity: str, keyword: str) -> list[dict[str, Any]]:
    clauses = ["datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)"]
    parameters: list[Any] = [start]
    if severity:
        clauses.append("effective_severity=?")
        parameters.append(severity)
    if keyword:
        pattern = f"%{_escape_like(keyword)}%"
        fields = ("cve_id", "title", "vendor", "product", "vulnerability_type", "summary")
        clauses.append("(" + " OR ".join(f"{field} LIKE ? ESCAPE '\\' COLLATE NOCASE" for field in fields) + ")")
        parameters.extend([pattern] * len(fields))
    result = connection.execute(
        f"""{_VULNERABILITY_CTE} SELECT * FROM deduped_vulnerabilities
            WHERE {' AND '.join(clauses)}
            ORDER BY effective_risk_score DESC, datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) DESC
            LIMIT 20""",
        parameters,
    ).fetchall()
    return [_materialize_vulnerability(dict(row)) for row in result]


def _document_events(connection, start: str, severity: str, keyword: str) -> list[dict[str, Any]]:
    clauses = ["datetime(COALESCE(NULLIF(h.disclosure_time,''),h.last_seen_at)) >= datetime(?)"]
    parameters: list[Any] = [start]
    if severity:
        clauses.append("LOWER(h.severity)=?")
        parameters.append(severity)
    if keyword:
        pattern = f"%{_escape_like(keyword)}%"
        clauses.append("(h.title LIKE ? ESCAPE '\\' COLLATE NOCASE OR w.name LIKE ? ESCAPE '\\' COLLATE NOCASE OR w.organization_name LIKE ? ESCAPE '\\' COLLATE NOCASE OR h.raw_json LIKE ? ESCAPE '\\' COLLATE NOCASE)")
        parameters.extend([pattern] * 4)
    result = connection.execute(
        f"""SELECT h.*, w.name AS watchlist_name, w.organization_name
            FROM document_hits h JOIN exposure_watchlists w ON w.id=h.watchlist_id
            WHERE {' AND '.join(clauses)}
            ORDER BY h.risk_score DESC, datetime(COALESCE(NULLIF(h.disclosure_time,''),h.last_seen_at)) DESC
            LIMIT 20""",
        parameters,
    ).fetchall()
    events: list[dict[str, Any]] = []
    for source in result:
        row = dict(source)
        risk = int(row.get("risk_score") or 0)
        stamp = str(row.get("disclosure_time") or row.get("last_seen_at") or "")
        try:
            raw = json.loads(str(row.get("raw_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
        events.append({
            "id": f"document:{row['id']}", "event_type": "document",
            "normalized_event_type": "document_exposure", "raw_source_type": "document_hits",
            "disclosureTime": stamp, "disclosureTimeRaw": stamp, "disclosureDate": stamp[:10],
            "updatedTime": str(row.get("last_seen_at") or ""), "updatedTimeRaw": str(row.get("last_seen_at") or ""),
            "title": str(row.get("title") or "未命名文件命中"), "category": "文件监测外泄",
            "attacker": str(row.get("platform") or row.get("discovery_source") or "文件平台"),
            "sourceSite": str(row.get("platform") or row.get("discovery_source") or "文件平台"),
            "industry": "未知", "country": "未知", "countryCode": "", "region": "未知",
            "severity": str(row.get("severity") or "low"),
            "victim": str(row.get("organization_name") or row.get("watchlist_name") or "未知实体"),
            "riskScore": risk, "priorityScore": risk,
            "monitoringPriority": "high" if risk >= 75 else "medium" if risk >= 45 else "low",
            "summary": str(raw.get("summary") or raw.get("preview_text") or raw.get("description") or ""),
            "reviewStatus": str(row.get("review_status") or "new"),
            "accessState": str(row.get("access_state") or "unknown"),
            "hasSampleEvidence": bool(row.get("evidence_count")),
        })
    return events


def _severity_counts(connection, start: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    queries = (
        ("""SELECT LOWER(severity),COUNT(*) FROM normalized_intelligence_events
             WHERE event_type IN ('data_leak','ransomware')
               AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
             GROUP BY LOWER(severity)""", False),
        (f"""{_VULNERABILITY_CTE} SELECT effective_severity,COUNT(*) FROM deduped_vulnerabilities
              WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
              GROUP BY effective_severity""", False),
        ("""SELECT LOWER(severity),COUNT(*) FROM document_hits
             WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
             GROUP BY LOWER(severity)""", False),
    )
    for sql, _ in queries:
        for row in connection.execute(sql, (start,)).fetchall():
            counter[str(row[0] or "low")] += int(row[1] or 0)
    return counter


def _event_key(item: dict[str, Any]) -> tuple[int, str]:
    return (
        int(item.get("priorityScore") or item.get("riskScore") or 0),
        str(item.get("updatedTimeRaw") or item.get("disclosureTimeRaw") or item.get("disclosureDate") or ""),
    )


def build_dashboard_overview(*, days: int = 7, event_type: str = "all", severity: str = "", keyword: str = "") -> dict[str, Any]:
    days = int(days) if int(days) in DASHBOARD_DAYS else 7
    event_type = str(event_type or "all").strip().lower().replace("-", "_")
    event_type = event_type if event_type in DASHBOARD_EVENT_TYPES else "all"
    severity = str(severity or "").strip().lower()
    severity = severity if severity in {"critical", "high", "medium", "low"} else ""
    keyword = str(keyword or "").strip()[:200]
    start = _sql_time(_range_start(days))
    day_keys, labels = _days(days)
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            revision = aggregate_revision(connection)
            key = sha1(json.dumps(
                {"revision": revision, "days": days, "type": event_type, "severity": severity, "keyword": keyword},
                sort_keys=True, ensure_ascii=False,
            ).encode()).hexdigest()
            cached = _cache_get("dashboard", key)
            if cached is not None:
                return cached

            normalized_counts = {
                str(row[0]): int(row[1] or 0)
                for row in connection.execute(
                    """SELECT event_type,COUNT(*) FROM normalized_intelligence_events
                       WHERE event_type IN ('data_leak','ransomware')
                         AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                       GROUP BY event_type""", (start,),
                ).fetchall()
            }
            vulnerability_count = int(connection.execute(
                f"""{_VULNERABILITY_CTE} SELECT COUNT(*) FROM deduped_vulnerabilities
                    WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)""",
                (start,),
            ).fetchone()[0])
            document_count = int(connection.execute(
                """SELECT COUNT(*) FROM document_hits
                   WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)""",
                (start,),
            ).fetchone()[0])
            high_count = int(connection.execute(
                """SELECT COUNT(*) FROM normalized_intelligence_events
                   WHERE event_type IN ('data_leak','ransomware')
                     AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                     AND LOWER(severity) IN ('critical','high')""", (start,),
            ).fetchone()[0])
            high_count += int(connection.execute(
                f"""{_VULNERABILITY_CTE} SELECT COUNT(*) FROM deduped_vulnerabilities
                    WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                      AND effective_severity IN ('critical','high')""", (start,),
            ).fetchone()[0])
            high_count += int(connection.execute(
                """SELECT COUNT(*) FROM document_hits
                   WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                     AND LOWER(severity) IN ('critical','high')""", (start,),
            ).fetchone()[0])
            exploited = int(connection.execute(
                f"""{_VULNERABILITY_CTE} SELECT COUNT(*) FROM deduped_vulnerabilities
                    WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                      AND is_exploited=1""", (start,),
            ).fetchone()[0])

            trend = {
                "labels": labels, "dataLeak": [0] * days, "ransomware": [0] * days,
                "vulnerability": [0] * days, "documentExposure": [0] * days,
                "total": [0] * days, "highRisk": [0] * days,
            }
            day_index = {value: index for index, value in enumerate(day_keys)}
            for row in connection.execute(
                """SELECT event_type,date(datetime(COALESCE(NULLIF(disclosure_time,''),updated_at),'+8 hours')),
                          COUNT(*),SUM(CASE WHEN LOWER(severity) IN ('critical','high') THEN 1 ELSE 0 END)
                   FROM normalized_intelligence_events
                   WHERE event_type IN ('data_leak','ransomware')
                     AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                   GROUP BY event_type,2""", (start,),
            ).fetchall():
                index = day_index.get(str(row[1] or ""))
                if index is not None:
                    trend["dataLeak" if row[0] == "data_leak" else "ransomware"][index] += int(row[2] or 0)
                    trend["highRisk"][index] += int(row[3] or 0)
            for row in connection.execute(
                f"""{_VULNERABILITY_CTE}
                    SELECT date(datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at),'+8 hours')),
                           COUNT(*),SUM(CASE WHEN effective_severity IN ('critical','high') THEN 1 ELSE 0 END)
                    FROM deduped_vulnerabilities
                    WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                    GROUP BY 1""", (start,),
            ).fetchall():
                index = day_index.get(str(row[0] or ""))
                if index is not None:
                    trend["vulnerability"][index] = int(row[1] or 0)
                    trend["highRisk"][index] += int(row[2] or 0)
            for row in connection.execute(
                """SELECT date(datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at),'+8 hours')),
                          COUNT(*),SUM(CASE WHEN LOWER(severity) IN ('critical','high') THEN 1 ELSE 0 END)
                   FROM document_hits
                   WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                   GROUP BY 1""", (start,),
            ).fetchall():
                index = day_index.get(str(row[0] or ""))
                if index is not None:
                    trend["documentExposure"][index] = int(row[1] or 0)
                    trend["highRisk"][index] += int(row[2] or 0)
            trend["total"] = [
                trend["dataLeak"][i] + trend["ransomware"][i] + trend["vulnerability"][i] + trend["documentExposure"][i]
                for i in range(days)
            ]

            countries = _rows(connection,
                """SELECT name,code,COUNT(*) AS count,ROUND(AVG(risk_score)) AS risk
                   FROM (
                     SELECT COALESCE(NULLIF(json_extract(event_metadata_json,'$.country'),''),region) AS name,
                            UPPER(COALESCE(json_extract(event_metadata_json,'$.country_code'),'')) AS code,
                            risk_score
                     FROM normalized_intelligence_events
                     WHERE datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                     UNION ALL
                     SELECT COALESCE(NULLIF(json_extract(raw_json,'$.country'),''),
                                     NULLIF(json_extract(raw_json,'$.region'),''),'未知') AS name,
                            UPPER(COALESCE(json_extract(raw_json,'$.country_code'),'')) AS code,
                            risk_score
                     FROM document_hits
                     WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                   )
                   WHERE name NOT IN ('','未知')
                   GROUP BY name,code ORDER BY count DESC,risk DESC LIMIT 6""", (start, start))
            industries = _rows(connection,
                """SELECT industry AS name,COUNT(*) AS count,ROUND(AVG(risk_score)) AS value
                   FROM normalized_intelligence_events
                   WHERE datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                     AND industry NOT IN ('','未知')
                   GROUP BY industry ORDER BY value DESC,count DESC LIMIT 4""", (start,))
            leak_types = _rows(connection,
                """SELECT category AS name,COUNT(*) AS value FROM normalized_intelligence_events
                   WHERE event_type='data_leak'
                     AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                   GROUP BY category ORDER BY value DESC,name LIMIT 6""", (start,))
            actors = _rows(connection,
                """SELECT attacker AS name,COUNT(*) AS value FROM normalized_intelligence_events
                   WHERE event_type='ransomware'
                     AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                     AND attacker NOT IN ('','未知')
                   GROUP BY attacker ORDER BY value DESC,name LIMIT 6""", (start,))
            vendors = _rows(connection,
                f"""{_VULNERABILITY_CTE} SELECT vendor AS name,COUNT(*) AS value FROM deduped_vulnerabilities
                    WHERE datetime(COALESCE(NULLIF(disclosure_time,''),last_seen_at)) >= datetime(?)
                      AND vendor NOT IN ('','未知')
                    GROUP BY vendor ORDER BY value DESC,name LIMIT 6""", (start,))
            severities = _severity_counts(connection, start)
            normalized_types: list[str] = []
            if event_type in {"all", "data_leak"}:
                normalized_types.append("data_leak")
            if event_type in {"all", "ransomware"}:
                normalized_types.append("ransomware")
            events = _normalized_events(connection, start, normalized_types, severity, keyword)
            if event_type in {"all", "vulnerability"}:
                events.extend(_vulnerability_events(connection, start, severity, keyword))
            if event_type in {"all", "document_exposure"}:
                events.extend(_document_events(connection, start, severity, keyword))
            events = sorted(events, key=_event_key, reverse=True)[:20]
            state = get_normalized_intelligence_cache_state(connection) or {}
        finally:
            connection.rollback()

    leak_count = normalized_counts.get("data_leak", 0)
    ransom_count = normalized_counts.get("ransomware", 0)
    payload = {
        "generatedAt": utc_now_iso(), "snapshotRevision": revision, "days": days,
        "kpis": {"dataLeak": leak_count, "ransomware": ransom_count, "vulnerability": vulnerability_count,
                 "documentExposure": document_count, "highRisk": high_count},
        "highlights": {"dataLeakTop": leak_types[0] if leak_types else None,
                       "activeRansomwareActors": len(actors), "exploitedVulnerabilities": exploited,
                       "highRisk": high_count},
        "dailyTrend": trend,
        "countries": [{"name": row.get("name") or "未知", "code": row.get("code") or "",
                       "count": int(row.get("count") or 0), "value": int(row.get("count") or 0),
                       "risk": int(row.get("risk") or 0)} for row in countries],
        "industries": [{"name": row.get("name") or "未知", "count": int(row.get("count") or 0),
                        "value": int(row.get("value") or 0)} for row in industries],
        "distribution": {"ransomware": ransom_count, "dataLeak": leak_count,
                         "vulnerability": vulnerability_count, "documentExposure": document_count},
        "severityDistribution": {"critical": severities["critical"], "high": severities["high"],
                                 "mediumLow": severities["medium"] + severities["low"]},
        "rankings": {"ransomwareActors": actors, "dataLeakTypes": leak_types, "vulnerabilityVendors": vendors},
        "events": events,
        "monitoringStatus": {"statusLabel": "监测服务运行中",
                             "subtitle": str(state.get("refreshed_at") or "读取最新完整快照"),
                             "appliedRevision": int(state.get("applied_revision") or 0)},
    }
    return _cache_set("dashboard", key, payload)


def _monitoring_snapshot() -> dict[str, Any]:
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            snapshot = load_monitoring_snapshot(connection)
        finally:
            connection.rollback()
    if snapshot is not None:
        return snapshot
    with _MONITORING_LOCK:
        with get_db_connection() as connection:
            snapshot = load_monitoring_snapshot(connection)
            if snapshot is not None:
                return snapshot
            events = load_normalized_events(connection, allow_refresh=False)
            snapshot = persist_monitoring_snapshot(connection, events)
            connection.commit()
            return snapshot


def _safe_pct(current: int, previous: int) -> int:
    if previous <= 0:
        return 100 if current else 0
    return round((current - previous) / previous * 100)


def build_threat_situation(*, days: int = 30) -> dict[str, Any]:
    days = max(1, min(90, int(days or 30)))
    now = datetime.now(timezone.utc)
    current_start = _sql_time(now - timedelta(days=days))
    previous_start = _sql_time(now - timedelta(days=days * 2))
    day_start = _sql_time(_range_start(days))
    day_keys, labels = _days(days)
    monitoring = _monitoring_snapshot()
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            revision = aggregate_revision(connection)
            monitoring_revision = str((monitoring.get("analysisSnapshot") or {}).get("revisionKey") or "")
            key = sha1(f"{revision}:{monitoring_revision}:{days}".encode()).hexdigest()
            cached = _cache_get("threat", key)
            if cached is not None:
                return cached
            count_row = connection.execute(
                """SELECT
                    SUM(CASE WHEN datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?) THEN 1 ELSE 0 END),
                    SUM(CASE WHEN datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                              AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) < datetime(?) THEN 1 ELSE 0 END),
                    SUM(CASE WHEN datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                              AND risk_score >= 60 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                              AND datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) < datetime(?)
                              AND risk_score >= 60 THEN 1 ELSE 0 END)
                   FROM normalized_intelligence_events
                   WHERE event_type!='vulnerability'""",
                (current_start, previous_start, current_start, current_start, previous_start, current_start),
            ).fetchone()
            countries = _rows(connection,
                """SELECT COALESCE(NULLIF(json_extract(event_metadata_json,'$.country'),''),region) AS name,
                          COUNT(*) AS eventCount,
                          SUM(CASE WHEN risk_score>=60 THEN 1 ELSE 0 END) AS highRiskCount,
                          ROUND(AVG(risk_score)) AS averageRiskScore
                   FROM normalized_intelligence_events
                   WHERE event_type!='vulnerability'
                     AND COALESCE(NULLIF(json_extract(event_metadata_json,'$.country'),''),region) NOT IN ('','未知')
                   GROUP BY name ORDER BY eventCount DESC,highRiskCount DESC,averageRiskScore DESC LIMIT 10""")
            day_index = {value: index for index, value in enumerate(day_keys)}
            trend_total, trend_high = [0] * days, [0] * days
            for row in connection.execute(
                """SELECT date(datetime(COALESCE(NULLIF(disclosure_time,''),updated_at),'+8 hours')),
                          COUNT(*),SUM(CASE WHEN risk_score>=60 THEN 1 ELSE 0 END)
                   FROM normalized_intelligence_events
                   WHERE datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) >= datetime(?)
                   GROUP BY 1""", (day_start,),
            ).fetchall():
                index = day_index.get(str(row[0] or ""))
                if index is not None:
                    trend_total[index], trend_high[index] = int(row[1] or 0), int(row[2] or 0)
            priority_rows = connection.execute(
                f"""SELECT {_NORMALIZED_COLUMNS} FROM normalized_intelligence_events
                    WHERE LENGTH(TRIM(title))>=4
                    ORDER BY risk_score DESC,datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) DESC LIMIT 10"""
            ).fetchall()
            priorities = []
            for source in priority_rows:
                event = _hydrate_event_row(dict(source))
                priorities.append({
                    "id": event.get("event_id"), "disclosureDate": str(event.get("disclosure_time") or "")[:10],
                    "title": build_display_title(event), "originalTitle": event.get("title") or "未命名事件",
                    "attacker": event.get("attacker") or "未知", "sourceSite": event.get("source_site_name") or "",
                    "country": event.get("country") or "未知", "industry": event.get("industry") or "未知",
                    "riskScore": int(event.get("risk_score") or 0),
                })
            coverage = connection.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN COALESCE(NULLIF(json_extract(event_metadata_json,'$.country'),''),region) NOT IN ('','未知') THEN 1 ELSE 0 END),
                          SUM(CASE WHEN region NOT IN ('','未知') THEN 1 ELSE 0 END),
                          SUM(CASE WHEN industry NOT IN ('','未知') THEN 1 ELSE 0 END)
                   FROM normalized_intelligence_events"""
            ).fetchone()
            coverage_total = max(1, int(coverage[0] or 0))
            industry_rows = _rows(connection,
                """WITH ranked AS (
                       SELECT industry,event_type,ROW_NUMBER() OVER(
                           PARTITION BY event_type
                           ORDER BY datetime(COALESCE(NULLIF(disclosure_time,''),updated_at)) DESC,event_id DESC
                       ) AS source_rank
                       FROM normalized_intelligence_events)
                   SELECT industry AS name,COUNT(*) AS value FROM ranked
                   WHERE industry NOT IN ('','未知')
                     AND (event_type='ransomware' OR (event_type='data_leak' AND source_rank<=3000))
                   GROUP BY industry ORDER BY value DESC,name""")
            vulnerability_industries = int(connection.execute(
                f"{_VULNERABILITY_CTE} SELECT MIN(500,COUNT(*)) FROM deduped_vulnerabilities"
            ).fetchone()[0])
            industry_counter = Counter({str(row["name"]): int(row["value"]) for row in industry_rows})
            industry_counter["基础设施软件"] += vulnerability_industries
            ranked_industries = industry_counter.most_common()
            industry_top = ranked_industries[:10]
            other = sum(value for _, value in ranked_industries[10:])
            if other:
                industry_top.append(("其他", other))
            industry_total = sum(industry_counter.values())
            actors = _rows(connection,
                """SELECT attacker AS actor,COUNT(*) AS value,ROUND(AVG(risk_score)) AS averageRiskScore
                   FROM normalized_intelligence_events
                   WHERE event_type='ransomware' AND attacker NOT IN ('','未知')
                   GROUP BY attacker ORDER BY value DESC,averageRiskScore DESC,actor LIMIT 10""")
        finally:
            connection.rollback()

    current_total, previous_total = int(count_row[0] or 0), int(count_row[1] or 0)
    current_high, previous_high = int(count_row[2] or 0), int(count_row[3] or 0)
    payload = {
        "generatedAt": utc_now_iso(), "snapshotRevision": revision, "days": days,
        "threatExecutiveCards": {
            "totalEvents30d": current_total, "totalEventsDeltaPct": _safe_pct(current_total, previous_total),
            "highRisk30d": current_high, "highRiskDeltaPct": _safe_pct(current_high, previous_high),
            "topCountry": countries[0]["name"] if countries else "未知",
            "topCountryEventCount": int(countries[0]["eventCount"]) if countries else 0,
        },
        "threatExecutiveTrend": {"labels": labels, "total": trend_total, "highRisk": trend_high},
        "threatExecutiveCountries": countries,
        "threatExecutivePriorityEvents": priorities,
        "threatExecutiveCoverage": {
            "countryCoverageRate": round(int(coverage[1] or 0) / coverage_total * 100),
            "regionCoverageRate": round(int(coverage[2] or 0) / coverage_total * 100),
            "industryCoverageRate": round(int(coverage[3] or 0) / coverage_total * 100),
        },
        "threatExecutiveIndustryDistribution": [
            {"name": name, "value": value, "percent": round(value / max(1, industry_total) * 100, 2)}
            for name, value in industry_top
        ],
        "threatExecutiveActiveActors": actors,
        "monitoringConfigurationSummary": monitoring.get("monitoringConfigurationSummary") or {},
        "monitoringPriorityQueue": monitoring.get("monitoringPriorityQueue") or [],
        "monitoringKeywordStats": monitoring.get("monitoringKeywordStats") or {"keywords": [], "categories": []},
        "sampleEvidenceAlerts": monitoring.get("sampleEvidenceAlerts") or [],
        "priorityAlertStream": monitoring.get("priorityAlertStream") or [],
        "analysisSnapshot": monitoring.get("analysisSnapshot") or {},
    }
    return _cache_set("threat", key, payload)
