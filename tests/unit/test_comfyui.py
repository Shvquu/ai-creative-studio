"""ComfyUI templates and client (HTTP mocked with httpx.MockTransport)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.core.errors import (
    GenerationError,
    ModelNotInstalledError,
    ProviderUnavailableError,
    ValidationError,
)
from backend.jobs.context import JobContext
from backend.providers.comfyui.client import ComfyUIClient
from backend.providers.comfyui.templates import TemplateLibrary, insert_loras, render

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = TemplateLibrary(REPO / "engines" / "comfyui" / "workflows")
OBJECT_INFO = json.loads((REPO / "tests" / "fixtures" / "comfyui_object_info_0.46.0.json").read_text())


@pytest.mark.parametrize("template_id", sorted(TEMPLATES.templates))
def test_template_valid_against_comfyui_0_46(template_id: str) -> None:
    tpl = TEMPLATES.get(template_id)
    assert tpl.structural_errors() == []
    assert tpl.validate_object_info(OBJECT_INFO) == [], "template no longer matches ComfyUI node definitions"


def test_render_sets_all_targets() -> None:
    tpl = TEMPLATES.get("flux2_klein_txt2img")
    wf = render(tpl, {"prompt": "a cat", "width": 768, "height": 512, "seed": 7})
    assert wf["4"]["inputs"]["text"] == "a cat"
    assert wf["8"]["inputs"]["width"] == 768 and wf["10"]["inputs"]["width"] == 768  # multi-target
    assert wf["9"]["inputs"]["noise_seed"] == 7
    assert tpl.workflow["4"]["inputs"]["text"] == ""  # template untouched


def test_render_rejects_unknown_and_missing_required() -> None:
    tpl = TEMPLATES.get("checkpoint_txt2img")
    with pytest.raises(ValidationError):
        render(tpl, {"prompt": "x", "model": "m", "bogus": 1})
    with pytest.raises(ValidationError):
        render(tpl, {"model": "m"})


def test_insert_loras_rewires_consumers() -> None:
    tpl = TEMPLATES.get("checkpoint_txt2img")
    wf = render(tpl, {"prompt": "x", "model": "m.safetensors"})
    wf = insert_loras(wf, tpl.meta.lora_anchor, [{"name": "a.safetensors", "strength": 0.8}, {"name": "b.safetensors"}])
    loras = {k: v for k, v in wf.items() if v["class_type"] == "LoraLoader"}
    assert len(loras) == 2
    first, second = sorted(loras, key=int)
    assert wf[first]["inputs"]["model"] == ["4", 0] and wf[second]["inputs"]["model"] == [first, 0]
    assert wf["12"]["inputs"]["model"] == [second, 0]  # ModelSamplingDiscrete now after the chain
    assert wf["6"]["inputs"]["clip"] == [second, 1] and wf["7"]["inputs"]["clip"] == [second, 1]


def test_lora_on_template_without_anchor_fails() -> None:
    tpl = TEMPLATES.get("z_image_turbo_txt2img")
    with pytest.raises(ValidationError):
        insert_loras(render(tpl, {"prompt": "x"}), tpl.meta.lora_anchor, [{"name": "l"}])


# ------------------------------------------------------------------ client
class FakeComfy:
    """Minimal fake of the ComfyUI HTTP API (no websocket → client polls)."""

    def __init__(self, *, prompt_status: int = 200, prompt_body: dict[str, Any] | None = None,
                 history_status: str = "success", messages: list[Any] | None = None) -> None:
        self.prompt_status = prompt_status
        self.prompt_body = prompt_body
        self.history_status = history_status
        self.messages = messages or []
        self.submitted: list[dict[str, Any]] = []
        self.interrupted = False
        self.uploads: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/prompt" and request.method == "POST":
            body = json.loads(request.content)
            self.submitted.append(body)
            if self.prompt_status != 200:
                return httpx.Response(self.prompt_status, json=self.prompt_body)
            return httpx.Response(200, json={"prompt_id": body["prompt_id"], "number": 1, "node_errors": {}})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[1]
            prompt = self.submitted[-1]["prompt"] if self.submitted else {}
            save_node = next((k for k, v in prompt.items() if v["class_type"].startswith("Save")), "9")
            return httpx.Response(200, json={pid: {
                "outputs": {save_node: {"images": [{"filename": "img_00001_.png", "subfolder": "acs", "type": "output"},
                                             {"filename": "preview.png", "subfolder": "", "type": "temp"}]}},
                "status": {"status_str": self.history_status, "completed": True, "messages": self.messages}}})
        if path == "/queue" and request.method == "GET":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if path == "/view":
            return httpx.Response(200, content=b"\x89PNG fake")
        if path == "/upload/image":
            self.uploads.append(request.headers.get("content-type", ""))
            return httpx.Response(200, json={"name": "up.png", "subfolder": "acs", "type": "input"})
        if path in ("/interrupt", "/queue"):
            self.interrupted = True
            return httpx.Response(200)
        if path == "/models/checkpoints":
            return httpx.Response(200, json=["v1-5-pruned-emaonly-fp16.safetensors"])
        if path.startswith("/models/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)


def make_client(fake: FakeComfy) -> ComfyUIClient:
    c = ComfyUIClient("http://comfy.test", use_websocket=False, poll_interval=0.01)
    c._http = httpx.AsyncClient(base_url="http://comfy.test", transport=httpx.MockTransport(fake.handler))
    return c


async def test_run_and_download(tmp_path: Path) -> None:
    fake = FakeComfy()
    client = make_client(fake)
    tpl = TEMPLATES.get("smoke_test_image")
    history = await client.run(render(tpl, {}), JobContext.detached(tmp_path))
    items = client.output_items(history, tpl.meta.outputs)
    assert [i["filename"] for i in items] == ["img_00001_.png"]  # temp previews excluded
    path = await client.download(items[0], tmp_path)
    assert path.read_bytes().startswith(b"\x89PNG")
    assert fake.submitted[0]["prompt"]["1"]["class_type"] == "EmptyImage"


async def test_missing_model_maps_to_model_not_installed(tmp_path: Path) -> None:
    body = {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
            "node_errors": {"4": {"class_type": "CheckpointLoaderSimple", "errors": [
                {"type": "value_not_in_list", "message": "Value not in list", "details": "ckpt_name: 'x' not in []",
                 "extra_info": {"input_name": "ckpt_name"}}]}}}
    client = make_client(FakeComfy(prompt_status=400, prompt_body=body))
    tpl = TEMPLATES.get("checkpoint_txt2img")
    with pytest.raises(ModelNotInstalledError) as exc:
        await client.run(render(tpl, {"prompt": "x", "model": "x"}), JobContext.detached(tmp_path))
    assert exc.value.details["missing_files"] == ["x"]


async def test_other_validation_errors(tmp_path: Path) -> None:
    body = {"error": {"message": "bad"}, "node_errors": {"3": {"class_type": "KSampler", "errors": [
        {"type": "value_bigger_than_max", "message": "Value 200 bigger than max", "extra_info": {"input_name": "steps"}}]}}}
    client = make_client(FakeComfy(prompt_status=400, prompt_body=body))
    with pytest.raises(ValidationError) as exc:
        await client.run({"3": {"class_type": "KSampler", "inputs": {}}}, JobContext.detached(tmp_path))
    assert "KSampler.steps" in exc.value.message


async def test_oom_error_has_hint(tmp_path: Path) -> None:
    msgs = [["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory. Tried to allocate"}]]
    client = make_client(FakeComfy(history_status="error", messages=msgs))
    with pytest.raises(GenerationError) as exc:
        await client.run(render(TEMPLATES.get("smoke_test_image"), {}), JobContext.detached(tmp_path))
    assert "Grafikspeicher" in exc.value.message


async def test_unreachable_comfyui() -> None:
    client = ComfyUIClient("http://127.0.0.1:9", request_timeout=1)
    with pytest.raises(ProviderUnavailableError):
        await client.system_stats()
    await client.close()


async def test_upload_returns_subfolder_path(tmp_path: Path) -> None:
    fake = FakeComfy()
    client = make_client(fake)
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    assert await client.upload_image(img) == "acs/up.png"
    assert "multipart/form-data" in fake.uploads[0]


async def test_provider_resolves_raw_checkpoint_and_missing_models(settings: Any, tmp_path: Path) -> None:
    from backend.providers.comfyui.image import ComfyUIImageProvider
    from backend.providers.registry import ProviderRegistry

    fake = FakeComfy()
    reg = ProviderRegistry(settings)
    prov: ComfyUIImageProvider = reg.get("image", "comfyui")  # type: ignore[assignment]
    prov.client._http = httpx.AsyncClient(base_url="http://comfy.test", transport=httpx.MockTransport(fake.handler))
    cm, tpl, params = await prov.resolve_model("v1-5-pruned-emaonly-fp16.safetensors", "text_to_image")
    assert cm is not None and cm.id == "sd15" and tpl == "checkpoint_txt2img"
    with pytest.raises(ModelNotInstalledError) as exc:
        await prov.resolve_model("sd15-lcm", "text_to_image")  # LoRA missing
    assert "lcm-lora" in exc.value.message
    models = await prov.get_models()
    assert any(m.id == "sd15" and m.installed for m in models)
    await reg.close()
