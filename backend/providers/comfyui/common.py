"""Shared logic for the ComfyUI image and video providers."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from backend.core.catalog import CatalogModel, load_catalog
from backend.core.errors import CapabilityNotSupportedError, GenerationError, ModelNotInstalledError
from backend.jobs.context import JobContext
from backend.providers.base import ModelInfo, ProviderHealth

from .client import ComfyUIClient
from .templates import ComfyTemplate, TemplateLibrary, insert_loras, render

GENERIC_CHECKPOINT_TEMPLATES = {
    "text_to_image": "checkpoint_txt2img",
    "image_to_image": "checkpoint_img2img",
    "inpaint": "checkpoint_inpaint",
    "outpaint": "checkpoint_outpaint",
}
SEED_MAX = 2**53 - 1


def random_seed() -> int:
    return random.randint(0, SEED_MAX)


class ComfyBase:
    """Mixin providing client, templates, catalog and model resolution."""

    name: str
    settings: Any
    shared: dict[str, Any]

    def _init_comfy(self) -> None:
        cfg = self.settings.comfyui
        self.client: ComfyUIClient = self.shared.setdefault(
            "client",
            ComfyUIClient(cfg.url, request_timeout=cfg.request_timeout_s, poll_interval=cfg.poll_interval_s,
                          use_websocket=cfg.use_websocket),
        )
        self.templates: TemplateLibrary = self.shared.setdefault(
            "templates", TemplateLibrary(self.settings.resolve(self.settings.paths.comfy_templates_dir))
        )
        self.catalog = load_catalog(str(self.settings.configs_dir))

    # ---------------------------------------------------------------- models
    def model_folders(self) -> list[str]:
        folders = {"checkpoints", "loras", "upscale_models", "diffusion_models", "text_encoders", "vae"}
        for m in self.catalog.models.values():
            folders.update(f.folder for f in m.files)
        return sorted(folders)

    async def installed(self) -> dict[str, set[str]]:
        return await self.client.installed_models(self.model_folders())

    async def resolve_model(self, model: str | None, task: str) -> tuple[CatalogModel | None, str, dict[str, Any]]:
        installed = await self.installed()
        if model:
            cm = self.catalog.find(model)
            if cm is not None:
                if task not in cm.tasks:
                    raise CapabilityNotSupportedError(
                        f"Modell '{cm.id}' unterstützt '{task}' nicht (unterstützt: {', '.join(cm.tasks)})"
                    )
                missing = cm.missing_files(installed)
                if missing:
                    raise ModelNotInstalledError(
                        f"Modell '{cm.id}' ist nicht vollständig installiert. Fehlend: "
                        + ", ".join(f"{f.folder}/{f.name}" for f in missing)
                        + f". Installieren: python scripts/models/download_models.py --model {cm.id}",
                        details={"model": cm.id, "missing_files": [f.name for f in missing]},
                    )
                return cm, cm.tasks[task], dict(cm.params)
            if model in installed.get("checkpoints", set()) and task in GENERIC_CHECKPOINT_TEMPLATES:
                return None, GENERIC_CHECKPOINT_TEMPLATES[task], {"model": model}
            raise ModelNotInstalledError(f"Modell '{model}' ist weder im Katalog noch in ComfyUI installiert.")
        for cm in self.catalog.for_task(task):
            if not cm.missing_files(installed):
                return cm, cm.tasks[task], dict(cm.params)
        candidates = ", ".join(m.id for m in self.catalog.for_task(task)) or "–"
        raise ModelNotInstalledError(
            f"Kein installiertes Modell für '{task}'. Kandidaten: {candidates}. "
            "Installieren: python scripts/models/download_models.py --recommended",
            details={"task": task},
        )

    async def models_info(self, types: tuple[str, ...]) -> list[ModelInfo]:
        installed = await self.installed()
        out: list[ModelInfo] = []
        for cm in self.catalog.models.values():
            if cm.type not in types:
                continue
            missing = cm.missing_files(installed)
            out.append(ModelInfo(
                id=cm.id, name=cm.name, type=cm.type, provider=self.name, installed=not missing, catalog_id=cm.id,
                family=cm.family, tasks=list(cm.tasks), license=cm.license, commercial_use=cm.commercial_use,
                size_gb=cm.total_size_gb, missing_files=[f.name for f in missing],
            ))
        if "image" in types:
            known = {f.name for m in self.catalog.models.values() for f in m.files}
            for ckpt in sorted(installed.get("checkpoints", set()) - known):
                out.append(ModelInfo(id=ckpt, name=ckpt, type="image", provider=self.name, installed=True,
                                     family="checkpoint", tasks=list(GENERIC_CHECKPOINT_TEMPLATES)))
        return out

    # ---------------------------------------------------------------- execution
    def build(self, template: ComfyTemplate, values: dict[str, Any], loras: list[dict[str, Any]]) -> dict[str, Any]:
        usable = {k: v for k, v in values.items() if k in template.meta.parameters and v is not None}
        workflow = render(template, usable)
        return insert_loras(workflow, template.meta.lora_anchor, loras)

    async def execute(self, template: ComfyTemplate, workflow: dict[str, Any], ctx: JobContext) -> list[Path]:
        history = await self.client.run(workflow, ctx, timeout=self.settings.comfyui.generation_timeout_s)
        items = self.client.output_items(history, template.meta.outputs or None)
        files = []
        for i, item in enumerate(items):
            files.append(await self.client.download(item, ctx.output_dir))
            await ctx.progress(0.96 + 0.04 * (i + 1) / max(1, len(items)), "Ergebnis wird gespeichert")
        if not files:
            raise GenerationError("ComfyUI hat keine Ausgabedateien erzeugt")
        return files

    async def comfy_health(self) -> ProviderHealth:
        try:
            stats = await self.client.system_stats()
        except Exception as exc:
            return ProviderHealth(available=False, detail=str(getattr(exc, "message", exc)))
        system = stats.get("system", {})
        devices = stats.get("devices", [])
        return ProviderHealth(
            available=True,
            detail=f"ComfyUI {system.get('comfyui_version', '?')} · {', '.join(d.get('name', '?') for d in devices)[:120]}",
            version=system.get("comfyui_version"),
            extra={"devices": devices, "ram_total": system.get("ram_total"), "ram_free": system.get("ram_free"),
                   "pytorch": system.get("pytorch_version"), "templates": len(self.templates.templates)},
        )

    async def upload(self, path: str | Path) -> str:
        return await self.client.upload_image(Path(path))
