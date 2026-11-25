"""Remotion motion-graphics provider (React compositions in engines/remotion).

License note: Remotion is free for individuals and companies with up to 3
employees; larger companies need a company license (https://www.remotion.dev/license).
When Remotion is unavailable, workflows fall back to FFmpeg title cards.
"""

from __future__ import annotations

import asyncio
import collections
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.errors import ExternalProcessError, StudioTimeoutError, ToolNotFoundError, ValidationError
from backend.jobs.context import JobContext

from .base import Capability, GenerationResult, MotionProvider, ProviderHealth

COMPOSITIONS: dict[str, dict[str, Any]] = {
    "TitleIntro": {
        "description": "Animierter Titel mit Akzentlinie, optionalem Logo und Untertitel (Intro).",
        "props": {"title": "string*", "subtitle": "string", "logo": "file"},
        "default_size": [1920, 1080], "default_seconds": 4,
    },
    "LowerThird": {
        "description": "Bauchbinde (Name + Rolle), optional transparent für den Schnitt.",
        "props": {"name": "string*", "role": "string", "transparent": "bool"},
        "default_size": [1920, 1080], "default_seconds": 5,
    },
    "SocialPost": {
        "description": "Social-Media-Clip: Bild mit Zoom, Headline, Subline und CTA-Button.",
        "props": {"image": "file", "headline": "string*", "subline": "string", "cta": "string", "brandName": "string"},
        "default_size": [1080, 1920], "default_seconds": 6,
    },
    "KineticText": {
        "description": "Kinetische Typografie: Phrasen nacheinander mit Pop-Animation (Hooks, Reels).",
        "props": {"phrases": "string[]*"},
        "default_size": [1080, 1920], "default_seconds": 4.5,
    },
    "Outro": {
        "description": "Outro mit Logo, Headline, CTA und URL.",
        "props": {"headline": "string", "cta": "string", "url": "string", "logo": "file"},
        "default_size": [1920, 1080], "default_seconds": 4,
    },
}
COMMON_PROPS = {"background", "textColor", "accent", "fontFamily"}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


class MotionRenderRequest(BaseModel):
    composition: Literal["TitleIntro", "LowerThird", "SocialPost", "KineticText", "Outro"]
    props: dict[str, Any] = Field(default_factory=dict)
    width: int | None = Field(None, ge=64, le=3840)
    height: int | None = Field(None, ge=64, le=3840)
    fps: int = Field(30, ge=1, le=60)
    duration_s: float | None = Field(None, gt=0.2, le=120)
    transparent: bool = False


class RemotionProvider(MotionProvider):
    def __init__(self, info: Any, settings: Any, shared: dict[str, Any] | None = None) -> None:
        super().__init__(info, settings, shared)
        self.project = settings.resolve(settings.paths.remotion_dir)
        self.npx = settings.remotion.npx_path
        self.timeout = settings.remotion.timeout_s

    def get_capabilities(self) -> set[Capability]:
        return {Capability.MOTION_RENDER}

    def installed(self) -> bool:
        return (self.project / "node_modules" / "@remotion" / "cli").is_dir()

    async def health(self) -> ProviderHealth:
        if not shutil.which(self.npx):
            return ProviderHealth(available=False, detail="Node.js/npx nicht gefunden")
        if not self.installed():
            return ProviderHealth(available=False, detail=f"Abhängigkeiten fehlen: cd {self.project} && npm install")
        version = None
        pkg = self.project / "node_modules" / "remotion" / "package.json"
        if pkg.is_file():
            version = json.loads(pkg.read_text()).get("version")
        return ProviderHealth(available=True, detail=f"Remotion {version} · Lizenz beachten (remotion.dev/license)",
                              version=version)

    async def get_compositions(self) -> list[dict[str, Any]]:
        return [{"id": k, **v} for k, v in COMPOSITIONS.items()]

    def _validate(self, req: MotionRenderRequest) -> None:
        spec = COMPOSITIONS[req.composition]["props"]
        allowed = set(spec) | COMMON_PROPS
        unknown = set(req.props) - allowed
        if unknown:
            raise ValidationError(f"Unbekannte Props für {req.composition}: {sorted(unknown)}", details={"allowed": sorted(allowed)})
        for name, kind in spec.items():
            if kind.endswith("*") and not req.props.get(name):
                raise ValidationError(f"{req.composition}: Prop '{name}' ist erforderlich")
        for key in ("background", "textColor", "accent"):
            if key in req.props and not _HEX.match(str(req.props[key])):
                raise ValidationError(f"{key} muss eine Hex-Farbe sein (#RRGGBB)")
        if "phrases" in req.props and (not isinstance(req.props["phrases"], list) or len(req.props["phrases"]) > 30):
            raise ValidationError("phrases muss eine Liste mit max. 30 Einträgen sein")

    async def render(self, req: MotionRenderRequest, ctx: JobContext) -> GenerationResult:
        if not self.installed():
            raise ToolNotFoundError(f"Remotion ist nicht installiert: cd {self.project} && npm install")
        npx = shutil.which(self.npx)
        if not npx:
            raise ToolNotFoundError("npx (Node.js) nicht gefunden")
        self._validate(req)
        spec = COMPOSITIONS[req.composition]
        run_id = uuid.uuid4().hex[:10]
        public_dir = self.project / "public" / "acs" / run_id
        props = dict(req.props)
        try:
            # Local files are copied into public/ so the bundler can serve them via staticFile().
            for name, kind in spec["props"].items():
                if kind.startswith("file") and props.get(name):
                    src = Path(str(props[name]))
                    if not src.is_file():
                        raise ValidationError(f"Datei für '{name}' nicht gefunden")
                    public_dir.mkdir(parents=True, exist_ok=True)
                    dst = public_dir / f"{name}{src.suffix.lower()}"
                    shutil.copyfile(src, dst)
                    props[name] = f"acs/{run_id}/{dst.name}"
            w, h = req.width or spec["default_size"][0], req.height or spec["default_size"][1]
            props.update({"width": w, "height": h, "fps": req.fps,
                          "durationInSeconds": req.duration_s or spec["default_seconds"]})
            if req.composition == "LowerThird":
                props.setdefault("transparent", req.transparent)
            props_file = public_dir.parent / f"{run_id}.props.json"
            props_file.parent.mkdir(parents=True, exist_ok=True)
            props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
            suffix = ".mov" if req.transparent else ".mp4"
            out = ctx.output_dir / f"{req.composition.lower()}_{run_id}{suffix}"
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            args = [npx, "remotion", "render", "src/index.ts", req.composition, str(out.resolve()),
                    f"--props={props_file.resolve()}"]
            if req.transparent:
                args += ["--image-format=png", "--pixel-format=yuva444p10le", "--codec=prores", "--prores-profile=4444"]
            await self._run(args, ctx)
            if not out.is_file():
                raise ExternalProcessError("Remotion hat keine Ausgabedatei erzeugt")
        finally:
            shutil.rmtree(public_dir, ignore_errors=True)
            (self.project / "public" / "acs" / f"{run_id}.props.json").unlink(missing_ok=True)
        return GenerationResult(files=[out], provider=self.name, model=f"remotion-{req.composition}",
                                parameters=req.model_dump(), metadata={"license_note": self.info.license_note})

    async def _run(self, args: list[str], ctx: JobContext) -> None:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(self.project), stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        tail: collections.deque[str] = collections.deque(maxlen=40)
        pattern = re.compile(r"(Rendered|Encoded)\s+(\d+)/(\d+)")

        async def read() -> None:
            assert proc.stdout
            async for raw in proc.stdout:
                for line in raw.decode(errors="replace").replace("\r", "\n").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    tail.append(line)
                    m = pattern.search(line)
                    if m:
                        done, total = int(m.group(2)), max(1, int(m.group(3)))
                        base = 0.05 if m.group(1) == "Rendered" else 0.8
                        span = 0.75 if m.group(1) == "Rendered" else 0.19
                        ctx.report(base + span * done / total, f"Remotion: {m.group(1)} {done}/{total}")

        try:
            await asyncio.wait_for(asyncio.gather(read(), proc.wait()), timeout=self.timeout)
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise StudioTimeoutError("Remotion-Rendering hat das Zeitlimit überschritten") from None
        if proc.returncode != 0:
            raise ExternalProcessError("Remotion-Fehler: " + " | ".join(list(tail)[-6:]), details={"log_tail": list(tail)})
