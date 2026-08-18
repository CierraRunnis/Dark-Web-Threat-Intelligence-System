from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.adapters.cracked import CrackedAdapter, _section_name
from darkweb_collector.adapters.registry import list_adapters
from darkweb_collector.sites.cracked import (
    get_cracked_sections,
    normalize_cracked_timestamp,
    parse_cracked_detail,
    parse_cracked_list,
)


LIST_HTML_FIXTURE = """
<html><head><title>Other Leaks | Cracked.st</title></head>
<body><table>
<tr>
  <td class="trow1">
    <span class=" subject_old" id="tid_1901723" style="font-size: 15px;">
      <a href="Thread-Staff-Domain-Mirror"><span><span>Domain Mirror</span></span></a>
    </span>
    <div class="author smalltext">
      <a data-uid='78748' data-class='profile_url'
         data-link='profilecard.php?action=profilecard&amp;uid=78748'
         href="https://cracked.st/Liars"><span class="admin_rank">Liars</span></a>
      <span class="thread-date">&nbsp;&nbsp;1 year ago</span>
    </div>
  </td>
  <td><span class="stats-count theme_text">0</span><br /><span class="stats-desc">Replies</span></td>
  <td><span class="stats-count theme_text">17.063</span><br /><span class="stats-desc">Views</span></td>
</tr>
<tr>
  <td class="trow1">
    <span class=" subject_new" id="tid_1901800">
      <a href="Thread-Forum-Rules"><span>Forum Rules</span></a>
    </span>
    <div class="author smalltext">
      <a data-uid='1' data-class='profile_url' href="https://cracked.st/Admin">Admin</a>
      <span class="thread-date">today</span>
    </div>
  </td>
  <td><span class="stats-count theme_text">5</span><br /><span class="stats-desc">Replies</span></td>
  <td><span class="stats-count theme_text">100</span><br /><span class="stats-desc">Views</span></td>
</tr>
</table></body></html>
"""


DETAIL_HTML_FIXTURE = """
<html><head><title>Domain Mirror | Cracked.sh</title></head>
<body>
<div class="thread-info">
  <h1>Domain Mirror</h1>
  <span class="smalltext">by <a href="member.php?action=profile&amp;uid=78748">Liars</a> - 14 April, 2025 - 12:25 AM</span>
</div>
<div id="posts">
  <div id="post_44662252" class="post-set">
    <a data-uid='78748' data-class='profile_url' href="https://cracked.st/Liars">
      <span class="admin_rank">Liars</span>
    </a>
    <div class="post-head">
      <span class="post_date">
        <span class="post-op">OP</span>
        <span title="10:25 PM - 13 April, 2025">14 April, 2025 - 12:25 AM</span>
      </span>
    </div>
    <div class="post_body scaleimages" id="pid_44662252">
      Dear Cracked Members,<br />
      This announcement describes the official mirror.
      <blockquote>quoted reply should not appear</blockquote>
      <div class="signature scaleimages">signature should not appear</div>
    </div>
    <div class="post_controls">controls</div>
  </div>
</div>
</body></html>
"""


class CrackedParserTests(unittest.TestCase):
    def test_section_name_handles_requested_forum_urls(self) -> None:
        self.assertEqual(
            "other_leaks",
            _section_name("https://cracked.st/Forum-Other-Leaks?sortby=started"),
        )
        self.assertEqual(
            "combolists",
            _section_name("https://cracked.st/Forum-Combolists--297?sortby=started"),
        )

    def test_parse_list_extracts_mybb_thread_metadata(self) -> None:
        url = "https://cracked.st/Forum-Other-Leaks?sortby=started"
        parsed = parse_cracked_list(url, LIST_HTML_FIXTURE, max_topics=10)

        self.assertEqual("cracked", parsed["site_name"])
        self.assertEqual(2, parsed["topic_count"])
        first = parsed["topics"][0]
        self.assertEqual("1901723", first["tid"])
        self.assertEqual("Domain Mirror", first["title"])
        self.assertEqual("https://cracked.st/Thread-Staff-Domain-Mirror", first["full_url"])
        self.assertEqual("Liars", first["author"])
        self.assertEqual("0", first["replies"])
        self.assertEqual("17.063", first["views"])
        self.assertEqual("1 year ago", first["published_at"])
        self.assertTrue(first["content_hash"])

    def test_parse_detail_extracts_author_timestamp_and_body(self) -> None:
        parsed = parse_cracked_detail(
            "https://cracked.sh/Thread-Staff-Domain-Mirror",
            DETAIL_HTML_FIXTURE,
        )

        self.assertEqual("cracked", parsed["site_name"])
        self.assertEqual("Liars", parsed["author"])
        self.assertEqual("14 April, 2025 - 12:25 AM", parsed["timestamp"])
        self.assertEqual("2025-04-14", parsed["published_at_utc"])
        self.assertIn("Dear Cracked Members", parsed["content"])
        self.assertNotIn("quoted reply should not appear", parsed["content"])
        self.assertNotIn("signature should not appear", parsed["content"])

    def test_get_sections_returns_requested_targets(self) -> None:
        sections = get_cracked_sections()
        self.assertEqual(
            "https://cracked.st/Forum-Other-Leaks?sortby=started&order=desc&datecut=9999&prefix=0",
            sections["other_leaks"],
        )
        self.assertEqual(
            "https://cracked.st/Forum-Combolists--297?sortby=started&order=desc&datecut=9999&prefix=0",
            sections["combolists"],
        )

    def test_normalize_timestamp_handles_relative_values(self) -> None:
        self.assertEqual(
            "2026-06-21",
            normalize_cracked_timestamp("yesterday", collected_at_utc="2026-06-22T12:00:00+00:00"),
        )
        self.assertEqual(
            "2026-06-22",
            normalize_cracked_timestamp("today", collected_at_utc="2026-06-22T12:00:00+00:00"),
        )
        self.assertEqual(
            "2026-06-20",
            normalize_cracked_timestamp("2 days ago", collected_at_utc="2026-06-22T12:00:00+00:00"),
        )


class CrackedAdapterTests(unittest.TestCase):
    def test_invalid_detail_html_rejects_empty_and_corrupt_payloads(self) -> None:
        adapter = CrackedAdapter()
        self.assertFalse(adapter._is_valid_detail_html(""))
        self.assertFalse(adapter._is_valid_detail_html("abc\x00" * 200))
        self.assertTrue(adapter._is_valid_detail_html('<div id="posts"><div class="post_body">ok</div></div>'))

    def test_adapter_is_registered(self) -> None:
        self.assertIn("cracked", list_adapters())


if __name__ == "__main__":
    unittest.main()
