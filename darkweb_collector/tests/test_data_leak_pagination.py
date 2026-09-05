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

from darkweb_collector.api_data import build_data_leak_page
from darkweb_collector.db import get_db_connection, replace_normalized_intelligence_events


class DataLeakPaginationTests(unittest.TestCase):
    def _normalized_row(
        self,
        *,
        event_id: str,
        title: str,
        category: str,
        disclosure_time: str,
        attacker: str = "actor",
        victim: str = "未知实体",
        region: str = "asia",
        event_type: str = "data_leak",
    ) -> dict:
        return {
            "event_id": event_id,
            "source_kind": event_type,
            "raw_source_type": "forum_details",
            "source_site_name": "test",
            "source_record_id": 1,
            "event_type": event_type,
            "category": category,
            "leak_type": "database",
            "title": title,
            "attacker": attacker,
            "victim": victim,
            "victim_key": victim.lower().replace(" ", "-"),
            "industry": "technology",
            "region": region,
            "disclosure_time": disclosure_time,
            "severity": "high",
            "risk_score": 80,
            "source_url": f"https://example.invalid/{event_id}",
            "detail_text": f"{title} detail",
            "mirror_resources_json": "[]",
            "screenshot_resources_json": "[]",
            "json_preview_url": "",
            "risk_reasons_json": "[]",
            "event_metadata_json": json.dumps(
                {"country": "中国", "country_code": "CN"},
                ensure_ascii=False,
            ),
            "updated_at": disclosure_time,
        }

    def test_page_returns_stable_rows_and_full_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            rows = [
                self._normalized_row(
                    event_id="forum:test:databases:003",
                    title="Newest database leak",
                    category="数据库泄露",
                    disclosure_time="2026-07-29T03:00:00+00:00",
                    victim="Acme",
                ),
                self._normalized_row(
                    event_id="forum:test:credentials:002",
                    title="Credential collection",
                    category="凭证泄露",
                    disclosure_time="2026-07-29T02:00:00+00:00",
                    victim="Beta",
                ),
                self._normalized_row(
                    event_id="forum:test:databases:001",
                    title="Older database leak",
                    category="数据库泄露",
                    disclosure_time="2026-07-29T01:00:00+00:00",
                ),
                self._normalized_row(
                    event_id="victim:test:001",
                    title="Ransomware victim",
                    category="已公开",
                    disclosure_time="2026-07-29T04:00:00+00:00",
                    event_type="ransomware",
                ),
            ]

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with get_db_connection() as connection:
                    replace_normalized_intelligence_events(connection, rows)
                    connection.commit()

                payload = build_data_leak_page(page=1, page_size=2)

            self.assertEqual(3, payload["total"])
            self.assertEqual(2, payload["totalPages"])
            self.assertEqual(["凭证泄露", "数据库泄露"], payload["categories"])
            self.assertEqual(
                ["forum:test:databases:003", "forum:test:credentials:002"],
                [item["id"] for item in payload["items"]],
            )
            self.assertEqual("3", payload["summary"][0]["value"])
            self.assertEqual("2", payload["summary"][1]["value"])
            self.assertEqual("2", payload["summary"][2]["value"])

    def test_filters_and_clamps_page_without_matching_other_event_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            rows = [
                self._normalized_row(
                    event_id="forum:test:databases:002",
                    title="Finance records",
                    category="数据库泄露",
                    disclosure_time="2026-07-29T02:00:00+00:00",
                    attacker="seller-a",
                ),
                self._normalized_row(
                    event_id="forum:test:credentials:001",
                    title="Credential records",
                    category="凭证泄露",
                    disclosure_time="2026-07-29T01:00:00+00:00",
                    attacker="seller-b",
                ),
                self._normalized_row(
                    event_id="victim:test:001",
                    title="Finance ransomware",
                    category="已公开",
                    disclosure_time="2026-07-29T03:00:00+00:00",
                    event_type="ransomware",
                ),
            ]

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with get_db_connection() as connection:
                    replace_normalized_intelligence_events(connection, rows)
                    connection.commit()

                payload = build_data_leak_page(
                    page=99,
                    page_size=1,
                    keyword="finance",
                    category="数据库泄露",
                )

            self.assertEqual(1, payload["page"])
            self.assertEqual(1, payload["total"])
            self.assertEqual("2", payload["summary"][0]["value"])
            self.assertEqual(["forum:test:databases:002"], [item["id"] for item in payload["items"]])


if __name__ == "__main__":
    unittest.main()
