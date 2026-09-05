from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPTS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SCRIPT_PATH = SCRIPTS / "benchmark_postgres_write_ablation.py"
SPEC = importlib.util.spec_from_file_location("dwti_write_ablation", SCRIPT_PATH)
assert SPEC and SPEC.loader
ablation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ablation
SPEC.loader.exec_module(ablation)


class _Cursor:
    pass


class _Connection:
    identity_tables = frozenset({"crawl_jobs"})
    schema = "dwti_fixture"
    read_only = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def execute(self, sql_text, parameters=None, *, return_identity=False):
        self.calls.append((sql_text, return_identity))
        return _Cursor()

    def executemany(self, sql_text, parameters):
        return _Cursor()

    def execute_values(self, sql_text, parameters, *, template=None, page_size=500):
        return _Cursor()

    def cursor(self):
        return _Cursor()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    @property
    def closed(self) -> bool:
        return False


def test_cli_defaults_cover_all_isolated_candidates(tmp_path: Path) -> None:
    args = ablation.build_parser().parse_args([
        "--source-schema", "dwti_source",
        "--output", str(tmp_path / "report.json"),
    ])
    assert args.concurrency == 8
    assert args.warmups == 5
    assert args.iterations == 100
    assert args.rounds == 3
    assert args.explain_rows == 512
    assert args.ablations == ablation.ABLATIONS
    assert ablation.VARIANTS == {
        "checkout_session": ("double_session", "single_session"),
        "job_identity": ("auto_returning", "no_returning"),
        "claim_sql": ("exception_rollback", "on_conflict_returning"),
        "crawl_jobs_index": ("old_index", "new_index"),
        "crawl_jobs_drop_wrong": ("old_index", "drop_only"),
        "crawl_jobs_read_index": ("without_recency_index", "recency_index"),
    }


def test_cli_accepts_subset_and_rejects_unknown() -> None:
    assert ablation._selected_ablations("claim_sql,checkout_session") == (
        "claim_sql", "checkout_session",
    )
    with pytest.raises(Exception):
        ablation._selected_ablations("")
    with pytest.raises(Exception):
        ablation._selected_ablations("claim_sql,unknown")


def test_auto_identity_wrapper_changes_only_default_identity_inserts() -> None:
    raw = _Connection()
    connection = ablation._AutoIdentityConnection(raw)
    connection.execute("INSERT INTO crawl_jobs(job_id) VALUES (?)", ("a",))
    connection.execute(
        "INSERT INTO crawl_jobs(job_id) VALUES (?)",
        ("b",),
        return_identity=False,
    )
    connection.execute(
        "INSERT INTO ai_aggregation_schedule_claims(profile_id) VALUES (?)",
        ("c",),
    )
    assert [capture for _sql, capture in raw.calls] == [True, False, False]


def test_plan_index_names_walks_nested_json_without_duplicates() -> None:
    plan = [{
        "Plan": {
            "Node Type": "Limit",
            "Plans": [
                {"Node Type": "Index Scan", "Index Name": "idx_new"},
                {
                    "Node Type": "Nested Loop",
                    "Plans": [
                        {"Node Type": "Index Only Scan", "Index Name": "idx_other"},
                        {"Node Type": "Index Scan", "Index Name": "idx_new"},
                    ],
                },
            ],
        },
    }]
    assert ablation._plan_index_names(plan) == ["idx_new", "idx_other"]


def test_source_fingerprint_requires_version_and_baseline_identity() -> None:
    snapshot = {
        "summary": {
            "migrations": [
                ("0001_baseline", "checksum", "fingerprint"),
                ("0004_performance_indexes", "checksum-4", ""),
            ],
        },
    }
    assert (
        ablation._source_fingerprint(snapshot, "0004_performance_indexes")
        == "fingerprint"
    )
    with pytest.raises(ablation.WriteBenchmarkError, match="missing"):
        ablation._source_fingerprint(snapshot, "0005_postgres_write_paths")
    snapshot["summary"]["migrations"][0] = ("0001_baseline", "checksum", "")
    with pytest.raises(ablation.WriteBenchmarkError, match="fingerprint"):
        ablation._source_fingerprint(snapshot, "0004_performance_indexes")


def test_index_ablation_contains_real_query_and_exact_predicates() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "WHERE status IN ('queued', 'running')" in source
    assert "WHERE status IN ('enqueued', 'running')" in source
    assert "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in source
    assert "WHERE site_name=? AND job_type=?" in source
    assert "ORDER BY COALESCE(started_at, enqueued_at) DESC" in source
    assert "same_single_session_connector" in source
    assert "no_identity_returning" in source
    assert "((COALESCE(finished_at, started_at, enqueued_at)) DESC)" in source
    assert '"jobs_payload_300"' in source
    assert "SELECT MAX(COALESCE(finished_at, started_at, enqueued_at)) AS latest" in source
    assert '"same_timestamp_ordering"' in source
    assert "LIMIT 300" in source
