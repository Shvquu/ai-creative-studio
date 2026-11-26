"""Live engine tests – skipped automatically when the engine is not available.

* Blender:  needs `blender` on PATH                                    (marker: blender)
* Remotion: needs engines/remotion/node_modules (npm install)          (marker: remotion)
* ComfyUI:  needs ACS_TEST_COMFYUI_URL pointing at a running ComfyUI   (marker: live_comfyui)
* Models:   additionally needs sd15-lcm (+ realesrgan-x4) installed    (marker: live_models)

Run all live tests:  ACS_TEST_COMFYUI_URL=http://127.0.0.1:8188 pytest -m "blender or remotion or live_comfyui or live_models"
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from tests.conftest import HAS_BLENDER, HAS_FFMPEG, HAS_REMOTION, write_test_image

COMFY_URL = os.environ.get("ACS_TEST_COMFYUI_URL")


def _comfy_up() -> bool:
    if not COMFY_URL:
        return False
    try:
        return httpx.get(f"{COMFY_URL}/system_stats", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


COMFY_UP = _comfy_up()


async def _run(studio: Any, job_type: str, params: dict[str, Any], timeout: float = 600) -> dict[str, Any]:
    job = await studio.submit(job_type, params)
    done = await studio.queue.wait(job.id, timeout=timeout)
    assert done.status.value == "succeeded", done.error
    return done.result


@pytest.mark.blender
@pytest.mark.skipif(not (HAS_BLENDER and HAS_FFMPEG), reason="blender/ffmpeg not installed")
async def test_blender_turntable_and_svg_logo(studio: Any) -> None:
    r = await _run(studio, "render3d.render", {"template": "product_turntable", "params": {"product": "can", "color": "#DC2626"},
                                               "width": 320, "height": 180, "frames": 4, "samples": 4, "fps": 12})
    video = r["assets"][0]
    assert video["kind"] == "video" and video["width"] == 320 and video["duration_s"] == pytest.approx(4 / 12, abs=0.1)
    svg = studio.settings.assets_dir / "references" / "logo.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" '
                   'fill="#1D4ED8"/><rect x="30" y="30" width="40" height="40" fill="#FFFFFF"/></svg>')
    r = await _run(studio, "render3d.render", {"template": "logo_extrude", "params": {"svg_path": "references/logo.svg"},
                                               "width": 320, "height": 180, "samples": 4, "output": "still"})
    assert r["assets"][0]["kind"] == "image" and r["quality"][0]["passed"]


@pytest.mark.blender
@pytest.mark.skipif(not HAS_BLENDER, reason="blender not installed")
async def test_blender_rejects_unknown_params(studio: Any) -> None:
    job = await studio.submit("render3d.render", {"template": "text_3d", "params": {"evil": 1}})
    done = await studio.queue.wait(job.id, timeout=30)
    assert done.error["code"] == "validation_error"


@pytest.mark.remotion
@pytest.mark.skipif(not (HAS_REMOTION and HAS_FFMPEG), reason="Remotion not installed (cd engines/remotion && npm install)")
async def test_remotion_compositions(studio: Any) -> None:
    logo = write_test_image(studio.settings.assets_dir / "references" / "logo.png", (256, 256))
    r = await _run(studio, "motion.render", {"composition": "TitleIntro", "width": 320, "height": 180, "duration_s": 1,
                                             "props": {"title": "Hallo", "subtitle": "Test", "logo": str(logo)}})
    v = r["assets"][0]
    assert v["kind"] == "video" and (v["width"], v["height"]) == (320, 180) and v["duration_s"] == pytest.approx(1, abs=0.1)
    r = await _run(studio, "motion.render", {"composition": "KineticText", "width": 180, "height": 320, "duration_s": 1,
                                             "props": {"phrases": ["Eins", "Zwei"]}})
    assert r["assets"][0]["height"] == 320
    job = await studio.submit("motion.render", {"composition": "SocialPost", "props": {}})  # headline missing
    done = await studio.queue.wait(job.id, timeout=60)
    assert done.error["code"] == "validation_error"


@pytest.mark.live_comfyui
@pytest.mark.skipif(not COMFY_UP, reason="set ACS_TEST_COMFYUI_URL to a running ComfyUI")
async def test_comfyui_live_smoke_and_templates(studio: Any) -> None:
    studio.settings.comfyui.url = COMFY_URL
    prov = studio.registry.get("image", "comfyui")
    prov.client.base_url = COMFY_URL.rstrip("/")
    prov.client._http = None
    r = await _run(studio, "system.smoke_test", {}, timeout=120)
    kinds = sorted(a["kind"] for a in r["assets"])
    assert kinds == ["image", "video"]
    info = await prov.client.object_info()
    for tpl in prov.templates.list():
        assert tpl.validate_object_info(info) == [], tpl.id


@pytest.mark.live_comfyui
@pytest.mark.skipif(not COMFY_UP, reason="set ACS_TEST_COMFYUI_URL to a running ComfyUI")
async def test_comfyui_live_cancel(studio: Any) -> None:
    """Cancel a running ComfyUI job: the queue entry is deleted / execution interrupted."""
    studio.settings.comfyui.url = COMFY_URL
    prov = studio.registry.get("image", "comfyui")
    prov.client.base_url = COMFY_URL.rstrip("/")
    prov.client._http = None
    installed = await prov.installed()
    if "v1-5-pruned-emaonly-fp16.safetensors" not in installed.get("checkpoints", set()):
        pytest.skip("needs sd15 checkpoint for a long-running job")
    job = await studio.submit("image.generate", {"prompt": "cancel me", "model": "sd15", "steps": 40, "width": 512, "height": 512})
    import asyncio

    for _ in range(100):
        if studio.queue.get(job.id).status.value == "running":
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(2)
    cancelled = await studio.queue.cancel(job.id)
    assert cancelled.status.value == "cancelled"
    q = (await prov.client.queue())
    assert not q.get("queue_running") or all(item[1] != prov.client for item in q["queue_running"])


@pytest.mark.live_models
@pytest.mark.skipif(not COMFY_UP, reason="set ACS_TEST_COMFYUI_URL to a running ComfyUI")
async def test_real_generation_sd15_lcm_and_esrgan(studio: Any) -> None:
    studio.settings.comfyui.url = COMFY_URL
    prov = studio.registry.get("image", "comfyui")
    prov.client.base_url = COMFY_URL.rstrip("/")
    prov.client._http = None
    installed = await prov.installed()
    if "lcm-lora-sdv1-5.safetensors" not in installed.get("loras", set()):
        pytest.skip("sd15-lcm not installed (scripts/models/download_models.py --model sd15-lcm)")
    r = await _run(studio, "image.generate", {"prompt": "a red apple on a wooden table, studio light", "seed": 7,
                                              "width": 384, "height": 384}, timeout=900)
    a = r["assets"][0]
    assert r["model"] == "sd15-lcm" and (a["width"], a["height"]) == (384, 384) and r["quality"][0]["passed"]
    side = studio.assets.read_sidecar(studio.assets.get(a["id"]))
    assert side["workflow"]["12"]["inputs"]["sampling"] == "lcm"  # exact workflow stored for reproducibility
    if "RealESRGAN_x4plus.safetensors" in installed.get("upscale_models", set()):
        up = await _run(studio, "image.upscale", {"source": a["id"], "scale": 2}, timeout=900)
        assert up["model"] == "realesrgan-x4" and up["assets"][0]["width"] == 768
