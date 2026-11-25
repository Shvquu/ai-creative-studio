"""Workflow endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.orchestration.studio import Studio

from ..deps import get_studio

router = APIRouter(tags=["workflows"])


@router.get("/workflows")
async def list_workflows(studio: Studio = Depends(get_studio)) -> list[dict[str, Any]]:
    return studio.workflows.list()


@router.get("/workflows/{workflow_id:path}/definition")
async def get_workflow(workflow_id: str, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    spec = studio.workflows.get(workflow_id)
    return {**spec.public(), "definition": spec.model_dump(by_alias=True)}


class RunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    project: str | None = None
    confirm_token: str | None = None


@router.post("/workflows/{workflow_id:path}/run", status_code=202)
async def run_workflow(workflow_id: str, body: RunRequest, studio: Studio = Depends(get_studio)) -> JSONResponse:
    spec = studio.workflows.get(workflow_id)
    studio.workflows.coerce_inputs(spec, body.inputs)  # validate early → 400 instead of a failed job
    params: dict[str, Any] = {"workflow_id": spec.id, "inputs": body.inputs, "project": body.project}
    if body.confirm_token:
        params["confirm_token"] = body.confirm_token
    job = await studio.submit("workflow.run", params, project=body.project, label=f"Workflow: {spec.name}")
    return JSONResponse(status_code=202, content={"job": job.model_dump(mode="json")})


@router.post("/workflows/reload")
async def reload_workflows(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    studio.workflows.reload()
    return {"count": len(studio.workflows.specs)}
