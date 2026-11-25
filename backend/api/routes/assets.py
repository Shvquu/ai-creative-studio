"""Asset library endpoints (search, metadata, files, thumbnails, uploads, organize)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.core.errors import NotFoundError, ValidationError
from backend.core.media import AUDIO_EXT, IMAGE_EXT, MODEL3D_EXT, SUBTITLE_EXT, VIDEO_EXT
from backend.core.paths import safe_filename
from backend.orchestration.studio import Studio

from ..deps import get_studio

router = APIRouter(tags=["assets"])
UPLOAD_EXT = IMAGE_EXT | VIDEO_EXT | AUDIO_EXT | MODEL3D_EXT | SUBTITLE_EXT | {".svg"}


@router.get("/assets")
async def list_assets(q: str | None = None, kind: str | None = None, tags: str | None = None, favorite: bool | None = None,
                      project: str | None = None, job_id: str | None = None, since: str | None = None,
                      until: str | None = None, sort: Literal["newest", "oldest", "name", "size", "rating"] = "newest",
                      limit: int = 60, offset: int = 0, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    tag_list = [t for t in (tags or "").split(",") if t.strip()]
    items, total = studio.assets.search(q, kind=kind, tags=tag_list, favorite=favorite, project=project, job_id=job_id,
                                        since=since, until=until, sort=sort, limit=limit, offset=offset)
    return {"assets": [a.model_dump() for a in items], "total": total, "limit": limit, "offset": offset}


@router.get("/assets/meta/stats")
async def asset_stats(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return {**studio.assets.stats(), "tags": studio.assets.all_tags()[:100], "projects": studio.assets.projects()}


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    asset = studio.assets.get(asset_id)
    sidecar = studio.assets.read_sidecar(asset)
    return {**asset.model_dump(), "sidecar": sidecar, "exists": studio.assets.abs_path(asset).is_file()}


class AssetPatch(BaseModel):
    tags: list[str] | None = None
    add_tags: list[str] | None = None
    remove_tags: list[str] | None = None
    favorite: bool | None = None
    rating: int | None = None
    notes: str | None = None
    project: str | None = None


@router.patch("/assets/{asset_id}")
async def patch_asset(asset_id: str, body: AssetPatch, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return studio.assets.update(asset_id, **body.model_dump()).model_dump()


@router.get("/assets/{asset_id}/file")
async def asset_file(asset_id: str, download: bool = False, studio: Studio = Depends(get_studio)) -> FileResponse:
    asset = studio.assets.get(asset_id)
    path = studio.assets.abs_path(asset)
    if not path.is_file():
        raise NotFoundError("Datei fehlt")
    return FileResponse(path, media_type=asset.mime, filename=path.name if download else None)


@router.get("/assets/{asset_id}/thumbnail")
async def asset_thumbnail(asset_id: str, size: int = 384, studio: Studio = Depends(get_studio)) -> FileResponse:
    path = await studio.assets.thumbnail(asset_id, size)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "max-age=3600"})


@router.post("/assets/upload")
async def upload(file: UploadFile = File(...), tags: str = Form(""), project: str | None = Form(None),
                 studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    name = safe_filename(file.filename or "upload")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in UPLOAD_EXT:
        raise ValidationError(f"Dateityp {ext or '(ohne Endung)'} nicht erlaubt", details={"allowed": sorted(UPLOAD_EXT)})
    limit = studio.settings.server.max_upload_mb * 1024 * 1024
    target = studio.paths.output_path(studio.settings.assets_dir / "references", name)
    size = 0
    with target.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                fh.close()
                target.unlink(missing_ok=True)
                raise ValidationError(f"Datei größer als {studio.settings.server.max_upload_mb} MB")
            fh.write(chunk)
    asset = await studio.assets.register(target, provider="upload", source="reference", project=project or None,
                                         tags=["reference", *[t for t in tags.split(",") if t.strip()]])
    return asset.model_dump()


@router.post("/assets/rescan")
async def rescan(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return await studio.assets.rescan()


class OrganizeRequest(BaseModel):
    rule: Literal["by_kind", "by_project", "by_date"] = "by_kind"
    asset_ids: list[str] | None = None
    dry_run: bool = True


@router.post("/assets/organize")
async def organize(body: OrganizeRequest, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return studio.assets.organize(body.rule, asset_ids=body.asset_ids, dry_run=body.dry_run)
