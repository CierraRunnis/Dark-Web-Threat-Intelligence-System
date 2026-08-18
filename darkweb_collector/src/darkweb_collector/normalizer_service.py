from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from darkweb_collector.db import (
    connect,
    connect_readonly,
    get_normalized_intelligence_cache_state,
    mark_normalized_intelligence_dirty,
    mark_normalized_intelligence_error,
    mark_normalized_intelligence_refresh_started,
)
from darkweb_collector.normalized_intelligence import (
    NORMALIZATION_VERSION,
    refresh_normalized_intelligence,
)
from darkweb_collector.runtime import default_db_path


logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 5.0
DEFAULT_DEBOUNCE_SECONDS = 60.0
DEFAULT_MAX_DELAY_SECONDS = 300.0


class NormalizerAlreadyRunningError(RuntimeError):
    pass


class _NormalizerFileLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def __enter__(self) -> "_NormalizerFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise NormalizerAlreadyRunningError(
                f"normalizer lock is already held: {self.path}"
            ) from exc
        self._handle = handle
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _resolved_db_path(db_path: str | Path | None) -> Path:
    if db_path is None:
        return default_db_path().expanduser().resolve()
    return Path(db_path).expanduser().resolve()


def normalizer_lock_path(db_path: str | Path | None = None) -> Path:
    path = _resolved_db_path(db_path)
    return Path(f"{path}.normalizer.lock")


def acquire_normalizer_lock(
    db_path: str | Path | None = None,
) -> _NormalizerFileLock:
    return _NormalizerFileLock(normalizer_lock_path(db_path))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _state_payload(state: dict | None) -> dict[str, Any]:
    payload = dict(state or {})
    source_revision = int(payload.get("source_revision") or 0)
    applied_revision = int(payload.get("applied_revision") or 0)
    payload["source_revision"] = source_revision
    payload["applied_revision"] = applied_revision
    payload["event_count"] = int(payload.get("event_count") or 0)
    payload["pending"] = source_revision > applied_revision
    return payload


def _ensure_service_state(path: Path) -> dict:
    with connect(path) as connection:
        state = get_normalized_intelligence_cache_state(connection)
        needs_version_refresh = bool(
            state
            and str(state.get("normalization_version") or "") != NORMALIZATION_VERSION
            and int(state.get("source_revision") or 0)
            <= int(state.get("applied_revision") or 0)
        )
        if state is None or needs_version_refresh:
            mark_normalized_intelligence_dirty(connection)
            connection.commit()
            state = get_normalized_intelligence_cache_state(connection)
        return dict(state or {})


def _refresh_pending_normalization(
    *,
    path: Path,
    force: bool,
    debounce_seconds: float,
    max_delay_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    state = _ensure_service_state(path)
    state_payload = _state_payload(state)
    now = _utc_now()
    pending = bool(state_payload["pending"])

    if not pending and not force:
        return {
            "status": "idle",
            "ran": False,
            "duration_seconds": round(time.perf_counter() - started, 3),
            **state_payload,
        }

    quiet_age = _elapsed_seconds(state.get("dirty_at"), now)
    pending_age = _elapsed_seconds(state.get("dirty_since"), now)
    debounce = max(0.0, float(debounce_seconds))
    max_delay = max(0.0, float(max_delay_seconds))
    due_to_quiet = quiet_age is None or quiet_age >= debounce
    due_to_max_delay = pending_age is None or pending_age >= max_delay
    if not force and not due_to_quiet and not due_to_max_delay:
        retry_in = min(debounce - quiet_age, max_delay - pending_age)
        return {
            "status": "debouncing",
            "ran": False,
            "retry_in_seconds": round(max(0.0, retry_in), 3),
            "quiet_for_seconds": round(quiet_age, 3),
            "pending_for_seconds": round(pending_age, 3),
            "duration_seconds": round(time.perf_counter() - started, 3),
            **state_payload,
        }

    with connect(path) as connection:
        latest_state = get_normalized_intelligence_cache_state(connection) or {}
        target_revision = int(latest_state.get("source_revision") or 0)
        mark_normalized_intelligence_refresh_started(
            connection,
            target_revision=target_revision,
            started_at=now.isoformat(),
        )
        connection.commit()

    try:
        with connect(path) as connection:
            events = refresh_normalized_intelligence(
                connection,
                target_revision=target_revision,
            )
    except Exception as exc:
        logger.exception("normalized intelligence refresh failed")
        try:
            with connect(path) as connection:
                failed_state = mark_normalized_intelligence_error(
                    connection,
                    error_message=str(exc),
                )
                connection.commit()
        except Exception:
            logger.exception("failed to persist normalizer error state")
            failed_state = latest_state
        return {
            "status": "error",
            "ran": True,
            "target_revision": target_revision,
            "error": str(exc),
            "duration_seconds": round(time.perf_counter() - started, 3),
            **_state_payload(dict(failed_state or {})),
        }

    with connect(path) as connection:
        completed_state = get_normalized_intelligence_cache_state(connection) or {}
    return {
        "status": "refreshed",
        "ran": True,
        "target_revision": target_revision,
        "normalized_event_count": len(events),
        "duration_seconds": round(time.perf_counter() - started, 3),
        **_state_payload(dict(completed_state)),
    }


def refresh_pending_normalization(
    force: bool = False,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run at most one due refresh and always return JSON-serializable state."""
    path = _resolved_db_path(db_path)
    try:
        with acquire_normalizer_lock(path):
            return _refresh_pending_normalization(
                path=path,
                force=bool(force),
                debounce_seconds=debounce_seconds,
                max_delay_seconds=max_delay_seconds,
            )
    except NormalizerAlreadyRunningError as exc:
        try:
            with connect_readonly(path) as connection:
                state = get_normalized_intelligence_cache_state(connection)
        except Exception:
            state = None
        return {
            "status": "already_running",
            "ran": False,
            "error": str(exc),
            **_state_payload(state),
        }


def run_normalizer_service(
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    force: bool = False,
    *,
    db_path: str | Path | None = None,
    stop_event=None,
) -> dict[str, Any]:
    """Poll revision state under one process-wide file lock until stopped."""
    path = _resolved_db_path(db_path)
    poll_interval = max(0.1, float(poll_seconds))
    last_result: dict[str, Any] = {"status": "starting", "ran": False}
    first_iteration = True
    with acquire_normalizer_lock(path):
        while stop_event is None or not stop_event.is_set():
            try:
                last_result = _refresh_pending_normalization(
                    path=path,
                    force=bool(force and first_iteration),
                    debounce_seconds=debounce_seconds,
                    max_delay_seconds=max_delay_seconds,
                )
            except Exception as exc:
                logger.exception("normalizer iteration failed")
                last_result = {
                    "status": "error",
                    "ran": False,
                    "error": str(exc),
                }
            first_iteration = False
            logger.info(
                "normalizer state: %s",
                json.dumps(last_result, ensure_ascii=False, sort_keys=True),
            )
            if stop_event is None:
                time.sleep(poll_interval)
            elif stop_event.wait(poll_interval):
                break
    return last_result
