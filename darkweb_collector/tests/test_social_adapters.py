from __future__ import annotations

import json
from pathlib import Path
import unittest
from datetime import datetime, timezone

from darkweb_collector.social_adapters import CollectRequest
from darkweb_collector.social_adapters.base import SocialAdapterError, dedupe_posts
from darkweb_collector.social_adapters.facebook import FacebookAdapter
from darkweb_collector.social_adapters.telegram import TelegramAdapter, telegram_source_identifier
from darkweb_collector.social_adapters.x import XAdapter
from darkweb_collector.social_adapters.youtube import YouTubeAdapter


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "social_platform_payloads.json").read_text(encoding="utf-8")
)


class FixtureTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get_json(self, url, *, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        return self.responses.pop(0)


class SocialAdapterTests(unittest.TestCase):
    def test_x_api_query_and_fixture_mapping(self):
        transport = FixtureTransport(FIXTURE["x"])
        result = XAdapter(transport=transport, bearer_token="fixture-token").collect(
            CollectRequest(keywords=("Tibet security",), sources=("example_x",), limit=20)
        )

        self.assertIn("190001", result.next_cursor)
        self.assertEqual(len(result.posts), 1)
        self.assertEqual(result.posts[0].source_url, "https://x.com/example_x/status/190001")
        self.assertEqual(result.posts[0].media_urls, ("https://img.example/x.png",))
        self.assertIn("-is:reply", transport.calls[0]["params"]["query"])
        self.assertIn("Bearer fixture-token", transport.calls[0]["headers"]["Authorization"])

    def test_facebook_collects_only_configured_public_pages(self):
        transport = FixtureTransport(FIXTURE["facebook"])
        result = FacebookAdapter(transport=transport, access_token="fixture-token").collect(
            CollectRequest(sources=("https://www.facebook.com/public.page",))
        )

        self.assertEqual(len(result.posts), 1)
        self.assertEqual(result.posts[0].author, "Public Page")
        self.assertIn("2026-07-15T01:05:00", result.next_cursor)
        self.assertTrue(result.coverage.limited)
        self.assertTrue(transport.calls[0]["url"].endswith("/public.page/posts"))

        private_transport = FixtureTransport()
        private_result = FacebookAdapter(transport=private_transport, access_token="fixture-token").collect(
            CollectRequest(sources=("https://www.facebook.com/groups/private-group",))
        )
        self.assertEqual(private_result.posts, ())
        self.assertEqual(private_transport.calls, [])

    def test_facebook_uses_authorized_browser_fallback_without_api_token(self):
        adapter = FacebookAdapter(
            access_token="",
            browser_storage_state="fixture-state.json",
            browser_fetcher=lambda _request: (
                [
                    {
                        "text": "Tibet test unit data offered for sale",
                        "source_url": "https://www.facebook.com/public.page/posts/12345",
                        "author": "Public Page",
                    }
                ],
                "browser-cursor",
            ),
        )
        result = adapter.collect(CollectRequest(keywords=("Tibet",), limit=5))

        self.assertEqual(result.coverage.mode, "browser_fallback")
        self.assertTrue(result.coverage.configured)
        self.assertTrue(result.coverage.limited)
        self.assertEqual(result.posts[0].platform_post_id, "12345")
        self.assertEqual(result.posts[0].metadata["collection_mode"], "authorized_browser")
        self.assertEqual(result.next_cursor, "browser-cursor")

    def test_youtube_maps_title_description_and_never_requests_comments(self):
        transport = FixtureTransport(FIXTURE["youtube"])
        result = YouTubeAdapter(transport=transport, api_key="fixture-key").collect(
            CollectRequest(keywords=("Tibet",), limit=5)
        )

        self.assertEqual(result.posts[0].title, "Example video title")
        self.assertEqual(result.posts[0].original_text, "Example video description")
        self.assertEqual(transport.calls[0]["params"]["part"], "snippet")
        self.assertNotIn("comment", json.dumps(transport.calls[0]).lower())
        self.assertNotIn("caption", json.dumps(transport.calls[0]).lower())

    def test_youtube_channel_source_uses_uploads_playlist_instead_of_search(self):
        source = "https://www.youtube.com/@fixture-channel"
        transport = FixtureTransport(
            {
                "items": [
                    {
                        "id": "UCfixture123456789",
                        "contentDetails": {"relatedPlaylists": {"uploads": "UUfixture123456789"}},
                    }
                ]
            },
            {
                "items": [
                    {
                        "snippet": {
                            "publishedAt": "2026-07-15T01:20:00Z",
                            "title": "Channel video",
                            "description": "Channel description",
                            "channelId": "UCfixture123456789",
                            "channelTitle": "Fixture Channel",
                            "resourceId": {"videoId": "channel-video-1"},
                        },
                        "contentDetails": {
                            "videoId": "channel-video-1",
                            "videoPublishedAt": "2026-07-15T01:20:00Z",
                        },
                    }
                ]
            },
        )
        result = YouTubeAdapter(transport=transport, api_key="fixture-key").collect(
            CollectRequest(
                sources=(source,),
                cursor=json.dumps({source: "2026-07-15T01:00:00+00:00"}),
                limit=5,
            )
        )

        self.assertEqual(result.posts[0].platform_post_id, "channel-video-1")
        self.assertTrue(transport.calls[0]["url"].endswith("/channels"))
        self.assertEqual(transport.calls[0]["params"]["forHandle"], "@fixture-channel")
        self.assertTrue(transport.calls[1]["url"].endswith("/playlistItems"))
        self.assertEqual(transport.calls[1]["params"]["playlistId"], "UUfixture123456789")
        self.assertNotIn("/search", "\n".join(call["url"] for call in transport.calls))
        self.assertEqual(json.loads(result.next_cursor)[source], "2026-07-15T01:20:00+00:00")

    def test_telegram_fixture_excludes_private_and_non_broadcast_rows(self):
        adapter = TelegramAdapter(
            fetcher=lambda request: (FIXTURE["telegram"], {"public_channel": "100"}),
            api_id="1",
            api_hash="fixture",
            session="fixture",
        )
        result = adapter.collect(CollectRequest(keywords=("Tibet",)))

        self.assertEqual(len(result.posts), 1)
        self.assertEqual(result.posts[0].platform_post_id, "8001:100")
        self.assertEqual(result.posts[0].source_url, "https://t.me/public_channel/100")
        self.assertNotIn("Private group", result.posts[0].original_text)

    def test_telegram_source_identifier_accepts_public_channel_forms_only(self):
        self.assertEqual(telegram_source_identifier("https://t.me/s/public_channel/100"), "public_channel")
        self.assertEqual(telegram_source_identifier("@public_channel"), "public_channel")
        self.assertEqual(telegram_source_identifier("public_channel"), "public_channel")
        self.assertEqual(telegram_source_identifier("https://t.me/+privateInvite"), "")
        self.assertEqual(telegram_source_identifier("https://t.me/joinchat/privateInvite"), "")

    def test_telegram_api_path_is_non_interactive_and_searches_each_keyword(self):
        class Chat:
            broadcast = True
            megagroup = False
            username = "public_channel"
            title = "Public Channel"
            id = 8001

        class Message:
            def __init__(self, message_id, text, minute):
                self.id = message_id
                self.message = text
                self.date = datetime(2026, 7, 15, 1, minute, tzinfo=timezone.utc)
                self.chat = Chat()

        class Client:
            def __init__(self):
                self.connected = False
                self.disconnected = False
                self.calls = []

            def connect(self):
                self.connected = True

            def is_user_authorized(self):
                return True

            def disconnect(self):
                self.disconnected = True

            def get_entity(self, value):
                self.calls.append(("entity", value))
                return Chat()

            def iter_messages(self, entity, **kwargs):
                self.calls.append(("messages", entity, kwargs))
                if entity is None:
                    minute = 10 if kwargs.get("search") == "Tibet" else 11
                    return [Message(100 + minute, kwargs.get("search"), minute)]
                return [Message(120, "channel update", 12)]

        client = Client()
        adapter = TelegramAdapter(
            api_id="1",
            api_hash="fixture",
            session="fixture-session",
            client_factory=lambda _session, _api_id, _api_hash: client,
        )
        result = adapter.collect(
            CollectRequest(keywords=("Tibet", "attack"), sources=("https://t.me/public_channel",))
        )

        self.assertTrue(client.connected)
        self.assertTrue(client.disconnected)
        message_calls = [call for call in client.calls if call[0] == "messages"]
        self.assertEqual([call[2].get("search") for call in message_calls[:2]], ["Tibet", "attack"])
        self.assertIsNone(message_calls[-1][2].get("search"))
        cursor = json.loads(result.next_cursor)
        self.assertEqual(cursor["https://t.me/public_channel"], "120")
        self.assertEqual(len([key for key in cursor if key.startswith("__global__:")]), 2)

    def test_missing_credentials_returns_browser_coverage_status_without_network(self):
        transport = FixtureTransport()
        result = XAdapter(transport=transport, bearer_token="").collect(CollectRequest(keywords=("Tibet",)))
        self.assertEqual(result.posts, ())
        self.assertEqual(result.coverage.mode, "browser_fallback")
        self.assertTrue(result.coverage.limited)
        self.assertEqual(transport.calls, [])

    def test_dedupe_uses_platform_native_id(self):
        adapter = XAdapter(transport=FixtureTransport(FIXTURE["x"]), bearer_token="fixture-token")
        post = adapter.collect(CollectRequest(keywords=("Tibet",))).posts[0]
        duplicate = type(post)(**{**post.__dict__, "original_text": "edited content"})
        unique = dedupe_posts([post, duplicate])
        self.assertEqual(len(unique), 1)

    def test_api_error_does_not_advance_cursor(self):
        adapter = XAdapter(
            transport=FixtureTransport({"errors": [{"title": "Too Many Requests", "status": 429}]}),
            bearer_token="fixture-token",
        )
        with self.assertRaises(SocialAdapterError):
            adapter.collect(CollectRequest(keywords=("Tibet",), cursor='{"__global__":"190000"}'))


if __name__ == "__main__":
    unittest.main()
