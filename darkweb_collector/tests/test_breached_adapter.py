from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.adapters.breached import BreachedAdapter, _section_name
from darkweb_collector.models import SeedResult, SiteConfig
from darkweb_collector.sites.breached import (
    normalize_breached_timestamp,
    parse_breached_detail,
    parse_breached_list,
)


LIST_HTML_FIXTURE = """
<html><head><title>Databases | BreachForums</title></head>
<body>
<div class="block-container">
  <div class="structItem structItem--thread is-prefix-1 js-inlineModContainer js-threadListItem-100200" data-author="actor_one">
    <div class="structItem-cell structItem-cell--main">
      <div class="structItem-title">
        <a href="/threads/example-corp-database-leak.100200/" data-tp-primary="on">Example Corp Database Leak (2026)</a>
      </div>
      <div class="structItem-minor">
        <ul class="structItem-parts">
          <li><a class="username" data-user-id="1">actor_one</a></li>
          <li><time class="u-dt" datetime="2026-05-01T10:00:00+0000">May 1, 2026</time></li>
        </ul>
      </div>
    </div>
    <div class="structItem-cell structItem-cell--meta">
      <dl class="pairs pairs--justified"><dt>Replies</dt><dd>12</dd></dl>
      <dl class="pairs pairs--justified structItem-minor"><dt>Views</dt><dd>3.4K</dd></dl>
    </div>
    <div class="structItem-cell structItem-cell--latest">
      <a href="/threads/example-corp-database-leak.100200/latest"><time class="u-dt" datetime="2026-05-08T22:11:00+0000">May 8, 2026</time></a>
    </div>
  </div>
  <div class="structItem structItem--thread js-inlineModContainer js-threadListItem-100201" data-author="actor_two">
    <div class="structItem-cell structItem-cell--main">
      <div class="structItem-title">
        <a href="/threads/healthnet-clinic-records.100201/">HealthNet Clinic Patient Records Dump</a>
      </div>
      <div class="structItem-minor">
        <ul class="structItem-parts">
          <li><a class="username" data-user-id="2">actor_two</a></li>
          <li><time class="u-dt" datetime="2026-04-20T08:00:00+0000">Apr 20, 2026</time></li>
        </ul>
      </div>
    </div>
    <div class="structItem-cell structItem-cell--meta">
      <dl class="pairs pairs--justified"><dt>Replies</dt><dd>3</dd></dl>
      <dl class="pairs pairs--justified structItem-minor"><dt>Views</dt><dd>982</dd></dl>
    </div>
    <div class="structItem-cell structItem-cell--latest">
      <a href="/threads/healthnet-clinic-records.100201/latest"><time class="u-dt" datetime="2026-05-07T14:30:00+0000">May 7, 2026</time></a>
    </div>
  </div>
</div>
</body></html>
"""


DETAIL_HTML_FIXTURE = """
<html><head><title>Example Corp Database Leak (2026) | BreachForums</title></head>
<body>
<div class="p-body-pageContent">
<article class="message message--post js-post js-inlineModContainer" data-author="actor_one" data-content="post-555000">
  <div class="message-userDetails">
    <h4 class="message-name"><a class="username" data-user-id="1">actor_one</a></h4>
  </div>
  <header class="message-attribution">
    <ul class="message-attribution-main listInline">
      <li><a href="/threads/example-corp-database-leak.100200/post-555000" rel="nofollow"><time class="u-dt" datetime="2026-05-01T10:00:00+0000">May 1, 2026</time></a></li>
    </ul>
  </header>
  <div class="message-userContent lbContainer js-lbContainer">
    <article class="message-body js-selectToQuote">
      <div class="bbWrapper">
        Victim: Example Corp.<br>
        Target: Example Corp customer database (3.4M rows).<br>
        Attacker: ShinyHackers group.<br>
        Mirror: <a class="link link--external" href="https://files.example.invalid/dump.7z" rel="nofollow noopener">files.example.invalid</a>
        <blockquote class="bbCodeBlock bbCodeBlock--expandable bbCodeBlock--quote">
          <a class="bbCodeBlock-sourceJump">someone said:</a>
          quoted reply about an unrelated company.
        </blockquote>
      </div>
    </article>
  </div>
</article>
</div>
</body></html>
"""


class BreachedParserTests(unittest.TestCase):
    def test_section_name_handles_xenforo_url(self) -> None:
        self.assertEqual(
            "databases",
            _section_name("https://breached.st/forums/databases.14/?order=post_date&direction=desc"),
        )
        self.assertEqual(
            "leaks_market",
            _section_name("https://breached.st/forums/leaks-market.18/"),
        )

    def test_parse_list_extracts_xenforo_threads(self) -> None:
        url = "https://breached.st/forums/databases.14/?order=post_date&direction=desc"
        parsed = parse_breached_list(url, LIST_HTML_FIXTURE, max_topics=10)

        self.assertEqual("breached", parsed["site_name"])
        self.assertEqual("databases", parsed["section"])
        self.assertEqual(2, parsed["topic_count"])
        first, second = parsed["topics"]

        self.assertEqual("100200", first["tid"])
        self.assertEqual("Example Corp Database Leak (2026)", first["title"])
        self.assertEqual(
            "https://breached.st/threads/example-corp-database-leak.100200/",
            first["full_url"],
        )
        self.assertEqual("actor_one", first["author"])
        self.assertEqual("12", first["replies"])
        self.assertEqual("3.4K", first["views"])
        self.assertEqual("2026-05-01T10:00:00+0000", first["published_at"])
        self.assertEqual("2026-05-08T22:11:00+0000", first["last_reply_at"])
        self.assertTrue(first["content_hash"])

        self.assertEqual("100201", second["tid"])
        self.assertEqual("actor_two", second["author"])

    def test_parse_detail_strips_quotes_and_collects_links(self) -> None:
        url = "https://breached.st/threads/example-corp-database-leak.100200/"
        parsed = parse_breached_detail(url, DETAIL_HTML_FIXTURE)

        self.assertEqual("breached", parsed["site_name"])
        self.assertEqual("actor_one", parsed["author"])
        self.assertEqual("2026-05-01T10:00:00+0000", parsed["timestamp"])
        self.assertEqual("2026-05-01", parsed["published_at_utc"])
        self.assertNotIn("quoted reply about an unrelated company", parsed["content"])
        self.assertIn("Example Corp", parsed["content"])
        self.assertIn(
            "https://files.example.invalid/dump.7z",
            parsed["attachments"],
        )
        victim_names = [v["name"] for v in parsed["victims"]]
        self.assertTrue(any("Example Corp" in name for name in victim_names))

    def test_normalize_timestamp_handles_iso_and_relative(self) -> None:
        self.assertEqual(
            "2026-05-01",
            normalize_breached_timestamp("2026-05-01T10:00:00+0000"),
        )
        self.assertEqual(
            "2026-05-08",
            normalize_breached_timestamp("yesterday", collected_at_utc="2026-05-09T12:00:00+00:00"),
        )
        self.assertEqual(
            "2026-05-09",
            normalize_breached_timestamp("today", collected_at_utc="2026-05-09T12:00:00+00:00"),
        )
        self.assertEqual(
            "2026-05-07",
            normalize_breached_timestamp("2 days ago", collected_at_utc="2026-05-09T12:00:00+00:00"),
        )


class BreachedAdapterTests(unittest.TestCase):
    def test_invalid_detail_html_rejects_corrupted_payloads(self) -> None:
        adapter = BreachedAdapter()
        self.assertFalse(adapter._is_valid_detail_html(""))
        self.assertFalse(adapter._is_valid_detail_html("abc\x00" * 200))
        self.assertTrue(
            adapter._is_valid_detail_html(
                '<article class="message message--post" data-content="post-1">'
                '<div class="bbWrapper">x</div></article>'
            )
        )

    def test_plan_details_rotates_across_sections(self) -> None:
        adapter = BreachedAdapter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"DARKWEB_COLLECTOR_DB_PATH": str(Path(tmp_dir) / "collector.db")},
                clear=False,
            ):
                config = SiteConfig(
                    site_name="breached",
                    enabled=True,
                    seed_urls=(
                        "https://breached.st/forums/databases.14/",
                        "https://breached.st/forums/cracked-accounts.16/",
                        "https://breached.st/forums/leaks-market.18/",
                    ),
                    seed_fetch_mode="browser",
                    detail_fetch_mode="browser",
                    profile="warm",
                    max_topics_per_run=10,
                    max_detail_pages_per_run=4,
                    cooldown_seconds=60,
                    output_dir=Path(tmp_dir) / "output",
                    dedupe_window_minutes=10,
                )
                seed_result = SeedResult(
                    site_name="breached",
                    collected_at_utc="2026-05-09T00:00:00+00:00",
                    payload={
                        "sections": [
                            {
                                "section": "databases",
                                "topics": [
                                    {"full_url": "https://breached.st/threads/db-1.1/", "title": "db1", "content_hash": "a"},
                                    {"full_url": "https://breached.st/threads/db-2.2/", "title": "db2", "content_hash": "b"},
                                ],
                            },
                            {
                                "section": "cracked",
                                "topics": [
                                    {"full_url": "https://breached.st/threads/cr-1.3/", "title": "cr1", "content_hash": "c"},
                                    {"full_url": "https://breached.st/threads/cr-2.4/", "title": "cr2", "content_hash": "d"},
                                ],
                            },
                            {
                                "section": "leaks",
                                "topics": [
                                    {"full_url": "https://breached.st/threads/lk-1.5/", "title": "lk1", "content_hash": "e"},
                                    {"full_url": "https://breached.st/threads/lk-2.6/", "title": "lk2", "content_hash": "f"},
                                ],
                            },
                        ]
                    },
                    raw_html_by_url={},
                )

                tasks = adapter.plan_details(seed_result, config)

        sections = [task.metadata["section"] for task in tasks]
        self.assertEqual(["databases", "cracked", "leaks", "databases"], sections)


if __name__ == "__main__":
    unittest.main()
