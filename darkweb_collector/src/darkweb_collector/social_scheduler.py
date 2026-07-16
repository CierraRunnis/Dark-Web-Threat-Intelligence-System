from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Protocol

from darkweb_collector.social_adapters import CollectRequest, SocialAdapter, get_social_adapter
from darkweb_collector.social_adapters.base import decode_cursor_map, encode_cursor_map


SOCIAL_SCAN_INTERVAL_SECONDS = 1800
SUPPORTED_SOCIAL_PLATFORMS = ("x", "facebook", "youtube", "telegram")


class SocialMonitoringService(Protocol):
    def list_due_social_campaign_platforms(self, now: str | None = None) -> list[dict[str, Any]]:
        ...

    def claim_social_scan(
        self,
        campaign_id: int,
        platform: str,
        scheduled_at: str | None = None,
    ) -> int | Mapping[str, Any] | None:
        ...

    def finish_social_scan(
        self,
        scan_run_id: int,
        *,
        stats: Mapping[str, Any],
        status: str,
        error: str | None,
        cursor: str | None,
    ) -> Any:
        ...

    def upsert_social_post_event(
        self,
        campaign_id: int,
        scan_run_id: int,
        post: Mapping[str, Any],
    ) -> Any:
        ...

    def update_social_source_state(
        self,
        source_id: int,
        *,
        cursor: str | None,
        status: str,
        error: str | None,
    ) -> Any:
        ...


def _service_module() -> ModuleType:
    """Delay the import so adapter/unit tests do not require the database service."""
    return importlib.import_module("darkweb_collector.social_monitoring")


def _as_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def anchored_scan_slot(
    anchor: str | datetime,
    now: str | datetime,
    *,
    interval_seconds: int = SOCIAL_SCAN_INTERVAL_SECONDS,
) -> datetime | None:
    anchor_utc = _as_utc(anchor)
    now_utc = _as_utc(now)
    if now_utc < anchor_utc:
        return None
    elapsed = int((now_utc - anchor_utc).total_seconds())
    return anchor_utc + timedelta(seconds=(elapsed // interval_seconds) * interval_seconds)


def is_anchored_scan_due(
    anchor: str | datetime,
    last_scheduled_at: str | datetime | None,
    now: str | datetime,
    *,
    end_at: str | datetime | None = None,
) -> bool:
    now_utc = _as_utc(now)
    if end_at is not None and now_utc > _as_utc(end_at):
        return False
    current_slot = anchored_scan_slot(anchor, now_utc)
    if current_slot is None:
        return False
    if last_scheduled_at is None:
        return True
    return current_slot > _as_utc(last_scheduled_at)


def due_campaign_platforms(
    campaigns: Iterable[Mapping[str, Any]],
    *,
    now: str | datetime,
    active: set[tuple[int, str]] | None = None,
) -> list[dict[str, Any]]:
    """Pure scheduling helper shared by the DB service and offline tests."""
    active_keys = active or set()
    due: list[dict[str, Any]] = []
    for campaign in campaigns:
        if not bool(campaign.get("enabled", True)):
            continue
        campaign_id = int(campaign.get("campaign_id") or campaign.get("id") or 0)
        anchor = campaign.get("anchor_at") or campaign.get("enabled_at") or campaign.get("start_at")
        if not campaign_id or not anchor:
            continue
        platforms = campaign.get("platforms") or SUPPORTED_SOCIAL_PLATFORMS
        if isinstance(platforms, str):
            platforms = [item.strip() for item in platforms.split(",") if item.strip()]
        last_runs = campaign.get("last_scheduled_at") or {}
        for raw_platform in platforms:
            platform = str(raw_platform).lower()
            if platform not in SUPPORTED_SOCIAL_PLATFORMS or (campaign_id, platform) in active_keys:
                continue
            last_scheduled = last_runs.get(platform) if isinstance(last_runs, Mapping) else last_runs
            if not is_anchored_scan_due(anchor, last_scheduled, now, end_at=campaign.get("end_at")):
                continue
            slot = anchored_scan_slot(anchor, now)
            due.append(
                {
                    **dict(campaign),
                    "campaign_id": campaign_id,
                    "platform": platform,
                    "scheduled_at": slot.isoformat() if slot else None,
                }
            )
    return due


def _claim_id(claim: int | Mapping[str, Any] | None) -> int | None:
    if claim is None or claim is False:
        return None
    if isinstance(claim, Mapping):
        value = claim.get("scan_run_id") or claim.get("id")
        return int(value) if value else None
    return int(claim)


def _finish_scan(
    service: SocialMonitoringService,
    scan_run_id: int,
    *,
    stats: Mapping[str, Any],
    status: str,
    error: str | None,
    cursor: str | None,
) -> None:
    service.finish_social_scan(
        scan_run_id,
        stats=stats,
        status=status,
        error=error,
        cursor=cursor,
    )


def enqueue_due_social_scans(
    dispatcher: Callable[[dict[str, Any]], str | None],
    *,
    now: datetime | None = None,
    service: SocialMonitoringService | None = None,
) -> list[dict[str, Any]]:
    selected_service = service or _service_module()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates = selected_service.list_due_social_campaign_platforms(now=now_utc.isoformat())
    dispatched: list[dict[str, Any]] = []
    for candidate in candidates:
        payload = dict(candidate)
        campaign_id = int(payload.get("campaign_id") or payload.get("campaignId") or payload.get("id") or 0)
        platform = str(payload.get("platform") or "").lower()
        scheduled_at = payload.get("scheduled_at") or payload.get("scheduledAt")
        if not campaign_id or platform not in SUPPORTED_SOCIAL_PLATFORMS:
            continue
        source_cursor_map = {
            str(source.get("value") or source.get("sourceValue") or source.get("source_value") or ""): source.get("cursor")
            for source in payload.get("sources", [])
            if isinstance(source, Mapping)
            and (source.get("value") or source.get("sourceValue") or source.get("source_value"))
            and source.get("cursor")
        }
        if source_cursor_map and platform != "x":
            cursor_map = decode_cursor_map(str(payload.get("cursor") or "") or None)
            cursor_map.update(source_cursor_map)
            payload["cursor"] = encode_cursor_map(cursor_map)
        try:
            claim = selected_service.claim_social_scan(campaign_id, platform, scheduled_at=scheduled_at)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 409:
                continue
            raise
        scan_run_id = _claim_id(claim)
        if scan_run_id is None:
            continue
        task_payload = {
            **payload,
            "campaign_id": campaign_id,
            "platform": platform,
            "scan_run_id": scan_run_id,
        }
        try:
            task_id = dispatcher(task_payload)
        except Exception as exc:
            _finish_scan(
                selected_service,
                scan_run_id,
                stats={"candidate_count": 0, "new_count": 0, "duplicate_count": 0},
                status="failed",
                error=str(exc),
                cursor=str(payload.get("cursor") or "") or None,
            )
            continue
        if task_id:
            dispatched.append(
                {
                    "campaign_id": campaign_id,
                    "platform": platform,
                    "scan_run_id": scan_run_id,
                    "job_id": task_id,
                    "queue_name": "social_api",
                }
            )
        else:
            _finish_scan(
                selected_service,
                scan_run_id,
                stats={"candidate_count": 0, "new_count": 0, "duplicate_count": 0},
                status="failed",
                error="dispatcher returned no task id",
                cursor=str(payload.get("cursor") or "") or None,
            )
    return dispatched


def _values(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = payload.get(key) or ()
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",")]
    result = []
    for value in values:
        if isinstance(value, Mapping):
            raw = (
                value.get("value") or value.get("term") or value.get("source")
                or value.get("source_value") or value.get("sourceValue") or value.get("url")
            )
        else:
            raw = value
        clean = str(raw or "").strip()
        if clean:
            result.append(clean)
    return tuple(result)


def build_collect_request(payload: Mapping[str, Any]) -> CollectRequest:
    keywords = list(_values(payload, "keywords"))
    for key in ("region_terms", "target_terms", "threat_terms"):
        keywords.extend(_values(payload, key))
    terms = payload.get("terms")
    if isinstance(terms, Mapping):
        for key in ("region", "target", "threat"):
            values = terms.get(key) or ()
            if isinstance(values, str):
                values = [values]
            keywords.extend(str(value).strip() for value in values if str(value).strip())
    return CollectRequest(
        keywords=tuple(dict.fromkeys(keywords)),
        sources=_values(payload, "sources"),
        cursor=str(payload.get("cursor") or "") or None,
        since=str(payload.get("last_success_at") or payload.get("since") or "") or None,
        limit=max(int(payload.get("limit") or 100), 1),
    )


def _created(result: Any) -> bool:
    if isinstance(result, tuple) and len(result) >= 2:
        return bool(result[1])
    if isinstance(result, Mapping):
        status = str(result.get("status") or "").lower()
        if status:
            return status in {"created", "inserted", "new"}
        return bool(result.get("created") or result.get("is_new"))
    return bool(result)


def match_social_post(post: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    text = f"{post.get('title') or ''}\n{post.get('original_text') or post.get('originalText') or ''}".casefold()

    def matches(key: str) -> tuple[str, ...]:
        return tuple(value for value in _values(payload, key) if value.casefold() in text)

    excluded = matches("exclude_terms")
    if excluded:
        return False, excluded
    regions = matches("region_terms")
    targets = matches("target_terms")
    threats = matches("threat_terms")
    matched = tuple(dict.fromkeys((*regions, *targets, *threats)))
    return bool(threats and (targets or regions)), matched


def _update_sources(
    service: SocialMonitoringService,
    payload: Mapping[str, Any],
    *,
    cursor: str | None,
    status: str,
    error: str | None,
) -> None:
    cursor_map = decode_cursor_map(cursor)
    for source in payload.get("sources", ()) or ():
        if not isinstance(source, Mapping) or not (source.get("id") or source.get("sourceId")):
            continue
        cursor_key = str(
            source.get("value") or source.get("source") or source.get("source_value")
            or source.get("sourceValue") or source.get("url") or ""
        )
        source_cursor = cursor_map.get(cursor_key) or cursor
        service.update_social_source_state(
            int(source.get("id") or source.get("sourceId")),
            cursor=source_cursor,
            status=status,
            error=error,
        )


def execute_claimed_social_scan(
    payload: Mapping[str, Any],
    *,
    service: SocialMonitoringService | None = None,
    adapter: SocialAdapter | None = None,
) -> dict[str, Any]:
    selected_service = service or _service_module()
    campaign_id = int(payload["campaign_id"])
    scan_run_id = int(payload["scan_run_id"])
    platform = str(payload["platform"]).lower()
    request = build_collect_request(payload)
    selected_adapter = adapter or get_social_adapter(platform)
    try:
        result = selected_adapter.collect(request)
        new_count = 0
        duplicate_count = 0
        for post in result.posts:
            post_payload = post.to_dict()
            matched, matched_terms = match_social_post(post_payload, payload)
            if not matched:
                continue
            post_payload["matched_terms"] = list(matched_terms)
            persisted = selected_service.upsert_social_post_event(
                campaign_id,
                scan_run_id,
                post_payload,
            )
            if _created(persisted):
                new_count += 1
            else:
                duplicate_count += 1
        stats = {
            "candidate_count": len(result.posts),
            "new_count": new_count,
            "duplicate_count": duplicate_count,
            "coverage": result.coverage.to_dict(),
        }
        status = "coverage_limited" if result.coverage.limited else "succeeded"
        _finish_scan(
            selected_service,
            scan_run_id,
            stats=stats,
            status=status,
            error=None,
            cursor=result.next_cursor,
        )
        _update_sources(
            selected_service,
            payload,
            cursor=result.next_cursor,
            status="healthy" if result.coverage.configured else "unconfigured",
            error=None if result.coverage.configured else result.coverage.reason,
        )
        return {**stats, "status": status, "cursor": result.next_cursor}
    except Exception as exc:
        stats = {"candidate_count": 0, "new_count": 0, "duplicate_count": 0}
        _finish_scan(
            selected_service,
            scan_run_id,
            stats=stats,
            status="failed",
            error=str(exc),
            cursor=request.cursor,
        )
        _update_sources(
            selected_service,
            payload,
            cursor=request.cursor,
            status="failed",
            error=str(exc),
        )
        raise
