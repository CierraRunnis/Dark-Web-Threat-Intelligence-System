from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageDraw, UnidentifiedImageError

from darkweb_collector.db import (
    claim_social_event,
    create_social_action,
    create_social_campaign,
    create_social_evidence,
    create_social_publication,
    create_social_scan_run,
    create_user,
    delete_social_campaign,
    delete_user,
    finish_social_scan_run,
    get_active_social_scan_run,
    get_social_campaign,
    get_social_event,
    get_social_evidence,
    get_user,
    get_user_by_username,
    get_db_connection,
    list_social_actions,
    list_social_campaigns,
    list_social_evidence,
    list_social_event_snapshots,
    list_social_events,
    list_social_publications,
    list_social_scan_runs,
    list_social_sources,
    list_social_terms,
    list_users,
    mark_social_publication_read,
    replace_social_sources,
    replace_social_terms,
    update_social_campaign,
    update_social_event,
    update_social_source,
    update_user,
    update_user_password,
    upsert_social_event,
)


PLATFORMS = ("x", "facebook", "youtube", "telegram")
ROLES = ("admin", "analyst")
VERIFICATION_RESULTS = ("credible", "monitor", "falsePositive")
SEVERITIES = ("normal", "major", "emergency")
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
SOCIAL_PLATFORM_HOSTS = {
    "x": ("x.com", "twitter.com"),
    "facebook": ("facebook.com", "fb.com"),
    "youtube": ("youtube.com", "youtu.be"),
    "telegram": ("t.me", "telegram.me"),
}


class SocialMonitoringError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_instant(value: str, timezone_name: str = "Asia/Shanghai") -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_load(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _camel_key(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _public_row(row: dict | None, *, json_fields: tuple[str, ...] = ()) -> dict | None:
    if row is None:
        return None
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if key in {"password_hash", "password_salt", "storage_path"}:
            continue
        if key in json_fields:
            value = _json_load(value, [] if key.endswith("_json") else {})
        if key == "enabled" or key == "approved":
            value = bool(value)
        payload[_camel_key(key.removesuffix("_json"))] = value
    return payload


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if len(password) < 6:
        raise SocialMonitoringError("password must be at least 6 characters")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return base64.b64encode(derived).decode("ascii"), base64.b64encode(salt).decode("ascii")


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    try:
        expected = base64.b64decode(password_hash)
        salt = base64.b64decode(password_salt)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


def ensure_initial_admin(username: str, password: str) -> dict:
    now = utc_now()
    with get_db_connection() as connection:
        existing = get_user_by_username(connection, username)
        if existing is None:
            password_hash, salt = hash_password(password)
            user_id = create_user(
                connection,
                {
                    "username": username,
                    "display_name": "管理员",
                    "role": "admin",
                    "password_hash": password_hash,
                    "password_salt": salt,
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            existing = get_user(connection, user_id)
        return _public_row(existing) or {}


def authenticate_user(username: str, password: str) -> dict | None:
    now = utc_now()
    with get_db_connection() as connection:
        user = get_user_by_username(connection, username)
        if user is None or not user["enabled"]:
            return None
        if not verify_password(password, user["password_hash"], user["password_salt"]):
            return None
        update_user(connection, int(user["id"]), {"last_login_at": now, "updated_at": now})
        user = get_user(connection, int(user["id"]))
        return _public_row(user)


def validate_session_user(user_id: int, session_version: int) -> dict | None:
    with get_db_connection() as connection:
        user = get_user(connection, user_id)
    if user is None or not user["enabled"] or int(user["session_version"]) != int(session_version):
        return None
    return _public_row(user)


def require_role(actor: dict, role: str) -> None:
    if actor.get("role") != role:
        raise SocialMonitoringError("administrator permission required", 403)


def list_users_payload(actor: dict) -> list[dict]:
    require_role(actor, "admin")
    with get_db_connection() as connection:
        return [_public_row(row) or {} for row in list_users(connection)]


def create_user_payload(actor: dict, payload: dict) -> dict:
    require_role(actor, "admin")
    username = str(payload.get("username") or "").strip()
    role = str(payload.get("role") or "analyst")
    if not username:
        raise SocialMonitoringError("username is required")
    if role not in ROLES:
        raise SocialMonitoringError("invalid role")
    password_hash, salt = hash_password(str(payload.get("password") or ""))
    now = utc_now()
    try:
        with get_db_connection() as connection:
            user_id = create_user(
                connection,
                {
                    "username": username,
                    "display_name": str(payload.get("displayName") or username).strip(),
                    "role": role,
                    "password_hash": password_hash,
                    "password_salt": salt,
                    "enabled": bool(payload.get("enabled", True)),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            return _public_row(get_user(connection, user_id)) or {}
    except sqlite3.IntegrityError as exc:
        raise SocialMonitoringError("username already exists", 409) from exc


def update_user_payload(actor: dict, user_id: int, payload: dict) -> dict:
    require_role(actor, "admin")
    values: dict[str, Any] = {"updated_at": utc_now()}
    if "displayName" in payload:
        values["display_name"] = str(payload["displayName"]).strip()
    if "role" in payload:
        if payload["role"] not in ROLES:
            raise SocialMonitoringError("invalid role")
        values["role"] = payload["role"]
    if "enabled" in payload:
        if int(actor["id"]) == int(user_id) and not payload["enabled"]:
            raise SocialMonitoringError("cannot disable the current user")
        values["enabled"] = bool(payload["enabled"])
    with get_db_connection() as connection:
        if update_user(connection, user_id, values) == 0:
            raise SocialMonitoringError("user not found", 404)
        if "enabled" in payload or "role" in payload:
            connection.execute(
                "UPDATE users SET session_version = session_version + 1 WHERE id = ?",
                (int(user_id),),
            )
        return _public_row(get_user(connection, user_id)) or {}


def change_user_password(actor: dict, user_id: int, new_password: str) -> dict:
    if actor.get("role") != "admin" and int(actor["id"]) != int(user_id):
        raise SocialMonitoringError("permission denied", 403)
    password_hash, salt = hash_password(new_password)
    with get_db_connection() as connection:
        if update_user_password(connection, user_id, password_hash, salt, utc_now()) == 0:
            raise SocialMonitoringError("user not found", 404)
        return _public_row(get_user(connection, user_id)) or {}


def delete_user_payload(actor: dict, user_id: int) -> None:
    require_role(actor, "admin")
    if int(actor["id"]) == int(user_id):
        raise SocialMonitoringError("cannot delete the current user")
    try:
        with get_db_connection() as connection:
            if delete_user(connection, user_id) == 0:
                raise SocialMonitoringError("user not found", 404)
    except sqlite3.IntegrityError as exc:
        raise SocialMonitoringError("user has audit records and cannot be deleted; disable it instead", 409) from exc


def _normalise_campaign_input(payload: dict, actor_id: int, *, existing: dict | None = None) -> dict:
    now = utc_now()
    platforms = payload.get("platforms", _json_load((existing or {}).get("platforms_json"), []))
    platforms = list(dict.fromkeys(str(value).lower() for value in platforms))
    if not platforms or any(value not in PLATFORMS for value in platforms):
        raise SocialMonitoringError("platforms must contain supported platforms")
    start_at = str(payload.get("startAt") or (existing or {}).get("start_at") or now)
    enabled = bool(payload.get("enabled", (existing or {}).get("enabled", True)))
    was_enabled = bool((existing or {}).get("enabled", False))
    anchor_at = str(payload.get("anchorAt") or (existing or {}).get("anchor_at") or start_at)
    if existing and enabled and not was_enabled:
        anchor_at = now
    return {
        "name": str(payload.get("name") or (existing or {}).get("name") or "").strip(),
        "start_at": start_at,
        "end_at": payload.get("endAt", (existing or {}).get("end_at")),
        "timezone": str(payload.get("timezone") or (existing or {}).get("timezone") or "Asia/Shanghai"),
        "enabled": enabled,
        "anchor_at": anchor_at,
        "platforms_json": json.dumps(platforms, ensure_ascii=False),
        "created_by": actor_id,
        "created_at": now,
        "updated_at": now,
    }


def _campaign_terms(payload: dict) -> list[dict]:
    terms = payload.get("terms") or {}
    aliases = {"region": "region", "target": "target", "threat": "threat", "exclude": "exclude"}
    return [
        {"term": str(term).strip(), "term_type": term_type}
        for input_key, term_type in aliases.items()
        for term in terms.get(input_key, [])
        if str(term).strip()
    ]


def _campaign_payload(connection: sqlite3.Connection, row: dict) -> dict:
    payload = _public_row(row, json_fields=("platforms_json",)) or {}
    grouped = {"region": [], "target": [], "threat": [], "exclude": []}
    for term in list_social_terms(connection, int(row["id"])):
        grouped.setdefault(str(term["term_type"]), []).append(term["term"])
    payload["terms"] = grouped
    payload["sources"] = [
        _public_row(item, json_fields=("metadata_json",)) or {}
        for item in list_social_sources(connection, int(row["id"]))
    ]
    return payload


def list_campaigns_payload() -> list[dict]:
    with get_db_connection() as connection:
        return [_campaign_payload(connection, row) for row in list_social_campaigns(connection)]


def save_campaign_payload(actor: dict, payload: dict, campaign_id: int | None = None) -> dict:
    require_role(actor, "admin")
    with get_db_connection() as connection:
        existing = get_social_campaign(connection, campaign_id) if campaign_id else None
        if campaign_id and existing is None:
            raise SocialMonitoringError("campaign not found", 404)
        values = _normalise_campaign_input(payload, int(actor["id"]), existing=existing)
        if not values["name"]:
            raise SocialMonitoringError("campaign name is required")
        if campaign_id:
            update_social_campaign(connection, campaign_id, values)
        else:
            campaign_id = create_social_campaign(connection, values)
        if "terms" in payload or not existing:
            replace_social_terms(connection, campaign_id, _campaign_terms(payload), values["updated_at"])
        if "sources" in payload or not existing:
            sources = [
                {
                    "platform": str(item.get("platform") or "").lower(),
                    "source_type": item.get("sourceType") or "account",
                    "source_value": item.get("sourceValue") or "",
                    "label": item.get("label") or "",
                    "metadata_json": json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                }
                for item in payload.get("sources", [])
            ]
            if any(item["platform"] not in PLATFORMS for item in sources):
                raise SocialMonitoringError("source platform is invalid")
            replace_social_sources(connection, campaign_id, sources, values["updated_at"])
        row = get_social_campaign(connection, campaign_id)
        assert row is not None
        return _campaign_payload(connection, row)


def remove_campaign_payload(actor: dict, campaign_id: int) -> None:
    require_role(actor, "admin")
    with get_db_connection() as connection:
        try:
            if delete_social_campaign(connection, campaign_id) == 0:
                raise SocialMonitoringError("campaign not found", 404)
        except sqlite3.IntegrityError as exc:
            raise SocialMonitoringError("campaign already has events and cannot be deleted; disable it instead", 409) from exc


def platform_status_payload() -> list[dict]:
    facebook_state = os.environ.get("SOCIAL_FACEBOOK_STORAGE_STATE", "").strip()
    configured = {
        "x": bool(os.environ.get("SOCIAL_X_BEARER_TOKEN", "").strip()),
        "facebook": bool(os.environ.get("SOCIAL_FACEBOOK_ACCESS_TOKEN", "").strip())
        or bool(facebook_state and Path(facebook_state).expanduser().is_file()),
        "youtube": bool(os.environ.get("SOCIAL_YOUTUBE_API_KEY", "").strip()),
        "telegram": all(
            os.environ.get(name, "").strip()
            for name in ("SOCIAL_TELEGRAM_API_ID", "SOCIAL_TELEGRAM_API_HASH", "SOCIAL_TELEGRAM_SESSION")
        ),
    }
    with get_db_connection() as connection:
        sources = list_social_sources(connection)
    return [
        {
            "platform": platform,
            "configured": configured[platform],
            "coverageLimited": platform in {"facebook", "telegram"},
            "sourceCount": sum(1 for row in sources if row["platform"] == platform and row["enabled"]),
            "status": "configured" if configured[platform] else "missing_credentials",
        }
        for platform in PLATFORMS
    ]


def list_scans_payload(campaign_id: int | None = None, limit: int = 100) -> list[dict]:
    with get_db_connection() as connection:
        return [_public_row(row) or {} for row in list_social_scan_runs(connection, campaign_id, limit)]


def _evidence_public(row: dict) -> dict:
    payload = _public_row(row, json_fields=("redaction_json",)) or {}
    payload["contentUrl"] = f"/api/social-monitoring/evidence/{row['id']}/content"
    return payload


def _event_payload(connection: sqlite3.Connection, row: dict, *, detail: bool = False) -> dict:
    payload = _public_row(row, json_fields=("matched_terms_json",)) or {}
    if detail:
        payload["evidence"] = [_evidence_public(item) for item in list_social_evidence(connection, int(row["id"]))]
        payload["actions"] = [
            _public_row(item, json_fields=("detail_json",)) or {}
            for item in list_social_actions(connection, int(row["id"]))
        ]
        payload["snapshots"] = [
            _public_row(item) or {} for item in list_social_event_snapshots(connection, int(row["id"]))
        ]
    return payload


def list_events_payload(status: str | None = None, platform: str | None = None, limit: int = 200) -> list[dict]:
    with get_db_connection() as connection:
        return [
            _event_payload(connection, row)
            for row in list_social_events(connection, status=status, platform=platform, limit=limit)
        ]


def get_event_payload(event_id: int) -> dict:
    with get_db_connection() as connection:
        row = get_social_event(connection, event_id)
        if row is None:
            raise SocialMonitoringError("event not found", 404)
        return _event_payload(connection, row, detail=True)


def list_event_evidence_payload(event_id: int) -> list[dict]:
    with get_db_connection() as connection:
        if get_social_event(connection, event_id) is None:
            raise SocialMonitoringError("event not found", 404)
        return [_evidence_public(row) for row in list_social_evidence(connection, event_id)]


def _audit(connection: sqlite3.Connection, event_id: int | None, action: str, actor: dict, detail: dict | None = None) -> None:
    create_social_action(
        connection,
        {
            "event_id": event_id,
            "action_type": action,
            "actor_user_id": int(actor["id"]),
            "detail_json": json.dumps(detail or {}, ensure_ascii=False),
            "created_at": utc_now(),
        },
    )


def _require_event_access(actor: dict, event: dict) -> None:
    if actor.get("role") != "admin" and int(event.get("assigned_to") or 0) != int(actor["id"]):
        raise SocialMonitoringError("claim the event before accessing original evidence", 403)


def claim_event_payload(actor: dict, event_id: int) -> dict:
    now = utc_now()
    with get_db_connection() as connection:
        if claim_social_event(connection, event_id, int(actor["id"]), now) == 0:
            if get_social_event(connection, event_id) is None:
                raise SocialMonitoringError("event not found", 404)
            raise SocialMonitoringError("event has already been claimed", 409)
        _audit(connection, event_id, "claimed", actor)
        row = get_social_event(connection, event_id)
        assert row is not None
        return _event_payload(connection, row, detail=True)


def verify_event_payload(actor: dict, event_id: int, payload: dict) -> dict:
    result = str(payload.get("result") or "")
    if result not in VERIFICATION_RESULTS:
        raise SocialMonitoringError("invalid verification result")
    severity = str(payload.get("severity") or "normal")
    if severity not in SEVERITIES:
        raise SocialMonitoringError("invalid severity")
    target_unit = str(payload.get("targetUnit") or "").strip()
    target_industry = str(payload.get("targetIndustry") or "").strip()
    if result != "falsePositive" and not (target_unit or target_industry):
        raise SocialMonitoringError("targetUnit or targetIndustry is required")
    if result != "falsePositive" and not str(payload.get("disposalDirection") or "").strip():
        raise SocialMonitoringError("disposalDirection is required")
    now = utc_now()
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        if actor.get("role") != "admin":
            severity = str(event["severity"] or "normal")
        _require_event_access(actor, event)
        if event["status"] not in {"verifying", "verified"}:
            raise SocialMonitoringError("event is not in verification", 409)
        duration_seconds = max(0, int((_parse_instant(now) - _parse_instant(event["claimed_at"] or now)).total_seconds()))
        update_social_event(
            connection,
            event_id,
            {
                "title": str(payload.get("threatTitle") or event["title"]).strip(),
                "threat_type": str(payload.get("threatType") or "").strip(),
                "target_unit": target_unit,
                "target_industry": target_industry,
                "status": "verified",
                "verification_result": result,
                "evidence_note": str(payload.get("evidenceNote") or ""),
                "disposal_direction": str(payload.get("disposalDirection") or ""),
                "severity": severity,
                "verified_by": int(actor["id"]),
                "verified_at": now,
                "verification_duration_seconds": duration_seconds,
                "updated_at": now,
            },
        )
        _audit(connection, event_id, "verified", actor, {"result": result, "severity": severity})
        row = get_social_event(connection, event_id)
        assert row is not None
        return _event_payload(connection, row, detail=True)


def evidence_root() -> Path:
    configured = os.environ.get("SOCIAL_EVIDENCE_ROOT", "").strip()
    if configured:
        root = Path(configured)
    elif os.environ.get("LOCALAPPDATA", "").strip():
        root = Path(os.environ["LOCALAPPDATA"]) / "DarkWebThreatIntel" / "social-evidence"
    else:
        root = Path.home() / ".darkweb-threat-intel" / "social-evidence"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_evidence_path(relative_path: str) -> Path:
    root = evidence_root()
    path = (root / relative_path).resolve()
    if root != path and root not in path.parents:
        raise SocialMonitoringError("invalid evidence path", 400)
    return path


def save_evidence_payload(actor: dict, event_id: int, filename: str, mime_type: str, content: bytes) -> dict:
    if not content or len(content) > MAX_EVIDENCE_BYTES:
        raise SocialMonitoringError("evidence must be between 1 byte and 10 MB")
    if mime_type not in {"image/png", "image/jpeg", "text/html"}:
        raise SocialMonitoringError("only PNG, JPEG, and HTML evidence is supported")
    if mime_type.startswith("image/"):
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise SocialMonitoringError("invalid image evidence") from exc
    digest = hashlib.sha256(content).hexdigest()
    now = utc_now()
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        _require_event_access(actor, event)
        event_dir = evidence_root() / str(event_id)
        event_dir.mkdir(parents=True, exist_ok=True)
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "text/html": ".html"}[mime_type]
        relative = f"{event_id}/{secrets.token_hex(16)}{suffix}"
        path = _safe_evidence_path(relative)
        path.write_bytes(content)
        evidence_id = create_social_evidence(
            connection,
            {
                "event_id": event_id,
                "evidence_type": "original",
                "original_filename": Path(filename or f"evidence{suffix}").name,
                "storage_path": relative,
                "mime_type": mime_type,
                "sha256": digest,
                "approved": False,
                "created_by": int(actor["id"]),
                "created_at": now,
            },
        )
        _audit(connection, event_id, "evidence_uploaded", actor, {"evidenceId": evidence_id, "sha256": digest})
        row = get_social_evidence(connection, evidence_id)
        assert row is not None
        return _evidence_public(row)


def _capture_page_artifacts(platform: str, source_url: str) -> tuple[bytes, bytes]:
    hostname = (urlparse(source_url).hostname or "").lower()
    allowed_hosts = SOCIAL_PLATFORM_HOSTS.get(platform, ())
    if not any(hostname == item or hostname.endswith(f".{item}") for item in allowed_hosts):
        raise SocialMonitoringError("source URL is outside the selected social platform", 400)
    storage_state = os.environ.get(f"SOCIAL_{platform.upper()}_STORAGE_STATE", "").strip()
    context_options: dict[str, Any] = {"viewport": {"width": 1440, "height": 960}}
    if storage_state:
        state_path = Path(storage_state).expanduser().resolve()
        if not state_path.is_file():
            raise SocialMonitoringError("configured browser storage state was not found", 409)
        context_options["storage_state"] = str(state_path)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(**context_options)
            page = context.new_page()
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1_500)
                html = page.content().encode("utf-8")
                screenshot = page.screenshot(type="png", full_page=True)
            finally:
                context.close()
                browser.close()
    except SocialMonitoringError:
        raise
    except Exception as exc:
        raise SocialMonitoringError(f"authorized browser capture failed: {exc}", 502) from exc
    return html, screenshot


def capture_event_evidence_payload(actor: dict, event_id: int) -> list[dict]:
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        _require_event_access(actor, event)
        platform = str(event["platform"])
        source_url = str(event["source_url"])
    html, screenshot = _capture_page_artifacts(platform, source_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return [
        save_evidence_payload(actor, event_id, f"browser-{timestamp}.html", "text/html", html),
        save_evidence_payload(actor, event_id, f"browser-{timestamp}.png", "image/png", screenshot),
    ]


def redact_evidence_payload(actor: dict, event_id: int, evidence_id: int, rectangles: list[dict], approve: bool) -> dict:
    if not rectangles:
        raise SocialMonitoringError("at least one redaction rectangle is required")
    now = utc_now()
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        source = get_social_evidence(connection, evidence_id)
        if event is None or source is None or int(source["event_id"]) != int(event_id):
            raise SocialMonitoringError("evidence not found", 404)
        _require_event_access(actor, event)
        source_path = _safe_evidence_path(source["storage_path"])
        try:
            with Image.open(source_path) as opened:
                image = opened.convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise SocialMonitoringError("evidence image cannot be opened", 409) from exc
        draw = ImageDraw.Draw(image)
        normalised: list[dict[str, int]] = []
        for rectangle in rectangles:
            try:
                x = max(0, int(rectangle["x"]))
                y = max(0, int(rectangle["y"]))
                width = int(rectangle["width"])
                height = int(rectangle["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SocialMonitoringError("invalid redaction rectangle") from exc
            if width <= 0 or height <= 0 or x >= image.width or y >= image.height:
                raise SocialMonitoringError("invalid redaction rectangle")
            right = min(image.width, x + width)
            bottom = min(image.height, y + height)
            draw.rectangle((x, y, right, bottom), fill="black")
            normalised.append({"x": x, "y": y, "width": right - x, "height": bottom - y})
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        content = buffer.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        relative = f"{event_id}/{secrets.token_hex(16)}-redacted.png"
        _safe_evidence_path(relative).write_bytes(content)
        new_id = create_social_evidence(
            connection,
            {
                "event_id": event_id,
                "evidence_type": "redacted",
                "original_filename": f"redacted-{Path(source['original_filename']).stem}.png",
                "storage_path": relative,
                "mime_type": "image/png",
                "sha256": digest,
                "source_evidence_id": evidence_id,
                "redaction_json": json.dumps(normalised, ensure_ascii=False),
                "approved": bool(approve),
                "created_by": int(actor["id"]),
                "created_at": now,
            },
        )
        _audit(connection, event_id, "evidence_redacted", actor, {"evidenceId": new_id, "sourceEvidenceId": evidence_id})
        row = get_social_evidence(connection, new_id)
        assert row is not None
        return _evidence_public(row)


def read_evidence_payload(actor: dict, evidence_id: int) -> tuple[Path, str]:
    with get_db_connection() as connection:
        evidence = get_social_evidence(connection, evidence_id)
        if evidence is None:
            raise SocialMonitoringError("evidence not found", 404)
        event = get_social_event(connection, int(evidence["event_id"]))
        assert event is not None
        if evidence["evidence_type"] == "original":
            _require_event_access(actor, event)
        _audit(connection, int(event["id"]), "evidence_viewed", actor, {"evidenceId": evidence_id})
        return _safe_evidence_path(evidence["storage_path"]), str(evidence["mime_type"])


def publish_event_payload(actor: dict, event_id: int) -> dict:
    now = utc_now()
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        _require_event_access(actor, event)
        required = (event["title"], event["threat_type"], event["verification_result"], event["disposal_direction"])
        if event["status"] != "verified" or not all(str(value or "").strip() for value in required):
            raise SocialMonitoringError("event verification is incomplete", 409)
        if not (event["target_unit"] or event["target_industry"]):
            raise SocialMonitoringError("event target is missing", 409)
        approved = [row for row in list_social_evidence(connection, event_id) if row["approved"] and row["evidence_type"] == "redacted"]
        if not approved:
            raise SocialMonitoringError("an approved redacted screenshot is required", 409)
        card = {
            "eventId": event_id,
            "threatTitle": event["title"],
            "platform": event["platform"],
            "sourceUrl": event["source_url"],
            "threatType": event["threat_type"],
            "targetUnit": event["target_unit"],
            "targetIndustry": event["target_industry"],
            "discoveredAt": event["discovered_at"],
            "verificationResult": event["verification_result"],
            "disposalDirection": event["disposal_direction"],
            "severity": event["severity"],
            "evidenceIds": [row["id"] for row in approved],
        }
        try:
            publication_id = create_social_publication(
                connection,
                {"event_id": event_id, "card_json": json.dumps(card, ensure_ascii=False), "published_by": actor["id"], "published_at": now},
            )
        except sqlite3.IntegrityError as exc:
            raise SocialMonitoringError("event has already been published", 409) from exc
        update_social_event(connection, event_id, {"status": "published", "published_at_internal": now, "updated_at": now})
        _audit(connection, event_id, "published", actor, {"publicationId": publication_id})
        return {"id": publication_id, "card": card, "publishedAt": now}


def close_event_payload(actor: dict, event_id: int) -> dict:
    now = utc_now()
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        _require_event_access(actor, event)
        if event["status"] not in {"verified", "published"}:
            raise SocialMonitoringError("event cannot be closed in its current status", 409)
        update_social_event(connection, event_id, {"status": "closed", "closed_at": now, "updated_at": now})
        _audit(connection, event_id, "closed", actor)
        row = get_social_event(connection, event_id)
        assert row is not None
        return _event_payload(connection, row, detail=True)


def notifications_payload(actor: dict, limit: int = 100, unread_only: bool = False) -> list[dict]:
    with get_db_connection() as connection:
        result = []
        for row in list_social_publications(connection, int(actor["id"]), limit):
            item = _public_row(row) or {}
            item["card"] = _json_load(row["card_json"], {})
            item.pop("cardJson", None)
            item["read"] = bool(row["read_at"])
            if not unread_only or not item["read"]:
                result.append(item)
        return result


def mark_notification_read_payload(actor: dict, publication_id: int) -> dict:
    now = utc_now()
    with get_db_connection() as connection:
        mark_social_publication_read(connection, publication_id, int(actor["id"]), now)
    return {"ok": True, "readAt": now}


def report_data_payload(actor: dict, event_id: int) -> dict:
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        _require_event_access(actor, event)
        if event["severity"] not in {"major", "emergency"}:
            raise SocialMonitoringError("only major or emergency events support special reports", 409)
        payload = _event_payload(connection, event, detail=True)
        payload["reportTitle"] = f"重大威胁事件专项分析报告：{event['title']}"
        payload["generatedAt"] = utc_now()
        return payload


def record_report_generated(actor: dict, event_id: int, file_name: str, sha256: str) -> dict:
    if len(sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sha256):
        raise SocialMonitoringError("sha256 must be a 64-character hexadecimal digest")
    with get_db_connection() as connection:
        event = get_social_event(connection, event_id)
        if event is None:
            raise SocialMonitoringError("event not found", 404)
        _require_event_access(actor, event)
        _audit(connection, event_id, "report_generated", actor, {"fileName": Path(file_name).name, "sha256": sha256.lower()})
    return {"ok": True, "fileName": Path(file_name).name, "sha256": sha256.lower()}


def summary_payload() -> dict:
    campaigns = list_campaigns_payload()
    scans = list_scans_payload(limit=20)
    events = list_events_payload(limit=1000)
    enabled = [item for item in campaigns if item["enabled"]]
    next_runs = []
    now = datetime.now(timezone.utc)
    for item in enabled:
        try:
            anchor = _parse_instant(str(item["anchorAt"]), str(item.get("timezone") or "Asia/Shanghai"))
            if now < anchor:
                next_runs.append(anchor.timestamp())
            else:
                elapsed = (now - anchor).total_seconds()
                next_runs.append(anchor.timestamp() + (int(elapsed // 1800) + 1) * 1800)
        except (ValueError, TypeError):
            continue
    last_scan = scans[0] if scans else None
    latest_slot = (last_scan or {}).get("scheduledAt")
    current_run_new_count = sum(
        int(item.get("newEventCount") or 0)
        for item in scans
        if latest_slot and item.get("scheduledAt") == latest_slot
    )
    next_run_at = datetime.fromtimestamp(min(next_runs), timezone.utc).isoformat() if next_runs else None
    pending_count = sum(1 for item in events if item["status"] in {"pending", "verifying"})
    major_count = sum(1 for item in events if item["severity"] in {"major", "emergency"})
    return {
        "campaignCount": len(campaigns),
        "enabledCampaignCount": len(enabled),
        "pendingCount": pending_count,
        "pendingVerificationCount": pending_count,
        "majorCount": major_count,
        "majorEventCount": major_count,
        "currentRunNewCount": current_run_new_count,
        "lastUpdatedAt": (last_scan or {}).get("finishedAt"),
        "nextUpdatedAt": next_run_at,
        "nextRunAt": next_run_at,
        "platforms": platform_status_payload(),
    }


# Scheduler-facing service contract.
def list_due_social_campaign_platforms(now: str | None = None) -> list[dict]:
    instant = datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00")).astimezone(timezone.utc)
    due: list[dict] = []
    with get_db_connection() as connection:
        for campaign in list_social_campaigns(connection):
            if not campaign["enabled"]:
                continue
            timezone_name = str(campaign["timezone"] or "Asia/Shanghai")
            start = _parse_instant(str(campaign["start_at"]), timezone_name)
            end = _parse_instant(str(campaign["end_at"]), timezone_name) if campaign["end_at"] else None
            if instant < start or (end and instant > end):
                continue
            anchor = _parse_instant(str(campaign["anchor_at"]), timezone_name)
            ticks = max(0, int((instant - anchor).total_seconds() // 1800))
            scheduled = anchor.timestamp() + ticks * 1800
            for platform in _json_load(campaign["platforms_json"], []):
                active = get_active_social_scan_run(connection, int(campaign["id"]), platform)
                latest = connection.execute(
                    "SELECT scheduled_at FROM social_scan_runs WHERE campaign_id = ? AND platform = ? ORDER BY id DESC LIMIT 1",
                    (campaign["id"], platform),
                ).fetchone()
                scheduled_at = datetime.fromtimestamp(scheduled, timezone.utc).isoformat()
                if active is not None and str(active["scheduled_at"]) < scheduled_at:
                    connection.execute(
                        """
                        UPDATE social_scan_runs
                        SET error_message = 'scan delayed beyond the next 30-minute slot'
                        WHERE id = ? AND status = 'running'
                        """,
                        (int(active["id"]),),
                    )
                if active is None and (latest is None or latest["scheduled_at"] < scheduled_at):
                    terms = list_social_terms(connection, int(campaign["id"]))
                    grouped = {
                        kind: [row["term"] for row in terms if row["term_type"] == kind]
                        for kind in ("region", "target", "threat", "exclude")
                    }
                    sources = [
                        {
                            "id": row["id"],
                            "value": row["source_value"],
                            "type": row["source_type"],
                            "cursor": row["cursor"],
                        }
                        for row in list_social_sources(connection, int(campaign["id"]))
                        if row["platform"] == platform and row["enabled"]
                    ]
                    due.append(
                        {
                            "campaign_id": campaign["id"],
                            "platform": platform,
                            "scheduled_at": scheduled_at,
                            "keywords": list(dict.fromkeys(grouped["region"] + grouped["target"] + grouped["threat"])),
                            "region_terms": grouped["region"],
                            "target_terms": grouped["target"],
                            "threat_terms": grouped["threat"],
                            "exclude_terms": grouped["exclude"],
                            "sources": sources,
                            "cursor": next((row["cursor"] for row in sources if row["cursor"]), ""),
                            "last_success_at": next(
                                (
                                    row["last_success_at"]
                                    for row in list_social_sources(connection, int(campaign["id"]))
                                    if row["platform"] == platform and row["last_success_at"]
                                ),
                                None,
                            ),
                            "limit": 100,
                        }
                    )
    return due


def claim_social_scan(campaign_id: int, platform: str, scheduled_at: str | None = None) -> dict:
    now = utc_now()
    try:
        with get_db_connection() as connection:
            active = get_active_social_scan_run(connection, campaign_id, platform)
            if active is not None:
                raise SocialMonitoringError("scan already running", 409)
            scan_id = create_social_scan_run(
                connection,
                {
                    "campaign_id": campaign_id, "platform": platform,
                    "scheduled_at": scheduled_at or now, "started_at": now,
                    "created_at": now,
                },
            )
            row = connection.execute("SELECT * FROM social_scan_runs WHERE id = ?", (scan_id,)).fetchone()
            return _public_row(dict(row)) or {}
    except sqlite3.IntegrityError as exc:
        raise SocialMonitoringError("scan already claimed", 409) from exc


def finish_social_scan(
    scan_run_id: int,
    payload: dict | None = None,
    *,
    stats: dict | None = None,
    status: str | None = None,
    error: str | None = None,
    cursor: str | None = None,
) -> None:
    payload = payload or {}
    stats = stats or payload
    values = {
        "finished_at": utc_now(),
        "status": status or payload.get("status") or "succeeded",
        "candidate_count": stats.get("candidate_count") or 0,
        "new_event_count": stats.get("new_count") or stats.get("new_event_count") or 0,
        "duplicate_count": stats.get("duplicate_count") or 0,
        "error_message": error or payload.get("error_message") or "",
        "cursor_after": cursor or payload.get("cursor_after") or "",
    }
    with get_db_connection() as connection:
        finish_social_scan_run(connection, scan_run_id, values)


def upsert_social_post_event(campaign_id: int, scan_run_id: int | None, post: dict) -> dict:
    now = utc_now()
    platform = str(post.get("platform") or "").lower()
    post_id = str(post.get("platformPostId") or post.get("platform_post_id") or "").strip()
    source_url = str(post.get("sourceUrl") or post.get("source_url") or "").strip()
    text = str(post.get("originalText") or post.get("original_text") or "")
    if platform not in PLATFORMS or not source_url:
        raise SocialMonitoringError("platform and sourceUrl are required")
    if not post_id:
        post_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    content_hash = str(post.get("contentHash") or post.get("content_hash") or "") or hashlib.sha256(text.encode("utf-8")).hexdigest()
    with get_db_connection() as connection:
        severity = str(post.get("severity") or "normal")
        searchable = f"{post.get('title') or ''}\n{text}".casefold()
        target_terms = [
            str(row["term"]).casefold()
            for row in list_social_terms(connection, campaign_id)
            if row["term_type"] == "target"
        ]
        citizen_sale = any(value in searchable for value in ("公民信息", "个人信息", "身份证")) and any(
            value in searchable for value in ("售卖", "出售", "贩卖", "for sale")
        )
        targeted_attack = any(value in searchable for value in target_terms) and any(
            value in searchable for value in ("攻击", "入侵", "行动", "attack", "breach")
        )
        if severity == "normal" and (citizen_sale or targeted_attack):
            severity = "major"
        event_id, created = upsert_social_event(
            connection,
            {
                "campaign_id": campaign_id, "scan_run_id": scan_run_id, "platform": platform,
                "platform_post_id": post_id, "source_url": source_url, "author": post.get("author") or "",
                "title": post.get("title") or "", "original_text": text, "content_hash": content_hash,
                "published_at": post.get("publishedAt") or post.get("published_at"),
                "source_deleted_at": now if post.get("isDeleted") or post.get("is_deleted") else None,
                "discovered_at": now,
                "matched_terms_json": json.dumps(post.get("matchedTerms") or post.get("matched_terms") or [], ensure_ascii=False),
                "threat_type": post.get("threatType") or post.get("threat_type") or "",
                "target_unit": post.get("targetUnit") or post.get("target_unit") or "",
                "target_industry": post.get("targetIndustry") or post.get("target_industry") or "",
                "severity": severity, "updated_at": now,
            },
        )
        return {"id": event_id, "status": "created" if created else "duplicate"}


def update_social_source_state(
    source_id: int,
    cursor: str | None = None,
    status: str = "healthy",
    error: str | None = None,
) -> None:
    now = utc_now()
    with get_db_connection() as connection:
        row = connection.execute("SELECT cursor FROM social_sources WHERE id = ?", (int(source_id),)).fetchone()
        values = {
            "cursor": cursor if cursor is not None else str((row or {})["cursor"] if row else ""),
            "health_status": status,
            "last_error": str(error or ""),
            "updated_at": now,
        }
        if status == "healthy":
            values["last_success_at"] = now
        update_social_source(
            connection,
            source_id,
            values,
        )
