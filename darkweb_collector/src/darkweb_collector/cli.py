from __future__ import annotations

from argparse import ArgumentParser
import json
import subprocess
import sys
import time

from darkweb_collector.config import get_site_config, load_site_configs
from darkweb_collector.orchestrator import enqueue_due_sites, run_site_once, show_runs
from darkweb_collector.public_vulnerabilities import sync_public_vulnerability_feed
from darkweb_collector.queueing import build_worker_command, queue_for_seed
from darkweb_collector.ransomware_live import sync_ransomware_live_victims
from darkweb_collector.state_store import get_state_store


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="crawl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-sites")

    run_site_parser = subparsers.add_parser("run-site")
    run_site_parser.add_argument("--site", required=True)
    run_site_parser.add_argument("--once", action="store_true")
    run_site_parser.add_argument("--continuous", action="store_true")
    run_site_parser.add_argument("--interval-seconds", type=int, default=None)

    subparsers.add_parser("enqueue-due")

    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--queue", required=True)

    show_runs_parser = subparsers.add_parser("show-runs")
    show_runs_parser.add_argument("--limit", type=int, default=20)

    sync_vulns_parser = subparsers.add_parser("sync-public-vulns")
    sync_vulns_parser.add_argument("--sample-file", default=None)
    sync_vulns_parser.add_argument("--limit", type=int, default=300)

    sync_ransomware_parser = subparsers.add_parser("sync-ransomware-live")
    sync_ransomware_parser.add_argument("--limit", type=int, default=0)

    return parser


def _run_list_sites() -> int:
    rows = []
    for config in load_site_configs():
        rows.append(
            {
                "site_name": config.site_name,
                "enabled": config.enabled,
                "profile": config.profile,
                "seed_fetch_mode": config.seed_fetch_mode,
                "detail_fetch_mode": config.detail_fetch_mode,
                "seed_urls": list(config.seed_urls),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def _run_site_once(site_name: str) -> int:
    result = run_site_once(site_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_site_continuous(site_name: str, interval_seconds: int | None) -> int:
    config = get_site_config(site_name)
    sleep_seconds = interval_seconds or config.effective_interval_seconds
    while True:
        result = run_site_once(site_name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "site_name": site_name,
                    "next_run_in_seconds": sleep_seconds,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        time.sleep(sleep_seconds)


def _enqueue_due() -> int:
    try:
        from darkweb_collector.tasks import crawl_seed
    except ImportError as exc:
        raise RuntimeError("Celery is required to enqueue queued crawl jobs") from exc

    def seed_dispatcher(config) -> str | None:
        queue_name = queue_for_seed(config.seed_fetch_mode)
        async_result = crawl_seed.apply_async(
            kwargs={"site_name": config.site_name, "force": False},
            queue=queue_name,
        )
        return str(async_result.id)

    dispatched = enqueue_due_sites(seed_dispatcher=seed_dispatcher, state_store=get_state_store(prefer_redis=True))
    print(json.dumps(dispatched, ensure_ascii=False, indent=2))
    return 0


def _run_worker(queue_name: str) -> int:
    command = build_worker_command(queue_name)
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def _show_runs(limit: int) -> int:
    print(json.dumps(show_runs(limit=limit), ensure_ascii=False, indent=2))
    return 0


def _sync_public_vulns(sample_file: str | None, limit: int) -> int:
    print(json.dumps(sync_public_vulnerability_feed(sample_file=sample_file, limit=limit), ensure_ascii=False, indent=2))
    return 0


def _sync_ransomware_live(limit: int) -> int:
    print(json.dumps(sync_ransomware_live_victims(limit=limit), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list-sites":
        return _run_list_sites()
    if args.command == "run-site":
        if args.once and args.continuous:
            parser.error("run-site cannot use --once and --continuous together")
        if args.continuous:
            return _run_site_continuous(args.site, args.interval_seconds)
        if args.once:
            return _run_site_once(args.site)
        parser.error("run-site requires either --once or --continuous")
    if args.command == "enqueue-due":
        return _enqueue_due()
    if args.command == "worker":
        return _run_worker(args.queue)
    if args.command == "show-runs":
        return _show_runs(args.limit)
    if args.command == "sync-public-vulns":
        return _sync_public_vulns(args.sample_file, args.limit)
    if args.command == "sync-ransomware-live":
        return _sync_ransomware_live(args.limit)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
