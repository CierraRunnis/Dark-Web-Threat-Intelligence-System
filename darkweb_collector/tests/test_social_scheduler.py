from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from darkweb_collector.social_adapters import CollectResult, CoverageStatus, SocialAdapterError, SocialPost
from darkweb_collector.social_scheduler import (
    anchored_scan_slot,
    due_campaign_platforms,
    enqueue_due_social_scans,
    execute_claimed_social_scan,
    is_anchored_scan_due,
    match_social_post,
)


ANCHOR = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)


class FakeService:
    def __init__(self):
        self.due = []
        self.claim = 77
        self.finished = []
        self.posts = []
        self.source_states = []

    def list_due_social_campaign_platforms(self, now=None):
        return self.due

    def claim_social_scan(self, campaign_id, platform, scheduled_at=None):
        return self.claim

    def finish_social_scan(self, scan_run_id, *, stats, status, error, cursor):
        self.finished.append(
            {"id": scan_run_id, "stats": stats, "status": status, "error": error, "cursor": cursor}
        )

    def upsert_social_post_event(self, campaign_id, scan_run_id, post):
        self.posts.append(post)
        return {"status": "created" if len(self.posts) == 1 else "duplicate"}

    def update_social_source_state(self, source_id, *, cursor, status, error):
        self.source_states.append(
            {"id": source_id, "cursor": cursor, "status": status, "error": error}
        )


class FixtureAdapter:
    platform = "x"

    def __init__(self, *, fail=False):
        self.fail = fail

    def coverage_status(self):
        return CoverageStatus("api", True)

    def collect(self, request):
        if self.fail:
            raise SocialAdapterError("fixture failure")
        post = SocialPost(
            platform="x",
            platform_post_id="1",
            source_url="https://x.com/example/status/1",
            original_text="fixture threat",
            published_at="2026-07-15T00:00:00+00:00",
        )
        return CollectResult((post, post), "next-cursor", CoverageStatus("api", True))


class SocialSchedulerTests(unittest.TestCase):
    def test_fixed_anchor_initial_t1799_and_t1800(self):
        self.assertEqual(anchored_scan_slot(ANCHOR, ANCHOR), ANCHOR)
        self.assertTrue(is_anchored_scan_due(ANCHOR, None, ANCHOR))
        self.assertFalse(
            is_anchored_scan_due(ANCHOR, ANCHOR, datetime(2026, 7, 15, 0, 29, 59, tzinfo=timezone.utc))
        )
        self.assertTrue(
            is_anchored_scan_due(ANCHOR, ANCHOR, datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc))
        )

    def test_due_expands_campaign_by_platform_and_skips_active_overlap(self):
        campaigns = [
            {
                "id": 9,
                "enabled": True,
                "start_at": ANCHOR.isoformat(),
                "platforms": ["x", "youtube"],
                "last_scheduled_at": {"x": ANCHOR.isoformat(), "youtube": ANCHOR.isoformat()},
            }
        ]
        due = due_campaign_platforms(
            campaigns,
            now=datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
            active={(9, "x")},
        )
        self.assertEqual([(item["campaign_id"], item["platform"]) for item in due], [(9, "youtube")])

    def test_enqueue_claim_prevents_overlap(self):
        service = FakeService()
        service.due = [{"campaign_id": 9, "platform": "x", "scheduled_at": ANCHOR.isoformat()}]
        service.claim = None
        calls = []

        dispatched = enqueue_due_social_scans(lambda payload: calls.append(payload), service=service, now=ANCHOR)
        self.assertEqual(dispatched, [])
        self.assertEqual(calls, [])

    def test_campaign_platforms_are_dispatched_as_four_independent_tasks(self):
        service = FakeService()
        service.due = [
            {"campaign_id": 9, "platform": platform, "scheduled_at": ANCHOR.isoformat()}
            for platform in ("x", "facebook", "youtube", "telegram")
        ]
        calls = []

        dispatched = enqueue_due_social_scans(
            lambda payload: calls.append(payload) or f"job-{payload['platform']}",
            service=service,
            now=ANCHOR,
        )

        self.assertEqual({item["platform"] for item in calls}, {"x", "facebook", "youtube", "telegram"})
        self.assertEqual(len(dispatched), 4)

    def test_enqueue_preserves_global_cursor_when_source_cursors_are_merged(self):
        service = FakeService()
        service.due = [
            {
                "campaign_id": 9,
                "platform": "youtube",
                "scheduled_at": ANCHOR.isoformat(),
                "cursor": json.dumps({"__global__": "2026-07-15T00:00:00+00:00"}),
                "sources": [{"id": 3, "value": "UCfixture", "cursor": "source-cursor"}],
            }
        ]
        calls = []

        enqueue_due_social_scans(
            lambda payload: calls.append(payload) or "job-youtube",
            service=service,
            now=ANCHOR,
        )

        cursor = json.loads(calls[0]["cursor"])
        self.assertEqual(cursor["__global__"], "2026-07-15T00:00:00+00:00")
        self.assertEqual(cursor["UCfixture"], "source-cursor")

    def test_success_persists_posts_scan_stats_and_cursor(self):
        service = FakeService()
        payload = {
            "campaign_id": 9,
            "scan_run_id": 77,
            "platform": "x",
            "keywords": ["Tibet"],
            "region_terms": ["fixture"],
            "threat_terms": ["threat"],
            "sources": [{"id": 3, "value": "example"}],
            "cursor": "old-cursor",
        }
        result = execute_claimed_social_scan(payload, service=service, adapter=FixtureAdapter())

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(service.finished[-1]["status"], "succeeded")
        self.assertEqual(service.finished[-1]["cursor"], "next-cursor")
        self.assertEqual(service.source_states[-1]["status"], "healthy")
        self.assertEqual(service.source_states[-1]["cursor"], "next-cursor")

    def test_failure_retains_last_good_cursor(self):
        service = FakeService()
        payload = {
            "campaign_id": 9,
            "scan_run_id": 77,
            "platform": "x",
            "keywords": ["Tibet"],
            "region_terms": ["fixture"],
            "threat_terms": ["threat"],
            "sources": [{"id": 3, "value": "example"}],
            "cursor": "last-good-cursor",
        }
        with self.assertRaises(SocialAdapterError):
            execute_claimed_social_scan(payload, service=service, adapter=FixtureAdapter(fail=True))

        self.assertEqual(service.finished[-1]["status"], "failed")
        self.assertEqual(service.finished[-1]["cursor"], "last-good-cursor")
        self.assertEqual(service.source_states[-1]["cursor"], "last-good-cursor")

    def test_match_requires_target_or_region_plus_threat_and_exclude_wins(self):
        post = {"title": "Tibet public service", "original_text": "database offered for sale"}
        payload = {
            "region_terms": ["Tibet"],
            "target_terms": ["specific unit"],
            "threat_terms": ["offered for sale"],
            "exclude_terms": ["exercise"],
        }
        self.assertTrue(match_social_post(post, payload)[0])
        self.assertFalse(match_social_post({**post, "title": "Tibet exercise"}, payload)[0])
        self.assertFalse(match_social_post({"title": "Tibet news", "original_text": "ordinary discussion"}, payload)[0])


if __name__ == "__main__":
    unittest.main()
