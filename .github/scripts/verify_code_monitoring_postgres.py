from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from darkweb_collector.code_monitoring import (
    CODE_CLASSIFICATION_VERSION,
    _classify_code_hit,
    search_code_hits_page,
)
from darkweb_collector.db import (
    delete_code_watchlist,
    get_db_connection,
    insert_code_hit_snapshot,
    insert_code_scan_run,
    replace_code_watch_terms,
    update_code_hit_last_snapshot,
    upsert_code_hit_with_state,
    upsert_code_watchlist,
)


now = datetime.now(timezone.utc).isoformat()
enterprise_match = {
    "valid": True,
    "level": "strong",
    "anchors": [{"type": "root_domain", "label": "企业主域名", "value": "catl.com"}],
    "system_keywords": [],
}
rules = ["api_key", "token", "ak_sk", "db_url", "jwt_secret", "redis_url", "private_key", "internal_url", "password"]


def classification(path: str, text: str, repository: str) -> dict:
    result = _classify_code_hit(
        "catl.com",
        path,
        text,
        rules,
        term_type="domain",
        enterprise_match=enterprise_match,
        context_metadata={"repositoryOwner": "quality", "repositoryName": repository},
    )
    assert result is not None
    return result


with get_db_connection() as connection:
    assert getattr(connection, "backend_name", "") == "postgresql"
    watchlist_id = upsert_code_watchlist(
        connection,
        {
            "name": "CATL Quality Preview",
            "organization_name": "宁德时代",
            "enabled": True,
            "notes": "isolated PostgreSQL quality verification",
            "metadata_json": json.dumps(
                {
                    "platforms": ["github"],
                    "enabled_rule_keys": rules,
                    "enterprise_profile": {"root_domains": ["catl.com"], "official_names": ["宁德时代"]},
                },
                ensure_ascii=False,
            ),
            "created_at": now,
            "updated_at": now,
        },
    )
    replace_code_watch_terms(
        connection,
        watchlist_id,
        [{"term": "catl.com", "term_type": "domain", "weight": 10, "enabled": True, "created_at": now, "updated_at": now}],
    )

    examples = (
        (
            "public-annual-report",
            "FineTune/data/pdf_docs/宁德时代_2021年_年度报告/basic_info.txt",
            "宁德时代 300750 年度报告 官网 catl.com",
            "https://github.com/quality/public-annual-report/blob/main/basic_info.txt",
            "suppressed",
        ),
        (
            "verified-secret",
            "config/prod.py",
            'catl.com\napi_key = "' + "Q" * 32 + '"',
            "https://github.com/quality/verified-secret/blob/main/config/prod.py",
            "primary",
        ),
    )
    for repository, path, text, file_url, expected_bucket in examples:
        result = classification(path, text, repository)
        assert result["classification_version"] == CODE_CLASSIFICATION_VERSION
        assert result["display_bucket"] == expected_bucket
        raw_payload = {
            **result,
            "candidate": {
                "repositoryOwner": "quality",
                "repositoryName": repository,
                "repositoryUrl": f"https://github.com/quality/{repository}",
                "filePath": path,
                "fileUrl": file_url,
            },
            "code_text": text,
            "term_type": "domain",
        }
        hit_id, created = upsert_code_hit_with_state(
            connection,
            {
                "watchlist_id": watchlist_id,
                "platform": "github",
                "repository_name": repository,
                "repository_owner": "quality",
                "repository_url": f"https://github.com/quality/{repository}",
                "file_path": path,
                "branch": "main",
                "file_url": file_url,
                "visibility": "public",
                "language": "python" if path.endswith(".py") else "text",
                "sensitive_type": result["sensitive_type"],
                "matched_rule": result["matched_rule"],
                "matched_term": "catl.com",
                "result_layer": result["result_layer"],
                "risk_score": result["risk_score"],
                "severity": result["severity"],
                "first_seen_at": now,
                "last_seen_at": now,
                "raw_json": json.dumps(raw_payload, ensure_ascii=False),
            },
        )
        assert created is True
        snapshot_id = insert_code_hit_snapshot(
            connection,
            {
                "hit_id": hit_id,
                "fetched_at": now,
                "search_url": "https://api.github.com/search/code",
                "page_url": file_url,
                "html_path": "",
                "screenshot_path": "",
                "code_fragment": "",
                "masked_fragment": "",
                "raw_artifact_path": "",
                "line_start": 1,
                "line_end": 2,
                "language": "text",
                "findings_json": json.dumps(result.get("findings") or []),
                "raw_json": json.dumps(raw_payload, ensure_ascii=False),
            },
        )
        update_code_hit_last_snapshot(connection, hit_id, snapshot_id)

    insert_code_scan_run(
        connection,
        {
            "watchlist_id": watchlist_id,
            "platforms_json": '["github"]',
            "requested_terms_json": '["catl.com"]',
            "candidate_count": 2,
            "hit_count": 2,
            "clue_hit_count": 1,
            "sensitive_hit_count": 1,
            "error_count": 0,
            "status": "succeeded",
            "errors_json": "[]",
            "started_at": now,
            "finished_at": now,
        },
    )
    connection.commit()

primary = search_code_hits_page(watchlist_id=watchlist_id, bucket="primary", limit=20)
suppressed = search_code_hits_page(watchlist_id=watchlist_id, bucket="suppressed", query="annual", limit=20)
assert primary["total"] == 1 and primary["items"][0]["repositoryName"] == "verified-secret"
assert suppressed["total"] == 1 and suppressed["items"][0]["repositoryName"] == "public-annual-report"

if os.environ.get("DARKWEB_KEEP_QUALITY_DATA") != "1":
    with get_db_connection() as connection:
        delete_code_watchlist(connection, watchlist_id)
        connection.commit()

print("Real PostgreSQL code hits, snapshots, scan history, paging, and strict classification checks passed.")
