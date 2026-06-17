from __future__ import annotations

import atexit
from pathlib import Path
from threading import Lock, current_thread
from typing import Any


_BROWSERS: dict[object, tuple[object, object]] = {}
_BROWSER_LOCK = Lock()


def _get_browser():
    thread_key = current_thread()
    with _BROWSER_LOCK:
        existing = _BROWSERS.get(thread_key)
        if existing is not None:
            return existing
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        _BROWSERS[thread_key] = (playwright, browser)
        return playwright, browser


def close_session_browser(*, all_threads: bool = False) -> None:
    thread_key = current_thread()
    with _BROWSER_LOCK:
        if all_threads:
            pairs = list(_BROWSERS.values())
            _BROWSERS.clear()
        else:
            pair = _BROWSERS.pop(thread_key, None)
            pairs = [pair] if pair is not None else []
    for playwright, browser in pairs:
        try:
            browser.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass


def fetch_page_artifacts_with_session(
    url: str,
    *,
    storage_state_path: str | None = None,
    wait_seconds: int = 4,
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    _, browser = _get_browser()

    context_kwargs: dict[str, Any] = {
        "viewport": {"width": 1440, "height": 960},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "ignore_https_errors": True,
    }
    candidate = None
    if storage_state_path:
        candidate = Path(storage_state_path)
        if candidate.exists():
            context_kwargs["storage_state"] = str(candidate)

    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    try:
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_seconds * 1000)
        except PlaywrightTimeoutError:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        page.wait_for_timeout(wait_seconds * 1000)
        html = page.content()
        return {
            "url": page.url,
            "requested_url": url,
            "title": page.title(),
            "html": html,
            "screenshot_png": b"",
        }
    finally:
        try:
            if candidate is not None:
                context.storage_state(path=str(candidate))
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass


atexit.register(lambda: close_session_browser(all_threads=True))
