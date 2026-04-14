from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.db import get_db_connection, upsert_crawl_job
from darkweb_collector.models import DetailTask
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
from darkweb_collector.orchestrator import run_detail_job_once
from darkweb_collector.utils import safe_stem, utc_now_iso


SITE_NAME = "lynx"


def _latest_detail_rows(connection: sqlite3.Connection, detail_url: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT v.id, v.name, v.display_label, v.detail_url, v.domain, v.status, v.source_url,
               v.content_hash, v.last_detail_fetch_status,
               vd.id AS detail_id, vd.text_excerpt, vd.fetched_at_utc
        FROM victims v
        LEFT JOIN victim_details vd
          ON vd.id = (
            SELECT vd2.id
            FROM victim_details vd2
            WHERE vd2.victim_id = v.id
            ORDER BY datetime(vd2.fetched_at_utc) DESC, vd2.id DESC
            LIMIT 1
          )
        WHERE v.site_name = ? AND v.detail_url = ?
        ORDER BY v.id DESC
        """,
        (SITE_NAME, detail_url),
    ).fetchall()


def _name_looks_like_description(value: str) -> bool:
    lowered = (value or "").lower()
    return len(lowered) > 80 or any(token in lowered for token in (" is a ", " based in ", " operating ", " leading "))


def _choose_winner(rows: list[sqlite3.Row], *, canonical_name: str, canonical_domain: str) -> sqlite3.Row:
    def score(row: sqlite3.Row) -> tuple[int, int]:
        score_value = 0
        row_name = str(row["name"] or "")
        row_domain = str(row["domain"] or "")
        if row_name == canonical_name:
            score_value += 200
        if row_name.lower() == canonical_name.lower():
            score_value += 40
        if canonical_domain and row_domain.lower() == canonical_domain.lower():
            score_value += 80
        if row["last_detail_fetch_status"] == "ok":
            score_value += 50
        if row["detail_id"] and str(row["text_excerpt"] or "").strip():
            score_value += 60
        if _name_looks_like_description(row_name):
            score_value -= 120
        return score_value, int(row["id"])

    return max(rows, key=score)


def _load_latest_mapping() -> dict[str, dict[str, str]]:
    latest_path = ROOT / "output" / SITE_NAME / "latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    mapping: dict[str, dict[str, str]] = {}
    for victim in payload.get("victims", []):
        detail_url = str(victim.get("detail_url") or "").strip()
        if not detail_url:
            continue
        mapping[detail_url] = {
            "name": str(victim.get("name") or "").strip(),
            "domain": str(victim.get("domain") or "").strip(),
            "status": str(victim.get("status") or "active"),
            "source_url": str(victim.get("source_url") or detail_url),
        }
    return mapping


def main() -> int:
    latest_mapping = _load_latest_mapping()
    blocker_job_id = f"manual-repair-{SITE_NAME}-{int(time.time())}"

    with get_db_connection() as connection:
        upsert_crawl_job(
            connection,
            job_id=blocker_job_id,
            site_name=SITE_NAME,
            job_type="seed",
            queue_name="manual",
            target=SITE_NAME,
            status="running",
            started_at=utc_now_iso(),
        )
        connection.commit()

    deleted_victims = 0
    deleted_detail_rows = 0
    repaired_details = 0

    try:
        with get_db_connection() as connection:
            for detail_url, canonical in latest_mapping.items():
                rows = _latest_detail_rows(connection, detail_url)
                if len(rows) <= 1:
                    continue
                winner = _choose_winner(
                    rows,
                    canonical_name=canonical["name"],
                    canonical_domain=canonical["domain"],
                )
                delete_ids = [int(row["id"]) for row in rows if int(row["id"]) != int(winner["id"])]
                if not delete_ids:
                    continue
                deleted_detail_rows += connection.execute(
                    f"DELETE FROM victim_details WHERE victim_id IN ({','.join('?' for _ in delete_ids)})",
                    delete_ids,
                ).rowcount
                deleted_victims += connection.execute(
                    f"DELETE FROM victims WHERE id IN ({','.join('?' for _ in delete_ids)})",
                    delete_ids,
                ).rowcount
            connection.commit()

        with get_db_connection() as connection:
            for detail_url, canonical in latest_mapping.items():
                winner_rows = _latest_detail_rows(connection, detail_url)
                if not winner_rows:
                    continue
                winner = _choose_winner(
                    winner_rows,
                    canonical_name=canonical["name"],
                    canonical_domain=canonical["domain"],
                )
                if winner["detail_id"] and str(winner["text_excerpt"] or "").strip():
                    continue
                metadata = {
                    "source_url": canonical["source_url"],
                    "name": canonical["name"],
                    "domain": canonical["domain"],
                    "status": canonical["status"],
                    "artifact_stem": safe_stem(
                        f"{str(winner['content_hash'] or '')[:10]}_{canonical['domain'] or canonical['name']}"
                    ),
                }
                task = DetailTask(site_name=SITE_NAME, target_url=detail_url, metadata=metadata)
                run_detail_job_once(SITE_NAME, task)
                repaired_details += 1

        with get_db_connection() as connection:
            events = ensure_normalized_intelligence(connection, force=True)
            remaining_missing = connection.execute(
                """
                SELECT COUNT(*)
                FROM victims v
                LEFT JOIN victim_details vd
                  ON vd.id = (
                    SELECT vd2.id
                    FROM victim_details vd2
                    WHERE vd2.victim_id = v.id
                    ORDER BY datetime(vd2.fetched_at_utc) DESC, vd2.id DESC
                    LIMIT 1
                  )
                WHERE v.site_name = ?
                  AND (vd.id IS NULL OR ifnull(vd.text_excerpt, '') = '')
                """,
                (SITE_NAME,),
            ).fetchone()[0]
            upsert_crawl_job(
                connection,
                job_id=blocker_job_id,
                site_name=SITE_NAME,
                job_type="seed",
                queue_name="manual",
                target=SITE_NAME,
                status="failed",
                finished_at=utc_now_iso(),
                duration_ms=0,
                error_message="manual lynx repair blocker cleared",
            )
            connection.commit()

        print(
            json.dumps(
                {
                    "site_name": SITE_NAME,
                    "deleted_victims": deleted_victims,
                    "deleted_detail_rows": deleted_detail_rows,
                    "repaired_details": repaired_details,
                    "remaining_missing": int(remaining_missing),
                    "normalized_events": len(events),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception:
        with get_db_connection() as connection:
            upsert_crawl_job(
                connection,
                job_id=blocker_job_id,
                site_name=SITE_NAME,
                job_type="seed",
                queue_name="manual",
                target=SITE_NAME,
                status="failed",
                finished_at=utc_now_iso(),
                duration_ms=0,
                error_message="manual lynx repair aborted",
            )
            connection.commit()
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
