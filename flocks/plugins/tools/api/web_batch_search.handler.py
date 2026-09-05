"""Batch public web threat-intelligence search handler.

Builds two natural-language threat-intel queries from the input keywords —
one Chinese, one English — and runs each through the Exa-backed `websearch`
tool. Exa is a semantic search engine, so two well-formed descriptive queries
replace the old keyword x suffix fan-out. Results from both queries are
merged and deduplicated by URL, then returned for web-search-agent to filter.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from flocks.tool.registry import ToolContext, ToolRegistry, ToolResult

WEB_TOOL_NAME = "websearch"
_CJK_RE = re.compile(r"[㐀-鿿]")

# Max keywords injected into one query prompt. Beyond this, near-synonym
# keywords only blur the semantic query; fewer is fine if a group is smaller.
MAX_KEYWORDS_PER_QUERY = 8
# Results requested per query (Chinese + English -> ~50 candidates per task).
NUM_RESULTS_PER_QUERY = 25
# Default recency window (days) for Exa's publish-date filter, used only when
# the caller omits window_days. web-search-agent normally passes the task's
# search_window_days through, so this default is just a safety net.
DEFAULT_WINDOW_DAYS = 30

# Substrings (case-insensitive) marking a websearch error as transient and
# worth retrying.
_TRANSIENT_ERROR_PATTERNS: Tuple[str, ...] = (
    "timeout",
    "timed out",
    "connection",
    "clienterror",
    "503",
    "502",
    "504",
)
_RETRY_BACKOFFS: Tuple[float, ...] = (0.5, 1.0)  # sleeps before attempt 2 and 3

# Domain substrings (case-insensitive) matched against each result's URL. Any
# match drops the result before it is returned to web-search-agent. Two kinds:
#   1. politically / socially sensitive sources that trip the LLM provider's
#      output content filter (mainland-China-blocked outlets);
#   2. low-value SEO / content-farm aggregators with no original reporting.
WEB_BLOCKED_DOMAIN_PATTERNS: Tuple[str, ...] = (
    # sensitive — 大纪元 / Epoch Times (blocked in mainland China; observed to
    # trigger MiniMax output moderation "new_sensitive 1027")
    "epochtimes",
    "d2n738oon34np4.cloudfront.net",  # Epoch Times CloudFront mirror
    # low-value SEO / content-farm aggregators (extend as needed)
    "undercodenews.com",
    "gblock.app",
)
_WEB_BLOCKED_DOMAINS_LC: Tuple[str, ...] = tuple(
    p.lower() for p in WEB_BLOCKED_DOMAIN_PATTERNS
)


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


def _coerce_window_days(value: Any) -> int:
    """Recency window in days for Exa's publish-date filter. Missing/invalid
    falls back to DEFAULT_WINDOW_DAYS; a value <= 0 means 'no date filter'."""
    if value is None:
        return DEFAULT_WINDOW_DAYS
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS


def _partition_keywords(
    keywords: List[Any],
) -> Tuple[List[str], List[str], List[str]]:
    """Split keywords into (chinese, english, skipped), each deduplicated.

    CJK ideographs -> chinese, pure ASCII -> english, anything else (Cyrillic,
    Arabic-Persian, ...) -> skipped: Exa coverage for those is weak and only
    two queries are issued. Order is preserved.
    """
    zh: List[str] = []
    en: List[str] = []
    skipped: List[str] = []
    seen: set = set()
    for raw in keywords or []:
        kw = _coerce_keyword(raw)
        if not kw:
            continue
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        if _CJK_RE.search(kw):
            zh.append(kw)
        elif kw.isascii():
            en.append(kw)
        else:
            skipped.append(kw)
    return zh, en, skipped


def _cn_prompt(keywords: List[str]) -> str:
    joined = "、".join(keywords[:MAX_KEYWORDS_PER_QUERY])
    return f"请帮我查询 {joined} 相关的攻击事件、勒索事件、泄露事件、安全通告"


def _en_prompt(keywords: List[str]) -> str:
    joined = ", ".join(keywords[:MAX_KEYWORDS_PER_QUERY])
    return (
        "Please search for attack incidents, ransomware incidents, data "
        f"breach incidents and security advisories related to {joined}"
    )


def _map_item(item: Dict[str, Any], query_lang: str) -> Dict[str, Any]:
    """Normalize one websearch result dict into the common result schema."""
    summary = (
        item.get("snippet")
        or item.get("summary")
        or item.get("text")
        or ""
    )
    if isinstance(summary, str) and len(summary) > 400:
        summary = summary[:400] + "..."
    url = item.get("url") or item.get("link") or ""
    return {
        "source": "web",
        "keyword": query_lang,
        "title": item.get("title") or "",
        "url": url,
        "time": item.get("publishedDate") or item.get("date") or item.get("published") or "",
        "summary": summary,
        "evidence": "",
        "confidence": "medium" if url else "low",
        "raw": {},
    }


def _is_transient_error(message: Optional[str]) -> bool:
    """Return True when the message looks like a recoverable network blip."""
    if not message:
        return False
    lower = str(message).lower()
    return any(p in lower for p in _TRANSIENT_ERROR_PATTERNS)


def _is_blocked_domain(url: str) -> bool:
    """True if the URL matches any blocked-domain substring. Matched results
    are dropped before reaching the agent — covers sources that trip the LLM
    provider's content filter or carry no original threat-intel value."""
    if not url:
        return False
    low = url.lower()
    return any(p and p in low for p in _WEB_BLOCKED_DOMAINS_LC)


def _extract_items(output: Any) -> List[Any]:
    """Pull the result list out of a websearch ToolResult output.

    ToolRegistry.execute serializes a tool's output for transport, so the
    websearch tool's list-of-dicts arrives here as a JSON string. Accept the
    string (parse it), an already-parsed list, or a dict carrying a `results`
    list — and fall back to an empty list for anything unrecognized.
    """
    if isinstance(output, str):
        text = output.strip()
        if not text:
            return []
        try:
            output = json.loads(text)
        except (ValueError, TypeError):
            return []
    if isinstance(output, list):
        return output
    if isinstance(output, dict):
        results = output.get("results")
        return results if isinstance(results, list) else []
    return []


async def _query_with_retry(
    ctx: ToolContext, query: str, start_date: str
) -> Tuple[Optional[ToolResult], Optional[str]]:
    """Call websearch with exponential-backoff retries on transient errors.

    Returns (tool_result_or_None, error_message_or_None). Non-transient tool
    errors short-circuit and skip the remaining retries.
    """
    attempts = len(_RETRY_BACKOFFS) + 1
    last_result: Optional[ToolResult] = None
    last_err: Optional[str] = None
    for attempt in range(attempts):
        try:
            last_result = await ToolRegistry.execute(
                WEB_TOOL_NAME,
                ctx,
                query=query,
                numResults=NUM_RESULTS_PER_QUERY,
                startPublishedDate=start_date,
            )
            if last_result.success:
                return last_result, None
            last_err = last_result.error or "unknown tool error"
            if not _is_transient_error(last_err):
                return last_result, f"query={query[:60]!r} tool error: {last_err}"
        except Exception as exc:
            last_result = None
            last_err = f"invocation error: {exc}"
        if attempt < attempts - 1:
            await asyncio.sleep(_RETRY_BACKOFFS[attempt])
    return last_result, f"query={query[:60]!r} {last_err} (after {attempts} attempts)"


async def handle(
    ctx: ToolContext, keywords: List[Any] = None, window_days: Any = None,
    **_: Any
) -> ToolResult:
    zh, en, skipped = _partition_keywords(keywords or [])
    window = _coerce_window_days(window_days)

    notes: List[str] = []
    if skipped:
        notes.append(
            f"skipped {len(skipped)} keyword(s) outside Chinese/English "
            f"coverage: {skipped[:8]}" + ("..." if len(skipped) > 8 else "")
        )

    # One Chinese + one English semantic query (whichever language has
    # keywords). Exa matches by meaning, so no keyword fan-out is needed.
    plan: List[Tuple[str, str]] = []  # (query_lang, prompt)
    if zh:
        plan.append(("zh", _cn_prompt(zh)))
    if en:
        plan.append(("en", _en_prompt(en)))

    if not plan:
        return ToolResult(success=True, output={
            "source": "web",
            "status": "completed",
            "query": {"keywords": []},
            "results": [],
            "source_coverage": {"web": "completed"},
            "errors": [],
            "notes": notes or ["no Chinese/English keywords to search"],
        })

    # window <= 0 means "no recency filter": fall back to a 10-year window so
    # the call still sends a valid startPublishedDate (Exa expects one).
    effective_days = window if window > 0 else 3650
    start_date = (
        datetime.now(timezone.utc) - timedelta(days=effective_days)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    notes.append(
        f"Exa publish-date window: {window} day(s)"
        if window > 0
        else "Exa publish-date window: none (window_days <= 0)"
    )

    task_results = await asyncio.gather(
        *(_query_with_retry(ctx, prompt, start_date) for _, prompt in plan)
    )

    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen_urls: set = set()
    success_count = 0
    blocked_filtered = 0

    for (query_lang, _prompt), (tool_result, err_msg) in zip(plan, task_results):
        if err_msg:
            errors.append(err_msg)
        if tool_result is None or not tool_result.success:
            continue
        success_count += 1
        items = _extract_items(tool_result.output)
        for item in items:
            if not isinstance(item, dict):
                continue
            mapped = _map_item(item, query_lang)
            url = mapped.get("url") or ""
            if not url or url in seen_urls:
                continue
            if _is_blocked_domain(url):
                blocked_filtered += 1
                continue
            seen_urls.add(url)
            results.append(mapped)

    if blocked_filtered:
        notes.append(
            f"dropped {blocked_filtered} result(s) from blocked domains "
            f"(patterns: {len(WEB_BLOCKED_DOMAIN_PATTERNS)})"
        )

    if success_count == 0:
        status = "failed"
    elif success_count < len(plan):
        status = "partial"
    else:
        status = "completed"

    return ToolResult(success=True, output={
        "source": "web",
        "status": status,
        "query": {"keywords": zh + en},
        "results": results,
        "source_coverage": {"web": status},
        "errors": errors,
        "notes": notes,
    })
