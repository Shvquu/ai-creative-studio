"""Provider interfaces.

Every generator/processor is accessed through one of these abstract classes.
New providers implement the relevant interface and are registered in
``configs/providers.yaml`` – nothing else in the system needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.errors import CapabilityNotSupportedError
from backend.jobs.context import JobContext

# ----------------------------------------------------------------------------
# Capabilities & info
# ----------------------------------------------------------------------------


class Capability(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    INPAINT = "inpaint"
    OUTPAINT = "outpaint"
    UPSCALE = "upscale"
    REMOVE_BACKGROUND = "remove_background"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    VIDEO_UPSCALE = "video_upscale"
    FRAME_INTERPOLATION = "frame_interpolation"
    # processing
    MEDIA_INFO = "media_info"
    CONVERT = "convert"
    RENDER = "render"
    EXTRACT_FRAMES = "extract_frames"
    ADD_AUDIO = "add_audio"
    ADD_SUBTITLES = "add_subtitles"
    MERGE = "merge"
    TRIM = "trim"
    RESIZE = "resize"
    COMPRESS = "compress"
    # image tools
    TEXT_OVERLAY = "text_overlay"
    PALETTE = "palette"
    # motion / 3D
    MOTION_RENDER = "motion_render"
    RENDER_3D = "render_3d"


class ProviderInfo(BaseModel):
    name: str
    display_name: str
    description: str = ""
    location: Literal["local", "cloud"] = "local"
    cost_model: str = "free"  # free | per_image | per_second | per_request
    unit_cost: float = 0.0
    currency: str = "USD"
    requires_api_key: bool = False
    api_key_env: str | None = None
    enabled: bool = True
    explicit_only: bool = False
    license_note: str | None = None
    roles: list[str] = []

    @property
    def is_free(self) -> bool:
        return self.location == "local" and self.cost_model == "free"


class ProviderHealth(BaseModel):
    available: bool
    detail: str = ""
    version: str | None = None
    extra: dict[str, Any] = {}


class ModelInfo(BaseModel):
    id: str
    name: str
    type: str  # image | video | upscale | lora | other
    provider: str
    installed: bool = True
    catalog_id: str | None = None
    family: str | None = None
    tasks: list[str] = []
    license: str | None = None
    commercial_use: bool | str | None = None
    fits_hardware: bool | None = None
    hardware_note: str | None = None
    size_gb: float | None = None
    missing_files: list[str] = []


# ----------------------------------------------------------------------------
# Requests
# ----------------------------------------------------------------------------

_SEED_MAX = 2**53 - 1  # JSON-safe integer range


class LoraSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    strength: float = Field(1.0, ge=-5, le=5)


class _Common(BaseModel):
    project: str | None = Field(None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=50)


class ImageGenerateRequest(_Common):
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = Field("", max_length=4000)
    model: str | None = Field(None, description="Catalog id (e.g. 'sdxl') or model file name; None = automatic")
    template: str | None = Field(None, description="Override ComfyUI template id")
    width: int | None = Field(None, ge=64, le=4096)
    height: int | None = Field(None, ge=64, le=4096)
    aspect_ratio: str | None = Field(None, pattern=r"^\d{1,2}:\d{1,2}$")
    steps: int | None = Field(None, ge=1, le=150)
    cfg: float | None = Field(None, ge=0, le=30)
    seed: int | None = Field(None, ge=0, le=_SEED_MAX)
    sampler: str | None = Field(None, max_length=64)
    scheduler: str | None = Field(None, max_length=64)
    batch_size: int = Field(1, ge=1, le=8)
    loras: list[LoraSpec] = Field(default_factory=list, max_length=8)
    style: str | None = Field(None, max_length=64)
    control_image: str | None = Field(None, description="ControlNet: Steuerbild (Foto für Canny-Kanten oder Skizze)")
    control_mode: Literal["canny", "none"] = Field("canny", description="canny = Kanten aus Foto, none = Bild direkt (Scribble)")
    control_strength: float = Field(0.8, ge=0, le=2)
    controlnet: str | None = Field(None, description="ControlNet-Katalog-ID oder Datei; leer = passend zu control_mode")


class ImageEditRequest(_Common):
    source: str = Field(description="Asset id or path inside the assets directory")
    prompt: str = Field("", max_length=4000)
    negative_prompt: str = Field("", max_length=4000)
    strength: float = Field(0.6, ge=0.05, le=1.0, description="Denoise strength (how much changes)")
    model: str | None = None
    steps: int | None = Field(None, ge=1, le=150)
    cfg: float | None = Field(None, ge=0, le=30)
    seed: int | None = Field(None, ge=0, le=_SEED_MAX)


class InpaintRequest(ImageEditRequest):
    mask: str | None = Field(None, description="Mask image (white = repaint). None: use source alpha channel")
    grow_mask_by: int = Field(8, ge=0, le=64)
    strength: float = Field(1.0, ge=0.05, le=1.0)


class OutpaintRequest(ImageEditRequest):
    left: int = Field(0, ge=0, le=2048)
    top: int = Field(0, ge=0, le=2048)
    right: int = Field(0, ge=0, le=2048)
    bottom: int = Field(0, ge=0, le=2048)
    feathering: int = Field(40, ge=0, le=512)
    strength: float = Field(1.0, ge=0.05, le=1.0)


class UpscaleRequest(_Common):
    source: str
    scale: float = Field(2.0, ge=1.0, le=8.0)
    model: str | None = Field(None, description="Upscale model (e.g. 'realesrgan-x4'); None = best available")
    method: Literal["auto", "model", "lanczos"] = "auto"


class RemoveBackgroundRequest(_Common):
    source: str
    model: str = Field("u2net", max_length=64)
    alpha_matting: bool = False


class VideoGenerateRequest(_Common):
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = Field("", max_length=4000)
    model: str | None = None
    template: str | None = None
    image: str | None = Field(None, description="Start image (asset id/path) for image-to-video")
    width: int | None = Field(None, ge=64, le=2048)
    height: int | None = Field(None, ge=64, le=2048)
    aspect_ratio: str | None = Field(None, pattern=r"^\d{1,2}:\d{1,2}$")
    frames: int | None = Field(None, ge=1, le=241)
    duration_s: float | None = Field(None, gt=0, le=15)
    fps: int | None = Field(None, ge=1, le=60)
    steps: int | None = Field(None, ge=1, le=100)
    cfg: float | None = Field(None, ge=0, le=30)
    seed: int | None = Field(None, ge=0, le=_SEED_MAX)
    camera: str | None = Field(None, max_length=200, description="Camera movement hint appended to prompt")


class VideoUpscaleRequest(_Common):
    source: str
    scale: float = Field(2.0, ge=1.0, le=4.0)
    model: str | None = Field(None, description="Upscale-Modell (Katalog-ID), leer = bestes installiertes")
    method: Literal["auto", "model", "lanczos"] = "auto"


# ----------------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------------


class GenerationResult(BaseModel):
    files: list[Path]
    provider: str
    model: str | None = None
    seed: int | None = None
    parameters: dict[str, Any] = {}
    workflow: dict[str, Any] | None = None  # exact engine workflow for reproducibility
    metadata: dict[str, Any] = {}

    model_config = {"arbitrary_types_allowed": True}


# ----------------------------------------------------------------------------
# Interfaces
# ----------------------------------------------------------------------------


class BaseProvider(ABC):
    role: str = ""

    def __init__(self, info: ProviderInfo, settings: Any, shared: dict[str, Any] | None = None) -> None:
        self.info = info
        self.name = info.name
        self.settings = settings
        self.shared = shared if shared is not None else {}

    @abstractmethod
    def get_capabilities(self) -> set[Capability]: ...

    async def get_models(self) -> list[ModelInfo]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None

    def supports(self, capability: Capability) -> bool:
        return capability in self.get_capabilities()

    def _unsupported(self, capability: Capability) -> CapabilityNotSupportedError:
        return CapabilityNotSupportedError(
            f"Provider '{self.name}' does not support '{capability.value}'",
            details={"provider": self.name, "capability": capability.value},
        )


class ImageProvider(BaseProvider):
    role = "image"

    async def generate(self, req: ImageGenerateRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.TEXT_TO_IMAGE)

    async def edit(self, req: ImageEditRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.IMAGE_TO_IMAGE)

    async def inpaint(self, req: InpaintRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.INPAINT)

    async def outpaint(self, req: OutpaintRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.OUTPAINT)

    async def upscale(self, req: UpscaleRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.UPSCALE)

    async def remove_background(self, req: RemoveBackgroundRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.REMOVE_BACKGROUND)


class VideoProvider(BaseProvider):
    role = "video"

    async def generate(self, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.TEXT_TO_VIDEO)

    async def image_to_video(self, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.IMAGE_TO_VIDEO)

    async def process(self, req: dict[str, Any], ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.VIDEO_TO_VIDEO)

    async def upscale(self, req: VideoUpscaleRequest, ctx: JobContext) -> GenerationResult:
        raise self._unsupported(Capability.VIDEO_UPSCALE)


class ProcessingProvider(BaseProvider):
    """Media processing (FFmpeg). Request models live in backend/providers/ffmpeg.py."""

    role = "processing"

    @abstractmethod
    async def get_info(self, path: Path) -> Any: ...

    @abstractmethod
    async def convert(self, req: Any, ctx: JobContext) -> GenerationResult: ...

    @abstractmethod
    async def render(self, req: Any, ctx: JobContext) -> GenerationResult: ...

    @abstractmethod
    async def extract_frames(self, req: Any, ctx: JobContext) -> GenerationResult: ...

    @abstractmethod
    async def add_audio(self, req: Any, ctx: JobContext) -> GenerationResult: ...

    @abstractmethod
    async def add_subtitles(self, req: Any, ctx: JobContext) -> GenerationResult: ...


class MotionProvider(BaseProvider):
    role = "motion"

    @abstractmethod
    async def get_compositions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def render(self, req: Any, ctx: JobContext) -> GenerationResult: ...


class Render3DProvider(BaseProvider):
    role = "render3d"

    @abstractmethod
    async def get_templates(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def render(self, req: Any, ctx: JobContext) -> GenerationResult: ...


ROLE_INTERFACES: dict[str, type[BaseProvider]] = {
    "image": ImageProvider,
    "video": VideoProvider,
    "processing": ProcessingProvider,
    "motion": MotionProvider,
    "render3d": Render3DProvider,
}
