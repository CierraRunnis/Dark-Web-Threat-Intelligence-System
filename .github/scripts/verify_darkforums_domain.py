from __future__ import annotations

from pathlib import Path
import tempfile

from darkweb_collector.adapters import darkforums as adapter_module
from darkweb_collector.models import DetailTask, RunContext, SiteConfig
from darkweb_collector.sites.darkforums import FORUM_SECTIONS, parse_darkforums_detail, parse_darkforums_list


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_HOST = "darkforums.as"
LIST_HTML = """
<html><title>Databases</title><body>
  <a href="Forum-Databases">Databases</a>
  <span class="subject_new" id="tid_42"><a href="Thread-Acme-Database">Acme Database</a></span>
</body></html>
"""
DETAIL_HTML = """
<html><title>Acme Database</title><body><div id="posts">
  <div class="post classic post_42" id="post_42">
    <a class="username">tester</a>
    <span class="post_date">28-08-2026, 08:10 PM</span>
    <div class="post_body">Victim: Acme. Database archive is available.</div><div class="post_meta"></div>
  </div><!-- end: postbit_classic -->
</div></body></html>
"""


for relative_path in (
    Path("darkweb_collector/sites.yaml"),
    Path("darkweb_collector/src/darkweb_collector/sites/darkforums.py"),
    Path("darkweb_collector/README.md"),
):
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "darkforums.ru" not in source, relative_path

assert set(FORUM_SECTIONS) == {"databases", "other_leaks", "sellers_place"}
assert all(url.startswith(f"https://{EXPECTED_HOST}/Forum-") for url in FORUM_SECTIONS.values())

list_payload = parse_darkforums_list(FORUM_SECTIONS["databases"], LIST_HTML, max_topics=1)
assert list_payload["topic_count"] == 1
assert list_payload["topics"][0]["full_url"] == f"https://{EXPECTED_HOST}/Thread-Acme-Database"

detail_url = f"https://{EXPECTED_HOST}/Thread-Acme-Database"
detail_payload = parse_darkforums_detail(detail_url, DETAIL_HTML)
assert detail_payload["domain"] == EXPECTED_HOST
assert detail_payload["author"] == "tester"
assert "Database archive" in detail_payload["content"]

config = SiteConfig(
    site_name="darkforums",
    enabled=True,
    seed_urls=tuple(FORUM_SECTIONS.values()),
    seed_fetch_mode="browser",
    detail_fetch_mode="browser",
    profile="warm",
    max_topics_per_run=1,
    max_detail_pages_per_run=1,
    cooldown_seconds=60,
    output_dir=Path(tempfile.gettempdir()) / "darkforums-test-output",
    dedupe_window_minutes=60,
    extras={"fetch_timeout_seconds": 5, "render_wait_seconds": 0},
)
run_context = RunContext(
    job_id="darkforums-domain-test",
    job_type="detail",
    queue_name="detail",
    target=detail_url,
    started_at_utc="2026-08-29T00:00:00+00:00",
)
task = DetailTask(site_name="darkforums", target_url=detail_url, metadata={"section": "databases"})
adapter = adapter_module.DarkforumsAdapter()

calls: list[tuple[str, bool]] = []
original_direct = adapter_module.fetch_via_http_proxy
original_seed_fallback = adapter_module.fetch_url
original_detail_fallback = adapter_module.fetch_page_artifacts
original_screenshot = adapter_module.screenshot_html_with_browser


def direct_success(_url, *, bypass_proxy=False, **_kwargs):
    calls.append(("direct", bypass_proxy))
    return LIST_HTML


try:
    adapter_module.fetch_via_http_proxy = direct_success
    adapter_module.fetch_url = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected seed fallback"))
    assert adapter._fetch_html(FORUM_SECTIONS["databases"], config, "browser") == LIST_HTML
finally:
    adapter_module.fetch_via_http_proxy = original_direct
    adapter_module.fetch_url = original_seed_fallback

assert calls == [("direct", True)]

calls.clear()


def direct_detail(_url, *, bypass_proxy=False, **_kwargs):
    calls.append(("direct", bypass_proxy))
    return DETAIL_HTML


try:
    adapter_module.fetch_via_http_proxy = direct_detail
    adapter_module.screenshot_html_with_browser = lambda *_args, **_kwargs: b"direct-png"
    adapter_module.fetch_page_artifacts = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected detail fallback"))
    result = adapter.collect_detail(task, config, run_context)
finally:
    adapter_module.fetch_via_http_proxy = original_direct
    adapter_module.screenshot_html_with_browser = original_screenshot
    adapter_module.fetch_page_artifacts = original_detail_fallback

assert calls == [("direct", True)]
assert result is not None and result.screenshot_png == b"direct-png"
assert result.payload["domain"] == EXPECTED_HOST

calls.clear()


def direct_blocked(_url, *, bypass_proxy=False, **_kwargs):
    calls.append(("direct", bypass_proxy))
    raise RuntimeError("HTTP 403 Forbidden")


try:
    adapter_module.fetch_via_http_proxy = direct_blocked
    adapter_module.fetch_page_artifacts = lambda **_kwargs: (DETAIL_HTML, b"browser-png")
    result = adapter.collect_detail(task, config, run_context)
finally:
    adapter_module.fetch_via_http_proxy = original_direct
    adapter_module.fetch_page_artifacts = original_detail_fallback

assert calls == [("direct", True)]
assert result is not None and result.screenshot_png == b"browser-png"
assert result.payload["domain"] == EXPECTED_HOST

print("DarkForums .as domain, parser, direct fetch, and browser fallback checks passed.")
