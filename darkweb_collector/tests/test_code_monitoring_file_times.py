from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.code_monitoring import (
    _build_stored_code_hit_payload,
    _collect_gitee_repo_search_window,
    _gitee_file_commit_metadata,
    _github_file_commit_metadata,
    _gitlab_file_commit_metadata,
)


class CodeMonitoringFileTimeTests(unittest.TestCase):
    def test_github_commit_metadata_uses_latest_file_commit(self) -> None:
        with patch(
            "darkweb_collector.code_monitoring._http_get_json",
            return_value=[
                {
                    "sha": "a566368149425b1da58ce0c1eb4c2be6561a2c6a",
                    "commit": {
                        "author": {"date": "2026-04-30T04:17:00Z"},
                        "committer": {"date": "2026-04-30T04:18:06Z"},
                    },
                }
            ],
        ) as get_json:
            payload = _github_file_commit_metadata("owner", "repo", "main", "config/app.yml")

        self.assertEqual("2026-04-30T04:18:06+00:00", payload["fileCommittedAt"])
        self.assertEqual(payload["fileCommittedAt"], payload["fileUpdatedAt"])
        self.assertEqual("a566368149425b1da58ce0c1eb4c2be6561a2c6a", payload["fileCommitSha"])
        self.assertEqual("github_commits_api", payload["fileTimeSource"])
        self.assertIn("path=config%2Fapp.yml", get_json.call_args.args[0])

    def test_gitlab_commit_metadata_uses_committed_date(self) -> None:
        with patch(
            "darkweb_collector.code_monitoring._http_get_json",
            return_value=[
                {
                    "id": "8aece18ce11e22f752ddd2a84c02e4df2e532762",
                    "created_at": "2026-01-09T09:30:00.000+01:00",
                    "committed_date": "2026-01-09T09:34:26.000+01:00",
                }
            ],
        ) as get_json:
            payload = _gitlab_file_commit_metadata("https://gitlab.com/group/project", "master", "README.md")

        self.assertEqual("2026-01-09T09:34:26+01:00", payload["fileCommittedAt"])
        self.assertEqual("8aece18ce11e22f752ddd2a84c02e4df2e532762", payload["fileCommitSha"])
        self.assertEqual("gitlab_commits_api", payload["fileTimeSource"])
        self.assertIn("projects/group%2Fproject/repository/commits", get_json.call_args.args[0])

    def test_gitee_commit_metadata_falls_back_to_html_time(self) -> None:
        html = """
        <html><head><title>提交</title></head>
        <body><time>2026-05-14 16:26:43 +0800</time></body></html>
        """
        candidate = {
            "repositoryUrl": "https://gitee.com/vnpy/vnpy",
            "branch": "master",
            "filePath": "README.md",
        }
        with patch.dict(os.environ, {"GITEE_ACCESS_TOKEN": "", "GITEE_TOKEN": ""}, clear=False), patch(
            "darkweb_collector.code_monitoring._read_http_text",
            return_value=(html, "https://gitee.com/vnpy/vnpy/commits/master/README.md"),
        ) as read_text:
            payload = _gitee_file_commit_metadata(candidate)

        self.assertEqual("2026-05-14T16:26:43+08:00", payload["fileCommittedAt"])
        self.assertEqual(payload["fileCommittedAt"], payload["fileUpdatedAt"])
        self.assertEqual("gitee_commits_html", payload["fileTimeSource"])
        self.assertIn("/commits/master/README.md", read_text.call_args.args[0])

    def test_gitee_widget_repo_owner_prefers_repository_url(self) -> None:
        widget_payload = {
            "hits": {
                "hits": [
                    {
                        "fields": {
                            "url": ["https://gitee.com/vnpy/vnpy"],
                            "title": ["vn.py"],
                            "path": ["vnpy"],
                            "owner.path.keyword": ["vn_py"],
                            "description": ["python framework"],
                        }
                    }
                ]
            }
        }
        with patch("darkweb_collector.code_monitoring._http_get_json", return_value=widget_payload):
            rows, _ = _collect_gitee_repo_search_window("python", page_count=1)

        self.assertEqual(1, len(rows))
        self.assertEqual("vnpy", rows[0]["repositoryOwner"])
        self.assertEqual("vnpy", rows[0]["repositoryName"])

    def test_stored_hit_payload_exposes_candidate_file_time(self) -> None:
        row = {
            "id": 7,
            "watchlist_id": 2,
            "watchlist_name": "宁德时代",
            "organization_name": "宁德时代",
            "platform": "github",
            "repository_name": "repo",
            "repository_owner": "owner",
            "repository_url": "https://github.com/owner/repo",
            "file_path": "config/app.yml",
            "branch": "main",
            "file_url": "https://github.com/owner/repo/blob/main/config/app.yml",
            "visibility": "public",
            "language": "YAML",
            "sensitive_type": "api_key",
            "matched_rule": "API Key",
            "matched_term": "catl.com",
            "result_layer": "sensitive",
            "risk_score": 80,
            "severity": "high",
            "review_status": "new",
            "evidence_count": 1,
            "first_seen_at": "2026-07-07T08:00:00+00:00",
            "last_seen_at": "2026-07-07T08:10:00+00:00",
            "last_snapshot_id": 9,
        }
        raw_payload = {
            "display_bucket": "primary",
            "result_layer": "sensitive",
            "candidate": {
                "fileUpdatedAt": "2026-04-30T04:18:06Z",
                "fileCommittedAt": "2026-04-30T04:18:06Z",
                "fileCommitSha": "a56636814942",
                "fileTimeSource": "github_commits_api",
            },
        }

        payload = _build_stored_code_hit_payload(row, raw_payload)

        self.assertIsNotNone(payload)
        self.assertEqual("2026-04-30T04:18:06+00:00", payload["fileUpdatedAt"])
        self.assertEqual("2026-04-30T04:18:06+00:00", payload["fileCommittedAt"])
        self.assertEqual("a56636814942", payload["fileCommitSha"])
        self.assertEqual("github_commits_api", payload["fileTimeSource"])


if __name__ == "__main__":
    unittest.main()
