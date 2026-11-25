"""Studio operations, model selection, workflows and FFmpeg pipelines (real FFmpeg, mock generator)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.core.catalog import Catalog
from backend.core.errors import HardwareInsufficientError, ModelNotInstalledError, ValidationError
from backend.orchestration.prompts import build_prompt
from backend.orchestration.selector import ModelSelector
from tests.conftest import REPO, fake_hardware, needs_ffmpeg, write_test_image, write_test_video

pytestmark = needs_ffmpeg


async def run(studio: Any, job_type: str, params: dict[str, Any], timeout: float = 120) -> Any:
    job = await studio.submit(job_type, params)
    done = await studio.queue.wait(job.id, timeout=timeout)
    assert done.status.value == "succeeded", done.error
    return done.result


# ------------------------------------------------------------------ selection
def test_selector_rules() -> None:
    catalog = Catalog(REPO / "configs")
    sel = ModelSelector(catalog)
    _, low = fake_hardware("low")
    installed = {"checkpoints": {"v1-5-pruned-emaonly-fp16.safetensors"}, "loras": {"lcm-lora-sdv1-5.safetensors"}}
    assert sel.choose("text_to_image", low, 16, installed).model.id == "sd15-lcm"
    with pytest.raises(ModelNotInstalledError) as exc:
        sel.choose("text_to_image", low, 16, {})
    assert exc.value.details["recommended"]["id"] == "sd15-lcm"
    with pytest.raises(HardwareInsufficientError):
        sel.choose("text_to_video", low, 16, {"diffusion_models": {"wan2.1_t2v_1.3B_fp16.safetensors"}})
    _, high = fake_hardware("high", vram=24, ram=64, accel="cuda")
    rec = sel.recommended(high, 64)
    assert rec["text_to_image"][0]["id"] == "z-image-turbo" and rec["image_to_video"][0]["id"] == "wan22-i2v-14b"
    _, mid = fake_hardware("mid", vram=12, ram=32, accel="cuda")
    assert sel.recommended(mid, 32)["text_to_video"][0]["id"] == "wan22-ti2v-5b"


def test_build_prompt_family_rules() -> None:
    sd = build_prompt("a fox", style="product", family="sd15", negative="ugly")
    assert "product photography" in sd["prompt"] and sd["negative_prompt"].startswith("ugly") and "lowres" in sd["negative_prompt"]
    flux = build_prompt("a fox", style="cinematic", family="flux2", supports_negative=False)
    assert flux["negative_prompt"] == ""
    with pytest.raises(ValueError):
        build_prompt("x", style="nope")


# --------------------------------------------------------------- operations
async def test_generate_with_mock_registers_assets_and_qa(studio: Any) -> None:
    result = await run(studio, "image.generate", {"prompt": "a lighthouse", "provider": "mock", "batch_size": 2,
                                                  "aspect_ratio": "16:9", "style": "cinematic", "project": "Test"})
    assert len(result["asset_ids"]) == 2 and result["quality"][0]["score"] > 0
    asset = studio.assets.get(result["asset_ids"][0])
    assert "cinematic" in asset.prompt and asset.project == "Test" and asset.width > asset.height


async def test_comfyui_unreachable_is_retried_then_fails(studio: Any) -> None:
    job = await studio.submit("image.generate", {"prompt": "x"})
    done = await studio.queue.wait(job.id, timeout=30)
    assert done.status.value == "failed" and done.error["code"] == "provider_unavailable" and done.attempts == 2


async def test_video_on_cpu_suggests_fallback(studio: Any) -> None:
    job = await studio.submit("video.generate", {"prompt": "x"})
    done = await studio.queue.wait(job.id, timeout=10)
    assert done.error["code"] == "hardware_insufficient"
    assert done.error["details"]["fallback_workflow"] == "videos/kenburns-slideshow"


async def test_upscale_falls_back_to_lanczos(studio: Any) -> None:
    write_test_image(studio.settings.assets_dir / "references" / "small.png", (200, 100))
    await studio.assets.rescan()
    result = await run(studio, "image.upscale", {"source": "references/small.png", "scale": 2})
    assert result["fallback"] == "lanczos" and result["assets"][0]["width"] == 400


async def test_validation_and_path_errors(studio: Any) -> None:
    with pytest.raises(ValidationError):
        await studio.submit("image.generate", {"prompt": ""})
    with pytest.raises(ValidationError):
        await studio.submit("process.merge", {"sources": ["only-one.mp4"]})
    job = await studio.submit("process.convert", {"source": "../../etc/passwd"})
    done = await studio.queue.wait(job.id, timeout=10)
    assert done.error["code"] == "path_not_allowed"


async def test_image_tools(studio: Any) -> None:
    src = write_test_image(studio.settings.assets_dir / "references" / "photo.png", (1600, 1000))
    r = await run(studio, "image.resize", {"source": str(src), "format_preset": "instagram_story", "mode": "blur"})
    assert (r["assets"][0]["width"], r["assets"][0]["height"]) == (1080, 1920)
    r = await run(studio, "image.text_overlay", {"source": r["asset_ids"][0], "title": "Großer Titel", "subtitle": "Untertitel"})
    assert r["assets"][0]["kind"] == "image"
    r = await run(studio, "image.palette", {"base_color": "#2563EB", "harmony": "triadic", "count": 5})
    assert len(r["colors"]) == 5 and all("wcag_aa_text" in c for c in r["colors"])
    r = await run(studio, "image.palette", {"source": str(src), "count": 4})
    assert len(r["colors"]) == 4
    r = await run(studio, "image.contact_sheet", {"sources": [str(src), str(src)], "labels": ["a", "b"]})
    assert r["assets"][0]["kind"] == "image"


async def test_ffmpeg_pipeline(studio: Any) -> None:
    refs = studio.settings.assets_dir / "references"
    imgs = [write_test_image(refs / f"s{i}.png", (800, 600)) for i in range(2)]
    vid = write_test_video(refs / "clip.mp4", 2.0)
    music = write_test_video(refs / "music.mp4", 8.0)  # has audio track
    r = await run(studio, "process.render", {
        "clips": [{"source": str(imgs[0]), "duration_s": 2, "ken_burns": {"zoom": "in"}},
                  {"source": str(vid)},
                  {"source": str(imgs[1]), "duration_s": 2, "ken_burns": {"zoom": "out", "pan": "left"}}],
        "width": 640, "height": 360, "fps": 24, "transition": "dissolve", "transition_duration": 0.5,
        "audio": {"source": str(music), "fade_out_s": 1}, "subtitles": [{"start_s": 0.2, "end_s": 1.5, "text": "Hallo"}],
        "output_name": "final_cut"})
    out = r["assets"][0]
    assert out["path"].endswith("final_cut.mp4") and out["width"] == 640 and out["duration_s"] == pytest.approx(5.0, abs=0.2)
    assert r["quality"][0]["passed"]
    info = await studio.ffmpeg.get_info(studio.resolve_input(out["id"]))
    assert info.has_audio and info.video_codec == "h264"
    r2 = await run(studio, "process.resize", {"source": out["id"], "aspect_ratio": "9:16", "mode": "blur"})
    assert r2["assets"][0]["height"] > r2["assets"][0]["width"]
    r3 = await run(studio, "process.extract_frames", {"source": out["id"], "count": 3})
    assert len(r3["asset_ids"]) == 3
    r4 = await run(studio, "process.merge", {"sources": [str(vid), str(vid)], "transition": "fade"})
    assert r4["assets"][0]["duration_s"] == pytest.approx(3.5, abs=0.2)
    r5 = await run(studio, "process.title_card", {"title": "Ende", "duration_s": 1.5, "width": 320, "height": 180})
    assert r5["assets"][0]["duration_s"] == pytest.approx(1.5, abs=0.1)
    r6 = await run(studio, "process.add_subtitles", {"video": str(vid), "subtitles": [{"start_s": 0, "end_s": 1, "text": "x"}],
                                                     "burn_in": False})
    assert r6["assets"][0]["kind"] == "video"


# --------------------------------------------------------------- workflows
def test_all_workflows_load_and_reference_known_actions(studio: Any) -> None:
    ids = set(studio.workflows.specs)
    assert {"images/text-to-image", "videos/storyboard-to-video", "videos/kenburns-slideshow", "branding/brand-kit",
            "social-media/youtube-thumbnail", "motion-design/title-intro"} <= ids
    for spec in studio.workflows.specs.values():
        if spec.fallback:
            assert spec.fallback in ids


def test_input_coercion(studio: Any) -> None:
    spec = studio.workflows.get("images/text-to-image")
    with pytest.raises(ValidationError):
        studio.workflows.coerce_inputs(spec, {})
    with pytest.raises(ValidationError):
        studio.workflows.coerce_inputs(spec, {"prompt": "x", "variants": 9})
    with pytest.raises(ValidationError):
        studio.workflows.coerce_inputs(spec, {"prompt": "x", "unknown": 1})
    out = studio.workflows.coerce_inputs(spec, {"prompt": "x", "variants": "3", "upscale": "ja"})
    assert out["variants"] == 3 and out["upscale"] is True and out["style"] == "photorealistic"


async def test_workflow_text_to_image_with_upscale(studio: Any) -> None:
    r = await run(studio, "workflow.run", {"workflow_id": "images/text-to-image", "inputs": {
        "prompt": "mountain lake", "variants": 2, "upscale": True, "image_provider": "mock"}})
    assert len(r["outputs"]["images"]) == 2 and r["outputs"]["quality_passed"] is True
    assert [e["status"] for e in r["log"]] == ["done", "done", "done"]


async def test_storyboard_falls_back_to_kenburns_on_cpu(studio: Any) -> None:
    r = await run(studio, "workflow.run", {"workflow_id": "videos/storyboard-to-video", "inputs": {
        "scenes": [{"prompt": "dawn", "duration_s": 1.5, "caption": "Morgen"}, {"prompt": "dusk", "duration_s": 1.5}],
        "image_provider": "mock", "title": "Mein Film"}}, timeout=240)
    assert r["fallback_used"]["to"] == "videos/kenburns-slideshow"
    video = studio.assets.get(r["outputs"]["video"])
    assert video.kind == "video" and video.path.endswith("mein-film.mp4") and video.duration_s > 2


async def test_brand_kit_workflow(studio: Any) -> None:
    r = await run(studio, "workflow.run", {"workflow_id": "branding/brand-kit", "inputs": {
        "brand_name": "Testmarke", "industry": "bakery", "tagline": "Frisch.", "brand_values": ["warm"],
        "logo_concepts": 2, "imagery_prompt": "fresh bread", "image_provider": "mock"}}, timeout=240)
    assert len(r["outputs"]["palette"]) == 5 and len(r["outputs"]["logos"]) == 2 and r["outputs"]["social_post"]
    html = studio.settings.assets_dir / "exports" / "brand" / "testmarke" / "brand-guidelines.html"
    text = html.read_text(encoding="utf-8")
    assert "Testmarke" in text and "data:image/png;base64" in text


async def test_workflow_step_error_names_step(studio: Any) -> None:
    job = await studio.submit("workflow.run", {"workflow_id": "images/text-to-image", "inputs": {"prompt": "x"}})
    done = await studio.queue.wait(job.id, timeout=60)  # default provider comfyui is unreachable in tests
    assert done.status.value == "failed" and "generate" in done.error["message"] or "Bilder generieren" in done.error["message"]


def test_workflow_templating(studio: Any) -> None:
    eng = studio.workflows
    ctx = {"inputs": {"a": [1, 2], "name": "X"}, "steps": {}}
    assert eng.render_value("{{ inputs.a }}", ctx) == [1, 2]
    assert eng.render_value("Hallo {{ inputs.name }}, {{ inputs.a | length }}", ctx) == "Hallo X, 2"
    assert eng.render_value({"k": ["{{ inputs.missing }}"]}, ctx) == {"k": [None]}
    with pytest.raises(Exception):  # sandbox: no access to python internals
        eng.render_value("{{ inputs.__class__.__mro__ }}", ctx)


def _unused(path: Path) -> None:  # pragma: no cover - keep imports explicit
    _ = path
