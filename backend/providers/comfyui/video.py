"""ComfyUI video provider: Wan 2.1 / 2.2 text-to-video and image-to-video."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from backend.core.catalog import frames_4n1
from backend.jobs.context import JobContext
from backend.providers.base import (
    Capability,
    GenerationResult,
    ModelInfo,
    ProviderHealth,
    VideoGenerateRequest,
    VideoProvider,
    VideoUpscaleRequest,
)

from .common import ComfyBase, random_seed


def _snap(value: int, multiple: int = 16) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


class ComfyUIVideoProvider(ComfyBase, VideoProvider):
    def __init__(self, info: Any, settings: Any, shared: dict[str, Any] | None = None) -> None:
        super().__init__(info, settings, shared)
        self._init_comfy()

    def get_capabilities(self) -> set[Capability]:
        return {Capability.TEXT_TO_VIDEO, Capability.IMAGE_TO_VIDEO, Capability.VIDEO_UPSCALE}

    async def health(self) -> ProviderHealth:
        return await self.comfy_health()

    async def get_models(self) -> list[ModelInfo]:
        return await self.models_info(("video", "upscale"))

    async def close(self) -> None:
        await self.client.close()

    async def generate(self, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        if req.image:
            return await self.image_to_video(req, ctx)
        return await self._run("text_to_video", req, ctx)

    async def image_to_video(self, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        return await self._run("image_to_video", req, ctx)

    async def _run(self, task: str, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        await ctx.progress(0.0, "Videomodell wird ausgewählt")
        cm, template_id, params = await self.resolve_model(req.model, task)
        template = self.templates.get(req.template or template_id)
        d = cm.defaults if cm else {}
        fps = req.fps or int(d.get("fps", 16))
        if req.width and req.height:
            width, height = _snap(req.width), _snap(req.height)
        else:
            res = self.catalog.resolution(cm.resolution_family if cm else None, req.aspect_ratio or "16:9")
            width, height = res or (int(d.get("width", 832)), int(d.get("height", 480)))
        if req.frames:
            frames = req.frames
        elif req.duration_s:
            frames = int(round(req.duration_s * fps)) + 1
        else:
            frames = int(d.get("frames", 49))
        frames = frames_4n1(frames, cm.max_frames if cm else None)
        seed = req.seed if req.seed is not None else random_seed()
        prompt = req.prompt if not req.camera else f"{req.prompt.rstrip('. ')}. {req.camera}"
        values: dict[str, Any] = {
            **params,
            "prompt": prompt,
            "width": width,
            "height": height,
            "frames": frames,
            "fps": fps,
            "seed": seed,
            "steps": req.steps or d.get("steps"),
            "cfg": req.cfg if req.cfg is not None else d.get("cfg"),
            "sampler": d.get("sampler"),
            "scheduler": d.get("scheduler"),
            "shift": d.get("shift"),
        }
        if req.negative_prompt:
            values["negative_prompt"] = req.negative_prompt
        if task == "image_to_video":
            if not req.image:
                from backend.core.errors import ValidationError

                raise ValidationError("Image-to-Video benötigt ein Startbild (image)")
            await ctx.progress(0.01, "Startbild wird hochgeladen")
            values["image"] = await self.upload(req.image)
        workflow = self.build(template, values, [])
        files = await self.execute(template, workflow, ctx)
        return GenerationResult(
            files=files, provider=self.name, model=cm.id if cm else req.model, seed=seed,
            parameters={k: v for k, v in values.items() if k not in ("prompt", "negative_prompt", "image")}
            | {"template": template.id, "task": task, "duration_s": round((frames - 1) / fps, 2)},
            workflow=workflow,
            metadata={"license": cm.license if cm else None, "commercial_use": cm.commercial_use if cm else None},
        )

    async def upscale(self, req: VideoUpscaleRequest, ctx: JobContext) -> GenerationResult:
        cm, template_id, params = await self.resolve_model(req.model, "video_upscale")
        template = self.templates.get(template_id)
        native = (cm.native_scale if cm else None) or 4
        await ctx.progress(0.01, "Video wird hochgeladen")
        # LoadVideo lists files in the input root → upload without subfolder, unique name
        src = Path(req.source)
        staged = ctx.output_dir / ".tmp" / f"{uuid.uuid4().hex[:8]}_{src.name}"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, staged)
        try:
            name = await self.client.upload_image(staged, subfolder="")
        finally:
            staged.unlink(missing_ok=True)
        values = {**params, "video": name, "rescale": round(req.scale / native, 4)}
        workflow = self.build(template, values, [])
        files = await self.execute(template, workflow, ctx)
        return GenerationResult(files=files, provider=self.name, model=cm.id if cm else None,
                                parameters={"scale": req.scale, "native_scale": native, "template": template.id},
                                workflow=workflow)

    async def smoke_test(self, ctx: JobContext) -> list:
        template = self.templates.get("smoke_test_video")
        return await self.execute(template, self.build(template, {}, []), ctx)
