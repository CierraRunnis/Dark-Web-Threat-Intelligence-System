from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

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


logger = logging.getLogger("darkweb_collector.code_monitoring_notifications")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _primary_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in hits
        if isinstance(item, dict)
        and not bool(item.get("suppressed"))
        and _normalize_text(item.get("displayBucket") or "primary") == "primary"
        and _normalize_text(item.get("resultLayer")).lower() == "sensitive"
        and _normalize_text(item.get("sensitiveType")).lower() != "clue"
    ]


def build_code_monitoring_markdown(hit: dict[str, Any]) -> str:
    repository = _normalize_text(hit.get("repositoryFullName") or hit.get("repositoryName")) or "未知"
    severity_labels = {"high": "高危", "medium": "中危", "low": "低危"}
    severity = _normalize_text(hit.get("severity")).lower()
    risk_label = severity_labels.get(severity, severity or "未知")
    lines = [
        "### 代码泄露监测通知",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- 监测对象：{_normalize_text(hit.get('watchlistName') or hit.get('organizationName')) or '未知'}",
        f"- 仓库名称：{repository}",
        f"- 来源平台：{_normalize_text(hit.get('platformLabel') or hit.get('platform')) or '未知'}",
        f"- 文件路径：{_normalize_text(hit.get('filePath')) or '未知'}",
        f"- 敏感类型：{_normalize_text(hit.get('sensitiveLabel') or hit.get('sensitiveType')) or '未知'}",
        f"- 检索命中词：{_normalize_text(hit.get('matchedTerm')) or '未知'}",
        f"- 命中层级：{_normalize_text(hit.get('resultLayerLabel') or hit.get('resultLayer')) or '未知'}",
        f"- 风险级别：{risk_label}（{int(hit.get('riskScore') or 0)} 分）",
        f"- 发现时间：{_normalize_text(hit.get('firstSeenAt')) or '未知'}",
    ]
    file_url = _normalize_text(hit.get("fileUrl"))
    if file_url:
        lines.append(f"- 来源链接：{file_url}")
    return "\n".join(lines)


def _wechat_ready(config: BotConfig) -> bool:
    status = bot_config_status(config)
    if not status.get("configured"):
        return False
    if config.provider == BOT_PROVIDER_WECHAT_WORK_AIBOT:
        return bool(config.chat_ids or config.chat_id)
    return True


def notify_code_monitoring_hits(
    hits: list[dict[str, Any]],
    *,
    wechat_config: BotConfig | None = None,
    dingtalk_config: DingTalkConfig | None = None,
) -> dict[str, Any]:
    eligible_hits = _primary_hits(hits)
    config_errors: list[dict[str, Any]] = []
    resolved_wechat: BotConfig | None = wechat_config
    resolved_dingtalk: DingTalkConfig | None = dingtalk_config
    if resolved_wechat is None:
        try:
            resolved_wechat = load_bot_config()
        except Exception as exc:
            config_errors.append({"channel": "wechat_work", "error": str(exc)})
    if resolved_dingtalk is None:
        try:
            resolved_dingtalk = load_dingtalk_config()
        except Exception as exc:
            config_errors.append({"channel": "dingtalk", "error": str(exc)})
    channel_ready = {
        "wechat_work": bool(resolved_wechat and _wechat_ready(resolved_wechat)),
        "dingtalk": bool(resolved_dingtalk and dingtalk_config_status(resolved_dingtalk).get("configured")),
    }
    result: dict[str, Any] = {
        "eligible": len(eligible_hits),
        "sent": 0,
        "failed": len(config_errors),
        "skipped": 0,
        "channels": channel_ready,
        "errors": config_errors,
    }
    if not eligible_hits:
        return result
    if not any(channel_ready.values()):
        result["skipped"] = len(eligible_hits)
        return result

    for hit in eligible_hits:
        content = build_code_monitoring_markdown(hit)
        if channel_ready["wechat_work"]:
            try:
                post_bot_payload(build_markdown_payload(content), resolved_wechat)
                result["sent"] += 1
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append({"channel": "wechat_work", "hit_id": hit.get("id"), "error": str(exc)})
                logger.exception("failed to send code monitoring hit to WeCom")
        if channel_ready["dingtalk"]:
            try:
                post_dingtalk_markdown(content, resolved_dingtalk, title="代码泄露监测通知")
                result["sent"] += 1
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append({"channel": "dingtalk", "hit_id": hit.get("id"), "error": str(exc)})
                logger.exception("failed to send code monitoring hit to DingTalk")
    return result
