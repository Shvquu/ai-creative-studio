"""Prompt building: style presets, negative-prompt presets and camera vocabulary.

Claude (the creative director) writes the creative prompt. This module adds the
*technical* parts that depend on the model family so results are consistent:
style keywords, sensible negatives (only for families that use them) and
camera-movement phrases for video models.
"""

from __future__ import annotations

from typing import Any

STYLE_PRESETS: dict[str, dict[str, str]] = {
    "photorealistic": {
        "label": "Fotorealistisch",
        "positive": "photorealistic, natural lighting, sharp focus, high detail, 35mm photograph",
        "negative": "illustration, painting, cartoon, cgi, blurry, oversaturated",
    },
    "cinematic": {
        "label": "Cinematisch",
        "positive": "cinematic still, dramatic lighting, anamorphic lens, shallow depth of field, color graded, film grain",
        "negative": "flat lighting, amateur, snapshot, overexposed",
    },
    "product": {
        "label": "Produktfotografie",
        "positive": "professional product photography, studio softbox lighting, clean seamless background, "
                    "crisp reflections, commercial advertising shot, centered composition",
        "negative": "clutter, busy background, hands, text, watermark, distorted product",
    },
    "logo-flat": {
        "label": "Logo (flach, vektorartig)",
        "positive": "minimalist flat vector logo, simple geometric shapes, bold clean lines, centered on plain white "
                    "background, high contrast, brand identity design",
        "negative": "photo, 3d render, gradient mess, realistic texture, many colors, small details, text artifacts",
    },
    "logo-3d": {
        "label": "Logo (3D, glänzend)",
        "positive": "3d logo emblem, glossy material, soft studio lighting, centered, plain background, brand mark",
        "negative": "photo background, clutter, text artifacts",
    },
    "isometric": {
        "label": "Isometrisch",
        "positive": "isometric 3d illustration, clean soft shading, pastel colors, miniature diorama",
        "negative": "perspective distortion, photo, noise",
    },
    "illustration": {
        "label": "Illustration",
        "positive": "detailed digital illustration, clean linework, vibrant harmonious colors",
        "negative": "photo, blurry, low quality",
    },
    "anime": {
        "label": "Anime",
        "positive": "anime style key visual, cel shading, vibrant colors, detailed background",
        "negative": "photorealistic, 3d, blurry",
    },
    "watercolor": {
        "label": "Aquarell",
        "positive": "watercolor painting, soft washes, paper texture, delicate brush strokes",
        "negative": "photo, digital, harsh edges",
    },
    "3d-render": {
        "label": "3D-Render",
        "positive": "high quality 3d render, octane, global illumination, physically based materials",
        "negative": "2d, flat, sketch",
    },
    "social-bold": {
        "label": "Social Media (plakativ)",
        "positive": "bold eye-catching composition, vibrant saturated colors, strong subject separation, "
                    "clean negative space for text",
        "negative": "cluttered, low contrast, dull",
    },
    "thumbnail": {
        "label": "YouTube-Thumbnail",
        "positive": "high impact youtube thumbnail background, dramatic contrast, vivid colors, clear focal subject, "
                    "large empty area on one side for title text",
        "negative": "text, letters, watermark, clutter, low contrast",
    },
}

NEGATIVE_BASE: dict[str, str] = {
    "sd15": "lowres, bad anatomy, bad hands, extra fingers, deformed, blurry, jpeg artifacts, watermark, signature, text",
    "sdxl": "lowres, deformed, blurry, jpeg artifacts, watermark, signature, text",
}

CAMERA_MOVES: dict[str, str] = {
    "static": "static camera, locked-off shot",
    "dolly-in": "the camera slowly dollies in towards the subject",
    "dolly-out": "the camera slowly pulls back revealing the scene",
    "pan-left": "the camera pans smoothly to the left",
    "pan-right": "the camera pans smoothly to the right",
    "orbit": "the camera orbits slowly around the subject",
    "tilt-up": "the camera tilts up",
    "crane-up": "a crane shot rising upwards over the scene",
    "tracking": "tracking shot following the subject",
    "handheld": "subtle handheld camera movement",
    "zoom-in": "slow zoom in",
}


def build_prompt(prompt: str, *, style: str | None = None, family: str | None = None,
                 negative: str = "", supports_negative: bool = True) -> dict[str, Any]:
    """Combine the creative prompt with style keywords and family-appropriate negatives."""
    positive = prompt.strip()
    neg_parts: list[str] = [negative.strip()] if negative.strip() else []
    applied_style = None
    if style:
        preset = STYLE_PRESETS.get(style)
        if preset is None:
            raise ValueError(f"Unknown style '{style}'. Available: {', '.join(sorted(STYLE_PRESETS))}")
        positive = f"{positive}, {preset['positive']}"
        neg_parts.append(preset["negative"])
        applied_style = style
    if supports_negative and family in NEGATIVE_BASE:
        neg_parts.append(NEGATIVE_BASE[family])
    negative_out = ", ".join(p for p in neg_parts if p) if supports_negative else ""
    return {"prompt": positive, "negative_prompt": negative_out, "style": applied_style}


def camera_phrase(move: str | None) -> str | None:
    if not move:
        return None
    return CAMERA_MOVES.get(move, move)
