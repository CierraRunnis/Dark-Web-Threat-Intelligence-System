from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.code_monitoring import (
    _classify_code_hit,
    _extract_code_lines,
    _search_page_url,
    build_code_hit_detail,
    save_code_watchlist_payload,
)
from darkweb_collector.db import (
    get_db_connection,
    insert_code_hit_snapshot,
    update_code_hit_last_snapshot,
    upsert_code_hit,
)


class CodeMonitoringTests(unittest.TestCase):
    def _env(self, db_path: Path, output_root: Path, config_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_root),
            "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
        }

    def _write_empty_sites(self, path: Path) -> None:
        path.write_text(json.dumps({"sites": []}, ensure_ascii=False), encoding="utf-8")

    def test_extract_code_lines_keeps_full_github_line(self) -> None:
        html = """
        <div id="LC31" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
          <span class="pl-s">'password'</span> : <span class="pl-s1">PASSWORD</span> ,
        </div>
        <div id="LC32" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
          <span class="pl-s">'search_query'</span>: [<span class="pl-s">'FROM'</span>, <span class="pl-s">'ibanking.alert@dbs.com'</span>, <span class="pl-s">'SUBJECT'</span>]
        </div>
        """

        rows = _extract_code_lines(html)

        self.assertEqual(2, len(rows))
        self.assertEqual(31, rows[0][0])
        self.assertIn("'password' : PASSWORD ,", rows[0][1])
        self.assertEqual(32, rows[1][0])
        self.assertIn("ibanking.alert@dbs.com", rows[1][1])
        self.assertIn("'search_query'", rows[1][1])

    def test_search_page_url_builds_follow_up_pages(self) -> None:
        self.assertEqual(
            "https://github.com/search?q=dbs&type=code&p=3",
            _search_page_url("github", "https://github.com/search?q=dbs&type=code", 3),
        )
        self.assertEqual(
            "https://gitlab.com/search?search=dbs&nav_source=navbar&type=blobs&page=2",
            _search_page_url("gitlab", "https://gitlab.com/search?search=dbs&nav_source=navbar&type=blobs", 2),
        )

    def test_classify_code_hit_supports_clue_and_sensitive_layers(self) -> None:
        clue = _classify_code_hit(
            "DBS.com",
            "app.py",
            "config = {'search_query': ['FROM', 'ibanking.alert@dbs.com']}\nmail_client.send('ibanking.alert@dbs.com')",
            ["password", "token"],
        )
        self.assertIsNotNone(clue)
        self.assertEqual("clue", clue["result_layer"])
        self.assertEqual("clue", clue["sensitive_type"])

        sensitive = _classify_code_hit(
            "DBS.com",
            "app.py",
            "token = 'abcdefghijklmnop123456'\nPASSWORD = os.getenv('PASSWORD')",
            ["password", "token"],
        )
        self.assertIsNotNone(sensitive)
        self.assertEqual("sensitive", sensitive["result_layer"])
        self.assertIn(sensitive["sensitive_type"], {"token", "password"})

    def test_build_code_hit_detail_rebuilds_preview_and_context_from_snapshot_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            html_path = output_root / "code_monitoring" / "watchlist" / "github" / "DBS.com" / "AutoMoneyCollection-app.py.html"
            artifact_path = output_root / "code_monitoring" / "watchlist" / "github" / "DBS.com" / "AutoMoneyCollection-app.py.json"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(
                """
                <html><body>
                <div id="LC31" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
                  <span class="pl-s">'password'</span> : <span class="pl-s1">PASSWORD</span> ,
                </div>
                <div id="LC32" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
                  <span class="pl-s">'search_query'</span> : [ <span class="pl-s">'FROM'</span> , <span class="pl-s">'ibanking.alert@dbs.com'</span> , <span class="pl-s">'SUBJECT'</span> , <span class="pl-s">'Transaction Alerts'</span> , <span class="pl-s">'SINCE'</span> , <span class="pl-s1">collection_date</span> ],
                </div>
                <div id="LC33" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
                  <span class="pl-s">'output_file_path'</span> : <span class="pl-s">f'{{excel_filename}}.xlsx'</span>
                </div>
                </body></html>
                """,
                encoding="utf-8",
            )
            artifact_path.write_text(
                json.dumps(
                    {
                        "candidate": {
                            "platform": "github",
                            "platformLabel": "GitHub",
                            "fileUrl": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                            "title": "app.py",
                            "repositoryOwner": "keithgzx",
                            "repositoryName": "AutoMoneyCollection",
                            "repositoryUrl": "https://github.com/keithgzx/AutoMoneyCollection",
                            "branch": "main",
                            "filePath": "app.py",
                            "lineStart": 32,
                            "lineEnd": 32,
                        },
                        "findings": [
                            {
                                "ruleKey": "password",
                                "label": "账号口令",
                                "secretLike": True,
                                "weight": 20,
                                "start": 100,
                                "end": 121,
                                "value": "PASSWORD = os.getenv(",
                                "excerpt": "PASSWORD = os.getenv(",
                            }
                        ],
                        "code_fragment": "featureFlags and layout shell noise",
                        "masked_fragment": "featureFlags and layout shell noise",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "星展银行",
                        "organization_name": "星展银行",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["py"],
                        "detail_fetch": True,
                        "enabled_rule_keys": ["password"],
                        "terms": [
                            {"term": "DBS.com", "term_type": "domain", "enabled": True},
                        ],
                    }
                )

                with get_db_connection() as connection:
                    hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "AutoMoneyCollection",
                            "repository_owner": "keithgzx",
                            "repository_url": "https://github.com/keithgzx/AutoMoneyCollection",
                            "file_path": "app.py",
                            "branch": "main",
                            "file_url": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                            "visibility": "public",
                            "language": "Python",
                            "sensitive_type": "password",
                            "matched_rule": "账号口令",
                            "matched_term": "DBS.com",
                            "risk_score": 10,
                            "severity": "low",
                            "first_seen_at": "2026-06-10T00:00:00+00:00",
                            "last_seen_at": "2026-06-10T00:00:00+00:00",
                            "raw_json": json.dumps(
                                {
                                    "candidate": {
                                        "platform": "github",
                                        "platformLabel": "GitHub",
                                        "fileUrl": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                                        "title": "app.py",
                                        "repositoryOwner": "keithgzx",
                                        "repositoryName": "AutoMoneyCollection",
                                        "repositoryUrl": "https://github.com/keithgzx/AutoMoneyCollection",
                                        "branch": "main",
                                        "filePath": "app.py",
                                        "lineStart": 32,
                                        "lineEnd": 32,
                                    },
                                    "masked_fragment": "featureFlags and layout shell noise",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    snapshot_id = insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-10T00:00:00+00:00",
                            "search_url": "https://github.com/search?q=DBS.com&type=code",
                            "page_url": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                            "html_path": str(html_path),
                            "screenshot_path": "",
                            "code_fragment": "featureFlags and layout shell noise",
                            "masked_fragment": "featureFlags and layout shell noise",
                            "raw_artifact_path": str(artifact_path),
                            "line_start": 32,
                            "line_end": 32,
                            "language": "Python",
                            "findings_json": json.dumps(
                                [
                                    {
                                        "ruleKey": "password",
                                        "label": "账号口令",
                                        "secretLike": True,
                                        "weight": 20,
                                        "start": 100,
                                        "end": 121,
                                        "value": "PASSWORD = os.getenv(",
                                        "excerpt": "PASSWORD = os.getenv(",
                                    }
                                ],
                                ensure_ascii=False,
                            ),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    update_code_hit_last_snapshot(connection, hit_id, snapshot_id)
                    connection.commit()

                detail = build_code_hit_detail(int(hit_id))

                self.assertIn("ibanking.alert@dbs.com", detail["codePreview"])
                self.assertNotIn("featureFlags", detail["codePreview"])
                self.assertLessEqual(len(detail["codePreview"].splitlines()), 3)
                self.assertTrue(detail["matchedTermContexts"])
                self.assertIn("ibanking.alert@dbs.com", detail["matchedTermContexts"][0]["text"])
                self.assertEqual(31, detail["matchedTermContexts"][0]["lineStart"])
                self.assertEqual(33, detail["matchedTermContexts"][0]["lineEnd"])


if __name__ == "__main__":
    unittest.main()
