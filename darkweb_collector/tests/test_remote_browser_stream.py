import asyncio
from queue import Queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from darkweb_collector.remote_browser_sessions import (
    _apply_stream_input,
    _state_payload,
    proxy_remote_browser_stream,
)


class RemoteBrowserStreamTests(unittest.TestCase):
    def test_windows_stream_state_uses_websocket_without_screenshot(self):
        page = Mock()
        page.title.return_value = "Login"
        page.url = "http://example.onion/login"
        session = SimpleNamespace(
            session_id="stream-test",
            platform="test",
            label="Test",
            login_url="http://example.onion/login",
            homepage_url="http://example.onion/",
            vnc_port=0,
            cdp_stream=True,
            storage_state_path="state.json",
            user_data_dir="profile",
            created_at="2026-07-30T00:00:00+00:00",
            last_error="",
        )

        state = _state_payload(session, page)

        self.assertEqual(state["mode"], "embedded_browser")
        self.assertEqual(state["screenshot"], "")
        self.assertEqual(state["rfb_ws_path"], "")
        self.assertEqual(state["stream_ws_path"], "/api/platform-sessions/remote-login/stream-test/stream")
        page.screenshot.assert_not_called()

    def test_stream_input_maps_mouse_and_keyboard_events(self):
        page = Mock()

        _apply_stream_input(page, {"type": "mouse", "action": "move", "x": 12, "y": 34})
        _apply_stream_input(
            page,
            {"type": "mouse", "action": "wheel", "deltaX": 5, "deltaY": 20},
        )
        _apply_stream_input(page, {"type": "key", "action": "down", "key": "a", "text": "a"})
        _apply_stream_input(page, {"type": "key", "action": "up", "key": "a"})

        page.mouse.move.assert_called_once_with(12.0, 34.0)
        page.mouse.wheel.assert_called_once_with(5.0, 20.0)
        page.keyboard.insert_text.assert_called_once_with("a")
        page.keyboard.up.assert_called_once_with("a")

    def test_stream_websocket_sends_ready_and_frame_messages(self):
        frame_queue = Queue(maxsize=2)
        frame_queue.put({"type": "frame", "data": "jpeg-base64", "width": 800, "height": 600})
        session = SimpleNamespace(cdp_stream=True)

        class FakeWebSocket:
            def __init__(self):
                self.messages = []
                self.closed = []

            async def accept(self):
                return None

            async def send_json(self, payload):
                self.messages.append(payload)

            async def receive(self):
                await asyncio.sleep(0.05)
                return {"type": "websocket.disconnect"}

            async def close(self, code=1000):
                self.closed.append(code)

        websocket = FakeWebSocket()

        def call_session(_session, op, payload=None):
            if op == "stream_open":
                return {"stream_id": "client-1", "frame_queue": frame_queue}
            if op == "stream_close":
                return {"closed": True}
            raise AssertionError(op)

        with (
            patch("darkweb_collector.remote_browser_sessions._get_remote_session", return_value=session),
            patch("darkweb_collector.remote_browser_sessions._call_session", side_effect=call_session),
        ):
            asyncio.run(proxy_remote_browser_stream("stream-test", websocket))

        self.assertEqual(
            websocket.messages[0],
            {"type": "ready", "width": 1024, "height": 675},
        )
        self.assertEqual(websocket.messages[1], {"type": "frame", "data": "jpeg-base64", "width": 800, "height": 600})


if __name__ == "__main__":
    unittest.main()
