"""Brand identity helpers: typography pairings and brand-guideline documents (HTML + Markdown)."""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Open-licensed (SIL OFL / Apache) Google Fonts – free for commercial use.
TYPE_PAIRINGS: list[dict[str, Any]] = [
    {"id": "modern-tech", "heading": "Space Grotesk", "body": "Inter", "mood": ["modern", "tech", "startup", "clean"]},
    {"id": "editorial", "heading": "Playfair Display", "body": "Source Sans 3", "mood": ["elegant", "editorial", "luxury", "fashion"]},
    {"id": "friendly", "heading": "Poppins", "body": "Open Sans", "mood": ["friendly", "approachable", "app", "education"]},
    {"id": "corporate", "heading": "Montserrat", "body": "Merriweather", "mood": ["corporate", "trust", "finance", "consulting"]},
    {"id": "bold-sport", "heading": "Bebas Neue", "body": "Roboto", "mood": ["bold", "sport", "energy", "fitness"]},
    {"id": "warm-craft", "heading": "Fraunces", "body": "Inter", "mood": ["warm", "craft", "food", "organic"]},
    {"id": "minimal-swiss", "heading": "Inter", "body": "Inter", "mood": ["minimal", "swiss", "neutral", "product"]},
    {"id": "classic-serif", "heading": "DM Serif Display", "body": "DM Sans", "mood": ["classic", "premium", "beauty", "hospitality"]},
    {"id": "playful", "heading": "Fredoka", "body": "Nunito", "mood": ["playful", "kids", "fun", "gaming"]},
    {"id": "engineering", "heading": "IBM Plex Sans", "body": "IBM Plex Serif", "mood": ["engineering", "industrial", "b2b", "science"]},
]


def suggest_typography(keywords: list[str], limit: int = 3) -> list[dict[str, Any]]:
    kws = {k.lower() for k in keywords}
    scored = sorted(TYPE_PAIRINGS, key=lambda p: -len(kws & set(p["mood"])))
    return [dict(p, license="SIL Open Font License (Google Fonts)") for p in scored[:limit]]


class BrandColor(BaseModel):
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    name: str = ""
    role: str = ""  # primary, secondary, accent, neutral, background


class BrandGuideRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=80)
    tagline: str | None = Field(None, max_length=200)
    mission: str | None = Field(None, max_length=1000)
    audience: str | None = Field(None, max_length=1000)
    positioning: str | None = Field(None, max_length=1000)
    values: list[str] = Field(default_factory=list, max_length=12)
    voice: list[str] = Field(default_factory=list, max_length=12)
    colors: list[BrandColor] = Field(default_factory=list, max_length=16)
    palette: list[str] = Field(default_factory=list, max_length=16, description="Hex colours; roles assigned automatically")
    heading_font: str = "Inter"
    body_font: str = "Inter"
    logos: list[str] = Field(default_factory=list, max_length=12, description="asset ids/paths")
    imagery: list[str] = Field(default_factory=list, max_length=12, description="example image assets")
    imagery_style: str | None = Field(None, max_length=1000)
    dos: list[str] = Field(default_factory=list, max_length=20)
    donts: list[str] = Field(default_factory=list, max_length=20)
    project: str | None = None


def _contrast(hex_a: str, hex_b: str) -> float:
    from backend.providers.image_tools import contrast_ratio, hex_to_rgb

    return contrast_ratio(hex_to_rgb(hex_a), hex_to_rgb(hex_b))


def _img_data_uri(path: Path, max_side: int = 900) -> str:
    from io import BytesIO

    from PIL import Image

    with Image.open(path) as im:
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def render_brand_guide(req: BrandGuideRequest, logo_paths: list[Path], image_paths: list[Path]) -> tuple[str, str]:
    """Return (html, markdown). HTML is self-contained (images embedded) and works offline."""
    e = html.escape
    colors = list(req.colors)
    if not colors and req.palette:
        roles = ["primary", "secondary", "accent", "neutral", "background"]
        colors = [BrandColor(hex=h, role=roles[i] if i < len(roles) else "extra", name=roles[i].capitalize() if i < len(roles) else "")
                  for i, h in enumerate(req.palette)]
    primary = next((c.hex for c in colors if c.role == "primary"), colors[0].hex if colors else "#111827")
    md = [f"# {req.brand_name} – Brand Guidelines", ""]
    if req.tagline:
        md += [f"> {req.tagline}", ""]
    for title, value in (("Mission", req.mission), ("Zielgruppe", req.audience), ("Positionierung", req.positioning)):
        if value:
            md += [f"## {title}", "", value, ""]
    if req.values:
        md += ["## Markenwerte", ""] + [f"- {v}" for v in req.values] + [""]
    if req.voice:
        md += ["## Tonalität", ""] + [f"- {v}" for v in req.voice] + [""]
    if colors:
        md += ["## Farbpalette", "", "| Rolle | Name | Hex | Kontrast Weiß | Kontrast Schwarz |", "|---|---|---|---:|---:|"]
        for c in colors:
            md.append(f"| {c.role or '–'} | {c.name or '–'} | `{c.hex.upper()}` | {_contrast(c.hex, '#FFFFFF')} | {_contrast(c.hex, '#000000')} |")
        md += ["", "WCAG AA verlangt ≥ 4,5:1 für Fließtext und ≥ 3:1 für große Schrift.", ""]
    md += ["## Typografie", "", f"- Überschriften: **{req.heading_font}**", f"- Fließtext: **{req.body_font}**",
           "- Beide Schriften sind frei unter der SIL Open Font License verfügbar (Google Fonts).", ""]
    if logo_paths:
        md += ["## Logo", ""] + [f"- `{p.name}`" for p in logo_paths] + [
            "", "Schutzzone: mindestens die Höhe des Logo-Bildzeichens rundum freihalten. Nicht verzerren, "
                "nicht umfärben, nicht auf unruhige Hintergründe setzen.", ""]
    if req.imagery_style or image_paths:
        md += ["## Bildsprache", "", req.imagery_style or "", ""] + [f"- `{p.name}`" for p in image_paths] + [""]
    if req.dos or req.donts:
        md += ["## Do & Don't", ""] + [f"- ✅ {d}" for d in req.dos] + [f"- ❌ {d}" for d in req.donts] + [""]
    md += ["---", "Erstellt mit AI Creative Studio (lokal)."]

    def section(title: str, body: str) -> str:
        return f'<section><h2>{e(title)}</h2>{body}</section>'

    parts = []
    for title, value in (("Mission", req.mission), ("Zielgruppe", req.audience), ("Positionierung", req.positioning)):
        if value:
            parts.append(section(title, f"<p>{e(value)}</p>"))
    if req.values or req.voice:
        lists = ""
        if req.values:
            lists += "<div><h3>Werte</h3><ul>" + "".join(f"<li>{e(v)}</li>" for v in req.values) + "</ul></div>"
        if req.voice:
            lists += "<div><h3>Tonalität</h3><ul>" + "".join(f"<li>{e(v)}</li>" for v in req.voice) + "</ul></div>"
        parts.append(section("Persönlichkeit", f'<div class="cols">{lists}</div>'))
    if colors:
        sw = "".join(
            f'<div class="swatch"><div class="chip" style="background:{c.hex}"></div><b>{e(c.name or c.role or c.hex)}</b>'
            f'<code>{c.hex.upper()}</code><small>{e(c.role)} · W {_contrast(c.hex, "#FFFFFF")} · S {_contrast(c.hex, "#000000")}</small></div>'
            for c in colors)
        parts.append(section("Farbpalette", f'<div class="swatches">{sw}</div>'))
    parts.append(section("Typografie", (
        f'<p class="type-h" style="font-family:\'{e(req.heading_font)}\',sans-serif">{e(req.heading_font)} – Überschriften Aa Bb 123</p>'
        f'<p style="font-family:\'{e(req.body_font)}\',sans-serif">{e(req.body_font)} – Fließtext. Franz jagt im komplett '
        f'verwahrlosten Taxi quer durch Bayern.</p><p class="muted">Freie Schriften (SIL OFL, Google Fonts).</p>')))
    if logo_paths:
        logos = "".join(f'<figure><img src="{_img_data_uri(p)}" alt="logo"><figcaption>{e(p.name)}</figcaption></figure>' for p in logo_paths)
        parts.append(section("Logo", f'<div class="gallery logos">{logos}</div><p class="muted">Schutzzone einhalten, nicht verzerren oder umfärben.</p>'))
    if req.imagery_style or image_paths:
        imgs = "".join(f'<figure><img src="{_img_data_uri(p)}" alt=""></figure>' for p in image_paths)
        parts.append(section("Bildsprache", f"<p>{e(req.imagery_style or '')}</p><div class=\"gallery\">{imgs}</div>"))
    if req.dos or req.donts:
        dd = ('<div class="cols"><div><h3>Do</h3><ul>' + "".join(f"<li>{e(d)}</li>" for d in req.dos) +
              '</ul></div><div><h3>Don\'t</h3><ul>' + "".join(f"<li>{e(d)}</li>" for d in req.donts) + "</ul></div></div>")
        parts.append(section("Do & Don't", dd))

    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(req.brand_name)} – Brand Guidelines</title>
<style>
:root{{--primary:{primary};--ink:#111827;--muted:#6B7280;--bg:#FFFFFF;--line:#E5E7EB}}
*{{box-sizing:border-box}}body{{margin:0;font-family:'{e(req.body_font)}',Inter,'Segoe UI',Arial,sans-serif;color:var(--ink);background:var(--bg);line-height:1.55}}
header{{background:var(--primary);color:#fff;padding:72px 8vw}}header h1{{font-family:'{e(req.heading_font)}',sans-serif;font-size:clamp(36px,6vw,72px);margin:0}}
header p{{font-size:20px;opacity:.9;margin:.5em 0 0}}main{{padding:24px 8vw 64px;max-width:1200px}}section{{border-bottom:1px solid var(--line);padding:32px 0}}
h2{{font-family:'{e(req.heading_font)}',sans-serif;font-size:28px;margin:0 0 16px}}h3{{margin:0 0 8px}}.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:24px}}
.swatches{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px}}.swatch{{display:flex;flex-direction:column;gap:4px}}
.chip{{height:96px;border-radius:12px;border:1px solid var(--line)}}code{{font-size:14px}}small,.muted{{color:var(--muted)}}
.type-h{{font-size:36px;font-weight:700;margin:0 0 8px}}.gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}
figure{{margin:0}}img{{width:100%;border-radius:12px;border:1px solid var(--line);background:#F9FAFB}}.logos img{{object-fit:contain;aspect-ratio:1;padding:16px}}
figcaption{{font-size:13px;color:var(--muted)}}footer{{padding:24px 8vw;color:var(--muted);font-size:13px}}
</style></head><body><header><h1>{e(req.brand_name)}</h1>{f'<p>{e(req.tagline)}</p>' if req.tagline else ''}</header>
<main>{''.join(parts)}</main><footer>Brand Guidelines · erstellt mit AI Creative Studio (lokal, Open Source)</footer></body></html>"""
    return page, "\n".join(md) + "\n"
