from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.adapters.registry import get_adapter, list_adapters
from darkweb_collector.adapters.updap import UpdapAdapter
from darkweb_collector.models import DetailTask, RunContext, SiteConfig
from darkweb_collector.sites.registry import get_parser
from darkweb_collector.sites.updap import (
    UpdapParseError,
    normalize_updap_timestamp,
    parse_updap_detail,
    parse_updap_list,
)


LIST_HTML = """
<html>
<head>
  <title>UpDap - Databases</title>
  <link rel="canonical" href="https://updap.com/Forum-Databases" />
</head>
<body>
<!-- start: forumdisplay_threadlist -->
<table class="tborder">
<tr class="inline_row">
  <td class="trow1 forumdisplay_regular"></td>
  <td class="trow1 forumdisplay_regular">
    <span class="subject_new" id="tid_9706">
      <a href="Thread-SQL-CSV-protemps-com-sg">SQL CSV protemps.com.sg</a>
    </span>
    <div>
      <span class="author smalltext"><a href="/User-alice">alice</a>, </span>
      <span class="thread_start_datetime smalltext">08-21-2026, 09:10 AM</span>
    </div>
  </td>
  <td class="trow1 forumdisplay_regular">
    <a href="/misc.php?action=whoposted&amp;tid=9706">4</a>
  </td>
  <td class="trow1 forumdisplay_regular">321</td>
  <td class="trow1 forumdisplay_regular">
    <span class="lastpost smalltext">08-22-2026, 10:11 AM<br />Last Post</span>
  </td>
</tr>
<tr class="inline_row">
  <td class="trow2 forumdisplay_regular"></td>
  <td class="trow2 forumdisplay_regular">
    <span class="subject_old" id="tid_9705">
      <a href="Thread-Example-Database">Example Database</a>
    </span>
    <div>
      <span class="author smalltext"><a href="/User-bob">bob</a>, </span>
      <span class="thread_start_datetime smalltext">08-20-2026, 08:00 PM</span>
    </div>
  </td>
  <td class="trow2 forumdisplay_regular">
    <a href="/misc.php?action=whoposted&amp;tid=9705">0</a>
  </td>
  <td class="trow2 forumdisplay_regular">99</td>
  <td class="trow2 forumdisplay_regular">
    <span class="lastpost smalltext">08-20-2026, 08:00 PM<br />Last Post</span>
  </td>
</tr>
</table>
</body>
</html>
"""

DETAIL_HTML = """
<html>
<head>
  <title>SQL CSV protemps.com.sg</title>
  <meta name="description" content="Public breach summary for person@example.com." />
  <link rel="canonical" href="https://updap.com/Thread-SQL-CSV-protemps-com-sg" />
</head>
<body>
<div id="posts">
  <div class="post " style="" id="post_9997">
    <div class="post__author">
      <div class="post__user-profile">
        <a href="https://updap.com/User-alice"><strong>alice</strong></a>
      </div>
    </div>
    <div class="post_content">
      <div class="post_head">
        <span class="post_date">08-21-2026, 09:10 AM</span>
      </div>
      <div class="post_body scaleimages" id="pid_9997">
        Public breach summary for person@example.com.
        <div class="hidecontent">
          <strong>You have not unlocked this post's content yet.</strong>
        </div>
      </div>
      <div class="post_meta" id="meta_9997"></div>
    </div>
  </div>
</div>
</body>
</html>
"""


def _config(tmp_path: Path) -> SiteConfig:
    return SiteConfig(
        site_name="updap",
        enabled=False,
        seed_urls=(
            "https://updap.com/Forum-Databases"
            "?sortby=started&order=desc&datecut=9999&prefix=0",
        ),
        seed_fetch_mode="http",
        detail_fetch_mode="http",
        profile="cold",
        max_topics_per_run=5,
        max_detail_pages_per_run=0,
        cooldown_seconds=21600,
        output_dir=tmp_path / "updap",
        dedupe_window_minutes=360,
        extras={"fetch_timeout_seconds": 90},
    )


def _run_context() -> RunContext:
    return RunContext(
        job_id="test-updap",
        job_type="seed",
        queue_name="seed_http",
        target="updap",
        started_at_utc="2026-08-27T00:00:00+00:00",
    )


def test_updap_list_parser_extracts_stable_topic_metadata() -> None:
    payload = parse_updap_list(
        "https://updap.com/Forum-Databases",
        LIST_HTML,
        max_topics=1,
    )

    assert payload["site_name"] == "updap"
    assert payload["topic_count"] == 1
    topic = payload["topics"][0]
    assert topic["tid"] == "9706"
    assert topic["full_url"] == (
        "https://updap.com/Thread-SQL-CSV-protemps-com-sg"
    )
    assert topic["author"] == "alice"
    assert topic["published_at"] == "08-21-2026, 09:10 AM"
    assert topic["replies"] == "4"
    assert topic["views"] == "321"
    assert topic["last_reply_at"] == "08-22-2026, 10:11 AM"


def test_updap_detail_parser_uses_public_redacted_excerpt() -> None:
    payload = parse_updap_detail(
        "https://updap.com/Thread-SQL-CSV-protemps-com-sg",
        DETAIL_HTML,
    )

    assert payload["site_name"] == "updap"
    assert payload["author"] == "alice"
    assert payload["timestamp"] == "08-21-2026, 09:10 AM"
    assert payload["published_at_utc"] == "2026-08-21"
    assert payload["content"] == "Public breach summary for [redacted-email]."
    assert payload["content_restricted"] is True
    assert payload["content_scope"] == "public_description_or_redacted_excerpt"


def test_updap_other_leaks_uses_the_same_mybb_parser() -> None:
    html = LIST_HTML.replace("Forum-Databases", "Forum-Other-Leaks")
    payload = parse_updap_list(
        "https://updap.com/Forum-Other-Leaks",
        html,
        max_topics=2,
    )

    assert payload["site_name"] == "updap"
    assert payload["topic_count"] == 2
    assert [topic["tid"] for topic in payload["topics"]] == ["9706", "9705"]


def test_updap_rejects_access_pages_instead_of_persisting_empty_results() -> None:
    with pytest.raises(UpdapParseError):
        parse_updap_list(
            "https://updap.com/Forum-Databases",
            "<html><title>403 Forbidden</title><body>Access denied</body></html>",
        )

    with pytest.raises(UpdapParseError):
        parse_updap_detail(
            "https://updap.com/Thread-Test",
            "<html><title>Just a moment</title></html>",
        )


def test_updap_uses_unambiguous_month_first_timestamp() -> None:
    assert normalize_updap_timestamp("08-09-2026, 07:25 AM") == "2026-08-09"


def test_updap_adapter_and_parser_are_registered() -> None:
    assert "updap" in list_adapters()
    assert isinstance(get_adapter("updap"), UpdapAdapter)
    assert get_parser("updap_list") is parse_updap_list
    assert get_parser("updap_detail") is parse_updap_detail


def test_updap_adapter_keeps_site_identity_and_drops_raw_detail_html(
    tmp_path: Path,
) -> None:
    adapter = UpdapAdapter()
    config = _config(tmp_path)

    with patch.object(adapter, "_fetch_html", return_value=LIST_HTML):
        seed_result = adapter.collect_seed(config, _run_context())

    assert seed_result.site_name == "updap"
    assert seed_result.payload["site_name"] == "updap"
    assert seed_result.payload["source_url"] == "updap"

    detail_task = DetailTask(
        site_name="updap",
        target_url="https://updap.com/Thread-SQL-CSV-protemps-com-sg",
        metadata={"section": "databases", "artifact_stem": "fixture"},
    )
    with patch.object(adapter, "_fetch_html", return_value=DETAIL_HTML):
        detail_result = adapter.collect_detail(
            detail_task,
            config,
            _run_context(),
        )

    assert detail_result.site_name == "updap"
    assert detail_result.payload["site_name"] == "updap"
    assert detail_result.raw_html is None
    assert detail_result.screenshot_png is None


def test_repository_config_is_safe_and_normalization_is_site_aware() -> None:
    from darkweb_collector.config import get_site_config
    from darkweb_collector.normalized_intelligence import (
        SOURCE_LABELS,
        _normalise_forum_timestamp,
    )

    config_path = Path(__file__).resolve().parents[1] / "sites.yaml"
    config = get_site_config("updap", config_path)

    assert config.enabled is True
    assert config.seed_fetch_mode == "http"
    assert config.profile == "cold"
    assert config.max_topics_per_run == 5
    assert config.max_detail_pages_per_run == 2
    assert len(config.seed_urls) == 2
    assert config.seed_urls[1].startswith("https://updap.com/Forum-Other-Leaks")
    assert config.extras["source_family"] == "pwnfrm"
    assert _normalise_forum_timestamp(
        "updap",
        "08-09-2026, 07:25 AM",
        collected_at_utc="2026-08-27T00:00:00+00:00",
    ) == "2026-08-09"
    assert SOURCE_LABELS["updap"] == "UpDap"
