"""Async client for the ComfyUI HTTP + WebSocket API.

Endpoints verified against ComfyUI 0.46.0 (server.py):
  POST /prompt  {prompt, client_id, prompt_id}  -> {prompt_id, number, node_errors} | 400 {error, node_errors}
  GET  /history/{prompt_id}                    -> {prompt_id: {outputs, status}}
  GET  /view?filename&subfolder&type            -> file bytes
  POST /upload/image (multipart: image, subfolder, type, overwrite)
  POST /interrupt {prompt_id}  ·  POST /queue {delete: [...]}  ·  GET /queue
  GET  /models/{folder}  ·  GET /object_info[/{node}]  ·  GET /system_stats
  WS   /ws?clientId=…  (events: status, execution_start, executing, progress,
       executed, execution_cached, execution_success, execution_error, execution_interrupted)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from backend.core.errors import (
    GenerationError,
    ModelNotInstalledError,
    ProviderUnavailableError,
    StudioTimeoutError,
    ValidationError,
)
from backend.jobs.context import JobContext

log = logging.getLogger("comfyui")

MODEL_INPUT_NAMES = {
    "ckpt_name", "unet_name", "clip_name", "vae_name", "lora_name", "model_name", "clip_name1", "clip_name2",
    "control_net_name",
}
OOM_MARKERS = ("out of memory", "outofmemory", "cuda error: out of memory", "allocation on device")


class ComfyUIClient:
    def __init__(self, base_url: str, *, request_timeout: float = 30.0, poll_interval: float = 1.0,
                 use_websocket: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.poll_interval = poll_interval
        self.use_websocket = use_websocket
        self._http: httpx.AsyncClient | None = None
        self._models_cache: dict[str, tuple[float, list[str]]] = {}

    # ----------------------------------------------------------------- basics
    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.request_timeout, trust_env=False)
        return self._http

    @property
    def ws_url(self) -> str:
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, parsed.path.rstrip("/") + "/ws", "", "", ""))

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = await self.http.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            raise ProviderUnavailableError(
                f"ComfyUI ist unter {self.base_url} nicht erreichbar. Starten mit ./start.sh "
                "(oder ACS__COMFYUI__URL anpassen).",
                details={"url": self.base_url, "error": str(exc)},
            ) from exc
        except httpx.TimeoutException as exc:
            raise StudioTimeoutError(f"ComfyUI antwortet nicht ({path})") from exc
        return resp

    async def get_json(self, path: str, **params: Any) -> Any:
        resp = await self._request("GET", path, params=params or None)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ info
    async def system_stats(self) -> dict[str, Any]:
        return await self.get_json("/system_stats")

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        return await self.get_json(f"/object_info/{node_class}" if node_class else "/object_info") or {}

    async def queue(self) -> dict[str, Any]:
        return await self.get_json("/queue") or {}

    async def list_models(self, folder: str, max_age_s: float = 15.0) -> list[str]:
        cached = self._models_cache.get(folder)
        if cached and time.monotonic() - cached[0] < max_age_s:
            return cached[1]
        data = await self.get_json(f"/models/{folder}")
        files = list(data or [])
        self._models_cache[folder] = (time.monotonic(), files)
        return files

    def invalidate_models(self) -> None:
        self._models_cache.clear()

    async def installed_models(self, folders: list[str]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for folder in folders:
            try:
                result[folder] = set(await self.list_models(folder))
            except httpx.HTTPStatusError:
                result[folder] = set()
        return result

    # ---------------------------------------------------------------- uploads
    async def upload_image(self, path: Path, *, subfolder: str = "acs", overwrite: bool = True) -> str:
        """Upload an image to ComfyUI's input directory and return the LoadImage value."""
        with path.open("rb") as fh:
            files = {"image": (path.name, fh, "application/octet-stream")}
            data = {"subfolder": subfolder, "type": "input", "overwrite": "true" if overwrite else "false"}
            resp = await self._request("POST", "/upload/image", files=files, data=data)
        if resp.status_code != 200:
            raise GenerationError(f"Upload nach ComfyUI fehlgeschlagen ({resp.status_code}): {resp.text[:300]}")
        info = resp.json()
        name, sub = info.get("name"), info.get("subfolder")
        return f"{sub}/{name}" if sub else name

    async def download(self, item: dict[str, Any], dest_dir: Path) -> Path:
        params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")}
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / Path(item["filename"]).name
        counter = 1
        while target.exists():
            target = dest_dir / f"{Path(item['filename']).stem}_{counter:03d}{Path(item['filename']).suffix}"
            counter += 1
        try:
            async with self.http.stream("GET", "/view", params=params, timeout=None) as resp:
                if resp.status_code != 200:
                    raise GenerationError(f"Ausgabedatei konnte nicht geladen werden: {item['filename']} ({resp.status_code})")
                with target.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        fh.write(chunk)
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError("ComfyUI-Verbindung beim Download verloren") from exc
        return target

    # ---------------------------------------------------------------- control
    async def interrupt(self, prompt_id: str) -> None:
        try:
            await self._request("POST", "/queue", json={"delete": [prompt_id]})
            await self._request("POST", "/interrupt", json={"prompt_id": prompt_id})
        except Exception as exc:  # best effort
            log.warning("Interrupt for %s failed: %s", prompt_id, exc)

    # -------------------------------------------------------------- execution
    async def submit(self, workflow: dict[str, Any], client_id: str, prompt_id: str) -> dict[str, Any]:
        resp = await self._request("POST", "/prompt", json={"prompt": workflow, "client_id": client_id, "prompt_id": prompt_id})
        if resp.status_code == 200:
            return resp.json()
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {"error": {"message": resp.text[:500]}}
        raise self._prompt_error(body, workflow)

    @staticmethod
    def _prompt_error(body: dict[str, Any], workflow: dict[str, Any]) -> Exception:
        error = body.get("error") or {}
        node_errors = body.get("node_errors") or {}
        missing: list[str] = []
        problems: list[str] = []
        for node_id, info in node_errors.items():
            class_type = info.get("class_type") or workflow.get(node_id, {}).get("class_type", "?")
            for err in info.get("errors", []):
                extra = err.get("extra_info") or {}
                input_name = extra.get("input_name")
                if err.get("type") == "value_not_in_list" and input_name in MODEL_INPUT_NAMES:
                    value = workflow.get(node_id, {}).get("inputs", {}).get(input_name)
                    missing.append(str(value))
                else:
                    problems.append(f"{class_type}.{input_name or '?'}: {err.get('message')} {err.get('details', '')}".strip())
        if missing:
            return ModelNotInstalledError(
                "Benötigte Modelldatei(en) fehlen in ComfyUI: " + ", ".join(sorted(set(missing)))
                + ". Installieren mit: python scripts/models/download_models.py --list",
                details={"missing_files": sorted(set(missing))},
            )
        message = error.get("message") or "Ungültiger Workflow"
        if problems:
            message += ": " + "; ".join(problems[:5])
        return ValidationError(f"ComfyUI hat den Workflow abgelehnt – {message}", details={"node_errors": node_errors})

    async def run(self, workflow: dict[str, Any], ctx: JobContext, *, timeout: float = 3600.0) -> dict[str, Any]:
        """Queue a workflow, track progress, return the history entry. Cancels cleanly."""
        client_id = uuid.uuid4().hex
        prompt_id = str(uuid.uuid4())
        ctx.shared["comfy_prompt_id"] = prompt_id
        total_nodes = max(1, len(workflow))
        ws = None
        if self.use_websocket:
            try:
                from websockets.asyncio.client import connect

                ws = await asyncio.wait_for(connect(f"{self.ws_url}?clientId={client_id}", max_size=None,
                                                    proxy=None), timeout=10)
            except Exception as exc:
                log.info("WebSocket unavailable (%s) – falling back to polling", exc)
                ws = None
        try:
            await self.submit(workflow, client_id, prompt_id)
            await ctx.progress(0.02, "In ComfyUI-Warteschlange")
            if ws is not None:
                await asyncio.wait_for(self._track_ws(ws, prompt_id, total_nodes, ctx), timeout=timeout)
            else:
                await asyncio.wait_for(self._track_poll(prompt_id, ctx), timeout=timeout)
            history = await self._history(prompt_id)
            if history is None:
                raise GenerationError("ComfyUI hat kein Ergebnis geliefert")
            status = history.get("status") or {}
            if status.get("status_str") == "error":
                raise self._execution_error(status)
            return history
        except asyncio.CancelledError:
            await asyncio.shield(self.interrupt(prompt_id))
            raise
        except asyncio.TimeoutError:
            await self.interrupt(prompt_id)
            raise StudioTimeoutError(f"ComfyUI-Generierung hat das Zeitlimit von {int(timeout)} s überschritten") from None
        finally:
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    async def _history(self, prompt_id: str) -> dict[str, Any] | None:
        data = await self.get_json(f"/history/{prompt_id}")
        return (data or {}).get(prompt_id)

    async def _queue_position(self, prompt_id: str) -> int | None:
        q = await self.queue()
        for i, item in enumerate(q.get("queue_pending", [])):
            if len(item) > 1 and item[1] == prompt_id:
                return i + 1
        for item in q.get("queue_running", []):
            if len(item) > 1 and item[1] == prompt_id:
                return 0
        return None

    async def _track_poll(self, prompt_id: str, ctx: JobContext) -> None:
        while True:
            history = await self._history(prompt_id)
            if history is not None and (history.get("status") or {}).get("completed") is not None:
                if (history.get("status") or {}).get("status_str") in ("success", "error"):
                    return
            pos = await self._queue_position(prompt_id)
            if pos is None and history is not None:
                return
            if pos and pos > 0:
                await ctx.progress(0.02, f"Warteschlange: Position {pos}")
            else:
                await ctx.progress(max(ctx.last_fraction, 0.05), "Wird generiert …")
            await asyncio.sleep(self.poll_interval)

    async def _track_ws(self, ws: Any, prompt_id: str, total_nodes: int, ctx: JobContext) -> None:
        done_nodes: set[str] = set()
        current_frac = 0.0
        current_node: str | None = None
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(5.0, self.poll_interval * 10))
            except asyncio.TimeoutError:
                # No event for a while: check history in case we missed the end.
                history = await self._history(prompt_id)
                if history is not None and (history.get("status") or {}).get("status_str") in ("success", "error"):
                    return
                continue
            if isinstance(raw, bytes):
                continue  # preview images
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            mtype, data = msg.get("type"), msg.get("data") or {}
            if data.get("prompt_id") not in (None, prompt_id):
                continue
            if mtype == "execution_cached":
                done_nodes.update(str(n) for n in data.get("nodes", []))
            elif mtype == "executing":
                node = data.get("node")
                if node is None and data.get("prompt_id") == prompt_id:
                    return  # legacy completion signal
                if current_node:
                    done_nodes.add(current_node)
                current_node = str(node) if node is not None else None
                current_frac = 0.0
            elif mtype == "progress":
                mx = data.get("max") or 1
                current_frac = min(1.0, (data.get("value") or 0) / mx)
                await ctx.progress(
                    0.05 + 0.9 * min(1.0, (len(done_nodes) + current_frac) / total_nodes),
                    f"Schritt {data.get('value')}/{mx}",
                )
                continue
            elif mtype == "executed":
                done_nodes.add(str(data.get("node")))
            elif mtype in ("execution_success", "execution_error", "execution_interrupted"):
                return
            await ctx.progress(0.05 + 0.9 * min(1.0, (len(done_nodes) + current_frac) / total_nodes), "Wird generiert …")

    @staticmethod
    def _execution_error(status: dict[str, Any]) -> Exception:
        detail = ""
        for entry in status.get("messages", []):
            if isinstance(entry, list) and len(entry) == 2 and entry[0] == "execution_error":
                info = entry[1]
                detail = f"{info.get('node_type', '')}: {info.get('exception_message', '')}".strip()
                break
        low = detail.lower()
        if any(m in low for m in OOM_MARKERS):
            return GenerationError(
                "Nicht genug Grafikspeicher (OOM). Auflösung/Frames reduzieren, ein kleineres Modell wählen "
                "oder andere Programme schließen, die Grafikspeicher belegen.",
                details={"engine_error": detail},
            )
        return GenerationError(f"ComfyUI-Ausführung fehlgeschlagen: {detail or 'unbekannter Fehler'}",
                               details={"engine_error": detail})

    @staticmethod
    def output_items(history: dict[str, Any], output_nodes: list[str] | None = None) -> list[dict[str, Any]]:
        """Collect every file reference from history outputs (images, videos, gifs, audio)."""
        items: list[dict[str, Any]] = []
        for node_id, out in (history.get("outputs") or {}).items():
            if output_nodes and node_id not in output_nodes:
                continue
            for value in out.values():
                if isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, dict) and "filename" in entry and entry.get("type", "output") == "output":
                            items.append(entry)
        return items
