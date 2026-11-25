"""Mock providers – deterministic synthetic media WITHOUT any AI model.

Used by the test-suite and for demos/workflow development on machines without a
GPU or without installed models. Outputs are clearly watermarked "MOCK". The
mock provider is ``explicit_only``: it is never chosen automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from backend.core.fonts import find_font
from backend.jobs.context import JobContext

from .base import (
    Capability,
    GenerationResult,
    ImageEditRequest,
    ImageGenerateRequest,
    ImageProvider,
    InpaintRequest,
    ModelInfo,
    OutpaintRequest,
    ProviderHealth,
    UpscaleRequest,
    VideoGenerateRequest,
    VideoProvider,
)


def _palette(text: str) -> list[tuple[int, int, int]]:
    digest = hashlib.sha256(text.encode()).digest()
    return [(digest[i], digest[i + 1], digest[i + 2]) for i in range(0, 15, 3)]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font("sans-bold")
    if path:
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def render_mock_image(prompt: str, seed: int, width: int, height: int, label: str = "MOCK") -> Image.Image:
    rng = random.Random(f"{prompt}|{seed}")
    colors = _palette(f"{prompt}|{seed}")
    img = Image.new("RGB", (width, height), colors[0])
    draw = ImageDraw.Draw(img)
    for y in range(height):  # vertical gradient
        t = y / max(1, height - 1)
        c = tuple(int(colors[0][i] * (1 - t) + colors[1][i] * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=c)
    for _ in range(12):
        r = rng.randint(min(width, height) // 12, min(width, height) // 3)
        x, y = rng.randint(0, width), rng.randint(0, height)
        col = colors[rng.randint(2, 4)]
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(*col,), outline=None)
    img = img.filter(ImageFilter.GaussianBlur(radius=max(1, min(width, height) // 80)))
    draw = ImageDraw.Draw(img)
    size = max(12, width // 22)
    font = _font(size)
    text = (prompt[:70] + "…") if len(prompt) > 70 else prompt
    draw.rectangle([0, height - size * 3, width, height], fill=(0, 0, 0))
    draw.text((size // 2, height - size * 2.6), f"{label} · seed {seed}", fill=(255, 200, 0), font=font)
    draw.text((size // 2, height - size * 1.4), text, fill=(255, 255, 255), font=_font(max(10, int(size * 0.7))))
    return img


class MockImageProvider(ImageProvider):
    def get_capabilities(self) -> set[Capability]:
        return {Capability.TEXT_TO_IMAGE, Capability.IMAGE_TO_IMAGE, Capability.INPAINT, Capability.OUTPAINT,
                Capability.UPSCALE}

    async def health(self) -> ProviderHealth:
        return ProviderHealth(available=True, detail="Synthetische Testbilder (keine KI)")

    async def get_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="mock-image", name="Mock Image (synthetisch)", type="image", provider=self.name,
                          tasks=["text_to_image", "image_to_image", "inpaint", "outpaint", "upscale"])]

    async def generate(self, req: ImageGenerateRequest, ctx: JobContext) -> GenerationResult:
        width, height = req.width or 768, req.height or 768
        if req.aspect_ratio and not (req.width and req.height):
            a, b = (int(x) for x in req.aspect_ratio.split(":"))
            width, height = (768, int(768 * b / a) // 8 * 8) if a >= b else (int(768 * a / b) // 8 * 8, 768)
        seed = req.seed if req.seed is not None else random.randint(0, 2**31)
        files = []
        for i in range(req.batch_size):
            ctx.check_cancelled()
            await ctx.progress(i / req.batch_size, f"Mock-Bild {i + 1}/{req.batch_size}")
            img = await asyncio.to_thread(render_mock_image, req.prompt, seed + i, width, height)
            path = ctx.output_dir / f"mock_{seed + i}.png"
            await asyncio.to_thread(img.save, path)
            files.append(path)
            await asyncio.sleep(0.01)
        return GenerationResult(files=files, provider=self.name, model="mock-image", seed=seed,
                                parameters={"width": width, "height": height, "batch_size": req.batch_size})

    async def _transform(self, source: str, ctx: JobContext, op: str, seed: int | None) -> GenerationResult:
        with Image.open(source) as im:
            im = im.convert("RGB")
            if op == "edit":
                im = ImageOps.posterize(im, 3).filter(ImageFilter.SMOOTH_MORE)
            elif op == "inpaint":
                im = im.filter(ImageFilter.GaussianBlur(6))
            path = ctx.output_dir / f"mock_{op}_{Path(source).stem}.png"
            im.save(path)
        return GenerationResult(files=[path], provider=self.name, model="mock-image", seed=seed, parameters={"op": op})

    async def edit(self, req: ImageEditRequest, ctx: JobContext) -> GenerationResult:
        return await self._transform(req.source, ctx, "edit", req.seed)

    async def inpaint(self, req: InpaintRequest, ctx: JobContext) -> GenerationResult:
        return await self._transform(req.source, ctx, "inpaint", req.seed)

    async def outpaint(self, req: OutpaintRequest, ctx: JobContext) -> GenerationResult:
        with Image.open(req.source) as im:
            im = im.convert("RGB")
            canvas = Image.new("RGB", (im.width + req.left + req.right, im.height + req.top + req.bottom), (40, 40, 40))
            canvas.paste(im.resize(canvas.size).filter(ImageFilter.GaussianBlur(25)))
            canvas.paste(im, (req.left, req.top))
            path = ctx.output_dir / f"mock_outpaint_{Path(req.source).stem}.png"
            canvas.save(path)
        return GenerationResult(files=[path], provider=self.name, model="mock-image", parameters=req.model_dump())

    async def upscale(self, req: UpscaleRequest, ctx: JobContext) -> GenerationResult:
        with Image.open(req.source) as im:
            out = im.resize((int(im.width * req.scale), int(im.height * req.scale)), Image.Resampling.LANCZOS)
            path = ctx.output_dir / f"mock_upscale_{Path(req.source).stem}.png"
            out.save(path)
        return GenerationResult(files=[path], provider=self.name, model="lanczos", parameters={"scale": req.scale})


class MockVideoProvider(VideoProvider):
    """Synthetic animated clips encoded with FFmpeg (requires ffmpeg on PATH)."""

    def get_capabilities(self) -> set[Capability]:
        return {Capability.TEXT_TO_VIDEO, Capability.IMAGE_TO_VIDEO}

    async def health(self) -> ProviderHealth:
        import shutil

        ok = shutil.which(self.settings.ffmpeg.ffmpeg_path) is not None
        return ProviderHealth(available=ok, detail="Synthetische Testvideos (FFmpeg)" if ok else "FFmpeg fehlt")

    async def get_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="mock-video", name="Mock Video (synthetisch)", type="video", provider=self.name,
                          tasks=["text_to_video", "image_to_video"])]

    async def _encode(self, frames_dir: Path, fps: int, out: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            self.settings.ffmpeg.ffmpeg_path, "-y", "-v", "error", "-framerate", str(fps), "-i",
            str(frames_dir / "f_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            from backend.core.errors import ExternalProcessError

            raise ExternalProcessError(f"Mock video encode failed: {err.decode(errors='replace')[-300:]}")

    async def generate(self, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        fps = req.fps or 12
        frames = req.frames or int((req.duration_s or 2) * fps)
        frames = max(4, min(frames, 240))
        width = (req.width or 480) // 2 * 2
        height = (req.height or 272) // 2 * 2
        seed = req.seed if req.seed is not None else random.randint(0, 2**31)
        base = None
        if req.image:
            with Image.open(req.image) as im:
                base = ImageOps.fit(im.convert("RGB"), (int(width * 1.2), int(height * 1.2)))
        else:
            base = render_mock_image(req.prompt, seed, int(width * 1.2), int(height * 1.2), label="MOCK VIDEO")
        tmp = ctx.output_dir / f".mock_frames_{seed}"
        tmp.mkdir(parents=True, exist_ok=True)
        for i in range(frames):
            ctx.check_cancelled()
            t = i / max(1, frames - 1)
            dx = int((base.width - width) * (0.5 + 0.5 * math.sin(t * math.pi)))
            dy = int((base.height - height) * t)
            frame = base.crop((dx, dy, dx + width, dy + height))
            await asyncio.to_thread(frame.save, tmp / f"f_{i:04d}.png")
            if i % 4 == 0:
                await ctx.progress(0.8 * t, f"Frame {i + 1}/{frames}")
        out = ctx.output_dir / f"mock_video_{seed}.mp4"
        await self._encode(tmp, fps, out)
        for f in tmp.glob("*.png"):
            f.unlink()
        tmp.rmdir()
        return GenerationResult(files=[out], provider=self.name, model="mock-video", seed=seed,
                                parameters={"width": width, "height": height, "frames": frames, "fps": fps,
                                            "image_to_video": bool(req.image)})

    async def image_to_video(self, req: VideoGenerateRequest, ctx: JobContext) -> GenerationResult:
        return await self.generate(req, ctx)


def mock_info(name: str = "mock") -> Any:
    from .base import ProviderInfo

    return ProviderInfo(name=name, display_name="Mock", roles=["image", "video"], explicit_only=True)


__all__ = ["MockImageProvider", "MockVideoProvider", "mock_info", "render_mock_image"]
