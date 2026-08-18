# Queue Workflow

## Install

```bash
pip install -r requirements.txt
```

## Start Redis

Run Redis locally and expose `REDIS_URL`, for example:

```bash
export REDIS_URL=redis://127.0.0.1:6379/0
```

## Common Commands

List configured sites:

```bash
python scripts/crawl.py list-sites
```

Run one site inline without Celery:

```bash
python scripts/crawl.py run-site --site dragonforce --once
```

Enqueue all due seed jobs:

```bash
python scripts/crawl.py enqueue-due
```

Start workers:

```bash
python scripts/crawl.py worker --queue seed_http
python scripts/crawl.py worker --queue detail_http
python scripts/crawl.py worker --queue browser_render
```

Inspect recent run records:

```bash
python scripts/crawl.py show-runs --limit 20
```

## Notes

- Site definitions live in `sites.yaml`.
- Results and run audit rows share the same SQLite database.
- Browser tasks are isolated in `browser_render` and capped with a single worker process.
