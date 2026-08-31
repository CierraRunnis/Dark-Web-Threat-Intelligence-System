from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile

from darkweb_collector.bot_assistant import BOT_PROVIDER_WECHAT_WORK_WEBHOOK, BotConfig
from darkweb_collector.dingtalk_bot import DingTalkConfig
from darkweb_collector import monitoring_notifications as notifications
from darkweb_collector.normalized_intelligence import _new_normalized_events


class Connection:
    def executemany(self, _query, _rows):
        return None

    def commit(self):
        return None


records: dict[tuple[str, str], dict] = {}
deliveries: list[tuple[str, str]] = []
fail_dingtalk = False


def get_record(_connection, event_id: str, match_signature: str):
    return records.get((event_id, match_signature))


def get_record_by_event_key(_connection, event_key: str):
    for record in records.values():
        if record.get("event_key") == event_key and record.get("status") == "sent" and not record.get("dry_run"):
            return record
    return None


def save_record(_connection, payload: dict):
    records[(payload["event_id"], payload["match_signature"])] = dict(payload)


def send_wechat(_payload, _config):
    deliveries.append((notifications.CHANNEL_WECHAT_WORK, current_event_id))
    return {"ok": True, "dry_run": False}


def send_dingtalk(_content, _config, *, title: str):
    assert title == "监控关键词命中通知"
    deliveries.append((notifications.CHANNEL_DINGTALK, current_event_id))
    if fail_dingtalk:
        raise RuntimeError("simulated DingTalk failure")
    return {"ok": True, "dry_run": False}


def event(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "ransomware" if event_id != "data-leak" else "data-leak",
        "title": f"Event {event_id}",
        "victim": "Example Corp",
        "attacker": "Example Actor",
        "disclosure_time": datetime.now(timezone.utc).isoformat(),
        "source_url": f"https://example.invalid/{event_id}",
        "monitoring_matches": [
            {"keyword": "Example", "category": "org_keywords", "weight": 10, "match_count": 1}
        ],
    }


notifications.monitoring_rules.enrich_events = lambda _connection, events: events
notifications.get_monitoring_keyword_notification = get_record
notifications.get_monitoring_keyword_notification_by_event_key = get_record_by_event_key
notifications.upsert_monitoring_keyword_notification = save_record
notifications.post_bot_payload = send_wechat
notifications.post_dingtalk_markdown = send_dingtalk

wechat = BotConfig(
    provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
    webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
    webhook_key="test",
)
dingtalk = DingTalkConfig(
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
)
connection = Connection()

current_event_id = "existing"
existing = event(current_event_id)
current_event_id = "first-new"
first = event(current_event_id)
new_events = _new_normalized_events([existing, first], {"existing"})
assert [item["event_id"] for item in new_events] == ["first-new"]
result = notifications.notify_keyword_matches_for_events(
    connection,
    new_events,
    config=wechat,
    dingtalk_config=dingtalk,
)
assert result["matched"] == 1 and result["sent"] == 2 and result["failed"] == 0
assert deliveries.count((notifications.CHANNEL_WECHAT_WORK, current_event_id)) == 1
assert deliveries.count((notifications.CHANNEL_DINGTALK, current_event_id)) == 1
assert deliveries.count((notifications.CHANNEL_WECHAT_WORK, "existing")) == 0
assert deliveries.count((notifications.CHANNEL_DINGTALK, "existing")) == 0
assert _new_normalized_events([existing, first], {"existing", "first-new"}) == []

again = notifications.notify_keyword_matches_for_events(
    connection,
    [first],
    config=wechat,
    dingtalk_config=dingtalk,
)
assert again["sent"] == 0 and again["skipped"] == 2

current_event_id = "failure-isolation"
failed_event = event(current_event_id)
fail_dingtalk = True
partial = notifications.notify_keyword_matches_for_events(
    connection,
    [failed_event],
    config=wechat,
    dingtalk_config=dingtalk,
)
assert partial["sent"] == 1 and partial["failed"] == 1
fail_dingtalk = False
retry = notifications.notify_keyword_matches_for_events(
    connection,
    [failed_event],
    config=wechat,
    dingtalk_config=dingtalk,
)
assert retry["sent"] == 1 and retry["skipped"] == 1
assert deliveries.count((notifications.CHANNEL_WECHAT_WORK, current_event_id)) == 1
assert deliveries.count((notifications.CHANNEL_DINGTALK, current_event_id)) == 2

current_event_id = "legacy-wechat"
legacy_event = event(current_event_id)
matches = notifications._match_entries(legacy_event["monitoring_matches"])
legacy_signature = notifications.keyword_match_signature(matches)
records[(current_event_id, legacy_signature)] = {
    "event_id": current_event_id,
    "event_key": notifications._notification_event_key(legacy_event),
    "match_signature": legacy_signature,
    "status": "sent",
    "dry_run": False,
}
legacy = notifications.notify_keyword_matches_for_events(
    connection,
    [legacy_event],
    config=wechat,
    dingtalk_config=dingtalk,
)
assert legacy["sent"] == 1 and legacy["skipped"] == 1
assert deliveries.count((notifications.CHANNEL_WECHAT_WORK, current_event_id)) == 0
assert deliveries.count((notifications.CHANNEL_DINGTALK, current_event_id)) == 1

current_event_id = "data-leak"
dingtalk_only = notifications.notify_keyword_matches_for_events(
    connection,
    [event(current_event_id)],
    config=wechat,
    dingtalk_config=dingtalk,
    channels={notifications.CHANNEL_DINGTALK},
)
assert dingtalk_only["sent"] == 1
assert deliveries.count((notifications.CHANNEL_WECHAT_WORK, current_event_id)) == 0
assert deliveries.count((notifications.CHANNEL_DINGTALK, current_event_id)) == 1

previous_db_path = os.environ.get("DARKWEB_COLLECTOR_DB_PATH")
previous_dry_run = os.environ.get("BOT_DRY_RUN")
scoped_deliveries: list[tuple[str, str]] = []
try:
    with tempfile.TemporaryDirectory(prefix="dwti-watchlist-notifications-") as temporary:
        os.environ["DARKWEB_COLLECTOR_DB_PATH"] = str(Path(temporary) / "collector.db")
        os.environ["BOT_DRY_RUN"] = "1"
        from darkweb_collector.db import get_db_connection, upsert_code_watchlist
        from darkweb_collector.watchlist_notifications import (
            save_watchlist_notification_profile,
            set_watchlist_dingtalk_config,
            set_watchlist_wechat_config,
        )

        with get_db_connection() as scoped_connection:
            object_a = upsert_code_watchlist(
                scoped_connection,
                {"name": "Object A", "organization_name": "Alpha Corp", "enabled": True, "metadata_json": "{}", "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()},
            )
            object_b = upsert_code_watchlist(
                scoped_connection,
                {"name": "Object B", "organization_name": "Beta Corp", "enabled": True, "metadata_json": "{}", "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()},
            )
            scoped_connection.commit()

        save_watchlist_notification_profile(
            object_a,
            keywords=[{"keyword": "Alpha", "category": "org_keywords", "weight": 10, "enabled": True, "match_mode": "contains"}],
        )
        set_watchlist_wechat_config(object_a, bot_id="alpha-bot", secret="alpha-secret")
        save_watchlist_notification_profile(
            object_b,
            keywords=[{"keyword": "Beta", "category": "org_keywords", "weight": 10, "enabled": True, "match_mode": "contains"}],
        )
        set_watchlist_dingtalk_config(object_b, webhook_url="beta-token")

        original_scoped_wechat = notifications.post_bot_payload
        original_scoped_dingtalk = notifications.post_dingtalk_markdown
        notifications.post_bot_payload = lambda _payload, config: scoped_deliveries.append(("wechat", config.settings_path)) or {"ok": True, "dry_run": False}
        notifications.post_dingtalk_markdown = lambda _content, config, *, title: scoped_deliveries.append(("dingtalk", config.settings_path)) or {"ok": True, "dry_run": False}
        try:
            scoped_events = [
                {**event("alpha-event"), "title": "Alpha incident"},
                {**event("beta-event"), "title": "Beta incident"},
            ]
            with get_db_connection() as scoped_connection:
                scoped_result = notifications.notify_keyword_matches_for_watchlists(scoped_connection, scoped_events)
        finally:
            notifications.post_bot_payload = original_scoped_wechat
            notifications.post_dingtalk_markdown = original_scoped_dingtalk

        assert scoped_result["matched"] == 2 and scoped_result["sent"] == 2
        assert len(scoped_deliveries) == 2
        assert any(channel == "wechat" and f"{object_a}\\wecom.json" in path for channel, path in scoped_deliveries)
        assert any(channel == "dingtalk" and f"{object_b}\\dingtalk.json" in path for channel, path in scoped_deliveries)
        from darkweb_collector.code_monitoring import delete_code_watchlist_payload

        delete_code_watchlist_payload(object_a)
        notification_root = Path(temporary) / "watchlist-notifications"
        assert not (notification_root / str(object_a)).exists()
        assert (notification_root / str(object_b)).exists()
finally:
    if previous_db_path is None:
        os.environ.pop("DARKWEB_COLLECTOR_DB_PATH", None)
    else:
        os.environ["DARKWEB_COLLECTOR_DB_PATH"] = previous_db_path
    if previous_dry_run is None:
        os.environ.pop("BOT_DRY_RUN", None)
    else:
        os.environ["BOT_DRY_RUN"] = previous_dry_run

root = Path(__file__).resolve().parents[2]
settings_html = (root / "threat-intelligence-dashboard/src/prototype/screens/settings.html").read_text(encoding="utf-8")
settings_runtime = (root / "threat-intelligence-dashboard/src/prototype/runtime.js").read_text(encoding="utf-8")
router_source = (root / "threat-intelligence-dashboard/src/router/index.js").read_text(encoding="utf-8")

assert "screen('/settings', 'Settings', 'settings.html')" in router_source
assert "情报监控关键词" in settings_html
assert 'data-monitoring-keyword-list' in settings_html
for action in ("monitoring-keyword-refresh", "monitoring-keyword-add", "monitoring-keyword-save"):
    assert f'data-code-action="{action}"' in settings_html
assert "renderMonitoringKeywords" in settings_runtime
assert "readMonitoringKeywords" in settings_runtime
assert "data-needs-watchlist-notifications" in settings_html
assert "作用范围：当前监测对象" in settings_html
assert "/api/code-monitoring/watchlists/${encodeURIComponent(watchlistId)}/notifications" in settings_runtime
assert "saveWatchlistNotificationProfile" in settings_runtime
assert "request('/api/monitoring/keywords')" not in settings_runtime

print("Monitoring keyword WeCom/DingTalk channel checks passed.")
