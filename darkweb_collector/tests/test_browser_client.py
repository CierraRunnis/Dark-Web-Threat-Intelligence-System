from __future__ import annotations

from pathlib import Path
import sys
from threading import Thread
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.browser_client as browser_client_module
from darkweb_collector.browser_client import (
    BrowserProxyConfig,
    _clear_browser_check_interstitial,
    _get_or_create_client,
    _looks_like_browser_check_page,
    close_browser_client,
)


class _FakeMouse:
    def __init__(self, page) -> None:
        self.page = page
        self.moves: list[tuple[float, float, int]] = []
        self.clicks: list[tuple[float, float, int]] = []
        self.wheels: list[tuple[int, int]] = []

    def move(self, x, y, steps=1):
        self.moves.append((x, y, steps))

    def click(self, x, y, delay=0):
        self.clicks.append((x, y, delay))
        self.page._interactions += 1
        if self.page._interactions >= self.page._clear_after:
            self.page._html = self.page._cleared_html

    def wheel(self, dx, dy):
        self.wheels.append((dx, dy))


class _FakeKeyboard:
    def __init__(self, page) -> None:
        self.page = page
        self.presses: list[str] = []

    def press(self, key: str):
        self.presses.append(key)
        self.page._interactions += 1
        if self.page._interactions >= self.page._clear_after:
            self.page._html = self.page._cleared_html


class _FakePage:
    def __init__(
        self,
        html: str,
        *,
        clear_after: int = 3,
        cleared_html: str = "<div id='posts'>ok</div>",
    ) -> None:
        self.viewport_size = {"width": 1440, "height": 960}
        self._html = html
        self._cleared_html = cleared_html
        self._clear_after = clear_after
        self._interactions = 0
        self.waits: list[int] = []
        self.load_states: list[tuple[str, int]] = []
        self.mouse = _FakeMouse(self)
        self.keyboard = _FakeKeyboard(self)

    def content(self) -> str:
        return self._html

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.waits.append(timeout_ms)

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_states.append((state, timeout))


class BrowserClientHelperTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_browser_client(all_threads=True)

    def test_browser_check_marker_detection(self) -> None:
        self.assertTrue(_looks_like_browser_check_page("Checking your browser"))
        self.assertTrue(_looks_like_browser_check_page("Please move your mouse or press a key"))
        self.assertTrue(_looks_like_browser_check_page("Performing security verification"))
        self.assertTrue(_looks_like_browser_check_page("Verify you are human"))
        self.assertFalse(_looks_like_browser_check_page("<div id='posts'>ready</div>"))

    def test_interstitial_handler_performs_interaction_until_cleared(self) -> None:
        page = _FakePage("Checking your browser", clear_after=2)
        html = _clear_browser_check_interstitial(page, timeout_ms=10000, settle_wait_ms=500)
        self.assertEqual("<div id='posts'>ok</div>", html)
        self.assertTrue(page.mouse.moves)
        self.assertTrue(page.mouse.clicks)
        self.assertTrue(page.keyboard.presses)

    def test_interstitial_handler_does_not_touch_normal_page(self) -> None:
        page = _FakePage("<div id='posts'>ok</div>")
        html = _clear_browser_check_interstitial(page, timeout_ms=10000, settle_wait_ms=500)
        self.assertEqual("<div id='posts'>ok</div>", html)
        self.assertFalse(page.mouse.moves)
        self.assertFalse(page.mouse.clicks)
        self.assertFalse(page.keyboard.presses)

    def test_close_browser_client_only_closes_current_thread_client(self) -> None:
        original_client_class = browser_client_module.BrowserClient
        created_clients = []

        class _FakeBrowserClient:
            def __init__(self, proxy) -> None:
                self.proxy = proxy
                self.closed = False
                created_clients.append(self)

            def close(self) -> None:
                self.closed = True

        browser_client_module.BrowserClient = _FakeBrowserClient
        try:
            main_client = _get_or_create_client(BrowserProxyConfig(server="socks5://127.0.0.1:9150"))
            worker_clients = []

            def _worker() -> None:
                worker_clients.append(
                    _get_or_create_client(BrowserProxyConfig(server="socks5://127.0.0.1:9150"))
                )
                close_browser_client()

            thread = Thread(target=_worker)
            thread.start()
            thread.join()

            self.assertEqual(2, len(created_clients))
            self.assertFalse(main_client.closed)
            self.assertTrue(worker_clients[0].closed)
        finally:
            browser_client_module.BrowserClient = original_client_class
