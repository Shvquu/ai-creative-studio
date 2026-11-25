"""Shared fixtures.

Tests never touch the real repository data: every Studio instance gets a temporary
project root (copy of configs/) with absolute paths to the real templates/workflows,
and ComfyUI is pointed at an unreachable port unless a live test opts in.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from backend.core.config import Settings, load_settings
from backend.core.hardware import HardwareReport, ProfileDecision

REPO = Path(__file__).resolve().parents[1]
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
HAS_BLENDER = shutil.which("blender") is not None
HAS_REMOTION = (REPO / "engines" / "remotion" / "node_modules" / "@remotion" / "cli").is_dir() and shutil.which("npx")

needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def make_settings(tmp_path: Path) -> Settings:
    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    for f in ("studio.yaml", "providers.yaml", "models.yaml", "hardware_profiles.yaml"):
        shutil.copy(REPO / "configs" / f, root / "configs" / f)
    s = load_settings(root, environ={})
    s.paths.assets_dir = str(tmp_path / "assets")
    s.paths.data_dir = str(tmp_path / "data")
    s.paths.workflows_dir = str(REPO / "workflows")
    s.paths.comfy_templates_dir = str(REPO / "engines" / "comfyui" / "workflows")
    s.paths.blender_scripts_dir = str(REPO / "engines" / "blender" / "scripts")
    s.paths.remotion_dir = str(REPO / "engines" / "remotion")
    s.comfyui.url = "http://127.0.0.1:9"  # unreachable unless a test overrides it
    s.comfyui.request_timeout_s = 2
    s.jobs.retry_backoff_s = 0.05
    s.ensure_dirs()
    return s


def fake_hardware(profile: str = "low", vram: float = 0.0, ram: float = 16.0, accel: str = "none") -> tuple[HardwareReport, ProfileDecision]:
    report = HardwareReport(
        os="Linux", os_version="test", architecture="x86_64", cpu_model="Test CPU", cpu_cores_physical=4,
        cpu_cores_logical=8, ram_total_gb=ram, ram_available_gb=ram / 2, disk_free_gb=100, disk_total_gb=500,
        python_version="3.12",
    )
    decision = ProfileDecision(profile=profile, reason="test", accelerator=accel, effective_vram_gb=vram,
                               cpu_only=accel == "none")
    return report, decision


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
async def studio(settings: Settings) -> AsyncIterator:
    from backend.orchestration.studio import Studio

    s = Studio(settings, configure_logging=False)
    s.set_hardware(*fake_hardware())
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
async def api(studio) -> AsyncIterator[httpx.AsyncClient]:
    from backend.api.app import create_app

    app = create_app(studio, start_queue=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def write_test_image(path: Path, size: tuple[int, int] = (640, 480), sharp: bool = True) -> Path:
    from PIL import Image, ImageDraw, ImageFilter

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, (90, 120, 160))
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 16):
        d.line([(i, 0), (size[0] - i, size[1])], fill=(240, 240, 240), width=2)
    d.rectangle([size[0] // 4, size[1] // 4, size[0] // 2, size[1] // 2], fill=(200, 60, 40))
    if not sharp:
        img = img.filter(ImageFilter.GaussianBlur(12))
    img.save(path)
    return path


def write_test_video(path: Path, seconds: float = 2.0, size: str = "320x240", audio: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True)
    return path
