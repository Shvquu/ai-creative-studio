"""ComfyUI image provider: text-to-image, image-to-image, inpaint, outpaint, upscale."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from backend.core.errors import CapabilityNotSupportedError, ValidationError
from backend.jobs.context import JobContext
from backend.providers.base import (
    Capability,
    GenerationResult,
    ImageEditRequest,
    ImageGenerateRequest,
    ImageProvider,
    InpaintRequest,
    ModelInfo,
    OutpaintRequest,
    ProviderHealth,
    UpscaleRequest,
)

from .common import ComfyBase, random_seed


def bypass_canny(workflow: dict[str, Any]) -> dict[str, Any]:
    """control_mode=none: feed the control image straight into ControlNet (scribbles, line art, depth maps)."""
    canny_ids = [k for k, v in workflow.items() if v["class_type"] == "Canny"]
    for cid in canny_ids:
        source = workflow[cid]["inputs"]["image"]
        for node in workflow.values():
            for key, value in node["inputs"].items():
                if value == [cid, 0]:
                    node["inputs"][key] = source
        del workflow[cid]
    return workflow


def _snap(value: int, multiple: int = 8) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


class ComfyUIImageProvider(ComfyBase, ImageProvider):
    def __init__(self, info: Any, settings: Any, shared: dict[str, Any] | None = None) -> None:
        super().__init__(info, settings, shared)
        self._init_comfy()

    def get_capabilities(self) -> set[Capability]:
        return {Capability.TEXT_TO_IMAGE, Capability.IMAGE_TO_IMAGE, Capability.INPAINT, Capability.OUTPAINT,
                Capability.UPSCALE}

    async def health(self) -> ProviderHealth:
        return await self.comfy_health()

    async def get_models(self) -> list[ModelInfo]:
        return await self.models_info(("image", "upscale"))

    async def close(self) -> None:
        await self.client.close()

    # ---------------------------------------------------------------- helpers
    def _dims(self, req: ImageGenerateRequest, cm: Any) -> tuple[int, int]:
        defaults = cm.defaults if cm else {}
        if req.width and req.height:
            return _snap(req.width), _snap(req.height)
        if req.aspect_ratio and cm is not None:
            res = self.catalog.resolution(cm.resolution_family, req.aspect_ratio)
            if res:
                return res
        return int(defaults.get("width", 1024)), int(defaults.get("height", 1024))

    @staticmethod
    def _sampling_values(req: Any, defaults: dict[str, Any]) -> dict[str, Any]:
        return {
            "steps": req.steps or defaults.get("steps"),
            "cfg": req.cfg if req.cfg is not None else defaults.get("cfg"),
            "sampler": getattr(req, "sampler", None) or defaults.get("sampler"),
            "scheduler": getattr(req, "scheduler", None) or defaults.get("scheduler"),
        }

    # ------------------------------------------------------------- operations
    async def _resolve_controlnet(self, req: ImageGenerateRequest, base_family: str | None) -> str:
        """Pick the ControlNet file for the request (catalog id, file name or by control_mode)."""
        if base_family not in (None, "sd15"):
            raise CapabilityNotSupportedError(
                f"ControlNet ist für SD-1.5-Modelle eingerichtet (gewählt: Familie '{base_family}'). model='sd15' oder 'sd15-lcm' wählen."
            )
        installed = (await self.installed()).get("controlnet", set())
        if req.controlnet:
            cm = self.catalog.find(req.controlnet) if req.controlnet in self.catalog.models else None
            name = cm.files[0].name if cm else req.controlnet
        else:
            wanted = "controlnet-canny-sd15" if req.control_mode == "canny" else "controlnet-scribble-sd15"
            name = self.catalog.get(wanted).files[0].name
        if name not in installed:
            from backend.core.errors import ModelNotInstalledError

            mid = next((m.id for m in self.catalog.models.values() if any(f.name == name for f in m.files)), name)
            raise ModelNotInstalledError(
                f"ControlNet '{name}' fehlt. Installieren: python scripts/models/download_models.py --model {mid}",
                details={"missing_files": [name]},
            )
        return name

    async def generate(self, req: ImageGenerateRequest, ctx: JobContext) -> GenerationResult:
        await ctx.progress(0.0, "Modell wird ausgewählt")
        cm, template_id, params = await self.resolve_model(req.model, "text_to_image")
        control_name = None
        if req.control_image:
            control_name = await self._resolve_controlnet(req, cm.family if cm else None)
            template_id = "checkpoint_controlnet_txt2img"
        template = self.templates.get(req.template or template_id)
        defaults = cm.defaults if cm else {}
        width, height = self._dims(req, cm)
        seed = req.seed if req.seed is not None else random_seed()
        negative = req.negative_prompt if (cm is None or cm.supports_negative_prompt) else ""
        values: dict[str, Any] = {
            **params,
            "prompt": req.prompt,
            "negative_prompt": negative,
            "width": width,
            "height": height,
            "batch_size": req.batch_size,
            "seed": seed,
            **self._sampling_values(req, defaults),
        }
        if control_name:
            await ctx.progress(0.01, "Steuerbild wird hochgeladen")
            values.update({"control_image": await self.upload(req.control_image), "controlnet": control_name,
                           "control_strength": req.control_strength})
        loras = [*(cm.extra_loras if cm else []), *[lora.model_dump() for lora in req.loras]]
        workflow = self.build(template, values, loras)
        if control_name and req.control_mode == "none":
            bypass_canny(workflow)
        files = await self.execute(template, workflow, ctx)
        return GenerationResult(
            files=files, provider=self.name, model=cm.id if cm else req.model, seed=seed,
            parameters={k: v for k, v in values.items() if k not in ("prompt", "negative_prompt", "control_image")} | {
                "template": template.id, "loras": loras} | ({"control_mode": req.control_mode, "control_source": str(req.control_image)}
                                                           if control_name else {}),
            workflow=workflow,
            metadata={"license": cm.license if cm else None, "commercial_use": cm.commercial_use if cm else None},
        )

    async def _edit_common(self, task: str, req: ImageEditRequest, ctx: JobContext,
                           extra: dict[str, Any]) -> GenerationResult:
        cm, template_id, params = await self.resolve_model(req.model, task)
        template = self.templates.get(template_id)
        defaults = {**(cm.defaults if cm else {}), **(cm.edit_defaults if cm else {})}
        seed = req.seed if req.seed is not None else random_seed()
        await ctx.progress(0.01, "Bild wird hochgeladen")
        values: dict[str, Any] = {
            **params,
            "image": await self.upload(req.source),
            "prompt": req.prompt or "high quality, detailed",
            "negative_prompt": req.negative_prompt,
            "strength": req.strength,
            "seed": seed,
            **self._sampling_values(req, defaults),
            **extra,
        }
        loras = list(cm.extra_loras if cm else [])
        workflow = self.build(template, values, loras)
        files = await self.execute(template, workflow, ctx)
        return GenerationResult(
            files=files, provider=self.name, model=cm.id if cm else req.model, seed=seed,
            parameters={k: v for k, v in values.items() if k not in ("prompt", "negative_prompt", "image")}
            | {"template": template.id, "source": str(req.source)},
            workflow=workflow,
        )

    async def edit(self, req: ImageEditRequest, ctx: JobContext) -> GenerationResult:
        return await self._edit_common("image_to_image", req, ctx, {})

    async def inpaint(self, req: InpaintRequest, ctx: JobContext) -> GenerationResult:
        mask_path = Path(req.mask) if req.mask else self._mask_from_alpha(Path(req.source), ctx.output_dir)
        mask_name = await self.upload(mask_path)
        return await self._edit_common("inpaint", req, ctx, {"mask": mask_name, "grow_mask_by": req.grow_mask_by})

    async def outpaint(self, req: OutpaintRequest, ctx: JobContext) -> GenerationResult:
        if not any((req.left, req.top, req.right, req.bottom)):
            raise ValidationError("Outpainting braucht mindestens einen Rand > 0 (left/top/right/bottom)")
        return await self._edit_common("outpaint", req, ctx, {
            "left": req.left, "top": req.top, "right": req.right, "bottom": req.bottom, "feathering": req.feathering,
        })

    async def upscale(self, req: UpscaleRequest, ctx: JobContext) -> GenerationResult:
        if req.method == "lanczos":
            raise CapabilityNotSupportedError("Lanczos-Upscaling übernimmt der Provider 'local-image-tools'")
        cm, template_id, params = await self.resolve_model(req.model, "upscale")
        template = self.templates.get(template_id)
        native = (cm.native_scale if cm else None) or 4
        values = {**params, "image": await self.upload(req.source), "rescale": round(req.scale / native, 4)}
        workflow = self.build(template, values, [])
        files = await self.execute(template, workflow, ctx)
        return GenerationResult(files=files, provider=self.name, model=cm.id if cm else None,
                                parameters={"scale": req.scale, "native_scale": native, "template": template.id},
                                workflow=workflow)

    @staticmethod
    def _mask_from_alpha(source: Path, out_dir: Path) -> Path:
        with Image.open(source) as im:
            if "A" not in im.getbands():
                raise ValidationError(
                    "Für Inpainting ohne Maske muss das Bild transparente Bereiche (Alpha-Kanal) enthalten."
                )
            alpha = im.getchannel("A")
            mask = alpha.point(lambda a: 255 if a < 128 else 0).convert("RGB")
        target = out_dir / ".tmp"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{source.stem}_mask.png"
        mask.save(path)
        return path

    # --- auxiliary --------------------------------------------------------
    async def smoke_test(self, ctx: JobContext) -> list[Path]:
        template = self.templates.get("smoke_test_image")
        workflow = self.build(template, {}, [])
        return await self.execute(template, workflow, ctx)
