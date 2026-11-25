"""Central configuration.

Precedence (lowest → highest):
  1. Defaults defined in the pydantic models below
  2. ``configs/studio.yaml``            (committed defaults)
  3. ``configs/studio.local.yaml``      (git-ignored, written by the Settings UI)
  4. ``.env`` file in the project root  (git-ignored)
  5. Environment variables ``ACS__SECTION__KEY``

Secrets (API keys, tokens) are never read from YAML – only from the environment.
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(os.environ.get("ACS_ROOT", Path(__file__).resolve().parents[2])).resolve()
ENV_PREFIX = "ACS__"


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(8420, ge=1, le=65535)
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    max_upload_mb: int = Field(200, ge=1, le=4096)


class PathSettings(BaseModel):
    assets_dir: str = "assets"
    data_dir: str = "data"
    workflows_dir: str = "workflows"
    comfy_templates_dir: str = "engines/comfyui/workflows"
    comfyui_dir: str = "engines/comfyui/ComfyUI"
    blender_scripts_dir: str = "engines/blender/scripts"
    remotion_dir: str = "engines/remotion"
    # Additional directories the API/MCP may read from (e.g. a NAS folder with references).
    extra_allowed_dirs: list[str] = []


class ComfyUISettings(BaseModel):
    url: str = "http://127.0.0.1:8188"
    request_timeout_s: float = Field(30.0, gt=0)
    generation_timeout_s: float = Field(3600.0, gt=0)
    poll_interval_s: float = Field(1.0, gt=0)
    use_websocket: bool = True


class FFmpegSettings(BaseModel):
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    timeout_s: float = Field(1800.0, gt=0)
    default_crf: int = Field(20, ge=0, le=51)
    preset: str = "medium"
    video_codec: str = "libx264"
    audio_codec: str = "aac"


class BlenderSettings(BaseModel):
    blender_path: str = "blender"
    timeout_s: float = Field(3600.0, gt=0)


class RemotionSettings(BaseModel):
    npx_path: str = "npx"
    timeout_s: float = Field(1800.0, gt=0)


class JobSettings(BaseModel):
    gpu_concurrency: int = Field(1, ge=1, le=8)
    cpu_concurrency: int = Field(2, ge=1, le=32)
    workflow_concurrency: int = Field(2, ge=1, le=16)
    max_attempts: int = Field(2, ge=1, le=10)
    retry_backoff_s: float = Field(5.0, ge=0)
    default_timeout_s: float = Field(7200.0, gt=0)


class HardwareSettings(BaseModel):
    profile: Literal["auto", "low", "mid", "high"] = "auto"


class CostSettings(BaseModel):
    currency: str = "USD"
    # 0 means: no budget released → every paid action is blocked.
    monthly_budget: float = Field(0.0, ge=0)
    max_cost_per_job: float = Field(1.0, ge=0)
    confirmation_ttl_s: int = Field(600, ge=30, le=86400)


class QualitySettings(BaseModel):
    auto_check: bool = True
    min_sharpness: float = 40.0
    min_score: int = Field(60, ge=0, le=100)


class LoggingSettings(BaseModel):
    level: str = "INFO"
    max_bytes: int = 5_000_000
    backup_count: int = 5


class Settings(BaseModel):
    server: ServerSettings = ServerSettings()
    paths: PathSettings = PathSettings()
    comfyui: ComfyUISettings = ComfyUISettings()
    ffmpeg: FFmpegSettings = FFmpegSettings()
    blender: BlenderSettings = BlenderSettings()
    remotion: RemotionSettings = RemotionSettings()
    jobs: JobSettings = JobSettings()
    hardware: HardwareSettings = HardwareSettings()
    costs: CostSettings = CostSettings()
    quality: QualitySettings = QualitySettings()
    logging: LoggingSettings = LoggingSettings()

    # Not part of YAML – resolved at load time.
    project_root: Path = PROJECT_ROOT
    api_token: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    # ----- resolved paths -------------------------------------------------
    def resolve(self, value: str | Path) -> Path:
        p = Path(value).expanduser()
        return (p if p.is_absolute() else self.project_root / p).resolve()

    @property
    def assets_dir(self) -> Path:
        return self.resolve(self.paths.assets_dir)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.paths.data_dir)

    @property
    def configs_dir(self) -> Path:
        return self.project_root / "configs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.logs_dir,
            self.cache_dir,
            self.tmp_dir,
            self.data_dir / "reports",
            self.assets_dir,
            *(self.assets_dir / sub for sub in ("references", "generated", "images", "videos", "exports")),
        ):
            d.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict[str, Any]:
        """Settings without secrets – safe to show in UI / MCP."""
        data = self.model_dump(exclude={"api_token", "project_root"})
        data["project_root"] = str(self.project_root)
        data["api_token_set"] = bool(self.api_token)
        return data


# ----------------------------------------------------------------------------
# Loading helpers
# ----------------------------------------------------------------------------

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def parse_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser (KEY=VALUE, comments, optional quotes). No variable expansion."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _coerce(value: str) -> Any:
    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return value


def env_overrides(environ: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        parts = [p.lower() for p in key[len(ENV_PREFIX):].split("__") if p]
        if not parts:
            continue
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = _coerce(value)
    return out


def load_settings(root: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    root = (root or PROJECT_ROOT).resolve()
    env = dict(parse_dotenv(root / ".env"))
    env.update(environ if environ is not None else os.environ)

    data: dict[str, Any] = {}
    data = deep_merge(data, load_yaml(root / "configs" / "studio.yaml"))
    data = deep_merge(data, load_yaml(root / "configs" / "studio.local.yaml"))
    data = deep_merge(data, env_overrides(env))
    # Secrets are never accepted from YAML.
    data.pop("api_token", None)
    data.pop("project_root", None)

    settings = Settings(**data)
    settings.project_root = root
    settings.api_token = env.get("ACS_API_TOKEN") or None
    return settings


def save_local_overrides(settings_root: Path, updates: dict[str, Any]) -> Path:
    """Merge ``updates`` into configs/studio.local.yaml (never touches studio.yaml)."""
    path = settings_root / "configs" / "studio.local.yaml"
    current = load_yaml(path)
    merged = deep_merge(current, updates)
    # Validate before writing.
    Settings(**deep_merge(load_yaml(settings_root / "configs" / "studio.yaml"), merged))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(merged, fh, sort_keys=False, allow_unicode=True)
    return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
