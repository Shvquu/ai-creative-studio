"""Helper actions for workflows (pure data transformations, no generation)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from backend.core.errors import ValidationError
from backend.jobs.context import JobContext

if TYPE_CHECKING:  # pragma: no cover
    from backend.orchestration.studio import Studio

Action = Callable[["Studio", dict[str, Any], JobContext], Awaitable[dict[str, Any]]]

_KB_PATTERN = [
    {"zoom": "in", "pan": "none"},
    {"zoom": "out", "pan": "right"},
    {"zoom": "in", "pan": "left"},
    {"zoom": "out", "pan": "none"},
    {"zoom": "in", "pan": "up"},
]


async def util_set(studio: Studio, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """Return the (rendered) params unchanged – handy to compute values once."""
    return {**params, "assets": [], "asset_ids": [], "asset": None}


async def util_collect(studio: Studio, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """Flatten several asset-id lists into one list."""
    ids: list[str] = []
    for value in params.get("lists", []):
        for v in value if isinstance(value, list) else [value]:
            if v and v not in ids:
                ids.append(v)
    return {"asset_ids": ids, "assets": [], "asset": None, "count": len(ids)}


async def timeline_from_assets(studio: Studio, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """Build an FFmpeg render timeline (clips + subtitle cues) from images/videos.

    params: assets [ids], durations [s] | duration_s, ken_burns: alternate|in|out|none,
            captions [text], transition_duration
    """
    assets = params.get("assets") or []
    if not assets:
        raise ValidationError("timeline.from_assets: keine Assets übergeben")
    default = float(params.get("duration_s", 4.0))
    durations = [float(d) if d else default for d in (params.get("durations") or [])]
    durations += [default] * (len(assets) - len(durations))
    mode = params.get("ken_burns", "alternate")
    td = float(params.get("transition_duration", 0.6)) if params.get("transition", "fade") != "none" else 0.0
    captions = params.get("captions") or []
    clips, cues, t = [], [], 0.0
    for i, ref in enumerate(assets):
        path = studio.resolve_input(ref)
        clip: dict[str, Any] = {"source": str(ref)}
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            clip["duration_s"] = durations[i]
            if mode == "alternate":
                clip["ken_burns"] = {**_KB_PATTERN[i % len(_KB_PATTERN)], "strength": 0.12}
            elif mode in ("in", "out"):
                clip["ken_burns"] = {"zoom": mode, "pan": "none", "strength": 0.12}
            seg = durations[i]
        else:
            info = await studio.ffmpeg.get_info(path)
            seg = info.duration_s or durations[i]
        clips.append(clip)
        if i < len(captions) and captions[i]:
            start = t + (td if i else 0) + 0.2
            cues.append({"start_s": round(start, 2), "end_s": round(t + seg - 0.3, 2), "text": str(captions[i])})
        t += seg - (td if i < len(assets) - 1 else 0)
    return {"clips": clips, "subtitles": cues, "total_s": round(t, 2), "assets": [], "asset_ids": [], "asset": None}


async def brand_typography(studio: Studio, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from backend.orchestration.brand import suggest_typography

    keywords = params.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.replace(",", " ").split() if k.strip()]
    pairs = suggest_typography(keywords, int(params.get("limit", 3)))
    return {"pairings": pairs, "heading_font": pairs[0]["heading"], "body_font": pairs[0]["body"],
            "assets": [], "asset_ids": [], "asset": None}


async def prompt_build(studio: Studio, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from backend.orchestration.prompts import build_prompt

    out = build_prompt(params["prompt"], style=params.get("style"), family=params.get("family"),
                       negative=params.get("negative_prompt", ""))
    return {**out, "assets": [], "asset_ids": [], "asset": None}


HELPER_ACTIONS: dict[str, Action] = {
    "util.set": util_set,
    "util.collect": util_collect,
    "timeline.from_assets": timeline_from_assets,
    "brand.typography": brand_typography,
    "prompt.build": prompt_build,
}
