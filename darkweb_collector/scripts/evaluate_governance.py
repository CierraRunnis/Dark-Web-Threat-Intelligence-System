from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.evaluation import evaluate_against_gold, load_gold_samples


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate automated governance rules against a gold sample set.")
    parser.add_argument("--input", required=True, help="Path to a JSON file containing labeled samples.")
    parser.add_argument("--refresh", action="store_true", help="Force refresh normalized intelligence before evaluation.")
    args = parser.parse_args()

    samples = load_gold_samples(args.input)
    result = evaluate_against_gold(samples, refresh=args.refresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
