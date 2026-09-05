"""Batch Telegram threat-intelligence search handler.

Routes one global search per keyword through the resident tg-search MCP server.
That server is the sole owner of the Telethon session, avoiding cross-process
SQLite/session conflicts while this handler preserves the workflow's existing
batch input and normalized output schema. Results are deduplicated by
(chat.id, message_id) and filtered for known noise chats and message text.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from flocks.tool.registry import ToolContext, ToolResult

DEFAULT_MCP_URL = "http://127.0.0.1:3333/mcp"
MCP_URL_ENV = "FLOCKS_TG_MCP_URL"
PER_KEYWORD_LIMIT = 100
CONNECT_TIMEOUT_S = 20.0
CALL_TIMEOUT_S = 120.0

# Serialize batch calls from this Flocks process. The resident MCP server owns
# the only Telethon client and session file.
_search_lock = asyncio.Lock()

# Substring patterns (case-insensitive) matched against chat.title and
# chat.username. Any match means the chat is noise and its messages are
# dropped. Each entry is a literal title fragment (the `|` characters are
# part of the actual chat names — they are NOT regex separators).
TELEGRAM_NOISE_CHAT_PATTERNS: Tuple[str, ...] = (
    "中文导航|搜索|汉化|吃瓜|万物搜",
    "中文群组|中文频道|电报导航群",
    "白嫖推送",
    "日月社工库交流群",
    "RYSGKCHAT",
    "社工库",
    "一诺社工",
)
_NOISE_PATTERNS_LC: Tuple[str, ...] = tuple(p.lower() for p in TELEGRAM_NOISE_CHAT_PATTERNS)

# Substring patterns (case-insensitive) matched against the message text
# itself. Any match means the message is dropped regardless of which chat it
# came from — this catches content-level noise even in chats with
# otherwise-normal names. Kept separate from TELEGRAM_NOISE_CHAT_PATTERNS
# because matching message bodies is broader and more prone to false
# positives than matching chat names.
TELEGRAM_NOISE_TEXT_PATTERNS: Tuple[str, ...] = (
    "社工库",
)
_NOISE_TEXT_PATTERNS_LC: Tuple[str, ...] = tuple(
    p.lower() for p in TELEGRAM_NOISE_TEXT_PATTERNS
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


def _coerce_window(value: Any) -> Optional[int]:
    """Return a positive day count, or None when no time filter should apply."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def _dedup_key(record: Dict[str, Any]) -> Tuple[Any, Any]:
    chat = record.get("chat") if isinstance(record.get("chat"), dict) else {}
    return (chat.get("id"), record.get("message_id"))


def _is_noise_chat(record: Dict[str, Any]) -> bool:
    """True if the record's chat title or @username contains any noise
    pattern. Matched chats are filtered out so the agent never sees them."""
    chat = record.get("chat") if isinstance(record.get("chat"), dict) else {}
    title = (chat.get("title") or "").lower()
    username = (chat.get("username") or "").lower()
    if not title and not username:
        return False
    for pattern in _NOISE_PATTERNS_LC:
        if pattern and (pattern in title or pattern in username):
            return True
    return False


def _is_noise_text(record: Dict[str, Any]) -> bool:
    """True if the record's message text contains any noise keyword. Matched
    messages are filtered out so the agent never sees them — this catches
    content-level noise even in chats with otherwise-normal names."""
    text = (record.get("text") or "").lower()
    if not text:
        return False
    for pattern in _NOISE_TEXT_PATTERNS_LC:
        if pattern and pattern in text:
            return True
    return False


def _map_record(record: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    chat = record.get("chat") if isinstance(record.get("chat"), dict) else {}
    sender = record.get("sender") if isinstance(record.get("sender"), dict) else {}

    title = chat.get("title") or chat.get("username") or ""
    url = record.get("link") or ""
    time_value = record.get("date") or ""
    text = record.get("text") or ""
    summary = (text[:300] + "...") if len(text) > 300 else text

    evidence_parts: List[str] = []
    if sender.get("name") or sender.get("username"):
        evidence_parts.append(
            f"from={sender.get('name') or sender.get('username')}"
        )
    if record.get("views"):
        evidence_parts.append(f"views={record['views']}")
    if record.get("forwards"):
        evidence_parts.append(f"forwards={record['forwards']}")
    if record.get("media_type"):
        evidence_parts.append(f"media={record['media_type']}")

    return {
        "source": "telegram",
        "keyword": keyword,
        "title": title,
        "url": url,
        "time": time_value,
        "summary": summary,
        "evidence": "; ".join(evidence_parts),
        "confidence": "medium" if url else "low",
        "raw": {},
    }


# ------------------------------- MCP layer -------------------------------


def _extract_mcp_records(result: Any) -> List[Dict[str, Any]]:
    if bool(getattr(result, "isError", False)):
        messages = [
            str(getattr(block, "text", "")).strip()
            for block in getattr(result, "content", None) or []
            if getattr(block, "text", None)
        ]
        detail = messages[0][:500] if messages else "unknown tool error"
        raise RuntimeError(f"tg-search MCP returned a tool error: {detail}")

    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and isinstance(structured.get("result"), list):
        return structured["result"]
    if isinstance(structured, list):
        return structured

    fallback_records: List[Dict[str, Any]] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("result"), list):
            return payload["result"]
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            fallback_records.append(payload)

    if fallback_records:
        return fallback_records

    raise ValueError("tg-search MCP response did not contain a result list")


async def _search_keyword(
    session: ClientSession, keyword: str, cutoff: Optional[datetime]
) -> List[Dict[str, Any]]:
    arguments: Dict[str, Any] = {
        "query": keyword,
        "limit": PER_KEYWORD_LIMIT,
        "use_default_excludes": False,
    }
    if cutoff is not None:
        arguments["min_date"] = cutoff.isoformat()
    result = await asyncio.wait_for(
        session.call_tool("search_global", arguments=arguments),
        timeout=CALL_TIMEOUT_S,
    )
    return _extract_mcp_records(result)


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
            "source": "telegram",
            "status": "completed",
            "query": {"keywords": []},
            "results": [],
            "source_coverage": {"telegram": "completed"},
            "errors": [],
            "notes": ["empty keywords list"],
        })

    def _failed(errs: List[str], nts: List[str]) -> ToolResult:
        return ToolResult(success=True, output={
            "source": "telegram",
            "status": "failed",
            "query": {"keywords": keyword_list},
            "results": [],
            "source_coverage": {"telegram": "failed"},
            "errors": errs,
            "notes": nts,
        })

    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    notes: List[str] = []
    seen_keys: set = set()
    success_count = 0
    flood_wait = False
    noise_filtered = 0
    text_filtered = 0

    window = _coerce_window(search_window_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=window) if window is not None else None
    mcp_url = os.environ.get(MCP_URL_ENV, "").strip() or DEFAULT_MCP_URL

    async with _search_lock:
        try:
            timeout = httpx.Timeout(CONNECT_TIMEOUT_S, read=None)
            async with httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
            ) as http_client:
                async with streamable_http_client(
                    mcp_url,
                    http_client=http_client,
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await asyncio.wait_for(
                            session.initialize(),
                            timeout=CONNECT_TIMEOUT_S,
                        )
                        for keyword in keyword_list:
                            try:
                                records = await _search_keyword(
                                    session,
                                    keyword,
                                    cutoff,
                                )
                            except Exception as exc:
                                errors.append(
                                    f"keyword={keyword!r} search error: {exc}"
                                )
                                break

                            if (
                                records
                                and isinstance(records[0], dict)
                                and records[0].get("error") == "flood_wait"
                            ):
                                flood_wait = True
                                errors.append(
                                    f"keyword={keyword!r} flood_wait retry_after_seconds="
                                    f"{records[0].get('retry_after_seconds')}"
                                )
                                notes.append(
                                    "flood_wait encountered — remaining keywords not searched"
                                )
                                break

                            success_count += 1
                            for record in records:
                                if not isinstance(record, dict):
                                    continue
                                if "error" in record:
                                    errors.append(
                                        f"keyword={keyword!r} record error: "
                                        f"{record.get('error')}: {record.get('message', '')}"
                                    )
                                    continue
                                if not record.get("date"):
                                    continue
                                if _is_noise_chat(record):
                                    noise_filtered += 1
                                    continue
                                if _is_noise_text(record):
                                    text_filtered += 1
                                    continue
                                key = _dedup_key(record)
                                if key in seen_keys:
                                    continue
                                seen_keys.add(key)
                                results.append(_map_record(record, keyword))
        except Exception as exc:
            if success_count == 0:
                return _failed(
                    [f"连接 tg-search MCP 失败: {exc}"],
                    [
                        "请确认常驻 tg-search 服务正在监听 "
                        f"{mcp_url}，且 Telegram session 已授权。"
                    ],
                )
            errors.append(f"tg-search MCP connection error: {exc}")

    if window is not None:
        notes.append(
            f"applied search_window_days={window} via tg-search MCP min_date"
        )
    if noise_filtered:
        notes.append(
            f"filtered {noise_filtered} messages from noise chats "
            f"(patterns: {len(TELEGRAM_NOISE_CHAT_PATTERNS)})"
        )
    if text_filtered:
        notes.append(
            f"filtered {text_filtered} messages by noise keyword "
            f"(patterns: {len(TELEGRAM_NOISE_TEXT_PATTERNS)})"
        )

    if flood_wait:
        status = "partial" if results or success_count else "failed"
    elif success_count == 0:
        status = "failed"
    elif success_count < len(keyword_list):
        status = "partial"
    else:
        status = "completed"

    return ToolResult(success=True, output={
        "source": "telegram",
        "status": status,
        "query": {"keywords": keyword_list},
        "results": results,
        "source_coverage": {"telegram": status},
        "errors": errors,
        "notes": notes,
    })
