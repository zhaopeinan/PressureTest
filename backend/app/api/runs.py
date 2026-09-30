from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings
from app.models.schemas import (
    DiscoverPathsRequest,
    DiscoverPathsResponse,
    GuardrailsInfo,
    RunCreate,
    RunDetail,
    RunStatus,
    RunSummary,
    ScenarioInfo,
    SystemMetrics,
)
from app.scenarios.registry import list_scenarios
from app.services.locust_runner import runner
from app.services.path_discovery import discover_paths
from app.services.system_monitor import collect_system_metrics

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/guardrails", response_model=GuardrailsInfo)
async def get_guardrails() -> GuardrailsInfo:
    return GuardrailsInfo(
        allowed_hosts=sorted(settings.allowed_host_set()),
        max_users=settings.max_users,
        max_spawn_rate=settings.max_spawn_rate,
        max_duration_seconds=settings.max_duration_seconds,
        max_workers=settings.max_workers,
        max_target_rps=settings.max_target_rps,
    )


@router.get("/system/metrics", response_model=SystemMetrics)
async def get_system_metrics() -> SystemMetrics:
    active = runner.active_run()
    pids = active.locust_pids() if active else []
    # psutil sampling may briefly block; keep API responsive via thread.
    data = await asyncio.to_thread(collect_system_metrics, pids)
    return SystemMetrics.model_validate(data)


@router.get("/system/events")
async def system_events() -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        while True:
            active = runner.active_run()
            pids = active.locust_pids() if active else []
            data = await asyncio.to_thread(collect_system_metrics, pids)
            payload = SystemMetrics.model_validate(data).model_dump(mode="json")
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/scenarios", response_model=list[ScenarioInfo])
async def get_scenarios() -> list[ScenarioInfo]:
    return list_scenarios()


@router.post("/discover-paths", response_model=DiscoverPathsResponse)
async def discover_site_paths(payload: DiscoverPathsRequest) -> DiscoverPathsResponse:
    try:
        result = await discover_paths(
            payload.host,
            start_path=payload.start_path,
            max_pages=payload.max_pages,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DiscoverPathsResponse.model_validate(result)


@router.get("/runs", response_model=list[RunSummary])
async def get_runs() -> list[RunSummary]:
    return runner.list_runs()


@router.post("/runs", response_model=RunDetail)
async def create_run(payload: RunCreate) -> RunDetail:
    try:
        state = await runner.create_run(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return state.to_detail()


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str) -> RunDetail:
    try:
        return runner.get_run(run_id).to_detail()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from exc


@router.post("/runs/{run_id}/stop", response_model=RunDetail)
async def stop_run(run_id: str) -> RunDetail:
    try:
        state = await runner.stop_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from exc
    return state.to_detail()


@router.get("/runs/{run_id}/report.docx")
async def download_word_report(run_id: str) -> FileResponse:
    try:
        state = runner.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from exc

    if state.status not in {RunStatus.finished, RunStatus.stopped, RunStatus.failed}:
        raise HTTPException(
            status_code=409,
            detail="测试仍在进行中，结束后可下载 Word 报告",
        )

    try:
        path = await asyncio.to_thread(runner.ensure_word_report, state, force=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成 Word 报告失败: {exc}") from exc

    filename = f"pressure-test-{run_id}.docx"
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    try:
        runner.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from exc

    async def event_stream() -> AsyncIterator[str]:
        last_len = -1
        last_status = None
        while True:
            try:
                state = runner.get_run(run_id)
            except KeyError:
                break

            history_len = len(state.history)
            if history_len != last_len or state.status != last_status:
                payload = {
                    "run": state.to_detail().model_dump(mode="json"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_len = history_len
                last_status = state.status

            if state.status.value in {"finished", "failed", "stopped"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
