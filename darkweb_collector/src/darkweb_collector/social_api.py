from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from darkweb_collector import social_monitoring as service


router = APIRouter()


def _actor(request: Request) -> dict:
    actor = getattr(request.state, "current_user", None)
    if not actor:
        raise HTTPException(status_code=401, detail="authentication required")
    return actor


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.SocialMonitoringError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/api/users")
def users(request: Request) -> list[dict]:
    return _call(service.list_users_payload, _actor(request))


@router.post("/api/users", status_code=201)
def create_user(request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.create_user_payload, _actor(request), payload)


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.update_user_payload, _actor(request), user_id, payload)


@router.delete("/api/users/{user_id}", status_code=204)
def remove_user(user_id: int, request: Request) -> None:
    return _call(service.delete_user_payload, _actor(request), user_id)


@router.post("/api/users/{user_id}/password")
def change_user_password(user_id: int, request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.change_user_password, _actor(request), user_id, str(payload.get("newPassword") or ""))


@router.get("/api/social-monitoring/summary")
def social_summary() -> dict:
    return _call(service.summary_payload)


@router.get("/api/social-monitoring/platforms")
def social_platforms() -> list[dict]:
    return _call(service.platform_status_payload)


@router.get("/api/social-monitoring/platform-config")
def social_platform_config(request: Request) -> dict:
    return _call(service.platform_config_payload, _actor(request))


@router.put("/api/social-monitoring/platform-config/{platform}")
def save_social_platform_config(platform: str, request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.save_platform_config_payload, _actor(request), platform, payload)


@router.delete("/api/social-monitoring/platform-config/{platform}")
def clear_social_platform_config(platform: str, request: Request) -> dict:
    return _call(service.clear_platform_config_payload, _actor(request), platform)


@router.post("/api/social-monitoring/telegram-session/start")
def start_telegram_session(request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.start_telegram_session_payload, _actor(request), payload)


@router.post("/api/social-monitoring/telegram-session/complete")
def complete_telegram_session(request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.complete_telegram_session_payload, _actor(request), payload)


@router.delete("/api/social-monitoring/telegram-session/{attempt_id}")
def cancel_telegram_session(attempt_id: str, request: Request) -> dict:
    return _call(service.cancel_telegram_session_payload, _actor(request), attempt_id)


@router.get("/api/social-monitoring/campaigns")
def social_campaigns() -> list[dict]:
    return _call(service.list_campaigns_payload)


@router.post("/api/social-monitoring/campaigns", status_code=201)
def create_social_campaign(request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.save_campaign_payload, _actor(request), payload)


@router.patch("/api/social-monitoring/campaigns/{campaign_id}")
def update_social_campaign(campaign_id: int, request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.save_campaign_payload, _actor(request), payload, campaign_id)


@router.delete("/api/social-monitoring/campaigns/{campaign_id}", status_code=204)
def remove_social_campaign(campaign_id: int, request: Request) -> None:
    return _call(service.remove_campaign_payload, _actor(request), campaign_id)


@router.get("/api/social-monitoring/scans")
def social_scans(campaign_id: int | None = Query(default=None, alias="campaignId"), limit: int = 100) -> list[dict]:
    return _call(service.list_scans_payload, campaign_id, limit)


@router.get("/api/social-monitoring/events")
def social_events(status: str | None = None, platform: str | None = None, limit: int = 200) -> list[dict]:
    return _call(service.list_events_payload, status, platform, limit)


@router.get("/api/social-monitoring/events/{event_id}")
def social_event_detail(event_id: int) -> dict:
    return _call(service.get_event_payload, event_id)


@router.get("/api/social-monitoring/events/{event_id}/evidence")
def social_event_evidence(event_id: int) -> list[dict]:
    return _call(service.list_event_evidence_payload, event_id)


@router.post("/api/social-monitoring/events/{event_id}/claim")
def claim_social_event(event_id: int, request: Request) -> dict:
    return _call(service.claim_event_payload, _actor(request), event_id)


@router.post("/api/social-monitoring/events/{event_id}/verify")
def verify_social_event(event_id: int, request: Request, payload: dict[str, Any]) -> dict:
    return _call(service.verify_event_payload, _actor(request), event_id, payload)


@router.post("/api/social-monitoring/events/{event_id}/evidence/upload", status_code=201)
async def upload_social_evidence(event_id: int, request: Request, file: UploadFile = File(...)) -> dict:
    content = await file.read(service.MAX_EVIDENCE_BYTES + 1)
    return _call(
        service.save_evidence_payload,
        _actor(request),
        event_id,
        file.filename or "evidence",
        file.content_type or "application/octet-stream",
        content,
    )


@router.post("/api/social-monitoring/events/{event_id}/evidence/capture", status_code=201)
def capture_social_evidence(event_id: int, request: Request) -> list[dict]:
    return _call(service.capture_event_evidence_payload, _actor(request), event_id)


@router.post("/api/social-monitoring/events/{event_id}/evidence/{evidence_id}/redact", status_code=201)
def redact_social_evidence(event_id: int, evidence_id: int, request: Request, payload: dict[str, Any]) -> dict:
    return _call(
        service.redact_evidence_payload,
        _actor(request),
        event_id,
        evidence_id,
        list(payload.get("rectangles") or []),
        bool(payload.get("approve", True)),
    )


@router.get("/api/social-monitoring/evidence/{evidence_id}/content")
def social_evidence_content(evidence_id: int, request: Request) -> FileResponse:
    path, mime_type = _call(service.read_evidence_payload, _actor(request), evidence_id)
    if mime_type == "text/html":
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
            headers={"X-Content-Type-Options": "nosniff"},
        )
    return FileResponse(path, media_type=mime_type, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/api/social-monitoring/events/{event_id}/publish", status_code=201)
def publish_social_event(event_id: int, request: Request) -> dict:
    return _call(service.publish_event_payload, _actor(request), event_id)


@router.post("/api/social-monitoring/events/{event_id}/close")
def close_social_event(event_id: int, request: Request) -> dict:
    return _call(service.close_event_payload, _actor(request), event_id)


@router.get("/api/social-monitoring/events/{event_id}/report-data")
def social_report_data(event_id: int, request: Request) -> dict:
    return _call(service.report_data_payload, _actor(request), event_id)


@router.post("/api/social-monitoring/events/{event_id}/report-generated")
def social_report_generated(event_id: int, request: Request, payload: dict[str, Any]) -> dict:
    return _call(
        service.record_report_generated,
        _actor(request),
        event_id,
        str(payload.get("fileName") or ""),
        str(payload.get("sha256") or ""),
    )


@router.get("/api/social-monitoring/notifications")
def social_notifications(
    request: Request,
    limit: int = 100,
    unread_only: bool = Query(default=False, alias="unreadOnly"),
) -> list[dict]:
    return _call(service.notifications_payload, _actor(request), limit, unread_only)


@router.post("/api/social-monitoring/notifications/{publication_id}/read")
def read_social_notification(publication_id: int, request: Request) -> dict:
    return _call(service.mark_notification_read_payload, _actor(request), publication_id)
