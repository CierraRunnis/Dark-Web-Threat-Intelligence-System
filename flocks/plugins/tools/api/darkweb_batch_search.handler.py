"""Batch dark web threat-intelligence search handler.

Iterates the input keyword list, calls the local intelligence API once per
keyword with the keyword as the only business filter, then merges and
technically deduplicates events. When search_window_days is given, keeps only
events disclosed within that window (entries with an unparseable date are
dropped). Industry / region / severity filtering still belongs to
darkweb-search-agent.
"""

import asyncio
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from flocks.tool.registry import ToolContext, ToolResult

DARKWEB_API_URL = "http://127.0.0.1:8000/api/ai/intelligence"
PER_KEYWORD_LIMIT = 500
REQUEST_TIMEOUT_S = 30
MAX_TOKEN_QUERIES = 120


def _coerce_keyword(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("keyword", "term", "query", "canonical"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(item, str):
        return item.strip()
    return str(item or "").strip()


def _confidence_from_risk(score: Any) -> str:
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "low"
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _coerce_window(value: Any) -> Optional[int]:
    """Return a positive day count, or None when no time filter should apply."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def _parse_date(value: Any) -> Optional[date]:
    """Parse a date from an event time field.

    Handles 2026-05-20, 2026/5/20, 2026年5月20日, and a bare-year fallback.
    Returns a date, or None when nothing parseable is found.
    """
    text = str(value or "").strip()
    if not text:
        return None
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except ValueError:
            return None
    m = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
    if m:
        try:
            return date(int(m.group(1)), 12, 31)
        except ValueError:
            return None
    return None


def _map_event(event: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    if not isinstance(event, dict):
        event = {"value": event}

    url = (
        event.get("disclosureUrl")
        or event.get("sourceUrl")
        or event.get("url")
        or ""
    )
    time_value = (
        event.get("disclosureTime")
        or event.get("updatedTime")
        or event.get("time")
        or ""
    )
    title = (
        event.get("title")
        or event.get("victim")
        or event.get("originalTitle")
        or ""
    )
    summary = event.get("summary") or ""
    if len(summary) > 15000:
        summary = summary[:15000] + "..."
    evidence_parts: List[str] = []
    for label, key in (
        ("attacker", "attacker"),
        ("category", "category"),
        ("severity", "severity"),
        ("cve", "cveId"),
        ("industry", "industry"),
        ("country", "country"),
    ):
        value = event.get(key)
        if value:
            evidence_parts.append(f"{label}={value}")

    sample_urls: List[str] = []
    seen_sample: set = set()
    for entry in (event.get("sampleLinks") or []) + (event.get("mirrorResources") or []):
        u = entry.get("url") if isinstance(entry, dict) else entry
        if isinstance(u, str):
            u = u.strip()
        if u and u != url and u not in seen_sample:
            seen_sample.add(u)
            sample_urls.append(u)

    return {
        "source": "darkweb",
        "keyword": keyword,
        "title": title,
        "url": url,
        "time": time_value,
        "summary": summary,
        "evidence": "; ".join(evidence_parts),
        "confidence": _confidence_from_risk(event.get("riskScore")),
        "sample_urls": sample_urls,
        "raw": {},
    }


def _expand_query_tokens(keyword: str) -> List[str]:
    """Return one literal darkweb API query for the complete keyword."""
    keyword = (keyword or "").strip()
    return [keyword] if keyword else []


async def _query_one(
    session: aiohttp.ClientSession, keyword: str
) -> Tuple[List[Dict[str, Any]], str]:
    params = {"keyword": keyword, "limit": str(PER_KEYWORD_LIMIT)}
    try:
        async with session.get(DARKWEB_API_URL, params=params) as resp:
            if resp.status >= 400:
                text = await resp.text()
                return [], f"keyword={keyword!r} HTTP {resp.status}: {text[:200]}"
            data = await resp.json(content_type=None)
            if not isinstance(data, dict):
                return [], ""
            events = data.get("events")
            return (events if isinstance(events, list) else []), ""
    except asyncio.TimeoutError:
        return [], f"keyword={keyword!r} timeout after {REQUEST_TIMEOUT_S}s"
    except aiohttp.ClientError as exc:
        return [], f"keyword={keyword!r} request failed: {exc}"
    except Exception as exc:
        return [], f"keyword={keyword!r} unexpected error: {exc}"


async def handle(
    ctx: ToolContext,
    keywords: List[Any] = None,
    search_window_days: Any = None,
    **_: Any,
) -> ToolResult:
    keyword_list: List[str] = []
    for raw in keywords or []:
        kw = _coerce_keyword(raw)
        if kw and kw not in keyword_list:
            keyword_list.append(kw)

    if not keyword_list:
        return ToolResult(success=True, output={
            "source": "darkweb",
            "status": "completed",
            "query": {"keywords": []},
            "results": [],
            "source_coverage": {"darkweb": "completed"},
            "errors": [],
            "notes": ["empty keywords list"],
        })

    # Preserve each input keyword as one literal query. Whitespace is part of
    # the phrase and must not create additional API calls.
    query_plan: List[Tuple[str, str]] = []  # (display_keyword, query_token)
    seen_pairs: set = set()
    for display_kw in keyword_list:
        for token in _expand_query_tokens(display_kw):
            key = (display_kw.lower(), token.lower())
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            query_plan.append((display_kw, token))

    notes: List[str] = []
    if len(query_plan) > MAX_TOKEN_QUERIES:
        notes.append(
            f"truncated query plan from {len(query_plan)} to {MAX_TOKEN_QUERIES} API calls"
        )
        query_plan = query_plan[:MAX_TOKEN_QUERIES]

    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen_keys: set = set()
    success_count = 0

    window = _coerce_window(search_window_days)
    cutoff = date.today() - timedelta(days=window) if window is not None else None
    filtered_out = 0

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for display_kw, token in query_plan:
            events, err = await _query_one(session, token)
            if err:
                errors.append(err)
                continue
            success_count += 1
            for event in events:
                dedup_key = None
                if isinstance(event, dict):
                    dedup_key = (
                        event.get("id")
                        or event.get("disclosureUrl")
                        or event.get("sourceUrl")
                    )
                if dedup_key:
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                mapped = _map_event(event, display_kw)
                if cutoff is not None:
                    event_date = _parse_date(mapped["time"])
                    if event_date is None or event_date < cutoff:
                        filtered_out += 1
                        continue
                results.append(mapped)

    if filtered_out:
        notes.append(
            f"filtered out {filtered_out} darkweb results outside "
            f"search_window_days={window} or without a parseable date"
        )

    if success_count == 0:
        status = "failed"
    elif success_count < len(query_plan):
        status = "partial"
    else:
        status = "completed"

    return ToolResult(success=True, output={
        "source": "darkweb",
        "status": status,
        "query": {"keywords": keyword_list},
        "results": results,
        "source_coverage": {"darkweb": status},
        "errors": errors,
        "notes": notes,
    })
