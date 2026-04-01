from __future__ import annotations

from pathlib import Path

from darkweb_collector.db import connect, insert_collection_run, insert_victim_detail, upsert_victim


def persist_run(db_path: Path, parsed: dict) -> Path:
    connection = connect(db_path)
    try:
        run_id = insert_collection_run(connection, parsed)
        for victim in parsed["victims"]:
            victim_id = upsert_victim(connection, run_id, victim)
            if "detail" in victim:
                insert_victim_detail(connection, victim_id, victim["detail"])
            elif victim.get("detail_error"):
                insert_victim_detail(
                    connection,
                    victim_id,
                    {
                        "fetched_at_utc": parsed["collected_at_utc"],
                        "fetch_status": victim["last_detail_fetch_status"],
                        "page_title": None,
                        "text_excerpt": victim["detail_error"][:1000],
                        "outbound_link_count": 0,
                    },
                )
        connection.commit()
    finally:
        connection.close()
    return db_path
