"""Model catalog (configs/models.yaml) and hardware profiles (configs/hardware_profiles.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import load_yaml
from .errors import NotFoundError, ValidationError


class ModelFile(BaseModel):
    name: str
    folder: str
    url: str
    size_gb: float
    sha256: str | None = None


class CatalogModel(BaseModel):
    id: str
    name: str
    type: Literal["image", "video", "upscale", "controlnet"]
    family: str
    description: str = ""
    files: list[ModelFile]
    min_vram_gb: float = 0
    rec_vram_gb: float = 0
    min_ram_gb: float = 0
    cpu_ok: bool = False
    license: str = ""
    commercial_use: bool | Literal["restricted"] = False
    license_note: str | None = None
    tasks: dict[str, str] = {}
    params: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    edit_defaults: dict[str, Any] = {}
    extra_loras: list[dict[str, Any]] = []
    resolution_family: str | None = None
    supports_negative_prompt: bool = True
    native_scale: int | None = None
    max_frames: int | None = None
    frame_rule: str | None = None
    est_seconds: dict[str, float] = {}

    @property
    def total_size_gb(self) -> float:
        return round(sum(f.size_gb for f in self.files), 2)

    def missing_files(self, installed: dict[str, set[str]]) -> list[ModelFile]:
        return [f for f in self.files if f.name not in installed.get(f.folder, set())]


class ProfileSection(BaseModel):
    models: list[str] = []
    max_long_edge: int | None = None
    max_batch: int | None = None
    requires_gpu: bool = False
    max_frames: int | None = None
    fallback_workflow: str | None = None


class HardwareProfile(BaseModel):
    name: str
    label: str
    criteria: str = ""
    image: ProfileSection = ProfileSection()
    video: ProfileSection = ProfileSection()
    upscale: list[str] = []
    comfyui_args: list[str] = []
    comfyui_args_cpu: list[str] = []
    notes: list[str] = Field(default_factory=list)


class Catalog:
    def __init__(self, configs_dir: Path) -> None:
        data = load_yaml(configs_dir / "models.yaml")
        self.models: dict[str, CatalogModel] = {}
        for entry in data.get("models", []):
            m = CatalogModel(**entry)
            if m.id in self.models:
                raise ValidationError(f"Duplicate model id in catalog: {m.id}")
            self.models[m.id] = m
        self.resolutions: dict[str, dict[str, list[int]]] = data.get("resolutions", {})
        prof = load_yaml(configs_dir / "hardware_profiles.yaml").get("profiles", {})
        self.profiles: dict[str, HardwareProfile] = {
            name: HardwareProfile(name=name, **cfg) for name, cfg in prof.items()
        }

    def get(self, model_id: str) -> CatalogModel:
        try:
            return self.models[model_id]
        except KeyError:
            raise NotFoundError(f"Unknown catalog model '{model_id}'", details={"known": sorted(self.models)}) from None

    def find(self, model_id_or_file: str) -> CatalogModel | None:
        if model_id_or_file in self.models:
            return self.models[model_id_or_file]
        matches = [m for m in self.models.values() if m.params.get("model") == model_id_or_file]
        # Prefer the plain variant (e.g. sd15 over sd15-lcm, which adds a LoRA) when matched by file name.
        matches.sort(key=lambda m: (bool(m.extra_loras), m.params.get("sampling") not in (None, "eps")))
        return matches[0] if matches else None

    def for_task(self, task: str) -> list[CatalogModel]:
        return [m for m in self.models.values() if task in m.tasks]

    def profile(self, name: str) -> HardwareProfile:
        return self.profiles[name]

    def resolution(self, family: str | None, aspect: str | None) -> tuple[int, int] | None:
        if not family or family not in self.resolutions:
            return None
        table = self.resolutions[family]
        if aspect and aspect in table:
            w, h = table[aspect]
            return int(w), int(h)
        if aspect:
            # closest aspect ratio
            try:
                a, b = (float(x) for x in aspect.split(":"))
                target = a / b
            except (ValueError, ZeroDivisionError):
                return None
            best = min(table.values(), key=lambda wh: abs(wh[0] / wh[1] - target))
            return int(best[0]), int(best[1])
        return None

    def hardware_fit(self, model: CatalogModel, vram_gb: float, ram_gb: float, cpu_only: bool) -> tuple[bool, str]:
        if cpu_only:
            if model.cpu_ok:
                return True, "CPU-Modus (langsam)"
            return False, "benötigt eine GPU"
        if vram_gb < model.min_vram_gb:
            return False, f"benötigt ≥ {model.min_vram_gb:g} GB VRAM (vorhanden: {vram_gb:g} GB)"
        if ram_gb and ram_gb + 0.5 < model.min_ram_gb:
            return True, f"läuft, aber {model.min_ram_gb:g} GB RAM empfohlen (vorhanden: {ram_gb:g} GB)"
        if vram_gb < model.rec_vram_gb:
            return True, f"läuft mit Offloading (empfohlen: {model.rec_vram_gb:g} GB VRAM)"
        return True, "passt"


@lru_cache(maxsize=4)
def load_catalog(configs_dir: str) -> Catalog:
    return Catalog(Path(configs_dir))


def frames_4n1(frames: int, max_frames: int | None = None) -> int:
    """Wan models need frame counts of the form 4n+1."""
    frames = max(1, int(frames))
    n = max(0, round((frames - 1) / 4))
    value = 4 * n + 1
    if max_frames:
        while value > max_frames:
            value -= 4
    return max(1, value)
