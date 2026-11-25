"""System status, hardware, providers, models, settings."""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.config import deep_merge, load_yaml, save_local_overrides
from backend.core.errors import NotFoundError, ValidationError
from backend.core.hardware import live_usage, select_profile
from backend.orchestration.studio import Studio

from ..deps import get_studio

router = APIRouter(tags=["system"])
_cache: dict[str, tuple[float, Any]] = {}


async def _cached(key: str, ttl: float, fn: Any) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = await fn()
    _cache[key] = (time.monotonic(), value)
    return value


@router.get("/system/status")
async def system_status(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    report, decision = await asyncio.to_thread(studio.hardware)

    async def providers_health() -> dict[str, Any]:
        out = {}
        for name in studio.registry.infos:
            health = await studio.registry.health(name)
            out[name] = {role: h.model_dump() for role, h in health.items()}
        return out

    health = await _cached("providers_health", 5.0, providers_health)
    comfy = (health.get("comfyui") or {}).get("image", {})
    disk = shutil.disk_usage(studio.settings.assets_dir)
    usage = await asyncio.to_thread(live_usage)
    comfy_devices = (comfy.get("extra") or {}).get("devices") or []
    if comfy_devices and not usage["gpus"]:
        usage["gpus"] = [{"name": d.get("name"), "vram_total_gb": round((d.get("vram_total") or 0) / 1024**3, 2),
                          "vram_free_gb": round((d.get("vram_free") or 0) / 1024**3, 2), "source": "comfyui"}
                         for d in comfy_devices if d.get("type") != "cpu"]
    return {
        "profile": decision.model_dump(),
        "hardware": {"os": f"{report.os} {report.os_version}", "cpu": report.cpu_model, "cores": report.cpu_cores_logical,
                     "ram_total_gb": report.ram_total_gb, "gpus": [g.model_dump() for g in report.gpus],
                     "cuda": report.cuda_version},
        "usage": usage,
        "disk": {"free_gb": round(disk.free / 1024**3, 1), "total_gb": round(disk.total / 1024**3, 1)},
        "comfyui": {"available": comfy.get("available", False), "detail": comfy.get("detail"), "url": studio.settings.comfyui.url},
        "providers": health,
        "jobs": studio.queue.counts(),
        "active_jobs": [j.model_dump(mode="json") for j in studio.queue.list(status="queued,running,retrying", limit=20)],
        "assets": studio.assets.stats(),
        "costs": studio.costs.summary(),
    }


@router.get("/system/hardware")
async def hardware(refresh: bool = False, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    report, decision = await asyncio.to_thread(studio.hardware, refresh)
    profile = studio.catalog.profiles.get(decision.profile)
    return {"report": report.model_dump(), "decision": decision.model_dump(),
            "profile": profile.model_dump() if profile else None,
            "profiles": {k: v.model_dump() for k, v in studio.catalog.profiles.items()},
            "recommended_models": studio.selector.recommended(decision, report.ram_total_gb)}


@router.get("/system/capabilities")
async def capabilities(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return await studio.capabilities()


@router.get("/providers")
async def providers(studio: Studio = Depends(get_studio)) -> list[dict[str, Any]]:
    out = []
    for name, info in studio.registry.infos.items():
        health = await studio.registry.health(name)
        caps: dict[str, list[str]] = {}
        for role in info.roles:
            if info.enabled:
                try:
                    caps[role] = sorted(c.value for c in studio.registry.get(role, name).get_capabilities())
                except Exception:
                    caps[role] = []
        out.append({**info.model_dump(), "health": {r: h.model_dump() for r, h in health.items()}, "capabilities": caps,
                    "api_key_present": studio.registry.api_key_present(info),
                    "default_for": [r for r, n in studio.registry.defaults.items() if n == name]})
    return out


class ProviderPatch(BaseModel):
    enabled: bool


@router.patch("/providers/{name}")
async def patch_provider(name: str, body: ProviderPatch, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    info = studio.registry.set_enabled(name, body.enabled)
    path = studio.settings.configs_dir / "providers.local.yaml"
    data = deep_merge(load_yaml(path), {"providers": {name: {"enabled": body.enabled}}})
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _cache.pop("providers_health", None)
    return info.model_dump()


@router.get("/models")
async def models(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return await studio.model_overview()


@router.get("/comfyui/templates")
async def comfy_templates(studio: Studio = Depends(get_studio)) -> list[dict[str, Any]]:
    try:
        prov = studio.registry.get("image", "comfyui")
    except Exception as exc:
        raise NotFoundError(str(exc)) from exc
    return [{**t.meta.model_dump(exclude={"parameters"}), "parameters": {k: v.model_dump() for k, v in t.meta.parameters.items()}}
            for t in prov.templates.list()]


EDITABLE = {
    "comfyui": {"url", "generation_timeout_s", "use_websocket"},
    "hardware": {"profile"},
    "jobs": {"gpu_concurrency", "cpu_concurrency", "workflow_concurrency", "max_attempts", "retry_backoff_s"},
    "quality": {"auto_check", "min_sharpness", "min_score"},
    "ffmpeg": {"ffmpeg_path", "ffprobe_path", "default_crf", "preset"},
    "blender": {"blender_path"},
    "remotion": {"npx_path"},
    "costs": {"monthly_budget", "max_cost_per_job"},
    "paths": {"extra_allowed_dirs", "comfyui_dir"},
}
RESTART_REQUIRED = {"jobs", "paths", "comfyui"}


@router.get("/settings")
async def get_settings_route(studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    return {"settings": studio.settings.public_dict(), "editable": {k: sorted(v) for k, v in EDITABLE.items()},
            "local_overrides": load_yaml(studio.settings.configs_dir / "studio.local.yaml")}


class SettingsUpdate(BaseModel):
    updates: dict[str, dict[str, Any]]


@router.put("/settings")
async def put_settings(body: SettingsUpdate, studio: Studio = Depends(get_studio)) -> dict[str, Any]:
    for section, values in body.updates.items():
        allowed = EDITABLE.get(section)
        if allowed is None or set(values) - allowed:
            raise ValidationError(f"Nicht editierbar: {section}.{sorted(set(values) - (allowed or set()))}")
    save_local_overrides(studio.settings.project_root, body.updates)
    # apply in-memory where safe
    for section, values in body.updates.items():
        obj = getattr(studio.settings, section)
        for k, v in values.items():
            setattr(obj, k, v)
    if "hardware" in body.updates:
        report, _ = studio.hardware()
        studio.set_hardware(report, select_profile(report, studio.settings.hardware.profile))
    if "costs" in body.updates:
        studio.costs.monthly_budget = studio.settings.costs.monthly_budget
        studio.costs.max_cost_per_job = studio.settings.costs.max_cost_per_job
    return {"saved": True, "restart_required": sorted(set(body.updates) & RESTART_REQUIRED)}
