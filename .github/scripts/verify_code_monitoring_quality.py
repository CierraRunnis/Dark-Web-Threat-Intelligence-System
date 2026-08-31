from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile

from darkweb_collector.code_monitoring import (
    CODE_CLASSIFICATION_VERSION,
    _build_stored_code_hit_payload,
    _classify_code_hit,
    _derived_search_terms_from_profile,
    paginate_code_hits_payloads,
)
from darkweb_collector.code_monitoring_notifications import _primary_hits
from darkweb_collector.bot_assistant import BOT_PROVIDER_WECHAT_WORK_WEBHOOK, BotConfig
from darkweb_collector.dingtalk_bot import DingTalkConfig
from darkweb_collector import code_monitoring_notifications as code_notifications
from darkweb_collector.db import _ensure_schema, upsert_code_hit_with_state, upsert_code_watchlist
from darkweb_collector.postgres_backend import CompatRow
from darkweb_collector import code_monitoring as code_monitoring_module
from darkweb_collector import watchlist_notifications as watchlist_notification_module


ENTERPRISE_MATCH = {
    "valid": True,
    "level": "strong",
    "anchors": [{"type": "root_domain", "label": "企业主域名", "value": "catl.com"}],
    "system_keywords": [],
}

derived_terms = _derived_search_terms_from_profile(
    {
        "official_names": ["宁德时代"],
        "brand_aliases": ["CATL"],
        "english_aliases": ["catl"],
        "root_domains": ["catl.com"],
        "internal_system_keywords": ["battery-platform"],
        "negative_aliases": ["cat"],
        "trusted_subdomain_patterns": ["*.catl.com"],
    }
)
assert {(item["term"], item["term_type"]) for item in derived_terms} == {
    ("宁德时代", "company_name"),
    ("CATL", "company_name"),
    ("catl.com", "domain"),
    ("battery-platform", "custom"),
}


def classify(file_path: str, text: str, repository_name: str = "sample") -> dict:
    payload = _classify_code_hit(
        "catl.com",
        file_path,
        text,
        ["api_key", "token", "ak_sk", "db_url", "jwt_secret", "redis_url", "private_key", "internal_url", "password"],
        term_type="domain",
        enterprise_match=ENTERPRISE_MATCH,
        context_metadata={"repository_name": repository_name, "repository_owner": "corp-security"},
    )
    assert payload is not None
    assert payload["classification_version"] == CODE_CLASSIFICATION_VERSION
    return payload


false_positive_cases = (
    ("app/api/v1/endpoints/sales/mobile.py", '{"email": "buyer@catl.com", "login": true}', "non-standard-automation-pms"),
    ("scripts/backfill_profiles.py", '{"官网":"https://www.catl.com","邮箱":"market@catl.com","证券":"A股"}', "ashare-monitor"),
    ("FineTune/data/pdf_docs/2021_宁德时代_年度报告/basic_info.txt", "宁德时代 300750 年度报告 catl.com", "PiXiu"),
    ("public/data/web10000_35.json", '{"website":"catl.com","dataset":"public"}', "nextlist1312"),
    ("scripts/careers-audit.json", '{"company":"CATL","domain":"catl.com","career":true}', "skill.supply"),
    ("reports/evidence.yaml", "public report evidence for catl.com", "startup"),
)
for path, text, repository in false_positive_cases:
    result = classify(path, text, repository)
    assert result["suppressed"] is True, (path, result)
    assert result["display_bucket"] == "suppressed"

literal_secret = classify("config/prod.py", 'catl.com\napi_key = "sk_live_1234567890abcdefghijkl"', "internal-service")
assert literal_secret["result_layer"] == "sensitive"
assert literal_secret["display_bucket"] == "primary"

private_key = classify(
    "deploy/prod.pem",
    "catl.com\n-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END " + "PRIVATE KEY-----",
    "internal-deploy",
)
assert private_key["display_bucket"] == "primary"

public_example = classify(
    "docs/example.md",
    'catl.com\napi_key = "replace_with_real_token_123456"',
    "public-docs",
)
assert public_example["display_bucket"] == "suppressed"

keyword_only = classify("src/client.py", "catl.com\nlogin(user)\nmail = 'public'", "client")
assert keyword_only["result_layer"] == "clue"
assert keyword_only["display_bucket"] == "suppressed"

environment_reference = classify("src/settings.py", 'catl.com\napi_key = os.getenv("CATL_API_KEY")', "client")
assert environment_reference["display_bucket"] == "suppressed"

internal_url_only = classify("config/service.py", 'catl.com\nendpoint = "http://10.20.30.40/admin"', "client")
assert internal_url_only["display_bucket"] == "suppressed"

internal_access = classify(
    "src/client.py",
    'catl.com\nendpoint = "http://10.20.30.40/admin"\nrequests.post(endpoint)\nlogin(user)',
    "internal-client",
)
assert internal_access["display_bucket"] == "primary"

remote_database = classify(
    "config/prod.py",
    'catl.com\ndatabase_url = "postgresql://service:real_password@db.corp.invalid:5432/prod"',
    "internal-service",
)
assert remote_database["display_bucket"] == "primary"

row = {
    "id": 1,
    "watchlist_id": 1,
    "platform": "github",
    "repository_name": "legacy",
    "repository_owner": "example",
    "repository_url": "https://github.com/example/legacy",
    "file_path": "README.md",
    "file_url": "https://github.com/example/legacy/blob/main/README.md",
    "sensitive_type": "clue",
    "matched_term": "catl.com",
}
assert _build_stored_code_hit_payload(row, {"display_bucket": "primary"}) is None

eligible = _primary_hits(
    [
        {"id": 1, "displayBucket": "primary", "suppressed": False, "resultLayer": "clue"},
        {"id": 2, "displayBucket": "suppressed", "suppressed": True, "resultLayer": "sensitive"},
        {"id": 3, "displayBucket": "primary", "suppressed": False, "resultLayer": "sensitive"},
    ]
)
assert [item["id"] for item in eligible] == [3]

deliveries: list[str] = []
original_wechat_post = code_notifications.post_bot_payload
original_dingtalk_post = code_notifications.post_dingtalk_markdown
try:
    code_notifications.post_bot_payload = lambda _payload, _config: deliveries.append("wechat") or {"ok": True}
    code_notifications.post_dingtalk_markdown = lambda _content, _config, *, title: deliveries.append("dingtalk") or {"ok": True, "title": title}
    notification_result = code_notifications.notify_code_monitoring_hits(
        [
            {"id": 1, "displayBucket": "primary", "suppressed": False, "resultLayer": "clue", "sensitiveType": "clue"},
            {"id": 2, "displayBucket": "suppressed", "suppressed": True, "resultLayer": "sensitive", "sensitiveType": "api_key"},
            {"id": 3, "displayBucket": "primary", "suppressed": False, "resultLayer": "sensitive", "sensitiveType": "api_key"},
        ],
        wechat_config=BotConfig(
            provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            webhook_key="test",
        ),
        dingtalk_config=DingTalkConfig(webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test"),
    )
finally:
    code_notifications.post_bot_payload = original_wechat_post
    code_notifications.post_dingtalk_markdown = original_dingtalk_post
assert notification_result["eligible"] == 1 and notification_result["sent"] == 2
assert deliveries == ["wechat", "dingtalk"]

scoped_deliveries: list[tuple[str, str]] = []
original_scoped_loader = watchlist_notification_module.load_watchlist_channel_configs
original_wechat_post = code_notifications.post_bot_payload
original_dingtalk_post = code_notifications.post_dingtalk_markdown
try:
    watchlist_notification_module.load_watchlist_channel_configs = lambda watchlist_id: (
        (
            BotConfig(
                provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
                webhook_url=f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=object-{watchlist_id}",
                webhook_key=f"object-{watchlist_id}",
                settings_path=f"object-{watchlist_id}-wechat.json",
            ) if watchlist_id == 11 else None
        ),
        (
            DingTalkConfig(
                webhook_url=f"https://oapi.dingtalk.com/robot/send?access_token=object-{watchlist_id}",
                settings_path=f"object-{watchlist_id}-dingtalk.json",
            ) if watchlist_id == 22 else None
        ),
        {},
    )
    code_notifications.post_bot_payload = lambda _payload, config: scoped_deliveries.append(("wechat", config.settings_path)) or {"ok": True}
    code_notifications.post_dingtalk_markdown = lambda _content, config, *, title: scoped_deliveries.append(("dingtalk", config.settings_path)) or {"ok": True}
    scoped_result = code_notifications.notify_code_monitoring_hits(
        [
            {"id": 11, "watchlistId": 11, "displayBucket": "primary", "suppressed": False, "resultLayer": "sensitive", "sensitiveType": "api_key"},
            {"id": 22, "watchlistId": 22, "displayBucket": "primary", "suppressed": False, "resultLayer": "sensitive", "sensitiveType": "api_key"},
        ]
    )
finally:
    watchlist_notification_module.load_watchlist_channel_configs = original_scoped_loader
    code_notifications.post_bot_payload = original_wechat_post
    code_notifications.post_dingtalk_markdown = original_dingtalk_post
assert scoped_result["sent"] == 2 and scoped_result["eligible"] == 2
assert scoped_deliveries == [("wechat", "object-11-wechat.json"), ("dingtalk", "object-22-dingtalk.json")]

now = datetime.now(timezone.utc)
items = [
    {"id": 1, "repositoryFullName": "org/new-primary", "filePath": "prod.env", "matchedTerm": "catl.com", "displayBucket": "primary", "suppressed": False, "severity": "high", "resultLayer": "sensitive", "firstSeenAt": now.isoformat(), "lastSeenAt": now.isoformat()},
    {"id": 2, "repositoryFullName": "org/old-primary", "filePath": "old.txt", "matchedTerm": "catl.com", "displayBucket": "primary", "suppressed": False, "severity": "medium", "resultLayer": "clue", "firstSeenAt": (now - timedelta(days=40)).isoformat(), "lastSeenAt": now.isoformat()},
    {"id": 3, "repositoryFullName": "org/public-dataset", "filePath": "public/data.json", "matchedTerm": "catl.com", "displayBucket": "suppressed", "suppressed": True, "severity": "low", "resultLayer": "clue", "firstSeenAt": now.isoformat(), "lastSeenAt": now.isoformat(), "suppressionReasons": ["公开参考数据集"]},
]
recent = paginate_code_hits_payloads(items, bucket="all", seen_after=(now - timedelta(days=7)).isoformat(), offset=0, limit=20)
assert recent["total"] == 2
suppressed = paginate_code_hits_payloads(items, query="dataset", bucket="suppressed", offset=0, limit=20)
assert suppressed["total"] == 1 and suppressed["items"][0]["id"] == 3

try:
    paginate_code_hits_payloads(items, seen_after="not-a-date")
except ValueError:
    pass
else:
    raise AssertionError("invalid seen_after must fail")

api_source = (Path(__file__).resolve().parents[2] / "darkweb_collector/src/darkweb_collector/api_app.py").read_text(encoding="utf-8")
assert api_source.index('@app.get("/api/code-monitoring/hits/page")') < api_source.index('@app.get("/api/code-monitoring/hits/{hit_id}")')


class RevisionCursor:
    def fetchone(self):
        columns = (
            "hit_count", "max_hit_id", "max_hit_seen_at", "max_snapshot_id", "review_count",
            "max_review_id", "watchlist_updated_at", "term_count", "term_updated_at",
        )
        return CompatRow(columns, (23, 23, now.isoformat(), 22, 0, 0, now.isoformat(), 1, now.isoformat()))


class RevisionConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql):
        return RevisionCursor()


original_ensure_default = code_monitoring_module.ensure_default_code_watchlist
original_get_connection = code_monitoring_module.get_db_connection
try:
    code_monitoring_module.ensure_default_code_watchlist = lambda: None
    code_monitoring_module.get_db_connection = lambda: RevisionConnection()
    revision = code_monitoring_module._code_hits_payload_cache_revision()
finally:
    code_monitoring_module.ensure_default_code_watchlist = original_ensure_default
    code_monitoring_module.get_db_connection = original_get_connection
assert revision[1:3] == (23, 23), revision

with tempfile.TemporaryDirectory(prefix="dwti-code-quality-") as temp_dir:
    connection = sqlite3.connect(Path(temp_dir) / "quality.db")
    connection.row_factory = sqlite3.Row
    _ensure_schema(connection)
    watchlist_id = upsert_code_watchlist(
        connection,
        {
            "name": "Quality",
            "organization_name": "CATL",
            "enabled": True,
            "metadata_json": "{}",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
    )
    payload = {
        "watchlist_id": watchlist_id,
        "platform": "github",
        "repository_name": "repo",
        "repository_owner": "owner",
        "repository_url": "https://github.com/owner/repo",
        "file_path": "prod.env",
        "branch": "main",
        "file_url": "https://github.com/owner/repo/blob/main/prod.env",
        "visibility": "public",
        "language": "",
        "sensitive_type": "api_key",
        "matched_rule": "API Key",
        "matched_term": "catl.com",
        "result_layer": "sensitive",
        "risk_score": 80,
        "severity": "high",
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "raw_json": "{}",
    }
    first_id, first_created = upsert_code_hit_with_state(connection, payload)
    second_id, second_created = upsert_code_hit_with_state(connection, payload)
    assert first_id == second_id and first_created is True and second_created is False
    connection.close()

print("Strict code monitoring classification, notification, and paging checks passed.")
