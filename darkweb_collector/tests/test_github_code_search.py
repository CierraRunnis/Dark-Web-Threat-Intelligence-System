from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from darkweb_collector import code_monitoring as code
from darkweb_collector.api_actions import get_code_monitoring_continuous_status
from darkweb_collector.api_app import _is_private_collector_output_path
from darkweb_collector.document_exposure_platforms import get_exposure_platform
from darkweb_collector.remote_browser_sessions import _browser_child_environment


class _Response:
    def __init__(self, payload: dict, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _search_payload(*, private: bool = False) -> dict:
    return {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "name": "settings.py",
                "path": "src/settings.py",
                "html_url": "https://github.com/example/acme/blob/main/src/settings.py",
                "repository": {
                    "private": private,
                    "name": "acme",
                    "full_name": "example/acme",
                    "html_url": "https://github.com/example/acme",
                    "default_branch": "main",
                    "owner": {"login": "example"},
                },
                "text_matches": [{"fragment": "ACME_TOKEN = 'example-value'"}],
            }
        ],
    }


class GitHubCodeSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        code._GITHUB_API_LAST_REQUEST_MONOTONIC = 0.0
        with code._GITHUB_API_CACHE_LOCK:
            code._GITHUB_API_QUERY_CACHE.clear()
        with code._GITHUB_API_STATE_LOCK:
            code._GITHUB_API_STATE.update(
                {
                    "last_request_at": "",
                    "last_success_at": "",
                    "last_error": "",
                    "limit": None,
                    "remaining": None,
                    "reset_at": "",
                    "cooldown_until": 0.0,
                    "cache_hits": 0,
                    "last_used_channel": "",
                    "fallback_used": False,
                    "degraded": False,
                }
            )

    def test_authenticated_search_parses_results_and_reuses_query_cache(self) -> None:
        response = _Response(
            _search_payload(),
            {
                "X-RateLimit-Limit": "10",
                "X-RateLimit-Remaining": "9",
                "X-RateLimit-Reset": str(int(time.time()) + 60),
            },
        )
        urlopen_mock = Mock(return_value=response)
        env = {
            "DARKWEB_GITHUB_TOKEN": "secret-test-token",
            "DARKWEB_GITHUB_CODE_SEARCH_MODE": "auto",
            "DARKWEB_GITHUB_CODE_SEARCH_MIN_INTERVAL_SECONDS": "0",
            "DARKWEB_GITHUB_CODE_SEARCH_CACHE_SECONDS": "300",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(code, "urlopen", urlopen_mock):
            first_rows, first_meta = code._github_api_code_search("acme.com", 1)
            second_rows, second_meta = code._github_api_code_search("acme.com", 1)
            status = code.github_code_search_status_payload()

        self.assertEqual(len(first_rows), 1)
        self.assertEqual(first_rows[0]["repositoryName"], "acme")
        self.assertEqual(first_rows[0]["branch"], "main")
        self.assertIn("ACME_TOKEN", first_rows[0]["snippetText"])
        self.assertFalse(first_meta["cache_hit"])
        self.assertTrue(second_meta["cache_hit"])
        self.assertEqual(second_rows, first_rows)
        self.assertEqual(urlopen_mock.call_count, 1)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-test-token")
        self.assertEqual(status["activeChannel"], "api")
        self.assertEqual(status["rateRemaining"], 9)
        self.assertEqual(status["cacheHits"], 1)
        self.assertEqual(status["lastUsedChannel"], "api")
        self.assertNotIn("secret-test-token", json.dumps(status))

    def test_private_repository_results_are_not_ingested(self) -> None:
        env = {
            "DARKWEB_GITHUB_TOKEN": "token",
            "DARKWEB_GITHUB_CODE_SEARCH_MIN_INTERVAL_SECONDS": "0",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(code, "urlopen", return_value=_Response(_search_payload(private=True))),
        ):
            rows, _ = code._github_api_code_search("acme.com", 1)

        self.assertEqual(rows, [])

    def test_token_file_is_reloaded_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            token_path = Path(temporary_dir) / "github-token"
            token_path.write_text("first-token\n", encoding="utf-8")
            with patch.dict(os.environ, {"DARKWEB_GITHUB_TOKEN_FILE": str(token_path)}, clear=True):
                first_token, first_source = code._github_api_token()
                token_path.write_text("second-token\n", encoding="utf-8")
                second_token, second_source = code._github_api_token()

        self.assertEqual((first_token, first_source), ("first-token", "token_file"))
        self.assertEqual((second_token, second_source), ("second-token", "token_file"))

    def test_rate_limit_enters_cooldown_without_exposing_token(self) -> None:
        reset_epoch = int(time.time()) + 120
        error = HTTPError(
            code.GITHUB_CODE_SEARCH_API,
            403,
            "forbidden",
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_epoch)},
            None,
        )
        urlopen_mock = Mock(side_effect=error)
        env = {
            "DARKWEB_GITHUB_TOKEN": "secret-rate-token",
            "DARKWEB_GITHUB_CODE_SEARCH_MIN_INTERVAL_SECONDS": "0",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(code, "urlopen", urlopen_mock):
            with self.assertRaisesRegex(code.GitHubCodeSearchUnavailable, "rate_limited") as first_error:
                code._github_api_code_search("acme.com", 1)
            with self.assertRaisesRegex(code.GitHubCodeSearchUnavailable, "rate_limited"):
                code._github_api_code_search("another-query", 1)
            status = code.github_code_search_status_payload()

        self.assertEqual(urlopen_mock.call_count, 1)
        self.assertEqual(status["lastError"], "rate_limited")
        self.assertTrue(status["cooldownUntil"])
        self.assertNotIn("secret-rate-token", str(first_error.exception))

    def test_plain_403_is_access_denied_not_rate_limited(self) -> None:
        error = HTTPError(
            code.GITHUB_CODE_SEARCH_API,
            403,
            "forbidden",
            {"X-RateLimit-Remaining": "7"},
            None,
        )
        env = {
            "DARKWEB_GITHUB_TOKEN": "token",
            "DARKWEB_GITHUB_CODE_SEARCH_MIN_INTERVAL_SECONDS": "0",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(code, "urlopen", side_effect=error):
            with self.assertRaisesRegex(code.GitHubCodeSearchUnavailable, "access_denied"):
                code._github_api_code_search("acme.com", 1)
            status = code.github_code_search_status_payload()

        self.assertEqual(status["lastError"], "access_denied")
        self.assertEqual(status["cooldownUntil"], "")

    def test_retry_after_takes_precedence_over_rate_reset(self) -> None:
        before = time.time()
        retry_epoch = code._github_retry_epoch(
            {"Retry-After": "5", "X-RateLimit-Reset": str(int(before) + 600)},
            60,
        )
        self.assertGreaterEqual(retry_epoch, before + 5)
        self.assertLess(retry_epoch, before + 10)

    def test_auto_mode_uses_browser_when_api_is_unavailable(self) -> None:
        platform = get_exposure_platform("github")
        web_candidate = {
            "repositoryUrl": "https://github.com/example/acme",
            "branch": "main",
            "filePath": "settings.py",
            "fileUrl": "https://github.com/example/acme/blob/main/settings.py",
        }
        env = {"DARKWEB_GITHUB_TOKEN": "token", "DARKWEB_GITHUB_CODE_SEARCH_MODE": "auto"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(
                code,
                "_collect_github_api_search_results_incremental",
                return_value=([], "github:api:rate_limited", {}),
            ),
            patch.object(
                code,
                "_collect_web_search_results_incremental",
                return_value=([web_candidate], "", {"last_page_scanned": 1}),
            ) as web_search,
        ):
            rows, issue, state = code._collect_search_results_incremental(
                platform,
                "https://github.com/search?q=acme&type=code",
                "state.json",
                page_limit=1,
                browser_fallback=True,
            )

        self.assertEqual(rows, [web_candidate])
        self.assertEqual(issue, "")
        self.assertEqual(state["cursor_mode"], "api+browser")
        self.assertEqual(code.github_code_search_status_payload()["lastUsedChannel"], "browser")
        web_search.assert_called_once()

    def test_api_mode_requires_token_and_does_not_fall_back(self) -> None:
        platform = get_exposure_platform("github")
        with (
            patch.dict(os.environ, {"DARKWEB_GITHUB_CODE_SEARCH_MODE": "api"}, clear=True),
            patch.object(code, "_collect_web_search_results_incremental") as web_search,
        ):
            rows, issue, state = code._collect_search_results_incremental(
                platform,
                "https://github.com/search?q=acme&type=code",
                None,
                page_limit=1,
                browser_fallback=True,
            )

        self.assertEqual(rows, [])
        self.assertEqual(issue, "github:api:auth_required")
        self.assertEqual(state, {})
        web_search.assert_not_called()

    def test_api_query_plan_uses_one_domain_alias_and_no_marker_fanout(self) -> None:
        env = {"DARKWEB_GITHUB_TOKEN": "token", "DARKWEB_GITHUB_CODE_SEARCH_MODE": "auto"}
        with patch.dict(os.environ, env, clear=True):
            domain_queries = code._expanded_search_queries_for_platform("github", "example.com", ["token", "password"])
            company_queries = code._expanded_search_queries_for_platform("github", "Example Company", ["token", "password"])

        self.assertEqual(domain_queries, ["@example.com"])
        self.assertEqual(company_queries, [])

    def test_candidate_identity_ignores_url_fragment(self) -> None:
        base = {
            "repositoryUrl": "https://github.com/example/acme",
            "branch": "main",
            "filePath": "settings.py",
            "fileUrl": "https://github.com/example/acme/blob/main/settings.py#L10",
        }
        changed_fragment = {**base, "fileUrl": "https://github.com/example/acme/blob/main/settings.py#L20"}
        self.assertEqual(code._candidate_identity(base), code._candidate_identity(changed_fragment))

    def test_browser_child_environment_drops_github_credentials(self) -> None:
        env = {
            "DARKWEB_GITHUB_TOKEN": "one",
            "DARKWEB_GITHUB_TOKEN_FILE": "token-file",
            "GITHUB_TOKEN": "two",
            "GH_TOKEN": "three",
            "KEEP_ME": "yes",
        }
        with patch.dict(os.environ, env, clear=True):
            child_env = _browser_child_environment()

        self.assertEqual(child_env["KEEP_ME"], "yes")
        for name in ("DARKWEB_GITHUB_TOKEN", "DARKWEB_GITHUB_TOKEN_FILE", "GITHUB_TOKEN", "GH_TOKEN"):
            self.assertNotIn(name, child_env)

    def test_platform_session_artifacts_are_not_public_static_files(self) -> None:
        self.assertTrue(_is_private_collector_output_path("/collector-output/platform_sessions"))
        self.assertTrue(_is_private_collector_output_path("/collector-output/platform_sessions/github/storage_state.json"))
        self.assertFalse(_is_private_collector_output_path("/collector-output/code_monitoring/evidence.json"))

    def test_continuous_status_includes_github_channel_state(self) -> None:
        with patch.dict(os.environ, {"DARKWEB_GITHUB_CODE_SEARCH_MODE": "browser"}, clear=True):
            status = get_code_monitoring_continuous_status()

        self.assertEqual(status["github_search"]["activeChannel"], "browser")


if __name__ == "__main__":
    unittest.main()
