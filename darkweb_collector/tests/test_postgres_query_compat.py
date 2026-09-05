from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import intelligence_aggregates, intelligence_queries
from darkweb_collector.postgres_backend import CompatRow, translate_sql


class FixtureCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class PostgreSQLDataLeakFixture:
    backend_name = "postgresql"

    def __init__(self):
        self.statements: list[str] = []

    def execute(self, sql, _parameters=()):
        statement = translate_sql(str(sql))
        parameters = tuple(_parameters or ())
        try:
            statement % parameters
        except (IndexError, TypeError, ValueError) as exc:
            raise AssertionError(f"invalid psycopg2 percent formatting: {statement}") from exc
        self.statements.append(statement)
        if "SELECT COUNT(*)" in statement and "GROUP BY" not in statement:
            return FixtureCursor([(0,)])
        return FixtureCursor()

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class PostgreSQLThreatFixture:
    backend_name = "postgresql"

    def __init__(self):
        self.statements: list[str] = []

    def execute(self, sql, _parameters=()):
        statement = str(sql)
        self.statements.append(statement)
        if "AS eventCount" in statement or "AS averageRiskScore" in statement:
            raise AssertionError("camelCase PostgreSQL aliases must be quoted")
        if 'AS "eventCount"' in statement:
            return FixtureCursor(
                [CompatRow(("name", "eventCount", "highRiskCount", "averageRiskScore"), ("中国", 3, 2, 80))]
            )
        if 'AS "averageRiskScore"' in statement and "attacker AS actor" in statement:
            return FixtureCursor(
                [CompatRow(("actor", "value", "averageRiskScore"), ("fixture-actor", 2, 75))]
            )
        if "SELECT\n                    SUM(CASE" in statement:
            return FixtureCursor([(0, 0, 0, 0)])
        if "SELECT COUNT(*)," in statement and "FROM normalized_intelligence_events" in statement:
            return FixtureCursor([(0, 0, 0, 0)])
        if "SELECT LEAST(500, COUNT(*))" in statement:
            return FixtureCursor([(0,)])
        return FixtureCursor()

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class PostgreSQLQueryCompatibilityTests(unittest.TestCase):
    def test_data_leak_distinct_lists_use_grouped_postgres_order(self) -> None:
        connection = PostgreSQLDataLeakFixture()
        with patch.object(
            intelligence_queries,
            "get_readonly_db_connection",
            return_value=connection,
        ):
            payload = intelligence_queries.build_data_leak_page()

        self.assertEqual(0, payload["total"])
        combined = "\n".join(connection.statements)
        self.assertNotIn("SELECT DISTINCT category", combined)
        for column in ("category", "attacker", "industry"):
            self.assertIn(f"GROUP BY {column}", combined)
            self.assertIn(f"ORDER BY LOWER({column})", combined)

    def test_threat_aliases_survive_postgres_identifier_folding(self) -> None:
        connection = PostgreSQLThreatFixture()
        monitoring = {
            "monitoringConfigurationSummary": {},
            "monitoringPriorityQueue": [],
            "monitoringKeywordStats": {"keywords": [], "categories": []},
            "sampleEvidenceAlerts": [],
            "priorityAlertStream": [],
            "analysisSnapshot": {},
        }
        with patch.object(
            intelligence_aggregates,
            "get_readonly_db_connection",
            return_value=connection,
        ), patch.object(
            intelligence_aggregates,
            "_monitoring_snapshot",
            return_value=monitoring,
        ), patch.object(
            intelligence_aggregates,
            "aggregate_revision",
            return_value="fixture-revision",
        ), patch.object(
            intelligence_aggregates,
            "_cache_get",
            return_value=None,
        ), patch.object(
            intelligence_aggregates,
            "_cache_set",
            side_effect=lambda _namespace, _key, payload: payload,
        ), patch.object(
            intelligence_aggregates,
            "_severity_counts",
            return_value=Counter(),
        ), patch.object(
            intelligence_aggregates,
            "_normalized_events",
            return_value=[],
        ), patch.object(
            intelligence_aggregates,
            "_vulnerability_events",
            return_value=[],
        ), patch.object(
            intelligence_aggregates,
            "_document_events",
            return_value=[],
        ):
            payload = intelligence_aggregates.build_threat_situation(days=1)

        self.assertEqual(3, payload["threatExecutiveCountries"][0]["eventCount"])
        self.assertEqual(
            75,
            payload["threatExecutiveActiveActors"][0]["averageRiskScore"],
        )
        combined = "\n".join(connection.statements)
        self.assertIn('AS "eventCount"', combined)
        self.assertIn('AS "averageRiskScore"', combined)


if __name__ == "__main__":
    unittest.main()
