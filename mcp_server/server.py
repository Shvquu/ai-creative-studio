"""AI Creative Studio – MCP server.

A thin, validating client of the local backend API (default http://127.0.0.1:8420).
All work (queue, providers, path checks, cost control) happens in the backend, so
jobs started from Claude Code are visible live in the dashboard.

Security properties:
  * no shell execution, no arbitrary file access – file arguments are asset ids or
    paths inside the assets directory (validated here *and* by the backend PathGuard)
  * typed + range-checked arguments (pydantic schemas → JSON Schema for the client)
  * per-request timeouts, structured errors, logging to data/logs/mcp.log (never stdout)
  * paid providers never run without an explicit confirmation token

Run:  python -m mcp_server.server   (Claude Code starts it via .mcp.json)
"""

from __future__ import annotations

import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

ROOT = Path(__file__).resolve().parents[1]
BACKEND_URL = os.environ.get("ACS_MCP_BACKEND_URL", "http://127.0.0.1:8420").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("ACS_MCP_TIMEOUT_S", "30"))
MAX_WAIT_S = 1800

log = logging.getLogger("mcp_server")


def _setup_logging() -> None:
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / "mcp.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- types
AssetRef = Annotated[str, Field(min_length=1, max_length=1024,
                                description="Asset-ID (32 Hex-Zeichen) oder Pfad innerhalb von assets/ (z. B. references/logo.png)")]
Hex = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", description="Hex-Farbe #RRGGBB")]
Aspect = Annotated[str, Field(pattern=r"^\d{1,2}:\d{1,2}$", description="Seitenverhältnis, z. B. 16:9")]
Project = Annotated[str | None, Field(default=None, max_length=80, description="Projektname zur Gruppierung")]
ConfirmToken = Annotated[str | None, Field(default=None, max_length=200,
                                           description="Nur nach ausdrücklicher Zustimmung des Benutzers zu einer Kostenschätzung")]
Wait = Annotated[bool, Field(default=True, description="Auf Fertigstellung warten (sonst sofort Job-ID zurückgeben)")]
Timeout = Annotated[int, Field(default=900, ge=1, le=MAX_WAIT_S, description="Maximale Wartezeit in Sekunden")]

_ASSET_ID = re.compile(r"^[0-9a-f]{32}$")


def check_ref(ref: str) -> str:
    """Reject obviously unsafe references early (backend enforces allowed roots again)."""
    if "\x00" in ref:
        raise ToolError("Ungültiger Pfad")
    if _ASSET_ID.match(ref):
        return ref
    parts = Path(ref.replace("\\", "/")).parts
    if ".." in parts:
        raise ToolError("Pfade mit '..' sind nicht erlaubt – Asset-ID oder Pfad innerhalb von assets/ verwenden")
    return ref


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# --------------------------------------------------------------------------- backend client
class Backend:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._assets_root: Path | None = None

    def set_client(self, client: httpx.AsyncClient) -> None:
        """Inject a client (tests use httpx.ASGITransport against the FastAPI app)."""
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            token = os.environ.get("ACS_API_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            self._client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=REQUEST_TIMEOUT, headers=headers, trust_env=False)
        return self._client

    async def request(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None,
                      timeout: float | None = None) -> Any:
        started = time.monotonic()
        try:
            resp = await self.client.request(method, f"/api{path}", json=json, params=params,
                                             timeout=timeout or REQUEST_TIMEOUT)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            log.warning("%s %s → backend unreachable", method, path)
            raise ToolError(
                f"AI-Creative-Studio-Backend nicht erreichbar ({BACKEND_URL}). Starten mit ./start.sh "
                "(Windows: .\\start.ps1) oder: python -m backend.cli serve"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ToolError(f"Zeitüberschreitung bei {path} – der Job läuft ggf. weiter (get_job_status).") from exc
        log.info("%s %s → %s (%.2fs)", method, path, resp.status_code, time.monotonic() - started)
        try:
            data = resp.json()
        except ValueError:
            data = {"error": {"code": "invalid_response", "message": resp.text[:300]}}
        if resp.status_code == 402 and data.get("error", {}).get("code") == "cost_confirmation_required":
            err = data["error"]
            return {"status": "cost_confirmation_required", "message": err["message"],
                    "estimate": err.get("details", {}).get("estimate"),
                    "instruction": "Benutzer ausdrücklich fragen. Nur bei Zustimmung erneut mit confirm_token aufrufen."}
        if resp.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            if err:
                hint = _HINTS.get(err.get("code", ""), "")
                details = err.get("details") or {}
                extra = ""
                if details.get("fallback_workflow"):
                    extra = f" Fallback-Workflow: {details['fallback_workflow']}."
                raise ToolError(f"[{err.get('code')}] {err.get('message')}{extra}{(' – ' + hint) if hint else ''}")
            detail = data.get("detail") if isinstance(data, dict) else data
            raise ToolError(f"HTTP {resp.status_code}: {str(detail)[:500]}")
        return data

    async def assets_root(self) -> Path:
        if self._assets_root is None:
            try:
                s = (await self.request("GET", "/settings"))["settings"]
                p = Path(s["paths"]["assets_dir"])
                self._assets_root = p if p.is_absolute() else Path(s["project_root"]) / p
            except ToolError:
                self._assets_root = ROOT / "assets"
        return self._assets_root


backend = Backend()

_HINTS = {
    "provider_unavailable": "ComfyUI starten (./start.sh startet ComfyUI mit) oder comfyui.url prüfen.",
    "model_not_installed": "Benutzer fragen, ob das Modell heruntergeladen werden soll (scripts/models/download_models.py) – große Downloads nie ungefragt.",
    "hardware_insufficient": "Kleineres Modell/geringere Auflösung oder den Fallback-Workflow nutzen.",
    "budget_exceeded": "Kein Budget für kostenpflichtige Provider freigegeben – lokale Provider verwenden.",
    "path_not_allowed": "Nur Asset-IDs oder Dateien innerhalb von assets/ sind erlaubt (Dateien nach assets/references kopieren, dann rescan_assets).",
    "tool_not_found": "Externes Programm fehlt – siehe docs/INSTALLATION.md.",
}


# --------------------------------------------------------------------------- result shaping
async def _compact_asset(a: dict[str, Any]) -> dict[str, Any]:
    root = await backend.assets_root()
    q = a.get("quality") or {}
    return _drop_none({
        "id": a.get("id"), "path": a.get("path"), "file": str(root / a["path"]) if a.get("path") else None,
        "kind": a.get("kind"), "width": a.get("width"), "height": a.get("height"), "duration_s": a.get("duration_s"),
        "fps": a.get("fps"), "model": a.get("model"), "seed": a.get("seed"),
        "quality_score": q.get("score"), "quality_passed": q.get("passed"),
    })


async def _compact_job(job: dict[str, Any]) -> dict[str, Any]:
    out = _drop_none({"job_id": job["id"], "type": job["type"], "status": job["status"],
                      "progress": round(job.get("progress", 0), 3), "message": job.get("message"),
                      "error": job.get("error"), "label": job.get("label")})
    result = job.get("result")
    if result:
        assets = result.get("assets") or ([result["asset"]] if result.get("asset") else [])
        summary: dict[str, Any] = {k: result[k] for k in ("model", "seed", "provider", "fallback", "fallback_used",
                                                          "outputs", "passed", "average_score", "colors",
                                                          "typography_suggestions", "report_path", "log")
                                   if result.get(k) is not None}
        if assets:
            summary["assets"] = [await _compact_asset(a) for a in assets[:40]]
        if result.get("quality"):
            summary["quality"] = result["quality"]
        if result.get("reports"):
            summary["reports"] = [{"path": r.get("path"), "score": r.get("score"), "passed": r.get("passed"),
                                   "issues": [i["message"] for i in r.get("issues", [])], "metrics": r.get("metrics")}
                                  for r in result["reports"]]
        out["result"] = summary
    return out


async def _wait(job_id: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + min(timeout_s, MAX_WAIT_S)
    job: dict[str, Any] = {}
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        chunk = min(60.0, remaining)
        job = await backend.request("GET", f"/jobs/{job_id}/wait", params={"timeout": chunk}, timeout=chunk + 15)
        if job["status"] in ("succeeded", "failed", "cancelled"):
            break
    compact = await _compact_job(job)
    if compact.get("status") not in ("succeeded", "failed", "cancelled"):
        compact["note"] = "Noch nicht fertig – später get_job_status oder wait_for_job aufrufen."
    return compact


async def _submit(path: str, params: dict[str, Any], wait: bool, timeout_s: int) -> dict[str, Any]:
    data = await backend.request("POST", path, json=_drop_none(params))
    if data.get("status") == "cost_confirmation_required":
        return data
    job = data["job"]
    if not wait:
        return await _compact_job(job)
    return await _wait(job["id"], timeout_s)


# --------------------------------------------------------------------------- server
mcp = MCPServer(
    "ai-creative-studio",
    instructions=(
        "Lokales AI Creative Studio (ComfyUI, FFmpeg, Blender, Remotion). Du orchestrierst – die Engines generieren. "
        "Vor größeren Aufträgen get_system_status/get_hardware_profile prüfen. Dateien werden als Asset-ID oder Pfad "
        "in assets/ übergeben. Ergebnisse enthalten 'file' (absoluter Pfad) – Bilder kannst du mit Read ansehen. "
        "Kostenpflichtige Aktionen liefern eine Schätzung: IMMER den Benutzer fragen, erst dann confirm_token senden. "
        "Modelle nie ungefragt herunterladen."
    ),
    version="0.1.0",
)

# ---- System / status ----------------------------------------------------------


@mcp.tool()
async def get_system_status() -> dict[str, Any]:
    """Systemstatus: Hardwareprofil, CPU/RAM/GPU/VRAM-Auslastung, ComfyUI-Erreichbarkeit, Provider, aktive Jobs, Speicher."""
    s = await backend.request("GET", "/system/status")
    return {
        "profile": s["profile"], "hardware": s["hardware"], "usage": s["usage"], "disk": s["disk"], "comfyui": s["comfyui"],
        "providers": {name: {role: {"available": h["available"], "detail": h["detail"]} for role, h in roles.items()}
                      for name, roles in s["providers"].items()},
        "jobs": s["jobs"], "active_jobs": [await _compact_job(j) for j in s["active_jobs"]],
        "assets": s["assets"], "costs": s["costs"],
    }


@mcp.tool()
async def get_hardware_profile(refresh: bool = False) -> dict[str, Any]:
    """Erkannte Hardware, gewähltes Profil (low/mid/high) inkl. Begründung und empfohlene Modelle pro Aufgabe."""
    h = await backend.request("GET", "/system/hardware", params={"refresh": refresh}, timeout=60)
    return {"decision": h["decision"], "profile": h["profile"], "recommended_models": h["recommended_models"],
            "gpus": h["report"]["gpus"], "ram_total_gb": h["report"]["ram_total_gb"], "notes": h["report"]["notes"]}


@mcp.tool()
async def list_providers() -> list[dict[str, Any]]:
    """Alle Provider mit Ort (local/cloud), Kostenmodell, API-Key-Pflicht, aktiviert, Gesundheit und Fähigkeiten."""
    return [{k: p[k] for k in ("name", "display_name", "location", "cost_model", "unit_cost", "requires_api_key",
                               "enabled", "roles", "capabilities", "health", "default_for", "license_note")}
            for p in await backend.request("GET", "/providers")]


@mcp.tool()
async def get_available_models(task: Annotated[str | None, Field(
        default=None, description="Optional: text_to_image, image_to_image, inpaint, outpaint, upscale, text_to_video, image_to_video")] = None
                               ) -> dict[str, Any]:
    """Modellkatalog mit Installationsstatus, Hardware-Eignung, Lizenz und Empfehlung je Aufgabe."""
    data = await backend.request("GET", "/models", timeout=60)
    catalog = [{k: m.get(k) for k in ("id", "name", "type", "installed", "fits_hardware", "hardware_note", "size_gb",
                                      "license", "commercial_use", "missing_files")} for m in data["catalog"]]
    out: dict[str, Any] = {"profile": data["profile"]["profile"], "comfyui_error": data["comfyui_error"],
                           "catalog": catalog, "recommended": data["recommended"]}
    if task:
        out["candidates"] = data["by_task"].get(task, [])
    out["download_hint"] = "python scripts/models/download_models.py --model <id> (nur nach Zustimmung des Benutzers)"
    return out


@mcp.tool()
async def get_presets() -> dict[str, Any]:
    """Stil-Presets, Kamerabewegungen, Social-Media-Formate, Auflösungs-Presets, Übergänge."""
    return await backend.request("GET", "/presets")


@mcp.tool()
async def get_comfyui_templates() -> list[dict[str, Any]]:
    """ComfyUI-Workflow-Templates (engines/comfyui/workflows) mit Aufgabe, Modellfamilie und Parametern."""
    return [{k: t.get(k) for k in ("id", "name", "task", "kind", "family", "description", "uploads")}
            | {"parameters": sorted(t.get("parameters", {}))} for t in await backend.request("GET", "/comfyui/templates")]


@mcp.tool()
async def run_smoke_test(timeout_s: Timeout = 300) -> dict[str, Any]:
    """Prüft die ComfyUI-Anbindung ohne Modelle (Queue, Ausführung, Bild- und Video-Download)."""
    data = await backend.request("POST", "/jobs", json={"type": "system.smoke_test", "params": {}})
    return await _wait(data["job"]["id"], timeout_s)


@mcp.tool()
async def estimate_cost(job_type: Annotated[str, Field(description="z. B. image.generate, video.generate, workflow.run")],
                        params: dict[str, Any]) -> dict[str, Any]:
    """Kosten- und Ressourcenschätzung (Provider, Modell, Anzahl, Kosten, VRAM/RAM, Dauer) ohne etwas auszuführen."""
    return await backend.request("POST", "/estimate", json={"type": job_type, "params": params})


# ---- Workflows & jobs -----------------------------------------------------------


@mcp.tool()
async def get_workflows() -> list[dict[str, Any]]:
    """Verfügbare Workflows (Bild, Video, Branding, Social Media, Motion Design) mit Eingaben und Voraussetzungen."""
    return await backend.request("GET", "/workflows")


@mcp.tool()
async def run_workflow(workflow_id: Annotated[str, Field(max_length=120, description="z. B. images/text-to-image")],
                       inputs: dict[str, Any], project: Project = None, confirm_token: ConfirmToken = None,
                       wait: Wait = True, timeout_s: Timeout = 1800) -> dict[str, Any]:
    """Workflow ausführen. Ohne GPU nutzen Video-Workflows automatisch den Ken-Burns-Fallback (siehe fallback_used)."""
    data = await backend.request("POST", f"/workflows/{workflow_id}/run",
                                 json=_drop_none({"inputs": inputs, "project": project, "confirm_token": confirm_token}))
    if data.get("status") == "cost_confirmation_required":
        return data
    return await _wait(data["job"]["id"], timeout_s) if wait else await _compact_job(data["job"])


@mcp.tool()
async def get_job_status(job_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]) -> dict[str, Any]:
    """Status, Fortschritt, Fehler und Ergebnis (Assets mit Dateipfaden, Qualität) eines Jobs."""
    return await _compact_job(await backend.request("GET", f"/jobs/{job_id}"))


@mcp.tool()
async def wait_for_job(job_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")], timeout_s: Timeout = 600) -> dict[str, Any]:
    """Blockiert bis der Job fertig ist (oder Timeout) und gibt das Ergebnis zurück."""
    return await _wait(job_id, timeout_s)


@mcp.tool()
async def cancel_job(job_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]) -> dict[str, Any]:
    """Job abbrechen (wartend: sofort; laufend: ComfyUI-Interrupt bzw. Prozessabbruch)."""
    return await _compact_job(await backend.request("POST", f"/jobs/{job_id}/cancel", timeout=45))


@mcp.tool()
async def retry_job(job_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]) -> dict[str, Any]:
    """Fehlgeschlagenen/abgebrochenen Job mit identischen Parametern neu starten."""
    return await _compact_job((await backend.request("POST", f"/jobs/{job_id}/retry"))["job"])


@mcp.tool()
async def list_jobs(status: Annotated[str | None, Field(default=None, description="z. B. running,queued")] = None,
                    type: Annotated[str | None, Field(default=None, description="z. B. image.* oder workflow.run")] = None,
                    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20) -> list[dict[str, Any]]:
    """Job-Historie (neueste zuerst)."""
    data = await backend.request("GET", "/jobs", params=_drop_none({"status": status, "type": type, "limit": limit}))
    return [await _compact_job(j) for j in data["jobs"]]


# ---- Image generation & editing ------------------------------------------------


@mcp.tool()
async def generate_image(
    prompt: Annotated[str, Field(min_length=1, max_length=4000)],
    negative_prompt: Annotated[str | None, Field(default=None, max_length=4000)] = None,
    style: Annotated[str | None, Field(default=None, description="Preset aus get_presets().styles")] = None,
    model: Annotated[str | None, Field(default=None, description="Katalog-ID (leer = automatisch passend zur Hardware)")] = None,
    aspect_ratio: Aspect | None = None,
    width: Annotated[int | None, Field(default=None, ge=64, le=4096)] = None,
    height: Annotated[int | None, Field(default=None, ge=64, le=4096)] = None,
    steps: Annotated[int | None, Field(default=None, ge=1, le=150)] = None,
    cfg: Annotated[float | None, Field(default=None, ge=0, le=30)] = None,
    seed: Annotated[int | None, Field(default=None, ge=0, le=2**53 - 1)] = None,
    batch_size: Annotated[int, Field(default=1, ge=1, le=8)] = 1,
    loras: Annotated[list[dict[str, Any]] | None, Field(default=None, max_length=8, description=(
        "Zusätzliche LoRAs [{name: Datei in models/loras, strength: 0.0–2.0}] – nur für Checkpoint-Modelle (SD 1.5/SDXL/FLUX.1)"))] = None,
    control_image: Annotated[AssetRef | None, Field(default=None, description=(
        "ControlNet (SD 1.5): Steuerbild – Foto (Kanten werden per Canny übernommen) oder Skizze mit control_mode='none'"))] = None,
    control_mode: Literal["canny", "none"] = "canny",
    control_strength: Annotated[float, Field(default=0.8, ge=0, le=2)] = 0.8,
    provider: Annotated[str | None, Field(default=None, description="leer = Standard (comfyui); 'mock' = Testmodus ohne KI")] = None,
    project: Project = None,
    tags: Annotated[list[str] | None, Field(default=None, max_length=20)] = None,
    confirm_token: ConfirmToken = None,
    wait: Wait = True,
    timeout_s: Timeout = 900,
) -> dict[str, Any]:
    """Bild(er) mit lokalem KI-Modell generieren (ComfyUI). Ergebnis: Assets mit Pfad, Seed, Modell und Qualitätsscore."""
    return await _submit("/images/generate", {
        "prompt": prompt, "negative_prompt": negative_prompt, "style": style, "model": model, "aspect_ratio": aspect_ratio,
        "width": width, "height": height, "steps": steps, "cfg": cfg, "seed": seed, "batch_size": batch_size,
        "loras": loras, "provider": provider,
        "control_image": check_ref(control_image) if control_image else None,
        "control_mode": control_mode if control_image else None,
        "control_strength": control_strength if control_image else None, "project": project, "tags": tags, "confirm_token": confirm_token}, wait, timeout_s)


@mcp.tool()
async def edit_image(
    source: AssetRef,
    prompt: Annotated[str, Field(max_length=4000)] = "",
    mode: Literal["img2img", "inpaint", "outpaint"] = "img2img",
    strength: Annotated[float | None, Field(default=None, ge=0.05, le=1.0, description="Veränderungsstärke (denoise)")] = None,
    mask: AssetRef | None = None,
    left: Annotated[int, Field(default=0, ge=0, le=2048)] = 0,
    top: Annotated[int, Field(default=0, ge=0, le=2048)] = 0,
    right: Annotated[int, Field(default=0, ge=0, le=2048)] = 0,
    bottom: Annotated[int, Field(default=0, ge=0, le=2048)] = 0,
    model: str | None = None,
    seed: Annotated[int | None, Field(default=None, ge=0, le=2**53 - 1)] = None,
    provider: str | None = None,
    project: Project = None,
    wait: Wait = True,
    timeout_s: Timeout = 900,
) -> dict[str, Any]:
    """Bild bearbeiten: img2img (Variation), inpaint (Maske weiß = neu; ohne Maske Alpha-Kanal) oder outpaint (Ränder erweitern)."""
    check_ref(source)
    params: dict[str, Any] = {"source": source, "prompt": prompt, "model": model, "seed": seed, "provider": provider,
                              "project": project, "strength": strength}
    if mode == "inpaint":
        params["mask"] = check_ref(mask) if mask else None
    if mode == "outpaint":
        params.update({"left": left, "top": top, "right": right, "bottom": bottom})
    endpoint = {"img2img": "/images/edit", "inpaint": "/images/inpaint", "outpaint": "/images/outpaint"}[mode]
    return await _submit(endpoint, params, wait, timeout_s)


@mcp.tool()
async def upscale_image(source: AssetRef, scale: Annotated[float, Field(default=2.0, ge=1.0, le=8.0)] = 2.0,
                        method: Literal["auto", "model", "lanczos"] = "auto", project: Project = None,
                        wait: Wait = True, timeout_s: Timeout = 900) -> dict[str, Any]:
    """Hochskalieren mit Real-ESRGAN (falls installiert) oder Lanczos-Fallback."""
    return await _submit("/images/upscale", {"source": check_ref(source), "scale": scale, "method": method,
                                             "project": project}, wait, timeout_s)


@mcp.tool()
async def remove_background(source: AssetRef, alpha_matting: bool = False,
                            model: Annotated[str, Field(default="u2net", max_length=64, description="rembg-Modell, z. B. u2net, isnet-general-use, birefnet-general")] = "u2net",
                            project: Project = None, wait: Wait = True, timeout_s: Timeout = 600) -> dict[str, Any]:
    """Hintergrund entfernen (rembg, lokal; optionales Paket). Ergebnis: PNG mit Transparenz. alpha_matting = feinere Kanten (langsamer)."""
    return await _submit("/images/remove_background", {"source": check_ref(source), "alpha_matting": alpha_matting,
                                                       "model": model, "project": project}, wait, timeout_s)


@mcp.tool()
async def create_contact_sheet(sources: Annotated[list[AssetRef], Field(min_length=1, max_length=64)],
                               columns: Annotated[int, Field(default=3, ge=1, le=8)] = 3,
                               labels: Annotated[list[str] | None, Field(default=None, max_length=64)] = None,
                               cell: Annotated[int, Field(default=384, ge=64, le=1024)] = 384,
                               background: Hex = "#111827") -> dict[str, Any]:
    """Übersichtsbild (Kontaktbogen) mehrerer Bilder/Varianten – z. B. zur Auswahl durch den Benutzer."""
    return await _submit("/images/contact_sheet", {"sources": [check_ref(x) for x in sources], "columns": columns,
                                                   "labels": labels, "cell": cell, "background": background}, True, 300)


@mcp.tool()
async def resize_image(source: AssetRef,
                       format_preset: Annotated[str | None, Field(default=None, description="z. B. instagram_post, youtube_thumbnail")] = None,
                       width: Annotated[int | None, Field(default=None, ge=16, le=8192)] = None,
                       height: Annotated[int | None, Field(default=None, ge=16, le=8192)] = None,
                       mode: Literal["crop", "pad", "blur", "stretch"] = "crop",
                       output_format: Literal["png", "jpg", "webp"] = "png", wait: Wait = True) -> dict[str, Any]:
    """Bild auf Social-Media-Format oder feste Größe bringen (Zuschnitt, Rand oder Blur-Hintergrund)."""
    return await _submit("/images/resize", {"source": check_ref(source), "format_preset": format_preset, "width": width,
                                            "height": height, "mode": mode, "output_format": output_format}, wait, 300)


@mcp.tool()
async def add_text_overlay(source: AssetRef, title: Annotated[str, Field(min_length=1, max_length=120)],
                           subtitle: Annotated[str | None, Field(default=None, max_length=200)] = None,
                           position: Literal["top", "center", "bottom", "left", "right"] = "bottom",
                           color: Hex = "#FFFFFF", accent: Hex = "#FACC15", uppercase: bool = False,
                           font_scale: Annotated[float, Field(default=1.0, ge=0.3, le=3.0)] = 1.0,
                           wait: Wait = True) -> dict[str, Any]:
    """Titel/Untertitel auf ein Bild setzen (Thumbnails, Social Posts) mit Kontrastfläche."""
    return await _submit("/images/text_overlay", {"source": check_ref(source), "title": title, "subtitle": subtitle,
                                                  "position": position, "color": color, "accent": accent,
                                                  "uppercase": uppercase, "font_scale": font_scale}, wait, 300)


@mcp.tool()
async def extract_palette(source: AssetRef | None = None, base_color: Hex | None = None,
                          harmony: Literal["analogous", "complementary", "triadic", "split", "monochrome"] = "analogous",
                          count: Annotated[int, Field(default=5, ge=2, le=12)] = 5) -> dict[str, Any]:
    """Farbpalette aus einem Bild extrahieren oder aus einer Basisfarbe ableiten (inkl. WCAG-Kontrastwerte)."""
    if not source and not base_color:
        raise ToolError("source oder base_color angeben")
    return await _submit("/images/palette", {"source": check_ref(source) if source else None, "base_color": base_color,
                                             "harmony": harmony, "count": count}, True, 120)


# ---- Video generation ------------------------------------------------------------


@mcp.tool()
async def generate_video(
    prompt: Annotated[str, Field(min_length=1, max_length=4000, description="Motiv + Handlung + Licht/Stimmung")],
    image: AssetRef | None = None,
    model: Annotated[str | None, Field(default=None, description="z. B. wan21-t2v-1.3b, wan22-ti2v-5b, wan22-i2v-14b")] = None,
    aspect_ratio: Aspect | None = "16:9",
    duration_s: Annotated[float | None, Field(default=None, gt=0, le=15)] = None,
    frames: Annotated[int | None, Field(default=None, ge=1, le=241, description="wird auf 4n+1 gerundet")] = None,
    fps: Annotated[int | None, Field(default=None, ge=1, le=60)] = None,
    camera_move: Annotated[str | None, Field(default=None, description="Preset aus get_presets().camera_moves")] = None,
    negative_prompt: str | None = None,
    seed: Annotated[int | None, Field(default=None, ge=0, le=2**53 - 1)] = None,
    provider: str | None = None,
    project: Project = None,
    confirm_token: ConfirmToken = None,
    wait: Wait = True,
    timeout_s: Timeout = 1800,
) -> dict[str, Any]:
    """KI-Video generieren (Wan 2.x via ComfyUI). Mit image = Image-to-Video. Ohne GPU: Fehler mit Fallback-Workflow."""
    params = {"prompt": prompt, "image": check_ref(image) if image else None, "model": model, "aspect_ratio": aspect_ratio,
              "duration_s": duration_s, "frames": frames, "fps": fps, "camera_move": camera_move,
              "negative_prompt": negative_prompt, "seed": seed, "provider": provider, "project": project,
              "confirm_token": confirm_token}
    return await _submit("/videos/generate", params, wait, timeout_s)


@mcp.tool()
async def upscale_video(source: AssetRef, scale: Annotated[float, Field(default=2.0, ge=1.0, le=4.0)] = 2.0,
                        method: Literal["auto", "model", "lanczos"] = "auto", project: Project = None,
                        wait: Wait = True, timeout_s: Timeout = 1800) -> dict[str, Any]:
    """Video hochskalieren: Real-ESRGAN Frame für Frame (ComfyUI, Audio/FPS bleiben) oder FFmpeg-Lanczos-Fallback."""
    return await _submit("/videos/upscale", {"source": check_ref(source), "scale": scale, "method": method,
                                             "project": project}, wait, timeout_s)


# ---- FFmpeg ------------------------------------------------------------------------


@mcp.tool()
async def get_video_info(path: AssetRef) -> dict[str, Any]:
    """Medieninfo per ffprobe: Auflösung, Dauer, FPS, Codecs, Bitrate, Audio."""
    return await backend.request("GET", "/process/info", params={"path": check_ref(path)})


@mcp.tool()
async def convert_video(source: AssetRef, format: Literal["mp4", "webm", "mov", "mkv", "gif", "mp3", "wav", "m4a"] = "mp4",
                        crf: Annotated[int | None, Field(default=None, ge=0, le=51)] = None,
                        fps: Annotated[float | None, Field(default=None, gt=0, le=120)] = None,
                        width: Annotated[int | None, Field(default=None, ge=16, le=7680)] = None,
                        height: Annotated[int | None, Field(default=None, ge=16, le=4320)] = None,
                        remove_audio: bool = False, wait: Wait = True, timeout_s: Timeout = 900) -> dict[str, Any]:
    """Format/Codec konvertieren (MP4/H.264, WebM/VP9, GIF mit Palette, Audio-Extraktion)."""
    return await _submit("/process/convert", {"source": check_ref(source), "format": format, "crf": crf, "fps": fps,
                                              "width": width, "height": height, "remove_audio": remove_audio}, wait, timeout_s)


@mcp.tool()
async def trim_video(source: AssetRef, start_s: Annotated[float, Field(ge=0)] = 0.0,
                     end_s: Annotated[float | None, Field(default=None, gt=0)] = None,
                     duration_s: Annotated[float | None, Field(default=None, gt=0)] = None,
                     wait: Wait = True) -> dict[str, Any]:
    """Video schneiden (Start/Ende oder Dauer)."""
    return await _submit("/process/trim", {"source": check_ref(source), "start_s": start_s, "end_s": end_s,
                                           "duration_s": duration_s}, wait, 900)


@mcp.tool()
async def extract_frames(source: AssetRef, fps: Annotated[float | None, Field(default=None, gt=0, le=120)] = None,
                         count: Annotated[int | None, Field(default=None, ge=1, le=5000)] = None,
                         start_s: Annotated[float, Field(ge=0)] = 0.0, format: Literal["png", "jpg", "webp"] = "png",
                         wait: Wait = True) -> dict[str, Any]:
    """Einzelbilder extrahieren (x Bilder pro Sekunde oder n gleichmäßig verteilte Frames)."""
    return await _submit("/process/extract_frames", {"source": check_ref(source), "fps": fps, "count": count,
                                                     "start_s": start_s, "format": format}, wait, 900)


Transition = Literal["none", "fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright", "fadeblack",
                     "fadewhite", "circleopen", "circleclose", "smoothleft", "smoothright", "zoomin", "pixelize", "radial"]


@mcp.tool()
async def merge_videos(sources: Annotated[list[AssetRef], Field(min_length=2, max_length=100)],
                       transition: Transition = "fade",
                       transition_duration: Annotated[float, Field(default=0.5, ge=0.1, le=5)] = 0.5,
                       width: Annotated[int | None, Field(default=None, ge=16, le=7680)] = None,
                       height: Annotated[int | None, Field(default=None, ge=16, le=4320)] = None,
                       fps: Annotated[float | None, Field(default=None, gt=0, le=120)] = None,
                       wait: Wait = True, timeout_s: Timeout = 1800) -> dict[str, Any]:
    """Clips zusammenfügen (normalisiert Auflösung/FPS/Audio) mit Übergängen (xfade)."""
    return await _submit("/process/merge", {"sources": [check_ref(s) for s in sources], "transition": transition,
                                            "transition_duration": transition_duration, "width": width, "height": height,
                                            "fps": fps}, wait, timeout_s)


@mcp.tool()
async def add_audio(video: AssetRef, audio: AssetRef, mode: Literal["replace", "mix"] = "replace",
                    volume: Annotated[float, Field(default=1.0, ge=0, le=4)] = 1.0,
                    fade_in_s: Annotated[float, Field(default=0.0, ge=0, le=30)] = 0.0,
                    fade_out_s: Annotated[float, Field(default=1.0, ge=0, le=30)] = 1.0,
                    normalize: bool = True, wait: Wait = True) -> dict[str, Any]:
    """Musik/Ton hinzufügen (ersetzen oder mischen), Loop auf Videolänge, Fades, Lautheitsnormalisierung (-16 LUFS)."""
    return await _submit("/process/add_audio", {"video": check_ref(video), "audio": check_ref(audio), "mode": mode,
                                                "volume": volume, "fade_in_s": fade_in_s, "fade_out_s": fade_out_s,
                                                "normalize": normalize}, wait, 900)


@mcp.tool()
async def add_subtitles(video: AssetRef,
                        subtitles: Annotated[list[dict[str, Any]] | str, Field(
                            description="Liste [{start_s, end_s, text}] oder Asset-ID/Pfad einer .srt/.vtt-Datei")],
                        burn_in: bool = True, font_size: Annotated[int, Field(default=28, ge=8, le=200)] = 28,
                        position: Literal["bottom", "top", "middle"] = "bottom", wait: Wait = True) -> dict[str, Any]:
    """Untertitel einbrennen (libass) oder als Spur einbetten (mov_text)."""
    subs = check_ref(subtitles) if isinstance(subtitles, str) else subtitles
    return await _submit("/process/add_subtitles", {"video": check_ref(video), "subtitles": subs, "burn_in": burn_in,
                                                    "style": {"font_size": font_size, "position": position}}, wait, 900)


@mcp.tool()
async def resize_video(source: AssetRef, aspect_ratio: Aspect, mode: Literal["blur", "crop", "pad"] = "blur",
                       wait: Wait = True, timeout_s: Timeout = 900) -> dict[str, Any]:
    """Seitenverhältnis ändern (z. B. 16:9 → 9:16) mit Blur-Hintergrund, Zuschnitt oder Balken."""
    return await _submit("/process/resize", {"source": check_ref(source), "aspect_ratio": aspect_ratio, "mode": mode},
                         wait, timeout_s)


@mcp.tool()
async def render_video(
    clips: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=200, description=(
        "Timeline: [{source: Asset, duration_s (für Bilder), start_s?, end_s?, ken_burns?: {zoom: in|out|none, pan: none|left|right|up|down}}]"))],
    width: Annotated[int, Field(default=1920, ge=16, le=7680)] = 1920,
    height: Annotated[int, Field(default=1080, ge=16, le=4320)] = 1080,
    fps: Annotated[float, Field(default=30, gt=0, le=120)] = 30,
    transition: Transition = "fade",
    transition_duration: Annotated[float, Field(default=0.6, ge=0.1, le=5)] = 0.6,
    audio: Annotated[dict[str, Any] | None, Field(default=None, description="{source, volume?, fade_in_s?, fade_out_s?, mode?}")] = None,
    subtitles: Annotated[list[dict[str, Any]] | str | None, Field(default=None)] = None,
    output_name: Annotated[str | None, Field(default=None, max_length=120)] = None,
    project: Project = None,
    wait: Wait = True,
    timeout_s: Timeout = 1800,
) -> dict[str, Any]:
    """Finales Video aus Timeline rendern: Bilder (Ken Burns) + Videos → Übergänge → Musik → Untertitel."""
    for c in clips:
        if not isinstance(c, dict) or "source" not in c:
            raise ToolError("Jeder Clip braucht 'source'")
        check_ref(str(c["source"]))
    if audio and audio.get("source"):
        check_ref(str(audio["source"]))
    return await _submit("/process/render", {"clips": clips, "width": width, "height": height, "fps": fps,
                                             "transition": transition, "transition_duration": transition_duration,
                                             "audio": audio, "subtitles": subtitles, "output_name": output_name,
                                             "project": project}, wait, timeout_s)


@mcp.tool()
async def create_title_card(title: Annotated[str, Field(min_length=1, max_length=200)],
                            subtitle: Annotated[str | None, Field(default=None, max_length=300)] = None,
                            duration_s: Annotated[float, Field(default=4.0, gt=0.5, le=60)] = 4.0,
                            width: Annotated[int, Field(default=1920, ge=16, le=7680)] = 1920,
                            height: Annotated[int, Field(default=1080, ge=16, le=4320)] = 1080,
                            background: Hex = "#0F172A", color: Hex = "#FFFFFF", accent: Hex = "#38BDF8",
                            wait: Wait = True) -> dict[str, Any]:
    """Animierte Titelkarte mit FFmpeg (funktioniert ohne Node.js/Remotion)."""
    return await _submit("/process/title_card", {"title": title, "subtitle": subtitle, "duration_s": duration_s,
                                                 "width": width, "height": height, "background": background,
                                                 "color": color, "accent": accent}, wait, 600)


@mcp.tool()
async def compress_video(source: AssetRef,
                         target_size_mb: Annotated[float | None, Field(default=None, gt=0.1, le=10000, description="Zielgröße (Bitrate wird berechnet)")] = None,
                         crf: Annotated[int, Field(default=28, ge=0, le=51, description="Qualität, wenn keine Zielgröße (höher = kleiner)")] = 28,
                         max_width: Annotated[int | None, Field(default=None, ge=16, le=7680)] = None,
                         wait: Wait = True, timeout_s: Timeout = 1800) -> dict[str, Any]:
    """Video verkleinern (Zielgröße in MB oder CRF, optional maximale Breite) – z. B. für Upload-Limits."""
    return await _submit("/process/compress", {"source": check_ref(source), "target_size_mb": target_size_mb, "crf": crf,
                                               "max_width": max_width}, wait, timeout_s)


@mcp.tool()
async def interpolate_video(source: AssetRef, target_fps: Annotated[float, Field(default=48, gt=1, le=240)] = 48,
                            mode: Literal["motion", "blend"] = "motion", wait: Wait = True,
                            timeout_s: Timeout = 1800) -> dict[str, Any]:
    """Frame-Interpolation (FFmpeg minterpolate, bewegungskompensiert) für flüssigere KI-Clips."""
    return await _submit("/process/interpolate", {"source": check_ref(source), "target_fps": target_fps, "mode": mode},
                         wait, timeout_s)


# ---- Motion design, 3D, brand -------------------------------------------------------


@mcp.tool()
async def render_motion_graphics(
    composition: Literal["TitleIntro", "LowerThird", "SocialPost", "KineticText", "Outro"],
    props: Annotated[dict[str, Any], Field(description=(
        "TitleIntro{title,subtitle,logo}, LowerThird{name,role,transparent}, SocialPost{image,headline,subline,cta,brandName}, "
        "KineticText{phrases[]}, Outro{headline,cta,url,logo}; immer optional: background,textColor,accent (Hex)"))],
    width: Annotated[int | None, Field(default=None, ge=64, le=3840)] = None,
    height: Annotated[int | None, Field(default=None, ge=64, le=3840)] = None,
    duration_s: Annotated[float | None, Field(default=None, gt=0.2, le=120)] = None,
    fps: Annotated[int, Field(default=30, ge=1, le=60)] = 30,
    transparent: bool = False,
    project: Project = None,
    wait: Wait = True,
    timeout_s: Timeout = 900,
) -> dict[str, Any]:
    """Motion Graphics mit Remotion rendern (Intro, Bauchbinde, Social-Clip, kinetische Typo, Outro)."""
    for key in ("logo", "image"):
        if props.get(key):
            check_ref(str(props[key]))
    return await _submit("/motion/render", {"composition": composition, "props": props, "width": width, "height": height,
                                            "duration_s": duration_s, "fps": fps, "transparent": transparent,
                                            "project": project}, wait, timeout_s)


@mcp.tool()
async def render_3d(
    template: Literal["product_turntable", "text_3d", "logo_extrude"],
    params: Annotated[dict[str, Any], Field(default_factory=dict, description=(
        "product_turntable{model_path?,product,color,material,background,degrees}; text_3d{text,color,material,background,"
        "accent,extrude,bevel,animation}; logo_extrude{svg_path,color?,material,background,extrude,bevel,degrees}"))],
    width: Annotated[int, Field(default=1280, ge=64, le=3840)] = 1280,
    height: Annotated[int, Field(default=720, ge=64, le=2160)] = 720,
    frames: Annotated[int, Field(default=72, ge=1, le=1200)] = 72,
    fps: Annotated[int, Field(default=24, ge=1, le=60)] = 24,
    samples: Annotated[int, Field(default=48, ge=1, le=4096)] = 48,
    output: Literal["video", "frames", "still"] = "video",
    engine: Literal["CYCLES", "EEVEE"] = "CYCLES",
    device: Literal["auto", "cpu", "gpu"] = "auto",
    transparent: bool = False,
    save_blend: bool = False,
    project: Project = None,
    wait: Wait = True,
    timeout_s: Timeout = 1800,
) -> dict[str, Any]:
    """3D-Szene mit Blender (headless) rendern: Produkt-Turntable, 3D-Text oder SVG-Logo-Extrusion.
    EEVEE braucht eine GPU/OpenGL; CYCLES läuft überall (device auto nutzt CUDA/OptiX/HIP/Metal falls vorhanden)."""
    for key in ("model_path", "svg_path", "font_path"):
        if params.get(key):
            check_ref(str(params[key]))
    return await _submit("/render3d/render", {"template": template, "params": params, "width": width, "height": height,
                                              "frames": frames, "fps": fps, "samples": samples, "output": output,
                                              "engine": engine, "device": device, "transparent": transparent,
                                              "save_blend": save_blend, "project": project}, wait, timeout_s)


@mcp.tool()
async def create_brand_guidelines(
    brand_name: Annotated[str, Field(min_length=1, max_length=80)],
    tagline: str | None = None, mission: str | None = None, audience: str | None = None, positioning: str | None = None,
    values: Annotated[list[str] | None, Field(default=None, max_length=12)] = None,
    voice: Annotated[list[str] | None, Field(default=None, max_length=12)] = None,
    palette: Annotated[list[str] | None, Field(default=None, max_length=16, description="Hex-Farben (Rollen automatisch)")] = None,
    heading_font: str = "Inter", body_font: str = "Inter",
    logos: Annotated[list[AssetRef] | None, Field(default=None, max_length=12)] = None,
    imagery: Annotated[list[AssetRef] | None, Field(default=None, max_length=12)] = None,
    imagery_style: str | None = None,
    dos: list[str] | None = None, donts: list[str] | None = None,
) -> dict[str, Any]:
    """Brand Guidelines als HTML (offline, Bilder eingebettet) + Markdown + brand.json erzeugen."""
    for ref in (logos or []) + (imagery or []):
        check_ref(ref)
    return await _submit("/brand/guidelines", {
        "brand_name": brand_name, "tagline": tagline, "mission": mission, "audience": audience, "positioning": positioning,
        "values": values or [], "voice": voice or [], "palette": palette or [], "heading_font": heading_font,
        "body_font": body_font, "logos": logos or [], "imagery": imagery or [], "imagery_style": imagery_style,
        "dos": dos or [], "donts": donts or []}, True, 300)


@mcp.tool()
async def suggest_typography(keywords: Annotated[str, Field(max_length=300, description="z. B. 'modern tech startup'")],
                             limit: Annotated[int, Field(default=3, ge=1, le=10)] = 3) -> dict[str, Any]:
    """Schriftpaarungen (freie Google Fonts, SIL OFL) passend zu Stichworten."""
    return await backend.request("GET", "/brand/typography", params={"keywords": keywords, "limit": limit})


# ---- Assets --------------------------------------------------------------------------


@mcp.tool()
async def list_assets(kind: Annotated[str | None, Field(default=None, description="image, video, audio, model3d, document")] = None,
                      limit: Annotated[int, Field(default=20, ge=1, le=200)] = 20,
                      sort: Literal["newest", "oldest", "name", "size", "rating"] = "newest") -> dict[str, Any]:
    """Neueste Assets (Bilder, Videos, Audio, 3D, Dokumente)."""
    data = await backend.request("GET", "/assets", params=_drop_none({"kind": kind, "limit": limit, "sort": sort}))
    return {"total": data["total"], "assets": [await _compact_asset(a) | {"tags": a["tags"], "favorite": a["favorite"],
                                                                          "prompt": (a.get("prompt") or "")[:160]}
                                               for a in data["assets"]]}


@mcp.tool()
async def search_assets(query: Annotated[str | None, Field(default=None, max_length=200)] = None,
                        kind: str | None = None, tags: Annotated[list[str] | None, Field(default=None, max_length=10)] = None,
                        favorite: bool | None = None, project: str | None = None,
                        limit: Annotated[int, Field(default=30, ge=1, le=200)] = 30) -> dict[str, Any]:
    """Assets nach Text (Prompt, Dateiname, Tags, Modell, Notizen), Typ, Tags, Favoriten und Projekt durchsuchen."""
    params = _drop_none({"q": query, "kind": kind, "tags": ",".join(tags) if tags else None, "favorite": favorite,
                         "project": project, "limit": limit})
    data = await backend.request("GET", "/assets", params=params)
    return {"total": data["total"], "assets": [await _compact_asset(a) | {"tags": a["tags"], "prompt": (a.get("prompt") or "")[:160]}
                                               for a in data["assets"]]}


@mcp.tool()
async def get_asset_metadata(asset_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]) -> dict[str, Any]:
    """Vollständige Metadaten inkl. Prompt, Seed, Parameter, Qualitätsbericht und exaktem ComfyUI-Workflow (Sidecar)."""
    data = await backend.request("GET", f"/assets/{asset_id}")
    data["file"] = str((await backend.assets_root()) / data["path"])
    sidecar = data.get("sidecar") or {}
    if sidecar.get("workflow"):
        data["workflow_nodes"] = len(sidecar["workflow"])
    return data


@mcp.tool()
async def tag_asset(asset_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")],
                    add_tags: list[str] | None = None, remove_tags: list[str] | None = None,
                    favorite: bool | None = None, rating: Annotated[int | None, Field(default=None, ge=0, le=5)] = None,
                    notes: Annotated[str | None, Field(default=None, max_length=4000)] = None,
                    project: str | None = None) -> dict[str, Any]:
    """Tags, Favorit, Bewertung, Notizen oder Projekt eines Assets ändern."""
    return await _compact_asset(await backend.request("PATCH", f"/assets/{asset_id}", json=_drop_none({
        "add_tags": add_tags, "remove_tags": remove_tags, "favorite": favorite, "rating": rating, "notes": notes,
        "project": project})))


@mcp.tool()
async def organize_assets(rule: Literal["by_kind", "by_project", "by_date"] = "by_kind",
                          asset_ids: list[str] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Assets in Ordnerstruktur sortieren. Standard: Dry-Run (zeigt nur geplante Verschiebungen). Nur nach Bestätigung dry_run=false."""
    return await backend.request("POST", "/assets/organize", json=_drop_none({"rule": rule, "asset_ids": asset_ids,
                                                                              "dry_run": dry_run}))


@mcp.tool()
async def rescan_assets() -> dict[str, Any]:
    """Manuell nach assets/ kopierte Dateien indizieren (z. B. Referenzbilder in assets/references)."""
    return await backend.request("POST", "/assets/rescan", timeout=120)


# ---- Quality -----------------------------------------------------------------------


@mcp.tool()
async def analyze_image(source: AssetRef, min_width: int | None = None, min_height: int | None = None,
                        expected_aspect: Aspect | None = None,
                        purpose: Annotated[str | None, Field(default=None, description="z. B. logo, photo, graphic")] = None,
                        preset: Annotated[str | None, Field(default=None, description="z. B. youtube_thumbnail")] = None
                        ) -> dict[str, Any]:
    """Bildqualität prüfen: Auflösung, Schärfe, Belichtung, Clipping, Kontrast, Rauschen, Leere – Score 0–100 mit Befunden."""
    return await _submit("/quality/analyze", {"source": check_ref(source), "min_width": min_width, "min_height": min_height,
                                              "expected_aspect": expected_aspect, "purpose": purpose, "preset": preset},
                         True, 300)


@mcp.tool()
async def analyze_video(source: AssetRef, expected_fps: float | None = None, expected_duration_s: float | None = None,
                        expected_aspect: Aspect | None = None, require_audio: bool = False,
                        min_width: int | None = None, min_height: int | None = None) -> dict[str, Any]:
    """Videoqualität prüfen: Streams, Auflösung, FPS, Dauer, Audio, schwarze/eingefrorene Segmente, Schärfe, Flackern."""
    return await _submit("/quality/analyze", {"source": check_ref(source), "expected_fps": expected_fps,
                                              "expected_duration_s": expected_duration_s, "expected_aspect": expected_aspect,
                                              "require_audio": require_audio, "min_width": min_width,
                                              "min_height": min_height}, True, 600)


@mcp.tool()
async def validate_resolution(source: AssetRef | None = None, width: int | None = None, height: int | None = None,
                              preset: Annotated[str | None, Field(default=None, description="z. B. youtube_thumbnail, instagram_story, tiktok")] = None,
                              aspect: Aspect | None = None, exact: bool = False) -> dict[str, Any]:
    """Auflösung/Seitenverhältnis gegen Plattform-Presets oder eigene Vorgaben prüfen."""
    return await backend.request("POST", "/quality/validate-resolution", json=_drop_none({
        "asset": check_ref(source) if source else None, "width": width, "height": height, "preset": preset,
        "aspect": aspect, "exact": exact}))


@mcp.tool()
async def generate_quality_report(assets: Annotated[list[AssetRef], Field(min_length=1, max_length=100)],
                                  title: Annotated[str, Field(default="Qualitätsbericht", max_length=120)] = "Qualitätsbericht",
                                  preset: str | None = None, project: Project = None) -> dict[str, Any]:
    """Qualitätsbericht (Markdown + JSON in assets/exports/reports) für mehrere Assets erstellen."""
    return await _submit("/quality/report", {"assets": [check_ref(a) for a in assets], "title": title, "preset": preset,
                                             "project": project}, True, 900)


def main() -> None:
    _setup_logging()
    log.info("MCP server starting (backend %s)", BACKEND_URL)
    mcp.run("stdio")


if __name__ == "__main__":
    main()

