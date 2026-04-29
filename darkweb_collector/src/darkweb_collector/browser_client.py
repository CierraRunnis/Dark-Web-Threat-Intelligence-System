from __future__ import annotations

import atexit
from threading import Lock, get_ident
import traceback
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserProxyConfig:
    server: str | None = None


class BrowserClient:
    def __init__(self, proxy: BrowserProxyConfig) -> None:
        self._proxy = proxy
        self._playwright = None
        self._browser = None
        self._created_monotonic = 0.0
        self._task_count = 0

    def _open(self) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": True,
        }
        if self._proxy.server:
            launch_kwargs["proxy"] = {"server": self._proxy.server}
        self._browser = self._playwright.firefox.launch(**launch_kwargs)
        self._created_monotonic = time.monotonic()
        self._task_count = 0

    def _should_rotate(self) -> bool:
        if self._browser is None:
            return True
        if self._task_count >= 10:
            return True
        return (time.monotonic() - self._created_monotonic) >= 15 * 60

    def _ensure_browser(self) -> None:
        if self._should_rotate():
            self.close()
            self._open()

    def fetch_page_artifacts(
        self,
        url: str,
        wait_seconds: int,
        timeout_seconds: int,
        screenshot_selector: str | None = None,
        screenshot_selectors: tuple[str, ...] = (),
        hide_selectors: tuple[str, ...] = (),
    ) -> tuple[str, bytes]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        self._ensure_browser()
        assert self._browser is not None
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
                "Gecko/20100101 Firefox/123.0"
            ),
            viewport={"width": 1440, "height": 960},
        )
        page = context.new_page()
        try:
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_seconds * 1000)
            except PlaywrightTimeoutError:
                # Some .onion pages keep polling or streaming content, so
                # networkidle never triggers. Fall back to DOM readiness.
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(wait_seconds * 1000)
            _clear_browser_check_interstitial(page, timeout_ms=timeout_seconds * 1000)
            if hide_selectors:
                selector_rules = ", ".join(hide_selectors)
                page.add_style_tag(content=f"{selector_rules} {{ display: none !important; }}")
                page.wait_for_timeout(500)
            screenshot_png = None
            if screenshot_selectors:
                try:
                    clip_boxes = []
                    for selector in screenshot_selectors:
                        page.wait_for_selector(selector, timeout=timeout_seconds * 1000)
                        locator = page.locator(selector).first
                        locator.scroll_into_view_if_needed(timeout=timeout_seconds * 1000)
                        box = locator.bounding_box()
                        if box is not None:
                            clip_boxes.append(box)
                    if clip_boxes:
                        min_x = min(box["x"] for box in clip_boxes)
                        min_y = min(box["y"] for box in clip_boxes)
                        max_x = max(box["x"] + box["width"] for box in clip_boxes)
                        max_y = max(box["y"] + box["height"] for box in clip_boxes)
                        screenshot_png = page.screenshot(
                            type="png",
                            clip={
                                "x": min_x,
                                "y": min_y,
                                "width": max_x - min_x,
                                "height": max_y - min_y,
                            },
                        )
                except PlaywrightTimeoutError:
                    screenshot_png = None
            elif screenshot_selector:
                try:
                    page.wait_for_selector(screenshot_selector, timeout=timeout_seconds * 1000)
                    locator = page.locator(screenshot_selector).first
                    locator.scroll_into_view_if_needed(timeout=timeout_seconds * 1000)
                    screenshot_png = locator.screenshot(type="png")
                except PlaywrightTimeoutError:
                    screenshot_png = None
            if screenshot_png is None:
                screenshot_png = page.screenshot(type="png", full_page=True)
            # Capture HTML after the page-specific selectors have had a chance to
            # appear. Some forum pages finish rendering well after the initial
            # DOMContentLoaded/networkidle checkpoint, which made us persist a
            # head-only document while the screenshot already contained the post.
            html = _read_page_content(page)
            self._task_count += 1
            return html, screenshot_png
        finally:
            context.close()

    def screenshot_html_content(
        self,
        html: str,
        base_url: str,
        wait_seconds: int,
        timeout_seconds: int,
        screenshot_selector: str | None = None,
        screenshot_selectors: tuple[str, ...] = (),
        hide_selectors: tuple[str, ...] = (),
    ) -> bytes:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        self._ensure_browser()
        assert self._browser is not None
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
                "Gecko/20100101 Firefox/123.0"
            ),
            viewport={"width": 1440, "height": 960},
        )
        page = context.new_page()
        try:
            rendered_html = _inject_base_href(html, base_url)
            page.set_content(rendered_html, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(wait_seconds * 1000)
            _clear_browser_check_interstitial(page, timeout_ms=timeout_seconds * 1000)
            if hide_selectors:
                selector_rules = ", ".join(hide_selectors)
                page.add_style_tag(content=f"{selector_rules} {{ display: none !important; }}")
                page.wait_for_timeout(500)

            screenshot_png = None
            if screenshot_selectors:
                try:
                    clip_boxes = []
                    for selector in screenshot_selectors:
                        page.wait_for_selector(selector, timeout=timeout_seconds * 1000)
                        locator = page.locator(selector).first
                        locator.scroll_into_view_if_needed(timeout=timeout_seconds * 1000)
                        box = locator.bounding_box()
                        if box is not None:
                            clip_boxes.append(box)
                    if clip_boxes:
                        min_x = min(box["x"] for box in clip_boxes)
                        min_y = min(box["y"] for box in clip_boxes)
                        max_x = max(box["x"] + box["width"] for box in clip_boxes)
                        max_y = max(box["y"] + box["height"] for box in clip_boxes)
                        screenshot_png = page.screenshot(
                            type="png",
                            clip={
                                "x": min_x,
                                "y": min_y,
                                "width": max_x - min_x,
                                "height": max_y - min_y,
                            },
                        )
                except PlaywrightTimeoutError:
                    screenshot_png = None
            elif screenshot_selector:
                try:
                    page.wait_for_selector(screenshot_selector, timeout=timeout_seconds * 1000)
                    locator = page.locator(screenshot_selector).first
                    locator.scroll_into_view_if_needed(timeout=timeout_seconds * 1000)
                    screenshot_png = locator.screenshot(type="png")
                except PlaywrightTimeoutError:
                    screenshot_png = None
            if screenshot_png is None:
                screenshot_png = page.screenshot(type="png", full_page=True)
            self._task_count += 1
            return screenshot_png
        finally:
            context.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


_GLOBAL_CLIENT: BrowserClient | None = None
_GLOBAL_PROXY: BrowserProxyConfig | None = None
_GLOBAL_CLIENT_THREAD_ID: int | None = None
_GLOBAL_CLIENT_LOCK = Lock()

_BROWSER_CHECK_MARKERS = (
    "checking your browser",
    "cf-browser-verification",
    "security verification",
    "verify you are human",
    "please move your mouse or press a key",
    "please wait while we verify",
)


def _read_page_content(page, *, attempts: int = 6, wait_ms: int = 250) -> str:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return page.content()
        except Exception as exc:
            last_error = exc
            page.wait_for_timeout(wait_ms)
    if last_error is not None:
        raise last_error
    return ""


def _inject_base_href(html: str, base_url: str) -> str:
    base_tag = f'<base href="{base_url}">'
    if "<head>" in html:
        return html.replace("<head>", f"<head>{base_tag}", 1)
    if "<html>" in html:
        return html.replace("<html>", f"<html><head>{base_tag}</head>", 1)
    return f"<head>{base_tag}</head>{html}"


def _looks_like_browser_check_page(html: str | None) -> bool:
    content = str(html or "").lower()
    return any(marker in content for marker in _BROWSER_CHECK_MARKERS)


def _clear_browser_check_interstitial(
    page,
    *,
    timeout_ms: int,
    settle_wait_ms: int = 750,
) -> str:
    html = _read_page_content(page)
    if not _looks_like_browser_check_page(html):
        return html

    deadline = time.monotonic() + max(timeout_ms, settle_wait_ms) / 1000
    viewport = getattr(page, "viewport_size", None) or {"width": 1440, "height": 960}
    center_x = int(viewport.get("width", 1440) * 0.5)
    center_y = int(viewport.get("height", 960) * 0.38)

    while time.monotonic() < deadline:
        try:
            page.mouse.move(center_x, center_y, steps=12)
            page.wait_for_timeout(120)
            page.mouse.click(center_x, center_y, delay=80)
            page.wait_for_timeout(120)
            page.mouse.wheel(0, 420)
            page.wait_for_timeout(120)
        except Exception:
            # Cloudflare/browser-check pages can trigger a navigation mid-action.
            # When that happens, just wait for the next stable DOM snapshot
            # instead of failing the whole fetch.
            page.wait_for_timeout(300)
        for key in ("Tab", "Space"):
            try:
                page.keyboard.press(key)
                page.wait_for_timeout(120)
            except Exception:
                page.wait_for_timeout(300)
            html = _read_page_content(page)
            if not _looks_like_browser_check_page(html):
                page.wait_for_timeout(settle_wait_ms)
                return _read_page_content(page)
        try:
            page.wait_for_load_state("networkidle", timeout=min(1500, timeout_ms))
        except Exception:
            pass
        html = _read_page_content(page)
        if not _looks_like_browser_check_page(html):
            page.wait_for_timeout(settle_wait_ms)
            return _read_page_content(page)
    return html


def _get_or_create_client(requested_proxy: BrowserProxyConfig) -> BrowserClient:
    global _GLOBAL_CLIENT, _GLOBAL_PROXY, _GLOBAL_CLIENT_THREAD_ID
    current_thread_id = get_ident()
    with _GLOBAL_CLIENT_LOCK:
        if (
            _GLOBAL_CLIENT is None
            or _GLOBAL_PROXY != requested_proxy
            or _GLOBAL_CLIENT_THREAD_ID != current_thread_id
        ):
            close_browser_client()
            _GLOBAL_CLIENT = BrowserClient(proxy=requested_proxy)
            _GLOBAL_PROXY = requested_proxy
            _GLOBAL_CLIENT_THREAD_ID = current_thread_id
        return _GLOBAL_CLIENT


def fetch_html_with_browser(
    url: str,
    wait_seconds: int,
    timeout_seconds: int,
    proxy_server: str | None = None,
) -> str:
    requested_proxy = BrowserProxyConfig(server=proxy_server)
    client = _get_or_create_client(requested_proxy)
    html, _ = client.fetch_page_artifacts(
        url=url,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
    )
    return html


def fetch_page_artifacts_with_browser(
    url: str,
    wait_seconds: int,
    timeout_seconds: int,
    proxy_server: str | None = None,
    screenshot_selector: str | None = None,
    screenshot_selectors: tuple[str, ...] = (),
    hide_selectors: tuple[str, ...] = (),
) -> tuple[str, bytes]:
    requested_proxy = BrowserProxyConfig(server=proxy_server)
    client = _get_or_create_client(requested_proxy)
    return client.fetch_page_artifacts(
        url=url,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
        screenshot_selector=screenshot_selector,
        screenshot_selectors=screenshot_selectors,
        hide_selectors=hide_selectors,
    )


def screenshot_html_with_browser(
    html: str,
    base_url: str,
    wait_seconds: int,
    timeout_seconds: int,
    proxy_server: str | None = None,
    screenshot_selector: str | None = None,
    screenshot_selectors: tuple[str, ...] = (),
    hide_selectors: tuple[str, ...] = (),
) -> bytes:
    requested_proxy = BrowserProxyConfig(server=proxy_server)
    client = _get_or_create_client(requested_proxy)
    return client.screenshot_html_content(
        html=html,
        base_url=base_url,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
        screenshot_selector=screenshot_selector,
        screenshot_selectors=screenshot_selectors,
        hide_selectors=hide_selectors,
    )


def close_browser_client() -> None:
    global _GLOBAL_CLIENT, _GLOBAL_PROXY, _GLOBAL_CLIENT_THREAD_ID
    if _GLOBAL_CLIENT is not None:
        _GLOBAL_CLIENT.close()
        _GLOBAL_CLIENT = None
    _GLOBAL_PROXY = None
    _GLOBAL_CLIENT_THREAD_ID = None


atexit.register(close_browser_client)
