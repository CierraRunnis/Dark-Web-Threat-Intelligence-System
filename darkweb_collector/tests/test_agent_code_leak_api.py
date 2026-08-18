from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.api_app as api_app
import darkweb_collector.code_monitoring as code_monitoring


def _request(*, api_key: str = "", authorization: str = "") -> Request:
    headers = []
    if api_key:
        headers.append((b"x-api-key", api_key.encode("utf-8")))
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/agent/code-leaks",
            "raw_path": b"/api/agent/code-leaks",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


async def _ok_call_next(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


class AgentApiAuthTests(unittest.TestCase):
    def _authorize(self, request: Request):
        return asyncio.run(api_app.require_api_auth(request, _ok_call_next))

    def test_agent_api_requires_configured_key(self) -> None:
        with patch.dict(os.environ, {api_app.AGENT_API_KEY_ENV: ""}, clear=False):
            response = self._authorize(_request())
        self.assertEqual(503, response.status_code)

    def test_agent_api_rejects_invalid_key(self) -> None:
        with patch.dict(os.environ, {api_app.AGENT_API_KEY_ENV: "agent-secret"}, clear=False):
            response = self._authorize(_request(api_key="wrong"))
        self.assertEqual(401, response.status_code)

    def test_agent_api_accepts_header_and_bearer_keys(self) -> None:
        with patch.dict(os.environ, {api_app.AGENT_API_KEY_ENV: "agent-secret"}, clear=False):
            header_response = self._authorize(_request(api_key="agent-secret"))
            bearer_response = self._authorize(_request(authorization="Bearer agent-secret"))
        self.assertEqual(200, header_response.status_code)
        self.assertEqual(200, bearer_response.status_code)


class AgentCodeLeakPayloadTests(unittest.TestCase):
    def test_agent_detail_embeds_raw_artifact_without_removing_existing_fields(self) -> None:
        secret = "postgres://admin:plain-secret@db.internal/prod"
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_path = Path(tmp_dir) / "artifact.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "code_text": f"DATABASE_URL = '{secret}'",
                        "findings": [{"ruleKey": "db_url", "value": secret}],
                    }
                ),
                encoding="utf-8",
            )
            base_detail = {
                "id": 7,
                "rawPayload": {"code_text": f"DATABASE_URL = '{secret}'"},
                "latestSnapshot": {"id": 11, "rawArtifactPath": str(artifact_path)},
                "snapshots": [
                    {
                        "id": 11,
                        "rawArtifactPath": str(artifact_path),
                        "codeFragment": f"DATABASE_URL = '{secret}'",
                        "maskedFragment": "DATABASE_URL = 'post***prod'",
                        "findings": [{"ruleKey": "db_url", "value": secret}],
                    }
                ],
            }
            with patch.object(code_monitoring, "build_code_hit_detail", return_value=base_detail):
                payload = code_monitoring.build_agent_code_hit_detail(7)

        self.assertEqual(secret, payload["snapshots"][0]["findings"][0]["value"])
        self.assertEqual(secret, payload["snapshots"][0]["rawArtifactContent"]["findings"][0]["value"])
        self.assertEqual(payload["rawPayload"], base_detail["rawPayload"])
        self.assertEqual(
            payload["latestSnapshot"]["rawArtifactContent"],
            payload["snapshots"][0]["rawArtifactContent"],
        )

    def test_agent_list_returns_full_details_and_clamps_limit(self) -> None:
        detail = {"id": 7, "rawPayload": {}, "snapshots": [], "findings": []}
        with (
            patch.object(api_app, "list_code_hits_payload", return_value=[{"id": 7}, {"id": 8}]) as list_hits,
            patch.object(api_app, "build_agent_code_hit_detail", return_value=detail) as build_detail,
        ):
            payload = api_app.agent_code_leaks(limit=1)

        self.assertEqual({"count": 1, "items": [detail]}, payload)
        self.assertEqual(1, list_hits.call_args.kwargs["limit"])
        self.assertTrue(list_hits.call_args.kwargs["include_suppressed"])
        build_detail.assert_called_once_with(7)

    def test_missing_agent_detail_returns_404(self) -> None:
        with patch.object(api_app, "build_agent_code_hit_detail", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                api_app.agent_code_leak_detail(999)
        self.assertEqual(404, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()

