"""Studio facade – the single entry point used by the API, the MCP server (via API),
the workflow engine, the CLI and the tests.

Every operation (``op_*``) validates input, resolves files (asset ids or paths inside
allowed roots), picks provider + model for the detected hardware, checks costs,
runs the provider, registers outputs as assets (with sidecar metadata) and runs
automatic quality control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from backend.assets import Asset, AssetStore
from backend.core.catalog import CatalogModel, load_catalog
from backend.core.config import Settings, get_settings
from backend.core.costs import CostEstimate, CostGuard, ResourceEstimate
from backend.core.db import Database
from backend.core.errors import (
    HardwareInsufficientError,
    ModelNotInstalledError,
    StudioError,
    ValidationError,
)
from backend.core.hardware import HardwareReport, ProfileDecision, collect_report, select_profile
from backend.core.logging import setup_logging
from backend.core.paths import PathGuard, slugify
from backend.jobs import Job, JobContext, JobQueue
from backend.providers import ffmpeg as ffm
from backend.providers.base import (
    GenerationResult,
    ImageEditRequest,
    ImageGenerateRequest,
    InpaintRequest,
    OutpaintRequest,
    RemoveBackgroundRequest,
    UpscaleRequest,
    VideoGenerateRequest,
    VideoUpscaleRequest,
)
from backend.providers.blender import Render3DRequest
from backend.providers.image_tools import (
    ContactSheetRequest,
    PaletteRequest,
    ResizeImageRequest,
    TextOverlayRequest,
)
from backend.providers.registry import ProviderRegistry
from backend.providers.remotion import MotionRenderRequest
from backend.quality import QualityAnalyzer, validate_resolution

from .brand import BrandGuideRequest, render_brand_guide, suggest_typography
from .prompts import build_prompt, camera_phrase
from .selector import ModelSelector

log = logging.getLogger("studio")
_ASSET_ID = re.compile(r"^[0-9a-f]{32}$")

Op = Callable[[dict[str, Any], JobContext], Awaitable[dict[str, Any]]]

# job type → (provider role, resource pool)
JOB_TYPES: dict[str, tuple[str | None, str]] = {
    "image.generate": ("image", "gpu"),
    "image.edit": ("image", "gpu"),
    "image.inpaint": ("image", "gpu"),
    "image.outpaint": ("image", "gpu"),
    "image.upscale": ("image", "gpu"),
    "image.remove_background": ("image_tools", "cpu"),
    "image.resize": ("image_tools", "cpu"),
    "image.text_overlay": ("image_tools", "cpu"),
    "image.palette": ("image_tools", "cpu"),
    "image.contact_sheet": ("image_tools", "cpu"),
    "video.generate": ("video", "gpu"),
    "video.image_to_video": ("video", "gpu"),
    "video.upscale": ("video", "gpu"),
    "motion.render": ("motion", "cpu"),
    "render3d.render": ("render3d", "gpu"),
    "quality.analyze": (None, "cpu"),
    "quality.report": (None, "cpu"),
    "brand.guidelines": (None, "cpu"),
    "workflow.run": (None, "workflow"),
    "system.smoke_test": ("image", "gpu"),
}
PROCESS_OPS: dict[str, tuple[type, str]] = {
    "convert": (ffm.ConvertRequest, "convert"),
    "trim": (ffm.TrimRequest, "trim"),
    "merge": (ffm.MergeRequest, "merge"),
    "render": (ffm.RenderRequest, "render"),
    "extract_frames": (ffm.ExtractFramesRequest, "extract_frames"),
    "add_audio": (ffm.AddAudioRequest, "add_audio"),
    "add_subtitles": (ffm.AddSubtitlesRequest, "add_subtitles"),
    "resize": (ffm.ResizeRequest, "resize"),
    "compress": (ffm.CompressRequest, "compress"),
    "interpolate": (ffm.InterpolateRequest, "interpolate"),
    "title_card": (ffm.TitleCardRequest, "title_card"),
}
for _op in PROCESS_OPS:
    JOB_TYPES[f"process.{_op}"] = ("processing", "cpu")

# Fields in request params that reference files (resolved through PathGuard / asset ids).
_FILE_FIELDS = {"source", "video", "audio", "image", "mask", "background_image", "model_path", "svg_path", "font_path",
                "logo", "control_image"}
_FILE_LIST_FIELDS = {"sources", "logos", "imagery", "assets"}


class Studio:
    def __init__(self, settings: Settings | None = None, *, registry: ProviderRegistry | None = None,
                 configure_logging: bool = True) -> None:
        self.settings = settings or get_settings()
        s = self.settings
        s.ensure_dirs()
        if configure_logging:
            setup_logging(s.logs_dir, s.logging.level, max_bytes=s.logging.max_bytes, backup_count=s.logging.backup_count)
        self.db = Database(s.db_path)
        self.catalog = load_catalog(str(s.configs_dir))
        self.registry = registry or ProviderRegistry(s)
        self.assets = AssetStore(self.db, s.assets_dir, s.cache_dir, s.ffmpeg.ffprobe_path, s.ffmpeg.ffmpeg_path)
        self.costs = CostGuard(self.db, currency=s.costs.currency, monthly_budget=s.costs.monthly_budget,
                               max_cost_per_job=s.costs.max_cost_per_job, ttl_s=s.costs.confirmation_ttl_s,
                               secret_path=s.data_dir / ".cost_secret")
        self.queue = JobQueue(
            self.db, s.assets_dir / "generated",
            concurrency={"gpu": s.jobs.gpu_concurrency, "cpu": s.jobs.cpu_concurrency, "workflow": s.jobs.workflow_concurrency},
            max_attempts=s.jobs.max_attempts, retry_backoff_s=s.jobs.retry_backoff_s, default_timeout_s=s.jobs.default_timeout_s,
        )
        roots = [s.assets_dir, s.tmp_dir, *(s.resolve(d) for d in s.paths.extra_allowed_dirs)]
        self.paths = PathGuard(roots, default_root=s.assets_dir)
        self.selector = ModelSelector(self.catalog)
        self._hardware: tuple[HardwareReport, ProfileDecision] | None = None
        self._register_jobs()
        from backend.workflows.engine import WorkflowEngine

        self.workflows = WorkflowEngine(self, s.resolve(s.paths.workflows_dir))

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.queue.start()

    async def stop(self) -> None:
        await self.queue.stop()
        await self.registry.close()

    # -------------------------------------------------------------- hardware
    def hardware(self, refresh: bool = False) -> tuple[HardwareReport, ProfileDecision]:
        if self._hardware is None or refresh:
            report = collect_report(self.settings.project_root,
                                    {"ffmpeg": self.settings.ffmpeg.ffmpeg_path, "ffprobe": self.settings.ffmpeg.ffprobe_path,
                                     "blender": self.settings.blender.blender_path})
            self._hardware = (report, select_profile(report, self.settings.hardware.profile))
        return self._hardware

    def set_hardware(self, report: HardwareReport, decision: ProfileDecision) -> None:
        """Inject a hardware snapshot (tests, simulations)."""
        self._hardware = (report, decision)

    # -------------------------------------------------------------- providers
    def provider(self, role: str, name: str | None = None) -> Any:
        return self.registry.get(role, name)

    @property
    def ffmpeg(self) -> ffm.FFmpegProvider:
        return self.registry.get("processing", self.registry.defaults.get("processing"))

    @property
    def image_tools(self) -> Any:
        return self.registry.get("image", self.registry.defaults.get("image_tools", "local-image-tools"))

    @property
    def quality(self) -> QualityAnalyzer:
        q = self.settings.quality
        return QualityAnalyzer(self.ffmpeg, q.min_sharpness, q.min_score)

    async def capabilities(self) -> dict[str, Any]:
        report, decision = self.hardware()
        caps: dict[str, Any] = {"profile": decision.profile, "gpu": not decision.cpu_only, "accelerator": decision.accelerator}
        comfy_ok = False
        try:
            comfy_ok = (await self.registry.get("image", self.registry.defaults["image"]).health()).available
        except Exception:
            comfy_ok = False
        caps["ai_image"] = comfy_ok
        caps["ai_video"] = comfy_ok and not decision.cpu_only
        for role, key in (("processing", "ffmpeg"), ("render3d", "blender"), ("motion", "remotion")):
            try:
                caps[key] = (await self.registry.get(role).health()).available
            except Exception:
                caps[key] = False
        caps["rembg"] = self.image_tools.rembg_available()
        return caps

    # ----------------------------------------------------------------- inputs
    def resolve_input(self, ref: str | Path) -> Path:
        ref_s = str(ref).strip()
        if _ASSET_ID.match(ref_s):
            asset = self.assets.get(ref_s)
            path = self.assets.abs_path(asset)
            if not path.is_file():
                raise ValidationError(f"Asset-Datei fehlt auf der Festplatte: {asset.path}")
            return path
        return self.paths.resolve(ref_s)

    def _resolve_params(self, params: dict[str, Any]) -> dict[str, Any]:
        out = dict(params)
        for key in _FILE_FIELDS:
            if isinstance(out.get(key), str) and out[key]:
                out[key] = str(self.resolve_input(out[key]))
        for key in _FILE_LIST_FIELDS:
            if isinstance(out.get(key), list):
                out[key] = [str(self.resolve_input(v)) for v in out[key]]
        if isinstance(out.get("subtitles"), str):
            out["subtitles"] = str(self.resolve_input(out["subtitles"]))
        if isinstance(out.get("clips"), list):
            out["clips"] = [{**c, "source": str(self.resolve_input(c["source"]))} if isinstance(c, dict) else c
                            for c in out["clips"]]
        if isinstance(out.get("audio"), dict) and out["audio"].get("source"):
            out["audio"] = {**out["audio"], "source": str(self.resolve_input(out["audio"]["source"]))}
        if isinstance(out.get("params"), dict):
            out["params"] = self._resolve_params(out["params"])
        if isinstance(out.get("props"), dict):
            out["props"] = self._resolve_params(out["props"])
        return out

    # ---------------------------------------------------------------- costs
    def _provider_name(self, role: str | None, params: dict[str, Any]) -> str | None:
        if role is None:
            return None
        if params.get("provider"):
            return str(params["provider"])
        if role == "image_tools":
            return self.registry.defaults.get("image_tools", "local-image-tools")
        return self.registry.defaults.get(role)

    def _catalog_model_for(self, job_type: str, params: dict[str, Any]) -> CatalogModel | None:
        model = params.get("model")
        if model:
            return self.catalog.find(str(model))
        task = {"image.generate": "text_to_image", "image.edit": "image_to_image", "image.inpaint": "inpaint",
                "image.outpaint": "outpaint", "image.upscale": "upscale", "video.generate": "text_to_video",
                "video.image_to_video": "image_to_video"}.get(job_type)
        if not task:
            return None
        if job_type == "video.generate" and params.get("image"):
            task = "image_to_video"
        report, decision = self.hardware()
        cands = [c for c in self.selector.candidates(task, decision, report.ram_total_gb, None) if c.fits]
        cands.sort(key=lambda c: c.preferred_rank)
        return cands[0].model if cands else None

    def estimate(self, job_type: str, params: dict[str, Any]) -> CostEstimate:
        role, _ = JOB_TYPES.get(job_type, (None, "cpu"))
        name = self._provider_name(role, params)
        report, decision = self.hardware()
        cm = self._catalog_model_for(job_type, params) if name in (None, "comfyui") else None
        count = int(params.get("batch_size", 1) or 1)
        resources = ResourceEstimate(note="grobe Schätzung")
        if cm is not None:
            key = "cpu" if decision.cpu_only else decision.profile
            secs = cm.est_seconds.get(key)
            resources = ResourceEstimate(
                vram_gb=None if decision.cpu_only else cm.rec_vram_gb, ram_gb=cm.min_ram_gb,
                est_seconds=secs * count if secs else None,
                disk_mb=(12.0 if cm.type == "video" else 1.5) * count,
                note=f"Modell {cm.id} · Profil {decision.profile}" + (" · CPU-Modus" if decision.cpu_only else ""),
            )
        if name is None:
            from backend.providers.base import ProviderInfo

            info = ProviderInfo(name="studio", display_name="Studio")
        else:
            info = self.registry.infos.get(name)
            if info is None:
                raise ValidationError(f"Unbekannter Provider '{name}'")
        return self.costs.estimate(info, job_type, model=cm.id if cm else params.get("model"), count=count,
                                   resources=resources)

    def _authorize(self, job_type: str, params: dict[str, Any]) -> CostEstimate:
        est = self.estimate(job_type, params)
        if est.requires_confirmation:
            info = self.registry.infos[est.provider]
            self.costs.authorize(info, est, params.get("confirm_token"))
        return est

    # ------------------------------------------------------------- submission
    async def submit(self, job_type: str, params: dict[str, Any], *, project: str | None = None,
                     label: str | None = None, parent_id: str | None = None) -> Job:
        if job_type not in JOB_TYPES:
            raise ValidationError(f"Unbekannter Job-Typ '{job_type}'", details={"known": sorted(JOB_TYPES)})
        self._validate(job_type, params)
        est = self._authorize(job_type, params)
        stored = {k: v for k, v in params.items() if k != "confirm_token"}
        if est.requires_confirmation:
            stored["_cost_estimate"] = est.model_dump()
        provider = self._provider_name(JOB_TYPES[job_type][0], params)
        return await self.queue.submit(job_type, stored, provider=provider, project=project or params.get("project"),
                                       label=label or self._label(job_type, params), parent_id=parent_id)

    def _label(self, job_type: str, params: dict[str, Any]) -> str:
        text = params.get("prompt") or params.get("title") or params.get("workflow_id") or params.get("composition") or ""
        return f"{job_type}: {str(text)[:60]}".strip(": ")

    def _validate(self, job_type: str, params: dict[str, Any]) -> None:
        """Fail fast on schema errors before queueing (pydantic validation of the request)."""
        clean = {k: v for k, v in params.items() if k not in ("provider", "confirm_token")}
        try:
            if job_type == "image.generate":
                ImageGenerateRequest(**clean)
            elif job_type == "image.edit":
                ImageEditRequest(**clean)
            elif job_type == "image.inpaint":
                InpaintRequest(**clean)
            elif job_type == "image.outpaint":
                OutpaintRequest(**clean)
            elif job_type == "image.upscale":
                UpscaleRequest(**clean)
            elif job_type == "video.upscale":
                VideoUpscaleRequest(**clean)
            elif job_type in ("video.generate", "video.image_to_video"):
                VideoGenerateRequest(**{k: v for k, v in clean.items() if k != "camera_move"})
            elif job_type.startswith("process."):
                PROCESS_OPS[job_type.split(".", 1)[1]][0](**clean)
            elif job_type == "motion.render":
                MotionRenderRequest(**clean)
            elif job_type == "render3d.render":
                Render3DRequest(**clean)
            elif job_type == "brand.guidelines":
                BrandGuideRequest(**clean)
            elif job_type == "workflow.run":
                self.workflows.get(str(clean.get("workflow_id", "")))
        except StudioError:
            raise
        except Exception as exc:  # pydantic.ValidationError
            raise ValidationError(f"Ungültige Parameter für {job_type}: {exc}") from exc

    # ------------------------------------------------------------- job wiring
    def _register_jobs(self) -> None:
        ops: dict[str, Op] = {
            "image.generate": self.op_image_generate,
            "image.edit": self.op_image_edit,
            "image.inpaint": self.op_image_inpaint,
            "image.outpaint": self.op_image_outpaint,
            "image.upscale": self.op_image_upscale,
            "image.remove_background": self.op_image_remove_background,
            "image.resize": self.op_image_resize,
            "image.text_overlay": self.op_image_text_overlay,
            "image.palette": self.op_image_palette,
            "image.contact_sheet": self.op_image_contact_sheet,
            "video.generate": self.op_video_generate,
            "video.image_to_video": self.op_video_generate,
            "video.upscale": self.op_video_upscale,
            "motion.render": self.op_motion_render,
            "render3d.render": self.op_render3d,
            "quality.analyze": self.op_quality_analyze,
            "quality.report": self.op_quality_report,
            "brand.guidelines": self.op_brand_guidelines,
            "workflow.run": self.op_workflow_run,
            "system.smoke_test": self.op_smoke_test,
        }
        for op in PROCESS_OPS:
            ops[f"process.{op}"] = self._make_process_op(op)
        for job_type, fn in ops.items():
            role, resource = JOB_TYPES[job_type]
            timeout = self.settings.comfyui.generation_timeout_s + 300 if resource == "gpu" else None
            self.queue.register(job_type, self._with_cost_record(fn), resource=resource, timeout_s=timeout)
        self.ops = ops

    def _with_cost_record(self, fn: Op) -> Op:
        async def wrapped(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
            result = await fn(params, ctx)
            if params.get("_cost_estimate"):
                self.costs.record(CostEstimate(**params["_cost_estimate"]), ctx.job_id)
            return result

        return wrapped

    async def run_op(self, job_type: str, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        """Run an operation inline (used by workflow steps) while respecting resource pools."""
        if job_type not in self.ops:
            raise ValidationError(f"Unbekannte Operation '{job_type}'")
        self._validate(job_type, params)
        self._authorize(job_type, params)
        resource = JOB_TYPES[job_type][1]
        if resource == "workflow":
            return await self.ops[job_type](params, ctx)
        async with self.queue.semaphores[resource]:
            return await self.ops[job_type](params, ctx)

    # ---------------------------------------------------------------- helpers
    def _out_ctx(self, ctx: JobContext, params: dict[str, Any]) -> JobContext:
        ctx.output_dir = self.assets.generated_dir(params.get("project"))
        return ctx

    async def _register(self, result: GenerationResult, ctx: JobContext, params: dict[str, Any], *,
                        prompt: str | None = None, negative: str | None = None, extra_tags: list[str] | None = None,
                        qa: bool = True, qa_expect: dict[str, Any] | None = None) -> dict[str, Any]:
        assets: list[Asset] = []
        tags = list(params.get("tags") or []) + list(extra_tags or [])
        for f in result.files:
            if not Path(f).is_file():
                continue
            asset = await self.assets.register(
                Path(f), job_id=ctx.job_id, provider=result.provider, model=result.model, prompt=prompt,
                negative_prompt=negative or None, seed=result.seed, params=result.parameters, tags=tags,
                project=params.get("project"), workflow=result.workflow,
            )
            assets.append(asset)
        quality = []
        if qa and self.settings.quality.auto_check:
            for asset in assets:
                if asset.kind not in ("image", "video"):
                    continue
                try:
                    rep = await self.quality.analyze(self.assets.abs_path(asset), **(qa_expect or {}))
                    asset = self.assets.set_quality(asset.id, rep.model_dump())
                    quality.append({"asset_id": asset.id, "score": rep.score, "passed": rep.passed, "summary": rep.summary()})
                except Exception as exc:  # QA must never fail a generation
                    log.warning("QA failed for %s: %s", asset.path, exc)
        assets = [self.assets.get(a.id) for a in assets]
        return {
            "assets": [a.model_dump() for a in assets],
            "asset_ids": [a.id for a in assets],
            "asset": assets[0].model_dump() if assets else None,
            "files": [a.path for a in assets],
            "provider": result.provider,
            "model": result.model,
            "seed": result.seed,
            "parameters": result.parameters,
            "metadata": result.metadata,
            "quality": quality,
        }

    def _image_provider(self, params: dict[str, Any]) -> tuple[Any, str]:
        name = params.get("provider") or self.registry.defaults["image"]
        return self.registry.get("image", name), name

    async def _auto_model(self, task: str, provider: Any, params: dict[str, Any]) -> str | None:
        if params.get("model") or not hasattr(provider, "installed"):
            return params.get("model")
        report, decision = self.hardware()
        installed = await provider.installed()
        cand = self.selector.choose(task, decision, report.ram_total_gb, installed)
        return cand.model.id

    # ------------------------------------------------------------ image ops
    async def op_image_generate(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate")})
        provider, _ = self._image_provider(params)
        if p.get("control_image") and not p.get("model") and hasattr(provider, "installed"):
            p["model"] = await self._controlnet_base_model(provider)
        p["model"] = await self._auto_model("text_to_image", provider, p)
        cm = self.catalog.find(p["model"]) if p.get("model") else None
        built = build_prompt(p["prompt"], style=p.get("style"), family=cm.family if cm else None,
                             negative=p.get("negative_prompt", ""),
                             supports_negative=cm.supports_negative_prompt if cm else True)
        p["prompt"], p["negative_prompt"] = built["prompt"], built["negative_prompt"]
        _, decision = self.hardware()
        profile = self.catalog.profiles.get(decision.profile)
        if profile and profile.image.max_batch:
            p["batch_size"] = min(int(p.get("batch_size", 1)), profile.image.max_batch)
        req = ImageGenerateRequest(**p)
        result = await provider.generate(req, ctx)
        return await self._register(result, ctx, params, prompt=req.prompt, negative=req.negative_prompt,
                                    extra_tags=[t for t in ("generated", p.get("style")) if t])

    async def _controlnet_base_model(self, provider: Any) -> str:
        """ControlNet templates target SD 1.5 – pick the best installed SD 1.5 variant."""
        report, decision = self.hardware()
        installed = await provider.installed()
        for cand in self.selector.candidates("text_to_image", decision, report.ram_total_gb, installed):
            if cand.model.family == "sd15" and cand.installed and cand.fits:
                return cand.model.id
        raise ModelNotInstalledError("ControlNet benötigt ein SD-1.5-Modell: python scripts/models/download_models.py --model sd15-lcm")

    async def _edit_like(self, task: str, method: str, model_cls: type, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate")})
        provider, _ = self._image_provider(params)
        p["model"] = await self._auto_model(task, provider, p)
        req = model_cls(**p)
        result = await getattr(provider, method)(req, ctx)
        return await self._register(result, ctx, params, prompt=getattr(req, "prompt", None), extra_tags=[task])

    async def op_image_edit(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._edit_like("image_to_image", "edit", ImageEditRequest, params, ctx)

    async def op_image_inpaint(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._edit_like("inpaint", "inpaint", InpaintRequest, params, ctx)

    async def op_image_outpaint(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._edit_like("outpaint", "outpaint", OutpaintRequest, params, ctx)

    async def op_image_upscale(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate")})
        req = UpscaleRequest(**p)
        provider = None
        if req.method in ("auto", "model"):
            try:
                provider, _ = self._image_provider(params)
                if hasattr(provider, "installed"):
                    installed = await provider.installed()
                    if not req.model:
                        report, decision = self.hardware()
                        req.model = self.selector.choose("upscale", decision, report.ram_total_gb, installed).model.id
                result = await provider.upscale(req, ctx)
                return await self._register(result, ctx, params, extra_tags=["upscaled"])
            except StudioError as exc:
                if req.method == "model":
                    raise
                log.info("AI upscale unavailable (%s) – falling back to Lanczos", exc.message)
        result = await self.image_tools.upscale(UpscaleRequest(**{**p, "method": "lanczos"}), ctx)
        out = await self._register(result, ctx, params, extra_tags=["upscaled", "lanczos"])
        out["fallback"] = "lanczos"
        return out

    async def _tool_op(self, method: str, model_cls: type, params: dict[str, Any], ctx: JobContext, tags: list[str],
                       qa: bool = True) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate", "project", "tags")})
        result = await getattr(self.image_tools, method)(model_cls(**p), ctx)
        return await self._register(result, ctx, params, extra_tags=tags, qa=qa)

    async def op_image_remove_background(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._tool_op("remove_background", RemoveBackgroundRequest, params, ctx, ["no-background"])

    async def op_image_resize(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._tool_op("resize", ResizeImageRequest, params, ctx, ["resized", params.get("format_preset") or ""])

    async def op_image_text_overlay(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._tool_op("text_overlay", TextOverlayRequest, params, ctx, ["text-overlay"])

    async def op_image_palette(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        out = await self._tool_op("palette", PaletteRequest, params, ctx, ["palette", "brand"], qa=False)
        out["colors"] = out["metadata"].get("colors", [])
        return out

    async def op_image_contact_sheet(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return await self._tool_op("contact_sheet", ContactSheetRequest, params, ctx, ["contact-sheet"], qa=False)

    # ------------------------------------------------------------ video ops
    async def op_video_generate(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate")})
        name = params.get("provider") or self.registry.defaults["video"]
        provider = self.registry.get("video", name)
        report, decision = self.hardware()
        task = "image_to_video" if p.get("image") else "text_to_video"
        if name == "comfyui" and decision.cpu_only:
            profile = self.catalog.profiles.get(decision.profile)
            raise HardwareInsufficientError(
                "KI-Videogenerierung benötigt eine GPU – auf diesem System nicht verfügbar. Alternative: Workflow "
                f"'{profile.video.fallback_workflow if profile else 'videos/kenburns-slideshow'}' (Standbilder + Kamerafahrten + Übergänge).",
                details={"fallback_workflow": profile.video.fallback_workflow if profile else None},
            )
        if p.pop("camera_move", None) and not p.get("camera"):
            p["camera"] = camera_phrase(params.get("camera_move"))
        p["model"] = await self._auto_model(task, provider, p)
        profile = self.catalog.profiles.get(decision.profile)
        if profile and profile.video.max_frames and p.get("frames"):
            p["frames"] = min(int(p["frames"]), profile.video.max_frames)
        req = VideoGenerateRequest(**p)
        result = await provider.generate(req, ctx)
        return await self._register(result, ctx, params, prompt=req.prompt, negative=req.negative_prompt,
                                    extra_tags=["generated", "video", task],
                                    qa_expect={"expected_fps": result.parameters.get("fps")})

    async def op_video_upscale(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        """AI upscale (Real-ESRGAN per frame via ComfyUI) with FFmpeg-Lanczos fallback."""
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate")})
        req = VideoUpscaleRequest(**p)
        if req.method in ("auto", "model"):
            try:
                provider = self.registry.get("video", params.get("provider"))
                result = await provider.upscale(req, ctx)
                return await self._register(result, ctx, params, extra_tags=["upscaled", "video"])
            except StudioError as exc:
                if req.method == "model":
                    raise
                log.info("AI video upscale unavailable (%s) – FFmpeg Lanczos fallback", exc.message)
        info = await self.ffmpeg.get_info(Path(req.source))
        w = ffm.even((info.width or 640) * req.scale)
        h = ffm.even((info.height or 360) * req.scale)
        result = await self.ffmpeg.convert(ffm.ConvertRequest(source=req.source, format="mp4", width=w, height=h), ctx)
        out = await self._register(result, ctx, params, extra_tags=["upscaled", "video", "lanczos"])
        out["fallback"] = "lanczos"
        return out

    def _make_process_op(self, op: str) -> Op:
        model_cls, method = PROCESS_OPS[op]

        async def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
            self._out_ctx(ctx, params)
            p = self._resolve_params({k: v for k, v in params.items()
                                      if k not in ("provider", "confirm_token", "_cost_estimate", "project", "tags")})
            req = model_cls(**p)
            result = await getattr(self.ffmpeg, method)(req, ctx)
            return await self._register(result, ctx, params, extra_tags=[op], qa=op in ("render", "merge"))

        return run

    async def op_motion_render(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate", "project", "tags")})
        req = MotionRenderRequest(**p)
        motion = self.registry.get("motion", params.get("provider"))
        if not (await motion.health()).available and req.composition in ("TitleIntro", "Outro"):
            # FFmpeg fallback keeps intros/outros working without Node.js/Remotion.
            props = req.props
            title = props.get("title") or props.get("headline") or "Titel"
            card = ffm.TitleCardRequest(title=title, subtitle=props.get("subtitle") or props.get("cta"),
                                        duration_s=req.duration_s or 4, width=req.width or 1920, height=req.height or 1080,
                                        fps=req.fps, background=props.get("background", "#0F172A"),
                                        color=props.get("textColor", "#FFFFFF"), accent=props.get("accent", "#38BDF8"))
            result = await self.ffmpeg.title_card(card, ctx)
            out = await self._register(result, ctx, params, extra_tags=["motion", "title-card", "ffmpeg-fallback"])
            out["fallback"] = "ffmpeg_title_card"
            return out
        result = await motion.render(req, ctx)
        return await self._register(result, ctx, params, extra_tags=["motion", req.composition.lower()])

    async def op_render3d(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        p = self._resolve_params({k: v for k, v in params.items() if k not in ("provider", "confirm_token", "_cost_estimate", "project", "tags")})
        req = Render3DRequest(**p)
        result = await self.registry.get("render3d", params.get("provider")).render(req, ctx)
        return await self._register(result, ctx, params, extra_tags=["3d", req.template])

    # ---------------------------------------------------------- quality ops
    async def op_quality_analyze(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        refs = list(params.get("assets") or []) + ([params["source"]] if params.get("source") else [])
        if not refs:
            raise ValidationError("assets (Liste) oder source angeben")
        expect = {k: params[k] for k in ("min_width", "min_height", "expected_aspect", "expected_fps",
                                         "expected_duration_s", "require_audio", "purpose") if params.get(k) is not None}
        reports = []
        for i, ref in enumerate(refs):
            path = self.resolve_input(ref)
            rep = await self.quality.analyze(path, **expect)
            asset = self.assets.find_by_path(path)
            if asset:
                self.assets.set_quality(asset.id, rep.model_dump())
            reports.append({**rep.model_dump(), "asset_id": asset.id if asset else None, "summary": rep.summary()})
            await ctx.progress((i + 1) / len(refs), f"Geprüft: {path.name}")
        if params.get("preset"):
            for r in reports:
                m = r["metrics"]
                if m.get("width") and m.get("height"):
                    r["resolution_check"] = validate_resolution(m["width"], m["height"], preset=params["preset"])
        return {"reports": reports, "passed": all(r["passed"] for r in reports),
                "average_score": round(sum(r["score"] for r in reports) / len(reports), 1)}

    async def op_quality_report(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        analysis = await self.op_quality_analyze(params, ctx.child(0, 0.9))
        from backend.quality.analyzer import QualityReport

        reps = [QualityReport(**{k: v for k, v in r.items() if k in QualityReport.model_fields}) for r in analysis["reports"]]
        out_dir = self.settings.assets_dir / "exports" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"quality_report_{slugify(params.get('title') or 'report')}_{ctx.job_id[:6]}"
        md_path = out_dir / f"{stem}.md"
        md_path.write_text(QualityAnalyzer.report_markdown(reps, params.get("title") or "Qualitätsbericht"), encoding="utf-8")
        json_path = out_dir / f"{stem}.json"
        json_path.write_text(QualityAnalyzer.report_json(reps), encoding="utf-8")
        assets = [await self.assets.register(p, job_id=ctx.job_id, provider="quality", tags=["report", "quality"],
                                             project=params.get("project"), source="report") for p in (md_path, json_path)]
        return {**analysis, "report_assets": [a.model_dump() for a in assets], "report_path": assets[0].path}

    # ------------------------------------------------------------ brand ops
    async def op_brand_guidelines(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        req = BrandGuideRequest(**{k: v for k, v in params.items() if k not in ("tags", "provider")})
        logos = [self.resolve_input(r) for r in req.logos]
        images = [self.resolve_input(r) for r in req.imagery]
        html_doc, md_doc = await asyncio.to_thread(render_brand_guide, req, logos, images)
        out_dir = self.settings.assets_dir / "exports" / "brand" / slugify(req.brand_name)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "brand-guidelines.html").write_text(html_doc, encoding="utf-8")
        (out_dir / "brand-guidelines.md").write_text(md_doc, encoding="utf-8")
        (out_dir / "brand.json").write_text(json.dumps(req.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        assets = []
        for name in ("brand-guidelines.html", "brand-guidelines.md", "brand.json"):
            assets.append(await self.assets.register(out_dir / name, job_id=ctx.job_id, provider="brand",
                                                     tags=["brand", "guidelines", slugify(req.brand_name)],
                                                     project=req.project or req.brand_name, source="export"))
        return {"assets": [a.model_dump() for a in assets], "asset_ids": [a.id for a in assets],
                "asset": assets[0].model_dump(), "files": [a.path for a in assets],
                "typography_suggestions": suggest_typography(req.values + req.voice)}

    # --------------------------------------------------------- workflow ops
    async def op_workflow_run(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        wf = self.workflows.get(params["workflow_id"])
        return await self.workflows.run(wf, params.get("inputs") or {}, ctx, project=params.get("project"),
                                        confirm_token=params.get("confirm_token"))

    async def op_smoke_test(self, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        self._out_ctx(ctx, params)
        img = self.registry.get("image", "comfyui")
        vid = self.registry.get("video", "comfyui")
        image_files = await img.smoke_test(ctx.child(0, 0.5))
        video_files = await vid.smoke_test(ctx.child(0.5, 1.0))
        result = GenerationResult(files=[*image_files, *video_files], provider="comfyui", model="smoke-test")
        return await self._register(result, ctx, {"tags": ["smoke-test"]}, qa=False)

    # ---------------------------------------------------------------- misc
    async def model_overview(self) -> dict[str, Any]:
        report, decision = self.hardware()
        installed: dict[str, set[str]] | None = None
        comfy_error = None
        try:
            prov = self.registry.get("image", "comfyui")
            installed = await prov.installed()
        except Exception as exc:
            comfy_error = getattr(exc, "message", str(exc))
        tasks = ("text_to_image", "image_to_image", "inpaint", "outpaint", "upscale", "text_to_video", "image_to_video")
        by_task = {t: [c.to_dict() for c in self.selector.candidates(t, decision, report.ram_total_gb, installed)] for t in tasks}
        catalog = []
        for m in self.catalog.models.values():
            fits, note = self.catalog.hardware_fit(m, decision.effective_vram_gb, report.ram_total_gb, decision.cpu_only)
            missing = [f.name for f in m.missing_files(installed)] if installed is not None else None
            catalog.append({**m.model_dump(exclude={"files"}), "files": [f.model_dump() for f in m.files],
                            "size_gb": m.total_size_gb, "fits_hardware": fits, "hardware_note": note,
                            "installed": (not missing) if missing is not None else None, "missing_files": missing})
        return {"profile": decision.model_dump(), "comfyui_error": comfy_error, "catalog": catalog, "by_task": by_task,
                "recommended": self.selector.recommended(decision, report.ram_total_gb)}
