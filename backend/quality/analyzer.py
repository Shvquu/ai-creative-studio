"""Automated media quality control.

Image checks (numpy, no OpenCV needed):
  resolution, aspect ratio, sharpness (variance of Laplacian), exposure (mean,
  clipped highlights/shadows), contrast, saturation, noise (Immerkær sigma),
  near-uniform/blank detection, alpha usage.

Video checks (ffprobe + ffmpeg filters + sampled frames):
  codec/container, resolution, fps, duration, audio presence, black segments,
  frozen segments, per-frame sharpness, brightness flicker, expectation matching.

Each check produces an ``issue`` with severity (info|warning|error); the score
starts at 100 and is reduced per issue. Thresholds are deliberately documented
so results are explainable.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from backend.core.errors import ValidationError
from backend.core.media import kind_for, probe_media

Severity = Literal["info", "warning", "error"]
_PENALTY = {"info": 0, "warning": 10, "error": 30}

RESOLUTION_PRESETS: dict[str, dict[str, Any]] = {
    "youtube_thumbnail": {"width": 1280, "height": 720, "aspect": "16:9", "max_mb": 2},
    "youtube_1080p": {"width": 1920, "height": 1080, "aspect": "16:9"},
    "youtube_4k": {"width": 3840, "height": 2160, "aspect": "16:9"},
    "instagram_post": {"width": 1080, "height": 1080, "aspect": "1:1"},
    "instagram_portrait": {"width": 1080, "height": 1350, "aspect": "4:5"},
    "instagram_story": {"width": 1080, "height": 1920, "aspect": "9:16"},
    "reels": {"width": 1080, "height": 1920, "aspect": "9:16"},
    "tiktok": {"width": 1080, "height": 1920, "aspect": "9:16"},
    "x_post": {"width": 1600, "height": 900, "aspect": "16:9"},
    "linkedin_post": {"width": 1200, "height": 627, "aspect": "1.91:1"},
    "og_image": {"width": 1200, "height": 630, "aspect": "1.91:1"},
    "print_a4_300dpi": {"width": 2480, "height": 3508, "aspect": "1:1.414"},
    "logo": {"width": 1024, "height": 1024, "aspect": "1:1"},
}


class Issue(BaseModel):
    check: str
    severity: Severity
    message: str
    value: Any = None


class QualityReport(BaseModel):
    path: str
    kind: str
    score: int
    passed: bool
    metrics: dict[str, Any] = {}
    issues: list[Issue] = []
    analyzed_at: str = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    def summary(self) -> str:
        if not self.issues:
            return f"OK ({self.score}/100)"
        worst = max(self.issues, key=lambda i: _PENALTY[i.severity])
        return f"{self.score}/100 – {worst.message}"


def _score(issues: list[Issue]) -> int:
    return max(0, 100 - sum(_PENALTY[i.severity] for i in issues))


def _parse_aspect(value: str) -> float:
    a, b = value.split(":")
    return float(a) / float(b)


# ----------------------------------------------------------------------------
# Image metrics
# ----------------------------------------------------------------------------

def _laplacian_var(gray: np.ndarray) -> float:
    g = gray.astype(np.float32)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def _noise_sigma(gray: np.ndarray) -> float:
    """Immerkær (1996) fast noise variance estimation."""
    g = gray.astype(np.float32)
    h, w = g.shape
    if h < 3 or w < 3:
        return 0.0
    m = (g[:-2, :-2] - 2 * g[:-2, 1:-1] + g[:-2, 2:]
         - 2 * g[1:-1, :-2] + 4 * g[1:-1, 1:-1] - 2 * g[1:-1, 2:]
         + g[2:, :-2] - 2 * g[2:, 1:-1] + g[2:, 2:])
    sigma = np.sum(np.abs(m)) * math.sqrt(0.5 * math.pi) / (6 * (w - 2) * (h - 2))
    return float(sigma)


def image_metrics(im: Image.Image, max_side: int = 1024) -> dict[str, Any]:
    im = ImageOps.exif_transpose(im)
    has_alpha = "A" in im.getbands()
    alpha_mean = None
    if has_alpha:
        alpha = np.asarray(im.getchannel("A"), dtype=np.float32) / 255
        alpha_mean = float(alpha.mean())
    rgb = im.convert("RGB")
    if max(rgb.size) > max_side:
        rgb = rgb.copy()
        rgb.thumbnail((max_side, max_side))
    arr = np.asarray(rgb, dtype=np.float32)
    gray = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    hsv = np.asarray(rgb.convert("HSV"), dtype=np.float32)
    # Images are measured at <= max_side so sharpness values are comparable across resolutions.
    return {
        "sharpness": round(_laplacian_var(gray), 1),
        "brightness": round(float(gray.mean()), 1),
        "contrast": round(float(gray.std()), 1),
        "clipped_highlights_pct": round(float((gray >= 250).mean() * 100), 2),
        "clipped_shadows_pct": round(float((gray <= 5).mean() * 100), 2),
        "saturation": round(float(hsv[..., 1].mean()), 1),
        "noise_sigma": round(_noise_sigma(gray), 2),
        "unique_colors_sample": int(len(np.unique(arr[::8, ::8].reshape(-1, 3).astype(np.uint8), axis=0))),
        "has_alpha": has_alpha,
        "alpha_coverage": round(alpha_mean, 3) if alpha_mean is not None else None,
    }


def analyze_image_file(
    path: Path,
    *,
    min_width: int | None = None,
    min_height: int | None = None,
    expected_aspect: str | None = None,
    min_sharpness: float = 40.0,
    purpose: str | None = None,
) -> QualityReport:
    issues: list[Issue] = []
    with Image.open(path) as im:
        width, height = im.size
        fmt = im.format
        metrics = image_metrics(im)
    metrics.update({"width": width, "height": height, "megapixels": round(width * height / 1e6, 2), "format": fmt,
                    "aspect_ratio": round(width / height, 4), "file_size_kb": round(path.stat().st_size / 1024, 1)})

    if min_width and width < min_width or min_height and height < min_height:
        issues.append(Issue(check="resolution", severity="error",
                            message=f"Auflösung {width}×{height} unter Minimum {min_width or '-'}×{min_height or '-'}",
                            value=[width, height]))
    elif max(width, height) < 512:
        issues.append(Issue(check="resolution", severity="warning", message=f"Geringe Auflösung ({width}×{height})",
                            value=[width, height]))
    if expected_aspect:
        target = _parse_aspect(expected_aspect)
        if abs(width / height - target) / target > 0.02:
            issues.append(Issue(check="aspect_ratio", severity="error",
                                message=f"Seitenverhältnis {width / height:.3f} statt {expected_aspect}", value=width / height))

    is_graphic = purpose in ("logo", "icon", "graphic") or metrics["unique_colors_sample"] < 64
    if metrics["contrast"] < 4 and metrics["unique_colors_sample"] < 8:
        issues.append(Issue(check="blank", severity="error", message="Bild ist (nahezu) einfarbig/leer",
                            value=metrics["contrast"]))
    elif not is_graphic and metrics["sharpness"] < min_sharpness:
        issues.append(Issue(check="sharpness", severity="warning",
                            message=f"Unscharf (Laplace-Varianz {metrics['sharpness']} < {min_sharpness})",
                            value=metrics["sharpness"]))
    if metrics["brightness"] < 35 and not is_graphic:
        issues.append(Issue(check="exposure", severity="warning", message="Sehr dunkel (unterbelichtet)",
                            value=metrics["brightness"]))
    elif metrics["brightness"] > 225 and not is_graphic:
        issues.append(Issue(check="exposure", severity="warning", message="Sehr hell (überbelichtet)",
                            value=metrics["brightness"]))
    if metrics["clipped_highlights_pct"] > 8 and not is_graphic:
        issues.append(Issue(check="clipping", severity="warning",
                            message=f"{metrics['clipped_highlights_pct']} % ausgefressene Lichter",
                            value=metrics["clipped_highlights_pct"]))
    if metrics["clipped_shadows_pct"] > 15 and not is_graphic:
        issues.append(Issue(check="clipping", severity="info",
                            message=f"{metrics['clipped_shadows_pct']} % abgesoffene Schatten",
                            value=metrics["clipped_shadows_pct"]))
    if metrics["contrast"] < 18 and not is_graphic and metrics["unique_colors_sample"] >= 8:
        issues.append(Issue(check="contrast", severity="info", message="Geringer Kontrast (flaues Bild)",
                            value=metrics["contrast"]))
    if metrics["noise_sigma"] > 12:
        issues.append(Issue(check="noise", severity="warning", message=f"Starkes Bildrauschen (σ≈{metrics['noise_sigma']})",
                            value=metrics["noise_sigma"]))
    if purpose == "logo" and not metrics["has_alpha"]:
        issues.append(Issue(check="transparency", severity="info",
                            message="Logo ohne Transparenz – für flexible Nutzung PNG mit Alpha empfehlen"))

    score = _score(issues)
    return QualityReport(path=str(path), kind="image", score=score,
                         passed=score >= 60 and not any(i.severity == "error" for i in issues),
                         metrics=metrics, issues=issues)


def validate_resolution(width: int, height: int, *, preset: str | None = None, min_width: int | None = None,
                        min_height: int | None = None, aspect: str | None = None, exact: bool = False) -> dict[str, Any]:
    target: dict[str, Any] = {}
    if preset:
        if preset not in RESOLUTION_PRESETS:
            raise ValidationError(f"Unbekanntes Preset '{preset}'", details={"presets": sorted(RESOLUTION_PRESETS)})
        target = RESOLUTION_PRESETS[preset]
    tw = min_width or target.get("width")
    th = min_height or target.get("height")
    ta = aspect or target.get("aspect")
    problems = []
    if exact and tw and th and (width, height) != (tw, th):
        problems.append(f"erwartet exakt {tw}×{th}, ist {width}×{height}")
    else:
        if tw and width < tw:
            problems.append(f"Breite {width} < {tw}")
        if th and height < th:
            problems.append(f"Höhe {height} < {th}")
    if ta:
        expected = _parse_aspect(ta)
        if abs(width / height - expected) / expected > 0.02:
            problems.append(f"Seitenverhältnis {width / height:.3f} statt {ta} ({expected:.3f})")
    return {"valid": not problems, "width": width, "height": height, "preset": preset,
            "target": {"width": tw, "height": th, "aspect": ta, "exact": exact}, "problems": problems}


# ----------------------------------------------------------------------------
# Analyzer (async, uses FFmpeg for video)
# ----------------------------------------------------------------------------

class QualityAnalyzer:
    def __init__(self, ffmpeg_provider: Any, min_sharpness: float = 40.0, min_score: int = 60) -> None:
        self.ff = ffmpeg_provider
        self.min_sharpness = min_sharpness
        self.min_score = min_score

    async def analyze(self, path: Path, **expect: Any) -> QualityReport:
        kind = kind_for(path)
        if kind == "image":
            return await asyncio.to_thread(analyze_image_file, path, min_sharpness=self.min_sharpness,
                                           **{k: v for k, v in expect.items() if k in
                                              ("min_width", "min_height", "expected_aspect", "purpose")})
        if kind == "video":
            return await self.analyze_video(path, **expect)
        info = await probe_media(path)
        return QualityReport(path=str(path), kind=kind, score=100, passed=True, metrics=info.model_dump(exclude={"raw"}))

    async def analyze_video(
        self,
        path: Path,
        *,
        expected_fps: float | None = None,
        expected_duration_s: float | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        expected_aspect: str | None = None,
        require_audio: bool = False,
        sample_frames: int = 8,
        **_: Any,
    ) -> QualityReport:
        info = await self.ff.get_info(path)
        issues: list[Issue] = []
        metrics: dict[str, Any] = {k: v for k, v in info.model_dump(exclude={"raw"}).items() if v is not None}
        w, h = info.width or 0, info.height or 0
        if not info.video_codec:
            issues.append(Issue(check="stream", severity="error", message="Kein Videostream gefunden"))
        if info.pixel_format and info.pixel_format not in ("yuv420p", "yuvj420p") and info.video_codec == "h264":
            issues.append(Issue(check="compatibility", severity="info",
                                message=f"Pixelformat {info.pixel_format} – für maximale Kompatibilität yuv420p"))
        if min_width and w < min_width or min_height and h < min_height:
            issues.append(Issue(check="resolution", severity="error", message=f"Auflösung {w}×{h} zu gering"))
        if expected_aspect and h:
            target = _parse_aspect(expected_aspect)
            if abs(w / h - target) / target > 0.02:
                issues.append(Issue(check="aspect_ratio", severity="error", message=f"Seitenverhältnis {w}:{h} ≠ {expected_aspect}"))
        if expected_fps and info.fps and abs(info.fps - expected_fps) > 0.5:
            issues.append(Issue(check="fps", severity="warning", message=f"{info.fps} fps statt {expected_fps}"))
        if expected_duration_s and info.duration_s and abs(info.duration_s - expected_duration_s) > max(0.5, expected_duration_s * 0.05):
            issues.append(Issue(check="duration", severity="warning",
                                message=f"Dauer {info.duration_s:.2f} s statt {expected_duration_s:.2f} s"))
        if require_audio and not info.has_audio:
            issues.append(Issue(check="audio", severity="error", message="Keine Audiospur"))
        if info.duration_s and info.duration_s < 0.5:
            issues.append(Issue(check="duration", severity="warning", message="Video kürzer als 0,5 s"))

        detect = await self.ff.detect(path, black=True, freeze=True)
        black_total = sum(seg.get("black_duration", 0) for seg in detect["black_segments"])
        freeze_total = sum(seg.get("duration", 0) for seg in detect["freeze_segments"])
        metrics["black_seconds"] = round(black_total, 2)
        metrics["frozen_seconds"] = round(freeze_total, 2)
        dur = info.duration_s or 0
        if dur and black_total / dur > 0.5:
            issues.append(Issue(check="black_frames", severity="error", message=f"{black_total:.1f} s schwarzes Bild"))
        elif black_total > 0.5:
            issues.append(Issue(check="black_frames", severity="warning", message=f"{black_total:.1f} s schwarze Frames"))
        if dur and freeze_total / dur > 0.6:
            issues.append(Issue(check="frozen", severity="warning",
                                message=f"Video steht {freeze_total:.1f} s still (Standbild statt Bewegung?)"))

        frame_metrics = await self._sample_frames(path, sample_frames, dur)
        if frame_metrics:
            sharp = [m["sharpness"] for m in frame_metrics]
            bright = [m["brightness"] for m in frame_metrics]
            metrics["frame_sharpness_mean"] = round(float(np.mean(sharp)), 1)
            metrics["frame_sharpness_min"] = round(float(np.min(sharp)), 1)
            metrics["brightness_mean"] = round(float(np.mean(bright)), 1)
            flicker = float(np.mean(np.abs(np.diff(bright)))) if len(bright) > 1 else 0.0
            metrics["brightness_flicker"] = round(flicker, 2)
            metrics["sampled_frames"] = len(frame_metrics)
            if metrics["frame_sharpness_mean"] < self.min_sharpness * 0.6:
                issues.append(Issue(check="sharpness", severity="warning",
                                    message=f"Frames unscharf (Ø Laplace-Varianz {metrics['frame_sharpness_mean']})"))
            if flicker > 25 and len(bright) >= 4:
                issues.append(Issue(check="flicker", severity="warning",
                                    message=f"Starke Helligkeitssprünge zwischen Frames (Ø {flicker:.1f})"))
        score = _score(issues)
        return QualityReport(path=str(path), kind="video", score=score,
                             passed=score >= self.min_score and not any(i.severity == "error" for i in issues),
                             metrics=metrics, issues=issues)

    async def _sample_frames(self, path: Path, count: int, duration: float) -> list[dict[str, Any]]:
        if not duration or count <= 0:
            return []
        from backend.jobs.context import JobContext
        from backend.providers.ffmpeg import ExtractFramesRequest

        tmp = Path(tempfile.mkdtemp(prefix="acs_qc_"))
        try:
            res = await self.ff.extract_frames(ExtractFramesRequest(source=str(path), count=count, format="png"),
                                               JobContext.detached(tmp))

            def measure() -> list[dict[str, Any]]:
                out = []
                for f in res.files:
                    with Image.open(f) as im:
                        out.append(image_metrics(im, max_side=640))
                return out

            return await asyncio.to_thread(measure)
        except Exception:
            return []
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def report_markdown(reports: list[QualityReport], title: str = "Qualitätsbericht") -> str:
        lines = [f"# {title}", "", f"Erstellt: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
                 "| Datei | Typ | Score | Status | Wichtigster Befund |", "|---|---|---:|---|---|"]
        for r in reports:
            worst = max(r.issues, key=lambda i: _PENALTY[i.severity]).message if r.issues else "–"
            lines.append(f"| {Path(r.path).name} | {r.kind} | {r.score} | {'✅' if r.passed else '❌'} | {worst} |")
        for r in reports:
            lines += ["", f"## {Path(r.path).name}", "", f"- Score: **{r.score}/100** ({'bestanden' if r.passed else 'nicht bestanden'})"]
            for k, v in r.metrics.items():
                if k in ("path",):
                    continue
                lines.append(f"- {k}: `{v}`")
            if r.issues:
                lines += ["", "**Befunde:**"]
                lines += [f"- [{i.severity}] {i.message}" for i in r.issues]
        return "\n".join(lines) + "\n"

    @staticmethod
    def report_json(reports: list[QualityReport]) -> str:
        return json.dumps([r.model_dump() for r in reports], indent=2, ensure_ascii=False, default=str)
