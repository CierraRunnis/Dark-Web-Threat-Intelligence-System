from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.sites.chaos import parse_chaos_detail, parse_chaos_homepage
from darkweb_collector.sites.darkforums import (
    extract_attackers_from_content,
    normalize_darkforums_timestamp,
    parse_darkforums_detail,
    parse_darkforums_list,
)
from darkweb_collector.sites.dragonforceblog import parse_dragonforceblog_detail_page, parse_dragonforceblog_list_page
from darkweb_collector.sites.dragonforce import parse_dragonforce_homepage


class ParserTests(unittest.TestCase):
    def test_dragonforce_parser_extracts_victims(self) -> None:
        html = """
        <html>
          <head><title>DragonForce</title></head>
          <body>
            <div class="text"><a class="text-pointer-animations link-published" href="/victim-1">Acme Corp (acme.example)</a></div>
            <div class="timer timer-published">1 March 2026</div>
            <div class=number><b>12 GB</b></div>
          </body>
        </html>
        """
        parsed = parse_dragonforce_homepage("http://dragon.onion/", html)
        self.assertEqual(1, parsed["victim_count"])
        self.assertEqual("Acme Corp", parsed["victims"][0]["name"])
        self.assertEqual("acme.example", parsed["victims"][0]["domain"])

    def test_dragonforce_parser_treats_domain_href_as_external_url(self) -> None:
        html = """
        <html>
          <head><title>DragonForce</title></head>
          <body>
            <div class="text"><a class="text-pointer-animations link-going" href="www.consultaegis.com/">Aegis Project Controls (www.consultaegis.com)</a></div>
            <div class="timer timer-going">2026-03-16 05:39:00 UTC</div>
            <div class=number><b>213G</b></div>
          </body>
        </html>
        """
        parsed = parse_dragonforce_homepage("http://dragon.onion/", html)
        self.assertEqual("https://www.consultaegis.com/", parsed["victims"][0]["detail_url"])

    def test_darkforums_parsers_extract_list_and_detail(self) -> None:
        list_html = """
        <html>
          <head><title>DarkForums - Databases</title></head>
          <body>
            <span class="subject_new" id="tid_123">
              <a href="Thread-123-Acme">Acme Database Leak</a>
            </span>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <head><title>Acme Detail</title></head>
          <body>
            <a class="username">LeakPoster</a>
            <span class="DateTime">2026-03-10</span>
            <div class="post_content">
              Victim: Acme Corporation Group: NightCrew This post contains breach details.
            </div>
            <div class="post_controls"></div>
          </body>
        </html>
        """
        list_result = parse_darkforums_list("https://darkforums.su/Forum-Databases", list_html, max_topics=5)
        self.assertEqual(1, list_result["topic_count"])
        self.assertEqual("Acme Database Leak", list_result["topics"][0]["title"])

        detail_result = parse_darkforums_detail("https://darkforums.su/Thread-123-Acme", detail_html)
        self.assertEqual("LeakPoster", detail_result["author"])
        self.assertTrue(detail_result["victims"])

    def test_darkforums_detail_prefers_first_post_body(self) -> None:
        detail_html = """
        <html>
          <head><title>Website - eurojobs.com</title></head>
          <body>
            <div id="posts">
              <div class="post classic " id="post_1">
                <div class="post_author scaleimages">
                  <div class="post_user-profile largetext"><a>Tanaka</a></div>
                </div>
                <div class="post_whole">
                  <div class="post_content">
                    <div class="post_head">
                      <span class="post_date">01-09-23, 05:04 PM <span class="post_edit">(edited)</span></span>
                    </div>
                    <div class="post_body scaleimages" id="pid_1">
                      Main body content<br />
                      Size sql file - 1.6 GB
                    </div>
                    <div class="post_meta"></div>
                  </div>
                </div>
              </div>
              <!-- end: postbit_classic -->
              <div class="post classic " id="post_2">
                <div class="post_whole">
                  <div class="post_content">
                    <div class="post_body scaleimages" id="pid_2">
                      thank you for sharing
                    </div>
                    <div class="post_meta"></div>
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """
        detail_result = parse_darkforums_detail("https://darkforums.su/Thread-Website-eurojobs-com", detail_html)
        self.assertEqual("Tanaka", detail_result["author"])
        self.assertIn("Main body content", detail_result["content"])
        self.assertNotIn("#1", detail_result["content"])
        self.assertIn("01-09-23, 05:04 PM", detail_result["timestamp"])

    def test_darkforums_timestamp_normalization_uses_original_post_time(self) -> None:
        normalized = normalize_darkforums_timestamp("20-12-24, 08:02 PM", collected_at_utc="2026-04-11T09:00:00+00:00")
        self.assertEqual("2024-12-20", normalized)

    def test_darkforums_attacker_extraction_filters_false_positives(self) -> None:
        explicit = "Victim: Acme. Group: LockBit. This post contains breach details."
        self.assertEqual(["LockBit"], extract_attackers_from_content(explicit))

        military = (
            "I am selling 11 TB of exfiltrated data from company based in Europe, Serbia. "
            "Its subcontractor for military and its making various howitzers, ammunition and complex systems."
        )
        self.assertEqual([], extract_attackers_from_content(military))

        crm_dump = (
            'Rejected By Jitasa","Item owner\'s visibility group","0","0","0","0","U.S." '
            "global BSA group L10."
        )
        self.assertEqual([], extract_attackers_from_content(crm_dump))

    def test_chaos_parsers_extract_homepage_and_detail(self) -> None:
        homepage_html = """
        <html>
          <head><title>CHAOS</title></head>
          <body>
            <div class="rounded-xl bg-bunker p-4 flex justify-between w-full">
              <div>
                <a href="/victim-1" class="break-words">ACME</a>
                <a href="https://acme.example" target="_blank">acme.example</a>
                Leaked size <span>15 Gb</span>
                View count <span>42</span>
                <div class="px-2 max-w-[80%]"><div>Leaked records</div></div>
                <div class="whitespace-nowrap">1d 2h 3m 4s</div>
              </div>
            </div></div></div>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <head><title>ACME detail</title></head>
          <body>
            <a href="https://example.com/">link</a>
            Detail content
          </body>
        </html>
        """
        homepage_result = parse_chaos_homepage("http://chaos.onion/", homepage_html)
        self.assertEqual(1, homepage_result["victim_count"])
        self.assertEqual("ACME", homepage_result["victims"][0]["name"])

        detail_result = parse_chaos_detail("http://chaos.onion/victim-1", detail_html)
        self.assertEqual("ok", detail_result["fetch_status"])
        self.assertGreaterEqual(detail_result["outbound_link_count"], 1)

    def test_chaos_detail_selects_matching_card_by_path(self) -> None:
        detail_html = """
        <html>
          <head><title>CHAOS - Detail</title></head>
          <body>
            <div class="rounded-xl bg-bunker p-4 flex justify-between w-full">
              <div>
                <a href="/wrong-card" class="break-words">Wrong Corp</a>
                <a href="https://wrong.example" target="_blank">wrong.example</a>
                Leaked size <span>15 Gb</span>
                View count <span>42</span>
                <div class="px-2 max-w-[80%]"><div>Wrong description</div></div>
              </div>
            </div></div></div>
            <div class="rounded-xl bg-bunker p-4 flex justify-between w-full">
              <div>
                <a href="/target-card" class="break-words">Target Corp</a>
                <a href="https://target.example" target="_blank">target.example</a>
                Leaked size <span>1000 Gb</span>
                View count <span>490</span>
                <div class="px-2 max-w-[80%]"><div>Correct target description</div></div>
              </div>
            </div></div></div>
          </body>
        </html>
        """
        detail_result = parse_chaos_detail("http://chaos.onion/target-card", detail_html)
        self.assertEqual(["Target Corp"], detail_result["victims"])
        self.assertEqual("1000 GB", detail_result["claimed_size"])
        self.assertEqual(490, detail_result["view_count"])
        self.assertIn("Correct target description", detail_result["content"])

    def test_dragonforceblog_detail_uses_post_uuid_payload(self) -> None:
        html = """
        <html>
          <head><title>DragonForce | Blog</title></head>
          <body>
            <div class="publications-list__publication">
              <p class="list-publication__website">www.edificedna.com</p>
              <h3 class="list-publication__name">Edifice Design + Architecture</h3>
              <p class="list-publication__description">List card summary</p>
            </div>
            <script type="application/json" data-nuxt-data="nuxt-app" id="__NUXT_DATA__">
              ["a86fd3d3-d7c9-4c73-ac1c-2c9e865aed29","2026-03-19T18:56:56.121538Z","Edifice Design + Architecture","www.edificedna.com","390 S Main St Ste B, Bountiful, Utah, 84...","Correct payload description for Edifice.",23087099904,"2026-03-13T15:19:54.539248Z",[],"679ef3bf-fa45-45db-9eb7-017e275ddd8b"]
            </script>
          </body>
        </html>
        """

        list_result = parse_dragonforceblog_list_page(
            "http://dragonblog.onion/blog?page=1",
            html,
        )
        self.assertEqual(
            "http://dragonblog.onion/blog/?post_uuid=a86fd3d3-d7c9-4c73-ac1c-2c9e865aed29",
            list_result["victims"][0]["detail_url"],
        )

        detail_result = parse_dragonforceblog_detail_page(
            "http://dragonblog.onion/blog/?post_uuid=a86fd3d3-d7c9-4c73-ac1c-2c9e865aed29",
            html,
        )
        self.assertEqual("Edifice Design + Architecture", detail_result["company_name"])
        self.assertEqual("www.edificedna.com", detail_result["victims"][0])
        self.assertIn("Correct payload description", detail_result["content"])
        self.assertEqual("21.50 GB", detail_result["claimed_size"])
