#!/usr/bin/env python3
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.pipeline import persist_run
from darkweb_collector.sites.registry import get_parser


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Import a local HTML sample and parse it into SQLite.")
    parser.add_argument("--site", required=True, help="Parser name, for example: dragonforce")
    parser.add_argument("--input", required=True, help="Path to the local HTML file")
    parser.add_argument("--source-url", required=True, help="Original page URL represented by the HTML sample")
    parser.add_argument(
        "--db-path",
        default=str(ROOT / "data" / "collector.db"),
        help="SQLite path, defaults to darkweb_collector/data/collector.db",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write parsed JSON",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    html_path = Path(args.input).resolve()
    db_path = Path(args.db_path).resolve()
    output_json = Path(args.output_json).resolve() if args.output_json else None

    parser = get_parser(args.site)
    html = html_path.read_text(encoding="utf-8")
    parsed = parser(args.source_url, html)
    persist_run(db_path, parsed)

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Imported HTML sample: {html_path}")
    print(f"Parser: {args.site}")
    print(f"Saved SQLite DB to: {db_path}")
    if output_json:
        print(f"Saved parsed JSON to: {output_json}")
    print(
        json.dumps(
            {
                "site_name": parsed["site_name"],
                "title": parsed["title"],
                "victim_count": parsed["victim_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
