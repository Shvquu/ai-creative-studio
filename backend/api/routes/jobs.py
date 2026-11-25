"""Job queue endpoints and Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.orchestration.studio import Studio

from ..deps import get_studio

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
async def list_jobs(status: str | None = None, type: str | None = None, parent_id: str | None = None,
                    limit: int = 50, offset: int = 0, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    jobs = studio.queue.list(status=status, job_type=type, parent_id=parent_id, limit=limit, offset=offset)
    return {"jobs": [j.model_dump(mode="json") for j in jobs], "counts": studio.queue.counts()}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return studio.queue.get(job_id).model_dump(mode="json")


@router.get("/jobs/{job_id}/wait")
async def wait_job(job_id: str, timeout: float = 60, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    job = await studio.queue.wait(job_id, timeout=max(0.0, min(timeout, 600)))
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return (await studio.queue.cancel(job_id)).model_dump(mode="json")


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return {"job": (await studio.queue.retry(job_id)).model_dump(mode="json")}


@router.get("/events")
async def events(request: Request, studio: Studio = Depends(get_studio)) -> StreamingResponse:
    """Server-Sent Events: job.created / job.updated / job.progress."""
    queue = studio.queue.subscribe()

    async def stream():  # noqa: ANN202
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event['event']}\ndata: {json.dumps(event['job'], default=str)}\n\n"
        finally:
            studio.queue.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
