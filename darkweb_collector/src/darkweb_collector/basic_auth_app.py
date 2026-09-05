from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from darkweb_collector.api_app import app
from darkweb_collector.http_basic_auth import (
    http_basic_auth_enabled,
    http_basic_authorization_valid,
    http_basic_challenge_header,
    validate_http_basic_auth_config,
)
from darkweb_collector.http_basic_cookie import (
    BASIC_AUTH_COOKIE_NAME,
    http_basic_gate_cookie_valid,
    issue_http_basic_gate_cookie,
)


_OUTER_AUTH_EXEMPT_PATHS = {"/api/health", "/api/ai/intelligence"}
_OUTER_AUTH_EXEMPT_PREFIXES = ("/api/agent/",)


class HttpBasicGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if (
            not http_basic_auth_enabled()
            or request.method == "OPTIONS"
            or request.url.path in _OUTER_AUTH_EXEMPT_PATHS
            or request.url.path.startswith(_OUTER_AUTH_EXEMPT_PREFIXES)
        ):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        basic_attempted = authorization.partition(" ")[0].casefold() == "basic"
        basic_valid = basic_attempted and http_basic_authorization_valid(authorization)
        cookie_valid = http_basic_gate_cookie_valid(
            request.cookies.get(BASIC_AUTH_COOKIE_NAME, "")
        )
        if not basic_valid and (basic_attempted or not cookie_valid):
            return JSONResponse(
                status_code=401,
                content={"detail": "HTTP Basic authentication required"},
                headers={
                    "WWW-Authenticate": http_basic_challenge_header(),
                    "Cache-Control": "no-store",
                },
            )

        response = await call_next(request)
        if basic_valid:
            cookie_value, ttl_seconds = issue_http_basic_gate_cookie()
            response.set_cookie(
                key=BASIC_AUTH_COOKIE_NAME,
                value=cookie_value,
                max_age=ttl_seconds,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
                path="/",
            )
        return response


validate_http_basic_auth_config()
app.add_middleware(HttpBasicGateMiddleware)
