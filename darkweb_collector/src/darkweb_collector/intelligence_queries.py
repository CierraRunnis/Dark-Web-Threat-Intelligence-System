from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import csv
import io
from typing import Any, Iterable, Iterator

from darkweb_collector.db import get_readonly_db_connection
from darkweb_collector.normalized_intelligence import (
    _build_vulnerability_base_event,
    _hydrate_event_row,
    normalized_event_to_list_item,
)


MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
NORMALIZED_EVENT_TYPES = ("data_leak", "ransomware")
SEARCH_EVENT_TYPES = (*NORMALIZED_EVENT_TYPES, "vulnerability")

_NORMALIZED_COLUMNS = """
event_id, source_kind, raw_source_type, source_site_name, source_record_id,
event_type, category, leak_type, title, attacker, victim, victim_key,
industry, region, disclosure_time, severity, risk_score, source_url,
detail_text, mirror_resources_json, screenshot_resources_json,
json_preview_url, risk_reasons_json, event_metadata_json, updated_at
"""

_VULNERABILITY_COLUMNS = """
id, source_name, source_type, cve_id, title, vendor, product, vulnerability_type,
severity, cvss, is_exploited, has_poc, patch_available, wide_impact,
disclosure_time, affected_versions, summary, advisory_url, reference_urls_json,
raw_json, last_seen_at
"""

_VULNERABILITY_CTE = f"""
WITH ranked_vulnerabilities AS (
    SELECT {_VULNERABILITY_COLUMNS},
           ROW_NUMBER() OVER (
               PARTITION BY UPPER(cve_id)
               ORDER BY datetime(disclosure_time) DESC, id DESC
           ) AS source_rank
    FROM vulnerability_records
), deduped_vulnerabilities AS (
    SELECT *,
           CASE
             WHEN LOWER(severity) = 'critical' OR COALESCE(cvss, 0) >= 9 THEN 'critical'
             WHEN is_exploited = 1 OR LOWER(severity) = 'high' OR COALESCE(cvss, 0) >= 7 THEN 'high'
             WHEN LOWER(severity) = 'medium' OR COALESCE(cvss, 0) >= 4 THEN 'medium'
             ELSE 'low'
           END AS effective_severity,
           MIN(100,
             CASE
               WHEN LOWER(severity) = 'critical' OR COALESCE(cvss, 0) >= 9 THEN 85
               WHEN is_exploited = 1 OR LOWER(severity) = 'high' OR COALESCE(cvss, 0) >= 7 THEN 72
               WHEN LOWER(severity) = 'medium' OR COALESCE(cvss, 0) >= 4 THEN 58
               ELSE 55
             END + CASE WHEN is_exploited = 1 THEN 10 ELSE 0 END
           ) AS effective_risk_score
    FROM ranked_vulnerabilities
    WHERE source_rank = 1
)
"""


def _bounded_page(page: int | None, page_size: int | None) -> tuple[int, int]:
    try:
        normalized_page = max(1, int(page or 1))
    except (TypeError, ValueError):
        normalized_page = 1
    try:
        normalized_page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    except (TypeError, ValueError):
        normalized_page_size = DEFAULT_PAGE_SIZE
    return normalized_page, normalized_page_size


def _positive_int(value: int | None) -> int | None:
    try:
        normalized = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _escape_like(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(value: str) -> str:
    return f"%{_escape_like(value.strip())}%"


def _parse_types(value: str | Iterable[str] | None) -> list[str]:
    if isinstance(value, str):
        raw = value.replace("data-leak", "data_leak").split(",")
    else:
        raw = list(value or [])
    requested = {str(item or "").strip().lower() for item in raw}
    if not requested or "all" in requested:
        return list(SEARCH_EVENT_TYPES)
    return [event_type for event_type in SEARCH_EVENT_TYPES if event_type in requested]


def _normalized_where(
    *,
    event_types: Iterable[str],
    days: int | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    severity: str | None = None,
    attacker: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    min_risk_score: int | None = None,
    alias: str = "n",
) -> tuple[str, list[object]]:
    prefix = f"{alias}." if alias else ""
    selected_types = [item for item in event_types if item in NORMALIZED_EVENT_TYPES]
    if not selected_types:
        return "0 = 1", []
    placeholders = ", ".join("?" for _ in selected_types)
    clauses = [f"{prefix}event_type IN ({placeholders})"]
    parameters: list[object] = list(selected_types)

    normalized_days = _positive_int(days)
    if normalized_days:
        clauses.append(
            f"datetime(COALESCE(NULLIF({prefix}disclosure_time, ''), {prefix}updated_at)) >= datetime('now', ?)"
        )
        parameters.append(f"-{normalized_days} days")
    if str(industry or "").strip():
        clauses.append(f"{prefix}industry LIKE ? ESCAPE '\\' COLLATE NOCASE")
        parameters.append(_like(str(industry)))
    if str(region or "").strip():
        clauses.append(
            f"({prefix}region LIKE ? ESCAPE '\\' COLLATE NOCASE "
            f"OR json_extract({prefix}event_metadata_json, '$.macro_region') LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend([_like(str(region))] * 2)
    if str(country or "").strip():
        clauses.append(
            f"(json_extract({prefix}event_metadata_json, '$.country') LIKE ? ESCAPE '\\' COLLATE NOCASE "
            f"OR json_extract({prefix}event_metadata_json, '$.country_code') LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend([_like(str(country))] * 2)
    if str(severity or "").strip():
        clauses.append(f"LOWER({prefix}severity) = ?")
        parameters.append(str(severity).strip().lower())
    if str(attacker or "").strip():
        clauses.append(f"{prefix}attacker LIKE ? ESCAPE '\\' COLLATE NOCASE")
        parameters.append(_like(str(attacker)))
    if str(category or "").strip():
        clauses.append(f"{prefix}category = ?")
        parameters.append(str(category).strip())
    normalized_source = str(source or "").strip().lower()
    if normalized_source in {"chat", "ransom", "forum", "public"}:
        source_text = f"LOWER({prefix}raw_source_type || ' ' || {prefix}source_kind || ' ' || {prefix}source_site_name)"
        source_expression = (
            f"CASE WHEN {source_text} LIKE '%telegram%' OR {source_text} LIKE '%chat%' THEN 'chat' "
            f"WHEN {source_text} LIKE '%victim%' OR {source_text} LIKE '%ransom%' THEN 'ransom' "
            f"WHEN {source_text} LIKE '%forum%' THEN 'forum' ELSE 'public' END"
        )
        clauses.append(f"({source_expression}) = ?")
        parameters.append(normalized_source)
    normalized_stage = str(stage or "").strip().lower()
    if normalized_stage:
        stage_text = f"LOWER({prefix}category || ' ' || {prefix}title)"
        published_patterns = ["%发布%", "%公开%", "%published%", "%released%", "%leak%"]
        countdown_patterns = ["%倒计时%", "%谈判%", "%countdown%", "%negotiat%"]
        if normalized_stage == "published":
            clauses.append("(" + " OR ".join(f"{stage_text} LIKE ?" for _ in published_patterns) + ")")
            parameters.extend(published_patterns)
        elif normalized_stage == "countdown":
            clauses.append("(" + " OR ".join(f"{stage_text} LIKE ?" for _ in countdown_patterns) + ")")
            parameters.extend(countdown_patterns)
        elif normalized_stage == "disclosed":
            all_patterns = published_patterns + countdown_patterns
            clauses.append("NOT (" + " OR ".join(f"{stage_text} LIKE ?" for _ in all_patterns) + ")")
            parameters.extend(all_patterns)
    if str(keyword or "").strip():
        pattern = _like(str(keyword))
        clauses.append(
            "(" + " OR ".join(
                f"{prefix}{column} LIKE ? ESCAPE '\\' COLLATE NOCASE"
                for column in (
                    "title", "attacker", "victim", "industry", "region",
                    "category", "detail_text", "event_metadata_json",
                )
            ) + ")"
        )
        parameters.extend([pattern] * 8)
    if min_risk_score is not None:
        try:
            threshold = max(0, min(100, int(min_risk_score)))
            clauses.append(f"{prefix}risk_score >= ?")
            parameters.append(threshold)
        except (TypeError, ValueError):
            pass
    return " AND ".join(clauses), parameters


def _normalized_order(sort: str | None, alias: str = "n") -> str:
    prefix = f"{alias}." if alias else ""
    time_expression = f"datetime(COALESCE(NULLIF({prefix}disclosure_time, ''), {prefix}updated_at))"
    normalized_sort = str(sort or "latest").strip().lower()
    if normalized_sort == "oldest":
        return f"{time_expression} ASC, {prefix}event_id ASC"
    if normalized_sort in {"severity", "risk"}:
        return f"{prefix}risk_score DESC, {time_expression} DESC, {prefix}event_id DESC"
    return f"{time_expression} DESC, {prefix}event_id DESC"


def _query_normalized_rows(
    connection,
    *,
    event_types: Iterable[str],
    limit: int,
    offset: int = 0,
    sort: str | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    where_clause, parameters = _normalized_where(event_types=event_types, **filters)
    rows = connection.execute(
        f"""
        SELECT {_NORMALIZED_COLUMNS}
        FROM normalized_intelligence_events n
        WHERE {where_clause}
        ORDER BY {_normalized_order(sort)}
        LIMIT ? OFFSET ?
        """,
        [*parameters, max(1, int(limit)), max(0, int(offset))],
    ).fetchall()
    return [_hydrate_event_row(dict(row)) for row in rows]


def _count_normalized(connection, *, event_types: Iterable[str], **filters: Any) -> int:
    where_clause, parameters = _normalized_where(event_types=event_types, **filters)
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM normalized_intelligence_events n WHERE {where_clause}",
            parameters,
        ).fetchone()[0]
    )


def _vulnerability_where(
    *,
    days: int | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    severity: str | None = None,
    attacker: str | None = None,
    keyword: str | None = None,
    min_risk_score: int | None = None,
    is_exploited: bool | None = None,
    vendor: str | None = None,
    product: str | None = None,
    alias: str = "v",
) -> tuple[str, list[object]]:
    prefix = f"{alias}." if alias else ""
    clauses = ["1 = 1"]
    parameters: list[object] = []
    normalized_days = _positive_int(days)
    if normalized_days:
        clauses.append(f"datetime({prefix}disclosure_time) >= datetime('now', ?)")
        parameters.append(f"-{normalized_days} days")
    if str(severity or "").strip():
        clauses.append(f"{prefix}effective_severity = ?")
        parameters.append(str(severity).strip().lower())
    if is_exploited is not None:
        clauses.append(f"{prefix}is_exploited = ?")
        parameters.append(int(bool(is_exploited)))
    if str(attacker or vendor or "").strip():
        clauses.append(f"{prefix}vendor LIKE ? ESCAPE '\\' COLLATE NOCASE")
        parameters.append(_like(str(attacker or vendor)))
    if str(product or "").strip():
        clauses.append(f"{prefix}product LIKE ? ESCAPE '\\' COLLATE NOCASE")
        parameters.append(_like(str(product)))
    if str(keyword or "").strip():
        pattern = _like(str(keyword))
        clauses.append(
            "(" + " OR ".join(
                f"{prefix}{column} LIKE ? ESCAPE '\\' COLLATE NOCASE"
                for column in ("cve_id", "title", "vendor", "product", "summary", "vulnerability_type")
            ) + ")"
        )
        parameters.extend([pattern] * 6)
    if min_risk_score is not None:
        try:
            clauses.append(f"{prefix}effective_risk_score >= ?")
            parameters.append(max(0, min(100, int(min_risk_score))))
        except (TypeError, ValueError):
            pass
    for requested, fixed_value in (
        (industry, "基础设施软件"),
        (region, "全球"),
        (country, "全球"),
    ):
        if str(requested or "").strip() and str(requested).strip().casefold() not in fixed_value.casefold():
            clauses.append("0 = 1")
    return " AND ".join(clauses), parameters


def _vulnerability_order(sort: str | None, alias: str = "v") -> str:
    prefix = f"{alias}." if alias else ""
    normalized_sort = str(sort or "latest").strip().lower()
    if normalized_sort == "oldest":
        return f"datetime({prefix}disclosure_time) ASC, {prefix}id ASC"
    if normalized_sort in {"severity", "risk"}:
        return f"{prefix}effective_risk_score DESC, datetime({prefix}disclosure_time) DESC, {prefix}id DESC"
    return f"datetime({prefix}disclosure_time) DESC, {prefix}id DESC"


def _materialize_vulnerability(row: dict[str, Any]) -> dict[str, Any]:
    event = _build_vulnerability_base_event(row)
    severity = str(event.get("severity") or "").lower()
    risk_score = {"critical": 85, "high": 72, "medium": 58}.get(severity, 55)
    if bool((event.get("metadata") or {}).get("is_exploited")):
        risk_score = min(100, risk_score + 10)
    return {
        **event,
        "source": (event.get("metadata") or {}).get("source") or "公开源",
        "risk_score": int(event.get("risk_score") or risk_score),
        "risk_reasons": event.get("risk_reasons") or [],
    }


def _query_vulnerability_rows(
    connection,
    *,
    limit: int,
    offset: int = 0,
    sort: str | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    where_clause, parameters = _vulnerability_where(**filters)
    rows = connection.execute(
        f"""
        {_VULNERABILITY_CTE}
        SELECT {_VULNERABILITY_COLUMNS}, effective_severity, effective_risk_score
        FROM deduped_vulnerabilities v
        WHERE {where_clause}
        ORDER BY {_vulnerability_order(sort)}
        LIMIT ? OFFSET ?
        """,
        [*parameters, max(1, int(limit)), max(0, int(offset))],
    ).fetchall()
    return [_materialize_vulnerability(dict(row)) for row in rows]


def _count_vulnerabilities(connection, **filters: Any) -> int:
    where_clause, parameters = _vulnerability_where(**filters)
    return int(
        connection.execute(
            f"{_VULNERABILITY_CTE} SELECT COUNT(*) FROM deduped_vulnerabilities v WHERE {where_clause}",
            parameters,
        ).fetchone()[0]
    )


def _page_payload(items: list[dict[str, Any]], total: int, page: int, page_size: int) -> dict[str, Any]:
    total_pages = (total + page_size - 1) // page_size
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
    }


def _clamped_page(total: int, page: int, page_size: int) -> int:
    total_pages = max(1, (total + page_size - 1) // page_size)
    return min(total_pages, max(1, page))


def _counter_rows(connection, sql: str, parameters: list[object], limit: int = 10) -> list[dict[str, Any]]:
    rows = connection.execute(sql, [*parameters, limit]).fetchall()
    return [{"name": str(row[0] or "未知"), "value": int(row[1] or 0)} for row in rows]


def build_ransomware_page(
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    keyword: str | None = None,
    stage: str | None = None,
    industry: str | None = None,
    days: int | None = None,
    severity: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    normalized_page, normalized_page_size = _bounded_page(page, page_size)
    filters = {
        "keyword": keyword,
        "stage": stage,
        "industry": industry,
        "days": days,
        "severity": severity,
    }
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            total = _count_normalized(connection, event_types=["ransomware"], **filters)
            normalized_page = _clamped_page(total, normalized_page, normalized_page_size)
            offset = (normalized_page - 1) * normalized_page_size
            raw_items = _query_normalized_rows(
                connection,
                event_types=["ransomware"],
                limit=normalized_page_size,
                offset=offset,
                sort=sort,
                **filters,
            )
            where_clause, parameters = _normalized_where(event_types=["ransomware"], **filters)
            actor_ranking = _counter_rows(
                connection,
                f"SELECT attacker, COUNT(*) FROM normalized_intelligence_events n WHERE {where_clause} "
                "AND TRIM(attacker) <> '' GROUP BY attacker ORDER BY COUNT(*) DESC, attacker COLLATE NOCASE LIMIT ?",
                parameters,
                6,
            )
            industry_ranking = _counter_rows(
                connection,
                f"SELECT industry, COUNT(*) FROM normalized_intelligence_events n WHERE {where_clause} "
                "AND TRIM(industry) <> '' GROUP BY industry ORDER BY COUNT(*) DESC, industry COLLATE NOCASE LIMIT ?",
                parameters,
                6,
            )
            timeline_rows = connection.execute(
                f"""
                SELECT date(COALESCE(NULLIF(disclosure_time, ''), updated_at)) AS bucket, COUNT(*)
                FROM normalized_intelligence_events n
                WHERE {where_clause}
                GROUP BY bucket
                ORDER BY bucket DESC
                LIMIT 30
                """,
                parameters,
            ).fetchall()
            stage_rows = connection.execute(
                f"SELECT category, COUNT(*) FROM normalized_intelligence_events n WHERE {where_clause} GROUP BY category",
                parameters,
            ).fetchall()
        finally:
            connection.rollback()

    items = [normalized_event_to_list_item(item) for item in raw_items]
    payload = _page_payload(items, total, normalized_page, normalized_page_size)
    payload.update(
        {
            "ransomwareEvents": items,
            "ransomwareActorRanking": actor_ranking,
            "ransomwareIndustryImpact": industry_ranking,
            "timeline": [
                {"date": str(row[0] or ""), "value": int(row[1] or 0)}
                for row in reversed(timeline_rows)
            ],
            "stageCounts": {str(row[0] or "未知"): int(row[1] or 0) for row in stage_rows},
        }
    )
    return payload


def build_data_leak_page(
    *,
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    category: str | None = None,
    days: int | None = None,
    attacker: str | None = None,
    industry: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    normalized_page, normalized_page_size = _bounded_page(page, page_size)
    filters = {
        "keyword": keyword,
        "category": category,
        "days": days,
        "attacker": attacker,
        "industry": industry,
        "severity": severity,
        "source": source,
    }
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            total = _count_normalized(connection, event_types=["data_leak"], **filters)
            normalized_page = _clamped_page(total, normalized_page, normalized_page_size)
            raw_items = _query_normalized_rows(
                connection,
                event_types=["data_leak"],
                limit=normalized_page_size,
                offset=(normalized_page - 1) * normalized_page_size,
                sort=sort,
                **filters,
            )
            categories = [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT DISTINCT category FROM normalized_intelligence_events
                    WHERE event_type = 'data_leak' AND TRIM(category) <> ''
                    ORDER BY category COLLATE NOCASE
                    """
                ).fetchall()
            ]
            all_total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM normalized_intelligence_events WHERE event_type = 'data_leak'"
                ).fetchone()[0]
            )
            victim_mentions = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM normalized_intelligence_events
                    WHERE event_type = 'data_leak' AND TRIM(victim) <> '' AND victim <> '未知实体'
                    """
                ).fetchone()[0]
            )
            attackers = [
                str(row[0]) for row in connection.execute(
                    """
                    SELECT DISTINCT attacker FROM normalized_intelligence_events
                    WHERE event_type = 'data_leak' AND TRIM(attacker) <> ''
                    ORDER BY attacker COLLATE NOCASE
                    """
                ).fetchall()
            ]
            industries = [
                str(row[0]) for row in connection.execute(
                    """
                    SELECT DISTINCT industry FROM normalized_intelligence_events
                    WHERE event_type = 'data_leak' AND TRIM(industry) <> ''
                    ORDER BY industry COLLATE NOCASE
                    """
                ).fetchall()
            ]
            source_filters = {key: value for key, value in filters.items() if key != "source"}
            source_where, source_parameters = _normalized_where(
                event_types=["data_leak"],
                **source_filters,
            )
            source_rows = connection.execute(
                f"""
                SELECT CASE
                         WHEN LOWER(raw_source_type || ' ' || source_kind || ' ' || source_site_name) LIKE '%telegram%'
                           OR LOWER(raw_source_type || ' ' || source_kind || ' ' || source_site_name) LIKE '%chat%' THEN 'chat'
                         WHEN LOWER(raw_source_type || ' ' || source_kind || ' ' || source_site_name) LIKE '%victim%'
                           OR LOWER(raw_source_type || ' ' || source_kind || ' ' || source_site_name) LIKE '%ransom%' THEN 'ransom'
                         WHEN LOWER(raw_source_type || ' ' || source_kind || ' ' || source_site_name) LIKE '%forum%' THEN 'forum'
                         ELSE 'public'
                       END AS source_key,
                       COUNT(*)
                FROM normalized_intelligence_events n
                WHERE {source_where}
                GROUP BY source_key
                """,
                source_parameters,
            ).fetchall()
        finally:
            connection.rollback()
    items = [normalized_event_to_list_item(item) for item in raw_items]
    payload = _page_payload(items, total, normalized_page, normalized_page_size)
    payload.update(
        {
            "dataLeakEvents": items,
            "categories": categories,
            "attackers": attackers,
            "industries": industries,
            "sourceCounts": {str(row[0] or "public"): int(row[1] or 0) for row in source_rows},
            "summary": [
                {
                    "label": "泄露事件", "value": str(all_total),
                    "description": "数据库中的数据泄露事件总数。",
                    "trend": "实时来自已接入论坛数据源", "tone": "warning", "icon": "DocumentRemove",
                },
                {
                    "label": "活跃板块", "value": str(len(categories)),
                    "description": "当前正在贡献数据的事件分类数量。",
                    "trend": "按数据库中的完整事件集合统计", "tone": "primary", "icon": "Files",
                },
                {
                    "label": "受害者提及", "value": str(victim_mentions),
                    "description": "从详情页内容中识别出的受害者实体。",
                    "trend": "已启用实体抽取", "tone": "success", "icon": "UserFilled",
                },
            ],
        }
    )
    return payload


def build_vulnerability_page(
    *,
    severity: str | None = None,
    is_exploited: bool | None = None,
    days: int | None = None,
    keyword: str | None = None,
    industry: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    sort: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    normalized_page, normalized_page_size = _bounded_page(page, page_size)
    filters = {
        "severity": severity,
        "is_exploited": is_exploited,
        "days": days,
        "keyword": keyword,
        "industry": industry,
        "vendor": vendor,
        "product": product,
    }
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            total = _count_vulnerabilities(connection, **filters)
            normalized_page = _clamped_page(total, normalized_page, normalized_page_size)
            raw_items = _query_vulnerability_rows(
                connection,
                limit=normalized_page_size,
                offset=(normalized_page - 1) * normalized_page_size,
                sort=sort,
                **filters,
            )
            where_clause, parameters = _vulnerability_where(**filters)
            severity_rows = connection.execute(
                f"{_VULNERABILITY_CTE} SELECT effective_severity, COUNT(*) FROM deduped_vulnerabilities v "
                f"WHERE {where_clause} GROUP BY effective_severity",
                parameters,
            ).fetchall()
            totals = connection.execute(
                f"{_VULNERABILITY_CTE} SELECT COUNT(*), SUM(is_exploited), SUM(patch_available), "
                f"SUM(CASE WHEN COALESCE(cvss, 0) >= 9 THEN 1 ELSE 0 END) "
                f"FROM deduped_vulnerabilities v WHERE {where_clause}",
                parameters,
            ).fetchone()
            vendor_ranking = _counter_rows(
                connection,
                f"{_VULNERABILITY_CTE} SELECT vendor, COUNT(*) FROM deduped_vulnerabilities v "
                f"WHERE {where_clause} AND TRIM(vendor) <> '' GROUP BY vendor ORDER BY COUNT(*) DESC, vendor LIMIT ?",
                parameters,
                6,
            )
            product_ranking = _counter_rows(
                connection,
                f"{_VULNERABILITY_CTE} SELECT product, COUNT(*) FROM deduped_vulnerabilities v "
                f"WHERE {where_clause} AND TRIM(product) <> '' GROUP BY product ORDER BY COUNT(*) DESC, product LIMIT ?",
                parameters,
                6,
            )
            timeline_rows = connection.execute(
                f"{_VULNERABILITY_CTE} SELECT date(disclosure_time), COUNT(*) FROM deduped_vulnerabilities v "
                f"WHERE {where_clause} GROUP BY date(disclosure_time) ORDER BY date(disclosure_time) DESC LIMIT 30",
                parameters,
            ).fetchall()
        finally:
            connection.rollback()

    items = [normalized_event_to_list_item(item) for item in raw_items]
    payload = _page_payload(items, total, normalized_page, normalized_page_size)
    payload.update(
        {
            "severityCounts": {str(row[0] or "low"): int(row[1] or 0) for row in severity_rows},
            "summary": {
                "total": int(totals[0] or 0),
                "exploited": int(totals[1] or 0),
                "patched": int(totals[2] or 0),
                "criticalCvss": int(totals[3] or 0),
            },
            "vendorRanking": vendor_ranking,
            "productRanking": product_ranking,
            "timeline": [
                {"date": str(row[0] or ""), "value": int(row[1] or 0)}
                for row in reversed(timeline_rows)
            ],
        }
    )
    return payload


def _fetch_normalized_by_ids(connection, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = connection.execute(
        f"SELECT {_NORMALIZED_COLUMNS} FROM normalized_intelligence_events WHERE event_id IN ({placeholders})",
        event_ids,
    ).fetchall()
    events = [_hydrate_event_row(dict(row)) for row in rows]
    return {str(event["event_id"]): event for event in events}


def _fetch_vulnerabilities_by_ids(connection, cve_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not cve_ids:
        return {}
    placeholders = ", ".join("?" for _ in cve_ids)
    rows = connection.execute(
        f"{_VULNERABILITY_CTE} SELECT {_VULNERABILITY_COLUMNS} FROM deduped_vulnerabilities "
        f"WHERE LOWER(cve_id) IN ({placeholders})",
        [item.lower() for item in cve_ids],
    ).fetchall()
    events = [_materialize_vulnerability(dict(row)) for row in rows]
    return {str((event.get("metadata") or {}).get("cve_id") or "").lower(): event for event in events}


def build_intelligence_search_page(
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    types: str | Iterable[str] | None = None,
    keyword: str | None = None,
    days: int | None = None,
    severity: str | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    attacker: str | None = None,
    min_risk_score: int | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    selected_types = _parse_types(types)
    normalized_types = [item for item in selected_types if item in NORMALIZED_EVENT_TYPES]
    include_vulnerability = "vulnerability" in selected_types
    normalized_filters = {
        "keyword": keyword, "days": days, "severity": severity, "industry": industry,
        "region": region, "country": country, "attacker": attacker,
        "min_risk_score": min_risk_score,
    }
    vulnerability_filters = dict(normalized_filters)
    normalized_page, normalized_page_size = _bounded_page(page, page_size)

    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            type_counts: dict[str, int] = {}
            for event_type in selected_types:
                if event_type == "vulnerability":
                    type_counts[event_type] = _count_vulnerabilities(connection, **vulnerability_filters)
                else:
                    type_counts[event_type] = _count_normalized(
                        connection, event_types=[event_type], **normalized_filters
                    )
            total = sum(type_counts.values())
            normalized_page = _clamped_page(total, normalized_page, normalized_page_size)
            offset = (normalized_page - 1) * normalized_page_size

            normalized_where, normalized_parameters = _normalized_where(
                event_types=normalized_types, **normalized_filters
            )
            vulnerability_where, vulnerability_parameters = _vulnerability_where(**vulnerability_filters)
            normalized_branch = f"""
                SELECT 'normalized' AS storage_kind, n.event_id AS record_key,
                       n.event_type AS event_type,
                       COALESCE(NULLIF(n.disclosure_time, ''), n.updated_at) AS sort_time,
                       n.risk_score AS sort_risk
                FROM normalized_intelligence_events n
                WHERE {normalized_where}
            """
            vulnerability_branch = f"""
                SELECT 'vulnerability' AS storage_kind, LOWER(v.cve_id) AS record_key,
                       'vulnerability' AS event_type, v.disclosure_time AS sort_time,
                       v.effective_risk_score AS sort_risk
                FROM deduped_vulnerabilities v
                WHERE {vulnerability_where if include_vulnerability else '0 = 1'}
            """
            normalized_sort = str(sort or "latest").strip().lower()
            if normalized_sort == "oldest":
                locator_order = "datetime(sort_time) ASC, record_key ASC"
            elif normalized_sort in {"severity", "risk"}:
                locator_order = "sort_risk DESC, datetime(sort_time) DESC, record_key DESC"
            else:
                locator_order = "datetime(sort_time) DESC, record_key DESC"
            locator_rows = connection.execute(
                f"""
                {_VULNERABILITY_CTE}
                SELECT * FROM (
                    {normalized_branch}
                    UNION ALL
                    {vulnerability_branch}
                )
                ORDER BY {locator_order}
                LIMIT ? OFFSET ?
                """,
                [
                    *normalized_parameters,
                    *(vulnerability_parameters if include_vulnerability else []),
                    normalized_page_size,
                    offset,
                ],
            ).fetchall()
            normalized_ids = [str(row["record_key"]) for row in locator_rows if row["storage_kind"] == "normalized"]
            vulnerability_ids = [str(row["record_key"]) for row in locator_rows if row["storage_kind"] == "vulnerability"]
            normalized_events = _fetch_normalized_by_ids(connection, normalized_ids)
            vulnerability_events = _fetch_vulnerabilities_by_ids(connection, vulnerability_ids)

            recent_counts = {}
            recent_normalized_filters = {**normalized_filters, "days": 1}
            recent_vulnerability_filters = {**vulnerability_filters, "days": 1}
            for event_type in selected_types:
                if event_type == "vulnerability":
                    recent_counts[event_type] = _count_vulnerabilities(connection, **recent_vulnerability_filters)
                else:
                    recent_counts[event_type] = _count_normalized(
                        connection, event_types=[event_type], **recent_normalized_filters
                    )
        finally:
            connection.rollback()

    items: list[dict[str, Any]] = []
    for locator in locator_rows:
        record_key = str(locator["record_key"])
        if locator["storage_kind"] == "vulnerability":
            event = vulnerability_events.get(record_key.lower())
        else:
            event = normalized_events.get(record_key)
        if event is not None:
            items.append(normalized_event_to_list_item(event))
    payload = _page_payload(items, total, normalized_page, normalized_page_size)
    payload.update(
        {
            "typeCounts": type_counts,
            "recent24h": sum(recent_counts.values()),
            "recent24hByType": recent_counts,
        }
    )
    return payload


def query_ai_events(
    connection,
    *,
    event_type: str | None,
    days: int | None,
    industry: str | None,
    region: str | None,
    country: str | None,
    severity: str | None,
    attacker: str | None,
    keyword: str | None,
    min_risk_score: int | None,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    selected_types = _parse_types(event_type)
    common_filters = {
        "days": days, "industry": industry, "region": region, "country": country,
        "severity": severity, "attacker": attacker, "keyword": keyword,
        "min_risk_score": min_risk_score,
    }
    candidates: list[dict[str, Any]] = []
    matched_count = 0
    for selected_type in selected_types:
        if selected_type == "vulnerability":
            matched_count += _count_vulnerabilities(connection, **common_filters)
            candidates.extend(
                _query_vulnerability_rows(connection, limit=limit, sort="latest", **common_filters)
            )
        else:
            matched_count += _count_normalized(
                connection, event_types=[selected_type], **common_filters
            )
            candidates.extend(
                _query_normalized_rows(
                    connection,
                    event_types=[selected_type],
                    limit=limit,
                    sort="latest",
                    **common_filters,
                )
            )
    return candidates, matched_count


def iter_csv_rows(dataset: str, parameters: dict[str, Any]) -> Iterator[bytes]:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "类型", "披露时间", "标题", "攻击者/厂商", "受害者/产品", "行业", "地区", "严重性", "风险分"]
    )
    yield "\ufeff".encode("utf-8") + output.getvalue().encode("utf-8")
    page = 1
    while True:
        if dataset == "ransomware":
            payload = build_ransomware_page(page=page, page_size=MAX_PAGE_SIZE, **parameters)
        elif dataset == "data_leak":
            payload = build_data_leak_page(page=page, page_size=MAX_PAGE_SIZE, **parameters)
        elif dataset == "vulnerability":
            payload = build_vulnerability_page(page=page, page_size=MAX_PAGE_SIZE, **parameters)
        else:
            payload = build_intelligence_search_page(page=page, page_size=MAX_PAGE_SIZE, **parameters)
        items = payload.get("items") or []
        if not items:
            return
        for item in items:
            output.seek(0)
            output.truncate(0)
            writer.writerow(
                [
                    item.get("id"), item.get("normalized_event_type"), item.get("disclosureTimeRaw"),
                    item.get("title"), item.get("attacker") or item.get("vendor"),
                    item.get("victim") or item.get("product"), item.get("industry"), item.get("region"),
                    item.get("severity"), item.get("riskScore"),
                ]
            )
            yield output.getvalue().encode("utf-8")
        if page >= int(payload.get("totalPages") or 0):
            return
        page += 1
