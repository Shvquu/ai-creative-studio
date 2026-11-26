"""Generation & processing endpoints. Long operations return a job (HTTP 202)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.core.errors import NotFoundError, ValidationError
from backend.orchestration.brand import TYPE_PAIRINGS, suggest_typography
from backend.orchestration.prompts import CAMERA_MOVES, STYLE_PRESETS
from backend.orchestration.studio import JOB_TYPES, PROCESS_OPS, Studio
from backend.providers.image_tools import SOCIAL_FORMATS
from backend.quality.analyzer import RESOLUTION_PRESETS, validate_resolution

from ..deps import get_studio

router = APIRouter(tags=["generation"])


class JobRequest(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    project: str | None = None
    label: str | None = None


async def _submit(studio: Studio, job_type: str, params: dict[str, Any], project: str | None = None,
                  label: str | None = None) -> JSONResponse:
    job = await studio.submit(job_type, params, project=project, label=label)
    return JSONResponse(status_code=202, content={"job": job.model_dump(mode="json")})


@router.post("/jobs", status_code=202)
async def create_job(body: JobRequest, studio: Studio = Depends(get_studio)) -> JSONResponse:
    return await _submit(studio, body.type, body.params, body.project, body.label)


@router.get("/jobs/types")
async def job_types() -> dict[str, Any]:
    return {k: {"role": v[0], "resource": v[1]} for k, v in JOB_TYPES.items()}


_IMAGE_OPS = {"generate", "edit", "inpaint", "outpaint", "upscale", "remove_background", "resize", "text_overlay",
              "palette", "contact_sheet"}
_VIDEO_OPS = {"generate", "image_to_video", "upscale"}


@router.post("/images/{op}", status_code=202)
async def image_op(op: str, params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    if op.replace("-", "_") not in _IMAGE_OPS:
        raise NotFoundError(f"Unbekannte Bildoperation '{op}'", details={"available": sorted(_IMAGE_OPS)})
    return await _submit(studio, f"image.{op.replace('-', '_')}", params)


@router.post("/videos/{op}", status_code=202)
async def video_op(op: str, params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    op = op.replace("-", "_")
    if op not in _VIDEO_OPS:
        raise NotFoundError(f"Unbekannte Videooperation '{op}'", details={"available": sorted(_VIDEO_OPS)})
    return await _submit(studio, f"video.{op}", params)


@router.post("/process/{op}", status_code=202)
async def process_op(op: str, params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    op = op.replace("-", "_")
    if op not in PROCESS_OPS:
        raise NotFoundError(f"Unbekannte Verarbeitung '{op}'", details={"available": sorted(PROCESS_OPS)})
    return await _submit(studio, f"process.{op}", params)


@router.get("/process/info")
async def media_info(path: str = Query(..., description="Asset-ID oder Pfad im assets-Verzeichnis"),
                     studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    info = await studio.ffmpeg.get_info(studio.resolve_input(path))
    return info.model_dump(exclude={"raw"})


@router.post("/motion/render", status_code=202)
async def motion_render(params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    return await _submit(studio, "motion.render", params)


@router.get("/motion/compositions")
async def motion_compositions(studio: Studio = Depends(get_studio)) -> list[dict[str, Any]]:
    return await studio.registry.get("motion").get_compositions()


@router.post("/render3d/render", status_code=202)
async def render3d(params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    return await _submit(studio, "render3d.render", params)


@router.get("/render3d/templates")
async def render3d_templates(studio: Studio = Depends(get_studio)) -> list[dict[str, Any]]:
    return await studio.registry.get("render3d").get_templates()


class ResolutionCheck(BaseModel):
    asset: str | None = None
    width: int | None = None
    height: int | None = None
    preset: str | None = None
    min_width: int | None = None
    min_height: int | None = None
    aspect: str | None = None
    exact: bool = False


@router.post("/quality/validate-resolution")
async def validate_res(body: ResolutionCheck, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    width, height = body.width, body.height
    if body.asset:
        info = await studio.ffmpeg.get_info(studio.resolve_input(body.asset))
        width, height = info.width, info.height
    if not width or not height:
        raise ValidationError("asset oder width+height angeben")
    return validate_resolution(width, height, preset=body.preset, min_width=body.min_width, min_height=body.min_height,
                               aspect=body.aspect, exact=body.exact)


@router.post("/quality/{op}", status_code=202)
async def quality_op(op: str, params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    if op not in ("analyze", "report"):
        raise NotFoundError("Unbekannte Qualitätsoperation")
    return await _submit(studio, f"quality.{op}", params)


@router.post("/brand/guidelines", status_code=202)
async def brand_guidelines(params: dict[str, Any], studio: Studio = Depends(get_studio)) -> JSONResponse:
    return await _submit(studio, "brand.guidelines", params)


@router.get("/brand/typography")
async def typography(keywords: str = "", limit: int = 3) -> dict[str, Any]:
    kws = [k for k in keywords.replace(",", " ").split() if k]
    return {"suggestions": suggest_typography(kws, limit) if kws else TYPE_PAIRINGS[:limit], "all": TYPE_PAIRINGS}


class EstimateRequest(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/estimate")
async def estimate(body: EstimateRequest, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    if body.type not in JOB_TYPES:
        raise ValidationError(f"Unbekannter Job-Typ '{body.type}'")
    return studio.estimate(body.type, body.params).model_dump()


@router.get("/presets")
async def presets() -> dict[str, Any]:
    return {
        "styles": {k: v["label"] for k, v in STYLE_PRESETS.items()},
        "camera_moves": CAMERA_MOVES,
        "social_formats": {k: list(v) for k, v in SOCIAL_FORMATS.items()},
        "resolution_presets": RESOLUTION_PRESETS,
        "aspect_ratios": ["1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9"],
        "transitions": ["none", "fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright", "fadeblack",
                        "fadewhite", "circleopen", "circleclose", "smoothleft", "smoothright", "zoomin", "pixelize", "radial"],
    }
