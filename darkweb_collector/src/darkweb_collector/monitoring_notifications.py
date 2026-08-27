from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
import os
from typing import Any

import darkweb_collector.monitoring_rules as monitoring_rules
from darkweb_collector.bot_assistant import (
    BOT_PROVIDER_WECHAT_WORK_AIBOT,
    BotConfig,
    bot_config_status,
    build_markdown_payload,
    load_bot_config,
    post_bot_payload,
)
from darkweb_collector.dingtalk_bot import (
    DingTalkConfig,
    dingtalk_config_status,
    load_dingtalk_config,
    post_dingtalk_markdown,
)
from darkweb_collector.detail_i18n import (
    translate_event_detail_text_live,
    translate_event_title_live,
)
from darkweb_collector.db import (
    get_monitoring_keyword_notification,
    get_monitoring_keyword_notification_by_event_key,
    upsert_monitoring_keyword_notification,
)


NOTIFICATION_ENABLED_ENV = "DARKWEB_MONITORING_KEYWORD_BOT_ENABLED"
NOTIFICATION_LOOKBACK_DAYS = 7
CHANNEL_WECHAT_WORK = "wechat_work"
CHANNEL_DINGTALK = "dingtalk"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _notifications_enabled() -> bool:
    return _normalize_text(os.environ.get(NOTIFICATION_ENABLED_ENV)).lower() not in {"0", "false", "no", "off"}


def _match_entries(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for item in matches:
        keyword = _normalize_text(item.get("keyword"))
        if not keyword:
            continue
        entries.append(
            {
                "keyword": keyword,
                "category": _normalize_text(item.get("category")) or "custom_keywords",
                "weight": int(item.get("weight") or 0),
                "match_count": int(item.get("match_count") or 0),
            }
        )
    entries.sort(key=lambda item: (item["category"].lower(), item["keyword"].lower()))
    return entries


def keyword_match_signature(matches: list[dict[str, Any]]) -> str:
    payload = [
        {
            "keyword": item["keyword"],
            "category": item["category"],
        }
        for item in _match_entries(matches)
    ]
    return sha1(_json_dumps(payload).encode("utf-8")).hexdigest()


def _parse_datetime_value(value: Any) -> datetime | None:
    text = _normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _event_disclosure_datetime(event: dict[str, Any]) -> datetime | None:
    metadata = event.get("metadata") or {}
    for value in (
        event.get("disclosure_time"),
        metadata.get("published_label"),
    ):
        parsed = _parse_datetime_value(value)
        if parsed is not None:
            return parsed
    return None


def _event_is_recent(event: dict[str, Any], *, lookback_days: int = NOTIFICATION_LOOKBACK_DAYS) -> bool:
    disclosed_at = _event_disclosure_datetime(event)
    if disclosed_at is None:
        return False
    now = datetime.now(timezone.utc)
    if disclosed_at > now + timedelta(days=1):
        return False
    return disclosed_at >= now - timedelta(days=lookback_days)


def _notification_event_key(event: dict[str, Any]) -> str:
    source_url = _normalize_text(event.get("source_url")).rstrip("/").lower()
    if source_url:
        return f"url:{source_url}"
    disclosed_at = _event_disclosure_datetime(event)
    payload = {
        "source_site_name": _normalize_text(event.get("source_site_name")).lower(),
        "event_type": _normalize_text(event.get("event_type")).lower(),
        "title": _normalize_text(event.get("title")).lower(),
        "victim": _normalize_text(event.get("victim")).lower(),
        "attacker": _normalize_text(event.get("attacker")).lower(),
        "disclosure_date": disclosed_at.strftime("%Y-%m-%d") if disclosed_at else "",
    }
    return f"fingerprint:{sha1(_json_dumps(payload).encode('utf-8')).hexdigest()}"


def _backfill_notification_event_keys(connection, events: list[dict[str, Any]]) -> None:
    rows = []
    for event in events:
        event_id = _normalize_text(event.get("event_id"))
        event_key = _notification_event_key(event)
        if not event_id or not event_key:
            continue
        rows.append((event_key, event_id))
    if not rows:
        return
    connection.executemany(
        """
        UPDATE monitoring_keyword_notifications
        SET event_key = ?
        WHERE event_id = ? AND ifnull(event_key, '') = ''
        """,
        rows,
    )


def _channel_match_signature(match_signature: str, channel: str) -> str:
    return f"{match_signature}:{channel}"


def _channel_event_key(event: dict[str, Any], channel: str) -> str:
    return f"{_notification_event_key(event)}|channel:{channel}"


def _notification_already_sent(
    connection,
    event: dict[str, Any],
    event_id: str,
    match_signature: str,
    channel: str,
) -> bool:
    row = get_monitoring_keyword_notification(
        connection,
        event_id,
        _channel_match_signature(match_signature, channel),
    )
    if row is not None and row.get("status") == "sent" and not bool(row.get("dry_run")):
        return True
    event_key = _channel_event_key(event, channel)
    if not event_key:
        return False
    if get_monitoring_keyword_notification_by_event_key(connection, event_key) is not None:
        return True
    if channel != CHANNEL_WECHAT_WORK:
        return False
    legacy = get_monitoring_keyword_notification(connection, event_id, match_signature)
    if legacy is not None and legacy.get("status") == "sent" and not bool(legacy.get("dry_run")):
        return True
    return get_monitoring_keyword_notification_by_event_key(connection, _notification_event_key(event)) is not None


def _display_value(value: Any, default: str = "未知") -> str:
    return _normalize_text(value) or default


def _truncate_text(value: Any, limit: int = 180) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _format_date_value(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-" and text[:10].replace("-", "").isdigit():
        return text[:10]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        pass
    for fmt in (
        "%d %b %Y",
        "%d %B %Y",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def _display_source(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") or {}
    return _display_value(metadata.get("source_label") or event.get("source_site_name"))


def _display_disclosure_date(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") or {}
    for value in (
        metadata.get("published_label"),
        event.get("disclosure_time"),
        metadata.get("updated_time"),
    ):
        formatted = _format_date_value(value)
        if formatted:
            return formatted
    return "未知"


def _display_title(event: dict[str, Any]) -> str:
    raw_title = _normalize_text(event.get("title"))
    fallback = raw_title or _normalize_text(event.get("victim")) or _normalize_text(event.get("event_id"))
    if not fallback:
        return "未命名事件"
    translated = translate_event_title_live(raw_title, fallback=fallback) if raw_title else fallback
    return _truncate_text(translated, limit=120)


def _summary_candidate_text(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") or {}
    for value in (
        metadata.get("summary"),
        event.get("detail_text"),
        metadata.get("original_summary"),
        event.get("title"),
    ):
        text = _normalize_text(value)
        if text:
            return text
    return ""


def _looks_like_disclosure_content(text: str) -> bool:
    lowered = text.lower()
    hint_tokens = (
        "credential",
        "credentials",
        "account",
        "password",
        "cookie",
        "mfa",
        "database",
        "records",
        "record",
        "dump",
        "sql",
        "source code",
        "repository",
        "repo",
        "github",
        "gitlab",
        "document",
        "documents",
        "file",
        "files",
        "contract",
        "invoice",
        "internal",
        "passport",
        "email",
        "phone",
        "kyc",
        "pii",
        "bank",
        "finance",
        "payment",
        "credit card",
        "sample",
        "proof",
        "preview",
        "凭证",
        "账号",
        "密码",
        "数据库",
        "记录",
        "数据表",
        "源码",
        "源代码",
        "文档",
        "文件",
        "合同",
        "发票",
        "护照",
        "邮箱",
        "手机",
        "个人信息",
        "金融",
        "支付",
        "样本",
    )
    return any(token in lowered or token in text for token in hint_tokens)


def _content_label(event: dict[str, Any]) -> str:
    text = " ".join(
        part
        for part in (
            _normalize_text(event.get("leak_type")),
            _normalize_text(event.get("category")),
            _summary_candidate_text(event),
        )
        if part
    )
    lowered = text.lower()
    label_map = (
        (("credential", "credentials", "account", "password", "cookie", "mfa", "凭证", "账号", "密码"), "账号凭证"),
        (("database", "records", "record", "dump", "sql", "数据库", "记录", "数据表"), "数据库记录"),
        (("source code", "repository", "repo", "github", "gitlab", "源码", "源代码"), "源码文件"),
        (("document", "documents", "file", "files", "contract", "invoice", "文档", "文件", "合同", "发票"), "文档资料"),
        (("passport", "email", "phone", "kyc", "pii", "护照", "邮箱", "手机", "个人信息"), "个人信息"),
        (("bank", "finance", "payment", "credit card", "金融", "支付", "银行卡"), "金融数据"),
    )
    for tokens, label in label_map:
        if any(token in lowered or token in text for token in tokens):
            return label
    if "sale" in lowered or "sell" in lowered or any(token in text for token in ("售卖", "出售", "交易")):
        return "待售数据"
    return "相关数据"


def _content_excerpt(event: dict[str, Any]) -> str:
    detail_text = _summary_candidate_text(event)
    if not detail_text or not _looks_like_disclosure_content(detail_text):
        return ""
    translated_detail = translate_event_detail_text_live(_truncate_text(detail_text, limit=220))
    return _truncate_text(translated_detail.rstrip("。；;，,"), limit=90)


def _build_event_summary(event: dict[str, Any]) -> str:
    event_type = _normalize_text(event.get("event_type"))
    victim = _display_value(event.get("victim"))
    attacker = _normalize_text(event.get("attacker"))
    source = _display_source(event)
    subject = attacker or source
    content_label = _content_label(event)
    content_excerpt = _content_excerpt(event)

    if event_type == "vulnerability":
        summary = f"公开源披露 { _display_title(event) }，影响 {victim}"
        if attacker:
            summary += f"，相关厂商为 {attacker}"
        if content_excerpt:
            summary += f"，摘要：{content_excerpt}"
        return f"{summary}。"

    if event_type == "ransomware":
        summary = f"{subject} 披露 {victim} 遭勒索，疑似泄露{content_label}"
    else:
        summary = f"{subject} 披露 {victim} 疑似泄露{content_label}"

    if content_excerpt:
        return f"{summary}，披露内容涉及 {content_excerpt}。"
    return f"{summary}，具体内容待进一步核实。"


def build_keyword_match_markdown(event: dict[str, Any]) -> str:
    title = _display_title(event)
    lines = [
        "### 监控关键词命中通知",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- 事件标题：{title}",
        f"- 情报来源：{_display_source(event)}",
        f"- 受害对象：{_display_value(event.get('victim'))}",
        f"- 攻击者/关联主体：{_display_value(event.get('attacker'))}",
        f"- 披露时间：{_display_disclosure_date(event)}",
        f"- 事件摘要：{_build_event_summary(event)}",
    ]
    source_url = _normalize_text(event.get("source_url"))
    if source_url:
        lines.append(f"- 来源链接：{source_url}")
    return "\n".join(lines)


def _record_notification_result(
    connection,
    *,
    event: dict[str, Any],
    match_signature: str,
    channel: str,
    matches: list[dict[str, Any]],
    status: str,
    dry_run: bool,
    response: Any = None,
    error_message: str = "",
) -> None:
    now = _now_utc_iso()
    upsert_monitoring_keyword_notification(
        connection,
        {
            "event_id": _normalize_text(event.get("event_id")),
            "event_key": _channel_event_key(event, channel),
            "match_signature": _channel_match_signature(match_signature, channel),
            "match_keywords_json": _json_dumps(matches),
            "status": status,
            "dry_run": dry_run,
            "response_json": _json_dumps({"channel": channel, "result": response or {}}),
            "error_message": error_message,
            "sent_at": now if status in {"sent", "dry_run"} else None,
            "created_at": now,
            "updated_at": now,
        },
    )


def notify_keyword_matches_for_events(
    connection,
    normalized_events: list[dict[str, Any]],
    *,
    config: BotConfig | None = None,
    dingtalk_config: DingTalkConfig | None = None,
    channels: set[str] | None = None,
) -> dict[str, Any]:
    if not _notifications_enabled():
        return {
            "enabled": False,
            "matched": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "dry_run": 0,
            "outside_window": 0,
        }

    requested_channels = channels or {CHANNEL_WECHAT_WORK, CHANNEL_DINGTALK}
    config_errors: list[dict[str, Any]] = []
    resolved_wechat: BotConfig | None = config
    resolved_dingtalk: DingTalkConfig | None = dingtalk_config
    if CHANNEL_WECHAT_WORK in requested_channels and resolved_wechat is None:
        try:
            resolved_wechat = load_bot_config()
        except Exception as exc:
            config_errors.append({"channel": CHANNEL_WECHAT_WORK, "error": str(exc)})
    if CHANNEL_DINGTALK in requested_channels and resolved_dingtalk is None:
        try:
            resolved_dingtalk = load_dingtalk_config()
        except Exception as exc:
            config_errors.append({"channel": CHANNEL_DINGTALK, "error": str(exc)})

    wechat_status = bot_config_status(resolved_wechat) if resolved_wechat else {"configured": False}
    dingtalk_status = dingtalk_config_status(resolved_dingtalk) if resolved_dingtalk else {"configured": False}
    wechat_ready = bool(
        resolved_wechat
        and (wechat_status.get("configured") or resolved_wechat.dry_run)
        and (
            resolved_wechat.provider != BOT_PROVIDER_WECHAT_WORK_AIBOT
            or resolved_wechat.dry_run
            or resolved_wechat.chat_ids
            or resolved_wechat.chat_id
        )
    )
    dingtalk_ready = bool(resolved_dingtalk and (dingtalk_status.get("configured") or resolved_dingtalk.dry_run))
    channel_ready = {
        CHANNEL_WECHAT_WORK: wechat_ready and CHANNEL_WECHAT_WORK in requested_channels,
        CHANNEL_DINGTALK: dingtalk_ready and CHANNEL_DINGTALK in requested_channels,
    }
    if not any(channel_ready.values()):
        return {
            "enabled": True,
            "configured": False,
            "matched": 0,
            "sent": 0,
            "failed": len(config_errors),
            "skipped": 0,
            "dry_run": 0,
            "outside_window": 0,
            "reason": "bot_not_configured",
            "channels": channel_ready,
            "errors": config_errors,
        }

    enriched_events = monitoring_rules.enrich_events(connection, normalized_events)
    _backfill_notification_event_keys(connection, enriched_events)
    connection.commit()
    result = {
        "enabled": True,
        "configured": any(channel_ready.values()),
        "matched": 0,
        "sent": 0,
        "failed": len(config_errors),
        "skipped": 0,
        "dry_run": 0,
        "outside_window": 0,
        "channels": channel_ready,
        "errors": config_errors,
    }
    for event in enriched_events:
        matches = _match_entries(event.get("monitoring_matches") or [])
        if not matches:
            continue
        if not _event_is_recent(event):
            result["skipped"] += 1
            result["outside_window"] += 1
            continue
        result["matched"] += 1
        event_id = _normalize_text(event.get("event_id"))
        if not event_id:
            result["skipped"] += 1
            continue
        match_signature = keyword_match_signature(matches)
        content = build_keyword_match_markdown(event)
        deliveries = (
            (CHANNEL_WECHAT_WORK, resolved_wechat),
            (CHANNEL_DINGTALK, resolved_dingtalk),
        )
        for channel, channel_config in deliveries:
            if not channel_ready[channel] or channel_config is None:
                continue
            if _notification_already_sent(connection, event, event_id, match_signature, channel):
                result["skipped"] += 1
                continue
            try:
                if channel == CHANNEL_WECHAT_WORK:
                    response = post_bot_payload(build_markdown_payload(content), channel_config)
                else:
                    response = post_dingtalk_markdown(content, channel_config, title="监控关键词命中通知")
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append({"channel": channel, "event_id": event_id, "error": str(exc)})
                _record_notification_result(
                    connection,
                    event=event,
                    match_signature=match_signature,
                    channel=channel,
                    matches=matches,
                    status="failed",
                    dry_run=False,
                    error_message=str(exc),
                )
                connection.commit()
                continue

            if bool(response.get("dry_run")):
                result["dry_run"] += 1
                stored_status = "dry_run"
            else:
                result["sent"] += 1
                stored_status = "sent"
            _record_notification_result(
                connection,
                event=event,
                match_signature=match_signature,
                channel=channel,
                matches=matches,
                status=stored_status,
                dry_run=bool(response.get("dry_run")),
                response=response,
            )
            connection.commit()
    return result
