from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile

from darkweb_collector.adapters import cracked as cracked_adapter
from darkweb_collector.browser_client import _cookie_rows, _persist_browser_storage_state
from darkweb_collector.config import get_site_config
from darkweb_collector.job_diagnostics import classify_error
from darkweb_collector.models import SiteConfig
from darkweb_collector.queueing import BROWSER_RENDER_QUEUE, queue_for_detail, queue_for_seed
from darkweb_collector.session_cookies import list_cookie_capable_sites
from darkweb_collector.sites.cracked import _safe_print
from darkweb_collector import tor_fetch


captured_outputs: list[Path] = []
captured_commands: list[list[str]] = []
original_run = tor_fetch.subprocess.run
original_which = tor_fetch.shutil.which


def fake_run(command, capture_output, check):
    assert capture_output is True and check is False
    captured_commands.append(list(command))
    output_path = Path(command[command.index("--output") + 1])
    output_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    captured_outputs.append(output_path)
    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")


try:
    tor_fetch.subprocess.run = fake_run
    tor_fetch.shutil.which = lambda _name: "curl"
    first = tor_fetch.fetch_via_http_proxy("https://example.invalid/a", retries=0, bypass_proxy=True)
    second = tor_fetch.fetch_via_http_proxy("https://example.invalid/b", retries=0, bypass_proxy=True)
finally:
    tor_fetch.subprocess.run = original_run
    tor_fetch.shutil.which = original_which

assert first and second
assert len({str(path) for path in captured_outputs}) == 2
assert all("--noproxy" in command and "*" in command for command in captured_commands)
assert all(not path.exists() for path in captured_outputs)

config = SiteConfig(
    site_name="cracked",
    enabled=True,
    seed_urls=("https://cracked.st/Forum-Other-Leaks",),
    seed_fetch_mode="browser",
    detail_fetch_mode="browser",
    profile="warm",
    max_topics_per_run=1,
    max_detail_pages_per_run=1,
    cooldown_seconds=60,
    output_dir=Path(tempfile.gettempdir()) / "cracked-test-output",
    dedupe_window_minutes=60,
    extras={
        "fetch_timeout_seconds": 5,
        "render_wait_seconds": 0,
        "browser_engine": "chromium",
        "browser_storage_state_file": "browser-state/cracked/storage-state.json",
    },
)

repository_config = get_site_config(
    "cracked",
    Path(__file__).resolve().parents[2] / "darkweb_collector" / "sites.yaml",
)
assert queue_for_seed(repository_config.seed_fetch_mode) == BROWSER_RENDER_QUEUE
assert queue_for_detail(repository_config.detail_fetch_mode) == BROWSER_RENDER_QUEUE
assert repository_config.extras["browser_engine"] == "chromium"
assert repository_config.extras["browser_storage_state_file"] == "browser-state/cracked/storage-state.json"
assert not any(key.startswith("session_cookie") for key in repository_config.extras)
assert "cracked" not in {site["site_name"] for site in list_cookie_capable_sites()}

calls: list[str] = []
browser_options: list[dict[str, object]] = []
original_fetch = cracked_adapter.fetch_via_http_proxy
original_proxy = cracked_adapter.get_http_proxy_settings
original_browser = cracked_adapter.fetch_page_artifacts_with_browser
original_cookie = cracked_adapter.resolve_session_cookie
original_close = cracked_adapter.close_browser_client
original_sleep = cracked_adapter.time.sleep


def fake_fetch(_url, *, proxy_host=None, proxy_port=None, bypass_proxy=False, **_kwargs):
    calls.append("direct" if bypass_proxy else "proxy")
    if bypass_proxy:
        raise RuntimeError("HTTP 403 Forbidden")
    return "<html>proxy challenge</html>"


def fake_browser(_url, *, cookie_header=None, **_kwargs):
    calls.append("browser_cookie" if cookie_header else "browser")
    browser_options.append(dict(_kwargs))
    return ("<html><div id=posts><div class=post_body>valid</div></div></html>" if cookie_header else "<html>challenge</html>", b"png")


try:
    cracked_adapter.fetch_via_http_proxy = fake_fetch
    cracked_adapter.get_http_proxy_settings = lambda: ("127.0.0.1", 7890)
    cracked_adapter.fetch_page_artifacts_with_browser = fake_browser
    cracked_adapter.resolve_session_cookie = lambda _config: "sid=secret-value"
    cracked_adapter.close_browser_client = lambda: None
    cracked_adapter.time.sleep = lambda _seconds: None
    html, screenshot = cracked_adapter.CrackedAdapter()._fetch_with_fallback(
        "https://cracked.st/Thread-Test",
        config,
        validator=cracked_adapter.CrackedAdapter._is_valid_detail_html,
        capture_screenshot=True,
    )
finally:
    cracked_adapter.fetch_via_http_proxy = original_fetch
    cracked_adapter.get_http_proxy_settings = original_proxy
    cracked_adapter.fetch_page_artifacts_with_browser = original_browser
    cracked_adapter.resolve_session_cookie = original_cookie
    cracked_adapter.close_browser_client = original_close
    cracked_adapter.time.sleep = original_sleep

assert calls == ["direct", "proxy", "browser", "browser_cookie"], calls
assert "post_body" in html and screenshot == b"png"
assert len(browser_options) == 2
assert all(options["browser_engine"] == "chromium" for options in browser_options)
assert Path(str(browser_options[0]["storage_state_path"])).parts[-3:] == (
    "browser-state",
    "cracked",
    "storage-state.json",
)
assert browser_options[0]["persist_storage_state"] is True
assert browser_options[1]["storage_state_path"] is None
assert browser_options[1]["persist_storage_state"] is False
assert classify_error("Proxy fetch failed: HTTP 403 Forbidden") == "site_blocked"
assert classify_error("Proxy connection refused") == "proxy"

cookies = _cookie_rows("sid=secret-value; mybbuser=123", "https://cracked.st/Thread-Test")
assert [item["name"] for item in cookies] == ["sid", "mybbuser"]
assert all(item["domain"] == "cracked.st" for item in cookies)


class FakeBrowserContext:
    @staticmethod
    def storage_state():
        return {"cookies": [{"name": "anonymous", "value": "challenge"}], "origins": []}


with tempfile.TemporaryDirectory(prefix="cracked-storage-state-") as temp_dir:
    state_path = Path(temp_dir) / "browser-state" / "cracked" / "storage-state.json"
    _persist_browser_storage_state(FakeBrowserContext(), state_path)
    assert json.loads(state_path.read_text(encoding="utf-8"))["cookies"][0]["name"] == "anonymous"
    assert not list(state_path.parent.glob("*.tmp"))

buffer = io.BytesIO()
stream = io.TextIOWrapper(buffer, encoding="cp936", errors="strict")
with redirect_stdout(stream):
    _safe_print("⭐ Cracked title")
stream.flush()
assert buffer.getvalue()

print("Cracked bounded fallback, isolated temporary files, cookies, and diagnostics checks passed.")
