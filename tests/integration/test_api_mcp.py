"""REST API (ASGI) and MCP server (in-memory MCP client → MCP server → API)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from typing import Any

import httpx
import pytest

from tests.conftest import needs_ffmpeg, write_test_image

pytestmark = needs_ffmpeg


async def _wait_job(api: httpx.AsyncClient, job_id: str, timeout: float = 60) -> dict[str, Any]:
    r = await api.get(f"/api/jobs/{job_id}/wait", params={"timeout": timeout})
    return r.json()


# --------------------------------------------------------------------- API
async def test_health_status_and_presets(api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/health")).json()["status"] == "ok"
    status = (await api.get("/api/system/status")).json()
    assert status["profile"]["profile"] == "low" and status["comfyui"]["available"] is False
    assert "ffmpeg" in status["providers"]
    presets = (await api.get("/api/presets")).json()
    assert "cinematic" in presets["styles"] and "youtube_thumbnail" in presets["resolution_presets"]
    providers = (await api.get("/api/providers")).json()
    assert {p["name"] for p in providers} >= {"comfyui", "ffmpeg", "mock", "blender", "remotion"}
    assert all(p["location"] == "local" for p in providers)


async def test_generate_job_lifecycle(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/images/generate", json={"prompt": "api test", "provider": "mock", "batch_size": 1})
    assert r.status_code == 202
    job = await _wait_job(api, r.json()["job"]["id"])
    assert job["status"] == "succeeded"
    asset_id = job["result"]["asset_ids"][0]
    meta = (await api.get(f"/api/assets/{asset_id}")).json()
    assert meta["sidecar"]["asset"]["id"] == asset_id and meta["exists"]
    assert (await api.get(f"/api/assets/{asset_id}/file")).headers["content-type"] == "image/png"
    assert (await api.get(f"/api/assets/{asset_id}/thumbnail")).headers["content-type"] == "image/webp"
    patched = (await api.patch(f"/api/assets/{asset_id}", json={"add_tags": ["hero"], "favorite": True})).json()
    assert patched["favorite"] and "hero" in patched["tags"]
    found = (await api.get("/api/assets", params={"q": "api test", "favorite": True})).json()
    assert found["total"] == 1
    jobs = (await api.get("/api/jobs", params={"type": "image.*"})).json()
    assert jobs["jobs"][0]["id"] == job["id"]


async def test_error_envelopes(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/images/generate", json={"prompt": ""})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"
    assert (await api.post("/api/images/nonsense", json={})).status_code == 404
    r = await api.get("/api/process/info", params={"path": "../../etc/passwd"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "path_not_allowed"
    assert (await api.get("/api/jobs/" + "0" * 32)).status_code == 404


async def test_upload_and_validation(api: httpx.AsyncClient, tmp_path: Any) -> None:
    img = write_test_image(tmp_path / "up.png", (1280, 720))
    with img.open("rb") as fh:
        r = await api.post("/api/assets/upload", files={"file": ("my photo.png", fh, "image/png")}, data={"tags": "kunde"})
    asset = r.json()
    assert asset["path"] == "references/my_photo.png" and "kunde" in asset["tags"]
    r = await api.post("/api/assets/upload", files={"file": ("evil.sh", b"#!/bin/sh", "text/plain")})
    assert r.status_code == 400
    v = (await api.post("/api/quality/validate-resolution", json={"asset": asset["id"], "preset": "youtube_thumbnail"})).json()
    assert v["valid"]


async def test_workflow_endpoints_and_estimate(api: httpx.AsyncClient) -> None:
    wfs = (await api.get("/api/workflows")).json()
    assert len(wfs) >= 14
    d = (await api.get("/api/workflows/images/text-to-image/definition")).json()
    assert d["inputs"]["prompt"]["required"]
    assert (await api.post("/api/workflows/images/text-to-image/run", json={"inputs": {}})).status_code == 400
    r = await api.post("/api/workflows/images/text-to-image/run",
                       json={"inputs": {"prompt": "x", "variants": 1, "image_provider": "mock"}})
    job = await _wait_job(api, r.json()["job"]["id"])
    assert job["status"] == "succeeded"
    est = (await api.post("/api/estimate", json={"type": "image.generate", "params": {"prompt": "x"}})).json()
    assert est["is_free"] and est["model"] == "sd15-lcm" and est["resources"]["est_seconds"]


async def test_settings_roundtrip(api: httpx.AsyncClient, studio: Any) -> None:
    r = await api.put("/api/settings", json={"updates": {"hardware": {"profile": "mid"}, "quality": {"min_score": 70}}})
    assert r.json()["saved"]
    assert studio.hardware()[1].profile == "mid"
    assert (studio.settings.configs_dir / "studio.local.yaml").is_file()
    assert (await api.put("/api/settings", json={"updates": {"server": {"port": 1}}})).status_code == 400
    s = (await api.get("/api/settings")).json()
    assert s["settings"]["quality"]["min_score"] == 70 and "api_token" not in s["settings"]


async def test_token_auth(settings: Any) -> None:
    from backend.api.app import create_app
    from backend.orchestration.studio import Studio

    settings.api_token = "s3cret"
    app = create_app(Studio(settings, configure_logging=False), start_queue=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/health")).status_code == 200
        assert (await c.get("/api/jobs")).status_code == 401
        assert (await c.get("/api/jobs", headers={"Authorization": "Bearer s3cret"})).status_code == 200
        assert (await c.get("/api/jobs", params={"token": "s3cret"})).status_code == 200


def test_sse_stream_live_server(settings: Any) -> None:
    """Server-Sent Events need a real server (ASGITransport buffers responses)."""
    import socket

    import uvicorn

    from backend.api.app import create_app
    from backend.orchestration.studio import Studio
    from tests.conftest import fake_hardware

    studio = Studio(settings, configure_logging=False)
    studio.set_hardware(*fake_hardware())
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(create_app(studio), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/api/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    events: list[str] = []

    def listen() -> None:
        with httpx.stream("GET", base + "/api/events", timeout=10) as r:
            for line in r.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                if "job.updated" in events:
                    return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.5)
    httpx.post(base + "/api/images/generate", json={"prompt": "sse", "provider": "mock"}, timeout=5)
    t.join(timeout=10)
    server.should_exit = True
    thread.join(timeout=10)
    assert "job.created" in events and "job.updated" in events


# --------------------------------------------------------------------- MCP
@contextlib.asynccontextmanager
async def mcp_session(studio: Any):
    """MCP client → MCP server → FastAPI app (in-process). Context manager, not a fixture:
    anyio cancel scopes must be entered and exited in the same task."""
    from mcp import Client

    from backend.api.app import create_app
    from mcp_server import server as mcp_mod

    app = create_app(studio, start_queue=False)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    mcp_mod.backend.set_client(http)
    mcp_mod.backend._assets_root = None
    try:
        async with Client(mcp_mod.mcp) as client:
            yield client
    finally:
        await http.aclose()
        mcp_mod.backend._client = None


def _data(result: Any) -> Any:
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


REQUIRED_TOOLS = {
    "get_system_status", "get_available_models", "get_workflows", "generate_image", "generate_video", "get_job_status",
    "cancel_job", "get_video_info", "convert_video", "extract_frames", "merge_videos", "add_audio", "add_subtitles",
    "render_video", "list_assets", "get_asset_metadata", "search_assets", "organize_assets", "analyze_image",
    "analyze_video", "validate_resolution", "generate_quality_report",
}


async def test_mcp_tool_catalog(studio: Any) -> None:
    async with mcp_session(studio) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert REQUIRED_TOOLS <= set(tools), REQUIRED_TOOLS - set(tools)
        schema = tools["generate_image"].input_schema
        assert schema["properties"]["batch_size"]["maximum"] == 8 and "prompt" in schema["required"]



async def test_mcp_generate_inspect_and_quality(studio: Any) -> None:
    async with mcp_session(studio) as client:
        r = await client.call_tool("generate_image", {"prompt": "mcp fox", "provider": "mock", "seed": 1})
        assert not r.is_error, r.content
        data = _data(r)
        assert data["status"] == "succeeded"
        asset = data["result"]["assets"][0]
        assert asset["file"].endswith(asset["path"]) and asset["quality_score"] is not None
        meta = _data(await client.call_tool("get_asset_metadata", {"asset_id": asset["id"]}))
        assert meta["seed"] == 1 and meta["prompt"].startswith("mcp fox")
        q = _data(await client.call_tool("analyze_image", {"source": asset["id"], "expected_aspect": "1:1"}))
        assert q["status"] == "succeeded" and q["result"]["reports"][0]["score"] >= 0
        s = _data(await client.call_tool("search_assets", {"query": "mcp fox"}))
        assert s["total"] == 1
        v = _data(await client.call_tool("validate_resolution", {"width": 1080, "height": 1920, "preset": "tiktok"}))
        assert v["valid"]
        rep = _data(await client.call_tool("generate_quality_report", {"assets": [asset["id"]], "title": "Test"}))
        assert rep["result"]["report_path"].endswith(".md")



async def test_mcp_safety_and_errors(studio: Any) -> None:
    async with mcp_session(studio) as client:
        r = await client.call_tool("get_video_info", {"path": "../../etc/passwd"})
        assert r.is_error and ".." in r.content[0].text
        r = await client.call_tool("get_video_info", {"path": "/etc/passwd"})
        assert r.is_error and "path_not_allowed" in r.content[0].text
        r = await client.call_tool("generate_image", {"prompt": "x", "batch_size": 99})
        assert r.is_error  # schema validation
        r = await client.call_tool("generate_video", {"prompt": "x"})
        assert not r.is_error and _data(r)["error"]["code"] == "hardware_insufficient"
        plan = _data(await client.call_tool("organize_assets", {}))
        assert plan["dry_run"] is True



async def test_mcp_workflow_and_jobs(studio: Any) -> None:
    async with mcp_session(studio) as client:
        wfs = _data(await client.call_tool("get_workflows", {}))
        assert any(w["id"] == "videos/kenburns-slideshow" for w in wfs)
        r = _data(await client.call_tool("run_workflow", {"workflow_id": "images/text-to-image", "inputs": {
            "prompt": "x", "variants": 1, "image_provider": "mock"}, "wait": False}))
        assert r["status"] in ("queued", "running")
        done = _data(await client.call_tool("wait_for_job", {"job_id": r["job_id"], "timeout_s": 60}))
        assert done["status"] == "succeeded" and done["result"]["outputs"]["images"]
        jobs = _data(await client.call_tool("list_jobs", {"type": "workflow.run"}))
        assert jobs[0]["job_id"] == r["job_id"]



async def test_mcp_cost_confirmation_passthrough(studio: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async with mcp_session(studio) as client:
        from backend.providers.base import ProviderInfo
        from backend.providers.mock import MockImageProvider

        info = ProviderInfo(name="paid", display_name="Paid", location="cloud", cost_model="per_image", unit_cost=0.05,
                            requires_api_key=True, api_key_env="PAID_KEY", enabled=True, roles=["image"])
        monkeypatch.setenv("PAID_KEY", "x")
        studio.registry.register_instance("paid", "image", MockImageProvider(info, studio.settings), info)
        studio.costs.monthly_budget = 1.0
        first = _data(await client.call_tool("generate_image", {"prompt": "x", "provider": "paid"}))
        assert first["status"] == "cost_confirmation_required" and first["estimate"]["total_cost"] == pytest.approx(0.05)
        second = _data(await client.call_tool("generate_image", {
            "prompt": "x", "provider": "paid", "confirm_token": first["estimate"]["confirmation_token"]}))
        assert second["status"] == "succeeded"



async def test_mcp_backend_unreachable() -> None:
    from mcp import Client

    from mcp_server import server as mcp_mod

    mcp_mod.backend.set_client(httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=1))
    try:
        async with Client(mcp_mod.mcp) as client:
            r = await client.call_tool("get_system_status", {})
            assert r.is_error and "nicht erreichbar" in r.content[0].text
    finally:
        mcp_mod.backend._client = None
    await asyncio.sleep(0)
