from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from darkweb_collector.db import (
    add_document_hit_review,
    get_db_connection,
    get_document_hit,
    get_exposure_watchlist,
    insert_exposure_scan_run,
    insert_document_hit_snapshot,
    list_document_hit_reviews,
    list_document_hit_snapshots,
    list_document_hits,
    list_exposure_scan_runs,
    list_exposure_watch_terms,
    list_exposure_watchlists,
    replace_exposure_watch_terms,
    update_document_hit_last_snapshot,
    upsert_document_hit,
    upsert_exposure_watchlist,
)
from darkweb_collector.detail_i18n import translate_event_title_live
from darkweb_collector.document_exposure_browser import fetch_page_artifacts_with_session
from darkweb_collector.document_exposure_platforms import (
    PLATFORMS,
    SEARCH_ENGINES,
    ExposurePlatform,
    get_exposure_platform,
    monitored_domains,
    platform_from_url,
)
from darkweb_collector.document_exposure_sessions import (
    build_platform_session_payloads,
    platform_storage_state_path,
)
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
from darkweb_collector.runtime import output_root
from darkweb_collector.utils import dump_json, dump_text, safe_stem


logger = logging.getLogger("darkweb_collector.document_exposure")
SENSITIVE_KEYWORDS = (
    "内部",
    "机密",
    "报价",
    "投标",
    "方案",
    "合同",
    "客户",
    "通讯录",
    "账号",
    "密码",
    "源代码",
    "运维",
    "财务",
    "名录",
    "清单",
)
FILE_NAME_RE = re.compile(r"\b[\w\-. ]+\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z|csv|txt)\b", re.IGNORECASE)
SHARE_LINK_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
PREVIEW_TEXT_LIMIT = 4000
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class DiscoverySource:
    key: str
    label: str
    search_url_template: str
    category: str


DISCOVERY_SOURCES: tuple[DiscoverySource, ...] = (
    DiscoverySource("baidu_search", "百度搜索", "https://www.baidu.com/s?wd={query}", "search_engine"),
    DiscoverySource("bing_search", "Bing", "https://www.bing.com/search?q={query}", "search_engine"),
    DiscoverySource("so360_search", "360搜索", "https://www.so.com/s?q={query}", "search_engine"),
    DiscoverySource("xiaobaipan", "小白盘", "https://www.xiaobaipan.com/s/{query}.html", "netdisk_search"),
    DiscoverySource("xiaobudian", "小不点搜索", "https://www.xiaoso.net/search?wd={query}", "netdisk_search"),
    DiscoverySource("lingfengyun", "凌风云", "https://www.lingfengyun.com/search?q={query}", "netdisk_search"),
    DiscoverySource("dalipan", "大力盘", "https://www.dalipan.com/search?keyword={query}", "netdisk_search"),
    DiscoverySource("baidu_wenku", "百度文库直搜", "https://wenku.baidu.com/search?word={query}", "document_library"),
    DiscoverySource("docin", "豆丁直搜", "https://www.docin.com/search.do?nkey={query}", "document_library"),
    DiscoverySource("doc88", "道客巴巴直搜", "https://www.doc88.com/search?q={query}", "document_library"),
    DiscoverySource("book118", "原创力直搜", "https://max.book118.com/search.html?q={query}", "document_library"),
    DiscoverySource("iask_share", "爱问共享直搜", "https://ishare.iask.sina.com.cn/search.php?key={query}", "document_library"),
)


DEFAULT_TERMS = [
    {"term": "示例企业", "term_type": "company_name", "weight": 15, "enabled": True},
    {"term": "example.com", "term_type": "domain", "weight": 12, "enabled": True},
    {"term": "内部", "term_type": "sensitive_keyword", "weight": 6, "enabled": True},
]
DEFAULT_SOURCE_FAMILIES = ["netdisk_aggregator", "search_engine", "document_library"]
DEFAULT_FILE_TYPES = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "7z", "txt", "csv"]
SOURCE_FAMILY_LABELS = {
    "search_engine": "搜索引擎监测",
    "netdisk_aggregator": "网盘监测",
    "document_library": "文库监测",
    "other": "其他来源",
}


ACCESS_STATE_LABELS = {
    "public": "公开访问",
    "login_required": "需要登录",
    "captcha": "需要验证码",
    "removed": "链接失效",
    "forbidden": "拒绝访问",
    "unknown": "待确认",
}
REVIEW_STATUS_LABELS = {
    "new": "未处理",
    "triaged": "处理中",
    "confirmed": "已确认",
    "false_positive": "误报",
    "closed": "已关闭",
}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()


def _strip_html(value: str) -> str:
    return _normalize_text(re.sub(r"<[^>]+>", " ", unescape(str(value or ""))))


def _canonical_title(value: str) -> str:
    return re.sub(r"\s+", " ", _normalize_text(value)).lower()


def _sanitize_url(value: str) -> str:
    return str(value or "").strip()


def _public_document_output_root() -> Path:
    path = output_root() / "document_exposure"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _query_output_dir(watchlist_name: str, source_key: str, term: str) -> Path:
    root = _public_document_output_root() / safe_stem(watchlist_name, "watchlist") / safe_stem(source_key, "source") / safe_stem(term, "term")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _public_output_url(path: Path) -> str:
    base = output_root().resolve()
    try:
        relative = path.resolve().relative_to(base)
    except ValueError:
        return path.resolve().as_uri()
    return f"/collector-output/{relative.as_posix()}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _watchlist_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _parse_json((payload or {}).get("metadata_json"), {})
    return data if isinstance(data, dict) else {}


def _source_family_for_source(source: DiscoverySource | None = None, platform_type: str | None = None) -> str:
    category = str((source.category if source is not None else platform_type) or "").strip().lower()
    if category == "netdisk_search":
        return "netdisk_aggregator"
    if category == "search_engine":
        return "search_engine"
    if category == "document_library":
        return "document_library"
    if category == "netdisk_share":
        return "netdisk_aggregator"
    return "other"


def _normalize_source_families(value: Any) -> list[str]:
    items = _parse_json(value, value)
    if isinstance(items, str):
        items = [part.strip() for part in items.split(",")]
    if not isinstance(items, list):
        items = []
    seen: set[str] = set()
    rows: list[str] = []
    for item in items:
        normalized = _normalize_text(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            rows.append(normalized)
    return rows or list(DEFAULT_SOURCE_FAMILIES)


def _normalize_file_types(value: Any) -> list[str]:
    items = _parse_json(value, value)
    if isinstance(items, str):
        items = [part.strip() for part in items.split(",")]
    if not isinstance(items, list):
        items = []
    seen: set[str] = set()
    rows: list[str] = []
    for item in items:
        normalized = _normalize_text(item).lower().lstrip(".")
        if normalized and normalized not in seen:
            seen.add(normalized)
            rows.append(normalized)
    return rows or list(DEFAULT_FILE_TYPES)


def _format_day_bucket(value: str | None) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _discovery_source_label(source_key: str | None) -> str:
    key = _normalize_text(source_key)
    for item in DISCOVERY_SOURCES:
        if item.key == key:
            return item.label
    return key


def _extract_access_code(*texts: Any) -> str:
    patterns = (
        re.compile(r"(?i)(?:提取码|访问码|口令|密码|code)[:：\s]*([A-Za-z0-9]{3,10})"),
        re.compile(r"(?i)(?:提取|访问)\s*[:：]?\s*([A-Za-z0-9]{3,10})"),
    )
    haystack = " ".join(_normalize_text(item) for item in texts if _normalize_text(item))
    if not haystack:
        return ""
    for pattern in patterns:
        match = pattern.search(haystack)
        if match:
            return _normalize_text(match.group(1))
    return ""


def _primary_file_name(file_names: list[str], title: str) -> str:
    for name in file_names:
        normalized = _normalize_text(name)
        if normalized:
            return normalized
    return _normalize_text(title)


def _file_type_from_name(name: str) -> str:
    text = _normalize_text(name)
    if "." not in text:
        return ""
    return text.rsplit(".", 1)[-1].lower()


def _matches_file_type(file_names: list[str], file_types: list[str]) -> bool:
    if not file_types:
        return True
    lowered_types = {item.lower().lstrip(".") for item in file_types if item}
    if not lowered_types:
        return True
    if not file_names:
        return True
    for name in file_names:
        suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if suffix and suffix in lowered_types:
            return True
    return False


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str]] = []
        self._in_script = False
        self._current_href = ""
        self._current_text: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._in_script = True
            return
        if self._in_script:
            return
        if tag == "a":
            attr_map = dict(attrs)
            self._current_href = str(attr_map.get("href") or "")
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._in_script = False
            return
        if self._in_script:
            return
        if tag == "a":
            href = _sanitize_url(self._current_href)
            text = _normalize_text("".join(self._current_text))
            if href:
                self.anchors.append({"href": href, "text": text})
            self._current_href = ""
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            return
        text = _normalize_text(data)
        if not text:
            return
        self._text_parts.append(text)
        if self._current_href:
            self._current_text.append(text)

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self._text_parts))


def _fetch_html(url: str, *, timeout: int = 30) -> str:
    request = Request(url, headers=HTTP_HEADERS)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _detect_search_block_reason(source: DiscoverySource, html: str, url: str) -> str:
    lowered = f"{html}\n{url}".lower()
    if "安全验证" in html or "captcha" in lowered or "verify you are human" in lowered:
        return f"{source.key}:captcha_or_security_verification"
    if "登录" in html or "sign in" in lowered or "passport.baidu.com" in lowered:
        return f"{source.key}:login_required"
    if "网络不给力" in html or "稍后重试" in html:
        return f"{source.key}:search_temporarily_unavailable"
    return ""


def _load_storage_state_path(platform_key: str) -> str | None:
    rows = {row["platform"]: row for row in build_platform_session_payloads()}
    row = rows.get(platform_key)
    if not row or not row.get("configured"):
        return None
    path = platform_storage_state_path(platform_key)
    return str(path) if path.exists() else None


def _matched_terms(title: str, preview_text: str, file_names: list[str], terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    haystack = " ".join([title, preview_text, " ".join(file_names)]).lower()
    matches = []
    seen: set[str] = set()
    for term in terms:
        value = _normalize_text(term.get("term"))
        if not value:
            continue
        lowered = value.lower()
        if lowered in haystack and lowered not in seen:
            seen.add(lowered)
            matches.append(
                {
                    "term": value,
                    "term_type": str(term.get("term_type") or "custom"),
                    "weight": int(term.get("weight") or 0),
                }
            )
    return matches


def _score_document_hit(title: str, preview_text: str, file_names: list[str], matches: list[dict[str, Any]], access_state: str) -> tuple[int, int, str]:
    confidence_score = 0
    risk_score = 0
    if matches:
        confidence_score += min(50, sum(int(item.get("weight") or 0) for item in matches))
    if file_names:
        confidence_score += min(20, len(file_names) * 3)
    if title:
        confidence_score += 10
    if preview_text:
        confidence_score += 10
    if access_state == "public":
        confidence_score += 10
    sensitive_hits = [token for token in SENSITIVE_KEYWORDS if token in title or token in preview_text]
    risk_score = confidence_score + min(30, len(sensitive_hits) * 8)
    if len(file_names) >= 3:
        risk_score += 10
    if any(name.lower().endswith((".zip", ".rar", ".7z")) for name in file_names):
        risk_score += 8
    risk_score = min(100, risk_score)
    severity = "high" if risk_score >= 75 else "medium" if risk_score >= 45 else "low"
    return min(100, confidence_score), risk_score, severity


def _detect_access_state(platform: ExposurePlatform, html: str, url: str) -> str:
    lowered = f"{html}\n{url}".lower()
    if any(token.lower() in lowered for token in ("验证", "captcha", "安全验证", "verify you are human")):
        return "captcha"
    if any(token.lower() in lowered for token in platform.login_indicators):
        return "login_required"
    if any(token in lowered for token in ("已失效", "链接不存在", "页面不存在", "404", "已删除", "不存在")):
        return "removed"
    if any(token in lowered for token in ("无权访问", "forbidden", "403")):
        return "forbidden"
    return "public"


def _extract_file_names(text: str, anchors: list[dict[str, str]]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for candidate in FILE_NAME_RE.findall(text):
        normalized = _normalize_text(candidate)
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            results.append(normalized)
    for item in anchors:
        label = _normalize_text(item.get("text"))
        if not label:
            continue
        if FILE_NAME_RE.search(label) and label.lower() not in seen:
            seen.add(label.lower())
            results.append(label)
    return results[:30]


def _parse_candidates_from_html(source: DiscoverySource, html: str, requested_url: str) -> list[dict[str, Any]]:
    parser = _AnchorParser()
    parser.feed(html)
    allowed_domains = monitored_domains(module="document_exposure")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parser.anchors:
        absolute = urljoin(requested_url, item["href"])
        absolute = _sanitize_url(absolute)
        if not absolute.startswith("http"):
            continue
        host = urlparse(absolute).netloc.lower()
        platform = platform_from_url(absolute)
        if source.category == "netdisk_search":
            if platform is None or platform.platform_type != "netdisk_share":
                continue
        elif source.category == "document_library":
            if platform is None or platform.platform_type != "document_library":
                continue
        else:
            if not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
                continue
        if absolute in seen:
            continue
        seen.add(absolute)
        candidates.append(
            {
                "url": absolute,
                "title": _normalize_text(item.get("text")) or absolute,
                "source": source.key,
            }
        )
    return candidates


def _build_search_urls(term: str) -> list[tuple[DiscoverySource, str]]:
    encoded = quote_plus(term)
    return [(source, source.search_url_template.format(query=encoded)) for source in DISCOVERY_SOURCES]


def _detail_payload_from_page(
    *,
    platform: ExposurePlatform,
    detail_url: str,
    source_query: str,
    source_url: str,
) -> dict[str, Any]:
    storage_state = _load_storage_state_path(platform.key) if platform.requires_login else None
    artifacts = fetch_page_artifacts_with_session(
        detail_url,
        storage_state_path=storage_state,
        wait_seconds=4,
        timeout_seconds=45,
    )
    html = artifacts["html"]
    parser = _AnchorParser()
    parser.feed(html)
    preview_text = parser.text[:PREVIEW_TEXT_LIMIT]
    file_names = _extract_file_names(preview_text, parser.anchors)
    access_state = _detect_access_state(platform, html, str(artifacts["url"]))
    return {
        "platform": platform,
        "page_url": str(artifacts["url"]),
        "page_title": _normalize_text(artifacts["title"]) or _normalize_text(platform.label),
        "html": html,
        "screenshot_png": artifacts["screenshot_png"],
        "preview_text": preview_text,
        "ocr_text": preview_text,
        "file_names": file_names,
        "access_state": access_state,
        "source_query": source_query,
        "source_url": source_url,
    }


def _write_snapshot_files(
    watchlist_name: str,
    platform_key: str,
    term: str,
    page_title: str,
    html: str,
    screenshot_png: bytes,
    payload: dict[str, Any],
) -> tuple[Path, Path]:
    base_dir = _query_output_dir(watchlist_name, platform_key, term)
    stem = safe_stem(page_title or platform_key, "detail")
    html_path = base_dir / f"{stem}.html"
    screenshot_path = base_dir / f"{stem}.png"
    dump_text(html_path, html)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(screenshot_png)
    dump_json(base_dir / f"{stem}.json", payload)
    return html_path, screenshot_path


def ensure_default_watchlist() -> dict[str, Any]:
    with get_db_connection() as connection:
        existing = list_exposure_watchlists(connection)
        if existing:
            watchlist = existing[0]
            terms = list_exposure_watch_terms(connection, int(watchlist["id"]))
            metadata = _watchlist_metadata(watchlist)
            return {
                **watchlist,
                "terms": terms,
                "source_families": metadata.get("source_families") or list(DEFAULT_SOURCE_FAMILIES),
                "file_types": metadata.get("file_types") or list(DEFAULT_FILE_TYPES),
                "page_limit": int(metadata.get("page_limit") or 4),
                "detail_fetch": bool(metadata.get("detail_fetch", True)),
            }
        now = _now_utc_iso()
        watchlist_id = upsert_exposure_watchlist(
            connection,
            {
                "name": "默认监测对象",
                "organization_name": "示例企业",
                "enabled": True,
                "notes": "文件监测默认对象",
                "metadata_json": _json_dumps(
                    {
                        "source_families": DEFAULT_SOURCE_FAMILIES,
                        "file_types": DEFAULT_FILE_TYPES,
                        "page_limit": 4,
                        "detail_fetch": True,
                    }
                ),
                "created_at": now,
                "updated_at": now,
            },
        )
        replace_exposure_watch_terms(
            connection,
            watchlist_id,
            [{**row, "created_at": now, "updated_at": now} for row in DEFAULT_TERMS],
        )
        connection.commit()
        return {
            "id": watchlist_id,
            "name": "默认监测对象",
            "organization_name": "示例企业",
            "enabled": True,
            "notes": "文件监测默认对象",
            "metadata_json": _json_dumps(
                {
                    "source_families": DEFAULT_SOURCE_FAMILIES,
                    "file_types": DEFAULT_FILE_TYPES,
                    "page_limit": 4,
                    "detail_fetch": True,
                }
            ),
            "created_at": now,
            "updated_at": now,
            "terms": list_exposure_watch_terms(connection, watchlist_id),
            "source_families": list(DEFAULT_SOURCE_FAMILIES),
            "file_types": list(DEFAULT_FILE_TYPES),
            "page_limit": 4,
            "detail_fetch": True,
        }


def list_watchlists_payload() -> list[dict[str, Any]]:
    ensure_default_watchlist()
    with get_db_connection() as connection:
        rows = list_exposure_watchlists(connection)
        payloads = []
        for row in rows:
            metadata = _watchlist_metadata(row)
            payloads.append(
                {
                    **row,
                    "terms": list_exposure_watch_terms(connection, int(row["id"])),
                    "source_families": metadata.get("source_families") or list(DEFAULT_SOURCE_FAMILIES),
                    "file_types": metadata.get("file_types") or list(DEFAULT_FILE_TYPES),
                    "page_limit": int(metadata.get("page_limit") or 4),
                    "detail_fetch": bool(metadata.get("detail_fetch", True)),
                }
            )
        return payloads


def save_watchlist_payload(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_utc_iso()
    with get_db_connection() as connection:
        watchlist_id = upsert_exposure_watchlist(
            connection,
            {
                "id": payload.get("id"),
                "name": payload.get("name"),
                "organization_name": payload.get("organization_name"),
                "enabled": payload.get("enabled", True),
                "notes": payload.get("notes", ""),
                "metadata_json": _json_dumps(
                    {
                        "source_families": payload.get("source_families") or list(DEFAULT_SOURCE_FAMILIES),
                        "file_types": payload.get("file_types") or list(DEFAULT_FILE_TYPES),
                        "page_limit": int(payload.get("page_limit") or 4),
                        "detail_fetch": bool(payload.get("detail_fetch", True)),
                    }
                ),
                "created_at": payload.get("created_at") or now,
                "updated_at": now,
            },
        )
        rows = payload.get("terms") or []
        replace_exposure_watch_terms(
            connection,
            watchlist_id,
            [
                {
                    "term": row.get("term"),
                    "term_type": row.get("term_type"),
                    "weight": row.get("weight", 10),
                    "enabled": row.get("enabled", True),
                    "created_at": now,
                    "updated_at": now,
                }
                for row in rows
            ],
        )
        connection.commit()
        watchlist = get_exposure_watchlist(connection, watchlist_id)
        metadata = _watchlist_metadata(watchlist or {})
        return {
            **(watchlist or {}),
            "terms": list_exposure_watch_terms(connection, watchlist_id),
            "source_families": metadata.get("source_families") or list(DEFAULT_SOURCE_FAMILIES),
            "file_types": metadata.get("file_types") or list(DEFAULT_FILE_TYPES),
            "page_limit": int(metadata.get("page_limit") or 4),
            "detail_fetch": bool(metadata.get("detail_fetch", True)),
        }


def scan_watchlist_once(
    watchlist_id: int,
    *,
    max_candidates_per_term: int = 6,
    source_families: list[str] | None = None,
    file_types: list[str] | None = None,
    page_limit: int | None = None,
    detail_fetch: bool | None = None,
) -> dict[str, Any]:
    ensure_default_watchlist()
    started_at = _now_utc_iso()
    with get_db_connection() as connection:
        watchlist = get_exposure_watchlist(connection, watchlist_id)
        if watchlist is None:
            raise ValueError(f"watchlist not found: {watchlist_id}")
        if not bool(watchlist.get("enabled")):
            return {"watchlist_id": watchlist_id, "scanned_terms": 0, "candidates": 0, "hits": 0, "message": "watchlist disabled"}
        terms = [item for item in list_exposure_watch_terms(connection, watchlist_id) if bool(item.get("enabled"))]
    watchlist_meta = _watchlist_metadata(watchlist)
    selected_source_families = _normalize_source_families(source_families or watchlist_meta.get("source_families"))
    selected_file_types = _normalize_file_types(file_types or watchlist_meta.get("file_types"))
    selected_page_limit = int(page_limit or watchlist_meta.get("page_limit") or max_candidates_per_term or 4)
    selected_detail_fetch = bool(detail_fetch if detail_fetch is not None else watchlist_meta.get("detail_fetch", True))

    total_candidates = 0
    total_hits = 0
    errors: list[str] = []
    seen_candidate_urls: set[str] = set()
    now = _now_utc_iso()
    for term_row in terms:
        term = _normalize_text(term_row.get("term"))
        if not term:
            continue
        for source, url in _build_search_urls(term):
            source_family = _source_family_for_source(source)
            if source_family not in selected_source_families:
                continue
            try:
                search_html = _fetch_html(url, timeout=30)
            except Exception as exc:
                errors.append(f"{source.key}:{term}:{exc}")
                continue
            block_reason = _detect_search_block_reason(source, search_html, url)
            if block_reason:
                errors.append(f"{block_reason}:{term}")
                continue
            candidates = _parse_candidates_from_html(source, search_html, url)[:selected_page_limit]
            total_candidates += len(candidates)
            for candidate in candidates:
                candidate_url = _normalize_text(candidate.get("url"))
                if not candidate_url or candidate_url in seen_candidate_urls:
                    continue
                seen_candidate_urls.add(candidate_url)
                detail_platform = platform_from_url(candidate["url"])
                if detail_platform is None:
                    continue
                try:
                    if selected_detail_fetch:
                        detail = _detail_payload_from_page(
                            platform=detail_platform,
                            detail_url=candidate["url"],
                            source_query=term,
                            source_url=url,
                        )
                    else:
                        detail = {
                            "platform": detail_platform,
                            "page_url": candidate["url"],
                            "page_title": _normalize_text(candidate.get("title")) or candidate["url"],
                            "html": "",
                            "screenshot_png": b"",
                            "preview_text": _normalize_text(candidate.get("title")),
                            "ocr_text": _normalize_text(candidate.get("title")),
                            "file_names": _extract_file_names(_normalize_text(candidate.get("title")), []),
                            "access_state": "unknown",
                            "source_query": term,
                            "source_url": url,
                        }
                except Exception as exc:
                    errors.append(f"{detail_platform.key}:{candidate['url']}:{exc}")
                    continue
                if not _matches_file_type(detail["file_names"], selected_file_types):
                    continue
                matches = _matched_terms(
                    detail["page_title"],
                    detail["preview_text"],
                    detail["file_names"],
                    terms,
                )
                if not matches:
                    continue
                confidence_score, risk_score, severity = _score_document_hit(
                    detail["page_title"],
                    detail["preview_text"],
                    detail["file_names"],
                    matches,
                    detail["access_state"],
                )
                raw_payload = {
                    "candidate": candidate,
                    "page_url": detail["page_url"],
                    "source_query": term,
                    "source_url": url,
                    "file_names": detail["file_names"],
                    "preview_text": detail["preview_text"],
                }
                with get_db_connection() as connection:
                    hit_id = upsert_document_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": detail_platform.key,
                            "platform_type": detail_platform.platform_type,
                            "discovery_source": source.key,
                            "canonical_url": detail["page_url"],
                            "normalized_title": _canonical_title(detail["page_title"]),
                            "title": detail["page_title"],
                            "access_state": detail["access_state"],
                            "confidence_score": confidence_score,
                            "risk_score": risk_score,
                            "severity": severity,
                            "matched_terms_json": _json_dumps(matches),
                            "file_count": len(detail["file_names"]),
                            "share_owner": "",
                            "disclosure_time": "",
                            "first_seen_at": now,
                            "last_seen_at": now,
                            "raw_json": _json_dumps(raw_payload),
                        },
                    )
                    html_path, screenshot_path = _write_snapshot_files(
                        str(watchlist["name"]),
                        detail_platform.key,
                        term,
                        detail["page_title"],
                        detail["html"],
                        detail["screenshot_png"],
                        raw_payload,
                    )
                    snapshot_id = insert_document_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": now,
                            "source_query": term,
                            "source_url": url,
                            "page_url": detail["page_url"],
                            "page_title": detail["page_title"],
                            "html_path": str(html_path),
                            "screenshot_path": str(screenshot_path),
                            "ocr_text": detail["ocr_text"],
                            "preview_text": detail["preview_text"],
                            "file_list_json": _json_dumps(
                                [{"name": name, "size": "", "path": name} for name in detail["file_names"]]
                            ),
                            "access_state": detail["access_state"],
                            "matched_terms_json": _json_dumps(matches),
                            "raw_json": _json_dumps(raw_payload),
                        },
                    )
                    update_document_hit_last_snapshot(connection, hit_id, snapshot_id)
                    connection.commit()
                    ensure_normalized_intelligence(connection, force=True)
                total_hits += 1
    result = {
        "watchlist_id": watchlist_id,
        "watchlist_name": watchlist["name"],
        "scanned_terms": len(terms),
        "candidates": total_candidates,
        "hits": total_hits,
        "errors": errors,
        "source_families": selected_source_families,
        "file_types": selected_file_types,
        "page_limit": selected_page_limit,
        "detail_fetch": selected_detail_fetch,
    }
    finished_at = _now_utc_iso()
    with get_db_connection() as connection:
        insert_exposure_scan_run(
            connection,
            {
                "watchlist_id": int(watchlist["id"]),
                "source_families_json": _json_dumps(selected_source_families),
                "requested_terms_json": _json_dumps([_normalize_text(item.get("term")) for item in terms if _normalize_text(item.get("term"))]),
                "candidate_count": total_candidates,
                "hit_count": total_hits,
                "error_count": len(errors),
                "status": "failed" if errors and total_hits == 0 else "partial" if errors else "succeeded",
                "errors_json": _json_dumps(errors),
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
        connection.commit()
    result["started_at"] = started_at
    result["finished_at"] = finished_at
    return result


def list_document_exposures_payload(
    *,
    watchlist_id: int | None = None,
    review_status: str | None = None,
    platform: str | None = None,
    access_state: str | None = None,
    source_family: str | None = None,
    limit: int | None = 200,
) -> list[dict[str, Any]]:
    ensure_default_watchlist()
    with get_db_connection() as connection:
        rows = list_document_hits(
            connection,
            watchlist_id=watchlist_id,
            review_status=review_status,
            platform=platform,
            access_state=access_state,
            limit=limit,
        )
    payloads = []
    for row in rows:
        matched_terms = json.loads(str(row.get("matched_terms_json") or "[]"))
        raw_payload = json.loads(str(row.get("raw_json") or "{}"))
        file_names = [
            _normalize_text(item)
            for item in _parse_json((raw_payload or {}).get("file_names"), [])
            if _normalize_text(item)
        ]
        primary_file_name = _primary_file_name(file_names, str(row.get("title") or ""))
        share_code = _extract_access_code(
            row.get("title"),
            (raw_payload or {}).get("preview_text"),
            " ".join(file_names),
        )
        platform_key = row.get("platform") or ""
        platform_label = get_exposure_platform(str(platform_key)).label if platform_key in PLATFORMS else str(platform_key)
        payloads.append(
            {
                "id": int(row["id"]),
                "watchlistId": int(row["watchlist_id"]),
                "watchlistName": row.get("watchlist_name") or "",
                "organizationName": row.get("organization_name") or "",
                "platform": platform_key,
                "platformLabel": platform_label,
                "platformType": row.get("platform_type") or "",
                "discoverySource": row.get("discovery_source") or "",
                "discoverySourceLabel": _discovery_source_label(row.get("discovery_source")),
                "sourceFamily": _source_family_for_source(platform_type=row.get("platform_type"), source=next((item for item in DISCOVERY_SOURCES if item.key == row.get("discovery_source")), None)),
                "canonicalUrl": row.get("canonical_url") or "",
                "title": row.get("title") or "",
                "normalizedTitle": row.get("normalized_title") or "",
                "accessState": row.get("access_state") or "",
                "accessStateLabel": ACCESS_STATE_LABELS.get(str(row.get("access_state") or ""), str(row.get("access_state") or "")),
                "confidenceScore": int(row.get("confidence_score") or 0),
                "riskScore": int(row.get("risk_score") or 0),
                "severity": row.get("severity") or "low",
                "reviewStatus": row.get("review_status") or "new",
                "reviewStatusLabel": REVIEW_STATUS_LABELS.get(str(row.get("review_status") or "new"), str(row.get("review_status") or "new")),
                "matchedTerms": matched_terms,
                "fileCount": int(row.get("file_count") or 0),
                "evidenceCount": int(row.get("evidence_count") or 0),
                "shareOwner": row.get("share_owner") or "",
                "primaryFileName": primary_file_name,
                "primaryFileType": _file_type_from_name(primary_file_name),
                "shareCode": share_code,
                "shareType": "password_share" if share_code else "public_share",
                "disclosureTime": row.get("disclosure_time") or "",
                "firstSeenAt": row.get("first_seen_at") or "",
                "lastSeenAt": row.get("last_seen_at") or "",
                "lastSnapshotId": row.get("last_snapshot_id"),
                "summary": _normalize_text((raw_payload or {}).get("preview_text") or "")[:280],
            }
        )
    if source_family:
        payloads = [item for item in payloads if item.get("sourceFamily") == source_family]
    return payloads


def build_document_exposure_detail(hit_id: int) -> dict[str, Any] | None:
    with get_db_connection() as connection:
        row = get_document_hit(connection, hit_id)
        if row is None:
            return None
        watchlist = get_exposure_watchlist(connection, int(row["watchlist_id"]))
        snapshots = list_document_hit_snapshots(connection, hit_id)
        reviews = list_document_hit_reviews(connection, hit_id)
    matched_terms = json.loads(str(row.get("matched_terms_json") or "[]"))
    raw_payload = json.loads(str(row.get("raw_json") or "{}"))
    formatted_snapshots = []
    for item in snapshots:
        file_list = json.loads(str(item.get("file_list_json") or "[]"))
        matched_snapshot_terms = json.loads(str(item.get("matched_terms_json") or "[]"))
        html_path_raw = _normalize_text(item.get("html_path"))
        screenshot_path_raw = _normalize_text(item.get("screenshot_path"))
        html_path = Path(html_path_raw) if html_path_raw else None
        screenshot_path = Path(screenshot_path_raw) if screenshot_path_raw else None
        formatted_snapshots.append(
            {
                "id": int(item["id"]),
                "fetchedAt": item.get("fetched_at") or "",
                "sourceQuery": item.get("source_query") or "",
                "sourceUrl": item.get("source_url") or "",
                "pageUrl": item.get("page_url") or "",
                "pageTitle": item.get("page_title") or "",
                "htmlPath": str(html_path or ""),
                "htmlUrl": _public_output_url(html_path) if html_path else "",
                "screenshotPath": str(screenshot_path or ""),
                "screenshotUrl": _public_output_url(screenshot_path) if screenshot_path else "",
                "ocrText": item.get("ocr_text") or "",
                "previewText": item.get("preview_text") or "",
                "fileList": file_list,
                "accessState": item.get("access_state") or "",
                "matchedTerms": matched_snapshot_terms,
            }
        )
    latest_snapshot = formatted_snapshots[0] if formatted_snapshots else {}
    preview_assets: list[dict[str, str]] = []
    if latest_snapshot.get("screenshotUrl"):
        preview_assets.append({"kind": "screenshot", "label": "页面截图", "url": latest_snapshot["screenshotUrl"]})
    if latest_snapshot.get("htmlUrl"):
        preview_assets.append({"kind": "html", "label": "页面快照", "url": latest_snapshot["htmlUrl"]})
    file_list: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for snapshot in formatted_snapshots:
        for file_row in snapshot.get("fileList") or []:
            file_name = _normalize_text(file_row.get("name") or file_row.get("path"))
            file_path = _normalize_text(file_row.get("path") or file_name)
            dedupe_key = f"{file_name}|{file_path}"
            if not file_name or dedupe_key in seen_files:
                continue
            seen_files.add(dedupe_key)
            file_list.append(
                {
                    "name": file_name,
                    "path": file_path,
                    "size": _normalize_text(file_row.get("size")),
                    "type": _file_type_from_name(file_name),
                }
            )
    discovery_source_key = row.get("discovery_source") or ""
    discovery_source = next((item for item in DISCOVERY_SOURCES if item.key == discovery_source_key), None)
    source_family = _source_family_for_source(
        platform_type=row.get("platform_type"),
        source=discovery_source,
    )
    source_family_label = SOURCE_FAMILY_LABELS.get(source_family, source_family)
    platform_key = row.get("platform") or ""
    platform_label = get_exposure_platform(str(platform_key)).label if platform_key in PLATFORMS else str(platform_key)
    preview_text = _normalize_text(
        latest_snapshot.get("previewText")
        or latest_snapshot.get("ocrText")
        or (raw_payload or {}).get("preview_text")
    )
    share_code = _extract_access_code(
        preview_text,
        row.get("title"),
        " ".join(file_row.get("name") or "" for file_row in file_list),
    )
    risk_reasons: list[str] = []
    if matched_terms:
        matched_names = [
            _normalize_text(item.get("term"))
            for item in matched_terms[:4]
            if _normalize_text(item.get("term"))
        ]
        if matched_names:
            risk_reasons.append(f"命中监测词：{', '.join(matched_names)}")
    if file_list:
        risk_reasons.append(f"关联文件 {len(file_list)} 个")
    if row.get("access_state") == "public":
        risk_reasons.append("目标页面可公开访问")
    elif row.get("access_state") == "login_required":
        risk_reasons.append("目标页面需要登录复核")
    return {
        "id": int(row["id"]),
        "watchlist": watchlist or {},
        "watchlistId": int(row["watchlist_id"]),
        "watchlistName": watchlist.get("name") if watchlist else "",
        "organizationName": watchlist.get("organization_name") if watchlist else "",
        "platform": row.get("platform") or "",
        "platformLabel": platform_label,
        "platformType": row.get("platform_type") or "",
        "discoverySource": row.get("discovery_source") or "",
        "discoverySourceLabel": discovery_source.label if discovery_source else discovery_source_key,
        "sourceFamily": source_family,
        "sourceFamilyLabel": source_family_label,
        "canonicalUrl": row.get("canonical_url") or "",
        "title": translate_event_title_live(row.get("title")),
        "originalTitle": row.get("title") or "",
        "normalizedTitle": row.get("normalized_title") or "",
        "accessState": row.get("access_state") or "",
        "accessStateLabel": ACCESS_STATE_LABELS.get(str(row.get("access_state") or ""), str(row.get("access_state") or "")),
        "confidenceScore": int(row.get("confidence_score") or 0),
        "riskScore": int(row.get("risk_score") or 0),
        "severity": row.get("severity") or "",
        "reviewStatus": row.get("review_status") or "",
        "matchedTerms": matched_terms,
        "fileCount": int(row.get("file_count") or 0),
        "evidenceCount": int(row.get("evidence_count") or 0),
        "shareOwner": row.get("share_owner") or "",
        "disclosureTime": row.get("disclosure_time") or "",
        "firstSeenAt": row.get("first_seen_at") or "",
        "lastSeenAt": row.get("last_seen_at") or "",
        "rawPayload": raw_payload,
        "latestSnapshot": latest_snapshot,
        "previewAssets": preview_assets,
        "fileList": file_list,
        "shareMeta": {
            "shareUrl": row.get("canonical_url") or "",
            "shareCode": share_code,
            "shareType": "password_share" if share_code else "public_share",
            "shareOwner": row.get("share_owner") or "",
            "accessState": row.get("access_state") or "",
            "accessStateLabel": ACCESS_STATE_LABELS.get(str(row.get("access_state") or ""), str(row.get("access_state") or "")),
        },
        "sourceResult": {
            "query": latest_snapshot.get("sourceQuery") or (raw_payload or {}).get("source_query") or "",
            "sourceUrl": latest_snapshot.get("sourceUrl") or (raw_payload or {}).get("source_url") or "",
            "pageUrl": latest_snapshot.get("pageUrl") or row.get("canonical_url") or "",
        },
        "documentMeta": {
            "primaryFileName": file_list[0]["name"] if file_list else _primary_file_name(_parse_json((raw_payload or {}).get("file_names"), []), str(row.get("title") or "")),
            "primaryFileType": file_list[0]["type"] if file_list else "",
            "fileCount": len(file_list) or int(row.get("file_count") or 0),
            "evidenceCount": int(row.get("evidence_count") or 0),
        },
        "riskAnalysis": {
            "score": int(row.get("risk_score") or 0),
            "severity": row.get("severity") or "",
            "confidenceScore": int(row.get("confidence_score") or 0),
            "reasons": risk_reasons,
        },
        "snapshots": formatted_snapshots,
        "reviews": reviews,
    }


def add_document_exposure_review(hit_id: int, *, status: str, reviewer: str = "", note: str = "") -> dict[str, Any]:
    with get_db_connection() as connection:
        add_document_hit_review(
            connection,
            {
                "hit_id": int(hit_id),
                "status": status,
                "reviewer": reviewer,
                "note": note,
                "created_at": _now_utc_iso(),
            },
        )
        connection.commit()
    detail = build_document_exposure_detail(hit_id)
    if detail is None:
        raise ValueError(f"document exposure not found: {hit_id}")
    return detail


def build_document_exposure_summary(source_family: str | None = None) -> dict[str, Any]:
    rows = list_document_exposures_payload(limit=500, source_family=source_family)
    high_risk = [row for row in rows if int(row.get("riskScore") or 0) >= 75]
    login_required = [row for row in rows if row.get("accessState") == "login_required"]
    platforms = sorted({row.get("platform") for row in rows if row.get("platform")})
    pending_review = [row for row in rows if str(row.get("reviewStatus") or "new") in {"", "new", "triaged"}]
    watchlists = list_watchlists_payload()
    enabled_term_count = sum(
        1
        for watchlist in watchlists
        for term in (watchlist.get("terms") or [])
        if bool(term.get("enabled"))
    )
    sessions = build_platform_session_payloads(module="document_exposure", manageable_only=True)
    configured_sessions = [row for row in sessions if bool(row.get("configured"))]
    invalid_sessions = [row for row in sessions if str(row.get("status") or "") in {"invalid", "missing", "unavailable"}]
    scan_runs = list_exposure_scan_runs_payload(limit=50)
    if source_family:
        scan_runs = [item for item in scan_runs if source_family in (item.get("sourceFamilies") or [])]
    latest_scan = scan_runs[0] if scan_runs else {}
    today = datetime.now(timezone.utc).date()
    trend_counter = {}
    for offset in range(6, -1, -1):
        trend_counter[(today - timedelta(days=offset)).isoformat()] = 0
    platform_distribution: dict[str, int] = {}
    discovery_distribution: dict[str, int] = {}
    risk_distribution = {"high": 0, "medium": 0, "low": 0}
    access_distribution: dict[str, int] = {}
    review_distribution: dict[str, int] = {}
    keyword_top: dict[str, int] = {}
    file_total = 0
    evidence_total = 0
    recent_count = 0
    invalid_count = 0
    public_count = 0
    for row in rows:
        bucket = _format_day_bucket(row.get("lastSeenAt") or row.get("firstSeenAt"))
        if bucket in trend_counter:
            trend_counter[bucket] += 1
            if bucket == today.isoformat():
                recent_count += 1
        platform_label = _normalize_text(row.get("platformLabel") or row.get("platform") or "未知平台")
        platform_distribution[platform_label] = platform_distribution.get(platform_label, 0) + 1
        discovery_label = _normalize_text(row.get("discoverySourceLabel") or row.get("discoverySource") or platform_label)
        discovery_distribution[discovery_label] = discovery_distribution.get(discovery_label, 0) + 1
        severity = str(row.get("severity") or "low")
        risk_distribution[severity] = risk_distribution.get(severity, 0) + 1
        access_state = str(row.get("accessState") or "unknown")
        access_distribution[access_state] = access_distribution.get(access_state, 0) + 1
        review_state = str(row.get("reviewStatus") or "new")
        review_distribution[review_state] = review_distribution.get(review_state, 0) + 1
        if access_state == "public":
            public_count += 1
        if access_state in {"removed", "forbidden"}:
            invalid_count += 1
        file_total += int(row.get("fileCount") or 0)
        evidence_total += int(row.get("evidenceCount") or 0)
        for term in row.get("matchedTerms") or []:
            term_name = _normalize_text(term.get("term"))
            if term_name:
                keyword_top[term_name] = keyword_top.get(term_name, 0) + 1
    return {
        "sourceFamily": source_family or "",
        "sourceFamilyLabel": SOURCE_FAMILY_LABELS.get(source_family or "", "文件监测"),
        "totalHits": len(rows),
        "highRiskCount": len(high_risk),
        "loginRequiredCount": len(login_required),
        "platformCount": len(platforms),
        "platforms": platforms,
        "pendingReviewCount": len(pending_review),
        "configuredSessionCount": len(configured_sessions),
        "invalidSessionCount": len(invalid_sessions),
        "watchlistCount": len(watchlists),
        "enabledTermCount": enabled_term_count,
        "lastScanAt": str(latest_scan.get("finishedAt") or ""),
        "lastCandidateCount": int(latest_scan.get("candidateCount") or 0),
        "lastHitCount": int(latest_scan.get("hitCount") or 0),
        "lastErrorCount": int(latest_scan.get("errorCount") or 0),
        "recentCount": recent_count,
        "publicCount": public_count,
        "invalidCount": invalid_count,
        "fileCount": file_total,
        "evidenceCount": evidence_total,
        "trend": [{"date": key, "value": value} for key, value in trend_counter.items()],
        "platformDistribution": [{"name": key, "value": value} for key, value in sorted(platform_distribution.items(), key=lambda item: item[1], reverse=True)],
        "discoveryDistribution": [{"name": key, "value": value} for key, value in sorted(discovery_distribution.items(), key=lambda item: item[1], reverse=True)],
        "riskDistribution": [
            {"key": "high", "label": "高危", "value": risk_distribution.get("high", 0)},
            {"key": "medium", "label": "中危", "value": risk_distribution.get("medium", 0)},
            {"key": "low", "label": "低危", "value": risk_distribution.get("low", 0)},
        ],
        "accessStateDistribution": [
            {"key": key, "label": ACCESS_STATE_LABELS.get(key, key), "value": value}
            for key, value in sorted(access_distribution.items(), key=lambda item: item[1], reverse=True)
        ],
        "reviewDistribution": [
            {"key": key, "label": REVIEW_STATUS_LABELS.get(key, key), "value": value}
            for key, value in sorted(review_distribution.items(), key=lambda item: item[1], reverse=True)
        ],
        "keywordTop": [{"name": key, "value": value} for key, value in sorted(keyword_top.items(), key=lambda item: item[1], reverse=True)[:10]],
    }


def list_exposure_scan_runs_payload(watchlist_id: int | None = None, limit: int | None = 50) -> list[dict[str, Any]]:
    ensure_default_watchlist()
    with get_db_connection() as connection:
        rows = list_exposure_scan_runs(connection, watchlist_id=watchlist_id, limit=limit)
    payloads: list[dict[str, Any]] = []
    for row in rows:
        payloads.append(
            {
                "id": int(row["id"]),
                "watchlistId": int(row["watchlist_id"]),
                "watchlistName": row.get("watchlist_name") or "",
                "organizationName": row.get("organization_name") or "",
                "sourceFamilies": _normalize_source_families(row.get("source_families_json")),
                "requestedTerms": _parse_json(row.get("requested_terms_json"), []),
                "candidateCount": int(row.get("candidate_count") or 0),
                "hitCount": int(row.get("hit_count") or 0),
                "errorCount": int(row.get("error_count") or 0),
                "status": str(row.get("status") or "unknown"),
                "errors": _parse_json(row.get("errors_json"), []),
                "startedAt": str(row.get("started_at") or ""),
                "finishedAt": str(row.get("finished_at") or ""),
            }
        )
    return payloads


def _format_date(value: str | None) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def build_document_exposure_event_records(limit: int | None = None) -> list[dict[str, Any]]:
    rows = list_document_exposures_payload(limit=limit or 200)
    events: list[dict[str, Any]] = []
    for row in rows:
        platform_label = get_exposure_platform(str(row.get("platform") or "")).label if row.get("platform") in PLATFORMS else str(row.get("platform") or "")
        summary = _normalize_text(row.get("summary"))
        events.append(
            {
                "id": f"document:{int(row['id'])}",
                "event_type": "document",
                "normalized_event_type": "document_exposure",
                "raw_source_type": "document_hits",
                "rawSourceTypeLabel": "文件监测命中",
                "disclosureTime": _format_date(row.get("disclosureTime") or row.get("lastSeenAt")),
                "disclosureTimeRaw": row.get("disclosureTime") or row.get("lastSeenAt") or "",
                "disclosureDate": _format_date(row.get("disclosureTime") or row.get("lastSeenAt")),
                "updatedTime": row.get("lastSeenAt") or "",
                "updatedTimeRaw": row.get("lastSeenAt") or "",
                "title": translate_event_title_live(row.get("title")),
                "originalTitle": row.get("title") or "",
                "category": "文件监测外泄",
                "attacker": platform_label,
                "sourceSite": platform_label,
                "industry": "未知",
                "country": "未知",
                "countryCode": "",
                "macroRegion": "未知",
                "region": "未知",
                "severity": row.get("severity") or "low",
                "victim": row.get("organizationName") or row.get("watchlistName") or "未知实体",
                "riskScore": int(row.get("riskScore") or 0),
                "riskReasons": [
                    f"命中监测词: {', '.join(item.get('term') for item in row.get('matchedTerms', [])[:3] if item.get('term'))}"
                ] if row.get("matchedTerms") else [],
                "monitoringMatches": row.get("matchedTerms") or [],
                "monitoringWeight": int(sum(int(item.get("weight") or 0) for item in row.get("matchedTerms") or [])),
                "monitoringPriority": "high" if int(row.get("riskScore") or 0) >= 75 else "medium" if int(row.get("riskScore") or 0) >= 45 else "low",
                "sampleLinks": [{"url": row.get("canonicalUrl") or "", "kind": row.get("platform") or "document"}] if row.get("canonicalUrl") else [],
                "sampleLinkCount": 1 if row.get("canonicalUrl") else 0,
                "hasSampleEvidence": bool(row.get("evidenceCount")),
                "priorityScore": int(row.get("riskScore") or 0),
                "confidenceScore": int(row.get("confidenceScore") or 0),
                "completenessScore": min(100, 30 + int(row.get("evidenceCount") or 0) * 10 + int(row.get("fileCount") or 0) * 5),
                "summary": summary,
                "reviewStatus": row.get("reviewStatus") or "new",
                "accessState": row.get("accessState") or "unknown",
                "platform": row.get("platform") or "",
                "fileCount": int(row.get("fileCount") or 0),
            }
        )
    return events


def build_document_exposure_event_detail(event_id: str) -> dict[str, Any] | None:
    if not str(event_id or "").startswith("document:"):
        return None
    try:
        hit_id = int(str(event_id).split(":", 1)[1])
    except Exception:
        return None
    detail = build_document_exposure_detail(hit_id)
    if detail is None:
        return None
    platform_key = str(detail.get("platform") or "")
    platform_label = get_exposure_platform(platform_key).label if platform_key in PLATFORMS else platform_key
    matched_terms = detail.get("matchedTerms") or []
    snapshot = detail["snapshots"][0] if detail.get("snapshots") else {}
    mirror_resources = []
    if snapshot.get("htmlUrl"):
        mirror_resources.append({"label": "本地HTML快照", "url": snapshot["htmlUrl"]})
    for item in snapshot.get("fileList") or []:
        if isinstance(item, dict) and item.get("name"):
            mirror_resources.append({"label": f"文件: {item['name']}", "url": detail.get("canonicalUrl") or ""})
    screenshot_resources = []
    if snapshot.get("screenshotUrl"):
        screenshot_resources.append({"label": "预览截图", "url": snapshot["screenshotUrl"]})
    return {
        "id": event_id,
        "identifier": event_id,
        "event_type": "document",
        "normalized_event_type": "document_exposure",
        "raw_source_type": "document_hits",
        "raw_source_type_label": "文件监测命中",
        "title": translate_event_title_live(detail.get("title")),
        "original_title": detail.get("originalTitle") or detail.get("title") or "",
        "disclosure_time": _format_date(detail.get("disclosureTime") or detail.get("lastSeenAt")),
        "disclosure_time_raw": detail.get("disclosureTime") or detail.get("lastSeenAt") or "",
        "updated_time": detail.get("lastSeenAt") or "",
        "updated_time_raw": detail.get("lastSeenAt") or "",
        "attacker": platform_label,
        "disclosure_url": detail.get("canonicalUrl") or "",
        "detail_text": snapshot.get("previewText") or snapshot.get("ocrText") or _normalize_text((detail.get("rawPayload") or {}).get("preview_text")),
        "category": "文件监测外泄",
        "source": platform_label,
        "industry": "未知",
        "country": "未知",
        "country_code": "",
        "macro_region": "未知",
        "region": "未知",
        "mirror_resources": mirror_resources,
        "screenshot_resources": screenshot_resources,
        "json_preview_url": "",
        "victim": (detail.get("watchlist") or {}).get("organization_name") or "未知实体",
        "risk_score": int(detail.get("riskScore") or 0),
        "risk_reasons": [
            f"命中监测词: {', '.join(item.get('term') for item in matched_terms[:4] if item.get('term'))}"
        ] if matched_terms else [],
        "risk_breakdown": {
            "total": int(detail.get("riskScore") or 0),
            "segments": [
                {"key": "matching", "label": "匹配度", "score": int(detail.get("confidenceScore") or 0), "max_score": 100, "reasons": []},
            ],
        },
        "rule_risk_breakdown": {},
        "monitoring_matches": matched_terms,
        "monitoring_weight": int(sum(int(item.get("weight") or 0) for item in matched_terms if isinstance(item, dict))),
        "monitoring_priority": "high" if int(detail.get("riskScore") or 0) >= 75 else "medium" if int(detail.get("riskScore") or 0) >= 45 else "low",
        "sample_links": [{"url": detail.get("canonicalUrl") or "", "kind": "document"}] if detail.get("canonicalUrl") else [],
        "has_sample_evidence": bool(detail.get("evidenceCount")),
        "sample_link_count": 1 if detail.get("canonicalUrl") else 0,
        "leak_type": "公开文件暴露",
        "severity": detail.get("severity") or "low",
        "confidence_score": int(detail.get("confidenceScore") or 0),
        "completeness_score": min(100, 30 + int(detail.get("evidenceCount") or 0) * 10 + int(detail.get("fileCount") or 0) * 5),
        "country_source": "unknown",
        "industry_source": "unknown",
        "tag_sources": [],
        "entity_link_evidence": {},
        "summary": snapshot.get("previewText") or "",
        "reviews": detail.get("reviews") or [],
        "access_state": detail.get("accessState") or "unknown",
        "review_status": detail.get("reviewStatus") or "new",
    }
