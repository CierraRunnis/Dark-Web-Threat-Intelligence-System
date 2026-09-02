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
    dingtalk_configs: list[DingTalkConfig] | None = None,
    _load_default_configs: bool = True,
) -> dict[str, Any]:
    eligible_hits = _primary_hits(hits)
    if (
        _load_default_configs
        and wechat_config is None
        and dingtalk_config is None
        and dingtalk_configs is None
    ):
        from darkweb_collector.watchlist_notifications import load_watchlist_channel_configs

        aggregate: dict[str, Any] = {
            "eligible": len(eligible_hits),
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "channels": {"wechat_work": False, "dingtalk": False},
            "errors": [],
            "objects": [],
        }
        grouped: dict[int, list[dict[str, Any]]] = {}
        for hit in eligible_hits:
            watchlist_id = int(hit.get("watchlistId") or hit.get("watchlist_id") or 0)
            if watchlist_id <= 0:
                aggregate["skipped"] += 1
                continue
            grouped.setdefault(watchlist_id, []).append(hit)
        for watchlist_id, object_hits in grouped.items():
            scoped_wechat, scoped_dingtalk, _ = load_watchlist_channel_configs(watchlist_id)
            scoped = notify_code_monitoring_hits(
                object_hits,
                wechat_config=scoped_wechat,
                dingtalk_configs=scoped_dingtalk,
                _load_default_configs=False,
            )
            aggregate["objects"].append({"watchlist_id": watchlist_id, "result": scoped})
            for key in ("sent", "failed", "skipped"):
                aggregate[key] += int(scoped.get(key) or 0)
            for channel, ready in (scoped.get("channels") or {}).items():
                aggregate["channels"][channel] = aggregate["channels"].get(channel, False) or bool(ready)
            aggregate["errors"].extend(scoped.get("errors") or [])
        return aggregate

    config_errors: list[dict[str, Any]] = []
    resolved_wechat: BotConfig | None = wechat_config
    resolved_dingtalk = (
        list(dingtalk_configs)
        if dingtalk_configs is not None
        else ([dingtalk_config] if dingtalk_config else [])
    )
    if resolved_wechat is None and _load_default_configs:
        try:
            resolved_wechat = load_bot_config()
        except Exception as exc:
            config_errors.append({"channel": "wechat_work", "error": str(exc)})
    if (
        not resolved_dingtalk
        and dingtalk_configs is None
        and dingtalk_config is None
        and _load_default_configs
    ):
        try:
            resolved_dingtalk = [load_dingtalk_config()]
        except Exception as exc:
            config_errors.append({"channel": "dingtalk", "error": str(exc)})
    channel_ready = {
        "wechat_work": bool(resolved_wechat and _wechat_ready(resolved_wechat)),
        "dingtalk": any(dingtalk_config_status(config).get("configured") for config in resolved_dingtalk),
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
            for config in resolved_dingtalk:
                if not dingtalk_config_status(config).get("configured"):
                    continue
                try:
                    post_dingtalk_markdown(content, config, title="代码泄露监测通知")
                    result["sent"] += 1
                except Exception as exc:
                    result["failed"] += 1
                    result["errors"].append(
                        {
                            "channel": "dingtalk",
                            "endpoint_id": config.endpoint_id,
                            "name": config.name,
                            "hit_id": hit.get("id"),
                            "error": str(exc),
                        }
                    )
                    logger.exception("failed to send code monitoring hit to DingTalk")
    return result
