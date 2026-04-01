#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import sys


SAMPLE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SAMPLE_DIR.parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.detail_extract import parse_generic_detail
from darkweb_collector.pipeline import persist_run
from darkweb_collector.sites.registry import get_parser


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_manifest_entry(manifest: dict, entry: dict) -> dict:
    file_path = SAMPLE_DIR / entry["file"]
    html = file_path.read_text(encoding="utf-8")
    output_path = SAMPLE_DIR / entry["output_json"]
    page_type = entry["page_type"]

    if page_type == "list":
        parser = get_parser(manifest["parser"])
        parsed = parser(entry["source_url"], html)
        save_json(output_path, parsed)
        return {
            "file": entry["file"],
            "page_type": page_type,
            "output_json": str(output_path),
            "victim_count": parsed["victim_count"],
            "parsed": parsed,
        }

    if page_type == "detail":
        parsed = parse_generic_detail(entry["source_url"], html)
        save_json(output_path, parsed)
        return {
            "file": entry["file"],
            "page_type": page_type,
            "output_json": str(output_path),
            "detail_status": parsed["fetch_status"],
            "page_title": parsed["page_title"],
            "parsed": parsed,
        }

    raise ValueError(f"unsupported page_type: {page_type}")


def validate_expectations(results: list[dict], expected: dict) -> list[str]:
    errors: list[str] = []
    result_by_file = {result["file"]: result for result in results}

    for page in expected.get("pages", []):
        result = result_by_file.get(page["file"])
        if not result:
            errors.append(f"missing result for {page['file']}")
            continue
        parsed = result.get("parsed", {})
        actual_count = parsed.get("victim_count")
        if actual_count != page["expected_victim_count"]:
            errors.append(
                f"{page['file']}: expected_victim_count={page['expected_victim_count']} actual={actual_count}"
            )

        victims = parsed.get("victims", [])
        for item in page.get("items", []):
            matched = any(
                victim.get("name") == item["name"]
                and victim.get("domain") == item["domain"]
                and victim.get("published_at_utc") == item["publicated_time"]
                for victim in victims
            )
            if not matched:
                errors.append(
                    f"{page['file']}: missing expected item name={item['name']} "
                    f"domain={item['domain']} publicated_time={item['publicated_time']}"
                )
    return errors


def main() -> int:
    manifest_path = SAMPLE_DIR / "manifest.json"
    expected_path = SAMPLE_DIR / "expected.json"
    manifest = load_json(manifest_path)
    expected = load_json(expected_path)

    results: list[dict] = []
    db_path = SAMPLE_DIR / manifest["db_path"]
    for entry in manifest["entries"]:
        result = parse_manifest_entry(manifest, entry)
        results.append(result)
        if entry["page_type"] == "list":
            persist_run(db_path, result["parsed"])

    errors = validate_expectations(results, expected)
    summary = {
        "site_name": manifest["site_name"],
        "db_path": str(db_path),
        "results": [
            {
                key: value
                for key, value in result.items()
                if key != "parsed"
            }
            for result in results
        ],
        "validation": {
            "ok": not errors,
            "errors": errors,
        },
    }
    save_json(SAMPLE_DIR / "results" / "run_summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
