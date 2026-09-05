from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from .config import Settings
from .repository import Repository
from .schemas import ProfileInput, ProfileUpdate, RunRequest
from .service import (
    AnalysisService,
    ProfileDisabledError,
    ProfileOverlapError,
    QueueCapacityError,
)


router = APIRouter(prefix="/api/ai-aggregation", tags=["AI Aggregation"])
_service_lock = Lock()
_service: AnalysisService | None = None


def _require_ai_aggregation_module(request: Request) -> dict[str, object]:
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    if user.get("role") == "admin" or "ai_aggregation" in (user.get("modules") or []):
        return user
    raise HTTPException(status_code=403, detail="当前账号没有 AI 聚合模块的访问权限")


def get_service() -> AnalysisService:
    global _service
    with _service_lock:
        if _service is None:
            settings = Settings.from_env()
            _service = AnalysisService(settings, Repository(settings.database_path))
        return _service


async def start_service() -> None:
    service = get_service()
    if not service.worker_tasks:
        await service.start()


async def stop_service() -> None:
    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        await service.stop()


def reset_service_for_tests() -> None:
    """Clear the lazy singleton after a test has stopped its lifespan."""
    global _service
    with _service_lock:
        _service = None


@router.on_event("startup")
async def _startup() -> None:
    await start_service()


@router.on_event("shutdown")
async def _shutdown() -> None:
    await stop_service()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    return await get_service().health()


@router.get("/profiles")
def list_profiles(request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    items = get_service().repository.list_profiles()
    return {"items": items, "total": len(items)}


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(payload: ProfileInput, request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    service = get_service()
    profile = service.repository.create_profile(payload)
    try:
        scheduler_id = await service.sync_profile_schedule(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"配置已保存，但同步 Flocks 定时任务失败：{exc}",
        ) from exc
    if scheduler_id:
        profile["flocks_scheduler_id"] = scheduler_id
    return profile


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    profile = get_service().repository.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="AI 聚合配置不存在")
    return profile


@router.put("/profiles/{profile_id}")
async def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    request: Request,
) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    service = get_service()
    profile = service.repository.update_profile(profile_id, payload)
    if not profile:
        raise HTTPException(status_code=404, detail="AI 聚合配置不存在")
    try:
        scheduler_id = await service.sync_profile_schedule(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"配置已保存，但同步 Flocks 定时任务失败：{exc}",
        ) from exc
    if scheduler_id:
        profile["flocks_scheduler_id"] = scheduler_id
    return profile


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str, request: Request) -> Response:
    _require_ai_aggregation_module(request)
    service = get_service()
    if not service.repository.get_profile(profile_id):
        raise HTTPException(status_code=404, detail="AI 聚合配置不存在")
    try:
        await service.disable_profile_schedule(profile_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"禁用 Flocks 定时任务失败：{exc}") from exc
    service.repository.delete_profile(profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/profiles/{profile_id}/enable")
async def enable_profile(profile_id: str, request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    service = get_service()
    profile = service.repository.set_profile_enabled(profile_id, True)
    if not profile:
        raise HTTPException(status_code=404, detail="AI 聚合配置不存在")
    scheduler_id = await service.sync_profile_schedule(profile)
    if scheduler_id:
        profile["flocks_scheduler_id"] = scheduler_id
    return profile


@router.post("/profiles/{profile_id}/disable")
async def disable_profile(profile_id: str, request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    service = get_service()
    profile = service.repository.set_profile_enabled(profile_id, False)
    if not profile:
        raise HTTPException(status_code=404, detail="AI 聚合配置不存在")
    await service.sync_profile_schedule(profile)
    return profile


@router.post("/profiles/{profile_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_profile(
    profile_id: str,
    request: Request,
    payload: RunRequest | None = None,
) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    try:
        run = await get_service().enqueue_profile(
            profile_id,
            keyword_override=payload.keyword if payload else None,
            keywords_override=payload.keywords if payload else None,
            search_window_days_override=(
                payload.search_window_days if payload else None
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI 聚合配置不存在") from exc
    except (ProfileDisabledError, ProfileOverlapError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QueueCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"run_id": run["id"], "status": run["analysis_status"], "run": run}


@router.get("/runs")
def list_runs(
    request: Request,
    analysis_status: str | None = Query(default=None, alias="status"),
    profile_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    if analysis_status and analysis_status not in {"queued", "running", "succeeded", "failed"}:
        raise HTTPException(status_code=422, detail="invalid analysis status")
    items, total = get_service().repository.list_runs(
        status=analysis_status,
        profile_id=profile_id,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    run = get_service().repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return run


@router.post("/runs/{run_id}/retry-deliveries")
async def retry_deliveries(run_id: str, request: Request) -> dict[str, Any]:
    _require_ai_aggregation_module(request)
    service = get_service()
    try:
        retried = await service.retry_deliveries(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析任务不存在") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = service.repository.get_run(run_id)
    return {
        "run_id": run_id,
        "retried": retried,
        "delivery_status": run["delivery_status"] if run else "unknown",
    }
