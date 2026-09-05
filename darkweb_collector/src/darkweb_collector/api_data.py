from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

import darkweb_collector.intelligence_queries as intelligence_queries_module
import darkweb_collector.intelligence_aggregates as intelligence_aggregates_module
import darkweb_collector.monitoring_rules as monitoring_rules_module
from darkweb_collector.config import get_site_config, load_site_configs
from darkweb_collector.detail_i18n import translate_event_detail_text_live
from darkweb_collector.document_exposure import (
    build_document_exposure_event_detail,
    build_document_exposure_event_records,
    build_document_exposure_summary,
)
from darkweb_collector.db import (
    get_db_connection,
    database_identity,
    get_normalized_intelligence_cache_state,
    get_readonly_db_connection,
    list_vulnerability_records,
)
from darkweb_collector.normalized_intelligence import (
    _build_vulnerability_base_event,
    _normalise_forum_timestamp,
    build_display_title,
    load_normalized_event_detail,
    load_normalized_event_page,
    load_normalized_events,
    normalized_event_to_detail,
    normalized_event_to_list_item,
)
from darkweb_collector.runtime import default_db_path, project_root
from darkweb_collector.utils import safe_stem


SECTION_LABELS = {
    "databases": "数据库板块",
    "other_leaks": "其他泄露板块",
    "sellers_place": "卖家交易板块",
}

STATUS_LABELS = {
    "published": "已公开",
    "going": "协商中",
    "transferring": "传输中",
    "stopped": "已停止",
}

INDUSTRY_LABELS = {
    "other": "其他",
    "unknown": "未知",
    "government": "政府",
    "finance": "金融",
    "healthcare": "医疗",
    "technology": "科技",
    "military": "军事",
    "agriculture": "农业",
    "retail": "零售",
    "education": "教育",
    "telecommunications": "通信",
    "energy": "能源",
    "transportation": "交通",
    "entertainment": "文娱",
}

INDUSTRY_LABELS.update(
    {
        "public sector": "政府",
        "financial services": "金融",
        "agriculture and food production": "农业",
        "consumer services": "零售",
        "telecommunication": "通信",
        "transportation/logistics": "交通",
        "hospitality and tourism": "文娱",
        "manufacturing": "制造业",
        "construction": "制造业",
        "business services": "其他",
    }
)

REGION_LABELS = {
    "unknown": "未知",
    "north_america": "北美",
    "europe": "欧洲",
    "asia": "亚洲",
    "middle_east": "中东",
    "africa": "非洲",
    "oceania": "大洋洲",
    "south_america": "南美",
}

JOB_STATUS_LABELS = {
    "succeeded": "成功",
    "failed": "失败",
    "running": "运行中",
    "enqueued": "已入队",
    "stale": "异常挂起",
}

RECENT_FAILURE_WINDOW_HOURS = 24
STALE_RUNNING_MINUTES = 30
STALE_ENQUEUED_MINUTES = 10
RANSOMWARE_EVENT_LIMIT = 0
RANSOMWARE_SOURCE_QUERY_LIMIT = 0
DATA_LEAK_EVENT_LIMIT = 3000
VULNERABILITY_EVENT_LIMIT = 500

_PAYLOAD_CACHE_LOCK = Lock()
_PAYLOAD_CACHE: dict[str, dict[str, Any]] = {}
PAYLOAD_CACHE_VERSION = "2026-04-11-executive-country-v2"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_dt(value: str | None) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return value or ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _apply_event_limit(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    try:
        normalized = int(limit)
    except (TypeError, ValueError):
        return items
    if normalized <= 0:
        return items
    return items[:normalized]


def _format_date(value: str | None) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return (value or "").split(" ", 1)[0]
    return dt.strftime("%Y-%m-%d")


def _weekday_cn(dt: datetime) -> str:
    names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return names[dt.weekday()]


def _label_industry(value: str | None) -> str:
    """标准化行业标签，支持中英文映射"""
    raw = (value or "").strip()
    lowered = raw.lower()
    
    # 英文关键词映射
    if "manufact" in lowered or "construction" in lowered:
        return "制造业"
    if "business services" in lowered:
        return "其他"
    if "consumer services" in lowered or "retail" in lowered:
        return "零售"
    if "transport" in lowered or "logistics" in lowered:
        return "交通"
    if "hospitality" in lowered or "tourism" in lowered or "entertainment" in lowered:
        return "文娱"
    if "public sector" in lowered or "government" in lowered:
        return "政府"
    if "financial services" in lowered or "finance" in lowered:
        return "金融"
    if "healthcare" in lowered:
        return "医疗"
    if "technology" in lowered:
        return "科技"
    if "agriculture" in lowered:
        return "农业"
    if "telecommunication" in lowered:
        return "通信"
    if "energy" in lowered:
        return "能源"
    if "education" in lowered:
        return "教育"
    
    # 回退到字典查找
    return INDUSTRY_LABELS.get(lowered, INDUSTRY_LABELS.get(raw, raw or "未知"))


def _label_region(value: str | None) -> str:
    raw = (value or "").strip()
    return REGION_LABELS.get(raw, raw or "未知")


def _label_source(value: str | None) -> str:
    return (value or "").strip() or "未知"


def _label_job_status(value: str | None) -> str:
    raw = (value or "").strip()
    return JOB_STATUS_LABELS.get(raw, raw or "未知")


def _event_hash(*parts: str) -> str:
    payload = "|".join((part or "").strip() for part in parts)
    return sha1(payload.encode("utf-8")).hexdigest()[:16]


def _parse_event_id(event_id: str) -> dict[str, str] | None:
    parts = (event_id or "").split(":")
    if len(parts) == 4 and parts[0] == "forum":
        return {
            "event_type": "forum",
            "site_name": parts[1],
            "section": parts[2],
            "hash": parts[3],
        }
    if len(parts) == 3 and parts[0] == "victim":
        return {
            "event_type": "victim",
            "site_name": parts[1],
            "hash": parts[2],
        }
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_recent(value: str | None, hours: int) -> bool:
    dt = _parse_dt(value)
    if dt is None:
        return False
    return dt >= (_now_utc() - timedelta(hours=hours))


def _is_stale_running(started_at: str | None, finished_at: str | None) -> bool:
    if finished_at:
        return False
    started = _parse_dt(started_at)
    if started is None:
        return False
    return started < (_now_utc() - timedelta(minutes=STALE_RUNNING_MINUTES))


def _is_stale_enqueued(enqueued_at: str | None, started_at: str | None, finished_at: str | None) -> bool:
    if started_at or finished_at:
        return False
    enqueued = _parse_dt(enqueued_at)
    if enqueued is None:
        return False
    return enqueued < (_now_utc() - timedelta(minutes=STALE_ENQUEUED_MINUTES))


def _effective_job_status(row: dict[str, Any]) -> str:
    status = row.get("status") or ""
    if status == "enqueued" and _is_stale_enqueued(row.get("enqueued_at"), row.get("started_at"), row.get("finished_at")):
        return "stale"
    if status == "running" and _is_stale_running(row.get("started_at"), row.get("finished_at")):
        return "stale"
    return status


def _job_event_dt(row: dict[str, Any] | None) -> datetime | None:
    if row is None:
        return None
    return _parse_dt(row.get("finished_at") or row.get("started_at") or row.get("enqueued_at"))


def _last_days(days: int = 7) -> list[datetime]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days - 1)
    return [start + timedelta(days=index) for index in range(days)]


def _series_from_counter(counter: Counter[str], days: int = 7) -> dict[str, list[Any]]:
    dates = _last_days(days)
    labels = [item.strftime("%m-%d") for item in dates]
    values = [int(counter.get(item.date().isoformat(), 0)) for item in dates]
    return {"labels": labels, "values": values}


def _count_by_day(values: list[str | None]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for raw in values:
        dt = _parse_dt(raw)
        if dt is None:
            continue
        counter[dt.date().isoformat()] += 1
    return counter


def _build_monitoring_status(forum_details: list[dict[str, Any]], crawl_jobs: list[dict[str, Any]]) -> dict[str, str]:
    latest_refresh = ""
    if crawl_jobs:
        latest_refresh = _format_dt(crawl_jobs[0].get("finished_at") or crawl_jobs[0].get("started_at"))
    elif forum_details:
        latest_refresh = _format_dt(forum_details[0].get("fetched_at"))

    site_names = sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")})
    failed_jobs = sum(
        1 for site_name in site_names if _latest_unresolved_problem_row([row for row in crawl_jobs if row.get("site_name") == site_name]) is not None
    )
    now_local = datetime.now().astimezone()
    return {
        "dateLabel": f"{now_local.strftime('%Y-%m-%d')} {_weekday_cn(now_local)}",
        "subtitle": "基于采集器 SQLite 数据库实时生成的威胁情报视图。",
        "scope": "覆盖论坛详情、受害者记录与爬虫任务审计数据。",
        "statusLabel": "采集状态",
        "statusValue": "采集中" if failed_jobs == 0 else "部分失败",
        "refreshedLabel": "最近刷新",
        "refreshedValue": latest_refresh or "暂无运行记录",
    }



def _recent_problem_rows(crawl_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in crawl_jobs
        if _effective_job_status(row) in {"failed", "stale"}
        and _is_recent(row.get("finished_at") or row.get("started_at"), RECENT_FAILURE_WINDOW_HOURS)
    ]


def _latest_succeeded_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("status") == "succeeded"), None)


def _latest_unresolved_problem_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest_success_dt = _job_event_dt(_latest_succeeded_row(rows))
    for row in rows:
        if _effective_job_status(row) not in {"failed", "stale"}:
            continue
        row_dt = _job_event_dt(row)
        if row_dt is None:
            continue
        if not _is_recent(row.get("finished_at") or row.get("started_at"), RECENT_FAILURE_WINDOW_HOURS):
            continue
        if latest_success_dt is not None and row_dt <= latest_success_dt:
            continue
        return row
    return None


def _build_data_leak_events(forum_details: list[dict[str, Any]]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for row in forum_details[:50]:
        event_id = f"forum:{row['site_name']}:{row['section']}:{_event_hash(row['topic_url'])}"
        events.append(
            {
                "id": event_id,
                "disclosureTime": _format_dt(row.get("fetched_at")),
                "title": row.get("title") or row.get("topic_url") or "未命名论坛帖子",
                "category": SECTION_LABELS.get(row.get("section", ""), row.get("section", "未知")),
                "attacker": row.get("attackers") or _label_source(row.get("site_name")),
                "industry": _label_industry(row.get("industry")),
                "region": _label_region(row.get("region")),
                "severity": "high" if row.get("section") == "databases" else "medium",
                "victim": row.get("victims") or "",
            }
        )
    return events


def _build_ransomware_events(victim_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for row in _apply_event_limit(victim_rows, RANSOMWARE_EVENT_LIMIT):
        raw_json = _parse_json(row.get("raw_json"))
        detail_url = row.get("detail_url") or raw_json.get("detail_url") or ""
        event_id = f"victim:{row['site_name']}:{_event_hash(detail_url or row.get('name', ''))}"
        events.append(
            {
                "id": event_id,
                "disclosureTime": _format_dt(row.get("published_at_utc") or row.get("last_seen_at")),
                "title": row.get("display_label") or row.get("name") or "未知受害者",
                "category": STATUS_LABELS.get(row.get("status", ""), row.get("status", "未知")),
                "attacker": _label_source(row.get("site_name")),
                "industry": _label_industry(row.get("industry")),
                "region": _label_region(row.get("region")),
                "severity": "high" if row.get("status") == "published" else "medium",
            }
        )
    return events


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _coerce_resource_list(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                if url:
                    normalized.append(
                        {
                            "label": str(item.get("name") or url),
                            "url": url,
                        }
                    )
            elif isinstance(item, str) and item.strip():
                normalized.append({"label": item.strip(), "url": item.strip()})
        return normalized
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
        return [{"label": item, "url": item} for item in items]
    return []


def _site_output_dir(site_name: str) -> Path | None:
    try:
        return get_site_config(site_name).output_dir
    except Exception:
        return None


def _public_output_url(path: Path) -> str:
    output_root = project_root() / "output"
    try:
        relative_path = path.resolve().relative_to(output_root.resolve())
    except ValueError:
        return path.resolve().as_uri()
    return f"/collector-output/{relative_path.as_posix()}"


def _resource_entry(path: Path, label: str) -> dict[str, str]:
    return {
        "label": label,
        "url": _public_output_url(path),
    }


def _forum_output_resources(row_dict: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    output_dir = _site_output_dir(row_dict["site_name"])
    if output_dir is None:
        return [], []
    topic_url = str(row_dict.get("topic_url") or "")
    if not topic_url:
        return [], []
    section = str(row_dict.get("section") or "section")
    artifact_stem = _event_hash(topic_url)[:10]
    detail_dir = output_dir / section / "details"
    resources = []
    screenshots = []
    html_path = detail_dir / f"{artifact_stem}.html"
    json_path = detail_dir / f"{artifact_stem}.json"
    png_path = detail_dir / f"{artifact_stem}.png"
    if html_path.exists():
        resources.append(_resource_entry(html_path, "本地HTML镜像"))
    if json_path.exists():
        resources.append(_resource_entry(json_path, "本地JSON镜像"))
    if png_path.exists():
        screenshots.append(_resource_entry(png_path, "详情截图"))
    return resources, screenshots


def _victim_output_resources(row_dict: dict[str, Any], raw_json: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    output_dir = _site_output_dir(row_dict["site_name"])
    if output_dir is None:
        return [], []

    content_hash = str(raw_json.get("content_hash") or row_dict.get("content_hash") or "")
    domain = str(raw_json.get("domain") or row_dict.get("domain") or "")
    name = str(raw_json.get("name") or row_dict.get("name") or "")
    if row_dict["site_name"] == "lynx":
        artifact_stem = safe_stem(f"{content_hash[:10]}_{name[:30]}")
    else:
        artifact_stem = safe_stem(f"{content_hash[:10]}_{domain or name}")

    detail_dir = output_dir / "details"
    resources = []
    screenshots = []
    html_path = detail_dir / f"{artifact_stem}.html"
    json_path = detail_dir / f"{artifact_stem}.json"
    png_path = detail_dir / f"{artifact_stem}.png"
    if html_path.exists():
        resources.append(_resource_entry(html_path, "本地HTML镜像"))
    if json_path.exists():
        resources.append(_resource_entry(json_path, "本地JSON镜像"))
    if png_path.exists():
        screenshots.append(_resource_entry(png_path, "详情截图"))
    return resources, screenshots


def _build_forum_event_payload(row_dict: dict[str, Any]) -> dict[str, Any]:
    raw_json = _parse_json(row_dict.get("raw_json"))
    attackers = row_dict.get("attackers") or raw_json.get("attackers") or ""
    victims = row_dict.get("victims") or raw_json.get("victims") or ""
    disclosure_time = (
        raw_json.get("published_at_utc")
        or _normalise_forum_timestamp(
            row_dict.get("site_name"),
            raw_json.get("timestamp") or row_dict.get("timestamps"),
            collected_at_utc=row_dict.get("fetched_at"),
        )
        or row_dict.get("fetched_at")
    )
    event_id = f"forum:{row_dict['site_name']}:{row_dict['section']}:{_event_hash(str(row_dict['topic_url']))}"
    local_mirror_resources, local_screenshot_resources = _forum_output_resources(row_dict)
    mirror_resources = _coerce_resource_list(row_dict.get("attachments"))
    mirror_resources.extend(local_mirror_resources)
    if row_dict.get("topic_url"):
        mirror_resources.append({"label": "原始披露链接", "url": str(row_dict["topic_url"])})

    return {
        "id": event_id,
        "event_type": "forum",
        "raw_source_type": "forum_details",
        "title": row_dict.get("title") or row_dict.get("topic_url") or "未命名论坛帖子",
        "disclosure_time": _format_dt(disclosure_time),
        "attacker": attackers or _label_source(row_dict.get("site_name")),
        "disclosure_url": row_dict.get("topic_url") or "",
        "detail_text": row_dict.get("content") or "",
        "category": SECTION_LABELS.get(row_dict.get("section", ""), row_dict.get("section", "未知")),
        "source": _label_source(row_dict.get("site_name")),
        "industry": _label_industry(row_dict.get("industry")),
        "region": _label_region(row_dict.get("region")),
        "mirror_resources": mirror_resources,
        "screenshot_resources": local_screenshot_resources,
        "json_preview_url": next((item["url"] for item in mirror_resources if item["url"].endswith(".json")), ""),
        "victim": victims,
    }


def _build_victim_event_payload(row_dict: dict[str, Any]) -> dict[str, Any]:
    raw_json = _parse_json(row_dict.get("raw_json"))
    detail_url = row_dict.get("detail_url") or raw_json.get("detail_url") or ""
    event_id = f"victim:{row_dict['site_name']}:{_event_hash(str(detail_url or row_dict.get('name', '')))}"
    local_mirror_resources, local_screenshot_resources = _victim_output_resources(row_dict, raw_json)
    mirror_resources = _coerce_resource_list(detail_url)
    mirror_resources.extend(local_mirror_resources)
    screenshot_resources = _coerce_resource_list(raw_json.get("thumbnails"))
    screenshot_resources.extend(local_screenshot_resources)

    return {
        "id": event_id,
        "event_type": "victim",
        "raw_source_type": "victims",
        "title": row_dict.get("display_label") or row_dict.get("name") or "未知受害者",
        "disclosure_time": _format_dt(row_dict.get("published_at_utc") or row_dict.get("fetched_at_utc")),
        "attacker": _label_source(row_dict.get("site_name")),
        "disclosure_url": detail_url,
        "detail_text": row_dict.get("text_excerpt") or raw_json.get("description") or "",
        "category": STATUS_LABELS.get(row_dict.get("status", ""), row_dict.get("status", "未知")),
        "source": _label_source(row_dict.get("site_name")),
        "industry": _label_industry(raw_json.get("industry")),
        "region": _label_region(raw_json.get("region")),
        "mirror_resources": mirror_resources,
        "screenshot_resources": screenshot_resources,
        "json_preview_url": next((item["url"] for item in mirror_resources if item["url"].endswith(".json")), ""),
        "victim": row_dict.get("name") or "",
    }


def _build_forum_event_records(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT d.site_name, d.section, d.topic_url, d.content, d.attachments, d.victims, d.attackers, d.fetched_at, d.raw_json,
               COALESCE(t.title, d.topic_url) AS title,
               COALESCE((SELECT industry FROM forum_victims fv WHERE fv.forum_detail_id = d.id LIMIT 1), 'other') AS industry,
               COALESCE((SELECT region FROM forum_victims fv WHERE fv.forum_detail_id = d.id LIMIT 1), 'unknown') AS region
        FROM forum_details d
        LEFT JOIN forum_topics t
          ON t.site_name = d.site_name
         AND t.section = d.section
         AND t.url = d.topic_url
        ORDER BY datetime(d.fetched_at) DESC
        """
    ).fetchall()
    return [_build_forum_event_payload(dict(row)) for row in rows]


def _build_victim_event_records(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT v.site_name, v.name, v.display_label, v.detail_url, v.status, v.published_at_utc, v.raw_json,
               v.last_detail_fetch_status, vd.text_excerpt, vd.page_title, vd.fetched_at_utc
        FROM victims v
        LEFT JOIN victim_details vd
          ON vd.victim_id = v.id
        ORDER BY COALESCE(vd.fetched_at_utc, v.published_at_utc, v.id) DESC
        """
    ).fetchall()
    events = []
    seen: set[str] = set()
    for row in rows:
        row_dict = dict(row)
        event_id = _build_victim_event_payload(row_dict)["id"]
        if event_id in seen:
            continue
        seen.add(event_id)
        events.append(_build_victim_event_payload(row_dict))
    return events


def build_event_records(limit: int | None = None) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        normalized_events, _ = monitoring_rules_module.build_monitoring_payload(connection, load_normalized_events(connection))

    events = build_document_exposure_event_records(limit=None) + [normalized_event_to_detail(item) for item in normalized_events]
    events.sort(
        key=lambda item: _parse_dt(
            str(
                item.get("updatedTimeRaw")
                or item.get("updated_time_raw")
                or item.get("disclosureTimeRaw")
                or item.get("disclosure_time_raw")
                or item.get("disclosureTime")
                or item.get("disclosure_time")
                or ""
            )
        )
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if limit is not None:
        return events[:limit]
    return events


def _build_forum_event_detail_by_id(
    connection,
    site_name: str,
    section: str,
    hash_value: str,
) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT d.site_name, d.section, d.topic_url, d.content, d.attachments, d.victims, d.attackers, d.fetched_at, d.raw_json,
               COALESCE(t.title, d.topic_url) AS title,
               COALESCE((SELECT industry FROM forum_victims fv WHERE fv.forum_detail_id = d.id LIMIT 1), 'other') AS industry,
               COALESCE((SELECT region FROM forum_victims fv WHERE fv.forum_detail_id = d.id LIMIT 1), 'unknown') AS region
        FROM forum_details d
        LEFT JOIN forum_topics t
          ON t.site_name = d.site_name
         AND t.section = d.section
         AND t.url = d.topic_url
        WHERE d.site_name = ? AND d.section = ?
        ORDER BY datetime(d.fetched_at) DESC
        """,
        (site_name, section),
    ).fetchall()
    for row in rows:
        row_dict = dict(row)
        if _event_hash(str(row_dict.get("topic_url") or "")) == hash_value:
            return _build_forum_event_payload(row_dict)
    return None


def _build_victim_event_detail_by_id(
    connection,
    site_name: str,
    hash_value: str,
) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT v.site_name, v.name, v.display_label, v.detail_url, v.status, v.published_at_utc, v.raw_json,
               v.last_detail_fetch_status, v.content_hash, v.domain, vd.text_excerpt, vd.page_title, vd.fetched_at_utc
        FROM victims v
        LEFT JOIN victim_details vd
          ON vd.victim_id = v.id
        WHERE v.site_name = ?
        ORDER BY COALESCE(vd.fetched_at_utc, v.published_at_utc, v.id) DESC
        """,
        (site_name,),
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        row_dict = dict(row)
        raw_json = _parse_json(row_dict.get("raw_json"))
        detail_url = row_dict.get("detail_url") or raw_json.get("detail_url") or ""
        event_id = f"victim:{row_dict['site_name']}:{_event_hash(str(detail_url or row_dict.get('name', '')))}"
        if event_id in seen:
            continue
        seen.add(event_id)
        if event_id.split(":", 2)[2] == hash_value:
            return _build_victim_event_payload(row_dict)
    return None


def _build_raw_event_detail_by_id(connection, event_id: str) -> dict[str, Any] | None:
    parsed = _parse_event_id(event_id)
    if parsed is None:
        return None
    if parsed["event_type"] == "forum":
        return _build_forum_event_detail_by_id(
            connection,
            site_name=parsed["site_name"],
            section=parsed["section"],
            hash_value=parsed["hash"],
        )
    if parsed["event_type"] == "victim":
        return _build_victim_event_detail_by_id(
            connection,
            site_name=parsed["site_name"],
            hash_value=parsed["hash"],
        )
    return None


def _merge_event_detail_payload(base: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in ("disclosure_url", "detail_text", "victim"):
        if not merged.get(key) and fallback.get(key):
            merged[key] = fallback[key]
    for key in ("industry", "region"):
        if merged.get(key) in {"", "未知"} and fallback.get(key) not in {"", "未知", None}:
            merged[key] = fallback[key]
    if not merged.get("mirror_resources") and fallback.get("mirror_resources"):
        merged["mirror_resources"] = fallback["mirror_resources"]
    if not merged.get("screenshot_resources") and fallback.get("screenshot_resources"):
        merged["screenshot_resources"] = fallback["screenshot_resources"]
    if not merged.get("json_preview_url") and fallback.get("json_preview_url"):
        merged["json_preview_url"] = fallback["json_preview_url"]
    merged.setdefault("identifier", merged.get("id") or fallback.get("id") or "")
    return merged


def _raw_event_detail_compat(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the legacy detail shape without refreshing the normalized snapshot."""
    compatible = dict(payload)
    source_type = str(compatible.get("event_type") or "")
    normalized_type = "data_leak" if source_type == "forum" else "ransomware" if source_type == "victim" else source_type
    original_title = str(compatible.get("title") or "")
    compatible["original_title"] = original_title
    compatible["normalized_event_type"] = normalized_type
    compatible["title"] = build_display_title(
        {
            "title": original_title,
            "event_type": normalized_type,
            "leak_type": "数据泄露" if normalized_type == "data_leak" else "勒索情报",
            "category": compatible.get("category") or "",
            "victim": compatible.get("victim") or "",
            "attacker": compatible.get("attacker") or "",
            "metadata": {},
        }
    )
    compatible.setdefault("severity", "high" if normalized_type in {"data_leak", "ransomware"} else "medium")
    compatible.setdefault("risk_score", 72 if compatible["severity"] == "high" else 58)
    compatible.setdefault("risk_reasons", [])
    compatible.setdefault("identifier", compatible.get("id") or "")
    return compatible


def build_event_detail(event_id: str, *, translate_detail: bool = False) -> dict[str, Any] | None:
    if str(event_id or "").startswith("document:"):
        payload = build_document_exposure_event_detail(event_id)
        if payload is None:
            return None
        if translate_detail and payload.get("detail_text"):
            payload["detail_text"] = translate_event_detail_text_live(payload.get("detail_text"))
        return payload
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            event = load_normalized_event_detail(connection, event_id, allow_refresh=False)
            fallback_payload = _build_raw_event_detail_by_id(connection, event_id)
            if event is None:
                payload = _raw_event_detail_compat(fallback_payload) if fallback_payload is not None else None
                if payload is None:
                    return None
            else:
                enriched_events, _ = monitoring_rules_module.build_monitoring_payload(
                    connection,
                    [event],
                    persist_default_keywords=False,
                )
                payload = normalized_event_to_detail(enriched_events[0] if enriched_events else event)
                if fallback_payload is not None:
                    payload = _merge_event_detail_payload(payload, fallback_payload)
        finally:
            connection.rollback()
    payload.setdefault("identifier", payload.get("id") or event_id)
    if translate_detail and payload.get("normalized_event_type") != "vulnerability":
        payload["detail_text"] = translate_event_detail_text_live(payload.get("detail_text"))
    return payload


def build_vulnerability_records(
    *,
    severity: str | None = None,
    is_exploited: bool | None = None,
    days: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = list_vulnerability_records(connection)

    raw_events = [
        normalized_event_to_list_item(_materialize_vulnerability_event(row))
        for row in rows
    ]
    deduped_map: dict[str, dict[str, Any]] = {}
    for item in raw_events:
        key = str(item.get("cveId") or item.get("id") or "")
        if not key:
            continue
        current = deduped_map.get(key)
        if current is None:
            deduped_map[key] = item
            continue
        current_dt = _parse_dt(str(current.get("updatedTimeRaw") or current.get("disclosureTimeRaw") or ""))
        item_dt = _parse_dt(str(item.get("updatedTimeRaw") or item.get("disclosureTimeRaw") or ""))
        if item_dt is not None and (current_dt is None or item_dt >= current_dt):
            deduped_map[key] = item

    vulnerability_events = list(deduped_map.values())
    filtered: list[dict[str, Any]] = []
    cutoff = _now_utc() - timedelta(days=days) if days else None
    severity_filter = (severity or "").strip().lower()
    for item in vulnerability_events:
        if severity_filter and str(item.get("severity") or "").lower() != severity_filter:
            continue
        if is_exploited is not None and bool(item.get("isExploited")) != bool(is_exploited):
            continue
        if cutoff is not None:
            event_dt = _parse_dt(str(item.get("disclosureTime") or "").replace(" ", "T"))
            if event_dt is None or event_dt < cutoff:
                continue
        filtered.append(item)
    filtered.sort(
        key=lambda item: _parse_dt(str(item.get("disclosureTime") or "").replace(" ", "T")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if limit is not None:
        return filtered[:limit]
    return filtered


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
    page_size: int = 20,
) -> dict[str, Any]:
    return intelligence_queries_module.build_vulnerability_page(
        severity=severity,
        is_exploited=is_exploited,
        days=days,
        keyword=keyword,
        industry=industry,
        vendor=vendor,
        product=product,
        sort=sort,
        page=page,
        page_size=page_size,
    )


def build_vulnerability_detail(event_id: str) -> dict[str, Any] | None:
    cve_id = str(event_id or "").removeprefix("vuln:").upper()
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            row = connection.execute(
                """
                SELECT *
                FROM vulnerability_records
                WHERE UPPER(cve_id) = ?
                ORDER BY datetime(disclosure_time) DESC, id DESC
                LIMIT 1
                """,
                (cve_id,),
            ).fetchone()
            if row is not None:
                event = _materialize_vulnerability_event(dict(row))
            else:
                event = load_normalized_event_detail(connection, event_id, allow_refresh=False)
        finally:
            connection.rollback()
    if event is None or event.get("event_type") != "vulnerability":
        return None
    return normalized_event_to_detail(event)


def _materialize_vulnerability_event(row: dict[str, Any]) -> dict[str, Any]:
    event = _build_vulnerability_base_event(row)
    severity = str(event.get("severity") or "").lower()
    risk_score = 55
    if severity == "critical":
        risk_score = 85
    elif severity == "high":
        risk_score = 72
    elif severity == "medium":
        risk_score = 58
    if bool((event.get("metadata") or {}).get("is_exploited")):
        risk_score = min(100, risk_score + 10)
    return {
        **event,
        "source": (event.get("metadata") or {}).get("source") or "公开源",
        "risk_score": int(event.get("risk_score") or risk_score),
        "risk_reasons": event.get("risk_reasons") or [],
    }


def _build_summary_cards(
    data_leak_events: list[dict[str, str]],
    ransomware_events: list[dict[str, str]],
    crawl_jobs: list[dict[str, Any]],
    forum_victims: list[dict[str, Any]],
    *,
    data_leak_total: int | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    data_leak_count = len(data_leak_events) if data_leak_total is None else data_leak_total
    site_names = sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")})
    failed_jobs = sum(
        1 for site_name in site_names if _latest_unresolved_problem_row([row for row in crawl_jobs if row.get("site_name") == site_name]) is not None
    )
    impacted_entities = len([row for row in forum_victims if row.get("victim_name")])

    dashboard_summary = [
        {
            "label": "数据泄露事件",
            "value": str(data_leak_count),
            "description": "已写入 SQLite 的论坛泄露详情数量。",
            "trend": f"{failed_jobs} 个失败任务" if failed_jobs else "运行正常",
            "tone": "warning",
            "icon": "Files",
        },
        {
            "label": "勒索受害者",
            "value": str(len(ransomware_events)),
            "description": "从泄露站点采集器解析出的受害者记录。",
            "trend": "采集链路在线",
            "tone": "danger",
            "icon": "Warning",
        },
        {
            "label": "受影响实体",
            "value": str(impacted_entities),
            "description": "从论坛详情中识别出的受害实体数量。",
            "trend": "来源于受害者实体表",
            "tone": "primary",
            "icon": "OfficeBuilding",
        },
        {
            "label": "爬虫任务",
            "value": str(len(crawl_jobs)),
            "description": "最近记录在任务审计表中的种子页与详情页任务。",
            "trend": "审计链路已开启",
            "tone": "success",
            "icon": "Bell",
        },
    ]

    data_leak_summary = [
        {
            "label": "泄露事件",
            "value": str(data_leak_count),
            "description": "当前已同步到前端的数据泄露详情数量。",
            "trend": "实时来自已接入论坛数据源",
            "tone": "warning",
            "icon": "DocumentRemove",
        },
        {
            "label": "活跃板块",
            "value": str(len({item["category"] for item in data_leak_events})),
            "description": "当前正在贡献数据的论坛板块数量。",
            "trend": "数据库 / 其他泄露 / 卖家交易",
            "tone": "primary",
            "icon": "Files",
        },
        {
            "label": "受害者提及",
            "value": str(impacted_entities),
            "description": "从详情页内容中识别出的受害者实体。",
            "trend": "已启用实体抽取",
            "tone": "success",
            "icon": "UserFilled",
        },
    ]

    ransomware_summary = [
        {
            "label": "受害者记录",
            "value": str(len(ransomware_events)),
            "description": "当前受害者表中的勒索受害者数量。",
            "trend": "为 0 表示相关站点暂未写入数据",
            "tone": "danger",
            "icon": "Warning",
        },
        {
            "label": "活跃来源",
            "value": str(len({item["attacker"] for item in ransomware_events if item["attacker"]})),
            "description": "当前贡献受害者数据的泄露站点数量。",
            "trend": "按站点来源聚合",
            "tone": "warning",
            "icon": "UserFilled",
        },
        {
            "label": "状态种类",
            "value": str(len({item["category"] for item in ransomware_events if item["category"]})),
            "description": "已公开、协商中、传输中等状态种类。",
            "trend": "来源于受害者状态字段",
            "tone": "primary",
            "icon": "TrendCharts",
        },
        {
            "label": "失败任务",
            "value": str(failed_jobs),
            "description": "供运维排查的失败爬虫任务数量。",
            "trend": "来源于任务审计表",
            "tone": "success",
            "icon": "Bell",
        },
    ]

    return dashboard_summary, data_leak_summary, ransomware_summary


def _build_preview_cards(
    data_leak_events: list[dict[str, str]],
    ransomware_events: list[dict[str, str]],
    crawl_jobs: list[dict[str, Any]],
    behavior_payload: dict[str, Any] | None = None,
    *,
    data_leak_total: int | None = None,
) -> list[dict[str, Any]]:
    data_leak_count = len(data_leak_events) if data_leak_total is None else data_leak_total
    site_names = sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")})
    failed_jobs = sum(
        1 for site_name in site_names if _latest_unresolved_problem_row([row for row in crawl_jobs if row.get("site_name") == site_name]) is not None
    )
    return [
        {
            "route": "/ransomware",
            "eyebrow": "模块预览",
            "title": "勒索情报",
            "summary": "聚合受害者表中的受害者记录与泄露站点活动。",
            "highlight": f"{len(ransomware_events)} 条受害者记录",
            "tone": "danger",
            "stats": [
                {"label": "受害者", "value": str(len(ransomware_events))},
                {"label": "来源数", "value": str(len({item['attacker'] for item in ransomware_events if item['attacker']}))},
                {"label": "已公开", "value": str(sum(1 for item in ransomware_events if item['category'] == '已公开'))},
            ],
        },
        {
            "route": "/data-leak",
            "eyebrow": "模块预览",
            "title": "数据泄露情报",
            "summary": "聚合论坛详情记录与标准化泄露事件。",
            "highlight": f"{data_leak_count} 条泄露详情",
            "tone": "warning",
            "stats": [
                {"label": "事件数", "value": str(data_leak_count)},
                {"label": "类型数", "value": str(len({item['category'] for item in data_leak_events}))},
                {"label": "地区数", "value": str(len({item['region'] for item in data_leak_events if item['region']}))},
            ],
        },
        {
            "route": "/threat-situation",
            "eyebrow": "模块预览",
            "title": "威胁态势",
            "summary": "从爬虫任务、结构化事件和风险分布构建整体态势视图。",
            "highlight": f"{failed_jobs} 个失败任务",
            "tone": "primary",
            "stats": [
                {"label": "任务数", "value": str(len(crawl_jobs))},
                {"label": "失败数", "value": str(failed_jobs)},
                {"label": "成功数", "value": str(sum(1 for row in crawl_jobs if row.get('status') == 'succeeded'))},
            ],
        },
    ]


def _build_recent_timeline(data_leak_events: list[dict[str, str]], ransomware_events: list[dict[str, str]], crawl_jobs: list[dict[str, Any]]) -> list[dict[str, str]]:
    timeline: list[dict[str, str]] = []
    for event in data_leak_events[:4]:
        timeline.append(
            {
                "time": event["disclosureTime"][-5:] if event["disclosureTime"] else "--:--",
                "module": "数据泄露",
                "title": event["title"],
                "detail": event["category"],
                "tone": "warning",
            }
        )
    for event in ransomware_events[:2]:
        timeline.append(
            {
                "time": event["disclosureTime"][-5:] if event["disclosureTime"] else "--:--",
                "module": "勒索情报",
                "title": event["title"],
                "detail": event["category"],
                "tone": "danger",
            }
        )
    unresolved_rows = []
    for site_name in sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")}):
        row = _latest_unresolved_problem_row([item for item in crawl_jobs if item.get("site_name") == site_name])
        if row is not None:
            unresolved_rows.append(row)
    unresolved_rows.sort(
        key=lambda row: _job_event_dt(row) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    for row in unresolved_rows[:2]:
            timeline.append(
                {
                    "time": _format_dt(row.get("finished_at") or row.get("started_at"))[-5:],
                    "module": "采集任务",
                    "title": f"{row.get('site_name')} {row.get('job_type')} {_label_job_status(_effective_job_status(row))}",
                    "detail": row.get("error_message") or row.get("target") or "任务失败",
                    "tone": "primary",
                }
            )
    return timeline[:8]


def _build_watchlist(crawl_jobs: list[dict[str, Any]], section_counts: Counter[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for site_name in sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")}):
        row = _latest_unresolved_problem_row([item for item in crawl_jobs if item.get("site_name") == site_name])
        if row is not None:
            items.append(
                {
                    "module": "采集任务",
                    "title": f"{row.get('site_name')} {row.get('job_type')} {_label_job_status(_effective_job_status(row))}",
                    "note": row.get("error_message") or "请检查代理链路或目标站点可达性",
                    "tone": "danger",
                }
            )
    for section, count in section_counts.most_common(3):
        items.append(
            {
                "module": "数据泄露",
                "title": f"{SECTION_LABELS.get(section, section)}持续活跃",
                "note": f"当前已累计 {count} 条详情记录。",
                "tone": "warning",
            }
        )
    return items[:3]


def _build_situation_alerts(crawl_jobs: list[dict[str, Any]]) -> list[dict[str, str]]:
    unresolved_rows: list[dict[str, Any]] = []
    for site_name in sorted({item.get("site_name") for item in crawl_jobs if item.get("site_name")}):
        row = _latest_unresolved_problem_row([item for item in crawl_jobs if item.get("site_name") == site_name])
        if row is not None:
            unresolved_rows.append(row)
    unresolved_rows.sort(
        key=lambda row: _job_event_dt(row) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return [
        {
            "level": "high",
            "time": _format_dt(row.get("finished_at") or row.get("started_at")),
            "title": f"{_label_source(row.get('site_name'))} {row.get('job_type')} {_label_job_status(_effective_job_status(row))}",
            "description": row.get("error_message") or row.get("target") or "采集任务状态更新",
            "source": _label_source(row.get("site_name")),
        }
        for row in unresolved_rows[:12]
    ]


def _build_country_focus(forum_victims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(_label_region(row.get("region")) for row in forum_victims)
    return [{"name": name, "value": value} for name, value in counts.most_common(6)]


def _build_vulnerability_summary(vulnerability_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exploited_count = sum(1 for item in vulnerability_events if item.get("isExploited"))
    patchable_count = sum(1 for item in vulnerability_events if item.get("patchAvailable"))
    vendor_count = len({item.get("vendor") for item in vulnerability_events if item.get("vendor")})
    return [
        {
            "label": "高危漏洞",
            "value": str(len(vulnerability_events)),
            "description": "已写入标准化事件表的公开源高危漏洞数量。",
            "trend": f"{exploited_count} 条已被利用",
            "tone": "danger",
            "icon": "WarningFilled",
        },
        {
            "label": "已被利用",
            "value": str(exploited_count),
            "description": "公开源披露中已确认存在利用活动的漏洞数量。",
            "trend": "优先进入处置视图",
            "tone": "warning",
            "icon": "Bell",
        },
        {
            "label": "影响厂商",
            "value": str(vendor_count),
            "description": "当前漏洞事件覆盖的重点厂商数量。",
            "trend": "用于识别高频产品族",
            "tone": "primary",
            "icon": "OfficeBuilding",
        },
        {
            "label": "可直接修复",
            "value": str(patchable_count),
            "description": "已明确有补丁或官方修复建议的漏洞数量。",
            "trend": "用于展示修复可执行性",
            "tone": "success",
            "icon": "CircleCheck",
        },
    ]


def _build_vulnerability_rankings(
    vulnerability_events: list[dict[str, Any]],
    field: str,
    limit: int = 6,
    recent_days: int = 30,
) -> list[dict[str, Any]]:
    cutoff = _now_utc() - timedelta(days=recent_days)
    recent_events = [
        item
        for item in vulnerability_events
        if (_parse_dt(str(item.get("disclosureTimeRaw") or item.get("disclosureTime") or "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    source_events = recent_events or vulnerability_events
    counter = Counter(item.get(field) or "未知" for item in source_events if item.get(field))
    return [{"name": name, "value": value} for name, value in counter.most_common(limit)]


def _build_vulnerability_watchlist(vulnerability_events: list[dict[str, Any]], limit: int = 3) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    for item in vulnerability_events[:limit]:
        alerts.append(
            {
                "module": "漏洞预警",
                "title": item.get("title") or item.get("cveId") or "高危漏洞",
                "note": "已被利用，建议优先核查补丁与暴露面。" if item.get("isExploited") else "存在公开 PoC 或高危利用条件，建议尽快研判。",
                "tone": "danger" if item.get("isExploited") else "warning",
            }
        )
    return alerts


def _build_vulnerability_timeline(vulnerability_events: list[dict[str, Any]], limit: int = 2) -> list[dict[str, str]]:
    timeline: list[dict[str, str]] = []
    for item in vulnerability_events[:limit]:
        timeline.append(
            {
                "time": (item.get("disclosureTime") or "--:--")[-5:],
                "module": "漏洞预警",
                "title": item.get("title") or item.get("cveId") or "公开源漏洞",
                "detail": "已被利用" if item.get("isExploited") else (item.get("category") or "公开披露"),
                "tone": "danger" if item.get("isExploited") else "primary",
            }
        )
    return timeline


def _build_vulnerability_alert_stream(vulnerability_events: list[dict[str, Any]], limit: int = 4) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    for item in vulnerability_events[:limit]:
        alerts.append(
            {
                "level": "critical" if item.get("isExploited") else "high",
                "time": item.get("disclosureTime") or "",
                "title": item.get("title") or item.get("cveId") or "公开源漏洞",
                "description": item.get("summary") or "公开源披露了新的高危漏洞事件。",
                "source": item.get("vendor") or "漏洞预警",
            }
        )
    return alerts


def _keyword_category(title: str, content: str) -> str:
    text = f"{title} {content}".lower()
    if any(keyword in text for keyword in ["password", "credential", "fullz", "account"]):
        return "凭证数据"
    if any(keyword in text for keyword in ["database", "dump", "records", "breach", "leak"]):
        return "数据库"
    if any(keyword in text for keyword in ["document", "passport", "id", "license", "statement"]):
        return "文档证件"
    if any(keyword in text for keyword in ["source code", "code", "repo", "git"]):
        return "源代码"
    return "其他"


def _build_threat_heatmap(data_leak_events: list[dict[str, str]], ransomware_events: list[dict[str, str]], crawl_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    regions = list({item["region"] for item in data_leak_events if item["region"]})[:5] or ["未知"]
    categories = ["数据泄露", "勒索情报", "失败任务"]
    values: list[list[int]] = []
    region_counts = Counter(item["region"] for item in data_leak_events)
    ransom_counts = Counter(item["region"] for item in ransomware_events if item["region"])
    site_names = sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")})
    failed_jobs = sum(
        1 for site_name in site_names if _latest_unresolved_problem_row([row for row in crawl_jobs if row.get("site_name") == site_name]) is not None
    )
    for region_index, region in enumerate(regions):
        values.append([region_index, 0, int(region_counts.get(region, 0))])
        values.append([region_index, 1, int(ransom_counts.get(region, 0))])
        values.append([region_index, 2, failed_jobs])
    return {"regions": regions, "categories": categories, "values": values}


def _latest_job_marker(connection) -> str:
    row = connection.execute(
        """
        SELECT MAX(COALESCE(finished_at, started_at, enqueued_at)) AS latest
        FROM crawl_jobs
        """
    ).fetchone()
    return str(row["latest"] or "") if row else ""


def _payload_cache_key(connection, namespace: str) -> str:
    cache_state = get_normalized_intelligence_cache_state(connection) or {}
    latest_jobs = _latest_job_marker(connection) if namespace == "intelligence" else ""
    vulnerability_state = connection.execute(
        """
        SELECT COUNT(*) AS count, MAX(id) AS latest_id, MAX(last_seen_at) AS latest
        FROM vulnerability_records
        """
    ).fetchone()
    monitoring_state = connection.execute(
        """
        SELECT COUNT(*) AS count, MAX(updated_at) AS latest
        FROM monitoring_keywords
        """
    ).fetchone()
    monitoring_count = int(monitoring_state["count"]) if monitoring_state else 0
    monitoring_latest = str(monitoring_state["latest"] or "") if monitoring_state else ""
    document_state = connection.execute(
        "SELECT COUNT(*) AS count, MAX(id) AS latest_id, MAX(last_seen_at) AS latest FROM document_hits"
    ).fetchone()
    code_state = connection.execute(
        "SELECT COUNT(*) AS count, MAX(id) AS latest_id, MAX(last_seen_at) AS latest FROM code_hits"
    ).fetchone()
    payload = {
        "payload_cache_version": PAYLOAD_CACHE_VERSION,
        "database": database_identity(connection),
        "namespace": namespace,
        "applied_revision": int(cache_state.get("applied_revision") or 0),
        "source_signature": cache_state.get("source_signature") or "",
        "refreshed_at": cache_state.get("refreshed_at") or "",
        "event_count": int(cache_state.get("event_count") or 0),
        "latest_jobs": latest_jobs,
        "vulnerability_count": int(vulnerability_state["count"]) if vulnerability_state else 0,
        "vulnerability_latest_id": int(vulnerability_state["latest_id"] or 0) if vulnerability_state else 0,
        "vulnerability_latest": str(vulnerability_state["latest"] or "") if vulnerability_state else "",
        "monitoring_keyword_count": monitoring_count,
        "monitoring_keyword_latest": monitoring_latest,
        "document_hit_count": int(document_state["count"] or 0) if document_state else 0,
        "document_hit_latest_id": int(document_state["latest_id"] or 0) if document_state else 0,
        "document_hit_latest": str(document_state["latest"] or "") if document_state else "",
        "code_hit_count": int(code_state["count"] or 0) if code_state else 0,
        "code_hit_latest_id": int(code_state["latest_id"] or 0) if code_state else 0,
        "code_hit_latest": str(code_state["latest"] or "") if code_state else "",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _get_cached_payload(namespace: str, cache_key: str) -> Any | None:
    with _PAYLOAD_CACHE_LOCK:
        entry = _PAYLOAD_CACHE.get(namespace)
        if entry and entry.get("key") == cache_key:
            return entry.get("payload")
    return None


def _set_cached_payload(namespace: str, cache_key: str, payload: Any) -> None:
    with _PAYLOAD_CACHE_LOCK:
        _PAYLOAD_CACHE[namespace] = {"key": cache_key, "payload": payload}


def _safe_pct(current: int, previous: int) -> int:
    if previous <= 0:
        return 100 if current > 0 else 0
    return round(((current - previous) / previous) * 100)


def _last_n_days(days: int) -> list[datetime]:
    today = datetime.now(timezone.utc).date()
    return [datetime.combine(today - timedelta(days=offset), datetime.min.time(), tzinfo=timezone.utc) for offset in range(days - 1, -1, -1)]


def _build_executive_trend(events: list[dict[str, Any]], days: int = 30) -> dict[str, list[Any]]:
    dates = _last_n_days(days)
    start = dates[0]
    total_counter: Counter[str] = Counter()
    high_counter: Counter[str] = Counter()
    for event in events:
        event_dt = _parse_dt(event.get("disclosure_time"))
        if event_dt is None or event_dt < start:
            continue
        key = event_dt.date().isoformat()
        total_counter[key] += 1
        if int(event.get("risk_score") or 0) >= 60:
            high_counter[key] += 1
    labels = [item.strftime("%m-%d") for item in dates]
    keys = [item.date().isoformat() for item in dates]
    return {
        "labels": labels,
        "total": [int(total_counter.get(key, 0)) for key in keys],
        "highRisk": [int(high_counter.get(key, 0)) for key in keys],
    }


def _build_executive_countries(events: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        country = (event.get("country") or "").strip()
        if not country or country == "未知":
            continue
        grouped.setdefault(country, []).append(event)
    rows: list[dict[str, Any]] = []
    for country, country_events in grouped.items():
        rows.append(
            {
                "name": country,
                "eventCount": len(country_events),
                "highRiskCount": sum(1 for item in country_events if int(item.get("risk_score") or 0) >= 60),
                "averageRiskScore": round(sum(int(item.get("risk_score") or 0) for item in country_events) / len(country_events)),
            }
        )
    rows.sort(key=lambda item: (item["eventCount"], item["highRiskCount"], item["averageRiskScore"]), reverse=True)
    return rows[:limit]


def _build_executive_priority_events(events: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    ranked = sorted(
        (
            item
            for item in events
            if (item.get("title") or "").strip() and len((item.get("title") or "").strip()) >= 4
        ),
        key=lambda item: (
            int(item.get("risk_score") or 0),
            _parse_dt(item.get("disclosure_time")) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return [
        {
            "id": item["event_id"],
            "disclosureDate": _format_date(item.get("disclosure_time")),
            "title": build_display_title(item),
            "originalTitle": item.get("title") or "未命名事件",
            "attacker": item.get("attacker") or "未知",
            "country": item.get("country") or "未知",
            "industry": item.get("industry") or "未知",
            "riskScore": int(item.get("risk_score") or 0),
        }
        for item in ranked[:limit]
    ]


def _build_executive_coverage(events: list[dict[str, Any]]) -> dict[str, int]:
    total = len(events) or 1
    return {
        "countryCoverageRate": round(sum(1 for item in events if (item.get("country") or "").strip() not in {"", "未知"}) / total * 100),
        "regionCoverageRate": round(sum(1 for item in events if (item.get("region") or "").strip() not in {"", "未知"}) / total * 100),
        "industryCoverageRate": round(sum(1 for item in events if (item.get("industry") or "").strip() not in {"", "未知"}) / total * 100),
    }


def _build_executive_cards(events: list[dict[str, Any]], countries: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=30)
    previous_start = now - timedelta(days=60)

    current_events = [item for item in events if (_parse_dt(item.get("disclosure_time")) or datetime.min.replace(tzinfo=timezone.utc)) >= current_start]
    previous_events = [
        item
        for item in events
        if previous_start <= (_parse_dt(item.get("disclosure_time")) or datetime.min.replace(tzinfo=timezone.utc)) < current_start
    ]
    current_high = [item for item in current_events if int(item.get("risk_score") or 0) >= 60]
    previous_high = [item for item in previous_events if int(item.get("risk_score") or 0) >= 60]
    top_country = countries[0] if countries else {"name": "未知", "eventCount": 0}
    return {
        "totalEvents30d": len(current_events),
        "totalEventsDeltaPct": _safe_pct(len(current_events), len(previous_events)),
        "highRisk30d": len(current_high),
        "highRiskDeltaPct": _safe_pct(len(current_high), len(previous_high)),
        "topCountry": top_country["name"],
        "topCountryEventCount": top_country["eventCount"],
    }


def _build_data_leak_page_summary(
    *,
    total: int,
    categories: list[str],
    victim_mentions: int,
) -> list[dict[str, str]]:
    return [
        {
            "label": "泄露事件",
            "value": str(total),
            "description": "数据库中的数据泄露事件总数。",
            "trend": "实时来自已接入论坛数据源",
            "tone": "warning",
            "icon": "DocumentRemove",
        },
        {
            "label": "活跃板块",
            "value": str(len(categories)),
            "description": "当前正在贡献数据的事件分类数量。",
            "trend": "按数据库中的完整事件集合统计",
            "tone": "primary",
            "icon": "Files",
        },
        {
            "label": "受害者提及",
            "value": str(victim_mentions),
            "description": "从详情页内容中识别出的受害者实体。",
            "trend": "已启用实体抽取",
            "tone": "success",
            "icon": "UserFilled",
        },
    ]


def build_data_leak_page(
    *,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    category: str = "",
    days: int | None = None,
    attacker: str | None = None,
    industry: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    return intelligence_queries_module.build_data_leak_page(
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        days=days,
        attacker=attacker,
        industry=industry,
        severity=severity,
        source=source,
        sort=sort,
    )


def build_ransomware_page(**parameters: Any) -> dict[str, Any]:
    return intelligence_queries_module.build_ransomware_page(**parameters)


def build_intelligence_search_page(**parameters: Any) -> dict[str, Any]:
    return intelligence_queries_module.build_intelligence_search_page(**parameters)


def iter_intelligence_csv(dataset: str, parameters: dict[str, Any]):
    return intelligence_queries_module.iter_csv_rows(dataset, parameters)


def build_intelligence_payload() -> dict[str, Any]:
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            cache_key = _payload_cache_key(connection, "intelligence")
            cached = _get_cached_payload("intelligence", cache_key)
            if cached is not None:
                return cached
            normalized_events, monitoring_payload = monitoring_rules_module.build_monitoring_payload(
                connection,
                load_normalized_events(connection, allow_refresh=False),
                persist_default_keywords=False,
            )
            vulnerability_rows = list_vulnerability_records(connection)
            crawl_jobs = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT site_name, job_type, status, target, enqueued_at, started_at, finished_at, error_message
                    FROM crawl_jobs
                    ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
                    LIMIT 100
                    """
                ).fetchall()
            ]
        finally:
            connection.rollback()

    def sort_by_disclosure(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: _parse_dt(str((item.get("metadata") or {}).get("updated_time") or item.get("disclosure_time") or "")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    data_leak_source_events = sort_by_disclosure([item for item in normalized_events if item.get("event_type") == "data_leak"])
    ransomware_source_events = sort_by_disclosure([item for item in normalized_events if item.get("event_type") == "ransomware"])
    vulnerability_source_events = sort_by_disclosure([_materialize_vulnerability_event(row) for row in vulnerability_rows])
    document_exposure_events = build_document_exposure_event_records(limit=100)
    document_exposure_summary = build_document_exposure_summary()
    data_leak_events = [normalized_event_to_list_item(item) for item in data_leak_source_events[:DATA_LEAK_EVENT_LIMIT]]
    ransomware_events = [normalized_event_to_list_item(item) for item in _apply_event_limit(ransomware_source_events, RANSOMWARE_EVENT_LIMIT)]
    vulnerability_all_events = [normalized_event_to_list_item(item) for item in vulnerability_source_events]
    vulnerability_events = vulnerability_all_events[:VULNERABILITY_EVENT_LIMIT]
    forum_victims = [
        {
            "victim_name": item.get("victim"),
            "industry": item.get("industry"),
            "region": item.get("region"),
        }
        for item in data_leak_source_events
        if item.get("victim") and item.get("victim") != "未知实体"
    ]
    dashboard_summary, data_leak_summary, ransomware_summary = _build_summary_cards(
        data_leak_events,
        ransomware_events,
        crawl_jobs,
        forum_victims,
        data_leak_total=len(data_leak_source_events),
    )
    vulnerability_summary = _build_vulnerability_summary(vulnerability_all_events)

    data_leak_counter = _count_by_day([row.get("disclosure_time") for row in data_leak_source_events])
    ransomware_counter = _count_by_day([row.get("disclosure_time") for row in ransomware_source_events])
    vulnerability_counter = _count_by_day([row.get("disclosure_time") for row in vulnerability_source_events])
    data_leak_series = _series_from_counter(data_leak_counter)
    ransomware_series = _series_from_counter(ransomware_counter)
    vulnerability_series = _series_from_counter(vulnerability_counter)
    threat_alert_series = {
        "labels": data_leak_series["labels"],
        "values": [
            int(data_leak_series["values"][index])
            + int(ransomware_series["values"][index])
            + int(vulnerability_series["values"][index])
            for index in range(len(data_leak_series["labels"]))
        ],
    }
    dashboard_data_leak_series = _series_from_counter(data_leak_counter, days=30)
    dashboard_ransomware_series = _series_from_counter(ransomware_counter, days=30)
    dashboard_vulnerability_series = _series_from_counter(vulnerability_counter, days=30)
    dashboard_threat_alert_series = {
        "labels": dashboard_data_leak_series["labels"],
        "values": [
            int(dashboard_data_leak_series["values"][index])
            + int(dashboard_ransomware_series["values"][index])
            + int(dashboard_vulnerability_series["values"][index])
            for index in range(len(dashboard_data_leak_series["labels"]))
        ],
    }

    section_counts = Counter(row.get("category") or "unknown" for row in data_leak_events)
    failed_jobs = sum(
        1
        for site_name in sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")})
        if _latest_unresolved_problem_row([row for row in crawl_jobs if row.get("site_name") == site_name]) is not None
    )
    attack_type_share = [
        {"name": "数据泄露", "value": len(data_leak_events)},
        {"name": "勒索情报", "value": len(ransomware_events)},
        {"name": "漏洞预警", "value": len(vulnerability_all_events)},
        {"name": "文件监测", "value": len(document_exposure_events)},
        {
            "name": "失败任务",
            "value": failed_jobs,
        },
    ]
    data_leak_keyword_counts = Counter(item.get("category") or "其他" for item in data_leak_events)
    top_industries = Counter(item.get("industry") or "未知" for item in data_leak_source_events if item.get("industry"))
    top_regions = Counter(
        item.get("region") or "未知"
        for item in data_leak_source_events + ransomware_source_events
        if item.get("region")
    )
    top_ransomware_actors = Counter(item.get("attacker") or "未知" for item in ransomware_events if item.get("attacker"))
    top_ransomware_industries = Counter(item.get("industry") or "未知" for item in ransomware_source_events if item.get("industry"))
    vulnerability_vendor_ranking = _build_vulnerability_rankings(vulnerability_all_events, "vendor")
    vulnerability_product_ranking = _build_vulnerability_rankings(vulnerability_all_events, "product")
    threat_level_trend = {
        "labels": data_leak_series["labels"],
        "high": ransomware_series["values"],
        "medium": data_leak_series["values"],
        "low": threat_alert_series["values"],
    }
    executive_behavior_events = [item for item in normalized_events if item.get("event_type") != "vulnerability"]
    executive_countries = _build_executive_countries(executive_behavior_events)
    executive_cards = _build_executive_cards(executive_behavior_events, executive_countries)
    executive_trend = _build_executive_trend(normalized_events)
    executive_priority_events = _build_executive_priority_events(normalized_events)
    executive_coverage = _build_executive_coverage(normalized_events)
    preview_cards = _build_preview_cards(
        data_leak_events,
        ransomware_events,
        crawl_jobs,
        {},
        data_leak_total=len(data_leak_source_events),
    )
    preview_cards.insert(
        2,
        {
            "route": "/document-exposure/search-engine",
            "eyebrow": "模块预览",
            "title": "文件监测",
            "summary": "集中查看文档平台、网盘聚合与搜索引擎中的疑似企业文件暴露线索。",
            "highlight": f"{document_exposure_summary['highRiskCount']} 条高风险命中",
            "tone": "warning",
            "stats": [
                {"label": "命中数", "value": str(document_exposure_summary["totalHits"])},
                {"label": "高风险", "value": str(document_exposure_summary["highRiskCount"])},
                {"label": "平台数", "value": str(document_exposure_summary["platformCount"])},
            ],
        },
    )
    preview_cards.insert(
        3,
        {
            "route": "/vulnerability-alerts",
            "eyebrow": "模块预览",
            "title": "漏洞预警",
            "summary": "聚合公开源高危漏洞、利用状态与受影响厂商/产品，适合演示应急研判入口。",
            "highlight": f"{sum(1 for item in vulnerability_all_events if item.get('isExploited'))} 条已被利用",
            "tone": "danger",
            "stats": [
                {"label": "漏洞数", "value": str(len(vulnerability_all_events))},
                {"label": "厂商数", "value": str(len({item.get('vendor') for item in vulnerability_all_events if item.get('vendor')}))},
                {"label": "已利用", "value": str(sum(1 for item in vulnerability_all_events if item.get('isExploited')))},
            ],
        },
    )
    dashboard_watchlist = _build_vulnerability_watchlist(vulnerability_events, limit=2) + _build_watchlist(crawl_jobs, section_counts)
    timeline = _build_vulnerability_timeline(vulnerability_events, limit=2) + _build_recent_timeline(data_leak_events, ransomware_events, crawl_jobs)
    situation_alerts = _build_vulnerability_alert_stream(vulnerability_events, limit=4) + _build_situation_alerts(crawl_jobs)
    dashboard_summary_cards = dashboard_summary + vulnerability_summary[:1]

    payload = {
        "monitoringStatus": _build_monitoring_status(
            [{"fetched_at": item.get("disclosure_time")} for item in normalized_events],
            crawl_jobs,
        ),
        "dashboardSummaryCards": dashboard_summary_cards,
        "modulePreviewCards": preview_cards,
        "dashboardTrendSeries": {
            "labels": dashboard_data_leak_series["labels"],
            "ransomware": dashboard_ransomware_series["values"],
            "dataLeak": dashboard_data_leak_series["values"],
            "vulnerability": dashboard_vulnerability_series["values"],
            "threatAlerts": dashboard_threat_alert_series["values"],
        },
        "dashboardCountryFocus": _build_country_focus(forum_victims),
        "crossModuleTimeline": timeline[:8],
        "dashboardWatchlist": dashboard_watchlist[:4],
        "ransomwareSummary": ransomware_summary,
        "ransomwareEvents": ransomware_events,
        "documentExposureSummary": [
            {
                "label": "监测命中",
                "value": str(document_exposure_summary["totalHits"]),
                "description": "来自文档平台、网盘聚合与搜索引擎的疑似暴露文件数量。",
                "trend": f"{document_exposure_summary['highRiskCount']} 条高风险",
                "tone": "warning",
                "icon": "Files",
            },
            {
                "label": "待复核",
                "value": str(document_exposure_summary["pendingReviewCount"]),
                "description": "当前仍需人工核验或待进一步确认的命中记录。",
                "trend": f"{document_exposure_summary['loginRequiredCount']} 条需登录复核",
                "tone": "primary",
                "icon": "Document",
            },
            {
                "label": "会话状态",
                "value": str(document_exposure_summary["configuredSessionCount"]),
                "description": "已配置平台会话数量。",
                "trend": f"{document_exposure_summary['invalidSessionCount']} 个异常",
                "tone": "primary",
                "icon": "Lock",
            },
        ],
        "documentExposureEvents": document_exposure_events,
        "dataLeakSummary": data_leak_summary,
        "dataLeakEvents": data_leak_events,
        "vulnerabilitySummary": vulnerability_summary,
        "vulnerabilityEvents": vulnerability_events,
        "vulnerabilityTrend": vulnerability_series,
        "vulnerabilityVendorRanking": vulnerability_vendor_ranking,
        "vulnerabilityProductRanking": vulnerability_product_ranking,
        "threatSituationSummary": {
            "title": "基于标准化情报事件的威胁态势总览",
            "description": "从数据泄露、勒索情报、公开源漏洞和爬虫任务日志中聚合生成当前态势视图。",
            "stats": [
                {"label": "泄露事件", "value": str(len(data_leak_events))},
                {"label": "勒索受害者", "value": str(len(ransomware_events))},
                {"label": "漏洞预警", "value": str(len(vulnerability_all_events))},
                {"label": "失败任务", "value": str(failed_jobs)},
            ],
        },
        "attackTypeShare": attack_type_share,
        "dataLeakEventTrend": data_leak_series,
        "dataLeakRanking": [
            {"name": name, "value": value}
            for name, value in (top_industries.most_common(5) or section_counts.most_common(5))
        ],
        "regionalThreatComparison": [{"name": name, "value": value} for name, value in top_regions.most_common(6)],
        "ransomwareActorRanking": [{"name": name, "value": value} for name, value in top_ransomware_actors.most_common(6)],
        "ransomwareIndustryImpact": [{"name": name, "value": value} for name, value in top_ransomware_industries.most_common(6)],
        "ransomwareTrend": ransomware_series,
        "sensitiveTypeShare": [{"name": name, "value": value} for name, value in data_leak_keyword_counts.most_common(5)],
        "situationAlerts": situation_alerts[:12],
        "threatHeatmap": _build_threat_heatmap(data_leak_events, ransomware_events, crawl_jobs),
        "threatLevelTrend": threat_level_trend,
        "threatExecutiveCards": executive_cards,
        "threatExecutiveTrend": executive_trend,
        "threatExecutiveCountries": executive_countries,
        "threatExecutivePriorityEvents": executive_priority_events,
        "threatExecutiveCoverage": executive_coverage,
        **monitoring_payload,
    }
    _set_cached_payload("intelligence", cache_key, payload)
    return payload


def build_dashboard_overview(**parameters: Any) -> dict[str, Any]:
    return intelligence_aggregates_module.build_dashboard_overview(**parameters)


def build_threat_situation(**parameters: Any) -> dict[str, Any]:
    return intelligence_aggregates_module.build_threat_situation(**parameters)


def warm_api_payloads() -> None:
    # Warm only compact route payloads. The legacy multi-megabyte payload remains
    # available on demand and retains its independent compatibility cache.
    build_dashboard_overview(days=7)
    build_threat_situation(days=30)


def _runtime_db_status() -> dict[str, Any]:
    runtime_db_path = default_db_path()
    source_db_path = Path(os.environ.get("DARKWEB_COLLECTOR_SOURCE_DB_PATH", project_root() / "data" / "collector.db")).expanduser()
    meta_path = Path(os.environ.get("DARKWEB_RUNTIME_DB_META_PATH", f"{runtime_db_path}.meta.json")).expanduser()

    runtime_exists = runtime_db_path.exists()
    source_exists = source_db_path.exists()
    status = {
        "runtime_db_path": str(runtime_db_path),
        "source_db_path": str(source_db_path),
        "using_runtime_db": runtime_db_path.resolve() != source_db_path.resolve() if runtime_exists and source_exists else str(runtime_db_path) != str(source_db_path),
        "runtime_db_exists": runtime_exists,
        "source_db_exists": source_exists,
        "runtime_db_updated_at": _format_dt(datetime.fromtimestamp(runtime_db_path.stat().st_mtime, tz=timezone.utc).isoformat()) if runtime_exists else "",
        "runtime_db_size_mb": round(runtime_db_path.stat().st_size / 1024 / 1024, 2) if runtime_exists else 0,
        "meta_exists": meta_path.exists(),
        "prepared_at": "",
        "copied_counts": {},
        "skipped_tables": {},
    }
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        status["prepared_at"] = _format_dt(meta.get("prepared_at"))
        status["copied_counts"] = meta.get("copied_counts") or {}
        status["skipped_tables"] = meta.get("skipped_tables") or {}
    return status


def build_jobs_payload() -> dict[str, Any]:
    with get_db_connection() as connection:
        crawl_jobs = [
            dict(row)
            for row in connection.execute(
                """
                SELECT site_name, job_type, status, queue_name, target, enqueued_at, started_at, finished_at, error_message
                FROM crawl_jobs
                ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
                LIMIT 300
                """
            ).fetchall()
        ]
        forum_detail_counts = {
            row["site_name"]: int(row["count"])
            for row in connection.execute(
                "SELECT site_name, COUNT(*) AS count FROM forum_details GROUP BY site_name"
            ).fetchall()
        }
        victim_counts = {
            row["site_name"]: int(row["count"])
            for row in connection.execute(
                "SELECT site_name, COUNT(*) AS count FROM victims GROUP BY site_name"
            ).fetchall()
        }
        vulnerability_count_row = connection.execute(
            "SELECT COUNT(*) AS count, MAX(disclosure_time) AS latest_disclosure_time FROM vulnerability_records"
        ).fetchone()

    from darkweb_collector.api_actions import get_ransomware_sync_status, get_vulnerability_sync_status

    try:
        configured_configs = load_site_configs()
        configured_sites = [config.site_name for config in configured_configs]
        enabled_map = {config.site_name: config.enabled for config in configured_configs}
    except Exception:
        configured_sites = sorted({row.get("site_name") for row in crawl_jobs if row.get("site_name")})
        enabled_map = {site_name: True for site_name in configured_sites}

    running_jobs = sum(1 for row in crawl_jobs if _effective_job_status(row) == "running")
    stale_jobs = sum(1 for row in crawl_jobs if _effective_job_status(row) == "stale")

    site_health = []
    unresolved_problem_rows: list[dict[str, Any]] = []
    for site_name in configured_sites:
        site_rows = [row for row in crawl_jobs if row.get("site_name") == site_name]
        latest_seed = next((row for row in site_rows if row.get("job_type") == "seed"), None)
        latest_detail = next((row for row in site_rows if row.get("job_type") == "detail"), None)
        latest_success = next((row for row in site_rows if row.get("status") == "succeeded"), None)
        latest_unresolved_problem = _latest_unresolved_problem_row(site_rows)
        if latest_unresolved_problem is not None:
            unresolved_problem_rows.append(latest_unresolved_problem)
        active_running = sum(1 for row in site_rows if _effective_job_status(row) == "running")
        active_enqueued = sum(1 for row in site_rows if _effective_job_status(row) == "enqueued")

        latest_seed_dt = _job_event_dt(latest_seed)
        latest_detail_dt = _job_event_dt(latest_detail)
        effective_seed_status = _effective_job_status(latest_seed) if latest_seed else ""
        if (
            effective_seed_status == "stale"
            and latest_seed
            and latest_seed.get("status") == "enqueued"
            and any(
                row.get("queue_name") == latest_seed.get("queue_name")
                and row.get("status") == "running"
                and not row.get("finished_at")
                for row in crawl_jobs
            )
        ):
            effective_seed_status = "enqueued"
        seed_age_minutes = None
        if latest_seed_dt is not None:
            seed_age_minutes = max(0, round((_now_utc() - latest_seed_dt).total_seconds() / 60))
        detail_status = _label_job_status(_effective_job_status(latest_detail)) if latest_detail else "未运行"
        if (
            latest_detail
            and _effective_job_status(latest_detail) in {"failed", "stale"}
            and latest_seed is not None
            and latest_seed.get("status") == "succeeded"
            and latest_seed_dt is not None
            and latest_detail_dt is not None
            and latest_seed_dt > latest_detail_dt
            and latest_unresolved_problem is None
        ):
            detail_status = "未更新"

        site_health.append(
            {
                "site_name": site_name,
                "enabled": enabled_map.get(site_name, True),
                "overall_status": (
                    "异常"
                    if latest_unresolved_problem
                    else "陈旧任务"
                    if effective_seed_status == "stale"
                    else "运行中"
                    if active_running
                    else "等待中"
                    if active_enqueued
                    else "正常"
                    if latest_success
                    else "未运行"
                ),
                "seed_status": _label_job_status(_effective_job_status(latest_seed)) if latest_seed else "未运行",
                "detail_status": detail_status,
                "running_jobs": active_running,
                "failed_jobs_24h": 1 if latest_unresolved_problem else 0,
                "last_success_at": _format_dt(latest_success.get("finished_at") if latest_success else None),
                "last_error": (
                    (latest_unresolved_problem.get("error_message") if latest_unresolved_problem else "")
                    or ("stale seed task auto-cleared" if effective_seed_status == "stale" else "")
                ),
                "forum_details_count": forum_detail_counts.get(site_name, 0),
                "victims_count": victim_counts.get(site_name, 0),
                "activeSeedJobStatus": effective_seed_status or "",
                "staleSeedDetected": effective_seed_status == "stale",
                "latestSeedJobAgeMinutes": seed_age_minutes,
                "blockingReason": "stale_seed_job" if effective_seed_status == "stale" else ("active_seed_job" if effective_seed_status in {"running", "enqueued"} else ""),
            }
        )

    unresolved_problem_rows.sort(
        key=lambda row: _job_event_dt(row) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    recent_failures = [
        {
            "site_name": row.get("site_name"),
            "job_type": row.get("job_type"),
            "status": _label_job_status(_effective_job_status(row)),
            "target": row.get("target"),
            "error_message": row.get("error_message") or "",
            "finished_at": _format_dt(row.get("finished_at") or row.get("started_at")),
        }
        for row in unresolved_problem_rows[:20]
    ]
    failed_jobs_24h = len(recent_failures)

    overall_status = "采集中" if running_jobs > 0 else "部分失败" if failed_jobs_24h > 0 or stale_jobs > 0 else "正常"
    vulnerability_sync = {
        **get_vulnerability_sync_status(),
        "record_count": int(vulnerability_count_row["count"]) if vulnerability_count_row else 0,
        "latest_disclosure_time": _format_dt(vulnerability_count_row["latest_disclosure_time"]) if vulnerability_count_row else "",
    }
    for key in ("started_at", "last_tick_at", "last_success_at"):
        vulnerability_sync[key] = _format_dt(vulnerability_sync.get(key))
    ransomware_sync = get_ransomware_sync_status()
    for key in ("started_at", "last_tick_at", "last_success_at"):
        ransomware_sync[key] = _format_dt(ransomware_sync.get(key))
    ransomware_sync["latest_disclosure_time"] = _format_dt(ransomware_sync.get("latest_disclosure_time"))
    return {
        "overall_status": overall_status,
        "running_jobs": running_jobs,
        "stale_jobs": stale_jobs,
        "failed_jobs_24h": failed_jobs_24h,
        "recent_failures": recent_failures,
        "site_health": site_health,
        "vulnerability_sync": vulnerability_sync,
        "ransomware_sync": ransomware_sync,
        "runtime_db": _runtime_db_status(),
        "updated_at": _format_dt(_now_utc().isoformat()),
    }


# ---------------------------------------------------------------------------
# AI 分析专用接口：返回与前端同源的、已分类筛选好的事件 + 聚合统计
# ---------------------------------------------------------------------------

AI_EVENT_TYPES = ("data_leak", "ransomware", "vulnerability")
AI_DEFAULT_LIMIT = 100
AI_MAX_LIMIT = 500


def _ai_normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _ai_event_dt(item: dict[str, Any]) -> datetime | None:
    raw = (
        item.get("updatedTimeRaw")
        or item.get("disclosureTimeRaw")
        or str(item.get("disclosureTime") or "").replace(" ", "T")
    )
    return _parse_dt(str(raw or ""))


def _ai_pick_first_url(resources: Any) -> str:
    """从 mirror/screenshot 资源列表里挑第一个非空 URL。"""
    if not resources:
        return ""
    if isinstance(resources, list):
        for item in resources:
            if isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                if url:
                    return url
            elif isinstance(item, str) and item.strip():
                return item.strip()
    if isinstance(resources, str):
        return resources.strip()
    return ""


def _ai_enrich_list_item(event: dict[str, Any]) -> dict[str, Any]:
    """在标准列表项基础上补充披露地址等 AI 需要的字段。"""
    item = normalized_event_to_list_item(event)
    metadata = event.get("metadata") or {}

    disclosure_url = (
        event.get("source_url")
        or metadata.get("source_url")
        or metadata.get("disclosure_url")
        or ""
    )
    mirror_resources = event.get("mirror_resources") or metadata.get("mirror_resources") or []
    screenshot_resources = event.get("screenshot_resources") or metadata.get("screenshot_resources") or []
    if not disclosure_url:
        # 没有源链接时，回退到镜像里的第一个 URL，至少给 AI 一个可点击的入口
        disclosure_url = _ai_pick_first_url(mirror_resources)

    item["disclosureUrl"] = str(disclosure_url or "")
    item["mirrorResources"] = mirror_resources
    item["screenshotResources"] = screenshot_resources
    item["jsonPreviewUrl"] = event.get("json_preview_url") or ""
    item["sourceUrl"] = item["disclosureUrl"]  # 兼容别名
    return item


def _ai_load_events(event_type_filter: str | None) -> list[dict[str, Any]]:
    """兼容旧内部调用，但每类最多只物化 AI_MAX_LIMIT 条候选记录。"""
    items, _ = _ai_query_events(
        event_type=event_type_filter,
        days=None,
        industry=None,
        region=None,
        country=None,
        severity=None,
        attacker=None,
        keyword=None,
        min_risk_score=None,
        limit=AI_MAX_LIMIT,
    )
    return items


def _ai_query_events(
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
    """在只读快照中执行 SQL 过滤，每类只返回进入全局 Top-N 的候选。"""
    with get_readonly_db_connection() as connection:
        connection.execute("BEGIN")
        try:
            candidates, matched_count = intelligence_queries_module.query_ai_events(
                connection,
                event_type=event_type,
                days=days,
                industry=industry,
                region=region,
                country=country,
                severity=severity,
                attacker=attacker,
                keyword=keyword,
                min_risk_score=min_risk_score,
                limit=limit,
            )
            normalized_candidates = [
                item for item in candidates if item.get("event_type") != "vulnerability"
            ]
            monitored, _ = monitoring_rules_module.build_monitoring_payload(
                connection,
                normalized_candidates,
                persist_default_keywords=False,
            )
        finally:
            connection.rollback()

    monitored_by_id = {str(item.get("event_id") or ""): item for item in monitored}
    items = [
        _ai_enrich_list_item(monitored_by_id.get(str(item.get("event_id") or ""), item))
        for item in candidates
    ]
    return items, matched_count


def _ai_apply_filters(
    items: list[dict[str, Any]],
    *,
    days: int | None,
    industry: str | None,
    region: str | None,
    country: str | None,
    severity: str | None,
    attacker: str | None,
    keyword: str | None,
    min_risk_score: int | None,
) -> list[dict[str, Any]]:
    cutoff = None
    if days is not None and days > 0:
        cutoff = _now_utc() - timedelta(days=days)

    industry_q = _ai_normalize_text(industry)
    region_q = _ai_normalize_text(region)
    country_q = _ai_normalize_text(country)
    severity_q = _ai_normalize_text(severity)
    attacker_q = _ai_normalize_text(attacker)
    keyword_q = _ai_normalize_text(keyword)

    filtered: list[dict[str, Any]] = []
    for item in items:
        if cutoff is not None:
            event_dt = _ai_event_dt(item)
            if event_dt is None or event_dt < cutoff:
                continue
        if industry_q and industry_q not in _ai_normalize_text(item.get("industry")):
            continue
        if region_q:
            haystack = " ".join(
                [
                    _ai_normalize_text(item.get("region")),
                    _ai_normalize_text(item.get("macroRegion")),
                ]
            )
            if region_q not in haystack:
                continue
        if country_q:
            haystack = " ".join(
                [
                    _ai_normalize_text(item.get("country")),
                    _ai_normalize_text(item.get("countryCode")),
                ]
            )
            if country_q not in haystack:
                continue
        if severity_q and _ai_normalize_text(item.get("severity")) != severity_q:
            continue
        if attacker_q and attacker_q not in _ai_normalize_text(item.get("attacker")):
            continue
        if keyword_q:
            haystack = " ".join(
                [
                    _ai_normalize_text(item.get("title")),
                    _ai_normalize_text(item.get("originalTitle")),
                    _ai_normalize_text(item.get("victim")),
                    _ai_normalize_text(item.get("summary")),
                    _ai_normalize_text(item.get("attacker")),
                    _ai_normalize_text(item.get("cveId")),
                ]
            )
            if keyword_q not in haystack:
                continue
        if min_risk_score is not None:
            try:
                if int(item.get("riskScore") or 0) < int(min_risk_score):
                    continue
            except (TypeError, ValueError):
                continue
        filtered.append(item)
    return filtered


def _ai_top_n(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"name": name, "value": value} for name, value in counter.most_common(limit) if name]


def _ai_build_aggregations(items: list[dict[str, Any]], days: int) -> dict[str, Any]:
    type_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    industry_counter: Counter[str] = Counter()
    region_counter: Counter[str] = Counter()
    country_counter: Counter[str] = Counter()
    attacker_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    high_risk_count = 0
    exploited_count = 0

    type_label_map = {"data_leak": "数据泄露", "ransomware": "勒索情报", "vulnerability": "漏洞预警"}

    timeline_buckets: dict[str, dict[str, int]] = {}
    series_days = max(7, min(days or 30, 90))
    for dt in _last_n_days(series_days):
        timeline_buckets[dt.date().isoformat()] = {"data_leak": 0, "ransomware": 0, "vulnerability": 0}

    for item in items:
        normalized_type = item.get("normalized_event_type") or "unknown"
        type_counter[type_label_map.get(normalized_type, normalized_type)] += 1
        if item.get("severity"):
            severity_counter[str(item.get("severity")).lower()] += 1
        if item.get("industry"):
            industry_counter[str(item.get("industry"))] += 1
        if item.get("region"):
            region_counter[str(item.get("region"))] += 1
        if item.get("country"):
            country_counter[str(item.get("country"))] += 1
        if item.get("attacker"):
            attacker_counter[str(item.get("attacker"))] += 1
        if item.get("sourceSite"):
            source_counter[str(item.get("sourceSite"))] += 1
        if item.get("category"):
            category_counter[str(item.get("category"))] += 1
        try:
            if int(item.get("riskScore") or 0) >= 70:
                high_risk_count += 1
        except (TypeError, ValueError):
            pass
        if bool(item.get("isExploited")):
            exploited_count += 1

        event_dt = _ai_event_dt(item)
        if event_dt is None:
            continue
        bucket_key = event_dt.date().isoformat()
        bucket = timeline_buckets.get(bucket_key)
        if bucket is None:
            continue
        if normalized_type in bucket:
            bucket[normalized_type] += 1

    timeline_labels = sorted(timeline_buckets.keys())
    timeline = {
        "labels": timeline_labels,
        "data_leak": [timeline_buckets[label]["data_leak"] for label in timeline_labels],
        "ransomware": [timeline_buckets[label]["ransomware"] for label in timeline_labels],
        "vulnerability": [timeline_buckets[label]["vulnerability"] for label in timeline_labels],
        "total": [
            timeline_buckets[label]["data_leak"]
            + timeline_buckets[label]["ransomware"]
            + timeline_buckets[label]["vulnerability"]
            for label in timeline_labels
        ],
    }

    return {
        "totals": {
            "events": len(items),
            "high_risk_events": high_risk_count,
            "exploited_vulnerabilities": exploited_count,
        },
        "by_event_type": _ai_top_n(type_counter),
        "by_severity": _ai_top_n(severity_counter),
        "by_category": _ai_top_n(category_counter),
        "top_industries": _ai_top_n(industry_counter, 10),
        "top_regions": _ai_top_n(region_counter, 10),
        "top_countries": _ai_top_n(country_counter, 10),
        "top_attackers": _ai_top_n(attacker_counter, 10),
        "top_sources": _ai_top_n(source_counter, 10),
        "timeline": timeline,
    }


def _ai_summarize(
    aggregations: dict[str, Any],
    filters: dict[str, Any],
    returned_count: int,
    matched_count: int,
) -> str:
    totals = aggregations.get("totals", {})
    pieces: list[str] = []
    pieces.append(
        f"在筛选条件下匹配到 {matched_count} 条事件（返回 {returned_count} 条），"
        f"其中高风险（risk≥70）{totals.get('high_risk_events', 0)} 条，"
        f"已被利用漏洞 {totals.get('exploited_vulnerabilities', 0)} 条。"
    )
    by_type = aggregations.get("by_event_type") or []
    if by_type:
        pieces.append(
            "类型分布：" + "、".join(f"{row['name']} {row['value']}" for row in by_type[:3]) + "。"
        )
    top_industries = aggregations.get("top_industries") or []
    if top_industries:
        pieces.append(
            "受影响行业 Top：" + "、".join(f"{row['name']}({row['value']})" for row in top_industries[:5]) + "。"
        )
    top_attackers = aggregations.get("top_attackers") or []
    if top_attackers:
        pieces.append(
            "活跃攻击源 Top：" + "、".join(f"{row['name']}({row['value']})" for row in top_attackers[:5]) + "。"
        )
    if filters.get("days"):
        pieces.append(f"时间窗口：最近 {filters['days']} 天。")
    return " ".join(pieces)


def build_ai_intelligence_payload(
    *,
    event_type: str | None = None,
    days: int | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    severity: str | None = None,
    attacker: str | None = None,
    keyword: str | None = None,
    min_risk_score: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """供 AI 调用的统一情报接口：先按参数筛选，再附带聚合统计与简短文字摘要。"""
    if limit is None:
        effective_limit = AI_DEFAULT_LIMIT
    else:
        try:
            effective_limit = max(1, min(int(limit), AI_MAX_LIMIT))
        except (TypeError, ValueError):
            effective_limit = AI_DEFAULT_LIMIT

    days_value: int | None = None
    if days is not None:
        try:
            parsed = int(days)
            if parsed > 0:
                days_value = parsed
        except (TypeError, ValueError):
            days_value = None

    filtered, matched_count = _ai_query_events(
        event_type=event_type,
        days=days_value,
        industry=industry,
        region=region,
        country=country,
        severity=severity,
        attacker=attacker,
        keyword=keyword,
        min_risk_score=min_risk_score,
        limit=effective_limit,
    )
    filtered.sort(
        key=lambda item: _ai_event_dt(item) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    returned_events = filtered[:effective_limit]
    aggregations = _ai_build_aggregations(returned_events, days=days_value or 30)

    filters_echo = {
        "event_type": (event_type or "all").lower(),
        "days": days_value,
        "industry": industry,
        "region": region,
        "country": country,
        "severity": severity,
        "attacker": attacker,
        "keyword": keyword,
        "min_risk_score": min_risk_score,
        "limit": effective_limit,
    }

    return {
        "generated_at": _format_dt(_now_utc().isoformat()),
        "filters": filters_echo,
        "matched_count": matched_count,
        "returned_count": len(returned_events),
        "truncated": matched_count > len(returned_events),
        "summary_text": _ai_summarize(aggregations, filters_echo, len(returned_events), matched_count),
        "aggregations": aggregations,
        "events": returned_events,
    }
