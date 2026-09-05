from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from darkweb_collector.runtime import default_db_path, output_root


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default

def _flocks_api_key() -> str:
    direct_value = os.environ.get("FLOCKS_API_KEY", "").strip()
    if direct_value:
        return direct_value

    secret_file = os.environ.get("FLOCKS_SECRET_FILE", "").strip()
    if not secret_file:
        return ""

    secret_id = os.environ.get(
        "FLOCKS_API_TOKEN_SECRET_ID", "server_api_token"
    ).strip() or "server_api_token"
    secret_path = Path(secret_file).expanduser()
    try:
        payload = json.loads(secret_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"unable to read Flocks secret file: {secret_path}"
        ) from exc

    token = str(payload.get(secret_id) or "").strip()
    if not token:
        raise ValueError(
            f"Flocks secret file does not contain secret id: {secret_id}"
        )
    return token


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    reports_dir: Path
    adapter_mode: str = "mock"
    delivery_mode: str = "mock"
    flocks_base_url: str = ""
    flocks_api_key: str = ""
    workflow_id: str = "threat_intel_search_pipeline"
    max_concurrent_runs: int = 2
    max_queued_runs: int = 50
    flocks_poll_interval_seconds: float = 2.0
    flocks_execution_timeout_seconds: float = 1800.0
    http_timeout_seconds: float = 15.0
    mock_analysis_delay_seconds: float = 0.05
    scheduler_poll_seconds: float = 5.0
    allowed_callback_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")

    @classmethod
    def from_env(cls) -> "Settings":
        allowed_hosts = tuple(
            host.strip().lower()
            for host in os.environ.get(
                "DARKWEB_AI_AGGREGATION_CALLBACK_ALLOWED_HOSTS",
                "localhost,127.0.0.1,::1",
            ).split(",")
            if host.strip()
        )
        return cls(
            database_path=default_db_path(),
            reports_dir=output_root() / "ai-aggregation" / "reports",
            adapter_mode=os.environ.get(
                "DARKWEB_AI_AGGREGATION_MODE", "mock"
            ).strip().lower(),
            delivery_mode=os.environ.get(
                "DARKWEB_AI_AGGREGATION_DELIVERY_MODE", "mock"
            ).strip().lower(),
            flocks_base_url=os.environ.get("FLOCKS_BASE_URL", "").strip().rstrip("/"),
            flocks_api_key=_flocks_api_key(),
            workflow_id=os.environ.get(
                "DARKWEB_AI_AGGREGATION_WORKFLOW_ID",
                "threat_intel_search_pipeline",
            ).strip(),
            max_concurrent_runs=_positive_int(
                "DARKWEB_AI_AGGREGATION_MAX_CONCURRENT", 2
            ),
            max_queued_runs=_positive_int("DARKWEB_AI_AGGREGATION_MAX_QUEUED", 50),
            flocks_poll_interval_seconds=_positive_float(
                "DARKWEB_AI_AGGREGATION_FLOCKS_POLL_SECONDS", 2.0
            ),
            flocks_execution_timeout_seconds=_positive_float(
                "DARKWEB_AI_AGGREGATION_FLOCKS_TIMEOUT_SECONDS", 1800.0
            ),
            http_timeout_seconds=_positive_float(
                "DARKWEB_AI_AGGREGATION_HTTP_TIMEOUT_SECONDS", 15.0
            ),
            mock_analysis_delay_seconds=_positive_float(
                "DARKWEB_AI_AGGREGATION_MOCK_DELAY_SECONDS", 0.05
            ),
            scheduler_poll_seconds=_positive_float(
                "DARKWEB_AI_AGGREGATION_SCHEDULER_POLL_SECONDS", 5.0
            ),
            allowed_callback_hosts=allowed_hosts,
        )

    def validate(self) -> None:
        if self.adapter_mode not in {"mock", "live"}:
            raise ValueError("DARKWEB_AI_AGGREGATION_MODE must be mock or live")
        if self.delivery_mode not in {"mock", "live"}:
            raise ValueError(
                "DARKWEB_AI_AGGREGATION_DELIVERY_MODE must be mock or live"
            )
        live = self.adapter_mode == "live" or self.delivery_mode == "live"
        if live and not self.flocks_base_url:
            raise ValueError("FLOCKS_BASE_URL is required in live mode")
        if live:
            parsed = urlparse(self.flocks_base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "FLOCKS_BASE_URL must be an absolute http(s) origin without "
                    "credentials, path, query, or fragment"
                )
        if live and not self.flocks_api_key:
            raise ValueError("FLOCKS_API_KEY is required in live mode")
        if self.delivery_mode == "live" and not self.allowed_callback_hosts:
            raise ValueError("at least one callback host must be allowed in live delivery mode")

