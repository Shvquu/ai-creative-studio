"""Local CPU image tools (no AI model needed, except optional rembg).

* Lanczos upscaling (fallback when no Real-ESRGAN model is installed)
* Resize / crop / pad to aspect ratios and social media formats
* Text overlays (thumbnails, social posts) with automatic contrast panel
* Colour palette extraction and palette swatch rendering (brand work)
* Contact sheets (variant overviews)
* Background removal via rembg (optional dependency: pip install ".[rembg]")
"""

from __future__ import annotations

import asyncio
import colorsys
import importlib.util
import math
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from pydantic import BaseModel, Field

from backend.core.errors import CapabilityNotSupportedError, ValidationError
from backend.core.fonts import find_font
from backend.jobs.context import JobContext

from .base import (
    Capability,
    GenerationResult,
    ImageProvider,
    ModelInfo,
    ProviderHealth,
    RemoveBackgroundRequest,
    UpscaleRequest,
)

SOCIAL_FORMATS: dict[str, tuple[int, int]] = {
    "instagram_post": (1080, 1080),
    "instagram_portrait": (1080, 1350),
    "instagram_story": (1080, 1920),
    "tiktok": (1080, 1920),
    "youtube_thumbnail": (1280, 720),
    "youtube_banner": (2560, 1440),
    "x_post": (1600, 900),
    "linkedin_post": (1200, 627),
    "facebook_cover": (1640, 624),
    "pinterest_pin": (1000, 1500),
    "og_image": (1200, 630),
}


class ResizeImageRequest(BaseModel):
    source: str
    format_preset: str | None = Field(None, description=f"One of {sorted(SOCIAL_FORMATS)}")
    width: int | None = Field(None, ge=16, le=8192)
    height: int | None = Field(None, ge=16, le=8192)
    mode: Literal["crop", "pad", "blur", "stretch"] = "crop"
    pad_color: str = Field("#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    output_format: Literal["png", "jpg", "webp"] = "png"


class TextOverlayRequest(BaseModel):
    source: str
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(None, max_length=200)
    position: Literal["top", "center", "bottom", "left", "right"] = "bottom"
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field("#FACC15", pattern=r"^#[0-9A-Fa-f]{6}$")
    panel: bool = True
    font_scale: float = Field(1.0, ge=0.3, le=3.0)
    uppercase: bool = False
    stroke: bool = True


class PaletteRequest(BaseModel):
    source: str | None = None
    base_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    count: int = Field(5, ge=2, le=12)
    harmony: Literal["analogous", "complementary", "triadic", "split", "monochrome"] = "analogous"


class ContactSheetRequest(BaseModel):
    sources: list[str] = Field(min_length=1, max_length=64)
    columns: int = Field(3, ge=1, le=8)
    cell: int = Field(384, ge=64, le=1024)
    labels: list[str] | None = None
    background: str = Field("#111827", pattern=r"^#[0-9A-Fa-f]{6}$")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        c2 = c / 255
        return c2 / 12.92 if c2 <= 0.03928 else ((c2 + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def harmony_palette(base: str, harmony: str, count: int) -> list[str]:
    r, g, b = (c / 255 for c in hex_to_rgb(base))
    h, light, s = colorsys.rgb_to_hls(r, g, b)
    offsets = {
        "analogous": [0, 1 / 12, -1 / 12, 2 / 12, -2 / 12],
        "complementary": [0, 0.5, 0, 0.5, 0],
        "triadic": [0, 1 / 3, 2 / 3, 0, 1 / 3],
        "split": [0, 5 / 12, 7 / 12, 0, 5 / 12],
        "monochrome": [0, 0, 0, 0, 0],
    }[harmony]
    lights = [light, min(0.92, light + 0.25), max(0.12, light - 0.22), min(0.97, light + 0.4), max(0.06, light - 0.35)]
    out = []
    for i in range(count):
        hh = (h + offsets[i % len(offsets)]) % 1.0
        ll = lights[i % len(lights)] if harmony == "monochrome" or i >= len(offsets) else (light if i < 3 else lights[i % 5])
        ss = s if i < 3 else max(0.1, s * 0.6)
        rr, gg, bb = colorsys.hls_to_rgb(hh, ll, ss)
        out.append(rgb_to_hex((int(rr * 255), int(gg * 255), int(bb * 255))))
    return out


def extract_palette(path: Path, count: int) -> list[dict[str, Any]]:
    with Image.open(path) as im:
        small = im.convert("RGB").resize((200, 200))
        quant = small.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
        palette = quant.getpalette() or []
        counts = sorted(quant.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    out = []
    for c, idx in counts[:count]:
        rgb = tuple(palette[idx * 3: idx * 3 + 3])
        out.append({"hex": rgb_to_hex(rgb), "rgb": list(rgb), "share": round(c / total, 3)})  # type: ignore[arg-type]
    return out


def _font(size: int, style: str = "sans-bold") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font(style)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_image(im: Image.Image, size: tuple[int, int], mode: str, pad_color: str = "#000000") -> Image.Image:
    im = ImageOps.exif_transpose(im).convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    if mode == "stretch":
        return im.resize(size, Image.Resampling.LANCZOS)
    if mode == "crop":
        return ImageOps.fit(im, size, Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    fg = ImageOps.contain(im, size, Image.Resampling.LANCZOS)
    if mode == "pad":
        bg = Image.new(im.mode, size, hex_to_rgb(pad_color) + ((255,) if im.mode == "RGBA" else ()))
    else:
        bg = ImageOps.fit(im, size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(radius=max(size) // 40))
    bg.paste(fg, ((size[0] - fg.width) // 2, (size[1] - fg.height) // 2), fg if fg.mode == "RGBA" else None)
    return bg


class LocalImageToolsProvider(ImageProvider):
    def get_capabilities(self) -> set[Capability]:
        caps = {Capability.UPSCALE, Capability.RESIZE, Capability.TEXT_OVERLAY, Capability.PALETTE}
        if self.rembg_available():
            caps.add(Capability.REMOVE_BACKGROUND)
        return caps

    @staticmethod
    def rembg_available() -> bool:
        return importlib.util.find_spec("rembg") is not None

    async def health(self) -> ProviderHealth:
        detail = "Pillow verfügbar"
        detail += " · rembg installiert" if self.rembg_available() else " · rembg nicht installiert (optional)"
        return ProviderHealth(available=True, detail=detail)

    async def get_models(self) -> list[ModelInfo]:
        models = [ModelInfo(id="lanczos", name="Lanczos-Upscaling (ohne KI)", type="upscale", provider=self.name,
                            tasks=["upscale"])]
        if self.rembg_available():
            models.append(ModelInfo(id="rembg-u2net", name="rembg U²-Net", type="other", provider=self.name,
                                    tasks=["remove_background"], license="MIT/Apache-2.0", commercial_use=True))
        return models

    def _out(self, ctx: JobContext, stem: str, ext: str) -> Path:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.output_dir / f"{stem}{ext}"
        i = 1
        while path.exists():
            path = ctx.output_dir / f"{stem}_{i:03d}{ext}"
            i += 1
        return path

    async def upscale(self, req: UpscaleRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)

        def work() -> Path:
            with Image.open(src) as im:
                out = im.resize((round(im.width * req.scale), round(im.height * req.scale)), Image.Resampling.LANCZOS)
                out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
                path = self._out(ctx, f"{src.stem}_x{req.scale:g}", ".png")
                out.save(path)
                return path

        path = await asyncio.to_thread(work)
        return GenerationResult(files=[path], provider=self.name, model="lanczos", parameters={"scale": req.scale})

    async def remove_background(self, req: RemoveBackgroundRequest, ctx: JobContext) -> GenerationResult:
        if not self.rembg_available():
            raise CapabilityNotSupportedError(
                "Hintergrundentfernung benötigt rembg: pip install -e \".[rembg]\" (lädt beim ersten Aufruf ein Modell)."
            )
        from rembg import new_session, remove  # type: ignore

        src = Path(req.source)

        def work() -> Path:
            session = new_session(req.model)
            with Image.open(src) as im:
                out = remove(im, session=session, alpha_matting=req.alpha_matting)
            path = self._out(ctx, f"{src.stem}_nobg", ".png")
            out.save(path)
            return path

        await ctx.progress(0.1, "Hintergrund wird entfernt")
        path = await asyncio.to_thread(work)
        return GenerationResult(files=[path], provider=self.name, model=f"rembg-{req.model}", parameters=req.model_dump())

    async def resize(self, req: ResizeImageRequest, ctx: JobContext) -> GenerationResult:
        if req.format_preset:
            if req.format_preset not in SOCIAL_FORMATS:
                raise ValidationError(f"Unbekanntes Format '{req.format_preset}'", details={"formats": sorted(SOCIAL_FORMATS)})
            size = SOCIAL_FORMATS[req.format_preset]
        elif req.width and req.height:
            size = (req.width, req.height)
        else:
            raise ValidationError("format_preset oder width+height angeben")
        src = Path(req.source)

        def work() -> Path:
            with Image.open(src) as im:
                out = fit_image(im, size, req.mode, req.pad_color)
            ext = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}[req.output_format]
            path = self._out(ctx, f"{src.stem}_{req.format_preset or f'{size[0]}x{size[1]}'}", ext)
            if ext == ".jpg":
                out = out.convert("RGB")
                out.save(path, quality=92)
            else:
                out.save(path)
            return path

        path = await asyncio.to_thread(work)
        return GenerationResult(files=[path], provider=self.name, parameters=req.model_dump() | {"size": list(size)})

    async def text_overlay(self, req: TextOverlayRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)

        def work() -> Path:
            with Image.open(src) as base:
                im = base.convert("RGBA")
            w, h = im.size
            overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            title = req.title.upper() if req.uppercase else req.title
            size = int(min(w, h * 1.6) * 0.085 * req.font_scale)
            font = _font(size)
            sub_font = _font(max(12, int(size * 0.45)), "sans")
            horizontal = req.position in ("left", "right")
            max_w = int(w * (0.5 if horizontal else 0.88))
            lines = _wrap(draw, title, font, max_w)
            sub_lines = _wrap(draw, req.subtitle, sub_font, max_w) if req.subtitle else []
            line_h = int(size * 1.12)
            sub_h = int(size * 0.6)
            block_h = line_h * len(lines) + (sub_h * len(sub_lines) + size // 3 if sub_lines else 0)
            margin = int(min(w, h) * 0.06)
            if req.position == "top":
                y0 = margin
            elif req.position == "center":
                y0 = (h - block_h) // 2
            else:
                y0 = h - block_h - margin
            if horizontal:
                y0 = (h - block_h) // 2
            x0 = margin if req.position != "right" else w - max_w - margin
            if req.panel:
                pad = size // 2
                if horizontal:
                    box = [x0 - pad, 0, x0 + max_w + pad, h]
                else:
                    box = [0, y0 - pad, w, y0 + block_h + pad]
                draw.rectangle(box, fill=(0, 0, 0, 150))
            fill = hex_to_rgb(req.color)
            stroke_w = max(1, size // 18) if req.stroke else 0
            y = y0
            for i, line in enumerate(lines):
                lw = draw.textlength(line, font=font)
                x = x0 if horizontal else (w - lw) / 2
                color = hex_to_rgb(req.accent) if (i == 0 and len(lines) > 1) else fill
                draw.text((x, y), line, font=font, fill=color, stroke_width=stroke_w, stroke_fill=(0, 0, 0))
                y += line_h
            if sub_lines:
                y += size // 3
                for line in sub_lines:
                    lw = draw.textlength(line, font=sub_font)
                    x = x0 if horizontal else (w - lw) / 2
                    draw.text((x, y), line, font=sub_font, fill=fill)
                    y += sub_h
            out = Image.alpha_composite(im, overlay).convert("RGB")
            path = self._out(ctx, f"{src.stem}_text", ".png")
            out.save(path)
            return path

        path = await asyncio.to_thread(work)
        return GenerationResult(files=[path], provider=self.name, parameters=req.model_dump())

    async def palette(self, req: PaletteRequest, ctx: JobContext) -> GenerationResult:
        if req.source:
            colors = await asyncio.to_thread(extract_palette, Path(req.source), req.count)
            hexes = [c["hex"] for c in colors]
        elif req.base_color:
            hexes = harmony_palette(req.base_color, req.harmony, req.count)
            colors = [{"hex": hx, "rgb": list(hex_to_rgb(hx))} for hx in hexes]
        else:
            raise ValidationError("source (Bild) oder base_color angeben")
        white, black = (255, 255, 255), (0, 0, 0)
        for c in colors:
            rgb = tuple(c["rgb"])
            c["contrast_white"] = contrast_ratio(rgb, white)  # type: ignore[arg-type]
            c["contrast_black"] = contrast_ratio(rgb, black)  # type: ignore[arg-type]
            c["text_color"] = "#FFFFFF" if c["contrast_white"] >= c["contrast_black"] else "#000000"
            c["wcag_aa_text"] = max(c["contrast_white"], c["contrast_black"]) >= 4.5

        def swatch() -> Path:
            cw, ch = 240, 300
            img = Image.new("RGB", (cw * len(hexes), ch), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            font = _font(22, "mono")
            for i, c in enumerate(colors):
                draw.rectangle([i * cw, 0, (i + 1) * cw, ch], fill=tuple(c["rgb"]))
                draw.text((i * cw + 16, ch - 44), c["hex"], fill=hex_to_rgb(c["text_color"]), font=font)
            path = self._out(ctx, "palette", ".png")
            img.save(path)
            return path

        path = await asyncio.to_thread(swatch)
        return GenerationResult(files=[path], provider=self.name, parameters=req.model_dump(), metadata={"colors": colors})

    async def contact_sheet(self, req: ContactSheetRequest, ctx: JobContext) -> GenerationResult:
        def work() -> Path:
            cols = min(req.columns, len(req.sources))
            rows = math.ceil(len(req.sources) / cols)
            label_h = 36 if req.labels else 0
            gap = 12
            sheet = Image.new("RGB", (cols * (req.cell + gap) + gap, rows * (req.cell + label_h + gap) + gap),
                              hex_to_rgb(req.background))
            draw = ImageDraw.Draw(sheet)
            font = _font(18, "sans")
            for i, src in enumerate(req.sources):
                with Image.open(src) as im:
                    thumb = ImageOps.contain(im.convert("RGB"), (req.cell, req.cell))
                cx = gap + (i % cols) * (req.cell + gap)
                cy = gap + (i // cols) * (req.cell + label_h + gap)
                sheet.paste(thumb, (cx + (req.cell - thumb.width) // 2, cy + (req.cell - thumb.height) // 2))
                if req.labels and i < len(req.labels):
                    draw.text((cx, cy + req.cell + 6), req.labels[i][:40], fill=(230, 230, 230), font=font)
            path = self._out(ctx, "contact_sheet", ".png")
            sheet.save(path)
            return path

        path = await asyncio.to_thread(work)
        return GenerationResult(files=[path], provider=self.name, parameters={"count": len(req.sources)})
