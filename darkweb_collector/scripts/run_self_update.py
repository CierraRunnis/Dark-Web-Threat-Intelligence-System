#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.self_update import run_self_update


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a safe in-place project update")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()
    run_self_update(args.job_id, args.branch, args.remote)


if __name__ == "__main__":
    main()
