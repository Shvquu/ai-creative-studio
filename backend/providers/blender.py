"""Blender 3D render provider (headless, Blender Python API).

Runs the scripts in ``engines/blender/scripts`` with
``blender --background --factory-startup --python <script> -- --params <json>``.
Frames are encoded to MP4 with FFmpeg afterwards.
"""

from __future__ import annotations

import asyncio
import collections
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.errors import ExternalProcessError, StudioTimeoutError, ToolNotFoundError, ValidationError
from backend.jobs.context import JobContext

from .base import Capability, GenerationResult, ProviderHealth, Render3DProvider

TEMPLATES: dict[str, dict[str, Any]] = {
    "product_turntable": {
        "script": "product_turntable.py",
        "name": "Produkt-Turntable",
        "description": "Studio-Set mit 3-Punkt-Licht und 360°-Kamerafahrt. Eigenes 3D-Modell (.glb/.obj/.fbx/.stl) "
                       "oder Primitive (bottle, box, can, sphere, torus).",
        "params": ["model_path", "product", "color", "material", "background", "degrees", "camera_distance"],
    },
    "text_3d": {
        "script": "text_3d.py",
        "name": "3D-Typografie",
        "description": "Extrudierter 3D-Text mit Animation (rise, spin, zoom) für Intros und Titel.",
        "params": ["text", "font_path", "color", "material", "background", "accent", "extrude", "bevel", "animation"],
    },
    "logo_extrude": {
        "script": "logo_extrude.py",
        "name": "3D-Logo aus SVG",
        "description": "Importiert ein SVG-Logo, extrudiert es (Originalfarben bleiben erhalten) und rendert eine Kamerafahrt.",
        "params": ["svg_path", "color", "material", "background", "extrude", "bevel", "degrees"],
    },
}


class Render3DRequest(BaseModel):
    template: Literal["product_turntable", "text_3d", "logo_extrude"] = "product_turntable"
    params: dict[str, Any] = Field(default_factory=dict)
    width: int = Field(1280, ge=64, le=3840)
    height: int = Field(720, ge=64, le=2160)
    fps: int = Field(24, ge=1, le=60)
    frames: int = Field(72, ge=1, le=1200)
    samples: int = Field(48, ge=1, le=4096)
    engine: Literal["CYCLES", "EEVEE"] = "CYCLES"
    device: Literal["auto", "cpu", "gpu"] = "auto"
    output: Literal["video", "frames", "still"] = "video"
    transparent: bool = False
    save_blend: bool = False


class BlenderProvider(Render3DProvider):
    def __init__(self, info: Any, settings: Any, shared: dict[str, Any] | None = None) -> None:
        super().__init__(info, settings, shared)
        self.blender = settings.blender.blender_path
        self.timeout = settings.blender.timeout_s
        self.scripts_dir = settings.resolve(settings.paths.blender_scripts_dir)

    def get_capabilities(self) -> set[Capability]:
        return {Capability.RENDER_3D}

    def _exe(self) -> str:
        exe = shutil.which(self.blender) or (self.blender if Path(self.blender).is_file() else None)
        if not exe:
            raise ToolNotFoundError(
                f"Blender nicht gefunden ('{self.blender}'). Installieren (blender.org) und ggf. "
                "ACS__BLENDER__BLENDER_PATH setzen."
            )
        return exe

    async def health(self) -> ProviderHealth:
        try:
            exe = self._exe()
        except ToolNotFoundError as exc:
            return ProviderHealth(available=False, detail=exc.message)
        proc = await asyncio.create_subprocess_exec(exe, "--version", stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return ProviderHealth(available=False, detail="blender --version timed out")
        first = (out.decode(errors="replace").splitlines() or [""])[0]
        return ProviderHealth(available=proc.returncode == 0, detail=first, version=first.replace("Blender", "").strip() or None)

    async def get_templates(self) -> list[dict[str, Any]]:
        return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "script"}} for k, v in TEMPLATES.items()]

    async def render(self, req: Render3DRequest, ctx: JobContext) -> GenerationResult:
        tpl = TEMPLATES[req.template]
        script = self.scripts_dir / tpl["script"]
        if not script.is_file():
            raise ToolNotFoundError(f"Blender-Skript fehlt: {script}")
        unknown = set(req.params) - set(tpl["params"])
        if unknown:
            raise ValidationError(f"Unbekannte Parameter für {req.template}: {sorted(unknown)}",
                                  details={"allowed": tpl["params"]})
        for key in ("model_path", "svg_path", "font_path"):
            if key in req.params and not Path(str(req.params[key])).is_file():
                raise ValidationError(f"{key}: Datei nicht gefunden")
        if req.template == "logo_extrude" and "svg_path" not in req.params:
            raise ValidationError("logo_extrude benötigt params.svg_path")

        run_dir = ctx.output_dir / f"blender_{req.template}_{uuid.uuid4().hex[:6]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        params = {
            **req.params,
            "output_dir": str(run_dir),
            "resolution": [req.width, req.height],
            "fps": req.fps,
            "frames": 1 if req.output == "still" else req.frames,
            "samples": req.samples,
            "engine": req.engine,
            "device": req.device,
            "output": "still" if req.output == "still" else "frames",
            "transparent": req.transparent,
            "save_blend": req.save_blend,
        }
        params_file = run_dir / "params.json"
        params_file.write_text(json.dumps(params, indent=2), encoding="utf-8")
        await self._run_blender(script, params_file, ctx, span=(0.0, 0.9 if req.output == "video" else 1.0))
        result_file = run_dir / "result.json"
        if not result_file.is_file():
            raise ExternalProcessError("Blender hat kein Ergebnis geschrieben (result.json fehlt)")
        result = json.loads(result_file.read_text(encoding="utf-8"))
        files = [Path(f) for f in result["files"]]
        if req.output == "video":
            from .ffmpeg import FFmpegProvider, SequenceRequest

            ff = FFmpegProvider(self.info, self.settings)
            child = ctx.child(0.9, 1.0, "Encoding")
            encoded = await ff.encode_sequence(SequenceRequest(directory=str(run_dir), fps=req.fps), child)
            target = ctx.output_dir / f"{req.template}_{uuid.uuid4().hex[:6]}.mp4"
            encoded.files[0].rename(target)
            for f in files:
                f.unlink(missing_ok=True)
            files = [target]
        if req.save_blend and (run_dir / "scene.blend").is_file():
            files.append(run_dir / "scene.blend")
        return GenerationResult(files=files, provider=self.name, model=f"blender-{req.template}",
                                parameters=req.model_dump(), metadata={"blender": result.get("blender"),
                                                                       "engine": result.get("engine")})

    async def _run_blender(self, script: Path, params_file: Path, ctx: JobContext, span: tuple[float, float]) -> None:
        cmd = [self._exe(), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script),
               "--", "--params", str(params_file)]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        tail: collections.deque[str] = collections.deque(maxlen=40)

        async def read() -> None:
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                tail.append(line)
                if line.startswith("ACS_PROGRESS"):
                    try:
                        _, done, total = line.split()
                        frac = int(done) / max(1, int(total))
                    except ValueError:
                        continue
                    ctx.report(span[0] + (span[1] - span[0]) * frac, f"Blender rendert Frame {done}/{total}")

        try:
            await asyncio.wait_for(asyncio.gather(read(), proc.wait()), timeout=self.timeout)
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise StudioTimeoutError(f"Blender hat das Zeitlimit ({int(self.timeout)} s) überschritten") from None
        if proc.returncode != 0:
            errors = [ln for ln in tail if "Error" in ln or "Traceback" in ln or "SystemExit" in ln][-5:]
            raise ExternalProcessError("Blender-Fehler: " + (" | ".join(errors) or " | ".join(list(tail)[-5:])),
                                       details={"log_tail": list(tail)})
